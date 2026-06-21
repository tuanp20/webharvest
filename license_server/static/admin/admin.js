/**
 * WebHarvest Admin Dashboard — Client-side JavaScript
 * Handles authentication, navigation, data loading, and CRUD operations.
 */

const API = '';  // Same origin
let authToken = localStorage.getItem('wh_admin_token') || '';

// ── API Helper ───────────────────────────────────────────────────────────

async function api(endpoint, options = {}) {
    const headers = { 'Content-Type': 'application/json' };
    if (authToken) headers['Authorization'] = `Bearer ${authToken}`;

    const resp = await fetch(`${API}${endpoint}`, { ...options, headers: { ...headers, ...options.headers } });

    if (resp.status === 401) {
        authToken = '';
        localStorage.removeItem('wh_admin_token');
        showLogin();
        throw new Error('Unauthorized');
    }

    const data = await resp.json();
    if (!resp.ok && !data.success) throw new Error(data.detail || data.error || 'Request failed');
    return data;
}

function formatVND(n) {
    if (!n && n !== 0) return '—';
    return new Intl.NumberFormat('vi-VN').format(n) + 'đ';
}

function formatDate(iso) {
    if (!iso) return '—';
    const d = new Date(iso);
    return d.toLocaleDateString('vi-VN', { day: '2-digit', month: '2-digit', year: 'numeric' });
}

function formatDateTime(iso) {
    if (!iso) return '—';
    const d = new Date(iso);
    return d.toLocaleString('vi-VN', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' });
}

function shortKey(key) {
    if (!key) return '—';
    return key.length > 16 ? key.slice(0, 8) + '…' + key.slice(-5) : key;
}

function tierBadge(tier) { return `<span class="badge badge-${tier}">${(tier || '').toUpperCase()}</span>`; }
function statusBadge(s) { return `<span class="badge badge-${s}">${(s || '').toUpperCase()}</span>`; }

// ── Auth ─────────────────────────────────────────────────────────────────

function showLogin() {
    document.getElementById('loginScreen').style.display = 'flex';
    document.getElementById('mainApp').style.display = 'none';
}

function showApp() {
    document.getElementById('loginScreen').style.display = 'none';
    document.getElementById('mainApp').style.display = 'flex';
    loadOverview();
}

document.getElementById('loginForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    const pw = document.getElementById('loginPassword').value;
    const errEl = document.getElementById('loginError');
    errEl.style.display = 'none';

    try {
        const res = await api('/api/admin/auth', { method: 'POST', body: JSON.stringify({ password: pw }) });
        authToken = res.token;
        localStorage.setItem('wh_admin_token', authToken);
        showApp();
    } catch (err) {
        errEl.textContent = 'Invalid password';
        errEl.style.display = 'block';
    }
});

document.getElementById('logoutBtn').addEventListener('click', () => {
    authToken = '';
    localStorage.removeItem('wh_admin_token');
    showLogin();
});

// ── Navigation ───────────────────────────────────────────────────────────

const navItems = document.querySelectorAll('.nav-item');
const pages = document.querySelectorAll('.page');

navItems.forEach(btn => {
    btn.addEventListener('click', () => {
        const page = btn.dataset.page;
        navItems.forEach(n => n.classList.remove('active'));
        btn.classList.add('active');
        pages.forEach(p => p.classList.remove('active'));
        document.getElementById('page' + page.charAt(0).toUpperCase() + page.slice(1)).classList.add('active');

        // Load data
        if (page === 'overview') loadOverview();
        else if (page === 'keys') loadKeys();
        else if (page === 'requests') loadRequests();
        else if (page === 'revenue') loadRevenue();
    });
});

// ── Overview ─────────────────────────────────────────────────────────────

async function loadOverview() {
    const from = document.getElementById('overviewDateFrom').value;
    const to = document.getElementById('overviewDateTo').value;
    let qs = '';
    if (from) qs += `date_from=${from}&`;
    if (to) qs += `date_to=${to}&`;

    try {
        const res = await api(`/api/admin/dashboard?${qs}`);
        const d = res.data;

        document.getElementById('statTotalUsers').textContent = d.devices || 0;
        document.getElementById('statActiveKeys').textContent = d.keys?.active || 0;
        document.getElementById('statExpiredKeys').textContent = d.keys?.expired || 0;
        document.getElementById('statRevenue').textContent = formatVND(d.revenue?.total_vnd);
        document.getElementById('statRequests').textContent = (d.requests?.total || 0).toLocaleString();

        // Tier chart (simple bar visualization)
        renderTierChart(d.tiers || {});

        // Recent keys
        loadRecentActivity();
    } catch (err) {
        console.error('Dashboard load failed:', err);
    }
}

function renderTierChart(tiers) {
    const canvas = document.getElementById('chartTiers');
    const ctx = canvas.getContext('2d');
    ctx.clearRect(0, 0, canvas.width, canvas.height);

    const data = [
        { label: 'Basic', value: tiers.basic || 0, color: '#0071e3' },
        { label: 'Pro', value: tiers.pro || 0, color: '#5e5ce6' },
        { label: 'Unlimited', value: tiers.unlimited || 0, color: '#d33d95' },
    ];
    const total = data.reduce((s, d) => s + d.value, 0) || 1;
    const barH = 36, gap = 16, startY = 20;

    data.forEach((d, i) => {
        const y = startY + i * (barH + gap);
        const pct = d.value / total;
        const barW = Math.max(4, pct * (canvas.width - 140));

        // Background bar
        ctx.fillStyle = 'rgba(0,0,0,0.04)';
        ctx.beginPath();
        ctx.roundRect(0, y, canvas.width - 80, barH, 6);
        ctx.fill();

        // Fill bar
        ctx.fillStyle = d.color;
        ctx.globalAlpha = 0.85;
        ctx.beginPath();
        ctx.roundRect(0, y, barW, barH, 6);
        ctx.fill();
        ctx.globalAlpha = 1;

        // Label
        ctx.fillStyle = '#1d1d1f';
        ctx.font = '500 13px "Plus Jakarta Sans", -apple-system, sans-serif';
        ctx.fillText(d.label, 12, y + 23);

        // Count
        ctx.fillStyle = '#86868b';
        ctx.font = '600 14px "Plus Jakarta Sans", -apple-system, sans-serif';
        ctx.fillText(d.value, canvas.width - 70, y + 23);
    });
}

async function loadRecentActivity() {
    try {
        const res = await api('/api/admin/keys?limit=8');
        const el = document.getElementById('recentActivity');
        el.innerHTML = res.data.map(k => `
            <div class="activity-item">
                <span class="key-mono" onclick="viewKeyDetail('${k.key}')">${shortKey(k.key)}</span>
                ${tierBadge(k.tier)} ${statusBadge(k.status)}
                <span style="color:var(--text-muted);margin-left:auto">${formatDate(k.created_at)}</span>
            </div>
        `).join('') || '<p style="color:var(--text-muted);padding:20px">No keys yet</p>';
    } catch (err) { console.error(err); }
}

document.getElementById('overviewFilterBtn').addEventListener('click', loadOverview);

// ── Keys ─────────────────────────────────────────────────────────────────

let keysPage = 1;

async function loadKeys(page = 1) {
    keysPage = page;
    const tier = document.getElementById('keysFilterTier').value;
    const status = document.getElementById('keysFilterStatus').value;
    const search = document.getElementById('keysSearch').value;

    let qs = `page=${page}&limit=20&`;
    if (tier) qs += `tier=${tier}&`;
    if (status) qs += `status=${status}&`;
    if (search) qs += `search=${encodeURIComponent(search)}&`;

    try {
        const res = await api(`/api/admin/keys?${qs}`);
        const tbody = document.getElementById('keysTableBody');
        tbody.innerHTML = res.data.map(k => `
            <tr>
                <td><span class="key-mono" onclick="viewKeyDetail('${k.key}')" title="${k.key}">${shortKey(k.key)}</span></td>
                <td>${tierBadge(k.tier)}</td>
                <td>${statusBadge(k.status)}</td>
                <td>${k.duration_months}mo</td>
                <td title="${k.device_id || ''}">${k.device_name || (k.device_id ? k.device_id.slice(0,8) + '…' : '—')}</td>
                <td>${k.owner_email || '—'}</td>
                <td>${formatDate(k.expires_at)}</td>
                <td>${k.total_requests || 0}</td>
                <td>
                    <button class="btn btn-sm btn-ghost" onclick="viewKeyDetail('${k.key}')">View</button>
                    ${k.status === 'active' ? `<button class="btn btn-sm btn-danger" onclick="revokeKey('${k.key}')">Revoke</button>` : ''}
                </td>
            </tr>
        `).join('') || '<tr><td colspan="9" style="text-align:center;color:var(--text-muted);padding:40px">No keys found</td></tr>';

        renderPagination('keysPagination', res.meta, loadKeys);
    } catch (err) { console.error(err); }
}

document.getElementById('keysFilterBtn').addEventListener('click', () => loadKeys(1));
document.getElementById('keysSearch').addEventListener('keydown', (e) => { if (e.key === 'Enter') loadKeys(1); });

document.getElementById('keysExportBtn').addEventListener('click', async () => {
    try {
        const res = await api('/api/admin/keys?limit=9999');
        const csv = [
            'Key,Tier,Status,Duration,Device,Owner,Email,Expires,Requests,Created',
            ...res.data.map(k => `"${k.key}",${k.tier},${k.status},${k.duration_months}mo,"${k.device_name || ''}","${k.owner_name || ''}","${k.owner_email || ''}",${k.expires_at || ''},${k.total_requests || 0},${k.created_at || ''}`)
        ].join('\n');
        const blob = new Blob([csv], { type: 'text/csv' });
        const a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = `webharvest-keys-${new Date().toISOString().slice(0,10)}.csv`;
        a.click();
    } catch (err) { console.error(err); }
});

// ── Key Detail Modal ─────────────────────────────────────────────────────

async function viewKeyDetail(key) {
    try {
        const res = await api(`/api/admin/keys/${key}`);
        const k = res.data;
        const body = document.getElementById('keyDetailBody');
        body.innerHTML = `
            <div style="margin-bottom:16px;text-align:center">
                <span class="created-key">${k.key}</span>
            </div>
            <div class="detail-grid">
                <div class="detail-item"><label>Tier</label>${tierBadge(k.tier)}</div>
                <div class="detail-item"><label>Status</label>${statusBadge(k.status)}</div>
                <div class="detail-item"><label>Duration</label><span>${k.duration_months} months</span></div>
                <div class="detail-item"><label>Amount</label><span>${formatVND(k.amount_vnd)}</span></div>
                <div class="detail-item"><label>Owner</label><span>${k.owner_name || '—'} ${k.owner_email ? '(' + k.owner_email + ')' : ''}</span></div>
                <div class="detail-item"><label>Device</label><span title="${k.device_id || ''}">${k.device_name || k.device_id || '—'}</span></div>
                <div class="detail-item"><label>Activated</label><span>${formatDate(k.activated_at)}</span></div>
                <div class="detail-item"><label>Expires</label><span>${formatDate(k.expires_at)}</span></div>
                <div class="detail-item"><label>Last Validated</label><span>${formatDateTime(k.last_validated)}</span></div>
                <div class="detail-item"><label>Total Requests</label><span>${k.total_requests || 0}</span></div>
                <div class="detail-item"><label>Today URLs</label><span>${k.daily_urls_used || 0}</span></div>
                <div class="detail-item"><label>Rebinds</label><span>${k.rebind_count || 0} / 2</span></div>
            </div>
            ${k.note ? `<div style="margin-top:16px"><label style="font-size:11px;color:var(--text-muted)">NOTE</label><p style="color:var(--text-secondary);font-size:13px">${k.note}</p></div>` : ''}
        `;

        const footer = document.getElementById('keyDetailFooter');
        footer.innerHTML = `
            ${k.status === 'active' ? `
                <button class="btn btn-sm btn-secondary" onclick="adminExtendKey('${k.key}')">Extend 1mo</button>
                <button class="btn btn-sm btn-secondary" onclick="adminResetDevice('${k.key}')">Reset Device</button>
                <button class="btn btn-sm btn-danger" onclick="revokeKey('${k.key}')">Revoke</button>
            ` : ''}
            <button class="btn btn-sm btn-ghost" onclick="closeModal()">Close</button>
        `;

        document.getElementById('keyDetailModal').style.display = 'flex';
    } catch (err) { console.error(err); alert('Failed to load key: ' + err.message); }
}

function closeModal() { document.getElementById('keyDetailModal').style.display = 'none'; }

async function revokeKey(key) {
    if (!confirm(`Revoke key ${key}?`)) return;
    try {
        await api(`/api/admin/keys/${key}`, { method: 'DELETE' });
        closeModal();
        loadKeys(keysPage);
    } catch (err) { alert('Failed: ' + err.message); }
}

async function adminExtendKey(key) {
    try {
        await api(`/api/admin/keys/${key}`, { method: 'PATCH', body: JSON.stringify({ action: 'extend', extend_months: 1 }) });
        viewKeyDetail(key);
        alert('Extended by 1 month');
    } catch (err) { alert('Failed: ' + err.message); }
}

async function adminResetDevice(key) {
    if (!confirm('Reset device binding? User will need to re-activate.')) return;
    try {
        await api(`/api/admin/keys/${key}`, { method: 'PATCH', body: JSON.stringify({ action: 'reset_device' }) });
        viewKeyDetail(key);
    } catch (err) { alert('Failed: ' + err.message); }
}

// ── Create Key ───────────────────────────────────────────────────────────

document.getElementById('createKeyForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    const tier = document.getElementById('createTier').value;
    const duration = parseInt(document.getElementById('createDuration').value);
    const email = document.getElementById('createEmail').value;
    const name = document.getElementById('createName').value;
    const count = parseInt(document.getElementById('createCount').value) || 1;
    const note = document.getElementById('createNote').value;

    try {
        const res = await api('/api/admin/keys', {
            method: 'POST',
            body: JSON.stringify({ tier, duration_months: duration, owner_email: email, owner_name: name, count, note }),
        });

        const result = document.getElementById('createResult');
        result.style.display = 'block';
        result.innerHTML = `
            <h3 style="color:var(--green);margin-bottom:12px">✅ Created ${res.data.length} key(s)</h3>
            ${res.data.map(k => `<div class="created-key" title="Click to copy" onclick="navigator.clipboard.writeText('${k.key}')">${k.key}</div>`).join('<br>')}
            <p style="color:var(--text-muted);font-size:12px;margin-top:8px">Click key to copy</p>
        `;
    } catch (err) {
        alert('Create failed: ' + err.message);
    }
});

// ── Request Logs ─────────────────────────────────────────────────────────

let reqPage = 1;

async function loadRequests(page = 1) {
    reqPage = page;
    const status = document.getElementById('reqFilterStatus').value;
    const from = document.getElementById('reqDateFrom').value;
    const to = document.getElementById('reqDateTo').value;

    let qs = `page=${page}&limit=30&`;
    if (status) qs += `status=${status}&`;
    if (from) qs += `date_from=${from}&`;
    if (to) qs += `date_to=${to}&`;

    try {
        const res = await api(`/api/admin/requests?${qs}`);
        const tbody = document.getElementById('reqTableBody');
        tbody.innerHTML = res.data.map(r => `
            <tr>
                <td>${formatDateTime(r.created_at)}</td>
                <td>${r.license_key ? `<span class="key-mono" onclick="viewKeyDetail('${r.license_key}')">${shortKey(r.license_key)}</span>` : '—'}</td>
                <td>${r.action || '—'}</td>
                <td title="${r.url || ''}">${r.url ? (r.url.length > 40 ? r.url.slice(0,40) + '…' : r.url) : '—'}</td>
                <td>${statusBadge(r.status)}</td>
                <td style="color:var(--red);max-width:200px;overflow:hidden;text-overflow:ellipsis" title="${r.error_message || ''}">${r.error_message || '—'}</td>
                <td style="color:var(--text-muted)">${r.ip_address || '—'}</td>
            </tr>
        `).join('') || '<tr><td colspan="7" style="text-align:center;color:var(--text-muted);padding:40px">No logs found</td></tr>';

        renderPagination('reqPagination', res.meta, loadRequests);
    } catch (err) { console.error(err); }
}

document.getElementById('reqFilterBtn').addEventListener('click', () => loadRequests(1));

// ── Revenue ──────────────────────────────────────────────────────────────

async function loadRevenue() {
    const groupBy = document.getElementById('revGroupBy').value;
    const from = document.getElementById('revDateFrom').value;
    const to = document.getElementById('revDateTo').value;

    let qs = `group_by=${groupBy}&`;
    if (from) qs += `date_from=${from}&`;
    if (to) qs += `date_to=${to}&`;

    try {
        const res = await api(`/api/admin/revenue?${qs}`);
        const data = res.data || [];

        // Summary
        const totalRev = data.reduce((s, r) => s + (r.revenue || 0), 0);
        const totalTx = data.reduce((s, r) => s + (r.transactions || 0), 0);
        document.getElementById('revenueSummary').innerHTML = `
            <div class="stat-card"><div class="stat-icon bg-purple"><svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="12" y1="1" x2="12" y2="23"/><path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/></svg></div><div class="stat-info"><span class="stat-value">${formatVND(totalRev)}</span><span class="stat-label">Total Revenue</span></div></div>
            <div class="stat-card"><div class="stat-icon bg-green"><svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg></div><div class="stat-info"><span class="stat-value">${totalTx}</span><span class="stat-label">Transactions</span></div></div>
            <div class="stat-card"><div class="stat-icon bg-cyan"><svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg></div><div class="stat-info"><span class="stat-value">${totalTx ? formatVND(Math.round(totalRev / totalTx)) : '—'}</span><span class="stat-label">Avg Order Value</span></div></div>
        `;

        // Table
        const tbody = document.getElementById('revTableBody');
        tbody.innerHTML = data.map(r => `
            <tr>
                <td>${r.period ? formatDate(r.period) : '—'}</td>
                <td>${tierBadge(r.tier)}</td>
                <td>${r.transactions || 0}</td>
                <td style="font-weight:600">${formatVND(r.revenue)}</td>
            </tr>
        `).join('') || '<tr><td colspan="4" style="text-align:center;color:var(--text-muted);padding:40px">No revenue data</td></tr>';
    } catch (err) { console.error(err); }
}

document.getElementById('revFilterBtn').addEventListener('click', loadRevenue);

// ── Pagination Helper ────────────────────────────────────────────────────

function renderPagination(containerId, meta, loadFn) {
    if (!meta) return;
    const { page, limit, total } = meta;
    const totalPages = Math.ceil(total / limit);
    const container = document.getElementById(containerId);

    if (totalPages <= 1) { container.innerHTML = ''; return; }

    let html = `<button ${page <= 1 ? 'disabled' : ''} onclick="${loadFn.name}(${page - 1})">←</button>`;
    for (let i = 1; i <= totalPages && i <= 10; i++) {
        html += `<button class="${i === page ? 'active' : ''}" onclick="${loadFn.name}(${i})">${i}</button>`;
    }
    if (totalPages > 10) html += `<button disabled>…${totalPages}</button>`;
    html += `<button ${page >= totalPages ? 'disabled' : ''} onclick="${loadFn.name}(${page + 1})">→</button>`;
    container.innerHTML = html;
}

// ── Init ─────────────────────────────────────────────────────────────────

(async function init() {
    if (authToken) {
        try {
            await api('/api/admin/dashboard');
            showApp();
        } catch { showLogin(); }
    } else {
        showLogin();
    }
})();
