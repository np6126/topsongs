"use strict";
/* topsongs dashboard — vanilla JS, no framework, no build step. */

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
const el = (tag, cls, html) => { const e = document.createElement(tag); if (cls) e.className = cls; if (html != null) e.innerHTML = html; return e; };
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

let TOKEN = localStorage.getItem("topsongs_token") || "";

// ---------- fetch helpers ----------
async function api(path, opts = {}) {
  const headers = { "Content-Type": "application/json", ...(opts.headers || {}) };
  if (TOKEN) headers["Authorization"] = "Bearer " + TOKEN;
  const res = await fetch(path, { ...opts, headers });
  if (res.status === 401) { showGate(); throw new Error("unauthorized"); }
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail || detail; } catch (_) {}
    throw new Error(detail);
  }
  return res.status === 204 ? null : res.json();
}
const get = (p) => api(p);
const post = (p, body) => api(p, { method: "POST", body: JSON.stringify(body || {}) });

// ---------- toast / modal ----------
function toast(msg, kind = "info") {
  const t = el("div", "toast " + kind, esc(msg));
  $("#toasts").appendChild(t);
  setTimeout(() => { t.style.opacity = "0"; t.style.transform = "translateX(40px)"; setTimeout(() => t.remove(), 300); }, 4200);
}
function confirmModal(title, text) {
  return new Promise((resolve) => {
    $("#modal-title").textContent = title;
    $("#modal-text").textContent = text;
    $("#modal").classList.remove("hidden");
    const cleanup = (val) => { $("#modal").classList.add("hidden"); $("#modal-ok").onclick = null; $("#modal-cancel").onclick = null; resolve(val); };
    $("#modal-ok").onclick = () => cleanup(true);
    $("#modal-cancel").onclick = () => cleanup(false);
  });
}

// ---------- token gate ----------
function showGate() { $("#token-gate").classList.remove("hidden"); $("#token-input").focus(); }
$("#token-submit").onclick = () => {
  TOKEN = $("#token-input").value.trim();
  localStorage.setItem("topsongs_token", TOKEN);
  $("#token-gate").classList.add("hidden");
  boot();
};
$("#token-input").addEventListener("keydown", (e) => { if (e.key === "Enter") $("#token-submit").click(); });

// ---------- navigation ----------
const loaders = {};
function show(view) {
  $$(".nav-item").forEach((b) => b.classList.toggle("active", b.dataset.view === view));
  $$(".view").forEach((v) => v.classList.toggle("active", v.id === "view-" + view));
  if (loaders[view]) loaders[view]();
  location.hash = view;
}
$$(".nav-item").forEach((b) => (b.onclick = () => show(b.dataset.view)));

// ---------- relative time ----------
function relTime(iso) {
  if (!iso) return "";
  const d = new Date(iso.replace(" ", "T"));
  const s = Math.round((Date.now() - d.getTime()) / 1000);
  if (s < 60) return "vor " + s + "s";
  if (s < 3600) return "vor " + Math.round(s / 60) + " min";
  if (s < 86400) return "vor " + Math.round(s / 3600) + " h";
  return "vor " + Math.round(s / 86400) + " Tagen";
}
function fmtDuration(sec) {
  if (sec == null) return "—";
  if (sec < 60) return sec + "s";
  if (sec < 3600) return Math.floor(sec / 60) + "min " + (sec % 60) + "s";
  const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60);
  return h + "h " + m + "min";
}
function fmtClock(iso) {
  if (!iso) return "—";
  const d = new Date(iso.replace(" ", "T"));
  return d.toLocaleString("de-DE", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
}

// ============================================================ DASHBOARD
const STAT_DEFS = [
  ["targeted_user_count", "Benutzer", "violet", "M16 11c1.66 0 3-1.34 3-3s-1.34-3-3-3-3 1.34-3 3 1.34 3 3 3zm-8 0c1.66 0 3-1.34 3-3S9.66 5 8 5 5 6.34 5 8s1.34 3 3 3zm0 2c-2.33 0-7 1.17-7 3.5V19h14v-2.5c0-2.33-4.67-3.5-7-3.5z"],
  ["eligible_artist_count", "Künstler", "cyan", "M12 3v10.55A4 4 0 1014 17V7h4V3h-6z"],
  ["created_playlist_count", "Erstellt", "green", "M19 13h-6v6h-2v-6H5v-2h6V5h2v6h6v2z"],
  ["replaced_playlist_count", "Ersetzt", "yellow", "M17.65 6.35A8 8 0 1019.74 14h-2.08A6 6 0 1112 6c1.66 0 3.14.69 4.22 1.78L13 11h7V4z"],
  ["orphan_deleted_count", "Gelöscht", "magenta", "M6 19a2 2 0 002 2h8a2 2 0 002-2V7H6v12z"],
  ["unmatched_local_track_count", "Ungematcht", "violet", "M15.5 14h-.79l-.28-.27a6.5 6.5 0 10-.7.7l.27.28v.79l5 4.99L20.49 19z"],
  ["failed_artist_count", "Fehler", "red", "M12 2L1 21h22L12 2zm1 16h-2v-2h2v2zm0-4h-2v-4h2v4z"],
];
// label + colour per stat key, shared by the dashboard grid and the run summary
const STAT_META = Object.fromEntries(STAT_DEFS.map(([key, label, color]) => [key, { label, color }]));
// the run summary shows every stat except the user count
const SUMMARY_KEYS = ["created_playlist_count", "replaced_playlist_count", "orphan_deleted_count",
  "eligible_artist_count", "unmatched_local_track_count", "failed_artist_count"];

async function loadDashboard() {
  let s;
  try { s = await get("/api/status"); } catch (e) { return; }
  updateHealth(s.jellyfin);

  const alert = $("#dash-alert");
  if (!s.configured) {
    alert.className = "alert bad"; alert.textContent = "Nicht konfiguriert: " + (s.error || "JELLYFIN_URL fehlt"); alert.classList.remove("hidden");
    return;
  }
  if (s.lock && s.lock.stale) {
    alert.className = "alert warn"; alert.innerHTML = "⚠ Veralteter Run-Lock (PID " + esc(s.lock.pid) + ", " + fmtDuration(s.lock.age_seconds) + " alt). Der nächste Run räumt ihn ab."; alert.classList.remove("hidden");
  } else { alert.classList.add("hidden"); }

  const lr = s.last_run;
  const running = s.run && s.run.running;
  $("#hero-time").textContent = lr ? fmtClock(lr.finished_at) : "noch nie";
  $("#hero-rel").textContent = lr ? relTime(lr.finished_at) + " · Provider: " + (lr.provider || "—") : "Es gab noch keinen Run.";

  const badge = $("#hero-badge");
  if (running) badge.innerHTML = '<span class="badge idle"><span class="spinner"></span> läuft gerade</span>';
  else if (!lr) badge.innerHTML = '<span class="badge idle"><span class="dot"></span> idle</span>';
  else if (lr.failed_user_count || lr.failed_artist_count) badge.innerHTML = '<span class="badge fail"><span class="dot"></span> mit Fehlern</span>';
  else badge.innerHTML = '<span class="badge ok"><span class="dot"></span> erfolgreich</span>';

  const grid = $("#stat-grid"); grid.innerHTML = "";
  for (const [key, label, color, icon] of STAT_DEFS) {
    const val = lr ? (lr[key] ?? 0) : 0;
    const c = el("div", "stat glass c-" + color);
    c.innerHTML = `<svg class="stat-ic" viewBox="0 0 24 24"><path d="${icon}"/></svg>
      <div class="stat-num">${val}</div><div class="stat-lbl">${label}</div>`;
    grid.appendChild(c);
  }

  // next run
  if (s.next_run) {
    $("#next-run").textContent = fmtClock(s.next_run.at);
    $("#cron-line").textContent = "in " + fmtDuration(s.next_run.seconds_until) + " · " + s.cron_schedule;
  } else { $("#next-run").textContent = s.cron_schedule || "—"; $("#cron-line").textContent = "Cron-Ausdruck"; }

  // lock
  if (s.lock && s.lock.active) {
    $("#lock-state").innerHTML = s.lock.stale ? '<span class="c-bad">veraltet</span>' : '<span class="c-yellow">aktiv</span>';
    $("#lock-line").textContent = "PID " + (s.lock.pid ?? "?") + " · " + fmtDuration(s.lock.age_seconds);
  } else { $("#lock-state").innerHTML = '<span class="c-good">frei</span>'; $("#lock-line").textContent = "kein laufender Run"; }

  // mode
  $("#mode-state").textContent = s.tag_managed ? "Tag-Mode" : "Prefix-Mode";
  $("#mode-line").textContent = s.tag_managed ? "Tag: " + s.managed_tag : "Prefix: " + (s.prefix || "—");
}
loaders.dashboard = loadDashboard;

function updateHealth(j) {
  const box = $("#jelly-dot");
  if (j && j.reachable) { box.className = "health ok"; $("#jelly-text").textContent = "Jellyfin · " + j.user_count + " User"; }
  else { box.className = "health bad"; $("#jelly-text").textContent = "Jellyfin offline"; }
}

$("#refresh-status").onclick = () => { loadDashboard(); toast("Status aktualisiert", "info"); };
$("#dash-run").onclick = () => { show("run"); startRun(); };

// ============================================================ RUN
let runES = null;
const logBox = () => $("#run-log");
function appendLog(line) {
  const box = logBox();
  const div = el("div", "log-line");
  let cls = "";
  if (/error|failed|fehlgeschlagen|run_failed/i.test(line)) cls = "err";
  else if (/warn|skip|stale/i.test(line)) cls = "warn";
  else if (/event=summary|finish|created|event=apply/i.test(line)) cls = "ok";
  div.className = "log-line " + cls;
  div.innerHTML = esc(line).replace(/(event=\w+)/g, '<span class="ev">$1</span>');
  box.appendChild(div);
  box.scrollTop = box.scrollHeight;
}
function setRunBusy(busy) {
  $("#run-spinner").classList.toggle("hidden", !busy);
  $("#run-start").disabled = busy;
  $("#dash-run").disabled = busy;
  $("#run-state-label").textContent = busy ? "läuft…" : "fertig";
}
async function startRun() {
  const dry = $("#run-dry").checked;
  logBox().innerHTML = "";
  $("#run-summary").classList.add("hidden");
  try {
    await post("/api/run", { dry_run: dry });
  } catch (e) {
    if (e.message.includes("already") || e.message.includes("läuft")) { toast("Läuft bereits — hänge mich an den Stream.", "info"); }
    else { toast("Run-Start fehlgeschlagen: " + e.message, "err"); return; }
  }
  setRunBusy(true);
  toast(dry ? "Dry-Run gestartet" : "Run gestartet", "info");
  streamRun();
}
function streamRun() {
  if (runES) runES.close();
  const url = "/api/run/stream" + (TOKEN ? "?token=" + encodeURIComponent(TOKEN) : "");
  runES = new EventSource(url);
  runES.onmessage = (ev) => { try { appendLog(JSON.parse(ev.data).line); } catch (_) {} };
  runES.addEventListener("done", (ev) => {
    runES.close(); runES = null; setRunBusy(false);
    let data = {}; try { data = JSON.parse(ev.data); } catch (_) {}
    renderRunSummary(data.summary);
    if (data.return_code === 0) toast("Run abgeschlossen ✓", "ok");
    else toast("Run beendet (code " + data.return_code + ")", "err");
    loadDashboard();
  });
  runES.onerror = () => { if (runES) { runES.close(); runES = null; } setRunBusy(false); };
}
function renderRunSummary(sum) {
  if (!sum) return;
  const box = $("#run-summary"); box.innerHTML = ""; box.classList.remove("hidden");
  for (const key of SUMMARY_KEYS) {
    const { label, color } = STAT_META[key];
    const c = el("div", "stat glass c-" + color);
    c.innerHTML = `<div class="stat-num">${sum[key] ?? 0}</div><div class="stat-lbl">${label}</div>`;
    box.appendChild(c);
  }
}
$("#run-start").onclick = startRun;
// re-attach to an in-progress run when opening the Run view
loaders.run = async () => {
  try { const s = await get("/api/run"); if (s.running && !runES) { setRunBusy(true); streamRun(); } } catch (_) {}
};

// ============================================================ MISSING
function covClass(c) { return c >= 1 ? "good" : c >= 0.5 ? "mid" : "bad"; }

// Artist autocomplete: the backend caches every artist it has seen on disk.
let artistOptions = null;
async function loadArtistOptions() {
  if (artistOptions) return;
  try {
    const data = await get("/api/artists");
    artistOptions = data.artists || [];
    const dl = $("#artist-options"); dl.innerHTML = "";
    for (const name of artistOptions) { const o = el("option"); o.value = name; dl.appendChild(o); }
  } catch (_) { artistOptions = null; }
}
loaders.missing = loadArtistOptions;
async function runMissing() {
  const body = $("#miss-body");
  body.innerHTML = '<div class="loader"><span class="spinner"></span> Frage Last.fm ab… (kann dauern)</div>';
  const payload = {
    artist: $("#miss-artist").value.trim() || null,
    user: $("#miss-user").value.trim() || null,
    all_types: $("#miss-alltypes").checked,
    no_cache: $("#miss-nocache").checked,
  };
  let data;
  try { data = await post("/api/missing", payload); } catch (e) { body.innerHTML = `<div class="empty err">${esc(e.message)}</div>`; return; }
  body.innerHTML = "";
  const hdr = el("p", "muted", `Benutzer: <b>${esc(data.user)}</b> · ${data.gaps.length} Künstler geprüft`);
  body.appendChild(hdr);
  if (data.total) body.appendChild(gapCard(data.total, "Gesamt", true));
  for (const g of data.gaps) body.appendChild(gapCard(g, null, false));
}
function gapCard(g, titleOverride, grand) {
  const card = el("div", "gap-card" + (grand ? " grand" : ""));
  if (g.error) { card.innerHTML = `<div class="gap-head"><span class="nm c-bad">✗ ${esc(g.artist_name)}</span></div><div class="gap-meta">${esc(g.error)}</div>`; return card; }
  const cov = g.coverage ?? 1, pct = Math.round(cov * 100), cc = covClass(cov);
  const name = titleOverride || g.artist_name || (g.artist_count ? g.artist_count + " Künstler" : "—");
  const meta = grand
    ? `${g.complete_album_count}/${g.album_count} Alben komplett · ${g.owned_tracks}/${g.total_tracks} Tracks`
    : `${g.complete_album_count}/${g.album_count} Alben · ${g.owned_tracks}/${g.total_tracks} Tracks`;
  card.innerHTML = `<div class="gap-head"><span class="nm">${esc(name)}</span><span class="gap-pct c-${cc}">${pct}%</span></div>
    <div class="gap-meta">${meta}</div>`;
  for (const a of g.albums || []) card.appendChild(albumRow(a));
  return card;
}
function albumRow(a) {
  const cc = covClass(a.coverage), pct = Math.round(a.coverage * 100);
  const row = el("div", "album");
  row.innerHTML = `
    <div class="a-title ${a.is_complete ? "c-good" : ""}">${esc(a.title)} ${a.year ? `<span class="yr">(${a.year})</span>` : ""}</div>
    <div class="a-frac c-${cc}">${a.owned_count}/${a.total_tracks}</div>
    <div class="bar"><span class="bg-${cc}" style="width:${pct}%"></span></div>`;
  if (a.missing_titles && a.missing_titles.length) {
    const ml = el("div", "miss-list");
    for (const t of a.missing_titles) ml.appendChild(el("div", "x", "✗ " + esc(t)));
    row.appendChild(ml);
  }
  return row;
}
$("#miss-go").onclick = runMissing;
$("#miss-artist").addEventListener("keydown", (e) => { if (e.key === "Enter") runMissing(); });

// ============================================================ PURGE
async function purgePreview() {
  const body = $("#purge-body");
  body.innerHTML = '<div class="loader"><span class="spinner"></span> Suche Playlists…</div>';
  let data;
  try { data = await post("/api/purge/preview", { prefix: $("#purge-prefix").value.trim() || null }); }
  catch (e) { body.innerHTML = `<div class="empty err">${esc(e.message)}</div>`; $("#purge-exec").disabled = true; return; }
  $("#purge-prefix").dataset.effective = data.prefix;
  const n = data.playlists.length;
  $("#purge-exec").disabled = n === 0;
  const block = el("div", "result-block glass");
  block.innerHTML = `<h4>Vorschau · Prefix „${esc(data.prefix)}“ · ${data.user_count} Benutzer</h4>`;
  if (!n) { block.innerHTML += '<div class="muted">Keine passenden Playlists.</div>'; body.innerHTML = ""; body.appendChild(block); return; }
  const list = el("div", "row-list");
  for (const p of data.playlists) list.appendChild(el("div", "row-item", `<span>${esc(p.name)}</span><span class="users">${esc((p.users || []).join(", "))}</span>`));
  block.appendChild(el("div", "muted", `<span class="tag-del">${n} Playlists</span> würden gelöscht.`));
  block.appendChild(list);
  body.innerHTML = ""; body.appendChild(block);
}
async function purgeExec() {
  const eff = $("#purge-prefix").dataset.effective || $("#purge-prefix").value.trim();
  if (!(await confirmModal("Playlists löschen?", `Alle Playlists mit Prefix „${eff}“ werden unwiderruflich gelöscht.`))) return;
  try {
    const r = await post("/api/purge", { prefix: $("#purge-prefix").value.trim() || null });
    toast(`${r.deleted} gelöscht, ${r.failed} Fehler`, r.failed ? "err" : "ok");
    $("#purge-exec").disabled = true; purgePreview();
  } catch (e) { toast(e.message, "err"); }
}
$("#purge-preview").onclick = purgePreview;
$("#purge-exec").onclick = purgeExec;

// ============================================================ PRUNE
async function prunePreview() {
  const body = $("#prune-body");
  const keep = $("#prune-keep").value.split(",").map((s) => s.trim()).filter(Boolean);
  if (!keep.length) { toast("Keep-Liste ist leer.", "err"); return; }
  body.innerHTML = '<div class="loader"><span class="spinner"></span> Lade Playlists…</div>';
  let data;
  try { data = await post("/api/prune/preview", { keep, rename_prefix: $("#prune-rename").value }); }
  catch (e) { body.innerHTML = `<div class="empty err">${esc(e.message)}</div>`; $("#prune-exec").disabled = true; return; }
  $("#prune-exec").disabled = data.delete.length === 0 && data.keep.every((k) => !k.will_rename);
  body.innerHTML = "";

  const keepB = el("div", "result-block glass");
  keepB.innerHTML = `<h4><span class="tag-keep">Behalten</span> (${data.keep.length})</h4>`;
  const kl = el("div", "row-list");
  for (const k of data.keep) kl.appendChild(el("div", "row-item", `<span>${esc(k.name)}</span>${k.will_rename ? `<span class="arrow">→ ${esc(k.target)}</span>` : '<span class="users">ok</span>'}`));
  keepB.appendChild(kl); body.appendChild(keepB);

  const delB = el("div", "result-block glass");
  delB.innerHTML = `<h4><span class="tag-del">Löschen</span> (${data.delete.length})</h4>`;
  if (data.delete.length) {
    const dl = el("div", "row-list");
    for (const d of data.delete) dl.appendChild(el("div", "row-item", `<span>${esc(d.name)}</span><span class="users">${esc((d.users || []).join(", "))}</span>`));
    delB.appendChild(dl);
  } else { delB.appendChild(el("div", "muted", "Nichts zu löschen.")); }
  body.appendChild(delB);

  if (data.unmatched && data.unmatched.length) body.appendChild(el("div", "alert warn", "Kein Treffer für: " + esc(data.unmatched.join(", "))));
}
async function pruneExec() {
  const keep = $("#prune-keep").value.split(",").map((s) => s.trim()).filter(Boolean);
  if (!(await confirmModal("Prune ausführen?", "Alle Playlists außer der Keep-Liste werden gelöscht. Behaltene werden ggf. umbenannt."))) return;
  try {
    const r = await post("/api/prune", { keep, rename_prefix: $("#prune-rename").value });
    toast(`${r.deleted} gelöscht, ${r.renamed} umbenannt, ${r.kept} behalten`, (r.delete_failed || r.rename_failed) ? "err" : "ok");
    $("#prune-exec").disabled = true; prunePreview();
  } catch (e) { toast(e.message, "err"); }
}
$("#prune-preview").onclick = prunePreview;
$("#prune-exec").onclick = pruneExec;

// ============================================================ CONFIG
async function loadConfig() {
  const body = $("#config-body");
  body.innerHTML = '<div class="loader"><span class="spinner"></span> Lade…</div>';
  let data;
  try { data = await get("/api/config"); } catch (e) { body.innerHTML = `<div class="empty err">${esc(e.message)}</div>`; return; }
  body.innerHTML = "";
  for (const f of data.fields) {
    const row = el("div", "cfg-row");
    row.innerHTML = `<div class="k">${esc(f.key)}</div><div class="v ${f.secret ? "secret" : ""}">${esc(f.value)}</div>`;
    body.appendChild(row);
  }
}
loaders.config = loadConfig;
$("#config-reload").onclick = loadConfig;

// ============================================================ BOOT
async function boot() {
  await loadDashboard();
  const initial = (location.hash || "#dashboard").slice(1);
  if ($("#view-" + initial)) show(initial);
  // light auto-refresh of the dashboard health while it is open
  setInterval(() => { if ($("#view-dashboard").classList.contains("active")) loadDashboard(); }, 20000);
}
async function init() {
  try {
    const a = await get("/api/auth");
    if (a.token_required && !TOKEN) { showGate(); return; }
  } catch (_) {}
  boot();
}
init();
