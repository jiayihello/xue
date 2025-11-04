#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
批量重新分配 IPv6 地址工具

适用场景：
1. 宿主机 IPv6 段变更（如更换机房、更换 ISP）
2. app.ini 中的 IPV6_PREFIX 已修改
3. 需要给所有容器重新分配新的 IPv6 地址

功能：
- 自动检测所有 IPv6-Only 容器
- 批量重新分配新段的 IPv6 地址
- 更新容器配置
- 清理旧的 NDP 代理
- 添加新的 NDP 代理

使用方法：
python3 reassign_ipv6_batch.py            # 交互模式（需要确认）
python3 reassign_ipv6_batch.py --yes      # 自动模式（跳过确认）
python3 reassign_ipv6_batch.py -y         # 自动模式（简写）
"""

import os
import sys
import json
import logging
import subprocess
from pathlib import Path

# 添加 server 目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from pylxd import Client
    from config_handler import app_config
    from ipv6_manager import allocate, release, _load_state, _save_state
except ImportError as e:
    print(f"❌ 导入模块失败: {e}")
    print("请确保在 server 目录下运行此脚本")
    sys.exit(1)

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class IPv6Reassigner:
    """IPv6 地址批量重新分配器"""
    
    def __init__(self):
        self.client = Client()
        self.parent_if = app_config.ipv6_interface or app_config.main_interface
        self.ipv6_mode = getattr(app_config, 'ipv6_mode', 'OFF')
        self.ipv6_prefix = getattr(app_config, 'ipv6_prefix', None)
        self.backup_file = None
    
    def check_prerequisites(self):
        """检查前置条件"""
        print("=" * 60)
        print("  检查系统配置")
        print("=" * 60)
        print()
        
        # 检查 IPv6 模式
        if self.ipv6_mode.upper() != 'ROUTED':
            print(f"❌ IPv6 模式错误: {self.ipv6_mode}")
            print("   只有 ROUTED 模式才需要重新分配 IPv6")
            return False
        print(f"✓ IPv6 模式: {self.ipv6_mode}")
        
        # 检查 IPv6 前缀
        if not self.ipv6_prefix:
            print("❌ 未配置 IPV6_PREFIX")
            print("   请在 app.ini 中配置 IPV6_PREFIX")
            return False
        print(f"✓ IPv6 前缀: {self.ipv6_prefix}")
        
        # 检查网卡
        if not self.parent_if:
            print("❌ 未配置网卡接口")
            return False
        print(f"✓ 父网卡: {self.parent_if}")
        
        print()
        return True
    
    def find_ipv6_containers(self):
        """查找所有使用 IPv6 的容器"""
        containers = []
        
        print("=" * 60)
        print("  扫描容器")
        print("=" * 60)
        print()
        
        for container in self.client.containers.all():
            # 检查是否有 eth0v6 设备
            if 'eth0v6' in container.devices:
                device = container.devices['eth0v6']
                old_ipv6 = device.get('ipv6.address', 'N/A')
                
                containers.append({
                    'name': container.name,
                    'container': container,
                    'old_ipv6': old_ipv6,
                    'status': container.status
                })
                
                print(f"找到: {container.name}")
                print(f"  当前 IPv6: {old_ipv6}")
                print(f"  状态: {container.status}")
                print()
        
        print(f"共找到 {len(containers)} 个 IPv6 容器")
        print()
        
        return containers
    
    def backup_current_allocations(self):
        """备份当前的 IPv6 分配"""
        try:
            state = _load_state()
            allocations = state.get('allocations', {})
            
            if not allocations:
                print("⚠️  当前没有 IPv6 分配记录")
                return True
            
            # 创建备份
            import time
            backup_filename = f"ipv6_allocations_backup_{int(time.time())}.json"
            backup_path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                backup_filename
            )
            
            with open(backup_path, 'w') as f:
                json.dump(state, f, indent=2)
            
            self.backup_file = backup_path
            print(f"✓ 已备份当前分配到: {backup_path}")
            print(f"  备份了 {len(allocations)} 个分配记录")
            print()
            
            return True
            
        except Exception as e:
            print(f"❌ 备份失败: {e}")
            return False
    
    def clear_old_ndp_proxies(self, old_ipv6):
        """清理旧的 NDP 代理"""
        if not old_ipv6 or old_ipv6 == 'N/A':
            return
        
        try:
            # 移除旧的 NDP 代理
            ipv6_addr = old_ipv6.split('/')[0]
            subprocess.run([
                'ip', '-6', 'neigh', 'del', 'proxy',
                ipv6_addr, 'dev', self.parent_if
            ], stderr=subprocess.DEVNULL, check=False)
            logger.debug(f"清理旧 NDP 代理: {ipv6_addr}")
        except Exception as e:
            logger.debug(f"清理 NDP 代理失败: {e}")
    
    def add_new_ndp_proxy(self, new_ipv6):
        """添加新的 NDP 代理"""
        try:
            ipv6_addr = new_ipv6.split('/')[0]
            subprocess.run([
                'ip', '-6', 'neigh', 'add', 'proxy',
                ipv6_addr, 'dev', self.parent_if
            ], stderr=subprocess.DEVNULL, check=False)
            logger.debug(f"添加新 NDP 代理: {ipv6_addr}")
            return True
        except Exception as e:
            logger.warning(f"添加 NDP 代理失败: {e}")
            return False
    
    def reassign_container_ipv6(self, container_info):
        """为单个容器重新分配 IPv6"""
        container = container_info['container']
        hostname = container_info['name']
        old_ipv6 = container_info['old_ipv6']
        
        try:
            # 1. 从旧系统释放（如果存在）
            try:
                release(hostname)
            except:
                pass
            
            # 2. 分配新的 IPv6 地址
            new_ipv6 = allocate(hostname)
            if not new_ipv6:
                return False, "分配新 IPv6 失败"
            
            # 3. 更新容器配置
            # 先删除旧设备
            if 'eth0v6' in container.devices:
                del container.devices['eth0v6']
            
            # 添加新设备
            container.devices['eth0v6'] = {
                'type': 'nic',
                'name': 'eth0v6',
                'nictype': 'routed',
                'parent': self.parent_if,
                'ipv6.address': new_ipv6
            }
            container.save(wait=True)
            
            # 4. 清理旧的 NDP 代理
            self.clear_old_ndp_proxies(old_ipv6)
            
            # 5. 添加新的 NDP 代理
            self.add_new_ndp_proxy(new_ipv6)
            
            return True, new_ipv6
            
        except Exception as e:
            logger.error(f"重新分配失败: {e}")
            return False, str(e)
    
    def reassign_all(self, containers, confirm=True):
        """批量重新分配所有容器的 IPv6"""
        if not containers:
            print("没有需要处理的容器")
            return
        
        print("=" * 60)
        print("  准备重新分配 IPv6")
        print("=" * 60)
        print()
        
        print(f"将处理 {len(containers)} 个容器:")
        for c in containers:
            print(f"  • {c['name']}: {c['old_ipv6']}")
        print()
        
        print("⚠️  警告:")
        print("  1. 此操作会更改所有容器的 IPv6 地址")
        print("  2. 容器的连接会短暂中断")
        print("  3. 已创建备份，出错可恢复")
        print()
        
        if confirm:
            response = input("确认执行？[y/N]: ").strip().lower()
            if response != 'y':
                print("操作已取消")
                return
        
        print()
        print("=" * 60)
        print("  开始重新分配")
        print("=" * 60)
        print()
        
        success_count = 0
        failed_count = 0
        results = []
        
        for i, container_info in enumerate(containers, 1):
            hostname = container_info['name']
            old_ipv6 = container_info['old_ipv6']
            
            print(f"[{i}/{len(containers)}] 处理: {hostname}")
            print(f"  旧 IPv6: {old_ipv6}")
            
            success, result = self.reassign_container_ipv6(container_info)
            
            if success:
                print(f"  ✓ 新 IPv6: {result}")
                success_count += 1
                results.append({
                    'hostname': hostname,
                    'old_ipv6': old_ipv6,
                    'new_ipv6': result,
                    'status': 'success'
                })
            else:
                print(f"  ✗ 失败: {result}")
                failed_count += 1
                results.append({
                    'hostname': hostname,
                    'old_ipv6': old_ipv6,
                    'new_ipv6': None,
                    'status': 'failed',
                    'error': result
                })
            
            print()
        
        # 保存结果报告
        self.save_report(results)
        
        # 显示摘要
        print("=" * 60)
        print("  完成")
        print("=" * 60)
        print()
        print(f"成功: {success_count}")
        print(f"失败: {failed_count}")
        print(f"总计: {len(containers)}")
        print()
        
        if self.backup_file:
            print(f"备份文件: {self.backup_file}")
        print()
        
        return results
    
    def save_report(self, results):
        """保存重新分配报告"""
        try:
            import time
            report_filename = f"ipv6_reassign_report_{int(time.time())}.json"
            report_path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                report_filename
            )
            
            with open(report_path, 'w') as f:
                json.dump({
                    'timestamp': time.time(),
                    'ipv6_prefix': self.ipv6_prefix,
                    'parent_interface': self.parent_if,
                    'results': results
                }, f, indent=2)
            
            print(f"✓ 报告已保存: {report_path}")
            print()
            
        except Exception as e:
            logger.warning(f"保存报告失败: {e}")


def show_current_config():
    """显示当前配置"""
    print()
    print("=" * 60)
    print("  当前配置")
    print("=" * 60)
    print()
    
    print(f"IPv4 模式: {getattr(app_config, 'ipv4_mode', 'N/A')}")
    print(f"IPv6 模式: {getattr(app_config, 'ipv6_mode', 'N/A')}")
    print(f"IPv6 前缀: {getattr(app_config, 'ipv6_prefix', 'N/A')}")
    print(f"主网卡: {getattr(app_config, 'main_interface', 'N/A')}")
    print(f"IPv6 网卡: {getattr(app_config, 'ipv6_interface', 'N/A')}")
    print()


def main():
    """主函数"""
    # 检查帮助参数
    if '-h' in sys.argv or '--help' in sys.argv:
        print(__doc__)
        print("示例:")
        print("  # 交互模式（需要确认）")
        print("  sudo python3 reassign_ipv6_batch.py")
        print()
        print("  # 自动模式（跳过确认）")
        print("  sudo python3 reassign_ipv6_batch.py --yes")
        print()
        sys.exit(0)
    
    print()
    print("=" * 60)
    print("  IPv6 地址批量重新分配工具")
    print("=" * 60)
    print()
    
    # 检查 root 权限
    if os.geteuid() != 0:
        print("❌ 需要 root 权限")
        print("   请使用: sudo python3 reassign_ipv6_batch.py")
        sys.exit(1)
    
    # 检查是否通过命令行参数跳过确认
    skip_confirm = '--yes' in sys.argv or '-y' in sys.argv
    if skip_confirm:
        print("⚡ 自动模式：已跳过确认步骤")
        print()
    
    # 显示当前配置
    show_current_config()
    
    # 创建重新分配器
    reassigner = IPv6Reassigner()
    
    # 检查前置条件
    if not reassigner.check_prerequisites():
        print()
        print("前置条件检查失败，请修复后重试")
        sys.exit(1)
    
    # 查找 IPv6 容器
    containers = reassigner.find_ipv6_containers()
    
    if not containers:
        print("没有找到使用 IPv6 的容器")
        sys.exit(0)
    
    # 备份当前分配
    if not reassigner.backup_current_allocations():
        print()
        print("备份失败，为安全起见停止操作")
        sys.exit(1)
    
    # 执行批量重新分配
    results = reassigner.reassign_all(containers, confirm=not skip_confirm)
    
    # 显示后续操作建议
    print()
    print("=" * 60)
    print("  后续操作")
    print("=" * 60)
    print()
    print("1. 验证容器连接:")
    print("   lxc list")
    print()
    print("2. 测试容器网络:")
    print("   lxc exec CONTAINER_NAME -- ping6 -c 3 ipv6.google.com")
    print()
    print("3. 查看 NDP 代理:")
    print(f"   ip -6 neigh show proxy dev {reassigner.parent_if}")
    print()
    print("4. 如需回滚，请使用备份文件:")
    if reassigner.backup_file:
        print(f"   {reassigner.backup_file}")
    print()


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n操作已取消")
        sys.exit(0)
    except Exception as e:
        logger.error(f"发生错误: {e}", exc_info=True)
        sys.exit(1)

