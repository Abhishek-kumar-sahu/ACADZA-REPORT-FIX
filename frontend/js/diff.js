// Field-level diff for {field, find, replace} edits (docs/DESIGN.md §7).
// Edits address raw stored HTML, which the API does not expose for rendering, so the diff shows the
// find/replace strings AS TEXT with token-level highlighting. Nothing here is ever parsed as HTML.
import { h } from "./dom.js";

const tokenize = (s) => String(s ?? "").split(/(\s+|[^\p{L}\p{N}\s])/u).filter((t) => t !== "");

/** LCS over tokens → [{op: "=", "-", "+", text}]. Inputs are bounded (find ≤ 300 chars, R-12). */
export function diffTokens(a, b) {
  const A = tokenize(a), B = tokenize(b);
  const dp = Array.from({ length: A.length + 1 }, () => new Uint16Array(B.length + 1));
  for (let i = A.length - 1; i >= 0; i--)
    for (let j = B.length - 1; j >= 0; j--)
      dp[i][j] = A[i] === B[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
  const out = [];
  let i = 0, j = 0;
  const push = (op, text) => (out.length && out.at(-1).op === op ? (out.at(-1).text += text) : out.push({ op, text }));
  while (i < A.length && j < B.length) {
    if (A[i] === B[j]) { push("=", A[i]); i++; j++; }
    else if (dp[i + 1][j] >= dp[i][j + 1]) push("-", A[i++]);
    else push("+", B[j++]);
  }
  while (i < A.length) push("-", A[i++]);
  while (j < B.length) push("+", B[j++]);
  return out;
}

function side(parts, keep) {
  const nodes = parts.filter((p) => p.op === "=" || p.op === keep)
    .map((p) => (p.op === "=" ? document.createTextNode(p.text) : h(keep === "-" ? "del" : "ins", {}, p.text)));
  return nodes.length ? nodes : [h("span", { class: "empty-mark" }, keep === "-" ? "(nothing removed)" : "(removed entirely)")];
}

/** Removed / Added rows for a text edit. */
export function textDiff(find, replace) {
  const parts = diffTokens(find, replace);
  return h("div", { class: "diff", role: "group", "aria-label": "Proposed text change" },
    h("div", { class: "diff-row" }, h("span", { class: "label" }, "Removed"), h("div", { class: "diff-text" }, side(parts, "-"))),
    h("div", { class: "diff-row" }, h("span", { class: "label" }, "Added"), h("div", { class: "diff-text" }, side(parts, "+"))));
}

const fmtAns = (v) => (Array.isArray(v) ? (v.length ? v.join(", ") : "(empty)") : String(v ?? "—"));

/** Semantic answer-key change, with option text where the letters map to options. */
export function answerDiff(find, replace, options = []) {
  const label = (v) => {
    const letters = Array.isArray(v) ? v : [v];
    const texts = letters.map((l) => options.find((o) => o.letter === l)?.text).filter(Boolean);
    return texts.length && !Array.isArray(v) ? `(${v}) ${texts[0] || "(blank option)"}` : fmtAns(v);
  };
  return h("div", { class: "answer-change", role: "group", "aria-label": "Answer key change" },
    h("span", { class: "faint" }, "Key"),
    h("del", { class: "from" }, label(find)), h("span", { "aria-hidden": "true" }, "→"), h("ins", { class: "to" }, label(replace)));
}

/** Whichever diff fits the edit. */
export function editDiff(edit, options) {
  if (!edit) return null;
  if (edit.field === "answer" || edit.field === "questionType") return answerDiff(edit.find, edit.replace, edit.field === "answer" ? options : []);
  return textDiff(edit.find, edit.replace);
}
