#!/bin/bash
#===============================================
# 手动解除容器网络阻断
#===============================================

if [ -z "$1" ]; then
    echo "用法: bash manual_unblock.sh <容器名>"
    echo ""
    echo "示例:"
    echo "  bash manual_unblock.sh XueiV0606"
    echo "  bash manual_unblock.sh XueiV4342"
    exit 1
fi

CONTAINER_NAME="$1"

echo "╔════════════════════════════════════════════╗"
echo "║      手动解除容器阻断                      ║"
echo "╚════════════════════════════════════════════╝"
echo ""
echo "容器: $CONTAINER_NAME"
echo ""

# 1. 获取容器 IP
echo "[1/4] 获取容器 IP"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

CONTAINER_IP=$(lxc list "$CONTAINER_NAME" -c 4 --format csv | cut -d' ' -f1)

if [ -z "$CONTAINER_IP" ]; then
    echo "❌ 容器未运行或无 IP"
    exit 1
fi

echo "IP: $CONTAINER_IP"
echo ""

# 2. 删除 iptables 规则
echo "[2/4] 删除 iptables 阻断规则"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# 删除所有相关规则（忽略错误）
sudo iptables -D FORWARD -s "$CONTAINER_IP" -j DROP 2>/dev/null && echo "  ✓ 已删除出站 DROP 规则" || echo "  - 无出站 DROP 规则"
sudo iptables -D FORWARD -d "$CONTAINER_IP" -j DROP 2>/dev/null && echo "  ✓ 已删除入站 DROP 规则" || echo "  - 无入站 DROP 规则"
sudo iptables -D FORWARD -s "$CONTAINER_IP" -p tcp --dport 22 -j ACCEPT 2>/dev/null && echo "  ✓ 已删除 SSH ACCEPT 规则" || echo "  - 无 SSH ACCEPT 规则"
sudo iptables -D FORWARD -d "$CONTAINER_IP" -p tcp --sport 22 -j ACCEPT 2>/dev/null && echo "  ✓ 已删除 SSH ACCEPT 规则" || echo "  - 无 SSH ACCEPT 规则"

echo ""

# 3. 更新数据库
echo "[3/4] 更新数据库状态"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

if [ -f "flow_management.db" ]; then
    sqlite3 flow_management.db << SQL
UPDATE container_flow_management 
SET is_blocked = 0, 
    blocked_at = NULL,
    updated_at = datetime('now')
WHERE hostname = '$CONTAINER_NAME';
SQL
    
    if [ $? -eq 0 ]; then
        echo "✓ 数据库已更新"
    else
        echo "⚠️  数据库更新失败"
    fi
else
    echo "⚠️  flow_management.db 不存在"
fi

echo ""

# 4. 验证网络
echo "[4/4] 验证网络连接"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

echo "测试连接..."
if timeout 5 lxc exec "$CONTAINER_NAME" -- ping -c 2 8.8.8.8 >/dev/null 2>&1; then
    echo "✅ 网络已恢复（可以连接外网）"
else
    echo "❌ 网络仍无法连接"
    echo ""
    echo "可能的原因:"
    echo "  1. 还有其他 iptables 规则阻断"
    echo "  2. 容器内部网络配置问题"
    echo ""
    echo "检查 iptables 规则:"
    echo "  sudo iptables -L FORWARD -n -v | grep $CONTAINER_IP"
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✓ 操作完成"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "验证命令:"
echo "  lxc exec $CONTAINER_NAME -- ping -c 3 8.8.8.8"
echo ""

# 保存 iptables 规则
if command -v netfilter-persistent >/dev/null 2>&1; then
    read -p "是否永久保存 iptables 规则? [Y/n]: " save_rules
    if [[ "${save_rules,,}" =~ ^(y|yes|)$ ]] || [ -z "$save_rules" ]; then
        sudo netfilter-persistent save
        echo "✓ 规则已永久保存"
    fi
fi

