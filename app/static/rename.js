"use strict";
/* Rename page: queue -> analyse on server -> review -> download with new name (renamed in the browser). */

const ICON_UP = '<svg viewBox="0 0 24 24" fill="none" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 16V4"/><path d="m7 9 5-5 5 5"/><path d="M4 16v3a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-3"/></svg>';
const FIELD_LABELS = { date: "Date", type: "Document type", party: "Customer / supplier", ref: "Reference no.", subject: "Subject" };
const items = [];
let META = { types: {} };
let running = 0;
const PARALLEL = 2;

(async function init() {
  const me = await boot("rename");
  if (!me) return;
  $("#dropIcon").innerHTML = ICON_UP; // constant
  try { META = await api("/api/meta"); } catch (e) { toast(e.message, true); }
  $("#dropHint").textContent += " · up to " + (ME.maxUpload || 50) + " MB each";

  const drop = $("#drop"), pick = $("#pick");
  drop.addEventListener("click", () => pick.click());
  drop.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); pick.click(); } });
  pick.addEventListener("change", () => { addFiles(pick.files); pick.value = ""; });
  ["dragenter", "dragover"].forEach((t) => drop.addEventListener(t, (e) => { e.preventDefault(); drop.classList.add("over"); }));
  ["dragleave", "drop"].forEach((t) => drop.addEventListener(t, (e) => { e.preventDefault(); drop.classList.remove("over"); }));
  drop.addEventListener("drop", (e) => addFiles(e.dataTransfer.files));
  window.addEventListener("dragover", (e) => e.preventDefault());
  window.addEventListener("drop", (e) => e.preventDefault());
  $("#clear").addEventListener("click", () => { items.length = 0; render(); });
  $("#all").addEventListener("click", downloadAll);
})();

function addFiles(fileList) {
  const max = (ME.maxUpload || 50) * 1024 * 1024;
  const batch = [];
  for (const f of Array.from(fileList || [])) {
    const it = { key: Math.random().toString(36).slice(2), file: f, status: "queued", result: null, name: "", fields: {}, open: false, edited: false };
    if (f.size > max) { it.status = "error"; it.error = "Too large (max " + (ME.maxUpload || 50) + " MB)"; }
    else if (f.size === 0) { it.status = "error"; it.error = "Empty file"; }
    batch.push(it);
  }
  items.unshift(...batch);
  render();
  pump();
}

function pump() {
  while (running < PARALLEL) {
    const next = items.find((i) => i.status === "queued");
    if (!next) return;
    analyse(next);
  }
}

async function analyse(it) {
  running++;
  it.status = "analysing";
  renderItem(it);
  const form = new FormData();
  form.append("file", it.file, it.file.name);
  form.append("source", "web");
  try {
    const r = await api("/api/analyze", { method: "POST", form });
    it.result = r;
    if (r.status === "blocked" || r.status === "error" || !r.suggested_name) {
      it.status = r.status === "blocked" ? "blocked" : "error";
      it.error = (r.warnings && r.warnings[0]) || r.error || "Could not be analysed";
    } else {
      it.status = r.status === "auto" ? "ready" : "review";
      it.name = r.suggested_name;
      it.fields = {};
      for (const k of Object.keys(FIELD_LABELS)) it.fields[k] = (r.fields[k] && r.fields[k].value) || "";
      it.open = it.status === "review";
    }
  } catch (e) {
    it.status = "error";
    it.error = e.message;
  }
  running--;
  renderItem(it);
  updateBar();
  pump();
}

function chip(it) {
  const c = it.result ? Math.round((it.result.confidence || 0) * 100) : 0;
  switch (it.status) {
    case "queued": return el("span", { class: "chip idle", text: "Waiting" });
    case "analysing": return el("span", { class: "row small muted" }, [el("span", { class: "spin" }), "Reading"]);
    case "ready": return el("span", { class: "chip ok", text: "Ready · " + c + "%", title: "Confidence " + c + "%" });
    case "review": return el("span", { class: "chip warn", text: "Please check · " + c + "%", title: "Confidence " + c + "%" });
    case "saved": return el("span", { class: "chip done", text: "Downloaded" });
    case "blocked": return el("span", { class: "chip bad", text: "Blocked" });
    default: return el("span", { class: "chip bad", text: "Failed" });
  }
}

function renderItem(it) {
  const old = document.getElementById("f-" + it.key);
  const node = buildItem(it);
  if (old) old.replaceWith(node); else render();
}

function buildItem(it) {
  const canAct = ["ready", "review", "saved"].includes(it.status);
  const orig = el("div", { class: "file-orig", title: it.file.name }, [it.file.name]);
  if (canAct) orig.appendChild(el("span", { class: "arrow", text: "→ new name" }));

  let nameArea;
  if (canAct) {
    nameArea = el("input", { type: "text", class: "name-input", value: it.name, "aria-label": "New file name", spellcheck: "false",
      oninput: (e) => { it.name = e.target.value; it.edited = true; } });
  } else if (it.status === "blocked" || it.status === "error") {
    nameArea = el("div", { class: "small muted", text: it.error || "Could not be analysed" });
  } else {
    nameArea = el("div", { class: "muted small", text: it.status === "queued" ? "Waiting to be read…" : "Reading the document…" });
  }

  const actions = el("div", { class: "file-actions" }, [chip(it)]);
  if (canAct) {
    actions.appendChild(el("button", { class: "ghost sm", text: it.open ? "Hide details" : "Details", "aria-expanded": String(it.open),
      onclick: () => { it.open = !it.open; renderItem(it); } }));
    actions.appendChild(el("button", { class: it.status === "saved" ? "sm" : "primary sm", text: it.status === "saved" ? "Download again" : "Download",
      onclick: () => download(it) }));
  } else if (it.status === "error" && it.result === null && it.file.size > 0 && it.error && !/Too large|Empty/.test(it.error)) {
    actions.appendChild(el("button", { class: "sm", text: "Retry", onclick: () => { it.status = "queued"; it.error = null; renderItem(it); pump(); } }));
  }

  const wrap = el("div", { class: "file", id: "f-" + it.key }, [
    el("div", { class: "file-main" }, [el("div", { class: "file-names" }, [orig, nameArea]), actions]),
  ]);
  if (canAct && it.open) wrap.appendChild(buildDetails(it));
  return wrap;
}

function buildDetails(it) {
  const box = el("div", { class: "details" });
  const f = it.result.fields || {};
  for (const [k, label] of Object.entries(FIELD_LABELS)) {
    const info = f[k] || {};
    let input;
    if (k === "type") {
      input = el("select", { "aria-label": label });
      const codes = Object.keys(META.types || {});
      if (it.fields.type && !codes.includes(it.fields.type)) codes.unshift(it.fields.type);
      for (const code of codes) input.appendChild(el("option", { value: code, text: code + " · " + (META.types[code] || code) }));
      input.value = it.fields.type || "DOC";
    } else if (k === "date") {
      input = el("input", { type: "date", value: it.fields.date || "", "aria-label": label });
    } else {
      input = el("input", { type: "text", value: it.fields[k] || "", "aria-label": label, maxlength: k === "subject" ? "200" : "120" });
    }
    input.addEventListener("change", () => { it.fields[k] = input.value; it.fieldsEdited = true; recompose(it); });
    const ev = info.value
      ? el("div", { class: "evidence" }, [el("span", { class: "conf " + confClass(info.confidence || 0) }), "Found: " + (info.source || "")])
      : el("div", { class: "evidence" }, [el("span", { class: "conf lo" }), "Not found in the file"]);
    box.appendChild(el("div", { class: "field" }, [el("label", { text: label }), input, ev]));
  }
  const warns = (it.result.warnings || []).filter(Boolean);
  if (it.result.ocr_used) warns.unshift("Text was read from a scan (OCR). Please double-check.");
  if (warns.length) box.appendChild(el("div", { class: "warnings", text: warns.join(" · ") }));
  return box;
}

async function recompose(it) {
  try {
    const r = await api("/api/compose", { method: "POST", json: { fields: it.fields, ext: it.result.ext || "" } });
    it.name = r.name;
    it.edited = false;
    const input = $("#f-" + it.key + " .name-input");
    if (input) input.value = r.name;
  } catch (e) { toast(e.message, true); }
}

async function download(it) {
  try {
    const body = { final_name: it.name };
    if (it.fieldsEdited) body.fields = it.fields;
    const r = await api("/api/files/" + encodeURIComponent(it.result.id) + "/finalize", { method: "POST", json: body });
    it.name = r.final_name;
    // Rename happens here in the browser: the original bytes are saved under the new name.
    const url = URL.createObjectURL(it.file);
    const a = el("a", { href: url, download: r.final_name });
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 30000);
    it.status = "saved";
    renderItem(it);
    updateBar();
  } catch (e) { toast(e.message, true); }
}

async function downloadAll() {
  const todo = items.filter((i) => i.status === "ready" || i.status === "review");
  if (!todo.length) { toast("Nothing new to download"); return; }
  for (const it of todo) {
    await download(it);
    await new Promise((r) => setTimeout(r, 350));
  }
}

function updateBar() {
  const done = items.filter((i) => ["ready", "review", "saved", "blocked", "error"].includes(i.status)).length;
  const pending = items.filter((i) => i.status === "ready" || i.status === "review").length;
  $("#count").textContent = items.length + (items.length === 1 ? " file" : " files") + (done < items.length ? " · reading " + (items.length - done) : "");
  $("#all").textContent = pending ? "Download all (" + pending + ")" : "Download all";
  $("#all").disabled = !pending;
}

function render() {
  $("#resultsArea").classList.toggle("hidden", items.length === 0);
  $("#list").replaceChildren(...items.map(buildItem));
  updateBar();
}
