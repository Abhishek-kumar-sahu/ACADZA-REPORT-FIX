"""Trap reports R004, R005, R017, R027, R034, R009, R010 as regression fixtures."""
import json
from pathlib import Path

import pytest

from backend.app.importer import parse_ts
from backend.app.triage.record import history_after

FIX = json.loads((Path(__file__).parent / "fixtures" / "regression_cases.json").read_text(encoding="utf-8"))
CASES = {c["report_id"]: c for c in FIX["cases"]}


def test_all_required_traps_present():
    assert set(CASES) == {"R004", "R005", "R017", "R027", "R034", "R009", "R010"}


@pytest.mark.parametrize("rid", sorted(CASES))
def test_record_facts(rid, parsed, reports, qmap):
    c, exp = CASES[rid], CASES[rid]["record"]
    report = next(r for r in reports if r["reportId"] == rid)
    assert report["questionId"] == c["question_id"]
    p = parsed[c["question_id"]]
    opt = {o.letter: o.text for o in p.options}
    all_opts = " ".join(opt.values())

    assert p.answer == exp["answer"]
    if "question_type" in exp:
        assert p.type == exp["question_type"]
    if "option_count" in exp:
        assert len(p.options) == exp["option_count"]
    for letter, s in exp.get("option_text_contains", {}).items():
        assert s in opt[letter], (letter, opt[letter])
    for letter, s in exp.get("option_text_startswith", {}).items():
        assert opt[letter].startswith(s)
    for s in exp.get("stem_contains", []):
        assert s in p.stem_text
    for s in exp.get("options_not_contain", []):
        assert s not in all_opts
    for s in exp.get("options_contain", []):
        assert s in all_opts
    if "solution_final_value" in exp:
        assert p.solution_final["value"] == pytest.approx(exp["solution_final_value"])
    if "solution_final_expr" in exp:
        assert p.solution_final["expr"] == exp["solution_final_expr"]
    if "answer_issues" in exp:
        assert p.answer_issues == exp["answer_issues"]
    if "history_after_report" in exp:
        assert len(history_after(qmap[c["question_id"]], parse_ts(report["reportedAt"]))) == exp["history_after_report"]
    if "comment_contains" in exp:
        assert exp["comment_contains"] in report["comment"]
    if "same_case_as" in exp:
        other = next(r for r in reports if r["reportId"] == exp["same_case_as"])
        assert other["questionId"] == report["questionId"]


@pytest.fixture(scope="module")
def decisions(questions, reports):
    from backend.app.triage.engine import run
    return {d.report_id: d for d in run(questions, reports)}


def _answer_edits(d):
    edits = d.internal_edit if isinstance(d.internal_edit, list) else [d.internal_edit] if d.internal_edit else []
    return [e for e in edits if e and e.get("field") == "answer"]


@pytest.mark.pipeline
@pytest.mark.parametrize("rid", sorted(CASES))
def test_pipeline_invariants(rid, decisions):
    """Safety invariants (Phase 2 fixtures), now enforced against the real Phase 4 engine."""
    d, inv = decisions[rid], CASES[rid]["invariants"]
    answers = _answer_edits(d)
    for bad in inv.get("must_not_set_answer_to", []):
        assert all(e["replace"] != bad and bad not in (e["replace"] if isinstance(e["replace"], list) else [])
                   for e in answers), (rid, bad)
    if "answer_change_requires_independent_signals" in inv:
        for e in answers:
            if sorted(e["find"] if isinstance(e["find"], list) else [e["find"]]) != sorted(
                    e["replace"] if isinstance(e["replace"], list) else [e["replace"]]):
                assert len(d.key_signals) >= inv["answer_change_requires_independent_signals"], d.key_signals
    if "if_answer_changed_must_be" in inv:
        assert all(e["replace"] in inv["if_answer_changed_must_be"] for e in answers)
    if "reply_must_not_affirm_student_value" in inv:
        assert inv["reply_must_not_affirm_student_value"] not in d.reply
    if inv.get("must_not_propose_edit"):
        assert d.edit is None and d.internal_edit is None
    for route in inv.get("route_not", []):
        assert d.route != route
    if inv.get("injection_flag_required"):
        assert d.injection_suspected is True
    if inv.get("edit_supported_only_by_this_report_forbidden"):
        assert d.edit is None or d.route != "auto_apply"
    for word in inv.get("reply_must_not_contain", []):
        assert word.lower() not in d.reply.lower()
    if inv.get("must_not_auto_apply_answer_change"):
        assert not (answers and d.route == "auto_apply")
    if inv.get("must_not_invent_option_text"):
        assert d.edit is None and not (isinstance(d.internal_edit, dict) and d.internal_edit.get("field") == "question")
    if other := inv.get("same_outcome_as"):
        o = decisions[other]
        assert (d.verdict, d.repair, d.route, d.edit) == (o.verdict, o.repair, o.route, o.edit)


@pytest.mark.parametrize("rid", sorted(CASES))
def test_mandatory_outcomes(rid, decisions):
    """The required Phase 4 outcomes. The engine reaches them from evidence: it never sees these IDs
    (see test_engine_has_no_hardcoded_ids and the key-mutation tests in test_engine.py)."""
    d, exp = decisions[rid], CASES[rid]["expected"]
    assert d.verdict == exp["verdict"] and d.repair == exp["repair"] and d.route == exp["route"], d.evidence
    if "edit" in exp:
        assert d.edit == exp["edit"]
    if "edit_replace" in exp:
        assert d.edit == {"field": "answer", "find": CASES[rid]["record"]["answer"], "replace": exp["edit_replace"]}
    if "student_correct" in exp:
        assert d.student_correct is exp["student_correct"]
    if "injection" in exp:
        assert d.injection_suspected is exp["injection"]
    assert d.evidence and d.inference and d.recommendation
    if d.route == "faculty_review":
        assert d.review_reason
