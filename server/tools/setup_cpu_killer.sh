#!/bin/bash
# CPU监控杀手 - systemd 服务安装脚本

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_NAME="lxd-cpu-killer"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"

echo "=========================================="
echo "  安装 LXD CPU 监控杀手服务"
echo "=========================================="

# 检查是否为root
if [ "$EUID" -ne 0 ]; then 
    echo "❌ 请使用 root 权限运行此脚本"
    exit 1
fi

# 检查Python脚本是否存在
PYTHON_SCRIPT="${SCRIPT_DIR}/cpu_monitor_killer.py"
if [ ! -f "$PYTHON_SCRIPT" ]; then
    echo "❌ 找不到 cpu_monitor_killer.py"
    exit 1
fi

# 设置可执行权限
chmod +x "$PYTHON_SCRIPT"

# 交互式配置
echo ""
echo "请配置监控参数 (直接回车使用默认值):"
echo ""

read -p "CPU阈值 (0-100, 默认90): " CPU_THRESHOLD
CPU_THRESHOLD=${CPU_THRESHOLD:-90}

read -p "持续时间/秒 (默认180): " DURATION
DURATION=${DURATION:-180}

read -p "监控间隔/秒 (默认5): " INTERVAL
INTERVAL=${INTERVAL:-5}

read -p "每次杀死进程数 (默认1): " KILL_TOP
KILL_TOP=${KILL_TOP:-1}

read -p "冷却期/秒 (默认300): " COOLDOWN
COOLDOWN=${COOLDOWN:-300}

read -p "最大杀死次数 (默认10): " MAX_KILLS
MAX_KILLS=${MAX_KILLS:-10}

# 创建systemd服务文件
cat > "$SERVICE_FILE" <<EOF
[Unit]
Description=LXD Container CPU Monitor and Process Killer
After=network.target lxd.service
Wants=lxd.service

[Service]
Type=simple
User=root
WorkingDirectory=${SCRIPT_DIR}
ExecStart=/usr/bin/python3 ${PYTHON_SCRIPT} \\
    --threshold ${CPU_THRESHOLD} \\
    --duration ${DURATION} \\
    --interval ${INTERVAL} \\
    --kill-top ${KILL_TOP} \\
    --cooldown ${COOLDOWN} \\
    --max-kills ${MAX_KILLS}

# 自动重启配置
Restart=always
RestartSec=10

# 日志配置
StandardOutput=journal
StandardError=journal
SyslogIdentifier=${SERVICE_NAME}

# 资源限制
MemoryMax=256M
CPUQuota=20%

[Install]
WantedBy=multi-user.target
EOF

echo ""
echo "✓ 服务文件已创建: $SERVICE_FILE"

# 重载systemd
systemctl daemon-reload
echo "✓ systemd 已重载"

# 询问是否启动服务
echo ""
read -p "是否立即启动服务? (y/n, 默认y): " START_NOW
START_NOW=${START_NOW:-y}

if [[ "$START_NOW" =~ ^[Yy]$ ]]; then
    systemctl enable ${SERVICE_NAME}.service
    systemctl start ${SERVICE_NAME}.service
    echo "✓ 服务已启动并设置为开机自启"
else
    echo "⏭️  服务已创建但未启动"
    echo "   使用以下命令启动: systemctl start ${SERVICE_NAME}.service"
fi

echo ""
echo "=========================================="
echo "  安装完成！"
echo "=========================================="
echo ""
echo "常用命令:"
echo "  查看状态:   systemctl status ${SERVICE_NAME}"
echo "  查看日志:   journalctl -u ${SERVICE_NAME} -f"
echo "  停止服务:   systemctl stop ${SERVICE_NAME}"
echo "  启动服务:   systemctl start ${SERVICE_NAME}"
echo "  重启服务:   systemctl restart ${SERVICE_NAME}"
echo "  禁用自启:   systemctl disable ${SERVICE_NAME}"
echo ""
echo "配置文件:   $SERVICE_FILE"
echo ""
