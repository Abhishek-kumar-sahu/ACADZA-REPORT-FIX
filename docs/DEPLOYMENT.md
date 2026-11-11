# Deployment

> **Project Status (2026-11-12): Phase 0–7 Complete. Phase 8 has NOT started.** Local execution and integration tests are verified. Deployment to Render is configured and ready.
> 
> **Database Architecture:** **SQLite is the default and existing database (`acadza.db`).** There is no migration to MySQL or PostgreSQL. All features, constraints, transactions, and audit integrity are built and verified natively on SQLite.

## 1. Local setup

Requirements: Python 3.11+, Git. (Node/Playwright is required only for running browser E2E tests).

```bash
git clone <repo-url> acadza-report-fix && cd acadza-report-fix
python -m venv .venv
# Windows: .venv\Scripts\activate     macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env                  # configure FACULTY_ACCESS_KEY and LLM_API_KEY
python scripts/import_data.py         # verifies SHA-256 hashes, creates SQLite acadza.db
python scripts/run_triage.py          # writes results.json, bonus_findings.json, artifacts/triage_snapshot.json
python scripts/validate_results.py    # contract check, exit 0 on success
uvicorn backend.app.main:app --reload --port 8000
# API: http://localhost:8000/api/v1/health
# Console: http://localhost:8000/ (Faculty console UI is served directly at /)
```

The frontend is served by FastAPI directly at `/`. There is no separate frontend server.

## 2. Environment variables

| Var | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./acadza.db` | SQLite database connection string. |
| `LLM_PROVIDER` | `none` | Active provider: `gemini`, `openai_compat`, or `none` (deterministic rules engine). |
| `LLM_MODEL` | `gemini-1.5-flash` | Model identifier for Google Gemini. |
| `LLM_API_KEY` | — | Secret Google Gemini API key (never committed, never logged, loaded as `SecretStr`). |
| `LLM_BASE_URL` | `https://generativelanguage.googleapis.com/v1beta/openai/` | OpenAI-compatible endpoint for Google Gemini. |
| `LLM_TIMEOUT_S` | `45` | Per-call timeout limit in seconds. |
| `LLM_MAX_CONCURRENCY` | `4` | Maximum parallel LLM calls. |
| `AUTO_APPLY_MIN_CONFIDENCE` | `0.85` | Confidence threshold for mechanical auto-eligible repairs. |
| `NO_CHANGE_MIN_CONFIDENCE` | `0.60` | Minimum confidence to close a non-defect report. |
| `BOOT_IMPORT` | `true` | Empty DB on startup → hash-verified import of `data/` questions and reports. |
| `BOOT_TRIAGE` | `true` | No triage run yet on startup → run triage engine once. |
| `BOOT_FROM_SNAPSHOT` | `true` | Empty DB → restore triage decisions from `artifacts/triage_snapshot.json`. |
| `LOG_LEVEL` | `INFO` | Structured JSON logs on stderr. |
| `MAX_BODY_BYTES` | `65536` | Request body size limit (64 KB). |
| `FACULTY_ACCESS_KEY` | — | **Required for faculty writes** (approve, reject, execute, rollback). Unset = read-only console (fail-closed 503). Must be ≥ 16 characters. |
| `CORS_ORIGINS` | empty | Dev only; comma-separated explicit origins (never `*`). |

## 3. Tests
See TESTING.md. Test execution:
```bash
pytest backend/tests -v                 # 453 backend unit, integration, and security tests
pytest backend/tests/test_console_e2e.py # 56 Playwright Edge browser E2E tests
python scripts/validate_results.py      # Contract check for results.json and bonus_findings.json
```

## 4. GitHub
- Public repo. Commit `results.json`, `bonus_findings.json`, and `artifacts/triage_snapshot.json`.
- Do **not** commit `.env` or `acadza.db` (enforced via `.gitignore`).
- Line endings are preserved as LF binary for data files via `.gitattributes`.

## 5. Render Configuration (`render.yaml`)

The service is configured as a single Python web service in `render.yaml`:

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
        value: gemini
      - key: LLM_MODEL
        value: gemini-1.5-flash
      - key: LLM_API_KEY
        sync: false          # Configured securely as a secret in Render Dashboard
      - key: LLM_BASE_URL
        value: https://generativelanguage.googleapis.com/v1beta/openai/
      - key: DATABASE_URL
        value: sqlite:///./acadza.db
      - key: FACULTY_ACCESS_KEY
        sync: false          # Configured securely as a secret in Render Dashboard
      - key: BOOT_FROM_SNAPSHOT
        value: "true"
      - key: BOOT_IMPORT
        value: "true"
      - key: BOOT_TRIAGE
        value: "true"
```

### SQLite Storage on Render Free Tier:
- **Ephemeral Storage Characteristics:** Render's free tier web services have an ephemeral container filesystem. When the container sleeps due to inactivity (after 15 minutes of idle) or redeploys, the local file system resets to the build state.
- **Boot Recovery Architecture:** Acadza handles this gracefully without requiring external database migrations:
  1. On cold start, `BOOT_IMPORT=true` automatically imports the 43 questions and 44 reports from `data/` and verifies their SHA-256 hashes.
  2. `BOOT_FROM_SNAPSHOT=true` immediately seeds the verified triage decisions from `artifacts/triage_snapshot.json`, ensuring the console, queue, and dashboard are populated and responsive within seconds.
  3. Any newly approved or executed faculty repairs during a container session are recorded in the local SQLite database. For permanent persistence across container re-creates in paid environments, a persistent disk can be mounted at `/data` or database snapshots can be periodically exported.
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
