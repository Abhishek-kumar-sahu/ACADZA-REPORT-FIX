"""Is the stored answer key supported by the record's own worked solution?

Rules-only mode has no independent solver, so every signal here is derived from the stored record
and re-checked deterministically:
  solution_final  the solution's final value/text matches exactly one option (or the integer key,
                  after a unit conversion or multiplier the stem asks for)
  recomputed      the expression equated to that final value re-evaluates to it (mathcheck)
  steps           other solution steps re-evaluate consistently and none is inconsistent
  explicit_letter the solution names the option ("correct answer is (D)")
  equation        an integer target solved from the record's own equation (e.g. the stem template
                  '(n q)/(2 ε_0)' against the solution's final 'q/(2 ε_0)' → n = 1)
  text_support    (recall items) the key option's text leads the solution's first sentence
A student's claim is never a signal; it is compared with the result afterwards.
"""
import math
import re
from dataclasses import dataclass, field

from . import mathcheck as M
from .html_parse import parse_quantity
from .record import ParsedRecord

UNIT_SCALE = {  # (dimension, factor to SI)
    "mm": ("L", 1e-3), "cm": ("L", 1e-2), "m": ("L", 1.0), "km": ("L", 1e3),
    "ms": ("T", 1e-3), "s": ("T", 1.0), "sec": ("T", 1.0), "second": ("T", 1.0), "seconds": ("T", 1.0),
    "min": ("T", 60.0), "g": ("M", 1e-3), "kg": ("M", 1.0),
    "mv": ("V", 1e-3), "v": ("V", 1.0), "volt": ("V", 1.0), "kv": ("V", 1e3),
}
OPTION_TOL = 0.002   # a stated final value is rounded like the options; options can sit 1% apart
_IN_UNIT = re.compile(r"\(\s*in\s+([A-Za-zμ]+)\s*\)|\bin\s+(mm|cm|m|km|ms|s|sec|seconds|min|g|kg|v|volt)\b", re.I)
_MULTIPLIER = re.compile(r"\bvalue\s+of\s+(\d+(?:\.\d+)?)\s*([A-Za-z])\b", re.I)
_TARGET = re.compile(r"\bvalue\s+of\s*['‘’\"]\s*([A-Za-z])\s*['‘’\"]", re.I)
_EXPLICIT = [re.compile(p, re.I | re.M) for p in (
    r"correct\s+(?:answer|option|choice)\s+is\s*\(?\s*([a-d])\s*\)",
    r"^\s*(?:solution\s*:?\s*)?\(\s*([a-d])\s*\)\s",
    r"\banswer\s*(?:is|:)\s*\(\s*([a-d])\s*\)")]


@dataclass
class KeyCheck:
    status: str                       # supported | contradicted | ambiguous | unverifiable
    key: object
    derived: object = None            # letter (scq) or number (integer) the record supports
    derived_label: str | None = None  # e.g. "D (4800 N / m^2)"
    signals: list[str] = field(default_factory=list)       # signal kinds
    notes: list[str] = field(default_factory=list)         # human-readable facts
    final_differs_from_key: bool = False                   # integer: equation supports key, final doesn't
    scale_note: str | None = None
    student_fact: str | None = None   # plain-language fact for the reply (built from clean option text)


def option_value(text: str) -> float | None:
    m = re.match(r"\s*(-?\d+(?:\.\d+)?)\s*:\s*(\d+(?:\.\d+)?)\s*$", text)
    if m and float(m.group(2)):
        return float(m.group(1)) / float(m.group(2))
    return parse_quantity(text)[0]


def norm_text(s: str) -> str:
    s = s.lower()
    s = re.sub(r"(?<=[\d)])\s*(mm|cm|m|s|n|v|j|w|kg|ev)\b", "", s)
    return re.sub(r"\s+", "", s)


def match_options(p: ParsedRecord, value: float | None = None, text: str | None = None) -> list[str]:
    if value is not None:
        hits = [o.letter for o in p.options if not o.blank and (v := option_value(o.text)) is not None
                and math.isclose(v, value, rel_tol=OPTION_TOL, abs_tol=1e-12)]
        if hits:
            return hits
    if text:
        t = norm_text(text)
        return [o.letter for o in p.options if not o.blank and norm_text(o.text) == t]
    return []


def explicit_letter(solution_text: str) -> str | None:
    for pat in _EXPLICIT:
        if m := pat.search(solution_text):
            return m.group(1).upper()
    return None


def _first_sentence(text: str) -> str:
    return re.split(r"(?<=[.!?])\s|\n", text.strip(), maxsplit=1)[0].lower()


def recall_support(p: ParsedRecord) -> str | None:
    """Letter whose full option text appears in the solution's first sentence, if exactly one does."""
    first = re.sub(r"\s+", " ", _first_sentence(p.solution_text))
    named = [o.letter for o in p.options if not o.blank and len(o.text.strip()) >= 4
             and re.sub(r"\s+", " ", o.text.strip().lower().rstrip(".")) in first]
    return named[0] if len(named) == 1 else None


def stem_scale(p: ParsedRecord, final_unit: str | None) -> tuple[float, str | None, str | None]:
    """(factor, note, student-facing fact template) the stem asks to apply to the solution's final
    value. The template has {final} and {scaled} placeholders."""
    if m := _MULTIPLIER.search(p.stem_text):
        k, var = float(m.group(1)), m.group(2)
        return k, f"the question asks for {m.group(1)} {var}", \
            f"{var} = {{final}}, and the question asks for {m.group(1)}{var} = {{scaled}}"
    if final_unit and (m := _IN_UNIT.search(p.stem_text)):
        want = (m.group(1) or m.group(2)).lower()
        have = final_unit.strip().split()[0].lower() if final_unit.strip() else ""
        if want in UNIT_SCALE and have in UNIT_SCALE and UNIT_SCALE[want][1] != UNIT_SCALE[have][1] \
                and UNIT_SCALE[want][0] == UNIT_SCALE[have][0]:
            return UNIT_SCALE[have][1] / UNIT_SCALE[want][1], f"the question asks for the answer in {want}", \
                f"{{final}} = {{scaled}} {want}, and the question asks for the answer in {want}"
    return 1.0, None, None


def _steps(p: ParsedRecord, final_value: float | None):
    checks = M.step_checks(p.solution_text)
    bad = [c for c in checks if c.status == "inconsistent"]
    recomputed = final_value is not None and any(
        c.status == "consistent" and c.rhs_value is not None and
        math.isclose(c.rhs_value, final_value, rel_tol=M.REL_TOL) for c in checks)
    good = [c for c in checks if c.status == "consistent"]
    return recomputed, good, bad


def _fmt(v: float) -> str:
    return f"{v:g}"


def check_key(p: ParsedRecord) -> KeyCheck:
    if p.type == "mcq":
        return KeyCheck("unverifiable", p.answer, notes=["multiple-correct item: no deterministic way to "
                                                         "check which statements are true"])
    fin = p.solution_final or {}
    fval, fexpr = fin.get("value"), fin.get("expr")
    recomputed, good, bad = _steps(p, fval)
    computed = M.computed_values(p.solution_text)
    kc = KeyCheck("unverifiable", p.answer)
    if bad:
        kc.notes.append(f"{len(bad)} solution step(s) do not re-evaluate correctly")

    if p.type == "scq":
        exp = explicit_letter(p.solution_text)
        fin_letters = match_options(p, fval, fexpr)
        if len(fin_letters) == 1:
            kc.signals.append("solution_final")
            kc.notes.append(f"solution ends at {fexpr} = option ({fin_letters[0]})")
            if recomputed:
                kc.signals.append("recomputed")
                kc.notes.append(f"its arithmetic re-evaluates to {_fmt(fval)}")
        elif len(fin_letters) > 1:
            kc.notes.append(f"solution's final value matches several options ({', '.join(fin_letters)})")
        if exp:
            kc.signals.append("explicit_letter")
            kc.notes.append(f"solution states option ({exp})")
        if good and not bad and "recomputed" not in kc.signals and kc.signals:
            kc.signals.append("steps")
            kc.notes.append(f"{len(good)} solution step(s) re-evaluate consistently")
        derived = exp or (fin_letters[0] if len(fin_letters) == 1 else None)
        if exp and len(fin_letters) == 1 and exp != fin_letters[0]:
            kc.status = "ambiguous"
            kc.notes.append("the solution names one option but computes another")
            return kc
        if derived is None:
            lead = recall_support(p)
            if lead:
                kc.signals.append("text_support")
                kc.notes.append(f"the solution's first sentence names option ({lead})")
                derived = lead
        if derived is None:
            return kc
        o = p.option(derived)
        kc.derived, kc.derived_label = derived, f"{derived} ({o.text})" if o else derived
        if o:
            kc.student_fact = (f"the explanation in the solution points to ({derived}) {o.text}"
                               if kc.signals == ["text_support"] else f"working it through gives ({derived}) {o.text}")
        if derived == p.answer:
            kc.status = "supported"
            return kc
        key_opt = p.option(p.answer) if isinstance(p.answer, str) else None
        kv = option_value(key_opt.text) if key_opt and not key_opt.blank else None
        if kv is not None and any(math.isclose(kv, c, rel_tol=M.REL_TOL) for c in computed):
            kc.status = "ambiguous"
            kc.notes.append(f"the keyed value {key_opt.text} also appears in the solution")
            return kc
        kc.status = "contradicted"
        return kc

    # integerQuestion
    try:
        key = float(p.answer)
    except (TypeError, ValueError):
        return kc
    derived_eq = None
    target = _TARGET.search(p.stem_text)
    if target and fexpr:
        t = target.group(1)
        tmpl, final_expr = M.stem_template(p.stem_text, t), M.parse_expr(fexpr)
        if tmpl and final_expr:
            sols = M.integer_candidates(tmpl, final_expr, t, extra=[key])
            if len(sols) == 1:
                derived_eq = next(iter(sols))
                kc.notes.append(f"the question defines the answer as {tmpl.text.replace(' ', '')}; the solution "
                                f"ends at {final_expr.text.replace(' ', '')}, which holds only for {t} = {derived_eq}")
    if derived_eq is None and (st := M.final_statement(p.solution_text)):
        sym, stated, _ = st
        for L, R in M.solution_equations_with(p.solution_text, sym):
            sols = M.integer_candidates(L, R, sym, extra=[key, stated])
            if len(sols) == 1:
                derived_eq = next(iter(sols))
                kc.notes.append(f"the solution's equation {L.text.replace(' ', '')} = {R.text.replace(' ', '')} "
                                f"holds for {sym} = {derived_eq}")
                if not math.isclose(stated, derived_eq):
                    kc.notes.append(f"but the solution then states {sym} = {_fmt(stated)}")
                break
    scale, note, fact = stem_scale(p, fin.get("unit"))
    fs = fval * scale if fval is not None else None
    if fs is not None and note:
        kc.scale_note = f"{fexpr} → {_fmt(round(fs, 9))} ({note})"
        kc.student_fact = fact.format(final=fexpr, scaled=_fmt(round(fs, 9)))

    if derived_eq is not None:
        kc.signals.append("equation")
        if good and not bad:
            kc.signals.append("steps")
            kc.notes.append(f"{len(good)} solution step(s) re-evaluate consistently")
        if fs is not None and math.isclose(fs, derived_eq, rel_tol=M.REL_TOL):
            kc.signals.append("solution_final")
        kc.derived, kc.derived_label = derived_eq, _fmt(derived_eq)
        kc.student_fact = kc.student_fact or f"working it through gives {_fmt(derived_eq)}"
        if math.isclose(derived_eq, key):
            kc.status = "supported"
            kc.final_differs_from_key = fs is not None and not math.isclose(fs, key, rel_tol=M.REL_TOL)
        else:
            kc.status = "contradicted"
        return kc
    if fs is None:
        return kc
    kc.signals.append("solution_final")
    kc.notes.append(f"solution ends at {fexpr}" + (f"; {kc.scale_note}" if kc.scale_note else ""))
    if recomputed:
        kc.signals.append("recomputed")
        kc.notes.append(f"its arithmetic re-evaluates to {_fmt(fval)}")
    elif good and not bad:
        kc.signals.append("steps")
        kc.notes.append(f"{len(good)} solution step(s) re-evaluate consistently")
    kc.derived, kc.derived_label = round(fs, 9), _fmt(round(fs, 9))
    kc.student_fact = kc.student_fact or f"working it through gives {_fmt(round(fs, 9))}"
    if math.isclose(fs, key, rel_tol=M.REL_TOL):
        kc.status = "supported"
    elif any(math.isclose(c * scale, key, rel_tol=M.REL_TOL) for c in computed):
        kc.status = "ambiguous"
        kc.notes.append(f"the key {p.answer} also appears as a computed value in the solution")
    else:
        kc.status = "contradicted"
    return kc


def claim_matches(p: ParsedRecord, claim: dict | None) -> dict:
    """Map a student's claim onto the record: {'letter'|'value', 'label'} or {} if it can't be placed."""
    if not claim:
        return {}
    if claim.get("letter"):
        o = p.option(claim["letter"])
        return {"letter": claim["letter"], "label": f"({claim['letter']})" + (f" {o.text}" if o else "")}
    if p.type == "integerQuestion" and claim.get("value") is not None:
        return {"value": claim["value"], "label": _fmt(claim["value"])}
    letters = match_options(p, None, claim.get("text")) if claim.get("text") else []
    if not letters and claim.get("value") is not None:
        letters = match_options(p, claim["value"])
    if len(letters) == 1:
        o = p.option(letters[0])
        return {"letter": letters[0], "label": f"({letters[0]}) {o.text}"}
    raw = claim.get("text") or (_fmt(claim["value"]) if claim.get("value") is not None else None)
    return {"label": raw, "unplaced": True} if raw else {}


def student_correct(placed: dict, kc: KeyCheck) -> bool | None:
    """Is the student's claimed answer the one the record supports? None if unknown."""
    if not placed or kc.status not in ("supported", "contradicted") or kc.derived is None:
        return None
    if "letter" in placed:
        return placed["letter"] == kc.derived
    if "value" in placed and isinstance(kc.derived, (int, float)):
        # Exact: for integer answers the rounding IS the question (3112.99 is not 3113).
        return math.isclose(placed["value"], kc.derived, rel_tol=1e-9, abs_tol=1e-9)
    if placed.get("unplaced"):
        return False
    return None
