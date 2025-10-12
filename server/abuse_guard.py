#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Abuse Guard - 基于 iptables/ip6tables 的简单滥用防护
- 目标：阻断常见挖矿、BT、端口扫描/反射滥用端口
- 作用范围：LXD bridge <-> 外网 主接口 的转发流量
- 特性：
  * 同时支持 IPv4 与 IPv6
  * 使用独立自定义链（ABUSE_GUARD/ABUSE_GUARD6），与现有规则解耦
  * 仅影响容器经由网桥的流量，对宿主机本地不生效
  * 自动配置定时任务（每天刷新黑名单 + 开机自动应用）

命令：
  python3 abuse_guard.py apply            # 应用/刷新规则（自动配置定时任务）
  python3 abuse_guard.py apply --skip-cron # 应用规则但跳过定时任务配置
  python3 abuse_guard.py remove           # 移除规则
  python3 abuse_guard.py status           # 查看状态

定时任务（自动配置）：
  每天 4:15  - 刷新域名黑名单并应用规则
  开机启动   - 自动应用防护规则

注意：
- 该脚本使用 iptables/ip6tables（legacy 接口）。若系统为纯 nftables 环境，请按需改造。
- 规则尽量保守，避免影响正常业务；如需调整端口清单，可修改 PORTS_* 列表后重新 apply。
- 定时任务在首次 apply 时自动配置，如已存在则跳过。
"""

import subprocess
import sys
import os

# 复用现有配置
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config_handler import app_config  # type: ignore


# 功能开关与名单
ENABLE_DOMAIN_BLACKLIST = True
# 挖矿/扫描/工具站等（按需扩展）
DOMAIN_BLACKLIST = [
    'ethermine.com', 'antpool.com', 'antpool.one', 'pool.bar',
    'zmap.io', 'nmap.org', 'foofus.net',
]

# 字符串匹配（明文流量才有效，默认关闭以避免误伤/开销）
ENABLE_STRING_MATCH = False
KEYWORDS_BLOCK = [
    # BT/DHT
    'torrent', '.torrent', 'peer_id=', 'announce', 'info_hash', 'get_peers',
    'find_node', 'BitTorrent', 'announce_peer', 'magnet:',
    # Mining
    'seed_hash'
]

import socket
from typing import List, Tuple

def _resolve_domains(domains: List[str]) -> Tuple[List[str], List[str]]:
    """解析域名到 IPv4/IPv6 列表（去重）。失败时忽略个别域名。"""
    v4, v6 = set(), set()
    for d in domains:
        try:
            infos = socket.getaddrinfo(d, None)
            for fam, _, _, _, sockaddr in infos:
                ip = sockaddr[0]
                if ':' in ip:
                    v6.add(ip)
                else:
                    v4.add(ip)
        except Exception:
            pass
    return list(v4), list(v6)

def _ensure_ipset(name: str, ipv6: bool, members: List[str]):
    family = 'inet6' if ipv6 else 'inet'
    # 创建集合（存在则忽略），并清空旧成员
    run(f"ipset create {name} hash:ip family {family} -exist")
    run(f"ipset flush {name}")
    for ip in members:
        run(f"ipset add {name} {ip} -exist")

def _maybe_add_string_rules(tool: str, chain: str):
    if not ENABLE_STRING_MATCH:
        return
    for kw in KEYWORDS_BLOCK:
        # 在自定义链中追加字符串匹配丢弃（IPv4/IPv6 通用）
        run(f"{tool} -A {chain} -m string --string \"{kw}\" --algo bm -j DROP")

# 可自定义的端口清单（尽量保守）
PORTS_TCP_BLOCK = [
    # 邮件/SMB等常见滥用端口（服务器不应从容器直发）
    25, 465, 587, 139, 445,
    # 常见矿池端口（不会拦 80/443 以免误伤）
    3333, 4444, 5555, 6666, 7777, 9999, 14444, 3334, 3555,
    # BT 常用端口
    51413,
]
# UDP 范围尽量保守：DHT/BT、SSDP、Memcached 放大
PORTS_UDP_BLOCK = [11211, 1900, 51413]
RANGE_UDP_BLOCK = [(6881, 6999)]  # BT/DHT


def run(cmd: str) -> tuple[bool, str, str]:
    try:
        p = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        return p.returncode == 0, p.stdout.strip(), p.stderr.strip()
    except Exception as e:
        return False, "", str(e)


def _ensure_chain(ipv6: bool = False):
    chain = "ABUSE_GUARD6" if ipv6 else "ABUSE_GUARD"
    tool = "ip6tables" if ipv6 else "iptables"
    # 创建链
    run(f"{tool} -nL {chain} >/dev/null 2>&1 || {tool} -N {chain}")
    # 先清空链中的旧规则
    run(f"{tool} -F {chain}")

    bridge = app_config.network_bridge
    main_if = app_config.main_interface

    # 将链接入 FORWARD 两个方向（在靠前位置插入）
    for rule in [
        f"{tool} -C FORWARD -i {bridge} -o {main_if} -j {chain} >/dev/null 2>&1 || {tool} -I FORWARD 1 -i {bridge} -o {main_if} -j {chain}",
        f"{tool} -C FORWARD -i {main_if} -o {bridge} -j {chain} >/dev/null 2>&1 || {tool} -I FORWARD 1 -i {main_if} -o {bridge} -j {chain}",
    ]:
        run(rule)

    # 端口阻断规则（出于稳妥，使用 multiport 和范围）
    if PORTS_TCP_BLOCK:
        ports = ",".join(str(p) for p in PORTS_TCP_BLOCK)
        run(f"{tool} -A {chain} -p tcp -m multiport --dports {ports} -j REJECT --reject-with tcp-reset")
    if PORTS_UDP_BLOCK:
        ports = ",".join(str(p) for p in PORTS_UDP_BLOCK)
        run(f"{tool} -A {chain} -p udp -m multiport --dports {ports} -j DROP")
    for start, end in RANGE_UDP_BLOCK:
        run(f"{tool} -A {chain} -p udp --dport {start}:{end} -j DROP")

    # 域名黑名单（解析并使用 ipset）
    if ENABLE_DOMAIN_BLACKLIST and DOMAIN_BLACKLIST:
        v4, v6 = _resolve_domains(DOMAIN_BLACKLIST)
        set_name = "ABUSE_DOMAINS_V6" if ipv6 else "ABUSE_DOMAINS_V4"
        members = v6 if ipv6 else v4
        _ensure_ipset(set_name, ipv6, members)
        run(f"{tool} -A {chain} -m set --match-set {set_name} dst -j DROP")

    # 可选的字符串匹配（明文流量）
    _maybe_add_string_rules(tool, chain)


def setup_crontab():
    """配置定时任务：每天刷新黑名单 + 开机自动应用"""
    try:
        # 获取脚本的绝对路径
        script_path = os.path.abspath(__file__)
        script_dir = os.path.dirname(script_path)
        
        # 获取当前 crontab
        result = subprocess.run(['crontab', '-l'], capture_output=True, text=True)
        existing_crontab = result.stdout if result.returncode == 0 else ""
        
        # 定义要添加的任务
        daily_job = f"15 4 * * * cd {script_dir} && /usr/bin/python3 {script_path} apply >/dev/null 2>&1"
        reboot_job = f"@reboot sleep 30 && cd {script_dir} && /usr/bin/python3 {script_path} apply >/dev/null 2>&1"
        
        # 检查是否已存在
        has_daily = "abuse_guard.py apply" in existing_crontab and "15 4" in existing_crontab
        has_reboot = "abuse_guard.py apply" in existing_crontab and "@reboot" in existing_crontab
        
        needs_update = False
        new_jobs = []
        
        if not has_daily:
            new_jobs.append(daily_job)
            needs_update = True
            print("  📅 添加定时任务：每天 4:15 刷新黑名单")
        else:
            print("  ✅ 定时任务已存在：每天 4:15 刷新黑名单")
        
        if not has_reboot:
            new_jobs.append(reboot_job)
            needs_update = True
            print("  🔄 添加定时任务：开机自动应用规则")
        else:
            print("  ✅ 定时任务已存在：开机自动应用规则")
        
        # 如果需要更新，添加新任务
        if needs_update:
            new_crontab = existing_crontab.rstrip('\n')
            if new_crontab:
                new_crontab += '\n'
            new_crontab += '\n'.join(new_jobs) + '\n'
            
            # 写入新的 crontab
            proc = subprocess.Popen(['crontab', '-'], stdin=subprocess.PIPE, text=True)
            proc.communicate(input=new_crontab)
            
            if proc.returncode == 0:
                print("  ✅ 定时任务配置成功")
            else:
                print("  ⚠️  定时任务配置失败（可能需要 root 权限）")
        
    except FileNotFoundError:
        print("  ⚠️  未找到 crontab 命令，跳过定时任务配置")
    except Exception as e:
        print(f"  ⚠️  配置定时任务时出错: {e}")


def remove_rules():
    for ipv6 in (False, True):
        chain = "ABUSE_GUARD6" if ipv6 else "ABUSE_GUARD"
        tool = "ip6tables" if ipv6 else "iptables"
        bridge = app_config.network_bridge
        main_if = app_config.main_interface
        # 先从 FORWARD 移除引用
        run(f"{tool} -D FORWARD -i {bridge} -o {main_if} -j {chain} >/dev/null 2>&1")
        run(f"{tool} -D FORWARD -i {main_if} -o {bridge} -j {chain} >/dev/null 2>&1")
        # 再清空并删除自定义链
        run(f"{tool} -F {chain} >/dev/null 2>&1")
        run(f"{tool} -X {chain} >/dev/null 2>&1")
    print("✅ Abuse Guard 规则已移除")


def status():
    for tool, chain in (("iptables", "ABUSE_GUARD"), ("ip6tables", "ABUSE_GUARD6")):
        ok, out, err = run(f"{tool} -S {chain}")
        print(f"[{tool}] {chain}:")
        if ok:
            print(out or "(无规则)")
        else:
            print("(不存在)")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(0)
    
    cmd = sys.argv[1]
    skip_cron = "--skip-cron" in sys.argv
    
    if cmd == "apply":
        # 应用规则
        _ensure_chain(False)
        _ensure_chain(True)
        print("✅ Abuse Guard 规则已应用/刷新 (IPv4+IPv6)")
        
        # 配置定时任务（除非指定跳过）
        if not skip_cron:
            print("\n📋 检查定时任务配置...")
            setup_crontab()
        else:
            print("\n⏭️  已跳过定时任务配置")
    
    elif cmd == "remove":
        remove_rules()
    
    elif cmd == "status":
        status()
    
    else:
        print("未知命令:", cmd)
        print("\n使用说明：")
        print("  python3 abuse_guard.py apply            # 应用规则并配置定时任务")
        print("  python3 abuse_guard.py apply --skip-cron # 应用规则但跳过定时任务")
        print("  python3 abuse_guard.py remove           # 移除规则")
        print("  python3 abuse_guard.py status           # 查看状态")
        sys.exit(1)

