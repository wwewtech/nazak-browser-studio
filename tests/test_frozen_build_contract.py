"""Frozen-build contract: every statically imported nazak submodule must be discoverable.

PyInstaller's Analysis walks static imports from nazak/main.py, so the P0-era
subpackages (api.routers, core.profiles, gui.tasks/task_bridge) are picked up
automatically. This guard fails when someone adds a nazak module that:
  * is imported dynamically (not visible to the static walk), or
  * name-collides with an entry in the spec's excludes list.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
NAZAK_DIR = REPO_ROOT / "nazak"
SPEC = REPO_ROOT / "NazakBrowserStudio.spec"


def _static_imports(module_path: Path) -> set[str]:
    """Collect absolute module names imported statically by a nazak module."""
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    package = ".".join(module_path.relative_to(REPO_ROOT).with_suffix("").parts[:-1])
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0:
                if node.module:
                    found.add(node.module)
                for alias in node.names:
                    # `from x import y` also makes `x.y` visible statically.
                    found.add(f"{node.module}.{alias.name}")
            else:
                base_parts = package.split(".")
                base = ".".join(base_parts[: len(base_parts) - node.level + 1])
                if node.module:
                    found.add(f"{base}.{node.module}")
                    for alias in node.names:
                        found.add(f"{base}.{node.module}.{alias.name}")
                else:
                    for alias in node.names:
                        found.add(f"{base}.{alias.name}")
    return {name for name in found if name.startswith("nazak")}


def _with_package_prefixes(name: str) -> set[str]:
    """`nazak.api.server` also makes `nazak.api` (its package) importable."""
    parts = name.split(".")
    return {".".join(parts[: i + 1]) for i in range(len(parts))}


def _module_file(name: str) -> Path | None:
    """Resolve a nazak module name to its file (nazak/ is the package root)."""
    if name == "nazak":
        return NAZAK_DIR / "__init__.py"
    parts = name.split(".")
    if parts[0] != "nazak":
        return None
    rel = Path(*parts[1:])
    for cand in (rel.with_suffix(".py"), rel / "__init__.py"):
        p = NAZAK_DIR / cand
        if p.is_file():
            return p
    return None


def _walk_nazak(start: str, seen: set[str]) -> None:
    """DFS over static nazak imports starting from `start`."""
    if start in seen:
        return
    seen.add(start)
    module_path = _module_file(start)
    if module_path is None:
        return
    for imp in _static_imports(module_path):
        if imp.startswith("nazak"):
            _walk_nazak(imp, seen)


def test_frozen_entry_walk_covers_all_nazak_subpackages():
    """Every nazak/*.py file must be reachable from main.py via static imports.

    A file that is NOT reachable would be silently missing from the frozen exe
    (ImportError at runtime, exactly the class of bug the P0 split could have
    introduced with a dynamic import).
    """
    seen: set[str] = set()
    _walk_nazak("nazak.main", seen)
    # A reachable module makes every package on its path reachable too.
    seen = {p for name in seen for p in _with_package_prefixes(name)} | seen

    # Modules deliberately outside the frozen app: dev-time asset generators
    # (never imported at runtime) and GUI leftovers not referenced anywhere.
    RUNTIME_OPTIONAL = {
        "nazak.tools.generate_bespoke_banners",
        "nazak.tools.generate_brand_assets",
        "nazak.tools.generate_monumental_banner",
        "nazak.gui.views.secrets_mode_card",  # superseded by SettingsView inline card
    }

    # Every real module under nazak/ must appear in the walked set.
    unreachable: list[str] = []
    for py in NAZAK_DIR.rglob("*.py"):
        rel = py.relative_to(REPO_ROOT).with_suffix("")
        name = ".".join(rel.parts)
        if name.endswith(".__init__"):
            name = name[: -len(".__init__")]
        if name not in seen and name not in RUNTIME_OPTIONAL:
            unreachable.append(name)
    assert not unreachable, (
        f"nazak modules unreachable from nazak/main.py via static imports "
        f"(would be missing from the frozen exe): {sorted(unreachable)}"
    )


def test_no_nazak_module_is_excluded_by_spec():
    """The spec excludes list must never shadow a nazak module name."""
    spec_text = SPEC.read_text(encoding="utf-8")
    import re

    excludes_block = re.search(r"excludes\s*=\s*\[(.*?)\]", spec_text, re.DOTALL)
    assert excludes_block, "spec must define an excludes list"
    excluded = {m.strip().strip("'\"") for m in excludes_block.group(1).split(",") if m.strip().strip("'\"")}

    for py in NAZAK_DIR.rglob("*.py"):
        parts = py.relative_to(NAZAK_DIR).with_suffix("").parts
        if parts[-1] == "__init__":
            parts = parts[:-1]
        for i in range(len(parts)):
            name = ".".join(parts[: i + 1])
            full = "nazak." + name
            assert full not in excluded, f"spec excludes shadows the nazak module {full}"
            # A bare top-level exclusion (e.g. 'test') must not shadow nazak.test-style names.
            assert parts[i] not in excluded or name != parts[i], (
                f"spec excludes entry {parts[i]!r} shadows nazak module {full}"
            )
