import { api } from "../api.js";
import { fmtNum, fmtTime, h, humanize, plural } from "../dom.js";
import { empty, skeletonBlock, statusBadge, term, urgency, verdictBadge } from "../ui.js";

export default {
  title: "Overview",
  async render(root, { isCurrent }) {
    root.append(h("div", { class: "page-head" }, h("div", {},
      h("h1", { class: "page-title" }, "Overview"),
      h("p", { class: "page-sub" }, "What needs a faculty decision, and how the question bank is doing."))),
    skeletonBlock(6));
    const d = await api.dashboard();
    if (!isCurrent()) return;
    root.lastElementChild.remove();
    const m = d.metrics, sc = d.status_counts || {};
    const alreadyFixed = (d.verdicts || []).find((v) => v.verdict === "already_fixed")?.count ?? 0;

    // 1. Pending faculty actions (first: this is what the faculty member opened the page for)
    const actions = [
      ["Needs your decision", sc.needs_review || 0, "#/review?tab=needs_review", "Proposed repairs and uncertain verdicts waiting for a teacher."],
      ["Approved, not executed", sc.approved || 0, "#/review?tab=approved", "Approved repairs are applied only when someone executes them."],
      ["Auto-eligible", sc.auto_pending || 0, "#/review?tab=auto_pending", "Mechanical edits that passed every guard. Still need execution."],
      ["Under investigation", sc.investigating || 0, "#/review?tab=investigating", "Cases a teacher put on hold."],
    ];
    const pending = h("section", { class: "panel", "aria-labelledby": "pending-h" },
      h("div", { class: "panel-head" }, h("h2", { class: "label", id: "pending-h" }, "Pending faculty actions")),
      h("div", { class: "metrics" }, actions.map(([label, n, href, tip]) =>
        h("a", { class: "metric", href, title: tip }, h("div", { class: "metric-value" }, fmtNum(n)), h("div", { class: "metric-label" }, label)))));

    // 2. Urgent cases
    const urgentBody = d.urgent.length
      ? h("table", { class: "data stack-sm" },
          h("thead", {}, h("tr", {}, h("th", { class: "r" }, term("urgency", "Urgency")), h("th", {}, "Question"), h("th", {}, "Reports"), h("th", {}, "Verdict"), h("th", {}, "Status"))),
          h("tbody", {}, d.urgent.map((c) => rowLink(`#/case/${c.question_id}`,
            h("td", { class: "r" }, urgency(c.urgency, c.urgency_breakdown)),
            h("td", {}, h("div", { class: "cell-title" }, c.title), h("div", { class: "cell-sub" }, `${c.subject} · ${c.chapter}`)),
            h("td", { class: "num" }, c.report_count),
            h("td", {}, verdictBadge(c.verdict), c.repair ? h("span", { class: "faint" }, ` ${humanize(c.repair)}`) : null),
            h("td", {}, statusBadge(c.status))))))
      : empty("No unresolved cases.", "Everything reported has been decided.");
    const urgent = h("section", { class: "panel", "aria-labelledby": "urgent-h" },
      h("div", { class: "panel-head" }, h("h2", { class: "label", id: "urgent-h" }, "Most urgent unresolved cases"), h("a", { href: "#/queue" }, "Open queue")),
      h("div", { class: "panel-body flush table-wrap" }, urgentBody));

    // 3. Metric strip (all from /dashboard)
    const strip = h("section", { "aria-label": "Key metrics", class: "metrics" }, [
      ["Total reports", m.total_reports, "#/queue"], ["Unique questions", m.unique_questions, "#/queue"],
      ["Untriaged", m.untriaged, "#/queue?status=untriaged"], ["Confirmed defects", m.confirmed_defects, "#/queue?verdict=defect"],
      ["Faculty review", m.needs_review, "#/review"], ["Already fixed", alreadyFixed, "#/queue?verdict=already_fixed"],
      ["Auto-eligible", m.auto_eligible ?? 0, "#/review?tab=auto_pending"], ["Executed repairs", m.auto_applied, "#/revisions"],
    ].map(([l, v, href]) => h("a", { class: "metric", href }, h("div", { class: "metric-value" }, fmtNum(v)), h("div", { class: "metric-label" }, l))));

    // 4. Distributions
    const bars = (title, rows, tone) => h("section", { class: "panel" },
      h("div", { class: "panel-head" }, h("h2", { class: "label" }, title)),
      h("div", { class: "panel-body" }, rows.length ? barList(rows, tone) : empty("No data yet.")));
    const subj = d.by_subject.map((s) => [s.subject, s.reports, `${plural(s.reports, "report")} on ${plural(s.cases, "question")}`]);
    const src = Object.entries(d.by_source).sort((a, b) => b[1] - a[1]).map(([k, v]) => [k, v]);
    const verd = d.verdicts.map((v) => [humanize(v.verdict), v.count]);

    const trend = h("section", { class: "panel" },
      h("div", { class: "panel-head" }, h("h2", { class: "label" }, "Resolutions, last 7 days"), h("span", { class: "faint num" }, `${d.trend.reduce((a, t) => a + t.resolved, 0)} total`)),
      h("div", { class: "panel-body" }, sparkBars(d.trend)));

    const run = d.ai_status.last_run;
    const engine = h("section", { class: "panel" },
      h("div", { class: "panel-head" }, h("h2", { class: "label" }, "Triage engine")),
      h("div", { class: "panel-body" }, run
        ? h("dl", { class: "kv" },
            h("dt", {}, "Mode"), h("dd", {}, run.mode === "rules_only" ? term("rules-only", "Rules-only (no AI model)") : `AI (${run.provider || "LLM"}${run.model ? " · " + run.model : ""})`),
            h("dt", {}, "Last run"), h("dd", {}, fmtTime(run.finished_at || run.started_at)),
            h("dt", {}, "Reports triaged"), h("dd", { class: "num" }, fmtNum(d.ai_status.triaged_reports)),
            h("dt", {}, "Model calls"), h("dd", { class: "num" }, `${run.calls} (failures ${run.failures})`))
        : empty("Triage has not run yet.", "Start the server with BOOT_TRIAGE=true or run scripts/run_triage.py.")));

    const activity = h("section", { class: "panel" },
      h("div", { class: "panel-head" }, h("h2", { class: "label" }, "Recent activity"), h("a", { href: "#/audit" }, "Audit logs")),
      h("div", { class: "panel-body" }, d.recent_activity.length ? h("ol", { class: "timeline" }, d.recent_activity.map(eventItem)) : empty("No activity yet.")));

    root.append(pending, urgent, strip,
      h("div", { class: "grid grid-3" }, bars("Reports by subject", subj), bars("Reports by source", src), bars("Verdicts", verd)),
      h("div", { class: "grid grid-2" }, h("div", { class: "stack" }, trend, engine), activity));
  },
};

export function rowLink(href, ...cells) {
  const tr = h("tr", { class: "link", tabindex: "0", onclick: () => (location.hash = href.slice(1)) }, cells);
  tr.addEventListener("keydown", (e) => { if (e.key === "Enter") location.hash = href.slice(1); });
  return tr;
}

export function barList(rows, tone = "") {
  const max = Math.max(1, ...rows.map((r) => r[1]));
  return h("div", { class: "bars" }, rows.map(([label, value, tip]) =>
    h("div", { class: "bar-row", title: tip || `${label}: ${value}` },
      h("span", { class: "cell-title" }, label),
      h("span", { class: "track", "aria-hidden": "true" }, h("span", { class: `fill ${tone}`, dataset: { w: (value / max) * 100 } })),
      h("span", { class: "num r" }, fmtNum(value)))));
}

function sparkBars(trend) {
  const NS = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(NS, "svg");
  svg.setAttribute("class", "spark");
  svg.setAttribute("viewBox", `0 0 ${trend.length * 20} 56`);
  svg.setAttribute("role", "img");
  svg.setAttribute("aria-label", trend.map((t) => `${t.date}: ${t.resolved}`).join(", "));
  const max = Math.max(1, ...trend.map((t) => t.resolved));
  trend.forEach((t, i) => {
    const hgt = t.resolved ? Math.max(2, (t.resolved / max) * 44) : 1;
    const r = document.createElementNS(NS, "rect");
    for (const [k, v] of Object.entries({ x: i * 20 + 4, y: 46 - hgt, width: 12, height: hgt, rx: 1 })) r.setAttribute(k, v);
    const title = document.createElementNS(NS, "title");
    title.textContent = `${t.date}: ${t.resolved}`;
    r.append(title);
    svg.append(r);
  });
  return h("div", {}, svg, h("div", { class: "spread faint" }, h("span", {}, trend[0]?.date || ""), h("span", {}, trend.at(-1)?.date || "")));
}

export function eventItem(e) {
  const who = e.actor_type === "faculty" ? e.actor.replace(/^faculty:/, "") : e.actor;
  const target = e.report_id || (e.question_id ? e.question_id.slice(0, 8) : "");
  return h("li", {},
    h("span", { class: "when" }, fmtTime(e.ts)),
    h("span", {}, h("span", {}, humanize(e.event_type)), " ",
      h("span", { class: "faint" }, `· ${who}`), target ? " " : null,
      e.question_id ? h("a", { href: `#/case/${e.question_id}` }, target) : target ? h("span", { class: "faint" }, target) : null,
      e.note ? h("div", { class: "cell-sub" }, e.note) : null));
}
