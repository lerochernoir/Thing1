#!/usr/bin/env node
// Step 6b — draw one session graph (graph.json from query.py) as a radial SVG, plus a PNG via resvg.
//
//   node render/render.mjs out/<uuid>/graph.json out/<uuid>/graph.svg [out/<uuid>/graph.png]
//
// Layout:
//   ring    — turns clockwise from 12 o'clock, numbered blue circles joined by arrows
//             (filled = human, hollow = peer agent)
//   inside  — white Session at the centre, pink Tools on an inner circle (area ~ calls),
//             grey tool-call dots between their turn and their tool, green File squares,
//             purple Skill triangles, curved low-opacity edges
//   outside — orange Topics at the mean angle of their turns with radial labels,
//             Decision diamonds and Question squares at their turn, white SUPERSEDES /
//             DEFERS arrows, dashed amber decision-lineage arc
import fs from "node:fs";
import * as d3 from "d3";
import { Resvg } from "@resvg/resvg-js";

const [, , inPath, svgPath, pngPath] = process.argv;
if (!inPath || !svgPath) {
  console.error("usage: render.mjs graph.json out.svg [out.png]");
  process.exit(2);
}
const g = JSON.parse(fs.readFileSync(inPath, "utf8"));

// ---- palette & geometry -----------------------------------------------------------
const C = {
  bg: "#0d0f12", fg: "#e8ebef", dim: "#8b939c", faint: "#2a2f36",
  turn: "#4c8dff", session: "#ffffff", tool: "#ff6fae", call: "#8b939c",
  file: "#3ecf8e", skill: "#a77bff", topic: "#ff9a3c", accept: "#3ecf8e",
  reject: "#ff5c5c", defer: "#c3c9d0", question: "#ffc23c", lineage: "#ffc23c",
};
const W = 1600, H = 1700, CX = W / 2, CY = 805;
const R = 360;                // turn ring
const R_TOOL = 140;           // tools
const R_SKILL = 205;          // skills
const R_FILE = 262;           // files
const R_DQ = R + 52;          // decisions / questions band
const R_LINEAGE = R + 98;     // dashed lineage arc
const R_TOPIC = R + 178;      // topics
const FONT = "Inter, 'DejaVu Sans', Helvetica, Arial, sans-serif";
const TAU = Math.PI * 2;

const turns = g.turns;
const nT = Math.max(turns.length, 1);
const angleOfTurn = (i) => -Math.PI / 2 + (TAU * i) / nT; // clockwise from 12 o'clock
const pol = (r, a) => [CX + r * Math.cos(a), CY + r * Math.sin(a)];
const f1 = (x) => Math.round(x * 10) / 10;
const esc = (s) => String(s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");

function circMean(angles) {
  if (!angles.length) return -Math.PI / 2;
  const x = d3.sum(angles, Math.cos), y = d3.sum(angles, Math.sin);
  if (Math.abs(x) < 1e-9 && Math.abs(y) < 1e-9) return angles[0];
  return Math.atan2(y, x);
}
const norm = (a) => ((a % TAU) + TAU) % TAU;

// Push angles apart so circular neighbours keep at least `minSep` radians,
// moving each item as little as possible (iterative relaxation, re-sorted each pass).
function spread(items, minSep) {
  const n = items.length;
  if (n < 2) return items;
  const sep = Math.min(minSep, (TAU / n) * 0.98);
  items.forEach((it, i) => { it.a = norm(it.a) + i * 1e-6; });
  for (let it = 0; it < 500; it++) {
    items.sort((p, q) => norm(p.a) - norm(q.a));
    let moved = false;
    for (let i = 0; i < n; i++) {
      const p = items[i], q = items[(i + 1) % n];
      const gap = norm(q.a - p.a);
      if (gap < sep - 1e-6) {
        const push = (sep - gap) / 2 + 1e-4;
        p.a -= push; q.a += push; moved = true;
      }
    }
    if (!moved) break;
  }
  return items;
}

// Quadratic curve bowed toward the centre; returns path string and point at t.
function curve(p0, p1, bow = 0.18) {
  const mx = (p0[0] + p1[0]) / 2, my = (p0[1] + p1[1]) / 2;
  const cx = mx + (CX - mx) * bow, cy = my + (CY - my) * bow;
  const p = d3.path();
  p.moveTo(p0[0], p0[1]);
  p.quadraticCurveTo(cx, cy, p1[0], p1[1]);
  const at = (t) => [(1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * cx + t * t * p1[0],
                     (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * cy + t * t * p1[1]];
  return { d: p.toString(), at };
}

const out = [];
const layer = { edges: [], nodes: [], labels: [], top: [] };

// ---- ring ---------------------------------------------------------------------------
const rTurn = Math.max(5, Math.min(14, (Math.PI * R) / nT * 0.38));
const turnPos = new Map(turns.map((t) => [t.index, pol(R, angleOfTurn(t.index))]));
layer.edges.push(`<circle cx="${CX}" cy="${CY}" r="${R}" fill="none" stroke="${C.faint}" stroke-width="1"/>`);
for (let i = 0; i + 1 < turns.length; i++) {
  const a0 = angleOfTurn(turns[i].index), a1 = angleOfTurn(turns[i + 1].index);
  const pad = (rTurn + 3) / R;
  const arc = d3.arc()({ innerRadius: R, outerRadius: R, startAngle: a0 + Math.PI / 2 + pad,
                         endAngle: a1 + Math.PI / 2 - pad - 4 / R });
  layer.nodes.push(`<path d="${arc}" transform="translate(${CX},${CY})" fill="none" stroke="${C.turn}" stroke-width="1.6" stroke-opacity="0.85"/>`);
  const ea = a1 - pad, tip = pol(R, ea), back = pol(R, ea - 9 / R);
  const nx = Math.cos(ea), ny = Math.sin(ea);
  layer.nodes.push(`<polygon points="${f1(tip[0])},${f1(tip[1])} ${f1(back[0] + nx * 4)},${f1(back[1] + ny * 4)} ${f1(back[0] - nx * 4)},${f1(back[1] - ny * 4)}" fill="${C.turn}"/>`);
}
const labelEvery = rTurn >= 9 ? 1 : rTurn >= 6 ? 5 : 10;
for (const t of turns) {
  const [x, y] = turnPos.get(t.index);
  const human = t.role === "human";
  layer.top.push(`<circle cx="${f1(x)}" cy="${f1(y)}" r="${f1(rTurn)}" fill="${human ? C.turn : C.bg}" stroke="${C.turn}" stroke-width="2"><title>turn ${t.index} (${t.role})</title></circle>`);
  if (t.index % labelEvery === 0) {
    const fs_ = Math.max(8, Math.min(12, rTurn * 0.95));
    layer.top.push(`<text x="${f1(x)}" y="${f1(y + fs_ * 0.36)}" font-size="${f1(fs_)}" font-weight="600" text-anchor="middle" fill="${human ? "#0d0f12" : C.turn}">${t.index}</text>`);
  }
}

// ---- inside: session, tools, calls, files, skills -----------------------------------
layer.top.push(`<circle cx="${CX}" cy="${CY}" r="18" fill="${C.session}"><title>Session ${esc(g.session.id)}</title></circle>`);
layer.labels.push(`<text x="${CX}" y="${CY + 36}" font-size="11" text-anchor="middle" fill="${C.dim}">session</text>`);

const callsByTool = d3.group(g.tool_calls, (c) => c.tool);
const toolItems = g.tools.map((t) => ({
  name: t.name, calls: t.calls,
  a: circMean((callsByTool.get(t.name) || []).map((c) => angleOfTurn(c.turn_index))),
}));
spread(toolItems, 0.42);
const toolR = d3.scaleSqrt().domain([1, d3.max(toolItems, (t) => t.calls) || 1]).range([7, 26]);
const toolPos = new Map();
for (const t of toolItems) {
  const p = pol(R_TOOL, t.a);
  toolPos.set(t.name, p);
  layer.edges.push(`<path d="${curve([CX, CY], p, 0).d}" fill="none" stroke="${C.tool}" stroke-opacity="0.25" stroke-width="1"/>`);
}

const callPos = new Map();
const perPair = d3.group(g.tool_calls, (c) => `${c.turn_index}|${c.tool}`);
for (const [, list] of perPair) {
  list.forEach((c, k) => {
    const tp = turnPos.get(c.turn_index), op = toolPos.get(c.tool);
    if (!tp || !op) return;
    const n = list.length;
    // Many calls on one turn→tool pair fan out in a band: lanes across, steps along.
    const lanes = Math.min(7, Math.max(1, Math.ceil(Math.sqrt(n))));
    const steps = Math.ceil(n / lanes);
    const lane = k % lanes, step = Math.floor(k / lanes);
    const t = steps === 1 ? 0.5 : 0.28 + (0.44 * step) / (steps - 1);
    const base = curve(tp, op, 0.12).at(t);
    const dx = op[0] - tp[0], dy = op[1] - tp[1], len = Math.hypot(dx, dy) || 1;
    const off = (lane - (lanes - 1) / 2) * 7;
    const p = [base[0] - (dy / len) * off, base[1] + (dx / len) * off];
    callPos.set(c.id, p);
    layer.edges.push(`<path d="${curve(tp, p, 0.08).d}" fill="none" stroke="${C.turn}" stroke-opacity="0.18" stroke-width="0.8"/>`);
    layer.edges.push(`<path d="${curve(p, op, 0.08).d}" fill="none" stroke="${C.tool}" stroke-opacity="0.18" stroke-width="0.8"/>`);
    const err = c.ok === false;
    layer.nodes.push(`<circle cx="${f1(p[0])}" cy="${f1(p[1])}" r="2.6" fill="${C.call}" ${err ? `stroke="${C.reject}" stroke-width="1"` : ""}><title>${esc(c.tool)} (turn ${c.turn_index})${err ? " — error" : ""}</title></circle>`);
  });
}
for (const t of toolItems) {
  const [x, y] = toolPos.get(t.name);
  const r = toolR(t.calls);
  layer.top.push(`<circle cx="${f1(x)}" cy="${f1(y)}" r="${f1(r)}" fill="${C.tool}"><title>${esc(t.name)}: ${t.calls} calls</title></circle>`);
  const lx = x + Math.cos(t.a) * 0, ly = y + r + 13;
  const short = t.name.startsWith("mcp__") ? t.name.split("__").pop() : t.name; // mcp__server__tool -> tool
  layer.labels.push(`<text x="${f1(lx)}" y="${f1(ly)}" font-size="11" font-weight="600" text-anchor="middle" fill="${C.tool}">${esc(short)} ${t.calls}</text>`);
}

const MAX_FILES = 28;
const filesShown = g.files.slice(0, MAX_FILES);
const fileItems = filesShown.map((f) => ({
  ...f, a: circMean(f.calls.map((id) => g.tool_calls.find((c) => c.id === id)).filter(Boolean).map((c) => angleOfTurn(c.turn_index))),
}));
spread(fileItems, 0.2);
for (const f of fileItems) {
  const p = pol(R_FILE, f.a);
  for (const id of f.calls) {
    const cp = callPos.get(id);
    if (cp) layer.edges.push(`<path d="${curve(cp, p, 0.1).d}" fill="none" stroke="${C.file}" stroke-opacity="0.16" stroke-width="0.8"/>`);
  }
  const s = 5 + Math.min(5, Math.sqrt(f.touches));
  layer.nodes.push(`<rect x="${f1(p[0] - s)}" y="${f1(p[1] - s)}" width="${f1(2 * s)}" height="${f1(2 * s)}" fill="${C.file}"><title>${esc(f.path)} — ${f.touches} touches</title></rect>`);
  const base = f.path.replace(/\/+$/, "").split("/").pop() || f.path;
  const label = base.length > 22 ? base.slice(0, 21) + "…" : base;
  const right = Math.cos(f.a) >= 0;
  layer.labels.push(`<text x="${f1(p[0] + (right ? s + 4 : -s - 4))}" y="${f1(p[1] + 3.5)}" font-size="10" text-anchor="${right ? "start" : "end"}" fill="${C.file}">${esc(label)}</text>`);
}
if (g.files.length > MAX_FILES) {
  layer.labels.push(`<text x="${CX}" y="${CY + R_FILE + 30}" font-size="10" text-anchor="middle" fill="${C.dim}">+${g.files.length - MAX_FILES} more files</text>`);
}

const skillItems = g.skills.map((k) => ({
  ...k, a: circMean(k.call_ids.map((id) => g.tool_calls.find((c) => c.id === id)).filter(Boolean).map((c) => angleOfTurn(c.turn_index))),
}));
spread(skillItems, 0.3);
for (const k of skillItems) {
  const p = pol(R_SKILL, k.a);
  for (const id of k.call_ids) {
    const cp = callPos.get(id);
    if (cp) layer.edges.push(`<path d="${curve(cp, p, 0.1).d}" fill="none" stroke="${C.skill}" stroke-opacity="0.3" stroke-width="0.9"/>`);
  }
  const s = 8;
  layer.nodes.push(`<polygon points="${f1(p[0])},${f1(p[1] - s)} ${f1(p[0] + s * 0.95)},${f1(p[1] + s * 0.7)} ${f1(p[0] - s * 0.95)},${f1(p[1] + s * 0.7)}" fill="${C.skill}"><title>skill ${esc(k.name)}</title></polygon>`);
  layer.labels.push(`<text x="${f1(p[0])}" y="${f1(p[1] + s + 11)}" font-size="10" text-anchor="middle" fill="${C.skill}">${esc(k.name)}</text>`);
}

// ---- outside: decisions, questions, lineage, topics ---------------------------------
function diamond(x, y, s, status) {
  const pts = `${f1(x)},${f1(y - s)} ${f1(x + s)},${f1(y)} ${f1(x)},${f1(y + s)} ${f1(x - s)},${f1(y)}`;
  const style = {
    accepted: `fill="${C.accept}" stroke="${C.accept}" stroke-width="1.5"`,
    accepted_by_default: `fill="${C.bg}" stroke="${C.accept}" stroke-width="2"`,
    rejected: `fill="${C.bg}" stroke="${C.reject}" stroke-width="2"`,
    deferred: `fill="${C.bg}" stroke="${C.defer}" stroke-width="1.6" stroke-dasharray="3 2"`,
  }[status] || `fill="${C.bg}" stroke="${C.defer}" stroke-width="1.5"`;
  return `<polygon points="${pts}" ${style}/>`;
}
function qsquare(x, y, s, status) {
  return status === "open"
    ? `<rect x="${f1(x - s)}" y="${f1(y - s)}" width="${2 * s}" height="${2 * s}" fill="${C.question}"/>`
    : `<rect x="${f1(x - s)}" y="${f1(y - s)}" width="${2 * s}" height="${2 * s}" fill="${C.bg}" stroke="${C.question}" stroke-width="1.8"/>`;
}

// Stack decisions then questions radially at their turn's angle.
const markers = [
  ...g.decisions.map((d) => ({ kind: "d", ...d, ti: d.turn_index })),
  ...g.questions.map((q) => ({ kind: "q", ...q, ti: q.raised_in })),
];
const decPos = new Map();
const stacks = d3.group(markers, (m) => m.ti);
for (const [ti, list] of stacks) {
  const a = angleOfTurn(ti);
  list.forEach((m, k) => {
    const lanes = Math.ceil(list.length / 3);
    const lane = Math.floor(k / 3), slot = (k % 3) - 1;
    const r = R_DQ + lane * 24;
    const aa = a + slot * (24 / r) * (list.length > 1 ? 1 : 0);
    const [x, y] = pol(r, aa);
    if (m.kind === "d") {
      decPos.set(m.id, [x, y, aa, r]);
      layer.top.push(`<g><title>${esc(m.id)} (${m.status}): ${esc(m.text)}</title>${diamond(x, y, 8, m.status)}</g>`);
      layer.labels.push(`<text x="${f1(x)}" y="${f1(y - 11)}" font-size="9" font-weight="600" text-anchor="middle" fill="${C.fg}">${esc(m.id)}</text>`);
    } else {
      layer.top.push(`<g><title>${esc(m.id)} (${m.status}): ${esc(m.text)}</title>${qsquare(x, y, 6, m.status)}</g>`);
      layer.labels.push(`<text x="${f1(x)}" y="${f1(y - 9)}" font-size="9" font-weight="600" text-anchor="middle" fill="${C.question}">${esc(m.id)}</text>`);
    }
    void lanes;
  });
}
// connector from each marker band back to its turn
for (const ti of stacks.keys()) {
  const a = angleOfTurn(ti);
  const p0 = pol(R + rTurn + 2, a), p1 = pol(R_DQ - 10, a);
  layer.edges.push(`<line x1="${f1(p0[0])}" y1="${f1(p0[1])}" x2="${f1(p1[0])}" y2="${f1(p1[1])}" stroke="${C.dim}" stroke-opacity="0.35"/>`);
}

// Dashed amber lineage arc spanning decision order (clockwise).
if (g.decisions.length >= 2) {
  const angs = g.decisions.map((d) => angleOfTurn(d.turn_index));
  const a0 = Math.min(...angs), a1 = Math.max(...angs);
  const span = a1 - a0 < 0.05 ? 0.12 : a1 - a0;
  const arc = d3.arc()({ innerRadius: R_LINEAGE, outerRadius: R_LINEAGE,
                         startAngle: a0 + Math.PI / 2 - 0.03, endAngle: a0 + span + Math.PI / 2 + 0.03 });
  layer.edges.push(`<path d="${arc}" transform="translate(${CX},${CY})" fill="none" stroke="${C.lineage}" stroke-width="1.8" stroke-dasharray="6 5" stroke-opacity="0.85"/>`);
  for (const d of g.decisions) {
    const a = angleOfTurn(d.turn_index);
    const [x, y] = pol(R_LINEAGE, a);
    layer.edges.push(`<circle cx="${f1(x)}" cy="${f1(y)}" r="2.2" fill="${C.lineage}"/>`);
  }
}

// SUPERSEDES / DEFERS: white labelled arrows routed outside the ring — out from the
// source diamond, along an arc at their own radius, back in to the target diamond.
let relLane = 0;
function relArrow(src, dst, label, dashed) {
  const ps = decPos.get(src), pd = decPos.get(dst);
  if (!ps || !pd) return;
  const rr = R_LINEAGE + 16 + (relLane++ % 4) * 12;
  let as = ps[2], ad = pd[2];
  let delta = Math.atan2(Math.sin(ad - as), Math.cos(ad - as)); // shortest signed turn
  if (Math.abs(delta) < 0.06) { ad = as + (delta >= 0 ? 0.06 : -0.06); delta = ad - as; }
  const sweep = delta > 0 ? 1 : 0;
  const a1 = pol(rr, as), a2 = pol(rr, ad);
  const ex = pd[0] - a2[0], ey = pd[1] - a2[1], el = Math.hypot(ex, ey) || 1;
  const tx = pd[0] - (ex / el) * 10, ty = pd[1] - (ey / el) * 10;
  const d = `M${f1(ps[0])},${f1(ps[1])} L${f1(a1[0])},${f1(a1[1])} A${rr},${rr} 0 0 ${sweep} ${f1(a2[0])},${f1(a2[1])} L${f1(tx)},${f1(ty)}`;
  layer.top.push(`<path d="${d}" fill="none" stroke="#ffffff" stroke-width="1.4" stroke-linejoin="round" ${dashed ? 'stroke-dasharray="4 3"' : ""}/>`);
  const ux = ex / el, uy = ey / el;
  layer.top.push(`<polygon points="${f1(tx + ux * 2)},${f1(ty + uy * 2)} ${f1(tx - ux * 7 - uy * 4)},${f1(ty - uy * 7 + ux * 4)} ${f1(tx - ux * 7 + uy * 4)},${f1(ty - uy * 7 - ux * 4)}" fill="#ffffff"/>`);
  const am = as + delta / 2;
  const [lx, ly] = pol(rr + 8, am);
  const deg = (am * 180) / Math.PI + 90;
  const flip = Math.sin(am) > 0;
  layer.top.push(`<text x="${f1(lx)}" y="${f1(ly)}" font-size="9" font-weight="700" letter-spacing="0.06em" text-anchor="middle" dominant-baseline="central" fill="#ffffff" transform="rotate(${f1(flip ? deg + 180 : deg)} ${f1(lx)} ${f1(ly)})">${label}</text>`);
}
for (const e of g.supersedes) relArrow(e.src, e.dst, "SUPERSEDES", false);
for (const e of g.defers) relArrow(e.src, e.dst, "DEFERS", true);

// Topics: orange dots at mean turn angle, radial labels.
const topicItems = g.topics.map((t) => ({ ...t, a: circMean(t.turn_indexes.map(angleOfTurn)) }));
spread(topicItems, 0.075);
for (const t of topicItems) {
  const [x, y] = pol(R_TOPIC, t.a);
  for (const ti of t.turn_indexes) {
    const tp = turnPos.get(ti);
    if (tp) layer.edges.push(`<path d="${curve(tp, [x, y], -0.12).d}" fill="none" stroke="${C.topic}" stroke-opacity="0.16" stroke-width="0.9"/>`);
  }
  layer.top.push(`<circle cx="${f1(x)}" cy="${f1(y)}" r="${f1(4 + Math.min(4, Math.sqrt(t.turn_indexes.length)))}" fill="${C.topic}"><title>${esc(t.slug)}: turns ${t.turn_indexes.join(", ")}</title></circle>`);
  const deg = (t.a * 180) / Math.PI;
  const flip = Math.cos(t.a) < 0;
  const [lx, ly] = pol(R_TOPIC + 12, t.a);
  layer.labels.push(`<text x="${f1(lx)}" y="${f1(ly)}" font-size="11" fill="${C.topic}" dominant-baseline="central" text-anchor="${flip ? "end" : "start"}" transform="rotate(${f1(flip ? deg + 180 : deg)} ${f1(lx)} ${f1(ly)})">${esc(t.slug)}</text>`);
}

// ---- chrome: title, header key, legend, footer -------------------------------------
const counts = `${g.turns.length} turns · ${g.tool_calls.length} tool calls · ${g.topics.length} topics · ${g.decisions.length} decisions · ${g.questions.length} questions`;
const chrome = [];
chrome.push(`<text x="56" y="78" font-size="40" font-weight="700" fill="${C.fg}">One chat, as a graph</text>`);
chrome.push(`<text x="58" y="112" font-size="17" fill="${C.dim}">${esc(counts)}</text>`);
if (g.session.title) chrome.push(`<text x="58" y="138" font-size="13" fill="${C.dim}" fill-opacity="0.8">${esc(g.session.title)}</text>`);
const key = [["ring", "the conversation, turn by turn"], ["inside", "tool calls, tools, files"], ["outside", "topics, decisions, questions"]];
key.forEach(([k, v], i) => {
  chrome.push(`<text x="${W - 56}" y="${70 + i * 22}" font-size="14" text-anchor="end" fill="${C.dim}"><tspan fill="${C.fg}" font-weight="600">${k}</tspan> — ${v}</text>`);
});

// Legend: 13 marks, bottom-centre, two rows.
const legend = [
  ["human turn", (x, y) => `<circle cx="${x}" cy="${y}" r="7" fill="${C.turn}" stroke="${C.turn}" stroke-width="2"/>`],
  ["peer-agent turn", (x, y) => `<circle cx="${x}" cy="${y}" r="7" fill="${C.bg}" stroke="${C.turn}" stroke-width="2"/>`],
  ["session", (x, y) => `<circle cx="${x}" cy="${y}" r="7" fill="${C.session}"/>`],
  ["tool (size = calls)", (x, y) => `<circle cx="${x}" cy="${y}" r="7" fill="${C.tool}"/>`],
  ["tool call", (x, y) => `<circle cx="${x}" cy="${y}" r="3" fill="${C.call}"/>`],
  ["file", (x, y) => `<rect x="${x - 6}" y="${y - 6}" width="12" height="12" fill="${C.file}"/>`],
  ["skill", (x, y) => `<polygon points="${x},${y - 8} ${x + 7.6},${y + 5.6} ${x - 7.6},${y + 5.6}" fill="${C.skill}"/>`],
  ["topic", (x, y) => `<circle cx="${x}" cy="${y}" r="5.5" fill="${C.topic}"/>`],
  ["decision · accepted", (x, y) => diamond(x, y, 8, "accepted")],
  ["accepted by default", (x, y) => diamond(x, y, 8, "accepted_by_default")],
  ["rejected", (x, y) => diamond(x, y, 8, "rejected")],
  ["deferred", (x, y) => diamond(x, y, 8, "deferred")],
  ["question · open / resolved", (x, y) => qsquare(x - 8, y, 6, "open") + qsquare(x + 8, y, 6, "resolved")],
];
const rows = [legend.slice(0, 7), legend.slice(7)];
const LY = H - 158;
chrome.push(`<line x1="${W / 2 - 560}" y1="${LY - 36}" x2="${W / 2 + 560}" y2="${LY - 36}" stroke="${C.faint}"/>`);
rows.forEach((row, ri) => {
  const widths = row.map(([label]) => 34 + label.length * 6.6 + 26);
  const total = d3.sum(widths);
  let x = W / 2 - total / 2;
  row.forEach(([label, mark], i) => {
    const mx = x + (label.startsWith("question") ? 16 : 10), y = LY + ri * 40;
    chrome.push(mark(mx, y));
    chrome.push(`<text x="${f1(x + (label.startsWith("question") ? 34 : 24))}" y="${y + 4.5}" font-size="13" fill="${C.fg}">${esc(label)}</text>`);
    x += widths[i];
  });
});
// Edge legend row (relationships drawn outside the ring).
chrome.push(`<text x="${W / 2}" y="${LY + 86}" font-size="12" text-anchor="middle" fill="${C.dim}">white arrows — SUPERSEDES (solid) / DEFERS (dashed)   ·   dashed amber arc — decision lineage   ·   red ring on a tool call — error</text>`);
chrome.push(`<text x="${W / 2}" y="${H - 34}" font-size="13" text-anchor="middle" fill="${C.dim}">Built with Relate + Claude Code</text>`);

const svg = `<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" font-family="${FONT}">
<title>One chat, as a graph — ${esc(g.session.id)}</title>
<rect width="${W}" height="${H}" fill="${C.bg}"/>
<g id="edges">${layer.edges.join("\n")}</g>
<g id="nodes">${layer.nodes.join("\n")}</g>
<g id="labels">${layer.labels.join("\n")}</g>
<g id="top">${layer.top.join("\n")}</g>
<g id="chrome">${chrome.join("\n")}</g>
</svg>
`;
fs.writeFileSync(svgPath, svg);
console.error(`[render] ${svgPath}`);
if (pngPath) {
  const png = new Resvg(svg, {
    fitTo: { mode: "width", value: W },
    font: { loadSystemFonts: true, defaultFontFamily: "DejaVu Sans" },
    background: C.bg,
  }).render().asPng();
  fs.writeFileSync(pngPath, png);
  console.error(`[render] ${pngPath}`);
}
