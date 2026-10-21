"""Round-9 regressions: account-import id collisions (Y-01), arbitrary-account
publishing (Y-02), path traversal in the extension/launch path (Y-04) and the
profile-edit dialog silently dropping the proxy (Y-06).
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from nazak.core.account_provisioner import AccountProvisioner
from nazak.core.browser_launcher import BrowserLauncher
from nazak.core.extension_generator import generate_profile_extension
from nazak.core.profile_manager import ProfileManager
from nazak.models.profile import BrowserProfile, GoogleSettings
from nazak.models.proxy import ProxyConfig, ProxyType

ACCOUNT_LINE = "user@gmail.com:pw123:JBSWY3DPEHPK3PXP:rec@mail.com"


# ---------------------------------------------------------------------------
# Y-01: the imported profile id was time-based -> a second import in the same
# second raised an unhandled ValueError ("Profile with id ... already exists").
# ---------------------------------------------------------------------------
def test_y01_two_imports_in_the_same_second_do_not_collide(tmp_path):
    pm = ProfileManager(tmp_path / "p.json", tmp_path / "profiles")
    prov = AccountProvisioner(pm, tmp_path / "profiles")

    first = prov.batch_import_and_create_profiles(ACCOUNT_LINE)
    second = prov.batch_import_and_create_profiles(ACCOUNT_LINE)

    assert first[0].id != second[0].id, "two imports produced the SAME profile id (Y-01)"
    imported = [p.id for p in pm.list_profiles() if p.id.startswith("prof_acc_")]
    assert len(imported) == 2, f"the second import was lost (Y-01): {imported}"


def test_y01_two_different_accounts_in_one_batch_get_distinct_ids(tmp_path):
    pm = ProfileManager(tmp_path / "p.json", tmp_path / "profiles")
    prov = AccountProvisioner(pm, tmp_path / "profiles")

    created = prov.batch_import_and_create_profiles("a@gmail.com:pw:JBSWY3DPEHPK3PXP\nb@gmail.com:pw:JBSWY3DPEHPK3PXP")
    ids = [p.id for p in created]
    assert len(set(ids)) == len(ids), f"ids collided inside one batch: {ids}"
    imported = [p.id for p in pm.list_profiles() if p.id.startswith("prof_acc_")]
    assert len(imported) == 2


# ---------------------------------------------------------------------------
# Y-02: the auto-login flow used to pick an arbitrary profile and publish
# under its identity.
# ---------------------------------------------------------------------------
def test_y02_auto_login_refuses_without_an_explicit_account(tmp_path, monkeypatch):
    import nazak.cli_auto_login_and_upload as flow

    monkeypatch.setattr(flow, "DATA_DIR", tmp_path)
    monkeypatch.setattr(flow, "PROFILES_FILE", tmp_path / "p.json")
    monkeypatch.setattr(flow, "PROFILES_DIR", tmp_path / "profiles")
    monkeypatch.setattr(flow, "EXTENSIONS_DIR", tmp_path / "ext")
    monkeypatch.setattr(flow, "SCREENSHOTS_DIR", tmp_path / "shots")
    monkeypatch.delenv("GOOGLE_EMAIL", raising=False)
    monkeypatch.delenv("NAZAK_DATA_FILE", raising=False)

    import asyncio

    result = asyncio.run(flow.run_live_flow())
    assert result is False, "the flow continued without a named account (Y-02)"


# ---------------------------------------------------------------------------
# Y-04: a hostile profile id escaped the extensions/profiles roots (rmtree +
# writes + lock-file deletion outside the root).
# ---------------------------------------------------------------------------
def test_y04_extension_generator_refuses_a_traversal_id(tmp_path):
    ext_root = tmp_path / "ext"
    ext_root.mkdir()
    hostile = BrowserProfile(id="../../evil", name="X", google=GoogleSettings())

    with pytest.raises(ValueError):
        generate_profile_extension(hostile, ext_root)
    assert not (tmp_path.parent / "evil").exists(), "the extension was written outside the root (Y-04)"


def test_y04_launcher_refuses_a_traversal_id(tmp_path):
    profiles_dir = tmp_path / "profiles"
    profiles_dir.mkdir()
    victim = tmp_path / "VICTIM"
    victim.mkdir()
    (victim / "SingletonLock").write_text("x", encoding="utf-8")

    bl = BrowserLauncher(profiles_dir, tmp_path / "ext")
    hostile = BrowserProfile(id="../VICTIM", name="X", google=GoogleSettings())

    with pytest.raises(ValueError):
        bl.build_chrome_args(hostile, "C:/fake/chrome.exe")
    assert (victim / "SingletonLock").exists(), "lock files outside profiles_dir were deleted (Y-04)"


def test_y04_normal_profile_id_still_works(tmp_path):
    profiles_dir = tmp_path / "profiles"
    ext_root = tmp_path / "ext"
    bl = BrowserLauncher(profiles_dir, ext_root)
    prof = BrowserProfile(id="prof_ok", name="OK", google=GoogleSettings())
    args, ext = bl.build_chrome_args(prof, "C:/fake/chrome.exe")
    assert ext and Path(ext).is_relative_to(ext_root.resolve())
    assert any(str(profiles_dir.resolve()) in a for a in args)


# ---------------------------------------------------------------------------
# Y-06: the profile-edit dialog showed "direct" for a structured proxy (no
# `raw` string) and REPLACED the whole proxy on save — the profile silently
# stopped using its proxy.
# ---------------------------------------------------------------------------
def test_y06_edit_dialog_renders_a_structured_proxy(tmp_path):
    """The dialog field must carry the stored proxy, not the literal 'direct'."""
    import inspect

    from nazak.gui.dialogs import profile_edit_dialog

    src = inspect.getsource(profile_edit_dialog.ProfileEditDialog)
    assert "stored_proxy.raw" in src, (
        "the dialog must render the stored proxy — a structured proxy without a "
        "`raw` string used to be shown as 'direct' and replaced on save (Y-06)"
    )
    assert 'setText("direct")' in src, "the direct fallback is still expected for a direct profile"
    # the rendered string must carry the credentials (not the display mask)
    assert "self.input_proxy_raw.setText(stored_proxy.to_display_string())" not in src, (
        "the dialog must not render the masked form — saving it would store '***' as the password (Y-06)"
    )


def test_y06_structured_proxy_survives_a_dialog_roundtrip(tmp_path):
    """Model the dialog's save path with the field it would show."""
    pm = ProfileManager(tmp_path / "p.json", tmp_path / "profiles")
    created = pm.create_profile(
        BrowserProfile(
            id="api_prof",
            name="API prof",
            proxy=ProxyConfig(type=ProxyType.HTTP, host="198.51.100.7", port=8080, username="u", password="pw"),
        )
    )
    assert created.proxy.raw is None, "precondition: the API-shaped proxy has no raw string"

    stored = pm.get_profile("api_prof")
    # what the dialog now renders
    proto = stored.proxy.type.value
    cred = f"{stored.proxy.username}:{stored.proxy.password or ''}@" if stored.proxy.username else ""
    field_value = f"{proto}://{cred}{stored.proxy.host}:{stored.proxy.port}"

    # what the dialog does on save
    stored.proxy = ProxyConfig.parse(field_value.strip())
    pm.update_profile(stored)

    after = pm.get_profile("api_prof")
    assert after.proxy.host == "198.51.100.7"
    assert after.proxy.port == 8080
    assert after.proxy.password == "pw", "the proxy password was lost on save (Y-06)"
    assert not after.proxy.is_direct(), "the proxy was silently replaced with DIRECT (Y-06)"


def test_y06_gitignore_covers_the_tombstone_file():
    """Y-03: the JSON backend's tombstone file is runtime state next to
    profiles.json and must never be committed."""
    repo = Path(__file__).resolve().parents[1]
    ignore = (repo / ".gitignore").read_text(encoding="utf-8")
    assert "*.tombstones" in ignore or "profiles.json.tombstones" in ignore, (
        "the delete-tombstone file is not git-ignored (Y-03)"
    )
