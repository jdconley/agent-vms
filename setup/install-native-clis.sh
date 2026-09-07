#!/bin/bash
# Official native CLI artifacts, pinned independently of mutable vendor installers.
set -euo pipefail

install_native_cli() (
  set -euo pipefail
  name="$1" version="$2" url="$3" checksum="$4" layout="$5"
  tools_dir="${6:-/usr/local/lib/agent-vms/tools}" bin_dir="${7:-/usr/local/bin}"
  destination="$tools_dir/$name-$version"
  install -d -m 0755 "$tools_dir" "$bin_dir"
  if [ ! -x "$destination/$name" ] || [ "$(cat "$destination/.sha256" 2>/dev/null || true)" != "$checksum" ]; then
    staging="$(mktemp -d "$tools_dir/.download-XXXXXX")"
    trap 'rm -rf "$staging"' EXIT
    curl --fail --location --silent --show-error --retry 3 --connect-timeout 15 --max-time 600 \
      "$url" -o "$staging/artifact"
    printf '%s  %s\n' "$checksum" "$staging/artifact" | sha256sum -c - >/dev/null || {
      echo "Checksum mismatch for $name $version; existing command preserved." >&2
      exit 1
    }
    install -d -m 0755 "$staging/payload"
    case "$layout" in
      tar) tar --extract --gzip --strip-components=1 --no-same-owner --file "$staging/artifact" --directory "$staging/payload" ;;
      binary) install -m 0755 "$staging/artifact" "$staging/payload/$name" ;;
      *) echo "Unknown native CLI layout: $layout" >&2; exit 1 ;;
    esac
    [ -x "$staging/payload/$name" ] || { echo "Missing executable: $name" >&2; exit 1; }
    printf '%s\n' "$checksum" > "$staging/payload/.sha256"
    rm -rf "$destination"
    mv "$staging/payload" "$destination"
  fi
  ln -sfn "$destination/$name" "$bin_dir/$name"
)

if [ "${BASH_SOURCE[0]}" = "$0" ]; then
  SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  # shellcheck source=setup/common.sh
  source "$SCRIPT_DIR/common.sh"
  require_ubuntu
  require_root
  # shellcheck source=versions.env
  source "$SCRIPT_DIR/../versions.env"
  echo "Installing Cursor $CURSOR_VERSION and Grok Build $GROK_VERSION…"
  install_native_cli cursor-agent "$CURSOR_VERSION" \
    "https://downloads.cursor.com/lab/$CURSOR_VERSION/linux/x64/agent-cli-package.tar.gz" "$CURSOR_SHA256" tar
  install_native_cli grok "$GROK_VERSION" \
    "https://x.ai/cli/grok-$GROK_VERSION-linux-x86_64" "$GROK_SHA256" binary
fi
