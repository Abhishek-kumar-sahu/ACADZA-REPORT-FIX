"""Answer canonicalisation and question history across all records/reports."""
from backend.app.importer import parse_ts
from backend.app.triage.html_parse import Option
from backend.app.triage.record import canonical_answer, history_after

MCQ_EMPTY = "68f21caf941cda588bc04365"
MCQ_JOINED = "68c8153cfb6b2f16e2d3ceaf"
BLANK_KEY = "68e872546e45ba37dcc16bc0"
MISSING_D = "622f08d7b70e4b50e4500a1b"


def test_answer_issues_only_where_expected(parsed):
    issues = {qid: p.answer_issues for qid, p in parsed.items() if p.answer_issues}
    assert issues == {
        MCQ_EMPTY: ["empty_element"],
        MCQ_JOINED: ["joined_string"],
        BLANK_KEY: ["keyed_option_blank:C"],
        MISSING_D: ["option_count:3"],
    }


def test_canonical_forms(parsed):
    assert parsed[MCQ_EMPTY].answer == ["B"]
    assert parsed[MCQ_JOINED].answer == ["A", "B", "D"]
    for p in parsed.values():
        if p.type == "scq":
            assert p.answer in p.letters, p.id
        elif p.type == "integerQuestion":
            assert p.answer == p.answer_raw and p.answer.lstrip("-").replace(".", "").isdigit()


def _opts(*letters, blank=()):
    return [Option(x, "", "" if x in blank else "v", x in blank) for x in letters]


def test_canonical_answer_edge_cases():
    four = _opts("A", "B", "C", "D")
    assert canonical_answer("mcq", ["A", "B"], four) == (["A", "B"], [])
    assert canonical_answer("mcq", ["B", "A", "A"], four)[1] == ["duplicate_letter"]
    assert canonical_answer("mcq", [], four)[1] == ["empty_answer"]
    assert canonical_answer("mcq", "A", four)[1] == ["not_a_list"]
    assert canonical_answer("scq", "E", four)[1] == ["not_a_letter"]
    assert canonical_answer("scq", "D", _opts("A", "B", "C"))[1] == ["keyed_option_missing:D"]
    assert canonical_answer("integerQuestion", "3.5", [])[1] == []
    assert canonical_answer("integerQuestion", "abc", [])[1] == ["not_numeric"]


def test_history_considered_for_every_report(reports, qmap):
    """Only R017's question has a fix recorded after the report; every other report has none."""
    found = {r["reportId"]: history_after(qmap[r["questionId"]], parse_ts(r["reportedAt"])) for r in reports}
    assert {k for k, v in found.items() if v} == {"R017"}
    assert found["R017"][0]["actor"] == "faculty"


def test_history_before_report_is_ignored(qmap):
    q = qmap["6208e80a9cb2ab67dac61bd0"]
    assert history_after(q, parse_ts("2026-11-08T00:00:00Z")) == []
