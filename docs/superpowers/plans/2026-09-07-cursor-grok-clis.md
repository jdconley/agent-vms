# Cursor and Grok CLI installation plan

Goal: include Cursor CLI and official Grok Build CLI in every managed or existing
Ubuntu VM installed by agent-vms.

Use official versioned Linux x86-64 artifacts with SHA-256 values recorded in
versions.env. Install under /usr/local/lib/agent-vms/tools and link cursor-agent
and grok into /usr/local/bin. Do not install the conflicting generic agent alias.
Keep sign-in user-owned. A failed download must preserve the existing command.
The guest fingerprint includes the new installer; readiness executes both CLIs
as the guest account with bounded version checks.

- [x] Add subprocess tests for checksum rejection, preserving the existing tool
  on failure, and coexistence of the two command names.
- [x] Add setup/install-native-clis.sh; integrate it with versions.env,
  setup/install-guest.sh and setup/health.sh.
- [x] Update README and architecture with commands, installation and sign-in.
- [x] Run the local suite and lint, then create a disposable Ubuntu KVM VM.
  Check both version/help commands as agent, T3/desktop readiness and repeat up.
  Delete the fixture and record only non-private verification evidence.
- [x] Review the final diff and scan for secrets and private setup references.

Delivery uses the private repository; verify hosted CI after pushing the commit.
