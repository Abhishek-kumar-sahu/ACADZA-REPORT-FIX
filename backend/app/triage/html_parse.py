"""Production HTML + inline MathML → structure-preserving readable text.

Why not strip tags: stripping turns <mfrac>nq / 2ε0</mfrac> into "n q 2 ε 0", which changes the
maths (PROMPTS.md failure #3). Here MathML is linearised structurally: (n q)/(2 ε_0).

Pure stdlib (html.parser). Tolerates the misnested/unclosed <span> chains found in the data.
"""
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser

VOID = {"br", "img", "hr", "input", "meta", "link", "col", "area", "base", "wbr",
        "mspace", "mprescripts", "none", "malignmark", "maligngroup"}
BLOCK = {"p", "div", "h1", "h2", "h3", "h4", "h5", "h6", "li", "tr", "table", "ul", "ol"}
SKIP = {"script", "style", "annotation", "annotation-xml", "mphantom"}
ZERO_WIDTH = dict.fromkeys((0x200B, 0x200C, 0x200D, 0x2060, 0xFEFF), None)
NBSP = chr(0xA0)
ARROWS = {"→", "⃗", "⟶", "→"}
BARS = {"¯", "‾", "_", "―", "—"}
# Literal LaTeX commands visible as text (markup_leak evidence). Written in a source file, never via a
# shell heredoc: a collapsed backslash once made this pattern match nothing (PROMPTS.md failure #1).
LATEX_COMMAND_RE = re.compile(r"\\[A-Za-z]+")


@dataclass
class Node:
    tag: str
    attrs: dict = field(default_factory=dict)
    children: list = field(default_factory=list)  # Node | str


class _TreeBuilder(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node("#root")
        self.stack = [self.root]

    def handle_starttag(self, tag, attrs):
        node = Node(tag, dict(attrs))
        self.stack[-1].children.append(node)
        if tag not in VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.stack[-1].children.append(Node(tag, dict(attrs)))

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                return  # stray end tags with no open match are ignored

    def handle_data(self, data):
        self.stack[-1].children.append(data)


def parse_html(raw: str) -> Node:
    b = _TreeBuilder()
    b.feed(raw or "")
    b.close()
    return b.root


def iter_nodes(node: Node, tag: str):
    for c in node.children:
        if isinstance(c, Node):
            if c.tag == tag:
                yield c
            yield from iter_nodes(c, tag)


# ---------------------------------------------------------------- MathML → linear text

def _wrap(x: str) -> str:
    return x if re.fullmatch(r"-?[\w.]+", x) else f"({x})"


def _clean_math(s: str) -> str:
    s = re.sub(r"[ \t]+", " ", s).strip()
    s = re.sub(r"\( ", "(", s)
    s = re.sub(r" \)", ")", s)
    s = re.sub(r"(^|[\s(^_/=,])- (?=[\w(])", r"\1-", s)  # unary minus binds: "- 5" → "-5"
    return s


def _tokens(node: Node) -> str:
    return "".join(c if isinstance(c, str) else _tokens(c) for c in node.children)


def _math(n) -> str:
    if isinstance(n, str):
        return n.strip()
    t = n.tag
    if t in SKIP:
        return ""
    kids = [c for c in n.children if not (isinstance(c, str) and not c.strip())]
    parts = [_math(c) for c in kids]
    if t in ("mi", "mn", "mo", "mtext", "ms"):
        return _tokens(n).replace(NBSP, " ").replace("−", "-").strip()
    if t == "mspace":
        return "\n" if n.attrs.get("linebreak") == "newline" else ""
    if t == "semantics":
        return parts[0] if parts else ""
    if t == "mfrac" and len(parts) >= 2:
        return f"{_wrap(parts[0])}/{_wrap(parts[1])}"
    if t == "msup" and len(parts) >= 2:
        return f"{_wrap(parts[0])}^{_wrap(parts[1])}"
    if t in ("msub", "munder") and len(parts) >= 2:
        return f"{_wrap(parts[0])}_{_wrap(parts[1])}"
    if t in ("msubsup", "munderover") and len(parts) >= 3:
        return f"{_wrap(parts[0])}_{_wrap(parts[1])}^{_wrap(parts[2])}"
    if t == "msqrt":
        return f"sqrt({_clean_math(' '.join(parts))})"
    if t == "mroot" and len(parts) >= 2:
        return f"({parts[0]})^(1/{parts[1]})"
    if t == "mover" and len(parts) >= 2:
        if parts[1] in ARROWS:
            return f"vec({parts[0]})"
        if parts[1] in BARS:
            return f"bar({parts[0]})"
        return f"{_wrap(parts[0])}^{_wrap(parts[1])}"
    if t == "mfenced":
        o, c = n.attrs.get("open", "("), n.attrs.get("close", ")")
        return f"{o}{', '.join(parts)}{c}"
    if t == "mtable":
        return "; ".join(p for p in parts if p)
    if t == "mtr":
        return ", ".join(p for p in parts if p)
    # math, mrow, mstyle, mpadded, menclose…: upright single identifiers in a row are one unit word
    # (<mi mathvariant="normal">o</mi><mi …>h</mi><mi …>m</mi> → "ohm", not "o h m").
    out, prev_upright = [], False
    for c, p in zip(kids, parts):
        upright = isinstance(c, Node) and c.tag == "mi" and c.attrs.get("mathvariant") == "normal"
        if upright and prev_upright and out:
            out[-1] += p
        elif p:
            out.append(p)
        prev_upright = upright
    return _clean_math(" ".join(out))


# ---------------------------------------------------------------- HTML → linear text

def _text(n, out: list) -> None:
    if isinstance(n, str):
        out.append(n.replace(NBSP, " ").translate(ZERO_WIDTH))
        return
    t = n.tag
    if t in SKIP:
        return
    if t == "math":
        out.append(" " + _math(n) + " ")
        return
    if t == "br":
        out.append("\n")
        return
    if t in ("sup", "sub"):
        inner = []
        for c in n.children:
            _text(c, inner)
        s = re.sub(r"\s+", " ", "".join(inner)).strip()
        out.append(("^" if t == "sup" else "_") + _wrap(s) if s else "")
        return
    for c in n.children:
        _text(c, out)
    if t in BLOCK:
        out.append("\n")


def html_to_text(raw: str) -> str:
    out: list[str] = []
    _text(parse_html(raw), out)
    lines = (re.sub(r"[ \t\r\f\v]+", " ", ln).strip() for ln in "".join(out).replace("\r", "\n").split("\n"))
    return "\n".join(ln for ln in lines if ln)


def latex_commands(text: str) -> list[str]:
    return LATEX_COMMAND_RE.findall(text or "")


# ---------------------------------------------------------------- options inside the stem

_TAG_RE = re.compile(r"<[^>]*>")
_MARKER_RE = re.compile(r"\(\s*([A-D])\s*\)")


@dataclass
class Option:
    letter: str
    html: str   # raw slice of the stored question HTML (may contain unbalanced tags)
    text: str   # linear text
    blank: bool


def _markers(raw: str) -> list[tuple[str, int, int]]:
    """(letter, start, end) of '(A)'-style markers that sit in text, never inside a tag."""
    found, pos = [], 0
    for m in list(_TAG_RE.finditer(raw)) + [None]:
        stop = m.start() if m else len(raw)
        for mk in _MARKER_RE.finditer(raw, pos, stop):
            found.append((mk.group(1), mk.start(), mk.end()))
        pos = m.end() if m else stop
    return found


def _chain(markers):
    """Last '(A)' followed in order by (B)[, (C)[, (D)]]. Anchoring on the LAST (A) prevents
    'Assertion (A)' / 'Statement (A)' in the stem from being read as an option (failure #2)."""
    for i in range(len(markers) - 1, -1, -1):
        if markers[i][0] != "A":
            continue
        chain, want = [markers[i]], "B"
        for mk in markers[i + 1:]:
            if mk[0] == want:
                chain.append(mk)
                if want == "D":
                    break
                want = chr(ord(want) + 1)
        if len(chain) >= 2:
            return chain
    return []


def split_options(raw: str) -> tuple[str, list[Option]]:
    """Returns (stem_html, options). No options found → (raw, [])."""
    chain = _chain(_markers(raw))
    if not chain:
        return raw, []
    opts = []
    for i, (letter, _start, end) in enumerate(chain):
        stop = chain[i + 1][1] if i + 1 < len(chain) else len(raw)
        html = raw[end:stop]
        text = html_to_text(html)
        opts.append(Option(letter, html, text, blank=not text.strip()))
    return raw[:chain[0][1]], opts


# ---------------------------------------------------------------- numbers & final values

_NUM = r"[-−]?\d+(?:\.\d+)?"
_QTY_RE = re.compile(rf"\s*({_NUM})(?:\s*[×x*]\s*10\s*\^\s*\(?\s*({_NUM})\s*\)?)?\s*(.*)", re.S)


def parse_quantity(s: str) -> tuple[float | None, str]:
    """'4800 N/m^2' → (4800.0, 'N/m^2'); '5.7 x 10^-5/^oC' → (5.7e-05, '/^oC'); 'q/(2 ε_0)' → (None, …)."""
    m = _QTY_RE.match(s or "")
    if not m:
        return None, (s or "").strip()
    mant = float(m.group(1).replace("−", "-"))
    exp = float(m.group(2).replace("−", "-")) if m.group(2) else 0.0
    return mant * 10 ** exp, m.group(3).strip(" .")


def solution_final(solution_text: str) -> dict | None:
    """Advisory signal only: what the stored solution's last '=' / '≈' evaluates to.
    Never a verdict on its own (prose after the last '=' can mislead)."""
    flat = (solution_text or "").replace("\n", " ")
    parts = re.split(r"[=≈]", flat)
    if len(parts) < 2:
        return None
    seg = re.split(r"\s[,;)]\s|\.\s|\s\.$", parts[-1].strip())[0].strip(" .")[:80]
    value, unit = parse_quantity(seg)
    return {"expr": seg, "value": value, "unit": unit if value is not None else None}
