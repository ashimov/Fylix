"""Staging directory service.

Each transfer gets a subdirectory under the staging root (host bind-mount,
watched by Microsoft Defender in prod). Files are written there plaintext,
then encrypted by the worker and moved to MinIO. `secure_delete` overwrites
bytes with random data before unlinking to make residual plaintext
recovery harder on spinning disks. On SSDs this is best-effort (wear
levelling may preserve old blocks).
"""

from __future__ import annotations

import os
import re
import secrets
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from pathlib import Path
from typing import IO
from uuid import UUID


class StagingError(RuntimeError):
    pass


_UNSAFE = re.compile(r"[^A-Za-z0-9._\- ]")
_OVERWRITE_CHUNK = 64 * 1024


class StagingService:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def safe_filename(name: str) -> str:
        name = Path(name).name
        name = _UNSAFE.sub("_", name)
        name = name.lstrip(".") or "file"
        return name[:255]

    def transfer_dir(self, transfer_id: UUID) -> Path:
        return self.root / str(transfer_id)

    def create_transfer_dir(self, transfer_id: UUID) -> Path:
        p = self.transfer_dir(transfer_id)
        p.mkdir(parents=True, exist_ok=True)
        return p

    def file_path(self, transfer_id: UUID, file_id: UUID, filename: str) -> Path:
        if not filename:
            raise StagingError("filename must not be empty")
        safe = self.safe_filename(filename)
        return self.transfer_dir(transfer_id) / f"{file_id}__{safe}"

    @contextmanager
    def open_write(self, transfer_id: UUID, file_id: UUID, filename: str) -> Iterator[IO[bytes]]:
        p = self.file_path(transfer_id, file_id, filename)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "wb") as f:
            yield f

    def secure_delete(self, transfer_id: UUID) -> None:
        d = self.transfer_dir(transfer_id)
        if not d.exists():
            return
        for path in d.iterdir():
            if path.is_file():
                _overwrite_and_unlink(path)
        with suppress(OSError):
            d.rmdir()


def _overwrite_and_unlink(path: Path) -> None:
    """Best-effort overwrite with random bytes before unlink."""
    try:
        size = path.stat().st_size
    except FileNotFoundError:
        return
    try:
        with open(path, "r+b", buffering=0) as f:
            written = 0
            while written < size:
                n = min(_OVERWRITE_CHUNK, size - written)
                f.write(secrets.token_bytes(n))
                written += n
            f.flush()
            os.fsync(f.fileno())
    except OSError:
        pass
    with suppress(FileNotFoundError):
        path.unlink()
