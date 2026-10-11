"""Profile package constants (P0 refactor). Extracted from core/profile_manager.py."""

MAX_MASS_GENERATE_COUNT = 200
MAX_BUNDLE_ENTRIES = 20_000
MAX_BUNDLE_ENTRY_BYTES = 512 * 1024 * 1024
MAX_BUNDLE_TOTAL_BYTES = 1024 * 1024 * 1024
BUNDLE_CHUNK = 1024 * 1024

MASK = "***"
PROXY_SECRET_FIELDS = ("password", "raw", "rotation_url")
