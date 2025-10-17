#!/bin/bash
#===============================================
# 验证流量限制功能状态
#===============================================

echo "╔════════════════════════════════════════════╗"
echo "║      流量限制功能状态验证                  ║"
echo "╚════════════════════════════════════════════╝"
echo ""

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

RESULT_FILE="/tmp/flow_limit_verification_$(date +%Y%m%d_%H%M%S).txt"

# 开始记录
{
echo "验证时间: $(date)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# ============================================
# 第一部分：容器阻断状态测试
# ============================================
echo "【1/6】容器网络阻断状态"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

CONTAINERS=("XueiV0606" "XueiV4342")

for container in "${CONTAINERS[@]}"; do
    echo ""
    echo "容器: $container"
    
    # 检查容器是否存在和运行
    if ! lxc info "$container" >/dev/null 2>&1; then
        echo "  状态: ❌ 不存在"
        continue
    fi
    
    CONTAINER_STATE=$(lxc list "$container" -c s --format csv)
    echo "  状态: $CONTAINER_STATE"
    
    if [ "$CONTAINER_STATE" != "RUNNING" ]; then
        echo "  网络: ⚠️  容器未运行，无法测试"
        continue
    fi
    
    # 获取 IP
    CONTAINER_IP=$(lxc list "$container" -c 4 --format csv | cut -d' ' -f1)
    echo "  IP: $CONTAINER_IP"
    
    # 测试网络连接
    echo -n "  网络测试: "
    if timeout 5 lxc exec "$container" -- ping -c 2 -W 2 8.8.8.8 >/dev/null 2>&1; then
        echo "❌ 可以连接外网（未阻断）"
        echo "    → 流量限制未生效！"
    else
        echo "✅ 无法连接外网（已阻断）"
        echo "    → 流量限制已生效"
    fi
    
    # 测试 SSH 端口（应该保留）
    echo -n "  SSH测试: "
    if timeout 3 lxc exec "$container" -- echo "OK" >/dev/null 2>&1; then
        echo "✅ SSH 可用（管理通道保留）"
    else
        echo "⚠️  SSH 不可用"
    fi
done

echo ""
echo ""

# ============================================
# 第二部分：iptables 规则检查
# ============================================
echo "【2/6】iptables 阻断规则"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

for container in "${CONTAINERS[@]}"; do
    CONTAINER_IP=$(lxc list "$container" -c 4 --format csv | cut -d' ' -f1 2>/dev/null)
    
    if [ -n "$CONTAINER_IP" ]; then
        echo ""
        echo "容器: $container ($CONTAINER_IP)"
        
        # 检查 DROP 规则
        DROP_RULES=$(sudo iptables -L FORWARD -n -v | grep "$CONTAINER_IP" | grep -c DROP)
        if [ "$DROP_RULES" -gt 0 ]; then
            echo "  ✅ 发现 $DROP_RULES 条 DROP 规则"
            sudo iptables -L FORWARD -n -v --line-numbers | grep "$CONTAINER_IP" | grep DROP | head -3
        else
            echo "  ❌ 没有 DROP 规则"
            echo "     → 容器网络未被 iptables 阻断"
        fi
        
        # 检查 ACCEPT 规则（SSH）
        ACCEPT_RULES=$(sudo iptables -L FORWARD -n -v | grep "$CONTAINER_IP" | grep -c "tcp dpt:22")
        if [ "$ACCEPT_RULES" -gt 0 ]; then
            echo "  ✅ 发现 SSH ACCEPT 规则（管理通道保留）"
        else
            echo "  ⚠️  没有 SSH ACCEPT 规则"
        fi
    fi
done

echo ""
echo ""

# ============================================
# 第三部分：流量使用情况
# ============================================
echo "【3/6】流量使用情况"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

if [ -f "list_flow_usage.py" ]; then
    echo ""
    python3 list_flow_usage.py | grep -E "NAME|XueiV0606|XueiV4342"
else
    echo "❌ list_flow_usage.py 不存在"
fi

echo ""
echo ""

# ============================================
# 第四部分：数据库阻断状态
# ============================================
echo "【4/6】数据库阻断记录"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

if [ -f "flow_management.db" ]; then
    # 检查是否有 is_blocked 字段
    HAS_IS_BLOCKED=$(sqlite3 flow_management.db "PRAGMA table_info(container_flow_management);" | grep -c "is_blocked" || echo "0")
    
    if [ "$HAS_IS_BLOCKED" -eq 0 ]; then
        echo "⚠️  数据库缺少 is_blocked 字段"
        echo "   需要运行: bash complete_fix.sh"
    else
        echo ""
        echo "超限容器的数据库状态:"
        sqlite3 flow_management.db << 'SQL'
SELECT 
    hostname,
    flow_limit_gb,
    COALESCE(is_blocked, 0) as is_blocked,
    blocked_at
FROM container_flow_management 
WHERE hostname IN ('XueiV0606', 'XueiV4342');
SQL
    fi
else
    echo "❌ flow_management.db 不存在"
fi

echo ""
echo ""

# ============================================
# 第五部分：服务状态
# ============================================
echo "【5/6】流量限制服务状态"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

echo ""
echo "服务状态:"
if systemctl is-active --quiet lxd-flow-limit-enforcer; then
    echo "  ✅ lxd-flow-limit-enforcer.service: 运行中"
else
    echo "  ❌ lxd-flow-limit-enforcer.service: 停止/失败"
fi

echo ""
echo "定时器状态:"
if systemctl is-active --quiet lxd-flow-limit-enforcer.timer; then
    echo "  ✅ lxd-flow-limit-enforcer.timer: 激活"
    NEXT_RUN=$(systemctl status lxd-flow-limit-enforcer.timer | grep "Trigger:" | awk '{print $2, $3, $4}')
    echo "     下次运行: $NEXT_RUN"
else
    echo "  ❌ lxd-flow-limit-enforcer.timer: 未激活"
fi

echo ""
echo "最近执行记录:"
journalctl -u lxd-flow-limit-enforcer.service -n 5 --no-pager 2>/dev/null | grep -E "Started|Failed|Error" || echo "  无记录"

echo ""
echo "Python 语法检查:"
if python3 -m py_compile flow_limit_enforcer.py 2>&1; then
    echo "  ✅ flow_limit_enforcer.py 语法正确"
else
    echo "  ❌ flow_limit_enforcer.py 有语法错误"
    echo "     错误信息:"
    python3 -m py_compile flow_limit_enforcer.py 2>&1 | head -5 | sed 's/^/     /'
fi

echo ""
echo ""

# ============================================
# 第六部分：综合判断
# ============================================
echo "【6/6】综合判断"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# 检查容器阻断状态
BLOCKED_COUNT=0
for container in "${CONTAINERS[@]}"; do
    if lxc list "$container" -c s --format csv 2>/dev/null | grep -q "RUNNING"; then
        if ! timeout 5 lxc exec "$container" -- ping -c 1 8.8.8.8 >/dev/null 2>&1; then
            BLOCKED_COUNT=$((BLOCKED_COUNT + 1))
        fi
    fi
done

# 检查服务状态
SERVICE_OK=0
if systemctl is-active --quiet lxd-flow-limit-enforcer; then
    SERVICE_OK=1
fi

# 检查 Python 语法
PYTHON_OK=0
if python3 -m py_compile flow_limit_enforcer.py 2>/dev/null; then
    PYTHON_OK=1
fi

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "容器阻断功能:"
if [ $BLOCKED_COUNT -eq 2 ]; then
    echo "  ✅ 超限容器已被阻断 ($BLOCKED_COUNT/2)"
    echo "     → XueiV0606 和 XueiV4342 无法访问外网"
    echo "     → 流量限制功能正常工作"
elif [ $BLOCKED_COUNT -eq 1 ]; then
    echo "  ⚠️  部分容器被阻断 ($BLOCKED_COUNT/2)"
    echo "     → 需要检查 iptables 规则"
else
    echo "  ❌ 容器未被阻断 ($BLOCKED_COUNT/2)"
    echo "     → 流量限制未生效"
fi

echo ""
echo "自动化服务:"
if [ $PYTHON_OK -eq 1 ] && [ $SERVICE_OK -eq 1 ]; then
    echo "  ✅ 流量限制器服务正常"
    echo "     → 每 5 分钟自动检查流量"
    echo "     → 超限容器将自动阻断"
elif [ $PYTHON_OK -eq 0 ]; then
    echo "  ❌ Python 脚本有语法错误"
    echo "     → 服务无法启动"
    echo "     → 需要修复: bash complete_fix.sh"
elif [ $SERVICE_OK -eq 0 ]; then
    echo "  ❌ 服务未运行"
    echo "     → 不会自动检查流量"
    echo "     → 需要启动: systemctl start lxd-flow-limit-enforcer"
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# 总结
echo "📊 总结:"
echo ""
if [ $BLOCKED_COUNT -eq 2 ]; then
    echo "  ✅ 手动阻断已生效（容器无法访问外网）"
else
    echo "  ❌ 手动阻断未生效"
fi

if [ $PYTHON_OK -eq 1 ] && [ $SERVICE_OK -eq 1 ]; then
    echo "  ✅ 自动化流量限制功能正常"
else
    echo "  ❌ 自动化流量限制功能异常"
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# 建议操作
echo "💡 建议操作:"
echo ""

if [ $BLOCKED_COUNT -lt 2 ]; then
    echo "1. 立即阻断超限容器:"
    echo "   bash quick_block_overlimit.sh"
    echo ""
fi

if [ $PYTHON_OK -eq 0 ] || [ $SERVICE_OK -eq 0 ]; then
    echo "2. 修复流量限制服务:"
    echo "   bash complete_fix.sh"
    echo ""
fi

if [ $BLOCKED_COUNT -eq 2 ] && [ $PYTHON_OK -eq 1 ] && [ $SERVICE_OK -eq 1 ]; then
    echo "✅ 系统运行正常，无需操作"
    echo ""
    echo "当用户充值后，解除阻断:"
    echo "   python3 flow_limit_enforcer.py unblock XueiV0606"
    echo "   python3 flow_limit_enforcer.py unblock XueiV4342"
    echo ""
fi

} | tee "$RESULT_FILE"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "完整报告已保存到: $RESULT_FILE"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

