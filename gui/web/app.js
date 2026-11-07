/* Dolby Access Custom - UI. Talks to gui/api.py through pywebview or the local HTTP fallback. */
"use strict";

async function call(name, ...args) { return window.pywebview.api[name](...args); }

/* ------------------------------------------------------------------ catalogue */
const ICON = {
  Dynamic: '<path d="M13 2L4 14h7l-1 8 9-12h-7z"/>',
  Movie: '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="M3 9h18M3 15h18M8 5v4M16 5v4M8 15v4M16 15v4"/>',
  Music: '<path d="M9 18V5l11-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="17" cy="16" r="3"/>',
  Game: '<path d="M6 9h12a4 4 0 0 1 4 4v1a3 3 0 0 1-5.4 1.8L15 14H9l-1.6 1.8A3 3 0 0 1 2 14v-1a4 4 0 0 1 4-4z"/><path d="M7 11v3M5.5 12.5h3M16 12h.01M18 13.5h.01"/>',
  Voice: '<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3"/>',
  Flat: '<path d="M3 12h18"/><path d="M6 8v8M18 8v8" opacity=".5"/>',
};
const PROFILES = [
  { key: "Dynamic", vi: "", c: ["#b06cff", "#ff5fa2"] },
  { key: "Movie", vi: "", c: ["#ff6a5f", "#ffa23d"] },
  { key: "Music", vi: "", c: ["#4f8dff", "#8b6bff"] },
  { key: "Game", vi: "", c: ["#1fd1a5", "#1aa0ff"] },
  { key: "Voice", vi: "", c: ["#ffcf4a", "#ff8a3d"] },
  { key: "Flat", vi: "No EQ", c: ["#9aa3b5", "#5e677a"] },
];
const IEQ_ORDER = ["Detailed", "Balanced", "Warm", "Off", "Performance", "Default", ""];
const IEQ_VI = { Detailed: "Detailed", Balanced: "Balanced", Warm: "Warm", Off: "IEQ off", Performance: "Performance", Default: "Default", "": "No EQ" };
const VI_WORDS = [[/khop Dolby/g, "Dolby-matched"], [/leveler nho/g, "memory leveler"], [/khong EQ/g, "no EQ"], [/khong/g, "no"], [/tham chieu/g, "reference"]];
const vi = (s) => VI_WORDS.reduce((t, [a, b]) => t.replace(a, b), s || "");
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const $ = (id) => document.getElementById(id);

let MODES = [], S = null, cursor = 0, view = { profile: null, ieq: null }, busyMode = false;
const prof = (k) => PROFILES.find((p) => p.key === k) || PROFILES[5];
const byId = (id) => MODES.find((m) => m.id === id);

/* ------------------------------------------------------------------ curves */
const F0 = Math.log10(20), F1 = Math.log10(20000);
function curvePath(pts, w, h, range, pad = 0) {
  if (!pts || !pts.length) pts = [[20, 0], [20000, 0]];
  const x = (f) => pad + ((Math.log10(f) - F0) / (F1 - F0)) * (w - pad * 2);
  const y = (g) => h / 2 - (g / range) * (h / 2 - 4);
  const p = pts.filter((q) => q[0] >= 20 && q[0] <= 20000).map((q) => [x(q[0]), y(q[1])]);
  let d = `M${p[0][0].toFixed(1)},${p[0][1].toFixed(1)}`;
  for (let i = 1; i < p.length; i++) {   // light Catmull-Rom smoothing
    const a = p[i - 2] || p[i - 1], b = p[i - 1], c = p[i], e = p[i + 1] || c;
    const c1 = [b[0] + (c[0] - a[0]) / 6, b[1] + (c[1] - a[1]) / 6], c2 = [c[0] - (e[0] - b[0]) / 6, c[1] - (e[1] - b[1]) / 6];
    d += `C${c1[0].toFixed(1)},${c1[1].toFixed(1)} ${c2[0].toFixed(1)},${c2[1].toFixed(1)} ${c[0].toFixed(1)},${c[1].toFixed(1)}`;
  }
  return { d, first: p[0], last: p[p.length - 1], y0: h / 2 };
}
function rel1k(pts) {   // show shape relative to 1 kHz, like Dolby's curves
  if (!pts || !pts.length) return pts;
  const r = pts.reduce((b, q) => (Math.abs(Math.log(q[0] / 1000)) < Math.abs(Math.log(b[0] / 1000)) ? q : b));
  return pts.map((q) => [q[0], q[1] - r[1]]);
}
function rangeOf(pts, min = 6) { return Math.max(min, Math.ceil(Math.max(0, ...(pts || []).map((q) => Math.abs(q[1]))) / 3) * 3 + 1); }

function miniCurve(pts, c, id) {
  const P = rel1k(pts), r = Math.max(8, rangeOf(P)), k = curvePath(P, 120, 42, r);
  return `<svg viewBox="0 0 120 42" preserveAspectRatio="none"><defs><linearGradient id="${id}" x1="0" x2="1"><stop offset="0" stop-color="${c[0]}"/><stop offset="1" stop-color="${c[1]}"/></linearGradient></defs>
    <line x1="0" x2="120" y1="21" y2="21" stroke="rgba(255,255,255,.1)"/><path d="${k.d}" fill="none" stroke="url(#${id})" stroke-width="2" stroke-linecap="round"/></svg>`;
}

function drawHeroCurve(m, c) {
  const P = rel1k(m ? m.curve : []), r = Math.max(9, rangeOf(P)), k = curvePath(P, 320, 120, r);
  $("heroCurve").innerHTML = `<defs><linearGradient id="hc" x1="0" x2="1"><stop offset="0" stop-color="${c[0]}"/><stop offset="1" stop-color="${c[1]}"/></linearGradient>
    <linearGradient id="hf" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${c[0]}" stop-opacity=".35"/><stop offset="1" stop-color="${c[0]}" stop-opacity="0"/></linearGradient></defs>
    <path d="${k.d}L${k.last[0]},120L${k.first[0]},120Z" fill="url(#hf)"/>
    <path d="${k.d}" fill="none" stroke="url(#hc)" stroke-width="3" stroke-linecap="round"/>`;
}

function drawChart(m, c) {
  const W = 560, H = 260, L = 38, R = 10, T = 12, B = 26, w = W - L - R, h = H - T - B;
  const P = rel1k(m ? m.curve : []), r = rangeOf(P, 9);
  const x = (f) => L + ((Math.log10(f) - F0) / (F1 - F0)) * w, y = (g) => T + h / 2 - (g / r) * (h / 2);
  let g = "";
  for (const f of [20, 50, 100, 200, 500, 1000, 2000, 5000, 10000, 20000]) {
    g += `<line class="grid" x1="${x(f)}" x2="${x(f)}" y1="${T}" y2="${T + h}"/><text x="${x(f)}" y="${H - 8}" text-anchor="middle">${f >= 1000 ? f / 1000 + "k" : f}</text>`;
  }
  const step = r > 12 ? 6 : 3;
  for (let d = -Math.floor(r / step) * step; d <= r; d += step) {
    g += `<line class="${d === 0 ? "zero" : "grid"}" x1="${L}" x2="${L + w}" y1="${y(d)}" y2="${y(d)}"/><text x="${L - 8}" y="${y(d) + 3.5}" text-anchor="end">${d > 0 ? "+" + d : d}</text>`;
  }
  const inner = curvePath(P, w, h, r);
  $("chart").innerHTML = `<defs><linearGradient id="cc" x1="0" x2="1"><stop offset="0" stop-color="${c[0]}"/><stop offset="1" stop-color="${c[1]}"/></linearGradient>
    <linearGradient id="cf" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${c[0]}" stop-opacity=".28"/><stop offset="1" stop-color="${c[0]}" stop-opacity="0"/></linearGradient></defs>
    ${g}<g transform="translate(${L},${T})"><path d="${inner.d}L${inner.last[0]},${inner.y0}L${inner.first[0]},${inner.y0}Z" fill="url(#cf)"/>
    <path d="${inner.d}" fill="none" stroke="url(#cc)" stroke-width="2.6" stroke-linecap="round"/></g>`;
  $("curveHint").textContent = m && m.curve.length ? `${m.curve.length}-point GraphicEQ · relative to 1 kHz · preamp ${m.preamp} dB` : "No EQ";
}

/* ------------------------------------------------------------------ mode selection logic */
function groups() {
  const g = {};
  for (const m of MODES) ((g[m.profile] ||= {})[m.ieq] ||= []).push(m);
  return g;
}
function pick(profile, ieq) {   // remembered variant first, then the live one, then a matched one
  const g = groups()[profile] || {}, pref = (S && S.pref) || {};
  const list = ieq === undefined ? Object.values(g).flat() : g[ieq] || [];
  if (!list.length) return null;
  const want = pref[ieq === undefined ? profile : `${profile}|${ieq}`];
  return list.find((m) => m.id === want) || list.find((m) => S && m.id === S.current)
    || list.slice().sort((a, b) => b.stages.length - a.stages.length)[0];
}

async function useMode(m) {
  if (!m || busyMode) return;
  if (S && m.id === S.current) { view = { profile: m.profile, ieq: m.ieq }; render(); return; }
  busyMode = true; view = { profile: m.profile, ieq: m.ieq };
  S.current = m.id; render();
  try {
    const r = await call("use_mode", m.id);
    if (!r.ok) toast(r.error || "Could not switch mode", "warn");
  } finally { busyMode = false; poll(); }
}

/* ------------------------------------------------------------------ render */
function render() {
  if (!S) return;
  const cur = byId(S.current), g = groups();
  if (!view.profile && cur) view = { profile: cur.profile, ieq: cur.ieq };
  const P = prof(view.profile || (cur && cur.profile) || "Music");
  document.body.classList.toggle("off", !S.active);

  // hero
  const hm = cur || null, hp = prof(hm ? hm.profile : "Flat");
  const hero = $("hero"); hero.style.setProperty("--c1", hp.c[0]); hero.style.setProperty("--c2", hp.c[1]);
  $("heroIcon").innerHTML = `<svg viewBox="0 0 24 24">${ICON[hp.key]}</svg>`;
  $("heroName").textContent = hm ? (hm.profile === "Flat" ? "Original (no EQ)" : `${hp.key} · ${IEQ_VI[hm.ieq] || hm.ieq}`) : "No mode selected";
  $("heroSub").textContent = hm ? (vi(hm.variant) || vi(hm.name)) + (S.active ? "" : " · off") : "Pick a mode below";
  const chips = [];
  if (hm) {
    chips.push(S.active ? `<span class="chip ok">On</span>` : `<span class="chip warn">${S.paused_by_guard ? "Paused by guard" : "Off"}</span>`);
    hm.stages.forEach((s) => chips.push(`<span class="chip">${esc(s)}</span>`));
    if (hm.linked) chips.push(`<span class="chip">Linked to HeSuVi</span>`);
  }
  $("heroChips").innerHTML = chips.join("");
  drawHeroCurve(hm, hp.c);

  // profile cards
  $("profiles").innerHTML = PROFILES.map((p) => {
    const has = !!g[p.key], sel = cur && cur.profile === p.key, n = has ? Object.values(g[p.key]).flat().length : 0;
    const sub = has ? (sel ? IEQ_VI[cur.ieq] || p.vi : p.vi || `${n} mode${n > 1 ? "s" : ""}`) : "Not measured";
    return `<button class="prof ${sel ? "sel" : ""} ${has ? "" : "empty"} ${view.profile === p.key && !sel ? "peek" : ""}" data-prof="${p.key}" style="--c1:${p.c[0]};--c2:${p.c[1]}" title="${has ? n + " versions" : "Not measured yet, click to measure"}">
      <span class="pi"><svg viewBox="0 0 24 24">${ICON[p.key]}</svg></span><span><b>${p.key === "Flat" ? "Original" : p.key}</b><small>${sub}</small></span></button>`;
  }).join("");

  // IEQ tiles for the profile being viewed
  const vp = view.profile || "Music", vg = g[vp] || {};
  const order = IEQ_ORDER.filter((k) => vg[k] || (vp === "Music" || vp === "Movie" || vp === "Dynamic") && ["Detailed", "Balanced", "Warm"].includes(k));
  $("ieqHint").textContent = `${vp === "Flat" ? "Original" : vp} · ${Object.values(vg).flat().length} modes`;
  $("ieqs").style.setProperty("--c1", P.c[0]);
  $("ieqs").innerHTML = order.map((k, i) => {
    const m = vg[k] ? pick(vp, k) : null, sel = cur && cur.profile === vp && cur.ieq === k;
    return `<button class="ieq ${sel ? "sel" : ""} ${m ? "" : "na"}" data-ieq="${k}">${miniCurve(m ? m.curve : [], P.c, "m" + i)}
      <span><b>${IEQ_VI[k] || k}</b><small>${m ? (vg[k].length > 1 ? vg[k].length + " versions" : "1 version") : "Not measured"}</small></span></button>`;
  }).join("") || `<p class="hint">No modes for this profile yet.</p>`;

  // variants of the viewed profile + ieq
  const vlist = (vg[view.ieq] || []).slice().sort((a, b) => b.stages.length - a.stages.length);
  $("variants").style.setProperty("--c1", P.c[0]);
  $("variants").innerHTML = vlist.length > 1 ? `<div class="vh">Versions</div>` + vlist.map((m) => `
    <button class="var ${S.current === m.id ? "sel" : ""}" data-mode="${m.id}"><span class="radio"></span><span class="var-body">
      <b>${esc(vi(m.variant) || vi(m.name))}</b>
      <div class="chips">${m.stages.map((s) => `<span class="chip">${esc(s)}</span>`).join("")}${m.linked ? '<span class="chip">Linked to HeSuVi</span>' : ""}${!m.stages.length && m.curve.length ? '<span class="chip">EQ only</span>' : ""}</div>
    </span></button>`).join("") : "";

  const shown = (S.current && byId(S.current) && byId(S.current).profile === vp && byId(S.current).ieq === view.ieq) ? byId(S.current) : pick(vp, view.ieq);
  drawChart(shown, P.c);
  $("modeNotes").innerHTML = shown && shown.notes ? `<b>Notes:</b> ${esc(vi(shown.notes))}` : "";

  renderTop(); renderDevices(); renderTask();
}

function renderTop() {
  const pw = $("power"); pw.checked = !!S.active; pw.parentElement.classList.toggle("on", !!S.active);
  $("powerLabel").textContent = S.active ? "On" : "Off";
  const d = S.target_device || S.default_device;
  $("devName").textContent = d ? (d.iface || d.name).replace(/ (Stereo|Hands-Free)$/, "") : "No headphones found";
  $("devSub").textContent = d ? `${d.name}${S.default_device && d.guid === S.default_device.guid ? " · default" : " · not default"}` : "Check the connection";
  // only the device you listen on (or the one this app's EQ runs on) raises the alarm; a laptop's own speaker tuning
  // stack on an unused device is shown on its card, not as an error
  const eps = (S.scan.endpoints || []).filter((e) => e.connected), bad = eps.filter((e) => e.conflict && (e.default || e.has_eapo));
  $("navAlert").hidden = !bad.length;
  const st = $("status"); let cls = "ok", txt = "No double processing";
  if (!S.scan.endpoints) { cls = ""; txt = "Scanning devices…"; }
  else if (bad.length) { cls = "bad"; txt = `${bad.length} device${bad.length > 1 ? "s" : ""} double-processed`; }
  else if (S.paused_by_guard) { cls = "warn"; txt = "Mode paused by the guard"; }
  else if (!S.active) { cls = "warn"; txt = "Original sound"; }
  st.className = "status " + cls; st.querySelector("span").textContent = txt;

  const n = S.notice, nb = $("notice");
  nb.hidden = !n;
  if (n) {
    const installing = S.task && S.task.kind === "install", busyAttach = !!(S.task && S.task.kind === "attach");
    $("noticeTitle").textContent = installing ? S.task.label : n.kind === "no-eapo" ? "Sound modes are not set up on this PC" : `${n.device} is not connected to the mode yet`;
    $("noticeText").textContent = installing ? "Confirm the Windows prompt. This takes about a minute." : n.text + (n.kind === "no-eapo" ? " Pick your device and the app installs everything." : " One click connects it, no restart needed.");
    $("noticeBtn").textContent = installing ? "Installing…" : n.kind === "no-eapo" ? "Set up" : busyAttach ? "Connecting…" : "Connect";
    $("noticeBtn").disabled = !!installing || busyAttach;
    $("noticeBtn").dataset.kind = n.kind;
  }

  const b = $("banner");
  if (bad.length || S.paused_by_guard) {
    const e = bad[0] || S.default_device, other = e ? e.layers.filter((l) => l.active && l.kind !== "eapo").map((l) => l.name) : [];
    b.hidden = false; b.className = "banner" + (bad.length ? " bad" : "");
    $("bannerTitle").textContent = bad.length ? `${e.iface || e.name} is processed by ${e.shaping} layers` : "Mode paused to avoid double processing";
    const fixable = !!(bad.length && e.extra && e.extra.length && !e.sysfx_disabled);
    $("bannerText").textContent = other.length ? `Active: ${other.join(", ")}. ` + (fixable ? "Turn off the extra layers to keep a single one." : "Turn it off (e.g. Spatial sound → Off) to keep a single layer.")
      + (S.policy === "auto" && S.paused_by_guard ? " The mode comes back on by itself." : "")
      : "Open Sound settings to check.";
    $("bannerFix").hidden = !fixable; $("bannerFix").dataset.guid = fixable ? e.guid : "";
  } else b.hidden = true;
}

let devHtml = "";
function renderDevices() {
  document.querySelectorAll("#policy button").forEach((x) => x.classList.toggle("on", x.dataset.v === S.policy));
  const eps = S.scan.endpoints;
  if (!eps) { $("devices").innerHTML = `<p class="hint">Scanning…</p>`; return; }
  const list = eps.filter((e) => e.connected);
  const html = list.map((e) => `
    <div class="dev ${e.conflict ? "conflict" : ""} ${e.default ? "default" : ""}">
      <div class="dev-h"><div class="dev-ico"><svg viewBox="0 0 24 24">${/headphone|headset|tai nghe/i.test(e.name) ? '<path d="M4 14v-2a8 8 0 0 1 16 0v2"/><rect x="3" y="14" width="4" height="6" rx="1.5"/><rect x="17" y="14" width="4" height="6" rx="1.5"/>' : '<rect x="6" y="3" width="12" height="18" rx="2"/><circle cx="12" cy="14" r="3.5"/><path d="M12 7h.01"/>'}</svg></div>
        <div><b>${esc(e.iface || e.name)}</b><span>${esc(e.name)}${e.default ? " · default" : ""}${e.default_comm ? " · communications" : ""}</span></div>
        <span class="pill ${e.conflict ? "bad" : e.shaping ? "ok" : ""}">${e.conflict ? e.shaping + " layers" : e.shaping ? "1 layer" : "Original"}</span></div>
      ${e.layers.length ? e.layers.map((l) => `<div class="layer ${l.active ? "on" : ""}"><i></i><span class="ln">${esc(l.kind_label)}<small>${esc(l.name)}</small></span>
        <span class="ls">${l.active ? "On" : "Off"}${l.detail && l.detail !== "Off" ? " · " + esc(vi(l.detail)) : ""}${l.certain ? "" : ' <span class="unsure" title="Inferred, not verified on this PC">(?)</span>'}</span></div>`).join("")
        : `<div class="none">No processing layers.</div>`}
      ${fixRow(e)}
    </div>`).join("");
  if (devHtml !== html) { $("devices").innerHTML = devHtml = html; }   // keep buttons clickable between polls
  const n = S.scan.nahimic || {};
  $("nahimicBox").hidden = !n.installed;
  if (n.installed) {
    $("nahimicText").textContent = n.off_by_app ? "Stopped by this app (service, tray app and startup tasks). Start it again any time."
      : n.running ? "Running in the background. Its sound effects are bypassed per device with \u201cTurn off extra layers\u201d; stopping the app itself is optional."
      : "Not running.";
    $("nahimicBtn").textContent = n.off_by_app ? "Start Nahimic again" : "Stop Nahimic";
    $("nahimicBtn").dataset.action = n.off_by_app ? "start" : "stop";
    $("nahimicBtn").disabled = !n.off_by_app && !n.running;
  }
  $("scanInfo").textContent = [...(S.scan.info || []).map(vi), S.scan_age != null ? `Scanned ${Math.round(S.scan_age)} s ago` : ""].filter(Boolean).join("  ·  ");
}

function fixRow(e) {
  const eapoInstalled = !(S.notice && S.notice.kind === "no-eapo");
  const conn = !eapoInstalled || /hands-free/i.test(e.name + " " + e.iface) ? ""
    : e.has_eapo ? `<div class="dev-fix"><span>Sound modes connected.</span><button class="btn ghost sm" data-detach="${e.guid}">Disconnect</button></div>`
    : `<div class="dev-fix"><span>Not connected to the sound modes.</span><button class="btn ghost sm" data-connect="${e.guid}">Connect</button></div>`;
  return fixRow2(e) + conn;
}
function fixRow2(e) {
  if (e.off_by_app) return `<div class="dev-fix"><span>Audio enhancements turned off by this app.</span><button class="btn ghost sm" data-restore="${e.guid}">Restore</button></div>`;
  if (e.extra && e.extra.length && !e.sysfx_disabled)
    return `<div class="dev-fix"><span>${esc(e.extra.join(", "))} also process${e.extra.length > 1 ? "" : "es"} this device.</span><button class="btn primary sm" data-fix="${e.guid}">Turn off extra layers</button></div>`;
  if (e.sysfx_disabled) return `<div class="dev-fix"><span>Audio enhancements are off for this device.</span></div>`;
  return "";
}

function pickerHtml(devs, pre) {
  if (!devs.length) return `<p>No playback device found. Connect your headphones and try again.</p>`;
  return `<div class="picker">${devs.map((d) => `<label class="pick"><input type="radio" name="dev" value="${d.guid}" ${d.guid === pre ? "checked" : ""}>
    <span><b>${esc(d.name)}</b><small>${esc(d.kind)}${d.default ? " · in use now" : ""}${d.has_eapo ? " · already connected" : ""}</small></span></label>`).join("")}</div>
    <label class="keep"><input type="checkbox" id="keepOrig"> Keep the device maker's effects too (Nahimic, Realtek…). Leave off for a single clean layer.</label>`;
}
const picked = () => { const r = document.querySelector('#cBody input[name="dev"]:checked'); return r ? r.value : null; };
const keepOrig = () => { const k = $("keepOrig"); return !!(k && k.checked); };
function defaultPick(devs) { const d = devs.find((x) => x.headphones && x.default) || devs.find((x) => x.headphones) || devs.find((x) => x.default) || devs[0]; return d && d.guid; }

async function connectDevice(guid) {
  const devs = await call("setup_devices");
  const ok = await confirmBox("Use the sound modes on which device?",
    `Pick your headphones. The app connects Equalizer APO to it (no extra window), Windows asks for <b>administrator</b> permission once and the sound drops for a few seconds.`
    + pickerHtml(devs, guid || defaultPick(devs)), "Connect");
  const g = picked(), keep = keepOrig();
  if (!ok || !g) return;
  toast("Connecting… confirm the Windows prompt");
  const r = await call("attach", g, keep); if (!r.ok) toast(r.error, "warn"); poll();
}

function confirmBox(title, html, yes = "Continue") {
  const d = $("confirm"); $("cTitle").textContent = title; $("cBody").innerHTML = html; $("cYes").textContent = yes;
  return new Promise((res) => {
    const done = (v) => { d.close(); $("cYes").onclick = $("cNo").onclick = null; d.oncancel = null; res(v); };
    $("cYes").onclick = () => done(true); $("cNo").onclick = () => done(false); d.oncancel = () => done(false);
    d.showModal();
  });
}

async function fixLayers(guid) {
  const e = (S.scan.endpoints || []).find((x) => x.guid === guid); if (!e) return;
  const nm = esc(e.iface || e.name);
  const ok = await confirmBox(`Turn off extra layers on ${e.iface || e.name}?`,
    `This sets <b>Audio enhancements: Off</b> for ${nm} (the same switch as in Windows Sound settings). It bypasses:<ul>${e.extra.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>`
    + (/speaker/i.test(e.name) ? `Built-in laptop speakers can sound thinner without the maker's tuning; Restore brings it back.<br>` : "")
    + (e.has_eapo ?`<b>Equalizer APO is on this device too and is bypassed as well</b>, so this app's modes stop working on it until you restore.<br>` : "")
    + `Other devices are not touched. The setting stays after a restart; <b>Restore</b> on the device card undoes it.`, "Turn off");
  if (!ok) return;
  const r = await call("layers_off", guid);
  if (!r.ok) toast(r.error, "warn"); poll();
}

async function nahimicAction(action) {
  if (action === "stop") {
    const ok = await confirmBox("Stop Nahimic?",
      `Stops the Nahimic service, closes its tray app and turns off its startup tasks, so it stays off after a restart.`
      + `<ul><li>Windows asks for <b>administrator</b> permission once.</li><li>The previous settings are saved; <b>Start Nahimic again</b> puts everything back.</li></ul>`
      + `Not needed for sound quality: \u201cTurn off extra layers\u201d already bypasses Nahimic's effects on a device.`, "Stop Nahimic");
    if (!ok) return;
  }
  $("nahimicBtn").disabled = true;
  toast(action === "stop" ? "Stopping Nahimic… confirm the Windows prompt" : "Starting Nahimic… confirm the Windows prompt");
  const r = await call("nahimic", action);
  if (!r.ok) toast(r.error, "warn"); poll();
}

let mStart = 0;
function renderTask() {
  const t = S.task, run = !!t;
  $("mStart").disabled = run; $("listen").disabled = run;
  if (t && t.kind === "measure") {
    const pct = Math.min(98, (t.elapsed / t.expected) * 100);
    $("mBar").style.width = pct + "%"; $("mHint").textContent = `${t.label} · ${Math.round(t.elapsed)} / ~${t.expected} s`;
  } else if (mStart) { $("mBar").style.width = "100%"; $("mHint").textContent = "Done"; mStart = 0; }
}

/* ------------------------------------------------------------------ 7.1 surround */
let SUR = null, surBusy = false, surAt = 0;
const SPK = [["L", 70, 62], ["C", 160, 34], ["R", 250, 62], ["SR", 284, 132], ["RR", 238, 200], ["RL", 82, 200], ["SL", 36, 132]];
function drawRoom() {
  $("surRoom").innerHTML = `<circle class="ring" cx="160" cy="124" r="96"/>` +
    `<g class="headg"><ellipse class="head" cx="160" cy="124" rx="24" ry="28"/><path class="head" d="M149 97l11-11 11 11"/></g>` +
    SPK.map(([n, x, y], i) => `<g class="spk" data-i="${i}"><circle cx="${x}" cy="${y}" r="17"/><text x="${x}" y="${y + 4}">${n}</text></g>`).join("");
}
async function loadSurround(force) {
  if (surBusy || (!force && Date.now() - surAt < 3000)) return;
  surBusy = true;
  try { SUR = await call("surround_status"); surAt = Date.now(); renderSurround(); }
  catch (e) { console.error(e); }
  finally { surBusy = false; }
}
function renderSurround() {
  const st = SUR; if (!st) return;
  const c = st.cable || {}, v = st.virtualizer || {}, apps = st.apps || [];
  const is71 = c.channels === 8, hrirOk = v.configured && !(v.hrir_missing || []).length && v.hrir && v.hrir.length;
  const dflt = S && S.default_device, loop = dflt && /CABLE Input/i.test(dflt.name || "");
  const level = !st.installed ? "bad" : st.ready && !loop ? "ok" : "warn";
  $("navSur").hidden = level === "ok";
  $("navSur").className = "dot " + (level === "bad" ? "bad" : "warn");
  const pill = $("surPill"); pill.className = "pill " + level;
  pill.textContent = !st.installed ? "Not set up" : level === "ok" ? "Ready" : !st.bridge_running ? "Bridge stopped" : "Needs attention";
  const pw = $("surPower"); pw.checked = !!st.bridge_running; pw.disabled = !st.installed;
  pw.parentElement.classList.toggle("on", !!st.bridge_running);
  $("surPowerLabel").textContent = st.bridge_running ? "On" : "Off";

  const hp = dflt ? (dflt.iface || dflt.name).replace(/ (Stereo|Hands-Free)$/, "") : "No default device";
  const nodes = [
    [apps.length ? "ok" : "warn", "Apps → CABLE Input", apps.length ? `${apps.length} app${apps.length > 1 ? "s" : ""} routed` : "No app routed yet"],
    [!st.installed ? "bad" : is71 ? "ok" : "warn", "CABLE Input 7.1", !st.installed ? "VB-CABLE missing" : `${c.channels || "?"} ch · ${c.rate ? c.rate / 1000 + " kHz" : "?"}`],
    [c.eapo && hrirOk ? "ok" : "bad", "HRIR virtualizer", c.eapo && hrirOk ? "Dolby Movie HRIR · binaural" : !c.eapo ? "Equalizer APO not on CABLE" : "7.1 config/HRIR missing"],
    [st.bridge_running ? "ok" : "warn", "Bridge", st.bridge_running ? "Running" : "Stopped"],
    [loop ? "bad" : dflt ? "ok" : "warn", "Headphones", loop ? "Default is CABLE Input (loop!)" : hp],
  ];
  $("surChain").innerHTML = nodes.map(([l, t, s]) => `<div class="node ${l}"><b><i></i>${esc(t)}</b><small>${esc(s)}</small></div>`).join("");

  $("surApps").innerHTML = apps.length ? apps.map((a) => `<span class="app-chip"><i></i>${esc(a.replace(/\.exe$/i, ""))}</span>`).join("")
    : `<p class="hint">No app is sent to CABLE Input yet. Music and video playing to your headphones stay stereo.</p>`;

  const fmt = (o, t, s) => `<div class="check ${o}"><i>${o === "ok" ? "✓" : o === "warn" ? "!" : "×"}</i><div><b>${esc(t)}</b><small>${esc(s)}</small></div></div>`;
  $("surChecks").innerHTML = [
    fmt(st.installed ? "ok" : "bad", "VB-CABLE installed", st.installed ? "CABLE Input and CABLE Output found" : "Run the installer in vendor\\VBCABLE"),
    fmt(!st.installed ? "bad" : is71 ? "ok" : "warn", "CABLE Input set to 7.1", is71 ? `8 channels · ${c.rate ? c.rate / 1000 + " kHz" : ""}` : "Sound settings → CABLE Input → Configure → 7.1 Surround"),
    fmt(c.eapo ? "ok" : "bad", "Equalizer APO on CABLE Input", c.eapo ? "Attached" : "Add CABLE Input in Equalizer APO's Configurator, then reboot"),
    fmt(v.configured ? "ok" : "bad", "7.1 virtualizer in config", v.configured ? "Runs only on 8-channel output" : "surround71.txt is not included"),
    fmt(hrirOk ? "ok" : "bad", "HRIR files", (v.hrir || []).length ? ((v.hrir_missing || []).length ? "Missing: " + v.hrir_missing.join(", ") : v.hrir.join(", ")) : "No sur_*.wav convolution found"),
    fmt(st.bridge_running ? "ok" : "warn", "Bridge running", st.bridge_running ? "CABLE Output → " + hp : "Turn it on with the switch above"),
    fmt(st.task ? "ok" : "warn", "Starts at logon", st.task ? `Task: ${st.task.status || "ready"}` : "Logon task not found"),
    fmt(loop ? "bad" : "ok", "Headphones are the default device", loop ? "Make your headphones the default, not CABLE Input" : hp),
  ].join("");
  renderSurTest();
}
function renderSurTest() {
  const t = S && S.task, run = !!(t && t.kind === "surround");
  const btn = $("surTest");
  btn.disabled = !!t || !SUR || !SUR.test_available || !SUR.installed;
  btn.textContent = run ? "Playing…" : "Play 7.1 test";
  let on = -1;
  if (run) on = Math.min(6, Math.floor(t.elapsed / (t.expected / 7)));
  document.querySelectorAll("#surRoom .spk").forEach((g) => g.classList.toggle("on", +g.dataset.i === on));
  $("surTestHint").textContent = run ? `Now: ${["front left", "center", "front right", "side right", "rear right", "rear left", "side left"][on]} · ${Math.round(t.elapsed)} / ~${t.expected} s`
    : SUR && !SUR.test_available ? "Test files missing in soundmode\\native" : !SUR || SUR.bridge_running ? "Noise moves around the 7 speakers" : "Turn the bridge on to hear it";
}

/* ------------------------------------------------------------------ events / toasts / log */
function toast(text, level = "info") {
  const el = document.createElement("div"); el.className = "toast " + level; el.textContent = text;
  $("toasts").appendChild(el);
  setTimeout(() => { el.classList.add("out"); setTimeout(() => el.remove(), 320); }, level === "warn" ? 7000 : 3800);
}
function addEvents(evs) {
  const log = $("log");
  for (const e of evs) {
    if (e.kind === "measure") { const c = $("mLog"); c.textContent += e.text + "\n"; c.scrollTop = c.scrollHeight; continue; }
    if (e.kind === "surround") setTimeout(() => loadSurround(true), 300);
    if (e.kind === "measure-done") { $("mLog").textContent += "\n" + e.text + "\n"; loadModes(); }
    if (log.querySelector(".empty")) log.innerHTML = "";
    const el = document.createElement("div"); el.className = "ev " + e.level;
    el.innerHTML = `<time>${e.time}</time><i></i><span>${esc(vi(e.text))}</span>`;
    log.prepend(el);
    if (e.kind !== "mode" && e.kind !== "power") toast(vi(e.text), e.level);
  }
}

/* ------------------------------------------------------------------ loop */
async function loadModes() { MODES = await call("modes"); render(); }
let polling = false;
async function poll() {
  if (polling) return; polling = true;
  try {
    const s = await call("state", cursor);
    if (busyMode && S) s.current = S.current;
    S = s;
    if (s.events.length) { cursor = s.events[s.events.length - 1].seq; addEvents(s.events); }
    render();
    if (!$("page-surround").hidden) { renderSurTest(); loadSurround(); }
  } catch (e) { console.error(e); }
  finally { polling = false; }
}

function bind() {
  document.querySelector(".nav").addEventListener("click", (e) => {
    const b = e.target.closest("button[data-page]"); if (!b) return;
    document.querySelectorAll(".nav button").forEach((x) => x.classList.toggle("on", x === b));
    document.querySelectorAll(".page").forEach((p) => (p.hidden = p.id !== "page-" + b.dataset.page));
    $("pageTitle").textContent = b.querySelector("span").textContent;
    if (b.dataset.page === "surround") loadSurround(true);
  });
  document.addEventListener("click", (e) => {
    const o = e.target.closest("[data-open]"); if (o) call("open", o.dataset.open);
  });
  $("profiles").addEventListener("click", (e) => {
    const b = e.target.closest(".prof"); if (!b) return;
    const k = b.dataset.prof;
    if (!groups()[k]) { document.querySelector('.nav button[data-page="measure"]').click(); if ($("mProfile").querySelector(`option[value="${k}"]`)) $("mProfile").value = k; return; }
    useMode(pick(k));
  });
  $("ieqs").addEventListener("click", (e) => {
    const b = e.target.closest(".ieq"); if (!b) return;
    const m = pick(view.profile, b.dataset.ieq);
    if (m) useMode(m);
    else { document.querySelector('.nav button[data-page="measure"]').click(); $("mProfile").value = view.profile; $("mIeq").value = b.dataset.ieq; }
  });
  $("variants").addEventListener("click", (e) => { const b = e.target.closest(".var"); if (b) useMode(byId(b.dataset.mode)); });
  $("power").addEventListener("change", async (e) => {
    S.active = e.target.checked; render();
    const r = await call("set_active", e.target.checked);
    if (!r.ok) {
      S.active = !e.target.checked; render();
      if (r.need_install && S.notice && S.notice.kind === "no-eapo") $("noticeBtn").click();   // offer the one-click install right away
      else toast(r.error, "warn");
    }
    poll();
  });
  $("noticeBtn").addEventListener("click", async (e) => {
    const kind = e.currentTarget.dataset.kind;
    if (kind === "no-eapo") {
      const s = (S.notice && S.notice.setup) || {};
      if (!s.installers) { toast("The installers are missing from vendor\\installers", "warn"); return; }
      const need = [!s.eapo && "<li><b>Equalizer APO 1.4.2</b> (the audio engine the modes run on)</li>", !s.hesuvi && "<li><b>HeSuVi 2.0</b> (the preset framework)</li>",
        !s.vst && "<li>The leveler plugins</li>", "<li>The app's HeSuVi files (old ones are backed up)</li>"].filter(Boolean).join("");
      const devs = await call("setup_devices");
      const ok = await confirmBox("Set up the sound modes",
        `<b>1. Pick the device to use them on</b>` + pickerHtml(devs, defaultPick(devs))
        + `<b>2. Installed for you</b> from the copies kept in this folder (checked against the official downloads):<ul>${need}</ul>`
        + `Windows asks for <b>administrator</b> permission once; everything else is automatic.`, "Install");
      const g = picked(), keep = keepOrig();
      if (!ok) return;
      const r = await call("install", g, keep); if (!r.ok) toast(r.error, "warn"); else toast("Installing… confirm the Windows prompt");
      poll(); return;
    }
    connectDevice(S.notice && S.notice.guid);
  });
  $("policy").addEventListener("click", async (e) => { const b = e.target.closest("button"); if (!b) return; S.policy = b.dataset.v; render(); await call("set_policy", b.dataset.v); });
  $("rescan").addEventListener("click", () => call("rescan"));
  $("devices").addEventListener("click", async (e) => {
    const c = e.target.closest("[data-connect]"), dt = e.target.closest("[data-detach]");
    if (c) connectDevice(c.dataset.connect);
    if (dt && await confirmBox("Disconnect the sound modes?", "Puts this device back exactly as it was before (the maker's effects return). Needs administrator permission once.", "Disconnect")) {
      const x = await call("detach", dt.dataset.detach); if (!x.ok) toast(x.error, "warn"); poll();
    }
    const f = e.target.closest("[data-fix]"), r = e.target.closest("[data-restore]");
    if (f) fixLayers(f.dataset.fix);
    if (r) { r.disabled = true; const x = await call("layers_restore", r.dataset.restore); if (!x.ok) toast(x.error, "warn"); poll(); }
  });
  $("bannerFix").addEventListener("click", (e) => { if (e.currentTarget.dataset.guid) fixLayers(e.currentTarget.dataset.guid); });
  $("nahimicBtn").addEventListener("click", (e) => nahimicAction(e.currentTarget.dataset.action));
  $("listen").addEventListener("click", async () => { const r = await call("listen"); if (!r.ok) toast(r.error, "warn"); else toast("Playing quiet noise for 5 s to check…"); poll(); });
  $("surPower").addEventListener("change", async (e) => {
    const on = e.target.checked; $("surPowerLabel").textContent = on ? "Starting…" : "Stopping…";
    const r = await call("surround_bridge", on); if (!r.ok) toast(r.error, "warn");
    setTimeout(() => loadSurround(true), 800);
  });
  $("surTest").addEventListener("click", async () => {
    const r = await call("surround_test"); if (!r.ok) toast(r.error, "warn"); else toast(`Playing the 7.1 sweep (~${r.seconds} s)…`);
    poll();
  });
  $("mStart").addEventListener("click", async () => {
    $("mLog").textContent = ""; mStart = Date.now();
    const r = await call("measure", $("mProfile").value, $("mIeq").value);
    if (!r.ok) { toast(r.error, "warn"); mStart = 0; }
    poll();
  });
}

async function boot() {
  bind();
  const opts = await call("measure_options").catch(() => ({ profiles: [], ieqs: [] }));
  $("mProfile").innerHTML = opts.profiles.map((p) => `<option value="${p}">${p}</option>`).join("");
  $("mIeq").innerHTML = opts.ieqs.map((p) => `<option value="${p}">${p}</option>`).join("");
  $("mProfile").value = "Music"; $("mIeq").value = "Balanced";
  drawRoom();
  await loadModes(); await poll();
  loadSurround(true);
  document.body.classList.remove("booting");
  setInterval(poll, 1000);
}

if (window.pywebview && window.pywebview.api) boot(); else window.addEventListener("pywebviewready", boot);
