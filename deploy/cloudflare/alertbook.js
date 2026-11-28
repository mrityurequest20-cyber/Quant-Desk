// MarketLens alerts, the relay's side (docs: marketlens/README.md, "Alerts"): the owner's rule settings, the keys of the
// alerts already sent (so each fires once a day), and the last few alerts sent, kept in the live relay's Durable Object
// beside the news and paper stores.
//
//   GET  /alerts/state   the rules and the recent log            (the app, READ key; the Worker's cron, internally)
//   PUT  /alerts/rules   the owner's settings                    (the app, READ key: the owner's own)
//   POST /alerts/sent    alerts the cron is about to push: answers which are new today and records them (internal only)
//
// Nothing here is a price or a position: rule ids, numbers within fixed ranges, and short alert texts the cron built.

const json = (status, body) => new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json", "cache-control": "no-store" } });
const IDS = new Set(["iv_extreme", "big_move", "gamma_flip", "curve_inverted", "ban", "mcx_move"]);
const NUMS = { hi: [0.5, 1], lo: [0, 0.5], mult: [1, 10], pts: [0, 0.2], near: [0.5, 1] };
const KEY = /^\d{4}-\d{2}-\d{2}:[a-z_]{2,20}:[A-Z0-9&_.-]{1,24}:[A-Za-z0-9-]{1,12}$/;
const TEXT = (x, n) => (typeof x === "string" ? x.replace(/[\u0000-\u001f\u007f]/g, " ").slice(0, n) : "");
export const MAX_LOG = 60;

export function cleanRules(list) {
	if (!Array.isArray(list)) return null;
	const out = [];
	for (const r of list.slice(0, 20)) {
		if (!r || typeof r !== "object" || !IDS.has(r.id)) continue;
		const c = { id: r.id };
		if (typeof r.on === "boolean") c.on = r.on;
		for (const [k, [lo, hi]] of Object.entries(NUMS)) if (typeof r[k] === "number" && Number.isFinite(r[k])) c[k] = Math.min(hi, Math.max(lo, r[k]));
		if (["indices", "all"].includes(r.scope)) c.scope = r.scope;
		out.push(c);
	}
	return out;
}

export class AlertBook {
	constructor(state) { this.state = state; this.chain = Promise.resolve(); }
	serial(fn) { const p = this.chain.then(fn, fn); this.chain = p.catch(() => {}); return p; }
	handle(request, url, now) { return this.serial(() => this.handle1(request, url, now)); }

	async handle1(request, url, now) {
		try {
			const route = request.method + " " + url.pathname;
			if (route === "GET /alerts/state") {
				const [rules, log] = await Promise.all([this.state.storage.get("alerts:rules"), this.state.storage.get("alerts:log")]);
				return json(200, { rules: Array.isArray(rules) ? rules : [], log: Array.isArray(log) ? log : [], now });
			}
			if (route === "PUT /alerts/rules") {
				const body = await request.json();
				const rules = cleanRules(body && body.rules);
				if (!rules) return json(400, { error: "rules must be a list" });
				await this.state.storage.put("alerts:rules", rules);
				return json(200, { ok: true, rules });
			}
			if (route === "POST /alerts/sent") {
				const body = await request.json();
				const list = (Array.isArray(body && body.alerts) ? body.alerts : []).slice(0, 40).filter((a) => a && KEY.test(String(a.key)));
				const seen = (await this.state.storage.get("alerts:seen")) || [];
				const day = new Date(now + 19800000).toISOString().slice(0, 10);
				const keep = seen.filter((k) => k.slice(0, 10) >= addDays(day, -2));            // three days of keys at most
				const have = new Set(keep);
				const fresh = list.filter((a) => !have.has(a.key));
				if (fresh.length) {
					const log = (await this.state.storage.get("alerts:log")) || [];
					const add = fresh.map((a) => ({ key: a.key, title: TEXT(a.title, 120), body: TEXT(a.body, 400), sev: ["P1", "P2", "INFO"].includes(a.sev) ? a.sev : "INFO", at: now }));
					await this.state.storage.put({ "alerts:seen": [...keep, ...fresh.map((a) => a.key)], "alerts:log": [...add.reverse(), ...log].slice(0, MAX_LOG) });
				} else if (keep.length !== seen.length) {
					await this.state.storage.put("alerts:seen", keep);
				}
				return json(200, { fresh: fresh.map((a) => a.key) });
			}
		} catch (e) {
			return json(503, { error: "the alert store is unavailable; nothing was changed" });
		}
		return json(404, { error: "no such alerts path" });
	}
}

function addDays(date, n) {
	const d = new Date(`${date}T00:00:00Z`);
	d.setUTCDate(d.getUTCDate() + n);
	return d.toISOString().slice(0, 10);
}
