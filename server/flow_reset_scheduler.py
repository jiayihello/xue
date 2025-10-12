#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
import os
import logging
import sqlite3
from datetime import datetime

# 添加当前目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flow_manager import FlowManager
from lxc_manager import LXCManager
from config_handler import app_config

# 配置日志
logging.basicConfig(
    level=getattr(logging, app_config.log_level.upper(), logging.INFO),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('flow_reset.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

def auto_reset_flows():
    """自动重置到期的容器流量"""
    logger.info("开始执行自动流量重置任务")
    
    try:
        flow_manager = FlowManager()
        lxc_manager = LXCManager()
        
        # 获取需要重置流量的容器
        containers_to_reset = flow_manager.get_containers_need_reset()
        
        if not containers_to_reset:
            logger.info("没有需要重置流量的容器")
            return
        
        logger.info(f"发现 {len(containers_to_reset)} 个容器需要重置流量: {containers_to_reset}")
        
        success_count = 0
        failed_count = 0
        
        for hostname in containers_to_reset:
            try:
                logger.info(f"正在重置容器 {hostname} 的流量...")
                
                # 获取容器当前流量统计
                container_info = lxc_manager.get_container_info(hostname)
                if container_info['code'] != 200:
                    logger.warning(f"无法获取容器 {hostname} 信息: {container_info['msg']}")
                    failed_count += 1
                    continue
                
                # 获取LXD容器对象以读取网络统计
                container = lxc_manager._get_container_or_error(hostname)
                if not container:
                    logger.warning(f"容器 {hostname} 不存在，从流量管理系统中清理")
                    # 自动清理已删除的容器记录
                    if flow_manager.unregister_container(hostname):
                        logger.info(f"已清理删除容器 {hostname} 的流量管理记录")
                    failed_count += 1
                    continue
                
                # 获取当前网络统计
                state = container.state()
                current_bytes_received = 0
                current_bytes_sent = 0
                
                if state.network:
                    for nic_name, nic_data in state.network.items():
                        if 'counters' in nic_data:
                            current_bytes_received += nic_data['counters'].get('bytes_received', 0)
                            current_bytes_sent += nic_data['counters'].get('bytes_sent', 0)
                
                # 执行流量重置
                if flow_manager.reset_container_flow(
                    hostname, 
                    current_bytes_received, 
                    current_bytes_sent, 
                    reset_type='auto'
                ):
                    logger.info(f"✅ 容器 {hostname} 流量重置成功")
                    success_count += 1
                else:
                    logger.error(f"❌ 容器 {hostname} 流量重置失败")
                    failed_count += 1
                    
            except Exception as e:
                logger.error(f"重置容器 {hostname} 流量时发生异常: {e}", exc_info=True)
                failed_count += 1
        
        logger.info(f"自动流量重置任务完成: 成功 {success_count}, 失败 {failed_count}")
        
    except Exception as e:
        logger.error(f"执行自动流量重置任务时发生异常: {e}", exc_info=True)

def register_existing_containers():
    """将现有容器注册到流量管理系统"""
    logger.info("开始注册现有容器到流量管理系统")
    
    try:
        flow_manager = FlowManager()
        lxc_manager = LXCManager()
        
        # 获取所有容器
        all_containers = lxc_manager.client.containers.all()
        
        registered_count = 0
        skipped_count = 0
        
        for container in all_containers:
            hostname = container.name
            
            # 检查是否已经注册
            if flow_manager.get_container_flow_info(hostname):
                logger.debug(f"容器 {hostname} 已在流量管理系统中注册，跳过")
                skipped_count += 1
                continue
            
            try:
                # 获取容器信息
                container_info = lxc_manager.get_container_info(hostname)
                if container_info['code'] != 200:
                    logger.warning(f"无法获取容器 {hostname} 信息，跳过注册")
                    continue
                
                # 获取流量限制
                flow_limit_gb = int(lxc_manager._get_user_metadata(container, 'flow_limit_gb', 0))
                
                # 使用容器创建时间作为开通日期
                try:
                    if container.created_at:
                        if isinstance(container.created_at, str):
                            # 解析ISO格式的时间字符串
                            created_datetime = datetime.fromisoformat(container.created_at.replace('Z', '+00:00'))
                            created_date = created_datetime.date()
                        else:
                            created_date = container.created_at.date()
                    else:
                        created_date = datetime.now().date()
                except Exception as e:
                    logger.warning(f"解析容器 {hostname} 创建时间失败: {e}，使用当前日期")
                    created_date = datetime.now().date()
                
                # 注册到流量管理系统
                if flow_manager.register_container(hostname, flow_limit_gb, created_date):
                    logger.info(f"✅ 容器 {hostname} 已注册到流量管理系统")
                    registered_count += 1
                else:
                    logger.error(f"❌ 容器 {hostname} 注册失败")
                    
            except Exception as e:
                logger.error(f"注册容器 {hostname} 时发生异常: {e}")
        
        logger.info(f"容器注册完成: 新注册 {registered_count}, 已存在 {skipped_count}")
        
    except Exception as e:
        logger.error(f"注册现有容器时发生异常: {e}", exc_info=True)

def cleanup_deleted_containers():
    """清理已删除容器的流量管理记录"""
    logger.info("开始清理已删除容器的流量管理记录")

    try:
        flow_manager = FlowManager()
        lxc_manager = LXCManager()

        # 获取所有在流量管理系统中的容器
        with sqlite3.connect(flow_manager.db_path) as conn:
            cursor = conn.execute("SELECT hostname FROM container_flow_management")
            managed_containers = [row[0] for row in cursor.fetchall()]

        if not managed_containers:
            logger.info("流量管理系统中没有容器记录")
            return

        # 获取所有实际存在的容器
        existing_containers = [c.name for c in lxc_manager.client.containers.all()]

        # 找出已删除的容器
        deleted_containers = set(managed_containers) - set(existing_containers)

        if not deleted_containers:
            logger.info("没有发现已删除的容器记录")
            return

        logger.info(f"发现 {len(deleted_containers)} 个已删除的容器记录: {list(deleted_containers)}")

        cleaned_count = 0
        for hostname in deleted_containers:
            if flow_manager.unregister_container(hostname):
                logger.info(f"✅ 已清理容器 {hostname} 的流量管理记录")
                cleaned_count += 1
            else:
                logger.error(f"❌ 清理容器 {hostname} 记录失败")

        logger.info(f"清理完成: 成功清理 {cleaned_count} 个记录")

    except Exception as e:
        logger.error(f"清理已删除容器记录时发生异常: {e}", exc_info=True)

def main():
    """主函数"""
    if len(sys.argv) > 1:
        command = sys.argv[1]
        if command == 'register':
            register_existing_containers()
        elif command == 'reset':
            auto_reset_flows()
        elif command == 'cleanup':
            cleanup_deleted_containers()
        else:
            print("用法:")
            print("  python3 flow_reset_scheduler.py register  # 注册现有容器")
            print("  python3 flow_reset_scheduler.py reset     # 执行流量重置")
            print("  python3 flow_reset_scheduler.py cleanup   # 清理已删除容器记录")
    else:
        # 默认执行流量重置
        auto_reset_flows()

if __name__ == "__main__":
    main()
