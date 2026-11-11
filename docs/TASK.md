# TASK: Development Roadmap

Legend: priority **P0** = blocks submission, **P1** = judged heavily, **P2** = polish. A task is checked only when it has been implemented **and** verified as its acceptance criterion says.

## Phase 0: Inspection and requirements

| ✓ | ID | Task | Pri | Deps | Acceptance | Status |
|---|---|---|---|---|---|---|
| [x] | T0.1 | Extract the ZIP into an isolated dir. List the files. | P0 | — | 4 files found | done 2026-11-10 |
| [x] | T0.2 | Inspect the schemas of all 3 JSON files and the README | P0 | T0.1 | DATA_DICTIONARY §1–3 written from actual data | done |
| [x] | T0.3 | Read every question and report (readable dump plus raw HTML where ambiguous) | P0 | T0.2 | DATA_DICTIONARY §4.1 covers all 44 reports | done |
| [x] | T0.4 | Scan for unreported defects | P1 | T0.3 | DATA_DICTIONARY §4.2 | done (manual + scan; scanner bug found, see PROMPTS C1) |
| [x] | T0.5 | Copy the data into the project. Record SHA-256. | P0 | T0.1 | hashes in DATA_DICTIONARY | done |

## Phase 1: Documentation and architecture

| ✓ | ID | Task | Pri | Deps | Acceptance | Status |
|---|---|---|---|---|---|---|
| [x] | T1.1 | RULES.md | P0 | T0.3 | every taxonomy repair has a scope and guard rule | done |
| [x] | T1.2 | SYSTEM_ARCHITECTURE.md with Mermaid | P0 | T1.1 | pipeline, lifecycle, fallback diagrams | done |
| [x] | T1.3 | PRD, DESIGN, AI_ENGINE, API, DB, TESTING, SECURITY, DEPLOYMENT, DECISIONS | P0 | T1.2 | files exist, cross-references resolve | done |
| [x] | T1.4 | Root files: README, PROMPTS, PRODUCT, CHANGELOG, CONTRIBUTING, .env.example, .gitignore | P0 | T1.3 | present | done |
| [x] | T1.5 | Resolve open questions with the user | P0 | T1.4 | each answered or default accepted | done 2026-11-10: project decisions 1–6 (see Open questions) |

## Phase 2: Data ingestion (done 2026-11-10, except T2.5)

| ✓ | ID | Task | Pri | Deps | Acceptance | Status |
|---|---|---|---|---|---|---|
| [x] | T2.1 | `config.py`, `models.py`, `db.py`: taxonomy CHECKs, guard triggers (SQLite + Postgres DDL) | P0 | T1.5 | T-I-08, T-I-09 pass on SQLite | done (`test_db_guards.py`) |
| [x] | T2.2 | `importer.py` + `scripts/import_data.py`: hash check, strict schema, idempotent, audited | P0 | T2.1 | T-U-01/02; 43 / 44 / 39; 45 audit events, chain ok | done (`test_import.py`; CLI run twice: imported, then already_imported) |
| [x] | T2.3 | `html_parse.py`: structural MathML, option split, LaTeX detection, quantities | P0 | T2.2 | all 43 records parse; T-U-03 to T-U-06 + failure regressions | done (`test_html_parse.py`, verified by 2 mutation runs) |
| [x] | T2.4 | `record.py`: canonical answers (mcq list), answer issues, `history_after` | P0 | T2.3 | issues only on the 4 known records; history only for R017 | done (`test_record.py`) |
| [ ] | T2.5 | Run the DB test suite on real PostgreSQL | P0 | T2.1 | `TEST_POSTGRES_URL=… pytest` green | **blocked**: Docker daemon not running; not yet executed. **Hard gate for T9.2 (production deploy).** |
| [x] | T2.6 | Regression fixtures R004, R005, R017, R027, R034, R009, R010 | P0 | T2.4 | record facts pass; pipeline invariants stored | done (record part); invariants run from T4.5 |
| [x] | T2.7 | Reference-notes leak guard (static + runtime file-open spy) | P0 | T2.2 | both fail when the importer is made to read the notes | done (`test_no_reference_leak.py`, mutation-verified) |
| [x] | T2.8 | `services/audit.py` hash chain + `services/revisions.py` apply/rollback (integrity layer only) | P0 | T2.1 | apply → rollback restores, original untouched, LIFO, append-only | done (`test_db_guards.py`) |

## Phase 3: Backend foundation (done 2026-11-11)

| ✓ | ID | Task | Pri | Deps | Acceptance | Status |
|---|---|---|---|---|---|---|
| [x] | T3.1 | `main.py` app factory, lifespan, env settings, error envelope, JSON logging, CORS, `/api/v1` | P0 | T2.1 | health 200; envelope + request id on every error | done (`test_api_errors.py`; real uvicorn smoke run) |
| [x] | T3.2 | Sanitiser (nh3 allowlist, MathML) | P0 | T3.1 | 26 XSS payloads neutralised; text + MathML identical on all 43 records | done (`test_sanitize.py`; found + fixed the stray-`<mspace>` content loss) |
| [x] | T3.3 | Read endpoints: health, taxonomy, settings, dashboard, cases, case, reports, report, question, history, revisions | P0 | T3.2 | values recomputed from source data in tests; invalid IDs 422, unknown 404; empty DB safe | done (`test_api_read.py`, `test_api_errors.py`) |
| [x] | T3.4 | `/audit`, `/audit/verify` | P0 | T2.8 | filters, order, chain verify | done |
| [x] | T3.5 | Urgency (R-90), computed on read | P1 | T3.3 | exact breakdown with a fixed clock | done (`test_urgency_breakdown_is_exact`) |
| [x] | T3.6 | Faculty key auth on every write endpoint, fail closed (R-85) | P0 | T3.1 | 401/403/503; schema-walk proves full coverage; key absent from responses and logs | done (`test_api_auth.py`, mutation-verified) |
| [x] | T3.7 | Minimal write endpoints to exercise auth: `auth/verify`, `cases/{id}/investigate`, `cases/{id}/reopen` | P1 | T3.6 | audited; 409 on illegal transitions | done |

## Phase 4: Triage engine (rules-only shipped 2026-11-11; LLM provider still to do)

| ✓ | ID | Task | Pri | Deps | Acceptance | Status |
|---|---|---|---|---|---|---|
| [x] | T4.1 | Detectors (`triage/detectors.py`) | P0 | T2.3 | structural facts on all 43 records; spelling detector finds exactly the 4 real typos; no false arithmetic inconsistencies | done |
| [x] | T4.2 | `mathcheck.py`: safe evaluator, step checks, integer equation solving | P0 | — | rejects unsafe input; R005 → {1}, R016 → {20} | done |
| [ ] | T4.3 | Provider interface: `none` (rules-only, **default**), `openai_compat` (Gemini etc.), `anthropic`; retries, fallback, `ai_calls` logging | P1 | T3.1 | T-I-02, T-I-03; results labelled (R-86) | todo (rules-only shipped first, ADR-017) |
| [ ] | T4.4 | Prompt files v1 plus loader with sha256. PROMPTS.md sync test. | P1 | T4.3 | T-U-36 | todo |
| [x] | T4.5 | Rules-only pipeline (`triage/engine.py`): complaints, key check, class rules, calibration, routing, replies | P0 | T4.1, T4.2 | 44 decisions; mandatory outcomes; generality mutation tests | done |
| [x] | T4.6 | `scripts/run_triage.py` → results.json + snapshot; `scripts/validate_results.py` | P0 | T4.5 | 44 entries, README schema only, deterministic bytes | done |
| [x] | T4.7 | `bonus_findings.json` (verified vs suspected) | P1 | T4.1 | generated by detectors over all 43 questions, not from reference notes | done (7 findings; via `run_triage.py` and `GET /bonus-findings`) |
| [x] | T4.8 | Enable regression invariants (`test_pipeline_invariants`) | P0 | T4.5 | 7 fixtures pass | done (7 passed, 0 skipped) |
| [x] | T4.9 | Persist triage (`services/triage_store.py`), boot triage, `/results`, `/bonus-findings`, `/triage/runs` | P0 | T4.5 | `/results` == results.json; nothing applied; human statuses kept on re-run | done |

## Phase 5: Faculty review, approval and safe repair execution (done 2026-11-11)

| ✓ | ID | Task | Pri | Deps | Acceptance | Status |
|---|---|---|---|---|---|---|
| [x] | T5.1 | Scope, find-once, answer validity (R-10 to R-14) | P0 | T2.3 | T-U-19 to T-U-21, API dry-run + pre-execution validation | done (`services/faculty_actions.py`, `POST /validate-edit`) |
| [x] | T5.2 | Repair guards R-31 to R-42 | P0 | T5.1 | T-U-18, T-U-22 to T-U-25, faculty-approval structural checks | done (`triage/validators.py`, `faculty_actions.py`) |
| [x] | T5.3 | Calibration and routing (R-21, R-30, R-43, R-44) | P0 | T5.2 | T-U-26 to T-U-31; auto-eligible repairs require explicit faculty approval to execute | done |
| [x] | T5.4 | Injection rules R-50 to R-54 | P0 | T4.1 | T-I-05; faculty-edit prompt injection + XSS rejected | done (`faculty_actions._check_injection`) |
| [x] | T5.5 | Reply checks and templates (R-70 to R-73) | P1 | T5.3 | T-U-32, T-U-33, PUT /reports/{id}/reply validated & audited | done (`PUT /reports/{id}/reply`) |
| [x] | T5.6 | Actions endpoints: approve, reject, execute, rollback, duplicate, reply | P0 | T5.1, T3.4, T3.6 | 87 tests in `test_api_phase5.py`; 453 total tests passing | done (`POST /repairs/{id}/approve`, `reject`, `execute`, `POST /revisions/{id}/rollback`, `POST /reports/{id}/duplicate`, `PUT /reports/{id}/reply`, `POST /validate-edit`) |

## Phase 6: Faculty console frontend (done 2026-11-11)

| ✓ | ID | Task | Pri | Deps | Acceptance | Status |
|---|---|---|---|---|---|---|
| [x] | T6.1 | Design system: DESIGN.md rev 2, `tokens.css` (3 layers, measured contrast), `app.css` components, Inter self-hosted | P1 | — | contrast measured; §11 audit | done |
| [x] | T6.2 | Shell: sidebar, hash router, API client, toasts, dialogs, status pills, keyboard | P0 | T6.1 | every route renders without console errors (e2e) | done |
| [x] | T6.3 | Overview | P1 | T3.3 | numbers equal `/dashboard` (e2e) | done |
| [x] | T6.4 | Report Queue: filters, search, sort, pagination, complaint category | P0 | T3.3 | counts equal `/cases` (e2e) | done |
| [x] | T6.5 | Question Review Workspace: question + MathML, analysis, evidence, limits, reports, diff, revisions, audit | P0 | T6.4 | MathML namespace check; malicious comment inert (e2e) | done |
| [x] | T6.6 | Actions: approve (answer-key confirmation), edit → validate → approve, reject (reason), execute, rollback, investigate, reopen, duplicate, reply | P0 | T5.6 | separate approve/execute/rollback; 409 refresh; R-71 enforced (e2e) | done |
| [x] | T6.7 | Faculty Review, Quality Audit, Revision History, Audit Logs, Settings (in-memory key) | P1 | T3.4 | key never stored (e2e) | done |
| [x] | T6.8 | Serve the console from FastAPI at `/` with a strict CSP | P0 | T6.2 | backend suite unchanged and green | done |
| [x] | T6.9 | Browser tests (Playwright + Edge) and responsive checks at 5 viewports | P0 | T6.6 | 56 e2e passed | done |

## Phase 7: Integration and QA (done 2026-11-11)
| [x] | T7.1 | End-to-end: import → triage → console → approve → rollback → results export | P0 | P4–P6 | manual walkthrough + 509 tests green (453 pytest + 56 Playwright) | done |
| [x] | T7.2 | Security audit: auth, headers, CSP, sanitization, prompt injection, audit verification | P0 | T7.1 | verified via test suite & verify_phase7.py | done |
| [x] | T7.3 | Performance benchmarks: latency measurements across all routes (<55ms API, <10ms static) | P1 | T7.1 | benchmarks recorded in TESTING.md | done |
| [x] | T7.4 | Data integrity verification: 43 original questions, 44 reports, results.json, bonus_findings | P0 | T7.1 | all invariants confirmed | done |

## Phase 8: Testing and QA (planned — NOT started)
| [ ] | T8.1 | Full pytest + Playwright regression run | P0 | T7.1 | planned | todo |
| [ ] | T8.2 | Final human review sign-off of low-confidence and auto-apply cases | P0 | T4.6 | planned | todo |
| [ ] | T8.3 | Final deliverables contract validation | P0 | T4.6 | planned | todo |

## Phase 9: Deployment
| [x] | T9.1 | `render.yaml`, requirements pinned, `.gitattributes` | P0 | T7.1 | verified & tested | done |
| [ ] | T9.2 | Deploy and run DEPLOYMENT §6 checks on Render | P0 | T9.1 | planned | todo |

## Phase 10: Submission
| [ ] | T10.1 | Finalise PROMPTS.md (real runs, version history, failures) | P0 | T8.2 | no draft markers left | todo |
| [x] | T10.2 | PRODUCT.md final review (≤ 1 page) | P0 | — | verified: 14 lines / 320 words, strictly ≤ 1 page | done |
| [ ] | T10.3 | Docs reconciled with code (every claim checked) | P0 | all | checklist in MEMORY | todo |
| [ ] | T10.4 | 3-min screen recording (user) | P0 | T9.2 | link in README | **user task** |

---

## Open questions

Resolved by project decisions:

| ID | Resolution |
|---|---|
| Q-1 | Metadata/syllabus problems are `defect` only via the taxonomy's `wrong_chapter` / `syllabus`; always faculty_review (R-23). |
| Q-2 | `results.json` edits are single `{field, find, replace}` or null. mcq answers are normalised to lists internally. Multi-field fixes go to faculty_review with edit null (R-14, ADR-008). |
| Q-3 | SQLite is the primary, default, and existing database (`acadza.db`); no MySQL or PostgreSQL migration. |
| Q-4 | Server-side faculty key on all writes; reads public (R-85, ADR-016). |
| Q-5 | Google Gemini API integration configured (`gemini-1.5-flash`), with deterministic rules-engine fallback (`rules-v1`). |
| Q-10 | Separate `bonus_findings.json`, verified vs suspected (R-95, ADR-018). |
| Q-13 | Resolved: SQLite is the existing database; external PostgreSQL container testing is eliminated. |

Still open; the default applies unless the user says otherwise:

| ID | Question | Default |
|---|---|---|
| Q-6 | R021 (`["","B"]`, only B correct): type_mismatch or answer_key format repair? | Pipeline decides via R-41. A type change is multi-field, so faculty_review under R-14. |
| Q-7 | One-word "wrong" on a correct question: no_error or not_actionable? | no_error if a check was possible and passed |
| Q-8 | Duplicate reports on one auto-applied fix: same route for all? | yes (R-61) |
| Q-9 | R034: unsound or solution_fix? | pipeline decides; both faculty |
| Q-11 | Auto-fill a blank **keyed** option grounded in the solution (R011)? | yes, only when grounded (R-38). Note: in rules-only mode the confidence cap prevents it anyway. |
| Q-12 | Inserted values: plain text or MathML? | plain text |
| Q-13 | Start Docker Desktop (or provide a Postgres URL) so T2.5 can run? | needs the user |
