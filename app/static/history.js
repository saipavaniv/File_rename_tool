"use strict";
const PAGE = 50;
let offset = 0, total = 0, timer;

(async function init() {
  const me = await boot("history");
  if (!me) return;
  if (me.user.role === "admin") {
    $("#allWrap").classList.remove("hidden");
    $("#export").classList.remove("hidden");
  }
  $("#q").addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(() => { offset = 0; load(); }, 250); });
  $("#all").addEventListener("change", () => { offset = 0; load(); });
  $("#prev").addEventListener("click", () => { offset = Math.max(0, offset - PAGE); load(); });
  $("#next").addEventListener("click", () => { offset += PAGE; load(); });
  $("#export").addEventListener("click", exportCsv);
  load();
})();

function allFlag() { return $("#all").checked ? "1" : "0"; }

async function load() {
  const q = $("#q").value.trim();
  const params = new URLSearchParams({ limit: PAGE, offset, all: allFlag() });
  if (q) params.set("q", q);
  try {
    const [data, st] = await Promise.all([api("/api/files?" + params), api("/api/stats?all=" + allFlag())]);
    total = data.total;
    renderStats(st);
    renderRows(data.items);
  } catch (e) { toast(e.message, true); }
}

function renderStats(s) {
  const pct = s.saved ? Math.round((s.accepted_unchanged / s.saved) * 100) + "%" : "–";
  const tiles = [[s.total, "Files analysed"], [s.saved, "Renamed and downloaded"], [pct, "Accepted without edits"], [s.blocked, "Blocked as unsafe"]];
  $("#stats").replaceChildren(...tiles.map(([v, l]) => el("div", { class: "card stat" }, [el("b", { text: String(v) }), el("span", { text: l })])));
}

function statusChip(r) {
  if (r.status === "saved") return el("span", { class: "chip done", text: r.final_name === r.suggested_name ? "Renamed" : "Renamed (edited)" });
  if (r.status === "blocked") return el("span", { class: "chip bad", text: "Blocked" });
  if (r.status === "error") return el("span", { class: "chip bad", text: "Failed" });
  return el("span", { class: "chip idle", text: "Not downloaded" });
}

function renderRows(rows) {
  const showUser = $("#all").checked;
  $("#userCol").classList.toggle("hidden", !showUser);
  if (!rows.length) {
    $("#rows").replaceChildren(el("tr", {}, [el("td", { colspan: "7", class: "empty", text: "No files yet." })]));
  } else {
    $("#rows").replaceChildren(...rows.map((r) => el("tr", {}, [
      el("td", { class: "small muted", text: fmtDateTime(r.created_at) }),
      el("td", {}, [
        el("div", { class: "small muted", text: r.original_name }),
        el("div", { class: "mono", text: r.final_name || r.suggested_name || "—" }),
        el("div", { class: "small muted mono", text: "SHA-256 " + (r.sha256 || "").slice(0, 16) + "…", title: r.sha256 || "" }),
      ]),
      el("td", { text: r.doc_type || "" }),
      el("td", { text: r.party || "" }),
      el("td", { class: "mono", text: r.reference || "" }),
      el("td", {}, [statusChip(r), el("div", { class: "small muted", text: r.source === "extension" ? "via browser button" : "via website" })]),
      showUser ? el("td", { text: r.user || "" }) : null,
    ])));
  }
  const end = Math.min(offset + PAGE, total);
  $("#pageInfo").textContent = total ? (offset + 1) + "–" + end + " of " + total : "";
  $("#prev").disabled = offset === 0;
  $("#next").disabled = end >= total;
}

async function exportCsv() {
  try {
    const q = $("#q").value.trim();
    const res = await api("/api/files/export.csv" + (q ? "?q=" + encodeURIComponent(q) : ""), { raw: true });
    const url = URL.createObjectURL(await res.blob());
    const a = el("a", { href: url, download: "rename-history.csv" });
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 10000);
  } catch (e) { toast(e.message, true); }
}
