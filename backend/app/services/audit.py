"""Append-only, hash-chained audit log (RULES R-83)."""
import hashlib
import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import AuditEvent, utcnow

GENESIS = "0" * 64
ACTOR_TYPES = ("system", "ai", "faculty")


def _digest(prev_hash: str, ev: AuditEvent) -> str:
    body = {
        "ts": ev.ts.isoformat(), "actor": ev.actor, "actor_type": ev.actor_type,
        "event_type": ev.event_type, "question_id": ev.question_id, "report_id": ev.report_id,
        "repair_id": ev.repair_id, "before": ev.before, "after": ev.after,
        "rule_ids": ev.rule_ids, "note": ev.note,
    }
    canon = json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)
    return hashlib.sha256((prev_hash + canon).encode("utf-8")).hexdigest()


def append(s: Session, *, actor: str, actor_type: str, event_type: str, question_id=None,
           report_id=None, repair_id=None, before=None, after=None, rule_ids=None, note=None) -> AuditEvent:
    # ponytail: reads the chain head per append; fine for one process, needs a lock/sequence if multi-writer.
    if actor_type not in ACTOR_TYPES:
        raise ValueError(f"actor_type must be one of {ACTOR_TYPES}")
    s.flush()
    last = s.scalars(select(AuditEvent).order_by(AuditEvent.id.desc()).limit(1)).first()
    prev = last.hash if last else GENESIS
    ev = AuditEvent(ts=utcnow(), actor=actor, actor_type=actor_type, event_type=event_type,
                    question_id=question_id, report_id=report_id, repair_id=repair_id,
                    before=before, after=after, rule_ids=rule_ids, note=note, prev_hash=prev)
    ev.hash = _digest(prev, ev)
    s.add(ev)
    s.flush()
    return ev


def verify(s: Session) -> dict:
    prev, n = GENESIS, 0
    for ev in s.scalars(select(AuditEvent).order_by(AuditEvent.id)):
        n += 1
        if ev.prev_hash != prev or _digest(prev, ev) != ev.hash:
            return {"ok": False, "events": n, "first_bad_id": ev.id}
        prev = ev.hash
    return {"ok": True, "events": n, "first_bad_id": None}
