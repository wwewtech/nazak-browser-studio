# Changelog

All notable changes to Nazak Browser Studio are documented here. For the full feature set see [README.md](README.md), the [REST API reference](docs/API_REFERENCE.md) and the [CLI reference](docs/CLI_REFERENCE.md).

## v1.12.0 — Structural Refactor (P0) & Platform Hardening (P1) (2026-10-12)

No behaviour change on default settings. `profiles.json` on-disk format is unchanged; all
`nazak.api.server.*` imports and `patch()` targets keep working; GUI signals keep their names.

### P0 — decompose the monoliths

- **API monolith split.** `nazak/api/server.py` (1792 lines) is now a thin composition root
  (singletons, guard, `app`, router mounting, WebSocket). Endpoints moved verbatim into
  `nazak/api/routers/` (`system`, `profiles`, `automation`, `proxies`, `cookies`, `warmup`,
  `synchronizer`, `autopost`); request bodies into `nazak/api/schemas.py`; Host/Origin/token/CSP/
  masking/SSRF-pinning perimeter into `nazak/api/security.py`; WS hub into `nazak/api/realtime.py`;
  lazy singleton accessors into `nazak/api/deps.py`. See
  [API reference § Code Map](docs/API_REFERENCE.md#-code-map--where-each-api-area-lives-p0-layout).
- **ProfileManager split + SQLite opt-in.** `nazak/core/profile_manager.py` (1195 lines) is now a
  facade over `nazak/core/profiles/` (`store_json`, `store_sqlite`, `service`, `bundles`, `files`,
  `merge`, `constants`, `presets`). JSON backend keeps atomic tmp+rename writes, corrupt `.bak`
  recovery and rotating `.bak.N` backups. New `SqliteProfileBackend` (`profiles.db`, WAL,
  single-row `save_one`/`delete_one` upserts, `VACUUM`, one-shot JSON→SQLite migration with
  `profiles.pre-sqlite.<ts>.bak` kept, never deleted). Selected by `NAZAK_PROFILE_STORE=json`
  (default) / `sqlite` (opt-in). Details and rollback:
  [API reference § Storage Backends](docs/API_REFERENCE.md#-profile-storage-backends--json-default--sqlite-opt-in)
  and [CLI reference § 5b](docs/CLI_REFERENCE.md#5b-profile-storage--json-default-and-sqlite-opt-in).
- **TaskBridge.** `nazak/gui/task_bridge.py` owns one `QThread` per bridge (busy → `RuntimeError`,
  cooperative `cancel()`, Qt signals, headless inline fallback); Qt-free business logic lives in
  `nazak/gui/tasks.py`; `nazak/gui/workers.py` keeps the same worker/signal names as adapters.
- **Fix along the way.** Rotation-URL pinned opener now disables env/system proxies
  (`ProxyHandler({})`): previously a system proxy (e.g. `127.0.0.1:10809`) silently routed the
  SSRF-pinned fetch through a middlebox, defeating the pinning.

### P1 — platform hardening

- **No import-time filesystem side effects.** `nazak/config.py` no longer creates the data tree on
  import; the new idempotent `ensure_data_dirs()` is called by real entry points (`nazak/main.py`,
  the API composition root, the CLI helpers and the GUI launcher). A test spawns a fresh
  interpreter with a redirected `NAZAK_DATA_DIR` and proves `import nazak.config` touches nothing.
- **Bounded logs.** The windowed (no-console) build replaces `sys.stdout`/`sys.stderr` with a
  size-rotated stream (5 MiB × 3 backups) instead of appending to the log file on every write.
- **Dependency drift is impossible.** `tests/test_p1_platform_hardening.py` parses
  `pyproject.toml` and `requirements.txt` and fails when a package exists in only one of them
  (`pyproject` is canonical; `requirements.txt` is what the image installs).
- **Container hardening.** The image is multi-stage (`builder` → `runtime` with a prepared
  virtualenv and Chromium), runs as unprivileged `nazak` (uid/gid 10001), declares a
  `HEALTHCHECK` probing `/api/system/info`, and forwards `NAZAK_PROFILE_STORE` through
  `docker-compose.yml`. Release packaging (`build_exe.py`, `installer.iss`) now also strips
  SQLite artefacts (`profiles.db*`, `profiles.pre-sqlite.*`).
- **CI gates.** New `security-audit` job: advisory `pip-audit` over the requirement set plus a
  blocking `bandit -ll` SAST pass with an explicit, documented skip list (`[tool.bandit]` in
  `pyproject.toml`). The test matrix enforces a coverage floor of **65 %** (measured baseline
  69 %) and then re-runs the backend-agnostic API/store suites with `NAZAK_PROFILE_STORE=sqlite`,
  so the whole request path is exercised against `profiles.db` as well (the backend is not a
  job-wide dimension: the suites that assert JSON-file internals stay on the default leg).
  A new opt-in `live-browser-smoke` job caches the Playwright browsers for `pytest -m live`.

### Tests & docs

- New suites: `tests/test_p0_api_split.py` (routes/exports/handler identity),
  `tests/test_p0_sqlite_store.py` (roundtrip, migration, upsert, corrupt-JSON survival,
  bare-list format), `tests/test_p0_task_bridge.py` (inline sync/async, busy-guard, cancel,
  error, progress), `tests/test_p1_platform_hardening.py` (import purity, log rotation,
  dependency drift, container and CI contracts).
- Suite: **783 passed, 5 deselected**; `ruff check`, `ruff format --check` and `mypy nazak` clean.
- Documentation translated to English throughout (`docs/*.md`, `CHANGELOG.md`), plus new
  [API reference § Operations & Hardening](docs/API_REFERENCE.md#-operations--hardening-p1) and
  a rewritten `docs/CLI_REFERENCE.md` § 5b/5c. User-facing CLI help text stays Russian by
  design (English flags/JSON keys), as documented in the CLI reference.

### SQLite default-switch decision (recorded, not yet executed)

`json` stays the default in this release. Switching the default to `sqlite` is deferred until
all gates pass: (1) one release soak of opt-in `sqlite` with no migration/data-loss reports;
(2) CI green on both backends across the full matrix; (3) a measured mass-generate/import
comparison on 200 profiles; (4) documented rollback drill (unset → JSON resumes, `.bak` kept).
Then: flip `backend_for()` default to `sqlite`, keep `json` as opt-out for one more release,
and announce in this changelog. Until then, `sqlite` is supported but opt-in.

## v1.11.0 — Round-3 & Round-3b Audit Remediation (2026-10-06)

Two audit passes over the whole product: the first covered the CLI/agent surface, publication
honesty, the local API perimeter, warmup and Docker; the second deliberately went into the code
the first one had not read — the dashboard HTML and its font dependencies, the whole stealth-JS
generator, the CDP injector loop, the synchronizer, `cli_cmds/automation.py`, the GUI dialogs,
`nazak/tools/*`, the release build, bundle import and every API request model. 13 commits.
Full findings with evidence, and an explicit list of what could not be verified:
[docs/AUDIT_ROUND3_FINDINGS.md](docs/AUDIT_ROUND3_FINDINGS.md) (§1–§10 first pass, §11 second pass).

Test suite: **725 collected** (3 `live` tests deselected by default), `ruff check`,
`ruff format --check` and `mypy` (with **no** suppressed error codes) clean. 56 new regression
tests. Verified on a real Docker engine (image build, runtime contract, `.dockerignore`), in a real
Chromium for the dashboard XSS (with a differential control), and on the published release artifact
itself: the released ZIP's SHA256 matches the published `SHA256SUMS.txt` and contains **no** runtime
`data/` (0 of 4357 entries — only `data/assets`).

### Security — strict CSP for the dashboard (round-3c)

The CSP shipped in v1.11.0 had to keep `script-src 'unsafe-inline'` because the dashboard was
built from 58 inline `on*` attributes, and a real-browser check proved that such a policy does
**not** stop the dashboard XSS. That refactor is now done:

- **All 58 inline handlers replaced by `data-action` + one delegated listener**
  (`DELEGATED_ACTIONS` in `nazak/web/app.js`, 42 distinct actions). `click`, `change` and `input`
  bubble to a single document-level dispatcher; parameters travel in `data-*` attributes and are
  read only from there; unknown actions are reported, not executed. `index.html` no longer contains
  a single `on*=` attribute, and `node --check` validates the bundle.
- **`script-src` is now strictly `'self'`** — no `'unsafe-inline'`, no `'unsafe-eval'`. The policy
  keeps `object-src 'none'`, `base-uri 'none'`, `form-action 'self'` and `frame-ancestors 'none'`.
  `style-src` still allows inline styles (≈62 inline `style=` attributes remain; CSS injection is
  not script execution) — that remainder is documented in `server.py` and in the API reference.
- **Verified in real Chromium** (`tests/live/test_dashboard_ui_smoke_live.py`): a full click-through
  of the dashboard (11 modals/dropdowns/checkbox/search/filter flows) produces zero page errors and
  zero console errors, and a differential control proves the point of the refactor — an inline
  handler injected straight into the DOM executes on a plain page but **not** on the dashboard,
  so a forgotten escaping no longer means script execution.

### Fixed — dashboard WebSocket / Origin on custom ports (round-3c)

The new browser test also caught a real perimeter bug: the Origin check compared the request
against a fixed port list `{8899, 3000}` that was only populated by `configure_local_access()`
from `main.py`. Serving the app any other way (`uvicorn nazak.api.server:app`, gunicorn,
embedding, tests) left the port unregistered, and since a **WebSocket handshake always sends
`Origin`**, the dashboard's live updates were rejected with 403 — as were all its `Origin`-bearing
POSTs. Unit tests on `TestClient` never saw it because `TestClient` sends no `Origin`.

`_origin_matches_request()` now accepts a loopback Origin that is either in the CORS whitelist
(the deliberate dev-server case) **or** matches the request's own `Host` (same-origin on any port).
Foreign origins, `null`, suffix-spoofed hosts (`127.0.0.1.evil.com`) and a local page on an
unlisted, non-matching port are still refused. Covered by `tests/test_api_origin_and_ws.py`
(19 tests, including a real WebSocket handshake on a random port).

### Security — second audit pass (round-3b)

Second pass covered the areas the first one had not read: the dashboard HTML/fonts, the whole
stealth-JS generator, the CDP injector loop, the synchronizer, `cli_cmds/automation.py`,
the GUI dialogs, `nazak/tools/*`, the release build (`build_exe.py`/`installer.iss`), bundle
import and every API request model. Findings, evidence and verification: §11 of the audit report.

- **Page→browser action injection closed (`Runtime.addBinding`).** The binding was installed for
  every attached session and the handler checked only the binding name, so any script in the
  master page — including a third-party ad iframe — could feed gestures that the synchronizer
  replayed as clicks/keys/typing in **other profiles'** logged-in browsers. Events are now accepted
  only from the main-world context of the top frame of a top-level page, capped at 4 KiB, rate
  limited (60/s, burst 120) and parsed off the CDP read loop.
- **Non-finite numbers cannot reach the stealth layer.** `json.loads` accepts `Infinity`/`NaN` and
  pydantic accepted them by default, so `device_pixel_ratio: Infinity` was stored and rendered as
  the Python literal `() => inf` (ReferenceError on every `window.devicePixelRatio` read, and a
  loud tamper signal), while `audio_noise_seed: NaN` silently disabled the audio-noise shield.
  Models now use `allow_inf_nan=False`, the generator formats floats through `_js_number()`, a
  hostile geo response is sanitized (`_finite_or_none`/`_safe_text`/`_safe_timezone`), and a
  non-finite body returns a serializable 422 instead of a 500.
- **Bounds on every request model** (`Field(ge/le/max_length/pattern)`) plus matching service-level
  clamps: `mass-generate count 1..200` (measured: unbounded `count` is O(n²) in `profiles.json`
  rewrites), `autopost delay_seconds 0..3600` (unbounded value held `is_running` for years),
  synchronizer delays/jitter, `cols 1..8`, `cdp_port`, `max_concurrency`, profile-id lists and
  text fields. Lower bounds that previously produced the endpoints' 400 contract were left intact.
- **Archive limits.** `.nazak` bundle import and cookie-ZIP parsing had no caps (measured: a 100 KiB
  archive wrote 100 MiB to disk). Entry-count, per-entry and total limits are now enforced, and a
  refused bundle leaves no half-extracted directory behind.
- **Release artifacts no longer carry runtime `data/`.** The build smoke-tests the freshly built
  exe, and the frozen app keeps its data next to the executable, so `data/profiles.json`,
  `data/profiles/`, `data/logs/`, `data/extensions/` ended up inside both the release ZIP and the
  installer — the very directory that holds plaintext passwords and 2FA seeds in `plain` mode.
  `sanitize_app_data()` strips them before packaging (`data/assets` is restored for the icon) and
  the installer excludes them as a second layer.
- **Security headers + partial CSP.** `/` was served with no headers at all. Responses now carry
  `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, `X-Frame-Options: DENY`,
  COOP/CORP, `Permissions-Policy` and a CSP with `object-src 'none'`, `base-uri 'none'`,
  `form-action 'self'`, `frame-ancestors 'none'`; API responses are `Cache-Control: no-store`
  (cookie exports must not land in the disk cache). `script-src` still needs `'unsafe-inline'`
  because the UI has 58 inline handlers — verified in a real browser that this CSP alone does
  **not** stop the XSS; escaping remains the load-bearing defence. A strict CSP needs the
  `addEventListener` refactor.
- **GUI honesty.** Cache cleanup asks for confirmation and both `clear_profile_cache` and
  `save_profile_cookies` results are honoured (error instead of a false success); the batch cookie
  import shows the `failed` counter.
- **Predictable CDP ports removed** in the GUI autopost worker (`9350 + idx` → `get_free_port()`),
  which matters because CDP has no authentication.
- **No page-visible brand markers.** `window.__nazakShieldApplied`, `window.__nazakSyncInstalled`
  and the `__nazak_sync_event` binding told any anti-fraud script exactly which product was in use.
  They are renamed to neutral, non-enumerable properties/binding (`__nsi`, `__nse_c`, `__nse_ev`),
  and the injector applies the script once per `(session, loaderId)` document.

### Fixed — CLI / synchronizer

- **`scenario run` without `--wait` no longer lies.** It started a daemon thread and printed
  success, but `main.py` exits with `SystemExit`, so the thread died before doing anything
  (reproduced: exit 0, marker file never created). Background mode now spawns a detached process
  (survives the CLI exit) that logs to `data/logs/scenario_<timestamp>.log` and returns its pid;
  if the spawn fails the command reports an error and points at `--wait`.
- **The synchronizer tells the truth about a dead pump.** `time.sleep()` sat outside the per-event
  `try`, so a negative `--min-delay`/`min_delay_ms` raised `ValueError` (verified) and killed the
  pump thread while `session.active` stayed `True` — `get_status()` kept reporting an active
  session and `mirror_navigation` blocked ~110 s. Delays are clamped, the sleep is inside the
  `try`, the pump's `finally` deactivates the session and records `last_error`, navigation checks
  the pump thread first, and the event queue is bounded with a `dropped_events` counter.
- **`sync navigate` refuses non-http(s) URLs.** The URL went straight into `page.goto()`, so
  `file://`, `data:` and `javascript:` opened in the worker browsers (verified by execution);
  the API now rejects them with 422 and the service layer refuses them too.
- **`_ensure_worker_pages` checks the page cache before importing Playwright** — a pure
  optimisation that also turned the pre-existing env failure of
  `test_mirror_one_replicates_event_to_all_workers` into a pass.

### Fixed — web dashboard

- `e.message` in the diagnostics error path is escaped; the video link carries
  `rel="noopener noreferrer"`.
- The dashboard no longer loads Google-hosted webfonts: it works offline and does not phone a
  third party on every load. `styles.css` uses explicit system stacks
  (`Segoe UI Variable Text`, `Cascadia Mono`).

### Fixed — tools

- `nazak/tools/generate_brand_assets.py` wrote to the author's hard-coded `D:/nazak/data/assets`
  (outside the repo, or crashed) and stamped a stale `V1.3.0` into the banner; both now derive
  from the repository and the package version. The mass-generate dialog docstring matches its
  actual 1..100 slider range.


### Security — CLI / agent surface

- **`profile get` masks secrets by default.** The proxy password, `account_password` and `totp_secret` in `google.notes` no longer reach the agent's stdout/logs: output is masked (`***`, `ab...yz`), plaintext only with an explicit `--reveal` (or `NAZAK_REVEAL=1`). Previously `model_dump()` printed everything verbatim and the `mask_proxy_dict` helper was dead code.
- **`account totp` no longer lies.** The command called `decrypt_notes(reveal=False)` (the mask) and returned `{"success": true, "totp_code": "000000"}` with exit 0. The secret is now revealed through `reveal_notes()`, and `generate_totp_rfc6238()` raises `ValueError` instead of fabricating a code (its test was updated too).
- **`@file` and `--out` are no longer arbitrary filesystem access.** A misspelled `@path` is an input error (`exit 2`) rather than a silent substitution of the literal `"@path"` string into the parser; reads are capped at 16 MB and directories are rejected. `--out` does not overwrite an existing file without `--force`/`--yes`.
- **`account login --profile <id>` does not log into someone else's account.** Previously the match was a substring search over name/email, and on a miss the first Google profile was silently taken and a video was published. Now only an exact id/email matches; otherwise it stops without publishing.
- **The live TOTP code is no longer printed.** The `print(... {code} ...)` calls in `cli_auto_login_and_upload.py` and the code substitution into the `account_provisioner.automate_google_login` progress output were removed (in `--json` mode that stdout went to stderr — that is, into the agent/CI logs).
- **The legacy login flow no longer writes a fake MP4.** Instead of `b"DEMO_MP4_HEADER" + b"0"*1024`, the clip is generated through `core.video_uniquifier.generate_demo_clip()` (the same honest generator as in the API), and "PUBLISHED SUCCESSFULLY" is printed only when the video link is actually found.
- **Account passwords are revealed for login through `reveal_notes()`** (the dpapi/passphrase modes work), and notes are written back from the original (encrypted) JSON so that decrypted text never reaches disk.

### Fixed — status honesty

- **The Instagram uploader returns an error when a publication is unconfirmed.** The steps used to sit under `if is_visible()`, and on failure it returned `True` with a fabricated `https://www.instagram.com/`. Now confirmation is required (a post link or a success toast); otherwise `publish-uncertain`.
- **A retry after clicking "Publish"/"Share" is forbidden** (`core/publish_status.py`): a second run means a duplicate publication. `403` was also removed from the list of retryable errors (it is a block/refusal, not a network failure).
- **The queue no longer leaves "stuck" jobs and browsers behind.** An unexpected exception in a batch no longer leaves `status="uploading"` and a `RUNNING` profile: the job is marked failed and the browsers the queue started are closed. `cancel_all` does not kill sessions the queue did not open.
- **`normalize_upload_platform` is case-insensitive** (`"Instagram_Reels"` no longer ends up on YouTube).
- **Warmup:** an unknown action returns `False` (not "success"), `dwell`/`human_scroll`/`watch_youtube` are clamped in time, and navigation validates the URL scheme (`sanitize_launch_url`) and refuses `file://`.

### Security — API / deployment

- **The server refuses to start on a non-loopback host without `NAZAK_API_TOKEN`** (`enforce_exposure_policy`, called from `main.py` for the GUI and web modes). The local solo scenario (`127.0.0.1`) is unchanged: no token needed. Docker/compose now pass `NAZAK_API_TOKEN` and document that the published port is visible on every interface.
- **`/docs`, `/redoc`, `/openapi.json` no longer bypass the Host check** (only `/static` is excluded).
- **A CSRF guard on `Sec-Fetch-Site: cross-site`** for HTTP and WebSocket: the state-changing `GET` endpoints of the Dolphin parity can no longer be triggered by a subresource load from a foreign site without `Origin`.
- **`Host: testserver` is accepted only in tests** (`NAZAK_ALLOW_TEST_HOST`, set by `tests/conftest.py`), not in production.
- **`X-API-Key` comparison uses `hmac.compare_digest`** instead of `==`.
- **`POST /api/autopost/uniquify` and `POST /api/autopost/launch`** accept only an existing regular file with a media extension (`resolve_media_source`) — an arbitrary path to a system file no longer goes to ffmpeg.
- **`rotate-proxy` pins the connection to the verified IP** (`_PinnedHTTP(S)Connection` + `_rotation_target`): the "public address first, then private" DNS race (TOCTOU) is eliminated, while the public-address filter and the ban on redirects are kept.

### Fixed — web / GUI

- **The diagnostics DOM-XSS is closed and verified in a real browser.** `health.ip/country/city` (values arriving from the geo API over plain HTTP through the user's proxy) are escaped through `escapeHtml`; `p.id` in inline handlers is escaped too; the video link is rendered only for the `http(s)` scheme. Verification: the new live test `tests/live/test_dashboard_xss_live.py` drives a real Chromium against a live Web Studio, replaces the `/api/profiles` and `/api/profiles/{id}/check` responses with a malicious payload (`</span><img src=x onerror=…>`) and fails if the script executed. Differential control: the same image with `app.js` rolled back to the pre-fix line — the test **fails** (`country=1, city=1, ip=1`; the injected code read 323 bytes from `/api/security/secrets-mode`), while on the fixed code it **passes**. The fields that were already escaped (`isp`, `error_message`) do not fire in the control.
- **GUI:** an `isRunning()` guard for `ProxyCheckWorker`/`CheckAllProxiesWorker` (a second click lost the reference to the live `QThread`), IP rotation moved into `ProxyRotateWorker` (the Qt main thread no longer blocks for 8 s), and the passphrase field is cleared after it is applied.

### Fixed — dependencies, quality, honest error handling

- **`requirements.txt` synchronized with `pyproject.toml`:** `psutil` and `cryptography` were added (the code imports them), plus `pytest-timeout` — without it the documented command `python -m pytest tests -q` failed with `unrecognized arguments: --timeout=30`.
- **`mypy`: all previously suppressed error codes are enabled** (`disable_error_code = []` instead of 12 disabled categories, including `arg-type`, `call-arg`, `attr-defined`, `assignment`, `index`) — the 16 errors found were fixed and the configuration is green again.
- **The unused `_HAS_CRYPTOGRAPHY` flag now works:** `passphrase` mode without the `cryptography` package produces a clear `SecretsError` instead of a `NameError` deep inside the KDF.
- **The fail-open of secret encryption is logged as `ERROR`** (the value still does not block the write, but it is no longer "silent").
- **The account parser no longer mangles passwords:** email is validated more strictly (a separator inside an email no longer glues fields together), and a password containing the separator (`p@ss:w0rd`) is recovered when the line contains a base32 2FA seed.
- **`process_monitor`** no longer swallows exceptions silently (a debug log instead of `pass`).
- **`format_video_metadata`** is annotated `dict[str, Any]` — the previous `dict[str, str]` contradicted the actual return value with `tags: list[str]`.

### Added

- `nazak/core/publish_status.py` — a shared "publication unconfirmed" contract for the uploaders and the queue.
- `core.video_uniquifier.generate_demo_clip()` — a single honest demo-clip generator for the API and the CLI.
- A global `--reveal` flag + the `NAZAK_REVEAL` env var; `--force` for `cookie export`, `cookie bulk-export`, `profile bundle-export`.
- `enforce_exposure_policy(host)` in `nazak/api/server.py`.
- Tests: `tests/test_round3_fixes.py` (29) and `tests/test_web_ui_injection_guards.py` (5).

### Fixed — Docker plumbing (verified on real Docker 29.8.2)

- **The `Dockerfile` would not build: the base image moved to trixie.** `docker run --rm python:3.11-slim cat /etc/os-release` → `Debian GNU/Linux 13 (trixie)`, while the apt list still held bookworm names — `libgl1-mesa-glx`, `libglib2.0-0`, `libatk1.0-0`, `libatk-bridge2.0-0`, `libcups2`, `libasound2` do not exist in trixie (confirmed via the Debian madison service and reproduced by a build: `E: Package 'libgl1-mesa-glx' has no installation candidate`). The base is pinned as `python:3.11-slim-trixie`, the names were replaced with `libgl1` and the `…t64` variants, and the unused `curl` was dropped. After the fix **`docker build` passes (exit 0)**, `hadolint 2.15.1` → exit 0.
- **`.dockerignore` added.** Without it `COPY . .` put the local `data/profiles.json` (account passwords and 2FA seeds in `plain` mode), the profiles' cookie/session files and `.git` into the image layers. Verified in the built image: `ls -a /app` contains neither `data` nor `.git`. Runtime data arrives through the bind mount `./data:/app/data`.
- **`docker-compose.yml` no longer exposes the API to the network.** Loopback only (`docker compose config` → `host_ip: 127.0.0.1`), `NAZAK_API_TOKEN` is mandatory (`${NAZAK_API_TOKEN:?…}` — without the variable compose fails with a clear message, exit 1), the outdated `version: '3.8'` was removed, and `.env.example` was added.
- **A new `docker.yml` CI job** (on Docker file changes and via `workflow_dispatch`): `docker compose config -q`, a real `docker build`, a check that startup without a token is refused, then the HTTP contract (`401` without a key, `200` with a key, `403` for a foreign `Host`/`Origin`/`Sec-Fetch-Site: cross-site`). Checked with `actionlint 1.7.12` (exit 0).
- **Verified on real Docker:** image build; dependencies inside the image (`deps-ok 1.10.0 7.2.2 50.0.2` — nazak/psutil/cryptography); startup refused without a token (exit 1 + text about `NAZAK_API_TOKEN`); the whole HTTP contract from inside the container; the web dashboard `200`; `docker compose up -d --build` → `Up`, `127.0.0.1:8899->8899/tcp`, `401`/`200` through the published port, `docker compose down` leaving nothing behind. 16/16 container checks in total.

## v1.10.0 — CLI Parity with GUI + AI-Agent Contract (2026-10-03)

The terminal CLI now covers **everything the GUI can do**: 11 groups, 61 commands (`profile`, `cookie`, `proxy`, `warmup`, `scenario`, `sync`, `autopost`, `account`, `cdp`, `secrets`, `system`) with 1:1 parity to the Fluent views and the REST API. 631 tests pass (612 before, plus 19 new CLI tests); `ruff` and `ruff format` are clean.

### Added

- **Modular CLI (`nazak/cli_cmds/`).** Direct-core by default (no server needed); `--server http://127.0.0.1:8899` replays the same commands through the running GUI/web API with `X-API-Key` support. Old root commands (`list`, `launch`, `stop`, `check`, `check-all`, `info`) keep working.
- **Profiles:** CRUD, `clone`, `batch-launch`/`batch-stop`, `bulk-import`, `mass-generate` (1–200, `--os-mix`), `fingerprint`, `clear-cache`, `seed-history`, `.nazak` `bundle-export`/`bundle-import`, idempotent `ensure --name` for agent retries.
- **Cookies / proxies:** single + bulk import/export (`json`/`netscape`/`zip`, `--file`/`@file`/stdin), `proxy check`/`check-all`/`test`/`rotate`.
- **Automation:** `warmup plan`/`launch`, `scenario list`/`run` (built-ins + aliases, `--concurrency`, `--wait`), `sync start`/`stop`/`status`/`tile`/`navigate`.
- **Autopost / accounts:** `autopost status`/`preview`/`uniquify`/`launch`/`cancel`, `account import`/`list`/`totp`/`login` (the former standalone `cli_auto_login_and_upload.py` flow, now parameterised).
- **CDP / system:** `cdp start`/`stop`/`active`/`info` (Dolphin `/v1.0` parity, `wsEndpoint` for `connect_over_cdp`), `system info`/`doctor`/`schema`/`version`, `secrets get`/`set`.
- **AI-agent contract:** `--json` accepted anywhere (stdout is a single JSON document, chatty progress goes to stderr), stable exit codes `0/1/2/4` (API 404→1, 400/409/422→2), every error carries a `hint` with the exact next command, destructive commands fail fast with `--yes` hint instead of hanging on `input()`, env duplicates (`NAZAK_JSON`, `NAZAK_YES`, `NAZAK_SERVER`, `NAZAK_API_TOKEN`, `NAZAK_PASSPHRASE`), machine-readable `system schema` (schema_version 1) for function-calling.

### Docs

- New [CLI reference](docs/CLI_REFERENCE.md) with the agent recipe (`doctor` → `schema` → `ensure` → `check` → `cdp start`); README Quick Start and test-coverage sections updated; REST API reference links to the CLI.

## v1.9.1 — Round-2 Audit Remediation (DEEP_AUDIT_ROUND2) (2026-09-30)

Second-pass audit of the v1.9.0 claims against the code. Every confirmed finding is fixed; the claims that did not reproduce were dropped instead of being "fixed". 612 tests pass (596 before, plus 9 new regression tests and 7 updated ones); `ruff`, `ruff format`, and `mypy` are clean.

### Fixed — Critical (P0)

- **Masked notes can no longer destroy stored secrets (D2-P0-2).** `PUT /api/profiles/{id}` (and the GUI write paths) now sanitise notes: helper keys (`_totp_raw`) are dropped, masks/placeholders never overwrite an envelope, and a genuinely new plaintext value is encrypted in the active mode before it reaches disk.
- **`_totp_raw` is no longer returned by listings (D2-P0-1).** `decrypt_notes(reveal=False)` (API/GUI listing) never injects the live 2FA seed; only `reveal_notes()` used by the automated login flow does.
- **Proxy credentials are protected everywhere (D2-P0-3).** API responses mask `password`, `raw` (the `user:pass@` part) and `rotation_url`; `save_profiles()` encrypts those three fields at rest in every mode except `plain`, and `load_profiles()` / bundle import decrypt them back. The write path treats an echoed mask as "keep the stored value".

### Fixed — Important (P1)

- **Local-only request guard (D2-P1-1).** CORS now reflects exactly the configured local ports (8899/3000 plus `--port`) instead of any port with credentials; a new middleware rejects non-local `Host` and non-local/cross-port `Origin` with `403` (including the WebSocket `/ws/events`), and an optional `NAZAK_API_TOKEN` env var can additionally require `X-API-Key` on `/api` and `/v1.0`.
- **Rotation URL SSRF/local-read is closed (D2-P1-2).** `POST /api/profiles/{id}/rotate-proxy` accepts only `http(s)` targets whose resolved addresses are public, refuses redirects, and answers with a generic `400`/`502` instead of echoing resolution errors.
- **Chrome flag / file-URL injection is refused (D2-P1-3).** `custom_url` values starting with `-` or using `file:`/`data:`/`javascript:`/`blob:`/`vbscript:` are rejected with `400`, and `build_chrome_args()` applies the same validation for GUI/CLI callers.
- **`PUT` merges instead of replacing (D2-P1-4).** `proxy`, `fingerprint` and `google` are merged field-by-field against the stored profile: partial bodies keep proxy credentials, timezone, GPU strings, seeds and notes instead of resetting them to model defaults.
- **Bulk cookie export requires an explicit scope (D2-P1-5).** `POST /api/cookies/bulk-export` with a missing/empty `profile_ids` returns `400`; profile bundles are built in a temp file and deleted right after the response instead of accumulating credential copies in `data/profiles/`.
- **The web modal no longer stamps one GPU on every profile (D2-P2-1).** It sends the stored WebGL strings when editing and omits them when creating; the API fills an omitted `fingerprint.webgl_*` with a freshly generated GPU.

### Fixed — Fingerprint coherence & honesty (D2-P2)

- **`navigator.deviceMemory` is quantized** to the Device Memory spec set `{1,2,4,8}` (the stored value stays in GB for the UI).
- **`audio_noise_seed` is random again** instead of a constant `0.000001` for every hand-built profile.
- **WebGPU architecture is derived from the GPU model number** (RTX 40xx/30xx/20xx, GTX legacy, RDNA generations) instead of a `"40" in renderer` substring.
- **`ua_full_version` comes from the profile's user agent / app version**, so `userAgentData.fullVersions` cannot disagree with `getHighEntropyValues()`; the `133.0.0.0` fallback is only used when no version is present.
- **`clone_profile()` generates a new device identity** (UA, platform-consistent GPU, screen, cores, RAM, media ids, noise seeds) while keeping timezone, language and shield toggles.
- **`passphrase` mode without a passphrase is rejected** (`SecretsError` in `set_current_mode()`/`encrypt_secret()`); the notes/proxy write path still succeeds but logs the degraded state instead of silently pretending the mode is active.

### Changed

- `FastAPI(version=...)` now reports `nazak.__version__` (the OpenAPI `/docs` page advertised 1.8.0).
- `requirements.txt` and `pyproject.toml` agree on `pytest>=7.4.0` (matching `minversion` and the installed tree).
- API reference documents the local-only access policy, the merge/launch semantics, the export scope rule and the rotation URL policy.

### Not reproducible (no code changed)

- The claimed pytest collection failure (`AttributeError: __spec__`) and the "596 failing tests" report: the suite runs clean (`596 passed` before this round, `612 passed` after). The local `pytest-of-pasha` temp ACL problem is environmental; tests use `--basetemp`.
- XSS in `app.js` (values go through `esc()`), path traversal in `_validate_id`/`validate_pid`, and DPAPI envelope integrity before write-back.

## v1.9.0 — Audit Remediation & Honesty Release (2026-09-25)

Deep mechanical audit of the v1.8.0 feature claims against the actual code, followed by a full remediation of every confirmed defect. 596 tests pass; `ruff`, `ruff format`, and `mypy` are clean.

### Fixed — Critical (P0)

- **Stealth now actually loads on modern Chrome.** Branded Chrome 137+ silently ignores `--load-extension`, which meant the entire stealth extension (18 shield sections) and its proxy-auth worker never executed. Stealth is now applied through the Chrome DevTools Protocol by a new persistent injector (`nazak/core/cdp_injector.py`): `Page.addScriptToEvaluateOnNewDocument` (stealth.js), `Emulation.setTimezoneOverride`, `Emulation.setUserAgentOverride` with Client-Hints rebuilt from the *real* running Chrome version, `Runtime.addBinding` for synchronizer gestures. The extension remains a fallback for Chromium builds.
- **Authenticated proxies work again.** `Fetch.enable` was issued without `handleAuthRequests`, so 407 challenges never reached the credential handler (previously masked by the broken extension path). Verified live against a 407-challenging proxy: challenge answered, page loads.
- **Action Synchronizer replicates for real.** The `mirror_navigation` "replication" was a `GET /json` tab probe; gesture mirroring was non-existent (a lost `_mirror_one` method crashed the mirror pump with `NameError`). Navigation now executes `page.goto` on workers through a single-threaded command pump (Playwright thread affinity respected), gestures are mirrored with coordinate jitter (`coordinate_jitter_px`) and micro-delays, and `stop_session` no longer tears down CDP sessions from a foreign thread. Live-verified: worker navigates and applies a mirrored scroll.
- **Warmup executes real actions.** Scenario steps previously degenerated into `asyncio.sleep` (and no-oped entirely when the browser was already running). Steps now navigate, scroll, and wait via CDP on the running profile; GUI launches the executor in a worker thread with honest progress instead of fake completion chips.
- **Autoposter reports the truth.**
  - Video uniqueizer no longer returns `success=True` with a plain byte copy when FFmpeg is missing or an encode fails (partial outputs are deleted); `batch_uniquify` docstring matches its real sequential behavior.
  - YouTube upload no longer fabricates `https://youtube.com/shorts` — it polls up to ~20 s for the real published URL and honestly returns `None` with a "check YouTube Studio" notice when it cannot capture it.
  - `"not logged in"` moved from retryable to manual-action errors (no more pointless triple retries).
  - `POST /api/autopost/launch` no longer writes a garbage `DEMO_MP4_HEADER` blob: a real source path is required (400 otherwise) or `"demo": true` generates a genuine playable ffmpeg test clip.
- **Proxy passwords are masked in API responses.** `GET /v1.0/browser_profiles` and mass-generate responses now return `"password": "***"` instead of plaintext credentials (API_REFERENCE example updated).

### Fixed — Important (P1)

- **Linux fingerprints no longer leak Windows GPU strings** — Linux profiles previously received `ANGLE (... Direct3D11 ...)` presets; new Mesa/OpenGL presets (NVIDIA, AMD radeonsi, Intel) and a Linux kernel `platformVersion` are used instead.
- **History seeder realism**: repeated visits to the same URL no longer share an identical timestamp (visits spread 2 h–3 d apart), transitions use real Chromium `PageTransition` constants (`LINK=0`, `TYPED=1`, `RELOAD=8`, chain flags), and `from_visit` chains multi-visit sequences instead of hardcoded `0`.
- **Test isolation**: test runs redirect all data into a temp dir via `NAZAK_DATA_DIR` (`tests/conftest.py`) — the production `data/` folder is never mutated by tests.

### Added

- `tests/live/` opt-in live suite (`pytest -m live`) covering real Chromium stealth application and synchronizer replication; deselected by default.
- Regression tests for the `handleAuthRequests` fix, proxy-password masking, demo-flag launch semantics, Linux GPU purity, seeder timestamp/transition quality, and the honest uniqueizer contract.

### Changed

- Version metadata unified at 1.9.0 (`pyproject.toml`, `nazak/__init__.py`, `version_info.txt`, `installer.iss`, `build_exe.py`).
- `README.md` / `docs/API_REFERENCE.md` synchronized with actual behavior (CDP timezone/UA overrides, WS event catalog, Dolphin masking, autopost `demo` flag, 596-test count).

## v1.8.0 — Enterprise Anti-Detect & Organic Profile Seeder (2026-09-22)

Native function cloaking, WebGPU/font/speech shields, canvas & audio noise, organic profile history seeder, FFmpeg video uniqueizer, dynamic version synchronization across build artifacts.

## v1.7.0 (2026-09-21)

Manifest V3 extension architecture, asyncBlocking proxy authentication, DevToolsActivePort handshake hardening, secrets storage modes (plain/DPAPI/passphrase).

## Earlier releases

See the [GitHub Releases page](https://github.com/wwewtech/nazak-browser-studio/releases) for v1.6.0 and older (v1.5.0 Dolphin parity, v1.4.1 modern installer, v1.3.0+).
