"""HawkAPI application shims for the Fylix codebase.

Three behaviours we standardise on top of HawkAPI 0.1.4:

  1. Structured error envelope. Both tests and the Vue frontend expect
     an error body shaped as ``{"detail": <rich>}`` (with ``<rich>``
     either a string or a dict like ``{"error": "invalid_credentials"}``).
     HawkAPI's native ``HTTPException.detail`` is declared as ``str`` and
     its default renderer emits RFC 9457 Problem Details JSON, which
     doesn't match our contract. This module provides a dict-tolerant
     subclass and overrides ``to_response()`` on both the subclass and
     the base class so the wire format is consistent.

  2. Multiple Set-Cookie on a single response. HawkAPI response
     ``headers`` is ``dict[str, str]`` which silently collapses duplicate
     keys — so a login flow that sets both a session cookie and a csrf
     cookie would lose one. The ``set_cookie`` / ``delete_cookie``
     helpers stash cookies under a sentinel key then splice them as raw
     ``(b"set-cookie", ...)`` tuples inside a monkey-patched
     ``_build_raw_headers`` on the three response classes (Response,
     JSONResponse, StreamingResponse — each owns an independent
     headers-building path, they do not share a base class).

  3. HEAD / OPTIONS route decorators. ``Router`` ships only
     get/post/patch/put/delete/websocket; TUS needs HEAD. We alias
     ``.head()`` / ``.options()`` onto ``add_route(..., methods={...})``.

Bootstrap from ``app.main`` by calling ``install_hawkapi_shims()`` before
any ``Router`` is constructed (in practice, before ``from app.routers
import *``).
"""
from __future__ import annotations

from typing import Any

from hawkapi import HTTPException as _HawkHTTPException
from hawkapi import JSONResponse, Response, Router
from hawkapi.responses import StreamingResponse


def _render_error_envelope(
    status_code: int,
    detail: Any,
    headers: dict[str, str] | None,
) -> JSONResponse:
    return JSONResponse(
        {"detail": detail},
        status_code=status_code,
        headers=headers or {},
    )


class HTTPException(_HawkHTTPException):
    """Dict-detail variant that renders the Fylix error envelope.

    HawkAPI catches ``HTTPException`` at request-dispatch time and calls
    ``exc.to_response()`` directly — bypassing the app's registered
    ``exception_handlers`` map. To emit the ``{"detail": <rich>}`` shape
    required by our tests and the admin SPA, we override
    ``to_response()`` itself.
    """

    def __init__(
        self,
        status_code: int,
        detail: Any = None,
        *,
        headers: dict[str, str] | None = None,
    ) -> None:
        str_detail = detail if isinstance(detail, str) else (
            "" if detail is None else str(detail)
        )
        super().__init__(status_code, detail=str_detail, headers=headers)
        # Parent stores `str_detail` on `.detail` (its declared type is str);
        # we re-assign the original object so callers that read `exc.detail`
        # get dict-index access back (e.g. `exc.detail["error"]` in tests).
        self.detail = detail  # type: ignore[assignment]
        self.rich_detail: Any = detail

    def to_response(self) -> JSONResponse:  # type: ignore[override]
        return _render_error_envelope(self.status_code, self.rich_detail, self.headers)


def _patched_base_to_response(self: _HawkHTTPException) -> JSONResponse:
    """Render raw ``hawkapi.HTTPException`` in Fylix envelope shape.

    Some callsites import ``hawkapi.HTTPException`` directly (plain
    string details). Overriding its ``to_response`` globally keeps the
    wire format consistent with our subclass.
    """
    return _render_error_envelope(self.status_code, self.detail, self.headers)


def install_error_handlers(app: Any) -> None:
    """Ensure both our subclass and the base ``HTTPException`` render the
    Fylix error envelope.

    Idempotent. Takes ``app`` for API symmetry — the actual override is
    on the exception classes themselves because HawkAPI catches
    ``HTTPException`` before reaching ``app._exception_handlers``.
    """
    _ = app  # unused; kept so caller sites read naturally
    if not getattr(_HawkHTTPException, "_fylix_patched", False):
        _HawkHTTPException.to_response = _patched_base_to_response  # type: ignore[method-assign]
        _HawkHTTPException._fylix_patched = True  # type: ignore[attr-defined]


# --- Cookie support ---------------------------------------------------------

_COOKIE_SENTINEL = "x-fylix-cookie-list"
_COOKIE_SEP = "\x1f"


def set_cookie(
    response: Response | JSONResponse | StreamingResponse,
    name: str,
    value: str,
    *,
    max_age: int | None = None,
    path: str = "/",
    domain: str | None = None,
    secure: bool = True,
    httponly: bool = True,
    samesite: str | None = "lax",
) -> None:
    """Attach a Set-Cookie header to `response`. Supports multiple cookies."""
    parts: list[str] = [f"{name}={value}"]
    if max_age is not None:
        parts.append(f"Max-Age={int(max_age)}")
    if domain:
        parts.append(f"Domain={domain}")
    parts.append(f"Path={path}")
    if secure:
        parts.append("Secure")
    if httponly:
        parts.append("HttpOnly")
    if samesite:
        parts.append(f"SameSite={samesite.capitalize()}")
    cookie_str = "; ".join(parts)
    # Access the private headers dict directly — JSONResponse exposes no
    # public `.headers` property (only `_headers`), but both the plain
    # Response and StreamingResponse do. Going via `_headers` keeps one
    # code-path across all three response classes.
    existing = response._headers.get(_COOKIE_SENTINEL, "")
    response._headers[_COOKIE_SENTINEL] = (
        f"{existing}{_COOKIE_SEP}{cookie_str}" if existing else cookie_str
    )


def delete_cookie(
    response: Response | JSONResponse | StreamingResponse,
    name: str,
    *,
    path: str = "/",
    domain: str | None = None,
) -> None:
    set_cookie(
        response,
        name,
        "",
        max_age=0,
        path=path,
        domain=domain,
        secure=False,
        httponly=False,
        samesite=None,
    )


def _patch_build_raw_headers(cls: type) -> None:
    if getattr(cls, "_fylix_cookie_patched", False):
        return
    original = cls._build_raw_headers  # type: ignore[attr-defined]

    def patched(self: Any) -> list[tuple[bytes, bytes]]:
        extras = self._headers.pop(_COOKIE_SENTINEL, None) if self._headers else None
        raw = original(self)
        if extras:
            for cookie_str in extras.split(_COOKIE_SEP):
                if cookie_str:
                    raw.append((b"set-cookie", cookie_str.encode("latin-1")))
        return raw

    cls._build_raw_headers = patched  # type: ignore[attr-defined]
    cls._fylix_cookie_patched = True  # type: ignore[attr-defined]


def install_cookie_support() -> None:
    """Patch Response / JSONResponse / StreamingResponse header builders.

    Idempotent. Each class has its own independent `_build_raw_headers`
    (they do NOT share a base), so each needs patching separately.
    """
    for cls in (Response, JSONResponse, StreamingResponse):
        _patch_build_raw_headers(cls)


# --- Router method aliases --------------------------------------------------

def _make_method_decorator(method_name: str):
    def decorator_factory(self: Router, path: str, **kwargs: Any):
        def decorator(fn):
            self.add_route(path, fn, methods={method_name}, **kwargs)
            return fn
        return decorator
    decorator_factory.__name__ = method_name.lower()
    return decorator_factory


def install_router_method_aliases() -> None:
    """Add `.head()` and `.options()` decorators on Router. Idempotent."""
    if not hasattr(Router, "head"):
        Router.head = _make_method_decorator("HEAD")  # type: ignore[attr-defined]
    if not hasattr(Router, "options"):
        Router.options = _make_method_decorator("OPTIONS")  # type: ignore[attr-defined]


def install_post_default_status() -> None:
    """Make ``@router.post(...)`` default to ``status_code=200`` instead of 201.

    HawkAPI's ``Router.post`` defaults to 201 Created; the admin SPA and
    tests expect 200 unless a route explicitly sets 201. Idempotent.
    """
    if getattr(Router, "_fylix_post_default_patched", False):
        return

    original_post = Router.post

    def patched_post(self: Router, path: str, *, status_code: int = 200, **kwargs: Any):
        return original_post(self, path, status_code=status_code, **kwargs)

    Router.post = patched_post  # type: ignore[method-assign]
    Router._fylix_post_default_patched = True  # type: ignore[attr-defined]


# --- Pydantic-aware msgspec encoder hook -----------------------------------

def install_pydantic_encoder_hook() -> None:
    """Teach HawkAPI's msgspec encoder how to serialize Pydantic models.

    Our schemas (``app/schemas/*``) are ``pydantic.BaseModel`` subclasses.
    HawkAPI's stock ``_enc_hook`` only handles datetime / UUID / set /
    bytes and raises ``TypeError`` for everything else, so a handler that
    returns a ``BaseModel`` instance crashes with 500 at serialization
    time. We wrap the hook to intercept BaseModel and call
    ``.model_dump(mode="json")`` before deferring to the original for any
    other types. Idempotent.
    """
    from hawkapi.serialization import encoder as _enc_mod

    try:
        from pydantic import BaseModel
    except ImportError:
        return

    if getattr(_enc_mod, "_fylix_pydantic_patched", False):
        return

    import msgspec

    original_hook = _enc_mod._enc_hook

    def patched_hook(obj: Any) -> Any:
        if isinstance(obj, BaseModel):
            return obj.model_dump(mode="json")
        return original_hook(obj)

    _enc_mod._enc_hook = patched_hook
    # The pre-built encoder bakes in the hook at construction time,
    # so we must rebuild it too.
    _enc_mod._encoder_with_hook = msgspec.json.Encoder(enc_hook=patched_hook)
    _enc_mod._msgpack_encoder_with_hook = msgspec.msgpack.Encoder(enc_hook=patched_hook)
    _enc_mod._fylix_pydantic_patched = True


# --- Pydantic ValidationError -> HawkAPI RequestValidationError -----------

def install_pydantic_validation_hook() -> None:
    """Translate ``pydantic.ValidationError`` into HawkAPI's
    ``RequestValidationError`` so body-decoding failures render 422, not 500.

    HawkAPI ships a Pydantic adapter whose ``decode_pydantic`` calls
    ``model_validate_json`` and re-raises the raw ``pydantic.ValidationError``.
    HawkAPI's request dispatch only catches ``RequestValidationError`` — any
    other exception turns into a 500. We wrap the adapter to translate the
    errors into the shape HawkAPI expects.
    """
    from hawkapi._compat import pydantic_adapter
    from hawkapi.validation import RequestValidationError, ValidationErrorDetail

    try:
        from pydantic import ValidationError as PydanticValidationError
    except ImportError:
        return

    if getattr(pydantic_adapter, "_fylix_validation_patched", False):
        return

    original = pydantic_adapter.decode_pydantic

    def patched(model_class: type, data: bytes) -> Any:
        try:
            return original(model_class, data)
        except PydanticValidationError as exc:
            errors = [
                ValidationErrorDetail(
                    field=".".join(str(p) for p in err.get("loc", ())),
                    message=str(err.get("msg", "")),
                    value=err.get("input"),
                )
                for err in exc.errors()
            ]
            raise RequestValidationError(errors, status_code=422) from exc

    pydantic_adapter.decode_pydantic = patched
    # Other modules may have already done `from ... import decode_pydantic`
    # at import time — patch those call-sites too.
    from hawkapi.di import resolver as _resolver
    if hasattr(_resolver, "decode_pydantic"):
        _resolver.decode_pydantic = patched
    pydantic_adapter._fylix_validation_patched = True


def install_validation_error_renderer() -> None:
    """Render ``RequestValidationError`` as the Fylix envelope instead of
    RFC 9457 Problem Details.

    Body shape after this patch:

        {"detail": [{"loc": [...], "msg": "...", "type": "..."}, ...]}

    matching the error structure the admin SPA and tests consume.
    """
    from hawkapi import app as _hawk_app
    from hawkapi.validation import RequestValidationError

    if getattr(_hawk_app, "_fylix_validation_renderer_patched", False):
        return

    def patched_builder(self: Any, exc: RequestValidationError) -> JSONResponse:
        detail = [
            {
                "loc": getattr(e, "field", "").split(".") if getattr(e, "field", "") else [],
                "msg": getattr(e, "message", ""),
                "type": "value_error",
            }
            for e in exc.errors
        ]
        return JSONResponse(
            {"detail": detail},
            status_code=self.validation_error_status,
        )

    _hawk_app.HawkAPI._build_validation_error_response = patched_builder
    _hawk_app._fylix_validation_renderer_patched = True


# --- Streaming-response passthrough ----------------------------------------

def install_streaming_response_passthrough() -> None:
    """Treat ``StreamingResponse`` as a direct response in ``_build_response``.

    HawkAPI's ``_build_response`` short-circuits when the handler returns a
    ``Response`` or ``JSONResponse`` instance — but ``StreamingResponse``
    inherits from neither, so it falls through and HawkAPI tries to JSON-
    encode the whole object (which blows up). We wrap the method to add the
    StreamingResponse check.
    """
    from hawkapi import app as _hawk_app

    if getattr(_hawk_app, "_fylix_streaming_passthrough_patched", False):
        return

    original = _hawk_app.HawkAPI._build_response

    def patched(self: Any, result: Any, status_code: int, *args: Any, **kwargs: Any) -> Any:
        if isinstance(result, StreamingResponse):
            return result
        return original(self, result, status_code, *args, **kwargs)

    _hawk_app.HawkAPI._build_response = patched
    _hawk_app._fylix_streaming_passthrough_patched = True


# --- Pydantic response_model support ---------------------------------------

def install_response_model_hook() -> None:
    """Accept Pydantic ``BaseModel`` returns when a route declares
    ``response_model=SomeModel``.

    HawkAPI's ``_apply_response_model`` normalises the handler result via
    ``msgspec.to_builtins``. For msgspec-native types that's fine, but a
    Pydantic ``BaseModel`` instance raises ``TypeError: Encoding objects of
    type ... is unsupported``. We normalise first with ``.model_dump`` then
    defer to the original.
    """
    from hawkapi import app as _hawk_app

    try:
        from pydantic import BaseModel
    except ImportError:
        return

    if getattr(_hawk_app, "_fylix_response_model_patched", False):
        return

    original = _hawk_app.HawkAPI._apply_response_model

    def patched(result: Any, response_model: type) -> Any:
        if isinstance(result, BaseModel):
            return result.model_dump(mode="json")
        if isinstance(result, list) and result and isinstance(result[0], BaseModel):
            return [item.model_dump(mode="json") for item in result]
        return original(result, response_model)

    # _apply_response_model is a @staticmethod on HawkAPI.
    _hawk_app.HawkAPI._apply_response_model = staticmethod(patched)
    _hawk_app._fylix_response_model_patched = True


def install_hawkapi_shims() -> None:
    """Apply all module-level monkey-patches. Idempotent.

    Must be called before any Router / response class is used.
    """
    install_cookie_support()
    install_router_method_aliases()
    install_post_default_status()
    install_pydantic_encoder_hook()
    install_pydantic_validation_hook()
    install_validation_error_renderer()
    install_streaming_response_passthrough()
    install_response_model_hook()
