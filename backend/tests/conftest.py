import json
import os
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from backend.app.config import ROOT, Settings
from backend.app.db import init_db, make_engine, session_factory
from backend.app.importer import import_all
from backend.app.main import create_app
from backend.app.models import Base
from backend.app.triage.record import parse_record

DATA = ROOT / "data"


@pytest.fixture(scope="session")
def questions() -> list[dict]:
    return json.loads((DATA / "questions.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def reports() -> list[dict]:
    return json.loads((DATA / "reports.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def qmap(questions) -> dict[str, dict]:
    return {q["_id"]: q for q in questions}


@pytest.fixture(scope="session")
def parsed(questions):
    return {q["_id"]: parse_record(q) for q in questions}


def _backends():
    yield "sqlite"
    if os.environ.get("TEST_POSTGRES_URL"):
        yield pytest.param("postgres", marks=pytest.mark.postgres)


@pytest.fixture(params=list(_backends()))
def engine(request):
    if request.param == "sqlite":
        eng = make_engine("sqlite://")
    else:
        eng = make_engine(os.environ["TEST_POSTGRES_URL"])
        Base.metadata.drop_all(eng)
    init_db(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def session(engine):
    with session_factory(engine)() as s:
        import_all(s, DATA)
        yield s


# ------------------------------------------------------------------ API helpers (Phase 3)

FACULTY_KEY = "test-faculty-key-" + "k" * 24          # >= 16 chars
FIXED_NOW = datetime(2026, 11, 10, 0, 0, tzinfo=timezone.utc)
API = "/api/v1"


def make_client(engine, *, key: str | None = FACULTY_KEY, boot_import: bool = True, boot_triage: bool = False,
                **settings_kw):
    # boot_triage defaults to False HERE so the Phase 3 tests keep exercising the pre-triage contract
    # (untriaged cases, 45 import audit events) exactly as written. Post-triage behaviour is tested via
    # the `api_triaged` fixture. The production default (Settings.boot_triage) is True.
    st = Settings(_env_file=None, database_url="sqlite://", faculty_access_key=key,
                  boot_import=boot_import, boot_triage=boot_triage, **settings_kw)
    app = create_app(st, engine=engine, clock=lambda: FIXED_NOW)
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def api(engine):
    with make_client(engine) as client:
        yield client


@pytest.fixture
def api_triaged(engine):
    with make_client(engine, boot_triage=True) as client:
        yield client


@pytest.fixture
def auth():
    return {"X-Faculty-Key": FACULTY_KEY}
