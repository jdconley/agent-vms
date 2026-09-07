#!/bin/bash
# Only the dedicated agent-vms network is managed here.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=setup/common.sh
source "$SCRIPT_DIR/common.sh"
require_ubuntu
[ "${1:-}" != --check ] || exit 0
require_root
if [ ! -r /dev/kvm ] || [ ! -w /dev/kvm ]; then
  echo 'KVM unavailable. Enable virtualization/nested KVM, or use agent-vm install on an existing VM.' >&2
  exit 1
fi
apt-get -o DPkg::Lock::Timeout=120 update -qq
apt_install qemu-kvm libvirt-daemon-system libvirt-clients virtinst cloud-image-utils \
  genisoimage openssh-client curl ca-certificates nftables
systemctl enable --now libvirtd
install -d -m 0755 /etc/agent-vms
if virsh --connect qemu:///system net-info agent-vms >/dev/null 2>&1; then
  if [ ! -f /etc/agent-vms/network.xml ]; then
    echo 'An unmanaged network named agent-vms already exists. Rename it before setup.' >&2
    exit 1
  fi
else
  ip -j route show | python3 -c '
import ipaddress,json,sys
target=ipaddress.ip_network("192.168.197.0/24")
for route in json.load(sys.stdin):
    dst=route.get("dst", "default")
    if dst != "default" and target.overlaps(ipaddress.ip_network(dst, strict=False)):
        sys.exit("192.168.197.0/24 overlaps an existing route. Use a different host/network.")
'
  cat > /etc/agent-vms/network.xml <<'EOF'
<network>
  <name>agent-vms</name>
  <forward mode='nat'/>
  <bridge name='avms0' stp='on' delay='0'/>
  <port isolated='yes'/>
  <ip address='192.168.197.1' netmask='255.255.255.0'>
    <dhcp><range start='192.168.197.10' end='192.168.197.250'/></dhcp>
  </ip>
</network>
EOF
  virsh --connect qemu:///system net-define /etc/agent-vms/network.xml
fi
# Only traffic originating on our bridge is restricted. Libvirt supplies NAT.
cat > /etc/agent-vms/firewall.nft <<'EOF'
add table inet agent_vms
flush table inet agent_vms
table inet agent_vms {
  chain input {
    type filter hook input priority -10; policy accept;
    iifname "avms0" ct state established,related accept
    iifname "avms0" udp dport { 53, 67 } accept
    iifname "avms0" tcp dport 53 accept
    iifname "avms0" drop
  }
  chain forward {
    type filter hook forward priority -10; policy accept;
    iifname "avms0" ct state established,related accept
    iifname "avms0" ip daddr { 0.0.0.0/8, 10.0.0.0/8, 100.64.0.0/10, 127.0.0.0/8, 169.254.0.0/16, 172.16.0.0/12, 192.168.0.0/16, 224.0.0.0/4 } reject
    iifname "avms0" meta nfproto ipv6 drop
  }
}
EOF
cat > /etc/systemd/system/agent-vms-firewall.service <<'EOF'
[Unit]
Description=Agent VM guest network restrictions
Before=libvirtd.service
After=network-pre.target
[Service]
Type=oneshot
ExecStart=/usr/sbin/nft -f /etc/agent-vms/firewall.nft
RemainAfterExit=yes
[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable agent-vms-firewall.service
systemctl restart agent-vms-firewall.service
# Consume all output: grep -q can close the pipe early and make virsh fail
# with SIGPIPE under pipefail. Network names also avoid translated status text.
if ! virsh --connect qemu:///system net-list --name | grep -Fx agent-vms >/dev/null; then
  virsh --connect qemu:///system net-start agent-vms
fi
virsh --connect qemu:///system net-autostart agent-vms
