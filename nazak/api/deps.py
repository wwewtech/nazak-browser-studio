"""
Nazak API shared dependencies / composition root (P0 refactor).

Singletons live in nazak.api.server (to preserve test patch targets); this
module provides lazy accessors so routers always see the *current* server
attributes (tests replace ``nazak.api.server.profile_manager`` per-test).
"""

from typing import Any


def _server():
    import nazak.api.server as srv

    return srv


def pm():
    return _server().profile_manager


def bl():
    return _server().browser_launcher


def uqm():
    return _server().upload_queue_mgr


def vu():
    return _server().video_uniquifier


def pmon():
    return _server().process_monitor


def sync_mgr():
    return _server().synchronizer_mgr


def scen_exec():
    return _server().scenario_executor


def wsm():
    from .realtime import ws_manager

    return ws_manager


def broadcast_coro(event: str, data: Any):
    return wsm().broadcast(event, data)
