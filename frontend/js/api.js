// The only module that talks to the backend. Contracts: docs/API_SPECIFICATION.md (/api/v1).
import { session } from "./state.js";

const BASE = document.querySelector('meta[name="acadza-api-base"]')?.content || "/api/v1";

export class ApiError extends Error {
  constructor({ status, code, message, details = null, requestId = null }) {
    super(message);
    Object.assign(this, { status, code, details, requestId });
  }
  get violations() {
    if (Array.isArray(this.details)) return this.details.map((d) => `${(d.loc || []).slice(1).join(".")}: ${d.msg}`);
    return [];
  }
}

function requestId() {
  const b = crypto.getRandomValues(new Uint8Array(8));
  return [...b].map((x) => x.toString(16).padStart(2, "0")).join("");
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function request(method, path, { body, query, write = false } = {}) {
  const url = new URL(BASE + path, location.origin);
  for (const [k, v] of Object.entries(query || {})) if (v !== undefined && v !== null && v !== "") url.searchParams.set(k, v);
  const headers = { Accept: "application/json", "X-Request-ID": requestId() };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (write && session.key) headers["X-Faculty-Key"] = session.key;

  // Reads retry once on a network failure or transient 503; writes are never retried automatically.
  for (let attempt = 0; ; attempt++) {
    let res;
    try {
      res = await fetch(url, { method, headers, body: body === undefined ? undefined : JSON.stringify(body), credentials: "omit", cache: "no-store" });
    } catch {
      if (!write && attempt === 0) { await sleep(600); continue; }
      throw new ApiError({ status: 0, code: "network", message: "Can't reach the server. Check your connection." });
    }
    const rid = res.headers.get("X-Request-ID");
    let data = null;
    try { data = await res.json(); } catch { /* empty or non-JSON body */ }
    if (res.ok) return data;
    const err = data?.error || {};
    const code = err.code || `http_${res.status}`;
    if (!write && res.status === 503 && code === "database_error" && attempt === 0) { await sleep(600); continue; }
    if (res.status === 401) session.markKey("none");
    if (res.status === 403 && write) session.markKey("rejected");
    if (code === "writes_disabled") session.writesEnabled = false;
    throw new ApiError({ status: res.status, code, message: err.message || res.statusText || "Request failed", details: err.details ?? null, requestId: err.request_id || rid });
  }
}

const get = (path, query) => request("GET", path, { query });
const post = (path, body) => request("POST", path, { body, write: true });
const put = (path, body) => request("PUT", path, { body, write: true });
const actor = () => session.actor;

export const api = {
  health: () => get("/health"),
  settings: () => get("/settings"),
  taxonomy: () => get("/taxonomy"),
  authStatus: () => get("/auth/status"),
  dashboard: () => get("/dashboard"),
  cases: (q) => get("/cases", q),
  caseDetail: (qid) => get(`/cases/${encodeURIComponent(qid)}`),
  reports: (q) => get("/reports", q),
  report: (rid) => get(`/reports/${encodeURIComponent(rid)}`),
  question: (qid, version) => get(`/questions/${encodeURIComponent(qid)}`, { version }),
  revisions: (q) => get("/revisions", q),
  audit: (q) => get("/audit", q),
  auditVerify: () => get("/audit/verify"),
  results: () => get("/results"),
  bonus: () => get("/bonus-findings"),
  triageRuns: () => get("/triage/runs"),

  verifyKey: () => post("/auth/verify"),
  investigate: (qid, note) => post(`/cases/${qid}/investigate`, { actor: actor(), note }),
  reopen: (qid, note) => post(`/cases/${qid}/reopen`, { actor: actor(), note: note || null }),
  approve: (id, { edit = null, note = null } = {}) => post(`/repairs/${id}/approve`, { actor: actor(), edit, note }),
  reject: (id, reason, note = null) => post(`/repairs/${id}/reject`, { actor: actor(), reason, note }),
  execute: (id, note = null) => post(`/repairs/${id}/execute`, { actor: actor(), note }),
  rollback: (revId, note = null) => post(`/revisions/${revId}/rollback`, { actor: actor(), note }),
  duplicate: (rid, of, note = null) => post(`/reports/${rid}/duplicate`, { actor: actor(), duplicate_of: of, note }),
  editReply: (rid, reply, note = null) => put(`/reports/${rid}/reply`, { actor: actor(), reply, note }),
  validateEdit: (questionId, repairType, edit) => post("/validate-edit", { question_id: questionId, repair_type: repairType, edit }),
};

// Plain-language messages for the error states in docs/DESIGN.md §8.
export function describeError(e) {
  if (!(e instanceof ApiError)) return { title: "Something went wrong in the console.", detail: String(e?.message || e) };
  const map = {
    401: "Enter the faculty key in Settings to make changes.",
    403: "The faculty key was rejected. It has been cleared; enter it again in Settings.",
    409: "This changed since you loaded it. The view has been refreshed to show the current state.",
    413: "That text is too long to send (limit 64 KB).",
    422: "The server rejected this input.",
    404: "Not found.",
  };
  let title = map[e.status] || e.message;
  if (e.code === "writes_disabled") title = "Changes are disabled on this server (no faculty key configured).";
  if (e.code === "database_error") title = "The database is unavailable. Try again shortly.";
  if (e.code === "network") title = e.message;
  const detail = e.status === 409 || e.status === 422 ? [e.message, ...e.violations].filter(Boolean).join(" · ") : (title === e.message ? "" : e.message);
  return { title, detail, requestId: e.requestId };
}
