"""FastAPI application factory. Run: uvicorn backend.app.main:app"""
import json
import logging
import re
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select
from sqlalchemy.engine import Engine

from .api import errors
from .api.errors import error_response
from .api.routes import read, write
from .config import APP_VERSION, Settings, settings as default_settings
from .db import init_db, make_engine, session_factory
from .importer import import_all
from .models import Question, TriageRun, utcnow
from .services.triage_store import run_and_store

log = logging.getLogger("acadza")
API_PREFIX = "/api/v1"
_RID = re.compile(r"^[A-Za-z0-9-]{8,64}$")
_SECURITY_HEADERS = {"X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY",
                     "Referrer-Policy": "no-referrer", "Cache-Control": "no-store"}
# Sanitised question HTML carries no style attributes, so 'self' stylesheets are enough.
CONSOLE_CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; font-src 'self'; "
               "img-src 'self' https:; connect-src 'self'; object-src 'none'; base-uri 'none'; "
               "form-action 'none'; frame-ancestors 'none'")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        out = {"ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"), "level": record.levelname,
               "logger": record.name, "msg": record.getMessage(), **getattr(record, "fields", {})}
        if record.exc_info:
            out["exc"] = self.formatException(record.exc_info)
        return json.dumps(out, default=str)


def configure_logging(level: str) -> None:
    logger = logging.getLogger("acadza")
    if not any(getattr(h, "_acadza", False) for h in logger.handlers):
        h = logging.StreamHandler()
        h.setFormatter(JsonFormatter())
        h._acadza = True
        logger.addHandler(h)
    logger.setLevel(level.upper())
    logger.propagate = False


def create_app(settings: Settings | None = None, engine: Engine | None = None, clock=utcnow) -> FastAPI:
    st = settings or default_settings
    configure_logging(st.log_level)
    owns_engine = engine is None

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        eng = engine or make_engine(st.database_url)
        init_db(eng)
        app.state.engine, app.state.sessionmaker = eng, session_factory(eng)
        if st.boot_import:
            with app.state.sessionmaker() as s:
                if not s.scalar(select(func.count()).select_from(Question)):
                    log.info("empty database: importing data", extra={"fields": import_all(s, st.data_dir)})
        if st.boot_triage:
            with app.state.sessionmaker() as s:
                if s.scalar(select(func.count()).select_from(Question)) and \
                        not s.scalar(select(func.count()).select_from(TriageRun)):
                    run, decisions = run_and_store(s)
                    log.info("no triage yet: ran rules engine", extra={"fields": {"run_id": run.id,
                                                                                  "decisions": len(decisions)}})
        if not st.writes_enabled:
            log.warning("faculty writes DISABLED: FACULTY_ACCESS_KEY unset or shorter than 16 chars")
        log.info("startup", extra={"fields": {"db": eng.dialect.name, "version": APP_VERSION}})
        yield
        if owns_engine:
            eng.dispose()

    app = FastAPI(title="Acadza Report → Fix API", version=APP_VERSION, lifespan=lifespan,
                  docs_url=f"{API_PREFIX}/reference", openapi_url=f"{API_PREFIX}/openapi.json", redoc_url=None,
                  swagger_ui_oauth2_redirect_url=None)
    app.state.settings, app.state.clock, app.state.version = st, clock, APP_VERSION
    errors.install(app)
    app.include_router(read, prefix=API_PREFIX)
    app.include_router(write, prefix=API_PREFIX)

    if st.cors_origin_list:  # dev only; production is same-origin
        app.add_middleware(CORSMiddleware, allow_origins=st.cors_origin_list, allow_credentials=False,
                           allow_methods=["GET", "POST", "PUT"],
                           allow_headers=["Content-Type", "X-Faculty-Key", "X-Request-ID"])

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        incoming = request.headers.get("x-request-id", "")
        request.state.request_id = incoming if _RID.match(incoming) else uuid.uuid4().hex[:16]
        start = time.perf_counter()
        # ponytail: trusts Content-Length; chunked bodies are bounded by the Pydantic field limits.
        length = request.headers.get("content-length")
        if length and length.isdigit() and int(length) > st.max_body_bytes:
            response = error_response(request, 413, "payload_too_large",
                                      f"Request body exceeds {st.max_body_bytes} bytes.")
        else:
            try:
                response = await call_next(request)
            except Exception as e:  # unhandled: same envelope + request id as every other error
                log.error("unhandled error", exc_info=e, extra={"fields": {"request_id": request.state.request_id}})
                response = error_response(request, 500, "internal_error", "Something went wrong on our side.")
        response.headers["X-Request-ID"] = request.state.request_id
        for k, v in _SECURITY_HEADERS.items():
            response.headers.setdefault(k, v)
        if not request.url.path.startswith("/api/"):   # the console: self-only, no inline script
            response.headers.setdefault("Content-Security-Policy", CONSOLE_CSP)
        # Never log headers (X-Faculty-Key) or bodies (student comments).
        log.info("request", extra={"fields": {
            "request_id": request.state.request_id, "method": request.method, "path": request.url.path,
            "status": response.status_code, "ms": round((time.perf_counter() - start) * 1000, 1)}})
        return response

    # Faculty console (Phase 6): static files mounted LAST so every /api/v1 route wins.
    if st.frontend_dir.is_dir():
        app.mount("/", StaticFiles(directory=st.frontend_dir, html=True), name="console")
    return app


app = create_app()
