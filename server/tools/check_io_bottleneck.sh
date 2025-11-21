#!/bin/bash
# LXD 容器 IO 瓶颈诊断脚本

echo "========================================"
echo "  LXD 容器 IO 瓶颈诊断"
echo "========================================"
echo ""

# 颜色定义
RED='\033[0;31m'
YELLOW='\033[1;33m'
GREEN='\033[0;32m'
NC='\033[0m'

# 1. 宿主机 CPU 状态（重点看 iowait）
echo "【1. 宿主机 CPU 状态】"
echo "----------------------------------------"
echo -e "${YELLOW}关键指标：%wa (iowait)${NC}"
echo ""
top -bn1 | head -5
echo ""

# 提取 iowait 值
IOWAIT=$(top -bn1 | grep "Cpu(s)" | awk '{print $10}' | sed 's/%wa,//')
if (( $(echo "$IOWAIT > 20" | bc -l 2>/dev/null || echo 0) )); then
    echo -e "${RED}⚠️  IO等待过高: ${IOWAIT}% (正常应 <5%)${NC}"
elif (( $(echo "$IOWAIT > 5" | bc -l 2>/dev/null || echo 0) )); then
    echo -e "${YELLOW}⚠️  IO等待偏高: ${IOWAIT}% (正常应 <5%)${NC}"
else
    echo -e "${GREEN}✓ IO等待正常: ${IOWAIT}%${NC}"
fi
echo ""
echo ""

# 2. 磁盘 IO 统计
echo "【2. 磁盘 IO 统计】"
echo "----------------------------------------"
echo -e "${YELLOW}关键指标：%util (磁盘使用率), await (响应时间)${NC}"
echo ""

if command -v iostat &> /dev/null; then
    iostat -x 1 1 | tail -n +4
    echo ""
    echo "说明："
    echo "  %util > 80%  : 磁盘接近满载"
    echo "  await > 50ms : IO响应慢"
else
    echo "未安装 iostat (需要 sysstat 包)"
    echo "安装命令: apt install sysstat"
fi
echo ""
echo ""

# 3. IO 占用 TOP 10 进程
echo "【3. IO 占用 TOP 10 进程】"
echo "----------------------------------------"
echo ""

if command -v iotop &> /dev/null; then
    echo "正在采样 IO 数据（3秒）..."
    iotop -o -b -n 3 -P 2>/dev/null | tail -20
elif command -v pidstat &> /dev/null; then
    echo "正在采样 IO 数据（3秒）..."
    pidstat -d 1 3 | grep -v "^Average" | sort -k4 -rn | head -15
else
    echo "未安装 iotop 或 pidstat"
    echo "安装命令: apt install iotop sysstat"
fi
echo ""
echo ""

# 4. 检查容器中的 IO 等待进程
echo "【4. 容器中的 IO 等待进程】"
echo "----------------------------------------"
echo -e "${YELLOW}状态为 D 的进程表示正在等待 IO（不可中断睡眠）${NC}"
echo ""

FOUND_BLOCKED=false

lxc list --format csv -c ns | grep RUNNING | cut -d',' -f1 | while read container; do
    # 检查容器内是否有 D 状态进程
    BLOCKED=$(lxc exec "$container" -- ps aux 2>/dev/null | awk '$8 ~ /D/' | wc -l)
    
    if [ "$BLOCKED" -gt 0 ]; then
        echo -e "${RED}容器: $container - 发现 $BLOCKED 个 IO 阻塞进程${NC}"
        lxc exec "$container" -- ps aux 2>/dev/null | awk '$8 ~ /D/ {printf "  PID: %-8s CPU: %-6s MEM: %-6s CMD: %s\n", $2, $3"%", $4"%", $11}'
        FOUND_BLOCKED=true
    fi
done

if [ "$FOUND_BLOCKED" = false ]; then
    echo -e "${GREEN}✓ 未发现容器中有 IO 阻塞进程${NC}"
fi
echo ""
echo ""

# 5. 存储池状态
echo "【5. LXD 存储池状态】"
echo "----------------------------------------"
lxc storage list
echo ""

# 查看存储池详细信息
for pool in $(lxc storage list --format csv -c n); do
    echo "存储池: $pool"
    lxc storage info "$pool" | grep -E "(space used|total space|driver)"
done
echo ""
echo ""

# 6. 系统负载
echo "【6. 系统负载】"
echo "----------------------------------------"
uptime
echo ""
LOAD=$(uptime | awk -F'load average:' '{print $2}' | awk '{print $1}' | sed 's/,//')
CPUS=$(nproc)
echo "CPU 核心数: $CPUS"
echo "1分钟负载: $LOAD"

if (( $(echo "$LOAD > $CPUS" | bc -l 2>/dev/null || echo 0) )); then
    echo -e "${RED}⚠️  系统负载超过 CPU 核心数，系统过载${NC}"
else
    echo -e "${GREEN}✓ 系统负载正常${NC}"
fi
echo ""
echo ""

# 诊断建议
echo "========================================"
echo "  诊断建议"
echo "========================================"
echo ""
echo "如果发现 IO 瓶颈，可以尝试："
echo ""
echo "1. 检查磁盘健康状态："
echo "   smartctl -a /dev/sda"
echo ""
echo "2. 查看具体容器的 IO 使用："
echo "   lxc exec <容器名> -- iotop"
echo ""
echo "3. 限制容器 IO 速率："
echo "   lxc config device override <容器名> root limits.read=100MB limits.write=100MB"
echo ""
echo "4. 查看容器日志是否有异常："
echo "   lxc info <容器名> --show-log"
echo ""
echo "5. 检查是否有进程在疯狂写日志："
echo "   du -sh /var/lib/lxd/containers/*/rootfs/var/log/*"
echo ""
