# Deep Audit — Round 2 (2026-09-27)

> ⚠️ **Исторический документ.** Все находки ниже исправлены в v1.9.1, а ссылки на строки
> кода с тех пор устарели (например, `server.py:205-217` теперь соответствует ~214-228, а
> упомянутые `POST /api/profiles/{profile_id}/export` и `POST /api/profiles/import` в коде
> отсутствуют). Актуальный разбор — `docs/AUDIT_ROUND3_FINDINGS.md`, изменения — `CHANGELOG.md`.
> Документ оставлен как история: переписывать номера строк в нём смысла нет.

Second-pass audit after the v1.9.0 remediation. Every finding below was **reproduced at
runtime** on this machine (Python 3.12.3, Windows), not just read from source. Probes were
temporary and deleted afterwards; each item lists the reproduction so results can be re-derived.

Scope: the trust boundary between the local HTTP API, the secrets store, the profile store on
disk, the Chrome command line and the fingerprint generator — i.e. where the v1.9.0 fixes
stopped one layer short of the data.

Severity: **P0** = credential/2FA material exposed or destroyed, or a usable remote primitive.
**P1** = silent data loss / isolation break / broken core promise. **P2** = detection or
correctness defect with real consequences.

---

## D2-P0-1 — `GET /api/profiles` hands out plaintext 2FA seeds even in DPAPI mode

`decrypt_notes(reveal=False)` is documented as "returns masked values for API/GUI listing",
but it injects the *unmasked* TOTP seed into a helper key **regardless of `reveal`**:

- `nazak/core/secrets_store.py:349-351` — `result["_totp_raw"] = plain` (outside the `reveal` branch)
- `nazak/api/server.py:251-265` — `_mask_profile_secrets()` calls `decrypt_notes(notes)` and
  serializes the whole dict, `_totp_raw` included, back into `google.notes`
- Reachable from `GET /api/profiles` (`server.py:423-440`), `GET /api/profiles/{id}`
  (`server.py:443-454`) and the mass-generator response (`server.py:844-849`)

Reproduction (DPAPI mode, i.e. secrets encrypted at rest):

```
stored notes : {"account_password": "nzk1:dpapi:...", "totp_secret": "nzk1:dpapi:..."}
GET /api/profiles -> notes:
  {"account_email": "owner@corp.com",
   "account_password": "Sup...ord!",
   "totp_secret": "JBS...APTK",
   "_secrets_mode": "dpapi",
   "_totp_raw": "JBSWY3DPEHPK3PXPAPTK"}        <-- plaintext seed
```

Impact: the DPAPI / passphrase storage-mode feature is bypassed by one unauthenticated
`GET /api/profiles` on `127.0.0.1:8899` — no passphrase, no Windows-user context needed, the
app decrypts the seed for the caller. A TOTP seed is worse than a masked password: it is not
rotated, so it yields a permanent second factor.

Fix direction: build the display dict explicitly; `_totp_raw` may only exist on the
`reveal=True` path, and the GUI ticker should pull it from a dedicated endpoint. Keep it out of
the response schema instead of filtering a dict.

---

## D2-P0-2 — One GUI edit-save permanently destroys encrypted secrets (verified end to end)

`PUT /api/profiles/{profile_id}` writes the client object verbatim:

- `nazak/api/server.py:468-478` — `profile_data.id = profile_id; profile_manager.update_profile(profile_data)`
- `nazak/core/profile_manager.py:451-459` — `self.profiles[profile.id] = profile` (replace, not merge)
- Nothing on the write path calls `encrypt_notes()` (its only call sites are
  `core/account_provisioner.py:327` and `core/profile_manager.py:499`), so whatever the client
  sent becomes the stored value.

The GET response is masked (D2-P0-1), and the web UI edit modal round-trips that exact string
(`nazak/web/app.js:428` prefills `edit-notes` from `prof.google.notes`;
`nazak/web/app.js:515, 520-524` PUTs it back).

Reproduction — `GET /api/profiles` → feed the response straight back into
`PUT /api/profiles/{id}` (what "open profile, click Save" does):

```
BEFORE: {"account_password": "nzk1:dpapi:AQAAANCMnd8BFdERjHoAwE/...",
         "totp_secret":      "nzk1:dpapi:AQAAANCMnd8BFdERjHoAwE/..."}

AFTER : {"account_password": "Sup...ord!",
         "totp_secret": "JBS...APTK",
         "_secrets_mode": "dpapi",
         "_totp_raw": "JBSWY3DPEHPK3PXPAPTK"}
```

`profiles.json` now holds display masks where ciphertext used to be, still advertises
`_secrets_mode: "dpapi"` (so the app believes the values are protected), and adds a plaintext
`_totp_raw` to disk. `decrypt_secret()` passes non-envelope strings through unchanged
(`secrets_store.py:291-297`), so the login flow types the literal `Sup...ord!` into the
password field. **Unrecoverable** — the ciphertext is gone.

Same class, nastier trigger: when the passphrase is not loaded, `decrypt_notes` substitutes
`"<encrypted: unavailable passphrase>"` (`secrets_store.py:346-348`); a later save writes that
sentinel over the real secret.

Fix direction: (a) never persist a value that equals the mask pattern or the sentinel in a
protected field — treat it as "unchanged"; (b) re-encrypt on write inside
`create_profile`/`update_profile`; (c) merge in `update_profile` instead of replacing;
(d) reject client-supplied `_totp_raw` / `_secrets_mode` keys.

---

## D2-P0-3 — Proxy credentials are never encrypted, and `/api/profiles` returns them in clear

The v1.9.0 changelog claims "Proxy passwords are masked in API responses", and
`_mask_proxy_for_api()` does that for the Dolphin endpoints (`server.py:238-248`). Two gaps
remain:

1. **`GET /api/profiles` and `GET /api/profiles/{id}` are not masked at all.**
   `_mask_profile_secrets()` only touches `google.notes`; the returned
   `response_model=BrowserProfile` keeps `proxy` verbatim. Verified:

   ```
   GET /api/profiles -> proxy: {"type": "socks5", "host": "1.2.3.4", "port": 1080,
     "username": "john", "password": "Hunter2!",
     "rotation_url": "http://provider/rotate?key=SECRET",
     "raw": "socks5://john:Hunter2!@1.2.3.4:1080", "active": true}
   GET /v1.0/browser_profiles -> proxy.password: "***"      # masked only here
   ```

   `proxy.raw` and `proxy.rotation_url` (both routinely embed credentials) leak from *both*
   endpoints — the masked Dolphin payload still carries `raw` with `user:pass@host`.

2. **The three storage modes never cover proxies.** `SECRET_FIELDS = ("account_password",
   "totp_secret")` (`secrets_store.py:53`), and only `google.notes` goes through
   `encrypt_notes`/`decrypt_notes`. Verified: right after switching to `dpapi` mode, the proxy
   block in `profiles.json` is still plaintext password + `raw` with credentials.
   `reencrypt_all_profile_secrets()` (`profile_manager.py:461-503`) cannot fix what it never
   reads, so `data/profiles.json` is a plaintext proxy-credential store in every mode.

Fix direction: add `proxy.password`, `proxy.raw`, `proxy.rotation_url` to the protected set (or
stop persisting `raw` and rebuild it at use time), and route every profile response through one
masking helper instead of one-per-endpoint.

---

## D2-P1-1 — The whole API is unauthenticated; CORS accepts any localhost port

- No auth anywhere: `grep -E "APIKeyHeader|HTTPBearer|api_key|Depends\("` in
  `nazak/api/server.py` → zero hits. Delete-profile, export-cookies, export `.nazak` bundle,
  launch-with-CDP, autopost and the secrets-mode switch are all callable by anything that can
  reach `127.0.0.1:8899`.
- `allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$"` + `allow_credentials=True`
  (`server.py:205-217`): any dev server, any Electron app, any page served on a local port can
  call the API cross-origin.
- `POST /api/profiles/{id}/start` returns the CDP `wsEndpoint` (`server.py:609-614`). DevTools
  binds to 127.0.0.1, but **WebSockets are not subject to CORS**, so a browser tab can open
  `ws://127.0.0.1:<port>/devtools/page/...` itself: read cookies, replay logged-in sessions,
  run JS inside the profile. Two HTTP requests = full account takeover.
- `/ws/events` (`server.py:1259-1270`) accepts any connection, no origin check, and streams
  profile ids + status transitions.

`docs/API_REFERENCE.md` documents `127.0.0.1:8899` as the integration surface for external
scripts, which makes the missing token a documented-by-accident hole.

Fix direction: startup-issued shared token (GUI and `start_app.bat` already know the port),
exact-port `allow_origins`, `Origin` check on the WS handshake, and refuse `Host`/`Origin`
values that are not localhost for `/v1.0/*`.


---

## D2-P1-2 — `rotation_url` is a local-file-read + SSRF primitive

`POST /api/profiles/{profile_id}/rotate-proxy` (`server.py:868-882`) takes the URL **from the
stored profile** (`prof.proxy.rotation_url` — writable by anyone through `POST/PUT /api/profiles`,
see D2-P1-4) and fetches it with a bare `urllib` call:

```python
req = urllib.request.Request(prof.proxy.rotation_url, headers={"User-Agent": "Nazak-Studio"})
with urllib.request.urlopen(req, timeout=10.0) as resp:
    resp_body = resp.read().decode("utf-8", errors="ignore")
    return {"success": True, "status_code": resp.status, "response": resp_body[:200]}
```

No scheme allowlist, no post-resolution IP checks, and `urlopen` follows redirects. Verified
(local HTTP server on 127.0.0.1 serving a fake metadata body; a file with a fake AWS key next to
the profile store):

```
file:///.../aws_creds.txt      -> {"success": true, "status_code": null,
                                   "response": "AKIAIOSFODNN7EXAMPLE / super-secret-token"}
http://127.0.0.1:PORT/...      -> {"success": true, "status_code": 200,
                                   "response": "INTERNAL-METADATA: iam-role-credentials-DO-NOT-SHARE"}
http://169.254.169.254/...     -> 500 "urlopen error timed out"   # not blocked by policy, just unreachable here
```

So this is an arbitrary-read primitive, not a blind one: `file://` returns the first 200 bytes of
any file the process can open (repeatable against other paths), and any internal HTTP service can
be reached and its body echoed back. On failure the 500 detail embeds the raw exception message
(`{e!s}`), which leaks resolution/connect results for internal host scanning. On a cloud workstation
the third case is the interesting one — nothing in the code prevents it.

Fix direction: validate at **write** time and at fetch time — scheme ∈ {http, https}; resolve the
host and reject loopback/private/link-local/unique-local ranges (resolve-and-check, not string
compare); disable redirects (`HTTPRedirectHandler` that refuses) so a public host cannot redirect
into `file://` or `169.254.169.254`; return a generic error instead of `{e!s}`.


---

## D2-P1-3 — Chrome argument injection via `custom_url`

`LaunchRequest.custom_url` (`server.py:315-317`) flows through
`launch_profile_with_cdp(custom_url=...)` (`browser_launcher.py:262`) into
`build_chrome_args(..., custom_url)`, where it is appended to argv as a bare string
(`browser_launcher.py:233-241`). Verified:

```
build_chrome_args(..., custom_url="--disable-web-security")
  argv tail: [..., '--disable-extensions-except=...', '--disable-web-security']
build_chrome_args(..., custom_url="file:///C:/Windows/win.ini")
  argv tail: [..., 'file:///C:/Windows/win.ini']
```

Both are accepted unmodified. With a leading `--` a caller disables web security, swaps
`--user-data-dir` (profile-crossing: profile A launched with profile B's directory), or points
`--load-extension` at an attacker directory. `file://` additionally bypasses the proxy — the
profile's real IP leaks while the GUI still shows "socks5 active".

Fix direction: validate the value (`http`/`https` only, reject anything starting with `-`), and
append the URL only after all flags with no further switch-looking tokens accepted.

---

## D2-P1-4 — `PUT /api/profiles/{id}` silently destroys fields the GUI does not display

`profile_manager.update_profile()` replaces the whole object
(`profile_manager.py:451-459`), so any field absent from the PUT body falls back to the Pydantic
default, and `update_proxy`-style merging never happens.

The web modal's body (`nazak/web/app.js:491-515`) contains only ~10 fields. Fields it does not
send are reset on every save. Verified after one edit-save of a profile that had a working
SOCKS5 proxy + rotation URL + Europe/London timezone:

```
proxy.type: socks5 -> direct (password/username/host/rotation_url all None)
timezone : Europe/London -> America/New_York (default, no longer proxy-IP aligned)
webgl_renderer: profile's GPU -> 'ANGLE (NVIDIA, NVIDIA GeForce RTX 3080 ...) [default]'
canvas_seed: profile's seed -> 242290 (new random default)
```

Consequences, in order of severity: proxy credentials vanish (profile now runs direct → IP
leak while the UI claims a proxy); fingerprint identity changes while the Chrome profile dir
(and its cache/localStorage history of canvas hashes) stays the same → the same browser
directory now reports two different GPUs and two different noise seeds across sessions;
timezone stops matching the proxy geolocation.

Fix direction: PATCH semantics (merge into existing profile), and never let a PUT reset a field
that the request did not mention — for Pydantic v2 use `model_fields_set` to distinguish
"absent" from "explicitly null".


---

## D2-P1-5 — Bulk credential export is unauthenticated and leaves plaintext on disk

- `POST /api/cookies/bulk-export` with `{"profile_ids": []}` exports **every** profile's cookies:
  `export_all_cookies()` does `target_ids = profile_ids or list(self.profiles.keys())`
  (`profile_manager.py:766-778`), and the endpoint passes the empty list straight through
  (`server.py:900-915`). One unauthenticated POST → session cookies of the whole fleet;
  `docs/API_REFERENCE.md:279-287` documents the endpoint as "Exports **all** session cookies"
  and its example passes a `profile_ids` array, so nobody reading it learns that omitting the
  array (or sending `[]`) silently widens the scope to every profile.
- `POST /api/profiles/{profile_id}/export` writes `data/profiles/<name>.nazak.zip` containing
  `profile.json` (all notes + proxy) and `cookies.json`, and **never removes it**
  (`server.py:815-856`): every export permanently copies the credential store to a second,
  guessable location. `bundle_contents()` reads `google.notes` straight from disk, so in `plain`
  mode the bundle holds plaintext passwords; in `dpapi` mode the envelopes are machine-bound
  (useless to a thief, unrecoverable for the user who moves machines — the format has no
  migration story).
- `POST /api/profiles/import` on top of that makes one exported bundle = arbitrary profile
  injection (name, group, cookies) into the operator's studio.

Fix direction: require a confirm token for bulk export, stream the archive instead of persisting
it, delete temp files in a `finally` block.

---

## D2-P2-1 — Fingerprint coherence defects that are directly detectable

1. **`device_memory: int = 16`** (`nazak/models/profile.py:90`) is injected verbatim as
   `navigator.deviceMemory` (`extension_generator.py:186`). The Device Memory spec quantizes to
   `{0.25, 0.5, 1, 2, 4, 8}` and Chrome clamps at `8`; real Chrome can never report `16`. Every
   default profile fails a one-line bot check.
2. **`audio_noise_seed: float = Field(default_factory=lambda: 0.000001)`** (`profile.py:134`) is
   a constant, not a generator — every profile gets the same audio-noise factor, so audio-context
   hashes collapse across the fleet. The template's `{fp.audio_noise_seed} || 0.00001`
   (`extension_generator.py:526`) does not save it.
3. **WebGPU architecture guessed by substring** (`extension_generator.py:120-125`): `"40" in
   renderer` → `ada lovelace`. A renderer containing `40` for any other reason (e.g. `GTX 940M`,
   `MX130 (412)`) is advertised as RTX 40-class with `timestamp-query` enabled, so
   `adapter.requestAdapter()` info contradicts `WEBGL_debug_renderer_info`.
4. **`max_texture_size: int = 16384` for every GPU** (`profile.py:105`, used at
   `extension_generator.py:285`) — a fixed constant across an entire fleet is a cheap correlation
   vector.
5. **`clone_profile()` re-randomizes only `canvas_seed`, `audio_noise_seed` and media device ids**
   (`profile_manager.py:556-581`); `user_agent`, `app_version`, `platform`, `webgl_renderer`,
   `screen_*`, `hardware_concurrency`, `device_memory` are copied byte-for-byte. The docstring's
   "a different fingerprint (device identity) is generated" holds only for the noise layer — a
   cloned fleet shares one device identity.
6. `ua_full_version` is derived by string splitting (`extension_generator.py:101`); an
   `app_version` without `Chrome/` silently becomes `"133.0.0.0"` while `brand_version` keeps the
   profile's real major, so `userAgentData.fullVersions` disagrees with
   `getHighEntropyValues()`.

Fix direction: quantize/validate `device_memory` to the spec set; make `audio_noise_seed`
actually random; derive WebGPU arch from an explicit `gpu_family` field; key `max_texture_size`
off the GPU preset; extend `clone_profile()` to device-identifying fields.


---

## D2-P2-2 — `passphrase` mode silently degrades to plaintext

`encrypt_secret()` returns the **plaintext with an `nzk1:plain:` marker** when no passphrase is
available (`secrets_store.py:284-286`), and `POST /api/security/secrets-mode`
(`server.py:1176-1189`) lets a caller switch to `passphrase` without supplying one.
`reencrypt_all_profile_secrets()` then "succeeds", the GUI shows the strong mode, and
`profiles.json` keeps `nzk1:plain:` blobs. Combined with D2-P0-2, a profile can end up labelled
`"_secrets_mode": "dpapi"` while holding masks and plaintext — with no error surfaced anywhere.

Fix direction: raise `SecretsError` when the target mode requires a passphrase that is absent;
never emit a plaintext envelope except for an explicit user-chosen `plain` mode.

---

## D2-P3 — Hygiene items (verified, low risk)

- `FastAPI(version="1.8.0")` (`server.py:192`) while `nazak.__version__ = "1.9.0"` — the
  CHANGELOG's "version metadata unified" claim misses `/openapi.json`, so `/docs` advertises the
  previous release.
- `requirements.txt` allows `pytest>=7.4.0` while `pyproject.toml` requires `pytest>=8.0.0`. On
  this machine the resolved tree aborts before collecting anything:
  `AttributeError: __spec__` raised from `py/_apipkg.py` (imported by `_pytest/compat.py`'s
  `LEGACY_PATH = py.path.local`) on Python 3.12. The "596 tests pass" gate is therefore not
  reproducible from the documented install path — pin `pytest>=8` in `requirements.txt` and drop
  the `py` dependency.
- `_validate_id` (`profile_manager.py:271-277`) is correctly applied on every cookie path:
  path traversal there is **not** exploitable today; keep it that way for new file endpoints.

---

## What did *not* reproduce

- No XSS sink found in `nazak/web/app.js` for the fields audited here: `renderGrid` writes
  name/group through `esc()`; `subprocess.Popen` receives an argument list, never a shell string.
- `GET /v1.0/browser_profiles` genuinely masks `proxy.password` (only `raw` is missed).
- The DPAPI envelope itself is sound: ciphertext written for `account_password` / `totp_secret`
  decrypts back to the original value in-process. The failures are in what the API returns and in
  what gets written back — not in the crypto.
- `POST /api/profiles/bulk_import` path-traversal and the Dolphin endpoints' ID handling held up.

---

## Recommended remediation order

| # | Item | Why this position |
| --- | --- | --- |
| 1 | D2-P0-2 masked notes written back | Destroys user data during normal GUI use |
| 2 | D2-P0-1 `_totp_raw` in listings | Defeats the entire secrets-mode feature |
| 3 | D2-P0-3 proxy masking + coverage | Plaintext credentials on disk and on the wire |
| 4 | D2-P1-2 / D2-P1-3 SSRF-file-read, Chrome arg injection | Two request-to-local-read / browser-flag primitives |
| 5 | D2-P1-4 PUT → merge semantics | Silent identity/proxy loss on every edit |
| 6 | D2-P1-1 auth token + exact-origin CORS | Promotes items 2-5 from "local process" to "any web page" |
| 7 | D2-P1-5 bulk export hardening | Blast radius |
| 8 | D2-P2-x fingerprint coherence, passphrase fallback | Detection + honesty of the core product claim |

Regression tests worth landing with the fixes (all cheap, no browser required):

1. `GET /api/profiles` → `PUT /api/profiles/{id}` with that exact body → assert the stored value
   of every `SECRET_FIELDS` entry still starts with `nzk1:` and `_totp_raw` is absent from disk.
2. In `dpapi` mode, assert the known plaintext of each protected field appears nowhere in the
   listing response body (substring scan of the raw JSON).
3. `rotation_url="file:///..."` and `rotation_url="http://169.254.169.254/"` → expect 400.
4. `custom_url="--disable-web-security"` and `custom_url="file:///C:/Windows/win.ini"` → 400.
5. Partial `PUT` body → assert `proxy.password`, `proxy.rotation_url`, `timezone`,
   `webgl_renderer`, `canvas_seed` unchanged.
6. `POST /api/cookies/bulk-export` with `[]` → must not return cookies of unlisted profiles.
7. `deviceMemory` value emitted by `build_content_js()` ∈ `{0.25,0.5,1,2,4,8}`; two freshly
   constructed `BrowserProfile()` objects must not share `audio_noise_seed`.

