/* CR Shop admin console — vanilla JS, no build step.
 *
 * Talks to the same origin it is served from, so there is no CORS to configure.
 * Set window.ADMIN_API_BASE before this script loads to point elsewhere.
 */
(() => {
  "use strict";

  const API = window.ADMIN_API_BASE || "/api/v1";
  const TOKEN_KEY = "crshop.admin.access_token";
  const REFRESH_KEY = "crshop.admin.refresh_token";
  const USER_KEY = "crshop.admin.user";

  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
  ));

  const state = { tab: "applications", status: "PENDING", rows: [], selected: null, tempToken: null };

  // ---------------------------------------------------------------- transport
  async function request(method, path, body, token) {
    const headers = { "Content-Type": "application/json" };
    if (token) headers.Authorization = `Bearer ${token}`;
    const res = await fetch(API + path, { method, headers, body: body ? JSON.stringify(body) : undefined });
    let json = null;
    try { json = await res.json(); } catch { /* non-JSON body */ }
    return { res, json };
  }

  function errorFrom(res, json) {
    const err = json && json.error;
    return new Error(err ? `${err.message}${err.code ? ` (${err.code})` : ""}` : `HTTP ${res.status}`);
  }

  // One refresh in flight at a time: parallel 401s must not each spend the
  // same refresh token, since the backend rotates it on every use.
  let refreshing = null;
  function refreshTokens() {
    if (!refreshing) {
      refreshing = (async () => {
        const rt = sessionStorage.getItem(REFRESH_KEY);
        if (!rt) throw new Error("No session");
        const { res, json } = await request("POST", "/auth/refresh", { refresh_token: rt });
        if (!res.ok || !json || json.success === false) throw errorFrom(res, json);
        storeSession(json.data);
      })().finally(() => { refreshing = null; });
    }
    return refreshing;
  }

  async function api(method, path, body) {
    const token = sessionStorage.getItem(TOKEN_KEY);
    let { res, json } = await request(method, path, body, token);
    if (res.status === 401 && token) {
      try {
        await refreshTokens();
      } catch {
        signOut(false);
        throw new Error("Your session has expired. Sign in again.");
      }
      ({ res, json } = await request(method, path, body, sessionStorage.getItem(TOKEN_KEY)));
    }
    if (!res.ok || !json || json.success === false) throw errorFrom(res, json);
    return json;
  }

  // -------------------------------------------------------------------- auth
  function storeSession(data) {
    sessionStorage.setItem(TOKEN_KEY, data.tokens.access_token);
    sessionStorage.setItem(REFRESH_KEY, data.tokens.refresh_token);
    sessionStorage.setItem(USER_KEY, JSON.stringify(data.user));
  }

  function signOut(revoke = true) {
    const access = sessionStorage.getItem(TOKEN_KEY);
    const refresh = sessionStorage.getItem(REFRESH_KEY);
    sessionStorage.removeItem(TOKEN_KEY);
    sessionStorage.removeItem(REFRESH_KEY);
    sessionStorage.removeItem(USER_KEY);
    state.selected = null;
    state.rows = [];
    if (revoke && access && refresh) {
      // Best effort: the refresh token would otherwise stay valid for 30 days.
      request("POST", "/auth/logout", { refresh_token: refresh }, access).catch(() => {});
    }
    show("login");
  }

  function finishLogin(data) {
    if (data.user.role !== "ADMIN") throw new Error("That account is not an administrator.");
    storeSession(data);
    state.tempToken = null;
    $("login-2fa-row").hidden = true;
    $("login-code").value = "";
    $("login-password").value = "";
    show("app");
    load();
  }

  $("login-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    $("login-error").textContent = "";
    $("login-submit").disabled = true;
    try {
      let data;
      if (state.tempToken) {
        data = (await api("POST", "/auth/login/2fa", {
          temp_token: state.tempToken, code: $("login-code").value.trim(),
        })).data;
      } else {
        data = (await api("POST", "/auth/login", {
          email: $("login-email").value.trim(), password: $("login-password").value,
        })).data;
        if (data.requires_2fa) {
          state.tempToken = data.temp_token;
          $("login-2fa-row").hidden = false;
          $("login-code").required = true;
          $("login-code").focus();
          return;
        }
      }
      finishLogin(data);
    } catch (err) {
      $("login-error").textContent = err.message;
      if (/expired/i.test(err.message)) {
        // A stale 2FA challenge cannot be completed; start over from the password.
        state.tempToken = null;
        $("login-2fa-row").hidden = true;
        $("login-code").required = false;
      }
    } finally {
      $("login-submit").disabled = false;
    }
  });

  $("logout").addEventListener("click", () => signOut(true));

  // --------------------------------------------------------------------- ui
  function show(view) {
    $("login-view").hidden = view !== "login";
    $("app-view").hidden = view !== "app";
    if (view === "app") {
      const user = JSON.parse(sessionStorage.getItem(USER_KEY) || "{}");
      $("who").textContent = user.email || user.full_name || "";
    }
  }

  let flashTimer;
  function flash(msg, bad = false) {
    const el = $("flash");
    el.textContent = msg;
    el.className = "flash" + (bad ? " bad" : "");
    el.hidden = false;
    clearTimeout(flashTimer);
    flashTimer = setTimeout(() => { el.hidden = true; }, bad ? 8000 : 4000);
  }

  document.querySelectorAll(".tab").forEach((b) => b.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t === b));
    state.tab = b.dataset.tab;
    state.selected = null;
    $("status-filter").hidden = state.tab !== "applications";
    $("list-title").textContent = b.textContent;
    renderDetail();
    load();
  }));

  $("status-filter").addEventListener("change", (e) => { state.status = e.target.value; load(); });
  $("refresh").addEventListener("click", load);

  // -------------------------------------------------------------------- data
  async function load() {
    $("list-body").innerHTML = "";
    $("list-empty").hidden = true;
    $("list-meta").textContent = "Loading…";
    try {
      const path = state.tab === "applications"
        ? `/admin/vendor-applications?status=${encodeURIComponent(state.status)}&limit=100`
        : "/admin/restaurants/pending?limit=100";
      const res = await api("GET", path);
      state.rows = res.data;
      renderList();
      const m = res.meta || {};
      $("list-meta").textContent = m.total != null ? `${m.total} total` : "";
    } catch (err) {
      $("list-meta").textContent = "";
      flash(err.message, true);
    }
  }

  function renderList() {
    const isApps = state.tab === "applications";
    $("list-thead").innerHTML = isApps
      ? "<tr><th>Ref</th><th>Business</th><th>Owner</th><th>Submitted</th><th>Status</th></tr>"
      : "<tr><th>Restaurant</th><th>Address</th><th>Cuisines</th><th>Status</th></tr>";
    const body = $("list-body");
    body.innerHTML = "";
    $("list-empty").hidden = state.rows.length > 0;
    for (const r of state.rows) {
      const tr = document.createElement("tr");
      tr.className = state.selected && state.selected.id === r.id ? "selected" : "";
      tr.innerHTML = isApps
        ? `<td>${esc(r.application_no)}</td><td>${esc(r.business_name)}<br><span class="muted">${esc(r.business_type)} · ${esc(r.area || r.address_line)}</span></td>
           <td>${esc(r.owner_full_name)}<br><span class="muted">${esc(r.owner_email)}</span></td>
           <td>${fmtDate(r.created_at)}</td><td><span class="pill ${esc(r.status)}">${esc(r.status)}</span></td>`
        : `<td>${esc(r.name)}</td><td>${esc(r.address_line || "")}</td><td>${esc((r.cuisine_types || []).join(", "))}</td>
           <td><span class="pill">${r.is_verified ? "VERIFIED" : "UNVERIFIED"}</span></td>`;
      tr.addEventListener("click", () => { state.selected = r; renderList(); renderDetail(); });
      body.appendChild(tr);
    }
  }

  function fmtDate(iso) {
    if (!iso) return "";
    const d = new Date(iso);
    return isNaN(d) ? esc(iso) : d.toLocaleString();
  }

  function row(label, value) {
    return `<dt>${esc(label)}</dt><dd>${value === "" || value == null ? '<span class="muted">—</span>' : value}</dd>`;
  }

  function link(v) {
    if (!v) return "";
    return /^https?:\/\//i.test(v)
      ? `<a href="${esc(v)}" target="_blank" rel="noopener">${esc(v)}</a>`
      : esc(v);
  }

  function renderDetail() {
    const el = $("detail");
    const r = state.selected;
    if (!r) { el.innerHTML = '<p class="muted">Select a row to review it.</p>'; return; }

    if (state.tab === "restaurants") {
      el.innerHTML = `
        <h2>${esc(r.name)}</h2>
        <dl>
          ${row("Status", esc(r.status))}
          ${row("Verified", r.is_verified ? "Yes" : "No")}
          ${row("Address", esc(r.address_line))}
          ${row("Location", `${r.latitude}, ${r.longitude}`)}
          ${row("Cuisines", esc((r.cuisine_types || []).join(", ")))}
          ${row("Slug", esc(r.slug))}
          ${row("ID", esc(r.id))}
        </dl>
        <div class="actions">
          <button id="act-approve" class="ok">Approve restaurant</button>
        </div>`;
      $("act-approve").addEventListener("click", () => decide(
        `/admin/restaurants/${r.id}/verify`, { is_verified: true }, "approve"));
      return;
    }

    const decided = r.status !== "PENDING";
    const docs = Object.entries(r.documents || {}).map(([k, v]) => row(k.replace(/_/g, " "), link(v))).join("");
    const payout = Object.entries(r.payout || {}).map(([k, v]) => row(k.replace(/_/g, " "), esc(v))).join("");
    el.innerHTML = `
      <h2>${esc(r.business_name)} <span class="pill ${esc(r.status)}">${esc(r.status)}</span></h2>
      <p class="muted">${esc(r.application_no)} · submitted ${fmtDate(r.created_at)}</p>

      <h3>Business</h3>
      <dl>
        ${row("Type", esc(r.business_type))}
        ${row("Category", esc(r.business_category))}
        ${row("Branches", esc(r.branch_count))}
        ${row("Cuisines", esc((r.cuisine_types || []).join(", ")))}
        ${row("Address", esc(r.address_line))}
        ${row("Area", esc(r.area))}
        ${row("Location", `<a href="https://www.openstreetmap.org/?mlat=${r.latitude}&mlon=${r.longitude}#map=17/${r.latitude}/${r.longitude}" target="_blank" rel="noopener">${r.latitude}, ${r.longitude}</a>`)}
      </dl>

      <h3>Owner</h3>
      <dl>
        ${row("Name", esc(r.owner_full_name))}
        ${row("Email", esc(r.owner_email))}
        ${row("Phone", esc(r.owner_phone))}
        ${row("National ID", esc(r.national_id))}
      </dl>

      <h3>Documents</h3>
      <dl>${docs || row("Documents", "")}</dl>

      <h3>Payout</h3>
      <dl>${payout || row("Payout", "")}</dl>

      ${decided ? `
        <h3>Decision</h3>
        <dl>
          ${row("Reviewed", fmtDate(r.reviewed_at))}
          ${row("Note", esc(r.review_note))}
        </dl>` : `
        <h3>Decision</h3>
        <label>Note <span class="muted">(emailed to the applicant on rejection)</span>
          <textarea id="decision-note" maxlength="1000"></textarea></label>
        <div class="actions">
          <button id="act-approve" class="ok">Approve</button>
          <button id="act-reject" class="bad">Reject</button>
        </div>`}`;

    if (!decided) {
      $("act-approve").addEventListener("click", () => decide(
        `/admin/vendor-applications/${r.id}/approve`, { note: noteOrNull() }, "approve"));
      $("act-reject").addEventListener("click", () => {
        if (!noteOrNull()) { flash("Write a note: the applicant is emailed the reason.", true); $("decision-note").focus(); return; }
        if (!confirm(`Reject ${r.application_no}? This cannot be undone.`)) return;
        decide(`/admin/vendor-applications/${r.id}/reject`, { note: noteOrNull() }, "reject");
      });
    }
  }

  function noteOrNull() {
    const el = $("decision-note");
    const v = el ? el.value.trim() : "";
    return v || null;
  }

  async function decide(path, body, verb) {
    const buttons = document.querySelectorAll(".actions button");
    buttons.forEach((b) => { b.disabled = true; });
    try {
      const res = await api("POST", path, body);
      flash(res.data.message || `Done: ${verb}`);
      state.selected = null;
      renderDetail();
      await load();
    } catch (err) {
      flash(err.message, true);
      buttons.forEach((b) => { b.disabled = false; });
    }
  }

  // ------------------------------------------------------------------- boot
  if (sessionStorage.getItem(TOKEN_KEY)) { show("app"); load(); } else { show("login"); }
})();
