"""Deterministic maths checks over the structural linear text produced by html_parse.

- `evaluate`: safe AST evaluator (numbers, + - * / **, whitelisted functions, bound variables).
  No eval/exec, no attribute access, bounded exponents and input length.
- `step_checks`: re-evaluates "lhs = rhs" pairs found in a solution. Closed numeric pairs are
  compared directly; pairs whose two sides share the same variables are checked as identities by
  evaluating both sides at seeded random points. Results: consistent / scaled (power-of-ten, i.e. a
  unit conversion) / inconsistent.
- `integer_candidates`: for an integer target variable, the integers in [0, 1000] that satisfy an
  equation for every random binding of the other variables.

Everything here is evidence about the *stored record*; none of it solves physics from first principles.
"""
import ast
import math
import operator
import random
import re
from dataclasses import dataclass

from .html_parse import parse_quantity

MAX_EXPR_CHARS = 400
REL_TOL = 0.01
FUNCS = {"sqrt": math.sqrt, "sin": math.sin, "cos": math.cos, "tan": math.tan, "ln": math.log,
         "log": math.log10, "exp": math.exp, "asin": math.asin, "acos": math.acos, "atan": math.atan}
CONSTS = {"π": math.pi, "pi": math.pi}
_BIN = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv}


class MathError(Exception):
    pass


def evaluate(expr: str, env: dict[str, float] | None = None) -> float:
    """Evaluate a Python-syntax arithmetic expression produced by `to_python`. Raises MathError."""
    if len(expr) > MAX_EXPR_CHARS:
        raise MathError("expression too long")
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as e:
        raise MathError("syntax") from e
    env = env or {}

    def ev(n):
        if isinstance(n, ast.Expression):
            return ev(n.body)
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)) and not isinstance(n.value, bool):
            return float(n.value)
        if isinstance(n, ast.Name):
            if n.id in env:
                return float(env[n.id])
            raise MathError(f"unbound {n.id}")
        if isinstance(n, ast.UnaryOp) and isinstance(n.op, (ast.USub, ast.UAdd)):
            v = ev(n.operand)
            return -v if isinstance(n.op, ast.USub) else v
        if isinstance(n, ast.BinOp):
            a, b = ev(n.left), ev(n.right)
            if isinstance(n.op, ast.Pow):
                if abs(b) > 64 or (abs(a) > 1e6 and abs(b) > 8):
                    raise MathError("exponent out of range")
                return a ** b
            if type(n.op) in _BIN:
                return _BIN[type(n.op)](a, b)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in FUNCS \
                and len(n.args) == 1 and not n.keywords:
            return FUNCS[n.func.id](ev(n.args[0]))
        raise MathError(f"disallowed {type(n).__name__}")

    try:
        v = ev(tree)
    except (ZeroDivisionError, OverflowError, ValueError, TypeError) as e:
        raise MathError(str(e)) from e
    if isinstance(v, complex) or math.isnan(v) or math.isinf(v):
        raise MathError("non-finite")
    return v


# ------------------------------------------------------------------ linear text → python

_TOKEN = re.compile(r"""
    (?P<num>\d+(?:\.\d+)?)
  | (?P<ident>[^\W\d_](?:_(?:\([^()]*\)|[^\W_]+))?(?![^\W\d_]))   # single letter (+ subscript)
  | (?P<word>[^\W\d_]{2,}(?:_(?:\([^()]*\)|[^\W_]+))?)            # multi-letter word or function
  | (?P<op>[-+*/^×·−÷])
  | (?P<lp>[(\[])
  | (?P<rp>[)\]])
  | (?P<ws>\s+)
  | (?P<other>.)
""", re.X)


@dataclass
class Expr:
    text: str             # original linear text of the span
    py: str               # python expression with variables renamed v0, v1…
    vars: dict[str, str]  # python name → original symbol

    @property
    def free(self) -> frozenset[str]:
        return frozenset(self.vars.values())


def _tokens(s: str):
    s = s.replace("()", " ")                         # empty-fence artifacts like "(400 ())"
    s = re.sub(r"(?<=\d)\s*x\s*(?=\d)", "×", s)      # "5.7 x 10" in plain HTML means times
    s = re.sub(r"(?<=\d) \. (?=\d)", ".", s)          # "0 . 3" (spaced decimal) means 0.3
    out = []
    for m in _TOKEN.finditer(s):
        kind = m.lastgroup
        if kind == "ws":
            continue
        text = m.group()
        if kind == "word" and text in FUNCS:
            kind = "func"
        elif kind == "word" and text in CONSTS:
            kind = "const"
        elif kind == "ident" and text in CONSTS:
            kind = "const"
        out.append((kind, text))
    return out


_MATH_KINDS = {"num", "ident", "op", "lp", "rp", "func", "const"}


def _balanced(toks) -> bool:
    depth = 0
    for k, _ in toks:
        depth += k == "lp"
        depth -= k == "rp"
        if depth < 0:
            return False
    return depth == 0


def _to_python(toks) -> Expr | None:
    if not toks or not _balanced(toks):
        return None
    names: dict[str, str] = {}
    parts, prev = [], None
    for i, (k, t) in enumerate(toks):
        if k == "func" and (i + 1 >= len(toks) or toks[i + 1][0] != "lp"):
            return None                               # "cos π/8" without brackets is ambiguous
        starts_atom = k in ("num", "ident", "lp", "func", "const")
        if prev in ("num", "ident", "rp", "const") and starts_atom:
            parts.append("*")                         # implicit multiplication: "2 q", "(a)(b)"
        if k == "num":
            parts.append(t)
        elif k == "ident":
            key = next((n for n, sym in names.items() if sym == t), None) or f"v{len(names)}"
            names[key] = t
            parts.append(key)
        elif k == "const":
            parts.append(repr(CONSTS[t]))
        elif k == "func":
            parts.append(t)
        elif k == "op":
            parts.append({"×": "*", "·": "*", "−": "-", "÷": "/", "^": "**"}.get(t, t))
        elif k == "lp":
            parts.append("(")
        elif k == "rp":
            parts.append(")")
        prev = k
    py = "".join(parts)
    try:
        ast.parse(py, mode="eval")
    except SyntaxError:
        return None
    return Expr(" ".join(t for _, t in toks), py, names)


def _trailing_run(seg: str):
    toks = _tokens(seg)
    i = len(toks)
    while i > 0 and toks[i - 1][0] in _MATH_KINDS:
        i -= 1
    if i > 0 and toks[i - 1] == ("other", "_"):
        return []                             # "(vec F)_21": the run is a subscript, not a value
    run = toks[i:]
    while run and not _balanced(run):        # drop leading tokens until balanced
        run = run[1:]
    while run and run[0][0] in ("op",) and run[0][1] not in "-−":
        run = run[1:]
    return run


def _leading_run(seg: str):
    toks = _tokens(seg)
    i = 0
    while i < len(toks) and toks[i][0] in _MATH_KINDS:
        i += 1
    run = toks[:i]
    while run and not _balanced(run):        # drop trailing tokens until balanced
        run = run[:-1]
    while run and run[-1][0] == "op":
        run = run[:-1]
    return run


def parse_expr(s: str) -> Expr | None:
    """Whole string as one expression, or None."""
    toks = _tokens(s)
    if any(k not in _MATH_KINDS for k, _ in toks):
        return None
    return _to_python(toks)


_UNIT_RE = re.compile(r"^[A-Za-zμΩÅ°∘/^\-\d\s().]{0,15}$")


def _quantity(seg: str) -> float | None:
    """Leading 'number [×10^k] unit' at the start of a right-hand side, e.g. '50 V', '4800 N / m^2'."""
    head = re.split(r"[,;]|\s(?:and|so|we|hence|for|therefore|then)\s", seg.strip(), maxsplit=1)[0]
    val, unit = parse_quantity(head)
    if val is None:
        return None
    unit = unit.strip()
    if unit and not (_UNIT_RE.match(unit) and re.search(r"[A-Za-zμΩÅ]", unit)) and unit not in (")",):
        return None
    return val


# ------------------------------------------------------------------ step checks

@dataclass
class StepCheck:
    line: int
    lhs: str
    rhs: str
    # consistent | scaled | inconsistent (closed numeric pairs only) | not_identity (symbolic pair that
    # is not an identity: neutral, because it may simply be an equation to be solved)
    status: str
    lhs_value: float | None = None
    rhs_value: float | None = None


def _close(a: float, b: float, tol: float = REL_TOL) -> bool:
    return math.isclose(a, b, rel_tol=tol, abs_tol=1e-12)


def _pow10_ratio(a: float, b: float) -> int | None:
    if a == 0 or b == 0 or (a < 0) != (b < 0):
        return None
    k = math.log10(abs(a / b))
    r = round(k)
    return r if r != 0 and abs(k - r) < 0.005 and abs(r) <= 12 else None


def _draws(names: frozenset[str], n: int = 3, seed: int = 20261110):
    rng = random.Random(seed + len(names))
    return [{s: rng.uniform(1.3, 3.7) for s in sorted(names)} for _ in range(n)]


def _env(expr: Expr, draw: dict[str, float]) -> dict[str, float]:
    return {py: draw[sym] for py, sym in expr.vars.items()}


def equations(text: str):
    """(line_no, lhs_segment, rhs_segment) for every '=' / '≈' in every line."""
    for ln, line in enumerate(text.split("\n")):
        parts = re.split(r"(?<![<>!])[=≈](?!=)", line)
        for i in range(len(parts) - 1):
            yield ln, parts[i], parts[i + 1]


def step_checks(solution_text: str) -> list[StepCheck]:
    out = []
    for ln, left, right in equations(solution_text):
        L = _to_python(_trailing_run(left))
        if L is None:
            continue
        R = _to_python(_leading_run(right))
        # A closed right-hand expression wins ("3 ln(2)"); only otherwise read "50 V" as number + unit.
        rq = None if (R is not None and not R.free) else _quantity(right)
        try:
            if not L.free and (rq is not None or (R is not None and not R.free)):
                lv = evaluate(L.py)
                rv = rq if rq is not None else evaluate(R.py)
                status = "consistent" if _close(lv, rv) else ("scaled" if _pow10_ratio(lv, rv) else "inconsistent")
                out.append(StepCheck(ln, L.text, right.strip()[:60], status, lv, rv))
            elif R is not None and L.free and L.free == R.free:
                ok = all(_close(evaluate(L.py, _env(L, d)), evaluate(R.py, _env(R, d)), 1e-6)
                         for d in _draws(L.free))
                out.append(StepCheck(ln, L.text, R.text, "consistent" if ok else "not_identity"))
        except MathError:
            continue
    return out


def computed_values(solution_text: str) -> list[float]:
    """Every numeric quantity that appears directly after an '=' in the solution."""
    vals = []
    for _, _, right in equations(solution_text):
        q = _quantity(right)
        if q is not None:
            vals.append(q)
    return vals


# ------------------------------------------------------------------ integer targets

def _satisfying(lhs: Expr, rhs: Expr, target: str, candidates) -> set[int]:
    others = (lhs.free | rhs.free) - {target}
    good = set()
    for k in candidates:
        try:
            if all(_close(evaluate(lhs.py, _env(lhs, {**d, target: k})),
                          evaluate(rhs.py, _env(rhs, {**d, target: k})), 1e-6)
                   for d in _draws(others)):
                good.add(k)
        except MathError:
            continue
    return good


def integer_candidates(lhs: Expr, rhs: Expr, target: str, extra=()) -> set[int]:
    if target not in (lhs.free | rhs.free):
        return set()
    return _satisfying(lhs, rhs, target, sorted(set(range(0, 1001)) | {int(x) for x in extra}))


def final_statement(solution_text: str) -> tuple[str, float, str] | None:
    """Last 'x = <number> [unit]' in the solution where x is a single symbol: (symbol, value, line)."""
    found = None
    for ln, left, right in equations(solution_text):
        run = _trailing_run(left)
        q = _quantity(right)
        if q is not None and len(run) == 1 and run[0][0] == "ident":
            found = (run[0][1], q, f"{run[0][1]} = {right.strip()[:30]}")
    return found


def solution_equations_with(solution_text: str, target: str):
    """Equation pairs in the solution that mention `target` on at least one side and are not the
    bare 'target = number' statement."""
    for _, left, right in equations(solution_text):
        L, R = _to_python(_trailing_run(left)), _to_python(_leading_run(right))
        if L is None or R is None:
            continue
        if target in (L.free | R.free) and not (L.free == {target} and not R.free and len(L.vars) == 1
                                                and L.py == next(iter(L.vars))):
            yield L, R


def stem_template(stem_text: str, target: str) -> Expr | None:
    """A maths span in the stem that contains `target` and at least one operator or other symbol,
    e.g. '(n q)/(2 ε_0)' for target n."""
    best = None
    toks = _tokens(stem_text)
    i = 0
    while i < len(toks):
        if toks[i][0] not in _MATH_KINDS:
            i += 1
            continue
        j = i
        while j < len(toks) and toks[j][0] in _MATH_KINDS:
            j += 1
        run = toks[i:j]
        while run and not _balanced(run):
            run = run[:-1]
        e = _to_python(run)
        if e and target in e.free and len(e.free) >= 2 and (best is None or len(e.py) > len(best.py)):
            best = e
        i = j
    return best
