# 流量管理系统部署检查清单

## 📋 目的

本检查清单确保流量管理系统的完整部署，避免常见问题：
- ✅ 新建容器自动注册到流量管理系统
- ✅ 到重置日自动重置流量
- ✅ 所有组件正常工作

## 🚀 部署步骤检查清单

### 阶段一：基础部署

- [ ] **1. 系统环境准备**
  ```bash
  apt update -y
  apt install -y python3-pip python3 sqlite3 cron
  pip3 install -r requirements.txt
  ```

- [ ] **2. 部署流量管理功能**
  ```bash
  cd /root/server
  sudo bash deploy_production_flow.sh
  ```
  
  **期望输出：**
  - ✅ 数据库初始化完成
  - ✅ 守护进程已启动
  - ✅ 定时任务已配置
  - ✅ 所有验证通过

### 阶段二：验证部署

- [ ] **3. 运行自动验证**
  ```bash
  bash post_deploy_check.sh
  ```
  
  **必须通过的检查：**
  - ✅ 数据库正常
  - ✅ 守护进程正在运行
  - ✅ 定时任务已配置（≥2条）
  - ✅ 管理命令已安装
  - ✅ API 服务正在运行

- [ ] **4. 如果验证失败，自动修复**
  ```bash
  bash post_deploy_check.sh --auto-fix
  ```
  
  或手动诊断：
  ```bash
  python3 diagnose_flow_management.py
  ```

### 阶段三：功能测试

- [ ] **5. 测试容器注册**
  ```bash
  # 查看已注册容器
  python3 list_flow_usage.py
  
  # 手动注册所有容器（如果需要）
  lxd-flow-manager register
  ```
  
  **验证：** 所有 LXD 容器都应该在列表中

- [ ] **6. 测试定时任务**
  ```bash
  # 查看定时任务
  crontab -l | grep flow
  ```
  
  **必须包含：**
  ```
  0 2 * * * /usr/bin/python3 /root/server/flow_reset_scheduler.py reset
  0 3 * * 0 /usr/bin/python3 /root/server/flow_reset_scheduler.py cleanup
  ```

- [ ] **7. 测试手动重置**
  ```bash
  # 查看容器流量信息
  lxd-flow-manager info <容器名>
  
  # 手动重置流量
  lxd-flow-manager reset <容器名>
  
  # 验证流量已归零
  lxd-flow-manager info <容器名>
  ```

- [ ] **8. 测试自动重置**
  ```bash
  # 手动触发自动重置（只重置到期的容器）
  python3 flow_reset_scheduler.py reset
  
  # 查看日志
  tail -50 flow_reset.log
  ```

### 阶段四：服务验证

- [ ] **9. 检查守护进程**
  ```bash
  systemctl status lxd-flow-continuity.service
  journalctl -u lxd-flow-continuity.service -n 50
  ```
  
  **期望状态：** active (running)

- [ ] **10. 检查 API 服务**
  ```bash
  systemctl status lxd-api.service
  
  # 测试 API
  TOKEN=$(grep '^TOKEN' /root/server/app.ini | cut -d'=' -f2 | tr -d ' ')
  curl -H "apikey: $TOKEN" "http://localhost:8060/api/check"
  ```
  
  **期望响应：** `{"code": 200, "msg": "API连接正常"}`

- [ ] **11. 测试新建容器自动注册**
  ```bash
  # 记录当前容器数
  BEFORE=$(sqlite3 flow_management.db "SELECT COUNT(*) FROM container_flow_management;")
  
  # 创建测试容器（通过 API 或面板）
  # ...
  
  # 等待几秒后检查
  sleep 5
  AFTER=$(sqlite3 flow_management.db "SELECT COUNT(*) FROM container_flow_management;")
  
  # 验证
  if [ $AFTER -gt $BEFORE ]; then
      echo "✅ 新容器自动注册成功"
  else
      echo "❌ 新容器未自动注册"
  fi
  ```

## ⚠️ 常见问题检查

### 问题 1: 定时任务未配置

**症状：**
```bash
crontab -l | grep flow
# 输出为空或只有一条
```

**修复：**
```bash
python3 diagnose_flow_management.py
# 选择 Y 自动修复
```

**验证：**
```bash
crontab -l | grep flow
# 应该看到至少 2 条任务
```

### 问题 2: 守护进程未运行

**症状：**
```bash
systemctl status lxd-flow-continuity.service
# 状态为 inactive 或 failed
```

**修复：**
```bash
systemctl restart lxd-flow-continuity.service
journalctl -u lxd-flow-continuity.service -n 50
```

**验证：**
```bash
systemctl is-active lxd-flow-continuity.service
# 输出: active
```

### 问题 3: 容器未注册

**症状：**
```bash
python3 list_flow_usage.py
# 看不到某些容器
```

**修复：**
```bash
lxd-flow-manager register
lxd-flow-manager cleanup
```

**验证：**
```bash
python3 list_flow_usage.py
# 所有容器都应该在列表中
```

## 📊 最终验证清单

部署完成后，确保以下所有命令都能正常执行：

```bash
# 1. 查看所有容器流量
python3 list_flow_usage.py

# 2. 查看单个容器信息
lxd-flow-manager info <容器名>

# 3. 查看定时任务
crontab -l | grep flow

# 4. 查看守护进程状态
systemctl status lxd-flow-continuity.service

# 5. 查看 API 服务状态
systemctl status lxd-api.service

# 6. 运行系统诊断
python3 diagnose_flow_management.py
```

**所有命令都应该正常执行且无错误！**

## 🔄 定期维护检查

每周或每月执行：

```bash
# 1. 运行诊断检查
cd /root/server
python3 diagnose_flow_management.py

# 2. 查看流量使用情况
python3 list_flow_usage.py

# 3. 检查日志
journalctl -u lxd-flow-continuity.service -n 100

# 4. 清理无效记录
lxd-flow-manager cleanup

# 5. 验证定时任务执行
grep CRON /var/log/syslog | grep flow_reset | tail -20
```

## 📝 部署记录

**部署信息：**
- 部署日期：__________
- 服务器IP：__________
- 容器数量：__________
- 部署人员：__________

**验证结果：**
- [ ] 数据库正常
- [ ] 守护进程运行
- [ ] 定时任务配置
- [ ] 管理命令可用
- [ ] 容器已注册
- [ ] API 服务正常
- [ ] 新建容器自动注册
- [ ] 自动重置功能正常

**签字确认：** __________

---

## 🎯 快速修复命令

如果遇到任何问题，运行：

```bash
# 方法 1: 自动诊断和修复
cd /root/server
python3 diagnose_flow_management.py

# 方法 2: 部署后验证和修复
bash post_deploy_check.sh --auto-fix

# 方法 3: 重新部署（最后手段）
sudo bash deploy_production_flow.sh
```

---

**最后更新：** 2025-10-10
**版本：** v2.0（增强部署验证）

