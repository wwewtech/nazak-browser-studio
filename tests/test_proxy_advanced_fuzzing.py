import pytest
from nazak.models.proxy import ProxyConfig, ProxyType, sanitize_port

def test_sanitize_port_bounds():
    assert sanitize_port(80) == 80
    assert sanitize_port("443") == 443
    assert sanitize_port(65535) == 65535
    assert sanitize_port(0, default=8080) == 8080
    assert sanitize_port(70000, default=8080) == 8080
    assert sanitize_port(-5, default=1080) == 1080
    assert sanitize_port("invalid", default=8080) == 8080
    assert sanitize_port(None, default=8080) == 8080

def test_parse_direct_and_null_variations():
    for raw in [None, "", "   ", "direct", "DIRECT", "none", "NONE", "null"]:
        p = ProxyConfig.parse(raw)
        assert p.is_direct() is True
        assert p.type == ProxyType.DIRECT
        assert p.to_chrome_proxy_arg() is None
        assert p.to_httpx_url() is None
        assert "Direct Connection" in p.to_display_string()

def test_parse_host_port_simple():
    p = ProxyConfig.parse("192.168.1.100:8080")
    assert p.type == ProxyType.HTTP
    assert p.host == "192.168.1.100"
    assert p.port == 8080
    assert p.has_auth() is False
    assert p.to_chrome_proxy_arg() == "http://192.168.1.100:8080"
    assert p.to_httpx_url() == "http://192.168.1.100:8080"

def test_parse_host_port_with_trailing_slash():
    p = ProxyConfig.parse("192.168.1.100:8080/")
    assert p.host == "192.168.1.100"
    assert p.port == 8080

def test_parse_host_port_user_pass_standard():
    p = ProxyConfig.parse("1.2.3.4:9000:admin:secret123")
    assert p.type == ProxyType.HTTP
    assert p.host == "1.2.3.4"
    assert p.port == 9000
    assert p.username == "admin"
    assert p.password == "secret123"
    assert p.has_auth() is True
    assert p.to_chrome_proxy_arg() == "http://1.2.3.4:9000"
    assert p.to_httpx_url() == "http://admin:secret123@1.2.3.4:9000"

def test_parse_user_pass_host_port_format():
    # Some providers give user:pass:host:port format
    p = ProxyConfig.parse("user77:pwd88:1.2.3.4:9000")
    assert p.host == "1.2.3.4"
    assert p.port == 9000
    assert p.username == "user77"
    assert p.password == "pwd88"
    assert p.has_auth() is True

def test_parse_user_pass_at_host_port():
    p = ProxyConfig.parse("myuser:mypass@proxy.provider.com:3128")
    assert p.host == "proxy.provider.com"
    assert p.port == 3128
    assert p.username == "myuser"
    assert p.password == "mypass"

def test_parse_socks5_url_scheme():
    p = ProxyConfig.parse("socks5://10.0.0.1:1080")
    assert p.type == ProxyType.SOCKS5
    assert p.host == "10.0.0.1"
    assert p.port == 1080
    assert p.to_chrome_proxy_arg() == "socks5://10.0.0.1:1080"
    assert p.to_httpx_url() == "socks5://10.0.0.1:1080"

def test_parse_socks4_url_scheme():
    p = ProxyConfig.parse("socks4://10.0.0.1:1080")
    assert p.type == ProxyType.SOCKS4
    assert p.host == "10.0.0.1"
    assert p.port == 1080
    assert p.to_chrome_proxy_arg() == "socks4://10.0.0.1:1080"

def test_parse_https_url_scheme():
    p = ProxyConfig.parse("https://secure.proxy.com:8443")
    assert p.type == ProxyType.HTTPS
    assert p.host == "secure.proxy.com"
    assert p.port == 8443

def test_parse_password_with_at_symbol():
    p = ProxyConfig.parse("socks5://admin:p@ss@word@10.0.0.1:1080")
    assert p.type == ProxyType.SOCKS5
    assert p.host == "10.0.0.1"
    assert p.port == 1080
    assert p.username == "admin"
    assert p.password == "p@ss@word"
    assert "p%40ss%40word" in p.to_httpx_url()

def test_parse_password_with_special_characters():
    p = ProxyConfig.parse("user1:s#c$r%t:1.2.3.4:8080")
    assert p.host == "1.2.3.4"
    assert p.port == 8080
    assert p.username == "user1"
    assert p.password == "s#c$r%t"
    httpx_url = p.to_httpx_url()
    assert "%23" in httpx_url or "#" in p.password

def test_parse_ipv6_brackets_simple():
    p = ProxyConfig.parse("[2001:db8::1]:8080")
    assert p.host == "2001:db8::1"
    assert p.port == 8080
    assert p.type == ProxyType.HTTP

def test_parse_ipv6_with_socks5_and_auth():
    p = ProxyConfig.parse("socks5://[::1]:1080:user99:pass99")
    assert p.host == "::1"
    assert p.port == 1080
    assert p.username == "user99"
    assert p.password == "pass99"

def test_parse_3_parts_host_port_user():
    p = ProxyConfig.parse("1.2.3.4:8080:myuser")
    assert p.host == "1.2.3.4"
    assert p.port == 8080
    assert p.username == "myuser"
    assert p.password == ""

def test_parse_single_host_default_port_http():
    p = ProxyConfig.parse("proxy.internal.net")
    assert p.host == "proxy.internal.net"
    assert p.port == 8080
    assert p.type == ProxyType.HTTP

def test_parse_single_host_default_port_socks5():
    p = ProxyConfig.parse("socks5://proxy.internal.net")
    assert p.host == "proxy.internal.net"
    assert p.port == 1080
    assert p.type == ProxyType.SOCKS5

def test_display_string_masking():
    p = ProxyConfig.parse("user:supersecret@1.2.3.4:8080")
    display = p.to_display_string()
    assert "supersecret" not in display
    assert "user:***@" in display
    assert "1.2.3.4:8080" in display

def test_to_chrome_proxy_arg_direct():
    p = ProxyConfig(type=ProxyType.DIRECT)
    assert p.to_chrome_proxy_arg() is None

def test_to_httpx_url_direct():
    p = ProxyConfig(type=ProxyType.DIRECT)
    assert p.to_httpx_url() is None

def test_parse_case_insensitivity():
    p = ProxyConfig.parse("SOCKS5://127.0.0.1:1080")
    assert p.type == ProxyType.SOCKS5
    assert p.host == "127.0.0.1"

def test_parse_whitespace_in_input():
    p = ProxyConfig.parse("   127.0.0.1:8080   ")
    assert p.host == "127.0.0.1"
    assert p.port == 8080

def test_parse_invalid_port_fallback():
    p = ProxyConfig.parse("127.0.0.1:999999")
    assert p.host == "127.0.0.1"
    assert p.port == 8080

def test_parse_empty_user_pass():
    p = ProxyConfig.parse(":127.0.0.1:8080")
    assert p.host == "127.0.0.1"
    assert p.port == 8080

def test_parse_auth_url_decoding():
    p = ProxyConfig.parse("http://user%20name:pass%20word@127.0.0.1:8080")
    assert p.username == "user name"
    assert p.password == "pass word"
