"""Debug the A-35 contract anchor: print what the generated hook looks like
around the defineProperty call to see why fullVersionList is not found."""

import tempfile
from pathlib import Path

from nazak.core.extension_generator import generate_profile_extension
from nazak.core.fingerprint_generator import generate_random_fingerprint
from nazak.models.profile import BrowserProfile, GoogleSettings

fp = generate_random_fingerprint("windows")
with tempfile.TemporaryDirectory() as td:
    ext = generate_profile_extension(BrowserProfile(id="p", name="P", fingerprint=fp, google=GoogleSettings()), Path(td))
    src = (Path(ext) / "stealth.js").read_text(encoding="utf-8")

anchor = "Object.defineProperty(uaData, 'getHighEntropyValues'"
idx = src.find(anchor)
print("anchor found at:", idx)
if idx >= 0:
    print(repr(src[idx:idx+400]))
else:
    # what IS there?
    i = src.find("getHighEntropyValues")
    while i >= 0:
        print("--- occurrence at", i, "---")
        print(repr(src[i-80:i+120]))
        i = src.find("getHighEntropyValues", i+1)
        if i > 40000:
            break
