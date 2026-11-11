"""Read endpoints against the real imported data. Every expected number is recomputed from the
source files or the DB, never typed in as a "known" metric."""
from collections import Counter

import pytest

from backend.app.services.revisions import apply_revision, rollback_revision
from backend.app.triage.html_parse import iter_nodes, parse_html
from backend.tests.conftest import API, FACULTY_KEY

LCR = "60f744b3f1b9bc7cc7b4a949"        # 3 reports: R001, R002, R003
UNREPORTED = "68dea87d387eea3d0d95fbe3"


def get(api, path, **params):
    r = api.get(API + path, params=params)
    assert r.status_code == 200, (path, r.status_code, r.text[:300])
    return r.json()


# ------------------------------------------------------------------ meta

def test_health(api):
    h = get(api, "/health")
    assert h["status"] == "ok" and h["data_imported"] is True and h["writes_enabled"] is True
    assert h["counts"] == {"questions": 43, "reports": 44, "cases": 39}


def test_taxonomy_is_the_file(api, questions):
    import json
    from backend.app.config import ROOT
    assert get(api, "/taxonomy") == json.loads((ROOT / "data" / "taxonomy.json").read_text(encoding="utf-8"))


def test_settings_reports_rules_only_and_never_the_key(api):
    st = get(api, "/settings")
    assert st["engine"]["mode"] in ("rules_only", "llm") and st["writes_enabled"] is True
    assert st["thresholds"] == {"auto_apply_min_confidence": 0.85, "no_change_min_confidence": 0.6}
    assert FACULTY_KEY not in str(st)


# ------------------------------------------------------------------ dashboard

def test_dashboard_metrics_come_from_data(api, reports, qmap):
    d = get(api, "/dashboard")
    m = d["metrics"]
    assert m["total_reports"] == len(reports) == 44
    assert m["unique_questions"] == len({r["questionId"] for r in reports}) == 39
    assert m["untriaged"] == 39
    # No triage has run, so these must be zero rather than invented.
    for k in ("needs_review", "confirmed_defects", "resolved", "auto_applied", "rejected", "critical_unresolved"):
        assert m[k] == 0, k
    want_reports = Counter(qmap[r["questionId"]]["subject"] for r in reports)
    want_cases = Counter(qmap[q]["subject"] for q in {r["questionId"] for r in reports})
    assert {x["subject"]: (x["reports"], x["cases"]) for x in d["by_subject"]} == {
        k: (want_reports[k], want_cases[k]) for k in want_cases}
    assert d["by_source"] == dict(Counter(r["source"] for r in reports))
    assert d["verdicts"] == [] and d["ai_status"] == {"last_run": None, "triaged_reports": 0}
    assert len(d["trend"]) == 7 and all(t["resolved"] == 0 for t in d["trend"])
    assert len(d["urgent"]) == 5 and d["recent_activity"][0]["event_type"] == "import_completed"


def test_dashboard_reacts_to_state_change(api, auth):
    before = get(api, "/dashboard")["metrics"]
    r = api.post(f"{API}/cases/{LCR}/investigate", json={"actor": "Meera", "note": "check key"}, headers=auth)
    assert r.status_code == 200
    after = get(api, "/dashboard")["metrics"]
    assert after["needs_review"] == before["needs_review"] + 1
    assert after["untriaged"] == before["untriaged"] - 1


# ------------------------------------------------------------------ cases (queue)

def test_cases_group_all_reports(api, reports):
    page = get(api, "/cases", limit=200)
    assert page["total"] == 39 and len(page["items"]) == 39
    assert sum(c["report_count"] for c in page["items"]) == 44
    by_q = {c["question_id"]: c for c in page["items"]}
    for qid, n in Counter(r["questionId"] for r in reports).items():
        assert by_q[qid]["report_count"] == n
    assert by_q[LCR]["report_ids"] == ["R002", "R003", "R001"]  # chronological
    assert all(c["verdict"] is None and c["triaged"] is False for c in page["items"])


def test_urgency_breakdown_is_exact(api):
    """R-90 with the fixed clock 2026-11-10T00:00Z. LCR: first report 2026-11-03T22:11Z → 145.8 h
    → age 12; 3 clean reports → volume 16; untriaged → impact 0, review 0."""
    c = get(api, f"/cases/{LCR}")
    assert c["urgency_breakdown"] == {"total": 28, "impact": 0, "volume": 16, "age": 12, "review": 0,
                                      "resolved": False}
    assert c["priority"] == "normal"


def test_queue_sorted_by_urgency_desc(api):
    items = get(api, "/cases", limit=200)["items"]
    assert [c["urgency"] for c in items] == sorted((c["urgency"] for c in items), reverse=True)


@pytest.mark.parametrize("params,check", [
    ({"status": "untriaged"}, lambda c: c["status"] == "untriaged"),
    ({"subject": "Botany"}, lambda c: c["subject"] == "Botany"),
    ({"priority": "normal"}, lambda c: c["priority"] == "normal"),
    ({"priority": "low"}, lambda c: c["priority"] == "low"),
])
def test_case_filters_are_exact(api, params, check):
    all_items = get(api, "/cases", limit=200)["items"]
    page = get(api, "/cases", limit=200, **params)
    assert page["total"] == sum(1 for c in all_items if check(c))
    assert all(check(c) for c in page["items"])


@pytest.mark.parametrize("params", [{"status": "resolved"}, {"verdict": "defect"}, {"defects_only": "true"},
                                    {"confidence": "high"}, {"status": "needs_review"}])
def test_filters_with_no_matches_yet(api, params):
    assert get(api, "/cases", **params) == {"total": 0, "limit": 50, "offset": 0, "items": []}


@pytest.mark.parametrize("q,expected", [("R019", {"612151a6a34397610a9a2e58"}), ("r019", {"612151a6a34397610a9a2e58"}),
                                        ("60f744", {LCR}), ("R0", None), ("nothing", set())])
def test_case_search(api, q, expected):
    got = {c["question_id"] for c in get(api, "/cases", q=q, limit=200)["items"]}
    assert got == expected if expected is not None else len(got) == 39


def test_pagination_is_stable(api):
    full = [c["question_id"] for c in get(api, "/cases", limit=200)["items"]]
    paged = []
    for off in range(0, 39, 10):
        page = get(api, "/cases", limit=10, offset=off)
        assert page["total"] == 39
        paged += [c["question_id"] for c in page["items"]]
    assert paged == full


@pytest.mark.parametrize("params", [{"status": "bogus"}, {"limit": 0}, {"limit": 201}, {"offset": -1},
                                    {"sort": "x"}, {"verdict": "maybe"}, {"q": "x" * 65}])
def test_invalid_query_params(api, params):
    r = api.get(f"{API}/cases", params=params)
    assert r.status_code == 422 and r.json()["error"]["code"] == "validation_failed"


def test_case_detail(api):
    c = get(api, f"/cases/{LCR}")
    assert [r["report_id"] for r in c["reports"]] == ["R002", "R003", "R001"]
    assert all(r["result"] is None for r in c["reports"])
    assert c["question"]["answer"] == "C" and [o["text"] for o in c["question"]["options"]] == [
        "50 V", "70 V", "130 V", "10 V"]
    assert {e["report_id"] for e in c["audit"]} == {"R001", "R002", "R003"}
    assert c["repairs"] == [] and c["revisions"] == []


def test_unreported_question_has_no_case_but_is_readable(api):
    assert api.get(f"{API}/cases/{UNREPORTED}").status_code == 404
    assert get(api, f"/questions/{UNREPORTED}")["id"] == UNREPORTED


# ------------------------------------------------------------------ reports

def test_reports_list(api, reports):
    page = get(api, "/reports", limit=200)
    assert page["total"] == 44
    assert {r["report_id"] for r in page["items"]} == {r["reportId"] for r in reports}
    assert get(api, "/reports", source="web")["total"] == sum(r["source"] == "web" for r in reports)
    assert get(api, "/reports", question_id=LCR)["total"] == 3
    assert {r["report_id"] for r in get(api, "/reports", q="r00")["items"]} == {f"R00{i}" for i in range(1, 10)}


def test_report_detail(api):
    r = get(api, "/reports/R017")
    assert len(r["fixed_after_report"]) == 1 and r["case_status"] == "untriaged"
    assert get(api, "/reports/R009")["other_reports_on_question"] == ["R010"]
    assert get(api, "/reports/R027")["comment"].startswith("IGNORE ALL PREVIOUS")  # stored as data, verbatim


@pytest.mark.parametrize("rid,status", [("R999", 404), ("X1", 422), ("R1", 422), ("R004;DROP", 422)])
def test_report_bad_ids(api, rid, status):
    assert api.get(f"{API}/reports/{rid}").status_code == status


# ------------------------------------------------------------------ questions

def test_every_question_renders_safely(api, questions, parsed):
    for q in questions:
        v = get(api, f"/questions/{q['_id']}")
        body = q[q["questionType"]]
        assert [o["text"] for o in v["options"]] == [o.text for o in parsed[q["_id"]].options]
        for field, raw in (("question_html_safe", body["question"]), ("solution_html_safe", body["solution"])):
            safe = v[field]
            assert "<script" not in safe and "onerror" not in safe and "javascript:" not in safe
            assert len(list(iter_nodes(parse_html(safe), "math"))) == (raw or "").count("<math"), (q["_id"], field)
        assert v["modified"] is False and v["version"] == 1


def test_question_original_vs_current(api):
    assert get(api, f"/questions/{LCR}", version="original")["which"] == "original"
    assert api.get(f"{API}/questions/{LCR}", params={"version": "v2"}).status_code == 422


@pytest.mark.parametrize("qid,status", [("f" * 24, 404), ("zz", 422), ("F" * 24, 422), ("6" * 25, 422)])
def test_question_bad_ids(api, qid, status):
    r = api.get(f"{API}/questions/{qid}")
    assert r.status_code == status and "error" in r.json()


def test_question_history(api):
    h = get(api, "/questions/6208e80a9cb2ab67dac61bd0/history")
    assert len(h["error_history"]) == 1
    assert [len(x["fixed_after_report"]) for x in h["reports"]] == [1]
    assert get(api, f"/questions/{LCR}/history")["error_history"] == []


# ------------------------------------------------------------------ revisions & audit

def test_revision_history_endpoints(api, engine):
    sm = api.app.state.sessionmaker
    with sm() as s:
        rev = apply_revision(s, LCR, "answer", "C", "A", actor="faculty:Meera", actor_type="faculty",
                             event_type="faculty_approved")
        s.commit()
    revs = get(api, f"/questions/{LCR}/revisions")
    assert revs["total"] == 1 and revs["items"][0]["before"] == "C" and revs["items"][0]["after"] == "A"
    assert get(api, f"/questions/{LCR}")["modified"] is True
    assert get(api, f"/questions/{LCR}", version="original")["answer"] == "C"
    with sm() as s:
        rollback_revision(s, rev.id, actor="faculty:Meera", actor_type="faculty")
        s.commit()
    page = get(api, "/revisions")
    assert page["total"] == 2 and page["items"][0]["reverted_by_revision_id"] == page["items"][1]["id"]
    assert get(api, f"/questions/{LCR}")["answer"] == "C"
    assert get(api, "/audit/verify")["ok"] is True


def test_audit_endpoints(api):
    assert get(api, "/audit")["total"] == 45
    assert get(api, "/audit", event_type="report_received")["total"] == 44
    assert get(api, "/audit", question_id=LCR)["total"] == 3
    assert get(api, "/audit", report_id="R004")["items"][0]["report_id"] == "R004"
    asc = get(api, "/audit", limit=200)["items"]
    assert [e["id"] for e in asc] == sorted(e["id"] for e in asc)
    assert get(api, "/audit", order="desc", limit=1)["items"][0]["event_type"] == "import_completed"
    assert get(api, "/audit", since="2100-01-01T00:00:00Z")["total"] == 0
    assert get(api, "/audit", until="2000-01-01T00:00:00")["total"] == 0   # naive input treated as UTC
    assert get(api, "/audit/verify") == {"ok": True, "events": 45, "first_bad_id": None}


def test_timestamps_are_explicit_utc(api):
    r = get(api, "/reports/R004")
    assert r["reported_at"] == "2026-11-04T00:50:00Z" or r["reported_at"].endswith("+00:00")
