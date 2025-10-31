#!/bin/bash
# iptables 流量监控系统一键部署脚本

set -e

# 颜色定义
COLOR_GREEN='\033[0;32m'
COLOR_YELLOW='\033[1;33m'
COLOR_RED='\033[0;31m'
COLOR_BLUE='\033[0;34m'
COLOR_NC='\033[0m'

# 获取脚本所在目录（server目录）
SERVER_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo -e "${COLOR_BLUE}================================${COLOR_NC}"
echo -e "${COLOR_BLUE}  iptables 流量监控系统部署  ${COLOR_NC}"
echo -e "${COLOR_BLUE}================================${COLOR_NC}"
echo ""

# 检查是否为 root
if [ "$EUID" -ne 0 ]; then
    echo -e "${COLOR_RED}错误: 请使用 root 权限运行此脚本${COLOR_NC}"
    exit 1
fi

# 检查必要的依赖
echo -e "${COLOR_YELLOW}[1/8] 检查依赖...${COLOR_NC}"

check_command() {
    if ! command -v $1 &> /dev/null; then
        echo -e "${COLOR_RED}错误: 未找到 $1${COLOR_NC}"
        exit 1
    fi
}

check_command python3
check_command lxc
check_command iptables
check_command ip6tables

echo -e "${COLOR_GREEN}✓ 依赖检查完成${COLOR_NC}"
echo ""

# 检查必要的文件
echo -e "${COLOR_YELLOW}[2/8] 检查必要文件...${COLOR_NC}"

required_files=(
    "iptables_manager.py"
    "flow_manager_v2.py"
    "lxc_manager.py"
    "flow_collector.py"
    "flow_limit_enforcer.py"
    "flow_reset_scheduler.py"
    "lxd_event_listener.py"
    "restore_on_boot.py"
    "periodic_sync.py"
)

for file in "${required_files[@]}"; do
    if [ ! -f "$SERVER_DIR/$file" ]; then
        echo -e "${COLOR_RED}错误: 文件不存在 $file${COLOR_NC}"
        exit 1
    fi
done

echo -e "${COLOR_GREEN}✓ 文件检查完成${COLOR_NC}"
echo ""

# 确保脚本可执行
echo -e "${COLOR_YELLOW}[3/8] 设置文件权限...${COLOR_NC}"

for file in "${required_files[@]}"; do
    chmod +x "$SERVER_DIR/$file"
done

echo -e "${COLOR_GREEN}✓ 权限设置完成${COLOR_NC}"
echo ""

# 初始化数据库
echo -e "${COLOR_YELLOW}[4/8] 初始化数据库...${COLOR_NC}"

cd "$SERVER_DIR"
python3 -c "from flow_manager_v2 import FlowManagerV2; FlowManagerV2()" 2>/dev/null || true

if [ -f "flow_management_v2.db" ]; then
    echo -e "${COLOR_GREEN}✓ 数据库初始化完成${COLOR_NC}"
else
    echo -e "${COLOR_RED}错误: 数据库初始化失败${COLOR_NC}"
    exit 1
fi
echo ""

# 数据迁移（如果有旧数据库）
if [ -f "$SERVER_DIR/flow_management.db" ]; then
    echo -e "${COLOR_YELLOW}[5/8] 发现旧数据库，是否迁移数据？${COLOR_NC}"
    read -p "$(echo -e "${COLOR_YELLOW}迁移旧数据? (y/n):${COLOR_NC} ")" migrate_choice
    
    if [ "$migrate_choice" = "y" ] || [ "$migrate_choice" = "Y" ]; then
        echo -e "${COLOR_BLUE}开始迁移数据...${COLOR_NC}"
        python3 "$SERVER_DIR/migrate_to_v2.py" backup
        python3 "$SERVER_DIR/migrate_to_v2.py" migrate
        
        if [ $? -eq 0 ]; then
            echo -e "${COLOR_GREEN}✓ 数据迁移完成${COLOR_NC}"
        else
            echo -e "${COLOR_RED}⚠ 数据迁移失败，但可以继续${COLOR_NC}"
        fi
    else
        echo -e "${COLOR_YELLOW}跳过数据迁移${COLOR_NC}"
    fi
else
    echo -e "${COLOR_YELLOW}[5/8] 未发现旧数据库，跳过迁移${COLOR_NC}"
fi
echo ""

# 同步现有容器
echo -e "${COLOR_YELLOW}[6/8] 同步现有容器...${COLOR_NC}"

python3 "$SERVER_DIR/lxd_event_listener.py" sync

if [ $? -eq 0 ]; then
    echo -e "${COLOR_GREEN}✓ 容器同步完成${COLOR_NC}"
else
    echo -e "${COLOR_RED}⚠ 容器同步失败，但可以继续${COLOR_NC}"
fi
echo ""

# 配置 systemd 服务
echo -e "${COLOR_YELLOW}[7/8] 配置 systemd 服务...${COLOR_NC}"

# 流量收集器（每分钟）
echo -e "  配置流量收集器..."
bash "$SERVER_DIR/setup_flow_collector.sh" > /dev/null 2>&1
echo -e "  ${COLOR_GREEN}✓ 流量收集器${COLOR_NC}"

# 流量限制执行器（每5分钟）
echo -e "  配置流量限制执行器..."
bash "$SERVER_DIR/setup_flow_limit_enforcer.sh" > /dev/null 2>&1
echo -e "  ${COLOR_GREEN}✓ 流量限制执行器${COLOR_NC}"

# 流量重置调度器（每天凌晨1点）
echo -e "  配置流量重置调度器..."
bash "$SERVER_DIR/setup_flow_reset_scheduler.sh" > /dev/null 2>&1
echo -e "  ${COLOR_GREEN}✓ 流量重置调度器${COLOR_NC}"

# LXD 事件监听器（持续运行）
echo -e "  配置 LXD 事件监听器..."
if bash "$SERVER_DIR/setup_lxd_event_listener.sh" > /tmp/lxd_event_listener_setup.log 2>&1; then
    echo -e "  ${COLOR_GREEN}✓ LXD 事件监听器${COLOR_NC}"
else
    echo -e "  ${COLOR_RED}✗ LXD 事件监听器配置失败${COLOR_NC}"
    echo -e "${COLOR_YELLOW}错误详情：${COLOR_NC}"
    cat /tmp/lxd_event_listener_setup.log
    echo -e "${COLOR_RED}[ERROR] 流量监控系统部署失败${COLOR_NC}"
    exit 1
fi

# 启动恢复（系统启动时）
echo -e "  配置启动恢复服务..."
bash "$SERVER_DIR/setup_boot_restore.sh" > /dev/null 2>&1
echo -e "  ${COLOR_GREEN}✓ 启动恢复服务${COLOR_NC}"

# 定期同步（每小时）
echo -e "  配置定期同步服务..."
bash "$SERVER_DIR/setup_periodic_sync.sh" > /dev/null 2>&1
echo -e "  ${COLOR_GREEN}✓ 定期同步服务${COLOR_NC}"

echo -e "${COLOR_GREEN}✓ 所有服务配置完成${COLOR_NC}"
echo ""

# 验证部署
echo -e "${COLOR_YELLOW}[8/8] 验证部署...${COLOR_NC}"

# 等待服务启动
sleep 3

# 检查服务状态
services=(
    "lxd-flow-collector.timer"
    "lxd-flow-limit-enforcer.timer"
    "lxd-flow-reset-scheduler.timer"
    "lxd-event-listener.service"
    "lxd-periodic-sync.timer"
)

all_ok=true
for service in "${services[@]}"; do
    if systemctl is-active --quiet "$service"; then
        echo -e "  ${COLOR_GREEN}✓${COLOR_NC} $service"
    else
        echo -e "  ${COLOR_RED}✗${COLOR_NC} $service"
        all_ok=false
    fi
done

echo ""

if [ "$all_ok" = true ]; then
    echo -e "${COLOR_GREEN}================================${COLOR_NC}"
    echo -e "${COLOR_GREEN}  部署成功！${COLOR_NC}"
    echo -e "${COLOR_GREEN}================================${COLOR_NC}"
    echo ""
    echo -e "系统已启动，流量监控正在运行。"
    echo ""
    echo -e "${COLOR_BLUE}常用命令:${COLOR_NC}"
    echo ""
    echo -e "  查看容器流量:"
    echo -e "    ${COLOR_YELLOW}python3 flow_manager_v2.py list${COLOR_NC}"
    echo ""
    echo -e "  查看单个容器详情:"
    echo -e "    ${COLOR_YELLOW}python3 flow_manager_v2.py info <hostname>${COLOR_NC}"
    echo ""
    echo -e "  设置流量限制:"
    echo -e "    ${COLOR_YELLOW}python3 flow_manager_v2.py set-limit <hostname> <GB>${COLOR_NC}"
    echo ""
    echo -e "  重置容器流量:"
    echo -e "    ${COLOR_YELLOW}python3 flow_reset_scheduler.py reset --hostname <hostname>${COLOR_NC}"
    echo ""
    echo -e "  查看流量限制状态:"
    echo -e "    ${COLOR_YELLOW}python3 flow_limit_enforcer.py status${COLOR_NC}"
    echo ""
    echo -e "  查看服务日志:"
    echo -e "    ${COLOR_YELLOW}journalctl -u lxd-flow-collector.service -f${COLOR_NC}"
    echo -e "    ${COLOR_YELLOW}journalctl -u lxd-event-listener.service -f${COLOR_NC}"
    echo ""
    echo -e "${COLOR_BLUE}服务管理:${COLOR_NC}"
    echo ""
    echo -e "  查看所有服务状态:"
    echo -e "    ${COLOR_YELLOW}systemctl status lxd-*.service lxd-*.timer${COLOR_NC}"
    echo ""
    echo -e "  重启流量收集器:"
    echo -e "    ${COLOR_YELLOW}systemctl restart lxd-flow-collector.timer${COLOR_NC}"
    echo ""
    echo -e "${COLOR_BLUE}文档位置:${COLOR_NC}"
    echo -e "  ${SERVER_DIR}/README_FLOW_V2.md"
    echo ""
else
    echo -e "${COLOR_RED}================================${COLOR_NC}"
    echo -e "${COLOR_RED}  部署完成，但有服务未正常启动${COLOR_NC}"
    echo -e "${COLOR_RED}================================${COLOR_NC}"
    echo ""
    echo -e "请检查日志:"
    echo -e "  journalctl -xe"
    echo ""
    exit 1
fi

