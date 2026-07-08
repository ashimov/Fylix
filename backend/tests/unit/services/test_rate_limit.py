import pytest
from redis.asyncio import Redis
from testcontainers.redis import RedisContainer  # type: ignore[import-untyped]

from app.services.rate_limit import RateLimiter


@pytest.fixture(scope="module")
def redis_container():
    with RedisContainer("redis:7-alpine") as r:
        yield r


@pytest.fixture
async def redis_client(redis_container):
    host = redis_container.get_container_host_ip()
    port = int(redis_container.get_exposed_port(6379))
    r = Redis(host=host, port=port, decode_responses=False)
    yield r
    await r.flushdb()
    await r.aclose()


@pytest.mark.asyncio
async def test_consume_allows_within_limit(redis_client: Redis) -> None:
    rl = RateLimiter(redis_client)
    for i in range(5):
        result = await rl.consume("test:1", limit=5, window_seconds=60)
        assert result.allowed is True
        assert result.remaining == 4 - i


@pytest.mark.asyncio
async def test_consume_blocks_past_limit(redis_client: Redis) -> None:
    rl = RateLimiter(redis_client)
    for _ in range(3):
        await rl.consume("test:2", limit=3, window_seconds=60)
    result = await rl.consume("test:2", limit=3, window_seconds=60)
    assert result.allowed is False
    assert result.retry_after > 0


@pytest.mark.asyncio
async def test_consume_different_keys_independent(redis_client: Redis) -> None:
    rl = RateLimiter(redis_client)
    for _ in range(3):
        await rl.consume("test:3a", limit=3, window_seconds=60)
    # exhausted on 3a, but 3b is fresh
    r = await rl.consume("test:3b", limit=3, window_seconds=60)
    assert r.allowed
