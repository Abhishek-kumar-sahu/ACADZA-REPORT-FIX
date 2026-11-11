"""Phase 7: End-to-end integration, performance benchmarking, and security auditing script.
Runs against a live in-process test server and directly validates all Phase 7 requirements.
"""
import hashlib
import json
import os
import sys
import time
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from backend.app.config import ROOT, Settings
from backend.app.db import make_engine, session_factory
from backend.app.importer import import_all
from backend.app.main import create_app
from backend.app.models import AuditEvent, Case, Question, QuestionRevision, Repair, Report, TriageResult, TriageRun
from backend.app.services import audit, triage_store

KEY = "phase7-audit-key-abcdef0123456789"
DATA_DIR = ROOT / "data"


def benchmark_endpoints(client, key):
    """Measure response times for key API routes."""
    routes = [
        ("GET", "/api/v1/health", None, None),
        ("GET", "/api/v1/dashboard", None, None),
        ("GET", "/api/v1/cases?limit=50", None, None),
        ("GET", "/api/v1/cases?status=needs_review", None, None),
        ("GET", "/api/v1/cases/60f744b3f1b9bc7cc7b4a949", None, None),
        ("GET", "/api/v1/reports", None, None),
        ("GET", "/api/v1/reports/R004", None, None),
        ("GET", "/api/v1/questions/60f744b3f1b9bc7cc7b4a949", None, None),
        ("GET", "/api/v1/audit?limit=50", None, None),
        ("GET", "/api/v1/audit/verify", None, None),
        ("GET", "/api/v1/results", None, None),
        ("GET", "/api/v1/bonus-findings", None, None),
        ("GET", "/", None, None),  # Static index.html
        ("GET", "/css/tokens.css", None, None),
        ("GET", "/css/app.css", None, None),
        ("GET", "/js/app.js", None, None),
    ]

    timings = {}
    for method, path, body, headers in routes:
        h = headers or {}
        # Warmup
        client.request(method, path, json=body, headers=h)
        # 5 runs
        runs = []
        for _ in range(5):
            t0 = time.perf_counter()
            r = client.request(method, path, json=body, headers=h)
            dt = (time.perf_counter() - t0) * 1000
            assert r.status_code == 200, f"{path} returned {r.status_code}"
            runs.append(dt)
        timings[path] = {
            "min_ms": round(min(runs), 2),
            "avg_ms": round(sum(runs) / len(runs), 2),
            "max_ms": round(max(runs), 2),
        }
    return timings


def verify_e2e_lifecycle(client, key):
    """Complete lifecycle:
    Report submission → Triage → Investigation → Proposal Editing → Validation → Approval → Execution → Revision → Rollback.
    """
    h = {"X-Faculty-Key": key}
    LCR = "60f744b3f1b9bc7cc7b4a949"

    # 1. Verify triage result exists
    c = client.get(f"/api/v1/cases/{LCR}").json()
    assert c["verdict"] == "defect"
    assert c["repair"] == "answer_key"
    assert c["repairs"][0]["status"] == "proposed"
    repair_id = c["repairs"][0]["id"]

    # 2. Faculty investigation
    r_inv = client.post(f"/api/v1/cases/{LCR}/investigate", json={"actor": "Auditor", "note": "E2E investigation check"}, headers=h)
    assert r_inv.status_code == 200
    assert r_inv.json()["status"] == "investigating"

    # 3. Reopen
    r_reopen = client.post(f"/api/v1/cases/{LCR}/reopen", json={"actor": "Auditor", "note": "Reopening case"}, headers=h)
    assert r_reopen.status_code == 200
    assert r_reopen.json()["status"] in ("needs_review", "untriaged")

    # 4. Dry-run edit validation
    valid_edit = {"field": "answer", "find": "C", "replace": "A"}
    r_val = client.post("/api/v1/validate-edit", json={"question_id": LCR, "repair_type": "answer_key", "edit": valid_edit}, headers=h)
    assert r_val.status_code == 200
    assert r_val.json()["valid"] is True

    # 5. Approve with edited proposal
    r_app = client.post(f"/api/v1/repairs/{repair_id}/approve", json={"actor": "Auditor", "edit": valid_edit, "note": "Approved via audit"}, headers=h)
    assert r_app.status_code == 200
    assert r_app.json()["status"] == "approved_applied"
    assert r_app.json()["preview"]["after"] == "A"

    # 6. Execution
    r_exec = client.post(f"/api/v1/repairs/{repair_id}/execute", json={"actor": "Auditor", "note": "Executing repair"}, headers=h)
    assert r_exec.status_code == 200
    revision_id = r_exec.json()["revision_id"]
    assert r_exec.json()["after"] == "A"

    # Verify live question answer updated
    q_curr = client.get(f"/api/v1/questions/{LCR}").json()
    assert q_curr["answer"] == "A"
    assert q_curr["modified"] is True

    # 7. Rollback
    r_roll = client.post(f"/api/v1/revisions/{revision_id}/rollback", json={"actor": "Auditor", "note": "Rolling back"}, headers=h)
    assert r_roll.status_code == 200
    assert r_roll.json()["restored_to"] == "C"

    # Verify question answer restored
    q_rest = client.get(f"/api/v1/questions/{LCR}").json()
    assert q_rest["answer"] == "C"

    # 8. Duplicate rollback returns 409
    r_dup_roll = client.post(f"/api/v1/revisions/{revision_id}/rollback", json={"actor": "Auditor"}, headers=h)
    assert r_dup_roll.status_code == 409

    # 9. Audit verify
    v = client.get("/api/v1/audit/verify").json()
    assert v["ok"] is True
    return True


def verify_data_integrity(eng):
    """Verify database invariants."""
    with session_factory(eng)() as s:
        # 43 questions
        q_count = s.scalar(select(func.count()).select_from(Question))
        assert q_count == 43, f"Expected 43 questions, got {q_count}"

        # 44 reports
        r_count = s.scalar(select(func.count()).select_from(Report))
        assert r_count == 44, f"Expected 44 reports, got {r_count}"

        # 39 unique reported cases
        c_count = s.scalar(select(func.count()).select_from(Case))
        assert c_count == 39, f"Expected 39 cases, got {c_count}"

        # Verify original_json matches source files exactly
        with open(DATA_DIR / "questions.json", "r", encoding="utf-8") as f:
            src_questions = {q["_id"]: q for q in json.load(f)}
        for q in s.scalars(select(Question)):
            assert q.original == src_questions[q.id], f"Original JSON mismatch for {q.id}"

        # Check results.json
        with open(ROOT / "results.json", "r", encoding="utf-8") as f:
            results_data = json.load(f)
        assert len(results_data) == 44, f"Expected 44 results in results.json, got {len(results_data)}"

        # Check bonus_findings.json
        with open(ROOT / "bonus_findings.json", "r", encoding="utf-8") as f:
            bonus_data = json.load(f)
        assert "findings" in bonus_data
        assert len(bonus_data["findings"]) == 7

        # Check audit chain
        v = audit.verify(s)
        assert v["ok"] is True, f"Audit chain verification failed: {v}"

        # Check no orphaned revisions
        rev_count = s.scalar(select(func.count()).select_from(QuestionRevision))
        for rev in s.scalars(select(QuestionRevision)):
            assert s.get(Question, rev.question_id) is not None

    return {
        "questions": q_count,
        "reports": r_count,
        "cases": c_count,
        "results_json_entries": len(results_data),
        "bonus_findings": len(bonus_data["findings"]),
        "audit_events": v["events"],
        "audit_chain_valid": v["ok"],
    }


def main():
    st = Settings(_env_file=None, database_url="sqlite://", faculty_access_key=KEY, boot_import=True, boot_triage=True)
    eng = make_engine("sqlite://")
    app = create_app(st, engine=eng)

    with TestClient(app) as client:
        # 1. Benchmark
        bench = benchmark_endpoints(client, KEY)

        # 2. Lifecycle
        lifecycle_ok = verify_e2e_lifecycle(client, KEY)

        # 3. Data integrity
        integrity = verify_data_integrity(eng)

    print("--- BENCHMARK RESULTS ---")
    print(json.dumps(bench, indent=2))
    print("\n--- E2E LIFECYCLE ---")
    print(f"Lifecycle test passed: {lifecycle_ok}")
    print("\n--- DATA INTEGRITY ---")
    print(json.dumps(integrity, indent=2))


if __name__ == "__main__":
    main()

