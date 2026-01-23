#!/usr/bin/env python3
"""
PT/BT 刷流智能限速器
监控容器带宽，自动限制高流量容器
"""

import subprocess
import time
import json
import logging
import argparse
from datetime import datetime, timedelta
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# 配置
CONFIG = {
    'check_interval': 30,          # 检查间隔（秒）
    'bandwidth_threshold_mbps': 50, # 带宽阈值（Mbps），超过则限速
    'limit_bandwidth_mbps': 10,     # 限速后的带宽（Mbps）
    'limit_duration_minutes': 30,   # 限速持续时间（分钟）
    'whitelist': [],                # 白名单容器（不限速）
    'state_file': '/tmp/pt_limiter_state.json'
}

class PTLimiter:
    def __init__(self, config):
        self.config = config
        self.state = self.load_state()
        self.last_bytes = {}  # 上次的字节数
        self.last_check_time = None
    
    def load_state(self):
        """加载状态"""
        try:
            with open(self.config['state_file'], 'r') as f:
                return json.load(f)
        except:
            return {'limited_containers': {}}
    
    def save_state(self):
        """保存状态"""
        with open(self.config['state_file'], 'w') as f:
            json.dump(self.state, f, indent=2, default=str)
    
    def run_cmd(self, cmd):
        """执行命令"""
        try:
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
            return result.stdout.strip()
        except Exception as e:
            logger.error(f"命令执行失败: {cmd}, 错误: {e}")
            return ""
    
    def get_container_ips(self):
        """获取所有容器的 IP"""
        containers = {}
        output = self.run_cmd("lxc list -c n,4 --format csv")
        for line in output.split('\n'):
            if not line.strip():
                continue
            parts = line.split(',')
            if len(parts) >= 2:
                name = parts[0].strip()
                # 提取 10.x.x.x 的 IP
                ip_part = parts[1].strip()
                if '10.' in ip_part:
                    for segment in ip_part.split():
                        if segment.startswith('10.'):
                            ip = segment.split('(')[0].strip()
                            containers[ip] = name
                            break
        return containers
    
    def get_iptables_bytes(self):
        """获取 iptables 流量统计"""
        bytes_data = {}
        output = self.run_cmd("iptables -L LXD_FLOW_ACCOUNTING -v -n -x 2>/dev/null")
        for line in output.split('\n'):
            if 'flow-' not in line:
                continue
            parts = line.split()
            if len(parts) >= 8:
                try:
                    bytes_count = int(parts[1])
                    # 找 IP
                    src = parts[7] if len(parts) > 7 else ""
                    dst = parts[8] if len(parts) > 8 else ""
                    
                    ip = None
                    if src.startswith('10.'):
                        ip = src
                    elif dst.startswith('10.'):
                        ip = dst
                    
                    if ip:
                        if ip not in bytes_data:
                            bytes_data[ip] = 0
                        bytes_data[ip] += bytes_count
                except:
                    continue
        return bytes_data
    
    def calculate_bandwidth(self, current_bytes):
        """计算带宽（Mbps）"""
        bandwidth = {}
        now = time.time()
        
        if self.last_check_time and self.last_bytes:
            elapsed = now - self.last_check_time
            if elapsed > 0:
                for ip, bytes_now in current_bytes.items():
                    bytes_before = self.last_bytes.get(ip, bytes_now)
                    diff = bytes_now - bytes_before
                    if diff < 0:  # iptables 规则被重置
                        diff = bytes_now
                    # 转换为 Mbps
                    mbps = (diff * 8) / (elapsed * 1000000)
                    bandwidth[ip] = round(mbps, 2)
        
        self.last_bytes = current_bytes
        self.last_check_time = now
        return bandwidth
    
    def limit_container(self, container_name, limit_mbps):
        """限制容器带宽"""
        limit_bps = f"{limit_mbps}Mbit"
        cmd_ingress = f"lxc config device set {container_name} eth0 limits.ingress={limit_bps}"
        cmd_egress = f"lxc config device set {container_name} eth0 limits.egress={limit_bps}"
        
        self.run_cmd(cmd_ingress)
        self.run_cmd(cmd_egress)
        logger.info(f"✓ 已限制 {container_name} 带宽为 {limit_mbps}Mbps")
    
    def restore_container(self, container_name, original_limit="10000Mbit"):
        """恢复容器带宽"""
        cmd_ingress = f"lxc config device set {container_name} eth0 limits.ingress={original_limit}"
        cmd_egress = f"lxc config device set {container_name} eth0 limits.egress={original_limit}"
        
        self.run_cmd(cmd_ingress)
        self.run_cmd(cmd_egress)
        logger.info(f"✓ 已恢复 {container_name} 带宽限制")
    
    def check_and_restore(self):
        """检查是否有容器需要恢复"""
        now = datetime.now()
        to_remove = []
        
        for container, info in self.state['limited_containers'].items():
            limit_until = datetime.fromisoformat(info['until'])
            if now >= limit_until:
                self.restore_container(container, info.get('original_limit', '10000Mbit'))
                to_remove.append(container)
        
        for container in to_remove:
            del self.state['limited_containers'][container]
        
        if to_remove:
            self.save_state()
    
    def check_containers(self):
        """检查所有容器"""
        container_ips = self.get_container_ips()
        current_bytes = self.get_iptables_bytes()
        bandwidth = self.calculate_bandwidth(current_bytes)
        
        if not bandwidth:
            return
        
        logger.info("--- 容器带宽监控 ---")
        for ip, mbps in sorted(bandwidth.items(), key=lambda x: x[1], reverse=True):
            container = container_ips.get(ip, "unknown")
            status = ""
            
            if container in self.state['limited_containers']:
                status = " [已限速]"
            elif mbps > self.config['bandwidth_threshold_mbps']:
                status = " [超阈值!]"
            
            logger.info(f"  {container} ({ip}): {mbps} Mbps{status}")
            
            # 检查是否需要限速
            if container != "unknown" and container not in self.config['whitelist']:
                if container not in self.state['limited_containers']:
                    if mbps > self.config['bandwidth_threshold_mbps']:
                        # 获取当前限制
                        current_limit = self.run_cmd(
                            f"lxc config device get {container} eth0 limits.ingress"
                        ) or "10000Mbit"
                        
                        # 限速
                        self.limit_container(container, self.config['limit_bandwidth_mbps'])
                        
                        # 记录状态
                        limit_until = datetime.now() + timedelta(
                            minutes=self.config['limit_duration_minutes']
                        )
                        self.state['limited_containers'][container] = {
                            'since': datetime.now().isoformat(),
                            'until': limit_until.isoformat(),
                            'original_limit': current_limit,
                            'triggered_mbps': mbps
                        }
                        self.save_state()
                        logger.warning(
                            f"⚠ {container} 带宽 {mbps}Mbps 超过阈值 "
                            f"{self.config['bandwidth_threshold_mbps']}Mbps，"
                            f"已限速至 {self.config['limit_bandwidth_mbps']}Mbps，"
                            f"将于 {limit_until.strftime('%H:%M:%S')} 恢复"
                        )
    
    def run(self):
        """主循环"""
        logger.info(f"PT 限速器启动")
        logger.info(f"  带宽阈值: {self.config['bandwidth_threshold_mbps']} Mbps")
        logger.info(f"  限速带宽: {self.config['limit_bandwidth_mbps']} Mbps")
        logger.info(f"  限速时长: {self.config['limit_duration_minutes']} 分钟")
        logger.info(f"  检查间隔: {self.config['check_interval']} 秒")
        
        while True:
            try:
                self.check_and_restore()
                self.check_containers()
            except Exception as e:
                logger.error(f"检查出错: {e}")
            
            time.sleep(self.config['check_interval'])


def main():
    parser = argparse.ArgumentParser(description='PT/BT 刷流智能限速器')
    parser.add_argument('--threshold', type=int, default=50,
                        help='带宽阈值 Mbps（默认 50）')
    parser.add_argument('--limit', type=int, default=10,
                        help='限速后带宽 Mbps（默认 10）')
    parser.add_argument('--duration', type=int, default=30,
                        help='限速持续时间（分钟，默认 30）')
    parser.add_argument('--interval', type=int, default=30,
                        help='检查间隔（秒，默认 30）')
    parser.add_argument('--whitelist', type=str, default='',
                        help='白名单容器，逗号分隔')
    parser.add_argument('--once', action='store_true',
                        help='只检查一次，不循环')
    
    args = parser.parse_args()
    
    config = CONFIG.copy()
    config['bandwidth_threshold_mbps'] = args.threshold
    config['limit_bandwidth_mbps'] = args.limit
    config['limit_duration_minutes'] = args.duration
    config['check_interval'] = args.interval
    if args.whitelist:
        config['whitelist'] = [x.strip() for x in args.whitelist.split(',')]
    
    limiter = PTLimiter(config)
    
    if args.once:
        limiter.check_and_restore()
        limiter.check_containers()
        # 等待一个间隔再检查一次以计算带宽
        time.sleep(5)
        limiter.check_containers()
    else:
        limiter.run()


if __name__ == '__main__':
    main()
