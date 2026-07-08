"""Request-scoped context — holds the correlation ID that chains HTTP
request → Redis queue job → worker task → downstream SMTP / Telegram call.

Use the `contextvars` module (not thread-locals) so the value is copied
into every asyncio task spawned inside the request handler. A failed
SMTP retry that logs from a background task still carries the same
`request_id` as the HTTP request that created the transfer.

Typical flow:

    HTTP                            Redis                    Worker
    ────                            ─────                    ──────
    Nginx $request_id  →
      RequestIdMiddleware
        sets contextvar
        handler runs:
          push_job(..., payload={..., "request_id": current_request_id()})
                                    LPUSH upload:ready
                                      ↓
                                    BRPOP                    consumer loop:
                                                               bind from payload
                                                               run_consumer_iteration
                                                               logs carry rid
"""

from __future__ import annotations

from contextvars import ContextVar, Token

# None = "no correlation id in scope" — caller code should log normally
# without a request_id field, not crash.
_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)


def current_request_id() -> str | None:
    """Return the request ID bound to the current async task, or None."""
    return _request_id.get()


def set_request_id(rid: str) -> Token[str | None]:
    """Bind a request ID to the current task. Returns a Token the caller
    MUST pass to `_request_id.reset(token)` in a finally-block so the
    previous value is restored (pytest etc.)."""
    return _request_id.set(rid)
