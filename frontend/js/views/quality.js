import { api } from "../api.js";
import { fmtTime, h, humanize } from "../dom.js";
import { setQuery } from "../router.js";
import { badge, callout, empty, skeletonBlock, term } from "../ui.js";
import { barList, rowLink } from "./overview.js";

export default {
  title: "Quality Audit",
  async render(root, { query, isCurrent }) {
    root.append(h("div", { class: "page-head" }, h("div", {},
      h("h1", { class: "page-title" }, "Quality Audit"),
      h("p", { class: "page-sub" }, "Problems the system found in questions nobody reported, and how the current triage results break down."))),
    skeletonBlock(6));
    const [bonus, runs, results, cases] = await Promise.all([api.bonus(), api.triageRuns(), api.results(), api.cases({ limit: 200 })]);
    const hasCase = new Set(cases.items.map((c) => c.question_id));   // unreported questions have no case to open
    if (!isCurrent()) return;
    root.lastElementChild.remove();

    const status = query.status || "all";
    const items = bonus.items.filter((f) => status === "all" || f.status === status);
    const filt = h("div", { class: "seg", role: "group", "aria-label": "Finding status" },
      [["all", "All", bonus.items.length], ["verified", "Verified", bonus.items.filter((f) => f.status === "verified").length],
        ["suspected", "Suspected", bonus.items.filter((f) => f.status === "suspected").length]].map(([k, l, n]) =>
        h("button", { "aria-pressed": String(k === status), onclick: () => setQuery({ status: k === "all" ? "" : k }) }, l, h("span", { class: "count" }, String(n)))));

    const findings = h("section", { class: "panel" },
      h("div", { class: "panel-head" }, h("h2", { class: "label" }, `Unreported findings · ${bonus.questions_inspected} questions inspected`), filt),
      h("div", { class: "panel-body flush" }, items.length ? h("div", { class: "table-wrap" }, h("table", { class: "data stack-sm" },
        h("thead", {}, h("tr", {}, h("th", {}, "Finding"), h("th", {}, "Question"), h("th", {}, "Category"), h("th", {}, "Status"), h("th", {}, "Severity"), h("th", {}, "Evidence"), h("th", {}, "Next step"))),
        h("tbody", {}, items.map((f) => (hasCase.has(f.questionId) ? (...cells) => rowLink(`#/case/${f.questionId}`, ...cells) : (...cells) => h("tr", {}, cells))(
          h("td", { class: "mono" }, f.findingId),
          h("td", {}, h("span", { class: "mono", title: f.questionId }, f.questionId.slice(0, 8)), h("div", { class: "cell-sub" }, `${f.subject} · ${f.field}${hasCase.has(f.questionId) ? "" : " · no student reports"}`)),
          h("td", {}, humanize(f.category)),
          h("td", {}, badge(f.status, f.status === "verified" ? "ok" : "warn", f.status === "verified" ? "A structural fact quoted from the record." : "A heuristic; a teacher should confirm.")),
          h("td", {}, badge(f.severity, f.severity === "high" ? "danger" : f.severity === "medium" ? "warn" : "neutral")),
          h("td", { class: "muted" }, f.evidence),
          h("td", { class: "faint", "data-hide-sm": true }, f.recommended_action))))))
        : empty("No findings in this filter.")));

    const count = (k) => Object.entries(results.reduce((a, r) => ((a[r[k]] = (a[r[k]] || 0) + 1), a), {})).sort((a, b) => b[1] - a[1]).map(([v, n]) => [humanize(v), n]);
    const run = runs.items[0];
    root.append(
      callout("info", "How these were found", ["Deterministic detectors over every stored question (", term("rules-only", "rules-only"),
        "). Factual errors in explanations, misfiled chapters and similar judgement calls need an AI model or a teacher and are not detected here."]),
      findings,
      h("div", { class: "grid grid-3" },
        h("section", { class: "panel" }, h("div", { class: "panel-head" }, h("h2", { class: "label" }, `Verdicts · ${results.length} reports`)), h("div", { class: "panel-body" }, barList(count("verdict")))),
        h("section", { class: "panel" }, h("div", { class: "panel-head" }, h("h2", { class: "label" }, "Routes")), h("div", { class: "panel-body" }, barList(count("route")))),
        h("section", { class: "panel" }, h("div", { class: "panel-head" }, h("h2", { class: "label" }, "Triage runs")), h("div", { class: "panel-body" }, run
          ? h("dl", { class: "kv" }, h("dt", {}, "Runs"), h("dd", { class: "num" }, String(runs.total)), h("dt", {}, "Latest"), h("dd", {}, `#${run.id} · ${fmtTime(run.finished_at)}`),
              h("dt", {}, "Mode"), h("dd", {}, humanize(run.mode)), h("dt", {}, "Engine"), h("dd", { class: "mono" }, run.prompt_versions?.engine || "—"),
              h("dt", {}, "Model calls"), h("dd", { class: "num" }, String(run.calls)))
          : empty("No triage run yet.")))));
  },
};
