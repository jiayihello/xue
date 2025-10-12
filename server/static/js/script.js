let captchaAnswer = 0;

function generateCaptcha() {
    const num1 = Math.ceil(Math.random() * 9) + 1;
    const num2 = Math.ceil(Math.random() * 9) + 1;
    captchaAnswer = num1 + num2;
    const captchaQuestionEl = document.getElementById('captchaQuestion');
    if (captchaQuestionEl) {
        captchaQuestionEl.innerText = `${num1} + ${num2} = ?`;
    }
    const captchaInputEl = document.getElementById('captchaInput');
    if (captchaInputEl) {
        captchaInputEl.value = '';
    }
}

document.addEventListener('DOMContentLoaded', function() {
    // Per-page selector for pagination
    const perPageSelect = document.getElementById('perPageSelect');
    if (perPageSelect) {
        perPageSelect.addEventListener('change', function() {
            const perPage = this.value;
            const url = new URL(window.location.href);
            url.searchParams.set('per_page', perPage);
            url.searchParams.set('page', '1'); // Reset to page 1 when changing items per page
            window.location.href = url.toString();
        });
    }

    // Search functionality
    const searchInput = document.getElementById('searchInput');
    if (searchInput) {
        searchInput.addEventListener('keyup', function(e) {
            const searchTerm = e.target.value.toLowerCase();
            const desktopRows = document.querySelectorAll('#containerListDesktopItems .custom-container-list-row');
            desktopRows.forEach(row => {
                const containerName = row.dataset.containerName.toLowerCase();
                if (containerName.includes(searchTerm)) {
                    row.style.display = 'flex';
                } else {
                    row.style.display = 'none';
                }
            });
            const mobileCards = document.querySelectorAll('.container-list-mobile .card');
            mobileCards.forEach(card => {
                const containerName = card.dataset.containerName.toLowerCase();
                if (containerName.includes(searchTerm)) {
                    card.style.display = 'block';
                } else {
                    card.style.display = 'none';
                }
            });
        });
    }

    // Sorting functionality
    const headers = document.querySelectorAll('.custom-container-list-header .sortable');
    headers.forEach(header => {
        header.addEventListener('click', function() {
            const sortColumn = this.dataset.sort;
            const currentOrder = this.dataset.order || 'desc';
            const newOrder = currentOrder === 'desc' ? 'asc' : 'desc';
            this.dataset.order = newOrder;

            headers.forEach(h => {
                h.classList.remove('sorted');
                h.querySelector('.sort-icon').classList.remove('asc', 'desc');
            });

            this.classList.add('sorted');
            this.querySelector('.sort-icon').classList.add(newOrder);

            sortTable(sortColumn, newOrder);
        });
    });


    if (document.getElementById('loginForm')) {
        generateCaptcha();
        const refreshButton = document.getElementById('refreshCaptchaBtn');
        if(refreshButton) {
            refreshButton.addEventListener('click', generateCaptcha);
        }

        const loginForm = document.getElementById('loginForm');
        loginForm.addEventListener('submit', function(event) {
            const userAnswer = parseInt(document.getElementById('captchaInput').value, 10);
            if (userAnswer !== captchaAnswer) {
                event.preventDefault();
                showToast('验证码错误，请重试。', 'danger');
                generateCaptcha();
            }
        });
    }

    if (document.getElementById('containerListDesktopItems')) {
        const containersToMonitor = [];
        document.querySelectorAll('[data-container-name]').forEach(el => {
            const containerName = el.dataset.containerName;
            const containerStatus = el.dataset.containerStatus;
            if (containerStatus === 'Running' && !containersToMonitor.includes(containerName)) {
                containersToMonitor.push(containerName);
            }
        });

        function updateAllContainerStats() {
            if (document.hidden) {
                return;
            }
            containersToMonitor.forEach(name => {
                $.ajax({
                    url: `/container/${name}/stats`,
                    type: 'GET',
                    success: function(stats) {
                        $(`#cpu-${name}`).text(stats.cpu_usage_percent);
                        $(`#mem-${name}`).text(stats.memory_usage_mb);
                        $(`#disk-${name}`).text(stats.disk_usage_mb);
                        $(`#flow-${name}`).text(stats.total_flow_used_gb);
                        $(`#rx-${name}`).text(stats.network_rx_kbps);
                        $(`#tx-${name}`).text(stats.network_tx_kbps);

                        $(`#cpu-mobile-${name}`).text(stats.cpu_usage_percent);
                        $(`#mem-mobile-${name}`).text(stats.memory_usage_mb);
                        $(`#disk-mobile-${name}`).text(stats.disk_usage_mb);
                        $(`#flow-mobile-${name}`).text(stats.total_flow_used_gb);
                        $(`#rx-mobile-${name}`).text(stats.network_rx_kbps);
                        $(`#tx-mobile-${name}`).text(stats.network_tx_kbps);
                    },
                    error: function(jqXHR) {
                        console.error(`获取容器 ${name} 状态失败:`, jqXHR.responseJSON?.message || '未知错误');
                        const index = containersToMonitor.indexOf(name);
                        if (index > -1) {
                           containersToMonitor.splice(index, 1);
                        }
                    }
                });
            });
        }

        if (containersToMonitor.length > 0) {
            updateAllContainerStats();
            setInterval(updateAllContainerStats, 2500);
        }
    }
});

function sortTable(column, order) {
    const list = document.getElementById('containerListDesktopItems');
    const rows = Array.from(list.querySelectorAll('.custom-container-list-row'));

    const getSortValue = (row, col) => {
        const cell = row.querySelector(`.col-${col} strong`) || row.querySelector(`.col-${col}`);
        let textValue = 'N/A';
        if (cell) {
             textValue = (cell.tagName === 'STRONG' ? cell.innerText : cell.textContent).trim();
        }
        if (textValue === 'N/A' || textValue === '-') {
            return -1; // Treat N/A as a very low value to group them
        }
        const numericValue = parseFloat(textValue);
        return isNaN(numericValue) ? -1 : numericValue;
    };

    rows.sort((a, b) => {
        const valA = getSortValue(a, column);
        const valB = getSortValue(b, column);

        if (order === 'asc') {
            return valA - valB;
        } else {
            return valB - valA;
        }
    });

    // Re-append sorted rows
    rows.forEach(row => list.appendChild(row));
}

function showToast(message, type = 'info') {
    let toastType = 'info';
    if (type === 'success') {
        toastType = 'success';
    } else if (type === 'error' || type === 'danger') {
        toastType = 'danger';
    } else if (type === 'warning') {
        toastType = 'warning';
    }
    const toastContainer = $('#toastContainer');
    const toastHtml = `
        <div class="toast align-items-center text-bg-${toastType} border-0" role="alert" aria-live="assertive" aria-atomic="true">
            <div class="d-flex">
                <div class="toast-body"></div>
                <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast" aria-label="Close"></button>
            </div>
        </div>
    `;
    const toastElement = $(toastHtml);
    // Use .text() to safely insert the message
    $('.toast-body', toastElement).text(message);
    toastContainer.append(toastElement);

    const toast = new bootstrap.Toast(toastElement[0]);
    toast.show();
    toastElement.on('hidden.bs.toast', function () {
        $(this).remove();
    });
}


function setButtonProcessing(button, isProcessing) {
    const $button = $(button);
    if (!$button.length) {
        return;
    }
    if (isProcessing) {
        if (!$button.data('original-html')) {
            $button.data('original-html', $button.html());
            const originalText = $button.text().trim();
            const spinnerHtml = '<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span>';
            $button.html(spinnerHtml + (originalText ? ' 处理中...' : ''));
            $button.addClass('btn-processing').prop('disabled', true);
        }
    } else {
        if ($button.data('original-html')) {
             $button.html($button.data('original-html'));
             $button.data('original-html', null);
             $button.removeClass('btn-processing').prop('disabled', false);
        } else {
             $button.removeClass('btn-processing').prop('disabled', false);
        }
    }
}

let currentConfirmAction = null;
let currentConfirmContainerName = null;
let currentConfirmRuleId = null;
let currentConfirmButtonElement = null;

function showConfirmationModal(actionType, nameOrId, buttonElement) {
    currentConfirmAction = actionType;
    currentConfirmButtonElement = buttonElement;
    const modalTitle = $('#confirmModalLabel');
    const modalBody = $('#confirmModalBody');
    const confirmButton = $('#confirmActionButton');
    let message = '';
    let buttonClass = 'btn-primary';
    let buttonText = '确认';

    // Clear previous content and set a safe base structure
    modalBody.empty();

    if (actionType === 'start_container') {
        currentConfirmContainerName = nameOrId;
        currentConfirmRuleId = null;
        modalTitle.text('确认启动');
        message = '确定要启动容器 ';
        buttonClass = 'btn-success';
        buttonText = '启动';
        modalBody.append(document.createTextNode(message))
                 .append($('<strong>').text(nameOrId))
                 .append(document.createTextNode(' 吗？'));
    } else if (actionType === 'stop_container') {
        currentConfirmContainerName = nameOrId;
        currentConfirmRuleId = null;
        modalTitle.text('确认停止');
        message = '确定要停止容器 ';
        buttonClass = 'btn-warning';
        buttonText = '停止';
        modalBody.append(document.createTextNode(message))
                 .append($('<strong>').text(nameOrId))
                 .append(document.createTextNode(' 吗？'));
    } else if (actionType === 'restart_container') {
        currentConfirmContainerName = nameOrId;
        currentConfirmRuleId = null;
        modalTitle.text('确认重启');
        message = '确定要重启容器 ';
        buttonClass = 'btn-warning';
        buttonText = '重启';
        modalBody.append(document.createTextNode(message))
                 .append($('<strong>').text(nameOrId))
                 .append(document.createTextNode(' 吗？'));
    } else if (actionType === 'delete_container') {
        currentConfirmContainerName = nameOrId;
        currentConfirmRuleId = null;
        modalTitle.text('确认删除容器');
        modalBody.append($('<strong>').text('警告：'))
                 .append(document.createTextNode(' 这将永久删除容器 '))
                 .append($('<strong>').text(nameOrId))
                 .append(document.createTextNode(' 及其所有数据！'))
                 .append($('<br>'))
                 .append(document.createTextNode('同时将强制删除所有通过本应用添加的关联 NAT 规则。'))
                 .append($('<br>'))
                 .append(document.createTextNode('确定删除吗？'));
        buttonClass = 'btn-danger';
        buttonText = '删除容器';
    } else if (actionType === 'delete_nat_rule') {
        currentConfirmContainerName = null;
        currentConfirmRuleId = nameOrId;
        modalTitle.text('确认删除 NAT 规则');
        modalBody.append(document.createTextNode('确定要删除 ID 为 '))
                 .append($('<strong>').text(nameOrId))
                 .append(document.createTextNode(' 的 NAT 规则吗？此操作将尝试移除对应的 iptables 规则记录 (仅针对通过本应用添加的规则)。'));
        buttonClass = 'btn-danger';
        buttonText = '删除规则';
    }

    confirmButton.removeClass('btn-primary btn-warning btn-danger btn-success').addClass(buttonClass).text(buttonText);
    setButtonProcessing(confirmButton, false);
    const confirmModal = new bootstrap.Modal(document.getElementById('confirmModal'));
    confirmModal.show();
}

$('#confirmActionButton').click(function() {
    const actionType = currentConfirmAction;
    const buttonElement = currentConfirmButtonElement;
    const confirmButton = $(this);
    if (!actionType || !buttonElement) {
        showToast("确认信息丢失，无法执行操作。", 'danger');
        const confirmModal = bootstrap.Modal.getInstance(document.getElementById('confirmModal'));
        if (confirmModal) confirmModal.hide();
        return;
    }
    setButtonProcessing(confirmButton, true);
     if (actionType !== 'delete_nat_rule') {
         setButtonProcessing(buttonElement, true);
     }
    if (actionType === 'delete_nat_rule') {
        const ruleId = currentConfirmRuleId;
        $.ajax({
            url: `/container/nat_rule/${ruleId}`,
            type: 'DELETE',
            success: function(data) {
                showToast(data.message, data.status);
                if (data.status === 'success' || data.status === 'warning') {
                    const containerNameInModalLabel = $('#natRuleModalLabel').text().replace('NAT 规则: ', '');
                    if (containerNameInModalLabel) {
                        loadNatRules(containerNameInModalLabel);
                    } else {
                         setTimeout(() => location.reload(), 1000);
                    }
                }
            },
            error: function(jqXHR) {
                if (jqXHR.status === 401) {
                    showToast("操作需要认证，请重新登录。", 'danger');
                    setTimeout(() => window.location.href = "/login?next=" + window.location.pathname, 1000);
                } else {
                    const message = jqXHR.responseJSON ? (jqXHR.responseJSON.message || "未知错误") : `删除 NAT 规则请求失败。`;
                    showToast("操作失败: " + message, 'danger');
                }
            },
            complete: function() {
                const confirmModal = bootstrap.Modal.getInstance(document.getElementById('confirmModal'));
                if (confirmModal) confirmModal.hide();
                setButtonProcessing(buttonElement, false);
                setButtonProcessing(confirmButton, false);
            }
        });
    } else {
        const containerName = currentConfirmContainerName;
        let action = actionType.replace('_container', '');
        $.post(`/container/${containerName}/action`, { action: action }, function(data) {
            showToast(data.message, data.status);
            if (data.status === 'success') {
                 setTimeout(() => location.reload(), 1000);
            }
        }).fail(function(jqXHR) {
             if (jqXHR.status === 401) {
                showToast("操作需要认证，请重新登录。", 'danger');
                setTimeout(() => window.location.href = "/login?next=" + window.location.pathname, 1000);
             } else {
                const message = jqXHR.responseJSON ? (jqXHR.responseJSON.message || "未知错误") : `执行 ${action} 操作请求失败。`;
                showToast("操作失败: " + message, 'danger');
                setButtonProcessing(buttonElement, false);
             }
        }).always(function() {
            const confirmModal = bootstrap.Modal.getInstance(document.getElementById('confirmModal'));
            if (confirmModal) confirmModal.hide();
             setButtonProcessing(confirmButton, false);
        });
    }
});

$('#confirmModal').on('hidden.bs.modal', function () {
    currentConfirmAction = null;
    currentConfirmContainerName = null;
    currentConfirmRuleId = null;
});

function performAction(containerName, action, buttonElement) {
    if (action === 'restart') {
        showConfirmationModal('restart_container', containerName, buttonElement);
    } else if (action === 'delete') {
        showConfirmationModal('delete_container', containerName, buttonElement);
    } else if (action === 'start') {
        showConfirmationModal('start_container', containerName, buttonElement);
    } else if (action === 'stop') {
        showConfirmationModal('stop_container', containerName, buttonElement);
    }
}

function showInfo(containerName, buttonElement) {
    const basicInfoContent = $('#basicInfoContent');
    const infoError = $('#infoError');
    const infoModal = new bootstrap.Modal(document.getElementById('infoModal'));

    $('#infoModalLabel').text(`容器信息: ${containerName}`);
    basicInfoContent.text('正在加载基础信息...'); // Use text for loading message
    infoError.addClass('d-none').text('');

    setButtonProcessing(buttonElement, true);

    $.ajax({
        url: `/container/${containerName}/info`,
        type: "GET",
        success: function(data) {
             if (data.status === 'NotFound') {
                 basicInfoContent.text(`错误: ${data.message}`); // Use text for error message
                 infoError.removeClass('d-none').text(data.message);
                 showToast("加载容器信息失败。", 'danger');
                 return;
             }

            // Securely build the info content
            basicInfoContent.empty(); // Clear loading message

            const createInfoRow = (label, value) => {
                const p = $('<p></p>');
                p.append($('<strong></strong>').text(label + ': '));
                p.append(document.createTextNode(value));
                return p;
            };

            const createStatusRow = (label, status) => {
                 const p = $('<p></p>');
                 const badge = $('<span></span>')
                    .addClass('badge')
                    .addClass(`bg-${status === 'Running' ? 'success' : status === 'Stopped' ? 'danger' : 'secondary'}`)
                    .text(status);
                 p.append($('<strong></strong>').text(label + ': '));
                 p.append(badge);
                 return p;
            };

            basicInfoContent.append(createInfoRow('名称', data.name || 'N/A'));
            basicInfoContent.append(createStatusRow('状态', data.status || 'Unknown'));
            basicInfoContent.append(createInfoRow('IP 地址', (data.ip && data.ip !== 'N/A') ? data.ip : '-'));
            // IPv6 地址列表
            if (data.ipv6_list && data.ipv6_list.length) {
                basicInfoContent.append(createInfoRow('IPv6 地址', data.ipv6_list.join(', ')));
            } else {
                basicInfoContent.append(createInfoRow('IPv6 地址', '-'));
            // SSH 外网地址
            if (data.public_ipv4 && data.public_ssh_port) {
                basicInfoContent.append(createInfoRow('SSH', `${data.public_ipv4}:${data.public_ssh_port}`));
            } else {
                basicInfoContent.append(createInfoRow('SSH', '-'));
            }

            }


            const imageInfo = (data.description && data.description !== 'N/A') ? data.description : (data.image_source && data.image_source !== 'N/A') ? data.image_source : 'N/A';
            basicInfoContent.append(createInfoRow('镜像', imageInfo));
            basicInfoContent.append(createInfoRow('架构', (data.architecture && data.architecture !== 'N/A') ? data.architecture : 'N/A'));
            basicInfoContent.append(createInfoRow('创建时间', data.created_at ? data.created_at.split('T')[0] : 'N/A'));

        },
        error: function(jqXHR) {
             if (jqXHR.status === 401) {
                showToast("操作需要认证，请重新登录。", 'danger');
                setTimeout(() => window.location.href = "/login?next=" + window.location.pathname, 1000);
             } else {
                const message = jqXHR.responseJSON ? jqXHR.responseJSON.message : "请求失败，无法加载详细信息。";
                basicInfoContent.text(`错误: ${message}`); // Use text for error message
                infoError.removeClass('d-none').text(message);
                showToast("加载容器信息失败。", 'danger');
             }
        },
        complete: function() {
            setButtonProcessing(buttonElement, false);
            infoModal.show();
        }
    });
}

function loadNatRules(containerName) {
    const natRulesContent = $('#natRulesContent');
    const natRulesError = $('#natRulesError');
    natRulesContent.html('<li>正在加载 NAT 规则...</li>');
    natRulesError.addClass('d-none').text('');
     $.ajax({
        url: `/container/${containerName}/nat_rules`,
        type: "GET",
        success: function(data) {
            natRulesContent.empty();
            if (data.status === 'success' && data.rules && data.rules.length > 0) {
                data.rules.forEach(rule => {
                    // Build rule elements securely
                    const detailsSpan = $('<span></span>').addClass('rule-details');
                    detailsSpan.append($('<strong></strong>').text(`ID ${rule.id}:`));
                    detailsSpan.append(document.createTextNode(` 主机 ${rule.host_port}/${rule.protocol} → 容器 ${rule.ip_at_creation}:${rule.container_port}`));
                    detailsSpan.append($('<br>'));
                    detailsSpan.append($('<small></small>').addClass('text-muted').text(`记录创建时间: ${rule.created_at ? new Date(rule.created_at).toLocaleString() : 'N/A'}`));

                    const deleteButton = $('<button></button>')
                        .addClass('btn btn-sm btn-danger')
                        .text('删除')
                        .on('click', function() { deleteNatRule(rule.id, this); });

                    const actionsSpan = $('<span></span>').addClass('rule-actions').append(deleteButton);

                    const li = $('<li></li>').attr('data-rule-id', rule.id).append(detailsSpan).append(actionsSpan);

                    natRulesContent.append(li);
                });
            } else if (data.status === 'success' && data.rules && data.rules.length === 0) {
                natRulesContent.html('<li>没有通过本应用添加的 NAT 规则记录。</li>');
            } else {
                 natRulesContent.html('<li>加载 NAT 规则失败。</li>');
                 natRulesError.removeClass('d-none').text(data.message || '未知错误获取规则列表。');
                 showToast(data.message || "加载 NAT 规则失败。", 'danger');
            }
        },
        error: function(jqXHR) {
             if (jqXHR.status === 401) {
                showToast("加载 NAT 规则需要认证，请重新登录。", 'danger');
                setTimeout(() => window.location.href = "/login?next=" + window.location.pathname, 1000);
             } else {
                 const message = jqXHR.responseJSON ? jqXHR.responseJSON.message : "请求失败，无法加载 NAT 规则。";
                 natRulesContent.html('<li>加载 NAT 规则失败。</li>');
                 natRulesError.removeClass('d-none').text(message);
                 showToast(message, 'danger');
             }
        }
    });
}

function deleteNatRule(ruleId, buttonElement) {
    showConfirmationModal('delete_nat_rule', ruleId, buttonElement);
}

function showNatRuleModal(containerName, buttonElement) {
    const natModal = new bootstrap.Modal(document.getElementById('natRuleModal'));
    $('#natRuleModalLabel').text(`NAT 规则: ${containerName}`);
    setButtonProcessing(buttonElement, true);

    loadNatRules(containerName);

    natModal.show();

    const natModalEl = document.getElementById('natRuleModal');
    natModalEl.addEventListener('shown.bs.modal', () => {
        setButtonProcessing(buttonElement, false);
    }, { once: true });
     natModalEl.addEventListener('hidden.bs.modal', () => {
        $('#natRulesContent').html('<li>...</li>');
    }, { once: true });
}

let term;
let fitAddon;
let socket;

function openSshModal(containerName) {
    $('#sshModalLabel').text(`在线 SSH: ${containerName}`);
    const sshModalEl = document.getElementById('sshModal');
    const sshModal = new bootstrap.Modal(sshModalEl);

    sshModalEl.addEventListener('shown.bs.modal', function () {
        $.get(`/container/${containerName}/info`, function(data) {
            if (data.ip && data.ip !== 'N/A' && data.status === 'Running') {
                initializeTerminal(containerName, data.ip);
            } else {
                $('#terminal').html('<div class="alert alert-danger p-3 m-3">无法获取容器IP地址或容器未运行，无法启动SSH。</div>');
            }
        }).fail(function() {
             $('#terminal').html('<div class="alert alert-danger p-3 m-3">获取容器信息失败，无法启动SSH。</div>');
        });
    }, { once: true });

    sshModal.show();
}

function initializeTerminal(containerName, ip) {
    const terminalContainer = document.getElementById('terminal');
    terminalContainer.innerHTML = '';

    term = new Terminal({ cursorBlink: true, rows: 25, cols: 80, theme: { background: '#000000'} });
    fitAddon = new FitAddon.FitAddon();
    term.loadAddon(fitAddon);
    term.open(terminalContainer);
    fitAddon.fit();
    term.focus();

    term.writeln('正在连接到服务器...');

    socket = io();

    socket.on('connect', () => {
        term.writeln('✅ 连接成功，正在启动SSH会话...');
        socket.emit('start_ssh', { 'container': containerName, 'ip': ip, 'cols': term.cols, 'rows': term.rows });
    });

    socket.on('ssh_output', (data) => {
        term.write(data);
    });

    socket.on('disconnect', () => {
        term.writeln('\r\n❌ 与服务器断开连接。');
        if(socket) socket.disconnect();
    });

    socket.on('ssh_error', (message) => {
        term.writeln(`\r\n❌ SSH 错误: ${message}`);
        if(socket) socket.disconnect();
    });

    term.onData((data) => {
        if(socket && socket.connected) {
            socket.emit('ssh_input', { 'input': data });
        }
    });

     $(window).on('resize.ssh', function() {
        if(fitAddon && term) {
            fitAddon.fit();
            if (socket && socket.connected) {
                socket.emit('ssh_resize', { 'cols': term.cols, 'rows': term.rows });
            }
        }
     });

     $('#sshModal').on('shown.bs.modal.ssh', function () {
         if(fitAddon && term) {
             fitAddon.fit();
             term.focus();
         }
     });
}

$('#sshModal').on('hidden.bs.modal', function () {
    if (socket) {
        socket.disconnect();
        socket = null;
    }
    if (term) {
        term.dispose();
        term = null;
    }
    $('#terminal').html('');
    $(window).off('resize.ssh');
    $('#sshModal').off('shown.bs.modal.ssh');
});


$('#infoModal').on('hidden.bs.modal', function () {
    $('#basicInfoContent').html('正在加载基础信息...');
    $('#infoError').addClass('d-none').text('');
    $('#infoModalLabel').text('容器信息');
});