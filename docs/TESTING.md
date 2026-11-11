# Testing

Commands (once implemented):
```bash
pytest backend/tests -q                 # unit + integration + API (no network)
pytest backend/tests -q -m llm          # opt-in: live LLM smoke (needs key)
python scripts/validate_results.py      # results.json contract
npx playwright test                     # e2e against a local server (frontend/tests/e2e)
```
LLM calls are replaced in tests by a `FakeProvider` that returns recorded fixtures from `backend/tests/fixtures/llm/`. Tests never hit the network unless they are marked `llm`.

> **Status (Phase 4):** data-layer, sanitiser, API and rules-only engine tests exist and run (§8). Frontend/e2e tests and LLM-mode tests are still planned. The "Expected" column states the pass criteria. Results get recorded in §8 only after real runs.

## 1. Unit tests

| ID | Area | Case | Expected |
|---|---|---|---|
| T-U-01 | import | hashes match the committed values | import ok |
| T-U-02 | import | one byte changed in a temp copy | import aborts with `data_hash_mismatch` |
| T-U-03 | html_parse | options split for all 31 scq + 2 mcq | 4 options each, except `622f08d7` (3) |
| T-U-04 | html_parse | `695ee00b` "Assertion (A)" | exactly 4 options (regression for PROMPTS failure #2) |
| T-U-05 | html_parse | MathML linearise `68dea616` stem | contains `(n q)/(2 ε_0)` (regression for failure #3) |
| T-U-06 | html_parse | solution final value `60f744b3` | `50 V` |
| T-U-07 | detectors | blank_option on `68e87254` | option C empty |
| T-U-08 | detectors | duplicate_options on `6956d797` | B == C |
| T-U-09 | detectors | latex_leak on `63765a28` (question), `612151a6` (solution) | hits `\frac`, `\AA` (regression for failure #1) |
| T-U-10 | detectors | latex_leak on all 43, total | the known positives only, no others |
| T-U-11 | detectors | exam_tag on `617fa18e` | `(NEET 2019)` |
| T-U-12 | detectors | figure_ref_no_image on `622df25a` | hit |
| T-U-13 | detectors | answer_malformed on both mcq | hit. On 41 others: none. |
| T-U-14 | detectors | fixed_after_report, R017 vs `6208e80a` | hit (11-07 > 11-04) |
| T-U-15 | detectors | injection on R027 | flagged. On the 43 other comments: none. |
| T-U-16 | mathcheck | `(1/3)*0.09*400**2` | 4800 |
| T-U-17 | mathcheck | `__import__('os')`, `().__class__`, `9**9**9`, long input | rejected, no execution, time-bounded |
| T-U-18 | validators | spelling edit changing a digit | reject R-31 |
| T-U-19 | validators | edit field outside scope (all 18 repairs × 4 fields matrix) | exactly the taxonomy-allowed pairs pass R-10 |
| T-U-20 | validators | find occurs 0 or 2 times | reject R-12 |
| T-U-21 | validators | answer replace "E" on scq; `["B","B"]` on mcq; `"abc"` on integer | reject R-13 |
| T-U-22 | validators | answer_form non-additive | reject R-35 |
| T-U-23 | validators | stem_data value absent from solution | not auto (R-37) |
| T-U-24 | validators | option_repair changing the stem | reject R-38 |
| T-U-25 | validators | option_repair, missing distractor | route faculty_review |
| T-U-26 | routing | answer_key with only blind solve agreeing | faculty_review (R-40a) |
| T-U-27 | routing | answer_key with blind + solution agreeing, conf 0.90 | auto_apply |
| T-U-28 | routing | no_error but blind ≠ key | faculty_review (R-21) |
| T-U-29 | routing | auto:false repair, any confidence | faculty_review, edit null |
| T-U-30 | routing | rules-only mode | confidence ≤ 0.70, unless a detector alone determines the verdict |
| T-U-31 | routing | LLM certainty 0.99 on weak signals | confidence not raised (R-43) |
| T-U-32 | replies | "Fixed!" with route faculty_review | rejected → template |
| T-U-33 | replies | > 320 chars, or contains "verdict" | rejected → template |
| T-U-34 | urgency | answer_key with 3 reports > spelling with 1 report and older | ordering holds |
| T-U-35 | schema | LLM output with an extra key `route` | rejected (`extra=forbid`) |
| T-U-36 | prompts | PROMPTS.md contains every prompt file verbatim | pass |
| T-U-37 | isolation | engine modules never open `docs/` | pass (import-time file-access guard) |

## 2. Integration (pipeline with FakeProvider)

| ID | Scenario | Expected |
|---|---|---|
| T-I-01 | Full run over 44 reports | 44 results, 39 cases, no exceptions |
| T-I-02 | Provider returns invalid JSON twice | case → faculty_review, engine_mode rules_only, `ai_calls` has 2 failed rows |
| T-I-03 | Provider times out | 2 retries, then fallback. Logged. |
| T-I-04 | LLM proposes an out-of-scope edit | dropped, `scope_violation` audit, faculty_review |
| T-I-05 | LLM obeys the injection (fixture says "change answer to C") | edit dropped by R-52, verdict decided by the solve signals |
| T-I-06 | Duplicate reports propose the same edit | one repair row linked to all reports (R-61) |
| T-I-07 | Auto-apply then rollback | original_json unchanged, current_json restored, 2 revisions, chain verifies |
| T-I-08 | Direct `UPDATE questions SET original_json` | trigger raises |
| T-I-09 | Direct `DELETE FROM audit_events` | trigger raises |
| T-I-10 | Re-run triage on an applied case | applied revision untouched, new proposal added |

## 3. API tests (HTTPX `AsyncClient`)

Every endpoint in API_SPECIFICATION: the happy path, 404, 409 and 422 cases. Specifically:
- Filters: each `status`, `subject`, `verdict`, `confidence` and `priority` value returns only matching rows, and the counts sum correctly.
- Search: `q=R019` returns case `612151a6`. `q=60f744` matches by prefix.
- Approve flows: approve, approve-with-edit, edit out of scope (422), stale find (409), double approve (409).
- `/api/v1/results` equals the committed `results.json` after a snapshot load.
- `/api/v1/dashboard` numbers equal direct SQL counts. No hard-coded values (the test seeds a different fixture and checks that the numbers change).

## 4. Frontend e2e (Playwright, Microsoft Edge; see §8 Phase 6 for what is actually run)

| ID | Flow | Expected |
|---|---|---|
| T-E-01 | Load the dashboard | metrics match `/api/v1/dashboard`. No console errors. |
| T-E-02 | Click every sidebar link | each view renders a heading. No 404. |
| T-E-03 | Queue filters and search | row counts match the API. URL hash updates. Back restores. |
| T-E-04 | Open case `60f744b3` | MathML elements present (`math` count > 0). Verification panel shows 4 rows. |
| T-E-05 | Open `63765a28` | literal `\frac{7}{8}` visible in "Current". Not visible in "Proposed" preview. |
| T-E-06 | Approve a needs-review case | confirm modal shows the diff. After confirm, the toast appears and the audit has a `faculty_approved` row. |
| T-E-07 | Rollback | case back to Needs review. History shows `rolled_back`. |
| T-E-08 | Edit proposal with an invalid edit | inline rule IDs shown. Save disabled. |
| T-E-09 | Edit reply to "Fixed" on a review case | warning shown |
| T-E-10 | Keyboard only: `/`, `j`, `k`, `Enter`, `a`, `Esc` | all work. Focus is visible and returns to the row. |
| T-E-11 | Offline (`context.setOffline(true)`) | banner shown, actions disabled |
| T-E-12 | Every `<button>` on every view | has an accessible name and a handler (no-op detection via a click spy) |
| T-UI-07 | Contrast of token pairs | ≥ 4.5:1 (script computes from tokens.css) |

## 5. Safety tests

T-U-15, T-U-17, T-U-19, T-U-35, T-I-04, T-I-05, T-I-08 and T-I-09, plus:
- T-S-01: XSS. A question with `<img src=x onerror=alert(1)>` and `<script>` gets sanitised. Playwright asserts no dialog.
- T-S-02: SQL injection strings in `q` and in IDs are treated as literals (ORM-bound parameters).
- T-S-03: The frontend bundle contains no `LLM_API_KEY`, `sk-` or `api_key` (grep in CI).
- T-S-04: An oversized body (> 64 KB) gets 413.

## 6. AI evaluation (no ground truth, ADR-012)

`scripts/validate_results.py` checks the **contract**:
- 44 entries, unique `reportId`s, all reports covered, `questionId` matches reports.json.
- `verdict` ∈ taxonomy. `repair` ∈ taxonomy or null. `repair` non-null ⇔ verdict == defect.
- `route` ∈ the 3 values. `edit` null when the repair has no fields or the route is no_change.
- Every edit passes R-10 to R-14 against the original data.
- `confidence` ∈ [0, 1]. `evidence` non-empty and ≤ 200 chars. Reply 1–3 sentences and ≤ 320 chars.
- `auto_apply` entries satisfy R-30 (re-checked from the snapshot signals).

**Consistency report** (printed, not a pass/fail): verdict and route distribution, the low-confidence list, every disagreement between the blind solve and the key, and every injection flag. Each item on the low-confidence list is reviewed by a human before submission (TASK P8).

**Regression set:** LLM fixtures recorded from the first real run are frozen. Prompt changes re-run the FakeProvider suite plus a live diff of verdict changes, recorded in PROMPTS.md.

## 7. Dataset coverage

Every question type (scq/mcq/integer), every subject (Physics/Zoology/Botany), every verdict in the taxonomy, and at least one report per repair class present in the data are exercised by T-I-01, plus targeted unit tests on the specific records named above.

## 8. Results log

### 2026-11-10: Phase 2 (data layer)
Command: `.venv/Scripts/python -X utf8 -m pytest -rs` (Windows 11, Python 3.12.6, SQLAlchemy 2.0.57, SQLite)
Result: **68 passed, 7 skipped** in ~1.2 s. The 7 skipped are `test_pipeline_invariants[R…]` (Phase 4).

| Module | Tests | Covers |
|---|---|---|
| test_import.py | 9 | T-U-01, T-U-02, strict schema on all 43 + 44 records, schema drift, unknown FK, counts 43/44/39, verbatim round-trip, idempotency, 45 audit events + chain |
| test_db_guards.py | 10 | T-I-07, T-I-08, T-I-09: original immutable, no delete, audit + revisions append-only, apply/rollback, LIFO, stale-find conflict, questionType move, tamper detection |
| test_html_parse.py | 25 | whole-dataset parse (no tag remnants, every `<math>` parsed, mfrac/msqrt/msup structure kept), option counts, blanks/duplicates, failure #1/#2/#3 regressions, quantities, solution finals |
| test_record.py | 6 | answer issues only on the 4 known records, canonical forms, edge cases, history for every report (only R017) |
| test_regression_fixtures.py | 8 + 7 skipped | the 7 trap reports' record facts |
| test_no_reference_leak.py | 2 | static + runtime guard that the engine never touches docs/ |
| test_config.py | 5 | Postgres URL normalisation, SQLite default |

**Mutation checks** (manual; code restored after each):
- Option chain anchored on the first `(A)` → `test_assertion_marker_not_taken_as_option` fails.
- Fraction linearised as "a b" → 2 tests fail.
- Importer made to read `docs/DATA_DICTIONARY.md` → both leak tests fail.

**Not run:** PostgreSQL backend (`TEST_POSTGRES_URL`). The Docker daemon was unavailable (TASK T2.5).

### 2026-11-11: Phase 3 (API foundation)
Command: `.venv/Scripts/python -X utf8 -m pytest -p no:warnings` (Python 3.12.6, FastAPI 0.162.4, Starlette 1.10.0, nh3 0.3.7, SQLite)
Result: **212 passed, 7 skipped** (219 collected) in ~11 s. The 7 skipped are still `test_pipeline_invariants[R…]` (Phase 4), skipped explicitly and **not** counted as passed.

| Module | Tests | Covers |
|---|---|---|
| test_api_read.py | 48 | every read endpoint; numbers recomputed from source files; filters checked exactly against the unfiltered list; search; stable pagination; invalid query params (422); bad and unknown IDs (422/404); every one of the 43 questions renders with options = parser output, no script/onerror/javascript:, `<math>` count preserved; history; revisions after apply/rollback; audit filters; UTC timestamps; exact urgency breakdown with a fixed clock; dashboard reacts to state changes (proves metrics aren't hard-coded) |
| test_api_auth.py | 42 | OpenAPI-schema walk proves every write op is on the protected router; read router is GET-only and keyless; 401 (+WWW-Authenticate) / 403 (5 near-miss keys) / 503 (unset, empty, short key) for every write; auth before body validation; investigate/reopen cycle + audit + 409s; 422 bodies without echo; key absent from responses, headers and logs; SecretStr repr; CORS allowed/denied/default; wildcard rejected |
| test_sanitize.py | 38 | 26 XSS payloads; safe img kept without handlers; malformed HTML balanced; formatting and MathML attributes kept; **all 43 records: identical readable text + `<math>` count after sanitising**; every option survives; stray-`<mspace>` regression on 3 records |
| test_api_errors.py | 15 | envelope shape + request id for 404/405/401/422; unversioned 404; list shape; security headers; request-id echo/replace; 413; DB failure (dropped table) → 503 without details; unhandled error → 500 without leak; empty dataset across all reads; idempotent boot import; OpenAPI paths versioned |
| test_source_hygiene.py | 1 | no control/invisible characters in code or docs |
| (Phase 2 modules) | 75 | unchanged, all passing after the UTC change |

**Mutation checks (code restored after each):**
- Remove the stray-MathML unwrap → 5 tests fail (all-records text check, 3 regressions, render-all-questions).
- Move `/auth/verify` onto the public router → 5 auth tests fail (schema walk, router check, 401/403 cases).
- Append a backspace to a test file → the hygiene test fails.

**Real-process smoke test** (uvicorn subprocess, env-supplied `FACULTY_ACCESS_KEY`, temp SQLite file, real HTTP): health 200 with 43/44/39; dashboard metrics; queue; R027 comment returned as data; options of 68c9ae5a all present after sanitising; auth/verify 401 → 403 → 200; investigate 200 + audit chain ok (46 events); `/api/v1/reference` 200; the key absent from server output.

### 2026-11-11: Phase 4 (rules-only triage engine)
Command: `.venv/Scripts/python -X utf8 -m pytest -p no:warnings` (same environment as Phase 3)
Result: **303 passed, 0 skipped** (303 collected) in ~18 s. The 7 formerly skipped `test_pipeline_invariants[R…]` tests are now implemented and pass against the real engine.

| Module | Tests | Covers |
|---|---|---|
| test_engine.py | 65 | each of 44 reports processed exactly once; all 43 questions inspected; determinism (incl. reversed input order); committed files == fresh run; no report or question ID literals in engine code; strict contract rejects 13 kinds of violation; taxonomy-only output; edit scope; auto-apply only for mechanical repairs; answer-key changes never auto-apply; every decision explains itself; nothing applied; **generality**: fixing or breaking a key (scq + integer) flips the verdict; removing an option / complete options; blank keyed option; malformed mcq keys; history after vs before the report; 3 injection texts on a correct and on a defective question; injection text absent from output; low confidence never closes; ambiguous values go to faculty; unsafe evaluator input (8 attacks); no false arithmetic inconsistencies on 43 solutions; spelling detector finds exactly the 4 real typos; complaint classes; claim extraction |
| test_regression_fixtures.py | 22 | record facts (7) + **pipeline invariants (7, formerly skipped)** + mandatory outcomes for R004, R005, R017, R027, R034, R009, R010 (7) + presence check |
| test_api_triage.py | 12 | `/results` == results.json; `/bonus-findings` == bonus file; runs listed; dashboard consistent with results; case status follows routes; evidence/inference/recommendation exposed; one repair for three duplicate reports; **nothing applied** (0 revisions, originals == current); re-run keeps a human status and supersedes proposals; triage audited; injection flag persisted; `auto_pending` filter; Phase 3 response shapes unchanged |
| test_no_reference_leak.py | 2 | now also covers engine run, results validation, bonus scan and DB persistence |
| (Phase 2-3 modules) | 202 | unchanged and passing; Phase 3 API fixtures pass `boot_triage=False` explicitly so they keep checking the pre-triage contract |

**Contract script:** `python scripts/validate_results.py` → `OK: 44 results, 7 bonus findings, all contract checks passed`.
**Determinism:** two consecutive `run_triage.py` runs produce byte-identical `results.json`, `bonus_findings.json` and `triage_snapshot.json` (sha256 compared).

**Mutation checks** (`mutate_p4.py`; code restored after each, then the full suite re-run green):

| Mutation | First failing test |
|---|---|
| key check treats a contradicted key as supported | `test_mandatory_outcomes[R004]` |
| routing ignores the R-40 forced review | `test_committed_files_are_real_engine_output` |
| history check disabled | `test_pipeline_invariants[R017]` |
| injection flag dropped | `test_pipeline_invariants[R027]` |

**Known warning:** Starlette 1.10 emits `StarletteDeprecationWarning: Using httpx with starlette.testclient is deprecated; install httpx2`. It is test-only and harmless today, and is tracked in MEMORY → Known issues.

### 2026-11-11: Phase 5 (faculty review & safe repair execution)
Command: `.venv/Scripts/python -X utf8 -m pytest -p no:warnings` (same environment as Phase 3 & 4)
Result: **453 passed, 0 skipped** (453 collected) in ~45 s.

| Module | Tests | Covers |
|---|---|---|
| test_api_phase5.py | 87 | Missing/wrong faculty key (401/403) across all 7 new endpoints; 404 on unknown IDs; approve → execute happy path with preview; execute without prior approval (409); double approve (409); double execute (409); approve rejected repair (409); answer-key changes never auto-applied; R-10..R-14 edit validation failures (422); stale find on execute (compare-and-set 409); rollback lifecycle (restore before-value, LIFO, no deleted history); duplicate rollback (409); audit events carry before/after, actor, timestamp; audit chain verification after every operation; original_json immutability check across all questions; validate-edit dry-run endpoint (happy, scope violation, not in text, unknown repair, 404); prompt injection in edits rejected; XSS / malicious HTML in replies rejected; reply length & forbidden claims validation (R-70..R-73); mark duplicate happy & edge cases (R-63); 503 writes_disabled when key unset; case status transitions (approved, rejected); faculty key leak prevention |
| test_api_auth.py | 105 | Updated with the 7 new write endpoints (schema walk, 401/403/503 matrices) |
| (Phase 2-4 modules) | 261 | unchanged and all passing |

**Contract script:** `python scripts/validate_results.py` → `OK: 44 results, 7 bonus findings, all contract checks passed`.

### 2026-11-11: Phase 6 (faculty console)
Command: `.venv/Scripts/python -X utf8 -m pytest -p no:warnings` (Python 3.12.6, Playwright for Python driving installed **Microsoft Edge**, headless)
Result: **509 passed, 0 skipped** in ~133 s: 453 backend (unchanged) + **56 browser tests** in `backend/tests/test_console_e2e.py`. If Playwright or Edge is missing, the e2e module skips with the reason shown.

The e2e tests start real uvicorn against a temp SQLite DB that was imported, triaged, and seeded with one extra **malicious report** (`<img onerror>` + `<script>`).

| Area | Tests |
|---|---|
| Screens | all 8 render with no console errors, page errors, native dialogs or HTTP ≥ 400 responses; exactly one active nav item |
| Data | Overview metrics equal `/dashboard`; queue counts equal `/cases` for status, search (R019), subject and sort |
| Keyboard | `j` + `Enter` opens a case |
| Content safety | MathML present in the MathML namespace; the malicious comment is shown as literal text, nothing executes, no `img[onerror]`/`script` in `main` |
| Auth | read-only without a key (buttons disabled with the reason); wrong key → rejected and cleared; valid key verified, absent from storage, URL and DOM, forgotten on reload; no key in frontend source |
| Workflows | answer-key: approve needs explicit "independently verified" → approval changes nothing → separate execute → rollback restores, audit chain ok; reject needs a reason; edit proposal must re-validate after every change (R-31 rejection shown) before approval, and is not executed; 409 conflict shows the server message and refreshes to the true state; investigate → reopen restores status; reply edit rejected by the server for a false "fixed" (R-71) then saved; mark duplicate |
| Error states | intercepted 401 / 413 / 503 `writes_disabled` show the right message and request ID; writes-disabled server disables buttons; failed read shows Retry, which works |
| Responsive | no horizontal overflow on 5 screens × 5 viewports (1440, 1280, 1024, 768, 390); mobile menu opens the sidebar and navigates |

**Mutation checks** (`mutate_p6.py`, code restored afterwards):

| Mutation | Result |
|---|---|
| Render the student comment with `innerHTML` | caught by `test_malicious_student_comment_is_inert_text` |
| Remove the answer-key "independently verified" gate | caught by `test_answer_key_approve_execute_rollback_are_separate` |

**Bugs found by these tests or by screenshot review and fixed:**
- 171 px horizontal overflow at 390 px (segmented control);
- "Menu" button visible on desktop (CSS specificity);
- a literal "null" rendered under options;
- a green "stored key" badge on a key the engine says is wrong;
- revision timeline padding.

### 2026-11-11: Phase 7 (system integration, QA & security audit)
Command: `.venv/Scripts/python -X utf8 -m pytest backend/tests -q -p no:warnings` and `backend/tests/verify_phase7.py`
Result: **509 passed, 0 skipped** across all test suites (453 backend unit/integration/API + 56 Playwright Edge browser E2E tests).

**1. Benchmark & Performance Measurements:**
Measured over 5 runs per endpoint (warm server, local SQLite):

| Route / Asset | Min (ms) | Avg (ms) | Max (ms) | Status |
|---|---|---|---|---|
| `GET /api/v1/health` | 3.7 | 4.3 | 5.0 | 200 OK |
| `GET /api/v1/dashboard` | 44.7 | 45.8 | 47.2 | 200 OK |
| `GET /api/v1/cases?limit=50` | 42.7 | 44.3 | 46.0 | 200 OK |
| `GET /api/v1/cases?status=needs_review` | 42.3 | 43.7 | 46.0 | 200 OK |
| `GET /api/v1/cases/60f744b3f1b9bc7cc7b4a949` | 44.9 | 50.2 | 58.6 | 200 OK |
| `GET /api/v1/reports` | 9.5 | 10.7 | 13.0 | 200 OK |
| `GET /api/v1/reports/R004` | 5.8 | 6.8 | 7.7 | 200 OK |
| `GET /api/v1/questions/60f744b3f1b9bc7cc7b4a949` | 5.1 | 5.4 | 6.2 | 200 OK |
| `GET /api/v1/audit?limit=50` | 5.8 | 6.9 | 9.0 | 200 OK |
| `GET /api/v1/audit/verify` | 7.8 | 8.8 | 10.6 | 200 OK |
| `GET /api/v1/results` | 5.6 | 6.0 | 6.7 | 200 OK |
| `GET /api/v1/bonus-findings` | 69.9 | 72.8 | 77.2 | 200 OK |
| `GET /` (index.html) | 4.3 | 5.0 | 5.5 | 200 OK |
| `GET /css/tokens.css` | 4.1 | 4.7 | 5.8 | 200 OK |
| `GET /css/app.css` | 4.7 | 7.7 | 18.9 | 200 OK |
| `GET /js/app.js` | 4.2 | 4.9 | 5.5 | 200 OK |

**2. Data Integrity Verification:**
- 43 imported questions remain byte-for-byte identical to source `data/questions.json`.
- 44 reports accounted for and linked to 39 cases.
- `results.json` contains exactly 44 entries and matches the committed schema.
- `bonus_findings.json` contains exactly 7 verified/suspected findings.
- Audit chain integrity verified (`verify_audit` ok = True, 0 broken hashes).
- Idempotency verified: re-running `import_data.py` or re-running startup boot sequence causes no duplicate records.

**3. Database Verification & SQLite Architecture:**
- **Default Database:** SQLite (`acadza.db`) is the default and existing database. Triggers, constraints, transactions, and audit hashing were verified natively on SQLite.
- **Data Integrity:** All 43 questions remain byte-identical to source `data/questions.json`. All 44 reports are accounted for.

---

### Phase Status & Test Suite Summary

> **Current Status (2026-11-12): Phase 0–7 Complete. Phase 8 has NOT started.**
> *(Note: The test statistics below reflect the verified results from Phase 7 integration testing. No test suites were executed during this documentation audit.)*

1. **Verified Test Suite Breakdown (509 total tests):**
   - **Backend Tests (453 tests):** Covers API authentication (`test_api_auth.py`), RFC 7807 error envelopes (`test_api_errors.py`), faculty review and execution actions (`test_api_phase5.py`), read endpoints and filtering (`test_api_read.py`), triage runs (`test_api_triage.py`), configuration (`test_config.py`), database triggers and immutability guards (`test_db_guards.py`), rules engine and math verification (`test_engine.py`), MathML parser (`test_html_parse.py`), idempotent importer (`test_import.py`), regression fixtures (`test_regression_fixtures.py`), and HTML/MathML sanitization (`test_sanitize.py`).
   - **Browser E2E Tests (56 tests):** Executed in Microsoft Edge via Playwright (`test_console_e2e.py`). Verifies all 8 console screens, responsive layout, drawer interactions, in-memory key lifecycle, diff rendering, and execution/rollback workflows.
   - **Contract Validation:** `scripts/validate_results.py` validates `results.json` (44 entries) and `bonus_findings.json` (7 findings).

2. **Test Isolation & Gemini API Separation:**
   - **Offline Determinism:** Pytest backend tests run completely offline without external network dependencies. LLM calls in tests are decoupled, running against recorded fixtures, rules engine checks, or test database instances.
   - **Live Gemini Verification:** Live Gemini API calls (via `LLM_PROVIDER=gemini`) require network connectivity and an active API key; they are tested independently as operational verification and are not part of the standard offline unit test run.

3. **Planned Phase 8 (Not Started):**
   - Phase 8 is reserved for formal end-to-end regression testing, stress-testing under load, and final QA sign-off prior to production deployment.

