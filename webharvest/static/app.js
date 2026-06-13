// ══════════════════════════════════════════════════════════════
// LICENSE GATE — Validates key on startup, shows gate if needed
// ══════════════════════════════════════════════════════════════

const LICENSE_KEY_STORAGE = 'wh_license_key';
const LICENSE_DATA_STORAGE = 'wh_license_data';
let licenseData = null;  // {tier, limits, expires_at, ...}

async function initLicenseGate() {
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
                hideLicenseGate();
                return;
            }
        } catch (e) {
            // Offline — try cached data
            const cached = localStorage.getItem(LICENSE_DATA_STORAGE);
            if (cached) {
                licenseData = JSON.parse(cached);
                applyLicenseTier();
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
            licenseData = { valid: true, tier: 'unlimited', limits: { batch_crawl: true, stealth_mode: true, proxy_support: true, max_daily_urls: 999999, max_concurrent: 20 } };
            applyLicenseTier();
            hideLicenseGate();
            return;
        }
    } catch (e) { /* ignore */ }

    showLicenseGate();
}

function showLicenseGate() {
    const gate = document.getElementById('license-gate');
    if (gate) gate.style.display = 'flex';
}

function hideLicenseGate() {
    const gate = document.getElementById('license-gate');
    if (gate) gate.style.display = 'none';
}

function applyLicenseTier() {
    if (!licenseData) return;
    const tier = licenseData.tier || 'basic';
    const limits = licenseData.limits || {};

    // Update tier badge in header
    const badge = document.getElementById('tier-badge');
    if (badge) {
        const tierNames = { basic: 'Basic', pro: 'Pro', unlimited: 'Unlimited' };
        const tierIcons = { basic: '⚡', pro: '⭐', unlimited: '💎' };
        badge.textContent = `${tierIcons[tier] || '⚡'} ${tierNames[tier] || tier}`;
        badge.className = `tier-badge tier-${tier}`;
        badge.style.display = 'inline-flex';

        if (licenseData.expires_at) {
            const exp = new Date(licenseData.expires_at);
            badge.title = `Hết hạn: ${exp.toLocaleDateString('vi-VN')}`;
        }
    }

    // Disable batch crawl for Basic
    if (!limits.batch_crawl) {
        document.querySelectorAll('.mode-btn[data-mode="batch"]').forEach(btn => {
            btn.classList.add('tier-locked');
            btn.title = 'Nâng cấp lên Pro để sử dụng Batch Crawl';
        });
    }

    // Disable stealth/proxy for Basic
    const fetcherSelect = document.getElementById('fetcher');
    if (fetcherSelect && limits.allowed_fetchers) {
        Array.from(fetcherSelect.options).forEach(opt => {
            if (!limits.allowed_fetchers.includes(opt.value) && opt.value !== 'auto') {
                opt.disabled = true;
                opt.textContent += ' 🔒';
            }
        });
    }
}

async function activateLicenseKey() {
    const input = document.getElementById('license-key-input');
    const errEl = document.getElementById('license-error');
    const key = (input?.value || '').trim().toUpperCase();

    if (!key) { errEl.textContent = 'Vui lòng nhập license key'; errEl.style.display = 'block'; return; }

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
                'NOT_FOUND': 'Key không tồn tại. Vui lòng kiểm tra lại.',
                'DEVICE_MISMATCH': 'Key đã được sử dụng trên thiết bị khác.',
                'EXPIRED': 'Key đã hết hạn. Vui lòng gia hạn.',
                'REVOKED': 'Key đã bị thu hồi.',
                'UNREACHABLE': 'Không thể kết nối đến server. Kiểm tra mạng.',
            };
            errEl.textContent = messages[data.error_code] || data.error || 'Kích hoạt thất bại';
            errEl.style.display = 'block';
        }
    } catch (e) {
        errEl.textContent = 'Lỗi kết nối. Kiểm tra mạng và thử lại.';
        errEl.style.display = 'block';
    }
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
            if (statusEl) { statusEl.textContent = '⏳ Đang chờ thanh toán...'; statusEl.style.display = 'block'; }

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
                            if (statusEl) { statusEl.textContent = `✅ Thanh toán thành công! Key: ${vData.data.key}`; }
                            // Re-validate
                            setTimeout(() => initLicenseGate(), 1500);
                        }
                    } else if (vData.data?.status === 'cancelled') {
                        clearInterval(_paymentPollInterval);
                        if (statusEl) { statusEl.textContent = '❌ Thanh toán đã bị hủy.'; }
                    }
                } catch (e) { /* keep polling */ }
            }, 3000);
        } else {
            errEl.textContent = data.error || 'Không thể tạo link thanh toán';
            errEl.style.display = 'block';
        }
    } catch (e) {
        errEl.textContent = 'Lỗi kết nối đến server.';
        errEl.style.display = 'block';
    }
}

// Initialize Lucide Icons
document.addEventListener("DOMContentLoaded", () => {
    lucide.createIcons();
    initLicenseGate();
    loadHistory();
    initProxyPanel();
    initAppleScrollAnimations();
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

// ── DataImpulse Proxy Panel Logic ──────────────────────────────────
function initProxyPanel() {
    const providerSelect = document.getElementById("proxy-provider");
    const diPanel = document.getElementById("di-panel");
    const manualPanel = document.getElementById("manual-panel");

    // Toggle panels based on provider selection
    providerSelect.addEventListener("change", () => {
        const val = providerSelect.value;
        diPanel.style.display = val === "dataimpulse" ? "block" : "none";
        manualPanel.style.display = val === "manual" ? "block" : "none";
        syncProxyHiddenField();
        lucide.createIcons(); // re-render icons in newly visible panels
    });

    // Password toggle
    const btnEye = document.getElementById("btn-toggle-pass");
    const passInput = document.getElementById("di-password");
    if (btnEye && passInput) {
        btnEye.addEventListener("click", () => {
            const isPassword = passInput.type === "password";
            passInput.type = isPassword ? "text" : "password";
            // Swap icon
            const icon = btnEye.querySelector("i");
            if (icon) icon.setAttribute("data-lucide", isPassword ? "eye-off" : "eye");
            lucide.createIcons();
        });
    }

    // Test connection button
    const btnTest = document.getElementById("btn-test-proxy");
    if (btnTest) btnTest.addEventListener("click", testProxyConnection);

    // Save settings button
    const btnSave = document.getElementById("btn-save-proxy");
    if (btnSave) btnSave.addEventListener("click", saveProxySettings);

    // Load saved settings from backend
    loadProxySettings();
}

function buildDataImpulseProxy() {
    const user = (document.getElementById("di-username").value || "").trim();
    const pass = (document.getElementById("di-password").value || "").trim();
    const country = document.getElementById("di-country").value;
    const session = document.getElementById("di-session").value;

    if (!user || !pass) return "";

    let params = [];
    if (country) params.push(`cr.${country}`);
    if (session !== "0") params.push(`sessttl.${session}`);

    const login = params.length > 0 ? `${user}__${params.join(";")}` : user;
    return `http://${login}:${pass}@gw.dataimpulse.com:823`;
}

function syncProxyHiddenField() {
    const provider = document.getElementById("proxy-provider").value;
    const hidden = document.getElementById("proxy");

    if (provider === "dataimpulse") {
        hidden.value = buildDataImpulseProxy();
    } else if (provider === "manual") {
        hidden.value = (document.getElementById("proxy-manual").value || "").trim();
    } else {
        hidden.value = "";
    }
}

async function testProxyConnection() {
    syncProxyHiddenField();
    const proxyUrl = document.getElementById("proxy").value;
    const resultEl = document.getElementById("proxy-test-result");
    const btn = document.getElementById("btn-test-proxy");

    if (!proxyUrl) {
        resultEl.className = "proxy-test-result error";
        resultEl.textContent = "⚠ Vui lòng nhập đầy đủ thông tin proxy";
        return;
    }

    resultEl.className = "proxy-test-result loading";
    resultEl.textContent = "⏳ Đang kiểm tra...";
    btn.classList.add("testing");

    try {
        const resp = await fetch("/api/test-proxy", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ proxy: proxyUrl })
        });
        const data = await resp.json();
        if (data.ok) {
            resultEl.className = "proxy-test-result success";
            resultEl.textContent = `✓ Kết nối thành công — IP: ${data.ip}`;
        } else {
            resultEl.className = "proxy-test-result error";
            resultEl.textContent = `✗ Lỗi: ${data.error}`;
        }
    } catch (e) {
        resultEl.className = "proxy-test-result error";
        resultEl.textContent = `✗ Không thể kết nối server`;
    } finally {
        btn.classList.remove("testing");
    }
}

async function saveProxySettings() {
    const provider = document.getElementById("proxy-provider").value;
    const payload = {
        provider,
        di_username: (document.getElementById("di-username").value || "").trim(),
        di_password: (document.getElementById("di-password").value || "").trim(),
        di_country: document.getElementById("di-country").value,
        di_session: document.getElementById("di-session").value,
        manual_proxy: (document.getElementById("proxy-manual").value || "").trim(),
    };

    const resultEl = document.getElementById("proxy-test-result");
    try {
        const resp = await fetch("/api/proxy-settings", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        });
        const data = await resp.json();
        if (data.ok) {
            resultEl.className = "proxy-test-result success";
            resultEl.textContent = "✓ Đã lưu cài đặt thành công";
            setTimeout(() => { resultEl.textContent = ""; resultEl.className = "proxy-test-result"; }, 3000);
        } else {
            resultEl.className = "proxy-test-result error";
            resultEl.textContent = `✗ Lỗi lưu: ${data.error}`;
        }
    } catch (e) {
        resultEl.className = "proxy-test-result error";
        resultEl.textContent = "✗ Không thể kết nối server";
    }
}

async function loadProxySettings() {
    try {
        const resp = await fetch("/api/proxy-settings");
        const data = await resp.json();
        if (data.ok && data.settings && Object.keys(data.settings).length > 0) {
            const s = data.settings;
            const providerSelect = document.getElementById("proxy-provider");
            if (s.provider) providerSelect.value = s.provider;
            if (s.di_username) document.getElementById("di-username").value = s.di_username;
            if (s.di_password) document.getElementById("di-password").value = s.di_password;
            if (s.di_country) document.getElementById("di-country").value = s.di_country;
            if (s.di_session) document.getElementById("di-session").value = s.di_session;
            if (s.manual_proxy) document.getElementById("proxy-manual").value = s.manual_proxy;

            // Show relevant panel
            const diPanel = document.getElementById("di-panel");
            const manualPanel = document.getElementById("manual-panel");
            diPanel.style.display = s.provider === "dataimpulse" ? "block" : "none";
            manualPanel.style.display = s.provider === "manual" ? "block" : "none";
            syncProxyHiddenField();
            lucide.createIcons();
        }
    } catch (e) {
        // Settings not available yet — ignore
    }
}

// Tab Navigation
const tabButtons = document.querySelectorAll(".tab-btn");
const tabContents = document.querySelectorAll(".tab-content");

tabButtons.forEach(button => {
    button.addEventListener("click", () => {
        const targetTab = button.dataset.tab;
        
        tabButtons.forEach(btn => btn.classList.remove("active"));
        tabContents.forEach(content => content.classList.remove("active"));
        
        button.classList.add("active");
        document.getElementById(`tab-${targetTab}`).classList.add("active");
        
        if (targetTab === "gallery") {
            loadHistory();
        }
    });
});

// App State
let ws = null;
let liveImageCount = 0;

// Elements
const crawlForm = document.getElementById("crawl-form");
const btnStart = document.getElementById("btn-start");
const btnStop = document.getElementById("btn-stop");
const statusBadge = document.getElementById("status-badge");
const logsViewer = document.getElementById("logs-viewer");
const liveImageGrid = document.getElementById("live-image-grid");
const liveGalleryCount = document.getElementById("live-gallery-count");

// Stats Elements
const statPages = document.getElementById("stat-pages");
const statFound = document.getElementById("stat-found");
const statDownloaded = document.getElementById("stat-downloaded");
const statFailed = document.getElementById("stat-failed");

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
function addLog(message, type = "info") {
    const time = new Date().toLocaleTimeString();
    const logLine = document.createElement("div");
    logLine.className = `log-line ${type}`;
    logLine.textContent = `[${time}] ${message}`;
    logsViewer.appendChild(logLine);
    logsViewer.scrollTop = logsViewer.scrollHeight;
}

// Helper: Create Image Card Element
function createImageCard(imgData) {
    const card = document.createElement("div");
    card.className = "image-item";
    
    const imageUrl = `/api/image?path=${encodeURIComponent(imgData.path)}`;
    
    card.innerHTML = `
        <img src="${imageUrl}" alt="${imgData.name}" loading="lazy">
        <div class="image-overlay">
            <span class="img-title" title="${imgData.name}">${imgData.name}</span>
            <div class="img-meta">
                <span class="img-domain">${imgData.domain}</span>
                <span>${formatBytes(imgData.size)}</span>
            </div>
        </div>
    `;
    
    // Zoom on Click
    card.addEventListener("click", () => {
        modal.style.display = "block";
        modalImg.src = imageUrl;
        modalCaption.textContent = `${imgData.name} (${imgData.domain}) - Kích thước: ${formatBytes(imgData.size)}`;
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
    statusBadge.textContent = "Đang chạy";
    statusBadge.className = "badge badge-active";
    
    logsViewer.innerHTML = "";
    liveImageGrid.innerHTML = "";
    liveImageCount = 0;
    liveGalleryCount.textContent = "0 ảnh";
    
    // Reset Stats
    statPages.textContent = "0";
    statFound.textContent = "0";
    statDownloaded.textContent = "0";
    statFailed.textContent = "0";
    
    addLog(`Đang kết nối tới server và bắt đầu cào: ${url}...`, "system");
    
    // Setup WebSocket
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const wsUrl = `${protocol}//${window.location.host}/api/ws/crawl`;
    
    ws = new WebSocket(wsUrl);
    
    ws.onopen = () => {
        // Compose proxy URL from current panel state before sending
        syncProxyHiddenField();
        const proxy = document.getElementById("proxy").value.trim();
        const payload = {
            url,
            output_dir,
            depth,
            max_pages,
            fetcher,
            min_file_size,
            allowed_formats: formats,
            proxy: proxy || null
        };
        ws.send(JSON.stringify(payload));
    };
    
    ws.onmessage = (event) => {
        const msg = JSON.parse(event.data);
        const eventType = msg.event;
        const data = msg.data;
        
        switch (eventType) {
            case "crawl_started":
                addLog(`Bắt đầu cào dữ liệu từ URL gốc...`, "system");
                break;
                
            case "page_started":
                addLog(`Đang quét liên kết: ${data.url}`, "info");
                break;
                
            case "page_fetched":
                statPages.textContent = data.pages_visited;
                statFound.textContent = data.images_found;
                addLog(`Quét thành công trang: ${data.url} - Tìm thấy ${data.images_found} ảnh`, "success");
                break;
                
            case "image_downloaded":
                // Increment downloaded stat
                const currentDl = parseInt(statDownloaded.textContent);
                statDownloaded.textContent = currentDl + 1;
                
                liveImageCount++;
                liveGalleryCount.textContent = `${liveImageCount} ảnh`;
                
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
                addLog(`Lỗi tải ảnh: ${data.url} - ${data.error}`, "warn");
                break;
                
            case "crawl_done":
                const r = data.result;
                addLog(`Hoàn thành chiến dịch cào dữ liệu!`, "system");
                addLog(r.summary, "success");
                
                // Update final stats to ensure sync
                statPages.textContent = r.pages_visited;
                statFound.textContent = r.images_found;
                statDownloaded.textContent = r.images_downloaded;
                statFailed.textContent = r.images_failed;
                
                closeWebSocket();
                break;
                
            case "proxy_fallback":
                addLog(`⚠ IP local bị chặn — đang thử proxy dự phòng: ${data.proxy}`, "proxy");
                updateProxyStatus("proxy", `Đang dùng proxy: ${data.proxy}`);
                break;

            case "proxy_success":
                addLog(`✓ Proxy dự phòng hoạt động: ${data.proxy}`, "success");
                updateProxyStatus("proxy", `Proxy đang hoạt động: ${data.proxy}`);
                break;

            case "local_ip_success":
                addLog(`✓ IP máy local hoạt động tốt — không cần proxy`, "success");
                updateProxyStatus("local", "IP máy local hoạt động tốt");
                break;

            case "all_proxies_failed":
                addLog(`✗ Tất cả proxy đều thất bại: ${data.message}`, "error");
                updateProxyStatus("error", "Tất cả proxy đều thất bại");
                break;

            case "error":
                addLog(`Lỗi hệ thống: ${data.message}`, "error");
                closeWebSocket();
                break;
        }
    };
    
    ws.onerror = (err) => {
        addLog(`Kết nối WebSocket gặp lỗi.`, "error");
        closeWebSocket();
    };
    
    ws.onclose = () => {
        addLog(`Đã đóng kết nối cào dữ liệu.`, "system");
        closeWebSocket();
    };
});

btnStop.addEventListener("click", () => {
    if (ws) {
        addLog("Đang dừng chiến dịch theo yêu cầu...", "warn");
        ws.close();
    }
});

function closeWebSocket() {
    if (ws) {
        ws = null;
    }
    btnStart.disabled = false;
    btnStop.disabled = true;
    statusBadge.textContent = "Đang dừng";
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
    historyImageGrid.innerHTML = `<div class="placeholder-text">Đang tải danh sách ảnh...</div>`;
    
    try {
        const response = await fetch(`/api/history?output_dir=${encodeURIComponent(outputDirVal)}`);
        const data = await response.json();
        
        allHistoryImages = data.images || [];
        renderHistoryGrid(allHistoryImages);
    } catch (err) {
        historyImageGrid.innerHTML = `<div class="placeholder-text error">Không thể tải lịch sử ảnh: ${err.message}</div>`;
        historyGalleryCount.textContent = "0 ảnh";
    }
}

function renderHistoryGrid(imagesList) {
    historyImageGrid.innerHTML = "";
    historyGalleryCount.textContent = `${imagesList.length} ảnh`;
    
    if (imagesList.length === 0) {
        historyImageGrid.innerHTML = `<div class="placeholder-text">Không tìm thấy ảnh nào trong thư mục này.</div>`;
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
    statusEl.textContent = `⏳ Đang phân tích ${file.name}...`;

    const formData = new FormData();
    formData.append("file", file);

    try {
        const resp = await fetch("/api/upload-batch", { method: "POST", body: formData });
        const data = await resp.json();
        if (data.ok && data.data) {
            displayParseResult(data.data, statusEl);
        } else {
            statusEl.className = "upload-status error";
            statusEl.textContent = `✗ ${data.error || "Lỗi không xác định"}`;
        }
    } catch (e) {
        statusEl.className = "upload-status error";
        statusEl.textContent = `✗ Không thể kết nối server: ${e.message}`;
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
        statusEl.textContent = "⏳ Đang tải Google Sheet...";

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
                statusEl.textContent = `✗ ${data.error || "Lỗi không xác định"}`;
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
        statusEl.textContent = `✗ Không tìm thấy URL hợp lệ. ${errors.join("; ")}`;
        return;
    }

    statusEl.className = "upload-status success";
    statusEl.textContent = `✓ ${data.valid_count} URL hợp lệ (${data.skipped_count} bỏ qua, ${data.duplicate_count} trùng)`;
    if (errors.length) statusEl.textContent += ` — ${errors.join("; ")}`;

    renderUrlPreview();
}

function renderUrlPreview() {
    const section = document.getElementById("url-preview-section");
    const list = document.getElementById("url-preview-list");
    const badge = document.getElementById("url-count-badge");
    section.style.display = "block";
    badge.textContent = `${batchUrls.length} URL`;
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
    if (!batchUrls.length) { alert("Vui lòng import danh sách URL trước."); return; }

    const output_dir = document.getElementById("output_dir").value.trim();
    const depth = parseInt(document.getElementById("depth").value);
    const max_pages = parseInt(document.getElementById("max_pages").value);
    const fetcher = document.getElementById("fetcher").value;
    const min_file_size = parseInt(document.getElementById("min_file_size").value) * 1024;
    const formats = Array.from(document.querySelectorAll('input[name="format"]:checked')).map(cb => cb.value);
    syncProxyHiddenField();
    const proxy = document.getElementById("proxy").value.trim();

    // UI reset
    btnStart.disabled = true; btnStop.disabled = false;
    statusBadge.textContent = "Batch đang chạy"; statusBadge.className = "badge badge-active";
    logsViewer.innerHTML = ""; liveImageGrid.innerHTML = ""; liveImageCount = 0;
    liveGalleryCount.textContent = "0 ảnh";
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
        card.innerHTML = `<span class="batch-card-idx">${i+1}</span><span class="batch-card-domain">${domain}</span><span class="batch-card-status">Đang chờ</span>`;
        cardsEl.appendChild(card);
    });
    lucide.createIcons();

    addLog(`Bắt đầu batch crawl ${batchUrls.length} URL...`, "system");

    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    batchWs = new WebSocket(`${protocol}//${window.location.host}/api/ws/batch-crawl`);

    let completedCount = 0, batchSuccess = 0, batchFailed = 0;

    batchWs.onopen = () => {
        batchWs.send(JSON.stringify({ urls: batchUrls, output_dir, depth, max_pages, fetcher, min_file_size, allowed_formats: formats, proxy: proxy || null }));
    };

    batchWs.onmessage = (event) => {
        const msg = JSON.parse(event.data);
        const { event: evt, data: d } = msg;

        switch (evt) {
            case "batch_start":
                addLog(`Batch bắt đầu: ${d.total_urls} URL, ${d.domain_groups} nhóm domain`, "system");
                break;
            case "batch_url_start": {
                const card = document.getElementById(`batch-card-${d.index}`);
                if (card) { card.className = "batch-url-card status-running"; card.querySelector(".batch-card-status").textContent = "Đang crawl..."; }
                document.getElementById("batch-stat-running").textContent = parseInt(document.getElementById("batch-stat-running").textContent) + 1;
                addLog(`[${d.index+1}/${batchUrls.length}] Bắt đầu: ${d.url}`, "info");
                break;
            }
            case "page_fetched":
                statPages.textContent = parseInt(statPages.textContent) + 1;
                statFound.textContent = parseInt(statFound.textContent) + (d.images || 0);
                break;
            case "image_downloaded": {
                statDownloaded.textContent = parseInt(statDownloaded.textContent) + 1;
                liveImageCount++; liveGalleryCount.textContent = `${liveImageCount} ảnh`;
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
                if (card) { card.className = "batch-url-card status-success"; card.querySelector(".batch-card-status").textContent = `✓ ${d.result.images_downloaded} ảnh`; }
                document.getElementById("batch-stat-success").textContent = batchSuccess;
                document.getElementById("batch-stat-running").textContent = Math.max(0, parseInt(document.getElementById("batch-stat-running").textContent) - 1);
                updateBatchProgress(completedCount, batchUrls.length);
                addLog(`✓ [${d.index+1}] Xong: ${d.url} — ${d.result.images_downloaded} ảnh`, "success");
                break;
            }
            case "batch_url_error": {
                completedCount++; batchFailed++;
                const card = document.getElementById(`batch-card-${d.index}`);
                if (card) { card.className = "batch-url-card status-error"; card.querySelector(".batch-card-status").textContent = `✗ Lỗi`; }
                document.getElementById("batch-stat-failed").textContent = batchFailed;
                document.getElementById("batch-stat-running").textContent = Math.max(0, parseInt(document.getElementById("batch-stat-running").textContent) - 1);
                updateBatchProgress(completedCount, batchUrls.length);
                addLog(`✗ [${d.index+1}] Lỗi: ${d.url} — ${d.error}`, "error");
                break;
            }
            case "batch_done":
                addLog(`Batch hoàn thành: ${d.success} thành công, ${d.failed} lỗi`, "system");
                closeBatchWs();
                break;
            case "error":
                addLog(`Lỗi: ${d.message}`, "error");
                closeBatchWs();
                break;
        }
    };

    batchWs.onerror = () => { addLog("Lỗi kết nối WebSocket.", "error"); closeBatchWs(); };
    batchWs.onclose = () => { closeBatchWs(); };
}

function updateBatchProgress(done, total) {
    const pct = total > 0 ? Math.round((done / total) * 100) : 0;
    document.getElementById("batch-progress-bar").style.width = `${pct}%`;
    document.getElementById("batch-progress-counter").textContent = `${done}/${total}`;
}

function closeBatchWs() {
    if (batchWs) { try { batchWs.close(); } catch(e) {} batchWs = null; }
    btnStart.disabled = false; btnStop.disabled = true;
    statusBadge.textContent = "Đang dừng"; statusBadge.className = "badge badge-inactive";
}

// Override stop button for batch mode too
btnStop.addEventListener("click", () => {
    if (batchWs) { addLog("Đang dừng batch...", "warn"); batchWs.close(); }
});
