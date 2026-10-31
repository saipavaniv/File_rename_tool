"use strict";
let tabId = null;

function $(id) { return document.getElementById(id); }
function el(tag, cls, text) { const n = document.createElement(tag); if (cls) n.className = cls; if (text !== undefined) n.textContent = text; return n; }

const LABEL = {
  queued: ["Waiting", "idle"], reading: ["Reading", "work"], naming: ["Naming", "work"],
  done: ["Downloaded", "ok"], check: ["Downloaded · check", "warn"], blocked: ["Blocked", "bad"],
  failed: ["Failed", "bad"], access: ["Needs access", "warn"],
};

(async function init() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  tabId = tab && tab.id;
  const cfg = await chrome.storage.local.get(["server", "token"]);
  $("settings").onclick = () => chrome.runtime.openOptionsPage();
  $("openSetup").onclick = () => chrome.runtime.openOptionsPage();
  $("site").onclick = () => cfg.server && chrome.tabs.create({ url: cfg.server.replace(/\/+$/, "") + "/history" });
  $("again").onclick = () => send("rescan");
  $("retry").onclick = () => send("retry");
  chrome.storage.session.onChanged.addListener((changes) => {
    const c = changes["tab:" + tabId];
    if (c) render(c.newValue);
  });
  if (!cfg.server || !cfg.token || !tabId) { $("setup").classList.remove("hidden"); return; }
  $("main").classList.remove("hidden");
  const res = await send("scan");   // clicking the icon IS the action: scan, rename, download
  if (res && res.error === "setup") { $("main").classList.add("hidden"); $("setup").classList.remove("hidden"); return; }
  const k = "tab:" + tabId;
  render((await chrome.storage.session.get(k))[k]);
})();

function send(cmd, extra) {
  return chrome.runtime.sendMessage(Object.assign({ cmd, tabId }, extra || {}));
}

function render(s) {
  if (!s) return;
  const items = s.items || [];
  $("none").classList.toggle("hidden", items.length > 0 || !!s.running);
  if (s.error) { $("status").textContent = s.error; $("list").replaceChildren(); return; }
  const finished = items.filter((i) => ["done", "check", "blocked", "failed", "access"].includes(i.status)).length;
  const ok = items.filter((i) => i.status === "done" || i.status === "check").length;
  const st = $("status");
  st.replaceChildren();
  if (!items.length) st.textContent = s.running ? "Looking for files…" : "";
  else if (s.running) { st.append("Renaming "); st.append(el("strong", null, finished + " of " + items.length)); st.append(" files…"); }
  else { st.append(el("strong", null, ok + " of " + items.length)); st.append(" files renamed and saved to Downloads" + (s.tooMany ? " (first 30 only)" : "")); }
  $("progress").style.width = items.length ? Math.round((finished / items.length) * 100) + "%" : "0";
  $("retry").classList.toggle("hidden", s.running || !items.some((i) => i.status === "failed" || i.status === "access"));

  // permission requests for files hosted on another site (must come from a click here)
  const origins = [...new Set(items.filter((i) => i.status === "access").map((i) => i.origin))];
  const acc = $("access");
  acc.replaceChildren();
  acc.classList.toggle("hidden", !origins.length || s.running);
  if (origins.length && !s.running) {
    acc.append("Some files are stored on " + origins.join(", ") + ". Allow the extension to read files from there?");
    const b = el("button", "primary", "Allow and retry");
    b.onclick = async () => {
      const granted = await chrome.permissions.request({ origins: origins.map((o) => o + "/*") });
      if (granted) send("retry", { statuses: ["access"] });
    };
    acc.append(el("br"), b);
  }

  $("list").replaceChildren(...items.map((it) => {
    const li = el("li");
    const [label, cls] = LABEL[it.status] || [it.status, "idle"];
    li.append(el("div", "orig", it.original || it.name || it.url));
    li.append(el("span", "chip " + cls, it.status === "done" || it.status === "check" ? (label + " " + Math.round((it.confidence || 0) * 100) + "%") : label));
    if (it.newName) li.append(el("div", "new", it.newName));
    if (it.message && it.status !== "access") li.append(el("div", "msg", it.message));
    return li;
  }));
}
