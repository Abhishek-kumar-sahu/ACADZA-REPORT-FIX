# MEMORY: Project State

Read this first in every session. Update it whenever a major decision or status changes.

## Identity
**Acadza: Report → Fix.** An AI-assisted triage and faculty review console for student-reported question errors. This is the Acadza AI Intern Assignment. The brief is in `docs/ASSIGNMENT_BRIEF.md`.

## Status (2026-11-11, end of Phase 7)
- ✅ Phases 0–7: inspection, docs, data layer, API foundation, rules-only triage engine, faculty review & safe execution, faculty console frontend, **full system integration, QA & security audit**.
- ✅ `pytest`: **509 passed, 0 skipped**: 453 backend + 56 browser e2e (`test_console_e2e.py`, Playwright driving installed Microsoft Edge).
- ✅ `results.json` (44) and `bonus_findings.json` (7) verified deterministic and compliant.
- ✅ Full E2E lifecycle and data integrity invariants verified.
- ⛔ **T2.5 PostgreSQL tests not executed** (no Docker daemon). Hard gate before production deploy.
- ❌ Not done: production deployment (Phase 9), screen recording, LLM provider (T4.3/T4.4).

## Project decisions (user)
1. Metadata/syllabus problems are defects only via taxonomy `wrong_chapter` / `syllabus` (faculty).
2. `results.json` edits are a single `{field, find, replace}` or null. mcq is a list internally. Multi-field fixes get faculty_review + edit null.
3. SQLite local, persistent PostgreSQL in production. Postgres tests must pass before deploy.
4. `FACULTY_ACCESS_KEY` on every write (fail closed). Reads public.
5. Rules-only engine first, labelled. A provider-independent adapter comes later.
6. `bonus_findings.json` is separate (verified vs suspected). `results.json` has exactly 44 entries.
7. (Phase 4 brief) Never automatically approve, reject or publish repairs in Phase 4; route uncertain cases to faculty; never hard-code trap IDs.

## Triage results (rules-v1)
- **Verdicts:** defect 27, no_error 11, display_issue 2, already_fixed 1, app_issue 1, language_mode 1, not_actionable 1.
- **Routes:** auto_apply 4 (R012 spelling, R013 exam tag, R014 `\frac`, R024 unit; eligible only, nothing applied), faculty_review 24, no_change 16.
- **Mandatory traps:**
  - R004: defect/answer_key A→D (student's 8225 not supported);
  - R005: defect/answer_key 2→1 (student correct);
  - R017: already_fixed;
  - R027: no_error + injection flagged;
  - R034: defect/unsound (self-contradicting solution);
  - R009/R010: option_repair, faculty, no edit.
- **Uncertain:** R035 (recall, unverifiable → faculty, 0.50), R026 (syllabus, 0.50), R034 (0.55).
- **Bonus (7):** notation ×2 (6062ec84 `/CC`, 6956d7e9 `√(2 m)`), spelling ×2 (hemispherial, Canolla), alignment `&` leak ×3 (622f08d7, 68c801bc, 6956d797).

## Code map (backend/app)
| Path | Role |
|---|---|
| `config.py` | env settings (`BOOT_IMPORT`, `BOOT_TRIAGE`, key, CORS, thresholds) |
| `models.py` / `db.py` | 11 tables, `UTCDateTime`, CHECKs from taxonomy, guard triggers; **SCHEMA_VERSION 2** (`auto_pending`; result inference/recommendation/review_reason) |
| `importer.py`, `sanitize.py`, `main.py`, `api/*` | Phase 2-3 (see API_SPECIFICATION) |
| `services/views.py`, `audit.py`, `revisions.py` | read models; hash chain; apply/rollback |
| `services/faculty_actions.py` | Phase 5: approve, reject, execute, rollback, duplicate, reply edit, dryrun validate |
| `services/triage_store.py` | run engine on DB records, persist results / proposed repairs / case statuses / audit |
| `triage/html_parse.py`, `record.py` | parser, canonical answers, history |
| `triage/complaints.py` | comment → class, claim, injection flag |
| `triage/detectors.py` | structural findings, near-miss spelling, foreign literals, chapter overlap |
| `triage/mathcheck.py` | safe evaluator, step checks, integer equation solving |
| `triage/answers.py` | key check (signals), claim placement, student correctness |
| `triage/engine.py` | class rules, `CONFIDENCE` (R-87), routing (R-88), replies + `reply_violations`, bonus |
| `triage/validators.py` | `validate_edit` (R-10..14), guards R-31/33/34/35 |
| `triage/output.py` | strict `ResultOut`/`BonusOut`, `validate_results`, deterministic writers |
| `scripts/run_triage.py`, `validate_results.py`, `import_data.py` | CLI |

## Frontend (`frontend/`, vanilla, no build)
| Path | Role |
|---|---|
| `index.html` | shell; no inline script (CSP) |
| `css/tokens.css` | 3-layer tokens (primitive → semantic → component), measured contrast, Inter @font-face |
| `css/app.css` | all components and layout; pages never restyle |
| `js/api.js` | the only backend client: base URL, request IDs, faculty key on writes only, ApiError, single read retry, error copy |
| `js/state.js` | **faculty key in memory only**; actor name in localStorage |
| `js/dom.js` | `h()` (textContent only), `setSafeHTML()` (the only HTML path; re-sanitises `*_html_safe`), formatters |
| `js/ui.js` | badges, confidence/urgency, toasts, native `<dialog>`, `runAction` (double-submit guard, 409 refresh), `writeButton` |
| `js/diff.js` | token LCS diff of find/replace as text; semantic answer diff |
| `js/router.js`, `js/app.js` | hash router, nav, status pills, shortcuts, `acadza:changed` refresh event |
| `js/views/*.js` | overview, queue, review, case (workspace + all action dialogs), quality, revisions, audit, settings |
| `assets/` | InterVariable.woff2 + OFL licence, favicon.svg |

Served by FastAPI at `/` (StaticFiles mounted after the routers) with `CONSOLE_CSP` (`backend/app/main.py`).

## API (`/api/v1`)
GET: health, taxonomy, settings, auth/status, dashboard, cases (+`auto_pending`), cases/{qid}, reports, reports/{rid}, questions/{qid}, …/history, …/revisions, revisions, audit, audit/verify, results, bonus-findings, triage/runs, openapi.json, reference.
POST/PUT (key): auth/verify, cases/{qid}/investigate, cases/{qid}/reopen, repairs/{id}/approve, repairs/{id}/reject, repairs/{id}/execute, revisions/{id}/rollback, reports/{id}/duplicate, reports/{id}/reply (PUT), validate-edit.

## Lessons (from failures)
1. **Never edit code or regexes through shell heredocs or sed.** Use the file tool, or a script written by it.
2. No `\uXXXX` in file-tool content; use code points. `test_source_hygiene.py` enforces this.
3. Option parser anchors on the last `(A)` followed by `(B)`.
4. Never give maths as tag-stripped text; linearise structurally.
5. `python -I` ignores `PYTHONIOENCODING`; use `-X utf8`.
6. Mutation-test every safety guard; assert iterated collections are non-empty.
7. Compute numbers in docs from real runs.
8. **Run each component over the whole dataset and read the output.** Every Phase 4 bug (tolerances, false inconsistencies, noisy spelling, dropped literal, misread claims, untruthful replies) was found that way.
9. Tolerances are domain decisions: options 0.2 %, integer claims exact.
10. A failed symbolic identity is not an error (equations ≠ identities).
11. Text field edits replace a substring (`find`), so compare-and-set and revision before/after must compute the full field value while checking exact match of `find`.
12. **Look at the screenshots.** "null" text, a desktop Menu button, a misleading green badge and timeline padding were all invisible to tests and obvious in an image.
13. Locate elements by accessible name in e2e tests (`get_by_role(..., name=)`), not by loose text: toasts linger, and cards mention other cards' IDs.
14. When a brief's claimed state differs from your memory, read the code and run the tests before building on either.

## Known issues / limits
- **Rules-only cannot judge physics or biology truth.** A wrong solution agreeing with a wrong key passes; recall disputes stay unverifiable.
- R034 is reached via self-contradiction, not physics (ADR-024).
- Spelling only catches typos with an in-record counterpart, or a word the comment names.
- Chapter check is lexical (prefix overlap), used only when a student complains.
- `solution_final` is advisory; contradiction requires the keyed value to be absent from all computed values.
- Audit append is single-writer. Case filtering is in memory. No failed-key rate limiting. Swagger UI uses a CDN. Starlette test-client deprecation warning.
- Postgres trigger DDL untested (T2.5).

- Console: there is no rendered "proposed" preview for HTML edits (raw HTML is not exposed; the diff is text). Complaint categories in the queue come from one `/reports?limit=200` page (enough for 44 reports). There is no persistent offline banner. A faculty-executed repair carries backend status/event `auto_applied` (labelled "Executed" in the UI).

## Next steps
1. (User) review the Phase 6 report and screenshots (`docs/screenshots/`).
2. (User) start Docker or provide a Postgres URL → T2.5 (deploy gate).
3. Phase 7+ only after review: integration pass, deployment (Render + persistent Postgres), screen recording.
