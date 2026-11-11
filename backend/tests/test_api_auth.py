"""Faculty-key authorization (RULES R-85, ADR-016)."""
import io
import logging

import pytest
from fastapi.routing import APIRoute
from pydantic import ValidationError

from backend.app.api import routes
from backend.app.api.deps import require_faculty
from backend.app.config import Settings
from backend.tests.conftest import API, FACULTY_KEY, make_client

LCR = "60f744b3f1b9bc7cc7b4a949"
WRITE_CALLS = [  # every write endpoint, with a valid body
    ("post", "/auth/verify", None),
    ("post", f"/cases/{LCR}/investigate", {"actor": "Meera", "note": "check the key"}),
    ("post", f"/cases/{LCR}/reopen", {"actor": "Meera"}),
    # Phase 5
    ("post", "/repairs/1/approve", {"actor": "Meera"}),
    ("post", "/repairs/1/reject", {"actor": "Meera", "reason": "not needed"}),
    ("post", "/repairs/1/execute", {"actor": "Meera"}),
    ("post", "/revisions/1/rollback", {"actor": "Meera"}),
    ("post", "/reports/R001/duplicate", {"actor": "Meera", "duplicate_of": "R002"}),
    ("put", "/reports/R001/reply", {"actor": "Meera", "reply": "Thank you for reporting."}),
    ("post", "/validate-edit", {"question_id": "a" * 24, "repair_type": "spelling"}),
]

# Map from actual test path to the OpenAPI path pattern for the schema-walk assertion.
_PATH_PATTERNS = {
    f"/cases/{LCR}/investigate": "/cases/{question_id}/investigate",
    f"/cases/{LCR}/reopen": "/cases/{question_id}/reopen",
    "/repairs/1/approve": "/repairs/{repair_id}/approve",
    "/repairs/1/reject": "/repairs/{repair_id}/reject",
    "/repairs/1/execute": "/repairs/{repair_id}/execute",
    "/revisions/1/rollback": "/revisions/{revision_id}/rollback",
    "/reports/R001/duplicate": "/reports/{report_id}/duplicate",
    "/reports/R001/reply": "/reports/{report_id}/reply",
}


def _deps(dependant):
    for d in dependant.dependencies:
        yield d.call
        yield from _deps(d)


def test_every_write_operation_is_on_the_protected_router(api):
    """Public sources only: the OpenAPI schema lists every operation the app serves. Every non-GET
    operation must be one of the `write` router's routes, and each of those carries require_faculty.
    (FastAPI 0.16x mounts routers lazily, so walking app.routes directly would find nothing and pass
    vacuously; hence the non-empty assertions.)"""
    served = {(m, path) for path, ops in api.get(f"{API}/openapi.json").json()["paths"].items()
              for m in ops if m not in ("get", "head")}
    protected = {(m.lower(), API + r.path) for r in routes.write.routes for m in r.methods}
    assert served and served == protected
    for r in routes.write.routes:
        assert isinstance(r, APIRoute) and require_faculty in set(_deps(r.dependant)), r.path
    # Normalize WRITE_CALLS paths to OpenAPI param patterns for comparison.
    import re as _re
    def _normalise(p):
        p = p.replace(LCR, "{question_id}")
        p = _re.sub(r"/\d+/", "/{repair_id}/", p) if "/repairs/" in p else p
        p = _re.sub(r"/\d+/", "/{revision_id}/", p) if "/revisions/" in p else p
        p = _re.sub(r"/R\d+/", "/{report_id}/", p) if "/reports/" in p else p
        return API + p
    normalised = {(m, _normalise(p)) for m, p, _ in WRITE_CALLS}
    assert served == normalised


def test_read_router_is_get_only_and_keyless():
    assert routes.read.routes
    for r in routes.read.routes:
        assert r.methods <= {"GET", "HEAD"}, r.path
        assert require_faculty not in set(_deps(r.dependant)), r.path


@pytest.mark.parametrize("method,path,body", WRITE_CALLS)
def test_missing_key_is_401(api, method, path, body):
    r = api.request(method, API + path, json=body)
    assert r.status_code == 401 and r.json()["error"]["code"] == "auth_required"
    assert r.headers["WWW-Authenticate"].startswith("FacultyKey")


@pytest.mark.parametrize("bad", ["wrong", FACULTY_KEY[:-1], FACULTY_KEY + "x", FACULTY_KEY.upper(), " " + FACULTY_KEY])
@pytest.mark.parametrize("method,path,body", WRITE_CALLS)
def test_wrong_key_is_403(api, method, path, body, bad):
    r = api.request(method, API + path, json=body, headers={"X-Faculty-Key": bad})
    assert r.status_code == 403 and r.json()["error"]["code"] == "forbidden"


def test_empty_header_is_401(api):
    r = api.post(f"{API}/auth/verify", headers={"X-Faculty-Key": ""})
    assert r.status_code == 401


def test_auth_checked_before_body_validation(api):
    """An unauthenticated caller learns nothing about the body schema."""
    r = api.post(f"{API}/cases/{LCR}/investigate", json={"evil": 1})
    assert r.status_code == 401


@pytest.mark.parametrize("key", [None, "", "short-key"])   # unset, empty, < 16 chars
@pytest.mark.parametrize("method,path,body", WRITE_CALLS)
def test_writes_disabled_without_configured_key(engine, method, path, body, key):
    with make_client(engine, key=key) as c:
        r = c.request(method, API + path, json=body, headers={"X-Faculty-Key": key or "anything"})
        assert r.status_code == 503 and r.json()["error"]["code"] == "writes_disabled"
        assert c.get(f"{API}/auth/status").json() == {"writes_enabled": False}
        assert c.get(f"{API}/dashboard").status_code == 200   # reads still work


def test_valid_key_investigate_reopen_cycle(api):
    h = {"X-Faculty-Key": FACULTY_KEY}
    assert api.post(f"{API}/auth/verify", headers=h).json() == {"ok": True}
    r = api.post(f"{API}/cases/{LCR}/investigate", json={"actor": "Meera", "note": "solution says 50 V"}, headers=h)
    assert r.status_code == 200 and r.json()["status"] == "investigating"
    assert r.json()["urgency_breakdown"]["review"] == 20
    ev = api.get(f"{API}/audit", params={"event_type": "investigation_requested"}).json()["items"][0]
    assert (ev["actor"], ev["actor_type"], ev["before"], ev["after"]) == (
        "faculty:Meera", "faculty", {"status": "untriaged"}, {"status": "investigating"})
    again = api.post(f"{API}/cases/{LCR}/investigate", json={"actor": "Meera", "note": "again"}, headers=h)
    assert again.status_code == 409 and again.json()["error"]["code"] == "conflict"
    back = api.post(f"{API}/cases/{LCR}/reopen", json={"actor": "Meera"}, headers=h)
    assert back.status_code == 200 and back.json()["status"] == "untriaged"
    assert api.post(f"{API}/cases/{LCR}/reopen", json={"actor": "Meera"}, headers=h).status_code == 409
    assert api.get(f"{API}/audit/verify").json()["ok"] is True


@pytest.mark.parametrize("body", [
    {"actor": "Meera"},                                   # note missing
    {"actor": "M", "note": "too short actor"},
    {"actor": "<script>", "note": "bad chars"},
    {"actor": "Meera", "note": "x" * 501},
    {"actor": "Meera", "note": "ok note", "route": "auto_apply"},   # extra field
])
def test_authorised_but_invalid_body_is_422(api, body):
    r = api.post(f"{API}/cases/{LCR}/investigate", json=body, headers={"X-Faculty-Key": FACULTY_KEY})
    assert r.status_code == 422 and r.json()["error"]["code"] == "validation_failed"
    assert "<script>" not in r.text   # offending input is not echoed


def test_unknown_case_with_valid_key_is_404(api):
    r = api.post(f"{API}/cases/{'f' * 24}/investigate", json={"actor": "Meera", "note": "nope"},
                 headers={"X-Faculty-Key": FACULTY_KEY})
    assert r.status_code == 404


def test_key_never_leaks(api):
    """Not in any read response, response header, or log line, even after an authenticated write."""
    buf = io.StringIO()
    handler = logging.StreamHandler(buf)
    logging.getLogger("acadza").addHandler(handler)
    try:
        api.post(f"{API}/cases/{LCR}/investigate", json={"actor": "Meera", "note": "leak check"},
                 headers={"X-Faculty-Key": FACULTY_KEY})
        api.post(f"{API}/auth/verify", headers={"X-Faculty-Key": "wrong-key"})
        bodies = [api.get(API + p) for p in ("/health", "/settings", "/auth/status", "/dashboard",
                                             f"/cases/{LCR}", "/audit?limit=200", "/openapi.json")]
    finally:
        logging.getLogger("acadza").removeHandler(handler)
    for r in bodies:
        assert FACULTY_KEY not in r.text and FACULTY_KEY not in str(r.headers)
    assert FACULTY_KEY not in buf.getvalue() and "wrong-key" not in buf.getvalue()
    assert "leak check" not in buf.getvalue()   # request bodies are not logged


def test_secret_not_in_settings_repr():
    st = Settings(_env_file=None, faculty_access_key=FACULTY_KEY)
    assert FACULTY_KEY not in repr(st) and FACULTY_KEY not in str(st.model_dump())


def test_cors(engine):
    with make_client(engine, cors_origins="http://localhost:5500") as c:
        ok = c.options(f"{API}/cases", headers={"Origin": "http://localhost:5500",
                                                "Access-Control-Request-Method": "POST",
                                                "Access-Control-Request-Headers": "X-Faculty-Key"})
        assert ok.headers.get("access-control-allow-origin") == "http://localhost:5500"
        bad = c.get(f"{API}/health", headers={"Origin": "https://evil.example"})
        assert "access-control-allow-origin" not in bad.headers
    with make_client(engine) as c:   # default: same-origin only
        assert "access-control-allow-origin" not in c.get(f"{API}/health", headers={"Origin": "http://x"}).headers


def test_cors_wildcard_rejected():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, cors_origins="*")
