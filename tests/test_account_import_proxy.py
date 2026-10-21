"""Hunt X-23/X-24: the account-import path silently dropped the proxy
(host/port empty -> is_direct() -> Chrome exits from the real IP) and collided
on the profile id inside the same second.
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from nazak.core.account_provisioner import AccountProvisioner
from nazak.core.profile_manager import ProfileManager
from nazak.models.proxy import ProxyType

ACCOUNT = "user@gmail.com:pw123:JBSWY3DPEHPK3PXP:rec@mail.com"


def _prov(tmp_path: Path) -> tuple[AccountProvisioner, ProfileManager]:
    pm = ProfileManager(tmp_path / "p.json", tmp_path / "profiles")
    return AccountProvisioner(pm, tmp_path / "profiles"), pm


def test_x23_proxy_is_parsed_into_the_profile(tmp_path):
    """The proxy line must be PARSED, not wrapped in a raw string: host/port
    empty made is_direct() True and dropped --proxy-server from the argv."""
    prov, _ = _prov(tmp_path)
    created = prov.batch_import_and_create_profiles(ACCOUNT, proxy_list=["http://user:pass@1.2.3.4:8080"])
    proxy = created[0].proxy
    assert proxy.host == "1.2.3.4"
    assert proxy.port == 8080
    assert proxy.username == "user"
    assert proxy.password == "pass"
    assert proxy.is_direct() is False, "the imported account would run WITHOUT its proxy (X-23)"
    assert proxy.to_chrome_proxy_arg() == "http://1.2.3.4:8080"
    assert proxy.to_httpx_url() is not None, "the OAuth token exchange would bypass the proxy (X-23)"


def test_x23_socks5_keeps_its_type(tmp_path):
    prov, _ = _prov(tmp_path)
    created = prov.batch_import_and_create_profiles(ACCOUNT, proxy_list=["socks5://u:p@h:1080"])
    proxy = created[0].proxy
    assert proxy.type == ProxyType.SOCKS5, "a socks5:// line was mislabelled as HTTP (X-23)"
    assert proxy.host == "h"
    assert proxy.port == 1080
    assert proxy.username == "u"


def test_x23_invalid_port_is_skipped_and_the_batch_continues(tmp_path):
    prov, pm = _prov(tmp_path)
    created = prov.batch_import_and_create_profiles(ACCOUNT, proxy_list=["1.2.3.4:99999"])
    assert len(created) == 1, "one broken proxy line killed the whole batch (X-23)"
    assert prov.last_import_skipped, "the broken proxy line was not reported (X-23)"
    assert "99999" in prov.last_import_skipped[0]["proxy"]
    assert prov.last_import_skipped[0]["error"]
    # the account itself is created, but without a proxy
    assert created[0].proxy.is_direct() is True


def test_x23_rotation_url_survives_the_import(tmp_path):
    prov, _ = _prov(tmp_path)
    created = prov.batch_import_and_create_profiles(
        ACCOUNT, proxy_list=["http://u:p@1.2.3.4:8080|http://rotate.example/ip"]
    )
    proxy = created[0].proxy
    assert proxy.rotation_url == "http://rotate.example/ip", "the rotation endpoint was lost (X-23)"


def test_x24_two_imports_get_distinct_ids(tmp_path):
    """X-24 (a.k.a. Y-01): the id was time-based, so a second import in the
    same second raised an unhandled ValueError."""
    prov, pm = _prov(tmp_path)
    first = prov.batch_import_and_create_profiles(ACCOUNT)
    second = prov.batch_import_and_create_profiles(ACCOUNT)
    assert first[0].id != second[0].id
    imported = [p.id for p in pm.list_profiles() if p.id.startswith("prof_acc_")]
    assert len(imported) == 2


def test_x23_round_robin_advances_over_the_proxy_list(tmp_path):
    prov, _ = _prov(tmp_path)
    created = prov.batch_import_and_create_profiles(
        "a@gmail.com:pw:JBSWY3DPEHPK3PXP\nb@gmail.com:pw:JBSWY3DPEHPK3PXP",
        proxy_list=["http://p1.example:8080", "http://p2.example:8080"],
    )
    hosts = {p.proxy.host for p in created}
    assert hosts == {"p1.example", "p2.example"}, f"round-robin broken: {hosts}"


def test_x23_cli_exposes_the_proxy_flag():
    """The proxy lines were a ghost parameter: neither the CLI nor the GUI
    could pass them."""
    from nazak.cli_cmds import autopost_accounts

    src = inspect.getsource(autopost_accounts.register)
    assert '"--proxy"' in src, "account import has no --proxy flag (X-23)"
    cmd_src = inspect.getsource(autopost_accounts.cmd_account_import)
    assert "proxy_list=" in cmd_src, "the CLI does not pass proxy_list to the provisioner (X-23)"
    assert "last_import_skipped" in cmd_src, "the CLI does not report the skipped proxy lines (X-23)"


def test_x23_gui_passes_the_proxy_lines():
    from nazak.gui.views import accounts_view

    src = inspect.getsource(accounts_view.AccountsView.on_provision_clicked)
    assert "proxy_list=" in src, "the GUI does not pass proxy_list to the provisioner (X-23)"
    assert "last_import_skipped" in src, "the GUI does not report the skipped proxy lines (X-23)"
    init_src = inspect.getsource(accounts_view.AccountsView.init_ui)
    assert "self.txt_proxies" in init_src, "the GUI has no proxy input field (X-23)"
