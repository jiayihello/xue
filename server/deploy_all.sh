#!/bin/bash

# ZJMF-LXD-Server 一键部署脚本
# 自动化完整部署流程

set -e

# 颜色定义
COLOR_RED='\033[0;31m'
COLOR_GREEN='\033[0;32m'
COLOR_YELLOW='\033[1;33m'
COLOR_BLUE='\033[0;34m'
COLOR_CYAN='\033[0;36m'
COLOR_NC='\033[0m' # No Color

# 日志函数
log_info() {
    echo -e "${COLOR_CYAN}[INFO]${COLOR_NC} $1"
}

log_ok() {
    echo -e "${COLOR_GREEN}[OK]${COLOR_NC} $1"
}

log_warn() {
    echo -e "${COLOR_YELLOW}[WARN]${COLOR_NC} $1"
}

log_error() {
    echo -e "${COLOR_RED}[ERROR]${COLOR_NC} $1"
}

log_step() {
    echo -e "\n${COLOR_BLUE}========================================${COLOR_NC}"
    echo -e "${COLOR_BLUE}  $1${COLOR_NC}"
    echo -e "${COLOR_BLUE}========================================${COLOR_NC}"
}

# 询问 yes/no 的函数
ask_yes_no() {
    local prompt="$1"
    local default="${2:-n}"  # 默认值为 n
    
    if [[ "$default" == "y" ]]; then
        read -p "$(echo -e "${COLOR_YELLOW}${prompt} [Y/n]:${COLOR_NC} ")" answer
        answer=${answer:-y}
    else
        read -p "$(echo -e "${COLOR_YELLOW}${prompt} [y/N]:${COLOR_NC} ")" answer
        answer=${answer:-n}
    fi
    
    if [[ "${answer,,}" == "y" || "${answer,,}" == "yes" ]]; then
        return 0
    else
        return 1
    fi
}

# 检查root权限
check_root() {
    if [ "$EUID" -ne 0 ]; then
        log_error "请使用root权限运行此脚本"
        echo "sudo bash deploy_all.sh"
        exit 1
    fi
}

# 获取脚本所在目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# 主脚本开始
clear
echo -e "${COLOR_GREEN}=========================================="
echo -e "  ZJMF-LXD-Server 一键部署脚本"
echo -e "==========================================${COLOR_NC}"
echo ""
log_info "脚本目录: $SCRIPT_DIR"
echo ""

# 检查root权限
check_root

# ==========================================
# 步骤 1: 安装 Python 依赖
# ==========================================
log_step "步骤 1/6: 安装 Python 依赖"

if [ -f "requirements.txt" ]; then
    log_info "安装 requirements.txt 中的依赖..."
    if pip3 install -r requirements.txt; then
        log_ok "Python 依赖安装完成"
    else
        log_warn "部分依赖可能安装失败，但继续执行..."
    fi
else
    log_warn "未找到 requirements.txt 文件，跳过"
fi

# ==========================================
# 步骤 2: 网络配置
# ==========================================
log_step "步骤 2/6: 网络配置"

# 检测可用的网卡接口
echo ""
log_info "检测可用的网卡接口..."
# 使用 set +e 临时关闭错误退出，避免 grep 无匹配时导致脚本退出
set +e
AVAILABLE_INTERFACES=$(ip -o link show 2>/dev/null | awk -F': ' '{print $2}' | grep -v '^lo$' | grep -v '^lxdbr' || true)
set -e

if [ -n "$AVAILABLE_INTERFACES" ]; then
    log_info "检测到以下网卡接口:"
    echo "$AVAILABLE_INTERFACES" | head -10 | nl -w2 -s') '
    echo ""
else
    log_warn "未自动检测到可用网卡，请手动输入"
    echo ""
fi

# 输入主网卡接口名
log_info "请输入主网卡接口名（常见: eth0, ens3, ens18, enp0s3）"
while true; do
    read -p "$(echo -e "${COLOR_YELLOW}主网卡接口名:${COLOR_NC} ")" MAIN_INTERFACE
    if [ -n "$MAIN_INTERFACE" ]; then
        # 验证网卡是否存在
        if ip link show "$MAIN_INTERFACE" >/dev/null 2>&1; then
            log_ok "主网卡接口: $MAIN_INTERFACE ✓ (已验证存在)"
            break
        else
            log_warn "警告: 网卡 '$MAIN_INTERFACE' 不存在于系统中"
            read -p "$(echo -e "${COLOR_YELLOW}是否仍然使用此接口名? [y/N]:${COLOR_NC} ")" confirm
            if [[ "$confirm" =~ ^[yY]$ ]]; then
                log_ok "主网卡接口: $MAIN_INTERFACE (未验证)"
                break
            fi
        fi
    else
        log_error "网卡接口名不能为空，请重新输入"
    fi
done

# 输入 IPv4 地址
echo ""
log_info "检测服务器 IPv4 地址..."
# 尝试自动检测 IPv4 地址
set +e
DETECTED_IPV4=""
if [ -n "$MAIN_INTERFACE" ]; then
    # 优先从指定网卡检测
    DETECTED_IPV4=$(ip -4 addr show "$MAIN_INTERFACE" 2>/dev/null | grep -oP '(?<=inet\s)\d+(\.\d+){3}' | head -1 || true)
fi
if [ -z "$DETECTED_IPV4" ]; then
    # 从所有网卡检测（排除回环和Docker）
    DETECTED_IPV4=$(ip -4 addr show 2>/dev/null | grep -oP '(?<=inet\s)\d+(\.\d+){3}' | grep -v '^127\.' | grep -v '^172\.1[6-9]\.' | grep -v '^172\.2[0-9]\.' | grep -v '^172\.3[0-1]\.' | head -1 || true)
fi
set -e

if [ -n "$DETECTED_IPV4" ]; then
    log_info "检测到 IPv4 地址: $DETECTED_IPV4"
    echo ""
fi

while true; do
    if [ -n "$DETECTED_IPV4" ]; then
        read -p "$(echo -e "${COLOR_YELLOW}请输入服务器的 IPv4 地址 [默认: $DETECTED_IPV4]:${COLOR_NC} ")" IPV4_ADDRESS
        IPV4_ADDRESS=${IPV4_ADDRESS:-$DETECTED_IPV4}
    else
        read -p "$(echo -e "${COLOR_YELLOW}请输入服务器的 IPv4 地址:${COLOR_NC} ")" IPV4_ADDRESS
    fi
    
    if [[ "$IPV4_ADDRESS" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
        log_ok "IPv4 地址: $IPV4_ADDRESS"
        break
    else
        log_error "无效的 IPv4 地址格式，请重新输入"
    fi
done

# 输入 IPv6 网卡接口名（可选）
echo ""
log_info "输入 IPv6 网卡接口名（如果与主网卡不同）"
log_info "如果 IPv6 与 IPv4 使用相同网卡，请直接按 Enter 跳过"
read -p "$(echo -e "${COLOR_YELLOW}IPv6 网卡接口名 [默认: $MAIN_INTERFACE]:${COLOR_NC} ")" IPV6_INTERFACE
IPV6_INTERFACE=${IPV6_INTERFACE:-$MAIN_INTERFACE}

if [ "$IPV6_INTERFACE" != "$MAIN_INTERFACE" ]; then
    # 验证 IPv6 网卡是否存在
    if ip link show "$IPV6_INTERFACE" >/dev/null 2>&1; then
        log_ok "IPv6 网卡接口: $IPV6_INTERFACE ✓ (已验证存在)"
    else
        log_warn "警告: 网卡 '$IPV6_INTERFACE' 不存在于系统中，将使用主网卡"
        IPV6_INTERFACE=$MAIN_INTERFACE
    fi
else
    log_ok "IPv6 网卡接口: $IPV6_INTERFACE (与主网卡相同)"
fi

# 选择 IPv6 模式
echo ""
log_info "选择 IPv6 模式:"
echo "  1) ROUTED  - 路由模式（分配独立IPv6地址）"
echo "  2) NAT66   - NAT66模式（IPv6地址转换）"
echo "  3) off     - 禁用IPv6"
echo ""

while true; do
    read -p "$(echo -e "${COLOR_YELLOW}请选择 IPv6 模式 [1/2/3]:${COLOR_NC} ")" ipv6_choice
    case "$ipv6_choice" in
        1)
            IPV6_MODE="ROUTED"
            echo ""
            read -p "$(echo -e "${COLOR_YELLOW}请输入 IPv6 前缀 (例如 2001:db8::/64):${COLOR_NC} ")" IPV6_PREFIX
            log_ok "IPv6 模式: $IPV6_MODE, 前缀: $IPV6_PREFIX"
            break
            ;;
        2)
            IPV6_MODE="NAT66"
            echo ""
            read -p "$(echo -e "${COLOR_YELLOW}请输入 NAT66 监听地址 (例如 fd00::1/128):${COLOR_NC} ")" NAT_LISTEN_IPV6
            log_ok "IPv6 模式: $IPV6_MODE, 监听地址: $NAT_LISTEN_IPV6"
            break
            ;;
        3)
            IPV6_MODE="off"
            IPV6_PREFIX=""
            NAT_LISTEN_IPV6=""
            log_ok "IPv6 模式: 禁用"
            break
            ;;
        *)
            log_error "无效的选择，请输入 1、2 或 3"
            ;;
    esac
done

# IPv6-Only 模式选项（仅在启用 IPv6 ROUTED 模式时可用）
IPV4_MODE="BRIDGE"  # 默认值
if [ "$IPV6_MODE" = "ROUTED" ]; then
    echo ""
    log_info "是否启用 IPv6-Only 模式？"
    log_info "启用后容器将只使用 IPv6 地址，不分配 IPv4 地址"
    echo ""
    
    if ask_yes_no "启用 IPv6-Only 模式" "n"; then
        IPV4_MODE="OFF"
        log_ok "✓ 已启用 IPv6-Only 模式 (IPV4_MODE=OFF)"
    else
        IPV4_MODE="BRIDGE"
        log_ok "✓ 使用标准模式 (IPv4+IPv6 双栈)"
    fi
fi

# 创建配置文件
log_info "生成网络配置..."
cat > network_config.env << EOF
# 网络配置文件
MAIN_INTERFACE=$MAIN_INTERFACE
IPV6_INTERFACE=$IPV6_INTERFACE
IPV4_ADDRESS=$IPV4_ADDRESS
IPV4_MODE=$IPV4_MODE
IPV6_MODE=$IPV6_MODE
IPV6_PREFIX=$IPV6_PREFIX
NAT_LISTEN_IPV6=$NAT_LISTEN_IPV6
EOF

# 执行网络配置
echo ""
log_info "执行网络配置脚本..."
if [ -f "network_setup.py" ]; then
    # 设置环境变量供 Python 脚本使用
    export MAIN_INTERFACE IPV6_INTERFACE IPV4_ADDRESS IPV4_MODE IPV6_MODE IPV6_PREFIX NAT_LISTEN_IPV6
    
    if python3 network_setup.py; then
        log_ok "网络配置完成"
    else
        log_error "网络配置失败"
        exit 1
    fi
else
    log_warn "未找到 network_setup.py，跳过网络配置"
fi

# ==========================================
# 步骤 3: 部署 iptables 流量监控系统 V2
# ==========================================
log_step "步骤 3/6: 部署 iptables 流量监控系统 V2"

if ask_yes_no "是否部署流量监控系统（iptables V2）?" "y"; then
    log_info "开始部署流量监控系统..."
    
    # 检查部署脚本是否存在
    if [ -f "deploy_iptables_flow.sh" ]; then
        # 执行流量系统部署脚本
        if bash deploy_iptables_flow.sh; then
            log_ok "流量监控系统部署完成"
            ENABLE_FLOW_MANAGEMENT=true
        else
            log_error "流量监控系统部署失败"
            if ask_yes_no "是否继续部署其他组件?" "y"; then
                log_warn "跳过流量监控系统，继续部署"
                ENABLE_FLOW_MANAGEMENT=false
            else
                exit 1
            fi
        fi
    else
        log_error "未找到 deploy_iptables_flow.sh 脚本"
        ENABLE_FLOW_MANAGEMENT=false
    fi
else
    log_info "跳过流量监控系统部署"
    ENABLE_FLOW_MANAGEMENT=false
fi

# ==========================================
# 步骤 4: 配置滥用防护
# ==========================================
log_step "步骤 4/6: 滥用防护配置"

if ask_yes_no "是否配置滥用防护（防挖矿、BT、扫描）?" "y"; then
    log_info "配置滥用防护..."
    
    if [ -f "abuse_guard.py" ]; then
        # 应用滥用防护规则（会自动设置cron）
        python3 abuse_guard.py apply
        log_ok "滥用防护配置完成（已自动添加定时任务）"
    else
        log_warn "未找到 abuse_guard.py"
    fi
else
    log_info "跳过滥用防护配置"
fi

# ==========================================
# 步骤 5: CPU保护系统
# ==========================================
log_step "步骤 5/6: CPU保护系统"

if ask_yes_no "是否部署CPU保护系统（自动杀进程+重启+关机）?" "n"; then
    log_info "开始部署CPU保护系统..."
    
    # 检查部署脚本是否存在
    if [ -f "tools/deploy_cpu_protection.sh" ]; then
        # 执行CPU保护系统部署脚本（快速模式）
        if bash tools/deploy_cpu_protection.sh --quick; then
            log_ok "CPU保护系统部署完成"
            ENABLE_CPU_PROTECTION=true
        else
            log_error "CPU保护系统部署失败"
            if ask_yes_no "是否继续部署其他组件?" "y"; then
                log_warn "跳过CPU保护系统，继续部署"
                ENABLE_CPU_PROTECTION=false
            else
                exit 1
            fi
        fi
    else
        log_error "未找到 tools/deploy_cpu_protection.sh 脚本"
        ENABLE_CPU_PROTECTION=false
    fi
else
    log_info "跳过CPU保护系统部署"
    ENABLE_CPU_PROTECTION=false
fi

# ==========================================
# 步骤 6: 创建并启用后端服务
# ==========================================
log_step "步骤 6/6: 后端 API 服务"

if ask_yes_no "是否创建并启用后端 API 服务?" "y"; then
    log_info "配置后端服务..."
    
    # 检查 app.py 和 app.ini
    if [ ! -f "app.py" ]; then
        log_error "未找到 app.py"
        exit 1
    fi
    
    # 创建配置文件（如果不存在）
    if [ ! -f "app.ini" ]; then
        if [ -f "app.ini.example" ]; then
            log_info "从 app.ini.example 创建配置文件..."
            cp app.ini.example app.ini
            
            # 生成随机 API Key
            API_KEY=$(openssl rand -hex 32)
            sed -i "s/your-secure-api-key-here/${API_KEY}/g" app.ini
            
            log_ok "配置文件已创建: app.ini"
            log_warn "⚠️  请记录您的 API Key: $API_KEY"
        else
            log_error "未找到 app.ini.example"
            exit 1
        fi
    else
        log_warn "app.ini 已存在，将更新网络配置..."
    fi
    
    # 更新 app.ini 中的网络配置（无论是新建还是已存在）
    log_info "更新 app.ini 网络配置..."
    
    # 更新 MAIN_INTERFACE
    if grep -q "^MAIN_INTERFACE\s*=" app.ini; then
        sed -i "s|^MAIN_INTERFACE\s*=.*|MAIN_INTERFACE = $MAIN_INTERFACE|g" app.ini
    else
        echo "MAIN_INTERFACE = $MAIN_INTERFACE" >> app.ini
    fi
    
    # 更新 IPV6_INTERFACE
    if [ -n "$IPV6_INTERFACE" ]; then
        if grep -q "^IPV6_INTERFACE\s*=" app.ini; then
            sed -i "s|^IPV6_INTERFACE\s*=.*|IPV6_INTERFACE = $IPV6_INTERFACE|g" app.ini
        else
            echo "IPV6_INTERFACE = $IPV6_INTERFACE" >> app.ini
        fi
    fi
    
    # 更新 NAT_LISTEN_IP
    if grep -q "^NAT_LISTEN_IP\s*=" app.ini; then
        sed -i "s|^NAT_LISTEN_IP\s*=.*|NAT_LISTEN_IP = $IPV4_ADDRESS|g" app.ini
    else
        echo "NAT_LISTEN_IP = $IPV4_ADDRESS" >> app.ini
    fi
    
    # 更新 IPV4_MODE
    if [ -n "$IPV4_MODE" ]; then
        if grep -q "^IPV4_MODE\s*=" app.ini; then
            sed -i "s|^IPV4_MODE\s*=.*|IPV4_MODE = $IPV4_MODE|g" app.ini
        else
            echo "IPV4_MODE = $IPV4_MODE" >> app.ini
        fi
    fi
    
    # 更新 IPV6_MODE
    if [ -n "$IPV6_MODE" ]; then
        if grep -q "^IPV6_MODE\s*=" app.ini; then
            sed -i "s|^IPV6_MODE\s*=.*|IPV6_MODE = $IPV6_MODE|g" app.ini
        else
            echo "IPV6_MODE = $IPV6_MODE" >> app.ini
        fi
    fi
    
    # 更新 IPV6_PREFIX（仅 ROUTED 模式）
    if [ -n "$IPV6_PREFIX" ]; then
        if grep -q "^IPV6_PREFIX\s*=" app.ini; then
            sed -i "s|^IPV6_PREFIX\s*=.*|IPV6_PREFIX = $IPV6_PREFIX|g" app.ini
        else
            echo "IPV6_PREFIX = $IPV6_PREFIX" >> app.ini
        fi
    fi
    
    # 更新 NAT_LISTEN_IPV6（仅 NAT66 模式）
    if [ -n "$NAT_LISTEN_IPV6" ]; then
        if grep -q "^NAT_LISTEN_IPV6\s*=" app.ini; then
            sed -i "s|^NAT_LISTEN_IPV6\s*=.*|NAT_LISTEN_IPV6 = $NAT_LISTEN_IPV6|g" app.ini
        else
            echo "NAT_LISTEN_IPV6 = $NAT_LISTEN_IPV6" >> app.ini
        fi
    fi
    
    log_ok "✓ app.ini 网络配置已更新"
    log_info "  MAIN_INTERFACE = $MAIN_INTERFACE"
    if [ "$IPV6_INTERFACE" != "$MAIN_INTERFACE" ]; then
        log_info "  IPV6_INTERFACE = $IPV6_INTERFACE"
    fi
    log_info "  NAT_LISTEN_IP = $IPV4_ADDRESS"
    log_info "  IPV4_MODE = $IPV4_MODE"
    if [ -n "$IPV6_MODE" ]; then
        log_info "  IPV6_MODE = $IPV6_MODE"
        if [ -n "$IPV6_PREFIX" ]; then
            log_info "  IPV6_PREFIX = $IPV6_PREFIX"
        fi
        if [ -n "$NAT_LISTEN_IPV6" ]; then
            log_info "  NAT_LISTEN_IPV6 = $NAT_LISTEN_IPV6"
        fi
    fi
    
    # 使用 setup_lxd_api_service.sh 创建服务
    if [ -f "tools/setup/setup_lxd_api_service.sh" ]; then
        log_info "创建 systemd 服务..."
        bash tools/setup/setup_lxd_api_service.sh
        log_ok "后端服务已创建并启动"
    else
        # 手动创建服务
        log_info "手动创建 systemd 服务..."
        
        cat > /etc/systemd/system/lxd-api.service << EOF
[Unit]
Description=LXD API Service
After=network.target snap.lxd.daemon.service lxd.service
Wants=snap.lxd.daemon.service lxd.service

[Service]
Type=simple
User=root
WorkingDirectory=$SCRIPT_DIR
ExecStart=/usr/bin/python3 $SCRIPT_DIR/app.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF
        
        systemctl daemon-reload
        systemctl enable lxd-api.service
        systemctl start lxd-api.service
        
        if systemctl is-active --quiet lxd-api.service; then
            log_ok "后端服务已启动"
        else
            log_error "后端服务启动失败，请检查日志: journalctl -u lxd-api.service -n 50"
        fi
    fi
else
    log_info "跳过后端服务配置"
fi

# ==========================================
# 部署完成总结
# ==========================================
echo ""
echo -e "${COLOR_GREEN}=========================================="
echo -e "  部署完成！"
echo -e "==========================================${COLOR_NC}"
echo ""

log_info "部署总结:"
echo ""

# 网络配置
echo -e "${COLOR_CYAN}网络配置:${COLOR_NC}"
echo "  主网卡接口: $MAIN_INTERFACE"
if [ "$IPV6_INTERFACE" != "$MAIN_INTERFACE" ]; then
    echo "  IPv6 网卡接口: $IPV6_INTERFACE"
fi
echo "  IPv4 地址: $IPV4_ADDRESS"
echo "  IPv4 模式: $IPV4_MODE"
echo "  IPv6 模式: $IPV6_MODE"
if [ -n "$IPV6_PREFIX" ]; then
    echo "  IPv6 前缀: $IPV6_PREFIX"
fi
if [ "$IPV4_MODE" = "OFF" ]; then
    echo "  ⚠️  IPv6-Only 模式已启用，容器不分配 IPv4 地址"
fi
echo ""

# 流量管理系统 V2
if [ "$ENABLE_FLOW_MANAGEMENT" = true ]; then
    echo -e "${COLOR_CYAN}流量监控系统 V2 (iptables):${COLOR_NC}"
    echo "  ✅ 已启用"
    
    # 检查服务状态
    if systemctl is-active --quiet lxd-event-listener.service; then
        echo "  ✅ 事件监听器: 运行中"
    else
        echo "  ⚠️  事件监听器: 未运行"
    fi
    
    # 检查定时器
    if systemctl is-active --quiet lxd-flow-collector.timer; then
        echo "  ✅ 流量收集器: 已配置 (每分钟)"
    else
        echo "  ⚠️  流量收集器: 未配置"
    fi
    
    if systemctl is-active --quiet lxd-flow-limit-enforcer.timer; then
        echo "  ✅ 流量限制执行器: 已配置 (每5分钟)"
    else
        echo "  ⚠️  流量限制执行器: 未配置"
    fi
    
    if systemctl is-active --quiet lxd-flow-reset-scheduler.timer; then
        echo "  ✅ 流量重置调度器: 已配置 (每天1AM)"
    else
        echo "  ⚠️  流量重置调度器: 未配置"
    fi
    
    # 检查数据库
    if [ -f "$SCRIPT_DIR/flow_management_v2.db" ]; then
        echo "  ✅ 数据库: flow_management_v2.db"
    else
        echo "  ⚠️  数据库文件缺失"
    fi
    
    echo ""
fi

# API 服务
echo -e "${COLOR_CYAN}API 服务:${COLOR_NC}"
if systemctl is-active --quiet lxd-api.service; then
    echo "  ✅ 后端服务: 运行中"
    
    # 获取端口
    PORT=$(grep -oP '(?<=port = )\d+' app.ini 2>/dev/null || echo "8080")
    echo "  访问地址: http://$IPV4_ADDRESS:$PORT"
    
    # 显示 API Key
    if [ -n "$API_KEY" ]; then
        echo "  API Key: $API_KEY"
    fi
else
    echo "  ⚠️  后端服务: 未运行"
fi
echo ""

# 滥用防护
if crontab -l 2>/dev/null | grep -q "abuse_guard.py apply"; then
    echo -e "${COLOR_CYAN}滥用防护:${COLOR_NC}"
    echo "  ✅ 已启用（每日更新）"
    echo ""
fi

# CPU保护系统
if [ "$ENABLE_CPU_PROTECTION" = true ]; then
    echo -e "${COLOR_CYAN}CPU保护系统:${COLOR_NC}"
    echo "  ✅ 已启用（激进模式）"
    
    # 检查服务状态
    if systemctl is-active --quiet lxd-cpu-killer.service; then
        echo "  ✅ 第一层（进程杀手）: 运行中 (CPU>60% → 杀进程)"
    else
        echo "  ⚠️  第一层（进程杀手）: 未运行"
    fi
    
    if systemctl is-active --quiet lxd-auto-restart.service; then
        echo "  ✅ 第二层（自动重启）: 运行中 (CPU>85% → 重启/关机)"
    else
        echo "  ⚠️  第二层（自动重启）: 未运行"
    fi
    
    echo "  📊 监控日志: journalctl -u lxd-cpu-killer -u lxd-auto-restart -f"
    echo ""
fi

# 常用命令
echo -e "${COLOR_CYAN}常用命令:${COLOR_NC}"
echo "  查看容器列表:       lxc list"
if [ "$ENABLE_FLOW_MANAGEMENT" = true ]; then
    echo "  查看流量使用:       python3 $SCRIPT_DIR/flow_manager_v2.py list"
    echo "  查询容器流量:       python3 $SCRIPT_DIR/flow_manager_v2.py info <容器名>"
    echo "  重置容器流量:       python3 $SCRIPT_DIR/flow_manager_v2.py reset <容器名>"
fi
echo "  查看服务状态:       systemctl status lxd-api.service"
if [ "$ENABLE_FLOW_MANAGEMENT" = true ]; then
    echo "  查看事件监听器:     systemctl status lxd-event-listener.service"
    echo "  查看定时器状态:     systemctl list-timers lxd-flow-*"
    echo "  查看流量日志:       tail -f $SCRIPT_DIR/flow_collector.log"
fi
echo "  查看服务日志:       journalctl -u lxd-api.service -f"
if [ "$ENABLE_CPU_PROTECTION" = true ]; then
    echo "  CPU保护监控:        journalctl -u lxd-cpu-killer -u lxd-auto-restart -f"
    echo "  CPU保护面板:        bash $SCRIPT_DIR/tools/monitor_protection.sh"
fi
echo ""

# 后续操作建议
echo -e "${COLOR_YELLOW}后续操作建议:${COLOR_NC}"
echo "  1. 检查所有服务状态是否正常"
echo "  2. 测试创建一个容器验证功能"
if [ "$ENABLE_FLOW_MANAGEMENT" = true ]; then
    echo "  3. 验证流量监控是否正常工作: python3 $SCRIPT_DIR/flow_manager_v2.py list"
    echo "  4. 查看 API 文档配置前端面板"
else
    echo "  3. 查看 API 文档配置前端面板"
fi
echo ""

# 提示可以运行检查脚本
echo -e "${COLOR_CYAN}自动检查部署状态:${COLOR_NC}"
if [ -f "$SCRIPT_DIR/tools/diagnostic/check_deployment.sh" ]; then
    echo "  bash $SCRIPT_DIR/tools/diagnostic/check_deployment.sh"
elif [ -f "$SCRIPT_DIR/tools/post_deployment_check.sh" ]; then
    echo "  bash $SCRIPT_DIR/tools/post_deployment_check.sh"
else
    echo "  检查脚本未找到"
fi
echo ""

log_ok "部署完成！感谢使用 ZJMF-LXD-Server"
echo ""

