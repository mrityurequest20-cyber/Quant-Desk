// The intraday price series behind the app's per-instrument chart: one close per minute for every instrument the relay sees, kept for the last two trading days.
//
// DISPLAY ONLY, like the rest of the live view (live.js): nothing here is read by the paper desk or any trading code. It is a window onto the prices the relay
// already holds, not a record: the record of every tick is the recorder's Parquet. A chart is a line of closes, one per minute, taken from the relay's own clock when a
// changed price arrived, so a quiet instrument or a dead feed shows as a flat gap, never as invented points.
//
// Memory is bounded three ways: at most MAX_BARS minutes per instrument (16 hours: a whole MCX evening), at most MAX_BARS_TOTAL minutes in all (about 36 bytes a minute
// in the heap: 29 MB; once the total is reached a name that is already charted gives up its own oldest minute for each new one, and a new name is not charted), and only the
// last two trading days of an instrument. A series is stored flat, [minute, close, minute,
// close, ...], two numbers a minute. It survives the object being evicted: 48 shards in the object's storage, each written at most every five minutes and only if it
// changed, and read back (and re-validated, because storage is not trusted either) when the object starts.

export const MAX_BARS = 960;
export const MAX_BARS_TOTAL = 800000;
export const SHARDS = 48;
export const FLUSH_MS = 5 * 60000;
const KEEP_MS = 4 * 86400e3;                                   // an instrument not seen for 4 days loses its series, with its quote
const IST_MS = 19800000, DAY_MS = 86400000;

export const shardKeys = () => Array.from({ length: SHARDS }, (_, i) => `bars:${i}`);
export function shardOf(name) {
	let h = 5381;
	for (let i = 0; i < name.length; i++) h = (((h << 5) + h) + name.charCodeAt(i)) >>> 0;
	return h % SHARDS;
}
const dayOf = (minute) => Math.floor((minute * 60000 + IST_MS) / DAY_MS);          // the IST calendar day of an epoch minute

export class Series {
	constructor() {
		this.m = new Map();                                    // name -> [minute, close, minute, close, ...]
		this.total = 0;                                        // minutes held, over every name
		this.dirty = new Set();                                // shards changed since they were last written
	}

	// A changed price arrived at `ms`. Returns false if it was not taken (not a price, a point older than the last one, or the total is full).
	add(name, ms, px) {
		if (typeof px !== "number" || !Number.isFinite(px) || px <= 0 || !Number.isFinite(ms)) return false;
		const minute = Math.floor(ms / 60000);
		let a = this.m.get(name);
		if (!a) {
			if (this.total >= MAX_BARS_TOTAL) return false;
			a = [];
			this.m.set(name, a);
		}
		const n = a.length;
		if (n && a[n - 2] === minute) a[n - 1] = px;                                     // the same minute: the close moves
		else if (n && a[n - 2] > minute) return false;                                   // a point from the past (the clock stepped back): ignored
		else {
			if (n && dayOf(a[n - 2]) !== dayOf(minute)) this.trimToLastDay(a);           // a new trading day: only the day before it stays
			a.push(minute, px);
			this.total += 1;
			if (a.length > MAX_BARS * 2) { const drop = a.length - MAX_BARS * 2; a.splice(0, drop); this.total -= drop / 2; }
			if (this.total > MAX_BARS_TOTAL && a.length > 2) { a.splice(0, 2); this.total -= 1; }               // the total is full: this name's oldest minute makes room for its newest
		}
		this.dirty.add(shardOf(name));
		return true;
	}

	trimToLastDay(a) {
		const last = dayOf(a[a.length - 2]);
		let i = 0;
		while (i < a.length && dayOf(a[i]) < last) i += 2;
		if (i) { a.splice(0, i); this.total -= i / 2; }
	}

	// What the chart shows: the latest day's closes, and the close of the day before (the baseline for the day's change).
	view(name) {
		const a = this.m.get(name);
		if (!a || !a.length) return { day: [], prev_close: null };
		const last = dayOf(a[a.length - 2]), day = [];
		let prev = null;
		for (let i = 0; i < a.length; i += 2) {
			if (dayOf(a[i]) === last) day.push([a[i], a[i + 1]]);
			else prev = a[i + 1];
		}
		return { day, prev_close: prev };
	}

	// Forget instruments not seen for 4 days (the same horizon as their quotes).
	prune(ms) {
		const cut = Math.floor((ms - KEEP_MS) / 60000);
		for (const [name, a] of this.m) {
			if (!a.length || a[a.length - 2] < cut) {
				this.total -= a.length / 2;
				this.m.delete(name);
				this.dirty.add(shardOf(name));
			}
		}
	}

	shard(i) {
		const o = {};
		for (const [name, a] of this.m) if (shardOf(name) === i) o[name] = a;
		return o;
	}

	// Read back what storage holds. Every series is re-checked: finite, positive, minutes strictly rising, even length, not past the cap.
	load(entries) {
		for (const v of entries instanceof Map ? entries.values() : Object.values(entries || {})) {
			if (!v || typeof v !== "object" || Array.isArray(v)) continue;
			for (const [name, a] of Object.entries(v)) {
				if (this.m.has(name) || !Array.isArray(a) || a.length < 2 || a.length % 2) continue;
				if (this.total + a.length / 2 > MAX_BARS_TOTAL) continue;
				const clean = [];
				for (let i = 0; i < a.length && clean.length < MAX_BARS * 2; i += 2) {
					const t = a[i], p = a[i + 1];
					if (!Number.isInteger(t) || typeof p !== "number" || !Number.isFinite(p) || p <= 0) continue;
					if (clean.length && t <= clean[clean.length - 2]) continue;
					clean.push(t, p);
				}
				if (clean.length) { this.m.set(name, clean); this.total += clean.length / 2; }
			}
		}
	}

	// Write the changed shards, each on its own. A shard with nothing left is deleted. A shard that fails stays marked, and the next flush tries it again.
	async flush(storage) {
		if (!this.dirty.size) return 0;
		const todo = [...this.dirty];
		this.dirty.clear();
		let done = 0;
		for (const i of todo) {                                                         // one shard at a time: a shard that fails (too big, a storage fault) does not take the others with it
			try {
				const o = this.shard(i);
				if (Object.keys(o).length) await storage.put(`bars:${i}`, o); else await storage.delete(`bars:${i}`);
				done += 1;
			} catch (e) {
				this.dirty.add(i);
			}
		}
		return done;
	}
}
