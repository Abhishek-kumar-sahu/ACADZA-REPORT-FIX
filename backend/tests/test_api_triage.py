"""Phase 4 API integration: boot triage, /results, /bonus-findings, /triage/runs, case statuses,
and the guarantee that triage proposes but never applies."""
import json
from collections import Counter

from sqlalchemy import func, select

from backend.app.config import ROOT
from backend.app.models import Question, QuestionRevision, Repair, TriageResult
from backend.app.services.triage_store import run_and_store
from backend.tests.conftest import API, FACULTY_KEY

LCR = "60f744b3f1b9bc7cc7b4a949"


def get(c, path, **params):
    r = c.get(API + path, params=params)
    assert r.status_code == 200, r.text[:300]
    return r.json()


def test_results_endpoint_equals_committed_file(api_triaged):
    assert get(api_triaged, "/results") == json.loads((ROOT / "results.json").read_text(encoding="utf-8"))


def test_bonus_endpoint_equals_committed_file(api_triaged):
    b = get(api_triaged, "/bonus-findings")
    committed = json.loads((ROOT / "bonus_findings.json").read_text(encoding="utf-8"))
    assert b["items"] == committed["findings"] and b["questions_inspected"] == 43
    assert all("reportId" not in f for f in b["items"])


def test_triage_runs_listed(api_triaged):
    runs = get(api_triaged, "/triage/runs")
    assert runs["total"] == 1 and runs["items"][0]["mode"] in ("rules_only", "llm") and runs["items"][0]["calls"] == 0


def test_dashboard_after_triage_matches_results(api_triaged):
    results = get(api_triaged, "/results")
    m = get(api_triaged, "/dashboard")["metrics"]
    assert m["confirmed_defects"] == sum(r["verdict"] == "defect" for r in results)
    assert m["auto_eligible"] == sum(r["route"] == "auto_apply" for r in results)
    assert m["auto_applied"] == 0 and m["untriaged"] == 0
    statuses = Counter(c["status"] for c in get(api_triaged, "/cases", limit=200)["items"])
    assert sum(statuses.values()) == 39 and m["needs_review"] == statuses["needs_review"]


def test_case_status_follows_routes(api_triaged):
    results = get(api_triaged, "/results")
    by_q = {}
    for r in results:
        by_q.setdefault(r["questionId"], set()).add(r["route"])
    for c in get(api_triaged, "/cases", limit=200)["items"]:
        routes = by_q[c["question_id"]]
        want = "needs_review" if "faculty_review" in routes else "auto_pending" if "auto_apply" in routes else "no_change"
        assert c["status"] == want, c["question_id"]


def test_case_detail_exposes_evidence_inference_recommendation(api_triaged):
    c = get(api_triaged, f"/cases/{LCR}")
    assert c["verdict"] == "defect" and c["repair"] == "answer_key" and c["urgency_breakdown"]["impact"] == 40
    res = c["reports"][0]["result"]
    for k in ("facts", "inference", "recommendation", "review_reason", "confidence_basis", "key_status"):
        assert res[k], k
    assert [r["repair_type"] for r in c["repairs"]] == ["answer_key"]
    assert sorted(c["repairs"][0]["report_ids"]) == ["R001", "R002", "R003"]   # one repair, three reports (R-61)
    assert c["repairs"][0]["status"] == "proposed"


def test_triage_never_applies_anything(api_triaged, qmap):
    sm = api_triaged.app.state.sessionmaker
    with sm() as s:
        assert s.scalar(select(func.count()).select_from(QuestionRevision)) == 0
        assert {r.status for r in s.scalars(select(Repair))} == {"proposed"}
        for q in s.scalars(select(Question)):
            assert q.current_json == q.original_json and q.original == qmap[q.id] and q.version == 1
    assert get(api_triaged, "/audit/verify")["ok"] is True


def test_retriage_keeps_human_status_and_supersedes(api_triaged):
    h = {"X-Faculty-Key": FACULTY_KEY}
    assert api_triaged.post(f"{API}/cases/{LCR}/investigate", json={"actor": "Meera", "note": "check"},
                            headers=h).status_code == 200
    sm = api_triaged.app.state.sessionmaker
    with sm() as s:
        run_and_store(s)
        assert s.scalar(select(func.count()).select_from(TriageResult).where(TriageResult.is_current.is_(True))) == 44
        assert s.scalar(select(func.count()).select_from(TriageResult)) == 88
        assert Counter(r.status for r in s.scalars(select(Repair)))["superseded"] > 0
    assert get(api_triaged, f"/cases/{LCR}")["status"] == "investigating"     # human status kept
    assert get(api_triaged, "/results") == json.loads((ROOT / "results.json").read_text(encoding="utf-8"))
    assert get(api_triaged, "/audit/verify")["ok"] is True


def test_triage_audited(api_triaged):
    ev = Counter(e["event_type"] for e in get(api_triaged, "/audit", limit=200)["items"])
    assert ev["triage_started"] == 1 and ev["triage_completed"] == 1 and ev["triage_decision"] == 44


def test_injection_flag_persisted(api_triaged):
    assert get(api_triaged, "/reports/R027")["injection_suspected"] is True
    assert sum(r["injection_suspected"] for r in get(api_triaged, "/reports", limit=200)["items"]) == 1


def test_auto_pending_filter(api_triaged):
    page = get(api_triaged, "/cases", status="auto_pending", limit=200)
    assert page["total"] >= 1 and all(c["status"] == "auto_pending" for c in page["items"])


def test_existing_contracts_unchanged(api_triaged):
    """Phase 3 response shapes still hold after triage (additive changes only)."""
    page = get(api_triaged, "/cases")
    assert set(page) == {"total", "limit", "offset", "items"}
    old_keys = {"question_id", "title", "subject", "chapter", "topic", "level", "type", "report_count", "report_ids",
                "sources", "first_reported_at", "latest_report_at", "verdict", "repair", "confidence",
                "confidence_band", "urgency", "urgency_breakdown", "priority", "status", "origin", "assigned_to",
                "engine_mode", "triaged"}
    assert old_keys <= set(page["items"][0])
    assert set(get(api_triaged, "/health")) == {"status", "db", "data_imported", "counts", "writes_enabled", "version"}
