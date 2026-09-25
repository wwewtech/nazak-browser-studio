"""
Unit tests for the loopback authenticating proxy forwarder (audit fix P0-1).

Chrome cannot embed proxy credentials into --proxy-server and the MV3
onAuthRequired worker no longer loads in branded Chrome 137+, so credentialed
proxies are routed through this forwarder.
"""

import base64
import socket
import socketserver
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from nazak.core.local_proxy import AuthForwardProxy

USER, PWD = "u1", "p1"
EXPECTED_AUTH = "Basic " + base64.b64encode(f"{USER}:{PWD}".encode()).decode()


class UpstreamProxy(BaseHTTPRequestHandler):
    """Stub upstream proxy that requires Basic proxy auth."""

    protocol_version = "HTTP/1.1"
    received: list[tuple[str, str, str | None]] = []

    def log_message(self, *args):
        pass

    def _auth_ok(self) -> bool:
        auth = self.headers.get("Proxy-Authorization")
        type(self).received.append((self.command, self.path, auth))
        return auth == EXPECTED_AUTH

    def do_GET(self):
        if not self._auth_ok():
            self.send_response(407)
            self.send_header("Proxy-Authenticate", 'Basic realm="test"')
            self.send_header("Connection", "close")
            self.end_headers()
            return
        body = b"UPSTREAM_OK"
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)

    def do_CONNECT(self):
        if not self._auth_ok():
            self.send_response(407)
            self.send_header("Proxy-Authenticate", 'Basic realm="test"')
            self.send_header("Connection", "close")
            self.end_headers()
            return
        self.send_response(200, "Connection Established")
        self.send_header("Connection", "close")
        self.end_headers()


class RawTunnelingAuthProxy(socketserver.ThreadingTCPServer):
    """Socket-level auth proxy relaying CONNECT synchronously (like the product)."""

    allow_reuse_address = True
    tunnel_target: tuple[str, int] | None = None
    received: list[tuple[str, str | None]] = []

    def start(self) -> int:
        threading.Thread(target=self.serve_forever, daemon=True).start()
        return self.server_address[1]


class _RawTunnelHandler(socketserver.StreamRequestHandler):
    rbufsize = 0  # type: ignore[assignment]
    wbufsize = 0  # type: ignore[assignment]

    def handle(self):
        request_line = self.rfile.readline().decode("latin-1").strip()
        if not request_line:
            return
        method, _target, _version = [*request_line.split(" "), "", ""][:3]
        auth: str | None = None
        while True:
            line = self.rfile.readline().decode("latin-1").strip()
            if not line:
                break
            if line.lower().startswith("proxy-authorization:"):
                auth = line.split(":", 1)[1].strip()
        RawTunnelingAuthProxy.received.append((method, auth))
        if auth != EXPECTED_AUTH:
            self.wfile.write(b"HTTP/1.1 407 Proxy Authentication Required\r\nProxy-Authenticate: Basic\r\n\r\n")
            return
        if method != "CONNECT":
            self.wfile.write(b"HTTP/1.1 501 Not Implemented\r\n\r\n")
            return
        target_addr = RawTunnelingAuthProxy.tunnel_target or ("127.0.0.1", 1)
        try:
            upstream = socket.create_connection(target_addr, timeout=5)
        except OSError:
            self.wfile.write(b"HTTP/1.1 502 Bad Gateway\r\n\r\n")
            return
        self.wfile.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
        try:
            import selectors

            sel = selectors.DefaultSelector()
            sel.register(self.connection, selectors.EVENT_READ, upstream)
            sel.register(upstream, selectors.EVENT_READ, self.connection)
            while True:
                events = sel.select(timeout=10)
                if not events:
                    return
                for key, _ in events:
                    data = key.fileobj.recv(65536)
                    if not data:
                        return
                    key.data.sendall(data)
        except OSError:
            return
        finally:
            upstream.close()


class EchoServer:
    """Trivial TCP echo server used as the 'origin' behind the tunnel."""

    def __init__(self) -> None:
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(5)
        self.port = self.sock.getsockname()[1]
        threading.Thread(target=self._accept_loop, daemon=True).start()

    def _accept_loop(self):
        while True:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            threading.Thread(target=self._echo, args=(conn,), daemon=True).start()

    @staticmethod
    def _echo(conn: socket.socket):
        try:
            while True:
                data = conn.recv(4096)
                if not data:
                    return
                conn.sendall(data)
        except OSError:
            return
        finally:
            conn.close()

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass


def _start_upstream() -> tuple[ThreadingHTTPServer, int]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), UpstreamProxy)
    server.daemon_threads = True
    import threading

    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, server.server_address[1]


def _raw_request(port: int, payload: bytes, timeout: float = 5.0) -> bytes:
    chunks: list[bytes] = []
    with socket.create_connection(("127.0.0.1", port), timeout=timeout) as sock:
        sock.sendall(payload)
        sock.settimeout(timeout)
        try:
            while True:
                data = sock.recv(4096)
                if not data:
                    break
                chunks.append(data)
        except TimeoutError:
            pass
    return b"".join(chunks)


def test_forwarder_injects_credentials_on_plain_http():
    UpstreamProxy.received.clear()
    upstream, upstream_port = _start_upstream()
    forwarder = AuthForwardProxy("127.0.0.1", upstream_port, USER, PWD)
    fwd_port = forwarder.start()
    try:
        response = _raw_request(
            fwd_port,
            b"GET http://example.test/ HTTP/1.1\r\nHost: example.test\r\nConnection: close\r\n\r\n",
        )
        assert b" 200 " in response.split(b"\r\n", 1)[0]
        assert b"UPSTREAM_OK" in response
        assert UpstreamProxy.received[-1][2] == EXPECTED_AUTH
    finally:
        forwarder.stop()
        upstream.shutdown()


def test_forwarder_injects_credentials_on_connect():
    UpstreamProxy.received.clear()
    upstream, upstream_port = _start_upstream()
    forwarder = AuthForwardProxy("127.0.0.1", upstream_port, USER, PWD)
    fwd_port = forwarder.start()
    try:
        response = _raw_request(
            fwd_port,
            b"CONNECT example.test:443 HTTP/1.1\r\nHost: example.test:443\r\n\r\n",
        )
        assert b" 200 " in response.split(b"\r\n", 1)[0]
        assert UpstreamProxy.received[-1][0] == "CONNECT"
        assert UpstreamProxy.received[-1][2] == EXPECTED_AUTH
    finally:
        forwarder.stop()
        upstream.shutdown()


def test_forwarder_relays_tunnel_data_end_to_end():
    """The forwarder must not just answer 200 — real tunnel bytes must flow."""
    echo = EchoServer()
    RawTunnelingAuthProxy.tunnel_target = ("127.0.0.1", echo.port)
    RawTunnelingAuthProxy.received.clear()
    tunnel_proxy = RawTunnelingAuthProxy(("127.0.0.1", 0), _RawTunnelHandler)
    proxy_port = tunnel_proxy.start()
    forwarder = AuthForwardProxy("127.0.0.1", proxy_port, USER, PWD)
    fwd_port = forwarder.start()
    try:
        with socket.create_connection(("127.0.0.1", fwd_port), timeout=5) as sock:
            sock.sendall(b"CONNECT echo.test:1234 HTTP/1.1\r\nHost: echo.test:1234\r\n\r\n")
            sock.settimeout(5)
            head = b""
            while b"\r\n\r\n" not in head:
                head += sock.recv(4096)
            assert b" 200 " in head.split(b"\r\n", 1)[0]
            # TLS-like payload must be echoed back through BOTH proxies.
            sock.sendall(b"PING-THROUGH-TUNNEL")
            echoed = b""
            while len(echoed) < len(b"PING-THROUGH-TUNNEL"):
                echoed += sock.recv(4096)
            assert echoed == b"PING-THROUGH-TUNNEL"
        assert RawTunnelingAuthProxy.received[-1] == ("CONNECT", EXPECTED_AUTH)
    finally:
        forwarder.stop()
        tunnel_proxy.shutdown()
        tunnel_proxy.server_close()
        echo.close()


def test_forwarder_without_credentials_upstream_rejects_407_passthrough():
    """Sanity: the stub really enforces auth (guards against false positives)."""
    UpstreamProxy.received.clear()
    upstream, upstream_port = _start_upstream()
    response = _raw_request(
        upstream_port,
        b"GET http://example.test/ HTTP/1.1\r\nHost: example.test\r\nConnection: close\r\n\r\n",
    )
    upstream.shutdown()
    assert b" 407 " in response.split(b"\r\n", 1)[0]


def test_forwarder_stop_is_clean():
    upstream, upstream_port = _start_upstream()
    forwarder = AuthForwardProxy("127.0.0.1", upstream_port, USER, PWD)
    port = forwarder.start()
    assert forwarder.alive is True
    forwarder.stop()
    upstream.shutdown()
    assert forwarder.alive is False
    try:
        socket.create_connection(("127.0.0.1", port), timeout=1.0).close()
        raise AssertionError("forwarder port must be closed after stop()")
    except OSError:
        pass
