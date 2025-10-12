#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Attach IPv6 for containers that miss a routed IPv6 device (eth0v6),
OR fix existing eth0v6 that has no ipv6.address/incorrect parent.

Usage:
  python3 attach_ipv6_missing.py               # batch fix all containers
  python3 attach_ipv6_missing.py <container>   # fix single container

Prerequisites:
  - app.ini must configure IPv6: IPV6_MODE=ROUTED and a /64 IPV6_PREFIX
"""

import sys
import os
from typing import Tuple

# Import project modules
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lxc_manager import LXCManager  # type: ignore
from ipv6_manager import allocate   # type: ignore
from config_handler import app_config  # type: ignore


def ensure_eth0v6(container, parent_if: str) -> Tuple[str, str]:
    """Ensure the container has eth0v6 with a valid ipv6.address and parent.
    Returns (status, message) where status in {ok_add, ok_update, skip, fail}.
    """
    name = container.name
    try:
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

    parent_if = getattr(app_config, 'ipv6_interface', None) or app_config.main_interface

    lxc = LXCManager()
    client = lxc.client

    # Targets
    if len(sys.argv) > 1:
        names = [sys.argv[1]]
    else:
        names = [c.name for c in client.containers.all()]

    ok_add = ok_update = skip = fail = 0
    for name in names:
        try:
            c = client.containers.get(name)
        except Exception as e:
            print(f"❌ {name}: container not found ({e})"); fail += 1; continue

        status, msg = ensure_eth0v6(c, parent_if)
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


if __name__ == '__main__':
    main()

