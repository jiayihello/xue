#!/bin/bash
# =====================================
# LXD 后端系统升级脚本
# =====================================
# 功能：
# 1. 自动备份现有系统
# 2. 安全升级到最新版本
# 3. 保留所有容器和配置
# 4. 迁移流量数据（如果需要）
# 5. 验证升级结果
# =====================================

set -e  # 遇到错误立即退出

# 颜色定义
COLOR_GREEN='\033[0;32m'
COLOR_YELLOW='\033[1;33m'
COLOR_RED='\033[0;31m'
COLOR_BLUE='\033[0;34m'
COLOR_NC='\033[0m'

# 日志函数
log_info() {
    echo -e "${COLOR_BLUE}[信息]${COLOR_NC} $1"
}

log_ok() {
    echo -e "${COLOR_GREEN}[成功]${COLOR_NC} $1"
}

log_warn() {
    echo -e "${COLOR_YELLOW}[警告]${COLOR_NC} $1"
}

log_error() {
    echo -e "${COLOR_RED}[错误]${COLOR_NC} $1"
}

# 检查 root 权限
check_root() {
    if [ "$EUID" -ne 0 ]; then
        log_error "请使用 root 权限运行此脚本"
        log_info "使用命令: sudo bash $0"
        exit 1
    fi
}

# 询问用户确认
ask_yes_no() {
    local prompt="$1"
    local default="${2:-n}"
    
    if [ "$default" = "y" ]; then
        prompt="$prompt [Y/n]: "
    else
        prompt="$prompt [y/N]: "
    fi
    
    while true; do
        read -p "$prompt" response
        response=${response:-$default}
        case "$response" in
            [Yy]* ) return 0 ;;
            [Nn]* ) return 1 ;;
            * ) echo "请输入 y 或 n" ;;
        esac
    done
}

# 获取当前目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKUP_DIR="${SCRIPT_DIR}/backup_$(date +%Y%m%d_%H%M%S)"

echo ""
echo "========================================"
echo "  LXD 后端系统升级工具"
echo "========================================"
echo ""
log_info "当前目录: $SCRIPT_DIR"
log_info "备份目录: $BACKUP_DIR"
echo ""

# 检查权限
check_root

# =====================================
# 步骤 1: 系统状态检查
# =====================================
echo "========================================"
echo "  步骤 1/7: 系统状态检查"
echo "========================================"
echo ""

# 检查当前版本
if [ -f "$SCRIPT_DIR/app.py" ]; then
    log_ok "找到现有的 app.py"
else
    log_error "未找到 app.py，请确认当前目录是否正确"
    exit 1
fi

# 检查是否有运行中的服务
log_info "检查运行中的服务..."
RUNNING_SERVICES=()
for service in lxd-api.service lxd-flow-collector.service lxd-event-listener.service flow-limit-enforcer.service flow-reset-scheduler.service; do
    if systemctl is-active --quiet $service 2>/dev/null; then
        RUNNING_SERVICES+=($service)
        log_ok "服务运行中: $service"
    fi
done

if [ ${#RUNNING_SERVICES[@]} -eq 0 ]; then
    log_warn "未检测到运行中的服务"
    if ! ask_yes_no "继续升级吗？" "y"; then
        log_info "用户取消升级"
        exit 0
    fi
fi

# 检查 LXD 是否正常
log_info "检查 LXD 状态..."
if lxc list >/dev/null 2>&1; then
    CONTAINER_COUNT=$(lxc list -c n -f csv | wc -l)
    log_ok "LXD 运行正常，共有 $CONTAINER_COUNT 个容器"
else
    log_error "LXD 未正常运行，请先修复 LXD"
    exit 1
fi

# =====================================
# 步骤 2: 创建备份
# =====================================
echo ""
echo "========================================"
echo "  步骤 2/7: 创建系统备份"
echo "========================================"
echo ""

if ask_yes_no "是否创建备份（强烈建议）？" "y"; then
    log_info "创建备份目录: $BACKUP_DIR"
    mkdir -p "$BACKUP_DIR"
    
    # 备份关键文件
    log_info "备份 Python 文件..."
    cp -r "$SCRIPT_DIR"/*.py "$BACKUP_DIR/" 2>/dev/null || true
    
    log_info "备份配置文件..."
    cp "$SCRIPT_DIR/app.ini" "$BACKUP_DIR/" 2>/dev/null || true
    cp "$SCRIPT_DIR/requirements.txt" "$BACKUP_DIR/" 2>/dev/null || true
    
    log_info "备份部署脚本..."
    cp "$SCRIPT_DIR"/*.sh "$BACKUP_DIR/" 2>/dev/null || true
    
    # 备份数据库（如果存在）
    log_info "备份数据库..."
    if [ -f "$SCRIPT_DIR/flow_data_v2.db" ]; then
        cp "$SCRIPT_DIR/flow_data_v2.db" "$BACKUP_DIR/"
        log_ok "备份流量数据库 V2"
    fi
    if [ -f "$SCRIPT_DIR/flow_data.db" ]; then
        cp "$SCRIPT_DIR/flow_data.db" "$BACKUP_DIR/"
        log_ok "备份流量数据库 V1（旧）"
    fi
    
    # 备份元数据
    log_info "备份元数据文件..."
    cp "$SCRIPT_DIR"/*.json "$BACKUP_DIR/" 2>/dev/null || true
    
    # 备份 systemd 服务文件
    log_info "备份 systemd 服务配置..."
    mkdir -p "$BACKUP_DIR/systemd"
    for service in lxd-api.service lxd-flow-collector.service lxd-event-listener.service flow-limit-enforcer.service flow-reset-scheduler.service; do
        if [ -f "/etc/systemd/system/$service" ]; then
            cp "/etc/systemd/system/$service" "$BACKUP_DIR/systemd/"
        fi
    done
    
    log_ok "备份完成: $BACKUP_DIR"
    
    # 创建备份说明
    cat > "$BACKUP_DIR/README.txt" << EOF
LXD 后端系统备份
================

备份时间: $(date)
备份位置: $BACKUP_DIR

此备份包含：
- 所有 Python 模块（*.py）
- 配置文件（app.ini, requirements.txt）
- 部署脚本（*.sh）
- 流量数据库（*.db）
- 元数据文件（*.json）
- Systemd 服务配置

如需恢复，请运行：
sudo bash restore_from_backup.sh $BACKUP_DIR

或手动复制文件到原目录。
EOF
    
    log_info "备份说明已保存到: $BACKUP_DIR/README.txt"
else
    log_warn "跳过备份（不推荐）"
fi

# =====================================
# 步骤 3: 停止旧服务
# =====================================
echo ""
echo "========================================"
echo "  步骤 3/7: 停止现有服务"
echo "========================================"
echo ""

log_info "停止所有相关服务..."
for service in lxd-api.service lxd-flow-collector.service lxd-event-listener.service flow-limit-enforcer.service flow-reset-scheduler.service periodic-sync.service; do
    if systemctl is-active --quiet $service 2>/dev/null; then
        log_info "停止服务: $service"
        systemctl stop $service
        log_ok "已停止: $service"
    fi
done

# =====================================
# 步骤 4: 更新代码
# =====================================
echo ""
echo "========================================"
echo "  步骤 4/7: 更新代码文件"
echo "========================================"
echo ""

log_info "当前目录已包含最新代码"
log_info "如需从远程更新，请执行："
log_info "  git pull origin main"
echo ""

if ask_yes_no "是否现在从 Git 拉取最新代码？" "n"; then
    log_info "从 Git 拉取最新代码..."
    if [ -d "$SCRIPT_DIR/.git" ]; then
        git pull origin main || log_warn "Git 拉取失败，继续使用当前代码"
    else
        log_warn "不是 Git 仓库，跳过"
    fi
else
    log_info "跳过 Git 拉取"
fi

# =====================================
# 步骤 5: 更新依赖
# =====================================
echo ""
echo "========================================"
echo "  步骤 5/7: 更新 Python 依赖"
echo "========================================"
echo ""

if [ -f "$SCRIPT_DIR/requirements.txt" ]; then
    log_info "安装/更新 Python 依赖..."
    pip3 install -r "$SCRIPT_DIR/requirements.txt" --upgrade
    log_ok "依赖更新完成"
else
    log_warn "未找到 requirements.txt"
fi

# =====================================
# 步骤 6: 数据迁移
# =====================================
echo ""
echo "========================================"
echo "  步骤 6/7: 数据迁移（如果需要）"
echo "========================================"
echo ""

# 检查是否需要从 V1 迁移到 V2
if [ -f "$SCRIPT_DIR/flow_data.db" ] && [ ! -f "$SCRIPT_DIR/flow_data_v2.db" ]; then
    log_warn "检测到旧版流量数据库（V1），需要迁移到 V2"
    
    if ask_yes_no "是否现在执行数据迁移？" "y"; then
        if [ -f "$SCRIPT_DIR/migrate_to_v2.py" ]; then
            log_info "执行数据迁移..."
            python3 "$SCRIPT_DIR/migrate_to_v2.py" || log_warn "数据迁移失败，但可以继续"
            log_ok "数据迁移完成"
        else
            log_warn "未找到迁移脚本 migrate_to_v2.py"
        fi
    else
        log_warn "跳过数据迁移（流量统计将从零开始）"
    fi
elif [ -f "$SCRIPT_DIR/flow_data_v2.db" ]; then
    log_ok "已使用 V2 流量数据库，无需迁移"
else
    log_info "未检测到流量数据库，将创建新的 V2 数据库"
fi

# =====================================
# 步骤 7: 重启服务
# =====================================
echo ""
echo "========================================"
echo "  步骤 7/7: 重新部署服务"
echo "========================================"
echo ""

if ask_yes_no "是否运行一键部署脚本 (deploy_all.sh)？" "y"; then
    if [ -f "$SCRIPT_DIR/deploy_all.sh" ]; then
        log_info "运行部署脚本..."
        bash "$SCRIPT_DIR/deploy_all.sh"
        log_ok "部署完成"
    else
        log_warn "未找到 deploy_all.sh，请手动部署"
    fi
else
    log_info "跳过自动部署"
    log_info "您可以手动运行以下命令启动服务："
    echo ""
    echo "  systemctl daemon-reload"
    echo "  systemctl restart lxd-api.service"
    echo "  systemctl restart lxd-flow-collector.service"
    echo "  systemctl restart lxd-event-listener.service"
    echo "  systemctl restart flow-limit-enforcer.service"
    echo "  systemctl restart flow-reset-scheduler.service"
    echo ""
fi

# =====================================
# 完成
# =====================================
echo ""
echo "========================================"
echo "  升级完成！"
echo "========================================"
echo ""

log_ok "后端系统已升级到最新版本"
echo ""
log_info "检查服务状态："
echo ""

# 显示服务状态
for service in lxd-api.service lxd-flow-collector.service lxd-event-listener.service flow-limit-enforcer.service flow-reset-scheduler.service; do
    if systemctl is-active --quiet $service 2>/dev/null; then
        log_ok "$service: 运行中 ✓"
    else
        log_warn "$service: 未运行"
    fi
done

echo ""
log_info "备份位置: $BACKUP_DIR"
log_info "查看日志: journalctl -u lxd-api.service -f"
log_info "测试 API: curl -H \"apikey: YOUR_TOKEN\" http://localhost:8060/api/check"
echo ""
log_ok "升级完成！如有问题，请查看日志或从备份恢复。"
echo ""

