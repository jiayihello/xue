#!/bin/bash

# --- LXD 容器网络速率与磁盘批量管理脚本 ---

# 帮助信息
usage() {
    echo "用法: $0 [命令] [参数]"
    echo ""
    echo "命令:"
    echo "  view                     批量查看所有容器的网络速率和磁盘大小。"
    echo "  set <下载速率> <上传速率>   批量设置所有容器的速率限制。"
    echo "                           (例如: $0 set 100Mbit 50Mbit)"
    echo "  set-by-disk <磁盘MB> <下载> <上传> [<磁盘MB> <下载> <上传>...]"
    echo "                           根据磁盘大小分组设置速率限制。"
    echo "                           (例如: $0 set-by-disk 1024 100Mbit 50Mbit 2048 200Mbit 100Mbit)"
    echo "  unset                    批量移除所有容器上单独设置的速率限制。"
    echo ""
    exit 1
}

# --- 辅助函数 ---

# 格式化速率
format_rate() {
    local rate=$1
    if [[ -z "$rate" ]]; then
        echo "未设置"
    elif [[ "$rate" =~ ^[0-9]+$ ]]; then
        echo "$((rate / 1000000)) Mbit/s"
    else
        echo "$rate"
    fi
}

# 获取有效的磁盘大小 (MB)
get_disk_size_mb() {
    local container=$1
    local size_str
    size_str=$(lxc config device get "$container" root size 2>/dev/null)
    if [ -z "$size_str" ]; then
        size_str=$(lxc profile device get default root size 2>/dev/null)
    fi
    if [[ "$size_str" == *"GB" ]]; then
        echo "$((${size_str//GB/} * 1024))"
    elif [[ "$size_str" == *"MB" ]]; then
        echo "${size_str//MB/}"
    else
        echo ""
    fi
}

# 智能设置/覆盖速率限制
apply_rate_limit() {
    local container=$1
    local ingress=$2
    local egress=$3

    # 检查 eth0 设备是否已在实例级别上被覆盖
    # 'lxc config device show' 只会列出被覆盖的设备
    if lxc config device show "$container" | grep -q '^eth0:'; then
        # 如果已被覆盖，使用 set 命令修改
        lxc config device set "$container" eth0 limits.ingress "$ingress" >/dev/null
        lxc config device set "$container" eth0 limits.egress "$egress" >/dev/null
    else
        # 如果未被覆盖 (继承自 profile)，使用 override 命令创建
        lxc config device override "$container" eth0 limits.ingress="$ingress" limits.egress="$egress" >/dev/null
    fi
    echo "已设置: $container"
}


# --- 主逻辑 ---

CONTAINERS=$(lxc list --format csv -c n)
if [ -z "$CONTAINERS" ]; then
    echo "未找到任何容器。"; exit 0;
fi

COMMAND=$1
shift

case "$COMMAND" in
    view)
        # ... (view command remains the same)
        default_ingress=$(lxc profile device get default eth0 limits.ingress 2>/dev/null)
        default_egress=$(lxc profile device get default eth0 limits.egress 2>/dev/null)
        default_disk=$(lxc profile device get default root size 2>/dev/null)
        echo "--- 默认 Profile (default) ---"
        echo "  下载 (ingress): $(format_rate "$default_ingress")"
        echo "  上传 (egress):   $(format_rate "$default_egress")"
        echo "  磁盘大小:       ${default_disk:-未设置}"
        echo "------------------------------------"
        for container in $CONTAINERS; do
          echo "--- 容器: $container ---"
          ingress=$(lxc config device get "$container" eth0 limits.ingress 2>/dev/null)
          egress=$(lxc config device get "$container" eth0 limits.egress 2>/dev/null)
          disk=$(lxc config device get "$container" root size 2>/dev/null)
          echo "  下载 (ingress): $([ -n "$ingress" ] && format_rate "$ingress" || echo "继承自 Profile ($(format_rate "$default_ingress"))")"
          echo "  上传 (egress):   $([ -n "$egress" ] && format_rate "$egress" || echo "继承自 Profile ($(format_rate "$default_egress"))")"
          echo "  磁盘大小:       $([ -n "$disk" ] && echo "$disk" || echo "继承自 Profile (${default_disk:-未设置})")"
        done
        ;;

    set)
        INGRESS=$1; EGRESS=$2
        if [ -z "$INGRESS" ] || [ -z "$EGRESS" ]; then usage; fi
        echo "将对所有容器统一设置速率: 下载 $INGRESS, 上传 $EGRESS"
        read -p "您确定吗？ (输入 y 继续): " confirm
        if [ "$confirm" != "y" ]; then echo "操作已取消。"; exit 0; fi
        for container in $CONTAINERS; do
            apply_rate_limit "$container" "$INGRESS" "$EGRESS"
        done
        echo "全部设置完成。"
        ;;

    set-by-disk)
        if [ $(($# % 3)) -ne 0 ]; then echo "错误: 参数数量必须是3的倍数。"; usage; fi
        declare -A plan
        echo "正在生成变更计划..."
        while [ $# -ge 3 ]; do
            disk_size_arg=$1; ingress_arg=$2; egress_arg=$3; shift 3
            for container in $CONTAINERS; do
                container_disk_mb=$(get_disk_size_mb "$container")
                if [ "$container_disk_mb" == "$disk_size_arg" ]; then
                    plan["$container"]="$ingress_arg $egress_arg"
                fi
            done
        done
        if [ ${#plan[@]} -eq 0 ]; then echo "未找到符合条件的容器。"; exit 0; fi
        echo "将执行以下变更:"
        for container in $(printf "%s\n" "${!plan[@]}" | sort); do
            read -r ingress egress <<< "${plan[$container]}"
            printf "  %-15s -> 下载 %s, 上传 %s\n" "$container" "$ingress" "$egress"
        done
        read -p "您确定要应用这些变更吗？ (输入 y 继续): " confirm
        if [ "$confirm" != "y" ]; then echo "操作已取消。"; exit 0; fi
        echo "正在应用变更..."
        for container in $(printf "%s\n" "${!plan[@]}" | sort); do
            read -r ingress egress <<< "${plan[$container]}"
            apply_rate_limit "$container" "$ingress" "$egress"
        done
        echo "全部设置完成。"
        ;;

    unset)
        echo "将移除所有容器的单独速率限制..."
        read -p "您确定吗？ (输入 y 继续): " confirm
        if [ "$confirm" != "y" ]; then echo "操作已取消。"; exit 0; fi
        for container in $CONTAINERS; do
            # unset 命令对于 override 和 set 的设备都有效
            lxc config device unset "$container" eth0 limits.ingress 2>/dev/null
            lxc config device unset "$container" eth0 limits.egress 2>/dev/null
            echo "已移除: $container"
        done
        echo "全部移除完成。"
        ;;

    *)
        usage
        ;;
esac

