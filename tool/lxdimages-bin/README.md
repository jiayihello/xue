# lxdimages 完整离线版本

## 📦 内容说明

此目录包含 `lxdimages` 工具的**完整源代码和二进制文件**，实现100%离线可用。

---

## 📂 文件结构

```
lxdimages-bin/
├── lxdimages-amd64       # x86_64 架构二进制文件 (8.88 MB)
├── lxdimages-arm64       # ARM64 架构二进制文件 (8.33 MB)
├── main.go               # Go 源代码主文件 (15.9 KB)
├── go.mod                # Go 模块配置
├── build.sh              # 构建脚本
├── cleanup.sh            # 清理脚本
├── tools/
│   └── ssh.go            # SSH 工具模块源代码 (7.4 KB)
└── README.md             # 本文件
```

---

## 🎯 文件说明

### 二进制文件（已编译）

| 文件 | 大小 | 架构 | 用途 |
|------|------|------|------|
| `lxdimages-amd64` | 8.88 MB | x86_64 | 直接使用的可执行文件 |
| `lxdimages-arm64` | 8.33 MB | aarch64 | ARM 服务器使用 |

### 源代码文件

| 文件 | 大小 | 说明 |
|------|------|------|
| `main.go` | 15.9 KB | 主程序源代码 |
| `tools/ssh.go` | 7.4 KB | SSH 工具模块 |
| `go.mod` | 28 B | Go 模块依赖 |

### 脚本文件

| 文件 | 大小 | 用途 |
|------|------|------|
| `build.sh` | 281 B | 编译源代码生成二进制文件 |
| `cleanup.sh` | 725 B | 清理编译产物 |

---

## 🚀 使用方法

### 1. 直接使用二进制文件（推荐）

```bash
cd LinuxTools-main
sudo bash lxdimages.sh
```

脚本会自动：
- ✅ 检测系统架构
- ✅ 选择对应的二进制文件
- ✅ 复制到 `/usr/local/bin/lxdimages`
- ✅ 设置可执行权限

### 2. 从源代码构建

如果你想自己编译：

```bash
cd LinuxTools-main/lxdimages-bin

# 构建当前架构的二进制文件
bash build.sh

# 或手动构建
go build -o lxdimages-amd64 main.go
```

---

## 🔒 安全性

### 文件来源

所有文件从官方仓库下载：
```
https://github.com/xkatld/zjmf-lxd-server/tree/main/lxdimages
```

### 下载时间

- **二进制文件**: 2025-10-12
- **源代码**: 2025-10-12

### 文件完整性

| 文件 | 大小 (字节) | 类型 |
|------|------------|------|
| lxdimages-amd64 | 8,881,766 | ELF 64-bit LSB executable |
| lxdimages-arm64 | 8,329,358 | ELF 64-bit LSB executable |
| main.go | 15,912 | Go source code |
| tools/ssh.go | 7,417 | Go source code |

---

## 🔄 重新编译

### 前提条件

需要安装 Go 编译器：
```bash
# Ubuntu/Debian
sudo apt install golang-go

# 或从官网下载
# https://golang.org/dl/
```

### 编译 amd64 版本

```bash
cd LinuxTools-main/lxdimages-bin

# 方法 1：使用构建脚本
bash build.sh

# 方法 2：手动编译
GOOS=linux GOARCH=amd64 go build -o lxdimages-amd64 main.go
```

### 编译 arm64 版本

```bash
cd LinuxTools-main/lxdimages-bin

# 跨平台编译 ARM64 版本
GOOS=linux GOARCH=arm64 go build -o lxdimages-arm64 main.go
```

### 编译所有架构

```bash
cd LinuxTools-main/lxdimages-bin

# 编译 amd64
GOOS=linux GOARCH=amd64 go build -o lxdimages-amd64 main.go

# 编译 arm64
GOOS=linux GOARCH=arm64 go build -o lxdimages-arm64 main.go

echo "编译完成！"
ls -lh lxdimages-*
```

---

## 📝 源代码说明

### main.go

主程序文件，包含：
- 命令行参数解析
- 镜像构建逻辑
- LXD API 交互
- 发行版配置

### tools/ssh.go

SSH 工具模块，负责：
- SSH 服务器安装
- SSH 配置优化
- 防火墙规则
- 服务启动管理

### go.mod

Go 模块配置，定义：
- 模块名称
- Go 版本要求
- 依赖包列表

---

## 🎯 优势

### 完全离线可用 ✨

- ✅ **二进制文件** - 直接使用，无需编译
- ✅ **源代码** - 可以自己编译和审计
- ✅ **构建脚本** - 一键重新构建
- ✅ **独立部署** - 不依赖外部资源

### 安全可控

- ✅ 可以审计源代码
- ✅ 可以自己编译
- ✅ 不担心供应链攻击
- ✅ 版本完全可控

### 灵活性

- ✅ 可以修改源代码
- ✅ 可以添加新功能
- ✅ 可以自定义工具集
- ✅ 可以针对特定需求优化

---

## 🔍 验证文件

### 检查二进制文件

```bash
cd LinuxTools-main/lxdimages-bin

# 查看文件类型
file lxdimages-amd64
file lxdimages-arm64

# 应该输出：
# lxdimages-amd64: ELF 64-bit LSB executable, x86-64, ...
# lxdimages-arm64: ELF 64-bit LSB executable, ARM aarch64, ...

# 查看文件大小
ls -lh lxdimages-*
```

### 检查源代码

```bash
cd LinuxTools-main/lxdimages-bin

# 查看 Go 代码
head -20 main.go

# 检查语法
go fmt main.go tools/ssh.go

# 检查依赖
go mod verify
```

---

## 🛠️ 自定义和修改

### 添加新的工具集

编辑 `tools/ssh.go` 或创建新的工具模块：

```go
// tools/docker.go
package tools

func InstallDocker() error {
    // 实现 Docker 安装逻辑
    return nil
}
```

然后在 `main.go` 中引用新工具。

### 支持新的发行版

编辑 `main.go`，添加新的发行版配置：

```go
distributions := map[string][]string{
    // ... 现有配置
    "archlinux": {"latest"},
    "gentoo": {"latest"},
}
```

### 修改构建选项

编辑 `build.sh`：

```bash
# 添加优化选项
go build -ldflags="-s -w" -o lxdimages-amd64 main.go

# -s: 去除符号表
# -w: 去除调试信息
# 可以减小文件大小
```

---

## 📊 文件大小对比

| 版本 | amd64 | arm64 | 总计 |
|------|-------|-------|------|
| **标准构建** | 8.88 MB | 8.33 MB | 17.21 MB |
| **优化构建 (-ldflags="-s -w")** | ~6.5 MB | ~6.1 MB | ~12.6 MB |
| **源代码** | 15.9 KB | 7.4 KB | 23.3 KB |

---

## 🔗 相关链接

- **项目主页**: https://github.com/xkatld/zjmf-lxd-server
- **Wiki 文档**: https://github.com/xkatld/zjmf-lxd-server/wiki
- **Go 官网**: https://golang.org/

---

## 💡 最佳实践

### 生产环境

1. ✅ 使用已编译的二进制文件（速度快）
2. ✅ 定期更新源代码和重新编译
3. ✅ 保留源代码备份（便于审计）
4. ✅ 使用版本控制管理修改

### 开发环境

1. ✅ 从源代码编译（便于调试）
2. ✅ 修改代码后测试
3. ✅ 使用 `go fmt` 格式化代码
4. ✅ 使用 `go vet` 检查代码

### 安全考虑

1. ✅ 验证源代码无恶意内容
2. ✅ 自己编译而不是使用预编译版本
3. ✅ 定期检查官方更新
4. ✅ 使用签名验证（如果可用）

---

## 🎉 总结

此目录包含：
- ✅ **完整的二进制文件** - 即装即用
- ✅ **完整的源代码** - 可审计可修改
- ✅ **构建工具** - 一键重新编译
- ✅ **100% 离线** - 不依赖网络

真正的**完全自主可控**的镜像构建工具！🚀

