// In-memory session state. The faculty key lives ONLY in this module variable: never in
// localStorage/sessionStorage, URLs, logs or the DOM. Reloading the page forgets it (by design).
// The actor name is not a secret; it is kept in localStorage for convenience and is self-declared.

let facultyKey = null;
let keyStatus = "none";          // none | verified | rejected | unchecked
const listeners = new Set();

export const session = {
  get key() { return facultyKey; },
  get keyStatus() { return keyStatus; },
  setKey(k, status = "unchecked") { facultyKey = k || null; keyStatus = k ? status : "none"; emit(); },
  markKey(status) { keyStatus = status; if (status === "rejected") facultyKey = null; emit(); },
  forgetKey() { facultyKey = null; keyStatus = "none"; emit(); },
  get actor() { return localStorage.getItem("acadza.actor") || ""; },
  setActor(name) { localStorage.setItem("acadza.actor", name.trim()); emit(); },
  writesEnabled: null,           // from /auth/status; null = unknown
  canWrite() { return Boolean(facultyKey) && keyStatus !== "rejected" && this.writesEnabled !== false && /^[\w .-]{2,60}$/.test(this.actor); },
  writeBlockReason() {
    if (this.writesEnabled === false) return "Changes are disabled on this server (no faculty key configured).";
    if (!facultyKey) return "Enter the faculty key in Settings to make changes.";
    if (keyStatus === "rejected") return "The faculty key was rejected. Enter it again in Settings.";
    if (!/^[\w .-]{2,60}$/.test(this.actor)) return "Set your name (2–60 letters, digits, spaces, . or -) in Settings.";
    return "";
  },
  subscribe(fn) { listeners.add(fn); return () => listeners.delete(fn); },
};

function emit() { for (const fn of listeners) fn(); }
