"""Linux KVM provisioning and guest lifecycle. All mutations require root."""
import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shlex
import shutil
import socket
import time
import urllib.request
import urllib.parse
import uuid
import xml.etree.ElementTree as ET

from lib.agent_vm import (ROOT, STATE, Error, cloud_config, free_port, log,
                          read_state, run, source_archive, start_tunnel, write_state)

INSTANCES = STATE / "instances"
BASES = Path("/var/lib/libvirt/images/agent-vms")
IMAGE_URL = "https://cloud-images.ubuntu.com/noble/current/"
IMAGE_NAME = "noble-server-cloudimg-amd64.img"
NETWORK = "agent-vms"
SYSTEMD = Path("/etc/systemd/system")
# Below Linux's ephemeral range, so outgoing connections never take these first.
SSH_PORTS = range(22200, 23000)
# Runs as the guest's agent user. Replaces only this controller's earlier key
# (matched by comment), then prints the host key for the controller to pin.
AUTHORIZE = r'''set -eu
key="$1"; dir="${2:-/home/agent/.ssh}"; comment="${key##* }"
install -d -m 700 "$dir"
touch "$dir/authorized_keys"
awk -v c="$comment" '$NF != c' "$dir/authorized_keys" > "$dir/authorized_keys.new"
printf '%s\n' "$key" >> "$dir/authorized_keys.new"
chmod 600 "$dir/authorized_keys.new"
mv "$dir/authorized_keys.new" "$dir/authorized_keys"
cat "${3:-/etc/ssh/ssh_host_ed25519_key.pub}"
'''


@contextlib.contextmanager
def locked():
    STATE.mkdir(parents=True, exist_ok=True, mode=0o755)
    with (STATE / "lock").open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise Error("Another agent-vm operation is running on this host. Retry when it finishes.") from exc
        yield


def require_root():
    if platform.system() != "Linux":
        raise Error("This command needs Ubuntu 24.04 x86-64. Use --host user@linux-host from this machine.")
    if os.geteuid() != 0:
        raise Error("Run with sudo on this host, or use --host with a passwordless-sudo SSH account.")


def virsh(*args, check=True):
    return run(["virsh", "--connect", "qemu:///system", *args], capture=True, check=check)


def assert_domain(state):
    actual = virsh("domuuid", state["name"]).strip()
    if actual != state["uuid"]:
        raise Error(f"Domain ownership mismatch for {state['name']}; refusing to modify it.")


def domain_exists(name):
    return name in virsh("list", "--all", "--name").splitlines()


def verify_image(path, expected):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    if digest.hexdigest() != expected:
        raise Error(f"Image checksum mismatch: {path}. Refusing to use it.")


def base_image():
    BASES.mkdir(parents=True, exist_ok=True)
    manifest = BASES / "ubuntu-24.04.json"
    digest = json.loads(manifest.read_text())["sha256"] if manifest.exists() else None
    # "current" moves on; a manifest whose image was removed cannot be re-downloaded.
    if not (digest and re.fullmatch(r"[a-f0-9]{64}", digest)
            and (BASES / f"ubuntu-24.04-{digest}.qcow2").exists()):
        log("[2/5] Downloading and verifying the Ubuntu 24.04 base image…")
        with urllib.request.urlopen(IMAGE_URL + "SHA256SUMS", timeout=60) as response:
            lines = response.read().decode().splitlines()
        matches = [line.split()[0] for line in lines if line.split()[-1].lstrip("*") == IMAGE_NAME]
        if len(matches) != 1 or not re.fullmatch(r"[a-f0-9]{64}", matches[0]):
            raise Error("Ubuntu checksum manifest did not identify exactly one supported image.")
        digest = matches[0]
    path = BASES / f"ubuntu-24.04-{digest}.qcow2"
    if not path.exists():
        temporary = BASES / "download.partial"
        run(["curl", "--fail", "--location", "--retry", "3", "--connect-timeout", "15",
             "--max-time", "1800", "--output", temporary, IMAGE_URL + IMAGE_NAME])
        verify_image(temporary, digest)
        temporary.chmod(0o444)
        temporary.replace(path)
    else:
        log("[2/5] Checking the cached immutable base image…")
        verify_image(path, digest)
    manifest.write_text(json.dumps({"sha256": digest, "source": IMAGE_URL + IMAGE_NAME}) + "\n")
    return path


def guest_command(directory, ip):
    return ["ssh", "-o", "BatchMode=yes", "-o", "IdentitiesOnly=yes",
            "-o", "StrictHostKeyChecking=accept-new", "-o", "ConnectTimeout=10",
            "-o", f"UserKnownHostsFile={directory / 'known_hosts'}",
            "-o", "ServerAliveInterval=30", "-o", "ServerAliveCountMax=3",
            "-i", directory / "management", f"agent@{ip}"]


def guest(directory, ip, command, **kwargs):
    return run([*guest_command(directory, ip), command], **kwargs)


def address(name, timeout=120):
    deadline = time.monotonic() + timeout
    while True:
        output = virsh("domifaddr", name, "--source", "lease")
        ips = re.findall(r"ipv4\s+([0-9.]+)/", output)
        if len(ips) == 1:
            return ips[0]
        if time.monotonic() >= deadline:
            raise Error(f"No unique DHCP address for {name}. Check virsh domifaddr {name} and libvirt network agent-vms.")
        time.sleep(2)


def running_address(name):
    power = virsh("domstate", name).strip()
    if power != "running":
        raise Error(f"{name} is {power}. Start it with: agent-vm up {name} (same --host and resources).")
    return address(name, timeout=0)


def domain_mac(name):
    macs = [interface.find("mac").get("address")
            for interface in ET.fromstring(virsh("dumpxml", name)).iterfind("./devices/interface")
            if interface.find("source") is not None and interface.find("source").get("network") == NETWORK]
    if len(macs) != 1:
        raise Error(f"{name} must have exactly one interface on the {NETWORK} network.")
    return macs[0]


def update_reservation(action, entry):
    virsh("net-update", NETWORK, action, "ip-dhcp-host", ET.tostring(entry, encoding="unicode"),
          "--live", "--config")


def reservations():
    return ET.fromstring(virsh("net-dumpxml", NETWORK)).findall("./ip/dhcp/host")


def reserve_address(name, ip):
    """Pin the current lease so SSH entries and tunnels survive host reboots."""
    mac = domain_mac(name)
    for entry in reservations():
        if entry.get("mac") == mac and entry.get("name") == name and entry.get("ip") == ip:
            return
        if entry.get("mac") == mac or entry.get("name") == name:
            update_reservation("delete", entry)
    update_reservation("add-last", ET.Element("host", mac=mac, name=name, ip=ip))


def release_address(name):
    try:
        entries = reservations()
    except Error:
        return  # Without the managed network there is no reservation to release.
    for entry in entries:
        if entry.get("name") == name:
            update_reservation("delete", entry)


def ssh_port(directory, state):
    """Choose, once, the host-loopback port that relays to this guest's SSH."""
    if state.get("ssh_port"):
        return state["ssh_port"]
    taken = set()
    for other in INSTANCES.glob("*"):
        if other.is_dir() and other != directory:
            try:
                taken.add(read_state(other).get("ssh_port"))
            except Error:
                pass
    for port in SSH_PORTS:
        if port in taken:
            continue
        with socket.socket() as probe:
            try:
                probe.bind(("127.0.0.1", port))
            except OSError:
                continue
        state["ssh_port"] = port
        write_state(directory, state)
        return port
    raise Error(f"No free SSH relay port in {SSH_PORTS.start}-{SSH_PORTS.stop - 1} on this host.")


def publish_ssh(name, ip, port):
    """Relay host loopback to guest SSH, since accounts are often limited to PermitOpen 127.0.0.1:*.

    Anything on the host can already reach the guest directly; this adds no exposure.
    """
    unit = f"agent-vms-ssh-{name}"
    files = {
        SYSTEMD / f"{unit}.socket": (f"[Unit]\nDescription=SSH relay to agent VM {name} (host loopback only)\n"
                                     f"[Socket]\nListenStream=127.0.0.1:{port}\n"
                                     "[Install]\nWantedBy=sockets.target\n"),
        SYSTEMD / f"{unit}.service": (f"[Unit]\nDescription=SSH relay to agent VM {name}\n"
                                      f"[Service]\nDynamicUser=yes\n"
                                      f"ExecStart=/usr/lib/systemd/systemd-socket-proxyd {ip}:22\n"),
    }
    changed = [path for path, text in files.items() if not path.exists() or path.read_text() != text]
    for path in changed:
        path.write_text(files[path])
    if changed:
        run(["systemctl", "daemon-reload"])
        # A running relay keeps its old target and port until it is stopped.
        run(["systemctl", "stop", f"{unit}.service", f"{unit}.socket"])
    run(["systemctl", "enable", "--now", f"{unit}.socket"])


def unpublish_ssh(name):
    unit = f"agent-vms-ssh-{name}"
    files = [SYSTEMD / f"{unit}.socket", SYSTEMD / f"{unit}.service"]
    if not any(path.exists() for path in files):
        return
    run(["systemctl", "disable", "--now", f"{unit}.socket", f"{unit}.service"], check=False)
    for path in files:
        path.unlink(missing_ok=True)
    run(["systemctl", "daemon-reload"])


def authorize(name, public_key):
    """Let the controller's key log in as agent and return how to reach and pin the guest."""
    if name is None:
        output = run(["runuser", "-u", "agent", "--", "bash", "-c", AUTHORIZE, "authorize", public_key],
                     capture=True, timeout=30)
        return {"hostname": "127.0.0.1", "port": 22, "host_key": output.strip()}
    directory = INSTANCES / name
    state = read_state(directory)
    assert_domain(state)
    ip = running_address(name)
    reserve_address(name, ip)
    port = ssh_port(directory, state)
    publish_ssh(name, ip, port)
    output = guest(directory, ip, shlex.join(["bash", "-c", AUTHORIZE, "authorize", public_key]),
                   capture=True, timeout=30)
    return {"hostname": "127.0.0.1", "port": port, "host_key": output.strip()}


def health(directory, ip):
    return guest(directory, ip, "sudo -n /usr/local/lib/agent-vms/health.sh", capture=True, timeout=100)


def install_guest(directory, ip):
    log("[4/5] Waiting for guest SSH and cloud-init…")
    deadline = time.monotonic() + 180
    while True:
        result = guest(directory, ip, "true", capture=True, check=False, timeout=15)
        if result.returncode == 0:
            break
        if time.monotonic() >= deadline:
            raise Error("Guest SSH did not become ready. Rerun up to resume; inspect virsh console for boot errors.")
        time.sleep(3)
    # cloud-init exit 2 also means degraded provisioning and must not be hidden.
    guest(directory, ip, "sudo -n timeout 300 cloud-init status --wait", timeout=320)
    script = ("set -eu; work=$(mktemp -d); trap 'rm -rf \"$work\"' EXIT; "
              "tar -xzf - -C \"$work\"; sudo -n bash \"$work/setup/install-guest.sh\"")
    guest(directory, ip, script, data=source_archive(), timeout=2400)
    log("[5/5] Verifying T3, desktop, browser and coding tools…")
    health(directory, ip)


def up(args):
    log("[1/5] Preparing the KVM host…")
    run(["bash", ROOT / "setup/install-host.sh"], timeout=1200)
    base = base_image()
    INSTANCES.mkdir(parents=True, exist_ok=True)
    directory = INSTANCES / args.name
    if directory.exists():
        state = read_state(directory)
        requested = (args.cpus, args.memory, args.disk)
        original = (state["cpus"], state["memory"], state["size_gib"])
        if requested != original:
            raise Error(f"{args.name} already has CPU/RAM/disk {original}; rerun with those values. Resizing is not implicit.")
    else:
        if domain_exists(args.name):
            raise Error(f"Domain {args.name} already exists and is not owned by agent-vms.")
        directory.mkdir(mode=0o711)
        state = {"managed_by": "agent-vms", "name": args.name, "uuid": str(uuid.uuid4()),
                 "disk": str(directory / "disk.qcow2"), "base": str(base), "phase": "allocated",
                 "cpus": args.cpus, "memory": args.memory, "size_gib": args.disk}
        write_state(directory, state)
    if not (directory / "management").exists():
        run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", directory / "management"])
    if not domain_exists(args.name):
        log(f"[3/5] Creating VM {args.name}…")
        disk = Path(state["disk"])
        if not disk.exists():
            partial_disk = directory / "disk.partial"
            partial_disk.unlink(missing_ok=True)
            run(["qemu-img", "create", "-f", "qcow2", "-F", "qcow2", "-b", state["base"], partial_disk, f"{args.disk}G"])
            partial_disk.replace(disk)
        (directory / "user-data").write_text(cloud_config(args.name, (directory / "management.pub").read_text()))
        (directory / "meta-data").write_text(json.dumps({"instance-id": state["uuid"], "local-hostname": args.name}))
        seed = directory / "seed.img"
        if not seed.exists():
            partial_seed = directory / "seed.partial"
            partial_seed.unlink(missing_ok=True)
            run(["cloud-localds", partial_seed, directory / "user-data", directory / "meta-data"])
            partial_seed.replace(seed)
        for path in (disk, seed):
            shutil.chown(path, user="libvirt-qemu", group="kvm")
            path.chmod(0o600)
        run(["virt-install", "--connect", "qemu:///system", "--name", args.name, "--uuid", state["uuid"],
             "--memory", args.memory, "--vcpus", args.cpus, "--cpu", "host-passthrough",
             "--disk", f"path={disk},format=qcow2,bus=virtio", "--disk", f"path={seed},device=cdrom",
             "--os-variant", "ubuntu24.04", "--network", "network=agent-vms,model=virtio",
             "--graphics", "none", "--import", "--noautoconsole"], timeout=120)
    assert_domain(state)
    if virsh("domstate", args.name).strip() == "shut off":
        virsh("start", args.name)
    state["phase"] = "provisioning"
    write_state(directory, state)
    try:
        ip = address(args.name)
        reserve_address(args.name, ip)
        install_guest(directory, ip)
    except Error:
        state["phase"] = "failed"
        write_state(directory, state)
        log(f"VM and logs retained. Rerun the same up command to resume {args.name}.")
        raise
    state.update(phase="ready", ip=ip)
    write_state(directory, state)
    virsh("autostart", args.name)
    return {"name": args.name, "status": "ready", "ip": ip, "user": "agent"}


def pairing_url(output):
    urls = re.findall(r"https?://[^\s\x1b]+", output)
    for url in urls:
        parsed = urllib.parse.urlsplit(url)
        credentials = urllib.parse.parse_qs(parsed.fragment or parsed.query)
        if parsed.path == "/pair" and credentials.get("token"):
            return url
    raise Error("T3 did not return a pairing URL. Check t3-serve logs; this may be an incompatible T3 version.")


def access(name):
    require_root()
    if name is None:
        run(["bash", ROOT / "setup/health.sh"], timeout=100)
        output = run(["runuser", "-u", "agent", "--", "env", "HOME=/home/agent",
                      "t3", "pair"], capture=True, timeout=30)
        return {"pairing_url": pairing_url(output), "port": 3773}
    directory = INSTANCES / name
    state = read_state(directory)
    assert_domain(state)
    ip = running_address(name)
    health(directory, ip)
    port = host_tunnel(directory, ip)
    output = guest(directory, ip, "t3 pair", capture=True, timeout=30)
    return {"pairing_url": pairing_url(output), "port": port}


def control_path(directory):
    identity = hashlib.sha256(str(directory).encode()).hexdigest()[:16]
    return STATE / "tunnels" / identity


def host_tunnel(directory, ip):
    control = control_path(directory)
    control.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    metadata = directory / "access.json"
    cmd = guest_command(directory, ip)
    if control.exists():
        live = run([*cmd[:-1], "-S", control, "-O", "check", cmd[-1]], capture=True, check=False)
        if live.returncode == 0 and metadata.exists():
            try:
                saved = json.loads(metadata.read_text())
                if saved["ip"] == ip and isinstance(saved["port"], int) and 1024 <= saved["port"] <= 65535:
                    return saved["port"]
            except (ValueError, KeyError):
                pass
        run([*cmd[:-1], "-S", control, "-O", "exit", cmd[-1]], check=False)
        control.unlink(missing_ok=True)
    port = free_port()
    start_tunnel([*cmd[:-1], "-M", "-S", control, "-fNT", "-o", "ExitOnForwardFailure=yes",
                  "-L", f"127.0.0.1:{port}:127.0.0.1:3773", cmd[-1]])
    metadata.write_text(json.dumps({"ip": ip, "port": port}))
    metadata.chmod(0o600)
    return port


def status(name):
    if name is None:
        output = run(["bash", ROOT / "setup/health.sh"], capture=True, timeout=100)
        return {"status": "ready", "health": output.strip()}
    directory = INSTANCES / name
    state = read_state(directory)
    assert_domain(state)
    result = {"name": name, "phase": state["phase"], "power": virsh("domstate", name).strip()}
    if result["power"] == "running":
        ip = address(name, timeout=0)
        result.update(ip=ip, health=health(directory, ip).strip())
    return result


def remove(name):
    directory = INSTANCES / name
    state = read_state(directory)
    if domain_exists(name):
        assert_domain(state)
        if virsh("domstate", name).strip() != "shut off":
            virsh("destroy", name)
        virsh("undefine", name)
    release_address(name)
    unpublish_ssh(name)
    control = control_path(directory)
    if control.exists():
        run(["ssh", "-S", control, "-O", "exit", "agent@localhost"], check=False)
        control.unlink(missing_ok=True)
    # The domain UUID and metadata were checked; this directory alone is owned.
    shutil.rmtree(directory)
    return {"name": name, "status": "deleted"}


def doctor():
    checks = {"linux": platform.system() == "Linux", "x86_64": platform.machine() == "x86_64",
              "kvm": os.access("/dev/kvm", os.R_OK | os.W_OK),
              "root": os.geteuid() == 0,
              "tools": {name: shutil.which(name) is not None for name in ("virsh", "virt-install", "qemu-img", "cloud-localds", "ssh", "curl")}}
    return checks


def dispatch(args):
    if args.command == "doctor":
        return doctor()
    require_root()
    if args.command == "install":
        with locked():
            run(["bash", ROOT / "setup/install-guest.sh"], timeout=2400)
        return {"status": "ready", "user": "agent"}
    if args.command == "access":
        with locked():
            return access(args.name)
    if args.command == "authorize":
        with locked():
            return authorize(args.name, args.public_key)
    if args.command == "run":
        if args.name:
            directory = INSTANCES / args.name
            state = read_state(directory)
            assert_domain(state)
            guest(directory, running_address(args.name), args.guest_command)
        else:
            run(["runuser", "-l", "agent", "-c", args.guest_command])
        return {"status": "command completed"}
    if args.command == "mobile":
        if args.name:
            directory = INSTANCES / args.name
            state = read_state(directory)
            assert_domain(state)
            ip = running_address(args.name)
            health(directory, ip)
            # Pass the script as an argument: with bash -s, any child reading
            # stdin (an apt prompt, for example) would consume the rest of it.
            script = (ROOT / "setup/mobile.sh").read_text()
            output = guest(directory, ip, shlex.join(["sudo", "-n", "bash", "-c", script]), capture=True, timeout=180)
        else:
            output = run(["bash", ROOT / "setup/mobile.sh"], capture=True, timeout=180)
        return {"url": pairing_url(output), "access": "tailscale"}
    if args.command == "status":
        return status(args.name)
    if args.command == "list":
        return [{"name": path.name, "phase": read_state(path)["phase"]}
                for path in sorted(INSTANCES.glob("*")) if path.is_dir()]
    with locked():
        if args.command == "up":
            return up(args)
        if args.command == "delete":
            return remove(args.name)
        if args.command == "stop":
            state = read_state(INSTANCES / args.name)
            assert_domain(state)
            if virsh("domstate", args.name).strip() != "shut off":
                virsh("shutdown", args.name)
            return {"name": args.name, "status": "shutdown requested"}
    raise Error(f"Unsupported command: {args.command}")
