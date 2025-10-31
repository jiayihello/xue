#!/bin/bash
# iptables 流量监控系统测试脚本

set -e

# 颜色定义
COLOR_GREEN='\033[0;32m'
COLOR_YELLOW='\033[1;33m'
COLOR_RED='\033[0;31m'
COLOR_BLUE='\033[0;34m'
COLOR_NC='\033[0m'

# 获取脚本所在目录（server目录）
SERVER_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SERVER_DIR"

echo -e "${COLOR_BLUE}================================${COLOR_NC}"
echo -e "${COLOR_BLUE}  iptables 流量监控系统测试  ${COLOR_NC}"
echo -e "${COLOR_BLUE}================================${COLOR_NC}"
echo ""

# 测试计数器
total_tests=0
passed_tests=0
failed_tests=0

# 测试函数
test_item() {
    local test_name="$1"
    local test_command="$2"
    
    total_tests=$((total_tests + 1))
    echo -n "测试 $total_tests: $test_name ... "
    
    if eval "$test_command" > /dev/null 2>&1; then
        echo -e "${COLOR_GREEN}✓ 通过${COLOR_NC}"
        passed_tests=$((passed_tests + 1))
        return 0
    else
        echo -e "${COLOR_RED}✗ 失败${COLOR_NC}"
        failed_tests=$((failed_tests + 1))
        return 1
    fi
}

echo -e "${COLOR_YELLOW}[1/6] 检查必要文件...${COLOR_NC}"

test_item "iptables_manager.py" "[ -f iptables_manager.py ]"
test_item "flow_manager_v2.py" "[ -f flow_manager_v2.py ]"
test_item "lxc_manager.py" "[ -f lxc_manager.py ]"
test_item "flow_collector.py" "[ -f flow_collector.py ]"
test_item "flow_limit_enforcer.py" "[ -f flow_limit_enforcer.py ]"
test_item "flow_reset_scheduler.py" "[ -f flow_reset_scheduler.py ]"
test_item "lxd_event_listener.py" "[ -f lxd_event_listener.py ]"
test_item "restore_on_boot.py" "[ -f restore_on_boot.py ]"
test_item "periodic_sync.py" "[ -f periodic_sync.py ]"

echo ""
echo -e "${COLOR_YELLOW}[2/6] 检查数据库...${COLOR_NC}"

test_item "数据库文件存在" "[ -f flow_management_v2.db ]"
test_item "数据库可读" "python3 -c 'from flow_manager_v2 import FlowManagerV2; FlowManagerV2().list_all_containers()'"

echo ""
echo -e "${COLOR_YELLOW}[3/6] 检查 Python 模块...${COLOR_NC}"

test_item "iptables_manager 可导入" "python3 -c 'from iptables_manager import IptablesManager'"
test_item "flow_manager_v2 可导入" "python3 -c 'from flow_manager_v2 import FlowManagerV2'"
test_item "lxc_manager 可导入" "python3 -c 'from lxc_manager import LXCManager'"

echo ""
echo -e "${COLOR_YELLOW}[4/6] 检查 systemd 服务...${COLOR_NC}"

test_item "lxd-flow-collector.timer 已启用" "systemctl is-enabled lxd-flow-collector.timer"
test_item "lxd-flow-collector.timer 运行中" "systemctl is-active lxd-flow-collector.timer"

test_item "lxd-flow-limit-enforcer.timer 已启用" "systemctl is-enabled lxd-flow-limit-enforcer.timer"
test_item "lxd-flow-limit-enforcer.timer 运行中" "systemctl is-active lxd-flow-limit-enforcer.timer"

test_item "lxd-flow-reset-scheduler.timer 已启用" "systemctl is-enabled lxd-flow-reset-scheduler.timer"
test_item "lxd-flow-reset-scheduler.timer 运行中" "systemctl is-active lxd-flow-reset-scheduler.timer"

test_item "lxd-event-listener.service 已启用" "systemctl is-enabled lxd-event-listener.service"
test_item "lxd-event-listener.service 运行中" "systemctl is-active lxd-event-listener.service"

test_item "lxd-boot-restore.service 已启用" "systemctl is-enabled lxd-boot-restore.service"

test_item "lxd-periodic-sync.timer 已启用" "systemctl is-enabled lxd-periodic-sync.timer"
test_item "lxd-periodic-sync.timer 运行中" "systemctl is-active lxd-periodic-sync.timer"

echo ""
echo -e "${COLOR_YELLOW}[5/6] 功能测试...${COLOR_NC}"

# 获取一个测试容器
test_container=$(python3 -c "
from lxc_manager import LXCManager
containers = LXCManager().list_all_containers()
if containers:
    print(containers[0])
" 2>/dev/null || echo "")

if [ -n "$test_container" ]; then
    test_hostname=$(python3 -c "
from lxc_manager import LXCManager
print(LXCManager().get_container_hostname('$test_container'))
" 2>/dev/null || echo "")
    
    if [ -n "$test_hostname" ]; then
        echo -e "  使用测试容器: ${COLOR_BLUE}$test_hostname${COLOR_NC}"
        
        test_item "获取容器流量" "python3 -c 'from flow_manager_v2 import FlowManagerV2; FlowManagerV2().get_container_usage(\"$test_hostname\")'"
        test_item "检查 iptables 规则" "python3 -c 'from iptables_manager import IptablesManager; IptablesManager().check_container_rules_exist(\"$test_hostname\")'"
        test_item "获取 iptables 计数" "python3 -c 'from iptables_manager import IptablesManager; IptablesManager().get_container_bytes(\"$test_hostname\")'"
    else
        echo -e "  ${COLOR_YELLOW}⚠ 无法获取容器 hostname，跳过功能测试${COLOR_NC}"
    fi
else
    echo -e "  ${COLOR_YELLOW}⚠ 没有运行中的容器，跳过功能测试${COLOR_NC}"
fi

echo ""
echo -e "${COLOR_YELLOW}[6/6] 系统状态...${COLOR_NC}"

# 获取统计信息
container_count=$(python3 -c "
from flow_manager_v2 import FlowManagerV2
print(len(FlowManagerV2().list_all_containers()))
" 2>/dev/null || echo "0")

rules_count=$(python3 -c "
from iptables_manager import IptablesManager
print(len(IptablesManager().list_all_tracked_containers()))
" 2>/dev/null || echo "0")

running_count=$(python3 -c "
from lxc_manager import LXCManager
print(len(LXCManager().list_all_containers()))
" 2>/dev/null || echo "0")

echo -e "  数据库中的容器: ${COLOR_BLUE}$container_count${COLOR_NC}"
echo -e "  有 iptables 规则的容器: ${COLOR_BLUE}$rules_count${COLOR_NC}"
echo -e "  运行中的容器: ${COLOR_BLUE}$running_count${COLOR_NC}"

echo ""
echo -e "${COLOR_BLUE}================================${COLOR_NC}"
echo -e "${COLOR_BLUE}         测试结果统计        ${COLOR_NC}"
echo -e "${COLOR_BLUE}================================${COLOR_NC}"
echo -e "  总测试数: ${COLOR_BLUE}$total_tests${COLOR_NC}"
echo -e "  通过: ${COLOR_GREEN}$passed_tests${COLOR_NC}"
echo -e "  失败: ${COLOR_RED}$failed_tests${COLOR_NC}"
echo ""

if [ $failed_tests -eq 0 ]; then
    echo -e "${COLOR_GREEN}✓ 所有测试通过！系统运行正常。${COLOR_NC}"
    exit 0
else
    echo -e "${COLOR_RED}✗ 有 $failed_tests 个测试失败。${COLOR_NC}"
    echo -e "${COLOR_YELLOW}请检查日志: journalctl -u 'lxd-*' -n 50${COLOR_NC}"
    exit 1
fi

