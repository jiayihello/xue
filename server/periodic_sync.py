#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
定期同步工具
定期检查并修复 iptables 规则与数据库的一致性
建议每小时运行一次
"""

import logging
import sys
from iptables_manager import IptablesManager
from flow_manager_v2 import FlowManagerV2
from lxc_manager import LXCManager

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('periodic_sync.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class PeriodicSyncer:
    """定期同步器"""
    
    def __init__(self):
        """初始化同步器"""
        self.iptables_mgr = IptablesManager()
        self.flow_mgr = FlowManagerV2()
        self.lxc_mgr = LXCManager()
    
    def sync(self) -> dict:
        """
        执行同步
        
        Returns:
            同步统计信息
        """
        logger.info("开始同步检查...")
        
        stats = {
            'total_checked': 0,
            'rules_fixed': 0,
            'blocks_fixed': 0,
            'orphaned_rules': 0,
            'errors': []
        }
        
        try:
            # 获取所有运行中的容器
            running_containers = set(self.lxc_mgr.list_all_containers())
            logger.info(f"当前运行中的容器: {len(running_containers)}个")
            
            # 获取数据库中的所有容器
            db_containers = self.flow_mgr.list_all_containers()
            logger.info(f"数据库中的容器: {len(db_containers)}个")
            
            # 检查每个数据库中的容器
            for container in db_containers:
                hostname = container['hostname']
                is_blocked = container['is_blocked']
                stats['total_checked'] += 1
                
                try:
                    # 检查容器是否在运行
                    container_name = self.lxc_mgr.get_container_name_by_hostname(hostname)
                    if not container_name or container_name not in running_containers:
                        logger.debug(f"容器 {hostname} 未运行，跳过")
                        continue
                    
                    # 检查 iptables 规则是否存在
                    rules_exist = self.iptables_mgr.check_container_rules_exist(hostname)
                    
                    if not rules_exist:
                        # 规则缺失，重新添加
                        logger.warning(f"容器 {hostname} 规则缺失，重新添加...")
                        success = self.iptables_mgr.ensure_container_rules(hostname)
                        if success:
                            stats['rules_fixed'] += 1
                            logger.info(f"✓ 容器 {hostname} 规则已恢复")
                        else:
                            stats['errors'].append(f"{hostname}: 规则恢复失败")
                            logger.error(f"✗ 容器 {hostname} 规则恢复失败")
                    
                    # 检查封禁状态一致性
                    is_actually_blocked = self.iptables_mgr.is_container_blocked(hostname)
                    
                    if is_blocked and not is_actually_blocked:
                        # 应该封禁但未封禁
                        logger.warning(f"容器 {hostname} 应封禁但未封禁，修复中...")
                        success = self.iptables_mgr.block_container(hostname)
                        if success:
                            stats['blocks_fixed'] += 1
                            logger.info(f"✓ 容器 {hostname} 封禁已恢复")
                        else:
                            stats['errors'].append(f"{hostname}: 封禁恢复失败")
                            logger.error(f"✗ 容器 {hostname} 封禁恢复失败")
                    
                    elif not is_blocked and is_actually_blocked:
                        # 不应封禁但被封禁
                        logger.warning(f"容器 {hostname} 不应封禁但被封禁，修复中...")
                        success = self.iptables_mgr.unblock_container(hostname)
                        if success:
                            stats['blocks_fixed'] += 1
                            logger.info(f"✓ 容器 {hostname} 封禁已解除")
                        else:
                            stats['errors'].append(f"{hostname}: 解封失败")
                            logger.error(f"✗ 容器 {hostname} 解封失败")
                
                except Exception as e:
                    stats['errors'].append(f"{hostname}: {str(e)}")
                    logger.error(f"同步容器 {hostname} 失败: {e}")
            
            # 清理孤立的 iptables 规则
            logger.info("检查孤立的 iptables 规则...")
            orphaned = self.cleanup_orphaned_rules(running_containers, db_containers)
            stats['orphaned_rules'] = orphaned
            
            # 输出统计
            logger.info(f"同步完成: 检查={stats['total_checked']}, "
                       f"规则修复={stats['rules_fixed']}, "
                       f"封禁修复={stats['blocks_fixed']}, "
                       f"孤立规则清理={stats['orphaned_rules']}")
            
            if stats['errors']:
                logger.warning(f"遇到 {len(stats['errors'])} 个错误:")
                for error in stats['errors'][:10]:
                    logger.warning(f"  - {error}")
        
        except Exception as e:
            logger.error(f"同步失败: {e}", exc_info=True)
            stats['errors'].append(f"全局错误: {str(e)}")
        
        return stats
    
    def cleanup_orphaned_rules(self, running_containers: set, db_containers: list) -> int:
        """
        清理孤立的 iptables 规则
        
        Args:
            running_containers: 运行中的容器集合
            db_containers: 数据库中的容器列表
            
        Returns:
            清理的规则数量
        """
        cleaned = 0
        
        try:
            # 获取所有 iptables 规则中的容器
            iptables_hostnames = self.iptables_mgr.list_all_tracked_containers()
            
            # 数据库中的所有 hostname
            db_hostnames = {c['hostname'] for c in db_containers}
            
            # 运行中容器的所有 hostname
            running_hostnames = set()
            for container_name in running_containers:
                hostname = self.lxc_mgr.get_container_hostname(container_name)
                if hostname:
                    running_hostnames.add(hostname)
            
            # 找出孤立的规则（既不在数据库中，也不在运行中）
            for hostname in iptables_hostnames:
                if hostname not in db_hostnames and hostname not in running_hostnames:
                    logger.warning(f"发现孤立规则: {hostname}，清理中...")
                    success = self.iptables_mgr.remove_container_rules(hostname)
                    if success:
                        cleaned += 1
                        logger.info(f"✓ 孤立规则 {hostname} 已清理")
                    else:
                        logger.error(f"✗ 孤立规则 {hostname} 清理失败")
        
        except Exception as e:
            logger.error(f"清理孤立规则失败: {e}")
        
        return cleaned
    
    def show_status(self):
        """显示同步状态"""
        logger.info("=" * 70)
        logger.info("同步状态检查")
        logger.info("=" * 70)
        
        try:
            # 获取运行中的容器
            running_containers = set(self.lxc_mgr.list_all_containers())
            logger.info(f"运行中的容器: {len(running_containers)}个")
            
            # 获取数据库中的容器
            db_containers = self.flow_mgr.list_all_containers()
            logger.info(f"数据库中的容器: {len(db_containers)}个")
            
            # 获取有 iptables 规则的容器
            iptables_hostnames = self.iptables_mgr.list_all_tracked_containers()
            logger.info(f"有 iptables 规则的容器: {len(iptables_hostnames)}个")
            
            # 检查不一致
            issues = []
            
            for container in db_containers:
                hostname = container['hostname']
                container_name = self.lxc_mgr.get_container_name_by_hostname(hostname)
                
                if container_name and container_name in running_containers:
                    # 容器在运行
                    if hostname not in iptables_hostnames:
                        issues.append(f"{hostname}: 运行中但无 iptables 规则")
                    
                    # 检查封禁状态
                    is_blocked_db = container['is_blocked']
                    is_blocked_iptables = self.iptables_mgr.is_container_blocked(hostname)
                    
                    if is_blocked_db != is_blocked_iptables:
                        issues.append(f"{hostname}: 封禁状态不一致 "
                                    f"(DB={is_blocked_db}, iptables={is_blocked_iptables})")
            
            # 孤立规则
            db_hostnames = {c['hostname'] for c in db_containers}
            for hostname in iptables_hostnames:
                if hostname not in db_hostnames:
                    issues.append(f"{hostname}: 孤立的 iptables 规则（不在数据库中）")
            
            # 输出结果
            if issues:
                logger.warning(f"\n发现 {len(issues)} 个问题:")
                for issue in issues[:20]:
                    logger.warning(f"  - {issue}")
            else:
                logger.info("\n✓ 所有容器状态一致")
        
        except Exception as e:
            logger.error(f"状态检查失败: {e}")
        
        logger.info("=" * 70)


def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description='定期同步工具')
    parser.add_argument('action', nargs='?', default='sync',
                       choices=['sync', 'status'],
                       help='操作类型')
    parser.add_argument('--verbose', '-v', action='store_true', help='详细输出')
    
    args = parser.parse_args()
    
    # 设置日志级别
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    syncer = PeriodicSyncer()
    
    if args.action == 'status':
        # 显示状态
        syncer.show_status()
        sys.exit(0)
    
    elif args.action == 'sync':
        # 执行同步
        stats = syncer.sync()
        if stats['errors']:
            sys.exit(1)
        else:
            sys.exit(0)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        logger.info("同步被用户中断")
        sys.exit(130)
    except Exception as e:
        logger.error(f"同步异常: {e}", exc_info=True)
        sys.exit(1)

