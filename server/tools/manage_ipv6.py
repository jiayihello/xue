#!/usr/bin/env python3
"""
IPv6 地址管理工具
支持：查看、手动分配、释放 IPv6 地址
"""

import sys
import os

# 添加父目录(server/)到Python路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ipv6_manager import allocate, get_allocated, list_allocations, release
from lxc_manager import LXCManager
from config_handler import app_config
from pylxd import Client as LXDClient
import subprocess
import logging

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)


def show_current_allocations():
    """显示当前所有IPv6分配"""
    allocations = list_allocations()
    
    if not allocations:
        print("\n[!] 当前没有已分配的 IPv6 地址\n")
        return
    
    print("\n" + "="*70)
    print("  当前 IPv6 地址分配情况")
    print("="*70)
    print(f"{'容器名':<30} {'IPv6 地址':<40}")
    print("-"*70)
    
    for hostname, ipv6 in sorted(allocations.items()):
        # 检查容器是否存在
        try:
            client = LXDClient()
            container = client.containers.get(hostname)
            status = "✓ 运行中" if container.status == "Running" else f"  {container.status}"
        except:
            status = "✗ 不存在"
        
        print(f"{hostname:<30} {ipv6:<40} {status}")
    
    print("="*70)
    print(f"总计: {len(allocations)} 个地址已分配\n")


def show_address_pool():
    """显示地址池状态"""
    pool = app_config.ipv6_address_pool
    allocations = list_allocations()
    used_addrs = set(allocations.values())
    
    print("\n" + "="*70)
    print("  IPv6 地址池状态")
    print("="*70)
    
    if pool:
        print(f"{'地址':<40} {'状态':<20} {'容器名':<20}")
        print("-"*70)
        
        for addr in pool:
            if addr in used_addrs:
                # 查找使用该地址的容器
                hostname = [h for h, a in allocations.items() if a == addr][0]
                print(f"{addr:<40} {'已占用':<20} {hostname:<20}")
            else:
                print(f"{addr:<40} {'可用':<20} {'-':<20}")
        
        used_count = sum(1 for addr in pool if addr in used_addrs)
        print("="*70)
        print(f"总计: {len(pool)} 个地址，已使用 {used_count} 个，剩余 {len(pool) - used_count} 个\n")
    else:
        print("未配置 IPV6_ADDRESS_POOL")
        print("将从 IPV6_PREFIX 自动分配: " + (app_config.ipv6_prefix or "未配置"))
        print("="*70 + "\n")


def assign_ipv6_to_container(hostname, custom_ipv6=None):
    """为容器分配IPv6地址"""
    
    # 检查容器是否存在
    try:
        client = LXDClient()
        container = client.containers.get(hostname)
    except Exception as e:
        logger.error(f"[✗] 容器 {hostname} 不存在: {e}")
        return False
    
    # 检查是否已分配
    existing = get_allocated(hostname)
    if existing:
        logger.warning(f"[!] 容器 {hostname} 已分配 IPv6: {existing}")
        response = input("是否要更改地址？[y/N]: ").strip().lower()
        if response != 'y':
            return False
        # 释放旧地址
        release(hostname)
    
    # 分配新地址
    ipv6_addr = allocate(hostname, custom_ipv6)
    if not ipv6_addr:
        logger.error(f"[✗] 为 {hostname} 分配 IPv6 失败")
        return False
    
    logger.info(f"[✓] 已为 {hostname} 分配 IPv6: {ipv6_addr}")
    
    # 添加到容器
    try:
        parent_if = app_config.ipv6_interface or app_config.main_interface
        
        # 移除旧的 eth0v6 设备（如果存在）
        if 'eth0v6' in container.devices:
            del container.devices['eth0v6']
        
        # 添加新设备
        container.devices['eth0v6'] = {
            'type': 'nic',
            'name': 'eth0v6',
            'nictype': 'routed',
            'parent': parent_if,
            'ipv6.address': ipv6_addr
        }
        container.save(wait=True)
        logger.info(f"[✓] 已在容器中配置 IPv6 网卡")
        
        # 添加 NDP 代理
        subprocess.run([
            'ip', '-6', 'neigh', 'add', 'proxy',
            ipv6_addr.split('/')[0], 'dev', parent_if
        ], stderr=subprocess.DEVNULL)
        logger.info(f"[✓] 已添加 NDP 代理")
        
        print(f"\n[✓] 成功为容器 {hostname} 配置 IPv6: {ipv6_addr}\n")
        return True
        
    except Exception as e:
        logger.error(f"[✗] 配置容器 IPv6 失败: {e}")
        return False


def release_ipv6_from_container(hostname):
    """从容器释放IPv6地址"""
    
    ipv6_addr = get_allocated(hostname)
    if not ipv6_addr:
        logger.warning(f"[!] 容器 {hostname} 未分配 IPv6")
        return False
    
    # 从容器移除设备
    try:
        client = LXDClient()
        container = client.containers.get(hostname)
        
        if 'eth0v6' in container.devices:
            del container.devices['eth0v6']
            container.save(wait=True)
            logger.info(f"[✓] 已从容器移除 IPv6 网卡")
    except Exception as e:
        logger.warning(f"[!] 从容器移除网卡失败: {e}")
    
    # 移除 NDP 代理
    try:
        parent_if = app_config.ipv6_interface or app_config.main_interface
        subprocess.run([
            'ip', '-6', 'neigh', 'del', 'proxy',
            ipv6_addr.split('/')[0], 'dev', parent_if
        ], stderr=subprocess.DEVNULL)
        logger.info(f"[✓] 已移除 NDP 代理")
    except:
        pass
    
    # 释放分配记录
    released = release(hostname)
    if released:
        print(f"\n[✓] 已释放 {hostname} 的 IPv6: {released}\n")
        return True
    
    return False


def interactive_menu():
    """交互式菜单"""
    
    while True:
        print("\n" + "="*70)
        print("  IPv6 地址管理工具")
        print("="*70)
        print("  1) 查看当前分配")
        print("  2) 查看地址池状态")
        print("  3) 为容器分配 IPv6（自动从池中选择）")
        print("  4) 为容器分配 IPv6（手动指定地址）")
        print("  5) 释放容器的 IPv6")
        print("  6) 批量分配（所有容器）")
        print("  0) 退出")
        print("="*70)
        
        choice = input("\n请选择操作 [0-6]: ").strip()
        
        if choice == '0':
            print("\n再见！\n")
            break
        
        elif choice == '1':
            show_current_allocations()
        
        elif choice == '2':
            show_address_pool()
        
        elif choice == '3':
            hostname = input("\n请输入容器名: ").strip()
            if hostname:
                assign_ipv6_to_container(hostname)
        
        elif choice == '4':
            hostname = input("\n请输入容器名: ").strip()
            if not hostname:
                continue
            ipv6 = input("请输入 IPv6 地址: ").strip()
            if ipv6:
                assign_ipv6_to_container(hostname, ipv6)
        
        elif choice == '5':
            hostname = input("\n请输入容器名: ").strip()
            if hostname:
                release_ipv6_from_container(hostname)
        
        elif choice == '6':
            try:
                client = LXDClient()
                containers = client.containers.all()
                
                if not containers:
                    print("\n[!] 没有找到任何容器\n")
                    continue
                
                print(f"\n找到 {len(containers)} 个容器，开始批量分配...\n")
                
                success = 0
                failed = 0
                
                for container in containers:
                    existing = get_allocated(container.name)
                    if existing:
                        print(f"[→] {container.name} 已分配: {existing}")
                        continue
                    
                    ipv6_addr = allocate(container.name)
                    if ipv6_addr:
                        try:
                            parent_if = app_config.ipv6_interface or app_config.main_interface
                            
                            if 'eth0v6' not in container.devices:
                                container.devices['eth0v6'] = {
                                    'type': 'nic',
                                    'name': 'eth0v6',
                                    'nictype': 'routed',
                                    'parent': parent_if,
                                    'ipv6.address': ipv6_addr
                                }
                                container.save(wait=True)
                            
                            subprocess.run([
                                'ip', '-6', 'neigh', 'add', 'proxy',
                                ipv6_addr.split('/')[0], 'dev', parent_if
                            ], stderr=subprocess.DEVNULL)
                            
                            print(f"[✓] {container.name}: {ipv6_addr}")
                            success += 1
                        except Exception as e:
                            print(f"[✗] {container.name}: 失败 - {e}")
                            failed += 1
                    else:
                        print(f"[✗] {container.name}: 无可用地址")
                        failed += 1
                
                print(f"\n批量分配完成: 成功 {success}，失败 {failed}\n")
                
            except Exception as e:
                logger.error(f"[✗] 批量分配失败: {e}")
        
        else:
            print("\n[!] 无效选择，请重试\n")


def main():
    """主函数"""
    
    # 检查 IPv6 模式
    if app_config.ipv6_mode != 'ROUTED':
        logger.error(f"\n[✗] IPv6 模式未启用或不是 ROUTED 模式")
        logger.error(f"    当前模式: {app_config.ipv6_mode}")
        logger.error(f"    请在 app.ini 中设置: IPV6_MODE = ROUTED\n")
        sys.exit(1)
    
    # 检查权限
    if os.geteuid() != 0:
        logger.error("\n[✗] 此脚本需要 root 权限运行")
        logger.error("    请使用: sudo python3 manage_ipv6.py\n")
        sys.exit(1)
    
    # 命令行参数处理
    if len(sys.argv) > 1:
        command = sys.argv[1]
        
        if command == 'list':
            show_current_allocations()
        
        elif command == 'pool':
            show_address_pool()
        
        elif command == 'assign' and len(sys.argv) >= 3:
            hostname = sys.argv[2]
            custom_ipv6 = sys.argv[3] if len(sys.argv) >= 4 else None
            assign_ipv6_to_container(hostname, custom_ipv6)
        
        elif command == 'release' and len(sys.argv) >= 3:
            hostname = sys.argv[2]
            release_ipv6_from_container(hostname)
        
        else:
            print("\n使用方法:")
            print("  python3 manage_ipv6.py              # 交互式菜单")
            print("  python3 manage_ipv6.py list         # 查看当前分配")
            print("  python3 manage_ipv6.py pool         # 查看地址池")
            print("  python3 manage_ipv6.py assign <容器名> [IPv6]  # 分配地址")
            print("  python3 manage_ipv6.py release <容器名>        # 释放地址")
            print()
    else:
        # 交互式菜单
        interactive_menu()


if __name__ == '__main__':
    main()

