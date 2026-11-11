"""Low-level write path for question content: revision + current_json + audit, one transaction.

This layer enforces only data integrity (optimistic concurrency, rollback safety). Taxonomy scope
and repair guards (RULES R-10..R-42) are enforced by the validators that call it (Phase 5).
original_json is never touched (and a DB trigger would refuse it).
"""
import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import EDITABLE_FIELDS, Question, QuestionRevision
from . import audit


class ConflictError(Exception):
    """The stored value no longer matches what the caller expected (HTTP 409)."""


def _get(rec: dict, field: str):
    return rec["questionType"] if field == "questionType" else rec[rec["questionType"]][field]


def _set(rec: dict, field: str, value) -> None:
    if field == "questionType":
        rec[value] = rec.pop(rec["questionType"])  # body object is keyed by the type
        rec["questionType"] = value
    else:
        rec[rec["questionType"]][field] = value


def _write(s: Session, q: Question, field: str, before, after, actor, actor_type, event_type,
           repair_id, reverts, note) -> QuestionRevision:
    rec = q.current
    _set(rec, field, after)
    q.current_json = json.dumps(rec, ensure_ascii=False)
    q.version += 1
    rev = QuestionRevision(question_id=q.id, version=q.version, repair_id=repair_id, field=field,
                           before=before, after=after, actor=actor, reverts_revision_id=reverts)
    s.add(rev)
    s.flush()
    audit.append(s, actor=actor, actor_type=actor_type, event_type=event_type, question_id=q.id,
                 repair_id=repair_id, before=before, after=after, note=note)
    return rev


def apply_revision(s: Session, question_id: str, field: str, expected_before, after, *, actor: str,
                   actor_type: str, event_type: str, repair_id: int | None = None,
                   note: str | None = None) -> QuestionRevision:
    if field not in EDITABLE_FIELDS:
        raise ValueError(f"field {field!r} is not editable")
    q = s.get(Question, question_id)
    if q is None:
        raise LookupError(question_id)
    before = _get(q.current, field)
    if before != expected_before:
        raise ConflictError(f"{field} changed since the proposal was made")
    if before == after:
        raise ConflictError(f"{field} already has the proposed value")
    return _write(s, q, field, before, after, actor, actor_type, event_type, repair_id, None, note)


def rollback_revision(s: Session, revision_id: int, *, actor: str, actor_type: str,
                      note: str | None = None) -> QuestionRevision:
    """Restore `before` of a revision (RULES R-82). Allowed only while the field still holds that
    revision's `after` value, so a later change is never silently clobbered."""
    rev = s.get(QuestionRevision, revision_id)
    if rev is None:
        raise LookupError(revision_id)
    if s.scalars(select(QuestionRevision).where(QuestionRevision.reverts_revision_id == rev.id)).first():
        raise ConflictError("revision already rolled back")
    q = s.get(Question, rev.question_id)
    current = _get(q.current, rev.field)
    if current != rev.after:
        raise ConflictError("field changed after this revision; roll back the later revision first")
    return _write(s, q, rev.field, current, rev.before, actor, actor_type, "rolled_back",
                  rev.repair_id, rev.id, note)
