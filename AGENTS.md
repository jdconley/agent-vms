# Set up T3 Code for the user

This repository is an installer and lifecycle tool. When asked to set up a T3
instance, perform the setup; do not merely explain these commands.

## Choose the target

1. Identify the user's SSH alias/address. Ask only if it is unavailable in the
   conversation or their specified deployment configuration.
2. For a Linux KVM host, run `./agent-vm up NAME --host USER@HOST`.
3. For an existing dedicated VM without nested KVM, run
   `./agent-vm install --host USER@VM`.

Targets must be Ubuntu 24.04 x86-64 with Python 3 and root/passwordless-sudo SSH.
Use `./agent-vm doctor --host USER@HOST --json` for preflight. On a Linux host
directly, omit `--host` and use sudo. On macOS, supply a remote host.

The CLI uploads only installer source, installs dependencies, checks readiness,
and creates a secure tunnel. Run from the cloned repository; no local
configuration file, image build or shared credential store is needed. Keep the
command running during installation and monitor its actual process handle. Rerun
the same command to resume a failed setup. Do not delete/recreate a VM to mask
an error.

Use `./agent-vm run [NAME] --host HOST --command 'COMMAND'` to execute setup,
repository clones, diagnostics or provider device-login commands as `agent`
inside the guest. Output streams to stderr while `--json` keeps the result on
stdout structured. Keep tokens out of command arguments and logs.

## Finish the handoff

- Check `status NAME --host USER@HOST --json` (omit NAME for an existing VM).
- Open the returned pairing link in the user's browser when possible; verify
  the page renders. The localhost link belongs to the controller where the
  command ran, not a phone or an unrelated agent sandbox.
- Verify `ssh avm-NAME true` (existing VM: `avm-HOSTNAME`) for Claude Code,
  Codex and editor access. If `up` reports SSH was not configured, fix the cause
  and run `ssh-config [NAME] --host USER@HOST`.
- Provider and GitHub accounts require the user's authorization in T3 or the
  guest CLI (`gh auth login`, then `gh auth setup-git`).
  Never copy their personal SSH private key, host login tokens, or browser profile.
- For phone access, run `mobile [NAME] --host USER@HOST` and surface Tailscale's
  authorization link. Wait for actual user authorization; elapsed time is not
  approval. Then verify the HTTPS pairing endpoint from the intended device.
- Treat pairing URLs as credentials: don't commit them or publish them in issues,
  transcripts or screenshots. Return the usable result in the current session.
- Don't report success based only on VM creation, an SSH connection or unit tests.
  The HTTP endpoint and desktop must be healthy, and the remote access must work.

## Developing this repository

Use Python's standard library and Bash. The controller must not need pip/npm
installation. Run `python3 -m unittest discover -s tests -v` and `./tests/lint.sh`.
Use the real Linux smoke-test procedure in CONTRIBUTING.md for provisioning
changes. Keep managed state, ownership checks, and immutable backing images.
Do not modify unrelated host networks or adopt VMs this tool did not create.
