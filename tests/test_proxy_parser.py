import pytest
from nazak.models.proxy import ProxyConfig, ProxyType

def test_parse_direct():
    p1 = ProxyConfig.parse("direct")
    assert p1.is_direct()
    assert p1.type == ProxyType.DIRECT

    p2 = ProxyConfig.parse("")
    assert p2.is_direct()

    p3 = ProxyConfig.parse(None)
    assert p3.is_direct()

def test_parse_host_port():
    p = ProxyConfig.parse("1.2.3.4:8080")
    assert p.type == ProxyType.HTTP
    assert p.host == "1.2.3.4"
    assert p.port == 8080
    assert not p.has_auth()
    assert p.to_chrome_proxy_arg() == "http://1.2.3.4:8080"
    assert p.to_httpx_url() == "http://1.2.3.4:8080"

def test_parse_host_port_user_pass():
    p = ProxyConfig.parse("1.2.3.4:8080:myuser:mypass")
    assert p.type == ProxyType.HTTP
    assert p.host == "1.2.3.4"
    assert p.port == 8080
    assert p.username == "myuser"
    assert p.password == "mypass"
    assert p.has_auth()
    assert p.to_chrome_proxy_arg() == "http://1.2.3.4:8080"
    assert p.to_httpx_url() == "http://myuser:mypass@1.2.3.4:8080"

def test_parse_socks5_url():
    p = ProxyConfig.parse("socks5://admin:secret123@192.168.1.100:1080")
    assert p.type == ProxyType.SOCKS5
    assert p.host == "192.168.1.100"
    assert p.port == 1080
    assert p.username == "admin"
    assert p.password == "secret123"
    assert p.to_chrome_proxy_arg() == "socks5://192.168.1.100:1080"
    assert p.to_httpx_url() == "socks5://admin:secret123@192.168.1.100:1080"

def test_parse_http_url():
    p = ProxyConfig.parse("http://user:pass@proxy.example.com:3128")
    assert p.type == ProxyType.HTTP
    assert p.host == "proxy.example.com"
    assert p.port == 3128
    assert p.username == "user"
    assert p.password == "pass"
