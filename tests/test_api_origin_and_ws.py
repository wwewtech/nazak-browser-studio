"""Origin/Host-периметр и живое WebSocket-рукопожатие (R3-round2b).

Живой браузерный тест (`tests/live/test_dashboard_ui_smoke_live.py`) нашёл, что
дашборд на **нестандартном порту** получал 403 на каждый запрос с заголовком
Origin: старый guard сверял Origin со списком портов ``{8899, 3000}``, который
пополнялся вызовом ``configure_local_access()`` из ``main.py``. Любой запуск
приложения голым ASGI-сервером (``uvicorn nazak.api.server:app``, gunicorn,
встраивание, тесты) оставлял порт незарегистрированным — а WebSocket-рукопожатие
Origin отправляет ВСЕГДА, поэтому live-обновления не работали вовсе.

Здесь проверяется, что guard сравнивает Origin с Host запроса (same-origin на
любом порту) и по-прежнему режет чужой Origin и локальную страницу с другого порта.
"""

from __future__ import annotations

import asyncio
import socket
import threading
import time
import urllib.request

import pytest
import websockets
from starlette.testclient import TestClient

from nazak.api import server
from nazak.api.server import _origin_matches_request, app


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


# --------------------------------------------------------------------------- чистая логика
@pytest.mark.parametrize(
    ("origin", "host", "expected", "why"),
    [
        ("http://127.0.0.1:8899", "127.0.0.1:8899", True, "дефолтный порт"),
        ("http://127.0.0.1:46399", "127.0.0.1:46399", True, "кастомный порт (раньше 403)"),
        ("http://localhost:9000", "localhost:9000", True, "localhost на кастомном порту"),
        ("https://127.0.0.1:8443", "127.0.0.1:8443", True, "https, тот же порт"),
        ("http://[::1]:9001", "[::1]:9001", True, "IPv6 loopback"),
        ("http://localhost:3000", "testserver", True, "CORS-whitelist: локальный dev-сервер"),
        ("http://127.0.0.1:9000", "127.0.0.1:8899", False, "локальная страница с другого порта"),
        ("https://evil.example.com", "127.0.0.1:8899", False, "чужой Origin"),
        ("http://127.0.0.1.evil.com:8899", "127.0.0.1:8899", False, "подделка суффиксом"),
        ("null", "127.0.0.1:8899", False, "Origin: null"),
        (None, "127.0.0.1:8899", True, "Origin отсутствует (не браузерный запрос)"),
        ("http://127.0.0.1", "127.0.0.1", True, "оба без порта — семантика порта 80"),
        ("http://127.0.0.1:8899", None, True, "порт 8899 в CORS-whitelist (Host не важен)"),
    ],
)
def test_origin_must_match_request_host(origin, host, expected, why):
    assert _origin_matches_request(origin, host) is expected, why


def test_whitelisted_ports_still_pass_for_cross_origin_clients():
    """Прежний CORS-кейс (dev-сервер на :3000) не потерян при переходе на same-origin."""
    assert _origin_matches_request("http://localhost:3000", "127.0.0.1:8899") is True
    assert _origin_matches_request("http://127.0.0.1:3000", "127.0.0.1:8899") is True
    assert _origin_matches_request("http://127.0.0.1:3001", "127.0.0.1:8899") is False


def test_origin_check_does_not_depend_on_registered_ports(monkeypatch):
    """Guard больше не зависит от configure_local_access(): порт не регистрируем."""
    monkeypatch.setattr(server, "_ALLOWED_PORTS", set())
    assert _origin_matches_request("http://127.0.0.1:54321", "127.0.0.1:54321") is True
    assert _origin_matches_request("http://127.0.0.1:54321", "127.0.0.1:12345") is False


def test_host_name_and_port_parsing():
    assert server._host_port("127.0.0.1:8899") == 8899
    assert server._host_port("[::1]:8899") == 8899
    assert server._host_port("localhost") is None
    assert server._host_port("") is None
    assert server._host_name("[::1]:8899") == "::1"


# --------------------------------------------------------------------------- HTTP через TestClient
@pytest.mark.parametrize("port", [8899, 9123, 54321])
def test_same_origin_requests_are_accepted_on_any_port(port):
    client = TestClient(app)
    host = f"127.0.0.1:{port}"
    resp = client.get("/api/system/info", headers={"host": host, "origin": f"http://{host}"})
    assert resp.status_code == 200, resp.text


def test_cross_origin_and_foreign_origin_are_refused():
    client = TestClient(app)
    assert (
        client.get(
            "/api/system/info",
            headers={"host": "127.0.0.1:8899", "origin": "http://127.0.0.1:9000"},
        ).status_code
        == 403
    )
    assert (
        client.get(
            "/api/system/info",
            headers={"host": "127.0.0.1:8899", "origin": "https://evil.example.com"},
        ).status_code
        == 403
    )


# --------------------------------------------------------------------------- живой WebSocket
def test_websocket_handshake_works_on_a_custom_port():
    """Рукопожатие с браузерными заголовками: same-origin пускают, чужой Origin — нет."""
    import uvicorn

    port = _free_port()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error", access_log=False)
    uv_server = uvicorn.Server(config)
    thread = threading.Thread(target=uv_server.run, daemon=True)
    thread.start()
    deadline = time.time() + 30
    while time.time() < deadline:
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=2)
            break
        except Exception:
            time.sleep(0.2)
    else:  # pragma: no cover - environment problem
        raise RuntimeError("server did not become ready")

    host = f"127.0.0.1:{port}"

    async def probe() -> dict[str, str]:
        out: dict[str, str] = {}
        cases = {
            "browser": {"Host": host, "Origin": f"http://{host}", "Sec-Fetch-Site": "same-origin"},
            "foreign": {"Host": host, "Origin": "https://evil.example.com"},
            "other_port": {"Host": host, "Origin": "http://127.0.0.1:1"},
        }
        for label, headers in cases.items():
            try:
                async with websockets.connect(
                    f"ws://127.0.0.1:{port}/ws/events", additional_headers=headers, open_timeout=5
                ) as ws:
                    await ws.send("ping")
                    out[label] = await asyncio.wait_for(ws.recv(), timeout=5)
            except Exception as exc:
                out[label] = f"{type(exc).__name__}"
        return out

    try:
        results = asyncio.run(probe())
    finally:
        uv_server.should_exit = True
        thread.join(timeout=10)

    assert results["browser"] == "pong", results
    assert results["foreign"] != "pong", results
    assert results["other_port"] != "pong", results
