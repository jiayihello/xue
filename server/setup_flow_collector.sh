#!/bin/bash
# 部署流量收集器 systemd 服务

set -e

COLOR_GREEN="\033[0;32m"
COLOR_YELLOW="\033[1;33m"
COLOR_RED="\033[0;31m"
COLOR_NC="\033[0m"

log_info() { echo -e "${COLOR_GREEN}[INFO]${COLOR_NC} $1"; }
log_warn() { echo -e "${COLOR_YELLOW}[WARN]${COLOR_NC} $1"; }
log_error() { echo -e "${COLOR_RED}[ERROR]${COLOR_NC} $1"; }

# 检查 root 权限
if [ "$EUID" -ne 0 ]; then
    log_error "请使用 root 权限运行此脚本"
    echo "sudo bash setup_flow_collector.sh"
    exit 1
fi

# 获取脚本所在目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

log_info "========================================"
log_info "部署流量收集器"
log_info "========================================"
echo ""

# 检查必要文件
log_info "检查必要文件..."
for file in "iptables_manager.py" "flow_manager_v2.py" "flow_collector.py"; do
    if [ ! -f "$file" ]; then
        log_error "缺少文件: $file"
        exit 1
    fi
    log_info "  ✓ $file"
done

# 创建 systemd service 文件
log_info ""
log_info "[1/3] 创建 systemd service 文件..."

cat > /etc/systemd/system/lxd-flow-collector.service <<EOF
[Unit]
Description=LXD Flow Collector
Documentation=file://$SCRIPT_DIR/iptables流量监控实施指南.md
After=network.target snap.lxd.daemon.service lxd.service

[Service]
Type=oneshot
WorkingDirectory=$SCRIPT_DIR
ExecStart=/usr/bin/python3 $SCRIPT_DIR/flow_collector.py
StandardOutput=journal
StandardError=journal
SyslogIdentifier=lxd-flow-collector

[Install]
WantedBy=multi-user.target
EOF

log_info "  ✓ /etc/systemd/system/lxd-flow-collector.service"

# 创建 systemd timer 文件（每分钟运行）
log_info ""
log_info "[2/3] 创建 systemd timer 文件..."

cat > /etc/systemd/system/lxd-flow-collector.timer <<EOF
[Unit]
Description=LXD Flow Collector Timer
Documentation=file://$SCRIPT_DIR/iptables流量监控实施指南.md

[Timer]
# 每分钟运行一次
OnBootSec=1min
OnUnitActiveSec=1min
AccuracySec=1s

[Install]
WantedBy=timers.target
EOF

log_info "  ✓ /etc/systemd/system/lxd-flow-collector.timer"

# 重新加载 systemd 并启动服务
log_info ""
log_info "[3/3] 启动服务..."

systemctl daemon-reload

# 启用并启动 timer
systemctl enable lxd-flow-collector.timer
systemctl start lxd-flow-collector.timer

log_info "  ✓ lxd-flow-collector.timer 已启动"

# 手动运行一次收集器（测试）
log_info ""
log_info "运行一次流量收集（测试）..."
if python3 flow_collector.py; then
    log_info "  ✓ 流量收集测试成功"
else
    log_warn "  ⚠ 流量收集测试失败，请检查日志"
fi

echo ""
log_info "========================================"
log_info "部署完成！"
log_info "========================================"
echo ""

log_info "服务状态:"
systemctl status lxd-flow-collector.timer --no-pager || true

echo ""
log_info "常用命令:"
echo "  查看 timer 状态:  systemctl status lxd-flow-collector.timer"
echo "  查看运行日志:     journalctl -u lxd-flow-collector.service -f"
echo "  手动运行一次:     python3 $SCRIPT_DIR/flow_collector.py"
echo "  查看收集器状态:   python3 $SCRIPT_DIR/flow_collector.py --status"
echo "  停止收集器:       systemctl stop lxd-flow-collector.timer"
echo "  重启收集器:       systemctl restart lxd-flow-collector.timer"
echo ""

