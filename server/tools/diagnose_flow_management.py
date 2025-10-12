#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
流量管理系统诊断和修复脚本
"""

import os
import sys
import subprocess
import sqlite3
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def check_database():
    """检查数据库是否存在和完整性"""
    print("\n=== 检查数据库 ===")
    db_path = "flow_management.db"
    
    if not os.path.exists(db_path):
        print("❌ 数据库不存在")
        return False
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # 检查必要的表
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [row[0] for row in cursor.fetchall()]
        
        required_tables = ['container_flow_management', 'flow_reset_history']
        missing_tables = [t for t in required_tables if t not in tables]
        
        if missing_tables:
            print(f"❌ 缺少必要的表: {', '.join(missing_tables)}")
            conn.close()
            return False
        
        # 检查容器数量
        cursor.execute("SELECT COUNT(*) FROM container_flow_management")
        count = cursor.fetchone()[0]
        
        print(f"✅ 数据库正常")
        print(f"   已注册容器数: {count}")
        
        conn.close()
        return True
    except Exception as e:
        print(f"❌ 数据库错误: {e}")
        return False

def check_crontab():
    """检查定时任务"""
    print("\n=== 检查定时任务 ===")
    try:
        result = subprocess.run(['crontab', '-l'], capture_output=True, text=True)
        crontab_content = result.stdout
        
        has_reset = 'flow_reset_scheduler.py reset' in crontab_content
        has_cleanup = 'flow_reset_scheduler.py cleanup' in crontab_content
        
        if has_reset:
            print("✅ 流量重置定时任务已配置")
            # 显示具体的定时任务
            for line in crontab_content.split('\n'):
                if 'flow_reset_scheduler.py reset' in line:
                    print(f"   {line}")
        else:
            print("❌ 流量重置定时任务未配置")
        
        if has_cleanup:
            print("✅ 清理定时任务已配置")
            for line in crontab_content.split('\n'):
                if 'flow_reset_scheduler.py cleanup' in line:
                    print(f"   {line}")
        else:
            print("❌ 清理定时任务未配置")
        
        return has_reset and has_cleanup
    except Exception as e:
        print(f"❌ 检查定时任务失败: {e}")
        return False

def check_daemon():
    """检查守护进程"""
    print("\n=== 检查守护进程 ===")
    try:
        result = subprocess.run(
            ['systemctl', 'is-active', 'lxd-flow-continuity.service'],
            capture_output=True, text=True
        )
        
        if result.returncode == 0:
            print("✅ 流量连续性守护进程正在运行")
            return True
        else:
            print("❌ 流量连续性守护进程未运行")
            return False
    except Exception as e:
        print(f"⚠️  检查守护进程失败: {e}")
        return False

def check_container_registration():
    """检查容器注册情况"""
    print("\n=== 检查容器注册情况 ===")
    try:
        from lxc_manager import LXCManager
        from flow_manager import FlowManager
        
        lxc_mgr = LXCManager()
        flow_mgr = FlowManager()
        
        # 获取所有LXD容器
        all_containers = lxc_mgr.client.containers.all()
        lxd_containers = {c.name for c in all_containers}
        
        # 获取已注册的容器
        conn = sqlite3.connect("flow_management.db")
        cursor = conn.cursor()
        cursor.execute("SELECT hostname FROM container_flow_management")
        registered_containers = {row[0] for row in cursor.fetchall()}
        conn.close()
        
        # 找出未注册的容器
        unregistered = lxd_containers - registered_containers
        
        # 找出已删除但仍在数据库中的容器
        deleted_but_registered = registered_containers - lxd_containers
        
        print(f"LXD 容器总数: {len(lxd_containers)}")
        print(f"已注册容器数: {len(registered_containers)}")
        
        if unregistered:
            print(f"\n⚠️  未注册的容器 ({len(unregistered)}):")
            for name in sorted(unregistered):
                print(f"   - {name}")
        else:
            print("✅ 所有容器都已注册")
        
        if deleted_but_registered:
            print(f"\n⚠️  已删除但仍在数据库中的容器 ({len(deleted_but_registered)}):")
            for name in sorted(deleted_but_registered):
                print(f"   - {name}")
        
        return len(unregistered) == 0 and len(deleted_but_registered) == 0
    except Exception as e:
        print(f"❌ 检查失败: {e}")
        import traceback
        traceback.print_exc()
        return False

def fix_crontab():
    """修复定时任务"""
    print("\n=== 修复定时任务 ===")
    try:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        
        # 获取现有的 crontab
        result = subprocess.run(['crontab', '-l'], capture_output=True, text=True)
        existing_crontab = result.stdout if result.returncode == 0 else ""
        
        # 移除旧的流量管理定时任务
        lines = [line for line in existing_crontab.split('\n') 
                 if 'flow_reset_scheduler.py' not in line]
        
        # 添加新的定时任务
        lines.append(f"0 2 * * * /usr/bin/python3 {script_dir}/flow_reset_scheduler.py reset >/dev/null 2>&1")
        lines.append(f"0 3 * * 0 /usr/bin/python3 {script_dir}/flow_reset_scheduler.py cleanup >/dev/null 2>&1")
        
        # 写入新的 crontab
        new_crontab = '\n'.join(filter(None, lines)) + '\n'
        
        proc = subprocess.Popen(['crontab', '-'], stdin=subprocess.PIPE, text=True)
        proc.communicate(input=new_crontab)
        
        if proc.returncode == 0:
            print("✅ 定时任务已修复")
            print("   每天凌晨 2 点: 自动重置到期流量")
            print("   每周日凌晨 3 点: 清理已删除容器记录")
            return True
        else:
            print("❌ 定时任务修复失败")
            return False
    except Exception as e:
        print(f"❌ 修复定时任务失败: {e}")
        return False

def fix_container_registration():
    """修复容器注册"""
    print("\n=== 修复容器注册 ===")
    try:
        # 注册所有未注册的容器
        print("正在注册未注册的容器...")
        subprocess.run(['python3', 'flow_reset_scheduler.py', 'register'])
        
        # 清理已删除容器的记录
        print("\n正在清理已删除容器的记录...")
        subprocess.run(['python3', 'flow_reset_scheduler.py', 'cleanup'])
        
        print("\n✅ 容器注册已修复")
        return True
    except Exception as e:
        print(f"❌ 修复容器注册失败: {e}")
        return False

def restart_daemon():
    """重启守护进程"""
    print("\n=== 重启守护进程 ===")
    try:
        subprocess.run(['systemctl', 'restart', 'lxd-flow-continuity.service'], check=True)
        print("✅ 守护进程已重启")
        return True
    except Exception as e:
        print(f"❌ 重启守护进程失败: {e}")
        return False

def main():
    print("=" * 60)
    print("  流量管理系统诊断和修复工具")
    print("=" * 60)
    
    # 检查是否为 root
    if os.geteuid() != 0:
        print("\n⚠️  建议使用 root 权限运行此脚本")
        print("   sudo python3 diagnose_flow_management.py")
    
    # 诊断阶段
    print("\n### 第一步：诊断系统 ###")
    
    db_ok = check_database()
    cron_ok = check_crontab()
    daemon_ok = check_daemon()
    reg_ok = check_container_registration()
    
    issues = []
    if not db_ok:
        issues.append("数据库")
    if not cron_ok:
        issues.append("定时任务")
    if not daemon_ok:
        issues.append("守护进程")
    if not reg_ok:
        issues.append("容器注册")
    
    # 修复阶段
    if issues:
        print("\n" + "=" * 60)
        print(f"发现 {len(issues)} 个问题: {', '.join(issues)}")
        print("=" * 60)
        
        print("\n### 第二步：修复问题 ###")
        
        response = input("\n是否自动修复这些问题? (Y/n): ")
        if response.lower() != 'n':
            fixed = 0
            
            if not cron_ok:
                if fix_crontab():
                    fixed += 1
            
            if not reg_ok:
                if fix_container_registration():
                    fixed += 1
            
            if not daemon_ok:
                if restart_daemon():
                    fixed += 1
            
            if not db_ok:
                print("\n⚠️  数据库问题需要手动修复")
                print("   请运行: python3 upgrade_flow_database.py")
            
            print("\n" + "=" * 60)
            print(f"修复完成: {fixed}/{len(issues)} 个问题已解决")
            print("=" * 60)
        else:
            print("\n跳过自动修复")
    else:
        print("\n" + "=" * 60)
        print("✅ 所有检查通过，系统运行正常！")
        print("=" * 60)
    
    # 显示后续操作建议
    print("\n### 后续操作建议 ###")
    print("\n1. 查看所有容器流量使用情况:")
    print("   python3 list_flow_usage.py")
    print("\n2. 手动测试流量重置:")
    print("   lxd-flow-manager reset <容器名>")
    print("\n3. 查看守护进程日志:")
    print("   journalctl -u lxd-flow-continuity.service -f")
    print("\n4. 检查定时任务:")
    print("   crontab -l | grep flow")
    print("\n5. 测试自动重置功能:")
    print("   python3 flow_reset_scheduler.py reset")
    print()

if __name__ == "__main__":
    main()

