"""Round-3b: строгий CSP для дашборда и целостность делегирования действий.

Статические проверки (без браузера): в разметке не должно остаться inline
обработчиков и других конструкций, которые требуют `unsafe-inline` в
`script-src`; каждое `data-action` обязано иметь обработчик в реестре и наоборот.

Живая проверка в реальном Chromium — в `tests/live/test_dashboard_ui_smoke_live.py`.
"""

from __future__ import annotations

import re
from pathlib import Path

from nazak.api.server import CSP_POLICY

WEB_DIR = Path(__file__).resolve().parents[1] / "nazak" / "web"
INDEX_HTML = WEB_DIR / "index.html"
APP_JS = WEB_DIR / "app.js"
STYLES_CSS = WEB_DIR / "styles.css"

# Любой inline-обработчик события: onclick="...", onerror='...' и т.д.
# Требуем кавычку после '=', чтобы комментарии вида `on*= атрибут` не считались
# разметкой (реальные HTML-обработчики всегда в кавычках).
_INLINE_HANDLER_RE = re.compile(r"\son[a-z]+\s*=\s*[\"']", re.IGNORECASE)
_DATA_ACTION_RE = re.compile(r'data-action="([a-z-]+)"')
_REGISTRY_KEY_RE = re.compile(r'^\s{2}"([a-z-]+)":', re.MULTILINE)


def _web_files() -> dict[str, str]:
    assert INDEX_HTML.is_file() and APP_JS.is_file(), "web dashboard assets missing"
    return {
        "index.html": INDEX_HTML.read_text(encoding="utf-8"),
        "app.js": APP_JS.read_text(encoding="utf-8"),
    }


# --------------------------------------------------------------------------- CSP
def test_script_src_is_strict_without_unsafe_inline():
    """Скрипты — только 'self': иначе CSP не защищает от XSS (проверено в браузере)."""
    script_src = next(part.strip() for part in CSP_POLICY.split(";") if part.strip().startswith("script-src"))
    assert script_src == "script-src 'self'", script_src
    assert "unsafe-inline" not in script_src
    assert "unsafe-eval" not in CSP_POLICY
    assert "object-src 'none'" in CSP_POLICY
    assert "base-uri 'none'" in CSP_POLICY
    assert "frame-ancestors 'none'" in CSP_POLICY
    assert "form-action 'self'" in CSP_POLICY


def test_style_src_unsafe_inline_is_the_only_documented_remainder():
    """Остаток зафиксирован явно: inline style= ещё есть, но это не исполнение кода."""
    style_src = next(part.strip() for part in CSP_POLICY.split(";") if part.strip().startswith("style-src"))
    assert style_src == "style-src 'self' 'unsafe-inline'", style_src
    # ни один другой ресурс не разрешает inline
    for directive in ("default-src", "img-src", "font-src", "connect-src", "object-src"):
        part = next(p.strip() for p in CSP_POLICY.split(";") if p.strip().startswith(directive))
        assert "unsafe" not in part, part


# --------------------------------------------------------------------------- разметка
def test_no_inline_event_handlers_anywhere():
    """58 обработчиков on* переведены на data-action (иначе CSP был бы нестрогим)."""
    for name, text in _web_files().items():
        offenders = [
            f"{name}:{i}: {line.strip()[:90]}"
            for i, line in enumerate(text.splitlines(), 1)
            if _INLINE_HANDLER_RE.search(line)
        ]
        assert offenders == [], f"inline event handlers found: {offenders}"


def test_no_inline_script_blocks_and_no_js_urls():
    """Строгий script-src 'self' требует внешнего файла и запрещает javascript:."""
    for name, text in _web_files().items():
        assert "<script" not in text or 'src="/static/app.js"' in text, name
        assert not re.search(r"<script(?![^>]*\bsrc=)", text), f"inline <script> block in {name}"
        assert "javascript:" not in text, f"javascript: URL in {name}"
        assert not re.search(r"\beval\s*\(", text), f"eval() in {name}"
        assert "new Function" not in text, f"new Function in {name}"


def test_index_html_loads_only_the_local_bundle():
    html = _web_files()["index.html"]
    scripts = re.findall(r"<script[^>]*>", html)
    assert scripts == ['<script src="/static/app.js">'], scripts
    assert html.count("/static/app.js") == 1


# --------------------------------------------------------------------------- делегирование
def test_every_data_action_has_a_handler_and_vice_versa():
    files = _web_files()
    actions = set()
    for text in files.values():
        actions.update(_DATA_ACTION_RE.findall(text))
    registry = set(_REGISTRY_KEY_RE.findall(files["app.js"]))

    assert actions, "no data-action attributes found — delegation was removed?"
    assert len(actions) >= 40, f"expected the full action surface, found {len(actions)}"
    assert actions - registry == set(), f"data-action without handler: {sorted(actions - registry)}"
    assert registry - actions == set(), f"handler never referenced: {sorted(registry - actions)}"


def test_delegation_listens_to_click_change_and_input():
    js = _web_files()["app.js"]
    for event in ("click", "change", "input"):
        assert f'document.addEventListener("{event}", _dispatchDelegatedAction)' in js, event
    assert "function _dispatchDelegatedAction(" in js
    assert "function _delegatedParams(" in js


def test_delegated_params_come_from_data_attributes_only():
    """Параметры читаются из data-*: значения в других атрибутах не подставляются."""
    js = _web_files()["app.js"]
    body = js[js.index("function _delegatedParams(") : js.index("function _dispatchDelegatedAction(")]
    assert 'attr.name.startsWith("data-")' in body
    assert 'attr.name === "data-action"' in body
    assert "innerHTML" not in body and "eval" not in body


def test_delegation_reports_unknown_actions_without_executing_them():
    js = _web_files()["app.js"]
    body = js[js.index("function _dispatchDelegatedAction(") : js.index("const DELEGATED_ACTIONS")]
    assert 'el.getAttribute("data-action")' in body
    assert "if (!handler)" in body
    assert "console.warn" in body


def test_handlers_are_declared_after_the_functions_they_call():
    """Реестр стоит в конце файла: все function-декларации уже подняты."""
    js = _web_files()["app.js"]
    registry_at = js.index("const DELEGATED_ACTIONS")
    for fn in ("openAutopostModal", "launchProfile", "deleteProfile", "startAutopostBatch"):
        assert js.index(f"function {fn}(") < registry_at, fn


def test_styles_css_still_has_no_remote_assets():
    css = STYLES_CSS.read_text(encoding="utf-8")
    assert "@import" not in css
    assert not re.search(r"url\(\s*['\"]?https?://", css)
