#!/bin/bash

# 检查root权限
if [ "$(id -u)" -ne 0 ]; then
   echo "错误：此脚本必须以root用户身份运行。"
   echo "请尝试使用 'sudo bash' 命令来执行。"
   exit 1
fi

# 安装必要依赖
echo "正在安装必要依赖..."
if command -v apt-get &> /dev/null; then
    apt-get update
    apt-get install -y iptables iptables-persistent python3 python3-pip
elif command -v yum &> /dev/null; then
    yum install -y iptables iptables-services python3 python3-pip
else
    echo "不支持的包管理器，请手动安装iptables和python3"
    exit 1
fi

# 确保脚本可执行
chmod +x network_setup.py

# 运行网络配置脚本
echo "正在配置网络规则..."
python3 network_setup.py

# 检查网络规则是否成功配置
if [ $? -ne 0 ]; then
    echo "网络规则配置失败，请检查日志。"
    exit 1
fi

echo "正在配置systemd服务..."
# 创建服务文件
cat > /etc/systemd/system/lxd-network-check.service << 'EOF'
[Unit]
Description=LXD Network Config Check
After=network.target lxd.service
Before=lxd-network-setup.service

[Service]
Type=oneshot
ExecStart=/bin/bash -c 'ip link show lxdbr0 >/dev/null 2>&1 || systemctl restart lxd.service'
TimeoutSec=0
StandardOutput=journal

[Install]
WantedBy=multi-user.target
EOF

# 重新加载systemd
systemctl daemon-reload
systemctl enable lxd-network-check.service
systemctl enable lxd-network-setup.service

echo "正在设置自动检查脚本..."
# 创建定时任务，每10分钟检查一次网络规则
(crontab -l 2>/dev/null; echo "*/10 * * * * /usr/bin/python3 $(pwd)/network_setup.py >/dev/null 2>&1") | crontab -

echo "===== 安装完成 ====="
echo "网络规则已配置并设置为系统启动时自动应用"
echo "容器网络配置已完成，系统重启后容器应能正常联网" 