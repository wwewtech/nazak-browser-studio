"""
Global test bootstrap — audit finding E2 (tests must never mutate real data/).

``nazak.api.server`` builds module-level singletons (profile_manager, upload
queue, ...) bound to ``nazak.config`` paths at import time. Redirecting
``NAZAK_DATA_DIR`` here — before any test module imports ``nazak`` — sends
every profiles.json / profiles/ / extensions/ / videos/ artifact of the test
run into a throwaway temp directory instead of the developer's production
``data/`` folder.
"""

import atexit
import os
import shutil
import tempfile
from pathlib import Path

_TEST_DATA_DIR = Path(tempfile.mkdtemp(prefix="nazak_test_data_"))
os.environ["NAZAK_DATA_DIR"] = str(_TEST_DATA_DIR)


def _cleanup_test_data_dir() -> None:
    shutil.rmtree(_TEST_DATA_DIR, ignore_errors=True)


atexit.register(_cleanup_test_data_dir)
