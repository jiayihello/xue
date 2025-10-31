#!/bin/bash

# 修复 app.ini 配置脚本
# 用于手动更新 IPv4 和 IPv6 配置

set -e

# 颜色定义
COLOR_GREEN='\033[0;32m'
COLOR_YELLOW='\033[1;33m'
COLOR_CYAN='\033[0;36m'
COLOR_NC='\033[0m' # No Color

echo -e "${COLOR_CYAN}=========================================="
echo -e "  修复 app.ini 配置工具"
echo -e "==========================================${COLOR_NC}"
echo ""

# 检查 app.ini 是否存在
if [ ! -f "app.ini" ]; then
    echo -e "${COLOR_YELLOW}[!] 未找到 app.ini 文件${COLOR_NC}"
    exit 1
fi

# 显示当前配置
echo -e "${COLOR_CYAN}当前 app.ini 配置:${COLOR_NC}"
echo "----------------------------------------"
grep "^NAT_LISTEN_IP\s*=" app.ini || echo "NAT_LISTEN_IP = (未设置)"
grep "^IPV6_MODE\s*=" app.ini || echo "IPV6_MODE = (未设置)"
grep "^IPV6_PREFIX\s*=" app.ini || echo "IPV6_PREFIX = (未设置)"
echo "----------------------------------------"
echo ""

# 询问是否更新
read -p "$(echo -e "${COLOR_YELLOW}是否要更新配置? [y/N]:${COLOR_NC} ")" confirm
if [[ ! "${confirm,,}" =~ ^(y|yes)$ ]]; then
    echo "操作已取消"
    exit 0
fi

echo ""

# 输入 IPv4 地址
while true; do
    read -p "$(echo -e "${COLOR_YELLOW}请输入服务器的 IPv4 地址:${COLOR_NC} ")" IPV4_ADDRESS
    if [[ "$IPV4_ADDRESS" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
        echo -e "${COLOR_GREEN}[✓] IPv4 地址: $IPV4_ADDRESS${COLOR_NC}"
        break
    else
        echo -e "${COLOR_YELLOW}[!] 无效的 IPv4 地址格式，请重新输入${COLOR_NC}"
    fi
done

# 选择 IPv6 模式
echo ""
echo "选择 IPv6 模式:"
echo "  1) ROUTED  - 路由模式（分配独立IPv6地址）"
echo "  2) NAT66   - NAT66模式（IPv6地址转换）"
echo "  3) OFF     - 禁用IPv6"
echo ""

while true; do
    read -p "$(echo -e "${COLOR_YELLOW}请选择 IPv6 模式 [1/2/3]:${COLOR_NC} ")" ipv6_choice
    case "$ipv6_choice" in
        1)
            IPV6_MODE="ROUTED"
            echo ""
            read -p "$(echo -e "${COLOR_YELLOW}请输入 IPv6 前缀 (例如 2001:db8::/64):${COLOR_NC} ")" IPV6_PREFIX
            echo -e "${COLOR_GREEN}[✓] IPv6 模式: $IPV6_MODE, 前缀: $IPV6_PREFIX${COLOR_NC}"
            break
            ;;
        2)
            IPV6_MODE="NAT66"
            echo ""
            read -p "$(echo -e "${COLOR_YELLOW}请输入 NAT66 配置 (例如 fd00::/64):${COLOR_NC} ")" IPV6_PREFIX
            echo -e "${COLOR_GREEN}[✓] IPv6 模式: $IPV6_MODE, 配置: $IPV6_PREFIX${COLOR_NC}"
            break
            ;;
        3)
            IPV6_MODE="OFF"
            IPV6_PREFIX=""
            echo -e "${COLOR_GREEN}[✓] IPv6 模式: 禁用${COLOR_NC}"
            break
            ;;
        *)
            echo -e "${COLOR_YELLOW}[!] 无效的选择，请输入 1、2 或 3${COLOR_NC}"
            ;;
    esac
done

echo ""
echo -e "${COLOR_CYAN}=========================================="
echo -e "  将进行以下更新"
echo -e "==========================================${COLOR_NC}"
echo "  NAT_LISTEN_IP = $IPV4_ADDRESS"
echo "  IPV6_MODE     = $IPV6_MODE"
if [ -n "$IPV6_PREFIX" ]; then
    echo "  IPV6_PREFIX   = $IPV6_PREFIX"
fi
echo ""

read -p "$(echo -e "${COLOR_YELLOW}确认更新? [y/N]:${COLOR_NC} ")" final_confirm
if [[ ! "${final_confirm,,}" =~ ^(y|yes)$ ]]; then
    echo "操作已取消"
    exit 0
fi

echo ""
echo -e "${COLOR_CYAN}[*] 开始更新配置...${COLOR_NC}"

# 备份原配置
cp app.ini app.ini.backup.$(date +%Y%m%d_%H%M%S)
echo -e "${COLOR_GREEN}[✓] 已备份原配置${COLOR_NC}"

# 更新 NAT_LISTEN_IP
if grep -q "^NAT_LISTEN_IP\s*=" app.ini; then
    sed -i "s|^NAT_LISTEN_IP\s*=.*|NAT_LISTEN_IP = $IPV4_ADDRESS|g" app.ini
else
    echo "NAT_LISTEN_IP = $IPV4_ADDRESS" >> app.ini
fi
echo -e "${COLOR_GREEN}[✓] 已更新 NAT_LISTEN_IP${COLOR_NC}"

# 更新 IPV6_MODE
if grep -q "^IPV6_MODE\s*=" app.ini; then
    sed -i "s|^IPV6_MODE\s*=.*|IPV6_MODE = $IPV6_MODE|g" app.ini
else
    echo "IPV6_MODE = $IPV6_MODE" >> app.ini
fi
echo -e "${COLOR_GREEN}[✓] 已更新 IPV6_MODE${COLOR_NC}"

# 更新 IPV6_PREFIX
if [ -n "$IPV6_PREFIX" ]; then
    if grep -q "^IPV6_PREFIX\s*=" app.ini; then
        sed -i "s|^IPV6_PREFIX\s*=.*|IPV6_PREFIX = $IPV6_PREFIX|g" app.ini
    else
        echo "IPV6_PREFIX = $IPV6_PREFIX" >> app.ini
    fi
    echo -e "${COLOR_GREEN}[✓] 已更新 IPV6_PREFIX${COLOR_NC}"
fi

echo ""
echo -e "${COLOR_GREEN}=========================================="
echo -e "  ✓ 配置更新完成！"
echo -e "==========================================${COLOR_NC}"
echo ""

# 显示新配置
echo -e "${COLOR_CYAN}新的 app.ini 配置:${COLOR_NC}"
echo "----------------------------------------"
grep "^NAT_LISTEN_IP\s*=" app.ini
grep "^IPV6_MODE\s*=" app.ini
grep "^IPV6_PREFIX\s*=" app.ini 2>/dev/null || echo "IPV6_PREFIX = (未设置)"
echo "----------------------------------------"
echo ""

# 询问是否重启服务
if systemctl is-active --quiet lxd-api.service; then
    echo -e "${COLOR_CYAN}检测到 lxd-api.service 正在运行${COLOR_NC}"
    read -p "$(echo -e "${COLOR_YELLOW}是否重启服务以应用新配置? [y/N]:${COLOR_NC} ")" restart_confirm
    
    if [[ "${restart_confirm,,}" =~ ^(y|yes)$ ]]; then
        echo -e "${COLOR_CYAN}[*] 重启服务...${COLOR_NC}"
        systemctl restart lxd-api.service
        echo -e "${COLOR_GREEN}[✓] 服务已重启${COLOR_NC}"
        echo ""
        systemctl status lxd-api.service --no-pager -l
    else
        echo ""
        echo -e "${COLOR_YELLOW}[!] 请手动重启服务以应用新配置:${COLOR_NC}"
        echo "    systemctl restart lxd-api.service"
    fi
else
    echo -e "${COLOR_YELLOW}[!] lxd-api.service 未运行，配置已更新但未应用${COLOR_NC}"
    echo -e "${COLOR_CYAN}启动服务:${COLOR_NC}"
    echo "    systemctl start lxd-api.service"
fi

echo ""
echo -e "${COLOR_GREEN}完成！${COLOR_NC}"

