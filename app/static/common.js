/* Shared helpers. All user/file data is inserted with textContent (never innerHTML) to prevent XSS. */
"use strict";

const ME = { user: null, csrf: null };
const ICON_MARK = '<svg viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M4 7h10M4 12h16M4 17h7"/><path d="m15 15 3 3 4-5"/></svg>';

function $(sel, root) { return (root || document).querySelector(sel); }
function $all(sel, root) { return Array.from((root || document).querySelectorAll(sel)); }

/** el("div", {class: "x", text: "hi", onclick: fn}, [children]) */
function el(tag, attrs, children) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "text") n.textContent = v;
    else if (k === "class") n.className = v;
    else if (k.startsWith("on") && typeof v === "function") n.addEventListener(k.slice(2), v);
    else if (k === "value") n.value = v;
    else n.setAttribute(k, v === true ? "" : v);
  }
  for (const c of [].concat(children || [])) {
    if (c === null || c === undefined || c === false) continue;
    n.appendChild(typeof c === "string" ? document.createTextNode(c) : c);
  }
  return n;
}

async function api(path, opts) {
  opts = opts || {};
  const init = { method: opts.method || "GET", credentials: "same-origin", headers: {} };
  if (init.method !== "GET" && ME.csrf) init.headers["X-CSRF-Token"] = ME.csrf;
  if (opts.json !== undefined) { init.headers["Content-Type"] = "application/json"; init.body = JSON.stringify(opts.json); }
  else if (opts.form) init.body = opts.form;
  else if (init.method !== "GET") init.body = "";
  const res = await fetch(path, init);
  if (res.status === 401 && !opts.noRedirect) { location.href = "/login"; throw new Error("Please sign in"); }
  if (opts.raw) { if (!res.ok) throw new Error("Request failed (" + res.status + ")"); return res; }
  let body = null;
  try { body = await res.json(); } catch (e) { /* non-JSON */ }
  if (!res.ok) throw new Error((body && body.detail) || ("Request failed (" + res.status + ")"));
  return body;
}

let toastTimer;
function toast(msg, bad) {
  let t = $(".toast");
  if (!t) { t = el("div", { class: "toast", role: "status" }); document.body.appendChild(t); }
  t.textContent = msg;
  t.className = "toast" + (bad ? " bad" : "");
  t.classList.remove("hidden");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.add("hidden"), bad ? 5000 : 2600);
}

function fmtDateTime(s) {
  if (!s) return "";
  const d = new Date(s.endsWith("Z") ? s : s + "Z");
  return d.toLocaleString(undefined, { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });
}

function brand() {
  const mark = el("span", { class: "brand-mark" });
  mark.innerHTML = ICON_MARK; // constant, trusted
  return el("a", { class: "brand", href: "/" }, [mark, "Smart Renamer", el("small", { text: "Kramski India" })]);
}

async function boot(page, opts) {
  opts = opts || {};
  let me;
  try { me = await api("/api/auth/me", { noRedirect: true }); }
  catch (e) { location.href = "/login"; return null; }
  ME.user = me.user; ME.csrf = me.csrf; ME.maxUpload = me.max_upload_mb;
  if (me.user.must_change_password && page !== "account") { location.href = "/account?first=1"; return null; }
  if (opts.admin && me.user.role !== "admin") { location.href = "/"; return null; }

  const links = [["/", "Rename", "rename"], ["/history", "History", "history"]];
  if (me.user.role === "admin") links.push(["/admin", "Admin", "admin"]);
  links.push(["/account", "Account", "account"]);
  const nav = el("nav", { class: "nav" }, links.map(([href, label, key]) =>
    el("a", { href, class: key === page ? "active" : "", text: label })));
  const out = el("button", { class: "ghost sm", text: "Sign out", onclick: async () => {
    try { await api("/api/auth/logout", { method: "POST" }); } catch (e) { /* ignore */ }
    location.href = "/login";
  } });
  const who = el("div", { class: "who" }, [el("span", { text: me.user.display_name }), out]);
  $("#top").replaceChildren(el("div", { class: "topbar" }, [el("div", { class: "topbar-in" }, [brand(), nav, who])]));
  document.body.classList.remove("hidden");
  return me;
}

function confClass(c) { return c >= 0.75 ? "hi" : c >= 0.5 ? "mid" : "lo"; }
