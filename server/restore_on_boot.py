#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
启动恢复脚本
在系统重启后，恢复所有容器的 iptables 规则和封禁状态
建议在系统启动时运行（通过 systemd）
"""

import logging
import sys
import time
from iptables_manager import IptablesManager
from flow_manager_v2 import FlowManagerV2
from lxc_manager import LXCManager

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('boot_restore.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class BootRestorer:
    """启动恢复器"""
    
    def __init__(self):
        """初始化恢复器"""
        self.iptables_mgr = IptablesManager()
        self.flow_mgr = FlowManagerV2()
        self.lxc_mgr = LXCManager()
    
    def restore_all(self) -> dict:
        """
        恢复所有容器
        
        Returns:
            恢复统计信息
        """
        logger.info("=" * 70)
        logger.info("开始恢复容器规则...")
        logger.info("=" * 70)
        
        stats = {
            'total': 0,
            'rules_added': 0,
            'blocked': 0,
            'skipped': 0,
            'errors': []
        }
        
        # 等待 LXD 完全启动
        logger.info("等待 LXD 服务完全启动...")
        time.sleep(3)
        
        try:
            # 获取所有运行中的容器
            running_containers = set(self.lxc_mgr.list_all_containers())
            logger.info(f"发现 {len(running_containers)} 个运行中的容器")
            
            # 获取数据库中的所有容器
            db_containers = self.flow_mgr.list_all_containers()
            stats['total'] = len(db_containers)
            logger.info(f"数据库中有 {stats['total']} 个容器记录")
            
            # 恢复每个容器
            for container in db_containers:
                hostname = container['hostname']
                is_blocked = container['is_blocked']
                
                try:
                    # 检查容器是否在运行
                    container_name = self.lxc_mgr.get_container_name_by_hostname(hostname)
                    if not container_name or container_name not in running_containers:
                        logger.debug(f"容器 {hostname} 未运行，跳过")
                        stats['skipped'] += 1
                        continue
                    
                    # 添加 iptables 规则
                    logger.info(f"恢复容器 {hostname} 的规则...")
                    success = self.iptables_mgr.ensure_container_rules(hostname)
                    
                    if success:
                        stats['rules_added'] += 1
                        
                        # 如果容器被封禁，恢复封禁状态
                        if is_blocked:
                            logger.info(f"恢复容器 {hostname} 的封禁状态...")
                            block_success = self.iptables_mgr.block_container(hostname)
                            if block_success:
                                stats['blocked'] += 1
                                logger.info(f"✓ 容器 {hostname} 已封禁")
                            else:
                                stats['errors'].append(f"{hostname}: 封禁失败")
                                logger.error(f"✗ 容器 {hostname} 封禁失败")
                        else:
                            logger.info(f"✓ 容器 {hostname} 规则已恢复")
                    else:
                        stats['errors'].append(f"{hostname}: 规则添加失败")
                        logger.error(f"✗ 容器 {hostname} 规则添加失败")
                
                except Exception as e:
                    stats['errors'].append(f"{hostname}: {str(e)}")
                    logger.error(f"恢复容器 {hostname} 失败: {e}")
            
            # 输出统计
            logger.info("=" * 70)
            logger.info("恢复完成:")
            logger.info(f"  总记录数: {stats['total']}")
            logger.info(f"  规则已恢复: {stats['rules_added']}")
            logger.info(f"  封禁已恢复: {stats['blocked']}")
            logger.info(f"  跳过: {stats['skipped']}")
            logger.info(f"  错误: {len(stats['errors'])}")
            
            if stats['errors']:
                logger.warning("错误详情:")
                for error in stats['errors'][:10]:
                    logger.warning(f"  - {error}")
            
            logger.info("=" * 70)
            
        except Exception as e:
            logger.error(f"恢复过程失败: {e}", exc_info=True)
            stats['errors'].append(f"全局错误: {str(e)}")
        
        return stats
    
    def verify_restoration(self) -> bool:
        """
        验证恢复是否成功
        
        Returns:
            是否成功
        """
        logger.info("验证恢复结果...")
        
        try:
            # 获取所有运行中的容器
            running_containers = self.lxc_mgr.list_all_containers()
            
            # 获取数据库中应该有规则的容器
            db_containers = self.flow_mgr.list_all_containers()
            
            success = True
            
            for container in db_containers:
                hostname = container['hostname']
                
                # 检查容器是否在运行
                container_name = self.lxc_mgr.get_container_name_by_hostname(hostname)
                if not container_name or container_name not in running_containers:
                    continue
                
                # 验证 iptables 规则
                if not self.iptables_mgr.check_container_rules_exist(hostname):
                    logger.error(f"✗ 容器 {hostname} 的规则缺失")
                    success = False
                else:
                    logger.debug(f"✓ 容器 {hostname} 规则正常")
            
            if success:
                logger.info("✓ 验证通过")
            else:
                logger.error("✗ 验证失败")
            
            return success
        
        except Exception as e:
            logger.error(f"验证失败: {e}")
            return False


def trigger_cache_invalidation():
    """触发API服务的缓存失效"""
    try:
        import requests
        import time
        from config_handler import app_config
        
        logger.info("尝试触发API服务的缓存刷新...")
        
        # 等待Flask服务就绪（最多等待30秒）
        max_retries = 30
        api_url = f'http://localhost:{app_config.http_port}/api/internal/cache/invalidate'
        
        for i in range(max_retries):
            try:
                response = requests.post(
                    api_url,
                    headers={'apikey': app_config.token},
                    timeout=2
                )
                if response.status_code == 200:
                    logger.info("✓ 已成功触发API服务缓存刷新")
                    return True
                else:
                    logger.warning(f"缓存刷新API返回非200状态码: {response.status_code}")
                break
            except requests.exceptions.ConnectionRefusedError:
                # API服务还未启动，继续等待
                if i < max_retries - 1:
                    logger.debug(f"API服务未就绪，等待... ({i+1}/{max_retries})")
                    time.sleep(1)
                    continue
                else:
                    logger.warning("API服务在30秒内未就绪，跳过缓存刷新")
                break
            except requests.exceptions.RequestException as e:
                logger.warning(f"触发缓存刷新请求失败: {e}")
                break
    except Exception as e:
        logger.warning(f"触发缓存刷新失败（非致命）: {e}")
    
    return False


def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description='启动恢复脚本')
    parser.add_argument('--verify', action='store_true', help='验证恢复结果')
    parser.add_argument('--verbose', '-v', action='store_true', help='详细输出')
    parser.add_argument('--no-cache-refresh', action='store_true', help='不触发缓存刷新')
    
    args = parser.parse_args()
    
    # 设置日志级别
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    restorer = BootRestorer()
    
    # 执行恢复
    stats = restorer.restore_all()
    
    # 触发缓存刷新（除非明确禁用）
    if not args.no_cache_refresh:
        trigger_cache_invalidation()
    
    # 验证（如果需要）
    if args.verify:
        verify_success = restorer.verify_restoration()
        if not verify_success:
            sys.exit(1)
    
    # 根据结果退出
    if stats['errors']:
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        logger.info("恢复被用户中断")
        sys.exit(130)
    except Exception as e:
        logger.error(f"恢复异常: {e}", exc_info=True)
        sys.exit(1)

