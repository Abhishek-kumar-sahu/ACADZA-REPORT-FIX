"""Import the read-only assignment datasets into the DB (docs/DATA_DICTIONARY.md).

- Verifies SHA-256 of every source file before reading it (changed data → abort, never load).
- Validates every record against the observed schema with extra="forbid" (schema drift → abort).
- Idempotent: a second run is a no-op once the same data is imported.
- Never opens anything under docs/ (reference notes are not data; see test_no_reference_leak).
"""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy.orm import Session

from .models import Case, Meta, Question, Report
from .services import audit

DATA_SHA256 = {
    "questions.json": "178d08f199386bdd1e94268449106f2ecf9c00b6f38d2fd4d79fb011f030641a",
    "reports.json": "042751d1f233395927e108240e5a011b6fa9bd8843296b67e3d1ebf610cb7b55",
    "taxonomy.json": "3100ea343cb758111dcd13cfb7ace4769a0be0dffc006d8f1dfc04208893d2df",
}
QTYPES = ("scq", "mcq", "integerQuestion")


class ImportError_(Exception):
    pass


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class BodyIn(_Strict):
    question: str = Field(min_length=1)
    solution: str
    answer: str | list[str]
    quesImages: list
    solutionImages: list


class HistoryIn(_Strict):
    type: str
    actor: str
    at: str
    note: str


class QuestionIn(_Strict):
    id: str = Field(alias="_id", pattern=r"^[0-9a-f]{24}$")
    qid: str | None
    questionType: Literal["scq", "mcq", "integerQuestion"]
    subject: str
    chapter: str
    concept: str | None
    subConcept: str | None
    level: str | None
    error: int
    updatedAt: str
    errorHistory: list[HistoryIn]
    scq: BodyIn | None = None
    mcq: BodyIn | None = None
    integerQuestion: BodyIn | None = None

    @model_validator(mode="after")
    def _one_body_matching_type(self):
        present = [t for t in QTYPES if getattr(self, t) is not None]
        if present != [self.questionType]:
            raise ValueError(f"body keys {present} do not match questionType {self.questionType}")
        ans = getattr(self, self.questionType).answer
        if (self.questionType == "mcq") != isinstance(ans, list):
            raise ValueError("mcq answer must be a list; scq/integer answer must be a string")
        return self


class ReportIn(_Strict):
    reportId: str = Field(pattern=r"^R\d{3,}$")
    questionId: str = Field(pattern=r"^[0-9a-f]{24}$")
    studentId: str
    source: Literal["android", "ios", "web"]
    reportedAt: str
    comment: str

    @field_validator("reportedAt")
    @classmethod
    def _iso(cls, v):
        parse_ts(v)
        return v


def parse_ts(v: str) -> datetime:
    """ISO-8601 → aware UTC. Tolerates 'Z' and variable fractional precision (e.g. '.33Z')."""
    dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError(f"timestamp without timezone: {v}")
    return dt.astimezone(timezone.utc)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_hashes(data_dir: Path) -> dict[str, str]:
    got = {}
    for name, want in DATA_SHA256.items():
        p = data_dir / name
        if not p.is_file():
            raise ImportError_(f"missing data file {p}")
        got[name] = sha256_file(p)
        if got[name] != want:
            raise ImportError_(f"data_hash_mismatch: {name} sha256 {got[name]} != expected {want}")
    return got


def load_validated(data_dir: Path) -> tuple[list[dict], list[dict]]:
    verify_hashes(data_dir)
    questions = json.loads((data_dir / "questions.json").read_text(encoding="utf-8"))
    reports = json.loads((data_dir / "reports.json").read_text(encoding="utf-8"))
    errors = []
    for i, q in enumerate(questions):
        try:
            QuestionIn.model_validate(q)
        except Exception as e:  # collect all, then fail once
            errors.append(f"questions[{i}] {q.get('_id')}: {e}")
    ids = [q["_id"] for q in questions]
    if len(set(ids)) != len(ids):
        errors.append("duplicate question _id")
    for i, r in enumerate(reports):
        try:
            ReportIn.model_validate(r)
        except Exception as e:
            errors.append(f"reports[{i}] {r.get('reportId')}: {e}")
        if r.get("questionId") not in set(ids):
            errors.append(f"reports[{i}] {r.get('reportId')}: unknown questionId {r.get('questionId')}")
    rids = [r.get("reportId") for r in reports]
    if len(set(rids)) != len(rids):
        errors.append("duplicate reportId")
    if errors:
        raise ImportError_("schema validation failed:\n" + "\n".join(errors))
    return questions, reports


def import_all(s: Session, data_dir: Path) -> dict:
    questions, reports = load_validated(data_dir)
    marker = s.get(Meta, "data_sha256")
    fingerprint = json.dumps(DATA_SHA256, sort_keys=True)
    if marker is not None:
        if marker.value != fingerprint:
            raise ImportError_("DB was imported from different data; delete the DB and re-import")
        return {"status": "already_imported"}

    for q in questions:
        raw = json.dumps(q, ensure_ascii=False)
        s.add(Question(
            id=q["_id"], qid=q["qid"], question_type=q["questionType"], subject=q["subject"],
            chapter=q["chapter"], concept=q["concept"], sub_concept=q["subConcept"], level=q["level"],
            original_json=raw, current_json=raw, version=1,
            content_sha256=hashlib.sha256(raw.encode("utf-8")).hexdigest()))
    s.flush()

    first_report: dict[str, datetime] = {}
    for r in sorted(reports, key=lambda r: (r["reportedAt"], r["reportId"])):
        ts = parse_ts(r["reportedAt"])
        s.add(Report(report_id=r["reportId"], question_id=r["questionId"], student_id=r["studentId"],
                     source=r["source"], reported_at=ts, comment=r["comment"]))
        first_report.setdefault(r["questionId"], ts)
    for qid, ts in first_report.items():
        s.add(Case(question_id=qid, origin="student", status="untriaged", first_reported_at=ts))
    s.flush()

    for r in sorted(reports, key=lambda r: (r["reportedAt"], r["reportId"])):
        audit.append(s, actor="system", actor_type="system", event_type="report_received",
                     question_id=r["questionId"], report_id=r["reportId"])
    s.add(Meta(key="data_sha256", value=fingerprint))
    summary = {"status": "imported", "questions": len(questions), "reports": len(reports),
               "cases": len(first_report)}
    audit.append(s, actor="system", actor_type="system", event_type="import_completed", after=summary)
    s.commit()
    return summary
