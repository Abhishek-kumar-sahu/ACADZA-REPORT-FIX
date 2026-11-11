"""Student comment → complaint class, claimed answer, injection flag.

The comment is untrusted evidence (RULES R-50). Nothing here acts on what the comment asks for:
it is pattern-matched into a closed set of complaint classes and an optional claimed answer, which
the engine then checks against the record. Patterns cover English and common Hinglish phrasing.
"""
import re
from dataclasses import dataclass, field

INJECTION = [
    r"ignore (all |any )?(the )?(previous|prior|above) (instructions|rules|prompts?)",
    r"\byou are (now )?(an?|the) \w+", r"\bsystem prompt\b", r"\badmin(istrator)? (bot|mode|access)\b",
    r"\bmark (this|it|the report) as\b", r"\bchange the (answer|key) to\b", r"\b(act|pretend) as\b",
    r"\bdisregard\b", r"</?(system|assistant|instructions?)>", r"\bjailbreak\b",
]
_INJ = [re.compile(p, re.I) for p in INJECTION]
_KEY_ROWS = ("qwertyuiop", "asdfghjkl", "zxcvbnm")

# (class, pattern) in priority order: the first match is the primary class.
CLASSES = [
    ("language", r"\b(hindi|english|marathi|tamil|telugu|bengali|gujarati|language|bhasha)\b"),
    ("figure_missing", r"\b(figure|diagram|image|graph|picture)\b"),
    ("missing_option", r"\boption\s*\(?[a-d]\)?\s*(is\s+)?(missing|not\s+(given|there|shown))|"
                       r"\bonly\s+\d\s+options?\b|\bmissing\s+option|\boptions?\s+missing"),
    ("blank_option", r"\b(blank|empty|khali)\b"),
    ("duplicate_options", r"\b(two|2|both)\s+options?\s+(are\s+)?(same|identical|equal|repeat)|"
                          r"\bsame\s+options?\b|\boptions?\s+(are\s+)?(same|repeated|identical)\b"),
    ("spelling", r"\b(spelling|spelt|typo|mis-?spel\w*)\b"),
    ("markup_visible", r"\\[a-z]+|\bcode\b.*\bshowing\b|\b(latex|html|tags?)\b"),
    ("exam_tag", r"\b(neet|jee|aipmt|aiims|mht[- ]?cet|bitsat)\s*\d{4}\b"),
    ("unit_or_form", r"\bunits?\b.*\b(not|nahi|missing|mention)|\b(no|without)\s+units?\b"),
    ("missing_data", r"\b(not\s+given|nahi\s+d(i|iya|ee)|missing|not\s+mentioned|insufficient)\b"),
    ("solution_mismatch", r"\bsolution\b"),
    ("type_issue", r"\b(multiple|single|multi)[- ]correct\b|\b(mcq|scq)\b"),
    ("chapter", r"\bchapter\b|\bwhy\s+is\s+it\s+in\b|\bwrong\s+(topic|unit|subject)\b"),
    ("syllabus", r"\bsyllabus\b"),
    ("display", r"\b(cut|screen|load(ing|s)?|slow|forever|blurr?y|zoom|not\s+(visible|showing|displaying|loading))\b"),
    ("app_behaviour", r"\b(clicked|tapped|saved|submitted|recorded|crash\w*|keyboard|lag\w*)\b|"
                      r"\bmarked\b.*\b(still|but)\b|\bgot\s+(it\s+)?(wrong|negative)\b"),
    ("answer_dispute", r"\b(answer|ans|key|galat|wrong|should\s+be|incorrect|solved|i\s+got|hona|aana)\b|"
                       r"\b(is|are)\s+(true|false|correct)\b|\bassertion\b|\d"),
]
_CLS = [(c, re.compile(p, re.I)) for c, p in CLASSES]


@dataclass
class Complaint:
    text: str
    classes: list[str]
    primary: str
    injection: bool
    injection_hits: list[str] = field(default_factory=list)
    claim: dict | None = None         # {"letter"?, "value"?, "text"?, "raw"}
    quoted_words: list[str] = field(default_factory=list)
    words: list[str] = field(default_factory=list)


def _gibberish(text: str) -> bool:
    t = text.strip().lower()
    if not t or not re.search(r"[a-z0-9]", t):
        return True
    letters = re.sub(r"[^a-z]", "", t)
    if " " not in t and len(letters) >= 4 and any(all(ch in row for ch in letters) for row in _KEY_ROWS):
        return True
    return False


_CHANGE_TO = re.compile(r"\bchange\s+the\s+(?:answer|key)\s+to\s+\(?([A-D])\)?\b", re.I)
_RATIO = re.compile(r"(\d+(?:\.\d+)?)\s*:\s*(\d+(?:\.\d+)?)")
_ROOT = re.compile(r"(\d+(?:\.\d+)?)?\s*(?:root|√|sqrt)\s*\(?\s*(\d+(?:\.\d+)?)\s*\)?", re.I)
_TAN_INV = re.compile(r"\btan\s*(?:inverse|inv|\^-1|⁻¹)\s*\(?\s*(\d+(?:\.\d+)?)\s*\)?", re.I)
_NUM = re.compile(r"(?<![\w.])(-?\d+(?:\.\d+)?)(?![\w.]*\d)")
_VAR_EQ = re.compile(r"\b[a-zA-Z]\s*=\s*(-?\d+(?:\.\d+)?)")


_CLAIM_PHRASE = re.compile(r"\b(?:should\s+be|must\s+be|i\s+got|answer\s+is|ans\s+is|answer|ans)\b\s*[:=]?\s*"
                           r"(?P<rest>.{1,40})", re.I)
_FIRST_PERSON = re.compile(r"\b(?:should\s+be|must\s+be|i\s+got)\b\s*[:=]?\s*(?P<rest>.{1,40})", re.I)
_ONLY_X = re.compile(r"\bonly\s+\(?([A-D])\)?\s+is\s+correct\b", re.I)
_EQ_NUM = re.compile(r"=\s*(-?\d+(?:\.\d+)?)")


def _value_in(s: str, allow_bare_number: bool = True) -> dict | None:
    if m := re.match(r"\s*\(?([A-D])\)?(?![\w])", s):
        return {"letter": m.group(1).upper()}
    if m := _TAN_INV.search(s):
        return {"text": f"tan^-1({m.group(1)})"}
    if m := _ROOT.search(s):
        coef = m.group(1) or "1"
        return {"text": f"{coef}sqrt({m.group(2)})", "value": float(coef) * float(m.group(2)) ** 0.5}
    if m := _RATIO.search(s):
        return {"text": f"{m.group(1)}:{m.group(2)}", "value": float(m.group(1)) / float(m.group(2))}
    if m := _VAR_EQ.search(s):
        return {"value": float(m.group(1))}
    if allow_bare_number and (m := _NUM.search(s)):
        return {"value": float(m.group(1))}
    return None


def extract_claim(text: str, allow_bare_number: bool = True, first_person_only: bool = False) -> dict | None:
    """The answer the student says is right, if stated. A claim is a lead to check, never a signal.
    Order: an injected 'change the answer to X' > explicit claim phrases ('should be', 'I got',
    'answer is', 'hona chahiye') > 'only X is correct' > '= value' > a bare value.
    first_person_only: 'answer is 20' may just quote the stored key, so only 'should be / must be /
    I got' count (used for solution-mismatch and type complaints)."""
    if m := _CHANGE_TO.search(text):
        return {"letter": m.group(1).upper(), "raw": m.group(0)}
    for m in (_FIRST_PERSON if first_person_only else _CLAIM_PHRASE).finditer(text):
        v = _value_in(m.group("rest"))
        if v:
            return {**v, "raw": m.group(0).strip()}
    if m := _ONLY_X.search(text):
        return {"letter": m.group(1).upper(), "raw": m.group(0)}
    if first_person_only:
        return None
    if m := _EQ_NUM.search(text):
        return {"value": float(m.group(1)), "raw": m.group(0)}
    v = _value_in(text, allow_bare_number)
    return {**v, "raw": text[:40]} if v else None


def classify(text: str) -> Complaint:
    hits = [p.pattern for p in _INJ if p.search(text)]
    classes = [c for c, p in _CLS if p.search(text)]
    if hits:
        classes = ["manipulation_attempt"] + classes
    if _gibberish(text):
        classes = ["unintelligible"]
    primary = classes[0] if classes else "other"
    claim = None
    if primary in ("answer_dispute", "manipulation_attempt"):
        claim = extract_claim(text)
    elif primary in ("solution_mismatch", "type_issue"):
        # These comments often *quote* values from the record ("solution says 40, answer is 20");
        # only a first-person claim counts.
        claim = extract_claim(text, first_person_only=True)
    quoted = re.findall(r"['‘’\"“”]([A-Za-z]{3,})['‘’\"“”]", text)
    words = [w.lower() for w in re.findall(r"[A-Za-z]{4,}", text)]
    return Complaint(text, classes, primary, bool(hits), hits, claim, quoted, words)
