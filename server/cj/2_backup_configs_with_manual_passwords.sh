#!/bin/bash
#===============================================
# 步骤 2: 备份所有容器配置（支持手动输入密码）
#===============================================

set -e

echo "╔════════════════════════════════════════════╗"
echo "║      备份容器配置（支持手动输入密码）      ║"
echo "╚════════════════════════════════════════════╝"
echo ""

BACKUP_DIR="/root/lxd-container-configs-$(date +%Y%m%d_%H%M%S)"
mkdir -p "$BACKUP_DIR"
cd "$BACKUP_DIR"

echo "[1/6] 备份容器列表..."
lxc list -c n --format csv > containers.list
CONTAINER_COUNT=$(wc -l < containers.list)
echo "✓ 找到 $CONTAINER_COUNT 个容器"
echo ""

echo "[2/6] 备份容器配置..."
cat containers.list | while read container; do
    echo "  备份: $container"
    
    # 完整配置
    lxc config show "$container" > "${container}.config.yaml"
    
    # 设备配置
    lxc config device show "$container" > "${container}.devices.yaml"
    
    # 提取所有可能的密码（虽然为空）
    echo "# 密码信息 - $(date)" > "${container}.passwords.txt"
    echo "# 系统未找到自动保存的密码" >> "${container}.passwords.txt"
    echo "# 请在下方手动填写密码（如果知道）" >> "${container}.passwords.txt"
    echo "" >> "${container}.passwords.txt"
    echo "manual_password: " >> "${container}.passwords.txt"
    
    # 提取所有user属性
    echo "" >> "${container}.passwords.txt"
    echo "# 所有用户属性:" >> "${container}.passwords.txt"
    lxc config show "$container" | grep "^  user\." >> "${container}.passwords.txt" || echo "无用户属性" >> "${container}.passwords.txt"
    
    # 其他重要属性
    lxc config get "$container" user.disk_size_mb 2>/dev/null > "${container}.disk_size.txt" || echo "2048" > "${container}.disk_size.txt"
    lxc config get "$container" user.flow_limit_gb 2>/dev/null > "${container}.flow_limit.txt" || echo "" > "${container}.flow_limit.txt"
    lxc config get "$container" user.nat_acl_limit 2>/dev/null > "${container}.nat_limit.txt" || echo "" > "${container}.nat_limit.txt"
done
echo "✓ 配置备份完成"
echo ""

echo "[3/6] 是否手动输入密码？"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "由于密码未自动保存，你可以："
echo "  1) 现在手动输入每个容器的密码"
echo "  2) 稍后编辑备份文件填写密码"
echo "  3) 跳过，恢复后手动设置密码"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
read -p "是否现在输入密码? [y/N]: " input_passwords

if [[ "${input_passwords,,}" =~ ^(y|yes)$ ]]; then
    echo ""
    echo "请为每个容器输入密码（直接回车跳过该容器）"
    echo ""
    
    cat containers.list | while read container; do
        echo -n "[$container] 密码: "
        read password
        if [ -n "$password" ]; then
            sed -i "s|manual_password: |manual_password: $password|" "${container}.passwords.txt"
            echo "  ✓ 已记录"
        else
            echo "  - 跳过"
        fi
    done
    
    echo ""
    echo "✓ 密码输入完成"
else
    echo ""
    echo "✓ 跳过密码输入"
    echo ""
    echo "稍后可以编辑以下文件添加密码："
    echo "  $BACKUP_DIR/*.passwords.txt"
    echo ""
    echo "格式："
    echo "  manual_password: 你的密码"
fi
echo ""

echo "[4/6] 生成密码摘要..."
cat > PASSWORD_SUMMARY.txt << 'EOF'
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        容器密码信息摘要
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

EOF

cat containers.list | while read container; do
    echo "" >> PASSWORD_SUMMARY.txt
    echo "容器: $container" >> PASSWORD_SUMMARY.txt
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━" >> PASSWORD_SUMMARY.txt
    cat "${container}.passwords.txt" | grep "manual_password:" >> PASSWORD_SUMMARY.txt
    echo "" >> PASSWORD_SUMMARY.txt
done
echo "✓ 密码摘要已生成"
echo ""

echo "[5/6] 生成配置摘要..."
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
    echo "【密码】" >> CONTAINER_SUMMARY.txt
    grep "manual_password:" "${container}.passwords.txt" >> CONTAINER_SUMMARY.txt
    
    echo "" >> CONTAINER_SUMMARY.txt
done
echo "✓ 配置摘要已生成"
echo ""

echo "[6/6] 生成恢复脚本..."
cat > restore_containers.sh << 'RESTORE_SCRIPT_EOF'
#!/bin/bash
#===============================================
# 容器配置恢复脚本（支持手动密码）
#===============================================

set -e

BACKUP_DIR="$(pwd)"
NEW_POOL="disk"
DEFAULT_IMAGE="debian12"  # 根据实际情况修改

echo "╔════════════════════════════════════════════╗"
echo "║      恢复容器配置                          ║"
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
    
    # 提取手动输入的密码
    MANUAL_PASSWORD=$(grep "^manual_password:" "${container}.passwords.txt" 2>/dev/null | cut -d' ' -f2-)
    [ "$MANUAL_PASSWORD" = "" ] && MANUAL_PASSWORD=""
    
    echo "  配置信息:"
    echo "    CPU限制: ${CPU_LIMIT:-未设置}"
    echo "    内存限制: ${MEMORY_LIMIT:-未设置}"
    echo "    磁盘大小: ${DISK_SIZE}MB"
    echo "    密码: ${MANUAL_PASSWORD:-未提供，需手动设置}"
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
        
        listen=$(grep -A 5 "^  $device_name:" "${container}.devices.yaml" | grep "listen:" | awk '{print $2}')
        connect=$(grep -A 5 "^  $device_name:" "${container}.devices.yaml" | grep "connect:" | awk '{print $2}')
        
        if [ -n "$listen" ] && [ -n "$connect" ]; then
            echo "    添加: $device_name ($listen -> $connect)"
            lxc config device add "$container" "$device_name" proxy \
                listen="$listen" connect="$connect" bind=host 2>/dev/null || echo "    ! 添加失败"
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
    if [ -n "$MANUAL_PASSWORD" ]; then
        lxc start "$container"
        sleep 5
        echo "root:$MANUAL_PASSWORD" | lxc exec "$container" -- chpasswd 2>/dev/null && echo "  ✓ 密码已设置" || echo "  ! 密码设置失败"
        lxc stop "$container"
    else
        echo "  ⚠️  未提供密码"
        echo "     手动设置: lxc exec $container -- passwd root"
    fi
    
    echo "  ✓ $container 恢复完成"
done

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✓ 恢复完成"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "启动容器:"
echo "  lxc start --all"
echo ""
echo "对于未设置密码的容器:"
echo "  lxc exec <容器名> -- passwd root"
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
echo "  - PASSWORD_SUMMARY.txt      # 密码摘要"
echo "  - CONTAINER_SUMMARY.txt     # 完整配置"
echo "  - restore_containers.sh     # 恢复脚本"
echo ""
echo "查看密码摘要:"
echo "  cat $BACKUP_DIR/PASSWORD_SUMMARY.txt"
echo ""
echo "如果需要补充密码，编辑对应的 .passwords.txt 文件:"
echo "  nano $BACKUP_DIR/<容器名>.passwords.txt"
echo "  修改: manual_password: 你的密码"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "下一步: 清理磁盘空间并重建存储池"
echo "  bash /root/server/cj/3_rebuild_storage.sh"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

