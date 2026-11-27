// Core logic against the session_graph synthetic fixture, laid out like ~/.claude/projects.
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const FIX = path.resolve(HERE, "../../session_graph/tests/fixtures/synthetic");
const SID = "5e55a0e0-0000-4000-8000-00000000f107";
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "meter-"));
const projects = path.join(tmp, "projects"), proj = path.join(projects, "-work-app");
fs.mkdirSync(proj, { recursive: true });
fs.cpSync(path.join(FIX, `${SID}.jsonl`), path.join(proj, `${SID}.jsonl`));
fs.cpSync(path.join(FIX, SID), path.join(proj, SID), { recursive: true });
fs.writeFileSync(path.join(proj, "older.jsonl"), '{"type":"ai-title","aiTitle":"Older chat"}\n');
fs.utimesSync(path.join(proj, "older.jsonl"), new Date(2020, 0, 1), new Date(2020, 0, 1));
process.env.SESSION_METER_HOME = path.join(tmp, "state");
const core = await import("../core.mjs");

test("lists sessions newest first with titles", () => {
  const s = core.listSessions(10, projects);
  assert.deepEqual(s.map((x) => x.id), [SID, "older"]);
  assert.equal(s[0].title, "Radial graph for a coding session");
  assert.equal(s[1].title, "Older chat");
  assert.equal(s[0].project, "work/app");
});

test("extracts, builds the graph and reads the meters", async () => {
  const [s] = core.listSessions(10, projects);
  const tagged = JSON.parse(fs.readFileSync(path.resolve(FIX, "../synthetic.tagged.json"), "utf8"));
  fs.mkdirSync(path.join(core.STATE_DIR, SID), { recursive: true });
  fs.writeFileSync(path.join(core.STATE_DIR, SID, "tagged.json"), JSON.stringify(tagged));
  const { data, tagged: t } = await core.extract(s);
  assert.ok(t);
  const g = core.toGraph(data, t);
  assert.equal(g.turns.length, 11);
  assert.equal(g.tool_calls.length, 18);
  assert.equal(g.tools[0].name, "Bash");
  assert.equal(g.supersedes.length, 2);
  const svg = core.compactSVG(g);
  assert.match(svg, /^<svg /);
  assert.doesNotMatch(svg, /id="chrome"/); // compact: no title, key or legend

  // Fixture calls run every 34 s from 09:00:17Z; 5 min after the 14th call there are a known number in the window.
  const now = Date.parse("2026-11-20T09:08:00Z");
  const m = core.meters(data, t, now);
  const inWindow = data.tool_calls.filter((c) => now - Date.parse(c.timestamp) <= 300000 && Date.parse(c.timestamp) <= now).length;
  assert.equal(m.rpm, Math.round((inWindow / 5) * 10) / 10);
  assert.equal(m.failed, 1);
  assert.equal(m.turns, 11);
  assert.equal(m.humanTurns, 9);
  assert.equal(m.openQuestions, 1);
  assert.equal(m.spark.length, 30);
  assert.equal(m.spark.reduce((a, b) => a + b, 0), data.tool_calls.filter((c) => Date.parse(c.timestamp) <= now).length);
  assert.equal(core.meters(data, null, now + 3600000).live, false);
  assert.equal(core.meters(data, null).openQuestions, null);
});

test("syncs layer 1 and layer 2 into Relate", async () => {
  const [s] = core.listSessions(10, projects);
  const { tagged } = await core.extract(s);
  const stores = await core.syncRelate(s, tagged);
  assert.ok(fs.existsSync(stores[0]) && fs.existsSync(stores[1]));
});
