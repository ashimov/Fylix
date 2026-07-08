"""OpenTelemetry bootstrap for Fylix (api + worker).

HawkAPI's ``observability`` integration configures `trace.get_tracer(...)`
for per-request spans, but leaves the ``TracerProvider`` + exporter
wiring to the application. This module provides the single call
``setup_otel(service_name)`` used by both ``app/main.py`` (api lifespan)
and ``app/worker/main.py`` (worker startup) so spans export to the
collector (Jaeger) configured by ``OTEL_EXPORTER_OTLP_ENDPOINT``.

Env vars (following OTel spec):

* ``OTEL_EXPORTER_OTLP_ENDPOINT`` — e.g. ``http://jaeger:4317`` (gRPC).
  When unset, the call is a no-op — useful for unit tests and dev where
  the collector isn't running.
* ``OTEL_SERVICE_NAME`` — overrides the ``service_name`` argument.
* ``OTEL_TRACES_SAMPLER_ARG`` — sampling ratio 0.0..1.0 (default 1.0).

Auto-instrumented libraries:

* SQLAlchemy — DB queries (select/insert/update spans with SQL text).
* Redis — queue pushes, rate-limit SET/GET, session lookups.
* httpx — outbound hCaptcha verify, Telegram alerts, MinIO scan
  webhooks. Minio SDK uses urllib3 directly (no httpx), so object-
  storage I/O is not traced here — we rely on our own manual spans.
"""

from __future__ import annotations

import logging
import os

log = logging.getLogger(__name__)

_initialised = False


def setup_otel(*, service_name: str) -> None:
    """Initialise the OTel ``TracerProvider`` + OTLP exporter + instrumentations.

    Idempotent. No-op when ``OTEL_EXPORTER_OTLP_ENDPOINT`` isn't set.
    """
    global _initialised  # noqa: PLW0603
    if _initialised:
        return
    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip()
    if not endpoint:
        log.info("otel: OTEL_EXPORTER_OTLP_ENDPOINT unset — tracing disabled")
        _initialised = True
        return

    # Lazy imports so unit tests don't pay the import cost when OTel is
    # not configured; also keeps the shim optional.
    from opentelemetry import trace
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    resolved_name = os.environ.get("OTEL_SERVICE_NAME", service_name)
    resource = Resource.create({"service.name": resolved_name})
    provider = TracerProvider(resource=resource)
    exporter = OTLPSpanExporter(endpoint=endpoint, insecure=True)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)

    _install_instrumentations()
    _initialised = True
    log.info(
        "otel: tracer provider registered (service=%s, endpoint=%s)",
        resolved_name,
        endpoint,
    )


def _install_instrumentations() -> None:
    """Wire per-library OTel instrumentations. Safe to call once."""
    from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
    from opentelemetry.instrumentation.redis import RedisInstrumentor
    from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor

    # SQLAlchemy: passing no engine instruments every engine created
    # after this point; our module-level engine in app.db is created
    # lazily on first session, so this order is safe.
    SQLAlchemyInstrumentor().instrument()
    RedisInstrumentor().instrument()
    HTTPXClientInstrumentor().instrument()
