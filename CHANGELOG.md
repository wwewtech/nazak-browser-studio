# Changelog

All notable changes to Nazak Browser Studio are documented here. For the full feature set see [README.md](README.md), the [REST API reference](docs/API_REFERENCE.md) and the [CLI reference](docs/CLI_REFERENCE.md).

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

- **`profile get` masks secrets by default.** Прокси-пароль, `account_password` и `totp_secret` в `google.notes` больше не попадают в stdout/логи агента: вывод маскируется (`***`, `ab...yz`), открытый текст — только по явному `--reveal` (или `NAZAK_REVEAL=1`). Ранее `model_dump()` печатал всё как есть, а хелпер `mask_proxy_dict` был мёртвым кодом.
- **`account totp` больше не врёт.** Команда вызывала `decrypt_notes(reveal=False)` (маска) и отдавала `{"success": true, "totp_code": "000000"}` с exit 0. Теперь секрет раскрывается через `reveal_notes()`, а `generate_totp_rfc6238()` бросает `ValueError` вместо фиктивного кода (обновлён и его тест).
- **`@file` и `--out` перестали быть произвольным доступом к ФС.** `@path` с опечаткой — это ошибка ввода (`exit 2`), а не молчаливая подстановка строки `"@path"` в парсер; чтение ограничено 16 МБ, каталоги отклоняются. `--out` не перезаписывает существующий файл без `--force`/`--yes`.
- **`account login --profile <id>` не логинится в чужой аккаунт.** Раньше совпадение искалось подстрокой по имени/email, а при промахе молча брался первый Google-профиль и публиковалось видео. Теперь — только точный id/email, иначе остановка без публикации.
- **Живой TOTP-код больше не печатается.** Убраны `print(... {code} ...)` в `cli_auto_login_and_upload.py` и подстановка кода в прогресс `account_provisioner.automate_google_login` (в `--json` режиме этот stdout уходил в stderr — то есть в логи агента/CI).
- **Легаси-поток логина больше не пишет фейковый MP4.** Вместо `b"DEMO_MP4_HEADER" + b"0"*1024` клип генерируется через `core.video_uniquifier.generate_demo_clip()` (тот же честный генератор, что и в API), и «PUBLISHED SUCCESSFULLY» печатается только когда ссылка на видео реально найдена.
- **Пароли аккаунтов раскрываются для логина через `reveal_notes()`** (режимы dpapi/passphrase работают), а notes записываются обратно из исходного (зашифрованного) JSON, чтобы расшифрованный текст не попал на диск.

### Fixed — честность статусов

- **Instagram-аплоадер возвращает ошибку, если публикация не подтверждена.** Раньше шаги были под `if is_visible()`, и при провале возвращалось `True` с выдуманным `https://www.instagram.com/`. Теперь нужно подтверждение (ссылка на пост или тост об успехе), иначе `publish-uncertain`.
- **Ретрай после клика «Publish»/«Share» запрещён** (`core/publish_status.py`): повторный прогон = дубль публикации. Также `403` убран из списка ретраибельных ошибок (это блок/отказ, а не сбой сети).
- **Очередь не оставляет «зависших» job'ов и браузеров.** Неожиданное исключение в батче больше не оставляет `status="uploading"` и профиль `RUNNING`: job помечается failed, поднятые очередью браузеры закрываются. `cancel_all` не убивает сессии, которые очередь не открывала.
- **`normalize_upload_platform` регистронезависим** (`"Instagram_Reels"` больше не уезжает на YouTube).
- **Warmup:** неизвестное действие возвращает `False` (а не «успех»), `dwell`/`human_scroll`/`watch_youtube` клампятся по времени, навигация проверяет схему URL (`sanitize_launch_url`) и отказывает `file://`.

### Security — API / развёртывание

- **Сервер отказывается стартовать на не-loopback хосте без `NAZAK_API_TOKEN`** (`enforce_exposure_policy`, вызывается из `main.py` для GUI и web режимов). Локальный solo-сценарий (`127.0.0.1`) не меняется: токен не нужен. Docker/compose теперь передают `NAZAK_API_TOKEN` и документируют, что публикуемый порт виден на всех интерфейсах.
- **`/docs`, `/redoc`, `/openapi.json` больше не обходят Host-проверку** (исключена только `/static`).
- **CSRF-щит по `Sec-Fetch-Site: cross-site`** для HTTP и WebSocket: изменяющие состояние `GET`-эндпоинты Dolphin-паритета больше нельзя дёрнуть подгрузкой с чужого сайта без `Origin`.
- **`Host: testserver` принимается только в тестах** (`NAZAK_ALLOW_TEST_HOST`, выставляется `tests/conftest.py`), а не в проде.
- **Сравнение `X-API-Key` — `hmac.compare_digest`** вместо `==`.
- **`POST /api/autopost/uniquify` и `POST /api/autopost/launch`** принимают только существующий обычный файл с медиа-расширением (`resolve_media_source`) — произвольный путь к системному файлу больше не уходит в ffmpeg.
- **`rotate-proxy` пиннит соединение к проверенному IP** (`_PinnedHTTP(S)Connection` + `_rotation_target`): устранена DNS-гонка «сначала публичный адрес, потом приватный» (TOCTOU) при сохранённом фильтре публичных адресов и запрете редиректов.

### Fixed — web / GUI

- **DOM-XSS в диагностике закрыт и проверен в реальном браузере.** `health.ip/country/city` (значения приходят из гео-API по открытому HTTP через прокси пользователя) экранируются через `escapeHtml`; `p.id` в inline-обработчиках тоже экранирован; ссылка на видео рендерится только для `http(s)`-схемы. Проверка: новый live-тест `tests/live/test_dashboard_xss_live.py` гоняет настоящий Chromium против живого Web Studio, подменяет ответы `/api/profiles` и `/api/profiles/{id}/check` вредоносной нагрузкой (`</span><img src=x onerror=…>`) и падает, если скрипт исполнился. Дифференциальный контроль: тот же образ с откатанной на до-фиксовую строку `app.js` — тест **падает** (`country=1, city=1, ip=1`, инжектированный код вычитал 323 байта из `/api/security/secrets-mode`), на исправленном коде — **проходит**. Поля, которые были экранированы и раньше (`isp`, `error_message`), в контроле не срабатывают.
- **GUI:** `isRunning()`-guard для `ProxyCheckWorker`/`CheckAllProxiesWorker` (повторный клик терял ссылку на живой `QThread`), ротация IP вынесена в `ProxyRotateWorker` (главный поток Qt больше не блокируется на 8 с), поле парольной фразы очищается после применения.

### Fixed — зависимости, качество, честность обработки ошибок

- **`requirements.txt` синхронизирован с `pyproject.toml`:** добавлены `psutil` и `cryptography` (код их импортирует), а также `pytest-timeout` — без него документированная команда `python -m pytest tests -q` падала с `unrecognized arguments: --timeout=30`.
- **`mypy`: включены все ранее подавленные коды ошибок** (`disable_error_code = []` вместо 12 отключённых категорий, включая `arg-type`, `call-arg`, `attr-defined`, `assignment`, `index`) — найденные 16 ошибок исправлены, конфигурация снова зелёная.
- **Неиспользуемый флаг `_HAS_CRYPTOGRAPHY` теперь работает:** режим `passphrase` без пакета `cryptography` даёт понятный `SecretsError`, а не `NameError` в недрах KDF.
- **Fail-open шифрования секретов логируется как `ERROR`** (значение по-прежнему не блокирует запись, но больше не «тихое»).
- **Парсер аккаунтов не калечит пароли:** email валидируется строже (разделитель внутри email больше не склеивает поля), а пароль, содержащий разделитель (`p@ss:w0rd`), восстанавливается, если в строке есть base32-сид 2FA.
- **`process_monitor`** больше не глотает исключения молча (debug-лог вместо `pass`).
- **`format_video_metadata`** аннотирован `dict[str, Any]` — прежняя `dict[str, str]` противоречила фактическому возврату с `tags: list[str]`.

### Added

- `nazak/core/publish_status.py` — общий контракт «публикация не подтверждена» для загрузчиков и очереди.
- `core.video_uniquifier.generate_demo_clip()` — единый честный генератор демо-клипа для API и CLI.
- Глобальный флаг `--reveal` + env `NAZAK_REVEAL`; `--force` для `cookie export`, `cookie bulk-export`, `profile bundle-export`.
- `enforce_exposure_policy(host)` в `nazak/api/server.py`.
- Тесты: `tests/test_round3_fixes.py` (29) и `tests/test_web_ui_injection_guards.py` (5).

### Fixed — Docker-обвязка (проверено на реальном Docker 29.8.2)

- **`Dockerfile` не собирался: база уехала в trixie.** `docker run --rm python:3.11-slim cat /etc/os-release` → `Debian GNU/Linux 13 (trixie)`, а в списке apt были имена из bookworm — `libgl1-mesa-glx`, `libglib2.0-0`, `libatk1.0-0`, `libatk-bridge2.0-0`, `libcups2`, `libasound2` в trixie отсутствуют (подтверждено сервисом Debian madison и воспроизведено сборкой: `E: Package 'libgl1-mesa-glx' has no installation candidate`). База закреплена как `python:3.11-slim-trixie`, имена заменены на `libgl1` и `…t64`-варианты, неиспользуемый `curl` убран. После правки **`docker build` проходит (exit 0)**, `hadolint 2.15.1` → exit 0.
- **Добавлен `.dockerignore`.** Без него `COPY . .` клал в слои образа локальные `data/profiles.json` (пароли и 2FA-сиды аккаунтов в режиме `plain`), cookie/session-файлы профилей и `.git`. Проверено в собранном образе: `ls -a /app` не содержит ни `data`, ни `.git`. Runtime-данные приходят через bind-mount `./data:/app/data`.
- **`docker-compose.yml` больше не выставляет API в сеть.** Только loopback (`docker compose config` → `host_ip: 127.0.0.1`), `NAZAK_API_TOKEN` обязателен (`${NAZAK_API_TOKEN:?…}` — без переменной compose падает с понятным сообщением, exit 1), устаревший `version: '3.8'` убран, добавлен `.env.example`.
- **Новая CI-джоба `docker.yml`** (при изменениях Docker-файлов и по `workflow_dispatch`): `docker compose config -q`, настоящий `docker build`, проверка отказа старта без токена, затем HTTP-контракт (`401` без ключа, `200` с ключом, `403` на чужой `Host`/`Origin`/`Sec-Fetch-Site: cross-site`). Проверена `actionlint 1.7.12` (exit 0).
- **Проверено в реальном Docker:** сборка образа; зависимости внутри образа (`deps-ok 1.10.0 7.2.2 50.0.2` — nazak/psutil/cryptography); отказ старта без токена (exit 1 + текст про `NAZAK_API_TOKEN`); весь HTTP-контракт из контейнера; веб-дашборд `200`; `docker compose up -d --build` → `Up`, `127.0.0.1:8899->8899/tcp`, `401`/`200` через опубликованный порт, `docker compose down` без остатка. Итого 16/16 проверок контейнера.

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
