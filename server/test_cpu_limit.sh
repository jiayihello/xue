#!/bin/bash

# CPU 限制功能测试脚本

set -e

echo "═══════════════════════════════════════════════════════════════"
echo "  CPU 限制功能测试"
echo "═══════════════════════════════════════════════════════════════"
echo ""

# 检查是否有 root 权限
if [ "$EUID" -ne 0 ]; then
    echo "❌ 请使用 root 权限运行此脚本"
    exit 1
fi

# 检查 LXD 是否运行
if ! lxc list &> /dev/null; then
    echo "❌ LXD 未运行或无法连接"
    exit 1
fi

echo "✅ LXD 运行正常"
echo ""

# 测试容器名称
TEST_CONTAINER="test-cpu-limit-$$"

echo "### 第一步：创建测试容器 ###"
echo ""
echo "容器名: $TEST_CONTAINER"

# 创建一个简单的测试容器
if lxc list | grep -q "$TEST_CONTAINER"; then
    echo "⚠️  容器已存在，先删除..."
    lxc delete -f "$TEST_CONTAINER" || true
fi

echo "创建容器..."
lxc launch ubuntu:22.04 "$TEST_CONTAINER" --config limits.cpu=2 --config limits.memory=512MB

# 等待容器启动
echo "等待容器启动..."
sleep 5

echo "✅ 容器创建成功"
echo ""

# 测试设置 CPU 限制
echo "### 第二步：测试设置 CPU 限制 ###"
echo ""

echo "设置 CPU 限制为 50%..."
python3 manage_cpu_limit.py set "$TEST_CONTAINER" 50

# 验证设置
CPU_ALLOWANCE=$(lxc config get "$TEST_CONTAINER" limits.cpu.allowance)
if [ "$CPU_ALLOWANCE" = "50%" ]; then
    echo "✅ CPU 限制设置成功: $CPU_ALLOWANCE"
else
    echo "❌ CPU 限制设置失败: $CPU_ALLOWANCE"
    exit 1
fi
echo ""

# 测试查询
echo "### 第三步：测试查询 CPU 限制 ###"
echo ""

python3 manage_cpu_limit.py get "$TEST_CONTAINER"
echo ""

# 测试修改
echo "### 第四步：测试修改 CPU 限制 ###"
echo ""

echo "修改 CPU 限制为 100%..."
python3 manage_cpu_limit.py set "$TEST_CONTAINER" 100

CPU_ALLOWANCE=$(lxc config get "$TEST_CONTAINER" limits.cpu.allowance)
if [ "$CPU_ALLOWANCE" = "100%" ]; then
    echo "✅ CPU 限制修改成功: $CPU_ALLOWANCE"
else
    echo "❌ CPU 限制修改失败: $CPU_ALLOWANCE"
    exit 1
fi
echo ""

# 测试移除限制
echo "### 第五步：测试移除 CPU 限制 ###"
echo ""

echo "移除 CPU 限制..."
python3 manage_cpu_limit.py set "$TEST_CONTAINER" 0

CPU_ALLOWANCE=$(lxc config get "$TEST_CONTAINER" limits.cpu.allowance || echo "")
if [ -z "$CPU_ALLOWANCE" ]; then
    echo "✅ CPU 限制移除成功"
else
    echo "❌ CPU 限制移除失败，仍然是: $CPU_ALLOWANCE"
    exit 1
fi
echo ""

# 测试 CPU 压力（可选）
echo "### 第六步：CPU 压力测试（可选）###"
echo ""

read -p "是否进行 CPU 压力测试？这将设置 50% 限制并运行压力测试。(y/N): " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo "设置 CPU 限制为 50%..."
    python3 manage_cpu_limit.py set "$TEST_CONTAINER" 50
    
    echo "安装 stress-ng（如果没有）..."
    lxc exec "$TEST_CONTAINER" -- apt-get update -qq
    lxc exec "$TEST_CONTAINER" -- apt-get install -y stress-ng > /dev/null 2>&1 || true
    
    echo "运行 CPU 压力测试（30秒）..."
    echo "（同时观察 CPU 使用率应该被限制在 50% 左右）"
    echo ""
    
    # 在后台运行压力测试
    lxc exec "$TEST_CONTAINER" -- stress-ng --cpu 4 --timeout 30s &
    STRESS_PID=$!
    
    # 监控 CPU 使用率
    for i in {1..30}; do
        CPU_INFO=$(lxc info "$TEST_CONTAINER" | grep "CPU usage" || echo "CPU usage: N/A")
        echo -ne "\r$CPU_INFO   "
        sleep 1
    done
    
    wait $STRESS_PID 2>/dev/null || true
    echo ""
    echo "✅ 压力测试完成"
else
    echo "⏭️  跳过压力测试"
fi
echo ""

# 清理
echo "### 第七步：清理测试容器 ###"
echo ""

read -p "是否删除测试容器 $TEST_CONTAINER？(Y/n): " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Nn]$ ]]; then
    echo "删除容器..."
    lxc delete -f "$TEST_CONTAINER"
    echo "✅ 容器已删除"
else
    echo "⏭️  保留测试容器"
fi
echo ""

# 总结
echo "═══════════════════════════════════════════════════════════════"
echo "  ✅ 测试完成！"
echo "═══════════════════════════════════════════════════════════════"
echo ""
echo "所有功能测试通过："
echo "  ✓ 设置 CPU 限制"
echo "  ✓ 查询 CPU 限制"
echo "  ✓ 修改 CPU 限制"
echo "  ✓ 移除 CPU 限制"
if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo "  ✓ CPU 压力测试"
fi
echo ""
echo "现在可以在生产环境中使用 CPU 限制功能了！"
echo ""

