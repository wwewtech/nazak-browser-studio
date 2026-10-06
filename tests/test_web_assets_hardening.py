"""Regression guards for web-dashboard asset / output hardening.

Pure static source inspection: the tests read the dashboard assets from disk
with ``pathlib`` and never start a server, a browser, or touch the network.

Covered findings:
  1. The diagnostics modal error path interpolated ``e.message`` into
     ``innerHTML`` without escaping (unlike every other dynamic value in that
     file, which goes through ``escapeHtml``).
  2. The autopost job video link rendered ``target="_blank"`` without
     ``rel="noopener noreferrer"``, so the opened third-party page got a
     ``window.opener`` handle back into the dashboard.
  3. ``index.html`` pulled Inter / JetBrains Mono from Google-hosted webfonts
     (``fonts.googleapis.com`` / ``fonts.gstatic.com``). A local-only,
     stealth-oriented dashboard must not phone Google on every load and must
     render correctly offline, so those links are gone and the CSS font stacks
     are explicit system stacks.
"""

from __future__ import annotations

import re
from pathlib import Path

WEB_DIR = Path(__file__).resolve().parents[1] / "nazak" / "web"
INDEX_HTML_PATH = WEB_DIR / "index.html"
STYLES_CSS_PATH = WEB_DIR / "styles.css"
APP_JS_PATH = WEB_DIR / "app.js"

# ``https://host``, ``http://host`` or protocol-relative ``//host``. A fragment
# (``#x``) or a relative path (``/static/...``, ``styles.css``) does not match.
_EXTERNAL_URL_RE = re.compile(r"^\s*(?:https?:)?//", re.IGNORECASE)

# ``src="..."`` / ``href='...'`` attribute values.
_ASSET_ATTR_RE = re.compile(r"""\b(?:src|href)\s*=\s*["']([^"']*)["']""", re.IGNORECASE)

# ``url(...)`` / ``url('...')`` / ``url("...")`` in inline styles or CSS.
_CSS_URL_RE = re.compile(r"""url\(\s*['"]?([^'")]*)['"]?\s*\)""", re.IGNORECASE)

# Any assignment into ``innerHTML`` (the templates that feed ``innerHTML`` in
# app.js are single-line assignments in this codebase).
_INNERHTML_ASSIGN_RE = re.compile(r"\.innerHTML\s*=", re.IGNORECASE)

# The ``escapeHtml`` implementation body, so its escaping semantics can be
# pinned without executing the (browser-only) JavaScript.
_ESCAPE_HTML_RE = re.compile(r"function escapeHtml\([^)]*\)\s*\{(.*?)\n\}", re.DOTALL)

# A quoted ``Inter`` font family (the Google-hosted face this project removed);
# a plain substring search would also hit ``pointer`` / ``interactive``.
_GOOGLE_FONT_RE = re.compile(r"""['"]Inter['"]""")


def _web_file(path: Path) -> str:
    """Return a dashboard asset read from disk (never from the network)."""
    assert path.is_file(), f"web dashboard asset missing: {path}"
    return path.read_text(encoding="utf-8")


def _font_stack(css: str, variable: str) -> str:
    match = re.search(rf"--{re.escape(variable)}\s*:\s*([^;]+);", css)
    assert match, f"styles.css does not declare --{variable}"
    return match.group(1).strip()


def test_index_html_loads_no_remote_assets() -> None:
    """index.html must not reference Google-hosted fonts or any remote asset."""
    html = _web_file(INDEX_HTML_PATH)

    for host in ("fonts.googleapis.com", "fonts.gstatic.com"):
        assert host not in html, f"index.html still references remote font host {host}"

    for match in _ASSET_ATTR_RE.finditer(html):
        value = match.group(1).strip()
        assert not _EXTERNAL_URL_RE.match(value), f"index.html asset attribute points at an external URL: {value}"

    for match in _CSS_URL_RE.finditer(html):
        value = match.group(1).strip()
        assert not _EXTERNAL_URL_RE.match(value), f"index.html url() points at an external asset: {value}"


def test_styles_css_has_no_remote_imports() -> None:
    """styles.css must not @import or url()-load anything from an external host."""
    css = _web_file(STYLES_CSS_PATH)

    assert "@import" not in css, "styles.css must not @import a remote stylesheet"

    for match in _CSS_URL_RE.finditer(css):
        value = match.group(1).strip()
        assert not _EXTERNAL_URL_RE.match(value), f"styles.css url() points at an external asset: {value}"


def test_styles_css_font_stacks_are_system_only() -> None:
    """The font stacks must resolve locally, without the Google-hosted Inter face."""
    css = _web_file(STYLES_CSS_PATH)

    assert not _GOOGLE_FONT_RE.search(css), "styles.css still requests the Google-hosted 'Inter' family"

    sans = _font_stack(css, "font-sans")
    mono = _font_stack(css, "font-mono")
    assert "sans-serif" in sans, f"--font-sans needs a generic fallback: {sans}"
    assert "monospace" in mono, f"--font-mono needs a generic fallback: {mono}"


def test_diag_error_path_escapes_exception_message() -> None:
    """The diagnostics error path must HTML-escape ``e.message``."""
    js = _web_file(APP_JS_PATH)

    diag_lines = [line for line in js.splitlines() if "diag-modal-body" in line and _INNERHTML_ASSIGN_RE.search(line)]
    assert diag_lines, "diagnostics modal error path not found in app.js"
    assert any("escapeHtml(e.message)" in line for line in diag_lines), (
        "the diagnostics error path must render escapeHtml(e.message)"
    )


def test_no_raw_exception_message_in_innerhtml() -> None:
    """No ``innerHTML`` template may interpolate a raw ``${e.message}``."""
    js = _web_file(APP_JS_PATH)

    for line in js.splitlines():
        if _INNERHTML_ASSIGN_RE.search(line):
            assert "${e.message}" not in line, f"raw ${{e.message}} interpolated into innerHTML: {line.strip()}"


def test_video_link_is_rel_hardened() -> None:
    """The autopost video link opens a third-party page and needs rel=noopener."""
    js = _web_file(APP_JS_PATH)

    link_lines = [
        line for line in js.splitlines() if "safeVideoUrl" in line and 'target="_blank"' in line and "<a href=" in line
    ]
    assert link_lines, "autopost video link line not found in app.js"
    for line in link_lines:
        assert 'rel="noopener noreferrer"' in line, f"video link missing rel hardening: {line.strip()}"


def test_escape_html_semantics_unchanged() -> None:
    """``escapeHtml`` must keep escaping &, <, >, " and '."""
    js = _web_file(APP_JS_PATH)

    match = _ESCAPE_HTML_RE.search(js)
    assert match, "escapeHtml implementation not found in app.js"
    body = match.group(1)
    for entity in ("&amp;", "&lt;", "&gt;", "&quot;", "&#039;"):
        assert entity in body, f"escapeHtml no longer emits {entity}"
