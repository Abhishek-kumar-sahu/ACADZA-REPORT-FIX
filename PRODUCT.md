# PRODUCT

**1. Who loses the most when a question is broken?**
The student who got it *right*. A wrong key (R001–R003: the solution says 50 V, the key says 130 V) marks every correct attempt wrong. That costs marks and confidence. Worse, it teaches the student to doubt correct reasoning weeks before JEE. The student who reports is only the visible one. The many who silently "learn" the wrong answer lose more.
*Design response:* urgency is driven by **impact on students**: wrong key and broken options first, typos last (RULES R-90). Fixes that can be proven are applied immediately instead of waiting for a human. Each student gets a reply that either says "you were right, it's fixed" or shows the one step they missed. It is never vague, and it never claims "fixed" when the fix is still under review.

**2. What would I never let AI auto-apply?**
Anything where the AI would be **authoring** content rather than **restoring** it: new distractors (R009/R010 missing option D), figures, translations, or whole new solutions to a question whose key isn't independently verified. The same goes for any answer-key change backed only by the model's own solve, and any edit whose only supporter is a comment that tried to give instructions (R027). The rule of thumb: auto-apply only when the correct value already exists *somewhere in the record* (the solution, a second independent solve) and the change is surgical and scope-checked. A broken question hurts students for a day. A confidently wrong "fix" hurts them with the system's authority behind it.

**3. One metric for week 1**
**Rollback rate of auto-applied fixes** (faculty rollbacks ÷ auto-applies). It is the single number that tells us whether automation can be trusted. Target < 2 %. If it is higher, the confidence threshold tightens for that repair type before anything else is tuned. A close second: median hours from first report to fix live.

**4. An idea beyond the brief**
**Silent-defect radar.** Most broken questions are never reported. Students assume they're wrong. Acadza already has attempt data. A question where the strongest students (by overall accuracy) disproportionately pick the *same wrong* option is almost certainly mis-keyed. Run the same blind-solve pipeline on those questions *before* anyone reports them. In this 43-question sample, a manual pass found unreported issues on 14 questions, mostly minor, but including a factually wrong solution line and a misfiled chapter. That suggests the unreported pool is large. One more step: cluster root causes across questions (for example `<sup>o</sup>C` converted to "AC"/"CC" by an importer) and fix them in bulk with a single faculty approval.
