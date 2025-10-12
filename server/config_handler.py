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

        # IPv6 相关配置（可选）
        self.ipv6_mode = parser.get('lxc', 'IPV6_MODE', fallback='OFF').upper()  # OFF | ROUTED | NDP_PROXY | NAT66
        self.ipv6_prefix = parser.get('lxc', 'IPV6_PREFIX', fallback=None)       # 例如 2001:db8:abcd:1234::/64
        self.ipv6_interface = parser.get('lxc', 'IPV6_INTERFACE', fallback=self.main_interface)

        # 端口映射连通性自检开关（严格模式：失败即回滚并报错）。默认开启严格模式。
        self.portmap_selftest_strict = parser.getboolean('lxc', 'PORTMAP_SELFTEST_STRICT', fallback=True)

        if not self.nat_listen_ip:
            raise ValueError("配置文件 [lxc] 中必须设置 NAT_LISTEN_IP，因为NAT模式已固定开启")

        if not self.main_interface:
            raise ValueError("配置文件 [lxc] 中必须设置 MAIN_INTERFACE (主网卡名)，用于iptables MASQUERADE规则")

app_config = AppConfig()