const $ = (s, el = document) => el.querySelector(s);
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const kg = n => Number(n || 0).toLocaleString(undefined, { maximumFractionDigits: 1 }) + " kg";
let user = null, categories = [];

async function api(path, method = "GET", body) {
  let res;
  try {
    res = await fetch("/api" + path, {
      method, headers: { "Content-Type": "application/json" },
      body: body ? JSON.stringify(body) : undefined, credentials: "same-origin"
    });
  } catch {
    throw new Error("Can't reach the server. Check that Flask is running and you opened the site from its URL.");
  }
  const text = await res.text();
  let data = null;
  try { data = JSON.parse(text); } catch { }
  if (!data) throw new Error(`Server replied ${res.status} without data. Open the site via http://localhost:5000 or your Vercel URL, not as a local file.`);
  if (!res.ok) throw new Error(data.error || `Request failed (${res.status}).`);
  return data;
}
function toast(msg) {
  const t = $("#toast"); t.textContent = msg; t.classList.add("show");
  setTimeout(() => t.classList.remove("show"), 2800);
}

/* ---------- auth ---------- */
document.querySelectorAll(".tab").forEach(b => b.onclick = () => {
  document.querySelectorAll(".tab").forEach(x => x.classList.toggle("active", x === b));
  $("#loginForm").classList.toggle("hidden", b.dataset.tab !== "login");
  $("#registerForm").classList.toggle("hidden", b.dataset.tab !== "register");
  $("#authError").textContent = "";
});
async function signIn(email, password) {
  try { user = (await api("/login", "POST", { email, password })).user; start(); }
  catch (e) { $("#authError").textContent = e.message; }
}
$("#loginForm").onsubmit = e => { e.preventDefault(); signIn($("#loginEmail").value, $("#loginPass").value); };
document.querySelectorAll("[data-demo]").forEach(b => b.onclick = () => signIn(b.dataset.demo, "demo123"));
$("#registerForm").onsubmit = async e => {
  e.preventDefault();
  try {
    user = (await api("/register", "POST", {
      name: $("#regName").value, email: $("#regEmail").value, phone: $("#regPhone").value,
      password: $("#regPass").value, role: $("#regRole").value })).user;
    start();
  } catch (err) { $("#authError").textContent = err.message; }
};
$("#logout").onclick = async () => { await api("/logout", "POST"); user = null; showAuth(); };

function showAuth() { $("#app").classList.add("hidden"); $("#auth").classList.remove("hidden"); }

/* ---------- shell ---------- */
const MENU = {
  farmer: [["dashboard", "Dashboard"], ["report", "Report waste"], ["requests", "My requests"], ["recycling", "Recycling guide"], ["notifications", "Notifications"]],
  worker: [["dashboard", "Dashboard"], ["requests", "Collection jobs"], ["reports", "Analytics"], ["recycling", "Recycling guide"], ["notifications", "Notifications"]],
  admin: [["dashboard", "Dashboard"], ["requests", "All requests"], ["users", "Users"], ["reports", "Analytics"], ["feedback", "Feedback"], ["notifications", "Notifications"]]
};
async function start() {
  $("#auth").classList.add("hidden"); $("#app").classList.remove("hidden");
  $("#whoName").textContent = user.name; $("#whoRole").textContent = user.role === "worker" ? "collection worker" : user.role;
  categories = await api("/categories");
  go("dashboard");
}
async function go(view) {
  const d = await api("/dashboard").catch(() => ({ unread: 0 }));
  $("#nav").innerHTML = MENU[user.role].map(([id, label]) =>
    `<button data-v="${id}" class="${id === view ? "active" : ""}">${label}${id === "notifications" && d.unread ? `<span class="badge">${d.unread}</span>` : ""}</button>`).join("");
  document.querySelectorAll("#nav button").forEach(b => b.onclick = () => go(b.dataset.v));
  $("#view").innerHTML = '<p class="sub">Loading…</p>';
  try { await VIEWS[view](d); } catch (e) { $("#view").innerHTML = `<p class="error">${esc(e.message)}</p>`; }
  $("#view").focus();
}
const head = (t, s) => `<h2>${t}</h2><p class="sub">${s}</p>`;
const pill = s => `<span class="pill ${s}">${s}</span>`;

/* ---------- views ---------- */
const VIEWS = {
  async dashboard(d) {
    const cards = [["Waste reported", kg(d.reported), "all submissions"], ["Collected", kg(d.collected), "picked up"],
      ["Recycled", kg(d.recycled), "turned into compost, fuel or mulch"], ["Pending requests", d.pending, "waiting for a collector"]];
    const rows = (await api("/requests")).slice(0, 5);
    $("#view").innerHTML = head(`Hello, ${esc(user.name.split(" ")[0])}`, user.role === "farmer" ? "Here is where your farm waste stands." : "Here is the current picture.") +
      `<div class="stats">${cards.map(c => `<div class="stat"><small>${c[0]}</small><b>${c[1]}</b><small>${c[2]}</small></div>`).join("")}</div>
       <div class="panel"><h3>Recent requests</h3>${requestTable(rows, false)}</div>` +
      (user.role === "farmer" ? `<button class="btn primary" onclick="go('report')">Report waste</button>` : "");
    bindActions();
  },

  async report() {
    $("#view").innerHTML = head("Report waste and request pickup", "Tell us what you have and where to collect it.") +
      `<form id="wasteForm" class="panel form-grid">
        <label>Waste type<select id="wCat" required>${categories.map(c => `<option value="${c.id}">${esc(c.name)}</option>`).join("")}</select></label>
        <label>Quantity (kg)<input id="wQty" type="number" min="1" step="any" required placeholder="e.g. 250"></label>
        <div class="full tipbox" id="wTip"></div>
        <label class="full">Pickup address or landmark<input id="wAddr" required placeholder="Village, road, plot number"></label>
        <div class="full row">
          <button type="button" class="btn ghost" id="gps">Use my current location</button>
          <span class="hint" id="gpsOut">GPS is optional but helps collectors find you.</span>
        </div>
        <label class="full">Notes (optional)<textarea id="wNotes" placeholder="Access gate, best time, how it's stacked…"></textarea></label>
        <div class="full"><button class="btn primary" type="submit">Submit request</button></div>
      </form>`;
    let lat = null, lng = null;
    const tip = () => { const c = categories.find(c => c.id == $("#wCat").value); $("#wTip").innerHTML = `<b>Best use: ${esc(c.recycling_method)}.</b> ${esc(c.recycling_tip)}`; };
    $("#wCat").onchange = tip; tip();
    $("#gps").onclick = () => {
      if (!navigator.geolocation) return toast("Location isn't supported on this device.");
      $("#gpsOut").textContent = "Finding you…";
      navigator.geolocation.getCurrentPosition(p => {
        lat = p.coords.latitude; lng = p.coords.longitude;
        $("#gpsOut").innerHTML = `Saved ${lat.toFixed(4)}, ${lng.toFixed(4)} · <a target="_blank" rel="noopener" href="https://www.openstreetmap.org/?mlat=${lat}&mlon=${lng}#map=15/${lat}/${lng}">view on map</a>`;
      }, () => $("#gpsOut").textContent = "Couldn't get location. Type the address instead.", { enableHighAccuracy: true, timeout: 10000 });
    };
    $("#wasteForm").onsubmit = async e => {
      e.preventDefault();
      try {
        await api("/requests", "POST", { category_id: $("#wCat").value, quantity_kg: $("#wQty").value,
          address: $("#wAddr").value, notes: $("#wNotes").value, latitude: lat, longitude: lng });
        toast("Request submitted"); go("requests");
      } catch (err) { toast(err.message); }
    };
  },

  async requests() {
    const rows = await api("/requests");
    const titles = { farmer: ["My requests", "Track each pickup and rate completed ones."], worker: ["Collection jobs", "Accept open requests and update their progress."], admin: ["All requests", "Every collection request in the system."] };
    $("#view").innerHTML = head(...titles[user.role]) + `<div class="panel">${requestTable(rows, true)}</div>`;
    bindActions();
  },

  async recycling() {
    $("#view").innerHTML = head("Recycling guide", "How each type of farm waste is best reused.") +
      `<div class="grid2">${categories.map(c => `<div class="tipcard"><span class="pill">${esc(c.recycling_method)}</span><h3>${esc(c.name)}</h3><p class="hint">${esc(c.description)}</p><p style="margin-top:.5rem">${esc(c.recycling_tip)}</p></div>`).join("")}</div>`;
  },

  async notifications() {
    const rows = await api("/notifications");
    $("#view").innerHTML = head("Notifications", "Updates on your requests.") +
      `<div class="panel">${rows.length ? rows.map(n => `<div class="note ${n.is_read ? "" : "unread"}">${esc(n.message)}<small>${esc(n.created_at)}</small></div>`).join("") : '<p class="empty">Nothing yet. Updates will appear here.</p>'}</div>`;
    await api("/notifications/read", "POST");
  },

  async reports() {
    const r = await api("/reports"); const max = Math.max(1, ...r.by_category.map(x => x.kg));
    const maxM = Math.max(1, ...r.monthly.map(x => x.kg));
    $("#view").innerHTML = head("Reports and analytics", "Waste volumes, request outcomes and service quality.") +
      `<div class="panel"><h3>Waste by category</h3><div class="bars">${r.by_category.map(x => `<div class="bar"><span>${esc(x.name)}</span><i style="width:${x.kg / max * 100}%"></i><span>${kg(x.kg)}</span></div>`).join("") || '<p class="empty">No data yet.</p>'}</div></div>
       <div class="panel"><h3>Waste reported per month</h3><div class="bars">${r.monthly.map(x => `<div class="bar alt"><span>${esc(x.month)}</span><i style="width:${x.kg / maxM * 100}%"></i><span>${kg(x.kg)}</span></div>`).join("")}</div></div>
       <div class="grid2"><div class="panel"><h3>Requests by status</h3>${r.by_status.map(s => `<p>${pill(s.status)} <b>${s.n}</b></p>`).join("")}</div>
       <div class="panel"><h3>Service rating</h3><p class="stat" style="border:0;padding:0"><b>${r.feedback.avg ?? "–"} / 5</b></p><p class="hint">${r.feedback.n} reviews</p></div></div>`;
  },

  async users() {
    const rows = await api("/admin/users");
    $("#view").innerHTML = head("Users", "Farmers, collection workers and admins.") +
      `<div class="panel tbl"><table><tr><th>Name</th><th>Email</th><th>Role</th><th>Joined</th><th></th></tr>${rows.map(u => `<tr><td>${esc(u.name)}</td><td>${esc(u.email)}</td><td>${pill(u.role)}</td><td>${esc(u.created_at.slice(0, 10))}</td><td>${u.id === user.id ? "" : `<button class="btn sm danger" data-deluser="${u.id}">Delete</button>`}</td></tr>`).join("")}</table></div>`;
    document.querySelectorAll("[data-deluser]").forEach(b => b.onclick = async () => {
      if (confirm("Delete this user and all of their records?")) { await api("/admin/users/" + b.dataset.deluser, "DELETE"); toast("User deleted"); go("users"); }
    });
  },

  async feedback() {
    const rows = await api("/admin/feedback");
    $("#view").innerHTML = head("Feedback", "What farmers say about collection.") +
      `<div class="panel">${rows.length ? rows.map(f => `<div class="note"><b>${"★".repeat(f.rating)}${"☆".repeat(5 - f.rating)}</b> ${esc(f.farmer)} on request #${f.request_id}<small>${esc(f.comment || "No comment")}</small></div>`).join("") : '<p class="empty">No feedback yet.</p>'}</div>`;
  }
};

/* ---------- request table + actions ---------- */
function requestTable(rows, actions) {
  if (!rows.length) return '<p class="empty">No requests yet.</p>';
  return `<div class="tbl"><table><tr><th>#</th><th>Waste</th><th>Quantity</th><th>Location</th><th>Status</th>${actions ? "<th>Action</th>" : ""}</tr>` +
    rows.map(r => `<tr><td>${r.id}</td><td>${esc(r.category)}</td><td>${kg(r.quantity_kg)}</td>
      <td>${esc(r.address)}${r.latitude ? ` <a target="_blank" rel="noopener" href="https://www.openstreetmap.org/?mlat=${r.latitude}&mlon=${r.longitude}#map=15/${r.latitude}/${r.longitude}">map</a>` : ""}${user.role !== "farmer" ? `<br><small class="hint">${esc(r.farmer)}</small>` : ""}</td>
      <td>${pill(r.status)}${r.scheduled_date ? `<br><small class="hint">${esc(r.scheduled_date)}</small>` : ""}</td>
      ${actions ? `<td>${actionFor(r)}</td>` : ""}</tr>`).join("") + "</table></div>";
}
function actionFor(r) {
  if (user.role === "farmer")
    return ["collected", "recycled"].includes(r.status) && !r.has_feedback ? `<button class="btn sm" data-rate="${r.id}">Rate service</button>` : "";
  const b = (s, label, cls = "") => `<button class="btn sm ${cls}" data-set="${r.id}:${s}">${label}</button>`;
  const del = user.role === "admin" ? `<button class="btn sm danger" data-delreq="${r.id}">Delete</button>` : "";
  const flow = { pending: b("accepted", "Accept", "primary") + " " + b("rejected", "Reject"),
    accepted: b("scheduled", "Schedule pickup", "primary"), scheduled: b("collected", "Mark collected", "primary"),
    collected: b("recycled", "Mark recycled", "primary") };
  return `<div class="row">${flow[r.status] || ""}${del}</div>`;
}
function bindActions() {
  document.querySelectorAll("[data-set]").forEach(b => b.onclick = async () => {
    const [id, status] = b.dataset.set.split(":"); const body = { status };
    if (status === "scheduled") { body.scheduled_date = prompt("Pickup date (YYYY-MM-DD)", new Date(Date.now() + 864e5).toISOString().slice(0, 10)); if (!body.scheduled_date) return; }
    try { await api("/requests/" + id, "PATCH", body); toast("Status updated"); go("requests"); } catch (e) { toast(e.message); }
  });
  document.querySelectorAll("[data-delreq]").forEach(b => b.onclick = async () => {
    if (confirm("Delete this request?")) { await api("/admin/requests/" + b.dataset.delreq, "DELETE"); go("requests"); }
  });
  document.querySelectorAll("[data-rate]").forEach(b => b.onclick = () => rateDialog(b.dataset.rate));
}
function rateDialog(id) {
  let rating = 0;
  $("#view").innerHTML = head("Rate the collection", `Request #${id}`) +
    `<form class="panel stack" id="fbForm"><div class="stars" role="radiogroup" aria-label="Rating">${[1, 2, 3, 4, 5].map(n => `<button type="button" data-n="${n}" aria-label="${n} stars">★</button>`).join("")}</div>
     <label>Comments (optional)<textarea id="fbText"></textarea></label><div class="row"><button class="btn primary">Send feedback</button><button type="button" class="btn ghost" onclick="go('requests')">Cancel</button></div></form>`;
  document.querySelectorAll(".stars button").forEach(s => s.onclick = () => {
    rating = +s.dataset.n; document.querySelectorAll(".stars button").forEach(x => x.classList.toggle("on", +x.dataset.n <= rating));
  });
  $("#fbForm").onsubmit = async e => {
    e.preventDefault();
    try { await api("/feedback", "POST", { request_id: id, rating, comment: $("#fbText").value }); toast("Thanks for your feedback"); go("requests"); }
    catch (err) { toast(err.message); }
  };
}

/* ---------- boot ---------- */
(async () => {
  try { user = (await api("/me")).user; } catch { }
  user ? start() : showAuth();
})();
