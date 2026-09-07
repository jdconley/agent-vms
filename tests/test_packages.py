import importlib
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


class PackageTests(unittest.TestCase):
    def test_interrupted_unpack_reinstalls_damaged_package(self):
        self.check_damaged_package(1)

    def test_successful_configure_does_not_hide_half_installed_package(self):
        self.check_damaged_package(0)

    def check_damaged_package(self, configure_exit):
        module = importlib.import_module("lib.packages")
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)
            scripts = {
                "dpkg": f'#!/bin/bash\nexit {configure_exit}\n',
                "dpkg-query": '#!/bin/bash\nprintf "iHR libasound2t64:amd64\\nii  healthy-package\\n"\n',
                "apt-get": '''#!/bin/bash
case "$*" in
  *--reinstall*libasound2t64:amd64*) echo repaired > "$RECOVERY_RESULT";;
  *) exit 93;;
esac
''',
            }
            for name, script in scripts.items():
                (path / name).write_text(script)
                (path / name).chmod(0o755)
            with patch.dict(os.environ, {"PATH": temporary + os.pathsep + os.environ["PATH"],
                                         "RECOVERY_RESULT": str(path / "result")}):
                module.recover(path / "lock")
            self.assertEqual((path / "result").read_text().strip(), "repaired")

    def test_clean_audit_still_finalizes_interrupted_journal(self):
        module = importlib.import_module("lib.packages")
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)
            dpkg = path / "dpkg"
            dpkg.write_text('''#!/bin/bash
case "$1" in
  --audit) exit 0;;
  --configure) echo finalized > "$RECOVERY_RESULT";;
  *) exit 91;;
esac
''')
            dpkg.chmod(0o755)
            (path / "dpkg-query").write_text('#!/bin/bash\nexit 0\n')
            (path / "dpkg-query").chmod(0o755)
            with patch.dict(os.environ, {"PATH": temporary + os.pathsep + os.environ["PATH"],
                                         "RECOVERY_RESULT": str(path / "result")}):
                module.recover(path / "lock")
            self.assertTrue((path / "result").exists(), "An empty audit left the interrupted journal unfinalized")

    def test_interrupted_dpkg_is_configured_before_retry(self):
        try:
            module = importlib.import_module("lib.packages")
        except ImportError:
            self.fail("Package recovery is missing")
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)
            dpkg = path / "dpkg"
            dpkg.write_text('''#!/bin/bash
case "$1" in
  --audit) echo 'Unconfigured packages remain';;
  --configure) echo configured > "$RECOVERY_RESULT";;
  *) exit 91;;
esac
''')
            dpkg.chmod(0o755)
            (path / "dpkg-query").write_text('#!/bin/bash\nexit 0\n')
            (path / "dpkg-query").chmod(0o755)
            with patch.dict(os.environ, {"PATH": temporary + os.pathsep + os.environ["PATH"],
                                         "RECOVERY_RESULT": str(path / "result")}):
                module.recover(path / "lock")
            self.assertEqual((path / "result").read_text().strip(), "configured")


if __name__ == "__main__":
    unittest.main()
