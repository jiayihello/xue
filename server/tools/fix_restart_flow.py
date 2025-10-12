#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
修复重启后流量丢失的脚本
手动恢复重启前的流量统计
"""

import sys
import os
import sqlite3
from datetime import datetime

# 添加当前目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flow_manager import FlowManager
from lxc_manager import LXCManager

def fix_restart_flow_loss(container_name, lost_mb):
    """修复重启导致的流量丢失"""
    print(f"=== 修复容器 {container_name} 重启后的流量丢失 ===")
    
    try:
        flow_manager = FlowManager()
        lxc_manager = LXCManager()
        
        # 获取当前流量信息
        flow_info = flow_manager.get_container_flow_info(container_name)
        if not flow_info:
            print(f"❌ 容器 {container_name} 未在流量管理系统中注册")
            return False
        
        # 获取当前LXD流量
        container = lxc_manager._get_container_or_error(container_name)
        if not container:
            print(f"❌ 容器 {container_name} 不存在")
            return False
        
        state = container.state()
        current_received = 0
        current_sent = 0
        
        if state.network:
            for nic_name, nic_data in state.network.items():
                if 'counters' in nic_data:
                    current_received += nic_data['counters'].get('bytes_received', 0)
                    current_sent += nic_data['counters'].get('bytes_sent', 0)
        
        print(f"当前状态:")
        print(f"  当前LXD流量: {(current_received + current_sent) / 1024 / 1024:.2f} MB")
        print(f"  基准值: {(flow_info['baseline_bytes_received'] + flow_info['baseline_bytes_sent']) / 1024 / 1024:.2f} MB")
        print(f"  累计值: {(flow_info.get('accumulated_bytes_received', 0) + flow_info.get('accumulated_bytes_sent', 0)) / 1024 / 1024:.2f} MB")
        
        # 计算需要添加的累计量
        lost_bytes = lost_mb * 1024 * 1024
        add_received = lost_bytes // 2  # 假设接收和发送各占一半
        add_sent = lost_bytes - add_received
        
        new_accumulated_received = flow_info.get('accumulated_bytes_received', 0) + add_received
        new_accumulated_sent = flow_info.get('accumulated_bytes_sent', 0) + add_sent
        
        print(f"\n修复操作:")
        print(f"  添加丢失流量: {lost_mb} MB")
        print(f"  新累计接收: {new_accumulated_received / 1024 / 1024:.2f} MB")
        print(f"  新累计发送: {new_accumulated_sent / 1024 / 1024:.2f} MB")
        
        # 更新数据库
        with sqlite3.connect(flow_manager.db_path) as conn:
            # 确保有累计字段
            cursor = conn.execute("PRAGMA table_info(container_flow_management)")
            columns = [column[1] for column in cursor.fetchall()]
            
            if 'accumulated_bytes_received' not in columns:
                conn.execute("ALTER TABLE container_flow_management ADD COLUMN accumulated_bytes_received BIGINT DEFAULT 0")
                conn.execute("ALTER TABLE container_flow_management ADD COLUMN accumulated_bytes_sent BIGINT DEFAULT 0")
            
            # 更新累计值
            conn.execute("""
                UPDATE container_flow_management 
                SET accumulated_bytes_received = ?, 
                    accumulated_bytes_sent = ?,
                    updated_at = ?
                WHERE hostname = ?
            """, (new_accumulated_received, new_accumulated_sent, datetime.now(), container_name))
            
            print("✅ 数据库更新成功")
        
        # 验证修复结果
        new_usage = flow_manager.calculate_current_period_usage(container_name, current_received, current_sent)
        print(f"\n修复后:")
        print(f"  计算的使用量: {new_usage:.3f} GB")
        print(f"  预期使用量: {(lost_bytes + current_received + current_sent) / 1024 / 1024 / 1024:.3f} GB")
        
        return True
        
    except Exception as e:
        print(f"❌ 修复失败: {e}")
        return False

def main():
    if len(sys.argv) < 3:
        print("用法: python3 fix_restart_flow.py <容器名> <丢失的流量MB>")
        print("示例: python3 fix_restart_flow.py ser792815117176 207")
        return
    
    container_name = sys.argv[1]
    lost_mb = float(sys.argv[2])
    
    print("=" * 60)
    print("重启流量丢失修复工具")
    print("=" * 60)
    
    if fix_restart_flow_loss(container_name, lost_mb):
        print("\n✅ 修复完成！请验证:")
        print(f"lxd-flow-manager info {container_name}")
    else:
        print("\n❌ 修复失败")

if __name__ == "__main__":
    main()
