#!/bin/bash
#===============================================
# 修复流量限制器服务
#===============================================

echo "╔════════════════════════════════════════════╗"
echo "║      修复流量限制器服务                    ║"
echo "╚════════════════════════════════════════════╝"
echo ""

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# 1. 检查当前错误
echo "[1/5] 检查服务错误"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "当前服务状态:"
systemctl status lxd-flow-limit-enforcer --no-pager -l | grep -A 5 "Active:"
echo ""
echo "最近错误:"
journalctl -u lxd-flow-limit-enforcer -n 20 --no-pager | grep -E "Error|error|Failed|failed"
echo ""

# 2. 检查 Python 语法
echo "[2/5] 检查 Python 文件语法"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

if python3 -m py_compile flow_limit_enforcer.py 2>&1; then
    echo "✓ flow_limit_enforcer.py 语法正确"
else
    echo "❌ flow_limit_enforcer.py 有语法错误"
    echo ""
    echo "尝试修复..."
    
    # 备份原文件
    cp flow_limit_enforcer.py flow_limit_enforcer.py.backup-$(date +%Y%m%d_%H%M%S)
    
    # 移除可能的隐藏字符和修复缩进
    python3 << 'PYTHON_FIX'
import sys

try:
    with open('flow_limit_enforcer.py', 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 移除 BOM 和其他隐藏字符
    content = content.replace('\ufeff', '')
    content = content.replace('\r\n', '\n')
    content = content.replace('\r', '\n')
    
    # 写回文件
    with open('flow_limit_enforcer.py', 'w', encoding='utf-8') as f:
        f.write(content)
    
    print("✓ 已清理文件")
    
except Exception as e:
    print(f"❌ 修复失败: {e}")
    sys.exit(1)
PYTHON_FIX

    echo "再次检查语法..."
    if python3 -m py_compile flow_limit_enforcer.py 2>&1; then
        echo "✓ 修复成功"
    else
        echo "❌ 仍有语法错误"
        echo ""
        echo "请查看详细错误信息:"
        python3 flow_limit_enforcer.py check 2>&1 | head -20
        exit 1
    fi
fi
echo ""

# 3. 测试手动执行
echo "[3/5] 测试手动执行"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "尝试手动运行一次..."

if timeout 30 python3 flow_limit_enforcer.py check 2>&1 | head -30; then
    echo ""
    echo "✓ 手动执行成功"
else
    echo ""
    echo "❌ 手动执行失败"
    echo ""
    echo "可能的问题:"
    echo "  1. 数据库文件损坏"
    echo "  2. 依赖模块缺失"
    echo "  3. LXD 连接失败"
    echo ""
    echo "查看完整日志:"
    echo "  python3 flow_limit_enforcer.py check 2>&1 | tee /tmp/enforcer-test.log"
fi
echo ""

# 4. 检查数据库
echo "[4/5] 检查数据库"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

if [ -f "flow_management.db" ]; then
    echo "✓ flow_management.db 存在"
    
    # 检查表
    if sqlite3 flow_management.db "SELECT name FROM sqlite_master WHERE type='table';" 2>&1; then
        echo "✓ 数据库可访问"
        
        # 检查 container_flow_management 表
        if sqlite3 flow_management.db "SELECT COUNT(*) FROM container_flow_management;" >/dev/null 2>&1; then
            CONTAINER_COUNT=$(sqlite3 flow_management.db "SELECT COUNT(*) FROM container_flow_management;")
            echo "✓ container_flow_management 表存在 ($CONTAINER_COUNT 条记录)"
        else
            echo "❌ container_flow_management 表不存在或损坏"
            echo ""
            echo "需要初始化数据库:"
            echo "  python3 flow_manager.py"
        fi
    else
        echo "❌ 数据库损坏"
    fi
else
    echo "❌ flow_management.db 不存在"
    echo ""
    echo "需要初始化数据库:"
    echo "  python3 flow_manager.py"
fi
echo ""

# 5. 重启服务
echo "[5/5] 重启服务"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

read -p "是否重启 lxd-flow-limit-enforcer 服务? [Y/n]: " restart_service

if [[ "${restart_service,,}" =~ ^(y|yes|)$ ]] || [ -z "$restart_service" ]; then
    echo "停止服务..."
    sudo systemctl stop lxd-flow-limit-enforcer 2>/dev/null || true
    
    echo "启动服务..."
    sudo systemctl start lxd-flow-limit-enforcer
    
    sleep 3
    
    echo "检查状态..."
    if systemctl is-active --quiet lxd-flow-limit-enforcer; then
        echo "✅ 服务运行中"
        
        # 启用开机自启
        sudo systemctl enable lxd-flow-limit-enforcer >/dev/null 2>&1
        echo "✓ 已设置开机自启"
        
        echo ""
        echo "查看实时日志:"
        echo "  journalctl -u lxd-flow-limit-enforcer -f"
    else
        echo "❌ 服务启动失败"
        echo ""
        echo "查看错误:"
        systemctl status lxd-flow-limit-enforcer --no-pager -l | tail -20
        echo ""
        journalctl -u lxd-flow-limit-enforcer -n 50 --no-pager
    fi
else
    echo "跳过重启"
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "完成"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "后续操作:"
echo "  1. 查看服务状态: systemctl status lxd-flow-limit-enforcer"
echo "  2. 查看日志: tail -f flow_limit_enforcer.log"
echo "  3. 手动检查: python3 flow_limit_enforcer.py check"
echo "  4. 查看被阻断容器: python3 flow_limit_enforcer.py status"

