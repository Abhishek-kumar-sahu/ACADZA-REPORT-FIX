"""Verify dataset hashes, validate schemas, and import into the configured DB (DATABASE_URL).

Usage: python scripts/import_data.py [--database-url URL]
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app.config import settings  # noqa: E402
from backend.app.db import init_db, make_engine, session_factory, table_counts  # noqa: E402
from backend.app.importer import ImportError_, import_all  # noqa: E402
from backend.app.services import audit  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--database-url", default=None)
    args = ap.parse_args()
    engine = make_engine(args.database_url)
    init_db(engine)
    with session_factory(engine)() as s:
        try:
            result = import_all(s, settings.data_dir)
        except ImportError_ as e:
            print(f"IMPORT FAILED: {e}", file=sys.stderr)
            return 1
        print(json.dumps({**result, "counts": table_counts(s), "audit": audit.verify(s),
                          "database": engine.url.render_as_string(hide_password=True)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
