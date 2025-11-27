#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
异步任务管理器
用于处理耗时的容器操作（重装、开关机等），避免前端长时间等待
"""

import threading
import logging
import time
import uuid
from enum import Enum
from typing import Dict, Callable, Any, Optional
from dataclasses import dataclass, field
from datetime import datetime
from queue import Queue

logger = logging.getLogger(__name__)

# 重装任务并发限制（防止多个重装同时进行导致宿主机过载）
MAX_CONCURRENT_REINSTALL = 2


class TaskStatus(Enum):
    """任务状态"""
    PENDING = "pending"      # 等待执行
    RUNNING = "running"      # 执行中
    SUCCESS = "success"      # 成功
    FAILED = "failed"        # 失败


@dataclass
class AsyncTask:
    """异步任务"""
    task_id: str
    task_type: str           # 任务类型：reinstall, start, stop, restart
    hostname: str            # 容器名
    status: TaskStatus = TaskStatus.PENDING
    result: Optional[Dict] = None
    error: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.now)
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None


class AsyncTaskManager:
    """
    异步任务管理器（单例模式）
    
    功能：
    - 将耗时操作放入后台线程执行
    - 立即返回任务ID，前端无需等待
    - 可查询任务执行状态和结果
    """
    
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        self.tasks: Dict[str, AsyncTask] = {}
        self.task_lock = threading.Lock()
        self.max_tasks = 1000  # 最多保留1000个任务记录
        self.task_ttl = 3600   # 任务记录保留1小时
        
        # 重装任务并发控制（信号量）
        # 防止多个重装同时进行导致宿主机过载
        self.reinstall_semaphore = threading.Semaphore(MAX_CONCURRENT_REINSTALL)
        
        self._initialized = True
        logger.info(f"异步任务管理器已初始化（重装并发限制: {MAX_CONCURRENT_REINSTALL}）")
    
    def submit_task(self, task_type: str, hostname: str, 
                    func: Callable, *args, **kwargs) -> str:
        """
        提交异步任务
        
        Args:
            task_type: 任务类型（reinstall, start, stop, restart）
            hostname: 容器名
            func: 要执行的函数
            *args, **kwargs: 函数参数
            
        Returns:
            任务ID
        """
        task_id = str(uuid.uuid4())[:8]
        
        task = AsyncTask(
            task_id=task_id,
            task_type=task_type,
            hostname=hostname
        )
        
        with self.task_lock:
            self.tasks[task_id] = task
            self._cleanup_old_tasks()
        
        # 启动后台线程执行任务
        thread = threading.Thread(
            target=self._execute_task,
            args=(task_id, func, args, kwargs),
            daemon=True
        )
        thread.start()
        
        logger.info(f"异步任务已提交: {task_type} for {hostname}, task_id={task_id}")
        return task_id
    
    def _execute_task(self, task_id: str, func: Callable, 
                      args: tuple, kwargs: dict):
        """在后台线程中执行任务"""
        task = self.tasks.get(task_id)
        if not task:
            return
        
        # 重装任务需要获取信号量（限制并发，防止宿主机过载）
        # 注意：create 是同步执行的，不会进入这里
        use_semaphore = task.task_type == 'reinstall'
        
        if use_semaphore:
            logger.info(f"任务 {task.task_type} for {task.hostname} 等待执行槽位...")
            self.reinstall_semaphore.acquire()
            logger.info(f"任务 {task.task_type} for {task.hostname} 获得执行槽位")
        
        try:
            with self.task_lock:
                task.status = TaskStatus.RUNNING
                task.started_at = datetime.now()
            
            logger.info(f"开始执行异步任务: {task.task_type} for {task.hostname}")
            result = func(*args, **kwargs)
            
            with self.task_lock:
                task.status = TaskStatus.SUCCESS
                task.result = result
                task.finished_at = datetime.now()
            
            logger.info(f"异步任务完成: {task.task_type} for {task.hostname}, result={result.get('code') if result else 'None'}")
            
        except Exception as e:
            logger.error(f"异步任务失败: {task.task_type} for {task.hostname}, error={e}", exc_info=True)
            
            with self.task_lock:
                task.status = TaskStatus.FAILED
                task.error = str(e)
                task.finished_at = datetime.now()
        finally:
            # 释放信号量
            if use_semaphore:
                self.reinstall_semaphore.release()
                logger.debug(f"任务 {task.task_type} for {task.hostname} 释放执行槽位")
    
    def get_task(self, task_id: str) -> Optional[AsyncTask]:
        """获取任务信息"""
        return self.tasks.get(task_id)
    
    def get_task_status(self, task_id: str) -> Optional[Dict]:
        """获取任务状态（用于API返回）"""
        task = self.tasks.get(task_id)
        if not task:
            return None
        
        return {
            'task_id': task.task_id,
            'task_type': task.task_type,
            'hostname': task.hostname,
            'status': task.status.value,
            'result': task.result,
            'error': task.error,
            'created_at': task.created_at.isoformat() if task.created_at else None,
            'started_at': task.started_at.isoformat() if task.started_at else None,
            'finished_at': task.finished_at.isoformat() if task.finished_at else None
        }
    
    def _cleanup_old_tasks(self):
        """清理过期任务"""
        now = datetime.now()
        expired_ids = []
        
        for task_id, task in self.tasks.items():
            # 检查是否过期
            if task.finished_at:
                age = (now - task.finished_at).total_seconds()
                if age > self.task_ttl:
                    expired_ids.append(task_id)
        
        # 删除过期任务
        for task_id in expired_ids:
            del self.tasks[task_id]
        
        # 如果还是太多，删除最旧的
        if len(self.tasks) > self.max_tasks:
            sorted_tasks = sorted(
                self.tasks.items(),
                key=lambda x: x[1].created_at
            )
            to_remove = len(self.tasks) - self.max_tasks
            for task_id, _ in sorted_tasks[:to_remove]:
                del self.tasks[task_id]


# 全局单例
_task_manager = AsyncTaskManager()


def get_task_manager() -> AsyncTaskManager:
    """获取任务管理器实例"""
    return _task_manager
