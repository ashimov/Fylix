"""Minimal tus 1.0.0 Core upload handler (PATCH + HEAD only).

The transfer and its TransferFile rows are created up-front via POST /api/transfers.
This module only handles the chunked upload into the staging dir; final
assembly/encryption is done by the worker.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import IO
from uuid import UUID

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Transfer, TransferFile
from app.services.staging import StagingService

TUS_VERSION = "1.0.0"
UPLOAD_READY_QUEUE = "upload:ready"


class TusError(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail


@dataclass
class UploadState:
    current_offset: int
    declared_length: int
    complete: bool


class TusHandler:
    def __init__(self, *, staging: StagingService, redis: Redis) -> None:
        self.staging = staging
        self.redis = redis

    async def handle_head(
        self,
        session: AsyncSession,
        transfer_id: UUID,
        file_id: UUID,
    ) -> UploadState:
        tf = await self._load_file(session, transfer_id, file_id)
        path = self.staging.file_path(transfer_id, tf.id, tf.safe_filename)
        current = path.stat().st_size if path.exists() else 0
        return UploadState(
            current_offset=current,
            declared_length=tf.size_bytes,
            complete=current == tf.size_bytes and tf.size_bytes > 0,
        )

    async def handle_patch(
        self,
        session: AsyncSession,
        transfer_id: UUID,
        file_id: UUID,
        upload_offset: int,
        body_stream: IO[bytes],
    ) -> UploadState:
        transfer, tf = await self._load_transfer_and_file(session, transfer_id, file_id)

        if transfer.status != "uploading":
            raise TusError(409, f"transfer status is {transfer.status}")

        path = self.staging.file_path(transfer_id, tf.id, tf.safe_filename)
        current = path.stat().st_size if path.exists() else 0

        if upload_offset != current:
            raise TusError(409, f"Upload-Offset mismatch (expected {current}, got {upload_offset})")

        path.parent.mkdir(parents=True, exist_ok=True)
        written = _append_stream(path, body_stream, max_total=tf.size_bytes)
        new_offset = current + written

        if new_offset > tf.size_bytes:
            # Truncate back to declared size and reject the excess.
            with open(path, "r+b") as f:
                f.truncate(tf.size_bytes)
            raise TusError(413, f"chunk exceeds declared Upload-Length ({tf.size_bytes})")

        state = UploadState(
            current_offset=new_offset,
            declared_length=tf.size_bytes,
            complete=new_offset == tf.size_bytes,
        )

        if state.complete and await self._all_files_complete(session, transfer_id):
            await self.redis.lpush(  # type: ignore[misc]
                UPLOAD_READY_QUEUE, json.dumps({"transfer_id": str(transfer_id)})
            )

        return state

    # ---- helpers ----

    async def _load_file(
        self, session: AsyncSession, transfer_id: UUID, file_id: UUID
    ) -> TransferFile:
        tf = await session.get(TransferFile, file_id)
        if tf is None or tf.transfer_id != transfer_id:
            raise TusError(404, "file not found")
        return tf

    async def _load_transfer_and_file(
        self, session: AsyncSession, transfer_id: UUID, file_id: UUID
    ) -> tuple[Transfer, TransferFile]:
        t = await session.get(Transfer, transfer_id)
        if t is None:
            raise TusError(404, "transfer not found")
        tf = await self._load_file(session, transfer_id, file_id)
        return t, tf

    async def _all_files_complete(self, session: AsyncSession, transfer_id: UUID) -> bool:
        rows = (
            (
                await session.execute(
                    select(TransferFile).where(TransferFile.transfer_id == transfer_id)
                )
            )
            .scalars()
            .all()
        )
        for row in rows:
            p = self.staging.file_path(transfer_id, row.id, row.safe_filename)
            size = p.stat().st_size if p.exists() else 0
            if size != row.size_bytes:
                return False
        return True


def _append_stream(path: Path, src: IO[bytes], *, max_total: int) -> int:
    """Append bytes from `src` to `path`, return number of bytes written.

    Reads src fully; caller is responsible for not submitting a chunk that
    would grossly exceed max_total. We still cap writes here to prevent
    runaway disk usage from a pathological client.
    """
    chunk_size = 64 * 1024
    written = 0
    current_size = path.stat().st_size if path.exists() else 0
    max_bytes = max_total - current_size + chunk_size  # small slack for overflow detect

    with open(path, "ab") as f:
        while True:
            data = src.read(chunk_size)
            if not data:
                break
            if written + len(data) > max_bytes:
                # Overflow — stop writing; caller will detect via size check.
                f.write(data[: max_bytes - written])
                written = max_bytes
                break
            f.write(data)
            written += len(data)
    return written
