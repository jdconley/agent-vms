#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
python3 -m compileall -q agent-vm lib tests
while IFS= read -r script; do
  bash -n "$script"
done < <(find setup instance image scripts tests -type f \( -name '*.sh' -o -name 'record-start' -o -name 'record-stop' \))
shellcheck -x setup/*.sh instance/*.sh image/*.sh scripts/record-* tests/*.sh
git diff --check
