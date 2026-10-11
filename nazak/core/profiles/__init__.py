"""Profile package facade (P0 refactor)."""

from .constants import (
    BUNDLE_CHUNK,
    MASK,
    MAX_BUNDLE_ENTRIES,
    MAX_BUNDLE_ENTRY_BYTES,
    MAX_BUNDLE_TOTAL_BYTES,
    MAX_MASS_GENERATE_COUNT,
    PROXY_SECRET_FIELDS,
)
from .files import validate_id
from .merge import load_notes_dict as _load_notes_dict, raw_from_proxy as _raw_from_proxy
from .presets import generate_default_10_profiles
from .service import ProfileService
from .store_json import STORE_SCHEMA_VERSION, JsonProfileBackend, ProfileBackend
from .store_sqlite import SQLITE_SCHEMA_VERSION, SqliteProfileBackend, backend_for, sqlite_path_for

__all__ = [
    "BUNDLE_CHUNK",
    "MASK",
    "MAX_BUNDLE_ENTRIES",
    "MAX_BUNDLE_ENTRY_BYTES",
    "MAX_BUNDLE_TOTAL_BYTES",
    "MAX_MASS_GENERATE_COUNT",
    "PROXY_SECRET_FIELDS",
    "SQLITE_SCHEMA_VERSION",
    "STORE_SCHEMA_VERSION",
    "JsonProfileBackend",
    "ProfileBackend",
    "ProfileService",
    "SqliteProfileBackend",
    "_load_notes_dict",
    "_raw_from_proxy",
    "backend_for",
    "generate_default_10_profiles",
    "sqlite_path_for",
    "validate_id",
]
