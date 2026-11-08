// The relay's news digest (docs/LIVE.md, "The news digest"): the day's market headlines as read by the desk's news engine (quantdesk/premarket/newsdigest.py), kept so the app can show them beside the live board.
//
//   POST /news/ingest  the news job (INGEST key)  the digest
//   GET  /news         the app (READ key)         the latest digest, with when the relay got it
//
// PUBLIC headlines only: titles and https links, never article text; no price, no account, no secret. The relay validates the SHAPE of everything (the job is trusted no more than a browser would be), keeps ONE digest
// (the newest replaces the last), cuts it to a size that fits a stored value even with wide characters, and answers 503 when storage cannot be read rather than treating that as "no news".

export const MAX_ITEMS = 80;
export const MAX_CHARS = 60000;                // of JSON: far under a Durable Object value's 128 KiB even at two bytes a character
const ISO = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/;
const SYMBOL = /^[A-Z0-9][A-Z0-9&-]{1,19}$/;
const LINK = /^https:\/\/[^\s<>"'\\]{4,500}$/;
const CTRL = /[\u0000-\u001f\u007f\u2028\u2029]/g;
const str = (x, max) => (typeof x === "string" ? x.replace(CTRL, " ").replace(/\s+/g, " ").trim().slice(0, max) : "");
const num = (x, lo, hi) => (typeof x === "number" && Number.isFinite(x) && x >= lo && x <= hi ? x : null);

export function cleanItem(r) {
	if (!r || typeof r !== "object" || Array.isArray(r)) return null;
	const title = str(r.title, 220);
	if (!title || !/^[0-9a-f]{12}$/.test(String(r.id)) || !ISO.test(String(r.ts))) return null;
	const tone = num(r.tone, -1, 1), novelty = num(r.novelty, 0, 1);
	if (tone === null) return null;
	const sources = (Array.isArray(r.sources) ? r.sources : []).map((s) => str(s, 40)).filter(Boolean).slice(0, 6);
	return {
		id: r.id, ts: r.ts, source: str(r.source, 40), sources: sources.length ? sources : [str(r.source, 40)].filter(Boolean), title,
		link: typeof r.link === "string" && LINK.test(r.link) ? r.link : "", tone, tone_from: r.tone_from === "surprise" ? "surprise" : "words",
		impact: ["low", "medium", "high"].includes(r.impact) ? r.impact : "low", recap: r.recap === true, event: /^[a-z][a-z _-]{0,23}$/i.test(String(r.event)) ? String(r.event) : "general",
		novelty: novelty === null ? 1 : novelty, symbols: (Array.isArray(r.symbols) ? r.symbols : []).filter((s) => typeof s === "string" && SYMBOL.test(s)).slice(0, 8),
	};
}

// The digest as the relay keeps it: a fresh object of known fields, newest first, cut (oldest first) until it fits.
export function cleanDigest(b) {
	if (!b || typeof b !== "object" || Array.isArray(b) || b.v !== 1 || !ISO.test(String(b.asof)) || !Array.isArray(b.items)) return null;
	const items = b.items.map(cleanItem).filter(Boolean).sort((x, y) => (x.ts < y.ts ? 1 : x.ts > y.ts ? -1 : 0)).slice(0, MAX_ITEMS);
	const sources = {};
	for (const [k, v] of Object.entries(b.sources && typeof b.sources === "object" && !Array.isArray(b.sources) ? b.sources : {}).slice(0, 20)) { const kk = str(k, 40), vv = str(v, 60); if (kk && vv) sources[kk] = vv; }
	const out = { v: 1, asof: b.asof, sources, items };
	while (out.items.length > 1 && JSON.stringify(out).length > MAX_CHARS) out.items.pop();
	out.n = out.items.length;
	return out.items.length && JSON.stringify(out).length <= MAX_CHARS ? out : null;
}

const json = (status, body) => new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json", "cache-control": "no-store" } });

// One digest in the Durable Object's storage. Requests run one at a time (the same chain as the paper book).
export class NewsBook {
	constructor(state) { this.state = state; this.chain = Promise.resolve(); }

	serial(fn) { const run = this.chain.then(fn, fn); this.chain = run.then(() => {}, () => {}); return run; }

	handle(request, url, now) { return this.serial(() => this.handle1(request, url, now)); }

	async handle1(request, url, now) {
		try {
			if (url.pathname === "/news/ingest" && request.method === "POST") {
				const d = cleanDigest(await request.json());
				if (!d) return json(400, { error: "not a valid digest" });
				await this.state.storage.put("news", { digest: d, stored_at: now });
				return json(200, { ok: true, n: d.n });
			}
			if (url.pathname === "/news" && request.method === "GET") {
				const held = await this.state.storage.get("news");
				const d = held && typeof held === "object" ? cleanDigest(held.digest) : null;
				return json(200, { digest: d, stored_at: d && Number.isFinite(held.stored_at) ? held.stored_at : null, now });
			}
		} catch (e) {
			return json(503, { error: "the news store is unavailable; nothing was changed" });
		}
		return json(404, { error: "no such news path" });
	}
}
