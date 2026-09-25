"""Controller SSH entries so Claude Code, Codex and editors can reach a VM directly."""
import ipaddress
import re
import shutil
import socket

from lib.agent_vm import PUBLIC_KEY, Error, run

HEADER = "# Managed by agent-vms. Rerun ./agent-vm ssh-config instead of editing.\n"


def paths(home):
    directory = home / ".ssh/agent-vms"
    return directory, directory / "config", directory / "known_hosts", directory / "id_ed25519"


def quote(path):
    return f'"{path}"' if re.search(r"\s", str(path)) else str(path)


def alias(name, host):
    target = name or re.sub(r"[^a-z0-9-]+", "-", host.rpartition("@")[2].lower()).strip("-")
    return f"avm-{target}"


def private_write(path, text, mode=0o600):
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(text)
    temporary.chmod(mode)
    temporary.replace(path)


def ensure_key(home):
    """A dedicated passphrase-free key lets GUI tools connect without an agent prompt."""
    directory, _, _, key = paths(home)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not key.exists():
        label = re.sub(r"[^A-Za-z0-9.-]+", "-", socket.gethostname())[:64] or "controller"
        run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", f"agent-vms@{label}", "-f", key])
    return key.with_name(key.name + ".pub").read_text().strip()


def entries(config):
    """Split the managed file into {alias: block}; it only ever contains Host blocks."""
    text = config.read_text() if config.exists() else ""
    return {chunk.split()[1]: chunk.strip() + "\n"
            for chunk in re.split(r"\n(?=Host )", text) if chunk.startswith("Host ")}


def save(home, blocks, known):
    directory, config, known_hosts, _ = paths(home)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    private_write(config, HEADER + "".join("\n" + blocks[name] for name in sorted(blocks)))
    private_write(known_hosts, "".join(line + "\n" for line in known))


def known_lines(known_hosts, without):
    lines = known_hosts.read_text().splitlines() if known_hosts.exists() else []
    return [line for line in lines if line.split(" ", 1)[0] != without]


def write_entry(home, name, hostname, port, jump, host_key):
    # These values come from the remote host; never let them add config lines.
    if not PUBLIC_KEY.fullmatch(host_key or ""):
        raise Error("The VM returned an invalid SSH host key; refusing to trust it.")
    try:
        ipaddress.IPv4Address(hostname)
    except ValueError as exc:
        raise Error("The VM returned an invalid address; refusing to write SSH config.") from exc
    if type(port) is not int or not 1 <= port <= 65535:
        raise Error("The VM returned an invalid SSH port; refusing to write SSH config.")
    _, config, known_hosts, key = paths(home)
    blocks = entries(config)
    blocks[name] = (f"Host {name}\n  HostName {hostname}\n  Port {port}\n  User agent\n  ProxyJump {jump}\n"
                    f"  IdentityFile {quote(key)}\n  IdentitiesOnly yes\n  HostKeyAlias {name}\n"
                    f"  UserKnownHostsFile {quote(known_hosts)}\n  StrictHostKeyChecking yes\n"
                    "  ServerAliveInterval 30\n")
    known = known_lines(known_hosts, name)
    known.append(f"{name} {' '.join(host_key.split()[:2])}")
    save(home, blocks, known)


def remove_entry(home, name):
    _, config, known_hosts, _ = paths(home)
    if not config.exists():
        return
    blocks = entries(config)
    blocks.pop(name, None)
    save(home, blocks, known_lines(known_hosts, name))


def include_line(home):
    return f"Include {quote(paths(home)[1])}"


def ensure_include(home):
    """Prepend our Include so entries win over later Host * defaults.

    A symlinked config usually belongs to a dotfiles repository; leave it alone.
    """
    config = home / ".ssh/config"
    if config.is_symlink():
        return False
    line = include_line(home)
    text = config.read_text() if config.exists() else ""
    if line in (existing.strip() for existing in text.splitlines()):
        return True
    backup = home / ".ssh/config.agent-vms-backup"
    if config.exists() and not backup.exists():
        shutil.copy2(config, backup)
    mode = config.stat().st_mode & 0o777 if config.exists() else 0o600
    private_write(config, f"{line}\n{text}", mode)
    return True
