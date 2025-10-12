#!/bin/bash

# 流量限制执行器部署脚本
# 设置自动检查和执行流量限制

echo "=== 部署流量限制执行器 ==="

# 检查当前目录
if [ ! -f "flow_limit_enforcer.py" ]; then
    echo "❌ 请在server目录下运行此脚本"
    exit 1
fi

# 设置执行权限
chmod +x flow_limit_enforcer.py

# 创建systemd服务文件
echo "创建流量限制执行器服务..."
cat > /etc/systemd/system/lxd-flow-limit-enforcer.service << 'EOF'
[Unit]
Description=LXD Flow Limit Enforcer Service
After=network.target lxd.service lxd-api.service
Wants=lxd.service lxd-api.service

[Service]
Type=oneshot
User=root
Group=root
WorkingDirectory=/root/server
ExecStart=/usr/bin/python3 /root/server/flow_limit_enforcer.py check
StandardOutput=journal
StandardError=journal
SyslogIdentifier=lxd-flow-limit-enforcer

[Install]
WantedBy=multi-user.target
EOF

# 创建定时器文件（每5分钟检查一次）
echo "创建流量限制检查定时器..."
cat > /etc/systemd/system/lxd-flow-limit-enforcer.timer << 'EOF'
[Unit]
Description=LXD Flow Limit Enforcer Timer
Requires=lxd-flow-limit-enforcer.service

[Timer]
OnBootSec=5min
OnUnitActiveSec=5min
Persistent=true

[Install]
WantedBy=timers.target
EOF

# 重新加载systemd配置
systemctl daemon-reload

# 启用并启动定时器
systemctl enable lxd-flow-limit-enforcer.timer
systemctl start lxd-flow-limit-enforcer.timer

# 添加到crontab作为备用（每5分钟检查一次）
echo "添加crontab定时任务..."
(crontab -l 2>/dev/null; echo "*/5 * * * * cd /root/server && python3 flow_limit_enforcer.py check >/dev/null 2>&1") | crontab -

# 创建管理命令
echo "创建流量限制管理命令..."
cat > /usr/local/bin/lxd-flow-limit << 'EOF'
#!/bin/bash

# LXD流量限制管理命令
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
    "check")
        echo "检查并执行流量限制..."
        $PYTHON flow_limit_enforcer.py check
        ;;
    
    "status")
        echo "查看被阻断的容器..."
        $PYTHON flow_limit_enforcer.py status
        ;;
    
    "unblock")
        if [ -z "$2" ]; then
            echo "用法: lxd-flow-limit unblock <容器名>"
            exit 1
        fi
        echo "解除容器 $2 的网络阻断..."
        $PYTHON flow_limit_enforcer.py unblock "$2"
        ;;
    
    "enable")
        echo "启用流量限制自动检查..."
        systemctl enable lxd-flow-limit-enforcer.timer
        systemctl start lxd-flow-limit-enforcer.timer
        echo "✅ 流量限制自动检查已启用"
        ;;
    
    "disable")
        echo "禁用流量限制自动检查..."
        systemctl stop lxd-flow-limit-enforcer.timer
        systemctl disable lxd-flow-limit-enforcer.timer
        echo "✅ 流量限制自动检查已禁用"
        ;;
    
    "logs")
        echo "查看流量限制执行器日志..."
        if [ "$2" = "-f" ]; then
            tail -f flow_limit_enforcer.log
        else
            tail -50 flow_limit_enforcer.log
        fi
        ;;
    
    "timer-status")
        echo "查看定时器状态..."
        systemctl status lxd-flow-limit-enforcer.timer
        echo
        echo "最近的执行记录:"
        journalctl -u lxd-flow-limit-enforcer.service --no-pager -n 10
        ;;
    
    *)
        echo "LXD流量限制管理工具"
        echo
        echo "用法: lxd-flow-limit <command> [args]"
        echo
        echo "流量限制命令:"
        echo "  check                检查并执行流量限制"
        echo "  status               查看被阻断的容器"
        echo "  unblock <容器名>      解除容器网络阻断"
        echo
        echo "系统管理命令:"
        echo "  enable               启用自动流量限制检查"
        echo "  disable              禁用自动流量限制检查"
        echo "  timer-status         查看定时器状态"
        echo "  logs [-f]            查看执行器日志"
        echo
        echo "示例:"
        echo "  lxd-flow-limit check"
        echo "  lxd-flow-limit status"
        echo "  lxd-flow-limit unblock ser123456789"
        echo "  lxd-flow-limit logs -f"
        ;;
esac
EOF

# 设置执行权限
chmod +x /usr/local/bin/lxd-flow-limit

# 测试服务
echo "测试流量限制执行器..."
python3 flow_limit_enforcer.py check

# 显示状态
echo
echo "=== 部署完成 ==="
echo "✅ 流量限制执行器服务已创建"
echo "✅ 定时器已启用（每5分钟检查一次）"
echo "✅ 管理命令已创建: lxd-flow-limit"
echo
echo "管理命令:"
echo "  lxd-flow-limit check        # 立即检查流量限制"
echo "  lxd-flow-limit status       # 查看被阻断的容器"
echo "  lxd-flow-limit unblock <容器名>  # 解除容器阻断"
echo "  lxd-flow-limit timer-status # 查看定时器状态"
echo "  lxd-flow-limit logs -f      # 实时查看日志"
echo
echo "定时器状态:"
systemctl status lxd-flow-limit-enforcer.timer --no-pager -l
echo
echo "⚠️ 重要提示:"
echo "1. 流量限制功能现在已启用，超限容器将被自动断网"
echo "2. 被断网的容器仍可通过SSH(22端口)进行管理"
echo "3. 当流量重置或手动解除阻断后，网络访问将自动恢复"
echo "4. 可以使用 lxd-flow-limit disable 临时禁用自动检查"
