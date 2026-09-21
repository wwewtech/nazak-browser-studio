# 🌐 Nazak Browser Studio — REST API & Swagger Reference

> **API Server URL**: `http://127.0.0.1:8899`  
> **Interactive Swagger UI**: [`http://127.0.0.1:8899/docs`](http://127.0.0.1:8899/docs) (or [`http://127.0.0.1:8899/swagger`](http://127.0.0.1:8899/swagger))  
> **ReDoc Alternative UI**: [`http://127.0.0.1:8899/redoc`](http://127.0.0.1:8899/redoc)  
> **OpenAPI Specification JSON**: [`http://127.0.0.1:8899/openapi.json`](http://127.0.0.1:8899/openapi.json)  

---

## 📑 Table of Contents
1. [Interactive Swagger Documentation](#-interactive-swagger-documentation)
2. [Dolphin{anty} v1.0 & Nazak v1 Local Automation API](#-1-dolphinanty-v10--nazak-v1-local-automation-api)
3. [Profile Management & Mass Farm Generation](#-2-profile-management-profiles)
4. [Cookie Management — Bulk & Single Profile](#-3-cookie-management-cookies)
5. [Action Synchronizer & Win32 Window Grid](#-4-action-synchronizer-synchronizer)
6. [Scenario Builder & Organic Warm-up](#-5-scenario-builder--organic-warm-up-scenarios)
7. [Proxy Diagnostics & Mobile IP Rotation](#-6-proxy-diagnostics--mobile-ip-rotation-proxies)
8. [YouTube Shorts & Instagram Reels Autoposter & FFmpeg](#-7-youtube-shorts--instagram-reels-autoposter--ffmpeg)
9. [System Diagnostics & WebSocket Events](#-8-system-diagnostics--websocket-events)
10. [Secrets Storage — User-Selectable Encryption Mode](#-9-secrets-storage--user-selectable-encryption-mode)
11. [Hardware Isolation & Manifest V3 Stealth Architecture](#-10-hardware-isolation--manifest-v3-stealth-architecture)

---

## ⚡ Interactive Swagger Documentation

When Nazak Browser Studio is running in server mode (`python -m nazak.main --mode web` or while the desktop GUI is running), the built-in FastAPI server automatically serves the interactive API documentation:

- **Swagger UI**: Open your browser at `http://127.0.0.1:8899/docs` (or `http://127.0.0.1:8899/swagger`). Test any endpoint in real time, inspect JSON schemas, and execute queries directly from the interface.
- **ReDoc**: Available at `http://127.0.0.1:8899/redoc` for structured technical reference in three-panel format.
- **OpenAPI Schema**: Raw schema available at `http://127.0.0.1:8899/openapi.json`.

---

## 🤖 1. Dolphin{anty} v1.0 & Nazak v1 Local Automation API

Provides a compatible subset of the Dolphin{anty} v1.0 local automation protocol as well as native Nazak v1 routes. External automation scripts in **Playwright**, **Puppeteer**, **Selenium**, or **BAS** connect directly over CDP to running profiles with isolated hardware fingerprints and proxy tunnels.

### Endpoints:

#### `GET /v1.0/browser_profiles`
Retrieves the list of all profiles with their live execution statuses, attached proxies, CDP endpoints, and tags.
- **Response `200 OK`**:
```json
{
  "success": true,
  "data": [
    {
      "id": "prof_01",
      "name": "01 - Google Ads USA (High-Tier Desktop RTX 4090)",
      "status": "running",
      "proxy": {
        "type": "http",
        "host": "198.51.100.24",
        "port": 8080,
        "username": "ads_user",
        "password": "secret_password"
      },
      "automation": {
        "port": 9222,
        "ws_endpoint": "ws://127.0.0.1:9222/devtools/browser/d92f98...",
        "wsEndpoint": "ws://127.0.0.1:9222/devtools/browser/d92f98...",
        "http_endpoint": "http://127.0.0.1:9222"
      },
      "tags": ["Google Ads", "USA", "RTX4090"]
    }
  ]
}
```

#### `GET /v1.0/browser_profiles/{id}/start` & `POST /api/v1/profiles/{id}/start`
Launches the browser profile, allocates a dynamic CDP port via `DevToolsActivePort` handshake, and returns the WebSocket endpoint.
- **Query Parameters**:
  - `custom_url` (optional, string) — initial URL to open.
  - `port` (optional, integer) — explicit CDP port (if omitted, a dynamic free port is allocated).
- **Response `200 OK`**:
```json
{
  "success": true,
  "automation": {
    "port": 9222,
    "wsEndpoint": "ws://127.0.0.1:9222/devtools/browser/f8d0a92b-8a71-4a1e-8e49-0123456789ab"
  },
  "pid": 14200,
  "profile_id": "prof_01"
}
```

#### `GET /v1.0/browser_profiles/{id}/stop` & `POST /api/v1/profiles/{id}/stop`
Terminates the running browser process and updates the profile status to `stopped`.
- **Response `200 OK`**:
```json
{
  "success": true,
  "profile_id": "prof_01"
}
```

#### `GET /v1.0/browser_profiles/active`
Lists all currently active browser profiles and their active CDP WebSocket endpoints.
- **Response `200 OK`**:
```json
{
  "success": true,
  "active_count": 1,
  "profiles": [
    {
      "profile_id": "prof_01",
      "name": "01 - Google Ads USA",
      "pid": 14200,
      "automation": {
        "port": 9222,
        "ws_endpoint": "ws://127.0.0.1:9222/devtools/browser/f8d0a..."
      }
    }
  ]
}
```

#### `GET /api/v1/profiles/{id}/cdp`
Inspects the active CDP port and WebSocket URL for a running profile without re-launching.
- **Response `200 OK`**:
```json
{
  "success": true,
  "cdp": {
    "port": 9222,
    "ws_endpoint": "ws://127.0.0.1:9222/devtools/browser/f8d0a..."
  }
}
```

---

### 💡 Automation Connection Examples

#### 🐍 Python: Playwright (`connect_over_cdp`)
```python
import requests
from playwright.sync_api import sync_playwright

PROFILE_ID = "prof_01"
BASE_API = "http://127.0.0.1:8899"

# 1. Launch profile via Nazak Local API
start_res = requests.get(f"{BASE_API}/v1.0/browser_profiles/{PROFILE_ID}/start").json()
if not start_res.get("success"):
    raise RuntimeError(f"Failed to launch profile: {start_res}")

ws_endpoint = start_res["automation"]["wsEndpoint"]
print(f"[+] Browser launched. Connecting via CDP: {ws_endpoint}")

# 2. Connect Playwright over CDP
with sync_playwright() as p:
    browser = p.chromium.connect_over_cdp(ws_endpoint)
    context = browser.contexts[0]
    page = context.pages[0] if context.pages else context.new_page()

    # Operates with isolated hardware fingerprint, proxy, and cookies
    page.goto("https://www.google.com")
    print(f"[+] Page title: {page.title()}")

    # 3. Clean up
    browser.close()
    requests.get(f"{BASE_API}/v1.0/browser_profiles/{PROFILE_ID}/stop")
```

#### 📦 Node.js: Puppeteer (`puppeteer.connect`)
```javascript
const axios = require('axios');
const puppeteer = require('puppeteer-core');

async function main() {
    const profileId = 'prof_01';

    // 1. Launch profile
    const res = await axios.get(`http://127.0.0.1:8899/v1.0/browser_profiles/${profileId}/start`);
    const wsEndpoint = res.data.automation.wsEndpoint;

    // 2. Connect Puppeteer
    const browser = await puppeteer.connect({ browserWSEndpoint: wsEndpoint });
    const pages = await browser.pages();
    const page = pages.length > 0 ? pages[0] : await browser.newPage();

    await page.goto('https://api.ipify.org?format=json');
    const content = await page.evaluate(() => document.body.innerText);
    console.log(`[+] Real Exit IP via Proxy: ${content}`);

    await browser.disconnect();
    await axios.get(`http://127.0.0.1:8899/v1.0/browser_profiles/${profileId}/stop`);
}

main().catch(console.error);
```

#### 💻 cURL
```bash
# Launch with CDP
curl -X GET "http://127.0.0.1:8899/v1.0/browser_profiles/prof_01/start"

# Query active CDP endpoint
curl -X GET "http://127.0.0.1:8899/api/v1/profiles/prof_01/cdp"

# Stop
curl -X GET "http://127.0.0.1:8899/v1.0/browser_profiles/prof_01/stop"
```

---

## 👤 2. Profile Management (Profiles)

| Method | Path | Description |
| :--- | :--- | :--- |
| `GET` | `/api/profiles` | List all profiles with live statuses, PIDs, and masked secrets |
| `POST` | `/api/profiles` | Create a new isolated profile |
| `GET` | `/api/profiles/{id}` | Get complete profile configuration |
| `PUT` | `/api/profiles/{id}` | Update hardware/proxy/account parameters |
| `DELETE` | `/api/profiles/{id}` | Safely delete profile, unlinking symlinks and purging data |
| `POST` | `/api/profiles/{id}/clone` | Clone profile with guaranteed distinct hardware seeds |
| `POST` | `/api/profiles/{id}/launch` | Launch browser profile (normal or CDP mode) |
| `POST` | `/api/profiles/{id}/stop` | Stop running browser profile |
| `POST` | `/api/profiles/batch-launch` | Launch an array of profile IDs simultaneously |
| `POST` | `/api/profiles/batch-stop` | Stop an array of profile IDs simultaneously |
| `POST` | `/api/profiles/randomize-fingerprint` | Generate an isolated randomized hardware fingerprint (`?os_type=windows`) |
| `POST` | `/api/profiles/bulk-import` | Bulk import profiles from raw proxy strings |
| `POST` | `/api/profiles/mass-generate` | 1-Click mass profile generator (1–100+ farm) with Round-Robin proxies |
| `GET` | `/api/profiles/{id}/bundle/export` | Export complete profile as portable `.nazak` zip archive |
| `POST` | `/api/profiles/{id}/clear-cache` | Purge browser cache and temporary shader data |

---

## 🍪 3. Cookie Management (Cookies)

Nazak provides universal multi-format cookie handling supporting single-profile operations and farm-wide bulk archives.

### Bulk Endpoints:

#### `POST /api/cookies/bulk-import`
Imports cookies across multiple profiles simultaneously. Auto-detects delimiters (`=== Profile 01 ===`, `--- Name ---`, `[Profile Name]`), JSON dictionary maps `{ "Profile_1": [...] }`, or standard JSON arrays.
- **Request Body**:
```json
{
  "cookies_data": "=== Account Alpha ===\n[{\"name\":\"SID\",\"value\":\"secret\",\"domain\":\".google.com\",\"path\":\"/\"}]\n\n=== Account Beta ===\n.google.com\tTRUE\t/\tTRUE\t0\tHSID\tsecret2\n",
  "auto_create_missing": true,
  "group": "Farm Batch 1"
}
```
- **Response**:
```json
{
  "success": true,
  "results": {
    "matched": 2,
    "created": 0,
    "failed": 0
  }
}
```

#### `POST /api/cookies/bulk-export`
Exports all session cookies into a structured JSON map or a downloadable `.zip` archive containing per-profile cookie files.
- **Request Body**:
```json
{
  "profile_ids": ["prof_01", "prof_02"],
  "format": "zip"
}
```

### Per-Profile Endpoints:

#### `GET /api/profiles/{id}/cookies/export`
Exports cookies for a single profile.
- **Query Parameter**: `format` (`json` or `netscape`, default: `json`).
- **Response `200 OK`**:
```json
{
  "format": "json",
  "cookies": [ ... ],
  "cookies_count": 24
}
```

#### `POST /api/profiles/{id}/cookies/import`
Imports raw JSON or Netscape format cookies into the specified profile.
- **Request Body**:
```json
{
  "cookies_data": "[{\"name\": \"SID\", \"value\": \"...\", \"domain\": \".google.com\"}]"
}
```

---

## ⚡ 4. Action Synchronizer (Synchronizer)

Replicates user motorics in real time from a Master profile to multiple Worker profiles, with sub-pixel humanizing jitter, randomized micro-delays (20–80 ms), and automatic Win32 window tiling.

| Method | Path | Description |
| :--- | :--- | :--- |
| `POST` | `/api/synchronizer/start` | Start Master → Workers synchronization session |
| `POST` | `/api/synchronizer/stop` | Stop active synchronizer session |
| `GET` | `/api/synchronizer/status` | Query active synchronizer state and connected workers |
| `POST` | `/api/synchronizer/tile-windows` | Arrange browser windows into a 2×2, 3×3, or 4×4 monitor grid |
| `POST` | `/api/synchronizer/navigate` | Broadcast URL navigation to all worker instances simultaneously |

---

## 🔥 5. Scenario Builder & Organic Warm-up (Scenarios)

Automates human-like browsing patterns to accumulate cookies and build account trust scores before high-value activity.

### Endpoints:

#### `GET /api/scenarios`
Returns the built-in scenario templates:
- `scen_ecom_trust` (alias: `ecommerce_trust_booster`) — Google SERP queries, marketplace visits, dwell time, cookie consent acceptance.
- `scen_youtube_viewer` (alias: `youtube_shorts_warmup`) — Shorts feed browsing, dwell time, organic watch duration.
- `scen_crypto_web3` (alias: `crypto_web3_farming`) — CoinMarketCap, DeFi protocol navigation, crypto whitepaper reading.
- `scen_finance_banking` (alias: `finance_high_cpc_banking`) — Accumulating Tier-1 financial / high-CPC banking cookies.

#### `POST /api/scenarios/run`
Executes a scenario across selected profiles with concurrency management.
- **Request Body**:
```json
{
  "scenario_id": "scen_ecom_trust",
  "profile_ids": ["prof_01", "prof_02", "prof_03"],
  "max_concurrency": 3
}
```

#### `POST /api/profiles/{id}/warmup/plan`
Generates a deterministic organic query plan tailored to a specific niche.
- **Request Body**:
```json
{
  "niche": "ecommerce",
  "steps_count": 5
}
```

#### `POST /api/profiles/{id}/warmup/launch`
Launches the profile directly into the initial organic query step of the warmup plan.

---

## 📱 6. Proxy Diagnostics & Mobile IP Rotation (Proxies)

| Method | Path | Description |
| :--- | :--- | :--- |
| `POST` | `/api/profiles/{id}/rotate-proxy` | Trigger provider rotation URL for dynamic mobile proxy |
| `POST` | `/api/profiles/{id}/check` | Perform 5-stage health check and auto-align geolocation/timezone |
| `POST` | `/api/profiles/check-all` | Batch run health checks across all configured profiles |
| `POST` | `/api/profiles/test-proxy` | Test standalone raw proxy string without profile binding |

#### 5-Stage Diagnostics Pipeline:
1. **TCP Connection Latency**: Ping time to host/port.
2. **External IP & ISP Identification**: Resolves exit IP, organization, and country.
3. **Geolocation & Timezone Alignment**: Extracts latitude, longitude, and timezone name.
4. **Google Reachability**: Checks connectivity and challenge detection against Google endpoints.
5. **Data Isolation**: Verifies that user data directory is isolated and free of port conflicts.

---

## 🎬 7. YouTube Shorts & Instagram Reels Autoposter & FFmpeg

| Method | Path | Description |
| :--- | :--- | :--- |
| `GET` | `/api/autopost/status` | Queue progress and FFmpeg binary availability |
| `POST` | `/api/autopost/uniquify` | Deep video uniquification with FFmpeg |
| `POST` | `/api/autopost/launch` | Start upload queue using Bezier motorics |
| `POST` | `/api/autopost/cancel` | Cancel queue and terminate active upload instances |
| `POST` | `/api/autopost/preview-spintax` | Preview generated titles/descriptions from spintax template |

---

## 📡 8. System Diagnostics & WebSocket Events

### `GET /api/system/info`
Host diagnostics: OS platform, CPU concurrency, memory stats, Chrome binary path, active profile count, data directory paths.

### `WebSocket /ws/events`
Real-time streaming channel for UI synchronization and telemetry:
- `profile_status_change` (`{ profile_id, status, pid }`)
- `profile_health_update` (`{ profile_id, health }`)
- `profiles_bulk_created` (`{ count }`)
- `cookies_bulk_imported`
- `synchronizer_started`, `synchronizer_stopped`
- `autopost_progress`, `autopost_complete`
- `secrets_mode_changed` (`{ mode }`)

---

## 🔐 9. Secrets Storage — User-Selectable Encryption Mode

> **User Choice Principle**: Nazak never forces a storage mechanism. The user selects the encryption mode for credentials (passwords, TOTP seeds). The passphrase is **never written to disk** and lives only in process memory.

### Supported Modes:

| Mode | Encryption Primitive | Key Derivation | Storage Format | Trade-off |
| :--- | :--- | :--- | :--- | :--- |
| `plain` *(default)* | None | None | Plaintext | Full transparency; no encryption |
| `dpapi` | Windows DPAPI | OS User Master Key | `nzk1:dpapi:...` | User-scoped; Windows only |
| `passphrase` | Fernet (AES-128-CBC + HMAC) | PBKDF2-HMAC-SHA256 (600,000 iterations) | `nzk1:passphrase:...` | Platform-independent; lost passphrase = unrecoverable data |

### Endpoints:

#### `GET /api/security/secrets-mode`
Inspects current mode, available modes, and platform suitability.

#### `POST /api/security/secrets-mode`
Switches active mode and re-encrypts all existing profile credentials atomically:
```json
{
  "mode": "passphrase",
  "passphrase": "my-secure-master-password"
}
```

### Masking Guarantee:
In all API endpoints (`GET /api/profiles`, `GET /api/profiles/{id}`), sensitive values (`account_password`, `totp_secret`) are masked (`ab...yz`) before transmission.

---

## 🛡️ 10. Hardware Isolation & Manifest V3 Stealth Architecture

### Chrome Manifest V3 Migration:
- **`manifest_version: 3`**: Compatible with modern Chromium deprecation rules.
- **Service Worker Architecture**: Uses `background.service_worker` (`background.js`) instead of persistent background scripts.
- **Declarative Proxy Authentication**: Uses `webRequestAuthProvider` permission with `chrome.webRequest.onAuthRequired.addListener(..., ["asyncBlocking"])`.
- **`MAIN` World Execution**: Stealth scripts inject at `document_start` inside the DOM's main execution context.

### Fingerprint Spoofing Fidelity:
- **`navigator.webdriver`**: Defined via prototype getter `get: () => false` with standard descriptor semantics, eliminating prototype deletion flags.
- **DOM Sub-pixel Jitter**: `Element.prototype.getBoundingClientRect` introduces deterministic sub-pixel offsets to defeat font and layout fingerprinting.
- **Canvas 2D Noise**: Linear Congruential Generator (LCG) perturbs all 4 RGBA channels with prime step 17, and synchronizes `HTMLCanvasElement.prototype.toDataURL`.
- **AudioContext Noise**: Uniformly distributes sample jitter across the full `AudioBuffer` spectrum.
- **CDP DevToolsActivePort Handshake**: Dynamically resolves bound port and ephemeral GUID, eliminating race conditions and stale socket fallbacks.
