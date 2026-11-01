"use strict";
$("#brand").replaceWith(brand());
if (location.protocol !== "https:" && !["localhost", "127.0.0.1"].includes(location.hostname)) {
  $("#note").textContent = "Warning: this connection is not encrypted (no HTTPS). Ask IT to enable HTTPS.";
}
$("#form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const err = $("#err"), go = $("#go");
  err.classList.add("hidden");
  const username = $("#u").value.trim(), password = $("#p").value;
  if (!username || !password) { err.textContent = "Enter your username and password."; err.classList.remove("hidden"); return; }
  go.disabled = true;
  try {
    const r = await api("/api/auth/login", { method: "POST", json: { username, password }, noRedirect: true });
    let next = "/";
    try { next = sessionStorage.getItem("hop-next") || "/"; sessionStorage.removeItem("hop-next"); } catch (e) { /* ignore */ }
    if (!next.startsWith("/") || next.startsWith("//")) next = "/";
    location.href = r.user.must_change_password ? "/account?first=1" : next;
  } catch (ex) {
    err.textContent = ex.message;
    err.classList.remove("hidden");
    $("#p").value = "";
    $("#p").focus();
  } finally {
    go.disabled = false;
  }
});
