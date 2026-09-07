# Development verification — 2026-09-06/07

Status: fresh KVM provisioning, existing-VM installation, physical-host reboot
recovery and cleanup have passed on a real Ubuntu host. Optional mobile access
remains experimental. These results cover the initial preview's installer;
they do not establish support for other operating systems or tool versions.

## Environment

- Controller: macOS ARM64, Python standard-library CLI and OpenSSH.
- Host: Ubuntu 24.04.4 x86-64, KVM, libvirt 10.0.0, QEMU 8.2.2;
  SSH as an ordinary user with passwordless sudo.
- Fresh guests: Ubuntu 24.04 cloud image with SHA-256
  `d0fe84bb5f80853425fa6be28e2c106f30104c3cfe8611933f2e65c9b63f0e30`.
- T3 Code 0.0.38, Codex 0.153.4, Claude Code 2.1.263, OpenCode 1.18.29,
  Node.js 22. Provider credentials were not copied or supplied.

## Passed

- macOS and Ubuntu suites: 30 tests on each; Python compilation, Bash syntax,
  ShellCheck and diff checks passed on both platforms.
- Fresh `up`: host setup, checksum verification, disk/seed creation, cloud-init,
  per-VM SSH identity, package installation, systemd startup and actual HTTP/X11
  health checks completed successfully.
- Managed `connect`: opened the real pairing link through both SSH hops in a
  browser; T3 rendered, browsed the guest filesystem and added a test Git project.
- Existing-VM `install`: used a separately created fresh VM and ordinary sudo
  user. No KVM management was required inside that VM.
- Real interruption recovery: deliberately killed dpkg during package unpack.
  Installation failed nonzero. After fixing recovery of reinst-required packages,
  rerunning the same install command repaired that package and completed setup.
- Existing-VM `connect`: captured JSON completed promptly through an SSH proxy;
  the background tunnel remained usable after the caller exited, and T3 browser
  pairing completed.
- Rerunning managed `up` retained the guest UUID, disk path, immutable backing
  image and a project file. Changed installer source applied successfully.
- `stop` shut down the managed guest gracefully. A subsequent plain `up` started
  it, passed service/desktop checks and automatically returned a pairing link.
- Chrome launched with its sandbox enabled and visibly rendered Example Domain
  on display `:1`. The installed recording helpers produced a finalized H.264
  MP4 at 1280×800; ffprobe verified duration and stream metadata.
- Guest isolation: a controlled HTTP listener was reachable from the host but
  unreachable from the other guest. Peer SSH and host SSH via both bridge and LAN
  addresses were blocked. Public HTTPS returned HTTP 200; DHCP/DNS worked.
- Deleting an unmanaged VM through the CLI was refused; it remained running.
- Physical-host reboot: a changed boot ID confirmed the reboot. Both VMs started
  automatically; firewall, libvirt and the managed network recovered. Both guests
  passed HTTP/X11 readiness without reinstalling. Reconnection/pairing worked,
  the T3 project remained available, and its persistence file was unchanged.
- Repeated isolation after reboot with two managed guests: a controlled peer
  listener was reachable from the host but blocked from the other guest. SSH,
  T3 and VNC were blocked in both guest-to-guest directions; host SSH was blocked
  via bridge and LAN addresses. Public HTTPS still returned HTTP 200. Socket
  inspection confirmed guest T3/VNC only listened on loopback.
- Ownership protection: deliberately mismatched VM metadata caused deletion to
  fail while preserving the VM and disk. After restoring the correct metadata,
  deleting one managed guest left the other healthy with its disk intact.
- Final cleanup: both managed guests and the separate existing-VM fixture were
  removed. Instance listing and libvirt domain listing were empty, and the test
  instance directories were absent. Temporary controller keys and tunnels were
  removed. The reusable image cache and managed network remain on the host.

## Cursor and Grok CLI addition — 2026-09-07

- Local suite: 33 tests passed, including real subprocess checks for native CLI
  coexistence, cached reruns, checksum rejection and incomplete archive rejection.
  Bash/Python checks, ShellCheck and Gitleaks passed.
- A fresh Ubuntu 24.04 KVM guest installed the official pinned artifacts and
  passed T3 HTTP, X11 and native CLI readiness checks.
- As the unprivileged guest account, `cursor-agent --version` reported
  `2026.09.02-c22c1a3`; `grok --version` reported `grok 1.0.13 (5e9a58528b76)`.
  Both `--help` and `login --help` completed successfully. No login or provider
  request was performed.
- Tool directories were root-owned and readable/executable by the guest account.
  No `/usr/local/bin/agent` alias was created.
- An unchanged `up` skipped package installation, passed readiness again and
  preserved a test project file. The test VM was then deleted; the managed
  instance listing was empty.

## Runtime findings fixed

- T3 pairing tokens use a URL fragment; parsing supports the observed format.
- Long instance names needed shorter SSH control socket paths.
- Remote sudo imports created root-owned bytecode and broke upload cleanup;
  remote Python now disables bytecode generation.
- Interrupted package installation needs write-mode dpkg recovery and explicit
  reinstallation of damaged packages. A real isolated dpkg database also confirmed
  that configure can exit zero while a half-installed package remains.
- SSH may accept a local listener while denying forwarding. Readiness now probes
  T3 through the tunnel, bypasses HTTP proxies and validates the environment JSON.
- SSH proxy processes inherited captured output and the caller's process group.
  Tunnel startup now detaches those descriptors and creates a separate session.
- A root-owned XDG settings directory prevented Chrome startup; installation
  repairs its ownership and health checks require it to be writable.
- An early-exiting grep caused virsh SIGPIPE under pipefail, incorrectly treating
  an active network as stopped. The check now consumes stable network names.
- A native npm dependency failed while downloading Node headers. Installation now
  uses the matching headers already installed by NodeSource. Retrying the same
  second managed VM completed installation and passed health checks.

## Remaining checks

- Optional Tailscale HTTPS/phone access remains unverified and is marked
  experimental. The real authorization flow generated a login link and correctly
  returned nonzero without authorization; no host credentials were reused.
- Provider sign-in remains a user-owned step. No provider-account session or
  billable coding request was exercised.

The earlier emulated Docker test could not run systemd reliably; the successful
real VM startup checks above supersede that limitation. See
[CONTRIBUTING.md](../CONTRIBUTING.md) for the complete release procedure. Keep
pairing tokens, keys, credentials and private target addresses out of reports.
