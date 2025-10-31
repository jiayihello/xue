#!/bin/bash
# 配置流量限制执行器定时任务

set -e

# 颜色定义
COLOR_GREEN='\033[0;32m'
COLOR_YELLOW='\033[1;33m'
COLOR_RED='\033[0;31m'
COLOR_NC='\033[0m'

# 获取脚本所在目录（server目录）
SERVER_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT_PATH="$SERVER_DIR/flow_limit_enforcer.py"

echo -e "${COLOR_YELLOW}配置流量限制执行器...${COLOR_NC}"

# 检查脚本是否存在
if [ ! -f "$SCRIPT_PATH" ]; then
    echo -e "${COLOR_RED}错误: 找不到 flow_limit_enforcer.py${COLOR_NC}"
    exit 1
fi

# 确保脚本可执行
chmod +x "$SCRIPT_PATH"

# 创建 systemd service
cat > /etc/systemd/system/lxd-flow-limit-enforcer.service <<EOF
[Unit]
Description=LXD Flow Limit Enforcer
Documentation=https://github.com/yourusername/lxd-toolkit
After=network.target snap.lxd.daemon.service lxd.service

[Service]
Type=oneshot
User=root
WorkingDirectory=$SERVER_DIR
ExecStart=/usr/bin/python3 $SCRIPT_PATH check
StandardOutput=journal
StandardError=journal
SyslogIdentifier=lxd-flow-limit-enforcer

[Install]
WantedBy=multi-user.target
EOF

# 创建 systemd timer（每5分钟运行一次）
cat > /etc/systemd/system/lxd-flow-limit-enforcer.timer <<EOF
[Unit]
Description=LXD Flow Limit Enforcer Timer
Documentation=https://github.com/yourusername/lxd-toolkit

[Timer]
OnBootSec=2min
OnUnitActiveSec=5min
Persistent=true

[Install]
WantedBy=timers.target
EOF

# 重新加载 systemd
systemctl daemon-reload

# 启用并启动 timer
systemctl enable lxd-flow-limit-enforcer.timer
systemctl start lxd-flow-limit-enforcer.timer

echo -e "${COLOR_GREEN}✓ 流量限制执行器配置完成${COLOR_NC}"
echo ""
echo "服务状态："
systemctl status lxd-flow-limit-enforcer.timer --no-pager || true
echo ""
echo "使用命令："
echo "  查看状态:  systemctl status lxd-flow-limit-enforcer.timer"
echo "  查看日志:  journalctl -u lxd-flow-limit-enforcer.service -f"
echo "  手动运行:  systemctl start lxd-flow-limit-enforcer.service"
echo "  停止服务:  systemctl stop lxd-flow-limit-enforcer.timer"

