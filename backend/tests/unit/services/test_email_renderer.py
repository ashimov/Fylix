from datetime import datetime, timezone

from app.services.email import EmailRenderer, Locale


def test_render_recipient_ru_contains_download_link() -> None:
    r = EmailRenderer()
    out = r.render_recipient(
        Locale.RU,
        sender_email="alice@example.com",
        message="смотрите файлы",
        download_url="https://example.com/t/abc123",
        file_count=2,
        total_bytes=1024 * 1024,
        expires_at=datetime(2026, 4, 20, 12, 0, tzinfo=timezone.utc),
    )
    assert out.subject
    assert "https://example.com/t/abc123" in out.html
    assert "alice@example.com" in out.html
    assert out.text


def test_render_recipient_en() -> None:
    r = EmailRenderer()
    out = r.render_recipient(
        Locale.EN,
        sender_email="a@b.co",
        message=None,
        download_url="https://x",
        file_count=1,
        total_bytes=1,
        expires_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    assert "https://x" in out.html
    assert out.subject


def test_render_recipient_kk() -> None:
    r = EmailRenderer()
    out = r.render_recipient(
        Locale.KK,
        sender_email="a@b.co",
        message=None,
        download_url="https://x",
        file_count=1,
        total_bytes=1,
        expires_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    assert "https://x" in out.html


def test_render_sender_confirm_ru() -> None:
    r = EmailRenderer()
    out = r.render_sender_confirm(
        Locale.RU,
        download_url="https://example.com/t/x",
        recipients=["a@b.co"],
        file_count=1,
        expires_at=datetime(2026, 4, 20, tzinfo=timezone.utc),
    )
    assert "https://example.com/t/x" in out.html
    assert "a@b.co" in out.html
    # Sender-panel link removed — no /s/ URLs should appear.
    assert "/s/" not in out.html


def test_render_download_notice_kz() -> None:
    r = EmailRenderer()
    out = r.render_download_notice(
        Locale.KK,
        download_ip="203.0.113.5",
        download_country="KZ",
        file_count=1,
        at=datetime(2026, 4, 14, 9, 0, tzinfo=timezone.utc),
    )
    assert "203.0.113.5" in out.text
    assert "KZ" in out.html or "KZ" in out.text


def test_render_download_notice_handles_unknown_country() -> None:
    r = EmailRenderer()
    out = r.render_download_notice(
        Locale.RU,
        download_ip="10.0.0.1",
        download_country=None,
        file_count=1,
        at=datetime(2026, 4, 14, tzinfo=timezone.utc),
    )
    assert "10.0.0.1" in out.text


def test_text_is_html_stripped() -> None:
    r = EmailRenderer()
    out = r.render_recipient(
        Locale.RU,
        sender_email="a@b.co", message=None,
        download_url="https://x", file_count=1, total_bytes=1,
        expires_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    assert "<" not in out.text
    assert ">" not in out.text
