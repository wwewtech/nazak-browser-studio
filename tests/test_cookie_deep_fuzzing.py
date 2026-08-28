import json

import pytest

from nazak.core.cookie_manager import cookies_to_netscape, parse_any_cookies, parse_netscape_cookies


def test_parse_netscape_standard_tabs():
    data = ".google.com\tTRUE\t/\tTRUE\t1754000000\tSID\tsid_value_12345"
    cookies = parse_netscape_cookies(data)
    assert len(cookies) == 1
    c = cookies[0]
    assert c["name"] == "SID"
    assert c["value"] == "sid_value_12345"
    assert c["domain"] == ".google.com"
    assert c["path"] == "/"
    assert c["expires"] == 1754000000
    assert c["secure"] is True


def test_parse_netscape_httponly_prefix():
    data = "#HttpOnly_.google.com\tTRUE\t/\tTRUE\t1754000000\t__Secure-3PSID\tsecret_cookie_val"
    cookies = parse_netscape_cookies(data)
    assert len(cookies) == 1
    c = cookies[0]
    assert c["name"] == "__Secure-3PSID"
    assert c["value"] == "secret_cookie_val"
    assert c["domain"] == ".google.com"
    assert c["httpOnly"] is True


def test_parse_netscape_space_separated_lines():
    data = "example.com   TRUE   /app   FALSE   1800000000   session_id   abcxyz"
    cookies = parse_netscape_cookies(data)
    assert len(cookies) == 1
    assert cookies[0]["name"] == "session_id"
    assert cookies[0]["value"] == "abcxyz"
    assert cookies[0]["domain"] == "example.com"
    assert cookies[0]["path"] == "/app"


def test_parse_netscape_float_expiration():
    data = "domain.com\tFALSE\t/\tFALSE\t1754000000.89\ttest_name\ttest_val"
    cookies = parse_netscape_cookies(data)
    assert len(cookies) == 1
    assert cookies[0]["expires"] == 1754000000


def test_parse_netscape_zero_and_invalid_exp():
    data = "domain.com\tFALSE\t/\tFALSE\t0\tc1\tv1\ndomain.com\tFALSE\t/\tFALSE\tinvalid\tc2\tv2"
    cookies = parse_netscape_cookies(data)
    assert len(cookies) == 2
    assert cookies[0]["expires"] == 0
    assert cookies[1]["expires"] == 0


def test_parse_netscape_ignores_comments():
    data = "# This is a comment\n# Another comment\n\n.domain.com\tTRUE\t/\tTRUE\t0\tname\tval"
    cookies = parse_netscape_cookies(data)
    assert len(cookies) == 1
    assert cookies[0]["name"] == "name"


def test_cookies_to_netscape_format():
    cookies = [
        {
            "name": "SID",
            "value": "val1",
            "domain": ".google.com",
            "path": "/",
            "expires": 1750000000,
            "secure": True,
            "httpOnly": True,
        },
        {
            "name": "NID",
            "value": "val2",
            "domain": "google.com",
            "path": "/search",
            "expires": 0,
            "secure": False,
            "httpOnly": False,
        },
    ]
    netscape_text = cookies_to_netscape(cookies)
    assert "# Netscape HTTP Cookie File" in netscape_text
    assert "#HttpOnly_.google.com" in netscape_text
    assert "val1" in netscape_text
    assert "val2" in netscape_text


def test_cookies_to_netscape_and_back_roundtrip():
    original = [
        {
            "name": "cookieA",
            "value": "valA",
            "domain": ".site.com",
            "path": "/",
            "expires": 1750000000,
            "secure": True,
            "httpOnly": True,
        }
    ]
    exported = cookies_to_netscape(original)
    reparsed = parse_netscape_cookies(exported)
    assert len(reparsed) == 1
    assert reparsed[0]["name"] == "cookieA"
    assert reparsed[0]["value"] == "valA"
    assert reparsed[0]["domain"] == ".site.com"
    assert reparsed[0]["httpOnly"] is True


def test_parse_any_cookies_json_array():
    json_data = json.dumps(
        [
            {
                "name": "token",
                "value": "xyz123",
                "domain": "api.test.com",
                "path": "/",
                "expirationDate": 1750000000.5,
                "secure": True,
                "httpOnly": False,
            }
        ]
    )
    cookies = parse_any_cookies(json_data)
    assert len(cookies) == 1
    assert cookies[0]["name"] == "token"
    assert cookies[0]["value"] == "xyz123"
    assert cookies[0]["expires"] == 1750000000


def test_parse_any_cookies_single_json_dict():
    json_data = json.dumps({"name": "single_cookie", "value": "single_val", "domain": "site.com"})
    cookies = parse_any_cookies(json_data)
    assert len(cookies) == 1
    assert cookies[0]["name"] == "single_cookie"


def test_parse_any_cookies_empty_input():
    assert parse_any_cookies("") == []
    assert parse_any_cookies("   ") == []
    assert parse_any_cookies(None) == []


def test_parse_any_cookies_malformed_json_fallback_to_netscape():
    malformed = ".google.com\tTRUE\t/\tTRUE\t0\tSID\tfallback_val"
    cookies = parse_any_cookies(malformed)
    assert len(cookies) == 1
    assert cookies[0]["value"] == "fallback_val"


def test_parse_any_cookies_ignores_invalid_dict_items():
    json_data = json.dumps([{"no_name": "val"}, {"name": "valid", "value": "123"}])
    cookies = parse_any_cookies(json_data)
    assert len(cookies) == 1
    assert cookies[0]["name"] == "valid"


def test_parse_any_cookies_normalizes_string_values():
    json_data = json.dumps([{"name": "num_val", "value": 12345, "domain": "test.com"}])
    cookies = parse_any_cookies(json_data)
    assert len(cookies) == 1
    assert cookies[0]["value"] == "12345"


def test_parse_netscape_with_equals_in_cookie_value():
    data = "domain.com\tFALSE\t/\tFALSE\t0\tauth_token\tpart1=abc&part2=xyz=="
    cookies = parse_netscape_cookies(data)
    assert len(cookies) == 1
    assert cookies[0]["value"] == "part1=abc&part2=xyz=="


def test_parse_netscape_with_spaces_in_cookie_value():
    data = "domain.com\tFALSE\t/\tFALSE\t0\tuser_pref\tmode=dark lang=ru"
    cookies = parse_netscape_cookies(data)
    assert len(cookies) == 1
    assert cookies[0]["value"] == "mode=dark lang=ru"


def test_cookies_to_netscape_skips_non_dicts():
    result = cookies_to_netscape(["invalid_string", 123, {"name": "ok", "value": "1"}])
    assert "ok\t1" in result or "ok" in result


def test_parse_netscape_multiple_lines():
    data = "\n".join([f"domain{i}.com\tFALSE\t/\tFALSE\t0\tc{i}\tv{i}" for i in range(10)])
    cookies = parse_netscape_cookies(data)
    assert len(cookies) == 10


def test_parse_netscape_short_lines_ignored():
    data = "too\tshort\tline\nvalid.com\tFALSE\t/\tFALSE\t0\tname\tval"
    cookies = parse_netscape_cookies(data)
    assert len(cookies) == 1
    assert cookies[0]["name"] == "name"


def test_parse_any_cookies_boolean_conversions():
    json_data = json.dumps([{"name": "c1", "value": "v1", "secure": "true", "httpOnly": 1}])
    cookies = parse_any_cookies(json_data)
    assert len(cookies) == 1
    assert cookies[0]["secure"] is True
    assert cookies[0]["httpOnly"] is True
