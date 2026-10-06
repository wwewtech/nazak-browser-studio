"""Source-level regression tests for the GUI-dialog and dev-tool hardening pass.

`PyQt6` / `qfluentwidgets` cannot be imported in this environment, so the GUI
dialogs are verified by reading their source and asserting on the exact code
that used to ignore return values / skip confirmation.  `nazak.core.browser_launcher`
only needs `psutil` and therefore is exercised for real.
"""

import re
import socket
from pathlib import Path

from nazak.core.browser_launcher import get_free_port

REPO_ROOT = Path(__file__).resolve().parents[1]
COOKIE_DIALOG = REPO_ROOT / "nazak" / "gui" / "dialogs" / "cookie_dialog.py"
BATCH_COOKIE_DIALOG = REPO_ROOT / "nazak" / "gui" / "dialogs" / "batch_cookie_dialog.py"
MASS_GENERATE_DIALOG = REPO_ROOT / "nazak" / "gui" / "dialogs" / "mass_generate_dialog.py"
WORKERS = REPO_ROOT / "nazak" / "gui" / "workers.py"
BRAND_ASSETS = REPO_ROOT / "nazak" / "tools" / "generate_brand_assets.py"


def _read(path: Path) -> str:
    assert path.is_file(), f"missing source file: {path}"
    return path.read_text(encoding="utf-8")


def _method_source(source: str, name: str) -> str:
    """Return the source of ``def <name>(`` up to the next same-indent method."""
    marker = f"    def {name}("
    start = source.index(marker)
    rest = source[start + len(marker) :]
    nxt = re.search(r"\n    def ", rest)
    return rest if nxt is None else rest[: nxt.start()]


def _class_source(source: str, name: str) -> str:
    """Return the source of ``class <name>`` up to the next top-level class."""
    marker = f"class {name}"
    start = source.index(marker)
    rest = source[start + len(marker) :]
    nxt = re.search(r"\nclass ", rest)
    return rest if nxt is None else rest[: nxt.start()]


# --------------------------------------------------------------------------- get_free_port
def test_get_free_port_returns_distinct_bindable_ports():
    """`get_free_port` must hand out unique, simultaneously bindable ports."""
    ports: list[int] = []
    for _ in range(50):
        port = get_free_port()
        assert isinstance(port, int)
        if port not in ports:
            ports.append(port)
        if len(ports) == 3:
            break
    assert len(ports) == 3, f"get_free_port kept handing out duplicate ports: {ports}"

    sockets = []
    try:
        for port in ports:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.bind(("127.0.0.1", port))
            sock.listen(1)
            sockets.append(sock)
        assert len({sock.getsockname()[1] for sock in sockets}) == 3
    finally:
        for sock in sockets:
            sock.close()


# --------------------------------------------------------------------------- cookie_dialog
def test_cookie_dialog_clear_cache_asks_for_confirmation_and_checks_result():
    src = _read(COOKIE_DIALOG)
    body = _method_source(src, "on_clear_cache")

    assert "QMessageBox.question" in body, "on_clear_cache must ask for confirmation before deleting caches"
    assert "QMessageBox" in src.split("class ")[0], "QMessageBox must be imported from PyQt6.QtWidgets"
    assert "if not self.profile_manager.clear_profile_cache(self.profile.id)" in body, (
        "clear_profile_cache's boolean result must be captured and honoured"
    )
    assert "InfoBar.error" in body or "InfoBar.warning" in body, "a failed clear must report an error/warning"
    # the pre-fix statement that ignored the return value must be gone
    assert "\n        self.profile_manager.clear_profile_cache(self.profile.id)\n" not in src


def test_cookie_dialog_reports_save_profile_cookies_failure():
    src = _read(COOKIE_DIALOG)
    body = _method_source(src, "on_import_cookies")

    assert "if not self.profile_manager.save_profile_cookies(self.profile.id, cookies)" in body, (
        "save_profile_cookies' boolean result must be captured and honoured"
    )
    assert "InfoBar.error" in body or "InfoBar.warning" in body, "a failed save must report an error/warning"
    # the pre-fix statement that ignored the return value must be gone
    assert "\n        self.profile_manager.save_profile_cookies(self.profile.id, cookies)\n" not in src


# --------------------------------------------------------------------------- batch_cookie_dialog
def test_batch_cookie_dialog_summary_includes_failed():
    src = _read(BATCH_COOKIE_DIALOG)
    body = _method_source(src, "on_import_all")

    assert "res['failed']" in body or 'res["failed"]' in body, "the summary must include the failed count"
    assert "InfoBar.warning" in body, "a non-zero failed count must be surfaced as a warning"
    # the pre-fix summary line that dropped `failed` must be gone
    old_line = "msg = f\"Imported: {res['matched']} updated, {res['created']} created\"\n"
    assert old_line not in src


# --------------------------------------------------------------------------- workers.py
def test_workers_uses_get_free_port_instead_of_predictable_range():
    src = _read(WORKERS)
    head = src.split("class ", 1)[0]
    worker = _class_source(src, "AutopostBatchWorker")

    assert "9350" not in src, "the predictable 9350 + idx CDP port range must be gone"
    assert "from ..core.browser_launcher import get_free_port" in head, (
        "get_free_port must be imported at module top next to the other core imports"
    )
    assert "cdp_port = get_free_port()" in worker, "the autopost worker must request a real free port"


# --------------------------------------------------------------------------- tools/generate_brand_assets.py
BRAND_INIT = REPO_ROOT / "nazak" / "__init__.py"


def _brand_version_resolver():
    """Load the tool's `_resolve_package_version` (it only needs `re` + `pathlib`)."""
    src = _read(BRAND_ASSETS)
    start = src.index("def _resolve_package_version()")
    func_src = src[start:].split("\nPACKAGE_VERSION")[0]
    namespace = {"re": re, "Path": Path, "__file__": str(BRAND_ASSETS)}
    exec(compile(func_src, str(BRAND_ASSETS), "exec"), namespace)
    return namespace["_resolve_package_version"]


def test_brand_assets_uses_repo_relative_path_and_package_version():
    src = _read(BRAND_ASSETS)

    assert "D:/nazak" not in src and "D:\\nazak" not in src, "the author's hard-coded D:/nazak path must be gone"
    assert 'Path(__file__).resolve().parents[2] / "data" / "assets"' in src, (
        "assets dir must be repo-relative, like the sibling generators"
    )
    assert "V1.3.0" not in src, "the stale hard-coded V1.3.0 banner tag must be gone"
    assert "from .. import __version__ as version" in src, "the package version must be imported"
    assert 'f"SYS // ANTI-DETECT ARCHITECTURE • V{PACKAGE_VERSION} RELEASE"' in src, (
        "the banner text must be derived from the package version"
    )


def test_brand_assets_resolves_the_real_package_version():
    """The version helper must return `nazak.__version__`, also without package context."""
    package_version = re.search(r'__version__\s*=\s*["\']([^"\']+)["\']', _read(BRAND_INIT))
    assert package_version, "nazak/__init__.py must define __version__"
    assert _brand_version_resolver()() == package_version.group(1)


# --------------------------------------------------------------------------- mass_generate_dialog
def test_mass_generate_dialog_docstring_matches_slider_range():
    src = _read(MASS_GENERATE_DIALOG)

    doc_range = re.search(r"N\s*\((\d+)\s*to\s*(\d+)\)", src)
    slider_range = re.search(r"self\.slider_count\.setRange\((\d+)\s*,\s*(\d+)\)", src)
    assert doc_range, "the module docstring must state the generation range as 'N (a to b)'"
    assert slider_range, "slider_count must set an explicit range"
    assert doc_range.groups() == slider_range.groups(), (
        f"docstring range {doc_range.groups()} != slider range {slider_range.groups()}"
    )
    docstring = src.split('"""')[1]
    assert "1..200" in docstring or "1-200" in docstring, "the docstring must mention the CLI/API 1..200 range"
