#!/bin/bash
#================================================================
# OpenGFW 性能测试脚本
# 用途：测试 OpenGFW 对服务器性能的影响
#================================================================

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

print_header() {
    echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${CYAN}$1${NC}"
    echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
}

print_info() {
    echo -e "${BLUE}[信息]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[✓]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[!]${NC} $1"
}

clear
echo -e "${CYAN}"
cat << "EOF"
╔═══════════════════════════════════════════════╗
║       OpenGFW 性能测试                        ║
║     评估 OpenGFW 对服务器的影响               ║
╚═══════════════════════════════════════════════╝
EOF
echo -e "${NC}"

# 检查 OpenGFW 是否安装
if ! systemctl list-unit-files | grep -q opengfw.service; then
    print_warning "OpenGFW 未安装"
    exit 1
fi

print_header "测试说明"
echo ""
echo "此测试将分别测试："
echo "  1. OpenGFW 关闭时的系统性能（基准）"
echo "  2. OpenGFW 开启时的系统性能"
echo "  3. 对比两者差异，计算性能影响"
echo ""
echo "测试项目："
echo "  • CPU 使用率"
echo "  • 内存使用量"
echo "  • 网络延迟"
echo "  • 网络吞吐量（需要 iperf3）"
echo ""
read -p "是否开始测试? [Y/n]: " -n 1 -r
echo
if [[ $REPLY =~ ^[Nn]$ ]]; then
    echo "已取消测试"
    exit 0
fi

# 检查依赖工具
print_info "检查测试工具..."
missing_tools=()

if ! command -v iperf3 &> /dev/null; then
    missing_tools+=("iperf3")
fi

if ! command -v bc &> /dev/null; then
    missing_tools+=("bc")
fi

if [ ${#missing_tools[@]} -ne 0 ]; then
    print_warning "缺少工具: ${missing_tools[*]}"
    read -p "是否自动安装? [Y/n]: " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Nn]$ ]]; then
        if command -v apt-get &> /dev/null; then
            apt-get update -qq
            apt-get install -y -qq ${missing_tools[*]}
        elif command -v yum &> /dev/null; then
            yum install -y -q ${missing_tools[*]}
        fi
    fi
fi

# 记录 OpenGFW 当前状态
opengfw_was_active=false
if systemctl is-active --quiet opengfw.service; then
    opengfw_was_active=true
fi

# ============================================
# 测试函数
# ============================================

# 获取 CPU 使用率（采样 3 秒）
get_cpu_usage() {
    local samples=3
    local total=0
    
    for i in $(seq 1 $samples); do
        local cpu=$(top -bn1 | grep "Cpu(s)" | awk '{print $2}' | cut -d'%' -f1)
        total=$(echo "$total + $cpu" | bc)
        sleep 1
    done
    
    echo "scale=2; $total / $samples" | bc
}

# 获取内存使用量（MB）
get_memory_usage() {
    free -m | awk 'NR==2{printf "%.0f", $3}'
}

# 获取 OpenGFW 进程资源占用
get_opengfw_usage() {
    if pgrep -x OpenGFW > /dev/null; then
        ps aux | grep -v grep | grep OpenGFW | awk '{printf "CPU: %.1f%%, 内存: %.1f%%", $3, $4}'
    else
        echo "未运行"
    fi
}

# 网络延迟测试（ping 本地回环）
get_network_latency() {
    ping -c 10 127.0.0.1 | tail -1 | awk -F '/' '{printf "%.3f", $5}'
}

# ============================================
# 开始测试
# ============================================

print_header "阶段 1：OpenGFW 关闭时的基准测试"
echo ""

print_info "停止 OpenGFW 服务..."
systemctl stop opengfw.service
sleep 2

print_info "采集基准数据（请等待 10 秒）..."
baseline_cpu=$(get_cpu_usage)
baseline_mem=$(get_memory_usage)
baseline_latency=$(get_network_latency)

echo ""
echo "基准数据："
echo "  CPU 使用率: ${baseline_cpu}%"
echo "  内存使用: ${baseline_mem} MB"
echo "  网络延迟: ${baseline_latency} ms"
echo ""

sleep 2

# ============================================

print_header "阶段 2：OpenGFW 开启时的性能测试"
echo ""

print_info "启动 OpenGFW 服务..."
systemctl start opengfw.service
sleep 3

if ! systemctl is-active --quiet opengfw.service; then
    print_warning "OpenGFW 启动失败，无法继续测试"
    exit 1
fi

print_info "采集运行数据（请等待 10 秒）..."
opengfw_cpu=$(get_cpu_usage)
opengfw_mem=$(get_memory_usage)
opengfw_latency=$(get_network_latency)
opengfw_process=$(get_opengfw_usage)

echo ""
echo "运行数据："
echo "  CPU 使用率: ${opengfw_cpu}%"
echo "  内存使用: ${opengfw_mem} MB"
echo "  网络延迟: ${opengfw_latency} ms"
echo "  OpenGFW 进程: ${opengfw_process}"
echo ""

sleep 2

# ============================================

print_header "阶段 3：性能影响分析"
echo ""

# 计算差异
cpu_diff=$(echo "scale=2; $opengfw_cpu - $baseline_cpu" | bc)
mem_diff=$(echo "$opengfw_mem - $baseline_mem" | bc)
latency_diff=$(echo "scale=3; $opengfw_latency - $baseline_latency" | bc)

# CPU 影响
echo -e "${CYAN}CPU 影响：${NC}"
echo "  基准: ${baseline_cpu}%"
echo "  运行: ${opengfw_cpu}%"
echo "  增加: ${cpu_diff}%"

if (( $(echo "$cpu_diff < 5" | bc -l) )); then
    print_success "影响很小（< 5%）"
elif (( $(echo "$cpu_diff < 15" | bc -l) )); then
    print_info "影响中等（5-15%）"
else
    print_warning "影响较大（> 15%）- 建议使用轻量版规则"
fi

echo ""

# 内存影响
echo -e "${CYAN}内存影响：${NC}"
echo "  基准: ${baseline_mem} MB"
echo "  运行: ${opengfw_mem} MB"
echo "  增加: ${mem_diff} MB"

if [ "$mem_diff" -lt 100 ]; then
    print_success "影响很小（< 100MB）"
elif [ "$mem_diff" -lt 300 ]; then
    print_info "影响中等（100-300MB）"
else
    print_warning "影响较大（> 300MB）"
fi

echo ""

# 延迟影响
echo -e "${CYAN}网络延迟影响：${NC}"
echo "  基准: ${baseline_latency} ms"
echo "  运行: ${opengfw_latency} ms"
echo "  增加: ${latency_diff} ms"

if (( $(echo "$latency_diff < 1" | bc -l) )); then
    print_success "影响很小（< 1ms）"
elif (( $(echo "$latency_diff < 5" | bc -l) )); then
    print_info "影响中等（1-5ms）"
else
    print_warning "影响较大（> 5ms）"
fi

echo ""

# ============================================

print_header "测试建议"
echo ""

# 根据测试结果给出建议
if (( $(echo "$cpu_diff > 20" | bc -l) )); then
    echo "🔧 CPU 使用率较高，建议："
    echo "   1. 切换到轻量版规则（只拦截核心代理协议）"
    echo "   2. 减少 workers.count（编辑 /etc/opengfw/config.yaml）"
    echo "   3. 关闭日志记录（在规则中设置 log: false）"
    echo ""
fi

if [ "$mem_diff" -gt 300 ]; then
    echo "💾 内存使用较高，建议："
    echo "   1. 减少 tcpTimeout（编辑 /etc/opengfw/config.yaml）"
    echo "   2. 降低 queueSize 和缓冲区大小"
    echo ""
fi

if (( $(echo "$latency_diff > 5" | bc -l) )); then
    echo "⚡ 网络延迟增加明显，建议："
    echo "   1. 使用轻量版规则"
    echo "   2. 增加 workers.count 以提高并发处理能力"
    echo ""
fi

if (( $(echo "$cpu_diff < 10" | bc -l) )) && [ "$mem_diff" -lt 150 ]; then
    echo "✅ 性能影响在可接受范围内，当前配置良好！"
    echo ""
fi

# ============================================

print_header "测试完成"
echo ""

# 恢复 OpenGFW 原始状态
if [ "$opengfw_was_active" = true ]; then
    print_info "恢复 OpenGFW 服务..."
    systemctl start opengfw.service
else
    print_info "OpenGFW 原本未运行，已停止服务"
    systemctl stop opengfw.service
fi

echo ""
echo "详细配置文件："
echo "  配置文件: /etc/opengfw/config.yaml"
echo "  规则文件: /etc/opengfw/rules.yaml"
echo ""
echo "管理命令："
echo "  bash /etc/opengfw/manage_opengfw.sh"
echo ""

read -p "按任意键退出..."

