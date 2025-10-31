#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LXD 事件监听器
监听 LXD 容器的创建、删除等事件，自动更新 iptables 规则和数据库
"""

import json
import logging
import subprocess
import sys
import time
from datetime import date, timedelta
from typing import Optional
from flow_manager_v2 import FlowManagerV2
from iptables_manager import IptablesManager
from lxc_manager import LXCManager

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('lxd_events.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class LXDEventListener:
    """LXD 事件监听器"""
    
    def __init__(self):
        """初始化监听器"""
        self.flow_mgr = FlowManagerV2()
        self.iptables_mgr = IptablesManager()
        self.lxc_mgr = LXCManager()
    
    def handle_container_created(self, hostname: str):
        """
        处理容器创建事件
        
        Args:
            hostname: 容器主机名
        """
        logger.info(f"容器已创建: {hostname}")
        
        try:
            # 等待容器启动并获得IP
            time.sleep(2)
            
            # 检查数据库中是否已存在
            info = self.flow_mgr.get_container_usage(hostname)
            if info:
                logger.info(f"容器 {hostname} 已在数据库中，更新 iptables 规则")
                # 只需添加 iptables 规则
                self.iptables_mgr.ensure_container_rules(hostname)
            else:
                logger.info(f"容器 {hostname} 是新容器，初始化流量记录")
                
                # 尝试从容器元数据中读取流量限制（魔方财务会设置这个值）
                limit_gb = 0  # 默认无限制
                try:
                    container_name = self.lxc_mgr.get_container_name_by_hostname(hostname)
                    if container_name:
                        container = self.lxc_mgr.client.containers.get(container_name)
                        flow_limit_str = container.config.get('user.flow_limit_gb', '0')
                        limit_gb = int(flow_limit_str) if flow_limit_str else 0
                        if limit_gb > 0:
                            logger.info(f"从容器元数据读取到流量限制: {limit_gb}GB")
                except Exception as e:
                    logger.warning(f"读取容器元数据失败，使用默认值: {e}")
                
                # 创建新记录（next_reset_date 由方法自动计算）
                self.flow_mgr.register_container(
                    hostname=hostname,
                    flow_limit_gb=limit_gb
                )
                # 添加 iptables 规则
                self.iptables_mgr.ensure_container_rules(hostname)
                logger.info(f"✓ 容器 {hostname} 已注册，流量限制: {limit_gb}GB")
        
        except Exception as e:
            logger.error(f"处理容器创建事件失败 ({hostname}): {e}")
    
    def handle_container_deleted(self, hostname: str):
        """
        处理容器删除事件
        
        Args:
            hostname: 容器主机名
        """
        logger.info(f"容器已删除: {hostname}")
        
        try:
            # 删除 iptables 规则
            self.iptables_mgr.remove_container_rules(hostname)
            
            # 注意：不删除数据库记录，保留历史数据
            logger.info(f"✓ 容器 {hostname} 的 iptables 规则已清理")
        
        except Exception as e:
            logger.error(f"处理容器删除事件失败 ({hostname}): {e}")
    
    def handle_container_started(self, hostname: str):
        """
        处理容器启动事件
        
        Args:
            hostname: 容器主机名
        """
        logger.info(f"容器已启动: {hostname}")
        
        try:
            # 等待容器获得IP
            time.sleep(1)
            
            # 🔥 修复：确保 iptables 规则存在并检查返回值
            success = self.iptables_mgr.ensure_container_rules(hostname)
            if not success:
                logger.error(f"容器 {hostname} 规则创建失败，跳过封禁检查")
                return
            
            # 如果容器超限，重新应用封禁
            info = self.flow_mgr.get_container_usage(hostname)
            if info and info['is_blocked']:
                logger.info(f"容器 {hostname} 已超限，重新应用封禁")
                block_success = self.iptables_mgr.block_container(hostname)
                if not block_success:
                    logger.error(f"容器 {hostname} 重新封禁失败")
                else:
                    logger.info(f"✓ 容器 {hostname} 已重新封禁")
            
            logger.info(f"✓ 容器 {hostname} 启动处理完成")
        
        except Exception as e:
            logger.error(f"处理容器启动事件失败 ({hostname}): {e}")
    
    def handle_container_stopped(self, hostname: str):
        """
        处理容器停止事件
        
        Args:
            hostname: 容器主机名
        """
        logger.debug(f"容器已停止: {hostname}")
        # 停止时无需特殊处理，iptables 规则保留
    
    def listen(self):
        """
        监听 LXD 事件流
        """
        logger.info("开始监听 LXD 事件...")
        
        try:
            # 使用 lxc monitor 监听事件
            process = subprocess.Popen(
                ['lxc', 'monitor', '--type=lifecycle'],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True,
                bufsize=1
            )
            
            logger.info("LXD 事件监听器已启动")
            
            for line in process.stdout:
                line = line.strip()
                if not line:
                    continue
                
                try:
                    # 解析事件
                    event = json.loads(line)
                    self.process_event(event)
                
                except json.JSONDecodeError:
                    logger.debug(f"无法解析事件: {line}")
                except Exception as e:
                    logger.error(f"处理事件失败: {e}")
            
            # 如果 monitor 意外退出
            stderr = process.stderr.read()
            if stderr:
                logger.error(f"lxc monitor 错误: {stderr}")
        
        except KeyboardInterrupt:
            logger.info("监听器被用户中断")
        except Exception as e:
            logger.error(f"监听器异常: {e}", exc_info=True)
    
    def process_event(self, event: dict):
        """
        处理单个事件
        
        Args:
            event: 事件字典
        """
        try:
            metadata = event.get('metadata', {})
            action = metadata.get('action', '')
            name = metadata.get('name', '')
            
            if not name:
                return
            
            # 从容器名获取 hostname
            hostname = self.lxc_mgr.get_container_hostname(name)
            if not hostname:
                logger.debug(f"无法获取容器 {name} 的 hostname，跳过")
                return
            
            # 根据动作类型处理
            if action == 'created':
                self.handle_container_created(hostname)
            elif action == 'deleted':
                self.handle_container_deleted(hostname)
            elif action == 'started':
                self.handle_container_started(hostname)
            elif action == 'stopped':
                self.handle_container_stopped(hostname)
            else:
                logger.debug(f"忽略事件: {action} ({name})")
        
        except Exception as e:
            logger.error(f"处理事件失败: {e}")
    
    def sync_all_containers(self):
        """
        同步所有现有容器（初始化或修复时使用）
        """
        logger.info("开始同步所有容器...")
        
        try:
            # 获取所有运行中的容器
            containers = self.lxc_mgr.list_all_containers()
            
            logger.info(f"找到 {len(containers)} 个容器")
            
            for container_name in containers:
                try:
                    hostname = self.lxc_mgr.get_container_hostname(container_name)
                    if not hostname:
                        logger.warning(f"容器 {container_name} 无法获取 hostname，跳过")
                        continue
                    
                    # 检查数据库
                    info = self.flow_mgr.get_container_usage(hostname)
                    if not info:
                        logger.info(f"注册新容器: {hostname}")
                        
                        # 尝试从容器元数据中读取流量限制
                        limit_gb = 0
                        try:
                            container = self.lxc_mgr.client.containers.get(container_name)
                            flow_limit_str = container.config.get('user.flow_limit_gb', '0')
                            limit_gb = int(flow_limit_str) if flow_limit_str else 0
                            if limit_gb > 0:
                                logger.info(f"从容器元数据读取到流量限制: {limit_gb}GB")
                        except Exception as e:
                            logger.warning(f"读取容器 {container_name} 元数据失败: {e}")
                        
                        # next_reset_date 由方法自动计算（创建后30天）
                        self.flow_mgr.register_container(
                            hostname=hostname,
                            flow_limit_gb=limit_gb
                        )
                    
                    # 确保 iptables 规则
                    self.iptables_mgr.ensure_container_rules(hostname)
                    
                    logger.info(f"✓ 容器 {hostname} 已同步")
                
                except Exception as e:
                    logger.error(f"同步容器 {container_name} 失败: {e}")
            
            logger.info("容器同步完成")
        
        except Exception as e:
            logger.error(f"同步失败: {e}")


def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description='LXD 事件监听器')
    parser.add_argument('action', nargs='?', default='listen',
                       choices=['listen', 'sync'],
                       help='操作类型')
    parser.add_argument('--verbose', '-v', action='store_true', help='详细输出')
    
    args = parser.parse_args()
    
    # 设置日志级别
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    listener = LXDEventListener()
    
    if args.action == 'sync':
        # 同步所有容器
        listener.sync_all_containers()
        sys.exit(0)
    
    elif args.action == 'listen':
        # 持续监听
        listener.listen()


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        logger.info("监听器被用户中断")
        sys.exit(130)
    except Exception as e:
        logger.error(f"监听器异常: {e}", exc_info=True)
        sys.exit(1)

