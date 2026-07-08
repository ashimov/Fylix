import logging

import pytest
from pytest_httpserver import HTTPServer  # type: ignore[import-untyped]

from app.services.telegram import TelegramClient


def test_disabled_is_noop() -> None:
    c = TelegramClient(bot_token="", chat_id="")
    assert c.enabled is False


@pytest.mark.asyncio
async def test_enabled_posts_to_sendMessage(httpserver: HTTPServer) -> None:
    httpserver.expect_request(
        "/bottok-123/sendMessage", method="POST"
    ).respond_with_json({"ok": True})

    c = TelegramClient(
        bot_token="tok-123",
        chat_id="42",
        base_url=httpserver.url_for(""),
    )
    assert c.enabled
    await c.send("hello")

    # Assert the request body had expected fields
    assert len(httpserver.log) == 1
    req, _ = httpserver.log[0]
    data = req.get_json()
    assert data["chat_id"] == "42"
    assert data["text"] == "hello"


@pytest.mark.asyncio
async def test_send_handles_error_response(httpserver: HTTPServer, caplog) -> None:
    httpserver.expect_request("/bot-x/sendMessage", method="POST").respond_with_data(
        "forbidden", status=403
    )
    c = TelegramClient(
        bot_token="-x",
        chat_id="1",
        base_url=httpserver.url_for(""),
    )
    caplog.set_level(logging.WARNING, logger="app.services.telegram")
    # Should NOT raise — just log the failure.
    await c.send("test")
    assert any("sendMessage failed" in r.getMessage() for r in caplog.records)
