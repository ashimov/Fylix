import os
from pathlib import Path

import pytest


@pytest.fixture
def tmp_master_key(tmp_path: Path) -> Path:
    """Write a deterministic 32-byte key to a tmp file, return its path."""
    key_file = tmp_path / "master_key"
    key_file.write_bytes(bytes(range(32)))  # 0x00..0x1f
    os.chmod(key_file, 0o400)
    return key_file
