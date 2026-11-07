// Regenerate the app's PNG icons from ONE source, quantdesk/web/static/app/icon.svg (the same mark the app draws in its header, app.js `mark()`),
// so the home-screen icon and the in-app mark cannot drift apart. Needs Playwright (any Chromium): `node deploy/make_icons.mjs`.
//   icon-192 / icon-512  the rounded mark on a transparent corner (browser tab, Android "any" icon)
//   apple-touch-icon     180 px, full bleed: iOS rounds the corners itself, so a pre-rounded icon would get a double edge
//   icon-maskable-512    full bleed, mark inside the central 80% safe zone so Android can crop to any shape
import { createRequire } from "node:module";
const { chromium } = createRequire(import.meta.url)("playwright");          // CommonJS resolution, so NODE_PATH works for a global install
import { readFileSync, writeFileSync } from "node:fs";
const dir = new URL("../quantdesk/web/static/app/", import.meta.url).pathname;
const svg = readFileSync(dir + "icon.svg", "utf8");
const inner = svg.replace(/^[\s\S]*?<rect[^>]*\/>\s*/, "").replace(/<\/svg>\s*$/, "");               // the two paths, without the rounded background
const page = await (await chromium.launch()).newPage();
async function render(size, { bleed, scale }) {
	const bg = bleed ? `<rect width="64" height="64" fill="#0B0E13"/>` : `<rect width="64" height="64" rx="15" fill="#0B0E13"/>`;
	const g = scale === 1 ? inner : `<g transform="translate(32 32) scale(${scale}) translate(-32 -32)">${inner}</g>`;
	await page.setViewportSize({ width: size, height: size });
	await page.setContent(`<body style="margin:0;background:transparent"><svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" width="${size}" height="${size}" style="display:block">${bg}${g}</svg></body>`);
	return page.screenshot({ omitBackground: true, clip: { x: 0, y: 0, width: size, height: size } });
}
writeFileSync(dir + "icon-192.png", await render(192, { bleed: false, scale: 1 }));
writeFileSync(dir + "icon-512.png", await render(512, { bleed: false, scale: 1 }));
writeFileSync(dir + "apple-touch-icon.png", await render(180, { bleed: true, scale: 1 }));
writeFileSync(dir + "icon-maskable-512.png", await render(512, { bleed: true, scale: 0.8 }));
await page.context().browser().close();
console.log("icons written from icon.svg");
