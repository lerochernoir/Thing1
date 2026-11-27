// session_meter — a small always-on-top window, anchored to a screen corner, that shows
// the Claude Code session you are in as an engine meter plus its ring graph.
//
//   npm start            (from this folder, after setup — see README.md)
//
// Toggle with the menu-bar icon or ⌘⇧G. Switch chats with the arrows; the pin keeps it
// following whichever chat was written to most recently.
import { app, BrowserWindow, Tray, Menu, globalShortcut, ipcMain, screen, shell, nativeImage } from "electron";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import * as core from "./core.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
// Launched from Finder or at login, an app gets a bare PATH. Keep the system python3 first
// (that is where `pip3 install --user relate-db` put Relate), then the usual Homebrew places.
if (app.isPackaged) process.env.PATH = [process.env.PATH, "/usr/bin", "/opt/homebrew/bin", "/usr/local/bin"].filter(Boolean).join(":");
const SETTINGS = path.join(core.STATE_DIR, "meter.json");
const SIZE = { w: 340, h: 640, collapsedH: 64 };
const MARGIN = 14;

let settings = { corner: "top-right", follow: true, relateSync: true, collapsed: false, shortcut: "CommandOrControl+Shift+G" };
try { settings = { ...settings, ...JSON.parse(fs.readFileSync(SETTINGS, "utf8")) }; } catch { /* first run */ }
const save = () => { try { fs.mkdirSync(core.STATE_DIR, { recursive: true }); fs.writeFileSync(SETTINGS, JSON.stringify(settings, null, 1)); } catch {} };

let win, tray;
let sessions = [];
let current = null;          // session object being shown
let snapshot = null;         // { data, tagged, graph, svg }
let lastStat = "";           // size:mtime of the current file, to detect writes
let extracting = false, pendingExtract = false;
let sync = { state: settings.relateSync ? "waiting" : "off", at: null, error: null };
let syncTimer = null;

// ---- window -------------------------------------------------------------------------
function anchor() {
  const { x, y, width, height } = screen.getPrimaryDisplay().workArea;
  const h = settings.collapsed ? SIZE.collapsedH : SIZE.h;
  const left = settings.corner.endsWith("left") ? x + MARGIN : x + width - SIZE.w - MARGIN;
  const top = settings.corner.startsWith("top") ? y + MARGIN : y + height - h - MARGIN;
  win.setBounds({ x: left, y: top, width: SIZE.w, height: h }, false);
}

function createWindow() {
  win = new BrowserWindow({
    width: SIZE.w, height: SIZE.h, show: false, frame: false, transparent: true, resizable: false,
    hasShadow: true, alwaysOnTop: true, skipTaskbar: true, fullscreenable: false,
    vibrancy: "hud", visualEffectState: "active", backgroundColor: "#00000000",
    webPreferences: { preload: path.join(HERE, "preload.cjs"), contextIsolation: true, sandbox: true },
  });
  win.setAlwaysOnTop(true, "floating");
  win.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true });
  win.loadFile(path.join(HERE, "index.html"));
  win.once("ready-to-show", () => { anchor(); win.showInactive(); push(); });
}

function toggle() {
  if (!win) return;
  if (win.isVisible()) win.hide(); else { anchor(); win.showInactive(); }
}

// ---- data loop ------------------------------------------------------------------------
function refreshSessions() {
  sessions = core.listSessions();
  if (!sessions.length) { current = null; return; }
  if (settings.follow || !current || !sessions.some((s) => s.id === current.id)) {
    if (!current || current.id !== sessions[0].id) select(sessions[0], false);
  } else {
    current = sessions.find((s) => s.id === current.id);
  }
}

function select(s, manual) {
  current = s; snapshot = null; lastStat = "";
  if (manual) { settings.follow = false; save(); }
  tick();
}

async function doExtract() {
  if (!current) return;
  if (extracting) { pendingExtract = true; return; }
  extracting = true;
  const s = current;
  try {
    const { data, tagged } = await core.extract(s);
    if (current?.id !== s.id) return;
    const graph = core.toGraph(data, tagged);
    snapshot = { data, tagged, graph, svg: core.compactSVG(graph), error: null };
    scheduleSync(s, tagged);
  } catch (e) {
    snapshot = { ...(snapshot || {}), error: String(e.message || e).split("\n")[0] };
  } finally {
    extracting = false;
    push();
    if (pendingExtract) { pendingExtract = false; doExtract(); }
  }
}

function scheduleSync(s, tagged) {
  if (!settings.relateSync) { sync = { state: "off", at: null, error: null }; return; }
  clearTimeout(syncTimer);
  // Debounced: a busy session writes every few seconds; Relate only needs to catch up.
  syncTimer = setTimeout(async () => {
    sync = { ...sync, state: "syncing" }; push();
    try { await core.syncRelate(s, tagged); sync = { state: "ok", at: Date.now(), error: null }; }
    catch (e) { sync = { state: "error", at: Date.now(), error: String(e.stderr || e.message || e).trim().split("\n").pop() }; }
    push();
  }, 20000);
}

function tick() {
  if (!current) { push(); return; }
  let st = "";
  try { const f = fs.statSync(current.file); st = `${f.size}:${f.mtimeMs}`; } catch { st = "gone"; }
  const subDir = current.file.replace(/\.jsonl$/, "") + "/subagents";
  try { for (const f of fs.readdirSync(subDir)) { const s2 = fs.statSync(path.join(subDir, f)); st += `|${s2.size}`; } } catch {}
  if (st !== lastStat) { lastStat = st; doExtract(); } else push();
}

function push() {
  if (!win || win.isDestroyed()) return;
  const m = snapshot?.data ? core.meters(snapshot.data, snapshot.tagged) : null;
  win.webContents.send("state", {
    sessions: sessions.map(({ id, title, project, mtime }) => ({ id, title, project, mtime })),
    current: current ? { id: current.id, title: current.title, project: current.project } : null,
    follow: settings.follow, collapsed: settings.collapsed, corner: settings.corner,
    meters: m, svg: snapshot?.svg || null, error: snapshot?.error || null,
    tagged: !!snapshot?.tagged, sync, shortcut: settings.shortcut,
  });
}

// ---- renderer requests ----------------------------------------------------------------
ipcMain.on("cmd", (_e, cmd, arg) => {
  const i = sessions.findIndex((s) => s.id === current?.id);
  if (cmd === "prev" && sessions.length) select(sessions[(i + 1) % sessions.length], true);      // older
  if (cmd === "next" && sessions.length) select(sessions[(i - 1 + sessions.length) % sessions.length], true); // newer
  if (cmd === "pick") { const s = sessions.find((x) => x.id === arg); if (s) select(s, true); }
  if (cmd === "follow") { settings.follow = !settings.follow; save(); refreshSessions(); tick(); }
  if (cmd === "collapse") { settings.collapsed = !settings.collapsed; save(); anchor(); push(); }
  if (cmd === "reveal" && current) shell.showItemInFolder(current.file);
  if (cmd === "hide") win.hide();
});

function buildTrayMenu() {
  const corners = ["top-right", "top-left", "bottom-right", "bottom-left"];
  return Menu.buildFromTemplate([
    { label: `Show / hide (${settings.shortcut.replace("CommandOrControl", "⌘").replace("Shift", "⇧").replace(/\+/g, "")})`, click: toggle },
    { type: "separator" },
    ...corners.map((c) => ({ label: `Anchor ${c.replace("-", " ")}`, type: "radio", checked: settings.corner === c,
                             click: () => { settings.corner = c; save(); anchor(); } })),
    { type: "separator" },
    { label: "Follow the latest chat", type: "checkbox", checked: settings.follow, click: () => ipcMain.emit("cmd", null, "follow") },
    { label: "Keep Relate in sync", type: "checkbox", checked: settings.relateSync,
      click: () => { settings.relateSync = !settings.relateSync; save(); sync = { state: settings.relateSync ? "waiting" : "off", at: null, error: null }; lastStat = ""; tick(); } },
    { label: "Open at login", type: "checkbox", checked: app.getLoginItemSettings().openAtLogin,
      click: (item) => app.setLoginItemSettings({ openAtLogin: item.checked }) },
    { label: "Open data folder", click: () => shell.openPath(core.STATE_DIR) },
    { type: "separator" },
    { label: "Quit", role: "quit" },
  ]);
}

app.whenReady().then(() => {
  if (process.platform === "darwin") app.dock?.hide();
  tray = new Tray(nativeImage.createEmpty());
  tray.setTitle("◉");
  tray.setToolTip("Session meter");
  tray.on("click", toggle);
  tray.on("right-click", () => tray.popUpContextMenu(buildTrayMenu()));
  tray.setContextMenu(buildTrayMenu());
  globalShortcut.register(settings.shortcut, toggle);
  createWindow();
  refreshSessions();
  setInterval(tick, 2000);             // watch the current transcript
  setInterval(() => { refreshSessions(); tray.setContextMenu(buildTrayMenu()); }, 10000);
  setInterval(push, 5000);             // time-based readings (rpm window, idle clock)
  screen.on("display-metrics-changed", anchor);
});
app.on("will-quit", () => globalShortcut.unregisterAll());
app.on("window-all-closed", (e) => e.preventDefault());
