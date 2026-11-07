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
export function configured(env) {
	const i = String(env.LIVE_INGEST_TOKEN || "").trim(), r = String(env.LIVE_READ_TOKEN || "").trim();
	return !!env.LIVE && i.length >= MIN_SECRET && r.length >= MIN_SECRET && i !== r;
}

// Keep only what the app shows, as numbers: anything else in a push is dropped, never stored.
export function clean(body) {
	if (!body || typeof body !== "object" || !body.quotes || typeof body.quotes !== "object" || Array.isArray(body.quotes)) return null;
	const names = Object.keys(body.quotes);
	if (!names.length || names.length > MAX_SYMBOLS) return null;
	const out = Object.create(null);                                                   // no prototype: a symbol named __proto__ or constructor is plain data
	for (const name of names) {
		if (!SYMBOL.test(name)) return null;
		const q = body.quotes[name];
		if (!q || typeof q !== "object") return null;
		const row = {};
		for (const k of NUMBERS) if (typeof q[k] === "number" && Number.isFinite(q[k])) row[k] = q[k];
		if (typeof q.t === "string" && q.t.length <= 40) row.t = q.t;                // the exchange's timestamp, shown as is
		if (typeof q.s === "string" && SEGMENTS.has(q.s)) row.s = q.s;               // what kind of instrument: index, stock, future, option, MCX, currency
		if (!("ltp" in row)) return null;                                              // a quote without a last price is not a quote
		out[name] = row;
	}
	return out;
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
		const raw = await request.text();
		if (new TextEncoder().encode(raw).length > MAX_BODY) return reply(413, { error: "too large" });      // bytes, not UTF-16 units
		let body;
		try { body = JSON.parse(raw); } catch (e) { return reply(400, { error: "not JSON" }); }
		const quotes = clean(body);
		if (!quotes) return reply(400, { error: "not a snapshot" });
		return stub.fetch("https://live/push", { method: "POST", body: JSON.stringify({ quotes }) });
	}
	if (url.pathname === "/live/snapshot") {
		if (request.method !== "GET") return reply(405, { error: "GET only" });
		if (!(await same(bearer(request), String(env.LIVE_READ_TOKEN).trim()))) return reply(401, { error: "no" });
		return stub.fetch("https://live/snapshot");
	}
	return reply(404, { error: "no such live path" });
}

// The Durable Object: the latest quote of each symbol and when it arrived. MEMORY ONLY: a wide universe is too big to rewrite to storage every five seconds, and
// the record of every tick is the recorder's Parquet, not this. After a restart the board fills again as symbols tick (seconds for a liquid one).
// A quote keeps its own arrival time, and the recorder only sends quotes whose tick is new, so replaying an old one is never done by this code.
// (Kite may send a last-known tick when it connects: that would show as fresh. Age is the relay's, not the exchange's; `t` is sent so it can be compared.)
export class LiveBoard {
	constructor(state, env) {
		this.quotes = new Map();
		this.seq = 0;
	}

	async fetch(request) {
		const now = Date.now();
		if (request.method === "POST") {
			const { quotes } = await request.json();
			let added = 0, refused = 0;
			for (const [name, q] of Object.entries(quotes)) {
				if (!this.quotes.has(name) && this.quotes.size >= MAX_TOTAL) { refused += 1; continue; }
				this.quotes.set(name, { ...q, at: now });
				added += 1;
			}
			this.seq += 1;
			return reply(200, { ok: true, seq: this.seq, n: added, refused });
		}
		const quotes = Object.create(null);
		let newest = null;
		for (const [name, q] of this.quotes) {
			const { at, ...rest } = q;
			const age = Math.max(0, (now - at) / 1000);
			quotes[name] = { ...rest, age_s: Math.round(age * 10) / 10 };
			if (newest === null || age < newest) newest = age;
		}
		return reply(200, { now, seq: this.seq, count: this.quotes.size, newest_age_s: newest === null ? null : Math.round(newest * 10) / 10, quotes });
	}
}
