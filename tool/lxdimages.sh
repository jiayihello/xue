#!/bin/bash

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; NC='\033[0m'

NAME="lxdimages"
INSTALL_DIR="/usr/local/bin"
FORCE=false
DELETE=false

# 获取脚本所在目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN_DIR="$SCRIPT_DIR/lxdimages-bin"

log() { echo -e "$1"; }
ok() { log "${GREEN}[OK]${NC} $1"; }
info() { log "${BLUE}[INFO]${NC} $1"; }
warn() { log "${YELLOW}[WARN]${NC} $1"; }
err() { log "${RED}[ERR]${NC} $1"; exit 1; }

[[ $EUID -ne 0 ]] && err "请使用 root 运行"

while [[ $# -gt 0 ]]; do
  case $1 in
    -f|--force) FORCE=true; shift;;
    -d|--delete) DELETE=true; shift;;
    -h|--help) 
      echo "用法: $0 [选项]"
      echo "选项:"
      echo "  -f, --force   强制重新安装"
      echo "  -d, --delete  删除已安装的程序"
      echo "  -h, --help    显示帮助信息"
      exit 0;;
    *) err "未知参数 $1";;
  esac
done

if [[ $DELETE == true ]]; then
  echo "警告: 此操作将删除已安装的 $NAME 程序！"
  read -p "确定要继续吗? (y/N): " CONFIRM
  if [[ $CONFIRM != "y" && $CONFIRM != "Y" ]]; then
    ok "取消删除操作"
    exit 0
  fi
  
  if [[ -f "$INSTALL_DIR/$NAME" ]]; then
    rm -f "$INSTALL_DIR/$NAME"
    ok "已删除 $NAME 程序"
  else
    warn "程序 $NAME 未安装，无需删除"
  fi
  exit 0
fi

info "开始安装 $NAME 程序（本地版本）"

info "检测系统架构..."
arch=$(uname -m)
case $arch in
  x86_64) 
    BIN="lxdimages-amd64"
    info "检测到架构: x86_64 (amd64)"
    ;;
  aarch64|arm64) 
    BIN="lxdimages-arm64"
    info "检测到架构: aarch64 (arm64)"
    ;;
  *) 
    err "不支持的架构: $arch，仅支持 amd64 和 arm64"
    ;;
esac

if [[ -f "$INSTALL_DIR/$NAME" ]] && [[ $FORCE != true ]]; then
  warn "$NAME 已安装，使用 -f 参数强制重新安装"
  exit 0
fi

# 检查本地二进制文件是否存在
LOCAL_BIN="$BIN_DIR/$BIN"
if [[ ! -f "$LOCAL_BIN" ]]; then
  err "本地二进制文件不存在: $LOCAL_BIN\n请确保 lxdimages-bin 目录中包含必要的文件"
fi

info "使用本地二进制文件: $LOCAL_BIN"
file_size=$(du -h "$LOCAL_BIN" 2>/dev/null | cut -f1 || echo "未知")
info "文件大小: $file_size"

info "安装程序到 $INSTALL_DIR/$NAME"
mkdir -p "$INSTALL_DIR"

# 从本地复制文件
if ! cp "$LOCAL_BIN" "$INSTALL_DIR/$NAME"; then
  err "复制文件失败"
fi

chmod +x "$INSTALL_DIR/$NAME"

if [[ ! -x "$INSTALL_DIR/$NAME" ]]; then
  err "安装失败: 程序不可执行"
fi

echo
ok "安装完成！"
echo "程序路径: $INSTALL_DIR/$NAME"
echo "系统架构: $arch"
echo "二进制文件: $BIN"
echo "源文件路径: $LOCAL_BIN"

if ! echo "$PATH" | grep -q "$INSTALL_DIR"; then
  warn "$INSTALL_DIR 不在 PATH 中，请手动添加或使用完整路径"
  echo "可以运行: export PATH=\"\$PATH:$INSTALL_DIR\""
fi

echo
info "程序信息:"
if "$INSTALL_DIR/$NAME" --version 2>/dev/null; then
  :
elif "$INSTALL_DIR/$NAME" -v 2>/dev/null; then
  :
elif "$INSTALL_DIR/$NAME" version 2>/dev/null; then
  :
else
  echo "程序已安装，可以使用 $NAME 命令运行"
fi

echo
ok "$NAME 安装完成！（使用本地文件）"
