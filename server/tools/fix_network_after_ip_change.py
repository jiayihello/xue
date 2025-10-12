#!/usr/bin/env python3
"""
修复宿主机IP变更后的网络连接问题
此脚本用于在宿主机IP变更后重新配置网络规则和验证容器连接
"""

import os
import subprocess
import logging
import sys
import json
import time
from config_handler import app_config
import network_setup

logging.basicConfig(level=logging.INFO,
                   format='%(asctime)s %(levelname)s: %(message)s',
                   datefmt='%Y-%m-%d %H:%M:%S')
logger = logging.getLogger('fix_network')

def run_cmd(cmd, check_output=False):
    """执行命令并返回结果"""
    logger.info(f"执行命令: {cmd}")
    try:
        if check_output:
            result = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE, 
                                  stderr=subprocess.PIPE, text=True)
            return result.stdout.strip(), result.returncode
        else:
            process = subprocess.Popen(cmd, stdout=subprocess.PIPE, 
                                     stderr=subprocess.PIPE, shell=True)
            stdout, stderr = process.communicate()
            if process.returncode != 0:
                logger.error(f"命令执行失败 ({process.returncode}): {stderr.decode('utf-8', errors='ignore')}")
                return False
            return True
    except Exception as e:
        logger.error(f"执行命令时出错: {str(e)}")
        return False

def get_current_ip():
    """获取当前主机IP"""
    try:
        # 尝试多种方法获取IP
        methods = [
            "hostname -I | awk '{print $1}'",
            "ip route get 8.8.8.8 | awk '{print $7; exit}'",
            "curl -s --connect-timeout 5 ifconfig.me",
            "curl -s --connect-timeout 5 ipinfo.io/ip"
        ]
        
        for method in methods:
            output, rc = run_cmd(method, check_output=True)
            if rc == 0 and output and output.strip():
                ip = output.strip()
                # 验证IP格式
                parts = ip.split('.')
                if len(parts) == 4 and all(part.isdigit() and 0 <= int(part) <= 255 for part in parts):
                    logger.info(f"检测到当前IP: {ip}")
                    return ip
        
        logger.error("无法自动检测当前IP地址")
        return None
    except Exception as e:
        logger.error(f"获取IP地址时出错: {e}")
        return None

def clear_old_iptables_rules():
    """清理旧的iptables规则"""
    logger.info("清理旧的iptables规则...")
    
    # 清理NAT表中的POSTROUTING规则（只清理LXD相关的）
    logger.info("清理NAT POSTROUTING规则...")
    run_cmd("iptables -t nat -F POSTROUTING")
    
    # 清理FORWARD规则
    logger.info("清理FORWARD规则...")
    run_cmd("iptables -F FORWARD")
    
    # 重新设置默认的FORWARD策略
    run_cmd("iptables -P FORWARD ACCEPT")
    
    logger.info("旧的iptables规则已清理")

def check_container_connectivity():
    """检查容器连接状态"""
    logger.info("检查容器连接状态...")
    
    try:
        # 获取所有容器列表
        output, rc = run_cmd("lxc list --format=json", check_output=True)
        if rc != 0:
            logger.error("无法获取容器列表")
            return False
        
        containers = json.loads(output)
        running_containers = [c for c in containers if c.get('status') == 'Running']
        
        logger.info(f"发现 {len(running_containers)} 个运行中的容器")
        
        for container in running_containers:
            name = container.get('name')
            logger.info(f"检查容器 {name} 的网络连接...")
            
            # 检查容器是否能ping通外网
            ping_result, _ = run_cmd(f"lxc exec {name} -- ping -c 1 -W 3 8.8.8.8", check_output=True)
            if "1 packets transmitted, 1 received" in ping_result:
                logger.info(f"✅ 容器 {name} 网络连接正常")
            else:
                logger.warning(f"❌ 容器 {name} 无法连接外网")
        
        return True
    except Exception as e:
        logger.error(f"检查容器连接时出错: {e}")
        return False

def verify_port_forwards():
    """验证端口转发规则"""
    logger.info("验证端口转发规则...")
    
    try:
        # 读取端口转发元数据
        if os.path.exists('iptables_rules.json'):
            with open('iptables_rules.json', 'r') as f:
                rules = json.load(f)
            
            logger.info(f"发现 {len(rules)} 条端口转发规则")
            
            for rule in rules:
                hostname = rule.get('hostname')
                dport = rule.get('dport')
                sport = rule.get('sport')
                dtype = rule.get('dtype')
                
                logger.info(f"验证容器 {hostname} 的端口转发: {dtype} {dport} -> {sport}")
                
                # 检查LXD proxy设备是否存在
                device_name = f"nat-{dtype.lower()}-{dport}"
                check_cmd = f"lxc config show {hostname} | grep -A 5 '{device_name}:'"
                output, rc = run_cmd(check_cmd, check_output=True)
                
                if rc == 0 and device_name in output:
                    logger.info(f"✅ 容器 {hostname} 的端口转发设备 {device_name} 存在")
                else:
                    logger.warning(f"❌ 容器 {hostname} 的端口转发设备 {device_name} 不存在或配置异常")
        else:
            logger.info("未找到端口转发规则文件")
        
        return True
    except Exception as e:
        logger.error(f"验证端口转发时出错: {e}")
        return False

def backup_current_config():
    """备份当前配置"""
    logger.info("备份当前配置...")
    
    try:
        # 备份iptables规则文件
        if os.path.exists('iptables_rules.json'):
            backup_file = f"iptables_rules.json.backup.{int(time.time())}"
            run_cmd(f"cp iptables_rules.json {backup_file}")
            logger.info(f"已备份端口转发规则到: {backup_file}")
        
        # 备份容器列表
        output, rc = run_cmd("lxc list --format=json", check_output=True)
        if rc == 0:
            backup_file = f"containers_backup.{int(time.time())}.json"
            with open(backup_file, 'w') as f:
                f.write(output)
            logger.info(f"已备份容器列表到: {backup_file}")
        
        return True
    except Exception as e:
        logger.error(f"备份配置时出错: {e}")
        return False

def main():
    """主修复流程"""
    print("===== 修复宿主机IP变更后的网络问题 =====")

    # 检查是否有root权限
    if os.geteuid() != 0:
        logger.error("此脚本需要root权限运行，请使用sudo")
        sys.exit(1)

    try:
        # 0. 备份当前配置
        logger.info("步骤 0: 备份当前配置...")
        backup_current_config()

        # 1. 获取当前IP
        logger.info("步骤 1: 检测当前IP地址...")
        current_ip = get_current_ip()
        if not current_ip:
            logger.error("无法获取当前IP，请手动检查网络配置")
            logger.info("您可以手动运行以下命令获取IP:")
            logger.info("  hostname -I | awk '{print $1}'")
            logger.info("  ip route get 8.8.8.8 | awk '{print $7; exit}'")
            return False

        # 2. 检查配置文件中的IP是否需要更新
        logger.info("步骤 2: 检查配置文件...")
        try:
            config_ip = app_config.nat_listen_ip
            if config_ip != current_ip:
                logger.warning(f"配置文件中的IP ({config_ip}) 与当前IP ({current_ip}) 不匹配")
                logger.warning("请更新 server/app.ini 文件中的 NAT_LISTEN_IP 配置")
                logger.warning(f"将 NAT_LISTEN_IP = {config_ip} 改为 NAT_LISTEN_IP = {current_ip}")

                # 询问是否继续
                response = input("是否继续修复网络规则? (y/N): ").strip().lower()
                if response not in ['y', 'yes']:
                    logger.info("用户选择退出，请先更新配置文件")
                    return False
            else:
                logger.info(f"✅ 配置文件中的IP ({config_ip}) 与当前IP匹配")
        except Exception as e:
            logger.error(f"读取配置文件失败: {e}")
            return False

        # 3. 清理旧的网络规则
        logger.info("步骤 3: 清理旧的网络规则...")
        clear_old_iptables_rules()

        # 4. 重新配置网络
        logger.info("步骤 4: 重新配置网络规则...")
        if network_setup.setup_network():
            logger.info("✅ 网络规则重新配置成功")
        else:
            logger.error("❌ 网络规则重新配置失败")
            return False

        # 5. 等待网络规则生效
        logger.info("等待网络规则生效...")
        import time
        time.sleep(3)

        # 6. 检查容器连接
        logger.info("步骤 5: 检查容器连接状态...")
        check_container_connectivity()

        # 7. 验证端口转发
        logger.info("步骤 6: 验证端口转发规则...")
        verify_port_forwards()

        logger.info("===== 网络修复完成 =====")
        logger.info("建议执行以下操作以确保所有更改生效:")
        logger.info("1. 重启LXD服务: sudo systemctl restart lxd")
        logger.info("2. 重启您的Python应用服务")
        logger.info("3. 运行测试脚本验证: python3 test_container_connectivity.py")

        return True

    except KeyboardInterrupt:
        logger.info("修复过程被用户中断")
        return False
    except Exception as e:
        logger.error(f"修复过程中发生错误: {e}")
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
