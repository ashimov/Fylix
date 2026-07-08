"""Upload policy: size, file count, extension blacklist.

Raised as PolicyViolation with suggested HTTP status code.
MIME validation is NOT done here — it happens in the worker against actual
bytes after tus chunks arrive.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.transfer import FileDescriptor
from app.services.settings_service import SettingsService


class PolicyViolation(RuntimeError):
    def __init__(self, reason: str, status_code: int = 422) -> None:
        super().__init__(reason)
        self.reason = reason
        self.status_code = status_code


class UploadPolicy:
    def __init__(self, settings_service: SettingsService) -> None:
        self.settings_service = settings_service

    async def check(
        self,
        session: AsyncSession,
        *,
        files: list[FileDescriptor],
        recipient_count: int,
    ) -> None:
        max_gb = await self.settings_service.get_int(session, "max_transfer_size_gb", 2)
        max_recipients = await self.settings_service.get_int(session, "max_recipients", 20)
        blacklist_raw = await self.settings_service.get_list(session, "extension_blacklist", [])

        if recipient_count > max_recipients:
            raise PolicyViolation(
                f"too many recipients (max {max_recipients})",
                status_code=422,
            )

        total = sum(f.size for f in files)
        max_bytes = max_gb * 1024 * 1024 * 1024
        if total > max_bytes:
            raise PolicyViolation(
                f"total size exceeds {max_gb} GB",
                status_code=413,
            )

        blacklist = {ext.lower() for ext in blacklist_raw}
        for f in files:
            # Check every suffix, not just the last one — guards against
            # double-extension bypass like `malware.exe.gz` with blacklist
            # `[".exe"]`. Path.suffixes handles compound extensions
            # (`[".tar", ".gz"]` for `a.tar.gz`).
            for ext in _extensions_of(f.filename):
                if ext in blacklist:
                    raise PolicyViolation(
                        f"file extension {ext} is not allowed",
                        status_code=422,
                    )


def _extensions_of(filename: str) -> list[str]:
    """Return all lowercased suffixes including the dot, innermost-first.

    >>> _extensions_of("a.tar.gz")
    ['.gz', '.tar']
    >>> _extensions_of("malware.exe.gz")
    ['.gz', '.exe']
    >>> _extensions_of("readme")
    []
    """
    return [s.lower() for s in reversed(Path(filename).suffixes)]
