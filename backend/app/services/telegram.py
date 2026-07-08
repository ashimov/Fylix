"""Async Telegram bot client for admin alerts.

Gracefully becomes a no-op when bot token or chat id is empty (dev default).
"""

from __future__ import annotations

import logging

import aiohttp

log = logging.getLogger(__name__)


class TelegramClient:
    def __init__(
        self,
        *,
        bot_token: str,
        chat_id: str,
        base_url: str = "https://api.telegram.org",
    ) -> None:
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.base_url = base_url.rstrip("/")

    @property
    def enabled(self) -> bool:
        return bool(self.bot_token and self.chat_id)

    async def send(
        self,
        text: str,
        *,
        parse_mode: str = "Markdown",
        disable_web_preview: bool = True,
    ) -> None:
        if not self.enabled:
            log.debug("telegram: disabled, skipping send")
            return
        url = f"{self.base_url}/bot{self.bot_token}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": disable_web_preview,
        }
        async with (
            aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session,
            session.post(url, json=payload) as resp,
        ):
            body = await resp.text()
            if resp.status >= 400:
                log.warning("telegram: sendMessage failed %d: %s", resp.status, body)
