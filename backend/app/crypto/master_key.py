"""Master-key loader.

Reads a 32-byte binary file (Docker secret in prod, bind-mount in dev) once
at startup and returns the bytes. Enforces file size and, optionally, Unix
permissions of 0o400 to catch deployment mistakes.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

_EXPECTED_LEN = 32
_ALLOWED_MODE_MASK = 0o777  # mask out file-type bits


class MasterKeyError(RuntimeError):
    """Raised when the master key cannot be loaded safely."""


def load_master_key(path: Path, *, enforce_perms: bool = False) -> bytes:
    if not path.exists() or not path.is_file():
        raise MasterKeyError(f"master key not found at {path}")

    if enforce_perms:
        mode = os.stat(path).st_mode & _ALLOWED_MODE_MASK
        # Accept 0o400 (owner-read only) or 0o600 (owner-rw); reject anything broader.
        if mode & (stat.S_IRGRP | stat.S_IROTH | stat.S_IWGRP | stat.S_IWOTH):
            raise MasterKeyError(
                f"master key {path} has permissions {oct(mode)}; "
                f"must be 0o400 or 0o600 (owner-only)"
            )

    data = path.read_bytes()
    if len(data) != _EXPECTED_LEN:
        raise MasterKeyError(f"master key must be exactly {_EXPECTED_LEN} bytes; got {len(data)}")
    return data
