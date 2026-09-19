"""Security regression tests for the OAuth callback flow (state/CSRF, isolation, XSS)."""

import threading
import time
import urllib.error
import urllib.request
from urllib.parse import quote

from nazak.core.account_provisioner import (
    AccountProvisioner,
    OAuthCallbackReceiver,
    generate_oauth_state,
)


def _hit(port: int, path: str, results: dict):
    # Bypass any system-wide proxy (dev machines often run local proxies on 127.0.0.1
    # which would otherwise intercept loopback calls and stall the callback).
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(f"http://127.0.0.1:{port}{path}", timeout=3) as resp:
            results["resp"] = (resp.status, resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        results["resp"] = (e.code, e.read().decode("utf-8"))
    except Exception as e:  # pragma: no cover - diagnostics only
        results["transport_err"] = repr(e)


def _run_receiver(receiver: OAuthCallbackReceiver, path: str, wait_timeout: float = 5.0) -> dict:
    results: dict = {}
    receiver.start()
    thread = threading.Thread(target=_hit, args=(receiver.bound_port, path, results))
    thread.start()
    deadline = time.time() + wait_timeout
    while time.time() < deadline:
        if receiver.poll():
            break
    thread.join(timeout=5)
    receiver.close()
    return results


def test_generate_oauth_state_is_unique_and_strong():
    states = {generate_oauth_state() for _ in range(50)}
    assert len(states) == 50
    for s in states:
        assert len(s) >= 32


def test_build_oauth_auth_url_includes_state():
    prov = AccountProvisioner(None, None)
    state = generate_oauth_state()
    url = prov.build_oauth_auth_url(client_id="cid", state=state)
    assert f"state={state}" in url


def test_build_oauth_auth_url_without_state_stays_clean():
    prov = AccountProvisioner(None, None)
    url = prov.build_oauth_auth_url(client_id="cid")
    assert "state=" not in url


def test_callback_accepts_code_with_matching_state():
    receiver = OAuthCallbackReceiver(port=0, expected_state="st_ok")
    _run_receiver(receiver, "/?code=GOODCODE&state=st_ok")
    assert receiver.auth_code == "GOODCODE"
    assert receiver.error is None


def test_callback_rejects_code_with_wrong_state():
    receiver = OAuthCallbackReceiver(port=0, expected_state="st_real")
    results = _run_receiver(receiver, "/?code=EVILCODE&state=st_fake")
    assert receiver.auth_code is None
    status, _body = results["resp"]
    assert status == 400


def test_callback_without_state_keeps_legacy_acceptance():
    receiver = OAuthCallbackReceiver(port=0, require_state=False)
    _run_receiver(receiver, "/?code=LEGACYCODE")
    assert receiver.auth_code == "LEGACYCODE"


def test_parallel_receivers_do_not_share_codes():
    r1 = OAuthCallbackReceiver(port=0, expected_state="s1")
    r2 = OAuthCallbackReceiver(port=0, expected_state="s2")
    r1.start()
    r2.start()
    res1: dict = {}
    res2: dict = {}
    t1 = threading.Thread(target=_hit, args=(r1.bound_port, "/?code=CODE1&state=s1", res1))
    t2 = threading.Thread(target=_hit, args=(r2.bound_port, "/?code=CODE2&state=s2", res2))
    t1.start()
    t2.start()
    deadline = time.time() + 5
    while time.time() < deadline and not (r1.auth_code and r2.auth_code):
        r1.poll()
        r2.poll()
    t1.join(timeout=5)
    t2.join(timeout=5)
    r1.close()
    r2.close()
    assert r1.auth_code == "CODE1"
    assert r2.auth_code == "CODE2"


def test_error_page_escapes_html():
    receiver = OAuthCallbackReceiver(port=0, require_state=False)
    encoded_error = quote("<script>alert(1)</script>")
    results = _run_receiver(receiver, f"/?error={encoded_error}")
    assert receiver.error is not None
    status, body = results["resp"]
    assert status == 400
    assert "<script>alert(1)</script>" not in body
    assert "&lt;script&gt;" in body