#!/bin/bash
# IPv6 手动分配 - 快速配置脚本
# 使用方法：sudo bash ipv6_quick_start.sh

set -e

echo "=========================================="
echo "  IPv6 手动分配 - 快速配置向导"
echo "=========================================="
echo ""

# 检查权限
if [ "$EUID" -ne 0 ]; then
    echo "[✗] 请使用 root 权限运行此脚本"
    echo "    sudo bash ipv6_quick_start.sh"
    exit 1
fi

# 获取脚本目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# 检查配置文件
if [ ! -f "app.ini" ]; then
    echo "[✗] 未找到 app.ini 配置文件"
    echo "    请先复制: cp app.ini.example app.ini"
    exit 1
fi

echo "请选择配置方式："
echo ""
echo "  1) 配置地址池（推荐）- 自动从预定义地址中分配"
echo "  2) 手动为容器分配 IPv6"
echo "  3) 查看当前分配情况"
echo "  4) 启动交互式管理工具"
echo "  0) 退出"
echo ""
read -p "请选择 [0-4]: " choice

case $choice in
    1)
        echo ""
        echo "=========================================="
        echo "  配置地址池"
        echo "=========================================="
        echo ""
        echo "请输入你的 IPv6 地址（每行一个，输入空行结束）："
        echo "示例："
        echo "  2001:db8:1234::1"
        echo "  2001:db8:1234::2"
        echo "  2001:db8:1234::3"
        echo ""
        
        addresses=()
        while true; do
            read -p "IPv6 地址 $(( ${#addresses[@]} + 1 )): " addr
            
            if [ -z "$addr" ]; then
                break
            fi
            
            addresses+=("$addr")
        done
        
        if [ ${#addresses[@]} -eq 0 ]; then
            echo ""
            echo "[!] 未输入任何地址，退出"
            exit 0
        fi
        
        # 生成地址池字符串
        pool_str=$(IFS=", "; echo "${addresses[*]}")
        
        echo ""
        echo "将配置以下地址池（共 ${#addresses[@]} 个地址）："
        echo "$pool_str"
        echo ""
        read -p "确认写入 app.ini? [y/N]: " confirm
        
        if [ "$confirm" != "y" ] && [ "$confirm" != "Y" ]; then
            echo "已取消"
            exit 0
        fi
        
        # 更新 app.ini
        if grep -q "^IPV6_ADDRESS_POOL" app.ini; then
            # 替换现有配置
            sed -i "s/^IPV6_ADDRESS_POOL.*/IPV6_ADDRESS_POOL = $pool_str/" app.ini
        else
            # 添加新配置
            echo "" >> app.ini
            echo "# IPv6 地址池" >> app.ini
            echo "IPV6_ADDRESS_POOL = $pool_str" >> app.ini
        fi
        
        # 确保 IPv6 模式为 ROUTED
        if ! grep -q "^IPV6_MODE.*ROUTED" app.ini; then
            echo ""
            echo "[!] 检测到 IPV6_MODE 不是 ROUTED，是否更改? [y/N]: "
            read -p "" set_mode
            
            if [ "$set_mode" = "y" ] || [ "$set_mode" = "Y" ]; then
                sed -i "s/^IPV6_MODE.*/IPV6_MODE = ROUTED/" app.ini
                echo "[✓] 已设置 IPV6_MODE = ROUTED"
            fi
        fi
        
        echo ""
        echo "[✓] 地址池配置完成！"
        echo ""
        echo "下一步："
        echo "  1. 重启后端服务: systemctl restart lxd-api.service"
        echo "  2. 创建容器时会自动从地址池分配"
        echo ""
        ;;
    
    2)
        echo ""
        echo "=========================================="
        echo "  手动为容器分配 IPv6"
        echo "=========================================="
        echo ""
        
        # 列出现有容器
        echo "现有容器："
        lxc list -c n,s --format csv | awk -F',' '{printf "  - %s (%s)\n", $1, $2}'
        echo ""
        
        read -p "请输入容器名: " container_name
        
        if [ -z "$container_name" ]; then
            echo "[!] 容器名不能为空"
            exit 1
        fi
        
        # 检查容器是否存在
        if ! lxc list -c n --format csv | grep -q "^${container_name}$"; then
            echo "[✗] 容器 $container_name 不存在"
            exit 1
        fi
        
        read -p "请输入 IPv6 地址: " ipv6_addr
        
        if [ -z "$ipv6_addr" ]; then
            echo "[!] IPv6 地址不能为空"
            exit 1
        fi
        
        echo ""
        echo "将为容器 $container_name 配置 IPv6: $ipv6_addr"
        read -p "确认? [y/N]: " confirm
        
        if [ "$confirm" != "y" ] && [ "$confirm" != "Y" ]; then
            echo "已取消"
            exit 0
        fi
        
        # 获取主网卡
        main_if=$(grep "^MAIN_INTERFACE" app.ini | cut -d'=' -f2 | tr -d ' ')
        if [ -z "$main_if" ]; then
            main_if="eth0"
        fi
        
        # 添加 IPv6 网卡
        echo ""
        echo "[*] 正在配置..."
        
        lxc config device remove "$container_name" eth0v6 2>/dev/null || true
        lxc config device add "$container_name" eth0v6 nic \
            nictype=routed \
            parent="$main_if" \
            ipv6.address="$ipv6_addr"
        
        echo "[✓] 已添加 IPv6 网卡"
        
        # 添加 NDP 代理
        ip -6 neigh add proxy "${ipv6_addr%%/*}" dev "$main_if" 2>/dev/null || \
            echo "[i] NDP 代理已存在（正常）"
        
        echo "[✓] 已配置 NDP 代理"
        
        # 记录到分配文件（如果使用了管理工具）
        if [ -f "ipv6_allocations.json" ]; then
            python3 - << EOF
import json
alloc_file = 'ipv6_allocations.json'
try:
    with open(alloc_file, 'r') as f:
        data = json.load(f)
except:
    data = {'allocations': {}, 'cursor': 0}

data['allocations']['$container_name'] = '$ipv6_addr'

with open(alloc_file, 'w') as f:
    json.dump(data, f, indent=2)

print("[✓] 已更新分配记录")
EOF
        fi
        
        echo ""
        echo "[✓] 配置完成！"
        echo ""
        echo "验证连通性："
        echo "  lxc exec $container_name -- ip -6 addr show"
        echo "  lxc exec $container_name -- ping6 -c 3 google.com"
        echo ""
        ;;
    
    3)
        echo ""
        echo "=========================================="
        echo "  当前 IPv6 分配情况"
        echo "=========================================="
        echo ""
        
        if [ -f "manage_ipv6.py" ]; then
            python3 manage_ipv6.py list
        else
            # 手动显示
            echo "容器 IPv6 配置："
            echo ""
            lxc list -c n,devices.eth0v6.ipv6.address --format csv | \
                awk -F',' '{if ($2 != "") printf "  %-30s %s\n", $1, $2}'
            echo ""
            
            if [ -f "ipv6_allocations.json" ]; then
                echo "分配记录："
                python3 -c "import json; data=json.load(open('ipv6_allocations.json')); print('\n'.join(f'  {k}: {v}' for k,v in data.get('allocations', {}).items()))"
                echo ""
            fi
        fi
        ;;
    
    4)
        echo ""
        if [ -f "manage_ipv6.py" ]; then
            python3 manage_ipv6.py
        else
            echo "[✗] 未找到 manage_ipv6.py 管理工具"
            exit 1
        fi
        ;;
    
    0)
        echo ""
        echo "再见！"
        echo ""
        exit 0
        ;;
    
    *)
        echo ""
        echo "[!] 无效选择"
        exit 1
        ;;
esac

