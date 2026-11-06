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
// The latest snapshot is kept in one Durable Object (class LiveBoard, binding LIVE) because a Worker has no memory shared between requests.
// Ages are worked out here, from this Worker's clock when each quote arrived, so a stale feed shows as stale whatever the phone's clock says.

const MAX_BODY = 65536;                 // bytes of one push
const MAX_SYMBOLS = 100;
const SYMBOL = /^[A-Za-z0-9&_.:-]{1,32}$/;
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
	const out = {};
	for (const name of names) {
		if (!SYMBOL.test(name)) return null;
		const q = body.quotes[name];
		if (!q || typeof q !== "object") return null;
		const row = {};
		for (const k of NUMBERS) if (typeof q[k] === "number" && Number.isFinite(q[k])) row[k] = q[k];
		if (typeof q.t === "string" && q.t.length <= 40) row.t = q.t;                // the exchange's timestamp, shown as is
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
		const raw = await request.text();
		if (raw.length > MAX_BODY) return reply(413, { error: "too large" });
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

// The Durable Object: the latest quote of each symbol and when it arrived. Replaying the same quote does not make it look fresh,
// because the recorder only sends quotes that changed (see quantdesk/data/live_push.py) and each keeps its own arrival time.
export class LiveBoard {
	constructor(state, env) {
		this.state = state;
		this.snap = { quotes: {}, seq: 0 };
		this.ready = state.blockConcurrencyWhile(async () => {
			const saved = await state.storage.get("snap");
			if (saved && typeof saved === "object" && saved.quotes) this.snap = saved;
		});
	}

	async fetch(request) {
		await this.ready;
		const now = Date.now();
		if (request.method === "POST") {
			const { quotes } = await request.json();
			for (const [name, q] of Object.entries(quotes)) this.snap.quotes[name] = { ...q, at: now };
			this.snap.seq += 1;
			await this.state.storage.put("snap", this.snap);
			return reply(200, { ok: true, seq: this.snap.seq, n: Object.keys(quotes).length });
		}
		const quotes = {};
		let newest = null;
		for (const [name, q] of Object.entries(this.snap.quotes)) {
			const { at, ...rest } = q;
			const age = Math.max(0, (now - at) / 1000);
			quotes[name] = { ...rest, age_s: Math.round(age * 10) / 10 };
			if (newest === null || age < newest) newest = age;
		}
		return reply(200, { now, seq: this.snap.seq, newest_age_s: newest === null ? null : Math.round(newest * 10) / 10, quotes });
	}
}
