// ══════════════════════════════════════════════════════════════
// LICENSE GATE — Validates key on startup, shows gate if needed
// ══════════════════════════════════════════════════════════════

const LICENSE_KEY_STORAGE = 'wh_license_key';
const LICENSE_DATA_STORAGE = 'wh_license_data';
let licenseData = null;  // {tier, limits, expires_at, ...}

// ══════════════════════════════════════════════════════════════
// ReconnectingWebSocket — auto-reconnects with exponential backoff
// ══════════════════════════════════════════════════════════════
class ReconnectingWebSocket {
    constructor(url, options = {}) {
        this.url = url;
        this.maxRetries = options.maxRetries || 5;
        this.retryCount = 0;
        this.retryDelay = options.retryDelay || 1000;
        this.maxDelay = options.maxDelay || 30000;
        this.onopen = null;
        this.onclose = null;
        this.onmessage = null;
        this.onerror = null;
        this._isManuallyClosed = false;
        this._ws = null;
        this._connect();
    }

    _connect() {
        this._ws = new WebSocket(this.url);
        this._ws.onopen = (e) => {
            this.retryCount = 0;
            if (this.onopen) this.onopen(e);
        };
        this._ws.onclose = (e) => {
            if (!this._isManuallyClosed && e.code !== 1000 && this.retryCount < this.maxRetries) {
                const delay = Math.min(this.retryDelay * Math.pow(2, this.retryCount), this.maxDelay);
                console.log(`WebSocket reconnecting in ${delay}ms (attempt ${this.retryCount + 1}/${this.maxRetries})`);
                this.retryCount++;
                setTimeout(() => this._connect(), delay);
            } else {
                if (this.onclose) this.onclose(e);
            }
        };
        this._ws.onmessage = (e) => {
            if (this.onmessage) this.onmessage(e);
        };
        this._ws.onerror = (e) => {
            if (this.onerror) this.onerror(e);
        };
    }

    send(data) {
        if (this._ws && this._ws.readyState === WebSocket.OPEN) {
            this._ws.send(data);
        }
    }

    close(code = 1000, reason = '') {
        this._isManuallyClosed = true;
        if (this._ws) this._ws.close(code, reason);
    }

    get readyState() {
        return this._ws ? this._ws.readyState : WebSocket.CLOSED;
    }
}

// ══════════════════════════════════════════════════════════════
// Toast Notification System
// ══════════════════════════════════════════════════════════════
const _toastContainer = document.createElement('div');
_toastContainer.className = 'toast-container';
document.body.appendChild(_toastContainer);

function showToast(message, type = 'info', duration = 4000) {
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    const icons = { success: 'check-circle', error: 'x-circle', warning: 'alert-triangle', info: 'info' };
    toast.innerHTML = `<svg class="lucide"><use href="#${icons[type] || 'info'}"></use></svg><span>${message}</span>`;
    _toastContainer.appendChild(toast);
    requestAnimationFrame(() => toast.classList.add('toast-visible'));
    setTimeout(() => {
        toast.classList.remove('toast-visible');
        setTimeout(() => toast.remove(), 300);
    }, duration);
}

function setButtonLoading(btn, loading) {
    if (!btn) return;
    if (loading) {
        btn.dataset.originalText = btn.dataset.originalText || btn.innerHTML;
        btn.disabled = true;
        btn.classList.add('btn-loading');
    } else {
        btn.disabled = false;
        btn.classList.remove('btn-loading');
        if (btn.dataset.originalText) {
            btn.innerHTML = btn.dataset.originalText;
        }
    }
}

// ══════════════════════════════════════════════════════════════
// Export Functionality
// ══════════════════════════════════════════════════════════════
function exportToCSV(data, filename) {
    if (!data || !data.length) {
        showToast(t('export_no_data') || 'No data to export', 'warning');
        return;
    }
    const headers = Object.keys(data[0]);
    const csv = [
        headers.join(','),
        ...data.map(row => headers.map(h => {
            const val = String(row[h] ?? '').replace(/"/g, '""');
            return `"${val}"`;
        }).join(','))
    ].join('\n');

    const blob = new Blob(['\uFEFF' + csv], { type: 'text/csv;charset=utf-8;' });
    const link = document.createElement('a');
    link.href = URL.createObjectURL(blob);
    link.download = filename || 'export.csv';
    link.click();
    URL.revokeObjectURL(link.href);
    showToast(t('export_success') || 'Exported successfully', 'success');
}

function exportToJSON(data, filename) {
    if (!data || !data.length) {
        showToast(t('export_no_data') || 'No data to export', 'warning');
        return;
    }
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
    const link = document.createElement('a');
    link.href = URL.createObjectURL(blob);
    link.download = filename || 'export.json';
    link.click();
    URL.revokeObjectURL(link.href);
    showToast(t('export_success') || 'Exported successfully', 'success');
}


async function initLicenseGate() {
    // Fetch device ID to display in the card
    try {
        const devInfoResp = await fetch('/api/device-id');
        const devInfo = await devInfoResp.json();
        if (devInfo.device_id) {
            const deviceIdEl = document.getElementById('display-device-id');
            const deviceNameEl = document.getElementById('display-device-name');
            if (deviceIdEl) deviceIdEl.textContent = devInfo.device_id;
            if (deviceNameEl) deviceNameEl.textContent = devInfo.device_name || 'N/A';
        }
    } catch (e) {
        console.error('Failed to fetch device info:', e);
    }

    const savedKey = localStorage.getItem(LICENSE_KEY_STORAGE);
    if (savedKey) {
        try {
            const resp = await fetch('/api/license/validate-local', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ key: savedKey }),
            });
            const result = await resp.json();
            if (result.success && result.data && result.data.valid) {
                licenseData = result.data;
                localStorage.setItem(LICENSE_DATA_STORAGE, JSON.stringify(licenseData));
                applyLicenseTier();
                // Allow closing the modal since we have a valid license
                const closeBtn = document.getElementById('btn-close-license');
                if (closeBtn) closeBtn.style.display = 'block';
                hideLicenseGate();
                return;
            } else {
                // Clear invalid/expired key
                if (result.error_code === 'TRIAL_EXHAUSTED' || result.error_code === 'TRIAL_EXPIRED' || result.error_code === 'EXPIRED') {
                    localStorage.removeItem(LICENSE_KEY_STORAGE);
                    localStorage.removeItem(LICENSE_DATA_STORAGE);
                    licenseData = null;
                    setTimeout(() => {
                        const errEl = document.getElementById('license-error');
                        if (errEl) {
                            const msgMap = {
                                'TRIAL_EXHAUSTED': t('license_err_trial_exhausted') || t('trial_exhausted_msg'),
                                'TRIAL_EXPIRED': t('license_err_trial_expired') || t('trial_exhausted_msg'),
                                'EXPIRED': t('license_err_expired')
                            };
                            errEl.textContent = msgMap[result.error_code] || result.error || t('error_activation_failed');
                            errEl.style.display = 'block';
                        }
                    }, 200);
                }
            }
        } catch (e) {
            // Offline — try cached data
            const cached = localStorage.getItem(LICENSE_DATA_STORAGE);
            if (cached) {
                licenseData = JSON.parse(cached);
                applyLicenseTier();
                const closeBtn = document.getElementById('btn-close-license');
                if (closeBtn) closeBtn.style.display = 'block';
                hideLicenseGate();
                return;
            }
        }
    }
    // No valid key — check if license server is configured
    try {
        const devResp = await fetch('/api/license/packages');
        const devData = await devResp.json();
        if (devData.success && devData.data && devData.data.length === 0) {
            // Dev mode — no license server configured
            licenseData = { valid: true, tier: 'unlimited', limits: { batch_crawl: true, stealth_mode: true, proxy_quota_gb: 50.0, max_daily_urls: 999999, max_concurrent: 20 } };
            applyLicenseTier();
            const closeBtn = document.getElementById('btn-close-license');
            if (closeBtn) closeBtn.style.display = 'block';
            hideLicenseGate();
            return;
        }
    } catch (e) { /* ignore */ }

    // No valid key & server is configured -> force license gate open, hide close button
    const closeBtn = document.getElementById('btn-close-license');
    if (closeBtn) closeBtn.style.display = 'none';
    showLicenseGate();
}

function showLicenseGate() {
    const gate = document.getElementById('license-gate');
    if (gate) gate.style.display = 'flex';

    // Show/hide deactivate button based on key presence
    const savedKey = localStorage.getItem(LICENSE_KEY_STORAGE);
    const deactivateBtn = document.getElementById('btn-deactivate-license');
    if (deactivateBtn) {
        deactivateBtn.style.display = savedKey ? 'block' : 'none';
    }

    const trialBox = document.getElementById('trial-box');
    if (trialBox) {
        trialBox.style.display = savedKey ? 'none' : 'flex';
    }
}

function hideLicenseGate() {
    const gate = document.getElementById('license-gate');
    if (gate) gate.style.display = 'none';
}

function showManageLicense() {
    const savedKey = localStorage.getItem(LICENSE_KEY_STORAGE);
    const input = document.getElementById('license-key-input');
    if (input && savedKey) {
        input.value = savedKey;
    }

    // Enable close button in case they want to return to the app
    const closeBtn = document.getElementById('btn-close-license');
    if (closeBtn) closeBtn.style.display = 'block';

    showLicenseGate();
}

async function deactivateLicenseKey() {
    const savedKey = localStorage.getItem(LICENSE_KEY_STORAGE);
    if (!savedKey) return;

    if (!confirm(t('confirm_deactivate_license'))) {
        return;
    }

    const errEl = document.getElementById('license-error');
    if (errEl) {
        errEl.style.display = 'none';
    }

    try {
        const resp = await fetch('/api/license/deactivate-local', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ key: savedKey }),
        });
        const data = await resp.json();
        if (data.success) {
            // Clear local storage
            localStorage.removeItem(LICENSE_KEY_STORAGE);
            localStorage.removeItem(LICENSE_DATA_STORAGE);
            licenseData = null;

            // Clear inputs
            const input = document.getElementById('license-key-input');
            if (input) input.value = '';

            // Hide badge in header
            const badge = document.getElementById('tier-badge');
            if (badge) badge.style.display = 'none';

            // Disable close button and show gate (forcing them to activate/register a key to continue)
            const closeBtn = document.getElementById('btn-close-license');
            if (closeBtn) closeBtn.style.display = 'none';

            // Update button visibility
            const deactivateBtn = document.getElementById('btn-deactivate-license');
            if (deactivateBtn) deactivateBtn.style.display = 'none';

            showToast(t('alert_deactivation_success'), 'success');
            showLicenseGate();
        } else {
            if (errEl) {
                errEl.textContent = data.error || t('error_deactivate_failed');
                errEl.style.display = 'block';
            }
        }
    } catch (e) {
        if (errEl) {
            errEl.textContent = t('error_connection_retry');
            errEl.style.display = 'block';
        }
    }
}

function applyLicenseTier() {
    if (!licenseData) return;
    const tier = licenseData.tier || 'basic';
    const limits = licenseData.limits || {};

    // Update tier badge in header
    const badge = document.getElementById('tier-badge');
    if (badge) {
        const tierNames = { trial: 'Trial', basic: 'Basic', pro: 'Pro', unlimited: 'Unlimited' };
        const tierIcons = { trial: '✨', basic: '⚡', pro: '⭐', unlimited: '💎' };
        
        if (limits.is_trial) {
            badge.textContent = `✨ Trial (${limits.trial_remaining}/${limits.trial_total})`;
        } else {
            badge.textContent = `${tierIcons[tier] || '⚡'} ${tierNames[tier] || tier}`;
        }
        badge.className = `tier-badge tier-${tier}`;
        badge.style.display = 'inline-flex';

        if (licenseData.expires_at) {
            const exp = new Date(licenseData.expires_at);
            badge.title = t('badge_expires_at', { date: exp.toLocaleDateString() });
        } else {
            badge.title = t('badge_unlimited');
        }
    }

    const trialBox = document.getElementById('trial-box');
    if (trialBox) {
        trialBox.style.display = 'none';
    }

    // Disable/Enable batch crawl mode selection based on limits
    if (!limits.batch_crawl) {
        document.querySelectorAll('.mode-btn[data-mode="batch"]').forEach(btn => {
            btn.classList.add('tier-locked');
            btn.title = t('tooltip_upgrade_pro_batch');
        });
    } else {
        document.querySelectorAll('.mode-btn[data-mode="batch"]').forEach(btn => {
            btn.classList.remove('tier-locked');
            btn.title = '';
        });
    }

    // Disable stealth/proxy options in Fetcher select for Basic
    const fetcherSelect = document.getElementById('fetcher');
    if (fetcherSelect && limits.allowed_fetchers) {
        Array.from(fetcherSelect.options).forEach(opt => {
            if (!limits.allowed_fetchers.includes(opt.value) && opt.value !== 'auto') {
                opt.disabled = true;
                if (!opt.textContent.includes('🔒')) {
                    opt.textContent += ' 🔒';
                }
            } else {
                opt.disabled = false;
                opt.textContent = opt.textContent.replace(' 🔒', '');
            }
        });
    }

    // Show proxy quota indicator for all tiers
    const proxySelect = document.getElementById('proxy-provider');
    if (proxySelect) {
        const quotaGb = limits.proxy_quota_gb || 0;
        if (quotaGb > 0) {
            // All tiers now have proxy access via server
            Array.from(proxySelect.options).forEach(opt => {
                opt.disabled = false;
                opt.textContent = opt.textContent.replace(' 🔒', '');
            });
        } else {
            // No proxy quota - lock to local IP
            Array.from(proxySelect.options).forEach(opt => {
                if (opt.value !== 'none') {
                    opt.disabled = true;
                    if (!opt.textContent.includes('🔒')) {
                        opt.textContent += ' 🔒';
                    }
                }
            });
            if (proxySelect.value !== 'none') {
                proxySelect.value = 'none';
                proxySelect.dispatchEvent(new Event('change'));
            }
        }
    }

    // Load proxy quota indicator
    loadProxyStatus();
}

async function activateLicenseKey() {
    const input = document.getElementById('license-key-input');
    const errEl = document.getElementById('license-error');
    const key = (input?.value || '').trim().toUpperCase();

    if (!key) { errEl.textContent = t('error_enter_license_key'); errEl.style.display = 'block'; return; }

    errEl.style.display = 'none';
    try {
        const resp = await fetch('/api/license/activate-local', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ key }),
        });
        const data = await resp.json();
        if (data.success) {
            localStorage.setItem(LICENSE_KEY_STORAGE, key);
            licenseData = data.data;
            licenseData.valid = true;
            localStorage.setItem(LICENSE_DATA_STORAGE, JSON.stringify(licenseData));
            applyLicenseTier();
            hideLicenseGate();
        } else {
            const messages = {
                'NOT_FOUND': t('license_err_not_found'),
                'DEVICE_MISMATCH': t('license_err_device_mismatch'),
                'EXPIRED': t('license_err_expired'),
                'REVOKED': t('license_err_revoked'),
                'UNREACHABLE': t('license_err_unreachable'),
            };
            errEl.textContent = messages[data.error_code] || data.error || t('error_activation_failed');
            errEl.style.display = 'block';
        }
    } catch (e) {
        errEl.textContent = t('error_connection_retry');
        errEl.style.display = 'block';
    }
}

async function requestFreeTrial() {
    const errEl = document.getElementById('license-error');
    if (errEl) errEl.style.display = 'none';

    try {
        const resp = await fetch('/api/license/request-trial-local', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ email: "" }),
        });
        const data = await resp.json();
        if (data.success && data.key) {
            const key = data.key;
            localStorage.setItem(LICENSE_KEY_STORAGE, key);
            
            // Re-validate to fetch full limits and cache
            const vResp = await fetch('/api/license/validate-local', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ key }),
            });
            const vData = await vResp.json();
            if (vData.success && vData.data) {
                licenseData = vData.data;
                licenseData.valid = true;
                localStorage.setItem(LICENSE_DATA_STORAGE, JSON.stringify(licenseData));
            } else {
                licenseData = {
                    valid: true,
                    tier: 'trial',
                    limits: {
                        max_daily_urls: 20,
                        max_concurrent: 5,
                        allowed_fetchers: ['auto', 'static', 'dynamic', 'stealth'],
                        batch_crawl: true,
                        stealth_mode: true,
                        proxy_quota_gb: 0.5,
                        is_trial: true,
                        trial_remaining: data.remaining || 20,
                        trial_total: 20
                    }
                };
                localStorage.setItem(LICENSE_DATA_STORAGE, JSON.stringify(licenseData));
            }
            
            applyLicenseTier();
            
            // Allow closing the modal since we have a valid license
            const closeBtn = document.getElementById('btn-close-license');
            if (closeBtn) closeBtn.style.display = 'block';
            
            hideLicenseGate();
            showToast(t('trial_success_alert'), 'success');
        } else {
            if (errEl) {
                const msgMap = {
                    'TRIAL_EXHAUSTED': t('license_err_trial_exhausted') || t('trial_exhausted_msg'),
                    'TRIAL_EXPIRED': t('license_err_trial_expired') || t('trial_exhausted_msg')
                };
                errEl.textContent = msgMap[data.error_code] || data.error || t('error_activation_failed');
                errEl.style.display = 'block';
            }
        }
    } catch (e) {
        if (errEl) {
            errEl.textContent = t('error_connection_retry');
            errEl.style.display = 'block';
        }
    }
}

function handleLicenseError(errorCode, defaultMessage) {
    localStorage.removeItem(LICENSE_KEY_STORAGE);
    localStorage.removeItem(LICENSE_DATA_STORAGE);
    licenseData = null;
    applyLicenseTier();

    const errEl = document.getElementById('license-error');
    if (errEl) {
        const msgMap = {
            'TRIAL_EXHAUSTED': t('license_err_trial_exhausted') || t('trial_exhausted_msg'),
            'TRIAL_EXPIRED': t('license_err_trial_expired') || t('trial_exhausted_msg'),
            'KEY_REQUIRED': t('error_enter_license_key')
        };
        errEl.textContent = msgMap[errorCode] || defaultMessage || t('trial_exhausted_msg');
        errEl.style.display = 'block';
    }
    showLicenseGate();
}

let _paymentPollInterval = null;

async function openPurchaseFlow(tier, duration) {
    const errEl = document.getElementById('license-error');
    errEl.style.display = 'none';

    try {
        const resp = await fetch('/api/license/create-payment', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ tier, duration_months: duration }),
        });
        const data = await resp.json();
        if (data.success && data.data?.checkout_url) {
            // Open in system browser
            window.open(data.data.checkout_url, '_blank');

            // Start polling for payment confirmation
            const orderCode = data.data.order_code;
            const statusEl = document.getElementById('payment-status');
            if (statusEl) { statusEl.textContent = t('payment_status_waiting'); statusEl.style.display = 'block'; }

            if (_paymentPollInterval) clearInterval(_paymentPollInterval);
            _paymentPollInterval = setInterval(async () => {
                try {
                    const vResp = await fetch('/api/license/verify-payment', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ order_code: orderCode }),
                    });
                    const vData = await vResp.json();
                    if (vData.success && vData.data?.status === 'paid') {
                        clearInterval(_paymentPollInterval);
                        if (vData.data.key) {
                            localStorage.setItem(LICENSE_KEY_STORAGE, vData.data.key);
                            if (statusEl) { statusEl.textContent = t('payment_status_success', { key: vData.data.key }); }
                            // Re-validate
                            setTimeout(() => initLicenseGate(), 1500);
                        }
                    } else if (vData.data?.status === 'cancelled') {
                        clearInterval(_paymentPollInterval);
                        if (statusEl) { statusEl.textContent = t('payment_status_cancelled'); }
                    }
                } catch (e) { /* keep polling */ }
            }, 3000);
        } else {
            errEl.textContent = data.error || t('error_create_payment_link_failed');
            errEl.style.display = 'block';
        }
    } catch (e) {
        errEl.textContent = t('error_connect_server_failed');
        errEl.style.display = 'block';
    }
}

// Theme Toggle Initialization
function initThemeToggle() {
    const toggleBtn = document.getElementById('theme-toggle');
    if (!toggleBtn) return;

    function updateToggleIcon(theme) {
        const iconName = theme === 'light' ? 'moon' : 'sun';
        toggleBtn.innerHTML = `<i data-lucide="${iconName}"></i>`;
        if (window.lucide) {
            window.lucide.createIcons();
        }
    }

    const currentTheme = document.documentElement.getAttribute('data-theme') || 'dark';
    updateToggleIcon(currentTheme);

    toggleBtn.addEventListener('click', () => {
        const theme = document.documentElement.getAttribute('data-theme') === 'light' ? 'dark' : 'light';
        document.documentElement.setAttribute('data-theme', theme);
        localStorage.setItem('theme', theme);
        updateToggleIcon(theme);
    });
}

// Initialize Lucide Icons
document.addEventListener("DOMContentLoaded", () => {
    initThemeToggle();
    lucide.createIcons();
    initLicenseGate();
    loadHistory();
    initProxyPanel();
    initAppleScrollAnimations();

    // Wire export buttons
    const btnExportCSV = document.getElementById('btn-export-csv');
    const btnExportJSON = document.getElementById('btn-export-json');
    if (btnExportCSV) {
        btnExportCSV.addEventListener('click', () => {
            exportToCSV(crawledProducts, 'webharvest-products.csv');
        });
    }
    if (btnExportJSON) {
        btnExportJSON.addEventListener('click', () => {
            exportToJSON(crawledProducts, 'webharvest-products.json');
        });
    }
});

// Scroll Animations
function initAppleScrollAnimations() {
    const observer = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                entry.target.classList.add('is-visible');
            }
        });
    }, { threshold: 0.05, rootMargin: '0px 0px -20px 0px' });

    document.querySelectorAll('.apple-animate').forEach(el => observer.observe(el));
}

// ── Proxy Status (Server-Managed — read-only display) ──────────────────
// Proxy is fully managed server-side. No credentials or URLs touch the frontend.

function initProxyPanel() {
    // Load quota display and circuit breaker status
    loadProxyStatus();

    // Test connection button (tests via server, no credentials exposed)
    const btnTest = document.getElementById("btn-test-proxy");
    if (btnTest) btnTest.addEventListener("click", testProxyConnection);
}

async function loadProxyStatus() {
    try {
        const [quotaResp, statusResp] = await Promise.all([
            fetch('/api/proxy/quota'),
            fetch('/api/proxy/status'),
        ]);
        const quotaData = await quotaResp.json();
        const statusData = await statusResp.json();

        const statusText = document.getElementById("proxy-status-text");
        const statusDot = document.querySelector(".proxy-dot");
        const quotaEl = document.getElementById("proxy-quota-display");

        // Show quota
        if (quotaData.ok && quotaData.data && quotaData.data.configured) {
            const d = quotaData.data;
            if (quotaEl) {
                quotaEl.textContent = `Proxy: ${d.remaining_gb.toFixed(2)}/${d.quota_gb} GB`;
                quotaEl.style.display = 'inline-block';
            }
            if (statusText) statusText.textContent = t("proxy_status_managed");
            if (statusDot) statusDot.className = "proxy-dot dot-proxy";
        } else {
            if (statusText) statusText.textContent = t("proxy_status_local_priority");
            if (statusDot) statusDot.className = "proxy-dot dot-local";
        }

        // Show circuit breaker warning
        if (statusData.ok && statusData.circuit_open) {
            if (statusText) statusText.textContent = t("proxy_status_circuit_breaker");
            if (statusDot) statusDot.className = "proxy-dot dot-error";
        }
    } catch (e) {
        console.warn('[Proxy] Failed to load status:', e);
    }
}

async function testProxyConnection() {
    const resultEl = document.getElementById("proxy-test-result");
    const btn = document.getElementById("btn-test-proxy");

    if (resultEl) {
        resultEl.className = "proxy-test-result loading";
        resultEl.textContent = t("proxy_checking");
    }
    if (btn) btn.classList.add("testing");

    try {
        const resp = await fetch("/api/test-proxy", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({})
        });
        const data = await resp.json();
        if (data.ok) {
            if (resultEl) {
                resultEl.className = "proxy-test-result success";
                resultEl.textContent = t("proxy_check_success", { ip: data.ip });
            }
        } else {
            if (resultEl) {
                resultEl.className = "proxy-test-result error";
                resultEl.textContent = `✗ ${data.error}`;
            }
        }
    } catch (e) {
        if (resultEl) {
            resultEl.className = "proxy-test-result error";
            resultEl.textContent = t("error_cannot_connect_server");
        }
    } finally {
        if (btn) btn.classList.remove("testing");
    }
}

// Tab Navigation
const tabButtons = document.querySelectorAll(".tab-btn");
const tabContents = document.querySelectorAll(".tab-content");

tabButtons.forEach(button => {
    button.addEventListener("click", () => {
        const targetTab = button.dataset.tab;
        
        tabButtons.forEach(btn => { btn.classList.remove("active"); btn.setAttribute("aria-selected", "false"); });
        tabContents.forEach(content => content.classList.remove("active"));
        
        button.classList.add("active");
        button.setAttribute("aria-selected", "true");
        document.getElementById(`tab-${targetTab}`).classList.add("active");
        
        if (targetTab === "gallery") {
            loadHistory();
        }
    });
});

// App State
let ws = null;
let liveImageCount = 0;
let currentScrapeMode = "images"; // "images" | "products"
let _detectDebounceTimer = null;

// Elements
const crawlForm = document.getElementById("crawl-form");
const btnStart = document.getElementById("btn-start");
const btnStop = document.getElementById("btn-stop");
const statusBadge = document.getElementById("status-badge");
const logsViewer = document.getElementById("logs-viewer");
const liveImageGrid = document.getElementById("live-image-grid");
const liveGalleryCount = document.getElementById("live-gallery-count");

// Product result elements (now inside the same tab)
const productTableBody = document.getElementById("product-table-body");
const productResultCount = document.getElementById("product-result-count");
let crawledProducts = [];
let productWs = null;

// Stats Elements (Image mode)
const statPages = document.getElementById("stat-pages");
const statFound = document.getElementById("stat-found");
const statDownloaded = document.getElementById("stat-downloaded");
const statFailed = document.getElementById("stat-failed");

// Stats Elements (Product mode)
const statProdTotal = document.getElementById("stat-prod-total");
const statProdSuccess = document.getElementById("stat-prod-success");
const statProdFailed = document.getElementById("stat-prod-failed");

// ── Scrape Mode Toggle ──────────────────────────────────────────
document.querySelectorAll(".scrape-mode-btn").forEach(btn => {
    btn.addEventListener("click", () => {
        document.querySelectorAll(".scrape-mode-btn").forEach(b => b.classList.remove("active"));
        btn.classList.add("active");
        switchScrapeMode(btn.dataset.scrapeMode);
    });
});

function switchScrapeMode(mode) {
    currentScrapeMode = mode;
    const isImages = mode === "images";

    // Config panels
    const imageConfigPanel = document.getElementById("image-config-panel");
    const productConfigPanel = document.getElementById("product-config-panel");
    if (imageConfigPanel) imageConfigPanel.style.display = isImages ? "block" : "none";
    if (productConfigPanel) productConfigPanel.style.display = isImages ? "none" : "block";

    // Stats grids
    const imageStats = document.getElementById("image-stats-grid");
    const productStats = document.getElementById("product-stats-grid");
    if (imageStats) imageStats.style.display = isImages ? "grid" : "none";
    if (productStats) productStats.style.display = isImages ? "none" : "grid";

    // Result sections
    const liveGallery = document.getElementById("live-gallery-section");
    const productResults = document.getElementById("product-results-section");
    if (liveGallery) liveGallery.style.display = isImages ? "block" : "none";
    if (productResults) productResults.style.display = isImages ? "none" : "block";

    // Update start button text
    if (btnStart) {
        btnStart.innerHTML = isImages
            ? `<i data-lucide="play"></i> ${t('btn_start_crawl')}`
            : `<i data-lucide="play"></i> ${t('btn_start_crawling_products')}`;
    }
    if (!isImages) {
        loadProductHistory();
    }
    lucide.createIcons();
}

// ── URL Auto-Detect ─────────────────────────────────────────────
const urlInput = document.getElementById("url");
if (urlInput) {
    urlInput.addEventListener("input", () => {
        clearTimeout(_detectDebounceTimer);
        const val = urlInput.value.trim();
        if (!val || val.length < 10) {
            hideDetectBadge();
            return;
        }
        _detectDebounceTimer = setTimeout(() => detectUrlMode(val), 500);
    });
}

async function detectUrlMode(url) {
    try {
        const resp = await fetch(`/api/detect-mode?url=${encodeURIComponent(url)}`);
        const data = await resp.json();
        if (data.mode === "products" && data.site) {
            showDetectBadge(data.message, data.site);
        } else {
            hideDetectBadge();
        }
    } catch (e) {
        hideDetectBadge();
    }
}

function showDetectBadge(message, site) {
    const badge = document.getElementById("url-detect-badge");
    const text = document.getElementById("url-detect-text");
    if (badge && text) {
        text.textContent = message || t('detected_site', { site });
        badge.style.display = "flex";
        lucide.createIcons();
    }
    // Wire up the switch button
    const switchBtn = document.getElementById("btn-detect-switch");
    if (switchBtn) {
        switchBtn.onclick = () => {
            // Activate product mode
            document.querySelectorAll(".scrape-mode-btn").forEach(b => b.classList.remove("active"));
            const prodBtn = document.querySelector('.scrape-mode-btn[data-scrape-mode="products"]');
            if (prodBtn) prodBtn.classList.add("active");
            switchScrapeMode("products");
            hideDetectBadge();
        };
    }
}

function hideDetectBadge() {
    const badge = document.getElementById("url-detect-badge");
    if (badge) badge.style.display = "none";
}

// Modal Elements
const modal = document.getElementById("image-modal");
const modalImg = document.getElementById("modal-img");
const modalCaption = document.getElementById("modal-caption");
const closeModal = document.querySelector(".close-modal");

// Helper: Format File Size
function formatBytes(bytes) {
    if (bytes === 0) return '0 Bytes';
    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
}

// Helper: Add Log Line
const MAX_LOG_LINES = 500;

function addLog(message, type = "info") {
    const time = new Date().toLocaleTimeString();
    const logLine = document.createElement("div");
    logLine.className = `log-line ${type}`;
    logLine.textContent = `[${time}] ${message}`;
    logsViewer.appendChild(logLine);
    logsViewer.scrollTop = logsViewer.scrollHeight;

    // Cap log lines to prevent unbounded DOM growth
    while (logsViewer.children.length > MAX_LOG_LINES) {
        logsViewer.removeChild(logsViewer.firstChild);
    }
}

// Lazy image loading with IntersectionObserver
const _imageObserver = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
        if (entry.isIntersecting) {
            const img = entry.target;
            if (img.dataset.src) {
                img.src = img.dataset.src;
                img.removeAttribute('data-src');
                _imageObserver.unobserve(img);
            }
        }
    });
}, { rootMargin: '200px' });

// Helper: Create Image Card Element
function createImageCard(imgData) {
    const card = document.createElement("div");
    card.className = "image-item";
    
    const imageUrl = `/api/image?path=${encodeURIComponent(imgData.path)}`;
    
    const img = document.createElement('img');
    img.dataset.src = imageUrl;  // Lazy load instead of img.src = imageUrl
    img.alt = imgData.name;
    img.loading = 'lazy';  // Native lazy loading as fallback
    _imageObserver.observe(img);

    const overlay = document.createElement('div');
    overlay.className = 'image-overlay';
    overlay.innerHTML = `
        <span class="img-title" title="${imgData.name}">${imgData.name}</span>
        <div class="img-meta">
            <span class="img-domain">${imgData.domain}</span>
            <span>${formatBytes(imgData.size)}</span>
        </div>
    `;

    card.appendChild(img);
    card.appendChild(overlay);
    
    // Zoom on Click
    card.addEventListener("click", () => {
        modal.style.display = "block";
        modalImg.src = imageUrl;
        modalCaption.textContent = t('modal_image_caption', { name: imgData.name, domain: imgData.domain, size: formatBytes(imgData.size) });
    });
    
    return card;
}

// Modal Close logic
closeModal.addEventListener("click", () => {
    modal.style.display = "none";
});
modal.addEventListener("click", (e) => {
    if (e.target === modal) {
        modal.style.display = "none";
    }
});

// Scraper WebSockets Logic
crawlForm.addEventListener("submit", (e) => {
    e.preventDefault();

    // Route based on scrape mode
    if (currentScrapeMode === "products") {
        startProductCrawl();
        return;
    }
    
    // Check if batch mode
    if (currentMode === "batch") {
        startBatchCrawl();
        return;
    }
    
    const url = document.getElementById("url").value.trim();
    const output_dir = document.getElementById("output_dir").value.trim();
    const depth = parseInt(document.getElementById("depth").value);
    const max_pages = parseInt(document.getElementById("max_pages").value);
    const fetcher = document.getElementById("fetcher").value;
    const min_file_size = parseInt(document.getElementById("min_file_size").value) * 1024; // KB to Bytes
    
    const formats = Array.from(document.querySelectorAll('input[name="format"]:checked')).map(cb => cb.value);
    
    // UI Updates
    btnStart.disabled = true;
    btnStop.disabled = false;
    statusBadge.textContent = t('status_running');
    statusBadge.className = "badge badge-active";
    
    logsViewer.innerHTML = "";
    liveImageGrid.innerHTML = "";
    liveImageCount = 0;
    liveGalleryCount.textContent = t('gallery_count', { count: 0 });
    
    // Reset Stats
    statPages.textContent = "0";
    statFound.textContent = "0";
    statDownloaded.textContent = "0";
    statFailed.textContent = "0";
    
    addLog(t('log_connecting_and_crawling', { url }), "system");
    
    // Setup WebSocket
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const wsUrl = `${protocol}//${window.location.host}/api/ws/crawl`;
    
    ws = new ReconnectingWebSocket(wsUrl);
    
    ws.onopen = () => {
        // Proxy is handled server-side — no proxy in payload
        ws.send(JSON.stringify({
            url, output_dir, depth, max_pages, fetcher,
            min_file_size, allowed_formats: formats,
        }));
    };
    
    ws.onmessage = (event) => {
        let msg;
        try {
            msg = JSON.parse(event.data);
        } catch (parseErr) {
            console.error('Failed to parse WebSocket message:', parseErr);
            return;
        }
        const eventType = msg.event;
        const data = msg.data;
        
        switch (eventType) {
            case "crawl_started":
                addLog(t('log_crawl_started_root'), "system");
                break;
                
            case "page_started":
                addLog(t('log_scanning_link', { url: data.url }), "info");
                break;
                
            case "page_fetched":
                statPages.textContent = data.pages_visited;
                statFound.textContent = data.images_found;
                addLog(t('log_page_scanned_success', { url: data.url, count: data.images_found }), "success");
                break;
                
            case "image_downloaded":
                // Increment downloaded stat
                const currentDl = parseInt(statDownloaded.textContent);
                statDownloaded.textContent = currentDl + 1;
                
                liveImageCount++;
                liveGalleryCount.textContent = t('gallery_count', { count: liveImageCount });
                
                // Add to live grid
                // Extract domain from url if possible
                let domain = "unknown";
                try {
                    domain = new URL(data.url).hostname;
                } catch(e) {}
                
                // Construct file info structure
                const filename = data.path.split(/[/\\]/).pop();
                const card = createImageCard({
                    name: filename,
                    path: data.path,
                    domain: domain,
                    size: data.size
                });
                
                if (liveImageGrid.querySelector(".placeholder-text")) {
                    liveImageGrid.innerHTML = "";
                }
                liveImageGrid.insertBefore(card, liveImageGrid.firstChild);
                break;
                
            case "image_failed":
                const currentFail = parseInt(statFailed.textContent);
                statFailed.textContent = currentFail + 1;
                addLog(t('log_image_download_failed', { url: data.url, error: data.error }), "warn");
                break;
                
            case "crawl_done":
                const r = data.result;
                addLog(t('log_crawl_completed'), "system");
                addLog(r.summary, "success");
                
                // Update final stats to ensure sync
                statPages.textContent = r.pages_visited;
                statFound.textContent = r.images_found;
                statDownloaded.textContent = r.images_downloaded;
                statFailed.textContent = r.images_failed;
                
                closeWebSocket();
                break;
                
            case "proxy_fallback":
                addLog(t('log_local_ip_blocked_trying_proxy', { proxy: data.proxy }), "proxy");
                updateProxyStatus("proxy", t('proxy_status_using_proxy', { proxy: data.proxy }));
                break;

            case "proxy_success":
                addLog(t('log_backup_proxy_working', { proxy: data.proxy }), "success");
                updateProxyStatus("proxy", t('proxy_status_active', { proxy: data.proxy }));
                break;

            case "local_ip_success":
                addLog(t('log_local_ip_working_no_proxy'), "success");
                updateProxyStatus("local", t('proxy_status_local_working'));
                break;

            case "all_proxies_failed":
                addLog(t('log_all_proxies_failed', { message: data.message }), "error");
                updateProxyStatus("error", t('proxy_status_all_failed'));
                break;

            case "error":
                addLog(t('log_system_error', { message: data.message }), "error");
                closeWebSocket();
                if (data.error_code === 'TRIAL_EXHAUSTED' || data.error_code === 'TRIAL_EXPIRED' || data.error_code === 'KEY_REQUIRED') {
                    handleLicenseError(data.error_code, data.message);
                }
                break;
        }
    };
    
    ws.onerror = (err) => {
        addLog(t('log_websocket_error'), "error");
        closeWebSocket();
    };
    
    ws.onclose = () => {
        addLog(t('log_crawl_connection_closed'), "system");
        closeWebSocket();
    };
});

btnStop.addEventListener("click", () => {
    if (ws) {
        addLog(t('log_stopping_campaign_requested'), "warn");
        ws.close();
    }
    if (productWs) {
        addLog(t('log_stopping_product_scrape_requested'), "warn");
        productWs.close();
    }
});

function closeWebSocket() {
    if (ws) {
        ws.close(1000, 'User stopped');
        ws = null;
    }
    btnStart.disabled = false;
    btnStop.disabled = true;
    statusBadge.textContent = t('status_stopping');
    statusBadge.className = "badge badge-inactive";
}

// Proxy Status Helper
function updateProxyStatus(type, text) {
    const dot = document.querySelector(".proxy-dot");
    const statusText = document.getElementById("proxy-status-text");
    if (!dot || !statusText) return;

    dot.className = "proxy-dot";
    if (type === "local") {
        dot.classList.add("dot-local");
    } else if (type === "proxy") {
        dot.classList.add("dot-proxy");
    } else {
        dot.classList.add("dot-error");
    }
    statusText.textContent = text;
}

// History Gallery Logic
const historyOutputDir = document.getElementById("history-output-dir");
const btnRefreshHistory = document.getElementById("btn-refresh-history");
const historyImageGrid = document.getElementById("history-image-grid");
const historyGalleryCount = document.getElementById("history-gallery-count");
const searchDomain = document.getElementById("search-domain");

let allHistoryImages = [];

async function loadHistory() {
    const outputDirVal = historyOutputDir.value.trim();
    historyImageGrid.innerHTML = `<div class="placeholder-text">${t('history_loading_images')}</div>`;
    
    try {
        const response = await fetch(`/api/history?output_dir=${encodeURIComponent(outputDirVal)}`);
        const data = await response.json();
        
        allHistoryImages = data.images || [];
        renderHistoryGrid(allHistoryImages);
    } catch (err) {
        historyImageGrid.innerHTML = `<div class="placeholder-text error">${t('history_load_failed', { error: err.message })}</div>`;
        historyGalleryCount.textContent = t('gallery_count', { count: 0 });
    }
}

function renderHistoryGrid(imagesList) {
    historyImageGrid.innerHTML = "";
    historyGalleryCount.textContent = t('gallery_count', { count: imagesList.length });
    
    if (imagesList.length === 0) {
        historyImageGrid.innerHTML = `<div class="placeholder-text">${t('history_no_images_found')}</div>`;
        return;
    }
    
    imagesList.forEach(img => {
        const card = createImageCard(img);
        historyImageGrid.appendChild(card);
    });
}

// Search / Filtering by Domain
searchDomain.addEventListener("input", () => {
    const term = searchDomain.value.toLowerCase().trim();
    if (!term) {
        renderHistoryGrid(allHistoryImages);
        return;
    }
    
    const filtered = allHistoryImages.filter(img => 
        img.domain.toLowerCase().includes(term) || 
        img.name.toLowerCase().includes(term)
    );
    renderHistoryGrid(filtered);
});

btnRefreshHistory.addEventListener("click", loadHistory);
historyOutputDir.addEventListener("keypress", (e) => {
    if (e.key === "Enter") {
        loadHistory();
    }
});

// Product History Gallery Logic
const btnRefreshProducts = document.getElementById("btn-refresh-products");

async function loadProductHistory() {
    const outputDir = document.getElementById("output_dir").value.trim() || "./output";
    if (!productTableBody) return;
    
    productTableBody.innerHTML = `
        <tr>
            <td colspan="6" style="padding: 24px; text-align: center; color: var(--text-secondary);">${t('history_loading_images') || 'Loading...'}</td>
        </tr>
    `;
    
    try {
        const response = await fetch(`/api/products?output_dir=${encodeURIComponent(outputDir)}`);
        const data = await response.json();
        
        if (data.ok && data.products) {
            _lastRenderedProductIndex = 0;  // Reset for full re-render
            crawledProducts = data.products.map(p => {
                let feImage = p.main_image_url;
                if (p.local_image_path) {
                    feImage = `/api/image?path=${encodeURIComponent(p.local_image_path)}`;
                }
                return {
                    title: p.title,
                    url: p.url,
                    price: p.price,
                    image: feImage,
                    variants_count: p.variants ? p.variants.length : 0
                };
            });
            renderProductsTable();
        } else {
            productTableBody.innerHTML = `
                <tr>
                    <td colspan="6" style="padding: 24px; text-align: center; color: var(--text-secondary);">${data.error || t('history_load_failed', { error: 'Unknown' })}</td>
                </tr>
            `;
        }
    } catch (err) {
        productTableBody.innerHTML = `
            <tr>
                <td colspan="6" style="padding: 24px; text-align: center; color: var(--text-secondary);">${err.message}</td>
            </tr>
        `;
    }
}

if (btnRefreshProducts) {
    btnRefreshProducts.addEventListener("click", loadProductHistory);
}

// ══════════════════════════════════════════════════════════════
// BATCH IMPORT LOGIC
// ══════════════════════════════════════════════════════════════

let currentMode = "single"; // "single" | "batch"
let batchUrls = []; // Array of URLs parsed from file/sheet
let batchWs = null;

// Mode Toggle
document.querySelectorAll(".mode-btn").forEach(btn => {
    btn.addEventListener("click", () => {
        document.querySelectorAll(".mode-btn").forEach(b => b.classList.remove("active"));
        btn.classList.add("active");
        currentMode = btn.dataset.mode;
        document.getElementById("single-url-panel").style.display = currentMode === "single" ? "block" : "none";
        document.getElementById("batch-import-panel").style.display = currentMode === "batch" ? "block" : "none";
        lucide.createIcons();
    });
});

// Batch Source Tabs (File vs Google Sheets)
document.querySelectorAll(".batch-tab").forEach(tab => {
    tab.addEventListener("click", () => {
        document.querySelectorAll(".batch-tab").forEach(t => t.classList.remove("active"));
        tab.classList.add("active");
        const src = tab.dataset.source;
        document.getElementById("batch-file-source").style.display = src === "file" ? "block" : "none";
        document.getElementById("batch-sheet-source").style.display = src === "sheet" ? "block" : "none";
        lucide.createIcons();
    });
});

// File Upload — Drop Zone
const dropZone = document.getElementById("file-drop-zone");
const fileInput = document.getElementById("batch-file-input");

if (dropZone && fileInput) {
    dropZone.addEventListener("click", () => fileInput.click());
    dropZone.querySelector(".file-browse-link")?.addEventListener("click", (e) => { e.stopPropagation(); fileInput.click(); });

    dropZone.addEventListener("dragover", (e) => { e.preventDefault(); dropZone.classList.add("drag-over"); });
    dropZone.addEventListener("dragleave", () => dropZone.classList.remove("drag-over"));
    dropZone.addEventListener("drop", (e) => {
        e.preventDefault(); dropZone.classList.remove("drag-over");
        if (e.dataTransfer.files.length) { fileInput.files = e.dataTransfer.files; handleFileUpload(e.dataTransfer.files[0]); }
    });
    fileInput.addEventListener("change", () => { if (fileInput.files.length) handleFileUpload(fileInput.files[0]); });
}

async function handleFileUpload(file) {
    const statusEl = document.getElementById("file-upload-status");
    statusEl.style.display = "block";
    statusEl.className = "upload-status loading";
    statusEl.textContent = t('upload_analyzing_file', { name: file.name });

    const formData = new FormData();
    formData.append("file", file);

    try {
        const resp = await fetch("/api/upload-batch", { method: "POST", body: formData });
        const data = await resp.json();
        if (data.ok && data.data) {
            displayParseResult(data.data, statusEl);
        } else {
            statusEl.className = "upload-status error";
            statusEl.textContent = `✗ ${data.error || t('error_unknown')}`;
        }
    } catch (e) {
        statusEl.className = "upload-status error";
        statusEl.textContent = t('error_cannot_connect_server_msg', { message: e.message });
    }
}

// Google Sheets Parse
const btnParseSheet = document.getElementById("btn-parse-sheet");
if (btnParseSheet) {
    btnParseSheet.addEventListener("click", async () => {
        const sheetUrl = document.getElementById("sheet-url").value.trim();
        if (!sheetUrl) return;
        const statusEl = document.getElementById("sheet-parse-status");
        statusEl.style.display = "block";
        statusEl.className = "upload-status loading";
        statusEl.textContent = t('sheet_loading');

        try {
            const resp = await fetch("/api/parse-sheet", {
                method: "POST", headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ url: sheetUrl })
            });
            const data = await resp.json();
            if (data.ok && data.data) {
                displayParseResult(data.data, statusEl);
            } else {
                statusEl.className = "upload-status error";
                statusEl.textContent = `✗ ${data.error || t('error_unknown')}`;
            }
        } catch (e) {
            statusEl.className = "upload-status error";
            statusEl.textContent = `✗ ${e.message}`;
        }
    });
}

function displayParseResult(data, statusEl) {
    batchUrls = data.urls || [];
    const errors = data.errors || [];

    if (batchUrls.length === 0) {
        statusEl.className = "upload-status error";
        statusEl.textContent = t('batch_error_no_valid_urls', { errors: errors.join('; ') });
        return;
    }

    statusEl.className = "upload-status success";
    statusEl.textContent = t('batch_success_urls_parsed', { valid_count: data.valid_count, skipped_count: data.skipped_count, duplicate_count: data.duplicate_count });
    if (errors.length) statusEl.textContent += ` — ${errors.join("; ")}`;

    renderUrlPreview();
}

function renderUrlPreview() {
    const section = document.getElementById("url-preview-section");
    const list = document.getElementById("url-preview-list");
    const badge = document.getElementById("url-count-badge");
    section.style.display = "block";
    badge.textContent = t('url_count_badge', { count: batchUrls.length });
    list.innerHTML = "";

    batchUrls.forEach((url, i) => {
        const item = document.createElement("div");
        item.className = "url-preview-item";
        let domain = "unknown";
        try { domain = new URL(url).hostname; } catch(e) {}
        item.innerHTML = `
            <span class="url-index">${i + 1}</span>
            <span class="url-domain-chip">${domain}</span>
            <span class="url-text" title="${url}">${url}</span>
            <button type="button" class="url-remove-btn" data-idx="${i}"><i data-lucide="x"></i></button>
        `;
        item.querySelector(".url-remove-btn").addEventListener("click", () => {
            batchUrls.splice(i, 1); renderUrlPreview(); lucide.createIcons();
        });
        list.appendChild(item);
    });
    lucide.createIcons();
}

// Clear all URLs
const btnClearUrls = document.getElementById("btn-clear-urls");
if (btnClearUrls) {
    btnClearUrls.addEventListener("click", () => {
        batchUrls = [];
        document.getElementById("url-preview-section").style.display = "none";
        document.getElementById("file-upload-status").style.display = "none";
        document.getElementById("sheet-parse-status").style.display = "none";
    });
}

// ── Batch Crawl WebSocket ──
function startBatchCrawl() {
    if (!batchUrls.length) { showToast(t('alert_import_urls_first'), 'warning'); return; }

    const output_dir = document.getElementById("output_dir").value.trim();
    const depth = parseInt(document.getElementById("depth").value);
    const max_pages = parseInt(document.getElementById("max_pages").value);
    const fetcher = document.getElementById("fetcher").value;
    const min_file_size = parseInt(document.getElementById("min_file_size").value) * 1024;
    const formats = Array.from(document.querySelectorAll('input[name="format"]:checked')).map(cb => cb.value);

    // UI reset
    btnStart.disabled = true; btnStop.disabled = false;
    statusBadge.textContent = t('status_batch_running'); statusBadge.className = "badge badge-active";
    logsViewer.innerHTML = ""; liveImageGrid.innerHTML = ""; liveImageCount = 0;
    liveGalleryCount.textContent = t('gallery_count', { count: 0 });
    statPages.textContent = "0"; statFound.textContent = "0"; statDownloaded.textContent = "0"; statFailed.textContent = "0";

    // Show batch progress
    const batchSection = document.getElementById("batch-progress-section");
    batchSection.style.display = "block";
    document.getElementById("batch-progress-bar").style.width = "0%";
    document.getElementById("batch-progress-counter").textContent = `0/${batchUrls.length}`;
    document.getElementById("batch-stat-success").textContent = "0";
    document.getElementById("batch-stat-failed").textContent = "0";
    document.getElementById("batch-stat-running").textContent = "0";

    // Build URL cards
    const cardsEl = document.getElementById("batch-url-cards");
    cardsEl.innerHTML = "";
    batchUrls.forEach((url, i) => {
        let domain = "unknown"; try { domain = new URL(url).hostname; } catch(e) {}
        const card = document.createElement("div");
        card.className = "batch-url-card status-pending";
        card.id = `batch-card-${i}`;
        card.innerHTML = `<span class="batch-card-idx">${i+1}</span><span class="batch-card-domain">${domain}</span><span class="batch-card-status">${t('status_pending')}</span>`;
        cardsEl.appendChild(card);
    });
    lucide.createIcons();

    addLog(t('log_batch_crawl_start', { count: batchUrls.length }), "system");

    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    batchWs = new ReconnectingWebSocket(`${protocol}//${window.location.host}/api/ws/batch-crawl`);

    let completedCount = 0, batchSuccess = 0, batchFailed = 0;

    batchWs.onopen = () => {
        batchWs.send(JSON.stringify({ urls: batchUrls, output_dir, depth, max_pages, fetcher, min_file_size, allowed_formats: formats }));
    };

    batchWs.onmessage = (event) => {
        let msg;
        try {
            msg = JSON.parse(event.data);
        } catch (parseErr) {
            console.error('Failed to parse WebSocket message:', parseErr);
            return;
        }
        const { event: evt, data: d } = msg;

        switch (evt) {
            case "batch_start":
                addLog(t('log_batch_started_details', { total_urls: d.total_urls, domain_groups: d.domain_groups }), "system");
                break;
            case "batch_url_start": {
                const card = document.getElementById(`batch-card-${d.index}`);
                if (card) { card.className = "batch-url-card status-running"; card.querySelector(".batch-card-status").textContent = t('status_crawling'); }
                document.getElementById("batch-stat-running").textContent = parseInt(document.getElementById("batch-stat-running").textContent) + 1;
                addLog(t('log_batch_url_started', { index: d.index + 1, total: batchUrls.length, url: d.url }), "info");
                break;
            }
            case "page_fetched":
                statPages.textContent = parseInt(statPages.textContent) + 1;
                statFound.textContent = parseInt(statFound.textContent) + (d.images || 0);
                break;
            case "image_downloaded": {
                statDownloaded.textContent = parseInt(statDownloaded.textContent) + 1;
                liveImageCount++; liveGalleryCount.textContent = t('gallery_count', { count: liveImageCount });
                let domain = "unknown"; try { domain = new URL(d.url).hostname; } catch(e) {}
                const fname = d.path.split(/[/\\]/).pop();
                const card = createImageCard({ name: fname, path: d.path, domain, size: d.size });
                if (liveImageGrid.querySelector(".placeholder-text")) liveImageGrid.innerHTML = "";
                liveImageGrid.insertBefore(card, liveImageGrid.firstChild);
                break;
            }
            case "batch_url_done": {
                completedCount++; batchSuccess++;
                const card = document.getElementById(`batch-card-${d.index}`);
                if (card) { card.className = "batch-url-card status-success"; card.querySelector(".batch-card-status").textContent = t('batch_card_status_success', { count: d.result.images_downloaded }); }
                document.getElementById("batch-stat-success").textContent = batchSuccess;
                document.getElementById("batch-stat-running").textContent = Math.max(0, parseInt(document.getElementById("batch-stat-running").textContent) - 1);
                updateBatchProgress(completedCount, batchUrls.length);
                addLog(t('log_batch_url_done', { index: d.index + 1, url: d.url, count: d.result.images_downloaded }), "success");
                break;
            }
            case "batch_url_error": {
                completedCount++; batchFailed++;
                const card = document.getElementById(`batch-card-${d.index}`);
                if (card) { card.className = "batch-url-card status-error"; card.querySelector(".batch-card-status").textContent = t('status_error'); }
                document.getElementById("batch-stat-failed").textContent = batchFailed;
                document.getElementById("batch-stat-running").textContent = Math.max(0, parseInt(document.getElementById("batch-stat-running").textContent) - 1);
                updateBatchProgress(completedCount, batchUrls.length);
                addLog(t('log_batch_url_error', { index: d.index + 1, url: d.url, error: d.error }), "error");
                break;
            }
            case "batch_done":
                addLog(t('log_batch_completed_summary', { success: d.success, failed: d.failed }), "system");
                closeBatchWs();
                break;
            case "error":
                addLog(t('log_error_msg', { message: d.message }), "error");
                closeBatchWs();
                if (d.error_code === 'TRIAL_EXHAUSTED' || d.error_code === 'TRIAL_EXPIRED' || d.error_code === 'KEY_REQUIRED') {
                    handleLicenseError(d.error_code, d.message);
                }
                break;
        }
    };

    batchWs.onerror = () => { addLog(t('log_websocket_connection_error'), "error"); closeBatchWs(); };
    batchWs.onclose = () => { closeBatchWs(); };
}

function updateBatchProgress(done, total) {
    const pct = total > 0 ? Math.round((done / total) * 100) : 0;
    document.getElementById("batch-progress-bar").style.width = `${pct}%`;
    document.getElementById("batch-progress-counter").textContent = `${done}/${total}`;
}

function closeBatchWs() {
    if (batchWs) { try { batchWs.close(1000, 'User stopped'); } catch(e) {} batchWs = null; }
    btnStart.disabled = false; btnStop.disabled = true;
    statusBadge.textContent = t('status_stopping'); statusBadge.className = "badge badge-inactive";
}

// Override stop button for batch mode too
btnStop.addEventListener("click", () => {
    if (batchWs) { addLog(t('log_stopping_batch_requested'), "warn"); batchWs.close(); }
});

// ══════════════════════════════════════════════════════════════
// PRODUCT SCRAPER LOGIC (Unified — inside main tab)
// ══════════════════════════════════════════════════════════════

// Track last rendered product index for incremental rendering
let _lastRenderedProductIndex = 0;

function appendProductRow(product, index) {
    if (!productTableBody) return;
    const row = document.createElement("tr");
    row.style.borderBottom = "1px solid var(--border-color)";
    
    const imgTd = document.createElement("td");
    imgTd.style.padding = "12px";
    if (product.image) {
        imgTd.innerHTML = `<img src="${product.image}" style="width: 48px; height: 48px; object-fit: cover; border-radius: 8px;" alt="${product.title}">`;
    } else {
        imgTd.innerHTML = `<div style="width: 48px; height: 48px; background: var(--border-color); border-radius: 8px; display: flex; align-items: center; justify-content: center;"><i data-lucide="image" style="width: 18px; color: var(--text-secondary);"></i></div>`;
    }
    
    const titleTd = document.createElement("td");
    titleTd.style.padding = "12px";
    titleTd.innerHTML = `<div style="font-weight: 500;">${product.title || t('product_no_name')}</div><div style="font-size: 12px; color: var(--text-secondary); word-break: break-all;">${product.url}</div>`;
    
    const priceTd = document.createElement("td");
    priceTd.style.padding = "12px";
    priceTd.textContent = product.price !== null ? `${product.price.toLocaleString('vi-VN')} USD` : t('product_not_updated');
    
    const siteTd = document.createElement("td");
    siteTd.style.padding = "12px";
    let domain = "generic";
    try { domain = new URL(product.url).hostname.replace('www.', ''); } catch(e) {}
    siteTd.innerHTML = `<span class="url-domain-chip" style="background: var(--bg-body); border: 1px solid var(--border-color);">${domain}</span>`;
    
    const variantsTd = document.createElement("td");
    variantsTd.style.padding = "12px";
    variantsTd.textContent = product.variants_count || 0;
    
    const actionTd = document.createElement("td");
    actionTd.style.padding = "12px";
    const btnDetail = document.createElement("button");
    btnDetail.type = "button";
    btnDetail.className = "btn-outline-sm btn-press";
    btnDetail.style.padding = "4px 8px";
    btnDetail.innerHTML = `<i data-lucide="eye" style="width: 14px; height: 14px; margin-right: 4px;"></i> ${t('btn_view')}`;
    btnDetail.addEventListener("click", () => {
        showToast(t('alert_product_details', { title: product.title, price: product.price || 'N/A', variants: product.variants_count || 0 }), 'info', 6000);
    });
    actionTd.appendChild(btnDetail);
    
    row.appendChild(imgTd);
    row.appendChild(titleTd);
    row.appendChild(priceTd);
    row.appendChild(siteTd);
    row.appendChild(variantsTd);
    row.appendChild(actionTd);
    
    productTableBody.appendChild(row);
}

function renderProductsTable() {
    if (!productTableBody) return;

    if (_lastRenderedProductIndex === 0) {
        productTableBody.innerHTML = "";  // Only clear on first render
    }

    if (crawledProducts.length === 0) {
        productTableBody.innerHTML = `
            <tr>
                <td colspan="6" style="padding: 24px; text-align: center; color: var(--text-secondary);">${t("product_placeholder_empty")}</td>
            </tr>
        `;
        return;
    }

    // Only render new products since last render
    for (let i = _lastRenderedProductIndex; i < crawledProducts.length; i++) {
        appendProductRow(crawledProducts[i], i);
    }
    _lastRenderedProductIndex = crawledProducts.length;

    // Update count
    productResultCount.textContent = t('product_count', { count: crawledProducts.length });
    
    lucide.createIcons();
}

// Reset function for when starting a new crawl or loading history
function resetProductsTable() {
    _lastRenderedProductIndex = 0;
    crawledProducts = [];
    if (productTableBody) productTableBody.innerHTML = '';
}

function startProductCrawl() {
    // Gather URL(s) from the main URL input
    const url = document.getElementById("url").value.trim();
    if (!url) {
        showToast(t('alert_enter_product_url'), 'warning');
        return;
    }
    const urls = url.split("\n").map(u => u.trim()).filter(u => u.length > 0);
    
    const output_dir = document.getElementById("output_dir").value.trim();
    const max_products = parseInt(document.getElementById("max-products").value) || 50;
    
    // UI Updates — use shared controls
    btnStart.disabled = true;
    btnStop.disabled = false;
    statusBadge.textContent = t('status_scraping_products');
    statusBadge.className = "badge badge-active";
    
    logsViewer.innerHTML = "";
    resetProductsTable();
    renderProductsTable();
    
    // Reset Stats
    statProdTotal.textContent = "0";
    statProdSuccess.textContent = "0";
    statProdFailed.textContent = "0";
    
    addLog(t('log_connecting_and_scraping_products'), "system");
    
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const wsUrl = `${protocol}//${window.location.host}/api/ws/product-crawl`;
    
    productWs = new ReconnectingWebSocket(wsUrl);
    
    productWs.onopen = () => {
        productWs.send(JSON.stringify({ urls, output_dir, max_products }));
    };
    
    productWs.onmessage = (event) => {
        let msg;
        try {
            msg = JSON.parse(event.data);
        } catch (parseErr) {
            console.error('Failed to parse WebSocket message:', parseErr);
            return;
        }
        const eventType = msg.event;
        const data = msg.data;
        
        switch (eventType) {
            case "product_crawl_start":
                addLog(t('log_product_crawl_campaign_started'), "system");
                break;
                
            case "fetch_page_start":
                addLog(t('log_scraping_category_page', { url: data.url, fetcher: data.fetcher }), "info");
                break;
                
            case "fetch_page_success":
                addLog(t('log_category_page_success', { url: data.url }), "success");
                break;
                
            case "fetch_page_failed":
                addLog(t('log_category_page_failed', { url: data.url, status: data.status }), "error");
                statProdFailed.textContent = parseInt(statProdFailed.textContent) + 1;
                break;
                
            case "listing_detected":
                addLog(t('log_category_page_detected', { count: data.count }), "info");
                statProdTotal.textContent = data.count;
                break;
                
            case "fetch_product_start":
                addLog(t('log_loading_product_detail_page', { url: data.url }), "info");
                break;
                
            case "fetch_product_failed":
                addLog(t('log_product_page_failed', { url: data.url, status: data.status }), "warn");
                statProdFailed.textContent = parseInt(statProdFailed.textContent) + 1;
                break;
                
            case "product_extracted":
                addLog(t('log_product_success', { title: data.title, price: data.price || 'N/A' }), "success");
                statProdSuccess.textContent = parseInt(statProdSuccess.textContent) + 1;
                
                crawledProducts.push(data);
                renderProductsTable();
                break;
                
            case "product_extraction_failed":
                addLog(t('log_product_extraction_failed', { url: data.url, reason: data.reason }), "warn");
                statProdFailed.textContent = parseInt(statProdFailed.textContent) + 1;
                break;
                
            case "product_error":
                addLog(t('log_product_processing_error', { url: data.url, error: data.error }), "warn");
                statProdFailed.textContent = parseInt(statProdFailed.textContent) + 1;
                break;
                
            case "product_crawl_done":
                addLog(t('log_product_crawl_campaign_completed', { count: data.count }), "system");
                closeProductWebSocket();
                break;
                
            case "error":
                addLog(t('log_system_error', { message: data.message }), "error");
                closeProductWebSocket();
                if (data.error_code === 'TRIAL_EXHAUSTED' || data.error_code === 'TRIAL_EXPIRED' || data.error_code === 'KEY_REQUIRED') {
                    handleLicenseError(data.error_code, data.message);
                }
                break;
        }
    };
    
    productWs.onerror = (err) => {
        addLog(t('log_websocket_error'), "error");
        closeProductWebSocket();
    };
    
    productWs.onclose = () => {
        addLog(t('log_product_crawl_connection_closed'), "system");
        closeProductWebSocket();
    };
}

function closeProductWebSocket() {
    if (productWs) {
        productWs.close(1000, 'User stopped');
        productWs = null;
    }
    btnStart.disabled = false;
    btnStop.disabled = true;
    statusBadge.textContent = t('status_stopping');
    statusBadge.className = "badge badge-inactive";
}


// Language changes event listener to trigger redraws
window.addEventListener('languageChanged', (e) => {
    // Redraw badge title if license key is loaded
    if (licenseData) {
        applyLicenseTier();
    }
    
    // Update active tab buttons text
    const activeTab = document.querySelector('.tab-btn.active').getAttribute('data-tab');
    
    // Update live gallery count
    const liveGalleryCount = document.getElementById("live-gallery-count");
    if (liveGalleryCount && liveImageCount !== undefined) {
        liveGalleryCount.textContent = t('gallery_count', { count: liveImageCount });
    }
    
    // Update history count
    if (typeof allHistoryImages !== 'undefined') {
        const historyCount = document.getElementById("history-gallery-count");
        if (historyCount) {
            historyCount.textContent = t('gallery_count', { count: allHistoryImages.length });
        }
    }
});
