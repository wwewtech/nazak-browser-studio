"""
Nazak API realtime hub (P0 refactor).

WebSocket ConnectionManager + process-state broadcast, extracted verbatim
from nazak/api/server.py. The singleton ``ws_manager`` lives here; server.py
re-exports it so ``patch("nazak.api.server.profile_manager")``-style tests
and ``from nazak.api.server import ws_manager`` keep working.
"""

import asyncio
import logging
from typing import Any

from fastapi import WebSocket

from ..models.profile import ProfileStatus

logger = logging.getLogger(__name__)

# Hunt S-03: a per-client send ceiling. TCP backpressure on a wedged client
# (dead peer, half-open connection, stuck proxy) used to park the broadcast
# loop on ``await connection.send_text`` FOREVER — every subsequent broadcast
# coroutine queued behind it, and synchronous callers that await the broadcast
# (upload queue job steps, API routers) froze with it. One slow client must not
# throttle the event loop: the send is raced against a short timeout and a
# timed-out client is evicted (its next inbound packet surfaces the disconnect).
WS_SEND_TIMEOUT_SEC = 5.0


class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    @staticmethod
    async def _send_with_timeout(connection: WebSocket, payload: str) -> None:
        try:
            await asyncio.wait_for(connection.send_text(payload), timeout=WS_SEND_TIMEOUT_SEC)
        except asyncio.TimeoutError as exc:
            raise RuntimeError(f"ws send timed out after {WS_SEND_TIMEOUT_SEC}s (wedged client)") from exc

    async def broadcast(self, event_type: str, data: Any):
        import json as _json

        payload = _json.dumps({"event": event_type, "data": data})
        for connection in list(self.active_connections):
            try:
                await self._send_with_timeout(connection, payload)
            except Exception as exc:
                logger.debug("WS send failed, dropping connection: %s", exc)
                self.disconnect(connection)


ws_manager = ConnectionManager()

_server_loop: asyncio.AbstractEventLoop | None = None


def set_server_loop(loop: asyncio.AbstractEventLoop | None) -> None:
    global _server_loop
    _server_loop = loop


def get_server_loop() -> asyncio.AbstractEventLoop | None:
    return _server_loop


def on_process_state_change(profile_id: str, status: ProfileStatus):
    global _server_loop
    payload = {"profile_id": profile_id, "status": status.value}
    if _server_loop and _server_loop.is_running():
        try:
            asyncio.run_coroutine_threadsafe(
                ws_manager.broadcast("profile_status_change", payload),
                _server_loop,
            )
            return
        except Exception as exc:
            logger.debug("process-state broadcast failed: %s", exc)
            pass
    try:
        asyncio.get_running_loop()
        asyncio.create_task(ws_manager.broadcast("profile_status_change", payload))
    except RuntimeError:
        logger.debug("no running loop for profile_status_change %s", payload)
