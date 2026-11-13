// The relay's paper-order queue (docs/RECORDING.md, "The paper runner"). PAPER MONEY ONLY: nothing here talks to a broker; it holds the owner's orders until the runner
// (quantdesk/paperlink, on GitHub Actions) takes them through the risk gate, and keeps the paper account and its results for the app to show.
//
//   POST /paper/order   the app (READ key)    queue one order            -> {queued, id, pending}
//   POST /paper/kill    the app (READ key)    set or clear the kill flag -> {kill}
//   GET  /paper/state   the app (READ key)    the summary, recent results, pending orders, kill
//   GET  /paper/queue   the runner (INGEST)   {kill, orders, now}
//   POST /paper/result  the runner (INGEST)   what happened to an order; removes it from the queue
//   POST /paper/state   the runner (INGEST)   {summary, account?}: refuses an account whose ledger is shorter than, or does not extend, the one held
//   GET  /paper/state?full=1  the runner (INGEST)  the summary and the full saved account (to restore from)
//
// The relay validates the SHAPE of everything that crosses it and stamps the queue time itself; every rule about whether a trade happens is the Python risk gate's.
// All of it lives in the same Durable Object as the live board (class LiveBoard), in storage, so it survives a restart. No secret and no price is stored here.

export const MAX_PENDING = 20;
export const MAX_QUEUE_BYTES = 90000;           // the whole queue is one stored value (limit 128 KiB): a full queue of big packages must not make the next order fail
export const MAX_QUEUE_BYTES_EXIT = 120000;     // ...and a sale always has room above that, so an exit can be queued when the queue is full
export const MAX_RESULTS = 50;                     // kept results: with the reason caps below, the stored value stays far under a Durable Object's 128 KiB limit
export const MAX_LAB = 120000;                     // characters: AUTO v2's strategy record (quantdesk/paper/auto2.py), one stored value (128 KiB at most), ASCII only
export const MAX_RESULTS_BYTES = 100000;           // characters of JSON in the stored results (far under a stored value's 128 KiB even with wide characters)
export const MAX_SEEN = 1000;                      // order ids remembered as used (about 70 KB stored)
export const MAX_SUMMARY = 60000;                  // characters
export const CHUNK = 100000;                       // characters per stored piece of the account (a stored value is limited to 128 KiB; the account is ASCII only, so a character is a byte)
export const MAX_CHUNKS = 12;
const ID = /^[A-Za-z0-9_-]{6,64}$/;
const NAME = /^[A-Z0-9][A-Z0-9&_.-]{2,39}$/;
const STATUS = new Set(["filled", "refused", "expired", "invalid", "done"]);
const isStr = (x, lo, hi) => typeof x === "string" && x.trim().length >= lo && x.length <= hi;
const isNum = (x) => typeof x === "number" && Number.isFinite(x);

// The shape of one order from the app. Unknown fields are dropped; the runner checks the same things again and is the authority.
export function cleanOrder(o) {
	if (!o || typeof o !== "object" || Array.isArray(o)) return null;
	if (!(typeof o.id === "string" && ID.test(o.id))) return null;
	if (o.side === "package") return cleanPackage(o);
	if (o.side !== "buy" && o.side !== "sell") return null;
	if (!(typeof o.symbol === "string" && NAME.test(o.symbol))) return null;
	const all = o.side === "sell" && o.lots === "all";
	if (!all && !(Number.isInteger(o.lots) && o.lots >= 1 && o.lots <= 1000)) return null;
	const out = { id: o.id, side: o.side, symbol: o.symbol, lots: o.lots };
	if (o.side === "buy") {
		if (!isStr(o.strategy, 1, 60) || !isStr(o.thesis, 20, 1000)) return null;
		out.strategy = o.strategy.trim();
		out.thesis = o.thesis.trim();
	}
	if (o.limit !== undefined && o.limit !== null) { if (!(isNum(o.limit) && o.limit > 0)) return null; out.limit = o.limit; }
	if (o.group !== undefined && o.group !== null) { if (!isStr(o.group, 1, 40)) return null; out.group = o.group.trim(); }
	// what the trader saw when deciding (used only to report slippage; a bad one is dropped, the order still goes)
	if (o.ref && typeof o.ref === "object" && !Array.isArray(o.ref) && isNum(o.ref.bid) && isNum(o.ref.ask) && o.ref.bid > 0 && o.ref.bid <= o.ref.ask) {
		out.ref = { bid: o.ref.bid, ask: o.ref.ask };
		if (isNum(o.ref.at) && o.ref.at > 0 && o.ref.at < 4e12) out.ref.at = o.ref.at;
	}
	return out;
}

// A package: several legs, bought and sold, opened together or not at all. The runner checks every rule again; this is only the shape.
function cleanPackage(o) {
	if (!Array.isArray(o.legs) || o.legs.length < 1 || o.legs.length > 50) return null;
	if (!isStr(o.strategy, 1, 60) || !isStr(o.thesis, 20, 1000)) return null;
	const legs = [], seen = new Set();
	for (const l of o.legs) {
		if (!l || typeof l !== "object" || Array.isArray(l)) return null;
		if (l.side !== "buy" && l.side !== "sell") return null;
		if (!(typeof l.symbol === "string" && NAME.test(l.symbol)) || seen.has(l.symbol)) return null;
		if (!(Number.isInteger(l.lots) && l.lots >= 1 && l.lots <= 1000)) return null;
		seen.add(l.symbol);
		const leg = { symbol: l.symbol, side: l.side, lots: l.lots };
		const r = l.ref;
		if (r && typeof r === "object" && !Array.isArray(r) && isNum(r.bid) && isNum(r.ask) && r.bid > 0 && r.bid <= r.ask) {
			leg.ref = { bid: r.bid, ask: r.ask };
			if (isNum(r.at) && r.at > 0 && r.at < 4e12) leg.ref.at = r.at;
		}
		legs.push(leg);
	}
	const out = { id: o.id, side: "package", legs, strategy: o.strategy.trim(), thesis: o.thesis.trim() };
	if (o.net_limit !== undefined && o.net_limit !== null) { if (!isNum(o.net_limit)) return null; out.net_limit = o.net_limit; }
	return out;
}

function cleanFill(f) {
	if (!f || typeof f !== "object" || Array.isArray(f)) return null;
	const fill = {};
	for (const k of ["seq", "qty", "price", "fees"]) if (isNum(f[k])) fill[k] = f[k];
	for (const k of ["kind", "ts", "symbol"]) if (typeof f[k] === "string") fill[k] = f[k].slice(0, 60);
	const sl = f.slip;
	if (sl && typeof sl === "object" && !Array.isArray(sl)) {
		fill.slip = {};
		for (const k of SLIP_KEYS) if (isNum(sl[k])) fill.slip[k] = sl[k];
		if (sl.side === "buy" || sl.side === "sell") fill.slip.side = sl.side;
	}
	return fill;
}

export const SLIP_KEYS = ["qty", "fill", "touch", "mid", "impact_ticks", "spread", "impact", "delay_s", "delay", "shown", "total_vs_seen", "seen_bid", "seen_ask", "spread_inr", "impact_inr", "delay_inr", "shown_inr", "total_inr", "bps"];

export function cleanResult(r) {
	if (!r || typeof r !== "object" || Array.isArray(r)) return null;
	if (!(typeof r.id === "string" && ID.test(r.id)) || !STATUS.has(r.status)) return null;
	const reasons = Array.isArray(r.reasons) ? r.reasons.filter((x) => typeof x === "string").slice(0, 5).map((x) => x.slice(0, 200)) : [];
	const fill = cleanFill(r.fill);
	const out = { id: r.id, status: r.status, reasons, fill, at: typeof r.at === "string" ? r.at.slice(0, 40) : null };
	if (Array.isArray(r.fills)) out.fills = r.fills.slice(0, 50).map(cleanFill).filter(Boolean);        // a package reports one fill per leg
	return out;
}

// {summary, account?}. The summary is shown to the app, so it must be a plain object of bounded size with a whole-number ledger length; the account, if sent, is a JSON text
// whose ledger has exactly that many rows. (The chain's hashes are verified by the runner when it restores; here only the SHAPE and the prefix rule are checked.)
export function cleanState(b) {
	if (!b || typeof b !== "object" || Array.isArray(b)) return null;
	const s = b.summary;
	if (!s || typeof s !== "object" || Array.isArray(s) || !Number.isInteger(s.ledger_len) || s.ledger_len < 0) return null;
	const text = JSON.stringify(s);
	if (text.length > MAX_SUMMARY) return null;
	const out = { summary: JSON.parse(text) };
	if (b.account !== undefined && b.account !== null) {
		if (typeof b.account !== "string" || b.account.length > CHUNK * MAX_CHUNKS || /[^\x00-\x7f]/.test(b.account)) return null;      // ASCII only (the runner writes JSON with every other character escaped): a character is a byte, a chunk fits a stored value
		let acct;
		try { acct = JSON.parse(b.account); } catch (e) { return null; }
		if (!acct || !Array.isArray(acct.ledger) || acct.ledger.length !== s.ledger_len) return null;
		if (!acct.ledger.every((r) => r && typeof r.hash === "string")) return null;
		out.account = b.account;
		out.hashes = acct.ledger.map((r) => r.hash);
	}
	return out;
}

const json = (status, body) => new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json", "cache-control": "no-store" } });

// The queue, results, kill flag and account, kept in the Durable Object's storage, each under its own key and each bounded, so one cannot starve another and the kill flag is
// never held hostage by a big value. A storage READ that fails is never cached as "empty" (it would then be saved over the real state): every request fails with 503 until a read
// succeeds. A WRITE is made before memory changes, so a failed write changes nothing and a retry is not told "already used".
export class PaperBook {
	constructor(state) {
		this.state = state;
		this.d = null;                             // {queue, results, kill, seen}
		this.chain = Promise.resolve();            // every request runs one at a time (see serial): a write awaits storage, and a second request must not decide from the state before it
	}

	serial(fn) {
		const run = this.chain.then(fn, fn);
		this.chain = run.then(() => {}, () => {});
		return run;
	}

	async load() {
		if (this.d) return;
		const s = this.state.storage;
		const [queue, results, kill, seen] = [await s.get("paper:queue"), await s.get("paper:results"), await s.get("paper:kill"), await s.get("paper:seen")];     // a throw here is not caught: nothing is cached
		this.d = {
			queue: Array.isArray(queue) ? queue.map(cleanQueued).filter(Boolean).slice(0, MAX_PENDING) : [],
			results: Array.isArray(results) ? results.map(cleanResult).filter(Boolean).slice(-MAX_RESULTS) : [],
			kill: kill === true,
			seen: Array.isArray(seen) ? seen.filter((x) => typeof x === "string" && ID.test(x)).slice(-MAX_SEEN) : [],
		};
	}

	handle(request, url, now) {
		return this.serial(() => this.handle1(request, url, now));
	}

	async handle1(request, url, now) {
		try { await this.load(); } catch (e) { return json(503, { error: "paper storage is unavailable; nothing was changed" }); }
		const p = url.pathname, m = request.method;
		try {
			if (p === "/paper/order" && m === "POST") return await this.order(await request.json(), now);
			if (p === "/paper/kill" && m === "POST") return await this.setKill(await request.json());
			if (p === "/paper/queue" && m === "GET") return json(200, { kill: this.d.kill === true, orders: this.d.queue, now });
			if (p === "/paper/result" && m === "POST") return await this.result(await request.json());
			if (p === "/paper/state" && m === "POST") return await this.putState(await request.json(), now);
			if (p === "/paper/state" && m === "GET") return await this.getState(url.searchParams.get("full") === "1", now);
			if (p === "/paper/lab" && m === "POST") return await this.putLab(await request.json(), now);
			if (p === "/paper/lab" && m === "GET") { const lab = await this.state.storage.get("paper:lab"); return json(200, { lab: typeof lab === "string" ? lab : null, now }); }
		} catch (e) {
			return json(500, { error: "the paper store could not complete that; nothing was changed" });       // storage failed: memory is untouched (see below)
		}
		return json(404, { error: "no such paper path" });
	}

	async order(raw, now) {
		const o = cleanOrder(raw);
		if (!o) return json(400, { error: "not a valid order" });
		if (this.d.seen.includes(o.id) || this.d.queue.some((q) => q.id === o.id) || this.d.results.some((r) => r.id === o.id)) return json(409, { error: "that order id was already used" });
		if (this.d.queue.length >= MAX_PENDING || JSON.stringify(this.d.queue).length + JSON.stringify(o).length > (o.side === "sell" ? MAX_QUEUE_BYTES_EXIT : MAX_QUEUE_BYTES)) return json(429, { error: "too many orders are waiting" });
		const queue = [...this.d.queue, { ...o, queued_at: now }], seen = [...this.d.seen, o.id].slice(-MAX_SEEN);
		await this.state.storage.put({ "paper:queue": queue, "paper:seen": seen });                         // both or neither
		this.d.queue = queue; this.d.seen = seen;
		return json(200, { queued: true, id: o.id, pending: queue.length });
	}

	async setKill(b) {
		if (!b || typeof b.on !== "boolean") return json(400, { error: "on must be true or false" });
		await this.state.storage.put("paper:kill", b.on);
		this.d.kill = b.on;
		return json(200, { kill: this.d.kill });
	}

	async result(raw) {
		const r = cleanResult(raw);
		if (!r) return json(400, { error: "not a valid result" });
		const queue = this.d.queue.filter((q) => q.id !== r.id);
		let results = [...this.d.results.filter((x) => x.id !== r.id), r].slice(-MAX_RESULTS);
		while (results.length > 1 && JSON.stringify(results).length > MAX_RESULTS_BYTES) results = results.slice(1);      // by size too: the oldest go first, so the list can never grow past a stored value's limit
		const seen = this.d.seen.includes(r.id) ? this.d.seen : [...this.d.seen, r.id].slice(-MAX_SEEN);
		await this.state.storage.put({ "paper:queue": queue, "paper:results": results, "paper:seen": seen });
		this.d.queue = queue; this.d.results = results; this.d.seen = seen;
		return json(200, { ok: true, pending: queue.length });
	}

	async heldAccount() {
		const meta = await this.state.storage.get("paper:meta");
		if (!meta || !Number.isInteger(meta.n) || meta.n < 1 || meta.n > MAX_CHUNKS) return { meta: null, text: null };
		const keys = Array.from({ length: meta.n }, (_, i) => "paper:acct:" + i);
		const got = await this.state.storage.get(keys);
		const parts = keys.map((k) => got.get(k));
		return { meta, text: parts.every((x) => typeof x === "string") ? parts.join("") : null };
	}

	// AUTO v2's strategy record: {"lab": "<json text>"}. Kept as text (the runner re-validates every entry when it reads it back: storage is not trusted), bounded and ASCII only.
	async putLab(raw, now) {
		const lab = raw && typeof raw === "object" ? raw.lab : null;
		if (typeof lab !== "string" || lab.length > MAX_LAB || /[^\x20-\x7e]/.test(lab)) return json(400, { error: "not a valid strategy record" });
		let o;
		try { o = JSON.parse(lab); } catch (e) { return json(400, { error: "not a valid strategy record" }); }
		if (!o || typeof o !== "object" || o.v !== 1 || !o.stats || typeof o.stats !== "object" || Array.isArray(o.stats)) return json(400, { error: "not a valid strategy record" });
		await this.state.storage.put("paper:lab", lab);
		return json(200, { saved: true, chars: lab.length, now });
	}

	async putState(raw, now) {
		const c = cleanState(raw);
		if (!c) return json(400, { error: "not a valid state" });
		const held = await this.heldAccount();
		const heldLen = held.meta ? held.meta.ledger_len : 0;
		if (c.summary.ledger_len < heldLen) return json(409, { error: "shorter ledger than the one held", held: heldLen });
		const writes = {};
		if (c.account !== undefined) {
			if (c.hashes.length < heldLen) return json(409, { error: "shorter ledger than the one held", held: heldLen });
			if (heldLen > 0) {                                                              // the new chain must extend the held one: the same hash at every held row
				let old = null;
				try { old = JSON.parse(held.text).ledger.map((r) => r.hash); } catch (e) { /* an unreadable held account cannot be extended safely */ }
				if (!old || old.length !== heldLen) return json(409, { error: "the account held cannot be read: the owner must look", held: heldLen });
				for (let i = 0; i < heldLen; i++) if (c.hashes[i] !== old[i]) return json(409, { error: "a different history from the one held", held: heldLen });
			}
			const n = Math.max(1, Math.ceil(c.account.length / CHUNK));
			for (let i = 0; i < n; i++) writes["paper:acct:" + i] = c.account.slice(i * CHUNK, (i + 1) * CHUNK);
			writes["paper:meta"] = { n, ledger_len: c.summary.ledger_len };
		} else if (c.summary.ledger_len > heldLen) {
			return json(409, { error: "the summary is ahead of the account held: send the account", held: heldLen });
		}
		writes["paper:summary"] = { ...c.summary, received_at: now };
		await this.state.storage.put(writes);
		return json(200, { ok: true, ledger_len: c.summary.ledger_len });
	}

	async getState(full, now) {
		const summary = (await this.state.storage.get("paper:summary")) || null;
		const base = { summary, results: this.d.results.slice(-30), pending: this.d.queue.map((q) => ({ id: q.id, side: q.side, symbol: q.side === "package" ? `${q.legs.length} legs` : q.symbol, lots: q.lots, queued_at: q.queued_at })), kill: this.d.kill === true, now };
		if (!full) return json(200, base);
		const held = await this.heldAccount();
		return json(200, { summary, account: held.text, kill: this.d.kill === true, now });
	}
}

function cleanQueued(q) {                                    // storage is not trusted either
	const o = cleanOrder(q);
	return o && isNum(q.queued_at) ? { ...o, queued_at: q.queued_at } : null;
}
