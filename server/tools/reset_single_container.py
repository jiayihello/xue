#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
重置单个容器的流量使用量
"""

import sys
import os

# 添加父目录(server/)到Python路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flow_manager import FlowManager
from lxc_manager import LXCManager

def reset_single_container(hostname):
    """重置单个容器的流量"""
    try:
        flow_mgr = FlowManager()
        lxc_mgr = LXCManager()
        
        # 检查容器是否存在
        container = lxc_mgr._get_container_or_error(hostname)
        if not container:
            print(f"❌ 容器 {hostname} 不存在")
            return False
        
        # 获取容器当前流量统计
        state = container.state()
        rx = tx = 0
        
        if state.network:
            for if_name, nic in state.network.items():
                # 排除环回接口
                if if_name == 'lo' or nic.get('type') == 'loopback':
                    continue
                cnt = nic.get('counters', {})
                rx += int(cnt.get('bytes_received', 0))
                tx += int(cnt.get('bytes_sent', 0))
        
        # 计算当前使用量
        current_usage = flow_mgr.calculate_current_period_usage(hostname, rx, tx)
        print(f"📊 容器 {hostname} 当前使用流量: {current_usage} GB")
        
        # 执行重置
        if flow_mgr.reset_container_flow(hostname, rx, tx, reset_type='manual'):
            print(f"✅ 容器 {hostname} 流量已重置为 0")
            print(f"   重置前使用: {current_usage} GB")
            return True
        else:
            print(f"❌ 容器 {hostname} 流量重置失败")
            return False
            
    except Exception as e:
        print(f"❌ 错误: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python3 reset_single_container.py <容器名>")
        print("示例: python3 reset_single_container.py XueiV6498")
        sys.exit(1)
    
    hostname = sys.argv[1]
    success = reset_single_container(hostname)
    sys.exit(0 if success else 1)

