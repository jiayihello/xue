#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sqlite3
import logging
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
import os
from typing import Optional, Dict, List, Tuple

logger = logging.getLogger(__name__)

class FlowManager:
    def __init__(self, db_path: str = "flow_management.db"):
        self.db_path = db_path
        self.init_database()

    def init_database(self):
        """初始化数据库"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                # 读取SQL文件并执行
                sql_file = os.path.join(os.path.dirname(__file__), 'create_flow_management_table.sql')
                if os.path.exists(sql_file):
                    with open(sql_file, 'r', encoding='utf-8') as f:
                        conn.executescript(f.read())
                else:
                    # 如果SQL文件不存在，直接创建表
                    conn.executescript("""
                        CREATE TABLE IF NOT EXISTS container_flow_management (
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
                        );

                        CREATE TABLE IF NOT EXISTS flow_reset_history (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            hostname VARCHAR(255) NOT NULL,
                            reset_date DATE NOT NULL,
                            reset_type VARCHAR(20) NOT NULL,
                            old_baseline_received BIGINT DEFAULT 0,
                            old_baseline_sent BIGINT DEFAULT 0,
                            new_baseline_received BIGINT DEFAULT 0,
                            new_baseline_sent BIGINT DEFAULT 0,
                            flow_used_gb DECIMAL(10,2) DEFAULT 0,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        );
                    """)
                logger.info("流量管理数据库初始化完成")
        except Exception as e:
            logger.error(f"初始化流量管理数据库失败: {e}")
            raise

    def register_container(self, hostname: str, flow_limit_gb: int = 0, created_date: Optional[datetime] = None) -> bool:
        """注册容器到流量管理系统"""
        try:
            if created_date is None:
                created_date = datetime.now().date()

            # 计算下次重置日期（下个月的同一天）
            next_reset_date = created_date + relativedelta(months=1)

            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO container_flow_management
                    (hostname, created_date, next_reset_date, flow_limit_gb, current_period_start, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (hostname, created_date, next_reset_date, flow_limit_gb, created_date, datetime.now()))

            logger.info(f"容器 {hostname} 已注册到流量管理系统，下次重置日期: {next_reset_date}")
            return True
        except Exception as e:
            logger.error(f"注册容器 {hostname} 到流量管理系统失败: {e}")
            return False

    def register_container_with_baseline(self, hostname: str, flow_limit_gb: int = 0,
                                       baseline_received: int = 0, baseline_sent: int = 0,
                                       created_date: Optional[datetime] = None) -> bool:
        """注册容器到流量管理系统（带初始基准值）"""
        try:
            if created_date is None:
                created_date = datetime.now().date()

            # 计算下次重置日期（下个月的同一天）
            next_reset_date = created_date + relativedelta(months=1)

            with sqlite3.connect(self.db_path) as conn:
                # 先检查是否需要添加累计字段（兼容性处理）
                cursor = conn.execute("PRAGMA table_info(container_flow_management)")
                columns = [column[1] for column in cursor.fetchall()]

                if 'accumulated_bytes_received' not in columns:
                    conn.execute("ALTER TABLE container_flow_management ADD COLUMN accumulated_bytes_received BIGINT DEFAULT 0")
                    conn.execute("ALTER TABLE container_flow_management ADD COLUMN accumulated_bytes_sent BIGINT DEFAULT 0")

                if 'last_max_bytes_received' not in columns:
                    conn.execute("ALTER TABLE container_flow_management ADD COLUMN last_max_bytes_received BIGINT DEFAULT 0")
                    conn.execute("ALTER TABLE container_flow_management ADD COLUMN last_max_bytes_sent BIGINT DEFAULT 0")

                conn.execute("""
                    INSERT OR REPLACE INTO container_flow_management
                    (hostname, created_date, next_reset_date, flow_limit_gb,
                     baseline_bytes_received, baseline_bytes_sent,
                     accumulated_bytes_received, accumulated_bytes_sent,
                     last_max_bytes_received, last_max_bytes_sent,
                     current_period_start, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (hostname, created_date, next_reset_date, flow_limit_gb,
                      baseline_received, baseline_sent, 0, 0, baseline_received, baseline_sent,
                      created_date, datetime.now()))

            logger.info(f"容器 {hostname} 已注册到流量管理系统，基准值: 接收 {baseline_received}, 发送 {baseline_sent}, 下次重置日期: {next_reset_date}")
            return True
        except Exception as e:
            logger.error(f"注册容器 {hostname} 到流量管理系统失败: {e}")
            return False

    def get_container_flow_info(self, hostname: str) -> Optional[Dict]:
        """获取容器流量管理信息"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.execute("""
                    SELECT * FROM container_flow_management WHERE hostname = ?
                """, (hostname,))
                row = cursor.fetchone()

                if row:
                    return dict(row)
                return None
        except Exception as e:
            logger.error(f"获取容器 {hostname} 流量信息失败: {e}")
            return None

    def calculate_current_period_usage(self, hostname: str, current_bytes_received: int, current_bytes_sent: int) -> float:
        """计算当前计费周期的流量使用量(GB) - 完全自动化版本"""
        flow_info = self.get_container_flow_info(hostname)
        if not flow_info:
            return round((current_bytes_received + current_bytes_sent) / (1024**3), 2)

        # 获取上次记录的最大流量值
        last_max_received = flow_info.get('last_max_bytes_received', 0)
        last_max_sent = flow_info.get('last_max_bytes_sent', 0)
        accumulated_received = flow_info.get('accumulated_bytes_received', 0)
        accumulated_sent = flow_info.get('accumulated_bytes_sent', 0)

        # 检测是否发生了重启
        restart_detected = False

        # 条件1：当前值明显小于历史最大值（且历史最大值不为0）
        # 重要：排除容器停止的情况（current_bytes 完全为 0）
        if (current_bytes_received > 0 or current_bytes_sent > 0) and \
           ((last_max_received > 0 and current_bytes_received < last_max_received * 0.9) or \
            (last_max_sent > 0 and current_bytes_sent < last_max_sent * 0.9)):
            restart_detected = True
            logger.warning(f"检测到容器 {hostname} 重启：当前流量({current_bytes_received + current_bytes_sent}) < 历史最大值({last_max_received + last_max_sent})")
        elif (current_bytes_received == 0 and current_bytes_sent == 0 and 
              (last_max_received > 0 or last_max_sent > 0)):
            # 容器已停止，不触发重启逻辑，避免错误累加流量
            logger.debug(f"容器 {hostname} 已停止 (current_bytes = 0)，跳过重启检测")

        # 条件2：历史最大值为0但当前有流量记录，说明是第一次运行新逻辑
        elif (last_max_received == 0 and last_max_sent == 0 and
              (current_bytes_received > 0 or current_bytes_sent > 0)):
            # 这是第一次使用新逻辑，直接设置最大值，不算重启
            self._update_max_values(hostname, current_bytes_received, current_bytes_sent)
            logger.info(f"容器 {hostname} 首次使用新流量逻辑，设置初始最大值")

        if restart_detected:
            # 将历史最大值累加到accumulated中
            new_accumulated_received = accumulated_received + last_max_received
            new_accumulated_sent = accumulated_sent + last_max_sent

            # 更新数据库：重置最大值为当前值，更新累计值
            self._update_after_restart_auto(
                hostname,
                current_bytes_received,
                current_bytes_sent,
                new_accumulated_received,
                new_accumulated_sent
            )

            # 返回总使用量：累计值 + 当前值
            total_usage = new_accumulated_received + new_accumulated_sent + current_bytes_received + current_bytes_sent
            logger.info(f"容器 {hostname} 重启后自动恢复，总使用量: {total_usage / (1024**3):.3f} GB")
            return round(total_usage / (1024**3), 2)
        else:
            # 没有重启，更新历史最大值
            if (current_bytes_received > last_max_received or current_bytes_sent > last_max_sent):
                self._update_max_values(hostname, current_bytes_received, current_bytes_sent)

        # 正常计算：累计值 + (当前值 - 基准值)
        baseline_received = flow_info.get('baseline_bytes_received', 0)
        baseline_sent = flow_info.get('baseline_bytes_sent', 0)
        
        # 当前周期使用量 = 累计值 + (当前计数 - 基准值)
        current_period_received = max(0, current_bytes_received - baseline_received)
        current_period_sent = max(0, current_bytes_sent - baseline_sent)
        total_usage = accumulated_received + accumulated_sent + current_period_received + current_period_sent
        return round(total_usage / (1024**3), 2)

    def _update_baseline_after_restart(self, hostname: str, current_bytes_received: int, current_bytes_sent: int,
                                      accumulated_received: int = 0, accumulated_sent: int = 0) -> bool:
        """容器重启后更新基准值，保持流量连续性"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                # 先检查是否需要添加累计字段（兼容旧数据库）
                cursor = conn.execute("PRAGMA table_info(container_flow_management)")
                columns = [column[1] for column in cursor.fetchall()]

                if 'accumulated_bytes_received' not in columns:
                    # 添加新字段
                    conn.execute("ALTER TABLE container_flow_management ADD COLUMN accumulated_bytes_received BIGINT DEFAULT 0")
                    conn.execute("ALTER TABLE container_flow_management ADD COLUMN accumulated_bytes_sent BIGINT DEFAULT 0")
                    logger.info("已添加累计流量字段到数据库")

                conn.execute("""
                    UPDATE container_flow_management
                    SET baseline_bytes_received = ?,
                        baseline_bytes_sent = ?,
                        accumulated_bytes_received = ?,
                        accumulated_bytes_sent = ?,
                        updated_at = ?
                    WHERE hostname = ?
                """, (current_bytes_received, current_bytes_sent, accumulated_received, accumulated_sent, datetime.now(), hostname))

                # 记录重启事件
                conn.execute("""
                    INSERT INTO flow_reset_history
                    (hostname, reset_date, reset_type, old_baseline_received, old_baseline_sent,
                     new_baseline_received, new_baseline_sent, flow_used_gb)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (hostname, datetime.now().date(), 'restart', 0, 0,
                      current_bytes_received, current_bytes_sent, round((accumulated_received + accumulated_sent) / (1024**3), 2)))

            logger.info(f"容器 {hostname} 重启后基准值已更新，累计流量已保存")
            return True
        except Exception as e:
            logger.error(f"更新容器 {hostname} 重启后基准值失败: {e}")
            return False

    def _update_container_baseline(self, hostname: str, current_bytes_received: int, current_bytes_sent: int) -> bool:
        """更新容器的流量基准值（用于容器启动后设置正确的基准值）"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                # 先检查是否需要添加累计字段（兼容性处理）
                cursor = conn.execute("PRAGMA table_info(container_flow_management)")
                columns = [column[1] for column in cursor.fetchall()]

                if 'accumulated_bytes_received' not in columns:
                    conn.execute("ALTER TABLE container_flow_management ADD COLUMN accumulated_bytes_received BIGINT DEFAULT 0")
                    conn.execute("ALTER TABLE container_flow_management ADD COLUMN accumulated_bytes_sent BIGINT DEFAULT 0")

                # 更新基准值
                conn.execute("""
                    UPDATE container_flow_management
                    SET baseline_bytes_received = ?,
                        baseline_bytes_sent = ?,
                        updated_at = ?
                    WHERE hostname = ?
                """, (current_bytes_received, current_bytes_sent, datetime.now(), hostname))

                rows_affected = conn.total_changes
                if rows_affected > 0:
                    logger.info(f"容器 {hostname} 基准值更新成功")
                    return True
                else:
                    logger.warning(f"容器 {hostname} 不存在于流量管理系统中")
                    return False

        except Exception as e:
            logger.error(f"更新容器 {hostname} 基准值失败: {e}")
            return False

    def _update_after_restart_auto(self, hostname: str, current_bytes_received: int, current_bytes_sent: int,
                                  accumulated_received: int, accumulated_sent: int) -> bool:
        """重启后自动更新流量数据"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                # 确保有所需字段
                cursor = conn.execute("PRAGMA table_info(container_flow_management)")
                columns = [column[1] for column in cursor.fetchall()]

                if 'accumulated_bytes_received' not in columns:
                    conn.execute("ALTER TABLE container_flow_management ADD COLUMN accumulated_bytes_received BIGINT DEFAULT 0")
                    conn.execute("ALTER TABLE container_flow_management ADD COLUMN accumulated_bytes_sent BIGINT DEFAULT 0")

                if 'last_max_bytes_received' not in columns:
                    conn.execute("ALTER TABLE container_flow_management ADD COLUMN last_max_bytes_received BIGINT DEFAULT 0")
                    conn.execute("ALTER TABLE container_flow_management ADD COLUMN last_max_bytes_sent BIGINT DEFAULT 0")

                # 更新数据
                conn.execute("""
                    UPDATE container_flow_management
                    SET accumulated_bytes_received = ?,
                        accumulated_bytes_sent = ?,
                        last_max_bytes_received = ?,
                        last_max_bytes_sent = ?,
                        updated_at = ?
                    WHERE hostname = ?
                """, (accumulated_received, accumulated_sent, current_bytes_received, current_bytes_sent, datetime.now(), hostname))

                # 记录重启事件
                conn.execute("""
                    INSERT INTO flow_reset_history
                    (hostname, reset_date, reset_type, old_baseline_received, old_baseline_sent,
                     new_baseline_received, new_baseline_sent, flow_used_gb)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (hostname, datetime.now().date(), 'auto_restart', 0, 0,
                      current_bytes_received, current_bytes_sent, round((accumulated_received + accumulated_sent) / (1024**3), 2)))

            return True
        except Exception as e:
            logger.error(f"自动更新容器 {hostname} 重启数据失败: {e}")
            return False

    def _update_max_values(self, hostname: str, current_bytes_received: int, current_bytes_sent: int) -> bool:
        """更新历史最大值"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                # 确保有所需字段
                cursor = conn.execute("PRAGMA table_info(container_flow_management)")
                columns = [column[1] for column in cursor.fetchall()]

                if 'last_max_bytes_received' not in columns:
                    conn.execute("ALTER TABLE container_flow_management ADD COLUMN last_max_bytes_received BIGINT DEFAULT 0")
                    conn.execute("ALTER TABLE container_flow_management ADD COLUMN last_max_bytes_sent BIGINT DEFAULT 0")

                conn.execute("""
                    UPDATE container_flow_management
                    SET last_max_bytes_received = ?,
                        last_max_bytes_sent = ?,
                        updated_at = ?
                    WHERE hostname = ?
                """, (current_bytes_received, current_bytes_sent, datetime.now(), hostname))

            return True
        except Exception as e:
            logger.error(f"更新容器 {hostname} 最大值失败: {e}")
            return False

    def reset_container_flow(self, hostname: str, current_bytes_received: int, current_bytes_sent: int, reset_type: str = 'manual') -> bool:
        """重置容器流量"""
        try:
            flow_info = self.get_container_flow_info(hostname)
            if not flow_info:
                logger.warning(f"容器 {hostname} 未在流量管理系统中注册")
                return False

            # 计算重置前的使用量
            old_usage_gb = self.calculate_current_period_usage(hostname, current_bytes_received, current_bytes_sent)

            # 更新基准值和重置日期
            reset_date = datetime.now().date()
            next_reset_date = reset_date + relativedelta(months=1)

            with sqlite3.connect(self.db_path) as conn:
                # 确保有所需字段
                cursor = conn.execute("PRAGMA table_info(container_flow_management)")
                columns = [column[1] for column in cursor.fetchall()]

                if 'accumulated_bytes_received' not in columns:
                    conn.execute("ALTER TABLE container_flow_management ADD COLUMN accumulated_bytes_received BIGINT DEFAULT 0")
                    conn.execute("ALTER TABLE container_flow_management ADD COLUMN accumulated_bytes_sent BIGINT DEFAULT 0")

                if 'last_max_bytes_received' not in columns:
                    conn.execute("ALTER TABLE container_flow_management ADD COLUMN last_max_bytes_received BIGINT DEFAULT 0")
                    conn.execute("ALTER TABLE container_flow_management ADD COLUMN last_max_bytes_sent BIGINT DEFAULT 0")

                # 更新流量管理记录，重置时清空所有累计数据
                conn.execute("""
                    UPDATE container_flow_management
                    SET accumulated_bytes_received = 0,
                        accumulated_bytes_sent = 0,
                        baseline_bytes_received = ?,
                        baseline_bytes_sent = ?,
                        last_max_bytes_received = ?,
                        last_max_bytes_sent = ?,
                        last_reset_date = ?,
                        next_reset_date = ?,
                        current_period_start = ?,
                        reset_count = reset_count + 1,
                        updated_at = ?
                    WHERE hostname = ?
                """, (current_bytes_received, current_bytes_sent, 
                      current_bytes_received, current_bytes_sent, 
                      reset_date, next_reset_date,
                      reset_date, datetime.now(), hostname))

                # 记录重置历史
                conn.execute("""
                    INSERT INTO flow_reset_history
                    (hostname, reset_date, reset_type, old_baseline_received, old_baseline_sent,
                     new_baseline_received, new_baseline_sent, flow_used_gb)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (hostname, reset_date, reset_type,
                      flow_info['baseline_bytes_received'], flow_info['baseline_bytes_sent'],
                      current_bytes_received, current_bytes_sent, old_usage_gb))

            logger.info(f"容器 {hostname} 流量已重置，重置前使用: {old_usage_gb}GB，下次重置: {next_reset_date}")
            return True
        except Exception as e:
            logger.error(f"重置容器 {hostname} 流量失败: {e}")
            return False

    def soft_rebase_baseline(self, hostname: str, current_bytes_received: int, current_bytes_sent: int) -> bool:
        """
        软重置/重基线：
        - 目的：在不改变 last_reset_date / next_reset_date / current_period_start 的前提下，
          以“当前计数”（已按业务口径排除 lo）作为新的基线与最大值；累计清零。
        - 效果：之后显示的“已用”将从当前计数开始继续累计；周期日期不变。
        - 会记录一条 flow_reset_history，类型 soft_rebase。
        """
        try:
            flow_info = self.get_container_flow_info(hostname)
            if not flow_info:
                logger.warning(f"容器 {hostname} 未在流量管理系统中注册，无法软重基线")
                return False

            old_base_rx = int(flow_info.get('baseline_bytes_received', 0) or 0)
            old_base_tx = int(flow_info.get('baseline_bytes_sent', 0) or 0)
            old_acc_rx = int(flow_info.get('accumulated_bytes_received', 0) or 0)
            old_acc_tx = int(flow_info.get('accumulated_bytes_sent', 0) or 0)
            old_last_rx = int(flow_info.get('last_max_bytes_received', 0) or 0)
            old_last_tx = int(flow_info.get('last_max_bytes_sent', 0) or 0)

            # 旧口径下的“已累计总量”（仅用于写入历史记录，便于审计）
            old_total_bytes = old_acc_rx + old_acc_tx + old_last_rx + old_last_tx
            old_total_gb = round(old_total_bytes / (1024**3), 2)

            with sqlite3.connect(self.db_path) as conn:
                # 确保必要字段存在
                cursor = conn.execute("PRAGMA table_info(container_flow_management)")
                columns = [column[1] for column in cursor.fetchall()]
                if 'accumulated_bytes_received' not in columns:
                    conn.execute("ALTER TABLE container_flow_management ADD COLUMN accumulated_bytes_received BIGINT DEFAULT 0")
                    conn.execute("ALTER TABLE container_flow_management ADD COLUMN accumulated_bytes_sent BIGINT DEFAULT 0")
                if 'last_max_bytes_received' not in columns:
                    conn.execute("ALTER TABLE container_flow_management ADD COLUMN last_max_bytes_received BIGINT DEFAULT 0")
                    conn.execute("ALTER TABLE container_flow_management ADD COLUMN last_max_bytes_sent BIGINT DEFAULT 0")

                # 不改动日期字段，只重基线与累计
                conn.execute(
                    """
                    UPDATE container_flow_management
                    SET baseline_bytes_received = ?,
                        baseline_bytes_sent = ?,
                        accumulated_bytes_received = 0,
                        accumulated_bytes_sent = 0,
                        last_max_bytes_received = ?,
                        last_max_bytes_sent = ?,
                        updated_at = ?
                    WHERE hostname = ?
                    """,
                    (current_bytes_received, current_bytes_sent,
                     current_bytes_received, current_bytes_sent,
                     datetime.now(), hostname)
                )

                # 写入历史记录（便于追踪口径切换）
                conn.execute(
                    """
                    INSERT INTO flow_reset_history
                    (hostname, reset_date, reset_type, old_baseline_received, old_baseline_sent,
                     new_baseline_received, new_baseline_sent, flow_used_gb)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (hostname, datetime.now().date(), 'soft_rebase',
                     old_base_rx, old_base_tx,
                     current_bytes_received, current_bytes_sent,
                     old_total_gb)
                )

            logger.info(f"容器 {hostname} 已软重基线，累计清零，日期未改动。新基线 RX={current_bytes_received}, TX={current_bytes_sent}")
            return True
        except Exception as e:
            logger.error(f"容器 {hostname} 软重基线失败: {e}")
            return False

    def get_containers_need_reset(self) -> List[str]:
        """获取需要重置流量的容器列表"""
        try:
            today = datetime.now().date()
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute("""
                    SELECT hostname FROM container_flow_management
                    WHERE next_reset_date <= ? AND auto_reset_enabled = 1
                """, (today,))
                return [row[0] for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"获取需要重置流量的容器列表失败: {e}")
            return []

    def get_flow_reset_history(self, hostname: str, limit: int = 10) -> List[Dict]:
        """获取流量重置历史"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.execute("""
                    SELECT * FROM flow_reset_history
                    WHERE hostname = ?
                    ORDER BY reset_date DESC
                    LIMIT ?
                """, (hostname, limit))
                return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"获取容器 {hostname} 流量重置历史失败: {e}")
            return []

    def unregister_container(self, hostname: str) -> bool:
        """从流量管理系统中注销容器"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("DELETE FROM container_flow_management WHERE hostname = ?", (hostname,))
                logger.info(f"容器 {hostname} 已从流量管理系统中注销")
                return True
        except Exception as e:
            logger.error(f"注销容器 {hostname} 失败: {e}")
            return False
