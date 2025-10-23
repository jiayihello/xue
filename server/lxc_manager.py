from pylxd import Client as LXDClient
from pylxd.exceptions import LXDAPIException, NotFound
from config_handler import app_config
import logging
import json
import subprocess
import os
import shlex
import random
import time
import datetime
import ipaddress
import socket

logger = logging.getLogger(__name__)

IPTABLES_RULES_METADATA_FILE = 'iptables_rules.json'

def _load_iptables_rules_metadata():
    try:
        if os.path.exists(IPTABLES_RULES_METADATA_FILE):
            with open(IPTABLES_RULES_METADATA_FILE, 'r') as f:
                return json.load(f)
        return []
    except Exception as e:
        logger.error(f"加载iptables规则元数据失败: {e}")
        return []

def _save_iptables_rules_metadata(rules):
    try:
        with open(IPTABLES_RULES_METADATA_FILE, 'w') as f:
            json.dump(rules, f, indent=4)
    except Exception as e:
        logger.error(f"保存iptables规则元数据失败: {e}")

class LXCManager:
    def __init__(self):
        try:
            self.client = LXDClient()
            # 延迟导入避免循环依赖
            self.flow_manager = None
        except LXDAPIException as e:
            logger.critical(f"无法连接到LXD守护进程: {e}")
            raise RuntimeError(f"无法连接到LXD守护进程: {e}")

    def _get_flow_manager(self):
        """获取流量管理器实例（延迟初始化）"""
        if self.flow_manager is None:
            try:
                from flow_manager import FlowManager
                self.flow_manager = FlowManager()
            except Exception as e:
                logger.warning(f"无法初始化流量管理器: {e}")
                return None
        return self.flow_manager

    def _get_container_or_error(self, hostname):
        try:
            return self.client.containers.get(hostname)
        except NotFound:
            return None
        except LXDAPIException as e:
            logger.error(f"获取容器 {hostname} 时发生LXD API错误: {e}")
            raise ValueError(f"获取容器时LXD API错误: {e}")

    def _get_container_ip(self, container):
        target_bridge = app_config.network_bridge
        nic_name_on_target_bridge = None
        container_name = container.name
        logger.debug(f"开始为容器 {container_name} 获取IP地址，目标网桥: {target_bridge}")
        for device_name, device_config in container.devices.items():
            if device_config.get('type') == 'nic' and device_config.get('network') == target_bridge:
                nic_name_on_target_bridge = device_name
                logger.debug(f"容器 {container_name} 上找到连接到网桥 {target_bridge} 的接口设备: {nic_name_on_target_bridge}")
                break
        try:
            state = container.state()
            # 优先使用与目标网桥匹配的设备
            if nic_name_on_target_bridge and state.network and nic_name_on_target_bridge in state.network:
                interface_state = state.network[nic_name_on_target_bridge]
                logger.debug(f"容器 {container_name} 接口 {nic_name_on_target_bridge} 的状态: {interface_state}")
                for addr_info in interface_state.get('addresses', []):
                    if addr_info.get('family') == 'inet' and addr_info.get('scope') == 'global':
                        ip_address = addr_info['address']
                        logger.info(f"为容器 {container_name} 在接口 {nic_name_on_target_bridge} 上找到IP: {ip_address}")
                        return ip_address
                logger.warning(f"容器 {container_name} 在接口 {nic_name_on_target_bridge} 上没有找到inet global IP地址。地址列表: {interface_state.get('addresses')}")
            else:
                # 兼容：设备定义可能在 profile 中（container.devices 空），直接遍历状态里所有接口找第一个全局 IPv4
                if not nic_name_on_target_bridge:
                    logger.warning(f"容器 {container_name} 未在 devices 中找到连接到网桥 {target_bridge} 的设备，尝试从状态中直接解析 IP。设备列表: {container.devices}")
                if state.network:
                    for if_name, if_state in state.network.items():
                        for addr_info in if_state.get('addresses', []):
                            if addr_info.get('family') == 'inet' and addr_info.get('scope') == 'global':
                                ip_address = addr_info['address']
                                logger.info(f"为容器 {container_name} 在接口 {if_name} 上找到IP(兼容模式): {ip_address}")
                                return ip_address
                logger.warning(f"容器 {container_name} 的网络状态中未解析到全局 IPv4。当前网络状态: {state.network}")
        except LXDAPIException as e:
            logger.error(f"获取容器 {container_name} 网络状态时发生LXD API错误: {e}")
        logger.warning(f"未能为容器 {container_name} 获取IP地址")
        return None

    def _get_user_metadata(self, container, key, default=None):
        return container.config.get(f"user.{key}", default)

    def _set_user_metadata(self, container, key, value):
        container.config[f"user.{key}"] = str(value)
        container.save(wait=True)

    def _run_shell_command_for_iptables(self, command_args):
        full_command = ['sudo', 'iptables'] + command_args
        try:
            logger.debug(f"执行iptables命令: {' '.join(full_command)}")
            process = subprocess.Popen(full_command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            stdout, stderr = process.communicate(timeout=15)
            if process.returncode != 0:
                error_message = stderr.decode('utf-8', errors='ignore').strip()
                logger.error(f"iptables命令执行失败 ({process.returncode}): {error_message}. 命令: {' '.join(full_command)}")
                return False, f"iptables命令执行失败: {error_message}"
            logger.info(f"iptables命令成功执行: {' '.join(full_command)}")
            return True, stdout.decode('utf-8', errors='ignore').strip()
        except subprocess.TimeoutExpired:
            logger.error(f"iptables命令超时: {' '.join(full_command)}")
            return False, "iptables命令执行超时"
        except FileNotFoundError:
            logger.error(f"iptables命令未找到，请检查路径: {full_command[0]}")
            return False, "iptables命令未找到"
        except Exception as e:
            logger.error(f"执行iptables命令时发生异常: {str(e)}. 命令: {' '.join(full_command)}")
            return False, f"执行iptables命令时发生异常: {str(e)}"


    # ===== IPv6 helpers (ROUTED mode support) =====
    def _ensure_ipv6_sysctl(self, parent_if: str):
        """Ensure IPv6 forwarding and proxy_ndp are enabled on the host for parent_if."""
        try:
            cmds = [
                ['sysctl', '-w', 'net.ipv6.conf.all.forwarding=1'],
                ['sysctl', '-w', 'net.ipv6.conf.default.forwarding=1'],
                ['sysctl', '-w', f'net.ipv6.conf.{parent_if}.proxy_ndp=1'],
                ['sysctl', '-w', 'net.ipv6.conf.all.proxy_ndp=1'],
            ]
            for cmd in cmds:
                try:
                    subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5)
                except Exception:
                    pass
        except Exception as e:
            logger.debug(f"设置IPv6 sysctl失败(可忽略): {e}")

    def _add_ndp_proxy_entry(self, ipv6_addr: str, parent_if: str):
        """Add an NDP proxy entry so upstream can resolve the container /128."""
        try:
            subprocess.run(['ip', '-6', 'neigh', 'replace', 'proxy', ipv6_addr, 'dev', parent_if],
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5)
        except Exception as e:
            logger.debug(f"添加NDP代理失败(可忽略): {e}")

    def _remove_ndp_proxy_entry(self, ipv6_addr: str, parent_if: str):
        """Remove the NDP proxy entry for the container address."""
        try:
            subprocess.run(['ip', '-6', 'neigh', 'del', 'proxy', ipv6_addr, 'dev', parent_if],
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5)
        except Exception as e:
            logger.debug(f"删除NDP代理失败(可忽略): {e}")


    def reconcile_ipv6_proxy_entries(self):
        """Re-apply IPv6 sysctl and NDP proxy entries for all recorded allocations.
        Useful on service start or after host reboot.
        """
        try:
            if not (getattr(app_config, 'ipv6_mode', 'OFF') == 'ROUTED' and getattr(app_config, 'ipv6_prefix', None)):
                return
            parent_if = app_config.ipv6_interface or app_config.main_interface
            if not parent_if:
                return
            # ensure sysctl first
            try:
                self._ensure_ipv6_sysctl(parent_if)
            except Exception:
                pass
            # re-apply NDP proxies
            try:
                from ipv6_manager import list_allocations
                allocs = list_allocations() or {}
                for hostname, addr in allocs.items():
                    try:
                        self._add_ndp_proxy_entry(addr, parent_if)
                    except Exception:
                        pass
            except Exception as e:
                logger.debug(f"加载IPv6分配记录失败: {e}")
        except Exception as e:
            logger.debug(f"reconcile_ipv6_proxy_entries 失败: {e}")

    def _self_heal_reinstall_ipv6(self, hostname: str):
        """Final safeguard after reinstall: ensure routed IPv6 NIC and NDP proxy exist.
        This will no-op if IPv6 routed mode is disabled or prefix missing.
        """
        try:
            if not (getattr(app_config, 'ipv6_mode', 'OFF') == 'ROUTED' and getattr(app_config, 'ipv6_prefix', None)):
                return
            parent_if = app_config.ipv6_interface or app_config.main_interface
            if not parent_if:
                return
            container = self._get_container_or_error(hostname)
            if not container:
                return
            # get or (re)allocate address deterministically
            try:
                from ipv6_manager import get_allocated, allocate
                ipv6_addr = get_allocated(hostname) or allocate(hostname)
            except Exception:
                ipv6_addr = None
            if not ipv6_addr:
                logger.warning(f"IPv6自愈: 无法为 {hostname} 获取/分配 IPv6 地址，跳过自愈")
                return
            # ensure device exists and matches
            dev_name = 'eth0v6'
            need_save = False
            dev = container.devices.get(dev_name)
            if not dev or dev.get('type') != 'nic' or dev.get('nictype') != 'routed':
                container.devices[dev_name] = {'type': 'nic', 'nictype': 'routed', 'parent': parent_if, 'ipv6.address': ipv6_addr}
                need_save = True
            else:
                if dev.get('parent') != parent_if or dev.get('ipv6.address') != ipv6_addr:
                    dev['parent'] = parent_if
                    dev['ipv6.address'] = ipv6_addr
                    container.devices[dev_name] = dev
                    need_save = True
            if need_save:
                try:
                    container.save(wait=True)
                    logger.info(f"IPv6自愈: 已为 {hostname} 确认 routed IPv6 网卡 {dev_name} = {ipv6_addr}")
                except Exception as e:
                    logger.warning(f"IPv6自愈: 保存 {hostname} IPv6 网卡失败: {e}")
            # ensure sysctl and NDP proxy present
            try:
                self._ensure_ipv6_sysctl(parent_if)
            except Exception:
                pass
            try:
                self._add_ndp_proxy_entry(ipv6_addr, parent_if)
            except Exception:
                pass
        except Exception as e:
            logger.debug(f"IPv6自愈失败({hostname}): {e}")


    def get_container_info(self, hostname):
        container = self._get_container_or_error(hostname)
        if not container:
            return {'code': 404, 'msg': '容器未找到'}
        try:
            state_before = container.state()
            time.sleep(1)
            state = container.state()
            config = container.config
            cpu_cores = int(config.get('limits.cpu', '1'))
            cpu_usage_before = state_before.cpu.get('usage', 0)
            cpu_usage_after = state.cpu.get('usage', 0)
            cpu_usage_diff_ns = cpu_usage_after - cpu_usage_before
            cpu_percent = 0
            if cpu_cores > 0:
                total_possible_ns = 1_000_000_000 * cpu_cores
                cpu_percent = round((cpu_usage_diff_ns / total_possible_ns) * 100, 2)
            total_ram_mb = 0
            mem_limit = config.get('limits.memory', '0MB')
            if mem_limit.upper().endswith('MB'): total_ram_mb = int(mem_limit[:-2])
            elif mem_limit.upper().endswith('GB'): total_ram_mb = int(mem_limit[:-2]) * 1024
            used_ram_mb = int(state.memory['usage'] / (1024*1024)) if state.memory and 'usage' in state.memory else 0
            total_disk_mb = 0
            root_device = container.devices.get('root', {})
            if 'size' in root_device:
                disk_size = root_device['size']
                if disk_size.upper().endswith('MB'): total_disk_mb = int(disk_size[:-2])
                elif disk_size.upper().endswith('GB'): total_disk_mb = int(disk_size[:-2]) * 1024
            used_disk_mb = int(state.disk['root']['usage'] / (1024*1024)) if state.disk and 'root' in state.disk and 'usage' in state.disk['root'] else 0
            status_map = {'Running': 'running', 'Stopped': 'stop', 'Frozen': 'frozen'}
            lxc_status = status_map.get(state.status, 'unknown')
            flow_limit_gb = int(self._get_user_metadata(container, 'flow_limit_gb', 0))
            bytes_received_total = 0
            bytes_sent_total = 0
            if state.network:
                for nic_name, nic_data in state.network.items():
                    # 排除环回接口（避免将 lo 的本地通信计入对外流量统计）
                    if nic_name == 'lo' or nic_data.get('type') == 'loopback':
                        continue
                    if 'counters' in nic_data:
                        bytes_received_total += nic_data['counters'].get('bytes_received', 0)
                        bytes_sent_total += nic_data['counters'].get('bytes_sent', 0)

            # 使用流量管理器计算当前周期的使用量
            flow_manager = self._get_flow_manager()
            if flow_manager:
                try:
                    used_flow_gb = flow_manager.calculate_current_period_usage(
                        hostname, bytes_received_total, bytes_sent_total
                    )
                except Exception as e:
                    logger.warning(f"计算容器 {hostname} 周期流量失败，使用原始计算: {e}")
                    bytes_total = bytes_received_total + bytes_sent_total
                    used_flow_gb = round(bytes_total / (1024*1024*1024), 2)
            else:
                # 回退到原始计算
                bytes_total = bytes_received_total + bytes_sent_total
                used_flow_gb = round(bytes_total / (1024*1024*1024), 2)

            created_at_val = container.created_at
            if isinstance(created_at_val, datetime.datetime):
                created_at_str = created_at_val.isoformat()
            else:
                created_at_str = str(created_at_val) if created_at_val else None

            # --- NEW LOGIC TO GET IMAGE ALIAS ---
            image_source_alias = 'N/A'
            container_fingerprint = container.config.get('volatile.base_image')
            if container_fingerprint:
                try:
                    image = self.client.images.get(container_fingerprint)
                    if image.aliases:
                        image_source_alias = image.aliases[0]['name']
                    else:
                        image_source_alias = image.properties.get('description', container_fingerprint)
                except NotFound:
                    logger.warning(f"镜像指纹 {container_fingerprint} 未找到 (容器: {hostname})")
                    image_source_alias = container.config.get('image.description', 'N/A')
                except Exception as e:
                    logger.error(f"获取容器 {hostname} 的镜像别名时出错: {e}")
                    image_source_alias = container.config.get('image.description', 'N/A')
            else:
                image_source_alias = container.config.get('image.description', 'N/A')
            # --- END OF NEW LOGIC ---

            # 计算“公网 IPv6 列表”（过滤 ULA fc00::/7、链路本地 fe80::/10）
            public_ipv6 = []
            for nic in (state.network or {}).values():
                for addr in nic.get('addresses', []):
                    if addr.get('family') == 'inet6' and addr.get('scope') == 'global':
                        try:
                            ip6 = ipaddress.IPv6Address(addr.get('address'))
                            if not (ip6.is_link_local or ip6.is_private):
                                public_ipv6.append(str(ip6))
                        except Exception:
                            pass

            # 获取网络模式配置
            ipv4_mode = getattr(app_config, 'ipv4_mode', 'BRIDGE').upper()
            ipv6_mode = getattr(app_config, 'ipv6_mode', 'OFF').upper()
            
            # 根据 IPv4 模式决定是否返回 PublicIPv4
            # IPv6-Only 模式（IPV4_MODE=OFF）下不返回误导性的服务器 IP
            if ipv4_mode == 'OFF':
                public_ipv4 = None  # IPv6-Only 模式，无 IPv4
            else:
                public_ipv4 = app_config.nat_listen_ip  # 传统模式，返回 NAT IP
            
            data = {
                'Hostname': hostname, 'Status': lxc_status,
                'UsedCPU': cpu_percent,
                'CPUCores': cpu_cores, # Added for lxdserver module
                'TotalRam': total_ram_mb, 'UsedRam': used_ram_mb,
                'TotalDisk': total_disk_mb, 'UsedDisk': used_disk_mb,
                'IP': self._get_container_ip(container) or 'N/A',
                'IPv6List': public_ipv6,
                'PublicIPv4': public_ipv4,  # 修改：IPv6-Only 模式下返回 None
                'IPv4Mode': ipv4_mode,  # 新增：返回 IPv4 模式（BRIDGE 或 OFF）
                'IPv6Mode': ipv6_mode,  # 修改：使用变量
                'PublicIPv6NAT': (str(getattr(app_config, 'nat_listen_ipv6', '')).split('/')[0] if ipv6_mode == 'NAT66' and getattr(app_config, 'nat_listen_ipv6', None) else ''),
                'PublicSSHPort': (lambda: (next((str(r.get('dport')) for r in _load_iptables_rules_metadata() if r.get('hostname') == hostname and r.get('dtype','').lower()=='tcp' and str(r.get('sport'))=='22'), None)) or (next((d.get('listen','').split(':')[2] for name,d in container.devices.items() if d.get('type')=='proxy' and name.startswith('nat-') and d.get('connect','').endswith(':22')), None)) )(),
                'Bandwidth': flow_limit_gb,
                'UseBandwidth': used_flow_gb, # For lxdserver module
                'UseBandwidth_GB': used_flow_gb, # For new web UI
                'ImageSourceAlias': image_source_alias, # <-- ADDED NEW FIELD
                'raw_lxd_info': {
                    'name': container.name,
                    'status': container.status,
                    'status_code': state.status_code,
                    'type': 'container',
                    'architecture': container.architecture,
                    'ephemeral': container.ephemeral,
                    'created_at': created_at_str,
                    'profiles': container.profiles,
                    'config': container.config,
                    'devices': container.devices,
                    'state': {
                         'cpu': state.cpu,
                         'disk': state.disk,
                         'memory': state.memory,
                         'network': state.network
                    },
                    'description': container.description
                }
            }
            return {'code': 200, 'msg': '获取成功', 'data': data}
        except LXDAPIException as e:
            logger.error(f"LXD API错误 (getinfo) for {hostname}: {e}")
            return {'code': 500, 'msg': f'LXD API错误 (getinfo): {e}'}
        except Exception as e:
            logger.error(f"获取信息时发生内部错误 for {hostname}: {str(e)}", exc_info=True)
            return {'code': 500, 'msg': f'获取信息时发生内部错误: {str(e)}'}

    def get_container_realtime_stats(self, hostname):
        container = self._get_container_or_error(hostname)
        if not container:
            return {'code': 404, 'msg': '容器未找到'}
        if container.status != 'Running':
            return {'code': 400, 'msg': '容器未运行'}
        try:
            state_before = container.state()
            time.sleep(1)
            state_after = container.state()
            cpu_cores = int(container.config.get('limits.cpu', '1'))
            cpu_usage_before = state_before.cpu.get('usage', 0)
            cpu_usage_after = state_after.cpu.get('usage', 0)
            cpu_usage_diff_ns = cpu_usage_after - cpu_usage_before
            cpu_percent = 0
            if cpu_cores > 0:
                total_possible_ns = 1_000_000_000 * cpu_cores
                cpu_percent = round((cpu_usage_diff_ns / total_possible_ns) * 100, 2)
            used_ram_mb = int(state_after.memory['usage'] / (1024*1024)) if state_after.memory and 'usage' in state_after.memory else 0
            used_disk_mb = int(state_after.disk['root']['usage'] / (1024*1024)) if state_after.disk and 'root' in state_after.disk and 'usage' in state_after.disk['root'] else 0
            bytes_rx_before, bytes_tx_before = 0, 0
            if state_before.network:
                for nic_data in state_before.network.values():
                    if 'counters' in nic_data:
                        bytes_rx_before += nic_data['counters'].get('bytes_received', 0)
                        bytes_tx_before += nic_data['counters'].get('bytes_sent', 0)
            bytes_rx_after, bytes_tx_after, bytes_total = 0, 0, 0
            if state_after.network:
                for nic_data in state_after.network.values():
                    if 'counters' in nic_data:
                        rx = nic_data['counters'].get('bytes_received', 0)
                        tx = nic_data['counters'].get('bytes_sent', 0)
                        bytes_rx_after += rx
                        bytes_tx_after += tx
                        bytes_total += rx + tx
            rx_speed_bps = bytes_rx_after - bytes_rx_before
            tx_speed_bps = bytes_tx_after - bytes_tx_before
            used_flow_gb = round(bytes_total / (1024*1024*1024), 2)
            stats = {
                'cpu_usage_percent': max(0, cpu_percent),
                'memory_usage_mb': used_ram_mb,
                'disk_usage_mb': used_disk_mb,
                'network_rx_kbps': round(rx_speed_bps / 1024, 2),
                'network_tx_kbps': round(tx_speed_bps / 1024, 2),
                'total_flow_used_gb': used_flow_gb,
            }
            return {'code': 200, 'msg': '获取成功', 'data': stats}
        except LXDAPIException as e:
            logger.error(f"LXD API错误 (get_container_realtime_stats) for {hostname}: {e}")
            return {'code': 500, 'msg': f'LXD API错误: {e}'}
        except Exception as e:
            logger.error(f"获取实时状态时发生内部错误 for {hostname}: {str(e)}", exc_info=True)
            return {'code': 500, 'msg': f'获取实时状态时发生内部错误: {str(e)}'}

    # === Restored functions from 'server old' for API compatibility ===

    def create_container(self, params):
        hostname = params.get('hostname')
        if self.client.containers.exists(hostname):
            return {'code': 409, 'msg': '容器已存在'}
        image_alias = params.get('system') or app_config.default_image_alias

        container_config_obj = {
            'name': hostname,
            'source': {'type': 'image', 'alias': image_alias},
            'config': {
                'limits.cpu': str(params.get('cpu', '1')),
                'limits.memory': f"{params.get('ram', '128')}MB",
                'security.nesting': 'true',
            },
            'devices': {
                'root': {
                    'path': '/', 'pool': app_config.storage_pool,
                    'size': f"{params.get('disk', '1024')}MB", 'type': 'disk'
                }
            }
        }
        
        # 根据 IPV4_MODE 配置决定是否添加 IPv4 网卡
        ipv4_mode = getattr(app_config, 'ipv4_mode', 'BRIDGE').upper()
        if ipv4_mode == 'BRIDGE':
            # 默认模式：添加 eth0 连接到网桥（NAT IPv4）
            container_config_obj['devices']['eth0'] = {
                'name': 'eth0', 'network': app_config.network_bridge, 'type': 'nic'
            }
            logger.info(f"容器 {hostname} 将配置 IPv4 网卡（BRIDGE 模式）")
        elif ipv4_mode == 'OFF':
            # IPv6-Only 模式：不添加 eth0
            logger.info(f"容器 {hostname} 不配置 IPv4 网卡（IPV4_MODE=OFF）")
        
        # CPU 使用率百分比限制（可选）
        if params.get('cpu_percent'):
            try:
                cpu_percent = int(params.get('cpu_percent'))
                if cpu_percent > 0:
                    container_config_obj['config']['limits.cpu.allowance'] = f"{cpu_percent}%"
                    logger.info(f"设置容器 {hostname} CPU 限制为 {cpu_percent}%")
            except (ValueError, TypeError) as e:
                logger.warning(f"无效的 CPU 百分比参数: {params.get('cpu_percent')}, 错误: {e}")

        # 带宽限制（仅在 IPv4 BRIDGE 模式下有效）
        if params.get('up') and params.get('down') and ipv4_mode == 'BRIDGE':
            # 修复：正确的Mbps到bit/s转换 (1 Mbps = 1,000,000 bit/s)
            if 'eth0' in container_config_obj['devices']:
                container_config_obj['devices']['eth0']['limits.ingress'] = f"{int(params.get('up'))*1000000}"
                container_config_obj['devices']['eth0']['limits.egress'] = f"{int(params.get('down'))*1000000}"
                logger.info(f"容器 {hostname} 设置带宽限制: 上行 {params.get('up')}Mbps, 下行 {params.get('down')}Mbps")
        elif params.get('up') and params.get('down') and ipv4_mode == 'OFF':
            logger.warning(f"容器 {hostname} 处于 IPv6-Only 模式，带宽限制参数将被忽略")

        container_to_cleanup_on_error = None
        try:
            logger.info(f"开始创建容器 {hostname} 使用配置: {container_config_obj}")
            container = self.client.containers.create(container_config_obj, wait=True)
            container_to_cleanup_on_error = container


            # IPv6: 在 ROUTED 模式下为容器分配独立IPv6并添加routed网卡，并为上游添加NDP代理
            try:
                if app_config.ipv6_mode == 'ROUTED':
                    from ipv6_manager import allocate
                    # 支持自定义 IPv6 地址（从 params 传递）
                    custom_ipv6 = params.get('custom_ipv6')
                    ipv6_addr = allocate(hostname, custom_ipv6=custom_ipv6)
                    if ipv6_addr:
                        device_name_v6 = 'eth0v6'
                        parent_if = app_config.ipv6_interface or app_config.main_interface
                        # 添加一个routed类型的IPv6独立网卡，parent 使用对外主网卡
                        container.devices[device_name_v6] = {
                            'type': 'nic',
                            'name': 'eth0v6',
                            'nictype': 'routed',
                            'parent': parent_if,
                            'ipv6.address': ipv6_addr
                        }
                        container.save(wait=True)
                        logger.info(f"已为容器 {hostname} 添加 IPv6 路由网卡 {device_name_v6}: {ipv6_addr}")
                        # 开启必须的IPv6转发与NDP代理
                        try:
                            self._ensure_ipv6_sysctl(parent_if)
                        except Exception:
                            pass
                        # 添加NDP代理项，确保上游能解析到该 /128
                        try:
                            self._add_ndp_proxy_entry(ipv6_addr, parent_if)
                        except Exception as e_ndp:
                            logger.warning(f"为容器 {hostname} 添加NDP代理失败: {e_ndp}")
                    else:
                        logger.warning(f"容器 {hostname} IPv6 分配失败，跳过添加 IPv6 网卡")
            except Exception as e:
                logger.error(f"为容器 {hostname} 配置IPv6时出错: {e}")

            self._set_user_metadata(container, 'nat_acl_limit', params.get('ports', 0))
            self._set_user_metadata(container, 'flow_limit_gb', params.get('bandwidth', 0))
            self._set_user_metadata(container, 'disk_size_mb', params.get('disk', '1024'))

            # 在启动前先注册到流量管理系统（基准值为0）
            flow_manager = self._get_flow_manager()
            if flow_manager:
                try:
                    flow_limit_gb = int(params.get('bandwidth', 0))
                    if flow_manager.register_container(hostname, flow_limit_gb):
                        logger.info(f"容器 {hostname} 已注册到流量管理系统")
                    else:
                        logger.warning(f"容器 {hostname} 注册到流量管理系统失败")
                except Exception as e:
                    logger.error(f"注册容器 {hostname} 到流量管理系统时发生异常: {e}")

            logger.info(f"容器 {hostname} 配置完成，开始启动...")
            container.start(wait=True)
            logger.info(f"容器 {hostname} 启动成功")

            logger.info(f"容器 {hostname} 已启动，等待网络稳定...")
            time.sleep(10)  # 减少等待时间

            logger.info(f"容器 {hostname} 网络稳定，准备设置初始密码...")

            new_password = params.get('password')
            if not new_password:
                logger.error(f"为容器 {hostname} 设置初始密码失败：未提供密码。")
            else:
                user_for_password = app_config.default_container_user
                try:
                    logger.info(f"为容器 {hostname} 的用户 {user_for_password} 设置初始密码 (使用 bash -c 'echo ... | chpasswd')")
                    escaped_new_password = shlex.quote(new_password)
                    command_to_execute_in_bash = f"echo '{user_for_password}:{escaped_new_password}' | chpasswd"
                    logger.debug(f"在容器内执行命令: bash -c \"{command_to_execute_in_bash}\"")

                    current_status_check = container.state().status
                    if current_status_check.lower() != 'running':
                        logger.error(f"容器 {hostname} 未处于运行状态 (当前状态: {current_status_check})，无法设置初始密码。")
                    else:
                        exit_code, stdout, stderr = container.execute(['bash', '-c', command_to_execute_in_bash])
                        if exit_code == 0:
                            logger.info(f"容器 {hostname} 初始密码使用 bash -c 'echo ... | chpasswd' 设置成功")
                        else:
                            err_msg_stdout = stdout.decode('utf-8', errors='ignore').strip() if stdout else ""
                            err_msg_stderr = stderr.decode('utf-8', errors='ignore').strip() if stderr else ""
                            full_err_msg = []
                            if err_msg_stdout: full_err_msg.append(f"STDOUT: {err_msg_stdout}")
                            if err_msg_stderr: full_err_msg.append(f"STDERR: {err_msg_stderr}")
                            combined_err_msg = "; ".join(full_err_msg) if full_err_msg else "命令执行失败，但未提供具体错误信息"
                            logger.error(f"容器 {hostname} 设置初始密码失败 (exit_code: {exit_code}): {combined_err_msg}")
                except LXDAPIException as e_passwd:
                    logger.error(f"为容器 {hostname} 设置初始密码时发生LXD API错误: {e_passwd}")
                except Exception as e_passwd_generic:
                    logger.error(f"为容器 {hostname} 设置初始密码时发生未知错误: {e_passwd_generic}", exc_info=True)
            try:
                ssh_external_port_min = 10000
                ssh_external_port_max = 65535
                random_ssh_dport = random.randint(ssh_external_port_min, ssh_external_port_max)
                logger.info(f"尝试为容器 {hostname} 自动添加 SSH (端口 22) 的 NAT 规则，使用外部端口 {random_ssh_dport}")

                container_ip_for_nat = None
                nat_add_attempts = 0
                while not container_ip_for_nat and nat_add_attempts < 3:
                    container_ip_for_nat = self._get_container_ip(container)
                    if container_ip_for_nat: break
                    logger.warning(f"为容器 {hostname} 获取IP失败 (尝试 {nat_add_attempts+1}/3)，等待后重试...")
                    time.sleep(5)
                    nat_add_attempts += 1

                if not container_ip_for_nat:
                    logger.error(f"为容器 {hostname} 自动添加 SSH NAT 规则失败：多次尝试后仍无法获取容器IP地址。")
                else:
                    add_ssh_rule_result = self.add_nat_rule_via_iptables(hostname, 'tcp', str(random_ssh_dport), '22')
                    if add_ssh_rule_result.get('code') == 200:
                        logger.info(f"成功为容器 {hostname} 自动添加 SSH NAT 规则: 外部端口 {random_ssh_dport} -> 内部端口 22")
                    elif add_ssh_rule_result.get('code') == 409:
                        logger.warning(f"尝试为容器 {hostname} 自动添加 SSH NAT 规则失败：外部端口 {random_ssh_dport} 已被此容器的其他规则使用。可尝试重新创建或手动添加其他端口。")
                    else:
                        logger.error(f"为容器 {hostname} 自动添加 SSH NAT 规则失败。外部端口: {random_ssh_dport}, 原因: {add_ssh_rule_result.get('msg')}")
            except Exception as e_ssh_nat:
                logger.error(f"为容器 {hostname} 自动添加 SSH NAT 规则时发生异常: {str(e_ssh_nat)}", exc_info=True)

            return {'code': 200, 'msg': '容器创建成功'}
        except (LXDAPIException, Exception) as e:
            error_type_msg = "LXD API错误" if isinstance(e, LXDAPIException) else "内部错误"
            logger.error(f"创建容器 {hostname} 过程中发生{error_type_msg}: {str(e)}", exc_info=True)
            if container_to_cleanup_on_error and self.client.containers.exists(container_to_cleanup_on_error.name):
                 try:
                     logger.info(f"创建过程中发生错误，尝试删除可能已部分创建的容器 {container_to_cleanup_on_error.name}")
                     current_state = container_to_cleanup_on_error.state()
                     if current_state.status and current_state.status.lower() == 'running':
                         container_to_cleanup_on_error.stop(wait=True)
                     container_to_cleanup_on_error.delete(wait=True)
                     logger.info(f"部分创建的容器 {container_to_cleanup_on_error.name} 已删除。")
                 except Exception as e_cleanup:
                     logger.error(f"尝试清理部分创建的容器 {container_to_cleanup_on_error.name} 时失败: {e_cleanup}")
            return {'code': 500, 'msg': f'{error_type_msg} (create): {str(e)}'}

    def add_nat_rule_via_iptables(self, hostname, dtype, dport, sport):
        container = self._get_container_or_error(hostname)
        if not container: return {'code': 404, 'msg': '容器未找到'}

        logger.info(f"为容器 {hostname} 通过LXD proxy设备添加端口转发规则: {dtype} {dport} -> {sport}")

        # 检查规则限制和已有规则
        limit = int(self._get_user_metadata(container, 'nat_acl_limit', 0))
        rules_metadata = _load_iptables_rules_metadata()
        current_host_rules_count = sum(1 for r in rules_metadata if r.get('hostname') == hostname)

        is_ssh_rule = (str(sport) == '22' and dtype.lower() == 'tcp')
        if not is_ssh_rule and limit > 0 and current_host_rules_count >= limit:
            logger.warning(f"容器 {hostname} 已达到端口转发规则数量上限 ({limit}条)")
            return {'code': 403, 'msg': f'已达到端口转发规则数量上限 ({limit}条)'}

        # 生成唯一设备名称和规则ID
        device_name = f"nat-{dtype.lower()}-{dport}"
        rule_comment = f'lxd_controller_nat_{hostname}_{dtype.lower()}_{dport}'

        # 检查是否已存在相同端口的转发规则
        for rule_meta in rules_metadata:
            if rule_meta.get('hostname') == hostname and \
               rule_meta.get('dtype', '').lower() == dtype.lower() and \
               str(rule_meta.get('dport')) == str(dport):
                logger.warning(f"容器 {hostname} 的端口转发规则 ({dtype} {dport}) 已存在")
                return {'code': 409, 'msg': '此外部端口和协议的端口转发规则已存在'}

        container_ip = self._get_container_ip(container)
        if not container_ip:
            logger.error(f"为容器 {hostname} 添加端口转发规则失败: 无法获取内部IP")
            return {'code': 500, 'msg': '无法获取容器内部IP地址'}


        if True:

	        # 非严格模式下，记录自检警告信息并继续创建
	        warn_msgs = []

        try:
            # 使用LXD proxy设备添加端口转发 - 使用容器的实际IP而不是127.0.0.1
            proto = dtype.lower()

            # 先清理可能遗留或命名不同的旧设备，避免端口占用冲突（例如历史 '-v4' 后缀）
            try:
                cleaned = False
                for dev in (device_name, f"{device_name}-v6", f"{device_name}-v4"):
                    if dev in container.devices:
                        del container.devices[dev]
                        cleaned = True
                        logger.info(f"在添加前移除旧proxy设备 {dev} 以避免冲突")
                if cleaned:
                    container.save(wait=True)
            except Exception as e_cleanup:
                logger.warning(f"添加前清理旧proxy设备时出错(可忽略): {e_cleanup}")
            # 更稳健的端口占用检测：直接尝试绑定套接字
            def _port_in_use(ip: str, port: str, proto_s: str, ipv6: bool=False):
                import socket, errno
                family = socket.AF_INET6 if ipv6 else socket.AF_INET
                stype = socket.SOCK_STREAM if str(proto_s).lower() == 'tcp' else socket.SOCK_DGRAM
                s = None
                try:
                    s = socket.socket(family, stype)
                    # 对于IPv6上的通配地址，保持默认V6ONLY策略，由宿主配置决定
                    bind_ip = ip
                    # 去除可能的 [] 包裹
                    if ipv6 and bind_ip.startswith('[') and bind_ip.endswith(']'):
                        bind_ip = bind_ip[1:-1]
                    s.bind((bind_ip, int(port)))
                    if stype == socket.SOCK_STREAM:
                        s.listen(1)
                    try:
                        s.close()
                    except Exception:
                        pass
                    return False, ''
                except OSError as e:
                    # 端口已被占用
                    if getattr(e, 'errno', None) in (errno.EADDRINUSE,):
                        return True, f"{ip}:{port} already in use ({proto_s})"
                    # 地址在本机不存在
                    if getattr(e, 'errno', None) in (errno.EADDRNOTAVAIL,):
                        return True, f"Address not available: {ip}"
                    return False, ''
                except Exception:
                    return False, ''


            # 两阶段创建：先创建 IPv6，再创建 IPv4，以规避 LXD 在某些环境中的绑定顺序问题
            v6_created = False

            # 预检查函数：通过 ss 检测是否已有监听（更健壮：处理 0.0.0.0/:: 与特定地址之间的冲突关系）
            def _port_occupied(ipv6: bool, ip: str, port: str, proto_s: str):
                try:
                    args = ['-ltnp']
                    if ipv6:
                        args.append('-6')
                    else:
                        args.append('-4')
                    res = subprocess.run(['ss'] + args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=4)
                    if res.returncode != 0:
                        return False, ''

                    lines = [ln for ln in res.stdout.splitlines() if f":{port}" in ln]
                    if not lines:
                        return False, ''

                    # 在 ss 输出中找到本地地址:端口的字段
                    def _extract_local_token(ln: str):
                        for tok in ln.split():
                            if f":{port}" in tok:
                                return tok
                        return ''

                    # 规范化待比较的监听地址
                    any_addr = '::' if ipv6 else '0.0.0.0'
                    want_any = (ip == any_addr)
                    ip_token = f"[{ip}]" if ipv6 and not ip.startswith('[') else ip

                    for ln in lines:
                        local_tok = _extract_local_token(ln)  # 例如 0.0.0.0:53733 / 127.0.0.1:53733 / [::]:53733 / [fe80::1]:53733
                        if not local_tok:
                            continue

                        # 监听在任意地址上：与特定地址绑定也冲突
                        if want_any:
                            return True, ln
                        else:
                            # 如果对方在任意地址监听，也冲突
                            if local_tok.startswith(f"{any_addr}:{port}") or local_tok.startswith(f"[{any_addr}]:{port}"):
                                return True, ln
                            # 对方在我们要绑定的同一具体地址上监听，也冲突
                            if ipv6:
                                if local_tok.startswith(f"{ip_token}:{port}"):
                                    return True, ln
                            else:
                                if local_tok.startswith(f"{ip}:{port}"):
                                    return True, ln

                    return False, ''
                except Exception:
                    return False, ''

            # 计算监听地址
            v4_host = app_config.nat_listen_ip or '0.0.0.0'
            v6_host = None

            # 先创建 IPv6（如启用 NAT66）
            try:
                if getattr(app_config, 'ipv6_mode', 'OFF') == 'NAT66':
                    v6_host = getattr(app_config, 'nat_listen_ipv6', None) or '::'
                    v6_host = str(v6_host).split('/')[0].strip('[]') if v6_host else '::'
                    # 预检查：IPv6 地址/端口占用
                    occ, line = _port_in_use(v6_host, str(dport), proto, ipv6=True)
                    if occ:
                        msg = f"IPv6端口已被占用: {line}"
                        logger.warning(msg)
                        return {'code': 409, 'msg': msg}


                    # 二次预检查：通过 ss 检测 IPv6 监听冲突
                    occ6b, line6b = _port_occupied(True, v6_host, str(dport), proto)
                    if occ6b:
                        msg6b = f"IPv6端口已被占用: {line6b}"
                        logger.warning(msg6b)
                        return {'code': 409, 'msg': msg6b}

                    #
                    #

                    #
                    #
                    #


                    #

                    #

                    #

                    #

                    #

                    #

                    #

                    #

                    #

                    #

                    #

                    #

                    #

                    #

                    #

                    #
                    #

                    #

                    #

                    #

                    #

                    #

                    #

                    #

                    #

                    #

                    container.devices[f"{device_name}-v6"] = {
                        'type': 'proxy',
                        'listen': f'{proto}:[{v6_host}]:{dport}',
                        'connect': f'{proto}:{container_ip}:{sport}',
                        'bind': 'host'
                    }
                    container.save(wait=True)
                    v6_created = True
            except Exception as e_v6:
                # IPv6失败：记录并继续尝试IPv4
                logger.warning(f"IPv6 代理设备创建失败(将继续尝试IPv4): {e_v6}")

            # 接着创建 IPv4 设备（改为绑定 NAT_LISTEN_IP，避免与 IPv6 冲突）
            try:
                # 预检查：IPv4 地址/端口占用
                occ4, line4 = _port_in_use(v4_host, str(dport), proto, ipv6=False)
                if occ4:
                    # 若之前创建了 v6，则回滚移除 v6 设备
                    if v6_created:
                        try:
                            dev_v6 = f"{device_name}-v6"
                            if dev_v6 in container.devices:
                                del container.devices[dev_v6]
                                container.save(wait=True)
                                logger.info(f"由于IPv4端口占用，已回滚删除 IPv6 设备 {dev_v6}")
                        except Exception as er:
                            logger.warning(f"IPv4占用回滚IPv6失败(可忽略): {er}")
                    msg4 = f"IPv4端口已被占用: {line4}"
                    logger.warning(msg4)
                    return {'code': 409, 'msg': msg4}

                # 二次预检查：通过 ss 检测监听冲突（处理 0.0.0.0 与具体地址的关系）
                occ4b, line4b = _port_occupied(False, v4_host, str(dport), proto)
                if occ4b:
                    if v6_created:
                        try:
                            dev_v6 = f"{device_name}-v6"
                            if dev_v6 in container.devices:
                                del container.devices[dev_v6]
                                container.save(wait=True)
                                logger.info(f"由于IPv4端口占用(ss检测)，已回滚删除 IPv6 设备 {dev_v6}")
                        except Exception as er:
                            logger.warning(f"IPv4占用回滚IPv6失败(可忽略): {er}")
                    msg4b = f"IPv4端口已被占用: {line4b}"
                    logger.warning(msg4b)
                    return {'code': 409, 'msg': msg4b}


                # 校验监听地址是否存在于本机（云厂商EIP通常不在实例网卡上，不能直接绑定）
                def _get_local_ips(ipv6: bool=False):
                    cmd = ['ip', '-o', '-6' if ipv6 else '-4', 'addr', 'show']
                    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=3)
                    if res.returncode != 0:
                        return set()
                    addrs = set()
                    for ln in res.stdout.splitlines():
                        parts = ln.split()
                        if 'inet6' in parts or 'inet' in parts:
                            for i, tok in enumerate(parts):
                                if tok in ('inet', 'inet6') and i+1 < len(parts):
                                    ip_mask = parts[i+1]
                                    ip_only = ip_mask.split('/')[0]
                                    if ':' in ip_only:
                                        ip_only = ip_only.strip('[]')
                                    addrs.add(ip_only)
                    return addrs
                local_v4 = _get_local_ips(False)
                local_v6 = _get_local_ips(True)

                if v4_host and v4_host != '0.0.0.0' and v4_host not in local_v4:
                    msg = f"监听IPv4地址不可用: {v4_host}。该地址不在本机任何网卡上，请使用 0.0.0.0 或者本机网卡的IPv4（如 10.8.4.13）。"
                    logger.warning(msg)
                    return {'code': 400, 'msg': msg}

                if getattr(app_config, 'ipv6_mode', 'OFF') == 'NAT66':
                    candidate_v6 = getattr(app_config, 'nat_listen_ipv6', None)
                    if candidate_v6:
                        candidate_v6 = str(candidate_v6).split('/')[0].strip('[]')
                    if candidate_v6 and candidate_v6 != '::' and candidate_v6 not in local_v6:
                        msg6 = f"监听IPv6地址不可用: {candidate_v6}。该地址不在本机任何网卡上，请使用 :: 或者本机网卡的全局IPv6。"
                        logger.warning(msg6)
                        return {'code': 400, 'msg': msg6}

                container.devices[device_name] = {
                    'type': 'proxy',
                    'listen': f'{proto}:{v4_host}:{dport}',
                    'connect': f'{proto}:{container_ip}:{sport}',
                    'bind': 'host'
                }
                container.save(wait=True)

                # 连通性自检（仅TCP）：可配置严格/宽松模式
                try:
                    if proto.lower() == 'tcp':
                        strict = getattr(app_config, 'portmap_selftest_strict', True)
                        # 1) 宿主直连容器后端端口，确认服务在监听
                        try:
                            _s = socket.create_connection((container_ip, int(sport)), timeout=2.0)
                            _s.close()
                        except Exception:
                            if strict:
                                # 回滚刚创建的设备（v4 + 可能的 v6）
                                try:
                                    if device_name in container.devices:
                                        del container.devices[device_name]
                                    if v6_created:
                                        dev_v6 = f"{device_name}-v6"
                                        if dev_v6 in container.devices:
                                            del container.devices[dev_v6]
                                    container.save(wait=True)
                                except Exception as _er:
                                    logger.warning(f"连通性自检失败后的回滚异常(可忽略): {_er}")
                                return {'code': 409, 'msg': f'容器端口未监听或不可达: {container_ip}:{sport}。请确认容器服务已启动'}
                            else:
                                logger.warning(f"自检警告（未阻断）：容器端口未监听或不可达: {container_ip}:{sport}")
                                warn_msgs.append(f"容器端口未监听或不可达: {container_ip}:{sport}")

                        # 2) 宿主自测代理监听是否可连
                        time.sleep(0.2)
                        v4_test_host = '127.0.0.1' if v4_host == '0.0.0.0' else v4_host
                        try:
                            _s2 = socket.create_connection((v4_test_host, int(dport)), timeout=2.0)
                            _s2.close()
                        except Exception as _el:
                            if strict:
                                try:
                                    if device_name in container.devices:
                                        del container.devices[device_name]
                                    if v6_created:
                                        dev_v6 = f"{device_name}-v6"
                                        if dev_v6 in container.devices:
                                            del container.devices[dev_v6]
                                    container.save(wait=True)
                                except Exception as _er2:
                                    logger.warning(f"代理监听自检失败后的回滚异常(可忽略): {_er2}")
                                return {'code': 502, 'msg': f'代理监听暂不可用: {v4_test_host}:{dport}。请稍后重试'}
                            else:
                                logger.warning(f"自检警告（未阻断）：代理监听暂不可用: {v4_test_host}:{dport}")
                                warn_msgs.append(f"代理监听暂不可用: {v4_test_host}:{dport}")
                except Exception as _e_self:
                    logger.debug(f"连通性自检出现非致命异常: {_e_self}")

            except Exception as e_v4:
                # 若 v4 创建失败且 v6 已创建，回滚 v6
                if v6_created:
                    try:
                        dev_v6 = f"{device_name}-v6"
                        if dev_v6 in container.devices:
                            del container.devices[dev_v6]
                            container.save(wait=True)
                            logger.info(f"由于IPv4创建失败，已回滚删除 IPv6 设备 {dev_v6}")
                    except Exception as er2:
                        logger.warning(f"IPv4失败回滚IPv6失败(可忽略): {er2}")
                logger.error(f"创建IPv4代理设备失败: {e_v4}")
                return {'code': 500, 'msg': f'添加端口转发规则失败(IPv4): {str(e_v4)}'}

            # 保存元数据以兼容现有系统（仍按一条规则记录）
            new_rule_meta = {
                'hostname': hostname,
                'dtype': proto,
                'dport': str(dport),
                'sport': str(sport),
                'container_ip': container_ip,
                'rule_id': rule_comment
            }
            rules_metadata.append(new_rule_meta)
            _save_iptables_rules_metadata(rules_metadata)

            logger.info(f"容器 {hostname} 添加端口转发规则成功 (LXD proxy: v4{'+v6' if getattr(app_config,'ipv6_mode','OFF')=='NAT66' else ''})")
            resp = {'code': 200, 'msg': '端口转发规则添加成功'}
            if warn_msgs:
                resp['warnings'] = warn_msgs
            return resp
        except Exception as e:
            logger.error(f"为容器 {hostname} 添加端口转发规则时发生异常: {str(e)}", exc_info=True)
            return {'code': 500, 'msg': f'添加端口转发规则失败: {str(e)}'}

    # === End of restored functions ===

    def delete_container(self, hostname):
        container = self._get_container_or_error(hostname)
        if not container: return {'code': 404, 'msg': '容器未找到'}
        try:
            logger.info(f"开始删除容器 {hostname}")

            logger.info(f"删除容器 {hostname} 前，清理其所有 NAT 规则")
            rules_metadata_snapshot = _load_iptables_rules_metadata()
            rules_for_this_host_to_delete = [
                rule for rule in rules_metadata_snapshot if rule.get('hostname') == hostname
            ]

            if not rules_for_this_host_to_delete:
                logger.info(f"容器 {hostname} 没有找到关联的 NAT 规则。")
            else:
                for rule_meta_to_delete in rules_for_this_host_to_delete:
                    logger.info(f"准备删除容器 {hostname} 的iptables规则: {rule_meta_to_delete}")
                    delete_attempt_result = self.delete_nat_rule_via_iptables(
                        hostname,
                        rule_meta_to_delete['dtype'],
                        rule_meta_to_delete['dport'],
                        rule_meta_to_delete['sport'],
                        container_ip_at_creation_time=rule_meta_to_delete.get('container_ip')
)
                    if delete_attempt_result.get('code') == 200:
                        logger.info(f"成功删除 NAT 规则: {rule_meta_to_delete} for {hostname}")
                    else:
                        logger.warning(f"删除 NAT 规则 {rule_meta_to_delete} for {hostname} 可能失败. 原因: {delete_attempt_result.get('msg')}")

                # 释放IPv6分配记录，并清理NDP代理
                try:
                    if app_config.ipv6_mode == 'ROUTED':
                        from ipv6_manager import release
                        addr = release(hostname)
                        if addr:
                            parent_if = app_config.ipv6_interface or app_config.main_interface
                            try:
                                self._remove_ndp_proxy_entry(addr, parent_if)
                            except Exception:
                                pass
                except Exception as e:
                    logger.warning(f"释放容器 {hostname} 的IPv6记录/清理NDP代理时出错: {e}")

            if container.status == 'Running':
                logger.info(f"容器 {hostname} 正在运行，先停止...")
                container.stop(wait=True)

            container.delete(wait=True)
            logger.info(f"容器 {hostname} 删除成功")

            # 从流量管理系统中注销
            flow_manager = self._get_flow_manager()
            if flow_manager:
                try:
                    if flow_manager.unregister_container(hostname):
                        logger.info(f"容器 {hostname} 已从流量管理系统中注销")
                    else:
                        logger.warning(f"容器 {hostname} 从流量管理系统注销失败")
                except Exception as e:
                    logger.error(f"从流量管理系统注销容器 {hostname} 时发生异常: {e}")

            return {'code': 200, 'msg': '容器删除成功'}
        except LXDAPIException as e:
            logger.error(f"LXD API错误 (delete container {hostname}): {e}")
            return {'code': 500, 'msg': f'LXD API错误 (delete): {e}'}
        except Exception as e:
            logger.error(f"删除容器 {hostname} 时发生内部错误: {str(e)}", exc_info=True)
            return {'code': 500, 'msg': f'删除容器时发生内部错误: {str(e)}'}

    def _power_action(self, hostname, action):
        container = self._get_container_or_error(hostname)
        if not container: return {'code': 404, 'msg': '容器未找到'}
        try:
            logger.info(f"对容器 {hostname} 执行电源操作: {action}")
            if action == 'start':
                if container.status == 'Running': return {'code': 200, 'msg': '容器已在运行中'}
                container.start(wait=True)
            elif action == 'stop':
                if container.status == 'Stopped': return {'code': 200, 'msg': '容器已停止'}
                container.stop(wait=True)
            elif action == 'restart':
                container.restart(wait=True)
            logger.info(f"容器 {hostname} {action} 操作成功")
            return {'code': 200, 'msg': f'容器{action}操作成功'}
        except LXDAPIException as e:
            logger.error(f"LXD API错误 (power action {action} for {hostname}): {e}")
            return {'code': 500, 'msg': f'LXD API错误 ({action}): {e}'}
        except Exception as e:
            logger.error(f"电源操作 {action} for {hostname} 时发生内部错误: {str(e)}", exc_info=True)
            return {'code': 500, 'msg': f'电源操作时发生内部错误: {str(e)}'}

    def start_container(self, hostname): return self._power_action(hostname, 'start')
    def stop_container(self, hostname): return self._power_action(hostname, 'stop')
    def restart_container(self, hostname): return self._power_action(hostname, 'restart')

    def change_password(self, hostname, new_password):
        container = self._get_container_or_error(hostname)
        if not container:
            return {'code': 404, 'msg': '容器未找到'}

        current_status_check = container.state().status
        if current_status_check.lower() != 'running':
            logger.warning(f"尝试为容器 {hostname} 修改密码，但容器未运行 (状态: {current_status_check})")
            return {'code': 400, 'msg': f'容器未运行 (状态: {current_status_check})'}
        try:
            user = app_config.default_container_user

            # 检测是否为Alpine系统
            is_alpine = False
            try:
                exit_code, stdout, _ = container.execute(['/bin/sh', '-c', 'cat /etc/os-release | grep -i alpine'])
                if exit_code == 0 and stdout:
                    stdout_str = stdout.decode('utf-8', errors='ignore')
                    if 'alpine' in stdout_str.lower():
                        is_alpine = True
                        logger.info(f"检测到容器 {hostname} 为Alpine系统，将使用特定的密码设置方法")
            except Exception as e_detect:
                logger.warning(f"检测容器 {hostname} 系统类型时出错: {e_detect}")

            # 添加备用检测方法
            if not is_alpine:
                try:
                    # 检查是否存在apk命令(Alpine特有)
                    exit_code, _, _ = container.execute(['/bin/sh', '-c', 'which apk'])
                    if exit_code == 0:
                        is_alpine = True
                        logger.info(f"通过apk命令检测到容器 {hostname} 为Alpine系统")
                except Exception as e_detect2:
                    logger.warning(f"备用方法检测容器 {hostname} 系统类型时出错: {e_detect2}")

            escaped_new_password = shlex.quote(new_password)

            if is_alpine:
                # Alpine特殊处理
                logger.info(f"为Alpine容器 {hostname} 的用户 {user} 设置密码")
                try:
                    # 先安装必要的包
                    logger.info(f"为Alpine容器 {hostname} 安装必要的软件包")
                    container.execute(['/bin/sh', '-c', 'apk update'])
                    # 安装openssh和调试工具
                    container.execute(['/bin/sh', '-c', 'apk add openssh shadow openrc curl busybox-extras'])

                    # 使用完整的SSH配置流程
                    logger.info(f"为Alpine容器 {hostname} 配置并启动SSH服务 (完整流程)")

                    # 创建必要的目录
                    container.execute(['/bin/sh', '-c', 'mkdir -p /var/run/sshd'])

                    # 修改SSH配置允许root登录和密码认证
                    container.execute(['/bin/sh', '-c', 'sed -i "s/#PermitRootLogin.*/PermitRootLogin yes/g" /etc/ssh/sshd_config'])
                    container.execute(['/bin/sh', '-c', 'sed -i "s/#PasswordAuthentication.*/PasswordAuthentication yes/g" /etc/ssh/sshd_config'])
                    container.execute(['/bin/sh', '-c', 'sed -i "s/PasswordAuthentication.*/PasswordAuthentication yes/g" /etc/ssh/sshd_config'])

                    # 生成SSH密钥（如果不存在）
                    container.execute(['/bin/sh', '-c', 'if [ ! -f /etc/ssh/ssh_host_rsa_key ]; then ssh-keygen -A; fi'])

                    # 设置密码
                    command_to_execute = f"echo '{user}:{escaped_new_password}' | chpasswd"
                    exit_code, stdout, stderr = container.execute(['/bin/sh', '-c', command_to_execute])

                    # 添加到启动服务
                    container.execute(['/bin/sh', '-c', 'rc-update add sshd default'])

                    # 直接启动SSH服务
                    logger.info(f"直接启动Alpine容器 {hostname} 的SSH服务")
                    start_ssh_output = container.execute(['/bin/sh', '-c', '/usr/sbin/sshd'])
                    logger.info(f"启动SSH服务结果: {start_ssh_output}")

                    # 验证SSH服务是否已启动
                    verify_cmd, verify_stdout, verify_stderr = container.execute(['/bin/sh', '-c', 'ps | grep sshd'])
                    if verify_stdout:
                        msg = verify_stdout.decode('utf-8', errors='ignore') if isinstance(verify_stdout, (bytes, bytearray)) else str(verify_stdout)
                        logger.info(f"SSH进程验证: {msg}")
                    else:
                        msg = verify_stderr.decode('utf-8', errors='ignore') if isinstance(verify_stderr, (bytes, bytearray)) else str(verify_stderr)
                        logger.warning(f"未检测到SSH进程! stderr: {msg}")

                    # 添加额外的自启动方式（多重保障）
                    container.execute(['/bin/sh', '-c', 'mkdir -p /etc/local.d'])
                    container.execute(['/bin/sh', '-c', 'echo "#!/bin/sh" > /etc/local.d/sshd.start'])
                    container.execute(['/bin/sh', '-c', 'echo "/usr/sbin/sshd" >> /etc/local.d/sshd.start'])
                    container.execute(['/bin/sh', '-c', 'chmod +x /etc/local.d/sshd.start'])
                    container.execute(['/bin/sh', '-c', 'rc-update add local default'])

                    # 检查22端口是否已在监听
                    port_check_cmd, port_stdout, port_stderr = container.execute(['/bin/sh', '-c', 'netstat -tulpn | grep :22'])
                    if port_stdout:
                        pmsg = port_stdout.decode('utf-8', errors='ignore') if isinstance(port_stdout, (bytes, bytearray)) else str(port_stdout)
                        logger.info(f"端口22监听状态: {pmsg}")
                    else:
                        pmsg = port_stderr.decode('utf-8', errors='ignore') if isinstance(port_stderr, (bytes, bytearray)) else str(port_stderr)
                        logger.warning(f"端口22未在监听! stderr: {pmsg}")

                    logger.info(f"Alpine容器 {hostname} SSH配置完成")

                except Exception as e_alpine:
                    logger.error(f"为Alpine容器 {hostname} 安装或配置SSH时出错: {e_alpine}")
                    # 不要修改exit_code，确保重装流程继续
                    logger.info(f"尽管SSH配置出现错误，但将继续重装流程以避免上层应用失败: {e_alpine}")
            else:
                # 常规系统处理
                logger.info(f"开始为容器 {hostname} 的用户 {user} 修改密码 (使用 bash -c 'echo ... | chpasswd')")
                command_to_execute_in_bash = f"echo '{user}:{escaped_new_password}' | chpasswd"
                logger.debug(f"在容器内执行命令: bash -c \"{command_to_execute_in_bash}\"")
                exit_code, stdout, stderr = container.execute(['bash', '-c', command_to_execute_in_bash])

            if exit_code == 0:
                logger.info(f"容器 {hostname} 密码修改成功")
                return {'code': 200, 'msg': '密码修改成功'}
            else:
                err_msg_stdout = stdout.decode('utf-8', errors='ignore').strip() if stdout else ""
                err_msg_stderr = stderr.decode('utf-8', errors='ignore').strip() if stderr else ""
                full_err_msg = []
                if err_msg_stdout: full_err_msg.append(f"STDOUT: {err_msg_stdout}")
                if err_msg_stderr: full_err_msg.append(f"STDERR: {err_msg_stderr}")
                combined_err_msg = "; ".join(full_err_msg) if full_err_msg else "命令执行失败，但未提供具体错误信息"
                logger.error(f"容器 {hostname} 密码修改失败 (exit_code: {exit_code}): {combined_err_msg}")
                return {'code': 500, 'msg': f'密码修改失败: {combined_err_msg}'}
        except LXDAPIException as e:
            logger.error(f"LXD API错误 (change password for {hostname}): {e}")
            return {'code': 500, 'msg': f'LXD API错误 (password): {e}'}
        except Exception as e:
            logger.error(f"修改密码 for {hostname} 时发生内部错误: {str(e)}", exc_info=True)
            return {'code': 500, 'msg': f'修改密码时发生内部错误: {str(e)}'}

    def reinstall_container(self, hostname, new_os_alias, new_password):
        container = self._get_container_or_error(hostname)
        if not container: return {'code': 404, 'msg': '容器未找到'}
        logger.info(f"开始重装容器 {hostname} 为系统 {new_os_alias}")

        # 保存所有NAT规则用于重装后恢复
        logger.info(f"保存容器 {hostname} 的所有端口转发规则")
        saved_nat_rules = []
        try:
            rules_result = self.list_nat_rules(hostname)
            if isinstance(rules_result, dict) and 'data' in rules_result:
                saved_nat_rules = rules_result.get('data', [])
                # 确保保存的规则使用了正确的键名格式
                for rule in saved_nat_rules:
                    if 'Dtype' not in rule and 'type' in rule:
                        rule['Dtype'] = rule['type']
                    if 'Dport' not in rule and 'dport' in rule:
                        rule['Dport'] = rule['dport']
                    if 'Sport' not in rule and 'sport' in rule:
                        rule['Sport'] = rule['sport']
                    if 'ID' not in rule and 'id' in rule:
                        rule['ID'] = rule['id']
                logger.info(f"成功保存容器 {hostname} 的 {len(saved_nat_rules)} 条端口转发规则")
                logger.debug(f"保存的规则: {saved_nat_rules}")
            else:
                logger.warning(f"保存容器 {hostname} 的端口转发规则失败: 返回格式异常 {rules_result}")
        except Exception as e:
            logger.error(f"保存容器 {hostname} 的端口转发规则时发生错误: {e}")

        # 保存原先的SSH端口信息用于后续恢复
        original_ssh_port = None
        rules_metadata_snapshot_reinstall = _load_iptables_rules_metadata()
        for rule in rules_metadata_snapshot_reinstall:
            if (rule.get('hostname') == hostname and
                rule.get('dtype', '').lower() == 'tcp' and
                str(rule.get('sport')) == '22'):
                original_ssh_port = rule.get('dport')
                logger.info(f"发现容器 {hostname} 原有SSH端口转发: 外部端口 {original_ssh_port} -> 内部端口 22")
                break

        original_config_keys = ['limits.cpu', 'limits.memory', 'user.nat_acl_limit', 'user.flow_limit_gb', 'user.disk_size_mb']
        original_devices_to_keep_config = ['eth0']

        preserved_config = {k: v for k, v in container.config.items() if k in original_config_keys}
        preserved_devices = {dev_name: dev_data for dev_name, dev_data in container.devices.items() if dev_name in original_devices_to_keep_config}
        new_root_size = self._get_user_metadata(container, 'disk_size_mb', '1024') + "MB"

        try:
            if container.status == 'Running':
                logger.info(f"容器 {hostname}正在运行，重装前先停止...")
                container.stop(wait=True)

            logger.info(f"重装容器 {hostname} 前，清理其所有 NAT 规则")
            rules_for_this_host_to_delete_reinstall = [
                rule for rule in rules_metadata_snapshot_reinstall if rule.get('hostname') == hostname
            ]


            if not rules_for_this_host_to_delete_reinstall:
                logger.info(f"容器 {hostname} (重装前) 没有找到关联的 NAT 规则。")
            else:
                for rule_meta_to_delete in rules_for_this_host_to_delete_reinstall:
                    logger.info(f"准备删除容器 {hostname} (重装前) 的iptables规则: {rule_meta_to_delete}")
                    delete_attempt_result = self.delete_nat_rule_via_iptables(
                        hostname,
                        rule_meta_to_delete['dtype'],
                        rule_meta_to_delete['dport'],
                        rule_meta_to_delete['sport'],
                        container_ip_at_creation_time=rule_meta_to_delete.get('container_ip')
                    )
                    if delete_attempt_result.get('code') == 200:
                        logger.info(f"成功删除 NAT 规则 (重装前): {rule_meta_to_delete} for {hostname}")
                    else:
                        logger.warning(f"删除 NAT 规则 (重装前) {rule_meta_to_delete} for {hostname} 可能失败. 原因: {delete_attempt_result.get('msg')}")

            logger.info(f"准备删除旧容器 {hostname}...")
            container.delete(wait=True)
            logger.info(f"旧容器 {hostname} 已删除，开始创建新容器...")

            reinstall_lxd_config = {
                'name': hostname,
                'source': {'type': 'image', 'alias': new_os_alias or app_config.default_image_alias},
                'config': preserved_config,
                'devices': preserved_devices
            }
            reinstall_lxd_config['devices']['root'] = {'path': '/', 'pool': app_config.storage_pool, 'size': new_root_size, 'type': 'disk'}

            new_container = self.client.containers.create(reinstall_lxd_config, wait=True)
            logger.info(f"新容器 {hostname} 配置完成，开始启动...")
            new_container.start(wait=True)
            logger.info(f"容器 {hostname} 重装并启动成功.")

            # 这部分是设置密码和SSH配置，即使失败也不影响重装成功
            ssh_config_success = True  # 标记SSH配置是否成功
            logger.info(f"重装后的容器 {hostname} 已启动，准备设置密码...")
            time.sleep(10)

            if not new_password:
                logger.error(f"为重装后的容器 {hostname} 设置密码失败：未提供密码。")
                ssh_config_success = False
            else:
                user_for_password = app_config.default_container_user
                try:
                    # 检测是否为Alpine系统
                    is_alpine = False
                    try:
                        exit_code, stdout, _ = new_container.execute(['/bin/sh', '-c', 'cat /etc/os-release | grep -i alpine'])
                        if exit_code == 0 and stdout:
                            stdout_str = stdout.decode('utf-8', errors='ignore')
                            if 'alpine' in stdout_str.lower():
                                is_alpine = True
                                logger.info(f"检测到容器 {hostname} 为Alpine系统，将使用特定的密码设置方法")
                    except Exception as e_detect:
                        logger.warning(f"检测容器 {hostname} 系统类型时出错: {e_detect}")

                    # 添加备用检测方法
                    if not is_alpine:
                        try:
                            # 检查是否存在apk命令(Alpine特有)
                            exit_code, _, _ = new_container.execute(['/bin/sh', '-c', 'which apk'])
                            if exit_code == 0:
                                is_alpine = True
                                logger.info(f"通过apk命令检测到容器 {hostname} 为Alpine系统")
                        except Exception as e_detect2:
                            logger.warning(f"备用方法检测容器 {hostname} 系统类型时出错: {e_detect2}")

                    # 为重装后的容器恢复/添加IPv6路由网卡
                    try:
                        if app_config.ipv6_mode == 'ROUTED' and app_config.ipv6_prefix:
                            from ipv6_manager import allocate
                            ipv6_addr = allocate(hostname)
                            if ipv6_addr:
                                device_name_v6 = 'eth0v6'
                                parent_if = app_config.ipv6_interface or app_config.main_interface
                                new_container.devices[device_name_v6] = {
                                    'type': 'nic',
                                    'name': 'eth0v6',
                                    'nictype': 'routed',
                                    'parent': parent_if,
                                    'ipv6.address': ipv6_addr
                                }
                                new_container.save(wait=True)
                                logger.info(f"为重装后的容器 {hostname} 恢复 IPv6 网卡 {device_name_v6}: {ipv6_addr}")
                                # 确保IPv6转发与NDP代理开启，并为该地址添加NDP代理项
                                try:
                                    self._ensure_ipv6_sysctl(parent_if)
                                except Exception:
                                    pass
                                try:
                                    self._add_ndp_proxy_entry(ipv6_addr, parent_if)
                                except Exception as e_ndp:
                                    logger.warning(f"为重装后的容器 {hostname} 添加NDP代理失败: {e_ndp}")
                                # 等待容器上报IPv6地址到状态，最多6秒
                                try:
                                    import time as _t
                                    for _ in range(6):
                                        st = new_container.state()
                                        has_v6 = False
                                        for nic, nd in (st.network or {}).items():
                                            if 'addresses' in nd:
                                                for a in nd['addresses']:
                                                    if a.get('family') == 'inet6' and a.get('scope') == 'global':
                                                        has_v6 = True
                                                        break
                                            if has_v6: break
                                        if has_v6:
                                            break
                                        _t.sleep(1)
                                except Exception:
                                    pass
                            else:
                                logger.warning(f"为重装后的容器 {hostname} 获取IPv6地址失败，跳过IPv6网卡")
                    except Exception as e:
                        logger.error(f"为重装后的容器 {hostname} 配置IPv6时出错: {e}")

                    escaped_new_password = shlex.quote(new_password)

                    try:
                        if is_alpine:
                            # Alpine特殊处理
                            logger.info(f"为Alpine容器 {hostname} 的用户 {user_for_password} 设置密码")
                            try:
                                # 先安装必要的包（带超时与镜像自动选择）
                                logger.info(f"为Alpine容器 {hostname} 安装必要的软件包（带超时与镜像自动选择）")
                                alpine_setup_script = r'''
set -e
ver=$(cut -d. -f1,2 /etc/alpine-release 2>/dev/null || echo "3.19")
# 优先尝试一组镜像（HTTP，BusyBox环境更友好），找到第一个可达的
mirrors="http://mirrors.edge.kernel.org/alpine http://ftp.halifax.rwth-aachen.de/alpine http://mirror1.hs-esslingen.de/pub/Mirrors/alpine http://dl-cdn.alpinelinux.org/alpine http://mirrors.tencent.com/alpine http://repo.huaweicloud.com/alpine http://mirrors.ustc.edu.cn/alpine http://mirrors.tuna.tsinghua.edu.cn/alpine http://mirrors.aliyun.com/alpine"
GOOD=""
for m in $mirrors; do
  wget -T 8 -O /dev/null $m/v$ver/main/x86_64/APKINDEX.tar.gz >/dev/null 2>&1 && { GOOD=$m; break; } || true
done
if [ -n "$GOOD" ]; then
  printf "%s\n%s\n" "$GOOD/v$ver/main" "$GOOD/v$ver/community" > /etc/apk/repositories
fi
# 使用超时避免长时间卡住
(timeout 120 sh -c "apk update") || (echo "apk update 超时，重试一次" && timeout 120 sh -c "apk update")
(timeout 180 sh -c "apk add --no-cache openssh shadow openrc curl busybox-extras") || (echo "apk add 超时，重试一次" && timeout 180 sh -c "apk add --no-cache openssh shadow openrc curl busybox-extras")
'''
                                exit_code_setup, out_setup, err_setup = new_container.execute(['/bin/sh', '-lc', alpine_setup_script])
                                if exit_code_setup != 0:
                                    out_msg = out_setup.decode('utf-8', errors='ignore') if isinstance(out_setup, (bytes, bytearray)) else str(out_setup)
                                    err_msg = err_setup.decode('utf-8', errors='ignore') if isinstance(err_setup, (bytes, bytearray)) else str(err_setup)
                                    logger.warning(f"Alpine 依赖安装脚本返回非零({exit_code_setup})，STDOUT: {out_msg}, STDERR: {err_msg}")

                                # 使用完整的SSH配置流程
                                logger.info(f"为Alpine容器 {hostname} 配置并启动SSH服务 (完整流程)")

                                # 创建必要的目录
                                new_container.execute(['/bin/sh', '-c', 'mkdir -p /var/run/sshd'])

                                # 修改SSH配置允许root登录和密码认证
                                new_container.execute(['/bin/sh', '-c', 'sed -i "s/#PermitRootLogin.*/PermitRootLogin yes/g" /etc/ssh/sshd_config'])
                                new_container.execute(['/bin/sh', '-c', 'sed -i "s/#PasswordAuthentication.*/PasswordAuthentication yes/g" /etc/ssh/sshd_config'])
                                new_container.execute(['/bin/sh', '-c', 'sed -i "s/PasswordAuthentication.*/PasswordAuthentication yes/g" /etc/ssh/sshd_config'])

                                # 生成SSH密钥（如果不存在）
                                new_container.execute(['/bin/sh', '-c', 'if [ ! -f /etc/ssh/ssh_host_rsa_key ]; then ssh-keygen -A; fi'])

                                # 设置密码
                                command_to_execute = f"echo '{user_for_password}:{escaped_new_password}' | chpasswd"
                                exit_code, stdout, stderr = new_container.execute(['/bin/sh', '-c', command_to_execute])

                                # 添加到启动服务
                                new_container.execute(['/bin/sh', '-c', 'rc-update add sshd default'])

                                # 直接启动SSH服务
                                logger.info(f"直接启动Alpine容器 {hostname} 的SSH服务")
                                start_ssh_output = new_container.execute(['/bin/sh', '-c', '/usr/sbin/sshd'])
                                logger.info(f"启动SSH服务结果: {start_ssh_output}")

                                # 验证SSH服务是否已启动
                                verify_cmd, verify_stdout, verify_stderr = new_container.execute(['/bin/sh', '-c', 'ps | grep sshd'])
                                if verify_stdout:
                                    logger.info(f"SSH进程验证: {verify_stdout.decode('utf-8', errors='ignore')}")
                                else:
                                    logger.warning(f"未检测到SSH进程! stderr: {verify_stderr.decode('utf-8', errors='ignore')}")
                                    ssh_config_success = False

                                # 添加额外的自启动方式（多重保障）
                                new_container.execute(['/bin/sh', '-c', 'mkdir -p /etc/local.d'])
                                new_container.execute(['/bin/sh', '-c', 'echo "#!/bin/sh" > /etc/local.d/sshd.start'])
                                new_container.execute(['/bin/sh', '-c', 'echo "/usr/sbin/sshd" >> /etc/local.d/sshd.start'])
                                new_container.execute(['/bin/sh', '-c', 'chmod +x /etc/local.d/sshd.start'])
                                new_container.execute(['/bin/sh', '-c', 'rc-update add local default'])

                                # 检查22端口是否已在监听
                                port_check_cmd, port_stdout, port_stderr = new_container.execute(['/bin/sh', '-c', 'netstat -tulpn | grep :22'])
                                if port_stdout:
                                    logger.info(f"端口22监听状态: {port_stdout.decode('utf-8', errors='ignore')}")
                                else:
                                    logger.warning(f"端口22未在监听! stderr: {port_stderr.decode('utf-8', errors='ignore')}")
                                    ssh_config_success = False

                                logger.info(f"Alpine容器 {hostname} SSH配置完成")

                            except Exception as e_alpine:
                                logger.error(f"为Alpine容器 {hostname} 安装或配置SSH时出错: {e_alpine}")
                                ssh_config_success = False
                                logger.info(f"尽管SSH配置出现错误，但将继续重装流程以避免上层应用失败: {e_alpine}")
                        else:
                            # 常规系统处理
                            logger.info(f"为常规容器 {hostname} 的用户 {user_for_password} 设置密码 (使用 bash -c 'echo ... | chpasswd')")
                            command_to_execute_in_bash = f"echo '{user_for_password}:{escaped_new_password}' | chpasswd"
                            exit_code, stdout, stderr = new_container.execute(['bash', '-c', command_to_execute_in_bash])

                        if exit_code == 0:
                            logger.info(f"重装后的容器 {hostname} 密码设置成功")
                        else:
                            err_msg_stdout = stdout.decode('utf-8', errors='ignore').strip() if stdout else ""
                            err_msg_stderr = stderr.decode('utf-8', errors='ignore').strip() if stderr else ""
                            full_err_msg = []
                            if err_msg_stdout: full_err_msg.append(f"STDOUT: {err_msg_stdout}")
                            if err_msg_stderr: full_err_msg.append(f"STDERR: {err_msg_stderr}")
                            combined_err_msg = "; ".join(full_err_msg) if full_err_msg else "命令执行失败，但未提供具体错误信息"
                            logger.error(f"重装后的容器 {hostname} 设置密码失败 (exit_code: {exit_code}): {combined_err_msg}")
                            ssh_config_success = False
                    except Exception as e_ssh:
                        logger.error(f"为容器 {hostname} 配置SSH时发生异常: {e_ssh}")
                        ssh_config_success = False
                except LXDAPIException as e_passwd:
                    logger.error(f"为重装后的容器 {hostname} 设置密码时发生LXD API错误: {e_passwd}")
                    ssh_config_success = False
                except Exception as e_passwd_generic:
                    logger.error(f"为重装后的容器 {hostname} 设置密码时发生未知错误: {e_passwd_generic}", exc_info=True)
                    ssh_config_success = False

            # NAT规则添加也不影响重装成功
            nat_config_success = True
            try:
                # 先等待IP地址分配
                container_ip_for_nat_reinstall = None
                nat_add_attempts_reinstall = 0
                while not container_ip_for_nat_reinstall and nat_add_attempts_reinstall < 3:
                    container_ip_for_nat_reinstall = self._get_container_ip(new_container)
                    if container_ip_for_nat_reinstall: break
                    logger.warning(f"为重装后的容器 {hostname} 获取IP失败 (尝试 {nat_add_attempts_reinstall+1}/3)，等待后重试...")
                    time.sleep(5)
                    nat_add_attempts_reinstall += 1

                if not container_ip_for_nat_reinstall:
                    logger.error(f"为重装后的容器 {hostname} 恢复端口转发规则失败：多次尝试后仍无法获取容器IP地址。")
                    nat_config_success = False
                else:
                    # 1. 确保SSH端口转发存在（优先级高）
                    if original_ssh_port:
                        ssh_port_to_use = original_ssh_port
                        logger.info(f"使用原始SSH端口 {ssh_port_to_use} 为容器 {hostname} 添加NAT规则")
                    else:
                        ssh_external_port_min_reinstall = 10000
                        ssh_external_port_max_reinstall = 65535
                        ssh_port_to_use = random.randint(ssh_external_port_min_reinstall, ssh_external_port_max_reinstall)
                        logger.info(f"没有找到原始SSH端口，使用随机端口 {ssh_port_to_use} 为容器 {hostname} 添加NAT规则")

                    logger.info(f"尝试为重装后的容器 {hostname} 自动添加 SSH (端口 22) 的 NAT 规则，使用外部端口 {ssh_port_to_use}")
                    add_ssh_rule_result_reinstall = self.add_nat_rule_via_iptables(new_container.name, 'tcp', str(ssh_port_to_use), '22')
                    if add_ssh_rule_result_reinstall.get('code') == 200:
                        logger.info(f"成功为重装后的容器 {hostname} 自动添加 SSH NAT 规则: 外部端口 {ssh_port_to_use} -> 内部端口 22")
                    elif add_ssh_rule_result_reinstall.get('code') == 409:
                        logger.warning(f"尝试为重装后的容器 {hostname} 自动添加 SSH NAT 规则失败：外部端口 {ssh_port_to_use} 已被此容器的其他规则使用。可尝试手动添加其他端口。")
                    else:
                        logger.error(f"为重装后的容器 {hostname} 自动添加 SSH NAT 规则失败。外部端口: {ssh_port_to_use}, 原因: {add_ssh_rule_result_reinstall.get('msg')}")

                    # 2. 恢复先前保存的所有端口转发规则
                    restored_count = 0
                    failed_count = 0

                    # 排除SSH规则以避免重复添加
                    saved_non_ssh_nat_rules = []
                    for rule in saved_nat_rules:
                        # 跳过SSH规则，因为我们已经添加了
                        if rule.get('Dtype', '').lower() == 'tcp' and str(rule.get('Sport')) == '22':
                            continue
                        saved_non_ssh_nat_rules.append(rule)

                    logger.info(f"开始为容器 {hostname} 恢复 {len(saved_non_ssh_nat_rules)} 条非SSH端口转发规则")

                    for rule in saved_non_ssh_nat_rules:
                        rule_type = rule.get('Dtype', '').lower()  # 注意这里的键名大写开头
                        dport = rule.get('Dport')                  # 注意这里的键名大写开头
                        sport = rule.get('Sport')                  # 注意这里的键名大写开头

                        if not all([rule_type, dport, sport]):
                            logger.warning(f"跳过无效的端口转发规则: {rule}")
                            failed_count += 1
                            continue

                        logger.info(f"恢复端口转发规则: {rule_type} {dport} -> {sport}")
                        result = self.add_nat_rule_via_iptables(hostname, rule_type, str(dport), str(sport))

                        if result.get('code') == 200:
                            logger.info(f"成功恢复端口转发规则: {rule_type} {dport} -> {sport}")
                            restored_count += 1
                        else:
                            logger.warning(f"恢复端口转发规则失败: {rule_type} {dport} -> {sport}, 原因: {result.get('msg')}")
                            failed_count += 1

                    logger.info(f"容器 {hostname} 的端口转发规则恢复完成: 成功 {restored_count}, 失败 {failed_count}")

                    if failed_count > 0:
                        nat_config_success = False
            except Exception as e_nat_reinstall:
                logger.error(f"为重装后的容器 {hostname} 恢复端口转发规则时发生异常: {str(e_nat_reinstall)}", exc_info=True)
                nat_config_success = False

            # 重装成功但SSH或NAT可能有问题
            if not ssh_config_success:
                logger.warning(f"容器 {hostname} 重装成功，但SSH配置可能有问题")
            if not nat_config_success:
                logger.warning(f"容器 {hostname} 重装成功，但部分端口转发规则可能没有成功恢复")

            # 不管SSH或NAT是否配置成功，只要容器创建和启动成功，就返回成功状态
            return {'code': 200, 'msg': '系统重装成功'}

        except LXDAPIException as e:
            logger.error(f"LXD API错误 (reinstall {hostname}): {e}")
            return {'code': 500, 'msg': f'LXD API错误 (reinstall): {e}'}
        except Exception as e:
            logger.error(f"重装容器 {hostname} 时发生内部错误: {str(e)}", exc_info=True)
            return {'code': 500, 'msg': f'重装容器时发生内部错误: {str(e)}'}

    def list_nat_rules(self, hostname):
        logger.debug(f"列出容器 {hostname} 的NAT规则")

        # 检查容器是否存在
        container = self._get_container_or_error(hostname)
        if not container:
            logger.warning(f"获取NAT规则失败: 容器 {hostname} 不存在")
            return {'code': 404, 'msg': '容器未找到', 'data': []}

        # 从元数据中读取规则
        rules_metadata = _load_iptables_rules_metadata()
        container_rules = []

        # 遍历元数据中的规则
        for rule_meta in rules_metadata:
            if rule_meta.get('hostname') == hostname:
                container_rules.append({
                    'Dtype': rule_meta.get('dtype','').upper(),  # 使用大写开头的键名
                    'Dport': rule_meta.get('dport'),            # 使用大写开头的键名
                    'Sport': rule_meta.get('sport'),            # 使用大写开头的键名
                    'ID': rule_meta.get('rule_id', f"iptables-{rule_meta.get('dtype')}-{rule_meta.get('dport')}")  # 使用大写开头的键名
                })

        # 同时检查容器设备是否有proxy设备（用于兼容性检查）
        for device_name, device_info in container.devices.items():
            if device_info.get('type') == 'proxy' and device_name.startswith('nat-'):
                try:
                    listen_parts = device_info.get('listen', '').split(':')
                    connect_parts = device_info.get('connect', '').split(':')

                    if len(listen_parts) == 3 and len(connect_parts) == 3:
                        dtype = listen_parts[0].lower()
                        dport = listen_parts[2]
                        sport = connect_parts[2]

                        # 检查是否已在元数据中
                        rule_exists = False
                        for rule in container_rules:
                            if (rule.get('Dtype', '').lower() == dtype and  # 注意这里使用大写键名
                                str(rule.get('Dport')) == str(dport) and
                                str(rule.get('Sport')) == str(sport)):
                                rule_exists = True
                                break

                        # 如果不存在，添加到列表
                        if not rule_exists:
                            logger.info(f"在容器 {hostname} 的设备中发现未在元数据中的proxy设备: {device_name}")
                            container_rules.append({
                                'Dtype': dtype.upper(),  # 使用大写开头的键名
                                'Dport': dport,          # 使用大写开头的键名
                                'Sport': sport,          # 使用大写开头的键名
                                'ID': f"proxy-{dtype}-{dport}"  # 使用大写开头的键名
                            })
                except Exception as e:
                    logger.warning(f"解析容器 {hostname} 的proxy设备 {device_name} 时发生错误: {str(e)}")

        logger.info(f"容器 {hostname} NAT规则列表: {container_rules}")
        return {'code': 200, 'msg': '获取成功', 'data': container_rules}

    def delete_nat_rule_via_iptables(self, hostname, dtype, dport, sport, container_ip_at_creation_time=None):
        logger.info(f"为容器 {hostname} 删除端口转发规则: {dtype} {dport} -> {sport}")

        # 加载元数据
        rules_metadata = _load_iptables_rules_metadata()
        rule_comment_to_use = f'lxd_controller_nat_{hostname}_{dtype.lower()}_{dport}'
        device_name = f"nat-{dtype.lower()}-{dport}"

        # 找到要删除的规则元数据
        rule_to_delete_meta = None
        for idx, rule_meta_item in enumerate(rules_metadata):
            if (rule_meta_item.get('hostname') == hostname and
                rule_meta_item.get('dtype', '').lower() == dtype.lower() and
                str(rule_meta_item.get('dport')) == str(dport) and
                str(rule_meta_item.get('sport')) == str(sport)):
                rule_to_delete_meta = rule_meta_item
                rule_comment_to_use = rule_meta_item.get('rule_id', rule_comment_to_use)
                break

        # 尝试获取容器
        container = None
        try:
            container = self._get_container_or_error(hostname)
        except Exception as e:
            logger.warning(f"获取容器 {hostname} 失败，可能已被删除: {str(e)}")

        # 如果容器存在，删除proxy设备（v4、旧后缀 -v4 以及可能存在的 -v6）
        if container:
            try:
                removed_any = False
                for dev in (device_name, f"{device_name}-v6", f"{device_name}-v4"):
                    if dev in container.devices:
                        del container.devices[dev]
                        removed_any = True
                        logger.info(f"计划从容器 {hostname} 中删除proxy设备 {dev}")
                if removed_any:
                    container.save(wait=True)
                    logger.info(f"成功保存容器 {hostname} 的设备变更")
                else:
                    logger.warning(f"未找到容器 {hostname} 中的proxy设备 {device_name} 或对应的 IPv6/旧 v4 设备")
            except Exception as e:
                logger.error(f"从容器 {hostname} 删除proxy设备 {device_name} (含可能的 -v6/-v4) 时发生异常: {str(e)}", exc_info=True)

        # 清理元数据
        modified = False
        final_rules = []
        for rule in rules_metadata:
            if (rule.get('hostname') == hostname and
                rule.get('dtype', '').lower() == dtype.lower() and
                str(rule.get('dport')) == str(dport) and
                str(rule.get('sport')) == str(sport)):
                modified = True
                continue
            final_rules.append(rule)

        # 保存更新后的元数据
        if modified:
            _save_iptables_rules_metadata(final_rules)
            logger.info(f"成功从元数据中删除规则: {hostname} {dtype} {dport} -> {sport}")
        else:
            logger.warning(f"在元数据中未找到要删除的规则: {hostname} {dtype} {dport} -> {sport}")

        return {'code': 200, 'msg': '端口转发规则删除成功'}

    # === CPU 限制管理 ===

    def update_cpu_limit(self, hostname, cpu_percent):
        """
        更新容器的 CPU 使用率百分比限制
        
        参数:
            hostname: 容器名称
            cpu_percent: CPU 使用率百分比（如 50 表示 50%，200 表示 200%）
                        0 或 None 表示移除限制
        
        返回:
            {'code': 200/404/500, 'msg': '...'}
        """
        try:
            container = self._get_container_or_error(hostname)
            if not container:
                return {'code': 404, 'msg': f'容器 {hostname} 不存在'}
            
            # 转换参数
            try:
                cpu_percent = int(cpu_percent) if cpu_percent else 0
            except (ValueError, TypeError):
                return {'code': 400, 'msg': f'无效的 CPU 百分比值: {cpu_percent}'}
            
            # 设置或移除 CPU 限制
            if cpu_percent > 0:
                container.config['limits.cpu.allowance'] = f"{cpu_percent}%"
                logger.info(f"设置容器 {hostname} CPU 限制为 {cpu_percent}%")
                msg = f'CPU 限制已更新为 {cpu_percent}%'
            else:
                # 移除限制
                if 'limits.cpu.allowance' in container.config:
                    del container.config['limits.cpu.allowance']
                    logger.info(f"移除容器 {hostname} 的 CPU 百分比限制")
                msg = 'CPU 百分比限制已移除'
            
            container.save(wait=True)
            return {'code': 200, 'msg': msg}
            
        except LXDAPIException as e:
            logger.error(f"更新容器 {hostname} CPU 限制时发生 LXD API 错误: {e}")
            return {'code': 500, 'msg': f'LXD API 错误: {e}'}
        except Exception as e:
            logger.error(f"更新容器 {hostname} CPU 限制时发生错误: {e}", exc_info=True)
            return {'code': 500, 'msg': f'更新 CPU 限制失败: {str(e)}'}

    def get_cpu_limit(self, hostname):
        """
        获取容器的 CPU 限制信息
        
        返回:
            {'code': 200/404/500, 'msg': '...', 'data': {'cpu_cores': '1', 'cpu_percent': 100}}
        """
        try:
            container = self._get_container_or_error(hostname)
            if not container:
                return {'code': 404, 'msg': f'容器 {hostname} 不存在'}
            
            cpu_cores = container.config.get('limits.cpu', '不限')
            cpu_allowance = container.config.get('limits.cpu.allowance', '')
            
            # 解析 CPU 百分比
            cpu_percent = None
            if cpu_allowance:
                # 格式可能是 "50%" 或 "2x50%"
                import re
                match = re.search(r'(\d+)%', cpu_allowance)
                if match:
                    cpu_percent = int(match.group(1))
            
            data = {
                'cpu_cores': cpu_cores,
                'cpu_allowance': cpu_allowance if cpu_allowance else '不限',
                'cpu_percent': cpu_percent
            }
            
            return {'code': 200, 'msg': '获取成功', 'data': data}
            
        except LXDAPIException as e:
            logger.error(f"获取容器 {hostname} CPU 限制时发生 LXD API 错误: {e}")
            return {'code': 500, 'msg': f'LXD API 错误: {e}'}
        except Exception as e:
            logger.error(f"获取容器 {hostname} CPU 限制时发生错误: {e}", exc_info=True)
            return {'code': 500, 'msg': f'获取 CPU 限制失败: {str(e)}'}

    def batch_update_cpu_limit(self, updates):
        """
        批量更新容器的 CPU 限制
        
        参数:
            updates: 列表，格式 [{'hostname': 'xxx', 'cpu_percent': 50}, ...]
        
        返回:
            {'code': 200, 'msg': '...', 'data': {'success': [...], 'failed': [...]}}
        """
        success = []
        failed = []
        
        for item in updates:
            hostname = item.get('hostname')
            cpu_percent = item.get('cpu_percent')
            
            if not hostname:
                failed.append({'hostname': '未指定', 'reason': '缺少 hostname'})
                continue
            
            result = self.update_cpu_limit(hostname, cpu_percent)
            if result['code'] == 200:
                success.append(hostname)
            else:
                failed.append({'hostname': hostname, 'reason': result['msg']})
        
        return {
            'code': 200,
            'msg': f'批量更新完成: 成功 {len(success)} 个, 失败 {len(failed)} 个',
            'data': {'success': success, 'failed': failed}
        }