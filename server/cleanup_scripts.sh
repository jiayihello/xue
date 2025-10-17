#!/bin/bash
#===============================================
# 整理 server 目录下的脚本
#===============================================

echo "╔════════════════════════════════════════════╗"
echo "║      整理 server 目录                      ║"
echo "╚════════════════════════════════════════════╝"
echo ""

cd /root/server

# 1. 删除临时修复脚本（问题已解决）
echo "[1/3] 删除临时修复脚本"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

TEMP_SCRIPTS=(
    "fix_indentation_error.sh"
    "quick_fix_syntax.sh"
    "force_fix_python.sh"
    "use_simple_enforcer.sh"
    "complete_fix.sh"
)

for script in "${TEMP_SCRIPTS[@]}"; do
    if [ -f "$script" ]; then
        rm -f "$script"
        echo "  ✓ 已删除: $script"
    else
        echo "  - 不存在: $script"
    fi
done

echo ""

# 2. 移动诊断和维护工具到 tools 目录
echo "[2/3] 移动诊断和维护工具到 tools/"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

TOOLS_SCRIPTS=(
    "diagnose_flow_limit.sh"
    "fix_flow_enforcer_service.sh"
    "fix_overlimit_containers.sh"
    "verify_flow_limit_status.sh"
    "manual_unblock.sh"
    "quick_block_overlimit.sh"
    "fix_storage_unavailable.sh"
    "force_fix_storage.sh"
    "rebuild_storage_pool.sh"
)

for script in "${TOOLS_SCRIPTS[@]}"; do
    if [ -f "$script" ]; then
        mv "$script" tools/
        echo "  ✓ 已移动: $script -> tools/"
    else
        echo "  - 不存在: $script"
    fi
done

echo ""

# 3. 移动文档到 tools 目录
echo "[3/3] 移动相关文档"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

DOCS=(
    "FLOW_LIMIT_FIX_GUIDE.md"
)

for doc in "${DOCS[@]}"; do
    if [ -f "$doc" ]; then
        mv "$doc" tools/
        echo "  ✓ 已移动: $doc -> tools/"
    else
        echo "  - 不存在: $doc"
    fi
done

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✓ 整理完成"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "整理结果:"
echo "  已删除: 5 个临时修复脚本"
echo "  已移动: 9 个诊断工具到 tools/"
echo "  已移动: 1 个文档到 tools/"
echo ""
echo "保留在 server/ 根目录:"
echo "  - cj/ (紧急恢复脚本)"
echo "  - 核心部署和管理脚本"
echo "  - 配置文件和数据库"
echo ""
echo "查看 tools/ 目录:"
echo "  ls -lh tools/*.sh"

