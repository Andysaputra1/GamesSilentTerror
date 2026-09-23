"use strict";
const el = id => document.getElementById(id);
let token = "", after = 0;
async function request(url, options = {}) {
  const response = await fetch(url, {...options, cache: "no-store", headers: {"Content-Type": "application/json", ...(token ? {Authorization: `Bearer ${token}`} : {})}});
  if (response.status === 204) return null;
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Permintaan gagal.");
  return data;
}
async function load(reset = false) {
  el("more").disabled = true;
  if (reset) { after = 0; el("messages").replaceChildren(); }
  try {
    const query = new URLSearchParams({after_id: String(after), limit: "100"});
    if (el("room").value.trim()) query.set("room_code", el("room").value.trim());
    if (el("match").value.trim()) query.set("match_id", el("match").value.trim());
    const data = await request(`/api/history/messages?${query}`);
    for (const row of data.messages) {
      const tr = document.createElement("tr");
      for (const value of [`${row.id} / ${row.created_at}`, `${row.room_code || "-"} / ${row.match_id || "-"} / ${row.round_number ?? "-"} / ${row.phase || "-"}`, `${row.sender_name} (${row.sender_kind})`, row.message]) {
        const td = document.createElement("td"); td.textContent = value; tr.append(td);
      }
      el("messages").append(tr);
    }
    after = data.next_after_id; el("more").hidden = !data.has_more;
    el("status").textContent = data.messages.length ? "Riwayat berhasil dimuat." : "Tidak ada pesan berikutnya.";
  } catch (error) { el("status").textContent = error.message; }
  finally { el("more").disabled = false; }
}
el("login").onsubmit = async event => {
  event.preventDefault();
  try {
    const data = await request("/api/auth/login", {method: "POST", body: JSON.stringify({username: el("username").value, password: el("password").value})});
    token = data.access_token; el("password").value = "";
    el("login").hidden = true; el("viewer").hidden = false; await load(true);
  } catch (error) { el("status").textContent = error.message; }
};
el("filters").onsubmit = event => { event.preventDefault(); load(true); };
el("more").onclick = () => load();
el("logout").onclick = async () => {
  try { await request("/api/auth/logout", {method: "POST"}); }
  catch (_) { /* Clear local access even when the server is unavailable. */ }
  token = ""; after = 0; el("messages").replaceChildren(); el("viewer").hidden = true; el("login").hidden = false; el("status").textContent = "Keluar dari halaman riwayat.";
};
