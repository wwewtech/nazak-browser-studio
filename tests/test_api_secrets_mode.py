"""Phase 3 API: /api/security/secrets-mode endpoints + notes masking."""

import json

import pytest
from fastapi.testclient import TestClient

from nazak.api.server import app
from nazak.core import secrets_store as ss


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def _plain_mode():
    ss.set_current_mode("plain")
    yield
    ss.set_current_mode("plain")


def test_get_secrets_mode(client):
    r = client.get("/api/security/secrets-mode")
    assert r.status_code == 200
    data = r.json()
    assert data["mode"] in ("plain", "dpapi", "passphrase")
    assert set(data["available_modes"]) == {"plain", "dpapi", "passphrase"}


def test_post_secrets_mode_switch_and_reject(client):
    r = client.post("/api/security/secrets-mode", json={"mode": "passphrase", "passphrase": "abc"})
    assert r.status_code == 200
    assert r.json()["mode"] == "passphrase"
    r = client.post("/api/security/secrets-mode", json={"mode": "rot13"})
    assert r.status_code == 400


def test_profile_notes_masked_in_api(client, tmp_path):
    from nazak.core.profile_manager import ProfileManager
    from nazak.models.profile import BrowserProfile, GoogleSettings

    # Encrypt a note directly into the manager's in-memory store
    notes = json.dumps(ss.encrypt_notes({"account_password": "SuperSecret123"}, mode="passphrase", passphrase="k"))
    prof = BrowserProfile(name="sec_test", google=GoogleSettings(notes=notes))
    created = app_module_profile_manager().create_profile(prof)
    try:
        # The passphrase lives only in memory; set it as the user would
        ss.set_current_mode("passphrase", passphrase="k")
        r = client.get(f"/api/profiles/{created.id}")
        assert r.status_code == 200
        body = r.json()
        api_notes = json.loads(body["google"]["notes"])
        assert "SuperSecret123" not in json.dumps(body)
        assert api_notes["account_password"] == "Sup...t123"

        # And the list endpoint too
        r = client.get("/api/profiles")
        assert "SuperSecret123" not in r.text
    finally:
        app_module_profile_manager().delete_profile(created.id, delete_data=True)


def app_module_profile_manager():
    from nazak.api import server

    return server.profile_manager
