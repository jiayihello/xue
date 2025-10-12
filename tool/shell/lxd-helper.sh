#!/bin/bash
readonly BACKUPS_ROOT_DIR="/root/lxc_image_backups"
set -o errexit
set -o nounset
set -o pipefail
trap 'printf "\033[0m"; exit' INT TERM EXIT
readonly COLOR_RESET='\033[0m'
readonly COLOR_GREEN='\033[0;32m'
readonly COLOR_YELLOW='\033[1;33m'
readonly COLOR_RED='\033[0;31m'
readonly COLOR_BLUE='\033[0;34m'
readonly COLOR_CYAN='\033[0;36m'
msg() {
    local color_name="$1"
    local message="$2"
    local color_var="COLOR_${color_name^^}"
    printf '%b%s%b\n' "${!color_var}" "${message}" "${COLOR_RESET}"
}
press_any_key() {
    echo ""
    read -n 1 -s -r -p "按任意键返回主菜单..."
}
check_root() {
    if [[ "$(id -u)" -ne 0 ]]; then
        msg "RED" "错误: 此脚本必须以 root 权限运行。请使用 'sudo bash $0'"
        exit 1
    fi
}
check_dependencies() {
    msg "BLUE" "正在检查核心依赖..."
    declare -A cmd_pkg_map
    cmd_pkg_map=(
        [jq]="jq"
        [btrfs]="btrfs-progs"
        [curl]="curl"
        [lsblk]="util-linux"
        [wc]="coreutils"
    )
    local missing_pkgs=()
    for cmd in "${!cmd_pkg_map[@]}"; do
        if ! command -v "$cmd" &>/dev/null; then
            missing_pkgs+=("${cmd_pkg_map[$cmd]}")
        fi
    done
    local unique_missing_pkgs
    unique_missing_pkgs=($(printf "%s\n" "${missing_pkgs[@]}" | sort -u | tr '\n' ' '))
    if [ ${#unique_missing_pkgs[@]} -gt 0 ]; then
        msg "YELLOW" "检测到缺失的依赖包: ${unique_missing_pkgs[*]}，将自动尝试安装..."
        if command -v apt-get &>/dev/null; then
            read -p "$(msg "YELLOW" "是否运行 'apt-get update' 来更新软件包列表? (y/N): ")" confirm_update
            if [[ "${confirm_update}" =~ ^[yY]$ ]]; then
                DEBIAN_FRONTEND=noninteractive apt-get update -y >/dev/null
            fi
            if ! DEBIAN_FRONTEND=noninteractive apt-get install -y "${unique_missing_pkgs[@]}"; then
                msg "RED" "自动安装依赖 (${unique_missing_pkgs[*]}) 失败。请手动安装后重试。"
                exit 1
            fi
            msg "GREEN" "依赖 ${unique_missing_pkgs[*]} 安装成功。"
        else
            msg "RED" "错误: 此脚本依赖于 'apt' 来自动安装缺失的包。请手动安装: ${unique_missing_pkgs[*]}"
            exit 1
        fi
    fi
    for cmd in "${!cmd_pkg_map[@]}"; do
         if ! command -v "$cmd" &>/dev/null; then
            msg "RED" "致命错误: 核心命令 '$cmd' 未找到且无法自动安装。脚本无法继续。"
            exit 1
        fi
    done
    msg "GREEN" "✓ 核心依赖检查通过。"
}
is_lxd_installed() {
    command -v lxd &>/dev/null || [ -x /snap/bin/lxd ]
}
configure_snap_path() {
    msg "BLUE" "配置 Snap 路径到系统 PATH..."

    # 确保 /snap/bin 在 PATH 中
    if [[ ":$PATH:" != *":/snap/bin:"* ]]; then
        echo 'export PATH=$PATH:/snap/bin' | sudo tee -a /etc/profile.d/snap_path.sh >/dev/null
        export PATH=$PATH:/snap/bin
        msg "GREEN" "✓ Snap 路径已添加到系统 PATH"
    else
        msg "GREEN" "✓ Snap 路径已存在于系统 PATH 中"
    fi

    # 创建符号链接以确保命令可用
    if [ -x /snap/bin/lxd ] && [ ! -x /usr/local/bin/lxd ]; then
        sudo ln -sf /snap/bin/lxd /usr/local/bin/lxd
        msg "GREEN" "✓ 创建 lxd 符号链接"
    fi

    if [ -x /snap/bin/lxc ] && [ ! -x /usr/local/bin/lxc ]; then
        sudo ln -sf /snap/bin/lxc /usr/local/bin/lxc
        msg "GREEN" "✓ 创建 lxc 符号链接"
    fi

    # 不使用source，避免影响脚本执行环境
    msg "GREEN" "✓ Snap 路径配置完成"
}
initialize_lxd() {
    msg "BLUE" "初始化 LXD..."

    # 等待 LXD snap 服务完全启动
    msg "YELLOW" "等待 LXD snap 服务启动..."
    local retry_count=0
    local max_retries=10

    while [ $retry_count -lt $max_retries ]; do
        if sudo snap services lxd | grep -q "active"; then
            msg "GREEN" "✓ LXD snap 服务已启动"
            break
        fi
        sleep 2
        ((retry_count++))
        msg "YELLOW" "等待中... ($retry_count/$max_retries)"
    done

    if [ $retry_count -eq $max_retries ]; then
        msg "YELLOW" "警告: LXD 服务状态检查超时，继续尝试初始化..."
    fi

    # 使用完整路径或确保命令可用
    local lxd_cmd
    if command -v lxd &>/dev/null; then
        lxd_cmd="lxd"
    elif [ -x /snap/bin/lxd ]; then
        lxd_cmd="/snap/bin/lxd"
    elif [ -x /usr/local/bin/lxd ]; then
        lxd_cmd="/usr/local/bin/lxd"
    else
        msg "RED" "错误: 无法找到 lxd 命令"
        return 1
    fi

    msg "BLUE" "使用命令: $lxd_cmd"

    # 执行初始化
    msg "BLUE" "正在执行 lxd init --auto..."
    if sudo "$lxd_cmd" init --auto; then
        msg "GREEN" "✓ LXD 初始化成功"

        # 验证安装
        local lxd_version
        lxd_version=$(sudo "$lxd_cmd" --version 2>/dev/null || echo "未知版本")
        msg "GREEN" "✓ LXD 版本: $lxd_version"

        # 测试 lxc 命令
        local lxc_cmd
        if command -v lxc &>/dev/null; then
            lxc_cmd="lxc"
        elif [ -x /snap/bin/lxc ]; then
            lxc_cmd="/snap/bin/lxc"
        elif [ -x /usr/local/bin/lxc ]; then
            lxc_cmd="/usr/local/bin/lxc"
        else
            msg "YELLOW" "警告: lxc 命令不可用，但 lxd 已安装"
            return 0
        fi

        msg "BLUE" "测试 LXC 命令..."
        if sudo "$lxc_cmd" list >/dev/null 2>&1; then
            msg "GREEN" "✓ LXC 命令测试成功"

            # 检查网络是否创建 - 使用更可靠的检测方法
            msg "BLUE" "检查网络桥接配置..."
            local network_output
            network_output=$(sudo "$lxc_cmd" network list --format csv 2>/dev/null | cut -d, -f1)

            if echo "$network_output" | grep -q "^lxdbr0$"; then
                msg "GREEN" "✓ LXD 网络桥接 (lxdbr0) 已创建"
            elif echo "$network_output" | grep -q "bridge"; then
                # 检查是否有其他桥接网络
                local bridge_networks
                bridge_networks=$(sudo "$lxc_cmd" network list --format csv 2>/dev/null | grep ",bridge," | cut -d, -f1 | tr '\n' ' ')
                if [[ -n "$bridge_networks" ]]; then
                    msg "GREEN" "✓ LXD 网络桥接已创建: $bridge_networks"
                else
                    msg "YELLOW" "警告: 未检测到网络桥接"
                fi
            else
                msg "YELLOW" "警告: 未检测到网络桥接，但这可能是正常的"
            fi

            # 额外检查：验证默认profile的网络配置
            if sudo "$lxc_cmd" profile show default | grep -q "network:"; then
                msg "GREEN" "✓ 默认profile网络配置正常"
            fi
        else
            msg "YELLOW" "警告: LXC 命令测试失败，但安装可能仍然成功"
        fi
    else
        msg "RED" "✗ LXD 初始化失败"
        return 1
    fi
}
run_with_lxd_check() {
    if ! is_lxd_installed; then
        msg "RED" "错误: 操作失败，因为 LXD 未安装。请先从主菜单选择 '1' 进行安装。"
        return 1
    fi
    "$@"
}
install_lxd() {
    msg "BLUE" "--- LXD 环境安装与配置 ---"
    if is_lxd_installed; then
        msg "GREEN" "LXD 已经安装。"
        lxd --version
        read -p "$(msg "YELLOW" "是否要强制重新进行自动化配置 (lxd init --auto)? [y/N]: ")" re_init
        if [[ "${re_init}" =~ ^[yY]$ ]]; then
            msg "YELLOW" "正在重新运行 lxd init --auto..."
            if sudo lxd init --auto; then
                msg "GREEN" "LXD 重新初始化成功。"
            else
                msg "RED" "LXD 重新初始化失败，请检查上面的错误信息。"
            fi
        fi
        return 0
    fi
    if ! command -v apt-get &>/dev/null; then
        msg "RED" "错误: 本安装脚本仅支持使用 'apt' 的系统 (如 Debian, Ubuntu)。"
        return 1
    fi
    msg "YELLOW" "检测到 LXD 未安装，即将开始 Snap 安装流程。"
    read -p "$(msg "YELLOW" "确认开始安装 LXD 吗? [y/N]: ")" confirm
    if [[ ! "${confirm}" =~ ^[yY]$ ]]; then
        msg "BLUE" "操作已由用户取消。"
        return
    fi
    local steps=(
        "更新软件包列表;sudo apt-get update -y"
        "安装 snapd;sudo apt-get install -y snapd"
        "安装 snap core;sudo snap install core"
        "通过 Snap 安装 LXD;sudo snap install lxd"
        "配置 Snap 路径;configure_snap_path"
        "初始化 LXD;initialize_lxd"
    )
    for i in "${!steps[@]}"; do
        local description="${steps[$i]%%;*}"
        local command="${steps[$i]#*;}"
        msg "BLUE" "步骤 $((i+1))/${#steps[@]}: ${description}..."

        # 特殊处理函数调用
        if [[ "$command" == "configure_snap_path" ]] || [[ "$command" == "initialize_lxd" ]]; then
            if ! "$command"; then
                msg "RED" "错误: 在执行 '${description}' 时失败。请检查错误日志并手动修复。"
                return 1
            fi
        else
            if ! eval "$command"; then
                msg "RED" "错误: 在执行 '${description}' 时失败。请检查错误日志并手动修复。"
                return 1
            fi
        fi
    done
    echo ""
    msg "GREEN" "==============================================="
    msg "GREEN" "✓ LXD (via Snap) 安装并初始化完成！"

    # 显示版本信息
    local lxd_cmd
    if command -v lxd &>/dev/null; then
        lxd_cmd="lxd"
    elif [ -x /snap/bin/lxd ]; then
        lxd_cmd="/snap/bin/lxd"
    else
        msg "YELLOW" "警告: 无法找到 lxd 命令来显示版本信息"
        msg "GREEN" "==============================================="
        return 0
    fi

    local version_info
    version_info=$(sudo "$lxd_cmd" --version 2>/dev/null || echo "版本信息获取失败")
    msg "GREEN" "LXD 版本: $version_info"

    # 提供使用提示
    msg "CYAN" "使用提示:"
    msg "CYAN" "- 如果命令不可用，请运行: source /etc/profile"
    msg "CYAN" "- 或者重新登录以加载新的 PATH 设置"
    msg "GREEN" "==============================================="
}
backup_images() {
    msg "BLUE" "--- LXD 镜像备份 ---"
    local image_aliases_list
    image_aliases_list=$(lxc image list --format=json | jq -r '.[] | select(.aliases | length > 0) | .aliases[0].name')
    if [[ -z "$image_aliases_list" ]]; then
        msg "YELLOW" "提示: 未找到任何带有别名(alias)的本地 LXD 镜像可供备份。"
        return
    fi
    local image_count
    image_count=$(echo "$image_aliases_list" | wc -l)
    msg "YELLOW" "检测到 ${image_count} 个带别名的本地镜像，将逐一备份。"
    read -p "$(msg "YELLOW" "确认开始备份吗? (y/N): ")" confirm
    if [[ ! "${confirm}" =~ ^[yY]$ ]]; then
        msg "BLUE" "操作已由用户取消。"
        return
    fi
    local backup_dir="${BACKUPS_ROOT_DIR}/lxc_image_backups_$(date +%Y%m%d_%H%M%S)"
    mkdir -p "$backup_dir"
    msg "YELLOW" "所有备份文件将存放在: ${backup_dir}"
    echo ""
    msg "BLUE" "开始导出镜像..."
    local success_count=0
    local fail_count=0
    set +o errexit
    while read -r alias; do
        if [[ -z "$alias" ]]; then continue; fi
        local filename="${backup_dir}/${alias}.tar.gz"
        msg "CYAN" "  -> 正在导出 $alias ..."
        local stderr
        if stderr=$(lxc image export "$alias" "${filename%.tar.gz}" 2>&1); then
            msg "GREEN" "     ✓ 导出成功: ${filename}"
            ((success_count++))
        else
            msg "RED" "     ✗ 错误: 导出 '$alias' 失败。"
            msg "RED" "       LXD 错误信息: ${stderr}"
            ((fail_count++))
        fi
    done <<< "$image_aliases_list"
    set -o errexit
    echo ""
    msg "GREEN" "==============================================="
    msg "GREEN" "备份流程完成。"
    msg "GREEN" "成功: $success_count, 失败: $fail_count"
    if [[ $success_count -gt 0 ]]; then
        msg "YELLOW" "备份文件列表:"
        ls -lh "$backup_dir"
    fi
    msg "GREEN" "==============================================="
}
restore_images() {
    msg "BLUE" "--- LXD 镜像恢复 ---"
    if ! [ -d "${BACKUPS_ROOT_DIR}" ]; then
        msg "RED" "错误: 备份根目录 '${BACKUPS_ROOT_DIR}' 不存在。"
        return 1
    fi
    local backup_dirs=()
    mapfile -t backup_dirs < <(find "${BACKUPS_ROOT_DIR}" -mindepth 1 -maxdepth 1 -type d -name "lxc_image_backups_*" -printf '%T@ %p\n' | sort -rn | cut -d' ' -f2-)
    if [ ${#backup_dirs[@]} -eq 0 ]; then
        msg "RED" "错误: 在 '${BACKUPS_ROOT_DIR}' 下未找到任何有效的备份目录 (格式如: lxc_image_backups_*)。"
        return 1
    fi
    msg "YELLOW" "发现以下备份目录 (按时间倒序)，请选择一个进行恢复:"
    local i=1
    for dir in "${backup_dirs[@]}"; do
        echo "   $i) $(basename "$dir")"
        ((i++))
    done
    read -p "请输入选项 [1-${#backup_dirs[@]}] (或按Enter取消): " choice
    if [[ ! "$choice" =~ ^[0-9]+$ ]] || (( choice < 1 )) || (( choice > ${#backup_dirs[@]} )); then
        msg "BLUE" "无效选择或用户取消，操作终止。"
        return
    fi
    local restore_dir="${backup_dirs[$((choice-1))]}"
    msg "YELLOW" "将从以下目录恢复: $restore_dir"
    local image_files=()
    mapfile -t image_files < <(find "$restore_dir" -maxdepth 1 -type f -name "*.tar.gz")
    if [ ${#image_files[@]} -eq 0 ]; then
        msg "RED" "错误: 在 '$restore_dir' 目录内没有找到任何镜像文件 (*.tar.gz)。"
        return 1
    fi
    for file in "${image_files[@]}"; do
        local alias
        alias=$(basename "$file" .tar.gz)
        msg "BLUE" "-------------------------------------------"
        msg "YELLOW" "准备恢复镜像: $alias"
        if lxc image info "$alias" &>/dev/null; then
            msg "RED" "警告：镜像 '$alias' 已存在。"
            read -p "$(msg "YELLOW" "是否删除旧镜像并覆盖? (y/N): ")" overwrite
            if [[ "${overwrite}" =~ ^[yY]$ ]]; then
                msg "RED" "  -> 正在删除旧镜像 '$alias'..."
                if lxc image delete "$alias"; then
                    msg "GREEN" "     ✓ 旧镜像已删除。"
                else
                    msg "RED" "     ✗ 删除失败！跳过此镜像的恢复。"
                    continue
                fi
            else
                msg "BLUE" "  -> 已跳过恢复 '$alias'。"
                continue
            fi
        fi
        msg "GREEN" "  -> 正在从文件导入: $file"
        if lxc image import "$file" --alias "$alias"; then
            msg "GREEN" "     ✓ 成功导入 '$alias'。"
        else
            msg "RED" "     ✗ 错误: 导入 '$alias' 失败。"
        fi
    done
    echo ""
    msg "GREEN" "==============================================="
    msg "GREEN" "镜像恢复流程已完成。当前镜像列表:"
    lxc image list
    msg "GREEN" "==============================================="
}
set_lxd_pool_as_default() {
    local pool_name="$1"
    echo ""
    msg "CYAN" "=> 配置默认 Profile"
    read -p "$(msg "YELLOW" "是否要将 '$pool_name' 设置为默认 profile 的根磁盘池? (这会替换现有设置) [y/N]: ")" set_default
    if [[ "${set_default}" =~ ^[yY]$ ]]; then
        msg "YELLOW" "正在修改默认 profile..."

        # 更安全的方式：先检查是否存在root设备，然后处理
        if lxc profile device list default | grep -q "^root"; then
            # 如果存在root设备，先删除
            if ! lxc profile device remove default root; then
                msg "RED" "✗ 删除现有root设备失败。"
                return 1
            fi
        fi

        # 添加新的root设备
        if lxc profile device add default root disk path=/ pool="$pool_name"; then
            msg "GREEN" "✓ 默认 profile 已更新。"
            lxc profile show default
        else
            msg "RED" "✗ 修改默认 profile 失败。"
            return 1
        fi
    else
        msg "BLUE" "已跳过修改默认 profile。"
    fi
}
create_btrfs_pool_from_file() {
    msg "BLUE" "--- 从镜像文件创建BTRFS存储池 ---"
    read -p "请输入新的 LXD 存储池名称 (例如: btrfs-pool): " pool_name
    if [[ -z "$pool_name" ]]; then
        msg "RED" "错误: 存储池名称不能为空。"
        return 1
    fi
    if lxc storage list | grep -qP "^\s*\|\s*${pool_name}\s*\|"; then
        msg "RED" "错误: 名为 '${pool_name}' 的LXD存储池已存在。"
        return 1
    fi
    read -p "请输入镜像文件大小 (GB) [默认: 20]: " file_size
    file_size=${file_size:-20}
    if ! [[ "$file_size" =~ ^[1-9][0-9]*$ ]]; then
        msg "RED" "错误: 大小必须是一个正整数。"
        return 1
    fi
    msg "YELLOW" "将通过 LXD 创建一个名为 '${pool_name}'，大小为 ${file_size}GB 的 BTRFS 存储池。"
    read -p "$(msg "YELLOW" "您确定要继续吗? [y/N]: ")" confirm
    if [[ ! "${confirm}" =~ ^[yY]$ ]]; then
        msg "BLUE" "操作已由用户取消。"
        return
    fi
    msg "BLUE" "正在通过 LXD 创建 BTRFS 存储池..."
    if ! lxc storage create "$pool_name" btrfs size="${file_size}GB"; then
        msg "RED" "在 LXD 中创建存储池失败。请检查错误信息。"
        return 1
    fi
    msg "GREEN" "✓ LXD 存储池创建成功。"
    lxc storage list
    set_lxd_pool_as_default "$pool_name"
}
create_btrfs_pool_from_device() {
    msg "BLUE" "--- 从块设备创建BTRFS存储池 (高级) ---"
    msg "YELLOW" "以下是系统中可用的块设备 (磁盘):"
    lsblk -d -o NAME,SIZE,TYPE | grep 'disk'
    echo ""
    read -p "请输入要用于创建 BTRFS 池的设备名称 (例如: sdb, vdb): /dev/" device_name
    local device_path="/dev/${device_name}"
    if [[ -z "$device_name" ]] || [[ ! -b "$device_path" ]]; then
        msg "RED" "错误: 设备 '$device_path' 无效或不存在。"
        return 1
    fi
    read -p "请输入新的 LXD 存储池名称 (例如: data-pool): " pool_name
    if [[ -z "$pool_name" ]]; then
        msg "RED" "错误: 存储池名称不能为空。"
        return 1
    fi
    if lxc storage list | grep -qP "^\s*\|\s*${pool_name}\s*\|"; then
        msg "RED" "错误: 名为 '${pool_name}' 的LXD存储池已存在。"
        return 1
    fi
    msg "RED" "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
    msg "RED" "警告: 此操作将格式化设备 '$device_path' 并销毁其上的所有数据！"
    msg "RED" "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
    read -p "$(msg "YELLOW" "请再次确认是否继续? (y/N): ")" confirm
    if [[ ! "${confirm}" =~ ^[yY]$ ]]; then
        msg "BLUE" "操作已由用户取消。"
        return
    fi
    msg "BLUE" "正在创建存储池..."
    if ! lxc storage create "$pool_name" btrfs source="$device_path"; then
        msg "RED" "在 LXD 中创建存储池失败。请检查错误信息。"
        return 1
    fi
    msg "GREEN" "✓ LXD 存储池创建成功。"
    lxc storage list
    set_lxd_pool_as_default "$pool_name"
}
delete_btrfs_pool() {
    msg "BLUE" "--- 删除 LXD 存储池 ---"
    msg "YELLOW" "当前可用的存储池:"
    lxc storage list
    read -p "请输入要删除的存储池名称: " pool_name
    if [[ -z "$pool_name" ]]; then
        msg "RED" "错误: 存储池名称不能为空。"
        return 1
    fi
    if [[ "$pool_name" == "default" ]]; then
        msg "RED" "错误: 为了安全，不允许通过此脚本删除 'default' 存储池。"
        return 1
    fi
    if ! lxc storage list | grep -qP "^\s*\|\s*${pool_name}\s*\|"; then
        msg "RED" "错误: 名为 '${pool_name}' 的存储池不存在。"
        return 1
    fi
    local used_by_count
    used_by_count=$(lxc query "/1.0/storage-pools/${pool_name}" | jq '.used_by | length')
    if [[ "$used_by_count" -ne 0 ]]; then
        msg "RED" "错误: 存储池 '${pool_name}' 正在被 ${used_by_count} 个资源使用，无法删除。"
        msg "YELLOW" "使用者列表如下:"
        lxc query "/1.0/storage-pools/${pool_name}" | jq -r '.used_by[]'
        return 1
    fi
    msg "RED" "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
    msg "RED" "警告: 此操作将永久删除存储池 '${pool_name}' 及其包含的所有LXD数据！"
    msg "RED" "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
    read -p "$(msg "YELLOW" "请再次确认是否继续? (y/N): ")" confirm
    if [[ ! "${confirm}" =~ ^[yY]$ ]]; then
        msg "BLUE" "操作已由用户取消。"
        return
    fi
    msg "BLUE" "正在删除 LXD 存储池 '${pool_name}'..."
    if ! lxc storage delete "$pool_name"; then
        msg "RED" "删除存储池失败。请检查 LXD 日志。"
        return 1
    fi
    msg "GREEN" "✓ 存储池 '${pool_name}' 已成功从 LXD 中删除。"
}
show_btrfs_creation_menu() {
    clear
    msg "CYAN" "请选择创建BTRFS存储池的方式:"
    echo "  1) 从镜像文件创建 (推荐, 可自定义大小)"
    echo "  2) 从专用块设备创建 (将格式化整个磁盘)"
    echo "  3) 返回"
    read -p "请输入选项 [1-3]: " creation_choice
    case "$creation_choice" in
        1) create_btrfs_pool_from_file ;;
        2) create_btrfs_pool_from_device ;;
        3) return ;;
        *) msg "RED" "无效选项" ;;
    esac
}
# 下载Alpine镜像
download_alpine_image() {
    msg "BLUE" "正在下载 Alpine 3.19 镜像..."

    # 检查镜像是否已存在
    if lxc image info alpine319 &>/dev/null; then
        msg "YELLOW" "Alpine 3.19 镜像 (alpine319) 已存在。"
        read -p "$(msg "YELLOW" "是否要删除现有镜像并重新下载? (y/N): ")" overwrite
        if [[ "${overwrite}" =~ ^[yY]$ ]]; then
            msg "BLUE" "正在删除现有镜像..."
            if lxc image delete alpine319; then
                msg "GREEN" "✓ 现有镜像已删除。"
            else
                msg "RED" "✗ 删除现有镜像失败。"
                return 1
            fi
        else
            msg "BLUE" "已跳过 Alpine 镜像下载。"
            return 0
        fi
    fi

    msg "BLUE" "正在从官方仓库下载 Alpine 3.19 镜像..."
    if lxc image copy images:alpine/3.19 local: --alias alpine319; then
        msg "GREEN" "✓ Alpine 3.19 镜像下载成功！别名: alpine319"
    else
        msg "RED" "✗ Alpine 3.19 镜像下载失败。"
        return 1
    fi
}

# 下载Debian镜像
download_debian_image() {
    msg "BLUE" "正在下载 Debian 12 镜像..."

    # 检查镜像是否已存在
    if lxc image info debian12 &>/dev/null; then
        msg "YELLOW" "Debian 12 镜像 (debian12) 已存在。"
        read -p "$(msg "YELLOW" "是否要删除现有镜像并重新下载? (y/N): ")" overwrite
        if [[ "${overwrite}" =~ ^[yY]$ ]]; then
            msg "BLUE" "正在删除现有镜像..."
            if lxc image delete debian12; then
                msg "GREEN" "✓ 现有镜像已删除。"
            else
                msg "RED" "✗ 删除现有镜像失败。"
                return 1
            fi
        else
            msg "BLUE" "已跳过 Debian 镜像下载。"
            return 0
        fi
    fi

    local temp_dir="/tmp/lxd_debian_download"
    local debian_file="debian12.tar.gz"
    local download_url="https://github.com/jiayihello/lxc-images/releases/download/debian/debian12.tar.gz"

    # 创建临时目录
    mkdir -p "$temp_dir"
    cd "$temp_dir" || {
        msg "RED" "错误: 无法进入临时目录 $temp_dir"
        return 1
    }

    # 清理可能存在的旧文件
    rm -f "$debian_file"

    msg "BLUE" "正在从 GitHub 下载 Debian 12 镜像文件..."
    if wget -O "$debian_file" "$download_url"; then
        msg "GREEN" "✓ Debian 12 镜像文件下载成功。"
    else
        msg "RED" "✗ Debian 12 镜像文件下载失败。"
        cd - >/dev/null
        rm -rf "$temp_dir"
        return 1
    fi

    msg "BLUE" "正在导入 Debian 12 镜像到 LXD..."
    if lxc image import "$debian_file" --alias debian12; then
        msg "GREEN" "✓ Debian 12 镜像导入成功！别名: debian12"
    else
        msg "RED" "✗ Debian 12 镜像导入失败。"
        cd - >/dev/null
        rm -rf "$temp_dir"
        return 1
    fi

    # 清理临时文件
    msg "BLUE" "正在清理临时文件..."
    cd - >/dev/null
    rm -rf "$temp_dir"
    msg "GREEN" "✓ 临时文件已清理。"
}

# 下载安装镜像主菜单
download_images() {
    while true; do
        clear
        msg "BLUE" "#############################################"
        msg "BLUE" "#           下载安装 LXD 镜像              #"
        msg "BLUE" "#############################################"
        echo "请选择要下载的镜像:"
        echo -e "  1) ${COLOR_GREEN}下载 Alpine 3.19 镜像${COLOR_RESET} (别名: alpine319)"
        echo -e "  2) ${COLOR_GREEN}下载 Debian 12 镜像${COLOR_RESET} (别名: debian12)"
        echo -e "  3) ${COLOR_CYAN}下载所有镜像${COLOR_RESET} (Alpine + Debian)"
        echo "  4) 返回主菜单"
        echo ""
        echo "镜像说明:"
        echo "  • Alpine 3.19: 轻量级 Linux 发行版，适合容器化应用"
        echo "  • Debian 12: 稳定可靠的 Linux 发行版，功能完整"
        echo ""
        read -p "请输入选项 [1-4]: " download_choice

        case $download_choice in
            1)
                download_alpine_image
                ;;
            2)
                download_debian_image
                ;;
            3)
                msg "BLUE" "开始下载所有镜像..."
                download_alpine_image
                echo ""
                download_debian_image
                ;;
            4)
                return
                ;;
            *)
                msg "RED" "无效的选项 '$download_choice'，请重新输入。"
                ;;
        esac

        if [[ "$download_choice" != "4" ]]; then
            echo ""
            msg "CYAN" "当前本地镜像列表:"
            lxc image list
        fi

        press_any_key
    done
}

manage_btrfs_storage() {
    while true; do
        clear
        msg "BLUE" "#############################################"
        msg "BLUE" "#          LXD BTRFS 存储管理             #"
        msg "BLUE" "#############################################"
        echo "当前存储池状态:"
        lxc storage list
        echo "---------------------------------------------"
        echo "请选择要执行的操作:"
        echo -e "  1) ${COLOR_GREEN}创建新的 LXD BTRFS 存储池${COLOR_RESET}"
        echo -e "  2) ${COLOR_RED}删除一个 LXD 存储池${COLOR_RESET}"
        echo "  3) 返回主菜单"
        read -p "请输入选项 [1-3]: " btrfs_choice
        case $btrfs_choice in
            1) run_with_lxd_check show_btrfs_creation_menu ;;
            2) run_with_lxd_check delete_btrfs_pool ;;
            3) return ;;
            *) msg "RED" "无效的选项 '$btrfs_choice'，请重新输入。" ;;
        esac
        press_any_key
    done
}
main_menu() {
    while true; do
        clear
        msg "BLUE" "#############################################"
        msg "BLUE" "#           LXD 助手 (v2.5)                 #"
        msg "BLUE" "#############################################"
        echo "请选择要执行的操作:"
        echo -e "  1) ${COLOR_CYAN}安装或检查 LXD 环境${COLOR_RESET}"
        echo -e "  2) ${COLOR_GREEN}下载安装镜像${COLOR_RESET} (Alpine/Debian)"
        echo -e "  3) ${COLOR_GREEN}备份所有本地 LXD 镜像${COLOR_RESET}"
        echo -e "  4) ${COLOR_YELLOW}从备份恢复 LXD 镜像${COLOR_RESET}"
        echo -e "  5) ${COLOR_CYAN}管理 BTRFS 存储池${COLOR_RESET}"
        echo "  6) 列出本地 LXD 镜像"
        echo -e "  7) ${COLOR_RED}退出脚本${COLOR_RESET}"
        read -p "请输入选项 [1-7]: " main_choice
        case $main_choice in
            1) install_lxd ;;
            2) run_with_lxd_check download_images ;;
            3) run_with_lxd_check backup_images ;;
            4) run_with_lxd_check restore_images ;;
            5) manage_btrfs_storage ;;
            6) run_with_lxd_check lxc image list ;;
            7) exit 0 ;;
            *) msg "RED" "无效的选项 '$main_choice'，请重新输入。" ;;
        esac
        press_any_key
    done
}
main() {
    check_root
    check_dependencies
    main_menu
}
main "$@"
