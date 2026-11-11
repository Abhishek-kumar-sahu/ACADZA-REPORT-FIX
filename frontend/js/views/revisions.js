import { api } from "../api.js";
import { fmtTime, h } from "../dom.js";
import { setQuery } from "../router.js";
import { badge, empty, skeletonRows, writeButton } from "../ui.js";
import { revisionDiff, rollbackDialog } from "./case.js";

const PAGE = 25;

export default {
  title: "Revision History",
  async render(root, { query, isCurrent, rerender }) {
    const page = Number(query.page || 1);
    root.append(h("div", { class: "page-head" }, h("div", {},
      h("h1", { class: "page-title" }, "Revision History"),
      h("p", { class: "page-sub" }, "Every executed change and every rollback. History is append-only; a rollback is itself a new revision."))));
    const panel = h("section", { class: "panel" }, skeletonRows(6));
    root.append(panel);
    const data = await api.revisions({ limit: PAGE, offset: (page - 1) * PAGE, question_id: query.question_id });
    if (!isCurrent()) return;
    const ctx = { options: [], refresh: async () => { document.dispatchEvent(new Event("acadza:changed")); await rerender(); } };
    const to = Math.min(data.total, page * PAGE);
    panel.replaceChildren(
      data.items.length ? h("div", { class: "panel-body" }, h("ol", { class: "timeline" }, [...data.items].reverse().map((v) => h("li", {},
        h("span", { class: "when" }, fmtTime(v.created_at)),
        h("div", { class: "stack" },
          h("div", { class: "row" }, h("strong", {}, `#${v.id}`), h("a", { href: `#/case/${v.question_id}`, class: "mono" }, v.question_id.slice(0, 8)),
            h("span", {}, `v${v.version} · ${v.field}`), h("span", { class: "faint" }, v.actor),
            v.repair_id ? badge(`repair #${v.repair_id}`) : null,
            v.reverts_revision_id ? badge(`rollback of #${v.reverts_revision_id}`) : null,
            v.reverted_by_revision_id ? badge(`rolled back by #${v.reverted_by_revision_id}`) : null),
          revisionDiff(v, [], true),
          !v.reverts_revision_id && !v.reverted_by_revision_id
            ? h("div", {}, writeButton(`Roll back #${v.id}…`, (e) => rollbackDialog(e.currentTarget, ctx, v), "btn btn-danger btn-sm")) : null)))))
        : empty("No revisions yet.", "Executed repairs appear here; approving alone does not create a revision."),
      h("div", { class: "pager" }, h("span", { class: "num" }, `${data.total ? (page - 1) * PAGE + 1 : 0}–${to} of ${data.total}`),
        h("div", { class: "row" },
          h("button", { class: "btn btn-sm", disabled: page <= 1, onclick: () => setQuery({ page: String(page - 1) }) }, "Previous"),
          h("button", { class: "btn btn-sm", disabled: to >= data.total, onclick: () => setQuery({ page: String(page + 1) }) }, "Next"))));
  },
};
