---
name: t3-instance
description: Create, install, reconnect to, or inspect a remote T3 Code VM using agent-vms. Use for requests to set up T3 on a Linux host, create an agent VM, or connect from a laptop or phone.
---

# Remote T3 instance

Read the repository's [AGENTS.md](../../../AGENTS.md) and follow its setup and
verification workflow. Run from the repository root on the controller:

```bash
./agent-vm up PROJECT --host USER@KVM_HOST
```

For a dedicated VM that already exists:

```bash
./agent-vm install --host USER@VM
```

`up` and `install` also create the SSH host `avm-PROJECT` for Claude Code, Codex
and editors; `ssh-config [PROJECT] --host HOST` repairs or adds it on another computer.
Use `connect [PROJECT] --host HOST` to reconnect, `status [PROJECT] --host HOST`
to verify, and `mobile [PROJECT] --host HOST` for opt-in Tailscale HTTPS. Omit
PROJECT for existing-VM installs. `--json` gives structured output and disables
automatic tunneling during installation. Actual account authorization belongs
to the user; never transfer host credentials to simulate a logged-in result.

Keep failed instances for diagnosis and rerun the same command to resume.
Only retire a managed VM when requested with `delete PROJECT --host HOST --yes`.
