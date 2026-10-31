"use strict";
const $ = (id) => document.getElementById(id);

(async function init() {
  const c = await chrome.storage.local.get(["server", "token", "folder"]);
  $("server").value = c.server || "";
  $("token").value = c.token || "";
  $("folder").value = c.folder ?? "Renamed";
  $("f").addEventListener("submit", save);
})();

function show(text, ok) {
  const m = $("msg");
  m.textContent = text;
  m.className = ok ? "ok" : "bad";
}

async function save(e) {
  e.preventDefault();
  let url;
  try { url = new URL($("server").value.trim()); } catch (ex) { return show("Enter the full server address, e.g. https://renamer.kramski.local"); }
  const local = ["localhost", "127.0.0.1"].includes(url.hostname);
  if (url.protocol !== "https:" && !(url.protocol === "http:" && local)) {
    return show("For security the server must use https:// (http is only allowed for localhost testing).");
  }
  const token = $("token").value.trim();
  if (!/^krn_[A-Za-z0-9_\-]{20,}$/.test(token)) return show("The key should start with krn_ — copy it again from the website.");
  // Ask Chrome for permission to talk to this one server only (must happen on this click).
  const granted = await chrome.permissions.request({ origins: [url.origin + "/*"] });
  if (!granted) return show("Permission to contact the server was not given.");
  await chrome.storage.local.set({ server: url.origin, token, folder: $("folder").value.trim() });
  const r = await chrome.runtime.sendMessage({ cmd: "test" });
  if (r && r.ok) show("Connected as " + (r.user.display_name || r.user.username) + ". You're ready: open a page with files and click the Smart Renamer icon.", true);
  else show("Saved, but the server answered: " + ((r && r.error) || "no response") + ". Check the address and key.");
}
