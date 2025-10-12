#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
软重基线工具：在不改变周期日期（last_reset_date/next_reset_date）的前提下，
将“当前 LXD 计数（已按业务口径排除 lo）”设为新的基线/最大值，并清空累计段。

用法：
  python3 soft_rebase_baseline.py <容器名>
  python3 soft_rebase_baseline.py --all
"""
import sys
import os
from typing import List

# 项目路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flow_manager import FlowManager
from lxc_manager import LXCManager

def _current_counters_excluding_lo(container) -> (int, int):
    state = container.state()
    rx = tx = 0
    if state.network:
        for if_name, nic in state.network.items():
            if if_name == 'lo' or nic.get('type') == 'loopback':
                continue
            cnt = nic.get('counters', {})
            rx += int(cnt.get('bytes_received', 0))
            tx += int(cnt.get('bytes_sent', 0))
    return rx, tx

def soft_rebase_one(hostname: str, flow_mgr: FlowManager, lxc_mgr: LXCManager) -> bool:
    container = lxc_mgr._get_container_or_error(hostname)
    if not container:
        print(f"❌ 容器不存在：{hostname}")
        return False
    rx, tx = _current_counters_excluding_lo(container)
    ok = flow_mgr.soft_rebase_baseline(hostname, rx, tx)
    if ok:
        print(f"✅ 已软重基线 {hostname}：RX={rx} TX={tx}（已排除 lo），周期日期保持不变")
    else:
        print(f"❌ 软重基线失败：{hostname}")
    return ok

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return

    flow_mgr = FlowManager()
    lxc_mgr = LXCManager()

    if sys.argv[1] == '--all':
        # 遍历数据库中所有容器
        import sqlite3
        with sqlite3.connect(flow_mgr.db_path) as conn:
            rows = conn.execute("SELECT hostname FROM container_flow_management ORDER BY hostname").fetchall()
            names: List[str] = [r[0] for r in rows]
        ok_all = True
        for name in names:
            ok_all = soft_rebase_one(name, flow_mgr, lxc_mgr) and ok_all
        if ok_all:
            print("\n✅ 全部容器软重基线完成。")
        else:
            print("\n⚠️ 部分容器软重基线失败，见上方输出。")
    else:
        name = sys.argv[1]
        soft_rebase_one(name, flow_mgr, lxc_mgr)

if __name__ == '__main__':
    main()

