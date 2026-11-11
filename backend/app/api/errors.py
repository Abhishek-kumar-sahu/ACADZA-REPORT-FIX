"""One error envelope for every non-2xx response:
{"error": {"code", "message", "details", "request_id"}}. Stack traces are logged, never returned."""
import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger("acadza.api")

_HTTP_CODES = {400: "bad_request", 401: "auth_required", 403: "forbidden", 404: "not_found",
               405: "method_not_allowed", 409: "conflict", 413: "payload_too_large",
               415: "unsupported_media_type", 422: "validation_failed", 429: "rate_limited"}


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, details=None, headers=None):
        super().__init__(message)
        self.status, self.code, self.message, self.details, self.headers = status, code, message, details, headers


def error_response(request: Request, status: int, code: str, message: str, details=None, headers=None):
    rid = getattr(request.state, "request_id", None)
    body = {"error": {"code": code, "message": message, "details": details, "request_id": rid}}
    return JSONResponse(body, status_code=status, headers=headers)


def install(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api(request: Request, e: ApiError):
        return error_response(request, e.status, e.code, e.message, e.details, e.headers)

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, e: RequestValidationError):
        # Never echo the offending input back (it may be a payload); location + reason is enough.
        details = [{"loc": list(err.get("loc", [])), "msg": err.get("msg"), "type": err.get("type")}
                   for err in e.errors()]
        return error_response(request, 422, "validation_failed", "Request is invalid.", details)

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, e: StarletteHTTPException):
        code = _HTTP_CODES.get(e.status_code, "http_error")
        msg = e.detail if isinstance(e.detail, str) else code
        return error_response(request, e.status_code, code, msg, headers=getattr(e, "headers", None))

    @app.exception_handler(SQLAlchemyError)
    async def _db(request: Request, e: SQLAlchemyError):
        log.error("database error", exc_info=e, extra={"fields": {"request_id": getattr(request.state, "request_id", None)}})
        return error_response(request, 503, "database_error", "The database is unavailable. Try again shortly.")
    # Unhandled exceptions are caught in main.request_context so the 500 keeps X-Request-ID.
