#!/bin/bash
#===============================================
# 网络模式切换脚本
# 快速切换 IPv4/IPv6 网络模式
#===============================================

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_FILE="$SCRIPT_DIR/app.ini"

# 检查配置文件
if [ ! -f "$CONFIG_FILE" ]; then
    echo -e "${RED}[错误]${NC} 找不到配置文件: $CONFIG_FILE"
    exit 1
fi

# 读取当前配置
get_current_config() {
    local key=$1
    grep "^$key\s*=" "$CONFIG_FILE" 2>/dev/null | cut -d'=' -f2 | tr -d ' ' || echo "未设置"
}

# 更新配置
update_config() {
    local key=$1
    local value=$2
    
    if grep -q "^$key\s*=" "$CONFIG_FILE"; then
        # 已存在，更新
        sed -i "s|^$key\s*=.*|$key = $value|g" "$CONFIG_FILE"
    else
        # 不存在，在 [lxc] 节下添加
        sed -i "/^\[lxc\]/a $key = $value" "$CONFIG_FILE"
    fi
}

# 显示当前配置
show_current_config() {
    echo -e "\n${CYAN}当前网络配置:${NC}"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    
    local ipv4_mode=$(get_current_config "IPV4_MODE")
    local ipv6_mode=$(get_current_config "IPV6_MODE")
    local ipv6_prefix=$(get_current_config "IPV6_PREFIX")
    local nat_ip=$(get_current_config "NAT_LISTEN_IP")
    
    echo "  IPV4_MODE:    ${ipv4_mode:-BRIDGE (默认)}"
    echo "  IPV6_MODE:    ${ipv6_mode:-OFF}"
    
    if [ "$ipv6_mode" != "OFF" ] && [ "$ipv6_mode" != "未设置" ]; then
        echo "  IPV6_PREFIX:  ${ipv6_prefix:-未设置}"
    fi
    
    if [ "$ipv4_mode" != "OFF" ] && [ "$ipv4_mode" != "未设置" ]; then
        echo "  NAT_LISTEN_IP: ${nat_ip:-未设置}"
    fi
    
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
}

# 显示网络模式说明
show_network_modes() {
    echo -e "\n${CYAN}可用的网络模式:${NC}"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "  1) 仅 IPv4 (NAT)"
    echo "     - IPV4_MODE=BRIDGE, IPV6_MODE=OFF"
    echo "     - 容器使用 NAT IPv4，无 IPv6"
    echo ""
    echo "  2) 双栈 (IPv4 NAT + 独立 IPv6)"
    echo "     - IPV4_MODE=BRIDGE, IPV6_MODE=ROUTED"
    echo "     - 容器同时拥有 NAT IPv4 和独立 IPv6"
    echo ""
    echo "  3) 仅 IPv6 (独立公网地址)"
    echo "     - IPV4_MODE=OFF, IPV6_MODE=ROUTED"
    echo "     - 容器仅使用独立 IPv6，无 IPv4"
    echo ""
    echo "  4) 自定义配置"
    echo "     - 手动设置各项参数"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
}

# 配置模式 1：仅 IPv4
configure_ipv4_only() {
    echo -e "\n${CYAN}[模式 1] 配置仅 IPv4 (NAT)${NC}"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    
    # 检查 NAT_LISTEN_IP
    local nat_ip=$(get_current_config "NAT_LISTEN_IP")
    if [ -z "$nat_ip" ] || [ "$nat_ip" = "未设置" ]; then
        echo -e "${YELLOW}[提示]${NC} 需要设置 NAT_LISTEN_IP"
        read -p "请输入服务器的公网 IPv4 地址: " nat_ip
        
        if [ -z "$nat_ip" ]; then
            echo -e "${RED}[错误]${NC} NAT_LISTEN_IP 不能为空"
            return 1
        fi
        
        update_config "NAT_LISTEN_IP" "$nat_ip"
    fi
    
    # 更新配置
    update_config "IPV4_MODE" "BRIDGE"
    update_config "IPV6_MODE" "OFF"
    
    echo -e "${GREEN}[完成]${NC} 已配置为仅 IPv4 模式"
    echo ""
    echo "配置结果:"
    echo "  IPV4_MODE = BRIDGE"
    echo "  IPV6_MODE = OFF"
    echo "  NAT_LISTEN_IP = $nat_ip"
}

# 配置模式 2：双栈
configure_dual_stack() {
    echo -e "\n${CYAN}[模式 2] 配置双栈 (IPv4 + IPv6)${NC}"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    
    # 检查 NAT_LISTEN_IP
    local nat_ip=$(get_current_config "NAT_LISTEN_IP")
    if [ -z "$nat_ip" ] || [ "$nat_ip" = "未设置" ]; then
        echo -e "${YELLOW}[提示]${NC} 需要设置 NAT_LISTEN_IP"
        read -p "请输入服务器的公网 IPv4 地址: " nat_ip
        
        if [ -z "$nat_ip" ]; then
            echo -e "${RED}[错误]${NC} NAT_LISTEN_IP 不能为空"
            return 1
        fi
        
        update_config "NAT_LISTEN_IP" "$nat_ip"
    fi
    
    # 检查 IPv6 前缀
    local ipv6_prefix=$(get_current_config "IPV6_PREFIX")
    if [ -z "$ipv6_prefix" ] || [ "$ipv6_prefix" = "未设置" ]; then
        echo -e "${YELLOW}[提示]${NC} 需要设置 IPv6 前缀"
        read -p "请输入 IPv6 /64 前缀 (例如 2001:db8::/64): " ipv6_prefix
        
        if [ -z "$ipv6_prefix" ]; then
            echo -e "${RED}[错误]${NC} IPV6_PREFIX 不能为空"
            return 1
        fi
        
        update_config "IPV6_PREFIX" "$ipv6_prefix"
    fi
    
    # 更新配置
    update_config "IPV4_MODE" "BRIDGE"
    update_config "IPV6_MODE" "ROUTED"
    
    echo -e "${GREEN}[完成]${NC} 已配置为双栈模式"
    echo ""
    echo "配置结果:"
    echo "  IPV4_MODE = BRIDGE"
    echo "  IPV6_MODE = ROUTED"
    echo "  NAT_LISTEN_IP = $nat_ip"
    echo "  IPV6_PREFIX = $ipv6_prefix"
}

# 配置模式 3：仅 IPv6
configure_ipv6_only() {
    echo -e "\n${CYAN}[模式 3] 配置仅 IPv6 (独立公网地址)${NC}"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    
    # 检查 IPv6 前缀
    local ipv6_prefix=$(get_current_config "IPV6_PREFIX")
    if [ -z "$ipv6_prefix" ] || [ "$ipv6_prefix" = "未设置" ]; then
        echo -e "${YELLOW}[提示]${NC} 需要设置 IPv6 前缀"
        read -p "请输入 IPv6 /64 前缀 (例如 2001:db8::/64): " ipv6_prefix
        
        if [ -z "$ipv6_prefix" ]; then
            echo -e "${RED}[错误]${NC} IPV6_PREFIX 不能为空"
            return 1
        fi
        
        update_config "IPV6_PREFIX" "$ipv6_prefix"
    fi
    
    # 更新配置
    update_config "IPV4_MODE" "OFF"
    update_config "IPV6_MODE" "ROUTED"
    
    echo -e "${GREEN}[完成]${NC} 已配置为仅 IPv6 模式"
    echo ""
    echo "配置结果:"
    echo "  IPV4_MODE = OFF"
    echo "  IPV6_MODE = ROUTED"
    echo "  IPV6_PREFIX = $ipv6_prefix"
    echo ""
    echo -e "${YELLOW}[注意]${NC} IPv6-Only 模式限制:"
    echo "  - 无法使用端口转发功能"
    echo "  - 无法设置带宽限制"
    echo "  - 无法访问纯 IPv4 网站"
}

# 自定义配置
configure_custom() {
    echo -e "\n${CYAN}[模式 4] 自定义配置${NC}"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    
    # IPv4 模式
    echo ""
    echo "IPv4 模式:"
    echo "  1) BRIDGE - 使用 NAT IPv4"
    echo "  2) OFF - 禁用 IPv4"
    read -p "请选择 IPv4 模式 [1/2]: " ipv4_choice
    
    case "$ipv4_choice" in
        1)
            local ipv4_mode="BRIDGE"
            read -p "请输入 NAT_LISTEN_IP (公网 IPv4): " nat_ip
            update_config "NAT_LISTEN_IP" "$nat_ip"
            ;;
        2)
            local ipv4_mode="OFF"
            ;;
        *)
            echo -e "${RED}[错误]${NC} 无效选择"
            return 1
            ;;
    esac
    
    update_config "IPV4_MODE" "$ipv4_mode"
    
    # IPv6 模式
    echo ""
    echo "IPv6 模式:"
    echo "  1) ROUTED - 独立 IPv6 地址"
    echo "  2) OFF - 禁用 IPv6"
    read -p "请选择 IPv6 模式 [1/2]: " ipv6_choice
    
    case "$ipv6_choice" in
        1)
            local ipv6_mode="ROUTED"
            read -p "请输入 IPV6_PREFIX (/64 前缀): " ipv6_prefix
            update_config "IPV6_PREFIX" "$ipv6_prefix"
            ;;
        2)
            local ipv6_mode="OFF"
            ;;
        *)
            echo -e "${RED}[错误]${NC} 无效选择"
            return 1
            ;;
    esac
    
    update_config "IPV6_MODE" "$ipv6_mode"
    
    echo -e "\n${GREEN}[完成]${NC} 自定义配置已保存"
}

# 重启服务
restart_service() {
    echo -e "\n${CYAN}是否重启 API 服务使配置生效?${NC}"
    read -p "[y/N]: " restart
    
    if [[ "${restart,,}" == "y" ]]; then
        echo -e "${CYAN}[处理]${NC} 重启服务..."
        
        if systemctl restart lxd-api.service; then
            echo -e "${GREEN}[完成]${NC} 服务重启成功"
            
            # 等待服务启动
            sleep 2
            
            # 检查服务状态
            if systemctl is-active --quiet lxd-api.service; then
                echo -e "${GREEN}[状态]${NC} 服务运行正常"
            else
                echo -e "${RED}[警告]${NC} 服务状态异常，请检查日志:"
                echo "  journalctl -u lxd-api.service -n 50"
            fi
        else
            echo -e "${RED}[错误]${NC} 服务重启失败"
        fi
    else
        echo -e "${YELLOW}[提示]${NC} 配置已保存，请手动重启服务:"
        echo "  systemctl restart lxd-api.service"
    fi
}

# 主菜单
main_menu() {
    clear
    echo -e "${GREEN}=========================================="
    echo -e "  网络模式配置工具"
    echo -e "==========================================${NC}"
    
    show_current_config
    show_network_modes
    
    echo ""
    read -p "请选择操作 [1-4, 0=退出]: " choice
    
    case "$choice" in
        1)
            configure_ipv4_only
            if [ $? -eq 0 ]; then
                restart_service
            fi
            ;;
        2)
            configure_dual_stack
            if [ $? -eq 0 ]; then
                restart_service
            fi
            ;;
        3)
            configure_ipv6_only
            if [ $? -eq 0 ]; then
                restart_service
            fi
            ;;
        4)
            configure_custom
            if [ $? -eq 0 ]; then
                restart_service
            fi
            ;;
        0)
            echo -e "\n${CYAN}再见！${NC}\n"
            exit 0
            ;;
        *)
            echo -e "\n${RED}[错误]${NC} 无效选择\n"
            sleep 2
            main_menu
            ;;
    esac
    
    echo ""
    read -p "按任意键返回主菜单..." -n1
    main_menu
}

# 检查 root 权限
if [ "$EUID" -ne 0 ]; then
    echo -e "${RED}[错误]${NC} 此脚本需要 root 权限运行"
    echo "请使用: sudo bash $0"
    exit 1
fi

# 启动主菜单
main_menu

