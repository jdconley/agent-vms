import importlib
from contextlib import ExitStack
import json
from pathlib import Path
import tempfile
import subprocess
import unittest
from unittest.mock import patch
from types import SimpleNamespace


class HostTests(unittest.TestCase):
    def host(self):
        try:
            return importlib.import_module("lib.host")
        except ImportError:
            self.fail("Host orchestrator is not implemented")

    def test_domain_uuid_mismatch_blocks_mutation(self):
        host = self.host()
        with patch.object(host, "virsh", return_value="foreign-uuid\n"):
            with self.assertRaisesRegex(host.Error, "ownership"):
                host.assert_domain({"name": "demo", "uuid": "owned-uuid"})

    def test_pairing_output_requires_real_pairing_url(self):
        host = self.host()
        with self.assertRaises(host.Error):
            host.pairing_url("T3 failed. See https://example.com/help")
        self.assertEqual(host.pairing_url("Open http://127.0.0.1:3773/pair?token=fixture\n"),
                         "http://127.0.0.1:3773/pair?token=fixture")

    def test_real_t3_fragment_pairing_url_is_accepted(self):
        host = self.host()
        url = "http://127.0.0.1:3773/pair#token=FIXTURE"
        self.assertEqual(host.pairing_url(f"Origin: http://127.0.0.1:3773\nPairing URL: {url}\n"), url)

    def test_maximum_name_has_short_control_socket_path(self):
        host = self.host()
        self.assertTrue(hasattr(host, "control_path"), "Short control socket helper is missing")
        path = host.control_path(Path("/var/lib/agent-vms/instances") / ("a" * 63))
        self.assertLess(len(str(path).encode()) + 17, 108)

    def test_health_timeout_is_not_success(self):
        host = self.host()
        with patch.object(host, "guest", side_effect=host.Error("service failed")):
            with self.assertRaisesRegex(host.Error, "service failed"):
                host.health(Path("/fixture"), "192.0.2.2")

    def test_download_rejects_checksum_mismatch(self):
        host = self.host()
        with tempfile.TemporaryDirectory() as d:
            target = Path(d) / "base.qcow2"
            target.write_bytes(b"corrupted image")
            with self.assertRaisesRegex(host.Error, "checksum"):
                host.verify_image(target, "0" * 64)

    def test_reconnect_reuses_live_host_tunnel(self):
        host = self.host()
        with tempfile.TemporaryDirectory() as d:
            directory = Path(d)
            (directory / "tunnel").touch()
            (directory / "access.json").write_text(json.dumps({"ip": "192.0.2.2", "port": 4567}))
            with patch.object(host, "control_path", return_value=directory / "tunnel"), \
                 patch.object(host, "run", return_value=subprocess.CompletedProcess([], 0)) as run:
                self.assertTrue(hasattr(host, "host_tunnel"), "Reusable tunnel helper is missing")
                self.assertEqual(host.host_tunnel(directory, "192.0.2.2"), 4567)
                self.assertTrue(any("check" in call.args[0] for call in run.call_args_list))
                self.assertFalse(any("-fNT" in call.args[0] for call in run.call_args_list))

    def test_failed_install_resumes_without_replacing_disk_or_identity(self):
        host = self.host()
        with tempfile.TemporaryDirectory() as temporary, ExitStack() as stack:
            root = Path(temporary)
            base = root / "base.qcow2"
            base.write_bytes(b"base fixture")
            domains = {}
            disk_creations = []

            def execute(argv, **kwargs):
                command = [str(x) for x in argv]
                if command[0] == "ssh-keygen":
                    key = Path(command[-1])
                    key.write_text("PRIVATE FIXTURE MUST STAY ON HOST")
                    Path(str(key) + ".pub").write_text("ssh-ed25519 AAAA public-fixture")
                elif command[0] == "qemu-img":
                    Path(command[-2]).write_bytes(b"persistent guest disk")
                    disk_creations.append(command)
                elif command[0] == "cloud-localds":
                    Path(command[1]).write_bytes(b"seed")
                elif command[0] == "virt-install":
                    domains[command[command.index("--name") + 1]] = command[command.index("--uuid") + 1]
                return subprocess.CompletedProcess(command, 0)

            def libvirt(*args, **kwargs):
                if args[0] == "domuuid":
                    return domains[args[1]]
                if args[0] == "domstate":
                    return "running"
                return ""

            stack.enter_context(patch.object(host, "INSTANCES", root / "instances"))
            stack.enter_context(patch.object(host, "base_image", return_value=base))
            stack.enter_context(patch.object(host, "run", side_effect=execute))
            stack.enter_context(patch.object(host, "virsh", side_effect=libvirt))
            stack.enter_context(patch.object(host, "domain_exists", side_effect=lambda name: name in domains))
            stack.enter_context(patch.object(host, "address", return_value="192.0.2.2"))
            stack.enter_context(patch.object(host.shutil, "chown"))
            install = stack.enter_context(patch.object(host, "install_guest", side_effect=host.Error("install failed")))
            args = SimpleNamespace(name="demo", cpus=4, memory=6144, disk=30)
            with self.assertRaisesRegex(host.Error, "install failed"):
                host.up(args)
            directory = root / "instances/demo"
            original = host.read_state(directory)
            self.assertEqual(original["phase"], "failed")
            self.assertNotIn("PRIVATE", (directory / "user-data").read_text())
            install.side_effect = None
            result = host.up(args)
            self.assertEqual(result["status"], "ready")
            self.assertEqual(host.read_state(directory)["uuid"], original["uuid"])
            self.assertEqual((directory / "disk.qcow2").read_bytes(), b"persistent guest disk")
            self.assertEqual(len(disk_creations), 1)


if __name__ == "__main__":
    unittest.main()
