import pytest
from hawkapi import HawkAPI
from hawkapi.testing import TestClient
from hawkapi.responses import JSONResponse

from app.middleware.csrf import CsrfMiddleware


def _build_app() -> HawkAPI:
    app = HawkAPI()
    app.add_middleware(CsrfMiddleware, protect_prefix="/api/admin", cookie_name="csrf")

    @app.post("/api/admin/do")
    def do() -> JSONResponse:
        return JSONResponse({"ok": True})

    @app.get("/api/admin/do")
    def get_do() -> JSONResponse:
        return JSONResponse({"ok": True})

    @app.post("/api/admin/login")
    def login() -> JSONResponse:
        return JSONResponse({"ok": True})

    @app.post("/api/public")
    def pub() -> JSONResponse:
        return JSONResponse({"ok": True})

    return app


@pytest.fixture(autouse=True)
def _insecure_cookies(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unit tests run over plain HTTP via TestClient; disable Secure flag so
    cookies are echoed back on subsequent requests."""
    import app.middleware.csrf as csrf_mod
    import app.config as config_mod
    monkeypatch.setattr(config_mod.settings, "dev_insecure_cookies", True)
    monkeypatch.setattr(csrf_mod.settings, "dev_insecure_cookies", True)


def test_first_admin_get_mints_cookie() -> None:
    client = TestClient(_build_app())
    r = client.get("/api/admin/do")
    assert r.status_code == 200
    assert "csrf" in r.cookies


def test_admin_post_without_token_rejected() -> None:
    client = TestClient(_build_app())
    client.get("/api/admin/do")  # mint cookie
    # Now try a POST without X-CSRF-Token header
    r = client.post("/api/admin/do")
    assert r.status_code == 403
    assert r.json()["detail"]["error"] == "csrf"


def test_admin_post_with_matching_token_passes() -> None:
    client = TestClient(_build_app())
    g = client.get("/api/admin/do")
    token = g.cookies["csrf"]
    r = client.post("/api/admin/do", headers={"X-CSRF-Token": token})
    assert r.status_code == 200


def test_admin_post_with_mismatched_token_rejected() -> None:
    client = TestClient(_build_app())
    client.get("/api/admin/do")
    r = client.post("/api/admin/do", headers={"X-CSRF-Token": "wrong"})
    assert r.status_code == 403


def test_admin_login_is_exempt_from_csrf() -> None:
    # Login doesn't have a prior cookie; it must accept POST without header.
    client = TestClient(_build_app())
    r = client.post("/api/admin/login")
    assert r.status_code == 200


def test_non_admin_post_is_unaffected() -> None:
    client = TestClient(_build_app())
    r = client.post("/api/public")
    assert r.status_code == 200


def test_get_never_checks_csrf() -> None:
    client = TestClient(_build_app())
    r = client.get("/api/admin/do")
    assert r.status_code == 200
