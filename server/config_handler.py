import configparser
import os

class AppConfig:
    def __init__(self, config_file='app.ini'):
        if not os.path.exists(config_file):
            raise FileNotFoundError(f"配置文件 {config_file} 未找到")

        parser = configparser.ConfigParser()
        parser.read(config_file)

        self.http_port = parser.getint('server', 'HTTP_PORT', fallback=8080)
        self.token = parser.get('server', 'TOKEN', fallback=None)
        self.log_level = parser.get('server', 'LOG_LEVEL', fallback='INFO').upper()

        if not self.token:
            raise ValueError("配置文件中必须提供 API TOKEN")

        self.default_image_alias = parser.get('lxc', 'DEFAULT_IMAGE_ALIAS', fallback='images:alpine/edge')
        self.network_bridge = parser.get('lxc', 'NETWORK_BRIDGE', fallback='lxdbr0')
        self.storage_pool = parser.get('lxc', 'STORAGE_POOL', fallback='default')
        self.default_container_user = parser.get('lxc', 'DEFAULT_CONTAINER_USER', fallback='root')
        self.main_interface = parser.get('lxc', 'MAIN_INTERFACE', fallback=None)
        self.nat_listen_ip = parser.get('lxc', 'NAT_LISTEN_IP', fallback=None)
        self.nat_listen_ipv6 = parser.get('lxc', 'NAT_LISTEN_IPV6', fallback=None)

        # IPv4 相关配置（可选）
        self.ipv4_mode = parser.get('lxc', 'IPV4_MODE', fallback='BRIDGE').upper()  # BRIDGE | OFF

        # IPv6 相关配置（可选）
        self.ipv6_mode = parser.get('lxc', 'IPV6_MODE', fallback='OFF').upper()  # OFF | ROUTED | NDP_PROXY | NAT66
        self.ipv6_prefix = parser.get('lxc', 'IPV6_PREFIX', fallback=None)       # 例如 2001:db8:abcd:1234::/64
        self.ipv6_interface = parser.get('lxc', 'IPV6_INTERFACE', fallback=self.main_interface)
        
        # IPv6 地址池（多个 /128 地址，逗号或分号分隔）
        pool_str = parser.get('lxc', 'IPV6_ADDRESS_POOL', fallback='').strip()
        if pool_str:
            # 支持逗号或分号分隔
            import re
            self.ipv6_address_pool = [addr.strip() for addr in re.split(r'[,;]', pool_str) if addr.strip()]
        else:
            self.ipv6_address_pool = None

        # 端口映射连通性自检开关（严格模式：失败即回滚并报错）。默认开启严格模式。
        self.portmap_selftest_strict = parser.getboolean('lxc', 'PORTMAP_SELFTEST_STRICT', fallback=True)

        # 配置验证：IPv6-Only 模式下不强制要求 NAT_LISTEN_IP
        if self.ipv4_mode != 'OFF' and not self.nat_listen_ip:
            raise ValueError("配置文件 [lxc] 中必须设置 NAT_LISTEN_IP（除非 IPV4_MODE=OFF）")

        if not self.main_interface:
            raise ValueError("配置文件 [lxc] 中必须设置 MAIN_INTERFACE (主网卡名)，用于iptables MASQUERADE规则")
        
        # IPv6-Only 模式额外验证
        if self.ipv4_mode == 'OFF':
            if self.ipv6_mode != 'ROUTED':
                raise ValueError("IPV4_MODE=OFF（IPv6-Only模式）必须配合 IPV6_MODE=ROUTED 使用")
            if not self.ipv6_prefix:
                raise ValueError("IPV6_MODE=ROUTED 必须设置 IPV6_PREFIX")

        # 镜像相关配置（可选）
        self.prebuilt_image = parser.getboolean('image', 'PREBUILT_IMAGE', fallback=False)

        # Celery 配置
        self.celery_broker_url = parser.get('celery', 'BROKER_URL', fallback='redis://127.0.0.1:6379/0')
        self.celery_result_backend = parser.get('celery', 'RESULT_BACKEND', fallback='redis://127.0.0.1:6379/1')

app_config = AppConfig()