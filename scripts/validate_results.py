"""Validate results.json and bonus_findings.json against the contract. Exit 1 on any problem.

Checks: exactly one entry per report (44), README keys in order, strict types, taxonomy-only verdicts and
repairs, repair <=> defect, edits valid against the ORIGINAL records (scope, find-exactly-once, answer
format), auto_apply only with an edit, reply rules, and the bonus file schema (no report IDs inside).
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.importer import load_validated  # noqa: E402
from backend.app.triage.output import BonusOut, validate_results  # noqa: E402


def main() -> int:
    questions, reports = load_validated(ROOT / "data")
    entries = json.loads((ROOT / "results.json").read_text(encoding="utf-8"))
    problems = validate_results(entries, reports, questions)
    bonus = json.loads((ROOT / "bonus_findings.json").read_text(encoding="utf-8"))
    qids = {q["_id"] for q in questions}
    for f in bonus.get("findings", []):
        try:
            BonusOut.model_validate(f)
        except Exception as e:
            problems.append(f"bonus {f.get('findingId')}: {e}")
        if f.get("questionId") not in qids:
            problems.append(f"bonus {f.get('findingId')}: unknown questionId")
        if "reportId" in f:
            problems.append(f"bonus {f.get('findingId')}: bonus findings must not reference reports")
    if bonus.get("questions_inspected") != len(questions):
        problems.append(f"bonus: questions_inspected {bonus.get('questions_inspected')} != {len(questions)}")
    if problems:
        print("INVALID:\n  " + "\n  ".join(problems))
        return 1
    print(f"OK: {len(entries)} results, {len(bonus['findings'])} bonus findings, all contract checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
