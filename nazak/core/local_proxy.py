"""
Local Authenticating Proxy Forwarder — audit fix P0-1 (proxy auth).

Chrome cannot attach credentials to ``--proxy-server``, and the MV3 extension
that used to answer 407 challenges no longer loads in branded Chrome 137+.
CDP ``Fetch.authRequired`` only sees challenges for requests initiated through
the *same* CDP session, which external Playwright/Selenium sessions never are.

Solution: the browser talks to a tiny unauthenticated loopback proxy started
per profile; that forwarder adds ``Proxy-Authorization`` for the real upstream
proxy (HTTP/HTTPS). Protocol-level, session-independent, works for every tab
and for CLI/GUI launches.
"""

from __future__ import annotations

import base64
import logging
import selectors
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import cast
from urllib.parse import urlsplit

logger = logging.getLogger(__name__)

_CONNECT_TIMEOUT = 15.0
_RELAY_IDLE_TIMEOUT = 120.0


class _ForwardHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    # Unbuffered reads: after CONNECT the same socket carries raw TLS bytes and
    # BaseHTTPRequestHandler must never over-read them into its request buffer.
    rbufsize = 0
    forwarder: AuthForwardProxy | None = None

    def log_message(self, *args):  # keep the console clean
        pass

    # ------------------------------------------------------------------ CONNECT
    def do_CONNECT(self) -> None:
        fwd = self.forwarder
        if fwd is None:
            self.send_error(500)
            return
        try:
            upstream = socket.create_connection((fwd.upstream_host, fwd.upstream_port), timeout=_CONNECT_TIMEOUT)
        except Exception as exc:
            logger.debug("forwarder: upstream connect failed: %s", exc)
            self.send_error(502, "Upstream proxy unreachable")
            return
        try:
            request = (
                f"CONNECT {self.path} HTTP/1.1\r\nHost: {self.path}\r\nProxy-Authorization: {fwd.auth_header}\r\n\r\n"
            )
            upstream.sendall(request.encode("latin-1"))
            head = b""
            while b"\r\n\r\n" not in head and len(head) < 65536:
                chunk = upstream.recv(4096)
                if not chunk:
                    break
                head += chunk
            status_line = head.split(b"\r\n", 1)[0]
            if b" 200" not in status_line:
                self.send_error(502, "Upstream proxy rejected CONNECT")
                return
            leftover = head.split(b"\r\n\r\n", 1)[1]
            self.send_response(200, "Connection Established")
            self.end_headers()
            self.wfile.flush()
            # Stop the HTTP request loop: this socket is a raw tunnel now.
            self.close_connection = True
            if leftover:
                self.connection.sendall(leftover)
            self._relay(self.connection, upstream)
        finally:
            try:
                upstream.close()
            except OSError:
                pass

    # ------------------------------------------------------ plain HTTP forward
    def _forward_http(self) -> None:
        self.close_connection = True
        fwd = self.forwarder
        if fwd is None:
            self.send_error(500)
            return
        parts = urlsplit(self.path)
        if not parts.hostname:
            self.send_error(400, "Absolute URI required for proxying")
            return
        try:
            upstream = socket.create_connection((fwd.upstream_host, fwd.upstream_port), timeout=_CONNECT_TIMEOUT)
        except Exception as exc:
            logger.debug("forwarder: upstream connect failed: %s", exc)
            self.send_error(502, "Upstream proxy unreachable")
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length) if length else b""
            lines = [f"{self.command} {self.path} {self.request_version}"]
            for key, value in self.headers.items():
                if key.lower() in ("proxy-authorization", "proxy-connection", "connection"):
                    continue
                lines.append(f"{key}: {value}")
            lines.append(f"Proxy-Authorization: {fwd.auth_header}")
            # One exchange per connection keeps auth deterministic.
            lines.append("Connection: close")
            raw = ("\r\n".join(lines) + "\r\n\r\n").encode("latin-1") + body
            upstream.sendall(raw)
            self._relay(upstream, self.connection)
        finally:
            try:
                upstream.close()
            except OSError:
                pass

    do_GET = _forward_http
    do_POST = _forward_http
    do_PUT = _forward_http
    do_DELETE = _forward_http
    do_HEAD = _forward_http
    do_OPTIONS = _forward_http
    do_PATCH = _forward_http

    # -------------------------------------------------------------------- relay
    @staticmethod
    def _relay(a: socket.socket, b: socket.socket) -> None:
        sel = None
        try:
            sel = selectors.DefaultSelector()
            sel.register(a, selectors.EVENT_READ, b)
            sel.register(b, selectors.EVENT_READ, a)
            while True:
                events = sel.select(timeout=_RELAY_IDLE_TIMEOUT)
                if not events:
                    return
                for key, _ in events:
                    data = cast(socket.socket, key.fileobj).recv(65536)
                    if not data:
                        return
                    cast(socket.socket, key.data).sendall(data)
        except OSError:
            return
        finally:
            if sel is not None:
                try:
                    sel.close()
                except Exception:
                    pass


class AuthForwardProxy:
    """Loopback HTTP proxy that injects upstream credentials into every request."""

    def __init__(self, upstream_host: str, upstream_port: int, username: str, password: str):
        token = base64.b64encode(f"{username}:{password}".encode()).decode("ascii")
        self.upstream_host = upstream_host
        self.upstream_port = upstream_port
        self.auth_header = f"Basic {token}"
        self.port: int | None = None
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> int:
        parent = self

        class _BoundHandler(_ForwardHandler):
            forwarder = parent

        server = ThreadingHTTPServer(("127.0.0.1", 0), _BoundHandler)
        server.daemon_threads = True
        self._server = server
        self.port = server.server_address[1]
        self._thread = threading.Thread(target=server.serve_forever, daemon=True, name="NazakAuthForwarder")
        self._thread.start()
        logger.info("auth forwarder: 127.0.0.1:%s -> %s:%s", self.port, self.upstream_host, self.upstream_port)
        return self.port

    def stop(self) -> None:
        server = self._server
        if server is not None:
            try:
                server.shutdown()
                server.server_close()
            except Exception:
                pass
        self._server = None
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)

    @property
    def alive(self) -> bool:
        return bool(self._thread and self._thread.is_alive())
