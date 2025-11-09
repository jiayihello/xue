#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
将所有使用ULA内网IPv6的容器重新分配公网IPv6地址

功能：
- 检测所有eth0v6使用ULA地址(fd00::/8)的容器
- 删除旧的ULA地址
- 从公网前缀重新分配IPv6
- 更新容器配置

使用方法：
python3 fix_ula_to_public_ipv6.py            # 交互模式
python3 fix_ula_to_public_ipv6.py --yes      # 自动模式
"""

import os
import sys
import ipaddress
import logging

# 添加父目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from pylxd import Client
    from config_handler import app_config
    from ipv6_manager import allocate, release
except ImportError as e:
    print(f"❌ 导入模块失败: {e}")
    sys.exit(1)

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)


def is_ula_address(addr_str):
    """检查是否为ULA地址 (fd00::/8)"""
    try:
        addr = ipaddress.IPv6Address(addr_str)
        # ULA范围: fd00::/8
        return addr.packed[0] == 0xfd
    except Exception:
        return False


def get_ula_containers(client):
    """获取所有使用ULA IPv6的容器"""
    ula_containers = []
    
    for container in client.containers.all():
        if container.status != 'Running':
            continue
            
        # 检查是否有eth0v6设备
        devices = container.devices
        if 'eth0v6' not in devices:
            continue
            
        # 获取eth0v6的IPv6地址
        eth0v6 = devices['eth0v6']
        ipv6_addr = eth0v6.get('ipv6.address', '')
        
        if ipv6_addr and is_ula_address(ipv6_addr):
            ula_containers.append({
                'name': container.name,
                'current_ipv6': ipv6_addr,
                'container': container
            })
    
    return ula_containers


def reassign_container_ipv6(container_info, parent_if):
    """为容器重新分配公网IPv6"""
    container = container_info['container']
    name = container_info['name']
    old_ipv6 = container_info['current_ipv6']
    
    try:
        # 从ipv6_manager分配新的公网IPv6
        new_ipv6 = allocate(name)
        if not new_ipv6:
            return False, "分配IPv6失败"
        
        # 更新eth0v6设备
        container.devices['eth0v6'] = {
            'type': 'nic',
            'name': 'eth0v6',
            'nictype': 'routed',
            'parent': parent_if,
            'ipv6.address': new_ipv6
        }
        container.save(wait=True)
        
        return True, new_ipv6
    except Exception as e:
        return False, str(e)


def main():
    # 检查IPv6模式
    if getattr(app_config, 'ipv6_mode', 'OFF').upper() != 'ROUTED':
        logger.error("❌ IPV6_MODE 必须设置为 ROUTED")
        sys.exit(1)
    
    ipv6_prefix = getattr(app_config, 'ipv6_prefix', None)
    if not ipv6_prefix:
        logger.error("❌ 未配置 IPV6_PREFIX")
        sys.exit(1)
    
    # 检查是否为公网前缀
    try:
        prefix = ipaddress.IPv6Network(ipv6_prefix, strict=False)
        if prefix.network_address.packed[0] == 0xfd:
            logger.error(f"❌ IPV6_PREFIX 配置的是ULA内网地址: {ipv6_prefix}")
            logger.error("请修改为公网IPv6前缀，例如: 2a01:e281:ac01:f3::/64")
            sys.exit(1)
    except Exception as e:
        logger.error(f"❌ IPV6_PREFIX 格式错误: {e}")
        sys.exit(1)
    
    parent_if = getattr(app_config, 'ipv6_interface', None) or getattr(app_config, 'main_interface', 'eth0')
    
    logger.info("=" * 60)
    logger.info("将ULA内网IPv6容器重新分配为公网IPv6")
    logger.info("=" * 60)
    logger.info(f"公网IPv6前缀: {ipv6_prefix}")
    logger.info(f"外网接口: {parent_if}")
    logger.info("")
    
    # 连接LXD
    try:
        client = Client()
    except Exception as e:
        logger.error(f"❌ 连接LXD失败: {e}")
        sys.exit(1)
    
    # 获取所有ULA容器
    ula_containers = get_ula_containers(client)
    
    if not ula_containers:
        logger.info("✅ 所有容器都已使用公网IPv6或未配置IPv6")
        return
    
    logger.info(f"发现 {len(ula_containers)} 个容器使用ULA内网IPv6:")
    logger.info("")
    for info in ula_containers:
        logger.info(f"  • {info['name']}: {info['current_ipv6']}")
    logger.info("")
    
    # 确认
    if '--yes' not in sys.argv and '-y' not in sys.argv:
        confirm = input("是否重新分配这些容器的IPv6？[y/N]: ")
        if confirm.lower() not in ['y', 'yes']:
            logger.info("已取消")
            return
    
    # 批量重新分配
    success_count = 0
    fail_count = 0
    
    logger.info("")
    logger.info("开始重新分配...")
    logger.info("")
    
    for info in ula_containers:
        name = info['name']
        old_ipv6 = info['current_ipv6']
        
        success, result = reassign_container_ipv6(info, parent_if)
        
        if success:
            logger.info(f"✅ {name}: {old_ipv6} → {result}")
            success_count += 1
        else:
            logger.error(f"❌ {name}: 失败 - {result}")
            fail_count += 1
    
    logger.info("")
    logger.info("=" * 60)
    logger.info(f"完成！成功: {success_count}, 失败: {fail_count}")
    logger.info("=" * 60)
    
    if success_count > 0:
        logger.info("")
        logger.info("⚠️  重要提示:")
        logger.info("1. 请重启 lxd-api 服务: systemctl restart lxd-api")
        logger.info("2. 在魔方财务后台同步受影响的产品")
        logger.info("3. 客户前端将显示新的公网IPv6地址")


if __name__ == '__main__':
    main()
