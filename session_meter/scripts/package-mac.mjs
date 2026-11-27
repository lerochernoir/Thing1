// Build "Session Meter.app" from this folder and install it in ~/Applications.
//
//   npm run package            (on the Mac; takes about a minute)
//
// The app bundles its own copy of the session_graph scripts (extract.py, the Cypher files,
// draw.mjs), so it keeps working wherever this checkout moves. It still uses the Mac's
// python3 with relate-db installed (pip3 install -r ../session_graph/requirements.txt).
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { packager } from "@electron/packager";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(HERE, "..");
const GRAPH = path.resolve(ROOT, "../session_graph");
const pkg = JSON.parse(fs.readFileSync(path.join(ROOT, "package.json"), "utf8"));
const target = { platform: process.env.SM_PLATFORM || "darwin", arch: process.env.SM_ARCH || process.arch };
const install = process.env.SM_INSTALL_DIR ?? path.join(os.homedir(), "Applications");

// 1. Stage exactly what the app needs.
const stage = fs.mkdtempSync(path.join(os.tmpdir(), "session-meter-"));
for (const f of ["main.mjs", "core.mjs", "preload.cjs", "index.html", "ui.js", "package.json", "package-lock.json"]) {
  fs.copyFileSync(path.join(ROOT, f), path.join(stage, f));
}
const sg = path.join(stage, "session_graph");
fs.mkdirSync(path.join(sg, "render"), { recursive: true });
for (const f of fs.readdirSync(GRAPH)) if (/\.(py|cypher)$/.test(f)) fs.copyFileSync(path.join(GRAPH, f), path.join(sg, f));
fs.copyFileSync(path.join(GRAPH, "render", "draw.mjs"), path.join(sg, "render", "draw.mjs"));
// The staged manifest drops dev tooling; the Electron version is passed to the packager directly.
const staged = { ...pkg, devDependencies: undefined, scripts: undefined };
fs.writeFileSync(path.join(stage, "package.json"), JSON.stringify(staged, null, 2));
console.log("staged", stage);
execFileSync("npm", ["ci", "--omit=dev", "--no-audit", "--no-fund"], { cwd: stage, stdio: "inherit" });  // d3 only

// 2. App icon (.icns) from assets/icon.png, with macOS's own sips + iconutil.
let icon;
if (process.platform === "darwin") {
  const set = path.join(stage, "icon.iconset");
  fs.mkdirSync(set);
  for (const s of [16, 32, 128, 256, 512]) {
    execFileSync("sips", ["-z", String(s), String(s), path.join(ROOT, "assets/icon.png"), "--out", path.join(set, `icon_${s}x${s}.png`)], { stdio: "ignore" });
    execFileSync("sips", ["-z", String(2 * s), String(2 * s), path.join(ROOT, "assets/icon.png"), "--out", path.join(set, `icon_${s}x${s}@2x.png`)], { stdio: "ignore" });
  }
  icon = path.join(stage, "icon.icns");
  execFileSync("iconutil", ["-c", "icns", set, "-o", icon]);
}

// 3. Package. LSUIElement keeps it out of the Dock and the ⌘-Tab switcher: a menu-bar app.
const [appDir] = await packager({
  dir: stage,
  name: "Session Meter",
  executableName: "Session Meter",
  appBundleId: "local.session-meter",
  appCategoryType: "public.app-category.developer-tools",
  electronVersion: pkg.devDependencies.electron,
  platform: target.platform,
  arch: target.arch,
  icon,
  out: path.join(ROOT, "dist"),
  overwrite: true,
  prune: false,  // the stage already holds production dependencies only (npm ci --omit=dev)
  ignore: [/\.iconset$/, /icon\.icns$/],
  extendInfo: { LSUIElement: true },
});
const app = path.join(appDir, "Session Meter.app");
console.log("built", app);

// 4. Install into ~/Applications (no admin password needed), replacing an older copy.
if (install && process.platform === "darwin") {
  fs.mkdirSync(install, { recursive: true });
  const dest = path.join(install, "Session Meter.app");
  fs.rmSync(dest, { recursive: true, force: true });
  execFileSync("ditto", [app, dest]);
  console.log(`installed ${dest}\nopen it with:  open "${dest}"`);
}
