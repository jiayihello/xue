#!/bin/bash
# 一键创建并启动 LXD Management API 服务（/etc/systemd/system/lxd-api.service）
# 用法：sudo bash setup_lxd_api_service.sh [install|remove|status|restart]
# 默认 install：写入单元、daemon-reload、enable 并立即启动

set -euo pipefail

SERVICE_NAME="lxd-api"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
# 自动检测脚本所在目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKDIR="$SCRIPT_DIR"
PYTHON="/usr/bin/python3"
EXEC_START="$PYTHON $WORKDIR/app.py"

cmd=${1:-install}

need_root() {
  if [ "$(id -u)" -ne 0 ]; then
    echo "❌ 需 root 运行：sudo bash $0 ${cmd}"
    exit 1
  fi
}

install_service() {
  need_root
  if [ ! -d "$WORKDIR" ]; then
    echo "❌ 未找到 $WORKDIR"
    exit 1
  fi
  if [ ! -f "$WORKDIR/app.py" ]; then
    echo "❌ 未找到 $WORKDIR/app.py"
    exit 1
  fi

  cat > "$SERVICE_FILE" <<EOF
[Unit]
Description=LXD Management API Service
After=network.target lxd.service
Wants=lxd.service

[Service]
User=root
Group=root
WorkingDirectory=$WORKDIR
ExecStart=$EXEC_START
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

  echo "✅ 已写入服务文件: $SERVICE_FILE"
  echo "▶ 重载并启用服务..."
  systemctl daemon-reload
  systemctl enable ${SERVICE_NAME}.service
  systemctl restart ${SERVICE_NAME}.service
  systemctl --no-pager --lines=15 status ${SERVICE_NAME}.service || true
  echo "✅ 完成：服务已启用并启动。日志查看：journalctl -u ${SERVICE_NAME}.service -f"
}

remove_service() {
  need_root
  systemctl stop ${SERVICE_NAME}.service 2>/dev/null || true
  systemctl disable ${SERVICE_NAME}.service 2>/dev/null || true
  rm -f "$SERVICE_FILE"
  systemctl daemon-reload
  echo "✅ 已移除 ${SERVICE_NAME}.service"
}

status_service() {
  systemctl status ${SERVICE_NAME}.service --no-pager -n 50 || true
}

restart_service() {
  systemctl restart ${SERVICE_NAME}.service
  systemctl --no-pager --lines=15 status ${SERVICE_NAME}.service || true
}

case "$cmd" in
  install)
    install_service ;;
  remove)
    remove_service ;;
  status)
    status_service ;;
  restart)
    restart_service ;;
  *)
    echo "用法：sudo bash $0 [install|remove|status|restart]" ; exit 1 ;;
esac

