#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
流量限制执行器
定期检查容器流量使用情况，自动封禁超限容器或解封未超限容器
建议每5分钟运行一次
"""

import logging
import sys
from datetime import datetime
from logging.handlers import RotatingFileHandler
from iptables_manager import IptablesManager
from flow_manager_v2 import FlowManagerV2

# 配置日志（添加日志轮转）
def setup_logging():
    """设置日志配置（支持日志轮转）"""
    logger = logging.getLogger(__name__)
    logger.setLevel(logging.INFO)
    
    # 文件处理器（10MB 轮转，保留 5 个备份）
    file_handler = RotatingFileHandler(
        'flow_limit_enforcer.log',
        maxBytes=10*1024*1024,  # 10MB
        backupCount=5,
        encoding='utf-8'
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(
        logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    )
    
    # 控制台处理器
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(
        logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    )
    
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    
    return logger

logger = setup_logging()


class FlowLimitEnforcer:
    """流量限制执行器"""
    
    def __init__(self):
        """初始化执行器"""
        self.iptables_mgr = IptablesManager()
        self.flow_mgr = FlowManagerV2()
    
    def check_and_enforce_all(self) -> dict:
        """
        检查所有容器并执行限制
        
        Returns:
            执行统计信息
        """
        logger.info("开始检查流量限制...")
        
        stats = {
            'total': 0,
            'checked': 0,
            'blocked': 0,
            'unblocked': 0,
            'skipped': 0,
            'errors': []
        }
        
        # 获取所有容器
        containers = self.flow_mgr.list_all_containers()
        stats['total'] = len(containers)
        
        if stats['total'] == 0:
            logger.info("没有已注册的容器")
            return stats
        
        logger.info(f"检查 {stats['total']} 个容器的流量限制...")
        
        for container in containers:
            hostname = container['hostname']
            used_gb = container['used_gb']
            limit_gb = container['limit_gb']
            is_blocked = container['is_blocked']
            usage_percent = container['usage_percent']
            
            # 跳过无限制的容器
            if limit_gb <= 0:
                logger.debug(f"容器 {hostname} 无流量限制，跳过")
                stats['skipped'] += 1
                continue
            
            stats['checked'] += 1
            
            try:
                # 判断是否超限
                is_overlimit = used_gb >= limit_gb
                
                if is_overlimit and not is_blocked:
                    # 超限但未封禁 → 封禁
                    logger.warning(f"容器 {hostname} 流量超限: {used_gb:.2f}/{limit_gb}GB "
                                 f"({usage_percent:.1f}%)")
                    
                    success = self.iptables_mgr.block_container(hostname)
                    if success:
                        self.flow_mgr.set_container_blocked(hostname, True)
                        stats['blocked'] += 1
                        logger.info(f"✓ 容器 {hostname} 已封禁")
                    else:
                        stats['errors'].append(f"{hostname}: 封禁失败")
                        logger.error(f"✗ 容器 {hostname} 封禁失败")
                
                elif not is_overlimit and is_blocked:
                    # 未超限但已封禁 → 解封
                    logger.info(f"容器 {hostname} 流量恢复正常: {used_gb:.2f}/{limit_gb}GB "
                              f"({usage_percent:.1f}%)")
                    
                    success = self.iptables_mgr.unblock_container(hostname)
                    if success:
                        self.flow_mgr.set_container_blocked(hostname, False)
                        stats['unblocked'] += 1
                        logger.info(f"✓ 容器 {hostname} 已解封")
                    else:
                        stats['errors'].append(f"{hostname}: 解封失败")
                        logger.error(f"✗ 容器 {hostname} 解封失败")
                
                elif is_overlimit and is_blocked:
                    # 仍然超限且已封禁 → 保持
                    logger.debug(f"容器 {hostname} 仍然超限: {used_gb:.2f}/{limit_gb}GB "
                               f"({usage_percent:.1f}%)")
                
                else:
                    # 正常状态
                    logger.debug(f"容器 {hostname} 正常: {used_gb:.2f}/{limit_gb}GB "
                               f"({usage_percent:.1f}%)")
                
            except Exception as e:
                stats['errors'].append(f"{hostname}: {str(e)}")
                logger.error(f"处理容器 {hostname} 失败: {e}")
        
        # 输出统计
        logger.info(f"检查完成: 总数={stats['total']}, 检查={stats['checked']}, "
                   f"封禁={stats['blocked']}, 解封={stats['unblocked']}, "
                   f"跳过={stats['skipped']}")
        
        if stats['errors']:
            logger.warning(f"遇到 {len(stats['errors'])} 个错误:")
            for error in stats['errors'][:10]:
                logger.warning(f"  - {error}")
        
        return stats
    
    def check_one(self, hostname: str) -> bool:
        """
        检查单个容器
        
        Args:
            hostname: 容器主机名
            
        Returns:
            是否成功
        """
        logger.info(f"检查容器 {hostname} 的流量限制...")
        
        try:
            # 获取容器信息
            info = self.flow_mgr.get_container_usage(hostname)
            if not info:
                logger.error(f"容器 {hostname} 未注册")
                return False
            
            used_gb = info['used_gb']
            limit_gb = info['limit_gb']
            is_blocked = info['is_blocked']
            usage_percent = info['usage_percent']
            
            if limit_gb <= 0:
                logger.info(f"容器 {hostname} 无流量限制")
                return True
            
            # 判断是否超限
            is_overlimit = used_gb >= limit_gb
            
            logger.info(f"容器 {hostname}: {used_gb:.2f}/{limit_gb}GB ({usage_percent:.1f}%)")
            
            if is_overlimit and not is_blocked:
                # 封禁
                logger.warning(f"容器 {hostname} 超限，开始封禁...")
                success = self.iptables_mgr.block_container(hostname)
                if success:
                    self.flow_mgr.set_container_blocked(hostname, True)
                    logger.info(f"✓ 容器 {hostname} 已封禁")
                else:
                    logger.error(f"✗ 容器 {hostname} 封禁失败")
                return success
            
            elif not is_overlimit and is_blocked:
                # 解封
                logger.info(f"容器 {hostname} 恢复正常，开始解封...")
                success = self.iptables_mgr.unblock_container(hostname)
                if success:
                    self.flow_mgr.set_container_blocked(hostname, False)
                    logger.info(f"✓ 容器 {hostname} 已解封")
                else:
                    logger.error(f"✗ 容器 {hostname} 解封失败")
                return success
            
            else:
                logger.info(f"容器 {hostname} 状态正常，无需操作")
                return True
                
        except Exception as e:
            logger.error(f"检查容器 {hostname} 失败: {e}")
            return False
    
    def show_status(self):
        """显示当前状态"""
        logger.info("=" * 70)
        logger.info("流量限制执行器状态")
        logger.info("=" * 70)
        
        containers = self.flow_mgr.list_all_containers()
        
        # 统计
        total = len(containers)
        with_limit = sum(1 for c in containers if c['limit_gb'] > 0)
        overlimit = sum(1 for c in containers if c['limit_gb'] > 0 and c['used_gb'] >= c['limit_gb'])
        blocked = sum(1 for c in containers if c['is_blocked'])
        
        logger.info(f"总容器数: {total}")
        logger.info(f"有流量限制: {with_limit}")
        logger.info(f"超限: {overlimit}")
        logger.info(f"已封禁: {blocked}")
        
        # 显示超限容器
        if overlimit > 0:
            logger.warning(f"\n超限容器 ({overlimit}个):")
            for c in containers:
                if c['limit_gb'] > 0 and c['used_gb'] >= c['limit_gb']:
                    status = '已封禁' if c['is_blocked'] else '未封禁'
                    logger.warning(f"  - {c['hostname']}: {c['used_gb']:.2f}/{c['limit_gb']}GB "
                                 f"({c['usage_percent']:.1f}%) [{status}]")
        
        # 显示已封禁但未超限的容器（异常状态）
        anomaly = [c for c in containers if c['is_blocked'] and 
                   (c['limit_gb'] <= 0 or c['used_gb'] < c['limit_gb'])]
        if anomaly:
            logger.warning(f"\n异常封禁状态 ({len(anomaly)}个):")
            for c in anomaly:
                logger.warning(f"  - {c['hostname']}: {c['used_gb']:.2f}/{c['limit_gb']}GB "
                             f"({c['usage_percent']:.1f}%) [不应封禁]")
        
        logger.info("=" * 70)
    
    def manual_block(self, hostname: str) -> bool:
        """
        手动封禁容器
        
        Args:
            hostname: 容器主机名
            
        Returns:
            是否成功
        """
        logger.info(f"手动封禁容器 {hostname}...")
        
        success = self.iptables_mgr.block_container(hostname)
        if success:
            self.flow_mgr.set_container_blocked(hostname, True)
            logger.info(f"✓ 容器 {hostname} 已封禁")
        else:
            logger.error(f"✗ 容器 {hostname} 封禁失败")
        
        return success
    
    def manual_unblock(self, hostname: str) -> bool:
        """
        手动解封容器
        
        Args:
            hostname: 容器主机名
            
        Returns:
            是否成功
        """
        logger.info(f"手动解封容器 {hostname}...")
        
        success = self.iptables_mgr.unblock_container(hostname)
        if success:
            self.flow_mgr.set_container_blocked(hostname, False)
            logger.info(f"✓ 容器 {hostname} 已解封")
        else:
            logger.error(f"✗ 容器 {hostname} 解封失败")
        
        return success


def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description='流量限制执行器')
    parser.add_argument('action', nargs='?', default='check',
                       choices=['check', 'status', 'block', 'unblock'],
                       help='操作类型')
    parser.add_argument('--hostname', help='容器主机名')
    parser.add_argument('--verbose', '-v', action='store_true', help='详细输出')
    
    args = parser.parse_args()
    
    # 设置日志级别
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    enforcer = FlowLimitEnforcer()
    
    if args.action == 'status':
        # 显示状态
        enforcer.show_status()
        sys.exit(0)
    
    elif args.action == 'block':
        # 手动封禁
        if not args.hostname:
            logger.error("需要指定 --hostname")
            sys.exit(1)
        success = enforcer.manual_block(args.hostname)
        sys.exit(0 if success else 1)
    
    elif args.action == 'unblock':
        # 手动解封
        if not args.hostname:
            logger.error("需要指定 --hostname")
            sys.exit(1)
        success = enforcer.manual_unblock(args.hostname)
        sys.exit(0 if success else 1)
    
    elif args.action == 'check':
        # 检查并执行
        if args.hostname:
            # 单个容器
            success = enforcer.check_one(args.hostname)
            sys.exit(0 if success else 1)
        else:
            # 所有容器
            stats = enforcer.check_and_enforce_all()
            if stats['errors']:
                sys.exit(1)
            else:
                sys.exit(0)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        logger.info("执行器被用户中断")
        sys.exit(130)
    except Exception as e:
        logger.error(f"执行器异常: {e}", exc_info=True)
        sys.exit(1)

