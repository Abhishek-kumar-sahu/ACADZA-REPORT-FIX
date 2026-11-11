// Hash routing helpers (filters live in the URL so Back/Forward and shared links work).
let rerender = () => {};
export const onReplace = (fn) => { rerender = fn; };

export function parseHash() {
  const raw = location.hash.replace(/^#/, "") || "/";
  const [path, qs = ""] = raw.split("?");
  return { path, query: Object.fromEntries(new URLSearchParams(qs)) };
}

export function setQuery(patch, { replace = false } = {}) {
  const { path, query } = parseHash();
  const next = { ...query, ...patch };
  for (const [k, v] of Object.entries(next)) if (v === "" || v === null || v === undefined) delete next[k];
  const hash = `#${path}${Object.keys(next).length ? "?" + new URLSearchParams(next) : ""}`;
  if (replace) { history.replaceState(null, "", hash); rerender(); } else location.hash = hash;
}
