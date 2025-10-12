#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
流量精度验证脚本
对比LXD原始数据和流量管理系统数据的精确性
"""

import sys
import os
import json
import subprocess

# 添加当前目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lxc_manager import LXCManager
from flow_manager import FlowManager

def get_lxd_raw_data(container_name):
    """获取LXD的原始精确数据"""
    try:
        # 方法1: 使用lxc query API获取精确数据
        cmd = f"lxc query /1.0/containers/{container_name}/state"
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        
        if result.returncode == 0:
            data = json.loads(result.stdout)
            network = data.get('network', {})
            
            total_rx = 0
            total_tx = 0
            
            print("LXD API原始数据:")
            for nic_name, nic_data in network.items():
                if 'counters' in nic_data:
                    rx = nic_data['counters'].get('bytes_received', 0)
                    tx = nic_data['counters'].get('bytes_sent', 0)
                    print(f"  {nic_name}: RX={rx:,} TX={tx:,}")
                    total_rx += rx
                    total_tx += tx
            
            print(f"LXD API总计: RX={total_rx:,} TX={tx:,} Total={total_rx + total_tx:,}")
            return total_rx, total_tx, None
        else:
            return None, None, f"LXD API调用失败: {result.stderr}"
            
    except Exception as e:
        return None, None, f"获取LXD原始数据失败: {e}"

def get_python_lxd_data(container_name):
    """通过Python LXD客户端获取数据"""
    try:
        lxc_manager = LXCManager()
        container = lxc_manager._get_container_or_error(container_name)
        if not container:
            return None, None, "容器不存在"
        
        state = container.state()
        if not state.network:
            return None, None, "无网络数据"
        
        total_rx = 0
        total_tx = 0
        
        print("Python LXD客户端数据:")
        for nic_name, nic_data in state.network.items():
            if 'counters' in nic_data:
                rx = nic_data['counters'].get('bytes_received', 0)
                tx = nic_data['counters'].get('bytes_sent', 0)
                print(f"  {nic_name}: RX={rx:,} TX={tx:,}")
                total_rx += rx
                total_tx += tx
        
        print(f"Python LXD总计: RX={total_rx:,} TX={total_tx:,} Total={total_rx + total_tx:,}")
        return total_rx, total_tx, None
        
    except Exception as e:
        return None, None, f"Python LXD获取失败: {e}"

def get_flow_manager_data(container_name):
    """获取流量管理系统的数据"""
    try:
        flow_manager = FlowManager()
        flow_info = flow_manager.get_container_flow_info(container_name)
        if not flow_info:
            return None, None, "容器未注册"
        
        # 通过API获取当前流量（这会调用LXD）
        lxc_manager = LXCManager()
        container = lxc_manager._get_container_or_error(container_name)
        if not container:
            return None, None, "容器不存在"
        
        state = container.state()
        current_rx = 0
        current_tx = 0
        
        if state.network:
            for nic_name, nic_data in state.network.items():
                if 'counters' in nic_data:
                    current_rx += nic_data['counters'].get('bytes_received', 0)
                    current_tx += nic_data['counters'].get('bytes_sent', 0)
        
        # 计算使用量
        usage_gb = flow_manager.calculate_current_period_usage(container_name, current_rx, current_tx)
        
        print("流量管理系统数据:")
        print(f"  当前RX: {current_rx:,}")
        print(f"  当前TX: {current_tx:,}")
        print(f"  总计: {current_rx + current_tx:,}")
        print(f"  基准RX: {flow_info['baseline_bytes_received']:,}")
        print(f"  基准TX: {flow_info['baseline_bytes_sent']:,}")
        print(f"  计算使用量: {usage_gb:.3f} GB")
        
        return current_rx, current_tx, None
        
    except Exception as e:
        return None, None, f"流量管理系统获取失败: {e}"

def compare_data(container_name):
    """对比各种数据源"""
    print("=" * 60)
    print(f"流量数据精度对比 - 容器: {container_name}")
    print("=" * 60)
    
    # 获取各种数据源的数据
    print("\n1. 获取LXD API原始数据...")
    api_rx, api_tx, api_error = get_lxd_raw_data(container_name)
    
    print("\n2. 获取Python LXD客户端数据...")
    py_rx, py_tx, py_error = get_python_lxd_data(container_name)
    
    print("\n3. 获取流量管理系统数据...")
    fm_rx, fm_tx, fm_error = get_flow_manager_data(container_name)
    
    # 对比分析
    print("\n" + "=" * 60)
    print("数据对比分析")
    print("=" * 60)
    
    if api_error:
        print(f"❌ LXD API: {api_error}")
    else:
        print(f"✅ LXD API: RX={api_rx:,} TX={api_tx:,} Total={api_rx + api_tx:,}")
    
    if py_error:
        print(f"❌ Python LXD: {py_error}")
    else:
        print(f"✅ Python LXD: RX={py_rx:,} TX={py_tx:,} Total={py_rx + py_tx:,}")
    
    if fm_error:
        print(f"❌ 流量管理: {fm_error}")
    else:
        print(f"✅ 流量管理: RX={fm_rx:,} TX={fm_tx:,} Total={fm_rx + fm_tx:,}")
    
    # 一致性检查
    if not any([api_error, py_error, fm_error]):
        print(f"\n一致性检查:")
        
        # API vs Python LXD
        if api_rx == py_rx and api_tx == py_tx:
            print("✅ LXD API 与 Python LXD 数据完全一致")
        else:
            print(f"⚠️  LXD API 与 Python LXD 数据不一致:")
            print(f"   RX差异: {py_rx - api_rx:,}")
            print(f"   TX差异: {py_tx - api_tx:,}")
        
        # Python LXD vs 流量管理
        if py_rx == fm_rx and py_tx == fm_tx:
            print("✅ Python LXD 与 流量管理系统 数据完全一致")
        else:
            print(f"⚠️  Python LXD 与 流量管理系统 数据不一致:")
            print(f"   RX差异: {fm_rx - py_rx:,}")
            print(f"   TX差异: {fm_tx - py_tx:,}")
        
        # 总体一致性
        if api_rx == py_rx == fm_rx and api_tx == py_tx == fm_tx:
            print("🎉 所有数据源完全一致！")
        else:
            print("⚠️  存在数据不一致，需要进一步调查")

def main():
    if len(sys.argv) < 2:
        print("用法: python3 verify_flow_accuracy.py <容器名>")
        return
    
    container_name = sys.argv[1]
    compare_data(container_name)

if __name__ == "__main__":
    main()
