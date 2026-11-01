"use strict";

(async function init() {
  const code = new URLSearchParams(location.hash.slice(1)).get("code") || "";
  const me = await boot("connect");
  if (!me) return;
  if (!/^[A-Za-z0-9_\-]{32,128}$/.test(code)) return fail("Open the Hop button and click Connect again.");
  $("#allow").addEventListener("click", async () => {
    $("#allow").disabled = true;
    try {
      await api("/api/pair/approve", { method: "POST", json: { code } });
      history.replaceState(null, "", "/connect");   // drop the code from the address bar
      $("#ask").classList.add("hidden");
      $("#done").classList.remove("hidden");
    } catch (e) { fail(e.message); }
  });
})();

function fail(msg) {
  $("#ask").classList.add("hidden");
  $("#badMsg").textContent = msg;
  $("#bad").classList.remove("hidden");
}
