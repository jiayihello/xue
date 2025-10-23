#!/bin/bash
#================================================================
# OpenGFW 管理脚本
# 用途：快速管理 OpenGFW 服务、查看日志、切换规则
#================================================================

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

INSTALL_DIR="/etc/opengfw"

# 打印带颜色的消息
print_header() {
    echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${CYAN}$1${NC}"
    echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
}

print_info() {
    echo -e "${BLUE}[信息]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[✓]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[!]${NC} $1"
}

print_error() {
    echo -e "${RED}[✗]${NC} $1"
}

# 检查服务状态
check_service_status() {
    if systemctl is-active --quiet opengfw.service; then
        return 0
    else
        return 1
    fi
}

# 显示服务状态
show_status() {
    print_header "OpenGFW 服务状态"
    
    if check_service_status; then
        print_success "服务正在运行"
        echo ""
        systemctl status opengfw.service --no-pager -l
    else
        print_error "服务未运行"
        echo ""
        systemctl status opengfw.service --no-pager -l
    fi
    
    echo ""
    read -p "按回车键返回菜单..."
}

# 查看实时日志
view_realtime_logs() {
    print_header "实时日志监控（按 Ctrl+C 退出）"
    echo ""
    print_info "仅显示拦截日志..."
    echo ""
    journalctl -u opengfw -f | grep --color=always "block"
}

# 查看拦截统计
view_block_statistics() {
    print_header "拦截统计（最近 1000 条日志）"
    echo ""
    
    local total_blocks=$(journalctl -u opengfw -n 1000 | grep -c "block" || echo "0")
    
    print_info "总拦截次数: ${total_blocks}"
    echo ""
    
    if [ "$total_blocks" -gt 0 ]; then
        echo "按协议分类："
        echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        
        journalctl -u opengfw -n 1000 | grep "block" | awk '{
            if ($0 ~ /shadowsocks|vmess/) ss++
            else if ($0 ~ /trojan/) trojan++
            else if ($0 ~ /socks/) socks++
            else if ($0 ~ /wireguard/) wg++
            else if ($0 ~ /bittorrent|bt/) bt++
            else other++
        } END {
            if (ss > 0) printf "  Shadowsocks/VMess: %d\n", ss
            if (trojan > 0) printf "  Trojan: %d\n", trojan
            if (socks > 0) printf "  Socks: %d\n", socks
            if (wg > 0) printf "  WireGuard: %d\n", wg
            if (bt > 0) printf "  BitTorrent: %d\n", bt
            if (other > 0) printf "  其他: %d\n", other
        }'
        
        echo ""
        echo "最近 10 次拦截："
        echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        journalctl -u opengfw -n 1000 | grep "block" | tail -n 10
    else
        print_warning "未发现拦截记录"
    fi
    
    echo ""
    read -p "按回车键返回菜单..."
}

# 切换规则文件
switch_rules() {
    print_header "切换规则文件"
    echo ""
    
    if [ ! -d "$INSTALL_DIR" ]; then
        print_error "OpenGFW 未安装"
        sleep 2
        return
    fi
    
    echo "可用规则文件："
    echo "  1) rules.yaml（当前使用）"
    echo "  2) 预设规则-轻量版.yaml（仅拦截核心代理协议）"
    echo "  3) 预设规则-完全版.yaml（拦截所有高危协议）"
    echo "  4) 预设规则-地域限制版.yaml（仅拦截中国大陆）"
    echo "  0) 返回"
    echo ""
    
    read -p "请选择 [0-4]: " choice
    
    case $choice in
        1)
            print_info "已在使用 rules.yaml"
            ;;
        2)
            if [ -f "${INSTALL_DIR}/预设规则-轻量版.yaml" ]; then
                cp "${INSTALL_DIR}/rules.yaml" "${INSTALL_DIR}/rules.yaml.bak"
                cp "${INSTALL_DIR}/预设规则-轻量版.yaml" "${INSTALL_DIR}/rules.yaml"
                systemctl restart opengfw.service
                print_success "已切换到轻量版规则并重启服务"
            else
                print_error "文件不存在"
            fi
            ;;
        3)
            if [ -f "${INSTALL_DIR}/预设规则-完全版.yaml" ]; then
                cp "${INSTALL_DIR}/rules.yaml" "${INSTALL_DIR}/rules.yaml.bak"
                cp "${INSTALL_DIR}/预设规则-完全版.yaml" "${INSTALL_DIR}/rules.yaml"
                systemctl restart opengfw.service
                print_success "已切换到完全版规则并重启服务"
            else
                print_error "文件不存在"
            fi
            ;;
        4)
            if [ -f "${INSTALL_DIR}/预设规则-地域限制版.yaml" ]; then
                cp "${INSTALL_DIR}/rules.yaml" "${INSTALL_DIR}/rules.yaml.bak"
                cp "${INSTALL_DIR}/预设规则-地域限制版.yaml" "${INSTALL_DIR}/rules.yaml"
                systemctl restart opengfw.service
                print_success "已切换到地域限制版规则并重启服务"
            else
                print_error "文件不存在"
            fi
            ;;
        0)
            return
            ;;
        *)
            print_error "无效选择"
            ;;
    esac
    
    echo ""
    read -p "按回车键返回菜单..."
}

# 编辑规则文件
edit_rules() {
    print_header "编辑规则文件"
    echo ""
    
    if [ ! -f "${INSTALL_DIR}/rules.yaml" ]; then
        print_error "规则文件不存在"
        sleep 2
        return
    fi
    
    # 备份当前规则
    cp "${INSTALL_DIR}/rules.yaml" "${INSTALL_DIR}/rules.yaml.bak.$(date +%Y%m%d_%H%M%S)"
    
    # 使用 nano 编辑
    if command -v nano &> /dev/null; then
        nano "${INSTALL_DIR}/rules.yaml"
    elif command -v vim &> /dev/null; then
        vim "${INSTALL_DIR}/rules.yaml"
    elif command -v vi &> /dev/null; then
        vi "${INSTALL_DIR}/rules.yaml"
    else
        print_error "未找到文本编辑器"
        sleep 2
        return
    fi
    
    echo ""
    read -p "是否重启服务以应用更改? [Y/n]: " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Nn]$ ]]; then
        systemctl restart opengfw.service
        print_success "服务已重启"
    fi
    
    echo ""
    read -p "按回车键返回菜单..."
}

# 启动/停止/重启服务
manage_service() {
    print_header "服务管理"
    echo ""
    
    echo "请选择操作："
    echo "  1) 启动服务"
    echo "  2) 停止服务"
    echo "  3) 重启服务"
    echo "  4) 启用开机自启"
    echo "  5) 禁用开机自启"
    echo "  0) 返回"
    echo ""
    
    read -p "请选择 [0-5]: " choice
    
    case $choice in
        1)
            systemctl start opengfw.service
            print_success "服务已启动"
            ;;
        2)
            systemctl stop opengfw.service
            print_success "服务已停止"
            ;;
        3)
            systemctl restart opengfw.service
            print_success "服务已重启"
            ;;
        4)
            systemctl enable opengfw.service
            print_success "已启用开机自启"
            ;;
        5)
            systemctl disable opengfw.service
            print_success "已禁用开机自启"
            ;;
        0)
            return
            ;;
        *)
            print_error "无效选择"
            ;;
    esac
    
    echo ""
    read -p "按回车键返回菜单..."
}

# 更新 GeoIP 数据库
update_geo_databases() {
    print_header "更新 GeoIP/GeoSite 数据库"
    echo ""
    
    cd "${INSTALL_DIR}"
    
    print_info "正在下载最新 GeoIP 数据库..."
    if wget -O geoip.dat.new "https://github.com/Loyalsoldier/v2ray-rules-dat/releases/latest/download/geoip.dat" 2>&1; then
        mv geoip.dat.new geoip.dat
        print_success "GeoIP 数据库更新成功"
    else
        print_error "GeoIP 数据库更新失败"
    fi
    
    echo ""
    print_info "正在下载最新 GeoSite 数据库..."
    if wget -O geosite.dat.new "https://github.com/Loyalsoldier/v2ray-rules-dat/releases/latest/download/geosite.dat" 2>&1; then
        mv geosite.dat.new geosite.dat
        print_success "GeoSite 数据库更新成功"
    else
        print_error "GeoSite 数据库更新失败"
    fi
    
    echo ""
    read -p "是否重启服务以应用更新? [Y/n]: " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Nn]$ ]]; then
        systemctl restart opengfw.service
        print_success "服务已重启"
    fi
    
    echo ""
    read -p "按回车键返回菜单..."
}

# 系统性能监控
show_performance() {
    print_header "系统性能监控"
    echo ""
    
    # CPU 使用率
    print_info "OpenGFW 进程 CPU 使用率:"
    ps aux | grep -v grep | grep OpenGFW | awk '{print "  进程 PID: "$2", CPU: "$3"%, 内存: "$4"%"}'
    
    echo ""
    
    # 内存使用
    print_info "内存使用情况:"
    free -h | grep -v "Swap"
    
    echo ""
    
    # 网络流量
    print_info "网络接口流量（10秒采样）:"
    if command -v vnstat &> /dev/null; then
        vnstat -tr 10
    else
        print_warning "未安装 vnstat，使用 ifconfig 代替"
        ifconfig | grep -A 7 "^[a-z]" | grep -E "RX|TX"
    fi
    
    echo ""
    read -p "按回车键返回菜单..."
}

# 卸载 OpenGFW
uninstall_opengfw() {
    print_header "卸载 OpenGFW"
    echo ""
    
    print_warning "此操作将完全删除 OpenGFW 及其所有配置"
    read -p "确定要卸载吗? [y/N]: " -n 1 -r
    echo
    
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        print_info "已取消卸载"
        sleep 1
        return
    fi
    
    if [ -f "${INSTALL_DIR}/uninstall.sh" ]; then
        bash "${INSTALL_DIR}/uninstall.sh"
    else
        print_info "正在手动卸载..."
        systemctl stop opengfw.service 2>/dev/null || true
        systemctl disable opengfw.service 2>/dev/null || true
        rm -f /etc/systemd/system/opengfw.service
        systemctl daemon-reload
        
        read -p "是否删除配置目录 ${INSTALL_DIR}? [y/N]: " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            rm -rf "${INSTALL_DIR}"
            print_success "卸载完成"
        else
            print_info "保留配置文件"
        fi
    fi
    
    echo ""
    read -p "按回车键退出..."
    exit 0
}

# 主菜单
show_menu() {
    clear
    echo -e "${CYAN}"
    cat << "EOF"
╔═══════════════════════════════════════════════╗
║         OpenGFW 管理控制台                    ║
║      深度包检测 - LXD 容器流量拦截            ║
╚═══════════════════════════════════════════════╝
EOF
    echo -e "${NC}"
    
    # 显示当前状态
    if check_service_status; then
        echo -e "${GREEN}● 服务状态: 运行中${NC}"
    else
        echo -e "${RED}● 服务状态: 已停止${NC}"
    fi
    
    # 显示当前规则
    if [ -f "${INSTALL_DIR}/rules.yaml" ]; then
        local rule_count=$(grep -c "^- name:" "${INSTALL_DIR}/rules.yaml" || echo "0")
        echo -e "${BLUE}● 当前规则数: ${rule_count}${NC}"
    fi
    
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""
    echo "  1) 查看服务状态"
    echo "  2) 查看实时日志（拦截记录）"
    echo "  3) 查看拦截统计"
    echo "  4) 切换规则文件"
    echo "  5) 编辑规则文件"
    echo "  6) 服务管理（启动/停止/重启）"
    echo "  7) 更新 GeoIP 数据库"
    echo "  8) 系统性能监控"
    echo "  9) 卸载 OpenGFW"
    echo "  0) 退出"
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""
}

# 主循环
main() {
    while true; do
        show_menu
        read -p "请选择 [0-9]: " choice
        
        case $choice in
            1) show_status ;;
            2) view_realtime_logs ;;
            3) view_block_statistics ;;
            4) switch_rules ;;
            5) edit_rules ;;
            6) manage_service ;;
            7) update_geo_databases ;;
            8) show_performance ;;
            9) uninstall_opengfw ;;
            0) 
                clear
                print_success "感谢使用 OpenGFW 管理控制台"
                exit 0
                ;;
            *)
                print_error "无效选择"
                sleep 1
                ;;
        esac
    done
}

# 运行主程序
main

