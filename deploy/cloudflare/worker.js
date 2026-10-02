// The QuantDesk site on Cloudflare: serves the read-only phone app that the desk publishes to GitHub Pages (the
// gh-pages branch, re-published every few minutes while it trades) from Cloudflare's edge.
//
// Nothing is built or stored here. Every request is passed through to Pages, so the app and its data.json are
// always the ones the desk last published, and Cloudflare only redeploys when this file or wrangler.jsonc
// changes on main, not on every data update. The site is read-only, so only GET and HEAD are served.

const LIVE = /(^|\/)(data\.json|sw\.js)$/;         // live data and the service worker: never from an edge cache
const PASS = ["accept", "accept-encoding", "if-none-match", "if-modified-since", "range"];

export default {
	async fetch(request, env) {
		if (request.method !== "GET" && request.method !== "HEAD") {
			return new Response("Read-only site.\n", { status: 405, headers: { allow: "GET, HEAD" } });
		}
		const origin = String(env.ORIGIN || "").replace(/\/+$/, "");
		if (!/^https:\/\//.test(origin)) {
			return new Response("ORIGIN is not set in wrangler.jsonc.\n", { status: 500 });
		}
		const url = new URL(request.url);
		const live = LIVE.test(url.pathname);
		const headers = new Headers();
		for (const h of PASS) {
			const v = request.headers.get(h);
			if (v) headers.set(h, v);
		}
		let res;
		try {
			res = await fetch(origin + url.pathname + url.search, {
				method: request.method, headers, redirect: "manual", ...(live ? { cache: "no-store" } : {}),
			});
		} catch (err) {
			return new Response(`GitHub Pages is unreachable: ${err}\n`, { status: 502 });
		}
		const out = new Response(res.body, res);
		const loc = out.headers.get("location");               // Pages redirects (folder → folder/) to its own host
		if (loc && loc.startsWith(origin)) {
			out.headers.set("location", new URL(loc.slice(origin.length) || "/", url.origin).toString());
		}
		if (live) {
			out.headers.set("cache-control", "no-cache");       // the app revalidates with the ETag: a 304 when unchanged
		}
		out.headers.set("x-content-type-options", "nosniff");
		return out;
	},
};
