// DOM helpers. Untrusted text is ONLY ever set with textContent (via h()).
// setSafeHTML() is the single entry point for academic HTML, and only for API fields named *_html_safe
// (already sanitised server-side); it re-applies the same allowlist client-side as defence in depth.

export function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") el.className = v;
    else if (k === "text") el.textContent = String(v);
    else if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2), v);
    else if (k === "dataset") Object.assign(el.dataset, v);
    else if (v === true) el.setAttribute(k, "");
    else el.setAttribute(k, String(v));
  }
  append(el, children);
  return el;
}

export function append(el, children) {
  for (const c of children.flat(Infinity)) {
    if (c === null || c === undefined || c === false) continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return el;
}

export function clear(el) { el.replaceChildren(); return el; }

const HTML_TAGS = new Set("h1 h2 h3 h4 h5 h6 p div span br hr b strong i em u s sup sub small ul ol li table thead tbody tr td th blockquote pre code img".split(" "));
const MATH_TAGS = new Set("math mrow mi mn mo mtext ms mspace msup msub msubsup mfrac msqrt mroot mover munder munderover mstyle mpadded mphantom menclose mfenced mtable mtr mtd mlabeledtr semantics annotation merror mmultiscripts mprescripts none".split(" "));
const ATTRS = new Set("xmlns display displaystyle dir scriptlevel mathvariant stretchy fence form separator lspace rspace largeop movablelimits accent accentunder symmetric minsize maxsize linebreak width height depth linethickness bevelled open close separators notation voffset columnalign rowalign columnspacing rowspacing columnspan rowspan encoding colspan alt".split(" "));

function scrub(node) {
  for (const child of [...node.childNodes]) {
    if (child.nodeType === Node.ELEMENT_NODE) {
      const name = child.localName;
      if (!HTML_TAGS.has(name) && !MATH_TAGS.has(name)) { child.remove(); continue; }
      for (const a of [...child.attributes]) {
        const ok = ATTRS.has(a.name) || (name === "img" && a.name === "src" && /^https?:\/\//i.test(a.value));
        if (!ok) child.removeAttribute(a.name);
      }
      scrub(child);
    } else if (child.nodeType !== Node.TEXT_NODE) {
      child.remove();                      // comments, processing instructions
    }
  }
}

export function setSafeHTML(el, sanitised) {
  const doc = new DOMParser().parseFromString(`<body>${sanitised || ""}</body>`, "text/html");
  scrub(doc.body);
  el.replaceChildren(...[...doc.body.childNodes].map((n) => document.importNode(n, true)));
  return el;
}

// ---------------------------------------------------------------- formatting
const DT = new Intl.DateTimeFormat(undefined, { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
export function fmtTime(iso) { if (!iso) return "—"; const d = new Date(iso); return isNaN(d) ? "—" : DT.format(d); }
export function fmtNum(n) { return n === null || n === undefined ? "—" : Number(n).toLocaleString(); }
export function fmtConf(c) { return c === null || c === undefined ? "—" : Number(c).toFixed(2); }
export function shortId(id) { return id ? `${id.slice(0, 8)}…` : "—"; }
export function humanize(s) { return s ? String(s).replace(/_/g, " ") : "—"; }
export function plural(n, word) { return `${n} ${word}${n === 1 ? "" : "s"}`; }
