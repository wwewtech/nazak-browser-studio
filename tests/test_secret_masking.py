"""Shared secret-masker contract tests (fix F6).

The CLI (mask_proxy_dict) and the API (_mask_proxy_for_api) must never drift
apart again: both delegate to nazak.core.secret_masking, and this suite pins
the exact masking contract for every documented proxy shape.
"""

from __future__ import annotations

from nazak.cli_cmds import common as cli_common
from nazak.core.secret_masking import mask_proxy_fields, mask_raw_proxy_string
from nazak.models.proxy import ProxyConfig


def test_url_form_password_masked_positionally_not_by_substring():
    """A password that occurs inside the username must not half-mask it."""
    out = mask_raw_proxy_string("http://pworker:pw@198.51.100.9:8080")
    assert out == "http://pworker:***@198.51.100.9:8080"
    # The username stays complete (an old substring-replace produced
    # "p***orker"), and the password survives nowhere as a standalone segment.
    assert "pworker" in out
    assert ":pw@" not in out
    assert ":***@" in out


def test_colon_form_masks_only_the_password():
    """host:port:user:pass — password hidden, username stays (as everywhere)."""
    out = mask_raw_proxy_string("1.2.3.4:8080:pxuser:pxDeepSecret123")
    assert out == "1.2.3.4:8080:pxuser:***"
    assert "pxDeepSecret123" not in out


def test_bare_host_port_and_scheme_left_alone():
    assert mask_raw_proxy_string("http://1.2.3.4:8080") == "http://1.2.3.4:8080"
    assert mask_raw_proxy_string("socks5://1.2.3.4:1080") == "socks5://1.2.3.4:1080"
    assert mask_raw_proxy_string("1.2.3.4:8080") == "1.2.3.4:8080"


def test_url_form_without_password_keeps_username():
    out = mask_raw_proxy_string("http://justuser@1.2.3.4:8080")
    assert out == "http://justuser@1.2.3.4:8080"


def test_fields_masks_password_raw_and_rotation():
    data = {
        "host": "1.2.3.4",
        "port": 8080,
        "username": "u",
        "password": "pw",
        "raw": "http://u:pw@1.2.3.4:8080",
        "rotation_url": "http://rotate.example/",
    }
    out = mask_proxy_fields(data)
    assert out["password"] == "***"
    assert out["raw"] == "http://u:***@1.2.3.4:8080"
    assert out["rotation_url"] == "***"
    assert out["host"] == "1.2.3.4" and out["username"] == "u"
    # The input dict is never mutated.
    assert data["password"] == "pw"


def test_cli_and_api_surfaces_share_one_contract():
    """Both surfaces must produce identical output for identical input."""
    payload = {
        "password": "pw",
        "raw": "http://pworker:pw@h:1",
        "rotation_url": "http://r",
        "host": "h",
    }
    cli_out = cli_common.mask_proxy_dict(payload)
    api_out = mask_proxy_fields(ProxyConfig(**payload).model_dump())
    # The API path starts from the full model dump; compare the overlapping
    # (masked-relevant) fields only — that is the contract the two surfaces
    # must never disagree on.
    for key in ("password", "raw", "rotation_url", "host"):
        assert cli_out[key] == api_out[key], f"surface drift on {key}: {cli_out[key]!r} != {api_out[key]!r}"
    assert cli_out["password"] == "***"
    assert cli_out["rotation_url"] == "***"
