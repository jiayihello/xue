#!/bin/bash

# 创建 lxd-flow-manager 命令脚本

echo "创建 lxd-flow-manager 命令..."

cat > /usr/local/bin/lxd-flow-manager << 'EOF'
#!/bin/bash

# LXD流量管理器命令行工具
# 用法: lxd-flow-manager <command> [args]

SCRIPT_DIR="/root/server"
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
             "http://localhost:8060/api/flow/info?hostname=$2"
        echo
        ;;
    
    "reset")
        if [ -z "$2" ]; then
            echo "用法: lxd-flow-manager reset <容器名>"
            exit 1
        fi
        echo "重置容器 $2 的流量..."
        curl -s -X POST \
             -H "apikey: $(grep '^TOKEN' app.ini | cut -d'=' -f2 | tr -d ' ')" \
             -H "Content-Type: application/json" \
             -d "{\"hostname\":\"$2\"}" \
             "http://localhost:8060/api/flow/reset"
        echo
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
        systemctl status lxd-flow-continuity.service
        echo
        echo "=== 最近日志 ==="
        journalctl -u lxd-flow-continuity.service --no-pager -n 10
        ;;
    
    "daemon-restart")
        echo "重启流量管理守护进程..."
        systemctl restart lxd-flow-continuity.service
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

    *)
        echo "LXD流量管理器 - 命令行工具"
        echo
        echo "用法: lxd-flow-manager <command> [args]"
        echo
        echo "容器管理命令:"
        echo "  info <容器名>        查看容器流量信息"
        echo "  reset <容器名>       重置容器流量"
        echo "  list-usage          列出所有容器已用/剩余/限制"
        echo
        echo "系统管理命令:"
        echo "  register            注册现有容器到流量管理系统"
        echo "  auto-reset          执行自动流量重置"
        echo "  cleanup             清理已删除容器的记录"
        echo "  check-now           立即检查所有容器流量"
        echo
        echo "守护进程管理:"
        echo "  daemon-status       查看守护进程状态"
        echo "  daemon-restart      重启守护进程"
        echo
        echo "示例:"
        echo "  lxd-flow-manager info ser123456789"
        echo "  lxd-flow-manager reset ser123456789"
        echo "  lxd-flow-manager list-usage"
        echo "  lxd-flow-manager register"
        ;;
esac
EOF

# 设置执行权限
chmod +x /usr/local/bin/lxd-flow-manager

echo "✅ lxd-flow-manager 命令创建完成"
echo "现在可以使用: lxd-flow-manager --help"
