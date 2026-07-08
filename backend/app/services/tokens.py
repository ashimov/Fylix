"""Token generation for transfers. Thin wrappers so call-sites self-document
which kind of token is being generated."""

import secrets

# 32 bytes of entropy → 43-char base64url string.
_TOKEN_BYTES = 32


def generate_download_token() -> str:
    """Public URL token used in https://.../t/{token}.

    Knowledge of this token is the only gate on download.
    """
    return secrets.token_urlsafe(_TOKEN_BYTES)


def generate_manage_token() -> str:
    """Sender-only URL token used in https://.../s/{manage_token}.

    Lets the sender view download history, delete early, revoke link.
    """
    return secrets.token_urlsafe(_TOKEN_BYTES)
