"""Rules-only triage engine (ADR-017). Deterministic: the same records and reports always produce the
same decisions. No LLM, no network, no randomness except seeded maths checks.

Per report:  history check → injection flag → complaint class → class rule → calibrated confidence
(CONFIDENCE table, RULES R-87) → route (RULES R-30/R-44/R-88) → truthful reply (R-70..R-73).
Nothing here keys on report or question IDs: every outcome comes from the record, its history, the
detectors and the stored solution. Decisions are proposals only: nothing is applied (Phase 5).
"""
import math
import re
from dataclasses import asdict, dataclass, field

from .. import taxonomy
from ..config import settings
from . import answers as A
from . import detectors as D
from .complaints import Complaint, classify
from .html_parse import parse_quantity
from .detectors import _LITERAL as _LITERAL_TEXT
from .mathcheck import equations, final_statement
from .record import ParsedRecord, history_after, parse_record
from .validators import guard, validate_edit

ENGINE = "rules-v1"
ENGINE_MODE = "rules_only"

# RULES R-87: rules-only confidence calibration. Confidence describes how strongly the record's own,
# deterministically re-checked evidence supports the verdict. It is never a model's self-report.
CONFIDENCE = {
    "structural": 0.95,            # a structural fact decides it (blank/missing/duplicate option, LaTeX
                                   # text, exam tag, figure reference without image, malformed key, later fix)
    "spelling_in_record": 0.90,    # the correct spelling appears elsewhere in the same record
    "unit_from_solution": 0.90,    # the solution states the unit of the keyed value unambiguously
    "classification": 0.85,       # display / app / language complaint with clean structural checks
    "unintelligible": 0.85,        # empty or keyboard-mash comment and clean checks
    "key_two_signals": 0.70,       # key check backed by >= 2 deterministic signals (rules-only ceiling)
    "key_one_signal": 0.65,        # key check backed by 1 signal, key supported
    "key_one_signal_against": 0.60,
    "comment_grounded": 0.70,      # correction grounded only in the student's comment
    "solution_values": 0.70,       # solution uses values the question never gives / solution anomalies
    "type_from_key": 0.70,         # mcq whose canonical key has a single letter
    "chapter_lexical": 0.65,       # none of the filed chapter's terms occur in the question or solution
    "recall_text": 0.60,           # recall item: key option leads the solution's first sentence
    "contradictory_record": 0.55,  # the solution contradicts itself about the statements the key depends on
    "syllabus": 0.50,              # complaint-only: needs faculty judgement (taxonomy: faculty confirm)
    "unverifiable": 0.50,          # no deterministic check possible
}
INJECTION_PENALTY = 0.20


@dataclass
class Decision:
    report_id: str
    question_id: str
    complaint_class: str
    verdict: str
    repair: str | None
    edit: dict | None
    route: str
    confidence: float
    confidence_basis: str
    evidence: list[str]                 # observed facts from the record and its checks
    inference: str                      # what the engine concludes from the evidence
    recommendation: str                 # what should happen next
    review_reason: str | None           # why a human must decide (faculty_review only)
    reply: str
    rule_ids: list[str]
    key_status: str
    key_signals: list[str]
    student_claim: str | None
    student_correct: bool | None
    injection_suspected: bool
    history_after_report: list[dict]
    internal_edit: object = None        # full proposal when it cannot be expressed in results.json
    suggestion: str | None = None       # faculty-only hint (never written by the system)
    engine: str = ENGINE
    engine_mode: str = ENGINE_MODE

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class _Draft:
    verdict: str
    conf_key: str
    evidence: list[str]
    inference: str
    repair: str | None = None
    edit: dict | None = None
    internal_edit: object = None
    suggestion: str | None = None
    forced_review: str | None = None      # reason a defect can never auto-apply here
    rule_ids: list[str] = field(default_factory=list)
    what: str = ""                        # plain-language description for the student reply
    tentative: bool = False               # a judgement call (syllabus/chapter): never call it confirmed
    key_fact: str = ""


# ------------------------------------------------------------------ edit builders (raw HTML)

def _unique_span(raw: str, needle: str, ctx: int = 12) -> str | None:
    """`needle`, widened with surrounding text (never across a tag) until it occurs once in raw."""
    if raw.count(needle) == 1:
        return needle
    i = raw.find(needle)
    while i != -1:
        for w in range(1, ctx + 1):
            lo, hi = max(0, i - w), min(len(raw), i + len(needle) + w)
            cand = raw[lo:hi]
            if "<" in cand or ">" in cand:
                break
            if raw.count(cand) == 1:
                return cand
        i = raw.find(needle, i + 1)
    return None


def _word_edit(raw: str, field_name: str, pairs: list[tuple[str, str]]) -> dict | None:
    """Single edit replacing wrong→right words. Covers all pairs with one contiguous tag-free span when
    possible (e.g. 'Epithellial tisue' → 'Epithelial tissue'), otherwise the first pair only."""
    spans = []
    for wrong, _ in pairs:
        m = re.search(rf"(?<![A-Za-z]){re.escape(wrong)}(?![A-Za-z])", raw)
        if not m:
            return None
        spans.append((m.start(), m.end()))
    lo, hi = min(s for s, _ in spans), max(e for _, e in spans)
    find = raw[lo:hi]
    if "<" in find or ">" in find:
        find = pairs[0][0]
        pairs = pairs[:1]
    rep = find
    for wrong, right in pairs:
        rep = re.sub(rf"(?<![A-Za-z]){re.escape(wrong)}(?![A-Za-z])", right, rep, count=1)
    find2 = _unique_span(raw, find)
    if find2 is None:
        return None
    return {"field": field_name, "find": find2, "replace": find2.replace(find, rep, 1)}


_FRAC = re.compile(r"\\frac\{(\w{1,6})\}\{(\w{1,6})\}")


def _markup_edit(raw: str, field_name: str) -> dict | None:
    m = _FRAC.search(raw)
    if not m or raw.count(m.group()) != 1:
        return None
    return {"field": field_name, "find": m.group(), "replace": f"{m.group(1)}/{m.group(2)}"}


def _append_edit(raw: str, addition: str) -> dict | None:
    """Append text after the last words of the question's final text node (answer_form)."""
    texts = [t for t in re.split(r"<[^>]*>", raw) if t.strip()]
    if not texts:
        return None
    words = texts[-1].rstrip().split()
    for n in range(3, min(12, len(words)) + 1):
        anchor = " ".join(words[-n:])
        if raw.count(anchor) == 1:
            return {"field": "question", "find": anchor, "replace": f"{anchor} {addition}"}
    return None


# ------------------------------------------------------------------ helpers

def _fmt_num(v: float) -> str:
    return str(int(v)) if float(v).is_integer() else f"{v:g}"


def _answer_label(p: ParsedRecord, ans) -> str:
    if isinstance(ans, str) and len(ans) == 1 and p.option(ans):
        return f"({ans}) {p.option(ans).text}"
    return str(ans)


def _relevant(findings, *kinds, field_name=None):
    return [f for f in findings if f.kind in kinds and (field_name is None or f.field == field_name)]


def _target_area(comment: str, p: ParsedRecord) -> tuple[str, str]:
    """Which part of the record a complaint points at: (field, text)."""
    c = comment.lower()
    if m := re.search(r"\boption\s*\(?([a-d])\)?", c):
        o = p.option(m.group(1).upper())
        if o:
            return "question", o.text
    if "option" in c:
        return "question", " ".join(o.text for o in p.options)
    if "solution" in c:
        return "solution", p.solution_text
    if "question" in c:
        return "question", p.stem_text + " " + " ".join(o.text for o in p.options)
    return "any", p.stem_text + " " + " ".join(o.text for o in p.options) + " " + p.solution_text


def _literal_text(solution_text: str, value: float) -> str:
    for m in _LITERAL_TEXT.finditer(solution_text):
        v = float(m.group(1)) * (10 ** int(m.group(2)) if m.group(2) else 1)
        if math.isclose(v, value, rel_tol=1e-9):
            text = re.sub(r"\s+", " ", m.group()).strip()
            return text[:-1].rstrip() if text.endswith(")") and text.count("(") < text.count(")") else text
    return _fmt_num(value)


def _unit_of_key(p: ParsedRecord) -> str | None:
    """Unit the solution attaches to the keyed (integer) value, if it is the same every time."""
    try:
        key = float(p.answer)
    except (TypeError, ValueError):
        return None
    units = set()
    for _, _, right in equations(p.solution_text):
        head = re.split(r"[,;()]", right.strip(), maxsplit=1)[0]
        v, u = parse_quantity(head)
        if v is not None and math.isclose(v, key, rel_tol=1e-9) and re.fullmatch(r"[A-Za-zμΩ]{1,4}", u.strip()):
            units.add(u.strip())
    return units.pop() if len(units) == 1 else None


def _stem_states_unit(p: ParsedRecord) -> str | None:
    s = p.stem_text
    m = (A._IN_UNIT.search(s) or re.search(r"\bin\s+(dioptres?|volts?|newtons?|joules?|seconds?|ev|cm|mm|m|kg|g)\b", s, re.I)
         or re.search(r"_\s*_.*?([A-Za-zμ]{1,3}\^?\d?)\s*\.?\s*$", s.split("\n")[0]))
    return m.group(0).strip() if m else None


# ------------------------------------------------------------------ class rules

def _key_dispute(p, findings, kc: A.KeyCheck, placed, correct) -> _Draft:
    contra = _relevant(findings, "contradictory_statements")
    if contra:
        return _Draft("defect", "contradictory_record", [contra[0].evidence, f"the stored key is ({p.answer})"],
                      "the record cannot establish any option: its own solution argues the statements both "
                      "ways, so no option is supported as written", repair="unsound",
                      forced_review="taxonomy: 'unsound' must be decided by faculty; the statements' physics "
                                    "cannot be checked without an independent solver",
                      rule_ids=["R-42", "R-22"], what="the worked solution contradicts itself, so the "
                      "answer key can't be confirmed")
    malformed = _relevant(findings, "answer_malformed")
    if malformed:
        return _format_defect(p, malformed[0])
    if kc.status == "contradicted":
        n = len(kc.signals)
        new = kc.derived if p.type == "scq" else _fmt_num(kc.derived)
        edit = {"field": "answer", "find": p.answer_raw, "replace": new}
        ev = [f"stored key {_answer_label(p, p.answer)}"] + kc.notes
        if placed.get("label") and correct is False:
            ev.append(f"student's value {placed['label']} is not supported either")
        return _Draft("defect", "key_two_signals" if n >= 2 else "key_one_signal_against", ev,
                      f"the stored key is wrong; the record supports {kc.derived_label}", repair="answer_key",
                      edit=edit, forced_review="answer-key changes need an independent solve that agrees "
                                               "(R-40a); rules-only mode has no solver",
                      rule_ids=["R-40", "R-20"],
                      what=f"the stored answer key doesn't match the worked solution, which gives {kc.derived_label}",
                      key_fact=f"the worked solution gives {kc.derived_label}")
    if kc.status == "supported":
        conf = "key_two_signals" if len(kc.signals) >= 2 else ("recall_text" if kc.signals == ["text_support"]
                                                              else "key_one_signal")
        ev = [f"stored key {_answer_label(p, p.answer)}"] + kc.notes
        if placed.get("label") and correct is False:
            ev.append(f"student's value {placed['label']} does not match")
        fact = kc.student_fact or ""
        return _Draft("no_error", conf, ev, "the stored key is consistent with the record's worked solution",
                      rule_ids=["R-22"], key_fact=fact)
    reason = {"ambiguous": "the solution's own values disagree about the answer",
              "unverifiable": "no deterministic check of this answer is possible from the record"}[kc.status]
    return _Draft("no_error", "unverifiable", [f"stored key {_answer_label(p, p.answer)}"] + kc.notes + [reason],
                  f"not confirmed: {reason}", forced_review=None, rule_ids=["R-21", "R-44"])


def _format_defect(p, finding) -> _Draft:
    ev = [finding.evidence]
    if p.type == "mcq" and len(p.answer) == 1:
        return _Draft("defect", "type_from_key", ev + [f"a multiple-correct item whose key has a single option ({p.answer[0]})"],
                      "stored as multiple-correct but keyed with one option: likely a single-correct (scq) item",
                      repair="type_mismatch", internal_edit=[
                          {"field": "questionType", "find": "mcq", "replace": "scq"},
                          {"field": "answer", "find": p.answer_raw, "replace": p.answer[0]}],
                      forced_review="the fix spans questionType and answer, which results.json cannot express "
                                    "as one edit (R-14); a type change also needs a solver count (R-41)",
                      rule_ids=["R-14", "R-41"], what="this question is set up as multiple-correct but has only "
                                                      "one correct option")
    return _Draft("defect", "structural", ev, "the stored key is malformed, so correct attempts are graded wrong",
                  repair="answer_key", edit={"field": "answer", "find": p.answer_raw, "replace": p.answer},
                  forced_review="format repairs still need an independent solve agreeing with the letters (R-40b)",
                  rule_ids=["R-40b"], what="the answer key was stored in a broken format, so your answer "
                                           "was marked wrong")


def _rule(cplx: Complaint, p: ParsedRecord, raw: dict, findings, kc, placed, correct) -> _Draft:
    cls = cplx.primary
    body = raw[raw["questionType"]]

    if cls in ("missing_option", "blank_option"):
        hits = _relevant(findings, "option_count", "blank_option")
        if not hits:
            return _Draft("display_issue", "classification", ["the stored question has 4 non-blank options"],
                          "the stored content is complete; the problem is how it is displayed",
                          what="", key_fact="")
        blank_keyed = [f for f in hits if f.kind == "blank_option" and f.data.get("letter") == p.answer]
        if blank_keyed:
            why = ("the blank option is the keyed answer; its value is not stated as a number in the solution, "
                   "so it cannot be restored from the record (R-38)")
            sugg = "check the solution: " + (p.solution_text.split("\n")[-1][:80] if p.solution_text else "")
        else:
            why = "a missing distractor is authored content; only faculty may write it (R-38)"
            sugg = None
        return _Draft("defect", "structural", [h.evidence for h in hits] + [f"stored key ({p.answer})"],
                      "an option is missing or blank in the stored question", repair="option_repair",
                      forced_review=why, suggestion=sugg, rule_ids=["R-38", "R-22"],
                      what="an option is missing from the question")

    if cls == "duplicate_options":
        hits = _relevant(findings, "duplicate_options")
        if hits:
            return _Draft("defect", "structural", [hits[0].evidence], "two options repeat",
                          repair="identical_options", forced_review="taxonomy: new distractors are authored "
                                                                    "content (identical_options, auto: false)",
                          rule_ids=["R-11"], what="two of the options are the same")
        return _Draft("no_error", "classification", ["all stored options are distinct"],
                      "the stored options are distinct", key_fact="the options in the question are all different")

    if cls == "figure_missing":
        hits = _relevant(findings, "figure_ref_no_image")
        if hits:
            return _Draft("defect", "structural", [hits[0].evidence], "the figure the question depends on is missing",
                          repair="diagram", forced_review="taxonomy: figures are authored by faculty "
                                                          "(diagram, auto: false); the engine never invents one",
                          rule_ids=["R-11"], what="the figure is missing from this question")
        return _Draft("display_issue", "classification", ["the question does not refer to a figure, or has images"],
                      "no missing figure in the stored record")

    if cls == "markup_visible":
        hits = _relevant(findings, "latex_leak", "alignment_leak")
        hits = [h for h in hits if h.field == "question"] or hits
        if hits:
            f = hits[0]
            edit = _markup_edit(body.get(f.field) or "", f.field) if f.kind == "latex_leak" else None
            return _Draft("defect", "structural", [f.evidence], "raw formatting code is visible to students",
                          repair="markup_leak", edit=edit,
                          forced_review=None if edit else "no deterministic conversion for this markup",
                          rule_ids=["R-34"], what="a formatting code was showing instead of the maths")
        return _Draft("display_issue", "classification", ["no raw markup in the stored question"],
                      "the stored content has no markup leak; likely a rendering problem")

    if cls == "exam_tag":
        hits = _relevant(findings, "exam_tag")
        if hits:
            tag = EXAM_TAG_IN_RAW(body["question"])
            edit = {"field": "question", "find": tag, "replace": ""} if tag else None
            return _Draft("defect", "structural", [hits[0].evidence], "an exam-source tag sits inside the question text",
                          repair="exam_reference", edit=edit, rule_ids=["R-33"],
                          what="the exam tag shouldn't be part of the question text")
        return _Draft("no_error", "classification", ["no exam tag in the stored question"], "no exam tag present")

    if cls == "spelling":
        return _spelling(cplx, p, raw)

    if cls == "unit_or_form":
        stated = _stem_states_unit(p)
        if stated:
            return _Draft("no_error", "classification", [f"the question already states the unit ('{stated}')"],
                          "the unit is stated", key_fact=f"the question asks for the answer '{stated}'")
        unit = _unit_of_key(p) if p.type == "integerQuestion" else None
        if unit:
            edit = _append_edit(body["question"], f"(in {unit})")
            return _Draft("defect", "unit_from_solution",
                          [f"the question never states the answer's unit; the solution gives the keyed value "
                           f"{p.answer} {unit}"], "the question should say which unit to answer in",
                          repair="answer_form", edit=edit, rule_ids=["R-35"],
                          what=f"the question didn't say the answer should be in {unit}")
        return _Draft("no_error", "unverifiable", ["no single unit can be read from the solution"],
                      "not confirmed: the unit could not be determined from the record")

    if cls == "missing_data":
        foreign = D.foreign_literals(p)
        if foreign:
            shown = ", ".join(_literal_text(p.solution_text, v) for v in foreign[:3])
            return _Draft("defect", "solution_values",
                          [f"the solution uses {shown}, which the question never gives"],
                          "a value needed to solve the question is missing from the stem", repair="stem_data",
                          forced_review="restoring a value needs wording and an independent check that the "
                                        "repaired stem reproduces the key (R-37)",
                          suggestion=f"the solution uses {shown}", rule_ids=["R-37"],
                          what="a value needed to solve it is missing from the question")
        return _Draft("no_error", "key_one_signal", ["every value the solution uses appears in the question"],
                      "no missing data found", key_fact="all the values needed are given in the question")

    if cls == "solution_mismatch":
        if kc.status == "contradicted":
            return _key_dispute(p, findings, kc, placed, correct)
        if kc.status == "supported" and kc.final_differs_from_key:
            st = final_statement(p.solution_text)
            edit = None
            if st:
                sym, stated, _ = st
                needle = f"{sym} = {_fmt_num(stated)}"
                if (body.get("solution") or "").count(needle) == 1:
                    edit = {"field": "solution", "find": needle, "replace": f"{sym} = {_fmt_num(kc.derived)}"}
            return _Draft("defect", "key_two_signals" if len(kc.signals) >= 2 else "solution_values",
                          [f"stored key {p.answer}"] + kc.notes,
                          "the key is right; the solution's last step is wrong", repair="solution_fix", edit=edit,
                          forced_review="solution changes need an independent solve agreeing with the key (R-39)",
                          rule_ids=["R-39"], what="the worked solution's last step has a mistake (the key is correct)")
        anomalies = _relevant(findings, "orphan_fragment", "latex_leak", "arithmetic_inconsistent", field_name="solution")
        if anomalies:
            ev = [a.evidence for a in anomalies]
            if kc.status == "supported":
                ev.append(f"its final value still matches the stored key ({p.answer})")
            return _Draft("defect", "solution_values", ev,
                          "the solution contains material that does not belong to this question",
                          repair="solution_fix", forced_review="rewriting a solution needs an independent "
                                                               "solve agreeing with the key (R-39)",
                          rule_ids=["R-39"], what="part of the worked solution belongs to a different question")
        if kc.status == "supported":
            return _Draft("no_error", "key_one_signal", [f"stored key {p.answer}"] + kc.notes,
                          "the solution and key agree", key_fact=kc.student_fact or "")
        return _Draft("no_error", "unverifiable", kc.notes or ["solution and key could not be compared"],
                      "not confirmed: the solution could not be checked deterministically")

    if cls == "type_issue":
        malformed = _relevant(findings, "answer_malformed")
        if p.type == "mcq" and isinstance(p.answer, list) and len(p.answer) == 1:
            return _format_defect(p, malformed[0] if malformed else D.Finding(
                "answer_shape", "answer_key", "answer", "verified", f"stored key {p.answer_raw!r}"))
        return _Draft("no_error", "unverifiable", [f"stored type {p.type}, key {p.answer!r}"],
                      "not confirmed: the type complaint needs a solver count (R-41)")

    if cls == "chapter":
        ov = D.chapter_overlap(p, raw, cplx.words)
        if not ov["chapter_terms_found"]:
            ev = [f"filed under '{ov['chapter']}'; none of its terms ({', '.join(ov['chapter_terms'])}) appear "
                  f"in the question or solution"]
            if ov["named_terms_found"]:
                ev.append("terms the student named do appear: " + ", ".join(ov["named_terms_found"]))
            return _Draft("defect", "chapter_lexical", ev, "the chapter metadata looks wrong",
                          repair="wrong_chapter", forced_review="taxonomy: chapter changes are faculty-only "
                                                                "(wrong_chapter, auto: false)",
                          rule_ids=["R-23"], tentative=True, what="which chapter this question is filed under")
        return _Draft("no_error", "unverifiable", [f"the filed chapter's terms appear: {', '.join(ov['chapter_terms_found'])}"],
                      "not confirmed: the filed chapter matches the question's wording")

    if cls == "syllabus":
        return _Draft("defect", "syllabus", ["the student reports the question is outside the syllabus; syllabus "
                                             "scope cannot be checked from the record"],
                      "possible syllabus issue (unverified)", repair="syllabus",
                      forced_review="taxonomy: faculty confirm syllabus scope; the question stays live meanwhile",
                      rule_ids=["R-23"], tentative=True, what="whether this question is within the syllabus")

    if cls == "language":
        lang = next((w for w in cplx.words if w in ("hindi", "marathi", "tamil", "telugu", "bengali", "gujarati")), None)
        return _Draft("language_mode", "classification", ["the student asks for the question in another language"],
                      "a language request, not a content error", key_fact=(lang or "another language").title())

    if cls in ("display", "app_behaviour"):
        malformed = _relevant(findings, "answer_malformed")
        if cls == "app_behaviour" and malformed:
            return _format_defect(p, malformed[0])
        broken = _relevant(findings, "option_count", "blank_option") + \
            [f for f in _relevant(findings, "latex_leak") if f.field == "question"]
        if broken:
            f = broken[0]
            return _Draft("defect", "structural", [f.evidence], "the stored content itself is broken",
                          repair=f.repair, forced_review="see the structural finding", rule_ids=["R-22"],
                          what="part of the question is genuinely broken")
        if cls == "display":
            return _Draft("display_issue", "classification",
                          [f"the stored question is complete ({len(p.options)} options, none blank, no raw markup)"
                           if p.options else "the stored question is complete (no raw markup)"],
                          "the stored content is fine; the problem is display or loading")
        return _Draft("app_issue", "classification", ["the stored question and key are consistent; the complaint "
                                                      "describes app behaviour"],
                      "platform behaviour, not this question")

    if cls == "unintelligible":
        severe = [f for f in findings if f.status == "verified" and f.severity == "high"]
        if severe:
            f = severe[0]
            return _Draft("defect", "structural", [f"comment unintelligible, but {f.evidence}"], "the record has a defect",
                          repair=f.repair, forced_review="defect found independently of the comment", rule_ids=["R-22"],
                          what="there is a problem with this question")
        return _Draft("not_actionable", "unintelligible", ["the comment has no readable content",
                                                           "structural checks found no defect"],
                      "nothing to act on")

    # answer_dispute, manipulation_attempt, other
    return _key_dispute(p, findings, kc, placed, correct)


def EXAM_TAG_IN_RAW(raw: str) -> str | None:
    m = D.EXAM_TAG.search(raw)
    return m.group() if m and raw.count(m.group()) == 1 else None


def _spelling(cplx: Complaint, p: ParsedRecord, raw: dict) -> _Draft:
    area_field, area_text = _target_area(cplx.text, p)
    area_words = set(D._words(area_text))
    pairs = []          # (wrong, right, grounding)
    for w, v, _ in D.near_miss_pairs(p):
        # The form inside the area the comment points at is the suspect; the other is the correction.
        if w in area_words and v not in area_words:
            pairs.append((w, v, "record"))
        elif v in area_words and w not in area_words:
            pairs.append((v, w, "record"))
    if not pairs:
        record_words = set(D._words(p.stem_text + " " + " ".join(o.text for o in p.options) + " " + p.solution_text))
        for named in cplx.words:
            if named in {x.lower() for x in record_words}:
                continue
            for tok in sorted(area_words):
                if len(tok) >= 4 and tok[0].lower() == named[0] and D.levenshtein(tok.lower(), named) == 1:
                    right = named if tok.islower() else named.capitalize() if tok[0].isupper() else named
                    pairs.append((tok, right, "comment"))
    if not pairs:
        return _Draft("no_error", "unverifiable", ["no misspelt word could be located in the part of the record "
                                                   "the comment points to"],
                      "not confirmed: the reported misspelling could not be located")
    grounding = "record" if all(g == "record" for *_, g in pairs) else "comment"
    pairs2 = [(w, r) for w, r, _ in pairs]
    fld = "question" if area_field in ("question", "any") and all(w in D._words(p.stem_text + " " + " ".join(o.text for o in p.options)) for w, _ in pairs2) else "solution"
    edit = _word_edit(raw[raw["questionType"]].get(fld) or "", fld, pairs2)
    ev = [f"'{w}' should read '{r}'" + (" (that spelling appears elsewhere in this record)" if g == "record"
                                         else " (correction suggested by the student's comment)")
          for w, r, g in pairs]
    return _Draft("defect", "spelling_in_record" if grounding == "record" else "comment_grounded", ev,
                  "a word is misspelt", repair="spelling", edit=edit,
                  forced_review=None if grounding == "record" else
                  "the correct spelling is grounded only in the student's comment, not in the record",
                  rule_ids=["R-31"], what="there's a spelling mistake")


# ------------------------------------------------------------------ history

def _already_fixed(cplx: Complaint, p: ParsedRecord, raw: dict, findings, hist: list[dict]) -> _Draft | None:
    if not hist:
        return None
    note = "; ".join(f"{h.get('type')} by {h.get('actor')} at {h.get('at')}: {h.get('note')}" for h in hist)
    record_text = (p.stem_text + " " + " ".join(o.text for o in p.options) + " " + p.solution_text).lower()
    if cplx.primary == "spelling":
        if cplx.quoted_words:
            gone = [w for w in cplx.quoted_words if w.lower() not in re.findall(r"[a-z]+", record_text)]
            if gone and len(gone) == len(cplx.quoted_words):
                return _Draft("already_fixed", "structural",
                              [f"fix recorded after this report ({note})", f"'{', '.join(gone)}' no longer appears in the record"],
                              "the reported problem was corrected after the report", rule_ids=["R-24"])
            return None
        if _spelling(cplx, p, raw).verdict != "defect":     # nothing misspelt left where the comment points
            return _Draft("already_fixed", "structural",
                          [f"fix recorded after this report ({note})", "no misspelling remains where the comment points"],
                          "the reported problem was corrected after the report", rule_ids=["R-24"])
        return None
    kinds = {"missing_option": ("option_count", "blank_option"), "blank_option": ("blank_option",),
             "duplicate_options": ("duplicate_options",), "markup_visible": ("latex_leak", "alignment_leak"),
             "exam_tag": ("exam_tag",), "figure_missing": ("figure_ref_no_image",)}.get(cplx.primary)
    if kinds and not _relevant(findings, *kinds):
        return _Draft("already_fixed", "structural",
                      [f"fix recorded after this report ({note})", "the reported problem is no longer in the record"],
                      "the reported problem was corrected after the report", rule_ids=["R-24"])
    return None


# ------------------------------------------------------------------ routing, confidence, reply

def _route(d: _Draft, conf: float, record: dict, injection_only: bool) -> tuple[str, str | None, list[str]]:
    rules = ["R-30"]
    if d.verdict != "defect":
        if conf < settings.no_change_min_confidence:
            return "faculty_review", f"confidence {conf:.2f} is below {settings.no_change_min_confidence:.2f}; " \
                                     "a non-defect is never closed on weak evidence (R-21, R-44)", rules + ["R-44"]
        return "no_change", None, rules
    rep = taxonomy.load()["repairs"][d.repair]
    if not rep["auto"]:
        return "faculty_review", d.forced_review or f"taxonomy: '{d.repair}' requires faculty (auto: false)", rules
    if d.forced_review:
        return "faculty_review", d.forced_review, rules
    if d.edit is None:
        return "faculty_review", "no safe surgical edit could be built from the record", rules
    bad = validate_edit(record, d.repair, d.edit) + guard(d.repair, d.edit)
    if bad:
        return "faculty_review", "; ".join(bad), rules + [b.split(":")[0] for b in bad]
    if injection_only:
        return "faculty_review", "the only report supporting this edit contains instruction-like text (R-52)", rules + ["R-52"]
    if conf < settings.auto_apply_min_confidence:
        return "faculty_review", f"confidence {conf:.2f} below the auto-apply threshold " \
                                 f"{settings.auto_apply_min_confidence:.2f} (R-44)", rules + ["R-44"]
    return "auto_apply", None, rules


FORBIDDEN_UNLESS_APPLIED = re.compile(r"\b(fixed|corrected|updated|changed)\b", re.I)


def _reply(d: _Draft, verdict: str, route: str, correct: bool | None) -> str:
    """Truthful, short, kind (RULES R-70..R-73). Never says 'fixed' unless the fix is live; never
    affirms an unverified claim; never echoes the comment."""
    if verdict == "defect" and d.tentative:
        s = f"Thanks for flagging this. A teacher will check {d.what} and follow up; the question stays available meanwhile."
    elif verdict == "defect" and route == "auto_apply":
        s = f"Thanks for flagging this - you're right: {d.what}. The correction is queued and will appear shortly."
    elif verdict == "defect":
        lead = "You're right - " if correct else "Thanks, you've spotted a real problem: "
        s = f"{lead}{d.what}. A teacher is checking it now and will confirm the fix."
    elif verdict == "no_error" and route == "no_change":
        fact = f": {d.key_fact.rstrip('.')}." if d.key_fact else "."
        s = f"Thanks for double-checking! We verified this question and the stored answer is correct{fact} " \
            "If your answer differs, recheck that step - it's an easy one to slip on."
    elif verdict == "no_error":
        s = "Thanks for flagging this. We couldn't confirm it automatically, so a teacher will review it and get back to you."
    elif verdict == "display_issue":
        s = "Thanks for telling us! The question itself is complete - this looks like a display or loading problem, " \
            "and we've passed it to the app team. Try reopening it or updating the app."
    elif verdict == "app_issue":
        s = "Sorry about that - this looks like an app problem, not an error in the question. We've passed it to the app team."
    elif verdict == "language_mode":
        s = f"Thanks for asking! This question is currently only available in English. We've noted your request for {d.key_fact or 'another language'}."
    elif verdict == "already_fixed":
        s = "Thanks for reporting this! It was already corrected after your report - reopen the question to see the current version."
    else:  # not_actionable
        s = "Thanks for reaching out! We couldn't tell what looked wrong - if you spot a problem, tell us which part and we'll check it."
    s = re.sub(r"\s+", " ", s).strip()
    return s if len(s) <= 320 else s[:317].rsplit(" ", 1)[0] + "..."


def reply_violations(reply: str, verdict: str, route: str) -> list[str]:
    """R-70/R-71/R-73 checks used by tests and the results validator."""
    out = []
    if not 1 <= len(re.findall(r"[.!?](?:\s|$)", reply)) <= 3:
        out.append("R-70: reply must be 1-3 sentences")
    if len(reply) > 320:
        out.append("R-70: reply longer than 320 characters")
    if re.search(r"\b(verdict|taxonomy|route|confidence|LLM|AI model)\b", reply, re.I):
        out.append("R-70: internal jargon in reply")
    if verdict not in ("already_fixed",) and route != "auto_apply" and FORBIDDEN_UNLESS_APPLIED.search(reply):
        out.append("R-71: reply claims a change that is not live")
    if re.search(r"\byou('| a)re (wrong|mistaken|careless)\b", reply, re.I):
        out.append("R-70: accusatory phrasing")
    return out


def decide(report: dict, raw: dict, p: ParsedRecord | None = None, findings=None) -> Decision:
    p = p or parse_record(raw)
    findings = D.scan(p, raw) if findings is None else findings
    cplx = classify(report["comment"])
    from ..importer import parse_ts
    hist = history_after(raw, parse_ts(report["reportedAt"]))
    kc = A.check_key(p)
    placed = A.claim_matches(p, cplx.claim)
    correct = A.student_correct(placed, kc)

    d = _already_fixed(cplx, p, raw, findings, hist) or _rule(cplx, p, raw, findings, kc, placed, correct)

    injection_only = cplx.injection
    conf = CONFIDENCE[d.conf_key]
    basis = f"{ENGINE_MODE}: {d.conf_key} = {conf:.2f} (RULES R-87)"
    if cplx.injection and d.edit and d.edit.get("field") == "answer" and placed.get("letter") == d.edit.get("replace"):
        conf = max(0.0, conf - INJECTION_PENALTY)               # R-43: injected demand matches proposal
        basis += f"; -{INJECTION_PENALTY:.2f} injected demand matches the proposal"
        d.edit, d.forced_review = None, "the proposed change matches an injected instruction (R-52)"
    conf = round(conf, 2)
    route, review, route_rules = _route(d, conf, raw, injection_only and d.edit is not None)

    evidence = list(d.evidence)
    if hist and d.verdict != "already_fixed":
        evidence.append("errorHistory has a fix dated after this report, but the reported problem is still present")
    if cplx.injection:
        evidence.append("comment contains instruction-like text; treated as data, not followed")
    if placed.get("label") and correct is True:
        evidence.append(f"student's answer {placed['label']} matches what the record supports")

    if route == "auto_apply":
        rec = "eligible for automatic application of the edit (executed in Phase 5; nothing applied yet)"
    elif route == "faculty_review":
        rec = "faculty to review" + (" the proposed edit" if d.edit else "") + (f"; hint: {d.suggestion}" if d.suggestion else "")
    else:
        rec = "close with no change and send the reply"

    return Decision(
        report_id=report["reportId"], question_id=report["questionId"], complaint_class=cplx.primary,
        verdict=d.verdict, repair=d.repair, edit=d.edit if d.repair else None, route=route, confidence=conf,
        confidence_basis=basis, evidence=evidence, inference=d.inference, recommendation=rec,
        review_reason=review, reply=_reply(d, d.verdict, route, correct),
        rule_ids=sorted(set(d.rule_ids + route_rules)), key_status=kc.status, key_signals=list(kc.signals),
        student_claim=placed.get("label"), student_correct=correct, injection_suspected=cplx.injection,
        history_after_report=hist, internal_edit=d.internal_edit or d.edit, suggestion=d.suggestion)


def run(questions: list[dict], reports: list[dict]) -> list[Decision]:
    """Decide every report exactly once, in reportId order."""
    qmap = {q["_id"]: q for q in questions}
    parsed = {q["_id"]: parse_record(q) for q in questions}
    findings = {qid: D.scan(parsed[qid], qmap[qid]) for qid in qmap}
    return [decide(r, qmap[r["questionId"]], parsed[r["questionId"]], findings[r["questionId"]])
            for r in sorted(reports, key=lambda r: r["reportId"])]


def covered_defects(decisions: list[Decision]) -> set[tuple[str, str]]:
    return {(d.question_id, d.repair) for d in decisions if d.verdict == "defect" and d.repair}


def bonus_findings(questions: list[dict], covered: set[tuple[str, str]]) -> list[dict]:
    """Question-level findings on every question that no report's defect verdict already covers.
    `covered` = {(question_id, repair)} from the report decisions."""
    solution_defects = {qid for qid, rep in covered if rep == "solution_fix"}
    out = []
    for q in sorted(questions, key=lambda q: q["_id"]):
        p = parse_record(q)
        for f in D.scan(p, q):
            if (q["_id"], f.repair) in covered:
                continue
            if f.field == "solution" and q["_id"] in solution_defects:
                continue                      # already part of a reported solution problem
            if f.kind == "answer_malformed" and (q["_id"], "type_mismatch") in covered:
                continue
            out.append({
                "questionId": q["_id"], "subject": q["subject"], "chapter": q["chapter"],
                "field": f.field, "category": f.repair, "check": f.kind, "status": f.status,
                "severity": f.severity, "evidence": f.evidence,
                "recommended_action": _ACTION[f.repair],
            })
    for i, f in enumerate(out, 1):
        f["findingId"] = f"B{i:02d}"
    return out


_ACTION = {
    "markup_leak": "Replace the visible markup with proper MathML/text (mechanical; faculty to confirm).",
    "notation": "Correct the unit/symbol so the solution and the options agree.",
    "spelling": "Confirm which spelling is correct and fix the misspelt form.",
    "solution_fix": "Review the solution and remove or correct the faulty part.",
    "unsound": "Faculty to check whether any option is correct as written.",
    "answer_key": "Faculty to verify the key independently.",
    "option_repair": "Faculty to restore the missing/blank option.",
    "identical_options": "Faculty to write a distinct distractor.",
    "diagram": "Faculty to attach the missing figure.",
    "exam_reference": "Remove the exam tag from the question text.",
    "solution_missing": "Write a solution ending in the keyed answer.",
    "answer_form": "State the answer's unit in the question.",
    "stem_data": "Add the missing value to the question.",
    "type_mismatch": "Faculty to correct the question type and key.",
    "wrong_chapter": "Faculty to re-file under the correct chapter.",
    "syllabus": "Faculty to confirm syllabus scope.",
    "noise": "Remove the stray text.",
    "wrong_question": "Faculty to pair the question with its own solution.",
}
