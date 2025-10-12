#!/bin/bash
# 安装/更新 CPU 高占用自动重启监控的 systemd 服务
# 使用: sudo bash setup_cpu_autorestart_monitor.sh [install|remove|status]
# 默认执行 install

set -euo pipefail

# 自动检测脚本所在目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="/usr/bin/python3"
SERVICE_NAME="lxd-cpu-autorestart"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"

# 默认参数（可根据需要调整）
INTERVAL=5            # 采样/刷新间隔秒
CPU_THRESHOLD=90      # CPU 阈值百分比
CPU_DURATION=180      # 持续高于阈值触发重启（秒）
COOLDOWN=300          # 重启冷却期（秒）
MAX_RESTARTS=3        # 每容器最大自动重启次数
NAME_FILTER=""       # 可选：仅监控包含该子串的容器名
TOP_N=20              # 仅显示前 N 项（影响输出）

cmd=${1:-install}

install_service() {
  if [ ! -f "$SCRIPT_DIR/top_containers.py" ]; then
    echo "❌ 未找到 $SCRIPT_DIR/top_containers.py，请确认在正确的目录运行此脚本"
    exit 1
  fi

  # 生成 ExecStart 命令
  EXTRA_FILTER_ARG=""
  if [ -n "$NAME_FILTER" ]; then
    EXTRA_FILTER_ARG="-f $NAME_FILTER"
  fi

  cat > "$SERVICE_FILE" <<EOF
[Unit]
Description=LXD CPU Auto-Restart Monitor (top_containers)
After=network.target lxd.service
Wants=lxd.service

[Service]
Type=simple
WorkingDirectory=$SCRIPT_DIR
ExecStart=$PYTHON $SCRIPT_DIR/top_containers.py -w -i $INTERVAL -n $TOP_N $EXTRA_FILTER_ARG \
  --auto-restart --cpu-threshold $CPU_THRESHOLD --cpu-duration $CPU_DURATION \
  --cooldown $COOLDOWN --max-restarts $MAX_RESTARTS
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

# 可根据需要设置
# User=root
# Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF

  echo "✅ 已写入服务文件: $SERVICE_FILE"
  echo "▶ 自动加载并启动服务..."
  systemctl daemon-reload
  systemctl enable ${SERVICE_NAME}.service
  # 已安装或更新后直接重启服务，确保新参数生效
  systemctl restart ${SERVICE_NAME}.service
  systemctl --no-pager --lines=10 status ${SERVICE_NAME}.service || true
  echo "✅ 完成：服务已启用并启动。可用命令：systemctl status ${SERVICE_NAME}.service"
}

remove_service() {
  systemctl stop ${SERVICE_NAME}.service 2>/dev/null || true
  systemctl disable ${SERVICE_NAME}.service 2>/dev/null || true
  rm -f "$SERVICE_FILE"
  systemctl daemon-reload
  echo "✅ 已移除服务 ${SERVICE_NAME}"
}

status_service() {
  systemctl status ${SERVICE_NAME}.service
}

case "$cmd" in
  install)
    install_service
    ;;
  remove)
    remove_service
    ;;
  status)
    status_service
    ;;
  *)
    echo "用法: sudo bash setup_cpu_autorestart_monitor.sh [install|remove|status]"
    exit 1
    ;;

esac

