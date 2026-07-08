import pytest
from pytest_httpserver import HTTPServer

from app.services.captcha import CaptchaVerifier


def test_disabled_when_secret_empty() -> None:
    c = CaptchaVerifier(secret="")
    assert c.required is False


@pytest.mark.asyncio
async def test_disabled_always_returns_true() -> None:
    c = CaptchaVerifier(secret="")
    assert await c.verify("") is True
    assert await c.verify("any-token") is True


@pytest.mark.asyncio
async def test_empty_token_when_required_returns_false() -> None:
    c = CaptchaVerifier(secret="s")
    assert await c.verify("") is False


@pytest.mark.asyncio
async def test_successful_verification(httpserver: HTTPServer) -> None:
    httpserver.expect_request("/verify", method="POST").respond_with_json(
        {
            "success": True,
            "challenge_ts": "2026-04-14T00:00:00Z",
        }
    )
    c = CaptchaVerifier(secret="s", verify_url=httpserver.url_for("/verify"))
    assert await c.verify("valid-token", remote_ip="1.2.3.4") is True
    assert len(httpserver.log) == 1
    req, _ = httpserver.log[0]
    assert req.form["secret"] == "s"
    assert req.form["response"] == "valid-token"
    assert req.form["remoteip"] == "1.2.3.4"


@pytest.mark.asyncio
async def test_failed_verification(httpserver: HTTPServer) -> None:
    httpserver.expect_request("/verify", method="POST").respond_with_json(
        {
            "success": False,
            "error-codes": ["invalid-input-response"],
        }
    )
    c = CaptchaVerifier(secret="s", verify_url=httpserver.url_for("/verify"))
    assert await c.verify("bad-token") is False


@pytest.mark.asyncio
async def test_network_error_returns_false(httpserver: HTTPServer) -> None:
    c = CaptchaVerifier(secret="s", verify_url="http://127.0.0.1:1/nonexistent")
    assert await c.verify("token") is False
