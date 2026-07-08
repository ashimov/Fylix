import pytest
from pydantic import ValidationError

from app.schemas.transfer import CreateTransferRequest, FileDescriptor


def test_create_transfer_request_happy_path() -> None:
    req = CreateTransferRequest(
        sender_email="a@b.co",
        recipient_emails=["x@y.co"],
        message="hi",
        ttl_days=7,
        files=[FileDescriptor(filename="a.pdf", size=1024)],
    )
    assert req.total_size == 1024
    assert req.file_count == 1


def test_rejects_invalid_sender_email() -> None:
    with pytest.raises(ValidationError):
        CreateTransferRequest(
            sender_email="not-an-email",
            recipient_emails=["x@y.co"],
            ttl_days=7,
            files=[FileDescriptor(filename="a.pdf", size=1)],
        )


def test_rejects_empty_files_list() -> None:
    with pytest.raises(ValidationError, match="at least 1"):
        CreateTransferRequest(
            sender_email="a@b.co",
            recipient_emails=["x@y.co"],
            ttl_days=7,
            files=[],
        )


def test_rejects_too_many_recipients() -> None:
    with pytest.raises(ValidationError):
        CreateTransferRequest(
            sender_email="a@b.co",
            recipient_emails=[f"u{i}@y.co" for i in range(21)],
            ttl_days=7,
            files=[FileDescriptor(filename="a", size=1)],
        )


def test_rejects_message_too_long() -> None:
    with pytest.raises(ValidationError):
        CreateTransferRequest(
            sender_email="a@b.co",
            recipient_emails=["x@y.co"],
            message="x" * 2001,
            ttl_days=7,
            files=[FileDescriptor(filename="a", size=1)],
        )


def test_ttl_bounds() -> None:
    with pytest.raises(ValidationError):
        CreateTransferRequest(
            sender_email="a@b.co",
            recipient_emails=["x@y.co"],
            ttl_days=0,
            files=[FileDescriptor(filename="a", size=1)],
        )


def test_dedups_recipient_emails_case_insensitive() -> None:
    req = CreateTransferRequest(
        sender_email="a@b.co",
        recipient_emails=["x@y.co", "X@Y.CO", "z@y.co"],
        ttl_days=1,
        files=[FileDescriptor(filename="a", size=1)],
    )
    # Case-insensitive dedup; preserve first-seen casing and order.
    emails = [str(e) for e in req.recipient_emails]
    assert len(emails) == 2
    assert emails[0].lower() == "x@y.co"
    assert emails[1].lower() == "z@y.co"
