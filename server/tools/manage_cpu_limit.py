#!/usr/bin/env python3
"""
容器 CPU 使用率限制管理工具
"""

import sys
import argparse
from lxc_manager import LXCManager

def main():
    parser = argparse.ArgumentParser(
        description='管理 LXD 容器的 CPU 使用率百分比限制',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
示例:
  # 设置单个容器 CPU 限制为 50%
  python3 manage_cpu_limit.py set test-container 50
  
  # 移除 CPU 限制（恢复无限制）
  python3 manage_cpu_limit.py set test-container 0
  
  # 查看容器 CPU 限制
  python3 manage_cpu_limit.py get test-container
  
  # 列出所有容器的 CPU 限制
  python3 manage_cpu_limit.py list
  
  # 批量设置多个容器
  python3 manage_cpu_limit.py batch container1:50 container2:100 container3:150

百分比说明:
  50%  = 0.5 个 CPU 核心
  100% = 1 个完整的 CPU 核心
  200% = 2 个完整的 CPU 核心
  0    = 移除限制（无限制）
        '''
    )
    
    subparsers = parser.add_subparsers(dest='command', help='子命令')
    
    # set 命令
    parser_set = subparsers.add_parser('set', help='设置容器的 CPU 限制')
    parser_set.add_argument('hostname', help='容器名称')
    parser_set.add_argument('cpu_percent', type=int, help='CPU 使用率百分比 (0 表示移除限制)')
    
    # get 命令
    parser_get = subparsers.add_parser('get', help='获取容器的 CPU 限制')
    parser_get.add_argument('hostname', help='容器名称')
    
    # list 命令
    parser_list = subparsers.add_parser('list', help='列出所有容器的 CPU 限制')
    parser_list.add_argument('--filter', help='过滤容器名（部分匹配）')
    
    # batch 命令
    parser_batch = subparsers.add_parser('batch', help='批量设置多个容器的 CPU 限制')
    parser_batch.add_argument('updates', nargs='+', 
                             help='格式: 容器名:百分比 (如 container1:50 container2:100)')
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        sys.exit(1)
    
    # 初始化 LXC 管理器
    try:
        lxc = LXCManager()
    except Exception as e:
        print(f"❌ 无法连接到 LXD: {e}")
        sys.exit(1)
    
    # 执行命令
    if args.command == 'set':
        result = lxc.update_cpu_limit(args.hostname, args.cpu_percent)
        if result['code'] == 200:
            print(f"✅ {result['msg']}")
        else:
            print(f"❌ 错误: {result['msg']}")
            sys.exit(1)
    
    elif args.command == 'get':
        result = lxc.get_cpu_limit(args.hostname)
        if result['code'] == 200:
            data = result['data']
            print(f"\n容器: {args.hostname}")
            print(f"  CPU 核心数: {data['cpu_cores']}")
            print(f"  CPU 使用率限制: {data['cpu_allowance']}")
            if data['cpu_percent']:
                print(f"  百分比: {data['cpu_percent']}%")
        else:
            print(f"❌ 错误: {result['msg']}")
            sys.exit(1)
    
    elif args.command == 'list':
        try:
            all_containers = lxc.client.containers.all()
            
            # 过滤容器
            if args.filter:
                containers = [c for c in all_containers if args.filter.lower() in c.name.lower()]
            else:
                containers = all_containers
            
            if not containers:
                print("没有找到容器")
                return
            
            print(f"\n{'容器名':<20} {'CPU核心':<10} {'CPU限制':<15} {'状态':<10}")
            print("-" * 60)
            
            for container in sorted(containers, key=lambda c: c.name):
                cpu_cores = container.config.get('limits.cpu', '不限')
                cpu_allowance = container.config.get('limits.cpu.allowance', '不限')
                status = container.status
                
                print(f"{container.name:<20} {cpu_cores:<10} {cpu_allowance:<15} {status:<10}")
            
            print(f"\n总计: {len(containers)} 个容器")
            
        except Exception as e:
            print(f"❌ 错误: {e}")
            sys.exit(1)
    
    elif args.command == 'batch':
        updates = []
        for item in args.updates:
            parts = item.split(':')
            if len(parts) != 2:
                print(f"❌ 无效的格式: {item} (应为 容器名:百分比)")
                sys.exit(1)
            
            hostname = parts[0]
            try:
                cpu_percent = int(parts[1])
            except ValueError:
                print(f"❌ 无效的百分比: {parts[1]} (应为整数)")
                sys.exit(1)
            
            updates.append({'hostname': hostname, 'cpu_percent': cpu_percent})
        
        result = lxc.batch_update_cpu_limit(updates)
        
        print(f"\n{result['msg']}\n")
        
        if result['data']['success']:
            print("✅ 成功:")
            for hostname in result['data']['success']:
                print(f"   - {hostname}")
        
        if result['data']['failed']:
            print("\n❌ 失败:")
            for item in result['data']['failed']:
                print(f"   - {item['hostname']}: {item['reason']}")

if __name__ == '__main__':
    main()

