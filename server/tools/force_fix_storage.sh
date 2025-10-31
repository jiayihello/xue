#!/bin/bash
#===============================================
# LXD 存储池强制修复脚本
# 用于修复 "Storage pool unavailable" 问题
#===============================================

set +e  # 允许命令失败，继续执行

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() { echo -e "${BLUE}[*]${NC} $1"; }
log_ok() { echo -e "${GREEN}[+]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[!]${NC} $1"; }
log_error() { echo -e "${RED}[-]${NC} $1"; }

if [ "$(id -u)" != "0" ]; then
    log_error "请使用 root 权限运行"
    exit 1
fi

POOL_NAME="disk"
STORAGE_FILE="/var/snap/lxd/common/lxd/disks/disk.img"

echo -e "${BLUE}=========================================="
echo -e "  LXD 存储池强制修复"
echo -e "==========================================${NC}"
echo ""

# 步骤 1: 备份配置
log_info "步骤 1/8: 备份存储池配置..."
lxc storage show "$POOL_NAME" > /root/disk-storage-backup-$(date +%Y%m%d_%H%M%S).yaml 2>/dev/null
log_ok "配置已备份到 /root/"

# 步骤 2: 检查文件系统
log_info "步骤 2/8: 检查文件系统..."
if command -v file &>/dev/null; then
    FILE_TYPE=$(file -s "$STORAGE_FILE" 2>/dev/null | grep -o "BTRFS")
    if [ -n "$FILE_TYPE" ]; then
        log_ok "文件系统类型: BTRFS"
    else
        log_warn "无法确认文件系统类型，继续执行..."
    fi
else
    log_warn "file 命令未安装，跳过文件系统检查"
    log_info "如需安装: apt install -y file"
fi

# 步骤 3: 检查当前 loop 设备
log_info "步骤 3/8: 检查当前 loop 设备..."
CURRENT_LOOP=$(losetup -j "$STORAGE_FILE" | cut -d: -f1)
if [ -n "$CURRENT_LOOP" ]; then
    log_info "当前 loop 设备: $CURRENT_LOOP"
else
    log_warn "未发现 loop 设备"
fi

# 步骤 4: 测试手动挂载
log_info "步骤 4/8: 测试 Btrfs 文件系统..."
mkdir -p /tmp/test-btrfs-mount
if [ -n "$CURRENT_LOOP" ]; then
    if mount -t btrfs "$CURRENT_LOOP" /tmp/test-btrfs-mount 2>&1; then
        log_ok "✓ 文件系统可以正常挂载"
        ls -la /tmp/test-btrfs-mount/ | head -10
        umount /tmp/test-btrfs-mount
    else
        log_error "✗ 文件系统无法挂载"
        log_warn "可能需要修复文件系统"
    fi
else
    log_warn "跳过挂载测试（无 loop 设备）"
fi
rmdir /tmp/test-btrfs-mount 2>/dev/null || true

# 步骤 5: 完全停止 LXD
log_info "步骤 5/8: 停止 LXD 服务..."
systemctl stop snap.lxd.daemon
sleep 3
log_ok "LXD 已停止"

# 步骤 6: 清理 loop 设备
log_info "步骤 6/8: 清理 loop 设备..."
if [ -n "$CURRENT_LOOP" ]; then
    log_info "卸载 $CURRENT_LOOP..."
    losetup -d "$CURRENT_LOOP" 2>/dev/null || true
fi

# 清理所有与该文件关联的 loop 设备
losetup -a | grep "$STORAGE_FILE" | cut -d: -f1 | while read loop_dev; do
    log_info "清理 $loop_dev..."
    losetup -d "$loop_dev" 2>/dev/null || true
done

# 清理所有未使用的 loop 设备
losetup -D 2>/dev/null || true
log_ok "Loop 设备已清理"

# 步骤 7: 重新启动 LXD
log_info "步骤 7/8: 重新启动 LXD..."
systemctl start snap.lxd.daemon
log_info "等待 LXD 完全启动..."
sleep 15

# 检查服务状态
if systemctl is-active --quiet snap.lxd.daemon; then
    log_ok "✓ LXD 服务已启动"
else
    log_error "✗ LXD 服务启动失败"
    systemctl status snap.lxd.daemon
    exit 1
fi

# 步骤 8: 验证修复结果
log_info "步骤 8/8: 验证存储池状态..."
echo ""
lxc storage list

POOL_STATE=$(lxc storage list --format csv | grep "^$POOL_NAME," | cut -d, -f6)
echo ""

if [ "$POOL_STATE" = "UNAVAILABLE" ] || [ -z "$POOL_STATE" ]; then
    log_error "存储池仍然不可用"
    echo ""
    log_warn "建议采取以下措施之一："
    echo ""
    echo "方法 1: 检查 LXD 日志"
    echo "  sudo journalctl -u snap.lxd.daemon -n 100"
    echo ""
    echo "方法 2: 尝试手动修复 Btrfs"
    echo "  sudo losetup -f $STORAGE_FILE"
    echo "  LOOP_DEV=\$(losetup -j $STORAGE_FILE | cut -d: -f1)"
    echo "  sudo btrfs check --readonly \$LOOP_DEV"
    echo "  # 如果有错误："
    echo "  sudo btrfs check --repair \$LOOP_DEV"
    echo ""
    echo "方法 3: 重建存储池（会保留数据）"
    echo "  bash /root/lxd-toolkit/server/rebuild_storage_pool.sh"
    echo ""
    
    # 显示详细错误信息
    log_info "LXD 最近的错误日志:"
    journalctl -u snap.lxd.daemon -n 20 | grep -i "error\|fail" || echo "  (无明显错误)"
    
    exit 1
else
    log_ok "✓✓✓ 存储池已恢复正常！"
    echo ""
    
    # 测试启动一个容器
    log_info "测试容器启动..."
    TEST_CONTAINER=$(lxc list -c n --format csv | head -1)
    
    if [ -n "$TEST_CONTAINER" ]; then
        log_info "尝试启动: $TEST_CONTAINER"
        if lxc start "$TEST_CONTAINER" 2>&1; then
            log_ok "✓ 容器启动成功！"
            echo ""
            read -p "是否启动所有容器? [Y/n]: " start_all
            start_all=${start_all:-Y}
            if [[ "${start_all,,}" =~ ^(y|yes|)$ ]]; then
                log_info "启动所有容器..."
                lxc start --all 2>&1 || log_warn "部分容器启动失败（可能已在运行）"
                echo ""
                log_ok "容器列表:"
                lxc list
            fi
        else
            log_warn "容器启动失败，请检查具体错误"
        fi
    fi
fi

echo ""
log_ok "=========================================="
log_ok "  修复完成！"
log_ok "=========================================="

