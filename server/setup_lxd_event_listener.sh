#!/bin/bash
# 配置 LXD 事件监听器服务

set -e

# 颜色定义
COLOR_GREEN='\033[0;32m'
COLOR_YELLOW='\033[1;33m'
COLOR_RED='\033[0;31m'
COLOR_NC='\033[0m'

# 获取脚本所在目录（server目录）
SERVER_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT_PATH="$SERVER_DIR/lxd_event_listener.py"

echo -e "${COLOR_YELLOW}配置 LXD 事件监听器...${COLOR_NC}"

# 检查脚本是否存在
if [ ! -f "$SCRIPT_PATH" ]; then
    echo -e "${COLOR_RED}错误: 找不到 lxd_event_listener.py${COLOR_NC}"
    exit 1
fi

# 确保脚本可执行
chmod +x "$SCRIPT_PATH"

# 创建 systemd service（持续运行）
cat > /etc/systemd/system/lxd-event-listener.service <<EOF
[Unit]
Description=LXD Event Listener
Documentation=https://github.com/yourusername/lxd-toolkit
After=network.target snap.lxd.daemon.service lxd.service
# 不使用 Requires，因为 LXD 可能通过 snap 或其他方式安装，服务名不同

[Service]
Type=simple
User=root
WorkingDirectory=$SERVER_DIR
ExecStart=/usr/bin/python3 $SCRIPT_PATH listen
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal
SyslogIdentifier=lxd-event-listener

[Install]
WantedBy=multi-user.target
EOF

# 重新加载 systemd
systemctl daemon-reload

# 启用并启动服务
systemctl enable lxd-event-listener.service
systemctl restart lxd-event-listener.service

# 等待服务启动
sleep 2

# 检查服务是否真的在运行
if systemctl is-active --quiet lxd-event-listener.service; then
    echo -e "${COLOR_GREEN}✓ LXD 事件监听器配置完成并正在运行${COLOR_NC}"
else
    echo -e "${COLOR_YELLOW}⚠ 服务已配置但未正常启动${COLOR_NC}"
    echo -e "${COLOR_YELLOW}这可能是正常的，服务将在几秒后启动${COLOR_NC}"
fi

echo ""
echo "服务状态："
systemctl status lxd-event-listener.service --no-pager || true
echo ""
echo "使用命令："
echo "  查看状态:  systemctl status lxd-event-listener.service"
echo "  查看日志:  journalctl -u lxd-event-listener.service -f"
echo "  重启服务:  systemctl restart lxd-event-listener.service"
echo "  停止服务:  systemctl stop lxd-event-listener.service"

