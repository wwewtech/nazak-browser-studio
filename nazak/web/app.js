// Nazak Browser Studio Client v1.3
let profiles = [];
let systemInfo = {};
let ws = null;
let currentDiagProfileId = null;
let selectedProfileIds = new Set();

const UA_PRESETS = {
  win11_chrome133: "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
  win10_chrome132: "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36",
  mac_chrome133: "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36"
};

document.addEventListener("DOMContentLoaded", () => {
  fetchSystemInfo();
  fetchProfiles();
  initWebSocket();
  window.addEventListener("click", (e) => {
    if (!e.target.matches(".dropdown-toggle") && !e.target.closest(".dropdown")) {
      document.querySelectorAll(".dropdown-menu").forEach(el => el.classList.remove("show"));
    }
  });
});

function showToast(msg, type = "info") {
  const container = document.getElementById("toast-container");
  const toast = document.createElement("div");
  toast.className = "toast";
  let icon = type === "success" ? "✓" : (type === "error" ? "✕" : "ℹ");
  toast.innerHTML = `<span style="color: ${type === 'success' ? 'var(--accent-emerald)' : (type === 'error' ? 'var(--accent-rose)' : 'var(--accent-amber)')}; font-weight: 700;">${icon}</span> <span>${escapeHtml(msg)}</span>`;
  container.appendChild(toast);
  setTimeout(() => {
    toast.style.opacity = "0";
    toast.style.transform = "translateY(10px)";
    toast.style.transition = "all 0.3s ease";
    setTimeout(() => toast.remove(), 300);
  }, 4000);
}

function initWebSocket() {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  const wsUrl = `${protocol}//${window.location.host}/ws/events`;
  try {
    ws = new WebSocket(wsUrl);
    ws.onopen = () => { document.getElementById("ws-status-text").innerText = "WS: Connected"; };
    ws.onmessage = (event) => {
      try { handleWsEvent(JSON.parse(event.data)); } catch (e) {}
    };
    ws.onclose = () => {
      document.getElementById("ws-status-text").innerText = "WS: Reconnecting...";
      setTimeout(initWebSocket, 2500);
    };
  } catch (e) {
    setTimeout(initWebSocket, 3000);
  }
}

function handleWsEvent(msg) {
  if (msg.event === "profile_status_change") {
    const { profile_id, status, pid, error } = msg.data;
    const prof = profiles.find(p => p.id === profile_id);
    if (prof) {
      prof.status = status;
      prof.pid = pid || null;
      renderProfiles();
      updateMetrics();
      if (status === "running") showToast(`Profile "${prof.name}" started (PID: ${pid})`, "success");
      if (status === "stopped") showToast(`Profile "${prof.name}" stopped`, "info");
      if (status === "error") showToast(`Launch error: ${error}`, "error");
    }
  } else if (msg.event === "profile_health_update") {
    const { profile_id, health } = msg.data;
    const prof = profiles.find(p => p.id === profile_id);
    if (prof) {
      prof.last_health_check = health;
      renderProfiles();
      updateMetrics();
      if (currentDiagProfileId === profile_id) renderDiagModalContent(prof, health);
    }
  } else if (msg.event === "profile_created" || msg.event === "profile_updated" || msg.event === "profile_deleted" || msg.event === "profiles_bulk_created") {
    fetchProfiles();
  } else if (msg.event === "autopost_job_update" || msg.event === "autopost_batch_started" || msg.event === "autopost_batch_finished") {
    updateAutopostStatusView();
  }
}

async function fetchSystemInfo() {
  try {
    const res = await fetch("/api/system/info");
    systemInfo = await res.json();
    const statusPill = document.getElementById("chrome-status-pill");
    const statusText = document.getElementById("chrome-status-text");
    const dot = document.getElementById("chrome-dot");
    if (systemInfo.chrome_installed) {
      dot.className = "status-dot online";
      statusText.innerText = "Chrome: Detected";
      statusPill.title = systemInfo.chrome_executable;
    } else {
      dot.className = "status-dot";
      dot.style.backgroundColor = "var(--accent-rose)";
      statusText.innerText = "Chrome: Not found";
    }
  } catch (e) {}
}

async function fetchProfiles() {
  try {
    const res = await fetch("/api/profiles");
    profiles = await res.json();
    renderProfiles();
    updateMetrics();
    updateBulkBar();
  } catch (e) {}
}

function updateMetrics() {
  document.getElementById("metric-total-profiles").innerText = profiles.length;
  const running = profiles.filter(p => p.status === "running").length;
  document.getElementById("metric-active-browsers").innerText = running;
  const withCheck = profiles.filter(p => p.last_health_check);
  const live = withCheck.filter(p => p.last_health_check.status === "healthy" || p.last_health_check.status === "degraded").length;
  document.getElementById("metric-live-proxies").innerText = withCheck.length > 0 ? `${live}/${profiles.length}` : "-";
  const googleOk = withCheck.filter(p => p.last_health_check.google && p.last_health_check.google.all_ok).length;
  document.getElementById("metric-google-ready").innerText = withCheck.length > 0 ? `${googleOk}/${profiles.length}` : "-";
}

function toggleSelect(id, checked) {
  if (checked) selectedProfileIds.add(id);
  else selectedProfileIds.delete(id);
  updateBulkBar();
}

function toggleSelectAll(checked) {
  if (checked) profiles.forEach(p => selectedProfileIds.add(p.id));
  else selectedProfileIds.clear();
  renderProfiles();
  updateBulkBar();
}

function clearSelection() {
  selectedProfileIds.clear();
  const selectAll = document.getElementById("select-all-checkbox");
  if (selectAll) selectAll.checked = false;
  renderProfiles();
  updateBulkBar();
}

function updateBulkBar() {
  const bar = document.getElementById("bulk-bar");
  const countText = document.getElementById("bulk-count-text");
  const size = selectedProfileIds.size;
  if (size > 0) {
    bar.style.display = "flex";
    countText.innerText = `Selected: ${size} of ${profiles.length} profiles`;
  } else {
    bar.style.display = "none";
  }
}

async function batchLaunchSelected() {
  const ids = Array.from(selectedProfileIds);
  if (ids.length === 0) return;
  showToast(`Starting ${ids.length} profiles...`, "info");
  try {
    await fetch("/api/profiles/batch-launch", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ profile_ids: ids })
    });
    fetchProfiles();
  } catch (e) {
    showToast(`Error: ${e.message}`, "error");
  }
}

async function batchStopSelected() {
  const ids = Array.from(selectedProfileIds);
  if (ids.length === 0) return;
  showToast(`Stopping ${ids.length} profiles...`, "info");
  try {
    await fetch("/api/profiles/batch-stop", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ profile_ids: ids })
    });
    fetchProfiles();
  } catch (e) {
    showToast(`Error: ${e.message}`, "error");
  }
}

async function batchCheckSelected() {
  const ids = Array.from(selectedProfileIds);
  if (ids.length === 0) return;
  showToast(`Running diagnostics for ${ids.length} profiles...`, "info");
  for (const id of ids) {
    try { await fetch(`/api/profiles/${id}/check`, { method: "POST" }); } catch (e) {}
  }
  fetchProfiles();
  showToast(`Diagnostics complete!`, "success");
}

function renderProfiles() {
  const grid = document.getElementById("profiles-grid");
  const search = document.getElementById("search-input").value.toLowerCase().trim();
  const groupFilter = document.getElementById("group-filter").value;
  const statusFilter = document.getElementById("status-filter").value;
  const filtered = profiles.filter(p => {
    if (groupFilter !== "ALL" && p.group !== groupFilter) return false;
    if (statusFilter !== "ALL" && p.status.toUpperCase() !== statusFilter) return false;
    if (search) {
      const matchName = p.name.toLowerCase().includes(search);
      const matchProxy = p.proxy.raw && p.proxy.raw.toLowerCase().includes(search);
      const matchNotes = p.google.notes && p.google.notes.toLowerCase().includes(search);
      const matchTags = p.google.tags && p.google.tags.some(t => t.toLowerCase().includes(search));
      if (!matchName && !matchProxy && !matchNotes && !matchTags) return false;
    }
    return true;
  });
  if (filtered.length === 0) {
    grid.innerHTML = `<div style="grid-column: 1 / -1; padding: 48px; text-align: center; color: var(--text-muted); background: var(--bg-surface); border-radius: 8px; border: 1px dashed var(--border-subtle);"><p style="font-size: 16px; margin-bottom: 8px;">No profiles found</p><span style="font-size: 12px;">Try adjusting your search or creating a new profile.</span></div>`;
    return;
  }
  grid.innerHTML = filtered.map(p => {
    const isRunning = p.status === "running";
    const statusClass = isRunning ? "badge-running" : (p.status === "error" ? "badge-error" : (p.status === "starting" ? "badge-checking" : "badge-stopped"));
    const statusLabel = isRunning ? "● Running" : (p.status === "error" ? "✕ Error" : (p.status === "starting" ? "▲ Starting..." : "○ Stopped"));
    const isSelected = selectedProfileIds.has(p.id);
    const proxyType = p.proxy.type ? p.proxy.type.toUpperCase() : "DIRECT";
    let proxyText = "Direct connection";
    if (p.proxy.type !== "direct" && p.proxy.host) proxyText = `${proxyType}://${p.proxy.host}:${p.proxy.port}`;
    const hc = p.last_health_check;
    const pingText = hc && hc.ping_ms ? `${hc.ping_ms} ms` : null;
    const ipText = hc && hc.ip ? hc.ip : null;
    const geoText = hc && hc.country ? `${hc.country}${hc.city ? ", " + hc.city : ""}` : null;
    let gBadges = `<span class="health-badge unknown">G: ?</span><span class="health-badge unknown">Sign In: ?</span><span class="health-badge unknown">Ads: ?</span><span class="health-badge unknown">YT: ?</span>`;
    if (hc && hc.google) {
      gBadges = `<span class="health-badge ${hc.google.google_main ? "ok" : "fail"}">${hc.google.google_main ? "✓ Search" : "✕ Search"}</span><span class="health-badge ${hc.google.google_accounts ? "ok" : "fail"}">${hc.google.google_accounts ? "✓ Sign In" : "✕ Sign In"}</span><span class="health-badge ${hc.google.google_ads ? "ok" : "fail"}">${hc.google.google_ads ? "✓ Ads" : "✕ Ads"}</span><span class="health-badge ${hc.google.youtube ? "ok" : "fail"}">${hc.google.youtube ? "✓ YouTube" : "✕ YouTube"}</span>`;
    }
    return `
      <div class="profile-card ${isRunning ? "running" : ""}" id="card-${p.id}">
        <div class="card-header">
          <div class="profile-checkbox-row">
            <input type="checkbox" class="profile-checkbox" ${isSelected ? "checked" : ""} onchange="toggleSelect('${p.id}', this.checked)">
            <div class="profile-identity">
              <div class="profile-name-row">
                <span class="profile-name">${escapeHtml(p.name)}</span>
                <span class="group-tag">${escapeHtml(p.group || "General")}</span>
              </div>
              <div class="profile-notes">${escapeHtml(p.google.notes || (p.google.tags ? p.google.tags.join(", ") : ""))}</div>
            </div>
          </div>
          <span class="profile-status-badge ${statusClass}">${statusLabel}</span>
        </div>
        <div class="card-details-box">
          <div class="detail-row">
            <span class="detail-label">PROXY:</span>
            <span class="detail-value">
              <span>${escapeHtml(proxyText)}</span>
              ${pingText ? `<span class="latency-pill">${pingText}</span>` : ""}
            </span>
          </div>
          ${ipText ? `<div class="detail-row"><span class="detail-label">IP & GEO:</span><span class="detail-value" style="color: var(--accent-sky);">${escapeHtml(ipText)} ${geoText ? `(${escapeHtml(geoText)})` : ""}</span></div>` : ""}
          <div class="detail-row"><span class="detail-label">GOOGLE:</span><div class="google-health-row">${gBadges}</div></div>
          <div class="detail-row"><span class="detail-label">FINGERPRINT:</span><span class="detail-value" style="color: var(--accent-emerald);"><span>${p.fingerprint.hardware_concurrency} cores / ${p.fingerprint.device_memory} GB</span><span style="color: var(--text-muted);">| ${p.fingerprint.screen_width}x${p.fingerprint.screen_height}</span></span></div>
        </div>
        <div class="card-actions">
          <div class="launch-group">
            ${isRunning ? `<button class="btn btn-danger btn-sm" onclick="stopProfile('${p.id}')"><span>⏹ Stop</span></button>` : `<button class="btn btn-success btn-sm" onclick="launchProfile('${p.id}')"><span>🚀 Launch</span></button>`}
            <div class="dropdown">
              <button class="btn btn-secondary btn-sm dropdown-toggle" onclick="toggleDropdown('dropdown-${p.id}')"><span>⚡ Google ▾</span></button>
              <div class="dropdown-menu" id="dropdown-${p.id}">
                <div class="dropdown-item" onclick="launchProfile('${p.id}', 'https://accounts.google.com/ServiceLogin')">🔑 Google Sign In (Auth)</div>
                <div class="dropdown-item" onclick="launchProfile('${p.id}', 'https://ads.google.com')">📊 Google Ads Dashboard</div>
                <div class="dropdown-item" onclick="launchProfile('${p.id}', 'https://studio.youtube.com')">🎬 YouTube Studio</div>
                <div class="dropdown-item" onclick="launchProfile('${p.id}', 'https://www.google.com')">🔍 Google Search (Warmup)</div>
                <div class="dropdown-item" onclick="launchProfile('${p.id}', 'https://whoer.net')">🛡 Whoer.net (IP Test)</div>
                <div class="dropdown-item" onclick="launchProfile('${p.id}', 'https://browserleaks.com/ip')">🌐 BrowserLeaks IP</div>
              </div>
            </div>
            <button class="btn btn-warmup btn-sm" onclick="openWarmupModal('${p.id}')" title="Automatic warmup"><span>🔥 Warmup</span></button>
          </div>
          <div class="more-group">
            <button class="btn btn-secondary btn-sm" onclick="openDiagModal('${p.id}')" title="Diagnostics"><span>🔍</span></button>
            <button class="btn btn-secondary btn-sm" onclick="openCookieModal('${p.id}')" title="Cookies"><span>🍪</span></button>
            <button class="btn btn-secondary btn-sm" onclick="openEditProfileModal('${p.id}')" title="Settings"><span>⚙</span></button>
            <button class="btn btn-secondary btn-sm" onclick="cloneProfile('${p.id}')" title="Clone"><span>📋</span></button>
            <button class="btn btn-secondary btn-sm" onclick="clearCache('${p.id}')" title="Clear cache"><span>🧹</span></button>
            <button class="btn btn-secondary btn-sm" onclick="deleteProfile('${p.id}')" title="Delete" style="color: var(--accent-rose);"><span>🗑</span></button>
          </div>
        </div>
      </div>
    `;
  }).join("");
}

function toggleDropdown(id) {
  const el = document.getElementById(id);
  const isShown = el.classList.contains("show");
  document.querySelectorAll(".dropdown-menu").forEach(m => m.classList.remove("show"));
  if (!isShown) el.classList.add("show");
}

async function launchProfile(id, customUrl = null) {
  try {
    const prof = profiles.find(p => p.id === id);
    if (prof) { prof.status = "starting"; renderProfiles(); }
    const res = await fetch(`/api/profiles/${id}/launch`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ custom_url: customUrl })
    });
    const data = await res.json();
    if (!res.ok) {
      showToast(`Launch error: ${data.detail || "Unknown error"}`, "error");
      fetchProfiles();
    }
  } catch (e) {
    showToast(`Network error: ${e.message}`, "error");
  }
}

async function stopProfile(id) {
  try {
    const res = await fetch(`/api/profiles/${id}/stop`, { method: "POST" });
    if (!res.ok) {
      const data = await res.json();
      showToast(`Error: ${data.detail}`, "error");
    }
  } catch (e) {}
}

async function openDiagModal(id) {
  currentDiagProfileId = id;
  const prof = profiles.find(p => p.id === id);
  if (!prof) return;
  const modal = document.getElementById("diag-modal");
  document.getElementById("diag-modal-title").innerText = `🔍 Diagnostics: ${prof.name}`;
  modal.classList.add("open");
  renderDiagModalContent(prof, null, true);
  try {
    const res = await fetch(`/api/profiles/${id}/check`, { method: "POST" });
    const health = await res.json();
    renderDiagModalContent(prof, health, false);
  } catch (e) {
    document.getElementById("diag-modal-body").innerHTML = `<div class="diag-step fail"><span>Error: ${e.message}</span></div>`;
  }
}

function renderDiagModalContent(prof, health, isLoading = false) {
  const body = document.getElementById("diag-modal-body");
  if (isLoading) {
    body.innerHTML = `<div style="text-align: center; padding: 24px; color: var(--accent-amber); font-family: var(--font-mono);"><p style="font-size: 16px; margin-bottom: 8px;">⏳ Running full diagnostics...</p><span style="font-size: 12px; color: var(--text-muted);">Checking TCP latency, IP geolocation, Google/YouTube availability, and disk isolation</span></div>`;
    return;
  }
  if (!health) return;

  body.innerHTML = `
    <div style="display: flex; flex-direction: column; gap: 12px;">
      <div class="diag-step ${health.ping_ms !== null ? "success" : "fail"}"><span>[1] TCP Ping:</span><span style="font-weight: 700; color: ${health.ping_ms ? "var(--accent-emerald)" : "var(--accent-rose)"};">${health.ping_ms !== null ? `${health.ping_ms} ms` : "Timeout"}</span></div>
      <div class="diag-step ${health.ip ? "success" : "fail"}"><span>[2] Public IP:</span><span style="font-weight: 700; color: ${health.ip ? "var(--accent-sky)" : "var(--accent-rose)"};">${health.ip ? `${health.ip} (${health.country || "N/A"}, ${health.city || ""})` : "IP error"}</span></div>
      ${health.isp ? `<div class="diag-step success"><span>[3] ISP / ASN:</span><span>${escapeHtml(health.isp)} (${escapeHtml(health.asn || "")})</span></div>` : ""}
      <div class="diag-step ${health.google && health.google.google_main ? "success" : "fail"}"><span>[4] Google Search:</span><span style="color: ${health.google && health.google.google_main ? "var(--accent-emerald)" : "var(--accent-rose)"};">${health.google && health.google.google_main ? `✓ Available (${health.google.latencies_ms?.google_main || "-"} ms)` : "✕ Error"}</span></div>
      <div class="diag-step ${health.google && health.google.google_accounts ? "success" : "fail"}"><span>[5] Google Auth / Login:</span><span style="color: ${health.google && health.google.google_accounts ? "var(--accent-emerald)" : "var(--accent-rose)"};">${health.google && health.google.google_accounts ? `✓ Available (${health.google.latencies_ms?.google_accounts || "-"} ms)` : "✕ Error"}</span></div>
      <div class="diag-step ${health.google && health.google.google_ads ? "success" : "fail"}"><span>[6] Google Ads:</span><span style="color: ${health.google && health.google.google_ads ? "var(--accent-emerald)" : "var(--accent-rose)"};">${health.google && health.google.google_ads ? `✓ Available (${health.google.latencies_ms?.google_ads || "-"} ms)` : "✕ Error"}</span></div>
      <div class="diag-step ${health.google && health.google.youtube ? "success" : "fail"}"><span>[7] YouTube:</span><span style="color: ${health.google && health.google.youtube ? "var(--accent-emerald)" : "var(--accent-rose)"};">${health.google && health.google.youtube ? `✓ Available (${health.google.latencies_ms?.youtube || "-"} ms)` : "✕ Error"}</span></div>
      <div class="diag-step ${health.data_isolation_ok ? "success" : "fail"}"><span>[8] Data isolation:</span><span style="color: ${health.data_isolation_ok ? "var(--accent-emerald)" : "var(--accent-rose)"};">${health.data_isolation_ok ? "✓ Isolated" : "✕ Error"}</span></div>
      ${health.error_message ? `<div style="padding: 10px; background: var(--accent-rose-glow); border: 1px solid var(--accent-rose); border-radius: 6px; color: #fda4af; font-size: 12px;">⚠ ${escapeHtml(health.error_message)}</div>` : ""}
    </div>
  `;
}

function closeDiagModal() {
  document.getElementById("diag-modal").classList.remove("open");
  currentDiagProfileId = null;
}

function launchFromDiag() {
  if (currentDiagProfileId) {
    launchProfile(currentDiagProfileId);
    closeDiagModal();
  }
}

async function randomizeFingerprintInModal() {
  try {
    const res = await fetch("/api/profiles/randomize-fingerprint?os_type=windows", { method: "POST" });
    const fp = await res.json();
    document.getElementById("edit-user-agent").value = fp.user_agent;
    document.getElementById("edit-screen-res").value = `${fp.screen_width}x${fp.screen_height}`;
    document.getElementById("edit-language").value = fp.language;
    document.getElementById("edit-cores").value = fp.hardware_concurrency;
    document.getElementById("edit-ram").value = fp.device_memory;
    showToast("New random hardware fingerprint generated!", "success");
  } catch (e) {
    showToast("Generation failed", "error");
  }
}

function openCreateProfileModal() {
  document.getElementById("profile-modal-title").innerText = "Create a new profile";
  document.getElementById("edit-profile-id").value = "";
  document.getElementById("edit-name").value = `Profile ${profiles.length + 1}`;
  document.getElementById("edit-group").value = "Google Ads";
  document.getElementById("edit-proxy-raw").value = "";
  document.getElementById("edit-tags").value = "Google Ads, New";
  document.getElementById("edit-notes").value = "";
  document.getElementById("edit-google-target").value = "google_login";
  document.getElementById("edit-ua-preset").value = "win11_chrome133";
  document.getElementById("edit-user-agent").value = UA_PRESETS.win11_chrome133;
  document.getElementById("edit-screen-res").value = "1920x1080";
  document.getElementById("edit-language").value = "en-US,en;q=0.9";
  document.getElementById("edit-cores").value = "8";
  document.getElementById("edit-ram").value = "16";
  document.getElementById("proxy-test-result").innerText = "";
  document.getElementById("profile-modal").classList.add("open");
}

function openEditProfileModal(id) {
  const prof = profiles.find(p => p.id === id);
  if (!prof) return;
  document.getElementById("profile-modal-title").innerText = `Edit: ${prof.name}`;
  document.getElementById("edit-profile-id").value = prof.id;
  document.getElementById("edit-name").value = prof.name;
  document.getElementById("edit-group").value = prof.group || "";
  document.getElementById("edit-proxy-raw").value = prof.proxy.raw || "";
  document.getElementById("edit-tags").value = prof.google.tags ? prof.google.tags.join(", ") : "";
  document.getElementById("edit-notes").value = prof.google.notes || "";
  document.getElementById("edit-google-target").value = prof.google.auto_open_page || "google_login";
  document.getElementById("edit-user-agent").value = prof.fingerprint.user_agent;
  document.getElementById("edit-screen-res").value = `${prof.fingerprint.screen_width}x${prof.fingerprint.screen_height}`;
  document.getElementById("edit-language").value = prof.fingerprint.language;
  document.getElementById("edit-cores").value = prof.fingerprint.hardware_concurrency;
  document.getElementById("edit-ram").value = prof.fingerprint.device_memory;
  document.getElementById("proxy-test-result").innerText = "";
  document.getElementById("profile-modal").classList.add("open");
}

function closeProfileModal() {
  document.getElementById("profile-modal").classList.remove("open");
}

function applyUaPreset() {
  const val = document.getElementById("edit-ua-preset").value;
  if (UA_PRESETS[val]) {
    document.getElementById("edit-user-agent").value = UA_PRESETS[val];
  }
}

async function testModalProxy() {
  const rawProxy = document.getElementById("edit-proxy-raw").value.trim();
  const resSpan = document.getElementById("proxy-test-result");
  resSpan.style.color = "var(--accent-amber)";
  resSpan.innerText = "⏳ Testing connection...";
  try {
    const res = await fetch("/api/profiles/test-proxy", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ raw_proxy: rawProxy })
    });
    const health = await res.json();
    if (health.status === "healthy" || health.status === "degraded") {
      resSpan.style.color = "var(--accent-emerald)";
      resSpan.innerText = `✓ Proxy is online! IP: ${health.ip} (${health.country || ""}) | Ping: ${health.ping_ms || 0}ms | Google: OK`;
    } else {
      resSpan.style.color = "var(--accent-rose)";
      resSpan.innerText = `✕ Error: ${health.error_message || "Connection failed"}`;
    }
  } catch (e) {
    resSpan.style.color = "var(--accent-rose)";
    resSpan.innerText = `✕ Error: ${e.message}`;
  }
}

async function saveProfileModal() {
  const id = document.getElementById("edit-profile-id").value;
  const name = document.getElementById("edit-name").value.trim();
  const group = document.getElementById("edit-group").value.trim();
  const rawProxy = document.getElementById("edit-proxy-raw").value.trim();
  const tags = document.getElementById("edit-tags").value.split(",").map(t => t.trim()).filter(Boolean);
  const notes = document.getElementById("edit-notes").value.trim();
  const target = document.getElementById("edit-google-target").value;
  const ua = document.getElementById("edit-user-agent").value.trim();
  const resParts = document.getElementById("edit-screen-res").value.split("x");
  const width = parseInt(resParts[0]) || 1920;
  const height = parseInt(resParts[1]) || 1080;
  const lang = document.getElementById("edit-language").value.trim();
  const cores = parseInt(document.getElementById("edit-cores").value) || 8;
  const ram = parseInt(document.getElementById("edit-ram").value) || 16;
  let existing = id ? profiles.find(p => p.id === id) : null;
  const payload = {
    id: id || undefined,
    name: name || "Profile",
    group: group || "General",
    proxy: {
      raw: rawProxy,
      type: rawProxy ? (rawProxy.includes("socks5") ? "socks5" : (rawProxy.includes("socks4") ? "socks4" : "http")) : "direct"
    },
    fingerprint: {
      user_agent: ua,
      screen_width: width,
      screen_height: height,
      color_depth: 24,
      device_memory: ram,
      hardware_concurrency: cores,
      platform: ua.includes("Macintosh") ? "MacIntel" : "Win32",
      language: lang,
      timezone: existing ? existing.fingerprint.timezone : "America/New_York",
      webgl_vendor: "Google Inc. (NVIDIA)",
      webgl_renderer: "ANGLE (NVIDIA, NVIDIA GeForce RTX 3070 Direct3D11 vs_5_0 ps_5_0, D3D11)",
      canvas_noise: true,
      audio_noise: true,
      webrtc_policy: "disable_non_proxied_udp"
    },
    google: { auto_open_page: target, tags: tags, notes: notes }
  };
  try {
    const url = id ? `/api/profiles/${id}` : "/api/profiles";
    const method = id ? "PUT" : "POST";
    const res = await fetch(url, {
      method: method,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    if (res.ok) {
      closeProfileModal();
      fetchProfiles();
      showToast("Profile saved!", "success");
    } else {
      const err = await res.json();
      showToast(`Error: ${err.detail || "Unknown error"}`, "error");
    }
  } catch (e) {
    showToast(`Network error: ${e.message}`, "error");
  }
}

function openBulkImportModal() {
  document.getElementById("bulk-proxy-text").value = "";
  document.getElementById("bulk-import-modal").classList.add("open");
}

function closeBulkImportModal() {
  document.getElementById("bulk-import-modal").classList.remove("open");
}

async function submitBulkImport() {
  const text = document.getElementById("bulk-proxy-text").value.trim();
  const group = document.getElementById("bulk-group").value.trim() || "Google Ads";
  const target = document.getElementById("bulk-target-page").value;
  if (!text) { alert("Enter at least one proxy."); return; }
  try {
    const res = await fetch("/api/profiles/bulk-import", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ proxy_lines: text, group: group, target_page: target })
    });
    const data = await res.json();
    closeBulkImportModal();
    fetchProfiles();
    showToast(`Created ${data.created_count} new profiles!`, "success");
  } catch (e) {
    showToast(`Error: ${e.message}`, "error");
  }
}

function openWarmupModal(id) {
  const prof = profiles.find(p => p.id === id);
  if (!prof) return;
  document.getElementById("warmup-profile-id").value = id;
  document.getElementById("warmup-modal-title").innerText = `🔥 Automatic warmup: ${prof.name}`;
  document.getElementById("warmup-modal").classList.add("open");
  previewWarmupPlan();
}

function closeWarmupModal() {
  document.getElementById("warmup-modal").classList.remove("open");
}

async function previewWarmupPlan() {
  const id = document.getElementById("warmup-profile-id").value;
  const niche = document.getElementById("warmup-niche").value;
  const steps = parseInt(document.getElementById("warmup-steps").value) || 5;
  const previewBox = document.getElementById("warmup-plan-preview");
  previewBox.innerText = "Generating plan...";
  try {
    const res = await fetch(`/api/profiles/${id}/warmup/plan`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ niche: niche, steps_count: steps })
    });
    const data = await res.json();
    previewBox.innerHTML = data.search_queries.map((q, idx) => `<div>${idx + 1}. Search: <span style="color: var(--accent-amber);">${escapeHtml(q)}</span></div>`).join("");
  } catch (e) {
    previewBox.innerText = "Failed to load.";
  }
}

async function startWarmup() {
  const id = document.getElementById("warmup-profile-id").value;
  const niche = document.getElementById("warmup-niche").value;
  const steps = parseInt(document.getElementById("warmup-steps").value) || 5;
  try {
    const res = await fetch(`/api/profiles/${id}/warmup/launch`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ niche: niche, steps_count: steps })
    });
    const data = await res.json();
    closeWarmupModal();
    fetchProfiles();
    showToast(`Warmup started (${data.plan.steps_count} queries)!`, "success");
  } catch (e) {
    showToast(`Error: ${e.message}`, "error");
  }
}

function openCookieModal(id) {
  const prof = profiles.find(p => p.id === id);
  if (!prof) return;
  document.getElementById("cookie-profile-id").value = id;
  document.getElementById("cookie-modal-title").innerText = `🍪 Cookie Manager: ${prof.name}`;
  document.getElementById("cookie-input-text").value = "";
  document.getElementById("cookie-modal").classList.add("open");
}

function closeCookieModal() {
  document.getElementById("cookie-modal").classList.remove("open");
}

async function submitCookiesImport() {
  const id = document.getElementById("cookie-profile-id").value;
  const text = document.getElementById("cookie-input-text").value.trim();
  if (!text) { alert("Paste cookies in JSON or Netscape format."); return; }
  try {
    const res = await fetch(`/api/profiles/${id}/cookies/import`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ cookies_data: text })
    });
    const data = await res.json();
    closeCookieModal();
    showToast(`Imported ${data.parsed_cookies_count} cookies!`, "success");
  } catch (e) {
    showToast(`Import error: ${e.message}`, "error");
  }
}

async function cloneProfile(id) {
  try {
    const res = await fetch(`/api/profiles/${id}/clone`, { method: "POST" });
    if (res.ok) { fetchProfiles(); showToast("Profile cloned!", "success"); }
  } catch (e) {}
}

async function deleteProfile(id) {
  if (!confirm("Delete this profile and all its isolated data?")) return;
  try {
    const res = await fetch(`/api/profiles/${id}`, { method: "DELETE" });
    if (res.ok) {
      selectedProfileIds.delete(id);
      fetchProfiles();
      showToast("Profile deleted", "info");
    }
  } catch (e) {}
}

async function clearCache(id) {
  try {
    const res = await fetch(`/api/profiles/${id}/clear-cache`, { method: "POST" });
    if (res.ok) { showToast("Browser cache cleared!", "success"); }
    else { const d = await res.json(); showToast(`Error: ${d.detail}`, "error"); }
  } catch (e) {}
}

async function checkAllProfiles() {
  const btn = document.getElementById("btn-check-all");
  btn.disabled = true;
  btn.innerHTML = "<span>⏳ Checking all proxies...</span>";
  showToast("Checking all proxies...", "info");
  try {
    await fetch("/api/profiles/check-all", { method: "POST" });
    fetchProfiles();
    showToast("All proxy checks complete!", "success");
  } catch (e) {
    showToast(`Error: ${e.message}`, "error");
  } finally {
    btn.disabled = false;
    btn.innerHTML = "<span>🔍 Check all proxies</span>";
  }
}

function escapeHtml(text) {
  if (!text) return "";
  return String(text).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#039;");
}

// === YouTube Shorts Autoposting Engine ===
let autopostSelectedProfiles = new Set();

function openAutopostModal() {
  document.getElementById("autopost-modal").classList.add("open");
  renderAutopostProfiles();
  updateAutopostStatusView();
}

function closeAutopostModal() {
  document.getElementById("autopost-modal").classList.remove("open");
}

function renderAutopostProfiles() {
  const container = document.getElementById("autopost-profiles-selector");
  if (autopostSelectedProfiles.size === 0) {
    profiles.forEach(p => autopostSelectedProfiles.add(p.id));
  }

  container.innerHTML = profiles.map(p => {
    const isChecked = autopostSelectedProfiles.has(p.id);
    const proxyStr = p.proxy.raw ? (p.proxy.host ? `${p.proxy.host}:${p.proxy.port}` : "Direct") : "Direct";
    return `
      <label style="display: flex; align-items: center; gap: 8px; font-size: 12px; cursor: pointer; padding: 4px 6px; background: var(--bg-surface); border-radius: 4px; border: 1px solid var(--border-subtle);">
        <input type="checkbox" ${isChecked ? "checked" : ""} onchange="toggleAutopostProfile('${p.id}', this.checked)">
        <span style="font-weight: 600; color: var(--text-primary);">${escapeHtml(p.name)}</span>
        <span style="color: var(--text-muted); font-size: 10px; margin-left: auto;">${escapeHtml(proxyStr)}</span>
      </label>
    `;
  }).join("");
}

function toggleAutopostProfile(id, checked) {
  if (checked) autopostSelectedProfiles.add(id);
  else autopostSelectedProfiles.delete(id);
}

function selectAutopostAll(checked) {
  if (checked) profiles.forEach(p => autopostSelectedProfiles.add(p.id));
  else autopostSelectedProfiles.clear();
  renderAutopostProfiles();
}

async function previewAutopostSpintax() {
  const title = document.getElementById("autopost-title-template").value;
  const desc = document.getElementById("autopost-desc-template").value;
  const tg = document.getElementById("autopost-tg").value;
  const platform = document.getElementById("autopost-platform").value;
  const ids = Array.from(autopostSelectedProfiles);

  if (ids.length === 0) { alert("Select at least one profile"); return; }

  try {
    const res = await fetch("/api/autopost/preview-spintax", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ profile_ids: ids, platform: platform, title_template: title, description_template: desc, tg_channel: tg })
    });
    const data = await res.json();
    const box = document.getElementById("autopost-spintax-preview-box");
    const list = document.getElementById("autopost-spintax-preview-list");
    box.style.display = "block";
    list.innerHTML = data.samples.map(s => `
      <div style="margin-bottom: 8px; padding-bottom: 6px; border-bottom: 1px dashed var(--border-subtle);">
        <div style="color: var(--accent-sky); font-weight: 700;">[${escapeHtml(s.profile_name)}]</div>
        <div><strong>Title:</strong> <span style="color: var(--accent-amber);">${escapeHtml(s.title)}</span></div>
        <div style="color: var(--text-muted); font-size: 10px; white-space: pre-wrap; margin-top: 2px;">${escapeHtml(s.description)}</div>
      </div>
    `).join("");
  } catch (e) {
    showToast(`Preview error: ${e.message}`, "error");
  }
}

async function startAutopostBatch() {
  const videoPath = document.getElementById("autopost-video-path").value.trim();
  const title = document.getElementById("autopost-title-template").value;
  const desc = document.getElementById("autopost-desc-template").value;
  const tg = document.getElementById("autopost-tg").value;
  const platform = document.getElementById("autopost-platform").value;
  const ids = Array.from(autopostSelectedProfiles);

  if (ids.length === 0) { alert("Select at least one profile"); return; }

  try {
    const res = await fetch("/api/autopost/launch", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        profile_ids: ids,
        source_video_path: videoPath,
        platform: platform,
        title_template: title,
        description_template: desc,
        tg_channel: tg,
        delay_seconds: 10
      })
    });
    const data = await res.json();
    if (res.ok) {
      showToast("Auto-posting queue started in the background!", "success");
      document.getElementById("btn-cancel-autopost").style.display = "inline-block";
      updateAutopostStatusView();
    } else {
      showToast(`Error: ${data.detail || "Failed to start"}`, "error");
    }
  } catch (e) {
    showToast(`Network error: ${e.message}`, "error");
  }
}

async function cancelAutopost() {
  try {
    await fetch("/api/autopost/cancel", { method: "POST" });
    showToast("Auto-posting stop requested", "info");
    document.getElementById("btn-cancel-autopost").style.display = "none";
    updateAutopostStatusView();
  } catch (e) {}
}

async function updateAutopostStatusView() {
  try {
    const res = await fetch("/api/autopost/status");
    const data = await res.json();
    const table = document.getElementById("autopost-jobs-table");
    const cancelBtn = document.getElementById("btn-cancel-autopost");

    if (cancelBtn) {
      cancelBtn.style.display = data.is_running ? "inline-block" : "none";
    }

    if (!data.jobs || data.jobs.length === 0) {
      table.innerHTML = `<div style="color: var(--text-muted); text-align: center;">Queue ready to start (FFmpeg: ${data.ffmpeg_available ? '✓ Detected' : '✕ Not found'})</div>`;
      return;
    }

    table.innerHTML = data.jobs.map(j => {
      let statusColor = "var(--text-muted)";
      let icon = "○";
      if (j.status === "published") { statusColor = "var(--accent-emerald)"; icon = "✓"; }
      if (j.status === "uploading") { statusColor = "var(--accent-amber)"; icon = "⏳"; }
      if (j.status === "uniqueizing") { statusColor = "var(--accent-sky)"; icon = "✨"; }
      if (j.status === "failed") { statusColor = "var(--accent-rose)"; icon = "✕"; }
      const platformName = (j.platform === "instagram_reels") ? "Reels" : "Shorts";

      return `
        <div style="display: flex; justify-content: space-between; align-items: center; padding: 6px 0; border-bottom: 1px solid var(--border-subtle);">
          <div>
            <strong style="color: var(--text-primary);">${escapeHtml(j.profile_name)}:</strong>
            <span style="color: ${statusColor}; margin-left: 6px;">${icon} ${escapeHtml(j.progress_message)}</span>
            ${j.title ? `<div style="font-size: 10px; color: var(--text-muted); margin-top: 2px;">Title: ${escapeHtml(j.title)}</div>` : ''}
          </div>
          <div>
            ${j.video_url ? `<a href="${escapeHtml(j.video_url)}" target="_blank" style="color: var(--accent-emerald); text-decoration: underline; font-size: 11px;">Open ${platformName} ↗</a>` : ''}
          </div>
        </div>
      `;
    }).join("");
  } catch (e) {}
}
