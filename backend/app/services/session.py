"""Redis-backed session store for admin auth.

Session key layout:
  session:{sid} → JSON { admin_id, issued_at, last_active }
  admin_sessions:{admin_id} → set of sid's (so we can revoke all sessions
                                            for an admin in one call)

Both keys share the same TTL. `touch()` refreshes the TTL of session:{sid}
but NOT the set — the set is rebuilt on the next create, and stale sid
entries are swept out by destroy_all_for. (We could add a side-index TTL
but the sweep-on-use approach is sufficient here.)

Session identity protection relies on:
  - session_id: 32-byte random token (256 bits of entropy)
  - Cookie flags: Secure + HttpOnly + SameSite=Strict
  - 30-minute sliding TTL
  - CSRF double-submit on mutating endpoints
  - Nginx CIDR allow-list for /admin paths (corp network only in prod)

A prior ua_hash binding was removed — it hashed the client-observable
User-Agent with plain SHA-256, which gives zero real protection against
an attacker who has the cookie (they got it from the same HTTP request
flow and therefore have the UA too) while causing false-positive
logouts on routine browser updates. Legacy session JSON blobs that
still contain an ua_hash key continue to load cleanly; the field is
simply ignored.
"""

from __future__ import annotations

import json
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from redis.asyncio import Redis


def _sid() -> str:
    return secrets.token_urlsafe(32)


@dataclass
class SessionData:
    admin_id: UUID
    issued_at: datetime
    last_active: datetime


class SessionStore:
    def __init__(self, redis: Redis, *, ttl_seconds: int) -> None:
        self.redis = redis
        self.ttl_seconds = ttl_seconds

    @staticmethod
    def _session_key(sid: str) -> str:
        return f"session:{sid}"

    @staticmethod
    def _index_key(admin_id: UUID) -> str:
        return f"admin_sessions:{admin_id}"

    async def create(self, *, admin_id: UUID) -> str:
        sid = _sid()
        now = datetime.now(UTC)
        payload = {
            "admin_id": str(admin_id),
            "issued_at": now.isoformat(),
            "last_active": now.isoformat(),
        }
        pipe = self.redis.pipeline()
        pipe.set(self._session_key(sid), json.dumps(payload), ex=self.ttl_seconds)
        pipe.sadd(self._index_key(admin_id), sid)
        pipe.expire(self._index_key(admin_id), self.ttl_seconds)
        await pipe.execute()
        return sid

    async def load(self, sid: str) -> SessionData | None:
        raw = await self.redis.get(self._session_key(sid))
        if raw is None:
            return None
        data = json.loads(raw)
        return SessionData(
            admin_id=UUID(data["admin_id"]),
            issued_at=datetime.fromisoformat(data["issued_at"]),
            last_active=datetime.fromisoformat(data["last_active"]),
        )

    async def touch(self, sid: str) -> bool:
        key = self._session_key(sid)
        raw = await self.redis.get(key)
        if raw is None:
            return False
        data = json.loads(raw)
        data["last_active"] = datetime.now(UTC).isoformat()

        # Refresh BOTH the session and the admin's session-index set, so a
        # subsequent destroy_all_for() still sees every live session.
        admin_id = data.get("admin_id")
        pipe = self.redis.pipeline()
        pipe.set(key, json.dumps(data), ex=self.ttl_seconds)
        if admin_id:
            pipe.expire(self._index_key(UUID(admin_id)), self.ttl_seconds)
        await pipe.execute()
        return True

    async def destroy(self, sid: str) -> None:
        # Load first to know which admin's index to clean up.
        raw = await self.redis.get(self._session_key(sid))
        if raw is not None:
            data = json.loads(raw)
            admin_id = UUID(data["admin_id"])
            pipe = self.redis.pipeline()
            pipe.delete(self._session_key(sid))
            pipe.srem(self._index_key(admin_id), sid)
            await pipe.execute()
        else:
            await self.redis.delete(self._session_key(sid))

    async def destroy_all_for(self, admin_id: UUID) -> int:
        members = await self.redis.smembers(self._index_key(admin_id))  # type: ignore[misc]
        if not members:
            return 0
        sid_keys = [self._session_key(m.decode() if isinstance(m, bytes) else m) for m in members]
        pipe = self.redis.pipeline()
        pipe.delete(*sid_keys)
        pipe.delete(self._index_key(admin_id))
        await pipe.execute()
        return len(members)
