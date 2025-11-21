#!/bin/bash
# CPU保护系统实时监控脚本

echo "═══════════════════════════════════════════════════════════"
echo "   LXD CPU保护系统 - 实时监控"
echo "═══════════════════════════════════════════════════════════"
echo ""

# 检查服务状态
echo "【服务状态】"
systemctl is-active lxd-cpu-killer > /dev/null 2>&1
if [ $? -eq 0 ]; then
    echo "✓ 第一层（进程杀手）: 运行中"
else
    echo "✗ 第一层（进程杀手）: 已停止"
fi

systemctl is-active lxd-auto-restart > /dev/null 2>&1
if [ $? -eq 0 ]; then
    echo "✓ 第二层（自动重启）: 运行中"
else
    echo "✗ 第二层（自动重启）: 已停止"
fi

echo ""
echo "【今日统计】（从00:00开始）"
KILL_COUNT=$(journalctl -u lxd-cpu-killer --since today 2>/dev/null | grep -c "已杀死")
RESTART_COUNT=$(journalctl -u lxd-auto-restart --since today 2>/dev/null | grep -c "已重启完成")
STOP_COUNT=$(journalctl -u lxd-auto-restart --since today 2>/dev/null | grep -c "自动关机")

echo "杀进程次数: $KILL_COUNT"
echo "容器重启: $RESTART_COUNT"
echo "自动关机: $STOP_COUNT"

echo ""
echo "【最近1小时活动】"
RECENT_KILL=$(journalctl -u lxd-cpu-killer --since "1 hour ago" 2>/dev/null | grep -c "已杀死")
RECENT_RESTART=$(journalctl -u lxd-auto-restart --since "1 hour ago" 2>/dev/null | grep -c "已重启完成")
RECENT_STOP=$(journalctl -u lxd-auto-restart --since "1 hour ago" 2>/dev/null | grep -c "自动关机")

echo "杀进程: $RECENT_KILL"
echo "重启: $RECENT_RESTART"
echo "关机: $RECENT_STOP"

echo ""
echo "【当前高CPU容器】（正在监控中）"
journalctl -u lxd-cpu-killer --since "5 min ago" 2>/dev/null | \
  grep "⚠️" | tail -5 | \
  awk '{print $9, $10}' || echo "  暂无"

echo ""
echo "【最近10条事件】"
journalctl -u lxd-cpu-killer -u lxd-auto-restart --since "10 min ago" -n 10 --no-pager 2>/dev/null | \
  grep -E "已杀死|执行重启|自动关机|开始监控" | tail -10 || echo "  暂无"

echo ""
echo "═══════════════════════════════════════════════════════════"
echo ""
echo "实时监控命令："
echo "  journalctl -u lxd-cpu-killer -u lxd-auto-restart -f"
echo ""
echo "查看扫描日志："
echo "  journalctl -u lxd-cpu-killer -n 50"
echo ""
echo "═══════════════════════════════════════════════════════════"
