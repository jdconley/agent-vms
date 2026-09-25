"""Installing coding tools as agent, run for real against fake npm and curl."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]

NPM = '''#!/bin/bash
echo "npm $*" >> "$LOG"
if [ "$1 $2" = "install -g" ]; then
  shift 2
  for spec in "$@"; do
    case "$spec" in
      t3@*) name=t3 ;;
      @openai/codex@*) name=codex ;;
      opencode-ai@*) name=opencode ;;
      *) continue ;;
    esac
    mkdir -p "$HOME/.local/bin"
    printf '#!/bin/sh\\n' > "$HOME/.local/bin/$name"
    chmod +x "$HOME/.local/bin/$name"
  done
fi
'''

# Writes a vendor installer that creates the command that vendor's script would.
CURL = '''#!/bin/bash
echo "curl $*" >> "$LOG"
out="" url=""
while [ $# -gt 0 ]; do
  case "$1" in
    -o) out="$2"; shift ;;
    https://*) url="$1" ;;
  esac
  shift
done
[ -n "$out" ] || { echo "fake curl: expected -o FILE" >&2; exit 2; }
case "$url" in
  https://claude.ai/*) target="$HOME/.local/bin/claude" ;;
  https://cursor.com/*) target="$HOME/.local/bin/cursor-agent" ;;
  https://x.ai/*) target="$HOME/.grok/bin/grok" ;;
esac
if [ "$url" = "${BROKEN_INSTALLER:-}" ]; then
  echo 'echo "ran broken installer" >> "$LOG"' > "$out"
else
  printf 'mkdir -p "%s"; printf "#!/bin/sh\\\\n" > "%s"; chmod +x "%s"; echo "ran installer %s" >> "$LOG"\\n' \\
    "$(dirname "$target")" "$target" "$target" "$url" > "$out"
fi
'''


class AgentToolsTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        self.home = root / "home"
        self.home.mkdir()
        self.log = root / "calls.log"
        self.log.touch()
        binary = root / "bin"
        binary.mkdir()
        for name, body in (("npm", NPM), ("curl", CURL)):
            (binary / name).write_text(body)
            (binary / name).chmod(0o755)
        self.environment = {**os.environ, "HOME": str(self.home), "LOG": str(self.log),
                            "PATH": f"{binary}{os.pathsep}{os.environ['PATH']}"}

    def install(self, **environment):
        return subprocess.run(["bash", str(ROOT / "setup/install-agent-tools.sh")], capture_output=True,
                              text=True, stdin=subprocess.DEVNULL, env={**self.environment, **environment})

    def calls(self, prefix):
        return [line for line in self.log.read_text().splitlines() if line.startswith(prefix)]

    def test_first_run_installs_every_tool_where_agent_can_update_it(self):
        result = self.install()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f"npm config set prefix {self.home}/.local", self.calls("npm config"))
        self.assertEqual(self.calls("npm install"),
                         ["npm install -g t3@latest @openai/codex@latest opencode-ai@latest"])
        downloads = self.calls("curl")
        self.assertEqual([next(a for a in line.split() if a.startswith("https://")) for line in downloads],
                         ["https://claude.ai/install.sh", "https://cursor.com/install", "https://x.ai/cli/install.sh"])
        for line in downloads:
            self.assertIn("--fail", line.split(), "A failed download must not produce a script to run")
        self.assertEqual(len(self.calls("ran installer")), 3)
        for command in (".local/bin/t3", ".local/bin/codex", ".local/bin/opencode", ".local/bin/claude",
                        ".local/bin/cursor-agent", ".grok/bin/grok"):
            self.assertTrue(os.access(self.home / command, os.X_OK), command)

    def test_installed_tools_are_left_to_their_own_updaters(self):
        self.install()
        self.log.write_text("")
        result = self.install()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.calls("npm install"), [])
        self.assertEqual(self.calls("curl"), [])

    def test_only_missing_npm_tools_are_installed(self):
        self.install()
        (self.home / ".local/bin/codex").unlink()
        self.log.write_text("")
        self.install()
        self.assertEqual(self.calls("npm install"), ["npm install -g @openai/codex@latest"])

    def test_installer_that_does_not_create_its_command_fails_by_name(self):
        result = self.install(BROKEN_INSTALLER="https://x.ai/cli/install.sh")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Grok Build", result.stderr)


if __name__ == "__main__":
    unittest.main()
