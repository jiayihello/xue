#!/usr/bin/env python3
"""
测试LXC容器连接状态
此脚本用于测试容器的网络连接和端口转发功能
"""

import subprocess
import sys
import json
import time
import logging

logging.basicConfig(level=logging.INFO,
                   format='%(asctime)s %(levelname)s: %(message)s',
                   datefmt='%Y-%m-%d %H:%M:%S')
logger = logging.getLogger('test_connectivity')

def run_command(cmd):
    """运行命令并返回输出"""
    logger.debug(f"执行: {cmd}")
    result = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE, 
                          stderr=subprocess.PIPE, text=True)
    return result.stdout.strip(), result.stderr.strip(), result.returncode

def test_lxd_connection():
    """测试LXD连接"""
    print("1. 测试LXD守护进程连接...")
    
    output, error, rc = run_command("lxc version")
    if rc == 0:
        print("✅ LXD守护进程连接正常")
        return True
    else:
        print(f"❌ LXD守护进程连接失败: {error}")
        return False

def list_containers():
    """列出所有容器"""
    print("\n2. 获取容器列表...")
    
    output, error, rc = run_command("lxc list --format=json")
    if rc != 0:
        print(f"❌ 获取容器列表失败: {error}")
        return []
    
    try:
        containers = json.loads(output)
        print(f"发现 {len(containers)} 个容器:")
        
        for container in containers:
            name = container.get('name')
            status = container.get('status')
            print(f"  - {name}: {status}")
        
        return containers
    except json.JSONDecodeError as e:
        print(f"❌ 解析容器列表失败: {e}")
        return []

def test_container_network(container_name):
    """测试单个容器的网络连接"""
    print(f"\n3. 测试容器 {container_name} 的网络连接...")
    
    # 检查容器状态
    output, error, rc = run_command(f"lxc info {container_name}")
    if rc != 0:
        print(f"❌ 无法获取容器 {container_name} 信息: {error}")
        return False
    
    if "Status: Running" not in output:
        print(f"⚠️  容器 {container_name} 未运行")
        return False
    
    # 测试内部网络连接
    tests = [
        ("ping本地回环", "ping -c 1 -W 3 127.0.0.1"),
        ("ping网关", "ping -c 1 -W 3 $(ip route | grep default | awk '{print $3}')"),
        ("ping外网DNS", "ping -c 1 -W 3 8.8.8.8"),
        ("DNS解析测试", "nslookup google.com")
    ]
    
    results = {}
    for test_name, cmd in tests:
        print(f"  测试 {test_name}...")
        output, error, rc = run_command(f"lxc exec {container_name} -- {cmd}")
        
        if rc == 0:
            print(f"    ✅ {test_name} 成功")
            results[test_name] = True
        else:
            print(f"    ❌ {test_name} 失败: {error}")
            results[test_name] = False
    
    return results

def test_port_forwards(container_name):
    """测试容器的端口转发"""
    print(f"\n4. 测试容器 {container_name} 的端口转发...")
    
    # 获取容器的proxy设备
    output, error, rc = run_command(f"lxc config show {container_name}")
    if rc != 0:
        print(f"❌ 无法获取容器 {container_name} 配置: {error}")
        return False
    
    # 查找proxy设备
    proxy_devices = []
    lines = output.split('\n')
    in_devices = False
    current_device = None
    
    for line in lines:
        if line.strip() == "devices:":
            in_devices = True
            continue
        
        if in_devices:
            if line.startswith('  ') and ':' in line and not line.startswith('    '):
                # 新设备
                current_device = line.strip().rstrip(':')
            elif line.startswith('    type: proxy'):
                if current_device:
                    proxy_devices.append(current_device)
    
    if not proxy_devices:
        print(f"  ℹ️  容器 {container_name} 没有配置端口转发")
        return True
    
    print(f"  发现 {len(proxy_devices)} 个端口转发设备:")
    for device in proxy_devices:
        print(f"    - {device}")
        
        # 获取设备详细信息
        device_output, _, _ = run_command(f"lxc config device show {container_name} {device}")
        if "listen:" in device_output and "connect:" in device_output:
            listen_line = [l for l in device_output.split('\n') if 'listen:' in l]
            connect_line = [l for l in device_output.split('\n') if 'connect:' in l]
            
            if listen_line and connect_line:
                listen_info = listen_line[0].split('listen:')[1].strip()
                connect_info = connect_line[0].split('connect:')[1].strip()
                print(f"      监听: {listen_info}")
                print(f"      转发到: {connect_info}")
    
    return True

def get_container_ip(container_name):
    """获取容器IP地址"""
    output, error, rc = run_command(f"lxc list {container_name} --format=json")
    if rc != 0:
        return None
    
    try:
        containers = json.loads(output)
        if containers:
            container = containers[0]
            state = container.get('state', {})
            network = state.get('network', {})
            
            for interface, info in network.items():
                if interface != 'lo':  # 跳过回环接口
                    addresses = info.get('addresses', [])
                    for addr in addresses:
                        if addr.get('family') == 'inet':
                            return addr.get('address')
        return None
    except:
        return None

def main():
    """主测试流程"""
    print("===== LXC容器连接测试 =====")

    # 1. 测试LXD连接
    if not test_lxd_connection():
        print("\n❌ LXD连接失败，请检查LXD服务状态")
        return False

    # 2. 获取容器列表
    containers = list_containers()
    if not containers:
        print("\n⚠️  没有发现任何容器")
        return True

    # 3. 测试每个运行中的容器
    running_containers = [c for c in containers if c.get('status') == 'Running']

    if not running_containers:
        print("\n⚠️  没有运行中的容器")
        return True

    print(f"\n开始测试 {len(running_containers)} 个运行中的容器...")

    all_results = {}
    for container in running_containers:
        container_name = container.get('name')

        # 获取容器IP
        container_ip = get_container_ip(container_name)
        if container_ip:
            print(f"\n容器 {container_name} IP: {container_ip}")

        # 测试网络连接
        network_results = test_container_network(container_name)

        # 测试端口转发
        port_forward_ok = test_port_forwards(container_name)

        all_results[container_name] = {
            'ip': container_ip,
            'network': network_results,
            'port_forwards': port_forward_ok
        }

    # 4. 输出总结
    print("\n===== 测试结果总结 =====")
    for container_name, results in all_results.items():
        print(f"\n容器: {container_name}")
        print(f"  IP地址: {results['ip'] or '未获取到'}")

        if isinstance(results['network'], dict):
            network_ok = all(results['network'].values())
            print(f"  网络连接: {'✅ 正常' if network_ok else '❌ 异常'}")

            for test_name, result in results['network'].items():
                status = '✅' if result else '❌'
                print(f"    {status} {test_name}")

        print(f"  端口转发: {'✅ 正常' if results['port_forwards'] else '❌ 异常'}")

    return True

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
