// One-minute candles (open, high, low, close, volume) behind the app's instrument page, for today's session of every instrument that is not an option.
//
// DISPLAY ONLY, like the rest of the live view (live.js): nothing here is read by the paper desk or any trading code. It is a window onto the prices the relay already holds, not a
// record: the record of every tick is the recorder's Parquet.
//
// How a candle is made. A feed sends the latest price of an instrument every few seconds, and (the Kite recorder does) the highest and lowest tick since its previous push. So:
//   open    the first price the relay heard in the minute
//   high    the highest of every pushed high (or price, when a feed sends none) in the minute; low the same way
//   close   the last price heard in the minute
//   volume  the rise in the day's cumulative volume across the minute, never negative. The first sighting of a name, a change of feed and a day whose counter restarted have no baseline,
//           so that one minute counts nothing rather than a guess.
// A feed that only polls (no high/low of its own) gives a candle whose wick is the range of what was polled, not of every trade: the reply says which, per name (`exact`).
// A quiet instrument or a dead feed leaves a gap; a minute nobody traded is never invented.
//
// Memory is bounded: MAX_CANDLES minutes per name (16 hours: a whole MCX day), MAX_CANDLES_TOTAL in all (six numbers a minute, about 60 bytes in the heap: 18 MB). Once the total is
// reached a name already charted gives up its own oldest minute for each new one and a new name is not charted. Only the latest IST day is kept: the day before is the line chart's
// job (series.js keeps its close). Stored flat, [minute, o, h, l, c, v, ...], in the object's storage in shards, like the line series, so a deploy or an eviction in the session
// does not empty the charts.

import { shardOf, SHARDS } from "./series.js";

export const MAX_CANDLES = 960;
export const MAX_CANDLES_TOTAL = 300000;
export const W = 6;                                                // numbers per candle
const IST_MS = 19800000, DAY_MS = 86400000, KEEP_MS = 4 * 86400e3;

export const candleKeys = () => Array.from({ length: SHARDS }, (_, i) => `cndl:${i}`);
const dayOf = (minute) => Math.floor((minute * 60000 + IST_MS) / DAY_MS);
const pos = (x) => typeof x === "number" && Number.isFinite(x) && x > 0;

export class Candles {
	constructor() {
		this.m = new Map();                                        // name -> [minute, o, h, l, c, v, ...]
		this.cum = new Map();                                      // name -> the day's cumulative volume when it was last heard (the baseline for the next rise)
		this.exact = new Map();                                    // name -> true when its feed sends the high and low of its own ticks
		this.total = 0;
		this.dirty = new Set();
	}

	// A price arrived at `ms`: q = {ltp, hi?, lo?, vol?}. `rebase` = the volume counter is not comparable with the one before (another feed took over). Returns false if it was not taken.
	add(name, ms, q, rebase) {
		if (!q || !pos(q.ltp) || !Number.isFinite(ms)) return false;
		const px = q.ltp, minute = Math.floor(ms / 60000);
		let hi = pos(q.hi) ? Math.max(q.hi, px) : px, lo = pos(q.lo) ? Math.min(q.lo, px) : px;
		if (hi > px * 1.2 || lo < px * 0.8) { hi = px; lo = px; }                          // a window extreme a fifth away from the price is a bad tick, not a wick
		let a = this.m.get(name);
		if (!a) {
			if (this.total >= MAX_CANDLES_TOTAL) return false;
			a = [];
			this.m.set(name, a);
		}
		const n = a.length;
		if (n && a[n - W] > minute) return false;                                          // a point from the past (the clock stepped back): ignored
		const vol = typeof q.vol === "number" && Number.isFinite(q.vol) && q.vol >= 0 ? q.vol : null, before = this.cum.get(name);
		const newDay = n > 0 && dayOf(a[n - W]) !== dayOf(minute);
		let dv = 0;
		if (vol !== null && before !== undefined && !rebase && !newDay && vol >= before) dv = vol - before;
		if (vol !== null) this.cum.set(name, vol);
		this.exact.set(name, pos(q.hi) && pos(q.lo));
		if (n && a[n - W] === minute) {
			if (hi > a[n - 4]) a[n - 4] = hi;
			if (lo < a[n - 3]) a[n - 3] = lo;
			a[n - 2] = px;
			a[n - 1] += dv;
		} else {
			if (newDay) { this.total -= n / W; a.length = 0; }                              // a new trading day: yesterday's candles go
			a.push(minute, px, hi, lo, px, dv);
			this.total += 1;
			if (a.length > MAX_CANDLES * W) { const drop = a.length - MAX_CANDLES * W; a.splice(0, drop); this.total -= drop / W; }
			if (this.total > MAX_CANDLES_TOTAL && a.length > W) { a.splice(0, W); this.total -= 1; }
		}
		this.dirty.add(shardOf(name));
		return true;
	}

	// What the chart shows: today's candles as rows [minute, o, h, l, c, v], from `since` (an epoch minute) on when given, so a page that already holds the day asks only for the tail.
	view(name, since) {
		const a = this.m.get(name), rows = [];
		if (!a) return { candles: rows, exact: false };
		const from = Number.isFinite(since) ? since : -Infinity;
		for (let i = 0; i < a.length; i += W) if (a[i] >= from) rows.push([a[i], a[i + 1], a[i + 2], a[i + 3], a[i + 4], a[i + 5]]);
		return { candles: rows, exact: this.exact.get(name) === true };
	}

	prune(ms) {
		const cut = Math.floor((ms - KEEP_MS) / 60000);
		for (const [name, a] of this.m) {
			if (!a.length || a[a.length - W] < cut) {
				this.total -= a.length / W;
				this.m.delete(name); this.cum.delete(name); this.exact.delete(name);
				this.dirty.add(shardOf(name));
			}
		}
	}

	shard(i) {
		const o = {};
		for (const [name, a] of this.m) if (shardOf(name) === i && a.length) o[name] = a;
		return o;
	}

	// Read back what storage holds. Storage is not trusted: every candle is re-checked (whole minutes strictly rising, positive prices, low <= open, close <= high, volume not negative).
	load(entries) {
		for (const v of entries instanceof Map ? entries.values() : Object.values(entries || {})) {
			if (!v || typeof v !== "object" || Array.isArray(v)) continue;
			for (const [name, a] of Object.entries(v)) {
				if (this.m.has(name) || !Array.isArray(a) || a.length < W || a.length % W) continue;
				const clean = [];
				for (let i = 0; i < a.length && clean.length < MAX_CANDLES * W; i += W) {
					const [t, o, h, l, c, vol] = a.slice(i, i + W);
					if (!Number.isInteger(t) || !pos(o) || !pos(h) || !pos(l) || !pos(c) || !(typeof vol === "number" && Number.isFinite(vol) && vol >= 0)) continue;
					if (l > Math.min(o, c) || h < Math.max(o, c)) continue;
					if (clean.length && t <= clean[clean.length - W]) continue;
					clean.push(t, o, h, l, c, vol);
				}
				if (!clean.length || this.total + clean.length / W > MAX_CANDLES_TOTAL) continue;
				this.m.set(name, clean);
				this.total += clean.length / W;
			}
		}
	}

	async flush(storage) {
		if (!this.dirty.size) return 0;
		const todo = [...this.dirty];
		this.dirty.clear();
		let done = 0;
		for (const i of todo) {                                                             // one shard at a time: a shard that fails does not take the others with it
			try {
				const o = this.shard(i);
				if (Object.keys(o).length) await storage.put(`cndl:${i}`, o); else await storage.delete(`cndl:${i}`);
				done += 1;
			} catch (e) {
				this.dirty.add(i);
			}
		}
		return done;
	}
}

// ---- the order book of one instrument: up to five levels a side, [price, quantity, orders] -------------------------------------------------------------------------------
// Bids are kept best (highest) first and offers best (lowest) first, whatever order they arrive in. A level without a positive price and a whole, non-negative quantity is dropped;
// a book whose best bid is above its best offer is a bad quote and is refused whole.
export const DEPTH_LEVELS = 5;
export function cleanDepth(d) {
	if (!d || typeof d !== "object" || Array.isArray(d)) return null;
	const side = (rows, desc) => {
		const out = [];
		for (const r of Array.isArray(rows) ? rows.slice(0, 20) : []) {
			if (!Array.isArray(r) || !pos(r[0]) || !(typeof r[1] === "number" && Number.isFinite(r[1]) && r[1] >= 0)) continue;
			const n = typeof r[2] === "number" && Number.isFinite(r[2]) && r[2] >= 0 ? Math.round(r[2]) : 0;
			if (r[1] > 0) out.push([r[0], Math.round(r[1]), n]);
		}
		out.sort((x, y) => (desc ? y[0] - x[0] : x[0] - y[0]));
		return out.slice(0, DEPTH_LEVELS);
	};
	const b = side(d.b, true), a = side(d.a, false);
	if (!b.length && !a.length) return null;
	if (b.length && a.length && b[0][0] > a[0][0]) return null;
	return { b, a };
}
