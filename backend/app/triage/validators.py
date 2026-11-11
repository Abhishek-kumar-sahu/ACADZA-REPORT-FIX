"""Deterministic edit validation (RULES R-10..R-14) and the repair guards needed for auto-eligibility
of the mechanical repairs the rules engine proposes (R-31 spelling, R-33 exam_reference, R-34 markup_leak,
R-35 answer_form). Every other repair is never auto-eligible in rules-only mode, so its guard is not
needed yet (Phase 5 adds the rest)."""
import re
from collections import Counter

from .. import taxonomy
from .detectors import EXAM_TAG, levenshtein
from .record import LETTER_RE, INT_RE

MAX_FIND = 300


def validate_edit(record: dict, repair: str, edit) -> list[str]:
    """Violations ('R-xx: message'); an empty list means the edit is structurally valid."""
    if edit is None:
        return []
    if not isinstance(edit, dict) or set(edit) != {"field", "find", "replace"}:
        return ["R-14: edit must be a single {field, find, replace} object"]
    field, find, rep = edit["field"], edit["find"], edit["replace"]
    allowed = taxonomy.repair_fields(repair)
    if field not in allowed:
        return [f"R-10: field '{field}' is outside repair '{repair}' scope ({', '.join(allowed) or 'none'})"]
    body = record[record["questionType"]]
    if field in ("question", "solution"):
        raw = body.get(field) or ""
        if not isinstance(find, str) or not isinstance(rep, str) or not find:
            return ["R-12: find/replace must be non-empty strings"]
        if len(find) > MAX_FIND:
            return [f"R-12: find longer than {MAX_FIND} chars (whole-field rewrite)"]
        n = raw.count(find)
        if n != 1:
            return [f"R-12: find occurs {n} times in the stored {field} (must be exactly once)"]
        if find == rep:
            return ["R-12: replace equals find"]
        return []
    if field == "answer":
        stored = body["answer"]
        if find != stored:
            return [f"R-13: find {find!r} does not equal the stored answer {stored!r}"]
        qtype = record["questionType"]
        if qtype == "scq" and not (isinstance(rep, str) and LETTER_RE.match(rep)):
            return [f"R-13: scq answer must be one letter A-D, got {rep!r}"]
        if qtype == "integerQuestion" and not (isinstance(rep, str) and INT_RE.match(rep)):
            return [f"R-13: integer answer must be numeric, got {rep!r}"]
        if qtype == "mcq" and not (isinstance(rep, list) and rep and rep == sorted(set(rep))
                                   and all(isinstance(x, str) and LETTER_RE.match(x) for x in rep)):
            return [f"R-13: mcq answer must be a sorted list of unique letters, got {rep!r}"]
        return []
    return [f"R-10: field '{field}' cannot be edited by the rules engine"]


def _non_letters(s: str) -> str:
    return re.sub(r"[A-Za-z]", "", s)


def guard(repair: str, edit: dict) -> list[str]:
    """Repair-specific guard for auto-eligibility. Unknown repairs → not auto-eligible."""
    find, rep = edit["find"], edit["replace"]
    if repair == "spelling":
        if _non_letters(find) != _non_letters(rep):
            return ["R-31: spelling edit changes non-letter characters"]
        fw, rw = re.findall(r"[A-Za-z]+", find), re.findall(r"[A-Za-z]+", rep)
        if len(fw) != len(rw) or any(levenshtein(a.lower(), b.lower()) > 3 for a, b in zip(fw, rw)):
            return ["R-31: spelling edit changes more than single words"]
        return []
    if repair == "exam_reference":
        if rep != "" or not EXAM_TAG.fullmatch(find):
            return ["R-33: exam_reference may only remove an exam tag"]
        return []
    if repair == "markup_leak":
        if not re.search(r"\\[A-Za-z]+", find):
            return ["R-34: find contains no markup leak"]
        if Counter(re.findall(r"\d", find)) != Counter(re.findall(r"\d", rep)):
            return ["R-34: markup_leak edit changes digits"]
        return []
    if repair == "answer_form":
        if not (rep.startswith(find) and len(rep) > len(find)) or \
                not re.fullmatch(r"\s*\(in [^()]{1,12}\)", rep[len(find):]):
            return ["R-35: answer_form must only append '(in <unit>)'"]
        return []
    return [f"R-30: '{repair}' is never auto-eligible in rules-only mode"]
