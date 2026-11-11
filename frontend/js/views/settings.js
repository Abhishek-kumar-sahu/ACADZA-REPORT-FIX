import { api, describeError } from "../api.js";
import { fmtTime, h, humanize } from "../dom.js";
import { session } from "../state.js";
import { badge, callout, runAction, skeletonBlock, toast } from "../ui.js";

export default {
  title: "Settings",
  async render(root, { isCurrent, rerender }) {
    root.append(h("div", { class: "page-head" }, h("div", {},
      h("h1", { class: "page-title" }, "Settings"),
      h("p", { class: "page-sub" }, "Connection, engine, and your faculty access for this browser tab."))), skeletonBlock(6));

    let health = null, st = null, auth = null, err = null;
    try { [health, st, auth] = await Promise.all([api.health(), api.settings(), api.authStatus()]); } catch (e) { err = e; }
    if (!isCurrent()) return;
    root.lastElementChild.remove();
    if (auth) session.writesEnabled = auth.writes_enabled;

    // ------------------------------------------------ faculty access
    const keyInput = h("input", { class: "input", type: "password", autocomplete: "off", spellcheck: "false", "aria-describedby": "key-help" });
    const actorInput = h("input", { class: "input", value: session.actor, maxlength: "60", autocomplete: "name", "aria-describedby": "actor-help" });
    const status = h("div", { "aria-live": "polite" });
    const paintStatus = () => status.replaceChildren(
      session.writesEnabled === false ? callout("warn", "Changes are disabled on this server", "The server has no faculty key configured, so every write is refused. Reading works normally.")
      : session.keyStatus === "verified" ? callout("ok", "Write access verified", `Signed in as “${session.actor || "—"}” for this tab. Reloading the page forgets the key.`)
      : session.keyStatus === "rejected" ? callout("danger", "The key was rejected", "The server did not accept it. It has been cleared from memory.")
      : callout("", "Read-only", "Enter the faculty key to approve, reject, execute or roll back repairs."));
    paintStatus();
    const verifyBtn = h("button", { class: "btn btn-primary", type: "submit" }, "Verify and use key");
    const form = h("form", { class: "stack", onsubmit: async (e) => {
      e.preventDefault();
      const name = actorInput.value.trim();
      if (!/^[\w .-]{2,60}$/.test(name)) { actorInput.setCustomValidity("2–60 letters, digits, spaces, '.' or '-'"); actorInput.reportValidity(); return; }
      if (!keyInput.value) { keyInput.setCustomValidity("Enter the faculty key"); keyInput.reportValidity(); return; }
      session.setActor(name);
      session.setKey(keyInput.value, "unchecked");
      keyInput.value = "";                         // never keep the key in the DOM
      try {
        const res = await runAction(verifyBtn, () => api.verifyKey());
        if (res?.ok) { session.markKey("verified"); toast(`Write access verified for ${name}.`); }
        else if (session.keyStatus !== "rejected") session.forgetKey();
      } finally { paintStatus(); }
    } },
      h("label", { class: "field" }, h("span", {}, "Your name (recorded on every action)"), actorInput,
        h("span", { class: "hint", id: "actor-help" }, "Self-declared and kept in this browser. It is not verified by the server.")),
      h("label", { class: "field" }, h("span", {}, "Faculty key"), keyInput,
        h("span", { class: "hint", id: "key-help" }, "Held in memory for this tab only: never saved to storage, the URL, logs or the page.")),
      h("div", { class: "row" }, verifyBtn,
        h("button", { class: "btn", type: "button", onclick: () => { session.forgetKey(); paintStatus(); toast("Faculty key forgotten."); } }, "Forget key")));
    for (const el of [keyInput, actorInput]) el.addEventListener("input", () => el.setCustomValidity(""));

    const access = h("section", { class: "panel" },
      h("div", { class: "panel-head" }, h("h2", { class: "label" }, "Faculty access")),
      h("div", { class: "panel-body stack" }, status, form,
        callout("info", "Shared key, self-declared names",
          "This system uses one shared faculty key and self-declared names, not individual verified accounts. Anyone holding the key can act under any name. Every action is audited and reversible, but the audit trail cannot prove who acted.")));

    // ------------------------------------------------ connection & engine
    const conn = h("section", { class: "panel" },
      h("div", { class: "panel-head" }, h("h2", { class: "label" }, "Connection"), h("button", { class: "btn btn-sm", onclick: rerender }, "Re-check")),
      h("div", { class: "panel-body" }, err ? callout("danger", describeError(err).title, describeError(err).detail) :
        h("dl", { class: "kv" },
          h("dt", {}, "API"), h("dd", {}, badge(health.status === "ok" ? "Healthy" : health.status, health.status === "ok" ? "ok" : "danger"), h("span", { class: "faint" }, ` ${location.origin}/api/v1`)),
          h("dt", {}, "Database"), h("dd", {}, health.db), h("dt", {}, "Data imported"), h("dd", {}, health.data_imported ? "Yes" : "No"),
          h("dt", {}, "Records"), h("dd", { class: "num" }, `${health.counts.questions} questions · ${health.counts.reports} reports · ${health.counts.cases} cases`),
          h("dt", {}, "Server writes"), h("dd", {}, auth.writes_enabled ? badge("Enabled", "ok") : badge("Disabled", "warn")),
          h("dt", {}, "Version"), h("dd", {}, health.version), h("dt", {}, "Checked"), h("dd", {}, fmtTime(new Date().toISOString())))));

    const engine = st ? h("section", { class: "panel" },
      h("div", { class: "panel-head" }, h("h2", { class: "label" }, "Triage engine & AI provider")),
      h("div", { class: "panel-body stack" },
        st.engine.mode === "rules_only"
          ? callout("warn", "No AI provider configured", "Verdicts come from the deterministic rules-only engine. Answer-key changes always need a teacher; key confidence is capped at 0.70.")
          : callout("info", `AI provider: ${st.engine.provider}`, st.engine.model || ""),
        h("dl", { class: "kv" },
          h("dt", {}, "Mode"), h("dd", {}, humanize(st.engine.mode)), h("dt", {}, "Provider"), h("dd", {}, st.engine.provider),
          h("dt", {}, "Model"), h("dd", {}, st.engine.model || "—"),
          h("dt", {}, "Auto-apply threshold"), h("dd", { class: "num" }, String(st.thresholds.auto_apply_min_confidence)),
          h("dt", {}, "No-change threshold"), h("dd", { class: "num" }, String(st.thresholds.no_change_min_confidence)),
          h("dt", {}, "Dataset fingerprint"), h("dd", { class: "mono faint" }, hashes(st.data_sha256))))) : null;

    const keys = h("section", { class: "panel" },
      h("div", { class: "panel-head" }, h("h2", { class: "label" }, "Keyboard")),
      h("div", { class: "panel-body" }, h("dl", { class: "kv" },
        ...[["g o / g q / g r", "Overview / Queue / Review"], ["g h / g a / g s", "Revisions / Audit / Settings"], ["/", "Search the queue"], ["j / k", "Move between rows"], ["Enter", "Open the focused row"], ["Esc", "Close a dialog"]]
          .flatMap(([k, v]) => [h("dt", { class: "mono" }, k), h("dd", {}, v)]))));

    root.append(h("div", { class: "grid grid-2" }, access, h("div", { class: "stack" }, conn, engine, keys)));
  },
};

function hashes(json) {
  if (!json) return "—";
  try { return Object.entries(JSON.parse(json)).map(([f, hsh]) => `${f} ${hsh.slice(0, 12)}`).join(" · "); } catch { return "—"; }
}
