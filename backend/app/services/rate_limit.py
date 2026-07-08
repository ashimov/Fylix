"""Redis-based rate limiter using atomic INCR + EXPIRE via Lua.

Returns (allowed: bool, remaining: int). Emits `window_reset_seconds` via a
second return value so middleware can send Retry-After.
"""
from __future__ import annotations

from dataclasses import dataclass

from redis.asyncio import Redis


_LUA = """
local c = redis.call('INCR', KEYS[1])
if c == 1 then
  redis.call('EXPIRE', KEYS[1], ARGV[2])
end
local ttl = redis.call('TTL', KEYS[1])
if c > tonumber(ARGV[1]) then
  return {0, 0, ttl}
else
  return {1, tonumber(ARGV[1]) - c, ttl}
end
"""


@dataclass
class RateCheck:
    allowed: bool
    remaining: int
    retry_after: int  # seconds until key expiry


class RateLimiter:
    def __init__(self, redis: Redis) -> None:
        self.redis = redis
        self._script = redis.register_script(_LUA)

    async def consume(self, key: str, *, limit: int, window_seconds: int) -> RateCheck:
        result = await self._script(keys=[key], args=[limit, window_seconds])
        allowed, remaining, ttl = result
        return RateCheck(
            allowed=bool(int(allowed)),
            remaining=int(remaining),
            retry_after=max(int(ttl), 0),
        )
