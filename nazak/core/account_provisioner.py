"""
Account Provisioner & Dual-Mode Activation Engine.
Automates batch importing accounts (Login:Pass:2FA:Recovery), generating isolated browser profiles,
performing automated Google login via CDP with TOTP generation, and managing OAuth 2.0 / YouTube Studio sessions.
"""

import base64
import hashlib
import hmac
import json
import logging
import re
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


class OAuthCallbackHandler(BaseHTTPRequestHandler):
    """Local HTTP callback receiver for Google OAuth 2.0 redirect flow."""

    auth_code = None
    error = None

    def do_GET(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)

        if "code" in params:
            OAuthCallbackHandler.auth_code = params["code"][0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            html = (
                "<html><head><title>Nazak Browser Studio</title></head>"
                "<body style='font-family: sans-serif; background: #121214; color: #f4f4f5; display: flex; align-items: center; justify-content: center; height: 100vh; margin: 0;'>"
                "<div style='background: #1a1a1e; border: 1px solid #27272e; border-radius: 12px; padding: 32px 48px; text-align: center;'>"
                "<h2 style='color: #22c55e;'>Авторизация YouTube завершена!</h2>"
                "<p style='color: #a1a1aa;'>OAuth токен успешно сохранен. Можете закрыть эту вкладку.</p>"
                "</div></body></html>"
            )
            self.wfile.write(html.encode("utf-8"))
        else:
            err = params.get("error", ["Unknown error"])[0]
            OAuthCallbackHandler.error = err
            self.send_response(400)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(f"Ошибка авторизации: {err}".encode())

    def log_message(self, format, *args):
        pass


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

            # Encode account data into google settings notes & tags
            notes_payload = json.dumps(
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

    def build_oauth_auth_url(self, client_id: str, redirect_uri: str = "http://127.0.0.1:3000") -> str:
        """Constructs Google OAuth 2.0 authorization URL."""
        scope = "https%3A%2F%2Fwww.googleapis.com%2Fauth%2Fyoutube.upload"
        return (
            f"https://accounts.google.com/o/oauth2/v2/auth?"
            f"access_type=offline&prompt=consent&scope={scope}&"
            f"response_type=code&client_id={client_id}&redirect_uri={redirect_uri}"
        )

    def listen_for_oauth_code(self, port: int = 3000, timeout: int = 120) -> str | None:
        """Spins up a temporary local HTTP server to receive the OAuth redirect code."""
        OAuthCallbackHandler.auth_code = None
        OAuthCallbackHandler.error = None

        server = HTTPServer(("127.0.0.1", port), OAuthCallbackHandler)
        server.timeout = 1.0

        start_time = time.time()
        while time.time() - start_time < timeout:
            server.handle_request()
            if OAuthCallbackHandler.auth_code:
                server.server_close()
                return OAuthCallbackHandler.auth_code
            if OAuthCallbackHandler.error:
                break

        server.server_close()
        return None

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

        email = notes.get("account_email", profile.google.target_account_email or "")
        password = notes.get("account_password", "")
        totp_secret = notes.get("totp_secret", "")
        recovery = notes.get("recovery_email", "")

        if not email or not password:
            return False, "Отсутствует email или пароль в профиле."

        async with async_playwright() as p:
            try:
                browser = await p.chromium.connect_over_cdp(cdp_url)
                context = browser.contexts[0] if browser.contexts else await browser.new_context()
                page = context.pages[0] if context.pages else await context.new_page()

                if progress_callback:
                    await progress_callback("Открытие страницы авторизации Google...")

                await page.goto(
                    "https://accounts.google.com/signin/v2/identifier?service=youtube",
                    wait_until="domcontentloaded",
                    timeout=45000,
                )
                await asyncio.sleep(2)

                # Check if already logged in
                if "myaccount.google.com" in page.url or "studio.youtube.com" in page.url:
                    await browser.close()
                    return True, "Аккаунт уже авторизован."

                # 1. Fill Email
                email_input = page.locator("input[type='email'], #identifierId").first
                if await email_input.is_visible():
                    if progress_callback:
                        await progress_callback("Ввод Email...")
                    await email_input.click()
                    for ch in email:
                        await email_input.type(ch, delay=45)
                    await asyncio.sleep(0.5)

                    next_btn = page.locator("#identifierNext, button:has-text('Next'), button:has-text('Далее')").first
                    await next_btn.click()
                    await asyncio.sleep(3)

                # 2. Fill Password
                pwd_input = page.locator("input[type='password'], [name='Passwd'], [name='password']").first
                await pwd_input.wait_for(state="visible", timeout=15000)
                if progress_callback:
                    await progress_callback("Ввод пароля...")
                await pwd_input.click()
                for ch in password:
                    await pwd_input.type(ch, delay=45)
                await asyncio.sleep(0.5)

                next_btn_pwd = page.locator("#passwordNext, button:has-text('Next'), button:has-text('Далее')").first
                await next_btn_pwd.click()
                await asyncio.sleep(4)

                # 3. Handle 2FA TOTP prompt if presented
                totp_input = page.locator(
                    "input[type='tel'], input[name='totpPin'], input[id='totpPin'], [aria-label*='код' i], [aria-label*='code' i]"
                ).first
                if await totp_input.is_visible():
                    if not totp_secret:
                        await browser.close()
                        return False, "Требуется 2FA код, но TOTP ключ не указан."

                    code = generate_totp_rfc6238(totp_secret)
                    if progress_callback:
                        await progress_callback(f"Генерация и ввод 2FA кода ({code})...")

                    await totp_input.click()
                    for ch in code:
                        await totp_input.type(ch, delay=55)
                    await asyncio.sleep(0.5)

                    next_btn_totp = page.locator("#totpNext, button:has-text('Next'), button:has-text('Далее')").first
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
                        await progress_callback("Ввод резервной почты...")
                    await rec_input.click()
                    for ch in recovery:
                        await rec_input.type(ch, delay=45)
                    await asyncio.sleep(0.5)
                    next_btn_rec = page.locator("button:has-text('Next'), button:has-text('Далее')").first
                    await next_btn_rec.click()
                    await asyncio.sleep(4)

                # Update notes auth_status
                notes["auth_status"] = "authenticated"
                notes["last_auth_time"] = time.time()
                profile.google.notes = json.dumps(notes)
                self.profile_manager.save_profiles()

                await browser.close()
                if progress_callback:
                    await progress_callback("Авторизация Google успешно завершена!")
                return True, "Авторизация Google успешно завершена!"

            except Exception as e:
                return False, f"Ошибка авто-логина: {e!s}"
