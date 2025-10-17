#!/bin/bash
#===============================================
# 诊断流量限制为何失效
#===============================================

echo "╔════════════════════════════════════════════╗"
echo "║      流量限制失效诊断                      ║"
echo "╚════════════════════════════════════════════╝"
echo ""

PROBLEM_CONTAINERS=("XueiV0606" "XueiV4342")

# 1. 检查流量限制器服务
echo "[1/7] 检查流量限制器服务状态"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
if systemctl is-active --quiet lxd-flow-limit-enforcer; then
    echo "✓ lxd-flow-limit-enforcer 服务运行中"
    echo ""
    echo "最近日志:"
    journalctl -u lxd-flow-limit-enforcer -n 20 --no-pager
else
    echo "❌ lxd-flow-limit-enforcer 服务未运行！"
    echo ""
    echo "这是主要原因：流量限制器未启动，无法阻断超限容器"
    echo ""
    echo "启动服务:"
    echo "  sudo systemctl start lxd-flow-limit-enforcer"
    echo "  sudo systemctl enable lxd-flow-limit-enforcer"
fi
echo ""

# 2. 检查流量管理数据库
echo "[2/7] 检查流量数据库记录"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
if [ -f "flow_management.db" ]; then
    echo "超限容器的数据库记录:"
    for container in "${PROBLEM_CONTAINERS[@]}"; do
        echo ""
        echo "容器: $container"
        sqlite3 flow_management.db << EOF
SELECT 
    container_name,
    printf('%.2f', CAST(bytes_sent + bytes_received AS REAL) / 1024 / 1024 / 1024) as used_gb,
    printf('%.2f', CAST(flow_limit_bytes AS REAL) / 1024 / 1024 / 1024) as limit_gb,
    is_blocked,
    last_check
FROM flow_records 
WHERE container_name = '$container';
EOF
    done
else
    echo "❌ flow_management.db 不存在"
fi
echo ""

# 3. 检查是否有阻断记录
echo "[3/7] 检查阻断日志"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
if [ -f "flow_limit_enforcer.log" ]; then
    echo "最近的阻断操作:"
    grep -E "XueiV0606|XueiV4342" flow_limit_enforcer.log | tail -20
    
    if [ $? -ne 0 ]; then
        echo "⚠️  未找到这两个容器的阻断记录"
    fi
else
    echo "❌ flow_limit_enforcer.log 不存在"
fi
echo ""

# 4. 检查 iptables 规则
echo "[4/7] 检查 iptables DROP 规则"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
for container in "${PROBLEM_CONTAINERS[@]}"; do
    echo ""
    echo "容器: $container"
    
    # 获取容器 IP
    IP=$(lxc list "$container" -c 4 --format csv | cut -d' ' -f1)
    
    if [ -n "$IP" ]; then
        echo "IP: $IP"
        echo "iptables 规则:"
        sudo iptables -L FORWARD -n -v | grep "$IP" || echo "  无规则（应该有 DROP 规则）"
    else
        echo "⚠️  容器未运行或无 IP"
    fi
done
echo ""

# 5. 检查流量管理器配置
echo "[5/7] 检查 flow_manager.py 配置"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
if [ -f "flow_manager.py" ]; then
    echo "检查是否启用了流量限制:"
    grep -n "ENABLE_FLOW_LIMIT\|enable_limit" flow_manager.py | head -5 || echo "未找到配置"
else
    echo "❌ flow_manager.py 不存在"
fi
echo ""

# 6. 检查 app.ini 配置
echo "[6/7] 检查 app.ini 流量配置"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
if [ -f "app.ini" ]; then
    grep -E "FLOW_|ENABLE" app.ini | grep -v "^#" || echo "未找到流量相关配置"
else
    echo "❌ app.ini 不存在"
fi
echo ""

# 7. 手动检查容器当前状态
echo "[7/7] 检查容器当前网络状态"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
for container in "${PROBLEM_CONTAINERS[@]}"; do
    echo ""
    echo "容器: $container"
    
    if lxc info "$container" | grep -q "Status: RUNNING"; then
        echo "  状态: 运行中"
        echo "  网络设备:"
        lxc exec "$container" -- ip -4 addr show eth0 2>/dev/null | grep inet || echo "  无法获取"
        
        # 尝试测试网络连接
        echo "  网络连接测试:"
        if lxc exec "$container" -- timeout 2 ping -c 1 8.8.8.8 >/dev/null 2>&1; then
            echo "  ⚠️  可以连接外网（应该被阻断！）"
        else
            echo "  ✓ 无法连接外网（已阻断）"
        fi
    else
        echo "  状态: 未运行"
    fi
done
echo ""

# 总结和建议
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🔍 诊断总结"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "可能的原因:"
echo "  1. ✅ 流量限制器服务未运行或崩溃"
echo "  2. ✅ iptables 规则未生效或被清除"
echo "  3. ✅ 流量检查间隔太长，容器在检查前跑了大量流量"
echo "  4. ✅ 数据库中 is_blocked 标记未更新"
echo "  5. ✅ 容器在流量限制功能部署前就已经超限"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "📋 推荐操作"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "立即阻断超限容器:"
echo "  python3 flow_manager.py block XueiV0606"
echo "  python3 flow_manager.py block XueiV4342"
echo ""
echo "检查并启动流量限制器:"
echo "  sudo systemctl status lxd-flow-limit-enforcer"
echo "  sudo systemctl start lxd-flow-limit-enforcer"
echo "  sudo systemctl enable lxd-flow-limit-enforcer"
echo ""
echo "查看流量限制器日志:"
echo "  tail -f flow_limit_enforcer.log"
echo "  journalctl -u lxd-flow-limit-enforcer -f"
echo ""
echo "手动运行一次流量检查:"
echo "  python3 flow_limit_enforcer.py"
echo ""

