#!/bin/bash
# OpenGFW 管理脚本 - ifconfig 命令修复

COLOR_GREEN='\033[0;32m'
COLOR_RED='\033[0;31m'
COLOR_YELLOW='\033[1;33m'
COLOR_NC='\033[0m'

echo "========================================"
echo "  修复 OpenGFW 管理脚本 ifconfig 问题"
echo "========================================"
echo ""

# 检查管理脚本是否存在
if [ ! -f "/etc/opengfw/manage_opengfw.sh" ]; then
    echo -e "${COLOR_RED}✗ 错误: 未找到 /etc/opengfw/manage_opengfw.sh${COLOR_NC}"
    echo "  请先部署 OpenGFW"
    exit 1
fi

echo -e "${COLOR_YELLOW}➜ 正在修复 ifconfig 命令问题...${COLOR_NC}"
echo ""

# 备份原文件
if [ ! -f "/etc/opengfw/manage_opengfw.sh.backup" ]; then
    cp /etc/opengfw/manage_opengfw.sh /etc/opengfw/manage_opengfw.sh.backup
    echo -e "${COLOR_GREEN}✓ 已备份原文件${COLOR_NC}"
fi

# 修复 ifconfig 命令
sed -i 's/print_warning "未安装 vnstat，使用 ifconfig 代替"/print_warning "未安装 vnstat，使用 ip 命令代替"/' /etc/opengfw/manage_opengfw.sh
sed -i 's|ifconfig | grep -A 7 "\^\\[a-z\\]" | grep -E "RX|TX"|ip -s link show | grep -E "^\\s+RX|^\\s+TX" | head -20|' /etc/opengfw/manage_opengfw.sh

echo -e "${COLOR_GREEN}✓ 已修复 ifconfig 命令${COLOR_NC}"
echo ""

echo "========================================"
echo -e "${COLOR_GREEN}✓ 修复完成！${COLOR_NC}"
echo "========================================"
echo ""
echo "现在可以正常使用 OpenGFW 管理界面了："
echo "  bash /etc/opengfw/manage_opengfw.sh"
echo ""
echo "或者运行："
echo "  sudo xue"
echo "  选择 14) 管理 OpenGFW"
echo ""

