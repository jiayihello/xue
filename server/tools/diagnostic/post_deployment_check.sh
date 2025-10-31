#!/bin/bash
#===============================================
# 部署后自动检查脚本 - 更新版
# 适配流量监控系统 V2 (iptables)
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
echo -e "${CYAN}║      部署后自动检查 (V2)                  ║${NC}"
echo -e "${CYAN}╚════════════════════════════════════════════╝${NC}"
echo ""

# 获取脚本所在目录并导航到 server 目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# 从 tools/diagnostic 返回到 server 目录
SERVER_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$SERVER_DIR" || {
    echo -e "${RED}错误: 无法进入 server 目录${NC}"
    exit 1
}

echo -e "${BLUE}检查目录: $SERVER_DIR${NC}"
echo ""

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
echo -e "${CYAN}[1/9] Python 依赖${NC}"
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

# 检查流量监控 V2 需要的库
if python3 -c "import filelock" 2>/dev/null; then
    check_item "filelock (V2 性能优化)" "pass"
else
    check_item "filelock (V2 性能优化)" "warn" "建议安装: pip3 install filelock"
fi

echo ""

# ============================================
# 检查 2: 配置文件
# ============================================
echo -e "${CYAN}[2/9] 配置文件${NC}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

if [ -f "app.ini" ]; then
    check_item "app.ini 存在" "pass"
    
    # 检查 TOKEN 配置
    if grep -q "^TOKEN\s*=" app.ini && [ "$(grep "^TOKEN\s*=" app.ini | cut -d'=' -f2 | tr -d ' ')" != "" ]; then
        TOKEN_VALUE=$(grep "^TOKEN\s*=" app.ini | cut -d'=' -f2 | tr -d ' ')
        # 不显示完整 TOKEN，只显示长度
        TOKEN_LEN=${#TOKEN_VALUE}
        check_item "TOKEN 已配置" "pass" "长度: $TOKEN_LEN 字符"
    else
        check_item "TOKEN 已配置" "fail" "必须设置 TOKEN 用于 API 认证"
    fi
    
    # 读取 HTTP_PORT 配置（默认 8060）
    if grep -q "^HTTP_PORT\s*=" app.ini; then
        HTTP_PORT=$(grep "^HTTP_PORT\s*=" app.ini | cut -d'=' -f2 | tr -d ' ')
        check_item "HTTP_PORT 已配置" "pass" "$HTTP_PORT"
    else
        HTTP_PORT=8060
        check_item "HTTP_PORT 已配置" "warn" "使用默认端口 8060"
    fi
    
    if grep -q "^NAT_LISTEN_IP\s*=" app.ini; then
        NAT_IP=$(grep "^NAT_LISTEN_IP\s*=" app.ini | cut -d'=' -f2 | tr -d ' ')
        check_item "NAT_LISTEN_IP 已配置" "pass" "$NAT_IP"
    else
        check_item "NAT_LISTEN_IP 已配置" "warn" "NAT 功能可能不可用"
    fi
    
    # 检查 IPv4 和 IPv6 模式
    IPV4_MODE=$(grep "^IPV4_MODE\s*=" app.ini 2>/dev/null | cut -d'=' -f2 | tr -d ' ' | tr '[:lower:]' '[:upper:]')
    IPV6_MODE=$(grep "^IPV6_MODE\s*=" app.ini 2>/dev/null | cut -d'=' -f2 | tr -d ' ' | tr '[:lower:]' '[:upper:]')
    
    if [ "$IPV4_MODE" = "OFF" ] && [ "$IPV6_MODE" = "ROUTED" ]; then
        check_item "网络模式" "pass" "IPv6-Only 模式 (ROUTED)"
    elif [ "$IPV4_MODE" = "BRIDGE" ] && [ "$IPV6_MODE" = "ROUTED" ]; then
        check_item "网络模式" "pass" "双栈模式 (IPv4 BRIDGE + IPv6 ROUTED)"
    elif [ "$IPV4_MODE" = "BRIDGE" ] && [ "$IPV6_MODE" = "OFF" ]; then
        check_item "网络模式" "pass" "仅 IPv4 模式 (BRIDGE)"
    else
        check_item "网络模式" "pass" "IPv4: ${IPV4_MODE:-BRIDGE}, IPv6: ${IPV6_MODE:-OFF}"
    fi
else
    check_item "app.ini 存在" "fail" "请复制 app.ini.example 并配置"
    HTTP_PORT=8060
fi

echo ""

# ============================================
# 检查 3: 数据库 (V2)
# ============================================
echo -e "${CYAN}[3/9] 流量监控数据库 V2${NC}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

if [ -f "flow_management_v2.db" ]; then
    check_item "flow_management_v2.db 存在" "pass"
    
    # 检查表结构
    if sqlite3 flow_management_v2.db "SELECT name FROM sqlite_master WHERE type='table';" 2>/dev/null | grep -q "container_flow"; then
        check_item "V2 数据库表结构" "pass"
        
        CONTAINER_COUNT=$(sqlite3 flow_management_v2.db "SELECT COUNT(*) FROM container_flow;" 2>/dev/null || echo "0")
        check_item "数据库中的容器记录" "pass" "$CONTAINER_COUNT 个容器"
    else
        check_item "V2 数据库表结构" "fail" "表结构不正确"
    fi
else
    check_item "flow_management_v2.db 存在" "warn" "将在首次使用时自动创建"
fi

# 检查旧数据库（如果存在，提示迁移）
if [ -f "flow_management.db" ]; then
    check_item "旧数据库 flow_management.db" "warn" "建议运行迁移脚本"
fi

echo ""

# ============================================
# 检查 4: Systemd 服务 (V2)
# ============================================
echo -e "${CYAN}[4/9] Systemd 服务状态 (流量监控 V2)${NC}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# LXD API 服务
if systemctl is-active --quiet lxd-api.service; then
    check_item "lxd-api.service" "pass" "运行中"
else
    if systemctl is-enabled --quiet lxd-api.service 2>/dev/null; then
        check_item "lxd-api.service" "fail" "已启用但未运行"
    else
        check_item "lxd-api.service" "fail" "未安装或未启用"
    fi
fi

# LXD 事件监听器（V2 核心服务）
if systemctl is-active --quiet lxd-event-listener.service; then
    check_item "lxd-event-listener.service" "pass" "运行中 (容器事件监听)"
else
    if systemctl is-enabled --quiet lxd-event-listener.service 2>/dev/null; then
        check_item "lxd-event-listener.service" "warn" "已启用但未运行"
    else
        check_item "lxd-event-listener.service" "warn" "未安装（流量监控可能不完整）"
    fi
fi

# 流量收集器（定时器）
if systemctl is-active --quiet lxd-flow-collector.timer; then
    check_item "lxd-flow-collector.timer" "pass" "激活 (每分钟收集流量)"
else
    check_item "lxd-flow-collector.timer" "warn" "未激活"
fi

# 流量限制执行器（定时器）
if systemctl is-active --quiet lxd-flow-limit-enforcer.timer; then
    check_item "lxd-flow-limit-enforcer.timer" "pass" "激活 (每5分钟检查限制)"
else
    check_item "lxd-flow-limit-enforcer.timer" "warn" "未激活"
fi

# 流量重置调度器（定时器）
if systemctl is-active --quiet lxd-flow-reset-scheduler.timer; then
    check_item "lxd-flow-reset-scheduler.timer" "pass" "激活 (每天凌晨1点)"
else
    check_item "lxd-flow-reset-scheduler.timer" "warn" "未激活"
fi

# 定期同步（定时器）
if systemctl is-active --quiet lxd-periodic-sync.timer; then
    check_item "lxd-periodic-sync.timer" "pass" "激活 (每小时同步)"
else
    check_item "lxd-periodic-sync.timer" "warn" "未激活"
fi

# 启动恢复服务
if systemctl is-enabled --quiet lxd-boot-restore.service 2>/dev/null; then
    check_item "lxd-boot-restore.service" "pass" "已启用 (宿主机重启时恢复规则)"
else
    check_item "lxd-boot-restore.service" "warn" "未启用（宿主机重启后需手动恢复）"
fi

echo ""

# ============================================
# 检查 5: API 可访问性
# ============================================
echo -e "${CYAN}[5/9] API 可访问性${NC}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# 检查监听端口
if ss -tlnp 2>/dev/null | grep -q ":${HTTP_PORT}" || netstat -tlnp 2>/dev/null | grep -q ":${HTTP_PORT}"; then
    check_item "API 监听端口 ${HTTP_PORT}" "pass"
    
    # 尝试访问 API（尝试多个端点）
    API_RESPONSE=$(curl -s -w "\nHTTP_CODE:%{http_code}" http://127.0.0.1:${HTTP_PORT}/api/check 2>/dev/null)
    HTTP_CODE=$(echo "$API_RESPONSE" | grep "HTTP_CODE:" | cut -d: -f2)
    
    if [ "$HTTP_CODE" = "200" ] || echo "$API_RESPONSE" | grep -q '"code".*200'; then
        check_item "API 响应正常" "pass" "/api/check 返回 200"
    else
        # 尝试备用端点
        API_RESPONSE2=$(curl -s -w "\nHTTP_CODE:%{http_code}" http://127.0.0.1:${HTTP_PORT}/ 2>/dev/null)
        HTTP_CODE2=$(echo "$API_RESPONSE2" | grep "HTTP_CODE:" | cut -d: -f2)
        
        if [ "$HTTP_CODE2" = "200" ] || [ "$HTTP_CODE2" = "404" ]; then
            check_item "API 响应正常" "pass" "API 运行中（HTTP $HTTP_CODE2）"
        else
            check_item "API 响应正常" "warn" "API 端点响应异常（可能需要认证）"
        fi
    fi
else
    check_item "API 监听端口 ${HTTP_PORT}" "fail" "服务未启动或端口未监听"
fi

echo ""

# ============================================
# 检查 6: LXD 状态
# ============================================
echo -e "${CYAN}[6/9] LXD 状态${NC}"
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
        NETWORK_COUNT=$(lxc network list -c n --format csv 2>/dev/null | wc -l)
        check_item "网络配置" "pass" "$NETWORK_COUNT 个网络"
    fi
else
    check_item "LXD 可用" "fail" "LXD 无法访问，请检查 LXD 服务"
fi

echo ""

# ============================================
# 检查 7: iptables 流量规则 (V2)
# ============================================
echo -e "${CYAN}[7/9] iptables 流量监控规则 (V2)${NC}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

if iptables -L -n >/dev/null 2>&1; then
    check_item "iptables 可用" "pass"
    
    # 检查 NAT 规则
    NAT_RULES=$(iptables -t nat -L POSTROUTING -n 2>/dev/null | grep -c MASQUERADE || echo "0")
    if [ "$NAT_RULES" -gt 0 ]; then
        check_item "NAT 规则 (MASQUERADE)" "pass" "$NAT_RULES 条规则"
    else
        check_item "NAT 规则 (MASQUERADE)" "warn" "未找到 MASQUERADE 规则"
    fi
    
    # 检查流量统计规则（V2）
    FLOW_RULES=$(iptables -L LXD_FLOW_ACCOUNTING -n 2>/dev/null | grep -c "bytes" 2>/dev/null || echo "0")
    FLOW_RULES=$(echo "$FLOW_RULES" | tr -d '\n\r ' | grep -o '[0-9]*' | head -1)
    FLOW_RULES=${FLOW_RULES:-0}
    
    if [ "$FLOW_RULES" -gt 0 ] 2>/dev/null; then
        check_item "流量统计规则 (V2)" "pass" "$FLOW_RULES 条规则"
    else
        FLOW_RULES_ALT=$(iptables -L -n 2>/dev/null | grep -c "lxd_flow" 2>/dev/null || echo "0")
        FLOW_RULES_ALT=$(echo "$FLOW_RULES_ALT" | tr -d '\n\r ' | grep -o '[0-9]*' | head -1)
        FLOW_RULES_ALT=${FLOW_RULES_ALT:-0}
        
        if [ "$FLOW_RULES_ALT" -gt 0 ] 2>/dev/null; then
            check_item "流量统计规则 (V2)" "pass" "$FLOW_RULES_ALT 条规则"
        else
            check_item "流量统计规则 (V2)" "warn" "未找到流量统计规则（可能尚未创建容器）"
        fi
    fi
    
    # 检查元数据文件
    if [ -f "iptables_rules.json" ]; then
        RULE_COUNT=$(python3 -c "import json; print(len(json.load(open('iptables_rules.json'))))" 2>/dev/null || echo "0")
        check_item "iptables 元数据" "pass" "$RULE_COUNT 条规则记录"
    else
        check_item "iptables 元数据" "warn" "元数据文件未创建（首次运行后生成）"
    fi
else
    check_item "iptables 可用" "fail" "iptables 不可用"
fi

echo ""

# ============================================
# 检查 8: IPv6 配置 (可选)
# ============================================
echo -e "${CYAN}[8/9] IPv6 配置${NC}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

if [ -f "app.ini" ]; then
    IPV6_MODE=$(grep "^IPV6_MODE\s*=" app.ini 2>/dev/null | cut -d'=' -f2 | tr -d ' ' | tr '[:lower:]' '[:upper:]')
    IPV6_PREFIX=$(grep "^IPV6_PREFIX\s*=" app.ini 2>/dev/null | cut -d'=' -f2 | tr -d ' ')
    
    if [ "$IPV6_MODE" = "OFF" ] || [ -z "$IPV6_MODE" ]; then
        check_item "IPv6 状态" "pass" "已禁用"
    elif [ "$IPV6_MODE" = "ROUTED" ]; then
        check_item "IPv6 状态" "pass" "ROUTED 模式（独立 IPv6）"
        if [ -n "$IPV6_PREFIX" ]; then
            check_item "IPv6 前缀" "pass" "$IPV6_PREFIX"
            
            # 检查 IPv6 分配记录
            if [ -f "ipv6_allocations.json" ]; then
                IPV6_ALLOC_COUNT=$(python3 -c "import json; print(len(json.load(open('ipv6_allocations.json'))))" 2>/dev/null || echo "0")
                check_item "IPv6 分配记录" "pass" "$IPV6_ALLOC_COUNT 个容器"
            fi
        else
            check_item "IPv6 前缀" "warn" "ROUTED 模式需要配置 IPV6_PREFIX"
        fi
    elif [ "$IPV6_MODE" = "NAT66" ]; then
        check_item "IPv6 状态" "pass" "NAT66 模式"
    else
        check_item "IPv6 状态" "warn" "未知模式: $IPV6_MODE"
    fi
fi

echo ""

# ============================================
# 检查 9: 日志和性能
# ============================================
echo -e "${CYAN}[9/9] 日志和性能${NC}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# 检查日志文件（V2）
LOG_FILES=(
    "lxd_events.log"
    "flow_collector.log"
    "iptables_manager.log"
)

for log_file in "${LOG_FILES[@]}"; do
    if [ -f "$log_file" ]; then
        LOG_SIZE=$(du -h "$log_file" 2>/dev/null | cut -f1)
        # 检查文件大小，如果超过 100MB 警告
        LOG_SIZE_KB=$(du -k "$log_file" 2>/dev/null | cut -f1)
        if [ "$LOG_SIZE_KB" -gt 102400 ]; then
            check_item "$log_file" "warn" "大小: $LOG_SIZE (建议清理)"
        else
            check_item "$log_file" "pass" "大小: $LOG_SIZE"
        fi
    else
        check_item "$log_file" "warn" "未创建（将在运行时生成）"
    fi
done

# 检查缓存性能（V2 新增）
if [ -f "iptables_rules.json.lock" ]; then
    check_item "文件锁机制 (性能优化)" "pass" "已启用"
fi

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
if [ $TOTAL_CHECKS -gt 0 ]; then
    PASS_RATE=$((PASSED_CHECKS * 100 / TOTAL_CHECKS))
else
    PASS_RATE=0
fi

if [ $FAILED_CHECKS -eq 0 ]; then
    echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${GREEN}✓ 所有关键检查通过！部署成功！${NC}"
    echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo ""
    
    if [ $WARNING_CHECKS -gt 0 ]; then
        echo -e "${YELLOW}提示: 有 $WARNING_CHECKS 个警告项，这些是可选功能或将在运行时自动创建${NC}"
        echo ""
    fi
    
    # 显示快速操作指南
    echo -e "${CYAN}快速操作指南:${NC}"
    echo ""
    echo "  1. 查看 API 状态:"
    echo "     systemctl status lxd-api.service"
    echo ""
    echo "  2. 查看流量监控服务:"
    echo "     systemctl status lxd-event-listener.service"
    echo "     systemctl list-timers | grep lxd-"
    echo ""
    echo "  3. 测试 API:"
    echo "     curl http://127.0.0.1:${HTTP_PORT}/api/check"
    echo ""
    echo "  4. 查看容器流量:"
    echo "     python3 flow_manager_v2.py list"
    echo ""
    echo "  5. 查看容器:"
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
    echo "  1. 查看 API 服务日志:"
    echo "     journalctl -u lxd-api.service -n 50"
    echo ""
    echo "  2. 查看事件监听器日志:"
    echo "     journalctl -u lxd-event-listener.service -n 50"
    echo ""
    echo "  3. 检查配置文件:"
    echo "     cat app.ini"
    echo ""
    echo "  4. 手动启动服务:"
    echo "     systemctl start lxd-api.service"
    echo "     systemctl start lxd-event-listener.service"
    echo ""
    echo "  5. 检查 LXD 状态:"
    echo "     lxc list"
    echo "     systemctl status snap.lxd.daemon.service"
    echo ""
    
    exit 1
fi
