# API Specification

> **Status: Phase 5 (2026-11-11).** §1–§9 describe endpoints that are **implemented and tested** (`backend/app/api/routes.py`; tests in `backend/tests/test_api_*.py` and `test_api_phase5.py`). All write endpoints are protected by `X-Faculty-Key` and audited. Phase 5 changes are **additive**; no existing field or route changed meaning.
> The live, machine-generated schema is at `GET /api/v1/openapi.json`, with an interactive reference at `GET /api/v1/reference`.

## 1. Conventions

| Item | Rule |
|---|---|
| Base path | `/api/v1`. Unversioned `/api/...` returns 404. |
| Format | JSON only. UTF-8. |
| Timestamps | ISO-8601 with an explicit UTC offset, e.g. `2026-11-04T00:50:00+00:00`. Stored as UTC. Query inputs without an offset are treated as UTC. |
| IDs | question `^[0-9a-f]{24}$`, report `^R\d{3,6}$`. A malformed ID gives **422**. A well-formed but unknown ID gives **404**. |
| Lists | `{"total", "limit", "offset", "items"}`. `limit` is 1–200 (default 50). `offset` ≥ 0. |
| Request ID | Every response carries `X-Request-ID`. A client-supplied value matching `^[A-Za-z0-9-]{8,64}$` is echoed; anything else is replaced. |
| Body limit | 64 KB (`MAX_BODY_BYTES`). Larger gives **413**. |
| Security headers | `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, `Cache-Control: no-store`. |
| HTML fields | Any field named `*_html_safe` is allowlist-sanitised (SECURITY §3) and may be inserted as HTML. All other strings (comments, raw revision `before`/`after`) must be rendered as **text**. |

## 2. Errors

Every non-2xx response:
```json
{"error": {"code": "not_found", "message": "No report R999.", "details": null, "request_id": "4e9b84db413d4051"}}
```
`error.request_id` always equals the `X-Request-ID` header.

| HTTP | `code` | When |
|---|---|---|
| 401 | `auth_required` | write without `X-Faculty-Key` (also sends `WWW-Authenticate: FacultyKey realm="acadza"`) |
| 403 | `forbidden` | wrong faculty key |
| 404 | `not_found` | unknown route, question, case or report |
| 405 | `method_not_allowed` | e.g. `DELETE /api/v1/cases` |
| 409 | `conflict` | illegal state transition (e.g. investigate a case already under investigation) |
| 413 | `payload_too_large` | body > 64 KB |
| 422 | `validation_failed` | bad path/query/body. `details` = `[{"loc", "msg", "type"}]`. The offending input is **not** echoed. |
| 500 | `internal_error` | unhandled error. No stack trace or message leaks. |
| 503 | `database_error` | the database raised an error. Generic message, details only in server logs. |
| 503 | `writes_disabled` | a write was attempted but the server has no valid `FACULTY_ACCESS_KEY` |

## 3. Authorization (RULES R-85, ADR-016)

- **All `GET` endpoints are public.**
- **Every non-GET endpoint** is registered on the `write` router, which requires `X-Faculty-Key`. It is compared with `hmac.compare_digest` against server env `FACULTY_ACCESS_KEY`. A test enumerates the OpenAPI schema to prove no write operation exists outside that router.
- Order of checks: writes disabled (503) → header missing or empty (401) → key wrong (403) → body validation (422). An unauthenticated caller never sees body validation details.
- A configured key shorter than 16 characters counts as **not configured** (fail closed).
- Write bodies use `extra="forbid"` and include `actor`: `^[\w .-]{2,60}$` (self-declared, see SECURITY §9).

## 4. Meta

### `GET /health`
```json
{"status": "ok", "db": "sqlite", "data_imported": true,
 "counts": {"questions": 43, "reports": 44, "cases": 39}, "writes_enabled": true, "version": "0.3.0"}
```
If the DB is unreachable it returns 503 `database_error`. It does not call any LLM.

### `GET /taxonomy`
Returns `data/taxonomy.json` verbatim.

### `GET /settings`
```json
{"version": "0.3.0", "writes_enabled": true, "database": "sqlite",
 "engine": {"provider": "none", "model": null, "mode": "rules_only"},
 "thresholds": {"auto_apply_min_confidence": 0.85, "no_change_min_confidence": 0.6},
 "data_sha256": "{\"questions.json\": \"178d…\", …}"}
```
Never contains secrets. `data_sha256` is `null` before import.

### `GET /auth/status`
`{"writes_enabled": true}`. Says nothing about the key itself.

## 5. Dashboard

### `GET /dashboard`
Computed from the DB at request time. Response from the real data before any triage (fixed clock 2026-11-10T00:00Z, abridged):
```json
{
  "generated_at": "2026-11-10T00:00:00+00:00",
  "metrics": {"total_reports": 44, "unique_questions": 39, "untriaged": 39, "needs_review": 0,
              "confirmed_defects": 0, "resolved": 0, "auto_applied": 0, "rejected": 0, "critical_unresolved": 0},
  "urgent": [{"question_id": "60f744b3f1b9bc7cc7b4a949", "urgency": 28, "priority": "normal", "…": "case summary"}],
  "by_subject": [{"subject": "Botany", "reports": 4, "cases": 4}, {"subject": "Physics", "reports": 35, "cases": 30},
                 {"subject": "Zoology", "reports": 5, "cases": 5}],
  "by_source": {"web": 9, "android": 26, "ios": 9},
  "verdicts": [],
  "status_counts": {"untriaged": 39},
  "trend": [{"date": "2026-11-04", "resolved": 0}, "… 7 days"],
  "recent_activity": ["… last 10 audit events, newest first"],
  "ai_status": {"last_run": null, "triaged_reports": 0}
}
```
Definitions:
- `needs_review` = cases in `needs_review` or `investigating`;
- `confirmed_defects` = current triage results with verdict `defect`;
- `resolved` = cases in `auto_fixed`, `approved`, `no_change`, `rejected` or `duplicate`;
- `auto_applied` = repairs with status `auto_applied`;
- `critical_unresolved` = unresolved cases with urgency ≥ 70;
- `trend` counts resolution audit events per UTC day for the last 7 days.

## 6. Cases (queue) and reports

### `GET /cases`
Query parameters:

| Param | Values |
|---|---|
| `status` | `all` (default), `resolved`, `untriaged`, `needs_review`, `auto_pending` (Phase 4: auto-eligible, nothing applied yet), `auto_fixed`, `no_change`, `approved`, `rejected`, `investigating`, `duplicate`, `rolled_back` |
| `defects_only` | bool |
| `subject` | case-insensitive exact match |
| `verdict` | a taxonomy verdict |
| `confidence` | `low` (<0.60), `medium` (<0.85), `high` (<0.95), `very_high` |
| `priority` | `critical` (urgency ≥70), `high` (40–69), `normal` (15–39), `low` (<15) |
| `q` | case-insensitive substring of the question ID or any report ID (≤64 chars) |
| `sort` | `urgency` (default), `latest`, `confidence`, `reports` |
| `order` | `desc` (default), `asc` |
| `limit`, `offset` | as in §1 |

Item:
```json
{"question_id": "60f744b3f1b9bc7cc7b4a949", "title": "In a LCR circuit the pd between the terminals of the inductance is 60 V, between the term…",
 "subject": "Physics", "chapter": "Alternating Current and EM Waves", "topic": null, "level": "EASY", "type": "scq",
 "report_count": 3, "report_ids": ["R002", "R003", "R001"], "sources": ["ios", "web"],
 "first_reported_at": "2026-11-03T22:11:00+00:00", "latest_report_at": "2026-11-07T01:25:00+00:00",
 "verdict": null, "repair": null, "confidence": null, "confidence_band": null,
 "urgency": 28, "urgency_breakdown": {"total": 28, "impact": 0, "volume": 16, "age": 12, "review": 0, "resolved": false},
 "priority": "normal", "status": "untriaged", "origin": "student", "assigned_to": null, "engine_mode": null, "triaged": false}
```
- `urgency` follows RULES R-90 and is computed at read time. **It is never AI confidence.**
- The case `verdict` is the most severe current report verdict. The case `confidence` is the minimum across its reports.
- Both are `null` until triage runs (Phase 4).

### `GET /cases/{question_id}`
The case summary plus:
- `question`: the same shape as `GET /questions/{id}`;
- `reports`: each with `result` (null before triage) and `fixed_after_report` (errorHistory entries dated after that report);
- `repairs` (each with `report_ids`) and `revisions`;
- `audit`: up to 200 events for this question, oldest first.

It returns 404 for a question with no reports (no case). That question is still readable via `/questions/{id}`.

### `GET /reports`
Filters: `question_id`, `source` (`android|ios|web`), `q` (substring of the report or question ID). Newest first.

### `GET /reports/{report_id}`
```json
{"report_id": "R017", "question_id": "6208e80a9cb2ab67dac61bd0", "student_id": "stu_b0babf1d", "source": "android",
 "reported_at": "2026-11-04T02:08:00+00:00", "comment": "spelling mistake 'mere' in options",
 "injection_suspected": false, "duplicate_of": null, "result": null,
 "question": {"id": "6208e80a…", "title": "Rate of photosynthesis is low in herbs, shrubs as compared to sun plants because",
              "subject": "Botany", "chapter": "Photosynthesis in Higher Plants", "type": "scq"},
 "case_status": "untriaged", "other_reports_on_question": [],
 "fixed_after_report": [{"type": "Spelling mistake", "actor": "faculty", "at": "2026-11-07T10:42:00Z",
                          "note": "'mere' -> 'more' in options A-C; 'shurbs' -> 'shrubs'"}]}
```
`comment` is untrusted student text, so render it as text.

## 7. Questions, history, revisions

### `GET /questions/{question_id}?version=current|original`
```json
{"id": "68c9ae5afb6b2f16e2d43b1c", "qid": "SecAQ23", "version": 1, "which": "current", "modified": false,
 "type": "scq", "subject": "Physics", "chapter": "Photoelectric effect and matter waves", "concept": "…", "sub_concept": "…",
 "level": "MEDIUM", "updated_at": "2026-01-30T16:05:44.859Z", "title": "Light of wavelength 4000 A^(∘) falls on …",
 "question_html_safe": "<h3>…<math …>…</math>…</h3>", "stem_html_safe": "…", "stem_text": "…",
 "options": [{"letter": "A", "html_safe": "…", "text": "3.1 V", "blank": false}, "… B, C, D"],
 "solution_html_safe": "…", "solution_text": "…",
 "answer": "D", "answer_canonical": "D", "answer_issues": [], "original_answer": "D",
 "images": {"question": [], "solution": []}, "error_history": []}
```
- `answer` is the value as stored, and `answer_canonical` is the normalised form (mcq is a sorted letter list). `answer_issues` lists format problems (`empty_element`, `joined_string`, `keyed_option_blank:C`, `option_count:3`, …).
- `version=original` renders the immutable imported record.
- `modified` is true once any revision has been applied.

### `GET /questions/{question_id}/history`
`{"question_id", "error_history": [...], "reports": [{"report_id", "reported_at", "fixed_after_report": [...]}], "revisions": [...]}`

### `GET /questions/{question_id}/revisions` and `GET /revisions?question_id=`
Item:
```json
{"id": 1, "question_id": "60f744b3…", "version": 2, "field": "answer", "before": "C", "after": "A",
 "actor": "faculty:Meera", "repair_id": null, "reverts_revision_id": null, "reverted_by_revision_id": 2,
 "created_at": "2026-11-11T…+00:00"}
```
For `question`/`solution` fields, `before`/`after` are **raw stored HTML**. Render them as text, or request the sanitised question view.

## 8. Audit and writes

### `GET /audit`
Filters: `question_id`, `report_id`, `actor_type` (`system|ai|faculty`), `event_type` (`^[a-z_]{3,40}$`), `since`, `until`, `order` (`asc` default, chronological). Item: `{"id", "ts", "actor", "actor_type", "event_type", "question_id", "report_id", "repair_id", "before", "after", "rule_ids", "note", "hash"}`.

### `GET /audit/verify`
`{"ok": true, "events": 45, "first_bad_id": null}`. Recomputes the hash chain.

### `POST /auth/verify` 🔒
No body. `200 {"ok": true}` if the key is valid. The console uses it to check a typed key.

### `POST /cases/{question_id}/investigate` 🔒
Body `{"actor": "Meera", "note": "3–500 chars"}`. Sets the case status to `investigating` and writes an audit `investigation_requested` event with `before`/`after` status. Returns the case detail. 409 if the case is already under investigation, 404 if there is no case.

### `POST /cases/{question_id}/reopen` 🔒
Body `{"actor": "Meera", "note": "optional ≤500"}`. Ends an investigation and restores the status recorded in the last `investigation_requested` event. Writes a `case_reopened` audit event. 409 unless the case is `investigating`.

**Example (real run against uvicorn, 2026-11-11):**
```
POST /api/v1/auth/verify                                  → 401 {"error":{"code":"auth_required",…}}
POST /api/v1/auth/verify   X-Faculty-Key: nope            → 403 {"error":{"code":"forbidden",…}}
POST /api/v1/auth/verify   X-Faculty-Key: <env key>       → 200 {"ok":true}
POST /api/v1/cases/60f744b3…/investigate  {"actor":"Smoke Test","note":"real-process check"} → 200 status=investigating
GET  /api/v1/audit/verify                                 → 200 {"ok":true,"events":46,"first_bad_id":null}
```

## 8b. Triage outputs (Phase 4)

On startup, if the DB has questions but no triage run and `BOOT_TRIAGE=true` (the default), the rules engine runs once and stores its proposals. Nothing is applied.

### `GET /results`
The current results in the exact `results.json` schema: one entry per report, sorted by `reportId`, with the keys `reportId, questionId, verdict, repair, edit, route, confidence, evidence, student_reply`. It equals the committed `results.json` when the DB holds the original data (tested).

### `GET /bonus-findings`
`{"engine": "rules-v1", "engine_mode": "rules_only", "questions_inspected": 43, "total": 7, "items": [...]}`. Each item has `findingId, questionId, subject, chapter, field, category (taxonomy repair), check, status (verified|suspected), severity (high|medium|low), evidence, recommended_action`. It is computed live from the current records, excludes defects already covered by a report's verdict, and never contains report IDs.

### `GET /triage/runs`
List of runs: `{"id", "mode": "rules_only", "provider": null, "model": null, "prompt_versions": {"engine": "rules-v1"}, "started_at", "finished_at", "calls": 0, "failures": 0}`.

### Result fields (additive, in `cases/{qid}` → `reports[].result` and `reports/{rid}` → `result`)
Fields from earlier phases are unchanged. New: `inference`, `recommendation`, `review_reason`, `facts` (evidence list), `confidence_basis` (e.g. `"rules_only: key_two_signals = 0.70 (RULES R-87)"`), `student_claim`, `student_correct`, `key_status`, `rule_ids`.

### Dashboard (additive)
`metrics.auto_eligible` = results routed `auto_apply` (eligible, not applied). `metrics.auto_applied` reflects repairs executed via `POST /repairs/{id}/execute`.

## 9. Faculty review and repair actions (Phase 5, implemented)

All write endpoints require the `X-Faculty-Key` header and write append-only audit events.

### `POST /repairs/{repair_id}/approve` 🔒
Approves a proposed repair. Optionally accepts an edited proposal `{"edit": {"field", "find", "replace"}}` which is re-validated against R-10..R-14 and repair guards (RULES R-81).
- Request body:
  ```json
  {"actor": "Meera", "edit": {"field": "question", "find": "...", "replace": "..."}, "note": "optional note"}
  ```
- Returns the updated repair object with status `approved_applied` (or `approved_no_edit` if no writable fields) and a before/after `preview` diff:
  ```json
  {"id": 5, "question_id": "617fa18efd53ff1629ed890f", "repair_type": "exam_reference", "edit": {...}, "status": "approved_applied", "confidence": 0.95, "created_by": "engine:rules-v1", "created_at": "...", "report_ids": ["R013"], "preview": {"field": "question", "before": "...", "after": "..."}, "audit_ok": true}
  ```
- Errors: 401 (auth), 403 (bad key), 404 (unknown repair), 409 (conflict: not in `proposed` status), 422 (validation failed).

### `POST /repairs/{repair_id}/reject` 🔒
Rejects a proposed repair with a mandatory reason.
- Request body:
  ```json
  {"actor": "Meera", "reason": "Explanation why repair is rejected (min 3 chars)", "note": "optional"}
  ```
- Returns updated repair object (`status: rejected`) and `"audit_ok": true`.
- Errors: 401, 403, 404, 409 (conflict if already approved/rejected).

### `POST /repairs/{repair_id}/execute` 🔒
Executes an approved repair against `current_json` atomically using compare-and-set protection (RULES R-80, R-82).
- Requires the repair to be in `approved_applied` status.
- Re-validates that `find` matches the current record state. On any conflict or stale edit, aborts atomically with 409.
- Creates a new `question_revisions` record and an audit event in the same transaction.
- Request body:
  ```json
  {"actor": "Meera", "note": "Applying verified fix"}
  ```
- Returns:
  ```json
  {"revision_id": 1, "question_id": "...", "version": 2, "field": "question", "before": "...", "after": "...", "actor": "faculty:Meera", "created_at": "...", "repair": {...}, "audit_ok": true}
  ```

### `POST /revisions/{revision_id}/rollback` 🔒
Rolls back a specific revision by creating a new revision restoring `before` (RULES R-82).
- Enforces LIFO per field: the field must still hold this revision's `after` value.
- Re-verifies compare-and-set; protects against duplicate rollback (409 if already rolled back).
- Request body:
  ```json
  {"actor": "Meera", "note": "Rolling back accidental edit"}
  ```
- Returns:
  ```json
  {"rollback_revision_id": 2, "original_revision_id": 1, "question_id": "...", "version": 3, "field": "question", "restored_to": "...", "actor": "faculty:Meera", "created_at": "...", "audit_ok": true}
  ```

### `POST /reports/{report_id}/duplicate` 🔒
Marks a report as a duplicate of another report (RULES R-63).
- Request body:
  ```json
  {"actor": "Meera", "duplicate_of": "R002", "note": "same defect reported by another student"}
  ```
- Returns updated report detail (`duplicate_of: "R002"`).

### `PUT /reports/{report_id}/reply` 🔒
Edits the final student reply on a triage result (RULES R-70..R-73).
- Validates 1–320 chars, checks against forbidden claims ("fixed" when not auto-applied), rejects accusatory language and internal jargon, rejects prompt injection/XSS.
- Request body:
  ```json
  {"actor": "Meera", "reply": "Thank you for bringing this to our attention. Our team has verified the question.", "note": "refined tone"}
  ```
- Returns updated result view with `reply_status: "edited"`.

### `POST /validate-edit` 🔒
Dry-run validation of an edit proposal against a question and repair type without making any changes.
- Request body:
  ```json
  {"question_id": "617fa18efd53ff1629ed890f", "repair_type": "exam_reference", "edit": {"field": "question", "find": "(NEET 2019)", "replace": ""}}
  ```
- Returns:
  ```json
  {"valid": true, "violations": []}
  ```
  Or on failure:
  ```json
  {"valid": false, "violations": ["R-10: field 'answer' is outside repair 'spelling' scope"]}
  ```

## 10. Planned (Phase 6+)

| Endpoint / Feature | Target Phase |
|---|---|
| Faculty Review Console frontend (SPA) | Phase 6 |
| LLM Provider adapter & multi-model evaluation | Phase 4 extension (T4.3/T4.4) |

## 10. Console static files (Phase 6)
`GET /` and every non-`/api` path serve `frontend/` (FastAPI `StaticFiles`, mounted **after** the routers, so every `/api/v1` route wins). These responses carry the console Content-Security-Policy (SECURITY §11). Unknown `/api/...` paths still return the JSON error envelope (tested).
