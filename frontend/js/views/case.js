// Question Review Workspace (docs/DESIGN.md §6.1). Approve, Execute and Roll back are separate,
// explicit actions; success is only ever reported from the API response.
import { api, describeError } from "../api.js";
import { fmtTime, h, humanize, setSafeHTML, shortId } from "../dom.js";
import { answerDiff, editDiff, textDiff } from "../diff.js";
import {
  badge, callout, confidence, empty, modal, repairStatusBadge, routeBadge, runAction, skeletonBlock,
  statusBadge, term, toast, toastError, urgency, verdictBadge, writeButton,
} from "../ui.js";
import { eventItem } from "./overview.js";

let taxonomy = null;
const changed = () => document.dispatchEvent(new Event("acadza:changed"));
const panel = (title, body, extra) => h("section", { class: "panel" },
  h("div", { class: "panel-head" }, h("h2", { class: "label" }, title), extra || null), h("div", { class: "panel-body" }, body));

export default {
  title: "Question review",
  async render(root, { params: [qid], isCurrent, rerender }) {
    root.append(skeletonBlock(8));
    const [c, tax] = await Promise.all([api.caseDetail(qid), taxonomy || api.taxonomy()]);
    taxonomy = tax;
    if (!isCurrent()) return;
    root.replaceChildren();
    document.title = `${c.question_id.slice(0, 8)} · ${c.title} · Acadza`;
    const refresh = async () => { changed(); await rerender(); };
    const ctx = { c, refresh, options: c.question.options };

    const lead = pickLead(c);
    root.append(header(ctx, lead), ...topCallouts(c),
      h("div", { class: "workspace" }, questionPanel(c, isCurrent), analysisPanel(c, lead)),
      repairsPanel(ctx), reportsPanel(ctx), h("div", { class: "grid grid-2" }, revisionsPanel(ctx), auditPanel(c)));
  },
};

// The report whose result determines the case verdict (most severe; prefers one with a review reason).
function pickLead(c) {
  const withRes = c.reports.filter((r) => r.result);
  return withRes.find((r) => r.result.verdict === c.verdict && r.result.review_reason) || withRes.find((r) => r.result.verdict === c.verdict) || withRes[0] || null;
}

function header(ctx, lead) {
  const { c } = ctx;
  const caseActions = h("div", { class: "row" },
    c.status === "investigating"
      ? writeButton("Reopen case…", () => reopenDialog(ctx))
      : writeButton("Request investigation…", () => investigateDialog(ctx)));
  return h("div", { class: "page-head" },
    h("div", { class: "stack" },
      h("a", { href: "#/queue", class: "faint" }, "← Report Queue"),
      h("h1", { class: "page-title" }, c.title),
      h("div", { class: "meta-row" }, h("span", { class: "mono", title: c.question_id }, c.question_id), h("span", {}, c.subject),
        h("span", {}, c.chapter), h("span", {}, c.type), h("span", {}, `${c.report_count} report${c.report_count === 1 ? "" : "s"}`)),
      h("div", { class: "row" }, statusBadge(c.status), verdictBadge(c.verdict), c.repair ? badge(humanize(c.repair)) : null,
        lead?.result ? routeBadge(lead.result.route) : null,
        h("span", { class: "faint" }, "Urgency"), urgency(c.urgency, c.urgency_breakdown),
        h("span", { class: "faint" }, "Confidence"), confidence(c.confidence, lead?.result?.confidence_basis))),
    caseActions);
}

function topCallouts(c) {
  const out = [];
  const answerRepairs = c.repairs.filter((r) => ["proposed", "approved_applied"].includes(r.status) && editsOf(r).some((e) => e.field === "answer"));
  if (answerRepairs.length)
    out.push(callout("warn", "Answer-key change: independent verification is unavailable",
      ["The rules-only engine compared the stored key with the stored worked solution; no independent solver ran (", term("R-40", "RULES R-40"),
        "). A teacher must verify the correct answer and explicitly approve, then separately execute."]));
  if (c.repairs.some((r) => r.status === "approved_applied"))
    out.push(callout("info", "Approved but not executed", "The live question is unchanged until someone executes the approved repair."));
  if (c.engine_mode === "rules_only")
    out.push(callout("", "Rules-only analysis", "Verdicts come from deterministic checks of the stored record, not an AI model. Key-related confidence is capped at 0.70."));
  return out;
}

// ---------------------------------------------------------------- question
function questionPanel(c, isCurrent) {
  const q = c.question;
  const body = h("div", { class: "stack" });
  const render = (view) => {
    const keyed = new Set([].concat(view.answer_canonical ?? []));
    const stem = setSafeHTML(h("div", { class: "content" }), view.stem_html_safe || view.question_html_safe);
    const opts = view.options.length
      ? h("ol", { class: "options", "aria-label": "Options" }, view.options.map((o) => h("li", { class: `option${keyed.has(o.letter) ? " keyed" : ""}${o.blank ? " blank" : ""}` },
          h("span", { class: "letter" }, `(${o.letter})`),
          o.blank ? h("span", { class: "body" }, "(blank in the stored question)") : setSafeHTML(h("div", { class: "content body" }), o.html_safe),
          keyed.has(o.letter) ? badge("stored key", "neutral outline", "The key currently stored. See the analysis for whether the record supports it.") : h("span"))))
      : h("div", { class: "row" }, h("span", { class: "faint" }, "Answer key"), h("strong", { class: "num" }, String(view.answer)));
    const issues = view.answer_issues.length ? h("div", { class: "row" }, view.answer_issues.map((i) => badge(humanize(i), "warn"))) : null;
    const sol = h("details", { class: "disclosure", open: true }, h("summary", {}, "Worked solution"),
      view.solution_html_safe ? setSafeHTML(h("div", { class: "content" }), view.solution_html_safe) : h("p", { class: "faint" }, "No solution stored."));
    const hist = h("details", { class: "disclosure" }, h("summary", {}, `Fix history (${view.error_history.length})`),
      view.error_history.length ? h("ol", { class: "timeline" }, view.error_history.map((e) => h("li", {}, h("span", { class: "when" }, fmtTime(e.at)), h("span", {}, `${e.type} · ${e.actor}`, h("div", { class: "cell-sub" }, e.note)))))
        : h("p", { class: "faint" }, "No fixes recorded in the source record."));
    const meta = h("details", { class: "disclosure" }, h("summary", {}, "Record details"),
      h("dl", { class: "kv" }, ["qid", "type", "subject", "chapter", "concept", "level", "version", "updated_at"].flatMap((k) => [h("dt", {}, humanize(k)), h("dd", { class: k === "qid" ? "mono" : "" }, view[k] ?? "—")])));
    body.replaceChildren(...[stem, opts, issues, sol, hist, meta].filter(Boolean));
  };
  render(q);
  let toggle = null;
  if (q.modified) {
    toggle = h("div", { class: "seg", role: "group", "aria-label": "Version" },
      h("button", { "aria-pressed": "true", onclick: (e) => { flip(e); render(q); } }, `Current v${q.version}`),
      h("button", { "aria-pressed": "false", onclick: async (e) => {
        flip(e);
        try { const orig = await api.question(c.question_id, "original"); if (isCurrent()) render(orig); } catch (err) { toastError(err); }
      } }, "Original"));
  }
  return panel(`Question${q.modified ? "" : ` · v${q.version} (original)`}`, body, toggle);
}
function flip(e) { for (const b of e.currentTarget.parentElement.children) b.setAttribute("aria-pressed", String(b === e.currentTarget)); }

// ---------------------------------------------------------------- analysis
function analysisPanel(c, lead) {
  const r = lead?.result;
  if (!r) return panel("Analysis", empty("Not triaged yet.", "Triage runs at server start (BOOT_TRIAGE) or via scripts/run_triage.py."));
  const facts = r.facts?.length ? r.facts : [r.evidence];
  return panel("Analysis", h("div", { class: "stack" },
    h("div", { class: "row" }, verdictBadge(r.verdict), r.repair ? badge(humanize(r.repair)) : null, routeBadge(r.route),
      h("span", { class: "faint" }, `from ${lead.report_id}`)),
    h("div", {}, h("div", { class: "label" }, "What the system concluded"), h("p", {}, r.inference || "—")),
    h("div", {}, h("div", { class: "label" }, "Evidence (observed in the record)"), h("ul", { class: "facts" }, facts.map((f) => h("li", {}, f)))),
    h("div", {}, h("div", { class: "label" }, "Confidence and its limits"),
      h("div", { class: "row" }, confidence(r.confidence, r.confidence_basis), h("span", { class: "faint mono" }, r.confidence_basis || "")),
      r.key_status ? h("p", { class: "muted" }, `Answer-key check: ${humanize(r.key_status)}.`, r.engine_mode === "rules_only" ? " Rules-only engine: no independent solver, so this cannot exceed 0.70." : "") : null),
    r.review_reason ? callout("warn", "Why a teacher must decide", r.review_reason) : null,
    h("div", {}, h("div", { class: "label" }, "Recommended next step"), h("p", {}, r.recommendation || "—")),
    r.rule_ids?.length ? h("p", { class: "faint" }, "Rules applied: ", h("span", { class: "mono" }, r.rule_ids.join(" "))) : null));
}

// ---------------------------------------------------------------- repairs
const editsOf = (r) => (Array.isArray(r.edit) ? r.edit : r.edit ? [r.edit] : []);

function repairsPanel(ctx) {
  const { c } = ctx;
  if (!c.repairs.length) return panel("Proposed repairs", empty("No repair proposed.", "Non-defect verdicts and uncertain cases carry no edit."));
  const active = c.repairs.filter((r) => r.status !== "superseded");
  const old = c.repairs.length - active.length;
  return panel("Proposed repairs", h("div", { class: "stack" }, active.map((r) => repairCard(ctx, r)),
    old ? h("p", { class: "faint" }, `${old} earlier proposal(s) superseded by a newer triage run.`) : null));
}

function explanationFor(c, r) {
  const rep = c.reports.find((x) => r.report_ids.includes(x.report_id) && x.result);
  return rep?.result?.inference || "";
}

function repairCard(ctx, r) {
  const { c } = ctx;
  const fields = taxonomy.repairs[r.repair_type]?.fields || [];
  const edits = editsOf(r);
  let body;
  if (Array.isArray(r.edit))
    body = [callout("info", "Multi-field change (faculty-only)", "This fix spans several fields, which cannot be executed as one edit (R-14). Apply it in the content system after review."),
      ...r.edit.map((e) => h("div", { class: "stack" }, h("div", { class: "label" }, `Field: ${e.field}`), editDiff(e, ctx.options)))];
  else if (r.edit)
    body = [h("div", { class: "row" }, h("span", { class: "label" }, `Field: ${r.edit.field}`)), editDiff(r.edit, ctx.options)];
  else body = [h("p", { class: "muted" }, fields.length ? "No safe surgical edit could be built from the record. A teacher can write one with Edit proposal." :
    `The taxonomy gives '${humanize(r.repair_type)}' no writable fields: a teacher fixes this outside the system, and approval records that decision.`)];

  const actions = [];
  if (r.status === "proposed") {
    actions.push(writeButton(fields.length && r.edit && !Array.isArray(r.edit) ? "Approve…" : "Acknowledge…", (e) => approveDialog(e.currentTarget, ctx, r, null), "btn btn-primary"));
    if (fields.length && !Array.isArray(r.edit)) actions.push(writeButton("Edit proposal…", (e) => editDialog(e.currentTarget, ctx, r)));
    actions.push(writeButton("Reject…", (e) => rejectDialog(e.currentTarget, ctx, r), "btn btn-danger"));
  } else if (r.status === "approved_applied") {
    actions.push(writeButton("Execute…", (e) => executeDialog(e.currentTarget, ctx, r), "btn btn-primary"),
      h("span", { class: "faint" }, "Approved. Nothing has changed in the live question yet."));
  } else if (r.status === "auto_applied") {
    const rev = c.revisions.find((v) => v.repair_id === r.id && !v.reverts_revision_id);
    actions.push(h("span", { class: "faint" }, rev ? `Executed as revision #${rev.id} (v${rev.version}).` : "Executed."));
    if (rev && !rev.reverted_by_revision_id) actions.push(writeButton(`Roll back revision #${rev.id}…`, (e) => rollbackDialog(e.currentTarget, ctx, rev), "btn btn-danger"));
  } else {
    actions.push(h("span", { class: "faint" }, { approved_no_edit: "Acknowledged. The fix happens outside the system.", rejected: "Rejected; nothing will change.", rolled_back: "Executed, then rolled back. The question was restored.", superseded: "Superseded." }[r.status] || ""));
  }
  const why = explanationFor(c, r);
  return h("article", { class: "repair", "aria-label": `Repair ${r.id}` },
    h("div", { class: "repair-head" }, h("strong", {}, `#${r.id} ${humanize(r.repair_type)}`), repairStatusBadge(r.status),
      h("span", { class: "faint" }, "for"), r.report_ids.map((id) => badge(id)), h("span", { class: "grow" }), confidence(r.confidence)),
    h("div", { class: "repair-body" }, why ? h("p", { class: "muted" }, why) : null, body),
    h("div", { class: "repair-actions" }, actions));
}

// ---------------------------------------------------------------- dialogs
function noteField(label = "Note (optional)", required = false) {
  const ta = h("textarea", { class: "textarea prose", maxlength: "500", required: required || null, rows: "3" });
  return [h("label", { class: "field" }, h("span", {}, label), ta), ta];
}

function errorSlot() { return h("div", { "aria-live": "assertive" }); }
function showError(slot, e) { const d = describeError(e); slot.replaceChildren(callout("danger", d.title, d.detail, d.requestId && `Request ID ${d.requestId}`)); }

/** Modal with a primary action; closes only on API success. */
function actionModal({ title, body, label, tone = "primary", valid = () => true, run, refresh }) {
  const slot = errorSlot();
  const go = h("button", { class: tone === "danger" ? "btn btn-danger filled" : "btn btn-primary" }, label);
  const dlg = modal({ title, body: [...[].concat(body), slot], actions: [h("button", { class: "btn", onclick: () => dlg.close() }, "Cancel"), go] });
  const sync = () => { go.disabled = !valid(); };
  dlg.addEventListener("input", sync); dlg.addEventListener("change", sync); sync();
  go.addEventListener("click", async () => {
    if (go.dataset.busy || !valid()) return;
    go.dataset.busy = "1"; go.disabled = true; const t = go.textContent; go.textContent = "Working…";
    try { const res = await run(); dlg.close(); await refresh?.(res); }
    catch (e) { showError(slot, e); if (e.status === 409) { dlg.close(); toastError(e); await refresh?.(); } }
    finally { if (go.isConnected) { delete go.dataset.busy; go.textContent = t; sync(); } }
  });
  return dlg;
}

function approveDialog(btn, ctx, r, editedEdit) {
  const edit = editedEdit || (Array.isArray(r.edit) ? null : r.edit);
  const isAnswer = editsOf(r).some((e) => e.field === "answer") || edit?.field === "answer";
  const noFields = !(taxonomy.repairs[r.repair_type]?.fields || []).length;
  const [noteLabel, note] = noteField();
  const verified = h("input", { type: "checkbox" });
  const body = [
    h("p", {}, noFields ? `Record that a teacher accepts this ${humanize(r.repair_type)} finding. Nothing in the question changes; the fix happens outside the system.`
      : "Approving records your decision. It does not change the question; you execute the repair as a separate step."),
    edit ? editDiff(edit, ctx.options) : null,
    isAnswer ? callout("warn", "Independent verification is unavailable", "This changes the answer key. The engine only compared the key with the stored solution. Confirm you have verified the correct answer yourself.") : null,
    isAnswer ? h("label", { class: "check" }, verified, h("span", {}, "I have independently verified the correct answer.")) : null,
    noteLabel];
  actionModal({
    title: `${noFields ? "Acknowledge" : "Approve"} repair #${r.id}${editedEdit ? " (edited)" : ""}`, body,
    label: noFields ? "Acknowledge" : "Approve repair", valid: () => !isAnswer || verified.checked,
    run: () => api.approve(r.id, { edit: editedEdit || null, note: note.value.trim() || null }),
    refresh: async (res) => { if (res) toastOk(`Repair #${res.id} ${res.status === "approved_no_edit" ? "acknowledged" : "approved"}. ${res.status === "approved_applied" ? "Not executed yet." : ""}`); await ctx.refresh(); },
  });
}

function rejectDialog(btn, ctx, r) {
  const reason = h("textarea", { class: "textarea prose", minlength: "3", maxlength: "500", required: true, rows: "3" });
  actionModal({
    title: `Reject repair #${r.id}`, tone: "danger", label: "Reject repair",
    body: [h("p", {}, "The question stays as it is. Say why, for the audit trail."), h("label", { class: "field" }, h("span", {}, "Reason (required)"), reason)],
    valid: () => reason.value.trim().length >= 3,
    run: () => api.reject(r.id, reason.value.trim()),
    refresh: async (res) => { if (res) toastOk(`Repair #${res.id} rejected.`); await ctx.refresh(); },
  });
}

function executeDialog(btn, ctx, r) {
  const v = ctx.c.question.version;
  const [noteLabel, note] = noteField();
  actionModal({
    title: `Execute repair #${r.id}`, label: `Execute repair #${r.id}`,
    body: [h("p", {}, `This writes to the live question (v${v} → v${v + 1}). The original record is never modified, and the change can be rolled back.`),
      editDiff(r.edit, ctx.options), editsOf(r).some((e) => e.field === "answer") ? callout("warn", "Answer-key change", "Students will be graded against the new key from now on.") : null, noteLabel],
    run: () => api.execute(r.id, note.value.trim() || null),
    refresh: async (res) => { if (res) toastOk(`Executed: revision #${res.revision_id}, question now v${res.version}.${res.audit_ok ? "" : " Audit chain check FAILED - see Audit Logs."}`); await ctx.refresh(); },
  });
}

export function rollbackDialog(btn, ctx, rev) {
  const [noteLabel, note] = noteField();
  actionModal({
    title: `Roll back revision #${rev.id}`, tone: "danger", label: `Roll back revision #${rev.id}`,
    body: [h("p", {}, `Restores the ${rev.field} field to its value before revision #${rev.id}. A new revision is recorded; history is never deleted. The server refuses if the field changed afterwards.`),
      revisionDiff(rev, ctx?.options || [], true), noteLabel],
    run: () => api.rollback(rev.id, note.value.trim() || null),
    refresh: async (res) => { if (res) toastOk(`Rolled back: revision #${res.original_revision_id} reverted by #${res.rollback_revision_id} (now v${res.version}).`); await ctx.refresh(); },
  });
}

function editDialog(btn, ctx, r) {
  const fields = taxonomy.repairs[r.repair_type].fields;
  const base = r.edit && !Array.isArray(r.edit) ? r.edit : { field: fields[0], find: "", replace: "" };
  const isList = (f) => f === "answer" && ctx.c.type === "mcq";
  const show = (v) => (Array.isArray(v) ? v.join(", ") : v ?? "");
  const fieldSel = h("select", { class: "select" }, fields.map((f) => h("option", { value: f, selected: f === base.field }, f)));
  const find = h("textarea", { class: "textarea", rows: "3" }); find.value = show(base.find);
  const replace = h("textarea", { class: "textarea", rows: "3" }); replace.value = show(base.replace);
  const preview = h("div");
  const result = h("div", { "aria-live": "polite" });
  let validatedFor = null;
  const current = () => {
    const f = fieldSel.value;
    const conv = (s) => (isList(f) ? s.split(/[\s,]+/).filter(Boolean).map((x) => x.toUpperCase()) : s);
    return { field: f, find: conv(find.value), replace: conv(replace.value) };
  };
  const key = () => JSON.stringify(current());
  const repaint = () => {
    const e = current();
    preview.replaceChildren(e.field === "answer" ? answerDiff(e.find, e.replace, ctx.options) : textDiff(e.find, e.replace));
    if (validatedFor !== key()) result.replaceChildren(h("p", { class: "faint" }, "Validate the edit before approving it."));
  };
  const validateBtn = h("button", { class: "btn" }, "Validate");
  validateBtn.addEventListener("click", async () => {
    const snapshot = key();
    const res = await runAction(validateBtn, () => api.validateEdit(ctx.c.question_id, r.repair_type, current()));
    if (!res) return;
    validatedFor = res.valid ? snapshot : null;
    result.replaceChildren(res.valid ? callout("ok", "Valid", "Scope, exact-match and guard checks passed on the server.")
      : callout("danger", "Not valid", h("ul", { class: "facts" }, res.violations.map((v) => h("li", {}, v)))));
    dlg.dispatchEvent(new Event("change"));
  });
  for (const el of [fieldSel, find, replace]) el.addEventListener("input", repaint);
  fieldSel.addEventListener("change", repaint);
  const dlg = actionModal({
    title: `Edit proposal for repair #${r.id} (${humanize(r.repair_type)})`, label: "Approve with this edit",
    body: [h("p", { class: "muted" }, "Find must match the stored text exactly (raw HTML) and occur once. Usually only Replace changes. The server re-validates on approval (R-81)."),
      h("label", { class: "field" }, h("span", {}, "Field"), fieldSel),
      h("label", { class: "field" }, h("span", {}, isList(base.field) ? "Find (letters, comma-separated)" : "Find"), find),
      h("label", { class: "field" }, h("span", {}, isList(base.field) ? "Replace (letters, comma-separated)" : "Replace"), replace),
      h("div", { class: "label" }, "Preview"), preview, h("div", { class: "row" }, validateBtn), result],
    valid: () => validatedFor === key(),
    run: () => Promise.resolve(current()),
    refresh: async (edit) => { if (edit) approveDialog(btn, ctx, r, edit); },
  });
  repaint();
}

function investigateDialog(ctx) {
  const { c } = ctx;
  const note = h("textarea", { class: "textarea prose", minlength: "3", maxlength: "500", rows: "3" });
  actionModal({
    title: "Request investigation", label: "Put on hold",
    body: [h("p", {}, "Puts the case on hold. Its status is restored when you reopen it."), h("label", { class: "field" }, h("span", {}, "What needs checking? (required)"), note)],
    valid: () => note.value.trim().length >= 3,
    run: () => api.investigate(c.question_id, note.value.trim()),
    refresh: async (res) => { if (res) toastOk("Case is under investigation."); await ctx.refresh(); },
  });
}

function reopenDialog(ctx) {
  const { c } = ctx;
  const [noteLabel, note] = noteField();
  actionModal({
    title: "Reopen case", label: "Reopen case", body: [h("p", {}, "Ends the investigation and restores the status the case had before."), noteLabel],
    run: () => api.reopen(c.question_id, note.value.trim() || null),
    refresh: async (res) => { if (res) toastOk(`Case reopened (status: ${humanize(res.status)}).`); await ctx.refresh(); },
  });
}

function replyDialog(btn, ctx, rep) {
  const ta = h("textarea", { class: "textarea prose", maxlength: "320", rows: "4" });
  ta.value = rep.result.reply || "";
  const count = h("span", { class: "faint num" });
  const sync = () => { count.textContent = `${ta.value.length}/320`; };
  ta.addEventListener("input", sync); sync();
  const [noteLabel, note] = noteField();
  actionModal({
    title: `Edit reply to ${rep.report_id}`, label: "Save reply",
    body: [h("p", { class: "muted" }, "1–3 short sentences. Don't say 'fixed' unless the fix is live; the server checks this (R-71/R-73)."),
      h("label", { class: "field" }, h("span", {}, "Reply the student will see"), ta), count, noteLabel],
    valid: () => ta.value.trim().length > 0,
    run: () => api.editReply(rep.report_id, ta.value.trim(), note.value.trim() || null),
    refresh: async (res) => { if (res) toastOk(`Reply to ${rep.report_id} saved.`); await ctx.refresh(); },
  });
}

function duplicateDialog(btn, ctx, rep) {
  const others = ctx.c.reports.filter((x) => x.report_id !== rep.report_id);
  const sel = h("select", { class: "select" }, h("option", { value: "" }, "Choose a report…"),
    others.map((x) => h("option", { value: x.report_id }, `${x.report_id} · ${x.comment.slice(0, 40)}`)), h("option", { value: "__other" }, "Another report ID…"));
  const other = h("input", { class: "input", placeholder: "R012", pattern: "R\\d{3,6}", hidden: true });
  sel.addEventListener("change", () => { other.hidden = sel.value !== "__other"; });
  const target = () => (sel.value === "__other" ? other.value.trim().toUpperCase() : sel.value);
  actionModal({
    title: `Mark ${rep.report_id} as a duplicate`, label: "Mark duplicate",
    body: [h("p", {}, "Links this report to another. The report keeps its own record; the link is audited."), h("label", { class: "field" }, h("span", {}, "Duplicate of"), sel), other],
    valid: () => /^R\d{3,6}$/.test(target()) && target() !== rep.report_id,
    run: () => api.duplicate(rep.report_id, target()),
    refresh: async (res) => { if (res) toastOk(`${res.report_id} marked as a duplicate of ${res.duplicate_of}.`); await ctx.refresh(); },
  });
}

const toastOk = (msg) => toast(msg);

// ---------------------------------------------------------------- reports
function reportsPanel(ctx) {
  const { c } = ctx;
  return panel(`Student reports (${c.reports.length})`, h("div", { class: "stack" }, c.reports.map((rep) => {
    const r = rep.result;
    const claim = r?.student_claim ? h("div", { class: "row" }, h("span", { class: "faint" }, "Student's claimed answer"), h("strong", {}, r.student_claim),
      r.student_correct === true ? badge("matches the record", "ok") : r.student_correct === false ? badge("not supported by the record") : badge("not checked")) : null;
    return h("article", { class: "repair", "aria-label": `Report ${rep.report_id}` },
      h("div", { class: "repair-head" }, h("strong", { class: "mono" }, rep.report_id), h("span", { class: "faint" }, `${rep.source} · ${fmtTime(rep.reported_at)} · ${shortId(rep.student_id)}`),
        rep.injection_suspected ? badge("instruction-like text · not followed", "danger", "The comment contains text that tries to instruct the system. It is treated as data only (R-50).") : null,
        rep.duplicate_of ? badge(`duplicate of ${rep.duplicate_of}`) : null,
        rep.fixed_after_report?.length ? badge("fixed after this report", "ok") : null),
      h("div", { class: "repair-body" },
        h("div", { class: "comment" }, rep.comment),          // untrusted: text node only
        claim,
        r ? h("div", { class: "row" }, verdictBadge(r.verdict), r.repair ? badge(humanize(r.repair)) : null, routeBadge(r.route), confidence(r.confidence, r.confidence_basis), h("span", { class: "faint" }, humanize(r.complaint_class))) : h("p", { class: "faint" }, "Not triaged yet."),
        r ? h("div", {}, h("div", { class: "label" }, `Reply preview · ${r.reply_status === "edited" ? "edited by faculty" : "draft"}`), h("div", { class: "comment" }, r.reply || "—")) : null),
      h("div", { class: "repair-actions" },
        r ? writeButton("Edit reply…", (e) => replyDialog(e.currentTarget, ctx, rep)) : null,
        !rep.duplicate_of ? writeButton("Mark duplicate…", (e) => duplicateDialog(e.currentTarget, ctx, rep)) : null));
  })));
}

// ---------------------------------------------------------------- revisions & audit
export function revisionDiff(rev, options, compact = false) {
  if (rev.field === "answer" || rev.field === "questionType") return answerDiff(rev.before, rev.after, rev.field === "answer" ? options : []);
  const a = String(rev.before ?? ""), b = String(rev.after ?? "");
  // Show only the changed region of long HTML fields (as text).
  let i = 0; while (i < a.length && i < b.length && a[i] === b[i]) i++;
  let j = 0; while (j < a.length - i && j < b.length - i && a[a.length - 1 - j] === b[b.length - 1 - j]) j++;
  const ctxLen = compact ? 30 : 60;
  const lo = Math.max(0, i - ctxLen);
  return textDiff((lo ? "…" : "") + a.slice(lo, a.length - j + ctxLen), (lo ? "…" : "") + b.slice(lo, b.length - j + ctxLen));
}

function revisionsPanel(ctx) {
  const { c } = ctx;
  if (!c.revisions.length) return panel("Revisions", empty(`No revisions. The live question is the original (v${c.question.version}).`));
  return panel(`Revisions · current v${c.question.version}`, h("ol", { class: "timeline" }, [...c.revisions].reverse().map((v) =>
    h("li", {}, h("span", { class: "when" }, fmtTime(v.created_at)),
      h("div", { class: "stack" },
        h("div", { class: "row" }, h("strong", {}, `#${v.id} · v${v.version} · ${v.field}`),
          v.reverts_revision_id ? badge(`rollback of #${v.reverts_revision_id}`) : null,
          v.reverted_by_revision_id ? badge(`rolled back by #${v.reverted_by_revision_id}`) : null,
          h("span", { class: "faint" }, v.actor)),
        revisionDiff(v, ctx.options, true),
        !v.reverts_revision_id && !v.reverted_by_revision_id ? h("div", {}, writeButton(`Roll back #${v.id}…`, (e) => rollbackDialog(e.currentTarget, ctx, v), "btn btn-danger btn-sm")) : null)))));
}

function auditPanel(c) {
  const events = [...c.audit].reverse().slice(0, 25);
  return panel("Audit timeline", events.length ? h("ol", { class: "timeline" }, events.map(eventItem)) : empty("No events."),
    h("a", { href: `#/audit?question_id=${c.question_id}` }, "All events"));
}
