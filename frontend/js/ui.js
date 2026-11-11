// Shared components (docs/DESIGN.md §5). Pages compose these; they never restyle them.
import { h, humanize, fmtConf } from "./dom.js";
import { ApiError, describeError } from "./api.js";
import { session } from "./state.js";

// ---------------------------------------------------------------- badges
const VERDICT = { defect: "danger", display_issue: "info", app_issue: "info", already_fixed: "ok" };
const STATUS = {
  untriaged: ["neutral", "Untriaged"], needs_review: ["warn", "Needs review"], auto_pending: ["info", "Auto-eligible"],
  approved: ["ok outline", "Approved · not executed"], auto_fixed: ["ok", "Applied"], no_change: ["neutral", "Closed · no change"],
  rejected: ["neutral", "Rejected"], investigating: ["warn", "Investigating"], duplicate: ["neutral", "Duplicate"],
  rolled_back: ["neutral", "Rolled back"],
};
const REPAIR_STATUS = {
  proposed: ["warn", "Proposed"], approved_applied: ["ok outline", "Approved · awaiting execution"],
  approved_no_edit: ["ok outline", "Acknowledged · fix outside system"],
  auto_applied: ["ok", "Executed"],   // backend status name for an executed repair (also set by faculty execute)
  rejected: ["neutral", "Rejected"], rolled_back: ["neutral", "Rolled back"], superseded: ["neutral", "Superseded"],
};
const ROUTE = { auto_apply: ["info", "Auto-eligible"], faculty_review: ["warn", "Faculty review"], no_change: ["neutral", "No change"] };

export const badge = (text, tone = "neutral", title) => h("span", { class: `badge ${tone}`, title }, text);
export const verdictBadge = (v) => (v ? badge(humanize(v), VERDICT[v] || "neutral") : badge("Not triaged"));
export const statusBadge = (s) => badge(...[...(STATUS[s] || ["neutral", humanize(s)])].reverse());
export const repairStatusBadge = (s) => badge(...[...(REPAIR_STATUS[s] || ["neutral", humanize(s)])].reverse());
export const routeBadge = (r) => (r ? badge(...[...(ROUTE[r] || ["neutral", humanize(r)])].reverse()) : null);

// ---------------------------------------------------------------- confidence & urgency
export function confidence(c, basis) {
  if (c === null || c === undefined) return h("span", { class: "faint" }, "—");
  const on = c >= 0.95 ? 4 : c >= 0.85 ? 3 : c >= 0.6 ? 2 : 1;
  const band = ["", "Low", "Medium", "High", "Very high"][on];
  const tip = `${band} confidence. ${basis || "Computed from deterministic evidence (RULES R-87), not a model's self-report."}`;
  return h("span", { class: "conf", title: tip, "aria-label": `Confidence ${fmtConf(c)}, ${band}` },
    h("span", { class: "num" }, fmtConf(c)),
    h("span", { class: "conf-bar", "aria-hidden": "true" }, [1, 2, 3, 4].map((i) => h("i", { class: i <= on ? "on" : "" }))));
}

export function urgency(total, br) {
  const tip = br ? `Urgency ${total}: impact ${br.impact} + volume ${br.volume} + age ${br.age} + review ${br.review}. Not AI confidence.` : "";
  return h("span", { class: "urg", title: tip, "aria-label": tip || `Urgency ${total}` },
    h("span", { class: "num" }, String(total ?? "—")),
    h("span", { class: "urg-bar", "aria-hidden": "true" }, h("i", { dataset: { w: total } })));
}
// Bar widths: CSP forbids inline style *attributes*; setting element.style via the CSSOM is allowed.
export function paintWidths(root) {
  for (const el of root.querySelectorAll("[data-w]")) el.style.width = `${Math.max(0, Math.min(100, Number(el.dataset.w) || 0))}%`;
}

const TERMS = {
  "auto_apply": "Eligible for automatic application of a mechanical edit. Nothing is applied until a faculty member executes it.",
  "faculty_review": "A teacher must decide. The reason is shown with the case.",
  "R-40": "Answer-key changes need an independent solve that agrees. The rules-only engine has no solver, so a teacher must verify.",
  "rules-only": "Verdicts come from deterministic checks of the stored record. No AI model was used.",
  "urgency": "Impact of the defect + number of reports + waiting time + pending review. Not AI confidence.",
};
export const term = (key, label = key) => h("span", { class: "term", title: TERMS[key] || "", tabindex: "0" }, label);

// ---------------------------------------------------------------- states
export const skeletonRows = (n = 6) => h("div", { "aria-busy": "true", "aria-label": "Loading" }, Array.from({ length: n }, () => h("div", { class: "sk-row" })));
export const skeletonBlock = (lines = 4) => h("div", { class: "panel-body", "aria-busy": "true" }, Array.from({ length: lines }, (_, i) => h("div", { class: "skeleton sk-line", dataset: { w: 90 - i * 12 } })));
export const empty = (title, next) => h("div", { class: "empty" }, h("strong", {}, title), next ? h("span", {}, next) : null);
export function errorBlock(e, onRetry) {
  const d = describeError(e);
  return h("div", { class: "callout danger", role: "alert" },
    h("div", {}, h("strong", {}, d.title), d.detail ? h("div", {}, d.detail) : null,
      d.requestId ? h("div", { class: "meta" }, `Request ID ${d.requestId}`) : null,
      onRetry ? h("div", { class: "row" }, h("button", { class: "btn btn-sm", onclick: onRetry }, "Retry")) : null));
}
export function callout(tone, title, body, meta) {
  return h("div", { class: `callout ${tone}`, role: tone === "danger" ? "alert" : null }, h("div", {}, h("strong", {}, title), body ? h("div", {}, body) : null, meta ? h("div", { class: "meta" }, meta) : null));
}

// ---------------------------------------------------------------- toasts
const toastRoot = () => document.getElementById("toasts");
export function toast(title, { tone = "ok", meta } = {}) {
  const t = h("div", { class: `toast ${tone}`, role: tone === "danger" ? "alert" : "status" }, h("div", {}, title), meta ? h("div", { class: "meta" }, meta) : null);
  const root = toastRoot();
  root.append(t);
  while (root.children.length > 3) root.firstElementChild.remove();
  setTimeout(() => t.remove(), tone === "danger" ? 9000 : 6000);
}
export function toastError(e) {
  const d = describeError(e);
  toast(d.title, { tone: "danger", meta: [d.detail, d.requestId && `Request ID ${d.requestId}`].filter(Boolean).join(" · ") });
}

// ---------------------------------------------------------------- dialogs
export function modal({ title, body, actions }) {
  const opener = document.activeElement;
  const dlg = h("dialog", { class: "modal", "aria-labelledby": "modal-title" },
    h("div", { class: "modal-head" }, h("h2", { id: "modal-title" }, title)),
    h("div", { class: "modal-body" }, body),
    h("div", { class: "modal-foot" }, actions));
  dlg.addEventListener("close", () => { dlg.remove(); if (opener && opener.isConnected) opener.focus(); });
  document.body.append(dlg);
  dlg.showModal();
  return dlg;
}

/** Confirm dialog. Resolves true only when the user clicks the explicit confirm button. */
export function confirmDialog({ title, body, confirmLabel, tone = "primary" }) {
  return new Promise((resolve) => {
    let ok = false;
    const confirmBtn = h("button", { class: tone === "danger" ? "btn btn-danger filled" : "btn btn-primary", onclick: () => { ok = true; dlg.close(); } }, confirmLabel);
    const dlg = modal({ title, body, actions: [h("button", { class: "btn", onclick: () => dlg.close() }, "Cancel"), confirmBtn] });
    dlg.addEventListener("close", () => resolve(ok));
    dlg.querySelector(".modal-foot .btn").focus();      // safe default: Cancel
  });
}

// ---------------------------------------------------------------- writes
/** Write button: disabled (with the reason) whenever the session cannot write. */
export function writeButton(label, onclick, cls = "btn") {
  const reason = session.writeBlockReason();
  return h("button", { class: cls, onclick, disabled: Boolean(reason), title: reason || null, "aria-disabled": reason ? "true" : null }, label);
}

/**
 * Run a write with a double-submit guard. Success is reported only from the API response.
 * On 409 the caller's refresh runs, so the view shows the real state.
 */
export async function runAction(button, fn, { success, refresh } = {}) {
  if (button?.dataset.busy) return null;
  const label = button?.textContent;
  if (button) { button.dataset.busy = "1"; button.disabled = true; button.textContent = "Working…"; }
  try {
    const res = await fn();
    if (success) toast(typeof success === "function" ? success(res) : success, { tone: "ok" });
    if (refresh) await refresh();
    return res;
  } catch (e) {
    toastError(e);
    if (e instanceof ApiError && e.status === 409 && refresh) await refresh();
    return null;
  } finally {
    if (button && button.isConnected) { delete button.dataset.busy; button.disabled = false; button.textContent = label; }
  }
}
