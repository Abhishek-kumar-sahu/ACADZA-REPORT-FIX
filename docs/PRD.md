# PRD: Acadza Report → Fix

## 1. Vision

A broken question should stop hurting students **hours** after the first report, not weeks. Faculty time should go only to the decisions that need a subject expert.

## 2. Problem

- About 8 lakh questions. Students report errors in free text ("ans galat hai", "wrong", "asdfgh").
- Most reports are the student being wrong. Some are real defects. Some are app or display problems. A few are attempts to game the system.
- Today a faculty member reads each one by hand. Meanwhile a wrong key keeps marking correct students wrong.

In the sample: 44 reports on 39 questions. By manual inspection (DATA_DICTIONARY §4), about 27 point to a defect. That includes 9 that only faculty may fix: diagram, duplicate options, chapter, syllabus, unsound. About 10–11 are the student mis-solving, and 6–7 are display, app, language, already-fixed or unusable. Two traps stand out. In R004 the student's number is wrong *and* the key is wrong. In R027 a prompt injection sits on a correct question.

## 3. Users

| Persona | Context | Needs |
|---|---|---|
| **Meera, Physics faculty (primary)** | Reviews a batch at 10 PM after teaching. About 60 cases. A laptop at 1366×768 or 1440×900. | See only what needs her. Trust the math check without redoing it. One-key approve. A safe undo. |
| **Rahul, Content lead** | Owns question-bank quality across subjects. | Which defects keep coming back, what was auto-applied, an audit trail he can defend. |
| **Student (17, pre-JEE/NEET, stressed)** | Reports from a phone mid-practice. | A quick, kind, true answer. Either "you were right, fixed" or "here's the step you missed". |

## 4. Pain points → design response

| Pain | Response |
|---|---|
| Reading 60 raw reports one by one | Grouped by question, urgency-sorted, safe fixes already applied |
| "Is the AI just agreeing with the student?" | A blind solve that never sees the key or the comment, with evidence shown next to the verdict |
| Fear of the AI breaking content | Field-level taxonomy scope in code, a diff before any write, rollback, an append-only audit |
| Raw HTML/MathML is unreadable | Rendered question with native MathML. Raw source only on request. |
| Replies are slow or cold | A pre-written reply that matches the actual outcome, editable |

## 5. Goals / non-goals

**Goals**
1. All 44 reports triaged, with a valid `results.json` in the exact README schema.
2. Zero unsafe auto-edits: every auto-applied edit passes the scope and guard rules.
3. A faculty member clears a typical case in under 30 seconds.
4. Every action is auditable and reversible.

**Non-goals**
- Authoring new content (distractors, figures, translations). We suggest. Faculty authors.
- Student-facing app changes. We produce the reply text only.
- Multi-tenant auth or roles. See open question Q-4.
- Editing metadata (chapter or subject). Faculty handles it in the CMS.

## 6. Functional requirements

| ID | Requirement |
|---|---|
| FR-1 | Import the 3 datasets with hash verification. Originals are never modified. |
| FR-2 | Group reports into one case per `questionId`, with a per-report verdict inside the case. |
| FR-3 | Run the 13-stage triage pipeline (SYSTEM_ARCHITECTURE §4) for every report. |
| FR-4 | Produce `results.json`: one entry per report, the exact README fields, validated by `scripts/validate_results.py`. |
| FR-5 | Auto-apply only edits passing RULES R-30 to R-42, to a working copy, with a revision row. |
| FR-6 | Dashboard metrics computed live from the DB (DESIGN §6.1). |
| FR-7 | Queue filters: status (all / needs review / confirmed defects / auto-fixed / no change / rejected), subject, verdict, confidence band, priority band. Search by report or question ID. |
| FR-8 | Case detail: rendered question + options + key + solution, metadata, reports, verdict, confidence, evidence, verification panel, diff, reply, audit. |
| FR-9 | Field-level diff with highlighted removed and added spans, a rendered before/after preview, and a semantic summary for answer changes ("Key: C (130 V) → A (50 V)"). |
| FR-10 | Actions: approve, edit proposal, reject, request investigation, mark duplicate, rollback, reopen. Each writes an audit event. Destructive ones need confirmation. |
| FR-11 | Reply preview with editing, and a check that the reply truthfully matches the route. |
| FR-12 | Audit history screen with filters and hash-chain verification. |
| FR-13 | AI activity screen: per-call provider, model, prompt version, latency, tokens, status, mode (LLM or rules-only). |
| FR-14 | Settings: reviewer name (stored locally and sent as actor), read-only thresholds, provider status, data hashes. |
| FR-15 | System-originated cases for unreported defects (bonus), kept separate from `results.json`. |

## 7. Non-functional requirements

- **Performance:** the queue API responds in under 200 ms for 1k cases, and first paint happens under 1.5 s on the free tier once the service is warm.
- **Accessibility:** WCAG 2.1 AA contrast, full keyboard operation, visible focus, `aria-live` toasts.
- **Reliability:** pipeline failures are isolated per case. The provider fallback is logged.
- **Security:** keys stay server-side, input is validated, HTML is sanitised, and the audit is append-only.
- **Cost:** about 3 LLM calls per *question* (not per report). The total budget for the full run is stated in AI_ENGINE.md.

## 8. User stories and acceptance criteria

1. *As Meera, I open the console and immediately see what needs me.* AC: the dashboard shows the "Needs your decision" count and the top 5 urgent cases, and each links to the case.
2. *As Meera, I check a wrong-key claim without solving it myself.* AC: the case shows blind-solve answer, solution final value, stored key, and student claim side by side, with ✓/✗ against the key.
3. *As Meera, I approve a fix knowing exactly what changes.* AC: the diff highlights only the changed span. The confirm dialog repeats it. After approval, the rendered question updates and an audit row appears.
4. *As Meera, I undo a bad auto-fix.* AC: rollback restores the previous value, writes a revision and audit row, and the case returns to "Needs review".
5. *As Meera, I edit the AI's proposal.* AC: the edited proposal is re-validated, out-of-scope edits are refused with the rule ID, and valid ones apply.
6. *As a student, I get a reply that doesn't lie.* AC: no "fixed" text unless the route is auto_apply or the edit was approved and applied.
7. *As Rahul, I can prove who changed what.* AC: the audit shows actor, time, before and after, and the chain verifies.

## 9. MVP scope

All of FR-1 to FR-14, plus FR-15 as a read-only list. Single shared deployment, no login (Q-4).

## 10. Roadmap (post-MVP)

1. A "same root cause" cluster across questions (for example the `<sup>o</sup>C` degree bug likely affects thousands of imports). One fix template, bulk review.
2. Report-quality feedback to students. Reward accurate reporters and surface them faster.
3. Evening theme, a reduced-glare palette for night review.
4. Per-institute faculty routing by subject.
5. Telemetry on how often each question gets "wrong attempt + report", used to find silent defects.

## 11. Success metrics

| Metric | Target (week 1) |
|---|---|
| Median time from first report to fix live (auto + approved) | < 24 h |
| Auto-apply precision (faculty rollbacks ÷ auto-applies) | < 2 % rollbacks |
| Faculty minutes per case | < 0.5 |
| Unsafe edit rate (scope or guard violations reaching the DB) | 0 |
| Reply edit rate (faculty rewrites the AI reply) | < 30 % |
