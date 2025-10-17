#!/bin/bash
#===============================================
# 部署后自动检查脚本
#===============================================

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

echo ""
echo -e "${CYAN}╔════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║      部署后自动检查                        ║${NC}"
echo -e "${CYAN}╚════════════════════════════════════════════╝${NC}"
echo ""

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

TOTAL_CHECKS=0
PASSED_CHECKS=0
FAILED_CHECKS=0
WARNING_CHECKS=0

# 辅助函数
check_item() {
    local name="$1"
    local status="$2"
    local details="$3"
    
    TOTAL_CHECKS=$((TOTAL_CHECKS + 1))
    
    if [ "$status" = "pass" ]; then
        echo -e "  ${GREEN}✓${NC} $name"
        [ -n "$details" ] && echo -e "    ${BLUE}→${NC} $details"
        PASSED_CHECKS=$((PASSED_CHECKS + 1))
    elif [ "$status" = "fail" ]; then
        echo -e "  ${RED}✗${NC} $name"
        [ -n "$details" ] && echo -e "    ${RED}→${NC} $details"
        FAILED_CHECKS=$((FAILED_CHECKS + 1))
    else
        echo -e "  ${YELLOW}⚠${NC} $name"
        [ -n "$details" ] && echo -e "    ${YELLOW}→${NC} $details"
        WARNING_CHECKS=$((WARNING_CHECKS + 1))
    fi
}

# ============================================
# 检查 1: Python 依赖
# ============================================
echo -e "${CYAN}[1/8] Python 依赖${NC}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

if python3 -c "import flask, pylxd" 2>/dev/null; then
    check_item "Flask 和 pylxd" "pass"
else
    check_item "Flask 和 pylxd" "fail" "请运行: pip3 install -r requirements.txt"
fi

if [ -f "requirements.txt" ]; then
    check_item "requirements.txt 存在" "pass"
else
    check_item "requirements.txt 存在" "fail"
fi

echo ""

# ============================================
# 检查 2: 配置文件
# ============================================
echo -e "${CYAN}[2/8] 配置文件${NC}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

if [ -f "app.ini" ]; then
    check_item "app.ini 存在" "pass"
    
    # 检查关键配置
    if grep -q "^API_KEY\s*=" app.ini && [ "$(grep "^API_KEY\s*=" app.ini | cut -d'=' -f2 | tr -d ' ')" != "" ]; then
        check_item "API_KEY 已配置" "pass"
    else
        check_item "API_KEY 已配置" "fail" "请设置 API_KEY"
    fi
    
    if grep -q "^NAT_LISTEN_IP\s*=" app.ini; then
        NAT_IP=$(grep "^NAT_LISTEN_IP\s*=" app.ini | cut -d'=' -f2 | tr -d ' ')
        check_item "NAT_LISTEN_IP 已配置" "pass" "$NAT_IP"
    else
        check_item "NAT_LISTEN_IP 已配置" "fail"
    fi
else
    check_item "app.ini 存在" "fail" "请复制 app.ini.example 并配置"
fi

echo ""

# ============================================
# 检查 3: 数据库
# ============================================
echo -e "${CYAN}[3/8] 数据库${NC}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

if [ -f "flow_management.db" ]; then
    check_item "flow_management.db 存在" "pass"
    
    # 检查表结构
    if sqlite3 flow_management.db "SELECT name FROM sqlite_master WHERE type='table';" 2>/dev/null | grep -q "container_flow_management"; then
        check_item "数据库表结构正确" "pass"
        
        CONTAINER_COUNT=$(sqlite3 flow_management.db "SELECT COUNT(*) FROM container_flow_management;" 2>/dev/null || echo "0")
        check_item "容器记录数" "pass" "$CONTAINER_COUNT 个容器"
    else
        check_item "数据库表结构正确" "fail" "请运行: python3 flow_manager.py"
    fi
else
    check_item "flow_management.db 存在" "warn" "将在首次使用时自动创建"
fi

echo ""

# ============================================
# 检查 4: Systemd 服务和后台任务
# ============================================
echo -e "${CYAN}[4/8] Systemd 服务和后台任务${NC}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# LXD API 服务
if systemctl is-active --quiet lxd-api; then
    check_item "lxd-api.service" "pass" "运行中"
else
    if systemctl is-enabled --quiet lxd-api 2>/dev/null; then
        check_item "lxd-api.service" "fail" "已启用但未运行"
    else
        check_item "lxd-api.service" "fail" "未安装或未启用"
    fi
fi

# 流量限制执行器（定时器）
if systemctl is-active --quiet lxd-flow-limit-enforcer.timer; then
    check_item "lxd-flow-limit-enforcer.timer" "pass" "定时器激活"
    
    # 检查最近执行状态
    LAST_RUN=$(systemctl status lxd-flow-limit-enforcer.service 2>/dev/null | grep "Active:" | grep -oP "since.*" || echo "未知")
    if [ "$LAST_RUN" != "未知" ]; then
        check_item "流量限制器最近执行" "pass" "$LAST_RUN"
    fi
else
    check_item "lxd-flow-limit-enforcer.timer" "warn" "定时器未激活"
fi

# 流量连续性守护进程
if systemctl list-unit-files 2>/dev/null | grep -q "lxd-flow-continuity.service"; then
    if systemctl is-active --quiet lxd-flow-continuity; then
        check_item "lxd-flow-continuity.service" "pass" "流量连续性守护进程运行中"
    else
        check_item "lxd-flow-continuity.service" "warn" "流量连续性守护进程未运行"
    fi
else
    check_item "lxd-flow-continuity.service" "warn" "未安装（可选）"
fi

# CPU 监控服务
if systemctl list-unit-files 2>/dev/null | grep -q "lxd-cpu-monitor.service"; then
    if systemctl is-active --quiet lxd-cpu-monitor; then
        check_item "lxd-cpu-monitor.service" "pass" "CPU 监控运行中"
    else
        check_item "lxd-cpu-monitor.service" "warn" "CPU 监控未运行"
    fi
else
    check_item "lxd-cpu-monitor.service" "warn" "未安装（可选）"
fi

# 检查 Cron 任务（流量重置调度器）
echo ""
echo "Cron 定时任务:"
if crontab -l 2>/dev/null | grep -q "flow_reset_scheduler.py"; then
    check_item "流量重置调度器 (cron)" "pass" "已配置"
    
    # 显示具体的 cron 时间
    CRON_SCHEDULE=$(crontab -l 2>/dev/null | grep "flow_reset_scheduler.py" | grep -v "^#" | head -1 | awk '{print $1,$2,$3,$4,$5}')
    if [ -n "$CRON_SCHEDULE" ]; then
        check_item "重置调度时间" "pass" "$CRON_SCHEDULE"
    fi
else
    check_item "流量重置调度器 (cron)" "warn" "未配置定时重置"
fi

# 检查流量管理器命令
if [ -f "/usr/local/bin/lxd-flow-limit" ]; then
    check_item "lxd-flow-limit 命令" "pass" "快捷命令已安装"
else
    check_item "lxd-flow-limit 命令" "warn" "快捷命令未安装"
fi

echo ""

# ============================================
# 检查 5: API 可访问性
# ============================================
echo -e "${CYAN}[5/8] API 可访问性${NC}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# 检查监听端口
if ss -tlnp 2>/dev/null | grep -q ":5000"; then
    check_item "API 监听端口 5000" "pass"
    
    # 尝试访问 API
    if curl -s http://127.0.0.1:5000/api/ping 2>/dev/null | grep -q "pong"; then
        check_item "API 响应正常" "pass"
    else
        check_item "API 响应正常" "fail" "无法访问 /api/ping"
    fi
else
    check_item "API 监听端口 5000" "fail" "服务未启动"
fi

echo ""

# ============================================
# 检查 6: LXD 状态
# ============================================
echo -e "${CYAN}[6/8] LXD 状态${NC}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

if lxc list >/dev/null 2>&1; then
    check_item "LXD 可用" "pass"
    
    CONTAINER_COUNT=$(lxc list -c n --format csv 2>/dev/null | wc -l)
    check_item "容器数量" "pass" "$CONTAINER_COUNT 个"
    
    # 检查存储池
    if lxc storage list >/dev/null 2>&1; then
        POOL_COUNT=$(lxc storage list -c n --format csv 2>/dev/null | wc -l)
        check_item "存储池" "pass" "$POOL_COUNT 个"
        
        # 检查是否有 UNAVAILABLE 的存储池
        if lxc storage list 2>/dev/null | grep -q "UNAVAILABLE"; then
            check_item "存储池健康状态" "fail" "有存储池不可用"
        else
            check_item "存储池健康状态" "pass"
        fi
    fi
    
    # 检查网络
    if lxc network list >/dev/null 2>&1; then
        check_item "网络配置" "pass"
    fi
else
    check_item "LXD 可用" "fail" "LXD 无法访问"
fi

echo ""

# ============================================
# 检查 7: 网络配置
# ============================================
echo -e "${CYAN}[7/8] 网络配置${NC}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# 检查 iptables 规则
if iptables -L -n >/dev/null 2>&1; then
    check_item "iptables 可用" "pass"
    
    NAT_RULES=$(iptables -t nat -L POSTROUTING -n 2>/dev/null | grep -c MASQUERADE || echo "0")
    if [ "$NAT_RULES" -gt 0 ]; then
        check_item "NAT 规则" "pass" "$NAT_RULES 条 MASQUERADE 规则"
    else
        check_item "NAT 规则" "warn" "未找到 MASQUERADE 规则"
    fi
else
    check_item "iptables 可用" "fail"
fi

# 检查 IPv6
if [ -f "app.ini" ]; then
    IPV6_MODE=$(grep "^IPV6_MODE\s*=" app.ini 2>/dev/null | cut -d'=' -f2 | tr -d ' ' | tr '[:upper:]' '[:lower:]')
    if [ "$IPV6_MODE" = "off" ] || [ -z "$IPV6_MODE" ]; then
        check_item "IPv6 配置" "pass" "IPv6 已禁用"
    elif [ "$IPV6_MODE" = "routed" ] || [ "$IPV6_MODE" = "nat66" ]; then
        check_item "IPv6 配置" "pass" "模式: $IPV6_MODE"
    else
        check_item "IPv6 配置" "warn" "未知模式: $IPV6_MODE"
    fi
fi

echo ""

# ============================================
# 检查 8: 日志文件
# ============================================
echo -e "${CYAN}[8/8] 日志文件${NC}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

LOG_FILES=(
    "flow_limit_enforcer.log"
    "flow_continuity_daemon.log"
    "flow_reset.log"
)

for log_file in "${LOG_FILES[@]}"; do
    if [ -f "$log_file" ]; then
        LOG_SIZE=$(du -h "$log_file" 2>/dev/null | cut -f1)
        check_item "$log_file" "pass" "大小: $LOG_SIZE"
    else
        check_item "$log_file" "warn" "未创建（将在运行时生成）"
    fi
done

echo ""

# ============================================
# 总结
# ============================================
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo -e "${CYAN}检查总结${NC}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "  总检查项: $TOTAL_CHECKS"
echo -e "  ${GREEN}✓ 通过: $PASSED_CHECKS${NC}"
echo -e "  ${YELLOW}⚠ 警告: $WARNING_CHECKS${NC}"
echo -e "  ${RED}✗ 失败: $FAILED_CHECKS${NC}"
echo ""

# 计算通过率
PASS_RATE=$((PASSED_CHECKS * 100 / TOTAL_CHECKS))

if [ $FAILED_CHECKS -eq 0 ]; then
    echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${GREEN}✓ 所有关键检查通过！部署成功！${NC}"
    echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo ""
    
    if [ $WARNING_CHECKS -gt 0 ]; then
        echo -e "${YELLOW}提示: 有 $WARNING_CHECKS 个警告项，建议查看上方详情${NC}"
        echo ""
    fi
    
    # 显示快速操作指南
    echo -e "${CYAN}快速操作指南:${NC}"
    echo ""
    echo "  1. 查看 API 状态:"
    echo "     systemctl status lxd-api"
    echo ""
    echo "  2. 查看实时日志:"
    echo "     tail -f flow_limit_enforcer.log"
    echo ""
    echo "  3. 测试 API:"
    echo "     curl http://127.0.0.1:5000/api/ping"
    echo ""
    echo "  4. 查看容器:"
    echo "     lxc list"
    echo ""
    
    exit 0
else
    echo -e "${RED}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${RED}✗ 检查发现 $FAILED_CHECKS 个问题，需要修复${NC}"
    echo -e "${RED}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo ""
    
    echo -e "${CYAN}建议操作:${NC}"
    echo ""
    echo "  1. 查看详细日志:"
    echo "     journalctl -u lxd-api -n 50"
    echo ""
    echo "  2. 检查配置文件:"
    echo "     cat app.ini"
    echo ""
    echo "  3. 手动启动服务:"
    echo "     systemctl start lxd-api"
    echo ""
    echo "  4. 重新部署:"
    echo "     bash deploy_all.sh"
    echo ""
    
    exit 1
fi

