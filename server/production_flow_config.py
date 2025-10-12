#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
生产环境流量管理配置
针对生产环境优化的配置参数
"""

import os
from dataclasses import dataclass
from typing import Optional

@dataclass
class ProductionFlowConfig:
    """生产环境流量管理配置"""
    
    # 守护进程配置
    daemon_check_interval: int = 300  # 5分钟检查一次（生产环境推荐）
    daemon_enabled: bool = True
    daemon_max_retries: int = 3
    daemon_retry_delay: int = 30
    
    # 事件监听配置（可选）
    event_monitor_enabled: bool = False  # 生产环境默认关闭
    event_monitor_reconnect_delay: int = 10
    event_monitor_max_reconnects: int = 5
    
    # 日志配置
    log_level: str = "INFO"
    log_rotation: bool = True
    log_max_size: str = "10MB"
    log_backup_count: int = 5
    
    # 性能配置
    batch_check_size: int = 10  # 每次批量检查的容器数量
    check_timeout: int = 30     # 单个容器检查超时时间
    database_pool_size: int = 5
    
    # 监控配置
    health_check_enabled: bool = True
    health_check_interval: int = 600  # 10分钟健康检查
    metrics_enabled: bool = True
    
    # 故障恢复配置
    auto_recovery_enabled: bool = True
    max_consecutive_failures: int = 5
    failure_cooldown_period: int = 300  # 5分钟冷却期
    
    @classmethod
    def from_env(cls) -> 'ProductionFlowConfig':
        """从环境变量加载配置"""
        return cls(
            daemon_check_interval=int(os.getenv('FLOW_DAEMON_INTERVAL', '300')),
            daemon_enabled=os.getenv('FLOW_DAEMON_ENABLED', 'true').lower() == 'true',
            event_monitor_enabled=os.getenv('FLOW_EVENT_MONITOR_ENABLED', 'false').lower() == 'true',
            log_level=os.getenv('FLOW_LOG_LEVEL', 'INFO'),
            batch_check_size=int(os.getenv('FLOW_BATCH_SIZE', '10')),
            health_check_enabled=os.getenv('FLOW_HEALTH_CHECK', 'true').lower() == 'true',
        )
    
    def validate(self) -> bool:
        """验证配置有效性"""
        if self.daemon_check_interval < 60:
            raise ValueError("守护进程检查间隔不应小于60秒")
        
        if self.batch_check_size > 50:
            raise ValueError("批量检查大小不应超过50")
        
        if self.check_timeout < 10:
            raise ValueError("检查超时时间不应小于10秒")
        
        return True

# 生产环境默认配置
PRODUCTION_CONFIG = ProductionFlowConfig()

# 不同规模的推荐配置
SMALL_SCALE_CONFIG = ProductionFlowConfig(
    daemon_check_interval=180,  # 3分钟
    batch_check_size=5,
    log_level="INFO"
)

MEDIUM_SCALE_CONFIG = ProductionFlowConfig(
    daemon_check_interval=300,  # 5分钟
    batch_check_size=10,
    log_level="INFO"
)

LARGE_SCALE_CONFIG = ProductionFlowConfig(
    daemon_check_interval=600,  # 10分钟
    batch_check_size=20,
    log_level="WARNING"
)
