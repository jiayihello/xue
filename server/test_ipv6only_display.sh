#!/bin/bash
#===============================================
# IPv6-Only 模式显示修复验证脚本
#===============================================

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo -e "\n${CYAN}=========================================="
echo -e "  IPv6-Only 显示修复验证工具"
echo -e "==========================================${NC}\n"

# 读取配置
get_config() {
    local key=$1
    grep "^$key\s*=" app.ini 2>/dev/null | cut -d'=' -f2 | tr -d ' ' || echo "未设置"
}

# 检查配置
echo -e "${CYAN}[1/5] 检查配置文件${NC}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

HTTP_PORT=$(get_config "HTTP_PORT")
TOKEN=$(get_config "TOKEN")
IPV4_MODE=$(get_config "IPV4_MODE")
IPV6_MODE=$(get_config "IPV6_MODE")

echo "  HTTP_PORT: $HTTP_PORT"
echo "  TOKEN: $TOKEN"
echo "  IPV4_MODE: ${IPV4_MODE:-BRIDGE (默认)}"
echo "  IPV6_MODE: ${IPV6_MODE:-OFF}"

if [ "$IPV4_MODE" = "OFF" ]; then
    echo -e "${GREEN}  ✓ IPv6-Only 模式已启用${NC}"
else
    echo -e "${YELLOW}  ! 当前为双栈模式，IPv4_MODE=${IPV4_MODE:-BRIDGE}${NC}"
fi

# 检查服务
echo -e "\n${CYAN}[2/5] 检查后端服务${NC}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

if systemctl is-active --quiet lxd-api.service; then
    echo -e "${GREEN}  ✓ 后端服务运行中${NC}"
else
    echo -e "${RED}  ✗ 后端服务未运行${NC}"
    echo -e "${YELLOW}  请先启动: systemctl start lxd-api.service${NC}"
    exit 1
fi

# 测试 API 连接
echo -e "\n${CYAN}[3/5] 测试 API 连接${NC}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

API_URL="http://127.0.0.1:${HTTP_PORT:-8060}/api/check"
RESPONSE=$(curl -s -H "apikey: $TOKEN" "$API_URL")

if echo "$RESPONSE" | grep -q "API连接正常"; then
    echo -e "${GREEN}  ✓ API 连接正常${NC}"
else
    echo -e "${RED}  ✗ API 连接失败${NC}"
    echo "  响应: $RESPONSE"
    exit 1
fi

# 选择测试容器
echo -e "\n${CYAN}[4/5] 选择测试容器${NC}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# 获取容器列表
CONTAINERS=$(lxc list -c n --format csv 2>/dev/null)

if [ -z "$CONTAINERS" ]; then
    echo -e "${YELLOW}  ! 没有找到运行中的容器${NC}"
    echo -e "${YELLOW}  请先创建一个测试容器${NC}"
    exit 0
fi

echo "可用容器:"
i=1
while IFS= read -r container; do
    echo "  $i) $container"
    i=$((i+1))
done <<< "$CONTAINERS"

echo ""
read -p "请选择容器编号 [1]: " choice
choice=${choice:-1}

# 获取选中的容器名
CONTAINER_NAME=$(echo "$CONTAINERS" | sed -n "${choice}p")

if [ -z "$CONTAINER_NAME" ]; then
    echo -e "${RED}  ✗ 无效选择${NC}"
    exit 1
fi

echo -e "${GREEN}  ✓ 已选择: $CONTAINER_NAME${NC}"

# 测试 API 返回
echo -e "\n${CYAN}[5/5] 测试 API 返回数据${NC}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

API_URL="http://127.0.0.1:${HTTP_PORT:-8060}/api/getinfo?hostname=${CONTAINER_NAME}"
RESPONSE=$(curl -s -H "apikey: $TOKEN" "$API_URL")

# 提取关键字段
IPV4_MODE_RESPONSE=$(echo "$RESPONSE" | grep -oP '"IPv4Mode"\s*:\s*"\K[^"]+' || echo "未返回")
IPV6_MODE_RESPONSE=$(echo "$RESPONSE" | grep -oP '"IPv6Mode"\s*:\s*"\K[^"]+' || echo "未返回")
PUBLIC_IPV4=$(echo "$RESPONSE" | grep -oP '"PublicIPv4"\s*:\s*(["]([^"]+)["]|null)' | cut -d'"' -f3)
IPV6_LIST=$(echo "$RESPONSE" | grep -oP '"IPv6List"\s*:\s*\[\K[^\]]+' || echo "")

echo ""
echo "API 返回数据:"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  容器名: $CONTAINER_NAME"
echo "  IPv4Mode: $IPV4_MODE_RESPONSE"
echo "  IPv6Mode: $IPV6_MODE_RESPONSE"
echo "  PublicIPv4: ${PUBLIC_IPV4:-null}"
echo "  IPv6List: [$IPV6_LIST]"
echo ""

# 验证结果
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "验证结果:"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

PASS=0
FAIL=0

# 检查 IPv4Mode 字段
if [ "$IPV4_MODE_RESPONSE" != "未返回" ]; then
    echo -e "${GREEN}  ✓ API 返回 IPv4Mode 字段${NC}"
    PASS=$((PASS+1))
else
    echo -e "${RED}  ✗ API 未返回 IPv4Mode 字段${NC}"
    echo -e "${YELLOW}    请确认后端代码已更新${NC}"
    FAIL=$((FAIL+1))
fi

# 检查 IPv6-Only 模式逻辑
if [ "$IPV4_MODE" = "OFF" ]; then
    echo ""
    echo "IPv6-Only 模式验证:"
    
    if [ "$IPV4_MODE_RESPONSE" = "OFF" ]; then
        echo -e "${GREEN}  ✓ IPv4Mode 正确返回 OFF${NC}"
        PASS=$((PASS+1))
    else
        echo -e "${RED}  ✗ IPv4Mode 应返回 OFF，实际: $IPV4_MODE_RESPONSE${NC}"
        FAIL=$((FAIL+1))
    fi
    
    if [ -z "$PUBLIC_IPV4" ] || [ "$PUBLIC_IPV4" = "null" ]; then
        echo -e "${GREEN}  ✓ PublicIPv4 正确返回 null（无 IPv4）${NC}"
        PASS=$((PASS+1))
    else
        echo -e "${RED}  ✗ PublicIPv4 应返回 null，实际: $PUBLIC_IPV4${NC}"
        echo -e "${YELLOW}    魔方将显示此 IP，造成误导${NC}"
        FAIL=$((FAIL+1))
    fi
    
    if [ -n "$IPV6_LIST" ]; then
        echo -e "${GREEN}  ✓ IPv6List 有数据${NC}"
        PASS=$((PASS+1))
    else
        echo -e "${YELLOW}  ! IPv6List 为空，容器可能未配置 IPv6${NC}"
    fi
fi

# 双栈模式验证
if [ "$IPV4_MODE" = "BRIDGE" ] || [ -z "$IPV4_MODE" ]; then
    echo ""
    echo "双栈模式验证:"
    
    if [ "$IPV4_MODE_RESPONSE" = "BRIDGE" ]; then
        echo -e "${GREEN}  ✓ IPv4Mode 正确返回 BRIDGE${NC}"
        PASS=$((PASS+1))
    else
        echo -e "${YELLOW}  ! IPv4Mode 返回: $IPV4_MODE_RESPONSE${NC}"
    fi
    
    if [ -n "$PUBLIC_IPV4" ] && [ "$PUBLIC_IPV4" != "null" ]; then
        echo -e "${GREEN}  ✓ PublicIPv4 有值: $PUBLIC_IPV4${NC}"
        PASS=$((PASS+1))
    else
        echo -e "${YELLOW}  ! PublicIPv4 为空，检查配置${NC}"
    fi
fi

# 总结
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "测试总结:"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo -e "${GREEN}  通过: $PASS${NC}"
echo -e "${RED}  失败: $FAIL${NC}"
echo ""

if [ $FAIL -eq 0 ]; then
    echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${GREEN}✓ 后端修复验证通过！${NC}"
    echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo ""
    echo "下一步:"
    echo "  1. 修改魔方插件 lxdserver.php（参考文档）"
    echo "  2. 在魔方前台测试容器详情页显示"
    echo "  3. 验证 IP 地址是否显示为 '仅 IPv6'"
    echo ""
else
    echo -e "${RED}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${RED}✗ 发现问题，需要修复${NC}"
    echo -e "${RED}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo ""
    echo "排查步骤:"
    echo "  1. 确认 lxc_manager.py 已更新（第 350-377 行）"
    echo "  2. 重启后端服务: systemctl restart lxd-api.service"
    echo "  3. 重新运行此脚本测试"
    echo ""
fi

# 显示完整 API 响应（可选）
echo ""
read -p "是否显示完整 API 响应? [y/N]: " show_full
if [[ "${show_full,,}" == "y" ]]; then
    echo ""
    echo "完整 API 响应:"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "$RESPONSE" | python3 -m json.tool 2>/dev/null || echo "$RESPONSE"
    echo ""
fi

echo ""

