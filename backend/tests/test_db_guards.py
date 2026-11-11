"""Originals immutable, audit + revisions append-only, rollback safe (RULES R-80, R-82, R-83)."""
import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from backend.app.models import AuditEvent, Question, QuestionRevision
from backend.app.services import audit
from backend.app.services.revisions import ConflictError, apply_revision, rollback_revision

QID = "61dffbec08489156b684bd22"  # "Epithellial tisue" spelling question


def _raises_db(session, sql, **params):
    with pytest.raises(DBAPIError):
        session.execute(text(sql), params)
        session.flush()
    session.rollback()


def test_original_json_update_blocked(session):  # T-I-08
    _raises_db(session, "UPDATE questions SET original_json = '{}' WHERE id = :i", i=QID)


def test_question_delete_blocked(session):
    _raises_db(session, "DELETE FROM questions WHERE id = :i", i=QID)


def test_audit_update_and_delete_blocked(session):  # T-I-09
    _raises_db(session, "UPDATE audit_events SET note = 'x'")
    _raises_db(session, "DELETE FROM audit_events")


def test_current_json_is_writable(session):
    session.execute(text("UPDATE questions SET version = version WHERE id = :i"), {"i": QID})
    session.rollback()


def _question_field(session, field="question"):
    q = session.get(Question, QID)
    return q.current["scq"][field]


def test_apply_then_rollback_restores_and_keeps_original(session, qmap):  # T-I-07
    before = _question_field(session)
    after = before.replace("Epithellial tisue", "Epithelial tissue")
    rev = apply_revision(session, QID, "question", before, after, actor="system",
                         actor_type="system", event_type="auto_applied")
    session.commit()
    q = session.get(Question, QID)
    assert "Epithelial tissue" in q.current["scq"]["question"] and q.version == 2
    assert q.original == qmap[QID]  # source record untouched

    rb = rollback_revision(session, rev.id, actor="faculty:Meera", actor_type="faculty")
    session.commit()
    q = session.get(Question, QID)
    assert q.current["scq"]["question"] == before and q.version == 3
    assert q.original == qmap[QID]
    assert rb.reverts_revision_id == rev.id
    assert [e.event_type for e in session.scalars(select(AuditEvent).order_by(AuditEvent.id))][-2:] == [
        "auto_applied", "rolled_back"]
    assert audit.verify(session)["ok"]

    _raises_db(session, "UPDATE question_revisions SET actor = 'x'")
    _raises_db(session, "DELETE FROM question_revisions")


def test_stale_find_conflicts(session):
    with pytest.raises(ConflictError):
        apply_revision(session, QID, "answer", "B", "C", actor="system", actor_type="system",
                       event_type="auto_applied")  # stored answer is "A", not "B"


def test_noop_edit_conflicts(session):
    with pytest.raises(ConflictError):
        apply_revision(session, QID, "answer", "A", "A", actor="system", actor_type="system",
                       event_type="auto_applied")


def test_rollback_refused_after_later_change_and_twice(session):
    r1 = apply_revision(session, QID, "answer", "A", "B", actor="system", actor_type="system", event_type="auto_applied")
    r2 = apply_revision(session, QID, "answer", "B", "C", actor="system", actor_type="system", event_type="auto_applied")
    with pytest.raises(ConflictError, match="later revision"):
        rollback_revision(session, r1.id, actor="faculty:x", actor_type="faculty")
    rollback_revision(session, r2.id, actor="faculty:x", actor_type="faculty")
    with pytest.raises(ConflictError, match="already rolled back"):
        rollback_revision(session, r2.id, actor="faculty:x", actor_type="faculty")
    rollback_revision(session, r1.id, actor="faculty:x", actor_type="faculty")  # LIFO order works
    session.commit()
    assert _question_field(session, "answer") == "A"
    assert len(session.scalars(select(QuestionRevision)).all()) == 4


def test_question_type_revision_moves_body(session):
    mcq = "68f21caf941cda588bc04365"
    apply_revision(session, mcq, "questionType", "mcq", "scq", actor="system", actor_type="system",
                   event_type="faculty_approved")
    rec = session.get(Question, mcq).current
    assert rec["questionType"] == "scq" and "scq" in rec and "mcq" not in rec


def test_tampered_chain_detected(session):
    # Simulate an out-of-band edit by recomputing nothing: drop the trigger, alter, verify.
    if session.bind.dialect.name != "sqlite":
        pytest.skip("trigger manipulation test is SQLite-only")
    session.execute(text("DROP TRIGGER audit_no_update"))
    session.execute(text("UPDATE audit_events SET note = 'tampered' WHERE id = 3"))
    res = audit.verify(session)
    assert res["ok"] is False and res["first_bad_id"] == 3
