# Changelog

All notable changes to Nazak Browser Studio are documented here. For the full feature set see [README.md](README.md) and the [REST API reference](docs/API_REFERENCE.md).

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
