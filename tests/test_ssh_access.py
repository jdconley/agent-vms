"""Direct SSH access for tools such as Claude Code, Codex and VS Code."""
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

from lib import agent_vm, host, sshconfig

ROOT = Path(__file__).resolve().parents[1]
HOST_KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIFixtureHostKeyFixtureHostKeyFixtureHost root@demo"


def resolve(home, alias):
    """Ask real OpenSSH how it would connect, without connecting."""
    output = subprocess.run(["ssh", "-G", "-F", str(home / ".ssh/config"), alias],
                            capture_output=True, text=True, check=True).stdout
    options = {}
    for line in output.splitlines():
        key, _, value = line.partition(" ")
        options.setdefault(key, value)
    return options


class ControllerConfigTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name)
        (self.home / ".ssh").mkdir(mode=0o700)

    def test_entry_reaches_guest_as_agent_through_the_kvm_host(self):
        (self.home / ".ssh/config").write_text("Host *\n  User someone-else\n")
        sshconfig.write_entry(self.home, "avm-demo", "127.0.0.1", 22200, "kvm-host", HOST_KEY)
        self.assertTrue(sshconfig.ensure_include(self.home))
        options = resolve(self.home, "avm-demo")
        # Restricted accounts may only forward to host loopback (PermitOpen 127.0.0.1:*).
        self.assertEqual(options["hostname"], "127.0.0.1")
        self.assertEqual(options["port"], "22200")
        self.assertEqual(options["user"], "agent", "Managed entries must win over earlier Host * defaults")
        self.assertEqual(options["proxyjump"], "kvm-host")
        self.assertEqual(options["hostkeyalias"], "avm-demo")
        self.assertEqual(options["stricthostkeychecking"], "true")
        self.assertEqual(options["identitiesonly"], "yes")
        self.assertIn(str(self.home / ".ssh/agent-vms/id_ed25519"), options["identityfile"])
        known = (self.home / ".ssh/agent-vms/known_hosts").read_text()
        self.assertEqual(known, "avm-demo " + " ".join(HOST_KEY.split()[:2]) + "\n")

    def test_include_is_added_once_and_existing_config_is_kept(self):
        original = "Include /elsewhere/conductor_config\n\nHost *\n  AddKeysToAgent yes\n"
        (self.home / ".ssh/config").write_text(original)
        self.assertTrue(sshconfig.ensure_include(self.home))
        self.assertTrue(sshconfig.ensure_include(self.home))
        text = (self.home / ".ssh/config").read_text()
        include = f"Include {self.home / '.ssh/agent-vms/config'}"
        self.assertTrue(text.startswith(include + "\n"), "Include must precede every Host block")
        self.assertEqual(text.count(include), 1)
        self.assertTrue(text.endswith(original))
        self.assertEqual((self.home / ".ssh/config.agent-vms-backup").read_text(), original)

    def test_missing_config_is_created_privately(self):
        self.assertTrue(sshconfig.ensure_include(self.home))
        self.assertEqual((self.home / ".ssh/config").stat().st_mode & 0o777, 0o600)

    def test_symlinked_config_is_left_for_the_owner_to_edit(self):
        target = self.home / "dotfiles-ssh-config"
        target.write_text("Host *\n")
        (self.home / ".ssh/config").symlink_to(target)
        self.assertFalse(sshconfig.ensure_include(self.home))
        self.assertEqual(target.read_text(), "Host *\n")

    def test_rewriting_an_entry_replaces_its_address_and_key(self):
        sshconfig.write_entry(self.home, "avm-demo", "127.0.0.1", 22200, "kvm-host", HOST_KEY)
        sshconfig.write_entry(self.home, "avm-other", "127.0.0.1", 22201, "kvm-host", HOST_KEY)
        newer = HOST_KEY.replace("Fixture", "Rotated")
        sshconfig.write_entry(self.home, "avm-demo", "127.0.0.1", 22299, "kvm-host", newer)
        sshconfig.ensure_include(self.home)
        self.assertEqual(resolve(self.home, "avm-demo")["port"], "22299")
        self.assertEqual(resolve(self.home, "avm-other")["port"], "22201")
        lines = (self.home / ".ssh/agent-vms/known_hosts").read_text().splitlines()
        self.assertEqual([line.split()[0] for line in lines].count("avm-demo"), 1)
        self.assertIn("Rotated", "\n".join(lines))

    def test_guest_supplied_host_key_cannot_inject_known_hosts_lines(self):
        for bad in (HOST_KEY + "\n@cert-authority * ssh-ed25519 AAAA", "not-a-key", ""):
            with self.assertRaises(agent_vm.Error):
                sshconfig.write_entry(self.home, "avm-demo", "127.0.0.1", 22200, "kvm-host", bad)
        with self.assertRaises(agent_vm.Error):
            sshconfig.write_entry(self.home, "avm-demo", "evil\n  ProxyCommand x", 22200, "kvm-host", HOST_KEY)
        for port in (0, 70000, "22\n  ProxyCommand x", True):
            with self.assertRaises(agent_vm.Error):
                sshconfig.write_entry(self.home, "avm-demo", "127.0.0.1", port, "kvm-host", HOST_KEY)

    def test_remove_entry_keeps_other_vms(self):
        sshconfig.write_entry(self.home, "avm-demo", "127.0.0.1", 22200, "kvm-host", HOST_KEY)
        sshconfig.write_entry(self.home, "avm-other", "127.0.0.1", 22201, "kvm-host", HOST_KEY)
        sshconfig.remove_entry(self.home, "avm-demo")
        config = (self.home / ".ssh/agent-vms/config").read_text()
        self.assertNotIn("avm-demo", config)
        self.assertIn("Host avm-other", config)
        self.assertNotIn("avm-demo", (self.home / ".ssh/agent-vms/known_hosts").read_text())

    def test_controller_key_is_created_once_and_kept_private(self):
        first = sshconfig.ensure_key(self.home)
        second = sshconfig.ensure_key(self.home)
        self.assertEqual(first, second)
        self.assertTrue(first.startswith("ssh-ed25519 "))
        self.assertEqual((self.home / ".ssh/agent-vms/id_ed25519").stat().st_mode & 0o777, 0o600)

    def test_alias_names_are_stable_and_ssh_safe(self):
        self.assertEqual(sshconfig.alias("demo", "kvm-host"), "avm-demo")
        self.assertEqual(sshconfig.alias(None, "ubuntu@Dev-Box.example.com"), "avm-dev-box-example-com")


class GuestAuthorizationTests(unittest.TestCase):
    def test_authorizing_replaces_only_this_controllers_previous_key(self):
        with tempfile.TemporaryDirectory() as directory:
            ssh_dir = Path(directory) / ".ssh"
            ssh_dir.mkdir()
            management = "ssh-ed25519 AAAAmanagement root@kvm-host"
            (ssh_dir / "authorized_keys").write_text(f"{management}\nssh-ed25519 AAAAold agent-vms@laptop\n")
            host_key = Path(directory) / "host.pub"
            host_key.write_text(HOST_KEY + "\n")
            new = "ssh-ed25519 AAAAnew agent-vms@laptop"
            output = subprocess.run(["bash", "-c", host.AUTHORIZE, "authorize", new, str(ssh_dir), str(host_key)],
                                    capture_output=True, text=True, check=True).stdout
            self.assertEqual(output.strip(), HOST_KEY)
            self.assertEqual((ssh_dir / "authorized_keys").read_text().splitlines(), [management, new])
            self.assertEqual((ssh_dir / "authorized_keys").stat().st_mode & 0o777, 0o600)

    def test_public_key_options_are_rejected_before_remote_work(self):
        for key in ('command="curl evil" ssh-ed25519 AAAAC3Nz agent-vms@laptop',
                    "ssh-ed25519 AAAAC3Nz agent-vms@laptop\nssh-ed25519 AAAAsecond"):
            result = subprocess.run(["python3", str(ROOT / "agent-vm"), "authorize", "demo", "--public-key", key],
                                    capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("public key", result.stderr.lower())


class FakeLibvirt:
    """In-memory domain and network XML with virsh net-update semantics."""

    def __init__(self, mac="52:54:00:aa:bb:cc", power="running"):
        self.power = power
        self.domain = (f"<domain><devices><interface type='network'><mac address='{mac}'/>"
                       "<source network='agent-vms'/></interface></devices></domain>")
        self.network = ET.fromstring("<network><name>agent-vms</name><ip address='192.168.197.1'>"
                                     "<dhcp><range start='192.168.197.10' end='192.168.197.250'/></dhcp></ip></network>")
        self.updates = []

    def __call__(self, *args, check=True):
        if args[0] == "dumpxml":
            return self.domain
        if args[0] == "domstate":
            return self.power + "\n"
        if args[0] == "net-dumpxml":
            return ET.tostring(self.network, encoding="unicode")
        if args[0] == "net-update":
            _, network, action, section, xml, *flags = args
            self.updates.append(action)
            self.assertions(network, section, flags)
            dhcp = self.network.find("./ip/dhcp")
            entry = ET.fromstring(xml)
            if action == "add-last":
                dhcp.append(entry)
            elif action == "delete":
                for existing in dhcp.findall("host"):
                    if existing.get("mac") == entry.get("mac"):
                        dhcp.remove(existing)
            return ""
        raise AssertionError(f"unexpected virsh call {args}")

    @staticmethod
    def assertions(network, section, flags):
        assert network == "agent-vms" and section == "ip-dhcp-host"
        assert "--live" in flags and "--config" in flags, "Reservations must survive restarts"

    def reservations(self):
        return [(h.get("mac"), h.get("name"), h.get("ip")) for h in self.network.findall("./ip/dhcp/host")]


class AddressReservationTests(unittest.TestCase):
    def test_current_lease_becomes_a_fixed_reservation(self):
        libvirt = FakeLibvirt()
        with patch.object(host, "virsh", side_effect=libvirt):
            host.reserve_address("demo", "192.168.197.23")
            host.reserve_address("demo", "192.168.197.23")
        self.assertEqual(libvirt.reservations(), [("52:54:00:aa:bb:cc", "demo", "192.168.197.23")])
        self.assertEqual(libvirt.updates, ["add-last"], "An unchanged reservation must not be rewritten")

    def test_changed_lease_replaces_the_old_reservation(self):
        libvirt = FakeLibvirt()
        with patch.object(host, "virsh", side_effect=libvirt):
            host.reserve_address("demo", "192.168.197.23")
            host.reserve_address("demo", "192.168.197.61")
        self.assertEqual(libvirt.reservations(), [("52:54:00:aa:bb:cc", "demo", "192.168.197.61")])

    def test_release_removes_only_that_vms_reservation(self):
        libvirt = FakeLibvirt()
        with patch.object(host, "virsh", side_effect=libvirt):
            host.reserve_address("demo", "192.168.197.23")
            libvirt.network.find("./ip/dhcp").append(
                ET.fromstring("<host mac='52:54:00:00:00:01' name='other' ip='192.168.197.40'/>"))
            host.release_address("demo")
        self.assertEqual(libvirt.reservations(), [("52:54:00:00:00:01", "other", "192.168.197.40")])

    def test_release_tolerates_a_missing_network_so_delete_can_finish(self):
        def missing(*args, check=True):
            raise host.Error("network not found: agent-vms")
        with patch.object(host, "virsh", side_effect=missing):
            host.release_address("demo")

    def test_stopped_vm_reports_its_state_instead_of_a_dhcp_error(self):
        with patch.object(host, "virsh", side_effect=FakeLibvirt(power="shut off")):
            with self.assertRaisesRegex(host.Error, "shut off.*up demo"):
                host.running_address("demo")


class LoopbackRelayTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        self.instances = root / "instances"
        self.units = root / "systemd"
        self.units.mkdir()
        for name, extra in (("demo", {}), ("other", {"ssh_port": 22200})):
            directory = self.instances / name
            directory.mkdir(parents=True)
            agent_vm.write_state(directory, {"managed_by": "agent-vms", "name": name,
                                             "disk": str(directory / "disk.qcow2"), **extra})
        for context in (patch.object(host, "INSTANCES", self.instances),
                        patch.object(host, "SYSTEMD", self.units)):
            context.start()
            self.addCleanup(context.stop)

    def test_port_is_stable_and_not_shared_with_other_vms(self):
        directory = self.instances / "demo"
        port = host.ssh_port(directory, host.read_state(directory))
        self.assertNotEqual(port, 22200, "Another VM already owns 22200")
        self.assertTrue(22200 <= port < 23000, "Stay below the Linux ephemeral port range")
        self.assertEqual(host.read_state(directory)["ssh_port"], port)
        self.assertEqual(host.ssh_port(directory, host.read_state(directory)), port)

    def test_relay_listens_only_on_host_loopback_and_survives_reboots(self):
        with patch.object(host, "run") as run:
            host.publish_ssh("demo", "192.168.197.23", 22201)
        socket_unit = (self.units / "agent-vms-ssh-demo.socket").read_text()
        service = (self.units / "agent-vms-ssh-demo.service").read_text()
        self.assertIn("ListenStream=127.0.0.1:22201", socket_unit)
        self.assertIn("WantedBy=sockets.target", socket_unit)
        self.assertIn("systemd-socket-proxyd 192.168.197.23:22", service)
        self.assertIn("DynamicUser=yes", service)
        commands = [" ".join(map(str, call.args[0])) for call in run.call_args_list]
        self.assertIn("systemctl enable --now agent-vms-ssh-demo.socket", commands)

    def test_changed_address_restarts_the_relay(self):
        with patch.object(host, "run"):
            host.publish_ssh("demo", "192.168.197.23", 22201)
        with patch.object(host, "run") as run:
            host.publish_ssh("demo", "192.168.197.23", 22201)
        commands = [" ".join(map(str, call.args[0])) for call in run.call_args_list]
        self.assertFalse(any("stop" in c or "daemon-reload" in c for c in commands), "Unchanged relay must not drop sessions")
        with patch.object(host, "run") as run:
            host.publish_ssh("demo", "192.168.197.61", 22201)
        commands = [" ".join(map(str, call.args[0])) for call in run.call_args_list]
        self.assertIn("systemctl daemon-reload", commands)
        self.assertTrue(any(c.startswith("systemctl stop") and "agent-vms-ssh-demo.service" in c for c in commands))
        self.assertIn("192.168.197.61:22", (self.units / "agent-vms-ssh-demo.service").read_text())

    def test_unpublish_removes_the_relay(self):
        with patch.object(host, "run"):
            host.publish_ssh("demo", "192.168.197.23", 22201)
        with patch.object(host, "run") as run:
            host.unpublish_ssh("demo")
            host.unpublish_ssh("demo")
        self.assertEqual(list(self.units.iterdir()), [])
        commands = [" ".join(map(str, call.args[0])) for call in run.call_args_list]
        self.assertEqual(sum(c.startswith("systemctl disable --now") for c in commands), 1)


class ControllerFlowTests(unittest.TestCase):
    def test_ssh_config_authorizes_writes_and_proves_the_connection(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            (home / ".ssh").mkdir()
            args = agent_vm.parser().parse_args(["ssh-config", "demo", "--host", "kvm-host"])
            calls = []
            def remote(target, arguments):
                calls.append((target, arguments))
                return {"hostname": "127.0.0.1", "port": 22200, "host_key": HOST_KEY}
            with patch.object(agent_vm.Path, "home", return_value=home), \
                    patch.object(agent_vm, "remote", side_effect=remote), \
                    patch.object(agent_vm, "run") as run:
                result = agent_vm.ssh_access(args)
            self.assertEqual(result["ssh"], "avm-demo")
            target, arguments = calls[0]
            self.assertEqual(target, "kvm-host")
            self.assertEqual(arguments[:2], ["authorize", "demo"])
            self.assertEqual(arguments[arguments.index("--public-key") + 1],
                             (home / ".ssh/agent-vms/id_ed25519.pub").read_text().strip())
            self.assertEqual(resolve(home, "avm-demo")["proxyjump"], "kvm-host")
            self.assertEqual(resolve(home, "avm-demo")["port"], "22200")
            probe = [str(x) for x in run.call_args.args[0]]
            self.assertEqual(probe[0], "ssh")
            self.assertIn("avm-demo", probe)

    def test_delete_forgets_the_local_ssh_entry(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            (home / ".ssh").mkdir()
            sshconfig.write_entry(home, "avm-demo", "127.0.0.1", 22200, "kvm-host", HOST_KEY)
            with patch.object(agent_vm.Path, "home", return_value=home), \
                    patch.object(agent_vm, "remote", return_value={"name": "demo", "status": "deleted"}), \
                    patch("sys.argv", ["agent-vm", "delete", "demo", "--host", "kvm-host", "--yes", "--json"]), \
                    patch("builtins.print"):
                agent_vm.main()
            self.assertNotIn("avm-demo", (home / ".ssh/agent-vms/config").read_text())

    def test_up_reports_ssh_problems_without_hiding_the_pairing_link(self):
        with patch.object(agent_vm, "remote", return_value={"name": "demo", "status": "ready"}), \
                patch.object(agent_vm, "connect", return_value={"url": "http://127.0.0.1:1/pair#token=x"}), \
                patch.object(agent_vm, "ssh_access", side_effect=agent_vm.Error("forwarding denied")), \
                patch("sys.argv", ["agent-vm", "up", "demo", "--host", "kvm-host"]), \
                patch("builtins.print") as printed:
            agent_vm.main()
        output = "\n".join(str(call.args[0]) for call in printed.call_args_list if call.args)
        self.assertIn("pair#token=x", output)
        self.assertIn("forwarding denied", output)
        self.assertIn("ssh-config demo --host kvm-host", output)


if __name__ == "__main__":
    unittest.main()
