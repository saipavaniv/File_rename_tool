"use strict";
const $ = (id) => document.getElementById(id);
const DEFAULT_SERVER = "http://localhost:8000";

(async function init() {
  const c = await chrome.storage.local.get(["server", "token", "folder"]);
  $("server").value = c.server || DEFAULT_SERVER;
  $("folder").value = c.folder ?? "Hop";
  $("state").textContent = c.token ? "✅ Connected. Click 🐇 on any page with files." : "Not connected yet. Click Connect below.";
  $("f").addEventListener("submit", connect);
  $("saveOnly").addEventListener("click", async () => {
    await chrome.storage.local.set({ folder: cleanFolder() });
    show("Saved.", true);
  });
  $("saveKey").addEventListener("click", saveKey);
})();

function show(text, ok) {
  const m = $("msg");
  m.textContent = text;
  m.className = ok ? "ok" : "bad";
}

function cleanFolder() { return $("folder").value.trim().replace(/[^A-Za-z0-9 _\-]/g, ""); }

async function checkedServer() {
  let url;
  try { url = new URL($("server").value.trim() || DEFAULT_SERVER); } catch (ex) { show("Enter an address like http://localhost:8000"); return null; }
  const local = ["localhost", "127.0.0.1"].includes(url.hostname);
  if (url.protocol !== "https:" && !(url.protocol === "http:" && local)) {
    show("For safety, Hop on another computer must use https:// (plain http is only allowed for this computer).");
    return null;
  }
  // Ask for permission to talk to this one address (the default localhost:8000 is already allowed).
  const granted = await chrome.permissions.request({ origins: [url.origin + "/*"] });
  if (!granted) { show("Permission to reach Hop was not given."); return null; }
  return url.origin;
}

async function connect(e) {
  e.preventDefault();
  const origin = await checkedServer();
  if (!origin) return;
  const prev = await chrome.storage.local.get(["server"]);
  const changes = { server: origin, folder: cleanFolder() };
  await chrome.storage.local.set(changes);
  if ((prev.server || DEFAULT_SERVER) !== origin) await chrome.storage.local.remove("token");
  const r = await chrome.runtime.sendMessage({ cmd: "pair" });
  if (r && r.ok) show("A tab opened: click Allow there. 🐇", true);
  else if (r && r.error === "offline") show("Hop isn't running at " + origin + ". Start it (run_local.bat), then click Connect again.");
  else show("Couldn't connect. Check the address and try again.");
}

async function saveKey() {
  const origin = await checkedServer();
  if (!origin) return;
  const token = $("token").value.trim();
  if (!/^krn_[A-Za-z0-9_\-]{20,}$/.test(token)) return show("The key should start with krn_. Copy it again from Hop → Account.");
  await chrome.storage.local.set({ server: origin, token, folder: cleanFolder() });
  const r = await chrome.runtime.sendMessage({ cmd: "test" });
  if (r && r.ok) show("Connected as " + (r.user.display_name || r.user.username) + ". 🐇", true);
  else show("Saved, but Hop answered: " + ((r && r.error) || "no response") + ".");
}
