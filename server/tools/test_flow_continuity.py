#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
流量连续性测试脚本
验证重启后流量统计的连续性
"""

import sys
import os
import logging
from datetime import datetime

# 添加当前目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flow_manager import FlowManager

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def test_flow_continuity():
    """测试流量连续性"""
    logger.info("开始测试流量连续性功能")
    
    # 创建测试用的流量管理器
    flow_manager = FlowManager("test_flow_management.db")
    
    test_hostname = "test-container"
    
    try:
        # 1. 注册测试容器
        logger.info("步骤1: 注册测试容器")
        if flow_manager.register_container(test_hostname, 100):
            logger.info("✅ 容器注册成功")
        else:
            logger.error("❌ 容器注册失败")
            return False
        
        # 2. 模拟容器运行一段时间，产生流量
        logger.info("步骤2: 模拟容器产生流量")
        simulated_received = 1000000000  # 1GB
        simulated_sent = 500000000       # 0.5GB
        
        usage1 = flow_manager.calculate_current_period_usage(test_hostname, simulated_received, simulated_sent)
        logger.info(f"初始流量使用: {usage1} GB")
        
        # 3. 模拟容器重启（流量计数器归零）
        logger.info("步骤3: 模拟容器重启")
        restart_received = 0  # 重启后LXD计数器归零
        restart_sent = 0
        
        usage2 = flow_manager.calculate_current_period_usage(test_hostname, restart_received, restart_sent)
        logger.info(f"重启后流量使用: {usage2} GB")
        
        # 4. 模拟重启后继续产生流量
        logger.info("步骤4: 模拟重启后继续产生流量")
        after_restart_received = 200000000  # 0.2GB
        after_restart_sent = 100000000       # 0.1GB
        
        usage3 = flow_manager.calculate_current_period_usage(test_hostname, after_restart_received, after_restart_sent)
        logger.info(f"重启后新增流量使用: {usage3} GB")
        
        # 5. 验证流量连续性
        logger.info("步骤5: 验证流量连续性")
        expected_total = usage1 + (after_restart_received + after_restart_sent) / (1024**3)
        
        logger.info(f"预期总流量: {expected_total:.2f} GB")
        logger.info(f"实际总流量: {usage3:.2f} GB")
        
        if abs(usage3 - expected_total) < 0.01:  # 允许小数点误差
            logger.info("✅ 流量连续性测试通过")
            success = True
        else:
            logger.error("❌ 流量连续性测试失败")
            success = False
        
        # 6. 查看流量管理信息
        logger.info("步骤6: 查看流量管理信息")
        flow_info = flow_manager.get_container_flow_info(test_hostname)
        if flow_info:
            logger.info(f"容器信息: {flow_info}")
        
        # 7. 查看重置历史
        logger.info("步骤7: 查看重置历史")
        history = flow_manager.get_flow_reset_history(test_hostname)
        for record in history:
            logger.info(f"历史记录: {record}")
        
        return success
        
    except Exception as e:
        logger.error(f"测试过程中发生异常: {e}", exc_info=True)
        return False
    
    finally:
        # 清理测试数据
        logger.info("清理测试数据")
        flow_manager.unregister_container(test_hostname)
        
        # 删除测试数据库
        test_db_path = "test_flow_management.db"
        if os.path.exists(test_db_path):
            os.remove(test_db_path)
            logger.info("测试数据库已删除")

def test_database_upgrade():
    """测试数据库升级功能"""
    logger.info("测试数据库升级功能")
    
    from upgrade_flow_database import upgrade_database
    
    # 创建一个旧版本的数据库
    test_db = "test_old_db.db"
    
    try:
        import sqlite3
        with sqlite3.connect(test_db) as conn:
            # 创建旧版本表结构（没有累计字段）
            conn.execute("""
                CREATE TABLE container_flow_management (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    hostname VARCHAR(255) NOT NULL UNIQUE,
                    created_date DATE NOT NULL,
                    last_reset_date DATE,
                    next_reset_date DATE NOT NULL,
                    flow_limit_gb INTEGER DEFAULT 0,
                    baseline_bytes_received BIGINT DEFAULT 0,
                    baseline_bytes_sent BIGINT DEFAULT 0,
                    current_period_start DATE NOT NULL,
                    reset_count INTEGER DEFAULT 0,
                    auto_reset_enabled BOOLEAN DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # 插入测试数据
            conn.execute("""
                INSERT INTO container_flow_management 
                (hostname, created_date, next_reset_date, current_period_start)
                VALUES ('test-old', '2025-01-01', '2025-02-01', '2025-01-01')
            """)
        
        logger.info("创建旧版本数据库完成")
        
        # 执行升级
        if upgrade_database(test_db):
            logger.info("✅ 数据库升级测试通过")
            return True
        else:
            logger.error("❌ 数据库升级测试失败")
            return False
            
    except Exception as e:
        logger.error(f"数据库升级测试异常: {e}")
        return False
    
    finally:
        # 清理测试文件
        if os.path.exists(test_db):
            os.remove(test_db)

def main():
    """主函数"""
    logger.info("=" * 60)
    logger.info("流量连续性功能测试")
    logger.info("=" * 60)
    
    success = True
    
    # 测试1: 流量连续性
    if not test_flow_continuity():
        success = False
    
    logger.info("-" * 40)
    
    # 测试2: 数据库升级
    if not test_database_upgrade():
        success = False
    
    logger.info("=" * 60)
    if success:
        logger.info("✅ 所有测试通过")
        sys.exit(0)
    else:
        logger.error("❌ 部分测试失败")
        sys.exit(1)

if __name__ == "__main__":
    main()
