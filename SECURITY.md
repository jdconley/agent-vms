# Security

This project provisions development computers for a single trusted owner. The
owner controls the Linux host; coding agents can run arbitrary commands and
sudo inside their VM. Public internet access is enabled. Do not treat this as a
production multi-tenant service or an assurance against hypervisor exploits.

- T3 and VNC listen on loopback. SSH access authenticates the operator; T3 pairing
  authorizes the browser. Tailnet HTTPS is opt-in.
- A management key is generated per managed guest and remains on the host.
  Host/provider credentials are not copied into guests. Guest logins are not
  shared across VMs.
- `up`, `install` and `ssh-config` create a passphrase-free key on your computer
  at `~/.ssh/agent-vms/id_ed25519` so GUI tools can connect without prompts.
  It logs in to your VMs as `agent`, which has sudo inside the VM; protect it
  like your other SSH keys. To revoke a computer, remove its `agent-vms@HOST`
  line from `/home/agent/.ssh/authorized_keys` in each VM. Each managed VM's
  SSH is relayed on the KVM host's loopback only; local users of that host
  could already reach the guest's SSH, and it still requires a key.
- Guests on the managed bridge cannot initiate access to host services other
  than DHCP/DNS or private network destinations. Other host users with sufficient
  local privileges remain trusted. For `install` on an existing VM, its cloud
  firewall and surrounding network remain the operator's responsibility.
- SSH follows your existing known_hosts policy. New guest host keys use
  trust-on-first-use on the isolated managed network.
- Pairing URLs, auth codes, logs, recordings and VM disks can contain sensitive
  data. Do not publish these artifacts. Deleting a VM is not secure disk erasure.
- System packages come from signed apt repositories. Coding tools install at
  their latest releases and update themselves as `agent`: npm verifies registry
  integrity and Claude Code's installer verifies Anthropic's SHA-256 manifest,
  but the Cursor and Grok installers download over HTTPS without checksums.
  Versions are not pinned, so VMs can differ and a compromised release would
  reach them on the next update.
- The tools are writable by `agent` and linked from `/usr/local/bin`, so a
  root shell can run agent-controlled programs. `agent` already has
  passwordless sudo, so this adds no new boundary.

Report vulnerabilities through this repository's GitHub private vulnerability
reporting feature when available. Otherwise contact the maintainer privately;
do not put credentials or a working exploit against a real host in a public issue.
