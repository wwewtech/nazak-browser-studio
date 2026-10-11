"""Honest publication status: "not confirmed" is not "succeeded" (audit R3).

Uploaders use this prefix to mark the situation "the Publish/Share click was made,
but the result is not confirmed". Such an error must not be retried (otherwise a
duplicate publication on the account), and must not be passed off as success.
"""

from __future__ import annotations

PUBLISH_UNCERTAIN_PREFIX = "publish-uncertain"


def publish_uncertain(message: str) -> str:
    """Error string for "published? unknown"."""
    return f"{PUBLISH_UNCERTAIN_PREFIX}: {message}"


def is_publish_uncertain(err: str | None) -> bool:
    return bool(err) and str(err).startswith(PUBLISH_UNCERTAIN_PREFIX)
