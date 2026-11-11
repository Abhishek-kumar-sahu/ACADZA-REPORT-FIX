"""/api/v1 routes. GETs are public; every other method lives on `write` and requires the faculty
key via a router-level dependency, so a write endpoint cannot be added unprotected
(test_every_write_route_requires_faculty enforces this)."""
from datetime import datetime, timezone
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Path, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select, text

from ..models import Case, Question, Repair, QuestionRevision, Report
from ..models import TriageRun
from ..services import audit, faculty_actions, triage_store, views
from ..services.revisions import ConflictError
from ..triage import engine as triage_engine
from .deps import DB, require_faculty
from .errors import ApiError

QID = Annotated[str, Path(pattern=r"^[0-9a-f]{24}$", description="24-hex question _id")]
RID = Annotated[str, Path(pattern=r"^R\d{3,6}$", description="report id, e.g. R004")]
Limit = Annotated[int, Query(ge=1, le=200)]
Offset = Annotated[int, Query(ge=0)]

read = APIRouter()
write = APIRouter(dependencies=[Depends(require_faculty)])


def _now(request: Request) -> datetime:
    return request.app.state.clock()


def _question(s, qid: str) -> Question:
    q = s.get(Question, qid)
    if q is None:
        raise ApiError(404, "not_found", f"No question with id {qid}.")
    return q


# ------------------------------------------------------------------ meta

@read.get("/health")
def health(request: Request, s: DB):
    s.execute(text("SELECT 1"))
    counts = {m.__tablename__: s.scalar(select(func.count()).select_from(m)) for m in (Question, Report, Case)}
    return {"status": "ok", "db": request.app.state.engine.dialect.name,
            "data_imported": views.meta_value(s, "data_sha256") is not None, "counts": counts,
            "writes_enabled": request.app.state.settings.writes_enabled,
            "version": request.app.state.version}


@read.get("/taxonomy")
def get_taxonomy():
    return views.taxonomy_view()


@read.get("/settings")
def get_settings(request: Request, s: DB):
    st = request.app.state.settings
    return {
        "version": request.app.state.version,
        "writes_enabled": st.writes_enabled,
        "database": request.app.state.engine.dialect.name,
        "engine": {"provider": st.llm_provider, "model": st.llm_model or None,
                   "mode": "rules_only" if st.llm_provider == "none" else "llm"},
        "thresholds": {"auto_apply_min_confidence": st.auto_apply_min_confidence,
                       "no_change_min_confidence": st.no_change_min_confidence},
        "data_sha256": views.meta_value(s, "data_sha256"),
    }


@read.get("/auth/status")
def auth_status(request: Request):
    """Public: whether writes are possible at all. Never reveals anything about the key."""
    return {"writes_enabled": request.app.state.settings.writes_enabled}


# ------------------------------------------------------------------ dashboard / queue

@read.get("/dashboard")
def get_dashboard(request: Request, s: DB):
    return views.dashboard(s, _now(request))


CaseStatus = Literal["all", "resolved", "untriaged", "needs_review", "auto_pending", "auto_fixed", "no_change",
                     "approved", "rejected", "investigating", "duplicate", "rolled_back"]


@read.get("/cases")
def list_cases(request: Request, s: DB, limit: Limit = 50, offset: Offset = 0,
               status: CaseStatus = "all", defects_only: bool = False,
               subject: Annotated[str | None, Query(max_length=64)] = None,
               verdict: Literal["defect", "no_error", "display_issue", "app_issue", "language_mode",
                                "already_fixed", "not_actionable"] | None = None,
               confidence: Literal["low", "medium", "high", "very_high"] | None = None,
               priority: Literal["critical", "high", "normal", "low"] | None = None,
               q: Annotated[str | None, Query(max_length=64)] = None,
               sort: Literal["urgency", "latest", "confidence", "reports"] = "urgency",
               order: Literal["asc", "desc"] = "desc"):
    return views.case_page(s, _now(request), status=status, defects_only=defects_only, subject=subject,
                           verdict=verdict, confidence=confidence, priority=priority, q=q, sort=sort,
                           order=order, limit=limit, offset=offset)


@read.get("/cases/{question_id}")
def get_case(request: Request, s: DB, question_id: QID):
    detail = views.case_detail(s, question_id, _now(request))
    if detail is None:
        raise ApiError(404, "not_found", f"No case for question {question_id}.")
    return detail


# ------------------------------------------------------------------ reports

@read.get("/reports")
def list_reports(s: DB, limit: Limit = 50, offset: Offset = 0,
                 question_id: Annotated[str | None, Query(pattern=r"^[0-9a-f]{24}$")] = None,
                 source: Literal["android", "ios", "web"] | None = None,
                 q: Annotated[str | None, Query(max_length=64)] = None):
    return views.report_page(s, question_id=question_id, source=source, q=q, limit=limit, offset=offset)


@read.get("/reports/{report_id}")
def get_report(s: DB, report_id: RID):
    r = s.get(Report, report_id)
    if r is None:
        raise ApiError(404, "not_found", f"No report {report_id}.")
    return views.report_detail(s, r)


# ------------------------------------------------------------------ questions / history

@read.get("/questions/{question_id}")
def get_question(s: DB, question_id: QID, version: Literal["current", "original"] = "current"):
    return views.question_view(_question(s, question_id), version)


@read.get("/questions/{question_id}/history")
def get_question_history(s: DB, question_id: QID):
    return views.question_history(s, _question(s, question_id))


@read.get("/questions/{question_id}/revisions")
def get_question_revisions(s: DB, question_id: QID, limit: Limit = 50, offset: Offset = 0):
    _question(s, question_id)
    return views.revision_page(s, question_id=question_id, limit=limit, offset=offset)


@read.get("/revisions")
def list_revisions(s: DB, limit: Limit = 50, offset: Offset = 0,
                   question_id: Annotated[str | None, Query(pattern=r"^[0-9a-f]{24}$")] = None):
    return views.revision_page(s, question_id=question_id, limit=limit, offset=offset)


@read.get("/audit")
def list_audit(s: DB, limit: Limit = 50, offset: Offset = 0,
               question_id: Annotated[str | None, Query(pattern=r"^[0-9a-f]{24}$")] = None,
               report_id: Annotated[str | None, Query(pattern=r"^R\d{3,6}$")] = None,
               actor_type: Literal["system", "ai", "faculty"] | None = None,
               event_type: Annotated[str | None, Query(pattern=r"^[a-z_]{3,40}$")] = None,
               since: datetime | None = None, until: datetime | None = None,
               order: Literal["asc", "desc"] = "asc"):
    since, until = (d if d is None or d.tzinfo else d.replace(tzinfo=timezone.utc) for d in (since, until))
    return views.audit_page(s, question_id=question_id, report_id=report_id, actor_type=actor_type,
                            event_type=event_type, since=since, until=until, order=order,
                            limit=limit, offset=offset)


@read.get("/audit/verify")
def verify_audit(s: DB):
    return audit.verify(s)


# ------------------------------------------------------------------ triage outputs (Phase 4)

@read.get("/results")
def get_results(s: DB):
    """Current triage results in the exact results.json schema (one entry per report)."""
    return triage_store.results_from_db(s)


@read.get("/bonus-findings")
def get_bonus_findings(s: DB):
    """Unreported question-level findings, computed from the current records and current results."""
    questions = [q.current for q in s.scalars(select(Question).order_by(Question.id))]
    findings = triage_engine.bonus_findings(questions, triage_store.covered_from_db(s))
    return {"engine": triage_engine.ENGINE, "engine_mode": triage_engine.ENGINE_MODE,
            "questions_inspected": len(questions), "total": len(findings), "items": findings}


@read.get("/triage/runs")
def list_triage_runs(s: DB, limit: Limit = 50, offset: Offset = 0):
    total = s.scalar(select(func.count()).select_from(TriageRun))
    rows = s.scalars(select(TriageRun).order_by(TriageRun.id.desc()).limit(limit).offset(offset)).all()
    return {"total": total, "limit": limit, "offset": offset, "items": [
        {"id": r.id, "mode": r.mode, "provider": r.provider, "model": r.model, "prompt_versions": r.prompt_versions,
         "started_at": r.started_at, "finished_at": r.finished_at, "calls": r.calls, "failures": r.failures}
        for r in rows]}


# ------------------------------------------------------------------ writes (faculty key required)

class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    actor: str = Field(pattern=r"^[\w .-]{2,60}$")


class InvestigateIn(_Body):
    note: str = Field(min_length=3, max_length=500)


class ReopenIn(_Body):
    note: str | None = Field(default=None, max_length=500)


@write.post("/auth/verify")
def verify_key():
    """Lets the console check a typed key before using it. Reaching here means the key is valid."""
    return {"ok": True}


@write.post("/cases/{question_id}/investigate")
def investigate(request: Request, s: DB, question_id: QID, body: InvestigateIn):
    case = s.get(Case, question_id)
    if case is None:
        raise ApiError(404, "not_found", f"No case for question {question_id}.")
    if case.status == "investigating":
        raise ApiError(409, "conflict", "Case is already under investigation.")
    before = case.status
    case.status = "investigating"
    audit.append(s, actor=f"faculty:{body.actor}", actor_type="faculty", event_type="investigation_requested",
                 question_id=question_id, before={"status": before}, after={"status": "investigating"},
                 note=body.note)
    s.commit()
    return views.case_detail(s, question_id, _now(request))


@write.post("/cases/{question_id}/reopen")
def reopen(request: Request, s: DB, question_id: QID, body: ReopenIn):
    """Ends an investigation, restoring the status the case had before it (from the audit trail)."""
    case = s.get(Case, question_id)
    if case is None:
        raise ApiError(404, "not_found", f"No case for question {question_id}.")
    if case.status != "investigating":
        raise ApiError(409, "conflict", f"Only a case under investigation can be reopened (status: {case.status}).")
    last = views.audit_page(s, question_id=question_id, event_type="investigation_requested",
                            order="desc", limit=1)["items"]
    restored = (last[0]["before"] or {}).get("status", "untriaged") if last else "untriaged"
    case.status = restored
    audit.append(s, actor=f"faculty:{body.actor}", actor_type="faculty", event_type="case_reopened",
                 question_id=question_id, before={"status": "investigating"}, after={"status": restored},
                 note=body.note)
    s.commit()
    return views.case_detail(s, question_id, _now(request))


# ------------------------------------------------------------------ Phase 5: faculty review actions

RepairID = Annotated[int, Path(ge=1, description="Repair id")]
RevisionID = Annotated[int, Path(ge=1, description="Revision id")]


class _EditProposal(BaseModel):
    """A single {field, find, replace} edit, the only shape we support (ADR-008, R-14)."""
    model_config = ConfigDict(extra="forbid")
    field: str = Field(min_length=1, max_length=16)
    find: Any          # str for question/solution/answer; list for mcq answer
    replace: Any       # same – JSON value, validated in faculty_actions


class ApproveIn(_Body):
    """Approve a proposed repair, optionally with an edited proposal (R-81)."""
    edit: _EditProposal | None = Field(default=None)
    note: str | None = Field(default=None, max_length=500)


class RejectIn(_Body):
    """Reject a proposed repair with a mandatory reason."""
    reason: str = Field(min_length=3, max_length=500)
    note: str | None = Field(default=None, max_length=500)


class ExecuteIn(_Body):
    """Execute (apply) an approved repair."""
    note: str | None = Field(default=None, max_length=500)


class RollbackIn(_Body):
    """Roll back a specific revision (RULES R-82)."""
    note: str | None = Field(default=None, max_length=500)


class DuplicateIn(_Body):
    """Mark a report as a duplicate of another."""
    duplicate_of: str = Field(pattern=r"^R\d{3,6}$")
    note: str | None = Field(default=None, max_length=500)


class EditReplyIn(_Body):
    """Edit the final student reply on a triage result."""
    reply: str = Field(min_length=1, max_length=320)
    note: str | None = Field(default=None, max_length=500)


class ValidateEditIn(BaseModel):
    """Dry-run validation of an edit against a repair type (no DB write)."""
    model_config = ConfigDict(extra="forbid")
    question_id: str = Field(pattern=r"^[0-9a-f]{24}$")
    repair_type: str = Field(min_length=1, max_length=32)
    edit: _EditProposal | None = None


def _repair_view(r: Repair, s) -> dict:
    from ..models import RepairReport
    report_ids = sorted(rr.report_id for rr in s.scalars(
        select(RepairReport).where(RepairReport.repair_id == r.id)
    ).all())
    return {"id": r.id, "question_id": r.question_id, "repair_type": r.repair_type,
            "edit": r.edit, "status": r.status, "confidence": r.confidence,
            "created_by": r.created_by, "created_at": r.created_at,
            "report_ids": report_ids}


@write.post("/repairs/{repair_id}/approve")
def approve_repair(request: Request, s: DB, repair_id: RepairID, body: ApproveIn):
    """Approve a proposed repair (RULES R-80, R-81, R-83, R-84).

    Optionally supply an edited proposal; it is re-validated (R-81). The response
    includes the before/after preview so the faculty can see what will change.
    """
    try:
        edit_dict = body.edit.model_dump() if body.edit is not None else None
        repair = faculty_actions.approve_repair(
            s, repair_id,
            actor=body.actor,
            edited_proposal=edit_dict,
            note=body.note,
        )
        s.commit()
    except LookupError as e:
        raise ApiError(404, "not_found", str(e))
    except ConflictError as e:
        raise ApiError(409, "conflict", str(e))
    except ValueError as e:
        raise ApiError(422, "validation_failed", str(e))

    # Return the repair plus a before/after preview if there is an executable edit.
    q = s.get(Question, repair.question_id)
    preview = None
    if repair.edit and q:
        try:
            preview = faculty_actions.repair_preview(q.current, repair.edit)
        except Exception:
            pass
    return {**_repair_view(repair, s), "preview": preview,
            "audit_ok": audit.verify(s)["ok"]}


@write.post("/repairs/{repair_id}/reject")
def reject_repair(s: DB, repair_id: RepairID, body: RejectIn):
    """Reject a proposed repair with a mandatory reason (RULES R-83, R-84)."""
    try:
        repair = faculty_actions.reject_repair(
            s, repair_id,
            actor=body.actor,
            reason=body.reason,
            note=body.note,
        )
        s.commit()
    except LookupError as e:
        raise ApiError(404, "not_found", str(e))
    except ConflictError as e:
        raise ApiError(409, "conflict", str(e))
    return {**_repair_view(repair, s), "audit_ok": audit.verify(s)["ok"]}


@write.post("/repairs/{repair_id}/execute")
def execute_repair(request: Request, s: DB, repair_id: RepairID, body: ExecuteIn):
    """Apply an approved repair atomically (RULES R-80, R-82, R-84).

    Requires the repair to be in `approved_applied` status.
    Uses compare-and-set: 409 if the field changed since approval.
    Never modifies original_json.
    """
    try:
        rev = faculty_actions.execute_repair(
            s, repair_id,
            actor=body.actor,
            note=body.note,
        )
        s.commit()
    except LookupError as e:
        raise ApiError(404, "not_found", str(e))
    except ConflictError as e:
        raise ApiError(409, "conflict", str(e))
    except ValueError as e:
        raise ApiError(422, "validation_failed", str(e))

    repair = s.get(Repair, repair_id)
    return {
        "revision_id": rev.id,
        "question_id": rev.question_id,
        "version": rev.version,
        "field": rev.field,
        "before": rev.before,
        "after": rev.after,
        "actor": rev.actor,
        "created_at": rev.created_at,
        "repair": _repair_view(repair, s),
        "audit_ok": audit.verify(s)["ok"],
    }


@write.post("/revisions/{revision_id}/rollback")
def rollback_revision(s: DB, revision_id: RevisionID, body: RollbackIn):
    """Roll back a specific revision (RULES R-82, R-84).

    - Faculty authorization required.
    - LIFO per field: the field must still hold this revision's after-value.
    - Creates a new revision; never deletes history.
    - 409 if already rolled back or if a later revision changed the same field.
    """
    try:
        rev = faculty_actions.rollback_revision(
            s, revision_id,
            actor=body.actor,
            note=body.note,
        )
        s.commit()
    except LookupError as e:
        raise ApiError(404, "not_found", str(e))
    except ConflictError as e:
        raise ApiError(409, "conflict", str(e))
    return {
        "rollback_revision_id": rev.id,
        "original_revision_id": revision_id,
        "question_id": rev.question_id,
        "version": rev.version,
        "field": rev.field,
        "restored_to": rev.after,
        "actor": rev.actor,
        "created_at": rev.created_at,
        "audit_ok": audit.verify(s)["ok"],
    }


@write.post("/reports/{report_id}/duplicate")
def mark_duplicate(s: DB, report_id: RID, body: DuplicateIn):
    """Mark a report as a duplicate of another (RULES R-63)."""
    try:
        rep = faculty_actions.mark_duplicate(
            s, report_id, body.duplicate_of,
            actor=body.actor,
            note=body.note,
        )
        s.commit()
    except LookupError as e:
        raise ApiError(404, "not_found", str(e))
    except ConflictError as e:
        raise ApiError(409, "conflict", str(e))
    except ValueError as e:
        raise ApiError(422, "validation_failed", str(e))
    return views.report_detail(s, rep)


@write.put("/reports/{report_id}/reply")
def edit_reply(s: DB, report_id: RID, body: EditReplyIn):
    """Edit the final student reply on a triage result (RULES R-70..R-73)."""
    try:
        result = faculty_actions.edit_reply(
            s, report_id, body.reply,
            actor=body.actor,
            note=body.note,
        )
        s.commit()
    except LookupError as e:
        raise ApiError(404, "not_found", str(e))
    except ValueError as e:
        raise ApiError(422, "validation_failed", str(e))
    return views.result_view(result)


@write.post("/validate-edit")
def validate_edit(s: DB, body: ValidateEditIn):
    """Dry-run validation of an edit against a repair type (R-10..R-14, R-31..R-42).
    Does not write anything. Returns {valid: bool, violations: [...]}.
    """
    q = s.get(Question, body.question_id)
    if q is None:
        raise ApiError(404, "not_found", f"No question with id {body.question_id}.")
    edit_dict = body.edit.model_dump() if body.edit is not None else None
    return faculty_actions.validate_edit_dryrun(q.current, body.repair_type, edit_dict)
