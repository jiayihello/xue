#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Attach IPv6 for containers that miss a routed IPv6 device (eth0v6),
OR fix existing eth0v6 that has no ipv6.address/incorrect parent.

Usage:
  python3 attach_ipv6_missing.py               # batch fix all containers
  python3 attach_ipv6_missing.py <container>   # fix single container
  python3 attach_ipv6_missing.py --force       # force reassign all (replace ULA with public)

Prerequisites:
  - app.ini must configure IPv6: IPV6_MODE=ROUTED and a /64 IPV6_PREFIX
"""

import sys
import os
import ipaddress
from typing import Tuple

# Import project modules
# Add parent directory (server/) to Python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lxc_manager import LXCManager  # type: ignore
from ipv6_manager import allocate, release   # type: ignore
from config_handler import app_config  # type: ignore


def is_ula_address(addr_str):
    """检查是否为ULA地址 (fd00::/8)"""
    try:
        addr = ipaddress.IPv6Address(addr_str)
        return addr.packed[0] == 0xfd
    except Exception:
        return False


def ensure_eth0v6(container, parent_if: str, force_reassign: bool = False) -> Tuple[str, str]:
    """Ensure the container has eth0v6 with a valid ipv6.address and parent.
    
    Args:
        container: LXD container object
        parent_if: Parent network interface
        force_reassign: If True, release and reassign ULA addresses to public IPv6
    
    Returns (status, message) where status in {ok_add, ok_update, skip, fail}.
    """
    name = container.name
    try:
        # 如果启用强制重分配且当前地址是ULA，则释放旧记录
        if force_reassign:
            dev = container.devices.get('eth0v6')
            if dev:
                old_addr = dev.get('ipv6.address', '')
                if old_addr and is_ula_address(old_addr):
                    release(name)  # 释放旧的ULA地址记录
        
        # Allocate a stable IPv6 for this hostname (idempotent)
        ip6 = allocate(name)
        if not ip6:
            return ("fail", f"{name}: allocate IPv6 failed (check app.ini IPV6_MODE/PREFIX)")

        dev = container.devices.get('eth0v6')
        if not dev:
            # Create device
            container.devices['eth0v6'] = {
                'type': 'nic',
                'nictype': 'routed',
                'parent': parent_if,
                'ipv6.address': ip6,
            }
            container.save(wait=True)
            return ("ok_add", f"{name}: added eth0v6 with {ip6}")
        else:
            # Fix/patch device fields
            changed = False
            if dev.get('type') != 'nic':
                dev['type'] = 'nic'; changed = True
            if dev.get('nictype') != 'routed':
                dev['nictype'] = 'routed'; changed = True
            if dev.get('parent') != parent_if:
                dev['parent'] = parent_if; changed = True
            if dev.get('ipv6.address') != ip6:
                dev['ipv6.address'] = ip6; changed = True

            if changed:
                container.devices['eth0v6'] = dev
                container.save(wait=True)
                return ("ok_update", f"{name}: updated eth0v6 -> {ip6}")
            else:
                return ("skip", f"{name}: already has eth0v6 with {ip6}")
    except Exception as e:
        return ("fail", f"{name}: error {e}")


def main():
    mode = str(getattr(app_config, 'ipv6_mode', 'OFF')).upper()
    prefix = getattr(app_config, 'ipv6_prefix', None)
    if mode != 'ROUTED' or not prefix:
        print('❌ 请先在 app.ini 配置 IPv6：IPV6_MODE=ROUTED 且 IPV6_PREFIX=/64 前缀')
        sys.exit(1)

    # 检查是否为公网IPv6前缀
    try:
        prefix_net = ipaddress.IPv6Network(prefix, strict=False)
        if prefix_net.network_address.packed[0] == 0xfd:
            print(f'❌ IPV6_PREFIX 配置的是ULA内网地址: {prefix}')
            print('   请修改为公网IPv6前缀，例如: 2a01:e281:ac01:f3::/64')
            sys.exit(1)
    except Exception as e:
        print(f'❌ IPV6_PREFIX 格式错误: {e}')
        sys.exit(1)

    parent_if = getattr(app_config, 'ipv6_interface', None) or app_config.main_interface

    # 检查是否启用强制重分配模式
    force_reassign = '--force' in sys.argv or '-f' in sys.argv
    if force_reassign:
        print('🔄 强制重分配模式：将替换所有ULA内网IPv6为公网IPv6')
        print(f'   公网前缀: {prefix}\n')

    lxc = LXCManager()
    client = lxc.client

    # Targets
    args = [arg for arg in sys.argv[1:] if not arg.startswith('-')]
    if args:
        names = args
    else:
        names = [c.name for c in client.containers.all()]

    ok_add = ok_update = skip = fail = 0
    for name in names:
        try:
            c = client.containers.get(name)
        except Exception as e:
            print(f"❌ {name}: container not found ({e})"); fail += 1; continue

        status, msg = ensure_eth0v6(c, parent_if, force_reassign=force_reassign)
        print(("✅ " if status.startswith('ok') else "➖ " if status=='skip' else "❌ ") + msg)
        if status == 'ok_add':
            ok_add += 1
        elif status == 'ok_update':
            ok_update += 1
        elif status == 'skip':
            skip += 1
        else:
            fail += 1

    print('\n=== Summary ===')
    print(f"OK(add):   {ok_add}")
    print(f"OK(update):{ok_update}")
    print(f"SKIP:      {skip}")
    print(f"FAIL:      {fail}")
    
    if force_reassign and (ok_add + ok_update) > 0:
        print('\n⚠️  重要提示:')
        print('1. 请重启 lxd-api 服务: systemctl restart lxd-api')
        print('2. 在魔方财务后台同步受影响的产品')
        print('3. 客户前端将显示新的公网IPv6地址')


if __name__ == '__main__':
    main()

