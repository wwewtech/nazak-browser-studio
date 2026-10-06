"""
Regression guards for the XSS / HTML-injection fixes in the web dashboard.

Static source inspection only: these tests read ``nazak/web/app.js`` from disk
and assert that the escaping / URL scheme-allowlist fixes stay in place. No
network, no browser, no server.

Covered findings:
  1. The diagnostics modal interpolated the attacker-influenced public IP /
     country / city (third-party proxy-check response fetched over plain HTTP
     through the user's proxy) into ``innerHTML`` without escaping.
  2. Profile ids were interpolated straight into inline ``onclick`` /
     ``onchange`` (and ``id``) attributes without escaping.
  3. The autopost job table rendered ``<a href="${escapeHtml(j.video_url)}">``
     with no URL scheme allowlist, so a ``javascript:`` URL would survive.
"""

import re
from pathlib import Path

APP_JS_PATH = Path(__file__).resolve().parents[1] / "nazak" / "web" / "app.js"

# A ``${ ... }`` interpolation body containing no nested braces (the plain
# value-render form). Nested template literals are reached separately, because
# ``[^{}]`` cannot cross a brace.
_INTERPOLATION_RE = re.compile(r"\$\{([^{}]*)\}")

# ``onclick="..."`` / ``onchange="..."`` attribute values. The inline handlers
# in this file pass single-quoted JS strings, so a double quote cannot legally
# appear inside the captured attribute value.
_HANDLER_ATTR_RE = re.compile(r"""\bon(?:click|change)\s*=\s*"([^"]*)\"""")

# ``id="..."`` attribute values.
_ID_ATTR_RE = re.compile(r"""\bid\s*=\s*"([^"]*)\"""")

# A raw (unescaped) interpolation of the proxy-check geolocation fields, i.e.
# ``${health.ip}`` or ``${health.country || "N/A"}``, but NOT the ternary
# ``${health.ip ? "success" : "fail"}`` that only selects a class name.
_RAW_HEALTH_FIELD_RE = re.compile(r"\$\{\s*health\.(?:ip|country|city)\b(?!\s*\?)")


def _app_js() -> str:
    """Return the web dashboard source (read from disk, never from network)."""
    assert APP_JS_PATH.is_file(), f"web dashboard source missing: {APP_JS_PATH}"
    return APP_JS_PATH.read_text(encoding="utf-8")


def _region(start_marker: str, end_marker: str | None = None) -> str:
    """Return the source from ``start_marker`` up to (excluding) ``end_marker``."""
    src = _app_js()
    start = src.index(start_marker)
    end = src.index(end_marker, start) if end_marker else len(src)
    return src[start:end]


def test_diagnostics_modal_does_not_render_raw_ip_or_geo():
    """Finding A: the diagnostics modal must escape ip / country / city."""
    template = _region("function renderDiagModalContent", "function closeDiagModal")

    offenders = _RAW_HEALTH_FIELD_RE.findall(template)
    assert offenders == [], "diagnostics modal interpolates unescaped proxy-check values: " + repr(offenders)

    # Positively: each of the three fields goes through the shared helper.
    for call in ("escapeHtml(health.ip", "escapeHtml(health.country", "escapeHtml(health.city"):
        assert call in template, f"diagnostics modal is not escaping via {call}...)"


def test_profile_card_escapes_ip_and_geo():
    """Finding A: the profile-card renderer (also re-run by WS health events)."""
    card = _region("function renderProfiles", "function toggleDropdown")

    assert "escapeHtml(ipText)" in card
    assert "escapeHtml(geoText)" in card


def test_profile_ids_in_inline_handlers_are_escaped():
    """Finding B: every ``${p.id}`` inside an inline handler is escapeHtml()-wrapped."""
    src = _app_js()
    seen = 0
    offenders = []

    for attr in _HANDLER_ATTR_RE.finditer(src):
        for interp in _INTERPOLATION_RE.finditer(attr.group(1)):
            body = interp.group(1)
            if "p.id" not in body:
                continue
            seen += 1
            if "escapeHtml(" not in body:
                offenders.append(body)

    # Sanity check: the dashboard really does build inline handlers from p.id,
    # so a clean run above is not vacuous.
    assert seen >= 5, f"expected inline handlers interpolating p.id, found {seen}"
    assert offenders == [], f"unescaped profile id inside inline handler: {offenders!r}"


def test_profile_ids_in_id_attributes_are_escaped():
    """Finding B: ``id="card-${p.id}"`` / ``id="dropdown-${p.id}"`` are escaped too."""
    src = _app_js()
    seen = 0
    offenders = []

    for attr in _ID_ATTR_RE.finditer(src):
        for interp in _INTERPOLATION_RE.finditer(attr.group(1)):
            body = interp.group(1)
            if "p.id" not in body:
                continue
            seen += 1
            if "escapeHtml(" not in body:
                offenders.append(body)

    assert seen >= 2, f"expected id attributes interpolating p.id, found {seen}"
    assert offenders == [], f"unescaped profile id inside id attribute: {offenders!r}"


def test_video_url_href_requires_http_scheme():
    """Finding C: the video link only renders for http:// / https:// URLs."""
    src = _app_js()

    assert 'href="${escapeHtml(j.video_url)}"' not in src, (
        "video_url is still used as an href without a scheme allowlist"
    )

    fn = src[src.index("async function updateAutopostStatusView") :]

    # j.video_url must be routed through an explicit http(s) scheme allowlist
    # into a ``... : null`` variable before it may reach an href.
    guard = re.search(
        r"const\s+(\w+)\s*=\s*[^;]*j\.video_url[^;]*\^https\?:\\?/\\?/[^;]*\?[^;]*:\s*null\s*;",
        fn,
    )
    assert guard, "j.video_url is not routed through an http(s) scheme allowlist"

    safe_var = guard.group(1)
    assert f'href="${{escapeHtml({safe_var})}}"' in fn, f"href is not built from the allowlisted variable {safe_var!r}"
    # A rejected URL still renders the label text, just without a link.
    assert "Open ${platformName}" in fn
