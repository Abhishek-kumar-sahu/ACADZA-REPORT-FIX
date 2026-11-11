"""Allowlist sanitiser for stored question HTML + MathML (ADR-013, SECURITY §3).

nh3 (Rust `ammonia`, html5ever parser) re-serialises a browser-equivalent parse tree, so output is
well-formed and only allowlisted tags/attributes survive. Notes:
- No `style`, `class`, `id`, `href` or event attributes anywhere. MathML Core allows `href` on
  any element, so it is deliberately absent from every allowlist.
- `<img>` keeps only http(s) `src` (no data:/javascript:).
- Script/style/iframe/etc. are removed *with their content*.
- `annotation-xml` and `maction` are dropped: they can embed or toggle HTML inside MathML.
"""
import re

import nh3

HTML_TAGS = {
    "h1", "h2", "h3", "h4", "h5", "h6", "p", "div", "span", "br", "hr", "b", "strong", "i", "em",
    "u", "s", "sup", "sub", "small", "ul", "ol", "li", "table", "thead", "tbody", "tr", "td", "th",
    "blockquote", "pre", "code", "img",
}
MATHML_TAGS = {
    "math", "mrow", "mi", "mn", "mo", "mtext", "ms", "mspace", "msup", "msub", "msubsup", "mfrac",
    "msqrt", "mroot", "mover", "munder", "munderover", "mstyle", "mpadded", "mphantom", "menclose",
    "mfenced", "mtable", "mtr", "mtd", "mlabeledtr", "semantics", "annotation", "merror",
    "mmultiscripts", "mprescripts", "none",
}
_TOKEN = {"mathvariant", "dir"}
_MO = _TOKEN | {"stretchy", "fence", "form", "separator", "lspace", "rspace", "largeop",
                "movablelimits", "accent", "symmetric", "minsize", "maxsize"}
ATTRIBUTES = {
    "math": {"xmlns", "display", "displaystyle", "dir"},
    "mstyle": {"displaystyle", "scriptlevel", "mathvariant", "dir"},
    "mi": _TOKEN, "mn": _TOKEN, "mtext": _TOKEN, "ms": _TOKEN, "mo": _MO,
    "mspace": {"linebreak", "width", "height", "depth"},
    "mfrac": {"linethickness", "bevelled"},
    "mover": {"accent"}, "munder": {"accentunder"}, "munderover": {"accent", "accentunder"},
    "mfenced": {"open", "close", "separators"},
    "menclose": {"notation"},
    "mpadded": {"width", "height", "depth", "lspace", "voffset"},
    "mtable": {"columnalign", "rowalign", "columnspacing", "rowspacing", "displaystyle"},
    "mtr": {"columnalign", "rowalign"}, "mtd": {"columnalign", "rowalign", "columnspan", "rowspan"},
    "annotation": {"encoding"},
    "td": {"colspan", "rowspan"}, "th": {"colspan", "rowspan"},
    "img": {"src", "alt", "width", "height"},
}
CONTENT_REMOVED = {"script", "style", "iframe", "object", "embed", "noscript", "template",
                   "textarea", "select", "svg", "annotation-xml", "maction", "frame", "frameset"}


_MATH_REGION = re.compile(r"(<math\b[^>]*>.*?(?:</math\s*>|$))", re.S | re.I)
_STRAY_MATHML_TAG = re.compile(r"</?(?:%s)\b[^>]*>" % "|".join(sorted(MATHML_TAGS - {"math"}, key=len, reverse=True)),
                               re.I)


def _unwrap_stray_mathml(raw: str) -> str:
    """MathML tags outside <math> (e.g. an unclosed <mspace linebreak="newline"> between options in
    68c9ae5a/68dea87d/68c8153c) are unknown containers to a browser, which still shows their content.
    nh3 instead deletes them *with* their content, silently dropping options B-D. Unwrap them first
    (keep content), matching what browsers render."""
    parts = _MATH_REGION.split(raw)
    return "".join(p if i % 2 else _STRAY_MATHML_TAG.sub("", p) for i, p in enumerate(parts))


def sanitize_html(raw: str | None) -> str:
    if not raw:
        return ""
    return nh3.clean(
        _unwrap_stray_mathml(raw),
        tags=HTML_TAGS | MATHML_TAGS,
        clean_content_tags=CONTENT_REMOVED,
        attributes=ATTRIBUTES,
        url_schemes={"http", "https"},
        strip_comments=True,
        link_rel=None,
    )
