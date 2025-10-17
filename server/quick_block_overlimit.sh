#!/bin/bash
#===============================================
# 快速阻断超限容器
#===============================================

set -e

echo "╔════════════════════════════════════════════╗"
echo "║      立即阻断超限容器                      ║"
echo "╚════════════════════════════════════════════╝"
echo ""

# 超限容器列表
CONTAINERS=("XueiV0606" "XueiV4342")

echo "[1/3] 阻断容器网络"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

for container in "${CONTAINERS[@]}"; do
    echo ""
    echo "处理: $container"
    
    # 获取容器 IP
    CONTAINER_IP=$(lxc list "$container" -c 4 --format csv | cut -d' ' -f1)
    
    if [ -z "$CONTAINER_IP" ]; then
        echo "  ⚠️  容器未运行或无 IP"
        continue
    fi
    
    echo "  IP: $CONTAINER_IP"
    
    # 删除可能存在的旧规则
    sudo iptables -D FORWARD -s "$CONTAINER_IP" -j DROP 2>/dev/null || true
    sudo iptables -D FORWARD -d "$CONTAINER_IP" -j DROP 2>/dev/null || true
    sudo iptables -D FORWARD -s "$CONTAINER_IP" -p tcp --dport 22 -j ACCEPT 2>/dev/null || true
    sudo iptables -D FORWARD -d "$CONTAINER_IP" -p tcp --sport 22 -j ACCEPT 2>/dev/null || true
    
    # 添加新规则（保留 SSH 访问）
    sudo iptables -I FORWARD 1 -s "$CONTAINER_IP" -p tcp --dport 22 -j ACCEPT
    sudo iptables -I FORWARD 1 -d "$CONTAINER_IP" -p tcp --sport 22 -j ACCEPT
    sudo iptables -I FORWARD 1 -s "$CONTAINER_IP" -j DROP
    sudo iptables -I FORWARD 1 -d "$CONTAINER_IP" -j DROP
    
    echo "  ✓ iptables 规则已添加"
    
    # 测试连接
    if lxc exec "$container" -- timeout 2 ping -c 1 8.8.8.8 >/dev/null 2>&1; then
        echo "  ❌ 网络仍可用（阻断失败）"
    else
        echo "  ✅ 网络已阻断"
    fi
done

echo ""
echo "[2/3] 更新数据库状态"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

if [ -f "flow_management.db" ]; then
    for container in "${CONTAINERS[@]}"; do
        echo "  更新: $container"
        
        # 检查表结构
        HAS_IS_BLOCKED=$(sqlite3 flow_management.db "PRAGMA table_info(container_flow_management);" | grep -c "is_blocked" || echo "0")
        
        if [ "$HAS_IS_BLOCKED" -eq 0 ]; then
            echo "    添加 is_blocked 字段..."
            sqlite3 flow_management.db "ALTER TABLE container_flow_management ADD COLUMN is_blocked BOOLEAN DEFAULT 0;"
            sqlite3 flow_management.db "ALTER TABLE container_flow_management ADD COLUMN blocked_at DATETIME;"
        fi
        
        # 更新状态
        sqlite3 flow_management.db << SQL
UPDATE container_flow_management 
SET is_blocked = 1, 
    blocked_at = datetime('now'),
    updated_at = datetime('now')
WHERE hostname = '$container';
SQL
        echo "    ✓ 已更新"
    done
else
    echo "  ⚠️  flow_management.db 不存在"
fi

echo ""
echo "[3/3] 保存 iptables 规则"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# 保存到临时文件
sudo iptables-save > /tmp/iptables-backup-$(date +%Y%m%d_%H%M%S).rules
echo "✓ 已保存到 /tmp/"

# 如果有 iptables-persistent
if command -v netfilter-persistent >/dev/null 2>&1; then
    read -p "是否永久保存规则? [Y/n]: " save_permanent
    if [[ "${save_permanent,,}" =~ ^(y|yes|)$ ]] || [ -z "$save_permanent" ]; then
        sudo netfilter-persistent save
        echo "✓ 已永久保存"
    fi
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✓ 阻断完成"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "验证容器网络:"
for container in "${CONTAINERS[@]}"; do
    echo "  $container:"
    if lxc exec "$container" -- timeout 2 ping -c 1 8.8.8.8 >/dev/null 2>&1; then
        echo "    ❌ 仍可连接外网"
    else
        echo "    ✅ 已阻断"
    fi
done
echo ""
echo "查看当前流量:"
echo "  python3 list_flow_usage.py"
echo ""
echo "解除阻断（充值后）:"
echo "  python3 flow_limit_enforcer.py unblock XueiV0606"
echo "  python3 flow_limit_enforcer.py unblock XueiV4342"

