"""hCaptcha verification.

When secret is empty, `required` is False and `verify` always returns True.
"""
from __future__ import annotations

import logging

import aiohttp

log = logging.getLogger(__name__)

_VERIFY_URL = "https://api.hcaptcha.com/siteverify"


class CaptchaVerifier:
    def __init__(
        self,
        *,
        secret: str,
        verify_url: str = _VERIFY_URL,
    ) -> None:
        self.secret = secret
        self.verify_url = verify_url

    @property
    def required(self) -> bool:
        return bool(self.secret)

    async def verify(self, token: str, *, remote_ip: str | None = None) -> bool:
        if not self.required:
            return True
        if not token:
            return False
        data = {"secret": self.secret, "response": token}
        if remote_ip:
            data["remoteip"] = remote_ip
        try:
            async with aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=10)
            ) as s, s.post(self.verify_url, data=data) as resp:
                if resp.status >= 400:
                    log.warning("hcaptcha: HTTP %d", resp.status)
                    return False
                body = await resp.json()
                return bool(body.get("success", False))
        except Exception:
            log.exception("hcaptcha: verify failed")
            return False
