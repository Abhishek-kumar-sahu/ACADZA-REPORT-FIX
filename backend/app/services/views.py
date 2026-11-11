"""Read models for the API. Everything is computed from the database at request time;
there are no hard-coded metrics. Urgency (RULES R-90) is computed on read so `age` is always current.
"""
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import taxonomy
from ..models import (AuditEvent, Case, Meta, Question, QuestionRevision, Repair, RepairReport,
                      Report, TriageResult, TriageRun)
from ..sanitize import sanitize_html
from ..triage.record import history_after, parse_record

EPOCH = datetime.min.replace(tzinfo=timezone.utc)
RESOLVED = ("auto_fixed", "approved", "no_change", "rejected", "duplicate")
RESOLUTION_EVENTS = ("auto_applied", "faculty_approved", "faculty_rejected", "marked_duplicate",
                     "case_closed_no_change")
# Case-level verdict = most severe report verdict.
VERDICT_SEVERITY = ["defect", "app_issue", "display_issue", "already_fixed", "language_mode",
                    "no_error", "not_actionable"]
IMPACT = {  # RULES R-90
    **dict.fromkeys(("answer_key", "unsound", "wrong_question"), 40),
    **dict.fromkeys(("option_repair", "stem_data", "diagram", "identical_options", "type_mismatch",
                     "solution_fix", "solution_missing"), 30),
    **dict.fromkeys(("markup_leak", "notation"), 20),
    **dict.fromkeys(("spelling", "noise", "exam_reference", "answer_form", "wrong_chapter", "syllabus"), 10),
}


def priority_band(urgency: int) -> str:
    return "critical" if urgency >= 70 else "high" if urgency >= 40 else "normal" if urgency >= 15 else "low"


def confidence_band(c: float | None) -> str | None:
    if c is None:
        return None
    return "low" if c < 0.60 else "medium" if c < 0.85 else "high" if c < 0.95 else "very_high"


def compute_urgency(*, verdict: str | None, repair: str | None, clean_reports: int,
                    first_reported_at: datetime | None, status: str, now: datetime) -> dict:
    if status in RESOLVED:
        return {"total": 0, "impact": 0, "volume": 0, "age": 0, "review": 0, "resolved": True}
    impact = IMPACT.get(repair, 0) if repair else (20 if verdict == "app_issue" else 0)
    volume = min(24, 8 * max(0, clean_reports - 1))
    age = 0
    if first_reported_at:
        age = min(16, int(max(0.0, (now - first_reported_at).total_seconds()) / 3600 // 12))
    review = 20 if status in ("needs_review", "investigating") else 0
    return {"total": min(100, impact + volume + age + review), "impact": impact, "volume": volume,
            "age": age, "review": review, "resolved": False}


# ------------------------------------------------------------------ questions

def _title(stem_text: str) -> str:
    line = stem_text.split("\n", 1)[0].strip()
    return line if len(line) <= 90 else line[:89].rstrip() + "…"


def question_view(q: Question, which: str = "current") -> dict:
    rec = q.current if which == "current" else q.original
    p = parse_record(rec)
    body = rec[rec["questionType"]]
    return {
        "id": q.id, "qid": q.qid, "version": q.version if which == "current" else 1, "which": which,
        "modified": q.current_json != q.original_json,
        "type": rec["questionType"], "subject": rec["subject"], "chapter": rec["chapter"],
        "concept": rec["concept"], "sub_concept": rec["subConcept"], "level": rec["level"],
        "updated_at": rec["updatedAt"],
        "title": _title(p.stem_text),
        "question_html_safe": sanitize_html(body["question"]),
        "stem_html_safe": sanitize_html(p.stem_html),
        "stem_text": p.stem_text,
        "options": [{"letter": o.letter, "html_safe": sanitize_html(o.html), "text": o.text, "blank": o.blank}
                    for o in p.options],
        "solution_html_safe": sanitize_html(body.get("solution")),
        "solution_text": p.solution_text,
        "answer": p.answer_raw, "answer_canonical": p.answer, "answer_issues": p.answer_issues,
        "original_answer": q.original[q.original["questionType"]]["answer"],
        "images": {"question": body.get("quesImages", []), "solution": body.get("solutionImages", [])},
        "error_history": rec.get("errorHistory") or [],
    }


def question_history(s: Session, q: Question) -> dict:
    rec = q.current
    reports = s.scalars(select(Report).where(Report.question_id == q.id).order_by(Report.reported_at)).all()
    return {
        "question_id": q.id,
        "error_history": rec.get("errorHistory") or [],
        "reports": [{"report_id": r.report_id, "reported_at": r.reported_at,
                     "fixed_after_report": history_after(rec, r.reported_at)} for r in reports],
        "revisions": [revision_view(r, s) for r in _revisions(s, q.id)],
    }


# ------------------------------------------------------------------ revisions & audit

def _revisions(s: Session, question_id: str | None = None):
    stmt = select(QuestionRevision).order_by(QuestionRevision.id)
    if question_id:
        stmt = stmt.where(QuestionRevision.question_id == question_id)
    return s.scalars(stmt).all()


def revision_view(r: QuestionRevision, s: Session) -> dict:
    reverted_by = s.scalar(select(QuestionRevision.id).where(QuestionRevision.reverts_revision_id == r.id))
    return {"id": r.id, "question_id": r.question_id, "version": r.version, "field": r.field,
            "before": r.before, "after": r.after, "actor": r.actor, "repair_id": r.repair_id,
            "reverts_revision_id": r.reverts_revision_id, "reverted_by_revision_id": reverted_by,
            "created_at": r.created_at}


def revision_page(s: Session, *, question_id=None, limit=50, offset=0) -> dict:
    stmt = select(QuestionRevision)
    if question_id:
        stmt = stmt.where(QuestionRevision.question_id == question_id)
    total = s.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = s.scalars(stmt.order_by(QuestionRevision.id).limit(limit).offset(offset)).all()
    return {"total": total, "limit": limit, "offset": offset, "items": [revision_view(r, s) for r in rows]}


def audit_view(e: AuditEvent) -> dict:
    return {"id": e.id, "ts": e.ts, "actor": e.actor, "actor_type": e.actor_type, "event_type": e.event_type,
            "question_id": e.question_id, "report_id": e.report_id, "repair_id": e.repair_id,
            "before": e.before, "after": e.after, "rule_ids": e.rule_ids, "note": e.note, "hash": e.hash}


def audit_page(s: Session, *, question_id=None, report_id=None, actor_type=None, event_type=None,
               since=None, until=None, order="asc", limit=50, offset=0) -> dict:
    stmt = select(AuditEvent)
    for col, val in ((AuditEvent.question_id, question_id), (AuditEvent.report_id, report_id),
                     (AuditEvent.actor_type, actor_type), (AuditEvent.event_type, event_type)):
        if val is not None:
            stmt = stmt.where(col == val)
    if since:
        stmt = stmt.where(AuditEvent.ts >= since)
    if until:
        stmt = stmt.where(AuditEvent.ts <= until)
    total = s.scalar(select(func.count()).select_from(stmt.subquery()))
    order_by = AuditEvent.id.asc() if order == "asc" else AuditEvent.id.desc()
    rows = s.scalars(stmt.order_by(order_by).limit(limit).offset(offset)).all()
    return {"total": total, "limit": limit, "offset": offset, "items": [audit_view(e) for e in rows]}


# ------------------------------------------------------------------ reports & results

def _current_results(s: Session, report_ids=None) -> dict[str, TriageResult]:
    stmt = select(TriageResult).where(TriageResult.is_current.is_(True))
    if report_ids is not None:
        stmt = stmt.where(TriageResult.report_id.in_(report_ids))
    return {r.report_id: r for r in s.scalars(stmt)}


def result_view(r: TriageResult | None) -> dict | None:
    if r is None:
        return None
    return {"verdict": r.verdict, "repair": r.repair, "edit": r.edit, "route": r.route,
            "confidence": r.confidence, "confidence_band": confidence_band(r.confidence),
            "evidence": r.evidence, "signals": r.signals, "suggestion": r.suggestion,
            "reply": r.reply_final or r.reply_draft, "reply_status": r.reply_status,
            "engine_mode": r.engine_mode, "complaint_class": r.complaint_class,
            # Phase 4: evidence / inference / recommendation kept separate (additive fields)
            "inference": r.inference, "recommendation": r.recommendation, "review_reason": r.review_reason,
            "facts": (r.signals or {}).get("evidence", []),
            "confidence_basis": (r.signals or {}).get("confidence_basis"),
            "student_claim": (r.signals or {}).get("student_claim"),
            "student_correct": (r.signals or {}).get("student_correct"),
            "key_status": (r.signals or {}).get("key_status"),
            "rule_ids": (r.signals or {}).get("rule_ids", [])}


def report_brief(r: Report) -> dict:
    return {"report_id": r.report_id, "question_id": r.question_id, "student_id": r.student_id,
            "source": r.source, "reported_at": r.reported_at, "comment": r.comment,
            "injection_suspected": r.injection_suspected, "duplicate_of": r.duplicate_of}


def report_page(s: Session, *, question_id=None, source=None, q=None, limit=50, offset=0) -> dict:
    stmt = select(Report)
    if question_id:
        stmt = stmt.where(Report.question_id == question_id)
    if source:
        stmt = stmt.where(Report.source == source)
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(func.lower(Report.report_id).like(like) | func.lower(Report.question_id).like(like))
    total = s.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = s.scalars(stmt.order_by(Report.reported_at.desc(), Report.report_id).limit(limit).offset(offset)).all()
    results = _current_results(s, [r.report_id for r in rows])
    return {"total": total, "limit": limit, "offset": offset,
            "items": [{**report_brief(r), "result": result_view(results.get(r.report_id))} for r in rows]}


def report_detail(s: Session, r: Report) -> dict:
    q = s.get(Question, r.question_id)
    siblings = s.scalars(select(Report.report_id).where(Report.question_id == r.question_id,
                                                       Report.report_id != r.report_id).order_by(Report.reported_at)).all()
    return {**report_brief(r),
            "result": result_view(_current_results(s, [r.report_id]).get(r.report_id)),
            "question": {"id": q.id, "title": _title(parse_record(q.current).stem_text),
                         "subject": q.subject, "chapter": q.chapter, "type": q.question_type},
            "case_status": s.scalar(select(Case.status).where(Case.question_id == r.question_id)),
            "other_reports_on_question": siblings,
            "fixed_after_report": history_after(q.current, r.reported_at)}


# ------------------------------------------------------------------ cases

def _case_rows(s: Session):
    """(case, question, [reports]) for every case; one query per table, grouped in Python."""
    cases = s.scalars(select(Case)).all()
    qs = {q.id: q for q in s.scalars(select(Question).where(Question.id.in_([c.question_id for c in cases])))}
    reports = defaultdict(list)
    for r in s.scalars(select(Report).order_by(Report.reported_at)):
        reports[r.question_id].append(r)
    return [(c, qs[c.question_id], reports[c.question_id]) for c in cases]


def case_summaries(s: Session, now: datetime) -> list[dict]:
    # ponytail: assembles every case in memory, fine for thousands of cases; move filters/sort into
    # SQL (and persist urgency) when the reported-question count reaches tens of thousands.
    rows = _case_rows(s)
    results = _current_results(s)
    out = []
    for case, q, reps in rows:
        res = [results[r.report_id] for r in reps if r.report_id in results]
        verdict = min((x.verdict for x in res), key=VERDICT_SEVERITY.index, default=None)
        repair = next((x.repair for x in res if x.verdict == "defect" and x.repair), None)
        conf = min((x.confidence for x in res), default=None)
        clean = sum(1 for r in reps if not r.injection_suspected and not r.duplicate_of)
        urg = compute_urgency(verdict=verdict, repair=repair, clean_reports=clean,
                              first_reported_at=case.first_reported_at, status=case.status, now=now)
        p = parse_record(q.current)
        out.append({
            "question_id": q.id, "title": _title(p.stem_text), "subject": q.subject, "chapter": q.chapter,
            "topic": q.concept, "level": q.level, "type": q.question_type,
            "report_count": len(reps), "report_ids": [r.report_id for r in reps],
            "sources": sorted({r.source for r in reps}),
            "first_reported_at": case.first_reported_at,
            "latest_report_at": reps[-1].reported_at if reps else None,
            "verdict": verdict, "repair": repair, "confidence": conf, "confidence_band": confidence_band(conf),
            "urgency": urg["total"], "urgency_breakdown": urg, "priority": priority_band(urg["total"]),
            "status": case.status, "origin": case.origin, "assigned_to": case.assigned_to,
            "engine_mode": res[0].engine_mode if res else None, "triaged": bool(res),
        })
    return out


SORT_KEYS = {
    "urgency": lambda c: (c["urgency"], c["latest_report_at"] or EPOCH),
    "latest": lambda c: c["latest_report_at"] or EPOCH,
    "confidence": lambda c: -1.0 if c["confidence"] is None else c["confidence"],
    "reports": lambda c: (c["report_count"], c["latest_report_at"] or EPOCH),
}


def case_page(s: Session, now: datetime, *, status="all", defects_only=False, subject=None, verdict=None,
              confidence=None, priority=None, q=None, sort="urgency", order="desc", limit=50, offset=0) -> dict:
    items = case_summaries(s, now)
    if status == "resolved":
        items = [c for c in items if c["status"] in RESOLVED]
    elif status != "all":
        items = [c for c in items if c["status"] == status]
    if defects_only:
        items = [c for c in items if c["verdict"] == "defect"]
    if subject:
        items = [c for c in items if c["subject"].lower() == subject.lower()]
    if verdict:
        items = [c for c in items if c["verdict"] == verdict]
    if confidence:
        items = [c for c in items if c["confidence_band"] == confidence]
    if priority:
        items = [c for c in items if c["priority"] == priority]
    if q:
        needle = q.strip().lower()
        items = [c for c in items if needle in c["question_id"].lower()
                 or any(needle in rid.lower() for rid in c["report_ids"])]
    items.sort(key=SORT_KEYS[sort], reverse=(order == "desc"))
    return {"total": len(items), "limit": limit, "offset": offset, "items": items[offset: offset + limit]}


def case_detail(s: Session, question_id: str, now: datetime) -> dict | None:
    case = s.get(Case, question_id)
    if case is None:
        return None
    summary = next(c for c in case_summaries(s, now) if c["question_id"] == question_id)
    q = s.get(Question, question_id)
    reps = s.scalars(select(Report).where(Report.question_id == question_id).order_by(Report.reported_at)).all()
    results = _current_results(s, [r.report_id for r in reps])
    repairs = s.scalars(select(Repair).where(Repair.question_id == question_id).order_by(Repair.id)).all()
    links = defaultdict(list)
    for link in s.scalars(select(RepairReport).where(RepairReport.repair_id.in_([r.id for r in repairs]))):
        links[link.repair_id].append(link.report_id)
    return {
        **summary,
        "question": question_view(q),
        "reports": [{**report_brief(r), "result": result_view(results.get(r.report_id)),
                     "fixed_after_report": history_after(q.current, r.reported_at)} for r in reps],
        "repairs": [{"id": r.id, "repair_type": r.repair_type, "edit": r.edit, "status": r.status,
                     "confidence": r.confidence, "created_by": r.created_by, "created_at": r.created_at,
                     "report_ids": sorted(links[r.id])} for r in repairs],
        "revisions": [revision_view(r, s) for r in _revisions(s, question_id)],
        "audit": audit_page(s, question_id=question_id, limit=200)["items"],
    }


# ------------------------------------------------------------------ dashboard & meta

def dashboard(s: Session, now: datetime) -> dict:
    cases = case_summaries(s, now)
    results = list(_current_results(s).values())
    status = Counter(c["status"] for c in cases)
    reports_by_subject = Counter()
    for subject, n in s.execute(select(Question.subject, func.count(Report.report_id))
                                .join(Report, Report.question_id == Question.id).group_by(Question.subject)):
        reports_by_subject[subject] = n
    cases_by_subject = Counter(c["subject"] for c in cases)

    start = (now - timedelta(days=6)).date()
    trend = {start + timedelta(days=i): 0 for i in range(7)}
    for ts in s.scalars(select(AuditEvent.ts).where(AuditEvent.event_type.in_(RESOLUTION_EVENTS))):
        if ts.date() in trend:
            trend[ts.date()] += 1

    last_run = s.scalars(select(TriageRun).order_by(TriageRun.id.desc()).limit(1)).first()
    unresolved = [c for c in cases if c["status"] not in RESOLVED]
    return {
        "generated_at": now,
        "metrics": {
            "total_reports": s.scalar(select(func.count()).select_from(Report)),
            "unique_questions": len(cases),
            "untriaged": status["untriaged"],
            "needs_review": status["needs_review"] + status["investigating"],
            "confirmed_defects": sum(1 for r in results if r.verdict == "defect"),
            "resolved": sum(status[x] for x in RESOLVED),
            "auto_applied": s.scalar(select(func.count()).select_from(Repair).where(Repair.status == "auto_applied")),
            "auto_eligible": sum(1 for r in results if r.route == "auto_apply"),
            "rejected": status["rejected"],
            "critical_unresolved": sum(1 for c in unresolved if c["priority"] == "critical"),
        },
        "urgent": sorted(unresolved, key=SORT_KEYS["urgency"], reverse=True)[:5],
        "by_subject": [{"subject": k, "reports": reports_by_subject[k], "cases": cases_by_subject[k]}
                       for k in sorted(cases_by_subject)],
        "by_source": dict(Counter(src for (src,) in s.execute(select(Report.source)))),
        "verdicts": [{"verdict": v, "count": n} for v, n in Counter(r.verdict for r in results).most_common()],
        "status_counts": dict(status),
        "trend": [{"date": d, "resolved": n} for d, n in trend.items()],
        "recent_activity": audit_page(s, order="desc", limit=10)["items"],
        "ai_status": {
            "last_run": None if last_run is None else {
                "id": last_run.id, "mode": last_run.mode, "provider": last_run.provider,
                "model": last_run.model, "started_at": last_run.started_at,
                "finished_at": last_run.finished_at, "calls": last_run.calls, "failures": last_run.failures},
            "triaged_reports": len(results),
        },
    }


def meta_value(s: Session, key: str) -> str | None:
    row = s.get(Meta, key)
    return row.value if row else None


def taxonomy_view() -> dict:
    return taxonomy.load()
