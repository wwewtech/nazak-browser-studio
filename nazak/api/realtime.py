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


class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, event_type: str, data: Any):
        import json as _json

        payload = _json.dumps({"event": event_type, "data": data})
        for connection in list(self.active_connections):
            try:
                await connection.send_text(payload)
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
