// The QuantDesk site on Cloudflare: serves the read-only phone app that the desk publishes to GitHub Pages (the
// gh-pages branch, re-published every few minutes while it trades) from Cloudflare's edge.
//
// Nothing is built or stored here. Every request is passed through to Pages, so the app and its data.json are
// always the ones the desk last published, and Cloudflare only redeploys when this file or wrangler.jsonc
// changes on main, not on every data update. The site is read-only, so only GET and HEAD are served.
//
// It is also the desk's alarm clock. GitHub's own cron is best-effort and, on this repository, very late: live.yml's
// 08:52 IST schedule arrived at 15:19-15:46 IST on 29 Sep - 1 Oct 2026 and the every-10-minutes scheduler.yml fired
// three times in a day. Cloudflare's cron triggers fire on the minute, so every 10 minutes on weekday mornings and
// through the session (wrangler.jsonc) this asks GitHub to run scheduler.yml now (workflow_dispatch runs at once).
// scheduler.py then decides: start the desk if it should be running and isn't, never after a manual cancel.
// The same clock starts the wide data collection on time (F-19-2): the 15:25 IST stock-chain snapshot is only possible
// while the book is live (it is blank after the close), and GitHub's own cron for collect-wide.yml arrived 4.5 hours late
// on this repository. So at 15:25 and 15:45 IST this also dispatches collect-wide.yml (step stocks / minutes); that workflow
// is read-only data collection beside the desk and keeps its own GitHub schedule as a fallback (a late duplicate is
// harmless: the stock snapshot refuses to record outside the session, and the minutes overlap and de-duplicate).
// It needs GH_DISPATCH_TOKEN: a fine-grained GitHub token for this repository with "Actions: read and write",
// saved as a secret of this Worker (Cloudflare dashboard → the Worker → Settings → Variables and Secrets).
//
// And it is the desk's watchdog (watchdog.js): after the alarm-clock job of each firing, the checks due at that IST time
// run (is the desk up, is its heartbeat fresh, did the evening workflows run, credential expiry, the weekly digest) and
// alert by push (ntfy, secret NTFY_TOPIC) and by email (watchdog-alert.yml opens an issue as the Actions bot). The watchdog
// never throws into this handler: the alarm clock always goes first.

import { runWatchdog } from "./watchdog.js";

const LIVE = /(^|\/)(data\.json|sw\.js)$/;         // live data and the service worker: never from an edge cache
const PASS = ["accept", "accept-encoding", "if-none-match", "if-modified-since", "range"];

// What kind of token the secret holds, never any of its value: a classic token (ghp_, 40 characters) cannot be
// limited to Actions on one repository, and a fine-grained one (github_pat_) can.
export function tokenKind(token) {
	const t = String(token || "");
	const kind = t.startsWith("github_pat_") ? "fine-grained" : t.startsWith("ghp_") ? "classic" : "unrecognised";
	return `${kind} token, ${t.length} characters`;
}

// The collect-wide.yml steps this Worker starts, by the cron (as written in wrangler.jsonc, UTC) that fires them.
export const COLLECT_CRONS = { "55 9 * * MON-FRI": "stocks", "15 10 * * MON-FRI": "minutes" };    // 15:25 and 15:45 IST

export async function dispatchWorkflow(env, file, inputs) {
	const token = String(env.GH_DISPATCH_TOKEN || "").trim();       // a pasted newline would break the header
	if (!token) return { ok: false, why: "GH_DISPATCH_TOKEN is not set on this Worker: the desk relies on GitHub's own cron" };
	const repo = String(env.GH_REPO || "mrityurequest20-cyber/Quant-Desk");
	const res = await fetch(`https://api.github.com/repos/${repo}/actions/workflows/${file}/dispatches`, {
		method: "POST",
		headers: { authorization: `Bearer ${token}`, accept: "application/vnd.github+json", "x-github-api-version": "2022-11-28",
			"user-agent": "quantdesk-worker", "content-type": "application/json" },
		body: JSON.stringify({ ref: String(env.GH_REF || "main"), ...(inputs ? { inputs } : {}) }),
	});
	if (res.status === 204) return { ok: true, why: "GitHub answered 204" };
	// GitHub says why it refused, and on a 403 which permission the call needed: log both (never the token)
	let msg = "";
	try { msg = String((await res.json()).message || ""); } catch (e) { msg = ""; }
	const needs = res.headers.get("x-accepted-github-permissions");
	return { ok: false, why: `GitHub answered ${res.status}${msg ? `: ${msg}` : ""}${needs ? ` (needs ${needs})` : ""}; ${tokenKind(token)}` };
}

// The one cron (as written in wrangler.jsonc, UTC) that must NOT start the desk: the watchdog's own half-hourly trigger.
// Every other cron asks GitHub to run scheduler.yml now, as before this file had a watchdog, so if Cloudflare ever reports a
// cron string differently the worst case is one extra, harmless dispatch, never a desk that silently is not started.
export const WATCHDOG_ONLY_CRON = "0,30 10-16 * * *";

export const dispatchScheduler = (env) => dispatchWorkflow(env, "scheduler.yml");
export const dispatchCollect = (env, step) => dispatchWorkflow(env, "collect-wide.yml", { step });

export default {
	async scheduled(event, env, ctx) {
		const step = COLLECT_CRONS[event.cron];
		if (step) {                                              // 15:25 / 15:45 IST: wide data collection, on time
			const r = await dispatchCollect(env, step);
			console.log(`collect-wide ${step} ${r.ok ? "dispatched" : "not dispatched"} (${event.cron}): ${r.why}`);
			return;
		}
		if (event.cron !== WATCHDOG_ONLY_CRON) {
			try {
				const r = await dispatchScheduler(env);
				console.log(`desk scheduler ${r.ok ? "dispatched" : "not dispatched"} (${event.cron}): ${r.why}`);
			} catch (e) {                                        // a network error here must not silence the watchdog below
				console.log(`desk scheduler not dispatched (${event.cron}): ${String(e && e.message).slice(0, 200)}`);
			}
		}
		try {                                                    // the alarm clock above always goes first and is never held up by this
			await runWatchdog(event, env, { dispatchWorkflow });
		} catch (e) {
			console.log(`watchdog failed (${event.cron}): ${String(e && e.message).slice(0, 200)}`);
		}
	},

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
