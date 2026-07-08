"""X-Request-Id middleware — the entry point of the correlation chain.

Responsibilities:
  - Reuse the Nginx-generated `X-Request-Id` (proxy_set_header forwards
    `$request_id`, a 32-char random hex from nginx >= 1.11). Accept a
    caller-supplied value only if it looks sane.
  - Fall back to a fresh UUIDv4 when the header is missing, too long,
    or contains CR/LF (header-injection guard — logs rely on the id
    being safe to interpolate into log-line templates).
  - Bind the id to `app.context._request_id` for the duration of the
    request so every log line / async task in the handler can tag with
    it.
  - Echo the id back in the response `X-Request-Id` header so curl /
    browser devtools / ops traces can correlate a client failure with
    server logs.

Implementation note: we override the raw ASGI `__call__` rather than use
`before_request` / `after_response` hooks because the HawkAPI 0.1.4 hook
pipeline buffers the entire response body before running the after-hook
— that would break streaming downloads passing through this middleware.
"""
from __future__ import annotations

import uuid
from typing import Any

from hawkapi._types import ASGIApp, Receive, Scope, Send
from hawkapi.middleware import Middleware

from app.context import _request_id, set_request_id

REQUEST_ID_HEADER = "X-Request-Id"
_MAX_ID_LEN = 128  # generous — nginx emits 32 chars; clients may add tenant prefixes
_HEADER_NAME_LC = REQUEST_ID_HEADER.lower().encode("latin-1")
_HEADER_NAME_BYTES = REQUEST_ID_HEADER.encode("latin-1")


def _is_safe_id(raw: str) -> bool:
    """Reject anything that could break log-line integrity or poison headers."""
    if not raw or len(raw) > _MAX_ID_LEN:
        return False
    for ch in raw:
        if ch in ("\r", "\n") or ord(ch) < 0x20 or ord(ch) == 0x7F:
            return False
    return True


def _extract_header(scope: Scope, name_lc: bytes) -> str | None:
    for k, v in scope.get("headers", []):
        if k.lower() == name_lc:
            try:
                return v.decode("latin-1")
            except Exception:  # noqa: BLE001
                return None
    return None


class RequestIdMiddleware(Middleware):
    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        incoming = _extract_header(scope, _HEADER_NAME_LC)
        rid = incoming if (incoming is not None and _is_safe_id(incoming)) else str(uuid.uuid4())
        rid_bytes = rid.encode("latin-1")

        async def send_with_header(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                headers = [
                    (k, v) for k, v in message.get("headers", [])
                    if k.lower() != _HEADER_NAME_LC
                ]
                headers.append((_HEADER_NAME_BYTES, rid_bytes))
                message = {**message, "headers": headers}
            await send(message)

        token = set_request_id(rid)
        try:
            await self.app(scope, receive, send_with_header)
        finally:
            _request_id.reset(token)
