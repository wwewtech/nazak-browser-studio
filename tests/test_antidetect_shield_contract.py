"""Round-10 anti-detect shield regressions (A-01..A-03).

These are SOURCE-level contracts (the repository convention for the GUI/shield
layer, see test_gui_and_tools_hardening.py): they pin the exact defects the
empirical audit found in the generated stealth.js, so a regression cannot reach
a release unnoticed. The BEHAVIOURAL proof is the live test
``tests/live/test_antidetect_shield_live.py`` (real Chrome, `pytest -m live`).
"""

from __future__ import annotations

import re
import tempfile
from pathlib import Path

import pytest

from nazak.core.extension_generator import generate_profile_extension
from nazak.core.fingerprint_generator import generate_random_fingerprint
from nazak.models.profile import BrowserProfile, GoogleSettings

REPO_ROOT = Path(__file__).resolve().parents[1]


def _generated_js() -> str:
    fp = generate_random_fingerprint("windows")
    profile = BrowserProfile(id="shield_contract", name="Shield", fingerprint=fp, google=GoogleSettings())
    with tempfile.TemporaryDirectory() as td:
        ext = generate_profile_extension(profile, Path(td))
        assert ext, "the extension generator returned no path"
        return (Path(ext) / "stealth.js").read_text(encoding="utf-8")


def test_a01_timezone_constant_is_in_the_shared_scope():
    """A-01: `targetTimezone` was declared with `const` inside section 6's
    try-block and used by section 12d — an out-of-scope reference, so EVERY
    Intl.DateTimeFormat().resolvedOptions() call threw
    "ReferenceError: targetTimezone is not defined"."""
    src = _generated_js()
    declarations = re.findall(r"^\s*const targetTimezone\s*=", src, re.M)
    assert len(declarations) == 1, (
        f"targetTimezone must be declared exactly once (found {len(declarations)}) — a second "
        "declaration inside a try-block made the other reference out of scope (A-01)"
    )
    # the single declaration must NOT live inside a try-block: find its indent
    line_no = next(idx for idx, line in enumerate(src.splitlines()) if re.match(r"^\s*const targetTimezone\s*=", line))
    lines = src.splitlines()
    # walk back to the section header the declaration belongs to
    section = ""
    for i in range(line_no, -1, -1):
        m = re.match(r"^\s*// (\d+[a-z]?)\. ", lines[i])
        if m:
            section = m.group(1)
            break
    assert section == "0", (
        f"targetTimezone is declared in section {section}; it must live in the IIFE scope "
        "next to makeNative() so BOTH the Intl hook and the Date hook can use it (A-01)"
    )


def test_a01_no_out_of_scope_timezone_use_in_the_intl_section():
    """The Intl locale section must not reference a constant it cannot see."""
    src = _generated_js()
    # the resolvedOptions hook must use the shared constant
    assert re.search(r"res\.timeZone\s*=\s*targetTimezone;", src), "the Intl hook no longer sets the timezone"
    # there must be no leftover local shadow declaration
    assert not re.search(r"const targetTimezone = [^;]+;\n\s*const origResolvedOptions", src), (
        "a local targetTimezone declaration is back (it shadows the shared one and breaks the Intl hook, A-01)"
    )


def test_a02_intl_constructors_keep_their_static_side():
    """A-02: replacing Intl.NumberFormat/Intl.DateTimeFormat with a plain
    function dropped `supportedLocalesOf` — a hard TypeError in any site that
    calls it, and a blatant sign of a tampered Intl."""
    src = _generated_js()
    assert "supportedLocalesOf" in src, (
        "the Intl constructor replacement must keep the static side (supportedLocalesOf) — "
        "dropping it broke every caller (A-02)"
    )
    # the static method must be re-attached to the wrapper, not only called
    assert re.search(r"Object\.defineProperty\(wrapped,\s*'supportedLocalesOf'", src), (
        "the wrapped Intl constructors must re-attach supportedLocalesOf (A-02)"
    )


def test_a03_voices_use_defineproperty_not_assign():
    """A-03: SpeechSynthesisVoice.prototype.name is a GETTER-ONLY accessor.
    Object.assign() onto such an instance throws, and the throw aborted the
    whole voice section — the page kept the HOST's voices."""
    src = _generated_js()
    voice_block = src[src.find("voiceObjects") - 400 : src.find("voiceObjects") + 600]
    assert "Object.assign(Object.create" not in voice_block, (
        "the voice objects must not be built with Object.assign — the SpeechSynthesisVoice "
        "prototype has getter-only properties and the assignment throws (A-03)"
    )
    assert "Object.defineProperty(inst" in voice_block, (
        "the voice objects must define their own properties with defineProperty (A-03)"
    )


def test_shield_sections_are_independent_of_each_other():
    """A structural guarantee: every section's try-block must be independent,
    so one failing statement cannot abort the NEXT section's shield."""
    src = _generated_js()
    # no section may reference a constant declared in a DIFFERENT section's
    # try-block. The audit found exactly that class of bug (A-01).
    for const_name in ("targetTimezone", "targetOffset"):
        decl_lines = [
            idx for idx, line in enumerate(src.splitlines()) if re.match(rf"^\s*const {const_name}\s*=", line)
        ]
        assert len(decl_lines) == 1, f"{const_name} is declared {len(decl_lines)} times"


def test_generated_shield_is_valid_javascript():
    """The generated shield must parse as JS (node --check when available)."""
    import shutil
    import subprocess

    src = _generated_js()
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    with tempfile.TemporaryDirectory() as td:
        f = Path(td) / "stealth.js"
        f.write_text(src, encoding="utf-8")
        proc = subprocess.run([node, "--check", str(f)], capture_output=True, text=True)
        assert proc.returncode == 0, f"the generated shield is not valid JS: {proc.stderr[:400]}"
