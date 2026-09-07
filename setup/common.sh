#!/bin/bash
# Shared preflight; sourcing this file makes no changes.
set -euo pipefail
require_ubuntu() {
  if [ "$(uname -s)" != Linux ] || [ ! -r /etc/os-release ]; then
    echo 'Requires Ubuntu 24.04 x86-64. Use --host user@ubuntu-machine.' >&2
    return 1
  fi
  # shellcheck disable=SC1091
  . /etc/os-release
  if [ "$ID" != ubuntu ] || [ "$VERSION_ID" != 24.04 ] || [ "$(uname -m)" != x86_64 ]; then
    echo 'Requires Ubuntu 24.04 x86-64; this machine is unsupported.' >&2
    return 1
  fi
  echo 'Ubuntu 24.04 x86-64 detected.' >&2
}
require_root() {
  if [ "$(id -u)" -ne 0 ]; then
    echo 'Run with sudo, or use --host with a passwordless-sudo account.' >&2
    return 1
  fi
}
apt_install() {
  python3 "$(dirname "${BASH_SOURCE[0]}")/../lib/packages.py"
  DEBIAN_FRONTEND=noninteractive apt-get -o DPkg::Lock::Timeout=120 install -y "$@"
}
