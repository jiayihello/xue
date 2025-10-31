#!/bin/bash

echo "╔════════════════════════════════════════════════════════════╗"
echo "║     修复 IPv6-Only 模式开通失败问题                       ║"
echo "╚════════════════════════════════════════════════════════════╝"
echo ""

echo "📋 当前配置检查"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
cd /root/lxd-toolkit/server

echo "1. 检查 IPV4_MODE 配置："
grep "^IPV4_MODE" app.ini || echo "   ⚠️  未找到 IPV4_MODE 配置"

echo ""
echo "2. 检查 IPV6_MODE 配置："
grep "^IPV6_MODE" app.ini || echo "   ⚠️  未找到 IPV6_MODE 配置"

echo ""
echo "3. 检查 IPV6_PREFIX 配置："
grep "^IPV6_PREFIX" app.ini || echo "   ⚠️  未找到 IPV6_PREFIX 配置"

echo ""
echo "4. 检查 IPV6_INTERFACE 配置："
grep "^IPV6_INTERFACE" app.ini || echo "   ⚠️  未找到 IPV6_INTERFACE 配置"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

echo "🔧 [步骤 1/3] 重启 LXD API 服务"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
systemctl restart lxd-api.service
sleep 2

if systemctl is-active --quiet lxd-api.service; then
    echo "✅ LXD API 服务已重启并运行中"
else
    echo "❌ LXD API 服务启动失败！"
    echo ""
    echo "查看错误日志："
    journalctl -u lxd-api.service -n 20 --no-pager
    exit 1
fi

echo ""
echo "🔧 [步骤 2/3] 测试配置读取"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
python3 << 'PYEOF'
import sys
sys.path.insert(0, '/root/lxd-toolkit/server')
from config_handler import app_config

print(f"IPV4_MODE: {app_config.ipv4_mode}")
print(f"IPV6_MODE: {app_config.ipv6_mode}")
print(f"IPV6_PREFIX: {app_config.ipv6_prefix}")
print(f"IPV6_INTERFACE: {app_config.ipv6_interface}")
print(f"NETWORK_BRIDGE: {app_config.network_bridge}")

if app_config.ipv4_mode != 'OFF':
    print("")
    print("⚠️  警告：IPV4_MODE 不是 OFF，当前为:", app_config.ipv4_mode)
    print("   IPv6-Only 模式需要设置 IPV4_MODE = OFF")
    sys.exit(1)

if app_config.ipv6_mode != 'ROUTED':
    print("")
    print("⚠️  警告：IPV6_MODE 不是 ROUTED，当前为:", app_config.ipv6_mode)
    print("   IPv6-Only 模式需要设置 IPV6_MODE = ROUTED")
    sys.exit(1)

if not app_config.ipv6_prefix:
    print("")
    print("⚠️  警告：IPV6_PREFIX 未配置！")
    print("   需要设置你的 /64 前缀，例如：IPV6_PREFIX = 2001:470:19:a0::/64")
    sys.exit(1)

print("")
print("✅ 配置检查通过！")
PYEOF

if [ $? -ne 0 ]; then
    echo ""
    echo "❌ 配置检查失败，请修改 app.ini 后重试"
    exit 1
fi

echo ""
echo "🔧 [步骤 3/3] 测试 IPv6 连接性"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# 检查 IPv6 接口
IPV6_IF=$(grep "^IPV6_INTERFACE" app.ini | cut -d'=' -f2 | tr -d ' ')
if [ -z "$IPV6_IF" ]; then
    IPV6_IF=$(grep "^MAIN_INTERFACE" app.ini | cut -d'=' -f2 | tr -d ' ')
fi

echo "检查接口: $IPV6_IF"
if ip link show "$IPV6_IF" > /dev/null 2>&1; then
    echo "✅ 接口 $IPV6_IF 存在"
    
    # 检查是否有 IPv6 地址
    IPV6_ADDRS=$(ip -6 addr show "$IPV6_IF" | grep "inet6" | grep -v "fe80:" | wc -l)
    if [ "$IPV6_ADDRS" -gt 0 ]; then
        echo "✅ 接口有 IPv6 地址"
        ip -6 addr show "$IPV6_IF" | grep "inet6" | grep -v "fe80:"
    else
        echo "⚠️  接口没有全局 IPv6 地址"
    fi
else
    echo "❌ 接口 $IPV6_IF 不存在！"
    echo "   可用的接口："
    ip link show | grep "^[0-9]" | awk '{print $2}' | sed 's/:$//'
fi

echo ""
echo "╔════════════════════════════════════════════════════════════╗"
echo "║                  ✅ 修复完成！                             ║"
echo "╚════════════════════════════════════════════════════════════╝"
echo ""
echo "📝 接下来需要在魔方财务中配置："
echo ""
echo "   1. 进入产品配置"
echo "   2. 找到该产品的配置参数"
echo "   3. 确保以下参数设置为 0："
echo "      • 上行带宽 (net_in) = 0"
echo "      • 下行带宽 (net_out) = 0"
echo "      • 端口转发数 (nat_acl_limit) = 0"
echo ""
echo "   4. 保存后重新尝试开通"
echo ""
echo "⚠️  重要提示："
echo "   - IPv6-Only 模式不支持带宽限制"
echo "   - IPv6-Only 模式不支持 NAT 端口转发"
echo "   - 这些参数必须设置为 0"
echo ""

