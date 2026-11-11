# Security

> **Project Status (2026-11-12): Phase 0–7 Complete. Phase 8 has NOT started.** Security invariants and defenses are verified across all API, data, and faculty execution layers.

Threat model, scaled to this product: a public demo URL, untrusted student text, untrusted stored HTML, an LLM that can be steered, and question content where a bad write harms students.

## 1. Secrets & API Keys
- **Gemini API Key:** `LLM_API_KEY` (and optional fallback keys) are loaded strictly through environment variables into Pydantic `SecretStr`. They are git-ignored via `.gitignore` and `.env.example` contains only placeholders.
- **Zero Leakage:** No secret is ever serialised into an API response, logs, or client-side storage. `/api/v1/settings` reports `configured: true/false` only.
- **Request Headers & Logs:** Outbound and inbound auth headers are never logged. The JSON request logger on stderr records method, path, status, and duration, explicitly stripping headers and bodies.
- **Faculty Key:** `FACULTY_ACCESS_KEY` is loaded as a `SecretStr`. On the frontend, it is kept strictly in JavaScript module memory (`state.js`) and is cleared from the DOM immediately upon verification; it is forgotten on page reload.

## 2. Prompt Injection & AI Guardrails
RULES §6 has the full set. In short:
- Student comments are inserted only as JSON-escaped data inside `<student_reports>`, and `<`/`>` are escaped so the block can't be closed.
- The system prompt explicitly instructs the model that student text is untrusted evidence, not instructions.
- Output can't escalate: the AI returns only structured JSON adhering to strict Pydantic schemas with `extra="forbid"`. There is no route, actor, or action field in the schema.
- An edit supported only by a flagged comment is dropped (R-52). Its verdict comes from independent signals.
- The LLM has **zero tool access** and zero write permissions. It cannot read or modify the database or filesystem.
- The blind solver (`solve.v1`) never sees student comments or stored keys.

## 3. Database Security (SQLite)
- **Engine:** SQLite is the default and existing database (`acadza.db`).
- **SQL Injection Prevention:** All database operations use SQLAlchemy ORM or Core queries with parameter binding. No dynamic SQL string interpolation exists in the codebase.
- **File System Permissions:** In local and containerized deployments, the database file is restricted to the running application process.
- **Immutability Triggers:** Database triggers prevent updates or deletions of original question records (`original_json`) and make audit logs append-only.


## 3. Input validation and sanitisation (implemented, Phase 3)
- **Requests:** Pydantic on every parameter. Path IDs are pattern-checked (`^[0-9a-f]{24}$`, `^R\d{3,6}$`), query enums are `Literal`s, string queries are capped at 64 chars, and bodies use `extra="forbid"`. Bodies over 64 KB are rejected by Content-Length (413). Validation errors return `loc`/`msg`/`type` but never echo the input.
- **Stored question HTML** (`backend/app/sanitize.py`, ADR-013): `nh3` (Rust ammonia, html5ever parser) re-serialises a browser-equivalent tree, keeping only:
  - HTML text tags (headings, `p`, `span`, `br`, `b/i/u/s`, `sup/sub`, lists, tables, `img`);
  - MathML presentation tags (`math`, `mrow`, `mi`, `mn`, `mo`, `mfrac`, `msup`, `msqrt`, `mover`, `mtable`, `semantics`, …) with their layout attributes only.
- Removed: `style`, `class`, `id`, `href` (MathML Core allows `href` on any element, so it is in no allowlist), every `on*` attribute, and `javascript:`/`data:` URLs (`img src` must be http/https). `script`, `style`, `iframe`, `object`, `embed`, `svg`, `template`, `noscript`, `annotation-xml` and `maction` are removed with their content. Comments are stripped.
- **Content preservation:** some records put MathML tags *outside* `<math>` (an unclosed `<mspace linebreak="newline">` between options). Browsers show such content. nh3 deleted it, which silently dropped options (B)–(D) on 3 real questions (found by a test, PROMPTS Part C). Stray MathML tags outside `<math>` are now unwrapped before sanitising.
- Tests: 26 XSS payloads (case variants, entity-obfuscated `javascript:`, mXSS `mtext/mglyph/style`, `noscript` breakout, `annotation-xml`, `maction`), a check that readable text and `<math>` counts are identical before and after sanitising **for every field of all 43 records**, and per-option preservation.
- Student comments are returned as plain strings and must be rendered with `textContent` (API_SPECIFICATION §1).
## 4. SQL injection
All DB access goes through the SQLAlchemy ORM or Core with bound parameters. No string-formatted SQL. Search uses `ilike` with a bound parameter.

## 5. CORS (implemented)
Production is same-origin, so no CORS middleware is installed and no `Access-Control-Allow-Origin` header is sent. In dev, `CORS_ORIGINS=http://localhost:5500` enables exactly the listed origins: methods GET/POST/PUT, headers `Content-Type`, `X-Faculty-Key` and `X-Request-ID`, no credentials. `*` is rejected when settings load. Tested: allowed origin, disallowed origin, default.
## 6. Error handling and logging (implemented)
- One envelope for every error, with `request_id` (API_SPECIFICATION §2). 500 and 503 responses carry generic messages. Exceptions and tracebacks go only to server logs.
- Logs are JSON lines on the `acadza` logger: `request_id`, method, path, status, ms. **Headers and bodies are never logged**, so the faculty key and student comments cannot leak into logs. A test sends an authenticated write and a wrong key, then asserts that neither key nor the request note appears in the log stream.
- Response headers: `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, `Cache-Control: no-store`.
- The API reference page (`/api/v1/reference`, FastAPI's Swagger UI) loads its JS/CSS from a public CDN. It is a developer page, not part of the faculty console, which loads no third-party assets.
## 7. Safe repair execution (implemented, Phase 5)
- **Zero unapproved execution:** Queued auto-eligible repairs are never applied automatically without explicit faculty approval (`POST /repairs/{id}/approve` then `POST /repairs/{id}/execute`).
- **Answer-key changes:** Answer-key modifications always require teacher approval (routed `faculty_review`, confidence capped at 0.70).
- **No invented content:** Missing options or distractors are never automatically invented; authoring is reserved for faculty.
- **Compare-and-set protection:** Writes happen through `faculty_actions.execute_repair()` and `services.apply_revision()`. It re-validates scope (R-10), requires `find` to match the current field uniquely (optimistic concurrency, 409 otherwise), writes a revision and an audit event in **one transaction**, and bumps the version.
- **Original data immutability:** `original_json` is immutable (enforced by DB trigger). Source files in `/data` are never opened for writing.
- **Rollback guarantees:** Rollback is LIFO per field (R-82). Duplicate rollback returns 409. Rollbacks append a new revision restoring previous state; historical records are never deleted.
- **Prompt injection & XSS defense:** `faculty_actions._check_injection()` rejects prompt injection keywords (`ignore all previous`, `you are now`, `system prompt`) and malicious HTML/XSS (`<script>`, `javascript:`, `on*=` handlers, `data:`, `<iframe>`, `<svg>`) in edited proposals and replies.

## 8. Audit integrity
- The table is append-only (trigger blocks UPDATE and DELETE).
- A hash chain allows tamper detection (`/api/v1/audit/verify`).
- Verification is automatically performed after every approve, reject, execute, and rollback operation.
- **Limitation:** an attacker with full DB write access could rebuild the whole chain. Mitigation for production would be periodically exporting the head hash to an external log. Not in MVP.

## 9. Access control (project decision 4, ADR-016)
- **Every write endpoint requires `X-Faculty-Key`.** It is compared in constant time to server env `FACULTY_ACCESS_KEY`. If the key is unset, writes return 503 `writes_disabled` (fail closed). A missing or wrong key returns 401 or 403. Reads (dashboard, queue, case view, audit) are public for the demo.
- All Phase 5 write endpoints (`/repairs/{id}/approve`, `/reject`, `/execute`, `/revisions/{id}/rollback`, `/reports/{id}/duplicate`, `/reports/{id}/reply`, `/validate-edit`) are mounted on `routes.write` with router-level dependency `require_faculty`.
- The key never appears in frontend source or API responses. Faculty enter it in Settings, and it is kept in memory only (Phase 6, §11): gone on reload.
- **Known limit:** one shared key. The `actor` name in audit entries is self-declared by whoever holds the key. Per-user accounts are a roadmap item.
- Check order: 503 `writes_disabled` → 401 `auth_required` (with `WWW-Authenticate`) → 403 `forbidden` → body validation. A configured key shorter than 16 characters is treated as unset.
- The key is a `SecretStr`, so it does not appear in the settings repr or dumps (tested).
- **Not implemented:** per-IP lockout or rate limiting of failed attempts (`ponytail:` note in `deps.py`). With a ≥16-character random key, guessing is impractical. Add rate limiting at the proxy if that ever changes.
- Triage re-runs will be rate-limited when that endpoint exists (Phase 4).

## 10. Dependencies
Pinned ranges in `requirements.txt`: fastapi, uvicorn, pydantic, pydantic-settings, sqlalchemy, psycopg, nh3, httpx (tests; also used by the future LLM adapters), pytest. The faculty console (Phase 6) loads no third-party scripts or CDNs.

## 11. Faculty console (Phase 6)
- **Key handling:** the faculty key is held in a JavaScript module variable only. It is never written to localStorage/sessionStorage, the URL, logs or the DOM; the input is cleared after submit, and a reload forgets it. This is enforced by e2e `test_valid_key_lives_only_in_memory`. A rejected key (403) is cleared immediately. The key is sent only on write requests (`X-Faculty-Key`) and never on reads.
- **Untrusted text** (student comments, revision before/after values, audit notes) is inserted only through `textContent`. Academic HTML is inserted only from `*_html_safe` API fields, through one function (`dom.setSafeHTML`) that re-applies the server allowlist client-side via `DOMParser` (defence in depth). There are no `innerHTML` assignments anywhere (mechanically checked). A mutation test that renders comments with `innerHTML` makes the XSS e2e test fail.
- **Content-Security-Policy** on the console (non-`/api` paths): `default-src 'self'; script-src 'self'; style-src 'self'; font-src 'self'; img-src 'self' https:; connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'`. Inline scripts and inline event handlers cannot run even if markup were injected. Bar widths are set through the CSSOM, which CSP allows.
- **Writes:** buttons are disabled with a stated reason when there is no key, the key was rejected, or the server has writes disabled. Every write goes through a double-submit guard. Success is shown only from the API response, and writes are never retried automatically. A 409 refreshes the view to the true state.
- **Limit:** the frontend checks are convenience only. The server re-validates everything (scope, guards, R-71 replies, state transitions).

## 12. Security Audit Results (Phase 7, 2026-11-11)
- **Authentication Boundaries**: All 10 write endpoints (`/auth/verify`, `/cases/{id}/investigate`, `/reopen`, `/repairs/{id}/approve`, `/reject`, `/execute`, `/revisions/{id}/rollback`, `/reports/{id}/duplicate`, `/reports/{id}/reply`, `/validate-edit`) strictly require `X-Faculty-Key`. Missing key returns 401 with `WWW-Authenticate`; invalid key returns 403; unconfigured key fails closed with 503 `writes_disabled`. Verified by 105 tests in `test_api_auth.py`.
- **CORS Configuration**: Same-origin only in production (`Access-Control-Allow-Origin` absent). In dev, only configured origins with explicit methods (GET, POST, PUT) and headers are allowed. Wildcard `*` is explicitly forbidden by Settings validation.
- **Security Headers & CSP**: Verified on every response (`X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, `Cache-Control: no-store`). Console CSP enforces `default-src 'self'` with zero inline scripts, objects, or frames.
- **Input Validation**: Request bodies enforced with Pydantic (`extra="forbid"`, `max_length` bounds, 64 KB Content-Length ceiling).
- **Sanitization & XSS**: 26 unit attack vectors + browser E2E test with `<img src=x onerror=...><script>...` verified completely inert.
- **Prompt Injection**: Student comments treated as pure untrusted data; heuristic detector flags instruction-like patterns; backend rejects injection payloads in faculty edit proposals and replies.
- **Audit Immutability**: Hash chain verified with 0 breaks; DB triggers forbid UPDATE/DELETE on `audit_events`, `questions.original_json`, and `question_revisions`.
- **Zero Secret Leaks**: Verified `FACULTY_ACCESS_KEY` never appears in logs, responses, headers, `localStorage`, `sessionStorage`, or frontend source code.
