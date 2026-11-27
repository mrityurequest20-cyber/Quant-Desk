// MarketLens (marketlens/) is served at /lens/ from this Worker, so its page and the private live relay (/live/*) share one origin:
// the app reads live quotes with the owner's key (the desk app's qd.livekey on this device) without any cross-origin access being
// opened on the relay. The files come from the marketlens-site branch that .github/workflows/marketlens.yml publishes after each
// warehouse update (public NSE/BSE end-of-day data only; nothing licensed is in it). Read-only: GET and HEAD, a fixed set of file
// types, no path outside the site.

export const LENS_ORIGIN = "https://raw.githubusercontent.com/mrityurequest20-cyber/Quant-Desk/marketlens-site";
const TYPES = {
	html: "text/html; charset=utf-8", js: "application/javascript; charset=utf-8", css: "text/css; charset=utf-8",
	json: "application/json; charset=utf-8", svg: "image/svg+xml", png: "image/png", ico: "image/x-icon",
	webmanifest: "application/manifest+json",
};
const SAFE = /^[A-Za-z0-9_\-./&]{1,200}$/;

export function lensPath(pathname) {
	if (pathname === "/lens") return { redirect: "/lens/" };
	if (!pathname.startsWith("/lens/")) return null;
	let sub = decodeURIComponent(pathname.slice("/lens/".length)) || "index.html";
	if (sub.endsWith("/")) sub += "index.html";
	if (!SAFE.test(sub) || sub.split("/").some((p) => p === ".." || p === "." || p === "") || sub.startsWith(".")) return { bad: true };
	const ext = (sub.match(/\.([a-z]+)$/) || [])[1];
	if (!ext || !TYPES[ext]) return { bad: true };
	return { sub, type: TYPES[ext] };
}

export async function handleLens(request, env, fetchFn = fetch) {
	const url = new URL(request.url);
	const p = lensPath(url.pathname);
	if (!p) return null;
	if (request.method !== "GET" && request.method !== "HEAD") return new Response("Read-only.\n", { status: 405, headers: { allow: "GET, HEAD" } });
	if (p.redirect) return Response.redirect(new URL(p.redirect, url.origin).toString(), 301);
	if (p.bad) return new Response("Not found.\n", { status: 404 });
	const origin = String(env.LENS_ORIGIN || LENS_ORIGIN).replace(/\/+$/, "");
	let res;
	try {
		res = await fetchFn(`${origin}/${p.sub.split("/").map(encodeURIComponent).join("/")}`, { method: request.method, cf: { cacheTtl: 60 } });
	} catch (e) {
		return new Response("MarketLens files are unreachable.\n", { status: 502 });
	}
	if (res.status === 404) return new Response("Not found.\n", { status: 404 });
	if (!res.ok) return new Response(`MarketLens files answered ${res.status}.\n`, { status: 502 });
	const headers = new Headers({
		"content-type": p.type, "x-content-type-options": "nosniff", "referrer-policy": "same-origin",
		// the page, its scripts and its data are revalidated each load, so a new day's build shows at once
		"cache-control": /\.(html|js|css|json)$/.test(p.sub) ? "no-cache" : "public, max-age=3600",
	});
	return new Response(request.method === "HEAD" ? null : res.body, { status: 200, headers });
}
