# Architecture Decision Records

Format: Context → Options → Decision → Rejected because → Trade-offs → Consequences.

---

## ADR-001: One FastAPI service serves API and static frontend
- **Context:** The brief requires a live URL that stays up 7 days on a free tier, a vanilla frontend and a FastAPI backend.
- **Options:** (a) FastAPI + separate static host (Netlify), (b) FastAPI `StaticFiles` mount, (c) Nginx container.
- **Decision:** (b).
- **Rejected:** (a) two deploys to keep alive, plus CORS and two URLs in the README. (c) more ops for no gain.
- **Trade-offs:** static assets aren't CDN-cached. That is irrelevant at faculty scale.
- **Consequences:** same-origin, so CORS is locked down in prod. Frontend and backend stay separate folders that talk only through `/api`.

## ADR-002: Multi-stage pipeline instead of one prompt
- **Context:** Students are often wrong. The key is sometimes wrong. Sometimes both (R004).
- **Options:** single prompt; prompt + self-critique; blind solve + triage + deterministic guards.
- **Decision:** blind solve (no key or comments) → triage → code validation → reply.
- **Rejected:** a single prompt anchors on the key or on the student and can't independently verify. Self-critique uses the same anchored context.
- **Trade-offs:** about 3 calls per case instead of 1.
- **Consequences:** answer_key auto-apply is possible *safely* (R-40).

## ADR-003: Backend computes route and confidence
- **Context:** The taxonomy says auto:false repairs "may suggest, never write".
- **Decision:** The LLM output schema has no `route`. `routing.py` derives it. Confidence comes from a signal table (RULES R-43).
- **Rejected:** model-reported confidence. It is uncalibrated and can be manipulated by injected text.
- **Consequences:** the policy is testable without an LLM. Changing thresholds is a config change.

## ADR-004: Vanilla SPA with hash routing, one `index.html`
- **Context:** The brief bans frameworks and suggests `frontend/pages/`.
- **Options:** multi-page HTML files; a single page with ES module views.
- **Decision:** single `index.html`, `js/router.js` (hash-based), one module per view.
- **Rejected:** multi-page. The drawer-over-queue workflow and keyboard navigation need persistent state across views, and separate pages would reload the queue.
- **Consequences:** no build step. Deep links work (`#/case/60f744b3…`).

## ADR-005: No KaTeX; native MathML only
- **Context:** Stored math is MathML. LaTeX appears only as *defects* (`\frac`, `\AA`).
- **Decision:** render MathML natively. Show leaked LaTeX as text.
- **Rejected:** KaTeX. It would "fix" the display of a broken record and hide the defect from the reviewer. It is also an extra dependency.
- **Consequences:** a markup_leak diff shows exactly what students see.

## ADR-006: Thin httpx provider adapters, no vendor SDKs
- **Decision:** two ~40-line adapters (Anthropic Messages, OpenAI-compatible chat) over `httpx`, which is already needed for tests.
- **Rejected:** LangChain (heavy, hides prompts) and vendor SDKs (two more dependencies for one POST each).
- **Trade-offs:** we handle retries and backoff ourselves (about 20 lines).
- **Consequences:** prompts are fully visible and logged. Swapping provider is an env change.

## ADR-007: Case = all reports on one `questionId`
- **Context:** 44 reports on 39 questions. `qid` is not unique (`SecAQ14` × 3), so it can't be used.
- **Decision:** group by `_id`. Per-report verdicts live inside the case. Identical edits are deduped into one repair (R-61).
- **Rejected:** a cross-question similarity merge. No such duplicates exist in the data, so it is speculative. It is noted in the roadmap.
- **Consequences:** LLM cost scales with broken questions.

## ADR-008: Edit format (revised 2026-11-10, project decision 2)
- **Context:** The README defines `{field, find, replace}`. mcq answers are lists, and both stored mcq answers are malformed. `type_mismatch` can span 3 fields.
- **Decision:**
  - `results.json` only ever contains a single `{field, find, replace}` object or `null`.
  - Answer edits put the value **exactly as stored** in `find` and the **canonical** value in `replace` (mcq: a sorted list of letters).
  - Multi-correct answers are normalised internally by `canonical_answer`.
  - A fix needing several fields is **not** forced into the README shape. It goes to `faculty_review` with `edit: null`, and the internal multi-field proposal lives in `repairs.edit` (RULES R-14).
- **Rejected:**
  - A list of edits in `results.json` (my first draft). It is incompatible with the README schema the scorer reads.
  - Emitting only the "main" field of a multi-field fix. That would describe a partial change as if it were the whole fix.
- **Trade-off:** a true multi-field fix (for example mcq→scq) can never auto-apply. That is acceptable, because such fixes are rare and high-stakes.

## ADR-009: Originals immutable; working copy plus revisions
- **Decision:** `questions.original_json` is protected by a DB trigger against UPDATE. Edits go to `current_json` with a `question_revisions` row (before, after, repair, actor).
- **Rejected:** editing in place with an audit log only. That makes rollback reconstruction-based and error-prone.
- **Consequences:** rollback is a new revision. `/data` files are never written.

## ADR-010: No repository layer
- **Decision:** services use the SQLAlchemy session directly.
- **Rejected:** a `repositories/` package. It would be a second abstraction over an ORM with one implementation and add indirection with no benefit at this size.
- **Consequences:** fewer files. If a second datastore ever appears, extract it then.

## ADR-011: Demo boots from a committed triage snapshot
- **Context:** LLM credits may run out during the 7-day live window. Render free disks are ephemeral.
- **Decision:** `run_triage.py` writes `results.json` (README schema only) **and** `artifacts/triage_snapshot.json` (the internal superset). An empty DB on boot imports the data and then the snapshot. The console says "Loaded precomputed results from <date>", as the README allows.
- **Rejected:** re-running the LLM on every boot (cost, nondeterminism) and committing the SQLite file (binary diffs, stale schema).
- **Consequences:** with production on persistent Postgres (ADR-015), the snapshot is only loaded into an **empty** database. After that, faculty actions persist across restarts. On a SQLite fallback deploy they would be lost on restart, and the UI footer says so when `persistence = ephemeral`.

## ADR-012: No ground-truth evaluator
- **Context:** The README says "We know the true answer". No labels are provided.
- **Decision:** `validate_results.py` checks schema, taxonomy, scope, count and coverage, and cross-checks against the DB. `evaluate_results.py` is **not** built.
- **Rejected:** hand-labelling and scoring ourselves. It would be circular, and it risks tuning to our own guesses.
- **Consequences:** quality is argued through evidence and tests, not a self-made accuracy number.

## ADR-013: HTML sanitised server-side with an allowlist
- **Decision:** `nh3` (the ammonia binding) with an allowlist of HTML text tags plus all MathML presentation tags and attributes (`display, mathvariant, stretchy, fence, form, linebreak, xmlns`). The `style` attribute is dropped except for `color`.
- **Rejected:** a frontend sanitiser library (another dependency in the browser) and `innerHTML` of raw data (XSS).
- **Consequences:** the API returns `question_html_safe`. The frontend inserts only safe HTML.

## ADR-014: Spelling guard uses a bundled wordlist
- **Decision:** a small domain wordlist (English common words + biology, physics and chemistry terms) in `backend/app/triage/wordlist.txt`, plus Levenshtein in ~10 lines.
- **Rejected:** `pyspellchecker` or a hunspell dependency for a guard that only needs "is the replacement a real word".
- **Consequences:** the wordlist needs occasional additions. It is a known ceiling, marked with a `ponytail:` comment.

## ADR-015: SQLite locally, PostgreSQL in production (revised 2026-11-10, project decision 3)
- **Decision:** `DATABASE_URL` selects the database. SQLite is the default for local development and tests. Production uses a **persistent free PostgreSQL** (psycopg 3). `postgres://` URLs from hosts are normalised to `postgresql+psycopg://` in `config.py`. Business code is dialect-free. Only the trigger DDL in `db.py` has two variants.
- **Rejected:** ephemeral SQLite on Render for the demo. Faculty actions would vanish on every restart.
- **Status:** the SQLite path is tested (68 tests). The Postgres path is **implemented but not yet executed**: the Docker daemon was not running during Phase 2. Run `TEST_POSTGRES_URL=postgresql+psycopg://… pytest -m "postgres or not postgres"` (TASK T2.5).
- **Consequences:** migrations remain `create_all` plus a `schema_version` guard until the first real schema change (DATABASE_SCHEMA §5).

## ADR-016: Faculty writes need a server-side key; reads are public (project decision 4)
- **Context:** The live demo URL is public, and approvals change question content.
- **Decision:** `X-Faculty-Key` is checked against env `FACULTY_ACCESS_KEY` with `hmac.compare_digest` on every write endpoint. If the key is unset, writes are disabled (fail closed). Faculty type the key into Settings, and it stays in `sessionStorage`. It is never in frontend source.
- **Rejected:** full user accounts (beyond MVP), and a key baked into the JS (that would be visible to anyone).
- **Trade-off:** one shared key means the audit `actor` name is self-declared. The key gates *whether* someone can write, not *who* they are. This is documented in SECURITY §9.

## ADR-017: Rules-only mode first, provider adapter second (project decision 5)
- **Context:** No LLM provider or budget is confirmed.
- **Decision:** build and ship the deterministic engine first. Its output is labelled `engine_mode = rules_only` (RULES R-86). The provider interface (`providers.py`) is implemented with an OpenAI-compatible adapter, which covers Gemini's OpenAI-compatible endpoint and others, plus Anthropic. It is switched on by env once a key exists.
- **Consequences:** `results.json` v1 will be rules-only. That means more `faculty_review` routes and capped confidence (≤ 0.70, unless a detector alone determines the verdict). This is stated in README and PROMPTS.md. LLM prompts stay drafts until really run.

## ADR-018: Bonus findings in a separate file, verified vs suspected (project decision 6)
- **Decision:** `bonus_findings.json` is generated by the detectors over all 43 records, with `status: verified | suspected` (RULES R-95). `results.json` stays at exactly 44 entries.
- **Rejected:** hand-copying the 14 questions from the reference notes. Those notes are a human cross-check, not engine input or ground truth.

## ADR-019: Timezone-aware datetimes end to end (Phase 3)
- **Context:** The API first emitted `2026-11-04T00:50:00` with no offset. Browsers parse that as *local* time, so a 10 PM review in IST would show times shifted by 5h30.
- **Decision:** a `UTCDateTime` column type stores naive UTC (portable across SQLite and Postgres) and returns aware UTC datetimes. Naive values are **rejected** on write rather than guessed. API query inputs without an offset are treated as UTC at the boundary.
- **Consequence:** every timestamp in the API carries `+00:00`. A naive `until=` once reached the DB layer and surfaced as a misleading 503; it is now normalised in the route, and there is a test for it.

## ADR-020: Urgency computed on read
- **Decision:** `services/views.compute_urgency` runs per request (impact + volume + age + review, RULES R-90). The `cases.urgency` column is not written for now.
- **Why:** age changes every hour, so a stored value goes stale unless a job refreshes it.
- **Ceiling:** filtering and sorting happen in memory over all cases (`ponytail:` note in `views.py`). That is fine for thousands of reported questions. Persist urgency and move filters into SQL beyond that.

## ADR-013 addendum (Phase 3): unwrap stray MathML before nh3
nh3/ammonia deletes MathML-named elements found in HTML context **together with their content**, while browsers render that content. Three real records have an unclosed `<mspace>` outside `<math>`, and sanitising them dropped options (B)–(D). `sanitize._unwrap_stray_mathml` removes such tags (keeping content) outside `<math>…</math>` before nh3 runs. Regression tests cover all three records and every option of every question.

## ADR-021: Rules-only engine derives every signal from the stored record
- **Context:** No LLM (ADR-017), yet R004, R005 and R016 need answer verification.
- **Decision:** re-check the record's *own* worked solution deterministically:
  - re-evaluate its arithmetic (safe AST);
  - match its final value to an option, with the unit conversions and multipliers the stem asks for;
  - solve integer targets from its own equations (stem template vs solution final, or the solution's last equation);
  - detect self-contradicting statements.
  Confidence for any key judgement is capped at 0.70, so nothing key-related auto-applies.
- **Rejected:** hard-coding the known traps (forbidden, and it wouldn't generalise). Treating the student's claim as a signal (R-40).
- **Limit:** a wrong solution that agrees with a wrong key passes, and recall answers cannot be verified. Both are documented in AI_ENGINE §0.

## ADR-022: `auto_apply` means "eligible"; Phase 4 applies nothing
- **Decision:** auto-eligible repairs are stored as `proposed`, and the case goes to the new status `auto_pending`. Replies say the correction "is queued", never "fixed". Execution belongs to Phase 5.
- **Consequence:** `metrics.auto_applied` stays 0. A test asserts no revision exists after triage and that `original_json == current_json` for all 43 questions.

## ADR-023: Triage runs at boot by default
- **Decision:** `BOOT_TRIAGE=true`. An empty triage history on startup runs the deterministic engine once (~0.3 s). Test fixtures turn it off so the Phase 3 pre-triage tests keep checking that contract unchanged. Post-triage behaviour has its own fixture.
- **Rejected:** loading a snapshot file (ADR-011). For a deterministic engine, re-running is cheaper and can't go stale. The snapshot is still written for audit and diffing.

## ADR-024: R034 reaches `unsound` through self-contradiction, not physics
- **Context:** whether "no option is correct" depends on interference physics that rules cannot evaluate.
- **Decision:** a solution that asserts both truth values for a statement the key depends on means the record cannot establish any option. The result is `unsound`, confidence 0.55, faculty only, with that reasoning stated in `inference`.
- **Limit:** a different assertion-reason defect with a *consistent but wrong* solution would not be caught without a solver.
