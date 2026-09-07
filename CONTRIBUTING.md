# Contributing

The controller uses Python 3.10+ without external Python packages. Installer
targets are Ubuntu 24.04 x86-64. Keep the first command usable by another agent:
explicit inputs, actionable failures, bounded waits, and inspectable state.

Run local checks:

```bash
python3 -m unittest discover -s tests -v
./tests/lint.sh
```

ShellCheck is required for linting. Tests that mutate infrastructure must never
run implicitly on a contributor's host. Unit tests use temporary directories and
mock subprocess boundaries; they do not prove a VM can boot or T3 can render.

## Before a release or provisioning change

Use a disposable Ubuntu 24.04 x86-64 KVM host with passwordless-sudo SSH. Record
the commit, tool versions and results, excluding credentials and pairing tokens.

1. Run `./agent-vm up smoke-test --host HOST`. Confirm creation, guest install,
   endpoint health and the generated controller tunnel.
2. Open the pairing link in a browser on the controller, complete pairing and
   check that T3 renders. Test provider sign-in only with an authorized account.
   Check `cursor-agent --version` and `grok --version` as the guest's `agent` user.
   When changing either native CLI pin, download the versioned artifact from its
   official installer source, update its SHA-256 in `versions.env`, and repeat
   the runtime check. Do not substitute third-party packages with similar names.
3. In the VM, use Chrome on display :1 and record a short interaction using
   `record-start smoke` and `record-stop`. Check the MP4 with ffprobe and playback.
4. Rerun `up` with the same name/resources. Verify it preserves guest files and
   does not replace its disk, UUID or backing image.
5. Stop the guest, wait for it to power off, then run `up` again. Verify services
   and desktop recover. Reboot the host and recheck firewall/network/service state.
6. Create a second managed guest. Confirm it cannot connect to the first guest's
   SSH/VNC/T3 ports or host SSH/private services; public HTTPS and DHCP/DNS work.
7. Interrupt a guest install, then rerun and verify recovery. Try invalid inputs,
   a foreign existing domain, wrong UUID metadata and unavailable remote SSH.
8. Run `delete smoke-test --host HOST --yes`. Confirm only owned resources are
   removed, then clean up the second test guest.
9. Separately exercise `install --host EXISTING_VM` and `connect --host EXISTING_VM`
   on a fresh dedicated VM without KVM. Rerun installation and verify persistence.
10. For mobile changes, authorize a disposable Tailscale node, check T3 HTTPS from
    a tailnet device, and remove that node after testing.

Do not declare the release verified until these actual runtime checks pass.
