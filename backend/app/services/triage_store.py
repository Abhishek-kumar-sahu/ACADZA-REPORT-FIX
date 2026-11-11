"""Run the rules engine against the database and persist its proposals.

Nothing here applies a repair: repairs are stored as `proposed`, cases move only between the
machine-owned statuses (untriaged / needs_review / auto_pending / no_change), and statuses set by a
human (investigating, approved, …) are never overwritten. Every decision is audited.
"""
import json

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ..models import (MACHINE_STATUSES, Case, Question, Repair, RepairReport, Report, TriageResult,
                      TriageRun, utcnow)
from ..triage import engine
from ..triage.output import result_entry
from . import audit

ACTOR = f"engine:{engine.ENGINE}"


def _records(s: Session) -> tuple[list[dict], list[dict]]:
    questions = [q.current for q in s.scalars(select(Question).order_by(Question.id))]
    reports = [{"reportId": r.report_id, "questionId": r.question_id, "studentId": r.student_id,
                "source": r.source, "reportedAt": r.reported_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "comment": r.comment} for r in s.scalars(select(Report))]
    return questions, reports


def run_and_store(s: Session, mode: str | None = None, provider: str | None = None,
                  model: str | None = None) -> tuple[TriageRun, list[engine.Decision]]:
    questions, reports = _records(s)
    from ..config import settings
    actual_mode = mode or ("llm" if settings.llm_provider and settings.llm_provider != "none" else "rules_only")
    actual_provider = provider or (settings.llm_provider if actual_mode == "llm" else None)
    actual_model = model or (settings.llm_model if actual_mode == "llm" else None)

    run = TriageRun(mode=actual_mode, provider=actual_provider, model=actual_model,
                    prompt_versions={"engine": engine.ENGINE})
    s.add(run)
    s.flush()
    audit.append(s, actor=ACTOR, actor_type="system", event_type="triage_started",
                 after={"run_id": run.id, "reports": len(reports), "mode": actual_mode,
                        "provider": actual_provider, "model": actual_model})

    decisions = engine.run(questions, reports)
    s.execute(update(TriageResult).where(TriageResult.is_current.is_(True)).values(is_current=False))
    for d in decisions:
        e = result_entry(d)
        s.add(TriageResult(
            report_id=d.report_id, run_id=run.id, is_current=True, complaint_class=d.complaint_class,
            verdict=d.verdict, repair=d.repair, edit=d.edit, route=d.route, confidence=d.confidence,
            evidence=e["evidence"], inference=d.inference, recommendation=d.recommendation,
            review_reason=d.review_reason, suggestion={"text": d.suggestion} if d.suggestion else None,
            signals={"evidence": d.evidence, "key_status": d.key_status, "key_signals": d.key_signals,
                     "confidence_basis": d.confidence_basis, "student_claim": d.student_claim,
                     "student_correct": d.student_correct, "rule_ids": d.rule_ids,
                     "history_after_report": d.history_after_report, "internal_edit": d.internal_edit},
            reply_draft=d.reply, engine_mode=d.engine_mode))
        rep = s.get(Report, d.report_id)
        rep.injection_suspected = d.injection_suspected
        audit.append(s, actor=ACTOR, actor_type="system", event_type="triage_decision", question_id=d.question_id,
                     report_id=d.report_id, rule_ids=d.rule_ids,
                     after={"verdict": d.verdict, "repair": d.repair, "route": d.route, "confidence": d.confidence})

    # One proposed repair per (question, repair, edit), linked to every supporting report (R-61).
    by_q: dict[str, list[engine.Decision]] = {}
    for d in decisions:
        by_q.setdefault(d.question_id, []).append(d)
    s.execute(update(Repair).where(Repair.status == "proposed").values(status="superseded"))
    for qid, ds in sorted(by_q.items()):
        groups: dict[tuple, list[engine.Decision]] = {}
        for d in ds:
            if d.verdict == "defect" and d.repair:
                key = (d.repair, json.dumps(d.internal_edit, sort_keys=True, ensure_ascii=False))
                groups.setdefault(key, []).append(d)
        for (repair, _), members in sorted(groups.items()):
            r = Repair(question_id=qid, repair_type=repair, edit=members[0].internal_edit, status="proposed",
                       confidence=min(m.confidence for m in members), created_by=ACTOR)
            s.add(r)
            s.flush()
            for m in members:
                s.add(RepairReport(repair_id=r.id, report_id=m.report_id))

        case = s.get(Case, qid)
        if case is not None and case.status in MACHINE_STATUSES:
            routes = {d.route for d in ds}
            new = "needs_review" if "faculty_review" in routes else "auto_pending" if "auto_apply" in routes else "no_change"
            if new != case.status:
                audit.append(s, actor=ACTOR, actor_type="system", event_type="case_status_changed", question_id=qid,
                             before={"status": case.status}, after={"status": new})
                case.status = new

    run.finished_at, run.calls, run.failures = utcnow(), 0, 0
    audit.append(s, actor=ACTOR, actor_type="system", event_type="triage_completed",
                 after={"run_id": run.id, "decisions": len(decisions),
                        "routes": {r: sum(d.route == r for d in decisions) for r in ("auto_apply", "faculty_review", "no_change")}})
    s.commit()
    return run, decisions


def covered_from_db(s: Session) -> set[tuple[str, str]]:
    rows = s.execute(select(Report.question_id, TriageResult.repair)
                     .join(TriageResult, TriageResult.report_id == Report.report_id)
                     .where(TriageResult.is_current.is_(True), TriageResult.verdict == "defect"))
    return {(q, r) for q, r in rows if r}


def results_from_db(s: Session) -> list[dict]:
    rows = s.execute(select(TriageResult, Report.question_id).join(Report, Report.report_id == TriageResult.report_id)
                     .where(TriageResult.is_current.is_(True)).order_by(TriageResult.report_id))
    return [{"reportId": t.report_id, "questionId": qid, "verdict": t.verdict, "repair": t.repair, "edit": t.edit,
             "route": t.route, "confidence": t.confidence, "evidence": t.evidence,
             "student_reply": t.reply_final or t.reply_draft} for t, qid in rows]
