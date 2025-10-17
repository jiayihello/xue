#!/bin/bash
#===============================================
# 步骤 2: 备份所有容器配置
# 用途：备份容器配置、密码、端口映射等所有信息
#===============================================

set -e

echo "╔════════════════════════════════════════════╗"
echo "║      备份容器配置信息                      ║"
echo "╚════════════════════════════════════════════╝"
echo ""

BACKUP_DIR="/root/lxd-container-configs-$(date +%Y%m%d_%H%M%S)"
mkdir -p "$BACKUP_DIR"
cd "$BACKUP_DIR"

echo "[1/5] 备份容器列表..."
lxc list -c n --format csv > containers.list
CONTAINER_COUNT=$(wc -l < containers.list)
echo "✓ 找到 $CONTAINER_COUNT 个容器"
echo ""

echo "[2/5] 备份容器配置..."
cat containers.list | while read container; do
    echo "  备份: $container"
    
    # 完整配置
    lxc config show "$container" > "${container}.config.yaml"
    
    # 设备配置
    lxc config device show "$container" > "${container}.devices.yaml"
    
    # 提取所有可能的密码
    echo "# 密码信息提取 - $(date)" > "${container}.passwords.txt"
    echo "" >> "${container}.passwords.txt"
    
    PASSWORD=$(lxc config get "$container" user.password 2>/dev/null || echo "")
    ROOT_PASSWORD=$(lxc config get "$container" user.root_password 2>/dev/null || echo "")
    DEFAULT_PASSWORD=$(lxc config get "$container" user.default_password 2>/dev/null || echo "")
    
    [ -n "$PASSWORD" ] && echo "user.password: $PASSWORD" >> "${container}.passwords.txt" || echo "user.password: 未设置" >> "${container}.passwords.txt"
    [ -n "$ROOT_PASSWORD" ] && echo "user.root_password: $ROOT_PASSWORD" >> "${container}.passwords.txt" || echo "user.root_password: 未设置" >> "${container}.passwords.txt"
    [ -n "$DEFAULT_PASSWORD" ] && echo "user.default_password: $DEFAULT_PASSWORD" >> "${container}.passwords.txt" || echo "user.default_password: 未设置" >> "${container}.passwords.txt"
    
    # 提取所有user属性
    echo "" >> "${container}.passwords.txt"
    echo "# 所有用户属性:" >> "${container}.passwords.txt"
    lxc config show "$container" | grep "^  user\." >> "${container}.passwords.txt" || echo "无用户属性" >> "${container}.passwords.txt"
    
    # Cloud-init配置
    lxc config get "$container" cloud-init.user-data 2>/dev/null > "${container}.cloud-init.txt" || echo "无 cloud-init 配置" > "${container}.cloud-init.txt"
    
    # 其他重要属性
    lxc config get "$container" user.disk_size_mb 2>/dev/null > "${container}.disk_size.txt" || echo "2048" > "${container}.disk_size.txt"
    lxc config get "$container" user.flow_limit_gb 2>/dev/null > "${container}.flow_limit.txt" || echo "" > "${container}.flow_limit.txt"
    lxc config get "$container" user.nat_acl_limit 2>/dev/null > "${container}.nat_limit.txt" || echo "" > "${container}.nat_limit.txt"
done
echo "✓ 配置备份完成"
echo ""

echo "[3/5] 生成密码摘要..."
cat > PASSWORD_SUMMARY.txt << 'EOF'
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        容器密码信息摘要
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

EOF

cat containers.list | while read container; do
    echo "" >> PASSWORD_SUMMARY.txt
    echo "容器: $container" >> PASSWORD_SUMMARY.txt
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━" >> PASSWORD_SUMMARY.txt
    cat "${container}.passwords.txt" >> PASSWORD_SUMMARY.txt
    echo "" >> PASSWORD_SUMMARY.txt
done
echo "✓ 密码摘要已生成"
echo ""

echo "[4/5] 生成配置摘要..."
cat > CONTAINER_SUMMARY.txt << 'SUMMARY_HEAD'
╔════════════════════════════════════════════╗
║        容器配置信息完整摘要                ║
╚════════════════════════════════════════════╝

SUMMARY_HEAD

cat containers.list | while read container; do
    cat >> CONTAINER_SUMMARY.txt << SUMMARY_ITEM

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
容器: $container
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

【资源限制】
SUMMARY_ITEM
    
    grep "limits\." "${container}.config.yaml" >> CONTAINER_SUMMARY.txt 2>/dev/null || echo "  无资源限制" >> CONTAINER_SUMMARY.txt
    
    echo "" >> CONTAINER_SUMMARY.txt
    echo "【端口映射】" >> CONTAINER_SUMMARY.txt
    grep -A 4 "nat-" "${container}.devices.yaml" >> CONTAINER_SUMMARY.txt 2>/dev/null || echo "  无端口映射" >> CONTAINER_SUMMARY.txt
    
    echo "" >> CONTAINER_SUMMARY.txt
    echo "【密码信息】" >> CONTAINER_SUMMARY.txt
    grep -v "^#" "${container}.passwords.txt" | head -5 >> CONTAINER_SUMMARY.txt
    
    echo "" >> CONTAINER_SUMMARY.txt
done
echo "✓ 配置摘要已生成"
echo ""

echo "[5/5] 生成恢复脚本..."
cat > restore_containers.sh << 'RESTORE_SCRIPT_EOF'
#!/bin/bash
#===============================================
# 容器配置和密码恢复脚本
#===============================================

set -e

BACKUP_DIR="$(pwd)"
NEW_POOL="disk"
DEFAULT_IMAGE="debian12"  # 根据实际情况修改

echo "╔════════════════════════════════════════════╗"
echo "║      恢复容器配置（包含密码）              ║"
echo "╚════════════════════════════════════════════╝"
echo ""
echo "备份目录: $BACKUP_DIR"
echo "目标存储池: $NEW_POOL"
echo "默认镜像: $DEFAULT_IMAGE"
echo ""

read -p "确认开始恢复? [y/N]: " confirm
if [[ ! "${confirm,,}" =~ ^(y|yes)$ ]]; then
    echo "已取消"
    exit 0
fi

TOTAL=$(wc -l < containers.list)
CURRENT=0

cat containers.list | while read container; do
    CURRENT=$((CURRENT + 1))
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "[$CURRENT/$TOTAL] 恢复容器: $container"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    
    # 提取配置
    CPU_LIMIT=$(grep "limits.cpu.allowance:" "${container}.config.yaml" 2>/dev/null | awk '{print $2}' | tr -d '"')
    MEMORY_LIMIT=$(grep "limits.memory:" "${container}.config.yaml" 2>/dev/null | awk '{print $2}' | tr -d '"')
    DISK_SIZE=$(cat "${container}.disk_size.txt" 2>/dev/null || echo "2048")
    
    # 提取密码
    PASSWORD=$(grep "^user.password:" "${container}.passwords.txt" 2>/dev/null | cut -d' ' -f2-)
    ROOT_PASSWORD=$(grep "^user.root_password:" "${container}.passwords.txt" 2>/dev/null | cut -d' ' -f2-)
    
    # 清理密码中的"未设置"标记
    [ "$PASSWORD" = "未设置" ] && PASSWORD=""
    [ "$ROOT_PASSWORD" = "未设置" ] && ROOT_PASSWORD=""
    
    # 使用第一个找到的密码
    FINAL_PASSWORD="${PASSWORD:-$ROOT_PASSWORD}"
    
    echo "  配置信息:"
    echo "    CPU限制: ${CPU_LIMIT:-未设置}"
    echo "    内存限制: ${MEMORY_LIMIT:-未设置}"
    echo "    磁盘大小: ${DISK_SIZE}MB"
    echo "    密码: ${FINAL_PASSWORD:-未找到，需手动设置}"
    echo ""
    
    # 1. 创建容器
    echo "  [1/6] 创建容器..."
    if lxc init "$DEFAULT_IMAGE" "$container" -s "$NEW_POOL" 2>&1; then
        echo "  ✓ 容器已创建"
    else
        echo "  ✗ 创建失败，跳过"
        continue
    fi
    
    # 2. 应用资源限制
    echo "  [2/6] 应用资源限制..."
    [ -n "$CPU_LIMIT" ] && lxc config set "$container" limits.cpu.allowance "$CPU_LIMIT"
    [ -n "$MEMORY_LIMIT" ] && lxc config set "$container" limits.memory "$MEMORY_LIMIT"
    echo "  ✓ 资源限制已设置"
    
    # 3. 设置磁盘大小
    echo "  [3/6] 设置磁盘..."
    lxc config device set "$container" root size="${DISK_SIZE}MB"
    echo "  ✓ 磁盘已设置"
    
    # 4. 恢复端口映射
    echo "  [4/6] 恢复端口映射..."
    PORT_COUNT=0
    grep -E "^  nat-" "${container}.devices.yaml" 2>/dev/null | while read line; do
        device_name=$(echo "$line" | awk '{print $1}' | tr -d ':')
        
        # 获取这个设备的完整配置
        listen=$(grep -A 5 "^  $device_name:" "${container}.devices.yaml" | grep "listen:" | awk '{print $2}')
        connect=$(grep -A 5 "^  $device_name:" "${container}.devices.yaml" | grep "connect:" | awk '{print $2}')
        
        if [ -n "$listen" ] && [ -n "$connect" ]; then
            echo "    添加端口映射: $device_name ($listen -> $connect)"
            lxc config device add "$container" "$device_name" proxy \
                listen="$listen" connect="$connect" bind=host 2>/dev/null || echo "    ! 端口映射添加失败"
            PORT_COUNT=$((PORT_COUNT + 1))
        fi
    done
    echo "  ✓ 端口映射已恢复 ($PORT_COUNT 个)"
    
    # 5. 恢复用户属性
    echo "  [5/6] 恢复用户属性..."
    grep "^  user\." "${container}.config.yaml" 2>/dev/null | while IFS= read line; do
        key=$(echo "$line" | awk '{print $1}' | tr -d ':')
        value=$(echo "$line" | cut -d' ' -f2- | sed 's/^"\(.*\)"$/\1/')
        lxc config set "$container" "$key" "$value" 2>/dev/null || true
    done
    echo "  ✓ 用户属性已恢复"
    
    # 6. 设置密码
    echo "  [6/6] 设置密码..."
    if [ -n "$FINAL_PASSWORD" ]; then
        # 启动容器以设置密码
        lxc start "$container"
        sleep 5
        echo "root:$FINAL_PASSWORD" | lxc exec "$container" -- chpasswd 2>/dev/null && echo "  ✓ 密码已设置" || echo "  ! 密码设置失败"
        lxc stop "$container"
    else
        echo "  ⚠️  未找到密码，需要手动设置"
        echo "     设置密码命令: lxc exec $container -- passwd root"
    fi
    
    echo "  ✓ $container 恢复完成"
done

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✓ 所有容器已恢复"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "后续操作:"
echo "  1. 启动所有容器:"
echo "     lxc start --all"
echo ""
echo "  2. 查看容器状态:"
echo "     lxc list"
echo ""
echo "  3. 对于未找到密码的容器，手动设置:"
echo "     lxc exec <容器名> -- passwd root"
RESTORE_SCRIPT_EOF

chmod +x restore_containers.sh
echo "✓ 恢复脚本已生成"
echo ""

echo "╔════════════════════════════════════════════╗"
echo "║      ✓ 备份完成！                          ║"
echo "╚════════════════════════════════════════════╝"
echo ""
echo "备份位置: $BACKUP_DIR"
echo "容器数量: $CONTAINER_COUNT"
echo ""
echo "重要文件:"
echo "  - containers.list           # 容器列表"
echo "  - PASSWORD_SUMMARY.txt      # 密码摘要"
echo "  - CONTAINER_SUMMARY.txt     # 完整配置摘要"
echo "  - restore_containers.sh     # 恢复脚本"
echo ""
echo "查看密码摘要:"
echo "  cat $BACKUP_DIR/PASSWORD_SUMMARY.txt"
echo ""
echo "查看完整配置:"
echo "  cat $BACKUP_DIR/CONTAINER_SUMMARY.txt"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "下一步: 清理磁盘空间并重建存储池"
echo "  bash /root/server/cj/3_rebuild_storage.sh"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

