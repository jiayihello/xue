#!/bin/bash
#===============================================
# 独立的部署检查命令
# 可随时运行以检查系统状态
#===============================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# 检查是否在 server 目录
if [ ! -f "$SCRIPT_DIR/post_deployment_check.sh" ]; then
    echo "错误: 找不到检查脚本"
    echo "请确保在 server 目录下运行此脚本"
    exit 1
fi

# 运行检查
bash "$SCRIPT_DIR/post_deployment_check.sh" "$@"

