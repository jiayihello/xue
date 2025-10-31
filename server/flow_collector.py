#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
流量收集器
定期从 iptables 读取流量统计并更新到数据库
建议每分钟运行一次（通过 systemd timer 或 cron）
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
        'flow_collector.log',
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


class FlowCollector:
    """流量收集器"""
    
    def __init__(self):
        """初始化收集器"""
        self.iptables_mgr = IptablesManager()
        self.flow_mgr = FlowManagerV2()
    
    def collect_all(self) -> dict:
        """
        收集所有容器的流量并更新到数据库（批量优化版）
        
        Returns:
            收集统计信息
        """
        import time
        start_time = time.time()
        
        logger.info("开始收集流量统计（批量模式）...")
        
        stats = {
            'total': 0,
            'success': 0,
            'failed': 0,
            'skipped': 0,
            'errors': [],
            'duration_seconds': 0,
            'containers_per_second': 0,
            'iptables_calls': 2  # 批量模式只调用2次iptables (IPv4+IPv6)
        }
        
        # 获取所有已注册的容器
        containers = self.flow_mgr.list_all_containers()
        stats['total'] = len(containers)
        
        if stats['total'] == 0:
            logger.warning("没有已注册的容器")
            return stats
        
        logger.info(f"找到 {stats['total']} 个已注册容器")
        
        # 🚀 性能优化：批量获取所有容器的流量统计（只调用2次iptables）
        try:
            all_traffic_stats = self.iptables_mgr.get_all_traffic_stats()
            logger.debug(f"批量获取流量统计成功，共 {len(all_traffic_stats)} 个容器有数据")
        except Exception as e:
            logger.error(f"批量获取流量统计失败: {e}")
            all_traffic_stats = {}
        
        # 获取所有配置了 iptables 规则的容器
        iptables_containers = self.iptables_mgr.list_all_rules()
        
        # 逐个容器更新数据库
        for container in containers:
            hostname = container['hostname']
            
            # 检查是否有 iptables 规则
            if hostname not in iptables_containers:
                logger.debug(f"容器 {hostname} 未配置 iptables 规则，跳过")
                stats['skipped'] += 1
                continue
            
            try:
                # 从批量结果中获取流量统计（无需额外iptables调用）
                traffic_stats = all_traffic_stats.get(hostname, {'bytes_sent': 0, 'bytes_received': 0})
                
                # 计算总流量（发送 + 接收）
                total_bytes = traffic_stats['bytes_sent'] + traffic_stats['bytes_received']
                
                # 更新到数据库
                success = self.flow_mgr.update_flow(hostname, total_bytes)
                
                if success:
                    stats['success'] += 1
                    
                    # 记录详细信息（仅当有流量变化时）
                    if total_bytes > 0:
                        sent_mb = traffic_stats['bytes_sent'] / 1024 / 1024
                        recv_mb = traffic_stats['bytes_received'] / 1024 / 1024
                        logger.debug(f"容器 {hostname}: 发送 {sent_mb:.2f}MB, "
                                   f"接收 {recv_mb:.2f}MB, 总计 {total_bytes} bytes")
                else:
                    stats['failed'] += 1
                    stats['errors'].append(f"{hostname}: 更新数据库失败")
                    
            except Exception as e:
                stats['failed'] += 1
                error_msg = f"{hostname}: {str(e)}"
                stats['errors'].append(error_msg)
                logger.error(f"收集容器 {hostname} 流量失败: {e}")
        
        # 计算性能指标
        import time
        stats['duration_seconds'] = round(time.time() - start_time, 2)
        if stats['total'] > 0 and stats['duration_seconds'] > 0:
            stats['containers_per_second'] = round(stats['total'] / stats['duration_seconds'], 2)
        
        # 输出统计（包含优化指标）
        logger.info(f"收集完成: 总数={stats['total']}, 成功={stats['success']}, "
                   f"失败={stats['failed']}, 跳过={stats['skipped']}, "
                   f"耗时={stats['duration_seconds']}秒 ({stats['containers_per_second']}容器/秒), "
                   f"iptables调用={stats['iptables_calls']}次")
        
        if stats['errors']:
            logger.warning(f"遇到 {len(stats['errors'])} 个错误:")
            for error in stats['errors'][:10]:  # 最多显示10个
                logger.warning(f"  - {error}")
        
        return stats
    
    def collect_one(self, hostname: str) -> bool:
        """
        收集单个容器的流量
        
        Args:
            hostname: 容器主机名
            
        Returns:
            是否成功
        """
        logger.info(f"收集容器 {hostname} 的流量...")
        
        try:
            # 获取流量统计
            traffic_stats = self.iptables_mgr.get_traffic_stats(hostname)
            total_bytes = traffic_stats['bytes_sent'] + traffic_stats['bytes_received']
            
            # 更新数据库
            success = self.flow_mgr.update_flow(hostname, total_bytes)
            
            if success:
                sent_gb = traffic_stats['bytes_sent'] / 1024 / 1024 / 1024
                recv_gb = traffic_stats['bytes_received'] / 1024 / 1024 / 1024
                logger.info(f"✓ 容器 {hostname}: 发送 {sent_gb:.3f}GB, "
                          f"接收 {recv_gb:.3f}GB")
            else:
                logger.error(f"✗ 容器 {hostname}: 更新数据库失败")
            
            return success
            
        except Exception as e:
            logger.error(f"收集容器 {hostname} 流量失败: {e}")
            return False
    
    def show_status(self):
        """显示当前状态"""
        logger.info("=" * 70)
        logger.info("流量收集器状态")
        logger.info("=" * 70)
        
        # 数据库中的容器
        containers = self.flow_mgr.list_all_containers()
        logger.info(f"数据库中的容器: {len(containers)}")
        
        # iptables 规则中的容器
        iptables_containers = self.iptables_mgr.list_all_rules()
        logger.info(f"iptables 规则中的容器: {len(iptables_containers)}")
        
        # 找出差异
        db_hostnames = set(c['hostname'] for c in containers)
        ipt_hostnames = set(iptables_containers)
        
        missing_rules = db_hostnames - ipt_hostnames
        orphan_rules = ipt_hostnames - db_hostnames
        
        if missing_rules:
            logger.warning(f"缺少 iptables 规则的容器 ({len(missing_rules)}个):")
            for hostname in sorted(missing_rules)[:10]:
                logger.warning(f"  - {hostname}")
        
        if orphan_rules:
            logger.warning(f"孤儿 iptables 规则 ({len(orphan_rules)}个):")
            for hostname in sorted(orphan_rules)[:10]:
                logger.warning(f"  - {hostname}")
        
        if not missing_rules and not orphan_rules:
            logger.info("✓ 所有容器的 iptables 规则都已配置")
        
        logger.info("=" * 70)


def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description='流量收集器')
    parser.add_argument('--hostname', help='只收集指定容器')
    parser.add_argument('--status', action='store_true', help='显示状态')
    parser.add_argument('--verbose', '-v', action='store_true', help='详细输出')
    
    args = parser.parse_args()
    
    # 设置日志级别
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    collector = FlowCollector()
    
    if args.status:
        # 显示状态
        collector.show_status()
    elif args.hostname:
        # 收集单个容器
        success = collector.collect_one(args.hostname)
        sys.exit(0 if success else 1)
    else:
        # 收集所有容器
        stats = collector.collect_all()
        
        # 根据结果设置退出码
        if stats['failed'] > 0:
            sys.exit(1)
        else:
            sys.exit(0)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        logger.info("收集被用户中断")
        sys.exit(130)
    except Exception as e:
        logger.error(f"收集器异常: {e}", exc_info=True)
        sys.exit(1)

