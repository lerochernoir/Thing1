// session_meter core: finds Claude Code sessions, runs the session_graph extractor,
// turns the result into meter readings and a compact ring graph. No Electron here,
// so all of it is testable with plain Node.
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { execFile } from "node:child_process";
import { promisify } from "node:util";
import { fileURLToPath, pathToFileURL } from "node:url";

const run = promisify(execFile);
const HERE = path.dirname(fileURLToPath(import.meta.url));
// Packaged app: session_graph is copied inside the bundle. Development: it sits next to this folder.
export const GRAPH_DIR = fs.existsSync(path.join(HERE, "session_graph", "extract.py"))
  ? path.join(HERE, "session_graph") : path.resolve(HERE, "../session_graph");
const { drawSVG } = await import(pathToFileURL(path.join(GRAPH_DIR, "render", "draw.mjs")).href);
export const PROJECTS = process.env.CLAUDE_PROJECTS_DIR || path.join(os.homedir(), ".claude", "projects");
export const STATE_DIR = process.env.SESSION_METER_HOME || path.join(os.homedir(), ".session_graph");
export const PYTHON = process.env.SESSION_METER_PYTHON || "python3";

export const RPM_WINDOW_MIN = 5;   // tool calls per minute, averaged over this window
export const RPM_MAX = 30;         // gauge full scale
export const RPM_REDLINE = 20;
export const LIVE_SECONDS = 90;    // "running" if anything happened this recently
export const SPARK_MIN = 30;       // sparkline length, minutes

// ---- sessions ---------------------------------------------------------------------
const TITLE_RE = /"aiTitle"\s*:\s*"((?:[^"\\]|\\.)*)"/g;

function readTitle(file, size) {
  // Titles are re-emitted through the log; the last one wins. Read only the tail.
  const n = Math.min(size, 256 * 1024);
  const fd = fs.openSync(file, "r");
  try {
    const buf = Buffer.alloc(n);
    fs.readSync(fd, buf, 0, n, size - n);
    let m, last = null;
    const s = buf.toString("utf8");
    TITLE_RE.lastIndex = 0;
    while ((m = TITLE_RE.exec(s))) last = m[1];
    return last ? JSON.parse(`"${last}"`) : null;
  } catch { return null; } finally { fs.closeSync(fd); }
}

export function listSessions(limit = 25, root = PROJECTS) {
  let projects = [];
  try { projects = fs.readdirSync(root, { withFileTypes: true }).filter((d) => d.isDirectory()); } catch { return []; }
  const out = [];
  for (const p of projects) {
    const dir = path.join(root, p.name);
    let files = [];
    try { files = fs.readdirSync(dir).filter((f) => f.endsWith(".jsonl")); } catch { continue; }
    for (const f of files) {
      const file = path.join(dir, f);
      let st;
      try { st = fs.statSync(file); } catch { continue; }
      out.push({ id: f.replace(/\.jsonl$/, ""), file, project: p.name.replace(/^-/, "").replace(/-/g, "/"),
                 mtime: st.mtimeMs, size: st.size });
    }
  }
  out.sort((a, b) => b.mtime - a.mtime);
  return out.slice(0, limit).map((s) => ({ ...s, title: readTitle(s.file, s.size) || path.basename(s.project) }));
}

// ---- extraction (the same extract.py the pipeline uses) ---------------------------
export async function extract(session) {
  const dir = path.join(STATE_DIR, session.id);
  fs.mkdirSync(dir, { recursive: true });
  const out = path.join(dir, "extract.json");
  await run(PYTHON, [path.join(GRAPH_DIR, "extract.py"), session.file, "-o", out], { timeout: 60000 });
  const data = JSON.parse(fs.readFileSync(out, "utf8"));
  const taggedPath = path.join(dir, "tagged.json");
  let tagged = null;
  try { tagged = JSON.parse(fs.readFileSync(taggedPath, "utf8")); } catch { /* not tagged yet */ }
  return { data, tagged };
}

// Keep this session's Relate store and the global store current (layer 1, plus layer 2 if tagged).
export async function syncRelate(session, tagged) {
  const dir = path.join(STATE_DIR, session.id);
  const stores = [path.join(dir, "graph.rl"), path.join(STATE_DIR, "global")];
  const rc = path.join(GRAPH_DIR, "run_cypher.py");
  for (const db of stores) {
    await run(PYTHON, [rc, "--db", db, path.join(GRAPH_DIR, "schema.cypher")], { timeout: 60000 });
    await run(PYTHON, [rc, "--db", db, path.join(GRAPH_DIR, "load.cypher"), "--params", path.join(dir, "extract.json")], { timeout: 120000 });
    if (tagged) await run(PYTHON, [rc, "--db", db, path.join(GRAPH_DIR, "layer2.cypher"), "--params", path.join(dir, "tagged.json")], { timeout: 120000 });
  }
  return stores;
}

// ---- graph.json shape, built straight from extract.json (+ tagged.json) -----------
export function toGraph(data, tagged) {
  const calls = data.tool_calls.map((c) => ({ id: c.id, turn_index: c.turn_index, tool: c.tool_name, ok: c.ok }));
  const tools = Object.entries(calls.reduce((m, c) => ((m[c.tool] = (m[c.tool] || 0) + 1), m), {}))
    .map(([name, n]) => ({ name, calls: n })).sort((a, b) => b.calls - a.calls || a.name.localeCompare(b.name));
  const fileMap = new Map(), skillMap = new Map();
  for (const c of data.tool_calls) {
    for (const p of c.files) {
      const f = fileMap.get(p) || { path: p, touches: 0, calls: [] };
      f.touches++; f.calls.push(c.id); fileMap.set(p, f);
    }
    if (c.skill) {
      const k = skillMap.get(c.skill) || { name: c.skill, calls: 0, call_ids: [] };
      k.calls++; k.call_ids.push(c.id); skillMap.set(c.skill, k);
    }
  }
  const t = tagged || { topics: [], decisions: [], questions: [] };
  return {
    session: { id: data.session.id, title: data.session.title, started: data.session.started },
    turns: data.turns.map((x) => ({ id: x.id, index: x.index, role: x.role })),
    tool_calls: calls, tools,
    files: [...fileMap.values()].sort((a, b) => b.touches - a.touches || a.path.localeCompare(b.path)),
    skills: [...skillMap.values()],
    topics: t.topics.map((x) => ({ slug: x.slug, turn_indexes: x.turn_indexes, confidence: x.confidence })),
    decisions: t.decisions.map((d) => ({ id: d.id, text: d.text, status: d.status, turn_index: d.turn_index })),
    supersedes: t.decisions.filter((d) => d.supersedes).map((d) => ({ src: d.id, dst: d.supersedes })),
    defers: t.decisions.filter((d) => d.defers).map((d) => ({ src: d.id, dst: d.defers })),
    questions: t.questions.map((q) => ({ id: q.id, text: q.text, status: q.status, raised_in: q.raised_in, resolved_in: q.resolved_in })),
  };
}

// ---- meter readings ---------------------------------------------------------------
export function meters(data, tagged, now = Date.now()) {
  const seen = (t) => Number.isFinite(t) && t <= now;
  const times = data.tool_calls.map((c) => Date.parse(c.timestamp)).filter(seen);
  const turnTimes = data.turns.map((t) => Date.parse(t.timestamp)).filter(seen);
  const last = Math.max(0, ...times, ...turnTimes);
  const recent = times.filter((t) => now - t <= RPM_WINDOW_MIN * 60000);
  const spark = Array.from({ length: SPARK_MIN }, (_, i) => {
    const hi = now - (SPARK_MIN - 1 - i) * 60000, lo = hi - 60000;
    return times.filter((t) => t > lo && t <= hi).length;
  });
  const failed = data.tool_calls.filter((c) => c.ok === false).length;
  const lastCall = data.tool_calls.length ? data.tool_calls[data.tool_calls.length - 1] : null;
  const live = last > 0 && now - last <= LIVE_SECONDS * 1000;
  return {
    rpm: Math.round((recent.length / RPM_WINDOW_MIN) * 10) / 10,
    rpmMax: RPM_MAX, rpmRedline: RPM_REDLINE,
    spark,
    calls: data.tool_calls.length,
    failed,
    errorRate: data.tool_calls.length ? failed / data.tool_calls.length : 0,
    turns: data.turns.length,
    humanTurns: data.turns.filter((t) => t.role === "human").length,
    peerTurns: data.turns.filter((t) => t.role === "peer_agent").length,
    files: data.files.length,
    openQuestions: tagged ? tagged.questions.filter((q) => q.status === "open").length : null,
    decisions: tagged ? tagged.decisions.length : null,
    lastActivity: last || null,
    live,
    nowTool: live && lastCall ? lastCall.tool_name : null,
  };
}

export function compactSVG(graph) {
  return drawSVG(graph, { compact: true });
}
