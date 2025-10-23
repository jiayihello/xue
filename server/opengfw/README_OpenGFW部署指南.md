# OpenGFW 部署指南 - LXD 服务器专用版

## 📖 目录

- [简介](#简介)
- [功能特性](#功能特性)
- [系统要求](#系统要求)
- [快速部署](#快速部署)
- [规则配置](#规则配置)
- [使用管理](#使用管理)
- [性能优化](#性能优化)
- [故障排查](#故障排查)
- [常见问题](#常见问题)

---

## 📝 简介

OpenGFW 是一个开源的深度包检测（DPI）工具，可以在网络层分析和拦截特定协议的流量。

**适用场景：**
- 🔒 防止 LXD 容器客户滥用代理协议（Shadowsocks、Trojan 等）
- 🚫 阻止容器内运行 VPN 服务（WireGuard、OpenVPN）
- 📊 拦截 BT/PT 下载，保护服务器带宽
- 🌍 基于地域限制特定流量（仅拦截中国大陆等）

**工作原理：**
- 部署在宿主机，分析所有经过的数据包
- 使用 iptables NFQUEUE 机制捕获流量
- 实时识别并拦截高危协议
- 不影响正常业务流量

---

## ✨ 功能特性

### ✅ 支持协议检测

| 协议类型 | 协议名称 | 拦截能力 |
|---------|---------|---------|
| 代理协议 | Shadowsocks, VMess, Trojan, Socks | ✅ 完全支持 |
| VPN 协议 | WireGuard, OpenVPN | ✅ 完全支持 |
| 下载协议 | BitTorrent | ✅ 完全支持 |
| 隧道协议 | SSH Tunnel | ⚠️ 可选启用 |
| 其他协议 | DNS over HTTPS (DoH) | ⚠️ 可选启用 |

### ✅ 高级功能

- **地域限制**: 仅拦截来自特定国家/地区的连接（基于 GeoIP）
- **域名过滤**: 拦截访问特定域名的流量（基于 SNI/Host）
- **白名单机制**: 允许信任 IP 或域名绕过拦截
- **实时日志**: 记录所有拦截事件，便于审计
- **统计分析**: 按协议类型统计拦截次数

---

## 💻 系统要求

### 硬件要求
- **CPU**: 2 核心及以上（推荐 4 核心）
- **内存**: 至少 512MB 可用内存（推荐 1GB+）
- **网络**: 支持 iptables 的 Linux 内核

### 软件要求
- **操作系统**: Debian 10+, Ubuntu 18.04+, CentOS 7+
- **内核版本**: Linux Kernel 3.10+
- **依赖工具**: iptables, systemd

### 兼容性
- ✅ LXD 宿主机（推荐部署位置）
- ✅ KVM 宿主机
- ✅ 物理服务器
- ❌ LXC 容器内部（权限不足）
- ❌ Docker 容器内部（网络隔离）

---

## 🚀 快速部署

### 方法一：一键自动部署（推荐）

```bash
# 1. 进入部署目录
cd /root/lxd-toolkit/server/opengfw

# 2. 赋予执行权限
chmod +x deploy_opengfw.sh

# 3. 运行部署脚本
bash deploy_opengfw.sh
```

**部署过程说明：**
1. ✅ 自动检测系统架构（amd64/arm64）
2. ✅ 检查并安装依赖（wget, iptables 等）
3. ✅ 备份现有 iptables 规则
4. ✅ 下载 OpenGFW 最新版本
5. ✅ 下载 GeoIP/GeoSite 数据库
6. ✅ 交互式配置拦截规则
7. ✅ 创建 systemd 服务
8. ✅ 自动启动并验证

**交互式选项：**
```
请选择要拦截的协议（多选，空格分隔，例如: 1 2 3）：
  1) Shadowsocks / VMess（代理协议）
  2) Trojan（代理协议）
  3) Socks（代理协议）
  4) WireGuard（VPN 协议）
  5) BitTorrent（BT 下载）
  6) 全部启用

请选择 [1-6]: 6

是否只拦截来自中国大陆的代理连接? [y/N]: y
```

---

### 方法二：手动部署

<details>
<summary>点击展开手动部署步骤</summary>

```bash
# 1. 创建安装目录
mkdir -p /etc/opengfw
cd /etc/opengfw

# 2. 下载 OpenGFW（以 amd64 为例）
wget https://github.com/apernet/OpenGFW/releases/download/v0.4.1/OpenGFW-linux-amd64
mv OpenGFW-linux-amd64 OpenGFW
chmod +x OpenGFW

# 3. 下载 GeoIP 数据库（可选）
wget https://github.com/Loyalsoldier/v2ray-rules-dat/releases/latest/download/geoip.dat
wget https://github.com/Loyalsoldier/v2ray-rules-dat/releases/latest/download/geosite.dat

# 4. 复制配置文件（从预设模板）
cp /root/lxd-toolkit/server/opengfw/预设规则-完全版.yaml rules.yaml

# 5. 创建 config.yaml（参考下方配置示例）

# 6. 创建 systemd 服务
nano /etc/systemd/system/opengfw.service

# 7. 启动服务
systemctl daemon-reload
systemctl enable opengfw.service
systemctl start opengfw.service
```

</details>

---

## ⚙️ 规则配置

### 预设规则文件

本项目提供了 3 套预设规则，您可以根据需求选择：

#### 1️⃣ 轻量版（推荐新手）
- **文件**: `预设规则-轻量版.yaml`
- **拦截协议**: Shadowsocks, Trojan, Socks
- **性能影响**: 低
- **适用场景**: 基础防护，性能优先

```bash
# 使用轻量版规则
cp /etc/opengfw/预设规则-轻量版.yaml /etc/opengfw/rules.yaml
systemctl restart opengfw
```

#### 2️⃣ 完全版（推荐生产环境）
- **文件**: `预设规则-完全版.yaml`
- **拦截协议**: 所有代理/VPN/下载协议 + 域名过滤
- **性能影响**: 中等
- **适用场景**: 全面防护，商业环境

```bash
# 使用完全版规则
cp /etc/opengfw/预设规则-完全版.yaml /etc/opengfw/rules.yaml
systemctl restart opengfw
```

#### 3️⃣ 地域限制版（推荐国际业务）
- **文件**: `预设规则-地域限制版.yaml`
- **拦截协议**: 仅拦截来自中国大陆的代理连接
- **性能影响**: 低
- **适用场景**: 有海外客户，只限制国内滥用

```bash
# 使用地域限制版规则
cp /etc/opengfw/预设规则-地域限制版.yaml /etc/opengfw/rules.yaml
systemctl restart opengfw
```

---

### 自定义规则示例

#### 示例 1：拦截特定域名

```yaml
# 拦截访问 example.com 的所有流量
- name: block example domain
  action: block
  log: true
  expr: string(tls?.req?.sni) == "example.com" || string(http?.req?.headers?.host) == "example.com"
```

#### 示例 2：允许特定 IP 绕过拦截

```yaml
# 白名单：允许 192.168.1.100 的所有流量
- name: allow trusted ip
  action: allow
  expr: string(ip.src) == "192.168.1.100"
```

#### 示例 3：只拦截来自特定国家的代理

```yaml
# 只拦截来自中国和俄罗斯的 Shadowsocks
- name: block shadowsocks from china and russia
  action: block
  log: true
  expr: fet != nil && fet.yes && (geoip(string(ip.src), "cn") || geoip(string(ip.src), "ru"))
```

#### 示例 4：拦截特定端口范围

```yaml
# 拦截目标端口在 8000-9000 范围内的流量
- name: block port range
  action: block
  log: true
  expr: tcp != nil && tcp.dport >= 8000 && tcp.dport <= 9000
```

---

## 🎛️ 使用管理

### 管理控制台

运行管理脚本，进入交互式控制台：

```bash
cd /etc/opengfw
bash manage_opengfw.sh
```

**控制台功能：**
- ✅ 查看服务状态
- ✅ 实时监控拦截日志
- ✅ 统计分析（按协议分类）
- ✅ 一键切换规则文件
- ✅ 在线编辑规则
- ✅ 服务启停管理
- ✅ 更新 GeoIP 数据库
- ✅ 性能监控
- ✅ 一键卸载

---

### 常用命令

#### 服务管理

```bash
# 查看服务状态
systemctl status opengfw

# 启动服务
systemctl start opengfw

# 停止服务
systemctl stop opengfw

# 重启服务
systemctl restart opengfw

# 启用开机自启
systemctl enable opengfw

# 禁用开机自启
systemctl disable opengfw
```

#### 日志查看

```bash
# 查看实时日志
journalctl -u opengfw -f

# 仅查看拦截日志
journalctl -u opengfw -f | grep "block"

# 查看最近 100 条日志
journalctl -u opengfw -n 100

# 查看今天的日志
journalctl -u opengfw --since today

# 导出日志到文件
journalctl -u opengfw --since "2025-01-01" > opengfw_logs.txt
```

#### 规则管理

```bash
# 编辑规则文件
nano /etc/opengfw/rules.yaml

# 验证规则语法（测试运行 5 秒）
timeout 5s /etc/opengfw/OpenGFW -c /etc/opengfw/config.yaml /etc/opengfw/rules.yaml

# 应用修改后的规则
systemctl restart opengfw
```

#### 统计分析

```bash
# 统计拦截次数（最近 1000 条日志）
journalctl -u opengfw -n 1000 | grep -c "block"

# 按协议分类统计
journalctl -u opengfw -n 1000 | grep "block" | awk '{
  if ($0 ~ /shadowsocks|vmess/) ss++
  else if ($0 ~ /trojan/) trojan++
  else if ($0 ~ /socks/) socks++
} END {
  print "Shadowsocks/VMess:", ss
  print "Trojan:", trojan
  print "Socks:", socks
}'
```

---

## ⚡ 性能优化

### 1. 调整工作线程数

根据 CPU 核心数调整（编辑 `/etc/opengfw/config.yaml`）：

```yaml
workers:
  count: 8  # 设置为 CPU 核心数
```

### 2. 增大缓冲区（高流量场景）

```yaml
io:
  queueSize: 4096       # 默认 2048
  rcvBuf: 16777216      # 16MB（默认 8MB）
  sndBuf: 16777216      # 16MB（默认 8MB）
```

### 3. 减少日志记录（降低磁盘 I/O）

编辑 `rules.yaml`，将 `log: true` 改为 `log: false`：

```yaml
- name: block shadowsocks
  action: block
  log: false  # 不记录日志
  expr: fet != nil && fet.yes
```

### 4. 优化 TCP 超时时间

```yaml
workers:
  tcpTimeout: 3m  # 默认 5m，减少内存占用
```

### 5. 使用轻量版规则

如果不需要拦截所有协议，使用轻量版规则可显著降低 CPU 负载：

```bash
cp /etc/opengfw/预设规则-轻量版.yaml /etc/opengfw/rules.yaml
systemctl restart opengfw
```

---

## 🔧 故障排查

### 问题 1：服务无法启动

**症状：**
```
systemctl status opengfw
● opengfw.service - OpenGFW Service
   Active: failed (Result: exit-code)
```

**排查步骤：**
```bash
# 1. 查看详细日志
journalctl -u opengfw -n 50 --no-pager

# 2. 检查配置文件语法
/etc/opengfw/OpenGFW -c /etc/opengfw/config.yaml /etc/opengfw/rules.yaml

# 3. 检查端口占用
netstat -tulnp | grep NFQUEUE

# 4. 检查权限
ls -l /etc/opengfw/OpenGFW
chmod +x /etc/opengfw/OpenGFW
```

---

### 问题 2：拦截不生效

**症状：** 容器仍然可以使用代理协议

**排查步骤：**
```bash
# 1. 确认服务运行中
systemctl status opengfw

# 2. 检查 iptables 规则
iptables -L -n | grep NFQUEUE

# 3. 查看实时日志，确认是否捕获流量
journalctl -u opengfw -f

# 4. 测试规则是否匹配
# 在容器中尝试使用代理，观察日志中是否有 "block" 记录

# 5. 检查规则文件
cat /etc/opengfw/rules.yaml
```

---

### 问题 3：性能问题（CPU 占用高）

**症状：** OpenGFW 进程 CPU 占用超过 50%

**解决方案：**
```bash
# 1. 检查当前配置
cat /etc/opengfw/config.yaml

# 2. 减少工作线程（如果核心数少）
nano /etc/opengfw/config.yaml
# workers.count: 4  # 改为 CPU 核心数的一半

# 3. 使用轻量版规则
cp /etc/opengfw/预设规则-轻量版.yaml /etc/opengfw/rules.yaml

# 4. 关闭日志记录
# 在 rules.yaml 中设置 log: false

# 5. 重启服务
systemctl restart opengfw
```

---

### 问题 4：与 LXD NAT 规则冲突

**症状：** 容器网络不通，或部署后容器无法访问外网

**解决方案：**
```bash
# 1. 检查 iptables 规则顺序
iptables -L -n -v --line-numbers

# 2. 确保 OpenGFW 规则在 NAT 规则之后
# 如果冲突，手动调整规则顺序或修改 config.yaml 中的 table 参数

# 3. 恢复备份的 iptables 规则
ls /root/iptables_backup_*.rules
iptables-restore < /root/iptables_backup_XXXXXX.rules

# 4. 重新部署 OpenGFW，选择不同的 queueNum
# 编辑 config.yaml
io:
  queueNum: 200  # 默认 100，改为其他值
```

---

## ❓ 常见问题

### Q1: OpenGFW 会影响容器正常业务吗？

**A:** 不会。OpenGFW 只拦截规则文件中指定的协议（如 Shadowsocks、Trojan），对正常的 HTTP/HTTPS、SSH、数据库连接等业务流量**完全无影响**。

---

### Q2: 可以只拦截特定容器的流量吗？

**A:** 可以。通过 IP 地址过滤实现：

```yaml
# 只拦截 IP 为 10.0.0.100 的容器
- name: block specific container
  action: block
  log: true
  expr: string(ip.src) == "10.0.0.100" && (fet != nil && fet.yes)
```

---

### Q3: 部署后如何验证是否生效？

**A:** 
1. 查看服务状态：`systemctl status opengfw`
2. 在容器中测试使用代理协议（如 Shadowsocks 客户端）
3. 观察日志：`journalctl -u opengfw -f | grep "block"`
4. 如果看到 "block shadowsocks" 日志，说明拦截成功

---

### Q4: GeoIP 数据库多久更新一次？

**A:** 建议每月更新一次：

```bash
# 手动更新
cd /etc/opengfw
wget -O geoip.dat https://github.com/Loyalsoldier/v2ray-rules-dat/releases/latest/download/geoip.dat
systemctl restart opengfw

# 或使用管理脚本
bash manage_opengfw.sh
# 选择 "7) 更新 GeoIP 数据库"
```

也可以配置 cron 自动更新：
```bash
# 每月 1 号凌晨 3 点更新
0 3 1 * * cd /etc/opengfw && wget -O geoip.dat https://github.com/Loyalsoldier/v2ray-rules-dat/releases/latest/download/geoip.dat && systemctl restart opengfw
```

---

### Q5: 误拦截了正常流量怎么办？

**A:** 使用白名单机制：

```yaml
# 方法 1：允许特定 IP
- name: allow trusted ip
  action: allow
  expr: string(ip.src) == "192.168.1.100"

# 方法 2：允许特定域名
- name: allow trusted domain
  action: allow
  expr: string(tls?.req?.sni) == "trusted.example.com"

# 注意：白名单规则需要放在拦截规则之前！
```

---

### Q6: 如何卸载 OpenGFW？

**A:** 
```bash
# 方法 1：使用管理脚本
bash /etc/opengfw/manage_opengfw.sh
# 选择 "9) 卸载 OpenGFW"

# 方法 2：手动卸载
systemctl stop opengfw
systemctl disable opengfw
rm -f /etc/systemd/system/opengfw.service
systemctl daemon-reload
rm -rf /etc/opengfw

# 恢复 iptables 备份（可选）
iptables-restore < /root/iptables_backup_XXXXXX.rules
```

---

### Q7: 支持 IPv6 流量拦截吗？

**A:** 支持。OpenGFW 默认同时处理 IPv4 和 IPv6 流量。规则中使用 `ip.src` 和 `ip.dst` 会自动适配 IPv6。

对于 IPv6 地址过滤：
```yaml
- name: block ipv6 address
  action: block
  expr: string(ip.src) == "2001:db8::1"
```

---

### Q8: 对服务器性能有多大影响？

**A:** 取决于流量大小和规则复杂度：

| 场景 | CPU 占用 | 内存占用 | 延迟增加 |
|------|---------|---------|---------|
| 轻量版规则 + 低流量 | < 5% | ~50MB | < 1ms |
| 完全版规则 + 中等流量 | 10-20% | ~100MB | 1-3ms |
| 完全版规则 + 高流量 | 20-40% | ~200MB | 3-5ms |

**优化建议：**
- 只启用必要的拦截规则
- 根据 CPU 核心数调整 workers.count
- 高流量场景使用轻量版规则

---

## 📚 参考资料

- **OpenGFW 官方仓库**: https://github.com/apernet/OpenGFW
- **规则表达式语法**: https://github.com/apernet/OpenGFW/wiki/Expressions
- **协议检测原理**: https://github.com/apernet/OpenGFW/wiki/Analyzers
- **GeoIP 数据库**: https://github.com/Loyalsoldier/v2ray-rules-dat

---

## 📧 技术支持

如遇到问题，请提供以下信息：

```bash
# 收集诊断信息
echo "=== 系统信息 ===" > opengfw_debug.txt
uname -a >> opengfw_debug.txt
echo "" >> opengfw_debug.txt

echo "=== 服务状态 ===" >> opengfw_debug.txt
systemctl status opengfw >> opengfw_debug.txt
echo "" >> opengfw_debug.txt

echo "=== 最近日志 ===" >> opengfw_debug.txt
journalctl -u opengfw -n 100 --no-pager >> opengfw_debug.txt
echo "" >> opengfw_debug.txt

echo "=== 配置文件 ===" >> opengfw_debug.txt
cat /etc/opengfw/config.yaml >> opengfw_debug.txt
echo "" >> opengfw_debug.txt
cat /etc/opengfw/rules.yaml >> opengfw_debug.txt

echo "诊断信息已保存到 opengfw_debug.txt"
```

---

**部署愉快！🎉**

