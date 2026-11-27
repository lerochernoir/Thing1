// Renderer: draws the meter from the state the main process pushes. No Node access here.
{
const $ = (id) => document.getElementById(id);
const NS = "http://www.w3.org/2000/svg";
const A0 = -110, A1 = 110;   // tachometer sweep, degrees from 12 o'clock

function polar(cx, cy, r, deg) {
  const a = (deg - 90) * Math.PI / 180;
  return [cx + r * Math.cos(a), cy + r * Math.sin(a)];
}
function arc(cx, cy, r, d0, d1) {
  const [x0, y0] = polar(cx, cy, r, d0), [x1, y1] = polar(cx, cy, r, d1);
  return `M${x0.toFixed(1)},${y0.toFixed(1)} A${r},${r} 0 ${d1 - d0 > 180 ? 1 : 0} 1 ${x1.toFixed(1)},${y1.toFixed(1)}`;
}

// ---- tachometer, built once; the needle rotates ------------------------------------
let tachMax = 30, tachRed = 20;
function buildTach(max, red) {
  tachMax = max; tachRed = red;
  const cx = 150, cy = 112, r = 100;
  const deg = (v) => A0 + (A1 - A0) * (v / max);
  let s = `<path d="${arc(cx, cy, r, A0, A1)}" fill="none" stroke="rgba(255,255,255,.12)" stroke-width="10" stroke-linecap="round"/>`;
  s += `<path d="${arc(cx, cy, r, deg(red), A1)}" fill="none" stroke="#ff5c5c" stroke-width="10" stroke-linecap="round" opacity=".85"/>`;
  s += `<path id="fill" d="" fill="none" stroke="#ff6fae" stroke-width="10" stroke-linecap="round"/>`;
  for (let v = 0; v <= max; v += 1) {
    const major = v % 5 === 0;
    const [x0, y0] = polar(cx, cy, r - 12, deg(v)), [x1, y1] = polar(cx, cy, r - (major ? 22 : 17), deg(v));
    s += `<line x1="${x0.toFixed(1)}" y1="${y0.toFixed(1)}" x2="${x1.toFixed(1)}" y2="${y1.toFixed(1)}" stroke="${v >= red ? "#ff5c5c" : "rgba(255,255,255,.45)"}" stroke-width="${major ? 2 : 1}"/>`;
    if (major) {
      const [tx, ty] = polar(cx, cy, r - 33, deg(v));
      s += `<text x="${tx.toFixed(1)}" y="${(ty + 4).toFixed(1)}" font-size="11" text-anchor="middle" fill="${v >= red ? "#ff5c5c" : "#98a2ad"}">${v}</text>`;
    }
  }
  s += `<g id="needle" style="transform-origin:${cx}px ${cy}px;transform:rotate(${A0}deg)"><line x1="${cx}" y1="${cy}" x2="${cx}" y2="${cy - r + 16}" stroke="#eef1f5" stroke-width="3" stroke-linecap="round"/></g>`;
  s += `<circle cx="${cx}" cy="${cy}" r="7" fill="#eef1f5"/>`;
  $("tach").innerHTML = s;
}
buildTach(30, 20);

function setTach(v) {
  const c = Math.max(0, Math.min(tachMax, v));
  const d = A0 + (A1 - A0) * (c / tachMax);
  document.getElementById("needle").style.transform = `rotate(${d}deg)`;
  document.getElementById("fill").setAttribute("d", c > 0.05 ? arc(150, 112, 100, A0, d) : "");
}

// Small half-dial: fraction 0..1 filled in a colour.
function dial(id, frac, color) {
  const f = Math.max(0, Math.min(1, frac || 0));
  const d = -90 + 180 * f;
  $(id).innerHTML = `<path d="${arc(22, 24, 18, -90, 90)}" fill="none" stroke="rgba(255,255,255,.14)" stroke-width="5" stroke-linecap="round"/>` +
    (f > 0.01 ? `<path d="${arc(22, 24, 18, -90, d)}" fill="none" stroke="${color}" stroke-width="5" stroke-linecap="round"/>` : "");
}

function ago(ms) {
  const s = Math.max(0, Math.round((Date.now() - ms) / 1000));
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.round(s / 60)}m ago`;
  if (s < 86400) return `${Math.round(s / 3600)}h ago`;
  return `${Math.round(s / 86400)}d ago`;
}

function render(st) {
  document.body.classList.toggle("collapsed", !!st.collapsed);
  $("follow").setAttribute("aria-pressed", String(!!st.follow));
  $("collapse").textContent = st.collapsed ? "+" : "–";
  if (!st.current) {
    $("title").textContent = "No Claude Code chats found";
    $("proj").textContent = "Looking in ~/.claude/projects";
    return;
  }
  $("title").textContent = st.current.title || st.current.id;
  $("proj").textContent = `${st.current.project} · ${st.current.id.slice(0, 8)}`;

  const sel = $("pick");
  const key = st.sessions.map((s) => s.id + s.title).join("|");
  if (sel.dataset.key !== key) {
    sel.dataset.key = key;
    sel.replaceChildren(...st.sessions.map((s) => {
      const o = document.createElement("option");
      o.value = s.id;
      o.textContent = `${s.title || s.id.slice(0, 8)} — ${ago(s.mtime)}`;
      return o;
    }));
  }
  sel.value = st.current.id;

  const m = st.meters;
  if (st.error && !m) { $("now").textContent = `Could not read this chat: ${st.error}`; return; }
  if (!m) { $("now").textContent = "Reading…"; return; }
  if (m.rpmMax !== tachMax || m.rpmRedline !== tachRed) buildTach(m.rpmMax, m.rpmRedline);

  $("lamp").classList.toggle("live", m.live);
  $("rpm").textContent = m.rpm.toFixed(1);
  $("miniRpm").textContent = `${m.rpm.toFixed(1)}/min`;
  setTach(m.rpm);

  dial("dErr", m.errorRate * 4, m.errorRate > 0.1 ? "#ff5c5c" : "#ffc23c");       // full at 25%
  $("vErr").textContent = m.calls ? `${Math.round(m.errorRate * 100)}%` : "–";
  dial("dTurn", m.turns ? m.humanTurns / m.turns : 0, "#4c8dff");                   // share typed by you
  $("vTurn").textContent = m.turns;
  dial("dFile", Math.min(1, m.files / 50), "#3ecf8e");
  $("vFile").textContent = m.files;
  dial("dQ", m.openQuestions == null ? 0 : Math.min(1, m.openQuestions / 5), "#ffc23c");
  $("vQ").textContent = m.openQuestions == null ? "–" : m.openQuestions;
  $("dQ").parentElement.title = m.openQuestions == null ? "Not tagged yet: run build.sh with an API key" : "";

  const peak = Math.max(1, ...m.spark);
  $("spark").replaceChildren(...m.spark.map((n) => {
    const i = document.createElement("i");
    i.style.height = `${(100 * n / peak).toFixed(0)}%`;
    i.title = `${n} call${n === 1 ? "" : "s"}`;
    return i;
  }));
  $("calls").textContent = `${m.calls} calls · ${m.failed} failed`;

  // The ring SVG is generated locally by draw.mjs, which escapes every label it writes.
  if (st.svg && $("ring").dataset.svg !== st.svg) { $("ring").innerHTML = st.svg; $("ring").dataset.svg = st.svg; }

  $("now").textContent = m.live ? `Running · ${m.nowTool || "thinking"} · ${ago(m.lastActivity)}` :
    m.lastActivity ? `Idle · last activity ${ago(m.lastActivity)}` : "No activity yet";
  const sy = st.sync || {};
  const syncEl = $("sync");
  syncEl.className = sy.state === "ok" ? "ok" : sy.state === "error" ? "err" : "";
  syncEl.textContent = sy.state === "ok" ? `Relate ✓ ${ago(sy.at)}` : sy.state === "syncing" ? "Relate syncing…" :
    sy.state === "error" ? "Relate error" : sy.state === "off" ? "Relate off" : "Relate pending";
  syncEl.title = sy.error || "";
}

const api = window.meter;
if (api) {
  api.onState(render);
  $("older").onclick = () => api.send("prev");
  $("newer").onclick = () => api.send("next");
  $("follow").onclick = () => api.send("follow");
  $("collapse").onclick = () => api.send("collapse");
  $("pick").onchange = (e) => api.send("pick", e.target.value);
  $("title").ondblclick = () => api.send("reveal");
}
}
