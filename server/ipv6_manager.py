import json
import os
import logging
import ipaddress
from typing import Optional

from config_handler import app_config

logger = logging.getLogger(__name__)

ALLOC_FILE = 'ipv6_allocations.json'


def _load_state():
    try:
        if os.path.exists(ALLOC_FILE):
            with open(ALLOC_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception as e:
        logger.warning(f"加载IPv6分配状态失败: {e}")
    return {"allocations": {}, "cursor": 0}


def _save_state(state):
    tmp = ALLOC_FILE + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(state, f, indent=2, ensure_ascii=False)
    os.replace(tmp, ALLOC_FILE)


def _parse_prefix(prefix: str) -> ipaddress.IPv6Network:
    try:
        net = ipaddress.ip_network(prefix, strict=False)
        if not isinstance(net, ipaddress.IPv6Network):
            raise ValueError('前缀不是IPv6网络')
        return net
    except Exception as e:
        raise ValueError(f"无效的IPv6前缀: {prefix}. 错误: {e}")


def _addr_at(prefix_net: ipaddress.IPv6Network, index: int) -> ipaddress.IPv6Address:
    # 跳过网络地址与末尾广播语义(虽然IPv6无广播，但保留一点冗余)
    base = int(prefix_net.network_address)
    addr_int = base + index
    return ipaddress.IPv6Address(addr_int)


def allocate(hostname: str, custom_ipv6: Optional[str] = None) -> Optional[str]:
    """为容器名分配可路由IPv6地址。
    
    Args:
        hostname: 容器名
        custom_ipv6: 可选的自定义IPv6地址（/128格式）
    
    返回字符串形式的IPv6地址，失败返回None。
    """
    mode = getattr(app_config, 'ipv6_mode', 'OFF')
    if mode.upper() != 'ROUTED':
        logger.debug("IPv6分配跳过：当前模式不是 ROUTED")
        return None

    state = _load_state()
    allocations = state.get('allocations', {})

    # 已分配则直接返回，确保重启后地址稳定
    if hostname in allocations:
        return allocations[hostname]

    # 如果指定了自定义IPv6地址，使用它
    if custom_ipv6:
        try:
            # 验证IPv6地址格式
            ipv6_obj = ipaddress.ip_address(custom_ipv6.split('/')[0])
            if not isinstance(ipv6_obj, ipaddress.IPv6Address):
                raise ValueError('不是有效的IPv6地址')
            
            # 检查是否已被占用
            used_addrs = set(allocations.values())
            if custom_ipv6 in used_addrs:
                logger.error(f"IPv6地址 {custom_ipv6} 已被占用")
                return None
            
            # 分配自定义地址
            allocations[hostname] = custom_ipv6
            state['allocations'] = allocations
            _save_state(state)
            logger.info(f"为 {hostname} 分配自定义IPv6地址: {custom_ipv6}")
            return custom_ipv6
        except Exception as e:
            logger.error(f"自定义IPv6地址 {custom_ipv6} 无效: {e}")
            return None

    # 检查是否配置了预定义地址池
    ipv6_pool = getattr(app_config, 'ipv6_address_pool', None)
    if ipv6_pool and isinstance(ipv6_pool, list):
        # 从地址池中选择未使用的地址
        used_addrs = set(allocations.values())
        for addr in ipv6_pool:
            if addr not in used_addrs:
                allocations[hostname] = addr
                state['allocations'] = allocations
                _save_state(state)
                logger.info(f"为 {hostname} 从地址池分配IPv6: {addr}")
                return addr
        logger.error("IPv6地址池已耗尽")
        return None

    # 否则从 /64 前缀自动分配
    prefix = getattr(app_config, 'ipv6_prefix', None)
    if not prefix:
        logger.warning("IPv6分配失败：未配置 IPV6_PREFIX 或 IPV6_ADDRESS_POOL")
        return None

    try:
        net = _parse_prefix(prefix)
        if net.prefixlen > 64:
            logger.warning(f"不推荐在 {net} 上进行逐个地址分配(前缀长度>{net.prefixlen})")
    except Exception as e:
        logger.error(str(e))
        return None

    # 从cursor开始寻找未占用地址，跳过前16个地址作为保留
    cursor = int(state.get('cursor', 0))
    start = max(16, cursor)

    used = set(allocations.values())
    # 简单线性探测，最多尝试 65535 个
    for offset in range(start, start + 65535):
        addr = str(_addr_at(net, offset))
        if addr not in used:
            allocations[hostname] = addr
            state['allocations'] = allocations
            state['cursor'] = offset + 1
            _save_state(state)
            logger.info(f"为 {hostname} 分配IPv6地址: {addr}")
            return addr

    logger.error("IPv6地址耗尽或无法分配")
    return None




def get_allocated(hostname: str) -> Optional[str]:
    """获取已为 hostname 分配的IPv6地址（如无则返回None）。"""
    state = _load_state()
    return state.get('allocations', {}).get(hostname)


def list_allocations() -> dict:
    """返回当前所有 hostname->IPv6 地址 的映射字典。"""
    state = _load_state()
    return dict(state.get('allocations', {}))


def release(hostname: str) -> Optional[str]:
    """释放容器名对应的IPv6地址（仅从记录中移除，不回收历史cursor）。返回被释放的地址或None。"""
    state = _load_state()
    allocations = state.get('allocations', {})
    if hostname in allocations:
        addr = allocations.pop(hostname)
        state['allocations'] = allocations
        _save_state(state)
        logger.info(f"已释放 {hostname} 的IPv6地址记录: {addr}")
        return addr
    else:
        logger.debug(f"未找到 {hostname} 的IPv6分配记录，无需释放")
        return None

