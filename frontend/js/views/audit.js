import { api } from "../api.js";
import { fmtTime, h, humanize } from "../dom.js";
import { setQuery } from "../router.js";
import { callout, empty, skeletonRows } from "../ui.js";

const PAGE = 50;
const EVENTS = ["report_received", "import_completed", "triage_started", "triage_decision", "triage_completed", "case_status_changed",
  "investigation_requested", "case_reopened", "faculty_approved", "faculty_edited_proposal", "faculty_rejected", "auto_applied",
  "rolled_back", "marked_duplicate", "reply_edited"];

export default {
  title: "Audit Logs",
  async render(root, { query, isCurrent }) {
    const page = Number(query.page || 1);
    const order = query.order || "desc";
    const sel = (label, key, opts) => h("label", { class: "field" }, h("span", {}, label),
      h("select", { class: "select", onchange: (e) => setQuery({ [key]: e.target.value, page: "" }) },
        opts.map(([v, t]) => h("option", { value: v, selected: v === (query[key] || "") }, t))));
    const qInput = h("input", { class: "input", value: query.question_id || "", placeholder: "24-character question ID", pattern: "[0-9a-f]{24}" });
    qInput.addEventListener("change", () => { const v = qInput.value.trim(); if (!v || /^[0-9a-f]{24}$/.test(v)) setQuery({ question_id: v, page: "" }); else qInput.setCustomValidity("Use the full 24-character question ID"); qInput.reportValidity(); });
    qInput.addEventListener("input", () => qInput.setCustomValidity(""));
    const verifySlot = h("div", {}, callout("", "Verifying the audit chain…"));
    root.append(
      h("div", { class: "page-head" }, h("div", {}, h("h1", { class: "page-title" }, "Audit Logs"),
        h("p", { class: "page-sub" }, "Append-only and hash-chained: every system, engine and faculty action, with before and after values."))),
      verifySlot,
      h("div", { class: "filters" },
        sel("Actor", "actor_type", [["", "Everyone"], ["faculty", "Faculty"], ["system", "System and engine"], ["ai", "AI model"]]),
        sel("Event", "event_type", [["", "All events"], ...EVENTS.map((e) => [e, humanize(e)])]),
        sel("Order", "order", [["desc", "Newest first"], ["asc", "Oldest first"]]),
        h("label", { class: "field search" }, h("span", {}, "Question ID"), qInput),
        h("button", { class: "btn btn-ghost", onclick: () => (location.hash = "/audit") }, "Clear filters")));
    const panel = h("section", { class: "panel" }, skeletonRows(8));
    root.append(panel);

    const [v, data] = await Promise.all([api.auditVerify(), api.audit({ actor_type: query.actor_type, event_type: query.event_type, question_id: query.question_id, order, limit: PAGE, offset: (page - 1) * PAGE })]);
    if (!isCurrent()) return;
    verifySlot.replaceChildren(v.ok
      ? callout("ok", `Audit chain verified: ${v.events} events, no tampering detected.`, "Each event's hash covers the previous one; any out-of-band edit breaks the chain.")
      : callout("danger", `Audit chain BROKEN at event #${v.first_bad_id}`, "An event was changed outside the application. Treat the log after this point as untrusted and escalate."));
    const to = Math.min(data.total, page * PAGE);
    panel.replaceChildren(
      data.items.length ? h("div", { class: "table-wrap" }, h("table", { class: "data stack-sm" },
        h("thead", {}, h("tr", {}, h("th", {}, "When"), h("th", {}, "Event"), h("th", {}, "Actor"), h("th", {}, "Target"), h("th", {}, "Change"), h("th", {}, "Note"))),
        h("tbody", {}, data.items.map((e) => h("tr", {},
          h("td", { class: "num faint nowrap" }, fmtTime(e.ts)),
          h("td", {}, humanize(e.event_type)),
          h("td", {}, h("span", { class: e.actor_type === "faculty" ? "" : "faint" }, e.actor)),
          h("td", { class: "nowrap" }, e.question_id ? h("a", { href: `#/case/${e.question_id}`, class: "mono" }, e.question_id.slice(0, 8)) : null,
            e.report_id ? h("span", { class: "mono" }, ` ${e.report_id}`) : null, e.repair_id ? h("span", { class: "faint" }, ` repair #${e.repair_id}`) : null),
          h("td", { class: "muted", "data-hide-sm": true }, change(e)),
          h("td", { class: "faint", "data-hide-sm": true }, e.note || "")))))) : empty("No events match these filters."),
      h("div", { class: "pager" }, h("span", { class: "num" }, `${data.total ? (page - 1) * PAGE + 1 : 0}–${to} of ${data.total}`),
        h("div", { class: "row" },
          h("button", { class: "btn btn-sm", disabled: page <= 1, onclick: () => setQuery({ page: String(page - 1) }) }, "Previous"),
          h("button", { class: "btn btn-sm", disabled: to >= data.total, onclick: () => setQuery({ page: String(page + 1) }) }, "Next"))));
  },
};

// Compact, text-only summary of before/after (values may contain raw stored HTML: never rendered as HTML).
function change(e) {
  const brief = (x) => { if (x === null || x === undefined) return "—"; const s = typeof x === "string" ? x : JSON.stringify(x); return s.length > 80 ? `${s.slice(0, 77)}…` : s; };
  if (e.before === null && e.after === null) return "";
  return `${brief(e.before)} → ${brief(e.after)}`;
}
