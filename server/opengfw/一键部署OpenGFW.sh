#!/bin/bash
#================================================================
# OpenGFW 一键部署快捷脚本
# 用途：从 LXD 服务器主菜单快速调用
#================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# 颜色定义
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m'

clear
echo -e "${BLUE}"
cat << "EOF"
╔═══════════════════════════════════════════════╗
║     OpenGFW 一键部署 - 容器流量拦截工具       ║
╚═══════════════════════════════════════════════╝
EOF
echo -e "${NC}"

echo -e "${GREEN}功能说明：${NC}"
echo "  • 拦截容器内的代理协议（Shadowsocks、Trojan、Socks）"
echo "  • 阻止 VPN 服务（WireGuard、OpenVPN）"
echo "  • 防止 BT/PT 下载滥用"
echo "  • 支持地域限制（仅拦截特定国家/地区）"
echo ""
echo -e "${GREEN}部署位置：${NC}宿主机（会自动分析所有容器流量）"
echo -e "${GREEN}性能影响：${NC}轻量版 < 5% CPU，完全版约 10-20% CPU"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

read -p "是否继续部署 OpenGFW? [Y/n]: " -n 1 -r
echo
if [[ $REPLY =~ ^[Nn]$ ]]; then
    echo "已取消部署"
    exit 0
fi

echo ""
echo "正在启动自动部署脚本..."
sleep 1

# 运行主部署脚本
bash "${SCRIPT_DIR}/deploy_opengfw.sh"

exit_code=$?

if [ $exit_code -eq 0 ]; then
    echo ""
    echo -e "${GREEN}═══════════════════════════════════════════════${NC}"
    echo -e "${GREEN}部署完成！管理命令：${NC}"
    echo -e "${GREEN}═══════════════════════════════════════════════${NC}"
    echo ""
    echo "  bash ${SCRIPT_DIR}/manage_opengfw.sh"
    echo ""
    echo "或直接运行："
    echo "  systemctl status opengfw      # 查看状态"
    echo "  journalctl -u opengfw -f      # 查看实时日志"
    echo ""
fi

read -p "按任意键返回主菜单..."
exit $exit_code

