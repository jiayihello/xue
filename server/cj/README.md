# LXD 容器恢复工具包

本工具包用于在 Btrfs 存储池损坏时，保留容器配置（包括密码、端口映射、资源限制等）并重建存储池。

---

## 📋 使用步骤

### 步骤 1：检查密码是否可以恢复

```bash
cd /root/server/cj
chmod +x *.sh
bash 1_check_passwords.sh
```

**作用**：检查容器密码是否存储在 LXD 配置中。

**预期结果**：
- ✅ 如果显示密码信息，说明可以完整恢复
- ⚠️ 如果未找到密码，恢复后需要手动设置

---

### 步骤 2：备份所有容器配置

```bash
bash 2_backup_configs.sh
```

**作用**：
- 备份容器配置（CPU、内存、磁盘等）
- 备份端口映射
- 备份密码信息
- 备份自定义用户属性
- 生成自动恢复脚本

**备份位置**：`/root/lxd-container-configs-日期时间/`

**重要文件**：
- `PASSWORD_SUMMARY.txt` - 所有容器的密码摘要
- `CONTAINER_SUMMARY.txt` - 所有容器的完整配置
- `restore_containers.sh` - 自动恢复脚本

**查看备份**：
```bash
# 查找最新备份
BACKUP_DIR=$(ls -td /root/lxd-container-configs-* | head -1)

# 查看密码摘要
cat $BACKUP_DIR/PASSWORD_SUMMARY.txt

# 查看完整配置
cat $BACKUP_DIR/CONTAINER_SUMMARY.txt
```

---

### 步骤 3：重建存储池

```bash
bash 3_rebuild_storage.sh
```

**作用**：
1. 清理磁盘空间（清除 APT 缓存、日志、临时文件等）
2. 删除损坏的存储池文件
3. 创建新的干净存储池

**警告**：
- ⚠️ 此操作会删除损坏的存储文件
- ⚠️ 容器数据会丢失（但配置已备份）
- ✅ 容器配置（密码、端口等）可以完整恢复

---

### 步骤 4：恢复容器配置

```bash
# 进入最新的备份目录
cd $(ls -td /root/lxd-container-configs-* | head -1)

# 运行恢复脚本
bash restore_containers.sh
```

**作用**：
- 重新创建所有容器
- 恢复资源限制（CPU、内存、磁盘）
- 恢复端口映射
- 恢复密码（如果有）
- 恢复自定义用户属性

**恢复后**：
```bash
# 启动所有容器
lxc start --all

# 查看容器状态
lxc list

# 对于未找到密码的容器，手动设置：
lxc exec <容器名> -- passwd root
```

---

## 🔍 文件说明

| 文件 | 说明 |
|------|------|
| `1_check_passwords.sh` | 检查密码是否可恢复 |
| `2_backup_configs.sh` | 备份所有容器配置 |
| `3_rebuild_storage.sh` | 清理和重建存储池 |
| `README.md` | 本说明文件 |

---

## 📊 恢复内容清单

### ✅ 可以恢复的内容

- ✅ CPU 限制（如 `limits.cpu.allowance: 10%`）
- ✅ 内存限制（如 `limits.memory: 128MB`）
- ✅ 磁盘大小（如 `2048MB`）
- ✅ 端口映射（所有 NAT 端口转发规则）
- ✅ 密码（如果存储在配置中）
- ✅ 自定义用户属性（如 `user.flow_limit_gb`）
- ✅ 网络限制（如 `limits.ingress`、`limits.egress`）

### ❌ 无法恢复的内容

- ❌ 容器内的文件和数据（文件系统已损坏）
- ❌ 容器内手动安装的软件
- ❌ 容器内的 `/etc/shadow`（如果密码没有存储在 LXD 配置中）

---

## 🆘 常见问题

### Q1: 磁盘空间不足怎么办？

步骤 3 的脚本会自动清理磁盘空间。如果仍然不足：

```bash
# 手动删除更多不需要的文件
du -sh /var/* | sort -h | tail -10

# 删除损坏的存储文件（释放 14G）
rm /var/snap/lxd/common/lxd/disks/disk.img.broken*
```

### Q2: 密码未找到怎么办？

如果步骤 1 显示未找到密码，容器恢复后需要手动设置：

```bash
# 启动容器
lxc start <容器名>

# 设置密码
lxc exec <容器名> -- passwd root
```

### Q3: 恢复后容器无法启动？

检查存储池状态：

```bash
lxc storage list
lxc storage show disk
```

如果存储池状态正常，检查容器配置：

```bash
lxc config show <容器名>
```

### Q4: 如何修改默认镜像？

编辑备份目录中的 `restore_containers.sh`，修改：

```bash
DEFAULT_IMAGE="debian12"  # 改为你的默认镜像别名
```

### Q5: 可以选择性恢复部分容器吗？

可以。编辑备份目录中的 `containers.list`，只保留需要恢复的容器名。

---

## 📝 脚本执行日志

所有脚本都会在执行过程中显示详细的进度信息。

建议保存执行日志：

```bash
bash 1_check_passwords.sh 2>&1 | tee check.log
bash 2_backup_configs.sh 2>&1 | tee backup.log
bash 3_rebuild_storage.sh 2>&1 | tee rebuild.log
```

---

## ⚠️ 重要提醒

1. **备份前请确认**：步骤 2 会生成配置备份，但不会备份容器内的文件数据。
2. **磁盘空间**：确保至少有 5GB 可用空间。
3. **执行顺序**：必须按照 1 → 2 → 3 → 4 的顺序执行。
4. **密码安全**：备份文件包含明文密码，请妥善保管。

---

## 📞 支持

如果遇到问题：

1. 查看脚本执行时的错误信息
2. 检查 `/root/lxd-container-configs-*/` 中的备份文件
3. 查看 LXD 日志：`journalctl -u snap.lxd.daemon -n 100`

---

**最后更新**: 2025-10-16

