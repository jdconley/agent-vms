#!/bin/bash
# Opt-in phone access. Tailnet authorization is deliberately user-owned.
set -euo pipefail
# Keep package/auth progress visible while the caller captures only pairing data.
exec 3>&1
exec 1>&2
if [ "$(id -u)" -ne 0 ]; then
  echo 'Run as root.' >&2
  exit 1
fi
if ! command -v tailscale >/dev/null; then
  install -d -m 0755 /usr/share/keyrings
  curl -fsSL https://pkgs.tailscale.com/stable/ubuntu/noble.noarmor.gpg -o /usr/share/keyrings/tailscale-archive-keyring.gpg
  curl -fsSL https://pkgs.tailscale.com/stable/ubuntu/noble.tailscale-keyring.list -o /etc/apt/sources.list.d/tailscale.list
  apt-get update -qq
  DEBIAN_FRONTEND=noninteractive apt-get -o DPkg::Lock::Timeout=120 install -y tailscale
fi
systemctl enable --now tailscaled
if ! tailscale status --json | python3 -c 'import json,sys; sys.exit(json.load(sys.stdin).get("BackendState") != "Running")'; then
  echo 'Authorize this VM using the Tailscale link below, then rerun mobile if it times out.' >&2
  tailscale up --operator=agent --timeout=60s
fi
tailscale set --operator=agent
runuser -l agent -c 't3 pair --tailscale' >&3
