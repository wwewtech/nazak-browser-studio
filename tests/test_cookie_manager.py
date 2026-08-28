import json

import pytest

from nazak.core.cookie_manager import cookies_to_netscape, parse_any_cookies, parse_netscape_cookies


def test_parse_netscape_cookies():
    raw = """# Netscape HTTP Cookie File
.google.com\tTRUE\t/\tTRUE\t1750000000\tSID\tabc123xyz
.google.com\tTRUE\t/\tTRUE\t1750000000\tHSID\tdef456uvw
"""
    cookies = parse_netscape_cookies(raw)
    assert len(cookies) == 2
    assert cookies[0]["name"] == "SID"
    assert cookies[0]["value"] == "abc123xyz"
    assert cookies[0]["domain"] == ".google.com"
    assert cookies[0]["secure"] is True


def test_cookies_to_netscape():
    cookies = [
        {
            "name": "session_id",
            "value": "secret999",
            "domain": "example.com",
            "path": "/",
            "secure": True,
            "httpOnly": True,
            "expires": 1800000000,
        }
    ]
    netscape_str = cookies_to_netscape(cookies)
    assert "# Netscape HTTP Cookie File" in netscape_str
    assert "session_id\tsecret999" in netscape_str
    assert "1800000000" in netscape_str


def test_parse_any_cookies_json():
    json_data = json.dumps([{"name": "NID", "value": "511=test", "domain": ".google.com", "path": "/"}])
    parsed = parse_any_cookies(json_data)
    assert len(parsed) == 1
    assert parsed[0]["name"] == "NID"


def test_parse_any_cookies_empty_and_comments():
    raw = "# Just comments\n# Another line\n"
    parsed = parse_any_cookies(raw)
    assert len(parsed) == 0
