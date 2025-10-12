# LXD 容器管理工具箱

一个功能完整的 LXD 容器管理工具集，包含 LXD 安装、镜像构建、虚拟内存管理、服务器部署等功能。

---

## 🚀 快速开始

```bash
# 运行工具箱
sudo bash linuxtools.sh
```

---

## 📋 功能列表

### 🔧 LXD 环境

- **1) 安装或检查 LXD 环境**
  - 自动安装最新版 LXD（via Snap）
  - 自动安装系统依赖
  - 自动配置 Python 环境
  - 支持 Debian 和 Ubuntu

- **2) 创建 BTRFS 存储池**
  - 从文件创建 BTRFS 存储池
  - 用于容器数据存储

---

### 📦 镜像管理

- **3) 安装 lxdimages 镜像构建工具**
  - 本地安装（无需外部下载）
  - 支持 amd64 和 arm64 架构
  - 安装后自动进入镜像构建

- **4) 构建自定义镜像**
  - 快速选项：Debian 12、Debian 13、Alpine 3.22
  - 完整列表：支持多种发行版和版本
  - 支持多选构建
  - 自动导入到 LXD
  - 自动清理临时文件

- **5) 备份所有本地 LXD 镜像**
  - 批量备份镜像

- **6) 列出本地 LXD 镜像**
  - 显示已导入的镜像列表

---

### 💾 虚拟内存管理

- **7) 安装并配置 ZRAM**
  - 内存压缩（推荐）
  - 提高内存利用率
  - 比 Swap 文件更快

- **8) 移除 ZRAM**
  - 卸载 ZRAM 服务

- **9) 添加 Swap 文件**
  - 基于硬盘的虚拟内存
  - 适合内存不足的场景

- **10) 移除 Swap 文件**
  - 清理 Swap 配置

---

### 🖥️ 服务器部署（新增！）

- **11) 部署 LXD 服务器后端（一键部署）**
  - ✅ 自动安装 Python 依赖
  - ✅ 配置网络（IPv4 + IPv6）
  - ✅ 部署流量管理系统
  - ✅ 配置滥用防护
  - ✅ 启动后端 API 服务
  - ⏱️ 预计时间：5-10 分钟

---

## 🎯 推荐使用流程

### 全新服务器部署

```
1. 安装 LXD 环境          (选项 1)
   ↓
2. 安装 lxdimages 工具    (选项 3)
   ↓
3. 构建自定义镜像         (选项 4)
   ↓
4. 部署服务器后端         (选项 11)
   ↓
5. 配置 ZRAM (可选)       (选项 7)
```

---

## 💡 功能特点

### 1. LXD 预安装配置

安装 LXD 时会自动执行：

- **安装系统依赖**：
  ```bash
  curl wget git iptables iptables-persistent 
  python3 python3-pip sqlite3 cron
  ```

- **智能配置 Python**：
  - Debian 12 → 删除 `/usr/lib/python3.11/EXTERNALLY-MANAGED`
  - Debian 13 → 删除 `/usr/lib/python3.13/EXTERNALLY-MANAGED`
  - Ubuntu/其他 → 自动检测并配置

---

### 2. 镜像构建工具

#### 支持的镜像

**快速选项**：
- Debian 12 (bookworm) → `debian12`
- Debian 13 (trixie) → `debian13`
- Alpine 3.22 → `alpine322`

**完整列表**：
- Ubuntu: jammy, noble, plucky
- Debian: bullseye, bookworm, trixie
- CentOS: 9-Stream, 10-Stream
- Fedora: 40, 41, 42
- AlmaLinux: 8, 9, 10
- Rocky Linux: 8, 9, 10
- Oracle Linux: 7, 8, 9
- openSUSE: 15.5, 15.6, tumbleweed
- Alpine: 3.19, 3.20, 3.21, 3.22, edge
- Amazon Linux: 2, 2023

#### 使用方式

```bash
# 方式一：从菜单选择
选择: 3 → 安装工具
选择: 4 → 构建镜像

# 方式二：命令行
lxdimages debian bookworm -add ssh -name debian12
lxdimages alpine 3.22 -add ssh -name alpine322
```

---

### 3. 服务器后端部署

一键完成以下步骤：

1. **安装依赖** - `pip3 install -r requirements.txt`
2. **配置网络** - IPv4 + IPv6（ROUTED/NAT66/off）
3. **流量管理** - 自动监控和限制
4. **滥用防护** - 防挖矿、BT、扫描
5. **后端服务** - API 服务 + Web 界面

#### 部署后功能

- 📊 **流量管理**
  - 实时监控容器流量
  - 自动限制超限容器
  - 定期重置流量

- 🚫 **滥用防护**
  - 防挖矿（阻止矿池连接）
  - 防 BT（阻止 P2P 流量）
  - 防扫描（阻止端口扫描）

- 🔌 **API 服务**
  - RESTful API
  - 容器管理接口
  - 流量查询接口
  - CPU 限制管理

---

## 📁 项目结构

```
项目根目录/
  ├── LinuxTools-main/
  │   ├── linuxtools.sh           # 主脚本
  │   ├── lxdimages.sh            # lxdimages 安装器
  │   ├── lxdimages-bin/          # 本地二进制文件
  │   │   ├── lxdimages-amd64
  │   │   └── lxdimages-arm64
  │   └── shell/                  # 原始子脚本（仅供参考）
  │       ├── lxd-helper.sh
  │       └── virtual-memory-manager.sh
  └── server/                     # 服务器后端
      ├── deploy_all.sh           # 一键部署脚本
      ├── app.py                  # API 服务
      ├── lxc_manager.py          # 容器管理
      ├── flow_manager.py         # 流量管理
      └── ...
```

---

## 🧪 使用示例

### 示例 1：安装 LXD 并构建镜像

```bash
$ sudo bash linuxtools.sh

选择: 1  # 安装 LXD
# → 自动安装依赖、配置 Python、安装 LXD

选择: 3  # 安装 lxdimages 工具
# → 安装成功后自动进入选项 4

# 在镜像构建菜单中
选择: 1,2,3  # 选择 Debian 12、Debian 13、Alpine 3.22
# → 自动构建并导入镜像
```

---

### 示例 2：部署完整服务器

```bash
$ sudo bash linuxtools.sh

选择: 1   # 安装 LXD
选择: 3   # 安装镜像工具并构建镜像
选择: 11  # 部署服务器后端

# 在部署过程中输入：
IPv4 地址: 192.168.1.100
IPv6 模式: 3 (off)
流量管理: Y
滥用防护: Y
后端服务: Y

# 5-10 分钟后部署完成！
```

---

## 🔧 系统要求

- **操作系统**: Ubuntu 20.04/22.04 或 Debian 11/12/13
- **权限**: Root 权限
- **架构**: amd64 或 arm64
- **网络**: 需要互联网连接（安装依赖时）

---

## 📚 文档

| 文档 | 说明 |
|------|------|
| `✅集成部署功能完成.md` | 部署功能说明 |
| `✅预安装配置完成.md` | LXD 预安装配置 |
| `✅菜单更新完成.md` | 镜像构建功能 |
| `../教程.txt` | 完整教程（根目录） |
| `../server/README.md` | Server 后端文档 |

---

## 🎨 菜单预览

```
=========================================
    LXD 容器管理工具箱 (整合版)        
=========================================

--- LXD 环境 ---
  1) 安装或检查 LXD 环境
  2) 创建 BTRFS 存储池（从文件）

--- 镜像管理 ---
  3) 安装 lxdimages 镜像构建工具
  4) 构建自定义镜像
  5) 备份所有本地 LXD 镜像
  6) 列出本地 LXD 镜像

--- 虚拟内存管理 ---
  7) 安装并配置 ZRAM (内存压缩, 推荐)
  8) 移除 ZRAM
  9) 添加 Swap 文件 (基于硬盘)
 10) 移除 Swap 文件

--- 服务器部署 ---
 11) 部署 LXD 服务器后端 (一键部署)

  ---------------------------------------
  0) 退出脚本
=========================================
```

---

## 🔍 常见问题

### Q: LXD 安装失败？

**A**: 检查以下几点：
1. 是否使用 root 权限
2. 网络连接是否正常
3. 是否为支持的系统版本

---

### Q: 镜像构建失败？

**A**: 常见原因：
1. 内存不足（需要至少 2GB）
2. 磁盘空间不足（需要至少 10GB）
3. 网络问题（下载镜像时）

---

### Q: 服务器部署失败？

**A**: 检查步骤：
1. 确保 LXD 已安装（选项 1）
2. 确保 server 目录存在
3. 查看详细错误日志
4. 运行诊断脚本：`python3 server/tools/diagnose_flow_management.py`

---

## 🛠️ 故障排查

### 查看服务状态

```bash
# API 服务
systemctl status lxd-api.service

# 流量守护进程
systemctl status lxd-flow-continuity.service

# 流量限制执行器
systemctl status lxd-flow-enforcer.service
```

### 查看日志

```bash
# API 服务日志
journalctl -u lxd-api.service -f

# 流量守护进程日志
journalctl -u lxd-flow-continuity.service -f
```

### 查看流量使用

```bash
python3 /root/server/list_flow_usage.py
```

---

## 💡 提示和技巧

### 1. 推荐使用 ZRAM

ZRAM 比 Swap 文件更快，推荐用于生产环境：

```bash
选择: 7  # 安装 ZRAM
大小: 物理内存的 50-100%
```

---

### 2. 构建多个镜像

可以一次性选择多个镜像构建：

```bash
选择: 1,2,3  # 构建 3 个镜像
或
选择: all    # 构建所有快速选项
```

---

### 3. 自定义镜像命名

修改 `lxdimages` 命令的 `-name` 参数：

```bash
lxdimages debian bookworm -add ssh -name my-debian12
```

---

## 🎉 开始使用

```bash
# 克隆或下载项目
cd /path/to/zjmf-lxd-server-main

# 运行 LinuxTools
sudo bash LinuxTools-main/linuxtools.sh

# 按照菜单提示操作
```

---

## 📞 获取帮助

1. 查看项目根目录的 `教程.txt`
2. 查看 `server/` 目录下的文档
3. 查看 `LinuxTools-main/` 目录下的完成文档

---

## ✅ 版本历史

### v3.0 - 服务器部署集成
- ✅ 新增服务器后端一键部署功能
- ✅ 集成到 LinuxTools 菜单

### v2.0 - 镜像构建功能
- ✅ 集成 lxdimages 工具
- ✅ 本地化二进制文件
- ✅ 支持多选镜像构建

### v1.0 - 基础功能
- ✅ LXD 安装和配置
- ✅ ZRAM 和 Swap 管理
- ✅ 菜单整合

---

**享受您的 LXD 容器管理之旅！** 🚀

