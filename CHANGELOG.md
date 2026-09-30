# Changelog

All notable changes to Nazak Browser Studio are documented here. For the full feature set see [README.md](README.md) and the [REST API reference](docs/API_REFERENCE.md).

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
