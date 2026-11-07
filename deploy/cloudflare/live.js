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

import { KotakPoller, istParts, runCycle, inSession } from "./kotak.js";

const MAX_BODY = 524288;                // bytes of one push (a batch of ~800 quotes is about 100 KB)
const MAX_SYMBOLS = 3000;               // in one push
const MAX_TOTAL = 4000;                 // symbols the board will ever hold: a stolen ingest key cannot grow it without bound
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
export function cleanUniverse(b) {
	if (!b || typeof b !== "object") return null;
	const quotes = [], chains = [];
	for (const q of Array.isArray(b.quotes) ? b.quotes.slice(0, 3000) : []) {
		if (!q || typeof q !== "object" || !SYMBOL.test(String(q.n)) || !SEGMENTS.has(q.s) || !SEG_KOTAK.has(q.g) || !/^[A-Za-z0-9 &_.-]{1,40}$/.test(String(q.t))) continue;
		quotes.push({ n: q.n, s: q.s, g: q.g, t: String(q.t), ...(q.one === true ? { one: true } : {}) });
	}
	for (const c of Array.isArray(b.chains) ? b.chains.slice(0, 60) : []) {
		if (c && /^[A-Za-z0-9&_-]{1,24}$/.test(String(c.u)) && SEG_KOTAK.has(c.x) && /^\d{4}-\d{2}-\d{2}$/.test(String(c.e))) chains.push({ u: c.u, x: c.x, e: c.e });
	}
	if (!quotes.length && !chains.length) return null;
	const count = Math.min(30, Math.max(1, Math.trunc(Number(b.count)) || 10));
	return { asof: /^\d{4}-\d{2}-\d{2}$/.test(String(b.asof)) ? b.asof : null, quotes, chains, count };
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
	if (!url.pathname.startsWith("/live/")) return null;
	if (!configured(env)) return reply(503, { error: "the live view is not switched on" });
	const stub = env.LIVE.get(env.LIVE.idFromName("board"));
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
	return reply(404, { error: "no such live path" });
}

const round1 = (x) => Math.round(x * 10) / 10;
const round2 = (x) => Math.round(x * 100) / 100;
const sameQuote = (a, b) => ["ltp", "vol", "bid", "ask", "bid_qty", "ask_qty", "oi"].every((k) => a[k] === b[k]);

// The Durable Object: per instrument, the latest quote of each source and when it arrived. MEMORY ONLY for quotes: a wide universe is too big to rewrite to storage every
// five seconds, and the record of every tick is the recorder's Parquet, not this. After a restart the board fills again as instruments tick (seconds for a liquid one).
// Only the universe (what to poll) is stored. A quote keeps its own arrival time: Kite's is the moment a new tick arrives, Kotak's is refreshed only when its price, volume or
// book CHANGED, so a quiet instrument, a holiday or a dead feed grows an age instead of looking live. Age is the relay's, not the exchange's.
export class LiveBoard {
	constructor(state, env) {
		this.state = state;
		this.env = env || {};
		this.quotes = new Map();                    // name -> {z?: quote, k?: quote}, each with `at`
		this.seq = 0;
		this.now = () => Date.now();
		this.fetchFn = null;                        // test hooks for the Kotak poller
		this.sleepFn = null;
		this.universe = null;
		this.cursor = 0;
		this.k = { status: "off", cycles: 0, calls_ok: 0, calls_failed: 0, last_ok: null, last_error: null, errors: {}, consecutive_failed: 0, total_calls: 0 };
		this.ready = state.blockConcurrencyWhile(async () => {
			const u = await state.storage.get("universe");
			if (u && typeof u === "object" && Array.isArray(u.quotes)) this.universe = u;
		});
	}

	kotakConfigured() { return String(this.env.KOTAK_CONSUMER_KEY || "").trim().length >= 10; }

	put(name, src, q, onlyIfChanged) {
		let e = this.quotes.get(name);
		if (!e) {
			if (this.quotes.size >= MAX_TOTAL) return false;
			e = {};
			this.quotes.set(name, e);
		}
		const prev = e[src];
		if (onlyIfChanged && prev && sameQuote(prev, q)) return true;      // unchanged: it keeps its arrival time
		e[src] = { ...q, at: this.now() };
		return true;
	}

	async arm() {
		if (!this.kotakConfigured()) return;
		const cur = await this.state.storage.getAlarm();
		if (cur === null || cur === undefined) await this.state.storage.setAlarm(this.now() + 1000);
	}

	// Always re-arms itself, whatever happened: a poller that dies on one bad answer would be the failure this exists to remove.
	async alarm() {
		await this.ready;
		const t0 = this.now();
		let delay = 60000;
		try {
			if (!this.kotakConfigured()) this.k.status = "off";
			else if (!this.universe) this.k.status = "no universe";
			else if (!inSession(t0)) this.k.status = "idle";
			else { delay = 5000; await this.cycle(); }
		} catch (e) {
			this.k.last_error = "cycle failed";
			this.k.status = "down";
		} finally {
			try { await this.state.storage.setAlarm(this.now() + Math.max(500, delay - (this.now() - t0))); } catch (e) { /* the next request or the cron re-arms it */ }
		}
	}

	async cycle() {
		const poller = new KotakPoller({ key: this.env.KOTAK_CONSUMER_KEY, fetchFn: this.fetchFn || undefined, now: this.now, sleepFn: this.sleepFn || undefined });
		const r = await runCycle(poller, this.universe, this.cursor);
		this.cursor = r.next;
		for (const [name, q] of r.updates) this.put(name, "k", q, true);
		const k = this.k;
		k.cycles += 1; k.calls_ok += r.ok; k.calls_failed += r.failed; k.total_calls = r.total;
		for (const [kind, n] of Object.entries(r.errors)) k.errors[kind] = (k.errors[kind] || 0) + n;
		if (r.ok > 0) { k.last_ok = this.now(); k.consecutive_failed = 0; k.last_error = r.failed ? `${r.failed} of ${r.ok + r.failed} calls failed` : null; }
		else { k.consecutive_failed += 1; k.last_error = r.errors.auth ? "Kotak refused the key" : "no call succeeded"; }
		k.status = r.errors.auth ? "auth" : r.ok === 0 ? "down" : r.failed ? "degraded" : "ok";
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
			if (o) {
				const ao = Math.max(0, useZ ? ak : az);
				out.alt = { src: useZ ? "k" : "z", ltp: o.ltp, age_s: round1(ao) };
				if (ao <= FRESH_S && age <= FRESH_S && p.ltp > 0 && o.ltp > 0) {
					const d = (Math.abs(p.ltp - o.ltp) / p.ltp) * 100;
					if (d > (p.s === "opt" ? TOL.opt : TOL.other)) out.x = round2(d);          // the two brokers disagree by more than a spread can explain
					for (const f of ["bid", "ask", "bid_qty", "ask_qty", "oi"]) if (!(f in out) && f in o) out[f] = o[f];     // the other source's book fills what this one lacks
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
				cycles: k.cycles, calls_ok: k.calls_ok, calls_failed: k.calls_failed, planned_calls: k.total_calls, errors: k.errors, last_error: k.last_error,
				universe: this.universe ? { asof: this.universe.asof, quotes: this.universe.quotes.length, chains: this.universe.chains.length } : null },
			both, disagree,
		};
	}

	async fetch(request) {
		await this.ready;
		const now = this.now();
		const path = new URL(request.url).pathname;
		await this.arm().catch(() => {});
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
			const asked = this.lastAsk !== undefined && now - this.lastAsk < 40 * 60000;
			const need = this.kotakConfigured() && t.dow >= 1 && t.dow <= 5 && t.mins >= 8 * 60 && t.mins < 15 * 60 + 35
				&& !(this.universe && this.universe.asof === t.date) && !asked;
			if (need) this.lastAsk = now;
			return reply(200, { need });
		}
		if (path === "/health") return reply(200, this.health(now));
		return reply(200, this.snapshot(now));
	}
}
