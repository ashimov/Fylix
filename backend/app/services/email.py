"""Email rendering service.

Jinja2-templated HTML + plain-text emails for the three user-facing flows:
recipient notification, sender confirmation, sender download notice.

Subjects are hard-coded per (locale, kind) since they don't need template logic.
"""
from __future__ import annotations

import enum
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from jinja2 import Environment, PackageLoader, select_autoescape


class Locale(str, enum.Enum):
    RU = "ru"
    KK = "kk"
    EN = "en"


@dataclass
class RenderedEmail:
    subject: str
    html: str
    text: str


_SUBJECTS: dict[Locale, dict[str, str]] = {
    Locale.RU: {
        "recipient": "Вам отправили файлы — Fylix",
        "sender_confirm": "Файлы загружены — Fylix",
        "sender_download_notice": "Ваши файлы скачали — Fylix",
    },
    Locale.KK: {
        "recipient": "Сізге файлдар жіберілді — Fylix",
        "sender_confirm": "Файлдар жүктелді — Fylix",
        "sender_download_notice": "Файлдарыңыз жүктеп алынды — Fylix",
    },
    Locale.EN: {
        "recipient": "Files have been sent to you — Fylix",
        "sender_confirm": "Your transfer is ready — Fylix",
        "sender_download_notice": "Your files were downloaded — Fylix",
    },
}


class EmailRenderer:
    def __init__(self) -> None:
        self._env = Environment(
            loader=PackageLoader("app.services", "templates"),
            autoescape=select_autoescape(["html", "xml"]),
            trim_blocks=True,
            lstrip_blocks=True,
        )

    def _render_html(self, template: str, ctx: dict[str, Any]) -> str:
        return self._env.get_template(template).render(**ctx)

    def render_recipient(
        self,
        locale: Locale,
        *,
        sender_email: str,
        message: str | None,
        download_url: str,
        file_count: int,
        total_bytes: int,
        expires_at: datetime,
    ) -> RenderedEmail:
        ctx = dict(
            sender_email=sender_email,
            message=message,
            download_url=download_url,
            file_count=file_count,
            total_mb=f"{total_bytes / (1024 * 1024):.1f}",
            expires_at=expires_at.strftime("%Y-%m-%d %H:%M UTC"),
        )
        html = self._render_html(f"recipient.{locale.value}.html", ctx)
        return RenderedEmail(
            subject=_SUBJECTS[locale]["recipient"],
            html=html,
            text=_strip_html(html),
        )

    def render_sender_confirm(
        self,
        locale: Locale,
        *,
        download_url: str,
        recipients: list[str],
        file_count: int,
        expires_at: datetime,
    ) -> RenderedEmail:
        ctx = dict(
            download_url=download_url,
            recipients=recipients,
            file_count=file_count,
            expires_at=expires_at.strftime("%Y-%m-%d %H:%M UTC"),
        )
        html = self._render_html(f"sender_confirm.{locale.value}.html", ctx)
        return RenderedEmail(
            subject=_SUBJECTS[locale]["sender_confirm"],
            html=html,
            text=_strip_html(html),
        )

    def render_download_notice(
        self,
        locale: Locale,
        *,
        download_ip: str,
        download_country: str | None,
        file_count: int,
        at: datetime,
    ) -> RenderedEmail:
        ctx = dict(
            download_ip=download_ip,
            download_country=download_country or "—",
            file_count=file_count,
            at=at.strftime("%Y-%m-%d %H:%M UTC"),
        )
        html = self._render_html(f"sender_download_notice.{locale.value}.html", ctx)
        return RenderedEmail(
            subject=_SUBJECTS[locale]["sender_download_notice"],
            html=html,
            text=_strip_html(html),
        )


def _strip_html(html: str) -> str:
    # Replace <br> and </p>/</div> with newlines before stripping.
    html = re.sub(r"</p>|</div>|<br\s*/?>", "\n", html, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", html)
    # Collapse runs of whitespace but keep paragraph breaks.
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n", "\n\n", text)
    return text.strip()


import aiosmtplib  # noqa: E402
from email.message import EmailMessage  # noqa: E402


import ssl  # noqa: E402


class SmtpSender:
    """Async SMTP sender.

    TLS policy:
    - port 465 → implicit TLS (SMTPS)
    - port 587 → STARTTLS upgrade
    - any other port → plaintext (mailpit dev, internal relays without TLS)

    When `verify_cert=False`, certificate validation is disabled — required for
    internal corporate relays that present a cert not matching their IP.
    """

    def __init__(
        self,
        *,
        host: str,
        port: int,
        user: str,
        password: str,
        sender: str,
        verify_cert: bool = True,
    ) -> None:
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.sender = sender
        self.verify_cert = verify_cert

    def _tls_context(self) -> ssl.SSLContext | None:
        if self.verify_cert:
            return None  # aiosmtplib uses the default, validating context
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx

    async def send(self, *, to: str, subject: str, html: str, text: str) -> None:
        msg = EmailMessage()
        msg["From"] = self.sender
        msg["To"] = to
        msg["Subject"] = subject
        msg.set_content(text)
        msg.add_alternative(html, subtype="html")

        use_tls = self.port == 465
        start_tls = self.port == 587
        kwargs: dict = dict(
            hostname=self.host,
            port=self.port,
            username=self.user or None,
            password=self.password or None,
            use_tls=use_tls,
            start_tls=start_tls,
            timeout=30,
        )
        ctx = self._tls_context()
        if ctx is not None and (use_tls or start_tls):
            kwargs["tls_context"] = ctx

        await aiosmtplib.send(msg, **kwargs)
