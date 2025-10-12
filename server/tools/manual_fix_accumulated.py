#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
手动修复累计流量值
这是一次性修复脚本，修复当前已经检测到重启但累计值没有正确更新的容器
"""

import sys
import os
import sqlite3
from datetime import datetime

# 添加当前目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flow_manager import FlowManager

def fix_accumulated_values(container_name):
    """修复累计值"""
    print(f"=== 修复容器 {container_name} 的累计流量值 ===")
    
    try:
        flow_manager = FlowManager()
        
        # 获取当前信息
        flow_info = flow_manager.get_container_flow_info(container_name)
        if not flow_info:
            print(f"❌ 容器 {container_name} 未注册")
            return False
        
        last_max_received = flow_info.get('last_max_bytes_received', 0)
        last_max_sent = flow_info.get('last_max_bytes_sent', 0)
        current_accumulated_received = flow_info.get('accumulated_bytes_received', 0)
        current_accumulated_sent = flow_info.get('accumulated_bytes_sent', 0)
        
        print(f"当前状态:")
        print(f"  历史最大接收: {last_max_received:,} 字节")
        print(f"  历史最大发送: {last_max_sent:,} 字节")
        print(f"  当前累计接收: {current_accumulated_received:,} 字节")
        print(f"  当前累计发送: {current_accumulated_sent:,} 字节")
        
        # 如果历史最大值不为0但累计值为0，说明需要修复
        if (last_max_received > 0 or last_max_sent > 0) and \
           (current_accumulated_received == 0 and current_accumulated_sent == 0):
            
            print(f"\n检测到需要修复：历史最大值不为0但累计值为0")
            
            # 将历史最大值设为累计值
            new_accumulated_received = last_max_received
            new_accumulated_sent = last_max_sent
            
            with sqlite3.connect(flow_manager.db_path) as conn:
                conn.execute("""
                    UPDATE container_flow_management 
                    SET accumulated_bytes_received = ?,
                        accumulated_bytes_sent = ?,
                        updated_at = ?
                    WHERE hostname = ?
                """, (new_accumulated_received, new_accumulated_sent, datetime.now(), container_name))
            
            print(f"✅ 修复完成:")
            print(f"  新累计接收: {new_accumulated_received:,} 字节")
            print(f"  新累计发送: {new_accumulated_sent:,} 字节")
            print(f"  总累计: {(new_accumulated_received + new_accumulated_sent) / 1024 / 1024:.2f} MB")
            
            return True
        else:
            print("✅ 累计值正常，无需修复")
            return True
            
    except Exception as e:
        print(f"❌ 修复失败: {e}")
        return False

def main():
    if len(sys.argv) < 2:
        print("用法: python3 manual_fix_accumulated.py <容器名>")
        return
    
    container_name = sys.argv[1]
    
    print("=" * 60)
    print("累计流量值修复工具")
    print("=" * 60)
    
    if fix_accumulated_values(container_name):
        print("\n请验证修复结果:")
        print(f"lxd-flow-manager info {container_name}")

if __name__ == "__main__":
    main()
