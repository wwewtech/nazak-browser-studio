"""Live test: the web dashboard must not execute attacker-controlled health data.

Audit R3 finding R3-05: `health.ip` / `health.country` / `health.city` come from a
third-party geo lookup performed over plain HTTP through the user's proxy
(`core/proxy_checker.py`), so a hostile proxy or MITM can return markup. They were
interpolated into `innerHTML` without escaping, which gave script execution in the
dashboard origin (and therefore access to the local API).

This test drives a REAL Chromium against the REAL dashboard, mocks exactly the two
API responses an attacker can influence, and fails if any payload executes.

Skipped by default; run with:
    pytest -m live tests/live/test_dashboard_xss_live.py

Verified manually (Docker image + Chromium) that reverting the escaping in
`nazak/web/app.js` makes this test fail: the injected script runs and reaches
`/api/security/secrets-mode` (323-byte response read from the injected code).
"""

import contextlib
import json
import socket
import threading
import time
import urllib.request

import pytest

from nazak.api.server import app

PAYLOAD_COUNTRY = (
    '</span><img src=x onerror="window.__xss_country=1;'
    "fetch('/api/security/secrets-mode').then(r=>r.text())"
    '.then(t=>{window.__xss_exfil=t.length})">'
)
PAYLOAD_CITY = '</span><img src=x onerror="window.__xss_city=1">'
PAYLOAD_IP = '"><img src=x onerror="window.__xss_ip=1">'

HOSTILE_HEALTH = {
    "status": "healthy",
    "ping_ms": 12.5,
    "ip": PAYLOAD_IP,
    "country": PAYLOAD_COUNTRY,
    "city": PAYLOAD_CITY,
    "isp": "AS probe",
    "asn": "AS123",
    "timezone_name": "UTC",
    "latitude": 1.0,
    "longitude": 2.0,
    "google": {
        "google_main": True,
        "google_accounts": True,
        "google_ads": True,
        "youtube": True,
        "latencies_ms": {"google_main": 10.0},
        "all_ok": True,
    },
    "data_isolation_ok": True,
    "error_message": "ok",
    "checked_at": "2026-10-06T00:00:00Z",
}

PROFILE = {
    "id": "prof_xss",
    "name": "XSS Probe",
    "group": "Probe",
    "status": "stopped",
    "pid": None,
    "proxy": {"type": "direct", "host": None, "port": None, "raw": None},
    "google": {"notes": "", "tags": []},
    "fingerprint": {
        "hardware_concurrency": 8,
        "device_memory": 16,
        "screen_width": 1920,
        "screen_height": 1080,
    },
    "last_health_check": None,
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


@pytest.mark.live
def test_dashboard_does_not_execute_hostile_health_data():
    sync_playwright = pytest.importorskip(
        "playwright.sync_api", reason="Playwright is required for the live browser test"
    ).sync_playwright
    with _live_server() as base, sync_playwright() as pw:
        browser = pw.chromium.launch(args=["--no-sandbox"])
        try:
            page = browser.new_page()
            page.goto(f"{base}/", wait_until="load")
            assert page.evaluate("() => typeof renderDiagModalContent === 'function'")

            # 1. the renderer itself, called with attacker-controlled data
            page.evaluate("(h) => renderDiagModalContent({}, h, false)", HOSTILE_HEALTH)
            page.wait_for_timeout(1500)
            direct = page.evaluate(
                "() => ({country: window.__xss_country|0, city: window.__xss_city|0,"
                " ip: window.__xss_ip|0, exfil: window.__xss_exfil||null})"
            )

            # 2. the full UI path: mocked API responses + a real click
            page.evaluate(
                "() => { window.__xss_country = 0; window.__xss_city = 0;"
                " window.__xss_ip = 0; window.__xss_exfil = null; }"
            )

            def _handler(route):
                url = route.request.url
                if url.endswith("/api/profiles/prof_xss/check"):
                    route.fulfill(status=200, content_type="application/json", body=json.dumps(HOSTILE_HEALTH))
                elif url.endswith("/api/profiles"):
                    route.fulfill(status=200, content_type="application/json", body=json.dumps([PROFILE]))
                else:
                    route.continue_()

            page.route("**/api/profiles**", _handler)
            page.evaluate("() => fetchProfiles()")
            page.wait_for_selector('button[title="Diagnostics"]', timeout=15000)
            page.click('button[title="Diagnostics"]')
            page.wait_for_timeout(3000)
            ui_path = page.evaluate(
                "() => ({country: window.__xss_country|0, city: window.__xss_city|0,"
                " ip: window.__xss_ip|0, exfil: window.__xss_exfil||null})"
            )

            markup = page.evaluate("() => (document.getElementById('diag-modal-body')||{}).innerHTML || ''")
        finally:
            browser.close()

    assert direct == {"country": 0, "city": 0, "ip": 0, "exfil": None}, f"payload executed (renderer): {direct}"
    assert ui_path == {"country": 0, "city": 0, "ip": 0, "exfil": None}, f"payload executed (UI): {ui_path}"
    # the hostile string must appear as *text*, i.e. escaped in the markup
    assert "&lt;img src=x onerror" in markup, "payload markup was not escaped in the DOM"
