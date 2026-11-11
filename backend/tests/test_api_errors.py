"""Error envelope consistency, database failures, empty datasets, payload limits, headers."""
import pytest
from sqlalchemy import text

from backend.app.services import views
from backend.tests.conftest import API, FACULTY_KEY, make_client

LIST_ENDPOINTS = ["/cases", "/reports", "/audit", "/revisions"]


def _is_envelope(r, status, code=None):
    body = r.json()
    assert r.status_code == status, r.text[:200]
    assert set(body) == {"error"} and set(body["error"]) == {"code", "message", "details", "request_id"}
    assert body["error"]["request_id"] == r.headers["X-Request-ID"]
    if code:
        assert body["error"]["code"] == code


@pytest.mark.parametrize("method,path,status,code", [
    ("get", "/nope", 404, "not_found"),
    ("get", "/cases/zz", 422, "validation_failed"),
    ("get", f"/cases/{'f' * 24}", 404, "not_found"),
    ("get", "/reports/R999", 404, "not_found"),
    ("delete", "/cases", 405, "method_not_allowed"),
    ("post", "/auth/verify", 401, "auth_required"),
])
def test_error_envelope_shape(api, method, path, status, code):
    _is_envelope(api.request(method, API + path), status, code)


def test_unversioned_api_is_404(api):
    assert api.get("/api/cases").status_code == 404


def test_list_shape(api):
    for p in LIST_ENDPOINTS:
        body = api.get(API + p).json()
        assert set(body) == {"total", "limit", "offset", "items"}, p
        assert isinstance(body["items"], list) and body["limit"] == 50 and body["offset"] == 0


def test_security_and_request_id_headers(api):
    r = api.get(f"{API}/health", headers={"X-Request-ID": "trace-12345678"})
    assert r.headers["X-Request-ID"] == "trace-12345678"
    for h, v in {"X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY",
                 "Referrer-Policy": "no-referrer"}.items():
        assert r.headers[h] == v
    bad = api.get(f"{API}/health", headers={"X-Request-ID": "<script>"})
    assert bad.headers["X-Request-ID"] != "<script>" and len(bad.headers["X-Request-ID"]) == 16


def test_payload_too_large(api):
    r = api.post(f"{API}/cases/{'6' * 24}/investigate", content=b"x" * (64 * 1024 + 1),
                 headers={"X-Faculty-Key": FACULTY_KEY, "Content-Type": "application/json"})
    _is_envelope(r, 413, "payload_too_large")


def test_database_error_is_503_without_details(api):
    with api.app.state.engine.begin() as c:
        c.execute(text("DROP TABLE cases"))
    r = api.get(f"{API}/cases")
    _is_envelope(r, 503, "database_error")
    assert "cases" not in r.json()["error"]["message"].lower() and "Traceback" not in r.text
    _is_envelope(api.get(f"{API}/dashboard"), 503, "database_error")


def test_unhandled_error_is_500_without_leak(api, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("secret internal detail")
    monkeypatch.setattr(views, "dashboard", boom)
    r = api.get(f"{API}/dashboard")
    _is_envelope(r, 500, "internal_error")
    assert "secret internal detail" not in r.text


def test_empty_dataset(engine):
    """Fresh DB with no import: every read returns an empty, well-formed answer, never an error."""
    with make_client(engine, boot_import=False) as c:
        h = c.get(f"{API}/health").json()
        assert h["data_imported"] is False and h["counts"] == {"questions": 0, "reports": 0, "cases": 0}
        d = c.get(f"{API}/dashboard").json()
        assert all(v == 0 for v in d["metrics"].values())
        assert d["urgent"] == [] and d["by_subject"] == [] and d["recent_activity"] == []
        for p in LIST_ENDPOINTS:
            assert c.get(API + p).json() == {"total": 0, "limit": 50, "offset": 0, "items": []}, p
        assert c.get(f"{API}/audit/verify").json() == {"ok": True, "events": 0, "first_bad_id": None}
        assert c.get(f"{API}/questions/{'6' * 24}").status_code == 404
        assert c.get(f"{API}/cases/{'6' * 24}").status_code == 404
        assert c.get(f"{API}/taxonomy").status_code == 200
        assert c.get(f"{API}/settings").json()["data_sha256"] is None


def test_boot_import_is_idempotent(engine):
    with make_client(engine) as c:
        assert c.get(f"{API}/health").json()["counts"]["reports"] == 44
    with make_client(engine) as c:   # second boot on the same DB must not duplicate anything
        assert c.get(f"{API}/health").json()["counts"] == {"questions": 43, "reports": 44, "cases": 39}
        assert c.get(f"{API}/audit").json()["total"] == 45


def test_openapi_lists_versioned_paths_only(api):
    paths = api.get(f"{API}/openapi.json").json()["paths"]
    assert paths and all(p.startswith(API + "/") for p in paths)
