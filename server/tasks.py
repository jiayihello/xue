"""
Celery 异步任务定义
用于处理耗时的容器操作（重装、开关机等）
"""
import sys
import os

# 确保当前目录在 Python 路径中
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from celery import Celery
from config_handler import app_config
import logging

logging.basicConfig(level=getattr(logging, app_config.log_level, logging.INFO),
                    format='%(asctime)s %(levelname)s: %(message)s [%(filename)s:%(lineno)d]',
                    datefmt='%Y-%m-%d %H:%M:%S')
logger = logging.getLogger(__name__)

# 创建 Celery 应用
celery_app = Celery('tasks',
                    broker=app_config.celery_broker_url,
                    backend=app_config.celery_result_backend)

# Celery 配置
celery_app.conf.update(
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    timezone='Asia/Shanghai',
    enable_utc=True,
    # 任务结果过期时间（1小时）
    result_expires=3600,
    # 限制重装任务并发（防止宿主机过载）
    worker_concurrency=2,
)


def get_lxc_manager():
    """获取 LXCManager 实例"""
    try:
        from lxc_manager import LXCManager
        return LXCManager()
    except RuntimeError as e:
        logger.critical(f"Celery Worker 无法连接到 LXD: {e}")
        raise


@celery_app.task(bind=True, max_retries=0)
def create_container_task(self, params):
    """创建容器（同步执行，因为需要返回IP等信息）"""
    lxc = get_lxc_manager()
    return lxc.create_container(params)


@celery_app.task(bind=True, max_retries=0)
def delete_container_task(self, hostname):
    """删除容器"""
    lxc = get_lxc_manager()
    return lxc.delete_container(hostname)


@celery_app.task(bind=True, max_retries=0)
def start_container_task(self, hostname):
    """启动容器"""
    lxc = get_lxc_manager()
    return lxc.start_container(hostname)


@celery_app.task(bind=True, max_retries=0)
def stop_container_task(self, hostname):
    """停止容器"""
    lxc = get_lxc_manager()
    return lxc.stop_container(hostname)


@celery_app.task(bind=True, max_retries=0)
def restart_container_task(self, hostname):
    """重启容器"""
    lxc = get_lxc_manager()
    return lxc.restart_container(hostname)


@celery_app.task(bind=True, max_retries=0)
def change_password_task(self, hostname, new_pass):
    """修改密码"""
    lxc = get_lxc_manager()
    return lxc.change_password(hostname, new_pass)


@celery_app.task(bind=True, max_retries=0)
def reinstall_container_task(self, hostname, new_os, new_password):
    """重装容器"""
    lxc = get_lxc_manager()
    return lxc.reinstall_container(hostname, new_os, new_password)


@celery_app.task(bind=True, max_retries=0)
def add_nat_rule_task(self, hostname, dtype, dport, sport, remark=''):
    """添加 NAT 规则"""
    lxc = get_lxc_manager()
    return lxc.add_nat_rule_via_iptables(hostname, dtype, dport, sport, remark)


@celery_app.task(bind=True, max_retries=0)
def delete_nat_rule_task(self, hostname, dtype, dport, sport):
    """删除 NAT 规则"""
    lxc = get_lxc_manager()
    return lxc.delete_nat_rule_via_iptables(hostname, dtype, dport, sport)
