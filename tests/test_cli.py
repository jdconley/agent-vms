import importlib.util
import http.server
import io
import json
from pathlib import Path
import os
import signal
import subprocess
import tarfile
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


class CommandTests(unittest.TestCase):
    def cli(self, *args):
        return subprocess.run(["python3", str(ROOT / "agent-vm"), *args],
                              capture_output=True, text=True)

    def test_help_explains_both_remote_paths(self):
        result = self.cli("--help")
        self.assertEqual(result.returncode, 0, result.stderr)
        for command in ("up", "install", "connect", "doctor", "delete"):
            self.assertIn(command, result.stdout)

    def test_invalid_names_fail_before_any_host_work(self):
        for name in ("../escape", "a'b", "-option", "UpperCase", "a" * 64):
            result = self.cli("up", name)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("name", result.stderr.lower())

    def test_delete_needs_explicit_confirmation(self):
        result = self.cli("delete", "example")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--yes", result.stderr)

    def test_host_cannot_inject_ssh_options(self):
        result = self.cli("install", "--host", "-oProxyCommand=touch /tmp/unsafe")
        self.assertNotEqual(result.returncode, 0)

    def test_tunnel_child_does_not_keep_caller_output_open(self):
        with tempfile.TemporaryDirectory() as directory:
            pidfile = Path(directory) / "child.pid"
            child = "import subprocess,pathlib; p=subprocess.Popen(['sleep','30']); pathlib.Path(" + repr(str(pidfile)) + ").write_text(str(p.pid))"
            caller = "from lib.agent_vm import start_tunnel; start_tunnel(['python3','-c'," + repr(child) + "]); print('ready')"
            try:
                result = subprocess.run(["python3", "-c", caller], cwd=ROOT,
                                        capture_output=True, text=True, timeout=3)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout.strip(), "ready")
                self.assertNotEqual(os.getpgid(int(pidfile.read_text())), os.getpgrp(),
                                    "The proxy must survive cleanup of the caller's process group")
            finally:
                if pidfile.exists():
                    try:
                        os.kill(int(pidfile.read_text()), signal.SIGTERM)
                    except ProcessLookupError:
                        pass


class DataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = ROOT / "lib" / "agent_vm.py"
        if not path.exists():
            return
        spec = importlib.util.spec_from_file_location("agent_vm", path)
        cls.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.module)

    def api(self):
        self.assertTrue(hasattr(self, "module"), "CLI library is not implemented")
        return self.module

    def test_seed_contains_only_public_management_identity(self):
        data = self.api().cloud_config("demo", "ssh-ed25519 AAAA review")
        seed = json.loads(data.split("\n", 1)[1])
        self.assertEqual(seed["users"][0]["name"], "agent")
        self.assertEqual(seed["users"][0]["ssh_authorized_keys"], ["ssh-ed25519 AAAA review"])
        self.assertFalse(seed["ssh_pwauth"])
        self.assertNotIn("PRIVATE KEY", data)
        self.assertNotIn("creds", data)

    def test_remote_archive_excludes_local_credentials_and_git(self):
        module = self.api()
        with tarfile.open(fileobj=io.BytesIO(module.source_archive()), mode="r:gz") as archive:
            names = archive.getnames()
        self.assertIn("agent-vm", names)
        self.assertIn("lib/agent_vm.py", names)
        self.assertFalse(any(".git" in x or "config.local" in x or ".ssh" in x for x in names))

    def test_state_rejects_disk_path_outside_owned_directory(self):
        module = self.api()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "demo"
            path.mkdir()
            (path / "state.json").write_text(json.dumps({"name": "demo", "disk": "/etc/passwd"}))
            with self.assertRaises(module.Error):
                module.read_state(path)

    def test_remote_transport_executes_transferred_doctor(self):
        module = self.api()
        with tempfile.TemporaryDirectory() as directory:
            binary = Path(directory)
            # SSH is the only remote boundary replaced. The real archive is
            # extracted, executed and cleaned up by the real remote shell body.
            (binary / "ssh").write_text('#!/bin/bash\nexec bash -c "${@: -1}"\n')
            (binary / "sudo").write_text('#!/bin/bash\nshift\nexec "$@"\n')
            # With real sudo, root-owned bytecode directories cannot be removed
            # by the SSH user. Observe the source tree immediately before the
            # remote cleanup, while still removing all test files normally.
            bytecode = binary / "bytecode"
            (binary / "rm").write_text(
                '#!/bin/bash\nfind "${@: -1}" -name "*.pyc" > "$BYTECODE_REPORT"\nexec /bin/rm "$@"\n')
            for file in binary.iterdir():
                file.chmod(0o755)
            with patch.dict(os.environ, {"PATH": str(binary) + os.pathsep + os.environ["PATH"],
                                         "BYTECODE_REPORT": str(bytecode)}):
                result = module.remote("fixture", ["doctor"])
            self.assertIn("kvm", result)
            self.assertEqual(bytecode.read_text(), "", "Privileged Python must not leave bytecode in uploaded source")

    def test_run_command_is_available_for_agent_setup(self):
        result = subprocess.run(["python3", str(ROOT / "agent-vm"), "run", "--help"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--command", result.stdout)

    def test_tunnel_does_not_report_ready_when_forwarding_is_denied(self):
        module = self.api()
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(module.Path, "home", return_value=Path(directory)), \
                    patch.object(module, "run") as run, \
                    patch.object(module, "start_tunnel"), \
                    patch("urllib.request.OpenerDirector.open", side_effect=urllib.error.URLError("Connection reset")):
                with self.assertRaisesRegex(module.Error, "forwarding"):
                    module.local_tunnel("fixture", 3773, "demo")
                self.assertIn("exit", run.call_args.args[0], "Failed tunnel should be closed")

    def test_http_proxy_cannot_fake_a_working_tunnel(self):
        module = self.api()
        class Proxy(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                body = b'{"environmentId":"proxy","serverVersion":"0.0.38"}'
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            def log_message(self, *_):
                pass
        server = http.server.HTTPServer(("127.0.0.1", 0), Proxy)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            proxy = f"http://127.0.0.1:{server.server_port}"
            with tempfile.TemporaryDirectory() as directory, \
                    patch.object(module.Path, "home", return_value=Path(directory)), \
                    patch.object(module, "start_tunnel"), \
                    patch.object(module, "run"), patch("urllib.request._opener", None), \
                    patch.dict(os.environ, {"HTTP_PROXY": proxy, "http_proxy": proxy, "NO_PROXY": "", "no_proxy": ""}):
                with self.assertRaisesRegex(module.Error, "forwarding"):
                    module.local_tunnel("fixture", 3773, "demo")
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_remote_failure_is_propagated(self):
        module = self.api()
        with tempfile.TemporaryDirectory() as directory:
            binary = Path(directory) / "ssh"
            binary.write_text('#!/bin/bash\nexit 42\n')
            binary.chmod(0o755)
            with patch.dict(os.environ, {"PATH": directory + os.pathsep + os.environ["PATH"]}):
                with self.assertRaisesRegex(module.Error, "exit 42"):
                    module.remote("fixture", ["doctor"])


if __name__ == "__main__":
    unittest.main()
