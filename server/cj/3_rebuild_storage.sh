#!/bin/bash
#===============================================
# 步骤 3: 清理磁盘空间并重建存储池
# 用途：删除损坏的存储池，创建新的干净存储池
#===============================================

set -e

echo "╔════════════════════════════════════════════╗"
echo "║      清理和重建存储池                      ║"
echo "╚════════════════════════════════════════════╝"
echo ""

echo "⚠️  警告: 此操作将："
echo "  1. 清理磁盘空间"
echo "  2. 删除损坏的存储池文件"
echo "  3. 创建新的干净存储池"
echo "  4. 容器配置已备份，可以恢复"
echo ""
read -p "确认继续? 输入 'yes' 继续: " confirm
if [ "$confirm" != "yes" ]; then
    echo "已取消"
    exit 0
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "第 1/7 步: 清理磁盘空间"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

echo "[1/6] 清理 APT 缓存..."
apt clean
apt autoremove -y

echo "[2/6] 清理旧日志..."
journalctl --vacuum-time=3d
find /var/log -type f -name "*.log.*" -delete 2>/dev/null || true
find /var/log -type f -name "*.gz" -delete 2>/dev/null || true

echo "[3/6] 清理临时文件..."
rm -rf /tmp/* 2>/dev/null || true
rm -rf /var/tmp/* 2>/dev/null || true

echo "[4/6] 清理 Snap 旧版本..."
snap list --all | awk '/disabled/{print $1, $3}' | while read snapname revision; do
    snap remove "$snapname" --revision="$revision" 2>/dev/null || true
done

echo "[5/6] 清理 LXD 缓存..."
rm -rf /var/snap/lxd/common/lxd/cache/* 2>/dev/null || true

echo "[6/6] 清理旧备份文件..."
find /root -name "disk-storage-backup-*.yaml" -delete 2>/dev/null || true
find /root -name "btrfs-*.log" -delete 2>/dev/null || true

echo ""
echo "清理完成！当前磁盘状态："
df -h /

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "第 2/7 步: 清理 Loop 设备"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
losetup -d /dev/loop4 2>/dev/null || true
losetup -D 2>/dev/null || true
echo "✓ Loop 设备已清理"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "第 3/7 步: 停止 LXD 服务"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
systemctl stop snap.lxd.daemon
sleep 3
echo "✓ LXD 已停止"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "第 4/7 步: 备份损坏的存储文件"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
STORAGE_FILE="/var/snap/lxd/common/lxd/disks/disk.img"
if [ -f "$STORAGE_FILE" ]; then
    mv "$STORAGE_FILE" "${STORAGE_FILE}.broken-$(date +%Y%m%d_%H%M%S)"
    echo "✓ 损坏文件已重命名为: ${STORAGE_FILE}.broken-$(date +%Y%m%d_%H%M%S)"
else
    echo "! 存储文件不存在，跳过"
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "第 5/7 步: 清理容器配置"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
rm -rf /var/snap/lxd/common/lxd/containers/* 2>/dev/null || true
rm -rf /var/snap/lxd/common/lxd/virtual-machines/* 2>/dev/null || true
echo "✓ 容器配置已清理"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "第 6/7 步: 启动 LXD"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
systemctl start snap.lxd.daemon
echo "等待 LXD 完全启动（15秒）..."
sleep 15
echo "✓ LXD 已启动"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "第 7/7 步: 创建新存储池"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# 删除旧存储池配置（如果存在）
lxc storage delete disk --force 2>/dev/null || true

# 创建新存储池（10GB，根据需要调整）
echo "创建新的 Btrfs 存储池（10GB）..."
lxc storage create disk btrfs size=10GB

# 设为默认存储池
echo "设置为默认存储池..."
lxc profile device set default root pool=disk

echo "✓ 新存储池已创建"

echo ""
echo "验证存储池状态："
lxc storage list

echo ""
echo "╔════════════════════════════════════════════╗"
echo "║      ✓ 存储池重建完成！                    ║"
echo "╚════════════════════════════════════════════╝"
echo ""
echo "当前磁盘使用情况："
df -h /
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "下一步: 恢复容器配置"
echo "  cd /root/lxd-container-configs-*"
echo "  ./restore_containers.sh"
echo ""
echo "或者查看最新备份目录:"
echo "  ls -td /root/lxd-container-configs-* | head -1"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

