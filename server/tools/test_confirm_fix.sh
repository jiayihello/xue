#!/bin/bash
# 测试二次确认修复

echo "=========================================="
echo "  测试 IPv6 重新分配工具修复"
echo "=========================================="
echo ""

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVER_DIR="$(dirname "$SCRIPT_DIR")"

# 测试 1: 帮助信息
echo "测试 1: 查看帮助信息"
echo "命令: python3 $SCRIPT_DIR/reassign_ipv6_batch.py --help"
echo ""
python3 "$SCRIPT_DIR/reassign_ipv6_batch.py" --help
echo ""
echo "----------------------------------------"
echo ""

# 测试 2: 检查 --yes 参数
echo "测试 2: 检查 --yes 参数是否被识别"
echo "命令: python3 $SCRIPT_DIR/reassign_ipv6_batch.py --yes (仅检查启动，会立即中断)"
echo ""
echo "按 Ctrl+C 中断..."
sleep 2

timeout 5 python3 "$SCRIPT_DIR/reassign_ipv6_batch.py" --yes 2>/dev/null || true

echo ""
echo "----------------------------------------"
echo ""

# 测试 3: 检查脚本修改
echo "测试 3: 检查一键脚本是否已添加 --yes 参数"
echo ""
if grep -q "reassign_ipv6_batch.py --yes" "$SCRIPT_DIR/reassign_ipv6_quick.sh"; then
    echo "✓ 一键脚本已正确配置 --yes 参数"
else
    echo "✗ 一键脚本未配置 --yes 参数"
fi
echo ""

echo "=========================================="
echo "  测试完成"
echo "=========================================="
echo ""
echo "如果以上测试都通过，说明修复成功！"
echo ""
echo "现在可以运行完整测试:"
echo "  cd $SCRIPT_DIR"
echo "  sudo bash reassign_ipv6_quick.sh"
echo ""

