#!/bin/bash
# 安装改进版的 lxd-flow-manager 命令

echo "=========================================="
echo "  安装改进版 lxd-flow-manager 命令"
echo "=========================================="
echo

# 备份旧版本
if [ -f /usr/local/bin/lxd-flow-manager ]; then
    echo "📦 备份旧版本..."
    cp /usr/local/bin/lxd-flow-manager /usr/local/bin/lxd-flow-manager.bak
    echo "   旧版本已备份到: /usr/local/bin/lxd-flow-manager.bak"
fi

# 复制新版本
echo "📥 安装新版本..."
cp lxd-flow-manager-improved.sh /usr/local/bin/lxd-flow-manager
chmod +x /usr/local/bin/lxd-flow-manager

echo "✅ 安装完成！"
echo
echo "=========================================="
echo "  新增功能"
echo "=========================================="
echo "✨ clear <容器名>     - 清零流量（保持周期）"
echo "📊 info              - 格式化JSON输出"
echo "🔄 clear-all         - 批量清零所有容器"
echo
echo "=========================================="
echo "  快速开始"
echo "=========================================="
echo "# 清零单个容器流量"
echo "lxd-flow-manager clear XueiV0412"
echo
echo "# 查看流量信息"
echo "lxd-flow-manager info XueiV0412"
echo
echo "# 查看所有命令"
echo "lxd-flow-manager"
echo "=========================================="

