#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Retrofit existing NAT port mappings to dual-stack (IPv4+IPv6) for NAT66 mode.
- For each container and each existing "nat-<proto>-<dport>" proxy device:
  * Ensure there is a matching IPv6 device "nat-<proto>-<dport>-v6"
    listen=tcp:[NAT_LISTEN_IPV6]:<dport>, connect to the same container host:port, bind=host
  * Normalize the IPv4 device to listen on NAT_LISTEN_IP (no longer 0.0.0.0), bind=host
  * Optionally remove legacy "-v4" devices if present
- Idempotent: safe to run multiple times

Usage:
  python3 server/retrofit_nat66_dualstack.py
"""

import re
import sys
import logging
import subprocess
import time

from config_handler import app_config
from lxc_manager import LXCManager

logging.basicConfig(level=logging.INFO, format='[%(levelname)s] %(message)s')
log = logging.getLogger('retrofit_nat66')


def _parse_host_port(s: str):
    """Parse 'tcp|udp:HOST:PORT' where HOST can be IPv4, name, or [IPv6]."""
    m = re.match(r'^(tcp|udp):(\[.*\]|[^:]+):(\d+)$', s)
    if not m:
        return None
    proto, host, port = m.group(1), m.group(2), m.group(3)
    host = host.strip('[]')
    return proto, host, port


def parse_proxy(dev: dict):
    """Parse LXD proxy device listen/connect into dict or None.
    Supports IPv6 addresses wrapped in brackets.
    """
    lis = dev.get('listen', '')
    con = dev.get('connect', '')
    m = _parse_host_port(lis)
    n = _parse_host_port(con)
    if not (m and n):
        return None
    return {
        'proto': m[0],
        'listen_host': m[1],
        'dport': m[2],
        'connect_host': n[1],
        'sport': n[2]
    }


def _get_local_ipv4():
    addrs = set()
    try:
        out = subprocess.check_output(['ip', '-4', 'addr'], text=True, errors='ignore')
        for m in re.finditer(r'inet\s+(\d+\.\d+\.\d+\.\d+)/(\d+)', out):
            addrs.add(m.group(1))
    except Exception:
        pass
    return addrs


def _get_local_ipv6():
    addrs = set()
    try:
        out = subprocess.check_output(['ip', '-6', 'addr'], text=True, errors='ignore')
        for m in re.finditer(r'inet6\s+([0-9a-fA-F:]+)/\d+', out):
            addrs.add(m.group(1).lower())
    except Exception:
        pass
    return addrs


def main():
    if str(getattr(app_config, 'ipv6_mode', 'OFF')).upper() != 'NAT66':
        log.info('IPV6_MODE != NAT66，跳过（无需改造）。')
        return 0

    v4_host = getattr(app_config, 'nat_listen_ip', None)
    if not v4_host:
        log.error('NAT_LISTEN_IP 未配置，无法规范化 IPv4 监听地址。中止。')
        return 2
    v6_conf = getattr(app_config, 'nat_listen_ipv6', None) or '::'
    v6_host = str(v6_conf).split('/')[0].strip('[]') if v6_conf else '::'

    # Resolve local addresses to avoid binding to non-local IPs (esp. IPv6 /128 not on host)
    local_v4 = _get_local_ipv4()
    local_v6 = _get_local_ipv6()
    allow_v4 = (v4_host == '0.0.0.0') or (v4_host in local_v4)
    allow_v6 = (v6_host == '::') or (v6_host.lower() in local_v6)

    lxc = LXCManager()
    client = lxc.client

    changed_cts = []
    failed_cts = []

    for ct in client.containers.all():
        name = ct.name
        devices = dict(ct.devices or {})
        # Map (proto, dport) -> list of (dev_name, info_dict)
        groups = {}
        legacy_v4_names = []

        for dev_name, dev in devices.items():
            if dev.get('type') != 'proxy' or not dev_name.startswith('nat-'):
                continue
            info = parse_proxy(dev)
            if not info:
                continue
            # legacy -v4 naming
            if dev_name.endswith('-v4'):
                legacy_v4_names.append(dev_name)
            key = (info['proto'].lower(), info['dport'])
            groups.setdefault(key, []).append((dev_name, info))

        dirty = False
        ct_errors = []

        for (proto, dport), items in groups.items():
            # Determine presence of standard v4/v6 devices
            std_v4_name = f'nat-{proto}-{dport}'
            std_v6_name = f'{std_v4_name}-v6'

            have_v4 = any(n == std_v4_name for n, _ in items)
            have_v6 = any(n == std_v6_name for n, _ in items)

            # Pick a source record (first in group)
            base_info = items[0][1]
            connect_host = base_info['connect_host']
            sport = base_info['sport']

            # 1) Normalize IPv4 listen to NAT_LISTEN_IP (keep connect as-is)
            if have_v4:
                dev = devices.get(std_v4_name, {}).copy()
                info = parse_proxy(dev)
                if not allow_v4:
                    log.warning(f"[{name}] 跳过规范化 IPv4 监听：{v4_host} 不是本机地址")
                elif info and info['listen_host'] != v4_host:
                    dev['listen'] = f"{proto}:{v4_host}:{dport}"
                    dev['bind'] = 'host'
                    devices[std_v4_name] = dev
                    dirty = True
                    log.info(f"[{name}] 规范化 IPv4 监听: {std_v4_name} -> {v4_host}:{dport}")

            # 2) If IPv6 counterpart missing, create it
            if not have_v6:
                if not allow_v6:
                    log.warning(f"[{name}] 跳过创建 IPv6 监听：{v6_host} 不在本机任何网卡上（或使用 ::）")
                else:
                    devices[std_v6_name] = {
                        'type': 'proxy',
                        'listen': f'{proto}:[{v6_host}]:{dport}',
                        'connect': f'{proto}:{connect_host}:{sport}',
                        'bind': 'host'
                    }
                    dirty = True
                    log.info(f"[{name}] 补充 IPv6 监听: {std_v6_name} -> [{v6_host}]:{dport}")

        # 3) Optionally remove legacy -v4 devices if a standard v4 exists
        for legacy_name in legacy_v4_names:
            # Derive std name from legacy: nat-proto-dport-v4 => nat-proto-dport
            parts = legacy_name.split('-')
            if len(parts) >= 4 and parts[-1] == 'v4':
                std_name = '-'.join(parts[:-1])
                if std_name in devices:
                    try:
                        del devices[legacy_name]
                        dirty = True
                        log.info(f"[{name}] 移除历史设备: {legacy_name}")
                    except Exception as e:
                        ct_errors.append(f"移除历史设备失败 {legacy_name}: {e}")

        if dirty:
            try:
                ct.devices = devices
                ct.save(wait=True)
                time.sleep(0.02)
                changed_cts.append(name)
            except Exception as e:
                failed_cts.append(name)
                log.error(f"[{name}] 保存设备变更失败: {e}")
                # No rollback here; administrator can re-run after resolving conflicts
                continue

    log.info('完成。')
    log.info('变更容器数: %d -> %s', len(changed_cts), ','.join(changed_cts) or '-')
    if failed_cts:
        log.warning('保存失败容器数: %d -> %s', len(failed_cts), ','.join(failed_cts))
    return 0


if __name__ == '__main__':
    sys.exit(main())

