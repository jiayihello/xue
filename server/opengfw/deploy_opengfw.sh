#!/bin/bash
#================================================================
# OpenGFW 自动部署脚本 - 适配 LXD 服务器
# 用途：在宿主机上部署 OpenGFW，拦截容器高危协议流量
#================================================================

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 配置变量
INSTALL_DIR="/etc/opengfw"
OPENGFW_VERSION="v0.4.1"  # 最新稳定版本
ARCH=$(uname -m)

# 检测系统架构
detect_architecture() {
    case "${ARCH}" in
        x86_64)
            DOWNLOAD_ARCH="amd64"
            ;;
        aarch64)
            DOWNLOAD_ARCH="arm64"
            ;;
        armv7l)
            DOWNLOAD_ARCH="armv7"
            ;;
        *)
            echo -e "${RED}[错误] 不支持的架构: ${ARCH}${NC}"
            exit 1
            ;;
    esac
}

# 打印带颜色的消息
print_info() {
    echo -e "${BLUE}[信息]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[成功]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[警告]${NC} $1"
}

print_error() {
    echo -e "${RED}[错误]${NC} $1"
}

# 检查是否为 root 用户
check_root() {
    if [[ $EUID -ne 0 ]]; then
        print_error "此脚本必须以 root 权限运行"
        exit 1
    fi
}

# 检查系统依赖
check_dependencies() {
    print_info "检查系统依赖..."
    
    local missing_deps=()
    
    for cmd in wget curl iptables systemctl; do
        if ! command -v $cmd &> /dev/null; then
            missing_deps+=($cmd)
        fi
    done
    
    if [ ${#missing_deps[@]} -ne 0 ]; then
        print_warning "缺少以下依赖: ${missing_deps[*]}"
        print_info "正在安装依赖..."
        
        if command -v apt-get &> /dev/null; then
            apt-get update
            apt-get install -y ${missing_deps[*]}
        elif command -v yum &> /dev/null; then
            yum install -y ${missing_deps[*]}
        else
            print_error "无法自动安装依赖，请手动安装: ${missing_deps[*]}"
            exit 1
        fi
    fi
    
    print_success "依赖检查完成"
}

# 检查 iptables 规则冲突
check_iptables_compatibility() {
    print_info "检查 iptables 规则兼容性..."
    
    # 检查是否已存在 NFQUEUE 规则
    if iptables -L -n | grep -q "NFQUEUE"; then
        print_warning "检测到已存在的 NFQUEUE 规则，可能与 OpenGFW 冲突"
        read -p "是否继续安装? [y/N]: " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            print_info "安装已取消"
            exit 0
        fi
    fi
    
    # 备份当前 iptables 规则
    print_info "备份当前 iptables 规则..."
    iptables-save > /root/iptables_backup_$(date +%Y%m%d_%H%M%S).rules
    print_success "iptables 规则已备份到 /root/"
}

# 创建安装目录
create_install_directory() {
    print_info "创建安装目录: ${INSTALL_DIR}"
    mkdir -p "${INSTALL_DIR}"
    cd "${INSTALL_DIR}"
    print_success "目录创建完成"
}

# 下载 OpenGFW
download_opengfw() {
    print_info "下载 OpenGFW ${OPENGFW_VERSION} (${DOWNLOAD_ARCH})..."
    
    local download_url="https://github.com/apernet/OpenGFW/releases/download/${OPENGFW_VERSION}/OpenGFW-linux-${DOWNLOAD_ARCH}"
    
    # 尝试使用 wget 或 curl 下载
    if command -v wget &> /dev/null; then
        wget -O OpenGFW "${download_url}" || {
            print_error "下载失败，请检查网络连接或手动下载"
            print_info "下载地址: ${download_url}"
            exit 1
        }
    elif command -v curl &> /dev/null; then
        curl -L -o OpenGFW "${download_url}" || {
            print_error "下载失败，请检查网络连接或手动下载"
            print_info "下载地址: ${download_url}"
            exit 1
        }
    fi
    
    chmod +x OpenGFW
    print_success "OpenGFW 下载完成"
}

# 下载 GeoIP/GeoSite 数据库
download_geo_databases() {
    print_info "下载 GeoIP 和 GeoSite 数据库..."
    
    local geoip_url="https://github.com/Loyalsoldier/v2ray-rules-dat/releases/latest/download/geoip.dat"
    local geosite_url="https://github.com/Loyalsoldier/v2ray-rules-dat/releases/latest/download/geosite.dat"
    
    if command -v wget &> /dev/null; then
        wget -O geoip.dat "${geoip_url}" 2>/dev/null || print_warning "GeoIP 下载失败（可选）"
        wget -O geosite.dat "${geosite_url}" 2>/dev/null || print_warning "GeoSite 下载失败（可选）"
    elif command -v curl &> /dev/null; then
        curl -L -o geoip.dat "${geoip_url}" 2>/dev/null || print_warning "GeoIP 下载失败（可选）"
        curl -L -o geosite.dat "${geosite_url}" 2>/dev/null || print_warning "GeoSite 下载失败（可选）"
    fi
    
    print_success "地理数据库下载完成"
}

# 生成配置文件
generate_config() {
    print_info "生成配置文件 config.yaml..."
    
    cat > "${INSTALL_DIR}/config.yaml" << 'EOF'
# OpenGFW 配置文件 - LXD 服务器优化版
# 用途：拦截容器高危协议流量

io:
  queueSize: 2048           # 队列大小（增大以处理更多容器流量）
  queueNum: 100             # NFQUEUE 队列编号
  table: opengfw            # iptables 表名
  connMarkAccept: 1001      # 接受连接的标记
  connMarkDrop: 1002        # 丢弃连接的标记
  rcvBuf: 8388608           # 8MB 接收缓冲区（优化高流量）
  sndBuf: 8388608           # 8MB 发送缓冲区
  local: false              # 不拦截本地流量
  rst: false                # 静默丢弃（不发送 RST 包）

workers:
  count: 8                  # 工作线程数（根据 CPU 核心数调整）
  queueSize: 128            # 每个工作线程的队列大小
  tcpMaxBufferedPagesTotal: 65536
  tcpMaxBufferedPagesPerConn: 16
  tcpTimeout: 5m            # TCP 超时时间
  udpMaxStreams: 8192       # UDP 最大流数量

# 地理数据库路径（自动下载）
ruleset:
  geoip: geoip.dat
  geosite: geosite.dat

# 重放模式（生产环境关闭）
replay:
  realtime: false
EOF
    
    print_success "config.yaml 生成完成"
}

# 生成规则文件（交互式）
generate_rules_interactive() {
    print_info "配置拦截规则..."
    echo ""
    echo "请选择要拦截的协议（多选，空格分隔，例如: 1 2 3）："
    echo "  1) Shadowsocks / VMess（代理协议）"
    echo "  2) Trojan（代理协议）"
    echo "  3) Socks（代理协议）"
    echo "  4) WireGuard（VPN 协议）"
    echo "  5) BitTorrent（BT 下载）"
    echo "  6) 全部启用"
    echo ""
    read -p "请选择 [1-6]: " -a choices
    
    # 开始生成规则文件
    cat > "${INSTALL_DIR}/rules.yaml" << 'EOF'
# OpenGFW 规则文件 - LXD 容器场景
# 拦截高危协议，防止滥用

EOF
    
    local enable_all=false
    for choice in "${choices[@]}"; do
        if [[ "$choice" == "6" ]]; then
            enable_all=true
            break
        fi
    done
    
    # Shadowsocks / VMess
    if [[ " ${choices[@]} " =~ " 1 " ]] || $enable_all; then
        cat >> "${INSTALL_DIR}/rules.yaml" << 'EOF'
# 1. 拦截 Shadowsocks 和 VMess 代理
- name: block shadowsocks and vmess
  action: block
  log: true
  expr: fet != nil && fet.yes

EOF
    fi
    
    # Trojan
    if [[ " ${choices[@]} " =~ " 2 " ]] || $enable_all; then
        cat >> "${INSTALL_DIR}/rules.yaml" << 'EOF'
# 2. 拦截 Trojan 代理
- name: block trojan
  action: block
  log: true
  expr: trojan != nil && trojan.yes

EOF
    fi
    
    # Socks
    if [[ " ${choices[@]} " =~ " 3 " ]] || $enable_all; then
        cat >> "${INSTALL_DIR}/rules.yaml" << 'EOF'
# 3. 拦截 Socks 代理
- name: block socks
  action: block
  log: true
  expr: socks != nil && socks.yes

EOF
    fi
    
    # WireGuard
    if [[ " ${choices[@]} " =~ " 4 " ]] || $enable_all; then
        cat >> "${INSTALL_DIR}/rules.yaml" << 'EOF'
# 4. 拦截 WireGuard VPN
- name: block wireguard
  action: block
  log: true
  expr: wireguard != nil && wireguard.yes

EOF
    fi
    
    # BitTorrent
    if [[ " ${choices[@]} " =~ " 5 " ]] || $enable_all; then
        cat >> "${INSTALL_DIR}/rules.yaml" << 'EOF'
# 5. 拦截 BitTorrent 下载
- name: block bittorrent
  action: block
  log: true
  expr: bt != nil && bt.yes

EOF
    fi
    
    # 添加地域限制选项
    echo ""
    read -p "是否只拦截来自中国大陆的代理连接? [y/N]: " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        # 修改规则，添加地域限制
        if [[ " ${choices[@]} " =~ " 1 " ]] || $enable_all; then
            sed -i 's/expr: fet != nil && fet.yes/expr: fet != nil \&\& fet.yes \&\& geoip(string(ip.src), "cn")/g' "${INSTALL_DIR}/rules.yaml"
        fi
        print_info "已添加地域限制：仅拦截来自中国大陆的连接"
    fi
    
    print_success "rules.yaml 生成完成"
}

# 创建 systemd 服务
create_systemd_service() {
    print_info "创建 systemd 服务..."
    
    cat > /etc/systemd/system/opengfw.service << EOF
[Unit]
Description=OpenGFW - Deep Packet Inspection Service
Documentation=https://github.com/apernet/OpenGFW
After=network.target
Wants=network.target

[Service]
Type=simple
User=root
WorkingDirectory=${INSTALL_DIR}
ExecStart=${INSTALL_DIR}/OpenGFW -c config.yaml rules.yaml
Restart=on-failure
RestartSec=10
LimitNOFILE=1048576
LimitNPROC=512

# 安全设置
NoNewPrivileges=false
PrivateTmp=true

[Install]
WantedBy=multi-user.target
EOF
    
    systemctl daemon-reload
    print_success "systemd 服务创建完成"
}

# 测试配置
test_configuration() {
    print_info "测试 OpenGFW 配置..."
    
    # 前台运行 5 秒测试
    timeout 5s "${INSTALL_DIR}/OpenGFW" -c config.yaml rules.yaml &> /tmp/opengfw_test.log || true
    
    if grep -q "error\|Error\|ERROR" /tmp/opengfw_test.log; then
        print_error "配置测试失败，请检查日志："
        cat /tmp/opengfw_test.log
        exit 1
    fi
    
    print_success "配置测试通过"
}

# 启动服务
start_service() {
    print_info "启用并启动 OpenGFW 服务..."
    
    systemctl enable opengfw.service
    systemctl start opengfw.service
    
    sleep 2
    
    if systemctl is-active --quiet opengfw.service; then
        print_success "OpenGFW 服务已成功启动"
    else
        print_error "OpenGFW 服务启动失败，请检查日志:"
        journalctl -u opengfw.service -n 20 --no-pager
        exit 1
    fi
}

# 显示部署信息
show_deployment_info() {
    echo ""
    echo -e "${GREEN}╔════════════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}║       OpenGFW 部署完成！                       ║${NC}"
    echo -e "${GREEN}╚════════════════════════════════════════════════╝${NC}"
    echo ""
    echo -e "${BLUE}安装信息:${NC}"
    echo "  安装目录: ${INSTALL_DIR}"
    echo "  配置文件: ${INSTALL_DIR}/config.yaml"
    echo "  规则文件: ${INSTALL_DIR}/rules.yaml"
    echo "  服务名称: opengfw.service"
    echo ""
    echo -e "${BLUE}常用命令:${NC}"
    echo "  查看服务状态: systemctl status opengfw"
    echo "  查看实时日志: journalctl -u opengfw -f"
    echo "  重启服务:     systemctl restart opengfw"
    echo "  停止服务:     systemctl stop opengfw"
    echo "  编辑规则:     nano ${INSTALL_DIR}/rules.yaml"
    echo ""
    echo -e "${BLUE}日志监控:${NC}"
    echo "  实时查看拦截日志："
    echo "  journalctl -u opengfw -f | grep 'block'"
    echo ""
    echo -e "${YELLOW}注意事项:${NC}"
    echo "  1. OpenGFW 会分析所有经过宿主机的流量"
    echo "  2. 修改规则后需重启服务: systemctl restart opengfw"
    echo "  3. 如需卸载，运行: bash ${INSTALL_DIR}/uninstall.sh"
    echo "  4. iptables 规则已备份到 /root/ 目录"
    echo ""
}

# 创建卸载脚本
create_uninstall_script() {
    cat > "${INSTALL_DIR}/uninstall.sh" << 'EOF'
#!/bin/bash
# OpenGFW 卸载脚本

echo "正在停止 OpenGFW 服务..."
systemctl stop opengfw.service
systemctl disable opengfw.service

echo "正在删除 systemd 服务..."
rm -f /etc/systemd/system/opengfw.service
systemctl daemon-reload

echo "正在删除安装目录..."
read -p "是否删除 /etc/opengfw 目录? [y/N]: " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    rm -rf /etc/opengfw
    echo "✓ 卸载完成"
else
    echo "保留配置文件在 /etc/opengfw"
fi

echo ""
echo "提示：iptables 备份文件仍保留在 /root/ 目录"
EOF
    chmod +x "${INSTALL_DIR}/uninstall.sh"
}

# 主函数
main() {
    clear
    echo -e "${BLUE}"
    cat << "EOF"
╔════════════════════════════════════════════════╗
║     OpenGFW 自动部署脚本 - LXD 服务器版        ║
║     拦截容器高危协议，保护服务器安全           ║
╚════════════════════════════════════════════════╝
EOF
    echo -e "${NC}"
    
    check_root
    detect_architecture
    check_dependencies
    check_iptables_compatibility
    create_install_directory
    download_opengfw
    download_geo_databases
    generate_config
    generate_rules_interactive
    create_systemd_service
    create_uninstall_script
    test_configuration
    start_service
    show_deployment_info
    
    print_success "所有步骤已完成！"
}

# 运行主函数
main

