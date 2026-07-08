"""HTTP helpers — small building blocks used by routers.

Keeping these out of `app/routers/public.py` so they're unit-testable without
standing up HawkAPI / DB / crypto plumbing.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

if TYPE_CHECKING:
    from hawkapi import Request


def client_ip_from_scope(scope: Mapping[str, Any]) -> str:
    """Scope-based variant of `client_ip` for ASGI middleware.

    Same trust model as `client_ip`: trust Nginx-set X-Forwarded-For
    first hop, fall back to the uvicorn socket peer.
    """
    for k, v in scope.get("headers", []):
        if k.lower() == b"x-forwarded-for":
            return str(v.decode("latin-1").split(",")[0].strip())
    client = scope.get("client")
    if client:
        return str(client[0])
    # Fallback placeholder for log/rate-limit keys, not a bind address.
    return "0.0.0.0"  # noqa: S104  # nosec B104


def client_ip(request: Request) -> str:
    """Resolve the effective client IP for logging and rate-limiting.

    Reads the first hop of `X-Forwarded-For` (set by Nginx via
    `proxy_set_header X-Forwarded-For $remote_addr;` — single-value,
    Nginx-controlled, not client-spoofable in the normal path). Falls
    back to the uvicorn-observed socket peer, then a safe literal.

    Callers must NOT trust this value beyond the edge proxy: container
    bypass (direct connection to api:8000) would allow header spoofing.
    """
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    client = request.client
    if not client:
        # Fallback placeholder for log/rate-limit keys, not a bind address.
        return "0.0.0.0"  # noqa: S104  # nosec B104
    # HawkAPI exposes `client` as a `tuple[str, int]`; the test doubles in
    # `tests/unit/test_http_utils.py` pass `SimpleNamespace(host=...)` for
    # legacy duck-typing. Support both without pulling in a type dependency.
    return client[0] if isinstance(client, tuple) else client.host  # type: ignore[attr-defined]


def content_disposition_attachment(filename: str, *, ascii_fallback: str | None = None) -> str:
    """Build a Content-Disposition header that survives non-ASCII filenames.

    Returns a string in the form::

        attachment; filename="<ascii-fallback>"; filename*=UTF-8''<percent-encoded>

    Per RFC 5987 + RFC 6266, modern browsers prefer `filename*=UTF-8''...` when
    present, older or strict parsers fall back to `filename="..."`. This
    matters because:

    * Cyrillic / CJK filenames would otherwise arrive at the client as
      mojibake or be mangled to underscores by the safe-filename sanitiser.
    * A filename containing a `"` or CR/LF in the quoted-string form could
      break out of the header — a header-injection vector.

    `ascii_fallback` is used verbatim inside the quoted `filename="..."`
    segment after stripping characters that can't safely appear there.
    When omitted, a fallback is derived from `filename` by replacing every
    byte outside the safe set `[A-Za-z0-9._- ]` with `_` — matching what
    `StagingService.safe_filename` produces.
    """
    if ascii_fallback is None:
        ascii_fallback = _ascii_only(filename) or "file"
    safe_ascii = _strip_quoted_unsafe(ascii_fallback) or "file"
    # RFC 5987 value: token `UTF-8''<pct-encoded>`. Use RFC 3986 unreserved
    # set — percent-encode everything else.
    encoded = quote(filename, safe="")
    return f"attachment; filename=\"{safe_ascii}\"; filename*=UTF-8''{encoded}"


def _ascii_only(name: str) -> str:
    return "".join(c if _is_safe_ascii(c) else "_" for c in name)


def _is_safe_ascii(c: str) -> bool:
    return c.isascii() and (c.isalnum() or c in "._- ")


def _strip_quoted_unsafe(name: str) -> str:
    # Inside a quoted-string, disallow CR, LF, the quote char itself, and
    # backslash (we don't emit an escape sequence).
    return "".join(c for c in name if c not in '"\r\n\\')
