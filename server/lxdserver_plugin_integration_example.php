<?php
/**
 * lxdserver 插件 CPU 限制功能集成示例
 * 
 * 这是一个集成示例，展示如何在 lxdserver 插件中添加 CPU 限制功能
 * 请根据你的实际插件代码进行调整
 */

// ============================================================================
// 示例 1：在创建容器时添加 CPU 限制
// ============================================================================

function lxdserver_CreateAccount($params) {
    // 获取配置参数
    $hostname = $params['domain'];
    $cpu = $params['configoption1'];      // CPU 核心数
    $ram = $params['configoption2'];      // 内存 (MB)
    $disk = $params['configoption3'];     // 磁盘 (MB)
    $cpuPercent = $params['configoption4'] ?? null; // ← 新增：CPU 限制 (%)
    
    // 构建 API 请求数据
    $postData = [
        'hostname' => $hostname,
        'cpu' => $cpu,
        'ram' => $ram,
        'disk' => $disk,
        'system' => $params['configoption5'] ?? 'ubuntu22',
    ];
    
    // 如果设置了 CPU 限制，添加到请求中
    if ($cpuPercent && $cpuPercent > 0) {
        $postData['cpu_percent'] = intval($cpuPercent);
    }
    
    // 调用 LXD API 创建容器
    $result = lxdserver_CallAPI($params, '/api/create', 'POST', $postData);
    
    if ($result['code'] == 200) {
        return 'success';
    } else {
        return $result['msg'] ?? '创建容器失败';
    }
}


// ============================================================================
// 示例 2：添加管理按钮 - 设置 CPU 限制
// ============================================================================

function lxdserver_AdminCustomButtonArray() {
    return [
        "设置 CPU 限制" => "setCPULimit",
        "查看 CPU 限制" => "getCPULimit",
    ];
}

function lxdserver_setCPULimit($params) {
    $hostname = $params['domain'];
    
    // 如果是 POST 请求，执行设置
    if ($_SERVER['REQUEST_METHOD'] === 'POST' && isset($_POST['cpu_percent'])) {
        $cpuPercent = intval($_POST['cpu_percent']);
        
        $result = lxdserver_CallAPI($params, '/api/cpu/limit/update', 'POST', [
            'hostname' => $hostname,
            'cpu_percent' => $cpuPercent
        ]);
        
        if ($result['code'] == 200) {
            return '<div class="alert alert-success">✅ CPU 限制已更新为 ' . $cpuPercent . '%</div>';
        } else {
            return '<div class="alert alert-danger">❌ 更新失败: ' . $result['msg'] . '</div>';
        }
    }
    
    // 显示设置表单
    return '
        <form method="post">
            <div class="form-group">
                <label>CPU 使用率限制 (%)</label>
                <input type="number" name="cpu_percent" class="form-control" 
                       min="0" max="1000" placeholder="0 表示移除限制">
                <small class="form-text text-muted">
                    50% = 0.5核心, 100% = 1核心, 200% = 2核心, 0 = 不限制
                </small>
            </div>
            <button type="submit" class="btn btn-primary">设置</button>
        </form>
    ';
}

function lxdserver_getCPULimit($params) {
    $hostname = $params['domain'];
    
    $result = lxdserver_CallAPI($params, '/api/cpu/limit/get?hostname=' . $hostname, 'GET');
    
    if ($result['code'] == 200) {
        $data = $result['data'];
        return '
            <div class="panel panel-default">
                <div class="panel-heading">CPU 限制信息</div>
                <div class="panel-body">
                    <p><strong>CPU 核心数:</strong> ' . $data['cpu_cores'] . '</p>
                    <p><strong>CPU 使用率限制:</strong> ' . $data['cpu_allowance'] . '</p>
                </div>
            </div>
        ';
    } else {
        return '<div class="alert alert-danger">❌ 获取失败: ' . $result['msg'] . '</div>';
    }
}


// ============================================================================
// 示例 3：批量设置 CPU 限制
// ============================================================================

function lxdserver_AdminServicesTabFields($params) {
    $fields = [];
    
    // 添加 CPU 限制设置字段
    $fields['CPU 限制 (%)'] = '<input type="number" name="lxd_cpu_percent" 
                                      value="' . ($params['customfields']['CPU限制'] ?? '') . '" 
                                      class="form-control" 
                                      placeholder="0 表示不限制">';
    
    return $fields;
}

function lxdserver_AdminServicesTabFieldsSave($params) {
    if (isset($_POST['lxd_cpu_percent'])) {
        $cpuPercent = intval($_POST['lxd_cpu_percent']);
        $hostname = $params['domain'];
        
        // 调用 API 设置 CPU 限制
        lxdserver_CallAPI($params, '/api/cpu/limit/update', 'POST', [
            'hostname' => $hostname,
            'cpu_percent' => $cpuPercent
        ]);
        
        // 保存到自定义字段
        Capsule::table('tblcustomfieldsvalues')
            ->where('fieldid', $params['customfields']['CPU限制_id'])
            ->where('relid', $params['serviceid'])
            ->update(['value' => $cpuPercent]);
    }
}


// ============================================================================
// 示例 4：API 调用辅助函数
// ============================================================================

function lxdserver_CallAPI($params, $endpoint, $method = 'GET', $data = null) {
    $serverip = $params['serverip'];
    $serverport = $params['configoption10'] ?? 5000; // API 端口
    $apikey = $params['serverpassword']; // API Key
    
    $url = "http://{$serverip}:{$serverport}{$endpoint}";
    
    $ch = curl_init();
    curl_setopt($ch, CURLOPT_URL, $url);
    curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
    curl_setopt($ch, CURLOPT_TIMEOUT, 30);
    
    // 设置 API Key
    $headers = [
        'apikey: ' . $apikey,
    ];
    
    if ($method === 'POST' && $data) {
        curl_setopt($ch, CURLOPT_POST, true);
        curl_setopt($ch, CURLOPT_POSTFIELDS, json_encode($data));
        $headers[] = 'Content-Type: application/json';
    }
    
    curl_setopt($ch, CURLOPT_HTTPHEADER, $headers);
    
    $response = curl_exec($ch);
    $httpCode = curl_getinfo($ch, CURLINFO_HTTP_CODE);
    curl_close($ch);
    
    if ($httpCode === 200) {
        return json_decode($response, true);
    } else {
        return [
            'code' => $httpCode,
            'msg' => 'API 调用失败: HTTP ' . $httpCode
        ];
    }
}


// ============================================================================
// WHMCS 产品配置选项定义
// ============================================================================

/**
 * 在 WHMCS 后台 → 产品/服务 → 配置选项 中添加：
 * 
 * 选项 1: CPU 核心数
 *   - 类型: 数量
 *   - 最小值: 1, 最大值: 16
 * 
 * 选项 2: 内存 (MB)
 *   - 类型: 数量
 *   - 最小值: 512, 最大值: 32768
 * 
 * 选项 3: 磁盘 (MB)
 *   - 类型: 数量
 *   - 最小值: 10240, 最大值: 1048576
 * 
 * 选项 4: CPU 使用率限制 (%) ← 新增
 *   - 类型: 下拉菜单
 *   - 选项:
 *     - 不限制 (0)
 *     - 25% (25)
 *     - 50% (50)
 *     - 75% (75)
 *     - 100% (100)
 *     - 150% (150)
 *     - 200% (200)
 *     - 300% (300)
 *     - 400% (400)
 * 
 * 选项 5: 操作系统
 *   - 类型: 下拉菜单
 *   - 选项: ubuntu22, ubuntu20, debian11, etc.
 */


// ============================================================================
// 高级示例：根据套餐自动设置 CPU 限制
// ============================================================================

function lxdserver_CreateAccount_Advanced($params) {
    $hostname = $params['domain'];
    $productId = $params['pid'];
    
    // 基础配置
    $postData = [
        'hostname' => $hostname,
        'cpu' => $params['configoption1'],
        'ram' => $params['configoption2'],
        'disk' => $params['configoption3'],
    ];
    
    // 根据产品 ID 自动设置 CPU 限制
    $cpuLimitMap = [
        1 => 50,   // 基础套餐: 50%
        2 => 100,  // 标准套餐: 100%
        3 => 200,  // 高级套餐: 200%
        4 => 0,    // VIP 套餐: 不限制
    ];
    
    if (isset($cpuLimitMap[$productId])) {
        $cpuLimit = $cpuLimitMap[$productId];
        if ($cpuLimit > 0) {
            $postData['cpu_percent'] = $cpuLimit;
        }
    }
    
    // 如果用户在配置选项中指定了 CPU 限制，优先使用用户设置
    if (!empty($params['configoption4'])) {
        $postData['cpu_percent'] = intval($params['configoption4']);
    }
    
    $result = lxdserver_CallAPI($params, '/api/create', 'POST', $postData);
    
    return ($result['code'] == 200) ? 'success' : $result['msg'];
}


// ============================================================================
// 客户端区域显示 CPU 限制信息
// ============================================================================

function lxdserver_ClientAreaCustomButtonArray() {
    return [
        "查看资源限制" => "viewLimits",
    ];
}

function lxdserver_viewLimits($params) {
    $hostname = $params['domain'];
    
    // 获取 CPU 限制
    $cpuResult = lxdserver_CallAPI($params, '/api/cpu/limit/get?hostname=' . $hostname, 'GET');
    
    // 获取容器信息
    $infoResult = lxdserver_CallAPI($params, '/api/info?hostname=' . $hostname, 'GET');
    
    $html = '<div class="panel panel-default">';
    $html .= '<div class="panel-heading">资源限制信息</div>';
    $html .= '<div class="panel-body">';
    
    if ($cpuResult['code'] == 200) {
        $html .= '<h4>CPU 限制</h4>';
        $html .= '<p><strong>CPU 核心数:</strong> ' . $cpuResult['data']['cpu_cores'] . '</p>';
        $html .= '<p><strong>CPU 使用率限制:</strong> ' . $cpuResult['data']['cpu_allowance'] . '</p>';
    }
    
    if ($infoResult['code'] == 200) {
        $info = $infoResult['data'];
        $html .= '<h4>其他资源</h4>';
        $html .= '<p><strong>内存限制:</strong> ' . ($info['memory_limit'] ?? 'N/A') . ' MB</p>';
        $html .= '<p><strong>磁盘限制:</strong> ' . ($info['disk_limit'] ?? 'N/A') . ' MB</p>';
    }
    
    $html .= '</div></div>';
    
    return $html;
}

?>

