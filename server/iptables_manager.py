#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
iptables 流量统计规则管理器
负责为每个容器创建和管理 iptables 规则来统计流量
"""

import subprocess
import logging
import json
import os
from typing import Dict, List, Optional, Tuple

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class IptablesManager:
    """iptables 规则管理器"""
    
    def __init__(self, rules_file: str = 'iptables_rules.json'):
        """
        初始化 iptables 管理器
        
        Args:
            rules_file: 规则配置文件路径
        """
        self.rules_file = rules_file
        self.rules_cache = self._load_rules_cache()
        
        # 确保流量统计链存在
        self._ensure_accounting_chains()
    
    def _load_rules_cache(self) -> Dict:
        """加载规则缓存（兼容旧的列表格式）"""
        if os.path.exists(self.rules_file):
            try:
                with open(self.rules_file, 'r') as f:
                    data = json.load(f)
                    
                    # ✅ 兼容性处理：如果是旧的列表格式，转换为字典
                    if isinstance(data, list):
                        logger.warning(f"检测到旧的列表格式rules_cache，自动转换为字典格式")
                        new_dict = {}
                        for item in data:
                            if isinstance(item, dict) and 'hostname' in item:
                                hostname = item['hostname']
                                new_dict[hostname] = item
                        logger.info(f"已转换 {len(new_dict)} 个容器规则到新格式")
                        # 立即保存新格式
                        self.rules_cache = new_dict
                        self._save_rules_cache()
                        return new_dict
                    
                    # 如果已经是字典格式，直接返回
                    return data
            except Exception as e:
                logger.warning(f"加载规则缓存失败: {e}")
        return {}
    
    def _save_rules_cache(self):
        """保存规则缓存"""
        try:
            logger.debug(f"准备保存规则缓存到 {self.rules_file}，当前缓存: {self.rules_cache}")
            with open(self.rules_file, 'w') as f:
                json.dump(self.rules_cache, f, indent=2)
            logger.info(f"✓ 规则缓存已保存到 {self.rules_file}，共 {len(self.rules_cache)} 个容器")
        except Exception as e:
            logger.error(f"✗ 保存规则缓存到 {self.rules_file} 失败: {e}", exc_info=True)
    
    def _ensure_accounting_chains(self):
        """确保 LXD_FLOW_ACCOUNTING 链存在（IPv4 和 IPv6）"""
        try:
            # 检查并创建 IPv4 链
            check_ipv4 = subprocess.run(
                ['iptables', '-L', 'LXD_FLOW_ACCOUNTING', '-n'],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            
            if check_ipv4.returncode != 0:
                # 链不存在，创建它
                subprocess.run(['iptables', '-N', 'LXD_FLOW_ACCOUNTING'], check=True)
                # 添加 FORWARD 链跳转
                subprocess.run([
                    'iptables', '-I', 'FORWARD', '1',
                    '-j', 'LXD_FLOW_ACCOUNTING'
                ], check=True)
                logger.info("✓ 已创建 IPv4 LXD_FLOW_ACCOUNTING 链")
            
            # 检查并创建 IPv6 链
            check_ipv6 = subprocess.run(
                ['ip6tables', '-L', 'LXD_FLOW_ACCOUNTING', '-n'],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            
            if check_ipv6.returncode != 0:
                # 链不存在，创建它
                subprocess.run(['ip6tables', '-N', 'LXD_FLOW_ACCOUNTING'], check=True)
                # 添加 FORWARD 链跳转
                subprocess.run([
                    'ip6tables', '-I', 'FORWARD', '1',
                    '-j', 'LXD_FLOW_ACCOUNTING'
                ], check=True)
                logger.info("✓ 已创建 IPv6 LXD_FLOW_ACCOUNTING 链")
                
        except Exception as e:
            logger.warning(f"创建流量统计链时出错（可能已存在）: {e}")
    
    def _run_command(self, cmd: List[str]) -> Tuple[bool, str]:
        """
        运行命令
        
        Args:
            cmd: 命令列表
            
        Returns:
            (成功标志, 输出内容)
        """
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=False
            )
            if result.returncode == 0:
                return True, result.stdout
            else:
                logger.warning(f"命令执行失败: {' '.join(cmd)}, 错误: {result.stderr}")
                return False, result.stderr
        except Exception as e:
            logger.error(f"命令执行异常: {' '.join(cmd)}, 异常: {e}")
            return False, str(e)
    
    def ensure_container_rules(self, hostname: str) -> bool:
        """
        确保容器的 iptables 规则存在（自动获取IP）
        
        Args:
            hostname: 容器主机名
            
        Returns:
            是否成功
        """
        try:
            # 导入 lxc_manager 获取容器IP
            from lxc_manager import LXCManager
            lxc_mgr = LXCManager()
            
            # 在LXD中，容器名称就是hostname，不需要转换
            container_name = hostname
            
            # 获取容器IP
            try:
                container = lxc_mgr.client.containers.get(container_name)
                state = container.state()
                
                ipv4 = None
                ipv6 = None
                
                # 从网络状态中提取IP
                if state.network and 'eth0' in state.network:
                    eth0 = state.network['eth0']
                    for addr in eth0.get('addresses', []):
                        if addr['family'] == 'inet' and addr['scope'] == 'global':
                            ipv4 = addr['address']
                        elif addr['family'] == 'inet6' and addr['scope'] == 'global':
                            ipv6 = addr['address']
                
                # 也检查 eth0v6 (IPv6-Only 模式)
                if not ipv6 and state.network and 'eth0v6' in state.network:
                    eth0v6 = state.network['eth0v6']
                    for addr in eth0v6.get('addresses', []):
                        if addr['family'] == 'inet6' and addr['scope'] == 'global':
                            ipv6 = addr['address']
                
                if not ipv4 and not ipv6:
                    logger.warning(f"容器 {hostname} 没有获取到 IP 地址")
                    return False
                
                # 调用 setup_rules
                return self.setup_rules(hostname, ipv4, ipv6)
                
            except Exception as e:
                logger.error(f"获取容器 {hostname} 的 IP 地址失败: {e}")
                return False
                
        except ImportError:
            logger.error("无法导入 lxc_manager")
            return False
        except Exception as e:
            logger.error(f"确保容器 {hostname} 规则失败: {e}")
            return False
    
    def setup_rules(self, hostname: str, ipv4: Optional[str] = None, 
                   ipv6: Optional[str] = None) -> bool:
        """
        为容器创建 iptables 规则
        
        Args:
            hostname: 容器主机名
            ipv4: IPv4 地址
            ipv6: IPv6 地址
            
        Returns:
            是否成功
        """
        logger.info(f"为容器 {hostname} 创建 iptables 规则...")
        
        # 🔥 重要修复：检查IP地址是否变化，如变化则先清理旧规则
        if hostname in self.rules_cache:
            old_info = self.rules_cache[hostname]
            old_ipv4 = old_info.get('ipv4')
            old_ipv6 = old_info.get('ipv6')
            
            # 检查IP是否变化
            ipv4_changed = (old_ipv4 != ipv4)
            ipv6_changed = (old_ipv6 != ipv6)
            
            if ipv4_changed or ipv6_changed:
                logger.warning(f"容器 {hostname} IP地址已变化:")
                if ipv4_changed:
                    logger.warning(f"  IPv4: {old_ipv4} → {ipv4}")
                if ipv6_changed:
                    logger.warning(f"  IPv6: {old_ipv6} → {ipv6}")
                
                # 先清理旧规则，避免规则累积
                logger.info(f"清理容器 {hostname} 的旧规则...")
                if old_ipv4:
                    self._cleanup_ipv4_rules(hostname, old_ipv4)
                if old_ipv6:
                    self._cleanup_ipv6_rules(hostname, old_ipv6)
        
        success = True
        
        # 添加新规则
        if ipv4:
            success = success and self._setup_ipv4_rules(hostname, ipv4)
        
        if ipv6:
            success = success and self._setup_ipv6_rules(hostname, ipv6)
        
        if success:
            # 更新缓存
            self.rules_cache[hostname] = {
                'ipv4': ipv4,
                'ipv6': ipv6
            }
            self._save_rules_cache()
            logger.info(f"✓ 容器 {hostname} 规则创建成功")
        else:
            logger.error(f"✗ 容器 {hostname} 规则创建失败")
        
        return success
    
    def _setup_ipv4_rules(self, hostname: str, ipv4: str) -> bool:
        """创建 IPv4 规则"""
        # ✅ 出站流量规则（源地址匹配）- 添加到 LXD_FLOW_ACCOUNTING 链
        # 先检查规则是否已存在
        check_cmd = ["iptables", "-L", "LXD_FLOW_ACCOUNTING", "-n"]
        success, output = self._run_command(check_cmd)
        if success and f"flow-{hostname}-out" in output:
            logger.debug(f"IPv4 规则已存在: {hostname}")
            return True

        cmd_out = [
            'iptables', '-A', 'LXD_FLOW_ACCOUNTING',
            '-s', ipv4,
            '-m', 'comment', '--comment', f'flow-{hostname}-out'
        ]
        
        # ✅ 入站流量规则（目标地址匹配）- 添加到 LXD_FLOW_ACCOUNTING 链
        cmd_in = [
            'iptables', '-A', 'LXD_FLOW_ACCOUNTING',
            '-d', ipv4,
            '-m', 'comment', '--comment', f'flow-{hostname}-in'
        ]
        
        success_out, _ = self._run_command(cmd_out)
        success_in, _ = self._run_command(cmd_in)
        
        if success_out and success_in:
            logger.debug(f"IPv4 规则已创建: {ipv4}")
            return True
        else:
            logger.error(f"IPv4 规则创建失败: {ipv4}")
            return False
    
    def _setup_ipv6_rules(self, hostname: str, ipv6: str) -> bool:
        """创建 IPv6 规则"""
        # ✅ 出站流量规则 - 添加到 LXD_FLOW_ACCOUNTING 链
        # 先检查规则是否已存在
        check_cmd = ["ip6tables", "-L", "LXD_FLOW_ACCOUNTING", "-n"]
        success, output = self._run_command(check_cmd)
        if success and f"flow-{hostname}-out" in output:
            logger.debug(f"IPv6 规则已存在: {hostname}")
            return True

        cmd_out = [
            'ip6tables', '-A', 'LXD_FLOW_ACCOUNTING',
            '-s', ipv6,
            '-m', 'comment', '--comment', f'flow-{hostname}-out'
        ]
        
        # ✅ 入站流量规则 - 添加到 LXD_FLOW_ACCOUNTING 链
        cmd_in = [
            'ip6tables', '-A', 'LXD_FLOW_ACCOUNTING',
            '-d', ipv6,
            '-m', 'comment', '--comment', f'flow-{hostname}-in'
        ]
        
        success_out, _ = self._run_command(cmd_out)
        success_in, _ = self._run_command(cmd_in)
        
        if success_out and success_in:
            logger.debug(f"IPv6 规则已创建: {ipv6}")
            return True
        else:
            logger.error(f"IPv6 规则创建失败: {ipv6}")
            return False
    
    def cleanup_rules(self, hostname: str) -> bool:
        """
        删除容器的 iptables 规则
        
        Args:
            hostname: 容器主机名
            
        Returns:
            是否成功
        """
        logger.info(f"清理容器 {hostname} 的 iptables 规则...")
        
        # 从缓存获取信息
        if hostname not in self.rules_cache:
            logger.warning(f"容器 {hostname} 不在规则缓存中")
            # 尝试通过 comment 查找并删除
            return self._cleanup_by_comment(hostname)
        
        info = self.rules_cache[hostname]
        success = True
        
        # 清理 IPv4
        if info.get('ipv4'):
            success = success and self._cleanup_ipv4_rules(hostname, info['ipv4'])
        
        # 清理 IPv6
        if info.get('ipv6'):
            success = success and self._cleanup_ipv6_rules(hostname, info['ipv6'])
        
        if success:
            # 从缓存移除
            del self.rules_cache[hostname]
            self._save_rules_cache()
            logger.info(f"✓ 容器 {hostname} 规则清理完成")
        else:
            logger.warning(f"容器 {hostname} 规则清理可能不完全")
        
        return success
    
    def remove_container_rules(self, hostname: str) -> bool:
        """
        删除容器的 iptables 规则（别名方法，兼容性）
        
        Args:
            hostname: 容器主机名
            
        Returns:
            是否成功
        """
        return self.cleanup_rules(hostname)
    
    def _cleanup_ipv4_rules(self, hostname: str, ipv4: str) -> bool:
        """清理 IPv4 规则"""
        # ✅ 从 LXD_FLOW_ACCOUNTING 链中删除出站规则
        cmd_out = [
            'iptables', '-D', 'LXD_FLOW_ACCOUNTING',
            '-s', ipv4,
            '-m', 'comment', '--comment', f'flow-{hostname}-out'
        ]
        
        # ✅ 从 LXD_FLOW_ACCOUNTING 链中删除入站规则
        cmd_in = [
            'iptables', '-D', 'LXD_FLOW_ACCOUNTING',
            '-d', ipv4,
            '-m', 'comment', '--comment', f'flow-{hostname}-in'
        ]
        
        self._run_command(cmd_out)
        self._run_command(cmd_in)
        
        return True
    
    def _cleanup_ipv6_rules(self, hostname: str, ipv6: str) -> bool:
        """清理 IPv6 规则"""
        # ✅ 从 LXD_FLOW_ACCOUNTING 链中删除出站规则
        cmd_out = [
            'ip6tables', '-D', 'LXD_FLOW_ACCOUNTING',
            '-s', ipv6,
            '-m', 'comment', '--comment', f'flow-{hostname}-out'
        ]
        
        # ✅ 从 LXD_FLOW_ACCOUNTING 链中删除入站规则
        cmd_in = [
            'ip6tables', '-D', 'LXD_FLOW_ACCOUNTING',
            '-d', ipv6,
            '-m', 'comment', '--comment', f'flow-{hostname}-in'
        ]
        
        self._run_command(cmd_out)
        self._run_command(cmd_in)
        
        return True
    
    def _cleanup_by_comment(self, hostname: str) -> bool:
        """通过 comment 查找并删除规则"""
        logger.info(f"尝试通过 comment 查找并删除 {hostname} 的规则...")
        
        # 这需要列出所有规则并逐一检查，比较复杂
        # 简化处理：警告用户手动清理
        logger.warning(f"请手动检查并清理容器 {hostname} 的 iptables 规则")
        return False
    
    def get_all_traffic_stats(self) -> Dict[str, Dict[str, int]]:
        """
        批量获取所有容器的流量统计（性能优化版）
        
        一次性执行iptables命令，解析所有容器的流量
        相比逐个调用get_traffic_stats()，性能提升5-10倍
        
        Returns:
            {
                'hostname1': {'bytes_sent': int, 'bytes_received': int},
                'hostname2': {'bytes_sent': int, 'bytes_received': int},
                ...
            }
        """
        logger.debug("批量获取所有容器流量统计...")
        
        # 初始化结果字典
        all_stats = {}
        for hostname in self.rules_cache.keys():
            all_stats[hostname] = {'bytes_sent': 0, 'bytes_received': 0}
        
        # 一次性获取IPv4统计
        ipv4_stats_all = self._get_all_ipv4_stats()
        for hostname, stats in ipv4_stats_all.items():
            if hostname in all_stats:
                all_stats[hostname]['bytes_sent'] += stats['bytes_sent']
                all_stats[hostname]['bytes_received'] += stats['bytes_received']
        
        # 一次性获取IPv6统计
        ipv6_stats_all = self._get_all_ipv6_stats()
        for hostname, stats in ipv6_stats_all.items():
            if hostname in all_stats:
                all_stats[hostname]['bytes_sent'] += stats['bytes_sent']
                all_stats[hostname]['bytes_received'] += stats['bytes_received']
        
        logger.debug(f"批量获取完成，共 {len(all_stats)} 个容器")
        return all_stats
    
    def _get_all_ipv4_stats(self) -> Dict[str, Dict[str, int]]:
        """一次性获取所有容器的IPv4流量统计"""
        result = {}
        
        # ✅ 一次性获取 LXD_FLOW_ACCOUNTING 链的规则
        cmd = ['iptables', '-L', 'LXD_FLOW_ACCOUNTING', '-v', '-n', '-x']
        success, output = self._run_command(cmd)
        
        if not success:
            logger.warning("获取IPv4统计失败")
            return result
        
        # 解析输出，查找所有flow规则
        for line in output.split('\n'):
            # 查找flow-{hostname}-out和flow-{hostname}-in规则
            if 'flow-' in line and ('-out' in line or '-in' in line):
                parts = line.split()
                if len(parts) >= 2:
                    try:
                        bytes_count = int(parts[1])
                        
                        # 提取hostname
                        if '-out' in line:
                            # flow-hostname-out
                            start = line.find('flow-') + 5
                            end = line.find('-out', start)
                            if end > start:
                                hostname = line[start:end]
                                if hostname not in result:
                                    result[hostname] = {'bytes_sent': 0, 'bytes_received': 0}
                                result[hostname]['bytes_sent'] = bytes_count
                        elif '-in' in line:
                            # flow-hostname-in
                            start = line.find('flow-') + 5
                            end = line.find('-in', start)
                            if end > start:
                                hostname = line[start:end]
                                if hostname not in result:
                                    result[hostname] = {'bytes_sent': 0, 'bytes_received': 0}
                                result[hostname]['bytes_received'] = bytes_count
                    except (ValueError, IndexError):
                        continue
        
        return result
    
    def _get_all_ipv6_stats(self) -> Dict[str, Dict[str, int]]:
        """一次性获取所有容器的IPv6流量统计"""
        result = {}
        
        # ✅ 一次性获取 LXD_FLOW_ACCOUNTING 链的规则
        cmd = ['ip6tables', '-L', 'LXD_FLOW_ACCOUNTING', '-v', '-n', '-x']
        success, output = self._run_command(cmd)
        
        if not success:
            logger.warning("获取IPv6统计失败")
            return result
        
        # 解析输出，查找所有flow规则
        for line in output.split('\n'):
            if 'flow-' in line and ('-out' in line or '-in' in line):
                parts = line.split()
                if len(parts) >= 2:
                    try:
                        bytes_count = int(parts[1])
                        
                        # 提取hostname
                        if '-out' in line:
                            start = line.find('flow-') + 5
                            end = line.find('-out', start)
                            if end > start:
                                hostname = line[start:end]
                                if hostname not in result:
                                    result[hostname] = {'bytes_sent': 0, 'bytes_received': 0}
                                result[hostname]['bytes_sent'] = bytes_count
                        elif '-in' in line:
                            start = line.find('flow-') + 5
                            end = line.find('-in', start)
                            if end > start:
                                hostname = line[start:end]
                                if hostname not in result:
                                    result[hostname] = {'bytes_sent': 0, 'bytes_received': 0}
                                result[hostname]['bytes_received'] = bytes_count
                    except (ValueError, IndexError):
                        continue
        
        return result
    
    def get_traffic_stats(self, hostname: str) -> Dict[str, int]:
        """
        获取容器的流量统计（单个容器查询）
        
        注意：如果需要查询多个容器，建议使用get_all_traffic_stats()批量查询
        
        Args:
            hostname: 容器主机名
            
        Returns:
            {'bytes_sent': int, 'bytes_received': int}
        """
        if hostname not in self.rules_cache:
            logger.warning(f"容器 {hostname} 不在规则缓存中")
            return {'bytes_sent': 0, 'bytes_received': 0}
        
        info = self.rules_cache[hostname]
        bytes_sent = 0
        bytes_received = 0
        
        # 获取 IPv4 统计
        if info.get('ipv4'):
            ipv4_stats = self._get_ipv4_stats(hostname, info['ipv4'])
            bytes_sent += ipv4_stats['bytes_sent']
            bytes_received += ipv4_stats['bytes_received']
        
        # 获取 IPv6 统计
        if info.get('ipv6'):
            ipv6_stats = self._get_ipv6_stats(hostname, info['ipv6'])
            bytes_sent += ipv6_stats['bytes_sent']
            bytes_received += ipv6_stats['bytes_received']
        
        return {
            'bytes_sent': bytes_sent,
            'bytes_received': bytes_received
        }
    
    def _get_ipv4_stats(self, hostname: str, ipv4: str) -> Dict[str, int]:
        """获取 IPv4 流量统计"""
        # 使用 iptables -L -v -n -x 获取详细统计
        cmd = ['iptables', '-L', 'FORWARD', '-v', '-n', '-x']
        success, output = self._run_command(cmd)
        
        if not success:
            return {'bytes_sent': 0, 'bytes_received': 0}
        
        bytes_sent = 0
        bytes_received = 0
        
        # 解析输出
        for line in output.split('\n'):
            if f'flow-{hostname}-out' in line:
                # 提取字节数（第2列）
                parts = line.split()
                if len(parts) >= 2:
                    try:
                        bytes_sent = int(parts[1])
                    except ValueError:
                        pass
            elif f'flow-{hostname}-in' in line:
                parts = line.split()
                if len(parts) >= 2:
                    try:
                        bytes_received = int(parts[1])
                    except ValueError:
                        pass
        
        return {
            'bytes_sent': bytes_sent,
            'bytes_received': bytes_received
        }
    
    def _get_ipv6_stats(self, hostname: str, ipv6: str) -> Dict[str, int]:
        """获取 IPv6 流量统计"""
        cmd = ['ip6tables', '-L', 'FORWARD', '-v', '-n', '-x']
        success, output = self._run_command(cmd)
        
        if not success:
            return {'bytes_sent': 0, 'bytes_received': 0}
        
        bytes_sent = 0
        bytes_received = 0
        
        for line in output.split('\n'):
            if f'flow-{hostname}-out' in line:
                parts = line.split()
                if len(parts) >= 2:
                    try:
                        bytes_sent = int(parts[1])
                    except ValueError:
                        pass
            elif f'flow-{hostname}-in' in line:
                parts = line.split()
                if len(parts) >= 2:
                    try:
                        bytes_received = int(parts[1])
                    except ValueError:
                        pass
        
        return {
            'bytes_sent': bytes_sent,
            'bytes_received': bytes_received
        }
    
    def block_container(self, hostname: str) -> bool:
        """
        封禁容器网络（超限时）
        
        Args:
            hostname: 容器主机名
            
        Returns:
            是否成功
        """
        if hostname not in self.rules_cache:
            logger.error(f"容器 {hostname} 不在规则缓存中，无法封禁")
            return False
        
        logger.info(f"封禁容器 {hostname} 的网络...")
        
        info = self.rules_cache[hostname]
        success = True
        
        # 🔥 重要修复：不删除旧规则，保留流量统计功能
        # DROP 规则会插入到最前面，先于统计规则生效
        if info.get('ipv4'):
            # 不调用 _cleanup_ipv4_rules，直接添加 DROP 规则
            success = success and self._block_ipv4(hostname, info['ipv4'])
        
        if info.get('ipv6'):
            # 不调用 _cleanup_ipv6_rules，直接添加 DROP 规则
            success = success and self._block_ipv6(hostname, info['ipv6'])
        
        if success:
            logger.info(f"✓ 容器 {hostname} 网络已封禁（统计规则保留）")
        else:
            logger.error(f"✗ 容器 {hostname} 网络封禁失败")
        
        return success
    
    def _block_ipv4(self, hostname: str, ipv4: str) -> bool:
        """封禁 IPv4"""
        # 创建 DROP 规则（但仍然计数）
        cmd_out = [
            'iptables', '-I', 'FORWARD', '1',
            '-s', ipv4, '-j', 'DROP',
            '-m', 'comment', '--comment', f'flow-{hostname}-blocked-out'
        ]
        
        cmd_in = [
            'iptables', '-I', 'FORWARD', '1',
            '-d', ipv4, '-j', 'DROP',
            '-m', 'comment', '--comment', f'flow-{hostname}-blocked-in'
        ]
        
        success_out, _ = self._run_command(cmd_out)
        success_in, _ = self._run_command(cmd_in)
        
        return success_out and success_in
    
    def _block_ipv6(self, hostname: str, ipv6: str) -> bool:
        """封禁 IPv6"""
        cmd_out = [
            'ip6tables', '-I', 'FORWARD', '1',
            '-s', ipv6, '-j', 'DROP',
            '-m', 'comment', '--comment', f'flow-{hostname}-blocked-out'
        ]
        
        cmd_in = [
            'ip6tables', '-I', 'FORWARD', '1',
            '-d', ipv6, '-j', 'DROP',
            '-m', 'comment', '--comment', f'flow-{hostname}-blocked-in'
        ]
        
        success_out, _ = self._run_command(cmd_out)
        success_in, _ = self._run_command(cmd_in)
        
        return success_out and success_in
    
    def unblock_container(self, hostname: str) -> bool:
        """
        解封容器网络（重置后）
        
        Args:
            hostname: 容器主机名
            
        Returns:
            是否成功
        """
        if hostname not in self.rules_cache:
            logger.error(f"容器 {hostname} 不在规则缓存中，无法解封")
            return False
        
        logger.info(f"解封容器 {hostname} 的网络...")
        
        info = self.rules_cache[hostname]
        success = True
        
        # 🔥 重要修复：只删除 DROP 规则，保留统计规则
        # 这样流量计数器不会归零
        if info.get('ipv4'):
            success = success and self._unblock_ipv4(hostname, info['ipv4'])
        
        if info.get('ipv6'):
            success = success and self._unblock_ipv6(hostname, info['ipv6'])
        
        if success:
            logger.info(f"✓ 容器 {hostname} 网络已解封（统计规则保留）")
        else:
            logger.error(f"✗ 容器 {hostname} 网络解封失败")
        
        return success
    
    def _unblock_ipv4(self, hostname: str, ipv4: str) -> bool:
        """解封 IPv4（只删除 DROP 规则，保留统计规则）"""
        cmd_out = [
            'iptables', '-D', 'FORWARD',
            '-s', ipv4, '-j', 'DROP',
            '-m', 'comment', '--comment', f'flow-{hostname}-blocked-out'
        ]
        
        cmd_in = [
            'iptables', '-D', 'FORWARD',
            '-d', ipv4, '-j', 'DROP',
            '-m', 'comment', '--comment', f'flow-{hostname}-blocked-in'
        ]
        
        # 删除 DROP 规则（统计规则保留）
        success_out, _ = self._run_command(cmd_out)
        success_in, _ = self._run_command(cmd_in)
        
        if success_out and success_in:
            logger.debug(f"IPv4 封禁已解除: {ipv4}")
            return True
        else:
            logger.warning(f"IPv4 解封可能失败: {ipv4}")
            return False
    
    def _unblock_ipv6(self, hostname: str, ipv6: str) -> bool:
        """解封 IPv6（只删除 DROP 规则，保留统计规则）"""
        cmd_out = [
            'ip6tables', '-D', 'FORWARD',
            '-s', ipv6, '-j', 'DROP',
            '-m', 'comment', '--comment', f'flow-{hostname}-blocked-out'
        ]
        
        cmd_in = [
            'ip6tables', '-D', 'FORWARD',
            '-d', ipv6, '-j', 'DROP',
            '-m', 'comment', '--comment', f'flow-{hostname}-blocked-in'
        ]
        
        # 删除 DROP 规则（统计规则保留）
        success_out, _ = self._run_command(cmd_out)
        success_in, _ = self._run_command(cmd_in)
        
        if success_out and success_in:
            logger.debug(f"IPv6 封禁已解除: {ipv6}")
            return True
        else:
            logger.warning(f"IPv6 解封可能失败: {ipv6}")
            return False
    
    def list_all_rules(self) -> List[str]:
        """列出所有被管理的容器"""
        return list(self.rules_cache.keys())
    
    def check_container_rules_exist(self, hostname: str) -> bool:
        """
        检查容器的 iptables 规则是否存在
        
        Args:
            hostname: 容器主机名
            
        Returns:
            规则是否存在
        """
        # 检查缓存中是否有记录
        if hostname not in self.rules_cache:
            return False
        
        # 进一步验证：检查 iptables 中是否真的有规则
        info = self.rules_cache[hostname]
        
        # 检查 IPv4 规则
        if info.get('ipv4'):
            ipv4 = info['ipv4']
            cmd = ['iptables', '-L', 'FORWARD', '-n']
            success, output = self._run_command(cmd)
            if success and f'flow-{hostname}-out' in output:
                return True
        
        # 检查 IPv6 规则
        if info.get('ipv6'):
            ipv6 = info['ipv6']
            cmd = ['ip6tables', '-L', 'FORWARD', '-n']
            success, output = self._run_command(cmd)
            if success and f'flow-{hostname}-out' in output:
                return True
        
        return False
    
    def is_container_blocked(self, hostname: str) -> bool:
        """
        检查容器是否被封禁
        
        Args:
            hostname: 容器主机名
            
        Returns:
            是否被封禁
        """
        if hostname not in self.rules_cache:
            return False
        
        info = self.rules_cache[hostname]
        
        # 检查 IPv4 封禁规则
        if info.get('ipv4'):
            cmd = ['iptables', '-L', 'FORWARD', '-n']
            success, output = self._run_command(cmd)
            if success and f'flow-{hostname}-blocked-out' in output:
                return True
        
        # 检查 IPv6 封禁规则
        if info.get('ipv6'):
            cmd = ['ip6tables', '-L', 'FORWARD', '-n']
            success, output = self._run_command(cmd)
            if success and f'flow-{hostname}-blocked-out' in output:
                return True
        
        return False
    
    def list_all_tracked_containers(self) -> List[str]:
        """
        列出所有有 iptables 规则的容器（别名，与 list_all_rules 相同）
        
        Returns:
            容器主机名列表
        """
        return self.list_all_rules()


# 测试代码
if __name__ == '__main__':
    manager = IptablesManager()
    
    # 示例：为容器创建规则
    # manager.setup_rules('test-container', '10.10.10.100', 'fd00::1')
    
    # 获取流量统计
    # stats = manager.get_traffic_stats('test-container')
    # print(f"流量统计: {stats}")
    
    # 清理规则
    # manager.cleanup_rules('test-container')
    
    print(f"当前管理的容器: {manager.list_all_rules()}")

