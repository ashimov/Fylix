"""Settings validation — production must be fail-closed on security controls."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.config import Settings

_BASE_KWARGS: dict[str, str] = {
    "postgres_db": "x",
    "postgres_user": "x",
    "postgres_password": "x",
    "minio_root_user": "x",
    "minio_root_password": "x",
}


def _make(**overrides: object) -> Settings:
    return Settings(**{**_BASE_KWARGS, **overrides}, _env_file=None)  # type: ignore[arg-type]


def test_production_requires_hcaptcha_secret() -> None:
    with pytest.raises(ValidationError, match="hcaptcha_secret"):
        _make(
            app_env="production",
            hcaptcha_secret="",
            dev_insecure_cookies=False,
            minio_secure=True,
        )


def test_production_forbids_dev_insecure_cookies() -> None:
    with pytest.raises(ValidationError, match="dev_insecure_cookies"):
        _make(
            app_env="production",
            hcaptcha_secret="s",
            dev_insecure_cookies=True,
            minio_secure=True,
        )


def test_production_requires_minio_secure() -> None:
    with pytest.raises(ValidationError, match="minio_secure"):
        _make(
            app_env="production",
            hcaptcha_secret="s",
            dev_insecure_cookies=False,
            minio_secure=False,
        )


def test_production_reports_all_missing_invariants() -> None:
    with pytest.raises(ValidationError) as exc:
        _make(
            app_env="production",
            hcaptcha_secret="",
            dev_insecure_cookies=True,
            minio_secure=False,
        )
    msg = str(exc.value)
    assert "hcaptcha_secret" in msg
    assert "dev_insecure_cookies" in msg
    assert "minio_secure" in msg


def test_production_ok_when_fully_configured() -> None:
    s = _make(
        app_env="production",
        hcaptcha_secret="s",
        dev_insecure_cookies=False,
        minio_secure=True,
    )
    assert s.app_env == "production"
    assert s.hcaptcha_secret == "s"
    assert s.dev_insecure_cookies is False
    assert s.minio_secure is True


def test_development_allows_empty_captcha() -> None:
    s = _make(app_env="development", hcaptcha_secret="", dev_insecure_cookies=False)
    assert s.hcaptcha_secret == ""


def test_development_allows_insecure_cookies() -> None:
    s = _make(app_env="development", hcaptcha_secret="", dev_insecure_cookies=True)
    assert s.dev_insecure_cookies is True


# --- Dual-key rotation: optional previous master key path -----------------


def test_master_key_previous_path_defaults_to_none() -> None:
    s = _make()
    assert s.master_key_previous_path is None


def test_master_key_previous_path_accepts_configured_path() -> None:
    s = _make(master_key_previous_path="/run/secrets/master_key_previous")
    assert s.master_key_previous_path is not None
    assert str(s.master_key_previous_path) == "/run/secrets/master_key_previous"
