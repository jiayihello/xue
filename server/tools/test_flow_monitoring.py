#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
流量监测测试脚本
用于验证流量统计和监测功能是否正常工作
"""

import sys
import os
import time
import json
import subprocess
from datetime import datetime

# 添加当前目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flow_manager import FlowManager
from lxc_manager import LXCManager
from config_handler import app_config

def run_command(cmd):
    """执行命令并返回结果"""
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
        return result.returncode == 0, result.stdout.strip(), result.stderr.strip()
    except Exception as e:
        return False, "", str(e)

def get_container_traffic_from_lxd(container_name):
    """直接从LXD获取容器流量统计"""
    print(f"\n=== 直接从LXD获取容器 {container_name} 流量统计 ===")
    
    # 方法1: 使用lxc info命令
    success, output, error = run_command(f"lxc info {container_name}")
    if success:
        print("LXC Info 输出:")
        lines = output.split('\n')
        in_network_section = False
        for line in lines:
            if 'Network usage:' in line:
                in_network_section = True
            elif in_network_section and (line.strip() == '' or not line.startswith('  ')):
                in_network_section = False
            
            if in_network_section or 'bytes received' in line or 'bytes sent' in line:
                print(f"  {line}")
    else:
        print(f"❌ 获取LXC信息失败: {error}")
    
    # 方法2: 使用Python LXD客户端
    try:
        lxc_manager = LXCManager()
        container = lxc_manager._get_container_or_error(container_name)
        if container:
            state = container.state()
            print(f"\n通过Python LXD客户端获取:")
            print(f"  容器状态: {container.status}")
            
            if state.network:
                total_received = 0
                total_sent = 0
                for nic_name, nic_data in state.network.items():
                    print(f"  网卡 {nic_name}:")
                    if 'counters' in nic_data:
                        received = nic_data['counters'].get('bytes_received', 0)
                        sent = nic_data['counters'].get('bytes_sent', 0)
                        print(f"    接收: {received:,} 字节 ({received/1024/1024:.2f} MB)")
                        print(f"    发送: {sent:,} 字节 ({sent/1024/1024:.2f} MB)")
                        total_received += received
                        total_sent += sent
                    else:
                        print(f"    无流量统计数据")
                
                print(f"  总计:")
                print(f"    总接收: {total_received:,} 字节 ({total_received/1024/1024:.2f} MB)")
                print(f"    总发送: {total_sent:,} 字节 ({total_sent/1024/1024:.2f} MB)")
                print(f"    总流量: {(total_received + total_sent):,} 字节 ({(total_received + total_sent)/1024/1024:.2f} MB)")
                
                return total_received, total_sent
            else:
                print("  ❌ 无网络统计信息")
                return 0, 0
        else:
            print(f"  ❌ 容器 {container_name} 不存在")
            return 0, 0
    except Exception as e:
        print(f"  ❌ 通过Python客户端获取失败: {e}")
        return 0, 0

def test_flow_calculation(container_name):
    """测试流量计算功能"""
    print(f"\n=== 测试容器 {container_name} 流量计算 ===")
    
    try:
        flow_manager = FlowManager()
        
        # 获取流量管理信息
        flow_info = flow_manager.get_container_flow_info(container_name)
        if not flow_info:
            print(f"❌ 容器 {container_name} 未在流量管理系统中注册")
            return
        
        print("流量管理信息:")
        print(f"  基准接收: {flow_info['baseline_bytes_received']:,} 字节")
        print(f"  基准发送: {flow_info['baseline_bytes_sent']:,} 字节")
        print(f"  累计接收: {flow_info.get('accumulated_bytes_received', 0):,} 字节")
        print(f"  累计发送: {flow_info.get('accumulated_bytes_sent', 0):,} 字节")
        
        # 获取当前LXD流量
        current_received, current_sent = get_container_traffic_from_lxd(container_name)
        
        # 计算当前周期使用量
        current_usage = flow_manager.calculate_current_period_usage(
            container_name, current_received, current_sent
        )
        
        print(f"\n流量计算结果:")
        print(f"  当前LXD接收: {current_received:,} 字节")
        print(f"  当前LXD发送: {current_sent:,} 字节")
        print(f"  计算的周期使用量: {current_usage:.3f} GB")
        
        # 手动计算验证
        manual_received = current_received - flow_info['baseline_bytes_received']
        manual_sent = current_sent - flow_info['baseline_bytes_sent']
        manual_accumulated = flow_info.get('accumulated_bytes_received', 0) + flow_info.get('accumulated_bytes_sent', 0)
        manual_total = manual_received + manual_sent + manual_accumulated
        manual_gb = max(0, manual_total) / (1024**3)
        
        print(f"\n手动计算验证:")
        print(f"  周期接收: {current_received} - {flow_info['baseline_bytes_received']} = {manual_received:,}")
        print(f"  周期发送: {current_sent} - {flow_info['baseline_bytes_sent']} = {manual_sent:,}")
        print(f"  累计流量: {manual_accumulated:,}")
        print(f"  总计: {manual_total:,} 字节")
        print(f"  转换GB: {manual_gb:.3f} GB")
        
        # 允许更大的误差范围，因为容器在持续产生流量
        if abs(current_usage - manual_gb) < 0.01:  # 10MB误差范围
            print("✅ 流量计算正确")
        elif abs(current_usage - manual_gb) < 0.05:  # 50MB误差范围
            print("⚠️  流量计算基本正确（可能有时间差导致的小误差）")
        else:
            print("❌ 流量计算有误")
            
    except Exception as e:
        print(f"❌ 测试流量计算失败: {e}")

def generate_traffic(container_name, size_mb=10):
    """在容器中生成测试流量"""
    print(f"\n=== 在容器 {container_name} 中生成 {size_mb}MB 测试流量 ===")
    
    try:
        # 在容器中下载文件生成流量
        cmd = f"lxc exec {container_name} -- wget -O /tmp/test_file http://httpbin.org/bytes/{size_mb * 1024 * 1024}"
        success, output, error = run_command(cmd)
        
        if success:
            print(f"✅ 成功生成约 {size_mb}MB 下载流量")
        else:
            print(f"❌ 生成流量失败: {error}")
            # 尝试其他方法
            cmd2 = f"lxc exec {container_name} -- dd if=/dev/zero of=/tmp/test_file bs=1M count={size_mb}"
            success2, output2, error2 = run_command(cmd2)
            if success2:
                print(f"✅ 使用dd命令生成了 {size_mb}MB 文件")
            else:
                print(f"❌ dd命令也失败: {error2}")
                
    except Exception as e:
        print(f"❌ 生成流量异常: {e}")

def main():
    """主函数"""
    if len(sys.argv) < 2:
        print("用法: python3 test_flow_monitoring.py <容器名> [生成流量MB]")
        print("示例: python3 test_flow_monitoring.py ser862250185144 5")
        return
    
    container_name = sys.argv[1]
    traffic_mb = int(sys.argv[2]) if len(sys.argv) > 2 else 0
    
    print("=" * 60)
    print("流量监测测试脚本")
    print("=" * 60)
    
    # 1. 获取初始流量
    print(f"\n1. 获取容器 {container_name} 初始流量")
    initial_received, initial_sent = get_container_traffic_from_lxd(container_name)
    
    # 2. 测试流量计算
    test_flow_calculation(container_name)
    
    # 3. 生成测试流量（如果指定）
    if traffic_mb > 0:
        generate_traffic(container_name, traffic_mb)
        
        # 等待一下
        print("\n等待3秒...")
        time.sleep(3)
        
        # 4. 再次检查流量
        print(f"\n4. 生成流量后再次检查")
        final_received, final_sent = get_container_traffic_from_lxd(container_name)
        
        print(f"\n流量变化:")
        print(f"  接收变化: {final_received - initial_received:,} 字节")
        print(f"  发送变化: {final_sent - initial_sent:,} 字节")
        print(f"  总变化: {(final_received + final_sent) - (initial_received + initial_sent):,} 字节")
        
        # 5. 再次测试流量计算
        test_flow_calculation(container_name)
    
    print("\n" + "=" * 60)
    print("测试完成")
    print("=" * 60)

if __name__ == "__main__":
    main()
