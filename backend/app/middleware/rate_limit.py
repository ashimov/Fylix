"""HawkAPI middleware applying rate-limits to specific paths.

Limits are read live from the settings table (with a short in-process cache)
so that changes via PATCH /api/admin/settings take effect without a restart.

  - POST /api/transfers            : upload hourly + upload daily
  - PATCH /api/transfers/.../files/... : NOT rate-limited (part of upload)
  - GET /t/{token}/file/...        : download hourly per IP
  - GET /t/{token}/zip             : download hourly per IP
  - GET /t/{token}                 : not rate-limited (static page)

Returns 429 with Retry-After when exceeded, and writes an audit event.

Implementation: overrides the raw ASGI `__call__` so the non-limited
fast path is pure pass-through (no response-body buffering) — critical
for the large streamed download responses flowing through this stack.
"""

from __future__ import annotations

import logging
import re
import time
from typing import Any

from hawkapi._types import ASGIApp, Receive, Scope, Send
from hawkapi.middleware import Middleware
from hawkapi.responses import JSONResponse

from app.services.rate_limit import RateLimiter
from app.services.settings_service import SettingsService
from app.utils.http import client_ip_from_scope

log = logging.getLogger(__name__)


_UPLOAD_CREATE_RE = re.compile(r"^/api/transfers/?$")
_DOWNLOAD_RE = re.compile(r"^/t/[^/]+/(file/[^/]+|zip)/?$")

_KEY_UPLOAD_HOURLY = "rate_hourly"
_KEY_UPLOAD_DAILY = "rate_daily"
_KEY_DOWNLOAD_HOURLY = "rate_download_hourly"

_DEFAULT_UPLOAD_HOURLY = 10
_DEFAULT_UPLOAD_DAILY = 100
_DEFAULT_DOWNLOAD_HOURLY = 30


class RateLimitMiddleware(Middleware):
    def __init__(
        self,
        app: ASGIApp,
        *,
        limiter: RateLimiter,
        session_factory: Any,
        settings_service: SettingsService,
        cache_ttl_seconds: int = 10,
    ) -> None:
        super().__init__(app)
        self.limiter = limiter
        self.session_factory = session_factory
        self.settings_service = settings_service
        # key → (value, expires_at_monotonic)
        self._cache: dict[str, tuple[int, float]] = {}
        self._cache_ttl = cache_ttl_seconds

    async def _get_int_cached(self, key: str, default: int) -> int:
        now = time.monotonic()
        cached = self._cache.get(key)
        if cached and cached[1] > now:
            return cached[0]
        async with self.session_factory() as session:
            v = await self.settings_service.get_int(session, key, default)
        self._cache[key] = (v, now + self._cache_ttl)
        return v

    @staticmethod
    def _classify(method: str, path: str) -> str | None:
        if method == "POST" and _UPLOAD_CREATE_RE.match(path):
            return "upload"
        if method == "GET" and _DOWNLOAD_RE.match(path):
            return "download"
        return None

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        method = scope.get("method", "").upper()
        path = scope.get("path", "")
        action = self._classify(method, path)
        if action is None:
            await self.app(scope, receive, send)
            return

        ip = client_ip_from_scope(scope)

        if action == "upload":
            upload_hourly = await self._get_int_cached(_KEY_UPLOAD_HOURLY, _DEFAULT_UPLOAD_HOURLY)
            upload_daily = await self._get_int_cached(_KEY_UPLOAD_DAILY, _DEFAULT_UPLOAD_DAILY)
            policy = [
                (f"rl:u:h:{ip}", upload_hourly, 3600),
                (f"rl:u:d:{ip}", upload_daily, 86400),
            ]
        else:  # download
            download_hourly = await self._get_int_cached(
                _KEY_DOWNLOAD_HOURLY, _DEFAULT_DOWNLOAD_HOURLY
            )
            policy = [(f"rl:d:h:{ip}", download_hourly, 3600)]

        for key, limit, window in policy:
            check = await self.limiter.consume(key, limit=limit, window_seconds=window)
            if not check.allowed:
                log.warning("rate-limit: IP=%s hit key=%s", ip, key)
                response = JSONResponse(
                    {"error": "rate_limit_exceeded"},
                    status_code=429,
                    headers={"Retry-After": str(check.retry_after)},
                )
                await response(scope, receive, send)
                return

        await self.app(scope, receive, send)
