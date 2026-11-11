# Acadza: Report → Fix

The system that sits between a student's "Report error" tap and the fix. It triages each report with an AI-assisted pipeline (powered by Google Gemini with a deterministic rules-engine fallback), verifies answer keys **independently** of both the key and the student, auto-applies only provably safe, taxonomy-permitted edits, and gives faculty a calm review console for the rest.

> **Project status: Phase 0–7 Complete. Phase 8 has NOT started.** Full system verified: 509 tests passing (453 backend API/unit/guards + 56 Playwright Edge browser E2E tests). E2E lifecycle (submission → triage → investigation → proposal editing → validation → approval → execution → rollback) and security invariants verified. Data integrity verified (43 original questions byte-identical, 44 reports, 44 entries in `results.json`, 7 bonus findings). SQLite is the default and existing database (`acadza.db`). Gemini API integration is supported and configured via environment settings.

## How it decides

```
report ─► group by question ─► deterministic detectors ─► blind solve (no key, no comment)
       ─► triage LLM (Gemini / comment = untrusted data) ─► scope + safety guards (code)
       ─► calibrated confidence ─► route: auto_apply | faculty_review | no_change ─► honest reply
```

- **The student's comment is a lead, not an instruction.** Injection attempts are flagged, and they can never author an edit.
- **The backend decides the route**, not the model. A repair may only touch the fields `taxonomy.json` lists for it.
- **Answer-key changes need two independent signals** that agree (a blind solve plus the stored solution, a second solve, or a numeric check).
- **Originals are never overwritten.** Every write is a revision with rollback and a hash-chained audit entry.
- **Database:** SQLite (`acadza.db`) is the existing and default database, protected with WAL mode, foreign keys, and immutability triggers.

## Repository map

| Path | What |
|---|---|
| `data/` | Original assignment datasets (read-only, hash-checked) |
| `docs/` | Architecture, rules, design, API, DB, testing, security, deployment, ADRs, roadmap, memory |
| `PROMPTS.md` | Every product prompt verbatim, Gemini integration details, coding-assistant prompts, AI mistakes caught, decision log |
| `PRODUCT.md` | One-page product answers |
| `results.json` | Baseline triage output for all 44 reports (`scripts/run_triage.py`, validated by `scripts/validate_results.py`) |
| `bonus_findings.json` | 7 unreported question-level findings, verified vs suspected |
| `artifacts/triage_snapshot.json` | Full internal triage decisions: evidence, inference, recommendation, review reason |
| `backend/` | FastAPI REST API (`/api/v1`), SQLite database models, services, and triage engine |
| `frontend/` | Vanilla ES modules faculty review console served at `/` |
| `scripts/import_data.py` | Verified idempotent import into SQLite `acadza.db` |
| `scripts/run_triage.py` | Runs triage engine and updates `results.json` and database |
| `scripts/validate_results.py` | Validates schema and deliverable contracts |

Start with [docs/RULES.md](docs/RULES.md) (the safety contract) and [docs/SYSTEM_ARCHITECTURE.md](docs/SYSTEM_ARCHITECTURE.md).

## Run locally

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Configure environment (copy template)
cp .env.example .env
# Set FACULTY_ACCESS_KEY (min 16 chars) and optional LLM_API_KEY for Gemini in .env

# 3. Start application
uvicorn backend.app.main:app --reload --port 8000
# Open http://localhost:8000/ : Settings → enter your name and faculty key to enable actions
```

See [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) for Render deployment configuration. Works in both AI-assisted mode (Gemini) and deterministic rules-only mode (`LLM_PROVIDER=none`).


