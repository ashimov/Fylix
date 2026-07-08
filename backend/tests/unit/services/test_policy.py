from unittest.mock import AsyncMock

import pytest

from app.schemas.transfer import FileDescriptor
from app.services.policy import PolicyViolation, UploadPolicy
from app.services.settings_service import SettingsService


@pytest.fixture
def policy_stub(monkeypatch) -> UploadPolicy:
    ss = SettingsService()
    ss.get_int = AsyncMock(side_effect=lambda s, k, d: {
        "max_transfer_size_gb": 2,
        "max_recipients": 20,
    }.get(k, d))
    ss.get_list = AsyncMock(side_effect=lambda s, k, d: {
        "extension_blacklist": [".exe", ".bat", ".scr"],
    }.get(k, d))
    return UploadPolicy(ss)


@pytest.mark.asyncio
async def test_happy_path(policy_stub: UploadPolicy) -> None:
    await policy_stub.check(
        session=None,  # stubbed service doesn't touch it
        files=[FileDescriptor(filename="a.pdf", size=1024)],
        recipient_count=1,
    )


@pytest.mark.asyncio
async def test_rejects_blacklisted_extension(policy_stub: UploadPolicy) -> None:
    with pytest.raises(PolicyViolation, match=".exe"):
        await policy_stub.check(
            session=None,
            files=[FileDescriptor(filename="payload.EXE", size=1024)],
            recipient_count=1,
        )


@pytest.mark.asyncio
async def test_rejects_size_over_limit(policy_stub: UploadPolicy) -> None:
    gb = 1024 * 1024 * 1024
    with pytest.raises(PolicyViolation, match="2 GB"):
        await policy_stub.check(
            session=None,
            files=[FileDescriptor(filename="big.bin", size=3 * gb)],
            recipient_count=1,
        )


@pytest.mark.asyncio
async def test_rejects_too_many_recipients(policy_stub: UploadPolicy) -> None:
    with pytest.raises(PolicyViolation, match="max 20"):
        await policy_stub.check(
            session=None,
            files=[FileDescriptor(filename="a.txt", size=1)],
            recipient_count=21,
        )


@pytest.mark.asyncio
async def test_status_codes_match_violation_type(policy_stub: UploadPolicy) -> None:
    # Size → 413
    try:
        await policy_stub.check(
            session=None,
            files=[FileDescriptor(filename="big", size=999 * 1024 * 1024 * 1024)],
            recipient_count=1,
        )
    except PolicyViolation as e:
        assert e.status_code == 413

    # Extension → 422
    try:
        await policy_stub.check(
            session=None,
            files=[FileDescriptor(filename="x.bat", size=1)],
            recipient_count=1,
        )
    except PolicyViolation as e:
        assert e.status_code == 422
