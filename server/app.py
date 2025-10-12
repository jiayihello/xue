import os
from flask import Flask, render_template, jsonify, request, session, redirect, url_for
from functools import wraps
import logging
import datetime
from math import ceil

from config_handler import app_config
from lxc_manager import LXCManager, _load_iptables_rules_metadata
from flow_manager import FlowManager
# 导入网络配置模块
import network_setup

app = Flask(__name__, template_folder='templates', static_folder='static')
app.secret_key = os.urandom(24)

logging.basicConfig(level=getattr(logging, app_config.log_level, logging.INFO),
                    format='%(asctime)s %(levelname)s: %(message)s [%(filename)s:%(lineno)d]',
                    datefmt='%Y-%m-%d %H:%M:%S')
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
            from flow_manager import FlowManager
            flow_manager = FlowManager()
        except Exception as e:
            logger.warning(f"无法初始化流量管理器: {e}")
            return None
    return flow_manager

# === Authentication for Web UI ===
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'logged_in' not in session:
            return redirect(url_for('login', next=request.url))
        return f(*args, **kwargs)
    return decorated_function

# === Authentication for external API (lxdserver.php) ===
def api_key_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        provided_key = request.headers.get('apikey')
        if provided_key and provided_key == app_config.token:
            return f(*args, **kwargs)
        else:
            logger.warning(f"API认证失败: 无效的API Key from {request.remote_addr}.提供的Key: '{provided_key}'")
            return jsonify({'code': 401, 'msg': '认证失败或API密钥无效'}), 401
    return decorated_function

def adapt_response(lxd_response, success_status='success', error_status='error'):
    if lxd_response.get('code') == 200:
        return {'status': success_status, 'message': lxd_response.get('msg', '操作成功')}
    else:
        return {'status': error_status, 'message': lxd_response.get('msg', '操作失败')}

# === Routes for Web UI ===

@app.route('/login', methods=['GET', 'POST'])
def login():
    template_context = {
        'session': session,
        'incus_error': (False, None),
        'image_error': (False, None),
        'storage_error': (False, None),
        'containers': [],
        'images': [],
        'available_pools': [],
        'login_error': None,
        'pagination': {}
    }

    if request.method == 'POST':
        if request.form.get('password') == app_config.token:
            session['logged_in'] = True
            next_url = request.args.get('next')
            return redirect(next_url or url_for('index'))
        else:
            template_context['login_error'] = "密码错误"
            return render_template('index.html', **template_context)
            
    return render_template('index.html', **template_context)

@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    return redirect(url_for('login'))

@app.route('/')
@login_required
def index():
    incus_error = (False, None)
    containers_list = []
    try:
        fingerprint_to_alias_map = {}
        all_images_for_map = lxc.client.images.all()
        for img in all_images_for_map:
            if img.aliases:
                fingerprint_to_alias_map[img.fingerprint] = img.aliases[0]['name']

        all_containers = lxc.client.containers.all()
        for c in all_containers:
            info_res = lxc.get_container_info(c.name)
            data = info_res.get('data', {})

            container_fingerprint = c.config.get('volatile.base_image')
            image_source = "N/A"
            if container_fingerprint:
                image_source = fingerprint_to_alias_map.get(
                    container_fingerprint,
                    c.config.get('image.description', container_fingerprint)
                )
            else:
                image_source = c.config.get('image.description', 'N/A')
            
            created_at_val = c.created_at
            if isinstance(created_at_val, datetime.datetime):
                created_at_str = created_at_val.isoformat()
            else:
                created_at_str = str(created_at_val) if created_at_val else 'N/A'

            containers_list.append({
                'name': c.name,
                'status': c.status,
                'ip': data.get('PublicIPv4', data.get('IP', 'N/A')),
                'ipv6_list': data.get('IPv6List', []),
                'public_ipv4': data.get('PublicIPv4', None),
                'public_ssh_port': data.get('PublicSSHPort', None),
                'image_source': image_source,
                'created_at': created_at_str,
                'cpu_usage': data.get('UsedCPU', '-'),
                'mem_usage': data.get('UsedRam', '-'),
                'disk_usage': data.get('UsedDisk', '-'),
                'total_flow': data.get('UseBandwidth_GB', '-'),
                'mem_total': data.get('TotalRam', 0),
                'disk_total': data.get('TotalDisk', 0),
                'flow_limit': data.get('Bandwidth', 0)
            })
    except Exception as e:
        logger.error(f"获取容器列表失败: {e}", exc_info=True)
        incus_error = (True, str(e))

    page = request.args.get('page', 1, type=int)
    allowed_per_page = [20, 50, 100]
    per_page = request.args.get('per_page', 20, type=int)
    if per_page not in allowed_per_page:
        per_page = 20

    total_items = len(containers_list)
    total_pages = ceil(total_items / per_page)
    start = (page - 1) * per_page
    end = start + per_page
    paginated_containers = sorted(containers_list, key=lambda x: x['name'])[start:end]


    image_error = (False, None)
    available_images = []
    try:
        all_images = lxc.client.images.all()
        for img in all_images:
            if not img.aliases: continue
            alias_name = img.aliases[0]['name']
            desc = img.properties.get('description', '无描述')
            available_images.append({'name': alias_name, 'description': f"{alias_name} ({desc})"})
    except Exception as e:
        logger.error(f"获取镜像列表失败: {e}")
        image_error = (True, str(e))

    storage_error = (False, None)
    available_pools = []
    try:
        all_pools = lxc.client.storage_pools.all()
        available_pools = [p.name for p in all_pools]
    except Exception as e:
        logger.error(f"获取存储池列表失败: {e}")
        storage_error = (True, str(e))

    pagination_details = {
        'page': page,
        'per_page': per_page,
        'total_pages': total_pages,
        'total_items': total_items,
        'allowed_per_page': allowed_per_page
    }

    return render_template('index.html',
                           containers=paginated_containers,
                           images=available_images,
                           available_pools=available_pools,
                           incus_error=incus_error,
                           image_error=image_error,
                           storage_error=storage_error,
                           pagination=pagination_details,
                           session=session)

@app.route('/container/<name>/action', methods=['POST'])
@login_required
def container_action(name):
    action = request.form.get('action')
    logger.info(f"WebUI请求对 {name} 执行操作: {action}")
    if action == 'start':
        result = lxc.start_container(name)
    elif action == 'stop':
        result = lxc.stop_container(name)
    elif action == 'restart':
        result = lxc.restart_container(name)
    elif action == 'delete':
        result = lxc.delete_container(name)
    else:
        result = {'code': 400, 'msg': '无效操作'}
    return jsonify(adapt_response(result))

@app.route('/container/<name>/info')
@login_required
def container_info(name):
    logger.info(f"WebUI请求获取 {name} 的信息")
    res = lxc.get_container_info(name)
    if res['code'] != 200:
        return jsonify({'status': 'NotFound', 'message': res['msg']}), 404

    lxc_data = res.get('data', {})
    raw_data = lxc_data.get('raw_lxd_info', {})
    adapted_info = {
        'name': raw_data.get('name'),
        'status': raw_data.get('status'),
        'status_code': raw_data.get('status_code'),
        'type': raw_data.get('type'),
        'architecture': raw_data.get('architecture'),
        'ephemeral': raw_data.get('ephemeral'),
        'created_at': raw_data.get('created_at'),
        'profiles': raw_data.get('profiles', []),
        'config': raw_data.get('config', {}),
        'devices': raw_data.get('devices', {}),
        'state': raw_data.get('state', {}),
        'image_source': lxc_data.get('ImageSourceAlias'),
        'description': raw_data.get('description'),
        'ip': lxc_data.get('PublicIPv4', lxc_data.get('IP')),
        'ipv6_list': lxc_data.get('IPv6List', []),
        'public_ipv4': lxc_data.get('PublicIPv4'),
        'public_ssh_port': lxc_data.get('PublicSSHPort'),
        'total_ram_mb': lxc_data.get('TotalRam', 0),
        'total_disk_mb': lxc_data.get('TotalDisk', 0),
        'flow_limit_gb': lxc_data.get('Bandwidth', 0),
        'live_data_available': raw_data.get('status') == 'Running',
        'message': '数据来自LXD实时信息'
    }
    return jsonify(adapted_info)

@app.route('/container/<name>/stats')
@login_required
def container_stats(name):
    logger.debug(f"WebUI请求获取 {name} 的实时状态")
    res = lxc.get_container_realtime_stats(name)
    if res['code'] != 200:
        return jsonify({'status': 'error', 'message': res['msg']}), res.get('code', 500)
    return jsonify(res['data'])

@app.route('/container/<name>/nat_rules', methods=['GET'])
@login_required
def list_nat_rules(name):
    logger.info(f"WebUI请求获取 {name} 的端口转发规则")
    res = lxc.list_nat_rules(name)
    if res['code'] != 200:
        return jsonify({'status': 'error', 'message': res['msg']}), 500

    adapted_rules = []
    for rule in res.get('data', []):
        adapted_rules.append({
            'id': rule.get('ID'),
            'host_port': rule.get('Dport'),
            'container_port': rule.get('Sport'),
            'protocol': rule.get('Dtype').lower(),
            'ip_at_creation': 'N/A',
            'created_at': datetime.datetime.now().isoformat()
        })
    return jsonify({'status': 'success', 'rules': adapted_rules})

@app.route('/container/nat_rule/<rule_id>', methods=['DELETE'])
@login_required
def delete_nat_rule(rule_id):
    logger.info(f"WebUI请求删除端口转发规则ID: {rule_id}")
    rules_metadata = _load_iptables_rules_metadata()
    rule_to_delete = next((rule for rule in rules_metadata if rule.get('rule_id') == rule_id), None)

    if not rule_to_delete:
        return jsonify({'status': 'error', 'message': '未在元数据中找到该规则ID'}), 404

    hostname = rule_to_delete.get('hostname')
    dtype = rule_to_delete.get('dtype')
    dport = rule_to_delete.get('dport')
    sport = rule_to_delete.get('sport')
    ip_at_creation = rule_to_delete.get('container_ip')

    result = lxc.delete_nat_rule_via_iptables(hostname, dtype, dport, sport, ip_at_creation)
    return jsonify(adapt_response(result))

# === Routes for External API (lxdserver.php) ===

@app.route('/api/check', methods=['GET'])
@api_key_required
def api_check():
    logger.info(f"API /api/check a called successfully from {request.remote_addr}")
    return jsonify({'code': 200, 'msg': 'API连接正常'})

@app.route('/api/getinfo', methods=['GET'])
@api_key_required
def api_getinfo():
    hostname = request.args.get('hostname')
    if not hostname:
        logger.warning("API /api/getinfo 调用缺少 hostname 参数")
        return jsonify({'code': 400, 'msg': '缺少hostname参数'}), 400
    logger.info(f"API请求getinfo for: {hostname}")
    return jsonify(lxc.get_container_info(hostname))

@app.route('/api/create', methods=['POST'])
@api_key_required
def api_create():
    try:
        payload = request.json
        if not payload or not payload.get('hostname'):
            logger.warning(f"API /api/create 调用请求体无效或缺少hostname. Payload: {payload}")
            return jsonify({'code': 400, 'msg': '无效的请求体或缺少hostname'}), 400
        logger.info(f"API请求create for: {payload.get('hostname')}")
        return jsonify(lxc.create_container(payload))
    except Exception as e:
        logger.error(f"处理 /api/create 时发生意外错误: {e}", exc_info=True)
        return jsonify({'code': 500, 'msg': '服务器内部错误'}), 500


@app.route('/api/delete', methods=['GET'])
@api_key_required
def api_delete():
    hostname = request.args.get('hostname')
    if not hostname:
        logger.warning("API /api/delete 调用缺少 hostname 参数")
        return jsonify({'code': 400, 'msg': '缺少hostname参数'}), 400
    logger.info(f"API请求delete for: {hostname}")
    return jsonify(lxc.delete_container(hostname))

@app.route('/api/boot', methods=['GET'])
@api_key_required
def api_boot():
    hostname = request.args.get('hostname')
    if not hostname:
        logger.warning("API /api/boot 调用缺少 hostname 参数")
        return jsonify({'code': 400, 'msg': '缺少hostname参数'}), 400
    logger.info(f"API请求boot for: {hostname}")
    return jsonify(lxc.start_container(hostname))

@app.route('/api/stop', methods=['GET'])
@api_key_required
def api_stop():
    hostname = request.args.get('hostname')
    if not hostname:
        logger.warning("API /api/stop 调用缺少 hostname 参数")
        return jsonify({'code': 400, 'msg': '缺少hostname参数'}), 400
    logger.info(f"API请求stop for: {hostname}")
    return jsonify(lxc.stop_container(hostname))

@app.route('/api/reboot', methods=['GET'])
@api_key_required
def api_reboot():
    hostname = request.args.get('hostname')
    if not hostname:
        logger.warning("API /api/reboot 调用缺少 hostname 参数")
        return jsonify({'code': 400, 'msg': '缺少hostname参数'}), 400
    logger.info(f"API请求reboot for: {hostname}")
    return jsonify(lxc.restart_container(hostname))

@app.route('/api/password', methods=['POST'])
@api_key_required
def api_password():
    try:
        payload = request.json
        hostname = payload.get('hostname')
        new_pass = payload.get('password')
        if not hostname or not new_pass:
            logger.warning(f"API /api/password 调用缺少hostname或password参数. Payload: {payload}")
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
            logger.warning(f"API /api/reinstall 调用缺少hostname, system或password参数. Payload: {payload}")
            return jsonify({'code': 400, 'msg': '缺少hostname, system或password参数'}), 400
        logger.info(f"API请求reinstall for: {hostname} with OS: {new_os}")
        return jsonify(lxc.reinstall_container(hostname, new_os, new_password))
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

    if not all([hostname, dtype, dport, sport]):
        logger.warning(f"API /api/addport 调用缺少参数. Hostname: {hostname}, dtype: {dtype}, dport: {dport}, sport: {sport}. Form: {request.form}, Args: {request.args}")
        return jsonify({'code': 400, 'msg': '缺少hostname, dtype, dport, 或 sport参数'}), 400
    logger.info(f"API请求addport for: {hostname}, {dtype}:{dport}->{sport}")
    return jsonify(lxc.add_nat_rule_via_iptables(hostname, dtype, dport, sport))

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

        # 获取容器当前流量统计
        container_info = lxc.get_container_info(hostname)
        if container_info['code'] != 200:
            return jsonify({'code': 404, 'msg': '容器未找到或无法获取信息'})

        # 获取LXD容器对象以读取网络统计
        container = lxc._get_container_or_error(hostname)
        if not container:
            return jsonify({'code': 404, 'msg': '容器不存在'})

        # 获取当前网络统计
        state = container.state()
        current_bytes_received = 0
        current_bytes_sent = 0

        if state.network:
            for nic_name, nic_data in state.network.items():
                if 'counters' in nic_data:
                    current_bytes_received += nic_data['counters'].get('bytes_received', 0)
                    current_bytes_sent += nic_data['counters'].get('bytes_sent', 0)

        # 执行流量重置
        if flow_mgr.reset_container_flow(
            hostname,
            current_bytes_received,
            current_bytes_sent,
            reset_type='manual'
        ):
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

    flow_info = flow_mgr.get_container_flow_info(hostname)
    if flow_info:
        # 获取容器当前流量统计
        try:
            container = lxc._get_container_or_error(hostname)
            if container:
                state = container.state()
                current_bytes_received = 0
                current_bytes_sent = 0

                if state.network:
                    for nic_name, nic_data in state.network.items():
                        if 'counters' in nic_data:
                            current_bytes_received += nic_data['counters'].get('bytes_received', 0)
                            current_bytes_sent += nic_data['counters'].get('bytes_sent', 0)

                # 计算当前周期使用量
                current_usage_gb = flow_mgr.calculate_current_period_usage(
                    hostname, current_bytes_received, current_bytes_sent
                )

                # 添加实时流量信息
                flow_info['current_bytes_received'] = current_bytes_received
                flow_info['current_bytes_sent'] = current_bytes_sent
                flow_info['current_usage_gb'] = current_usage_gb
                flow_info['current_total_bytes'] = current_bytes_received + current_bytes_sent

        except Exception as e:
            logger.error(f"获取容器 {hostname} 当前流量统计失败: {e}")
            flow_info['current_usage_gb'] = 0
            flow_info['error'] = f"无法获取当前流量: {e}"

        # 获取重置历史
        reset_history = flow_mgr.get_flow_reset_history(hostname, 5)
        flow_info['reset_history'] = reset_history
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


if __name__ == '__main__':
    logger.info(f"启动LXD网页管理器，监听端口: {app_config.http_port}")
    logger.info("请使用您的TOKEN作为密码登录WebUI，或作为API Key用于外部模块调用。")
    app.run(host='0.0.0.0', port=app_config.http_port, debug=(app_config.log_level == 'DEBUG'))