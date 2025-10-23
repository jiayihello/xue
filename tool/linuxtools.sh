#!/bin/bash
#
# +--------------------------------------------------------------------+
# | Script Name:    LXD 工具箱（欢乐云）                              |
# | Author:         xkatld & gemini                                    |
# | Description:    LXD 容器管理、镜像构建、虚拟内存管理、服务器部署  |
# | Usage:          sudo xue (推荐) 或 sudo bash linuxtools.sh        |
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
    
    # 检查并自动安装 lxdimages
    if ! command -v lxdimages &>/dev/null; then
        msg_warn "检测到 lxdimages 工具未安装"
        msg_info "正在自动安装 lxdimages..."
        echo ""
        
        if install_lxdimages_tool; then
            msg_ok "✓ lxdimages 工具安装成功！"
            echo ""
            sleep 1
        else
            msg_error "lxdimages 工具安装失败，无法继续"
            return 1
        fi
    fi
    
    # 定义常用镜像（3个）
    declare -A common_images=(
        ["1"]="debian:bookworm:debian12:Debian 12 (bookworm)"
        ["2"]="debian:trixie:debian13:Debian 13 (trixie)"
        ["3"]="alpine:3.22:alpine322:Alpine 3.22"
    )
    
    # 定义所有镜像
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
    
    # 显示常用镜像 + 更多选项
    echo -e "${COLOR_CYAN}常用镜像:${COLOR_NC}"
    for key in $(echo "${!common_images[@]}" | tr ' ' '\n' | sort -n); do
        IFS=':' read -r dist version name desc <<< "${common_images[$key]}"
        printf "  %s) %-30s -> %s\n" "$key" "$desc" "$name"
    done
        echo ""
    echo -e "${COLOR_CYAN}  4) 更多镜像选项...${COLOR_NC}"
        echo ""
    
    read -p "输入选择（多选用空格分隔，选 4 查看全部）: " user_choice
    
    # 如果用户选择 4（更多选项），显示完整列表
    if [[ "$user_choice" == *"4"* ]]; then
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
        # 跳过"更多选项"的 4
        if [[ "$choice" == "4" ]]; then
            continue
        fi
        
        # 先在常用列表中查找
        if [[ -n "${common_images[$choice]:-}" ]]; then
            selected_images+=("${common_images[$choice]}")
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
    
    # 临时禁用 errexit，防止单个镜像构建失败导致整个脚本退出
    set +o errexit
    
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
            if lxc image list --format csv 2>/dev/null | grep -q "^$name,"; then
                msg_ok "✓ 镜像构建成功！"
                msg_ok "✓ 已导入到 LXD: $name"
                
                # 获取镜像大小
                local image_size=$(lxc image list "$name" --format csv 2>/dev/null | cut -d',' -f4 || echo "未知")
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
        rm -rf /tmp/lxdimages-* 2>/dev/null || true
        rm -rf /tmp/lxd-build-* 2>/dev/null || true
        rm -rf /var/tmp/lxdimages-* 2>/dev/null || true
        msg_ok "✓ 临时文件已清理"
        
        echo ""
        ((index++))
    done
    
    # 重新启用 errexit
    set -o errexit
    
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
        lxc image list 2>/dev/null | head -20 || echo "无法获取镜像列表"
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
    
    echo ""
    msg_ok "✓ LXD 存储池创建成功。"
    echo ""
    
    # 询问是否设为默认存储池
    read -p "$(echo -e "${COLOR_YELLOW}是否将此存储池设为默认? [Y/n]: ${COLOR_NC}")" set_default
    if [[ ! "${set_default}" =~ ^[nN]$ ]]; then
        msg_info "正在设置默认存储池..."
        
        # 获取默认 profile
        if lxc profile device set default root pool="$pool_name" 2>/dev/null; then
            msg_ok "✓ 已设置为默认存储池"
        else
            # 如果 root 设备不存在，则添加
            if lxc profile device add default root disk path=/ pool="$pool_name" 2>/dev/null; then
                msg_ok "✓ 已设置为默认存储池"
            else
                msg_warn "⚠ 设置默认存储池失败"
                msg_info "手动设置命令："
                echo "  lxc profile device set default root pool=$pool_name"
            fi
        fi
    fi
    
    echo ""
    msg_info "当前存储池列表:"
    lxc storage list
}

delete_storage_pool() {
    clear_screen
    msg_info "--- 删除 LXD 存储池 ---"
    echo ""
    
    # 显示当前存储池列表
    msg_info "当前存储池列表:"
    lxc storage list
    echo ""
    
    # 获取所有存储池名称
    local pools=$(lxc storage list --format csv | cut -d',' -f1)
    
    if [[ -z "$pools" ]]; then
        msg_warn "没有可删除的存储池"
        return
    fi
    
    # 输入要删除的存储池名称
    read -p "请输入要删除的存储池名称: " pool_name
    
    if [[ -z "$pool_name" ]]; then
        msg_error "存储池名称不能为空"
        return 1
    fi
    
    # 检查存储池是否存在
    if ! lxc storage list | grep -qP "^\s*\|\s*${pool_name}\s*\|"; then
        msg_error "存储池 '$pool_name' 不存在"
        return 1
    fi
    
    # 检查是否为默认存储池
    local is_default=false
    if lxc profile show default 2>/dev/null | grep -q "pool: $pool_name"; then
        is_default=true
        msg_warn "⚠️  警告：'$pool_name' 是默认存储池！"
        echo ""
    fi
    
    # 检查存储池中是否有容器或镜像
    msg_info "正在检查存储池使用情况..."
    local pool_info=$(lxc storage info "$pool_name" 2>/dev/null)
    
    if echo "$pool_info" | grep -q "used by:"; then
        echo ""
        msg_warn "此存储池正在被以下资源使用："
        lxc storage show "$pool_name" | grep -A 10 "used_by:" | tail -n +2
        echo ""
    fi
    
    # 显示警告
    echo -e "${COLOR_RED}========================================${COLOR_NC}"
    echo -e "${COLOR_RED}  ⚠️  警告：删除存储池${COLOR_NC}"
    echo -e "${COLOR_RED}========================================${COLOR_NC}"
    echo ""
    msg_error "此操作将："
    echo "  ✗ 删除存储池: $pool_name"
    if [[ "$is_default" == true ]]; then
        echo "  ✗ 移除默认存储池配置"
    fi
    echo "  ✗ 删除存储池中的所有数据"
    echo ""
    msg_error "⚠️  此操作不可逆！"
    echo ""
    
    # 二次确认
    read -p "$(echo -e "${COLOR_YELLOW}确认删除存储池 '$pool_name'? [y/N]: ${COLOR_NC}")" confirm1
    if [[ ! "${confirm1}" =~ ^[yY]$ ]]; then
        msg_info "操作已取消"
        return
    fi
    
    echo ""
    read -p "$(echo -e "${COLOR_RED}再次确认删除? 输入存储池名称 '$pool_name' 继续: ${COLOR_NC}")" confirm2
    if [[ "${confirm2}" != "$pool_name" ]]; then
        msg_info "操作已取消"
        return
    fi
    
    # 执行删除
    echo ""
    msg_info "正在删除存储池..."
    
    # 如果是默认存储池，先从 profile 中移除
    if [[ "$is_default" == true ]]; then
        msg_info "正在从默认 profile 中移除..."
        if lxc profile device remove default root 2>/dev/null; then
            msg_ok "✓ 已从默认 profile 移除"
        else
            msg_warn "⚠ 从 profile 移除失败，继续尝试删除存储池..."
        fi
    fi
    
    # 删除存储池
    if lxc storage delete "$pool_name"; then
        echo ""
        msg_ok "==============================================="
        msg_ok "✓ 存储池 '$pool_name' 已成功删除"
        msg_ok "==============================================="
        echo ""
        
        if [[ "$is_default" == true ]]; then
            msg_warn "提示：你可能需要设置新的默认存储池"
            msg_info "创建新存储池命令："
            echo "  选择菜单选项 4) 创建 BTRFS 存储池"
        fi
    else
        echo ""
        msg_error "删除失败！"
        echo ""
        msg_info "可能的原因："
        echo "  1. 存储池中仍有容器在使用"
        echo "  2. 存储池中仍有镜像"
        echo "  3. 存储池正在被其他资源占用"
        echo ""
        msg_info "故障排查："
        echo "  查看使用情况: lxc storage show $pool_name"
        echo "  强制删除: lxc storage delete $pool_name --force"
        return 1
    fi
    
    echo ""
    msg_info "当前存储池列表:"
    lxc storage list
}

manage_storage_pools() {
    while true; do
        clear_screen
        msg_info "--- LXD 存储池管理 ---"
        echo ""
        
        # 显示当前存储池状态
        msg_info "当前存储池状态:"
        lxc storage list
        echo ""
        
        # 显示子菜单
        echo -e "${COLOR_GREEN}=========================================${COLOR_NC}"
        echo -e "${COLOR_CYAN}  请选择操作：${COLOR_NC}"
        echo -e "${COLOR_GREEN}=========================================${COLOR_NC}"
        echo ""
        echo "  1) 创建 BTRFS 存储池"
        echo "  2) 删除存储池"
        echo "  3) 查看存储池详情"
        echo ""
        echo "  0) 返回主菜单"
        echo ""
        echo -e "${COLOR_GREEN}=========================================${COLOR_NC}"
        
        read -p "请输入您的选择: " storage_choice
        
        case "$storage_choice" in
            1)
                create_btrfs_pool_from_file
                press_any_key
                ;;
            2)
                delete_storage_pool
                press_any_key
                ;;
            3)
                clear_screen
                msg_info "--- 存储池详情 ---"
                echo ""
                
                # 获取所有存储池
                local pools=$(lxc storage list --format csv | cut -d',' -f1)
                
                if [[ -z "$pools" ]]; then
                    msg_warn "没有可用的存储池"
                else
                    echo "可用的存储池："
                    echo "$pools" | nl
                    echo ""
                    
                    read -p "输入要查看的存储池名称（或按回车返回）: " pool_name
                    
                    if [[ -n "$pool_name" ]]; then
                        echo ""
                        msg_info "存储池 '$pool_name' 的详细信息："
                        echo ""
                        lxc storage show "$pool_name"
                        echo ""
                        lxc storage info "$pool_name"
                    fi
                fi
                
                press_any_key
                ;;
            0)
                return
                ;;
            *)
                msg_error "无效的选择 '$storage_choice'，请重新输入。"
                sleep 2
                ;;
        esac
    done
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
    msg_info "--- [Swap文件] 添加/修改 Swap 文件 ---"
    show_swap_status
    
    if ! check_openvz; then
        return 1
    fi
    
    # 检查是否已存在 swap 文件或配置
    local swap_exists=false
    local swap_active=false
    local current_size=""
    
    # 检查文件是否存在
    if [[ -f "${SWAP_FILE_PATH}" ]]; then
        swap_exists=true
        # 获取当前大小（MB）
        current_size=$(du -m "${SWAP_FILE_PATH}" | awk '{print $1}')
    fi
    
    # 检查是否已激活
    if swapon --show | grep -q "${SWAP_FILE_PATH}"; then
        swap_active=true
    fi
    
    # 检查 fstab 配置
    local in_fstab=false
    if grep -q "${SWAP_FILE_PATH}" /etc/fstab; then
        in_fstab=true
    fi
    
    # 如果已存在 swap，提供修改选项
    if [[ "$swap_exists" == true ]]; then
        echo ""
        msg_warn "检测到已存在的 Swap 文件："
        echo "  路径: ${SWAP_FILE_PATH}"
        [[ -n "$current_size" ]] && echo "  当前大小: ${current_size} MB"
        [[ "$swap_active" == true ]] && echo "  状态: ✓ 已激活" || echo "  状态: ✗ 未激活"
        [[ "$in_fstab" == true ]] && echo "  开机自启: ✓ 已配置" || echo "  开机自启: ✗ 未配置"
        echo ""
        
        msg_info "请选择操作："
        echo "  1) 修改 Swap 大小（会先禁用并删除旧的）"
        echo "  2) 取消操作"
        echo ""
        read -p "请输入选择 [1-2]: " modify_choice
        
        case "$modify_choice" in
            1)
                msg_info "准备修改 Swap 文件大小..."
                
                # 禁用当前 swap
                if [[ "$swap_active" == true ]]; then
                    msg_warn "正在禁用当前 Swap..."
                    swapoff "${SWAP_FILE_PATH}" 2>/dev/null || {
                        msg_error "禁用 Swap 失败，请手动执行: swapoff ${SWAP_FILE_PATH}"
                        return 1
                    }
                    msg_ok "✓ Swap 已禁用"
                fi
                
                # 删除旧文件
                msg_warn "正在删除旧的 Swap 文件..."
                rm -f "${SWAP_FILE_PATH}"
                msg_ok "✓ 旧文件已删除"
                
                # 从 fstab 中移除（稍后会重新添加）
                if [[ "$in_fstab" == true ]]; then
                    sed -i.bak "\#${SWAP_FILE_PATH}#d" /etc/fstab
                fi
                
                echo ""
                ;;
            2|*)
                msg_info "操作已取消。"
                return
                ;;
        esac
    fi

    # 询问新的 swap 大小
    local swap_size
    while true; do
        if [[ -n "$current_size" ]]; then
            read -p "请输入新的 Swap 文件大小 (MB, 当前: ${current_size}MB, 推荐: 物理内存的1-2倍): " swap_size
        else
            read -p "请输入 Swap 文件大小 (MB, 推荐值为物理内存的1-2倍): " swap_size
        fi
        
        if [[ "$swap_size" =~ ^[1-9][0-9]*$ ]]; then
            break
        else
            msg_error "输入无效，请输入一个正整数。"
        fi
    done

    # 创建新的 swap 文件
    echo ""
    msg_info "正在创建 ${swap_size}MB 的 Swap 文件于 '${SWAP_FILE_PATH}'..."
    
    if ! fallocate -l "${swap_size}M" "${SWAP_FILE_PATH}"; then
        msg_error "创建 Swap 文件失败"
        return 1
    fi
    
    chmod 600 "${SWAP_FILE_PATH}"
    
    if ! mkswap "${SWAP_FILE_PATH}"; then
        msg_error "格式化 Swap 文件失败"
        rm -f "${SWAP_FILE_PATH}"
        return 1
    fi
    
    if ! swapon "${SWAP_FILE_PATH}"; then
        msg_error "启用 Swap 文件失败"
        return 1
    fi
    
    # 写入 fstab（如果还没有）
    if ! grep -q "${SWAP_FILE_PATH}" /etc/fstab; then
        msg_info "正在将 Swap 配置写入 /etc/fstab 以便开机自启..."
        echo "${SWAP_FILE_PATH} none swap sw 0 0" >> /etc/fstab
    fi

    echo ""
    msg_ok "✓ Swap 文件已成功创建并启用！"
    echo ""
    msg_info "当前 Swap 状态："
    swapon --show
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
        
        # 自动运行部署后检查
        msg_info "开始自动检查部署状态..."
        sleep 2
        
        local check_script="$server_dir/post_deployment_check.sh"
        if [[ -f "$check_script" ]]; then
            chmod +x "$check_script"
            if bash "$check_script"; then
                echo ""
                msg_ok "✓ 部署后检查通过！系统运行正常"
            else
                echo ""
                msg_warn "⚠ 部署后检查发现问题，请查看上方详情"
            fi
        else
            msg_warn "未找到检查脚本，跳过自动检查"
        fi
        
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

deploy_opengfw() {
    clear_screen
    msg_info "--- OpenGFW 深度包检测防火墙部署 ---"
    echo ""
    
    # 获取脚本所在目录
    local script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    local opengfw_dir="$script_dir/../server/opengfw"
    local deploy_script="$opengfw_dir/deploy_opengfw.sh"
    
    # 检查 opengfw 目录是否存在
    if [[ ! -d "$opengfw_dir" ]]; then
        msg_error "未找到 opengfw 目录: $opengfw_dir"
        echo ""
        msg_info "请确保项目结构如下："
        echo "  项目根目录/"
        echo "    ├── LinuxTools-main/"
        echo "    │   └── linuxtools.sh (当前脚本)"
        echo "    └── server/"
        echo "        └── opengfw/"
        echo "            └── deploy_opengfw.sh"
        return 1
    fi
    
    # 检查部署脚本是否存在
    if [[ ! -f "$deploy_script" ]]; then
        msg_error "未找到部署脚本: $deploy_script"
        return 1
    fi
    
    # 显示说明
    echo -e "${COLOR_CYAN}========================================${COLOR_NC}"
    echo -e "${COLOR_CYAN}  OpenGFW 防火墙部署${COLOR_NC}"
    echo -e "${COLOR_CYAN}========================================${COLOR_NC}"
    echo ""
    msg_info "OpenGFW 是什么？"
    echo "  ✓ 深度包检测 (DPI) 工具"
    echo "  ✓ 可拦截代理协议（Shadowsocks、Trojan、Socks 等）"
    echo "  ✓ 可拦截 VPN 协议（WireGuard）"
    echo "  ✓ 可拦截 BT 下载"
    echo "  ✓ 支持基于地域的智能拦截"
    echo ""
    msg_info "适用场景："
    echo "  🔹 LXD 容器服务器的流量管控"
    echo "  🔹 防止滥用（代理转发、BT 下载等）"
    echo "  🔹 合规性管理"
    echo ""
    msg_warn "⚠️  重要提示："
    echo "  • OpenGFW 会分析所有经过宿主机的流量"
    echo "  • 仅影响 LXD 容器流量，不影响宿主机本身"
    echo "  • 部署前请确保了解法律法规要求"
    echo ""
    msg_info "此脚本将自动完成："
    echo "  1. 检测系统架构 (AMD64/ARM64)"
    echo "  2. 下载 OpenGFW v0.4.1"
    echo "  3. 下载 GeoIP 数据库"
    echo "  4. 配置 iptables 规则"
    echo "  5. 创建 systemd 服务"
    echo "  6. 交互式选择拦截策略"
    echo ""
    msg_warn "预计时间: 3-5 分钟"
    echo ""
    
    # 询问确认
    echo -e "${COLOR_YELLOW}========================================${COLOR_NC}"
    echo -e "${COLOR_YELLOW}  ⚠️  请仔细阅读上述说明${COLOR_NC}"
    echo -e "${COLOR_YELLOW}========================================${COLOR_NC}"
    echo ""
    read -p "$(echo -e "${COLOR_YELLOW}是否开始部署 OpenGFW? [y/N]: ${COLOR_NC}")" confirm
    if [[ ! "${confirm}" =~ ^[yY]$ ]]; then
        msg_info "操作已由用户取消。"
        return
    fi
    
    echo ""
    msg_info "开始部署 OpenGFW..."
    echo ""
    
    # 添加执行权限
    chmod +x "$deploy_script"
    
    # 切换到 opengfw 目录并执行部署脚本
    cd "$opengfw_dir" || {
        msg_error "无法进入 opengfw 目录"
        return 1
    }
    
    # 执行部署脚本（直接运行，会有交互式选项）
    if bash deploy_opengfw.sh; then
        echo ""
        echo ""
        msg_ok "==============================================="
        msg_ok "✓ OpenGFW 部署流程已完成！"
        msg_ok "==============================================="
        echo ""
        
        # 自动复制管理脚本到 /etc/opengfw/
        msg_info "正在安装管理脚本..."
        if [[ -f "$opengfw_dir/manage_opengfw.sh" ]]; then
            if cp "$opengfw_dir/manage_opengfw.sh" /etc/opengfw/manage_opengfw.sh 2>/dev/null; then
                chmod +x /etc/opengfw/manage_opengfw.sh
                msg_ok "✓ 管理脚本已安装到 /etc/opengfw/manage_opengfw.sh"
            else
                msg_warn "⚠️  管理脚本复制失败，请手动复制"
            fi
        else
            msg_warn "⚠️  未找到管理脚本: $opengfw_dir/manage_opengfw.sh"
        fi
        echo ""
        
        # 检查服务状态
        msg_info "正在检查服务状态..."
        sleep 1
        
        if systemctl is-active --quiet opengfw.service; then
            msg_ok "✓ OpenGFW 服务运行正常"
            echo ""
            
            msg_info "服务信息："
            systemctl status opengfw.service --no-pager -l | head -10
            echo ""
        else
            msg_warn "⚠️  服务未运行，请检查日志"
            echo ""
        fi
        
        msg_info "常用管理命令："
        echo "  图形化管理:     bash /etc/opengfw/manage_opengfw.sh"
        echo "  查看服务状态:   systemctl status opengfw"
        echo "  查看实时日志:   journalctl -u opengfw -f"
        echo "  查看拦截日志:   journalctl -u opengfw -f | grep 'block'"
        echo "  重启服务:       systemctl restart opengfw"
        echo "  停止服务:       systemctl stop opengfw"
        echo "  编辑规则:       nano /etc/opengfw/rules.yaml"
        echo "  编辑配置:       nano /etc/opengfw/config.yaml"
        echo ""
        
        msg_info "配置文件位置："
        echo "  主配置:   /etc/opengfw/config.yaml"
        echo "  规则文件: /etc/opengfw/rules.yaml"
        echo "  GeoIP:    /etc/opengfw/geoip.dat"
        echo "  管理脚本: /etc/opengfw/manage_opengfw.sh"
        echo "  卸载脚本: /etc/opengfw/uninstall.sh"
        echo ""
        
        msg_ok "提示：您也可以在主菜单选择 '14) 管理 OpenGFW' 来使用图形化管理界面"
        echo ""
        
    else
        echo ""
        msg_error "部署失败，请查看上面的错误信息"
        echo ""
        msg_info "故障排查："
        echo "  1. 检查网络连接（需下载 GitHub 文件）"
        echo "  2. 确认 iptables 工作正常"
        echo "  3. 查看详细错误日志"
        echo ""
        msg_info "手动排查命令："
        echo "  检查 iptables: iptables -L -n -v"
        echo "  检查网络:      curl -I https://github.com"
        echo "  查看日志:      journalctl -xe"
        echo ""
        return 1
    fi
    
    # 返回原目录
    cd "$script_dir" || true
}

manage_opengfw() {
    clear_screen
    msg_info "--- OpenGFW 图形化管理界面 ---"
    echo ""
    
    # 检查 OpenGFW 服务是否存在
    if ! systemctl list-unit-files | grep -q "opengfw.service"; then
        msg_error "OpenGFW 服务未安装"
        echo ""
        msg_info "请先部署 OpenGFW："
        echo "  1. 返回主菜单"
        echo "  2. 选择 '13) 部署 OpenGFW 防火墙'"
        echo ""
        return 1
    fi
    
    # 检查管理脚本是否存在
    local manage_script="/etc/opengfw/manage_opengfw.sh"
    
    if [[ ! -f "$manage_script" ]]; then
        msg_warn "管理脚本未找到: $manage_script"
        echo ""
        msg_info "正在尝试从工具集复制..."
        
        # 尝试从工具集目录复制
        local script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
        local source_script="$script_dir/../server/opengfw/manage_opengfw.sh"
        
        if [[ -f "$source_script" ]]; then
            if cp "$source_script" "$manage_script" 2>/dev/null; then
                chmod +x "$manage_script"
                msg_ok "✓ 管理脚本已安装"
                echo ""
            else
                msg_error "复制失败，请手动安装管理脚本："
                echo "  cp $source_script $manage_script"
                echo "  chmod +x $manage_script"
                return 1
            fi
        else
            msg_error "源脚本也不存在: $source_script"
            echo ""
            msg_info "请确保工具集完整，或手动上传管理脚本"
            return 1
        fi
    fi
    
    # 显示当前状态
    echo -e "${COLOR_CYAN}========================================${COLOR_NC}"
    echo -e "${COLOR_CYAN}  当前状态${COLOR_NC}"
    echo -e "${COLOR_CYAN}========================================${COLOR_NC}"
    echo ""
    
    # 检查服务状态
    if systemctl is-active --quiet opengfw.service; then
        msg_ok "服务状态: ✓ 运行中"
    else
        msg_error "服务状态: ✗ 已停止"
    fi
    
    # 显示配置信息
    if [[ -f /etc/opengfw/rules.yaml ]]; then
        local rule_count=$(grep -c "^- name:" /etc/opengfw/rules.yaml 2>/dev/null || echo "0")
        msg_info "规则数量: $rule_count 条"
    fi
    
    echo ""
    echo -e "${COLOR_CYAN}========================================${COLOR_NC}"
    echo ""
    
    # 询问是否启动管理界面
    read -p "$(echo -e "${COLOR_YELLOW}是否启动图形化管理界面? [Y/n]: ${COLOR_NC}")" confirm
    if [[ "${confirm}" =~ ^[nN]$ ]]; then
        msg_info "操作已取消"
        return
    fi
    
    echo ""
    msg_info "正在启动管理界面..."
    echo ""
    sleep 1
    
    # 运行管理脚本
    if bash "$manage_script"; then
        echo ""
        msg_ok "管理界面已退出"
    else
        echo ""
        msg_error "管理脚本执行出错"
        echo ""
        msg_info "您也可以直接运行："
        echo "  bash $manage_script"
        return 1
    fi
}

# ========================================
# 完整卸载工具集
# ========================================

uninstall_toolkit() {
    clear_screen
    msg_info "--- 完整卸载工具集 ---"
    echo ""
    
    local target_dir="/root/lxd-toolkit"
    
    # 检查目录是否存在
    if [[ ! -d "$target_dir" ]]; then
        msg_warn "未找到工具集目录: $target_dir"
        echo ""
        msg_info "工具集可能未安装或已被删除"
        return
    fi
    
    # 显示警告
    echo -e "${COLOR_RED}========================================${COLOR_NC}"
    echo -e "${COLOR_RED}  ⚠️  警告：完整卸载${COLOR_NC}"
    echo -e "${COLOR_RED}========================================${COLOR_NC}"
    echo ""
    msg_warn "此操作将删除以下内容："
    echo "  📁 $target_dir/tool/      - LinuxTools 工具箱"
    echo "  📁 $target_dir/server/    - LXD 服务器后端"
    echo "  📁 所有下载的文件和配置"
    echo "  🔧 /usr/local/bin/xue     - 全局命令"
    echo ""
    msg_error "⚠️  此操作不可逆！"
    echo ""
    msg_info "以下内容不会被删除："
    echo "  ✓ LXD 环境和容器"
    echo "  ✓ ZRAM/SWAP 配置"
    echo "  ✓ 流量管理数据库"
    echo "  ✓ 系统服务配置"
    echo ""
    
    # 二次确认
    read -p "$(echo -e "${COLOR_YELLOW}是否确认删除? [y/N]: ${COLOR_NC}")" confirm1
    if [[ ! "${confirm1}" =~ ^[yY]$ ]]; then
        msg_info "操作已取消。"
        return
    fi
    
    echo ""
    read -p "$(echo -e "${COLOR_RED}再次确认删除? 输入 'YES' 继续: ${COLOR_NC}")" confirm2
    if [[ "${confirm2}" != "YES" ]]; then
        msg_info "操作已取消。"
        return
    fi
    
    # 执行删除
    echo ""
    msg_info "正在卸载工具集..."
    
    # 删除工具集目录
    local removed_dir=false
    local removed_cmd=false
    
    if rm -rf "$target_dir" 2>/dev/null; then
        msg_ok "✓ 已删除目录: $target_dir"
        removed_dir=true
    else
        msg_error "✗ 删除目录失败: $target_dir"
    fi
    
    # 删除全局命令
    local xue_cmd="/usr/local/bin/xue"
    if [[ -f "$xue_cmd" ]]; then
        if rm -f "$xue_cmd" 2>/dev/null; then
            msg_ok "✓ 已删除全局命令: xue"
            removed_cmd=true
        else
            msg_warn "⚠ 无法删除命令: $xue_cmd"
        fi
    fi
    
    echo ""
    
    if [[ "$removed_dir" == true ]]; then
        msg_ok "==============================================="
        msg_ok "✓ 工具集已完全卸载"
        msg_ok "==============================================="
        echo ""
        msg_info "如需重新安装，请执行："
        echo "  bash <(curl -sSL https://raw.githubusercontent.com/jiayihello/xue/old/tool/linuxtools.sh)"
        echo "  然后选择菜单选项 1 (下载完整工具集到本地)"
        echo ""
    else
        msg_error "卸载失败，请手动删除："
        echo "  rm -rf $target_dir"
        echo "  rm -f $xue_cmd"
        return 1
    fi
}

# ========================================
# 下载完整工具集到本地
# ========================================

download_repository() {
    clear_screen
    msg_info "--- 下载完整工具集到本地 ---"
    echo ""
    
    # 仓库信息
    local repo_url="https://github.com/jiayihello/xue.git"
    local branch="old"
    local target_dir="/root/lxd-toolkit"
    
    # 显示说明
    echo -e "${COLOR_CYAN}========================================${COLOR_NC}"
    echo -e "${COLOR_CYAN}  下载完整工具集${COLOR_NC}"
    echo -e "${COLOR_CYAN}========================================${COLOR_NC}"
    echo ""
    msg_info "将下载以下内容到 $target_dir："
    echo "  📁 tool/      - LinuxTools 工具箱"
    echo "  📁 server/    - LXD 服务器后端"
    echo ""
    msg_info "包含所有依赖文件："
    echo "  ✓ lxdimages 二进制文件"
    echo "  ✓ 部署脚本"
    echo "  ✓ 配置文件"
    echo ""
    msg_warn "预计大小: ~20MB"
    echo ""
    
    # 询问确认
    read -p "$(echo -e "${COLOR_YELLOW}是否下载? [y/N]: ${COLOR_NC}")" confirm
    if [[ ! "${confirm}" =~ ^[yY]$ ]]; then
        msg_info "操作已由用户取消。"
        return
    fi
    
    echo ""
    msg_info "开始下载..."
    echo ""
    
    # 检查 git
    if ! command -v git &> /dev/null; then
        msg_warn "Git 未安装，正在安装..."
        if apt-get update && apt-get install -y git 2>/dev/null || yum install -y git 2>/dev/null; then
            msg_ok "✓ Git 安装成功"
        else
            msg_error "Git 安装失败，请手动安装: apt install git 或 yum install git"
            return 1
        fi
    fi
    
    # 如果目标目录已存在，询问是否覆盖
    if [[ -d "$target_dir" ]]; then
        echo ""
        msg_warn "目标目录已存在: $target_dir"
        read -p "$(echo -e "${COLOR_YELLOW}是否删除并重新下载? [y/N]: ${COLOR_NC}")" overwrite
        if [[ "${overwrite}" =~ ^[yY]$ ]]; then
            msg_info "删除旧目录..."
            rm -rf "$target_dir"
            msg_ok "✓ 已删除旧目录"
        else
            msg_info "操作已取消。"
            return
        fi
    fi
    
    # 克隆仓库
    echo ""
    msg_info "正在从 GitHub 下载..."
    echo ""
    
    if git clone -b "$branch" "$repo_url" "$target_dir"; then
        echo ""
        msg_ok "==============================================="
        msg_ok "✓ 下载完成！"
        msg_ok "==============================================="
        echo ""
        
        # 创建全局命令
        msg_info "正在创建全局命令..."
        local xue_cmd="/usr/local/bin/xue"
        
        cat > "$xue_cmd" << 'EOF'
#!/bin/bash
# LXD 工具箱（欢乐云）- 快捷启动脚本

TOOLKIT_DIR="/root/lxd-toolkit/tool"
SCRIPT_PATH="$TOOLKIT_DIR/linuxtools.sh"

if [[ ! -f "$SCRIPT_PATH" ]]; then
    echo -e "\033[0;31m[!] 错误: 未找到工具集\033[0m"
    echo ""
    echo "工具集可能未安装或已被删除。"
    echo ""
    echo "请先安装工具集："
    echo "  bash <(curl -sSL https://raw.githubusercontent.com/jiayihello/xue/old/tool/linuxtools.sh)"
    exit 1
fi

# 检查 root 权限
if [[ "${EUID}" -ne 0 ]]; then
    echo -e "\033[0;31m[!] 错误: 需要 root 权限\033[0m"
    echo ""
    echo "请使用以下命令之一："
    echo "  sudo xue"
    echo "  sudo -i"
    echo "  su -"
    exit 1
fi

cd "$TOOLKIT_DIR" || exit 1
exec bash linuxtools.sh "$@"
EOF
        
        chmod +x "$xue_cmd"
        msg_ok "✓ 全局命令创建成功"
        echo ""
        
        # 显示使用说明
        echo -e "${COLOR_GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${COLOR_NC}"
        echo -e "${COLOR_GREEN}  使用方法${COLOR_NC}"
        echo -e "${COLOR_GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${COLOR_NC}"
        echo ""
        echo -e "${COLOR_CYAN}🚀 快捷命令（推荐）：${COLOR_NC}"
        echo -e "   ${COLOR_YELLOW}sudo xue${COLOR_NC}          - 启动 LXD 工具箱"
        echo ""
        echo -e "${COLOR_CYAN}1️⃣  LinuxTools 工具箱：${COLOR_NC}"
        echo "   cd $target_dir/tool"
        echo "   sudo bash linuxtools.sh"
        echo ""
        echo -e "${COLOR_CYAN}2️⃣  Server 后端部署：${COLOR_NC}"
        echo "   cd $target_dir/server"
        echo "   sudo bash deploy_all.sh"
        echo ""
        echo -e "${COLOR_GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${COLOR_NC}"
        echo ""
        
        # 询问是否立即切换到本地版本
        read -p "$(echo -e "${COLOR_YELLOW}是否立即启动工具箱? [Y/n]: ${COLOR_NC}")" switch
        if [[ ! "${switch}" =~ ^[nN]$ ]]; then
            echo ""
            msg_info "正在启动工具箱..."
            cd "$target_dir/tool" || {
                msg_error "无法切换到目录: $target_dir/tool"
                return 1
            }
            chmod +x linuxtools.sh
            sleep 1
            exec bash linuxtools.sh
        fi
    else
        echo ""
        msg_error "下载失败，请检查："
        echo "  1. 网络连接是否正常"
        echo "  2. GitHub 是否可以访问"
        echo "  3. 磁盘空间是否充足"
        echo ""
        msg_info "手动下载命令："
        echo "  git clone -b $branch $repo_url $target_dir"
        return 1
    fi
}

# ========================================
# 主菜单
# ========================================

show_main_menu() {
    clear_screen
    show_swap_status
    echo -e "${COLOR_GREEN}========================================="
    echo -e "       LXD 工具箱（欢乐云）          "
    echo -e "=========================================${COLOR_NC}"
    echo ""
    echo -e "${COLOR_CYAN}--- 工具管理 ---${COLOR_NC}"
    echo "  1) 下载完整工具集到本地"
    echo "  2) 完整卸载工具集"
    echo ""
    echo -e "${COLOR_CYAN}--- LXD 环境 ---${COLOR_NC}"
    echo "  3) 安装或检查 LXD 环境"
    echo "  4) 存储池管理"
    echo ""
    echo -e "${COLOR_CYAN}--- 镜像管理 ---${COLOR_NC}"
    echo "  5) 构建自定义镜像"
    echo "  6) 备份所有本地 LXD 镜像"
    echo "  7) 列出本地 LXD 镜像"
    echo ""
    echo -e "${COLOR_CYAN}--- 虚拟内存管理 ---${COLOR_NC}"
    echo "  8) 安装并配置 ZRAM (内存压缩, 推荐)"
    echo "  9) 移除 ZRAM"
    echo " 10) 添加/修改 Swap 文件 (基于硬盘)"
    echo " 11) 移除 Swap 文件"
    echo ""
    echo -e "${COLOR_CYAN}--- 服务器部署 ---${COLOR_NC}"
    echo " 12) 部署 LXD 服务器后端 (一键部署)"
    echo ""
    echo -e "${COLOR_CYAN}--- OpenGFW 防火墙 ---${COLOR_NC}"
    echo " 13) 部署 OpenGFW 防火墙 (DPI 深度包检测)"
    echo " 14) 管理 OpenGFW (图形化管理界面)"
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
            1) download_repository ;;
            2) uninstall_toolkit ;;
            3) install_lxd ;;
            4) 
                if ! is_lxd_installed; then
                    msg_error "LXD 未安装，请先选择选项 3 安装 LXD。"
                else
                    manage_storage_pools
                fi
                ;;
            5) build_custom_images ;;
            6) 
                if ! is_lxd_installed; then
                    msg_error "LXD 未安装，请先选择选项 3 安装 LXD。"
                else
                    backup_images
                fi
                ;;
            7) 
                if ! is_lxd_installed; then
                    msg_error "LXD 未安装，请先选择选项 3 安装 LXD。"
                else
                    list_images
                fi
                ;;
            8) configure_zram ;;
            9) remove_zram ;;
            10) create_swap_file ;;
            11) remove_swap_file ;;
            12) deploy_lxd_server ;;
            13) deploy_opengfw ;;
            14) manage_opengfw ;;
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
