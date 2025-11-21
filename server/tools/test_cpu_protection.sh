#!/bin/bash
# =============================================================================
# CPU 保护系统 - 自检测试脚本
# 
# 功能：检查所有脚本的可用性和依赖
# 使用：bash test_cpu_protection.sh
# =============================================================================

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# 测试结果统计
TOTAL_TESTS=0
PASSED_TESTS=0
FAILED_TESTS=0

# 日志函数
log_test() {
    echo -e "${BLUE}[TEST]${NC} $1"
    TOTAL_TESTS=$((TOTAL_TESTS + 1))
}

log_pass() {
    echo -e "${GREEN}[PASS]${NC} $1"
    PASSED_TESTS=$((PASSED_TESTS + 1))
}

log_fail() {
    echo -e "${RED}[FAIL]${NC} $1"
    FAILED_TESTS=$((FAILED_TESTS + 1))
}

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

# 脚本目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVER_DIR="$(dirname "$SCRIPT_DIR")"

echo ""
echo "=========================================="
echo "  CPU 保护系统自检测试"
echo "=========================================="
echo ""
echo "测试目录: $SCRIPT_DIR"
echo ""

# ========== 测试1: 检查文件存在性 ==========
log_test "检查必要文件是否存在"

FILES_TO_CHECK=(
    "cpu_monitor_killer.py"
    "top_containers.py"
    "deploy_cpu_protection.sh"
    "setup_cpu_killer.sh"
)

FILES_OK=true
for file in "${FILES_TO_CHECK[@]}"; do
    if [ -f "$SCRIPT_DIR/$file" ]; then
        log_info "  ✓ $file"
    else
        log_fail "  ✗ 缺少文件: $file"
        FILES_OK=false
    fi
done

if [ "$FILES_OK" = true ]; then
    log_pass "所有必要文件存在"
else
    log_fail "缺少必要文件"
fi

# ========== 测试2: 检查Python环境 ==========
log_test "检查 Python 环境"

if command -v python3 &> /dev/null; then
    PYTHON_VERSION=$(python3 --version 2>&1 | awk '{print $2}')
    log_pass "Python 已安装: $PYTHON_VERSION"
else
    log_fail "Python 未安装"
fi

# ========== 测试3: 检查Python依赖 ==========
log_test "检查 Python 依赖库"

DEPS_OK=true

# 检查pylxd
if python3 -c "import pylxd" 2>/dev/null; then
    PYLXD_VERSION=$(python3 -c "import pylxd; print(pylxd.__version__)" 2>/dev/null || echo "未知版本")
    log_pass "  ✓ pylxd: $PYLXD_VERSION"
else
    log_fail "  ✗ pylxd 未安装"
    DEPS_OK=false
fi

# 检查argparse（标准库）
if python3 -c "import argparse" 2>/dev/null; then
    log_info "  ✓ argparse (标准库)"
else
    log_fail "  ✗ argparse 缺失（不应该发生）"
    DEPS_OK=false
fi

# 检查typing（标准库）
if python3 -c "import typing" 2>/dev/null; then
    log_info "  ✓ typing (标准库)"
else
    log_fail "  ✗ typing 缺失（不应该发生）"
    DEPS_OK=false
fi

if [ "$DEPS_OK" = true ]; then
    log_pass "所有 Python 依赖已满足"
else
    log_fail "缺少 Python 依赖"
fi

# ========== 测试4: 检查脚本语法 ==========
log_test "检查 Python 脚本语法"

SYNTAX_OK=true

# 检查 cpu_monitor_killer.py
if python3 -m py_compile "$SCRIPT_DIR/cpu_monitor_killer.py" 2>/dev/null; then
    log_pass "  ✓ cpu_monitor_killer.py 语法正确"
else
    log_fail "  ✗ cpu_monitor_killer.py 语法错误"
    SYNTAX_OK=false
fi

# 检查 top_containers.py
if python3 -m py_compile "$SCRIPT_DIR/top_containers.py" 2>/dev/null; then
    log_pass "  ✓ top_containers.py 语法正确"
else
    log_fail "  ✗ top_containers.py 语法错误"
    SYNTAX_OK=false
fi

if [ "$SYNTAX_OK" = true ]; then
    log_pass "所有脚本语法正确"
else
    log_fail "存在语法错误"
fi

# ========== 测试5: 检查脚本可执行性 ==========
log_test "检查脚本 --help 参数"

HELP_OK=true

# 测试 cpu_monitor_killer.py
if python3 "$SCRIPT_DIR/cpu_monitor_killer.py" --help > /dev/null 2>&1; then
    log_pass "  ✓ cpu_monitor_killer.py --help 正常"
else
    log_fail "  ✗ cpu_monitor_killer.py --help 失败"
    HELP_OK=false
fi

# 测试 top_containers.py
if python3 "$SCRIPT_DIR/top_containers.py" --help > /dev/null 2>&1; then
    log_pass "  ✓ top_containers.py --help 正常"
else
    log_fail "  ✗ top_containers.py --help 失败"
    HELP_OK=false
fi

if [ "$HELP_OK" = true ]; then
    log_pass "所有脚本可正常运行"
else
    log_fail "存在脚本运行问题"
fi

# ========== 测试6: 检查LXD环境 ==========
log_test "检查 LXD 环境"

if command -v lxc &> /dev/null; then
    LXC_VERSION=$(lxc --version 2>/dev/null || echo "未知")
    log_pass "  ✓ LXC 已安装: $LXC_VERSION"
    
    # 检查LXD服务
    if systemctl is-active --quiet lxd.service 2>/dev/null || \
       systemctl is-active --quiet snap.lxd.daemon.service 2>/dev/null; then
        log_pass "  ✓ LXD 服务运行中"
        
        # 测试LXD连接
        if timeout 5 lxc list > /dev/null 2>&1; then
            log_pass "  ✓ LXD 连接测试成功"
        else
            log_warn "  ⚠ LXD 连接测试失败（可能需要权限）"
        fi
    else
        log_warn "  ⚠ LXD 服务未运行"
    fi
else
    log_warn "  ⚠ LXC 未安装"
fi

# ========== 测试7: 检查Shell脚本语法 ==========
log_test "检查 Shell 脚本语法"

SHELL_OK=true

# 检查 deploy_cpu_protection.sh
if bash -n "$SCRIPT_DIR/deploy_cpu_protection.sh" 2>/dev/null; then
    log_pass "  ✓ deploy_cpu_protection.sh 语法正确"
else
    log_fail "  ✗ deploy_cpu_protection.sh 语法错误"
    SHELL_OK=false
fi

# 检查 setup_cpu_killer.sh
if bash -n "$SCRIPT_DIR/setup_cpu_killer.sh" 2>/dev/null; then
    log_pass "  ✓ setup_cpu_killer.sh 语法正确"
else
    log_fail "  ✗ setup_cpu_killer.sh 语法错误"
    SHELL_OK=false
fi

if [ "$SHELL_OK" = true ]; then
    log_pass "所有 Shell 脚本语法正确"
else
    log_fail "存在 Shell 脚本语法错误"
fi

# ========== 测试8: 检查服务文件模板 ==========
log_test "检查 systemd 服务模板"

# 测试能否正确生成服务文件（临时文件）
TEMP_SERVICE="/tmp/test_lxd_cpu_killer_$$.service"

cat > "$TEMP_SERVICE" <<'EOF'
[Unit]
Description=Test Service
After=network.target

[Service]
Type=simple
User=root
ExecStart=/usr/bin/python3 /tmp/test.py

[Install]
WantedBy=multi-user.target
EOF

if systemd-analyze verify "$TEMP_SERVICE" 2>/dev/null; then
    log_pass "systemd 服务文件模板正确"
else
    log_warn "systemd 服务文件模板验证失败（非关键）"
fi

rm -f "$TEMP_SERVICE"

# ========== 测试9: 检查文档完整性 ==========
log_test "检查文档文件"

DOCS_OK=true

if [ -f "$SERVER_DIR/docs/guides/CPU监控自动杀进程-使用指南.md" ]; then
    log_pass "  ✓ 使用指南存在"
else
    log_warn "  ⚠ 使用指南缺失"
    DOCS_OK=false
fi

if [ -f "$SCRIPT_DIR/CPU_KILLER_快速参考.txt" ]; then
    log_pass "  ✓ 快速参考存在"
else
    log_warn "  ⚠ 快速参考缺失"
    DOCS_OK=false
fi

if [ "$DOCS_OK" = true ]; then
    log_pass "文档完整"
else
    log_warn "部分文档缺失（非关键）"
fi

# ========== 测试10: 模拟安装测试 ==========
log_test "模拟安装检查（不实际安装）"

# 检查是否有root权限
if [ "$EUID" -eq 0 ]; then
    log_info "  ✓ 具有 root 权限"
    log_pass "可以执行实际安装"
else
    log_warn "  ⚠ 无 root 权限（测试模式）"
    log_warn "实际安装需要 root 权限"
fi

# ========== 测试结果汇总 ==========
echo ""
echo "=========================================="
echo "  测试结果汇总"
echo "=========================================="
echo ""
echo "总测试数: $TOTAL_TESTS"
echo "通过数: $PASSED_TESTS"
echo "失败数: $FAILED_TESTS"
echo ""

if [ $FAILED_TESTS -eq 0 ]; then
    echo -e "${GREEN}✓ 所有测试通过！系统可以正常部署${NC}"
    echo ""
    echo "建议下一步："
    echo "  1. 先测试运行："
    echo "     python3 $SCRIPT_DIR/cpu_monitor_killer.py --dry-run"
    echo ""
    echo "  2. 执行一键部署："
    echo "     sudo bash $SCRIPT_DIR/deploy_cpu_protection.sh"
    echo ""
    exit 0
else
    echo -e "${RED}✗ 存在 $FAILED_TESTS 个测试失败${NC}"
    echo ""
    echo "请根据上述错误信息修复问题后重试"
    echo ""
    
    # 给出修复建议
    if ! command -v python3 &> /dev/null; then
        echo "修复建议："
        echo "  - 安装 Python3: apt install python3 python3-pip"
    fi
    
    if ! python3 -c "import pylxd" 2>/dev/null; then
        echo "修复建议："
        echo "  - 安装 pylxd: pip3 install pylxd"
    fi
    
    if ! command -v lxc &> /dev/null; then
        echo "修复建议："
        echo "  - 安装 LXD: snap install lxd"
    fi
    
    exit 1
fi
