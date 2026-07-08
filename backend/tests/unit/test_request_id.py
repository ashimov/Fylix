"""Request-ID correlation: middleware + contextvar + worker propagation."""

from __future__ import annotations

from hawkapi import HawkAPI
from hawkapi.testing import TestClient

from app.context import current_request_id, set_request_id
from app.middleware.request_id import REQUEST_ID_HEADER, RequestIdMiddleware


def _app_with_middleware() -> HawkAPI:
    app = HawkAPI()
    app.add_middleware(RequestIdMiddleware)

    @app.get("/probe")
    def probe() -> dict[str, str | None]:
        return {"rid": current_request_id()}

    return app


def test_middleware_generates_request_id_when_header_absent() -> None:
    client = TestClient(_app_with_middleware())
    r = client.get("/probe")
    assert r.status_code == 200
    rid = r.headers.get(REQUEST_ID_HEADER)
    assert rid is not None
    # UUIDv4 is 36 chars with dashes.
    assert len(rid) == 36
    # Handler saw the same id via contextvar.
    assert r.json()["rid"] == rid


def test_middleware_uses_incoming_header_when_provided() -> None:
    client = TestClient(_app_with_middleware())
    given = "abc-123-from-nginx"
    r = client.get("/probe", headers={REQUEST_ID_HEADER: given})
    assert r.headers.get(REQUEST_ID_HEADER) == given
    assert r.json()["rid"] == given


def test_middleware_rejects_overlong_incoming_id() -> None:
    """An attacker cannot poison logs with a 10 MB X-Request-Id."""
    client = TestClient(_app_with_middleware())
    r = client.get("/probe", headers={REQUEST_ID_HEADER: "x" * 500})
    rid = r.headers.get(REQUEST_ID_HEADER)
    assert rid is not None
    assert len(rid) == 36  # replaced with fresh UUID


def test_middleware_rejects_control_chars_in_incoming_id() -> None:
    client = TestClient(_app_with_middleware())
    r = client.get("/probe", headers={REQUEST_ID_HEADER: "ok\r\nX-Injected: bad"})
    rid = r.headers.get(REQUEST_ID_HEADER)
    assert rid is not None
    assert "\r" not in rid and "\n" not in rid
    assert len(rid) == 36  # fell back to fresh UUID


def test_contextvar_is_none_outside_request() -> None:
    """contextvar scope: handler bind is request-local, doesn't leak."""
    assert current_request_id() is None


def test_set_request_id_manually() -> None:
    """Worker will use this to bind request_id read from a Redis job payload."""
    token = set_request_id("worker-bound-id")
    try:
        assert current_request_id() == "worker-bound-id"
    finally:
        # Restore previous state (None in this test context).
        from app.context import _request_id

        _request_id.reset(token)
    assert current_request_id() is None
