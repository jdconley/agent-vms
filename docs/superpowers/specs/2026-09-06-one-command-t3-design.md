# One-command remote T3

The requested outcome is a repository any coding agent can use to create and
configure a remote VM, with usable T3 access and installed development tools.
The existing KVM workflow stays the primary VM provider. An existing Ubuntu VM
can also receive the same guest installation without nested virtualization.

## Interface

`./agent-vm up NAME --host USER@HOST` installs host dependencies, prepares a
versioned image, creates or resumes an owned VM, installs its guest tools, and
checks T3 readiness. With no host, it runs on the current Linux KVM host.
`./agent-vm install --host USER@VM` installs into an existing dedicated VM.
`connect`, `status`, `list`, `stop`, `delete`, and `doctor` make lifecycle and
recovery discoverable. Deletion requires an explicit flag and never targets
unmanaged domains. Arguments, remote execution, and machine state use structured
data rather than sourced deployment configuration.

## Access and identity

T3 and VNC listen on loopback. SSH tunnels supply browser access without public
ports. For a KVM guest, the host tunnels to guest loopback using a per-instance
management key; the key never enters the guest. Tailscale is opt-in and its
authentication step is surfaced honestly. Provider authentication occurs in the
guest through T3 or its CLIs. No shared host-account key or provider credentials
are copied by default. The guest user is consistently `agent`.

## Implementation boundaries

A Python-standard-library CLI validates inputs, dispatches SSH, stores state,
and orchestrates libvirt. Bash scripts install Ubuntu packages and guest tools.
The base is an immutable checksum-verified Ubuntu cloud image; first-boot guest
installation replaces the mandatory Packer build, so one command has no manual
image installation step. Reusing the immutable downloaded base keeps subsequent
VM creation cheap. Packer's legacy entry point will be retired or routed through
the supported workflow rather than leaving two conflicting installation paths.

Each managed VM has a state directory, dedicated SSH identity, seed, and disk.
The libvirt network isolates guest ports and host firewall rules limit guest
access to host services and private networks while allowing DHCP/DNS and public
internet. State transitions are restartable; failures retain diagnostic state
and exit nonzero. Existing domains and disk paths are never overwritten.

## Verification requirements

Unit and subprocess tests exercise validation, archive contents, SSH quoting,
state ownership, failure propagation, safe deletion, and cloud-init generation.
ShellCheck and Python compilation run in CI. A real Ubuntu KVM smoke test must
create a VM using the documented command, reach the authenticated T3 pairing
page through its tunnel, check desktop recording, rerun provisioning, reboot,
and remove only its own test resources. An existing-VM install must likewise
be checked on Linux. Local mocks alone cannot establish completion.

## Alternatives considered

Keeping mandatory Packer builds is familiar but adds another tool and lengthy
build phase before first use. Cloud-provider APIs remove the KVM requirement but
introduce accounts, billing, and provider-specific provisioning. Starting with
KVM plus existing-VM installation serves the repository's stated scope while
leaving a clear boundary for future providers.
