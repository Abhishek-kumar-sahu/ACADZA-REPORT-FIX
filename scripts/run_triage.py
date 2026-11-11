"""Run the rules-only triage engine on the original datasets and write the deliverables.

  results.json                  exactly 44 entries, README schema
  bonus_findings.json           unreported question-level findings (not reports)
  artifacts/triage_snapshot.json  internal superset: evidence / inference / recommendation / review reason

Usage: python scripts/run_triage.py [--database-url URL]   (with a URL, also import + persist to that DB)
Output is deterministic: running twice produces byte-identical files.
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.importer import load_validated  # noqa: E402
from backend.app.triage import engine, output  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--database-url", default=None, help="also import and persist decisions to this DB")
    args = ap.parse_args()

    questions, reports = load_validated(ROOT / "data")            # hash-verified, schema-validated
    decisions = engine.run(questions, reports)
    entries = output.results(decisions)
    problems = output.validate_results(entries, reports, questions)
    if problems:
        print("results.json would be INVALID:\n  " + "\n  ".join(problems), file=sys.stderr)
        return 1
    bonus = engine.bonus_findings(questions, engine.covered_defects(decisions))
    output.dump(entries, ROOT / "results.json")
    output.dump(output.bonus_document(bonus, len(questions)), ROOT / "bonus_findings.json")
    output.dump(output.snapshot(decisions), ROOT / "artifacts" / "triage_snapshot.json")

    if args.database_url:
        from backend.app.db import init_db, make_engine, session_factory
        from backend.app.importer import import_all
        from backend.app.services.triage_store import run_and_store
        eng = make_engine(args.database_url)
        init_db(eng)
        with session_factory(eng)() as s:
            import_all(s, ROOT / "data")
            run_and_store(s)

    count = lambda key: {v: sum(e[key] == v for e in entries) for v in sorted({e[key] for e in entries})}  # noqa: E731
    print(json.dumps({"engine": engine.ENGINE, "mode": engine.ENGINE_MODE, "reports": len(entries),
                      "verdicts": count("verdict"), "routes": count("route"),
                      "bonus_findings": len(bonus)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
