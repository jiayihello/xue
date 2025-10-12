#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
List current-period flow usage for all registered containers using FlowManager.
- Shows Used(GB) and Remaining(GB) when a limit is set; otherwise marks as '不限'.
- Reads current LXD counters to compute up-to-date usage, preserving continuity.
"""

import os
import sys
import sqlite3
from typing import List, Tuple

# Allow import from this project folder
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from datetime import datetime

try:
    from flow_manager import FlowManager
    from lxc_manager import LXCManager
except Exception as e:
    print(f"❌ 依赖导入失败: {e}")
    sys.exit(1)


def get_registered_containers(conn: sqlite3.Connection) -> List[Tuple[str, int]]:
    cur = conn.execute(
        "SELECT hostname, COALESCE(flow_limit_gb, 0) FROM container_flow_management ORDER BY hostname"
    )
    return [(row[0], int(row[1] or 0)) for row in cur.fetchall()]


def format_gb(v: float) -> str:
    try:
        return f"{float(v):.2f}"
    except Exception:
        return "-"


def main():
    try:
        flow_mgr = FlowManager()
        lxc_mgr = LXCManager()
    except Exception as e:
        print(f"❌ 初始化失败: {e}")
        sys.exit(1)

    # Open DB
    try:
        conn = sqlite3.connect(flow_mgr.db_path)
    except Exception as e:
        print(f"❌ 无法打开数据库: {e}")
        sys.exit(1)

    with conn:
        items = get_registered_containers(conn)

    if not items:
        print("未在流量管理系统中找到容器记录。可运行: lxd-flow-manager register")
        return

    rows = []
    for hostname, limit_gb in items:
        try:
            container = lxc_mgr._get_container_or_error(hostname)
            if not container:
                rows.append((hostname, None, None, limit_gb, '容器不存在'))
                continue

            state = container.state()
            rx = tx = 0
            if state.network:
                for if_name, nic in state.network.items():
                    # 排除环回接口 lo（不计入对外流量口径）
                    if if_name == 'lo' or nic.get('type') == 'loopback':
                        continue
                    cnt = nic.get('counters', {})
                    rx += int(cnt.get('bytes_received', 0))
                    tx += int(cnt.get('bytes_sent', 0))

            used_gb = flow_mgr.calculate_current_period_usage(hostname, rx, tx)
            if limit_gb and limit_gb > 0:
                remain_gb = max(0.0, float(limit_gb) - float(used_gb))
            else:
                remain_gb = None  # 不限

            rows.append((hostname, used_gb, remain_gb, limit_gb, None))
        except Exception as e:
            rows.append((hostname, None, None, limit_gb, f"计算失败: {e}"))

    # Print table
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print(f"\n时间: {now} | 所有容器当前周期流量使用情况")
    header = ["NAME", "Used(GB)", "Remaining(GB)", "Limit(GB)", "Note"]

    # widths
    name_w = max(len(header[0]), *(len(r[0]) for r in rows))
    def strlen(s):
        return len(s) if s is not None else 1
    used_w = max(len(header[1]), *(strlen(format_gb(r[1])) for r in rows))
    rem_w = max(len(header[2]), *(strlen("不限") if r[2] is None else strlen(format_gb(r[2])) for r in rows))
    lim_w = max(len(header[3]), *(strlen(str(r[3])) for r in rows))
    note_w = len(header[4])

    print(f"{header[0]:<{name_w}}  {header[1]:>{used_w}}  {header[2]:>{rem_w}}  {header[3]:>{lim_w}}  {header[4]}")
    for name, used, remain, limit_gb, note in rows:
        used_s = format_gb(used) if used is not None else "-"
        rem_s = ("不限" if remain is None else format_gb(remain)) if used is not None else "-"
        note_s = note or ""
        print(f"{name:<{name_w}}  {used_s:>{used_w}}  {rem_s:>{rem_w}}  {str(limit_gb):>{lim_w}}  {note_s}")


if __name__ == "__main__":
    main()

