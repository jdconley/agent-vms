# Architecture

`agent-vm` is a Python 3 standard-library CLI. It calls Ubuntu installers and
libvirt through argument arrays. Remote commands use SSH with explicit quoting;
a small allowlisted source archive is streamed to a temporary directory. Local
deployment configuration and credentials never enter that archive.

## Two paths, one guest

`up` prepares a KVM host, downloads an Ubuntu cloud image over HTTPS, verifies its
published SHA-256, and stores it under a content-addressed, read-only filename.
Each guest receives its own qcow2 overlay and NoCloud seed. The seed contains a
public management key, a stable instance UUID, and a consistent `agent` account.
The private management key stays on the host and is unique to that instance.

After cloud-init completes, the host streams `setup/install-guest.sh` and its
sources over SSH. `install` runs that same installer in an existing VM. It
installs packages, desktop tools, coding CLIs and systemd units. There is no
image build account, shared credential store, or dependency on a human login
name. Services are installed after cloud-init, avoiding boot ordering cycles.

T3 and VNC bind to loopback. HTTP and X11 readiness are checked before success.
An installer fingerprint permits unchanged reruns to check/start existing
services. Ubuntu, Node and Chrome apt packages receive current repository
versions at installation and the base image is content-addressed, but the
installation is not reproducible: coding tools track their latest releases.

## Coding tools

`setup/install-agent-tools.sh` installs the coding CLIs as `agent` so their own
updaters can replace them. T3, Codex and OpenCode use npm with the prefix
`/home/agent/.local`. Claude Code uses [Anthropic's native installer](https://claude.ai/install.sh),
which checks each binary against a published SHA-256 manifest. Cursor CLI and
Grok Build use their official [Cursor](https://cursor.com/install) and
[Grok](https://x.ai/cli/install.sh) installers, which download over HTTPS without
checksums. Installer scripts are downloaded completely before they run. A tool is
installed only when missing; afterwards its own updater owns it. Root-owned links
in `/usr/local/bin` point at the agent's copies, so login shells, plain SSH
commands, services and the management channel all run the current versions.

`agent-vms-update.timer` runs `setup/update-tools.sh clis` daily as `agent`: every
tool's own update command, each with a timeout, continuing past failures. T3 runs
agent sessions as child processes, so it is never replaced while it runs:
`t3-serve.service` updates it in `ExecStartPre`, and a failed or offline check
starts the installed version. `agent-vm update` runs the updater immediately and
restarts T3 only when a newer version exists. Health checks require each coding
CLI to resolve to the agent's copy and run as `agent`. Reinstalling over an older
release removes its root-owned npm packages and pinned binaries. No provider
authentication is attempted during installation.

## State and recovery

Host metadata lives at `/var/lib/agent-vms/instances/NAME`. It records the libvirt
UUID, disk/base paths, requested resources and provisioning phase. The directory
also contains a per-instance management identity, known_hosts, disk and seed.
Private keys and state are root-only; QEMU owns only disk and seed. A host-wide
lock serializes mutations. Existing domains must match the recorded UUID before
they can be changed. Failed provisioning preserves the guest for diagnosis.

Base images live under `/var/lib/libvirt/images/agent-vms`. A guest's backing
image is never replaced. Deleting a guest removes its owned directory and domain;
base-image garbage collection is deliberately manual until reference checking
is implemented. VMs created by other tools remain unmanaged.

## Remote access

For a KVM VM, a host-local SSH tunnel forwards to guest loopback using its
management key. The controller then opens a separate SSH tunnel to host
loopback. For an existing VM, only the controller tunnel is needed. Pairing URLs
are rewritten to the selected local port; no public listener is required.
Controller tunnel sockets live under `~/.local/state/agent-vms/tunnels`.

Tools that run agents over SSH (Claude Code, Codex, editors) need a direct login
as `agent`. After `up`/`install`, the controller creates a dedicated key in
`~/.ssh/agent-vms`, and the host installs its public key in the guest over the
management connection, which also returns the guest's host key. SSH accounts are
often limited to forwarding to loopback (`PermitOpen 127.0.0.1:*`), so the host
publishes each guest's SSH on a stable host-loopback port (22200–22999, recorded
in state) with a socket-activated `systemd-socket-proxyd` unit running as a
dynamic user. The controller writes a `Host avm-NAME` entry with the key pinned,
`ProxyJump` through the KVM host and that port; an existing VM jumps through
itself to its own port 22. `~/.ssh/config` gets one `Include` line at the top so
these entries take precedence over later `Host *` defaults. The host turns each
guest's first DHCP lease into a libvirt reservation, so the address survives
reboots; deletion releases it and removes the relay units. Only this
controller's previous key (matched by its comment) is replaced; the management
key and other keys are kept.

`mobile` optionally installs Tailscale in the VM, requests user authorization,
and runs T3's `pair --tailscale`. The resulting HTTPS endpoint is private to the
tailnet. T3 Connect remains an upstream alternative that users can configure.

## Isolation

The dedicated libvirt NAT bridge `avms0` has isolated guest ports. A dedicated
nftables table blocks guest-originated host access except DHCP/DNS, private IPv4
destinations, and IPv6 forwarding. Existing host networks/firewall tables are
not rewritten. The agent has sudo inside its VM and public internet access.
This is a single-owner development tool, not a hostile multi-tenant service.

## Design choices

A prebuilt VM image (for example with Packer) would start guests faster, but it
adds another tool and a long build before first use. Guests instead boot the
checksum-verified Ubuntu cloud image and run the same installer as `install`,
so one command works on a fresh host and reruns reuse the cached base image.
Cloud-provider APIs would remove the KVM requirement but bring accounts, billing
and provider-specific provisioning. KVM plus installation into an existing VM
covers self-hosted use and leaves a clear boundary for adding providers later.
