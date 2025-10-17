# ZJMF-LXD-Server 部署指南

## 🚀 快速开始

### 一键部署（推荐）

```bash
cd /root/server
chmod +x deploy_all.sh
sudo bash deploy_all.sh
```

**仅需 5-10 分钟**，全自动完成所有配置！

---

## 📚 文档导航

| 文档 | 说明 | 适合人群 |
|------|------|---------|
| **QUICK_DEPLOY.txt** | 快速部署指南 | ⭐ 新手必读 |
| **✅一键部署说明.md** | 详细使用说明 | 深入了解 |
| **✅一键部署脚本完成.md** | 功能总览 | 开发者参考 |
| **教程.txt** (根目录) | 完整教程 | 全面学习 |

---

## 📋 部署流程

一键部署脚本会自动完成：

1. ✅ 安装 Python 依赖
2. ✅ 配置网络（IPv4 + IPv6）
3. ✅ 流量管理系统
4. ✅ 滥用防护
5. ✅ 后端 API 服务

---

## 🎯 推荐配置

新手推荐使用以下配置：

```
IPv4 地址: [您的服务器IP]
IPv6 模式: off (如果没有IPv6地址段)
流量管理: Y
滥用防护: Y
CPU 监控: N (可选)
后端服务: Y
```

---

## 🧪 部署完成后

### 检查服务状态

```bash
# API 服务
systemctl status lxd-api.service

# 流量守护进程
systemctl status lxd-flow-continuity.service

# 流量限制执行器
systemctl status lxd-flow-enforcer.service
```

### 查看流量使用

```bash
python3 list_flow_usage.py
```

### 测试创建容器

```bash
lxc launch ubuntu:22.04 test-container
lxc list
```

---

## 🔧 常用命令

```bash
# 查看容器列表
lxc list

# 查看流量使用
python3 /root/server/list_flow_usage.py

# 重置容器流量
python3 /root/server/flow_reset_scheduler.py reset <容器名>

# 查看服务日志
journalctl -u lxd-api.service -f
journalctl -u lxd-flow-continuity.service -f

# 应用滥用防护
python3 /root/server/abuse_guard.py apply
```

---

## 📞 获取帮助

如果遇到问题：

1. 查看 `QUICK_DEPLOY.txt` 快速指南
2. 查看 `✅一键部署说明.md` 详细说明
3. 查看 `FLOW_TROUBLESHOOTING.md` 故障排查
4. 运行诊断脚本：`python3 tools/diagnose_flow_management.py`

---

## 🎉 开始部署

```bash
cd /root/server
chmod +x deploy_all.sh
sudo bash deploy_all.sh
```

**5-10 分钟后，您的 LXD 服务器就准备好了！** 🚀

