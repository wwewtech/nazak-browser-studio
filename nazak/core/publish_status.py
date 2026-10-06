"""Честный статус публикации: «не подтверждено» — это не «получилось» (audit R3).

Загрузчики помечают этим префиксом ситуацию «клик Publish/Share сделан, но
результат не подтверждён». Такую ошибку нельзя ретраить (иначе дубль
публикации на аккаунте), и нельзя выдавать за успех.
"""

from __future__ import annotations

PUBLISH_UNCERTAIN_PREFIX = "publish-uncertain"


def publish_uncertain(message: str) -> str:
    """Строка ошибки для «опубликовано? неизвестно»."""
    return f"{PUBLISH_UNCERTAIN_PREFIX}: {message}"


def is_publish_uncertain(err: str | None) -> bool:
    return bool(err) and str(err).startswith(PUBLISH_UNCERTAIN_PREFIX)
