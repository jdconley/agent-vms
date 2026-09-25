"""The guest updater, run for real against fake npm, CLIs and systemd tools."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
CLIS = ("claude", "codex", "opencode", "cursor-agent", "grok")

FAKES = {
    "npm": '''#!/bin/bash
echo "npm $*" >> "$LOG"
if [ "$1" = view ]; then
  [ -n "${REGISTRY_T3:-}" ] || exit 1
  echo "$REGISTRY_T3"
  exit 0
fi
[ "$1" != install ] || exit "${NPM_INSTALL_EXIT:-0}"
''',
    "t3": '''#!/bin/bash
echo "t3 v$INSTALLED_T3"
''',
    # A real timeout is absent on macOS; the duration is not under test.
    "timeout": '''#!/bin/bash
shift
exec "$@"
''',
    "id": '''#!/bin/bash
echo 0
''',
    "systemctl": '''#!/bin/bash
echo "systemctl $*" >> "$LOG"
[ "$*" != "${SYSTEMCTL_FAIL:-}" ]
''',
    # runuser -u agent -- COMMAND...: the account switch is not under test.
    "runuser": '''#!/bin/bash
shift 3
exec "$@"
''',
}

CLI_FAKE = '''#!/bin/bash
name="$(basename "$0")"
if [ "$1" = --version ]; then echo "$name 9.9.9"; exit 0; fi
if [ -t 0 ]; then input=terminal; else input=no-terminal; fi
echo "$name $* $input" >> "$LOG"
[ "$name" != "${FAIL_TOOL:-}" ]
'''


class UpdateToolsTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        self.log = root / "calls.log"
        self.log.touch()
        binary = root / "bin"
        binary.mkdir()
        for name, body in FAKES.items():
            (binary / name).write_text(body)
        for name in CLIS:
            (binary / name).write_text(CLI_FAKE)
        for fake in binary.iterdir():
            fake.chmod(0o755)
        library = root / "lib"
        library.mkdir()
        self.script = library / "update-tools.sh"
        shutil.copy(ROOT / "setup/update-tools.sh", self.script)
        (library / "health.sh").write_text('echo health >> "$LOG"; exit "${HEALTH_EXIT:-0}"\n')
        self.environment = {**os.environ, "PATH": f"{binary}{os.pathsep}{os.environ['PATH']}",
                            "LOG": str(self.log), "INSTALLED_T3": "0.0.38"}

    def run_mode(self, mode, **environment):
        return subprocess.run(["bash", str(self.script), mode], capture_output=True, text=True,
                              stdin=subprocess.DEVNULL, env={**self.environment, **environment})

    def calls(self):
        return self.log.read_text().splitlines()

    def test_t3_installs_a_newer_registry_version(self):
        result = self.run_mode("t3", REGISTRY_T3="0.0.42")
        self.assertEqual(result.returncode, 0, result.stderr)
        installs = [call for call in self.calls() if call.startswith("npm install")]
        self.assertEqual(len(installs), 1)
        self.assertIn("-g", installs[0])
        self.assertIn("t3@0.0.42", installs[0])

    def test_t3_leaves_the_current_version_alone(self):
        result = self.run_mode("t3", REGISTRY_T3="0.0.38")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(any(call.startswith("npm install") for call in self.calls()))

    def test_t3_starts_the_installed_version_when_offline(self):
        result = self.run_mode("t3")
        self.assertEqual(result.returncode, 0, "An unreachable registry must never block T3")
        self.assertFalse(any(call.startswith("npm install") for call in self.calls()))

    def test_t3_starts_the_installed_version_when_install_fails(self):
        result = self.run_mode("t3", REGISTRY_T3="0.0.42", NPM_INSTALL_EXIT="1")
        self.assertEqual(result.returncode, 0)
        self.assertIn("installed version", result.stderr)

    def test_t3_outdated_reports_only_a_reachable_different_version(self):
        self.assertEqual(self.run_mode("t3-outdated", REGISTRY_T3="0.0.42").returncode, 0)
        self.assertNotEqual(self.run_mode("t3-outdated", REGISTRY_T3="0.0.38").returncode, 0)
        self.assertNotEqual(self.run_mode("t3-outdated").returncode, 0)

    def test_clis_runs_every_tools_own_updater_without_a_terminal(self):
        result = self.run_mode("clis")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.calls(), [
            "claude update no-terminal", "codex update no-terminal", "opencode upgrade no-terminal",
            "cursor-agent update no-terminal", "grok update no-terminal"])

    def test_clis_continues_after_a_failure_and_reports_it(self):
        result = self.run_mode("clis", FAIL_TOOL="codex")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(len(self.calls()), 5, "Later tools must still update")
        self.assertIn("codex update", result.stderr)

    def test_now_restarts_t3_only_when_it_is_outdated(self):
        result = self.run_mode("now", REGISTRY_T3="0.0.38")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("systemctl start agent-vms-update.service", self.calls())
        self.assertFalse(any("restart t3-serve" in call for call in self.calls()))
        self.assertIn("health", self.calls())
        self.assertIn("version codex codex 9.9.9", result.stdout.splitlines())
        self.assertIn("version t3 t3 v0.0.38", result.stdout.splitlines())

    def test_now_warns_before_restarting_an_outdated_t3(self):
        result = self.run_mode("now", REGISTRY_T3="0.0.42")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("systemctl restart t3-serve.service", self.calls())
        self.assertIn("sessions", result.stderr)

    def test_now_reports_failed_updates_but_still_lists_versions(self):
        result = self.run_mode("now", REGISTRY_T3="0.0.38", SYSTEMCTL_FAIL="start agent-vms-update.service")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("journalctl -u agent-vms-update", result.stderr)
        self.assertEqual(sum(line.startswith("version ") for line in result.stdout.splitlines()), 6)


if __name__ == "__main__":
    unittest.main()
