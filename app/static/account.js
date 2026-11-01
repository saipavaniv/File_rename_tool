"use strict";

(async function init() {
  const me = await boot("account");
  if (!me) return;
  const first = new URLSearchParams(location.search).get("first") || me.user.must_change_password;
  if (first) $("#first").classList.remove("hidden");
  if (me.user.must_change_password) $("#extCard").classList.add("hidden");
  $("#origin").textContent = location.origin;
  $("#pwForm").addEventListener("submit", changePw);
  $("#mkTok").addEventListener("click", makeToken);
  $("#copyExt").addEventListener("click", async () => {
    try { await navigator.clipboard.writeText($("#extUrl").textContent); toast("Copied: paste it in the address bar"); }
    catch (e) { toast("Type chrome://extensions in the address bar", true); }
  });
  if (/Edg\//.test(navigator.userAgent)) $("#extUrl").textContent = "edge://extensions";
  $("#copyTok").addEventListener("click", async () => {
    try { await navigator.clipboard.writeText($("#tokVal").textContent); toast("Key copied"); }
    catch (e) { toast("Select the key and copy it manually", true); }
  });
  if (!me.user.must_change_password) loadTokens();
})();

function msg(text, ok) {
  const m = $("#pwMsg");
  m.textContent = text;
  m.className = "alert " + (ok ? "ok" : "bad");
}

async function changePw(e) {
  e.preventDefault();
  const cur = $("#cur").value, n1 = $("#new1").value, n2 = $("#new2").value;
  if (!cur || !n1) return msg("Fill in all fields.");
  if (n1 !== n2) return msg("The new passwords don't match.");
  try {
    await api("/api/auth/password", { method: "POST", json: { current: cur, new: n1 } });
    $("#pwForm").reset();
    msg("Password changed. Other devices have been signed out.", true);
    if (ME.user.must_change_password) setTimeout(() => { location.href = "/"; }, 900);
  } catch (ex) { msg(ex.message); }
}

async function loadTokens() {
  try {
    const rows = await api("/api/auth/tokens");
    if (!rows.length) {
      $("#toks").replaceChildren(el("tr", {}, [el("td", { colspan: "4", class: "muted small", text: "No keys yet." })]));
      return;
    }
    $("#toks").replaceChildren(...rows.map((t) => el("tr", {}, [
      el("td", {}, [el("div", { text: t.name }), el("div", { class: "mono small muted", text: t.prefix + "…" })]),
      el("td", { class: "small", text: t.last_used_at ? fmtDateTime(t.last_used_at) : "Never" }),
      el("td", { class: "small", text: fmtDateTime(t.expires_at) }),
      el("td", {}, [el("button", { class: "sm danger", text: "Revoke", onclick: () => revoke(t) })]),
    ])));
  } catch (e) { toast(e.message, true); }
}

async function makeToken() {
  try {
    const r = await api("/api/auth/tokens", { method: "POST", json: { name: $("#tokName").value.trim() || "Browser", days: 180 } });
    $("#tokVal").textContent = r.token;
    $("#newTok").classList.remove("hidden");
    loadTokens();
  } catch (e) { toast(e.message, true); }
}

async function revoke(t) {
  if (!confirm("Revoke the key \"" + t.name + "\"? The browser button using it will stop working.")) return;
  try { await api("/api/auth/tokens/" + t.id, { method: "DELETE" }); toast("Key revoked"); loadTokens(); }
  catch (e) { toast(e.message, true); }
}
