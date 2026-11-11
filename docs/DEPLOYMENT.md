# Deployment

> **Status:** nothing is deployed yet. Local run (§1) works and was verified with a real uvicorn process on 2026-11-11.
> **Deployment gate:** PostgreSQL integration and DB-level protection tests (TASK T2.5) must pass before any production deploy. They have not run yet (no Docker daemon available).

## 1. Local setup

Requirements: Python 3.11+, Node 18+ (only for Playwright tests), Git.

```bash
git clone <repo-url> acadza-report-fix && cd acadza-report-fix
python -m venv .venv
# Windows: .venv\Scripts\activate     macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env                  # then edit; LLM_PROVIDER=none works with no key
python scripts/import_data.py         # verifies hashes, creates acadza.db
python scripts/run_triage.py          # writes results.json, bonus_findings.json, artifacts/triage_snapshot.json
python scripts/validate_results.py    # contract check, exit 1 on any problem
uvicorn backend.app.main:app --reload --port 8000
# API: http://localhost:8000/api/v1/health   reference: http://localhost:8000/api/v1/reference
# Console: http://localhost:8000/ (Faculty console UI is served directly at /)
```

The frontend is served by FastAPI at `/`. There is no separate frontend server. Optionally, for live-reload CSS work, run `python -m http.server 5500 -d frontend` with `CORS_ORIGINS=http://localhost:5500` and `window.API_BASE` set in `frontend/js/config.js`.

## 2. Environment variables

| Var | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | `sqlite:///<repo>/acadza.db` | Local: SQLite. **Production: persistent PostgreSQL.** `postgres://…` is accepted and normalised to `postgresql+psycopg://…`. |
| `LLM_PROVIDER` | `none` | `anthropic`, `openai_compat` or `none` |
| `LLM_MODEL` | — | model ID for the chosen provider (e.g. a Gemini model via `openai_compat`) |
| `LLM_API_KEY` | — | secret |
| `LLM_BASE_URL` | provider default | for `openai_compat` |
| `LLM_FALLBACK_PROVIDER` / `_MODEL` / `_API_KEY` / `_BASE_URL` | — | optional second provider |
| `LLM_TIMEOUT_S` | `45` | per call |
| `LLM_MAX_CONCURRENCY` | `4` | |
| `LLM_PRICE_IN_PER_MTOK` / `LLM_PRICE_OUT_PER_MTOK` | — | only for the cost display |
| `AUTO_APPLY_MIN_CONFIDENCE` | `0.85` | RULES R-44 |
| `NO_CHANGE_MIN_CONFIDENCE` | `0.60` | RULES R-44 |
| `BOOT_IMPORT` | `true` | empty DB on startup → hash-verified import of `data/` |
| `BOOT_TRIAGE` | `true` | no triage run yet → run the rules engine once (proposals only, nothing applied) |
| `LOG_LEVEL` | `INFO` | JSON logs on stderr |
| `MAX_BODY_BYTES` | `65536` | request body limit (413 above) |
| `FACULTY_ACCESS_KEY` | — | **required for any write**. Unset = read-only console (fail closed). Use a long random value (`python -c "import secrets;print(secrets.token_urlsafe(32))"`). |
| `CORS_ORIGINS` | empty | dev only |
| `BOOT_FROM_SNAPSHOT` | `true` | empty DB → import + snapshot load |

## 3. Tests
See TESTING.md. Briefly: `pytest` (backend). Later: `python scripts/validate_results.py` and `npx playwright test`.

**Before production, run the suite against PostgreSQL (required):**
```bash
docker run -d --rm --name acadza-pg -e POSTGRES_PASSWORD=test -e POSTGRES_DB=acadza_test -p 55432:5432 postgres:16-alpine
TEST_POSTGRES_URL=postgresql+psycopg://postgres:test@localhost:55432/acadza_test pytest
```
Every DB-backed test runs twice (sqlite and postgres). The postgres variants are marked `postgres`.

## 4. GitHub
- Public repo. Commit `results.json` and `artifacts/triage_snapshot.json`. Do **not** commit `.env` or `*.db`.
- Commit the actual output of `run_triage.py`. Never edit `results.json` by hand.

## 5. Render

`render.yaml` (planned):
```yaml
services:
  - type: web
    name: acadza-report-fix
    runtime: python
    plan: free
    buildCommand: pip install -r requirements.txt
    startCommand: uvicorn backend.app.main:app --host 0.0.0.0 --port $PORT
    healthCheckPath: /api/v1/health
    envVars:
      - key: PYTHON_VERSION
        value: "3.11.9"
      - key: LLM_PROVIDER
        value: none           # demo serves the committed snapshot; set a key to enable re-triage
      - key: LLM_API_KEY
        sync: false
      - key: DATABASE_URL
        sync: false          # persistent Postgres URL (secret)
      - key: FACULTY_ACCESS_KEY
        sync: false          # required for faculty writes
      - key: BOOT_FROM_SNAPSHOT
        value: "true"
```

**Free-tier caveats (verify at deploy time, since policies change):**
- Instances spin down after inactivity. The first request after idle takes about 30–60 s. The console shows "Waking server…" if `/api/v1/health` is slow.
- The filesystem is ephemeral, so **production uses PostgreSQL** (project decision 3). Candidates: Neon or Supabase free tiers (persistent), or Render Postgres (free instances have historically expired after a fixed period, so check current terms against the 7-day requirement). Put the URL in `DATABASE_URL` as a secret. The SQLite fallback works but loses faculty actions on restart, and the UI says so.
- "Stay up for 7 days": an external uptime ping on `/api/v1/health` every 10 minutes keeps it warm (optional).

## 6. Post-deploy checks
1. `GET /api/v1/health` returns `status: ok` and `data_hashes_ok: true`.
2. Dashboard totals are 44 reports and 39 questions.
3. Open case `60f744b3…`. MathML renders.
4. Approve and roll back a case. The audit verify shows `ok`.
5. `GET /api/v1/results` equals the committed `results.json`.

## 7. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `data_hash_mismatch` on start | `data/*.json` was modified or line endings were converted. Add `data/*.json -text` to `.gitattributes`. |
| `schema_version mismatch` | Delete `acadza.db` and re-import (demo data). |
| Math shows as plain text | The browser lacks MathML Core. Use current Chrome, Edge, Firefox or Safari. |
| All cases say "Rules-only" | `LLM_PROVIDER=none`, or the key is invalid. Check AI Activity for errors. |
| 503 on the first request | Render cold start. Retry after ~60 s. |
