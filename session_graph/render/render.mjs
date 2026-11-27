#!/usr/bin/env node
// Step 6b — draw one session graph (graph.json from query.py) as a radial SVG, plus a PNG via resvg.
//
//   node render/render.mjs out/<uuid>/graph.json out/<uuid>/graph.svg [out/<uuid>/graph.png]
//
// The drawing itself lives in draw.mjs (shared with the session_meter desktop widget).
import fs from "node:fs";
import { Resvg } from "@resvg/resvg-js";
import { drawSVG, BG } from "./draw.mjs";

const [, , inPath, svgPath, pngPath] = process.argv;
if (!inPath || !svgPath) {
  console.error("usage: render.mjs graph.json out.svg [out.png]");
  process.exit(2);
}
const g = JSON.parse(fs.readFileSync(inPath, "utf8"));
const svg = drawSVG(g);
fs.writeFileSync(svgPath, svg);
console.error(`[render] ${svgPath}`);
if (pngPath) {
  const png = new Resvg(svg, {
    fitTo: { mode: "original" },
    font: { loadSystemFonts: true, defaultFontFamily: "DejaVu Sans" },
    background: BG,
  }).render().asPng();
  fs.writeFileSync(pngPath, png);
  console.error(`[render] ${pngPath}`);
}
