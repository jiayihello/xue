#!/bin/bash

# 生产环境流量管理部署脚本

set -e

echo "=========================================="
echo "  生产环境流量管理系统部署"
echo "=========================================="

# 检查是否为root用户
if [ "$EUID" -ne 0 ]; then
    echo "❌ 请使用root权限运行此脚本"
    exit 1
fi

# 获取脚本所在目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# 环境检测
echo "检测生产环境..."

# 检测容器数量
CONTAINER_COUNT=$(lxc list --format csv | wc -l)
echo "检测到 $CONTAINER_COUNT 个容器"

# 根据容器数量推荐配置
if [ "$CONTAINER_COUNT" -lt 10 ]; then
    RECOMMENDED_INTERVAL=180  # 3分钟
    SCALE="小规模"
elif [ "$CONTAINER_COUNT" -lt 50 ]; then
    RECOMMENDED_INTERVAL=300  # 5分钟
    SCALE="中等规模"
else
    RECOMMENDED_INTERVAL=600  # 10分钟
    SCALE="大规模"
fi

echo "检测到 $SCALE 环境，推荐检查间隔: ${RECOMMENDED_INTERVAL}秒"

# 询问用户配置
read -p "是否使用推荐配置? (Y/n): " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Nn]$ ]]; then
    CHECK_INTERVAL=$RECOMMENDED_INTERVAL
else
    while true; do
        read -p "请输入检查间隔(秒，建议不少于180): " CHECK_INTERVAL
        if [[ "$CHECK_INTERVAL" =~ ^[0-9]+$ ]]; then
            if [ "$CHECK_INTERVAL" -lt 180 ]; then
                echo "⚠️  警告: 检查间隔过短可能影响性能"
            fi
            break
        else
            echo "❌ 请输入有效的数字"
        fi
    done
fi

# 创建生产环境配置
echo "创建生产环境配置..."
cat > production_flow.env << EOF
# 生产环境流量管理配置
FLOW_DAEMON_ENABLED=true
FLOW_DAEMON_INTERVAL=$CHECK_INTERVAL
FLOW_EVENT_MONITOR_ENABLED=false
FLOW_LOG_LEVEL=INFO
FLOW_BATCH_SIZE=10
FLOW_HEALTH_CHECK=true
EOF

echo "✅ 配置文件已创建: production_flow.env"

# 运行标准安装
echo "执行标准安装..."
bash setup_flow_management.sh

# 优化systemd服务配置
echo "优化systemd服务配置..."
cat > /etc/systemd/system/lxd-flow-continuity.service << EOF
[Unit]
Description=LXD Flow Continuity Daemon (Production)
After=network.target lxd.service
Wants=lxd.service
StartLimitIntervalSec=300
StartLimitBurst=3

[Service]
Type=simple
User=root
WorkingDirectory=$SCRIPT_DIR
EnvironmentFile=$SCRIPT_DIR/production_flow.env
ExecStart=/usr/bin/python3 $SCRIPT_DIR/flow_continuity_daemon.py --daemon --interval $CHECK_INTERVAL
ExecReload=/bin/kill -HUP \$MAINPID
Restart=always
RestartSec=30
TimeoutStartSec=60
TimeoutStopSec=30

# 资源限制
MemoryMax=256M
CPUQuota=10%

# 安全设置
NoNewPrivileges=true
ProtectSystem=false
ProtectHome=false
ReadWritePaths=$SCRIPT_DIR

# 日志设置
StandardOutput=journal
StandardError=journal
SyslogIdentifier=lxd-flow-continuity

[Install]
WantedBy=multi-user.target
EOF

# 重新加载并启动服务
systemctl daemon-reload
systemctl enable lxd-flow-continuity.service
systemctl restart lxd-flow-continuity.service

# 等待服务启动
sleep 5

# 检查服务状态
if systemctl is-active --quiet lxd-flow-continuity.service; then
    echo "✅ 生产环境流量管理服务已启动"
else
    echo "❌ 服务启动失败"
    systemctl status lxd-flow-continuity.service
    exit 1
fi

# 设置日志轮转
echo "设置日志轮转..."
cat > /etc/logrotate.d/lxd-flow-management << EOF
$SCRIPT_DIR/*.log {
    daily
    rotate 7
    compress
    delaycompress
    missingok
    notifempty
    create 644 root root
    postrotate
        systemctl reload lxd-flow-continuity.service > /dev/null 2>&1 || true
    endscript
}
EOF

# 创建监控脚本
echo "创建监控脚本..."
cat > /usr/local/bin/lxd-flow-monitor << 'EOF'
#!/bin/bash

# 流量管理系统监控脚本

echo "=== LXD流量管理系统状态 ==="
echo

# 服务状态
echo "1. 服务状态:"
systemctl is-active lxd-flow-continuity.service && echo "✅ 守护进程运行正常" || echo "❌ 守护进程异常"

# 最近日志
echo
echo "2. 最近日志 (最后10行):"
journalctl -u lxd-flow-continuity.service -n 10 --no-pager

# 数据库状态
echo
echo "3. 数据库状态:"
if [ -f "flow_management.db" ]; then
    CONTAINER_COUNT=$(sqlite3 flow_management.db "SELECT COUNT(*) FROM container_flow_management;" 2>/dev/null || echo "0")
    echo "✅ 数据库正常，管理 $CONTAINER_COUNT 个容器"
else
    echo "❌ 数据库文件不存在"
fi

# 磁盘使用
echo
echo "4. 磁盘使用:"
du -sh *.db *.log 2>/dev/null || echo "无日志文件"

echo
echo "=== 监控完成 ==="
EOF

chmod +x /usr/local/bin/lxd-flow-monitor

# 设置监控定时任务
echo "设置监控定时任务..."
CURRENT_CRONTAB=$(crontab -l 2>/dev/null || echo "")
MONITOR_JOB="0 */6 * * * /usr/local/bin/lxd-flow-monitor >> /var/log/lxd-flow-monitor.log 2>&1"

if echo "$CURRENT_CRONTAB" | grep -q "lxd-flow-monitor"; then
    echo "⚠️  监控定时任务已存在，跳过添加"
else
    (echo "$CURRENT_CRONTAB"; echo "$MONITOR_JOB") | crontab -
    echo "✅ 监控定时任务已添加"
fi

echo
echo "=========================================="
echo "  生产环境部署完成！"
echo "=========================================="

# 最终验证
echo ""
echo "### 最终验证 ###"
echo ""

VERIFICATION_PASSED=true

# 1. 验证服务
echo "1. 验证服务..."
if systemctl is-active --quiet lxd-flow-continuity.service; then
    echo "   ✅ 守护进程正在运行"
else
    echo "   ❌ 守护进程未运行"
    VERIFICATION_PASSED=false
fi

# 2. 验证定时任务
echo "2. 验证定时任务..."
FINAL_CRONTAB=$(crontab -l 2>/dev/null || echo "")
RESET_COUNT=$(echo "$FINAL_CRONTAB" | grep -c "flow_reset_scheduler.py reset")
CLEANUP_COUNT=$(echo "$FINAL_CRONTAB" | grep -c "flow_reset_scheduler.py cleanup")
MONITOR_COUNT=$(echo "$FINAL_CRONTAB" | grep -c "lxd-flow-monitor")

echo "   流量重置任务: $RESET_COUNT 条"
echo "   清理任务: $CLEANUP_COUNT 条"
echo "   监控任务: $MONITOR_COUNT 条"

if [ "$RESET_COUNT" -ge 1 ] && [ "$CLEANUP_COUNT" -ge 1 ]; then
    echo "   ✅ 所有定时任务已配置"
else
    echo "   ❌ 定时任务配置不完整"
    VERIFICATION_PASSED=false
fi

# 3. 验证配置文件
echo "3. 验证配置文件..."
if [ -f "production_flow.env" ]; then
    echo "   ✅ 生产环境配置文件存在"
else
    echo "   ❌ 配置文件不存在"
    VERIFICATION_PASSED=false
fi

# 4. 验证日志轮转
echo "4. 验证日志轮转..."
if [ -f "/etc/logrotate.d/lxd-flow-management" ]; then
    echo "   ✅ 日志轮转已配置"
else
    echo "   ⚠️  日志轮转未配置"
fi

# 5. 验证监控脚本
echo "5. 验证监控脚本..."
if [ -x "/usr/local/bin/lxd-flow-monitor" ]; then
    echo "   ✅ 监控脚本已安装"
else
    echo "   ❌ 监控脚本未安装或无执行权限"
    VERIFICATION_PASSED=false
fi

echo ""
if [ "$VERIFICATION_PASSED" = true ]; then
    echo "=========================================="
    echo "  ✅ 所有验证通过！部署成功！"
    echo "=========================================="
else
    echo "=========================================="
    echo "  ⚠️  部分验证失败，请检查错误信息"
    echo "=========================================="
    echo "  可以运行诊断脚本进行修复："
    echo "  python3 diagnose_flow_management.py"
    echo "=========================================="
fi

echo
echo "配置信息:"
echo "  规模: $SCALE ($CONTAINER_COUNT 个容器)"
echo "  检查间隔: ${CHECK_INTERVAL}秒"
echo "  日志级别: INFO"
echo "  资源限制: 内存256MB, CPU 10%"
echo
echo "管理命令:"
echo "  systemctl status lxd-flow-continuity    # 查看服务状态"
echo "  journalctl -u lxd-flow-continuity -f    # 查看实时日志"
echo "  lxd-flow-monitor                        # 运行监控检查"
echo "  lxd-flow-manager daemon-status          # 详细状态"
echo "  python3 diagnose_flow_management.py     # 运行系统诊断"
echo
echo "监控:"
echo "  日志轮转: 每日轮转，保留7天"
echo "  自动监控: 每6小时运行一次"
echo "  监控日志: /var/log/lxd-flow-monitor.log"
echo
echo "定时任务:"
echo "  每天凌晨2点: 自动重置到期容器流量"
echo "  每周日凌晨3点: 自动清理已删除容器记录"
echo "  每6小时: 运行系统监控检查"
echo
echo "注意事项:"
echo "  ⚠️  生产环境已禁用事件监听以确保稳定性"
echo "  ⚠️  如需调整配置，请编辑 production_flow.env"
echo "  ⚠️  重启服务: systemctl restart lxd-flow-continuity"
echo
