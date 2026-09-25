# agent-vms

**Your own remote T3 Code computer, in one command.**

Give each project an Ubuntu VM with T3 Code, coding agents, Chrome, a desktop,
and screen recording. Run it on a Linux server you own and connect from your
laptop over SSH: open T3 in your browser, or point Claude Code, Codex or your
editor at the VM. An agent can perform the setup by following [AGENTS.md](AGENTS.md).

```bash
./agent-vm up my-project --host you@linux-server
```

This installs the host dependencies, downloads and verifies Ubuntu, creates the
VM, installs its development tools, checks T3 and the desktop, and opens an SSH
tunnel. The final output is a one-time pairing link you can open in your browser
and an SSH host (`avm-my-project`) for tools that work over SSH.
The first installation takes several minutes; rerunning the command resumes it.

**Already have a VM?** Install the same environment directly:

```bash
./agent-vm install --host ubuntu@your-vm
```

That machine needs no KVM support. Use a dedicated development VM: installation
creates an `agent` user with sudo access and installs system packages and services.

> Preview status: fresh VM creation, existing-VM installation, browser access,
> host reboot recovery, network isolation and cleanup have passed on Ubuntu 24.04.
> Phone access remains experimental. See [verification results](docs/VERIFICATION.md).

## Before you start

- Clone [this repository](https://github.com/jdconley/agent-vms) and run the commands
  from its root directory:

  ```bash
  git clone https://github.com/jdconley/agent-vms.git
  cd agent-vms
  ```
- Your laptop/controller needs Python 3.10+ and OpenSSH. Linux and macOS work.
- The target needs **Ubuntu 24.04 x86-64**, Python 3, and SSH access as root or
  a user with passwordless sudo. Check that `ssh you@host true` works first.
  SSH config aliases, identity files, custom ports and ProxyJump are supported
  through your normal `~/.ssh/config`.
- The SSH server must allow local TCP forwarding to loopback (`AllowTcpForwarding
  local` or `yes`, with `PermitOpen` allowing `127.0.0.1:*`). The CLI verifies the
  tunnel before reporting a browser link as ready.
- `up` additionally needs working `/dev/kvm` on that host. Many ordinary cloud
  VMs do not support nested virtualization; use `install` on those VMs.
- Defaults: 4 CPUs, 6 GiB RAM, 30 GiB guest disk. Allow additional host space for
  the base image and downloads. The host needs outbound HTTPS and a free
  `192.168.197.0/24` subnet.

On the Linux host itself, omit `--host` and run with sudo:

```bash
sudo ./agent-vm up my-project
```

Provider sign-in is a separate, user-owned step in T3 or the provider CLI.
Installing a tool does not authorize your account, and no host credentials are
copied to the VM. Versions for T3, Codex, Claude Code, OpenCode, Cursor CLI and
Grok Build are recorded in [versions.env](versions.env).

## Everyday commands

```bash
./agent-vm doctor --host you@linux-server
./agent-vm list --host you@linux-server
./agent-vm status my-project --host you@linux-server
./agent-vm connect my-project --host you@linux-server
./agent-vm run my-project --host you@linux-server --command 'git --version'
./agent-vm ssh-config my-project --host you@linux-server
./agent-vm stop my-project --host you@linux-server
./agent-vm up my-project --host you@linux-server
./agent-vm delete my-project --host you@linux-server --yes
```

`connect` creates a new pairing link and a background SSH tunnel. It chooses a
free local port and prints a command to close the tunnel. After a laptop/host
restart, run `connect` again. Stopping/deleting applies only to managed KVM VMs;
`delete --yes` permanently removes that VM's files.

For an existing VM installed with `install`, omit the instance name:

```bash
./agent-vm status --host ubuntu@your-vm
./agent-vm connect --host ubuntu@your-vm
```

Customize resources when creating a VM:

```bash
./agent-vm up big-project --host you@linux-server --cpus 8 --memory 12288 --disk 60
```

Reruns must use the same resource values. Existing disks are never silently
resized or replaced. `up` and `install` accept `--no-connect` for provisioning
without a local tunnel or SSH entry. Every command accepts `--json`; this also
skips both for `up` and `install`, so agents can inspect a stable result.

## SSH access for Claude Code, Codex and editors

`up` and `install` also let this computer log in to the VM as `agent`:

```bash
ssh avm-my-project
```

- **Claude Code desktop:** add an SSH connection with host `avm-my-project`.
  On first connection it installs and manages its own Claude Code copy in the
  VM (under `~/.claude/remote`); the pinned `claude` command stays for T3 and
  the terminal.
- **Codex (Codex app or ChatGPT desktop app):** enable `avm-my-project` under
  Settings → Connections. The app asks you to sign in to Codex in the VM the
  first time; `ssh -t avm-my-project codex login --device-auth` also works.
- **VS Code or Cursor Remote-SSH:** connect to `avm-my-project`.

This creates a dedicated key at `~/.ssh/agent-vms/id_ed25519`, writes the host
entries to `~/.ssh/agent-vms/config`, and adds an `Include` for that file to the
top of `~/.ssh/config` (the original is saved once as `~/.ssh/config.agent-vms-backup`).
A symlinked `~/.ssh/config` is left alone; the command prints the line to add.
Managed VMs are reached with `ProxyJump` through the KVM host, where a small
systemd relay on the host's loopback (`127.0.0.1:22200` and up) forwards to the
VM's SSH. That works with SSH accounts limited to loopback forwarding, and the
VM needs no open port. Each VM keeps a fixed address on the host's private
network. Its host key is pinned through the management connection, so there is
no first-connection prompt.

To set up another computer, or to repair an entry, run:

```bash
./agent-vm ssh-config my-project --host you@linux-server
# Existing VM (creates avm-your-vm):
./agent-vm ssh-config --host ubuntu@your-vm
```

`delete` removes the VM's entry. To see the desktop, forward VNC and open a VNC
viewer at `localhost:5901`: `ssh -N -L 5901:127.0.0.1:5901 avm-my-project`.

## GitHub access

`gh` comes from GitHub's signed apt repository. Sign in once per VM with your
own GitHub account; no host credentials or tokens are copied into the VM:

```bash
ssh -t avm-my-project gh auth login --web --git-protocol https
ssh avm-my-project gh auth setup-git
```

`gh` prints a one-time code; enter it at <https://github.com/login/device>.
`gh auth setup-git` lets plain `git clone` and `git push` use that sign-in.
Without the SSH entry, run the same steps through the CLI:

```bash
./agent-vm run my-project --host you@linux-server \
  --command 'gh auth login --web --git-protocol https && gh auth setup-git'
```

The token stays in the VM under `/home/agent/.config/gh` and is deleted with
the VM. Revoke it from your GitHub settings if you stop trusting the VM.

## Phone access

Phone access is experimental; end-to-end tailnet HTTPS validation is pending.

SSH tunnel links work on the computer running the command. For phone access,
install and authorize Tailscale on the VM:

```bash
./agent-vm mobile my-project --host you@linux-server
# Existing VM:
./agent-vm mobile --host ubuntu@your-vm
```

Follow the Tailscale authorization link printed during setup. If authorization
takes longer than a minute, finish it and rerun the command. Enable HTTPS when
Tailscale requests it. The resulting T3 pairing link uses Tailscale HTTPS and
works on devices in your tailnet. This never enables Tailscale Funnel or public
port forwarding. [T3 remote-access documentation](https://github.com/pingdotgg/t3code/blob/main/docs/user/remote-access.md).

## What agents get

- T3 Code plus Codex, Claude Code, OpenCode, Cursor CLI and Grok Build CLIs
- Node.js 22, Python 3, Git, GitHub CLI (`gh`), build tools, jq and unzip
- Xfce desktop, Google Chrome, xdotool and scrot
- `record-start LABEL` / `record-stop` for screen recordings
- `/home/agent/workspaces` for projects; persistent files across restarts
- Global tool instructions describing the desktop and recording workflow

Use `cursor-agent` for Cursor CLI and `grok` for Grok Build inside the VM. Both
are installed from official Linux releases with pinned SHA-256 checksums.
The generic `agent` command is omitted because both upstream installers claim it.
Sign in with `cursor-agent login` or `grok login` using your own account.
These are terminal tools; their availability in T3's provider selector depends
on T3's upstream support.

Recordings stop after at most 15 minutes. `record-stop` finishes earlier; videos
remain in `/home/agent/recordings` until you remove them or delete the VM.

VNC listens on guest loopback (`5901`), and T3 listens on guest loopback (`3773`).
The managed network blocks guest-to-guest traffic and guest-initiated access to
host/private-network services except its DHCP/DNS. The VM can reach the public
internet. See [SECURITY.md](SECURITY.md) for the trust model and limits.

## Troubleshooting and contributing

Errors exit nonzero. Guest install logs live at `/var/log/agent-vms-install.log`;
service logs are available with `journalctl -u t3-serve -u vncserver@1` in the VM.
Rerun the original command after fixing the reported problem. Existing VMs are
retained on failure so their logs and files remain available.

See [architecture](docs/ARCHITECTURE.md), [migration from the original prototype](docs/MIGRATION.md),
and [contributing](CONTRIBUTING.md). This is an independent, self-hosted project,
not an official T3 service. Repository code is [MIT licensed](LICENSE); installed
third-party tools retain their own licenses.
