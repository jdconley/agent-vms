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
        self.assertEqual(service_users, ["User=agent", "User=agent"])
        self.assertNotIn("I-KNOW-THIS-IS-INSECURE", script)

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
