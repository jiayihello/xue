#!/usr/bin/env python3
"""
IPv6 分配状态重建工具

用途：
  当后端重新安装后，ipv6_allocations.json 丢失，
  导致新后端尝试分配已被使用的 IPv6 地址。
  本工具扫描现有容器，重建 IPv6 分配状态文件。

使用场景：
  1. 后端重新安装后，IPv6 分配冲突
  2. ipv6_allocations.json 文件损坏或丢失
  3. 需要从现有容器重建分配状态

使用方法：
  sudo python3 tools/rebuild_ipv6_state.py
"""

import json
import os
import sys
import ipaddress
import logging
from datetime import datetime

# 添加父目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from pylxd import Client
    from config_handler import app_config
except ImportError as e:
    print(f"❌ 导入模块失败: {e}")
    print("请确保已安装所需依赖: pip3 install pylxd")
    sys.exit(1)

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

ALLOC_FILE = 'ipv6_allocations.json'
BACKUP_DIR = 'ipv6_state_backups'


def print_banner():
    """打印标题"""
    print("\n" + "=" * 60)
    print("  IPv6 分配状态重建工具")
    print("=" * 60 + "\n")


def check_ipv6_mode():
    """检查 IPv6 模式"""
    if app_config.ipv6_mode == 'OFF':
        print("❌ IPv6 模式未启用（IPV6_MODE = OFF）")
        print("   本工具仅适用于 IPv6-Only 或 IPv4+IPv6 混合模式")
        sys.exit(1)
    
    if not app_config.ipv6_prefix:
        print("❌ 未配置 IPv6 前缀（IPV6_PREFIX 为空）")
        sys.exit(1)
    
    print("✓ IPv6 模式:", app_config.ipv6_mode)
    print("✓ IPv6 前缀:", app_config.ipv6_prefix)


def backup_existing_state():
    """备份现有状态文件"""
    if not os.path.exists(ALLOC_FILE):
        print("ℹ️  未找到现有状态文件，无需备份")
        return None
    
    # 创建备份目录
    if not os.path.exists(BACKUP_DIR):
        os.makedirs(BACKUP_DIR)
    
    # 生成备份文件名
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_file = os.path.join(BACKUP_DIR, f'ipv6_allocations_backup_{timestamp}.json')
    
    # 复制文件
    with open(ALLOC_FILE, 'r', encoding='utf-8') as src:
        with open(backup_file, 'w', encoding='utf-8') as dst:
            dst.write(src.read())
    
    print(f"✓ 已备份现有状态到: {backup_file}")
    return backup_file


def get_ipv6_from_container(container) -> list:
    """从容器中提取 IPv6 地址"""
    ipv6_addresses = []
    
    try:
        # 方法1：从 devices 中获取
        devices = container.devices
        for device_name, device_config in devices.items():
            if device_config.get('type') == 'nic':
                # 检查 ROUTED 模式的 ipv6.address
                if 'ipv6.address' in device_config:
                    ipv6_addresses.append(device_config['ipv6.address'])
        
        # 方法2：从容器状态中获取
        if container.status == 'Running':
            state = container.state()
            network = state.network or {}
            
            for iface_name, iface_data in network.items():
                if iface_name == 'lo':
                    continue
                
                addresses = iface_data.get('addresses', [])
                for addr_info in addresses:
                    if addr_info.get('family') == 'inet6':
                        address = addr_info.get('address', '')
                        scope = addr_info.get('scope', '')
                        
                        # 只获取全局地址
                        if scope == 'global':
                            # 移除前缀长度
                            if '/' in address:
                                address = address.split('/')[0]
                            ipv6_addresses.append(address)
    
    except Exception as e:
        logger.warning(f"从容器 {container.name} 获取 IPv6 时出错: {e}")
    
    # 去重
    return list(set(ipv6_addresses))


def calculate_index_from_address(prefix_str: str, ipv6_str: str) -> int:
    """从 IPv6 地址计算索引"""
    try:
        prefix_net = ipaddress.ip_network(prefix_str, strict=False)
        ipv6_addr = ipaddress.ip_address(ipv6_str)
        
        base = int(prefix_net.network_address)
        addr_int = int(ipv6_addr)
        
        index = addr_int - base
        return index
    except Exception as e:
        logger.warning(f"计算 IPv6 索引失败: {e}")
        return -1


def scan_containers():
    """扫描所有容器，提取 IPv6 分配信息"""
    print("\n" + "-" * 60)
    print("  扫描容器")
    print("-" * 60 + "\n")
    
    try:
        client = Client()
        containers = client.containers.all()
    except Exception as e:
        print(f"❌ 连接 LXD 失败: {e}")
        sys.exit(1)
    
    if not containers:
        print("⚠️  未找到任何容器")
        return {}
    
    print(f"找到 {len(containers)} 个容器\n")
    
    allocations = {}
    max_index = 0
    
    for container in containers:
        ipv6_list = get_ipv6_from_container(container)
        
        if not ipv6_list:
            print(f"  • {container.name:15s}  状态: {container.status:10s}  IPv6: (无)")
            continue
        
        # 通常一个容器只有一个全局 IPv6
        ipv6_addr = ipv6_list[0]
        print(f"  • {container.name:15s}  状态: {container.status:10s}  IPv6: {ipv6_addr}")
        
        # 计算索引
        index = calculate_index_from_address(app_config.ipv6_prefix, ipv6_addr)
        if index > max_index:
            max_index = index
        
        # 记录分配
        allocations[container.name] = ipv6_addr
    
    print(f"\n✓ 扫描完成，找到 {len(allocations)} 个 IPv6 分配")
    
    return allocations, max_index + 1  # cursor 应该是下一个可用的索引


def build_state(allocations: dict, cursor: int):
    """构建状态文件"""
    state = {
        "allocations": allocations,
        "cursor": cursor
    }
    return state


def save_state(state: dict):
    """保存状态文件"""
    print("\n" + "-" * 60)
    print("  保存状态文件")
    print("-" * 60 + "\n")
    
    try:
        tmp_file = ALLOC_FILE + '.tmp'
        with open(tmp_file, 'w', encoding='utf-8') as f:
            json.dump(state, f, indent=2, ensure_ascii=False)
        
        # 原子替换
        os.replace(tmp_file, ALLOC_FILE)
        
        print(f"✓ 状态文件已保存: {ALLOC_FILE}")
        print(f"  • 分配记录: {len(state['allocations'])} 个")
        print(f"  • 下一个索引: {state['cursor']}")
    except Exception as e:
        print(f"❌ 保存状态文件失败: {e}")
        sys.exit(1)


def verify_state():
    """验证状态文件"""
    print("\n" + "-" * 60)
    print("  验证状态文件")
    print("-" * 60 + "\n")
    
    try:
        with open(ALLOC_FILE, 'r', encoding='utf-8') as f:
            state = json.load(f)
        
        allocations = state.get('allocations', {})
        cursor = state.get('cursor', 0)
        
        print(f"✓ 状态文件读取成功")
        print(f"  • 分配记录: {len(allocations)} 个")
        print(f"  • 下一个索引: {cursor}")
        
        if allocations:
            print("\n  前 5 个分配:")
            for i, (hostname, ipv6) in enumerate(list(allocations.items())[:5]):
                print(f"    {i+1}. {hostname:15s} → {ipv6}")
        
        return True
    except Exception as e:
        print(f"❌ 验证失败: {e}")
        return False


def main():
    print_banner()
    
    # 1. 检查配置
    print("=" * 60)
    print("  检查配置")
    print("=" * 60 + "\n")
    check_ipv6_mode()
    
    # 2. 备份现有状态
    print("\n" + "=" * 60)
    print("  备份现有状态")
    print("=" * 60 + "\n")
    backup_file = backup_existing_state()
    
    # 3. 扫描容器
    allocations, cursor = scan_containers()
    
    if not allocations:
        print("\n⚠️  未找到任何 IPv6 分配，创建空状态文件")
        allocations = {}
        cursor = 10  # 从 10 开始，避开保留地址
    
    # 4. 构建状态
    state = build_state(allocations, cursor)
    
    # 5. 保存状态
    save_state(state)
    
    # 6. 验证状态
    if verify_state():
        print("\n" + "=" * 60)
        print("  ✅ 状态重建完成！")
        print("=" * 60 + "\n")
        
        print("后续操作:")
        print("  1. 重启后端服务:")
        print("     sudo systemctl restart lxd-api.service")
        print("\n  2. 测试创建新容器:")
        print("     在魔方财务中开通新容器")
        print("\n  3. 如果仍有问题，检查日志:")
        print("     sudo journalctl -u lxd-api.service -f")
        
        if backup_file:
            print(f"\n  备份文件: {backup_file}")
            print("  如需回滚，复制回 ipv6_allocations.json")
    else:
        print("\n❌ 状态验证失败，请检查文件")
        sys.exit(1)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⚠️  操作已取消")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ 发生错误: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

