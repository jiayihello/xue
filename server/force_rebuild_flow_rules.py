#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
强制重建流量统计规则
清除所有缓存和规则，从零开始重建
"""

import sys
import os
import logging
import json

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def main():
    """主函数"""
    logger.info("=" * 60)
    logger.info("强制重建流量统计规则")
    logger.info("=" * 60)
    
    # 检查是否为 root
    if os.geteuid() != 0:
        logger.error("✗ 此脚本需要 root 权限运行")
        return 1
    
    # 切换到 server 目录
    script_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(script_dir)
    logger.info(f"\n工作目录: {script_dir}\n")
    
    try:
        from iptables_manager import IptablesManager
        from pylxd import Client
        
        # 步骤1: 清除缓存
        logger.info("步骤1: 清除缓存文件...")
        cache_file = 'iptables_rules.json'
        if os.path.exists(cache_file):
            # 备份旧文件
            backup_file = cache_file + '.backup'
            os.rename(cache_file, backup_file)
            logger.info(f"  ✓ 已备份缓存到 {backup_file}")
        
        # 创建空缓存
        with open(cache_file, 'w') as f:
            json.dump({}, f)
        logger.info(f"  ✓ 已清空缓存文件")
        
        # 步骤2: 获取所有容器
        logger.info("\n步骤2: 获取容器列表...")
        lxd_client = Client()
        containers = lxd_client.containers.all()
        running_containers = [c for c in containers if c.status == 'Running']
        logger.info(f"  找到 {len(running_containers)} 个运行中的容器")
        
        # 步骤3: 为每个容器创建规则
        logger.info("\n步骤3: 创建流量统计规则...")
        iptables_mgr = IptablesManager()
        
        success_count = 0
        for container in running_containers:
            hostname = container.name
            logger.info(f"\n  处理容器: {hostname}")
            
            # 获取容器IP
            state = container.state()
            ipv4 = None
            ipv6 = None
            
            if state.network and 'eth0' in state.network:
                eth0 = state.network['eth0']
                addresses = eth0.get('addresses', [])
                
                for addr in addresses:
                    if addr['family'] == 'inet' and addr['scope'] == 'global':
                        ipv4 = addr['address']
                    elif addr['family'] == 'inet6' and addr['scope'] == 'global':
                        ipv6 = addr['address']
            
            if not ipv4 and not ipv6:
                logger.warning(f"    ⚠ 无法获取IP地址，跳过")
                continue
            
            logger.info(f"    IPv4: {ipv4}")
            logger.info(f"    IPv6: {ipv6}")
            
            # 直接调用内部方法创建规则
            success = True
            if ipv4:
                logger.info(f"    → 创建 IPv4 规则...")
                if iptables_mgr._setup_ipv4_rules(hostname, ipv4):
                    logger.info(f"    ✓ IPv4 规则创建成功")
                else:
                    logger.error(f"    ✗ IPv4 规则创建失败")
                    success = False
            
            if ipv6:
                logger.info(f"    → 创建 IPv6 规则...")
                if iptables_mgr._setup_ipv6_rules(hostname, ipv6):
                    logger.info(f"    ✓ IPv6 规则创建成功")
                else:
                    logger.error(f"    ✗ IPv6 规则创建失败")
                    success = False
            
            if success:
                # 更新缓存
                iptables_mgr.rules_cache[hostname] = {
                    'ipv4': ipv4,
                    'ipv6': ipv6
                }
                iptables_mgr._save_rules_cache()
                success_count += 1
                logger.info(f"    ✓ {hostname} 完成")
        
        logger.info(f"\n成功为 {success_count}/{len(running_containers)} 个容器创建规则")
        
        # 步骤4: 验证规则
        logger.info("\n步骤4: 验证规则...")
        import subprocess
        
        logger.info("\n  IPv4 规则:")
        result = subprocess.run(
            ['iptables', '-L', 'LXD_FLOW_ACCOUNTING', '-n', '-v'],
            capture_output=True,
            text=True
        )
        print(result.stdout)
        
        logger.info("\n  IPv6 规则:")
        result = subprocess.run(
            ['ip6tables', '-L', 'LXD_FLOW_ACCOUNTING', '-n', '-v'],
            capture_output=True,
            text=True
        )
        print(result.stdout)
        
        # 完成
        logger.info("\n" + "=" * 60)
        logger.info("✓ 流量统计规则重建完成！")
        logger.info("=" * 60)
        logger.info("\n后续步骤:")
        logger.info("  1. 重启流量收集服务:")
        logger.info("     systemctl restart lxd-flow-collector.service")
        logger.info("\n  2. 测试流量收集:")
        logger.info("     python3 flow_collector.py")
        logger.info("\n  3. 查看流量统计:")
        logger.info("     python3 flow_manager_v2.py list")
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

