#!/bin/bash
# Bounded readiness check: systemd state alone does not prove HTTP/X11 readiness.
set -euo pipefail
for tool in t3 codex claude opencode cursor-agent grok google-chrome-stable ffmpeg xdotool scrot; do
  command -v "$tool" >/dev/null || { echo "Missing tool: $tool" >&2; exit 1; }
done
runuser -u agent -- test -w /home/agent/.config || {
  echo 'Agent settings directory is not writable. Repair with: sudo install -d -m 0755 -o agent -g agent /home/agent/.config' >&2
  exit 1
}
for tool in cursor-agent grok; do
  runuser -u agent -- env HOME=/home/agent timeout 30 "$tool" --version >/dev/null || {
    echo "Cannot run $tool as agent. Rerun the installer and inspect its log." >&2
    exit 1
  }
done
for _ in $(seq 1 30); do
  if systemctl is-active --quiet t3-serve.service vncserver@1.service && \
     curl --fail --silent --max-time 2 http://127.0.0.1:3773/.well-known/t3/environment >/dev/null && \
     runuser -u agent -- env DISPLAY=:1 XAUTHORITY=/home/agent/.Xauthority xdpyinfo >/dev/null 2>&1; then
    echo 'T3 HTTP endpoint, X11 desktop and required tools are healthy.'
    exit 0
  fi
  sleep 2
done
echo 'Readiness timed out. Inspect: sudo journalctl -u t3-serve -u vncserver@1 --no-pager -n 80' >&2
exit 1
