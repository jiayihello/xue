#!/bin/bash
#===============================================
# 数据库清理脚本
# 用于清理历史容器记录
#===============================================

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

DB_FILE="flow_management.db"

echo -e "${CYAN}=========================================="
echo -e "  数据库清理工具"
echo -e "==========================================${NC}"
echo ""

# 检查数据库是否存在
if [ ! -f "$DB_FILE" ]; then
    echo -e "${RED}[错误]${NC} 数据库文件不存在: $DB_FILE"
    exit 1
fi

# 显示当前数据库状态
echo -e "${CYAN}[信息]${NC} 当前数据库状态:"
echo ""

# 容器记录数
CONTAINER_COUNT=$(sqlite3 "$DB_FILE" "SELECT COUNT(*) FROM container_flow_management;" 2>/dev/null || echo "0")
echo "  容器记录数: $CONTAINER_COUNT"

# 显示容器列表
if [ "$CONTAINER_COUNT" -gt 0 ]; then
    echo ""
    echo -e "${CYAN}数据库中的容器记录:${NC}"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    sqlite3 "$DB_FILE" "SELECT container_name, created_at, used_bandwidth_bytes FROM container_flow_management;" 2>/dev/null | while IFS='|' read -r name created used; do
        echo "  容器: $name"
        echo "    创建时间: $created"
        echo "    已用流量: $(numfmt --to=iec-i --suffix=B $used 2>/dev/null || echo "$used bytes")"
        echo ""
    done
fi

# 检查当前运行的容器
echo -e "${CYAN}[信息]${NC} 当前 LXD 容器:"
LXD_CONTAINERS=$(lxc list -c n --format csv 2>/dev/null)
LXD_COUNT=$(echo "$LXD_CONTAINERS" | grep -v '^$' | wc -l)

if [ "$LXD_COUNT" -gt 0 ]; then
    echo "$LXD_CONTAINERS" | while read -r container; do
        echo "  - $container"
    done
else
    echo "  （无运行中的容器）"
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# 询问操作
echo -e "${YELLOW}选择操作:${NC}"
echo "  1) 清空所有容器记录（保留表结构）"
echo "  2) 删除不存在的容器记录（清理历史数据）"
echo "  3) 重建整个数据库"
echo "  4) 取消"
echo ""

read -p "请选择 [1-4]: " choice

case "$choice" in
    1)
        echo ""
        echo -e "${YELLOW}[警告]${NC} 这将删除所有容器记录！"
        read -p "确认操作? [y/N]: " confirm
        
        if [[ "${confirm,,}" == "y" ]]; then
            echo -e "${CYAN}[处理]${NC} 清空容器记录..."
            sqlite3 "$DB_FILE" "DELETE FROM container_flow_management;"
            
            if [ $? -eq 0 ]; then
                echo -e "${GREEN}[完成]${NC} 已清空所有容器记录"
                NEW_COUNT=$(sqlite3 "$DB_FILE" "SELECT COUNT(*) FROM container_flow_management;" 2>/dev/null || echo "0")
                echo "  剩余记录数: $NEW_COUNT"
            else
                echo -e "${RED}[错误]${NC} 清空失败"
                exit 1
            fi
        else
            echo -e "${YELLOW}[取消]${NC} 操作已取消"
        fi
        ;;
    
    2)
        echo ""
        echo -e "${CYAN}[处理]${NC} 清理不存在的容器记录..."
        
        # 获取数据库中的容器名
        DB_CONTAINERS=$(sqlite3 "$DB_FILE" "SELECT container_name FROM container_flow_management;" 2>/dev/null)
        
        DELETED_COUNT=0
        
        for container in $DB_CONTAINERS; do
            # 检查容器是否存在于 LXD
            if ! lxc info "$container" >/dev/null 2>&1; then
                echo "  删除记录: $container (容器不存在)"
                sqlite3 "$DB_FILE" "DELETE FROM container_flow_management WHERE container_name='$container';"
                DELETED_COUNT=$((DELETED_COUNT + 1))
            else
                echo "  保留记录: $container (容器存在)"
            fi
        done
        
        echo ""
        echo -e "${GREEN}[完成]${NC} 已清理 $DELETED_COUNT 条记录"
        NEW_COUNT=$(sqlite3 "$DB_FILE" "SELECT COUNT(*) FROM container_flow_management;" 2>/dev/null || echo "0")
        echo "  剩余记录数: $NEW_COUNT"
        ;;
    
    3)
        echo ""
        echo -e "${YELLOW}[警告]${NC} 这将删除并重建整个数据库！"
        read -p "确认操作? [y/N]: " confirm
        
        if [[ "${confirm,,}" == "y" ]]; then
            echo -e "${CYAN}[处理]${NC} 备份原数据库..."
            BACKUP_FILE="${DB_FILE}.backup.$(date +%Y%m%d_%H%M%S)"
            cp "$DB_FILE" "$BACKUP_FILE"
            echo "  备份文件: $BACKUP_FILE"
            
            echo -e "${CYAN}[处理]${NC} 删除原数据库..."
            rm "$DB_FILE"
            
            echo -e "${CYAN}[处理]${NC} 重建数据库..."
            python3 -c "from flow_manager import FlowManager; fm = FlowManager(); print('✅ 数据库重建完成')"
            
            if [ -f "$DB_FILE" ]; then
                echo -e "${GREEN}[完成]${NC} 数据库已重建"
                echo "  新数据库: $DB_FILE"
                echo "  备份文件: $BACKUP_FILE"
            else
                echo -e "${RED}[错误]${NC} 数据库重建失败"
                echo "  恢复备份: cp $BACKUP_FILE $DB_FILE"
                exit 1
            fi
        else
            echo -e "${YELLOW}[取消]${NC} 操作已取消"
        fi
        ;;
    
    4|*)
        echo -e "${YELLOW}[取消]${NC} 操作已取消"
        exit 0
        ;;
esac

echo ""
echo -e "${GREEN}=========================================="
echo -e "  操作完成"
echo -e "==========================================${NC}"
echo ""

# 显示最终状态
FINAL_COUNT=$(sqlite3 "$DB_FILE" "SELECT COUNT(*) FROM container_flow_management;" 2>/dev/null || echo "0")
echo "最终记录数: $FINAL_COUNT"
echo ""


