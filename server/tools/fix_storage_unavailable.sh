#!/bin/bash
#===============================================
# LXD 存储池不可用问题修复脚本
# 用途：诊断和修复 "Storage pool unavailable" 错误
#===============================================

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 日志函数
log_info() { echo -e "${BLUE}[*]${NC} $1"; }
log_ok() { echo -e "${GREEN}[+]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[!]${NC} $1"; }
log_error() { echo -e "${RED}[-]${NC} $1"; }

# 检查是否为 root
if [ "$(id -u)" != "0" ]; then
    log_error "请使用 root 权限运行此脚本"
    exit 1
fi

echo -e "${BLUE}=========================================="
echo -e "  LXD 存储池修复工具"
echo -e "==========================================${NC}"
echo ""

# 询问存储池名称
read -p "请输入存储池名称 [disk]: " POOL_NAME
POOL_NAME=${POOL_NAME:-disk}

log_info "检查存储池: $POOL_NAME"

# 步骤 1: 获取存储池信息
log_info "步骤 1/6: 获取存储池信息..."
if ! lxc storage show "$POOL_NAME" &>/dev/null; then
    log_error "存储池 '$POOL_NAME' 不存在"
    exit 1
fi

# 获取存储池驱动和源文件
DRIVER=$(lxc storage get "$POOL_NAME" driver 2>/dev/null || lxc storage show "$POOL_NAME" | grep "^driver:" | awk '{print $2}')
SOURCE=$(lxc storage get "$POOL_NAME" source 2>/dev/null || lxc storage show "$POOL_NAME" | grep "^  source:" | awk '{print $2}')

log_ok "存储池信息:"
echo "  驱动: $DRIVER"
echo "  源文件: $SOURCE"

# 步骤 2: 检查源文件
log_info "步骤 2/6: 检查存储源文件..."
if [ ! -f "$SOURCE" ]; then
    log_error "存储文件不存在: $SOURCE"
    log_warn "可能原因:"
    echo "  1. 文件被删除"
    echo "  2. 磁盘已满"
    echo "  3. 文件系统损坏"
    exit 1
fi

FILE_SIZE=$(du -h "$SOURCE" | awk '{print $1}')
log_ok "存储文件存在: $SOURCE ($FILE_SIZE)"

# 步骤 3: 检查 loop 设备
log_info "步骤 3/6: 检查 loop 设备..."
if losetup -a | grep -q "$SOURCE"; then
    LOOP_DEV=$(losetup -j "$SOURCE" | cut -d: -f1)
    log_ok "已挂载到 loop 设备: $LOOP_DEV"
else
    log_warn "未挂载到 loop 设备"
fi

# 步骤 4: 检查容器使用情况
log_info "步骤 4/6: 检查使用该存储池的容器..."
USED_BY=$(lxc storage show "$POOL_NAME" | grep -A 100 "used_by:" | grep "/1.0/instances/" | wc -l)
log_info "使用该存储池的容器数量: $USED_BY"

if [ "$USED_BY" -gt 0 ]; then
    log_warn "以下容器正在使用此存储池:"
    lxc storage show "$POOL_NAME" | grep -A 100 "used_by:" | grep "/1.0/instances/" | sed 's|.*/instances/||' | sed 's/^/  - /'
fi

# 步骤 5: 尝试修复
log_info "步骤 5/6: 尝试修复..."
echo ""
echo "选择修复方法:"
echo "  1) 重启 LXD 服务（推荐，最安全）"
echo "  2) 清理并重新挂载 loop 设备"
echo "  3) 检查并修复 Btrfs 文件系统（危险！）"
echo "  4) 显示详细诊断信息"
echo "  0) 取消"
echo ""
read -p "请选择 [1]: " choice
choice=${choice:-1}

case $choice in
    1)
        log_info "重启 LXD 服务..."
        
        # 停止所有容器
        log_info "停止所有运行中的容器..."
        lxc list -c n,s --format csv | awk -F, '$2=="RUNNING"{print $1}' | while read container; do
            log_info "  停止: $container"
            lxc stop "$container" --timeout 30 || true
        done
        
        # 重启 LXD
        log_info "重启 LXD 守护进程..."
        systemctl restart snap.lxd.daemon
        
        # 等待服务启动
        log_info "等待 LXD 服务启动..."
        sleep 10
        
        # 检查存储池状态
        log_info "检查存储池状态..."
        if lxc storage list | grep -q "$POOL_NAME"; then
            STATUS=$(lxc storage list --format csv | grep "^$POOL_NAME," | cut -d, -f4)
            if [ -z "$STATUS" ] || [ "$STATUS" = "CREATED" ]; then
                log_ok "✓ 存储池已恢复！"
            else
                log_warn "存储池状态: $STATUS"
            fi
        fi
        ;;
        
    2)
        log_info "清理并重新挂载 loop 设备..."
        
        # 清理现有的 loop 设备
        if losetup -a | grep -q "$SOURCE"; then
            LOOP_DEV=$(losetup -j "$SOURCE" | cut -d: -f1)
            log_info "卸载 $LOOP_DEV..."
            losetup -d "$LOOP_DEV" || true
        fi
        
        # 清理所有未使用的 loop 设备
        log_info "清理未使用的 loop 设备..."
        losetup -D
        
        # 重启 LXD
        log_info "重启 LXD 服务..."
        systemctl restart snap.lxd.daemon
        sleep 10
        
        log_ok "✓ 清理完成"
        ;;
        
    3)
        log_warn "警告: 这可能需要很长时间，并且有数据损坏风险！"
        read -p "确认继续? [y/N]: " confirm
        if [[ "${confirm,,}" =~ ^(y|yes)$ ]]; then
            log_info "检查 Btrfs 文件系统..."
            
            # 如果未挂载，先挂载
            if ! losetup -a | grep -q "$SOURCE"; then
                LOOP_DEV=$(losetup -f)
                losetup "$LOOP_DEV" "$SOURCE"
            else
                LOOP_DEV=$(losetup -j "$SOURCE" | cut -d: -f1)
            fi
            
            log_info "只读检查: $LOOP_DEV"
            btrfs check --readonly "$LOOP_DEV" || {
                log_error "文件系统有错误"
                read -p "是否尝试修复? [y/N]: " repair
                if [[ "${repair,,}" =~ ^(y|yes)$ ]]; then
                    log_warn "开始修复..."
                    btrfs check --repair "$LOOP_DEV"
                    log_ok "修复完成"
                fi
            }
            
            # 重启 LXD
            systemctl restart snap.lxd.daemon
            sleep 10
        else
            log_info "已取消"
        fi
        ;;
        
    4)
        log_info "详细诊断信息:"
        echo ""
        echo "=== 存储池配置 ==="
        lxc storage show "$POOL_NAME"
        echo ""
        echo "=== Loop 设备状态 ==="
        losetup -a | grep "$SOURCE" || echo "未挂载"
        echo ""
        echo "=== 文件信息 ==="
        file "$SOURCE"
        echo ""
        echo "=== 磁盘空间 ==="
        df -h "$(dirname "$SOURCE")"
        echo ""
        echo "=== Btrfs 挂载 ==="
        mount | grep btrfs || echo "无 btrfs 挂载"
        exit 0
        ;;
        
    0|*)
        log_info "已取消"
        exit 0
        ;;
esac

# 步骤 6: 验证修复结果
log_info "步骤 6/6: 验证修复结果..."
echo ""

# 检查存储池状态
lxc storage list | grep "$POOL_NAME"

# 尝试启动一个容器测试
if [ "$USED_BY" -gt 0 ]; then
    TEST_CONTAINER=$(lxc storage show "$POOL_NAME" | grep -A 100 "used_by:" | grep "/1.0/instances/" | head -1 | sed 's|.*/instances/||')
    
    log_info "测试容器启动: $TEST_CONTAINER"
    if lxc start "$TEST_CONTAINER" 2>&1; then
        log_ok "✓ 容器启动成功！"
        log_info "是否启动所有容器? [y/N]: "
        read -p "" start_all
        if [[ "${start_all,,}" =~ ^(y|yes)$ ]]; then
            log_info "启动所有容器..."
            lxc start --all
        fi
    else
        log_error "容器启动失败"
        log_warn "可能需要进一步诊断，请运行:"
        echo "  lxc storage show $POOL_NAME"
        echo "  journalctl -u snap.lxd.daemon -n 50"
    fi
fi

echo ""
log_ok "=========================================="
log_ok "  修复流程完成"
log_ok "=========================================="
echo ""
log_info "如果问题仍然存在，请检查:"
echo "  1. 磁盘空间是否充足: df -h"
echo "  2. LXD 日志: journalctl -u snap.lxd.daemon -f"
echo "  3. 系统日志: dmesg | tail -50"

