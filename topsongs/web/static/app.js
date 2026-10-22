"use strict";
/* topsongs dashboard — vanilla JS, no framework, no build step. */

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
const el = (tag, cls, html) => { const e = document.createElement(tag); if (cls) e.className = cls; if (html != null) e.innerHTML = html; return e; };
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const playlistRow = (p) => el("div", "row-item", `<span>${esc(p.name)}</span><span class="users">${esc((p.users || []).join(", "))}</span>`);

let TOKEN = localStorage.getItem("topsongs_token") || "";

// ---------- language ----------
// The server's TOPSONGS_LANGUAGE picks the language. Texts are written in English;
// de.json holds the German versions, keyed by the English text. Values fill {name}
// placeholders after the lookup; escape them first where the text becomes HTML.
let LANG = "en";
let CATALOG = {};
const translate = (msg) => CATALOG[msg] ?? msg;
function t(msg, values) {
  const template = translate(msg);
  return values ? template.replace(/\{(\w+)\}/g, (m, key) => (key in values ? String(values[key]) : m)) : template;
}
async function useLanguage(lang) {
  LANG = lang === "de" ? "de" : "en";
  document.documentElement.lang = LANG;
  if (LANG === "en") return;
  try { CATALOG = await (await fetch("de.json")).json(); } catch (_) { CATALOG = {}; }
  for (const e of $$("[data-i18n]")) e.innerHTML = translate(e.innerHTML.trim().replace(/\s+/g, " "));
  for (const e of $$("[placeholder]")) e.placeholder = translate(e.placeholder);
  for (const e of $$("[title]")) e.title = translate(e.title);
}

// ---------- fetch helpers ----------
async function api(path, opts = {}) {
  const headers = { "Content-Type": "application/json", ...(opts.headers || {}) };
  if (TOKEN) headers["Authorization"] = "Bearer " + TOKEN;
  const res = await fetch(path, { ...opts, headers });
  if (res.status === 401) { showGate(); throw new Error("unauthorized"); }
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail || detail; } catch (_) {}
    throw Object.assign(new Error(detail), { status: res.status });
  }
  return res.status === 204 ? null : res.json();
}
const get = (p) => api(p);
const post = (p, body) => api(p, { method: "POST", body: JSON.stringify(body || {}) });

// ---------- toast / modal ----------
function toast(msg, kind = "info") {
  const box = el("div", "toast " + kind, esc(msg));
  $("#toasts").appendChild(box);
  setTimeout(() => { box.style.opacity = "0"; box.style.transform = "translateX(40px)"; setTimeout(() => box.remove(), 300); }, 4200);
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
  if (s < 60) return t("{n} s ago", { n: s });
  if (s < 3600) return t("{n} min ago", { n: Math.round(s / 60) });
  if (s < 86400) return t("{n} h ago", { n: Math.round(s / 3600) });
  return t("{n} days ago", { n: Math.round(s / 86400) });
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
  return d.toLocaleString(LANG === "de" ? "de-DE" : "en-GB", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
}
// de: 12.10.2026, en: 2026-10-12 (as the CLI prints them)
const fmtDate = (iso) => !iso ? "—" : LANG === "de" ? iso.split("-").reverse().join(".") : iso;

// ============================================================ DASHBOARD
// [key, label, colour, icon]; a function, so the labels follow the loaded language
const statDefs = () => [
  ["targeted_user_count", t("Users"), "violet", "M16 11c1.66 0 3-1.34 3-3s-1.34-3-3-3-3 1.34-3 3 1.34 3 3 3zm-8 0c1.66 0 3-1.34 3-3S9.66 5 8 5 5 6.34 5 8s1.34 3 3 3zm0 2c-2.33 0-7 1.17-7 3.5V19h14v-2.5c0-2.33-4.67-3.5-7-3.5z"],
  ["eligible_artist_count", t("Artists"), "cyan", "M12 3v10.55A4 4 0 1014 17V7h4V3h-6z"],
  ["created_playlist_count", t("Created"), "green", "M19 13h-6v6h-2v-6H5v-2h6V5h2v6h6v2z"],
  ["replaced_playlist_count", t("Replaced"), "yellow", "M17.65 6.35A8 8 0 1019.74 14h-2.08A6 6 0 1112 6c1.66 0 3.14.69 4.22 1.78L13 11h7V4z"],
  ["orphan_deleted_count", t("Deleted"), "magenta", "M6 19a2 2 0 002 2h8a2 2 0 002-2V7H6v12z"],
  ["unmatched_local_track_count", t("Unmatched"), "violet", "M15.5 14h-.79l-.28-.27a6.5 6.5 0 10-.7.7l.27.28v.79l5 4.99L20.49 19z"],
  ["failed_artist_count", t("Errors"), "red", "M12 2L1 21h22L12 2zm1 16h-2v-2h2v2zm0-4h-2v-4h2v4z"],
];
// the run summary shows every stat except the user count
const SUMMARY_KEYS = ["created_playlist_count", "replaced_playlist_count", "orphan_deleted_count",
  "eligible_artist_count", "unmatched_local_track_count", "failed_artist_count"];

async function loadDashboard() {
  let s;
  try { s = await get("/api/status"); } catch (e) { return; }
  updateHealth(s.jellyfin);

  const alert = $("#dash-alert");
  if (!s.configured) {
    alert.className = "alert bad"; alert.textContent = t("Not configured: {error}", { error: s.error || t("JELLYFIN_URL is missing") }); alert.classList.remove("hidden");
    return;
  }
  if (s.lock && s.lock.stale) {
    alert.className = "alert warn"; alert.innerHTML = "⚠ " + t("Stale run lock (PID {pid}, {age} old). The next run clears it.", { pid: esc(s.lock.pid), age: fmtDuration(s.lock.age_seconds) }); alert.classList.remove("hidden");
  } else { alert.classList.add("hidden"); }

  const lr = s.last_run;
  const running = s.run && s.run.running;
  $("#hero-time").textContent = lr ? fmtClock(lr.finished_at) : t("never");
  $("#hero-rel").textContent = lr ? relTime(lr.finished_at) + " · Provider: " + (lr.provider || "—") : t("There has been no run yet.");

  const badge = $("#hero-badge");
  if (running) badge.innerHTML = `<span class="badge idle"><span class="spinner"></span> ${t("running")}</span>`;
  else if (!lr) badge.innerHTML = '<span class="badge idle"><span class="dot"></span> idle</span>';
  else if (lr.failed_user_count || lr.failed_artist_count) badge.innerHTML = `<span class="badge fail"><span class="dot"></span> ${t("with errors")}</span>`;
  else badge.innerHTML = `<span class="badge ok"><span class="dot"></span> ${t("successful")}</span>`;

  const grid = $("#stat-grid"); grid.innerHTML = "";
  for (const [key, label, color, icon] of statDefs()) {
    const val = lr ? (lr[key] ?? 0) : 0;
    const c = el("div", "stat glass c-" + color);
    c.innerHTML = `<svg class="stat-ic" viewBox="0 0 24 24"><path d="${icon}"/></svg>
      <div class="stat-num">${val}</div><div class="stat-lbl">${label}</div>`;
    grid.appendChild(c);
  }

  // next run
  if (s.next_run) {
    $("#next-run").textContent = fmtClock(s.next_run.at);
    $("#cron-line").textContent = t("in {duration}", { duration: fmtDuration(s.next_run.seconds_until) }) + " · " + s.cron_schedule;
  } else { $("#next-run").textContent = s.cron_schedule || "—"; $("#cron-line").textContent = t("cron expression"); }

  // lock
  if (s.lock && s.lock.active) {
    $("#lock-state").innerHTML = s.lock.stale ? `<span class="c-bad">${t("stale")}</span>` : `<span class="c-yellow">${t("active")}</span>`;
    $("#lock-line").textContent = "PID " + (s.lock.pid ?? "?") + " · " + fmtDuration(s.lock.age_seconds);
  } else { $("#lock-state").innerHTML = `<span class="c-good">${t("free")}</span>`; $("#lock-line").textContent = t("no run in progress"); }

  $("#nav-live").classList.toggle("hidden", !s.live_enabled);
  $("#live-off").classList.toggle("hidden", !!s.live_enabled);

  // playlists: marked by their tag; the prefix only shapes the names
  $("#mode-state").textContent = "Tag: " + s.managed_tag;
  $("#mode-line").textContent = s.prefix ? t("Name prefix: {prefix}", { prefix: s.prefix }) : t("no name prefix");
}
loaders.dashboard = loadDashboard;

function updateHealth(j) {
  const box = $("#jelly-dot");
  if (j && j.reachable) { box.className = "health ok"; $("#jelly-text").textContent = t("Jellyfin · {count} users", { count: j.user_count }); }
  else { box.className = "health bad"; $("#jelly-text").textContent = "Jellyfin offline"; }
}

$("#refresh-status").onclick = () => { loadDashboard(); toast(t("Status refreshed"), "info"); };
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
  $("#run-state-label").textContent = busy ? t("running…") : t("done");
}
async function startRun() {
  const dry = $("#run-dry").checked;
  logBox().innerHTML = "";
  $("#run-summary").classList.add("hidden");
  try {
    await post("/api/run", { dry_run: dry });
  } catch (e) {
    if (e.status === 409) { toast(t("Already running — attaching to the stream."), "info"); }
    else { toast(t("Could not start the run: {error}", { error: e.message }), "err"); return; }
  }
  setRunBusy(true);
  toast(dry ? t("Dry run started") : t("Run started"), "info");
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
    if (data.return_code === 0) toast(t("Run finished ✓"), "ok");
    else toast(t("Run ended (code {code})", { code: data.return_code }), "err");
    loadDashboard();
  });
  runES.onerror = () => { if (runES) { runES.close(); runES = null; } setRunBusy(false); };
}
function renderRunSummary(sum) {
  if (!sum) return;
  const meta = Object.fromEntries(statDefs().map(([key, label, color]) => [key, { label, color }]));
  const box = $("#run-summary"); box.innerHTML = ""; box.classList.remove("hidden");
  for (const key of SUMMARY_KEYS) {
    const { label, color } = meta[key];
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

function fillDatalist(dl, values) {
  dl.innerHTML = "";
  for (const v of values) { const o = el("option"); o.value = v; dl.appendChild(o); }
}

// Artist autocomplete: the backend caches the library's artists on disk.
let artistOptions = null;
async function loadArtistOptions() {
  if (artistOptions) return;
  try {
    const data = await get("/api/artists");
    artistOptions = data.artists || [];
    fillDatalist($("#artist-options"), artistOptions);
  } catch (_) { artistOptions = null; }
}
loaders.missing = loadArtistOptions;
// Browsers match datalist options anywhere in the name; offer only names that start
// with what was typed (ignoring case and accents), so "dar" finds Dark Funeral, not Suidakra.
const fold = (s) => s.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
function suggestArtists(input) {
  const typed = fold(input.value.trim());
  fillDatalist($("#artist-options"), (artistOptions || []).filter((name) => fold(name).startsWith(typed)));
}
for (const id of ["#miss-artist", "#live-artist"]) {
  for (const type of ["input", "focus"]) $(id).addEventListener(type, (e) => suggestArtists(e.target));
}

async function runMissing() {
  const body = $("#miss-body");
  body.innerHTML = `<div class="loader"><span class="spinner"></span> ${t("Asking Last.fm… (may take a while)")}</div>`;
  const payload = {
    artist: $("#miss-artist").value.trim() || null,
    user: $("#miss-user").value.trim() || null,
    all_types: $("#miss-alltypes").checked,
    no_cache: $("#miss-nocache").checked,
  };
  let data;
  try { data = await post("/api/missing", payload); } catch (e) { body.innerHTML = `<div class="empty err">${esc(e.message)}</div>`; return; }
  body.innerHTML = "";
  const checked = data.gaps.length === 1
    ? t("User: <b>{user}</b> · 1 artist checked", { user: esc(data.user) })
    : t("User: <b>{user}</b> · {count} artists checked", { user: esc(data.user), count: data.gaps.length });
  const hdr = el("p", "muted", checked);
  body.appendChild(hdr);
  if (data.total) body.appendChild(gapCard(data.total, t("Total"), true));
  for (const g of data.gaps) body.appendChild(gapCard(g, null, false));
}
function gapCard(g, titleOverride, grand) {
  const card = el("div", "gap-card" + (grand ? " grand" : ""));
  if (g.error) { card.innerHTML = `<div class="gap-head"><span class="nm c-bad">✗ ${esc(g.artist_name)}</span></div><div class="gap-meta">${esc(g.error)}</div>`; return card; }
  const cov = g.coverage ?? 1, pct = Math.round(cov * 100), cc = covClass(cov);
  const name = titleOverride || g.artist_name || (g.artist_count ? t("{count} artists", { count: g.artist_count }) : "—");
  const counts = { complete: g.complete_album_count, albums: g.album_count, owned: g.owned_tracks, tracks: g.total_tracks };
  const meta = grand
    ? t("{complete}/{albums} albums complete · {owned}/{tracks} tracks", counts)
    : t("{complete}/{albums} albums · {owned}/{tracks} tracks", counts);
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
    for (const title of a.missing_titles) ml.appendChild(el("div", "x", "✗ " + esc(title)));
    row.appendChild(ml);
  }
  return row;
}
$("#miss-go").onclick = runMissing;
$("#miss-artist").addEventListener("keydown", (e) => { if (e.key === "Enter") runMissing(); });

// ============================================================ LIVE
const shareOptions = () => [[1, t("all (100 %)")], [0.75, "75 %"], [0.66, "2/3"], [0.5, t("half")], [0.33, "1/3"], [0.25, "25 %"], [0, t("any (all songs)")]];
// name: the user's own playlist name, null while the suggested one applies
// query: the last concert request, so a repeated event does not load it again
// allUsers / users: every user / the ones a playlist is for; public: one playlist everyone sees
const live = { artist: null, loads: 0, query: null, concerts: [], selected: new Set(), perVenue: false, minShare: 0.5, name: null, seq: 0, timer: null,
  allUsers: [], users: new Set(), public: false };

const playable = (c) => c.song_count > 0;
// The first chosen user owns a public playlist; the preview matches against their library.
const owner = () => live.allUsers.find((u) => live.users.has(u)) || null;

// The users picked last time, kept in this browser; without them the default user.
const LIVE_USERS_KEY = "topsongs_live_users";
async function loadLiveUsers() {
  if (live.allUsers.length) return;
  try {
    const data = await get("/api/users");
    const saved = JSON.parse(localStorage.getItem(LIVE_USERS_KEY) || "[]").filter((u) => data.users.includes(u));
    live.allUsers = data.users;
    live.users = new Set(saved.length ? saved : data.default ? [data.default] : []);
  } catch (_) {}
}
loaders.live = () => { loadArtistOptions(); loadLiveUsers(); loadLiveExisting(); };

// One input #live-<field> per concert filter field; its suggestions come from the loaded concerts.
const LIVE_FILTERS = ["tour", "year", "venue", "city", "country"];
const filterInput = (field) => $("#live-" + field);
const clearFilters = () => { for (const f of LIVE_FILTERS) filterInput(f).value = ""; };

async function loadConcerts({ mbid = null, force = false } = {}) {
  const artist = $("#live-artist").value.trim();
  if (!artist) { toast(t("Enter an artist."), "err"); return; }
  const params = new URLSearchParams({ artist, user: owner() || "" });
  for (const f of LIVE_FILTERS) { const v = filterInput(f).value.trim(); if (v) params.set(f, v); }
  if (mbid) params.set("mbid", mbid);
  if (!force && params.toString() === live.query) return;
  live.query = params.toString();
  const load = ++live.loads;
  const body = $("#live-body");
  body.innerHTML = `<div class="loader"><span class="spinner"></span> ${t("Asking setlist.fm…")}</div>`;
  let data;
  try { data = await get("/api/live/concerts?" + params); }
  catch (e) { if (load === live.loads) { live.query = null; body.innerHTML = `<div class="empty err">${esc(e.message)}</div>`; } return; }
  if (load !== live.loads) return;  // a newer load is under way
  if (data.needs_choice) { renderArtistChoice(data); return; }
  Object.assign(live, { artist: data.artist, concerts: data.concerts, selected: new Set(), name: null });
  for (const f of LIVE_FILTERS) fillDatalist(filterInput(f).list, data.suggestions[f] || []);
  selectLast(1, false);
  renderLive();
}

function renderArtistChoice(data) {
  const body = $("#live-body"); body.innerHTML = "";
  const block = el("div", "result-block glass", `<h4>${t("Which artist “{artist}”?", { artist: esc(data.artist) })}</h4>`);
  const list = el("div", "row-list");
  for (const c of data.candidates) {
    const row = el("button", "row-item live-pick", `<span>${esc(c.name)}</span><span class="users">${esc(c.disambiguation || c.mbid)}</span>`);
    row.onclick = () => loadConcerts({ mbid: c.mbid, force: true });
    list.appendChild(row);
  }
  block.appendChild(list); body.appendChild(block);
}

function selectLast(n, perVenue) {
  live.selected = new Set();
  const venues = new Set();
  for (const c of live.concerts) {
    if (live.selected.size >= n) break;
    if (!playable(c) || (perVenue && venues.has(c.venue_key))) continue;
    venues.add(c.venue_key); live.selected.add(c.id);
  }
}

function renderLive() {
  const body = $("#live-body"); body.innerHTML = "";
  const block = el("div", "result-block glass");
  block.innerHTML = `<h4>${t("Concerts")} · ${esc(live.artist)} <span class="users">(${t("setlist.fm, newest first")})</span></h4>`;
  if (!live.concerts.length) { block.appendChild(el("div", "muted", t("setlist.fm has no matching concerts."))); body.appendChild(block); return; }

  const quick = el("div", "live-quick");
  const nSel = el("select", "search small");
  for (let i = 1; i <= live.concerts.filter(playable).length; i++) { const o = el("option"); o.value = i; o.textContent = t("Last {count}", { count: i }); nSel.appendChild(o); }
  nSel.value = String(Math.max(1, live.selected.size));
  const venueT = el("label", "toggle", `<input type="checkbox" ${live.perVenue ? "checked" : ""}><span class="slider"></span><span>${t("one concert per venue")}</span>`);
  const apply = el("button", "btn ghost", t("Select"));
  apply.onclick = () => { live.perVenue = venueT.querySelector("input").checked; selectLast(+nSel.value, live.perVenue); live.name = null; renderLive(); };
  quick.append(nSel, venueT, apply);
  block.appendChild(quick);

  const list = el("div", "row-list");
  for (const c of live.concerts) {
    const ok = playable(c);
    const row = el("label", "row-item live-concert" + (ok ? "" : " off"));
    row.innerHTML = `<input type="checkbox" ${ok ? "" : "disabled"} ${live.selected.has(c.id) ? "checked" : ""}>
      <span class="d">${fmtDate(c.date)}</span>
      <span class="v">${esc(c.place)} ${c.country ? `<span class="users">${esc(c.country)}</span>` : ""}</span>
      <span class="tour">${esc(c.tour || "")}</span>
      <span class="n">${ok ? c.song_count + (c.song_count === 1 ? " Song" : " Songs") : t("no setlist yet")}</span>
      ${c.url ? `<a href="${esc(c.url)}" target="_blank" rel="noopener" title="${t("on setlist.fm")}">↗</a>` : "<span></span>"}`;
    row.querySelector("input").onchange = (e) => { e.target.checked ? live.selected.add(c.id) : live.selected.delete(c.id); live.name = null; schedulePreview(); };
    list.appendChild(row);
  }
  block.appendChild(list);
  body.appendChild(block);
  body.appendChild(el("div", "", '<div id="live-preview"></div>'));
  schedulePreview();
}

// quiet keeps the current preview on screen until the new one arrives: a user change
// only moves ✓/✗ marks, and a spinner in between would make the page jump.
function schedulePreview(quiet = false) {
  clearTimeout(live.timer);
  live.timer = setTimeout(() => loadPreview(quiet), 250);
}

async function loadPreview(quiet) {
  const box = $("#live-preview"); if (!box) return;
  const ids = live.concerts.filter((c) => live.selected.has(c.id)).map((c) => c.id);
  if (!ids.length) { box.innerHTML = `<div class="empty">${t("Select at least one concert.")}</div>`; return; }
  const seq = ++live.seq;
  if (!quiet) box.innerHTML = `<div class="loader"><span class="spinner"></span> ${t("Matching against your library…")}</div>`;
  let data;
  try { data = await post("/api/live/preview", { artist: live.artist, user: owner(), setlist_ids: ids, min_share: live.minShare }); }
  catch (e) { if (seq === live.seq) box.innerHTML = `<div class="empty err">${esc(e.message)}</div>`; return; }
  if (seq !== live.seq) return;
  renderPreview(box, data, ids);
}

function songRow(s, i, total) {
  const chips = (s.encore ? `<span class="chip">${t("encore")}</span>` : "") + (s.cover_artist ? `<span class="chip">Cover: ${esc(s.cover_artist)}</span>` : "");
  return el("div", "row-item live-song" + (s.in_library ? "" : " miss"),
    `<span class="pos">${i == null ? "" : i}</span><span class="t">${esc(s.title)} ${chips}</span>
     <span class="cnt">${total > 1 ? s.play_count + "/" + total : ""}</span>
     <span class="st ${s.in_library ? "c-good" : "c-bad"}">${s.in_library ? "✓" : t("✗ missing")}</span>`);
}

function renderPreview(box, data, ids) {
  const belowOpen = !!box.querySelector(".live-below[open]");
  box.innerHTML = "";
  const block = el("div", "result-block glass");
  const n = data.concert_count;
  const concerts = n === 1 ? t("1 concert, original order") : t("{count} concerts, most played first", { count: n });
  const matched = t("{matched} of {total} in the library", { matched: data.matched_count, total: data.songs.length });
  block.innerHTML = `<h4>${t("Preview")} · ${concerts} · ${matched}</h4>`;
  if (n > 1) {
    const row = el("div", "live-quick", `<span>${t("Song must have been played at")}</span>`);
    const sel = el("select", "search small");
    for (const [v, label] of shareOptions()) { const o = el("option"); o.value = v; o.textContent = label; sel.appendChild(o); }
    sel.value = String(live.minShare);
    sel.onchange = () => { live.minShare = +sel.value; schedulePreview(); };
    row.appendChild(sel); row.appendChild(el("span", "", t("of the concerts")));
    block.appendChild(row);
  }
  const list = el("div", "row-list");
  if (!data.songs.length) list.appendChild(el("div", "muted", t("No song reaches the threshold.")));
  data.songs.forEach((s, i) => list.appendChild(songRow(s, i + 1, n)));
  block.appendChild(list);
  if (data.below.length) {
    const det = el("details", "live-below", `<summary>${t("Played less often ({count}), not in the playlist", { count: data.below.length })}</summary>`);
    det.open = belowOpen;
    const bl = el("div", "row-list");
    data.below.forEach((s) => bl.appendChild(songRow(s, null, n)));
    det.appendChild(bl); block.appendChild(det);
  }

  block.appendChild(recipientsRow());
  const create = el("div", "form-row");
  const name = el("input", "search grow"); name.id = "live-name";
  name.value = live.name || data.suggested_name;
  name.oninput = () => { live.name = name.value; };
  const btn = el("button", "btn btn-primary glow", `<svg viewBox="0 0 24 24"><path d="M19 13h-6v6h-2v-6H5v-2h6V5h2v6h6v2z"/></svg> ${t("Create playlist")}`);
  btn.disabled = data.matched_count === 0;
  btn.onclick = () => createLive(ids, name.value.trim(), btn);
  create.append(name, btn);
  block.appendChild(create);
  box.appendChild(block);
}

// "For: [user chips] [all]  (o) Public for all users". A private copy goes to each chosen
// user; a public playlist is one, owned by the first chosen user, so the chips grey out.
function recipientsRow() {
  const row = el("div", "live-quick live-for", `<span>${t("For:")}</span>`);
  const before = owner();
  const changed = () => {
    localStorage.setItem(LIVE_USERS_KEY, JSON.stringify([...live.users]));
    row.replaceWith(recipientsRow());
    if (owner() !== before) schedulePreview(true);
  };
  const chip = (label, on, onclick) => {
    const b = el("button", "pick-chip" + (on ? " on" : ""), esc(label));
    b.disabled = live.public;
    b.onclick = onclick;
    row.appendChild(b);
  };
  for (const name of live.allUsers) {
    chip(name, live.users.has(name), () => {
      if (!live.users.has(name)) live.users.add(name);
      else if (live.users.size > 1) live.users.delete(name);
      changed();
    });
  }
  const everyone = live.allUsers.length > 1 && live.allUsers.every((u) => live.users.has(u));
  if (live.allUsers.length > 1) {
    chip(t("all"), everyone, () => { live.users = new Set(everyone ? [live.allUsers[0]] : live.allUsers); changed(); });
  }
  const pub = el("label", "toggle", `<input type="checkbox" ${live.public ? "checked" : ""}><span class="slider"></span><span>${t("Public for all users")}</span>`);
  pub.querySelector("input").onchange = (e) => { live.public = e.target.checked; changed(); };
  row.appendChild(pub);
  if (live.public && before) row.appendChild(el("span", "users", t("owned by {user}", { user: esc(before) })));
  return row;
}

async function createLive(ids, name, btn) {
  if (!name) { toast(t("The name is missing."), "err"); return; }
  btn.disabled = true;
  const users = live.public ? [owner()].filter(Boolean) : live.allUsers.filter((u) => live.users.has(u));
  try {
    const r = await post("/api/live/playlist", { artist: live.artist, users, public: live.public, setlist_ids: ids, min_share: live.minShare, name });
    for (const c of r.created) {
      const values = { name: c.name, count: c.track_count, user: c.user };
      toast(r.public ? t("Created: {name} ({count} songs, public, owned by {user})", values) : t("Created: {name} ({count} songs, for {user})", values), "ok");
      if (c.warning) toast(c.warning, "err");
    }
    for (const f of r.failed) toast(`${f.user}: ${f.error}`, "err");
    loadLiveExisting();
  } catch (e) { toast(e.message, "err"); }
  btn.disabled = false;
}

async function loadLiveExisting() {
  const box = $("#live-existing");
  let data;
  try { data = await get("/api/live/playlists"); } catch (_) { box.innerHTML = ""; return; }
  box.innerHTML = "";
  const block = el("div", "result-block glass", `<h4>${t("Existing live playlists ({count})", { count: data.playlists.length })}</h4>`);
  if (!data.playlists.length) block.appendChild(el("div", "muted", t("None yet. Deleting only works by hand in Jellyfin.")));
  const list = el("div", "row-list");
  for (const p of data.playlists) list.appendChild(playlistRow(p));
  block.appendChild(list); box.appendChild(block);
}

$("#live-load").onclick = () => loadConcerts({ force: true });
// Picking from a datalist fires `input` (Chrome sends `change` only once the field
// loses focus); typing fires `input` too, but with inputType insertText or delete*.
// `change` still covers Enter and leaving the field after typing. loadConcerts
// skips a request it just made, so a pick followed by `change` loads once.
const isPick = (e) => !e.inputType || e.inputType === "insertReplacementText";
const isOption = (input) => [...input.list.options].some((o) => o.value === input.value);
// Picking a library artist loads its concerts at once and starts the filters fresh;
// Enter loads any other name, so setlist.fm can offer its candidates.
const isLibraryArtist = () => (artistOptions || []).includes($("#live-artist").value.trim());
const artistPicked = () => { if (isLibraryArtist()) { clearFilters(); loadConcerts(); } };
$("#live-artist").addEventListener("input", (e) => { if (isPick(e)) artistPicked(); });
$("#live-artist").addEventListener("change", artistPicked);
$("#live-artist").addEventListener("keydown", (e) => { if (e.key === "Enter" && !isLibraryArtist()) loadConcerts({ force: true }); });
for (const f of LIVE_FILTERS) {
  const input = filterInput(f);
  input.addEventListener("input", (e) => { if (live.artist && isPick(e) && isOption(input)) loadConcerts(); });
  input.addEventListener("change", () => { if (live.artist) loadConcerts(); });
}
$("#live-clear").onclick = () => { clearFilters(); if (live.artist) loadConcerts(); };

// ============================================================ PURGE
async function purgePreview() {
  const body = $("#purge-body");
  body.innerHTML = `<div class="loader"><span class="spinner"></span> ${t("Searching playlists…")}</div>`;
  let data;
  try { data = await post("/api/purge/preview", { prefix: $("#purge-prefix").value.trim() || null }); }
  catch (e) { body.innerHTML = `<div class="empty err">${esc(e.message)}</div>`; $("#purge-exec").disabled = true; return; }
  $("#purge-prefix").dataset.selection = data.selection;
  const n = data.playlists.length;
  $("#purge-exec").disabled = n === 0;
  const block = el("div", "result-block glass");
  block.innerHTML = `<h4>${t("Preview")} · ${esc(data.selection)} · ${t("{count} users", { count: data.user_count })}</h4>`;
  if (!n) { block.innerHTML += `<div class="muted">${t("No matching playlists.")}</div>`; body.innerHTML = ""; body.appendChild(block); return; }
  const list = el("div", "row-list");
  for (const p of data.playlists) list.appendChild(playlistRow(p));
  block.appendChild(el("div", "muted", t('<span class="tag-del">{count} playlists</span> would be deleted.', { count: n })));
  block.appendChild(list);
  body.innerHTML = ""; body.appendChild(block);
}
async function purgeExec() {
  const selection = $("#purge-prefix").dataset.selection;
  if (!(await confirmModal(t("Delete playlists?"), t("All playlists with {selection} will be deleted irrevocably.", { selection })))) return;
  try {
    const r = await post("/api/purge", { prefix: $("#purge-prefix").value.trim() || null });
    toast(t("{deleted} deleted, {failed} errors", { deleted: r.deleted, failed: r.failed }), r.failed ? "err" : "ok");
    $("#purge-exec").disabled = true; purgePreview();
  } catch (e) { toast(e.message, "err"); }
}
$("#purge-preview").onclick = purgePreview;
$("#purge-exec").onclick = purgeExec;

// ============================================================ PRUNE
async function prunePreview() {
  const body = $("#prune-body");
  const keep = $("#prune-keep").value.split(",").map((s) => s.trim()).filter(Boolean);
  if (!keep.length) { toast(t("The keep list is empty."), "err"); return; }
  body.innerHTML = `<div class="loader"><span class="spinner"></span> ${t("Loading playlists…")}</div>`;
  let data;
  try { data = await post("/api/prune/preview", { keep, rename_prefix: $("#prune-rename").value }); }
  catch (e) { body.innerHTML = `<div class="empty err">${esc(e.message)}</div>`; $("#prune-exec").disabled = true; return; }
  $("#prune-exec").disabled = data.delete.length === 0 && data.keep.every((k) => !k.will_rename);
  body.innerHTML = "";

  const keepB = el("div", "result-block glass");
  keepB.innerHTML = `<h4><span class="tag-keep">${t("Keep")}</span> (${data.keep.length})</h4>`;
  const kl = el("div", "row-list");
  for (const k of data.keep) kl.appendChild(el("div", "row-item", `<span>${esc(k.name)}</span>${k.will_rename ? `<span class="arrow">→ ${esc(k.target)}</span>` : '<span class="users">ok</span>'}`));
  keepB.appendChild(kl); body.appendChild(keepB);

  if (data.protected && data.protected.length) {
    const protB = el("div", "result-block glass");
    protB.innerHTML = `<h4><span class="tag-keep">${t("Protected")}</span> (${data.protected.length}) · ${t("live playlists are always kept")}</h4>`;
    const pl = el("div", "row-list");
    for (const p of data.protected) pl.appendChild(playlistRow(p));
    protB.appendChild(pl); body.appendChild(protB);
  }

  const delB = el("div", "result-block glass");
  delB.innerHTML = `<h4><span class="tag-del">${t("Delete")}</span> (${data.delete.length})</h4>`;
  if (data.delete.length) {
    const dl = el("div", "row-list");
    for (const d of data.delete) dl.appendChild(playlistRow(d));
    delB.appendChild(dl);
  } else { delB.appendChild(el("div", "muted", t("Nothing to delete."))); }
  body.appendChild(delB);

  if (data.unmatched && data.unmatched.length) body.appendChild(el("div", "alert warn", t("No match for: {names}", { names: esc(data.unmatched.join(", ")) })));
}
async function pruneExec() {
  const keep = $("#prune-keep").value.split(",").map((s) => s.trim()).filter(Boolean);
  if (!(await confirmModal(t("Run prune?"), t("All playlists except the keep list will be deleted. Kept ones may be renamed.")))) return;
  try {
    const r = await post("/api/prune", { keep, rename_prefix: $("#prune-rename").value });
    toast(t("{deleted} deleted, {renamed} renamed, {kept} kept", { deleted: r.deleted, renamed: r.renamed, kept: r.kept }), (r.delete_failed || r.rename_failed) ? "err" : "ok");
    $("#prune-exec").disabled = true; prunePreview();
  } catch (e) { toast(e.message, "err"); }
}
$("#prune-preview").onclick = prunePreview;
$("#prune-exec").onclick = pruneExec;

// ============================================================ CONFIG
async function loadConfig() {
  const body = $("#config-body");
  body.innerHTML = `<div class="loader"><span class="spinner"></span> ${t("Loading…")}</div>`;
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
  let auth = {};
  try { auth = await get("/api/auth"); } catch (_) {}
  await useLanguage(auth.language);
  if (auth.token_required && !TOKEN) { showGate(); return; }
  boot();
}
init();
