#!/bin/bash
# =============================================================================
# LXD 容器 CPU 保护 - 一键部署脚本
# 
# 功能：自动部署双重保护方案
#   - 第一层：智能进程杀手（轻度干预，无感知）
#   - 第二层：容器自动重启（重度干预，彻底清理）
# 
# 使用方法：
#   sudo bash deploy_cpu_protection.sh
#   sudo bash deploy_cpu_protection.sh --quick    # 快速模式（使用默认配置）
#   sudo bash deploy_cpu_protection.sh --uninstall  # 卸载
# 
# =============================================================================

set -e  # 遇到错误立即退出

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 日志函数
log_info() {
    echo -e "${GREEN}✓${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}⚠${NC} $1"
}

log_error() {
    echo -e "${RED}✗${NC} $1"
}

log_step() {
    echo -e "${BLUE}▶${NC} $1"
}

# 检查是否为root
check_root() {
    if [ "$EUID" -ne 0 ]; then 
        log_error "请使用 root 权限运行此脚本"
        echo "使用方法: sudo bash $0"
        exit 1
    fi
}

# 检测脚本目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVER_DIR="$(dirname "$SCRIPT_DIR")"

# 检查文件是否存在
check_files() {
    log_step "检查必要文件..."
    
    local missing=0
    
    if [ ! -f "$SCRIPT_DIR/cpu_monitor_killer.py" ]; then
        log_error "缺少文件: cpu_monitor_killer.py"
        missing=1
    fi
    
    if [ ! -f "$SCRIPT_DIR/top_containers.py" ]; then
        log_error "缺少文件: top_containers.py"
        missing=1
    fi
    
    if [ $missing -eq 1 ]; then
        log_error "请确保所有文件都在 $SCRIPT_DIR 目录下"
        exit 1
    fi
    
    log_info "所有必要文件检查完成"
}

# 检查Python环境
check_python() {
    log_step "检查 Python 环境..."
    
    # 检查Python版本
    if ! command -v python3 &> /dev/null; then
        log_error "未找到 python3，请先安装"
        exit 1
    fi
    
    local python_version=$(python3 --version 2>&1 | awk '{print $2}')
    log_info "Python 版本: $python_version"
    
    # 检查pylxd库
    if ! python3 -c "import pylxd" 2>/dev/null; then
        log_warn "pylxd 库未安装，正在安装..."
        pip3 install pylxd
        log_info "pylxd 已安装"
    else
        log_info "pylxd 库已安装"
    fi
}

# 检查LXD服务
check_lxd() {
    log_step "检查 LXD 服务..."
    
    if ! command -v lxc &> /dev/null; then
        log_error "未找到 LXD，请先安装 LXD"
        exit 1
    fi
    
    if ! systemctl is-active --quiet lxd.service && ! systemctl is-active --quiet snap.lxd.daemon.service; then
        log_error "LXD 服务未运行"
        exit 1
    fi
    
    log_info "LXD 服务运行正常"
}

# 测试脚本可用性
test_scripts() {
    log_step "测试脚本可用性..."
    
    # 测试 cpu_monitor_killer.py
    log_info "测试 cpu_monitor_killer.py..."
    if ! python3 "$SCRIPT_DIR/cpu_monitor_killer.py" --help > /dev/null 2>&1; then
        log_error "cpu_monitor_killer.py 脚本测试失败"
        exit 1
    fi
    log_info "cpu_monitor_killer.py 测试通过"
    
    # 测试 top_containers.py
    log_info "测试 top_containers.py..."
    if ! python3 "$SCRIPT_DIR/top_containers.py" --help > /dev/null 2>&1; then
        log_error "top_containers.py 脚本测试失败"
        exit 1
    fi
    log_info "top_containers.py 测试通过"
}

# 交互式配置
interactive_config() {
    echo ""
    echo "=========================================="
    echo "  配置第一层：智能进程杀手"
    echo "=========================================="
    echo ""
    
    read -p "CPU阈值/% (默认60，推荐60-90): " LAYER1_THRESHOLD
    LAYER1_THRESHOLD=${LAYER1_THRESHOLD:-60}
    
    read -p "持续时间/秒 (默认120，推荐60-180): " LAYER1_DURATION
    LAYER1_DURATION=${LAYER1_DURATION:-120}
    
    read -p "监控间隔/秒 (默认5，推荐3-10): " LAYER1_INTERVAL
    LAYER1_INTERVAL=${LAYER1_INTERVAL:-5}
    
    read -p "每次杀死进程数 (默认1，推荐1-3): " LAYER1_KILL_TOP
    LAYER1_KILL_TOP=${LAYER1_KILL_TOP:-1}
    
    read -p "冷却期/秒 (默认180，推荐120-300): " LAYER1_COOLDOWN
    LAYER1_COOLDOWN=${LAYER1_COOLDOWN:-180}
    
    read -p "最大杀死次数 (默认10): " LAYER1_MAX_KILLS
    LAYER1_MAX_KILLS=${LAYER1_MAX_KILLS:-10}
    
    echo ""
    echo "=========================================="
    echo "  配置第二层：容器自动重启"
    echo "=========================================="
    echo ""
    
    read -p "CPU阈值/% (默认85，推荐80-95): " LAYER2_THRESHOLD
    LAYER2_THRESHOLD=${LAYER2_THRESHOLD:-85}
    
    read -p "持续时间/秒 (默认300，推荐240-600): " LAYER2_DURATION
    LAYER2_DURATION=${LAYER2_DURATION:-300}
    
    read -p "冷却期/秒 (默认600，推荐300-900): " LAYER2_COOLDOWN
    LAYER2_COOLDOWN=${LAYER2_COOLDOWN:-600}
    
    read -p "最大重启次数 (默认3): " LAYER2_MAX_RESTARTS
    LAYER2_MAX_RESTARTS=${LAYER2_MAX_RESTARTS:-3}
}

# 快速模式配置（使用推荐值）
quick_config() {
    log_info "使用快速配置（激进模式）..."
    
    # 第一层配置（激进）
    LAYER1_THRESHOLD=60
    LAYER1_DURATION=120
    LAYER1_INTERVAL=5
    LAYER1_KILL_TOP=1
    LAYER1_COOLDOWN=180
    LAYER1_MAX_KILLS=10
    
    # 第二层配置（激进，达到3次后自动关机）
    LAYER2_THRESHOLD=85
    LAYER2_DURATION=300
    LAYER2_COOLDOWN=600
    LAYER2_MAX_RESTARTS=3
}

# 显示配置摘要
show_config() {
    echo ""
    echo "=========================================="
    echo "  配置摘要"
    echo "=========================================="
    echo ""
    echo "【第一层：智能进程杀手】"
    echo "  CPU阈值: ${LAYER1_THRESHOLD}%"
    echo "  持续时间: ${LAYER1_DURATION}秒"
    echo "  监控间隔: ${LAYER1_INTERVAL}秒"
    echo "  杀死进程数: ${LAYER1_KILL_TOP}个"
    echo "  冷却期: ${LAYER1_COOLDOWN}秒"
    echo "  最大杀死次数: ${LAYER1_MAX_KILLS}次"
    echo ""
    echo "【第二层：容器自动重启】"
    echo "  CPU阈值: ${LAYER2_THRESHOLD}%"
    echo "  持续时间: ${LAYER2_DURATION}秒"
    echo "  冷却期: ${LAYER2_COOLDOWN}秒"
    echo "  最大重启次数: ${LAYER2_MAX_RESTARTS}次"
    echo "  ⚠️  达到${LAYER2_MAX_RESTARTS}次后自动关机容器"
    echo "  ℹ️  用户手动启动后重新计数，再次达到则再次关机"
    echo ""
}

# 部署第一层服务
deploy_layer1() {
    log_step "部署第一层：智能进程杀手..."
    
    # 设置可执行权限
    chmod +x "$SCRIPT_DIR/cpu_monitor_killer.py"
    
    # 创建systemd服务
    cat > /etc/systemd/system/lxd-cpu-killer.service <<EOF
[Unit]
Description=LXD Container CPU Monitor and Process Killer
After=network.target lxd.service snap.lxd.daemon.service
Wants=lxd.service

[Service]
Type=simple
User=root
WorkingDirectory=$SCRIPT_DIR
ExecStart=/usr/bin/python3 $SCRIPT_DIR/cpu_monitor_killer.py \\
    --threshold ${LAYER1_THRESHOLD} \\
    --duration ${LAYER1_DURATION} \\
    --interval ${LAYER1_INTERVAL} \\
    --kill-top ${LAYER1_KILL_TOP} \\
    --cooldown ${LAYER1_COOLDOWN} \\
    --max-kills ${LAYER1_MAX_KILLS}

# 自动重启配置
Restart=always
RestartSec=10

# 日志配置
StandardOutput=journal
StandardError=journal
SyslogIdentifier=lxd-cpu-killer

# 资源限制
MemoryMax=256M
CPUQuota=20%

[Install]
WantedBy=multi-user.target
EOF
    
    log_info "第一层服务文件已创建"
}

# 部署第二层服务
deploy_layer2() {
    log_step "部署第二层：容器自动重启..."
    
    # 设置可执行权限
    chmod +x "$SCRIPT_DIR/top_containers.py"
    
    # 创建systemd服务
    cat > /etc/systemd/system/lxd-auto-restart.service <<EOF
[Unit]
Description=LXD Container Auto Restart on High CPU
After=network.target lxd.service snap.lxd.daemon.service
Wants=lxd.service

[Service]
Type=simple
User=root
WorkingDirectory=$SCRIPT_DIR
ExecStart=/usr/bin/python3 $SCRIPT_DIR/top_containers.py -w --auto-restart \\
    --cpu-threshold ${LAYER2_THRESHOLD} \\
    --cpu-duration ${LAYER2_DURATION} \\
    --cooldown ${LAYER2_COOLDOWN} \\
    --max-restarts ${LAYER2_MAX_RESTARTS}

# 自动重启配置
Restart=always
RestartSec=10

# 日志配置
StandardOutput=journal
StandardError=journal
SyslogIdentifier=lxd-auto-restart

# 资源限制
MemoryMax=256M
CPUQuota=20%

[Install]
WantedBy=multi-user.target
EOF
    
    log_info "第二层服务文件已创建"
}

# 启动服务
start_services() {
    log_step "启动服务..."
    
    # 重载systemd
    systemctl daemon-reload
    log_info "systemd 已重载"
    
    # 启用并启动第一层
    systemctl enable lxd-cpu-killer.service
    systemctl start lxd-cpu-killer.service
    log_info "第一层服务已启动"
    
    # 启用并启动第二层
    systemctl enable lxd-auto-restart.service
    systemctl start lxd-auto-restart.service
    log_info "第二层服务已启动"
    
    # 等待服务启动
    sleep 2
    
    # 检查服务状态
    if systemctl is-active --quiet lxd-cpu-killer.service; then
        log_info "第一层服务运行正常"
    else
        log_error "第一层服务启动失败"
        systemctl status lxd-cpu-killer.service --no-pager
        exit 1
    fi
    
    if systemctl is-active --quiet lxd-auto-restart.service; then
        log_info "第二层服务运行正常"
    else
        log_error "第二层服务启动失败"
        systemctl status lxd-auto-restart.service --no-pager
        exit 1
    fi
}

# 显示使用说明
show_usage() {
    echo ""
    echo "=========================================="
    echo "  部署完成！"
    echo "=========================================="
    echo ""
    echo "【服务状态】"
    echo "  第一层: systemctl status lxd-cpu-killer"
    echo "  第二层: systemctl status lxd-auto-restart"
    echo ""
    echo "【查看日志】"
    echo "  第一层: journalctl -u lxd-cpu-killer -f"
    echo "  第二层: journalctl -u lxd-auto-restart -f"
    echo "  合并查看: journalctl -u lxd-cpu-killer -u lxd-auto-restart -f"
    echo ""
    echo "【服务管理】"
    echo "  停止: systemctl stop lxd-cpu-killer lxd-auto-restart"
    echo "  启动: systemctl start lxd-cpu-killer lxd-auto-restart"
    echo "  重启: systemctl restart lxd-cpu-killer lxd-auto-restart"
    echo "  禁用: systemctl disable lxd-cpu-killer lxd-auto-restart"
    echo ""
    echo "【测试运行】"
    echo "  测试模式: python3 $SCRIPT_DIR/cpu_monitor_killer.py --dry-run"
    echo "  查看TOP: python3 $SCRIPT_DIR/top_containers.py"
    echo ""
    echo "【配置文件】"
    echo "  第一层: /etc/systemd/system/lxd-cpu-killer.service"
    echo "  第二层: /etc/systemd/system/lxd-auto-restart.service"
    echo ""
    echo "【快速参考】"
    echo "  文档: $SERVER_DIR/docs/guides/CPU监控自动杀进程-使用指南.md"
    echo "  快速参考: $SCRIPT_DIR/CPU_KILLER_快速参考.txt"
    echo ""
}

# 卸载服务
uninstall_services() {
    log_step "卸载 CPU 保护服务..."
    
    # 停止服务
    systemctl stop lxd-cpu-killer.service 2>/dev/null || true
    systemctl stop lxd-auto-restart.service 2>/dev/null || true
    
    # 禁用服务
    systemctl disable lxd-cpu-killer.service 2>/dev/null || true
    systemctl disable lxd-auto-restart.service 2>/dev/null || true
    
    # 删除服务文件
    rm -f /etc/systemd/system/lxd-cpu-killer.service
    rm -f /etc/systemd/system/lxd-auto-restart.service
    
    # 重载systemd
    systemctl daemon-reload
    
    log_info "服务已卸载"
    echo ""
}

# 主函数
main() {
    echo ""
    echo "╔══════════════════════════════════════════════════════════════╗"
    echo "║      LXD 容器 CPU 保护 - 一键部署脚本                       ║"
    echo "║                                                              ║"
    echo "║  双重保护方案：                                              ║"
    echo "║    第一层：智能进程杀手（轻度干预）                         ║"
    echo "║    第二层：容器自动重启（重度干预）                         ║"
    echo "╚══════════════════════════════════════════════════════════════╝"
    echo ""
    
    # 检查参数
    if [ "$1" == "--uninstall" ]; then
        check_root
        uninstall_services
        log_info "卸载完成"
        exit 0
    fi
    
    # 检查环境
    check_root
    check_files
    check_python
    check_lxd
    test_scripts
    
    # 配置
    if [ "$1" == "--quick" ]; then
        quick_config
    else
        interactive_config
    fi
    
    # 显示配置
    show_config
    
    # 确认
    echo ""
    read -p "确认部署？(y/n, 默认y): " CONFIRM
    CONFIRM=${CONFIRM:-y}
    
    if [[ ! "$CONFIRM" =~ ^[Yy]$ ]]; then
        log_warn "部署已取消"
        exit 0
    fi
    
    # 部署
    deploy_layer1
    deploy_layer2
    start_services
    
    # 显示使用说明
    show_usage
    
    log_info "🎉 部署完成！CPU 保护系统已启动运行"
}

# 运行主函数
main "$@"
