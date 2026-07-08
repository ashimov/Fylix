"""Process-lifetime crypto material, held in memory only.

Lives in its own module so routers can import the accessors at the top
of the file without creating a circular dependency with `app.main`
(which historically owned the globals and forced callers into lazy
`from app.main import get_master_key` imports inside function bodies).

`main.lifespan` populates these at startup via `set_*` and zeroes them
on shutdown via `clear_master_keys`. Everyone else treats them as
read-only — crash loudly if unset (`get_master_key` raises
RuntimeError) so a pre-lifespan request never silently decrypts with
`None`.
"""
from __future__ import annotations

_MASTER_KEY: bytes | None = None
# Only set during a master-key rotation transition window — see
# docs/KEY_ROTATION.md "Zero-downtime rotation". Routers pass this to
# unwrap_key / unwrap_totp_secret so old blobs keep decoding.
_PREVIOUS_MASTER_KEY: bytes | None = None


def get_master_key() -> bytes:
    if _MASTER_KEY is None:
        raise RuntimeError("master key not loaded (startup did not complete)")
    return _MASTER_KEY


def get_previous_master_key() -> bytes | None:
    """Return the previous-generation master key if a rotation window is
    active (MASTER_KEY_PREVIOUS_PATH was set at boot); None otherwise.
    """
    return _PREVIOUS_MASTER_KEY


def set_master_key(key: bytes) -> None:
    global _MASTER_KEY  # noqa: PLW0603 — module-level lifetime singleton
    _MASTER_KEY = key


def set_previous_master_key(key: bytes | None) -> None:
    global _PREVIOUS_MASTER_KEY  # noqa: PLW0603
    _PREVIOUS_MASTER_KEY = key


def clear_master_keys() -> None:
    """Best-effort zeroization of both keys on shutdown. Python doesn't
    guarantee memory wipe but we try."""
    global _MASTER_KEY, _PREVIOUS_MASTER_KEY  # noqa: PLW0603
    if _MASTER_KEY is not None:
        _MASTER_KEY = b"\x00" * 32  # noqa: F841 — overwrite bytes first
        _MASTER_KEY = None
    if _PREVIOUS_MASTER_KEY is not None:
        _PREVIOUS_MASTER_KEY = b"\x00" * 32  # noqa: F841
        _PREVIOUS_MASTER_KEY = None
