#!/usr/bin/env python3
"""
qBittorrent 进程检测限速器
检测到 qBittorrent 进程的容器自动限速
"""

import subprocess
import json
import logging
import argparse
import time
from datetime import datetime
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# BT 客户端进程名列表
BT_PROCESSES = [
    'qbittorrent',
    'qbittorrent-nox',
    'transmission',
    'transmission-daemon',
    'deluge',
    'deluged',
    'rtorrent',
    'aria2c',
]

STATE_FILE = '/tmp/qb_limiter_state.json'


def run_cmd(cmd, timeout=30):
    """执行命令"""
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, 
            text=True, timeout=timeout
        )
        return result.stdout.strip(), result.returncode
    except Exception as e:
        logger.error(f"命令执行失败: {cmd}, 错误: {e}")
        return "", 1


def get_containers():
    """获取所有运行中的容器"""
    output, _ = run_cmd("lxc list -c n,s --format csv")
    containers = []
    for line in output.split('\n'):
        if not line.strip():
            continue
        parts = line.split(',')
        if len(parts) >= 2 and parts[1].strip() == 'RUNNING':
            containers.append(parts[0].strip())
    return containers


def check_bt_process(container):
    """检查容器内是否有 BT 客户端进程"""
    # 构建 grep 模式
    pattern = '|'.join(BT_PROCESSES)
    cmd = f"lxc exec {container} -- pgrep -l -f '{pattern}' 2>/dev/null"
    output, code = run_cmd(cmd)
    
    if output:
        # 过滤掉误匹配（如 BT-Panel）
        lines = output.split('\n')
        bt_found = []
        for line in lines:
            line_lower = line.lower()
            # 排除宝塔面板
            if 'bt-panel' in line_lower or 'bt-task' in line_lower:
                continue
            # 检查是否真的是 BT 客户端
            for proc in BT_PROCESSES:
                if proc in line_lower:
                    bt_found.append(line.strip())
                    break
        return bt_found
    return []


def get_current_limit(container):
    """获取容器当前的带宽和IO限制"""
    ingress, _ = run_cmd(f"lxc config device get {container} eth0 limits.ingress")
    egress, _ = run_cmd(f"lxc config device get {container} eth0 limits.egress")
    io_read, _ = run_cmd(f"lxc config device get {container} root limits.read")
    io_write, _ = run_cmd(f"lxc config device get {container} root limits.write")
    return {
        'ingress': ingress or '',
        'egress': egress or '',
        'io_read': io_read or '',
        'io_write': io_write or ''
    }


def set_limit(container, limit_mbps, io_limit_mb=10):
    """设置容器带宽和IO限制"""
    # 网络限制
    limit = f"{limit_mbps}Mbit"
    run_cmd(f"lxc config device set {container} eth0 limits.ingress={limit}")
    run_cmd(f"lxc config device set {container} eth0 limits.egress={limit}")
    # IO 限制
    io_limit = f"{io_limit_mb}MB"
    run_cmd(f"lxc config device set {container} root limits.read={io_limit}")
    run_cmd(f"lxc config device set {container} root limits.write={io_limit}")
    logger.info(f"✓ 已限制 {container} 带宽={limit_mbps}Mbps, IO={io_limit_mb}MB/s")


def restore_limit(container, original):
    """恢复容器原始带宽和IO限制"""
    # 恢复网络限制
    if original.get('ingress'):
        run_cmd(f"lxc config device set {container} eth0 limits.ingress={original['ingress']}")
    else:
        run_cmd(f"lxc config device unset {container} eth0 limits.ingress")
    
    if original.get('egress'):
        run_cmd(f"lxc config device set {container} eth0 limits.egress={original['egress']}")
    else:
        run_cmd(f"lxc config device unset {container} eth0 limits.egress")
    
    # 恢复 IO 限制
    if original.get('io_read'):
        run_cmd(f"lxc config device set {container} root limits.read={original['io_read']}")
    else:
        run_cmd(f"lxc config device unset {container} root limits.read")
    
    if original.get('io_write'):
        run_cmd(f"lxc config device set {container} root limits.write={original['io_write']}")
    else:
        run_cmd(f"lxc config device unset {container} root limits.write")
    
    logger.info(f"✓ 已恢复 {container} 原始带宽和IO限制")


def load_state():
    """加载状态"""
    try:
        with open(STATE_FILE, 'r') as f:
            return json.load(f)
    except:
        return {'limited': {}}


def save_state(state):
    """保存状态"""
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f, indent=2)


def check_all(limit_mbps, io_limit_mb, dry_run=False):
    """检查所有容器"""
    state = load_state()
    containers = get_containers()
    
    logger.info(f"=== 检查 {len(containers)} 个容器 ===")
    
    for container in containers:
        bt_procs = check_bt_process(container)
        is_limited = container in state['limited']
        
        if bt_procs:
            # 发现 BT 进程
            proc_names = ', '.join(bt_procs)
            
            if not is_limited:
                # 需要限速
                logger.warning(f"⚠ {container}: 发现 BT 进程 [{proc_names}]")
                
                if not dry_run:
                    # 保存原始限制
                    original = get_current_limit(container)
                    state['limited'][container] = {
                        'original': original,
                        'since': datetime.now().isoformat(),
                        'processes': bt_procs
                    }
                    # 限速 + 限 IO
                    set_limit(container, limit_mbps, io_limit_mb)
                    save_state(state)
                else:
                    logger.info(f"  [模拟] 将限速为 {limit_mbps}Mbps, IO={io_limit_mb}MB/s")
            else:
                logger.info(f"  {container}: BT 进程运行中 [{proc_names}]，已限速")
        else:
            # 没有 BT 进程
            if is_limited:
                # 需要恢复
                logger.info(f"✓ {container}: BT 进程已停止，恢复带宽")
                
                if not dry_run:
                    original = state['limited'][container].get('original', {})
                    restore_limit(container, original)
                    del state['limited'][container]
                    save_state(state)
                else:
                    logger.info(f"  [模拟] 将恢复原始带宽")
            else:
                logger.info(f"  {container}: 正常")
    
    # 显示当前限速状态
    if state['limited']:
        logger.info("--- 当前限速容器 ---")
        for c, info in state['limited'].items():
            since = info.get('since', 'unknown')
            logger.info(f"  {c}: 自 {since} 起限速")


def main():
    parser = argparse.ArgumentParser(description='qBittorrent 进程检测限速器')
    parser.add_argument('--limit', type=int, default=10,
                        help='限速带宽 Mbps（默认 10）')
    parser.add_argument('--io-limit', type=int, default=10,
                        help='限速IO MB/s（默认 10）')
    parser.add_argument('--interval', type=int, default=1800,
                        help='检查间隔秒数（默认 1800 = 30分钟）')
    parser.add_argument('--once', action='store_true',
                        help='只检查一次')
    parser.add_argument('--dry-run', action='store_true',
                        help='模拟运行，不实际限速')
    parser.add_argument('--status', action='store_true',
                        help='显示当前状态')
    
    args = parser.parse_args()
    
    if args.status:
        state = load_state()
        if state['limited']:
            print("当前限速容器:")
            for c, info in state['limited'].items():
                print(f"  {c}: {info}")
        else:
            print("没有容器被限速")
        return
    
    logger.info(f"qBittorrent 限速器启动")
    logger.info(f"  限速带宽: {args.limit} Mbps")
    logger.info(f"  限速IO: {args.io_limit} MB/s")
    logger.info(f"  检查间隔: {args.interval} 秒 ({args.interval//60} 分钟)")
    
    if args.once:
        check_all(args.limit, args.io_limit, args.dry_run)
    else:
        while True:
            try:
                check_all(args.limit, args.io_limit, args.dry_run)
            except Exception as e:
                logger.error(f"检查出错: {e}")
            
            logger.info(f"下次检查: {args.interval//60} 分钟后")
            time.sleep(args.interval)


if __name__ == '__main__':
    main()
