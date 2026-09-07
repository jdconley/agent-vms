# Migrating from the original prototype

Existing VMs, images and host keys are not modified automatically. The new CLI
creates separately tracked VMs and refuses to adopt a same-named foreign domain.
Choose a new name for the first new instance and migrate your repositories and
work intentionally. Reauthenticate providers inside the new VM.

The old Packer build and shared push/pull credential store have been retired.
`instance/new-instance.sh` and `instance/connect.sh` are compatibility wrappers
around the new CLI; `instance/config.local` is no longer sourced.

If you previously ran `setup/setup-creds-store.sh`, each old guest has a private
key capable of SSH access to the host account. Review and remove the matching
`creds-sync` public key from that account's `~/.ssh/authorized_keys` when retiring
the old setup. Do not remove unrelated authorized keys. Deleting old guest files
alone does not revoke a copied private key. Treat provider credentials held in
old guests according to your own rotation policy.

Do not overwrite a backing qcow2 image used by existing overlays. Keep it until
all dependent guests have been migrated or retired. The new CLI stores base
images by checksum to avoid replacement.

The new guest account is always `agent`; the old INSTANCE_USER setting is retired.
T3 and VNC are accessible through SSH tunnels by default. Use `mobile` for Tailscale access.
