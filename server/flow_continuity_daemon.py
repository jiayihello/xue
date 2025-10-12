#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
流量连续性守护进程
定期检查所有容器的流量状态，及时处理重启情况
"""

import time
import logging
import sys
import os
import signal
from datetime import datetime, timedelta

# 添加当前目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flow_manager import FlowManager
from lxc_manager import LXCManager
from config_handler import app_config

logging.basicConfig(
    level=getattr(logging, app_config.log_level.upper(), logging.INFO),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('flow_continuity_daemon.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class FlowContinuityDaemon:
    def __init__(self, check_interval=300):  # 生产环境默认5分钟检查一次
        self.flow_manager = FlowManager()
        self.lxc_manager = LXCManager()
        self.check_interval = check_interval
        self.running = False
        self.last_check_time = {}  # 记录每个容器的上次检查时间
        self.failure_count = {}    # 记录失败次数
        self.last_health_check = datetime.now()
        self.total_checks = 0
        self.successful_checks = 0
        
    def start(self):
        """启动守护进程"""
        logger.info(f"启动流量连续性守护进程，检查间隔: {self.check_interval}秒")
        self.running = True
        
        # 注册信号处理器
        signal.signal(signal.SIGTERM, self._signal_handler)
        signal.signal(signal.SIGINT, self._signal_handler)
        
        try:
            while self.running:
                start_time = datetime.now()

                try:
                    self._check_all_containers()
                    self._health_check()
                    self.successful_checks += 1
                except Exception as e:
                    logger.error(f"检查周期异常: {e}", exc_info=True)

                self.total_checks += 1

                # 计算实际耗时，调整睡眠时间
                elapsed = (datetime.now() - start_time).total_seconds()
                sleep_time = max(0, self.check_interval - elapsed)

                if sleep_time > 0:
                    time.sleep(sleep_time)
                else:
                    logger.warning(f"检查耗时 {elapsed:.1f}s 超过间隔 {self.check_interval}s")

        except Exception as e:
            logger.error(f"守护进程异常: {e}", exc_info=True)
        finally:
            logger.info("流量连续性守护进程已停止")
    
    def stop(self):
        """停止守护进程"""
        self.running = False
    
    def _signal_handler(self, signum, frame):
        """信号处理器"""
        logger.info(f"收到信号 {signum}，正在停止守护进程...")
        self.stop()
    
    def _check_all_containers(self):
        """检查所有容器的流量状态"""
        try:
            # 获取所有在流量管理系统中的容器
            import sqlite3
            with sqlite3.connect(self.flow_manager.db_path) as conn:
                cursor = conn.execute("SELECT hostname FROM container_flow_management WHERE auto_reset_enabled = 1")
                managed_containers = [row[0] for row in cursor.fetchall()]
            
            if not managed_containers:
                logger.debug("没有需要检查的容器")
                return
            
            logger.debug(f"检查 {len(managed_containers)} 个容器的流量状态")
            
            for hostname in managed_containers:
                try:
                    self._check_container_flow_status(hostname)
                except Exception as e:
                    logger.error(f"检查容器 {hostname} 流量状态时发生异常: {e}")
                    
        except Exception as e:
            logger.error(f"检查所有容器时发生异常: {e}")
    
    def _check_container_flow_status(self, hostname):
        """检查单个容器的流量状态"""
        try:
            # 获取容器对象
            container = self.lxc_manager._get_container_or_error(hostname)
            if not container:
                logger.debug(f"容器 {hostname} 不存在，跳过检查")
                return
            
            # 只检查运行中的容器
            if container.status != 'Running':
                logger.debug(f"容器 {hostname} 未运行，跳过检查")
                return
            
            # 获取流量管理信息
            flow_info = self.flow_manager.get_container_flow_info(hostname)
            if not flow_info:
                logger.debug(f"容器 {hostname} 未在流量管理系统中注册")
                return
            
            # 获取当前流量统计
            state = container.state()
            current_bytes_received = 0
            current_bytes_sent = 0
            
            if state.network:
                for nic_name, nic_data in state.network.items():
                    # 排除环回接口 lo，避免本地通信影响对外流量连续性判断
                    if nic_name == 'lo' or nic_data.get('type') == 'loopback':
                        continue
                    if 'counters' in nic_data:
                        current_bytes_received += nic_data['counters'].get('bytes_received', 0)
                        current_bytes_sent += nic_data['counters'].get('bytes_sent', 0)

            # 检查是否发生重启
            baseline_received = flow_info['baseline_bytes_received']
            baseline_sent = flow_info['baseline_bytes_sent']
            
            if (current_bytes_received < baseline_received or current_bytes_sent < baseline_sent):
                logger.info(f"🔄 检测到容器 {hostname} 可能重启，立即处理流量连续性")
                
                # 触发流量连续性处理
                usage = self.flow_manager.calculate_current_period_usage(
                    hostname, current_bytes_received, current_bytes_sent
                )
                
                logger.info(f"✅ 容器 {hostname} 流量连续性处理完成，当前使用: {usage} GB")
                
                # 记录处理时间
                self.last_check_time[hostname] = datetime.now()
            else:
                logger.debug(f"容器 {hostname} 流量正常: 接收 {current_bytes_received}, 发送 {current_bytes_sent}")
                
        except Exception as e:
            logger.error(f"检查容器 {hostname} 流量状态时发生异常: {e}")
            # 记录失败次数
            self.failure_count[hostname] = self.failure_count.get(hostname, 0) + 1

            # 如果连续失败次数过多，暂时跳过该容器
            if self.failure_count[hostname] >= 5:
                logger.warning(f"容器 {hostname} 连续失败 {self.failure_count[hostname]} 次，暂时跳过")

    def _health_check(self):
        """健康检查"""
        now = datetime.now()

        # 每10分钟进行一次健康检查
        if (now - self.last_health_check).total_seconds() < 600:
            return

        self.last_health_check = now

        # 计算成功率
        if self.total_checks > 0:
            success_rate = (self.successful_checks / self.total_checks) * 100
            logger.info(f"健康检查: 总检查 {self.total_checks}, 成功率 {success_rate:.1f}%")

            if success_rate < 80:
                logger.warning(f"成功率过低: {success_rate:.1f}%，请检查系统状态")

        # 检查数据库连接
        try:
            self.flow_manager.get_container_flow_info("health_check_test")
            logger.debug("数据库连接正常")
        except Exception as e:
            logger.error(f"数据库连接异常: {e}")

        # 检查LXD连接
        try:
            self.lxc_manager.client.containers.all()
            logger.debug("LXD连接正常")
        except Exception as e:
            logger.error(f"LXD连接异常: {e}")

        # 重置失败计数器（给容器第二次机会）
        for hostname in list(self.failure_count.keys()):
            if self.failure_count[hostname] >= 3:
                self.failure_count[hostname] = max(0, self.failure_count[hostname] - 1)
                logger.debug(f"重置容器 {hostname} 失败计数: {self.failure_count[hostname]}")

def create_systemd_service():
    """创建systemd服务文件"""
    service_content = f"""[Unit]
Description=LXD Flow Continuity Daemon
After=network.target lxd.service
Wants=lxd.service

[Service]
Type=simple
User=root
WorkingDirectory={os.path.dirname(os.path.abspath(__file__))}
ExecStart=/usr/bin/python3 {os.path.abspath(__file__)} --daemon
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
"""
    
    service_path = "/etc/systemd/system/lxd-flow-continuity.service"
    
    try:
        with open(service_path, 'w') as f:
            f.write(service_content)
        
        logger.info(f"✅ 已创建systemd服务文件: {service_path}")
        logger.info("启用服务: sudo systemctl enable lxd-flow-continuity")
        logger.info("启动服务: sudo systemctl start lxd-flow-continuity")
        return True
    except Exception as e:
        logger.error(f"创建systemd服务文件失败: {e}")
        return False

def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description='流量连续性守护进程')
    parser.add_argument('--daemon', action='store_true', help='以守护进程模式运行')
    parser.add_argument('--interval', type=int, default=60, help='检查间隔（秒）')
    parser.add_argument('--create-service', action='store_true', help='创建systemd服务文件')
    
    args = parser.parse_args()
    
    if args.create_service:
        create_systemd_service()
        return
    
    if args.daemon:
        logger.info("=" * 60)
        logger.info("流量连续性守护进程")
        logger.info("=" * 60)
        
        daemon = FlowContinuityDaemon(check_interval=args.interval)
        daemon.start()
    else:
        # 单次检查模式
        logger.info("执行单次流量状态检查...")
        daemon = FlowContinuityDaemon()
        daemon._check_all_containers()
        logger.info("检查完成")

if __name__ == "__main__":
    main()
