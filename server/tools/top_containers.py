#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Top N containers by CPU, memory and network (rx/tx) using the LXD Python API (pylxd).

Usage examples (run in the server directory):
  python3 top_containers.py                    # one-shot top 10 by CPU over 1s
  python3 top_containers.py -n 20              # top 20
  python3 top_containers.py -w                 # watch mode, refresh every 2s
  python3 top_containers.py -w -i 5            # watch, 5s interval
  python3 top_containers.py -f XueiV           # only show names containing 'XueiV'

Notes:
- CPU% is sampled over the interval using state.cpu.usage nanoseconds.
- CPU% is normalized by the container's configured cores (limits.cpu, default 1).
- Memory is taken from state.memory.usage (MB).
- Net rx/tx are deltas of state.network.*.counters over the interval (KB/s).
- Only running containers are shown.
"""

import argparse
import os
import sys
import time
from datetime import datetime

# Add parent directory (server/) to Python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from pylxd import Client
except Exception as e:
    print("❌ 需要 pylxd 库，请先安装: pip3 install pylxd", file=sys.stderr)
    raise


def sample_stats(client: 'Client', names: list[str], interval: float = 1.0):
    """Return a dict: name -> (cpu_percent, mem_mb, rx_kbps, tx_kbps)."""
    before_cpu = {}
    before_net = {}
    for n in names:
        c = client.containers.get(n)
        s = c.state()
        before_cpu[n] = s.cpu.get('usage', 0)
        # sum across all nics
        rx = tx = 0
        if s.network:
            for nic in s.network.values():
                cnt = nic.get('counters', {})
                rx += int(cnt.get('bytes_received', 0))
                tx += int(cnt.get('bytes_sent', 0))
        before_net[n] = (rx, tx)

    time.sleep(max(interval, 0.5))

    results = {}
    for n in names:
        c = client.containers.get(n)
        s2 = c.state()
        # cpu
        cpu_after = s2.cpu.get('usage', 0)
        cpu_diff = max(0, cpu_after - before_cpu.get(n, 0))
        try:
            cores = int(c.config.get('limits.cpu', '1'))
            if cores <= 0:
                cores = 1
        except Exception:
            cores = 1
        total_possible = 1_000_000_000 * cores * interval
        cpu_percent = round(cpu_diff / total_possible * 100, 2) if total_possible > 0 else 0.0
        # mem
        try:
            mem_mb = int(s2.memory.get('usage', 0) / (1024 * 1024))
        except Exception:
            mem_mb = 0
        # net
        rx = tx = 0
        if s2.network:
            for nic in s2.network.values():
                cnt = nic.get('counters', {})
                rx += int(cnt.get('bytes_received', 0))
                tx += int(cnt.get('bytes_sent', 0))
        before_rx, before_tx = before_net.get(n, (0,0))
        rx_kbps = round(max(0, rx - before_rx) / 1024 / interval, 2)
        tx_kbps = round(max(0, tx - before_tx) / 1024 / interval, 2)
        results[n] = (max(0.0, cpu_percent), mem_mb, rx_kbps, tx_kbps)
    return results


def fetch_running_names(client: 'Client', name_filter: str | None = None):
    names = []
    for ct in client.containers.all():
        try:
            if ct.status == 'Running':
                if name_filter and name_filter not in ct.name:
                    continue
                names.append(ct.name)
        except Exception:
            continue
    return names


def print_table(rows: list[tuple[str, float, int, float, float]], top_n: int, header: bool = True):
    rows_sorted = sorted(rows, key=lambda x: x[1], reverse=True)[:top_n]
    if header:
        print(f"\nTime: {datetime.now().strftime('%H:%M:%S')} | Showing top {top_n} by CPU%")
        print("NAME\tCPU%\tMEM(MB)\tRX(KB/s)\tTX(KB/s)")
    for name, cpu, mem, rx, tx in rows_sorted:
        print(f"{name}\t{cpu:5.2f}\t{mem}\t{rx:7.2f}\t{tx:7.2f}")


def main():
    ap = argparse.ArgumentParser(description="Top N LXD containers by CPU%")
    ap.add_argument('-n', '--top', type=int, default=10, help='show top N (default 10)')
    ap.add_argument('-w', '--watch', action='store_true', help='watch mode (continuous)')
    ap.add_argument('-i', '--interval', type=float, default=2.0, help='sample/refresh interval seconds (default 2.0)')
    ap.add_argument('-f', '--filter', type=str, default=None, help='name substring filter')
    # Auto-restart options
    ap.add_argument('--auto-restart', action='store_true', help='当CPU持续高占用时自动重启容器')
    ap.add_argument('--cpu-threshold', type=float, default=30.0, help='CPU阈值百分比(0-100)，高于该值视为高占用，默认90')
    ap.add_argument('--cpu-duration', type=float, default=180.0, help='CPU持续高于阈值的秒数，达到后触发重启，默认180秒')
    ap.add_argument('--cooldown', type=float, default=300.0, help='同一容器重启后的冷却期(秒)，默认300')
    ap.add_argument('--max-restarts', type=int, default=3, help='每个容器在监控期间允许的最大自动重启次数，默认3')
    args = ap.parse_args()

    client = Client()

    try:
        if not args.watch:
            names = fetch_running_names(client, args.filter)
            if not names:
                print("无运行中的容器或未匹配到名称。")
                return
            res = sample_stats(client, names, interval=max(args.interval, 1.0))
            rows = [(n, cpu, mem, rx, tx) for n, (cpu, mem, rx, tx) in res.items()]
            print_table(rows, args.top)
        else:
            # Watch mode with optional auto-restart
            high_cpu_since: dict[str, float] = {}
            last_restart_at: dict[str, float] = {}
            restart_counts: dict[str, int] = {}

            if args.auto_restart:
                print(
                    f"启用自动重启策略: CPU>{args.cpu_threshold}% 持续≥{args.cpu_duration}s -> 重启; 冷却期 {int(args.cooldown)}s; 每容器最多 {args.max_restarts} 次\n"
                )
                time.sleep(1)

            while True:
                names = fetch_running_names(client, args.filter)
                if not names:
                    print("无运行中的容器或未匹配到名称。")
                    time.sleep(args.interval)
                    continue

                res = sample_stats(client, names, interval=max(args.interval, 1.0))
                rows = [(n, cpu, mem, rx, tx) for n, (cpu, mem, rx, tx) in res.items()]

                # Clear screen only when attached to a TTY (avoid systemd "TERM not set")
                try:
                    if sys.stdout.isatty():
                        os.system('cls' if os.name == 'nt' else 'clear')
                except Exception:
                    pass
                print_table(rows, args.top)

                # Auto-restart logic after printing table so messages are visible
                if args.auto_restart:
                    now_ts = time.time()
                    for n, (cpu, _mem, _rx, _tx) in res.items():
                        # skip if already reached max restarts
                        if restart_counts.get(n, 0) >= args.max_restarts:
                            continue
                        if cpu >= args.cpu_threshold:
                            start_ts = high_cpu_since.get(n)
                            if start_ts is None:
                                high_cpu_since[n] = now_ts
                            else:
                                duration = now_ts - start_ts
                                if duration >= args.cpu_duration:
                                    last_ts = last_restart_at.get(n, 0)
                                    if (now_ts - last_ts) >= args.cooldown:
                                        try:
                                            print(f"⚠️ 检测到容器 {n} CPU {cpu}% 已持续 ≥ {int(args.cpu_duration)}s，执行重启...")
                                            client.containers.get(n).restart(wait=True)
                                            last_restart_at[n] = time.time()
                                            restart_counts[n] = restart_counts.get(n, 0) + 1
                                            # reset the counter so下一轮重新计时
                                            high_cpu_since[n] = None
                                            print(f"✅ 容器 {n} 已重启完成。(累计自动重启 {restart_counts[n]} 次)")
                                        except Exception as e:
                                            print(f"❌ 重启容器 {n} 失败: {e}", file=sys.stderr)
                                    else:
                                        remain = int(args.cooldown - (now_ts - last_ts))
                                        print(f"⏳ 容器 {n} 高CPU已达阈值，但冷却期未结束，剩余 {remain}s")
                        else:
                            # CPU恢复正常，清除高负载开始时间
                            if n in high_cpu_since and high_cpu_since[n] is not None:
                                high_cpu_since[n] = None

                time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\n已退出。")


if __name__ == '__main__':
    main()

