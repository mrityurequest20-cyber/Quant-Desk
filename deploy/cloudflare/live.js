// The live view relay: the Kite recorder pushes a small snapshot of the latest prices every 5 seconds, the app reads it every 5 seconds.
//
//   POST /live/ingest    the recorder (GitHub Actions) sends {"quotes": {"NIFTY": {"ltp": ..., "bid": ..., ...}}}; needs LIVE_INGEST_TOKEN
//   GET  /live/snapshot  the app reads the latest quote of every symbol, each with its age in seconds; needs LIVE_READ_TOKEN
//
// DISPLAY ONLY. Nothing here is read by the paper desk or any trading code, and nothing that arrives here can place an order. The prices are
// Zerodha's licensed market data, so the read endpoint is private: it answers only to the owner's key, never to the public site's visitors, and the
// data is never written to the repository or to Pages. Both secrets are Worker secrets (Cloudflare dashboard -> the Worker -> Settings -> Variables
// and Secrets). If either is missing or too short, or they are equal, the endpoints answer 503 and nothing is stored: it fails closed.
//
// The latest snapshot is kept in one Durable Object (class LiveBoard, binding LIVE) because a Worker has no memory shared between requests. It is held in memory only.
// Ages are worked out here, from this Worker's clock when each quote arrived, so a stale feed shows as stale whatever the phone's clock says.

import { KotakPoller, istParts, runCycle, inSession, SPECIAL_SESSIONS } from "./kotak.js";
import { Series, shardKeys, FLUSH_MS } from "./series.js";
import { PaperBook, cleanOrder, cleanResult, cleanState } from "./paper.js";
import { NewsBook } from "./news.js";

const MAX_BODY = 524288;                // bytes of one push (a batch of ~800 quotes is about 100 KB)
const MAX_SYMBOLS = 3000;               // in one push
const MAX_TOTAL = 6000;                 // symbols the board will ever hold: a stolen ingest key cannot grow it without bound
const SYMBOL = /^[A-Za-z0-9&_.:-]{1,40}$/;
const SEGMENTS = new Set(["idx", "eq", "fut", "bfo", "mcx", "cds", "opt"]);
const NUMBERS = ["ltp", "bid", "ask", "bid_qty", "ask_qty", "vol", "oi", "chg"];
const MIN_SECRET = 24;                  // characters

const JSON_HEADERS = { "content-type": "application/json; charset=utf-8", "cache-control": "no-store", "x-content-type-options": "nosniff", "x-robots-tag": "noindex" };
const reply = (status, body) => new Response(JSON.stringify(body), { status, headers: JSON_HEADERS });

// Compare two secrets without leaking, through timing, how much of one matched: hash both to the same length first.
export async function same(a, b) {
	const enc = new TextEncoder();
	const [x, y] = await Promise.all([crypto.subtle.digest("SHA-256", enc.encode(String(a))), crypto.subtle.digest("SHA-256", enc.encode(String(b)))]);
	const u = new Uint8Array(x), v = new Uint8Array(y);
	let diff = 0;
	for (let i = 0; i < u.length; i++) diff |= u[i] ^ v[i];
	return diff === 0;
}

function bearer(request) {
	const m = /^Bearer\s+(\S+)$/.exec(request.headers.get("authorization") || "");
	return m ? m[1] : "";
}

// The two secrets must both be set, long enough and different, or the view is off.
// Two live sources feed one board: Kite's websocket (pushed by the recorder, source "z") and Kotak's REST quotes (polled by the board itself on a Durable Object alarm,
// source "k"). Per instrument the board keeps the latest quote of each, shows the fresher one with its source, and flags the instrument when the two disagree.
const FRESH_S = 60;                     // a quote this young counts as live for comparing and enriching
const TOL = { opt: 3.0, other: 0.5 };   // percent: options have wide spreads and thin books; a spot or a future that differs more than this between two brokers is a fault
const SEG_KOTAK = new Set(["nse_cm", "bse_cm", "nse_fo", "bse_fo"]);

export function configured(env) {
	const i = String(env.LIVE_INGEST_TOKEN || "").trim(), r = String(env.LIVE_READ_TOKEN || "").trim();
	return !!env.LIVE && i.length >= MIN_SECRET && r.length >= MIN_SECRET && i !== r;
}

// Why the view is off, for the 503 body: what is missing, never a value. The owner sets these in a dashboard and cannot run a command on the Worker, so "not switched on"
// alone leaves a typo in a name, a Text variable that a deploy wiped, a too-short string or the same string twice to be guessed at. Only a state per piece is given (missing,
// too short, ok, the same), plus the NAMES of the Worker's own LIVE* and KOTAK* settings so a misspelt name shows. No token, no length, no value, nothing that helps guess one.
export function whyOff(env) {
	const i = String(env.LIVE_INGEST_TOKEN || "").trim(), r = String(env.LIVE_READ_TOKEN || "").trim();
	const state = (v) => (!v ? "missing" : v.length < MIN_SECRET ? `too short (at least ${MIN_SECRET} characters)` : "ok");
	return {
		LIVE_object: env.LIVE ? "ok" : "missing (the Durable Object binding)",
		LIVE_INGEST_TOKEN: state(i),
		LIVE_READ_TOKEN: state(r),
		different: i && r && i === r ? "no: the two are the same string" : "ok",
		seen: Object.keys(env || {}).filter((k) => /^(LIVE|KOTAK)/i.test(k)).map((k) => (/^[A-Za-z][A-Za-z0-9_]{0,39}$/.test(k) ? k : "(an unusual setting name)")).sort().slice(0, 20),          // a name only if it looks like one: a `NAME=value` typed into the name box is never echoed
	};
}

// Read a request body at most `max` bytes, stopping at the cap: a chunked body with no Content-Length is never buffered whole. null = too large.
export async function readCapped(request, max) {
	if (!request.body) return "";
	const reader = request.body.getReader();
	const chunks = [];
	let n = 0;
	for (;;) {
		const { done, value } = await reader.read();
		if (done) break;
		n += value.byteLength;
		if (n > max) { try { await reader.cancel(); } catch (e) { /* already closed */ } return null; }
		chunks.push(value);
	}
	const all = new Uint8Array(n);
	let at = 0;
	for (const c of chunks) { all.set(c, at); at += c.byteLength; }
	return new TextDecoder().decode(all);
}

// Keep only what the app shows, as numbers: anything else in a push is dropped, never stored. One bad quote or name is skipped and counted, it does not
// poison the rest of the push; a push with no usable quote at all is refused. Returns {quotes, dropped} or null.
export function clean(body) {
	if (!body || typeof body !== "object" || !body.quotes || typeof body.quotes !== "object" || Array.isArray(body.quotes)) return null;
	const names = Object.keys(body.quotes);
	if (!names.length || names.length > MAX_SYMBOLS) return null;
	const out = Object.create(null);                                                   // no prototype: a symbol named __proto__ or constructor is plain data
	let dropped = 0;
	for (const name of names) {
		const q = body.quotes[name];
		if (!SYMBOL.test(name) || !q || typeof q !== "object") { dropped += 1; continue; }
		const row = {};
		for (const k of NUMBERS) if (typeof q[k] === "number" && Number.isFinite(q[k])) row[k] = q[k];
		if (typeof q.t === "string" && q.t.length <= 40) row.t = q.t;                // the exchange's timestamp, shown as is
		if (typeof q.s === "string" && SEGMENTS.has(q.s)) row.s = q.s;               // what kind of instrument: index, stock, future, option, MCX, currency
		if (!("ltp" in row)) { dropped += 1; continue; }                               // a quote without a last price is not a quote
		out[name] = row;
	}
	return Object.keys(out).length ? { quotes: out, dropped } : null;
}

// What the Kotak poller is told to fetch: [{n: name, s: segment, g: Kotak segment, t: token or index name, one?}] and the option chains [{u, x, e}]. Anything malformed is skipped.
const isDate = (e) => {                                                                // a real calendar date: not 2026-13-99 (which would throw below), not 2026-02-30
	if (typeof e !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(e)) return false;
	const d = new Date(e + "T00:00:00Z");
	return !Number.isNaN(d.getTime()) && d.toISOString().slice(0, 10) === e;
};
export function cleanUniverse(b) {
	if (!b || typeof b !== "object") return null;
	const quotes = [], chains = [], names = new Set(), seenChain = new Set();
	for (const q of Array.isArray(b.quotes) ? b.quotes.slice(0, 3000) : []) {
		if (!q || typeof q !== "object" || typeof q.n !== "string" || typeof q.t !== "string" || typeof q.s !== "string" || typeof q.g !== "string") continue;
		if (!SYMBOL.test(q.n) || !SEGMENTS.has(q.s) || !SEG_KOTAK.has(q.g) || !/^[A-Za-z0-9 &_.-]{1,40}$/.test(q.t) || names.has(q.n)) continue;      // one entry per name: a name asked for twice would defeat the freshness rule
		names.add(q.n);
		quotes.push({ n: q.n, s: q.s, g: q.g, t: q.t, ...(q.one === true ? { one: true } : {}) });
	}
	for (const c of Array.isArray(b.chains) ? b.chains.slice(0, 400) : []) {
		if (!c || typeof c.u !== "string" || typeof c.x !== "string" || !/^[A-Za-z0-9&_-]{1,24}$/.test(c.u) || !SEG_KOTAK.has(c.x) || !isDate(c.e)) continue;
		if (c.n !== undefined && !(Number.isInteger(c.n) && c.n >= 1 && c.n <= 10)) continue;          // a keep-count that is not a small integer is a malformed chain, not an index chain that runs every cycle
		const k = `${c.u}|${c.e}`;                                                          // one chain per underlying and expiry, whatever exchange it claims: two would update the same option names from two answers
		if (!seenChain.has(k)) { seenChain.add(k); chains.push({ u: c.u, x: c.x, e: c.e, ...(Number.isInteger(c.n) && c.n >= 1 && c.n <= 10 ? { n: c.n } : {}) }); }
	}
	if (!quotes.length && !chains.length) return null;
	const count = Math.min(30, Math.max(1, Math.trunc(Number(b.count)) || 10));
	return { asof: isDate(b.asof) ? b.asof : null, quotes, chains, count };
}

// The Worker's own clock (wrangler cron, every 10 minutes in the session) re-arms the poller if its alarm was ever lost.
export async function armLive(env) {
	if (!configured(env) || !String(env.KOTAK_CONSUMER_KEY || "").trim()) return false;
	await env.LIVE.get(env.LIVE.idFromName("board")).fetch("https://live/arm", { method: "POST" });
	return true;
}

// Should the Worker's own cron ask GitHub to rebuild the universe? Yes when the poller is on, it is a weekday between 08:00 and the close, the universe is not today's,
// and the last request was over 40 minutes ago (so a failing build is retried, not hammered).
export async function needsUniverse(env) {
	if (!configured(env) || !String(env.KOTAK_CONSUMER_KEY || "").trim()) return false;
	const r = await env.LIVE.get(env.LIVE.idFromName("board")).fetch("https://live/needs-universe", { method: "POST" });
	return !!(await r.json()).need;
}

export async function handleLive(request, env) {
	const url = new URL(request.url);
	const isPaper = url.pathname.startsWith("/paper/"), isNews = url.pathname === "/news" || url.pathname === "/news/ingest";
	if (!url.pathname.startsWith("/live/") && !isPaper && !isNews) return null;
	if (!configured(env)) {
		let why;
		try { why = whyOff(env); } catch (e) { /* the diagnosis is a courtesy: the 503 is what matters, and it always returns */ }
		return reply(503, { error: "the live view is not switched on", ...(why ? { why } : {}) });
	}
	const stub = env.LIVE.get(env.LIVE.idFromName("board"));
	if (isPaper) return handlePaper(request, env, url, stub);
	if (isNews) return handleNews(request, env, url, stub);
	if (url.pathname === "/live/ingest") {
		if (request.method !== "POST") return reply(405, { error: "POST only" });
		if (!(await same(bearer(request), String(env.LIVE_INGEST_TOKEN).trim()))) return reply(401, { error: "no" });
		const declared = Number(request.headers.get("content-length"));
		if (Number.isFinite(declared) && declared > MAX_BODY) return reply(413, { error: "too large" });     // before the body is read
		const raw = await readCapped(request, MAX_BODY);                                                     // bytes, and the stream stops at the cap whatever the headers say
		if (raw === null) return reply(413, { error: "too large" });
		let body;
		try { body = JSON.parse(raw); } catch (e) { return reply(400, { error: "not JSON" }); }
		const cleaned = clean(body);
		if (!cleaned) return reply(400, { error: "not a snapshot" });
		return stub.fetch("https://live/push", { method: "POST", body: JSON.stringify(cleaned) });
	}
	if (url.pathname === "/live/universe") {                                         // what the Kotak poller asks for: built daily by quantdesk/data/kotak_universe.py
		if (request.method !== "POST") return reply(405, { error: "POST only" });
		if (!(await same(bearer(request), String(env.LIVE_INGEST_TOKEN).trim()))) return reply(401, { error: "no" });
		const declared = Number(request.headers.get("content-length"));
		if (Number.isFinite(declared) && declared > MAX_BODY) return reply(413, { error: "too large" });
		const raw = await readCapped(request, MAX_BODY);
		if (raw === null) return reply(413, { error: "too large" });
		let body;
		try { body = JSON.parse(raw); } catch (e) { return reply(400, { error: "not JSON" }); }
		const universe = cleanUniverse(body);
		if (!universe) return reply(400, { error: "not a universe" });
		return stub.fetch("https://live/universe", { method: "POST", body: JSON.stringify(universe) });
	}
	if (url.pathname === "/live/health") {
		if (request.method !== "GET") return reply(405, { error: "GET only" });
		if (!(await same(bearer(request), String(env.LIVE_READ_TOKEN).trim()))) return reply(401, { error: "no" });
		return stub.fetch("https://live/health");
	}
	if (url.pathname === "/live/snapshot") {
		if (request.method !== "GET") return reply(405, { error: "GET only" });
		if (!(await same(bearer(request), String(env.LIVE_READ_TOKEN).trim()))) return reply(401, { error: "no" });
		return stub.fetch("https://live/snapshot");
	}
	if (url.pathname === "/live/series") {
		if (request.method !== "GET") return reply(405, { error: "GET only" });
		if (!(await same(bearer(request), String(env.LIVE_READ_TOKEN).trim()))) return reply(401, { error: "no" });
		const name = url.searchParams.get("name") || "";
		if (!SYMBOL.test(name)) return reply(400, { error: "not an instrument name" });
		return stub.fetch("https://live/series?name=" + encodeURIComponent(name));
	}
	return reply(404, { error: "no such live path" });
}

// /paper/*: the paper-order queue. The app (READ key) queues an order and sets the kill flag and reads the state; the runner (INGEST key) drains the queue, posts results and keeps the
// account. Each route takes exactly one of the two keys: the key that reads the board can queue a PAPER order, and cannot write a result or a state.
const PAPER_ROUTES = {
	"POST /paper/order": "read", "POST /paper/kill": "read",
	"GET /paper/queue": "ingest", "POST /paper/result": "ingest", "POST /paper/state": "ingest",
};
async function handlePaper(request, env, url, stub) {
	const route = request.method + " " + url.pathname;
	const need = PAPER_ROUTES[route] || (route === "GET /paper/state" ? (url.searchParams.get("full") === "1" ? "ingest" : "read") : null);
	if (!need) return reply(request.method === "GET" || request.method === "POST" ? 404 : 405, { error: "no such paper path" });
	if (!(await same(bearer(request), String(need === "read" ? env.LIVE_READ_TOKEN : env.LIVE_INGEST_TOKEN).trim()))) return reply(401, { error: "no" });
	let body;
	if (request.method === "POST") {
		const declared = Number(request.headers.get("content-length"));
		if (Number.isFinite(declared) && declared > PAPER_MAX_BODY) return reply(413, { error: "too large" });
		const raw = await readCapped(request, PAPER_MAX_BODY);
		if (raw === null) return reply(413, { error: "too large" });
		try { body = JSON.parse(raw); } catch (e) { return reply(400, { error: "not JSON" }); }
		if (route === "POST /paper/order" && !cleanOrder(body)) return reply(400, { error: "not a valid order" });
		if (route === "POST /paper/result" && !cleanResult(body)) return reply(400, { error: "not a valid result" });
		if (route === "POST /paper/state" && !cleanState(body)) return reply(400, { error: "not a valid state" });
	}
	return stub.fetch("https://live" + url.pathname + url.search, { method: request.method, ...(body !== undefined ? { body: JSON.stringify(body) } : {}) });
}
// /news and /news/ingest: the news digest (news.js). The job (INGEST key) sends it; the app (READ key) reads it. Public headlines only.
async function handleNews(request, env, url, stub) {
	const route = request.method + " " + url.pathname;
	const need = route === "POST /news/ingest" ? "ingest" : route === "GET /news" ? "read" : null;
	if (!need) return reply(request.method === "GET" || request.method === "POST" ? 404 : 405, { error: "no such news path" });
	if (!(await same(bearer(request), String(need === "read" ? env.LIVE_READ_TOKEN : env.LIVE_INGEST_TOKEN).trim()))) return reply(401, { error: "no" });
	let body;
	if (request.method === "POST") {
		const declared = Number(request.headers.get("content-length"));
		if (Number.isFinite(declared) && declared > NEWS_MAX_BODY) return reply(413, { error: "too large" });
		const raw = await readCapped(request, NEWS_MAX_BODY);
		if (raw === null) return reply(413, { error: "too large" });
		try { body = JSON.parse(raw); } catch (e) { return reply(400, { error: "not JSON" }); }
	}
	let fwd;
	try { fwd = body !== undefined ? JSON.stringify(body) : undefined; } catch (e) { return reply(400, { error: "not a valid digest" }); }      // absurdly deep nesting parses but cannot be written back out
	return stub.fetch("https://live" + url.pathname, { method: request.method, ...(fwd !== undefined ? { body: fwd } : {}) });
}
const NEWS_MAX_BODY = 200000;
const PAPER_MAX_BODY = 1300000;           // a saved account is up to MAX_CHUNKS x CHUNK characters

const round1 = (x) => Math.round(x * 10) / 10;
const round2 = (x) => Math.round(x * 100) / 100;
// Did the instrument MOVE? Compare only what both updates carry: a chain row has no book and a quote row has one, so a missing field is not a change (otherwise an option covered
// by both would look new every cycle). The book counts when both have one.
const MOVED = ["ltp", "vol", "oi"];
const sameQuote = (a, b) => {
	for (const k of MOVED) if (k in a && k in b && a[k] !== b[k]) return false;
	if ("bid" in a && "bid" in b && (a.bid !== b.bid || a.ask !== b.ask || a.bid_qty !== b.bid_qty || a.ask_qty !== b.ask_qty)) return false;
	return true;
};
// An option's name carries its expiry (NIFTY12NOV2624500CE: 12 Nov 2026). From the day after it, the contract is gone: the expiry day itself is still traded.
const OPT_EXPIRY = /^.+?(\d{2})(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)(\d{2})\d+(?:\.\d+)?(?:CE|PE)$/;
const MONTH = { JAN: 1, FEB: 2, MAR: 3, APR: 4, MAY: 5, JUN: 6, JUL: 7, AUG: 8, SEP: 9, OCT: 10, NOV: 11, DEC: 12 };
const AGREE_KEYS = ["cycles", "both", "disagree", "opt_both", "opt_disagree", "worst_cycle_pct", "first_at", "last_at"];
function cleanDay(d) {
	if (!d || typeof d !== "object" || !/^\d{4}-\d{2}-\d{2}$/.test(String(d.day))) return null;
	const out = { day: d.day };
	for (const k of AGREE_KEYS) { const v = Number(d[k]); out[k] = Number.isFinite(v) && v >= 0 ? v : 0; }
	out.peak = { z: {}, k: {} };
	for (const src of ["z", "k"]) for (const [g, n] of Object.entries(d.peak && d.peak[src] && typeof d.peak[src] === "object" ? d.peak[src] : {})) if (/^[a-z]{1,6}$/.test(g) || g === "other") { const v = Number(n); if (Number.isFinite(v) && v >= 0) out.peak[src][g] = v; }
	return out;
}
export function cleanAgree(raw) {                       // storage is not trusted: a malformed tally is dropped, not shown
	if (!raw || typeof raw !== "object") return null;
	const today = cleanDay(raw.today), days = {};
	for (const [k, v] of Object.entries(raw.days && typeof raw.days === "object" ? raw.days : {})) { const c = cleanDay(v); if (c && c.day === k) days[k] = c; }
	return today || Object.keys(days).length ? { today, days } : null;
}

export function expiredOption(name, today) {          // today: the IST date as yyyymmdd
	const m = OPT_EXPIRY.exec(name);
	return !!m && (2000 + Number(m[3])) * 10000 + MONTH[m[2]] * 100 + Number(m[1]) < today;
}
const STALE_MS = 4 * 86400e3;               // a quote not seen for 4 days is dropped (expired contracts must not fill the board for good); shorter would empty the board over a weekend, when the last prices are worth showing, aged
const FIRST_SEEN_MS = 12 * 3600e3;          // Kotak's own timestamp dates a first-seen price only if it is within this of now

// The Durable Object: per instrument, the latest quote of each source and when it arrived. MEMORY ONLY for quotes: a wide universe is too big to rewrite to storage every
// five seconds, and the record of every tick is the recorder's Parquet, not this. After a restart the board fills again as instruments tick (seconds for a liquid one).
// Only the universe (what to poll) is stored. A quote keeps its own arrival time: Kite's is the moment a new tick arrives, Kotak's is refreshed only when its price, volume or
// book CHANGED, so a quiet instrument, a holiday or a dead feed grows an age instead of looking live. Age is the relay's, not the exchange's.
export class LiveBoard {
	constructor(state, env) {
		this.state = state;
		this.env = env || {};
		this.quotes = new Map();                    // name -> {z?: quote, k?: quote}, each with `at`
		this.news = new NewsBook(state);            // the news digest (news.js)
		this.book = new PaperBook(state);           // the paper-order queue and account (paper.js): same object, its own storage keys
		this.series = new Series();                 // one close a minute per instrument, for the app's chart (series.js); stored in shards
		this.lastFlush = 0;
		this.seq = 0;
		this.now = () => Date.now();
		this.fetchFn = null;                        // test hooks for the Kotak poller
		this.sleepFn = null;
		this.universe = null;
		this.cursor = 0;
		this.lastPrune = 0;
		this.k = { status: "off", cycles: 0, calls_ok: 0, calls_failed: 0, last_ok: null, last_error: null, errors: {}, consecutive_failed: 0, consecutive_auth: 0, last_rate: 0, refused: 0, pruned: 0, total_calls: 0 };
		this.agree = null;                          // today's Kite-vs-Kotak tally (see tally()); the finished days are kept in this.agreeDays
		this.agreeDays = {};
		this.ready = state.blockConcurrencyWhile(async () => {
			const u = cleanUniverse(await state.storage.get("universe"));                    // re-validated on every reload: storage is not trusted either
			if (u) this.universe = u;
			try { this.series.load(await state.storage.get(shardKeys())); } catch (e) { /* no chart history: the board still starts */ }
			try {                                                                            // the tally survives an eviction or a deploy: a restart must not cost the day its number
				const ag = cleanAgree(await state.storage.get("agree"));
				if (ag) { this.agree = ag.today; this.agreeDays = ag.days; }
			} catch (e) { /* the day's tally starts again from here */ }
			try {                                                                            // the rebuild throttle survives an eviction or a deploy; it can never cost the live view
				const la = await state.storage.get("lastAsk");
				if (typeof la === "number" && Number.isFinite(la)) this.lastAsk = la;
			} catch (e) { /* the in-memory throttle starts empty */ }
		});
	}

	kotakConfigured() { return String(this.env.KOTAK_CONSUMER_KEY || "").trim().length >= 10; }

	// Drop what has not been seen for 4 days (an expired weekly option, a retired symbol), so the board cannot fill for good. A weekend's last prices stay, showing their age.
	prune(now) {
		this.lastPrune = now;
		let gone = 0;
		const today = Number(istParts(now).date.replace(/-/g, ""));
		for (const [name, e] of this.quotes) {
			if (expiredOption(name, today)) { this.quotes.delete(name); gone += 1; continue; }        // an expired contract has no price to show, and at a roll its names must not keep the room the next expiry needs
			for (const s of ["z", "k"]) if (e[s] && now - e[s].at > STALE_MS) delete e[s];
			if (!e.z && !e.k) { this.quotes.delete(name); gone += 1; }
		}
		this.k.pruned += gone;
		this.series.prune(now);
		return gone;
	}

	put(name, src, q, onlyIfChanged) {
		const now = this.now();
		if (expiredOption(name, Number(istParts(now).date.replace(/-/g, "")))) return false;        // an old universe or a recorder cannot put an expired contract back (it would show until the next prune)
		let e = this.quotes.get(name);
		if (!e) {
			if (this.quotes.size >= MAX_TOTAL && !(now - this.lastPrune > 60000 && this.prune(now) > 0)) return false;      // full: make room from the stale ones, once a minute at most
			e = {};
			this.quotes.set(name, e);
		}
		const { lst, ...quote } = q;
		const prev = e[src];
		if (prev && onlyIfChanged && sameQuote(prev, quote)) { e[src] = { ...prev, ...quote, at: prev.at }; return true; }     // unchanged: it keeps its arrival time, and any field it lacked
		let at = now;
		if (!prev && Number.isFinite(lst)) at = Math.min(now, Math.max(lst, now - FIRST_SEEN_MS));      // first sight of a price Kotak itself dates: a last-known price is as old as it is
		e[src] = { ...quote, at };
		this.series.add(name, now, quote.ltp);
		return true;
	}

	async arm() {
		if (!this.kotakConfigured()) return;
		const cur = await this.state.storage.getAlarm();
		if (cur === null || cur === undefined) await this.state.storage.setAlarm(this.now() + 1000);
	}

	// Always re-arms itself, whatever happened (a poller that dies on one bad answer would be the failure this exists to remove), except when the key has been removed.
	// Backs off when Kotak refuses the key (a minute, doubling to 15) or rate-limits (15 s), so a bad key is not hammered all session.
	async alarm() {
		await this.ready;
		const t0 = this.now();
		let delay = 60000, rearm = true;
		try {
			this.prune(t0);
			await this.maybeFlush(t0);
			if (!this.kotakConfigured()) { this.k.status = "off"; rearm = false; }
			else if (!this.universe) this.k.status = "no universe";
			else if (!inSession(t0)) this.k.status = "idle";
			else {
				delay = 5000;
				await this.cycle();
				if (this.k.consecutive_auth > 0) delay = Math.min(900000, 60000 * 2 ** Math.min(this.k.consecutive_auth - 1, 4));
				else if (this.k.last_rate > 0) delay = 15000;
			}
		} catch (e) {
			this.k.last_error = "cycle failed";
			this.k.status = "down";
		} finally {
			if (rearm) try { await this.state.storage.setAlarm(this.now() + Math.max(500, delay - (this.now() - t0))); } catch (e) { /* the next request or the cron re-arms it */ }
		}
	}

	async cycle() {
		const poller = new KotakPoller({ key: this.env.KOTAK_CONSUMER_KEY, fetchFn: this.fetchFn || undefined, now: this.now, sleepFn: this.sleepFn || undefined });
		const r = await runCycle(poller, this.universe, this.cursor);
		this.cursor = r.next;
		const k = this.k;
		for (const [name, q] of r.updates) if (!this.put(name, "k", q, true)) k.refused += 1;      // a full board refuses new names: counted, and shown in /live/health
		k.consecutive_auth = r.errors.auth ? k.consecutive_auth + 1 : 0;
		k.last_rate = r.errors.rate || 0;
		k.cycles += 1; k.calls_ok += r.ok; k.calls_failed += r.failed; k.total_calls = r.total;
		for (const [kind, n] of Object.entries(r.errors)) k.errors[kind] = (k.errors[kind] || 0) + n;
		if (r.ok > 0) { k.last_ok = this.now(); k.consecutive_failed = 0; k.last_error = r.failed ? `${r.failed} of ${r.ok + r.failed} calls failed` : null; }
		else { k.consecutive_failed += 1; k.last_error = r.errors.auth ? "Kotak refused the key" : "no call succeeded"; }
		k.status = r.errors.auth ? "auth" : r.ok === 0 ? "down" : r.failed ? "degraded" : "ok";
		try { this.tally(this.now()); } catch (e) { /* a tally problem never costs the live view */ }
	}

	// How often the two brokers agree, kept per IST day: every Kotak cycle in the session counts the instruments for which BOTH sources are fresh (under FRESH_S) and how many of those
	// differ by more than a spread explains (TOL, the same rule as the "differ" flag). Counts only: no price, no name. The finished days stay for a week so a late reader still gets them.
	tally(now) {
		const day = istParts(now).date;
		if (!this.agree || this.agree.day !== day) {
			if (this.agree && this.agree.cycles > 0) this.agreeDays[this.agree.day] = this.agree;
			const keep = Object.keys(this.agreeDays).sort().slice(-7);
			this.agreeDays = Object.fromEntries(keep.map((d) => [d, this.agreeDays[d]]));
			this.agree = { day, cycles: 0, both: 0, disagree: 0, opt_both: 0, opt_disagree: 0, worst_cycle_pct: 0, first_at: now, last_at: now, peak: { z: {}, k: {} } };
		}
		const a = this.agree;
		let both = 0, dis = 0, ob = 0, od = 0;
		const fresh = { z: {}, k: {} };                                                     // names each source holds fresh, by segment (the wide universe arriving)
		for (const e of this.quotes.values()) {
			for (const src of ["z", "k"]) if (e[src] && (now - e[src].at) / 1000 <= FRESH_S) { const g = /^[a-z]{1,6}$/.test(String(e[src].s)) ? e[src].s : "other"; fresh[src][g] = (fresh[src][g] || 0) + 1; }
			if (!(e.z && e.k) || (now - e.z.at) / 1000 > FRESH_S || (now - e.k.at) / 1000 > FRESH_S || !(e.z.ltp > 0) || !(e.k.ltp > 0)) continue;
			const opt = e.z.s === "opt", bad = (Math.abs(e.z.ltp - e.k.ltp) / e.z.ltp) * 100 > (opt ? TOL.opt : TOL.other);
			both += 1; if (bad) dis += 1;
			if (opt) { ob += 1; if (bad) od += 1; }
		}
		for (const src of ["z", "k"]) for (const [g, n] of Object.entries(fresh[src])) if (n > (a.peak[src][g] || 0)) a.peak[src][g] = n;      // the most names fresh in any one cycle
		a.cycles += 1; a.both += both; a.disagree += dis; a.opt_both += ob; a.opt_disagree += od; a.last_at = now;
		if (both >= 20) a.worst_cycle_pct = Math.max(a.worst_cycle_pct, round2((dis / both) * 100));      // a cycle with a handful of pairs says nothing about the day
	}

	snapshot(now) {
		const quotes = Object.create(null);
		let newest = null;
		for (const [name, e] of this.quotes) {
			const z = e.z, k = e.k;
			const az = z ? (now - z.at) / 1000 : Infinity, ak = k ? (now - k.at) / 1000 : Infinity;
			const useZ = az <= ak;
			const p = useZ ? z : k, o = useZ ? k : z;
			const age = Math.max(0, Math.min(az, ak));
			const { at, ...rest } = p;
			const out = { ...rest, age_s: round1(age), src: useZ ? "z" : "k" };
			const label = (z && z.s) || (k && k.s);                                           // one label per instrument, Kite's first, so a row cannot hop between filters
			if (label) out.s = label;
			if (o) {
				const ao = Math.max(0, useZ ? ak : az);
				out.alt = { src: useZ ? "k" : "z", ltp: o.ltp, age_s: round1(ao) };
				if (ao <= FRESH_S && age <= FRESH_S && p.ltp > 0 && o.ltp > 0) {
					const d = (Math.abs(p.ltp - o.ltp) / p.ltp) * 100;
					if (d > (p.s === "opt" ? TOL.opt : TOL.other)) out.x = round2(d);          // the two brokers disagree by more than a spread can explain
					else {                                                                    // the other source fills what this one lacks, but never on a flagged row, and a bid and an ask only as a pair
						if (!("bid" in out) && !("ask" in out) && o.bid > 0 && o.ask >= o.bid) { out.bid = o.bid; out.ask = o.ask; for (const f of ["bid_qty", "ask_qty"]) if (f in o) out[f] = o[f]; }
						if (!("oi" in out) && "oi" in o) out.oi = o.oi;
					}
				}
			}
			quotes[name] = out;
			if (newest === null || age < newest) newest = age;
		}
		return { now, seq: this.seq, count: this.quotes.size, newest_age_s: newest === null ? null : round1(newest), quotes };
	}

	health(now) {
		const src = { z: { n: 0, newest: null }, k: { n: 0, newest: null } };
		let both = 0, disagree = 0;
		for (const e of this.quotes.values()) {
			for (const s of ["z", "k"]) if (e[s]) {
				const a = (now - e[s].at) / 1000;
				src[s].n += 1;
				if (src[s].newest === null || a < src[s].newest) src[s].newest = a;
			}
			if (e.z && e.k && (now - e.z.at) / 1000 <= FRESH_S && (now - e.k.at) / 1000 <= FRESH_S && e.z.ltp > 0 && e.k.ltp > 0) {
				both += 1;
				if ((Math.abs(e.z.ltp - e.k.ltp) / e.z.ltp) * 100 > (e.z.s === "opt" ? TOL.opt : TOL.other)) disagree += 1;
			}
		}
		const k = this.k;
		return {
			now, names: this.quotes.size,
			kite: { n: src.z.n, newest_age_s: src.z.newest === null ? null : round1(src.z.newest) },
			kotak: { configured: this.kotakConfigured(), status: k.status, n: src.k.n, newest_age_s: src.k.newest === null ? null : round1(src.k.newest), last_ok_age_s: k.last_ok === null ? null : round1((now - k.last_ok) / 1000),
				cycles: k.cycles, consecutive_auth: k.consecutive_auth, calls_ok: k.calls_ok, calls_failed: k.calls_failed, planned_calls: k.total_calls, errors: k.errors, last_error: k.last_error, refused: k.refused, pruned: k.pruned,
				universe: this.universe ? { asof: this.universe.asof, quotes: this.universe.quotes.length, chains: this.universe.chains.length } : null },
			both, disagree,
			agreement: { today: this.agree, days: this.agreeDays },
		};
	}

	// The chart series are written to storage at most every five minutes, and only the shards that changed (series.js). Never raises: a chart is not worth the board.
	async maybeFlush(now) {
		if (now - this.lastFlush < FLUSH_MS) return;
		this.lastFlush = now;
		try { await this.series.flush(this.state.storage); } catch (e) { /* the shards stay marked and the next flush tries again */ }
		try { await this.state.storage.put("agree", { today: this.agree, days: this.agreeDays }); } catch (e) { /* the in-memory tally still stands */ }
	}

	async fetch(request) {
		await this.ready;
		const now = this.now();
		const url = new URL(request.url), path = url.pathname;
		if (now - this.lastPrune > 5 * 60000) this.prune(now);                                  // also when only Kite is pushing and no alarm runs
		await this.maybeFlush(now);
		await this.arm().catch(() => {});
		if (path === "/news" || path === "/news/ingest") return this.news.handle(request, url, now);              // the news digest (news.js)
		if (path.startsWith("/paper/")) return this.book.handle(request, url, now);              // the paper-order queue (paper.js)
		if (request.method === "POST" && path === "/push") {                                    // Kite, from the recorder
			const { quotes, dropped } = await request.json();
			let added = 0, refused = 0;
			for (const [name, q] of Object.entries(quotes)) {
				if (this.put(name, "z", q, false)) added += 1; else refused += 1;
			}
			this.seq += 1;
			return reply(200, { ok: true, seq: this.seq, n: added, refused, dropped: dropped || 0 });
		}
		if (request.method === "POST" && path === "/universe") {
			const u = await request.json();
			this.universe = u;
			this.cursor = 0;
			await this.state.storage.put("universe", u);
			await this.arm().catch(() => {});
			return reply(200, { ok: true, quotes: u.quotes.length, chains: u.chains.length, kotak: this.kotakConfigured() });
		}
		if (request.method === "POST" && path === "/arm") return reply(200, { ok: true });
		if (request.method === "POST" && path === "/needs-universe") {
			const t = istParts(now);
			const asked = this.lastAsk !== undefined && now >= this.lastAsk && now - this.lastAsk < 40 * 60000;          // a stored time from the future (a clock fault) does not block the request for good
			const need = this.kotakConfigured() && ((t.dow >= 1 && t.dow <= 5) || Object.prototype.hasOwnProperty.call(SPECIAL_SESSIONS, t.date)) && t.mins >= 8 * 60 && t.mins < 15 * 60 + 35
				&& !(this.universe && this.universe.asof === t.date) && !asked;
			if (need) {
				this.lastAsk = now;
				try { await this.state.storage.put("lastAsk", now); } catch (e) { /* the in-memory throttle still holds */ }
			}
			return reply(200, { need });
		}
		if (path === "/series") {
			const name = url.searchParams.get("name") || "";
			return reply(200, { name, ...(SYMBOL.test(name) ? this.series.view(name) : { day: [], prev_close: null }) });
		}
		if (path === "/health") return reply(200, this.health(now));
		return reply(200, this.snapshot(now));
	}
}
