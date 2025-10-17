#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
流量限制执行器
当容器流量超过限制时自动断网，恢复时自动解除限制
"""

import sys
import os
import sqlite3
import subprocess
from datetime import datetime

# 添加当前目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flow_manager import FlowManager
from lxc_manager import LXCManager
import logging

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('flow_limit_enforcer.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class FlowLimitEnforcer:
    def __init__(self):
        self.flow_manager = FlowManager()
        self.lxc_manager = LXCManager()
        
    def run_command(self, cmd):
        """执行命令"""
        try:
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
            return result.returncode == 0, result.stdout.strip(), result.stderr.strip()
        except Exception as e:
            return False, "", str(e)
    
    def block_container_network(self, container_name, container_ip, container_ipv6_list=None):
        """阻断容器网络访问（同时覆盖 IPv4 与 IPv6）。"""
        try:
            # 阻断容器的出站流量（IPv4）
            block_rules_v4 = [
                f"iptables -I FORWARD -s {container_ip} -j DROP",
                f"iptables -I FORWARD -d {container_ip} -j DROP",
                # 保留SSH访问（22端口）以便管理
                f"iptables -I FORWARD -s {container_ip} -p tcp --dport 22 -j ACCEPT",
                f"iptables -I FORWARD -d {container_ip} -p tcp --sport 22 -j ACCEPT"
            ]
            for rule in block_rules_v4:
                success, output, error = self.run_command(rule)
                if not success:
                    logger.error(f"执行IPv4阻断规则失败: {rule}, 错误: {error}")
                    return False

            # 阻断容器的出站流量（IPv6，可选）
            container_ipv6_list = container_ipv6_list or []
            for ip6 in container_ipv6_list:
                ip6cidr = f"{ip6}/128" if "/" not in str(ip6) else str(ip6)
                for rule in [
                    f"ip6tables -I FORWARD -s {ip6cidr} -j DROP",
                    f"ip6tables -I FORWARD -d {ip6cidr} -j DROP",
                    f"ip6tables -I FORWARD -s {ip6cidr} -p tcp --dport 22 -j ACCEPT",
                    f"ip6tables -I FORWARD -d {ip6cidr} -p tcp --sport 22 -j ACCEPT",
                ]:
                    success, output, error = self.run_command(rule)
                    if not success:
                        logger.error(f"执行IPv6阻断规则失败: {rule}, 错误: {error}")

            # 记录阻断状态
            self._update_block_status(container_name, True)
            logger.warning(f"容器 {container_name} (IPv4: {container_ip}) 已被阻断网络访问")
            return True

        except Exception as e:
            logger.error(f"阻断容器 {container_name} 网络失败: {e}")
            return False

    def unblock_container_network(self, container_name, container_ip, container_ipv6_list=None):
        """解除容器网络阻断（同时覆盖 IPv4 与 IPv6）。"""
        try:
            # 移除IPv4阻断规则
            unblock_rules_v4 = [
                f"iptables -D FORWARD -s {container_ip} -j DROP",
                f"iptables -D FORWARD -d {container_ip} -j DROP",
                f"iptables -D FORWARD -s {container_ip} -p tcp --dport 22 -j ACCEPT",
                f"iptables -D FORWARD -d {container_ip} -p tcp --sport 22 -j ACCEPT"
            ]
            for rule in unblock_rules_v4:
                self.run_command(rule)

            # 移除IPv6阻断规则（可选）
            container_ipv6_list = container_ipv6_list or []
            for ip6 in container_ipv6_list:
                ip6cidr = f"{ip6}/128" if "/" not in str(ip6) else str(ip6)
                for rule in [
                    f"ip6tables -D FORWARD -s {ip6cidr} -j DROP",
                    f"ip6tables -D FORWARD -d {ip6cidr} -j DROP",
                    f"ip6tables -D FORWARD -s {ip6cidr} -p tcp --dport 22 -j ACCEPT",
                    f"ip6tables -D FORWARD -d {ip6cidr} -p tcp --sport 22 -j ACCEPT",
                ]:
                    self.run_command(rule)

            # 记录解除状态
            self._update_block_status(container_name, False)
            logger.info(f"容器 {container_name} (IPv4: {container_ip}) 网络访问已恢复")
            return True

        except Exception as e:
            logger.error(f"解除容器 {container_name} 网络阻断失败: {e}")
            return False

    def _ensure_database_fields(self):
        """确保数据库有必要的字段"""
        try:
            with sqlite3.connect(self.flow_manager.db_path) as conn:
                cursor = conn.execute("PRAGMA table_info(container_flow_management)")
                columns = [column[1] for column in cursor.fetchall()]

                if 'is_blocked' not in columns:
                    conn.execute("ALTER TABLE container_flow_management ADD COLUMN is_blocked BOOLEAN DEFAULT 0")
                    logger.info("添加字段: is_blocked")

                if 'blocked_at' not in columns:
                    conn.execute("ALTER TABLE container_flow_management ADD COLUMN blocked_at DATETIME")
                    logger.info("添加字段: blocked_at")

                if 'last_check_at' not in columns:
                    conn.execute("ALTER TABLE container_flow_management ADD COLUMN last_check_at DATETIME")
                    logger.info("添加字段: last_check_at")

                if 'block_count' not in columns:
                    conn.execute("ALTER TABLE container_flow_management ADD COLUMN block_count INTEGER DEFAULT 0")
                    logger.info("添加字段: block_count")

        except Exception as e:
            logger.error(f"确保数据库字段失败: {e}")

    def _update_block_status(self, container_name, is_blocked):
        """更新容器阻断状态"""
        try:
            with sqlite3.connect(self.flow_manager.db_path) as conn:
                cursor = conn.execute("PRAGMA table_info(container_flow_management)")
                columns = [column[1] for column in cursor.fetchall()]
                
                if 'is_blocked' not in columns:
                    conn.execute("ALTER TABLE container_flow_management ADD COLUMN is_blocked BOOLEAN DEFAULT 0")
                    conn.execute("ALTER TABLE container_flow_management ADD COLUMN blocked_at DATETIME")
                
                if is_blocked:
                    conn.execute("""
                        UPDATE container_flow_management 
                        SET is_blocked = 1, blocked_at = ?, updated_at = ?
                        WHERE hostname = ?
                    """, (datetime.now(), datetime.now(), container_name))
                else:
                    conn.execute("""
                        UPDATE container_flow_management 
                        SET is_blocked = 0, blocked_at = NULL, updated_at = ?
                        WHERE hostname = ?
                    """, (datetime.now(), container_name))
                    
        except Exception as e:
            logger.error(f"更新容器 {container_name} 阻断状态失败: {e}")
    
    def check_and_enforce_limits(self):
        """检查并执行流量限制"""
        logger.info("开始检查容器流量限制...")

        try:
            self._ensure_database_fields()

            with sqlite3.connect(self.flow_manager.db_path) as conn:
                cursor = conn.execute("""
                    SELECT hostname, flow_limit_gb, COALESCE(is_blocked, 0) as is_blocked
                    FROM container_flow_management
                    WHERE flow_limit_gb > 0
                """)
                containers = cursor.fetchall()
            
            for hostname, limit_gb, is_blocked in containers:
                try:
                    container = self.lxc_manager._get_container_or_error(hostname)
                    if not container:
                        logger.warning(f"容器 {hostname} 不存在，跳过检查")
                        continue
                    
                    container_info_response = self.lxc_manager.get_container_info(hostname)
                    if container_info_response.get('code') != 200:
                        logger.warning(f"容器 {hostname} 信息获取失败，跳过检查")
                        continue

                    container_info = container_info_response.get('data', {})
                    container_ip = container_info.get('IP')
                    container_ipv6_list = container_info.get('IPv6List') or []

                    if not container_ip or container_ip == 'N/A':
                        logger.warning(f"容器 {hostname} 无IPv4地址，跳过")
                        container_ip = None

                    state = container.state()
                    current_received = 0
                    current_sent = 0

                    if state.network:
                        for nic_name, nic_data in state.network.items():
                            if nic_name == 'lo' or nic_data.get('type') == 'loopback':
                                continue
                            if 'counters' in nic_data:
                                current_received += nic_data['counters'].get('bytes_received', 0)
                                current_sent += nic_data['counters'].get('bytes_sent', 0)

                    current_usage_gb = self.flow_manager.calculate_current_period_usage(
                        hostname, current_received, current_sent
                    )

                    if current_usage_gb >= limit_gb:
                        if not is_blocked:
                            logger.warning(f"容器 {hostname} 流量超限: {current_usage_gb:.2f}GB / {limit_gb}GB")
                            if container_ip:
                                self.block_container_network(hostname, container_ip, container_ipv6_list)
                        else:
                            logger.debug(f"容器 {hostname} 已被阻断: {current_usage_gb:.2f}GB / {limit_gb}GB")
                    else:
                        if is_blocked:
                            logger.info(f"容器 {hostname} 流量恢复正常: {current_usage_gb:.2f}GB / {limit_gb}GB")
                            if container_ip:
                                self.unblock_container_network(hostname, container_ip, container_ipv6_list)
                        else:
                            logger.debug(f"容器 {hostname} 流量正常: {current_usage_gb:.2f}GB / {limit_gb}GB")

                except Exception as e:
                    logger.error(f"检查容器 {hostname} 流量限制失败: {e}")
                    continue
            
            logger.info("流量限制检查完成")
            
        except Exception as e:
            logger.error(f"检查流量限制失败: {e}")
    
    def get_blocked_containers(self):
        """获取被阻断的容器列表"""
        try:
            with sqlite3.connect(self.flow_manager.db_path) as conn:
                cursor = conn.execute("""
                    SELECT hostname, flow_limit_gb, blocked_at
                    FROM container_flow_management 
                    WHERE is_blocked = 1
                    ORDER BY blocked_at DESC
                """)
                return cursor.fetchall()
        except Exception as e:
            logger.error(f"获取被阻断容器列表失败: {e}")
            return []
    
    def manually_unblock_container(self, container_name):
        """手动解除容器阻断"""
        try:
            container_info_response = self.lxc_manager.get_container_info(container_name)
            if container_info_response.get('code') != 200:
                print(f"❌ 容器 {container_name} 信息获取失败")
                return False

            container_info = container_info_response.get('data', {})
            container_ip = container_info.get('IP') or '0.0.0.0/32'
            container_ipv6_list = container_info.get('IPv6List') or []

            if self.unblock_container_network(container_name, container_ip, container_ipv6_list):
                print(f"✅ 容器 {container_name} 网络访问已手动恢复")
                return True
            else:
                print(f"❌ 解除容器 {container_name} 阻断失败")
                return False

        except Exception as e:
            print(f"❌ 手动解除容器 {container_name} 阻断异常: {e}")
            return False

def main():
    """主函数"""
    if len(sys.argv) < 2:
        print("流量限制执行器")
        print()
        print("用法:")
        print("  python3 flow_limit_enforcer.py check        # 检查并执行流量限制")
        print("  python3 flow_limit_enforcer.py status       # 查看被阻断的容器")
        print("  python3 flow_limit_enforcer.py unblock <容器名>  # 手动解除容器阻断")
        print()
        print("示例:")
        print("  python3 flow_limit_enforcer.py check")
        print("  python3 flow_limit_enforcer.py status")
        print("  python3 flow_limit_enforcer.py unblock ser123456789")
        return
    
    enforcer = FlowLimitEnforcer()
    command = sys.argv[1]
    
    if command == "check":
        enforcer.check_and_enforce_limits()
    
    elif command == "status":
        print("=== 被阻断的容器列表 ===")
        blocked_containers = enforcer.get_blocked_containers()
        
        if not blocked_containers:
            print("没有被阻断的容器")
        else:
            for hostname, limit_gb, blocked_at in blocked_containers:
                print(f"  {hostname}: 限制 {limit_gb}GB, 阻断时间 {blocked_at}")
    
    elif command == "unblock":
        if len(sys.argv) < 3:
            print("请指定要解除阻断的容器名")
            return
        
        container_name = sys.argv[2]
        enforcer.manually_unblock_container(container_name)
    
    else:
        print(f"❌ 未知命令: {command}")

if __name__ == "__main__":
    main()
