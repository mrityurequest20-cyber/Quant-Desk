// Which feed serves which part of the market.
//
// The board can hold a price for one instrument from several brokers' feeds at once. Each feed has a one-letter code; a ROUTE says, for a kind of instrument, which feeds may be
// shown and in what order of preference. The first feed in the route whose price is fresh is the one shown; if none is fresh the freshest of the route is shown, with its age; a
// feed that is not in the route is never shown for that kind (it is still kept, counted in /live/health and compared). So one broker can carry the index options, another the
// commodities, and a third stand behind both, and a dead feed is stepped over without anyone doing anything.
//
// The table is data, not code: config/quantdesk.yaml `feeds.routes` is the source of truth, wrangler.jsonc carries the same table to the Worker as the FEED_ROUTES variable (a
// test compares the two), and a Worker with no such variable falls back to "freshest wins among every feed", which is how the board behaved when it only knew Kite and Kotak.
//
// DISPLAY ONLY: a route decides which price is SHOWN. It gives no feed the ability to place an order; no feed here has one.

// The feeds the board knows by code. A new broker is one line here, one in config/quantdesk.yaml `feeds.sources`, and an adapter that POSTs {"src": "<code>", "quotes": {...}} to /live/ingest.
export const SOURCES = { z: "Kite", k: "Kotak", u: "Upstox", d: "Dhan", a: "Angel One", f: "Fyers" };
export const PUSH_SOURCES = new Set(["z", "u", "d", "a", "f"]);          // feeds that push to /live/ingest; "k" is polled by the board itself and cannot be pushed, so a pusher can never pose as it
export const SEGMENT_KEYS = ["idx", "eq", "fut", "bfo", "mcx", "cds", "opt"];

// {segment: [code, ...]} from the Worker variable (a JSON string, or an object in tests). Anything malformed is dropped: an unknown segment, an unknown code, a repeat. null = no routes.
export function parseRoutes(raw) {
	let o = raw;
	if (typeof raw === "string") { if (!raw.trim()) return null; try { o = JSON.parse(raw); } catch (e) { return null; } }
	if (!o || typeof o !== "object" || Array.isArray(o)) return null;
	const out = {};
	for (const seg of SEGMENT_KEYS) {
		if (!Array.isArray(o[seg])) continue;
		const list = [];
		for (const c of o[seg]) if (typeof c === "string" && Object.prototype.hasOwnProperty.call(SOURCES, c) && !list.includes(c)) list.push(c);
		if (list.length) out[seg] = list;
	}
	return Object.keys(out).length ? out : null;
}

const ORDER = Object.keys(SOURCES);
// The freshest of a list of {src, age}; on a tie the feed listed first in SOURCES (Kite), so a row never flips between two feeds that are equally fresh.
export const freshest = (list) => list.reduce((b, x) => (x.age < b.age || (x.age === b.age && ORDER.indexOf(x.src) < ORDER.indexOf(b.src)) ? x : b), list[0]);
// Which feed's price to show for one instrument. `have` = [{src, age}] (age in seconds, of each feed that holds it), `route` = the segment's ordered codes or undefined.
// Returns the chosen src (null only when no feed holds it). When the route allows none of the feeds that hold it, the freshest of all is shown: a mis-set route can never blank the board.
export function pick(have, route, freshS) {
	if (!have.length) return null;
	if (!route || !route.length) return freshest(have).src;
	const allowed = route.map((c) => have.find((x) => x.src === c)).filter(Boolean);
	if (!allowed.length) return freshest(have).src;
	const fresh = allowed.find((x) => x.age <= freshS);
	return (fresh || freshest(allowed)).src;
}
// How far down a route a feed sits (0 = first choice); a feed not in the route ranks last. With no route every feed ranks the same.
export const rank = (src, route) => { if (!route) return 0; const i = route.indexOf(src); return i < 0 ? 99 : i; };
