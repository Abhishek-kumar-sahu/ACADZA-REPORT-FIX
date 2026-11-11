"""The human reference notes (docs/DATA_DICTIONARY.md §4) must never reach the engine or AI input.

Two independent guards:
1. Static: no string constant in backend/app or scripts (docstrings excluded) points at docs/.
2. Runtime: spy on every file open while initialising, importing, and parsing all 43 records and
   checking history for all 44 reports; nothing under docs/ may be opened.
"""
import ast
import builtins
import io
import re
from pathlib import Path

from backend.app.config import ROOT
from backend.app.db import init_db, make_engine, session_factory
from backend.app.importer import import_all, parse_ts
from backend.app.triage.record import history_after, parse_record

DOCS = (ROOT / "docs").resolve()
DOCS_REF = re.compile(r"(^|[\\/])docs([\\/]|$)|DATA_DICTIONARY", re.I)


def _docstring_ids(tree) -> set[int]:
    ids = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                ids.add(id(body[0].value))
    return ids


def test_no_code_string_references_docs():
    offenders = []
    for py in list((ROOT / "backend" / "app").rglob("*.py")) + list((ROOT / "scripts").glob("*.py")):
        tree = ast.parse(py.read_text(encoding="utf-8"))
        skip = _docstring_ids(tree)
        for node in ast.walk(tree):
            if (isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in skip
                    and DOCS_REF.search(node.value)):
                offenders.append(f"{py.relative_to(ROOT)}: {node.value!r}")
    assert offenders == []


def test_engine_never_opens_docs(monkeypatch, questions, reports):
    opened: list[Path] = []
    real_open = builtins.open

    def spy(file, *a, **k):
        if isinstance(file, (str, Path)):
            opened.append(Path(file).resolve())
        return real_open(file, *a, **k)

    monkeypatch.setattr(builtins, "open", spy)
    monkeypatch.setattr(io, "open", spy)

    eng = make_engine("sqlite://")
    init_db(eng)
    with session_factory(eng)() as s:
        import_all(s, ROOT / "data")
    qmap = {q["_id"]: q for q in questions}
    for q in questions:
        parse_record(q)
    for r in reports:
        history_after(qmap[r["questionId"]], parse_ts(r["reportedAt"]))
    # Phase 4: the whole triage path (engine, bonus scan, outputs, DB persistence).
    from backend.app.services.triage_store import run_and_store
    from backend.app.triage import engine, output
    decisions = engine.run(questions, reports)
    output.validate_results(output.results(decisions), reports, questions)
    output.bonus_document(engine.bonus_findings(questions, engine.covered_defects(decisions)), len(questions))
    with session_factory(eng)() as s:
        run_and_store(s)

    assert any(p.parent == (ROOT / "data").resolve() for p in opened), "spy saw no data reads; spy broken"
    leaked = [p for p in opened if p == DOCS or DOCS in p.parents]
    assert leaked == []
