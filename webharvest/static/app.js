// Initialize Lucide Icons
document.addEventListener("DOMContentLoaded", () => {
    lucide.createIcons();
    loadHistory();
    initProxyPanel();
});

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
