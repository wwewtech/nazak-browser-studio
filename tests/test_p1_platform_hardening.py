"""P1 platform hardening regression tests.

Covers the P1 pass on top of the P0 structural refactor:

- importing the config module must not touch the filesystem (explicit entry points)
- ``ensure_data_dirs()`` is idempotent and creates the whole runtime tree
- ``requirements.txt`` cannot drift from ``pyproject.toml``
- the windowed-GUI stdout/stderr replacement rotates its log file
- the Docker image is multi-stage, runs unprivileged and declares a healthcheck
- CI keeps the storage matrix, coverage gate and security audit wired up
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# P1: no import-time filesystem side effects
# ---------------------------------------------------------------------------
def test_import_config_does_not_create_data_dirs(tmp_path):
    """`import nazak.config` must not create anything on disk (P1).

    Run in a subprocess so the check is not affected by modules the test session
    already imported: a fresh interpreter, a fresh NAZAK_DATA_DIR, then assert
    that the directory is still absent after the import.
    """
    data_dir = tmp_path / "fresh_data"
    # Keep the inherited environment (Windows needs SYSTEMROOT/PATH for winsock
    # and asyncio); only the data root is redirected.
    env = {**os.environ, "NAZAK_DATA_DIR": str(data_dir), "PYTHONPATH": str(REPO_ROOT)}
    code = "import nazak.config as c;import sys;sys.exit(0 if not c.DATA_DIR.exists() else 3)"
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, (
        f"importing nazak.config created {data_dir}\nstdout={proc.stdout}\nstderr={proc.stderr[-2000:]}"
    )
    assert not data_dir.exists(), "config import must not provision the data tree"


def test_ensure_data_dirs_creates_tree_and_is_idempotent(monkeypatch, tmp_path):
    import nazak.config as config

    fresh = tmp_path / "runtime"
    monkeypatch.setattr(config, "DATA_DIR", fresh)
    monkeypatch.setattr(config, "PROFILES_DIR", fresh / "profiles")
    monkeypatch.setattr(config, "EXTENSIONS_DIR", fresh / "extensions")
    monkeypatch.setattr(config, "LOGS_DIR", fresh / "logs")
    monkeypatch.setattr(config, "_data_dirs_ready", False)

    assert config.ensure_data_dirs() == fresh
    for sub in ("", "profiles", "extensions", "logs"):
        assert (fresh / sub).is_dir(), f"{sub or '.'} was not created"

    # second call is a no-op (and must not raise if dirs already exist)
    assert config.ensure_data_dirs() == fresh


def test_entry_points_call_ensure_data_dirs():
    """Every real entry point provisions the tree explicitly."""
    checks = {
        "nazak/main.py": "ensure_data_dirs()",
        "nazak/api/server.py": "ensure_data_dirs()",
        "nazak/cli_cmds/common.py": "ensure_data_dirs()",
        "nazak/gui/main_window.py": "ensure_data_dirs()",
    }
    for rel, needle in checks.items():
        source = (REPO_ROOT / rel).read_text(encoding="utf-8")
        assert needle in source, f"{rel} must call {needle}"


# ---------------------------------------------------------------------------
# P1: single source of truth for dependencies
# ---------------------------------------------------------------------------
def _quote_list(text: str, key: str) -> list[str]:
    """Extract a flat TOML array of strings (``key = [ "a", "b" ]``) as a list."""
    match = re.search(rf"^{re.escape(key)}\s*=\s*\[(.*?)^\]", text, re.DOTALL | re.MULTILINE)
    if not match:
        return []
    body = match.group(1)
    return [item.strip() for item in re.findall(r'"([^"]+)"', body)]


def test_requirements_do_not_drift_from_pyproject():
    """requirements.txt and pyproject.toml must declare the same packages.

    `pyproject.toml [project.dependencies]` is the canonical runtime list and
    `requirements.txt` is what the Docker image installs; a package present in
    only one of them is a real deployment bug.
    """
    pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    requirements = (REPO_ROOT / "requirements.txt").read_text(encoding="utf-8")

    runtime = _quote_list(pyproject, "dependencies")
    assert runtime, "could not parse [project.dependencies] from pyproject.toml"
    dev = _quote_list(pyproject, "dev")

    req_lines = [line.split("#", 1)[0].strip() for line in requirements.splitlines() if line.split("#", 1)[0].strip()]

    missing_in_requirements = [dep for dep in runtime if dep not in req_lines]
    assert not missing_in_requirements, (
        f"declared in pyproject but absent from requirements.txt: {missing_in_requirements}"
    )

    known = set(runtime) | set(dev)
    unknown = [line for line in req_lines if line not in known]
    assert not unknown, (
        f"requirements.txt lines that are not declared in pyproject.toml (runtime or dev extra): {unknown}"
    )


def test_requirements_comment_points_at_pyproject_as_canonical():
    requirements = (REPO_ROOT / "requirements.txt").read_text(encoding="utf-8")
    assert "pyproject.toml" in requirements, "requirements.txt must name its canonical source"


# ---------------------------------------------------------------------------
# P1: bounded log growth in the windowed build
# ---------------------------------------------------------------------------
def test_rotating_stream_rotates_and_never_raises(tmp_path):
    from nazak.main import _RotatingStream

    log_path = tmp_path / "stdout.log"
    stream = _RotatingStream(log_path, max_bytes=200, backup_count=2)

    stream.write("x" * 500)
    stream.flush()

    assert log_path.exists(), "the stream must create its log file"
    backup = log_path.with_name(log_path.name + ".1")
    assert backup.exists(), "exceeding max_bytes must rotate into a .1 backup"
    assert backup.stat().st_size >= 200

    # After rotation new writes land in the primary file again.
    stream.write("tail")
    stream.flush()
    assert "tail" in log_path.read_text(encoding="utf-8")

    # Unknown/odd payloads must be swallowed, not crash the GUI.
    stream.write("")
    stream.flush()
    assert stream.isatty() is False


# ---------------------------------------------------------------------------
# P1: container hardening
# ---------------------------------------------------------------------------
def test_dockerfile_is_multistage_unprivileged_and_has_healthcheck():
    dockerfile = (REPO_ROOT / "Dockerfile").read_text(encoding="utf-8")

    stages = re.findall(r"^FROM\s+\S+(?:\s+AS\s+(\S+))?", dockerfile, re.MULTILINE)
    assert len(stages) >= 2, "Dockerfile must use multiple stages (builder + runtime)"
    assert any(name for name in stages), "the builder stage must be named (COPY --from=...)"

    assert "COPY --from=" in dockerfile, "the runtime stage must copy the prepared venv/browsers"
    assert re.search(r"^USER\s+(?!root)\S+", dockerfile, re.MULTILINE), "image must drop root"
    assert "USER root" not in dockerfile
    assert "HEALTHCHECK" in dockerfile, "image must declare a readiness probe"
    assert "playwright install chromium" in dockerfile, "Chromium must be installed in the image"
    # The unprivileged user must own the runtime data mount point.
    assert "chown" in dockerfile
    assert "NAZAK_DATA_DIR=/app/data" in dockerfile


def test_compose_passes_storage_backend_and_keeps_loopback_binding():
    compose = (REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert "NAZAK_PROFILE_STORE=${NAZAK_PROFILE_STORE:-json}" in compose
    assert "127.0.0.1:8899:8899" in compose, "published port must stay on loopback"
    assert "NAZAK_API_TOKEN" in compose


def test_env_example_documents_storage_backend():
    env_example = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
    assert "NAZAK_PROFILE_STORE=json" in env_example
    assert "sqlite" in env_example


# ---------------------------------------------------------------------------
# P1: CI quality gates
# ---------------------------------------------------------------------------
def test_ci_runs_both_storage_backends_with_coverage_gate():
    yaml = pytest.importorskip("yaml", reason="PyYAML is not required for the runtime package")

    workflow = yaml.safe_load((REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"))
    jobs = workflow["jobs"]

    matrix = jobs["test-matrix"]["strategy"]["matrix"]
    # The OS/Python matrix must stay a full cross product...
    assert sorted(matrix["os"]) == ["ubuntu-latest", "windows-latest"]
    assert len(matrix["python-version"]) == 4
    # ...while the storage backend is NOT a job-wide dimension: running every
    # suite with sqlite would break the suites that assert JSON-file internals on
    # purpose. It is exercised by a dedicated step instead (see the next test).
    assert "profile-store" not in matrix, (
        "the storage backend must not be a job-wide matrix dimension (breaks JSON-specific suites)"
    )

    steps_text = str(jobs["test-matrix"]["steps"])
    assert "--cov-fail-under=65" in steps_text, "coverage gate must be enforced"
    assert "NAZAK_PROFILE_STORE" in steps_text and "sqlite" in steps_text, (
        "a dedicated step must run the API/store suites against the SQLite backend"
    )
    assert "os.environ['NAZAK_PROFILE_STORE']" in steps_text.replace("\\'", "'"), (
        "the sqlite leg must set the variable itself so it works on both shells"
    )

    assert "security-audit" in jobs, "a dependency/SAST audit job must exist"
    audit_text = str(jobs["security-audit"]["steps"])
    assert "pip-audit" in audit_text and "bandit" in audit_text

    assert "live-browser-smoke" in jobs, "the opt-in live browser job must exist"
    live_text = str(jobs["live-browser-smoke"])
    assert "actions/cache" in live_text and "ms-playwright" in live_text, "the live job must cache Playwright browsers"


def test_sqlite_leg_targets_backend_agnostic_suites():
    """The SQLite CI leg must name real files and avoid JSON-specific suites."""
    workflow = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    match = re.search(
        r"os\.environ\['NAZAK_PROFILE_STORE'\] = 'sqlite'.*?pytest\.main\(\[(.*?)\]\)",
        workflow,
        re.DOTALL,
    )
    assert match, "could not find the SQLite storage-matrix step"

    files = re.findall(r"'(tests/[^']+)'", match.group(1))
    assert files, "the SQLite leg must name explicit test files"
    missing = [rel for rel in files if not (REPO_ROOT / rel).is_file()]
    assert not missing, f"the SQLite leg references missing test files: {missing}"

    forbidden = {
        "tests/test_deep_storage_and_concurrency.py",
        "tests/test_core_concurrency_and_storage.py",
        "tests/test_profile_manager.py",
        "tests/test_profile_manager_and_storage.py",
    }
    overlap = sorted(forbidden & set(files))
    assert not overlap, f"JSON-specific suites must not run under the SQLite backend: {overlap}"


def test_bandit_configuration_is_declared():
    pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert "[tool.bandit]" in pyproject
    assert "exclude_dirs" in pyproject
    assert "B603" in pyproject, "documented subprocess skip must stay explicit"


# ---------------------------------------------------------------------------
# P1: the release version cannot drift between the five places that carry it
# ---------------------------------------------------------------------------
def test_version_is_consistent_across_release_artifacts():
    import nazak

    version = nazak.__version__
    assert re.fullmatch(r"\d+\.\d+\.\d+", version), f"unexpected version format: {version}"
    parts = tuple(int(p) for p in version.split("."))

    pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert f'version = "{version}"' in pyproject, "pyproject.toml version is out of sync"

    build_exe = (REPO_ROOT / "build_exe.py").read_text(encoding="utf-8")
    assert f'_FALLBACK_VERSION = "{version}"' in build_exe, "build_exe.py fallback version is out of sync"

    installer = (REPO_ROOT / "installer.iss").read_text(encoding="utf-8")
    assert f'#define MyAppVersion "{version}"' in installer, "installer.iss version is out of sync"

    # version_info.txt used to lag two releases behind; keep it pinned to the package.
    version_info = (REPO_ROOT / "version_info.txt").read_text(encoding="utf-8")
    expected_tuple = f"filevers=({parts[0]}, {parts[1]}, {parts[2]}, 0)"
    assert expected_tuple in version_info, f"version_info.txt must declare {expected_tuple}"
    assert f"'{version}.0'" in version_info, "version_info.txt string fields are out of sync"


# ---------------------------------------------------------------------------
# P1: documentation links must resolve (docs are part of the product surface)
# ---------------------------------------------------------------------------
def test_documentation_relative_links_resolve():
    link_re = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
    docs = [REPO_ROOT / "README.md", REPO_ROOT / "CHANGELOG.md", *sorted((REPO_ROOT / "docs").glob("*.md"))]

    broken: list[str] = []
    checked = 0
    for doc in docs:
        assert doc.is_file(), f"documentation file is missing: {doc}"
        for raw in link_re.findall(doc.read_text(encoding="utf-8")):
            target = raw.strip()
            if target.startswith(("http://", "https://", "mailto:", "#")):
                continue
            path_part = target.split("#", 1)[0]
            if not path_part:
                continue
            checked += 1
            if not (doc.parent / path_part).resolve().exists():
                broken.append(f"{doc.relative_to(REPO_ROOT)} -> {target}")

    assert checked > 0, "no relative documentation links were inspected"
    assert not broken, f"broken relative documentation links: {broken}"


def test_documentation_is_free_of_cyrillic_outside_design_notes():
    """Docs are English-only (P1 translation pass).

    User-facing CLI help strings stay Russian by design, but that is code, not
    documentation — every `.md` shipped in the repo must be English.
    """
    docs = [REPO_ROOT / "README.md", REPO_ROOT / "CHANGELOG.md", *sorted((REPO_ROOT / "docs").glob("*.md"))]
    cyrillic = re.compile(r"[\u0400-\u04FF]")
    offenders = {
        doc.relative_to(REPO_ROOT).as_posix(): len(cyrillic.findall(doc.read_text(encoding="utf-8"))) for doc in docs
    }
    offenders = {name: count for name, count in offenders.items() if count}
    assert not offenders, f"documentation still contains Cyrillic characters: {offenders}"


def _collect_suite_counts() -> tuple[int, int, int]:
    """Return (expected_passed, collected, deselected) for the real test suite.

    ``expected_passed`` excludes the tests that carry an ``xfail`` marker: those
    are the documented open bugs, so they count as ``xfailed``/``xpassed`` in a
    run rather than as passes. Collection only, so this is cheap and does not
    re-run anything: it is what keeps the documented figures honest instead of
    merely self-consistent.
    """
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "tests", "--collect-only", "-q", "-p", "no:cacheprovider"],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=600,
    )
    output = proc.stdout + proc.stderr
    match = re.search(r"(\d+)/(\d+) tests collected \((\d+) deselected\)", output)
    assert match, f"could not read the collected-test counts from pytest output:\n{output[-2000:]}"
    selected, collected, deselected = (int(g) for g in match.groups())
    xfail_marked = sum(
        1
        for path in (REPO_ROOT / "tests").glob("test_*.py")
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.lstrip().startswith("@pytest.mark.xfail(")
    )
    return selected - xfail_marked, collected, deselected


def test_documentation_suite_figures_match_reality():
    """The documented suite figures must equal the real collection counts.

    These numbers drifted three times (the README said 772 while the changelog
    said 783 and the suite actually ran 787), so they are now checked against
    pytest's own collection: the README badge, the README test section and the
    newest CHANGELOG entry all have to agree with reality, not just each other.
    Historical changelog entries are ignored on purpose.
    """
    selected, collected, deselected = _collect_suite_counts()

    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    changelog = (REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")

    badge = re.search(r"badge/tests-(\d+)%20passing", readme)
    assert badge, "README must keep the 'tests passing' badge"
    readme_collected = re.search(r"\*\*(\d+) collected tests\*\*", readme)
    assert readme_collected, "README must state the collected test count"
    readme_run = re.search(r"(\d+) passed, (\d+) deselected", readme)
    assert readme_run, "README must state the current 'N passed, M deselected' line"

    # The newest CHANGELOG entry is the section right after the title.
    current_entry = changelog.split("\n## ", 1)[1]
    changelog_run = re.search(r"(\d+) passed, (\d+) deselected", current_entry)
    assert changelog_run, "the newest CHANGELOG entry must state 'N passed, M deselected'"

    expected = (
        f"real suite: {selected} selected / {collected} collected / {deselected} deselected\n"
        f"README badge: {badge.group(1)}\n"
        f"README collected: {readme_collected.group(1)}\n"
        f"README run line: {readme_run.group(1)} passed, {readme_run.group(2)} deselected\n"
        f"CHANGELOG run line: {changelog_run.group(1)} passed, {changelog_run.group(2)} deselected"
    )

    assert badge.group(1) == readme_run.group(1) == changelog_run.group(1) == str(selected), (
        f"documented 'passed' figure is out of date\n{expected}"
    )
    assert readme_collected.group(1) == str(collected), f"documented collected figure is out of date\n{expected}"
    assert readme_run.group(2) == changelog_run.group(2) == str(deselected), (
        f"documented deselected figure is out of date\n{expected}"
    )


def test_documentation_references_existing_test_files():
    """Test files named in the docs must exist under tests/.

    `tests/test_round3_fixes.py` was split into three files while README and
    CHANGELOG kept pointing at the old name, so the references are validated now.
    """
    docs = [
        REPO_ROOT / "README.md",
        REPO_ROOT / "CHANGELOG.md",
    ]
    ref_re = re.compile(r"tests/(test_[a-z0-9_]+\.py)")
    missing: dict[str, list[str]] = {}
    for doc in docs:
        for ref in sorted(set(ref_re.findall(doc.read_text(encoding="utf-8")))):
            if not (REPO_ROOT / "tests" / ref).is_file():
                missing.setdefault(doc.name, []).append(ref)
    assert not missing, f"documents reference test files that do not exist: {missing}"
