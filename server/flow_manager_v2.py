#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
流量管理器 V2 - 基于 iptables 增量累加
使用简化的3字段数据库表，准确统计容器流量
"""

import sqlite3
import logging
from datetime import date, datetime
from dateutil.relativedelta import relativedelta
from typing import Optional, Dict, List, Tuple
import os

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class FlowManagerV2:
    """流量管理器 V2"""
    
    def __init__(self, db_path: str = 'flow_management_v2.db'):
        """
        初始化流量管理器
        
        Args:
            db_path: 数据库文件路径
        """
        self.db_path = db_path
        self._initialize_database()
    
    def _initialize_database(self):
        """初始化数据库表"""
        with sqlite3.connect(self.db_path) as conn:
            # 🔥 启用 WAL 模式改善并发性能
            # WAL (Write-Ahead Logging) 允许读写并发，大幅提升多进程访问性能
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            
            # 创建新的简化表（如果不存在）
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS container_flow_v2 (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    hostname VARCHAR(255) NOT NULL UNIQUE,
                    created_date DATE NOT NULL,
                    
                    -- 核心字段（只需3个）
                    period_total_bytes BIGINT DEFAULT 0,      -- 周期累计流量
                    last_iptables_bytes BIGINT DEFAULT 0,     -- 上次 iptables 快照
                    next_reset_date DATE NOT NULL,            -- 下次重置日期
                    
                    -- 流量限制
                    flow_limit_gb INTEGER DEFAULT 0,          -- 流量限制（GB，0=无限制）
                    is_blocked INTEGER DEFAULT 0,             -- 是否已封禁
                    
                    -- 辅助字段
                    ipv4 VARCHAR(50),                         -- IPv4 地址（可选）
                    ipv6 VARCHAR(100),                        -- IPv6 地址（可选）
                    reset_count INTEGER DEFAULT 0,            -- 重置次数
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                
                -- 流量重置历史记录表
                CREATE TABLE IF NOT EXISTS flow_reset_history_v2 (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    hostname VARCHAR(255) NOT NULL,
                    reset_date DATE NOT NULL,
                    reset_type VARCHAR(20) NOT NULL,          -- 'scheduled', 'manual'
                    flow_used_gb REAL NOT NULL,               -- 重置时已用流量（GB）
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                
                -- 创建索引
                CREATE INDEX IF NOT EXISTS idx_hostname_v2 ON container_flow_v2(hostname);
                CREATE INDEX IF NOT EXISTS idx_next_reset_v2 ON container_flow_v2(next_reset_date);
                CREATE INDEX IF NOT EXISTS idx_reset_history_hostname ON flow_reset_history_v2(hostname);
            """)
            
            logger.info("数据库表初始化完成")
    
    def register_container(self, hostname: str, flow_limit_gb: int = 0,
                          ipv4: Optional[str] = None, ipv6: Optional[str] = None) -> bool:
        """
        注册容器到流量管理系统
        
        Args:
            hostname: 容器主机名
            flow_limit_gb: 流量限制（GB），0表示无限制
            ipv4: IPv4 地址
            ipv6: IPv6 地址
            
        Returns:
            是否成功
        """
        try:
            # ✅ 输入验证
            if not hostname or not hostname.strip():
                logger.error("主机名不能为空")
                return False
            
            # 验证主机名格式（允许字母、数字、连字符、下划线）
            if not all(c.isalnum() or c in '-_' for c in hostname):
                logger.error(f"主机名包含非法字符: {hostname}")
                return False
            
            # 验证流量限制
            if not isinstance(flow_limit_gb, int):
                logger.error(f"流量限制必须是整数: {flow_limit_gb}")
                return False
            
            if flow_limit_gb < 0:
                logger.error(f"流量限制不能为负数: {flow_limit_gb}")
                return False
            
            # 🔥 重要修复：先检查是否已存在，避免覆盖已有数据
            existing = self.get_container_usage(hostname)
            if existing:
                logger.warning(f"容器 {hostname} 已注册（已用: {existing['used_gb']:.2f}GB），跳过")
                return False
            
            created_date = date.today()
            next_reset_date = self._calculate_next_reset_date(created_date)
            
            with sqlite3.connect(self.db_path) as conn:
                # 🔥 修改为 INSERT（不是 INSERT OR REPLACE），防止意外覆盖
                conn.execute("""
                    INSERT INTO container_flow_v2
                    (hostname, created_date, period_total_bytes, last_iptables_bytes,
                     next_reset_date, flow_limit_gb, ipv4, ipv6, updated_at)
                    VALUES (?, ?, 0, 0, ?, ?, ?, ?, ?)
                """, (hostname, created_date, next_reset_date, flow_limit_gb,
                      ipv4, ipv6, datetime.now()))
            
            logger.info(f"✓ 容器 {hostname} 已注册，限制: {flow_limit_gb}GB，"
                       f"下次重置: {next_reset_date}")
            return True
            
        except sqlite3.IntegrityError:
            logger.error(f"容器 {hostname} 已存在于数据库，注册失败")
            return False
        except Exception as e:
            logger.error(f"注册容器 {hostname} 失败: {e}")
            return False
    
    def _calculate_next_reset_date(self, created_date: date) -> date:
        """
        计算下次重置日期（创建后一个月）
        
        Args:
            created_date: 创建日期
            
        Returns:
            下次重置日期
        """
        return created_date + relativedelta(months=1)
    
    def update_flow(self, hostname: str, current_iptables_bytes: int) -> bool:
        """
        更新容器流量（增量累加）
        
        Args:
            hostname: 容器主机名
            current_iptables_bytes: 当前 iptables 统计的字节数
            
        Returns:
            是否成功
        """
        try:
            # ✅ 输入验证
            if not hostname or not hostname.strip():
                logger.error("主机名不能为空")
                return False
            
            if not isinstance(current_iptables_bytes, int) or current_iptables_bytes < 0:
                logger.error(f"iptables 字节数无效: {current_iptables_bytes}")
                return False
            
            with sqlite3.connect(self.db_path) as conn:
                # 获取上次快照
                row = conn.execute("""
                    SELECT period_total_bytes, last_iptables_bytes
                    FROM container_flow_v2
                    WHERE hostname = ?
                """, (hostname,)).fetchone()
                
                if not row:
                    logger.warning(f"容器 {hostname} 未注册")
                    return False
                
                period_total, last_snapshot = row
                
                # 计算增量
                if current_iptables_bytes >= last_snapshot:
                    # 正常增长
                    increment = current_iptables_bytes - last_snapshot
                else:
                    # iptables 计数器归零了（宿主机重启/容器重启等）
                    # 使用当前值作为增量（这是新周期的开始）
                    increment = current_iptables_bytes
                    logger.info(f"容器 {hostname} iptables 计数器归零，"
                              f"当前值: {current_iptables_bytes}")
                
                # 更新数据库
                new_total = period_total + increment
                conn.execute("""
                    UPDATE container_flow_v2
                    SET period_total_bytes = ?,
                        last_iptables_bytes = ?,
                        updated_at = ?
                    WHERE hostname = ?
                """, (new_total, current_iptables_bytes, datetime.now(), hostname))
                
                if increment > 0:
                    logger.debug(f"容器 {hostname} 流量更新: +{increment/1024/1024:.2f}MB, "
                               f"总计: {new_total/1024/1024/1024:.2f}GB")
                
                return True
                
        except Exception as e:
            logger.error(f"更新容器 {hostname} 流量失败: {e}")
            return False
    
    def get_container_usage(self, hostname: str) -> Optional[Dict]:
        """
        获取容器流量使用情况
        
        Args:
            hostname: 容器主机名
            
        Returns:
            流量使用信息字典，或 None
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                row = conn.execute("""
                    SELECT hostname, period_total_bytes, flow_limit_gb,
                           is_blocked, next_reset_date, created_date
                    FROM container_flow_v2
                    WHERE hostname = ?
                """, (hostname,)).fetchone()
                
                if not row:
                    return None
                
                total_gb = row['period_total_bytes'] / (1024 ** 3)
                limit_gb = row['flow_limit_gb']
                
                return {
                    'hostname': row['hostname'],
                    'used_gb': round(total_gb, 2),
                    'limit_gb': limit_gb,
                    'is_blocked': bool(row['is_blocked']),
                    'usage_percent': round(total_gb / limit_gb * 100, 1) if limit_gb > 0 else 0,
                    'next_reset_date': row['next_reset_date'],
                    'created_date': row['created_date']
                }
                
        except Exception as e:
            logger.error(f"获取容器 {hostname} 使用情况失败: {e}")
            return None
    
    def list_all_containers(self) -> List[Dict]:
        """
        列出所有容器的流量使用情况
        
        Returns:
            容器列表
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute("""
                    SELECT hostname, period_total_bytes, flow_limit_gb,
                           is_blocked, next_reset_date
                    FROM container_flow_v2
                    ORDER BY period_total_bytes DESC
                """).fetchall()
                
                result = []
                for row in rows:
                    total_gb = row['period_total_bytes'] / (1024 ** 3)
                    limit_gb = row['flow_limit_gb']
                    
                    result.append({
                        'hostname': row['hostname'],
                        'used_gb': round(total_gb, 2),
                        'limit_gb': limit_gb,
                        'is_blocked': bool(row['is_blocked']),
                        'usage_percent': round(total_gb / limit_gb * 100, 1) if limit_gb > 0 else 0,
                        'next_reset_date': row['next_reset_date']
                    })
                
                return result
                
        except Exception as e:
            logger.error(f"列出容器失败: {e}")
            return []
    
    def _run_command(self, args: list, use_sudo: bool = False) -> Tuple[bool, str]:
        """执行命令"""
        import subprocess
        cmd = ['sudo'] + args if use_sudo else args
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=15
            )
            if result.returncode != 0:
                return False, result.stderr.strip()
            return True, result.stdout.strip()
        except subprocess.TimeoutExpired:
            return False, "命令超时"
        except Exception as e:
            return False, str(e)
    
    def _get_iptables_rule_numbers(self, hostname: str, use_ipv6: bool = False) -> List[int]:
        """
        获取容器在 LXD_FLOW_ACCOUNTING 链中的规则行号
        
        Args:
            hostname: 容器名
            use_ipv6: 是否查询 ip6tables
        
        Returns:
            规则行号列表
        """
        import re
        rule_numbers = []
        cmd = 'ip6tables' if use_ipv6 else 'iptables'
        
        success, output = self._run_command([
            cmd, '-L', 'LXD_FLOW_ACCOUNTING', '-v', '-n', '-x', '--line-numbers'
        ])
        
        if not success:
            # 链不存在不算错误
            if 'No chain' not in output and 'does not exist' not in output:
                logger.warning(f"获取 {cmd} 规则失败: {output}")
            return rule_numbers
        
        # 解析输出，查找包含 hostname 的规则
        for line in output.split('\n'):
            if hostname.lower() in line.lower():
                match = re.match(r'^(\d+)\s+', line)
                if match:
                    rule_numbers.append(int(match.group(1)))
        
        return rule_numbers
    
    def _reset_iptables_counters(self, hostname: str) -> Tuple[int, int]:
        """
        清零容器的 iptables 和 ip6tables 计数器
        
        Args:
            hostname: 容器名
            
        Returns:
            (ipv4清零数, ipv6清零数)
        """
        ipv4_count = 0
        ipv6_count = 0
        
        # 清零 IPv4 (iptables)
        rule_numbers = self._get_iptables_rule_numbers(hostname, use_ipv6=False)
        for rule_num in rule_numbers:
            success, error = self._run_command([
                'iptables', '-Z', 'LXD_FLOW_ACCOUNTING', str(rule_num)
            ])
            if success:
                ipv4_count += 1
            else:
                logger.warning(f"清零 iptables 规则 {rule_num} 失败: {error}")
        
        # 清零 IPv6 (ip6tables)
        rule_numbers = self._get_iptables_rule_numbers(hostname, use_ipv6=True)
        for rule_num in rule_numbers:
            success, error = self._run_command([
                'ip6tables', '-Z', 'LXD_FLOW_ACCOUNTING', str(rule_num)
            ])
            if success:
                ipv6_count += 1
            else:
                logger.warning(f"清零 ip6tables 规则 {rule_num} 失败: {error}")
        
        if ipv4_count > 0 or ipv6_count > 0:
            logger.info(f"✓ 容器 {hostname} 已清零计数器 (iptables: {ipv4_count}, ip6tables: {ipv6_count})")
        else:
            logger.info(f"容器 {hostname} 没有找到 iptables/ip6tables 规则")
        
        return ipv4_count, ipv6_count

    def reset_container_flow(self, hostname: str, reset_type: str = 'manual') -> bool:
        """
        重置容器流量
        
        Args:
            hostname: 容器主机名
            reset_type: 重置类型（'scheduled' 或 'manual'）
            
        Returns:
            是否成功
        """
        try:
            # 🔥 第一步：清零 iptables 和 ip6tables 计数器
            self._reset_iptables_counters(hostname)
            
            with sqlite3.connect(self.db_path) as conn:
                # 获取当前流量
                row = conn.execute("""
                    SELECT period_total_bytes, created_date, next_reset_date
                    FROM container_flow_v2
                    WHERE hostname = ?
                """, (hostname,)).fetchone()
                
                if not row:
                    logger.warning(f"容器 {hostname} 未注册")
                    return False
                
                old_total_bytes, created_date, old_next_reset = row
                old_usage_gb = old_total_bytes / (1024 ** 3)
                
                # 计算新的重置日期
                if reset_type == 'scheduled':
                    # 按月递增
                    old_reset_date = datetime.strptime(old_next_reset, '%Y-%m-%d').date()
                    new_reset_date = old_reset_date + relativedelta(months=1)
                else:
                    # 手动重置，从今天开始计算
                    new_reset_date = self._calculate_next_reset_date(date.today())
                
                # 🔥 重要：iptables 计数器已清零，所以 last_iptables_bytes 也设为 0
                conn.execute("""
                    UPDATE container_flow_v2
                    SET period_total_bytes = 0,
                        last_iptables_bytes = 0,
                        next_reset_date = ?,
                        is_blocked = 0,
                        reset_count = reset_count + 1,
                        updated_at = ?
                    WHERE hostname = ?
                """, (new_reset_date, datetime.now(), hostname))
                
                # 记录历史
                conn.execute("""
                    INSERT INTO flow_reset_history_v2
                    (hostname, reset_date, reset_type, flow_used_gb)
                    VALUES (?, ?, ?, ?)
                """, (hostname, date.today(), reset_type, old_usage_gb))
                
                logger.info(f"✓ 容器 {hostname} 流量已完整重置: "
                          f"{old_usage_gb:.2f}GB → 0GB，下次重置: {new_reset_date}")
                return True
                
        except Exception as e:
            logger.error(f"重置容器 {hostname} 流量失败: {e}")
            return False
    
    def check_and_get_overdue_containers(self) -> List[str]:
        """
        检查并获取需要重置的容器列表
        
        Returns:
            需要重置的容器主机名列表
        """
        try:
            today = date.today()
            with sqlite3.connect(self.db_path) as conn:
                rows = conn.execute("""
                    SELECT hostname
                    FROM container_flow_v2
                    WHERE next_reset_date <= ?
                """, (today,)).fetchall()
                
                return [row[0] for row in rows]
                
        except Exception as e:
            logger.error(f"检查逾期容器失败: {e}")
            return []
    
    def set_container_blocked(self, hostname: str, blocked: bool) -> bool:
        """
        设置容器封禁状态
        
        Args:
            hostname: 容器主机名
            blocked: 是否封禁
            
        Returns:
            是否成功
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    UPDATE container_flow_v2
                    SET is_blocked = ?,
                        updated_at = ?
                    WHERE hostname = ?
                """, (1 if blocked else 0, datetime.now(), hostname))
                
                logger.info(f"容器 {hostname} 封禁状态: {blocked}")
                return True
                
        except Exception as e:
            logger.error(f"设置容器 {hostname} 封禁状态失败: {e}")
            return False
    
    def update_container_limit(self, hostname: str, new_limit_gb: int) -> bool:
        """
        更新容器流量限制
        
        Args:
            hostname: 容器主机名
            new_limit_gb: 新的流量限制（GB）
            
        Returns:
            是否成功
        """
        try:
            # ✅ 输入验证
            if not isinstance(new_limit_gb, int) or new_limit_gb < 0:
                logger.error(f"流量限制必须是非负整数: {new_limit_gb}")
                return False
            
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    UPDATE container_flow_v2
                    SET flow_limit_gb = ?,
                        updated_at = ?
                    WHERE hostname = ?
                """, (new_limit_gb, datetime.now(), hostname))
                
                logger.info(f"容器 {hostname} 流量限制已更新: {new_limit_gb}GB")
                return True
                
        except Exception as e:
            logger.error(f"更新容器 {hostname} 流量限制失败: {e}")
            return False
    
    def set_next_reset_date(self, hostname: str, next_reset: date) -> bool:
        """
        设置容器的下次重置日期
        
        Args:
            hostname: 容器主机名
            next_reset: 下次重置日期
            
        Returns:
            是否成功
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    UPDATE container_flow_v2
                    SET next_reset_date = ?,
                        updated_at = ?
                    WHERE hostname = ?
                """, (next_reset, datetime.now(), hostname))
                
                logger.info(f"容器 {hostname} 下次重置日期已更新: {next_reset}")
                return True
                
        except Exception as e:
            logger.error(f"设置容器 {hostname} 重置日期失败: {e}")
            return False
    
    def unregister_container(self, hostname: str) -> bool:
        """
        注销容器（删除记录）
        
        Args:
            hostname: 容器主机名
            
        Returns:
            是否成功
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    DELETE FROM container_flow_v2
                    WHERE hostname = ?
                """, (hostname,))
                
                logger.info(f"容器 {hostname} 已注销")
                return True
                
        except Exception as e:
            logger.error(f"注销容器 {hostname} 失败: {e}")
            return False


# 命令行工具
if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='流量管理器 V2')
    parser.add_argument('action', choices=['register', 'list', 'reset', 'usage', 'info',
                                           'set-limit', 'set-reset'],
                       help='操作类型')
    parser.add_argument('--hostname', help='容器主机名')
    parser.add_argument('--limit', type=int, default=250, help='流量限制（GB）')
    parser.add_argument('--ipv4', help='IPv4 地址')
    parser.add_argument('--ipv6', help='IPv6 地址')
    parser.add_argument('--reset-date', help='重置日期 (YYYY-MM-DD)')
    parser.add_argument('hostname_arg', nargs='?', help='容器主机名（位置参数）')
    parser.add_argument('value_arg', nargs='?', help='值（用于 set-limit 的GB数或 set-reset 的日期）')
    
    args = parser.parse_args()
    
    manager = FlowManagerV2()
    
    if args.action == 'register':
        if not args.hostname:
            print("错误: 需要指定 --hostname")
            exit(1)
        manager.register_container(args.hostname, args.limit, args.ipv4, args.ipv6)
    
    elif args.action == 'list':
        containers = manager.list_all_containers()
        print(f"\n{'主机名':<20} {'已用(GB)':<12} {'限制(GB)':<12} {'使用率':<10} {'状态':<8} {'下次重置'}")
        print("-" * 90)
        for c in containers:
            status = '已封禁' if c['is_blocked'] else '正常'
            print(f"{c['hostname']:<20} {c['used_gb']:<12.2f} {c['limit_gb']:<12} "
                  f"{c['usage_percent']:<10.1f}% {status:<8} {c['next_reset_date']}")
    
    elif args.action == 'reset':
        if not args.hostname:
            print("错误: 需要指定 --hostname")
            exit(1)
        manager.reset_container_flow(args.hostname, 'manual')
    
    elif args.action == 'usage':
        if not args.hostname:
            print("错误: 需要指定 --hostname")
            exit(1)
        info = manager.get_container_usage(args.hostname)
        if info:
            print(f"\n容器: {info['hostname']}")
            print(f"已用流量: {info['used_gb']:.2f} GB")
            print(f"流量限制: {info['limit_gb']} GB")
            print(f"使用率: {info['usage_percent']:.1f}%")
            print(f"状态: {'已封禁' if info['is_blocked'] else '正常'}")
            print(f"下次重置: {info['next_reset_date']}")
        else:
            print(f"容器 {args.hostname} 未注册")
    
    elif args.action == 'info':
        hostname = args.hostname or args.hostname_arg
        if not hostname:
            print("错误: 需要指定容器主机名")
            print("用法: python3 flow_manager_v2.py info <hostname>")
            exit(1)
        info = manager.get_container_usage(hostname)
        if info:
            print(f"\n容器: {info['hostname']}")
            print(f"已用流量: {info['used_gb']:.2f} GB")
            print(f"流量限制: {info['limit_gb']} GB")
            print(f"使用率: {info['usage_percent']:.1f}%")
            print(f"封禁状态: {'已封禁' if info['is_blocked'] else '正常'}")
            print(f"下次重置: {info['next_reset_date']}")
        else:
            print(f"容器 {hostname} 未注册")
            exit(1)
    
    elif args.action == 'set-limit':
        hostname = args.hostname or args.hostname_arg
        limit_value = args.value_arg if args.value_arg else args.limit
        if not hostname:
            print("错误: 需要指定容器主机名和流量限制")
            print("用法: python3 flow_manager_v2.py set-limit <hostname> <GB>")
            print("示例: python3 flow_manager_v2.py set-limit test001 100")
            exit(1)
        try:
            limit_gb = int(limit_value)
            if manager.update_container_limit(hostname, limit_gb):
                print(f"✓ 容器 {hostname} 流量限制已设置为 {limit_gb} GB")
            else:
                print(f"✗ 设置失败")
                exit(1)
        except (ValueError, TypeError):
            print(f"错误: 流量限制必须是整数")
            exit(1)
    
    elif args.action == 'set-reset':
        hostname = args.hostname or args.hostname_arg
        reset_date_str = args.value_arg or args.reset_date
        if not hostname or not reset_date_str:
            print("错误: 需要指定容器主机名和重置日期")
            print("用法: python3 flow_manager_v2.py set-reset <hostname> <YYYY-MM-DD>")
            print("示例: python3 flow_manager_v2.py set-reset test001 2025-12-01")
            exit(1)
        try:
            from datetime import datetime
            reset_date_obj = datetime.strptime(reset_date_str, '%Y-%m-%d').date()
            if manager.set_next_reset_date(hostname, reset_date_obj):
                print(f"✓ 容器 {hostname} 重置日期已设置为 {reset_date_str}")
            else:
                print(f"✗ 设置失败")
                exit(1)
        except ValueError:
            print(f"错误: 日期格式不正确，应为 YYYY-MM-DD")
            exit(1)

