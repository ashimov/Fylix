from pathlib import Path
from typing import Self

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "development"
    app_name: str = "Fylix"
    public_url: str = "https://localhost"
    log_level: str = "info"
    cleanup_interval_seconds: int = 300

    # Built-in defender-poll heuristic: watches staging dir for files that
    # "disappeared" mid-upload and flips the transfer to `infected`. The
    # check is race-prone with the encrypt worker's staging-cleanup step
    # and produces false positives (see incident 2026-04-20). Disable when
    # a host-level AV (Microsoft Defender for Endpoint on the node) is the
    # real malware gate.
    defender_poll_enabled: bool = True

    postgres_db: str
    postgres_user: str
    postgres_password: str
    postgres_host: str = "postgres"
    postgres_port: int = 5432

    redis_url: str = "redis://redis:6379/0"

    minio_root_user: str
    minio_root_password: str
    minio_endpoint: str = "minio:9000"
    minio_bucket: str = "transfers"
    minio_secure: bool = False

    smtp_host: str = "mailpit"
    smtp_port: int = 1025
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "no-reply@example.com"
    # Set False for internal corporate relays with self-signed certs.
    smtp_verify_cert: bool = True

    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    # GlitchTip/Sentry DSN for error reporting. Empty = disabled.
    sentry_dsn: str = ""
    sentry_traces_sample_rate: float = 0.1

    hcaptcha_secret: str = ""
    hcaptcha_site_key: str = ""

    maxmind_db_path: Path = Field(default=Path("/srv/fylix/geoip/GeoLite2-Country.mmdb"))

    master_key_path: Path = Field(default=Path("/run/secrets/master_key"))
    # Optional previous-generation master key, only set during a rotation
    # window so reads fall back when current-key unwrap fails.
    master_key_previous_path: Path | None = None
    staging_dir: Path = Field(default=Path("/srv/fylix/staging"))

    # When True, cookies are set without the Secure flag (for local plain-HTTP dev).
    # NEVER set in production. See .env.example for details.
    dev_insecure_cookies: bool = False

    # TTL for the rate-limit middleware's in-process settings cache (seconds).
    # Set to 0 in test environments to disable caching and always read live from DB.
    rate_limit_cache_ttl: int = 10

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @model_validator(mode="after")
    def _validate_production_invariants(self) -> Self:
        if self.app_env != "production":
            return self
        problems: list[str] = []
        if not self.hcaptcha_secret:
            problems.append("hcaptcha_secret must be set (HCAPTCHA_SECRET env)")
        if self.dev_insecure_cookies:
            problems.append("dev_insecure_cookies must be False (DEV_INSECURE_COOKIES=0)")
        if not self.minio_secure:
            problems.append(
                "minio_secure must be True (MINIO_SECURE=true) — plain-HTTP "
                "ciphertext + access keys on the internal data network is "
                "not acceptable for a security-focused deployment"
            )
        if problems:
            raise ValueError(
                "production app_env requires fail-closed security controls: " + "; ".join(problems)
            )
        return self


settings = Settings()  # type: ignore[call-arg]
