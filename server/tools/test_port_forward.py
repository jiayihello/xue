#!/usr/bin/env python3
"""
测试LXD端口转发功能
此脚本用于测试使用LXD proxy设备方式实现的端口转发功能
"""

import subprocess
import sys
import time
import random
import json
import os

# 测试参数
CONTAINER_NAME = "test-port-forward"
TEST_PORT_OUTSIDE = random.randint(20000, 30000)
TEST_PORT_INSIDE = 80
PROTOCOL = "tcp"

def run_command(cmd):
    """运行命令并返回输出"""
    print(f"执行: {cmd}")
    result = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if result.returncode != 0:
        print(f"错误: {result.stderr}")
    return result.stdout.strip(), result.returncode

def test_create_container():
    """创建测试容器"""
    print("1. 创建测试容器...")
    
    # 检查容器是否已存在
    output, _ = run_command(f"lxc list --format=json")
    containers = json.loads(output)
    for container in containers:
        if container.get('name') == CONTAINER_NAME:
            print(f"容器 {CONTAINER_NAME} 已存在，先删除")
            run_command(f"lxc delete -f {CONTAINER_NAME}")
            time.sleep(2)
    
    # 创建新容器
    _, rc = run_command(f"lxc launch images:debian/12 {CONTAINER_NAME}")
    if rc != 0:
        print("创建容器失败")
        sys.exit(1)
    
    # 等待容器启动
    print("等待容器启动...")
    time.sleep(5)
    
    # 安装nginx用于测试
    run_command(f"lxc exec {CONTAINER_NAME} -- apt update")
    run_command(f"lxc exec {CONTAINER_NAME} -- apt install -y nginx")
    print("容器创建成功并安装了nginx")

def test_add_port_forward():
    """测试添加端口转发"""
    print(f"\n2. 添加端口转发 {TEST_PORT_OUTSIDE} -> {TEST_PORT_INSIDE}...")
    
    # 添加端口转发
    device_name = f"nat-{PROTOCOL}-{TEST_PORT_OUTSIDE}"
    _, rc = run_command(f'lxc config device add {CONTAINER_NAME} {device_name} proxy listen={PROTOCOL}:0.0.0.0:{TEST_PORT_OUTSIDE} connect={PROTOCOL}:127.0.0.1:{TEST_PORT_INSIDE}')
    if rc != 0:
        print("添加端口转发失败")
        return False
    
    print("端口转发添加成功")
    return True

def test_port_connectivity():
    """测试端口连通性"""
    print(f"\n3. 测试端口 {TEST_PORT_OUTSIDE} 连通性...")
    
    # 获取主机IP
    host_ip, _ = run_command("hostname -I | awk '{print $1}'")
    
    # 测试连接
    print(f"尝试连接 http://{host_ip}:{TEST_PORT_OUTSIDE} ...")
    _, rc = run_command(f"curl -s -m 5 -o /dev/null -w '%{{http_code}}' http://127.0.0.1:{TEST_PORT_OUTSIDE}")
    
    if rc == 0:
        print(f"端口转发测试成功! 可以通过 http://{host_ip}:{TEST_PORT_OUTSIDE} 访问容器内的nginx服务")
        return True
    else:
        print("端口转发测试失败")
        return False

def test_remove_port_forward():
    """测试删除端口转发"""
    print(f"\n4. 删除端口转发...")
    
    device_name = f"nat-{PROTOCOL}-{TEST_PORT_OUTSIDE}"
    _, rc = run_command(f"lxc config device remove {CONTAINER_NAME} {device_name}")
    if rc != 0:
        print("删除端口转发失败")
        return False
    
    print("端口转发删除成功")
    return True

def cleanup():
    """清理测试环境"""
    print("\n5. 清理测试环境...")
    run_command(f"lxc delete -f {CONTAINER_NAME}")
    print("清理完成")

def main():
    """主测试流程"""
    print("===== LXD端口转发功能测试 =====")
    
    try:
        test_create_container()
        
        if test_add_port_forward():
            time.sleep(2)  # 等待端口转发生效
            port_test_result = test_port_connectivity()
            test_remove_port_forward()
        
        cleanup()
        
        # 输出测试结果
        print("\n===== 测试结果 =====")
        if port_test_result:
            print("✅ 端口转发功能测试通过!")
        else:
            print("❌ 端口转发功能测试失败!")
            
    except KeyboardInterrupt:
        print("\n测试被用户中断")
        cleanup()
    except Exception as e:
        print(f"\n测试过程中发生错误: {e}")
        cleanup()

if __name__ == "__main__":
    main() 