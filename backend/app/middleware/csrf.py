"""CSRF double-submit cookie middleware for /api/admin/*.

Rules:
- On any response inside the protected prefix, set `csrf` cookie if missing.
  Cookie is Readable-by-JS (HttpOnly=False — the SPA must read it to
  send X-CSRF-Token), Secure, SameSite=Strict.
- On mutating requests (POST/PATCH/PUT/DELETE) inside the protected prefix,
  reject 403 unless the X-CSRF-Token header matches the cookie value.
- Login path is exempt (client has no prior cookie).
- Non-protected paths are unaffected.

Implementation: ASGI `__call__` override so a response that already
carries a Set-Cookie (e.g. session on login) can coexist with the csrf
Set-Cookie — HawkAPI's `dict[str, str]` headers collapse duplicates, so
we append cookies directly to the raw (bytes, bytes) header list on
`http.response.start`.
"""
from __future__ import annotations

import secrets
from typing import Any

from hawkapi._types import ASGIApp, Receive, Scope, Send
from hawkapi.middleware import Middleware
from hawkapi.responses import JSONResponse

from app.config import settings

_MUTATING = frozenset({"POST", "PATCH", "PUT", "DELETE"})


def _parse_cookies(scope: Scope) -> dict[str, str]:
    raw = b""
    for k, v in scope.get("headers", []):
        if k.lower() == b"cookie":
            raw = v
            break
    jar: dict[str, str] = {}
    if not raw:
        return jar
    for item in raw.decode("latin-1").split(";"):
        item = item.strip()
        if not item or "=" not in item:
            continue
        name, _, value = item.partition("=")
        jar[name.strip()] = value.strip()
    return jar


def _get_header(scope: Scope, name_lc: bytes) -> str | None:
    for k, v in scope.get("headers", []):
        if k.lower() == name_lc:
            return v.decode("latin-1")
    return None


def _build_csrf_cookie(name: str, value: str, *, secure: bool) -> bytes:
    parts = [f"{name}={value}", "Max-Age=86400", "Path=/"]
    if secure:
        parts.append("Secure")
    # HttpOnly intentionally omitted — SPA must read the cookie.
    parts.append("SameSite=Strict")
    return "; ".join(parts).encode("latin-1")


class CsrfMiddleware(Middleware):
    def __init__(
        self,
        app: ASGIApp,
        *,
        protect_prefix: str = "/api/admin",
        cookie_name: str = "csrf",
        exempt_paths: tuple[str, ...] = ("/api/admin/login",),
    ) -> None:
        super().__init__(app)
        self.protect_prefix = protect_prefix.rstrip("/")
        self.cookie_name = cookie_name
        self.exempt_paths = exempt_paths

    def _is_protected(self, path: str) -> bool:
        return path == self.protect_prefix or path.startswith(self.protect_prefix + "/")

    def _is_exempt(self, path: str) -> bool:
        return any(path == p or path.startswith(p + "/") for p in self.exempt_paths)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        if not self._is_protected(path):
            await self.app(scope, receive, send)
            return

        method = scope.get("method", "").upper()
        cookies = _parse_cookies(scope)

        if method in _MUTATING and not self._is_exempt(path):
            cookie_val = cookies.get(self.cookie_name)
            header_val = _get_header(scope, b"x-csrf-token")
            if (
                not cookie_val
                or not header_val
                or not secrets.compare_digest(cookie_val, header_val)
            ):
                response = JSONResponse({"detail": {"error": "csrf"}}, status_code=403)
                await response(scope, receive, send)
                return

        if self.cookie_name in cookies:
            await self.app(scope, receive, send)
            return

        token = secrets.token_urlsafe(32)
        secure = not settings.dev_insecure_cookies
        new_cookie_bytes = _build_csrf_cookie(self.cookie_name, token, secure=secure)

        async def send_with_cookie(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.append((b"set-cookie", new_cookie_bytes))
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_cookie)
