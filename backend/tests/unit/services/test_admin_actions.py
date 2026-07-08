from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from app.services.admin_actions import record


@pytest.mark.asyncio
async def test_record_calls_session_add_with_expected_row() -> None:
    session = MagicMock()
    session.add = MagicMock()
    admin_id = uuid4()

    await record(
        session,
        admin_id=admin_id,
        action="delete_transfer",
        target_type="transfer",
        target_id="abc-123",
        ip="203.0.113.5",
        details={"reason": "abuse"},
    )

    session.add.assert_called_once()
    row = session.add.call_args[0][0]
    assert row.admin_id == admin_id
    assert row.action == "delete_transfer"
    assert row.target_type == "transfer"
    assert row.target_id == "abc-123"
    assert str(row.ip) == "203.0.113.5"
    assert row.details == {"reason": "abuse"}


@pytest.mark.asyncio
async def test_record_with_minimal_fields() -> None:
    session = MagicMock()
    session.add = MagicMock()
    await record(session, admin_id=uuid4(), action="login")
    row = session.add.call_args[0][0]
    assert row.target_type is None
    assert row.target_id is None
    assert row.ip is None
    assert row.details is None
