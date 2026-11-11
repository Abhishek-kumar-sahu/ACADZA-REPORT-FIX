// Shell: hash router, nav state, connection/key pills, keyboard shortcuts.
import { api } from "./api.js";
import { clear, h } from "./dom.js";
import { session } from "./state.js";
import { errorBlock, paintWidths } from "./ui.js";
import { onReplace, parseHash } from "./router.js";
import overview from "./views/overview.js";
import queue, { invalidateQueueLookups } from "./views/queue.js";
import review from "./views/review.js";
import caseView from "./views/case.js";
import quality from "./views/quality.js";
import revisions from "./views/revisions.js";
import audit from "./views/audit.js";
import settings from "./views/settings.js";

const ROUTES = [
  [/^\/?$/, "overview", overview],
  [/^\/queue$/, "queue", queue],
  [/^\/review$/, "review", review],
  [/^\/case\/([0-9a-f]{24})$/, "queue", caseView],
  [/^\/quality$/, "quality", quality],
  [/^\/revisions$/, "revisions", revisions],
  [/^\/audit$/, "audit", audit],
  [/^\/settings$/, "settings", settings],
];

const main = document.getElementById("main");
let renderToken = 0;

async function route() {
  const token = ++renderToken;
  const { path, query } = parseHash();
  const match = ROUTES.map(([re, nav, view]) => [path.match(re), nav, view]).find(([m]) => m);
  document.getElementById("shell").classList.remove("nav-open");
  document.getElementById("menu-btn").setAttribute("aria-expanded", "false");
  if (!match) {
    clear(main).append(h("div", { class: "empty" }, h("strong", {}, "Page not found"), h("a", { href: "#/" }, "Go to Overview")));
    document.title = "Not found · Acadza";
    return;
  }
  const [m, nav, view] = match;
  for (const a of document.querySelectorAll(".nav a")) {
    if (a.dataset.route === nav) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
  }
  document.title = `${view.title || "Acadza"} · Acadza`;
  clear(main);
  try {
    await view.render(main, { params: m.slice(1), query, isCurrent: () => token === renderToken, rerender: route });
    if (token === renderToken) paintWidths(main);
  } catch (e) {
    if (token === renderToken) clear(main).append(errorBlock(e, route));
  }
}

// ---------------------------------------------------------------- pills & counts
function pill(id, tone, text) {
  const el = document.getElementById(id);
  el.querySelector(".dot").className = `dot ${tone}`;
  el.querySelector("span:last-child").textContent = text;
}

function paintKeyPill() {
  const s = session.keyStatus;
  if (session.writesEnabled === false) return pill("key-pill", "warn", "Writes disabled on server");
  if (s === "verified") return pill("key-pill", "ok", `Faculty · ${session.actor || "name not set"}`);
  if (s === "rejected") return pill("key-pill", "danger", "Key rejected");
  if (s === "unchecked") return pill("key-pill", "warn", "Key not verified");
  pill("key-pill", "neutral", "Read-only");
}

export async function refreshChrome() {
  try {
    const [health, st, auth] = await Promise.all([api.health(), api.settings(), api.authStatus()]);
    pill("api-pill", "ok", `API ok · ${health.db}`);
    session.writesEnabled = auth.writes_enabled;
    const mode = st.engine.mode === "rules_only" ? "Rules-only engine · no AI model" : `AI: ${st.engine.provider} ${st.engine.model || ""}`;
    document.getElementById("engine-note").textContent = `${mode} · v${st.version}`;
  } catch {
    pill("api-pill", "danger", "API unreachable");
  }
  try {
    const d = await api.dashboard();
    document.getElementById("nav-queue").textContent = d.metrics.unique_questions;
    document.getElementById("nav-review").textContent = d.metrics.needs_review || "";
  } catch { /* the page itself shows the error */ }
  paintKeyPill();
}

// ---------------------------------------------------------------- keyboard
let gPending = false;
document.addEventListener("keydown", (e) => {
  const t = e.target;
  if (t instanceof HTMLElement && (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName))) return;
  if (document.querySelector("dialog[open]") || e.metaKey || e.ctrlKey || e.altKey) return;
  if (e.key === "/") { const s = document.querySelector("[data-search]"); if (s) { e.preventDefault(); s.focus(); } return; }
  if (gPending) {
    gPending = false;
    const to = { o: "#/", q: "#/queue", r: "#/review", a: "#/audit", s: "#/settings", h: "#/revisions" }[e.key];
    if (to) { e.preventDefault(); location.hash = to.slice(1); }
    return;
  }
  if (e.key === "g") { gPending = true; setTimeout(() => (gPending = false), 800); return; }
  if (e.key === "j" || e.key === "k") {
    const rows = [...document.querySelectorAll("tr.link")];
    if (!rows.length) return;
    const i = rows.indexOf(document.activeElement);
    rows[Math.max(0, Math.min(rows.length - 1, i + (e.key === "j" ? 1 : -1)))].focus();
    e.preventDefault();
  }
});

document.getElementById("menu-btn").addEventListener("click", () => {
  const shell = document.getElementById("shell");
  const open = shell.classList.toggle("nav-open");
  document.getElementById("menu-btn").setAttribute("aria-expanded", String(open));
});

session.subscribe(paintKeyPill);
onReplace(route);
window.addEventListener("hashchange", route);
refreshChrome();
route();
document.addEventListener("acadza:changed", () => { invalidateQueueLookups(); refreshChrome(); });
