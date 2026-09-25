from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class InstallTests(unittest.TestCase):
    def test_guest_installer_rejects_unsupported_os_before_mutations(self):
        result = subprocess.run(["bash", str(ROOT / "setup/install-guest.sh"), "--check"], capture_output=True, text=True)
        self.assertIn("Ubuntu 24.04", result.stdout + result.stderr)

    def test_service_templates_never_listen_publicly(self):
        path = ROOT / "setup/install-guest.sh"
        self.assertTrue(path.exists(), "Guest installer is missing")
        script = path.read_text()
        self.assertIn("--host 127.0.0.1", script)
        self.assertIn("-localhost yes", script)
        service_users = [line for line in script.splitlines() if line.startswith("User=")]
        self.assertEqual(service_users, ["User=agent"] * 3, "Desktop, T3 and the updater all run as agent")
        self.assertNotIn("I-KNOW-THIS-IS-INSECURE", script)

    def test_coding_tools_are_installed_by_agent_so_they_can_update(self):
        script = (ROOT / "setup/install-guest.sh").read_text()
        self.assertNotRegex(script, r"npm[^\n]* install --global", "Root-owned tools cannot update themselves")
        self.assertIn("runuser -u agent -- env HOME=/home/agent bash /usr/local/lib/agent-vms/install-agent-tools.sh",
                      script)
        for mapping in ("t3:.local/bin/t3", "codex:.local/bin/codex", "opencode:.local/bin/opencode",
                        "claude:.local/bin/claude", "cursor-agent:.local/bin/cursor-agent", "grok:.grok/bin/grok"):
            self.assertIn(mapping, script)
        self.assertIn('ln -sfn "/home/agent/${link#*:}" "/usr/local/bin/${link%%:*}"', script)

    def test_earlier_root_installs_are_removed(self):
        script = (ROOT / "setup/install-guest.sh").read_text()
        self.assertIn("for package in t3 @openai/codex @anthropic-ai/claude-code opencode-ai; do", script)
        self.assertIn('npm uninstall --global "${legacy[@]}"', script)
        self.assertIn("rm -rf /usr/local/lib/agent-vms/tools", script)
        self.assertFalse((ROOT / "setup/install-native-clis.sh").exists())

    def test_t3_updates_only_when_its_service_starts(self):
        script = (ROOT / "setup/install-guest.sh").read_text()
        # The leading "-" lets T3 start with the installed version when offline.
        self.assertIn("ExecStartPre=-/usr/local/lib/agent-vms/update-tools.sh t3", script)
        self.assertIn("ExecStart=/usr/local/bin/t3 serve --host 127.0.0.1 --port 3773 --no-browser", script)
        self.assertIn("TimeoutStartSec=900", script)

    def test_a_daily_timer_runs_every_tools_updater(self):
        script = (ROOT / "setup/install-guest.sh").read_text()
        self.assertIn("ExecStart=/usr/local/lib/agent-vms/update-tools.sh clis", script)
        for setting in ("OnCalendar=daily", "RandomizedDelaySec=2h", "Persistent=true", "WantedBy=timers.target"):
            self.assertIn(setting, script)
        self.assertIn("systemctl enable --now agent-vms-update.timer", script)

    def test_installer_fingerprint_covers_the_new_scripts(self):
        fingerprint = next(line for line in (ROOT / "setup/install-guest.sh").read_text().splitlines()
                           if line.startswith("FINGERPRINT="))
        self.assertIn("install-agent-tools.sh", fingerprint)
        self.assertIn("update-tools.sh", fingerprint)
        self.assertNotIn("install-native-clis.sh", fingerprint)

    def test_only_node_is_pinned(self):
        settings = [line.split("=", 1)[0] for line in (ROOT / "versions.env").read_text().splitlines()
                    if line and not line.startswith("#")]
        self.assertEqual(settings, ["NODE_MAJOR"])

    def test_health_runs_every_agent_owned_coding_tool(self):
        health = (ROOT / "setup/health.sh").read_text()
        self.assertIn("for tool in t3 codex claude opencode cursor-agent grok; do", health)
        # A leftover root copy would shadow the agent's self-updating one.
        self.assertIn('case "$(readlink -f "/usr/local/bin/$tool")" in /home/agent/*)', health)

    def test_github_cli_comes_from_githubs_signed_repository(self):
        script = (ROOT / "setup/install-guest.sh").read_text()
        keyring = "/etc/apt/keyrings/githubcli-archive-keyring.gpg"
        # GitHub publishes a binary keyring; it must not go through gpg --dearmor.
        self.assertIn(f"https://cli.github.com/packages/githubcli-archive-keyring.gpg -o {keyring}", script)
        self.assertIn(f"signed-by={keyring}] https://cli.github.com/packages stable main", script)
        installs = [line for line in script.splitlines() if line.startswith("apt_install")]
        self.assertTrue(any(" gh" in f" {line} " or line.endswith(" gh") for line in installs),
                        "gh must be installed with the other signed-repository packages")

    def test_health_requires_github_cli(self):
        tools = next(line for line in (ROOT / "setup/health.sh").read_text().splitlines()
                     if line.startswith("for tool in") and "t3" in line)
        self.assertIn(" gh ", f" {tools} ")

    def test_agents_are_told_how_github_sign_in_works(self):
        script = (ROOT / "setup/install-guest.sh").read_text()
        self.assertIn("gh auth status", script)
        self.assertIn("never ask for a token", script.lower())

    def test_host_network_isolates_guests(self):
        script = (ROOT / "setup/install-host.sh").read_text()
        self.assertIn("isolated='yes'", script)
        self.assertIn("iifname", script)


if __name__ == "__main__":
    unittest.main()
