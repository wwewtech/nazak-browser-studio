# Аудит Nazak Browser Studio — раунд 3: дыры, расхождения и что осталось неисправленным

> **Статус: исправлено (раунд 3 закрыт).** Все находки §3–§6 закрыты в коде, кроме одной
> сознательно отложенной (R3-15 остаётся как «сделано»: коды mypy включены, 16 ошибок
> исправлены). Что именно сделано — в `CHANGELOG.md` («Unreleased — Round-3 Audit
> Remediation»). Тесты: `tests/test_round3_fixes.py` (29) и
> `tests/test_web_ui_injection_guards.py` (5); `ruff check`, `ruff format --check` и `mypy`
> (со **всеми** включёнными кодами ошибок) — чистые. Полный прогон в этом окружении:
> **659 passed, 9 failed, 0 errors**, где все 9 падений — отсутствие `qfluentwidgets` (6)
> и `playwright` (4) в окружении, то есть ровно те же 9, что падали до правок.
> Отчёт оставлен как исторический документ аудита: сами находки ниже не переписаны.
> Позже был отдельно проверен Docker-контур — см. §10 (найдена и исправлена поломка сборки).

Документ составлен по фактическому чтению кода рабочей копии
`C:\Users\User\Desktop\work\nazak-browser-studio` и по истории git (69 коммитов, `git rev-list --count HEAD` → 69).
Каждое утверждение снабжено ссылкой `файл:строка`. Где проверка не удалась — это написано прямо.

---

## 0. Методика и границы проверки

Что реально выполнялось (не только чтение):

| Проверка | Команда / способ | Результат |
|---|---|---|
| Утечка секретов в CLI | свой профиль в `NAZAK_DATA_DIR`, затем `python -m nazak.cli profile get prof_v1 --json` | секреты в открытом виде, exit 0 |
| TOTP из CLI | `python -m nazak.cli account totp prof_v1 --json` | `totp_code: "000000"`, exit 0 |
| Локальный guard API | `starlette.testclient.TestClient(app)` с разными `Host`/`Origin` | см. §3.1 |
| Экспорт cookie без ключа | `GET /api/profiles/prof_v1/cookies/export` | 200 + httpOnly-cookie в теле |
| Запуск тестов | `python -m pytest tests -q` (как в `README.md:233`) | ошибка запуска, см. §6.1 |
| Полный прогон тестов | `pytest tests -o addopts=""` (temp-каталог внутри workspace) | `9 failed, 491 passed, 149 warnings, 133 errors in 196.53s` |
| Секреты в истории git | `git log --all -p` (патч 7 317 628 байт, 69 коммитов) + поиск шаблонов ключей | см. §7 |
| Зависимости-транзитивность | `importlib.metadata` Requires-Dist по 8 установленным пакетам | см. §6.2 |
| Статический счёт тестов | `Select-String '^\s*def test_'` по `tests/**/*.py` | 572 определения, 55 файлов |

Ограничения окружения (важно для честности выводов):

* `PyQt6-Fluent-Widgets` (`qfluentwidgets`) и `playwright` в этом окружении **не установлены**, `cryptography` и `psutil` установлены. Поэтому часть тестов падает на импорте — это не дефект кода.
* DSH-песочница запрещает создавать подкаталоги внутри каталогов, созданных `tempfile.mkdtemp`; из-за этого 133 ошибки прогона — `PermissionError` на временных каталогах pytest, а не дефекты проекта.
* Docker/Docker Compose здесь не запускались: вывод о сетевой экспозиции контейнера опирается на чтение `Dockerfile`/`docker-compose.yml` и официальную документацию Docker (ссылка в §3.2).
* Второй пользователь Windows для проверки межпользовательского доступа не создавался.
* Реальный браузер для проверки CSRF/XSS не запускался.

---

## 1. Сводка находок

| ID | Серьёзность | Область | Суть | Как проверено |
|---|---|---|---|---|
| R3-01 | High | API | API не аутентифицирован; единственная защита — заголовки `Host`/`Origin` от клиента | код + запуск |
| R3-02 | High | Развёртывание | `Dockerfile` поднимает API на `0.0.0.0`, `docker-compose.yml` публикует порт на все интерфейсы, токен не задан | чтение + док. Docker |
| R3-03 | High | CLI | `profile get` печатает пароль прокси и пароль/2FA-сид аккаунта в открытом виде | запуск |
| R3-04 | High | CLI | `account totp` возвращает `000000` с `success: true` и exit 0 | запуск |
| R3-05 | High | Web UI | DOM-XSS: `health.ip/country/city` вставляются в `innerHTML` без экранирования; источник — ответ стороннего сервиса по HTTP через прокси | чтение обоих концов потока |
| R3-06 | High | Uploader | Instagram-аплоадер возвращает `success=true` и выдуманный URL, если публикация не произошла | чтение |
| R3-07 | High | Secrets | Режим хранения секретов по умолчанию — `plain`; пароли и TOTP-сиды маркетплейс-аккаунтов лежат в `data/profiles.json` открытым текстом | чтение + запуск |
| R3-08 | Medium | CLI/сценарий | `account login --profile <id>` при несовпадении id молча логинится в **другой** аккаунт и публикует видео как Public | чтение |
| R3-09 | Medium | CLI | Легаси-поток логина пишет фальшивый `DEMO_MP4_HEADER`-файл и загружает его на YouTube, затем печатает «PUBLISHED SUCCESSFULLY» | чтение |
| R3-10 | Medium | CSRF | Изменяющие состояние эндпоинты зарегистрированы как `GET` | код + запуск + MDN |
| R3-11 | Medium | Uploader | Ретрай неидемпотентной публикации → возможная повторная публикация того же видео | чтение |
| R3-12 | Medium | API | `/api/autopost/uniquify` принимает произвольный абсолютный путь к файлу | чтение |
| R3-13 | Medium | API | SSRF-гонка (`TOCTOU`) в `rotate-proxy`: имя резолвится дважды | чтение |
| R3-14 | Medium | Сборка | `python -m pytest tests -q` из README не работает: `addopts` требует `pytest-timeout` | запуск |
| R3-15 | Medium | CI | `mypy`-гейт отключает 13 категорий ошибок (включая `arg-type`, `call-arg`) | чтение конфига |
| R3-16 | Medium | Зависимости | `requirements.txt` не содержит `psutil` и `cryptography`, которые импортирует код | чтение + метаданные |
| R3-17 | Low | API | `testserver` в списке «локальных» хостов; сравнение API-ключа через `==` | запуск/чтение |
| R3-18 | Low | API | `/docs`, `/openapi.json`, `/static` полностью обходят guard | чтение |
| R3-19 | Low | Web UI | `p.id` подставляется в inline-обработчики без экранирования (сейчас не эксплуатируется) | чтение |
| R3-20 | Low | Web UI | `href` из DOM YouTube без проверки схемы | чтение |
| R3-21 | Low | GUI | Второй клик «Проверить» перезаписывает ссылку на работающий `QThread` | чтение |
| R3-22 | Low | GUI | Блокирующий `urlopen(timeout=8)` в главном потоке Qt | чтение |
| R3-23 | Low | Секреты | `_HAS_CRYPTOGRAPHY` вычисляется, но нигде не проверяется | grep |
| R3-24 | Low | Секреты | Fail-open при недоступном шифровании: значение остаётся открытым, только `warning` в лог | чтение |
| R3-25 | Low | Статусы | Зависший job остаётся `uploading`, профиль — `RUNNING`; неизвестное действие warmup = успех | чтение |
| R3-26 | Low | Парсер | Пароль с разделителем обрезается, остаток уходит в TOTP-сид | чтение |
| R3-27 | Low | GUI | Парольная фраза остаётся в поле виджета; в таблице показываются 7 символов 2FA-сида | чтение |
| R3-28 | Low | Warmup | `dwell`/`human_scroll` без ограничения длительности; сценарий приходит из API | чтение |
| R3-29 | Low | Процесс/репозиторий | Проглатывание исключений в мониторе процессов; нет `SECURITY.md` и сканера зависимостей | чтение + листинг |

Расхождения документации/коммитов — отдельно в §6.

---

## 2. Что показывает история коммитов

Факты из `git log` (69 коммитов, авторские даты 2026-08-23 … 2026-10-03):

1. Самоаудит в проекте проводился минимум трижды:
   * `948275c` — «add comprehensive English documentation and audit report»;
   * `838ccf4` — «add comprehensive audit regression suite and 100 deep defect tests»;
   * `d6ba7e6` — «remediate P0/P1 audit findings across stealth, synchronizer, autoposter, secrets, fingerprint and seeder»;
   * `f996dfb` — «remediate round-2 findings … (D2-P0-1/2/3, D2-P1-1…5, D2-P2-1/2)».
2. Отчёты об аудите **удалены** из репозитория: `fa503f7` — «Remove superseded work documents (audit report, deep-analysis plan, remediation progress): all findings are fixed…». Единственный оставшийся документ — `docs/DEEP_AUDIT_ROUND2.md`, и его ссылки на строки устарели (см. §6.12). То есть прослеживаемого бэклога безопасности в репозитории сейчас нет.
3. `nazak/cli_cmds/*` добавлены в `98a4042` («ADD CLI!») и расширены в `c0fa3d1` (v1.10.0: `17 files changed, 867 insertions(+)`). Именно там находятся три подтверждённых High-дефекта R3-03, R3-04, R3-08/R3-09 — то есть на самой молодой и менее всего отревьюенной поверхности.
4. `nazak/cli_auto_login_and_upload.py` существует с первого релиза (`7595011`) и **пережил** все раунды аудита: фальшивый MP4 (R3-09) и печать живого TOTP-кода там остались.
5. Коммит `d6ba7e6` утверждает: «Autoposter: … POST /api/autopost/launch requires a real source or demo=true (generates a genuine ffmpeg clip, **no DEMO_MP4_HEADER blob**)». Это верно только для API-пути: строка `b"DEMO_MP4_HEADER"` по-прежнему присутствует в `nazak/cli_auto_login_and_upload.py:265` (см. §5/R3-09).

---

## 3. Высокие находки

### R3-01. Локальный API не аутентифицирован; guard опирается только на заголовки клиента

**Файлы:** `nazak/api/server.py:239-309`, `nazak/api/server.py:283-287`, `nazak/config.py:40`

```python
# server.py:283-287
def _is_api_token_valid(request_headers) -> bool:
    expected = os.environ.get(_API_TOKEN_ENV)
    if not expected:
        return True
    return request_headers.get("x-api-key") == expected
```
```python
# server.py:296-308
    if not _is_local_host(request.headers.get("host")):
        return JSONResponse(status_code=403, ...)
    origin = request.headers.get("origin")
    if origin and not _is_local_origin(origin):
        return JSONResponse(status_code=403, ...)
    if path.startswith(("/api", "/v1.0")) and not _is_api_token_valid(request.headers):
        return JSONResponse(status_code=401, ...)
```

Проверено запуском (`TestClient`, свежий `NAZAK_DATA_DIR`):

```
Host='127.0.0.1'            -> HTTP 200
Host='testserver'           -> HTTP 200
Host='evil.example.com'     -> HTTP 403
Origin=https://evil.example.com -> 403
Origin=http://localhost:3000     -> 200
GET /v1.0/browser_profiles/prof_v1/stop -> 200        (без X-API-Key)
GET /api/profiles/prof_v1/cookies/export -> 200
   {'format': 'json', 'cookies': [{'name': 'SID', 'value': 'secret-session-value',
     'domain': '.google.com', 'path': '/', 'httpOnly': True, 'secure': True}], ...}
X-API-Key needed? NAZAK_API_TOKEN = None
```

Дополнительно: в проекте **нет** ни одной проверки IP клиента — поиск по `*.py` шаблонов `request.client|client.host|remote_addr|X-Forwarded|trusted` не даёт совпадений.

**Почему это дыра, а не теория:** решающее значение имеет только заголовок `Host`, который целиком контролирует клиент. Пока сервер слушает только loopback (`config.py:40`), это ограничивает доступ процессами этой машины; при любом пробросе порта наружу фильтр перестаёт что-либо значить (§R3-02). Отсутствие аутентификации задокументировано (`docs/API_REFERENCE.md:8`), поэтому это осознанный компромисс, а не случайность — но его последствия в коде не ограничены: API выдаёт **сессионные cookie всех профилей** (`server.py:1154-1167`, `1130-1151`), собирает `.nazak`-бандл со `data/` профиля (`server.py:967-994`), запускает браузеры и меняет данные профилей.

**Влияние:** любой процесс на машине (в т.ч. запущенный другим пользователем Windows — loopback не изолирован по пользователям; на второй учётной записи я это не проверял) может выгрузить cookie Google/YouTube, то есть забрать аккаунты фермы, и управлять браузерами.

**Что сделать:** включить токен по умолчанию (генерировать при первом старте и класть в `data/`, GUI подставляет его автоматически) либо перейти на Unix-socket / named pipe; отдельно — ограничить выдачу cookie-экспорта отдельным подтверждением.

### R3-02. Docker-развёртывание из репозитория выставляет неаутентифицированный API в сеть

**Файлы:** `Dockerfile:36-38`, `docker-compose.yml:8-13`

```dockerfile
EXPOSE 8899
CMD ["python", "-m", "nazak.main", "--mode", "web", "--host", "0.0.0.0", "--port", "8899"]
```
```yaml
    ports:
      - "8899:8899"
    environment:
      - PYTHONUNBUFFERED=1
```

`NAZAK_API_TOKEN` в compose не задаётся (переменных всего одна). Docker документирует: «When a port is published, it's published to all network interfaces by default» ([Publishing and exposing ports](https://raw.githubusercontent.com/docker/docs/f63001e0752a7337403b2e00fa5ea34e7370048d/content/get-started/docker-concepts/running-containers/publishing-ports.md), проверено 2026-10-03).

**Влияние:** любой, кто дотянется до порта 8899, отправляет `Host: 127.0.0.1`, проходит guard (это проверено выше) и получает весь API: выгрузка cookie, экспорт бандлов, запуск браузеров, `source_video_path` (§R3-12). Полная цепочка на живом Docker мной не воспроизводилась, но каждый её шаг проверен отдельно.

**Что сделать:** в `Dockerfile`/`docker-compose.yml` — `--host 127.0.0.1` (или обязательный `NAZAK_API_TOKEN` + отказ стартовать при `0.0.0.0` без токена), добавить `USER` (сейчас контейнер работает от root — в `Dockerfile` нет директивы `USER`).

### R3-03. `nazak.cli profile get` печатает пароль прокси и пароль/2FA-сид аккаунта

**Файл:** `nazak/cli_cmds/profiles.py:190-203`

```python
def cmd_get(args, opt: GlobalOptions) -> int:
    if opt.server:
        return _via_server(opt, "GET", f"/api/profiles/{args.profile_id}")
    pm, bl = get_managers()
    p = pm.get_profile(args.profile_id)
    ...
    d = p.model_dump()
    ...
    emit({"success": True, "profile": d}, opt)
```

`BrowserProfile` не исключает поля (`nazak/models/profile.py:166` `proxy`, `:168` `google`), `ProxyConfig` хранит `password`/`raw` как обычные поля (`nazak/models/proxy.py:40-43`), а при загрузке прокси-поля расшифровываются в память (`nazak/core/profile_manager.py:494`).

Проверено запуском (профиль `prof_v1`, режим `plain`):

```
exit code: 0
"password": "pxSecret123",
"notes": "{\"account_email\": \"farm.account@gmail.com\", \"account_password\": \"AccPass456!\",
          \"totp_secret\": \"JBSWY3DPEHPK3PXP\", \"_secrets_mode\": \"plain\"}"
```

Хелпер маскирования `mask_proxy_dict` (`nazak/cli_cmds/common.py:230-241`) **нигде не вызывается**: поиск по репозиторию даёт единственное совпадение — само определение.

**Влияние:** пароли и TOTP-сиды попадают в stdout, в логи CI/агентов и в `--json`-потоки. Маскирование, которое есть в API (`server.py:330-370`), в CLI не подключено.

**Что сделать:** перед `emit` применять `decrypt_notes(reveal=False)` + `mask_proxy_dict`, а полный вывод отдавать только по явному `--reveal`.

### R3-04. `nazak.cli account totp` возвращает неверный код и рапортует об успехе

**Файлы:** `nazak/cli_cmds/autopost_accounts.py:378-399`, `nazak/core/secrets_store.py:390`, `nazak/core/account_provisioner.py:39-64`

```python
# autopost_accounts.py:387-398
    try:
        revealed = decrypt_notes(notes)          # reveal по умолчанию False
    except Exception:
        revealed = notes
    secret = revealed.get("totp_secret", "")
    if not secret or secret.startswith("<encrypted"):
        return emit_error(...)
    try:
        code = generate_totp_rfc6238(secret)
    ...
    emit({"success": True, "profile_id": p.id, "totp_code": code}, opt)
    return EXIT_OK
```
```python
# secrets_store.py:390
        result[field] = plain if reveal else mask_secret(plain)
```

Проверено запуском:

```
{ "success": true, "profile_id": "prof_v1", "totp_code": "000000" }
exit code: 0
[stderr] Error computing TOTP: Non-base32 digit found
```

**Влияние:** команда, документированная как генератор 2FA (`docs/CLI_REFERENCE.md`) и предназначенная для ИИ-агентов, всегда отдаёт нерабочий код и при этом `success: true` / exit 0. Тихая ложь вместо ошибки — это же ломает и авто-логин, если его переиспользовать.

**Что сделать:** вызывать `reveal_notes`/`decrypt_notes(..., reveal=True)`; при замаскированном значении возвращать `EXIT_CONFLICT` с явным текстом; `generate_totp_rfc6238` не должен возвращать `"000000"` — только исключение.

### R3-05. DOM-XSS в Web Studio: `health.ip/country/city` вставляются в `innerHTML` без экранирования

**Файлы:** `nazak/web/app.js:361`, `nazak/core/proxy_checker.py:102-118`, `nazak/models/health.py:40-43`

```javascript
// app.js:361 (внутри body.innerHTML = `...` на :358)
${health.ip ? `${health.ip} (${health.country || "N/A"}, ${health.city || ""})` : "IP error"}
```

Экранирование применяется рядом (`app.js:362` — `escapeHtml(health.isp)`, `:368` — `escapeHtml(health.error_message)`, `:263` — `escapeHtml(ipText)/escapeHtml(geoText)`), но не здесь.

Источник значений — сторонний сервис, опрашиваемый **по открытому HTTP через прокси пользователя**:

```python
# proxy_checker.py:102-111
geo_resp = await client.get(
    "http://ip-api.com/json/?fields=status,message,country,countryCode,regionName,city,isp,as,query,timezone,lat,lon"
)
...
        result.country = geo_data.get("country")
        result.city = geo_data.get("city")
```

Модель не ограничивает эти поля (`health.py:40-43` — обычные `str | None`). Дальше значения идут в UI двумя путями: `server.py:853-866` (ответ `POST /api/profiles/{id}/check` + `broadcast("profile_health_update")`) → `app.js:342` или WS-обработчик `app.js:71-79` → `renderDiagModalContent` (`app.js:350-371`).

**Почему это реально:** вредоносный/подменённый прокси (или MITM на этом HTTP-запросе) возвращает `country` вида `</span><img src=x onerror=...>`, и скрипт исполняется в origin `http://127.0.0.1:8899` — то есть в origin самого API. Из этого origin запросы проходят и Host-, и Origin-проверки, а значит скрипт может читать cookie-экспорт и бандлы (R3-01). Достаточно открыть модалку «Diagnostics».

**Проверено в реальном браузере (после исправления).** Отдельный live-тест
`tests/live/test_dashboard_xss_live.py` поднимает настоящий сервер, открывает дашборд в Chromium и
подменяет ответы `/api/profiles` и `/api/profiles/{id}/check` вредоносными значениями
(`</span><img src=x onerror=…>` в `ip`/`country`/`city` плюс payload, который тянет
`/api/security/secrets-mode`), после чего проверяет маркеры `window.__xss_*` по двум путям:
прямой вызов `renderDiagModalContent()` и полный UI-путь с реальным кликом по кнопке «Diagnostics».

| Запуск (один и тот же образ, отличается только `nazak/web/app.js`) | Результат |
|---|---|
| Исправленный код | **тест проходит**: маркеры `country=0, city=0, ip=0, exfil=null`, payload виден в DOM как текст (`&lt;img src=x onerror`) |
| Контроль: строка откатана на до-фиксовый вид (`${health.ip} (${health.country}…)`) | **тест падает**: `country=1, city=1, ip=1`, `exfil=323` — инжектированный скрипт исполнился и вычитал 323 байта ответа `/api/security/secrets-mode`; поля `isp` и `error_message`, экранированные и раньше, не срабатывают |

То есть фикс подтверждён исполнением, а сам тест — не «слепой»: на уязвимой версии он падает.
Запуск: `pytest -m live tests/live/test_dashboard_xss_live.py` (в образе есть Chromium; на хосте
без `playwright` тест корректно скипается).

**Что сделать:** `escapeHtml` на `health.ip/country/city` (или собрать узел через `textContent`); заодно запретить использование открытого HTTP для гео-запроса. — **сделано**: экранирование добавлено, HTTP для гео-запроса помечен как риск (отдельного решения по смене провайдера не принималось).

### R3-06. Instagram-аплоадер объявляет успех, даже если публикации не было

**Файл:** `nazak/core/instagram_uploader.py:183-222`

```python
                share_btn = self._first(page.locator("button:has-text('Share')"))
                if await asyncio.wait_for(share_btn.is_visible(), timeout=20.0):
                    await self._safe_wait(share_btn.click(), timeout=15.0, label="share button click")
                    await asyncio.sleep(5 * self.delay_scale)
                ...
                return True, published_url or "https://www.instagram.com/", None
```

Все шаги (загрузка файла, caption, Next, Share) обёрнуты в `if ... is_visible()`; если диалог не появился, исключения нет и управление доходит до `:222`, где возвращается `True` и выдуманный URL. Очередь загрузок принимает это как успех: `upload_queue.py:385-397` ставит `job.status = "published"` и рассылает «Published successfully!».

**Влияние:** оператор видит «опубликовано» там, где публикации нет; для фермы это ещё и потеря управляемости (ретраев не будет, потому что ошибки нет).

**Что сделать:** обязательная проверка результата (появление ссылки `/p/` или запись в профиле) и `return False, None, "share dialog not found"` при отсутствии подтверждения.

### R3-07. Секреты аккаунтов по умолчанию хранятся открытым текстом

**Файлы:** `nazak/core/secrets_store.py:44,282-293`, `nazak/core/account_provisioner.py:326-339`, `nazak/config.py:33`

```python
DEFAULT_SECRETS_MODE = "plain"          # secrets_store.py:44
...
    if effective_mode == "plain":       # :292-293
        return value
```
```python
# account_provisioner.py:326-339
            notes_payload = json.dumps(
                encrypt_notes(
                    {
                        "account_email": acc["email"],
                        "account_password": acc["password"],
                        "totp_secret": acc["totp_secret"],
```

Проверено запуском: после создания профиля в `data/profiles.json` лежит
`"account_password": "AccPass456!", "totp_secret": "JBSWY3DPEHPK3PXP"`.

**Влияние:** одна копия файла (бэкап, облачная синхронизация, экспорт бандла, письмо в поддержку) = полный доступ к купленным Google-аккаунтам вместе с 2FA-сидом.

**Важно для объективности:** это задокументированный выбор пользователя (`README.md:189-194`: «`plain` — Readable plaintext (**default**, zero setup)»), то есть не скрытый дефект, а небезопасное значение по умолчанию. Формулировка «пользователь сам выбирает» не отменяет того, что до осознанного выбора все секреты уже лежат в открытом виде.

**Что сделать:** при первом импорте аккаунтов явно спрашивать режим (или делать `dpapi`/`passphrase` значением по умолчанию, оставляя `plain` как явный opt-in с предупреждением).

---

## 4. Средние находки

### R3-08. `account login --profile <id>` может залогиниться в другой аккаунт и опубликовать видео

**Файлы:** `nazak/cli_cmds/autopost_accounts.py:412-414`, `nazak/cli_auto_login_and_upload.py:37-52`, `:322-333`

```python
# autopost_accounts.py:412-414
    if args.profile and not args.email:
        # передаём как email-фильтр по id через env; live_flow умеет матчить по name/id
        os.environ["GOOGLE_EMAIL"] = args.profile
```
```python
# cli_auto_login_and_upload.py:39-52
    if target_email:
        profiles = [p for p in pm.list_profiles()
                    if (target_email in p.name)
                    or (p.google and p.google.target_account_email and target_email in p.google.target_account_email)]
    if not profiles:
        existing = pm.list_profiles()
        google_profs = [p for p in existing if p.google and (p.google.notes or p.google.target_account_email)]
        if google_profs:
            profiles = [google_profs[0]]      # ← молчаливый выбор «первого попавшегося»
```

Совпадение — подстрочное (`in`), а не по id/email. Далее поток вводит пароль и нажимает «Publish» с видимостью Public (`:322-333`).

**Влияние:** опечатка в id приводит к работе с чужим (другим) аккаунтом фермы и публикации. Ошибки «профиль не найден» не будет.

**Что сделать:** матчить строго по `id`/точному email, при несовпадении — выход с кодом 1 и подсказкой; публикацию делать только по явному флагу.

### R3-09. Легаси-поток логина загружает на YouTube фальшивый MP4 и печатает ложный успех

**Файл:** `nazak/cli_auto_login_and_upload.py:259-265, 330-357`

```python
            if not video_file.exists():
                video_file.parent.mkdir(parents=True, exist_ok=True)
                video_file.write_bytes(b"DEMO_MP4_HEADER" + b"0" * 1024)
...
            await done_btn.click()
            await asyncio.sleep(6)
            ...
            print(f"🎉 PUBLISHED SUCCESSFULLY! Link: {video_url or 'https://youtube.com/shorts'}")
            ...
            return True
```

Дополнительно в этом же файле:
* строка `:187` печатает **живой** TOTP-код: `print(f"🛡️ Step 4: 2FA prompt detected! Generating current TOTP code: {code}...")`;
* строки `:80-81` читают `account_password`/`totp_secret` прямо из JSON без расшифровки, поэтому в режимах `dpapi`/`passphrase` в поля логина будет введён конверт, а не пароль;
* `cmd_account_login` в `--json`-режиме перенаправляет весь этот stdout в **stderr** (`autopost_accounts.py:419-429`), т.е. TOTP-код окажется в логах агента/CI.

**Влияние:** на аккаунт фермы уходит заведомо невалидный файл (риск для аккаунта), статус публикации — вымысел; живой одноразовый код утекает в лог.

**Что сделать:** удалить ветку с `DEMO_MP4_HEADER` (генерировать клип через ffmpeg, как в API-пути `server.py:1368-1410`), не печатать код, расшифровывать секреты через `reveal_notes`, проверять факт публикации перед «SUCCESS».

### R3-10. Изменяющие состояние эндпоинты сделаны `GET`

**Файлы:** `nazak/api/server.py:697-707` (`GET /v1.0/browser_profiles/{id}/start`), `:732-738` (`GET .../stop`), guard `:301-302`

```python
@app.get("/v1.0/browser_profiles/{profile_id}/start", ...)
...
@app.get("/v1.0/browser_profiles/{profile_id}/stop", ...)
```
```python
    origin = request.headers.get("origin")
    if origin and not _is_local_origin(origin):
```

Проверено запуском: `GET /v1.0/browser_profiles/prof_v1/stop` → 200 без каких-либо заголовков авторизации.

Origin-проверка выполняется только при наличии заголовка. MDN: «if a cross-origin `GET` or `HEAD` request is made in [no-cors mode], the `Origin` header will not be added» ([Origin header — MDN](https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Origin), проверено 2026-10-03). Следствие: сторонний сайт может тянуть `<img src="http://127.0.0.1:8899/v1.0/browser_profiles/<id>/start">` и запускать/останавливать браузеры профилей (слепой CSRF; ответ прочитать нельзя, но эффект есть). Реальный браузер я не запускал, поведение `Origin` взято из документации MDN.

**Что сделать:** перенести start/stop на `POST`; для небезопасных методов требовать `Origin` (отсутствие = отказ), а не «отсутствие = разрешено».

### R3-11. Ретрай публикации может загрузить видео повторно

**Файлы:** `nazak/core/upload_queue.py:22-31,159-161,175-196,361-368`, `nazak/core/youtube_uploader.py:213-247`

```python
RETRYABLE_UPLOAD_ERRORS = ("timeout", "temporarily unavailable", "429", "403", "rate limit",
                           "network", "session disconnected", "connection closed")
...
        return any(token in lowered for token in RETRYABLE_UPLOAD_ERRORS)
```

`upload_shorts` нажимает «Publish» (`youtube_uploader.py:216-217`) и уже потом опрашивает URL, вызывает `browser.close()` и `notify_progress` (`:220-244`). Любое исключение на этих шагах возвращает `False` (`:246-247`), а `_retryable_upload` повторит **весь** цикл до 3 раз, если текст ошибки содержит один из токенов (например, `Timeout 30000ms exceeded`).

**Влияние:** дубликаты публикаций на аккаунтах фермы. Условие — совпадение текста ошибки с токеном; безусловным это не является (что именно вернёт Playwright, я не проверял).

**Что сделать:** после успешного клика «Publish» считать попытку невоспроизводимой (`non-idempotent`), а «403» убрать из списка ретраев (см. R3-25/ниже).

### R3-12. `/api/autopost/uniquify` принимает произвольный абсолютный путь

**Файл:** `nazak/api/server.py:1354-1365`

```python
async def uniquify_videos_endpoint(req: UniquifyRequest):
    for pid in req.profile_ids:
        validate_pid(pid)
    src = Path(req.source_video_path)
    if not src.exists():
        raise HTTPException(status_code=400, detail=f"Source video not found: {req.source_video_path}")
    results = await asyncio.to_thread(video_uniquifier.batch_uniquify, src, req.profile_ids)
```

**Влияние:** оракул существования файлов (`400 Source video not found` против запуска ffmpeg) и передача произвольного локального файла в парсер ffmpeg; результат пишется в `DATA_DIR/videos/output` (`video_uniquifier.py:77-78`), траверсала там нет. Прочитать содержимое произвольного файла через этот эндпоинт мне подтвердить не удалось, поэтому «чтение файлов» я не утверждаю.

**Что сделать:** whitelist каталога (например, только `DATA_DIR/videos`) + проверка `is_relative_to`, проверка расширения/сигнатуры.

### R3-13. SSRF-гонка (`TOCTOU`) в `rotate-proxy`

**Файл:** `nazak/api/server.py:1035-1082`, `:1096-1101`

```python
    addresses = _resolve_host_ips(parts.hostname, port)   # первое разрешение имени
    ...
        if not ip.is_global:
            return "host must be a public address"
```
```python
        req = urllib.request.Request(url, headers={"User-Agent": "Nazak-Studio"})
        with _NO_REDIRECT_OPENER.open(req, timeout=10.0) as resp:   # второе разрешение имени
```

Проверка идёт по IP из первого разрешения, а `urllib` резолвит имя повторно при подключении. При DNS с чередующимися ответами (public → private) фильтр обходится. Эксплуатацию я не воспроизводил (нет управляемого DNS), факт двойного разрешения — из кода. Дополнительно требуется, чтобы атакующий мог записать `rotation_url` (через API, см. R3-01/R3-02).

**Что сделать:** резолвить один раз и подключаться по проверенному IP (например, `http.client` с `Host`-заголовком), либо использовать `ipaddress`-allowlist и пиннинг соединения.

### R3-14. Документированная команда тестов не запускается

**Файлы:** `README.md:232-238`, `pyproject.toml:150`, `pyproject.toml:52-55`, `requirements.txt:11-14`

```
addopts = "-p no:asyncio --strict-markers -ra --timeout=30 --timeout-method=thread -m 'not live'"   # pyproject.toml:150
```
`pytest-timeout` объявлен только в dev-extra (`pyproject.toml:55`), в `requirements.txt` его нет.

Проверено запуском:

```
$ python -m pytest tests -q
ERROR: usage: python -m pytest [options] [file_or_dir] [...]
python -m pytest: error: unrecognized arguments: --timeout=30 --timeout-method=thread
```

**Влияние:** «Quick Start»-путь (`pip install -r requirements.txt` → `pytest`) не работает; это же подтверждает коммит `5f7a7d4`, который добавил `pytest-timeout` в CI, но не в `requirements.txt`.

**Что сделать:** добавить `pytest-timeout` в `requirements.txt` или убрать `--timeout*` из `addopts` в `[tool.pytest.ini_options]`.

### R3-15. Гейт `mypy` отключает почти все содержательные проверки

**Файл:** `pyproject.toml:183-205`

```toml
disable_error_code = [
    "no-redef", "arg-type", "dict-item", "assignment", "index", "import-untyped",
    "override", "misc", "attr-defined", "call-arg", "call-overload", "valid-type",
]
```
При этом CI объявляет это отдельной job «Type Analysis (MyPy)» и падает при ошибке (`ci.yml:43-64`).

**Влияние:** зелёный mypy в CI не означает типовой корректности: неверные типы аргументов, присваивания, вызовы с неверными аргументами и обращения к несуществующим атрибутам подавлены. Это подтверждается и находкой R3-23 (`_HAS_CRYPTOGRAPHY` объявлен и не используется — mypy это не поймает).

**Что сделать:** сузить список, включив минимум `arg-type`, `call-arg`, `attr-defined`, и починить ошибки по модулям.

### R3-16. `requirements.txt` не содержит `psutil` и `cryptography`, которые нужны коду

**Файлы:** `requirements.txt:1-14`, `nazak/core/browser_launcher.py:18`, `nazak/models/profile.py` (через `secrets_store`), `pyproject.toml:41,47`

```
18: import psutil        # browser_launcher.py — импорт на уровне модуля, подтягивается из nazak/__init__.py
```

Проверено метаданными установленных пакетов (`importlib.metadata`, `Requires-Dist`): ни один из `fastapi 0.131.0`, `uvicorn 0.41.0`, `pydantic 2.12.5`, `httpx 0.28.1`, `requests 2.32.5`, `PySocks 1.7.1`, `PyQt6 6.11.0`, `rich 14.3.3`, `pytest 9.1.1`, `websockets 16.0` не требует `psutil` или `cryptography`. `PyQt6-Fluent-Widgets`, `pytest-asyncio`, `playwright` в этом окружении не установлены — их метаданные я проверить не смог.

**Влияние:** на чистом окружении по инструкции `README.md:208-210` приложение должно упасть на `import psutil`; `cryptography` нужен для режима `passphrase` (там `import` защищён `try/except`, но флаг не используется — R3-23). Docker-сборка использует тот же `requirements.txt` (`Dockerfile:30-31`).

**Что сделать:** синхронизировать `requirements.txt` с `pyproject.toml:34-48`.

---

## 5. Низкие находки

* **R3-17** `_LOCAL_HOSTS` включает `"testserver"` (`server.py:239`) — проверено: `Host: testserver` → 200. Ключ API сравнивается через `==` (`server.py:287`), а не `hmac.compare_digest`.
* **R3-18** Префиксы `/static`, `/docs`, `/redoc`, `/openapi.json`, `/swagger` выходят из middleware до проверок (`server.py:293-294`) — схема API и статика отдаются при любом `Host`.
* **R3-19** `p.id` без экранирования в inline-обработчиках (`app.js:244, 269, 271-289`). Сейчас не эксплуатируется: id валидируется `^[a-zA-Z0-9_\-]+$` (`server.py:325-326`, `profile_manager.py:179`). Риск появится при ослаблении правила или ручной правке `profiles.json`.
* **R3-20** `href="${escapeHtml(j.video_url)}"` (`app.js:853`) — экранирование есть, проверки схемы нет; источник — DOM YouTube Studio (`youtube_uploader.py:227`).
* **R3-21** `self.check_worker = ProxyCheckWorker(...)` без проверки `isRunning()` (`gui/views/profiles_view.py:450`); тот же шаблон с другим классом — `self.worker = CheckAllProxiesWorker(...)` (`gui/views/proxies_view.py:216-218`) — повторный клик теряет последнюю ссылку на работающий `QThread`, что для Qt заканчивается аварийным завершением. Корректный образец есть в `gui/views/warmup_view.py:249, 335`.
* **R3-22** `urllib.request.urlopen(req, timeout=8.0)` для пользовательского `rotation_url` вызывается из обработчика кнопки в главном потоке Qt (`gui/views/proxies_view.py:157, 162-170`) — UI замирает до 8 с.
* **R3-23** `_HAS_CRYPTOGRAPHY` присваивается (`secrets_store.py:37,39`) и нигде не читается (grep: только эти две строки). При отсутствии `cryptography` выбор режима `passphrase` приведёт к `NameError` вместо понятной ошибки.
* **R3-24** Fail-open при недоступном шифровании: `encrypt_notes`/`protect_proxy_fields` пишут значение открытым текстом и только логируют `warning` (`secrets_store.py:352-353, 460-463`). Это осознанное решение с комментарием, но по факту «выбран сильный режим» и «значение в открытом виде» сосуществуют.
* **R3-25** Честность статусов: `try/finally` без `except` (`upload_queue.py:321, 369-382`) оставляет job в `uploading` и профиль `RUNNING` при неожиданном исключении; неизвестное действие warmup возвращает `True` (`warmup_engine.py:350`); «403» считается ретраибельным (`upload_queue.py:25`); `normalize_upload_platform` регистрозависим (`upload_queue.py:47-56`) — `"Instagram_Reels"` молча станет `youtube_shorts`; `cancel_all` убивает браузеры, которые сам не запускал (`upload_queue.py:144-151`).
* **R3-26** `parse_account_string` (`account_provisioner.py:81-97`): пароль, содержащий выбранный разделитель, обрезается (`p@ss:w0rd` → `p@ss`, остаток уходит в `totp_secret`); строки с другим разделителем дают мусорный email. Валидации формата нет, ошибочные строки отбрасываются молча (`:78-79`).
* **R3-27** GUI: парольная фраза остаётся в поле после применения (`gui/views/secrets_mode_card.py:98` читает `passphrase_edit.text()`, вызовов `.clear()` в файле нет; в `settings_view.py:181` очистка есть); в таблице аккаунтов отображается замаскированный 2FA-сид — 7 символов (`gui/views/accounts_view.py:327` `notes = decrypt_notes(notes)` → `:354` `totp_sec = notes.get("totp_secret","")` → `:364` ячейка таблицы; `mask_secret` — `secrets_store.py:74-80`), при этом полный сид кладётся в `Qt.ItemDataRole.UserRole` (`accounts_view.py:368`).
* **R3-28** `warmup_engine.py:332-336, 362-367`: `dwell` со `min_sec`/`max_sec` и `human_scroll` с `duration_sec` не ограничены; сценарий можно передать через API (`server.py:1223-1224`), и такой шаг навсегда занимает один из 10 слотов конкурентности (`warmup_engine.py:458`).
* **R3-29** `process_monitor._monitor_loop` глотает все исключения (`process_monitor.py:67-68`); нет `SECURITY.md`, `dependabot.yml` и сканера уязвимостей зависимостей (в `.github/workflows` только `ci.yml`, `release.yml`, `security.yml` = CodeQL).

---

## 6. Расхождения документации, коммитов и кода

1. **Тесты.** `README.md:19,230,237` — «631 automated tests», «631 passed, 2 deselected». Проверено: `pytest tests --collect-only -q -o addopts=""` → **633** node id, с `-m "not live"` → **631 из 633** (2 отброшены). Статически в `tests/**/*.py` — **572** строки `def test_`, из них 2 — фикстуры, 10 `parametrize` дают расширение до 633. То есть число 631 корректно как «собранных node id», но реального прогона «631 passed» я **не воспроизвёл**: в этом окружении `9 failed, 491 passed, 133 errors`. Все проверенные падения — `ModuleNotFoundError: qfluentwidgets` (6) и `playwright` (4); все 133 ошибки — `PermissionError` песочницы на временных каталогах. «Не могу подтвердить» относится именно к строке «631 passed».
2. `README.md:255` — «`test_deep_api_and_scenarios.py` — 25 API & scenario integration tests»; фактически 28 `def test_` (посчитано по файлу).
3. `README.md:75` документирует ответ `start` как `automation: {port, wsEndpoint, ws_endpoint}`; `server.py:724-729` возвращает только `{port, wsEndpoint}` (`ws_endpoint` есть лишь в `browser_launcher.py:441`).
4. `README.md:249` — «single-use state tokens, TLS-only callback URL validation». В коде state сравнивается (`account_provisioner.py:157-168`), но не инвалидируется после использования, и `redirect_uri` по умолчанию — `http://127.0.0.1:3000` (`:364`). Тестов на это в `tests/test_oauth_state_security.py` нет.
5. `docs/API_REFERENCE.md:8` и `CHANGELOG.md:35` — «CORS отражает 8899/3000 плюс порт, переданный с `--port`». CORS-список и regex жёстко заданы (`server.py:216-228`); `--port` расширяет только `_ALLOWED_PORTS` (`server.py:240,247-250`), используемый в `_is_local_origin` (`:280`), — то есть CORS сам по себе порт не «отражает».
6. `README.md:209` `pip install -r requirements.txt` — см. R3-16: в файле нет `psutil` и `cryptography`.
7. `CHANGELOG.md:45` — «audio_noise_seed is random again»; в `profile_manager.py:449` значение детерминированное (`0.000001 * idx`), при `idx=0` это `0.0`.
8. `README.md:244` приписывает тесты `Emulation.setTimezoneOverride`/`setUserAgentOverride` файлу `test_advanced_stealth_and_seeder.py`; они находятся в `test_cdp_injector.py:119,122`.
9. Версии: `nazak/__init__.py:5`, `pyproject.toml:7`, `version_info.txt`, `README.md:19,26` — 1.10.0; при этом `installer.iss:8` и `build_exe.py:43,45` содержат fallback `"1.9.1"`, `release.yml:12` — дефолтный тег `v1.4.1`, `gui/splash.py:121` рисует `v1.3.0`, `start_macos.sh:69,87` — «271 tests».
10. `docs/API_REFERENCE.md:402` — «Requires a real `source_video_path` (400 if missing)»; фактически есть fallback на `DATA_DIR/videos/source.mp4` (`server.py:1427-1444`).
11. `docs/API_REFERENCE.md:476` и `README.md:166` описывают `--time-zone-for-testing` как «C++-side alignment», тогда как `cdp_injector.py:12-13` прямо говорит, что флаг «was proven dead in the audit» (флаг всё ещё добавляется в `browser_launcher.py:247`, `TZ` — в `:350-352`).
12. `docs/DEEP_AUDIT_ROUND2.md:257,264` ссылается на `POST /api/profiles/{profile_id}/export` и `POST /api/profiles/import` — таких маршрутов в `server.py` нет; ссылки на строки в документе устарели (например, `:205-217` против фактических `214-228`). Историческое состояние я подтвердить не могу, но сам документ сейчас вводит в заблуждение.

---

## 7. Что проверено и НЕ подтвердилось (важно не меньше находок)

* **Секретов в истории git нет.** Сканирование полного патча истории (`git log --all -p`, 7 317 628 байт, 69 коммитов) по шаблонам private key / `AKIA…` / `ghp_…` / `AIza…` / `xox[baprs]-…` дало **одно** совпадение — строку `"response": "AKIAIOSFODNN7EXAMPLE / super-secret-token"` в `docs/DEEP_AUDIT_ROUND2.md:174`. Это пример ключа из публичной документации AWS, использованный как тестовая строка, а не реальный креденшл.
* **Исторические версии `data/profiles.json`** (коммиты `7595011`, `1ea6efe`, `452700d`, `06e4aec`, файл перестал отслеживаться в `9caefc8`) содержат только `"password": null` и человекочитаемые `notes` — учётных данных там нет.
* **Zip-slip защищён:** `profile_manager.py:1119-1124` (абсолютные пути, диск, `..`, `is_relative_to`); импорт cookie-ZIP читает архив в память и ничего не распаковывает (`cookie_manager.py:219-247`).
* **Маскирование секретов в API работает:** `server.py:330-370`, `secrets_store.py:74-80, 388-390`; `_totp_raw` появляется только при `reveal=True`.
* **Инъекций команд нет:** поиск `shell=True|os.system|os.popen|eval(|exec(` по `*.py` вне тестов не даёт совпадений; ffmpeg и Chrome запускаются списком аргументов (`video_uniquifier.py:112-139`, `browser_launcher.py:358`), `custom_url` фильтруется `sanitize_launch_url` (`browser_launcher.py:34-56`) и проверен тестом (`tests/test_audit_round2_regressions.py:116-127`).
* **Инъекций в SQL нет:** `history_seeder.py` использует параметризованные запросы (`:162, 167-178, 211-217`).
* **Пути профилей защищены:** `validate_pid` (`server.py:312-327`) и `_validate_id` (`profile_manager.py:166-180`) запрещают `/`, `\`, `:`, `..`; удаление данных требует `is_relative_to` (`:678-683`).
* **CSRF-токен OAuth генерируется CSPRNG:** `secrets.token_urlsafe(32)` (`account_provisioner.py:124`); колбэк слушает только loopback (`:247`); `?error=` экранируется (`:188`). Замечание — `listen_for_oauth_code(state=None)` делает проверку необязательной (`:382-391`), но **вызовов этого метода вне тестов я не нашёл** (grep: только `tests/`).
* **`automate_google_login` объявляет успех без проверки результата** (`account_provisioner.py:614-628`), но **вызовов в репозитории нет** (только определение) — поэтому это латентный дефект, а не активная дыра.
* **CORS ограничен точными портами** (`server.py:214-228`), regex не принимает произвольный порт (проверено: `Origin=http://localhost:3000` → 200, `Origin=https://evil.example.com` → 403).

---

## 8. Чего я НЕ смог проверить (прямо)

1. Строку «631 passed» из `README.md:237` — окружение не даёт чистого прогона (нет `qfluentwidgets`/`playwright`, песочница ломает временные каталоги pytest). *(Обновлено: числа в README приведены к фактическим — 669 collected / 666 selected / 3 live deselected.)*
2. ~~Исполнение XSS (R3-05) в реальном браузере.~~ **Проверено**: live-тест в Chromium + дифференциальный контроль (см. §3/R3-05).
3. CSRF через no-cors GET (R3-10) в реальном браузере: отсутствие `Origin` взято из MDN.
4. Эксплуатацию DNS-rebinding SSRF (R3-13) — нет управляемого DNS.
5. Чтение произвольных файлов через `/api/autopost/uniquify` (R3-12) — не подтверждаю, что содержимое утекает.
6. Межпользовательский доступ на Windows (R3-01) — вторая учётная запись не создавалась.
7. Запуск Docker-конфигурации (R3-02) — цепочка собрана из проверенных звеньев, но целиком не воспроизводилась.
8. Метаданные зависимостей `PyQt6-Fluent-Widgets`, `pytest-asyncio`, `playwright` (не установлены здесь) — поэтому «`psutil` не приходит транзитивно» я утверждаю только про 10 проверенных пакетов.
9. Историческое состояние кода, на которое ссылается `docs/DEEP_AUDIT_ROUND2.md`.
10. `docker build` / `docker compose up` целиком — см. §10: движок Docker на этой машине
    не запускается (нет WSL2, нужен админ + перезагрузка). Всё, что можно проверить без
    демона, проверено; сам `docker build` вынесен в CI-джобу `docker.yml`.

---

## 10. Docker-контур: проверено на реальном движке

Проверка выполнялась после закрытия §3–§6, уже с работающим Docker:

* `winget install Docker.DockerDesktop` → **Docker 29.8.2, Docker Compose 5.5.1**.
  Движок сначала не стартовал: лог Docker Desktop
  (`%LOCALAPPDATA%\Docker\log\host\monitor.log`) содержал
  `[main.wslexec][E] c:\windows\system32\wsl.exe --version failed: exit status 1` и
  `[main.engines][E] … engine linux/wsl failed to start: checking preconditions: checking WSL version: wsl is not installed`
  с сообщением «Install it by running `wsl --install` in an administrative PowerShell, then restart your computer».
  WSL отсутствовал, а оболочка агента не админ (`elevated: False`).
* По согласованию с пользователем WSL установлен с повышением прав (UAC):
  `wsl --install --no-distribution` → «Загрузка: Подсистема Windows для Linux 3.0.1 … Установка выполнена»,
  затем `wsl --version` → **WSL 3.0.1.0, ядро 6.18.40.1-1**, версия по умолчанию 2.
  Несмотря на `RebootPending: True` в CBS, движок поднялся без перезагрузки:
  `docker info` → `29.8.2 | Docker Desktop (containerized) | docker-desktop`.

### R3-30 (High, исправлено и проверено сборкой) — `Dockerfile` не собирался: имена пакетов от другой версии Debian

Исходный `Dockerfile:2` использовал `FROM python:3.11-slim`, а список apt-пакетов (`:9-28`) — имена
из bookworm. База при этом уже trixie — это подтверждено **запуском образа**:
`docker run --rm python:3.11-slim cat /etc/os-release` → `PRETTY_NAME="Debian GNU/Linux 13 (trixie)"`,
`VERSION_CODENAME=trixie`; запись в `docker-library/official-images`:
`Tags: 3.11.17-slim-trixie, 3.11-slim-trixie, 3.11.17-slim, 3.11-slim` / `Directory: 3.11/slim-trixie`.
По сервису Debian madison (`api.ftp-master.debian.org/madison`) этих пакетов в stable (trixie) нет:

| Пакет в Dockerfile | stable (trixie) | Замена |
|---|---|---|
| `libgl1-mesa-glx` | нет (только bullseye/bookworm) | `libgl1` |
| `libglib2.0-0` | нет | `libglib2.0-0t64` |
| `libatk1.0-0` | нет | `libatk1.0-0t64` |
| `libatk-bridge2.0-0` | нет | `libatk-bridge2.0-0t64` |
| `libcups2` | нет | `libcups2t64` |
| `libasound2` | нет | `libasound2t64` |

**Поломка воспроизведена** сборкой того же списка пакетов на `python:3.11-slim`:
`E: Package 'libgl1-mesa-glx' has no installation candidate` → `apt` exit 100, `docker build` exit 1.
Исправление (база `python:3.11-slim-trixie`, имена `libgl1`/`…t64`, убран неиспользуемый `curl`):
**`docker build` проходит, exit 0**; `hadolint 2.15.1` → exit 0 (`DL3008` закрыт
`# hadolint ignore=DL3008` с обоснованием: пиннинг apt-версий в плавающем базовом образе ломает
сборку иначе).

### R3-31 (High, исправлено и проверено) — не было `.dockerignore`: локальные секреты уезжали в образ

`COPY . .` без `.dockerignore` кладёт в слои образа всё содержимое каталога сборки, включая
`data/profiles.json` (пароли и TOTP-сиды аккаунтов в режиме `plain`), cookie/session-файлы
профилей и всю историю `.git`. По `dockerignore(5)`: «the CLI modifies the context to exclude
files and directories that match patterns specified in the file. This avoids adding them to
images using the ADD or COPY instruction». Добавлен `.dockerignore` (data/, .git/, .github/,
секреты, кэши, артефакты сборки). **Проверено в собранном образе**:
`ls -a /app` не содержит `data` и `.git`.

### R3-32 (Medium, исправлено и проверено) — compose выставлял порт на все интерфейсы

Было `ports: - "8899:8899"` (Docker публикует на всех интерфейсах хоста) и токен не задавался.
Стало: только loopback + обязательный токен. **Проверено настоящим Compose**:
`docker compose config` → `host_ip: 127.0.0.1`, `published: "8899"`, `NAZAK_API_TOKEN: ci-compose-token`;
без переменной — `docker compose config -q` падает с
«required variable NAZAK_API_TOKEN is missing a value: set NAZAK_API_TOKEN in a .env file next to docker-compose.yml»
(exit 1). Устаревший `version: '3.8'` убран; добавлен `.env.example`.

### R3-33 (инфраструктура) — CI-джоба с настоящим `docker build`

`.github/workflows/docker.yml` (только при изменениях Docker-файлов + `workflow_dispatch`):
`docker compose config -q` → `docker build` → отказ старта без токена → HTTP-контракт → логи и
cleanup. Проверен `actionlint 1.7.12` (exit 0). Теперь те же шаги подтверждены и локально (ниже),
поэтому джоба дублирует уже проверенный сценарий на каждый push.

### Что именно проверено на реальном Docker (все шаги воспроизводимы)

| Проверка | Команда/способ | Результат |
|---|---|---|
| Сборка образа | `docker build -t nazak-r3-verify .` | **exit 0** (слои: apt → pip → `playwright install chromium --with-deps` 114 MiB → COPY) |
| `.dockerignore` | `docker run --rm --entrypoint sh IMAGE -c "ls -a /app"` | `NO_GIT`, `NO_DATA` |
| Зависимости в образе | `docker run --rm --entrypoint python IMAGE -c "import psutil, cryptography, nazak"` | `deps-ok 1.10.0 7.2.2 50.0.2` |
| Отказ без токена | `docker run --rm -e NAZAK_API_TOKEN= IMAGE` | exit 1 + текст «…`NAZAK_API_TOKEN` не задан. Варианты: 1) … 2) …» |
| HTTP-контракт | `docker run -e NAZAK_API_TOKEN=… -p 127.0.0.1:18899:8899 IMAGE` | без ключа `401`; с ключом `200` (`status=online`); неверный ключ `401`; чужой `Host` `403`; чужой `Origin` `403`; `Sec-Fetch-Site: cross-site` `403`; `/openapi.json` чужой `Host` `403`, локальный `200` |
| Веб-дашборд | `GET /` | `200` + HTML |
| **`docker compose up -d --build`** | реальный Compose | контейнер `Up`, порты `127.0.0.1:8899->8899/tcp`; без ключа `401`, с ключом `200`; `docker compose down` удалил контейнер и сеть |
| Исходный Dockerfile | сборка старого списка пакетов | `E: Package 'libgl1-mesa-glx' has no installation candidate` (подтверждение R3-30) |

Итог: **16/16 проверок контейнера и 8/8 шагов compose-сценария пройдены**; тестовые образы и
runtime-данные из `data/` после проверки удалены, контейнеров не осталось.

---

## 9. Предлагаемый порядок исправления

1. **R3-01/R3-02** — токен по умолчанию + запрет `0.0.0.0` без токена; сузить выдачу cookie-экспорта. Это единственная находка, где ущерб — кража всех аккаунтов фермы.
2. **R3-03/R3-04/R3-08/R3-09** — CLI: маскировать секреты, починить TOTP, убрать подстановку «первого профиля», удалить `DEMO_MP4_HEADER`, не печатать живые коды.
3. **R3-05** — экранировать `health.*`; заодно убрать HTTP для гео-запроса.
4. **R3-06/R3-11** — честный статус публикации + запрет ретрая после клика «Publish».
5. **R3-07** — сделать безопасный режим хранения значением по умолчанию или спрашивать при импорте.
6. **R3-14/R3-16/R3-15** — привести `requirements.txt` и `addopts` в рабочее состояние, сузить `disable_error_code`.
7. **R3-10/R3-12/R3-13** — методы/валидация путей/пиннинг IP.
8. Остальное — по таблице §1.

---

## 11. Второй проход аудита (round-3b): участки, которые в §1–§10 не проверялись

Первый проход закрыл периметр API, CLI-секреты, честность публикации, warmup и Docker.
Второй проход целенаправленно смотрел туда, где я ещё не читал код: `index.html` и
шрифтовые зависимости дашборда, генератор stealth-JS целиком, `cdp_injector` (цикл
CDP), `synchronizer`, `cli_cmds/automation.py`, `gui/dialogs/*`, `nazak/tools/*`,
`build_exe.py`/`installer.iss` (сборка релиза), `profile_manager.import_profile_bundle`
и cookie-ZIP, а также все pydantic-модели запросов API на предмет границ.

### Сводка

| # | Находка | Severity | Как проверял | Статус |
|---|---|---|---|---|
| R3b-01 | `scenario run` без `--wait`: daemon-поток убивался `SystemExit`, команда печатала success | High | репро механизма + чтение | исправлено, тест |
| R3b-02 | Отрицательный `min_delay_ms` → `ValueError` вне `try` убивал поток-насос, `session.active` оставался `True` | Medium | запуск: `_mirror_one` пробросил `ValueError('sleep length must be non-negative')` | исправлено, тесты |
| R3b-03 | `Infinity`/`NaN` из JSON принимались моделями → в stealth.js попадали литералы `inf`/`nan` | Medium | сквозной запуск: POST 200 → `() => inf`, `const factor = nan` | исправлено, тесты |
| R3b-04 | `MassGenerateRequest.count` без верхней границы → O(n²) перезаписи `profiles.json` | Medium | замер: 20→0.06 с, 40→0.15 с, 80→0.43 с | исправлено, тесты |
| R3b-05 | `AutopostBatchRequest.delay_seconds` без границы → батч «засыпал» на годы, блокируя `is_running` | Medium | расчёт + чтение `upload_queue.py:227` | исправлено, тесты |
| R3b-06 | `.nazak` и cookie-ZIP распаковывались без лимитов | Medium | замер: 100 КиБ архив → 100 МиБ на диске | исправлено, тесты |
| R3b-07 | Сборка релиза увозила runtime `data/` (в т.ч. `profiles.json`) в ZIP и установщик | Medium | фрозен-путь воспроизведён: `data/{profiles.json,profiles,extensions,logs}` рядом с exe | исправлено, тест |
| R3b-08 | GUI-воркеры использовали предсказуемый диапазон CDP-портов `9350 + idx` | Low-Medium | чтение + grep | исправлено, тест |
| R3b-09 | `Runtime.addBinding` стоял во всех сессиях: любая страница мастера (включая iframe) могла диктовать клики в браузерах других профилей | High | чтение цепочки `_on_binding_called → submit_event → _dispatch_event` | исправлено, тесты |
| R3b-10/11 | Ни одного security-заголовка; CSP отсутствовал | Medium | grep по репозиторию + живой сервер | исправлено (частичный CSP), тесты |
| R3b-12 | GUI: удаление кэша без подтверждения, ложный успех импорта cookie | Medium | чтение | исправлено, статические тесты |
| R3b-13 | В инжектируемом JS были page-visible маркеры `__nazakShieldApplied`, `__nazakSyncInstalled`, `__nazak_sync_event` | Low (для антидетекта — Medium) | генерация stealth.js и проверка содержимого | исправлено, тесты |
| R3b-14 | Мелочи: `${e.message}` в `innerHTML`, `target="_blank"` без `rel`, Google Fonts с CDN, `D:/nazak/...` в tools, «V1.3.0» в ассете, docstring 1..500 против слайдера 1..100, неограниченная очередь событий, inline-разбор binding'а в цикле CDP, `cols<0` | Low | чтение + запуск | исправлено |

### R3b-01. `nazak scenario run` без `--wait` рапортовал успех, не выполняя работу

`cli_cmds/automation.py:196-207` (до фикса) стартовал `threading.Thread(target=_bg, daemon=True)`
и сразу возвращал `emit_success`. `nazak/main.py:90` и `:139` — `raise SystemExit(run_cli())`,
поэтому интерпретатор завершался немедленно и daemon-поток уничтожался. Воспроизведено
отдельным репро: процесс печатает «success reported, exiting now», `exit=0`, а файл-маркер,
который поток должен был создать через 1.5 с, не появился и через 2.5 с.

**Исправлено:** фон — отдельный процесс (`subprocess.Popen` с `DETACHED_PROCESS |
CREATE_NEW_PROCESS_GROUP` на Windows, `start_new_session=True` на POSIX), stdout/stderr
пишутся в `data/logs/scenario_<timestamp>.log`, в JSON-ответе `pid` и путь к логу; при
невозможности старта — честная ошибка с подсказкой про `--wait`. Команду целиком я не
запускал, чтобы не поднимать реальный браузер на машине пользователя.

### R3b-02. Отрицательный джиттер убивал синхронизатор, а статус оставался «active»

`synchronizer.py:355-356` (до фикса) — `time.sleep(delay_ms / 1000.0)` стоял **вне**
per-event `try` (строка 357). `SynchronizerStartRequest.min_delay_ms` (`server.py:542`)
и CLI `--min-delay` не имели нижней границы. Запуск подтвердил:
`_mirror_one` с интервалом `(-1.0, -0.5)` пробросил `ValueError('sleep length must be non-negative')`;
в `_mirror_pump` его ловил `except` (строка 316), который писал warning и выходил, **не
сбрасывая `session.active`** — `get_status()` продолжал отдавать `active: true`, а
`mirror_navigation` ждал ответа до 110 с.

**Исправлено:** `_clamp_delay_range()` нормализует интервал (неотрицательный,
упорядоченный, ≤60 с) и вызывается и в `SynchronizerSession.__init__`, и перед sleep;
sleep перенесён внутрь `try`; `finally` насоса выставляет `session.active = False` и
пишет `last_error`; `mirror_navigation` проверяет живость потока и не ждёт мёртвый насос;
очередь событий ограничена `MAX_PENDING_EVENTS` с честным счётчиком `dropped_events`.

### R3b-03. `Infinity`/`NaN` ломали stealth.js

`json.loads` принимает литералы `Infinity`/`NaN`, pydantic v2 по умолчанию их не
отвергает, а шаблон stealth-JS подставлял два float-поля через `str()`
(`extension_generator.py:335` — `device_pixel_ratio`, `:601` — `audio_noise_seed`).
Сквозной запуск: `POST /api/profiles` с `{"device_pixel_ratio":Infinity,"audio_noise_seed":NaN}`
→ **HTTP 200**, в модели `inf`/`nan`, в `stealth.js`:

```
Object.defineProperty(Window.prototype, 'devicePixelRatio', { get: makeNative(() => inf, ...
const factor = nan || 0.00001;
```

`inf`/`nan` — не идентификаторы JS (там `Infinity`/`NaN`): первое даёт ReferenceError на
каждом чтении `devicePixelRatio` (страница ломается и это яркий признак подмены), второе
глотается внешним `try/catch` → аудио-шум молча отключался.

**Исправлено:** `allow_inf_nan=False` в `FingerprintConfig`/`BatterySpoofConfig`/
`GeolocationSpoofConfig`; `_js_number()` в генераторе (защита в глубину: `inf`→`Infinity`,
`nan`→`0` с warning); ответ валидации больше не падает с 500 — `RequestValidationError`
обрабатывается безопасно (см. R3b-10/11); нечисловые `lat/lon` и слишком长 строки из
гео-ответа санитизируются в `proxy_checker` (`_finite_or_none`, `_safe_text`, `_safe_timezone`).

### R3b-04 / R3b-05. Отсутствие границ у числовых полей запросов

Ни одна модель запроса не имела `Field(ge/le)` (`server.py:464-553` до фикса). Замер
стоимости `mass_generate_profiles` (каждый профиль перезаписывает весь `profiles.json`):
`count=20 → 0.06 с`, `40 → 0.15 с`, `80 → 0.43 с` — то есть один запрос с `count=10000`
вешает сервер на часы (CLI при этом всегда проверял `1..200`). Для `delay_seconds`
`upload_queue.py:433` считал `random.randint(max(5, d-3), d+5)`, а вход в новый батч
закрыт, пока идёт текущий (`upload_queue.py:227`) — `delay_seconds=10**9` означал паузу
≈31 год и выключенный автопостинг до перезапуска.

**Исправлено:** границы в моделях (`count 1..200`, `delay_seconds 0..3600`, `min/max_delay_ms
0..60000`, `coordinate_jitter_px 0..50`, `cols 1..8`, `cdp_port 1..65535`, `max_concurrency
1..10`, `steps_count 1..20`, `max_length` для строк и списков, `format` по pattern) и
**дублирующие клампы в сервисном слое** (`mass_generate_profiles`, `run_batch_upload`,
`SynchronizerSession`, `tile_windows_win32`). Нижние границы, отвечавшие за 400-контракт
эндпоинтов, намеренно не добавлялись — проверено, что три существующих теста на 400
проходят.

### R3b-06. Zip-бомба в импорте бандла и cookie-архива

`profile_manager.py:1090/1115/1131` использовал только `namelist()`/`read()` — ни проверки
`ZipInfo.file_size`, ни счётчика записей. Замер: архив **100 КиБ → 100 МиБ** записано на
диск (5 записей по 20 МиБ нулей). Cookie-ZIP (`cookie_manager.py:233`) читался в память целиком.

**Исправлено:** лимиты по числу записей (20 000 / 200), по записи (512 МиБ / 32 МиБ) и по
сумме (1 ГиБ / 64 МиБ); распаковка бандла потоковая с реальным подсчётом байт (заявленный
`file_size` подделывается вниз), при превышении — отказ и удаление полураспакованного каталога.

### R3b-07. Релизные артефакты увозили `data/`

Фрозен-приложение держит данные рядом с собой (`config.py:13-17`, `DATA_DIR = EXE_DIR/data`),
а `build_exe.py:182` запускает собранный exe в рамках сборки — после чего в
`dist/NazakBrowserStudio/data/` появляются `profiles.json`, `profiles/`, `logs/`,
`extensions/`. ZIP пакует любой файл под `APP_DIR` (`build_exe.py:204-209`), установщик
копирует всё рекурсивно (`installer.iss:59`). Воспроизведено на фрозен-пути: рядом с
фейковым exe создаётся `data/{profiles.json,profiles,extensions,logs,videos}`; в
`profiles.json` — 10 дефолтных профилей (проверено: паролей и 2FA там нет). Сегодня это
не утечка, но это ровно тот каталог, где в режиме `plain` лежат пароли и 2FA-сиды.

**Исправлено:** `sanitize_app_data()` в `build_exe.py` (вызывается между `smoke_test()` и
`package_zip()`, удаляет runtime-файлы и каталоги, восстанавливает `data/assets` для иконки)
плюс второй слой — `Excludes:` в `installer.iss`. Полный `pyinstaller`/`ISCC` я не запускал:
проверен механизм (фрозен-каталог и `rglob("*")` в упаковке), сам факт содержимого ZIP — вывод.

### R3b-08. Предсказуемые CDP-порты в GUI-воркерах

`gui/workers.py:133` — `cdp_port = 9350 + idx`, тогда как остальные пути берут эфемерный
порт (`browser_launcher.get_free_port()`). В связке с отсутствием аутентификации у CDP
локальный процесс может угадать порт и подключиться к живой сессии профиля.

**Исправлено:** `get_free_port()`; тест проверяет, что литерала `9350` больше нет, а также
что функция возвращает различные bindable порты.

### R3b-09. Инъекция действий со страницы в браузеры других профилей

`Runtime.addBinding` ставится для каждой attached-сессии (`cdp_injector.py:317`),
обработчик проверял только имя и `type` (`:347-360`), после чего событие уходило в
`submit_event` (`synchronizer.py:221-228`) и проигрывалось как `mouse.click`,
`keyboard.press` или ввод до 8 символов в **worker-профилях** (`:454`, `:466`, `:470-477`).
Пока идёт sync-сессия, любой скрипт на странице мастера (в том числе рекламный iframe)
мог кликать в чужих залогиненных профилях.

**Исправлено:** `binding_event_allowed()` (чистая, тестируемая) принимает жест только если
это main-world контекст (`auxData.isDefault`) **главного** фрейма (`Page.getFrameTree` +
`Page.frameNavigated`) top-level страницы (`targetInfo.type == "page"`, OOPIF исключён);
payload ограничен 4 КиБ; включён token-bucket (60 событий/с, burst 120); разбор payload'а
вынесен в задачу, чтобы флуд со страницы не задерживал `Fetch.continueRequest` в цикле чтения
CDP; счётчики `binding_events_accepted/rejected/throttled` доступны в статусе инжектора.

### R3b-10/11. Security-заголовки и частичный CSP

Ни `Content-Security-Policy`, ни `X-Content-Type-Options`, ни `Referrer-Policy`, ни
`X-Frame-Options` не выставлялись нигде (`grep` по репозиторию — 0 совпадений); `/`
отдавался голым `FileResponse`. Строгий CSP сейчас невозможен: в `index.html` 40, а в
генерируемой `app.js` разметке ещё 18 inline-обработчиков `on*`.

**Исправлено:** middleware выставляет `X-Content-Type-Options: nosniff`,
`Referrer-Policy: no-referrer`, `X-Frame-Options: DENY`, `Cross-Origin-Opener-Policy`,
`Cross-Origin-Resource-Policy`, `Permissions-Policy` и CSP с `object-src 'none'`,
`base-uri 'none'`, `form-action 'self'`, `frame-ancestors 'none'`, `script-src 'self'
'unsafe-inline'`; для `/api` и `/v1.0` добавлен `Cache-Control: no-store` (экспорт cookies
не должен оседать в дисковом кэше). **Честная граница:** проверено в реальном браузере, что
этот CSP НЕ останавливает сам XSS — версия дашборда без экранирования продолжает исполнять
payload при включённом CSP (`country=1, city=1, ip=1`, 323 байта из
`/api/security/secrets-mode`). Защиту держит экранирование (R3-05), CSP — второй слой
против внешних скриптов, object/embed и встраивания. Строгий CSP требует перевода
inline-обработчиков на `addEventListener` — отдельная задача, в этот раунд не входила.

### R3b-12. GUI-диалоги: подтверждение и честные результаты

`gui/dialogs/cookie_dialog.py:106-107` — один клик удалял Cache/Code Cache/GPUCache/
DawnCache/Service Worker/CacheStorage без подтверждения и игнорировал `False` от
`clear_profile_cache`; `:97-98` печатал «Successfully saved N entries» независимо от
результата `save_profile_cookies`; `batch_cookie_dialog.py:244-245` не показывал счётчик
`failed`.

**Исправлено:** `QMessageBox.question` + проверка обоих булевых результатов (ошибка вместо
успеха), счётчик `failed` в сводке с `InfoBar.warning`. GUI без PyQt6 не запускается,
поэтому проверено чтением и статическим тестом; поведение диалогов в живом GUI не проверялось.

### R3b-13. Page-visible маркеры продукта

В сгенерированном `stealth.js` был `window.__nazakShieldApplied`, в sync-клиенте —
`window.__nazakSyncInstalled`, а binding назывался `__nazak_sync_event`: любая
антифрод-система могла определить Nazak одной строкой `if (window.__nazak…)`.

**Исправлено:** флаги идемпотентности переименованы (`window.__nsi`, `window.__nse_c`) и
сделаны неперечислимыми (`enumerable: false`), имя binding'а — `__nse_ev`, бренд убран из
комментариев внутри инжектируемого JS (комментарии видны через `Function.prototype.toString()`
для незаклоаченных функций). Дополнительно инжектор применяет скрипт к текущему документу
один раз на `(sessionId, loaderId)`, поэтому видимый странице флаг-«предохранитель» стал
резервным, а не основным механизмом. Тесты: `"__nazak" not in SYNC_CLIENT_JS`,
`"__nazakShieldApplied" not in stealth.js`.

**Остаточный риск (не устранён):** страница всё ещё может найти эти свойства явным
перечислением (`Object.getOwnPropertyNames(window)`, `getOwnPropertySymbols`). Полностью
невидимый вариант требует убрать флаги и полагаться только на учёт инъекций на стороне CDP —
это шире, чем правка этого раунда, и риск двойного применения скрипта выше выгоды.

### R3b-14. Мелкие исправления

- `app.js:346` — `${e.message}` теперь через `escapeHtml`; `app.js:854` — `rel="noopener noreferrer"`.
- Google Fonts с CDN (`index.html:8-10`) убраны: дашборд больше не обращается к внешним
  хостам и работает офлайн; `styles.css` использует явные системные стеки
  (`Segoe UI Variable Text` / `Cascadia Mono`), других `url()`/`@import` в CSS нет.
- `synchronizer._navigate_worker_sync` больше не передаёт URL в `page.goto()` как есть:
  `file://`, `data:` и `javascript:` отклоняются (проверено запуском), плюс `field_validator`
  на `SynchronizerNavigateRequest.url` отдаёт 422 на границе.
- `nazak/tools/generate_brand_assets.py` — путь `D:/nazak/data/assets` заменён на
  repo-relative, версия баннера берётся из пакета (было жёстко «V1.3.0»).
- `mass_generate_dialog.py` — docstring приведён к реальному диапазону слайдера (1..100).
- `synchronizer.py:150-153` — `cols` ограничен 1..8 (отрицательное значение давало
  ZeroDivisionError/отрицательную геометрию, что гасилось общим `except`).
- `synchronizer._ensure_worker_pages` проверяет кэш страниц **до** импорта playwright
  (побочный эффект: тест `test_mirror_one_replicates_event_to_all_workers`, падавший из-за
  отсутствия playwright, теперь проходит).
- Классы `RequestValidationError`-ответа не эхо исходный ввод: тело 422 сериализуемо даже
  для `Infinity`, а 5-мегабайтная строка не возвращается клиенту целиком.

### Что проверено и НЕ подтвердилось во втором проходе

- Утечек секретов в логи нет: все `logger.*` с упоминанием паролей/токенов логируют имена
  полей, а не значения (`secrets_store.py:366/475/489`, `account_provisioner.py:549`).
- `NazakBrowserStudio.spec:13-16` бандлит только `nazak/web` и `data/assets` — корневой
  `data/` в образ не попадает; `app.manifest:15` — `requestedExecutionLevel="asInvoker"`,
  `installer.iss:43` — `PrivilegesRequired=lowest` (никакого запроса администратора).
- В сгенерированном JS нет небезопасных подстановок строк: все строковые/структурные
  значения идут через `json.dumps`, «сырыми» остаются 14 числовых/булевых полей
  (единственные float — те, что закрыты `_js_number`).
- `parse_cookie_files_from_dir/zip` не распаковывают архив на диск (zip-slip невозможен),
  `import_profile_bundle` фильтрует абсолютные пути, диски и `..`.

### Что осталось непроверенным (прямо)

- Исполнение R3b-09 в живом браузере: цепочку я прочитал и покрыл тестами на чистых
  функциях, но реальную пару «мастер + воркер» с вредоносной страницей не поднимал.
- Фактическое содержимое релизного ZIP/Setup.exe: `pyinstaller` и `ISCC` не запускались
  (проверен механизм, а не готовый артефакт).
- Поведение GUI-диалогов после правок (нет PyQt6/qfluentwidgets в окружении) и отрисовка
  баннера в `generate_brand_assets.py` (нужны PyQt6 + Pillow).
- Строгий CSP без `'unsafe-inline'` — не реализован, см. R3b-10/11.

### Верификация второго прохода

- Полный прогон: **725 collected, 3 live deselected**; `715 passed, 7 failed` без live
  (7 — окружение: нет `qfluentwidgets`/`playwright`), против **9** падений на коммите
  `5a25115` в том же окружении (одно падение закрыто улучшением `_ensure_worker_pages`).
- Новые файлы тестов: `tests/test_round3b_api_bounds.py` (12),
  `tests/test_round3b_stealth_and_sync.py` (16),
  `tests/test_round3b_storage_and_packaging.py` (9),
  `tests/test_round3b_cli_background.py` (4),
  `tests/test_web_assets_hardening.py` (7), `tests/test_gui_and_tools_hardening.py` (8).
- `ruff check`/`ruff format --check` — чисто; `mypy nazak` — `Success` (57 файлов).
- В образе (`nazak-browser-studio-nazak-studio:latest`, Chromium внутри): живые заголовки
  подтверждены (`CSP`, `nosniff`, `DENY`, `no-referrer`, `no-store`), все границы отдают 422,
  `Infinity` в теле — 422 (было 500), `file://` в navigate — 422; живой XSS-тест в Chromium
  проходит (21 passed вместе с web/gui-тестами), а на версии дашборда без экранирования —
  падает, как и должно.
