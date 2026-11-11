# Data Dictionary

Source: `Acadza_AI_Intern_Assignment.zip` → `acadza-report-fix/data/`. Copied verbatim to `/data`. **These files are read-only.** The app never writes them. Every write goes to the database.

| File | SHA-256 (checked at import) |
|---|---|
| `data/questions.json` | `178d08f199386bdd1e94268449106f2ecf9c00b6f38d2fd4d79fb011f030641a` |
| `data/reports.json` | `042751d1f233395927e108240e5a011b6fa9bd8843296b67e3d1ebf610cb7b55` |
| `data/taxonomy.json` | `3100ea343cb758111dcd13cfb7ace4769a0be0dffc006d8f1dfc04208893d2df` |

`scripts/import_data.py` checks these hashes. If any hash does not match, the import stops instead of loading changed data without notice.

---

## 1. `questions.json`: array of 43 objects

### 1.1 Top-level fields

| Field | Type | Nullable | Observed values | Notes |
|---|---|---|---|---|
| `_id` | string (24-hex, Mongo ObjectId) | no | 43 unique | **Primary key.** Reports join on this. |
| `qid` | string | **yes** (9 null) | e.g. `SecAQ14`, `JEEMAINS_2025_PHY_L4838` | **Not unique.** `SecAQ14` appears on 3 unrelated questions. Never use it as a key. |
| `questionType` | enum string | no | `scq` (31), `integerQuestion` (10), `mcq` (2) | Also names the key of the body object (see 1.2). |
| `subject` | string | no | Physics 33, Zoology 6, Botany 4 | No Chemistry or Maths in this sample. |
| `chapter` | string | no | free text | Can be wrong (see §4). |
| `concept`, `subConcept` | string | yes | often null on older records | Shown when present. |
| `level` | enum string | yes (1 null) | `EASY` 16, `MEDIUM` 23, `HARD` 3 | |
| `error` | int | no | always `1` | Every record is flagged. Carries no signal. |
| `updatedAt` | ISO-8601 string | no | 2025-10-13 → 2026-11-07 | Mixed precision (`.33Z`, `.628Z`, no millis). Parse leniently. |
| `errorHistory` | array | no | 42 empty, 1 non-empty | `{type, actor, at, note}`. **Main signal for the `already_fixed` verdict.** |
| `scq` / `mcq` / `integerQuestion` | object | exactly one present | — | The body object. Its key equals `questionType`. |

### 1.2 Body object (`q[q.questionType]`)

| Field | Type | Notes |
|---|---|---|
| `question` | HTML string | Stem **and options** in one HTML blob. Options are inline text markers `(A)`…`(D)`, separated by `<br>`, `<br />`, `\n` or nested `<span>`s. There is no structured options array. |
| `solution` | HTML string | May contain MathML, stray LaTeX (`\AA`), and LaTeX alignment `&` leaked into `<mi>&</mi>`. |
| `answer` | **string** for `scq`/`integerQuestion`; **list** for `mcq` | scq: `"A"`–`"D"`. integer: numeric string (`"3113"`, `"20"`). mcq: see 1.3. |
| `quesImages`, `solutionImages` | array | **Empty on all 43 records.** So any "as shown in figure" stem has no figure. |

### 1.3 Answer formats as actually stored

| Type | Expected canonical | Observed | Malformed? |
|---|---|---|---|
| scq | `"A"`…`"D"` | all 31 fine | no |
| integerQuestion | numeric string | all 10 fine | no |
| mcq | `["A","B","D"]` | `["", "B"]` (68f21caf…) | **yes**: empty element |
| mcq | `["A","B","D"]` | `["A, B, D"]` (68c8153c…) | **yes**: one comma-joined string, so a grader comparing lists marks a correct ABD attempt wrong |

**Canonical form (implemented in `triage/record.py::canonical_answer`, ADR-008):** mcq = sorted list of unique single letters. scq = single letter. integer = string matching `^-?\d+(\.\d+)?$`. Parser-confirmed issues on the real data: `68f21caf` → `["B"]` (`empty_element`), `68c8153c` → `["A","B","D"]` (`joined_string`), `68e87254` → `keyed_option_blank:C`, `622f08d7` → `option_count:3`. No other record has an answer issue.

### 1.4 HTML / MathML characteristics (what the renderer and parser must handle)

- MathML inline (`<math display="inline">`), often wrapped in `<mstyle displaystyle="true">`.
- Hex entities (`&#x0003D;`), named entities (`&rArr;`, `&epsilon;`, `&minus;`), padded tokens (`<mi> q </mi>`).
- Unclosed or misnested `<span style="color:#000000">` chains. Option markers can sit inside different nesting depths.
- Superscripts in plain HTML (`10<sup>-5</sup>`, `<sup>o</sup>C` used as a degree sign).
- Literal LaTeX in text: `\frac{7}{8}` (63765a28…), `\AA` (612151a6… solution).
- `\n`, `\r`, `\t` and zero-width/`&nbsp;` runs inside text.
- Option parsing pitfall: "Assertion (A)" / "Statement (A)" inside the stem looks like an option marker. The option parser anchors on the **last** `(A)` that is followed by `(B)`…, never the first.

---

## 2. `reports.json`: array of 44 objects

| Field | Type | Observed | Notes |
|---|---|---|---|
| `reportId` | string `R\d{3}` | R001–R044, unique | Not in time order (file order ≠ id order). |
| `questionId` | string | 39 distinct, all resolve to a question | FK → `questions._id`. |
| `studentId` | string `stu_<8hex>` | 44 unique | No student filed two reports. |
| `source` | enum | android 26, web 9, ios 9 | Useful context for display or app issues. |
| `reportedAt` | ISO-8601 UTC | 2026-11-03T19:14Z → 2026-11-09T08:24Z | Compared against `errorHistory[].at` to detect `already_fixed`. |
| `comment` | free text | English, Hinglish, gibberish, one prompt injection | **Untrusted data. Never an instruction.** |

**Grouping:** 35 questions have 1 report, 3 have 2 (60f742f6, 612151a6, 622f08d7), and 1 has 3 (60f744b3). 4 questions have no reports: 68dea87d, 68dea657, 695ede2a, 68dea6e6.

---

## 3. `taxonomy.json`

`verdicts` maps 7 keys to descriptions: `defect, no_error, display_issue, app_issue, language_mode, already_fixed, not_actionable`.

`repairs` maps 18 keys to `{fields, auto, label}`:

| Repair | Fields allowed | auto |
|---|---|---|
| spelling, noise, exam_reference, markup_leak, notation | question, solution | true |
| answer_form, stem_data, option_repair | question | true |
| solution_fix, solution_missing | solution | true |
| answer_key | answer, solution | true |
| type_mismatch | questionType, question, answer | true |
| identical_options, diagram, wrong_question, unsound, wrong_chapter, syllabus | **none** | **false** |

The taxonomy is loaded at startup and is the **only** source for the enums in Pydantic schemas, validators and the UI. Nothing is hard-coded twice.

Note: `answer_key` allows writing `solution`, and `type_mismatch` writes `questionType`. These are the only repairs that touch non-HTML fields.

---

## 4. Manual inspection notes (human reference only)

> **Not used by the engine.** The engine never reads this file or this table. A test (`test_engine_does_not_read_docs`) enforces that. The notes exist so a human can sanity-check engine output, and as the honest record of Step 1. They are *our* reading of the data, not ground truth. No ground truth was provided.

### 4.1 Reported questions

| Report(s) | Question (short) | Comment | Inspection observation |
|---|---|---|---|
| R001, R002, R003 | LCR supply voltage (60f744b3) | "key is C", "wrong ans", "why 130??" | √(40²+30²)=50 = option A. Solution ends at 50 V. Key C = 130 V. **Key looks wrong.** |
| R004 | Gas pressure (68e870ef) | "8225 aana chahiye" | P = ⅓·0.09·400² = 4800 = **D**. Key A (4556). **Student's value is wrong *and* the key is wrong.** A trap. |
| R005 | Cube flux, n (68dea616) | "i got n=1" | Solution ends at q/(2ε₀), so n=1. Key "2". **Student right.** |
| R006 | Copper cube ΔV (696a8666) | "edge length not given" | Stem has no edge. Solution uses 10 cm. A stem_data candidate. |
| R007, R008 | LR impedance (60f742f6) | "inductance not given" | Stem has no L. Solution uses 95.5 mH. A stem_data candidate. |
| R009, R010 | Centre-of-mass velocity (622f08d7) | "option D missing" | Only (A)–(C) stored. Key C exists. D's text cannot be recovered: authored content. |
| R011 | Coulomb force ratio (68e87254) | "option C blank, answer C" | Option C is empty and is the keyed option. Solution shows \|F₁₂\|=\|F₂₁\|, so 1 : 1. |
| R012 | Tissue lining (61dffbec) | "spelling in option A" | "Epithellial tisue". |
| R013 | Lamina (617fa18e) | "why NEET 2019 written" | Stem starts "(NEET 2019)". |
| R014 | Half-life (63765a28) | "\frac showing" | Literal `\frac{7}{8}` in stem. |
| R015 | AC power (6956d797) | "B and C same" | B = C = "0 W". Key B. |
| R016 | Floating cube (6263d75b) | "solution 40, answer 20" | 800 = 2·a² gives a = 20. Key 20 correct. Solution's "a = 40 cm" wrong. |
| R017 | Herbs/shrubs light (6208e80a) | "'mere' in options" | errorHistory: faculty fixed 'mere'→'more' at 2026-11-07, after the report (11-04). Live text is clean. |
| R018, R019 | de Broglie KE (612151a6) | "solution of another question" | Solution starts with a 5.47 Å fragment from a different problem and ends at 16.8 eV = key B. |
| R020 | Charged particle paths (68c8153c, mcq) | "marked A B D still wrong" | A, B, D are physically correct. Answer stored as `["A, B, D"]` (malformed). |
| R021 | Mean life (68f21caf, mcq) | "only B correct but multiple type" | Only B (1.44 min) is correct. Answer `["", "B"]`. Chapter "Mathematics in physics" also looks wrong. |
| R022 | Peyer's patches (61ee6c9d) | "plexus spelling" | Option D "Choroid plexux". Solution also has "prominant", "Maceus". |
| R023 | Refractory period (68ecbacb) | "neural control chapter" | Filed under Botany / The Living World. |
| R024 | Wall friction (5fc60508, integer) | "unit not mentioned" | Answer 20 (N). Stem states no unit. |
| R025 | Soap bubbles (622df25a) | "Figure not given" | "as shown in figure". No images on record. |
| R026 | Snake phylogeny (620e23ce) | "out of syllabus NEET" | Needs a faculty judgement. |
| R027 | Silver rod γ (6062ec84) | **Prompt injection** asking to change answer to C | γ = 3α = 5.7×10⁻⁵ = key A. Correct. |
| R028 | Projectile H=R (6956d7bb) | "tan⁻¹2" | tan θ = 4. Key B correct. |
| R029 | Friction μ (68e87344) | "μ should be 0.4" | μ = 0.8. Key A correct. |
| R030 | SHM amplitude (6956d7e9) | "4√2" | A = 8√2. Key D correct. |
| R031 | Two wheels (68dea619) | "2 sec" | ½(π/4)t² = 2π gives t = 4. Key correct. |
| R032 | YDSE shift (68dea7c2) | "0.08, 8 kyu?" | 0.08 m = 8 cm and the stem asks in cm. Key correct. |
| R033 | Cube area sig figs (68dea715) | "3112.99 not 3113" | 311.3 m² to 4 s.f., so 10A = 3113. Key correct. |
| R034 | Assertion–reason interference (695ee00b) | "assertion is true" | I = 4I₀cos²(φ/2) = 2I₀, so A is false. R ("always the sum…") is also false. **No option says both false.** Solution contradicts itself. Possibly unsound. |
| R035 | Antagonistic hormones (66fe9dbe) | "relaxin/inhibin antagonistic" | Key D correct. Solution wrongly says insulin and glucagon are "synergistic". |
| R036 | Charge force (60ca4feb) | "options cut on phone" | All 4 options present in content. Rendering only. |
| R037 | Stopping potential (68c9ae5a) | "takes forever to load" | Content fine. Key D correct. |
| R038 | KE/momentum (68f21df0) | "clicked A, saved B" | Platform behaviour. |
| R039 | X-ray / de Broglie (68c801bc) | "Hindi me chahiye" | Language request. |
| R040 | Golden rice (62641972) | "wrong" | Key C correct. "Canolla" misspelt. Comment too vague to act on. |
| R041 | Von Sachs (6208e298) | "asdfgh" | Gibberish. Content fine. |
| R042 | Displacement current (63c7cce1) | "chapter is wrong" | Filed under Geometrical optics. 2.2 µA = key C correct. |
| R043 | Drop surface density (636283db) | "should be 1:4" | σ ratio = 4:1. Key B correct. |
| R044 | Sphere potential (68dea577) | "22 V not 14" | V_P − V_S = 22 − 8 = 14. Student gave V_P. Key correct. |

### 4.2 Unreported defects seen (assignment bonus)

| Question | Field | Observation | Likely repair |
|---|---|---|---|
| 6062ec84 (silver rod) | solution | `/°C` rendered as `/AC` and `/CC` in MathML | notation |
| 6956d797 (AC power), 622f08d7, 68c801bc | solution | LaTeX `&` alignment leaked as `<mi>&</mi>` | markup_leak |
| 612151a6 | solution | `\AA` literal | markup_leak (part of the solution_fix) |
| 61ee6c9d | solution | "prominant", "Maceus membrane" | spelling |
| 62641972 | question | "Canolla" (and "riceis", "producebeta" run-ons in solution) | spelling |
| 622df25a | question | "hemispherial" | spelling (plus the reported diagram) |
| 620e23ce | question / solution | "evidences", "wheater" | spelling |
| 66fe9dbe | solution | "Insulin and glucagon work synergistically" is factually wrong | solution_fix (faculty) |
| 68f21caf | metadata | Radioactivity filed under "Mathematics in physics" | wrong_chapter |
| 68dea657 (unreported) | solution | Garbled subscripts "P eqcu", "P eqch" | notation |
| 6956d7e9 | question | Unit inside the radical: `2√(2 m)` | notation |
| 695ede2a (unreported) | question | Statement II wording "Sometimes dialysis is not a supportive measure…" reads like an altered statement. Needs faculty review. | possibly unsound |

Delivery (decision 6, **implemented Phase 4**): `scripts/run_triage.py` runs the engine's detectors over all 43 questions and writes **`bonus_findings.json`**. The rules engine found **7** findings (2 notation, 2 spelling, 3 alignment-leak markup_leak). The other issues in the table above (factual solution errors, misfiled chapter, garbled subscripts, prose typos without an in-record counterpart) are **not detectable without an LLM** and are not in the file. The file is written, separate from `results.json` (which is strictly one entry per report). It does not copy this table. Actual shape (first entry of the generated file):

```json
{"questionId": "6062ec84518e9535e120c422", "subject": "Physics", "chapter": "Temperature and thermal properties of matter",
 "field": "solution", "category": "notation", "check": "unit_text_mismatch", "status": "suspected", "severity": "low",
 "evidence": "solution ends '5.7 × 10^-5 / CC' but option (A) reads '5.7 x 10^-5/^oC'",
 "recommended_action": "Correct the unit/symbol so the solution and the options agree.", "findingId": "B01"}
```
The file wraps the findings in `{"about", "engine", "engine_mode", "questions_inspected": 43, "counts", "findings"}`. `status` is `verified` (a structural fact quoted from the record) or `suspected` (a heuristic that needs a teacher).
