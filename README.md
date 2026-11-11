# Acadza: Report → Fix

The system that sits between a student's "Report error" tap and the fix. It triages each report with an AI pipeline, verifies answer keys **independently** of both the key and the student, auto-applies only provably safe, taxonomy-permitted edits, and gives faculty a calm review console for the rest.

> **Project status: System integration, QA and security audit complete.** Full system verified: 509 tests passing (453 backend API/unit/guards + 56 Playwright Edge browser E2E tests). E2E lifecycle (submission → triage → investigation → proposal editing → validation → approval → execution → rollback) and security invariants verified. Data integrity verified (43 original questions byte-identical, 44 reports, 44 entries in `results.json`, 7 bonus findings). PostgreSQL testing remains a deployment gate. Live deployment is Phase 9.

## How it decides

```
report ─► group by question ─► deterministic detectors ─► blind solve (no key, no comment)
       ─► triage LLM (comment = untrusted data) ─► scope + safety guards (code)
       ─► calibrated confidence ─► route: auto_apply | faculty_review | no_change ─► honest reply
```

- **The student's comment is a lead, not an instruction.** Injection attempts are flagged, and they can never author an edit.
- **The backend decides the route**, not the model. A repair may only touch the fields `taxonomy.json` lists for it.
- **Answer-key changes need two independent signals** that agree (a blind solve plus the stored solution, a second solve, or a numeric check).
- **Originals are never overwritten.** Every write is a revision with rollback and a hash-chained audit entry.

## Repository map

| Path | What |
|---|---|
| `data/` | Original assignment datasets (read-only, hash-checked) |
| `docs/` | Architecture, rules, design, API, DB, testing, security, deployment, ADRs, roadmap, memory |
| `PROMPTS.md` | Every product prompt verbatim, coding-assistant prompts, AI mistakes caught, decision log |
| `PRODUCT.md` | One-page product answers |
| `results.json` | rules-only engine output for all 44 reports (`scripts/run_triage.py`, validated by `scripts/validate_results.py`) |
| `bonus_findings.json` | 7 unreported question-level findings, verified vs suspected |
| `artifacts/triage_snapshot.json` | full decisions: evidence, inference, recommendation, review reason |
| `backend/` | data layer + `/api/v1` read API and protected writes; engine to follow |
| `scripts/import_data.py` | verified import into `DATABASE_URL` |

Start with [docs/RULES.md](docs/RULES.md) (the safety contract) and [docs/SYSTEM_ARCHITECTURE.md](docs/SYSTEM_ARCHITECTURE.md).

## Run locally

```bash
pip install -r requirements.txt
set FACULTY_ACCESS_KEY=<a long random value>      # PowerShell: $env:FACULTY_ACCESS_KEY="..."
uvicorn backend.app.main:app --port 8000
# open http://localhost:8000/ : Settings → enter your name and the key to enable actions
```

Screenshots of every screen: [docs/screenshots/](docs/screenshots/).

See [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md). It works without an LLM key (`LLM_PROVIDER=none`, rules-only mode, clearly labelled).

## Deliverables checklist
- [ ] Public GitHub repo
- [x] `results.json` (44 entries, validated; **rules-only, no LLM**)
- [ ] Live URL (Render)
- [x] `PROMPTS.md` (started; product prompts are v1 drafts, not yet run)
- [x] `PRODUCT.md`
- [ ] 3-minute screen recording
