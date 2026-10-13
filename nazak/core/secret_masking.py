"""Shared secret-masking for proxy payloads (fix F6).

The API (``_mask_proxy_for_api``) and the CLI (``mask_proxy_dict``) used to
implement the same masking twice — and each had a gap the other had already
closed: the API leaked ``password="pw"`` when it appeared inside the username
(``pworker:pw@host``), the CLI leaked the documented ``host:port:user:pass``
colon form. One implementation now serves both surfaces.
"""

from __future__ import annotations

MASK = "***"


def mask_raw_proxy_string(raw: str) -> str:
    """Replace every credential segment of a proxy string with ``MASK``.

    Handles both documented shapes:

    - URL form ``scheme://user:pass@host:port`` — masks the userinfo password
      positionally (never a substring search: a password that also occurs in
      the username must not leave ``pworker:pw@`` partially masked).
    - Colon form ``host:port:user:pass`` (or ``host:port:user``) — masks the
      trailing credential segments.
    """
    raw = str(raw)
    # Split off an optional scheme first: the userinfo lives AFTER `://`.
    scheme, scheme_sep, rest = raw.partition("://")
    if "@" not in rest:
        # No credentials in the URL form. Fall back to the colon form only
        # when there was no scheme (a bare `host:port:user:pass` string).
        if scheme_sep:
            return raw
        parts = raw.split(":")
        # host:port:user:pass — mask only the password segment; the username
        # is not masked anywhere else in the product either (the `username`
        # field of the API payload stays readable).
        if len(parts) >= 4:
            return ":".join([*parts[:-1], MASK])
        return raw
    userinfo, sep, hostpart = rest.rpartition("@")
    user, colon, _password = userinfo.rpartition(":")
    masked_userinfo = f"{user}{colon}{MASK}" if colon else userinfo
    return f"{scheme}{scheme_sep}{masked_userinfo}{sep}{hostpart}"


def mask_proxy_fields(data: dict) -> dict:
    """Return a copy of a proxy dict with every secret field masked.

    Masks ``password``, the credential segments inside ``raw`` (both forms),
    and ``rotation_url``. Non-string / missing fields are left untouched.
    """
    out = dict(data)
    if out.get("password"):
        out["password"] = MASK
    raw = out.get("raw")
    if isinstance(raw, str) and raw:
        out["raw"] = mask_raw_proxy_string(raw)
    if out.get("rotation_url"):
        out["rotation_url"] = MASK
    return out
