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
installs packages, desktop tools, pinned coding CLIs and systemd units. There is
no image build account, shared credential store, or dependency on a human login
name. Services are installed after cloud-init, avoiding boot ordering cycles.

T3 and VNC bind to loopback. HTTP and X11 readiness are checked before success.
An installer fingerprint permits unchanged reruns to check/start existing
services. Ubuntu, Node and Chrome apt packages receive current repository
versions at installation; the image is content-addressed and coding CLI versions
are pinned, but the whole installation is not a byte-reproducible build.

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
is implemented. Existing prototype instances remain unmanaged.

## Remote access

For a KVM VM, a host-local SSH tunnel forwards to guest loopback using its
management key. The controller then opens a separate SSH tunnel to host
loopback. For an existing VM, only the controller tunnel is needed. Pairing URLs
are rewritten to the selected local port; no public listener is required.
Controller tunnel sockets live under `~/.local/state/agent-vms/tunnels`.

`mobile` optionally installs Tailscale in the VM, requests user authorization,
and runs T3's `pair --tailscale`. The resulting HTTPS endpoint is private to the
tailnet. T3 Connect remains an upstream alternative that users can configure.

## Isolation

The dedicated libvirt NAT bridge `avms0` has isolated guest ports. A dedicated
nftables table blocks guest-originated host access except DHCP/DNS, private IPv4
destinations, and IPv6 forwarding. Existing host networks/firewall tables are
not rewritten. The agent has sudo inside its VM and public internet access.
This is a single-owner development tool, not a hostile multi-tenant service.
