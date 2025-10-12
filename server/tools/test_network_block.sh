#!/bin/bash

# 网络阻断验证脚本
# 用于测试容器是否真的被阻断网络访问

CONTAINER_NAME="$1"

if [ -z "$CONTAINER_NAME" ]; then
    echo "用法: bash test_network_block.sh <容器名>"
    echo "示例: bash test_network_block.sh XueiV2389"
    exit 1
fi

echo "=== 测试容器 $CONTAINER_NAME 的网络阻断状态 ==="

# 检查容器是否存在
if ! lxc list --format csv -c n | grep -q "^$CONTAINER_NAME$"; then
    echo "❌ 容器 $CONTAINER_NAME 不存在"
    exit 1
fi

# 检查容器是否运行
if ! lxc list --format csv -c ns | grep "^$CONTAINER_NAME" | grep -q "RUNNING"; then
    echo "❌ 容器 $CONTAINER_NAME 未运行"
    exit 1
fi

# 获取容器IP
CONTAINER_IP=$(lxc list --format csv -c n4 | grep "^$CONTAINER_NAME" | cut -d',' -f2 | grep -oE '10\.[0-9]+\.[0-9]+\.[0-9]+' | head -1)

if [ -z "$CONTAINER_IP" ]; then
    echo "❌ 无法获取容器 $CONTAINER_NAME 的IP地址"
    exit 1
fi

echo "容器IP: $CONTAINER_IP"

# 1. 检查iptables规则
echo
echo "=== 1. 检查iptables阻断规则 ==="
BLOCK_RULES=$(iptables -L FORWARD -n | grep "$CONTAINER_IP")
if [ -n "$BLOCK_RULES" ]; then
    echo "✅ 发现阻断规则:"
    echo "$BLOCK_RULES"
else
    echo "❌ 未发现阻断规则"
fi

# 2. 测试容器内网络连通性
echo
echo "=== 2. 测试容器内网络连通性 ==="

# 测试ping
echo "测试ping 8.8.8.8..."
if timeout 10 lxc exec "$CONTAINER_NAME" -- ping -c 3 8.8.8.8 >/dev/null 2>&1; then
    echo "❌ ping测试成功 - 网络未被阻断"
else
    echo "✅ ping测试失败 - 网络已被阻断"
fi

# 测试HTTP连接
echo "测试HTTP连接..."
if timeout 10 lxc exec "$CONTAINER_NAME" -- curl -s --connect-timeout 5 http://www.baidu.com >/dev/null 2>&1; then
    echo "❌ HTTP连接成功 - 网络未被阻断"
else
    echo "✅ HTTP连接失败 - 网络已被阻断"
fi

# 测试DNS解析
echo "测试DNS解析..."
if timeout 10 lxc exec "$CONTAINER_NAME" -- nslookup baidu.com >/dev/null 2>&1; then
    echo "❌ DNS解析成功 - 网络未被阻断"
else
    echo "✅ DNS解析失败 - 网络已被阻断"
fi

# 3. 测试SSH管理功能
echo
echo "=== 3. 测试SSH管理功能 ==="
if lxc exec "$CONTAINER_NAME" -- echo "SSH连接正常" 2>/dev/null; then
    echo "✅ SSH管理功能正常"
else
    echo "❌ SSH管理功能异常"
fi

# 4. 检查容器内进程
echo
echo "=== 4. 检查容器内基本功能 ==="
echo "当前时间: $(lxc exec "$CONTAINER_NAME" -- date 2>/dev/null || echo '无法获取')"
echo "系统负载: $(lxc exec "$CONTAINER_NAME" -- uptime 2>/dev/null || echo '无法获取')"

# 5. 检查端口映射状态
echo
echo "=== 5. 检查端口映射状态 ==="
TOKEN=$(grep '^TOKEN' app.ini | cut -d'=' -f2 | tr -d ' ')
if [ -n "$TOKEN" ]; then
    NAT_RESULT=$(curl -s -H "apikey: $TOKEN" "http://localhost:8060/api/natlist?hostname=$CONTAINER_NAME")
    if echo "$NAT_RESULT" | grep -q '"code":200'; then
        echo "端口映射配置:"
        echo "$NAT_RESULT" | python3 -m json.tool 2>/dev/null || echo "$NAT_RESULT"
    else
        echo "无端口映射或获取失败"
    fi
else
    echo "无法获取API TOKEN"
fi

# 6. 流量管理状态
echo
echo "=== 6. 流量管理状态 ==="
python3 -c "
import sys
sys.path.insert(0, '.')
from flow_limit_enforcer import FlowLimitEnforcer
enforcer = FlowLimitEnforcer()
blocked = enforcer.get_blocked_containers()
found = False
for hostname, limit_gb, blocked_at in blocked:
    if hostname == '$CONTAINER_NAME':
        print(f'✅ 容器在阻断列表中: 限制 {limit_gb}GB, 阻断时间 {blocked_at}')
        found = True
        break
if not found:
    print('❌ 容器不在阻断列表中')
"

echo
echo "=== 测试总结 ==="
echo "如果网络已被正确阻断，应该看到:"
echo "  ✅ 发现阻断规则"
echo "  ✅ ping/HTTP/DNS测试失败"
echo "  ✅ SSH管理功能正常"
echo "  ✅ 容器在阻断列表中"
echo
echo "如果需要解除阻断:"
echo "  lxd-flow-limit unblock $CONTAINER_NAME"
echo
echo "如果需要提高流量限制:"
echo "  python3 batch_update_flow_limit.py update $CONTAINER_NAME 500"
