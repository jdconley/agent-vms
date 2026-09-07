import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class RecordingTests(unittest.TestCase):
    def test_bad_label_fails_before_creating_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / "recordings"
            result = subprocess.run([str(ROOT / "scripts/record-start"), "../escape"],
                                    env=os.environ | {"AGENT_VMS_RECORDINGS_DIR": str(directory)},
                                    capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("label", result.stderr.lower())
            self.assertFalse(directory.exists())

    def test_failed_ffmpeg_does_not_report_recording_started(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)
            binary = path / "bin"
            binary.mkdir()
            # These tests exercise the shell lifecycle; flock is Linux-only.
            for name, body in (("ffmpeg", "exit 1"), ("flock", "exit 0")):
                file = binary / name
                file.write_text("#!/bin/bash\n" + body + "\n")
                file.chmod(0o755)
            env = os.environ | {"AGENT_VMS_RECORDINGS_DIR": str(path / "recordings"),
                                "PATH": str(binary) + os.pathsep + os.environ["PATH"]}
            result = subprocess.run([str(ROOT / "scripts/record-start"), "test"], env=env,
                                    capture_output=True, text=True, timeout=10)
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn("Recording started", result.stdout)
            self.assertFalse((path / "recordings/.pid").exists())


if __name__ == "__main__":
    unittest.main()
