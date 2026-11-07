// Kotak Neo market data for the live relay: the SECOND live source, polled from inside the Worker so it needs no GitHub runner, no cron and no daily login.
//
// Kotak's Trade API answers a plain GET with the app's consumer key (no TOTP, no MPIN, no static IP for market data). This file asks for live quotes (last price,
// five levels of book, volume, open interest, percent change) and index option chains, and turns each answer into the relay's quote shape. Response shapes are the
// ones quantdesk/intraday/kotak.py already parses (verified on a runner on 2 and 3 Oct 2026); limits are the ones noted there: 25 instruments a quotes call (the docs say
// 50, the live API took 25) and 25 requests a second.
//
// MARKET DATA ONLY. Only the two read endpoints below are ever called (quotes and option-chain); there is no order, position, holding, margin or profile call anywhere
// in this file, and the consumer key is never printed, logged, returned or put in an error. A test greps for all of that.
//
// A price is "fresh" only when it moved: the relay refreshes a Kotak quote's arrival time only if its price, volume or book changed since the last cycle, so a closed
// market, a holiday or a frozen instrument grows an age instead of looking live.

export const BASE = "https://mis.kotaksecurities.com";
export const BATCH = 25;
export const MAX_CALLS = 40;           // external requests in one alarm: a Worker's free plan allows 50 subrequests per invocation
export const MIN_GAP_MS = 45;          // between request starts: 25 a second is Kotak's limit, this is about 22
export const PARALLEL = 4;
const TIMEOUT_MS = 8000;
export const MON = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"];

// Kotak sends numbers as strings ("166.7500") and missing values as null, "" or "-".
export function num(x) {
	if (x === null || x === undefined || x === "" || x === "-" || typeof x === "boolean") return NaN;
	const v = Number(x);
	return Number.isFinite(v) ? v : NaN;
}

export class KotakError extends Error {
	constructor(kind, message) { super(message); this.kind = kind; }     // kind: auth | rate | net | shape | http
}

// IST wall-clock parts of an instant, without a time-zone database (IST is UTC+5:30 all year).
export function istParts(ms) {
	const d = new Date(ms + 5.5 * 3600e3);
	return { dow: d.getUTCDay(), mins: d.getUTCHours() * 60 + d.getUTCMinutes(), date: d.toISOString().slice(0, 10) };
}

// NSE and BSE derivatives trade 09:15 to 15:30 IST; the index quotes start with the pre-open. Poll from 09:00 to 15:35, Monday to Friday. Holidays are not listed here:
// on one nothing moves, so nothing is refreshed and every age grows (see the note at the top).
export function inSession(ms) {
	const t = istParts(ms);
	return t.dow >= 1 && t.dow <= 5 && t.mins >= 9 * 60 && t.mins < 15 * 60 + 35;
}

// "nse_cm|Nifty 50,nse_cm|2885" for a path: spaces become %20 but the bar and comma stay literal, as Kotak's gateway expects.
export function enc(batch) {
	return encodeURIComponent(batch).replace(/%7C/gi, "|").replace(/%2C/gi, ",");
}

// The one name both live sources use for an option, so a price from either lands on the same row: NIFTY12NOV2624500CE.
export function optionName(underlying, expiryIso, strike, side) {
	const [y, m, d] = String(expiryIso).slice(0, 10).split("-");
	return `${underlying}${d}${MON[Number(m) - 1]}${y.slice(2)}${Number.isInteger(strike) ? strike : String(strike)}${side}`;
}

export function best(q, side) {
	const lv = (((q && q.depth) || {})[side] || [{}])[0] || {};
	const v = num(lv.price);
	return v > 0 ? v : NaN;
}

function bestQty(q, side) {
	const lv = (((q && q.depth) || {})[side] || [{}])[0] || {};
	const v = num(lv.quantity ?? lv.qty);
	return v > 0 ? v : NaN;
}

// One Kotak quote row -> the relay's quote shape. null if there is no usable last price.
export function parseQuote(q) {
	if (!q || typeof q !== "object") return null;
	const ltp = num(q.ltp);
	if (!(ltp > 0)) return null;
	const out = { ltp };
	const b = best(q, "buy"), a = best(q, "sell");
	if (b > 0 && a >= b) { out.bid = b; out.ask = a; const bq = bestQty(q, "buy"), aq = bestQty(q, "sell"); if (bq > 0) out.bid_qty = bq; if (aq > 0) out.ask_qty = aq; }
	const vol = num(q.last_volume ?? q.volume ?? q.vol);
	if (vol >= 0) out.vol = vol;
	const oi = num(q.open_int);
	if (oi >= 0) out.oi = oi;
	const pc = num(q.per_change), ch = num(q.change);
	if (Number.isFinite(pc)) out.chg = pc;                                   // percent from the previous close, as Kite's `change`
	else if (Number.isFinite(ch) && ltp - ch > 0) out.chg = (ch / (ltp - ch)) * 100;
	return out;
}

// (common data, calls, puts) wherever they sit in an option-chain response.
export function chainParts(body) {
	const todo = [body];
	while (todo.length) {
		const x = todo.shift();
		if (Array.isArray(x)) { for (const v of x) if (v && typeof v === "object") todo.push(v); continue; }
		if (x && typeof x === "object") {
			const calls = x.call ?? x.calls, puts = x.put ?? x.puts;
			if (Array.isArray(calls) || Array.isArray(puts)) return { common: x.common_data || x.commonData || {}, calls: calls || [], puts: puts || [] };
			for (const v of Object.values(x)) if (v && typeof v === "object") todo.push(v);
		}
	}
	return { common: {}, calls: [], puts: [] };
}

// An option-chain response -> [{strike, side, ltp, vol, oi}]. The chain already carries each contract's last price, volume and open interest.
export function parseChain(body) {
	const { calls, puts } = chainParts(body);
	const rows = [];
	for (const [side, items] of [["CE", calls], ["PE", puts]]) {
		for (const item of items) {
			const ins = item.instrument || item.inst || {};
			const strike = num(ins.strikePrice ?? ins.strkPrc);
			if (!(strike > 0)) continue;
			const q = item.quote || {}, oi = item.openInterest || item.oi || {};
			const ltp = num(q.ltp);
			if (!(ltp > 0)) continue;
			const row = { strike, side, ltp };
			const vol = num(q.volume ?? q.vol);
			if (vol >= 0) row.vol = vol;
			const cur = num(oi.current ?? oi.cur);
			if (cur >= 0) row.oi = cur;
			rows.push(row);
		}
	}
	return rows;
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

export class KotakPoller {
	// `fetchFn` and `now` are injectable so tests need no network and no clock.
	constructor({ key, fetchFn, now, sleepFn } = {}) {
		this.key = String(key || "").trim();
		this.fetchFn = fetchFn || ((...a) => fetch(...a));
		this.now = now || (() => Date.now());
		this.sleep = sleepFn || sleep;
		this.lastStart = 0;
	}

	// Every request starts at least MIN_GAP_MS after the previous one, whichever worker asks.
	async pace() {
		const wait = this.lastStart + MIN_GAP_MS - this.now();
		this.lastStart = Math.max(this.now(), this.lastStart + MIN_GAP_MS);
		if (wait > 0) await this.sleep(wait);
	}

	async get(path, params) {
		await this.pace();
		let url = `${BASE}/${path}`;
		if (params) url += "?" + new URLSearchParams(params).toString();
		let res;
		try {
			res = await this.fetchFn(url, { headers: { Authorization: this.key, accept: "application/json" }, signal: AbortSignal.timeout(TIMEOUT_MS) });
		} catch (e) {
			throw new KotakError("net", `network (${e && e.name ? e.name : "error"})`);       // the class only: never a URL, never the key
		}
		if (res.status === 401 || res.status === 403) throw new KotakError("auth", `HTTP ${res.status}`);
		if (res.status === 429) throw new KotakError("rate", "HTTP 429");
		let body;
		try { body = await res.json(); } catch (e) { throw new KotakError("shape", `HTTP ${res.status}, not JSON`); }
		if (res.status !== 200) throw new KotakError("http", `HTTP ${res.status}`);
		if (body && typeof body === "object" && !Array.isArray(body)) {
			const err = body.Error || body.error || body["Error Message"] || body.errMsg;
			if (err) throw new KotakError("http", "Kotak answered with an error");
		}
		return body;
	}

	// [{g: segment, t: token or index name}] -> the quote rows, as sent.
	async quotes(items) {
		const batch = items.map((i) => `${i.g}|${i.t}`).join(",");
		const body = await this.get(`script-details/1.0/quotes/neosymbol/${enc(batch)}/all`);
		const rows = Array.isArray(body) ? body : (body && Array.isArray(body.data) ? body.data : []);
		return rows.filter((r) => r && typeof r === "object");
	}

	async chain(underlying, exchange, expiryIso, count) {
		return this.get("market-data/1.0/watchlist/option-chain", { exchange, underlying, instrument_type: "option", count: String(count), expiry: expiryIso });
	}
}

// The calls one cycle makes. The universe is {quotes: [{n, s, g, t, one?}], chains: [{u, x, e}], count}. Instruments flagged `one` (indices, asked for by name) go one to a call,
// because the answer carries the token, not the name; the rest go 25 to a call. When the plan is longer than MAX_CALLS it is rotated, so each item is refreshed within
// ceil(plan / MAX_CALLS) cycles and no cycle exceeds the subrequest limit.
export function plan(universe, cursor) {
	const calls = [];
	const singles = (universe.quotes || []).filter((q) => q.one), many = (universe.quotes || []).filter((q) => !q.one);
	for (const q of singles) calls.push({ kind: "q", items: [q] });
	for (let i = 0; i < many.length; i += BATCH) calls.push({ kind: "q", items: many.slice(i, i + BATCH) });
	for (const c of universe.chains || []) calls.push({ kind: "c", chain: c });
	if (calls.length <= MAX_CALLS) return { calls, next: 0, total: calls.length };
	const start = cursor % calls.length;
	const picked = [];
	for (let k = 0; k < MAX_CALLS; k++) picked.push(calls[(start + k) % calls.length]);
	return { calls: picked, next: (start + MAX_CALLS) % calls.length, total: calls.length };
}

// Run one planned cycle. Returns {updates: [[name, quote]], ok, failed, errors: {kind: count}}. Never throws: a failed call is counted and the rest go on.
export async function runCycle(poller, universe, cursor) {
	const { calls, next, total } = plan(universe, cursor);
	const byKey = new Map();
	for (const q of universe.quotes || []) if (!q.one) byKey.set(`${q.g}|${q.t}`, q);
	const updates = [];
	const errors = {};
	let ok = 0, failed = 0, i = 0;
	const count = universe.count || 10;
	const work = async () => {
		while (i < calls.length) {
			const c = calls[i++];
			try {
				if (c.kind === "q") {
					const rows = await poller.quotes(c.items);
					for (const r of rows) {
						const quote = parseQuote(r);
						if (!quote) continue;
						const it = c.items.length === 1 && c.items[0].one ? c.items[0] : byKey.get(`${r.exchange}|${r.exchange_token}`);
						if (it) updates.push([it.n, { ...quote, s: it.s }]);
					}
				} else {
					const u = c.chain;
					for (const r of parseChain(await poller.chain(u.u, u.x, u.e, count))) updates.push([optionName(u.u, u.e, r.strike, r.side), { ltp: r.ltp, ...(r.vol !== undefined ? { vol: r.vol } : {}), ...(r.oi !== undefined ? { oi: r.oi } : {}), s: "opt" }]);
				}
				ok += 1;
			} catch (e) {
				failed += 1;
				const kind = e instanceof KotakError ? e.kind : "shape";
				errors[kind] = (errors[kind] || 0) + 1;
				if (kind === "auth") i = calls.length;                       // a refused key is refused for every call: stop asking this cycle
			}
		}
	};
	await Promise.all(Array.from({ length: Math.min(PARALLEL, calls.length) }, work));
	return { updates, ok, failed, errors, next, total };
}
