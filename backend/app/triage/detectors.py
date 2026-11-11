"""Deterministic detectors over one parsed question (RULES §5). Pure functions: no I/O, no LLM.

Every Finding carries quoted evidence from the record. `status` is "verified" when the check is a
structural fact (an option is blank, a literal `\\frac` is present) and "suspected" when it is a
heuristic that needs a human (near-miss spellings, unit mismatches, contradictory statements).
"""
import re
from collections import Counter
from dataclasses import dataclass, field

from .html_parse import latex_commands, parse_quantity
from .mathcheck import step_checks
from .record import ParsedRecord

SEVERITY = {
    **dict.fromkeys(("answer_key", "option_repair", "identical_options", "diagram", "stem_data", "unsound",
                     "wrong_question", "type_mismatch"), "high"),
    **dict.fromkeys(("solution_fix", "solution_missing", "answer_form"), "medium"),
    **dict.fromkeys(("spelling", "notation", "exam_reference", "noise", "wrong_chapter", "syllabus"), "low"),
}
EXAM_TAG = re.compile(r"\(\s*(?:JEE|NEET|AIPMT|AIIMS|MHT[- ]?CET|BITSAT|KCET|WBJEE)[^)]{0,30}\d{4}\s*\)\s?", re.I)
FIGURE_REF = re.compile(r"\b(as shown|shown in (the )?(figure|diagram)|(given|following|adjacent) (figure|diagram)|"
                        r"in the figure|see (the )?(figure|diagram))\b", re.I)
AMP_LEAK = re.compile(r"<m[io]>\s*&(?:amp;)?\s*</m[io]>")
UNIT_SYNONYMS = {"volt": "v", "volts": "v", "ohm": "ω", "ohms": "ω", "sec": "s", "second": "s", "seconds": "s",
                 "min": "min", "minute": "min", "minutes": "min", "days": "day", "day": "day"}
STOP = set("""a an the of in on at to for from by with and or but is are was were be been being this that these those
it its as into than then so such which what who whom whose when where why how all any both each few more most other
some no nor not only own same very can will just should now there their they them he she his her you your our we
also because if while during before after above below between through about against under over again further once
here off out up down each per given find value will would could has have had do does did""".split())


@dataclass
class Finding:
    kind: str
    repair: str
    field: str                 # question | solution | answer | metadata
    status: str                # verified | suspected
    evidence: str
    data: dict = field(default_factory=dict)

    @property
    def severity(self) -> str:
        if self.repair == "markup_leak":
            return "medium" if self.field == "question" else "low"
        return SEVERITY.get(self.repair, "low")


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip().lower())


def _words(s: str) -> list[str]:
    return re.findall(r"[A-Za-z][A-Za-z'’]*[A-Za-z]|[A-Za-z]", s)   # hyphens split words


def levenshtein(a: str, b: str) -> int:
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _inflection(a: str, b: str) -> bool:
    """Plural/verb forms are not misspellings: herb/herbs, occur/occurs, plant/plants."""
    a, b = a.lower(), b.lower()
    short, long_ = sorted((a, b), key=len)
    return long_ in (short + "s", short + "es", short + "d", short + "ed") or \
        (short.endswith("y") and long_ == short[:-1] + "ies")


def single_indel(a: str, b: str) -> bool:
    """True if one word is the other with exactly one letter inserted (tisue/tissue, Canolla/Canola).
    Substitutions are excluded on purpose: state/snake, adaxial/abaxial, given/gives are real words."""
    a, b = a.lower(), b.lower()
    if abs(len(a) - len(b)) != 1:
        return False
    short, long_ = sorted((a, b), key=len)
    return any(long_[:i] + long_[i + 1:] == short for i in range(len(long_)))


def near_miss_pairs(p: ParsedRecord) -> list[tuple[str, str, str]]:
    """(token, in_record_neighbour, field) where both spellings occur in the same record and differ by
    a single inserted/dropped letter. Direction is not assumed: callers decide which form is wrong."""
    fields = {"question": p.stem_text + " " + " ".join(o.text for o in p.options), "solution": p.solution_text}
    tokens = {f: Counter(w for w in _words(t) if len(w) >= 5) for f, t in fields.items()}
    vocab = tokens["question"] + tokens["solution"]
    out, seen = [], set()
    for f, cnt in tokens.items():
        for w in cnt:
            for v in vocab:
                if v == w or v.lower() == w.lower() or w[0].lower() != v[0].lower() or _inflection(w, v):
                    continue
                if single_indel(w, v):
                    key = tuple(sorted((w.lower(), v.lower())))
                    if key not in seen:
                        seen.add(key)
                        out.append((w, v, f))
    return out


_TRUTH = re.compile(r"(?P<label>assertion|reason|statement)\s*[-–]?\s*(?:\(\s*(?P<l1>[a-z]{1,3})\s*\)|"
                    r"(?P<l2>i{1,3}|[12]))?\s*(?:is|are)\s+(?P<neg>not\s+)?(?P<val>true|false|correct|incorrect)\b",
                    re.I)


def truth_claims(text: str) -> dict[str, set[bool]]:
    """Truth values the solution asserts for each labelled statement (Assertion, Reason, Statement-I…)."""
    claims: dict[str, set[bool]] = {}
    for m in _TRUTH.finditer(text.replace("\n", " ")):
        sub = (m.group("l1") or m.group("l2") or "").upper()
        label = m.group("label").capitalize() + (f" ({sub})" if sub else "")
        val = m.group("val").lower() in ("true", "correct")
        claims.setdefault(label, set()).add(val != bool(m.group("neg")))
    return claims


def _unit_norm(u: str) -> str:
    u = u.lower().replace(" ", "").replace("^", "").replace("∘", "o").replace("°", "o")
    return UNIT_SYNONYMS.get(u, u)


def scan(p: ParsedRecord, raw: dict) -> list[Finding]:
    """All question-level findings for one record. `raw` is the stored record (for raw-HTML checks)."""
    body = raw[raw["questionType"]]
    out: list[Finding] = []
    opts = p.options

    if p.type != "integerQuestion" and len(opts) != 4:
        letters = "".join(o.letter for o in opts)
        out.append(Finding("option_count", "option_repair", "question", "verified",
                           f"only {len(opts)} options stored ({', '.join(letters)}); an MCQ needs 4", {"count": len(opts)}))
    for o in opts:
        if o.blank:
            out.append(Finding("blank_option", "option_repair", "question", "verified",
                               f"option ({o.letter}) is blank in the stored question", {"letter": o.letter}))
    texts = Counter(_norm(o.text) for o in opts if not o.blank)
    for t, n in texts.items():
        if n > 1:
            dup = [o for o in opts if _norm(o.text) == t]
            out.append(Finding("duplicate_options", "identical_options", "question", "verified",
                               f"options {' and '.join(o.letter for o in dup)} are identical ('{dup[0].text}')",
                               {"letters": [o.letter for o in dup]}))
    malformed = [i for i in p.answer_issues if i in ("empty_element", "joined_string", "not_a_letter",
                                                     "duplicate_letter", "not_a_list", "not_numeric")]
    if malformed:
        out.append(Finding("answer_malformed", "answer_key", "answer", "verified",
                           f"stored answer {p.answer_raw!r} is malformed ({', '.join(malformed)}); "
                           f"canonical form {p.answer!r}", {"issues": malformed}))

    q_text = p.stem_text + " " + " ".join(o.text for o in opts)
    for f, text in (("question", q_text), ("solution", p.solution_text)):
        cmds = latex_commands(text)
        if cmds:
            out.append(Finding("latex_leak", "markup_leak", f, "verified",
                               f"raw LaTeX visible in {f}: {', '.join(sorted(set(cmds)))}", {"commands": cmds}))
    for f in ("question", "solution"):
        n = len(AMP_LEAK.findall(body.get(f) or ""))
        if n:
            out.append(Finding("alignment_leak", "markup_leak", f, "verified",
                               f"LaTeX alignment '&' rendered as a symbol in {f} ({n}x)", {"count": n}))
    if m := EXAM_TAG.search(p.stem_text):
        out.append(Finding("exam_tag", "exam_reference", "question", "verified",
                           f"exam tag '{m.group().strip()}' inside the question text", {"tag": m.group()}))
    if FIGURE_REF.search(p.stem_text) and not body.get("quesImages"):
        out.append(Finding("figure_ref_no_image", "diagram", "question", "verified",
                           "question refers to a figure ('" + FIGURE_REF.search(p.stem_text).group() +
                           "') but the record has no question images"))
    if not p.solution_text.strip():
        out.append(Finding("solution_empty", "solution_missing", "solution", "verified", "solution is empty"))
    elif re.match(r"^\s*[=≈]", p.solution_text):
        out.append(Finding("orphan_fragment", "solution_fix", "solution", "suspected",
                           "solution starts mid-derivation: '" + p.solution_text.split("\n")[0][:60] + "'"))

    for c in step_checks(p.solution_text):
        if c.status == "inconsistent":
            out.append(Finding("arithmetic_inconsistent", "solution_fix", "solution", "verified",
                               f"solution step '{c.lhs} = {c.rhs}' does not hold ({c.lhs_value:g} vs {c.rhs_value:g})"))

    contradicted = {k: v for k, v in truth_claims(p.solution_text).items() if len(v) > 1}
    if contradicted:
        out.append(Finding("contradictory_statements", "unsound", "solution", "suspected",
                           "solution asserts both true and false for: " + ", ".join(sorted(contradicted)),
                           {"labels": sorted(contradicted)}))

    for w, v, f in near_miss_pairs(p):
        out.append(Finding("near_miss_spelling", "spelling", f, "suspected",
                           f"'{w}' and '{v}' both appear in this record (one is likely misspelt)",
                           {"tokens": [w, v]}))

    # Unit text of the solution's final value vs the option it matches (value equal, unit differs).
    fin = p.solution_final
    if fin and fin.get("value") is not None and fin.get("unit") and len(fin["unit"]) <= 12:
        for o in opts:
            ov, ou = parse_quantity(o.text)
            if ov is not None and ou and abs(ov - fin["value"]) <= 1e-9 + 0.01 * abs(ov) \
                    and re.search(r"[A-Za-z]", fin["unit"]) and not ou.startswith(":") \
                    and _unit_norm(ou) != _unit_norm(fin["unit"]):
                out.append(Finding("unit_text_mismatch", "notation", "solution", "suspected",
                                   f"solution ends '{fin['expr']}' but option ({o.letter}) reads '{o.text}'",
                                   {"letter": o.letter}))
                break
    return out


def chapter_overlap(p: ParsedRecord, raw: dict, extra_terms: list[str] = ()) -> dict:
    """Lexical check for chapter complaints: do the filed chapter's own terms appear anywhere in the
    question or solution? (5-letter prefix match; stop-words ignored.) Returns the terms found/missing
    for the filed chapter and for any topic words the student named."""
    text = (p.stem_text + " " + " ".join(o.text for o in p.options) + " " + p.solution_text).lower()
    prefixes = {w.lower()[:5] for w in _words(text) if len(w) >= 4}

    def present(term: str) -> bool:
        return term.lower()[:5] in prefixes

    terms = [w for w in _words(raw.get("chapter") or "") if len(w) >= 4 and w.lower() not in STOP]
    named = [w for w in extra_terms if len(w) >= 5 and w.lower() not in STOP]
    return {"chapter": raw.get("chapter"), "chapter_terms": terms,
            "chapter_terms_found": [t for t in terms if present(t)],
            "named_terms_found": [t for t in named if present(t)]}


_LITERAL = re.compile(r"(?<![\w.^])(\d+(?:\.\d+)?)(?:\s*×\s*10\s*\^\s*\(?\s*(-?\d+)\s*\)?)?")


def literals(text: str, with_form: bool = False):
    """Numeric literals; 'a × 10^k' is one literal. with_form → {value: written_in_scientific_form}."""
    out: dict[float, bool] = {}
    for m in _LITERAL.finditer(text):
        v = round(float(m.group(1)) * (10 ** int(m.group(2)) if m.group(2) else 1), 12)
        out[v] = out.get(v, False) or bool(m.group(2))
    return out if with_form else set(out)


def foreign_literals(p: ParsedRecord) -> list[float]:
    """Numbers the solution uses that the question never gives (excluding small constants, the final
    answer and values the solution itself computes). Evidence for 'data missing' complaints only:
    on its own this is too noisy (solutions legitimately introduce constants)."""
    from .mathcheck import computed_values
    given = literals(p.stem_text + " " + " ".join(o.text for o in p.options))
    computed = {round(v, 12) for v in computed_values(p.solution_text)}
    used = literals(p.solution_text, with_form=True)
    trivial = {0.0, 1.0, 2.0, 3.0, 4.0} | {10.0 ** k for k in range(-6, 7)}
    return sorted(v for v, sci in used.items() if v not in given and v not in computed
                  and (sci or v not in trivial)
                  and not any(abs(v - g * 10 ** k) <= 1e-9 * max(1.0, abs(v)) for g in given
                              for k in (-3, -2, -1, 1, 2, 3)))
