"""Parser validated against all 43 real records, plus one regression test per identified parser
failure (PROMPTS.md Part C)."""
import re

import pytest

from backend.app.triage.html_parse import (html_to_text, iter_nodes, latex_commands, parse_html,
                                           parse_quantity, split_options)

FIELDS = ("question", "solution")
TAG_REMNANT = re.compile(r"</?[a-zA-Z][\w-]*[\s/>]")


def _bodies(questions):
    for q in questions:
        body = q[q["questionType"]]
        for f in FIELDS:
            yield q["_id"], f, body[f] or ""


# ------------------------------------------------------------- whole-dataset validation

def test_every_field_parses_without_tag_remnants(questions):
    for qid, f, raw in _bodies(questions):
        text = html_to_text(raw)
        assert not TAG_REMNANT.search(text), (qid, f, TAG_REMNANT.search(text).group())
        if raw.strip():
            assert text.strip(), (qid, f)


def test_every_math_element_is_linearised(questions):
    """Every <math> in the raw HTML becomes a node in the tree (none swallowed by bad nesting)."""
    for qid, f, raw in _bodies(questions):
        assert len(list(iter_nodes(parse_html(raw), "math"))) == raw.count("<math"), (qid, f)


@pytest.mark.parametrize("tag,marker", [("mfrac", "/"), ("msqrt", "sqrt("), ("msup", "^")])
def test_math_structure_survives_linearisation(questions, tag, marker):
    """Structure, not just tokens: each fraction/root/power leaves its operator in the text.
    (Stripped text alone would lose them, which is PROMPTS.md failure #3.)"""
    for qid, f, raw in _bodies(questions):
        n = raw.count(f"<{tag}")
        assert html_to_text(raw).count(marker) >= n, (qid, f, tag)


def test_option_counts_on_all_choice_questions(parsed):
    counts = {qid: len(p.options) for qid, p in parsed.items() if p.type != "integerQuestion"}
    assert len(counts) == 33
    assert {qid for qid, n in counts.items() if n != 4} == {"622f08d7b70e4b50e4500a1b"}
    assert counts["622f08d7b70e4b50e4500a1b"] == 3


def test_integer_questions_have_no_options(parsed):
    ints = [p for p in parsed.values() if p.type == "integerQuestion"]
    assert len(ints) == 10 and all(p.options == [] for p in ints)


def test_option_letters_in_order_and_stem_has_no_options(parsed):
    for p in parsed.values():
        if p.options:
            assert p.letters == ["A", "B", "C", "D"][: len(p.options)]
            assert "(B)" not in p.stem_text and "(C)" not in p.stem_text, p.id


def test_only_known_blank_and_duplicate_options(parsed):
    blanks = {(p.id, o.letter) for p in parsed.values() for o in p.options if o.blank}
    assert blanks == {("68e872546e45ba37dcc16bc0", "C")}
    dups = set()
    for p in parsed.values():
        texts = [o.text for o in p.options if not o.blank]
        if len(set(texts)) != len(texts):
            dups.add(p.id)
    assert dups == {"6956d79788d7701e5617bc29"}


# ------------------------------------------------------------- failure #1: LaTeX regex matched nothing

def test_latex_leaks_found_exactly(parsed):
    hits = {}
    for p in parsed.values():
        for f, text in (("question", p.stem_text + " " + " ".join(o.text for o in p.options)),
                        ("solution", p.solution_text)):
            if latex_commands(text):
                hits[(p.id, f)] = latex_commands(text)
    assert hits == {("63765a28f1d8416ae0408d89", "question"): ["\\frac"],
                    ("612151a6a34397610a9a2e58", "solution"): ["\\AA"]}


def test_latex_regex_has_real_backslash():
    assert latex_commands(r"t = \frac{7}{8}") == ["\\frac"]
    assert latex_commands("[a-zA-Z]+") == []  # the broken pattern's only possible match


def test_latex_alignment_leak_kept_visible(parsed):
    assert "&" in parsed["6956d79788d7701e5617bc29"].solution_text


# ------------------------------------------------------------- failure #2: "Assertion (A)" as an option

def test_assertion_marker_not_taken_as_option(parsed):
    p = parsed["695ee00b88d7701e561aabc5"]
    assert len(p.options) == 4
    assert p.options[0].text.startswith("Both A and R are true")
    assert "Assertion (A)" in p.stem_text and "Reason (R)" in p.stem_text


def test_marker_inside_tag_attribute_ignored():
    stem, opts = split_options('<p title="(A)">Q?</p>(A) x<br>(B) y<br>(C) z<br>(D) w')
    assert [o.text for o in opts] == ["x", "y", "z", "w"] and "Q?" in html_to_text(stem)


def test_no_option_chain_returns_whole_html():
    assert split_options("<p>Statement (A) only</p>") == ("<p>Statement (A) only</p>", [])


# ------------------------------------------------------------- failure #3: stripped text changed the maths

def test_fraction_structure_preserved_r005(parsed):
    p = parsed["68dea616d0cda73d07e93ae6"]
    assert "(n q)/(2 ε_0)" in p.stem_text
    assert "q/2" in p.stem_text  # charge q/2, not "q 2"
    assert p.solution_final["expr"] == "q/(2 ε_0)"


def test_mathml_constructs():
    m = lambda s: html_to_text(f'<math xmlns="http://www.w3.org/1998/Math/MathML">{s}</math>')  # noqa: E731
    assert m("<msqrt><mn>2</mn></msqrt>") == "sqrt(2)"
    assert m("<msup><mn>10</mn><mrow><mo>&#x02212;</mo><mn>5</mn></mrow></msup>") == "10^-5"
    assert m("<msub><mi>F</mi><mn>12</mn></msub>") == "F_12"
    assert m("<mover><mi>F</mi><mo>&rarr;</mo></mover>") == "vec(F)"
    assert m("<mroot><mi>x</mi><mn>3</mn></mroot>") == "(x)^(1/3)"
    assert m('<mi mathvariant="normal">o</mi><mi mathvariant="normal">h</mi><mi mathvariant="normal">m</mi>') == "ohm"
    assert m("<semantics><mi>x</mi><annotation>LaTeX x</annotation></semantics>") == "x"


def test_html_superscripts_and_entities(parsed):
    assert parsed["6062ec84518e9535e120c422"].options[0].text.startswith("5.7 x 10^-5")
    assert html_to_text("a&nbsp;b&#8203;c") == "a bc"


def test_unbalanced_spans_tolerated(parsed):
    # 61dffbec nests options inside unclosed <span> chains.
    assert [o.text for o in parsed["61dffbec08489156b684bd22"].options] == [
        "Epithellial tisue", "Connective tissue", "Nervous tissue", "Muscular tissue"]


# ------------------------------------------------------------- quantities / solution final value

@pytest.mark.parametrize("s,v,u", [("4800 N/m^2", 4800.0, "N/m^2"), ("5.7 x 10^-5/^oC", 5.7e-05, "/^oC"),
                                   ("−3.5 V", -3.5, "V"), ("q/(2 ε_0)", None, "q/(2 ε_0)")])
def test_parse_quantity(s, v, u):
    val, unit = parse_quantity(s)
    assert (val if v is None else pytest.approx(v)) == val and unit == u


@pytest.mark.parametrize("qid,value", [
    ("60f744b3f1b9bc7cc7b4a949", 50.0), ("68e870ef42c06737d6e565c4", 4800.0),
    ("6263d75bdd44e265ef926d97", 40.0), ("68dea7c2387eea3d0d95f9bb", 0.08),
    ("63765a28f1d8416ae0408d89", 180.0), ("60f742f6660d187cc13a8078", 50.0)])
def test_solution_final_values(parsed, qid, value):
    assert parsed[qid].solution_final["value"] == pytest.approx(value)
