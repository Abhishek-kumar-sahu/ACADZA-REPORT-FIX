# RULES: Business and AI Safety Rules

This is the contract between the AI and the data. The **LLM proposes**. **Backend code decides.** Every rule here is enforced in Python (`backend/app/triage/rules.py`, `validators.py`, `routing.py`). None of it is left to the prompt. Prompts restate the rules only to make LLM output better. They are never the enforcement.

Rule IDs (`R-xx`) are referenced from code comments, tests and audit events.

---

## 1. Closed vocabularies

**R-01. Taxonomy is authoritative.** `data/taxonomy.json` is loaded at startup. Verdict and repair enums are generated from it. Any LLM output with a verdict or repair outside these keys fails validation and is retried once. If it fails again, the report goes to `faculty_review` with `verdict` taken from deterministic signals, or `not_actionable` if there are none.

Verdicts: `defect`, `no_error`, `display_issue`, `app_issue`, `language_mode`, `already_fixed`, `not_actionable`.

Repairs and the fields each may write:

| Repair | May write | Taxonomy auto | Our auto-apply also requires (R-30 to R-42) |
|---|---|---|---|
| spelling | question, solution | ✅ | R-31 words-only guard |
| noise | question, solution | ✅ | R-32 removal-only guard |
| exam_reference | question, solution | ✅ | R-33 exam-tag pattern guard |
| markup_leak | question, solution | ✅ | R-34 leak-pattern + number-preservation guard |
| answer_form | question | ✅ | R-35 additive-only guard |
| notation | question, solution | ✅ | R-36 single-expression guard |
| stem_data | question | ✅ | R-37 value-stated-in-solution guard |
| option_repair | question | ✅ | R-38 stem-unchanged + grounded-value guard |
| solution_fix | solution | ✅ | R-39 ends-in-verified-key guard |
| solution_missing | solution | ✅ | R-39 |
| answer_key | answer, solution | ✅ | R-40 independent verification guard |
| type_mismatch | questionType, question, answer | ✅ | R-41 type-consistency guard |
| identical_options, diagram, wrong_question, unsound, wrong_chapter, syllabus | **nothing** | ❌ | Always `faculty_review`. `edit` is `null`. |

**R-02. Repair only with defect.** `repair` is non-null **only if** `verdict == "defect"`. For any other verdict, `repair = null`, `edit = null`, `route = "no_change"` (or `faculty_review` per R-21).

**R-03. Routes.** The only routes are `auto_apply`, `faculty_review` and `no_change`. The route is computed by `routing.py`. The LLM never outputs a route. If it does, the field is discarded.

## 2. Field-level permissions

**R-10. Scope check.** For every edit, `edit.field ∈ taxonomy.repairs[repair].fields`. This is checked in code. A violation rejects the edit, logs `scope_violation` to the audit trail, and forces `faculty_review` with no edit.

**R-11. Empty-scope repairs never carry an edit.** If `fields == []`, then `edit` in `results.json` is `null`. A human-readable *suggestion* (for example a suggested distractor or chapter) can be stored in internal metadata. It is shown in the console marked **"Suggestion: faculty-authored content"** and is never written by the system.

**R-12. Surgical edits only.** For `question` and `solution` fields:
- `find` must be a non-empty substring of the **current raw stored HTML** and must occur **exactly once**. If not, reject.
- `len(find) ≤ 300` chars. A whole-field rewrite is never a valid `find`. The one exception is `solution_missing`, where `find` is the entire (unusable) solution and the edit carries `"mode": "replace_field"` internally.
- After replacement, the field must still parse as HTML, and sanitizing it must not drop any tags (no new unknown tags).
- Unchanged text outside `find` must stay byte-identical (checked by diffing before and after).

**R-13. Answer edits.** `edit = {"field":"answer","find":<current stored value>,"replace":<new value>}`. This is the README shape, unchanged.
- `find` must equal the stored value exactly, as stored (a string, or a list for mcq).
- `replace` must be the **canonical** form for the type. scq: one existing, non-blank option letter. mcq: a non-empty, sorted, unique list of existing option letters (for example `["A, B, D"]` becomes `["A","B","D"]`; normalisation is implemented in `triage/record.py::canonical_answer`). integer: a numeric string.

**R-14. Single-field outputs only.** In `results.json`, `edit` is always a single `{field, find, replace}` object or `null`. No other shape is ever emitted (project decision 2, 2026-11-10). If a correct fix needs **more than one field** (for example `type_mismatch` needing `questionType` + `answer`, or `answer_key` needing `answer` + `solution`), the README schema cannot represent it safely. In that case:
- `route = faculty_review` and `edit = null` in `results.json`;
- the full ordered multi-field proposal is stored internally (`repairs.edit` as a list), validated field-by-field under R-10 to R-13, and shown in the console diff;
- `evidence` says that the change spans several fields and is held for a teacher.
This is a documented limitation (ADR-008).

**R-15. Metadata is off-limits.** `subject`, `chapter`, `concept`, `level`, `qid`, `_id`, `errorHistory`, `updatedAt` are never writable by any repair. Chapter and subject problems are `wrong_chapter` (faculty only).

## 3. Verdict rules

**R-20. Content before complaint.** The verdict is about the **stored record**, not about whether the student is right. If the student's claimed answer is wrong but the key is *also* wrong (for example R004), the verdict is `defect / answer_key`, and the reply must not tell the student their value was right.

**R-21. Doubtful no-change.** If verdict ∈ {`no_error`, `not_actionable`} but any independent check disagrees with the stored record (blind solve ≠ key, or solution final value ≠ key), the route becomes `faculty_review`, not `no_change`. We never close a report while a check still disagrees with the record.

**R-22. Verdict-specific evidence requirements:**

| Verdict | Required deterministic or independent signal |
|---|---|
| `defect` | At least one of: a detector hit (§5), blind-solve mismatch, a solution/key mismatch, or LLM content analysis with a quoted `find` span that exists in the record. |
| `no_error` | For calculable questions: blind solve == key. For recall questions: LLM verification plus no detector hits relevant to the complaint. |
| `display_issue` | The complaint is about appearance or loading, **and** detectors confirm the stored content is complete (option count, no blanks, no leaks). If detectors find the content actually broken, the verdict is `defect`. Example: "only 3 options showing" with only 3 stored options is `defect/option_repair`, not `display_issue`. |
| `app_issue` | The complaint describes platform behaviour (recorded wrong option, keyboard, lag, grading) **and** the record is consistent. Exception: a grading complaint on an mcq with a malformed answer is `defect/answer_key` (R-40b). |
| `language_mode` | Complaint asks for another language. No content defect is required. |
| `already_fixed` | `errorHistory` has an entry with `at > report.reportedAt` addressing the complaint, **and** the live record no longer has the problem (detector re-run). |
| `not_actionable` | Comment is empty or unintelligible (e.g. keyboard mash, or a single word like "wrong" with no target), **and** all checks found nothing. If checks *did* find a defect, the verdict is `defect` regardless of the comment. |

**R-23. Syllabus and metadata complaints** (decision 1, 2026-11-10; implemented: syllabus is complaint-triggered per the taxonomy label, confidence 0.50; chapter uses a lexical check, confidence 0.65; both always faculty, and the reply never calls them confirmed). They are classified as `defect` **only through repairs the taxonomy provides**:
- chapter, subject or topic metadata wrong → `wrong_chapter`;
- outside the syllabus → `syllabus`.
Both have `fields: []` and `auto: false`, so they are always `faculty_review` with `edit = null`. The question stays live. No new verdict or repair type is ever introduced. If the metadata is actually correct (the student is mistaken), the verdict is `no_error`.

**R-24. History before repair.** Before any repair is proposed, the pipeline reads `errorHistory` (`record.history_after(question, report.reportedAt)`). If an entry postdates the report, the detectors re-run on the live record. If the reported problem is gone, the verdict is `already_fixed` and nothing is proposed. Any history entry is also passed to the triage prompt and shown in the console. The detector half of this is implemented and tested (`test_history_considered_for_every_report`).

## 4. Routing and confidence

**R-30. Auto-apply requires *all* of:**
1. `verdict == defect` and `taxonomy.repairs[repair].auto == true`.
2. The edit passes R-10 to R-14 and the repair-specific guard (R-31 to R-41).
3. `confidence ≥ AUTO_APPLY_MIN_CONFIDENCE` (default **0.85**).
4. No `injection_suspected` flag on **every** report that supports this edit. At least one clean report, or a detector, must independently support it.
5. No conflicting edit on the same field in the same case.
6. The edit is not already applied (idempotency: if `find` is absent and `replace` is present, it is already fixed).

Anything else that is a defect goes to `faculty_review`.

**Repair-specific guards** (deterministic, `validators.py`):

- **R-31 spelling.** Words only. After removing letters `[A-Za-z]`, `find` and `replace` are identical (same digits, symbols, tags). Each changed word is within Levenshtein distance ≤ 3, and the replacement word is in the domain wordlist or the medical/biology/physics term list.
- **R-32 noise.** `replace` is `find` with a span removed, and the removed span matches a noise pattern (`^\s*Q?\d+[.)]`, `space for rough work`, source labels).
- **R-33 exam_reference.** The removed span matches `\(?\s*(JEE|NEET|AIPMT|AIIMS|MHT[- ]?CET|BITSAT|KCET|WBJEE)[^)]{0,30}\d{4}\s*\)?`. Nothing else changes.
- **R-34 markup_leak.** `find` matches a leak pattern (`\\[a-zA-Z]+\{?`, `<mi>&</mi>`, escaped tags as text). The multiset of digits in `find` equals that in `replace`. The replacement is plain text or MathML.
- **R-35 answer_form.** Additive. `find` is a substring of `replace` and `len(replace) > len(find)`. The added text matches a unit or rounding phrase (`(in N)`, `in cm`, `rounded to …`). The unit must agree with the unit the solution's final line uses.
- **R-36 notation.** A single expression. Edit distance ≤ 10 chars. The digit multiset is preserved, except for at most one restored symbol, exponent or bracket.
- **R-37 stem_data.** Additive. The added value **and its unit** appear verbatim in the stored solution (for example "95.5 × 10⁻³" / "10 cm" or the MathML equivalent). The blind solver, given the repaired stem, reproduces the key. Otherwise `faculty_review`.
- **R-38 option_repair.** Text before the first option marker is byte-identical. The edit touches only one option slot. **Auto only when the new option text is grounded:** the blank or missing option is the keyed answer *and* the solution's final value fills it (example: R011, where the solution shows equal forces, so 1 : 1). A missing *distractor* (for example R009/R010, option D missing while the key C is present) is authored content, so it goes to `faculty_review` with a suggestion only.
- **R-39 solution_fix / solution_missing.** The new solution's final value equals the stored key **and** the blind solve. The original key must itself be verified (R-40 check passes for the key). If the key is wrong, use `answer_key` instead.
- **R-40 answer_key.** Highest stakes.
  - (a) Value change. The blind solver (key, solution and comments withheld) must produce the proposed answer. **Plus at least one more independent signal:** the stored solution's final value equals the proposed answer, *or* a second blind solve with a different prompt seed agrees, *or* a numeric expression evaluated by the backend (safe AST evaluator) matches the proposed option value within 1 %. The old key must disagree with these signals. A student's claim never counts as a signal.
  - (b) Format repair (malformed mcq list). This is a deterministic normalisation (`["A, B, D"]` → `["A","B","D"]`, `["","B"]` → `["B"]`), auto-eligible only if the set of letters is unchanged **and** the blind solve agrees with that set. If the set changes, (a) applies.
- **R-41 type_mismatch.** The blind solver's count of correct options must match the new type (exactly 1 for scq, ≥ 2 for mcq). Changing to or from `integerQuestion` is always `faculty_review`.
- **R-42 Unsound or no valid option.** If the blind solver finds no correct option, or two correct options in an scq, the result is `defect / unsound`, routed to faculty. The system never picks "closest option" as the key.

**R-43. Confidence is computed, not asked for.** `confidence = calibrate(signals)` per the table below. The LLM's self-reported certainty can only **lower** it (subtract 0.15 if it reports < 0.5). It can never raise it.

| Signal pattern | Base confidence |
|---|---|
| Deterministic detector hit that by itself determines the verdict (blank option, duplicate options, literal LaTeX, exam tag, malformed answer, errorHistory fix, missing-figure reference with no images) | 0.95 |
| answer_key: blind solve + solution final + numeric check all agree on new answer | 0.95 |
| answer_key: blind solve + one more signal | 0.90 |
| no_error (calculable): blind solve == key == solution final | 0.92 |
| no_error (calculable): blind solve == key, solution unclear | 0.85 |
| no_error (recall/biology): LLM verification only | 0.75 |
| stem_data: value found verbatim in solution + repaired-stem solve reproduces key | 0.90 |
| Pure classification (language_mode, app_issue, display_issue with clean detectors) | 0.90 |
| not_actionable (gibberish + clean checks) | 0.85 |
| LLM-only defect judgement, no deterministic support | ≤ 0.70 |
| Any independent check disagrees with the chosen verdict | ≤ 0.55 → faculty_review |

Penalties: blind solver unavailable or failed −0.15. Rules-only fallback mode: cap at 0.70 (so nothing auto-applies without an LLM unless a detector alone determines the verdict). Injection-flagged report whose requested change matches the proposal: −0.20.

**R-44. Thresholds** live in `config.py` (env-overridable) and are shown read-only on the Settings screen: `AUTO_APPLY_MIN_CONFIDENCE=0.85`, `NO_CHANGE_MIN_CONFIDENCE=0.60`. A non-defect verdict below 0.60 is routed to `faculty_review`.

## 5. Deterministic detectors (run before any LLM call)

| Detector | Fires when | Supports |
|---|---|---|
| `option_count` | scq/mcq with ≠ 4 parsed options | option_repair |
| `blank_option` | an option marker followed by empty text | option_repair |
| `duplicate_options` | two options have equal normalised text | identical_options |
| `latex_leak` | `\\[a-zA-Z]+` in text nodes, `<mi>&</mi>` | markup_leak |
| `exam_tag` | R-33 pattern in question text | exam_reference |
| `figure_ref_no_image` | `figure|shown|diagram` in stem and `quesImages == []` | diagram |
| `answer_malformed` | answer fails canonical format (§1.3 of the data dictionary) | answer_key (format) |
| `answer_option_missing` | keyed letter not present or blank | option_repair / answer_key |
| `solution_final_vs_key` | last numeric value in solution ≠ keyed option value (tolerance 1 %) | answer_key / solution_fix (signal only) |
| `fixed_after_report` | `errorHistory[].at > reportedAt` | already_fixed |
| `spelling` | tokens not in wordlist with an in-list neighbour at distance ≤ 2 | spelling |
| `injection` | comment matches injection heuristics (R-50) | sets `injection_suspected` |

Detectors are pure functions with unit tests on the real 43 questions.

## 6. Untrusted input and prompt injection

**R-50. Comments are data.** Student comments are passed to the LLM only inside a `<student_reports>` JSON block, with `<`/`>` escaped. The system prompt states that the content is evidence, not instructions. Heuristic flags: `ignore (all )?previous`, `you are (now )?`, `system prompt`, `admin`, `mark (this|it) as`, `change the answer to`, role-play markers, and very long or encoded payloads.

**R-51. Injection never blocks analysis.** A flagged report is still triaged on the merits of the question. Example: R027, where the question is checked independently and the key is correct, so the verdict is `no_error`.

**R-52. Injection never authors an edit.** Any edit whose only support is an injection-flagged comment is dropped. If other evidence supports a defect, the case goes to `faculty_review` (R-30.4).

**R-53. Output can't escalate privileges.** The LLM output schema has no `route`, no `actor`, and no free-form "actions". Unknown keys are rejected (`extra="forbid"`).

**R-54. Replies never echo the injection.** The student reply never quotes the comment and never confirms any change the comment demanded.

## 7. Duplicates

**R-60. Grouping key = `questionId`.** All reports on one question form one **case**. Each report still gets its own result entry and its own verdict, because two students can complain about different things on the same question.

**R-61. Dedup of edits.** Identical proposals (same repair, field, find, replace) from several reports collapse into **one repair record** linked to all supporting report IDs. It is applied at most once. Each linked report shows the same route.

**R-62. Corroboration.** More clean reports agreeing raises **urgency**, never **confidence**. Popularity is not proof.

**R-63. "Mark as duplicate"** (faculty action) links a report to another report's outcome. The report inherits that verdict, and the audit records the link.

## 8. Student replies

**R-70.** 1–3 sentences, max 320 chars, no blame ("you're wrong"), no internal jargon (no "verdict", "taxonomy", "route").

**R-71. Truthful status.** `auto_apply` may say "fixed". `faculty_review` must say "a teacher is checking", never "fixed". `no_change` explains briefly why the question stands and, for calculable cases, gives the key step (for example "0.08 m is 8 cm, and the question asks in cm").

**R-72.** Same language register as the student where safe (Hinglish in, simple English with a light Hinglish touch out). Never translate content into another language (that is `language_mode`).

**R-73.** The backend checks the forbidden claims (`fixed|corrected|updated` when route ≠ auto_apply, accusatory phrases). On failure it uses the deterministic template for that verdict and route.

## 9. Faculty actions, rollback and audit

**R-80. Never overwrite originals.** `questions.original_json` is immutable (a DB trigger blocks UPDATE). Edits produce a new `question_revisions` row and update `current_json`.

**R-81. Faculty edits are re-validated.** When faculty edits a proposal, it goes through R-10 to R-14 again. Faculty *can* override the confidence threshold. Faculty *cannot* write outside the taxonomy scope. To make a scope-free change, they reject and handle it in the CMS. Taxonomy wins.

**R-82. Rollback.** Any applied revision can be rolled back if no later revision touched the same field. Otherwise later revisions must be rolled back first (LIFO). Rollback creates a new revision restoring `before`. It never deletes history.

**R-83. Audit is append-only.** Every state change writes an `audit_events` row: who (`system` / `ai:<model>` / `faculty:<name>`), what, before, after, rule IDs, and a hash chained to the previous row. There are no UPDATE or DELETE paths. `GET /api/v1/audit/verify` recomputes the chain.

**R-84. Confirmation.** Approve-apply, rollback and reject require a confirm dialog that shows the exact diff or effect.

**R-85. Faculty authorization** (decision 4; **implemented**, Phase 3). Every write endpoint (approve, reject, edit proposal, edit reply, investigate, duplicate, rollback, reopen, triage re-run) requires the `X-Faculty-Key` header, which must match the server-side `FACULTY_ACCESS_KEY` (constant-time compare). If the key is not configured, writes are **disabled** (fail closed, HTTP 503 `writes_disabled`). Reads stay public for the demo. The key never appears in frontend source: faculty type it into Settings and it is kept in `sessionStorage` for the tab only.

**R-86. Engine-mode honesty** (decision 5). A result produced without an LLM has `engine_mode = rules_only`, and its evidence starts with `"Rules-only:"`. The console shows a persistent "Rules-only (no AI)" label. README and PROMPTS.md state which mode produced the committed `results.json`. Deterministic output is never described as AI analysis.

## 10. Urgency (queue order), never confidence

**R-90** (implemented in `services/views.compute_urgency`, computed on read). `urgency = impact + volume + age + review_bonus`, capped at 100. The breakdown is stored and shown on hover.

| Component | Value |
|---|---|
| impact | answer_key / unsound / wrong_question 40 · option_repair / stem_data / diagram / identical_options / type_mismatch / solution_fix / solution_missing 30 · markup_leak / notation / app_issue 20 · spelling / noise / exam_reference / answer_form / wrong_chapter / syllabus 10 · non-defect 0 |
| volume | 8 × (clean reports − 1), max 24 |
| age | hours since first report ÷ 12, max 16 |
| review_bonus | +20 while a human decision is pending |

Why: a wrong key or broken option actively mis-marks every student who meets the question, so impact dominates. Age is capped so old cosmetic issues never outrank a fresh wrong key. Resolved cases drop to urgency 0.

## 11. Bonus findings (unreported defects)

**R-95.** `bonus_findings.json` is separate from `results.json`, and `results.json` has exactly one entry per supplied report (44). Each finding has `status`:
- `verified`: confirmed by a deterministic check whose evidence is quoted from the record (for example a literal `\AA`, `<mi>&</mi>`, or `/CC` where the solution's own unit is `/°C`);
- `suspected`: a judgement (LLM or rules) that needs a teacher (for example a factually wrong solution sentence, or a possibly altered statement).
Findings are produced by the engine's detectors over all 43 records (`scripts/scan_unreported.py`, Phase 4). They are **not** copied from the human reference notes.

## 12. Rules-only engine (Phase 4, implemented in `backend/app/triage/`)

**R-87. Rules-only confidence calibration.** `engine.CONFIDENCE` is the single table. Confidence says how strongly the record's own, deterministically re-checked evidence supports the verdict. It is never a model's self-report.

| Evidence pattern | Confidence |
|---|---|
| A structural fact decides it (blank/missing/duplicate option, LaTeX text, exam tag, figure reference without image, malformed key, fix recorded after the report) | 0.95 |
| Spelling: the correct form appears elsewhere in the same record | 0.90 |
| Answer form: the solution attaches one unit to the keyed value | 0.90 |
| Display / app / language complaint with clean structural checks | 0.85 |
| Unintelligible comment and clean checks | 0.85 |
| Key check with ≥ 2 deterministic signals (rules-only ceiling for any key judgement) | 0.70 |
| Correction grounded only in the student's comment; solution uses values the stem never gives; solution anomalies; mcq keyed with one letter | 0.70 |
| Key check with 1 signal (key supported) | 0.65 |
| Chapter: none of the filed chapter's terms occur in the question or solution | 0.65 |
| Key check with 1 signal (key contradicted) | 0.60 |
| Recall item: the key option's text leads the solution's first sentence | 0.60 |
| The solution contradicts itself about the statements the key depends on | 0.55 |
| Syllabus (complaint-only; the taxonomy says faculty confirm) | 0.50 |
| No deterministic check possible | 0.50 |

An injection-flagged report whose demand matches a proposed answer change loses 0.20, and the edit is dropped (R-52).

**Key-check signals** (`triage/answers.py`). These are derived from the stored record and never from the student's claim:

| Signal | Meaning |
|---|---|
| `solution_final` | the solution's final value or text matches exactly one option (0.2 % tolerance), or the integer key after a unit conversion or multiplier the stem asks for (e.g. "(in cm)", "value of 10 A") |
| `recomputed` | the expression equated to that final value re-evaluates to it |
| `steps` | other steps re-evaluate consistently and none is inconsistent |
| `explicit_letter` | the solution names the option |
| `equation` | an integer target solved from the record's own equation (stem template vs solution final, or the solution's last equation) |
| `text_support` | recall items only |

A key is **contradicted** only if the derived answer differs from the key **and** the keyed value appears nowhere among the solution's computed values. Otherwise the result is **ambiguous**, which goes to faculty. This prevents the 5fc60508 trap, where the last `=` gives 30 N but 20 N is also computed.

**R-88. Auto-eligibility in rules-only mode.** Only mechanical repairs whose correct text already exists can be auto-eligible:
- spelling corrected from another occurrence in the same record (R-31);
- `exam_reference` removal (R-33);
- `\frac{a}{b}` → `a/b` (R-34);
- answer-unit append taken from the solution (R-35).

Every one also needs a valid edit (R-10 to R-14), a passing guard, confidence ≥ 0.85, and no injection. **Answer-key, solution, stem and option changes never auto-apply without an independent solver (R-40, R-39, R-37, R-38).** `auto_apply` means *eligible*: Phase 4 applies nothing. Repairs are stored as `proposed`, and the case status is `auto_pending`.

**R-89. Student correctness is separate from key correctness.** The engine first decides whether the record supports its key (`key_status`). Only then does it compare the student's claim (`student_correct`: true/false/null). A claim is a lead, never a signal. In solution-mismatch and type complaints only first-person claims count ("should be", "I got"), because "answer is 20" usually quotes the stored key. Integer claims are compared exactly (3112.99 ≠ 3113).

**R-96. Evidence ≠ inference ≠ recommendation.** Each decision stores:
- `evidence`: observed facts, quoted from the record and its checks;
- `inference`: what the engine concludes;
- `recommendation`: what should happen next;
- `review_reason`: why a human must decide (always present for `faculty_review`).

`results.json` carries the evidence (plus a short `Review:` clause), at most **300 characters**. The full set is in `artifacts/triage_snapshot.json` and the API.

**R-97. Comment-to-record anchoring.** Spelling complaints use the part of the record the comment points to ("option A", "options", "solution") to decide which of two near-identical spellings is the wrong one. Without such a pointer, a near-miss pair is only a *suspected* bonus finding.
