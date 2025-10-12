#!/bin/bash

echo "=== LXD 资源清理工具 ==="

echo "1. 清理所有容器..."
lxc list --format csv -c n | while read container; do
    if [ ! -z "$container" ]; then
        echo "  删除容器: $container"
        lxc delete -f "$container" 2>/dev/null || true
    fi
done

echo "2. 清理临时镜像..."
lxc image list --format csv -c l | grep -E "(base|config)" | while read alias; do
    if [ ! -z "$alias" ]; then
        echo "  删除镜像: $alias"
        lxc image delete "$alias" 2>/dev/null || true
    fi
done

echo "3. 清理临时文件..."
rm -f rootfs.tar.xz meta.tar.xz metadata.yaml meta-fixed.tar.xz 2>/dev/null || true

echo "=== 清理完成 ==="
echo "现在可以重新运行构建命令了"
