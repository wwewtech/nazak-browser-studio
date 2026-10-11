# Nazak Browser Studio — CLI Reference (GUI parity)

The CLI covers **all 6 GUI sections** (Profiles / Autoposting / Accounts / Proxies / Warmup / Settings)
and every REST API group. Russian help text, English keys/JSON fields — convenient for AI agents.

## 0. Getting Started

```powershell
python -m nazak.cli --help
python -m nazak.cli --json profile list
python -m nazak.main --mode cli profile list --json   # the same through the launcher
NazakBrowserStudio.exe profile list                   # frozen EXE
NazakBrowserStudio.exe list                           # the legacy alias works too
```

## 1. AI Contract

| Element | Rule |
|---|---|
| `--json` | accepted **anywhere**: `profile list --json` == `--json profile list` |
| stdout | with `--json` — exactly one JSON document (progress from chatty commands goes to stderr); without the flag — Rich tables |
| stderr | errors + human progress in `--json` mode |
| exit codes | `0` ok · `1` not found (and API 404 under `--server`) · `2` usage/validation (API 400/409/422) · `4` conflict/busy (API 5xx/transport) · `130` Ctrl+C |
| errors | always `{success: false, error, code, hint?}` — `hint` contains the exact next command |
| `--yes / -y` | skip confirmations. In a non-interactive context (`--json`, pipe, CI) a destructive command without `--yes` **does not hang**: it immediately returns code 4 with `hint: "... --yes"` |
| env duplicates | `NAZAK_JSON=1`, `NAZAK_YES=1`, `NAZAK_REVEAL=1`, `NAZAK_SERVER=url`, `NAZAK_API_TOKEN`, `NAZAK_PASSPHRASE`, `NAZAK_VERBOSE=1`, `NAZAK_DATA_DIR`, `NAZAK_PROFILE_STORE=json\|sqlite` — the same as the flags |
| `--server URL` | run through a running GUI/web API (`http://127.0.0.1:8899`), `--api-key` or `$NAZAK_API_TOKEN` |
| input data | argument, `@file`, `--file`, `--stdin`, pipe; proxies/accounts line by line |
| `@file` | a nonexistent path is an input error (`exit 2`), not data; directories and files > 16 MB are rejected |
| `--out` | an existing file is not overwritten without `--force` (or `--yes`); the directory must exist |
| secrets | masked by default (`***`, `ab...yz`): proxy password, `account_password`, `totp_secret` in `google.notes`. Plaintext only with an explicit `--reveal` (or `NAZAK_REVEAL=1`) |
| `--reveal` | global flag: `profile get <id> --reveal --json`. In `system schema` it is present in `global_flags` |

## 2. Groups

| Group | Commands | GUI source |
|---|---|---|
| `profile` | `list [--group] · get <id> · create --name --group --proxy --os --target-page --tags · update <id> [--name/--group/--proxy] · delete <id> · clone <id> [--new-name] · launch <id> [--url --cdp-port] · stop <id> · batch-launch/batch-stop --profiles --all · bulk-import [--file/stdin] --group --target-page · mass-generate --count 1..200 --os-mix --tags --file --notes · fingerprint --os · clear-cache <id> · seed-history <id> --count 5..100 · bundle-export <id> [--out] · bundle-import <file> [--new-name]` | ProfilesView + dialogs |
| `cookie` | `import <id> [--file/stdin] · export <id> --format json\|netscape [--out] · bulk-import [--file/stdin] --group [--no-autocreate] · bulk-export --profiles/--all --format json\|zip [--out]` | BatchCookieDialog, CookieManagerDialog |
| `proxy` | `check <id> · check-all · test <raw\|@file> · rotate <id>` | ProxiesView |
| `warmup` | `plan <id> --niche ecommerce\|finance\|tech\|travel\|crypto --steps · launch <id> ...` | WarmupView |
| `scenario` | `list · run --scenario <id\|alias> [--scenario-file] --profiles/--all --concurrency --wait` (aliases: `ecommerce_trust_booster`, `youtube_shorts_warmup`, `crypto_web3_farming`, `finance_high_cpc_banking`) | WarmupView + API |
| `sync` | `start --master --workers --no-jitter --min-delay --max-delay --coord-jitter · stop · status · tile [--cols] · navigate <url>` | SynchronizerDialog |
| `autopost` | `status · preview --profiles/--all --title --desc --tg · uniquify --video --profiles/--all · launch --profiles/--all --video --platform youtube_shorts\|instagram_reels --title --desc --tg --delay --demo --wait · cancel` | AutopostView |
| `account` | `import [--file/stdin] --group --mode browser_stealth\|oauth_api · list · totp <id> · login [--profile --email --video --data-file]` | AccountsView + `cli_auto_login_and_upload.py` |
| `cdp` | `start <id> [--url --port] · stop <id> · active · info <id>` (response `{automation: {port, wsEndpoint}}`, `connect_over_cdp`) | Dolphin `/v1.0/*` |
| `secrets` | `get · set --mode plain\|dpapi\|passphrase [--passphrase/--passphrase-stdin/$NAZAK_PASSPHRASE]` | SettingsView |
| `system` | `info · doctor · schema · version` | SettingsView System card |
| `profile` | `ensure --name ...` — idempotent get-or-create (retries without duplicates, returns `created: true/false`) | — |
| legacy root | `list · launch <id> [url] · stop <id> · check <id> · check-all · info · help` | the old `cli.py` |

## 3. Agent Recipe (so you never stumble)

```powershell
python -m nazak.cli system doctor --json     # 0) preflight: chrome/ffmpeg/data
python -m nazak.cli system schema --json     # 0b) exact schema of all 60+ commands for function-calling
python -m nazak.cli profile ensure --name "Ads 01" --group "Google Ads" --json  # 1) idempotently
python -m nazak.cli proxy check <id> --json  # 2) check before launch
python -m nazak.cli cdp start <id> --json    # 3) wsEndpoint for connect_over_cdp
# destructive — always with --yes (otherwise code 4 + hint):
python -m nazak.cli profile delete <id> --yes --json
# through the server: the same commands + --server; API 404/400 map to codes 1/2
python -m nazak.cli --server http://127.0.0.1:8899 sync status --json
```

## 4. Examples

```powershell
# Profiles
python -m nazak.cli profile list --json
python -m nazak.cli profile create --name "Ads 01" --group "Google Ads" --proxy "host:port:user:pass" --json
python -m nazak.cli profile clone prof_01 --new-name "Ads 01 copy" --json
python -m nazak.cli profile mass-generate --count 20 --group "Farm" --os-mix all --json
python -m nazak.cli profile bundle-export prof_01 --out prof_01.nazak

# Cookies (Netscape / JSON / ZIP, folder / stdin)
python -m nazak.cli cookie bulk-import --file cookies.txt --group "Imported" --json
Get-Content cookies.txt | python -m nazak.cli cookie bulk-import --stdin --json
python -m nazak.cli cookie export prof_01 --format netscape
python -m nazak.cli cookie bulk-export --all --format zip --out all.zip

# Proxies
python -m nazak.cli proxy check prof_01 --json
python -m nazak.cli proxy test "socks5://user:pass@host:port" --json
python -m nazak.cli proxy rotate prof_01 --json

# Warmup / scenarios
python -m nazak.cli scenario list --json
python -m nazak.cli scenario run --scenario youtube_shorts_warmup --profiles prof_01,prof_02 --concurrency 2 --json
python -m nazak.cli warmup plan prof_01 --niche crypto --steps 5 --json

# `scenario run` without --wait starts a SEPARATE process (not a thread): it survives
# the CLI exit and writes a log to data/logs/scenario_<timestamp>.log. The JSON response
# carries "pid" and "log". Previously this was a daemon thread that died with the process:
# the command printed success without having done anything. If the process could not be
# started, the command returns an error and points at the --wait flag.
python -m nazak.cli scenario run --scenario youtube_shorts_warmup --profiles prof_01 --json
# synchronous mode (waits for completion, nothing is left running in the background):
python -m nazak.cli scenario run --scenario youtube_shorts_warmup --profiles prof_01 --wait --json

# Synchronizer
python -m nazak.cli sync start --master prof_01 --workers prof_02,prof_03 --json
python -m nazak.cli sync navigate "https://www.google.com" --json
python -m nazak.cli sync tile --cols 2 --json
python -m nazak.cli sync stop --json

# Synchronizer bounds: --min-delay/--max-delay 0..60000 ms (negative
# values used to kill the pump thread while the status kept showing active),
# --cols 1..8, navigate accepts only http(s) — file://, data: and javascript:
# are rejected (previously the URL went into the workers' page.goto() as-is).

# Autoposting
python -m nazak.cli autopost status --json
python -m nazak.cli autopost preview --profiles prof_01 --title "{Best|Top} VPN 2026 #shorts" --json
python -m nazak.cli autopost uniquify --video clip.mp4 --profiles prof_01,prof_02 --json
python -m nazak.cli autopost launch --profiles prof_01 --video clip.mp4 --platform youtube_shorts --wait --json
python -m nazak.cli autopost cancel --json

# Accounts
python -m nazak.cli account import --file accounts.txt --group "Retriv Gmail" --mode browser_stealth --json
python -m nazak.cli account totp prof_01 --json
python -m nazak.cli account login --profile prof_01 --video clip.mp4

# CDP for Playwright/Puppeteer
python -m nazak.cli cdp start prof_01 --json
# {"automation": {"port": 9222, "wsEndpoint": "ws://127.0.0.1:9222/..."}}
python -m nazak.cli cdp active --json

# Secrets / system
python -m nazak.cli secrets get --json
python -m nazak.cli secrets set --mode passphrase --passphrase-stdin --json
python -m nazak.cli system info --json
python -m nazak.cli system doctor --json
python -m nazak.cli system version --json
python -m nazak.cli profile ensure --name "Farm 01" --group "Farm" --json

# Through a running server (unified API validation)
python -m nazak.cli --server http://127.0.0.1:8899 profile list --json
$env:NAZAK_API_TOKEN="secret"; python -m nazak.cli --server http://127.0.0.1:8899 sync status --json
```

## 5. Server Mode

By default commands go **directly through the core** (no server needed). With `--server` the same
commands go through `httpx` to the GUI/web API (the same paths as in `docs/API_REFERENCE.md`).
Exceptions (direct only): `profile bundle-import`, `account import/login` — for these the CLI
honestly returns an error with an explanation instead of a silently wrong result.

## 5b. Profile Storage — JSON (Default) and SQLite (Opt-in)

`ProfileManager` is a facade over the `nazak/core/profiles` package (P0): the store
(`store_json` / `store_sqlite`), the service (`service.py`: CRUD, cloning with
fresh fingerprints, mass-generate clamped to 1..200, batch cookies, bundles,
reencrypt), bundles (zip-slip/zip-bomb protection), on-disk files, mask merging,
limit constants, 10 seed presets. The on-disk `profiles.json` format is unchanged.

```powershell
# JSON (default) — current behaviour, fully compatible
python -m nazak.cli profile list --json

# SQLite (opt-in) — profiles.db next to profiles.json (WAL);
# the first run migrates every valid row from JSON in a single transaction
# and keeps JSON as profiles.pre-sqlite.<ts>.bak (never deleted)
$env:NAZAK_PROFILE_STORE="sqlite"; python -m nazak.cli profile list --json

# Rollback: unset the variable (or set json) — JSON is used again from the next start
$env:NAZAK_PROFILE_STORE="json"; python -m nazak.cli profile list --json
```

Rules: updates in SQLite are point upserts (`save_one`), deletions are
`delete_one`, with no rewrite of the whole file; corrupt JSON no longer
resets the fleet when data exists in SQLite. The plan to make SQLite the default
is in [CHANGELOG.md](../CHANGELOG.md) (the P0 section, gates and rollback).

## 5c. Where Each Piece of Code Lives (P0)

- API: `nazak/api/server.py` — a thin composition root; routers in
  `nazak/api/routers/` (system, profiles, automation, proxies, cookies,
  warmup, synchronizer, autopost); schemas in `nazak/api/schemas.py`; the perimeter in
  `nazak/api/security.py`; realtime in `nazak/api/realtime.py`; lazy singletons in
  `nazak/api/deps.py`. Compatibility: `from nazak.api.server import ...` and
  `patch("nazak.api.server.profile_manager")` work as before.
- GUI background: `nazak/gui/task_bridge.py` (`TaskBridge`: one QThread, busy-guard,
  `cancel()`, headless inline for tests) + `nazak/gui/tasks.py` (Qt-free
  tasks); `nazak/gui/workers.py` — adapters with the same signals as before.

## 6. Exit Codes and Errors

```json
{"success": false, "error": "Profile 'prof_xx' not found", "code": 1}
{"success": false, "error": "Confirmation required", "code": 4, "hint": "profile delete prof_xx --yes"}
```

`1` — profile/file not found · `2` — missing arguments, bad format, empty bulk ·
`4` — already running / queue busy / stop required / no ffmpeg / no `--yes` in a non-interactive context.
In human mode the same error is a red panel in stderr + a dim hint.
