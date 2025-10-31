#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
流量重置调度器
定期检查并重置到期容器的流量
建议每天凌晨运行一次
"""

import logging
import sys
from datetime import date
from logging.handlers import RotatingFileHandler
from flow_manager_v2 import FlowManagerV2
from iptables_manager import IptablesManager

# 配置日志（添加日志轮转）
def setup_logging():
    """设置日志配置（支持日志轮转）"""
    logger = logging.getLogger(__name__)
    logger.setLevel(logging.INFO)
    
    # 文件处理器（10MB 轮转，保留 5 个备份）
    file_handler = RotatingFileHandler(
        'flow_reset.log',
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


class FlowResetScheduler:
    """流量重置调度器"""
    
    def __init__(self):
        """初始化调度器"""
        self.flow_mgr = FlowManagerV2()
        self.iptables_mgr = IptablesManager()
    
    def reset_due_containers(self) -> dict:
        """
        重置所有到期的容器
        
        Returns:
            重置统计信息
        """
        logger.info("开始检查需要重置的容器...")
        
        stats = {
            'total_checked': 0,
            'due': 0,
            'reset': 0,
            'failed': 0,
            'errors': []
        }
        
        # 获取所有到期的容器
        overdue_containers = self.flow_mgr.check_and_get_overdue_containers()
        stats['due'] = len(overdue_containers)
        
        if stats['due'] == 0:
            logger.info("没有需要重置的容器")
            return stats
        
        logger.info(f"找到 {stats['due']} 个需要重置的容器")
        
        # 逐个重置
        for hostname in overdue_containers:
            try:
                # 获取容器信息
                info = self.flow_mgr.get_container_usage(hostname)
                if not info:
                    logger.warning(f"容器 {hostname} 信息获取失败，跳过")
                    stats['failed'] += 1
                    continue
                
                used_gb = info['used_gb']
                logger.info(f"重置容器 {hostname}: 已用 {used_gb:.2f}GB")
                
                # 重置流量
                success = self.flow_mgr.reset_container_flow(hostname, 'scheduled')
                
                if success:
                    # 如果容器被封禁，解除封禁
                    if info['is_blocked']:
                        logger.info(f"容器 {hostname} 被封禁，正在解封...")
                        unblock_success = self.iptables_mgr.unblock_container(hostname)
                        if unblock_success:
                            self.flow_mgr.set_container_blocked(hostname, False)
                            logger.info(f"✓ 容器 {hostname} 已解封")
                        else:
                            logger.warning(f"⚠ 容器 {hostname} 解封失败")
                    
                    stats['reset'] += 1
                    logger.info(f"✓ 容器 {hostname} 流量已重置")
                else:
                    stats['failed'] += 1
                    stats['errors'].append(f"{hostname}: 重置失败")
                    logger.error(f"✗ 容器 {hostname} 流量重置失败")
                    
            except Exception as e:
                stats['failed'] += 1
                error_msg = f"{hostname}: {str(e)}"
                stats['errors'].append(error_msg)
                logger.error(f"重置容器 {hostname} 失败: {e}")
        
        # 输出统计
        logger.info(f"重置完成: 到期={stats['due']}, 成功={stats['reset']}, "
                   f"失败={stats['failed']}")
        
        if stats['errors']:
            logger.warning(f"遇到 {len(stats['errors'])} 个错误:")
            for error in stats['errors'][:10]:
                logger.warning(f"  - {error}")
        
        return stats
    
    def reset_one(self, hostname: str, reset_type: str = 'manual') -> bool:
        """
        重置单个容器的流量
        
        Args:
            hostname: 容器主机名
            reset_type: 重置类型（'manual' 或 'scheduled'）
            
        Returns:
            是否成功
        """
        logger.info(f"重置容器 {hostname} 的流量...")
        
        try:
            # 获取容器信息
            info = self.flow_mgr.get_container_usage(hostname)
            if not info:
                logger.error(f"容器 {hostname} 未注册")
                return False
            
            used_gb = info['used_gb']
            logger.info(f"当前已用流量: {used_gb:.2f}GB")
            
            # 重置流量
            success = self.flow_mgr.reset_container_flow(hostname, reset_type)
            
            if success:
                # 如果容器被封禁，解除封禁
                if info['is_blocked']:
                    logger.info(f"容器 {hostname} 被封禁，正在解封...")
                    unblock_success = self.iptables_mgr.unblock_container(hostname)
                    if unblock_success:
                        self.flow_mgr.set_container_blocked(hostname, False)
                        logger.info(f"✓ 容器 {hostname} 已解封")
                    else:
                        logger.warning(f"⚠ 容器 {hostname} 解封失败")
                
                logger.info(f"✓ 容器 {hostname} 流量已重置: {used_gb:.2f}GB → 0GB")
                return True
            else:
                logger.error(f"✗ 容器 {hostname} 流量重置失败")
                return False
                
        except Exception as e:
            logger.error(f"重置容器 {hostname} 失败: {e}")
            return False
    
    def show_status(self):
        """显示重置状态"""
        logger.info("=" * 70)
        logger.info("流量重置调度器状态")
        logger.info("=" * 70)
        
        today = date.today()
        
        # 获取所有到期的容器
        overdue = self.flow_mgr.check_and_get_overdue_containers()
        
        logger.info(f"当前日期: {today}")
        logger.info(f"到期容器数: {len(overdue)}")
        
        if overdue:
            logger.warning(f"\n需要重置的容器 ({len(overdue)}个):")
            for hostname in overdue[:20]:  # 最多显示20个
                info = self.flow_mgr.get_container_usage(hostname)
                if info:
                    logger.warning(f"  - {hostname}: {info['used_gb']:.2f}GB, "
                                 f"应于 {info['next_reset_date']} 重置")
        
        # 显示最近的重置日期
        containers = self.flow_mgr.list_all_containers()
        if containers:
            logger.info(f"\n最近的重置日期:")
            # 按重置日期排序
            sorted_containers = sorted(containers, 
                                      key=lambda x: x['next_reset_date'])
            for c in sorted_containers[:10]:
                logger.info(f"  - {c['hostname']}: {c['next_reset_date']}")
        
        logger.info("=" * 70)
    
    def reset_all(self, force: bool = False) -> dict:
        """
        重置所有容器（仅用于测试或特殊情况）
        
        Args:
            force: 是否强制重置（忽略日期）
            
        Returns:
            重置统计信息
        """
        if not force:
            logger.error("reset_all 需要 --force 参数，防止误操作")
            return {'error': 'force required'}
        
        logger.warning("⚠️ 强制重置所有容器的流量...")
        
        containers = self.flow_mgr.list_all_containers()
        stats = {
            'total': len(containers),
            'success': 0,
            'failed': 0
        }
        
        for c in containers:
            hostname = c['hostname']
            success = self.reset_one(hostname, 'manual')
            if success:
                stats['success'] += 1
            else:
                stats['failed'] += 1
        
        logger.info(f"批量重置完成: 总数={stats['total']}, "
                   f"成功={stats['success']}, 失败={stats['failed']}")
        
        return stats


def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description='流量重置调度器')
    parser.add_argument('action', nargs='?', default='reset_due',
                       choices=['reset_due', 'reset', 'status', 'reset_all'],
                       help='操作类型')
    parser.add_argument('--hostname', help='容器主机名（用于 reset）')
    parser.add_argument('--force', action='store_true',
                       help='强制执行（用于 reset_all）')
    parser.add_argument('--verbose', '-v', action='store_true', help='详细输出')
    
    args = parser.parse_args()
    
    # 设置日志级别
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    scheduler = FlowResetScheduler()
    
    if args.action == 'status':
        # 显示状态
        scheduler.show_status()
        sys.exit(0)
    
    elif args.action == 'reset':
        # 重置单个容器
        if not args.hostname:
            logger.error("需要指定 --hostname")
            sys.exit(1)
        success = scheduler.reset_one(args.hostname, 'manual')
        sys.exit(0 if success else 1)
    
    elif args.action == 'reset_all':
        # 重置所有容器
        stats = scheduler.reset_all(force=args.force)
        if 'error' in stats:
            sys.exit(1)
        elif stats['failed'] > 0:
            sys.exit(1)
        else:
            sys.exit(0)
    
    elif args.action == 'reset_due':
        # 重置到期容器（默认）
        stats = scheduler.reset_due_containers()
        if stats['failed'] > 0:
            sys.exit(1)
        else:
            sys.exit(0)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        logger.info("调度器被用户中断")
        sys.exit(130)
    except Exception as e:
        logger.error(f"调度器异常: {e}", exc_info=True)
        sys.exit(1)

