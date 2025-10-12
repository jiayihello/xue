#!/bin/bash
#
# +--------------------------------------------------------------------+
# | Script Name:    LXD Container Toolkit (Integrated Edition)        |
# | Author:         xkatld & gemini                                    |
# | Description:    LXD 容器管理工具箱 - 整合版                       |
# | Usage:          sudo bash linuxtools.sh                            |
# +--------------------------------------------------------------------+

# --- 安全设置 ---
set -o errexit
set -o nounset
set -o pipefail

# --- 全局配置 ---
readonly BACKUPS_ROOT_DIR="/root/lxc_image_backups"
readonly SWAP_FILE_PATH="/swapfile"

# --- 颜色定义 ---
readonly COLOR_GREEN='\033[0;32m'
readonly COLOR_RED='\033[0;31m'
readonly COLOR_YELLOW='\033[1;33m'
readonly COLOR_CYAN='\033[0;36m'
readonly COLOR_BLUE='\033[0;34m'
readonly COLOR_NC='\033[0m' # No Color

# --- 消息函数 ---
msg_info() { echo -e "${COLOR_CYAN}[*] $1${COLOR_NC}"; }
msg_ok() { echo -e "${COLOR_GREEN}[+] $1${COLOR_NC}"; }
msg_error() { echo -e "${COLOR_RED}[!] 错误: $1${COLOR_NC}" >&2; }
msg_warn() { echo -e "${COLOR_YELLOW}[-] 警告: $1${COLOR_NC}"; }
msg() {
    local color_name="$1"
    local message="$2"
    local color_var="COLOR_${color_name^^}"
    printf '%b%s%b\n' "${!color_var}" "${message}" "${COLOR_NC}"
}

# --- 核心功能函数 ---

# 检查是否以 root 权限运行
check_root() {
    if [[ "${EUID}" -ne 0 ]]; then
        msg_error "此脚本需要 root 权限，请使用 'sudo' 运行。"
        exit 1
    fi
}

# 检查核心依赖
check_dependencies() {
    local dependencies=("curl" "mktemp" "sort")
    msg_info "正在检查核心依赖: ${dependencies[*]}..."
    for cmd in "${dependencies[@]}"; do
        if ! command -v "$cmd" &>/dev/null; then
            msg_error "依赖命令 '$cmd' 未找到，请先安装它。"
            exit 1
        fi
    done
}

# 检查 OpenVZ 环境
check_openvz() {
    if [[ -d "/proc/vz" ]]; then
        msg_error "不支持 OpenVZ 虚拟化环境，因为它无法修改内核和 Swap。"
        return 1
    fi
    return 0
}

# 兼容性清屏函数
clear_screen() {
    if command -v "clear" &>/dev/null; then
        clear
    else
        printf '\033[2J\033[H'
    fi
}

press_any_key() {
    echo ""
    read -n 1 -s -r -p "按任意键返回主菜单..."
}

# ========================================
# LXD 相关函数
# ========================================

is_lxd_installed() {
    command -v lxd &>/dev/null || [ -x /snap/bin/lxd ]
}

configure_snap_path() {
    msg_info "配置 Snap 路径到系统 PATH..."
    if [[ ":$PATH:" != *":/snap/bin:"* ]]; then
        echo 'export PATH=$PATH:/snap/bin' | sudo tee -a /etc/profile.d/snap_path.sh >/dev/null
        export PATH=$PATH:/snap/bin
        msg_ok "✓ Snap 路径已添加到系统 PATH"
    else
        msg_ok "✓ Snap 路径已存在于系统 PATH 中"
    fi

    if [ -x /snap/bin/lxd ] && [ ! -x /usr/local/bin/lxd ]; then
        sudo ln -sf /snap/bin/lxd /usr/local/bin/lxd
        msg_ok "✓ 创建 lxd 符号链接"
    fi

    if [ -x /snap/bin/lxc ] && [ ! -x /usr/local/bin/lxc ]; then
        sudo ln -sf /snap/bin/lxc /usr/local/bin/lxc
        msg_ok "✓ 创建 lxc 符号链接"
    fi

    msg_ok "✓ Snap 路径配置完成"
}

initialize_lxd() {
    msg_info "初始化 LXD..."
    msg_warn "等待 LXD snap 服务启动..."
    local retry_count=0
    local max_retries=10

    while [ $retry_count -lt $max_retries ]; do
        if sudo snap services lxd | grep -q "active"; then
            msg_ok "✓ LXD snap 服务已启动"
            break
        fi
        sleep 2
        ((retry_count++))
        msg_warn "等待中... ($retry_count/$max_retries)"
    done

    local lxd_cmd
    if command -v lxd &>/dev/null; then
        lxd_cmd="lxd"
    elif [ -x /snap/bin/lxd ]; then
        lxd_cmd="/snap/bin/lxd"
    elif [ -x /usr/local/bin/lxd ]; then
        lxd_cmd="/usr/local/bin/lxd"
    else
        msg_error "无法找到 lxd 命令"
        return 1
    fi

    msg_info "正在执行 lxd init --auto..."
    if sudo "$lxd_cmd" init --auto; then
        msg_ok "✓ LXD 初始化成功"
        local lxd_version
        lxd_version=$(sudo "$lxd_cmd" --version 2>/dev/null || echo "未知版本")
        msg_ok "✓ LXD 版本: $lxd_version"
    else
        msg_error "✗ LXD 初始化失败"
        return 1
    fi
}

# 预安装依赖和配置
prepare_system_for_lxd() {
    msg_info "--- 准备系统环境 ---"
    
    # 安装基础依赖
    msg_info "安装基础依赖包..."
    if DEBIAN_FRONTEND=noninteractive apt-get install -y \
        curl wget git iptables iptables-persistent \
        python3 python3-pip sqlite3 cron 2>&1 | grep -v "iptables-persistent"; then
        msg_ok "✓ 基础依赖包安装成功"
    else
        msg_warn "部分依赖安装可能有警告，继续..."
    fi
    
    # 检测 Debian/Ubuntu 版本并删除 Python EXTERNALLY-MANAGED 文件
    msg_info "配置 Python 环境..."
    
    local python_version=""
    
    # 检测系统版本
    if [[ -f /etc/os-release ]]; then
        source /etc/os-release
        
        # Debian 版本检测
        if [[ "$ID" == "debian" ]]; then
            case "$VERSION_ID" in
                "12")
                    python_version="3.11"
                    msg_info "检测到 Debian 12，使用 Python 3.11"
                    ;;
                "13")
                    python_version="3.13"
                    msg_info "检测到 Debian 13，使用 Python 3.13"
                    ;;
                *)
                    # 自动检测当前 Python 版本
                    python_version=$(python3 --version 2>&1 | grep -oP '\d+\.\d+' | head -1)
                    msg_warn "Debian 版本 $VERSION_ID，自动检测 Python $python_version"
                    ;;
            esac
        # Ubuntu 版本检测
        elif [[ "$ID" == "ubuntu" ]]; then
            python_version=$(python3 --version 2>&1 | grep -oP '\d+\.\d+' | head -1)
            msg_info "检测到 Ubuntu $VERSION_ID，使用 Python $python_version"
        else
            python_version=$(python3 --version 2>&1 | grep -oP '\d+\.\d+' | head -1)
            msg_warn "未知系统，自动检测 Python $python_version"
        fi
    else
        # 如果无法读取 os-release，自动检测 Python 版本
        python_version=$(python3 --version 2>&1 | grep -oP '\d+\.\d+' | head -1)
        msg_warn "无法检测系统版本，自动检测 Python $python_version"
    fi
    
    # 删除 EXTERNALLY-MANAGED 文件
    if [[ -n "$python_version" ]]; then
        local managed_file="/usr/lib/python${python_version}/EXTERNALLY-MANAGED"
        if [[ -f "$managed_file" ]]; then
            msg_info "删除 Python 外部管理限制文件..."
            if rm -f "$managed_file"; then
                msg_ok "✓ 已删除 $managed_file"
            else
                msg_warn "⚠ 无法删除 $managed_file"
            fi
        else
            msg_info "Python 外部管理文件不存在，跳过"
        fi
    fi
    
    echo ""
    msg_ok "✓ 系统环境准备完成"
    echo ""
}

install_lxd() {
    clear_screen
    msg_info "--- LXD 环境安装与配置 ---"
    if is_lxd_installed; then
        msg_ok "LXD 已经安装。"
        lxd --version
        read -p "$(msg_warn "是否要强制重新进行自动化配置 (lxd init --auto)? [y/N]: ")" re_init
        if [[ "${re_init}" =~ ^[yY]$ ]]; then
            msg_warn "正在重新运行 lxd init --auto..."
            if sudo lxd init --auto; then
                msg_ok "LXD 重新初始化成功。"
            else
                msg_error "LXD 重新初始化失败，请检查上面的错误信息。"
            fi
        fi
        return 0
    fi

    if ! command -v apt-get &>/dev/null; then
        msg_error "本安装脚本仅支持使用 'apt' 的系统 (如 Debian, Ubuntu)。"
        return 1
    fi

    msg_warn "检测到 LXD 未安装，即将开始 Snap 安装流程。"
    read -p "$(msg_warn "确认开始安装 LXD 吗? [y/N]: ")" confirm
    if [[ ! "${confirm}" =~ ^[yY]$ ]]; then
        msg_info "操作已由用户取消。"
        return
    fi
    
    # 执行系统准备
    if ! prepare_system_for_lxd; then
        msg_error "系统准备失败"
        return 1
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
        msg_info "步骤 $((i+1))/${#steps[@]}: ${description}..."

        if [[ "$command" == "configure_snap_path" ]] || [[ "$command" == "initialize_lxd" ]]; then
            if ! "$command"; then
                msg_error "在执行 '${description}' 时失败。"
                return 1
            fi
        else
            if ! eval "$command"; then
                msg_error "在执行 '${description}' 时失败。"
                return 1
            fi
        fi
    done

    echo ""
    msg_ok "==============================================="
    msg_ok "✓ LXD (via Snap) 安装并初始化完成！"
    msg_ok "==============================================="
}

install_lxdimages_tool() {
    clear_screen
    msg_info "--- 安装 lxdimages 镜像构建工具 ---"
    
    # 检查是否已安装
    if command -v lxdimages &>/dev/null; then
        msg_ok "lxdimages 工具已安装"
        lxdimages --version 2>/dev/null || lxdimages -v 2>/dev/null || echo "版本信息不可用"
        read -p "$(msg_warn "是否要重新安装? (y/N): ")" reinstall
        if [[ ! "${reinstall}" =~ ^[yY]$ ]]; then
            msg_info "跳过安装"
            return 0
        fi
    fi
    
    # 获取脚本所在目录
    local script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    local installer="$script_dir/lxdimages.sh"
    
    if [[ ! -f "$installer" ]]; then
        msg_error "未找到 lxdimages.sh 安装脚本"
        msg_error "期望路径: $installer"
        return 1
    fi
    
    msg_info "正在安装 lxdimages 工具..."
    if bash "$installer" --force; then
        msg_ok "✓ lxdimages 工具安装成功！"
        echo ""
        msg_info "工具已安装到: /usr/local/bin/lxdimages"
        return 0
    else
        msg_error "✗ lxdimages 工具安装失败"
        return 1
    fi
}

build_custom_images() {
    clear_screen
    echo -e "${COLOR_GREEN}========================================="
    echo -e "    构建自定义 LXD 镜像"
    echo -e "=========================================${COLOR_NC}"
    echo ""
    
    # 检查 lxdimages 是否已安装
    if ! command -v lxdimages &>/dev/null; then
        msg_error "lxdimages 工具未安装！"
        msg_info "请先选择菜单选项 3) 安装 lxdimages 工具"
        return 1
    fi
    
    # 定义镜像列表
    declare -A quick_images=(
        ["1"]="debian:bookworm:debian12:Debian 12 (bookworm)"
        ["2"]="debian:trixie:debian13:Debian 13 (trixie)"
        ["3"]="alpine:3.22:alpine322:Alpine 3.22"
    )
    
    declare -A all_images=(
        ["1"]="debian:bullseye:debian11:Debian 11 (bullseye)"
        ["2"]="debian:bookworm:debian12:Debian 12 (bookworm)"
        ["3"]="debian:trixie:debian13:Debian 13 (trixie)"
        ["4"]="ubuntu:jammy:ubuntu2204:Ubuntu 22.04 (jammy)"
        ["5"]="ubuntu:noble:ubuntu2404:Ubuntu 24.04 (noble)"
        ["6"]="alpine:3.19:alpine319:Alpine 3.19"
        ["7"]="alpine:3.20:alpine320:Alpine 3.20"
        ["8"]="alpine:3.21:alpine321:Alpine 3.21"
        ["9"]="alpine:3.22:alpine322:Alpine 3.22"
        ["10"]="centos:9-Stream:centos9:CentOS Stream 9"
        ["11"]="fedora:41:fedora41:Fedora 41"
    )
    
    # 显示快捷选项
    echo -e "${COLOR_CYAN}快捷选项（推荐）:${COLOR_NC}"
    for key in $(echo "${!quick_images[@]}" | tr ' ' '\n' | sort -n); do
        IFS=':' read -r dist version name desc <<< "${quick_images[$key]}"
        printf "  %s) %-30s -> %s\n" "$key" "$desc" "$name"
    done
    echo ""
    
    read -p "输入选择（多选用空格分隔）或回车查看全部: " user_choice
    
    # 如果用户按回车，显示完整列表
    if [[ -z "$user_choice" ]]; then
        clear_screen
        echo -e "${COLOR_GREEN}========================================="
        echo -e "    构建自定义 LXD 镜像 - 完整列表"
        echo -e "=========================================${COLOR_NC}"
        echo ""
        
        echo -e "${COLOR_CYAN}--- Debian 系列 ---${COLOR_NC}"
        for key in 1 2 3; do
            IFS=':' read -r dist version name desc <<< "${all_images[$key]}"
            printf "  %2s) %-30s -> %s\n" "$key" "$desc" "$name"
        done
        echo ""
        
        echo -e "${COLOR_CYAN}--- Ubuntu 系列 ---${COLOR_NC}"
        for key in 4 5; do
            IFS=':' read -r dist version name desc <<< "${all_images[$key]}"
            printf "  %2s) %-30s -> %s\n" "$key" "$desc" "$name"
        done
        echo ""
        
        echo -e "${COLOR_CYAN}--- Alpine 系列 ---${COLOR_NC}"
        for key in 6 7 8 9; do
            IFS=':' read -r dist version name desc <<< "${all_images[$key]}"
            printf "  %2s) %-30s -> %s\n" "$key" "$desc" "$name"
        done
        echo ""
        
        echo -e "${COLOR_CYAN}--- CentOS/Fedora 系列 ---${COLOR_NC}"
        for key in 10 11; do
            IFS=':' read -r dist version name desc <<< "${all_images[$key]}"
            printf "  %2s) %-30s -> %s\n" "$key" "$desc" "$name"
        done
        echo ""
        
        read -p "输入选择（多选用空格分隔）或 0 返回: " user_choice
        
        if [[ "$user_choice" == "0" ]]; then
            return 0
        fi
    fi
    
    # 解析用户选择
    if [[ -z "$user_choice" ]]; then
        msg_info "未选择任何镜像"
        return 0
    fi
    
    # 构建选择的镜像列表
    declare -a selected_images
    for choice in $user_choice; do
        # 先在快捷列表中查找
        if [[ -n "${quick_images[$choice]:-}" ]]; then
            selected_images+=("${quick_images[$choice]}")
        # 再在完整列表中查找
        elif [[ -n "${all_images[$choice]:-}" ]]; then
            selected_images+=("${all_images[$choice]}")
        else
            msg_warn "无效选项: $choice，已跳过"
        fi
    done
    
    if [[ ${#selected_images[@]} -eq 0 ]]; then
        msg_error "没有有效的镜像选择"
        return 1
    fi
    
    # 开始构建
    echo ""
    msg_info "开始构建 ${#selected_images[@]} 个镜像..."
    echo ""
    
    local success_count=0
    local fail_count=0
    declare -a success_list
    declare -a fail_list
    
    local index=1
    for image_info in "${selected_images[@]}"; do
        IFS=':' read -r dist version name desc <<< "$image_info"
        
        echo -e "${COLOR_BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${COLOR_NC}"
        echo -e "${COLOR_CYAN}[$index/${#selected_images[@]}] 正在构建 $desc...${COLOR_NC}"
        echo -e "${COLOR_BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${COLOR_NC}"
        echo ""
        
        msg_info "执行命令: lxdimages $dist $version -add ssh -name $name"
        echo ""
        
        # 执行构建命令
        if lxdimages "$dist" "$version" -add ssh -name "$name"; then
            echo ""
            # 验证镜像是否导入
            if lxc image list --format csv | grep -q "^$name,"; then
                msg_ok "✓ 镜像构建成功！"
                msg_ok "✓ 已导入到 LXD: $name"
                
                # 获取镜像大小
                local image_size=$(lxc image list "$name" --format csv | cut -d',' -f4)
                success_list+=("$name ($image_size)")
                ((success_count++))
            else
                msg_warn "⚠ 镜像构建完成但未能验证导入状态"
                success_list+=("$name (未验证)")
                ((success_count++))
            fi
        else
            echo ""
            msg_error "✗ 镜像构建失败: $desc"
            fail_list+=("$desc ($name)")
            ((fail_count++))
        fi
        
        # 清理临时文件
        msg_info "清理临时文件..."
        rm -rf /tmp/lxdimages-* 2>/dev/null
        rm -rf /tmp/lxd-build-* 2>/dev/null
        rm -rf /var/tmp/lxdimages-* 2>/dev/null
        msg_ok "✓ 临时文件已清理"
        
        echo ""
        ((index++))
    done
    
    # 显示最终结果
    echo -e "${COLOR_BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${COLOR_NC}"
    echo -e "${COLOR_GREEN}    构建任务完成！${COLOR_NC}"
    echo -e "${COLOR_BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${COLOR_NC}"
    echo ""
    
    echo "统计信息:"
    echo "- 总计: ${#selected_images[@]} 个镜像"
    echo "- 成功: $success_count 个"
    echo "- 失败: $fail_count 个"
    echo ""
    
    if [[ $success_count -gt 0 ]]; then
        echo -e "${COLOR_GREEN}成功的镜像:${COLOR_NC}"
        for img in "${success_list[@]}"; do
            echo "  ✓ $img"
        done
        echo ""
    fi
    
    if [[ $fail_count -gt 0 ]]; then
        echo -e "${COLOR_RED}失败的镜像:${COLOR_NC}"
        for img in "${fail_list[@]}"; do
            echo "  ✗ $img"
        done
        echo ""
    fi
    
    # 显示当前镜像列表
    if [[ $success_count -gt 0 ]]; then
        echo -e "${COLOR_CYAN}当前 LXD 镜像列表:${COLOR_NC}"
        lxc image list | head -20
        echo ""
        
        echo -e "${COLOR_GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${COLOR_NC}"
        echo -e "${COLOR_GREEN}所有镜像已准备就绪，可以使用！${COLOR_NC}"
        echo -e "${COLOR_GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${COLOR_NC}"
        echo ""
        echo "使用示例:"
        if [[ ${#success_list[@]} -gt 0 ]]; then
            local first_img=$(echo "${success_list[0]}" | cut -d' ' -f1)
            echo "  lxc launch $first_img my-container"
            echo "  lxc exec my-container -- /bin/bash"
        fi
        echo ""
    fi
}

backup_images() {
    clear_screen
    msg_info "--- LXD 镜像备份 ---"
    
    if ! command -v jq &>/dev/null; then
        msg_warn "未检测到 jq 工具，正在安装..."
        apt-get install -y jq
    fi
    
    local image_aliases_list
    image_aliases_list=$(lxc image list --format=json | jq -r '.[] | select(.aliases | length > 0) | .aliases[0].name')
    
    if [[ -z "$image_aliases_list" ]]; then
        msg_warn "提示: 未找到任何带有别名(alias)的本地 LXD 镜像可供备份。"
        return
    fi
    
    local image_count
    image_count=$(echo "$image_aliases_list" | wc -l)
    msg_warn "检测到 ${image_count} 个带别名的本地镜像，将逐一备份。"
    
    read -p "$(msg_warn "确认开始备份吗? (y/N): ")" confirm
    if [[ ! "${confirm}" =~ ^[yY]$ ]]; then
        msg_info "操作已由用户取消。"
        return
    fi
    
    local backup_dir="${BACKUPS_ROOT_DIR}/lxc_image_backups_$(date +%Y%m%d_%H%M%S)"
    mkdir -p "$backup_dir"
    msg_warn "所有备份文件将存放在: ${backup_dir}"
    
    echo ""
    msg_info "开始导出镜像..."
    local success_count=0
    local fail_count=0
    set +o errexit
    
    while read -r alias; do
        if [[ -z "$alias" ]]; then continue; fi
        local filename="${backup_dir}/${alias}.tar.gz"
        msg "CYAN" "  -> 正在导出 $alias ..."
        local stderr
        if stderr=$(lxc image export "$alias" "${filename%.tar.gz}" 2>&1); then
            msg_ok "     ✓ 导出成功: ${filename}"
            ((success_count++))
        else
            msg_error "     ✗ 错误: 导出 '$alias' 失败。"
            msg_error "       LXD 错误信息: ${stderr}"
            ((fail_count++))
        fi
    done <<< "$image_aliases_list"
    
    set -o errexit
    
    echo ""
    msg_ok "==============================================="
    msg_ok "备份流程完成。"
    msg_ok "成功: $success_count, 失败: $fail_count"
    if [[ $success_count -gt 0 ]]; then
        msg_warn "备份文件列表:"
        ls -lh "$backup_dir"
    fi
    msg_ok "==============================================="
}

restore_images() {
    clear_screen
    msg_info "--- LXD 镜像恢复 ---"
    
    if ! [ -d "${BACKUPS_ROOT_DIR}" ]; then
        msg_error "备份根目录 '${BACKUPS_ROOT_DIR}' 不存在。"
        return 1
    fi
    
    local backup_dirs=()
    mapfile -t backup_dirs < <(find "${BACKUPS_ROOT_DIR}" -mindepth 1 -maxdepth 1 -type d -name "lxc_image_backups_*" -printf '%T@ %p\n' | sort -rn | cut -d' ' -f2-)
    
    if [ ${#backup_dirs[@]} -eq 0 ]; then
        msg_error "在 '${BACKUPS_ROOT_DIR}' 下未找到任何有效的备份目录。"
        return 1
    fi
    
    msg_warn "发现以下备份目录 (按时间倒序)，请选择一个进行恢复:"
    local i=1
    for dir in "${backup_dirs[@]}"; do
        echo "   $i) $(basename "$dir")"
        ((i++))
    done
    
    read -p "请输入选项 [1-${#backup_dirs[@]}] (或按Enter取消): " choice
    if [[ ! "$choice" =~ ^[0-9]+$ ]] || (( choice < 1 )) || (( choice > ${#backup_dirs[@]} )); then
        msg_info "无效选择或用户取消，操作终止。"
        return
    fi
    
    local restore_dir="${backup_dirs[$((choice-1))]}"
    msg_warn "将从以下目录恢复: $restore_dir"
    
    local image_files=()
    mapfile -t image_files < <(find "$restore_dir" -maxdepth 1 -type f -name "*.tar.gz")
    
    if [ ${#image_files[@]} -eq 0 ]; then
        msg_error "在 '$restore_dir' 目录内没有找到任何镜像文件 (*.tar.gz)。"
        return 1
    fi
    
    for file in "${image_files[@]}"; do
        local alias
        alias=$(basename "$file" .tar.gz)
        echo "-------------------------------------------"
        msg_warn "准备恢复镜像: $alias"
        
        if lxc image info "$alias" &>/dev/null; then
            msg_error "警告：镜像 '$alias' 已存在。"
            read -p "$(msg_warn "是否删除旧镜像并覆盖? (y/N): ")" overwrite
            if [[ "${overwrite}" =~ ^[yY]$ ]]; then
                msg_info "  -> 正在删除旧镜像 '$alias'..."
                if lxc image delete "$alias"; then
                    msg_ok "     ✓ 旧镜像已删除。"
                else
                    msg_error "     ✗ 删除失败！跳过此镜像的恢复。"
                    continue
                fi
            else
                msg_info "  -> 已跳过恢复 '$alias'。"
                continue
            fi
        fi
        
        msg_info "  -> 正在从文件导入: $file"
        if lxc image import "$file" --alias "$alias"; then
            msg_ok "     ✓ 成功导入 '$alias'。"
        else
            msg_error "     ✗ 错误: 导入 '$alias' 失败。"
        fi
    done
    
    echo ""
    msg_ok "==============================================="
    msg_ok "镜像恢复流程已完成。当前镜像列表:"
    lxc image list
    msg_ok "==============================================="
}

list_images() {
    clear_screen
    msg_info "--- 本地 LXD 镜像列表 ---"
    lxc image list
}

create_btrfs_pool_from_file() {
    clear_screen
    msg_info "--- 从镜像文件创建BTRFS存储池 ---"
    
    read -p "请输入新的 LXD 存储池名称 (例如: btrfs-pool): " pool_name
    if [[ -z "$pool_name" ]]; then
        msg_error "存储池名称不能为空。"
        return 1
    fi
    
    if lxc storage list | grep -qP "^\s*\|\s*${pool_name}\s*\|"; then
        msg_error "名为 '${pool_name}' 的LXD存储池已存在。"
        return 1
    fi
    
    read -p "请输入镜像文件大小 (GB) [默认: 20]: " file_size
    file_size=${file_size:-20}
    
    if ! [[ "$file_size" =~ ^[1-9][0-9]*$ ]]; then
        msg_error "大小必须是一个正整数。"
        return 1
    fi
    
    msg_warn "将通过 LXD 创建一个名为 '${pool_name}'，大小为 ${file_size}GB 的 BTRFS 存储池。"
    read -p "$(msg_warn "您确定要继续吗? [y/N]: ")" confirm
    
    if [[ ! "${confirm}" =~ ^[yY]$ ]]; then
        msg_info "操作已由用户取消。"
        return
    fi
    
    msg_info "正在通过 LXD 创建 BTRFS 存储池..."
    if ! lxc storage create "$pool_name" btrfs size="${file_size}GB"; then
        msg_error "在 LXD 中创建存储池失败。"
        return 1
    fi
    
    msg_ok "✓ LXD 存储池创建成功。"
    lxc storage list
}

manage_btrfs_storage() {
    clear_screen
    msg_info "--- LXD BTRFS 存储管理 ---"
    echo "当前存储池状态:"
    lxc storage list
    echo ""
    msg_info "目前仅支持创建 BTRFS 存储池（从镜像文件）"
    msg_info "更多功能请查看 shell/lxd-helper.sh 完整脚本"
}

# ========================================
# 虚拟内存相关函数
# ========================================

show_swap_status() {
    echo ""
    msg "BLUE" "--- 当前系统虚拟内存状态 ---"
    echo "Swap 摘要:"
    swapon --summary 2>/dev/null || msg "YELLOW" "  -> 当前没有活动的 Swap 设备。"
    echo ""
    echo "内存使用情况:"
    free -h
    echo "------------------------------------"
        echo ""
}

detect_zram_service() {
    if [[ -f /lib/systemd/system/zramswap.service ]]; then
        echo "/etc/default/zramswap zramswap.service"
    elif [[ -f /lib/systemd/system/zram-config.service ]]; then
        echo "/etc/default/zram-config zram-config.service"
    else
        echo ""
    fi
}

check_zram_module_support() {
    msg_warn "正在检查内核是否支持 ZRAM 模块..."
    if modprobe --dry-run zram &>/dev/null; then
        msg_ok "✓ 内核支持 ZRAM 模块。"
        return 0
    else
        msg_error "您当前的内核 ($(uname -r)) 似乎不支持 ZRAM 模块。"
        msg_warn "这在某些云厂商提供的定制内核中很常见。"
        msg_warn "请考虑使用 Swap 文件功能作为替代，或更换为标准的 Linux 内核。"
        return 1
    fi
}

configure_zram() {
    clear_screen
    msg_info "--- [ZRAM] 安装并配置 ZRAM ---"
    show_swap_status
    
    if ! check_openvz; then
        return 1
    fi
    
    if ! check_zram_module_support; then
        return 1
    fi

    msg_warn "正在安装 zram-tools (若未安装)..."
    DEBIAN_FRONTEND=noninteractive apt-get update -y >/dev/null && apt-get install -y zram-tools

    local zram_details
    zram_details=$(detect_zram_service)
    if [[ -z "$zram_details" ]]; then
        msg_error "安装 zram-tools 后，未能侦测到任何已知的 ZRAM 服务。"
        return 1
    fi

    local config_file service_name
    read -r config_file service_name <<< "$zram_details"
    msg_ok "侦测到 ZRAM 服务: $service_name"

    local zram_size
    while true; do
        read -p "请输入 ZRAM 大小 (MB, 推荐值为物理内存的50%-100%): " zram_size
        if [[ "$zram_size" =~ ^[1-9][0-9]*$ ]]; then
            break
        else
            msg_error "输入无效，请输入一个正整数。"
        fi
    done

    msg_warn "正在向 '$config_file' 写入配置..."
    echo -e "ALGO=zstd\nSIZE=${zram_size}" > "$config_file"

    msg_warn "正在重启 ZRAM 服务 ($service_name) 以应用配置..."
    if systemctl restart "$service_name"; then
        echo ""
        msg_ok "✓ ZRAM 已成功配置并启用！"
    else
        echo ""
        msg_error "ZRAM 服务启动失败。请运行 'systemctl status $service_name' 查看详细错误。"
        return 1
    fi
}

remove_zram() {
    clear_screen
    msg_info "--- [ZRAM] 移除 ZRAM ---"
    show_swap_status
    
    local zram_details
    zram_details=$(detect_zram_service)

    if [[ -z "$zram_details" ]] && ! dpkg -s "zram-tools" &>/dev/null; then
        msg_error "未检测到 ZRAM 服务或 zram-tools 包，无需移除。"
        return 1
    fi

    msg_error "警告：此操作将停止 ZRAM 服务并卸载 zram-tools 包！"
    read -p "$(echo -e "${COLOR_YELLOW}您确定要继续吗? [y/N]: ${COLOR_NC}")" confirm
    if [[ ! "${confirm}" =~ ^[yY]$ ]]; then
        msg_info "操作已由用户取消。"
        return
    fi

    if [[ -n "$zram_details" ]]; then
        local service_name
        service_name=$(echo "$zram_details" | awk '{print $2}')
        if systemctl is-active --quiet "$service_name"; then
            msg_warn "正在停止并禁用服务: $service_name..."
            systemctl stop "$service_name"
            systemctl disable "$service_name"
        fi
    fi

    if dpkg -s "zram-tools" &>/dev/null; then
        msg_warn "正在卸载 zram-tools 并清理配置..."
        apt-get purge -y zram-tools >/dev/null
    fi
    
    echo ""
    msg_ok "✓ ZRAM 已成功移除！"
}

create_swap_file() {
    clear_screen
    msg_info "--- [Swap文件] 添加 Swap 文件 ---"
    show_swap_status
    
    if ! check_openvz; then
        return 1
    fi
    
    if grep -q "${SWAP_FILE_PATH}" /etc/fstab; then
        msg_error "Swap 文件 '${SWAP_FILE_PATH}' 的配置已存在于 /etc/fstab。"
        return 1
    fi

    local swap_size
    while true; do
        read -p "请输入 Swap 文件大小 (MB, 推荐值为物理内存的1-2倍): " swap_size
        if [[ "$swap_size" =~ ^[1-9][0-9]*$ ]]; then
            break
        else
            msg_error "输入无效，请输入一个正整数。"
        fi
    done

    msg_warn "正在创建 ${swap_size}MB 的 Swap 文件于 '${SWAP_FILE_PATH}'..."
    fallocate -l "${swap_size}M" "${SWAP_FILE_PATH}"
    chmod 600 "${SWAP_FILE_PATH}"
    mkswap "${SWAP_FILE_PATH}"
    swapon "${SWAP_FILE_PATH}"
    
    msg_warn "正在将 Swap 配置写入 /etc/fstab 以便开机自启..."
    echo "${SWAP_FILE_PATH} none swap sw 0 0" >> /etc/fstab

    echo ""
    msg_ok "✓ Swap 文件已成功创建并启用！"
}

remove_swap_file() {
    clear_screen
    msg_info "--- [Swap文件] 移除 Swap 文件 ---"
    show_swap_status
    
    if ! grep -q "${SWAP_FILE_PATH}" /etc/fstab && [ ! -f "${SWAP_FILE_PATH}" ]; then
        msg_error "未找到 Swap 文件或其配置，无需移除。"
        return 1
    fi

    msg_error "警告：此操作将永久禁用并删除 Swap 文件！"
    read -p "$(echo -e "${COLOR_YELLOW}您确定要继续吗? [y/N]: ${COLOR_NC}")" confirm
    if [[ ! "${confirm}" =~ ^[yY]$ ]]; then
        msg_info "操作已由用户取消。"
        return
    fi

    msg_warn "正在禁用并从 /etc/fstab 中移除配置..."
    swapoff "${SWAP_FILE_PATH}" 2>/dev/null
    sed -i.bak "\#${SWAP_FILE_PATH}#d" /etc/fstab

    msg_warn "正在删除 Swap 物理文件..."
    rm -f "${SWAP_FILE_PATH}"
    
    echo ""
    msg_ok "✓ Swap 文件已成功移除！原 /etc/fstab 已备份为 /etc/fstab.bak"
}

# ========================================
# 服务器部署函数
# ========================================

deploy_lxd_server() {
    clear_screen
    msg_info "--- LXD 服务器后端一键部署 ---"
    echo ""
    
    # 检查 LXD 是否已安装
    if ! is_lxd_installed; then
        msg_error "LXD 未安装，请先选择选项 1 安装 LXD。"
        return 1
    fi
    
    # 获取脚本所在目录
    local script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    local server_dir="$script_dir/../server"
    local deploy_script="$server_dir/deploy_all.sh"
    
    # 检查 server 目录是否存在
    if [[ ! -d "$server_dir" ]]; then
        msg_error "未找到 server 目录: $server_dir"
        echo ""
        msg_info "请确保项目结构如下："
        echo "  项目根目录/"
        echo "    ├── LinuxTools-main/"
        echo "    │   └── linuxtools.sh (当前脚本)"
        echo "    └── server/"
        echo "        └── deploy_all.sh"
        return 1
    fi
    
    # 检查部署脚本是否存在
    if [[ ! -f "$deploy_script" ]]; then
        msg_error "未找到部署脚本: $deploy_script"
        return 1
    fi
    
    # 显示说明
    echo -e "${COLOR_CYAN}========================================${COLOR_NC}"
    echo -e "${COLOR_CYAN}  LXD 服务器后端一键部署${COLOR_NC}"
    echo -e "${COLOR_CYAN}========================================${COLOR_NC}"
    echo ""
    msg_info "此脚本将自动完成以下步骤:"
    echo "  1. 安装 Python 依赖"
    echo "  2. 配置网络 (IPv4 + IPv6)"
    echo "  3. 部署流量管理系统"
    echo "  4. 配置滥用防护"
    echo "  5. 启动后端 API 服务"
    echo ""
    msg_warn "预计时间: 5-10 分钟"
    echo ""
    
    # 询问确认
    read -p "$(echo -e "${COLOR_YELLOW}是否开始部署? [y/N]: ${COLOR_NC}")" confirm
    if [[ ! "${confirm}" =~ ^[yY]$ ]]; then
        msg_info "操作已由用户取消。"
        return
    fi
    
    echo ""
    msg_info "开始部署..."
    echo ""
    
    # 添加执行权限
    chmod +x "$deploy_script"
    
    # 切换到 server 目录并执行部署脚本
    cd "$server_dir" || {
        msg_error "无法进入 server 目录"
        return 1
    }
    
    # 执行部署脚本
    if bash deploy_all.sh; then
        echo ""
        msg_ok "==============================================="
        msg_ok "✓ LXD 服务器后端部署完成！"
        msg_ok "==============================================="
        echo ""
        msg_info "后续操作:"
        echo "  1. 查看部署总结（脚本输出）"
        echo "  2. 记录 API Key"
        echo "  3. 配置前端面板"
        echo ""
        msg_info "常用命令:"
        echo "  查看服务状态: systemctl status lxd-api.service"
        echo "  查看流量使用: python3 $server_dir/list_flow_usage.py"
        echo "  查看服务日志: journalctl -u lxd-api.service -f"
        echo ""
    else
        echo ""
        msg_error "部署失败，请查看上面的错误信息"
        echo ""
        msg_info "故障排查:"
        echo "  1. 查看详细日志"
        echo "  2. 检查网络连接"
        echo "  3. 确认所有依赖已安装"
        echo ""
        return 1
    fi
    
    # 返回原目录
    cd "$script_dir" || true
}

# ========================================
# 主菜单
# ========================================

show_main_menu() {
    clear_screen
    show_swap_status
    echo -e "${COLOR_GREEN}========================================="
    echo -e "    LXD 容器管理工具箱 (整合版)        "
    echo -e "=========================================${COLOR_NC}"
    echo ""
    echo -e "${COLOR_CYAN}--- LXD 环境 ---${COLOR_NC}"
    echo "  1) 安装或检查 LXD 环境"
    echo "  2) 创建 BTRFS 存储池（从文件）"
    echo ""
    echo -e "${COLOR_CYAN}--- 镜像管理 ---${COLOR_NC}"
    echo "  3) 安装 lxdimages 镜像构建工具"
    echo "  4) 构建自定义镜像"
    echo "  5) 备份所有本地 LXD 镜像"
    echo "  6) 列出本地 LXD 镜像"
    echo ""
    echo -e "${COLOR_CYAN}--- 虚拟内存管理 ---${COLOR_NC}"
    echo "  7) 安装并配置 ZRAM (内存压缩, 推荐)"
    echo "  8) 移除 ZRAM"
    echo "  9) 添加 Swap 文件 (基于硬盘)"
    echo " 10) 移除 Swap 文件"
    echo ""
    echo -e "${COLOR_CYAN}--- 服务器部署 ---${COLOR_NC}"
    echo " 11) 部署 LXD 服务器后端 (一键部署)"
    echo ""
    echo "  ---------------------------------------"
    echo -e "  ${COLOR_RED}0) 退出脚本${COLOR_NC}"
    echo -e "${COLOR_GREEN}=========================================${COLOR_NC}"
    read -p "请输入您的选择: " choice
}

# ========================================
# 主函数
# ========================================

main() {
    check_root
    check_dependencies

    while true; do
        show_main_menu
        
        case "$choice" in
            1) install_lxd ;;
            2) 
                if ! is_lxd_installed; then
                    msg_error "LXD 未安装，请先选择选项 1 安装 LXD。"
                else
                    create_btrfs_pool_from_file
                fi
                ;;
            3) 
                # 安装 lxdimages 工具，成功后自动进入选项 4
                if install_lxdimages_tool; then
                    echo ""
                    msg_info "工具安装完成，现在进入镜像构建..."
                    sleep 2
                    build_custom_images
                fi
                ;;
            4) build_custom_images ;;
            5) 
                if ! is_lxd_installed; then
                    msg_error "LXD 未安装，请先选择选项 1 安装 LXD。"
                else
                    backup_images
                fi
                ;;
            6) 
                if ! is_lxd_installed; then
                    msg_error "LXD 未安装，请先选择选项 1 安装 LXD。"
                else
                    list_images
                fi
                ;;
            7) configure_zram ;;
            8) remove_zram ;;
            9) create_swap_file ;;
            10) remove_swap_file ;;
            11) deploy_lxd_server ;;
            0) 
            msg_info "感谢使用，再见！"
            exit 0
                ;;
            *) 
            msg_error "无效的选择 '$choice'，请重新输入。"
                ;;
        esac
        
        press_any_key
    done
}

# --- 脚本执行入口 ---
trap 'printf "\033[0m"; exit' INT TERM EXIT
main "$@"
