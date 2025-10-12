#!/bin/bash

# 流量管理功能安装脚本

set -e

echo "=========================================="
echo "  ZJMF-LXD-Server 流量管理功能安装脚本"
echo "=========================================="

# 检查是否为root用户
if [ "$EUID" -ne 0 ]; then
    echo "❌ 请使用root权限运行此脚本"
    echo "sudo bash setup_flow_management.sh"
    exit 1
fi

# 获取脚本所在目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "当前工作目录: $SCRIPT_DIR"

# 检查必要文件是否存在
echo "检查必要文件..."
required_files=(
    "flow_manager.py"
    "flow_reset_scheduler.py"
    "create_flow_management_table.sql"
    "flow_continuity_daemon.py"
    "production_flow_config.py"
)

for file in "${required_files[@]}"; do
    if [ ! -f "$file" ]; then
        echo "❌ 缺少必要文件: $file"
        exit 1
    fi
    echo "✅ 找到文件: $file"
done

# 安装Python依赖
echo "安装Python依赖..."
pip3 install python-dateutil sqlite3 2>/dev/null || {
    echo "⚠️  部分依赖可能已安装，继续..."
}

# 初始化/升级数据库
echo "初始化/升级流量管理数据库..."

# 检查并运行数据库升级工具（如果存在）
if [ -f "tools/upgrade_flow_database.py" ]; then
    echo "运行数据库升级工具..."
    python3 tools/upgrade_flow_database.py
elif [ -f "upgrade_flow_database.py" ]; then
    echo "运行数据库升级工具..."
    python3 upgrade_flow_database.py
fi

python3 -c "
from flow_manager import FlowManager
fm = FlowManager()
print('✅ 流量管理数据库初始化完成')
"

# 注册现有容器
echo "注册现有容器到流量管理系统..."
python3 flow_reset_scheduler.py register

# 设置流量连续性守护进程
echo "设置流量连续性守护进程..."
python3 flow_continuity_daemon.py --create-service

# 启用并启动守护进程
systemctl daemon-reload
systemctl enable lxd-flow-continuity.service
systemctl start lxd-flow-continuity.service

if systemctl is-active --quiet lxd-flow-continuity.service; then
    echo "✅ 流量连续性守护进程已启动"
else
    echo "⚠️  流量连续性守护进程启动失败，请检查日志"
fi

# 设置定时任务
echo "设置流量重置定时任务..."

# 获取当前 crontab 内容
CURRENT_CRONTAB=$(crontab -l 2>/dev/null || echo "")

# 检查并添加 reset 定时任务
RESET_JOB="0 2 * * * /usr/bin/python3 $SCRIPT_DIR/flow_reset_scheduler.py reset >/dev/null 2>&1"
if echo "$CURRENT_CRONTAB" | grep -q "flow_reset_scheduler.py reset"; then
    echo "⚠️  流量重置定时任务已存在，跳过添加"
else
    echo "添加流量重置定时任务..."
    (echo "$CURRENT_CRONTAB"; echo "$RESET_JOB") | crontab -
    if [ $? -eq 0 ]; then
        echo "✅ 已添加流量重置定时任务（每天凌晨2点执行）"
    else
        echo "❌ 添加流量重置定时任务失败"
        exit 1
    fi
fi

# 重新获取当前 crontab（因为可能已更新）
CURRENT_CRONTAB=$(crontab -l 2>/dev/null || echo "")

# 检查并添加 cleanup 定时任务
CLEANUP_JOB="0 3 * * 0 /usr/bin/python3 $SCRIPT_DIR/flow_reset_scheduler.py cleanup >/dev/null 2>&1"
if echo "$CURRENT_CRONTAB" | grep -q "flow_reset_scheduler.py cleanup"; then
    echo "⚠️  清理定时任务已存在，跳过添加"
else
    echo "添加清理定时任务..."
    (echo "$CURRENT_CRONTAB"; echo "$CLEANUP_JOB") | crontab -
    if [ $? -eq 0 ]; then
        echo "✅ 已添加清理任务（每周日凌晨3点执行）"
    else
        echo "❌ 添加清理任务失败"
        exit 1
    fi
fi

# 验证定时任务是否真的添加成功
echo ""
echo "验证定时任务..."
FINAL_CRONTAB=$(crontab -l 2>/dev/null || echo "")
RESET_COUNT=$(echo "$FINAL_CRONTAB" | grep -c "flow_reset_scheduler.py reset")
CLEANUP_COUNT=$(echo "$FINAL_CRONTAB" | grep -c "flow_reset_scheduler.py cleanup")

if [ "$RESET_COUNT" -gt 0 ] && [ "$CLEANUP_COUNT" -gt 0 ]; then
    echo "✅ 定时任务验证成功"
    echo "   - 流量重置任务: $RESET_COUNT 条"
    echo "   - 清理任务: $CLEANUP_COUNT 条"
else
    echo "❌ 定时任务验证失败"
    echo "   - 流量重置任务: $RESET_COUNT 条（期望 ≥1）"
    echo "   - 清理任务: $CLEANUP_COUNT 条（期望 ≥1）"
    exit 1
fi

# 创建流量管理脚本的快捷命令
echo "创建管理命令..."
cat > /usr/local/bin/lxd-flow-manager << EOF
#!/bin/bash
# LXD流量管理工具

SCRIPT_DIR="$SCRIPT_DIR"

case "\$1" in
    "reset")
        if [ -z "\$2" ]; then
            echo "用法: lxd-flow-manager reset <容器名>"
            exit 1
        fi
        echo "重置容器 \$2 的流量..."
        curl -X POST -H "apikey: \$(grep TOKEN \$SCRIPT_DIR/app.ini | cut -d'=' -f2 | tr -d ' ')" \\
             -H "Content-Type: application/json" \\
             -d "{\"hostname\": \"\$2\"}" \\
             http://localhost:\$(grep HTTP_PORT \$SCRIPT_DIR/app.ini | cut -d'=' -f2 | tr -d ' ')/api/flow/reset
        ;;
    "info")
        if [ -z "\$2" ]; then
            echo "用法: lxd-flow-manager info <容器名>"
            exit 1
        fi
        echo "获取容器 \$2 的流量信息..."
        curl -H "apikey: \$(grep TOKEN \$SCRIPT_DIR/app.ini | cut -d'=' -f2 | tr -d ' ')" \\
             "http://localhost:\$(grep HTTP_PORT \$SCRIPT_DIR/app.ini | cut -d'=' -f2 | tr -d ' ')/api/flow/info?hostname=\$2"
        ;;
    "auto-reset")
        echo "执行自动流量重置..."
        python3 \$SCRIPT_DIR/flow_reset_scheduler.py reset
        ;;
    "register")
        echo "注册现有容器到流量管理系统..."
        python3 \$SCRIPT_DIR/flow_reset_scheduler.py register
        ;;
    "cleanup")
        echo "清理已删除容器的流量管理记录..."
        python3 \$SCRIPT_DIR/flow_reset_scheduler.py cleanup
        ;;
    "test")
        echo "运行流量连续性测试..."
        if [ -f "\$SCRIPT_DIR/tools/test_flow_continuity.py" ]; then
            python3 \$SCRIPT_DIR/tools/test_flow_continuity.py
        elif [ -f "\$SCRIPT_DIR/test_flow_continuity.py" ]; then
            python3 \$SCRIPT_DIR/test_flow_continuity.py
        else
            echo "❌ 未找到测试脚本"
            exit 1
        fi
        ;;
    "upgrade-db")
        echo "升级流量管理数据库..."
        if [ -f "\$SCRIPT_DIR/tools/upgrade_flow_database.py" ]; then
            python3 \$SCRIPT_DIR/tools/upgrade_flow_database.py
        elif [ -f "\$SCRIPT_DIR/upgrade_flow_database.py" ]; then
            python3 \$SCRIPT_DIR/upgrade_flow_database.py
        else
            echo "❌ 未找到数据库升级工具"
            exit 1
        fi
        ;;
    "daemon-status")
        echo "检查流量连续性守护进程状态..."
        systemctl status lxd-flow-continuity.service
        ;;
    "daemon-restart")
        echo "重启流量连续性守护进程..."
        systemctl restart lxd-flow-continuity.service
        ;;
    "check-now")
        echo "立即检查所有容器流量状态..."
        python3 \$SCRIPT_DIR/flow_continuity_daemon.py
        ;;
    "list-usage")
        echo "列出所有容器当前周期流量使用 (已用/剩余/限制) ..."
        python3 \$SCRIPT_DIR/list_flow_usage.py
        ;;
    *)
        echo "LXD流量管理工具"
        echo ""
        echo "用法:"
        echo "  lxd-flow-manager reset <容器名>     # 手动重置指定容器流量"
        echo "  lxd-flow-manager info <容器名>      # 查看容器流量管理信息"
        echo "  lxd-flow-manager list-usage         # 列出所有容器已用/剩余/限制"
        echo "  lxd-flow-manager auto-reset         # 执行自动流量重置"
        echo "  lxd-flow-manager register           # 注册现有容器"
        echo "  lxd-flow-manager cleanup            # 清理已删除容器记录"
        echo "  lxd-flow-manager test               # 运行功能测试"
        echo "  lxd-flow-manager upgrade-db         # 升级数据库结构"
        echo "  lxd-flow-manager daemon-status      # 查看守护进程状态"
        echo "  lxd-flow-manager daemon-restart     # 重启守护进程"
        echo "  lxd-flow-manager check-now          # 立即检查流量状态"
        echo ""
        ;;
esac
EOF

chmod +x /usr/local/bin/lxd-flow-manager

echo ""
echo "=========================================="
echo "  流量管理功能安装完成！"
echo "=========================================="

# 最终验证所有组件
echo ""
echo "### 最终验证 ###"
echo ""

VERIFICATION_PASSED=true

# 1. 验证数据库
echo "1. 验证数据库..."
if [ -f "flow_management.db" ]; then
    CONTAINER_COUNT=$(sqlite3 flow_management.db "SELECT COUNT(*) FROM container_flow_management;" 2>/dev/null || echo "0")
    echo "   ✅ 数据库正常，已注册 $CONTAINER_COUNT 个容器"
else
    echo "   ❌ 数据库文件不存在"
    VERIFICATION_PASSED=false
fi

# 2. 验证守护进程
echo "2. 验证守护进程..."
if systemctl is-active --quiet lxd-flow-continuity.service; then
    echo "   ✅ 守护进程正在运行"
else
    echo "   ❌ 守护进程未运行"
    VERIFICATION_PASSED=false
fi

# 3. 验证定时任务
echo "3. 验证定时任务..."
CRON_CHECK=$(crontab -l 2>/dev/null | grep "flow_reset_scheduler.py" | wc -l)
if [ "$CRON_CHECK" -ge 2 ]; then
    echo "   ✅ 定时任务已配置（$CRON_CHECK 条）"
else
    echo "   ❌ 定时任务配置不完整（仅 $CRON_CHECK 条，期望 ≥2）"
    VERIFICATION_PASSED=false
fi

# 4. 验证管理命令
echo "4. 验证管理命令..."
if [ -x "/usr/local/bin/lxd-flow-manager" ]; then
    echo "   ✅ 管理命令已安装"
else
    echo "   ❌ 管理命令未安装或无执行权限"
    VERIFICATION_PASSED=false
fi

# 5. 验证诊断脚本
echo "5. 验证诊断脚本..."
if [ -f "diagnose_flow_management.py" ]; then
    echo "   ✅ 诊断脚本已存在"
else
    echo "   ⚠️  诊断脚本不存在（可选）"
fi

echo ""
if [ "$VERIFICATION_PASSED" = true ]; then
    echo "=========================================="
    echo "  ✅ 所有验证通过！安装成功！"
    echo "=========================================="
else
    echo "=========================================="
    echo "  ⚠️  部分验证失败，请检查错误信息"
    echo "=========================================="
fi

echo ""
echo "功能说明："
echo "✅ 自动流量重置：每月自动重置容器流量统计"
echo "✅ 手动流量重置：支持通过API手动重置"
echo "✅ 流量历史记录：记录每次重置的历史"
echo "✅ 周期性统计：基于产品开通日期计算月度流量"
echo ""
echo "管理命令："
echo "  lxd-flow-manager reset <容器名>     # 手动重置指定容器流量"
echo "  lxd-flow-manager info <容器名>      # 查看容器流量管理信息"
echo "  lxd-flow-manager list-usage         # 列出所有容器流量"
echo "  lxd-flow-manager auto-reset         # 执行自动流量重置"
echo "  lxd-flow-manager register           # 注册现有容器"
echo ""
echo "定时任务："
echo "  每天凌晨2点自动检查并重置到期的容器流量"
echo "  每周日凌晨3点自动清理已删除容器记录"
echo ""
echo "API接口："
echo "  POST /api/flow/reset    # 重置容器流量"
echo "  GET  /api/flow/info     # 获取流量管理信息"
echo ""
echo "验证和诊断："
echo "  python3 diagnose_flow_management.py    # 运行系统诊断"
echo "  python3 list_flow_usage.py             # 查看所有容器流量"
echo "  crontab -l | grep flow                 # 检查定时任务"
echo ""
echo "注意事项："
echo "⚠️  新创建的容器会自动注册到流量管理系统"
echo "⚠️  删除容器时会自动从流量管理系统注销"
echo "⚠️  流量统计基于容器创建日期，每月同一天重置"
echo ""
echo "重启服务使配置生效："
echo "  systemctl restart lxd-api.service"
echo ""
