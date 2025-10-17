#!/bin/bash
#===============================================
# 立即阻断超限容器并修复流量限制系统
#===============================================

set -e

echo "╔════════════════════════════════════════════╗"
echo "║      修复流量限制系统                      ║"
echo "╚════════════════════════════════════════════╝"
echo ""

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# 1. 获取所有超限容器
echo "[1/5] 检测超限容器"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

OVERLIMIT_CONTAINERS=$(python3 - << 'PYTHON_EOF'
import sys
sys.path.insert(0, '.')

try:
    from flow_manager import FlowManager
    
    fm = FlowManager()
    records = fm.list_all_records()
    
    overlimit = []
    for r in records:
        used_gb = (r['bytes_sent'] + r['bytes_received']) / (1024**3)
        limit_gb = r['flow_limit_bytes'] / (1024**3)
        
        if used_gb > limit_gb:
            overlimit.append(r['container_name'])
            print(f"超限: {r['container_name']} - {used_gb:.2f}GB / {limit_gb:.2f}GB")
    
    # 输出容器名列表（用于 shell 处理）
    if overlimit:
        print("\n" + " ".join(overlimit))
    else:
        print("\n无超限容器")
        
except Exception as e:
    print(f"错误: {e}", file=sys.stderr)
    sys.exit(1)
PYTHON_EOF
)

if [ -z "$OVERLIMIT_CONTAINERS" ] || [ "$OVERLIMIT_CONTAINERS" = "无超限容器" ]; then
    echo "✓ 未发现超限容器"
    echo ""
    echo "但根据 list_flow_usage.py 的输出，确实有超限容器。"
    echo "可能是流量数据库未同步。"
    echo ""
    read -p "是否手动指定容器名进行阻断? [y/N]: " manual_input
    
    if [[ "${manual_input,,}" =~ ^(y|yes)$ ]]; then
        read -p "输入容器名（空格分隔）: " OVERLIMIT_CONTAINERS
    else
        echo "跳过"
        exit 0
    fi
fi

echo ""
echo "将要阻断的容器: $OVERLIMIT_CONTAINERS"
echo ""

# 2. 逐个阻断
echo "[2/5] 阻断超限容器网络"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

for container in $OVERLIMIT_CONTAINERS; do
    echo ""
    echo "处理容器: $container"
    
    # 获取容器 IP
    CONTAINER_IP=$(lxc list "$container" -c 4 --format csv | cut -d' ' -f1)
    
    if [ -z "$CONTAINER_IP" ]; then
        echo "  ⚠️  容器未运行或无 IP，跳过"
        continue
    fi
    
    echo "  IP: $CONTAINER_IP"
    
    # 检查是否已有 DROP 规则
    if sudo iptables -C FORWARD -s "$CONTAINER_IP" -j DROP 2>/dev/null; then
        echo "  ✓ 已存在 DROP 规则"
    else
        echo "  添加 iptables DROP 规则..."
        sudo iptables -I FORWARD 1 -s "$CONTAINER_IP" -j DROP
        sudo iptables -I FORWARD 1 -d "$CONTAINER_IP" -j DROP
        echo "  ✓ 已阻断网络"
    fi
    
    # 更新数据库标记
    echo "  更新数据库..."
    python3 - << PYTHON_BLOCK_EOF
import sys
sys.path.insert(0, '.')
from flow_manager import FlowManager

fm = FlowManager()
fm.block_container('$container')
print("  ✓ 数据库已更新")
PYTHON_BLOCK_EOF

    # 测试网络连接
    echo "  测试网络连接..."
    if lxc exec "$container" -- timeout 2 ping -c 1 8.8.8.8 >/dev/null 2>&1; then
        echo -e "  ${RED}✗ 网络仍然可用（阻断失败）${NC}"
    else
        echo -e "  ${GREEN}✓ 网络已阻断${NC}"
    fi
done

echo ""
echo "✓ 超限容器阻断完成"
echo ""

# 3. 检查流量限制器服务
echo "[3/5] 检查流量限制器服务"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

if systemctl is-active --quiet lxd-flow-limit-enforcer; then
    echo "✓ lxd-flow-limit-enforcer 服务运行中"
    echo ""
    echo "服务状态:"
    systemctl status lxd-flow-limit-enforcer --no-pager -l | head -15
else
    echo "❌ lxd-flow-limit-enforcer 服务未运行"
    echo ""
    read -p "是否启动服务? [Y/n]: " start_service
    
    if [[ "${start_service,,}" =~ ^(y|yes|)$ ]] || [ -z "$start_service" ]; then
        echo "启动服务..."
        sudo systemctl start lxd-flow-limit-enforcer
        sudo systemctl enable lxd-flow-limit-enforcer
        sleep 3
        
        if systemctl is-active --quiet lxd-flow-limit-enforcer; then
            echo "✓ 服务已启动"
        else
            echo "❌ 服务启动失败"
            echo ""
            echo "查看日志:"
            journalctl -u lxd-flow-limit-enforcer -n 50 --no-pager
        fi
    fi
fi
echo ""

# 4. 检查流量限制器配置
echo "[4/5] 检查流量限制器配置"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

if [ -f "flow_limit_enforcer.py" ]; then
    echo "✓ flow_limit_enforcer.py 存在"
    
    # 检查检查间隔
    CHECK_INTERVAL=$(grep -E "time\.sleep\(|CHECK_INTERVAL" flow_limit_enforcer.py | head -1)
    echo "检查间隔配置: $CHECK_INTERVAL"
    
    if echo "$CHECK_INTERVAL" | grep -q "3600\|60"; then
        echo ""
        echo "⚠️  检查间隔较长，建议改为 300 秒（5 分钟）"
        echo "编辑文件: nano flow_limit_enforcer.py"
    fi
else
    echo "❌ flow_limit_enforcer.py 不存在"
fi
echo ""

# 5. 保存 iptables 规则
echo "[5/5] 保存 iptables 规则"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

if command -v iptables-save >/dev/null 2>&1; then
    echo "保存当前 iptables 规则..."
    sudo iptables-save > /tmp/iptables-backup-$(date +%Y%m%d_%H%M%S).rules
    echo "✓ 已保存到 /tmp/"
    
    # 如果有 netfilter-persistent
    if command -v netfilter-persistent >/dev/null 2>&1; then
        read -p "是否使用 netfilter-persistent 永久保存? [Y/n]: " save_persistent
        if [[ "${save_persistent,,}" =~ ^(y|yes|)$ ]] || [ -z "$save_persistent" ]; then
            sudo netfilter-persistent save
            echo "✓ 已永久保存"
        fi
    else
        echo ""
        echo "⚠️  未安装 netfilter-persistent，重启后规则会丢失"
        echo "安装: apt install iptables-persistent"
    fi
else
    echo "⚠️  iptables-save 不可用"
fi
echo ""

# 总结
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✓ 修复完成"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "已执行的操作:"
echo "  ✓ 阻断超限容器网络"
echo "  ✓ 更新数据库阻断标记"
echo "  ✓ 检查/启动流量限制器服务"
echo "  ✓ 保存 iptables 规则"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "📋 后续操作"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "1. 查看当前流量使用:"
echo "   python3 list_flow_usage.py"
echo ""
echo "2. 查看流量限制器日志:"
echo "   tail -f flow_limit_enforcer.log"
echo "   journalctl -u lxd-flow-limit-enforcer -f"
echo ""
echo "3. 手动解除容器阻断（充值后）:"
echo "   python3 flow_manager.py unblock <容器名>"
echo ""
echo "4. 手动运行一次流量检查:"
echo "   python3 flow_limit_enforcer.py"
echo ""
echo "5. 查看所有阻断的容器:"
echo "   sqlite3 flow_management.db 'SELECT container_name, is_blocked FROM flow_records WHERE is_blocked = 1;'"
echo ""

