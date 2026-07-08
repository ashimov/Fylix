from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from hawkapi import HawkAPI
from redis.asyncio import Redis

# Install HawkAPI parity shims (Router.head/.options, multi-Set-Cookie support)
# BEFORE any router module is imported — their decorators and response classes
# are bound at import time.
from app.http import install_error_handlers, install_hawkapi_shims

install_hawkapi_shims()

from app.config import settings  # noqa: E402
from app.crypto import load_master_key  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.logging_config import configure_logging  # noqa: E402
from app.middleware.csrf import CsrfMiddleware  # noqa: E402
from app.middleware.rate_limit import RateLimitMiddleware  # noqa: E402
from app.middleware.request_id import RequestIdMiddleware  # noqa: E402
from app.routers.admin import router as admin_router  # noqa: E402
from app.routers.metrics import router as metrics_router  # noqa: E402
from app.routers.public import config_router, download_router  # noqa: E402
from app.routers.public import router as public_router  # noqa: E402
from app.services.rate_limit import RateLimiter  # noqa: E402
from app.services.settings_service import SettingsService  # noqa: E402
from app.state import (  # noqa: E402
    clear_master_keys,
    get_master_key,
    get_previous_master_key,
    set_master_key,
    set_previous_master_key,
)

# get_master_key + get_previous_master_key are re-exported from app.state
# so legacy `from app.main import get_master_key` imports keep working
# after the refactor — do not remove them.
__all__ = ["app", "get_master_key", "get_previous_master_key"]


@asynccontextmanager
async def lifespan(_: HawkAPI) -> AsyncIterator[None]:
    configure_logging(level=settings.log_level.upper())
    if settings.sentry_dsn:
        import sentry_sdk

        sentry_sdk.init(
            dsn=settings.sentry_dsn,
            environment=settings.app_env,
            traces_sample_rate=settings.sentry_traces_sample_rate,
            send_default_pii=False,
        )
    # OpenTelemetry bootstrap — no-op when OTEL_EXPORTER_OTLP_ENDPOINT
    # is unset (tests, offline dev). See app/observability.py.
    from app.observability import setup_otel

    setup_otel(service_name="fylix-api")

    enforce_perms = settings.app_env != "development"
    set_master_key(
        load_master_key(settings.master_key_path, enforce_perms=enforce_perms)
    )
    if settings.master_key_previous_path is not None:
        set_previous_master_key(
            load_master_key(
                settings.master_key_previous_path, enforce_perms=enforce_perms
            )
        )
    try:
        yield
    finally:
        clear_master_keys()


app = HawkAPI(
    title=settings.app_name,
    lifespan=lifespan,
    # Our own /healthz below checks master-key readiness; disable HawkAPI's default.
    health_url=None,
    readyz_url=None,
    livez_url=None,
    # No public API docs in production — admin plane is CIDR-gated at Nginx.
    docs_url=None,
    redoc_url=None,
    scalar_url=None,
    openapi_url=None,
    # Match the 422 status that our tests and the admin SPA expect for
    # body-validation failures; HawkAPI defaults to 400.
    validation_error_status=422,
)
install_error_handlers(app)
app.include_router(public_router)
app.include_router(download_router)
app.include_router(config_router)
app.include_router(admin_router)
app.include_router(metrics_router)

_rl_redis = Redis.from_url(settings.redis_url, decode_responses=False)

# HawkAPI middleware order: FIRST-added = outermost (runs first on request,
# last on response). RequestIdMiddleware must be outermost so request_id is
# bound before rate-limit/csrf emit any logs and the echo header lands on
# the final response.
app.add_middleware(RequestIdMiddleware)
app.add_middleware(CsrfMiddleware, protect_prefix="/api/admin", cookie_name="csrf")
app.add_middleware(
    RateLimitMiddleware,
    limiter=RateLimiter(_rl_redis),
    session_factory=SessionLocal,
    settings_service=SettingsService(),
    cache_ttl_seconds=settings.rate_limit_cache_ttl,
)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    # Confirms startup completed (master key loaded) without leaking any key data.
    _ = get_master_key()  # raises if not loaded
    return {"status": "ok", "app": settings.app_name}
