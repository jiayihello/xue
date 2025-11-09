#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
LXD容器批量迁移工具
支持将当前服务器的所有容器迁移到目标服务器
"""

import sys
import os
import json
import subprocess
import sqlite3
import random
from datetime import datetime

# 添加父目录(server/)到Python路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lxc_manager import LXCManager
from flow_manager import FlowManager

def run_command(cmd, timeout=300):
    """执行命令并返回结果"""
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return result.returncode == 0, result.stdout.strip(), result.stderr.strip()
    except Exception as e:
        return False, "", str(e)

def export_container_data(container_name):
    """导出容器的配置和流量数据（包含 NAT 规则，若 API 为空则从 proxy 设备兜底提取），
    同时附带 expanded_config/expanded_devices 以便导入时精确还原 limits 与 root.size。
    """
    print(f"导出容器 {container_name} 的数据...")

    try:
        # 获取容器配置
        lxc_manager = LXCManager()
        container_info = lxc_manager.get_container_info(container_name)

        # 获取流量管理数据
        flow_manager = FlowManager()
        flow_info = flow_manager.get_container_flow_info(container_name)

        # 获取 expanded 配置（实例+profile 合并后的有效配置/设备）
        expanded_config, expanded_devices = {}, {}
        try:
            c = lxc_manager._get_container_or_error(container_name)
            if c:
                expanded_config = getattr(c, 'expanded_config', {}) or {}
                expanded_devices = getattr(c, 'expanded_devices', {}) or {}
        except Exception:
            pass

        # 获取端口映射规则（优先 API）
        success, nat_output, _ = run_command(
            f"curl -s -H 'apikey: $(grep '^TOKEN' app.ini | cut -d'=' -f2 | tr -d ' ')' 'http://localhost:8060/api/natlist?hostname={container_name}'"
        )
        nat_json = json.loads(nat_output) if (success and nat_output) else {"data": []}
        nat_list = nat_json.get("data", []) or []

        # 兜底：从容器 proxy 设备提取
        if not nat_list and c:
            try:
                if c.devices:
                    for dev_name, dev in c.devices.items():
                        if dev.get('type') == 'proxy' and dev_name.startswith('nat-'):
                            ls = (dev.get('listen') or '').split(':')
                            cs = (dev.get('connect') or '').split(':')
                            if len(ls) == 3 and len(cs) == 3:
                                dtype = (ls[0] or '').lower()
                                dport = ls[2]
                                sport = cs[2]
                                nat_list.append({
                                    'Dtype': dtype.upper(),
                                    'Dport': dport,
                                    'Sport': sport,
                                    'ID': f"proxy-{dtype}-{dport}"
                                })
            except Exception:
                pass

        # 组合导出数据
        export_data = {
            "container_info": container_info,
            "flow_info": flow_info,
            "nat_rules": nat_list,
            "expanded_config": expanded_config,
            "expanded_devices": expanded_devices,
            "export_time": datetime.now().isoformat(),
            "source_server": os.uname().nodename
        }

        # 保存到文件
        export_file = f"{container_name}_migration_data.json"
        with open(export_file, 'w', encoding='utf-8') as f:
            json.dump(export_data, f, indent=2, ensure_ascii=False)

        print(f"✅ 容器数据已导出到: {export_file}")
        return export_file

    except Exception as e:
        print(f"❌ 导出容器数据失败: {e}")
        return None

def export_container_image(container_name):
    """导出容器镜像（健壮：自动停机、快照发布、已存在镜像指纹解析、fallback 到 lxc export）。
    返回导出的“元数据文件”实际路径（.tar.xz 或 .tar.gz）。若走实例备份，返回备份 tar 路径。
    同时会把同前缀的 .rootfs 文件保留在当前目录，供打包阶段一并纳入。
    """
    print(f"导出容器 {container_name} 的镜像...")
    try:
        alias = f"{container_name}-migration-{int(datetime.now().timestamp())}"
        snapshot = f"mig-for-export"
        was_running = False
        have_alias = False
        existing_fingerprint = None

        # 导出前清理可能残留的同名前缀文件
        prefix = f"{container_name}_image"
        run_command(f"rm -f {prefix}* 2>/dev/null || true")

        # 检查是否运行中
        ok, state_out, _ = run_command(f"lxc list --format csv -c s {container_name}")
        if ok and state_out.strip().upper() == 'RUNNING':
            was_running = True

        # 停止容器（仅在运行时）
        if was_running:
            _ok, _, _ = run_command(f"lxc stop {container_name} --timeout 120")

        # 尝试快照发布（更稳）
        run_command(f"lxc snapshot {container_name} {snapshot}")
        pub_ok, _, pub_err = run_command(f"lxc publish {container_name}/{snapshot} --alias {alias}")
        if pub_ok:
            have_alias = True
        else:
            if 'already exists' in pub_err:
                parts = pub_err.split()
                existing_fingerprint = parts[-1] if parts else None
                print(f"ℹ️ 镜像已存在，使用已存在指纹: {existing_fingerprint}")
            else:
                print(f"⚠️ 发布镜像失败，尝试 lxc export 备份路径: {pub_err}")

        # 导出（使用固定前缀，便于识别 meta 与 rootfs）
        meta_file = None
        if have_alias:
            ok, _, err = run_command(f"lxc image export {alias} {prefix}")
            if not ok:
                print(f"❌ 导出镜像失败: {err}")
                return None
        elif existing_fingerprint:
            ok, _, err = run_command(f"lxc image export {existing_fingerprint} {prefix}")
            if not ok:
                print(f"❌ 导出镜像失败: {err}")
                return None
        else:
            # 直接导出实例备份（无需镜像）
            ok, _, err = run_command(f"lxc export {container_name} {prefix}.tar.gz --instance-only")
            if not ok:
                print(f"❌ 备份导出失败: {err}")
                return None
            meta_file = f"{prefix}.tar.gz"

        # 确认导出的 meta 与 rootfs 文件
        if meta_file is None:
            # lxc image export 默认生成 {prefix}.tar.xz 与 {prefix}.rootfs
            # 也可能是 .tar.gz
            candidates = []
            for ext in ('.tar.xz', '.tar.gz'):
                p = f"{prefix}{ext}"
                if os.path.exists(p):
                    candidates.append(p)
            if not candidates:
                print("❌ 未找到镜像元数据文件（.tar.xz/.tar.gz）")
                return None
            # 优先 .tar.xz
            meta_file = candidates[0] if candidates[0].endswith('.tar.xz') else candidates[-1]

        # 清理：删除别名镜像与快照
        if have_alias:
            run_command(f"lxc image delete {alias}")
        run_command(f"lxc delete {container_name}/{snapshot}")

        # 恢复运行状态
        if was_running:
            run_command(f"lxc start {container_name}")

        print(f"✅ 容器镜像已导出到: {meta_file}")
        return meta_file

    except Exception as e:
        print(f"❌ 导出容器镜像失败: {e}")
        return None

def create_migration_package(container_name):
    """创建完整的迁移包"""
    print(f"\n=== 创建容器 {container_name} 的迁移包 ===")
    
    # 导出配置数据
    data_file = export_container_data(container_name)
    if not data_file:
        return False
    
    # 导出容器镜像
    image_file = export_container_image(container_name)
    if not image_file:
        return False
    
    # 创建迁移包
    package_name = f"{container_name}_migration_package"
    success, _, error = run_command(f"mkdir -p {package_name}")
    if not success:
        print(f"❌ 创建迁移包目录失败: {error}")
        return False

    # 移动文件到迁移包（包含 rootfs 伴随文件）
    run_command(f"mv {data_file} {package_name}/")
    run_command(f"mv {image_file} {package_name}/")
    # 伴随 rootfs 文件（lxc image export 通常生成 prefix.rootfs）
    base_noext = image_file.replace('.tar.xz','').replace('.tar.gz','')
    run_command(f"[ -f {base_noext}.rootfs ] && mv {base_noext}.rootfs {package_name}/ || true")
    # 兼容旧命名：<meta>.rootfs
    run_command(f"[ -f {image_file}.rootfs ] && mv {image_file}.rootfs {package_name}/ || true")

    # 创建迁移说明文件
    readme_content = f"""# 容器 {container_name} 迁移包

## 包含文件
- {data_file}: 容器配置和流量数据
- {image_file}: 容器镜像文件

## 迁移步骤
1. 将整个迁移包传输到目标服务器
2. 在目标服务器上运行: python3 migrate_containers.py import {package_name}
3. 验证迁移结果

## 迁移时间
{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

## 源服务器
{os.uname().nodename}
"""
    
    with open(f"{package_name}/README.md", 'w', encoding='utf-8') as f:
        f.write(readme_content)
    
    # 打包
    success, _, error = run_command(f"tar -czf {package_name}.tar.gz {package_name}")
    if success:
        print(f"✅ 迁移包创建完成: {package_name}.tar.gz")
        # 清理临时目录
        run_command(f"rm -rf {package_name}")
        return f"{package_name}.tar.gz"
    else:
        print(f"❌ 打包失败: {error}")
        return False

def import_migration_package(package_path):
    """导入迁移包"""
    print(f"\n=== 导入迁移包 {package_path} ===")
    
    try:
        # 解压迁移包
        package_dir = package_path.replace('.tar.gz', '')
        success, _, error = run_command(f"tar -xzf {package_path}")
        if not success:
            print(f"❌ 解压迁移包失败: {error}")
            return False
        
        # 查找数据文件和镜像文件（递归扫描，兼容 rootfs 伴随文件 或 实例备份）
        data_file = None
        image_meta = None
        image_rootfs = None
        backup_file = None
        all_files = []
        for root, dirs, files in os.walk(package_dir):
            for fname in files:
                all_files.append(os.path.join(root, fname))
        for p in all_files:
            if p.endswith('_migration_data.json'):
                data_file = p
            elif p.endswith('_image.tar.gz') or p.endswith('_image.tar.xz'):
                image_meta = p
            elif p.endswith('.rootfs'):
                image_rootfs = p
            elif p.endswith('.tar.gz') and (not p.endswith('_image.tar.gz')) and backup_file is None:
                # 可能是实例备份（lxc export）
                backup_file = p
        if image_meta and not image_rootfs and os.path.exists(image_meta + '.rootfs'):
            image_rootfs = image_meta + '.rootfs'
        if not data_file:
            print("❌ 迁移包缺少 *_migration_data.json")
            print("📄 包内文件：")
            for p in all_files:
                print("  -", os.path.relpath(p, package_dir))
            return False
        if not (image_meta or backup_file):
            print("❌ 迁移包缺少镜像文件（_image.tar.gz 或实例备份 .tar.gz）")
            print("📄 包内文件：")
            for p in all_files:
                print("  -", os.path.relpath(p, package_dir))
            return False
        image_file = image_meta or backup_file

        if not data_file or not image_file:
            print(f"❌ 迁移包内容不完整")
            return False
        
        # 读取配置数据
        with open(data_file, 'r', encoding='utf-8') as f:
            migration_data = json.load(f)

        # 兼容不同导出结构：container_info 可能是 {code,msg,data:{Hostname,..}}
        ci = migration_data.get('container_info', {}) or {}
        container_name = (
            ci.get('Hostname') or
            (ci.get('data') or {}).get('Hostname') or
            ((ci.get('data') or {}).get('raw_lxd_info') or {}).get('name')
        )
        if not container_name:
            print("❌ 无法从迁移数据中解析容器名称（缺少 Hostname/raw_lxd_info.name）")
            return False

        # 导入前，先清理目标机上可能残留的旧镜像与同名实例，避免冲突
        print(f"清理目标机上 '{container_name}' 的残留镜像...")
        run_command(f"lxc image list --format csv -c l | grep {container_name} | xargs -r lxc image delete")
        run_command(f"lxc delete {container_name} --force 2>/dev/null || true")

        # 根据包内容智能判断导入方式：
        # 1) 备份包：包含 backup/index.yaml -> lxc import
        # 2) 镜像包：包含 metadata.yaml -> lxc image import [meta] [rootfs] --alias ... + lxc launch
        # 3) 未识别：先尝试镜像导入，失败再尝试备份导入
        used_image_alias = False
        alias = f"{container_name}-imported-{int(datetime.now().timestamp())}"

        def tar_has(path, marker):
            ok, _, _ = run_command(f"tar -tf '{path}' 2>/dev/null | grep -q '{marker}'")
            return ok

        is_backup = tar_has(image_file, '^backup/index.yaml$')
        has_meta = tar_has(image_file, '^metadata.yaml$')

        if is_backup:
            ok_imp, _, err_imp = run_command(f"lxc import '{image_file}'")
            if not ok_imp:
                print(f"❌ 实例备份导入失败: {err_imp}")
                return False
            print("✅ 已通过实例备份恢复容器")
        elif has_meta or (image_rootfs and os.path.exists(image_rootfs)):
            import_cmd = f"lxc image import '{image_file}'"
            if image_rootfs and os.path.exists(image_rootfs):
                import_cmd += f" '{image_rootfs}'"
            import_cmd += f" --alias {alias}"
            success, _, error = run_command(import_cmd)
            if not success:
                print(f"❌ 镜像导入失败: {error}")
                # 尝试备份导入兜底
                ok_imp, _, err_imp = run_command(f"lxc import '{image_file}'")
                if not ok_imp:
                    return False
                print("✅ 已通过实例备份恢复容器（镜像导入失败后兜底）")
            else:
                used_image_alias = True
                print("--> 正在从镜像创建容器，这在性能较弱的VPS上可能需要长达15分钟，请耐心等待...")
                ok_launch, _, err_launch = run_command(f"lxc launch {alias} {container_name} --verbose", timeout=900)
                if not ok_launch:
                    print(f"❌ 使用别名 '{alias}' 创建容器失败: {err_launch}")
                    return False
        else:
            # 未识别：先试镜像，再试备份
            try_img_cmd = f"lxc image import '{image_file}'"
            if image_rootfs and os.path.exists(image_rootfs):
                try_img_cmd += f" '{image_rootfs}'"
            try_img_cmd += f" --alias {alias}"
            ok_img, _, err_img = run_command(try_img_cmd)
            if ok_img:
                used_image_alias = True
                ok_launch, _, err_launch = run_command(f"lxc launch {alias} {container_name} --verbose", timeout=900)
                if not ok_launch:
                    print(f"❌ 使用别名 '{alias}' 创建容器失败: {err_launch}")
                    return False
            else:
                ok_imp, _, err_imp = run_command(f"lxc import '{image_file}'")
                if not ok_imp:
                    print(f"❌ 无法识别并导入迁移包（镜像/备份均失败）: {err_img or err_imp}")
                    return False
                print("✅ 已通过实例备份恢复容器（识别失败后兜底）")

        # 恢复流量管理数据（完整字段）
        if migration_data.get('flow_info'):
            flow_manager = FlowManager()
            flow_info = migration_data['flow_info']
            # 注册容器到流量管理系统（带限额）
            flow_manager.register_container(container_name, flow_info.get('flow_limit_gb', 0))
            with sqlite3.connect(flow_manager.db_path) as conn:
                # 兼容性：确保列存在
                cols = [row[1] for row in conn.execute("PRAGMA table_info(container_flow_management)").fetchall()]
                def ensure(col, ddl):
                    if col not in cols:
                        conn.execute(ddl)
                ensure('accumulated_bytes_received', "ALTER TABLE container_flow_management ADD COLUMN accumulated_bytes_received BIGINT DEFAULT 0")
                ensure('accumulated_bytes_sent',     "ALTER TABLE container_flow_management ADD COLUMN accumulated_bytes_sent BIGINT DEFAULT 0")
                ensure('last_max_bytes_received',    "ALTER TABLE container_flow_management ADD COLUMN last_max_bytes_received BIGINT DEFAULT 0")
                ensure('last_max_bytes_sent',        "ALTER TABLE container_flow_management ADD COLUMN last_max_bytes_sent BIGINT DEFAULT 0")
                ensure('baseline_bytes_received',    "ALTER TABLE container_flow_management ADD COLUMN baseline_bytes_received BIGINT DEFAULT 0")
                ensure('baseline_bytes_sent',        "ALTER TABLE container_flow_management ADD COLUMN baseline_bytes_sent BIGINT DEFAULT 0")
                ensure('current_period_start',       "ALTER TABLE container_flow_management ADD COLUMN current_period_start DATE")
                ensure('auto_reset_enabled',         "ALTER TABLE container_flow_management ADD COLUMN auto_reset_enabled BOOLEAN DEFAULT 1")
                ensure('flow_limit_gb',              "ALTER TABLE container_flow_management ADD COLUMN flow_limit_gb INTEGER DEFAULT 0")
                # 执行更新
                conn.execute("""
                    UPDATE container_flow_management
                    SET created_date = ?,
                        baseline_bytes_received = ?,
                        baseline_bytes_sent = ?,
                        accumulated_bytes_received = ?,
                        accumulated_bytes_sent = ?,
                        last_max_bytes_received = ?,
                        last_max_bytes_sent = ?,
                        last_reset_date = ?,
                        next_reset_date = ?,
                        current_period_start = ?,
                        reset_count = ?,
                        auto_reset_enabled = COALESCE(?, 1),
                        flow_limit_gb = COALESCE(?, flow_limit_gb)
                    WHERE hostname = ?
                """, (
                    flow_info.get('created_date'),
                    flow_info.get('baseline_bytes_received', 0),
                    flow_info.get('baseline_bytes_sent', 0),
                    flow_info.get('accumulated_bytes_received', 0),
                    flow_info.get('accumulated_bytes_sent', 0),
                    flow_info.get('last_max_bytes_received', 0),
                    flow_info.get('last_max_bytes_sent', 0),
                    flow_info.get('last_reset_date'),
                    flow_info.get('next_reset_date'),
                    flow_info.get('current_period_start'),
                    flow_info.get('reset_count', 0),
                    flow_info.get('auto_reset_enabled', 1),
                    flow_info.get('flow_limit_gb', 0),
                    container_name
                ))

        # 恢复容器资源/配置（优先 expanded，确保与源机 profile 继承后一致）
        original_status = (migration_data.get('container_info', {}).get('raw_lxd_info') or {}).get('status')
        exp_cfg = migration_data.get('expanded_config', {})
        exp_devs = migration_data.get('expanded_devices', {})

        # 恢复CPU
        if exp_cfg.get('limits.cpu'):
            run_command(f"lxc config set {container_name} limits.cpu \"{exp_cfg['limits.cpu']}\"")
        # 恢复内存
        if exp_cfg.get('limits.memory'):
            run_command(f"lxc config set {container_name} limits.memory {exp_cfg['limits.memory']}")

        # 恢复其他重要配置 (user.*, environment.*, security.*)
        for key, value in exp_cfg.items():
            if any(key.startswith(p) for p in ('user.', 'environment.', 'security.')):
                 run_command(f"lxc config set {container_name} {key} \"{value}\"")

        # 恢复磁盘（需要在容器停止时操作，并 override profile device）
        disk_size_to_set = exp_devs.get('root', {}).get('size')
        if not disk_size_to_set:
            disk_size_mb = exp_cfg.get('user.disk_size_mb')
            if disk_size_mb:
                disk_size_to_set = f"{disk_size_mb}MB"

        if disk_size_to_set:
            print(f"设置容器 {container_name} 的磁盘大小为 {disk_size_to_set}...")
            run_command(f"lxc stop {container_name} --force")
            ok, _, err = run_command(f"lxc config device override {container_name} root size={disk_size_to_set}")
            if not ok:
                print(f"  ❌ 设置磁盘大小失败: {err}")

        # === NAT 恢复（直接使用 lxc proxy, 不依赖 API） ===
        # 清理旧规则
        print(f"清理容器 {container_name} 的旧端口映射规则...")
        run_command(f"lxc config device remove {container_name} `lxc config device list {container_name} | grep '^nat-'` 2>/dev/null || true")

        # 确保容器运行以获取IP (Robust method)
        run_command(f"lxc start {container_name}")
        ip = None
        print("等待容器获取IP地址...")
        for i in range(45):
            ok, _out, _ = run_command(f"lxc exec {container_name} -- ip -4 -br addr show eth0")
            if ok and _out:
                parts = _out.strip().split()
                if len(parts) >= 3 and '/' in parts[2]:
                    ip = parts[2].split('/')[0]
                    print(f"  ✅ 成功获取IP: {ip}")
                    break
            run_command("sleep 1")
            if i > 5 and i % 5 == 0:
                print(f"  ... still waiting for IP ({i}s)")

        # 添加新规则
        nat_rules = list(migration_data.get('nat_rules', []) or [])
        if not nat_rules:
            rnd_port = random.randint(10000, 65535)
            print(f"ℹ️ 未发现 NAT 规则, 自动分配 SSH 端口: {rnd_port} -> 22")
            nat_rules.append({'Dtype': 'TCP', 'Dport': str(rnd_port), 'Sport': '22'})

        print(f"恢复容器 {container_name} 的端口映射规则...")
        if ip:
            for rule in nat_rules:
                dtype = (rule.get('Dtype') or '').lower()
                dport = rule.get('Dport')
                sport = rule.get('Sport')
                if not all([dtype, dport, sport]): continue
                dev_name = f"nat-{dtype}-{dport}"
                cmd = f"lxc config device add {container_name} {dev_name} proxy listen={dtype}:0.0.0.0:{dport} connect={dtype}:{ip}:{sport}"
                ok, _, err = run_command(cmd)
                if ok:
                    print(f"  ✅ 端口映射 {dport} -> {sport} ({dtype})")
                else:
                    print(f"  ❌ 端口映射失败: {err}")
        else:
            print(f"  ❌ 未能获取容器IP, 跳过 NAT 规则恢复。")

        # 根据原状态恢复运行/停止
        if original_status and original_status.lower() == 'stopped':
            run_command(f"lxc stop {container_name} --force")

        # 清理
        try:
            # 仅当通过镜像别名导入时才需要删除别名镜像
            if 'used_image_alias' in locals() and used_image_alias:
                run_command(f"lxc image delete {alias}")
        finally:
            run_command(f"rm -rf {package_dir}")
        # 导入成功后，删除目标机上的迁移包
        print(f"清理目标机上的迁移包: {package_path}")
        run_command(f"rm -f {package_path}")

        print(f"✅ 容器 {container_name} 迁移完成")
        return True

    except Exception as e:
        print(f"❌ 导入迁移包失败: {e}")
        return False

def main():
    """主函数"""
    if len(sys.argv) < 2:
        print("LXD容器迁移工具")
        print()
        print("用法:")
        print("  python3 migrate_containers.py export <容器名>     # 导出单个容器")
        print("  python3 migrate_containers.py export-all         # 导出所有容器")
        print("  python3 migrate_containers.py import <迁移包>     # 导入迁移包")
        print()
        print("示例:")
        print("  python3 migrate_containers.py export ser123456789")
        print("  python3 migrate_containers.py export-all")
        print("  python3 migrate_containers.py import ser123456789_migration_package.tar.gz")
        return
    
    command = sys.argv[1]
    
    if command == "export":
        if len(sys.argv) < 3:
            print("请指定要导出的容器名")
            return
        
        container_name = sys.argv[2]
        package = create_migration_package(container_name)
        if package:
            print(f"\n🎉 迁移包创建成功: {package}")
            print(f"请将此文件传输到目标服务器，然后运行:")
            print(f"python3 migrate_containers.py import {package}")
    
    elif command == "export-all":
        print("=== 批量导出所有容器 ===")
        
        # 获取所有容器
        success, output, error = run_command("lxc list --format csv -c n")
        if not success:
            print(f"❌ 获取容器列表失败: {error}")
            return
        
        containers = [name.strip() for name in output.split('\n') if name.strip()]
        
        if not containers:
            print("没有找到容器")
            return
        
        print(f"找到 {len(containers)} 个容器: {', '.join(containers)}")
        
        packages = []
        for container_name in containers:
            package = create_migration_package(container_name)
            if package:
                packages.append(package)
        
        if packages:
            print(f"\n🎉 批量导出完成，共创建 {len(packages)} 个迁移包:")
            for package in packages:
                print(f"  - {package}")
    
    elif command == "import":
        if len(sys.argv) < 3:
            print("请指定要导入的迁移包路径")
            return
        
        package_path = sys.argv[2]
        if not os.path.exists(package_path):
            print(f"❌ 迁移包文件不存在: {package_path}")
            return
        
        if import_migration_package(package_path):
            print(f"\n🎉 迁移包导入成功")
        else:
            print(f"\n❌ 迁移包导入失败")
            sys.exit(1)
    
    else:
        print(f"❌ 未知命令: {command}")

if __name__ == "__main__":
    main()
