#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
流量管理数据库升级脚本
添加累计流量字段以支持重启后流量连续性
"""

import sqlite3
import logging
import os
import sys

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def upgrade_database(db_path: str = "flow_management.db"):
    """升级数据库结构"""
    try:
        if not os.path.exists(db_path):
            logger.info(f"数据库文件 {db_path} 不存在，无需升级")
            return True
        
        with sqlite3.connect(db_path) as conn:
            # 检查当前表结构
            cursor = conn.execute("PRAGMA table_info(container_flow_management)")
            columns = [column[1] for column in cursor.fetchall()]
            
            logger.info(f"当前数据库字段: {columns}")
            
            # 检查是否需要添加累计流量字段
            need_upgrade = False
            
            if 'accumulated_bytes_received' not in columns:
                logger.info("添加 accumulated_bytes_received 字段...")
                conn.execute("ALTER TABLE container_flow_management ADD COLUMN accumulated_bytes_received BIGINT DEFAULT 0")
                need_upgrade = True
            
            if 'accumulated_bytes_sent' not in columns:
                logger.info("添加 accumulated_bytes_sent 字段...")
                conn.execute("ALTER TABLE container_flow_management ADD COLUMN accumulated_bytes_sent BIGINT DEFAULT 0")
                need_upgrade = True
            
            if need_upgrade:
                logger.info("✅ 数据库升级完成")
                
                # 显示升级后的表结构
                cursor = conn.execute("PRAGMA table_info(container_flow_management)")
                new_columns = [column[1] for column in cursor.fetchall()]
                logger.info(f"升级后数据库字段: {new_columns}")
                
                # 显示现有数据
                cursor = conn.execute("SELECT COUNT(*) FROM container_flow_management")
                count = cursor.fetchone()[0]
                logger.info(f"现有容器记录数: {count}")
                
            else:
                logger.info("✅ 数据库已是最新版本，无需升级")
            
            return True
            
    except Exception as e:
        logger.error(f"升级数据库失败: {e}")
        return False

def main():
    """主函数"""
    db_path = "flow_management.db"
    
    if len(sys.argv) > 1:
        db_path = sys.argv[1]
    
    logger.info(f"开始升级数据库: {db_path}")
    
    if upgrade_database(db_path):
        logger.info("数据库升级成功")
        sys.exit(0)
    else:
        logger.error("数据库升级失败")
        sys.exit(1)

if __name__ == "__main__":
    main()
