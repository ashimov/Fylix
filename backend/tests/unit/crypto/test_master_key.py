from pathlib import Path

import pytest

from app.crypto.master_key import MasterKeyError, load_master_key


def test_load_master_key_reads_32_bytes(tmp_master_key: Path) -> None:
    key = load_master_key(tmp_master_key)
    assert isinstance(key, bytes)
    assert len(key) == 32
    assert key == bytes(range(32))


def test_load_master_key_rejects_missing_file(tmp_path: Path) -> None:
    missing = tmp_path / "nope"
    with pytest.raises(MasterKeyError, match="not found"):
        load_master_key(missing)


def test_load_master_key_rejects_wrong_size(tmp_path: Path) -> None:
    bad = tmp_path / "short"
    bad.write_bytes(b"\x00" * 16)
    with pytest.raises(MasterKeyError, match="32 bytes"):
        load_master_key(bad)


def test_load_master_key_rejects_loose_permissions(tmp_path: Path) -> None:
    import os

    f = tmp_path / "loose"
    f.write_bytes(bytes(range(32)))
    os.chmod(f, 0o644)  # world-readable
    with pytest.raises(MasterKeyError, match="permissions"):
        load_master_key(f, enforce_perms=True)
