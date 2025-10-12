#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
批量修改容器流量限制工具
用于批量更新容器的流量配额设置
"""

import sys
import os
import sqlite3
from datetime import datetime

# 添加当前目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flow_manager import FlowManager
from lxc_manager import LXCManager

def get_all_containers():
    """获取所有容器列表"""
    try:
        lxc_manager = LXCManager()
        containers = lxc_manager.client.containers.all()
        return [container.name for container in containers]
    except Exception as e:
        print(f"❌ 获取容器列表失败: {e}")
        return []

def get_containers_with_flow_limit(limit_gb):
    """获取指定流量限制的容器"""
    try:
        flow_manager = FlowManager()
        with sqlite3.connect(flow_manager.db_path) as conn:
            cursor = conn.execute("""
                SELECT hostname, flow_limit_gb
                FROM container_flow_management
                WHERE flow_limit_gb = ?
                ORDER BY hostname
            """, (limit_gb,))
            return cursor.fetchall()
    except Exception as e:
        print(f"❌ 查询流量限制失败: {e}")
        return []

def update_container_flow_limit(container_name, new_limit_gb):
    """更新单个容器的流量限制"""
    try:
        flow_manager = FlowManager()
        
        # 检查容器是否在流量管理系统中
        flow_info = flow_manager.get_container_flow_info(container_name)
        if not flow_info:
            print(f"  ❌ 容器 {container_name} 未在流量管理系统中注册")
            return False
        
        # 更新流量限制
        with sqlite3.connect(flow_manager.db_path) as conn:
            cursor = conn.execute("""
                UPDATE container_flow_management 
                SET flow_limit_gb = ?, updated_at = ?
                WHERE hostname = ?
            """, (new_limit_gb, datetime.now(), container_name))
            
            if cursor.rowcount > 0:
                print(f"  ✅ 容器 {container_name}: {flow_info['flow_limit_gb']}GB → {new_limit_gb}GB")
                return True
            else:
                print(f"  ❌ 容器 {container_name} 更新失败")
                return False
                
    except Exception as e:
        print(f"  ❌ 容器 {container_name} 更新异常: {e}")
        return False

def update_container_metadata(container_name, new_limit_gb):
    """同时更新LXD容器的元数据"""
    try:
        lxc_manager = LXCManager()
        container = lxc_manager._get_container_or_error(container_name)
        if container:
            # 更新容器的用户元数据
            container.config['user.flow_limit_gb'] = str(new_limit_gb)
            container.save()
            return True
    except Exception as e:
        print(f"  ⚠️ 更新容器 {container_name} 元数据失败: {e}")
        return False

def list_containers_by_limit():
    """列出所有容器及其流量限制"""
    print("=== 所有容器的流量限制情况 ===")

    try:
        flow_manager = FlowManager()
        lxc_manager = LXCManager()

        with sqlite3.connect(flow_manager.db_path) as conn:
            cursor = conn.execute("""
                SELECT hostname, flow_limit_gb, created_date, next_reset_date
                FROM container_flow_management
                ORDER BY flow_limit_gb, hostname
            """)

            containers = cursor.fetchall()

            if not containers:
                print("没有找到已注册的容器")
                return

            # 按流量限制分组显示
            current_limit = None
            for hostname, limit_gb, created_date, next_reset in containers:
                if current_limit != limit_gb:
                    current_limit = limit_gb
                    print(f"\n📊 流量限制 {limit_gb}GB 的容器:")

                # 获取当前使用量
                try:
                    container = lxc_manager._get_container_or_error(hostname)
                    if container:
                        state = container.state()
                        current_received = 0
                        current_sent = 0
                        if state.network:
                            for nic_name, nic_data in state.network.items():
                                if 'counters' in nic_data:
                                    current_received += nic_data['counters'].get('bytes_received', 0)
                                    current_sent += nic_data['counters'].get('bytes_sent', 0)

                        usage_gb = flow_manager.calculate_current_period_usage(hostname, current_received, current_sent)
                        usage_percent = (usage_gb / limit_gb * 100) if limit_gb > 0 else 0
                        print(f"  {hostname}: {usage_gb:.2f}GB / {limit_gb}GB ({usage_percent:.1f}%) - 下次重置: {next_reset}")
                    else:
                        print(f"  {hostname}: 容器不存在 / {limit_gb}GB - 下次重置: {next_reset}")
                except Exception as e:
                    print(f"  {hostname}: 无法获取使用量 / {limit_gb}GB - 下次重置: {next_reset}")

    except Exception as e:
        print(f"❌ 查询失败: {e}")

def batch_update_by_old_limit(old_limit_gb, new_limit_gb, confirm=False):
    """批量更新指定旧限制的容器"""
    print(f"=== 批量更新流量限制: {old_limit_gb}GB → {new_limit_gb}GB ===")

    # 获取需要更新的容器
    containers = get_containers_with_flow_limit(old_limit_gb)

    if not containers:
        print(f"没有找到流量限制为 {old_limit_gb}GB 的容器")
        return

    print(f"找到 {len(containers)} 个容器需要更新:")
    for hostname, limit_gb in containers:
        print(f"  {hostname}: {limit_gb}GB → {new_limit_gb}GB")

    if not confirm:
        print(f"\n⚠️ 这是预览模式，如需执行请添加 --confirm 参数")
        return

    # 确认更新
    print(f"\n开始批量更新...")
    success_count = 0

    for hostname, limit_gb in containers:
        if update_container_flow_limit(hostname, new_limit_gb):
            # 同时更新LXD元数据
            update_container_metadata(hostname, new_limit_gb)
            success_count += 1

    print(f"\n🎉 批量更新完成: {success_count}/{len(containers)} 个容器更新成功")

def batch_update_all_containers(new_limit_gb, confirm=False):
    """批量更新所有容器的流量限制"""
    print(f"=== 批量更新所有容器流量限制为 {new_limit_gb}GB ===")

    try:
        flow_manager = FlowManager()
        with sqlite3.connect(flow_manager.db_path) as conn:
            cursor = conn.execute("""
                SELECT hostname, flow_limit_gb
                FROM container_flow_management
                ORDER BY hostname
            """)

            containers = cursor.fetchall()

            if not containers:
                print("没有找到已注册的容器")
                return

            print(f"找到 {len(containers)} 个容器需要更新:")
            for hostname, limit_gb in containers:
                print(f"  {hostname}: {limit_gb}GB → {new_limit_gb}GB")

            if not confirm:
                print(f"\n⚠️ 这是预览模式，如需执行请添加 --confirm 参数")
                return

            # 确认更新
            print(f"\n开始批量更新...")
            success_count = 0

            for hostname, limit_gb in containers:
                if update_container_flow_limit(hostname, new_limit_gb):
                    # 同时更新LXD元数据
                    update_container_metadata(hostname, new_limit_gb)
                    success_count += 1

            print(f"\n🎉 批量更新完成: {success_count}/{len(containers)} 个容器更新成功")

    except Exception as e:
        print(f"❌ 批量更新失败: {e}")

def update_single_container(container_name, new_limit_gb):
    """更新单个容器的流量限制"""
    print(f"=== 更新容器 {container_name} 的流量限制为 {new_limit_gb}GB ===")
    
    if update_container_flow_limit(container_name, new_limit_gb):
        # 同时更新LXD元数据
        update_container_metadata(container_name, new_limit_gb)
        print(f"🎉 容器 {container_name} 流量限制更新成功")
    else:
        print(f"❌ 容器 {container_name} 流量限制更新失败")

def main():
    """主函数"""
    if len(sys.argv) < 2:
        print("批量修改容器流量限制工具")
        print()
        print("用法:")
        print("  python3 batch_update_flow_limit.py list                           # 列出所有容器的流量限制")
        print("  python3 batch_update_flow_limit.py update <容器名> <新限制GB>        # 更新单个容器")
        print("  python3 batch_update_flow_limit.py batch-old <旧限制GB> <新限制GB>   # 批量更新指定旧限制的容器")
        print("  python3 batch_update_flow_limit.py batch-all <新限制GB>            # 批量更新所有容器")
        print()
        print("选项:")
        print("  --confirm    确认执行更新（不加此参数只显示预览）")
        print()
        print("示例:")
        print("  python3 batch_update_flow_limit.py list")
        print("  python3 batch_update_flow_limit.py update ser123456789 200")
        print("  python3 batch_update_flow_limit.py batch-old 2 200 --confirm")
        print("  python3 batch_update_flow_limit.py batch-all 200 --confirm")
        print()
        print("常见场景:")
        print("  # 将所有2GB限制的容器改为200GB")
        print("  python3 batch_update_flow_limit.py batch-old 2 200 --confirm")
        return
    
    command = sys.argv[1]
    confirm = '--confirm' in sys.argv
    
    if command == "list":
        list_containers_by_limit()
    
    elif command == "update":
        if len(sys.argv) < 4:
            print("请指定容器名和新的流量限制")
            print("用法: python3 batch_update_flow_limit.py update <容器名> <新限制GB>")
            return
        
        container_name = sys.argv[2]
        try:
            new_limit_gb = int(sys.argv[3])
        except ValueError:
            print("❌ 流量限制必须是数字")
            return
        
        update_single_container(container_name, new_limit_gb)
    
    elif command == "batch-old":
        if len(sys.argv) < 4:
            print("请指定旧限制和新限制")
            print("用法: python3 batch_update_flow_limit.py batch-old <旧限制GB> <新限制GB> [--confirm]")
            return
        
        try:
            old_limit_gb = int(sys.argv[2])
            new_limit_gb = int(sys.argv[3])
        except ValueError:
            print("❌ 流量限制必须是数字")
            return
        
        batch_update_by_old_limit(old_limit_gb, new_limit_gb, confirm)
    
    elif command == "batch-all":
        if len(sys.argv) < 3:
            print("请指定新的流量限制")
            print("用法: python3 batch_update_flow_limit.py batch-all <新限制GB> [--confirm]")
            return
        
        try:
            new_limit_gb = int(sys.argv[2])
        except ValueError:
            print("❌ 流量限制必须是数字")
            return
        
        batch_update_all_containers(new_limit_gb, confirm)
    
    else:
        print(f"❌ 未知命令: {command}")
        print("使用 python3 batch_update_flow_limit.py 查看帮助")

if __name__ == "__main__":
    main()
