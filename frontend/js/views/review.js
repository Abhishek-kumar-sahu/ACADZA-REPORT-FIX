import { api } from "../api.js";
import { fmtTime, h, humanize } from "../dom.js";
import { setQuery } from "../router.js";
import { confidence, empty, skeletonRows, statusBadge, urgency, verdictBadge } from "../ui.js";
import { rowLink } from "./overview.js";

const TABS = [
  ["needs_review", "Needs decision", "Approve, edit or reject the proposal; or confirm there is nothing to change."],
  ["approved", "Approved · not executed", "Approved repairs change nothing until executed. Execute after a final check."],
  ["auto_pending", "Auto-eligible", "Mechanical edits that passed every guard. Review the diff, then approve and execute."],
  ["investigating", "Investigating", "Cases on hold. Reopen when the investigation is complete."],
];

export default {
  title: "Faculty Review",
  async render(root, { query, isCurrent }) {
    const tab = TABS.find((t) => t[0] === query.tab) || TABS[0];
    const counts = (await api.dashboard()).status_counts || {};
    if (!isCurrent()) return;
    root.append(
      h("div", { class: "page-head" }, h("div", {},
        h("h1", { class: "page-title" }, "Faculty Review"),
        h("p", { class: "page-sub" }, "Cases waiting on a teacher, grouped by the action they need."))),
      h("div", { class: "seg", role: "tablist", "aria-label": "Review stage" }, TABS.map(([key, label]) =>
        h("button", { role: "tab", "aria-selected": String(key === tab[0]), "aria-pressed": String(key === tab[0]), onclick: () => setQuery({ tab: key }) },
          label, h("span", { class: "count" }, String(counts[key] || 0))))),
      h("p", { class: "muted" }, tab[2]));
    const panel = h("section", { class: "panel", role: "tabpanel" }, skeletonRows(6));
    root.append(panel);

    const page = await api.cases({ status: tab[0], sort: "urgency", order: "desc", limit: 200 });
    if (!isCurrent()) return;
    const next = { needs_review: "Decide", approved: "Execute (or leave)", auto_pending: "Review diff → approve → execute", investigating: "Reopen when done" }[tab[0]];
    panel.replaceChildren(page.items.length
      ? h("div", { class: "table-wrap" }, h("table", { class: "data stack-sm" },
          h("thead", {}, h("tr", {}, h("th", { class: "r" }, "Urgency"), h("th", {}, "Question"), h("th", {}, "Verdict"), h("th", {}, "Confidence"), h("th", {}, "Status"), h("th", {}, "Next step"), h("th", {}, "Waiting since"))),
          h("tbody", {}, page.items.map((c) => rowLink(`#/case/${c.question_id}`,
            h("td", { class: "r" }, urgency(c.urgency, c.urgency_breakdown)),
            h("td", {}, h("div", { class: "cell-title", title: c.title }, c.title), h("div", { class: "cell-sub" }, `${c.subject} · ${c.report_count} report${c.report_count === 1 ? "" : "s"}`)),
            h("td", {}, verdictBadge(c.verdict), c.repair ? h("div", { class: "cell-sub" }, humanize(c.repair)) : null),
            h("td", { "data-hide-sm": true }, confidence(c.confidence)),
            h("td", {}, statusBadge(c.status)),
            h("td", {}, h("span", { class: "muted" }, next)),
            h("td", { class: "faint num", "data-hide-sm": true }, fmtTime(c.first_reported_at)))))))
      : empty(`Nothing in “${tab[1]}”.`, tab[0] === "approved" ? "Approved repairs appear here until someone executes them." : "Check the other stages, or the full queue."));
  },
};
