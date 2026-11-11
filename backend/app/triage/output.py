"""Output artefacts and their strict schemas.

results.json      exactly the README schema: one object per report, these 9 keys, nothing else.
bonus_findings.json  unreported question-level findings (never counted as reports).
triage_snapshot.json internal superset (evidence / inference / recommendation / review reason …).

All three are deterministic: no timestamps, stable ordering, fixed float rounding.
"""
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .. import taxonomy
from .engine import ENGINE, ENGINE_MODE, Decision, reply_violations
from .validators import validate_edit

RESULT_KEYS = ["reportId", "questionId", "verdict", "repair", "edit", "route", "confidence", "evidence",
               "student_reply"]
MAX_EVIDENCE = 300


class EditOut(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    field: Literal["question", "solution", "answer", "questionType"]
    find: str | list[str]
    replace: str | list[str]


class ResultOut(BaseModel):
    """The README result schema, strict: unknown keys, wrong types and unknown taxonomy values fail."""
    model_config = ConfigDict(extra="forbid", strict=True)
    reportId: str = Field(pattern=r"^R\d{3,6}$")
    questionId: str = Field(pattern=r"^[0-9a-f]{24}$")
    verdict: str
    repair: str | None
    edit: EditOut | None
    route: Literal["auto_apply", "faculty_review", "no_change"]
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: str = Field(min_length=1, max_length=MAX_EVIDENCE)
    student_reply: str = Field(min_length=1, max_length=320)

    @field_validator("verdict")
    @classmethod
    def _verdict(cls, v):
        if v not in taxonomy.verdicts():
            raise ValueError(f"unknown verdict {v!r}")
        return v

    @field_validator("repair")
    @classmethod
    def _repair(cls, v):
        if v is not None and v not in taxonomy.repairs():
            raise ValueError(f"unknown repair {v!r}")
        return v

    @model_validator(mode="after")
    def _coherent(self):
        if (self.repair is not None) != (self.verdict == "defect"):
            raise ValueError("R-02: repair is required for, and only for, verdict 'defect'")
        if self.repair is None and self.edit is not None:
            raise ValueError("R-02: an edit requires a repair")
        if self.repair and not taxonomy.repair_fields(self.repair) and self.edit is not None:
            raise ValueError(f"R-11: repair {self.repair!r} has no writable fields; edit must be null")
        if self.route == "auto_apply" and (self.verdict != "defect" or self.edit is None):
            raise ValueError("R-30: auto_apply requires a defect with an edit")
        return self


def _evidence(d: Decision) -> str:
    text = "; ".join(d.evidence)
    if d.review_reason:
        text += f". Review: {d.review_reason}"
    return text if len(text) <= MAX_EVIDENCE else text[:MAX_EVIDENCE - 3].rsplit(" ", 1)[0] + "..."


def result_entry(d: Decision) -> dict:
    return {"reportId": d.report_id, "questionId": d.question_id, "verdict": d.verdict, "repair": d.repair,
            "edit": d.edit, "route": d.route, "confidence": round(d.confidence, 2), "evidence": _evidence(d),
            "student_reply": d.reply}


def results(decisions: list[Decision]) -> list[dict]:
    return [result_entry(d) for d in sorted(decisions, key=lambda d: d.report_id)]


def validate_results(entries: list[dict], reports: list[dict], questions: list[dict]) -> list[str]:
    """Every contract check on results.json. Returns problems; empty means valid."""
    problems = []
    want = sorted(r["reportId"] for r in reports)
    got = [e.get("reportId") for e in entries]
    if len(entries) != len(reports):
        problems.append(f"expected {len(reports)} entries, got {len(entries)}")
    if sorted(got) != want:
        problems.append(f"reportIds differ from reports.json: missing {sorted(set(want) - set(got))}, "
                        f"extra {sorted(set(got) - set(want))}")
    if len(set(got)) != len(got):
        problems.append("duplicate reportIds")
    rq = {r["reportId"]: r["questionId"] for r in reports}
    qmap = {q["_id"]: q for q in questions}
    for e in entries:
        rid = e.get("reportId")
        if list(e) != RESULT_KEYS:
            problems.append(f"{rid}: keys must be exactly {RESULT_KEYS} in order, got {list(e)}")
        try:
            ResultOut.model_validate(e)
        except Exception as ex:  # collect all
            problems.append(f"{rid}: {ex}")
            continue
        if rq.get(rid) != e["questionId"]:
            problems.append(f"{rid}: questionId does not match reports.json")
            continue
        if e["edit"] is not None:
            for v in validate_edit(qmap[e["questionId"]], e["repair"], e["edit"]):
                problems.append(f"{rid}: {v}")
        for v in reply_violations(e["student_reply"], e["verdict"], e["route"]):
            problems.append(f"{rid}: {v}")
    return problems


class BonusOut(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    findingId: str = Field(pattern=r"^B\d{2,}$")
    questionId: str = Field(pattern=r"^[0-9a-f]{24}$")
    subject: str
    chapter: str
    field: Literal["question", "solution", "answer", "metadata"]
    category: str
    check: str
    status: Literal["verified", "suspected"]
    severity: Literal["high", "medium", "low"]
    evidence: str = Field(min_length=1)
    recommended_action: str = Field(min_length=1)

    @field_validator("category")
    @classmethod
    def _cat(cls, v):
        if v not in taxonomy.repairs():
            raise ValueError(f"unknown repair category {v!r}")
        return v


def bonus_document(findings: list[dict], questions_inspected: int) -> dict:
    for f in findings:
        BonusOut.model_validate(f)
    return {
        "about": "Unreported question-level findings from the rules engine's detectors. These are NOT student "
                 "reports and are not part of results.json. 'verified' = structural fact quoted from the record; "
                 "'suspected' = heuristic that needs a teacher.",
        "engine": ENGINE, "engine_mode": ENGINE_MODE, "questions_inspected": questions_inspected,
        "counts": {"verified": sum(f["status"] == "verified" for f in findings),
                   "suspected": sum(f["status"] == "suspected" for f in findings)},
        "findings": findings,
    }


def snapshot(decisions: list[Decision]) -> dict:
    return {"engine": ENGINE, "engine_mode": ENGINE_MODE,
            "decisions": [d.to_dict() for d in sorted(decisions, key=lambda d: d.report_id)]}


def dump(obj, path: Path) -> str:
    text = json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=False) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
    return text
