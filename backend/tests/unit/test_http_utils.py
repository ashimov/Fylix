"""RFC 5987 / 6266 Content-Disposition helper — survives non-ASCII filenames
and rejects header-injection via stray `"` / CR / LF in the quoted-string.

Also covers the `client_ip` helper that reads X-Forwarded-For with a
fallback to `request.client.host`.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from app.utils.http import client_ip, content_disposition_attachment


def _fake_request(*, xff: str | None = None, host: str | None = "1.2.3.4") -> Any:
    """Build a duck-typed Request with just the two attributes client_ip reads."""
    client = SimpleNamespace(host=host) if host is not None else None
    headers = {"x-forwarded-for": xff} if xff is not None else {}
    return SimpleNamespace(headers=headers, client=client)


def _fake_request_no_client(*, xff: str | None = None) -> Any:
    headers = {"x-forwarded-for": xff} if xff is not None else {}
    return SimpleNamespace(headers=headers, client=None)


def test_ascii_only_filename_produces_both_filename_and_filename_star() -> None:
    header = content_disposition_attachment("report.pdf")
    assert 'filename="report.pdf"' in header
    assert "filename*=UTF-8''report.pdf" in header
    assert header.startswith("attachment; ")


def test_cyrillic_filename_percent_encodes_utf8_in_filename_star() -> None:
    header = content_disposition_attachment("отчёт.pdf")
    assert "filename*=UTF-8''%D0%BE%D1%82%D1%87%D1%91%D1%82.pdf" in header


def test_cyrillic_filename_provides_ascii_fallback() -> None:
    header = content_disposition_attachment("отчёт.pdf")
    assert 'filename="_____.pdf"' in header


def test_filename_with_quote_is_neutralised_in_ascii_fallback() -> None:
    """`"` cannot appear inside filename="..." without breaking the header.
    Our helper replaces non-safe ASCII with `_` in the fallback derivation."""
    header = content_disposition_attachment('evil".pdf')
    # Fallback: `evil".pdf` -> non-safe `"` becomes `_`.
    assert 'filename="evil_.pdf"' in header
    # And no bare " remains in the quoted segment.
    quoted_segment = header.split("filename*=")[0]
    assert quoted_segment.count('"') == 2  # only the pair wrapping the fallback


def test_filename_with_crlf_is_stripped_from_ascii_fallback() -> None:
    """CR/LF in a header is a classic response-splitting vector."""
    header = content_disposition_attachment("evil\r\nX-Injected: yes.pdf")
    assert "\r" not in header
    assert "\n" not in header


def test_explicit_ascii_fallback_used_verbatim() -> None:
    header = content_disposition_attachment("отчёт.pdf", ascii_fallback="report.pdf")
    assert 'filename="report.pdf"' in header
    assert "filename*=UTF-8''%D0%BE%D1%82%D1%87%D1%91%D1%82.pdf" in header


def test_explicit_ascii_fallback_also_strips_crlf() -> None:
    header = content_disposition_attachment("ok.pdf", ascii_fallback='dangerous".pdf\r\nX: y')
    assert "\r" not in header
    assert "\n" not in header


def test_empty_filename_falls_back_to_literal_file() -> None:
    header = content_disposition_attachment("")
    assert 'filename="file"' in header
    assert "filename*=UTF-8''" in header


def test_filename_with_space_is_preserved_in_ascii_fallback() -> None:
    header = content_disposition_attachment("my report.pdf")
    assert 'filename="my report.pdf"' in header
    assert "filename*=UTF-8''my%20report.pdf" in header


def test_cjk_filename_encodes_correctly() -> None:
    header = content_disposition_attachment("文件.pdf")
    assert "filename*=UTF-8''%E6%96%87%E4%BB%B6.pdf" in header


# --- client_ip -----------------------------------------------------------


def test_client_ip_uses_first_xff_when_present() -> None:
    req = _fake_request(xff="198.51.100.10", host="10.0.0.5")
    assert client_ip(req) == "198.51.100.10"


def test_client_ip_strips_whitespace_from_first_xff_hop() -> None:
    req = _fake_request(xff="  198.51.100.10 ,10.0.0.5", host="10.0.0.5")
    assert client_ip(req) == "198.51.100.10"


def test_client_ip_falls_back_to_request_client_host_without_xff() -> None:
    req = _fake_request(xff=None, host="10.0.0.5")
    assert client_ip(req) == "10.0.0.5"


def test_client_ip_returns_0_0_0_0_when_no_client_and_no_xff() -> None:
    req = _fake_request_no_client(xff=None)
    assert client_ip(req) == "0.0.0.0"
