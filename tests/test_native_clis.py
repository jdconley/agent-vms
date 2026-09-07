import hashlib
import io
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class NativeCliTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.bins = self.root / "bin"
        self.tools = self.root / "tools"

    def install(self, name, version, artifact, checksum, layout="binary"):
        return subprocess.run([
            "bash", "-c", 'source "$1"; install_native_cli "${@:2}"', "bash",
            str(ROOT / "setup/install-native-clis.sh"), name, version,
            artifact.as_uri(), checksum, layout, str(self.tools), str(self.bins),
        ], capture_output=True, text=True)

    def test_both_commands_coexist_and_rerun_without_downloading(self):
        grok = self.root / "grok-download"
        grok.write_text("#!/bin/sh\necho grok-fixture\n")
        cursor = self.root / "cursor.tar.gz"
        body = b"#!/bin/sh\necho cursor-fixture\n"
        with tarfile.open(cursor, "w:gz") as archive:
            member = tarfile.TarInfo("package/cursor-agent")
            member.mode, member.size = 0o755, len(body)
            archive.addfile(member, io.BytesIO(body))
        for name, artifact, layout in [("cursor-agent", cursor, "tar"), ("grok", grok, "binary")]:
            checksum = hashlib.sha256(artifact.read_bytes()).hexdigest()
            result = self.install(name, "1.0", artifact, checksum, layout)
            self.assertEqual(result.returncode, 0, result.stderr)
            artifact.unlink()
            result = self.install(name, "1.0", artifact, checksum, layout)
            self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(subprocess.check_output([self.bins / "cursor-agent"], text=True).strip(), "cursor-fixture")
        self.assertEqual(subprocess.check_output([self.bins / "grok"], text=True).strip(), "grok-fixture")
        self.assertFalse((self.bins / "agent").exists())

    def test_bad_checksum_preserves_installed_command(self):
        artifact = self.root / "grok-download"
        artifact.write_text("#!/bin/sh\necho original\n")
        checksum = hashlib.sha256(artifact.read_bytes()).hexdigest()
        result = self.install("grok", "1.0", artifact, checksum)
        self.assertEqual(result.returncode, 0, result.stderr)
        artifact.write_text("#!/bin/sh\necho corrupted\n")
        result = self.install("grok", "2.0", artifact, checksum)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("checksum", result.stderr.lower())
        self.assertEqual(subprocess.check_output([self.bins / "grok"], text=True).strip(), "original")
        self.assertFalse((self.tools / "grok-2.0").exists())
        self.assertFalse(list(self.tools.glob(".download-*")))

    def test_archive_without_executable_is_not_activated(self):
        artifact = self.root / "empty.tar.gz"
        with tarfile.open(artifact, "w:gz"):
            pass
        checksum = hashlib.sha256(artifact.read_bytes()).hexdigest()
        result = self.install("cursor-agent", "1.0", artifact, checksum, "tar")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Missing executable", result.stderr)
        self.assertFalse((self.bins / "cursor-agent").exists())
        self.assertFalse((self.tools / "cursor-agent-1.0").exists())


if __name__ == "__main__":
    unittest.main()
