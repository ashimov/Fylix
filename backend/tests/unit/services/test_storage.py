import io
from urllib.parse import urlparse
from uuid import uuid4

import pytest
from testcontainers.minio import MinioContainer  # type: ignore[import-untyped]

from app.services.storage import ObjectNotFound, StorageService


@pytest.fixture(scope="module")
def minio() -> MinioContainer:
    with MinioContainer() as mc:
        yield mc


@pytest.fixture
def storage(minio: MinioContainer) -> StorageService:
    cfg = minio.get_config()
    endpoint = cfg["endpoint"]
    if endpoint.startswith("http"):
        endpoint = urlparse(endpoint).netloc
    svc = StorageService(
        endpoint=endpoint,
        access_key=cfg["access_key"],
        secret_key=cfg["secret_key"],
        bucket="transfers",
        secure=False,
    )
    svc.ensure_bucket()
    return svc


def test_object_key_format() -> None:
    tid = uuid4()
    fid = uuid4()
    key = StorageService.object_key(tid, fid)
    assert key == f"{tid}/{fid}.enc"


def test_put_and_get_object(storage: StorageService) -> None:
    tid = uuid4()
    fid = uuid4()
    payload = b"\x01\x02\x03encrypted-bytes"
    key = StorageService.object_key(tid, fid)
    storage.put_bytes(key, payload)
    out = b"".join(storage.get_stream(key))
    assert out == payload


def test_get_missing_raises(storage: StorageService) -> None:
    with pytest.raises(ObjectNotFound):
        list(storage.get_stream("does/not/exist"))


def test_delete_object(storage: StorageService) -> None:
    tid = uuid4()
    fid = uuid4()
    key = StorageService.object_key(tid, fid)
    storage.put_bytes(key, b"x")
    storage.delete_object(key)
    with pytest.raises(ObjectNotFound):
        list(storage.get_stream(key))


def test_delete_prefix_removes_all_transfer_files(storage: StorageService) -> None:
    tid = uuid4()
    for _ in range(3):
        fid = uuid4()
        storage.put_bytes(StorageService.object_key(tid, fid), b"data")
    storage.delete_transfer(tid)
    assert list(storage.list_transfer_keys(tid)) == []


def test_put_stream_writes_iterable(storage: StorageService) -> None:
    tid = uuid4()
    fid = uuid4()
    key = StorageService.object_key(tid, fid)
    chunks = [b"A" * 1000, b"B" * 2000, b"C" * 500]
    total = sum(len(c) for c in chunks)
    storage.put_stream(key, iter(chunks), length=total)
    out = b"".join(storage.get_stream(key))
    assert out == b"A" * 1000 + b"B" * 2000 + b"C" * 500


def test_put_file_uploads_from_file_like(storage: StorageService) -> None:
    """put_file should accept a seekable file-like and upload its contents."""
    tid = uuid4()
    fid = uuid4()
    key = StorageService.object_key(tid, fid)
    payload = b"\xde\xad\xbe\xef" * 256  # 1 KiB
    fileobj = io.BytesIO(payload)
    storage.put_file(key, fileobj, len(payload))
    out = b"".join(storage.get_stream(key))
    assert out == payload


def test_put_file_accepts_spooled_temp_file(storage: StorageService) -> None:
    """put_file should work with SpooledTemporaryFile (the encrypt-task usage)."""
    from tempfile import SpooledTemporaryFile

    tid = uuid4()
    fid = uuid4()
    key = StorageService.object_key(tid, fid)
    payload = b"spooled-data-" * 100
    with SpooledTemporaryFile(max_size=1024) as spooled:
        spooled.write(payload)
        length = spooled.tell()
        spooled.seek(0)
        storage.put_file(key, spooled, length)
    out = b"".join(storage.get_stream(key))
    assert out == payload
