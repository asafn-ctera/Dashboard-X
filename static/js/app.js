const API = '';
let allVMs = [];
let allTemplates = [];
let activeFolders = new Set();
let folderAutoSelected = false;
let searchTerm = '';
let currentUserEmail = '';
let authConnected = false;
let sortCol = 'creation_date';
let sortDir = 'desc';
let autoRefresh = true;
let refreshTimer = null;
let pendingSnapshot = null;
let provisioningVMs = new Set();
let pendingAction = null;
let pendingRestore = null;
let currentSuggestionVMs = [];
let expandedVmKey = null;
let configuredFolderSet = new Set();
let savedJenkinsJobs = [];
let jenkinsJobSearchTimer = null;
let jenkinsBuilds = [];
let jenkinsBuildsTimer = null;
const CLONE_TEMPLATE_LIMIT = 5;

// -- init -------------------------------------------------------------

document.addEventListener('DOMContentLoaded', () => {
    loadStatus().finally(() => {
        autoAddUserFolders().finally(() => loadVMs());
    });
    loadTemplates();
    loadJenkinsJobs().then(() => loadJenkinsBuilds());
    startAutoRefresh();

    document.getElementById('search').addEventListener('input', (e) => {
        searchTerm = e.target.value.toLowerCase();
        renderTable();
    });

    document.getElementById('auto-refresh').addEventListener('change', (e) => {
        autoRefresh = e.target.checked;
        if (autoRefresh) startAutoRefresh();
        else stopAutoRefresh();
    });

    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            closeSnapshotDialog();
            closeRestoreDialog();
            closeActionDialog();
            closeJenkinsParamsDialog();
            closeAddEnvDialog();
            closeAddJenkinsJobDialog();
            closeRowMenus();
        }
    });
    document.getElementById('snapshot-dialog').addEventListener('click', (e) => {
        if (e.target.id === 'snapshot-dialog') closeSnapshotDialog();
    });
    document.getElementById('restore-dialog').addEventListener('click', (e) => {
        if (e.target.id === 'restore-dialog') closeRestoreDialog();
    });
    document.getElementById('action-dialog').addEventListener('click', (e) => {
        if (e.target.id === 'action-dialog') closeActionDialog();
    });
    document.getElementById('add-env-dialog').addEventListener('click', (e) => {
        if (e.target.id === 'add-env-dialog') closeAddEnvDialog();
    });
    document.getElementById('jenkins-params-dialog').addEventListener('click', (e) => {
        if (e.target.id === 'jenkins-params-dialog') closeJenkinsParamsDialog();
    });
    document.getElementById('add-jenkins-job-dialog').addEventListener('click', (e) => {
        if (e.target.id === 'add-jenkins-job-dialog') closeAddJenkinsJobDialog();
    });
    document.addEventListener('click', (e) => {
        if (!e.target.closest('.row-menu')) closeRowMenus();
    });
});

// -- auto-add user folders --------------------------------------------

async function autoAddUserFolders() {
    if (!authConnected) return;
    const prefix = getUserPrefix();
    if (!prefix) return;

    const candidatePaths = [
        `Technical Teams/Engineering/${prefix}`,
        `Technical Teams/Engineering/Portal Sandbox/${prefix}`,
    ];

    let res, data;
    try {
        res = await fetch(`${API}/api/config/folders`);
        data = await res.json();
    } catch { return; }
    const existing = new Set(data.folders || []);

    for (const candidate of candidatePaths) {
        const match = existing.has(candidate) ? candidate
            : [...existing].find(f => f.toLowerCase() === candidate.toLowerCase());
        if (match) continue;

        try {
            const parent = candidate.substring(0, candidate.lastIndexOf('/'));
            const folderName = candidate.substring(candidate.lastIndexOf('/') + 1);
            const browseRes = await fetch(`${API}/api/vsphere/browse?path=${encodeURIComponent(parent)}`);
            const browseData = await browseRes.json();
            if (!browseData.success || !Array.isArray(browseData.items)) continue;
            const found = browseData.items.find(
                i => i.type === 'folder' && i.name.toLowerCase() === folderName.toLowerCase()
            );
            if (!found) continue;

            await fetch(`${API}/api/config/folders`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ folder: found.path }),
            });
            activeFolders.add(found.path);
        } catch { /* ignore */ }
    }
}

// -- data fetching ----------------------------------------------------

async function loadStatus() {
    try {
        const res = await fetch(`${API}/api/auth/status`);
        const data = await res.json();
        authConnected = Boolean(data.connected);
        currentUserEmail = data.user || '';
        const dot = document.getElementById('status-dot');
        const text = document.getElementById('status-text');
        dot.className = `status-dot ${authConnected ? 'connected' : 'disconnected'}`;
        text.textContent = authConnected
            ? `${data.server} (${data.user})`
            : `Disconnected from ${data.server}`;
        if (authConnected) {
            closeLoginDialog();
        } else {
            showLoginDialog(data.user || '');
        }
    } catch {
        authConnected = false;
        document.getElementById('status-dot').className = 'status-dot disconnected';
        document.getElementById('status-text').textContent = 'Connection error';
        showLoginDialog(currentUserEmail || '');
    }
}

async function loadVMs(force = false) {
    showLoading(true);
    hideError();
    try {
        if (!authConnected) {
            allVMs = [];
            renderFolderTabs();
            renderStats();
            renderTable();
            return;
        }
        const params = [];
        if (force) params.push('refresh=true');
        const url = `${API}/api/vms${params.length ? `?${params.join('&')}` : ''}`;
        const res = await fetch(url);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        allVMs = await res.json();
        renderFolderTabs();
        renderStats();
        renderTable();
    } catch (e) {
        showError(`Failed to load VMs: ${e.message}`);
    } finally {
        showLoading(false);
    }
}

function showLoginDialog(username = '') {
    const dialog = document.getElementById('login-dialog');
    const userInput = document.getElementById('login-username');
    const status = document.getElementById('login-status');
    if (!userInput.value && username) userInput.value = username;
    status.textContent = '';
    status.className = 'action-status';
    dialog.classList.add('active');
}

function closeLoginDialog() {
    document.getElementById('login-dialog').classList.remove('active');
}

async function submitLogin() {
    const username = document.getElementById('login-username').value.trim();
    const password = document.getElementById('login-password').value;
    const btn = document.getElementById('login-confirm-btn');
    const status = document.getElementById('login-status');
    if (!username || !password) {
        status.className = 'action-status error';
        status.textContent = 'Username and password are required.';
        return;
    }

    btn.disabled = true;
    btn.textContent = 'Connecting...';
    status.className = 'action-status loading';
    status.textContent = 'Connecting to vSphere...';
    try {
        const res = await fetch(`${API}/api/auth/login`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username, password }),
        });
        const data = await res.json();
        if (!data.success) {
            status.className = 'action-status error';
            status.textContent = data.message || 'Login failed';
            return;
        }
        status.className = 'action-status success';
        status.textContent = data.message || 'Connected';
        document.getElementById('login-password').value = '';
        await loadStatus();
        await loadVMs(true);
        await loadTemplates();
    } catch (e) {
        status.className = 'action-status error';
        status.textContent = `Login failed: ${e.message}`;
    } finally {
        btn.disabled = false;
        btn.textContent = 'Connect';
    }
}

async function loadTemplates() {
    try {
        const res = await fetch(`${API}/api/templates?limit=${CLONE_TEMPLATE_LIMIT}`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        allTemplates = await res.json();
    } catch (e) {
        allTemplates = [];
    }
    renderQuickTemplates();
}

function renderQuickTemplates() {
    const container = document.getElementById('quick-templates');
    const templates = allTemplates.slice(0, 5);

    if (templates.length === 0) {
        container.innerHTML = '<div class="quick-tpl-placeholder">No templates available.</div>';
        return;
    }

    container.innerHTML = templates.map(t => {
        const version = t.portal_version || '';
        const date = t.creation_date ? formatDate(t.creation_date) : '';
        return `<button class="quick-tpl-btn" onclick="quickCloneTemplate('${escAttr(t.name)}')" title="${esc(t.name)}">
            <span class="quick-tpl-name">${esc(t.name)}</span>
            <span class="quick-tpl-detail">
                ${version ? `<span class="quick-tpl-version">${esc(version)}</span>` : ''}
                ${date ? `<span class="quick-tpl-date">${esc(date)}</span>` : ''}
            </span>
        </button>`;
    }).join('');
}

function quickCloneTemplate(name) {
    selectedCloneTemplate = name;
    const tpl = allTemplates.find(t => t.name === name);
    document.getElementById('clone-step-1').style.display = 'none';
    document.getElementById('clone-step-2').style.display = '';
    document.getElementById('clone-back-btn').style.display = '';
    document.getElementById('clone-next-btn').style.display = '';
    document.getElementById('clone-selected-label').textContent = name;
    document.getElementById('clone-selected-meta').textContent = tpl ? templateMetaLine(tpl) : '';
    document.getElementById('clone-vm-name').value = '';
    document.getElementById('clone-status').className = 'action-status';
    document.getElementById('clone-status').textContent = '';
    document.getElementById('clone-dialog').classList.add('active');
    document.getElementById('clone-vm-name').focus();
}

function refreshVMs() {
    loadStatus().finally(() => loadVMs(true));
}

// -- auto-refresh -----------------------------------------------------

function startAutoRefresh() {
    stopAutoRefresh();
    refreshTimer = setInterval(() => {
        loadVMs();
        loadJenkinsBuilds();
    }, 60000);
}

function stopAutoRefresh() {
    if (refreshTimer) {
        clearInterval(refreshTimer);
        refreshTimer = null;
    }
}

// -- clone VM dialog --------------------------------------------------

let selectedCloneTemplate = '';

async function openCloneDialog() {
    selectedCloneTemplate = '';
    document.getElementById('clone-step-1').style.display = '';
    document.getElementById('clone-step-2').style.display = 'none';
    document.getElementById('clone-back-btn').style.display = 'none';
    document.getElementById('clone-next-btn').style.display = 'none';
    document.getElementById('clone-vm-name').value = '';
    document.getElementById('clone-selected-meta').textContent = '';
    document.getElementById('clone-status').className = 'action-status';
    document.getElementById('clone-status').textContent = '';
    const list = document.getElementById('clone-template-list');
    list.innerHTML = '<div class="clone-tpl-empty">Loading templates...</div>';

    if (allTemplates.length === 0) {
        await loadTemplates();
    }
    renderCloneTemplateList(allTemplates);
    document.getElementById('clone-dialog').classList.add('active');
    const firstTemplateBtn = document.querySelector('#clone-template-list .clone-tpl-item');
    if (firstTemplateBtn) firstTemplateBtn.focus();
}

function closeCloneDialog() {
    document.getElementById('clone-dialog').classList.remove('active');
}

function renderCloneTemplateList(templates) {
    const list = document.getElementById('clone-template-list');
    if (templates.length === 0) {
        list.innerHTML = '<div class="clone-tpl-empty">No templates found in latest 5</div>';
        return;
    }
    list.innerHTML = templates.map(t =>
        `<button class="clone-tpl-item${t.name === selectedCloneTemplate ? ' selected' : ''}" onclick="selectCloneTemplate('${escAttr(t.name)}')">
            <span class="clone-tpl-title">${esc(t.name)}</span>
            <span class="clone-tpl-meta">${esc(templateMetaLine(t))}</span>
        </button>`
    ).join('');
}

function selectCloneTemplate(name) {
    selectedCloneTemplate = name;
    const tpl = allTemplates.find(t => t.name === name);
    document.getElementById('clone-step-1').style.display = 'none';
    document.getElementById('clone-step-2').style.display = '';
    document.getElementById('clone-back-btn').style.display = '';
    document.getElementById('clone-next-btn').style.display = '';
    document.getElementById('clone-selected-label').textContent = name;
    document.getElementById('clone-selected-meta').textContent = tpl ? templateMetaLine(tpl) : '';
    document.getElementById('clone-vm-name').focus();
}

function cloneStepBack() {
    document.getElementById('clone-step-1').style.display = '';
    document.getElementById('clone-step-2').style.display = 'none';
    document.getElementById('clone-back-btn').style.display = 'none';
    document.getElementById('clone-next-btn').style.display = 'none';
    document.getElementById('clone-status').className = 'action-status';
    document.getElementById('clone-status').textContent = '';
}

async function cloneVM() {
    const templateName = selectedCloneTemplate;
    const vmName = document.getElementById('clone-vm-name').value.trim();
    const statusEl = document.getElementById('clone-status');
    const btn = document.getElementById('clone-next-btn');

    if (!vmName) {
        statusEl.className = 'action-status error';
        statusEl.textContent = 'Please enter a VM name';
        return;
    }

    btn.disabled = true;
    btn.textContent = 'Creating VM...';
    statusEl.className = 'action-status loading';
    statusEl.textContent = `Cloning ${templateName}... this may take a few minutes.`;

    provisioningVMs.add(vmName);
    allVMs.push({
        name: vmName,
        folder: 'Provisioning...',
        portal_version: templateName.replace('PIM_C9_', '').replace('PIM_', ''),
        creation_date: new Date().toISOString(),
        ip_address: null,
        connect_url: null,
        status: 'provisioning',
    });
    renderStats();
    renderTable();

    try {
        const res = await fetch(`${API}/api/clone`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ template_name: templateName, vm_name: vmName }),
        });
        const data = await res.json();
        provisioningVMs.delete(vmName);
        if (data.success) {
            statusEl.className = 'action-status success';
            statusEl.textContent = data.message;
            document.getElementById('clone-vm-name').value = '';
            loadVMs(true);
            setTimeout(() => closeCloneDialog(), 1500);
        } else {
            statusEl.className = 'action-status error';
            statusEl.textContent = data.message;
            allVMs = allVMs.filter(v => v.status !== 'provisioning' || v.name !== vmName);
            renderStats();
            renderTable();
        }
    } catch (e) {
        provisioningVMs.delete(vmName);
        statusEl.className = 'action-status error';
        statusEl.textContent = `Clone failed: ${e.message}`;
        allVMs = allVMs.filter(v => v.status !== 'provisioning' || v.name !== vmName);
        renderStats();
        renderTable();
    } finally {
        btn.disabled = false;
        btn.textContent = 'Create VM';
    }
}

// -- create empty VM (edge filer) ------------------------------------

async function createEmptyVM() {
    const vmName = document.getElementById('ef-vm-name').value.trim();
    const numCpus = parseInt(document.getElementById('ef-cpus').value, 10) || 4;
    const memoryGb = parseInt(document.getElementById('ef-memory').value, 10) || 8;
    const diskGb = parseInt(document.getElementById('ef-disk').value, 10) || 100;
    const statusEl = document.getElementById('ef-create-status');
    const btn = document.getElementById('ef-create-btn');

    if (!vmName) {
        statusEl.className = 'action-status error';
        statusEl.textContent = 'Please enter a VM name';
        return;
    }

    btn.disabled = true;
    btn.textContent = 'Creating VM...';
    statusEl.className = 'action-status loading';
    statusEl.textContent = `Creating empty VM "${vmName}"... this may take a minute.`;

    provisioningVMs.add(vmName);
    allVMs.push({
        name: vmName,
        folder: 'Provisioning...',
        portal_version: null,
        creation_date: new Date().toISOString(),
        ip_address: null,
        connect_url: null,
        status: 'provisioning',
    });
    renderStats();
    renderTable();

    try {
        const res = await fetch(`${API}/api/create-empty-vm`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                vm_name: vmName,
                num_cpus: numCpus,
                memory_gb: memoryGb,
                disk_gb: diskGb,
            }),
        });
        const data = await res.json();
        provisioningVMs.delete(vmName);
        if (data.success) {
            statusEl.className = 'action-status success';
            statusEl.textContent = data.message;
            document.getElementById('ef-vm-name').value = '';
            loadVMs(true);
        } else {
            statusEl.className = 'action-status error';
            statusEl.textContent = data.message;
            allVMs = allVMs.filter(v => v.status !== 'provisioning' || v.name !== vmName);
            renderStats();
            renderTable();
        }
    } catch (e) {
        provisioningVMs.delete(vmName);
        statusEl.className = 'action-status error';
        statusEl.textContent = `Create failed: ${e.message}`;
        allVMs = allVMs.filter(v => v.status !== 'provisioning' || v.name !== vmName);
        renderStats();
        renderTable();
    } finally {
        btn.disabled = false;
        btn.textContent = 'Create Edge Filer';
    }
}

// -- snapshots --------------------------------------------------------

function openSnapshotDialog(vmName, folder) {
    pendingSnapshot = { vmName, folder };
    const now = new Date();
    const dateStr = now.toISOString().slice(0, 16).replace('T', '_').replace(':', '-');
    const snapName = `${vmName}_${dateStr}`;

    document.getElementById('snapshot-dialog-text').textContent =
        `Create a snapshot for "${vmName}"?`;
    document.getElementById('snapshot-name-preview').textContent = snapName;
    document.getElementById('snapshot-dialog').classList.add('active');
}

function closeSnapshotDialog() {
    document.getElementById('snapshot-dialog').classList.remove('active');
    pendingSnapshot = null;
}

async function confirmSnapshot() {
    if (!pendingSnapshot) return;
    const { vmName, folder } = pendingSnapshot;
    const btn = document.getElementById('snapshot-confirm-btn');

    btn.disabled = true;
    btn.textContent = 'Creating...';

    try {
        const res = await fetch(`${API}/api/snapshot`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ vm_name: vmName, folder }),
        });
        const data = await res.json();
        closeSnapshotDialog();
        if (data.success) {
            showToast(`Snapshot created: ${data.snapshot_name}`, 'success');
        } else {
            showToast(`Snapshot failed: ${data.message}`, 'error');
        }
    } catch (e) {
        closeSnapshotDialog();
        showToast(`Snapshot failed: ${e.message}`, 'error');
    } finally {
        btn.disabled = false;
        btn.textContent = 'Create Snapshot';
    }
}

function openRestoreDialog(vmName, folder) {
    pendingRestore = { vmName, folder };
    document.getElementById('restore-dialog-text').textContent =
        `Restore "${vmName}" to a snapshot?`;
    const select = document.getElementById('restore-snapshot-select');
    const confirmBtn = document.getElementById('restore-confirm-btn');
    select.innerHTML = '<option value="">Loading snapshots...</option>';
    select.disabled = true;
    confirmBtn.disabled = true;
    document.getElementById('restore-dialog').classList.add('active');
    loadSnapshotsForRestore(vmName, folder);
}

function closeRestoreDialog() {
    document.getElementById('restore-dialog').classList.remove('active');
    pendingRestore = null;
}

async function confirmRestoreSnapshot() {
    if (!pendingRestore) return;
    const { vmName, folder } = pendingRestore;
    const btn = document.getElementById('restore-confirm-btn');
    const snapshotName = document.getElementById('restore-snapshot-select').value;
    if (!snapshotName) {
        showToast('Please select a snapshot', 'error');
        return;
    }

    btn.disabled = true;
    btn.textContent = 'Restoring...';

    try {
        const res = await fetch(`${API}/api/restore-snapshot`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                vm_name: vmName,
                folder,
                snapshot_name: snapshotName,
            }),
        });
        const data = await res.json();
        closeRestoreDialog();
        showToast(data.message, data.success ? 'success' : 'error');
        if (data.success) loadVMs(true);
    } catch (e) {
        closeRestoreDialog();
        showToast(`Restore failed: ${e.message}`, 'error');
    } finally {
        btn.disabled = false;
        btn.textContent = 'Restore';
    }
}

async function loadSnapshotsForRestore(vmName, folder) {
    const select = document.getElementById('restore-snapshot-select');
    const confirmBtn = document.getElementById('restore-confirm-btn');
    try {
        const url = `${API}/api/snapshots?vm_name=${encodeURIComponent(vmName)}&folder=${encodeURIComponent(folder)}`;
        const res = await fetch(url);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const snapshots = await res.json();
        if (!Array.isArray(snapshots) || snapshots.length === 0) {
            select.innerHTML = '<option value="">No snapshots found</option>';
            select.disabled = true;
            confirmBtn.disabled = true;
            return;
        }
        select.innerHTML = snapshots
            .map((name, idx) => `<option value="${esc(name)}"${idx === 0 ? ' selected' : ''}>${esc(name)}</option>`)
            .join('');
        select.disabled = false;
        confirmBtn.disabled = false;
    } catch (e) {
        select.innerHTML = '<option value="">Failed to load snapshots</option>';
        select.disabled = true;
        confirmBtn.disabled = true;
        showToast(`Failed to load snapshots: ${e.message}`, 'error');
    }
}

// -- VM actions (stop, restart, delete) --------------------------------

function openActionDialog(action, vmName, folder) {
    pendingAction = { action, vmName, folder };
    const labels = {
        'power-on':  { title: 'Start VM', text: `Power on "${vmName}"?`, btn: 'Start', cls: 'start' },
        'power-off': { title: 'Stop VM', text: `Power off "${vmName}"?`, btn: 'Stop', cls: 'stop' },
        'restart':   { title: 'Restart VM', text: `Hard-restart "${vmName}"? This is equivalent to a power reset.`, btn: 'Restart', cls: 'restart' },
        'delete':    { title: 'Delete VM', text: `Permanently delete "${vmName}"? This cannot be undone.`, btn: 'Delete', cls: 'delete' },
    };
    const l = labels[action];
    document.getElementById('action-dialog-title').textContent = l.title;
    document.getElementById('action-dialog-text').textContent = l.text;
    const confirmBtn = document.getElementById('action-confirm-btn');
    confirmBtn.textContent = l.btn;
    confirmBtn.className = `btn btn-${l.cls === 'delete' ? 'danger' : 'primary'}`;
    document.getElementById('action-dialog').classList.add('active');
}

function closeActionDialog() {
    document.getElementById('action-dialog').classList.remove('active');
    pendingAction = null;
}

function closeRowMenus() {
    document.querySelectorAll('.row-menu[open]').forEach((menu) => {
        menu.removeAttribute('open');
    });
}

function openEnvAction(action, vmName, folder) {
    closeRowMenus();
    openActionDialog(action, vmName, folder);
}

function openSnapshotAction(action, vmName, folder) {
    closeRowMenus();
    if (action === 'create') {
        openSnapshotDialog(vmName, folder);
        return;
    }
    if (action === 'restore') {
        openRestoreDialog(vmName, folder);
    }
}

async function confirmAction() {
    if (!pendingAction) return;
    const { action, vmName, folder } = pendingAction;
    const btn = document.getElementById('action-confirm-btn');
    const origText = btn.textContent;

    btn.disabled = true;
    btn.textContent = 'Working...';

    try {
        const res = await fetch(`${API}/api/${action}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ vm_name: vmName, folder }),
        });
        const data = await res.json();
        closeActionDialog();
        showToast(data.message, data.success ? 'success' : 'error');
        if (data.success) loadVMs(true);
    } catch (e) {
        closeActionDialog();
        showToast(`Action failed: ${e.message}`, 'error');
    } finally {
        btn.disabled = false;
        btn.textContent = origText;
    }
}

function showToast(message, type) {
    const toast = document.createElement('div');
    toast.style.cssText = `
        position: fixed; bottom: 24px; right: 24px; padding: 14px 22px;
        border-radius: 10px; font-size: 0.88rem; z-index: 200;
        background: ${type === 'success' ? 'rgba(117,228,214,0.12)' : 'rgba(240,123,123,0.12)'};
        color: ${type === 'success' ? '#75e4d6' : '#f07b7b'};
        border: 1px solid ${type === 'success' ? 'rgba(117,228,214,0.25)' : 'rgba(240,123,123,0.25)'};
        backdrop-filter: blur(12px); max-width: 400px;
        animation: fadeIn 0.2s ease-out;
    `;
    toast.textContent = message;
    document.body.appendChild(toast);
    setTimeout(() => {
        toast.style.opacity = '0';
        toast.style.transition = 'opacity 0.3s';
        setTimeout(() => toast.remove(), 300);
    }, 4000);
}

// -- rendering --------------------------------------------------------

function renderFolderTabs() {
    const folders = [...new Set(allVMs.map(vm => vm.folder))];
    const container = document.getElementById('folder-tabs');
    container.innerHTML = '';

    if (!folderAutoSelected && currentUserEmail && folders.length > 0) {
        const prefix = getUserPrefix();
        if (prefix) {
            for (const f of folders) {
                if (f.toLowerCase().includes(prefix)) {
                    activeFolders.add(f);
                }
            }
        }
        folderAutoSelected = true;
    }

    const addBtn = document.createElement('button');
    addBtn.className = 'tab tab-add';
    addBtn.textContent = '+ Add vSphere Environment';
    addBtn.title = 'Add a vSphere folder to monitor';
    addBtn.onclick = openAddEnvDialog;
    container.appendChild(addBtn);
}

function renderStats() {
    const visible = filteredVMs();
    renderEnvControlPanel(allVMs);
}

function renderTable() {
    const tbody = document.getElementById('vm-tbody');
    const vms = filteredVMs();
    sortVMs(vms);

    if (vms.length === 0) {
        tbody.innerHTML = `<tr><td colspan="5" class="empty-state"><p>No VMs found</p></td></tr>`;
        return;
    }

    tbody.innerHTML = vms.map(vm => {
        const status = String(vm.status || '').toLowerCase();
        const isProvisioning = status === 'provisioning';
        const isOn = status === 'poweredon' || status === 'running';
        const isOff = status === 'poweredoff' || status === 'off' || status === 'stopped' || status === 'suspended';
        const n = escAttr(vm.name);
        const f = escAttr(vm.folder);
        const rowKey = vmRowKey(vm.name, vm.folder);
        const rk = escAttr(rowKey);
        const isExpanded = expandedVmKey === rowKey;

        return `
        <tr class="vm-main-row${isProvisioning ? ' row-provisioning' : ''}${isExpanded ? ' expanded' : ''}" onclick="toggleVmRow(event, '${rk}')">
            <td><strong>${esc(vm.name)}</strong></td>
            <td>${folderHierarchyHtml(vm.folder)}</td>
            <td class="date-cell">${vm.creation_date ? formatDate(vm.creation_date) : '--'}</td>
            <td>${vm.ip_address
                ? `<a class="ip-link" href="${esc(vm.connect_url)}" target="_blank" rel="noopener">${esc(vm.ip_address)}</a>`
                : '<span class="no-ip">No IP</span>'}</td>
            <td>${statusBadge(vm.status)}</td>
        </tr>
        ${isProvisioning || !isExpanded ? '' : `
        <tr class="vm-actions-row">
            <td colspan="5">
                <div class="expanded-actions-grid">
                    <section class="action-section">
                        <h4>Environment Actions</h4>
                        <div class="actions-cell">
                            <button class="btn-action menu-item start" onclick="openEnvAction('power-on','${n}','${f}')"
                                ${isOff ? '' : 'disabled'}>Start</button>
                            <button class="btn-action menu-item stop" onclick="openEnvAction('power-off','${n}','${f}')"
                                ${isOn ? '' : 'disabled'}>Stop</button>
                            <button class="btn-action menu-item restart" onclick="openEnvAction('restart','${n}','${f}')"
                                ${isOn ? '' : 'disabled'}>Restart</button>
                            <button class="btn-action menu-item delete" onclick="openEnvAction('delete','${n}','${f}')">Delete</button>
                        </div>
                    </section>
                    <section class="action-section">
                        <h4>Snapshot Actions</h4>
                        <div class="actions-cell">
                            <button class="btn-action menu-item snap" onclick="openSnapshotAction('create','${n}','${f}')">Create</button>
                            <button class="btn-action menu-item snap" onclick="openSnapshotAction('restore','${n}','${f}')">Restore</button>
                        </div>
                    </section>
                    <section class="action-section">
                        <h4>Env Upgrade</h4>
                        <div class="actions-cell">
                            <button class="btn-action menu-item" onclick="triggerPortalUpgrade('${n}','${f}')">Portal Upgrade (RPM)</button>
                            <button class="btn-action menu-item" onclick="triggerImageUpgrade('${n}','${f}')">Image Upgrade</button>
                        </div>
                    </section>
                </div>
            </td>
        </tr>`}`;
    }).join('');

    updateSortHeaders();
}

// -- sorting ----------------------------------------------------------

function sortBy(col) {
    if (sortCol === col) {
        sortDir = sortDir === 'asc' ? 'desc' : 'asc';
    } else {
        sortCol = col;
        sortDir = 'asc';
    }
    renderTable();
}

function sortVMs(vms) {
    const dir = sortDir === 'asc' ? 1 : -1;
    vms.sort((a, b) => {
        if (sortCol === 'creation_date') {
            const ta = toTime(a.creation_date);
            const tb = toTime(b.creation_date);
            if (ta < tb) return -1 * dir;
            if (ta > tb) return 1 * dir;
            return 0;
        }
        let va = a[sortCol] ?? '';
        let vb = b[sortCol] ?? '';
        if (typeof va === 'string') va = va.toLowerCase();
        if (typeof vb === 'string') vb = vb.toLowerCase();
        if (va < vb) return -1 * dir;
        if (va > vb) return 1 * dir;
        return 0;
    });
}

function updateSortHeaders() {
    document.querySelectorAll('thead th[data-col]').forEach(th => {
        const col = th.dataset.col;
        th.classList.toggle('sorted', col === sortCol);
        const arrow = th.querySelector('.sort-arrow');
        if (arrow) {
            arrow.textContent = col === sortCol
                ? (sortDir === 'asc' ? '\u25B2' : '\u25BC')
                : '\u25B2';
        }
    });
}

// -- filtering --------------------------------------------------------

function filteredVMs() {
    return allVMs.filter(vm => {
        if (activeFolders.size > 0 && !activeFolders.has(vm.folder)) return false;
        if (searchTerm) {
            const hay = `${vm.name} ${vm.portal_version || ''} ${vm.ip_address || ''} ${vm.folder}`.toLowerCase();
            if (!hay.includes(searchTerm)) return false;
        }
        return true;
    });
}

// -- helpers ----------------------------------------------------------

function statusBadge(status) {
    if (status === 'provisioning') {
        return '<span class="vm-status provisioning"><span class="vm-status-dot"></span>Provisioning</span>';
    }
    const label = status.replace('powered', '').replace('On', 'Running').replace('Off', 'Off');
    const cls = status === 'poweredOn' ? 'poweredOn'
        : status === 'poweredOff' ? 'poweredOff'
        : 'suspended';
    return `<span class="vm-status ${cls}"><span class="vm-status-dot"></span>${label}</span>`;
}

function formatDate(iso) {
    try {
        const d = new Date(iso);
        return d.toLocaleDateString('en-IL', { year: 'numeric', month: 'short', day: 'numeric' });
    } catch {
        return iso;
    }
}

function getUserPrefix() {
    if (!currentUserEmail) return '';
    return currentUserEmail.split('@')[0].toLowerCase();
}

function shortFolderPath(folderPath) {
    if (!folderPath) return '';
    const parts = folderPath.split('/').filter(Boolean);
    return parts.slice(-3).join('/');
}

function folderHierarchyHtml(folderPath) {
    if (!folderPath) return '';
    const parts = folderPath.split('/').filter(Boolean);
    const display = parts.slice(-3);
    return `<div class="folder-hierarchy" title="${esc(folderPath)}">${
        display.map((p, i) => {
            const isLast = i === display.length - 1;
            return `<span class="${isLast ? 'folder-current' : 'folder-ancestor'}">${esc(p)}</span>`;
        }).join('')
    }</div>`;
}

// -- add environment dialog -------------------------------------------

let _browsePath = '';

async function openAddEnvDialog() {
    try {
        const res = await fetch(`${API}/api/config/folders`);
        const data = await res.json();
        configuredFolderSet = new Set(data.folders || []);
    } catch {
        configuredFolderSet = new Set();
    }
    document.getElementById('add-env-status').textContent = '';
    document.getElementById('add-env-status').className = 'action-status';
    document.getElementById('quick-add-section').innerHTML = '';
    document.getElementById('add-env-dialog').classList.add('active');
    browseTo('');
    loadQuickAddSuggestions();
}

async function loadQuickAddSuggestions() {
    const prefix = getUserPrefix();
    if (!prefix) return;

    const parentPaths = [
        'Technical Teams/Engineering',
        'Technical Teams/Engineering/Portal Sandbox',
    ];

    const found = [];
    await Promise.all(parentPaths.map(async (parent) => {
        try {
            const res = await fetch(`${API}/api/vsphere/browse?path=${encodeURIComponent(parent)}`);
            const data = await res.json();
            if (!data.success || !Array.isArray(data.items)) return;
            for (const item of data.items) {
                if (item.type === 'folder' && item.name.toLowerCase() === prefix) {
                    found.push(item);
                }
            }
        } catch { /* ignore */ }
    }));

    const suggestions = found.filter(f => !configuredFolderSet.has(f.path));
    if (suggestions.length === 0) return;

    const container = document.getElementById('quick-add-section');
    container.innerHTML = `<div class="quick-add-box">
        <div class="quick-add-label">Your environments</div>
        ${suggestions.map(f => {
            const p = escAttr(f.path);
            const vmLabel = f.vm_count === 1 ? '1 VM' : `${f.vm_count} VMs`;
            return `<div class="quick-add-item">
                <span class="quick-add-path">${esc(f.path)}</span>
                ${f.vm_count > 0 ? `<span class="browse-vm-count">${vmLabel}</span>` : ''}
                <button class="btn btn-small btn-primary" onclick="quickAddFolder('${p}', this)">+ Add</button>
            </div>`;
        }).join('')}
    </div>`;
}

async function quickAddFolder(folder, btn) {
    btn.disabled = true;
    btn.textContent = 'Adding...';
    try {
        const res = await fetch(`${API}/api/config/folders`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ folder }),
        });
        const data = await res.json();
        if (data.success) {
            configuredFolderSet.add(folder);
            activeFolders.add(folder);
            btn.textContent = 'Added';
            btn.className = 'btn btn-small btn-secondary';
            loadVMs(true);
        } else {
            btn.textContent = '+ Add';
            btn.disabled = false;
            showToast(data.message || 'Failed to add', 'error');
        }
    } catch (e) {
        btn.textContent = '+ Add';
        btn.disabled = false;
        showToast(`Failed: ${e.message}`, 'error');
    }
}

function closeAddEnvDialog() {
    document.getElementById('add-env-dialog').classList.remove('active');
}

async function browseTo(path) {
    _browsePath = path;
    renderBrowseBreadcrumb(path);
    const list = document.getElementById('browse-list');
    list.innerHTML = '<div class="browse-loading"><span class="spinner"></span> Loading...</div>';
    try {
        const res = await fetch(`${API}/api/vsphere/browse?path=${encodeURIComponent(path)}`);
        const data = await res.json();
        if (!data.success) {
            list.innerHTML = `<div class="browse-empty">${esc(data.message || 'Failed to load')}</div>`;
            return;
        }
        renderBrowseList(data.items.filter(i => !i.name.startsWith('_')));
    } catch (e) {
        list.innerHTML = `<div class="browse-empty">Failed: ${esc(e.message)}</div>`;
    }
}

function renderBrowseBreadcrumb(path) {
    const container = document.getElementById('browse-breadcrumb');
    const parts = path ? path.split('/') : [];
    let html = `<span class="crumb clickable" onclick="browseTo('')">Root</span>`;
    let accumulated = '';
    for (let i = 0; i < parts.length; i++) {
        accumulated += (i === 0 ? '' : '/') + parts[i];
        const p = escAttr(accumulated);
        html += `<span class="crumb-sep">/</span>`;
        if (i < parts.length - 1) {
            html += `<span class="crumb clickable" onclick="browseTo('${p}')">${esc(parts[i])}</span>`;
        } else {
            html += `<span class="crumb">${esc(parts[i])}</span>`;
        }
    }
    container.innerHTML = html;
}

function renderBrowseList(items) {
    const list = document.getElementById('browse-list');
    if (items.length === 0) {
        list.innerHTML = '<div class="browse-empty">This folder is empty</div>';
        return;
    }
    list.innerHTML = items.map(item => {
        const p = escAttr(item.path);
        const isAdded = configuredFolderSet.has(item.path);
        const canAdd = item.type === 'folder';
        const canNavigate = item.has_children;
        const vmLabel = item.vm_count === 1 ? '1 VM' : `${item.vm_count} VMs`;

        let addBtn = '';
        if (canAdd) {
            addBtn = `<button class="btn btn-small browse-add-btn ${isAdded ? 'btn-secondary' : 'btn-primary'}"
                        onclick="event.stopPropagation(); addFolderFromDialog('${p}')"
                        ${isAdded ? 'disabled' : ''}>
                    ${isAdded ? 'Added' : '+ Add'}
                </button>`;
        }

        const clickHandler = canNavigate ? `onclick="browseTo('${p}')"` : '';
        const navClass = canNavigate ? ' navigable' : '';
        const typeClass = item.type === 'datacenter' ? ' type-datacenter' : '';

        return `<div class="browse-item${navClass}${typeClass}" ${clickHandler}>
            <span class="browse-name">${esc(item.name)}</span>
            ${item.vm_count > 0 ? `<span class="browse-vm-count">${vmLabel}</span>` : ''}
            ${addBtn}
            ${canNavigate ? '<span class="browse-chevron">&#8250;</span>' : ''}
        </div>`;
    }).join('');
}

async function addFolderFromDialog(folder) {
    const statusEl = document.getElementById('add-env-status');
    try {
        const res = await fetch(`${API}/api/config/folders`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ folder }),
        });
        const data = await res.json();
        if (data.success) {
            configuredFolderSet.add(folder);
            activeFolders.add(folder);
            loadVMs(true);
            closeAddEnvDialog();
            showToast(`Added: ${folder}`, 'success');
        } else {
            statusEl.className = 'action-status error';
            statusEl.textContent = data.message || 'Failed to add folder';
        }
    } catch (e) {
        statusEl.className = 'action-status error';
        statusEl.textContent = `Failed: ${e.message}`;
    }
}

function vmRowKey(name, folder) {
    return `${name}@@${folder}`;
}

function toggleVmRow(event, rowKey) {
    if (event?.target?.closest('a, button, summary, input, select, label')) return;
    if (expandedVmKey === rowKey) expandedVmKey = null;
    else expandedVmKey = rowKey;
    closeRowMenus();
    renderTable();
}

function triggerPortalUpgrade(vmName, folder) {
    const rpm = window.prompt(`Enter RPM name/path for "${vmName}"`);
    if (!rpm) return;
    showToast(`Portal upgrade queued for "${vmName}" with RPM: ${rpm}`, 'success');
}

function triggerImageUpgrade(vmName, folder) {
    const imageVersion = window.prompt(`Enter target image version for "${vmName}"`);
    if (!imageVersion) return;
    showToast(`Image upgrade queued for "${vmName}" to version: ${imageVersion}`, 'success');
}

function toTime(iso) {
    const t = Date.parse(iso || '');
    return Number.isNaN(t) ? 0 : t;
}

function normalizeStatus(status) {
    return String(status || '').toLowerCase();
}

function isRunningStatus(status) {
    const s = normalizeStatus(status);
    return s === 'poweredon' || s === 'running';
}

function isStoppedStatus(status) {
    const s = normalizeStatus(status);
    return s === 'poweredoff' || s === 'off' || s === 'stopped' || s === 'suspended';
}

let allSuggestions = [];

function renderEnvControlPanel(vms) {
    renderSuggestions(vms);
}

function renderSuggestions(vms) {
    const container = document.getElementById('suggestions-list');
    const noSuggestion = document.getElementById('no-suggestion');

    const prefix = getUserPrefix();
    const userVMs = prefix
        ? vms.filter(v => `${v.name} ${v.folder}`.toLowerCase().includes(prefix))
        : vms;
    allSuggestions = pickSuggestions(userVMs);
    if (allSuggestions.length === 0) {
        currentSuggestionVMs = [];
        container.innerHTML = '';
        noSuggestion.style.display = 'block';
        return;
    }

    noSuggestion.style.display = 'none';
    container.innerHTML = allSuggestions.map((s, idx) =>
        `<div class="suggestion-box">
            <div class="suggestion-title">${esc(s.title)}</div>
            <div class="suggestion-meta">${s.vms.length} environment(s) found</div>
            <div class="suggestion-names">${esc(summarizeEnvNames(s.vms))}</div>
            <button class="btn btn-danger btn-full" onclick="deleteSuggestionEnvs(${idx})">
                Delete
            </button>
        </div>`
    ).join('');
}

function pickSuggestions(vms) {
    const suggestions = [];
    const now = Date.now();
    const dayMs = 24 * 60 * 60 * 1000;

    const oldStopped = vms.filter((v) => {
        const created = toTime(v.creation_date);
        return created > 0 && now - created > (3 * dayMs) && isStoppedStatus(v.status);
    });
    if (oldStopped.length > 0) {
        suggestions.push({
            title: 'Suggestion: delete stopped environments older than 3 days.',
            vms: oldStopped,
        });
    }

    const notRunning = vms.filter((v) => !isRunningStatus(v.status) && v.status !== 'provisioning');
    if (notRunning.length > 0) {
        suggestions.push({
            title: 'Suggestion: delete non-running environments.',
            vms: notRunning,
        });
    }

    const veryOld = vms.filter((v) => {
        const created = toTime(v.creation_date);
        return created > 0 && now - created > (30 * dayMs);
    });
    if (veryOld.length > 0) {
        suggestions.push({
            title: 'Suggestion: remove environments older than 1 month.',
            vms: veryOld,
        });
    }

    return suggestions;
}

function summarizeEnvNames(vms) {
    const names = vms.map(v => v.name);
    const preview = names.slice(0, 6).join(', ');
    if (names.length <= 6) return preview;
    return `${preview} ... +${names.length - 6} more`;
}

function templateMetaLine(tpl) {
    const parts = [];
    if (tpl.portal_version) {
        parts.push(`Version ${tpl.portal_version}`);
    }
    if (tpl.creation_date) {
        parts.push(`Created ${formatDate(tpl.creation_date)}`);
    }
    if (tpl.folder) {
        parts.push(shortFolderPath(tpl.folder));
    }
    if (parts.length === 0) return 'No additional metadata';
    return parts.join(' · ');
}

async function deleteSuggestionEnvs(idx) {
    const suggestion = allSuggestions[idx];
    if (!suggestion || suggestion.vms.length === 0) return;
    const ok = window.confirm(`Delete ${suggestion.vms.length} suggested environment(s)?`);
    if (!ok) return;

    const buttons = document.querySelectorAll('#suggestions-list .btn-danger');
    const btn = buttons[idx];
    if (btn) { btn.disabled = true; btn.textContent = 'Deleting...'; }

    let success = 0;
    let failed = 0;
    for (const vm of suggestion.vms) {
        try {
            const res = await fetch(`${API}/api/delete`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ vm_name: vm.name, folder: vm.folder }),
            });
            const data = await res.json();
            if (data.success) success += 1;
            else failed += 1;
        } catch {
            failed += 1;
        }
    }

    if (btn) { btn.disabled = false; btn.textContent = 'Delete'; }
    showToast(`Delete finished: ${success} deleted, ${failed} failed`, failed ? 'error' : 'success');
    loadVMs(true);
}

function esc(s) {
    if (!s) return '';
    const d = document.createElement('div');
    d.textContent = s;
    return d.innerHTML;
}

function escAttr(s) {
    if (!s) return '';
    return s.replace(/\\/g, '\\\\').replace(/'/g, "\\'");
}

function showLoading(show) {
    document.getElementById('loading-overlay').style.display = show ? 'flex' : 'none';
    document.getElementById('vm-table').style.display = show ? 'none' : '';
}

function showError(msg) {
    const el = document.getElementById('error-banner');
    el.textContent = msg;
    el.classList.add('visible');
}

function hideError() {
    document.getElementById('error-banner').classList.remove('visible');
}

// -- jenkins jobs -----------------------------------------------------

let _activeJenkinsJobName = '';

function getVmNameFromEmail() {
    if (!currentUserEmail) return '';
    const local = currentUserEmail.split('@')[0] || '';
    return local.toUpperCase();
}

async function loadJenkinsJobs() {
    try {
        const res = await fetch(`${API}/api/jenkins/saved-jobs`);
        const data = await res.json();
        savedJenkinsJobs = data.jobs || [];
    } catch {
        savedJenkinsJobs = [];
    }
    renderJenkinsJobs();
}

function renderJenkinsJobs() {
    const container = document.getElementById('jenkins-jobs-list');
    if (savedJenkinsJobs.length === 0) {
        container.innerHTML = '<p class="jenkins-no-jobs">No Jenkins jobs configured. Click "+ Add Job" to get started.</p>';
        return;
    }
    container.innerHTML = savedJenkinsJobs.map(job => {
        const j = escAttr(job);
        return `<div class="jenkins-job-chip">
            <button class="jenkins-job-btn" onclick="openJenkinsBuildDialog('${j}')" title="Build ${esc(job)}">${esc(job)}</button>
            <button class="jenkins-job-remove" onclick="removeJenkinsJob('${j}')" title="Remove job">&times;</button>
        </div>`;
    }).join('');
}

async function removeJenkinsJob(jobName) {
    try {
        const res = await fetch(`${API}/api/jenkins/saved-jobs`, {
            method: 'DELETE',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ job_name: jobName }),
        });
        const data = await res.json();
        if (data.success) {
            savedJenkinsJobs = savedJenkinsJobs.filter(j => j !== jobName);
            renderJenkinsJobs();
            showToast(`Removed job: ${jobName}`, 'success');
        } else {
            showToast(data.message, 'error');
        }
    } catch (e) {
        showToast(`Failed to remove job: ${e.message}`, 'error');
    }
}

async function addJenkinsJob(jobName) {
    const statusEl = document.getElementById('add-jenkins-job-status');
    try {
        const res = await fetch(`${API}/api/jenkins/saved-jobs`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ job_name: jobName }),
        });
        const data = await res.json();
        if (data.success) {
            savedJenkinsJobs.push(jobName);
            renderJenkinsJobs();
            statusEl.className = 'action-status success';
            statusEl.textContent = `Added: ${jobName}`;
            renderJenkinsJobSearchResults();
        } else {
            statusEl.className = 'action-status error';
            statusEl.textContent = data.message;
        }
    } catch (e) {
        statusEl.className = 'action-status error';
        statusEl.textContent = `Failed: ${e.message}`;
    }
}

// -- add jenkins job dialog -------------------------------------------

let _jenkinsJobSearchCache = [];

function openAddJenkinsJobDialog() {
    document.getElementById('jenkins-job-search-input').value = '';
    document.getElementById('add-jenkins-job-status').textContent = '';
    document.getElementById('add-jenkins-job-status').className = 'action-status';
    document.getElementById('jenkins-job-search-results').innerHTML =
        '<div class="browse-loading"><span class="spinner"></span> Loading jobs...</div>';
    document.getElementById('add-jenkins-job-dialog').classList.add('active');
    searchJenkinsJobs('');
    setTimeout(() => document.getElementById('jenkins-job-search-input').focus(), 50);
}

function closeAddJenkinsJobDialog() {
    document.getElementById('add-jenkins-job-dialog').classList.remove('active');
    if (jenkinsJobSearchTimer) clearTimeout(jenkinsJobSearchTimer);
}

function debounceJenkinsJobSearch() {
    if (jenkinsJobSearchTimer) clearTimeout(jenkinsJobSearchTimer);
    const query = document.getElementById('jenkins-job-search-input').value.trim();
    document.getElementById('jenkins-job-search-results').innerHTML =
        '<div class="browse-loading"><span class="spinner"></span> Searching...</div>';
    jenkinsJobSearchTimer = setTimeout(() => searchJenkinsJobs(query), 300);
}

async function searchJenkinsJobs(query) {
    const container = document.getElementById('jenkins-job-search-results');
    try {
        const res = await fetch(`${API}/api/jenkins/search-jobs?query=${encodeURIComponent(query)}`);
        if (!res.ok) {
            const err = await res.text();
            throw new Error(err || `Server returned ${res.status}`);
        }
        const data = await res.json();
        _jenkinsJobSearchCache = Array.isArray(data) ? data : [];
        renderJenkinsJobSearchResults();
    } catch (e) {
        container.innerHTML = `<div class="browse-empty">Failed to search: ${esc(e.message)}</div>`;
    }
}

function renderJenkinsJobSearchResults() {
    const container = document.getElementById('jenkins-job-search-results');
    const jobs = _jenkinsJobSearchCache;
    if (jobs.length === 0) {
        container.innerHTML = '<div class="browse-empty">No jobs found</div>';
        return;
    }
    const savedSet = new Set(savedJenkinsJobs);
    container.innerHTML = jobs.map(job => {
        const j = escAttr(job.name);
        const isSaved = savedSet.has(job.name);
        const colorCls = job.color === 'blue' ? 'job-ok'
            : job.color === 'red' ? 'job-fail'
            : job.color === 'disabled' ? 'job-disabled'
            : (job.color || '').includes('anime') ? 'job-building'
            : '';
        return `<div class="jenkins-job-search-item">
            <span class="jenkins-job-search-dot ${colorCls}"></span>
            <span class="jenkins-job-search-name">${esc(job.name)}</span>
            <button class="btn btn-small${isSaved ? ' btn-secondary' : ' btn-primary'}"
                onclick="addJenkinsJob('${j}')" ${isSaved ? 'disabled' : ''}>
                ${isSaved ? 'Added' : '+ Add'}
            </button>
        </div>`;
    }).join('');
}

// -- jenkins build dialog (parameterized) -----------------------------

async function openJenkinsBuildDialog(jobName) {
    _activeJenkinsJobName = jobName;
    const dialog = document.getElementById('jenkins-params-dialog');
    const loading = document.getElementById('jenkins-params-loading');
    const form = document.getElementById('jenkins-params-form');
    const submitBtn = document.getElementById('jenkins-params-submit');
    const subtitle = document.getElementById('jenkins-params-subtitle');
    const status = document.getElementById('jenkins-params-status');

    form.innerHTML = '';
    loading.style.display = 'flex';
    submitBtn.disabled = true;
    status.textContent = '';
    status.className = 'action-status';
    subtitle.textContent = jobName;

    dialog.classList.add('active');

    try {
        const res = await fetch(`${API}/api/jenkins/job/params?job_name=${encodeURIComponent(jobName)}`);
        const data = await res.json();

        loading.style.display = 'none';

        if (!data.success) {
            form.innerHTML = `<div class="jenkins-params-error">${esc(data.message)}</div>`;
            return;
        }

        if (data.parameters.length === 0) {
            form.innerHTML = '<div class="jenkins-params-empty">This job has no parameters.</div>';
            submitBtn.disabled = false;
            return;
        }

        renderJenkinsParams(data.parameters);
        submitBtn.disabled = false;
    } catch (e) {
        loading.style.display = 'none';
        form.innerHTML = `<div class="jenkins-params-error">Failed to load parameters: ${esc(e.message)}</div>`;
    }
}

function renderJenkinsParams(params) {
    const form = document.getElementById('jenkins-params-form');

    form.innerHTML = params.map(p => {
        const id = `jp-${p.name}`;
        const label = p.description || p.name;

        if (p.type === 'ChoiceParameterDefinition' && p.choices) {
            const options = p.choices.map(c =>
                `<option value="${esc(c)}">${esc(c)}</option>`
            ).join('');
            return `<div class="jp-field">
                <label for="${id}">${esc(label)}</label>
                <select id="${id}" class="panel-select" data-param="${esc(p.name)}">${options}</select>
            </div>`;
        }

        if (p.type === 'BooleanParameterDefinition') {
            return `<div class="jp-field jp-field-bool">
                <label class="jp-checkbox-label">
                    <input type="checkbox" id="${id}" data-param="${esc(p.name)}">
                    <span>${esc(label)}</span>
                </label>
            </div>`;
        }

        if (p.type === 'TextParameterDefinition') {
            return `<div class="jp-field">
                <label for="${id}">${esc(label)}</label>
                <textarea id="${id}" class="panel-input jp-textarea" data-param="${esc(p.name)}"></textarea>
            </div>`;
        }

        if (p.type === 'PasswordParameterDefinition') {
            return `<div class="jp-field">
                <label for="${id}">${esc(label)}</label>
                <input type="password" id="${id}" class="panel-input" data-param="${esc(p.name)}">
            </div>`;
        }

        return `<div class="jp-field">
            <label for="${id}">${esc(label)}</label>
            <input type="text" id="${id}" class="panel-input" data-param="${esc(p.name)}">
        </div>`;
    }).join('');

    params.forEach(p => {
        const el = document.getElementById(`jp-${p.name}`);
        if (!el) return;

        let val = p.default_value || '';
        if ((p.name === 'VM_NAMES' || p.name === 'VM_NAME') && !val) {
            val = getVmNameFromEmail();
        }

        if (p.type === 'BooleanParameterDefinition') {
            el.checked = val === 'true';
        } else {
            el.value = val;
        }
    });
}

function closeJenkinsParamsDialog() {
    document.getElementById('jenkins-params-dialog').classList.remove('active');
    _activeJenkinsJobName = '';
}

// -- jenkins builds (your builds) -------------------------------------

async function loadJenkinsBuilds() {
    const container = document.getElementById('jenkins-builds-list');
    if (savedJenkinsJobs.length === 0) {
        jenkinsBuilds = [];
        container.innerHTML = '<div class="jenkins-builds-placeholder">Add Jenkins jobs above to see your builds.</div>';
        scheduleBuildPoll();
        return;
    }

    try {
        const promises = savedJenkinsJobs.map(job =>
            fetch(`${API}/api/jenkins/builds?job_name=${encodeURIComponent(job)}&limit=10`)
                .then(r => r.ok ? r.json() : [])
                .catch(() => [])
        );
        const results = await Promise.all(promises);
        jenkinsBuilds = results.flat()
            .sort((a, b) => (b.timestamp || 0) - (a.timestamp || 0))
            .slice(0, 10);
    } catch {
        jenkinsBuilds = [];
    }

    renderJenkinsBuilds();
    scheduleBuildPoll();
}

function scheduleBuildPoll() {
    if (jenkinsBuildsTimer) {
        clearTimeout(jenkinsBuildsTimer);
        jenkinsBuildsTimer = null;
    }
    const hasBuilding = jenkinsBuilds.some(b => b.status === 'BUILDING');
    if (hasBuilding) {
        jenkinsBuildsTimer = setTimeout(() => loadJenkinsBuilds(), 15000);
    }
}

function renderJenkinsBuilds() {
    const container = document.getElementById('jenkins-builds-list');

    if (jenkinsBuilds.length === 0) {
        container.innerHTML = '<div class="jenkins-builds-placeholder">No recent builds found.</div>';
        return;
    }

    container.innerHTML = jenkinsBuilds.map(build => {
        const isBuilding = build.status === 'BUILDING';
        const isFailed = build.status === 'FAILURE' || build.status === 'ABORTED';
        const isSuccess = build.status === 'SUCCESS';
        const isUnstable = build.status === 'UNSTABLE';

        const statusCls = isBuilding ? 'building'
            : isFailed ? 'failed'
            : isSuccess ? 'success'
            : isUnstable ? 'unstable'
            : 'other';

        const duration = build.duration_s
            ? `${Math.floor(build.duration_s / 60)}m ${build.duration_s % 60}s`
            : '';

        const timeAgo = build.timestamp ? formatTimeAgo(build.timestamp) : '';

        const jn = escAttr(build.job_name);
        const retryBtn = isFailed
            ? `<button class="btn btn-small btn-primary jenkins-retry-btn" onclick="event.stopPropagation(); retryJenkinsBuild('${jn}', ${build.number}, this)">Retry</button>`
            : '';

        const shortJob = build.job_name.length > 32
            ? build.job_name.substring(0, 29) + '...'
            : build.job_name;

        return `<div class="jenkins-build-item">
            <div class="build-bar ${statusCls}"></div>
            <div class="build-info">
                <div class="build-main">
                    <a class="build-number" href="${esc(build.url)}" target="_blank" rel="noopener">#${build.number}</a>
                    <span class="build-job-name" title="${esc(build.job_name)}">${esc(shortJob)}</span>
                </div>
                <div class="build-meta">
                    ${build.branch ? `<span class="build-branch">${esc(build.branch)}</span>` : ''}
                    ${build.vm_names ? `<span class="build-vms">${esc(build.vm_names)}</span>` : ''}
                    ${duration ? `<span class="build-duration">${duration}</span>` : ''}
                    ${timeAgo ? `<span class="build-time">${timeAgo}</span>` : ''}
                </div>
            </div>
            <div class="build-badge ${statusCls}">${isBuilding ? 'In Progress' : esc(build.status)}</div>
            ${retryBtn}
        </div>`;
    }).join('');
}

async function retryJenkinsBuild(jobName, buildNumber, btn) {
    btn.disabled = true;
    btn.textContent = 'Retrying...';

    try {
        const res = await fetch(`${API}/api/jenkins/rebuild`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ job_name: jobName, build_number: buildNumber }),
        });
        const data = await res.json();
        showToast(data.message, data.success ? 'success' : 'error');
        if (data.success) {
            setTimeout(() => loadJenkinsBuilds(), 3000);
        }
    } catch (e) {
        showToast(`Retry failed: ${e.message}`, 'error');
    } finally {
        btn.disabled = false;
        btn.textContent = 'Retry';
    }
}

function formatTimeAgo(timestamp) {
    const diff = Date.now() - timestamp;
    const minutes = Math.floor(diff / 60000);
    const hours = Math.floor(diff / 3600000);
    const days = Math.floor(diff / 86400000);

    if (minutes < 1) return 'just now';
    if (minutes < 60) return `${minutes}m ago`;
    if (hours < 24) return `${hours}h ago`;
    return `${days}d ago`;
}

// -- jenkins build dialog (parameterized) -----------------------------

async function submitJenkinsBuild() {
    const submitBtn = document.getElementById('jenkins-params-submit');
    const status = document.getElementById('jenkins-params-status');
    const jobName = _activeJenkinsJobName;

    const params = {};
    document.querySelectorAll('#jenkins-params-form [data-param]').forEach(el => {
        const name = el.dataset.param;
        if (el.type === 'checkbox') {
            params[name] = el.checked ? 'true' : 'false';
        } else {
            params[name] = el.value;
        }
    });

    submitBtn.disabled = true;
    submitBtn.textContent = 'Triggering...';
    status.className = 'action-status loading';
    status.textContent = 'Sending build request to Jenkins...';

    try {
        const res = await fetch(`${API}/api/jenkins/build`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ job_name: jobName, parameters: params }),
        });
        const data = await res.json();
        status.className = `action-status ${data.success ? 'success' : 'error'}`;
        status.textContent = data.message;
        if (data.success) {
            const mainStatus = document.getElementById('jenkins-build-status');
            mainStatus.className = 'action-status success';
            mainStatus.textContent = data.message;
            setTimeout(() => {
                closeJenkinsParamsDialog();
                loadJenkinsBuilds();
            }, 1500);
        }
    } catch (e) {
        status.className = 'action-status error';
        status.textContent = `Build trigger failed: ${e.message}`;
    } finally {
        submitBtn.disabled = false;
        submitBtn.textContent = 'Build';
    }
}


