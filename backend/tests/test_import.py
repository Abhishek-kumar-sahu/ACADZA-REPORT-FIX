"""T-U-01/02 and import validation against all 43 questions and 44 reports."""
import json
import shutil
from collections import Counter

import pytest
from sqlalchemy import func, select

from backend.app.importer import DATA_SHA256, ImportError_, import_all, load_validated, verify_hashes
from backend.app.models import AuditEvent, Case, Meta, Question, Report
from backend.app.config import ROOT
from backend.app.services import audit

DATA = ROOT / "data"


def test_hashes_match_committed_values():  # T-U-01
    assert verify_hashes(DATA) == DATA_SHA256


def test_tampered_byte_aborts(tmp_path):  # T-U-02
    shutil.copytree(DATA, tmp_path / "data")
    p = tmp_path / "data" / "reports.json"
    p.write_bytes(p.read_bytes().replace(b"wrong ans", b"wrong anz"))
    with pytest.raises(ImportError_, match="data_hash_mismatch: reports.json"):
        verify_hashes(tmp_path / "data")


def test_all_records_pass_strict_schema():
    qs, rs = load_validated(DATA)
    assert (len(qs), len(rs)) == (43, 44)


def test_schema_drift_is_rejected(tmp_path, monkeypatch, questions):
    shutil.copytree(DATA, tmp_path / "data")
    bad = [dict(questions[0], unexpected_field=1)] + questions[1:]
    p = tmp_path / "data" / "questions.json"
    p.write_text(json.dumps(bad), encoding="utf-8")
    monkeypatch.setitem(DATA_SHA256, "questions.json", __import__("hashlib").sha256(p.read_bytes()).hexdigest())
    with pytest.raises(ImportError_, match="unexpected_field"):
        load_validated(tmp_path / "data")


def test_unknown_question_reference_rejected(tmp_path, monkeypatch, reports):
    shutil.copytree(DATA, tmp_path / "data")
    bad = reports + [dict(reports[0], reportId="R999", questionId="f" * 24)]
    p = tmp_path / "data" / "reports.json"
    p.write_text(json.dumps(bad), encoding="utf-8")
    monkeypatch.setitem(DATA_SHA256, "reports.json", __import__("hashlib").sha256(p.read_bytes()).hexdigest())
    with pytest.raises(ImportError_, match="R999: unknown questionId"):
        load_validated(tmp_path / "data")


def test_counts_and_grouping(session, reports):
    count = lambda m: session.scalar(select(func.count()).select_from(m))  # noqa: E731
    assert (count(Question), count(Report), count(Case)) == (43, 44, 39)
    per_case = Counter(r["questionId"] for r in reports)
    assert Counter(per_case.values()) == {1: 35, 2: 3, 3: 1}
    for case in session.scalars(select(Case)):
        assert case.status == "untriaged" and case.origin == "student"
        first = min(r.reported_at for r in session.scalars(select(Report).where(Report.question_id == case.question_id)))
        assert case.first_reported_at == first


def test_original_json_roundtrips_exactly(session, qmap):
    for q in session.scalars(select(Question)):
        assert q.original == qmap[q.id]
        assert q.current_json == q.original_json and q.version == 1


def test_reports_stored_verbatim(session, reports):
    by_id = {r.report_id: r for r in session.scalars(select(Report))}
    for r in reports:
        row = by_id[r["reportId"]]
        assert (row.question_id, row.student_id, row.source, row.comment) == (
            r["questionId"], r["studentId"], r["source"], r["comment"])
        assert row.reported_at.utcoffset().total_seconds() == 0  # aware UTC after the DB round-trip
        assert row.reported_at.strftime("%Y-%m-%dT%H:%M:%SZ") == r["reportedAt"]


def test_import_is_idempotent_and_audited(session):
    assert import_all(session, DATA) == {"status": "already_imported"}
    types = Counter(e.event_type for e in session.scalars(select(AuditEvent)))
    assert types == {"report_received": 44, "import_completed": 1}
    assert audit.verify(session) == {"ok": True, "events": 45, "first_bad_id": None}
    assert session.get(Meta, "data_sha256") is not None
