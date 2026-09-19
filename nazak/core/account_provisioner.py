"""
Account Provisioner & Dual-Mode Activation Engine.
Automates batch importing accounts (Login:Pass:2FA:Recovery), generating isolated browser profiles,
performing automated Google login via CDP with TOTP generation, and managing OAuth 2.0 / YouTube Studio sessions.
"""

import base64
import hashlib
import hmac
import html
import json
import logging
import re
import secrets
import struct
import time
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

try:
    import pyotp
except ImportError:
    pyotp = None

from ..models.profile import BrowserProfile, GoogleSettings, ProfileStatus
from ..models.proxy import ProxyConfig, ProxyType
from .fingerprint_generator import generate_random_fingerprint
from .profile_manager import ProfileManager
from .secrets_store import (
    encrypt_notes,
    reveal_notes,
)

logger = logging.getLogger(__name__)


def generate_totp_rfc6238(secret: str, interval: int = 30, digits: int = 6) -> str:
    """
    Pure Python RFC 6238 TOTP generator fallback if pyotp is unavailable or key is malformed.
    """
    if pyotp is not None:
        try:
            cleaned = secret.replace(" ", "").strip().upper()
            return pyotp.TOTP(cleaned, interval=interval, digits=digits).now()
        except Exception:
            pass

    try:
        cleaned = secret.replace(" ", "").strip().upper()
        padding = (8 - len(cleaned) % 8) % 8
        cleaned += "=" * padding
        key = base64.b32decode(cleaned, casefold=True)
        counter = int(time.time() // interval)
        counter_bytes = struct.pack(">Q", counter)
        h = hmac.new(key, counter_bytes, hashlib.sha1).digest()
        offset = h[-1] & 0x0F
        code_int = struct.unpack(">I", h[offset : offset + 4])[0] & 0x7FFFFFFF
        code = str(code_int % (10**digits)).zfill(digits)
        return code
    except Exception as e:
        logger.error(f"Error computing TOTP: {e}")
        return "000000"


def parse_account_string(raw_line: str) -> dict[str, str] | None:
    """
    Parses market account string format:
    login@gmail.com:password:2fa_secret:recovery@mail.com
    Handles multi-delimiter lines, marketing banners, order headers, and extra metadata.
    """
    line = raw_line.strip()
    if not line or line.startswith("#") or line.startswith("=") or line.startswith("-") or line.startswith("↓"):
        return None

    # Line must contain an email address
    if "@" not in line:
        return None

    delimiters = [":", ";", "|", "\t"]
    parts = []
    chosen_delimiter = None
    for d in delimiters:
        if d in line:
            candidate_parts = [p.strip() for p in line.split(d)]
            if len(candidate_parts) >= 2 and "@" in candidate_parts[0]:
                parts = candidate_parts
                chosen_delimiter = d
                break

    if not parts or len(parts) < 2:
        return None

    email = parts[0]
    password = parts[1]
    totp_secret = parts[2] if len(parts) > 2 else ""

    # Reconstruct recovery email / notes if it contained delimiters (e.g. URLs)
    if len(parts) > 3:
        recovery_email = chosen_delimiter.join(parts[3:]) if chosen_delimiter else parts[3]
    else:
        recovery_email = ""

    if "secret=" in totp_secret:
        m = re.search(r"secret=([A-Za-z0-9]+)", totp_secret)
        if m:
            totp_secret = m.group(1)

    # Sanitize TOTP secret
    totp_secret = totp_secret.replace(" ", "").strip()

    return {
        "email": email,
        "password": password,
        "totp_secret": totp_secret,
        "recovery_email": recovery_email,
        "raw": line,
    }


def generate_oauth_state() -> str:
    """Cryptographically strong OAuth ``state`` token (CSRF protection)."""
    return secrets.token_urlsafe(32)


class OAuthCallbackHandler(BaseHTTPRequestHandler):
    """Local HTTP callback receiver for Google OAuth 2.0 redirect flow.

    Mutable flow state (``auth_code`` / ``error``) lives on the *instance*
    instead of class attributes, and the accepted ``?code=`` is verified
    against the per-session ``expected_state`` token — parallel authorization
    flows cannot hand their codes to each other, and remote CSRF
    code-substitution is rejected.
    """

    # Set per-session by the OAuthCallbackReceiver handler factory.
    expected_state: str | None = None
    _observer: "OAuthCallbackReceiver | None" = None

    def __init__(self, request, client_address, server):
        self.auth_code: str | None = None
        self.error: str | None = None
        super().__init__(request, client_address, server)

    def _notify_observer(self):
        """Propagate flow results to the owning receiver (per-session binding)."""
        observer = type(self)._observer
        if observer is not None:
            observer.auth_code = self.auth_code
            observer.error = self.error

    def do_GET(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)

        if "code" in params:
            received_state = params.get("state", [None])[0]
            if self.expected_state and received_state != self.expected_state:
                logger.warning("OAuth callback rejected: state parameter mismatch (possible CSRF attempt).")
                self.error = "state_mismatch"
                self._notify_observer()
                self._respond_simple(
                    400,
                    "Authorization failed",
                    "Security check failed (state mismatch). Please restart the authorization.",
                )
                return

            self.auth_code = params["code"][0]
            self._notify_observer()
            page_html = (
                "<html><head><title>Nazak Browser Studio</title></head>"
                "<body style='font-family: sans-serif; background: #121214; color: #f4f4f5; display: flex; align-items: center; justify-content: center; height: 100vh; margin: 0;'>"
                "<div style='background: #1a1a1e; border: 1px solid #27272e; border-radius: 12px; padding: 32px 48px; text-align: center;'>"
                "<h2 style='color: #22c55e;'>YouTube authorization complete!</h2>"
                "<p style='color: #a1a1aa;'>OAuth token saved successfully. You can close this tab.</p>"
                "</div></body></html>"
            )
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(page_html.encode("utf-8"))
        else:
            err = params.get("error", ["Unknown error"])[0]
            self.error = err
            self._notify_observer()
            self._respond_simple(400, "Authorization failed", f"Authorization error: {html.escape(err)}")

    def _respond_simple(self, status: int, title: str, message: str):
        body = (
            "<html><head><title>Nazak Browser Studio</title></head>"
            "<body style='font-family: sans-serif; background: #121214; color: #f4f4f5; display: flex; align-items: center; justify-content: center; height: 100vh; margin: 0;'>"
            "<div style='background: #1a1a1e; border: 1px solid #27272e; border-radius: 12px; padding: 32px 48px; text-align: center;'>"
            f"<h2 style='color: #ef4444;'>{html.escape(title)}</h2>"
            f"<p style='color: #a1a1aa;'>{message}</p>"
            "</div></body></html>"
        )
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(body.encode("utf-8"))

    def log_message(self, format, *args):
        pass


class OAuthCallbackReceiver:
    """Encapsulated OAuth callback loop with per-session CSRF state validation.

    Replaces the legacy class-attribute globals: every receiver builds its own
    handler subclass, so two parallel authorization flows cannot read each
    other's codes, and each received ``?code=`` must carry the state token
    issued for that session.
    """

    def __init__(self, port: int = 3000, timeout: int = 120, expected_state: str | None = None, require_state: bool = True):
        self.port = port
        self.timeout = timeout
        self.expected_state = expected_state or (generate_oauth_state() if require_state else None)
        self.auth_code: str | None = None
        self.error: str | None = None
        self._server: HTTPServer | None = None
        self._handler_cls = self._build_handler(expected_state=self.expected_state, observer=self)

    @staticmethod
    def _build_handler(expected_state: str | None, observer: "OAuthCallbackReceiver") -> type[OAuthCallbackHandler]:
        return type(
            "BoundOAuthCallbackHandler",
            (OAuthCallbackHandler,),
            {"expected_state": expected_state, "_observer": observer},
        )

    @property
    def handler_cls(self) -> type[OAuthCallbackHandler]:
        return self._handler_cls

    @property
    def bound_port(self) -> int | None:
        return self._server.server_address[1] if self._server else None

    def start(self) -> None:
        """Bind the local callback server (idempotent)."""
        if self._server is None:
            self._server = HTTPServer(("127.0.0.1", self.port), self._handler_cls)
            self._server.timeout = 1.0

    def poll(self) -> bool:
        """Process at most one pending request. Returns True when the flow has finished."""
        self.start()
        self._server.handle_request()
        return self.auth_code is not None or self.error is not None

    def close(self) -> None:
        if self._server is not None:
            self._server.server_close()
            self._server = None

    def wait(self) -> str | None:
        """Blocking loop mirroring legacy ``listen_for_oauth_code`` semantics."""
        self.start()
        start_time = time.time()
        try:
            while time.time() - start_time < self.timeout:
                self._server.handle_request()
                if self.auth_code:
                    return self.auth_code
                if self.error:
                    break
        finally:
            self.close()
        return None


class AccountProvisioner:
    """
    Orchestrates batch account import, profile fingerprint creation,
    CDP automated Google login, and OAuth 2.0 dual-mode management.
    """

    def __init__(self, profile_manager: ProfileManager, profiles_dir: Path):
        self.profile_manager = profile_manager
        self.profiles_dir = profiles_dir

    def batch_import_and_create_profiles(
        self,
        raw_text: str,
        group_name: str = "Imported",
        posting_mode: str = "browser_stealth",
        proxy_list: list[str] | None = None,
    ) -> list[BrowserProfile]:
        """
        Parses multi-line account strings and creates corresponding isolated profiles with hardware fingerprints.
        """
        lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
        created_profiles = []
        proxy_idx = 0

        for i, line in enumerate(lines, start=1):
            acc = parse_account_string(line)
            if not acc:
                continue

            # Assign proxy
            proxy_cfg = ProxyConfig(type=ProxyType.DIRECT, raw="direct")
            if proxy_list and len(proxy_list) > 0:
                raw_px = proxy_list[proxy_idx % len(proxy_list)].strip()
                if raw_px:
                    proxy_cfg = ProxyConfig(type=ProxyType.HTTP, raw=raw_px)
                proxy_idx += 1

            fp = generate_random_fingerprint()
            pid = f"prof_acc_{int(time.time())}_{i}"

            username = acc["email"].split("@")[0] if "@" in acc["email"] else acc["email"]
            gpu_display = fp.webgl_unmasked_renderer.replace("NVIDIA GeForce ", "").replace("AMD Radeon ", "").strip()
            profile_name = f"{username} — {gpu_display}"

            # Encode account data into google settings notes & tags.
            # Sensitive fields are stored according to the user-selected mode
            # (plain / dpapi / passphrase) via secrets_store.
            notes_payload = json.dumps(
                encrypt_notes(
                    {
                        "account_email": acc["email"],
                        "account_password": acc["password"],
                        "totp_secret": acc["totp_secret"],
                        "recovery_email": acc["recovery_email"],
                        "posting_mode": posting_mode,
                        "auth_status": "ready_to_launch",
                        "imported_at": time.time(),
                        "oauth_tokens": {},
                    }
                )
            )

            google_settings = GoogleSettings(
                target_account_email=acc["email"],
                auto_open_page="youtube_studio" if posting_mode == "browser_stealth" else "google_login",
                tags=["Imported", "2FA", posting_mode],
                notes=notes_payload,
            )

            profile = BrowserProfile(
                id=pid,
                name=profile_name,
                group=group_name,
                proxy=proxy_cfg,
                fingerprint=fp,
                google=google_settings,
                status=ProfileStatus.STOPPED,
            )

            saved = self.profile_manager.create_profile(profile)
            created_profiles.append(saved)

        return created_profiles

    def build_oauth_auth_url(
        self, client_id: str, redirect_uri: str = "http://127.0.0.1:3000", state: str | None = None
    ) -> str:
        """Constructs Google OAuth 2.0 authorization URL.

        When ``state`` is provided (recommended — obtain one via
        ``generate_oauth_state()`` or ``OAuthCallbackReceiver`` and pass the
        same value to ``listen_for_oauth_code(state=...)``) it is embedded as
        the CSRF ``state`` parameter.
        """
        scope = "https%3A%2F%2Fwww.googleapis.com%2Fauth%2Fyoutube.upload"
        state_suffix = f"&state={state}" if state else ""
        return (
            f"https://accounts.google.com/o/oauth2/v2/auth?"
            f"access_type=offline&prompt=consent&scope={scope}&"
            f"response_type=code&client_id={client_id}&redirect_uri={redirect_uri}"
            f"{state_suffix}"
        )

    def listen_for_oauth_code(self, port: int = 3000, timeout: int = 120, state: str | None = None) -> str | None:
        """Spins up a temporary local HTTP server to receive the OAuth redirect code.

        Pass ``state`` (the same token embedded into the authorization URL via
        ``build_oauth_auth_url(..., state=...)``) to enforce CSRF protection:
        a ``?code=`` arriving with a missing or mismatched state is rejected.
        Without ``state`` the legacy permissive behavior is preserved.
        """
        receiver = OAuthCallbackReceiver(port=port, timeout=timeout, expected_state=state, require_state=bool(state))
        return receiver.wait()

    def exchange_oauth_code_for_tokens(
        self,
        code: str,
        client_id: str,
        client_secret: str,
        redirect_uri: str = "http://127.0.0.1:3000",
        proxy_url: str | None = None,
    ) -> dict[str, any] | None:
        """Exchanges Google OAuth 2.0 code for tokens through profile isolated proxy."""
        import urllib.parse
        import urllib.request

        token_url = "https://oauth2.googleapis.com/token"
        payload = {
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        }

        try:
            data = urllib.parse.urlencode(payload).encode("utf-8")
            req = urllib.request.Request(
                token_url,
                data=data,
                method="POST",
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
            )

            # Route through profile proxy if configured
            if proxy_url and proxy_url != "direct":
                proxy_handler = urllib.request.ProxyHandler({"http": proxy_url, "https": proxy_url})
                opener = urllib.request.build_opener(proxy_handler)
            else:
                opener = urllib.request.build_opener()

            with opener.open(req, timeout=20) as response:
                res_body = response.read().decode("utf-8")
                tokens = json.loads(res_body)
                tokens["obtained_at"] = time.time()
                return tokens
        except Exception as e:
            logger.error(f"Failed to exchange OAuth code for tokens: {e}")
            return None

    def refresh_access_token(
        self, refresh_token: str, client_id: str, client_secret: str, proxy_url: str | None = None
    ) -> dict[str, any] | None:
        """Uses refresh_token to acquire fresh access_token through profile proxy."""
        import urllib.parse
        import urllib.request

        token_url = "https://oauth2.googleapis.com/token"
        payload = {
            "refresh_token": refresh_token,
            "client_id": client_id,
            "client_secret": client_secret,
            "grant_type": "refresh_token",
        }

        try:
            data = urllib.parse.urlencode(payload).encode("utf-8")
            req = urllib.request.Request(
                token_url,
                data=data,
                method="POST",
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
            )

            # Route through profile proxy if configured
            if proxy_url and proxy_url != "direct":
                proxy_handler = urllib.request.ProxyHandler({"http": proxy_url, "https": proxy_url})
                opener = urllib.request.build_opener(proxy_handler)
            else:
                opener = urllib.request.build_opener()

            with opener.open(req, timeout=20) as response:
                res_body = response.read().decode("utf-8")
                tokens = json.loads(res_body)
                tokens["obtained_at"] = time.time()
                return tokens
        except Exception as e:
            logger.error(f"Failed to refresh access token: {e}")
            return None

    async def automate_google_login(
        self, profile: BrowserProfile, cdp_url: str, progress_callback: Callable | None = None
    ) -> tuple[bool, str]:
        """
        Executes stealth automated Google login over CDP:
        1. Navigates to accounts.google.com
        2. Types email
        3. Types password
        4. Injects live 6-digit TOTP code
        5. Handles recovery email if prompted
        6. Saves session
        """
        import asyncio

        from playwright.async_api import async_playwright

        notes = {}
        if profile.google.notes:
            try:
                notes = json.loads(profile.google.notes)
            except Exception:
                pass

        # Decrypt secret fields (supports legacy plaintext notes transparently).
        try:
            notes = reveal_notes(notes)
        except Exception as exc:
            logger.warning("Failed to decrypt profile secrets: %s", exc)
            return False, "Stored credentials are encrypted and the passphrase is unavailable."

        email = notes.get("account_email", profile.google.target_account_email or "")
        password = notes.get("account_password", "")
        totp_secret = notes.get("totp_secret", "")
        recovery = notes.get("recovery_email", "")

        if not email or not password or password.startswith("<encrypted"):
            return False, "Email or password is missing from the profile."

        async with async_playwright() as p:
            try:
                browser = await p.chromium.connect_over_cdp(cdp_url)
                context = browser.contexts[0] if browser.contexts else await browser.new_context()
                page = context.pages[0] if context.pages else await context.new_page()

                if progress_callback:
                    await progress_callback("Opening the Google sign-in page...")

                await page.goto(
                    "https://accounts.google.com/signin/v2/identifier?service=youtube",
                    wait_until="domcontentloaded",
                    timeout=45000,
                )
                await asyncio.sleep(2)

                # Check if already logged in
                if "myaccount.google.com" in page.url or "studio.youtube.com" in page.url:
                    await browser.close()
                    return True, "Account is already signed in."

                # 1. Fill Email
                email_input = page.locator("input[type='email'], #identifierId").first
                if await email_input.is_visible():
                    if progress_callback:
                        await progress_callback("Entering email...")
                    await email_input.click()
                    for ch in email:
                        await email_input.type(ch, delay=45)
                    await asyncio.sleep(0.5)

                    next_btn = page.locator("#identifierNext, button:has-text('Next')").first
                    await next_btn.click()
                    await asyncio.sleep(3)

                # 2. Fill Password
                pwd_input = page.locator("input[type='password'], [name='Passwd'], [name='password']").first
                await pwd_input.wait_for(state="visible", timeout=15000)
                if progress_callback:
                    await progress_callback("Entering password...")
                await pwd_input.click()
                for ch in password:
                    await pwd_input.type(ch, delay=45)
                await asyncio.sleep(0.5)

                next_btn_pwd = page.locator("#passwordNext, button:has-text('Next')").first
                await next_btn_pwd.click()
                await asyncio.sleep(4)

                # 3. Handle 2FA TOTP prompt if presented
                totp_input = page.locator(
                    "input[type='tel'], input[name='totpPin'], input[id='totpPin'], [aria-label*='code' i]"
                ).first
                if await totp_input.is_visible():
                    if not totp_secret:
                        await browser.close()
                        return False, "A 2FA code is required, but no TOTP secret was provided."

                    code = generate_totp_rfc6238(totp_secret)
                    if progress_callback:
                        await progress_callback(f"Generating and entering the 2FA code ({code})...")

                    await totp_input.click()
                    for ch in code:
                        await totp_input.type(ch, delay=55)
                    await asyncio.sleep(0.5)

                    next_btn_totp = page.locator("#totpNext, button:has-text('Next')").first
                    await next_btn_totp.click()
                    await asyncio.sleep(4)

                # 4. Handle recovery email challenge if presented
                rec_opt = page.locator("[data-challengeindex='0'], [data-challengetype='12']").first
                if await rec_opt.is_visible():
                    await rec_opt.click()
                    await asyncio.sleep(2)

                rec_input = page.locator("input[type='email'], [name='knowledgePreregisteredEmailResponse']").first
                if await rec_input.is_visible() and recovery:
                    if progress_callback:
                        await progress_callback("Entering recovery email...")
                    await rec_input.click()
                    for ch in recovery:
                        await rec_input.type(ch, delay=45)
                    await asyncio.sleep(0.5)
                    next_btn_rec = page.locator("button:has-text('Next')").first
                    await next_btn_rec.click()
                    await asyncio.sleep(4)

                # Update notes auth_status (write back the *stored* envelopes, not
                # the revealed plaintext held in ``notes``).
                stored = {}
                if profile.google.notes:
                    try:
                        stored = json.loads(profile.google.notes)
                    except Exception:
                        stored = {}
                stored["auth_status"] = "authenticated"
                stored["last_auth_time"] = time.time()
                profile.google.notes = json.dumps(stored)
                self.profile_manager.save_profiles()

                await browser.close()
                if progress_callback:
                    await progress_callback("Google sign-in completed successfully!")
                return True, "Google sign-in completed successfully!"

            except Exception as e:
                return False, f"Automatic sign-in error: {e!s}"
