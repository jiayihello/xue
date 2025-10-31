#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据迁移工具
将旧流量监控系统的数据迁移到新的 iptables 系统
"""

import os
import sqlite3
import logging
import sys
from datetime import date, timedelta
from flow_manager_v2 import FlowManagerV2
from iptables_manager import IptablesManager
from lxc_manager import LXCManager

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('migration.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class MigrationTool:
    """数据迁移工具"""
    
    def __init__(self, old_db_path: str = 'flow_management.db'):
        """
        初始化迁移工具
        
        Args:
            old_db_path: 旧数据库路径
        """
        self.old_db_path = old_db_path
        self.flow_mgr = FlowManagerV2()
        self.iptables_mgr = IptablesManager()
        self.lxc_mgr = LXCManager()
    
    def check_old_database(self) -> bool:
        """
        检查旧数据库是否存在
        
        Returns:
            是否存在
        """
        if not os.path.exists(self.old_db_path):
            logger.error(f"旧数据库文件不存在: {self.old_db_path}")
            return False
        
        logger.info(f"找到旧数据库: {self.old_db_path}")
        return True
    
    def read_old_data(self) -> list:
        """
        从旧数据库读取数据
        
        Returns:
            容器数据列表
        """
        logger.info("读取旧数据库...")
        
        containers = []
        
        try:
            # 🔥 修复：使用 with 语句管理连接，确保异常情况下也能正确关闭
            with sqlite3.connect(self.old_db_path) as conn:
                conn.row_factory = sqlite3.Row
                
                # 尝试读取旧表
                rows = conn.execute("""
                    SELECT hostname, flow_limit_gb, next_reset_date
                    FROM container_flow_management
                """).fetchall()
                
                for row in rows:
                    containers.append({
                        'hostname': row['hostname'],
                        'limit_gb': row['flow_limit_gb'],
                        'next_reset_date': row['next_reset_date']
                    })
            
            logger.info(f"从旧数据库读取到 {len(containers)} 条记录")
            
        except sqlite3.Error as e:
            logger.error(f"读取旧数据库失败: {e}")
            return []
        
        return containers
    
    def migrate(self, dry_run: bool = False) -> dict:
        """
        执行迁移
        
        Args:
            dry_run: 是否只是测试（不实际写入）
            
        Returns:
            迁移统计信息
        """
        logger.info("=" * 70)
        logger.info(f"开始迁移{'（测试模式）' if dry_run else ''}...")
        logger.info("=" * 70)
        
        stats = {
            'total': 0,
            'migrated': 0,
            'skipped': 0,
            'failed': 0,
            'errors': []
        }
        
        # 检查旧数据库
        if not self.check_old_database():
            return stats
        
        # 读取旧数据
        old_containers = self.read_old_data()
        stats['total'] = len(old_containers)
        
        if stats['total'] == 0:
            logger.warning("旧数据库中没有数据")
            return stats
        
        # 获取当前运行的容器
        running_containers = set(self.lxc_mgr.list_all_containers())
        
        # 迁移每个容器
        for container in old_containers:
            hostname = container['hostname']
            limit_gb = container['limit_gb']
            next_reset_date = container['next_reset_date']
            
            try:
                # 检查新数据库中是否已存在
                existing = self.flow_mgr.get_container_usage(hostname)
                if existing:
                    logger.info(f"容器 {hostname} 已存在于新数据库，跳过")
                    stats['skipped'] += 1
                    continue
                
                # 检查容器是否在运行
                container_name = self.lxc_mgr.get_container_name_by_hostname(hostname)
                is_running = container_name and container_name in running_containers
                
                if not dry_run:
                    # 注册到新数据库
                    logger.info(f"迁移容器 {hostname}: limit={limit_gb}GB, "
                              f"reset_date={next_reset_date}")
                    
                    # 先注册容器（会自动计算重置日期）
                    self.flow_mgr.register_container(
                        hostname=hostname,
                        flow_limit_gb=limit_gb
                    )
                    
                    # 然后设置正确的重置日期（从旧数据迁移）
                    from datetime import datetime
                    reset_date_obj = datetime.strptime(next_reset_date, '%Y-%m-%d').date()
                    self.flow_mgr.set_next_reset_date(hostname, reset_date_obj)
                    
                    # 如果容器在运行，添加 iptables 规则
                    if is_running:
                        logger.info(f"容器 {hostname} 正在运行，添加 iptables 规则")
                        self.iptables_mgr.ensure_container_rules(hostname)
                    
                    stats['migrated'] += 1
                    logger.info(f"✓ 容器 {hostname} 迁移完成")
                else:
                    # 测试模式
                    logger.info(f"[测试] 将迁移 {hostname}: limit={limit_gb}GB, "
                              f"reset_date={next_reset_date}, "
                              f"running={is_running}")
                    stats['migrated'] += 1
            
            except Exception as e:
                stats['failed'] += 1
                error_msg = f"{hostname}: {str(e)}"
                stats['errors'].append(error_msg)
                logger.error(f"迁移容器 {hostname} 失败: {e}")
        
        # 输出统计
        logger.info("=" * 70)
        logger.info(f"迁移完成:")
        logger.info(f"  总记录数: {stats['total']}")
        logger.info(f"  已迁移: {stats['migrated']}")
        logger.info(f"  跳过: {stats['skipped']}")
        logger.info(f"  失败: {stats['failed']}")
        
        if stats['errors']:
            logger.warning(f"错误详情:")
            for error in stats['errors'][:10]:
                logger.warning(f"  - {error}")
        
        logger.info("=" * 70)
        
        if not dry_run and stats['migrated'] > 0:
            logger.info("\n建议:")
            logger.info("  1. 运行 'python3 flow_collector.py' 开始收集流量")
            logger.info("  2. 运行 'python3 flow_limit_enforcer.py status' 检查状态")
            logger.info("  3. 备份旧数据库后删除或重命名")
        
        return stats
    
    def backup_old_database(self) -> bool:
        """
        备份旧数据库
        
        Returns:
            是否成功
        """
        if not os.path.exists(self.old_db_path):
            logger.error(f"旧数据库不存在: {self.old_db_path}")
            return False
        
        from datetime import datetime
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_path = f"{self.old_db_path}.backup_{timestamp}"
        
        try:
            import shutil
            shutil.copy2(self.old_db_path, backup_path)
            logger.info(f"✓ 旧数据库已备份到: {backup_path}")
            return True
        except Exception as e:
            logger.error(f"备份失败: {e}")
            return False


def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description='数据迁移工具')
    parser.add_argument('action', nargs='?', default='migrate',
                       choices=['migrate', 'check', 'backup'],
                       help='操作类型')
    parser.add_argument('--old-db', default='flow_management.db',
                       help='旧数据库路径')
    parser.add_argument('--dry-run', action='store_true',
                       help='测试模式（不实际写入）')
    parser.add_argument('--verbose', '-v', action='store_true', help='详细输出')
    
    args = parser.parse_args()
    
    # 设置日志级别
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    tool = MigrationTool(old_db_path=args.old_db)
    
    if args.action == 'check':
        # 检查旧数据库
        if tool.check_old_database():
            containers = tool.read_old_data()
            logger.info(f"旧数据库中有 {len(containers)} 条记录")
            if containers:
                logger.info("\n前 5 条记录:")
                for c in containers[:5]:
                    logger.info(f"  - {c['hostname']}: {c['limit_gb']}GB, "
                              f"reset_date={c['next_reset_date']}")
            sys.exit(0)
        else:
            sys.exit(1)
    
    elif args.action == 'backup':
        # 备份旧数据库
        success = tool.backup_old_database()
        sys.exit(0 if success else 1)
    
    elif args.action == 'migrate':
        # 执行迁移
        if not args.dry_run:
            logger.warning("即将开始迁移，建议先运行 --dry-run 测试")
            logger.warning("按 Ctrl+C 取消，或等待 5 秒继续...")
            import time
            try:
                time.sleep(5)
            except KeyboardInterrupt:
                logger.info("迁移已取消")
                sys.exit(0)
        
        stats = tool.migrate(dry_run=args.dry_run)
        
        if stats['failed'] > 0:
            sys.exit(1)
        else:
            sys.exit(0)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        logger.info("迁移被用户中断")
        sys.exit(130)
    except Exception as e:
        logger.error(f"迁移异常: {e}", exc_info=True)
        sys.exit(1)

