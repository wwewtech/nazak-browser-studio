# Nazak Browser Studio Audit — Round 3: Gaps, Discrepancies, and What Remains Unfixed

> **Status: fixed (Round 3 closed).** All findings in §3–§6 are fixed in the code, except for one
> deliberately deferred (R3-15 still counts as "done": the mypy codes are enabled and 16 errors
> were fixed). What exactly was done is in `CHANGELOG.md` ("Unreleased — Round-3 Audit
> Remediation"). Tests: `tests/test_round3_fixes.py` (29) and
> `tests/test_web_ui_injection_guards.py` (5); `ruff check`, `ruff format --check`, and `mypy`
> (with **all** error codes enabled) are clean. A full run in this environment:
> **659 passed, 9 failed, 0 errors**, where all 9 failures are the absence of `qfluentwidgets` (6)
> and `playwright` (4) from the environment, that is, exactly the same 9 that failed before the fixes.
> The report is kept as a historical audit document: the findings below have not been rewritten.
> The Docker setup was checked separately later — see §10 (a broken build was found and fixed).

This document was compiled from an actual reading of the working-copy code at
`C:\Users\User\Desktop\work\nazak-browser-studio` and from the git history (69 commits, `git rev-list --count HEAD` → 69).
Every statement is backed by a `file:line` reference. Where a check failed, that is stated plainly.

---

## 0. Methodology and Scope of the Review

What was actually executed (not just read):

| Check | Command / method | Result |
|---|---|---|
| Secret leakage in the CLI | own profile under `NAZAK_DATA_DIR`, then `python -m nazak.cli profile get prof_v1 --json` | secrets in plaintext, exit 0 |
| TOTP from the CLI | `python -m nazak.cli account totp prof_v1 --json` | `totp_code: "000000"`, exit 0 |
| Local API guard | `starlette.testclient.TestClient(app)` with different `Host`/`Origin` values | see §3.1 |
| Cookie export without a key | `GET /api/profiles/prof_v1/cookies/export` | 200 + httpOnly cookie in the body |
| Running the tests | `python -m pytest tests -q` (as in `README.md:233`) | startup error, see §6.1 |
| Full test run | `pytest tests -o addopts=""` (temp directory inside the workspace) | `9 failed, 491 passed, 149 warnings, 133 errors in 196.53s` |
| Secrets in git history | `git log --all -p` (patch 7,317,628 bytes, 69 commits) + key-pattern search | see §7 |
| Dependency transitivity | `importlib.metadata` Requires-Dist across 8 installed packages | see §6.2 |
| Static test count | `Select-String '^\s*def test_'` over `tests/**/*.py` | 572 definitions, 55 files |

Environment limitations (important for the honesty of the conclusions):

* `PyQt6-Fluent-Widgets` (`qfluentwidgets`) and `playwright` are **not installed** in this environment, while `cryptography` and `psutil` are installed. That is why some tests fail at import — it is not a code defect.
* The DSH sandbox forbids creating subdirectories inside directories created by `tempfile.mkdtemp`; because of this, 133 errors in the run are `PermissionError` on pytest temporary directories, not project defects.
* Docker/Docker Compose were not started here: the conclusion about the container's network exposure rests on reading `Dockerfile`/`docker-compose.yml` and the official Docker documentation (link in §3.2).
* No second Windows user was created to test cross-user access.
* No real browser was launched to test CSRF/XSS.

---

## 1. Summary of Findings

| ID | Severity | Area | Essence | How verified |
|---|---|---|---|---|
| R3-01 | High | API | The API is unauthenticated; the only protection is the client-supplied `Host`/`Origin` headers | code + execution |
| R3-02 | High | Deployment | The `Dockerfile` binds the API to `0.0.0.0`, `docker-compose.yml` publishes the port on all interfaces, and no token is set | reading + Docker docs |
| R3-03 | High | CLI | `profile get` prints the proxy password and the account password/2FA seed in plaintext | execution |
| R3-04 | High | CLI | `account totp` returns `000000` with `success: true` and exit 0 | execution |
| R3-05 | High | Web UI | DOM XSS: `health.ip/country/city` are inserted into `innerHTML` without escaping; the source is a third-party service's response over HTTP through a proxy | reading both ends of the flow |
| R3-06 | High | Uploader | The Instagram uploader returns `success=true` and a fabricated URL when no publication took place | reading |
| R3-07 | High | Secrets | The default secret storage mode is `plain`; marketplace account passwords and TOTP seeds sit in `data/profiles.json` as plaintext | reading + execution |
| R3-08 | Medium | CLI/scenario | When the id does not match, `account login --profile <id>` silently logs into a **different** account and publishes the video as Public | reading |
| R3-09 | Medium | CLI | The legacy login flow writes a fake `DEMO_MP4_HEADER` file and uploads it to YouTube, then prints "PUBLISHED SUCCESSFULLY" | reading |
| R3-10 | Medium | CSRF | State-changing endpoints are registered as `GET` | code + execution + MDN |
| R3-11 | Medium | Uploader | Retrying a non-idempotent publication → the same video may be published again | reading |
| R3-12 | Medium | API | `/api/autopost/uniquify` accepts an arbitrary absolute file path | reading |
| R3-13 | Medium | API | SSRF race (`TOCTOU`) in `rotate-proxy`: the name is resolved twice | reading |
| R3-14 | Medium | Build | `python -m pytest tests -q` from the README does not work: `addopts` requires `pytest-timeout` | execution |
| R3-15 | Medium | CI | The `mypy` gate disables 13 error categories (including `arg-type`, `call-arg`) | reading the config |
| R3-16 | Medium | Dependencies | `requirements.txt` does not list `psutil` and `cryptography`, which the code imports | reading + metadata |
| R3-17 | Low | API | `testserver` is in the list of "local" hosts; the API key is compared with `==` | execution/reading |
| R3-18 | Low | API | `/docs`, `/openapi.json`, `/static` bypass the guard entirely | reading |
| R3-19 | Low | Web UI | `p.id` is substituted into inline handlers without escaping (not currently exploitable) | reading |
| R3-20 | Low | Web UI | `href` from the YouTube DOM without scheme validation | reading |
| R3-21 | Low | GUI | A second click on "Check" overwrites the reference to the running `QThread` | reading |
| R3-22 | Low | GUI | A blocking `urlopen(timeout=8)` on the Qt main thread | reading |
| R3-23 | Low | Secrets | `_HAS_CRYPTOGRAPHY` is computed but never checked anywhere | grep |
| R3-24 | Low | Secrets | Fail-open when encryption is unavailable: the value stays in plaintext, with only a `warning` in the log | reading |
| R3-25 | Low | Statuses | A stuck job stays `uploading` and the profile stays `RUNNING`; an unknown warmup action counts as success | reading |
| R3-26 | Low | Parser | A password containing the separator is truncated and the remainder goes into the TOTP seed | reading |
| R3-27 | Low | GUI | The passphrase stays in the widget field; 7 characters of the 2FA seed are shown in the table | reading |
| R3-28 | Low | Warmup | `dwell`/`human_scroll` have no duration limit; the scenario comes from the API | reading |
| R3-29 | Low | Process/repository | Swallowed exceptions in the process monitor; no `SECURITY.md` and no dependency scanner | reading + listing |

Documentation/commit discrepancies are covered separately in §6.

---

## 2. What the Commit History Shows

Facts from `git log` (69 commits, author dates 2026-08-23 … 2026-10-03):

1. The project has self-audited at least three times:
   * `948275c` — "add comprehensive English documentation and audit report";
   * `838ccf4` — "add comprehensive audit regression suite and 100 deep defect tests";
   * `d6ba7e6` — "remediate P0/P1 audit findings across stealth, synchronizer, autoposter, secrets, fingerprint and seeder";
   * `f996dfb` — "remediate round-2 findings … (D2-P0-1/2/3, D2-P1-1…5, D2-P2-1/2)".
2. The audit reports were **removed** from the repository: `fa503f7` — "Remove superseded work documents (audit report, deep-analysis plan, remediation progress): all findings are fixed…". The only remaining document is `docs/DEEP_AUDIT_ROUND2.md`, and its line references are stale (see §6.12). In other words, there is no traceable security backlog in the repository right now.
3. `nazak/cli_cmds/*` was added in `98a4042` ("ADD CLI!") and extended in `c0fa3d1` (v1.10.0: `17 files changed, 867 insertions(+)`). That is exactly where the three confirmed High defects R3-03, R3-04, and R3-08/R3-09 live — that is, on the youngest and least-reviewed surface.
4. `nazak/cli_auto_login_and_upload.py` has existed since the first release (`7595011`) and **survived** every audit round: the fake MP4 (R3-09) and the printing of a live TOTP code are still there.
5. Commit `d6ba7e6` claims: "Autoposter: … POST /api/autopost/launch requires a real source or demo=true (generates a genuine ffmpeg clip, **no DEMO_MP4_HEADER blob**)". This holds only for the API path: the string `b"DEMO_MP4_HEADER"` is still present in `nazak/cli_auto_login_and_upload.py:265` (see §5/R3-09).

---

## 3. High Findings

### R3-01. The local API is unauthenticated; the guard relies only on client-supplied headers

**Files:** `nazak/api/server.py:239-309`, `nazak/api/server.py:283-287`, `nazak/config.py:40`

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

Verified by execution (`TestClient`, fresh `NAZAK_DATA_DIR`):

```
Host='127.0.0.1'            -> HTTP 200
Host='testserver'           -> HTTP 200
Host='evil.example.com'     -> HTTP 403
Origin=https://evil.example.com -> 403
Origin=http://localhost:3000     -> 200
GET /v1.0/browser_profiles/prof_v1/stop -> 200        (without X-API-Key)
GET /api/profiles/prof_v1/cookies/export -> 200
   {'format': 'json', 'cookies': [{'name': 'SID', 'value': 'secret-session-value',
     'domain': '.google.com', 'path': '/', 'httpOnly': True, 'secure': True}], ...}
X-API-Key needed? NAZAK_API_TOKEN = None
```

Additionally, the project has **no** client IP check at all — searching `*.py` for the patterns `request.client|client.host|remote_addr|X-Forwarded|trusted` yields no matches.

**Why this is a hole rather than a theory:** only the `Host` header matters, and the client controls it entirely. As long as the server listens on loopback only (`config.py:40`), that confines access to processes on this machine; with any port forwarding to the outside, the filter stops meaning anything (§R3-02). The absence of authentication is documented (`docs/API_REFERENCE.md:8`), so it is a deliberate trade-off rather than an accident — but its consequences in the code are not limited: the API hands out **session cookies for every profile** (`server.py:1154-1167`, `1130-1151`), assembles a `.nazak` bundle containing the profile's `data/` (`server.py:967-994`), starts browsers, and modifies profile data.

**Impact:** any process on the machine (including one running under a different Windows user — loopback is not isolated per user; I did not verify this on a second account) can export Google/YouTube cookies, that is, take over the farm's accounts, and control the browsers.

**What to do:** enable the token by default (generate it on first start and place it in `data/`, with the GUI injecting it automatically), or switch to a Unix socket / named pipe; separately, gate the cookie export behind a separate confirmation.

### R3-02. The repository's Docker deployment exposes the unauthenticated API to the network

**Files:** `Dockerfile:36-38`, `docker-compose.yml:8-13`

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

`NAZAK_API_TOKEN` is not set in the compose file (there is only one environment variable). Docker documents: "When a port is published, it's published to all network interfaces by default" ([Publishing and exposing ports](https://raw.githubusercontent.com/docker/docs/f63001e0752a7337403b2e00fa5ea34e7370048d/content/get-started/docker-concepts/running-containers/publishing-ports.md), checked 2026-10-03).

**Impact:** anyone who can reach port 8899 sends `Host: 127.0.0.1`, passes the guard (verified above), and gets the whole API: cookie export, bundle export, starting browsers, `source_video_path` (§R3-12). I did not reproduce the full chain on a live Docker instance, but every step of it was verified separately.

**What to do:** in `Dockerfile`/`docker-compose.yml`, use `--host 127.0.0.1` (or make `NAZAK_API_TOKEN` mandatory and refuse to start on `0.0.0.0` without a token); add a `USER` directive (the container currently runs as root — there is no `USER` directive in the `Dockerfile`).

### R3-03. `nazak.cli profile get` prints the proxy password and the account password/2FA seed

**File:** `nazak/cli_cmds/profiles.py:190-203`

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

`BrowserProfile` does not exclude the fields (`nazak/models/profile.py:166` `proxy`, `:168` `google`), `ProxyConfig` stores `password`/`raw` as ordinary fields (`nazak/models/proxy.py:40-43`), and when the profile is loaded the proxy fields are decrypted into memory (`nazak/core/profile_manager.py:494`).

Verified by execution (profile `prof_v1`, mode `plain`):

```
exit code: 0
"password": "pxSecret123",
"notes": "{\"account_email\": \"farm.account@gmail.com\", \"account_password\": \"AccPass456!\",
          \"totp_secret\": \"JBSWY3DPEHPK3PXP\", \"_secrets_mode\": \"plain\"}"
```

The masking helper `mask_proxy_dict` (`nazak/cli_cmds/common.py:230-241`) is **never called**: a repository-wide search yields a single match — its own definition.

**Impact:** passwords and TOTP seeds end up in stdout, in CI/agent logs, and in `--json` streams. The masking that exists in the API (`server.py:330-370`) is not wired into the CLI.

**What to do:** apply `decrypt_notes(reveal=False)` + `mask_proxy_dict` before `emit`, and return the full output only with an explicit `--reveal`.

### R3-04. `nazak.cli account totp` returns a wrong code and reports success

**Files:** `nazak/cli_cmds/autopost_accounts.py:378-399`, `nazak/core/secrets_store.py:390`, `nazak/core/account_provisioner.py:39-64`

```python
# autopost_accounts.py:387-398
    try:
        revealed = decrypt_notes(notes)          # reveal defaults to False
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

Verified by execution:

```
{ "success": true, "profile_id": "prof_v1", "totp_code": "000000" }
exit code: 0
[stderr] Error computing TOTP: Non-base32 digit found
```

**Impact:** a command documented as a 2FA generator (`docs/CLI_REFERENCE.md`) and intended for AI agents always returns a non-working code while reporting `success: true` / exit 0. A quiet lie instead of an error — the same flaw also breaks auto-login if it is reused.

**What to do:** call `reveal_notes`/`decrypt_notes(..., reveal=True)`; when the value is masked, return `EXIT_CONFLICT` with explicit text; `generate_totp_rfc6238` must not return `"000000"` — only an exception.

### R3-05. DOM XSS in Web Studio: `health.ip/country/city` are inserted into `innerHTML` without escaping

**Files:** `nazak/web/app.js:361`, `nazak/core/proxy_checker.py:102-118`, `nazak/models/health.py:40-43`

```javascript
// app.js:361 (inside body.innerHTML = `...` at :358)
${health.ip ? `${health.ip} (${health.country || "N/A"}, ${health.city || ""})` : "IP error"}
```

Escaping is applied nearby (`app.js:362` — `escapeHtml(health.isp)`, `:368` — `escapeHtml(health.error_message)`, `:263` — `escapeHtml(ipText)/escapeHtml(geoText)`), but not here.

The source of the values is a third-party service queried **over plain HTTP through the user's proxy**:

```python
# proxy_checker.py:102-111
geo_resp = await client.get(
    "http://ip-api.com/json/?fields=status,message,country,countryCode,regionName,city,isp,as,query,timezone,lat,lon"
)
...
        result.country = geo_data.get("country")
        result.city = geo_data.get("city")
```

The model does not constrain these fields (`health.py:40-43` — plain `str | None`). From there the values reach the UI along two paths: `server.py:853-866` (the `POST /api/profiles/{id}/check` response + `broadcast("profile_health_update")`) → `app.js:342`, or the WS handler `app.js:71-79` → `renderDiagModalContent` (`app.js:350-371`).

**Why this is real:** a malicious/spoofed proxy (or a MITM on this HTTP request) returns a `country` such as `</span><img src=x onerror=...>`, and the script executes in the origin `http://127.0.0.1:8899` — that is, in the API's own origin. From that origin, requests pass both the Host and the Origin checks, which means the script can read the cookie export and the bundles (R3-01). All it takes is opening the "Diagnostics" modal.

**Verified in a real browser (after the fix).** A separate live test
`tests/live/test_dashboard_xss_live.py` starts a real server, opens the dashboard in Chromium, and
replaces the `/api/profiles` and `/api/profiles/{id}/check` responses with malicious values
(`</span><img src=x onerror=…>` in `ip`/`country`/`city` plus a payload that fetches
`/api/security/secrets-mode`), after which it checks the `window.__xss_*` markers along two paths:
a direct call to `renderDiagModalContent()` and the full UI path with a real click on the "Diagnostics" button.

| Run (same image, only `nazak/web/app.js` differs) | Result |
|---|---|
| Fixed code | **the test passes**: markers `country=0, city=0, ip=0, exfil=null`, and the payload is visible in the DOM as text (`&lt;img src=x onerror`) |
| Control: the line rolled back to its pre-fix form (`${health.ip} (${health.country}…)`) | **the test fails**: `country=1, city=1, ip=1`, `exfil=323` — the injected script executed and read 323 bytes of the `/api/security/secrets-mode` response; the `isp` and `error_message` fields, which were escaped even before, do not fire |

So the fix is confirmed by execution, and the test itself is not "blind": it fails on the vulnerable version.
Run: `pytest -m live tests/live/test_dashboard_xss_live.py` (the image includes Chromium; on a host
without `playwright` the test skips correctly).

**What to do:** use `escapeHtml` on `health.ip/country/city` (or build the node via `textContent`); also forbid plain HTTP for the geo request. — **done**: escaping has been added, and plain HTTP for the geo request is flagged as a risk (no separate decision was made to change providers).

### R3-06. The Instagram uploader reports success even when there was no publication

**File:** `nazak/core/instagram_uploader.py:183-222`

```python
                share_btn = self._first(page.locator("button:has-text('Share')"))
                if await asyncio.wait_for(share_btn.is_visible(), timeout=20.0):
                    await self._safe_wait(share_btn.click(), timeout=15.0, label="share button click")
                    await asyncio.sleep(5 * self.delay_scale)
                ...
                return True, published_url or "https://www.instagram.com/", None
```

All the steps (file upload, caption, Next, Share) are wrapped in `if ... is_visible()`; if the dialog never appears, no exception is raised and control reaches `:222`, which returns `True` and a fabricated URL. The upload queue accepts this as success: `upload_queue.py:385-397` sets `job.status = "published"` and broadcasts "Published successfully!".

**Impact:** the operator sees "published" where no publication happened; for a farm this also means losing control (there will be no retries, because there is no error).

**What to do:** make verification of the result mandatory (a `/p/` link appearing or an entry in the profile) and `return False, None, "share dialog not found"` when there is no confirmation.

### R3-07. Account secrets are stored as plaintext by default

**Files:** `nazak/core/secrets_store.py:44,282-293`, `nazak/core/account_provisioner.py:326-339`, `nazak/config.py:33`

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

Verified by execution: after a profile is created, `data/profiles.json` contains
`"account_password": "AccPass456!", "totp_secret": "JBSWY3DPEHPK3PXP"`.

**Impact:** one copy of the file (a backup, cloud sync, a bundle export, an email to support) = full access to the purchased Google accounts together with the 2FA seed.

**Important for objectivity:** this is a documented user choice (`README.md:189-194`: "`plain` — Readable plaintext (**default**, zero setup)"), that is, not a hidden defect but an insecure default. The wording "the user chooses it themselves" does not change the fact that, before any conscious choice is made, all the secrets already sit in plaintext.

**What to do:** ask for the mode explicitly on the first account import (or make `dpapi`/`passphrase` the default, leaving `plain` as an explicit opt-in with a warning).

---

## 4. Medium Findings

### R3-08. `account login --profile <id>` can log into a different account and publish a video

**Files:** `nazak/cli_cmds/autopost_accounts.py:412-414`, `nazak/cli_auto_login_and_upload.py:37-52`, `:322-333`

```python
# autopost_accounts.py:412-414
    if args.profile and not args.email:
        # passed as an email filter by id through env; live_flow can match by name/id
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
            profiles = [google_profs[0]]      # ← silently picks "the first one it finds"
```

The match is a substring match (`in`), not by id/email. Then the flow enters the password and clicks "Publish" with Public visibility (`:322-333`).

**Impact:** a typo in the id leads to working with someone else's (a different) farm account and publishing. There will be no "profile not found" error.

**What to do:** match strictly by `id`/exact email, and on a mismatch exit with code 1 and a hint; only publish when an explicit flag is given.

### R3-09. The legacy login flow uploads a fake MP4 to YouTube and prints a false success

**File:** `nazak/cli_auto_login_and_upload.py:259-265, 330-357`

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

Also in the same file:
* line `:187` prints a **live** TOTP code: `print(f"🛡️ Step 4: 2FA prompt detected! Generating current TOTP code: {code}...")`;
* lines `:80-81` read `account_password`/`totp_secret` straight from the JSON without decryption, so in `dpapi`/`passphrase` modes an envelope, not the password, will be typed into the login fields;
* `cmd_account_login` in `--json` mode redirects all of that stdout to **stderr** (`autopost_accounts.py:419-429`), i.e. the TOTP code will end up in agent/CI logs.

**Impact:** a knowingly invalid file is uploaded to the farm account (an account risk), the publication status is fiction, and a live one-time code leaks into the log.

**What to do:** remove the `DEMO_MP4_HEADER` branch (generate a clip with ffmpeg, as the API path does in `server.py:1368-1410`), stop printing the code, decrypt secrets via `reveal_notes`, and verify that the publication happened before "SUCCESS".

### R3-10. State-changing endpoints are implemented as `GET`

**Files:** `nazak/api/server.py:697-707` (`GET /v1.0/browser_profiles/{id}/start`), `:732-738` (`GET .../stop`), guard `:301-302`

```python
@app.get("/v1.0/browser_profiles/{profile_id}/start", ...)
...
@app.get("/v1.0/browser_profiles/{profile_id}/stop", ...)
```
```python
    origin = request.headers.get("origin")
    if origin and not _is_local_origin(origin):
```

Verified by execution: `GET /v1.0/browser_profiles/prof_v1/stop` → 200 without any authorization headers.

The Origin check runs only when the header is present. MDN: "if a cross-origin `GET` or `HEAD` request is made in [no-cors mode], the `Origin` header will not be added" ([Origin header — MDN](https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Origin), checked 2026-10-03). Consequence: a third-party site can fetch `<img src="http://127.0.0.1:8899/v1.0/browser_profiles/<id>/start">` and start/stop profile browsers (blind CSRF; the response cannot be read, but the effect is there). I did not launch a real browser; the `Origin` behavior is taken from the MDN documentation.

**What to do:** move start/stop to `POST`; for unsafe methods require `Origin` (absent = deny) rather than "absent = allowed".

### R3-11. Retrying a publication can upload the video again

**Files:** `nazak/core/upload_queue.py:22-31,159-161,175-196,361-368`, `nazak/core/youtube_uploader.py:213-247`

```python
RETRYABLE_UPLOAD_ERRORS = ("timeout", "temporarily unavailable", "429", "403", "rate limit",
                           "network", "session disconnected", "connection closed")
...
        return any(token in lowered for token in RETRYABLE_UPLOAD_ERRORS)
```

`upload_shorts` clicks "Publish" (`youtube_uploader.py:216-217`) and only afterwards polls the URL, calls `browser.close()`, and calls `notify_progress` (`:220-244`). Any exception in these steps returns `False` (`:246-247`), and `_retryable_upload` will repeat the **entire** cycle up to 3 times if the error text contains one of the tokens (for example, `Timeout 30000ms exceeded`).

**Impact:** duplicate publications on the farm's accounts. The precondition is that the error text matches a token; it is not unconditional (I did not check exactly what Playwright returns).

**What to do:** after a successful "Publish" click, treat the attempt as non-reproducible (`non-idempotent`), and remove "403" from the retry list (see R3-25/below).

### R3-12. `/api/autopost/uniquify` accepts an arbitrary absolute path

**File:** `nazak/api/server.py:1354-1365`

```python
async def uniquify_videos_endpoint(req: UniquifyRequest):
    for pid in req.profile_ids:
        validate_pid(pid)
    src = Path(req.source_video_path)
    if not src.exists():
        raise HTTPException(status_code=400, detail=f"Source video not found: {req.source_video_path}")
    results = await asyncio.to_thread(video_uniquifier.batch_uniquify, src, req.profile_ids)
```

**Impact:** a file-existence oracle (`400 Source video not found` versus starting ffmpeg) and passing an arbitrary local file to the ffmpeg parser; the result is written to `DATA_DIR/videos/output` (`video_uniquifier.py:77-78`), where there is no traversal. I was unable to confirm reading the contents of an arbitrary file through this endpoint, so I am not claiming "file read".

**What to do:** a directory whitelist (for example, only `DATA_DIR/videos`) + an `is_relative_to` check, plus extension/signature validation.

### R3-13. SSRF race (`TOCTOU`) in `rotate-proxy`

**File:** `nazak/api/server.py:1035-1082`, `:1096-1101`

```python
    addresses = _resolve_host_ips(parts.hostname, port)   # first name resolution
    ...
        if not ip.is_global:
            return "host must be a public address"
```
```python
        req = urllib.request.Request(url, headers={"User-Agent": "Nazak-Studio"})
        with _NO_REDIRECT_OPENER.open(req, timeout=10.0) as resp:   # second name resolution
```

The check uses the IP from the first resolution, while `urllib` resolves the name again when connecting. With DNS that returns alternating answers (public → private), the filter is bypassed. I did not reproduce the exploitation (no controlled DNS); the fact of the double resolution comes from the code. It additionally requires that the attacker be able to write `rotation_url` (through the API, see R3-01/R3-02).

**What to do:** resolve once and connect to the verified IP (for example, `http.client` with a `Host` header), or use an `ipaddress` allowlist and connection pinning.

### R3-14. The documented test command does not run

**Files:** `README.md:232-238`, `pyproject.toml:150`, `pyproject.toml:52-55`, `requirements.txt:11-14`

```
addopts = "-p no:asyncio --strict-markers -ra --timeout=30 --timeout-method=thread -m 'not live'"   # pyproject.toml:150
```
`pytest-timeout` is declared only in the dev extra (`pyproject.toml:55`); `requirements.txt` does not have it.

Verified by execution:

```
$ python -m pytest tests -q
ERROR: usage: python -m pytest [options] [file_or_dir] [...]
python -m pytest: error: unrecognized arguments: --timeout=30 --timeout-method=thread
```

**Impact:** the "Quick Start" path (`pip install -r requirements.txt` → `pytest`) does not work; this is also confirmed by commit `5f7a7d4`, which added `pytest-timeout` to CI but not to `requirements.txt`.

**What to do:** add `pytest-timeout` to `requirements.txt` or remove `--timeout*` from `addopts` in `[tool.pytest.ini_options]`.

### R3-15. The `mypy` gate disables almost all meaningful checks

**File:** `pyproject.toml:183-205`

```toml
disable_error_code = [
    "no-redef", "arg-type", "dict-item", "assignment", "index", "import-untyped",
    "override", "misc", "attr-defined", "call-arg", "call-overload", "valid-type",
]
```
At the same time, CI declares this as a separate job, "Type Analysis (MyPy)", and fails on an error (`ci.yml:43-64`).

**Impact:** a green mypy in CI does not mean type correctness: wrong argument types, assignments, calls with wrong arguments, and accesses to non-existent attributes are suppressed. This is also borne out by finding R3-23 (`_HAS_CRYPTOGRAPHY` is declared and never used — mypy will not catch that).

**What to do:** narrow the list by enabling at least `arg-type`, `call-arg`, and `attr-defined`, and fix the errors module by module.

### R3-16. `requirements.txt` does not contain `psutil` and `cryptography`, which the code needs

**Files:** `requirements.txt:1-14`, `nazak/core/browser_launcher.py:18`, `nazak/models/profile.py` (via `secrets_store`), `pyproject.toml:41,47`

```
18: import psutil        # browser_launcher.py — a module-level import, pulled in from nazak/__init__.py
```

Verified with the metadata of the installed packages (`importlib.metadata`, `Requires-Dist`): none of `fastapi 0.131.0`, `uvicorn 0.41.0`, `pydantic 2.12.5`, `httpx 0.28.1`, `requests 2.32.5`, `PySocks 1.7.1`, `PyQt6 6.11.0`, `rich 14.3.3`, `pytest 9.1.1`, `websockets 16.0` requires `psutil` or `cryptography`. `PyQt6-Fluent-Widgets`, `pytest-asyncio`, and `playwright` are not installed in this environment — I could not check their metadata.

**Impact:** in a clean environment following the instructions in `README.md:208-210`, the application should crash on `import psutil`; `cryptography` is needed for the `passphrase` mode (there the `import` is guarded by `try/except`, but the flag is not used — R3-23). The Docker build uses the same `requirements.txt` (`Dockerfile:30-31`).

**What to do:** synchronize `requirements.txt` with `pyproject.toml:34-48`.

---

## 5. Low Findings

* **R3-17** `_LOCAL_HOSTS` includes `"testserver"` (`server.py:239`) — verified: `Host: testserver` → 200. The API key is compared with `==` (`server.py:287`) rather than `hmac.compare_digest`.
* **R3-18** The prefixes `/static`, `/docs`, `/redoc`, `/openapi.json`, `/swagger` exit the middleware before the checks (`server.py:293-294`) — the API schema and static files are served for any `Host`.
* **R3-19** `p.id` without escaping in inline handlers (`app.js:244, 269, 271-289`). Not exploitable at present: the id is validated against `^[a-zA-Z0-9_\-]+$` (`server.py:325-326`, `profile_manager.py:179`). The risk will appear if the rule is loosened or `profiles.json` is edited by hand.
* **R3-20** `href="${escapeHtml(j.video_url)}"` (`app.js:853`) — escaping is present, scheme validation is not; the source is the YouTube Studio DOM (`youtube_uploader.py:227`).
* **R3-21** `self.check_worker = ProxyCheckWorker(...)` without an `isRunning()` check (`gui/views/profiles_view.py:450`); the same pattern with a different class — `self.worker = CheckAllProxiesWorker(...)` (`gui/views/proxies_view.py:216-218`) — a repeat click loses the last reference to the running `QThread`, which for Qt ends in a crash. A correct example exists in `gui/views/warmup_view.py:249, 335`.
* **R3-22** `urllib.request.urlopen(req, timeout=8.0)` for a user-supplied `rotation_url` is called from a button handler on the Qt main thread (`gui/views/proxies_view.py:157, 162-170`) — the UI freezes for up to 8 s.
* **R3-23** `_HAS_CRYPTOGRAPHY` is assigned (`secrets_store.py:37,39`) and never read (grep: only those two lines). Without `cryptography`, choosing the `passphrase` mode will produce a `NameError` instead of a clear error.
* **R3-24** Fail-open when encryption is unavailable: `encrypt_notes`/`protect_proxy_fields` write the value in plaintext and only log a `warning` (`secrets_store.py:352-353, 460-463`). This is a deliberate decision with a comment, but in practice "a strong mode was chosen" and "the value is in plaintext" coexist.
* **R3-25** Status honesty: `try/finally` without `except` (`upload_queue.py:321, 369-382`) leaves the job in `uploading` and the profile in `RUNNING` on an unexpected exception; an unknown warmup action returns `True` (`warmup_engine.py:350`); "403" is treated as retryable (`upload_queue.py:25`); `normalize_upload_platform` is case-sensitive (`upload_queue.py:47-56`) — `"Instagram_Reels"` silently becomes `youtube_shorts`; `cancel_all` kills browsers it did not start itself (`upload_queue.py:144-151`).
* **R3-26** `parse_account_string` (`account_provisioner.py:81-97`): a password containing the chosen separator is truncated (`p@ss:w0rd` → `p@ss`, and the remainder goes into `totp_secret`); lines with a different separator produce a garbage email. There is no format validation, and malformed lines are discarded silently (`:78-79`).
* **R3-27** GUI: the passphrase stays in the field after it is applied (`gui/views/secrets_mode_card.py:98` reads `passphrase_edit.text()`, and there are no `.clear()` calls in the file; `settings_view.py:181` does clear it); the accounts table displays a masked 2FA seed — 7 characters (`gui/views/accounts_view.py:327` `notes = decrypt_notes(notes)` → `:354` `totp_sec = notes.get("totp_secret","")` → `:364` the table cell; `mask_secret` — `secrets_store.py:74-80`), while the full seed is placed into `Qt.ItemDataRole.UserRole` (`accounts_view.py:368`).
* **R3-28** `warmup_engine.py:332-336, 362-367`: `dwell` with `min_sec`/`max_sec` and `human_scroll` with `duration_sec` are unbounded; the scenario can be supplied through the API (`server.py:1223-1224`), and such a step permanently occupies one of the 10 concurrency slots (`warmup_engine.py:458`).
* **R3-29** `process_monitor._monitor_loop` swallows all exceptions (`process_monitor.py:67-68`); there is no `SECURITY.md`, no `dependabot.yml`, and no dependency vulnerability scanner (in `.github/workflows` there are only `ci.yml`, `release.yml`, `security.yml` = CodeQL).

---

## 6. Discrepancies Between Documentation, Commits, and Code

1. **Tests.** `README.md:19,230,237` — "631 automated tests", "631 passed, 2 deselected". Verified: `pytest tests --collect-only -q -o addopts=""` → **633** node ids, with `-m "not live"` → **631 of 633** (2 deselected). Statically, `tests/**/*.py` contains **572** `def test_` lines, 2 of which are fixtures, and 10 `parametrize` decorators expand the count to 633. So the number 631 is correct as "collected node ids", but I **did not reproduce** an actual "631 passed" run: in this environment it is `9 failed, 491 passed, 133 errors`. All the failures I inspected are `ModuleNotFoundError: qfluentwidgets` (6) and `playwright` (4); all 133 errors are sandbox `PermissionError`s on temporary directories. "I cannot confirm" applies specifically to the "631 passed" line.
2. `README.md:255` — "`test_deep_api_and_scenarios.py` — 25 API & scenario integration tests"; in fact there are 28 `def test_` (counted in the file).
3. `README.md:75` documents the `start` response as `automation: {port, wsEndpoint, ws_endpoint}`; `server.py:724-729` returns only `{port, wsEndpoint}` (`ws_endpoint` exists only in `browser_launcher.py:441`).
4. `README.md:249` — "single-use state tokens, TLS-only callback URL validation". In the code the state is compared (`account_provisioner.py:157-168`) but is not invalidated after use, and `redirect_uri` defaults to `http://127.0.0.1:3000` (`:364`). There are no tests for this in `tests/test_oauth_state_security.py`.
5. `docs/API_REFERENCE.md:8` and `CHANGELOG.md:35` — "CORS reflects 8899/3000 plus the port passed with `--port`". The CORS list and regex are hard-coded (`server.py:216-228`); `--port` only extends `_ALLOWED_PORTS` (`server.py:240,247-250`), which is used in `_is_local_origin` (`:280`) — that is, CORS itself does not "reflect" the port.
6. `README.md:209` `pip install -r requirements.txt` — see R3-16: the file lacks `psutil` and `cryptography`.
7. `CHANGELOG.md:45` — "audio_noise_seed is random again"; in `profile_manager.py:449` the value is deterministic (`0.000001 * idx`), and with `idx=0` it is `0.0`.
8. `README.md:244` attributes the `Emulation.setTimezoneOverride`/`setUserAgentOverride` tests to `test_advanced_stealth_and_seeder.py`; they are in `test_cdp_injector.py:119,122`.
9. Versions: `nazak/__init__.py:5`, `pyproject.toml:7`, `version_info.txt`, `README.md:19,26` — 1.10.0; yet `installer.iss:8` and `build_exe.py:43,45` contain a fallback of `"1.9.1"`, `release.yml:12` uses the default tag `v1.4.1`, `gui/splash.py:121` draws `v1.3.0`, and `start_macos.sh:69,87` says "271 tests".
10. `docs/API_REFERENCE.md:402` — "Requires a real `source_video_path` (400 if missing)"; in fact there is a fallback to `DATA_DIR/videos/source.mp4` (`server.py:1427-1444`).
11. `docs/API_REFERENCE.md:476` and `README.md:166` describe `--time-zone-for-testing` as "C++-side alignment", whereas `cdp_injector.py:12-13` states plainly that the flag "was proven dead in the audit" (the flag is still added in `browser_launcher.py:247`, and `TZ` in `:350-352`).
12. `docs/DEEP_AUDIT_ROUND2.md:257,264` references `POST /api/profiles/{profile_id}/export` and `POST /api/profiles/import` — no such routes exist in `server.py`; the line references in that document are stale (for example, `:205-217` versus the actual `214-228`). I cannot confirm the historical state, but the document itself is misleading now.

---

## 7. What Was Checked and NOT Confirmed (No Less Important Than the Findings)

* **There are no secrets in the git history.** Scanning the full history patch (`git log --all -p`, 7,317,628 bytes, 69 commits) for private key / `AKIA…` / `ghp_…` / `AIza…` / `xox[baprs]-…` patterns produced **one** match — the line `"response": "AKIAIOSFODNN7EXAMPLE / super-secret-token"` in `docs/DEEP_AUDIT_ROUND2.md:174`. That is an example key from the public AWS documentation, used as a test string, not a real credential.
* **Historical versions of `data/profiles.json`** (commits `7595011`, `1ea6efe`, `452700d`, `06e4aec`; the file stopped being tracked in `9caefc8`) contain only `"password": null` and human-readable `notes` — there are no credentials in them.
* **Zip-slip is protected against:** `profile_manager.py:1119-1124` (absolute paths, drive, `..`, `is_relative_to`); the cookie-ZIP import reads the archive into memory and extracts nothing (`cookie_manager.py:219-247`).
* **Secret masking works in the API:** `server.py:330-370`, `secrets_store.py:74-80, 388-390`; `_totp_raw` appears only with `reveal=True`.
* **There is no command injection:** searching `*.py` outside the tests for `shell=True|os.system|os.popen|eval(|exec(` yields no matches; ffmpeg and Chrome are launched with an argument list (`video_uniquifier.py:112-139`, `browser_launcher.py:358`), `custom_url` is filtered by `sanitize_launch_url` (`browser_launcher.py:34-56`) and covered by a test (`tests/test_audit_round2_regressions.py:116-127`).
* **There is no SQL injection:** `history_seeder.py` uses parameterized queries (`:162, 167-178, 211-217`).
* **Profile paths are protected:** `validate_pid` (`server.py:312-327`) and `_validate_id` (`profile_manager.py:166-180`) forbid `/`, `\`, `:`, `..`; deleting data requires `is_relative_to` (`:678-683`).
* **The OAuth CSRF token is generated by a CSPRNG:** `secrets.token_urlsafe(32)` (`account_provisioner.py:124`); the callback listens on loopback only (`:247`); `?error=` is escaped (`:188`). One caveat — `listen_for_oauth_code(state=None)` makes the check optional (`:382-391`), but **I found no calls to this method outside the tests** (grep: only `tests/`).
* **`automate_google_login` reports success without verifying the result** (`account_provisioner.py:614-628`), but **there are no calls to it in the repository** (only the definition) — so this is a latent defect rather than an active hole.
* **CORS is limited to exact ports** (`server.py:214-228`), and the regex does not accept an arbitrary port (verified: `Origin=http://localhost:3000` → 200, `Origin=https://evil.example.com` → 403).

---

## 8. What I Could NOT Verify (Stated Plainly)

1. The line "631 passed" from `README.md:237` — the environment does not allow a clean run (no `qfluentwidgets`/`playwright`, and the sandbox breaks pytest's temporary directories). *(Updated: the numbers in the README have been brought in line with reality — 669 collected / 666 selected / 3 live deselected.)*
2. ~~Execution of the XSS (R3-05) in a real browser.~~ **Verified**: a live test in Chromium + differential control (see §3/R3-05).
3. CSRF via a no-cors GET (R3-10) in a real browser: the absence of `Origin` is taken from MDN.
4. Exploitation of the DNS-rebinding SSRF (R3-13) — no controlled DNS.
5. Reading arbitrary files through `/api/autopost/uniquify` (R3-12) — I do not confirm that the contents leak.
6. Cross-user access on Windows (R3-01) — no second account was created.
7. Running the Docker configuration (R3-02) — the chain is assembled from verified links, but was not reproduced end to end.
8. The dependency metadata of `PyQt6-Fluent-Widgets`, `pytest-asyncio`, and `playwright` (not installed here) — which is why I claim "`psutil` does not arrive transitively" only for the 10 packages I checked.
9. The historical state of the code that `docs/DEEP_AUDIT_ROUND2.md` refers to.
10. `docker build` / `docker compose up` end to end — see §10: the Docker engine does not start on
    this machine (no WSL2, which needs admin rights + a reboot). Everything that can be checked
    without the daemon has been checked; `docker build` itself has been moved into the CI job `docker.yml`.

---

## 10. Docker Setup: Verified on a Real Engine

This check was performed after §3–§6 were closed, with Docker already working:

* `winget install Docker.DockerDesktop` → **Docker 29.8.2, Docker Compose 5.5.1**.
  The engine did not start at first: the Docker Desktop log
  (`%LOCALAPPDATA%\Docker\log\host\monitor.log`) contained
  `[main.wslexec][E] c:\windows\system32\wsl.exe --version failed: exit status 1` and
  `[main.engines][E] … engine linux/wsl failed to start: checking preconditions: checking WSL version: wsl is not installed`
  with the message "Install it by running `wsl --install` in an administrative PowerShell, then restart your computer".
  WSL was absent, and the agent's shell was not elevated (`elevated: False`).
* With the user's agreement, WSL was installed with elevation (UAC):
  `wsl --install --no-distribution` → "Downloading: Windows Subsystem for Linux 3.0.1 … Installation complete",
  then `wsl --version` → **WSL 3.0.1.0, kernel 6.18.40.1-1**, default version 2.
  Despite `RebootPending: True` in CBS, the engine came up without a reboot:
  `docker info` → `29.8.2 | Docker Desktop (containerized) | docker-desktop`.

### R3-30 (High, fixed and verified by a build) — the `Dockerfile` did not build: package names from a different Debian version

The original `Dockerfile:2` used `FROM python:3.11-slim`, while its apt package list (`:9-28`) used names
from bookworm. The base image, however, was already trixie — confirmed by **running the image**:
`docker run --rm python:3.11-slim cat /etc/os-release` → `PRETTY_NAME="Debian GNU/Linux 13 (trixie)"`,
`VERSION_CODENAME=trixie`; the entry in `docker-library/official-images`:
`Tags: 3.11.17-slim-trixie, 3.11-slim-trixie, 3.11.17-slim, 3.11-slim` / `Directory: 3.11/slim-trixie`.
According to the Debian madison service (`api.ftp-master.debian.org/madison`), these packages do not exist in stable (trixie):

| Package in the Dockerfile | stable (trixie) | Replacement |
|---|---|---|
| `libgl1-mesa-glx` | no (bullseye/bookworm only) | `libgl1` |
| `libglib2.0-0` | no | `libglib2.0-0t64` |
| `libatk1.0-0` | no | `libatk1.0-0t64` |
| `libatk-bridge2.0-0` | no | `libatk-bridge2.0-0t64` |
| `libcups2` | no | `libcups2t64` |
| `libasound2` | no | `libasound2t64` |

**The breakage was reproduced** by building the same package list on `python:3.11-slim`:
`E: Package 'libgl1-mesa-glx' has no installation candidate` → `apt` exit 100, `docker build` exit 1.
The fix (base `python:3.11-slim-trixie`, names `libgl1`/`…t64`, unused `curl` removed):
**`docker build` passes, exit 0**; `hadolint 2.15.1` → exit 0 (`DL3008` silenced by
`# hadolint ignore=DL3008` with the justification that pinning apt versions in a floating base image
would break the build otherwise).

### R3-31 (High, fixed and verified) — there was no `.dockerignore`: local secrets were shipped into the image

`COPY . .` without a `.dockerignore` puts the entire contents of the build directory into the image layers, including
`data/profiles.json` (account passwords and TOTP seeds in `plain` mode), the profiles' cookie/session
files, and the whole `.git` history. Per `dockerignore(5)`: "the CLI modifies the context to exclude
files and directories that match patterns specified in the file. This avoids adding them to
images using the ADD or COPY instruction". A `.dockerignore` was added (data/, .git/, .github/,
secrets, caches, build artifacts). **Verified in the built image**:
`ls -a /app` contains no `data` and no `.git`.

### R3-32 (Medium, fixed and verified) — compose exposed the port on all interfaces

It used to be `ports: - "8899:8899"` (Docker publishes on all host interfaces) and no token was set.
Now: loopback only + a mandatory token. **Verified with real Compose**:
`docker compose config` → `host_ip: 127.0.0.1`, `published: "8899"`, `NAZAK_API_TOKEN: ci-compose-token`;
without the variable, `docker compose config -q` fails with
"required variable NAZAK_API_TOKEN is missing a value: set NAZAK_API_TOKEN in a .env file next to docker-compose.yml"
(exit 1). The obsolete `version: '3.8'` was removed; `.env.example` was added.

### R3-33 (infrastructure) — a CI job with a real `docker build`

`.github/workflows/docker.yml` (only on changes to Docker files + `workflow_dispatch`):
`docker compose config -q` → `docker build` → refusal to start without a token → the HTTP contract → logs and
cleanup. Checked with `actionlint 1.7.12` (exit 0). The same steps are now confirmed locally as well (below),
so the job replays an already-verified scenario on every push.

### What Exactly Was Verified on Real Docker (all steps are reproducible)

| Check | Command/method | Result |
|---|---|---|
| Image build | `docker build -t nazak-r3-verify .` | **exit 0** (layers: apt → pip → `playwright install chromium --with-deps` 114 MiB → COPY) |
| `.dockerignore` | `docker run --rm --entrypoint sh IMAGE -c "ls -a /app"` | `NO_GIT`, `NO_DATA` |
| Dependencies in the image | `docker run --rm --entrypoint python IMAGE -c "import psutil, cryptography, nazak"` | `deps-ok 1.10.0 7.2.2 50.0.2` |
| Refusal without a token | `docker run --rm -e NAZAK_API_TOKEN= IMAGE` | exit 1 + the text "…`NAZAK_API_TOKEN` is not set. Options: 1) … 2) …" |
| HTTP contract | `docker run -e NAZAK_API_TOKEN=… -p 127.0.0.1:18899:8899 IMAGE` | without a key `401`; with a key `200` (`status=online`); wrong key `401`; foreign `Host` `403`; foreign `Origin` `403`; `Sec-Fetch-Site: cross-site` `403`; `/openapi.json` with a foreign `Host` `403`, local `200` |
| Web dashboard | `GET /` | `200` + HTML |
| **`docker compose up -d --build`** | real Compose | container `Up`, ports `127.0.0.1:8899->8899/tcp`; without a key `401`, with a key `200`; `docker compose down` removed the container and the network |
| Original Dockerfile | building the old package list | `E: Package 'libgl1-mesa-glx' has no installation candidate` (confirmation of R3-30) |

Bottom line: **16/16 container checks and 8/8 steps of the compose scenario passed**; the test images and
the runtime data from `data/` were deleted after the check, and no containers were left behind.

---

## 9. Proposed Remediation Order

1. **R3-01/R3-02** — a token by default + a ban on `0.0.0.0` without a token; restrict what the cookie export hands out. This is the only finding where the damage is the theft of every account on the farm.
2. **R3-03/R3-04/R3-08/R3-09** — CLI: mask secrets, fix TOTP, remove the "first profile" fallback, delete `DEMO_MP4_HEADER`, and stop printing live codes.
3. **R3-05** — escape `health.*`; also remove HTTP for the geo request.
4. **R3-06/R3-11** — an honest publication status + no retry after the "Publish" click.
5. **R3-07** — make the secure storage mode the default, or ask on import.
6. **R3-14/R3-16/R3-15** — bring `requirements.txt` and `addopts` into working order, and narrow `disable_error_code`.
7. **R3-10/R3-12/R3-13** — methods / path validation / IP pinning.
8. Everything else — per the table in §1.

---

## 11. Second Audit Pass (round-3b): Areas Not Covered in §1–§10

The first pass closed out the API perimeter, the CLI secrets, publication honesty, warmup, and Docker.
The second pass deliberately looked where I had not yet read the code: `index.html` and
the dashboard's font dependencies, the stealth-JS generator in its entirety, `cdp_injector` (the
CDP loop), `synchronizer`, `cli_cmds/automation.py`, `gui/dialogs/*`, `nazak/tools/*`,
`build_exe.py`/`installer.iss` (the release build), `profile_manager.import_profile_bundle`
and cookie-ZIP, as well as all the pydantic API request models for their bounds.

### Summary

| # | Finding | Severity | How I checked | Status |
|---|---|---|---|---|
| R3b-01 | `scenario run` without `--wait`: the daemon thread was killed by `SystemExit`, and the command printed success | High | repro of the mechanism + reading | fixed, test |
| R3b-02 | A negative `min_delay_ms` → a `ValueError` outside `try` killed the pump thread, and `session.active` stayed `True` | Medium | execution: `_mirror_one` raised `ValueError('sleep length must be non-negative')` | fixed, tests |
| R3b-03 | `Infinity`/`NaN` from JSON were accepted by the models → the literals `inf`/`nan` ended up in stealth.js | Medium | end-to-end run: POST 200 → `() => inf`, `const factor = nan` | fixed, tests |
| R3b-04 | `MassGenerateRequest.count` with no upper bound → O(n²) rewrites of `profiles.json` | Medium | measurement: 20→0.06 s, 40→0.15 s, 80→0.43 s | fixed, tests |
| R3b-05 | `AutopostBatchRequest.delay_seconds` with no bound → the batch would "sleep" for years, blocking `is_running` | Medium | calculation + reading `upload_queue.py:227` | fixed, tests |
| R3b-06 | `.nazak` and cookie-ZIP were extracted without limits | Medium | measurement: a 100 KiB archive → 100 MiB on disk | fixed, tests |
| R3b-07 | The release build shipped the runtime `data/` (including `profiles.json`) into the ZIP and the installer | Medium | the frozen path was reproduced: `data/{profiles.json,profiles,extensions,logs}` next to the exe | fixed, test |
| R3b-08 | The GUI workers used a predictable CDP port range, `9350 + idx` | Low-Medium | reading + grep | fixed, test |
| R3b-09 | `Runtime.addBinding` was installed in every session: any page of the wizard (including an iframe) could dictate clicks in other profiles' browsers | High | reading the chain `_on_binding_called → submit_event → _dispatch_event` | fixed, tests |
| R3b-10/11 | Not a single security header; CSP was absent | Medium | grep across the repository + a live server | fixed (partial CSP), tests |
| R3b-12 | GUI: cache deletion without confirmation, a false success on cookie import | Medium | reading | fixed, static tests |
| R3b-13 | The injected JS contained page-visible markers `__nazakShieldApplied`, `__nazakSyncInstalled`, `__nazak_sync_event` | Low (Medium for anti-detection) | generating stealth.js and checking its contents | fixed, tests |
| R3b-14 | Minor items: `${e.message}` in `innerHTML`, `target="_blank"` without `rel`, Google Fonts from a CDN, `D:/nazak/...` in the tools, "V1.3.0" in an asset, a docstring of 1..500 versus a slider of 1..100, an unbounded event queue, inline parsing of the binding in the CDP loop, `cols<0` | Low | reading + execution | fixed |

### R3b-01. `nazak scenario run` without `--wait` reported success without doing the work

`cli_cmds/automation.py:196-207` (before the fix) started `threading.Thread(target=_bg, daemon=True)`
and immediately returned `emit_success`. `nazak/main.py:90` and `:139` — `raise SystemExit(run_cli())`,
so the interpreter exited immediately and the daemon thread was destroyed. Reproduced with
a separate repro: the process prints "success reported, exiting now", `exit=0`, while the marker file,
which the thread was supposed to create after 1.5 s, had not appeared even after 2.5 s.

**Fixed:** the background work is a separate process (`subprocess.Popen` with `DETACHED_PROCESS |
CREATE_NEW_PROCESS_GROUP` on Windows, `start_new_session=True` on POSIX), stdout/stderr
are written to `data/logs/scenario_<timestamp>.log`, and the JSON response carries the `pid` and the log path; if
the process cannot be started, there is an honest error with a hint about `--wait`. I did not run the
command end to end, so as not to bring up a real browser on the user's machine.

### R3b-02. A negative jitter killed the synchronizer while the status stayed "active"

`synchronizer.py:355-356` (before the fix) — `time.sleep(delay_ms / 1000.0)` sat **outside**
the per-event `try` (line 357). `SynchronizerStartRequest.min_delay_ms` (`server.py:542`)
and the CLI `--min-delay` had no lower bound. Execution confirmed it:
`_mirror_one` with the interval `(-1.0, -0.5)` raised `ValueError('sleep length must be non-negative')`;
in `_mirror_pump` it was caught by an `except` (line 316) that logged a warning and exited **without
resetting `session.active`** — `get_status()` kept returning `active: true`, and
`mirror_navigation` waited for a response for up to 110 s.

**Fixed:** `_clamp_delay_range()` normalizes the interval (non-negative,
ordered, ≤60 s) and is called both in `SynchronizerSession.__init__` and before the sleep;
the sleep was moved inside the `try`; the pump's `finally` sets `session.active = False` and
records `last_error`; `mirror_navigation` checks that the thread is alive and does not wait on a dead pump;
the event queue is bounded by `MAX_PENDING_EVENTS` with an honest `dropped_events` counter.

### R3b-03. `Infinity`/`NaN` broke stealth.js

`json.loads` accepts the literals `Infinity`/`NaN`, pydantic v2 does not reject them
by default, and the stealth-JS template substituted two float fields via `str()`
(`extension_generator.py:335` — `device_pixel_ratio`, `:601` — `audio_noise_seed`).
End-to-end run: `POST /api/profiles` with `{"device_pixel_ratio":Infinity,"audio_noise_seed":NaN}`
→ **HTTP 200**, `inf`/`nan` in the model, and in `stealth.js`:

```
Object.defineProperty(Window.prototype, 'devicePixelRatio', { get: makeNative(() => inf, ...
const factor = nan || 0.00001;
```

`inf`/`nan` are not JS identifiers (the language has `Infinity`/`NaN`): the first produces a ReferenceError on
every read of `devicePixelRatio` (the page breaks, which is a glaring sign of spoofing), and the second is
swallowed by an outer `try/catch` → the audio noise was silently disabled.

**Fixed:** `allow_inf_nan=False` in `FingerprintConfig`/`BatterySpoofConfig`/
`GeolocationSpoofConfig`; `_js_number()` in the generator (defense in depth: `inf`→`Infinity`,
`nan`→`0` with a warning); the validation response no longer fails with a 500 — `RequestValidationError`
is handled safely (see R3b-10/11); non-numeric `lat/lon` and over-long strings from the
geo response are sanitized in `proxy_checker` (`_finite_or_none`, `_safe_text`, `_safe_timezone`).

### R3b-04 / R3b-05. Missing bounds on numeric request fields

Not a single request model had `Field(ge/le)` (`server.py:464-553` before the fix). A measurement of
the cost of `mass_generate_profiles` (each profile rewrites the entire `profiles.json`):
`count=20 → 0.06 s`, `40 → 0.15 s`, `80 → 0.43 s` — that is, a single request with `count=10000`
hangs the server for hours (the CLI, by contrast, always validated `1..200`). For `delay_seconds`,
`upload_queue.py:433` computed `random.randint(max(5, d-3), d+5)`, and entry into a new batch is
blocked while the current one runs (`upload_queue.py:227`) — `delay_seconds=10**9` meant a pause of
≈31 years and autoposting switched off until a restart.

**Fixed:** bounds in the models (`count 1..200`, `delay_seconds 0..3600`, `min/max_delay_ms
0..60000`, `coordinate_jitter_px 0..50`, `cols 1..8`, `cdp_port 1..65535`, `max_concurrency
1..10`, `steps_count 1..20`, `max_length` for strings and lists, `format` by pattern) plus
**duplicate clamps in the service layer** (`mass_generate_profiles`, `run_batch_upload`,
`SynchronizerSession`, `tile_windows_win32`). The lower bounds that governed the endpoints'
400 contract were deliberately not added — it was verified that the three existing tests for 400
pass.

### R3b-06. Zip bomb in the bundle and cookie archive import

`profile_manager.py:1090/1115/1131` used only `namelist()`/`read()` — no check of
`ZipInfo.file_size`, no entry counter. Measurement: an archive of **100 KiB → 100 MiB** written to
disk (5 entries of 20 MiB of zeros each). The cookie ZIP (`cookie_manager.py:233`) was read into memory in full.

**Fixed:** limits on the number of entries (20,000 / 200), on a single entry (512 MiB / 32 MiB), and on the
total (1 GiB / 64 MiB); the bundle is extracted as a stream with real byte counting (the declared
`file_size` can be forged downwards), and when a limit is exceeded the extraction is refused and the half-extracted directory is deleted.

### R3b-07. Release artifacts shipped `data/`

A frozen application keeps its data next to itself (`config.py:13-17`, `DATA_DIR = EXE_DIR/data`),
and `build_exe.py:182` runs the built exe as part of the build — after which
`dist/NazakBrowserStudio/data/` contains `profiles.json`, `profiles/`, `logs/`, and
`extensions/`. The ZIP packs any file under `APP_DIR` (`build_exe.py:204-209`), and the installer
copies everything recursively (`installer.iss:59`). Reproduced on the frozen path: next to a
fake exe, `data/{profiles.json,profiles,extensions,logs,videos}` is created; in
`profiles.json` there are 10 default profiles (verified: no passwords or 2FA in them). Today this is
not a leak, but it is exactly the directory where passwords and 2FA seeds live in `plain` mode.

**Fixed:** `sanitize_app_data()` in `build_exe.py` (called between `smoke_test()` and
`package_zip()`; it deletes the runtime files and directories and restores `data/assets` for the icon)
plus a second layer — `Excludes:` in `installer.iss`. I did not run a full `pyinstaller`/`ISCC`:
the mechanism was verified (the frozen directory and `rglob("*")` in the packaging), and the actual contents of the ZIP are an inference.

### R3b-08. Predictable CDP ports in the GUI workers

`gui/workers.py:133` — `cdp_port = 9350 + idx`, whereas the other paths take an ephemeral
port (`browser_launcher.get_free_port()`). Combined with the lack of authentication on CDP,
a local process can guess the port and connect to a profile's live session.

**Fixed:** `get_free_port()`; the test checks that the literal `9350` is gone and that
the function returns distinct bindable ports.

### R3b-09. Injection of actions from a page into other profiles' browsers

`Runtime.addBinding` is installed for every attached session (`cdp_injector.py:317`),
and the handler checked only the name and `type` (`:347-360`), after which the event went to
`submit_event` (`synchronizer.py:221-228`) and was replayed as a `mouse.click`,
`keyboard.press`, or a text entry of up to 8 characters in the **worker profiles** (`:454`, `:466`, `:470-477`).
While a sync session was running, any script on the master page (including an advertising iframe)
could click inside other logged-in profiles.

**Fixed:** `binding_event_allowed()` (pure and testable) accepts a gesture only if
it comes from the main-world context (`auxData.isDefault`) of the **main** frame (`Page.getFrameTree` +
`Page.frameNavigated`) of the top-level page (`targetInfo.type == "page"`, OOPIF excluded);
the payload is limited to 4 KiB; a token bucket is enabled (60 events/s, burst 120); payload parsing
was moved into a task so that a flood from the page does not delay `Fetch.continueRequest` in the CDP read
loop; the `binding_events_accepted/rejected/throttled` counters are available in the injector's status.

### R3b-10/11. Security headers and CSP

Neither `Content-Security-Policy`, nor `X-Content-Type-Options`, nor `Referrer-Policy`, nor
`X-Frame-Options` was ever set (`grep` across the repository — 0 matches); `/`
was served as a bare `FileResponse`. A strict CSP was impossible at the time: `index.html` had 40, and the
generated `app.js` markup had another 18 inline `on*` handlers.

**Fixed:** middleware sets `X-Content-Type-Options: nosniff`,
`Referrer-Policy: no-referrer`, `X-Frame-Options: DENY`, `Cross-Origin-Opener-Policy`,
`Cross-Origin-Resource-Policy`, `Permissions-Policy`, and a CSP with `object-src 'none'`,
`base-uri 'none'`, `form-action 'self'`, `frame-ancestors 'none'`; for `/api` and `/v1.0`
a `Cache-Control: no-store` header was added (the cookie export must not linger in the disk cache).
**The honest boundary at that time:** it was verified in a real browser that a CSP with
`script-src 'self' 'unsafe-inline'` does NOT stop the XSS itself (the dashboard version without
escaping kept executing the payload — `country=1, city=1, ip=1`, 323 bytes from
`/api/security/secrets-mode`): escaping was what held the line.

**Closed in round-3c (see §12):** the handlers were moved to `data-action` + delegation,
`script-src` became a strict `'self'`, and the injected inline handler no longer executes
even with broken escaping.

### R3b-12. GUI dialogs: confirmation and honest results

`gui/dialogs/cookie_dialog.py:106-107` — a single click deleted Cache/Code Cache/GPUCache/
DawnCache/Service Worker/CacheStorage without confirmation and ignored a `False` from
`clear_profile_cache`; `:97-98` printed "Successfully saved N entries" regardless of the
result of `save_profile_cookies`; `batch_cookie_dialog.py:244-245` did not show the
`failed` counter.

**Fixed:** `QMessageBox.question` + checks of both boolean results (an error instead of
success), and the `failed` counter in the summary with `InfoBar.warning`. The GUI does not start without PyQt6,
so this was verified by reading and a static test; the dialogs' behavior in a live GUI was not tested.

### R3b-13. Page-visible product markers

The generated `stealth.js` contained `window.__nazakShieldApplied`, the sync client contained
`window.__nazakSyncInstalled`, and the binding was named `__nazak_sync_event`: any
anti-fraud system could identify Nazak with a single line, `if (window.__nazak…)`.

**Fixed:** the idempotency flags were renamed (`window.__nsi`, `window.__nse_c`) and
made non-enumerable (`enumerable: false`), the binding name is now `__nse_ev`, and the brand was removed from
the comments inside the injected JS (comments are visible through `Function.prototype.toString()`
for non-closured functions). In addition, the injector applies the script to the current document
once per `(sessionId, loaderId)`, so the page-visible "fuse" flag has become
a fallback rather than the primary mechanism. Tests: `"__nazak" not in SYNC_CLIENT_JS`,
`"__nazakShieldApplied" not in stealth.js`.

**Residual risk (not eliminated):** the page can still find these properties by explicitly
enumerating them (`Object.getOwnPropertyNames(window)`, `getOwnPropertySymbols`). A fully
invisible variant would require removing the flags and relying only on injection bookkeeping on the CDP
side — that is broader than this round's fix, and the risk of double-applying the script outweighs the benefit.

### R3b-14. Minor fixes

- `app.js:346` — `${e.message}` now goes through `escapeHtml`; `app.js:854` — `rel="noopener noreferrer"`.
- Google Fonts from the CDN (`index.html:8-10`) were removed: the dashboard no longer contacts external
  hosts and works offline; `styles.css` uses explicit system stacks
  (`Segoe UI Variable Text` / `Cascadia Mono`), and there are no other `url()`/`@import` rules in the CSS.
- `synchronizer._navigate_worker_sync` no longer passes the URL to `page.goto()` as is:
  `file://`, `data:`, and `javascript:` are rejected (verified by execution), plus a `field_validator`
  on `SynchronizerNavigateRequest.url` returns 422 at the boundary.
- `nazak/tools/generate_brand_assets.py` — the path `D:/nazak/data/assets` was replaced with a
  repo-relative one, and the banner version comes from the package (it used to be hard-coded as "V1.3.0").
- `mass_generate_dialog.py` — the docstring was brought in line with the slider's actual range (1..100).
- `synchronizer.py:150-153` — `cols` is bounded to 1..8 (a negative value produced a
  ZeroDivisionError/negative geometry, which was swallowed by a generic `except`).
- `synchronizer._ensure_worker_pages` checks the page cache **before** importing playwright
  (a side effect: the test `test_mirror_one_replicates_event_to_all_workers`, which failed because
  playwright was missing, now passes).
- The `RequestValidationError` response classes do not echo the original input: the 422 body is serializable even
  for `Infinity`, and a 5-megabyte string is not returned to the client in full.

### What Was Checked and NOT Confirmed in the Second Pass

- There are no secret leaks into the logs: every `logger.*` call that mentions passwords/tokens logs field
  names, not values (`secrets_store.py:366/475/489`, `account_provisioner.py:549`).
- `NazakBrowserStudio.spec:13-16` bundles only `nazak/web` and `data/assets` — the root
  `data/` does not end up in the image; `app.manifest:15` — `requestedExecutionLevel="asInvoker"`,
  `installer.iss:43` — `PrivilegesRequired=lowest` (no administrator prompt at all).
- The generated JS has no unsafe string interpolation: all string/structured
  values go through `json.dumps`, and 14 numeric/boolean fields remain "raw"
  (the only floats are the ones covered by `_js_number`).
- `parse_cookie_files_from_dir/zip` do not extract the archive to disk (zip-slip is impossible), and
  `import_profile_bundle` filters out absolute paths, drives, and `..`.

### What Remained Unverified (Stated Plainly)

- Execution of R3b-09 in a live browser: I read the chain and covered it with tests on pure
  functions, but I did not bring up a real "master + worker" pair with a malicious page.
- The behavior of the GUI dialogs after the fixes (no PyQt6/qfluentwidgets in this environment) and the rendering of
  the banner in `generate_brand_assets.py` (PyQt6 + Pillow are required).
- The `Setup.exe` installer (Inno Setup format) was not unpacked: the contents were verified against the
  release ZIP, and the installer is built from the same directory and has a second layer — `Excludes:`.

---

## 12. Round-3c: Strict CSP and the Origin/WebSocket Bug Found by a Live Browser

### R3c-01 (Medium, fixed and verified) — the CSP did not protect against XSS because of inline handlers

`script-src` was forced to contain `'unsafe-inline'`, because the entire markup was built
on 58 `on*` attributes (40 in `index.html`, 18 in the `app.js` templates). A check in a real
browser (differential control in `tests/live/test_dashboard_xss_live.py`) showed that
such a CSP does **not** stop the XSS: the dashboard version without escaping executed the payload
(`country=1, city=1, ip=1`, 323 bytes from `/api/security/secrets-mode`).

**Fixed:**
- The 58 inline handlers were moved to `data-action="name"` + parameters in `data-*`; a single
  delegated listener (`click`/`change`/`input`) calls a function from `DELEGATED_ACTIONS`
  (42 actions). Parameters are read **only** from `data-*` attributes, and an unknown action
  is logged rather than executed.
- `CSP_POLICY` in `server.py`: `script-src 'self'` — without `'unsafe-inline'` or `'unsafe-eval'`.
  `style-src` keeps `'unsafe-inline'` (≈62 inline `style=` attributes; a CSS injection does not lead to code
  execution) — the remainder is documented in the code and in the API reference.
- Tests: `tests/test_csp_strict_and_delegation.py` (11 static checks: not a single `on*=`,
  parity between `data-action` and the registry, absence of inline `<script>`/`eval`/`javascript:`,
  and a strict `script-src`) and the live `tests/live/test_dashboard_ui_smoke_live.py` — 11 click
  scenarios across the dashboard requiring zero page/console errors, plus differential control:
  the injected inline handler executes on an ordinary page and does **not** execute on the
  dashboard. `node --check app.js` — the syntax is valid.

### R3c-02 (Medium, fixed and verified) — the Origin check broke the dashboard on a non-standard port

`_is_local_origin()` compared the Origin against the port list `_ALLOWED_PORTS = {8899, 3000}`,
which was only extended by a call to `configure_local_access(args.port)` from `main.py`.
Consequences:
- Starting the application by any route other than `main.py` (a bare `uvicorn nazak.api.server:app`,
  gunicorn, embedding, tests) → the port was not registered → **every** request with an
  `Origin` header got a 403. A WebSocket handshake always sends Origin, so live updates
  (health, profile statuses, upload progress) did not work at all.
- Unit tests on `TestClient` did not see this: it does not send `Origin`. A live browser test
  found it: `WebSocket connection to 'ws://127.0.0.1:46399/ws/events' failed: ... 403`.

**Fixed:** `_origin_matches_request(origin, host)` — a loopback Origin is accepted if it is
either in the CORS whitelist (`:3000` — a deliberate case for the local frontend, plus the port registered by
`configure_local_access`) or **matches the `Host` of the request itself** (same-origin on any port).
Still rejected: a foreign Origin, `null`, a suffix forgery (`127.0.0.1.evil.com`), and a
local page from an unregistered and non-matching port. Verified by
`tests/test_api_origin_and_ws.py` (19 tests, including a real WebSocket handshake on a
random port: same-origin → `pong`, a foreign Origin and a different port → rejection) and by a live browser
(zero console errors in the UI smoke test).

### What Was Verified in round-3c

- All live tests in the image (`3 passed, 2 skipped`): the XSS control, the UI smoke test under a strict CSP, and the
  differential CSP control.
- Full run: `747 passed`, 7 failures — the same environment-dependent ones (no `qfluentwidgets`/`playwright`
  in this environment), with no new regressions.
- `ruff check`/`format`, `mypy` (Linux and Windows), `node --check` — clean.
- **Release artifact v1.11.0** (checked in this same round): `NazakBrowserStudio-v1.11.0-Windows-x64.zip`
  was downloaded (152.34 MB, 4357 entries), its SHA256 matched the
  published `SHA256SUMS.txt`, entries with runtime data (`profiles.json`, `profiles/`,
  `logs/`, `extensions/`, `videos/`, `screenshots/`) — **0**, and only `assets/` under `data/`;
  the dashboard fixes inside the artifact are in place (0 references to Google Fonts, system fonts,
  `escapeHtml(e.message)`, `rel="noopener noreferrer"`).
- A strict CSP without `'unsafe-inline'` — not implemented, see R3b-10/11.

### Verification of the Second Pass

- Full run: **725 collected, 3 live deselected**; `715 passed, 7 failed` without live
  (the 7 are environmental: no `qfluentwidgets`/`playwright`), versus **9** failures at commit
  `5a25115` in the same environment (one failure was closed by the `_ensure_worker_pages` improvement).
- New test files: `tests/test_round3b_api_bounds.py` (12),
  `tests/test_round3b_stealth_and_sync.py` (16),
  `tests/test_round3b_storage_and_packaging.py` (9),
  `tests/test_round3b_cli_background.py` (4),
  `tests/test_web_assets_hardening.py` (7), `tests/test_gui_and_tools_hardening.py` (8).
- `ruff check`/`ruff format --check` — clean; `mypy nazak` — `Success` (57 files) **on both
  platforms** (`--platform linux`, as on the CI runner, and Windows). The first CI run with fully
  enabled error codes found 7 errors that are invisible on Windows: `ctypes.windll`/
  `GetLastError` do not exist in typeshed for Linux (6 × `attr-defined` in `secrets_store.py`) and
  `sanitize_launch_url()` returns `str | None` (1 × `return-value` in the synchronizer's URL
  validator). Fixed in `d6f6b51`.
- In the image (`nazak-browser-studio-nazak-studio:latest`, Chromium inside): the live headers are
  confirmed (`CSP`, `nosniff`, `DENY`, `no-referrer`, `no-store`), all bounds return 422,
  `Infinity` in the body — 422 (it used to be 500), `file://` in navigate — 422; the live XSS test in Chromium
  passes (21 passed together with the web/gui tests), and on the dashboard version without escaping it
  fails, as it should.
