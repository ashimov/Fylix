"""MinIO storage service.

Stores ciphertext blobs keyed by `{transfer_id}/{file_id}.enc`.
Reads are streamed (decrypt happens in the caller using AES-GCM
from app.crypto.stream — not here). Writes are atomic per-object.
"""

from __future__ import annotations

import io
from collections.abc import Iterable, Iterator
from typing import IO
from uuid import UUID

from minio import Minio
from minio.deleteobjects import DeleteObject
from minio.error import S3Error


class StorageError(RuntimeError):
    pass


class ObjectNotFound(StorageError):
    pass


class StorageService:
    def __init__(
        self,
        *,
        endpoint: str,
        access_key: str,
        secret_key: str,
        bucket: str,
        secure: bool = True,
    ) -> None:
        self.bucket = bucket
        self._client = Minio(endpoint, access_key=access_key, secret_key=secret_key, secure=secure)

    def ensure_bucket(self) -> None:
        if not self._client.bucket_exists(self.bucket):
            self._client.make_bucket(self.bucket)

    @staticmethod
    def object_key(transfer_id: UUID, file_id: UUID) -> str:
        return f"{transfer_id}/{file_id}.enc"

    def put_bytes(self, key: str, data: bytes) -> None:
        self._client.put_object(
            self.bucket,
            key,
            data=io.BytesIO(data),
            length=len(data),
            content_type="application/octet-stream",
        )

    def put_stream(self, key: str, stream: Iterable[bytes], length: int) -> None:
        """Stream bytes into MinIO without buffering them all locally.

        `length` must equal the total bytes the iterable will yield.
        """
        self._client.put_object(
            self.bucket,
            key,
            data=_IteratorIO(iter(stream)),  # type: ignore[arg-type]  # duck-typed file-like
            length=length,
            content_type="application/octet-stream",
        )

    def put_file(self, key: str, fileobj: IO[bytes], length: int) -> None:
        """Upload from a file-like with .read(n) and known length."""
        self._client.put_object(
            self.bucket,
            key,
            data=fileobj,  # type: ignore[arg-type]  # IO[bytes] satisfies the read(n) use
            length=length,
            content_type="application/octet-stream",
        )

    def get_stream(self, key: str) -> Iterator[bytes]:
        try:
            resp = self._client.get_object(self.bucket, key)
        except S3Error as e:
            if e.code == "NoSuchKey":
                raise ObjectNotFound(key) from e
            raise
        try:
            yield from resp.stream(64 * 1024)
        finally:
            resp.close()
            resp.release_conn()

    def delete_object(self, key: str) -> None:
        self._client.remove_object(self.bucket, key)

    def list_transfer_keys(self, transfer_id: UUID) -> Iterator[str]:
        for obj in self._client.list_objects(self.bucket, prefix=f"{transfer_id}/", recursive=True):
            yield obj.object_name

    def delete_transfer(self, transfer_id: UUID) -> None:
        objects_to_delete = (DeleteObject(name) for name in self.list_transfer_keys(transfer_id))
        errors = list(self._client.remove_objects(self.bucket, objects_to_delete))
        if errors:
            raise StorageError(f"delete errors: {errors}")


class _IteratorIO(io.RawIOBase):
    """Wrap an iterator[bytes] into a readable file-like for MinIO."""

    def __init__(self, it: Iterator[bytes]) -> None:
        self._it = it
        self._buf = b""

    def readable(self) -> bool:
        return True

    def readinto(self, b: bytearray) -> int:  # type: ignore[override]
        while not self._buf:
            try:
                self._buf = next(self._it)
            except StopIteration:
                return 0
        n = min(len(b), len(self._buf))
        b[:n] = self._buf[:n]
        self._buf = self._buf[n:]
        return n
