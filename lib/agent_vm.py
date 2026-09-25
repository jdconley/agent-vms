"""CLI and transport. Uses only Python's standard library on the controller."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shlex
import socket
import subprocess
import sys
import tarfile
import tempfile
import urllib.parse
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
STATE = Path("/var/lib/agent-vms")
NAME = re.compile(r"[a-z][a-z0-9-]{0,61}[a-z0-9]$|[a-z]$")
# One key per line, no authorized_keys options such as command= or from=.
PUBLIC_KEY = re.compile(r"(ssh-ed25519|ecdsa-sha2-nistp(?:256|384|521)|ssh-rsa) [A-Za-z0-9+/]+={0,3}( [A-Za-z0-9@._-]+)?")


class Error(Exception):
    pass


def log(message):
    print(message, file=sys.stderr, flush=True)


def run(argv, *, capture=False, data=None, timeout=None, check=True):
    try:
        result = subprocess.run([str(x) for x in argv], input=data,
                                stdout=subprocess.PIPE if capture else sys.stderr,
                                stderr=None, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise Error(f"Timed out after {timeout}s: {argv[0]}") from exc
    if check and result.returncode:
        raise Error(f"Command failed (exit {result.returncode}): {shlex.join([str(x) for x in argv])}")
    return result.stdout.decode() if capture and check else result


def cloud_config(name, public_key):
    return "#cloud-config\n" + json.dumps({
        "hostname": name, "manage_etc_hosts": True,
        "users": [{"name": "agent", "groups": "sudo", "shell": "/bin/bash",
                   "sudo": "ALL=(ALL) NOPASSWD:ALL", "lock_passwd": True,
                   "ssh_authorized_keys": [public_key.strip()]}],
        "ssh_pwauth": False, "disable_root": True,
    }, indent=2) + "\n"


def read_state(directory):
    try:
        state = json.loads((directory / "state.json").read_text())
        if (state["name"] != directory.name or state.get("managed_by") != "agent-vms"
                or Path(state["disk"]) != directory / "disk.qcow2"
                or not NAME.fullmatch(state["name"])):
            raise ValueError("ownership or disk path mismatch")
        return state
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise Error(f"Invalid or missing managed state at {directory}: {exc}") from exc


def write_state(directory, state):
    temporary = directory / "state.json.tmp"
    temporary.write_text(json.dumps(state, indent=2) + "\n")
    temporary.chmod(0o600)
    temporary.replace(directory / "state.json")


def source_archive():
    """Explicit source allowlist: never transfer ignored configs, keys or .git."""
    files = [ROOT / "agent-vm", ROOT / "versions.env"]
    for directory, pattern in (("lib", "*.py"), ("setup", "*.sh"), ("scripts", "record-*")):
        files.extend(sorted((ROOT / directory).glob(pattern)))
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w:gz") as archive:
        for path in files:
            if path.is_symlink():
                raise Error(f"Refusing to transfer source symlink: {path}")
            if path.is_file():
                archive.add(path, arcname=str(path.relative_to(ROOT)), recursive=False)
    return stream.getvalue()


def ssh_base(host):
    return ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
            "-o", "ServerAliveInterval=30", "-o", "ServerAliveCountMax=3", host]


def remote(host, arguments):
    # The SSH user owns the upload and must be able to remove it after sudo.
    # Root-owned __pycache__ contents otherwise make the cleanup trap fail.
    command = shlex.join(["python3", "-B", "./agent-vm", *arguments, "--json"])
    # The remote path comes only from mktemp. Arguments are shell-quoted exactly
    # once; repository files arrive through stdin, not shell interpolation.
    script = (
        "set -eu; command -v python3 >/dev/null || { echo 'Install python3 on the Ubuntu host first.' >&2; exit 1; }; "
        "work=$(mktemp -d); trap 'rm -rf \"$work\"' EXIT; "
        "tar -xzf - -C \"$work\"; cd \"$work\"; "
        f"if [ \"$(id -u)\" = 0 ]; then {command}; else sudo -n {command}; fi"
    )
    result = run([*ssh_base(host), script], capture=True, data=source_archive(), check=False)
    # The remote CLI and ssh already explained the failure on stderr.
    if result.returncode == 255:
        raise Error(f"Could not connect to {host} over SSH (exit 255); see the SSH message above.")
    if result.returncode:
        raise Error(f"{host} reported an error (exit {result.returncode}); see the message above.")
    try:
        return json.loads(result.stdout.decode())
    except ValueError as exc:
        raise Error("Remote host did not return valid JSON. Check its shell startup output.") from exc


def free_port(preferred=3773):
    with socket.socket() as sock:
        try:
            sock.bind(("127.0.0.1", preferred))
        except OSError:
            sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def start_tunnel(argv):
    # ProxyCommand/ProxyJump children can outlive ssh -f and inherit the caller's
    # output pipes. Keep every background descriptor off the CLI's JSON stream.
    with tempfile.TemporaryFile() as diagnostic:
        try:
            result = subprocess.run([str(x) for x in argv], stdin=subprocess.DEVNULL,
                                    stdout=diagnostic, stderr=diagnostic, timeout=30,
                                    start_new_session=True)
        except subprocess.TimeoutExpired as exc:
            raise Error("Timed out starting the SSH tunnel. Check SSH connectivity and forwarding settings.") from exc
        if result.returncode:
            diagnostic.seek(0)
            log(diagnostic.read(65536).decode(errors="replace").strip())
            raise Error(f"SSH tunnel failed to start (exit {result.returncode}). Check SSH connectivity and forwarding settings.")


def local_tunnel(host, port, name):
    directory = Path.home() / ".local/state/agent-vms/tunnels"
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    identity = hashlib.sha256(f"{host}:{name}".encode()).hexdigest()[:16]
    control = directory / identity
    # A repeated connect replaces this tool's old tunnel, not other SSH sessions.
    if control.exists():
        run([*ssh_base(host)[:-1], "-S", control, "-O", "exit", host], check=False)
    local_port = free_port()
    start_tunnel([*ssh_base(host)[:-1], "-M", "-S", control, "-fNT",
         "-o", "ExitOnForwardFailure=yes", "-o", "ControlPersist=no",
         "-L", f"127.0.0.1:{local_port}:127.0.0.1:{port}", host])
    # SSH can bind the local port successfully even when the server rejects
    # forwarding. Prove the full path before handing out a pairing link.
    try:
        endpoint = f"http://127.0.0.1:{local_port}/.well-known/t3/environment"
        # System/corporate proxies must not answer a loopback readiness probe.
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(endpoint, timeout=10) as response:
            environment = json.loads(response.read(65536))
            if (response.geturl() != endpoint or not isinstance(environment, dict)
                    or not environment.get("environmentId") or not environment.get("serverVersion")):
                raise ValueError("Unexpected T3 environment response")
    except (OSError, ValueError) as exc:
        run([*ssh_base(host)[:-1], "-S", control, "-O", "exit", host], check=False)
        raise Error("SSH tunnel could not reach T3. Check the server's AllowTcpForwarding and PermitOpen settings "
                    "and T3 service health; local forwarding to host loopback must be allowed.") from exc
    return local_port, f"ssh -S {shlex.quote(str(control))} -O exit {shlex.quote(host)}"


def ssh_access(args):
    """Authorize this computer for SSH as agent, for Claude Code, Codex and editors."""
    from lib import sshconfig
    if not args.host:
        raise Error("ssh-config sets up SSH on your laptop. Run it there with --host.")
    home = Path.home()
    public_key = sshconfig.ensure_key(home)
    info = remote(args.host, ["authorize", *([args.name] if args.name else []), "--public-key", public_key])
    alias = sshconfig.alias(args.name, args.host)
    sshconfig.write_entry(home, alias, info["hostname"], info["port"], args.host, info["host_key"])
    result = {"ssh": alias}
    if not sshconfig.ensure_include(home):
        result["ssh_include"] = sshconfig.include_line(home)
        return result
    try:
        run([*ssh_base(alias), "true"], timeout=60)
    except Error as exc:
        raise Error(f"Wrote SSH entry {alias}, but could not connect through it. Check that {args.host} "
                    "allows forwarding to its loopback (AllowTcpForwarding local, PermitOpen 127.0.0.1:*).") from exc
    return result


def connect(args):
    if args.host:
        info = remote(args.host, ["access", *([args.name] if args.name else [])])
        port, close = local_tunnel(args.host, info["port"], args.name or "existing")
    else:
        from lib.host import access
        info = access(args.name)
        port, close = info["port"], info.get("close", "")
    url = urllib.parse.urlsplit(info["pairing_url"])
    info["url"] = urllib.parse.urlunsplit(url._replace(netloc=f"127.0.0.1:{port}"))
    info.pop("pairing_url")
    info["disconnect"] = close
    return info


def parser():
    result = argparse.ArgumentParser(description="Install T3 Code on your own remote VMs.",
        epilog="Examples: ./agent-vm up demo --host you@kvm-host | ./agent-vm install --host ubuntu@vm")
    commands = result.add_subparsers(dest="command", required=True)
    for name, help_text in (
        ("up", "Create or resume a KVM VM and open a secure T3 tunnel"),
        ("install", "Install T3 and desktop tools into an existing Ubuntu VM"),
        ("connect", "Open a secure browser tunnel and mint a pairing link"),
        ("status", "Show VM state and service health"),
        ("list", "List this host's managed VMs"),
        ("stop", "Shut down a managed VM gracefully"),
        ("delete", "Delete a managed VM and its disk (requires --yes)"),
        ("doctor", "Check host requirements without installing software"),
        ("mobile", "Enable Tailscale HTTPS for phone access (requires tailnet sign-in)"),
        ("run", "Run a shell command as the guest's agent user"),
        ("access", "Inspect the host-local pairing endpoint"),
        ("ssh-config", "Set up SSH as agent for Claude Code, Codex and editors"),
        ("authorize", "Authorize a controller SSH key (used by ssh-config)"),
    ):
        sub = commands.add_parser(name, help=help_text)
        if name in ("up", "stop", "delete"):
            sub.add_argument("name")
        elif name in ("status", "connect", "access", "mobile", "run", "ssh-config", "authorize"):
            sub.add_argument("name", nargs="?")
        sub.add_argument("--host", help="SSH alias or user@host; omit to run on this Linux machine")
        sub.add_argument("--json", action="store_true", help="Machine-readable result; up/install skip the local tunnel and SSH entry")
        if name in ("up", "install"):
            sub.add_argument("--no-connect", action="store_true", help="Install and verify without opening a tunnel")
        if name == "up":
            sub.add_argument("--cpus", type=int, default=4)
            sub.add_argument("--memory", type=int, default=6144, help="RAM in MiB")
            sub.add_argument("--disk", type=int, default=30, help="Disk size in GiB")
        if name == "delete":
            sub.add_argument("--yes", action="store_true")
        if name == "run":
            sub.add_argument("--command", dest="guest_command", required=True, help="Shell command to execute inside the guest")
        if name == "authorize":
            sub.add_argument("--public-key", required=True)
    return result


def validate(args):
    name = getattr(args, "name", None)
    if name is not None and not NAME.fullmatch(name):
        raise Error("Instance name must be 1–63 lowercase letters, digits or hyphens, starting with a letter and ending with a letter/digit.")
    if args.host and not re.fullmatch(r"(?:[a-zA-Z0-9_][a-zA-Z0-9_.-]*@)?[a-zA-Z0-9][a-zA-Z0-9_.-]*", args.host):
        raise Error("Invalid SSH host. Use an SSH config alias or user@hostname (put ports and identity files in ~/.ssh/config).")
    if args.command == "delete" and not args.yes:
        raise Error("Deleting a VM permanently erases its disk. Repeat with --yes.")
    if args.command == "authorize" and not PUBLIC_KEY.fullmatch(args.public_key):
        raise Error("Expected one OpenSSH public key without options.")
    if args.command == "up" and not (1 <= args.cpus <= 256 and 2048 <= args.memory <= 1048576 and 15 <= args.disk <= 16384):
        raise Error("Use 1–256 CPUs, 2048–1048576 MiB RAM and 15–16384 GiB disk.")


def forwarded(args):
    """Arguments for the same command on the remote host."""
    result = [args.command]
    if getattr(args, "name", None):
        result.append(args.name)
    if args.command == "up":
        result += ["--cpus", str(args.cpus), "--memory", str(args.memory), "--disk", str(args.disk)]
    if args.command == "delete":
        result += ["--yes"]
    if args.command == "run":
        # The = form keeps a value such as --version from parsing as an option.
        result += [f"--command={args.guest_command}"]
    if args.command == "authorize":
        result += ["--public-key", args.public_key]
    return result


def report(result, args):
    if "url" in result:
        destination = "a device on your tailnet" if result.get("access") == "tailscale" else "this computer"
        print(f"\nT3 Code is ready. Open this one-time pairing link on {destination}:\n\n  {result['url']}\n")
        if result.get("access") != "tailscale":
            print("The SSH tunnel stays open in the background.")
        print("Pairing links are secrets; don't paste them into issues.")
        print("Sign in to your coding provider in T3 to start working.")
        if result.get("disconnect"):
            print(f"Close tunnel: {result['disconnect']}")
    if "ssh" in result:
        print(f"\nSSH as agent (Claude Code, Codex, editors): ssh {result['ssh']}")
        if result.get("ssh_include"):
            print(f"~/.ssh/config is a symlink, so it was not changed. Add this as its first line:\n  {result['ssh_include']}")
    if "ssh_error" in result:
        rerun = shlex.join(["./agent-vm", "ssh-config", *([args.name] if args.name else []), "--host", args.host])
        print(f"\nSSH access was not configured: {result['ssh_error']}\nAfter fixing that, run: {rerun}")


def main():
    args = parser().parse_args()
    try:
        validate(args)
        if args.command == "connect":
            result = connect(args)
        elif args.command == "ssh-config":
            result = ssh_access(args)
        elif args.host:
            result = remote(args.host, forwarded(args))
        else:
            from lib.host import dispatch
            result = dispatch(args)
        if args.command == "delete" and args.host:
            from lib import sshconfig
            sshconfig.remove_entry(Path.home(), sshconfig.alias(args.name, args.host))
        if args.command in ("up", "install") and not args.json and not args.no_connect:
            args.name = getattr(args, "name", None)
            result.update(connect(args))
            if args.host:
                # The VM and T3 already work; keep the pairing link if only SSH setup fails.
                try:
                    result.update(ssh_access(args))
                except Error as exc:
                    result["ssh_error"] = str(exc)
        if args.json:
            print(json.dumps(result))
        elif {"url", "ssh", "ssh_error"} & set(result if isinstance(result, dict) else ()):
            report(result, args)
        else:
            print(json.dumps(result, indent=2))
    except KeyboardInterrupt:
        log("\nagent-vm: Interrupted. Rerun the same command to resume.")
        sys.exit(1)
    except (Error, OSError) as exc:
        log(f"\nagent-vm: {exc}")
        sys.exit(1)
