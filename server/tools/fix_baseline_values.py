#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
修复流量管理基准值脚本
用于修复因容器创建时基准值设置过高导致的流量统计不准确问题
"""

import sys
import os
import sqlite3
from datetime import datetime

# 添加当前目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flow_manager import FlowManager
from lxc_manager import LXCManager

def get_container_real_usage(container_name):
    """获取容器的真实流量使用情况"""
    try:
        lxc_manager = LXCManager()
        container = lxc_manager._get_container_or_error(container_name)
        if not container:
            return None, None, f"容器 {container_name} 不存在"
        
        state = container.state()
        if not state.network:
            return None, None, "容器无网络统计信息"
        
        total_received = 0
        total_sent = 0
        for nic_name, nic_data in state.network.items():
            if 'counters' in nic_data:
                total_received += nic_data['counters'].get('bytes_received', 0)
                total_sent += nic_data['counters'].get('bytes_sent', 0)
        
        return total_received, total_sent, None
        
    except Exception as e:
        return None, None, f"获取容器流量失败: {e}"

def analyze_baseline_issue(container_name):
    """分析基准值问题"""
    print(f"=== 分析容器 {container_name} 的基准值问题 ===")
    
    # 获取流量管理信息
    flow_manager = FlowManager()
    flow_info = flow_manager.get_container_flow_info(container_name)
    if not flow_info:
        print(f"❌ 容器 {container_name} 未在流量管理系统中注册")
        return False
    
    # 获取当前LXD流量
    current_received, current_sent, error = get_container_real_usage(container_name)
    if error:
        print(f"❌ {error}")
        return False
    
    # 分析数据
    baseline_received = flow_info['baseline_bytes_received']
    baseline_sent = flow_info['baseline_bytes_sent']
    baseline_total = baseline_received + baseline_sent
    
    current_total = current_received + current_sent
    calculated_usage = max(0, current_total - baseline_total)
    
    print(f"当前LXD流量统计:")
    print(f"  接收: {current_received:,} 字节 ({current_received/1024/1024:.2f} MB)")
    print(f"  发送: {current_sent:,} 字节 ({current_sent/1024/1024:.2f} MB)")
    print(f"  总计: {current_total:,} 字节 ({current_total/1024/1024:.2f} MB)")
    
    print(f"\n当前基准值:")
    print(f"  基准接收: {baseline_received:,} 字节 ({baseline_received/1024/1024:.2f} MB)")
    print(f"  基准发送: {baseline_sent:,} 字节 ({baseline_sent/1024/1024:.2f} MB)")
    print(f"  基准总计: {baseline_total:,} 字节 ({baseline_total/1024/1024:.2f} MB)")
    
    print(f"\n计算的使用量:")
    print(f"  {calculated_usage:,} 字节 ({calculated_usage/1024/1024:.2f} MB = {calculated_usage/1024/1024/1024:.3f} GB)")
    
    # 判断是否有问题
    baseline_percentage = (baseline_total / current_total) * 100 if current_total > 0 else 0
    print(f"\n基准值占当前总流量的 {baseline_percentage:.1f}%")
    
    if baseline_percentage > 50:
        print("⚠️  基准值过高！建议修复")
        return True
    elif baseline_percentage > 20:
        print("⚠️  基准值较高，可能需要修复")
        return True
    else:
        print("✅ 基准值正常")
        return False

def fix_baseline_option1_reset(container_name):
    """修复方案1：重置流量（将当前流量作为新基准值）"""
    print(f"\n=== 修复方案1：重置容器 {container_name} 流量 ===")
    
    current_received, current_sent, error = get_container_real_usage(container_name)
    if error:
        print(f"❌ {error}")
        return False
    
    flow_manager = FlowManager()
    if flow_manager.reset_container_flow(container_name, current_received, current_sent, 'manual'):
        print("✅ 流量重置成功")
        print("⚠️  注意：这会将当前所有流量作为新的基准值，从现在开始重新计算")
        return True
    else:
        print("❌ 流量重置失败")
        return False

def fix_baseline_option2_zero(container_name):
    """修复方案2：将基准值设为0（保留所有历史流量）"""
    print(f"\n=== 修复方案2：将容器 {container_name} 基准值设为0 ===")
    
    try:
        flow_manager = FlowManager()
        if flow_manager._update_container_baseline(container_name, 0, 0):
            print("✅ 基准值已设为0")
            print("✅ 现在将统计容器的全部流量使用量")
            return True
        else:
            print("❌ 基准值更新失败")
            return False
    except Exception as e:
        print(f"❌ 更新基准值异常: {e}")
        return False

def main():
    """主函数"""
    if len(sys.argv) < 2:
        print("用法:")
        print("  python3 fix_baseline_values.py <容器名> [操作]")
        print("")
        print("操作选项:")
        print("  analyze  - 分析基准值问题（默认）")
        print("  reset    - 重置流量（将当前流量作为新基准值）")
        print("  zero     - 将基准值设为0（统计全部流量）")
        print("")
        print("示例:")
        print("  python3 fix_baseline_values.py ser862250185144 analyze")
        print("  python3 fix_baseline_values.py ser862250185144 zero")
        return
    
    container_name = sys.argv[1]
    operation = sys.argv[2] if len(sys.argv) > 2 else 'analyze'
    
    print("=" * 60)
    print("流量管理基准值修复工具")
    print("=" * 60)
    
    if operation == 'analyze':
        has_issue = analyze_baseline_issue(container_name)
        if has_issue:
            print("\n建议的修复方案:")
            print("1. 重置流量: python3 fix_baseline_values.py", container_name, "reset")
            print("2. 基准值归零: python3 fix_baseline_values.py", container_name, "zero")
            print("\n推荐使用方案2（基准值归零），这样可以统计容器的全部流量使用量")
    
    elif operation == 'reset':
        if fix_baseline_option1_reset(container_name):
            print("\n修复完成！请重新查看流量统计:")
            print(f"lxd-flow-manager info {container_name}")
    
    elif operation == 'zero':
        if fix_baseline_option2_zero(container_name):
            print("\n修复完成！请重新查看流量统计:")
            print(f"lxd-flow-manager info {container_name}")
    
    else:
        print(f"❌ 未知操作: {operation}")
        return
    
    print("\n" + "=" * 60)

if __name__ == "__main__":
    main()
