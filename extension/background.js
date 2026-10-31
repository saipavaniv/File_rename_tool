/* Smart Renamer extension - background worker.
 * Click -> find files on the page -> read each one (with the page's own login) -> send to the
 * company server for naming -> download the SAME bytes under the new name.
 * Talks only to the server configured in Settings. Nothing runs until the user clicks. */
"use strict";

const MAX_FILES = 30;
const MAX_BYTES = 50 * 1024 * 1024;
const PARALLEL = 2;

// ------------------------------------------------------------------ settings & state

async function getConfig() {
  const c = await chrome.storage.local.get(["server", "token", "folder"]);
  return { server: (c.server || "").replace(/\/+$/, ""), token: c.token || "", folder: c.folder ?? "Renamed" };
}

// In-memory state per tab (single source of truth, so parallel downloads can't overwrite each
// other's progress), mirrored to session storage so the popup can show it and it survives a restart.
const STATE = new Map();
let persistChain = Promise.resolve();

async function getState(tabId) {
  if (STATE.has(tabId)) return STATE.get(tabId);
  const k = "tab:" + tabId;
  const s = (await chrome.storage.session.get(k))[k] || null;
  if (s && !STATE.has(tabId)) STATE.set(tabId, s);
  return STATE.get(tabId) || null;
}

function setState(tabId, state) {
  STATE.set(tabId, state);
  const snapshot = JSON.parse(JSON.stringify(state));
  persistChain = persistChain.then(() => chrome.storage.session.set({ ["tab:" + tabId]: snapshot })).catch(() => {});
  return persistChain;
}

function clearState(tabId) {
  STATE.delete(tabId);
  return chrome.storage.session.remove("tab:" + tabId);
}

async function patchItem(tabId, idx, patch) {
  const s = await getState(tabId);
  if (!s || !s.items[idx]) return;
  Object.assign(s.items[idx], patch);
  await setState(tabId, s);
}

// ------------------------------------------------------------------ functions injected into the page

/* Runs inside the web page: list file links + light context (title, sender emails). */
function scanPage() {
  const EXT = /\.(pdf|docx?|xlsx?|xlsm|xlsb|pptx?|csv|txt|rtf|odt|ods|msg|eml|dxf|dwg|step|stp|igs|iges|stl|zip|7z|rar|png|jpe?g|tiff?|bmp|gif|xml)(?:$|[?#])/i;
  const PATTERN = /(attid=|[?&]disp=safe|view=att|\/attachments?\/|\/download(?:$|[/?])|[?&]download=|export=download|getattachment|\/files?\/)/i;
  const out = [], seen = new Set();
  const ct = (document.contentType || "").toLowerCase();
  if (ct && !ct.startsWith("text/html") && !ct.includes("xml+html")) {
    out.push({ url: location.href, name: decodeURIComponent((location.pathname.split("/").pop() || "").slice(0, 200)), linkText: document.title });
    seen.add(location.href);
  }
  for (const a of document.querySelectorAll("a[href]")) {
    let href;
    try { href = new URL(a.getAttribute("href"), location.href).href; } catch (e) { continue; }
    if (!/^(https?|blob|data):/i.test(href) || seen.has(href)) continue;
    const dl = a.hasAttribute("download");
    const path = (() => { try { return new URL(href).pathname; } catch (e) { return ""; } })();
    if (!(dl || EXT.test(path) || EXT.test(href) || PATTERN.test(href))) continue;
    if (/^data:text\/html/i.test(href)) continue;
    seen.add(href);
    const text = (a.getAttribute("download") || a.getAttribute("aria-label") || a.textContent || "").replace(/\s+/g, " ").trim();
    let name = a.getAttribute("download") || "";
    if (!name) { try { name = decodeURIComponent(path.split("/").pop() || ""); } catch (e) { name = ""; } }
    out.push({ url: href, name: name.slice(0, 200), linkText: text.slice(0, 200) });
    if (out.length >= 40) break;
  }
  const emails = new Set();
  for (const n of document.querySelectorAll("[email], a[href^='mailto:']")) {
    const e = (n.getAttribute("email") || n.getAttribute("href").slice(7).split("?")[0] || "").trim().toLowerCase();
    if (/^[^@\s]{1,64}@[^@\s]{1,190}\.[a-z]{2,24}$/.test(e)) emails.add(e);
    if (emails.size >= 5) break;
  }
  let subject = "";
  if (location.hostname === "mail.google.com") subject = (document.title.split(" - ")[0] || "").trim();
  const h = document.querySelector("h2.hP");
  if (h) subject = h.textContent.trim();
  return { files: out, context: { page_title: document.title.slice(0, 300), page_host: location.hostname,
           sender_emails: Array.from(emails), email_subject: subject.slice(0, 300) } };
}

/* Runs inside the web page: download one file using the page's own session (cookies). */
async function fetchInPage(url, max) {
  try {
    const r = await fetch(url, { credentials: "include" });
    if (!r.ok) return { error: "Server said " + r.status };
    const ct = r.headers.get("content-type") || "";
    const len = +(r.headers.get("content-length") || 0);
    if (len > max) return { error: "Too large" };
    const buf = await r.arrayBuffer();
    if (buf.byteLength > max) return { error: "Too large" };
    const bytes = new Uint8Array(buf);
    let bin = "";
    for (let i = 0; i < bytes.length; i += 0x8000) bin += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
    return { b64: btoa(bin), ct, cd: r.headers.get("content-disposition") || "", size: buf.byteLength };
  } catch (e) {
    return { error: "cross-origin" };
  }
}

// ------------------------------------------------------------------ helpers

function b64ToBytes(b64) {
  const bin = atob(b64);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

async function bytesToB64(buf) {
  const bytes = new Uint8Array(buf);
  let bin = "";
  for (let i = 0; i < bytes.length; i += 0x8000) bin += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
  return btoa(bin);
}

function nameFromDisposition(cd) {
  if (!cd) return "";
  const star = /filename\*\s*=\s*(?:UTF-8|utf-8)''([^;]+)/.exec(cd);
  if (star) { try { return decodeURIComponent(star[1].trim().replace(/^"|"$/g, "")); } catch (e) { /* fall through */ } }
  const plain = /filename\s*=\s*"?([^";]+)"?/i.exec(cd);
  return plain ? plain[1].trim() : "";
}

function originOf(url) {
  try { const u = new URL(url); return /^https?:$/.test(u.protocol) ? u.origin : ""; } catch (e) { return ""; }
}

async function serverCall(cfg, path, init) {
  const res = await fetch(cfg.server + path, Object.assign({ credentials: "omit", cache: "no-store" }, init, {
    headers: Object.assign({ Authorization: "Bearer " + cfg.token }, (init && init.headers) || {}) }));
  let body = null;
  try { body = await res.json(); } catch (e) { /* ignore */ }
  if (!res.ok) throw new Error((body && body.detail) || "Server error " + res.status);
  return body;
}

// ------------------------------------------------------------------ main flow

async function getBytes(tabId, item) {
  // First try inside the page itself: uses the page's own login and works for blob: links.
  let r = null;
  try {
    const [res] = await chrome.scripting.executeScript({ target: { tabId }, func: fetchInPage, args: [item.url, MAX_BYTES] });
    r = res && res.result;
  } catch (e) { r = { error: "cross-origin" }; }
  if (r && r.b64) return r;
  if (r && r.error && r.error !== "cross-origin") throw new Error(r.error);
  // Cross-origin file (e.g. attachment served from another domain): fetch from the extension,
  // only if the user has allowed that site.
  const origin = originOf(item.url);
  if (!origin) throw new Error("Could not read this file");
  if (!(await chrome.permissions.contains({ origins: [origin + "/*"] }))) {
    const e = new Error("Needs permission");
    e.needsAccess = origin;
    throw e;
  }
  const resp = await fetch(item.url, { credentials: "include" });
  if (!resp.ok) throw new Error("Server said " + resp.status);
  const buf = await resp.arrayBuffer();
  if (buf.byteLength > MAX_BYTES) throw new Error("Too large");
  return { b64: await bytesToB64(buf), ct: resp.headers.get("content-type") || "", cd: resp.headers.get("content-disposition") || "", size: buf.byteLength };
}

async function processItem(tabId, idx, item, context, cfg) {
  await patchItem(tabId, idx, { status: "reading" });
  try {
    const data = await getBytes(tabId, item);
    if (/^text\/html/i.test(data.ct) && !/\.html?$/i.test(item.name)) throw new Error("Link opens a web page, not a file");
    const original = nameFromDisposition(data.cd) || item.name || "file";
    await patchItem(tabId, idx, { status: "naming", original });

    const bytes = b64ToBytes(data.b64);
    const form = new FormData();
    form.append("file", new Blob([bytes]), original.slice(0, 200));
    form.append("source", "extension");
    form.append("context", JSON.stringify(Object.assign({}, context, { link_text: item.linkText || "" })));
    const r = await serverCall(cfg, "/api/analyze", { method: "POST", body: form });
    if (!r.suggested_name || r.status === "blocked" || r.status === "error") {
      await patchItem(tabId, idx, { status: r.status === "blocked" ? "blocked" : "failed", message: (r.warnings && r.warnings[0]) || r.error || "Could not be named" });
      return;
    }
    const fin = await serverCall(cfg, "/api/files/" + encodeURIComponent(r.id) + "/finalize", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ final_name: r.suggested_name }) });

    const folder = (cfg.folder || "").replace(/[^A-Za-z0-9 _\-]/g, "").trim();
    await chrome.downloads.download({
      url: "data:application/octet-stream;base64," + data.b64,   // exactly the bytes that were analysed
      filename: (folder ? folder + "/" : "") + fin.final_name,
      conflictAction: "uniquify", saveAs: false,
    });
    await patchItem(tabId, idx, { status: r.status === "auto" ? "done" : "check", newName: fin.final_name,
                                  confidence: r.confidence, fileId: r.id });
  } catch (e) {
    if (e.needsAccess) await patchItem(tabId, idx, { status: "access", origin: e.needsAccess, message: "Allow access to " + e.needsAccess });
    else await patchItem(tabId, idx, { status: "failed", message: e.message || "Failed" });
  }
}

async function runQueue(tabId, indices, context, cfg) {
  let next = 0;
  async function lane() {
    while (next < indices.length) {
      const i = indices[next++];
      const s = await getState(tabId);
      await processItem(tabId, i, s.items[i], context, cfg);
    }
  }
  await Promise.all(Array.from({ length: PARALLEL }, lane));
  const s = await getState(tabId);
  if (s) { s.running = false; await setState(tabId, s); }
}

async function startScan(tabId) {
  const cfg = await getConfig();
  if (!cfg.server || !cfg.token) return { error: "setup" };
  if (!(await chrome.permissions.contains({ origins: [originOf(cfg.server) + "/*"] }))) return { error: "setup" };
  const existing = await getState(tabId);
  if (existing && existing.running) return { ok: true };
  let scan;
  try {
    const [res] = await chrome.scripting.executeScript({ target: { tabId }, func: scanPage });
    scan = res && res.result;
  } catch (e) {
    await setState(tabId, { running: false, items: [], error: "This page can't be read (browser pages, the Web Store and some PDFs viewers are protected)." });
    return { ok: true };
  }
  const files = (scan && scan.files || []).slice(0, MAX_FILES);
  const state = { running: files.length > 0, startedAt: Date.now(), context: scan.context, tooMany: (scan.files || []).length > MAX_FILES,
                  items: files.map((f) => ({ url: f.url, name: f.name, linkText: f.linkText, original: f.name || f.linkText || "file", status: "queued" })) };
  await setState(tabId, state);
  if (files.length) runQueue(tabId, files.map((_, i) => i), scan.context, cfg);
  return { ok: true };
}

async function retry(tabId, onlyStatus) {
  const cfg = await getConfig();
  const s = await getState(tabId);
  if (!s || s.running) return;
  const idx = s.items.map((it, i) => (onlyStatus.includes(it.status) ? i : -1)).filter((i) => i >= 0);
  if (!idx.length) return;
  idx.forEach((i) => { s.items[i].status = "queued"; s.items[i].message = ""; });
  s.running = true;
  await setState(tabId, s);
  runQueue(tabId, idx, s.context || {}, cfg);
}

// ------------------------------------------------------------------ messages from popup / options

chrome.runtime.onMessage.addListener((msg, sender, reply) => {
  if (sender.id !== chrome.runtime.id) return false;     // only our own pages
  (async () => {
    if (msg.cmd === "scan") reply(await startScan(msg.tabId));
    else if (msg.cmd === "rescan") { await clearState(msg.tabId); reply(await startScan(msg.tabId)); }
    else if (msg.cmd === "retry") { await retry(msg.tabId, msg.statuses || ["failed", "access"]); reply({ ok: true }); }
    else if (msg.cmd === "test") {
      const cfg = await getConfig();
      try { const me = await serverCall(cfg, "/api/auth/me", {}); reply({ ok: true, user: me.user }); }
      catch (e) { reply({ ok: false, error: e.message }); }
    } else reply({ error: "unknown" });
  })();
  return true;
});

// Right-click a link -> "Rename & download"
chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.create({ id: "smart-rename-link", title: "Rename && download with Smart Renamer", contexts: ["link"] });
  chrome.storage.local.get(["server"]).then((c) => { if (!c.server) chrome.runtime.openOptionsPage(); });
});

chrome.contextMenus.onClicked.addListener(async (info, tab) => {
  if (info.menuItemId !== "smart-rename-link" || !tab || !info.linkUrl) return;
  const cfg = await getConfig();
  if (!cfg.server || !cfg.token) { chrome.runtime.openOptionsPage(); return; }
  let context = {};
  try { const [res] = await chrome.scripting.executeScript({ target: { tabId: tab.id }, func: scanPage }); context = res.result.context; } catch (e) { /* ignore */ }
  const prev = (await getState(tab.id)) || { items: [] };
  const idx = prev.items.length;
  prev.items.push({ url: info.linkUrl, name: "", linkText: info.selectionText || "", original: info.linkUrl.split("/").pop().split("?")[0] || "file", status: "queued" });
  prev.running = true;
  prev.context = context;
  await setState(tab.id, prev);
  await runQueue(tab.id, [idx], context, cfg);
  const s = await getState(tab.id);
  const it = s && s.items[idx];
  chrome.action.setBadgeText({ tabId: tab.id, text: it && (it.status === "done" || it.status === "check") ? "✓" : "!" });
  chrome.action.setBadgeBackgroundColor({ tabId: tab.id, color: it && it.status === "done" ? "#0e5e59" : "#b3261e" });
});

chrome.tabs.onRemoved.addListener((tabId) => clearState(tabId));
chrome.tabs.onUpdated.addListener((tabId, change) => {
  if (change.status === "loading") getState(tabId).then((s) => { if (s && !s.running) clearState(tabId); });
});
