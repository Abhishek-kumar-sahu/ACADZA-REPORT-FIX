"""SQLAlchemy models. See docs/DATABASE_SCHEMA.md. Datetimes: UTCDateTime (naive UTC in the DB, aware in Python).

original_json / current_json are TEXT holding the exact JSON record so the original can be
reproduced byte-for-byte and the immutability trigger compares plain text on every dialect.
"""
import json
from datetime import datetime, timezone

from sqlalchemy import (JSON, Boolean, CheckConstraint, DateTime, Float, ForeignKey, Index,
                        Integer, String, Text, TypeDecorator, UniqueConstraint)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from . import taxonomy

JSONT = JSON().with_variant(JSONB(), "postgresql")

# auto_pending: triage found an auto-eligible repair; nothing is applied until Phase 5 executes it.
CASE_STATUSES = ("untriaged", "needs_review", "auto_pending", "auto_fixed", "no_change", "approved", "rejected",
                 "investigating", "duplicate", "rolled_back")
MACHINE_STATUSES = ("untriaged", "needs_review", "auto_pending", "no_change")   # triage may overwrite these
REPAIR_STATUSES = ("proposed", "auto_applied", "approved_applied", "approved_no_edit", "rejected",
                   "rolled_back", "superseded")
EDITABLE_FIELDS = ("question", "solution", "answer", "questionType")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class UTCDateTime(TypeDecorator):
    """Stored as naive UTC (portable across SQLite/Postgres); always timezone-aware in Python, so the
    API serialises unambiguous '+00:00' timestamps. Naive input is rejected rather than guessed."""
    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("naive datetime; pass an aware UTC datetime")
        return value.astimezone(timezone.utc).replace(tzinfo=None)

    def process_result_value(self, value, dialect):
        return None if value is None else value.replace(tzinfo=timezone.utc)


def _in(col: str, values) -> str:
    return f"{col} IN ({', '.join(repr(v) for v in values)})"


class Base(DeclarativeBase):
    pass


class Meta(Base):
    __tablename__ = "meta"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text)


class Question(Base):
    __tablename__ = "questions"
    id: Mapped[str] = mapped_column(String(24), primary_key=True)
    qid: Mapped[str | None] = mapped_column(String(128))  # NOT unique in the source data
    question_type: Mapped[str] = mapped_column(String(32))
    subject: Mapped[str] = mapped_column(String(64))
    chapter: Mapped[str] = mapped_column(String(256))
    concept: Mapped[str | None] = mapped_column(String(256))
    sub_concept: Mapped[str | None] = mapped_column(String(256))
    level: Mapped[str | None] = mapped_column(String(16))
    original_json: Mapped[str] = mapped_column(Text)   # immutable (DB trigger)
    current_json: Mapped[str] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer, default=1)
    content_sha256: Mapped[str] = mapped_column(String(64))
    imported_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    @property
    def original(self) -> dict:
        return json.loads(self.original_json)

    @property
    def current(self) -> dict:
        return json.loads(self.current_json)


class Report(Base):
    __tablename__ = "reports"
    report_id: Mapped[str] = mapped_column(String(16), primary_key=True)
    question_id: Mapped[str] = mapped_column(ForeignKey("questions.id"), index=True)
    student_id: Mapped[str] = mapped_column(String(64))
    source: Mapped[str] = mapped_column(String(16))
    reported_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    comment: Mapped[str] = mapped_column(Text)
    injection_suspected: Mapped[bool] = mapped_column(Boolean, default=False)
    duplicate_of: Mapped[str | None] = mapped_column(ForeignKey("reports.report_id"))


class Case(Base):
    __tablename__ = "cases"
    question_id: Mapped[str] = mapped_column(ForeignKey("questions.id"), primary_key=True)
    origin: Mapped[str] = mapped_column(String(8), default="student")
    status: Mapped[str] = mapped_column(String(16), default="untriaged")
    urgency: Mapped[int] = mapped_column(Integer, default=0)
    urgency_breakdown: Mapped[dict | None] = mapped_column(JSONT)
    assigned_to: Mapped[str | None] = mapped_column(String(64))
    first_reported_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)
    __table_args__ = (
        CheckConstraint(_in("status", CASE_STATUSES), name="ck_case_status"),
        CheckConstraint(_in("origin", ("student", "system")), name="ck_case_origin"),
        Index("ix_cases_status_urgency", "status", "urgency"),
    )


class TriageRun(Base):
    __tablename__ = "triage_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    mode: Mapped[str] = mapped_column(String(16))  # llm | rules_only | snapshot
    provider: Mapped[str | None] = mapped_column(String(32))
    model: Mapped[str | None] = mapped_column(String(64))
    prompt_versions: Mapped[dict | None] = mapped_column(JSONT)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    calls: Mapped[int] = mapped_column(Integer, default=0)
    failures: Mapped[int] = mapped_column(Integer, default=0)
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)
    __table_args__ = (CheckConstraint(_in("mode", ("llm", "rules_only", "snapshot")), name="ck_run_mode"),)


class TriageResult(Base):
    __tablename__ = "triage_results"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    report_id: Mapped[str] = mapped_column(ForeignKey("reports.report_id"), index=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("triage_runs.id"))
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)
    complaint_class: Mapped[str | None] = mapped_column(String(32))
    verdict: Mapped[str] = mapped_column(String(32))
    repair: Mapped[str | None] = mapped_column(String(32))
    edit: Mapped[dict | None] = mapped_column(JSONT)
    route: Mapped[str] = mapped_column(String(16))
    confidence: Mapped[float] = mapped_column(Float)
    evidence: Mapped[str] = mapped_column(Text)            # observed facts (results.json evidence string)
    inference: Mapped[str | None] = mapped_column(Text)    # what the engine concludes
    recommendation: Mapped[str | None] = mapped_column(Text)
    review_reason: Mapped[str | None] = mapped_column(Text)  # why a human must decide
    signals: Mapped[dict | None] = mapped_column(JSONT)
    suggestion: Mapped[dict | None] = mapped_column(JSONT)
    reply_draft: Mapped[str] = mapped_column(Text, default="")
    reply_final: Mapped[str | None] = mapped_column(Text)
    reply_status: Mapped[str] = mapped_column(String(8), default="draft")
    engine_mode: Mapped[str] = mapped_column(String(16))
    __table_args__ = (
        CheckConstraint(_in("verdict", taxonomy.verdicts()), name="ck_result_verdict"),
        CheckConstraint(f"repair IS NULL OR {_in('repair', taxonomy.repairs())}", name="ck_result_repair"),
        CheckConstraint(_in("route", taxonomy.ROUTES), name="ck_result_route"),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_result_confidence"),
        # R-02: a repair only accompanies a defect.
        CheckConstraint("repair IS NULL OR verdict = 'defect'", name="ck_result_repair_needs_defect"),
        CheckConstraint(_in("engine_mode", ("llm", "rules_only")), name="ck_result_engine_mode"),
    )


class Repair(Base):
    __tablename__ = "repairs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    question_id: Mapped[str] = mapped_column(ForeignKey("questions.id"), index=True)
    repair_type: Mapped[str] = mapped_column(String(32))
    edit: Mapped[list | dict | None] = mapped_column(JSONT)  # internal form may be a list (multi-field)
    status: Mapped[str] = mapped_column(String(20), default="proposed")
    confidence: Mapped[float] = mapped_column(Float)
    created_by: Mapped[str] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    __table_args__ = (
        CheckConstraint(_in("repair_type", taxonomy.repairs()), name="ck_repair_type"),
        CheckConstraint(_in("status", REPAIR_STATUSES), name="ck_repair_status"),
    )


class RepairReport(Base):
    __tablename__ = "repair_reports"
    repair_id: Mapped[int] = mapped_column(ForeignKey("repairs.id"), primary_key=True)
    report_id: Mapped[str] = mapped_column(ForeignKey("reports.report_id"), primary_key=True)


class QuestionRevision(Base):
    """Append-only (DB trigger). Rollback = a new revision with reverts_revision_id set."""
    __tablename__ = "question_revisions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    question_id: Mapped[str] = mapped_column(ForeignKey("questions.id"))
    version: Mapped[int] = mapped_column(Integer)
    repair_id: Mapped[int | None] = mapped_column(ForeignKey("repairs.id"))
    field: Mapped[str] = mapped_column(String(16))
    before: Mapped[object] = mapped_column(JSONT)
    after: Mapped[object] = mapped_column(JSONT)
    actor: Mapped[str] = mapped_column(String(80))
    reverts_revision_id: Mapped[int | None] = mapped_column(ForeignKey("question_revisions.id"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    __table_args__ = (
        UniqueConstraint("question_id", "version", name="uq_revision_version"),
        CheckConstraint(_in("field", EDITABLE_FIELDS), name="ck_revision_field"),
    )


class AiCall(Base):
    __tablename__ = "ai_calls"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("triage_runs.id"), index=True)
    question_id: Mapped[str | None] = mapped_column(String(24), index=True)
    stage: Mapped[str] = mapped_column(String(16))
    provider: Mapped[str] = mapped_column(String(32))
    model: Mapped[str] = mapped_column(String(64))
    prompt_id: Mapped[str] = mapped_column(String(32))
    prompt_version: Mapped[str] = mapped_column(String(8))
    prompt_sha256: Mapped[str] = mapped_column(String(64))
    input_sha256: Mapped[str] = mapped_column(String(64))
    request_text: Mapped[str] = mapped_column(Text)
    raw_output: Mapped[str | None] = mapped_column(Text)
    parsed_ok: Mapped[bool] = mapped_column(Boolean, default=False)
    validation_errors: Mapped[list | None] = mapped_column(JSONT)
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    tokens_in: Mapped[int | None] = mapped_column(Integer)
    tokens_out: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class AuditEvent(Base):
    """Append-only (DB triggers) and hash-chained (services/audit.py)."""
    __tablename__ = "audit_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    actor: Mapped[str] = mapped_column(String(80))
    actor_type: Mapped[str] = mapped_column(String(8))
    event_type: Mapped[str] = mapped_column(String(32), index=True)
    question_id: Mapped[str | None] = mapped_column(String(24))
    report_id: Mapped[str | None] = mapped_column(String(16))
    repair_id: Mapped[int | None] = mapped_column(Integer)
    before: Mapped[object | None] = mapped_column(JSONT)
    after: Mapped[object | None] = mapped_column(JSONT)
    rule_ids: Mapped[list | None] = mapped_column(JSONT)
    note: Mapped[str | None] = mapped_column(Text)
    prev_hash: Mapped[str] = mapped_column(String(64))
    hash: Mapped[str] = mapped_column(String(64), unique=True)
    __table_args__ = (
        CheckConstraint(_in("actor_type", ("system", "ai", "faculty")), name="ck_audit_actor_type"),
        Index("ix_audit_question_ts", "question_id", "ts"),
    )
