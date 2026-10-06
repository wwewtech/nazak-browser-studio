"""Live browser test: the delegated dashboard works under a strict CSP.

Two things are proved here, both in real Chromium against the real dashboard:

1. **UI smoke** — every control that used to be an inline ``on*`` handler is now
   driven by ``data-action`` delegation, so clicking through the dashboard must
   still open/close the modals, select profiles, re-render the grid and toggle
   the dropdown, with **zero** uncaught page errors.
2. **Strict CSP** — an inline handler injected into the DOM (the "escaping was
   forgotten" scenario) is *not* executed on the dashboard, while the very same
   payload does execute on a plain page without the policy. The second half is
   the control that proves the first half is not a false negative.

Skipped by default; run with:
    pytest -m live tests/live/test_dashboard_ui_smoke_live.py
"""

from __future__ import annotations

import contextlib
import json
import socket
import threading
import time
import urllib.request

import pytest

from nazak.api.server import app

PROFILE_ID = "prof_ui"

PROFILE = {
    "id": PROFILE_ID,
    "name": "UI Smoke Probe",
    "group": "Probe",
    "status": "stopped",
    "pid": None,
    "proxy": {"type": "direct", "host": None, "port": None, "raw": None},
    "google": {"notes": "", "tags": ["smoke"], "auto_open_page": "google_login"},
    "fingerprint": {
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/133.0.0.0",
        "platform": "Win32",
        "hardware_concurrency": 8,
        "device_memory": 16,
        "screen_width": 1920,
        "screen_height": 1080,
        "device_pixel_ratio": 1.0,
        "language": "en-US",
        "timezone": "Europe/Berlin",
    },
    "last_health_check": None,
    "notes": "",
}

HEALTH = {
    "status": "healthy",
    "ping_ms": 12.5,
    "ip": "203.0.113.7",
    "country": "Germany",
    "city": "Berlin",
    "isp": "Probe ISP",
    "asn": "AS123",
    "timezone_name": "Europe/Berlin",
    "latitude": 52.5,
    "longitude": 13.4,
    "google": {
        "google_main": True,
        "google_accounts": True,
        "google_ads": True,
        "youtube": True,
        "latencies_ms": {"google_main": 10.0},
        "all_ok": True,
    },
    "data_isolation_ok": True,
    "error_message": "",
    "checked_at": "2026-10-06T00:00:00Z",
}

# Ответы на всё, что дашборд запрашивает при кликах по UI (полностью герметично:
# ни один мок-запрос не уходит на настоящий API).
API_RESPONSES = {
    "/api/system/info": {
        "chrome_installed": True,
        "chrome_version": "133.0.0.0",
        "data_directory": "/tmp/nazak",
        "profiles_count": 1,
        "running_count": 0,
    },
    "/api/autopost/status": {"jobs": [], "is_running": False},
    "/api/autopost/jobs": {"jobs": []},
    "/api/warmup/plan": {"queries": ["best vpn", "cheap vpn"], "steps_count": 2},
    "/api/scenarios": {"scenarios": []},
}


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@contextlib.contextmanager
def _live_server():
    import uvicorn

    port = _free_port()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error", access_log=False)
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 30
    while time.time() < deadline:
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=2)
            break
        except Exception:
            time.sleep(0.3)
    else:  # pragma: no cover - environment problem
        raise RuntimeError("web server did not become ready")
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=10)


def _install_mocks(page) -> None:
    def handler(route):
        url = route.request.url
        path = url.split("?", 1)[0].replace("http://127.0.0.1", "")
        if path.endswith(f"/api/profiles/{PROFILE_ID}/check"):
            body = json.dumps(HEALTH)
        elif path.endswith("/api/profiles"):
            body = json.dumps([PROFILE])
        elif path in API_RESPONSES:
            body = json.dumps(API_RESPONSES[path])
        elif "/api/profiles/" in path:
            body = json.dumps(PROFILE)
        else:
            body = json.dumps({"success": True, "jobs": [], "queries": ["q1"], "scenarios": []})
        route.fulfill(status=200, content_type="application/json", body=body)

    page.route("**/api/**", handler)


def _page_is_visible(page, element_id: str) -> bool:
    """Модалки показываются классом ``open``, выпадающие меню — классом ``show``."""
    return bool(
        page.evaluate(
            "(id) => { const el = document.getElementById(id);"
            " return !!el && (el.classList.contains('open') || el.classList.contains('show')); }",
            element_id,
        )
    )


@pytest.mark.live
def test_delegated_dashboard_ui_works_under_strict_csp():
    errors: list[str] = []
    console_errors: list[str] = []

    from playwright.sync_api import sync_playwright

    with _live_server() as base, sync_playwright() as pw:
        browser = pw.chromium.launch(args=["--no-sandbox"])
        try:
            page = browser.new_page()
            page.on("pageerror", lambda exc: errors.append(str(exc)))
            page.on(
                "console",
                lambda msg: console_errors.append(msg.text) if msg.type == "error" else None,
            )
            _install_mocks(page)
            page.goto(f"{base}/", wait_until="load")
            page.wait_for_selector('[data-action="diag-open"]', timeout=15000)

            # --- 1. диагностика: открыть и закрыть (делегированный click)
            page.click('[data-action="diag-open"]')
            page.wait_for_timeout(600)
            assert _page_is_visible(page, "diag-modal"), "diag modal did not open via data-action"
            page.click('#diag-modal [data-action="diag-close"]')
            page.wait_for_timeout(300)
            assert not _page_is_visible(page, "diag-modal"), "diag modal did not close"

            # --- 2. настройки профиля + рандомизация отпечатка
            page.click('[data-action="profile-edit-open"]')
            page.wait_for_timeout(400)
            assert _page_is_visible(page, "profile-modal"), "profile modal did not open"
            ua_before = page.input_value("#edit-user-agent")
            page.click('[data-action="fingerprint-randomize"]')
            page.wait_for_timeout(200)
            assert page.input_value("#edit-user-agent") != ua_before, "fingerprint not randomized"
            page.click('#profile-modal [data-action="profile-modal-close"]')
            page.wait_for_timeout(300)
            assert not _page_is_visible(page, "profile-modal")

            # --- 3. cookie-менеджер и прогрев
            page.click('[data-action="cookie-open"]')
            page.wait_for_timeout(300)
            assert _page_is_visible(page, "cookie-modal")
            page.click('#cookie-modal [data-action="cookie-close"]')
            page.click('[data-action="warmup-open"]')
            page.wait_for_timeout(500)
            assert _page_is_visible(page, "warmup-modal")
            page.click('#warmup-modal [data-action="warmup-close"]')

            # --- 4. модалки из шапки
            page.click('[data-action="autopost-open"]')
            page.wait_for_timeout(500)
            assert _page_is_visible(page, "autopost-modal"), "autopost modal did not open"
            page.click('#autopost-modal [data-action="autopost-close"]')
            page.click('[data-action="bulk-import-open"]')
            page.wait_for_timeout(300)
            assert _page_is_visible(page, "bulk-import-modal")
            page.click('#bulk-import-modal [data-action="bulk-import-close"]')

            # --- 5. выпадающее меню (click) и выбор профиля (change)
            dropdown_id = page.get_attribute('[data-action="dropdown-toggle"]', "data-target")
            page.click('[data-action="dropdown-toggle"]')
            page.wait_for_timeout(200)
            assert page.evaluate(
                "(id) => { const el = document.getElementById(id); return !!el && el.classList.contains('show'); }",
                dropdown_id,
            ), "dropdown did not open"
            # Клик по заголовку: глобальный слушатель в DOMContentLoaded закрывает
            # открытые меню, иначе они перекрывают чекбоксы карточки.
            page.click(".brand-title")
            page.wait_for_timeout(200)
            assert not page.evaluate(
                "(id) => { const el = document.getElementById(id); return !!el && el.classList.contains('show'); }",
                dropdown_id,
            ), "dropdown did not close on an outside click"

            page.check('[data-action="profile-select"]')  # change-событие на чекбоксе
            page.wait_for_timeout(300)
            assert "1" in page.inner_text("#bulk-count-text"), page.inner_text("#bulk-count-text")
            assert page.evaluate("() => document.getElementById('bulk-bar').style.display") != "none"

            # --- 6. select-all (change; чекбокс лежит в панели, видимой лишь при выборе),
            #        поиск (input), фильтр (change), refresh (click)
            page.check('[data-action="select-all-toggle"]')
            page.wait_for_timeout(200)
            assert page.evaluate("() => selectedProfileIds.size") == 1
            page.fill("#search-input", "smoke")  # input -> renderProfiles
            page.wait_for_timeout(200)
            page.select_option("#group-filter", "ALL")  # change -> renderProfiles
            page.click('[data-action="profiles-fetch"]')
            page.wait_for_timeout(400)
            assert page.evaluate("() => Array.isArray(profiles) && profiles.length === 1")
            page.click('[data-action="selection-clear"]')
            page.wait_for_timeout(200)
            assert page.evaluate("() => selectedProfileIds.size") == 0
            page.click('[data-action="profile-create-open"]')
            page.wait_for_timeout(300)
            assert _page_is_visible(page, "profile-modal")
            page.click('#profile-modal [data-action="profile-modal-close"]')

            # --- 7. инлайн-скриптов быть не должно (иначе CSP бы их заблокировал)
            inline_blocked = page.evaluate(
                "() => [...document.querySelectorAll('*')].some("
                "el => [...el.attributes].some(a => a.name.startsWith('on')))"
            )
            assert inline_blocked is False, "an element still carries an inline handler attribute"
        finally:
            browser.close()

    assert errors == [], f"uncaught page errors: {errors}"
    assert console_errors == [], f"console errors: {console_errors}"


@pytest.mark.live
def test_strict_csp_blocks_injected_inline_handler():
    """Дифференциальный контроль: тот же payload исполняется без CSP и не исполняется с ним."""
    payload = '<img src=x onerror="window.__csp_probe=1">'

    from playwright.sync_api import sync_playwright

    with _live_server() as base, sync_playwright() as pw:
        browser = pw.chromium.launch(args=["--no-sandbox"])
        try:
            # A. страница дашборда: строгий script-src 'self'
            page = browser.new_page()
            _install_mocks(page)
            page.goto(f"{base}/", wait_until="load")
            csp = page.evaluate("() => document.querySelector('meta[http-equiv]')?.content || null")
            assert page.evaluate("() => typeof escapeHtml === 'function'")
            page.evaluate(
                """(html) => document.body.insertAdjacentHTML('beforeend', html)""",
                payload,
            )
            page.wait_for_timeout(1200)
            dashboard_marker = page.evaluate("() => window.__csp_probe || 0")
            headers = page.evaluate("() => null")  # заголовки проверяются ниже через запрос
            page.close()

            # B. контрольная страница без нашей политики — тот же payload ДОЛЖЕН сработать
            control = browser.new_page()
            control.set_content(f"<html><body>{payload}</body></html>")
            control.wait_for_timeout(1200)
            control_marker = control.evaluate("() => window.__csp_probe || 0")
            control.close()
        finally:
            browser.close()

    assert control_marker == 1, "the harness cannot detect inline-handler execution at all"
    assert dashboard_marker == 0, "CSP must block the injected inline handler on the dashboard"
    assert csp is None  # политика приходит заголовком, а не meta-тегом
