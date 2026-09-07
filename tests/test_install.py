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

    def test_host_network_isolates_guests(self):
        script = (ROOT / "setup/install-host.sh").read_text()
        self.assertIn("isolated='yes'", script)
        self.assertIn("iifname", script)


if __name__ == "__main__":
    unittest.main()
