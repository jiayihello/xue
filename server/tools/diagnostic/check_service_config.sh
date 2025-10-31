#!/bin/bash
# 检查 lxd-api 服务配置和工作目录

echo "=== 检查服务配置 ==="
echo ""

# 查看服务配置
echo "1. 服务配置文件:"
systemctl cat lxd-api.service 2>/dev/null || echo "服务配置不存在"
echo ""

# 查看服务状态
echo "2. 服务状态:"
systemctl status lxd-api.service --no-pager
echo ""

# 查看服务进程
echo "3. 服务进程:"
ps aux | grep -E "app\.py|lxd.*api" | grep -v grep
echo ""

# 查看进程工作目录
echo "4. 进程工作目录:"
SERVICE_PID=$(systemctl show -p MainPID lxd-api.service 2>/dev/null | cut -d= -f2)
if [ -n "$SERVICE_PID" ] && [ "$SERVICE_PID" != "0" ]; then
    echo "PID: $SERVICE_PID"
    ls -la /proc/$SERVICE_PID/cwd 2>/dev/null || echo "无法读取工作目录"
    readlink /proc/$SERVICE_PID/cwd 2>/dev/null || echo "无法读取工作目录链接"
else
    echo "未找到服务PID"
fi
echo ""

# 查看服务日志
echo "5. 最近的服务日志:"
journalctl -u lxd-api.service -n 20 --no-pager 2>/dev/null || echo "无法读取日志"

