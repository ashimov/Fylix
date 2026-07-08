from uuid import uuid4

import pytest
from redis.asyncio import Redis
from testcontainers.redis import RedisContainer  # type: ignore[import-untyped]

from app.services.session import SessionStore


@pytest.fixture(scope="module")
def redis_container():
    with RedisContainer("redis:7-alpine") as c:
        yield c


@pytest.fixture
async def redis_client(redis_container):
    host = redis_container.get_container_host_ip()
    port = int(redis_container.get_exposed_port(6379))
    r = Redis(host=host, port=port, decode_responses=False)
    yield r
    await r.flushdb()
    await r.aclose()


@pytest.fixture
def store(redis_client: Redis) -> SessionStore:
    return SessionStore(redis_client, ttl_seconds=60)


@pytest.mark.asyncio
async def test_create_and_load_roundtrip(store: SessionStore) -> None:
    admin_id = uuid4()
    sid = await store.create(admin_id=admin_id)
    assert isinstance(sid, str) and len(sid) >= 32

    data = await store.load(sid)
    assert data is not None
    assert data.admin_id == admin_id


@pytest.mark.asyncio
async def test_load_unknown_sid_returns_none(store: SessionStore) -> None:
    assert await store.load("not-a-session") is None


@pytest.mark.asyncio
async def test_touch_extends_ttl(redis_client: Redis) -> None:
    store = SessionStore(redis_client, ttl_seconds=60)
    sid = await store.create(admin_id=uuid4())

    # Drop TTL manually
    await redis_client.expire(f"session:{sid}", 5)
    ttl_before = await redis_client.ttl(f"session:{sid}")
    assert ttl_before <= 5

    await store.touch(sid)

    ttl_after = await redis_client.ttl(f"session:{sid}")
    assert ttl_after > 55


@pytest.mark.asyncio
async def test_touch_unknown_sid_is_noop(store: SessionStore) -> None:
    # Should not raise; returns False to signal nothing was touched.
    result = await store.touch("nonexistent")
    assert result is False


@pytest.mark.asyncio
async def test_destroy_removes_session(store: SessionStore) -> None:
    sid = await store.create(admin_id=uuid4())
    await store.destroy(sid)
    assert await store.load(sid) is None


@pytest.mark.asyncio
async def test_destroy_all_for_admin(redis_client: Redis) -> None:
    store = SessionStore(redis_client, ttl_seconds=60)
    admin_id = uuid4()
    other_admin_id = uuid4()
    sid_a1 = await store.create(admin_id=admin_id)
    sid_a2 = await store.create(admin_id=admin_id)
    sid_b1 = await store.create(admin_id=other_admin_id)

    removed = await store.destroy_all_for(admin_id)
    assert removed == 2
    assert await store.load(sid_a1) is None
    assert await store.load(sid_a2) is None
    # Other admin's session untouched
    assert await store.load(sid_b1) is not None


@pytest.mark.asyncio
async def test_session_data_carries_issued_and_last_active(store: SessionStore) -> None:
    sid = await store.create(admin_id=uuid4())
    data = await store.load(sid)
    assert data is not None
    assert data.issued_at is not None
    assert data.last_active is not None


@pytest.mark.asyncio
async def test_touch_refreshes_index_key_ttl(redis_client: Redis) -> None:
    """touch() must also extend the admin_sessions index TTL so destroy_all_for
    still finds live sessions after the original TTL would have expired."""
    store = SessionStore(redis_client, ttl_seconds=60)
    admin_id = uuid4()
    sid = await store.create(admin_id=admin_id)
    index_key = f"admin_sessions:{admin_id}"

    # Artificially reduce the index key TTL to 5 s.
    await redis_client.expire(index_key, 5)
    ttl_before = await redis_client.ttl(index_key)
    assert ttl_before <= 5

    # touch() should restore it to full ttl_seconds.
    result = await store.touch(sid)
    assert result is True

    ttl_after = await redis_client.ttl(index_key)
    assert ttl_after > 55
