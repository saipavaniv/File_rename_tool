"use strict";
let pqTimer;

(async function init() {
  const me = await boot("admin", { admin: true });
  if (!me) return;
  $all(".tabs button").forEach((b) => b.addEventListener("click", () => showTab(b.dataset.tab)));
  $("#userForm").addEventListener("submit", addUser);
  $("#gen").addEventListener("click", () => { $("#np").value = genPassword(); });
  $("#imp").addEventListener("click", importCsv);
  $("#pq").addEventListener("input", () => { clearTimeout(pqTimer); pqTimer = setTimeout(loadParties, 250); });
  $("#setForm").addEventListener("submit", saveSettings);
  $("#tpl").addEventListener("input", example);
  $("#af").addEventListener("change", loadAudit);
  $("#verify").addEventListener("click", verify);
  window.addEventListener("hashchange", () => showTab(location.hash.slice(1)));
  showTab(location.hash.slice(1) || "users");
})();

const loaders = { users: loadUsers, parties: loadParties, settings: loadSettings, learning: loadCorrections, audit: loadAudit };

function showTab(name) {
  if (!loaders[name]) name = "users";
  $all(".tabs button").forEach((b) => b.classList.toggle("active", b.dataset.tab === name));
  $all("section[id^=tab-]").forEach((s) => s.classList.toggle("hidden", s.id !== "tab-" + name));
  history.replaceState(null, "", "#" + name);
  loaders[name]();
}

function genPassword() {
  const words = ["River", "Copper", "Stamp", "Spring", "Vellore", "Mould", "Press", "Signal", "Harbor", "Falcon", "Cedar", "Orbit"];
  const r = new Uint32Array(4);
  crypto.getRandomValues(r);
  return words[r[0] % words.length] + "-" + words[r[1] % words.length] + "-" + (1000 + (r[2] % 9000)) + "!";
}

// ---------------- users
async function loadUsers() {
  try {
    const rows = await api("/api/admin/users");
    $("#users").replaceChildren(...rows.map((u) => {
      const state = !u.is_active ? el("span", { class: "chip bad", text: "Disabled" })
        : u.locked ? el("span", { class: "chip warn", text: "Locked" }) : null;
      const actions = el("div", { class: "row" });
      if (u.locked) actions.appendChild(el("button", { class: "sm", text: "Unlock", onclick: () => patchUser(u, { unlock: true }) }));
      actions.appendChild(el("button", { class: "sm", text: "Reset password", onclick: () => resetPw(u) }));
      actions.appendChild(el("button", { class: "sm " + (u.is_active ? "danger" : ""), text: u.is_active ? "Disable" : "Enable",
        onclick: () => patchUser(u, { is_active: !u.is_active }) }));
      return el("tr", {}, [
        el("td", {}, [el("div", { text: u.display_name || u.username }), el("div", { class: "small muted mono", text: u.username }), state]),
        el("td", {}, [el("select", { "aria-label": "Role", onchange: (e) => patchUser(u, { role: e.target.value }) }, [
          el("option", { value: "user", text: "User", selected: u.role === "user" }),
          el("option", { value: "admin", text: "Admin", selected: u.role === "admin" })])]),
        el("td", { class: "small", text: u.last_login_at ? fmtDateTime(u.last_login_at) : "Never" }),
        el("td", {}, [actions]),
      ]);
    }));
  } catch (e) { toast(e.message, true); }
}

async function patchUser(u, body) {
  try { await api("/api/admin/users/" + u.id, { method: "PATCH", json: body }); toast("Saved"); }
  catch (e) { toast(e.message, true); }
  loadUsers();
}

async function resetPw(u) {
  const pw = genPassword();
  if (!confirm("Reset the password for " + u.username + "?\n\nNew temporary password:\n" + pw + "\n\nGive it to them in person. They must change it at next sign-in.")) return;
  patchUser(u, { password: pw });
}

async function addUser(e) {
  e.preventDefault();
  const body = { username: $("#nu").value.trim().toLowerCase(), display_name: $("#nd").value.trim(), role: $("#nr").value, password: $("#np").value };
  try {
    await api("/api/admin/users", { method: "POST", json: body });
    toast("Added " + body.username + ". Give them the temporary password in person.");
    $("#userForm").reset();
    loadUsers();
  } catch (ex) { toast(ex.message, true); }
}

// ---------------- parties
async function loadParties() {
  try {
    const q = $("#pq").value.trim();
    const r = await api("/api/admin/parties" + (q ? "?q=" + encodeURIComponent(q) : ""));
    $("#pcount").textContent = r.total + (r.total === 1 ? " company" : " companies");
    if (!r.items.length) {
      $("#parties").replaceChildren(el("tr", {}, [el("td", { colspan: "6", class: "empty", text: "No companies yet. Import a CSV export from the ERP to improve accuracy." })]));
      return;
    }
    $("#parties").replaceChildren(...r.items.map((p) => el("tr", {}, [
      el("td", { class: "mono small", text: p.code }),
      el("td", {}, [el("div", { text: p.name }), p.aliases ? el("div", { class: "small muted", text: "also: " + p.aliases }) : null]),
      el("td", { class: "mono", text: p.short_name || "(automatic)" }),
      el("td", { class: "small", text: p.domains }),
      el("td", { class: "small", text: p.kind }),
      el("td", {}, [el("button", { class: "sm danger", text: "Remove", onclick: () => removeParty(p) })]),
    ])));
  } catch (e) { toast(e.message, true); }
}

async function importCsv() {
  const f = $("#csv").files[0];
  if (!f) { toast("Choose a CSV file first", true); return; }
  const form = new FormData();
  form.append("file", f, f.name);
  try {
    const r = await api("/api/admin/parties/import", { method: "POST", form });
    toast("Imported: " + r.added + " new, " + r.updated + " updated" + (r.skipped ? ", " + r.skipped + " skipped" : ""));
    $("#csv").value = "";
    loadParties();
  } catch (e) { toast(e.message, true); }
}

async function removeParty(p) {
  if (!confirm("Remove " + p.name + " from the list?")) return;
  try { await api("/api/admin/parties/" + p.id, { method: "DELETE" }); loadParties(); }
  catch (e) { toast(e.message, true); }
}

// ---------------- settings
async function loadSettings() {
  try {
    const s = await api("/api/admin/settings");
    $("#tpl").value = s.template;
    $("#own").value = (s.own_names || []).join("; ");
    $("#dom").value = (s.own_domains || []).join("; ");
    $("#dord").value = s.date_order;
    $("#thr").value = s.auto_threshold;
    example();
  } catch (e) { toast(e.message, true); }
}

function example() {
  const v = { date: "2026-10-28", type: "QUO", party: "Precitool", ref: "PTC-Q-2026-0457", subject: "Progressive-Die-Contact-Spring" };
  let n = $("#tpl").value;
  for (const [k, val] of Object.entries(v)) n = n.split("{" + k + "}").join(val);
  $("#example").textContent = n + ".pdf";
}

async function saveSettings(e) {
  e.preventDefault();
  const split = (s) => s.split(/[;,]/).map((x) => x.trim()).filter(Boolean);
  try {
    await api("/api/admin/settings", { method: "PUT", json: {
      template: $("#tpl").value.trim(), own_names: split($("#own").value), own_domains: split($("#dom").value),
      date_order: $("#dord").value, auto_threshold: parseFloat($("#thr").value) } });
    toast("Rules saved");
  } catch (ex) { toast(ex.message, true); }
}

// ---------------- corrections & audit
async function loadCorrections() {
  try {
    const rows = await api("/api/admin/corrections");
    if (!rows.length) { $("#corr").replaceChildren(el("tr", {}, [el("td", { colspan: "4", class: "empty", text: "No corrections yet." })])); return; }
    $("#corr").replaceChildren(...rows.map((c) => el("tr", {}, [
      el("td", { text: c.field }), el("td", { class: "mono small", text: c.suggested || "—" }),
      el("td", { class: "mono small", text: c.corrected || "—" }), el("td", { text: String(c.count) })])));
  } catch (e) { toast(e.message, true); }
}

async function loadAudit() {
  try {
    const a = $("#af").value;
    const rows = await api("/api/admin/audit?limit=200" + (a ? "&action=" + encodeURIComponent(a) : ""));
    $("#audit").replaceChildren(...rows.map((r) => el("tr", {}, [
      el("td", { class: "small", text: fmtDateTime(r.at) }), el("td", { text: r.username || "—" }),
      el("td", {}, [el("span", { class: "chip " + (/fail|lock|blocked/.test(r.action) ? "bad" : "idle"), text: r.action })]),
      el("td", { class: "small mono", text: r.target }), el("td", { class: "small muted", text: r.ip })])));
  } catch (e) { toast(e.message, true); }
}

async function verify() {
  const out = $("#verifyOut");
  try {
    const r = await api("/api/admin/audit/verify");
    out.textContent = r.ok ? "Intact: " + r.checked + " entries verified" : "Warning: log altered at entry #" + r.broken_at_id;
    out.className = "small chip " + (r.ok ? "ok" : "bad");
    loadAudit();
  } catch (e) { toast(e.message, true); }
}
