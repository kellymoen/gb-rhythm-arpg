"use strict";
// Feel lab UI: generic descriptor-driven sliders, press/grade graph, record/replay controls.
const $ = (id) => document.getElementById(id);
const state = { tables: [], fields: {}, values: {}, status: {}, since: 0, baseline: 0, presses: [], windows: {}, dragging: null, latencyId: null };
const MAX_PRESSES = 64;

async function api(path, body) {
  const opt = body === undefined ? {} : { method: "POST", headers: { "X-Lab": "1", "Content-Type": "application/json" }, body: JSON.stringify(body) };
  const r = await fetch(path, opt);
  const j = await r.json();
  if (!r.ok) throw new Error(j.error || r.statusText);
  return j;
}
function say(text, err) { const m = $("msg"); m.textContent = text; m.className = err ? "err" : ""; clearTimeout(say.t); say.t = setTimeout(() => (m.textContent = ""), 6000); }
const guard = (fn) => async (...a) => { try { await fn(...a); } catch (e) { say(e.message, true); } };

// ---- sliders --------------------------------------------------------------------------------
function build(tables) {
  const root = $("tables"); root.innerHTML = "";
  for (const t of tables) {
    const wrap = document.createElement("div");
    const head = document.createElement("div"); head.className = "table-head";
    head.innerHTML = `<b>${t.name}</b><small>${t.source}</small>`;
    for (const [label, fn] of [["Save", () => api("/api/save", { table: t.name }).then((r) => say(`saved ${t.source}: ${r.saved[t.name] || 0} value(s) changed`))],
                               ["Reset", () => api("/api/reset", { table: t.name }).then(refresh)]]) {
      const b = document.createElement("button"); b.textContent = label; b.onclick = guard(fn); head.append(b);
    }
    wrap.append(head);
    const groups = new Map();
    for (const f of t.fields) {
      state.fields[f.id] = f;
      const g = f.path.slice(0, -1).join(".") || "(root)";
      if (!groups.has(g)) groups.set(g, []);
      groups.get(g).push(f);
      if (f.path.join(".") === "timing.latency_offset") state.latencyId = f.id;
    }
    for (const [g, fs] of groups) {
      const d = document.createElement("details"); d.open = groups.size <= 8 || g === "timing";
      d.innerHTML = `<summary>${g}</summary>`;
      fs.forEach((f) => d.append(fieldRow(f)));
      wrap.append(d);
    }
    root.append(wrap);
  }
}

function fieldRow(f) {
  const row = document.createElement("div"); row.className = "field" + (f.available ? "" : " disabled"); row.id = "row-" + f.id;
  const name = f.path[f.path.length - 1];
  let control;
  if (f.type === "enum") {
    control = document.createElement("select");
    for (const [k, v] of Object.entries(f.values)) control.add(new Option(k, v));
  } else {
    control = document.createElement("input"); control.type = "range"; control.min = f.min; control.max = f.max; control.step = 1;
  }
  control.id = "in-" + f.id; control.disabled = !f.available;
  const num = document.createElement("input"); num.className = "num"; num.type = "number"; num.min = f.min; num.max = f.max; num.id = "num-" + f.id; num.disabled = !f.available;
  const undo = document.createElement("button"); undo.className = "icon"; undo.textContent = "↺"; undo.title = "reset to default (" + f.default + ")";
  const label = document.createElement("label"); label.htmlFor = control.id; label.textContent = name; label.title = f.label + (f.restart ? " (needs ROM restart)" : "");
  if (f.restart) { const b = document.createElement("span"); b.className = "badge"; b.textContent = "restart"; label.append(" ", b); }
  const send = (v) => { v = Number(v); if (Number.isNaN(v)) return; state.values[f.id] = v; paint(f.id); api("/api/set", { id: f.id, value: v }).catch((e) => say(e.message, true)); };
  const begin = () => (state.dragging = f.id), end = () => (state.dragging = null);
  control.addEventListener("pointerdown", begin); control.addEventListener("focus", begin); control.addEventListener("blur", end);
  window.addEventListener("pointerup", end);
  control.oninput = () => send(control.value);
  num.onfocus = begin; num.onblur = end; num.onchange = () => send(Math.max(f.min, Math.min(f.max, Number(num.value))));
  undo.onclick = () => send(f.default);
  row.append(label, control, num, undo);
  if (f.doc) { const d = document.createElement("div"); d.className = "doc"; d.textContent = f.doc + (f.type === "enum" ? "" : `  [${f.min}..${f.max}]`); row.append(d); }
  return row;
}

function paint(id) {
  const f = state.fields[id], v = state.values[id];
  if (v === undefined) return;
  const c = $("in-" + id), n = $("num-" + id);
  if (c && document.activeElement !== c) c.value = v;
  if (n && document.activeElement !== n) n.value = v;
  $("row-" + id).classList.toggle("changed", v !== f.default);
}

async function refresh() {
  const j = await api("/api/values");
  if (state.dragging === null) { state.values = j.values; for (const id in j.values) paint(id); }
  status(j.status); replays(j.replays);
}

// ---- status, record, replay ------------------------------------------------------------------
function status(st) {
  state.status = st;
  const mode = $("mode"); mode.textContent = st.mode === "replay" ? `replay ${st.replay.frame}/${st.replay.total}` : st.mode === "recording" ? `recording ${st.recording_frames}f` : "live"; mode.className = "pill " + st.mode;
  const a = st.audio ? ` · audio ${st.audio.driver} q ${st.audio.queued_frames}f underruns ${st.audio.underruns}` : " · muted";
  $("status").textContent = `frame ${st.frame} · ${st.fps} fps${a}`;
  $("warnings").textContent = (st.warnings || []).join("  ");
  $("cancel-replay").hidden = st.mode !== "replay";
  $("rec-start").disabled = st.mode !== "live"; $("rec-stop").disabled = st.mode !== "recording";
  const r = st.replay_result, box = $("replay-result");
  if (r) { box.className = r.ok ? "ok" : "bad"; box.textContent = r.ok ? `${r.name}: matches the recording` : `${r.name}: MISMATCH\n` + r.mismatches.join("\n"); }
}
let lastReplays = "";
function replays(names) {
  if (JSON.stringify(names) === lastReplays) return; lastReplays = JSON.stringify(names);
  const ul = $("replays"); ul.innerHTML = names.length ? "" : '<li class="muted">no recordings yet</li>';
  for (const n of names) {
    const li = document.createElement("li"); li.innerHTML = `<span>${n}</span>`;
    const play = Object.assign(document.createElement("button"), { textContent: "Play" });
    play.onclick = guard(() => api("/api/replay", { name: n }));
    const chk = Object.assign(document.createElement("button"), { textContent: "Check headless" });
    chk.onclick = guard(async () => { say("checking " + n + "…"); const r = await api("/api/replay/check", { name: n }); const b = $("replay-result"); b.className = r.ok ? "ok" : "bad"; b.textContent = r.output; say(r.ok ? "replay matches" : "replay differs", !r.ok); });
    li.append(play, chk); ul.append(li);
  }
}
$("restart").onclick = guard(() => api("/api/restart", {}).then(() => say("ROM restarted")));
$("rec-start").onclick = guard(() => api("/api/record", { action: "start" }).then(() => say("recording from frame 0")));
$("rec-stop").onclick = guard(async () => {
  const name = $("rec-name").value.trim(); if (!name) throw new Error("type a replay name first");
  const r = await api("/api/record", { action: "stop", name }); say("saved " + r.saved);
});
$("save-all").onclick = guard(() => api("/api/save", {}).then((r) => say("saved: " + Object.entries(r.saved).map(([k, n]) => `${k} ${n} changed`).join(", "))));
$("reset-all").onclick = guard(() => api("/api/reset", {}).then(refresh));
$("cancel-replay").onclick = guard(() => api("/api/replay", { action: "cancel" }));

// ---- press graph -----------------------------------------------------------------------------
async function pollPresses() {
  try {
    const j = await api("/api/presses?after=" + state.since);
    state.since = j.seq; state.windows = j.windows;
    if (j.presses.length) { state.presses.push(...j.presses); state.presses = state.presses.slice(-400); }
    draw();
  } catch (e) { /* server gone */ }
}
$("clear-presses").onclick = () => { state.baseline = state.presses.length ? state.presses[state.presses.length - 1].seq : state.since; draw(); };

function draw() {
  const cv = $("graph"), g = cv.getContext("2d"), W = cv.width, H = cv.height, css = getComputedStyle(document.documentElement);
  const col = (n) => css.getPropertyValue(n).trim();
  const ps = state.presses.filter((p) => p.seq > state.baseline).slice(-MAX_PRESSES);
  const pw = state.windows.perfect ?? 3, gw = state.windows.good ?? 6;
  const R = Math.max(gw + 3, 8, ...ps.map((p) => Math.abs(p.frames) + 1));
  const L = 40, T = 10, B = 22, PW = W - L - 10, PH = H - T - B;
  const y = (v) => T + PH / 2 - (v / R) * (PH / 2);
  g.clearRect(0, 0, W, H); g.font = "11px system-ui"; g.textBaseline = "middle";
  g.fillStyle = col("--good-bg"); g.fillRect(L, y(gw), PW, y(-gw) - y(gw));
  g.fillStyle = col("--perfect-bg"); g.fillRect(L, y(pw), PW, y(-pw) - y(pw));
  g.strokeStyle = col("--line"); g.fillStyle = col("--muted"); g.textAlign = "right";
  for (let v = -R; v <= R; v += R > 12 ? 4 : 2) { g.beginPath(); g.moveTo(L, y(v)); g.lineTo(L + PW, y(v)); g.globalAlpha = v === 0 ? 1 : 0.4; g.stroke(); g.globalAlpha = 1; g.fillText((v > 0 ? "+" : "") + v, L - 6, y(v)); }
  g.textAlign = "left"; g.fillStyle = col("--muted"); g.fillText("late", L + 4, T + 6); g.fillText("early", L + 4, H - B - 6);
  g.textAlign = "center"; g.fillText("press (newest right) · frames from the beat slot", L + PW / 2, H - 7);
  const lat = state.latencyId ? state.values[state.latencyId] : undefined;
  const cur = lat === undefined ? ps : ps.filter((p) => p.windows.latency === undefined || p.windows.latency === lat);
  if (cur.length >= 2) { // mean +/- sd of presses graded under the current latency offset
    const mean = cur.reduce((s, p) => s + p.frames, 0) / cur.length;
    g.strokeStyle = col("--accent"); g.setLineDash([6, 4]); g.beginPath(); g.moveTo(L, y(mean)); g.lineTo(L + PW, y(mean)); g.stroke(); g.setLineDash([]);
  }
  const step = PW / MAX_PRESSES;
  ps.forEach((p, i) => {
    const x = L + step * (MAX_PRESSES - ps.length + i) + step / 2;
    g.fillStyle = col(p.grade === "PERFECT" ? "--perfect" : p.grade === "GOOD" ? "--good" : "--off");
    g.globalAlpha = cur.includes(p) ? 1 : 0.35;
    g.beginPath(); g.arc(x, y(Math.max(-R, Math.min(R, p.frames))), 4, 0, 7); g.fill(); g.globalAlpha = 1;
  });
  stats(cur, ps);
}

function stats(cur, all) {
  const el = $("stats");
  if (!all.length) { el.innerHTML = '<span class="hint muted">Press A or B in time with the music. Each press shows up here with its grade and how many frames off the beat slot it was.</span>'; return; }
  const n = cur.length, mean = n ? cur.reduce((s, p) => s + p.frames, 0) / n : 0;
  const sd = n > 1 ? Math.sqrt(cur.reduce((s, p) => s + (p.frames - mean) ** 2, 0) / (n - 1)) : 0;
  const pct = (g) => n ? Math.round((100 * cur.filter((p) => p.grade === g).length) / n) : 0;
  const sign = mean > 0.05 ? "late" : mean < -0.05 ? "early" : "centred";
  const lat = state.latencyId ? state.values[state.latencyId] : undefined;
  const sug = lat === undefined ? null : Math.round(lat + mean);
  el.innerHTML = `<div><b>${n}</b>presses at this latency</div><div><b>${mean >= 0 ? "+" : ""}${mean.toFixed(1)}f</b>mean (${sign})</div><div><b>±${sd.toFixed(1)}f</b>spread (sd)</div>` +
    `<div><b>${pct("PERFECT")}%</b>perfect</div><div><b>${pct("GOOD")}%</b>good</div><div><b>${pct("OFFBEAT")}%</b>offbeat</div>` +
    (sug !== null && n >= 8 && sug !== lat ? `<div class="hint">Mean error ${mean.toFixed(1)}f: try <button id="apply-lat">set latency_offset to ${sug}</button> (now ${lat}). Spread ±${sd.toFixed(1)}f is your consistency, which latency cannot fix.</div>` : "");
  const b = $("apply-lat"); if (b) b.onclick = guard(async () => { await api("/api/set", { id: state.latencyId, value: sug }); state.values[state.latencyId] = sug; paint(state.latencyId); });
}

// ---- screen mirror + virtual pad -------------------------------------------------------------
const held = new Set();
const sendHeld = () => api("/api/input", { held: [...held] }).catch(() => {});
document.querySelectorAll("#pad button").forEach((b) => {
  b.onpointerdown = (e) => { e.preventDefault(); b.setPointerCapture(e.pointerId); held.add(b.dataset.b); sendHeld(); };
  const up = () => { held.delete(b.dataset.b); sendHeld(); };
  b.onpointerup = up; b.onpointercancel = up;
});
let screenTimer = null;
$("show-screen").onchange = () => {
  $("screen-wrap").hidden = !$("show-screen").checked;
  clearInterval(screenTimer);
  if ($("show-screen").checked) screenTimer = setInterval(() => { $("screen").src = "/screen.png?" + Date.now(); }, 100);
};

// ---- boot ------------------------------------------------------------------------------------
(async () => {
  try {
    const j = await api("/api/state");
    state.tables = j.tables; build(j.tables); status(j.status); replays(j.replays);
    $("rec-help").title = "Replays are saved in " + j.replay_dir;
    if (!j.status.windowed) { $("show-screen").checked = true; $("show-screen").onchange(); }
    await refresh();
  } catch (e) { say(e.message, true); }
  setInterval(() => refresh().catch(() => {}), 400);
  setInterval(pollPresses, 150);
})();
