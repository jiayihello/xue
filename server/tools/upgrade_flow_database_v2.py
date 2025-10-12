#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
流量管理数据库升级脚本 v2
添加流量限制执行器所需的字段
"""

import sys
import os
import sqlite3
from datetime import datetime

# 添加当前目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flow_manager import FlowManager

def upgrade_database():
    """升级数据库结构"""
    print("=== 升级流量管理数据库 ===")
    
    try:
        flow_manager = FlowManager()
        db_path = flow_manager.db_path
        
        print(f"数据库路径: {db_path}")
        
        with sqlite3.connect(db_path) as conn:
            # 检查当前表结构
            cursor = conn.execute("PRAGMA table_info(container_flow_management)")
            columns = [column[1] for column in cursor.fetchall()]
            
            print(f"当前字段: {', '.join(columns)}")
            
            # 添加流量限制执行器所需的字段
            new_fields = []
            
            if 'is_blocked' not in columns:
                conn.execute("ALTER TABLE container_flow_management ADD COLUMN is_blocked BOOLEAN DEFAULT 0")
                new_fields.append('is_blocked')
                print("✅ 添加字段: is_blocked")
            
            if 'blocked_at' not in columns:
                conn.execute("ALTER TABLE container_flow_management ADD COLUMN blocked_at DATETIME")
                new_fields.append('blocked_at')
                print("✅ 添加字段: blocked_at")
            
            if 'last_check_at' not in columns:
                conn.execute("ALTER TABLE container_flow_management ADD COLUMN last_check_at DATETIME")
                new_fields.append('last_check_at')
                print("✅ 添加字段: last_check_at")
            
            if 'block_count' not in columns:
                conn.execute("ALTER TABLE container_flow_management ADD COLUMN block_count INTEGER DEFAULT 0")
                new_fields.append('block_count')
                print("✅ 添加字段: block_count")
            
            # 确保已有字段存在
            if 'accumulated_bytes_received' not in columns:
                conn.execute("ALTER TABLE container_flow_management ADD COLUMN accumulated_bytes_received BIGINT DEFAULT 0")
                new_fields.append('accumulated_bytes_received')
                print("✅ 添加字段: accumulated_bytes_received")
            
            if 'accumulated_bytes_sent' not in columns:
                conn.execute("ALTER TABLE container_flow_management ADD COLUMN accumulated_bytes_sent BIGINT DEFAULT 0")
                new_fields.append('accumulated_bytes_sent')
                print("✅ 添加字段: accumulated_bytes_sent")
            
            if 'last_max_bytes_received' not in columns:
                conn.execute("ALTER TABLE container_flow_management ADD COLUMN last_max_bytes_received BIGINT DEFAULT 0")
                new_fields.append('last_max_bytes_received')
                print("✅ 添加字段: last_max_bytes_received")
            
            if 'last_max_bytes_sent' not in columns:
                conn.execute("ALTER TABLE container_flow_management ADD COLUMN last_max_bytes_sent BIGINT DEFAULT 0")
                new_fields.append('last_max_bytes_sent')
                print("✅ 添加字段: last_max_bytes_sent")
            
            if new_fields:
                print(f"\n✅ 数据库升级完成，添加了 {len(new_fields)} 个新字段")
            else:
                print("\n✅ 数据库已是最新版本，无需升级")
            
            # 验证表结构
            cursor = conn.execute("PRAGMA table_info(container_flow_management)")
            updated_columns = [column[1] for column in cursor.fetchall()]
            
            print(f"\n更新后字段: {', '.join(updated_columns)}")
            
            # 显示当前数据
            cursor = conn.execute("SELECT COUNT(*) FROM container_flow_management")
            count = cursor.fetchone()[0]
            print(f"当前注册容器数量: {count}")
            
            if count > 0:
                cursor = conn.execute("""
                    SELECT hostname, flow_limit_gb, 
                           COALESCE(is_blocked, 0) as is_blocked,
                           COALESCE(block_count, 0) as block_count
                    FROM container_flow_management 
                    ORDER BY hostname
                """)
                
                print("\n当前容器状态:")
                for hostname, limit_gb, is_blocked, block_count in cursor.fetchall():
                    status = "🔴 已阻断" if is_blocked else "🟢 正常"
                    print(f"  {hostname}: {limit_gb}GB {status} (阻断次数: {block_count})")
            
        return True
        
    except Exception as e:
        print(f"❌ 数据库升级失败: {e}")
        return False

def test_flow_limit_enforcer():
    """测试流量限制执行器"""
    print("\n=== 测试流量限制执行器 ===")
    
    try:
        # 导入并测试
        from flow_limit_enforcer import FlowLimitEnforcer
        
        enforcer = FlowLimitEnforcer()
        
        # 测试检查功能
        print("测试流量限制检查功能...")
        enforcer.check_and_enforce_limits()
        
        # 测试状态查询
        print("测试被阻断容器查询...")
        blocked_containers = enforcer.get_blocked_containers()
        
        if blocked_containers:
            print("当前被阻断的容器:")
            for hostname, limit_gb, blocked_at in blocked_containers:
                print(f"  {hostname}: 限制 {limit_gb}GB, 阻断时间 {blocked_at}")
        else:
            print("✅ 当前没有被阻断的容器")
        
        print("✅ 流量限制执行器测试通过")
        return True
        
    except Exception as e:
        print(f"❌ 流量限制执行器测试失败: {e}")
        return False

def main():
    """主函数"""
    print("流量管理数据库升级工具 v2")
    print("=" * 50)
    
    # 升级数据库
    if not upgrade_database():
        print("❌ 数据库升级失败，退出")
        return
    
    # 测试功能
    if not test_flow_limit_enforcer():
        print("❌ 功能测试失败，请检查配置")
        return
    
    print("\n" + "=" * 50)
    print("🎉 升级完成！")
    print("\n现在可以正常使用流量限制功能:")
    print("  lxd-flow-limit check        # 检查流量限制")
    print("  lxd-flow-limit status       # 查看被阻断容器")
    print("  lxd-flow-limit timer-status # 查看定时器状态")

if __name__ == "__main__":
    main()
