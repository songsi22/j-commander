const API_BASE = '/api/container';
const SCHEDULE_API = '/api/jobs';
const HISTORY_API = '/api/jobs/history';
const TIME_API = '/api/time';

let selectedServers = new Set();
let serverData = [];
let jobData = [];
let systemTime = null;
let currentWas = 'konetic';

// DOM Elements
const tbody = document.getElementById('server-list');
const clockEl = document.getElementById('system-clock');

// Scheduler DOM
const jobListBody = document.getElementById('job-list');
const jobCountBadge = document.getElementById('job-count');
const jobModal = document.getElementById('job-modal');
const jobForm = document.getElementById('job-form');
const jobServerSelect = document.getElementById('job-server-select');

// Header Elements
const headerCheckbox = document.getElementById('header-checkbox');
const wasRadios = document.getElementsByName('was-select');
const bulkStartBtn = document.getElementById('bulk-start');
const bulkStopBtn = document.getElementById('bulk-stop');
const bulkRestartBtn = document.getElementById('bulk-restart');

async function init() {
    setupWasSelector();
    setupTabs(); // Add tab setup
    startClock();
    startStatusPolling();
    await loadCurrentWas();
    await fetchJobs();
    await fetchHistory();
}

function setupTabs() {
    const tabBtns = document.querySelectorAll('.tab-btn');
    const tabContents = document.querySelectorAll('.tab-content');

    tabBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            const target = btn.getAttribute('data-tab');

            // Update Tab Buttons
            tabBtns.forEach(b => b.classList.remove('active'));
            btn.classList.add('active');

            // Update Content Panels
            tabContents.forEach(content => {
                content.classList.remove('active');
                if (content.id === target) {
                    content.classList.add('active');
                }
            });
        });
    });
}


// --- Scheduler & Clock ---

async function startClock() {
    await fetchTime();
    setInterval(() => {
        if (systemTime) {
            systemTime = new Date(systemTime.getTime() + 1000);
            updateClockDisplay();
        }
    }, 1000);
    setInterval(fetchTime, 60000);
}

async function fetchTime() {
    try {
        const res = await fetch(TIME_API);
        const data = await res.json();
        systemTime = new Date(data.time.replace(' ', 'T'));
        updateClockDisplay();
    } catch (err) {
        console.error("Time sync failed:", err);
    }
}

function updateClockDisplay() {
    if (clockEl && systemTime) {
        clockEl.innerText = systemTime.toLocaleString('ko-KR', {
            hour: '2-digit', minute: '2-digit', second: '2-digit',
            year: 'numeric', month: '2-digit', day: '2-digit'
        });
    }
}

function startStatusPolling() {
    // Poll every 10 seconds to sync servers, jobs, and history
    setInterval(async () => {
        await fetchServers(null, currentWas);
        await fetchJobs();
        await fetchHistory();
    }, 10000);
}

// Job Management
async function fetchServers(btn, was) {
    const wasToFetch = was || currentWas;
    const refreshBtn = btn; // Only use button if explicitly passed (manual click)
    if (refreshBtn) {
        refreshBtn.classList.add('loading');
        refreshBtn.innerHTML = '<span class="spinner"></span>Refreshing...';
    }

    try {
        const res = await fetch(`${API_BASE}/list?was=${wasToFetch}`);
        if (!res.ok) throw new Error('Failed to fetch server list');
        const data = await res.json();
        serverData = data.servers || [];
        renderTable();
        updateBulkButtons();
    } catch (err) {
        showToast(err.message, 'error');
    } finally {
        if (refreshBtn) {
            refreshBtn.classList.remove('loading');
            refreshBtn.innerHTML = 'Refresh List';
        }
    }
}

async function fetchJobs() {
    try {
        const res = await fetch(SCHEDULE_API);
        const data = await res.json();
        jobData = data.jobs || [];
        renderJobs();
    } catch (err) {
        console.error("Failed to fetch jobs:", err);
    }
}

async function fetchHistory() {
    try {
        const res = await fetch(HISTORY_API);
        const data = await res.json();
        renderHistory(data.history || []);
    } catch (err) {
        console.error("Failed to fetch history:", err);
    }
}

function renderJobs() {
    if (!jobListBody) return;
    jobListBody.innerHTML = '';

    if (jobCountBadge) jobCountBadge.innerText = jobData.length;
    const jobCountTab = document.getElementById('job-count-tab');
    if (jobCountTab) jobCountTab.innerText = jobData.length;

    if (jobData.length === 0) {
        jobListBody.innerHTML = '<tr><td colspan="6" style="text-align: center; color: var(--text-secondary);">No scheduled tasks.</td></tr>';
        return;
    }

    jobData.forEach(job => {
        const tr = document.createElement('tr');
        const nextRun = job.next_run_time ? new Date(job.next_run_time).toLocaleString() : 'Pending';
        const [action, servers, isCluster] = job.args;
        // Trigger display improvement
        let trigger = job.trigger;
        if (trigger.includes('date[')) {
            trigger = 'One-Time';
        }

        tr.innerHTML = `
            <td><span class="badge" style="background: var(--card-border);">${action.toUpperCase()}</span></td>
            <td style="max-width: 200px; overflow: hidden; text-overflow: ellipsis;" title="${servers.join(', ')}">${servers.join(', ')}</td>
            <td>${trigger}</td>
            <td>${isCluster ? '<span style="color:var(--success)">Yes</span>' : '<span style="color:var(--text-secondary)">No</span>'}</td>
            <td>${nextRun}</td>
            <td>
                <button class="btn-mini btn-stop" onclick="deleteJob('${job.id}')">Delete</button>
            </td>
        `;
        jobListBody.appendChild(tr);
    });
}

function renderHistory(history) {
    const list = document.getElementById('history-list');
    if (!list) return;
    list.innerHTML = '';

    if (history.length === 0) {
        list.innerHTML = '<tr><td colspan="5" style="text-align: center; color: var(--text-secondary);">No execution history.</td></tr>';
        return;
    }

    history.forEach(entry => {
        const tr = document.createElement('tr');
        const statusColor = entry.status === 'SUCCESS' ? 'var(--success)' : (entry.status === 'SKIPPED' ? 'var(--warning)' : 'var(--error)');
        const timestamp = new Date(entry.timestamp).toLocaleString();

        tr.innerHTML = `
            <td>${timestamp}</td>
            <td><span class="badge" style="background: var(--card-border);">${entry.action.toUpperCase()}</span></td>
            <td>${entry.targets.join(', ')}</td>
            <td style="color: ${statusColor}; font-weight: 500;">${entry.status}</td>
            <td>${entry.detail}</td>
        `;
        list.appendChild(tr);
    });
}

function openJobModal() {
    jobModal.classList.add('show');
    jobServerSelect.innerHTML = '';
    serverData.forEach(server => {
        const div = document.createElement('div');
        div.className = 'checkbox-item';
        div.innerHTML = `
            <input type="checkbox" name="job-servers" value="${server.name}">
            <span>${server.name}</span>
        `;
        jobServerSelect.appendChild(div);
    });
}

function closeJobModal() {
    jobModal.classList.remove('show');
    jobForm.reset();
}

window.onclick = function (event) {
    if (event.target == jobModal) closeJobModal();
}

async function deleteJob(jobId) {
    if (!confirm('Are you sure you want to delete this task?')) return;
    try {
        const res = await fetch(`${SCHEDULE_API}/${jobId}`, { method: 'DELETE' });
        if (res.ok) {
            showToast('Job cancelled', 'success');
            await fetchJobs();
            await fetchServers(); // Refresh status in case it was waiting on this job
        } else {
            throw new Error('Failed to delete job');
        }
    } catch (err) {
        showToast(err.message, 'error');
    }
}

jobForm.addEventListener('submit', async (e) => {
    e.preventDefault();

    const action = document.getElementById('job-action').value;
    const selectedCheckboxes = jobServerSelect.querySelectorAll('input[type="checkbox"]:checked');
    const servers = Array.from(selectedCheckboxes).map(cb => cb.value);

    // Cron Inputs (Simplified to Hour/Min)
    const hour = document.getElementById('cron-hour').value;
    const min = document.getElementById('cron-min').value;
    const cron = `${min} ${hour} * * *`;

    if (servers.length === 0) {
        alert('Please select at least one server.');
        return;
    }

    const clusterAware = document.getElementById('job-cluster-aware').checked;

    try {
        const res = await fetch(SCHEDULE_API, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                action, servers, cron, cluster_aware: clusterAware, was: currentWas
            })
        });

        const result = await res.json();
        if (res.ok) {
            showToast('Schedule created successfully', 'success');
            closeJobModal();
            await fetchJobs();
            await fetchServers();
        } else {
            let errorMsg = 'Failed';
            if (result.detail) {
                if (typeof result.detail === 'string') {
                    errorMsg = result.detail;
                } else if (Array.isArray(result.detail)) {
                    // Pydantic validation errors
                    errorMsg = result.detail.map(e => `${e.loc.pop()}: ${e.msg}`).join('\n');
                } else {
                    errorMsg = JSON.stringify(result.detail);
                }
            }
            throw new Error(errorMsg);
        }
    } catch (err) {
        alert('Error creating schedule:\n' + err.message);
    }
});

// --- Existing Server Logic (was-selector, fetchServers, renderTable, etc.) ---
function setupWasSelector() {
    Array.from(wasRadios).forEach(radio => {
        radio.addEventListener('change', () => {
            loadCurrentWas();
        });
    });
}

async function loadCurrentWas() {
    // Determine selected WAS
    for (const radio of wasRadios) {
        if (radio.checked) { currentWas = radio.value; break; }
    }
    selectedServers.clear();
    updateBulkButtons();

    // Unified fetch for all WAS
    renderLoading();
    // After switching, immediately fetch to show real data
    await fetchServers(null, currentWas);
}

// Duplicate function removed

function renderLoading() {
    tbody.innerHTML = '<tr><td colspan="4" style="text-align: center; padding: 2rem; color: var(--text-secondary);">Loading servers...</td></tr>';
}

function renderPlaceholder(was) {
    serverData = [];
    tbody.innerHTML = `<tr><td colspan="4" style="text-align: center; padding: 2rem; color: var(--text-secondary);">
        ${was.toUpperCase()} is not connected.<br>
        <span style="font-size: 0.8em; opacity: 0.7;">Only WAS 1 is active.</span>
    </td></tr>`;
}

function renderError(msg) {
    tbody.innerHTML = `<tr><td colspan="4" style="text-align: center; padding: 2rem; color: var(--error);">Error: ${msg}</td></tr>`;
}

function renderTable() {
    tbody.innerHTML = '';
    if (serverData.length === 0) {
        tbody.innerHTML = '<tr><td colspan="4" style="text-align: center; padding: 2rem; color: var(--text-secondary);">No servers found.</td></tr>';
        return;
    }

    serverData.forEach(server => {
        const tr = document.createElement('tr');
        const isSelected = selectedServers.has(server.name);
        const statusClass = getStatusClass(server.status);

        tr.innerHTML = `
            <td><input type="checkbox" class="server-checkbox" data-name="${server.name}" ${isSelected ? 'checked' : ''}></td>
            <td style="font-weight: 500;">${server.name}</td>
            <td>
                <div class="status-indicator">
                    <span class="dot ${statusClass}"></span>
                    <span>${server.status}</span>
                </div>
            </td>
            <td>
                <div class="row-actions">
                    <button class="btn-mini btn-start" onclick="performAction(this, 'start', '${server.name}')">Start</button>
                    <button class="btn-mini btn-stop" onclick="performAction(this, 'stop', '${server.name}')">Stop</button>
                    <button class="btn-mini btn-restart" onclick="performAction(this, 'restart', '${server.name}')">Restart</button>
                </div>
            </td>
        `;

        const checkbox = tr.querySelector('.server-checkbox');
        checkbox.addEventListener('change', (e) => {
            if (e.target.checked) selectedServers.add(server.name);
            else selectedServers.delete(server.name);
            updateBulkButtons();
        });

        tbody.appendChild(tr);
    });

    if (headerCheckbox) headerCheckbox.disabled = false;
    updateBulkButtons();
}

function getStatusClass(status) {
    status = status.toUpperCase();
    if (status.includes('RUNNING')) return 'running';
    if (status.includes('SHUTDOWN')) return 'shutdown';
    if (status.includes('STOPPED')) return 'stopped';
    return 'unknown';
}

function updateBulkButtons() {
    const count = selectedServers.size;
    const hasSelection = count > 0;

    bulkStartBtn.disabled = !hasSelection;
    bulkStopBtn.disabled = !hasSelection;
    bulkRestartBtn.disabled = !hasSelection;

    const targetCheckbox = headerCheckbox;
    if (!targetCheckbox) return;

    if (serverData.length > 0 && count === serverData.length) {
        targetCheckbox.checked = true;
        targetCheckbox.indeterminate = false;
    } else if (count > 0) {
        targetCheckbox.checked = false;
        targetCheckbox.indeterminate = true;
    } else {
        targetCheckbox.checked = false;
        targetCheckbox.indeterminate = false;
    }
}

async function performAction(btn, action, target) {
    let targets = [];
    const sourceBtn = btn;

    if (target === 'BULK') {
        targets = Array.from(selectedServers);
    } else {
        targets = [target];
    }

    if (targets.length === 0) return;

    // Confirmation Step
    if (action !== 'status') {
        const confirmMsg = target === 'BULK'
            ? `Are you sure you want to ${action.toUpperCase()} ${targets.length} selected servers?`
            : `Are you sure you want to ${action.toUpperCase()} ${target}?`;

        if (!confirm(confirmMsg)) return;
    }

    if (sourceBtn) {
        sourceBtn.classList.add('loading');
        sourceBtn.disabled = true;
        // Add spinner if not already there
        if (!sourceBtn.querySelector('.spinner')) {
            const span = document.createElement('span');
            span.className = 'spinner';
            sourceBtn.prepend(span);
        }
    }

    const displayText = target === 'BULK' ? `Selected (${targets.length})` : target;
    showToast(`Executing ${action} on ${displayText}...`, 'info');

    try {
        const res = await fetch(API_BASE, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ action, servers: targets, was: currentWas })
        });

        const result = await res.json();

        if (result.success) {
            showToast(`${action.toUpperCase()} completed successfully.`, 'success');
            if (target === 'BULK') {
                selectedServers.clear();
            }
            await fetchServers();
        } else {
            showToast(`Error: ${result.stderr || result.detail || 'Action failed'}`, 'error');
        }
    } catch (err) {
        showToast(`Request failed: ${err.message}`, 'error');
    } finally {
        if (sourceBtn) {
            sourceBtn.classList.remove('loading');
            sourceBtn.disabled = false;
            // Remove injected spinner
            const spinner = sourceBtn.querySelector('.spinner');
            if (spinner) spinner.remove();
            updateBulkButtons();
        }
    }
}

function showToast(message, type = 'info') {
    const container = document.getElementById('toast-container');
    if (!container) return;

    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.innerText = message;
    container.appendChild(toast);

    // Auto remove
    setTimeout(() => {
        toast.style.opacity = '0';
        toast.style.transform = 'translateX(20px)';
        setTimeout(() => toast.remove(), 300);
    }, 4000);
}

if (headerCheckbox) {
    headerCheckbox.addEventListener('change', (e) => {
        if (e.target.checked) {
            serverData.forEach(s => selectedServers.add(s.name));
        } else {
            selectedServers.clear();
        }
        renderTable();
    });
}

init();
