#!/usr/bin/env python3
"""
批量修复容器带宽限制脚本
修复zjmf-lxd-server中由于错误的单位转换导致的带宽限制问题
原问题：使用了125000作为Mbps到bit/s的转换系数，正确应该是1000000
"""

import subprocess
import json
import sys
import os

def run_cmd(cmd):
    """执行命令并返回结果"""
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
        return result.returncode == 0, result.stdout.strip(), result.stderr.strip()
    except Exception as e:
        return False, "", str(e)

def get_containers():
    """获取所有容器列表"""
    success, output, error = run_cmd("lxc list --format json")
    if not success:
        print(f"❌ 获取容器列表失败: {error}")
        return []
    
    try:
        containers = json.loads(output)
        return [c['name'] for c in containers if c.get('name')]
    except:
        print("❌ 解析容器列表失败")
        return []

def get_network_limits(container):
    """获取容器的网络限制配置"""
    success, output, error = run_cmd(f"lxc config show {container}")
    if not success:
        return None, None
    
    ingress = None
    egress = None
    
    for line in output.split('\n'):
        line = line.strip()
        if 'limits.ingress:' in line:
            ingress = line.split(':', 1)[1].strip().strip('"\'')
        elif 'limits.egress:' in line:
            egress = line.split(':', 1)[1].strip().strip('"\'')
    
    return ingress, egress

def fix_container(container):
    """修复单个容器的带宽限制"""
    print(f"\n检查容器: {container}")
    
    ingress, egress = get_network_limits(container)
    
    if not ingress or not egress:
        print(f"  ⚠️  跳过 - 未找到网络限制配置")
        return False
    
    try:
        ingress_val = int(ingress)
        egress_val = int(egress)
    except:
        print(f"  ⚠️  跳过 - 无法解析带宽值: ingress={ingress}, egress={egress}")
        return False
    
    # 检查是否是125000的倍数（错误配置的特征）
    if ingress_val % 125000 == 0 and egress_val % 125000 == 0:
        # 计算原始Mbps值
        original_mbps_in = ingress_val // 125000
        original_mbps_out = egress_val // 125000
        
        # 计算正确的bit/s值
        correct_ingress = original_mbps_in * 1000000
        correct_egress = original_mbps_out * 1000000
        
        print(f"  🔧 需要修复:")
        print(f"     当前: {original_mbps_in}Mbps -> {ingress_val} bit/s (错误)")
        print(f"     修复: {original_mbps_in}Mbps -> {correct_ingress} bit/s (正确)")
        
        # 执行修复
        cmd1 = f"lxc config device set {container} eth0 limits.ingress={correct_ingress}"
        cmd2 = f"lxc config device set {container} eth0 limits.egress={correct_egress}"
        
        success1, _, error1 = run_cmd(cmd1)
        success2, _, error2 = run_cmd(cmd2)
        
        if success1 and success2:
            print(f"  ✅ 修复成功")
            return True
        else:
            print(f"  ❌ 修复失败: {error1} {error2}")
            return False
    else:
        print(f"  ✅ 配置正常 - ingress={ingress_val}, egress={egress_val}")
        return False

def main():
    print("=" * 60)
    print("zjmf-lxd-server 容器带宽限制批量修复工具")
    print("=" * 60)
    print("此工具将修复由于错误单位转换导致的带宽限制问题")
    print("错误: 1 Mbps -> 125,000 bit/s")
    print("正确: 1 Mbps -> 1,000,000 bit/s")
    print()
    
    # 检查是否有root权限
    if os.geteuid() != 0:
        print("❌ 请使用root权限运行此脚本")
        print("sudo python3 fix_bandwidth_limits.py")
        sys.exit(1)
    
    # 获取容器列表
    containers = get_containers()
    if not containers:
        print("❌ 未找到任何容器")
        sys.exit(1)
    
    print(f"找到 {len(containers)} 个容器: {', '.join(containers)}")
    print()
    
    # 确认执行
    response = input("是否开始检查和修复？(y/N): ").strip().lower()
    if response != 'y':
        print("操作已取消")
        sys.exit(0)
    
    print("\n开始处理...")
    print("=" * 60)
    
    fixed_count = 0
    total_count = len(containers)
    
    for container in containers:
        if fix_container(container):
            fixed_count += 1
    
    print("\n" + "=" * 60)
    print("处理完成!")
    print(f"总容器数: {total_count}")
    print(f"修复数量: {fixed_count}")
    print(f"跳过数量: {total_count - fixed_count}")
    
    if fixed_count > 0:
        print("\n建议重启已修复的容器以确保配置生效:")
        print("lxc restart <容器名>")
        print("\n或批量重启所有容器:")
        print("lxc list --format csv -c n | xargs -I {} lxc restart {}")

if __name__ == "__main__":
    main()
