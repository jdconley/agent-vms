# One-command T3 implementation plan

Goal: make the documented one-command remote setup work and prove it on Linux.

- [x] Add CLI acceptance tests for help, input validation, secret-free transfer,
  generated seed identity, state ownership, and nonzero failure handling.
- [x] Implement a standard-library CLI with remote SSH dispatch and safe local
  state. Add install/up/status/list/connect/stop/delete/doctor commands.
- [x] Implement a resumable Ubuntu guest installer: fixed agent user, Node/T3/
  coding tools, desktop/browser, loopback services, recording, and health checks.
- [x] Implement KVM host setup, immutable verified image acquisition, isolated
  networking, safe VM creation, guest provisioning, and SSH access.
- [x] Replace unsafe legacy launch/setup paths with migration guidance or wrappers.
- [x] Rewrite README, AGENTS.md, repository skill, architecture, SECURITY.md,
  contributing instructions, and CI around the supported workflow.
- [x] Run unit/subprocess tests and lint. Inspect failures before fixes.
- [x] Run a real Linux install/KVM/browser/reboot/retry/cleanup smoke test and
  record evidence: [verification notes](../../VERIFICATION.md).

Test entry point: `python3 -m unittest discover -s tests -v`.
Lint entry point: `./tests/lint.sh`.
Core setup verification is complete; optional phone access remains experimental.
