"""
Unit Tests for Action Synchronizer and Window Tile Engine.
"""
import pytest
from unittest.mock import MagicMock
from nazak.core.synchronizer import SynchronizerSession, SynchronizerManager, tile_windows_win32

def test_synchronizer_session_init_and_state():
    session = SynchronizerSession(
        master_profile_id="master_1",
        worker_profile_ids=["master_1", "worker_a", "worker_b"],
        humanize_jitter=True
    )
    # Ensure master is filtered out from workers
    assert session.master_profile_id == "master_1"
    assert session.worker_profile_ids == ["worker_a", "worker_b"]
    assert session.humanize_jitter is True
    assert session.active is False

    d = session.to_dict()
    assert d["master_profile_id"] == "master_1"
    assert len(d["worker_profile_ids"]) == 2

def test_synchronizer_manager_lifecycle():
    mock_launcher = MagicMock()
    mock_launcher.profile_pids = {"master_1": 1001, "worker_a": 1002, "worker_b": 1003}
    mock_launcher.get_cdp_info.return_value = {"port": 9222, "ws_endpoint": "ws://..."}

    mgr = SynchronizerManager(mock_launcher)
    status = mgr.get_status()
    assert status["active"] is False

    session = mgr.start_session("master_1", ["worker_a", "worker_b"])
    assert session.active is True
    assert mgr.get_status()["active"] is True

    stopped = mgr.stop_session()
    assert stopped is not None
    assert stopped.active is False
    assert mgr.get_status()["active"] is False

def test_tile_windows_empty_handling():
    # Calling tile_windows with empty list returns False safely without crash
    res = tile_windows_win32([])
    assert res is False
