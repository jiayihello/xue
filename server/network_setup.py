#!/usr/bin/env python3
import os
import subprocess
import logging
import sys
import ipaddress
from config_handler import app_config


logging.basicConfig(level=logging.INFO,
                   format='%(asctime)s %(levelname)s: %(message)s',
                   datefmt='%Y-%m-%d %H:%M:%S')
logger = logging.getLogger('network_setup')

def run_cmd(cmd):
    """执行命令并返回是否成功"""
    logger.debug(f"执行命令: {cmd}")
    try:
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True)
        stdout, stderr = process.communicate()
        if process.returncode != 0:
            logger.error(f"命令执行失败 ({process.returncode}): {stderr.decode('utf-8', errors='ignore')}")
            return False
        return True
    except Exception as e:
        logger.error(f"执行命令时出错: {str(e)}")
        return False


def run_and_capture(cmd):
    """执行命令并返回 (success, stdout_str)"""
    logger.debug(f"执行命令(捕获输出): {cmd}")
    try:
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True)
        stdout, stderr = process.communicate()
        if process.returncode != 0:
            logger.error(f"命令执行失败 ({process.returncode}): {stderr.decode('utf-8', errors='ignore')}")
            return False, ''
        return True, stdout.decode('utf-8', errors='ignore').strip()
    except Exception as e:
        logger.error(f"执行命令时出错: {str(e)}")
        return False, ''

def setup_network():
    """配置网络规则"""
    logger.info("开始设置网络规则...")

    # 获取配置（优先从环境变量读取，以支持部署时动态配置）
    try:
        network_bridge = app_config.network_bridge
        # 优先从环境变量读取 MAIN_INTERFACE，如果不存在则从配置文件读取
        main_interface = os.environ.get('MAIN_INTERFACE') or app_config.main_interface
        nat_listen_ip = app_config.nat_listen_ip
        
        logger.info(f"网络配置: bridge={network_bridge}, interface={main_interface}, nat_ip={nat_listen_ip}")
    except Exception as e:
        logger.error(f"读取配置文件失败: {str(e)}")
        return False

    # 确保网络桥接存在
    logger.info(f"检查网络桥接 {network_bridge}...")
    if not run_cmd(f"ip link show {network_bridge} >/dev/null 2>&1"):
        logger.error(f"网络桥接 {network_bridge} 不存在，请确保LXD已正确配置")
        return False

    # 启用IPv4/IPv6 转发
    logger.info("启用IP转发(IPv4/IPv6)...")
    run_cmd("echo 1 > /proc/sys/net/ipv4/ip_forward")
    run_cmd("echo 'net.ipv4.ip_forward=1' >> /etc/sysctl.conf")
    # IPv6 转发与 proxy_ndp（全局与特定外网网卡）
    run_cmd("sysctl -w net.ipv6.conf.all.forwarding=1")
    run_cmd("sysctl -w net.ipv6.conf.default.forwarding=1")
    if main_interface:
        run_cmd(f"sysctl -w net.ipv6.conf.{main_interface}.forwarding=1")
        run_cmd(f"sysctl -w net.ipv6.conf.{main_interface}.proxy_ndp=1")
    if network_bridge:
        run_cmd(f"sysctl -w net.ipv6.conf.{network_bridge}.forwarding=1")
    run_cmd("sysctl -w net.ipv6.conf.all.proxy_ndp=1")
    # 关闭IPv6临时地址，避免NAT66使用临时源地址（如不支持则忽略）
    run_cmd("sysctl -w net.ipv6.conf.all.use_tempaddr=0")
    run_cmd("sysctl -w net.ipv6.conf.default.use_tempaddr=0")
    if main_interface:
        run_cmd(f"sysctl -w net.ipv6.conf.{main_interface}.use_tempaddr=0")
    # NOTE: 避免调用 sysctl -p：它会从 /etc/sysctl.conf 重新加载并覆盖上面通过 sysctl -w 设置的 IPv6 选项。
    # 持久化由我们后续写入的 /etc/rc.local 以及（如需）/etc/sysctl.d/*.conf 负责。
    # run_cmd("sysctl -p")

    # 获取桥接网络的子网（用于IPv4 NAT）
    logger.info(f"获取 {network_bridge} 的IP地址和子网...")
    process = subprocess.Popen(f"ip addr show {network_bridge} | grep 'inet ' | awk '{{print $2}}'",
                               stdout=subprocess.PIPE, shell=True)
    stdout, _ = process.communicate()
    bridge_subnet = stdout.decode('utf-8').strip()

    if not bridge_subnet:
        logger.warning(f"无法获取 {network_bridge} 的子网，使用默认 10.0.0.0/8")
        bridge_subnet = "10.0.0.0/8"
    else:
        # 从 CIDR 格式获取子网部分
        ip_parts = bridge_subnet.split('/')
        if len(ip_parts) == 2:
            ip = ip_parts[0].split('.')
            if len(ip) == 4:
                bridge_subnet = f"{ip[0]}.{ip[1]}.{ip[2]}.0/{ip_parts[1]}"

    # 添加NAT规则
    logger.info(f"设置NAT规则: {bridge_subnet} -> {main_interface}...")
    run_cmd(f"iptables -t nat -C POSTROUTING -s {bridge_subnet} -o {main_interface} -j MASQUERADE >/dev/null 2>&1 || "
            f"iptables -t nat -A POSTROUTING -s {bridge_subnet} -o {main_interface} -j MASQUERADE")

    # 添加IPv4 FORWARD规则
    logger.info("设置IPv4 FORWARD规则...")
    run_cmd(f"iptables -C FORWARD -i {network_bridge} -o {main_interface} -j ACCEPT >/dev/null 2>&1 || "
            f"iptables -A FORWARD -i {network_bridge} -o {main_interface} -j ACCEPT")
    run_cmd(f"iptables -C FORWARD -i {main_interface} -o {network_bridge} -m state --state RELATED,ESTABLISHED -j ACCEPT >/dev/null 2>&1 || "
            f"iptables -A FORWARD -i {main_interface} -o {network_bridge} -m state --state RELATED,ESTABLISHED -j ACCEPT")

    # 添加IPv6 FORWARD规则 (如果IPv6启用)
    if app_config.ipv6_mode != 'OFF':
        logger.info("设置IPv6 FORWARD规则...")
        run_cmd(f"ip6tables -C FORWARD -i {network_bridge} -o {main_interface} -j ACCEPT >/dev/null 2>&1 || "
                f"ip6tables -A FORWARD -i {network_bridge} -o {main_interface} -j ACCEPT")
        run_cmd(f"ip6tables -C FORWARD -i {main_interface} -o {network_bridge} -m state --state RELATED,ESTABLISHED -j ACCEPT >/dev/null 2>&1 || "
                f"ip6tables -A FORWARD -i {main_interface} -o {network_bridge} -m state --state RELATED,ESTABLISHED -j ACCEPT")

        # NAT66 出站（SNAT）：仅在 NAT66 模式下启用
        if app_config.ipv6_mode == 'NAT66' and getattr(app_config, 'nat_listen_ipv6', None):
            ok, v6_addr = run_and_capture(f"lxc network get {network_bridge} ipv6.address")
            if ok and v6_addr and v6_addr.lower() != 'none':
                try:
                    # 解析出 /64 子网（将 x::1/64 转为 x::/64）
                    net = ipaddress.ip_network(v6_addr, strict=False)
                    bridge_v6_subnet = f"{net.network_address}/{net.prefixlen}"
                    # 清洗宿主 /128（去除可能的 / 和 []）
                    host_v6 = str(getattr(app_config, 'nat_listen_ipv6')).split('/')[0].strip('[]')
                    logger.info(f"设置IPv6 SNAT (NAT66): {bridge_v6_subnet} -> {main_interface} 使用 {host_v6}")
                    # 先确保 ip6tables 规则（兼容部分环境）
                    run_cmd(
                        f"ip6tables -t nat -C POSTROUTING -s {bridge_v6_subnet} -o {main_interface} -j SNAT --to {host_v6} >/dev/null 2>&1 || "
                        f"ip6tables -t nat -A POSTROUTING -s {bridge_v6_subnet} -o {main_interface} -j SNAT --to {host_v6}"
                    )
                    # 再确保 nftables 规则（在 nf_tables 后端时优先生效）
                    run_cmd("nft add table ip6 nat 2>/dev/null || true")
                    run_cmd("nft 'add chain ip6 nat postrouting { type nat hook postrouting priority srcnat ; }' 2>/dev/null || true")
                    # 仅在不存在等价规则时追加
                    run_cmd(
                        "sh -lc \"nft list chain ip6 nat postrouting | grep -q 'ip6 saddr "
                        f"{bridge_v6_subnet} oifname \"{main_interface}\" snat to {host_v6}' || "
                        f"nft add rule ip6 nat postrouting ip6 saddr {bridge_v6_subnet} oifname \"{main_interface}\" snat to {host_v6}\""
                    )
                except Exception as e:
                    logger.error(f"计算或设置 NAT66 规则失败: {e}")
            else:
                logger.warning("未检测到 lxdbr0 的 IPv6 段或为 none，跳过 NAT66 SNAT 配置")

    # 设置LXD网络DNS
    logger.info("配置LXD网络DNS...")
    run_cmd(f"lxc network set {network_bridge} dns.mode=managed >/dev/null 2>&1")
    run_cmd(f"lxc network set {network_bridge} dns.domain=lxd >/dev/null 2>&1")

    # 保存iptables规则
    logger.info("持久化iptables规则...")
    # 检查是否安装了iptables-persistent
    if run_cmd("which netfilter-persistent >/dev/null 2>&1"):
        run_cmd("netfilter-persistent save")
    else:
        logger.warning("未安装netfilter-persistent，无法持久化保存iptables规则")
        logger.warning("请安装iptables-persistent: apt install -y iptables-persistent")

    # 创建启动脚本
    create_startup_script(network_bridge, main_interface, bridge_subnet)

    logger.info("网络规则设置完成")
    return True

def create_startup_script(network_bridge, main_interface, bridge_subnet):
    """创建启动脚本和systemd服务"""
    logger.info("创建系统启动脚本...")

    # 创建rc.local脚本
    rc_local_content = f"""#!/bin/bash
# LXD容器网络自启动配置脚本 - 由zjmf-lxd-server生成

# 开启IPv4/IPv6 转发与NDP代理
echo 1 > /proc/sys/net/ipv4/ip_forward
sysctl -w net.ipv6.conf.all.forwarding=1 >/dev/null 2>&1
sysctl -w net.ipv6.conf.default.forwarding=1 >/dev/null 2>&1
sysctl -w net.ipv6.conf.all.proxy_ndp=1 >/dev/null 2>&1
sysctl -w net.ipv6.conf.{main_interface}.proxy_ndp=1 >/dev/null 2>&1

# IPv4: 添加NAT规则
iptables -t nat -C POSTROUTING -s {bridge_subnet} -o {main_interface} -j MASQUERADE >/dev/null 2>&1 || \\
iptables -t nat -A POSTROUTING -s {bridge_subnet} -o {main_interface} -j MASQUERADE


# IPv6: 添加FORWARD规则
ip6tables -C FORWARD -i {network_bridge} -o {main_interface} -j ACCEPT >/dev/null 2>&1 || \
ip6tables -A FORWARD -i {network_bridge} -o {main_interface} -j ACCEPT

ip6tables -C FORWARD -i {main_interface} -o {network_bridge} -m state --state RELATED,ESTABLISHED -j ACCEPT >/dev/null 2>&1 || \
ip6tables -A FORWARD -i {main_interface} -o {network_bridge} -m state --state RELATED,ESTABLISHED -j ACCEPT

# IPv6: NAT66 出站（SNAT），在 NAT66 模式时可由主程序再次注入，rc.local 作为兜底
BR6_RAW=$(lxc network get {network_bridge} ipv6.address 2>/dev/null || true)
# 去除空白并统一大小写，避免空字符串或 none 引发解析错误
BR6=$(echo "$BR6_RAW" | tr -d '\r\n[:space:]' | tr '[:upper:]' '[:lower:]')
if [ -n "$BR6" ] && [ "$BR6" != "none" ]; then
  # 将形如 fd42:...::1/64 转为 fd42:...::/64
  BR6_CIDR=$(echo "$BR6" | python3 - << 'PY'
import ipaddress, sys
s=sys.stdin.read().strip()
if not s:
    raise SystemExit(0)
net=ipaddress.ip_network(s, strict=False)
print(f"{{net.network_address}}/{{net.prefixlen}}")
PY
)
  HOST6={getattr(app_config, 'nat_listen_ipv6', '')}
  if [ -n "$HOST6" ]; then
    HOST6=${{HOST6%/*}}
    ip6tables -t nat -C POSTROUTING -s "$BR6_CIDR" -o {main_interface} -j SNAT --to "$HOST6" >/dev/null 2>&1 || \
    ip6tables -t nat -A POSTROUTING -s "$BR6_CIDR" -o {main_interface} -j SNAT --to "$HOST6"
  fi
fi

# IPv4: 添加FORWARD规则
iptables -C FORWARD -i {network_bridge} -o {main_interface} -j ACCEPT >/dev/null 2>&1 || \\
iptables -A FORWARD -i {network_bridge} -o {main_interface} -j ACCEPT

iptables -C FORWARD -i {main_interface} -o {network_bridge} -m state --state RELATED,ESTABLISHED -j ACCEPT >/dev/null 2>&1 || \\
iptables -A FORWARD -i {main_interface} -o {network_bridge} -m state --state RELATED,ESTABLISHED -j ACCEPT

# IPv6: 添加FORWARD规则（不做NAT66）
ip6tables -C FORWARD -i {network_bridge} -o {main_interface} -j ACCEPT >/dev/null 2>&1 || \
ip6tables -A FORWARD -i {network_bridge} -o {main_interface} -j ACCEPT

ip6tables -C FORWARD -i {main_interface} -o {network_bridge} -m state --state RELATED,ESTABLISHED -j ACCEPT >/dev/null 2>&1 || \
ip6tables -A FORWARD -i {main_interface} -o {network_bridge} -m state --state RELATED,ESTABLISHED -j ACCEPT

# 提示：每个容器的NDP代理项由应用在启动与容器创建/重装时自动维护

exit 0
"""
    # 用 UTF-8 写入，避免在非 UTF-8 默认编码环境下因中文注释报 UnicodeEncodeError
    with open('/etc/rc.local', 'w', encoding='utf-8') as f:
        f.write(rc_local_content)

    os.chmod('/etc/rc.local', 0o755)
    logger.info("已创建 /etc/rc.local")

    # 创建systemd服务
    systemd_service_content = """[Unit]
Description=LXD容器网络配置服务
After=network.target lxd.service

[Service]
Type=oneshot
ExecStart=/etc/rc.local
TimeoutSec=0
StandardOutput=journal

[Install]
WantedBy=multi-user.target
"""

    try:
        # 用 UTF-8 写入，避免非 UTF-8 默认编码环境下中文注释导致 UnicodeEncodeError
        with open('/etc/systemd/system/lxd-network-setup.service', 'w', encoding='utf-8') as f:
            f.write(systemd_service_content)

        # 启用服务
        run_cmd("systemctl daemon-reload")
        run_cmd("systemctl enable lxd-network-setup.service")
        logger.info("已创建并启用systemd服务: lxd-network-setup.service")
    except Exception as e:
        logger.error(f"创建systemd服务失败: {str(e)}")

if __name__ == "__main__":
    logger.info("LXD容器网络配置脚本启动")
    if os.geteuid() != 0:
        logger.error("此脚本需要以root权限运行")
        sys.exit(1)

    success = setup_network()
    if success:
        logger.info("网络配置成功完成")
        sys.exit(0)
    else:
        logger.error("网络配置失败")
        sys.exit(1)