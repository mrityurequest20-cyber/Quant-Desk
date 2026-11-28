// MarketLens alerts, the Worker's side: on each ten-minute cron firing in market hours, read the live relay's snapshot and
// MarketLens's close-of-day baseline (overview.json, from the published site), evaluate the owner's rules with the app's
// own code (livecore.js and alertrules.js, byte-for-byte copies of marketlens/web/: a test compares them), keep the ones
// not sent today (the relay's alert store) and push each to the owner's phone through ntfy, as the watchdog does.
//
// Read-only and display-only, like the rest of MarketLens: it places nothing, holds no position, and its only secret is the
// ntfy topic the watchdog already uses. It never throws into the cron: the desk's alarm clock runs before it and is never
// held up by it (worker.js).
//
// Hours (IST): NSE rules on trading days 09:20-15:30; MCX rules on weekdays 09:05-23:30; the end-of-day ban list once the
// site is rebuilt in the evening, 20:30-23:50 on trading days.

import "./livecore.js";
import "./alertrules.js";
import { ist, isTradingDate, pushNtfy } from "./watchdog.js";
import { LENS_ORIGIN } from "./lens.js";

const FETCH_MS = 8000;
let cached = { at: 0, ov: null };

export function windows(nowMs) {
	const t = ist(nowMs), trading = isTradingDate(t.date), weekday = t.dow >= 1 && t.dow <= 5;
	return { nse: trading && t.hhmm >= "09:20" && t.hhmm <= "15:30", mcx: weekday && t.hhmm >= "09:05" && t.hhmm <= "23:30",
		eod: trading && t.hhmm >= "20:30" && t.hhmm <= "23:50", day: t.date, hhmm: t.hhmm };
}

async function overview(env, nowMs, fetchFn) {
	if (cached.ov && nowMs - cached.at < 20 * 60000) return cached.ov;
	const origin = String(env.LENS_ORIGIN || LENS_ORIGIN).replace(/\/+$/, "");
	const r = await fetchFn(`${origin}/data/overview.json`, { signal: AbortSignal.timeout(FETCH_MS) });
	if (!r.ok) throw new Error(`overview.json answered ${r.status}`);
	cached = { at: nowMs, ov: await r.json() };
	return cached.ov;
}

export async function runAlerts(event, env, deps = {}, log = console.log) {
	const nowMs = event.scheduledTime ?? Date.now();
	const w = windows(nowMs);
	if (!(w.nse || w.mcx || w.eod)) return { ran: false, why: "outside market hours" };
	if (!env.LIVE || !String(env.NTFY_TOPIC || "").trim()) return { ran: false, why: "no live relay or no ntfy topic" };
	const fetchFn = deps.fetch || fetch;
	const stub = env.LIVE.get(env.LIVE.idFromName("board"));
	const [ov, snap, state] = await Promise.all([
		overview(env, nowMs, fetchFn),
		stub.fetch("https://live/snapshot").then((r) => r.json()),
		stub.fetch("https://live/alerts/state").then((r) => (r.ok ? r.json() : { rules: [] })),
	]);
	const alerts = globalThis.AlertRules.evaluate((snap && snap.quotes) || {}, ov, state.rules, nowMs, { nse: w.nse, mcx: w.mcx, eod: w.eod });
	if (!alerts.length) return { ran: true, n: 0, sent: 0 };
	const res = await stub.fetch("https://live/alerts/sent", { method: "POST", body: JSON.stringify({ alerts }) });
	const fresh = new Set(res.ok ? (await res.json()).fresh || [] : []);
	let sent = 0;
	for (const a of alerts.filter((x) => fresh.has(x.key)).slice(0, 8)) {          // never a flood: eight a firing at most
		const r = await pushNtfy(env, { sev: a.sev, check: "MARKET", title: a.title, body: a.body, link: "" });
		if (r.ok) sent += 1;
	}
	log(`marketlens alerts ${w.day} ${w.hhmm}: ${alerts.length} due, ${fresh.size} new, ${sent} pushed`);
	return { ran: true, n: alerts.length, fresh: fresh.size, sent };
}
