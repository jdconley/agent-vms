#!/bin/bash
# Runs as agent. Installs missing coding CLIs where their own updaters can
# replace them; an installed tool is left to its updater.
set -euo pipefail
export PATH="$HOME/.local/bin:$HOME/.grok/bin:$PATH"
npm config set prefix "$HOME/.local"
missing=()
for entry in t3:t3 codex:@openai/codex opencode:opencode-ai; do
  [ -x "$HOME/.local/bin/${entry%%:*}" ] || missing+=("${entry#*:}@latest")
done
if [ "${#missing[@]}" -gt 0 ]; then
  echo "Installing ${missing[*]}…"
  # NodeSource includes matching headers, so native addons need no extra download.
  npm_package_config_node_gyp_nodedir=/usr npm install -g "${missing[@]}"
fi
vendor_install() {
  local name="$1" command="$2" url="$3" script
  [ -x "$command" ] && return 0
  echo "Installing $name with its official installer…"
  script="$(mktemp)"
  # Download completely before running so a truncated script never executes.
  curl --fail --silent --show-error --location --retry 3 --connect-timeout 15 --max-time 300 "$url" -o "$script"
  bash "$script" </dev/null || { rm -f "$script"; echo "$name installer failed." >&2; return 1; }
  rm -f "$script"
  [ -x "$command" ] || { echo "$name installer finished without $command." >&2; return 1; }
}
vendor_install 'Claude Code' "$HOME/.local/bin/claude" https://claude.ai/install.sh
vendor_install 'Cursor CLI' "$HOME/.local/bin/cursor-agent" https://cursor.com/install
vendor_install 'Grok Build' "$HOME/.grok/bin/grok" https://x.ai/cli/install.sh
