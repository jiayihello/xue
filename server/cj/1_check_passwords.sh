#!/bin/bash
#===============================================
# 步骤 1: 检查容器密码配置
# 用途：检查密码是否存储在 LXD 配置中
#===============================================

echo "╔════════════════════════════════════════════╗"
echo "║      检查容器密码配置                      ║"
echo "╚════════════════════════════════════════════╝"
echo ""

lxc list -c n --format csv | while read container; do
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "容器: $container"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    
    # 检查常见的密码存储位置
    PASSWORD=$(lxc config get "$container" user.password 2>/dev/null)
    ROOT_PASSWORD=$(lxc config get "$container" user.root_password 2>/dev/null)
    DEFAULT_PASSWORD=$(lxc config get "$container" user.default_password 2>/dev/null)
    
    # 检查 cloud-init 配置
    CLOUD_INIT=$(lxc config get "$container" cloud-init.user-data 2>/dev/null | grep -i "password" || echo "")
    
    # 检查所有 user.* 属性
    USER_ATTRS=$(lxc config show "$container" | grep "^  user\." | grep -i "pass" || echo "")
    
    # 显示结果
    FOUND=0
    
    if [ -n "$PASSWORD" ]; then
        echo "✓ user.password: $PASSWORD"
        FOUND=1
    fi
    
    if [ -n "$ROOT_PASSWORD" ]; then
        echo "✓ user.root_password: $ROOT_PASSWORD"
        FOUND=1
    fi
    
    if [ -n "$DEFAULT_PASSWORD" ]; then
        echo "✓ user.default_password: $DEFAULT_PASSWORD"
        FOUND=1
    fi
    
    if [ -n "$CLOUD_INIT" ]; then
        echo "✓ cloud-init 中发现密码配置"
        FOUND=1
    fi
    
    if [ -n "$USER_ATTRS" ]; then
        echo "✓ 其他密码相关属性:"
        echo "$USER_ATTRS"
        FOUND=1
    fi
    
    if [ $FOUND -eq 0 ]; then
        echo "⚠️  未在配置中找到密码信息"
        echo "   密码可能只存储在容器内部（无法恢复）"
    fi
    
    echo ""
done

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✓ 检查完成"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "如果大部分容器都显示了密码，说明可以完整恢复！"
echo "如果未找到密码，恢复后需要手动重新设置密码。"
echo ""
echo "下一步: 执行备份脚本"
echo "  bash /root/server/cj/2_backup_configs.sh"

