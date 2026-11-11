# DESIGN: Acadza Report → Fix faculty console

> **Revision 2 (Phase 6, 2026-11-11).** This replaces the Phase 1 light "warm paper" direction. The product owner set a dark charcoal / off-white / muted-emerald identity. Every value here is implemented in `frontend/css/tokens.css`; contrast figures were **measured** with the WCAG relative-luminance formula, not estimated.

## 0. Non-negotiable constraints

The product is **Acadza: an academic quality-management workspace** for a teacher reviewing student-reported errors late at night. It must look like mature enterprise software. These rules are checked per screen in §11 before Phase 6 is declared complete.

**Prohibited**
1. Purple or blue-purple gradients or backgrounds, and any decorative gradient.
2. Neon glows, coloured shadows, and glassmorphism or backdrop blur used as decoration.
3. Oversized rounded cards (radius above 8 px), floating decorative shapes, illustrations, mascots, emoji.
4. Animation that does not orient the user (no shimmer loops, no bouncing, no count-up numbers, no parallax).
5. Hard-coded or sample metrics. Every number comes from the API. "Unknown" is shown as "—", never invented.
6. Icons used as decoration. An icon appears only next to a label, or as a state glyph with text.
7. Copying another product's layout. Linear, Raycast and Vercel are references for *discipline* (density, alignment, restraint), not for layout.

**Required**
1. Typography, alignment, spacing and hierarchy carry the design, not colour.
2. Colour is reserved for **state**: verdict, route, status, diff and errors. Everything else is neutral.
3. Academic content (question, options, MathML) is never overlapped, truncated or recoloured by UI decoration.
4. Every visual element serves a task: knowing what is wrong, why the system thinks so, the evidence, what changes, and what to do next.
5. Compact data tables with 40 px rows and tabular numerals.
6. One design system. Pages compose shared components and never restyle them locally.

## 1. Identity

- **Wordmark:** "Acadza" set in Inter 600, with a small `Report → Fix` product label in ink-3. No logo glyph.
- **Voice in the UI:** plain, specific, never alarmist. "Answer-key change needs your approval", not "Critical alert!".
- **Theme:** dark charcoal canvas, slightly warm-neutral (green-grey undertone), off-white text, and a single muted emerald accent for primary actions and focus.

## 2. Tokens (three layers)

**Primitives** (raw values; never used directly by components):
```
--c-gray-950 #0F1110   --c-gray-900 #161917   --c-gray-850 #1C201E   --c-gray-800 #232825
--c-gray-700 #2A2F2C   --c-gray-600 #3B413D   --c-gray-500 #646C67   --c-gray-400 #8E8D87
--c-gray-200 #B9B7B0   --c-gray-50  #E9E7E1
--c-emerald-500 #4CB38C  --c-emerald-900 #0B1A14  --c-red-400 #E07A70  --c-amber-400 #D6A548
--c-steel-300 #8FB3BF
```

**Semantic** (what components use):

| Token | Value | Use | Measured contrast |
|---|---|---|---|
| `--bg` | gray-950 | app canvas | — |
| `--surface` | gray-900 | panels, tables, sidebar | — |
| `--raised` | gray-850 | modals, popovers, focused rows | — |
| `--hover` | gray-800 | row/button hover | — |
| `--line` | gray-700 | dividers (decorative) | 1.30:1 on surface |
| `--line-strong` | gray-600 | table header rule, card edge | 1.69:1 |
| `--line-input` | gray-500 | input and checkbox borders (WCAG 1.4.11) | **3.28:1** surface, 3.50 canvas, 3.05 raised |
| `--ink` | gray-50 | primary text | 15.3 canvas · 14.3 surface · 13.3 raised · 12.1 hover |
| `--ink-2` | gray-200 | secondary text | 9.4 · 8.8 · 8.2 · 7.5 |
| `--ink-3` | gray-400 | meta and labels | 5.7 · 5.3 · 4.95 · **4.50 (floor; avoid on hover)** |
| `--accent` | emerald-500 | primary button, focus ring, links | 7.3 · 6.9 · 6.4 · 5.8 |
| `--on-accent` | emerald-900 | text on accent buttons | 6.94 on accent |
| `--danger` | red-400 | defect, destructive, removed | 6.5 · 6.1 · 5.6 · 5.1 |
| `--warn` | amber-400 | needs review, limitations | 8.4 · 7.9 · 7.3 · 6.7 |
| `--info` | steel-300 | system / informational | 8.5 · 7.9 · 7.4 · 6.7 |
| `--del-bg` / `--del-ink` | #3A201D / #F2B5AE | removed text in diffs | 8.54 |
| `--ins-bg` / `--ins-ink` | #16362A / #B5E6CF | added text in diffs | 9.52 |

State "soft" fills are the state colour at 12–14 % alpha over `--surface`, with text in the full state colour.

**Component tokens:** `--btn-h: 32px`, `--row-h: 40px`, `--radius-sm: 4px`, `--radius: 6px` (maximum anywhere: 8 px), `--sidebar-w: 224px`, `--focus: 0 0 0 2px var(--bg), 0 0 0 4px var(--accent)`.

**Spacing:** a 4 px scale (`--s1` 4 … `--s8` 48). **Elevation:** borders only. Modals use `--raised` plus a 1 px `--line-strong` border and a neutral 24 px shadow at 40 % black. There is never a coloured shadow.

## 3. Typography

| Role | Spec |
|---|---|
| UI | Inter (self-hosted variable woff2, OFL, `frontend/assets/fonts`), 13.5/20 |
| Page title | Inter 600, 20/28, letter-spacing −0.01em |
| Section label | Inter 600, 11/16, uppercase, +0.06em, ink-3 |
| Table | 13/18, `font-variant-numeric: tabular-nums` |
| **Academic content** | Inter 400, **16/26**, ink, max width 72ch. MathML at 1.08em in the system math font (`math` family, STIX/Cambria Math fallback). |
| IDs, field names, find/replace | `ui-monospace, "Cascadia Code", Consolas, monospace` 12.5/18 |

## 4. Layout

```
┌────────────┬─────────────────────────────────────────────────────────────┐
│ Acadza     │ Page title                        ● API ok   🔑 Key: verified│
│ Report→Fix │ one-line context                                            │
│            ├─────────────────────────────────────────────────────────────┤
│ Overview   │                                                             │
│ Report Queue│  page content (max 1440px, 24px gutters)                   │
│ Faculty Review 9                                                         │
│ Quality Audit                                                            │
│ Revision History                                                         │
│ Audit Logs │                                                             │
│ Settings   │                                                             │
│            │                                                             │
│ rules-only │                                                             │
│ engine     │                                                             │
└────────────┴─────────────────────────────────────────────────────────────┘
```

- The sidebar is fixed at ≥ 1024 px. Between 720 and 1023 px it collapses to an overlay opened by a menu button. Below 720 px the top bar holds the menu, and tables become stacked rows.
- The top bar always shows backend status (from `/health`) and faculty-key status (none / verified / rejected). The key status links to Settings.
- The sidebar footer always discloses the engine mode from `/settings` (e.g. "Rules-only engine · no AI").

## 5. Components

| Component | Spec |
|---|---|
| Button | 32 px high, 6 px radius. Variants: **primary** (accent fill, on-accent text; one per region), **secondary** (surface + line-input border), **danger** (danger text and border; filled only inside a confirm dialog), **ghost** (text only). Disabled at 45 % opacity and `aria-disabled`. While pending, the label becomes "Working…" and the button is disabled (double-submit guard). |
| Input / select / textarea | 32 px, `--line-input` border, focus ring `--focus`. Labels always visible (no placeholder-only labels). |
| Badge | 20 px, 4 px radius, soft fill + state text, 11.5 px 500. Always contains text. |
| Verdict badge | defect = danger; no_error / not_actionable / language_mode = neutral; display_issue / app_issue = info; already_fixed = accent |
| Status badge | untriaged neutral · needs_review warn · auto_pending info · approved accent-outline ("Approved — not executed") · auto_fixed accent ("Applied") · rejected neutral · investigating warn · rolled_back neutral |
| Confidence meter | `0.70` + a 4-segment bar + band word. **Always** followed by the confidence basis in a tooltip, and in rules-only mode by "ceiling 0.70 for key checks". |
| Urgency | integer + 3 px bar in ink-2; breakdown in a tooltip (impact · volume · age · review). Never coloured like confidence. |
| Table | sticky header, 40 px rows, row hover `--hover`, the whole row a link, `j`/`k` move, `Enter` opens. Numeric columns right-aligned. |
| Callout | 1 px left rule in the state colour plus a soft fill. Used for **limitations** (warn), **errors** (danger) and **system notes** (info). Never decorative. |
| Diff | see §7 |
| Dialog | native `<dialog>`, focus trapped, `Esc` closes, focus returns to the trigger. Destructive confirm buttons repeat the verb ("Execute repair", "Roll back revision 3"). |
| Toast | bottom-right, `role="status"`, 6 s, at most 3. Errors carry the request ID. |
| Tooltip | native `title` plus `aria-describedby` text for technical terms (route, auto_pending, R-40 …) via the `term()` helper. |
| Skeleton | static blocks at the real row/card size (no shimmer animation; constraint 4). |
| Empty state | one sentence saying why it is empty, plus the next step. |

## 6. Screens (all data from real endpoints)

| Route | Screen | Endpoints |
|---|---|---|
| `#/` | **Overview**: pending faculty actions first, then urgent cases, metrics strip, reports by subject and source, verdicts, 7-day resolutions, recent activity, engine status | `/dashboard`, `/cases?status=approved` (awaiting execution) |
| `#/queue` | **Report Queue**: filters (status, subject, verdict, confidence, priority), search, sort, pagination; complaint category per question | `/cases`, `/reports?limit=200` (complaint classes), `/taxonomy` |
| `#/review` | **Faculty Review**: tabs for Needs decision / Auto-eligible / Approved, awaiting execution / Investigating | `/cases?status=…` |
| `#/case/<qid>` | **Question Review Workspace** (main product) | `/cases/<qid>`, all write actions |
| `#/quality` | **Quality Audit**: unreported findings (verified/suspected), triage runs, verdict and route distribution of the current results | `/bonus-findings`, `/triage/runs`, `/results` |
| `#/revisions` | **Revision History**: every revision, reverted-by links, rollback | `/revisions`, `POST /revisions/<id>/rollback` |
| `#/audit` | **Audit Logs**: filterable log + hash-chain verification | `/audit`, `/audit/verify` |
| `#/settings` | **Settings**: connection, health, engine/provider, thresholds, data hashes, faculty key, actor name, disclosure | `/health`, `/settings`, `/auth/status`, `POST /auth/verify` |

### 6.1 Question Review Workspace

```
┌ ← Queue   In a LCR circuit the pd between…        [needs review] [defect·answer_key]┐
│ 60f744b3… · Physics · AC & EM Waves · scq · 3 reports      Urgency 72   Conf 0.70 ⓘ │
├──────────────────────────────────────┬──────────────────────────────────────────────┤
│ QUESTION  (current v1 | original)    │ ▌ Answer-key change. Independent verification│
│ rendered stem + MathML               │ ▌ is unavailable (rules-only engine). Explicit│
│ (A) 50 V                             │ ▌ teacher approval required.                  │
│ (B) 70 V                             │ VERDICT  defect · answer_key                  │
│ (C) 130 V  ← stored key              │ WHY       inference sentence                  │
│ (D) 10 V                             │ EVIDENCE  • stored key (C) 130 V              │
│ ▸ Worked solution                    │           • solution ends at 50 V = (A)       │
│ ▸ Fix history (errorHistory)         │ CONFIDENCE 0.70 · basis · limitation          │
│                                      │ REVIEW REASON  R-40a …                        │
├──────────────────────────────────────┴──────────────────────────────────────────────┤
│ PROPOSED REPAIRS                                                                     │
│  #3 answer_key · proposed · reports R001 R002 R003                                   │
│  Field: answer      Key: (C) 130 V  →  (A) 50 V                                      │
│  [Approve…] [Edit proposal…] [Reject…]                (Execute only after approval)  │
├──────────────────────────────────────────────────────────────────────────────────────┤
│ STUDENT REPORTS (3)   R001 · web · 07 Nov  "answer should be 50V…"  claim (A) ✓     │
│                       reply preview [Edit reply] [Mark duplicate…]                   │
├──────────────────────────────────────────────────────────────────────────────────────┤
│ REVISIONS (v1 current)  ·  AUDIT TIMELINE                                            │
└──────────────────────────────────────────────────────────────────────────────────────┘
```

**Action lifecycle (separate buttons, never chained):**
`proposed` → **Approve** (or **Edit proposal → Validate → Approve with edit**, or **Reject** with a reason) → `approved_applied` → **Execute** (a confirm dialog repeats the diff) → applied → **Roll back** (confirm) from the revision list. `approved_no_edit` repairs (diagram, wrong_chapter, syllabus, unsound, …) show "Acknowledged: fix outside the system" and have no Execute button. The UI never calls execute after approve, and never shows a success state the API did not return.

## 7. Diff

Edits are `{field, find, replace}` over **raw stored HTML**. The API does not expose raw HTML (only sanitised views), so the console never renders raw HTML. Instead:
- **Text fields:** a two-row block, *Removed* and *Added*, showing the `find` and `replace` strings **as text** (monospace) with a character-level diff. Removed spans use `--del-bg/--del-ink` + strikethrough, added spans use `--ins-bg/--ins-ink` + underline, and both are wrapped in `<del>`/`<ins>` for screen readers. Above the block: field name, repair label, and a plain-language explanation. The current rendered field (sanitised, MathML intact) sits above for context. Maths is never re-rendered from edit text.
- **Answer field:** a semantic line with option text, `Key: (C) 130 V → (A) 50 V`. mcq lists render as letter sets.
- **Multi-field internal proposals** (type_mismatch) are listed field by field, marked "faculty-only; not executable as one edit (R-14)".

## 8. States

| State | Treatment |
|---|---|
| Loading | Static skeleton at the real size. After 400 ms, a text label. |
| Empty | Reason + next step ("No cases awaiting execution. Approved repairs appear here."). |
| Error | Danger callout: what failed, the server's message, request ID, **Retry** (reads only). |
| 401 | "Enter the faculty key in Settings" + link; the key status pill turns neutral. |
| 403 | "The faculty key was rejected"; the key is cleared from memory. |
| 409 | The server message (e.g. "Repair 3 is in status 'approved_applied'"), then the view reloads to show the true state. |
| 413 | "That text is too long to send (limit 64 KB)." |
| 503 `writes_disabled` | "Changes are disabled on this server (no faculty key configured)." All write buttons disabled with that reason. |
| 503 `database_error` / offline | Banner; reads retry once; writes are never retried automatically. |
| Read-only (no key) | Write buttons stay visible but disabled, tooltip "Enter the faculty key in Settings". |

## 9. Motion

Only for orientation: dialog fade/scale 120 ms, toast slide 150 ms, row hover background 80 ms. `prefers-reduced-motion: reduce` removes them all. Nothing animates on its own.

## 10. Accessibility

- WCAG 2.1 AA, with contrast measured in §2.
- Skip link. Landmarks: `nav`, `main`, `header`.
- The page `<title>` follows the route.
- Visible focus ring everywhere.
- Full keyboard use: `g o / g q / g r` navigate, `/` focuses search, `j/k/Enter` in tables, `Esc` closes dialogs.
- Native `<dialog>` with focus return.
- Badges always contain text; colour is never the only signal.
- Live regions announce toasts and loading completion.
- MathML is native, so it is readable by screen readers that support it.

## 11. Per-screen verification against §0 (completed 2026-11-11)

Method: (a) a mechanical scan of `frontend/css` and `frontend/js` found no gradients, no blur/backdrop/glass, no coloured shadows (only the focus ring, 2 px state rules and one neutral overlay shadow), radii of 1/2/4/6/8 px only, no inline `style` attributes and no `innerHTML` assignment; (b) each screen was inspected in the screenshots in `docs/screenshots/`; (c) the e2e suite checks real data, keyboard paths and overflow at 5 viewports.

| Screen | No gradients/glow/glass | Radius ≤ 8 | Colour = state only | Real data only | Task-serving elements only | Keyboard + focus |
|---|---|---|---|---|---|---|
| Overview | ✓ | ✓ | ✓ | ✓ numbers asserted equal to `/dashboard` (e2e) | ✓ pending actions first; every metric links to its list | ✓ |
| Report Queue | ✓ | ✓ | ✓ | ✓ counts asserted against `/cases` | ✓ | ✓ `/`, `j/k`, `Enter`, sortable headers are buttons |
| Faculty Review | ✓ | ✓ | ✓ | ✓ | ✓ "Next step" column | ✓ |
| Workspace | ✓ | ✓ | ✓ (the "stored key" badge is neutral: green would imply a key the engine says is wrong is correct) | ✓ | ✓ | ✓ dialogs: focus to Cancel, `Esc`, focus returns |
| Quality Audit | ✓ | ✓ | ✓ | ✓ | ✓ rows link only when a case exists (unreported questions have none) | ✓ |
| Revision History | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Audit Logs | ✓ | ✓ | ✓ | ✓ chain status from `/audit/verify` | ✓ | ✓ |
| Settings | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |

## 12. Implementation notes and deviations (Phase 6)

- **The faculty key is held in memory only** (`frontend/js/state.js`), per the Phase 6 brief. This supersedes the earlier "sessionStorage" plan. Reloading forgets it. The actor name is not secret and is kept in `localStorage`.
- **Tooltips** use native `title` (plus `aria-label`/`aria-describedby` where the text matters). There is no custom tooltip widget.
- **Offline:** there is no persistent banner. Every failed read shows an error callout with **Retry**, reads retry once automatically, and writes never retry automatically. The top-bar API pill turns red when `/health` fails at startup.
- **Executed repairs:** the backend gives a faculty-executed repair status `auto_applied` and audit event `auto_applied` (Phase 5 behaviour, unchanged). The console labels it **"Executed"** so a manual execution is never presented as automatic.
- **Diff:** no rendered "proposed" preview, because the API exposes only sanitised HTML and edits address raw HTML (§7). The current field is shown rendered; the change is shown as text.
