#!/bin/bash
# Shared installer for a managed guest or an existing dedicated Ubuntu VM.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"
# shellcheck source=setup/common.sh
source "$SCRIPT_DIR/common.sh"
require_ubuntu
[ "${1:-}" != --check ] || exit 0
require_root
# shellcheck source=versions.env
source "$REPO_DIR/versions.env"
install -d -m 0755 /var/lib/agent-vms /usr/local/lib/agent-vms /etc/agent-vms
exec 8>/var/lib/agent-vms/guest-install.lock
flock -n 8 || { echo 'Another guest installer is still running. Wait, then retry.' >&2; exit 1; }
touch /var/log/agent-vms-install.log
chmod 600 /var/log/agent-vms-install.log
exec > >(tee -a /var/log/agent-vms-install.log >&2) 2>&1
trap 'echo "Guest setup failed at line $LINENO. Rerun to resume. Log: /var/log/agent-vms-install.log" >&2' ERR
FINGERPRINT="$(cat "$REPO_DIR/versions.env" "$SCRIPT_DIR/install-guest.sh" "$SCRIPT_DIR/install-native-clis.sh" "$SCRIPT_DIR/common.sh" "$REPO_DIR/lib/packages.py" "$SCRIPT_DIR/health.sh" "$REPO_DIR"/scripts/record-* | sha256sum | cut -d' ' -f1)"
if [ -f /var/lib/agent-vms/guest-version ] && [ "$(cat /var/lib/agent-vms/guest-version)" = "$FINGERPRINT" ]; then
  systemctl start vncserver@1.service t3-serve.service
  bash "$SCRIPT_DIR/health.sh"
  exit 0
fi
echo 'Installing desktop and development dependencies…'
apt-get -o DPkg::Lock::Timeout=120 update -qq
apt_install ca-certificates curl gnupg git build-essential python3 jq unzip sudo \
  xfce4 xfce4-terminal dbus-x11 tigervnc-standalone-server tigervnc-common \
  x11-utils x11-xserver-utils xdotool scrot ffmpeg openssh-server
if ! id agent >/dev/null 2>&1; then
  useradd --create-home --shell /bin/bash agent
fi
if [ "$(getent passwd agent | cut -d: -f6)" != /home/agent ]; then
  echo 'Existing agent account has a different home; refusing to modify it.' >&2
  exit 1
fi
install -d -m 0755 -o agent -g agent /home/agent
printf 'agent ALL=(ALL) NOPASSWD:ALL\n' > /etc/sudoers.d/agent-vms
chmod 440 /etc/sudoers.d/agent-vms
visudo -cf /etc/sudoers.d/agent-vms
install -d -m 0755 /etc/apt/keyrings
curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key | gpg --dearmor --yes -o /etc/apt/keyrings/nodesource.gpg
printf 'deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_%s.x nodistro main\n' "$NODE_MAJOR" > /etc/apt/sources.list.d/agent-vms-node.list
curl -fsSL https://dl.google.com/linux/linux_signing_key.pub | gpg --dearmor --yes -o /etc/apt/keyrings/google-chrome.gpg
echo 'deb [arch=amd64 signed-by=/etc/apt/keyrings/google-chrome.gpg] https://dl.google.com/linux/chrome/deb/ stable main' > /etc/apt/sources.list.d/agent-vms-chrome.list
apt-get -o DPkg::Lock::Timeout=120 update -qq
apt_install nodejs google-chrome-stable
echo "Installing T3 $T3_VERSION and coding providers…"
# NodeSource includes matching headers. Native addons can compile against them
# instead of depending on another download from nodejs.org during installation.
npm_package_config_node_gyp_nodedir=/usr npm install --global "t3@$T3_VERSION" "@openai/codex@$CODEX_VERSION" \
  "@anthropic-ai/claude-code@$CLAUDE_VERSION" "opencode-ai@$OPENCODE_VERSION"
bash "$SCRIPT_DIR/install-native-clis.sh"
cat > /etc/agent-vms/xstartup <<'EOF'
#!/bin/sh
unset SESSION_MANAGER DBUS_SESSION_BUS_ADDRESS
exec dbus-launch --exit-with-session startxfce4
EOF
chmod 755 /etc/agent-vms/xstartup
cat > /etc/systemd/system/vncserver@.service <<'EOF'
[Unit]
Description=Agent VM desktop on display %i (SSH access only)
After=network.target
[Service]
Type=simple
User=agent
WorkingDirectory=/home/agent
ExecStart=/usr/bin/tigervncserver -fg :%i -geometry 1280x800 -depth 24 -localhost yes -SecurityTypes None -xstartup /etc/agent-vms/xstartup
ExecStop=/usr/bin/tigervncserver -kill :%i
Restart=on-failure
RestartSec=3
[Install]
WantedBy=multi-user.target
EOF
cat > /etc/systemd/system/t3-serve.service <<'EOF'
[Unit]
Description=T3 Code (SSH access only)
After=network-online.target vncserver@1.service
Wants=network-online.target vncserver@1.service
[Service]
Type=simple
User=agent
WorkingDirectory=/home/agent
Environment=DISPLAY=:1
Environment=XAUTHORITY=/home/agent/.Xauthority
ExecStart=/usr/bin/env t3 serve --host 127.0.0.1 --port 3773 --no-browser
Restart=on-failure
RestartSec=3
[Install]
WantedBy=multi-user.target
EOF
install -m 0755 "$REPO_DIR/scripts/record-start" /usr/local/bin/record-start
install -m 0755 "$REPO_DIR/scripts/record-stop" /usr/local/bin/record-stop
install -m 0755 "$SCRIPT_DIR/health.sh" /usr/local/lib/agent-vms/health.sh
# install -d only applies ownership to the leaf directory. Create the XDG
# parent explicitly before .config/opencode so Chrome/Xfce can write settings.
install -d -m 0755 -o agent -g agent /home/agent/.config
for destination in .codex/AGENTS.md .claude/CLAUDE.md .config/opencode/AGENTS.md; do
  install -d -m 0755 -o agent -g agent "/home/agent/$(dirname "$destination")"
  if [ ! -f "/home/agent/$destination" ]; then
    cat > "/home/agent/$destination" <<'EOF'
# Your remote development computer

You are running as agent in your own Ubuntu VM. T3, Codex, Claude Code,
OpenCode, Cursor CLI (cursor-agent), Grok Build (grok), Git, Node.js, Python,
Chrome, Xfce, xdotool, scrot and ffmpeg are installed.
Use /home/agent/workspaces for repositories. Provider authentication belongs to
this VM; no host credentials are mounted or synchronized.

For GUI commands use DISPLAY=:1 and XAUTHORITY=/home/agent/.Xauthority.
Launch Chrome with google-chrome-stable (keep its sandbox enabled).
Use xdotool for mouse/keyboard and scrot /tmp/screenshot.png for screenshots;
inspect screenshots using your image-viewing tool. For visual verification,
run record-start TASK, perform the interaction, then record-stop. Return the
recording path in your result. Recordings live in /home/agent/recordings.
Do not include credentials, pairing URLs or authentication screens in recordings.
EOF
    chown agent:agent "/home/agent/$destination"
  fi
done
install -d -m 0755 -o agent -g agent /home/agent/workspaces /home/agent/recordings
systemctl daemon-reload
systemctl enable vncserver@1.service t3-serve.service
systemctl restart vncserver@1.service t3-serve.service
bash "$SCRIPT_DIR/health.sh"
printf '%s\n' "$FINGERPRINT" > /var/lib/agent-vms/guest-version
echo 'T3 and the desktop are ready. Provider sign-in happens inside this VM.'
