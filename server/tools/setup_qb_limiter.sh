#!/bin/bash
# 安装 qBittorrent 限速器服务

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SERVICE_FILE="/etc/systemd/system/qb-limiter.service"

cat > "$SERVICE_FILE" << EOF
[Unit]
Description=qBittorrent Process Limiter
After=network.target lxd.service

[Service]
Type=simple
ExecStart=/usr/bin/python3 ${SCRIPT_DIR}/qb_limiter.py --limit 10 --interval 1800
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable qb-limiter
systemctl start qb-limiter

echo "✓ qb-limiter 服务已安装并启动"
echo ""
echo "常用命令:"
echo "  查看状态: systemctl status qb-limiter"
echo "  查看日志: journalctl -u qb-limiter -f"
echo "  停止服务: systemctl stop qb-limiter"
echo "  重启服务: systemctl restart qb-limiter"
