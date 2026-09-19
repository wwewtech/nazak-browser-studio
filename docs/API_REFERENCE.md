# 🌐 Nazak Browser Studio — REST API & Swagger Reference

> **API Server URL**: `http://127.0.0.1:8899`
> **Interactive Swagger UI**: [`http://127.0.0.1:8899/docs`](http://127.0.0.1:8899/docs) (or [`http://127.0.0.1:8899/swagger`](http://127.0.0.1:8899/swagger))
> **ReDoc Alternative UI**: [`http://127.0.0.1:8899/redoc`](http://127.0.0.1:8899/redoc)
> **OpenAPI Specification JSON**: [`http://127.0.0.1:8899/openapi.json`](http://127.0.0.1:8899/openapi.json)

---

## 📑 Table of Contents
1. [Interactive Swagger Documentation](#-interactive-swagger-documentation)
2. [Dolphin{anty} v1.0 Local Automation API (Playwright / Puppeteer / Selenium)](#-1-dolphinanty-v10-local-automation-api)
3. [Profile Management & Mass Farm Generation](#-2-profile-management-profiles)
4. [Batch Cookies Import & Export (Cookies)](#-3-batch-cookies-import--export-cookies)
5. [Action Synchronizer & Win32 Window Grid](#-4-action-synchronizer)
6. [Scenario Builder & Auto Warm-up (Scenarios)](#-5-scenario-builder--auto-warm-up-scenarios)
7. [Proxy Diagnostics & Mobile IP Rotation (Proxies)](#-6-proxies--mobile-ip-rotation-proxies)
8. [YouTube Shorts Stealth Autoposter & FFmpeg](#-7-youtube-shorts-autoposter--ffmpeg)
9. [System Telemetry & WebSocket Events](#-8-system-telemetry--websocket-events)
10. [Secrets Storage — User-Selectable Encryption Mode](#-9-secrets-storage--user-selectable-encryption-mode)

---

## ⚡ Interactive Swagger Documentation

When Nazak Browser Studio is running in server mode (`python -m nazak.main --mode web` or while the desktop app is running), the built-in FastAPI server automatically deploys an interactive UI:

- **Swagger UI**: Open your browser at `http://127.0.0.1:8899/docs` (or `http://127.0.0.1:8899/swagger`). Here you can test every endpoint in real time, inspect JSON request/response schemas, and click the **"Try it out"** button.
- **ReDoc**: Available at `http://127.0.0.1:8899/redoc` for comfortably reading the technical specification in a three-panel format.

---

## 🤖 1. Dolphin{anty} v1.0 Local Automation API

Implements a compatible subset of the Dolphin{anty} v1.0 local automation protocol (start/stop/status + profile listing). Your existing **Playwright**, **Puppeteer**, **Selenium**, or **BAS** scripts can connect to warmed-up profiles; full protocol parity is not claimed.

### Endpoints:

#### `GET /v1.0/browser_profiles`
Retrieves the list of all profiles, their statuses, attached proxies, and tags.
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

#### `GET /v1.0/browser_profiles/{id}/start`
Launches the Chromium profile with allocation of a dynamic CDP port and generation of a WebSocket URL for automation connections.
- **Query Parameters**:
  - `custom_url` (optional, string) — initial URL to open.
  - `port` (optional, integer) — explicit CDP port (if not specified, a free port is allocated).
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

#### `GET /v1.0/browser_profiles/{id}/stop`
Stops a running profile.
- **Response `200 OK`**:
```json
{
  "success": true,
  "profile_id": "prof_01"
}
```

#### `GET /v1.0/browser_profiles/active`
List of all currently active profiles with their CDP WebSocket endpoints.
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

---

### 💡 Automation Script Connection Examples

#### 🐍 Python: Playwright (`connect_over_cdp`)
```python
import requests
from playwright.sync_api import sync_playwright

PROFILE_ID = "prof_01"
BASE_API = "http://127.0.0.1:8899"

# 1. Launch the browser via API
start_res = requests.get(f"{BASE_API}/v1.0/browser_profiles/{PROFILE_ID}/start").json()
if not start_res.get("success"):
    raise RuntimeError(f"Failed to launch profile: {start_res}")

ws_endpoint = start_res["automation"]["wsEndpoint"]
print(f"[+] Browser launched. Connecting via CDP: {ws_endpoint}")

# 2. Connect Playwright to the launched isolated profile
with sync_playwright() as p:
    browser = p.chromium.connect_over_cdp(ws_endpoint)
    context = browser.contexts[0]
    page = context.pages[0] if context.pages else context.new_page()

    # All cookies, hardware fingerprints, proxy, and session are already active!
    page.goto("https://www.google.com")
    print(f"[+] Page title: {page.title()}")

    # 3. Close the session after work is done
    browser.close()
    requests.get(f"{BASE_API}/v1.0/browser_profiles/{PROFILE_ID}/stop")
```

#### 📦 Node.js / JavaScript: Puppeteer (`puppeteer.connect`)
```javascript
const axios = require('axios');
const puppeteer = require('puppeteer-core');

async function main() {
    const profileId = 'prof_01';

    // 1. Launch the profile
    const res = await axios.get(`http://127.0.0.1:8899/v1.0/browser_profiles/${profileId}/start`);
    const wsEndpoint = res.data.automation.wsEndpoint;

    // 2. Connect to CDP
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
# Launch
curl -X GET "http://127.0.0.1:8899/v1.0/browser_profiles/prof_01/start"

# Stop
curl -X GET "http://127.0.0.1:8899/v1.0/browser_profiles/prof_01/stop"
```

---

## 👤 2. Profile Management (Profiles)

| Method | Path | Description |
| :--- | :--- | :--- |
| `GET` | `/api/profiles` | Get the list of all profiles with their real status and PID |
| `POST` | `/api/profiles` | Create a new isolated profile |
| `GET` | `/api/profiles/{id}` | Get the detailed profile configuration |
| `PUT` | `/api/profiles/{id}` | Update hardware/proxy/account parameters |
| `DELETE` | `/api/profiles/{id}` | Delete the profile and clean up session files on disk |
| `POST` | `/api/profiles/{id}/clone` | Clone the profile with random re-issuing of hardware fingerprints |
| `POST` | `/api/profiles/{id}/launch` | Launch the browser (normal or with CDP) |
| `POST` | `/api/profiles/{id}/stop` | Stop the browser process |
| `POST` | `/api/profiles/batch-launch` | Batch launch an array `["prof_01", "prof_02"]` |
| `POST` | `/api/profiles/batch-stop` | Batch stop an array `["prof_01", "prof_02"]` |
| `POST` | `/api/profiles/mass-generate` | Mass-create a farm (1–100+ profiles) with Round-Robin proxies |
| `POST` | `/api/profiles/bulk-import` | Bulk-create profiles from proxy strings |
| `GET` | `/api/profiles/{id}/bundle/export` | Export a profile to a portable `.nazak` zip archive |
| `POST` | `/api/profiles/{id}/clear-cache` | Clear browser cache, shaders, and profile temporary files |

---

## 🍪 3. Batch Cookies Import & Export (Cookies)

#### `POST /api/cookies/bulk-import`
Universal batch import of cookies for multiple profiles at once.
- **Supported `cookies_data` formats**:
  1. Blocks with profile delimiters (`=== Profile 01 ===`, `--- Name ---`, `[Profile 01]`).
  2. A JSON map `{ "Profile_A": [...], "Profile_B": [...] }`.
  3. A single JSON array or Netscape format.
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
Exports all session cookies to a structured JSON or a downloadable `.zip` archive.
- **Request Body**:
```json
{
  "profile_ids": ["prof_01", "prof_02"],
  "format": "zip"
}
```

---

## ⚡ 4. Action Synchronizer

Replicates actions from the main window (**Master**) to any child windows (**Workers**) with anti-fraud protection (sub-pixel jitter and time delays) and automatic window tiling on a grid.

| Method | Path | Description |
| :--- | :--- | :--- |
| `POST` | `/api/synchronizer/start` | Start a Master → Workers synchronization session |
| `POST` | `/api/synchronizer/stop` | Stop the current synchronization |
| `GET` | `/api/synchronizer/status` | Get the synchronization session status |
| `POST` | `/api/synchronizer/tile-windows` | 1-click alignment of all browser windows on a 2x2, 3x3, 4x4 grid |
| `POST` | `/api/synchronizer/navigate` | Instantly navigate all workers to a URL in sync |

---

## 🔥 5. Scenario Builder & Auto Warm-up (Scenarios)

#### `GET /api/scenarios`
Retrieves the list of built-in scenarios:
- `scen_ecom_trust` (alias: `ecommerce_trust_booster`) — Google SERP warm-up, e-commerce sites, clicks on products.
- `scen_youtube_viewer` (alias: `youtube_shorts_warmup`) — Shorts feed viewing, full video watches, recommendation boosting.
- `scen_crypto_web3` (alias: `crypto_web3_farming`) — Browsing CoinMarketCap, DeFi protocols, crypto news.
- `scen_finance_banking` (alias: `finance_high_cpc_banking`) — Collecting top-price-tier trust cookies (banks, loans).

#### `POST /api/scenarios/run`
Runs a scenario across a pool of profiles with concurrency control (`max_concurrency`).
- **Request Body**:
```json
{
  "scenario_id": "scen_ecom_trust",
  "profile_ids": ["prof_01", "prof_02", "prof_03"],
  "max_concurrency": 3
}
```

---

## 📱 6. Proxies & Mobile IP Rotation (Proxies)

#### `POST /api/profiles/{id}/rotate-proxy`
Triggers the rotation URL of a dynamic mobile proxy (changing the external IP address via the provider's link).
- **Response `200 OK`**:
```json
{
  "success": true,
  "status_code": 200,
  "response": "{\"status\":\"IP_CHANGED\",\"new_ip\":\"188.130.155.40\"}"
}
```

#### `POST /api/profiles/{id}/check`
4-stage diagnostics: TCP Latency, Geolocation / ISP, Google Reachability Suite, storage/Data Isolation check.

---

## 🎬 7. YouTube Shorts Autoposter & FFmpeg

| Method | Path | Description |
| :--- | :--- | :--- |
| `GET` | `/api/autopost/status` | Autoposting queue status and FFmpeg availability |
| `POST` | `/api/autopost/uniquify` | Deep uniquification of the source video for each profile |
| `POST` | `/api/autopost/launch` | Start an autonomous upload queue with Bézier curves |
| `POST` | `/api/autopost/cancel` | Instant cancellation of the upload queue |
| `POST` | `/api/autopost/preview-spintax` | Preview of randomized titles and descriptions |

---

## 📡 8. System Telemetry & WebSocket Events

### `GET /api/system/info`
Returns information about the host, the path to Google Chrome, the number of running browsers, and data paths.

### `WebSocket /ws/events`
Real-time event streaming:
```json
// Example: browser status changed
{
  "event": "profile_status_change",
  "data": {
    "profile_id": "prof_01",
    "status": "running",
    "pid": 14200
  }
}
```
Other event types:
- `profile_created`, `profile_updated`, `profile_deleted`
- `profile_health_update`
- `cookies_bulk_imported`
- `synchronizer_started`, `synchronizer_stopped`
- `autopost_progress`, `autopost_complete`
- `secrets_mode_changed`

---

## 🔐 9. Secrets Storage — User-Selectable Encryption Mode

> **The choice is always yours.** Nazak never decides how your credentials are
> stored — you do. The selected mode applies to newly imported accounts and is
> persisted across restarts. **The passphrase itself is never written to disk.**

### Modes

| Mode | Description | Trade-off |
| :--- | :--- | :--- |
| `plain` *(default)* | Credentials stored as readable text | No protection; full transparency |
| `dpapi` | Windows DPAPI encryption, bound to your Windows user account | Windows-only; data unreadable for other OS users |
| `passphrase` | Fernet (AES128-CBC + HMAC, PBKDF2 480k iterations) with your own passphrase | Lost passphrase = lost data (by design, no backdoor) |

### `GET /api/security/secrets-mode`

```json
{
  "mode": "passphrase",
  "available_modes": ["plain", "dpapi", "passphrase"],
  "platform": "nt",
  "notes": "The user selects the mode. ..."
}
```

### `POST /api/security/secrets-mode`

Switch the active mode (applies to new imports; existing envelopes stay decodable):

```json
// Request
{ "mode": "passphrase", "passphrase": "your-own-secret" }

// Response
{ "success": true, "mode": "passphrase", "message": "Secrets mode switched to 'passphrase'. ..." }
```

- `dpapi` requested on a non-Windows host → `400 Bad Request`.
- Unknown mode → `400 Bad Request`.
- `passphrase` mode without a passphrase: new values are stored as plaintext
  and a warning is logged (your workflow is never blocked).

### Masking in profile responses

`GET /api/profiles` and `GET /api/profiles/{id}` always return **masked** secret
fields (`abc...xyz`), never plaintext, regardless of the active mode:

```json
{ "account_password": "pw1...6789", "totp_secret": "TOP...CRET" }
```

- Legacy plaintext notes stay fully readable/maskable — nothing breaks.
- If decryption is impossible (e.g. no passphrase), the field shows
  `<encrypted: unavailable passphrase>`.
- The same choice is available in the desktop GUI:
  **Settings → Secrets Storage (your choice)**.

### WebSocket event

```json
{ "event": "secrets_mode_changed", "data": { "mode": "passphrase" } }
```
