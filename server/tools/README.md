# Tools 目录

此目录包含 **一次性使用** 的验证、测试、修复和诊断工具。这些工具不是系统运行必需的，仅在特定场景下使用。

## 📂 文件分类

### 🔍 诊断工具（重要）

**diagnose_flow_management.py** - 流量管理系统诊断和自动修复
- 检查：数据库、定时任务、守护进程、容器注册
- 功能：自动修复常见问题
- 使用：`python3 diagnose_flow_management.py`
- **推荐**：系统出问题时第一个运行此工具

**post_deploy_check.sh** - 部署后完整性检查
- 检查：所有组件是否正确安装和运行
- 功能：验证部署是否成功
- 使用：`bash post_deploy_check.sh`
- **推荐**：每次部署后运行

### 🧪 测试脚本

开发和调试时使用，生产环境不需要：

- `test_container_connectivity.py` - 测试容器网络连接性
- `test_flow_continuity.py` - 测试流量连续性
- `test_flow_monitoring.py` - 测试流量监控功能
- `test_network_block.sh` - 测试网络阻断功能
- `test_port_forward.py` - 测试端口转发

### ✅ 验证脚本

用于验证系统配置和功能：

- `verify_flow_accuracy.py` - 验证流量统计准确性
- `verify_nat66.sh` - 验证 NAT66 配置

### 🔧 修复脚本（针对旧版本问题）

这些脚本用于修复旧版本的特定问题，新部署通常不需要：

- `fix_bandwidth_limits.py` - 修复带宽限制问题
- `fix_baseline_values.py` - 修复流量基准值问题
- `fix_network_after_ip_change.py` - 修复 IP 变更后的网络问题
- `fix_restart_flow.py` - 修复重启后的流量问题
- `manual_fix_accumulated.py` - 手动修复累积流量错误
- `apply_security_fixes.py` - 应用安全修复
- `attach_ipv6_missing.py` - 添加缺失的 IPv6 配置
- `retrofit_nat66_dualstack.py` - 改造为 NAT66 双栈模式

### 📦 升级脚本（一次性）

用于从旧版本升级数据库结构，只需运行一次：

- `upgrade_flow_database.py` - 数据库升级（v1）
- `upgrade_flow_database_v2.py` - 数据库升级（v2）

### 🗂️ 旧版本脚本（已废弃）

已被新版本替代，保留作为参考：

- `install_improved_manager.sh` - 旧安装脚本
- `lxd-flow-manager-improved.sh` - 旧管理脚本
- `setup_network_service.sh` - 旧网络设置脚本

### 🛠️ 临时脚本

为特定任务临时创建的工具：

- `reset_single_container.py` - 手动重置单个容器流量

---

## 🎯 常用场景

### 场景 1：系统出现问题

```bash
cd /root/server/tools
python3 diagnose_flow_management.py
```

**会自动检查并修复：**
- ✅ 定时任务是否配置
- ✅ 守护进程是否运行
- ✅ 容器是否已注册
- ✅ 清理已删除容器的记录

### 场景 2：部署后验证

```bash
cd /root/server/tools
bash post_deploy_check.sh
```

**会检查：**
- 数据库是否创建
- 守护进程是否运行
- 定时任务是否配置
- 管理命令是否安装
- API 服务是否运行

### 场景 3：测试功能

```bash
cd /root/server/tools

# 测试流量监控
python3 test_flow_monitoring.py

# 测试容器连接
python3 test_container_connectivity.py

# 验证流量准确性
python3 verify_flow_accuracy.py
```

### 场景 4：修复特定问题

```bash
cd /root/server/tools

# 如果流量基准值有问题
python3 fix_baseline_values.py

# 如果带宽限制有问题
python3 fix_bandwidth_limits.py
```

### 场景 5：数据库升级

```bash
cd /root/server/tools

# 升级数据库结构（仅运行一次）
python3 upgrade_flow_database_v2.py
```

---

## 📋 使用建议

### ✅ 推荐经常使用

1. **diagnose_flow_management.py** - 诊断和修复工具
   - 系统出问题时首选
   - 可以定期运行检查系统健康状况

2. **post_deploy_check.sh** - 部署检查
   - 每次部署后必须运行
   - 确保所有组件正常

### ⚠️ 按需使用

3. **测试脚本** - 开发调试时使用
4. **验证脚本** - 怀疑配置有问题时使用
5. **修复脚本** - 仅在遇到特定问题时使用

### 🚫 不建议使用

6. **升级脚本** - 只在升级版本时运行一次，不要重复运行
7. **旧版本脚本** - 已废弃，仅作参考

---

## 🔗 相关文档

返回上级目录查看：

- **README_DEPLOYMENT.md** - 完整部署指南
- **DEPLOYMENT_CHECKLIST.md** - 部署检查清单
- **FLOW_TROUBLESHOOTING.md** - 故障排查指南
- **CORE_SCRIPTS.md** - 核心运行脚本清单

---

## ⚠️ 重要提醒

1. **tools/ 目录可选**：删除此目录不影响系统运行
2. **核心脚本在上级目录**：`/root/server/` 才是核心运行脚本
3. **诊断工具最有用**：`diagnose_flow_management.py` 可以解决大部分问题
4. **不要删除数据库**：运行这些工具时不要删除 `flow_management.db`

---

**最后更新**: 2025-10-12

