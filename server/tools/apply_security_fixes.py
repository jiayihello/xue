#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
自动应用安全和性能修复
执行: python3 apply_security_fixes.py
"""

import os
import sys
import subprocess
import shutil
from datetime import datetime

def backup_file(filepath):
    """备份文件"""
    if os.path.exists(filepath):
        backup = f"{filepath}.bak.{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        shutil.copy2(filepath, backup)
        print(f"✅ 已备份: {filepath} -> {backup}")
        return True
    return False

def fix_logging_rotation():
    """修复1: 添加日志轮转"""
    print("\n🔧 修复1: 添加日志轮转...")
    
    files_to_fix = [
        'flow_continuity_daemon.py',
        'flow_limit_enforcer.py', 
        'flow_reset_scheduler.py'
    ]
    
    for filename in files_to_fix:
        if not os.path.exists(filename):
            continue
            
        backup_file(filename)
        
        with open(filename, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # 添加导入
        if 'from logging.handlers import RotatingFileHandler' not in content:
            content = content.replace(
                'import logging',
                'import logging\nfrom logging.handlers import RotatingFileHandler'
            )
        
        # 替换 FileHandler
        content = content.replace(
            "logging.FileHandler('flow_continuity_daemon.log')",
            "RotatingFileHandler('flow_continuity_daemon.log', maxBytes=10*1024*1024, backupCount=5)"
        )
        content = content.replace(
            "logging.FileHandler('flow_limit_enforcer.log')",
            "RotatingFileHandler('flow_limit_enforcer.log', maxBytes=10*1024*1024, backupCount=5)"
        )
        content = content.replace(
            "logging.FileHandler('flow_reset.log')",
            "RotatingFileHandler('flow_reset.log', maxBytes=10*1024*1024, backupCount=5)"
        )
        
        with open(filename, 'w', encoding='utf-8') as f:
            f.write(content)
        
        print(f"  ✅ 已修复: {filename}")

def fix_flask_secret_key():
    """修复2: Flask Secret Key 持久化"""
    print("\n🔧 修复2: Flask Secret Key 持久化...")
    
    # 检查配置文件
    if not os.path.exists('app.ini'):
        print("  ⚠️ app.ini 不存在，跳过")
        return
    
    # 读取配置
    import configparser
    config = configparser.ConfigParser()
    config.read('app.ini')
    
    # 添加 SECRET_KEY
    if not config.has_option('server', 'SECRET_KEY'):
        import secrets
        secret_key = secrets.token_hex(32)
        config.set('server', 'SECRET_KEY', secret_key)
        
        with open('app.ini', 'w') as f:
            config.write(f)
        
        print(f"  ✅ 已生成并保存 SECRET_KEY")
    else:
        print(f"  ℹ️  SECRET_KEY 已存在")
    
    # 修改 app.py
    if os.path.exists('app.py'):
        backup_file('app.py')
        
        with open('app.py', 'r', encoding='utf-8') as f:
            content = f.read()
        
        # 替换 secret_key
        content = content.replace(
            "app.secret_key = os.urandom(24)",
            "app.secret_key = app_config.secret_key if hasattr(app_config, 'secret_key') else os.urandom(24)"
        )
        
        with open('app.py', 'w', encoding='utf-8') as f:
            f.write(content)
        
        print(f"  ✅ 已修复: app.py")
    
    # 修改 config_handler.py
    if os.path.exists('config_handler.py'):
        backup_file('config_handler.py')
        
        with open('config_handler.py', 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        # 在 __init__ 中添加 secret_key 读取
        modified = False
        for i, line in enumerate(lines):
            if 'self.token = parser.get' in line and not modified:
                # 在 token 之后添加
                indent = len(line) - len(line.lstrip())
                lines.insert(i+1, ' ' * indent + "self.secret_key = parser.get('server', 'SECRET_KEY', fallback=None)\n")
                modified = True
                break
        
        if modified:
            with open('config_handler.py', 'w', encoding='utf-8') as f:
                f.writelines(lines)
            print(f"  ✅ 已修复: config_handler.py")

def fix_sqlite_wal_mode():
    """修复3: SQLite WAL 模式"""
    print("\n🔧 修复3: 启用 SQLite WAL 模式...")
    
    if not os.path.exists('flow_manager.py'):
        return
    
    backup_file('flow_manager.py')
    
    with open('flow_manager.py', 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 在每个 sqlite3.connect 后添加 WAL 模式
    content = content.replace(
        'with sqlite3.connect(self.db_path) as conn:',
        '''with sqlite3.connect(self.db_path, timeout=30) as conn:
                conn.execute("PRAGMA journal_mode=WAL")'''
    )
    
    with open('flow_manager.py', 'w', encoding='utf-8') as f:
        f.write(content)
    
    print(f"  ✅ 已修复: flow_manager.py (启用 WAL 模式)")

def fix_api_key_logging():
    """修复4: API Key 脱敏"""
    print("\n🔧 修复4: API Key 日志脱敏...")
    
    if not os.path.exists('app.py'):
        return
    
    backup_file('app.py')
    
    with open('app.py', 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 脱敏 API Key
    old_log = "logger.warning(f\"API认证失败: 无效的API Key from {request.remote_addr}.提供的Key: '{provided_key}'\")"
    new_log = '''masked_key = (provided_key[:4] + '***' + provided_key[-4:]) if provided_key and len(provided_key) > 8 else '***'
            logger.warning(f"API认证失败: 无效的API Key from {request.remote_addr}. Key: {masked_key}")'''
    
    content = content.replace(old_log, new_log)
    
    with open('app.py', 'w', encoding='utf-8') as f:
        f.write(content)
    
    print(f"  ✅ 已修复: app.py (API Key 脱敏)")

def add_memory_monitoring():
    """修复5: 添加内存监控"""
    print("\n🔧 修复5: 添加内存监控...")
    
    if not os.path.exists('flow_continuity_daemon.py'):
        return
    
    backup_file('flow_continuity_daemon.py')
    
    with open('flow_continuity_daemon.py', 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 添加 psutil 导入
    if 'import psutil' not in content:
        content = content.replace(
            'from config_handler import app_config',
            'from config_handler import app_config\nimport psutil'
        )
    
    # 在 health_check 中添加内存监控
    health_check_addition = '''
        # 内存使用监控
        try:
            import psutil
            process = psutil.Process()
            mem_mb = process.memory_info().rss / 1024 / 1024
            logger.info(f"守护进程内存使用: {mem_mb:.1f} MB")
            
            if mem_mb > 500:  # 超过500MB警告
                logger.warning(f"⚠️  内存使用过高: {mem_mb:.1f} MB，建议检查")
        except ImportError:
            logger.debug("psutil 未安装，跳过内存监控。安装: pip3 install psutil")
        except Exception as e:
            logger.debug(f"内存监控异常: {e}")
'''
    
    # 在健康检查函数末尾添加
    if '# 重置失败计数器' in content:
        content = content.replace(
            '# 重置失败计数器（给容器第二次机会）',
            health_check_addition + '\n        # 重置失败计数器（给容器第二次机会）'
        )
    
    with open('flow_continuity_daemon.py', 'w', encoding='utf-8') as f:
        f.write(content)
    
    print(f"  ✅ 已修复: flow_continuity_daemon.py (添加内存监控)")
    print(f"  ℹ️  需要安装: pip3 install psutil")

def create_requirements_update():
    """更新 requirements.txt"""
    print("\n📦 更新依赖...")
    
    if os.path.exists('requirements.txt'):
        with open('requirements.txt', 'r') as f:
            reqs = f.read()
        
        if 'psutil' not in reqs:
            with open('requirements.txt', 'a') as f:
                f.write('\npsutil>=5.9.0\n')
            print("  ✅ 已添加 psutil 到 requirements.txt")

def install_dependencies():
    """安装新依赖"""
    print("\n📥 安装新依赖...")
    try:
        subprocess.run(['pip3', 'install', 'psutil'], check=True)
        print("  ✅ psutil 安装成功")
    except:
        print("  ⚠️  psutil 安装失败，请手动安装: pip3 install psutil")

def create_health_check_endpoint():
    """创建健康检查端点"""
    print("\n🏥 添加健康检查端点...")
    
    health_check_code = '''
@app.route('/health')
def health_check():
    """健康检查端点"""
    checks = {
        'status': 'ok',
        'timestamp': datetime.datetime.now().isoformat()
    }
    
    # 检查 LXD 连接
    try:
        lxc.client.containers.all()
        checks['lxd'] = 'ok'
    except Exception as e:
        checks['lxd'] = 'error'
        checks['lxd_error'] = str(e)
    
    # 检查数据库
    try:
        fm = get_flow_manager()
        if fm:
            fm.get_container_flow_info('health_check')
            checks['database'] = 'ok'
        else:
            checks['database'] = 'not_initialized'
    except Exception as e:
        checks['database'] = 'error'
        checks['database_error'] = str(e)
    
    # 检查磁盘空间
    try:
        import shutil
        stat = shutil.disk_usage('/')
        free_gb = stat.free / (1024**3)
        checks['disk_free_gb'] = round(free_gb, 2)
        checks['disk'] = 'ok' if free_gb > 1 else 'low'
    except Exception as e:
        checks['disk'] = 'unknown'
    
    status_code = 200 if checks.get('lxd') == 'ok' and checks.get('database') == 'ok' else 503
    return jsonify(checks), status_code
'''
    
    if os.path.exists('app.py'):
        backup_file('app.py')
        
        with open('app.py', 'r', encoding='utf-8') as f:
            content = f.read()
        
        if '@app.route(\'/health\')' not in content:
            # 在文件末尾的 if __name__ 之前插入
            content = content.replace(
                "if __name__ == '__main__':",
                health_check_code + "\nif __name__ == '__main__':"
            )
            
            with open('app.py', 'w', encoding='utf-8') as f:
                f.write(content)
            
            print("  ✅ 已添加健康检查端点: /health")

def main():
    """主函数"""
    print("=" * 60)
    print("  LXD容器管理系统 - 安全与性能修复工具")
    print("=" * 60)
    
    # 检查当前目录
    if not os.path.exists('app.py'):
        print("\n❌ 错误: 请在 server 目录下运行此脚本")
        sys.exit(1)
    
    print("\n⚠️  修复前会自动备份文件（.bak.日期时间）")
    print("\n开始应用修复...")
    
    try:
        # 应用修复
        fix_logging_rotation()
        fix_flask_secret_key()
        fix_sqlite_wal_mode()
        fix_api_key_logging()
        add_memory_monitoring()
        create_requirements_update()
        create_health_check_endpoint()
        
        # 安装依赖
        print("\n是否立即安装新依赖？(y/N): ", end='')
        if input().lower() == 'y':
            install_dependencies()
        
        print("\n" + "=" * 60)
        print("✅ 修复完成！")
        print("=" * 60)
        print("\n📋 后续步骤:")
        print("1. 检查备份文件（*.bak.*）确认修改正确")
        print("2. 重启所有服务:")
        print("   systemctl restart lxd-api")
        print("   systemctl restart lxd-flow-continuity")
        print("3. 访问健康检查: curl http://localhost:8060/health")
        print("4. 查看完整报告: cat SECURITY_AUDIT_REPORT.md")
        print("\n⚠️  如有问题，可从备份文件恢复")
        
    except Exception as e:
        print(f"\n❌ 修复过程中出错: {e}")
        print("请检查备份文件并手动恢复")
        sys.exit(1)

if __name__ == "__main__":
    main()

