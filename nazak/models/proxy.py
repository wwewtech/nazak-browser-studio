"""
Proxy data models, parsing, validation, and serialization.
Supports HTTP, HTTPS, SOCKS4, SOCKS5 with robust parsing and auth handling.
"""
from enum import Enum
import re
from typing import Optional, Any, List, Dict
from urllib.parse import urlparse, quote, unquote
from pydantic import BaseModel, Field

class ProxyType(str, Enum):
    DIRECT = "direct"
    HTTP = "http"
    HTTPS = "https"
    SOCKS4 = "socks4"
    SOCKS5 = "socks5"

def sanitize_port(port_val: Any, default: int = 8080) -> int:
    try:
        p = int(port_val)
        if 1 <= p <= 65535:
            return p
    except (ValueError, TypeError):
        pass
    return default

class ProxyConfig(BaseModel):
    """
    Structured proxy configuration supporting HTTP(S) and SOCKS4/5 with optional auth.
    """
    type: ProxyType = ProxyType.DIRECT
    host: Optional[str] = None
    port: Optional[int] = None
    username: Optional[str] = None
    password: Optional[str] = None
    rotation_url: Optional[str] = None
    raw: Optional[str] = None
    active: bool = True

    @classmethod
    def parse(cls, raw_str: Optional[str]) -> "ProxyConfig":
        """
        Parses proxy strings in all common industry formats:
        - direct / none / empty
        - host:port
        - host:port:user:pass
        - user:pass:host:port
        - user:pass@host:port
        - http://user:pass@host:port
        - socks5://user:pass@host:port
        - socks5://host:port:user:pass
        - host:port:user:pass:http://change-ip-url
        - host:port:user:pass|http://change-ip-url
        - [ipv6]:port
        """
        if not raw_str or raw_str.strip().lower() in ("direct", "none", "", "null"):
            return cls(type=ProxyType.DIRECT, raw=raw_str)

        text = raw_str.strip()
        rotation_url = None

        # Check for rotation URL delimiter (| or # or :http/https)
        if "|" in text and ("http://" in text or "https://" in text):
            p_part, r_part = text.split("|", 1)
            text = p_part.strip()
            rotation_url = r_part.strip()
        elif "#http" in text:
            p_part, r_part = text.split("#", 1)
            text = p_part.strip()
            rotation_url = r_part.strip()
        else:
            # Check for colon-separated rotation URL (e.g. host:port:u:p:http://...)
            # Find the last occurrence of http:// or https:// if it's preceded by a colon or space
            for proto in (":http://", ":https://"):
                if proto in text:
                    idx = text.rfind(proto)
                    rotation_url = text[idx + 1:].strip()
                    text = text[:idx].strip()
                    break

        text = text.rstrip("/").lstrip(":")
        scheme = None

        # Check for scheme prefix (http://, socks5://, etc)
        if "://" in text:
            parts = text.split("://", 1)
            scheme_part = parts[0].lower()
            if scheme_part in ("http", "https", "socks4", "socks5"):
                scheme = ProxyType(scheme_part)
            text = parts[1].rstrip("/")

        default_scheme = scheme or ProxyType.HTTP

        # Handle IPv6 brackets: [2001:db8::1]:8080 or [::1]:1080:user:pass
        if text.startswith("["):
            ipv6_match = re.match(r"^\[([a-fA-F0-9:]+)\]:(\d+)(?::([^:]+):([^:]+))?$", text)
            if ipv6_match:
                host = ipv6_match.group(1)
                port = sanitize_port(ipv6_match.group(2), 8080)
                user = ipv6_match.group(3)
                pwd = ipv6_match.group(4)
                return cls(type=default_scheme, host=host, port=port, username=user, password=pwd, rotation_url=rotation_url, raw=raw_str)

        # Case 1: user:pass@host:port
        if "@" in text:
            auth_part, net_part = text.rsplit("@", 1)
            u_parts = auth_part.split(":", 1)
            username = unquote(u_parts[0])
            password = unquote(u_parts[1]) if len(u_parts) > 1 else ""

            host_parts = net_part.split(":")
            host = host_parts[0]
            port = sanitize_port(host_parts[1] if len(host_parts) > 1 else None, 1080 if default_scheme == ProxyType.SOCKS5 else 8080)
            return cls(type=default_scheme, host=host, port=port, username=username, password=password, rotation_url=rotation_url, raw=raw_str)

        # Case 2: Multi-part colon separated (host:port, host:port:user:pass, user:pass:host:port, host:port:user)
        parts = text.split(":")
        if len(parts) == 4:
            # Check if format is user:pass:host:port or host:port:user:pass
            if parts[3].isdigit() and not parts[1].isdigit():
                username, password, host, port_str = parts
            else:
                host, port_str, username, password = parts
            port = sanitize_port(port_str, 8080)
            return cls(type=default_scheme, host=host, port=port, username=username, password=password, rotation_url=rotation_url, raw=raw_str)
        elif len(parts) == 3:
            # host:port:username (password empty)
            host, port_str, username = parts
            port = sanitize_port(port_str, 8080)
            return cls(type=default_scheme, host=host, port=port, username=username, password="", rotation_url=rotation_url, raw=raw_str)
        elif len(parts) == 2:
            host, port_str = parts
            port = sanitize_port(port_str, 8080)
            return cls(type=default_scheme, host=host, port=port, rotation_url=rotation_url, raw=raw_str)
        elif len(parts) == 1 and parts[0]:
            h = parts[0].strip()
            if h.lower() in ("direct", "none", "null", "false", "no", "local", "invalid") or ("." not in h and h.lower() != "localhost"):
                return cls(type=ProxyType.DIRECT, rotation_url=rotation_url, raw=raw_str)
            host = h
            port = 1080 if default_scheme == ProxyType.SOCKS5 else 8080
            return cls(type=default_scheme, host=host, port=port, rotation_url=rotation_url, raw=raw_str)

        return cls(type=ProxyType.DIRECT, rotation_url=rotation_url, raw=raw_str)

    def is_direct(self) -> bool:
        return self.type == ProxyType.DIRECT or not self.host or not self.port

    def has_auth(self) -> bool:
        return bool(self.username and self.password)

    def to_chrome_proxy_arg(self) -> Optional[str]:
        """
        Returns string for Chrome --proxy-server flag.
        Format: protocol://host:port
        """
        if self.is_direct():
            return None
        proto = "socks5" if self.type == ProxyType.SOCKS5 else ("socks4" if self.type == ProxyType.SOCKS4 else "http")
        return f"{proto}://{self.host}:{self.port}"

    def to_httpx_url(self) -> Optional[str]:
        """
        Returns connection URL for HTTPX / Requests client with URL-safe encoded credentials.
        """
        if self.is_direct():
            return None
        proto = self.type.value
        if self.has_auth():
            safe_user = quote(self.username or "", safe="")
            safe_pass = quote(self.password or "", safe="")
            return f"{proto}://{safe_user}:{safe_pass}@{self.host}:{self.port}"
        return f"{proto}://{self.host}:{self.port}"

    def to_display_string(self) -> str:
        if self.is_direct():
            return "Direct Connection (No Proxy)"
        auth_part = f"{self.username}:***@" if self.has_auth() else ""
        return f"{self.type.value}://{auth_part}{self.host}:{self.port}"
