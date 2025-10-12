#!/bin/bash

# LXD流量管理器命令行工具 - 改进版
# 用法: lxd-flow-manager <command> [args]

# 自动检测脚本所在目录（工具在 tools/ 子目录，所以需要返回上一级）
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="/usr/bin/python3"

# 检查脚本目录是否存在
if [ ! -d "$SCRIPT_DIR" ]; then
    echo "错误: 脚本目录 $SCRIPT_DIR 不存在"
    exit 1
fi

# 切换到脚本目录
cd "$SCRIPT_DIR"

# 解析命令
case "$1" in
    "info")
        if [ -z "$2" ]; then
            echo "用法: lxd-flow-manager info <容器名>"
            exit 1
        fi
        echo "获取容器 $2 的流量信息..."
        curl -s -H "apikey: $(grep '^TOKEN' app.ini | cut -d'=' -f2 | tr -d ' ')" \
             "http://localhost:8060/api/flow/info?hostname=$2" | python3 -m json.tool
        echo
        ;;
    
    "reset")
        if [ -z "$2" ]; then
            echo "用法: lxd-flow-manager reset <容器名>"
            exit 1
        fi
        echo "⚠️  硬重置容器 $2 的流量（更新重置日期）..."
        curl -s -X POST \
             -H "apikey: $(grep '^TOKEN' app.ini | cut -d'=' -f2 | tr -d ' ')" \
             -H "Content-Type: application/json" \
             -d "{\"hostname\":\"$2\"}" \
             "http://localhost:8060/api/flow/reset" | python3 -m json.tool
        echo
        ;;
    
    "clear")
        if [ -z "$2" ]; then
            echo "用法: lxd-flow-manager clear <容器名>"
            exit 1
        fi
        echo "✨ 清零容器 $2 的流量（保持周期日期）..."
        $PYTHON soft_rebase_baseline.py "$2"
        echo
        echo "验证结果："
        curl -s -H "apikey: $(grep '^TOKEN' app.ini | cut -d'=' -f2 | tr -d ' ')" \
             "http://localhost:8060/api/flow/info?hostname=$2" | python3 -c "
import json, sys
data = json.load(sys.stdin)
if data['code'] == 200:
    usage = data['data'].get('current_usage_gb', 0)
    limit = data['data'].get('flow_limit_gb', 0)
    print(f'✅ 已用流量: {usage} GB / {limit} GB')
else:
    print('❌ 获取信息失败')
"
        ;;
    
    "register")
        echo "注册现有容器到流量管理系统..."
        $PYTHON flow_reset_scheduler.py register
        ;;
    
    "auto-reset")
        echo "执行自动流量重置..."
        $PYTHON flow_reset_scheduler.py reset
        ;;
    
    "cleanup")
        echo "清理已删除容器的记录..."
        $PYTHON flow_reset_scheduler.py cleanup
        ;;
    
    "daemon-status")
        echo "=== 流量管理守护进程状态 ==="
        systemctl status lxd-flow-continuity.service 2>/dev/null || echo "守护进程未安装"
        echo
        echo "=== 最近日志 ==="
        journalctl -u lxd-flow-continuity.service --no-pager -n 10 2>/dev/null || echo "无日志"
        ;;
    
    "daemon-restart")
        echo "重启流量管理守护进程..."
        systemctl restart lxd-flow-continuity.service 2>/dev/null || echo "守护进程未安装"
        echo "守护进程已重启"
        ;;
    
    "check-now")
        echo "立即检查所有容器流量..."
        $PYTHON flow_continuity_daemon.py
        ;;

    "list-usage")
        echo "列出所有容器当前周期流量使用 (已用/剩余/限制) ..."
        $PYTHON list_flow_usage.py
        ;;

    "clear-all")
        echo "⚠️  确认要清零所有容器流量吗？(y/N): "
        read -r confirm
        if [ "$confirm" = "y" ] || [ "$confirm" = "Y" ]; then
            echo "清零所有容器流量..."
            $PYTHON soft_rebase_baseline.py --all
        else
            echo "已取消"
        fi
        ;;

    *)
        echo "=========================================="
        echo "  LXD流量管理器 - 命令行工具 (改进版)"
        echo "=========================================="
        echo
        echo "📊 容器管理命令:"
        echo "  info <容器名>        查看容器流量信息（格式化输出）"
        echo "  clear <容器名>       ✨ 清零容器流量（推荐，流量立即归零）"
        echo "  reset <容器名>       硬重置流量（更新重置日期到下月）"
        echo "  list-usage          列出所有容器已用/剩余/限制"
        echo
        echo "🔧 系统管理命令:"
        echo "  register            注册现有容器到流量管理系统"
        echo "  auto-reset          执行自动流量重置"
        echo "  cleanup             清理已删除容器的记录"
        echo "  check-now           立即检查所有容器流量"
        echo "  clear-all           清零所有容器流量（需确认）"
        echo
        echo "⚙️  守护进程管理:"
        echo "  daemon-status       查看守护进程状态"
        echo "  daemon-restart      重启守护进程"
        echo
        echo "📝 使用示例:"
        echo "  lxd-flow-manager clear XueiV0412    # 清零流量（最常用）"
        echo "  lxd-flow-manager info XueiV0412     # 查看流量信息"
        echo "  lxd-flow-manager list-usage         # 查看所有容器"
        echo
        echo "💡 提示:"
        echo "  - clear: 清零流量但保持周期日期（适合手动清零）"
        echo "  - reset: 更新周期日期到下月（适合月度重置）"
        echo "=========================================="
        ;;
esac

