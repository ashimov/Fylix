from pathlib import Path
from uuid import uuid4

import pytest

from app.services.staging import StagingError, StagingService


@pytest.fixture
def staging(tmp_path: Path) -> StagingService:
    return StagingService(root=tmp_path)


def test_create_transfer_dir_returns_path(staging: StagingService) -> None:
    tid = uuid4()
    p = staging.create_transfer_dir(tid)
    assert p.is_dir()
    assert p.name == str(tid)


def test_open_write_creates_file_in_transfer_dir(staging: StagingService) -> None:
    tid = uuid4()
    fid = uuid4()
    staging.create_transfer_dir(tid)
    target = staging.file_path(tid, fid, "logo.png")
    with staging.open_write(tid, fid, "logo.png") as f:
        f.write(b"hello")
    assert target.read_bytes() == b"hello"


def test_filenames_are_sanitised(staging: StagingService) -> None:
    safe = staging.safe_filename("../../etc/passwd")
    assert "/" not in safe
    assert ".." not in safe


def test_safe_filename_falls_back_to_file_when_all_dots(staging: StagingService) -> None:
    # After lstrip('.') this becomes empty; fallback kicks in.
    assert staging.safe_filename("...") == "file"
    assert staging.safe_filename(".") == "file"

    safe = staging.safe_filename("bad\x00name.txt")
    assert "\x00" not in safe


def test_secure_delete_removes_files_and_dir(staging: StagingService) -> None:
    tid = uuid4()
    fid = uuid4()
    staging.create_transfer_dir(tid)
    with staging.open_write(tid, fid, "x.bin") as f:
        f.write(b"A" * 4096)
    staging.secure_delete(tid)
    assert not (staging.root / str(tid)).exists()


def test_secure_delete_tolerates_missing_dir(staging: StagingService) -> None:
    staging.secure_delete(uuid4())


def test_file_path_rejects_empty_filename(staging: StagingService) -> None:
    tid = uuid4()
    fid = uuid4()
    staging.create_transfer_dir(tid)
    with pytest.raises(StagingError, match="filename"):
        staging.file_path(tid, fid, "")


def test_file_path_includes_file_id_prefix(staging: StagingService) -> None:
    tid = uuid4()
    fid = uuid4()
    p = staging.file_path(tid, fid, "résumé.pdf")
    assert p.name.startswith(str(fid) + "__")
    # Two files with the same safe_filename but different file_ids don't collide.
    fid2 = uuid4()
    p2 = staging.file_path(tid, fid2, "résumé.pdf")
    assert p != p2
