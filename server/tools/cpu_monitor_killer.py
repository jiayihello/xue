#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
容器CPU监控与自动进程杀手

功能：
1. 实时监控所有容器的CPU占用
2. 当容器CPU持续超过阈值时，自动杀死容器内最占CPU的进程
3. 支持白名单保护（不杀系统关键进程）
4. 支持黑名单优先杀死（如挖矿进程）
5. 详细日志记录

用法：
  python3 cpu_monitor_killer.py                          # 使用默认配置
  python3 cpu_monitor_killer.py --threshold 80           # 自定义CPU阈值
  python3 cpu_monitor_killer.py --duration 120           # 自定义持续时间
  python3 cpu_monitor_killer.py --kill-top 3            # 杀死前3个最耗CPU的进程
  python3 cpu_monitor_killer.py --dry-run               # 只显示不杀（测试模式）

后台运行：
  nohup python3 cpu_monitor_killer.py > cpu_killer.log 2>&1 &
"""

from __future__ import annotations  # Python 3.7+ 兼容性

import argparse
import os
import sys
import time
import re
from datetime import datetime
from typing import Dict, List, Tuple, Optional

# 添加父目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from pylxd import Client
except Exception as e:
    print("❌ 需要 pylxd 库，请先安装: pip3 install pylxd", file=sys.stderr)
    sys.exit(1)


# ==================== 配置 ====================

# 进程白名单（不会被杀死的进程）
WHITELIST_PROCESSES = [
    'systemd', 'init', 'sshd', 'bash', 'sh', 'zsh',
    'python', 'python3', 'nginx', 'apache2', 'mysql', 'mysqld',
    'postgres', 'redis-server', 'memcached', 'mongod',
    'node', 'php-fpm', 'dockerd', 'containerd',
    'cron', 'dbus-daemon', 'systemd-', 'agetty'
]

# 进程黑名单（优先杀死的可疑进程）
BLACKLIST_PROCESSES = [
    'xmrig', 'minergate', 'cpuminer', 'minerd', 'ccminer',
    'ethminer', 'claymore', 'phoenixminer', 'lolminer',
    'nbminer', 'gminer', 'bminer', 't-rex', 'nanominer',
    'xmr-stak', 'cryptonight', 'randomx', 'equihash',
    'kdevtmpfsi', 'kinsing', 'kthrotlds', 'bioset',
    # 常见挖矿或滥用进程特征
    '.sh', 'tmp/.', '/dev/shm/', 'curl.*pool', 'wget.*pool'
]

# ==================== 工具函数 ====================

def log(msg: str, level: str = 'INFO'):
    """日志输出"""
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    prefix = {
        'INFO': '✓',
        'WARN': '⚠️',
        'ERROR': '❌',
        'KILL': '🔪',
        'SKIP': '⏭️'
    }.get(level, 'ℹ️')
    print(f"[{timestamp}] {prefix} {msg}")
    sys.stdout.flush()


def get_container_cpu_usage(client: Client, container_name: str, interval: float = 2.0) -> float:
    """获取容器CPU使用率（%）"""
    try:
        c = client.containers.get(container_name)
        if c.status != 'Running':
            return 0.0
        
        s1 = c.state()
        cpu_before = s1.cpu.get('usage', 0)
        
        time.sleep(interval)
        
        s2 = c.state()
        cpu_after = s2.cpu.get('usage', 0)
        cpu_diff = max(0, cpu_after - cpu_before)
        
        # 获取容器核心数
        try:
            cores = int(c.config.get('limits.cpu', '1'))
            if cores <= 0:
                cores = 1
        except Exception:
            cores = 1
        
        # 计算CPU使用率
        total_possible = 1_000_000_000 * cores * interval
        cpu_percent = (cpu_diff / total_possible * 100) if total_possible > 0 else 0.0
        
        return round(max(0.0, cpu_percent), 2)
    except Exception as e:
        log(f"获取容器 {container_name} CPU失败: {e}", 'ERROR')
        return 0.0


def get_container_top_processes(client: Client, container_name: str, limit: int = 10) -> List[Dict]:
    """获取容器内CPU占用最高的进程列表"""
    try:
        c = client.containers.get(container_name)
        if c.status != 'Running':
            return []
        
        # 在容器内执行 ps 命令获取进程信息
        # 格式：PID %CPU %MEM COMMAND
        result = c.execute(['ps', 'aux', '--sort=-%cpu'])
        if result.exit_code != 0:
            return []
        
        processes = []
        lines = result.stdout.split('\n')[1:]  # 跳过标题行
        
        for line in lines[:limit]:
            if not line.strip():
                continue
            
            parts = line.split(None, 10)
            if len(parts) < 11:
                continue
            
            try:
                proc = {
                    'user': parts[0],
                    'pid': int(parts[1]),
                    'cpu': float(parts[2]),
                    'mem': float(parts[3]),
                    'command': parts[10]
                }
                processes.append(proc)
            except (ValueError, IndexError):
                continue
        
        return processes
    except Exception as e:
        log(f"获取容器 {container_name} 进程列表失败: {e}", 'ERROR')
        return []


def is_whitelisted(command: str) -> bool:
    """检查进程是否在白名单中"""
    cmd_lower = command.lower()
    for pattern in WHITELIST_PROCESSES:
        if pattern.lower() in cmd_lower:
            return True
    return False


def is_blacklisted(command: str) -> bool:
    """检查进程是否在黑名单中"""
    cmd_lower = command.lower()
    for pattern in BLACKLIST_PROCESSES:
        if pattern.lower() in cmd_lower:
            return True
    return False


def kill_process(client: Client, container_name: str, pid: int, signal: int = 9) -> bool:
    """杀死容器内的进程"""
    try:
        c = client.containers.get(container_name)
        result = c.execute(['kill', f'-{signal}', str(pid)])
        return result.exit_code == 0
    except Exception as e:
        log(f"杀死进程失败 (容器={container_name}, PID={pid}): {e}", 'ERROR')
        return False


def select_processes_to_kill(processes: List[Dict], kill_count: int = 1) -> List[Dict]:
    """
    选择要杀死的进程
    优先级：
    1. 黑名单进程
    2. 非白名单的高CPU进程
    """
    # 分类进程
    blacklisted = []
    killable = []
    
    for proc in processes:
        if is_whitelisted(proc['command']):
            continue  # 跳过白名单
        
        if is_blacklisted(proc['command']):
            blacklisted.append(proc)
        else:
            killable.append(proc)
    
    # 优先返回黑名单进程
    selected = blacklisted[:kill_count]
    if len(selected) < kill_count:
        selected.extend(killable[:kill_count - len(selected)])
    
    return selected


# ==================== 主监控逻辑 ====================

def monitor_loop(args):
    """主监控循环"""
    client = Client()
    
    # 记录容器高CPU开始时间
    high_cpu_since: Dict[str, float] = {}
    # 记录容器杀进程次数
    kill_counts: Dict[str, int] = {}
    # 记录上次杀进程时间（用于冷却）
    last_kill_time: Dict[str, float] = {}
    
    log(f"🚀 CPU监控启动 | 阈值={args.threshold}% | 持续时间={args.duration}s | 间隔={args.interval}s")
    log(f"📊 配置: 杀死进程数={args.kill_top} | 冷却期={args.cooldown}s | 最大杀死次数={args.max_kills}")
    if args.dry_run:
        log("🧪 测试模式：只显示不杀", 'WARN')
    
    iteration = 0
    
    while True:
        iteration += 1
        try:
            # 获取所有运行中的容器
            containers = [c.name for c in client.containers.all() if c.status == 'Running']
            
            if not containers:
                log("未找到运行中的容器，等待...")
                time.sleep(args.interval)
                continue
            
            log(f"\n{'='*60}")
            log(f"第 {iteration} 次扫描 | 运行中容器: {len(containers)} 个")
            
            now = time.time()
            
            for container_name in containers:
                # 检查是否达到最大杀死次数
                if kill_counts.get(container_name, 0) >= args.max_kills:
                    continue
                
                # 获取CPU使用率（使用1秒采样，加快扫描速度）
                cpu_usage = get_container_cpu_usage(client, container_name, interval=1.0)
                
                if cpu_usage >= args.threshold:
                    # CPU超过阈值
                    start_time = high_cpu_since.get(container_name)
                    
                    if start_time is None:
                        # 开始记录
                        high_cpu_since[container_name] = now
                        log(f"容器 {container_name} CPU={cpu_usage}% ⚠️ 开始监控", 'WARN')
                    else:
                        # 计算持续时间
                        duration = now - start_time
                        
                        if duration >= args.duration:
                            # 达到持续时间阈值，检查冷却期
                            last_kill = last_kill_time.get(container_name, 0)
                            
                            if (now - last_kill) < args.cooldown:
                                remain = int(args.cooldown - (now - last_kill))
                                log(f"容器 {container_name} CPU={cpu_usage}% 冷却期剩余 {remain}s", 'SKIP')
                                continue
                            
                            # 获取高CPU进程
                            processes = get_container_top_processes(client, container_name, limit=20)
                            
                            if not processes:
                                log(f"容器 {container_name} 无法获取进程列表", 'WARN')
                                continue
                            
                            # 选择要杀死的进程
                            to_kill = select_processes_to_kill(processes, args.kill_top)
                            
                            if not to_kill:
                                log(f"容器 {container_name} 没有可杀死的进程（全部在白名单）", 'SKIP')
                                high_cpu_since[container_name] = None  # 重置
                                continue
                            
                            log(f"容器 {container_name} CPU={cpu_usage}% 持续 {int(duration)}s，准备杀死 {len(to_kill)} 个进程", 'KILL')
                            
                            # 杀死进程
                            killed = 0
                            for proc in to_kill:
                                is_black = is_blacklisted(proc['command'])
                                tag = '🎯黑名单' if is_black else ''
                                
                                log(f"  {tag} PID={proc['pid']} CPU={proc['cpu']}% CMD={proc['command'][:60]}", 'KILL')
                                
                                if not args.dry_run:
                                    if kill_process(client, container_name, proc['pid']):
                                        killed += 1
                                        log(f"    ✓ 已杀死 PID={proc['pid']}", 'KILL')
                                    else:
                                        log(f"    ✗ 杀死失败 PID={proc['pid']}", 'ERROR')
                                else:
                                    log(f"    🧪 测试模式，跳过杀死", 'WARN')
                                    killed += 1
                            
                            # 更新统计
                            kill_counts[container_name] = kill_counts.get(container_name, 0) + killed
                            last_kill_time[container_name] = now
                            high_cpu_since[container_name] = None  # 重置监控
                            
                            log(f"容器 {container_name} 已处理 | 杀死={killed}个 | 累计={kill_counts[container_name]}次")
                        else:
                            remain = int(args.duration - duration)
                            log(f"容器 {container_name} CPU={cpu_usage}% 持续 {int(duration)}s，还需 {remain}s")
                else:
                    # CPU正常
                    if high_cpu_since.get(container_name) is not None:
                        log(f"容器 {container_name} CPU={cpu_usage}% ✓ 恢复正常")
                        high_cpu_since[container_name] = None
            
            # 扫描完成后等待，确保总周期接近interval设定值
            # 45个容器×1秒采样≈45秒，再等待保证不会太频繁
            time.sleep(max(5, args.interval))
            
        except KeyboardInterrupt:
            log("\n收到终止信号，退出监控...")
            break
        except Exception as e:
            log(f"监控循环出错: {e}", 'ERROR')
            time.sleep(args.interval)


# ==================== 命令行参数 ====================

def main():
    parser = argparse.ArgumentParser(
        description='容器CPU监控与自动进程杀手',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    
    # 监控参数
    parser.add_argument('--threshold', type=float, default=60.0,
                        help='CPU阈值百分比，默认60%%')
    parser.add_argument('--duration', type=float, default=180.0,
                        help='CPU持续高于阈值的秒数，默认180秒')
    parser.add_argument('--interval', type=float, default=5.0,
                        help='监控间隔秒数，默认5秒')
    
    # 动作参数
    parser.add_argument('--kill-top', type=int, default=1,
                        help='每次杀死最高CPU的N个进程，默认1')
    parser.add_argument('--cooldown', type=float, default=300.0,
                        help='同一容器杀进程后的冷却期(秒)，默认300')
    parser.add_argument('--max-kills', type=int, default=10,
                        help='每个容器最多杀死进程次数，默认10')
    
    # 测试参数
    parser.add_argument('--dry-run', action='store_true',
                        help='测试模式：只显示不杀进程')
    
    args = parser.parse_args()
    
    # 参数验证
    if args.threshold <= 0 or args.threshold > 100:
        print("❌ CPU阈值必须在 0-100 之间", file=sys.stderr)
        sys.exit(1)
    
    if args.duration < 10:
        print("❌ 持续时间至少需要 10 秒", file=sys.stderr)
        sys.exit(1)
    
    # 启动监控
    monitor_loop(args)


if __name__ == '__main__':
    main()
