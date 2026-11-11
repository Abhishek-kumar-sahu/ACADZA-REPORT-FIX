"""A question record parsed into what triage needs: stem, options, solution, canonical answer,
answer-format issues, and edit history. Pure function of the stored record, no I/O.
"""
import re
from dataclasses import dataclass, field
from datetime import datetime

from ..importer import parse_ts
from .html_parse import Option, html_to_text, solution_final, split_options

LETTER_RE = re.compile(r"^[A-D]$")
INT_RE = re.compile(r"^-?\d+(\.\d+)?$")


@dataclass
class ParsedRecord:
    id: str
    type: str
    subject: str
    chapter: str
    stem_html: str
    stem_text: str
    options: list[Option]
    solution_text: str
    solution_final: dict | None
    answer_raw: object
    answer: object                    # canonical: "A" | "3113" | ["A","B","D"]
    answer_issues: list[str] = field(default_factory=list)
    history: list[dict] = field(default_factory=list)

    @property
    def letters(self) -> list[str]:
        return [o.letter for o in self.options]

    def option(self, letter: str) -> Option | None:
        return next((o for o in self.options if o.letter == letter), None)


def canonical_answer(qtype: str, raw, options: list[Option]) -> tuple[object, list[str]]:
    """Normalise the stored answer and report every format problem (RULES §5 answer_malformed).
    mcq canonical = sorted unique list of single letters (decision 2 / ADR-008)."""
    issues: list[str] = []
    if qtype == "integerQuestion":
        if not isinstance(raw, str) or not INT_RE.match(raw.strip()):
            issues.append("not_numeric")
        return (raw.strip() if isinstance(raw, str) else raw), issues

    if qtype == "scq":
        if not isinstance(raw, str):
            return raw, ["not_a_string"]
        letters = [raw.strip().upper()]
        if not LETTER_RE.match(letters[0]):
            issues.append("not_a_letter")
        canon = letters[0]
    else:  # mcq
        if not isinstance(raw, list):
            return raw, ["not_a_list"]
        letters = []
        for el in raw:
            if not isinstance(el, str) or not el.strip():
                issues.append("empty_element")
                continue
            parts = [p for p in re.split(r"[\s,;]+", el.strip().upper()) if p]
            if len(parts) > 1:
                issues.append("joined_string")
            letters.extend(parts)
        if any(not LETTER_RE.match(x) for x in letters):
            issues.append("not_a_letter")
        if len(set(letters)) != len(letters):
            issues.append("duplicate_letter")
        if not letters:
            issues.append("empty_answer")
        canon = sorted(set(letters))
        if canon == raw:
            issues = [i for i in issues if i not in ("joined_string",)]

    by_letter = {o.letter: o for o in options}
    for x in letters:
        if LETTER_RE.match(x):
            if x not in by_letter:
                issues.append(f"keyed_option_missing:{x}")
            elif by_letter[x].blank:
                issues.append(f"keyed_option_blank:{x}")
    return canon, sorted(set(issues))


def parse_record(rec: dict) -> ParsedRecord:
    qtype = rec["questionType"]
    body = rec[qtype]
    if qtype == "integerQuestion":
        stem_html, options = body["question"], []
    else:
        stem_html, options = split_options(body["question"])
    sol_text = html_to_text(body.get("solution") or "")
    answer, issues = canonical_answer(qtype, body["answer"], options)
    if qtype != "integerQuestion" and len(options) != 4:
        issues.append(f"option_count:{len(options)}")
    return ParsedRecord(
        id=rec["_id"], type=qtype, subject=rec["subject"], chapter=rec["chapter"],
        stem_html=stem_html, stem_text=html_to_text(stem_html), options=options,
        solution_text=sol_text, solution_final=solution_final(sol_text),
        answer_raw=body["answer"], answer=answer, answer_issues=sorted(set(issues)),
        history=list(rec.get("errorHistory") or []))


def history_after(rec_or_parsed, reported_at: datetime) -> list[dict]:
    """errorHistory entries recorded after a report: a prior fix must be considered before any
    repair is proposed (already_fixed, RULES R-22)."""
    hist = rec_or_parsed.history if isinstance(rec_or_parsed, ParsedRecord) else rec_or_parsed.get("errorHistory") or []
    return [h for h in hist if parse_ts(h["at"]) > reported_at]
