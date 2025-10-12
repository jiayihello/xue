-- 流量管理表
CREATE TABLE IF NOT EXISTS container_flow_management (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    hostname VARCHAR(255) NOT NULL UNIQUE,
    created_date DATE NOT NULL,                    -- 容器开通日期
    last_reset_date DATE,                          -- 上次流量重置日期
    next_reset_date DATE NOT NULL,                 -- 下次流量重置日期
    flow_limit_gb INTEGER DEFAULT 0,               -- 流量限制(GB)
    baseline_bytes_received BIGINT DEFAULT 0,      -- 基准接收字节数
    baseline_bytes_sent BIGINT DEFAULT 0,          -- 基准发送字节数
    accumulated_bytes_received BIGINT DEFAULT 0,   -- 累计接收字节数（重启前）
    accumulated_bytes_sent BIGINT DEFAULT 0,       -- 累计发送字节数（重启前）
    current_period_start DATE NOT NULL,            -- 当前计费周期开始日期
    reset_count INTEGER DEFAULT 0,                 -- 重置次数
    auto_reset_enabled BOOLEAN DEFAULT 1,          -- 是否启用自动重置
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 流量重置历史记录表
CREATE TABLE IF NOT EXISTS flow_reset_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    hostname VARCHAR(255) NOT NULL,
    reset_date DATE NOT NULL,
    reset_type VARCHAR(20) NOT NULL,               -- 'auto' 或 'manual'
    old_baseline_received BIGINT DEFAULT 0,
    old_baseline_sent BIGINT DEFAULT 0,
    new_baseline_received BIGINT DEFAULT 0,
    new_baseline_sent BIGINT DEFAULT 0,
    flow_used_gb DECIMAL(10,2) DEFAULT 0,          -- 重置前已使用流量
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 创建索引
CREATE INDEX IF NOT EXISTS idx_hostname ON container_flow_management(hostname);
CREATE INDEX IF NOT EXISTS idx_next_reset_date ON container_flow_management(next_reset_date);
CREATE INDEX IF NOT EXISTS idx_flow_history_hostname ON flow_reset_history(hostname);
CREATE INDEX IF NOT EXISTS idx_flow_history_date ON flow_reset_history(reset_date);
