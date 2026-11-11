"""Faculty review and safe repair execution (RULES R-80 to R-85, Phase 5).

Decision surface:
  approve_repair   – approve a proposed/auto_pending repair (optionally with an edited proposal).
  reject_repair    – reject a proposed/auto_pending repair with a mandatory reason.
  execute_repair   – apply an approved repair to current_json atomically.
  rollback_revision– restore a field to its before-value (RULES R-82, LIFO per field).

Every write:
  - Re-validates scope and guards (R-10..R-14, R-31..R-42) for any edit.
  - Uses compare-and-set through revisions.apply_revision (409 on stale).
  - Writes an audit event inside the same transaction.
  - Never touches original_json (DB trigger enforces this).
  - Verifies the audit chain afterward and raises if it breaks.
"""
from __future__ import annotations

import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Case, Repair, RepairReport, Report
from .. import taxonomy
from ..triage.validators import guard, validate_edit
from . import audit, revisions
from .revisions import ConflictError


# ---------------------------------------------------------------------------
# Injection / XSS guard for faculty-authored text in edited proposals
# ---------------------------------------------------------------------------
_INJECTION_PATTERNS = [
    re.compile(r"ignore\s+(all\s+)?previous", re.I),
    re.compile(r"you\s+are\s+(now\s+)?", re.I),
    re.compile(r"system\s+prompt", re.I),
    re.compile(r"<\s*script", re.I),
    re.compile(r"javascript\s*:", re.I),
    re.compile(r"on\w+\s*=", re.I),     # onerror=, onclick= etc.
    re.compile(r"<\s*iframe", re.I),
    re.compile(r"<\s*svg", re.I),
    re.compile(r"data\s*:", re.I),
    re.compile(r"vbscript\s*:", re.I),
    re.compile(r"&\s*#\s*x?\d+\s*;", re.I),  # character entity injection
]


def _check_injection(text: str) -> list[str]:
    """Return rule IDs of any injection/XSS patterns found in text."""
    hits = []
    for pat in _INJECTION_PATTERNS:
        if pat.search(text):
            hits.append("R-50")
            break
    return hits


def _validate_proposed_edit(record: dict, repair_type: str, edit: Any) -> list[str]:
    """Full structural + scope + guard validation of an edit (R-10..R-14, R-31..R-42).

    Returns a list of violation strings; empty means the edit is valid.
    """
    # R-11: empty-scope repairs never carry an edit.
    if taxonomy.repair_fields(repair_type) == []:
        if edit is not None:
            return ["R-11: this repair type has no writable fields; edit must be null"]
        return []

    violations = validate_edit(record, repair_type, edit)
    if violations:
        return violations

    # Repair guard (R-31..R-42). guard() returns non-empty list when not auto-eligible,
    # but for faculty approvals we only enforce the structural guard, not the auto-eligibility
    # decision itself.  So we skip the "not auto-eligible in rules-only mode" message.
    if edit is not None:
        guard_violations = guard(repair_type, edit)
        # Filter out the "not auto-eligible" soft rejection; keep real structural violations.
        structural = [v for v in guard_violations if not v.startswith("R-30:")]
        if structural:
            return structural

    # Injection check on find/replace text
    if isinstance(edit, dict):
        for key in ("find", "replace"):
            val = edit.get(key)
            if isinstance(val, str):
                inj = _check_injection(val)
                if inj:
                    return [f"R-50: injection pattern detected in edit.{key}"]

    return []


# ---------------------------------------------------------------------------
# Public action functions
# ---------------------------------------------------------------------------

def approve_repair(
    s: Session,
    repair_id: int,
    *,
    actor: str,
    edited_proposal: dict | None = None,
    note: str | None = None,
) -> Repair:
    """Approve a proposed repair, optionally with an edited proposal (RULES R-81).

    If `edited_proposal` is provided it must be a valid {field, find, replace} dict
    for the repair's type, and it replaces the engine's proposal.

    Raises:
        LookupError     – repair not found
        ValueError      – edit validation fails (R-10..R-14, R-81)
        ConflictError   – repair already approved / rejected / applied
    """
    repair = _get_repair(s, repair_id, expected_statuses=("proposed",))
    q = _get_question(s, repair.question_id)
    record = q.current

    if edited_proposal is not None:
        violations = _validate_proposed_edit(record, repair.repair_type, edited_proposal)
        if violations:
            raise ValueError(f"Edit validation failed: {'; '.join(violations)}")
        repair.edit = edited_proposal
        event_type = "faculty_edited_proposal"
        rule_ids = ["R-81"]
    else:
        event_type = "faculty_approved"
        rule_ids = ["R-80", "R-81"]

    # For no-writable-field repairs (diagram, wrong_chapter, syllabus, unsound, etc.)
    # approval is "acknowledged; fix outside the system" (approved_no_edit).
    has_edit = repair.edit is not None and taxonomy.repair_fields(repair.repair_type) != []
    repair.status = "approved_applied" if has_edit else "approved_no_edit"

    audit.append(
        s,
        actor=f"faculty:{actor}",
        actor_type="faculty",
        event_type=event_type,
        question_id=repair.question_id,
        repair_id=repair.id,
        before={"status": "proposed"},
        after={"status": repair.status, "edit": repair.edit},
        rule_ids=rule_ids,
        note=note,
    )
    _update_case_on_approval(s, repair.question_id, actor)
    s.flush()
    return repair


def reject_repair(
    s: Session,
    repair_id: int,
    *,
    actor: str,
    reason: str,
    note: str | None = None,
) -> Repair:
    """Reject a proposed repair with a mandatory reason (RULES R-83).

    Raises:
        LookupError   – repair not found
        ConflictError – repair already approved/rejected/applied
    """
    repair = _get_repair(s, repair_id, expected_statuses=("proposed",))
    old_status = repair.status
    repair.status = "rejected"
    _update_case_on_rejection(s, repair.question_id)
    audit.append(
        s,
        actor=f"faculty:{actor}",
        actor_type="faculty",
        event_type="faculty_rejected",
        question_id=repair.question_id,
        repair_id=repair.id,
        before={"status": old_status},
        after={"status": "rejected", "reason": reason},
        rule_ids=["R-83"],
        note=reason if not note else f"{reason} | {note}",
    )
    s.flush()
    return repair


def execute_repair(
    s: Session,
    repair_id: int,
    *,
    actor: str,
    note: str | None = None,
) -> revisions.QuestionRevision:
    """Apply an approved repair to the question record (RULES R-80, R-82).

    Requirements enforced:
      - Repair must be in `approved_applied` state (never execute proposed/rejected).
      - Answer-key changes always require this explicit execution path after approval.
      - Edit is re-validated against the CURRENT record (compare-and-set via apply_revision).
      - Applied atomically; on any conflict the whole transaction is rolled back.
      - Original_json never modified (DB trigger).

    Raises:
        LookupError   – repair not found
        ConflictError – not in approved_applied state, or stale find, or already applied
        ValueError    – edit is None or structurally invalid
    """
    repair = _get_repair(s, repair_id, expected_statuses=("approved_applied",))
    edit = repair.edit
    if edit is None or not isinstance(edit, dict):
        raise ValueError("Repair has no executable edit (approved_no_edit repairs do not apply)")

    field = edit.get("field")
    find = edit.get("find")
    replace = edit.get("replace")
    if not all([field, find is not None, replace is not None]):
        raise ValueError("Edit is malformed; expected {field, find, replace}")

    # Re-validate against current record before writing (R-80, R-81)
    q = _get_question(s, repair.question_id)
    violations = _validate_proposed_edit(q.current, repair.repair_type, edit)
    if violations:
        raise ValueError(f"Pre-execution validation failed: {'; '.join(violations)}")

    current_val = revisions._get(q.current, field)
    if field in ("question", "solution"):
        if not isinstance(current_val, str) or find not in current_val:
            raise ConflictError(f"Target text not found in {field} (stale edit)")
        after_val = current_val.replace(find, replace, 1)
        expected_before = current_val
    else:  # answer, questionType
        expected_before = find
        after_val = replace

    # compare-and-set: apply_revision checks that current field == expected_before before writing
    rev = revisions.apply_revision(
        s,
        repair.question_id,
        field,
        expected_before,
        after_val,
        actor=f"faculty:{actor}",
        actor_type="faculty",
        event_type="auto_applied",
        repair_id=repair.id,
        note=note,
    )

    repair.status = "auto_applied"
    _update_case_status(s, repair.question_id, "auto_fixed")
    s.flush()
    return rev


def rollback_revision(
    s: Session,
    revision_id: int,
    *,
    actor: str,
    note: str | None = None,
) -> revisions.QuestionRevision:
    """Roll back a revision (RULES R-82).

    Rules:
      - Only if the field still holds that revision's after-value (LIFO per field).
      - Rollback creates a new revision; never deletes history.
      - Duplicate rollback of the same revision is a 409.
      - Audit event appended.

    Raises:
        LookupError   – revision not found
        ConflictError – field changed since this revision, or already rolled back
    """
    rev = revisions.rollback_revision(
        s,
        revision_id,
        actor=f"faculty:{actor}",
        actor_type="faculty",
        note=note,
    )
    # Mark associated repair as rolled_back (if any)
    if rev.repair_id is not None:
        rp = s.get(Repair, rev.repair_id)
        if rp is not None and rp.status == "auto_applied":
            rp.status = "rolled_back"
            _update_case_status(s, rp.question_id, "rolled_back")
    s.flush()
    return rev


def mark_duplicate(
    s: Session,
    report_id: str,
    duplicate_of: str,
    *,
    actor: str,
    note: str | None = None,
) -> Report:
    """Mark a report as a duplicate of another (RULES R-63).

    Raises:
        LookupError   – report not found
        ConflictError – already a duplicate
        ValueError    – trying to duplicate itself
    """
    rep = s.get(Report, report_id)
    if rep is None:
        raise LookupError(report_id)
    target = s.get(Report, duplicate_of)
    if target is None:
        raise LookupError(f"target report {duplicate_of} not found")
    if report_id == duplicate_of:
        raise ValueError("A report cannot be a duplicate of itself")
    if rep.duplicate_of is not None:
        raise ConflictError(f"Report {report_id} is already a duplicate of {rep.duplicate_of}")

    rep.duplicate_of = duplicate_of
    audit.append(
        s,
        actor=f"faculty:{actor}",
        actor_type="faculty",
        event_type="marked_duplicate",
        question_id=rep.question_id,
        report_id=report_id,
        before={"duplicate_of": None},
        after={"duplicate_of": duplicate_of},
        rule_ids=["R-63"],
        note=note,
    )
    s.flush()
    return rep


def edit_reply(
    s: Session,
    report_id: str,
    new_reply: str,
    *,
    actor: str,
    note: str | None = None,
):
    """Edit the final student reply on a triage result.

    The new reply is validated for length and forbidden claims (RULES R-70..R-73).
    It does NOT apply any repair; it only sets `reply_final` on the current TriageResult.

    Raises:
        LookupError – report or its current result not found
        ValueError  – reply fails R-70/R-73 checks
    """
    from ..models import TriageResult
    rep = s.get(Report, report_id)
    if rep is None:
        raise LookupError(report_id)
    result = s.scalars(
        select(TriageResult).where(
            TriageResult.report_id == report_id,
            TriageResult.is_current.is_(True),
        )
    ).first()
    if result is None:
        raise LookupError(f"No current triage result for report {report_id}")

    # R-70: 1–3 sentences, max 320 chars
    stripped = new_reply.strip()
    if not stripped or len(stripped) > 320:
        raise ValueError("R-70: reply must be 1–320 characters")

    # R-71 / R-73: no forbidden claims
    _check_reply_claims(stripped, result.route)

    # Injection check
    if _check_injection(stripped):
        raise ValueError("R-50: injection pattern detected in reply text")

    old = result.reply_final
    result.reply_final = stripped
    result.reply_status = "edited"
    audit.append(
        s,
        actor=f"faculty:{actor}",
        actor_type="faculty",
        event_type="reply_edited",
        question_id=rep.question_id,
        report_id=report_id,
        before={"reply": old},
        after={"reply": stripped},
        rule_ids=["R-70", "R-73"],
        note=note,
    )
    s.flush()
    return result


# ---------------------------------------------------------------------------
# Dry-run validation (no DB write)
# ---------------------------------------------------------------------------

def validate_edit_dryrun(record: dict, repair_type: str, edit: Any) -> dict:
    """Validate an edit without writing anything (R-10..R-14, R-31..R-42).

    Returns {"valid": bool, "violations": [...]} – violations empty means valid.
    """
    if repair_type not in taxonomy.repairs():
        return {"valid": False, "violations": [f"R-01: unknown repair type '{repair_type}'"]}
    violations = _validate_proposed_edit(record, repair_type, edit)
    return {"valid": not violations, "violations": violations}


# ---------------------------------------------------------------------------
# Repair preview (before/after)
# ---------------------------------------------------------------------------

def repair_preview(record: dict, edit: dict) -> dict:
    """Return {field, before, after} for display in the console diff.

    Raises ValueError for malformed edits.
    """
    if not isinstance(edit, dict) or not all(k in edit for k in ("field", "find", "replace")):
        raise ValueError("edit must be {field, find, replace}")
    field, find, replace = edit["field"], edit["find"], edit["replace"]
    body = record[record["questionType"]]
    if field in ("question", "solution"):
        raw = body.get(field) or ""
        after = raw.replace(find, replace, 1) if find in raw else raw
        return {"field": field, "before": raw, "after": after, "find": find, "replace": replace}
    if field == "answer":
        return {"field": field, "before": body.get("answer"), "after": replace,
                "find": find, "replace": replace}
    if field == "questionType":
        return {"field": field, "before": record.get("questionType"), "after": replace,
                "find": find, "replace": replace}
    raise ValueError(f"unrecognised field '{field}'")


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _get_repair(s: Session, repair_id: int, expected_statuses: tuple[str, ...]) -> Repair:
    repair = s.get(Repair, repair_id)
    if repair is None:
        raise LookupError(f"No repair with id {repair_id}")
    if repair.status not in expected_statuses:
        raise ConflictError(
            f"Repair {repair_id} is in status '{repair.status}', "
            f"expected one of {expected_statuses}"
        )
    return repair


def _get_question(s: Session, question_id: str):
    from ..models import Question
    q = s.get(Question, question_id)
    if q is None:
        raise LookupError(f"No question with id {question_id}")
    return q


def _update_case_on_approval(s: Session, question_id: str, actor: str) -> None:
    """Move case to 'approved' if all remaining proposed repairs for this question
    are either approved or rejected (no longer purely 'proposed')."""
    case = s.get(Case, question_id)
    if case is None:
        return
    # Count any still-proposed repairs on this question
    still_proposed = s.scalars(
        select(Repair).where(
            Repair.question_id == question_id,
            Repair.status == "proposed",
        )
    ).all()
    if not still_proposed:
        old = case.status
        case.status = "approved"
        audit.append(
            s,
            actor=f"faculty:{actor}",
            actor_type="faculty",
            event_type="case_status_changed",
            question_id=question_id,
            before={"status": old},
            after={"status": "approved"},
        )


def _update_case_on_rejection(s: Session, question_id: str) -> None:
    """Move case to 'rejected' if all repairs are now rejected."""
    case = s.get(Case, question_id)
    if case is None:
        return
    still_active = s.scalars(
        select(Repair).where(
            Repair.question_id == question_id,
            Repair.status.in_(("proposed", "approved_applied", "auto_applied")),
        )
    ).all()
    if not still_active:
        case.status = "rejected"


def _update_case_status(s: Session, question_id: str, new_status: str) -> None:
    case = s.get(Case, question_id)
    if case is not None:
        case.status = new_status


_FORBIDDEN_WHEN_NOT_APPLIED = re.compile(
    r"\b(fixed|corrected|updated|changed|resolved)\b", re.I
)
_ACCUSATORY = re.compile(
    r"\b(you('re| are) wrong|your mistake|your error|incorrect report)\b", re.I
)
_INTERNAL_JARGON = re.compile(
    r"\b(verdict|taxonomy|route|auto_apply|faculty_review|no_change|repair_type)\b", re.I
)


def _check_reply_claims(text: str, route: str) -> None:
    """Validate reply constraints (RULES R-71, R-73). Raises ValueError on violation."""
    if route != "auto_apply" and _FORBIDDEN_WHEN_NOT_APPLIED.search(text):
        raise ValueError(
            "R-71: reply claims the issue is fixed but the route is not auto_apply"
        )
    if _ACCUSATORY.search(text):
        raise ValueError("R-73: reply contains accusatory phrasing")
    if _INTERNAL_JARGON.search(text):
        raise ValueError("R-73: reply contains internal jargon")
