#!/bin/bash

# 部署后验证和修复脚本
# 在每次部署流量管理系统后运行此脚本，确保所有组件正常工作

set -e

echo "============================================================"
echo "  流量管理系统部署后验证与修复"
echo "============================================================"

# 获取脚本所在目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# 颜色定义
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

ISSUES_FOUND=0
AUTO_FIX=false

# 检查是否自动修复
if [ "$1" == "--auto-fix" ] || [ "$1" == "-f" ]; then
    AUTO_FIX=true
    echo "自动修复模式已启用"
fi

echo ""
echo "### 第一步：系统检查 ###"
echo ""

# ==================================================
# 1. 检查数据库
# ==================================================
echo "1. 检查数据库..."
if [ -f "flow_management.db" ]; then
    CONTAINER_COUNT=$(sqlite3 flow_management.db "SELECT COUNT(*) FROM container_flow_management;" 2>/dev/null || echo "0")
    echo -e "   ${GREEN}✅${NC} 数据库正常，已注册 $CONTAINER_COUNT 个容器"
else
    echo -e "   ${RED}❌${NC} 数据库文件不存在"
    ISSUES_FOUND=$((ISSUES_FOUND + 1))
    
    if [ "$AUTO_FIX" = true ]; then
        echo "      尝试初始化数据库..."
        python3 upgrade_flow_database.py && echo -e "      ${GREEN}✅${NC} 数据库已初始化" || echo -e "      ${RED}❌${NC} 数据库初始化失败"
    fi
fi

# ==================================================
# 2. 检查守护进程
# ==================================================
echo "2. 检查守护进程..."
if systemctl is-active --quiet lxd-flow-continuity.service 2>/dev/null; then
    echo -e "   ${GREEN}✅${NC} 守护进程正在运行"
elif systemctl list-unit-files | grep -q lxd-flow-continuity.service; then
    echo -e "   ${YELLOW}⚠️${NC}  守护进程已安装但未运行"
    ISSUES_FOUND=$((ISSUES_FOUND + 1))
    
    if [ "$AUTO_FIX" = true ]; then
        echo "      尝试启动守护进程..."
        systemctl restart lxd-flow-continuity.service && echo -e "      ${GREEN}✅${NC} 守护进程已启动" || echo -e "      ${RED}❌${NC} 守护进程启动失败"
    fi
else
    echo -e "   ${RED}❌${NC} 守护进程未安装"
    ISSUES_FOUND=$((ISSUES_FOUND + 1))
    
    if [ "$AUTO_FIX" = true ]; then
        echo "      尝试创建守护进程服务..."
        python3 flow_continuity_daemon.py --create-service && systemctl daemon-reload && systemctl start lxd-flow-continuity.service && echo -e "      ${GREEN}✅${NC} 守护进程已创建并启动" || echo -e "      ${RED}❌${NC} 守护进程创建失败"
    fi
fi

# ==================================================
# 3. 检查定时任务
# ==================================================
echo "3. 检查定时任务..."
CURRENT_CRONTAB=$(crontab -l 2>/dev/null || echo "")
RESET_COUNT=$(echo "$CURRENT_CRONTAB" | grep -c "flow_reset_scheduler.py reset" || echo "0")
CLEANUP_COUNT=$(echo "$CURRENT_CRONTAB" | grep -c "flow_reset_scheduler.py cleanup" || echo "0")

echo "   流量重置任务: $RESET_COUNT 条（期望 ≥1）"
echo "   清理任务: $CLEANUP_COUNT 条（期望 ≥1）"

if [ "$RESET_COUNT" -ge 1 ] && [ "$CLEANUP_COUNT" -ge 1 ]; then
    echo -e "   ${GREEN}✅${NC} 定时任务已配置"
else
    echo -e "   ${RED}❌${NC} 定时任务配置不完整"
    ISSUES_FOUND=$((ISSUES_FOUND + 1))
    
    if [ "$AUTO_FIX" = true ]; then
        echo "      修复定时任务..."
        
        # 移除旧的任务
        TEMP_CRONTAB=$(echo "$CURRENT_CRONTAB" | grep -v "flow_reset_scheduler.py" || echo "")
        
        # 添加新任务
        RESET_JOB="0 2 * * * /usr/bin/python3 $SCRIPT_DIR/flow_reset_scheduler.py reset >/dev/null 2>&1"
        CLEANUP_JOB="0 3 * * 0 /usr/bin/python3 $SCRIPT_DIR/flow_reset_scheduler.py cleanup >/dev/null 2>&1"
        
        NEW_CRONTAB="$TEMP_CRONTAB
$RESET_JOB
$CLEANUP_JOB"
        
        echo "$NEW_CRONTAB" | crontab - && echo -e "      ${GREEN}✅${NC} 定时任务已修复" || echo -e "      ${RED}❌${NC} 定时任务修复失败"
    fi
fi

# ==================================================
# 4. 检查管理命令
# ==================================================
echo "4. 检查管理命令..."
if [ -x "/usr/local/bin/lxd-flow-manager" ]; then
    echo -e "   ${GREEN}✅${NC} 管理命令已安装"
else
    echo -e "   ${RED}❌${NC} 管理命令未安装或无执行权限"
    ISSUES_FOUND=$((ISSUES_FOUND + 1))
    
    if [ "$AUTO_FIX" = true ]; then
        echo "      安装管理命令..."
        if [ -f "$SCRIPT_DIR/setup_flow_management.sh" ]; then
            # 提取创建管理命令的部分并执行
            chmod +x /usr/local/bin/lxd-flow-manager 2>/dev/null && echo -e "      ${GREEN}✅${NC} 管理命令权限已修复" || echo -e "      ${YELLOW}⚠️${NC}  需要重新运行 setup_flow_management.sh"
        fi
    fi
fi

# ==================================================
# 5. 检查 API 服务
# ==================================================
echo "5. 检查 API 服务..."
if systemctl is-active --quiet lxd-api.service 2>/dev/null; then
    echo -e "   ${GREEN}✅${NC} API 服务正在运行"
elif systemctl list-unit-files | grep -q lxd-api.service; then
    echo -e "   ${YELLOW}⚠️${NC}  API 服务已安装但未运行"
    ISSUES_FOUND=$((ISSUES_FOUND + 1))
    
    if [ "$AUTO_FIX" = true ]; then
        echo "      尝试启动 API 服务..."
        systemctl restart lxd-api.service && echo -e "      ${GREEN}✅${NC} API 服务已启动" || echo -e "      ${RED}❌${NC} API 服务启动失败"
    fi
else
    echo -e "   ${YELLOW}⚠️${NC}  API 服务未安装（可能需要手动部署）"
fi

# ==================================================
# 6. 检查容器注册情况
# ==================================================
echo "6. 检查容器注册情况..."
if [ -f "flow_management.db" ]; then
    LXD_CONTAINER_COUNT=$(lxc list --format csv 2>/dev/null | wc -l)
    DB_CONTAINER_COUNT=$(sqlite3 flow_management.db "SELECT COUNT(*) FROM container_flow_management;" 2>/dev/null || echo "0")
    
    echo "   LXD 容器数: $LXD_CONTAINER_COUNT"
    echo "   数据库记录数: $DB_CONTAINER_COUNT"
    
    if [ "$LXD_CONTAINER_COUNT" -eq "$DB_CONTAINER_COUNT" ]; then
        echo -e "   ${GREEN}✅${NC} 容器数量匹配"
    else
        echo -e "   ${YELLOW}⚠️${NC}  容器数量不匹配"
        ISSUES_FOUND=$((ISSUES_FOUND + 1))
        
        if [ "$AUTO_FIX" = true ]; then
            echo "      同步容器注册..."
            python3 flow_reset_scheduler.py register && python3 flow_reset_scheduler.py cleanup && echo -e "      ${GREEN}✅${NC} 容器注册已同步" || echo -e "      ${RED}❌${NC} 同步失败"
        fi
    fi
fi

# ==================================================
# 7. 检查诊断脚本
# ==================================================
echo "7. 检查诊断脚本..."
if [ -f "diagnose_flow_management.py" ]; then
    echo -e "   ${GREEN}✅${NC} 诊断脚本已存在"
else
    echo -e "   ${YELLOW}⚠️${NC}  诊断脚本不存在（建议添加）"
fi

# ==================================================
# 总结
# ==================================================
echo ""
echo "============================================================"
if [ $ISSUES_FOUND -eq 0 ]; then
    echo -e "  ${GREEN}✅ 所有检查通过！系统运行正常${NC}"
    echo "============================================================"
    echo ""
    echo "快速验证命令："
    echo "  python3 list_flow_usage.py              # 查看所有容器流量"
    echo "  crontab -l | grep flow                  # 查看定时任务"
    echo "  systemctl status lxd-flow-continuity    # 查看守护进程状态"
else
    echo -e "  ${YELLOW}发现 $ISSUES_FOUND 个问题${NC}"
    echo "============================================================"
    
    if [ "$AUTO_FIX" = false ]; then
        echo ""
        echo "建议运行以下命令之一修复问题："
        echo ""
        echo "1. 自动修复（推荐）："
        echo "   bash post_deploy_check.sh --auto-fix"
        echo ""
        echo "2. 使用诊断脚本："
        echo "   python3 diagnose_flow_management.py"
        echo ""
        echo "3. 重新运行部署脚本："
        echo "   sudo bash deploy_production_flow.sh"
    else
        echo ""
        echo "自动修复已完成，请检查上述错误信息"
        echo "如果仍有问题，建议运行："
        echo "   python3 diagnose_flow_management.py"
    fi
fi

echo ""
echo "详细文档："
echo "  cat FLOW_TROUBLESHOOTING.md    # 故障排查指南"
echo ""

exit 0

