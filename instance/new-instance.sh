#!/bin/bash
# Compatibility entry point. Legacy config.local is no longer sourced.
set -euo pipefail
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec "$REPO_DIR/agent-vm" up "$@"
