"""Request ID middleware, upload rate limits, and safe API error shaping."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import get_settings
from app.services.rate_limit import check_upload_rate_limit, client_ip_from_headers

logger = logging.getLogger("app.http")


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response


class UploadRateLimitMiddleware(BaseHTTPMiddleware):
    """Cap uploads per client IP so a public demo cannot become free transcription."""

    _UPLOAD_SUFFIXES = (
        "/recordings/initiate",
        "/recordings/upload",
        "/recordings/complete",
    )

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        if request.method in {"POST", "PUT"} and any(
            request.url.path.endswith(suffix) for suffix in self._UPLOAD_SUFFIXES
        ):
            settings = get_settings()
            client = request.client.host if request.client else "unknown"
            ip = client_ip_from_headers(
                {k.lower(): v for k, v in request.headers.items()},
                fallback=client,
            )
            try:
                check_upload_rate_limit(ip, settings)
            except HTTPException as exc:
                request_id = getattr(request.state, "request_id", None) or str(uuid.uuid4())
                detail = exc.detail if isinstance(exc.detail, dict) else {
                    "error": {"code": "rate_limited", "message": str(exc.detail)}
                }
                if request_id and "request_id" not in detail:
                    detail = {**detail, "request_id": request_id}
                return JSONResponse(status_code=exc.status_code, content=detail)
        return await call_next(request)


def _error_body(
    *,
    code: str,
    message: str,
    request_id: str | None,
    details: object | None = None,
) -> dict[str, object]:
    error: dict[str, object] = {"code": code, "message": message}
    if details is not None:
        error["details"] = details
    payload: dict[str, object] = {"error": error}
    if request_id:
        payload["request_id"] = request_id
    return payload


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        request_id = getattr(request.state, "request_id", None)
        detail = exc.detail
        if isinstance(detail, dict) and "error" in detail:
            body = dict(detail)
            if request_id:
                body["request_id"] = request_id
            return JSONResponse(status_code=exc.status_code, content=body)
        message = detail if isinstance(detail, str) else "Request failed."
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_body(code="http_error", message=message, request_id=request_id),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        request_id = getattr(request.state, "request_id", None)
        return JSONResponse(
            status_code=422,
            content=_error_body(
                code="validation_error",
                message="Request validation failed.",
                request_id=request_id,
                details=exc.errors(),
            ),
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        request_id = getattr(request.state, "request_id", None)
        logger.exception("Unhandled error request_id=%s", request_id, exc_info=exc)
        return JSONResponse(
            status_code=500,
            content=_error_body(
                code="internal_error",
                message="An unexpected error occurred.",
                request_id=request_id,
            ),
        )
