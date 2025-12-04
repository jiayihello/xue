import os
import re
import time
import threading
from collections import defaultdict
from functools import wraps

from flask import Flask, request, jsonify
import logging
from config_handler import app_config

# hostname 验证正则：允许字母、数字、下划线、连字符，1-63字符，不能以连字符开头
HOSTNAME_PATTERN = re.compile(r'^[a-zA-Z0-9][a-zA-Z0-9_-]{0,62}$')

def validate_hostname(hostname):
    """
    验证 hostname 格式是否合法
    
    Args:
        hostname: 待验证的主机名
        
    Returns:
        (bool, str): (是否合法, 错误信息)
    """
    if not hostname:
        return False, 'hostname 不能为空'
    if not isinstance(hostname, str):
        return False, 'hostname 必须是字符串'
    if len(hostname) > 63:
        return False, 'hostname 长度不能超过63个字符'
    if not HOSTNAME_PATTERN.match(hostname):
        return False, 'hostname 格式无效，只允许字母、数字、下划线和连字符，且不能以连字符开头'
    return True, ''

# === 速率限制（防止暴力破解和滥用）===
class RateLimiter:
    """简单的内存速率限制器"""
    def __init__(self, max_requests: int = 60, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.requests = defaultdict(list)
        self.lock = threading.Lock()
    
    def is_allowed(self, client_ip: str) -> bool:
        """检查请求是否允许"""
        now = time.time()
        with self.lock:
            # 清理过期记录
            self.requests[client_ip] = [
                t for t in self.requests[client_ip] 
                if now - t < self.window_seconds
            ]
            # 检查是否超限
            if len(self.requests[client_ip]) >= self.max_requests:
                return False
            # 记录本次请求
            self.requests[client_ip].append(now)
            return True

# 全局速率限制器：每分钟最多60个请求/IP
rate_limiter = RateLimiter(max_requests=60, window_seconds=60)

from lxc_manager import LXCManager
# 导入网络配置模块
import network_setup
# 导入 Celery 任务
from tasks import (
    start_container_task, stop_container_task, restart_container_task,
    reinstall_container_task, celery_app
)

app = Flask(__name__)

# 配置日志（带轮换，防止无限增长）
from logging.handlers import RotatingFileHandler

log_level = getattr(logging, app_config.log_level, logging.INFO)
log_format = logging.Formatter('%(asctime)s %(levelname)s: %(message)s [%(filename)s:%(lineno)d]',
                               datefmt='%Y-%m-%d %H:%M:%S')

# 控制台输出
console_handler = logging.StreamHandler()
console_handler.setFormatter(log_format)
console_handler.setLevel(log_level)

# 文件输出（轮换：单文件最大10MB，保留5个备份）
file_handler = RotatingFileHandler(
    'lxd_api.log',
    maxBytes=10*1024*1024,  # 10MB
    backupCount=5,
    encoding='utf-8'
)
file_handler.setFormatter(log_format)
file_handler.setLevel(log_level)

# 配置根日志器
logging.basicConfig(level=log_level, handlers=[console_handler, file_handler])
logger = logging.getLogger(__name__)

# 在服务启动时配置网络
if os.geteuid() == 0:  # 检查是否有root权限
    try:
        logger.info("服务启动，正在配置网络规则...")
        network_setup.setup_network()
    except Exception as e:
        logger.error(f"网络配置失败: {e}")
else:
    logger.warning("服务未以root权限运行，无法配置网络规则，容器可能无法联网")
    logger.warning("请使用sudo或root用户运行，或手动运行network_setup.py脚本")

try:
    lxc = LXCManager()
    # 启动阶段尝试修复IPv6(ROUTED)所需的sysctl与NDP代理（若以root运行）
    try:
        if os.geteuid() == 0 and hasattr(lxc, 'reconcile_ipv6_proxy_entries'):
            lxc.reconcile_ipv6_proxy_entries()
    except Exception as e:
        logger.debug(f"启动时IPv6 NDP代理修复失败(可忽略): {e}")
    # 延迟初始化流量管理器
    flow_manager = None

except RuntimeError as e:
    logger.critical(f"无法连接到LXD，程序中止。错误: {e}")
    exit(1)

def get_flow_manager():
    """获取流量管理器实例（延迟初始化）"""
    global flow_manager
    if flow_manager is None:
        try:
            from flow_manager_v2 import FlowManagerV2
            flow_manager = FlowManagerV2()
        except Exception as e:
            logger.warning(f"无法初始化流量管理器: {e}")
            return None
    return flow_manager

# === Authentication for API ===
def api_key_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        client_ip = request.remote_addr
        
        # 速率限制检查
        if not rate_limiter.is_allowed(client_ip):
            logger.warning(f"API请求被速率限制拒绝: {client_ip}")
            return jsonify({'code': 429, 'msg': '请求过于频繁，请稍后再试'}), 429
        
        # API Key 验证
        provided_key = request.headers.get('apikey')
        if provided_key and provided_key == app_config.token:
            return f(*args, **kwargs)
        else:
            logger.warning(f"API认证失败: 无效的API Key from {client_ip}")
            return jsonify({'code': 401, 'msg': '认证失败或API密钥无效'}), 401
    return decorated_function

# === API Routes ===

@app.route('/api/check', methods=['GET'])
@api_key_required
def api_check():
    logger.info(f"API /api/check called successfully from {request.remote_addr}")
    return jsonify({'code': 200, 'msg': 'API连接正常'})

@app.route('/api/getinfo', methods=['GET'])
@api_key_required
def api_getinfo():
    hostname = request.args.get('hostname')
    if not hostname:
        logger.warning("API /api/getinfo 调用缺少 hostname 参数")
        return jsonify({'code': 400, 'msg': '缺少hostname参数'}), 400
    valid, err_msg = validate_hostname(hostname)
    if not valid:
        logger.warning(f"API /api/getinfo hostname 验证失败: {err_msg}")
        return jsonify({'code': 400, 'msg': err_msg}), 400
    logger.info(f"API请求getinfo for: {hostname}")
    return jsonify(lxc.get_container_info(hostname))

@app.route('/api/create', methods=['POST'])
@api_key_required
def api_create():
    """
    创建容器 - 同步执行
    注意：创建操作必须同步执行，因为前端需要获取容器的IP和端口信息来更新数据库
    """
    try:
        payload = request.json
        if not payload or not payload.get('hostname'):
            logger.warning(f"API /api/create 调用请求体无效或缺少hostname")
            return jsonify({'code': 400, 'msg': '无效的请求体或缺少hostname'}), 400
        valid, err_msg = validate_hostname(payload.get('hostname'))
        if not valid:
            logger.warning(f"API /api/create hostname 验证失败: {err_msg}")
            return jsonify({'code': 400, 'msg': err_msg}), 400
        logger.info(f"API请求create for: {payload.get('hostname')}")
        return jsonify(lxc.create_container(payload))
    except Exception as e:
        logger.error(f"处理 /api/create 时发生意外错误: {e}", exc_info=True)
        return jsonify({'code': 500, 'msg': '服务器内部错误'}), 500


@app.route('/api/delete', methods=['GET', 'DELETE'])
@api_key_required
def api_delete():
    hostname = request.args.get('hostname')
    if not hostname:
        logger.warning("API /api/delete 调用缺少 hostname 参数")
        return jsonify({'code': 400, 'msg': '缺少hostname参数'}), 400
    valid, err_msg = validate_hostname(hostname)
    if not valid:
        logger.warning(f"API /api/delete hostname 验证失败: {err_msg}")
        return jsonify({'code': 400, 'msg': err_msg}), 400
    logger.info(f"API请求delete for: {hostname}")
    return jsonify(lxc.delete_container(hostname))

@app.route('/api/boot', methods=['GET'])
@api_key_required
def api_boot():
    hostname = request.args.get('hostname')
    if not hostname:
        logger.warning("API /api/boot 调用缺少 hostname 参数")
        return jsonify({'code': 400, 'msg': '缺少hostname参数'}), 400
    valid, err_msg = validate_hostname(hostname)
    if not valid:
        return jsonify({'code': 400, 'msg': err_msg}), 400
    
    # 异步执行 (Celery)
    try:
        task = start_container_task.delay(hostname)
        logger.info(f"API请求boot for: {hostname}, 已提交异步任务 {task.id}")
        return jsonify({'code': 200, 'msg': '开机指令已发送', 'task_id': task.id})
    except Exception as e:
        logger.error(f"提交异步任务失败: {e}")
        return jsonify({'code': 500, 'msg': f'任务提交失败，请检查Celery服务: {e}'}), 500

@app.route('/api/stop', methods=['GET'])
@api_key_required
def api_stop():
    hostname = request.args.get('hostname')
    if not hostname:
        logger.warning("API /api/stop 调用缺少 hostname 参数")
        return jsonify({'code': 400, 'msg': '缺少hostname参数'}), 400
    valid, err_msg = validate_hostname(hostname)
    if not valid:
        return jsonify({'code': 400, 'msg': err_msg}), 400
    
    # 异步执行 (Celery)
    try:
        task = stop_container_task.delay(hostname)
        logger.info(f"API请求stop for: {hostname}, 已提交异步任务 {task.id}")
        return jsonify({'code': 200, 'msg': '关机指令已发送', 'task_id': task.id})
    except Exception as e:
        logger.error(f"提交异步任务失败: {e}")
        return jsonify({'code': 500, 'msg': f'任务提交失败，请检查Celery服务: {e}'}), 500

@app.route('/api/reboot', methods=['GET'])
@api_key_required
def api_reboot():
    hostname = request.args.get('hostname')
    if not hostname:
        logger.warning("API /api/reboot 调用缺少 hostname 参数")
        return jsonify({'code': 400, 'msg': '缺少hostname参数'}), 400
    valid, err_msg = validate_hostname(hostname)
    if not valid:
        return jsonify({'code': 400, 'msg': err_msg}), 400
    
    # 异步执行 (Celery)
    try:
        task = restart_container_task.delay(hostname)
        logger.info(f"API请求reboot for: {hostname}, 已提交异步任务 {task.id}")
        return jsonify({'code': 200, 'msg': '重启指令已发送', 'task_id': task.id})
    except Exception as e:
        logger.error(f"提交异步任务失败: {e}")
        return jsonify({'code': 500, 'msg': f'任务提交失败，请检查Celery服务: {e}'}), 500

@app.route('/api/password', methods=['POST'])
@api_key_required
def api_password():
    try:
        payload = request.json
        hostname = payload.get('hostname')
        new_pass = payload.get('password')
        if not hostname or not new_pass:
            logger.warning(f"API /api/password 调用缺少hostname或password参数. hostname: {payload.get('hostname') if payload else None}")
            return jsonify({'code': 400, 'msg': '缺少hostname或password参数'}), 400
        logger.info(f"API请求password change for: {hostname}")
        return jsonify(lxc.change_password(hostname, new_pass))
    except Exception as e:
        logger.error(f"处理 /api/password 时发生意外错误: {e}", exc_info=True)
        return jsonify({'code': 500, 'msg': '服务器内部错误'}), 500

@app.route('/api/reinstall', methods=['POST'])
@api_key_required
def api_reinstall():
    try:
        payload = request.json
        hostname = payload.get('hostname')
        new_os = payload.get('system')
        new_password = payload.get('password')
        if not all([hostname, new_os, new_password]):
            logger.warning(f"API /api/reinstall 调用缺少hostname, system或password参数. hostname: {payload.get('hostname') if payload else None}, system: {payload.get('system') if payload else None}")
            return jsonify({'code': 400, 'msg': '缺少hostname, system或password参数'}), 400
        
        # 先检查容器是否存在
        container_info = lxc.get_container_info(hostname)
        if container_info.get('code') == 404:
            return jsonify({'code': 404, 'msg': '容器未找到'}), 404
        
        # 异步执行重装 (Celery)
        try:
            task = reinstall_container_task.delay(hostname, new_os, new_password)
            logger.info(f"API请求reinstall for: {hostname} with OS: {new_os}, 已提交异步任务 {task.id}")
            return jsonify({'code': 200, 'msg': '重装指令已发送，正在后台执行', 'task_id': task.id})
        except Exception as e:
            logger.error(f"提交重装任务失败: {e}")
            return jsonify({'code': 500, 'msg': f'任务提交失败，请检查Celery服务: {e}'}), 500
    except Exception as e:
        logger.error(f"处理 /api/reinstall 时发生意外错误: {e}", exc_info=True)
        return jsonify({'code': 500, 'msg': f'服务器内部错误: {e}'}), 500


@app.route('/api/natlist', methods=['GET'])
@api_key_required
def api_natlist():
    hostname = request.args.get('hostname')
    if not hostname:
        logger.warning("API /api/natlist 调用缺少 hostname 参数")
        return jsonify({'code': 400, 'msg': '缺少hostname参数'}), 400
    logger.info(f"API请求natlist for: {hostname}")
    return jsonify(lxc.list_nat_rules(hostname))

@app.route('/api/addport', methods=['POST'])
@api_key_required
def api_addport():
    hostname_from_form = request.form.get('hostname')
    hostname_from_query = request.args.get('hostname')
    hostname = hostname_from_form or hostname_from_query

    dtype = request.form.get('dtype')
    dport = request.form.get('dport')
    sport = request.form.get('sport')
    remark = request.form.get('remark', '')  # 获取备注参数，默认为空

    if not all([hostname, dtype, dport, sport]):
        logger.warning(f"API /api/addport 调用缺少参数. Hostname: {hostname}, dtype: {dtype}, dport: {dport}, sport: {sport}. Form: {request.form}, Args: {request.args}")
        return jsonify({'code': 400, 'msg': '缺少hostname, dtype, dport, 或 sport参数'}), 400
    logger.info(f"API请求addport for: {hostname}, {dtype}:{dport}->{sport}, 备注: {remark}")
    return jsonify(lxc.add_nat_rule_via_iptables(hostname, dtype, dport, sport, remark))

@app.route('/api/addport/batch', methods=['POST'])
@api_key_required
def api_addport_batch():
    """
    批量添加NAT转发规则 - 性能优化版本
    
    请求体 (JSON):
    {
        "hostname": "container-name",
        "rules": [
            {"dport": 10000, "sport": 8000, "dtype": "tcp"},
            {"dport": 10000, "sport": 8000, "dtype": "udp"},
            {"dport": 10001, "sport": 8001, "dtype": "tcp"},
            ...
        ],
        "remark": "备注信息（可选）"
    }
    
    返回:
    {
        "code": 200/207/403/404/409/500,
        "msg": "批量添加成功！共添加 10 条规则",
        "data": {
            "success": 10,
            "failed": 0,
            "details": [
                {"rule": "TCP 10000->8000", "status": "success"},
                ...
            ]
        }
    }
    """
    try:
        data = request.get_json()
        if not data:
            logger.warning("API /api/addport/batch 调用未提供JSON数据")
            return jsonify({'code': 400, 'msg': '请求体必须是JSON格式'}), 400
        
        hostname = data.get('hostname')
        rules = data.get('rules', [])
        remark = data.get('remark', '')
        
        # 参数验证
        if not hostname:
            logger.warning("API /api/addport/batch 调用缺少hostname参数")
            return jsonify({'code': 400, 'msg': '缺少hostname参数'}), 400
        
        if not rules or not isinstance(rules, list):
            logger.warning(f"API /api/addport/batch 调用rules参数无效: {rules}")
            return jsonify({'code': 400, 'msg': 'rules参数必须是非空数组'}), 400
        
        if len(rules) > 50:  # 安全限制，防止一次性添加过多规则
            logger.warning(f"API /api/addport/batch 调用规则数量过多: {len(rules)}")
            return jsonify({'code': 400, 'msg': f'单次批量添加最多支持50条规则，当前: {len(rules)}条'}), 400
        
        # 验证每条规则的格式
        for idx, rule in enumerate(rules):
            if not isinstance(rule, dict):
                return jsonify({'code': 400, 'msg': f'规则 #{idx+1} 格式错误，必须是对象'}), 400
            if not all(k in rule for k in ['dtype', 'dport', 'sport']):
                return jsonify({'code': 400, 'msg': f'规则 #{idx+1} 缺少必要字段 (dtype, dport, sport)'}), 400
        
        logger.info(f"API批量添加NAT规则: {hostname}, 规则数: {len(rules)}, 备注: {remark}")
        result = lxc.add_nat_rules_batch(hostname, rules, remark)
        
        # 根据返回的code设置HTTP状态码
        http_status = 200
        if result.get('code') == 207:  # Multi-Status
            http_status = 200  # 仍然返回200，但code字段为207表示部分成功
        elif result.get('code') >= 400:
            http_status = result.get('code')
        
        return jsonify(result), http_status
        
    except Exception as e:
        logger.error(f"API /api/addport/batch 发生异常: {e}", exc_info=True)
        return jsonify({'code': 500, 'msg': f'服务器内部错误: {str(e)}'}), 500

@app.route('/api/delport', methods=['POST'])
@api_key_required
def api_delport():
    hostname_from_form = request.form.get('hostname')
    hostname_from_query = request.args.get('hostname')
    hostname = hostname_from_form or hostname_from_query

    dtype = request.form.get('dtype')
    dport = request.form.get('dport')
    sport = request.form.get('sport')

    container_ip_at_creation = request.form.get('container_ip_at_creation', None)

    if not all([hostname, dtype, dport, sport]):
        logger.warning(f"API /api/delport 调用缺少参数. Hostname: {hostname}, dtype: {dtype}, dport: {dport}, sport: {sport}. Form: {request.form}, Args: {request.args}")
        return jsonify({'code': 400, 'msg': '缺少hostname, dtype, dport, 或 sport参数'}), 400
    logger.info(f"API请求delport for: {hostname}, {dtype}:{dport}->{sport}")
    return jsonify(lxc.delete_nat_rule_via_iptables(hostname, dtype, dport, sport, container_ip_at_creation_time=container_ip_at_creation))

# === 流量管理API ===

@app.route('/api/flow/reset', methods=['POST'])
@api_key_required
def api_reset_flow():
    """手动重置容器流量"""
    try:
        flow_mgr = get_flow_manager()
        if not flow_mgr:
            return jsonify({'code': 500, 'msg': '流量管理系统未初始化'}), 500

        payload = request.json
        hostname = payload.get('hostname')
        if not hostname:
            logger.warning("API /api/flow/reset 调用缺少 hostname 参数")
            return jsonify({'code': 400, 'msg': '缺少hostname参数'}), 400

        logger.info(f"API请求重置容器 {hostname} 的流量")

        # 检查容器是否存在
        container_info = lxc.get_container_info(hostname)
        if container_info['code'] != 200:
            return jsonify({'code': 404, 'msg': '容器未找到或无法获取信息'})

        # 使用新系统重置流量（V2 不需要传递字节数，会自动读取 iptables）
        if flow_mgr.reset_container_flow(hostname, reset_type='manual'):
            # 如果容器被封禁，解除封禁
            from iptables_manager import IptablesManager
            iptables_mgr = IptablesManager()
            
            # 检查是否被封禁
            container_usage = flow_mgr.get_container_usage(hostname)
            if container_usage and container_usage.get('is_blocked'):
                iptables_mgr.unblock_container(hostname)
                flow_mgr.set_container_blocked(hostname, False)
                logger.info(f"容器 {hostname} 已解封")
            
            return jsonify({'code': 200, 'msg': '流量重置成功'})
        else:
            return jsonify({'code': 500, 'msg': '流量重置失败'})

    except Exception as e:
        logger.error(f"处理 /api/flow/reset 时发生意外错误: {e}", exc_info=True)
        return jsonify({'code': 500, 'msg': f'服务器内部错误: {e}'}), 500

@app.route('/api/flow/info', methods=['GET'])
@api_key_required
def api_flow_info():
    """获取容器流量管理信息"""
    flow_mgr = get_flow_manager()
    if not flow_mgr:
        return jsonify({'code': 500, 'msg': '流量管理系统未初始化'}), 500

    hostname = request.args.get('hostname')
    if not hostname:
        logger.warning("API /api/flow/info 调用缺少 hostname 参数")
        return jsonify({'code': 400, 'msg': '缺少hostname参数'}), 400

    logger.info(f"API请求获取容器 {hostname} 的流量管理信息")

    # 使用新系统 V2 的 get_container_usage 方法
    flow_info = flow_mgr.get_container_usage(hostname)
    if flow_info:
        # V2 返回的数据结构：
        # {
        #   'hostname': str,
        #   'used_gb': float,
        #   'limit_gb': int,
        #   'is_blocked': bool,
        #   'usage_percent': float,
        #   'next_reset_date': str,
        #   'created_date': str
        # }
        
        # 为了保持API兼容性，添加一些额外字段
        try:
            from iptables_manager import IptablesManager
            iptables_mgr = IptablesManager()
            
            # 获取 iptables 实时统计
            traffic_stats = iptables_mgr.get_traffic_stats(hostname)
            flow_info['current_bytes_received'] = traffic_stats['bytes_received']
            flow_info['current_bytes_sent'] = traffic_stats['bytes_sent']
            flow_info['current_total_bytes'] = traffic_stats['bytes_received'] + traffic_stats['bytes_sent']
            
        except Exception as e:
            logger.error(f"获取容器 {hostname} iptables 统计失败: {e}")
            flow_info['current_bytes_received'] = 0
            flow_info['current_bytes_sent'] = 0
            flow_info['current_total_bytes'] = 0
            flow_info['error'] = f"无法获取 iptables 统计: {e}"

        # 注意：V2 系统没有 get_flow_reset_history 方法
        # 如果需要重置历史，需要直接查询数据库
        try:
            import sqlite3
            with sqlite3.connect(flow_mgr.db_path) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute("""
                    SELECT reset_date, reset_type, flow_used_gb, created_at
                    FROM flow_reset_history_v2
                    WHERE hostname = ?
                    ORDER BY created_at DESC
                    LIMIT 5
                """, (hostname,)).fetchall()
                
                reset_history = []
                for row in rows:
                    reset_history.append({
                        'reset_date': row['reset_date'],
                        'reset_type': row['reset_type'],
                        'flow_used_gb': row['flow_used_gb'],
                        'created_at': row['created_at']
                    })
                flow_info['reset_history'] = reset_history
        except Exception as e:
            logger.error(f"获取重置历史失败: {e}")
            flow_info['reset_history'] = []

        return jsonify({'code': 200, 'msg': '获取成功', 'data': flow_info})
    else:
        return jsonify({'code': 404, 'msg': '容器未在流量管理系统中注册'})


# === CPU 限制管理 API ===

@app.route('/api/cpu/limit/update', methods=['POST'])
@api_key_required
def api_update_cpu_limit():
    """
    更新容器的 CPU 使用率百分比限制
    
    请求体 JSON:
        {
            "hostname": "容器名",
            "cpu_percent": 50  # CPU 使用率百分比，0 表示移除限制
        }
    """
    try:
        payload = request.json
        if not payload:
            return jsonify({'code': 400, 'msg': '无效的请求体'}), 400
        
        hostname = payload.get('hostname')
        cpu_percent = payload.get('cpu_percent')
        
        if not hostname:
            logger.warning("API /api/cpu/limit/update 调用缺少 hostname 参数")
            return jsonify({'code': 400, 'msg': '缺少hostname参数'}), 400
        
        if cpu_percent is None:
            logger.warning("API /api/cpu/limit/update 调用缺少 cpu_percent 参数")
            return jsonify({'code': 400, 'msg': '缺少cpu_percent参数'}), 400
        
        logger.info(f"API请求更新容器 {hostname} CPU 限制为 {cpu_percent}%")
        return jsonify(lxc.update_cpu_limit(hostname, cpu_percent))
        
    except Exception as e:
        logger.error(f"处理 /api/cpu/limit/update 时发生意外错误: {e}", exc_info=True)
        return jsonify({'code': 500, 'msg': f'服务器内部错误: {e}'}), 500


@app.route('/api/cpu/limit/get', methods=['GET'])
@api_key_required
def api_get_cpu_limit():
    """
    获取容器的 CPU 限制信息
    
    参数:
        hostname: 容器名
    """
    try:
        hostname = request.args.get('hostname')
        if not hostname:
            logger.warning("API /api/cpu/limit/get 调用缺少 hostname 参数")
            return jsonify({'code': 400, 'msg': '缺少hostname参数'}), 400
        
        logger.info(f"API请求获取容器 {hostname} CPU 限制信息")
        return jsonify(lxc.get_cpu_limit(hostname))
        
    except Exception as e:
        logger.error(f"处理 /api/cpu/limit/get 时发生意外错误: {e}", exc_info=True)
        return jsonify({'code': 500, 'msg': f'服务器内部错误: {e}'}), 500


@app.route('/api/cpu/limit/batch', methods=['POST'])
@api_key_required
def api_batch_update_cpu_limit():
    """
    批量更新容器的 CPU 限制
    
    请求体 JSON:
        {
            "updates": [
                {"hostname": "容器1", "cpu_percent": 50},
                {"hostname": "容器2", "cpu_percent": 100}
            ]
        }
    """
    try:
        payload = request.json
        if not payload or 'updates' not in payload:
            return jsonify({'code': 400, 'msg': '无效的请求体或缺少updates字段'}), 400
        
        updates = payload.get('updates', [])
        if not isinstance(updates, list):
            return jsonify({'code': 400, 'msg': 'updates 必须是数组'}), 400
        
        logger.info(f"API请求批量更新 {len(updates)} 个容器的 CPU 限制")
        return jsonify(lxc.batch_update_cpu_limit(updates))
        
    except Exception as e:
        logger.error(f"处理 /api/cpu/limit/batch 时发生意外错误: {e}", exc_info=True)
        return jsonify({'code': 500, 'msg': f'服务器内部错误: {e}'}), 500


# === 磁盘 I/O 限制管理 API ===

@app.route('/api/disk/io/update', methods=['POST'])
@api_key_required
def api_update_disk_io_limit():
    """
    更新容器的磁盘 I/O 读写速度限制
    
    请求体 JSON:
        {
            "hostname": "容器名",
            "disk_read": 100,    # 磁盘读取限制 (MB/s)，0 表示移除限制
            "disk_write": 50     # 磁盘写入限制 (MB/s)，0 表示移除限制
        }
    """
    try:
        payload = request.json
        if not payload:
            return jsonify({'code': 400, 'msg': '无效的请求体'}), 400
        
        hostname = payload.get('hostname')
        if not hostname:
            logger.warning("API /api/disk/io/update 调用缺少 hostname 参数")
            return jsonify({'code': 400, 'msg': '缺少hostname参数'}), 400
        
        disk_read = payload.get('disk_read')
        disk_write = payload.get('disk_write')
        
        if disk_read is None and disk_write is None:
            logger.warning("API /api/disk/io/update 调用未指定任何限制参数")
            return jsonify({'code': 400, 'msg': '至少需要指定 disk_read 或 disk_write 参数'}), 400
        
        # 验证 disk_read 参数
        if disk_read is not None:
            try:
                disk_read = int(disk_read)
                if disk_read < 0:
                    return jsonify({'code': 400, 'msg': 'disk_read 必须大于或等于 0'}), 400
                if disk_read > 10000:
                    return jsonify({'code': 400, 'msg': 'disk_read 超出合理范围 (0-10000 MB/s)'}), 400
            except (ValueError, TypeError):
                return jsonify({'code': 400, 'msg': f'disk_read 必须是整数'}), 400
        
        # 验证 disk_write 参数
        if disk_write is not None:
            try:
                disk_write = int(disk_write)
                if disk_write < 0:
                    return jsonify({'code': 400, 'msg': 'disk_write 必须大于或等于 0'}), 400
                if disk_write > 10000:
                    return jsonify({'code': 400, 'msg': 'disk_write 超出合理范围 (0-10000 MB/s)'}), 400
            except (ValueError, TypeError):
                return jsonify({'code': 400, 'msg': f'disk_write 必须是整数'}), 400
        
        logger.info(f"API请求更新容器 {hostname} 磁盘 I/O 限制: 读={disk_read}MB/s, 写={disk_write}MB/s")
        return jsonify(lxc.update_disk_io_limit(hostname, disk_read, disk_write))
        
    except Exception as e:
        logger.error(f"处理 /api/disk/io/update 时发生意外错误: {e}", exc_info=True)
        return jsonify({'code': 500, 'msg': f'服务器内部错误: {e}'}), 500


@app.route('/api/disk/io/get', methods=['GET'])
@api_key_required
def api_get_disk_io_limit():
    """
    获取容器的磁盘 I/O 限制信息
    
    参数:
        hostname: 容器名
    """
    try:
        hostname = request.args.get('hostname')
        if not hostname:
            logger.warning("API /api/disk/io/get 调用缺少 hostname 参数")
            return jsonify({'code': 400, 'msg': '缺少hostname参数'}), 400
        
        logger.info(f"API请求获取容器 {hostname} 磁盘 I/O 限制信息")
        return jsonify(lxc.get_disk_io_limit(hostname))
        
    except Exception as e:
        logger.error(f"处理 /api/disk/io/get 时发生意外错误: {e}", exc_info=True)
        return jsonify({'code': 500, 'msg': f'服务器内部错误: {e}'}), 500


@app.route('/api/internal/cache/invalidate', methods=['POST'])
@api_key_required
def api_invalidate_cache():
    """
    内部API：使NAT元数据缓存失效
    
    用于系统恢复后强制刷新缓存，确保缓存与实际iptables规则同步
    主要在restore_on_boot.py恢复完成后调用
    
    Returns:
        JSON响应
    """
    try:
        from lxc_manager import _metadata_manager
        
        # 使缓存失效
        _metadata_manager.invalidate()
        logger.info("NAT元数据缓存已通过API失效")
        
        return jsonify({
            'code': 200, 
            'msg': '缓存已失效，下次查询将重新加载'
        })
    except Exception as e:
        logger.error(f"缓存失效失败: {e}")
        return jsonify({'code': 500, 'msg': f'缓存失效失败: {str(e)}'}), 500


@app.route('/api/task/status', methods=['GET'])
@api_key_required
def api_task_status():
    """
    查询异步任务状态 (Celery)
    
    参数:
        task_id: 任务ID
    """
    task_id = request.args.get('task_id')
    if not task_id:
        return jsonify({'code': 400, 'msg': '缺少task_id参数'}), 400
    
    # 使用 Celery AsyncResult 查询任务状态
    from celery.result import AsyncResult
    task_result = AsyncResult(task_id, app=celery_app)
    
    # 状态映射
    status_map = {
        'PENDING': 'pending',
        'STARTED': 'running',
        'SUCCESS': 'success',
        'FAILURE': 'failed',
        'RETRY': 'running',
        'REVOKED': 'failed'
    }
    
    task_info = {
        'task_id': task_id,
        'status': status_map.get(task_result.status, task_result.status.lower()),
        'result': None,
        'error': None
    }
    
    if task_result.successful():
        task_info['result'] = task_result.result
    elif task_result.failed():
        task_info['error'] = str(task_result.result)
    
    return jsonify({'code': 200, 'msg': '获取成功', 'data': task_info})


def startup_checks():
    """启动时的检查和初始化"""
    try:
        from lxc_manager import _metadata_manager
        
        # 使NAT元数据缓存失效，确保与恢复后的系统状态同步
        # 这在宿主机重启后非常重要，避免缓存中的数据与实际iptables不一致
        _metadata_manager.invalidate()
        logger.info("✓ 启动检查完成：NAT元数据缓存已失效")
    except Exception as e:
        logger.warning(f"启动检查失败（非致命）: {e}")


if __name__ == '__main__':
    try:
        # 执行启动检查
        startup_checks()
        
        logger.info(f"启动LXD API服务器，监听端口: {app_config.http_port}")
        logger.info("请使用您的TOKEN作为API Key（HTTP Header: apikey）用于外部模块调用。")
        
        # 启动Flask服务
        app.run(host='0.0.0.0', port=app_config.http_port, debug=(app_config.log_level == 'DEBUG'))
    except KeyboardInterrupt:
        logger.info("服务已停止")
    except Exception as e:
        logger.critical(f"服务启动失败: {e}")
        import sys
        sys.exit(1)
