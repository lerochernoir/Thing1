// Dev preview: render the window's UI in headless Chromium with real data from this machine's
// newest Claude Code chat, through a stub of the preload bridge. Writes preview.png / preview-collapsed.png.
//   node test/preview.mjs [outDir]
import path from "node:path";
import { fileURLToPath } from "node:url";
import { createRequire } from "node:module";
import * as core from "../core.mjs";

const require = createRequire(import.meta.url);
const { chromium } = require("playwright");
const HERE = path.dirname(fileURLToPath(import.meta.url));
const out = process.argv[2] || HERE;

const sessions = core.listSessions();
if (!sessions.length) { console.error("no sessions under", core.PROJECTS); process.exit(1); }
const s = sessions[0];
const { data, tagged } = await core.extract(s);
const graph = core.toGraph(data, tagged);
const state = (collapsed) => ({
  sessions: sessions.map(({ id, title, project, mtime }) => ({ id, title, project, mtime })),
  current: { id: s.id, title: s.title, project: s.project }, follow: true, collapsed, corner: "top-right",
  meters: core.meters(data, tagged), svg: core.compactSVG(graph), error: null, tagged: !!tagged,
  sync: { state: "ok", at: Date.now() - 12000, error: null }, shortcut: "CommandOrControl+Shift+G",
});

const browser = await chromium.launch();
for (const collapsed of [false, true]) {
  const page = await browser.newPage({ viewport: { width: 340, height: collapsed ? 64 : 640 }, deviceScaleFactor: 2 });
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.addInitScript((st) => {
    window.meter = { onState: (fn) => setTimeout(() => fn(st), 0), send: () => {} };
    document.addEventListener("DOMContentLoaded", () => { document.documentElement.style.background = "linear-gradient(160deg,#2b3a4d,#4a3a5a)"; });
  }, state(collapsed));
  await page.goto("file://" + path.join(HERE, "..", "index.html"));
  await page.waitForTimeout(1200);
  const file = path.join(out, collapsed ? "preview-collapsed.png" : "preview.png");
  await page.screenshot({ path: file });
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth);
  console.log(file, errors.length ? errors : "no errors", overflow ? "OVERFLOW" : "fits");
}
await browser.close();
