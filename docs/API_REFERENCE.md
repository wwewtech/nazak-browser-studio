# 🌐 Nazak Browser Studio — REST API & Swagger Reference

> **API Server URL**: `http://127.0.0.1:8899`  
> **Interactive Swagger UI**: [`http://127.0.0.1:8899/docs`](http://127.0.0.1:8899/docs) (or [`http://127.0.0.1:8899/swagger`](http://127.0.0.1:8899/swagger))  
> **ReDoc Alternative UI**: [`http://127.0.0.1:8899/redoc`](http://127.0.0.1:8899/redoc)  
> **OpenAPI Specification JSON**: [`http://127.0.0.1:8899/openapi.json`](http://127.0.0.1:8899/openapi.json)  
>
> **Access policy (local-only API)**: every non-static request must carry a `Host` of `localhost` / `127.0.0.1` and, when present, an `Origin` on one of the configured local ports (`8899`, `3000`, plus the port passed with `--port`); anything else is answered with `403`. Cross-site requests are additionally rejected when the browser marks them `Sec-Fetch-Site: cross-site` (this closes blind CSRF against the state-changing `GET` endpoints of the Dolphin-parity subset). CORS reflects exactly those ports with credentials allowed - never an arbitrary port. `/ws/events` applies the same check to the WebSocket `Origin` header. `/docs`, `/redoc` and `/openapi.json` sit behind the same `Host` check (only `/static` is exempt). Set the environment variable `NAZAK_API_TOKEN` to additionally require `X-API-Key: <token>` on `/api/*` and `/v1.0/*` calls (off by default for loopback; the local web UI does not send it). **Binding to a non-loopback host now requires the token**: `--host 0.0.0.0` without `NAZAK_API_TOKEN` refuses to start (`enforce_exposure_policy`), because any client can otherwise send `Host: 127.0.0.1` and pass the guard.
>
> **Prefer the terminal?** The CLI (`python -m nazak.cli ...`) covers every API group with 1:1 parity — see the [CLI reference](CLI_REFERENCE.md). With `--server http://127.0.0.1:8899` the same commands run through this API.

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
11. [Hardware Isolation & Manifest V3 Stealth Architecture](#-10-hardware-isolation--manifest-v3-stealth-architecture) — plus the operator-facing [Anti-Detect Guide](ANTIDETECT_GUIDE.md) (limits & applicability)
12. [Code Map — Where Each API Area Lives (P0 layout)](#-code-map--where-each-api-area-lives-p0-layout)
13. [Profile Storage Backends — JSON (default) & SQLite (opt-in)](#-profile-storage-backends--json-default--sqlite-opt-in)
14. [Operations & Hardening (P1)](#-operations--hardening-p1)

---

## 🗂 Code Map — Where Each API Area Lives (P0 layout)

`nazak/api/server.py` is now a thin composition root (singletons, guard,
`app`, router mounting, WebSocket). It re-exports every name the old
1792-line monolith exposed, so `from nazak.api.server import ...` and
`patch("nazak.api.server.profile_manager")` keep working unchanged.

| Area | Router module | Schemas | Notes |
|---|---|---|---|
| System + secrets-mode | `nazak/api/routers/system.py` | `SecretsModeRequest` | `GET /api/system/info`, `GET/POST /api/security/secrets-mode` |
| Profiles (CRUD, launch/stop, clone, bundles) | `nazak/api/routers/profiles.py` | `LaunchRequest`, `BulkImportRequest`, `MassGenerateRequest` | batch endpoints mutate via `ProfileManager` |
| Dolphin v1.0 + CDP + batch launch/stop | `nazak/api/routers/automation.py` | `BatchActionRequest` | `launch_with_cdp` returns `automation: {port, wsEndpoint}` |
| Proxy check + rotation | `nazak/api/routers/proxies.py` | `ProxyTestRequest` | rotation fetch is SSRF-pinned (see `security.py`) |
| Cookies | `nazak/api/routers/cookies.py` | `CookieImportRequest`, `BulkCookie*Request` | ZIP export via `cookie_manager` |
| Scenarios & warmup | `nazak/api/routers/warmup.py` | `WarmupRequest`, `ScenarioRunRequest` | `SCENARIO_ALIASES` live in the router |
| Synchronizer | `nazak/api/routers/synchronizer.py` | `SynchronizerStartRequest`, `SynchronizerNavigateRequest`, `WindowTileRequest` | |
| Autoposter | `nazak/api/routers/autopost.py` | `AutopostBatchRequest`, `UniquifyRequest` | `asyncio.to_thread` for ffmpeg |

Shared pieces:

- `nazak/api/schemas.py` — all request bodies with audit bounds (count
  `1..200`, delays `0..3600`, `cols 1..8`, id lists ≤ 500, …). Bounds are
  load-bearing: single calls cannot stall the server.
- `nazak/api/security.py` — local-only `Host`/`Origin`/`Sec-Fetch-Site`
  guard, `NAZAK_API_TOKEN` policy (`enforce_exposure_policy`,
  `X-API-Key`), CSP + security headers, `validate_pid`, proxy/notes
  masking, `resolve_media_source`, SSRF-pinned rotation fetch.
- `nazak/api/realtime.py` — WebSocket `ConnectionManager` (`ws_manager`)
  + `on_process_state_change` broadcast.
- `nazak/api/deps.py` — lazy accessors (`pm()`, `bl()`, …) so routers
  always see the *current* `nazak.api.server` singletons (tests replace
  them per-test).

The GUI background jobs behind these endpoints (`workers.py`) run through
a single `TaskBridge` (`nazak/gui/task_bridge.py`): one `QThread` at a time
(busy → `RuntimeError`), cooperative `cancel()`, Qt signals
(`progress`/`finished`/`error`/`cancelled`), headless inline fallback for
tests. Business logic lives in Qt-free callables in `nazak/gui/tasks.py`
(`check_single_proxy`, `check_all_proxies`, `rotate_proxy`,
`run_warmup_scenario`, `run_autopost_batch`). Since v1.15.1 every cancel
path delivers its completion signal (`batch_finished_signal` /
`finished_signal`), so the views never wait for a run that was cancelled,
and `run_autopost_batch` carries a per-profile `finally`-sweep: the browser
the loop launched is always stopped, on the happy path and on any
exception.

---

## 💾 Profile Storage Backends — JSON (default) & SQLite (opt-in)

`ProfileManager` (`nazak/core/profile_manager.py`) is a facade over the
`nazak.core.profiles` package and keeps the exact public API the test-suite
relies on (`profiles` dict, `_save_lock`, `_merge_*`, `MAX_BUNDLE_*`,
`save_profiles()`, …). On-disk `profiles.json` format is unchanged
(a bare list of `BrowserProfile` dicts).

| Piece | Module | Role |
|---|---|---|
| Store contract | `profiles/store_json.py` (`ProfileBackend`) | `load_all()` / `save_all()` |
| JSON backend | `profiles/store_json.py` (`JsonProfileBackend`) | atomic write (tmp + rename, Windows retries), corrupt-file `.bak`, rotating `.bak.N` (5), persisted delete-tombstones (`profiles.json.tombstones`), `mark_seen_empty_store` (a delete-all is never reseeded with the demo presets) |
| SQLite backend | `profiles/store_sqlite.py` (`SqliteProfileBackend`) | `profiles.db` (WAL), `save_one`/`delete_one` upserts, shared `meta` tombstones, `VACUUM`, one-shot JSON→SQLite migration |
| Business logic | `profiles/service.py` (`ProfileService`) | CRUD, clone (fresh fingerprints/seeds), mass-generate (clamped to 200), batch cookies, bundles, reencrypt; `update()` refuses ids with a live tombstone (a stale snapshot cannot resurrect a deleted profile) |
| Bundles | `profiles/bundles.py` | `.nazak` export/import with zip-slip + zip-bomb guards |
| Disk files | `profiles/files.py` | cookies, cache purge, history seeding, sizes, `validate_id` |
| Merge rules | `profiles/merge.py` | masked-secret round-trip, proxy/fingerprint/google partial-update merges |
| Constants | `profiles/constants.py` | `MAX_MASS_GENERATE_COUNT=200`, bundle bounds, `MASK="***"` |
| Defaults | `profiles/presets.py` | the 10 seed profiles (seeded only on a genuine first run — never over a deliberate delete-all) |
| Backend select | `backend_for()` in `store_sqlite.py` | `NAZAK_PROFILE_STORE=json` (default) / `sqlite` (opt-in) |

### `NAZAK_PROFILE_STORE`

- `json` (default) — current behaviour, full backward compatibility.
- `sqlite` (opt-in) — `profiles.db` next to `profiles.json` (WAL mode).
  First open migrates every valid row from `profiles.json` in one
  transaction and keeps the JSON as `profiles.pre-sqlite.<ts>.bak`
  (never deleted). Updates use single-row upserts (`save_one`) instead
  of rewriting the whole file; deletes use `delete_one`. Corrupt JSON no
  longer resets the fleet when SQLite already has data.
- Rollback: unset the variable (or set `json`) — the JSON file stays in
  place and is used again on next start.

```powershell
$env:NAZAK_PROFILE_STORE="sqlite"; python -m nazak.main --mode web
$env:NAZAK_PROFILE_STORE="sqlite"; python -m nazak.cli profile list --json
```

GUI `TaskBridge` note: Qt workers that touch profiles (`AutopostBatchWorker`,
`WarmupScenarioWorker`, proxy checkers) execute `tasks.*` callables through
one owned `QThread`; headless/test runs execute the same callables inline.

---

## 🛡 Operations & Hardening (P1)

### Dependency policy

`pyproject.toml` `[project.dependencies]` is the canonical runtime list;
`requirements.txt` is what the Docker image installs. `tests/test_p1_platform_hardening.py`
parses both and fails if a package exists in only one of them, so the two files cannot
drift apart.

CI runs a `security-audit` job on every push/PR:

- `pip-audit -r requirements.txt --desc on` — prints every advisory affecting the declared
  requirement set. It is advisory-only (the step does not fail the build), so a newly
  published transitive CVE cannot block unrelated pull requests.
- `bandit -c pyproject.toml -r nazak -ll` — static analysis at **medium severity and above**,
  and it *does* fail the build. The `[tool.bandit]` skips are explicit and documented:
  asserts (internal invariants), `subprocess` usage (launching Chrome/ffmpeg is the product
  feature), best-effort cleanup `try/except`, and `"password"` literals that are field names
  rather than secrets.

### Import purity

`nazak/config.py` no longer creates directories at import time. `ensure_data_dirs()` is
idempotent and is called by the real entry points: `nazak/main.py`, the API composition root
(`nazak/api/server.py`), the CLI helpers (`nazak/cli_cmds/common.py`) and the GUI launcher.
A test spawns a fresh interpreter with a redirected `NAZAK_DATA_DIR` and asserts that
`import nazak.config` leaves the filesystem untouched.

### Logging

In the windowed (no-console) build, `sys.stdout`/`sys.stderr` are replaced by a
size-rotated stream (`nazak/main.py`, 5 MiB × 3 backups). The previous implementation opened
and appended to the log file on every write with no rotation.

### Container

The image is multi-stage (`builder` → `runtime`): the runtime layer receives a prepared
virtualenv and the Chromium build, but no pip caches or build tooling. It runs as the
unprivileged user `nazak` (uid/gid **10001**) and declares a `HEALTHCHECK` that probes
`/api/system/info` with the token from the environment.

Because the app writes to `./data` through a bind mount, the host directory must be writable
by uid 10001:

```powershell
docker compose up -d --build
# first run only, if ./data is owned by your desktop user:
sudo chown -R 10001:10001 ./data
```

`docker compose config`/`docker run` smoke tests (`.github/workflows/docker.yml`) keep
verifying the refusal-without-token path and the Host/Origin/token policy.

### Test gates

CI runs the full matrix (Windows + Ubuntu × Python 3.10–3.13) on the default JSON backend with a
coverage floor of **65 %** (measured baseline: 69 %), and then re-runs the backend-agnostic
API/store suites with `NAZAK_PROFILE_STORE=sqlite` so the whole request path is verified against
`profiles.db` too. The backend is deliberately *not* a job-wide matrix dimension: several suites
assert JSON-file internals on purpose and are covered by the default leg.
A separate opt-in `live-browser-smoke` job (workflow_dispatch) caches the Playwright browsers and
runs `pytest -m live tests/live`.

---

## ⚡ Interactive Swagger Documentation

When Nazak Browser Studio is running in server mode (`python -m nazak.main --mode web` or while the desktop GUI is running), the built-in FastAPI server automatically serves the interactive API documentation:

- **Swagger UI**: Open your browser at `http://127.0.0.1:8899/docs` (or `http://127.0.0.1:8899/swagger`). Test any endpoint in real time, inspect JSON schemas, and execute queries directly from the interface.
- **ReDoc**: Available at `http://127.0.0.1:8899/redoc` for structured technical reference in three-panel format.
- **OpenAPI Schema**: Raw schema available at `http://127.0.0.1:8899/openapi.json`.

### Request validation, limits and response headers

Every request model carries explicit bounds — a single call can no longer stall the server:

| Field | Bound |
|---|---|
| `MassGenerateRequest.count` | `1..200` (matches the CLI; the service clamps too) |
| `AutopostBatchRequest.delay_seconds` | `0..3600` |
| `SynchronizerStartRequest.min_delay_ms` / `max_delay_ms` | `0..60000` |
| `SynchronizerStartRequest.coordinate_jitter_px` | `0..50` |
| `SynchronizerStartRequest.worker_profile_ids`, `BatchActionRequest.profile_ids`, `ScenarioRunRequest.profile_ids`, `UniquifyRequest.profile_ids` | ≤ 500 ids |
| `WindowTileRequest.cols` | `1..8` |
| `LaunchRequest.cdp_port` | `1..65535` |
| `ScenarioRunRequest.max_concurrency` | `1..10` |
| `WarmupRequest.steps_count` | `1..20` |
| `BulkCookieExportRequest.format` | `json` \| `netscape` \| `zip` |
| `CookieImportRequest.cookies_data`, `BulkCookieImportRequest.cookies_data` | ≤ 5 000 000 chars |
| `SynchronizerNavigateRequest.url` | http(s) only — `file://`, `data:` and `javascript:` are rejected |

Out-of-range values return **422** with a JSON-safe body. That body never echoes non-finite
numbers or multi-megabyte inputs (a raw `Infinity` used to produce a 500 while serializing the
error itself), and it does not include the request URL.

Responses carry `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`,
`X-Frame-Options: DENY`, COOP/CORP, `Permissions-Policy` and a CSP with a **strict
`script-src 'self'`** (`object-src 'none'`, `base-uri 'none'`, `form-action 'self'`,
`frame-ancestors 'none'`). The dashboard has no inline handlers and no inline `<script>`, so
`'unsafe-inline'` is not needed for scripts; only `style-src` still allows inline styles
(≈62 inline `style=` attributes remain — CSS injection does not execute script).
`/api` and `/v1.0` responses are `Cache-Control: no-store`.

**Origin rule.** A loopback `Origin` is accepted when it is either the documented dev-server port
(`:3000`, plus whatever `configure_local_access()` registered) or **same-origin with the request's
own `Host`** — the latter makes the dashboard work on any `--port`, including the WebSocket
handshake, which always carries `Origin`. Foreign origins, `null`, `127.0.0.1.evil.com`-style
suffix spoofs and a local page on an unlisted, non-matching port are refused with 403.
Verified end-to-end in a real browser and by `tests/test_api_origin_and_ws.py`.

---

## 🤖 1. Dolphin{anty} v1.0 & Nazak v1 Local Automation API

Provides a compatible subset of the Dolphin{anty} v1.0 local automation protocol as well as native Nazak v1 routes. External automation scripts in **Playwright**, **Puppeteer**, **Selenium**, or **BAS** connect directly over CDP to running profiles with isolated hardware fingerprints and proxy tunnels.

### Endpoints:

#### `GET /v1.0/browser_profiles`
Retrieves the list of all profiles with their live execution statuses, attached proxies, CDP endpoints, and tags. Proxy credentials are always masked in responses: `password`, `raw` and `rotation_url` become `"***"` — the password is redacted from `raw` positionally in both documented shapes (`user:pass@host` and `host:port:user:pass`; one shared masker, `nazak/core/secret_masking.py`, serves this API and the CLI) — credentials never leave the machine in plaintext. Echoing a masked body back to `PUT /api/profiles/{id}` keeps the stored value instead of overwriting it.
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
        "password": "***"
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
| `GET` | `/api/profiles/{id}/bundle/export` | Export complete profile as portable `.nazak` zip archive (built in a temp file, deleted right after the response) |
| `POST` | `/api/profiles/{id}/clear-cache` | Purge browser cache and temporary shader data |
| `POST` | `/api/profiles/{id}/seed-history` | Seed organic Chromium browsing history (SQLite) across the past 14 days (`?entries_count=25`) |

### Write & launch semantics:

- **`PUT /api/profiles/{id}` merges instead of replacing.** Only the fields present in the request body are written; `proxy`, `fingerprint` and `google` are merged per-field against the stored profile, so a partial body never resets proxy credentials, timezone, GPU strings or noise seeds. Masked values (`"***"`, `<encrypted: ...>`, `ab...yz`) received back from a `GET` keep the stored secret untouched.
- **Launch URL policy**: `custom_url` (and `google.custom_url`) may only be `http(s)` or `about:` targets. Values starting with `-` (Chrome flag injection) or using `file:` / `data:` / `javascript:` / `blob:` / `vbscript:` are refused with `400`; a bare hostname is promoted to `https://`.
- **`POST /api/profiles/{id}/clone` regenerates the device.** The clone gets a fresh user agent, GPU, screen, core/RAM counts, media device ids and noise seeds, while the operator's timezone, language and shield toggles are kept.
- **New profiles get a random GPU** when the request omits `fingerprint.webgl_*` instead of all landing on one stock renderer.

### Key Endpoints:

#### `POST /api/profiles/{id}/seed-history`
Seeds authentic Chromium browsing history records into the profile's SQLite database (`<user_data_dir>/Default/History`). Injects realistic visit timestamps across the past 14 days using WebKit epoch microseconds (`(unix_epoch + 11644473600) * 1,000,000`) and natural dwell times across high-trust domains (Google, Wikipedia, GitHub, StackOverflow, Reddit, YouTube, BBC, Amazon) to defeat empty-profile bot detection (Google Antifraud, Cloudflare Turnstile, DataDome).

- **Path Parameters**:
  - `id` (string, required): Profile identifier.
- **Query Parameters**:
  - `entries_count` (integer, default: `25`, min: `5`, max: `100`): Number of history entries to seed.
- **Response `200 OK`**:
```json
{
  "success": true,
  "profile_id": "prof_01",
  "seeded_entries": 25
}
```

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
Exports session cookies for the listed profiles into a structured JSON map or a downloadable `.zip` archive containing per-profile cookie files. `profile_ids` is required and must be non-empty — an omitted or empty list returns `400` instead of silently exporting every profile.
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
| `POST` | `/api/profiles/{id}/rotate-proxy` | Trigger provider rotation URL for dynamic mobile proxy (`http(s)` to a public host only — `file:`, loopback, private and link-local targets, and redirects, are refused with `400`) |
| `POST` | `/api/profiles/{id}/check` | Perform 5-stage health check; the result (including the `timezone_mismatch` report) is recorded on the profile — the spoofed fingerprint is never rewritten by the geo lookup (see below) |
| `POST` | `/api/profiles/check-all` | Batch run health checks across all configured profiles |
| `POST` | `/api/profiles/test-proxy` | Test standalone raw proxy string without profile binding |

#### 5-Stage Diagnostics Pipeline:
1. **TCP Connection Latency**: Ping time to host/port.
2. **External IP & ISP Identification**: Resolves exit IP, organization, and country.
3. **Geolocation & Timezone Extraction**: Records latitude, longitude, and timezone name **on the check result only** — the profile's spoofed `fingerprint.timezone`/`geolocation` are never overwritten by a geo lookup (v1.15.1): a Berlin-configured profile must not silently become a Tokyo profile after one check. A mismatch between the profile timezone and the exit-IP timezone is reported on the result (`timezone_mismatch`), and the operator decides whether to align the fingerprint.
4. **Google Reachability**: Checks connectivity and challenge detection against Google endpoints.
5. **Data Isolation**: Verifies that user data directory is isolated and free of port conflicts.

---

## 🎬 7. YouTube Shorts & Instagram Reels Autoposter & FFmpeg

| Method | Path | Description |
| :--- | :--- | :--- |
| `GET` | `/api/autopost/status` | Queue progress and FFmpeg binary availability |
| `POST` | `/api/autopost/uniquify` | Deep video uniquification with FFmpeg. `source_video_path` must be an existing regular file with a media extension (`.mp4 .mov .mkv .webm .avi .m4v .mpg .mpeg .wmv .flv`), otherwise `400` |
| `POST` | `/api/autopost/launch` | Start upload queue using Bezier motorics. `source_video_path` (same validation as above) wins; otherwise the server falls back to `<data>/videos/source.mp4`, and if that is absent it answers `400` unless `"demo": true` is passed, in which case a real ffmpeg test clip is generated (never a fake byte blob) |
| `POST` | `/api/autopost/cancel` | Cancel queue and terminate active upload instances |
| `POST` | `/api/autopost/preview-spintax` | Preview generated titles/descriptions from spintax template |

---

## 📡 8. System Diagnostics & WebSocket Events

### `GET /api/system/info`
Host diagnostics: OS platform, CPU concurrency, memory stats, Chrome binary path, active profile count, data directory paths.

### `WebSocket /ws/events`
Real-time streaming channel for UI synchronization and telemetry:
- `profile_status_change` (`{ profile_id, status, pid, error }`)
- `profile_created`, `profile_updated`, `profile_deleted`
- `profile_health_update` (`{ profile_id, health }`)
- `profiles_bulk_created` (`{ count }`)
- `cookies_bulk_imported` (`{ count, profiles_updated }`)
- `synchronizer_started` (`{ session }`), `synchronizer_stopped`
- `autopost_batch_started` (`{ total }`)
- `autopost_job_update` (`{ profile_id, status, message?, error?, video_url? }` — one event per job transition)
- `autopost_batch_finished` (`{ results }`)
- `secrets_mode_changed` (`{ mode }`)

---

## 🔐 9. Secrets Storage — User-Selectable Encryption Mode

> **User Choice Principle**: Nazak never forces a storage mechanism. The user selects the encryption mode for credentials (passwords, TOTP seeds). The passphrase is **never written to disk** and lives only in process memory.

### Supported Modes:

| Mode | Encryption Primitive | Key Derivation | Storage Format | Trade-off |
| :--- | :--- | :--- | :--- | :--- |
| `plain` *(default)* | None | None | Plaintext | Full transparency; no encryption |
| `dpapi` | Windows DPAPI | OS User Master Key | `nzk1:dpapi:...` | User-scoped; Windows only |
| `passphrase` | Fernet (AES-128-CBC + HMAC) | PBKDF2-HMAC-SHA256 (600,000 iterations) | `nzk1:pwd:...` | Platform-independent; lost passphrase = unrecoverable data |

### Endpoints:

#### `GET /api/security/secrets-mode`
Inspects current mode, available modes, and platform suitability.

#### `POST /api/security/secrets-mode`
Switches the active mode. New writes use the selected mode immediately; existing envelopes stay decodable and are **not** re-encrypted by this call — re-encryption of the whole fleet is a separate, explicit operation (`ProfileManager.reencrypt_all_profile_secrets`):
```json
{
  "mode": "passphrase",
  "passphrase": "my-secure-master-password"
}
```

### Masking Guarantee:
In all API endpoints (`GET /api/profiles`, `GET /api/profiles/{id}`), sensitive values (`account_password`, `totp_secret`) are masked (`ab...yz`) before transmission, and proxy credentials (`password`, `raw`, `rotation_url`) are masked (`"***"`). The write path recognises those masks and placeholders, so saving a profile that was loaded from the API never destroys a stored secret; a genuinely new plaintext value is encrypted in the active mode before it reaches disk.

---

## 🛡️ 10. Hardware Isolation & Manifest V3 Stealth Architecture

> 📖 **Operator-facing documentation:** [`docs/ANTIDETECT_GUIDE.md`](ANTIDETECT_GUIDE.md)
> — the surface map, the verification method (CreepJS/BotD replays), the honest limits
> (what is spoofed vs. what is left to the operator: IP, TLS, behaviour) and the
> applicability matrix.

### Chrome Manifest V3 Migration:
- **`manifest_version: 3`**: Compatible with modern Chromium deprecation rules.
- **Service Worker Architecture**: Uses `background.service_worker` (`background.js`) instead of persistent background scripts.
- **Declarative Proxy Authentication**: Uses `webRequestAuthProvider` permission with `chrome.webRequest.onAuthRequired.addListener(..., ["asyncBlocking"])`.
- **`MAIN` World Execution**: Stealth scripts inject at `document_start` inside the DOM's main execution context.

### Fingerprint Spoofing Fidelity (Total Hardware Shield v2.6):

- **Proxy-Over-Native Hook Architecture (the stealth core)**: every hook is a **Proxy over the NATIVE function**, never a plain-JS replacement. The native getter runs first (receiver-less access still throws the native `Illegal invocation` TypeError with its native stack), the function's shape (own keys, extendability, `toString()`) stays native, and a proxied API answers `toString()` with the **exact original signature**. Our own frames are spliced out of error stacks, and `Error.stackTraceLimit` is raised inside traps so the native stack tail survives. Verified by a faithful port of the CreepJS lie detector: **0 corrupted APIs of 36 scanned** (a plain-Chrome control: 0; the pre-rework shield: 33), and **6 of 7** adversarial error-trace shapes match the host byte-for-byte (the 7th is a V8 engine limitation shared by every JS-level stealth tool). Nothing is left on the instances: `getOwnPropertyNames(navigator)` is empty, the window carries none of our properties.
- **Scope coverage**: the shield applies to the main world, **Workers and ServiceWorkers** (a Worker's navigator is a `WorkerNavigator` — a different class; both prototypes are hooked) and cross-origin iframes.
- **WebGPU Hardware Emulation (`navigator.gpu`)**: Intercepts `navigator.gpu.requestAdapter()` and synchronizes `adapter.requestAdapterInfo()` and `adapter.info` with the profile's WebGL vendor and architecture, on a real `GPUAdapterInfo`-shaped object (NVIDIA Ada Lovelace RTX 4090/4080, Ampere RTX 3080/3070, Apple M-Series, AMD RDNA 3, Intel Alchemist).
- **WebGL fidelity**: UNMASKED_VENDOR/RENDERER answer `null` until `WEBGL_debug_renderer_info` is requested (the native semantics), both the WebGL **and** WebGL2 prototypes are hooked, and the aliased ranges are real `Float32Array` pairs.
- **Local Font Spoofing (`queryLocalFonts`)**: answers from a **per-profile font pool** (24–42 realistic families per OS; a real Windows box reports 25–60 — measured). Families the host lacks are backed by a real sibling font through `@font-face src: local(...)`, so the rendered widths agree with the claim; the aliases stay out of `document.fonts` (size and enumeration are filtered).
- **SpeechSynthesis Platform Voices**: Overrides `speechSynthesis.getVoices()` to align system speech voices with the spoofed operating system and primary language locale; the voice objects carry no own properties, like the native ones.
- **Content-Derived Canvas Noise**: LCG perturbation derived from the **profile seed and the CONTENT** — the same content yields the same hash on every read (a real browser's property), different profiles hash differently. The main canvas and the OffscreenCanvas produce the **same** image (measured: 0 differing pixels). The noise is applied exactly once per read, on the raw pixels.
- **AudioContext & OfflineAudioContext Noise**: Per-call phase shift shared between direct `getChannelData` reads and `startRendering` renders, so two reads of the same buffer never repeat the pattern; `sampleRate`/`baseLatency`/`numberOfChannels` pinned to the profile.
- **Stable Sub-pixel Jitter**: `measureText` and `getBoundingClientRect` offsets are **stable per string / per element** (a real renderer only changes them when the layout changes) — two reads of the same rect or the same text never differ, and the canvas metric agrees with the DOM metric.
- **WebRTC Candidate Sanitizer & Leak Protection**: Intercepts `createOffer`, `createAnswer` and `setLocalDescription` on `RTCPeerConnection` plus the `RTCIceCandidate` constructor, so trickle-ICE candidates (which bypass the SDP hooks entirely) are scrubbed too. Strips private IPv4 candidates (RFC 1918: `10.x`, `192.168.x`, `172.16-31.x`) and IPv6 mDNS candidates from SDP payloads.
- **Chromium V8 & C++ Timezone Synchronization**: The CDP stealth injector issues `Emulation.setTimezoneOverride` per page session (verified live: JavaScript `Intl` reports the profile timezone), backed by the `--time-zone-for-testing={timezone}` launch flag and the `TZ` process environment for native routines. The fingerprint generator always resolves the *current* DST-aware offset via zoneinfo — a static table offset goes stale for half the year (Berlin −60 in winter vs −120 in summer) and the zone/offset mismatch is an instant tell.
- **Organic Profile History Seeder (SQLite)**: Populates authentic WebKit microsecond timestamps into Chromium's native `Default/History` database across the past 14 days with realistic multi-visit frequencies across high-trust domains (Google, Wikipedia, GitHub, StackOverflow, Reddit, YouTube, BBC, Amazon).
- **`navigator.webdriver`**: A Proxy over the **native** getter — the property keeps its native descriptor semantics and `toString()`, and `Object.getOwnPropertyNames(navigator)` stays empty.
- **Human cursor (Bezier motorics)**: aimed moves overshoot the target and settle back with 1–2 micro-corrections, and the speed profile is asymmetric (fast attack, long tail) rather than a time-symmetric cosine ease.
- **CDP DevToolsActivePort Handshake**: Dynamically resolves bound port and ephemeral GUID directly from Chromium runtime state, eliminating race conditions and stale socket fallbacks.

> ⚠️ **Honest limits:** the shield owns the *fingerprint* signal — it cannot own your IP
> reputation, your TLS stack, or your behaviour pattern. See the
> [Anti-Detect Guide](ANTIDETECT_GUIDE.md) for the full boundary map and the operator
> checklist.
