# Migration Notes

Living document for framework / schema / architectural migrations the
Fylix codebase has been through. Read this before touching anything in
`backend/app/http.py` or the middleware stack.

---

## FastAPI → HawkAPI 0.1.5 (2026-04-19)

### Why

The Fylix author owns and maintains the **HawkAPI** framework in-house
([github.com/ashimov/HawkAPI](https://github.com/ashimov/HawkAPI)). Fylix
is the first product to run it in production. Dropping FastAPI / Starlette
as a dependency was a strategic decision to:

1. Own the full request-path stack (no Starlette transitive).
2. Benefit from HawkAPI's msgspec-based serialisation (5–6× faster than
   FastAPI's Pydantic path on 5 of 6 competitive benchmark scenarios).
3. Keep bug-fix latency to zero — fixes in HawkAPI land immediately.

### What changed on the wire

**Nothing.** Error envelopes, cookie behaviour, status codes, and
request/response shapes were preserved bit-for-bit by a shim layer in
[`backend/app/http.py`](../backend/app/http.py). The admin SPA and the
public frontend weren't touched during the migration — they already saw
FastAPI-shape `{"detail": ...}` envelopes, and they still do.

### The shim (`backend/app/http.py`)

HawkAPI's defaults differ from FastAPI in eight places that Fylix /
its tests rely on. The shim patches each in a single idempotent
`install_hawkapi_shims()` orchestrator, called at the top of
`app/main.py` **before any router is imported** (decorators and
response classes bind at import time).

| Shim | Why it exists | HawkAPI upstream status |
|---|---|---|
| `install_cookie_support` | Response headers are `dict[str, str]` in HawkAPI → duplicate `Set-Cookie` collapses. Login sets session + csrf simultaneously. | Open — tracked internally; sentinel + patched `_build_raw_headers` is the workaround. |
| `install_router_method_aliases` | `Router` ships only get/post/patch/put/delete/websocket. TUS needs `.head()`, `.options()`. | Open. |
| `install_post_default_status` | `Router.post` defaults to 201; tests / SPA expect 200 unless explicit. | Stylistic difference — unlikely to land upstream. |
| `install_pydantic_encoder_hook` | msgspec encoder raises `TypeError` on `BaseModel`; handlers that return `AdminPublic` etc. crash with 500. | Partially addressed by hawkapi[pydantic] adapter, but encoder hook still misses BaseModel. |
| `install_pydantic_validation_hook` | `pydantic.ValidationError` from body decoding crashes 500; hawkapi only catches `RequestValidationError`. | Not fixed upstream — shim translates on our side. |
| `install_validation_error_renderer` | HawkAPI emits RFC 9457 Problem Details; SPA/tests expect FastAPI-shape `{"detail": [...]}`. | Opinionated — we override the renderer rather than the default. |
| `install_streaming_response_passthrough` | `_build_response` only recognises `Response`/`JSONResponse`; `StreamingResponse` has no shared base → gets JSON-encoded. | **Partially fixed in 0.1.5**: trivial-route fast path now dispatches streaming in-place. Shim kept as defence-in-depth. |
| `install_response_model_hook` | `_apply_response_model` uses `msgspec.to_builtins` which chokes on Pydantic instances. | Open — the `response_model=` flag is FastAPI-parity, expected to land in upstream. |

### The custom `HTTPException` (`app.http.HTTPException`)

HawkAPI's `hawkapi.HTTPException` accepts `detail: str` only and
renders via `to_response()` (bypasses `app._exception_handlers`). Our
subclass:

- accepts arbitrary `detail` (dict, list, str, None)
- stores the original object on both `self.detail` (for `exc.detail["error"]` compatibility) and `self.rich_detail`
- overrides `to_response()` to emit `{"detail": <rich>}` as `JSONResponse`

All routers should import `HTTPException` from `app.http`, not
`hawkapi` directly. If the raw base is imported, `install_error_handlers`
also patches its `to_response` globally so the envelope stays
consistent — but that's a safety net, not the intended path.

### Middleware

The three custom middlewares — **RequestIdMiddleware**,
**CsrfMiddleware**, **RateLimitMiddleware** — were rewritten off
Starlette's `BaseHTTPMiddleware.dispatch(req, call_next)` onto raw
ASGI `__call__(scope, receive, send)` (HawkAPI ships a `Middleware`
base class but its `before_request`/`after_response` hook path buffers
the whole response body — breaks streamed downloads and multi-cookie
emission). See the docstrings in each file for specifics.

Order note: HawkAPI applies **first-added = outermost** (opposite of
Starlette/FastAPI). `main.py` adds `RequestIdMiddleware` first so it
wraps everything.

### Upgrading HawkAPI

1. `cd backend && uv lock --upgrade-package hawkapi`
2. `uv sync`
3. `docker compose build api worker && docker compose up -d --force-recreate api worker`
4. Run unit + integration tests: `pytest tests/unit/` + `docker compose exec api /opt/venv/bin/python -m pytest tests/integration/`
5. Review the new HawkAPI changelog — if a shim's "Why it exists" reason is now fixed upstream, the shim can be removed.

---

## Known follow-ups

These were flagged in the 2026-04-20 full code review and deferred to
their own focused refactor tickets (each large enough to warrant an
isolated PR):

### admin router split

`backend/app/routers/admin.py` is 1466 lines mixing auth, transfers,
blocklist, settings, admins, audit, telegram, analytics, and crypto
rewrap. Target layout:

```
backend/app/routers/admin/
  __init__.py       # re-exports `router` aggregator + legacy symbols
  _shared.py        # _AdminCtx, require_session/admin_role/viewer_or_admin,
                    # _session dep, singletons (to move to lifespan per #9),
                    # SESSION_COOKIE, cursor helpers
  auth.py           # login / logout / me
  transfers.py      # /transfers CRUD + revoke + delete
  blocklist.py      # /blocklist/{kind}
  settings.py       # /settings, /extensions, /crypto/rewrap
  admins.py         # /admins CRUD + reset-totp
  audit.py          # /audit, /audit.csv, /admin-actions, /analytics
  telegram.py       # /telegram GET/PATCH
```

`backend/app/routers/admin/__init__.py` must re-export:
`router, _encode_cursor, _decode_cursor, _CSV_MAX_WINDOW_DAYS,
_validate_audit_window` (consumed by two unit tests).

### Module-level singletons → lifespan DI

`_auth`, `_redis`, `_session_store`, `_storage_svc`, `_settings_service`
are lazy globals in `admin.py`. Move initialisation to `app.main`
lifespan and inject via `Depends()`. Enables substitution in tests
without `monkeypatch.setattr(admin_mod, "_redis", ...)`.

### Admin SPA i18n

`admin-frontend/src/` hardcodes Russian throughout. Introduce
`vue-i18n` with `ru/kk/en` locale JSON files mirroring the public
frontend. Breaking points: `views/*.vue` labels/toasts/table headers
(200+ strings), component error messages, toast durations.

### Integration test deadline-polling migration

`tests/integration/conftest.py` now exports a generic `wait_until(
predicate, timeout, interval, message)` helper. 12 test files still
have hand-rolled `while loop.time() < deadline:` loops with
`asyncio.sleep(0.3)`. Migrate each individually — mechanical work,
each site needs its own predicate closure around the existing check.

---

## Schema migrations

Alembic manages all schema changes; see `backend/alembic/versions/`.
Current head: `0011` (composite `(created_at DESC, id DESC)` index on
`transfers` for admin pagination).

For master-key rotation (separate from framework migration), see
`docs/KEY_ROTATION.md`.
