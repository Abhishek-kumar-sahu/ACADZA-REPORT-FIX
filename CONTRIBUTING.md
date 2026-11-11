# Contributing

1. **Read `docs/MEMORY.md` first.** Then read `docs/RULES.md` before touching triage, validators or routing.
2. **Never modify `data/*.json`.** Import verifies their hashes.
3. **Safety rules live in code with IDs.** A change to routing or validation must cite the rule ID (`R-xx`) in the code comment and in the test name, and update RULES.md in the same commit.
4. **Prompts are versioned files.** Never edit `prompts/*.vN.md` in place. Add `vN+1`, mirror it into PROMPTS.md (a test enforces this), and log the reason in PROMPTS.md §A4.
5. **No fake data in the UI.** Every number on screen comes from the API.
6. **Docs track code.** If behaviour changes, update the relevant doc and `docs/TASK.md` / `docs/MEMORY.md` in the same PR. Tasks are checked only after verification.
7. **Before a PR:** `pytest backend/tests -q`, `python scripts/validate_results.py`, `npx playwright test`.
8. **Commits:** imperative mood, one concern per commit. Mark deliberate shortcuts with a `ponytail:` comment that names the ceiling.
