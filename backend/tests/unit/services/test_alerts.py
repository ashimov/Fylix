from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.alerts import AlertDispatcher
from app.services.telegram import TelegramClient


@pytest.mark.asyncio
async def test_low_severity_writes_audit_not_telegram() -> None:
    tg = TelegramClient(bot_token="x", chat_id="y", base_url="http://nope")
    tg.send = AsyncMock()  # type: ignore[method-assign]
    disp = AlertDispatcher(tg)

    session = MagicMock()
    session.add = MagicMock()
    session.commit = AsyncMock()

    await disp.alert(
        session,
        event_type="upload_complete",
        severity="info",
        message="done",
    )
    session.add.assert_called_once()
    tg.send.assert_not_called()


@pytest.mark.asyncio
async def test_critical_severity_sends_telegram() -> None:
    tg = TelegramClient(bot_token="x", chat_id="y", base_url="http://nope")
    tg.send = AsyncMock()  # type: ignore[method-assign]
    disp = AlertDispatcher(tg)

    session = MagicMock()
    session.add = MagicMock()
    session.commit = AsyncMock()

    await disp.alert(
        session,
        event_type="infected_file",
        severity="critical",
        message="quarantined",
        details={"file": "x.exe"},
    )
    session.add.assert_called_once()
    tg.send.assert_awaited_once()


@pytest.mark.asyncio
async def test_telegram_failure_is_non_fatal() -> None:
    tg = TelegramClient(bot_token="x", chat_id="y", base_url="http://nope")
    tg.send = AsyncMock(side_effect=RuntimeError("boom"))  # type: ignore[method-assign]
    disp = AlertDispatcher(tg)

    session = MagicMock()
    session.add = MagicMock()
    session.commit = AsyncMock()

    # Must NOT raise despite TG failure
    await disp.alert(
        session,
        event_type="rate_limit_spike",
        severity="error",
        message="flood",
    )
    session.add.assert_called_once()
