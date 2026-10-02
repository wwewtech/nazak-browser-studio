# Nazak Browser Studio — CLI Reference (паритет с GUI)

CLI покрывает **все 6 разделов GUI** (Profiles / Autoposting / Accounts / Proxies / Warmup / Settings)
и все группы REST API. Русская справка, английские ключи/JSON-поля, удобно ИИ-агентам.

## 0. Запуск

```powershell
python -m nazak.cli --help
python -m nazak.cli --json profile list
python -m nazak.main --mode cli profile list --json   # то же через launcher
NazakBrowserStudio.exe profile list                   # frozen EXE
NazakBrowserStudio.exe list                           # legacy alias тоже работает
```

## 1. AI-контракт

| Элемент | Правило |
|---|---|
| `--json` | ставится **где угодно**: `profile list --json` == `--json profile list` |
| stdout | при `--json` — только JSON `{success, ...}`; без флага — Rich-таблицы |
| stderr | только ошибки |
| exit-коды | `0` ok · `1` not found · `2` usage/validation · `4` conflict/busy · `130` Ctrl+C |
| `--yes / -y` | пропустить подтверждения (`profile delete`, destructive) |
| `--server URL` | выполнить через running GUI/web API (`http://127.0.0.1:8899`), `--api-key` или `$NAZAK_API_TOKEN` |
| входные данные | аргумент, `@file`, `--file`, `--stdin`, pipe; прокси/аккаунты построчно |
| секреты | маскируются (`***`, `ab...yz`); без `--reveal`-подобных флагов секреты не печатаются |

## 2. Группы

| Группа | Команды | GUI-источник |
|---|---|---|
| `profile` | `list [--group] · get <id> · create --name --group --proxy --os --target-page --tags · update <id> [--name/--group/--proxy] · delete <id> · clone <id> [--new-name] · launch <id> [--url --cdp-port] · stop <id> · batch-launch/batch-stop --profiles --all · bulk-import [--file/stdin] --group --target-page · mass-generate --count 1..200 --os-mix --tags --file --notes · fingerprint --os · clear-cache <id> · seed-history <id> --count 5..100 · bundle-export <id> [--out] · bundle-import <file> [--new-name]` | ProfilesView + dialogs |
| `cookie` | `import <id> [--file/stdin] · export <id> --format json\|netscape [--out] · bulk-import [--file/stdin] --group [--no-autocreate] · bulk-export --profiles/--all --format json\|zip [--out]` | BatchCookieDialog, CookieManagerDialog |
| `proxy` | `check <id> · check-all · test <raw\|@file> · rotate <id>` | ProxiesView |
| `warmup` | `plan <id> --niche ecommerce\|finance\|tech\|travel\|crypto --steps · launch <id> ...` | WarmupView |
| `scenario` | `list · run --scenario <id\|алиас> [--scenario-file] --profiles/--all --concurrency --wait` (алиасы: `ecommerce_trust_booster`, `youtube_shorts_warmup`, `crypto_web3_farming`, `finance_high_cpc_banking`) | WarmupView + API |
| `sync` | `start --master --workers --no-jitter --min-delay --max-delay --coord-jitter · stop · status · tile [--cols] · navigate <url>` | SynchronizerDialog |
| `autopost` | `status · preview --profiles/--all --title --desc --tg · uniquify --video --profiles/--all · launch --profiles/--all --video --platform youtube_shorts\|instagram_reels --title --desc --tg --delay --demo --wait · cancel` | AutopostView |
| `account` | `import [--file/stdin] --group --mode browser_stealth\|oauth_api · list · totp <id> · login [--profile --email --video --data-file]` | AccountsView + `cli_auto_login_and_upload.py` |
| `cdp` | `start <id> [--url --port] · stop <id> · active · info <id>` (ответ `{automation: {port, wsEndpoint}}`, `connect_over_cdp`) | Dolphin `/v1.0/*` |
| `secrets` | `get · set --mode plain\|dpapi\|passphrase [--passphrase/--passphrase-stdin/$NAZAK_PASSPHRASE]` | SettingsView |
| `system` | `info` | SettingsView System card |
| legacy root | `list · launch <id> [url] · stop <id> · check <id> · check-all · info · help` | старый `cli.py` |

## 3. Примеры

```powershell
# Профили
python -m nazak.cli profile list --json
python -m nazak.cli profile create --name "Ads 01" --group "Google Ads" --proxy "host:port:user:pass" --json
python -m nazak.cli profile clone prof_01 --new-name "Ads 01 copy" --json
python -m nazak.cli profile mass-generate --count 20 --group "Farm" --os-mix all --json
python -m nazak.cli profile bundle-export prof_01 --out prof_01.nazak

# Cookies (Netscape / JSON / ZIP, папка / stdin)
python -m nazak.cli cookie bulk-import --file cookies.txt --group "Imported" --json
Get-Content cookies.txt | python -m nazak.cli cookie bulk-import --stdin --json
python -m nazak.cli cookie export prof_01 --format netscape
python -m nazak.cli cookie bulk-export --all --format zip --out all.zip

# Прокси
python -m nazak.cli proxy check prof_01 --json
python -m nazak.cli proxy test "socks5://user:pass@host:port" --json
python -m nazak.cli proxy rotate prof_01 --json

# Warmup / сценарии
python -m nazak.cli scenario list --json
python -m nazak.cli scenario run --scenario youtube_shorts_warmup --profiles prof_01,prof_02 --concurrency 2 --json
python -m nazak.cli warmup plan prof_01 --niche crypto --steps 5 --json

# Синхронизатор
python -m nazak.cli sync start --master prof_01 --workers prof_02,prof_03 --json
python -m nazak.cli sync navigate "https://www.google.com" --json
python -m nazak.cli sync tile --cols 2 --json
python -m nazak.cli sync stop --json

# Автопостинг
python -m nazak.cli autopost status --json
python -m nazak.cli autopost preview --profiles prof_01 --title "{Best|Top} VPN 2026 #shorts" --json
python -m nazak.cli autopost uniquify --video clip.mp4 --profiles prof_01,prof_02 --json
python -m nazak.cli autopost launch --profiles prof_01 --video clip.mp4 --platform youtube_shorts --wait --json
python -m nazak.cli autopost cancel --json

# Аккаунты
python -m nazak.cli account import --file accounts.txt --group "Retriv Gmail" --mode browser_stealth --json
python -m nazak.cli account totp prof_01 --json
python -m nazak.cli account login --profile prof_01 --video clip.mp4

# CDP для Playwright/Puppeteer
python -m nazak.cli cdp start prof_01 --json
# {"automation": {"port": 9222, "wsEndpoint": "ws://127.0.0.1:9222/..."}}
python -m nazak.cli cdp active --json

# Secrets / system
python -m nazak.cli secrets get --json
python -m nazak.cli secrets set --mode passphrase --passphrase-stdin --json
python -m nazak.cli system info --json

# Через running сервер (единая валидация API)
python -m nazak.cli --server http://127.0.0.1:8899 profile list --json
$env:NAZAK_API_TOKEN="secret"; python -m nazak.cli --server http://127.0.0.1:8899 sync status --json
```

## 4. Server-режим

По умолчанию команды идут **напрямую через core** (сервер не нужен). С `--server` те же команды
идут через `httpx` к GUI/web API (те же пути, что в `docs/API_REFERENCE.md`).
Исключения (только direct): `profile bundle-import`, `account import/login` — для них CLI честно
возвращает ошибку с объяснением вместо молчаливого неверного результата.

## 5. Exit-коды и ошибки

```json
{"success": false, "error": "Профиль 'prof_xx' не найден", "code": 1}
```

`1` — профиль/файл не найден · `2` — нет аргументов, плохой формат, пустой bulk ·
`4` — уже запущен/очередь занята/нужен стоп/нет ffmpeg. В human-режиме та же ошибка — красная панель в stderr.
