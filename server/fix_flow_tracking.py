#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
修复流量统计功能
1. 修复 rules_cache 格式问题
2. 创建 LXD_FLOW_ACCOUNTING 链
3. 为现有容器添加流量统计规则
"""

import sys
import os
import logging
import subprocess

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def run_command(cmd, check=True):
    """运行命令"""
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=check
        )
        return result.returncode == 0, result.stdout, result.stderr
    except subprocess.CalledProcessError as e:
        return False, e.stdout, e.stderr
    except Exception as e:
        return False, "", str(e)

def create_flow_accounting_chain():
    """创建 LXD_FLOW_ACCOUNTING 链"""
    logger.info("=" * 60)
    logger.info("创建流量统计链...")
    logger.info("=" * 60)
    
    # IPv4
    logger.info("\n[1/4] 检查 IPv4 LXD_FLOW_ACCOUNTING 链...")
    success, stdout, stderr = run_command(
        ['iptables', '-L', 'LXD_FLOW_ACCOUNTING', '-n'],
        check=False
    )
    
    if not success:
        logger.info("  → 链不存在，创建中...")
        success, _, stderr = run_command(['iptables', '-N', 'LXD_FLOW_ACCOUNTING'])
        if success:
            logger.info("  ✓ IPv4 LXD_FLOW_ACCOUNTING 链创建成功")
        else:
            logger.error(f"  ✗ 创建失败: {stderr}")
            return False
    else:
        logger.info("  ✓ IPv4 LXD_FLOW_ACCOUNTING 链已存在")
    
    # IPv6
    logger.info("\n[2/4] 检查 IPv6 LXD_FLOW_ACCOUNTING 链...")
    success, stdout, stderr = run_command(
        ['ip6tables', '-L', 'LXD_FLOW_ACCOUNTING', '-n'],
        check=False
    )
    
    if not success:
        logger.info("  → 链不存在，创建中...")
        success, _, stderr = run_command(['ip6tables', '-N', 'LXD_FLOW_ACCOUNTING'])
        if success:
            logger.info("  ✓ IPv6 LXD_FLOW_ACCOUNTING 链创建成功")
        else:
            logger.error(f"  ✗ 创建失败: {stderr}")
            return False
    else:
        logger.info("  ✓ IPv6 LXD_FLOW_ACCOUNTING 链已存在")
    
    # 检查 FORWARD 链是否跳转到 LXD_FLOW_ACCOUNTING
    logger.info("\n[3/4] 检查 IPv4 FORWARD 链跳转...")
    success, stdout, stderr = run_command(['iptables', '-L', 'FORWARD', '-n'])
    
    if 'LXD_FLOW_ACCOUNTING' not in stdout:
        logger.info("  → 添加跳转规则...")
        success, _, stderr = run_command(
            ['iptables', '-I', 'FORWARD', '1', '-j', 'LXD_FLOW_ACCOUNTING']
        )
        if success:
            logger.info("  ✓ IPv4 FORWARD 跳转规则添加成功")
        else:
            logger.error(f"  ✗ 添加失败: {stderr}")
            return False
    else:
        logger.info("  ✓ IPv4 FORWARD 跳转规则已存在")
    
    logger.info("\n[4/4] 检查 IPv6 FORWARD 链跳转...")
    success, stdout, stderr = run_command(['ip6tables', '-L', 'FORWARD', '-n'])
    
    if 'LXD_FLOW_ACCOUNTING' not in stdout:
        logger.info("  → 添加跳转规则...")
        success, _, stderr = run_command(
            ['ip6tables', '-I', 'FORWARD', '1', '-j', 'LXD_FLOW_ACCOUNTING']
        )
        if success:
            logger.info("  ✓ IPv6 FORWARD 跳转规则添加成功")
        else:
            logger.error(f"  ✗ 添加失败: {stderr}")
            return False
    else:
        logger.info("  ✓ IPv6 FORWARD 跳转规则已存在")
    
    return True

def add_container_rules():
    """为现有容器添加流量统计规则"""
    logger.info("\n" + "=" * 60)
    logger.info("为现有容器添加流量统计规则...")
    logger.info("=" * 60)
    
    try:
        from iptables_manager import IptablesManager
        from pylxd import Client
        
        iptables_mgr = IptablesManager()
        lxd_client = Client()
        
        containers = lxd_client.containers.all()
        logger.info(f"\n找到 {len(containers)} 个容器")
        
        success_count = 0
        for container in containers:
            hostname = container.name
            
            # 检查容器状态
            if container.status != 'Running':
                logger.info(f"  ⊙ {hostname}: 容器未运行，跳过")
                continue
            
            # 检查规则是否已存在
            if iptables_mgr.check_container_rules_exist(hostname):
                logger.info(f"  ✓ {hostname}: 流量统计规则已存在")
                success_count += 1
                continue
            
            # 为容器创建规则
            logger.info(f"  → {hostname}: 创建流量统计规则...")
            if iptables_mgr.ensure_container_rules(hostname):
                logger.info(f"  ✓ {hostname}: 创建成功")
                success_count += 1
            else:
                logger.error(f"  ✗ {hostname}: 创建失败")
        
        logger.info(f"\n成功为 {success_count}/{len(containers)} 个容器配置流量统计")
        return success_count > 0
        
    except Exception as e:
        logger.error(f"添加容器规则失败: {e}", exc_info=True)
        return False

def test_flow_collection():
    """测试流量收集功能"""
    logger.info("\n" + "=" * 60)
    logger.info("测试流量收集功能...")
    logger.info("=" * 60)
    
    try:
        logger.info("\n运行流量收集器...")
        success, stdout, stderr = run_command(['python3', 'flow_collector.py'])
        
        if success:
            logger.info("✓ 流量收集器运行成功")
            if stdout:
                logger.info(f"\n输出:\n{stdout}")
            return True
        else:
            logger.error("✗ 流量收集器运行失败")
            if stderr:
                logger.error(f"\n错误:\n{stderr}")
            return False
            
    except Exception as e:
        logger.error(f"测试流量收集失败: {e}", exc_info=True)
        return False

def main():
    """主函数"""
    logger.info("=" * 60)
    logger.info("流量统计修复脚本")
    logger.info("=" * 60)
    
    # 检查是否为 root
    if os.geteuid() != 0:
        logger.error("✗ 此脚本需要 root 权限运行")
        logger.error("  请使用: sudo python3 fix_flow_tracking.py")
        return 1
    
    # 切换到 server 目录
    script_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(script_dir)
    logger.info(f"\n工作目录: {script_dir}\n")
    
    try:
        # 步骤1: 创建流量统计链
        if not create_flow_accounting_chain():
            logger.error("\n✗ 创建流量统计链失败")
            return 1
        
        # 步骤2: 为容器添加规则
        if not add_container_rules():
            logger.error("\n✗ 添加容器规则失败")
            return 1
        
        # 步骤3: 测试流量收集
        if not test_flow_collection():
            logger.warning("\n⚠ 流量收集测试失败（可能需要手动检查）")
        
        # 完成
        logger.info("\n" + "=" * 60)
        logger.info("✓ 流量统计修复完成！")
        logger.info("=" * 60)
        logger.info("\n后续步骤:")
        logger.info("  1. 重启流量收集服务:")
        logger.info("     systemctl restart lxd-flow-collector.timer")
        logger.info("\n  2. 查看流量统计:")
        logger.info("     python3 flow_manager_v2.py list")
        logger.info("\n  3. 查看服务日志:")
        logger.info("     journalctl -u lxd-flow-collector.service -f")
        logger.info("")
        
        return 0
        
    except KeyboardInterrupt:
        logger.info("\n\n⚠ 用户中断")
        return 130
    except Exception as e:
        logger.error(f"\n✗ 发生意外错误: {e}", exc_info=True)
        return 1

if __name__ == '__main__':
    sys.exit(main())

