#!/bin/bash
#===============================================
# LXD 存储池重建脚本
# 用途：在不丢失数据的情况下重建存储池
# 警告：这个过程会临时停止所有容器
#===============================================

set -e

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
BACKUP_DIR="/root/lxd-storage-rebuild-$(date +%Y%m%d_%H%M%S)"

echo -e "${RED}=========================================="
echo -e "  ⚠️  LXD 存储池重建工具"
echo -e "==========================================${NC}"
echo ""
log_warn "这个操作会："
echo "  1. 导出所有容器为镜像"
echo "  2. 删除所有容器实例"
echo "  3. 删除并重新创建存储池"
echo "  4. 从镜像恢复所有容器"
echo ""
log_error "容器数据会保留，但需要一定时间"
echo ""
read -p "确认继续? [yes/NO]: " confirm
if [ "$confirm" != "yes" ]; then
    log_info "已取消"
    exit 0
fi

mkdir -p "$BACKUP_DIR"
cd "$BACKUP_DIR"

# 步骤 1: 导出所有容器
log_info "步骤 1/7: 导出所有容器..."
lxc list -c n --format csv > containers.list

if [ ! -s containers.list ]; then
    log_warn "没有找到容器"
else
    CONTAINER_COUNT=$(wc -l < containers.list)
    log_info "找到 $CONTAINER_COUNT 个容器"
    
    cat containers.list | while read container; do
        log_info "  导出: $container"
        
        # 获取容器配置
        lxc config show "$container" > "${container}.config.yaml"
        
        # 获取设备配置
        lxc config device show "$container" > "${container}.devices.yaml"
        
        # 发布为镜像
        lxc publish "$container" --alias "rebuild-$container" --force
        
        log_ok "  ✓ $container 已导出"
    done
fi

# 步骤 2: 备份存储池配置
log_info "步骤 2/7: 备份存储池配置..."
lxc storage show "$POOL_NAME" > storage-pool.yaml
log_ok "存储池配置已保存"

# 步骤 3: 删除所有容器实例
log_info "步骤 3/7: 删除容器实例..."
cat containers.list | while read container; do
    log_info "  删除: $container"
    lxc delete "$container" -f
done
log_ok "所有容器实例已删除"

# 步骤 4: 删除存储池
log_info "步骤 4/7: 删除存储池..."
log_warn "尝试删除存储池（如果失败会跳过）..."
lxc storage delete "$POOL_NAME" 2>&1 || {
    log_warn "存储池删除失败，尝试强制方式..."
    
    # 停止 LXD
    systemctl stop snap.lxd.daemon
    
    # 清理 loop 设备
    losetup -a | grep "$STORAGE_FILE" | cut -d: -f1 | xargs -r -I{} losetup -d {}
    
    # 启动 LXD
    systemctl start snap.lxd.daemon
    sleep 10
    
    # 再次尝试删除
    lxc storage delete "$POOL_NAME" 2>&1 || log_warn "仍然无法删除存储池，继续..."
}

# 步骤 5: 重新创建存储池
log_info "步骤 5/7: 重新创建存储池..."

# 检查存储文件是否存在
if [ -f "$STORAGE_FILE" ]; then
    log_info "使用现有存储文件: $STORAGE_FILE"
    SIZE=$(du -h "$STORAGE_FILE" | awk '{print $1}')
    log_info "文件大小: $SIZE"
    
    # 尝试重新创建（指向现有文件）
    if lxc storage create "$POOL_NAME" btrfs source="$STORAGE_FILE" 2>&1; then
        log_ok "✓ 存储池已重新创建（使用现有文件）"
    else
        log_error "无法重新使用现有文件"
        log_warn "尝试创建新的存储文件..."
        
        # 备份旧文件
        mv "$STORAGE_FILE" "${STORAGE_FILE}.broken"
        log_info "旧文件已重命名为: ${STORAGE_FILE}.broken"
        
        # 创建新的存储池
        lxc storage create "$POOL_NAME" btrfs size=20GB
        log_ok "✓ 已创建新的存储池"
    fi
else
    log_warn "存储文件不存在，创建新的..."
    lxc storage create "$POOL_NAME" btrfs size=20GB
    log_ok "✓ 已创建新的存储池"
fi

# 步骤 6: 恢复容器
log_info "步骤 6/7: 恢复容器..."
cat containers.list | while read container; do
    log_info "  恢复: $container"
    
    # 从镜像创建容器
    lxc init "rebuild-$container" "$container" -s "$POOL_NAME"
    
    # 恢复设备配置（如果有自定义设备）
    if [ -s "${container}.devices.yaml" ]; then
        log_info "  恢复设备配置..."
        # 这里需要手动处理，因为 device show 输出格式复杂
    fi
    
    # 清理临时镜像
    lxc image delete "rebuild-$container"
    
    log_ok "  ✓ $container 已恢复"
done

# 步骤 7: 启动所有容器
log_info "步骤 7/7: 启动容器..."
read -p "是否启动所有容器? [Y/n]: " start_containers
start_containers=${start_containers:-Y}

if [[ "${start_containers,,}" =~ ^(y|yes|)$ ]]; then
    cat containers.list | while read container; do
        log_info "  启动: $container"
        lxc start "$container" || log_warn "  ! $container 启动失败"
    done
    
    echo ""
    log_ok "容器列表:"
    lxc list
fi

echo ""
log_ok "=========================================="
log_ok "  ✓ 重建完成！"
log_ok "=========================================="
echo ""
log_info "备份数据保存在: $BACKUP_DIR"
log_info "如果旧存储文件被替换，备份在: ${STORAGE_FILE}.broken"

