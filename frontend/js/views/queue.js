import { api } from "../api.js";
import { fmtTime, h, humanize } from "../dom.js";
import { setQuery } from "../router.js";
import { confidence, empty, skeletonRows, statusBadge, term, urgency, verdictBadge } from "../ui.js";
import { rowLink } from "./overview.js";

const PAGE = 25;
const STATUS_TABS = [["all", "All"], ["needs_review", "Needs review"], ["auto_pending", "Auto-eligible"], ["approved", "Approved"],
  ["investigating", "Investigating"], ["untriaged", "Untriaged"], ["resolved", "Resolved"]];

let refocusSearch = false;   // keep the caret in the search box across re-renders
let lookups = null;   // {subjects, verdicts, complaints: Map(qid → Set(class))}
async function loadLookups() {
  if (lookups) return lookups;
  // ponytail: one /reports page of 200 covers this dataset (44); page through /reports when reports exceed 200.
  const [dash, tax, reps] = await Promise.all([api.dashboard(), api.taxonomy(), api.reports({ limit: 200 })]);
  const complaints = new Map();
  for (const r of reps.items) {
    const c = r.result?.complaint_class;
    if (!c) continue;
    if (!complaints.has(r.question_id)) complaints.set(r.question_id, new Set());
    complaints.get(r.question_id).add(c);
  }
  lookups = { subjects: dash.by_subject.map((s) => s.subject), verdicts: Object.keys(tax.verdicts), complaints, complete: reps.total <= reps.items.length };
  return lookups;
}
export const invalidateQueueLookups = () => { lookups = null; };

function select(label, key, value, options) {
  return h("label", { class: "field" }, h("span", {}, label),
    h("select", { class: "select", onchange: (e) => setQuery({ [key]: e.target.value, page: "" }) },
      options.map(([v, t]) => h("option", { value: v, selected: v === (value || "") }, t))));
}

export default {
  title: "Report Queue",
  async render(root, { query, isCurrent }) {
    const q = { status: query.status || "all", sort: query.sort || "urgency", order: query.order || "desc", page: Number(query.page || 1) };
    const L = await loadLookups();
    if (!isCurrent()) return;

    const search = h("input", { class: "input", type: "search", value: query.q || "", placeholder: "R004 or 60f744b3", "data-search": true, "aria-describedby": "search-hint" });
    let timer;
    search.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(() => { refocusSearch = true; setQuery({ q: search.value.trim(), page: "" }, { replace: true }); }, 300); });

    const head = h("div", { class: "page-head" },
      h("div", {}, h("h1", { class: "page-title" }, "Report Queue"),
        h("p", { class: "page-sub" }, "One row per reported question, ordered by ", term("urgency", "urgency"), " (impact, report count, waiting time). Press / to search, j/k to move, Enter to open.")));

    const tabs = h("div", { class: "seg", role: "group", "aria-label": "Status" }, STATUS_TABS.map(([v, t]) =>
      h("button", { "aria-pressed": String(q.status === v), onclick: () => setQuery({ status: v === "all" ? "" : v, page: "" }) }, t)));

    const filters = h("div", { class: "filters" },
      h("label", { class: "field search" }, h("span", {}, "Search"), search, h("span", { class: "sr-only", id: "search-hint" }, "Report ID or question ID")),
      select("Subject", "subject", query.subject, [["", "All subjects"], ...L.subjects.map((s) => [s, s])]),
      select("Verdict", "verdict", query.verdict, [["", "All verdicts"], ...L.verdicts.map((v) => [v, humanize(v)])]),
      select("Confidence", "confidence", query.confidence, [["", "Any"], ["very_high", "Very high ≥ 0.95"], ["high", "High 0.85–0.94"], ["medium", "Medium 0.60–0.84"], ["low", "Low < 0.60"]]),
      select("Priority", "priority", query.priority, [["", "Any"], ["critical", "Critical ≥ 70"], ["high", "High 40–69"], ["normal", "Normal 15–39"], ["low", "Low < 15"]]),
      h("label", { class: "check", title: "Only cases whose verdict is defect" },
        h("input", { type: "checkbox", checked: query.defects_only === "true", onchange: (e) => setQuery({ defects_only: e.target.checked ? "true" : "", page: "" }) }),
        h("span", {}, "Defects only")),
      h("button", { class: "btn btn-ghost", onclick: () => (location.hash = "/queue") }, "Clear filters"));

    const tablePanel = h("section", { class: "panel" }, h("div", { class: "panel-body flush" }, skeletonRows(8)));
    root.append(head, tabs, filters, tablePanel);
    if (refocusSearch) { refocusSearch = false; search.focus(); search.setSelectionRange(search.value.length, search.value.length); }

    const page = await api.cases({
      status: q.status, subject: query.subject, verdict: query.verdict, confidence: query.confidence, priority: query.priority,
      defects_only: query.defects_only === "true" ? "true" : undefined, q: query.q, sort: q.sort, order: q.order,
      limit: PAGE, offset: (q.page - 1) * PAGE,
    });
    if (!isCurrent()) return;

    const sortTh = (key, label, cls = "") => {
      const active = q.sort === key;
      const next = active && q.order === "desc" ? "asc" : "desc";
      return h("th", { class: cls, "aria-sort": active ? (q.order === "desc" ? "descending" : "ascending") : "none" },
        h("button", { class: "sort", onclick: () => setQuery({ sort: key, order: next, page: "" }) }, label, active ? (q.order === "desc" ? " ↓" : " ↑") : ""));
    };

    const body = page.items.length
      ? h("div", { class: "table-wrap" }, h("table", { class: "data stack-sm" },
          h("thead", {}, h("tr", {}, sortTh("urgency", "Urgency", "r"), h("th", {}, "Question"), sortTh("reports", "Reports", "r"),
            h("th", {}, "Complaint"), h("th", {}, "Verdict"), sortTh("confidence", "Confidence"), h("th", {}, "Status"), sortTh("latest", "Latest report"))),
          h("tbody", {}, page.items.map((c) => {
            const cls = [...(L.complaints.get(c.question_id) || [])].map(humanize);
            return rowLink(`#/case/${c.question_id}`,
              h("td", { class: "r" }, urgency(c.urgency, c.urgency_breakdown)),
              h("td", {}, h("div", { class: "cell-title", title: c.title }, c.title),
                h("div", { class: "cell-sub" }, h("span", { class: "mono" }, c.question_id.slice(0, 8)), ` · ${c.subject} · ${c.chapter}`)),
              h("td", { class: "r num" }, c.report_count),
              h("td", { "data-hide-sm": true, title: cls.join(", ") }, cls.length ? `${cls[0]}${cls.length > 1 ? ` +${cls.length - 1}` : ""}` : h("span", { class: "faint" }, "—")),
              h("td", {}, verdictBadge(c.verdict), c.repair ? h("div", { class: "cell-sub" }, humanize(c.repair)) : null),
              h("td", { "data-hide-sm": true }, confidence(c.confidence)),
              h("td", {}, statusBadge(c.status)),
              h("td", { class: "num faint nowrap", "data-hide-sm": true }, fmtTime(c.latest_report_at)));
          }))))
      : empty("No cases match these filters.", "Clear a filter or search for a different ID.");

    const from = page.total ? (q.page - 1) * PAGE + 1 : 0, to = Math.min(page.total, q.page * PAGE);
    const pager = h("div", { class: "pager" },
      h("span", { class: "num", "aria-live": "polite" }, `${from}–${to} of ${page.total}`),
      h("div", { class: "row" },
        h("button", { class: "btn btn-sm", disabled: q.page <= 1, onclick: () => setQuery({ page: String(q.page - 1) }) }, "Previous"),
        h("button", { class: "btn btn-sm", disabled: to >= page.total, onclick: () => setQuery({ page: String(q.page + 1) }) }, "Next")));
    tablePanel.replaceChildren(h("div", { class: "panel-body flush" }, body), pager,
      L.complete ? null : h("div", { class: "pager" }, "Complaint categories are shown for the first 200 reports only."));
  },
};
