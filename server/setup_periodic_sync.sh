#!/bin/bash
# 配置定期同步服务

set -e

# 颜色定义
COLOR_GREEN='\033[0;32m'
COLOR_YELLOW='\033[1;33m'
COLOR_RED='\033[0;31m'
COLOR_NC='\033[0m'

# 获取脚本所在目录（server目录）
SERVER_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT_PATH="$SERVER_DIR/periodic_sync.py"

echo -e "${COLOR_YELLOW}配置定期同步服务...${COLOR_NC}"

# 检查脚本是否存在
if [ ! -f "$SCRIPT_PATH" ]; then
    echo -e "${COLOR_RED}错误: 找不到 periodic_sync.py${COLOR_NC}"
    exit 1
fi

# 确保脚本可执行
chmod +x "$SCRIPT_PATH"

# 创建 systemd service
cat > /etc/systemd/system/lxd-periodic-sync.service <<EOF
[Unit]
Description=LXD Periodic Sync
Documentation=https://github.com/yourusername/lxd-toolkit
After=network.target snap.lxd.daemon.service lxd.service

[Service]
Type=oneshot
User=root
WorkingDirectory=$SERVER_DIR
ExecStart=/usr/bin/python3 $SCRIPT_PATH sync
StandardOutput=journal
StandardError=journal
SyslogIdentifier=lxd-periodic-sync

[Install]
WantedBy=multi-user.target
EOF

# 创建 systemd timer（每小时运行一次）
cat > /etc/systemd/system/lxd-periodic-sync.timer <<EOF
[Unit]
Description=LXD Periodic Sync Timer
Documentation=https://github.com/yourusername/lxd-toolkit

[Timer]
OnBootSec=5min
OnUnitActiveSec=1h
Persistent=true

[Install]
WantedBy=timers.target
EOF

# 重新加载 systemd
systemctl daemon-reload

# 启用并启动 timer
systemctl enable lxd-periodic-sync.timer
systemctl start lxd-periodic-sync.timer

echo -e "${COLOR_GREEN}✓ 定期同步服务配置完成${COLOR_NC}"
echo ""
echo "服务状态："
systemctl status lxd-periodic-sync.timer --no-pager || true
echo ""
echo "使用命令："
echo "  查看状态:  systemctl status lxd-periodic-sync.timer"
echo "  查看日志:  journalctl -u lxd-periodic-sync.service -f"
echo "  手动运行:  systemctl start lxd-periodic-sync.service"
echo "  停止服务:  systemctl stop lxd-periodic-sync.timer"

