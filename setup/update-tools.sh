#!/bin/bash
# Keep the agent-owned coding tools current.
#   t3           before t3-serve starts: install a newer T3, never fail the start
#   t3-outdated  exit 0 when npm has a different T3 than the installed one
#   clis         run each coding CLI's own updater (as agent)
#   now          as root: update CLIs, restart T3 only if newer, check health
set -uo pipefail
NPM_FETCH=(--fetch-timeout=20000 --fetch-retries=1)
TOOLS=(t3 codex claude opencode cursor-agent grok)
installed_t3() { t3 --version 2>/dev/null | grep -oE '[0-9]+\.[0-9]+\.[0-9]+[^ ]*' | head -n1; }
latest_t3() { timeout 60 npm view "${NPM_FETCH[@]}" t3 version 2>/dev/null; }
case "${1:-}" in
  t3)
    latest="$(latest_t3)"
    if [ -z "$latest" ]; then
      echo 'npm registry unavailable; starting the installed T3.' >&2
      exit 0
    fi
    [ "$latest" != "$(installed_t3)" ] || exit 0
    echo "Updating T3 to $latest before it starts…" >&2
    npm_package_config_node_gyp_nodedir=/usr timeout 600 npm install -g "${NPM_FETCH[@]}" "t3@$latest" >&2 \
      || echo 'T3 update failed; starting the installed version.' >&2
    exit 0 ;;
  t3-outdated)
    latest="$(latest_t3)"
    [ -n "$latest" ] && [ "$latest" != "$(installed_t3)" ] ;;
  clis)
    failed=()
    for updater in "claude update" "codex update" "opencode upgrade" "cursor-agent update" "grok update"; do
      echo "== $updater" >&2
      # Word splitting separates each command from its update subcommand.
      # shellcheck disable=SC2086
      timeout 600 $updater </dev/null >&2 || failed+=("$updater")
    done
    if [ "${#failed[@]}" -gt 0 ]; then
      echo "Updates failed: ${failed[*]}. The previous versions remain installed." >&2
      exit 1
    fi ;;
  now)
    [ "$(id -u)" = 0 ] || { echo 'Run as root.' >&2; exit 1; }
    status=0
    systemctl start agent-vms-update.service || {
      echo 'Some tools did not update; see: journalctl -u agent-vms-update' >&2
      status=1
    }
    if runuser -u agent -- env HOME=/home/agent "$0" t3-outdated; then
      echo 'A newer T3 is available. Restarting T3 now; running agent sessions end.' >&2
      systemctl restart t3-serve.service || status=1
    fi
    bash "$(dirname "$0")/health.sh" >&2 || status=1
    for tool in "${TOOLS[@]}"; do
      printf 'version %s %s\n' "$tool" "$(runuser -u agent -- env HOME=/home/agent timeout 30 "$tool" --version 2>&1 | head -n1)"
    done
    exit "$status" ;;
  *)
    echo 'Usage: update-tools.sh t3|t3-outdated|clis|now' >&2
    exit 2 ;;
esac
