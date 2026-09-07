#!/bin/bash
set -euo pipefail
echo 'Separate image builds are no longer needed. Run ./agent-vm up NAME --host USER@HOST.' >&2
echo 'Existing legacy VMs are not migrated automatically. See docs/MIGRATION.md.' >&2
exit 1
