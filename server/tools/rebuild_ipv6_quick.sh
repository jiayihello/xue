#!/bin/bash
# IPv6 分配状态快速重建脚本

echo ""
echo "========================================"
echo "  IPv6 分配状态重建"
echo "========================================"
echo ""

# 检查是否在正确的目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVER_DIR="$(dirname "$SCRIPT_DIR")"

# 切换到 server 目录
cd "$SERVER_DIR" || {
    echo "❌ 无法切换到 server 目录"
    exit 1
}

echo "当前目录: $(pwd)"
echo ""

# 检查 Python 脚本是否存在
if [ ! -f "tools/rebuild_ipv6_state.py" ]; then
    echo "❌ 未找到 tools/rebuild_ipv6_state.py"
    exit 1
fi

# 检查 app.ini 配置
echo "检查配置文件..."
if [ ! -f "app.ini" ]; then
    echo "❌ 未找到 app.ini 配置文件"
    exit 1
fi

# 显示当前 IPv6 配置
IPV6_MODE=$(grep "^IPV6_MODE" app.ini | cut -d'=' -f2 | tr -d ' ')
IPV6_PREFIX=$(grep "^IPV6_PREFIX" app.ini | cut -d'=' -f2 | tr -d ' ')

echo "✓ IPv6 模式: $IPV6_MODE"
echo "✓ IPv6 前缀: $IPV6_PREFIX"
echo ""

# 确认执行
echo "========================================"
echo ""
echo "⚠️  重要提示:"
echo "  1. 本工具会重建 ipv6_allocations.json 文件"
echo "  2. 现有状态文件会自动备份"
echo "  3. 从当前容器扫描 IPv6 地址"
echo ""
read -p "是否继续？[y/N]: " -r
echo ""

if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "操作已取消"
    exit 0
fi

echo "========================================"
echo "  开始执行"
echo "========================================"
echo ""

# 执行 Python 脚本
sudo python3 tools/rebuild_ipv6_state.py

# 检查执行结果
if [ $? -eq 0 ]; then
    echo ""
    echo "========================================"
    echo "  ✅ 执行完成"
    echo "========================================"
    echo ""
    echo "建议验证步骤:"
    echo "  1. 查看状态文件:"
    echo "     cat ipv6_allocations.json"
    echo ""
    echo "  2. 查看当前容器:"
    echo "     lxc list"
    echo ""
    echo "  3. 重启后端服务:"
    echo "     sudo systemctl restart lxd-api.service"
    echo ""
    echo "  4. 测试创建新容器:"
    echo "     在魔方财务中开通新容器"
    echo ""
else
    echo ""
    echo "❌ 执行失败，请查看上方错误信息"
    exit 1
fi

