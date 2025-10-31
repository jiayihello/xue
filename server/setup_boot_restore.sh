#!/bin/bash
# 配置启动恢复服务

set -e

# 颜色定义
COLOR_GREEN='\033[0;32m'
COLOR_YELLOW='\033[1;33m'
COLOR_RED='\033[0;31m'
COLOR_NC='\033[0m'

# 获取脚本所在目录（server目录）
SERVER_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT_PATH="$SERVER_DIR/restore_on_boot.py"

echo -e "${COLOR_YELLOW}配置启动恢复服务...${COLOR_NC}"

# 检查脚本是否存在
if [ ! -f "$SCRIPT_PATH" ]; then
    echo -e "${COLOR_RED}错误: 找不到 restore_on_boot.py${COLOR_NC}"
    exit 1
fi

# 确保脚本可执行
chmod +x "$SCRIPT_PATH"

# 创建 systemd service（启动时运行一次）
cat > /etc/systemd/system/lxd-boot-restore.service <<EOF
[Unit]
Description=LXD Flow Rules Boot Restore
Documentation=https://github.com/yourusername/lxd-toolkit
After=network.target snap.lxd.daemon.service lxd.service
# 不使用 Requires，因为 LXD 可能通过 snap 或其他方式安装，服务名不同

[Service]
Type=oneshot
User=root
WorkingDirectory=$SERVER_DIR
ExecStart=/usr/bin/python3 $SCRIPT_PATH
StandardOutput=journal
StandardError=journal
SyslogIdentifier=lxd-boot-restore
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
EOF

# 重新加载 systemd
systemctl daemon-reload

# 启用服务（下次启动时自动运行）
systemctl enable lxd-boot-restore.service

echo -e "${COLOR_GREEN}✓ 启动恢复服务配置完成${COLOR_NC}"
echo ""
echo "服务将在下次系统启动时自动运行"
echo ""
echo "使用命令："
echo "  立即测试:  systemctl start lxd-boot-restore.service"
echo "  查看状态:  systemctl status lxd-boot-restore.service"
echo "  查看日志:  journalctl -u lxd-boot-restore.service -n 50"

