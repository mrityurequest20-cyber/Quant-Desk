// The desk's watchdog: the one thing that notices when the desk did NOT do something, and tells the owner.
//
// It runs inside the Cloudflare Worker (worker.js calls runWatchdog from the same cron firings that already start the
// desk), because the Worker has a clock that does not depend on GitHub's cron, which has been hours late on this
// repository. It READS GitHub's public workflow-run list and the published site's data.json, and it SENDS alerts. It never
// starts a trade, never touches a journal, and never holds a secret other than its own (the GitHub token the Worker
// already uses, and the ntfy topic).
//
// Two alert paths, deliberately independent of each other:
//   push   ntfy (https://docs.ntfy.sh), straight from the Worker, to the topic in the NTFY_TOPIC secret.
//   email  the Worker dispatches watchdog-alert.yml, which opens an issue as the Actions bot and assigns the owner, so
//          GitHub emails and pushes it (a personal token would not notify its own owner). P1 alerts and the weekly digest.
//
// Stateless on purpose (no storage to lose or corrupt): every check runs at fixed IST times, so each fires at most once a
// day. Messages are built from check names, workflow names, times and run links only: never a key, a journal value or a
// position. See docs/MASTER_PLAN.md section 3.

const IST_MS = 330 * 60 * 1000;
const DAY_MS = 86400000;
const DEFAULT_REPO = "mrityurequest20-cyber/Quant-Desk";

// NSE trading holidays, copied from config/quantdesk.yaml `calendar.holidays` (a test fails if they differ). A year whose
// list is not entered is not known: its weekdays are treated as trading days, as the desk does, and W9 asks for the list.
export const HOLIDAYS = ["2026-01-15", "2026-01-26", "2026-03-03", "2026-03-26", "2026-03-31", "2026-04-03", "2026-04-14",
	"2026-05-01", "2026-05-28", "2026-06-26", "2026-09-14", "2026-10-02", "2026-10-20", "2026-11-10", "2026-11-24", "2026-12-25"];
export const HOLIDAY_YEARS = [2026];

const p2 = (n) => String(n).padStart(2, "0");

// Wall clock in IST (UTC+05:30, no daylight saving) for a UTC millisecond timestamp.
export function ist(ms) {
	const d = new Date(ms + IST_MS);
	const date = `${d.getUTCFullYear()}-${p2(d.getUTCMonth() + 1)}-${p2(d.getUTCDate())}`;
	return { date, hhmm: `${p2(d.getUTCHours())}:${p2(d.getUTCMinutes())}`, dow: d.getUTCDay(), year: d.getUTCFullYear(),
		month: d.getUTCMonth() + 1, day: d.getUTCDate() };
}

const dowOf = (date) => new Date(`${date}T00:00:00Z`).getUTCDay();
export const isTradingDate = (date) => { const w = dowOf(date); return w >= 1 && w <= 5 && !HOLIDAYS.includes(date); };
const addDays = (date, n) => ist(Date.parse(`${date}T00:00:00Z`) + n * DAY_MS).date;
const prevWeekday = (date) => { let d = addDays(date, -1); while (dowOf(d) === 0 || dowOf(d) === 6) d = addDays(d, -1); return d; };

// Text that is safe in an HTTP header and a notification: printable ASCII only, clipped.
export function ascii(s, max = 200) {
	return String(s ?? "").replace(/[^\x20-\x7e]/g, " ").replace(/\s+/g, " ").trim().slice(0, max);
}

const link = (u) => (typeof u === "string" && /^https:\/\/github\.com\//.test(u) ? u : "");

// ---- reading GitHub and the site ---------------------------------------------------------------------------------------

function repoOf(env) { return String(env.GH_REPO || DEFAULT_REPO); }

async function ghGet(env, path, params = {}) {
	const url = new URL(`https://api.github.com/repos/${repoOf(env)}${path}`);
	for (const [k, v] of Object.entries(params)) url.searchParams.set(k, String(v));
	const headers = { accept: "application/vnd.github+json", "x-github-api-version": "2022-11-28", "user-agent": "quantdesk-watchdog" };
	const token = String(env.GH_DISPATCH_TOKEN || "").trim();
	if (token) headers.authorization = `Bearer ${token}`;          // the repository is public; the token only lifts the rate limit
	const res = await fetch(url.toString(), { headers });
	if (!res.ok) throw new Error(`GitHub GET ${path} answered ${res.status}`);
	return res.json();
}

const workflowRuns = async (env, file, params) => (await ghGet(env, `/actions/workflows/${file}/runs`, params)).workflow_runs || [];
const allRuns = async (env, params) => (await ghGet(env, "/actions/runs", params)).workflow_runs || [];

// pandas writes "2026-10-23 09:31:00.123456+05:30"; make it something every engine parses.
export function parseTs(ts) {
	if (typeof ts !== "string") return NaN;
	return Date.parse(ts.trim().replace(" ", "T").replace(/(\.\d{3})\d+/, "$1"));
}

async function readHeartbeat(env) {
	const origin = String(env.ORIGIN || "").replace(/\/+$/, "");
	if (!/^https:\/\//.test(origin)) throw new Error("ORIGIN is not set");
	const res = await fetch(`${origin}/data.json`, { cache: "no-store" });
	if (!res.ok) throw new Error(`published data.json answered ${res.status}`);
	const data = await res.json();
	return (data && data.state && data.state.heartbeat) || null;
}

// ---- the checks. Each returns a list of alerts: { sev: "P1"|"P2"|"INFO", check, title, body, link } -------------------------

const actionsUrl = (env, file) => `https://github.com/${repoOf(env)}/actions/workflows/${file}`;

// W1: a Live paper desk run exists today
async function w1DeskStarted(c) {
	const runs = await workflowRuns(c.env, "live.yml", { per_page: 10 });
	if (runs.some((r) => ist(Date.parse(r.created_at)).date === c.now.date)) return [];
	return [{ sev: "P1", check: "W1", title: "Desk not started",
		body: `No Live paper desk run exists for ${c.now.date} at ${c.now.hhmm} IST. The scheduler should have started it by now.`,
		link: actionsUrl(c.env, "live.yml") }];
}

// W2: the published heartbeat is fresh, the desk is not halted, the feed is the real one
async function w2Heartbeat(c) {
	const hb = await readHeartbeat(c.env);
	const at = parseTs(hb && hb.ts);
	if (!hb || Number.isNaN(at)) {
		return [{ sev: "P2", check: "W2", title: "Heartbeat unreadable",
			body: "The published data.json has no readable state.heartbeat.ts, so the desk's liveness cannot be checked from outside.", link: "" }];
	}
	const out = [];
	const ageMin = (c.nowMs - at) / 60000;
	if (ageMin > 10) {
		out.push({ sev: "P1", check: "W2", title: "Stale heartbeat",
			body: `The desk's last published heartbeat is ${Math.round(ageMin)} minutes old (limit 10) at ${c.now.hhmm} IST.`, link: actionsUrl(c.env, "live.yml") });
	}
	if (hb.halted === true) {
		out.push({ sev: "P1", check: "W2", title: "Desk halted",
			body: "The desk reports halted. Clearing a halt is the owner's decision (clear-halt workflow).", link: "" });
	}
	if (typeof hb.feed === "string" && hb.feed && !/kotak/i.test(hb.feed)) {
		out.push({ sev: "P2", check: "W2", title: "Feed fell back",
			body: `The desk's live feed is "${ascii(hb.feed, 40)}", not Kotak.`, link: "" });
	}
	return out;
}

// W3 and friends: a workflow that must run each trading day did, and did not fail
function ranToday(file, label, sev, check) {
	return async (c) => {
		const mine = (await workflowRuns(c.env, file, { per_page: 10 })).filter((r) => ist(Date.parse(r.created_at)).date === c.now.date);
		if (!mine.length) {
			return [{ sev, check, title: `${label} did not run`, body: `No ${label} run was created today (${c.now.date}).`, link: actionsUrl(c.env, file) }];
		}
		if (mine.some((r) => r.conclusion === "success" || r.status !== "completed")) return [];
		const last = mine[0];
		return [{ sev, check, title: `${label} failed`, body: `Every ${label} run today ended ${ascii(last.conclusion, 20)}.`, link: link(last.html_url) || actionsUrl(c.env, file) }];
	};
}

// W6: any watched workflow failed or was cancelled on main since the previous slot
const NOISE_CANCELLED = new Set(["Desk scheduler", "Publish site", "CI"]);       // cancelled by their own concurrency rules
async function w6Failures(c, since) {
	const sinceMs = Date.parse(`${c.now.date}T${since}:00+05:30`);
	const created = ist(sinceMs - DAY_MS).date;                                  // GitHub filters `created` by UTC date: look a day back
	const bad = [];
	for (const status of ["failure", "cancelled"]) {
		for (const r of await allRuns(c.env, { status, per_page: 100, created: `>=${created}` })) {
			if (r.head_branch !== "main" || Date.parse(r.updated_at) < sinceMs) continue;
			if (status === "cancelled" && NOISE_CANCELLED.has(r.name)) continue;
			bad.push(r);
		}
	}
	if (!bad.length) return [];
	const names = [...new Set(bad.map((r) => ascii(r.name, 40)))].slice(0, 8);
	return [{ sev: "P2", check: "W6", title: `${bad.length} workflow run(s) failed or cancelled`,
		body: `Since ${since} IST on main: ${names.join(", ")}.`, link: link(bad[0].html_url) || `https://github.com/${repoOf(c.env)}/actions` }];
}

// W7: credential expiry register (CRED_EXPIRY: {"NAME": "YYYY-MM-DD"}). Alerts as an expiry date is crossed into 14, 7, 2, 0 days.
async function w7Expiry(c) {
	let reg = {};
	try { reg = JSON.parse(String(c.env.CRED_EXPIRY || "{}")); } catch (e) {
		return [{ sev: "P2", check: "W7", title: "Credential expiry register unreadable", body: "CRED_EXPIRY is not valid JSON.", link: "" }];
	}
	const gap = c.now.dow === 1 ? 3 : 1;                                           // the Worker looks on weekdays: Monday follows Friday
	const out = [];
	for (const [name, date] of Object.entries(reg)) {
		if (!/^\d{4}-\d{2}-\d{2}$/.test(String(date))) continue;
		const days = Math.round((Date.parse(`${date}T00:00:00Z`) - Date.parse(`${c.now.date}T00:00:00Z`)) / DAY_MS);
		const crossed = [14, 7, 2, 0].find((t) => days <= t && days + gap > t);
		if (days < 0 || crossed !== undefined) {
			out.push({ sev: days <= 7 ? "P1" : "P2", check: "W7", title: days < 0 ? `${ascii(name, 40)} has expired` : `${ascii(name, 40)} expires in ${days} day(s)`,
				body: `Credential ${ascii(name, 40)} expires on ${date}. Renew it before then (the desk or the alarm clock stops without it).`, link: "" });
		}
	}
	return out;
}

// W8: the Saturday digest
async function w8Digest(c) {
	const days = [];
	for (let i = 0; i < 7; i++) days.push(addDays(c.now.date, -i));
	const expected = days.filter(isTradingDate);
	const runs = await workflowRuns(c.env, "live.yml", { per_page: 30 });
	const ran = new Set(runs.filter((r) => r.conclusion === "success").map((r) => ist(Date.parse(r.created_at)).date));
	const got = expected.filter((d) => ran.has(d)).length;
	const failed = await allRuns(c.env, { status: "failure", per_page: 100, created: `>=${addDays(c.now.date, -8)}` });
	const onMain = failed.filter((r) => r.head_branch === "main" && Date.parse(r.updated_at) >= c.nowMs - 7 * DAY_MS);
	return [{ sev: "INFO", check: "W8", title: "Weekly digest",
		body: `Sessions run ${got} of ${expected.length} expected in the last 7 days. Workflow runs failed on main: ${onMain.length}. Details: the learning bot's weekly and monthly reports, and docs/MASTER_PLAN.md section 8.`,
		link: `https://github.com/${repoOf(c.env)}/actions` }];
}

// W9: next year's holiday list is entered (15 Dec), and this year's (15 Jun)
async function w9Calendar(c) {
	const out = [];
	for (const [md, need] of [["12-15", c.now.year + 1], ["06-15", c.now.year]]) {
		const mark = `${c.now.year}-${md}`;
		if (c.now.date >= mark && prevWeekday(c.now.date) < mark && !HOLIDAY_YEARS.includes(need)) {
			out.push({ sev: "P2", check: "W9", title: `NSE ${need} holiday list not entered`,
				body: `calendar.holiday_years has no ${need}: the desk would treat ${need} holidays as trading days. Enter the dates from NSE's circular.`, link: "" });
		}
	}
	return out;
}

// Fixed IST times for each check. They must coincide with a cron firing in wrangler.jsonc (a test checks this).
//   days: "trading" = Mon-Fri not a holiday; "weekdays" = Mon-Fri; "saturday"
export const SLOTS = [
	{ at: "07:30", days: "weekdays", run: w7Expiry, check: "W7" },
	{ at: "07:30", days: "weekdays", run: w9Calendar, check: "W9" },
	{ at: "09:10", days: "trading", run: w1DeskStarted, check: "W1" },
	{ at: "09:30", days: "trading", run: w2Heartbeat, check: "W2" },
	{ at: "11:00", days: "trading", run: w2Heartbeat, check: "W2" },
	{ at: "13:00", days: "trading", run: w2Heartbeat, check: "W2" },
	{ at: "15:00", days: "trading", run: w2Heartbeat, check: "W2" },
	{ at: "16:00", days: "trading", run: ranToday("live.yml", "Live paper desk", "P1", "W3"), check: "W3" },
	{ at: "16:00", days: "trading", run: ranToday("collect-wide.yml", "Collect wide data", "P2", "W3"), check: "W3" },
	{ at: "16:00", days: "trading", run: (c) => w6Failures(c, "08:00"), check: "W6" },
	{ at: "18:00", days: "trading", run: ranToday("selfreview.yml", "Self-review", "P2", "W5"), check: "W5" },
	{ at: "18:00", days: "trading", run: (c) => w6Failures(c, "16:00"), check: "W6" },
	{ at: "21:00", days: "trading", run: ranToday("data.yml", "Data warehouse", "P2", "W5"), check: "W5" },
	{ at: "21:00", days: "trading", run: (c) => w6Failures(c, "18:00"), check: "W6" },
	{ at: "17:30", days: "saturday", run: w8Digest, check: "W8" },
];

function dayMatches(kind, now) {
	if (kind === "saturday") return now.dow === 6;
	if (kind === "weekdays") return now.dow >= 1 && now.dow <= 5;
	return isTradingDate(now.date);
}

// ---- sending ---------------------------------------------------------------------------------------------------------

const PRIORITY = { P1: "high", P2: "default", INFO: "low" };
const TAGS = { P1: "rotating_light", P2: "warning", INFO: "bar_chart" };

export async function pushNtfy(env, a) {
	const topic = String(env.NTFY_TOPIC || "").trim();
	if (!topic) return { ok: false, why: "NTFY_TOPIC is not set" };
	if (!/^[A-Za-z0-9_-]{8,64}$/.test(topic)) return { ok: false, why: "NTFY_TOPIC is not a valid topic name" };
	const server = String(env.NTFY_SERVER || "https://ntfy.sh").replace(/\/+$/, "");
	const headers = { Title: ascii(`${a.sev} ${a.check}: ${a.title}`, 120), Priority: PRIORITY[a.sev] || "default", Tags: TAGS[a.sev] || "warning" };
	if (link(a.link)) headers.Click = a.link;
	try {
		const res = await fetch(`${server}/${topic}`, { method: "POST", headers, body: ascii(a.body, 500) });
		return res.ok ? { ok: true, why: "ntfy accepted it" } : { ok: false, why: `ntfy answered ${res.status}` };
	} catch (e) {
		return { ok: false, why: "ntfy was unreachable" };
	}
}

// Email path: watchdog-alert.yml opens an issue as the Actions bot and assigns the owner.
export async function emailViaIssue(env, a, day, dispatchWorkflow) {
	return dispatchWorkflow(env, "watchdog-alert.yml", { severity: a.sev, check: a.check, title: ascii(a.title, 120),
		body: ascii(a.body, 600), link: link(a.link), day });
}

export async function sendAlert(env, a, day, dispatchWorkflow) {
	const push = await pushNtfy(env, a);
	let email;
	if (a.sev === "P2") email = { ok: false, why: "P2 goes by push only" };
	else if (typeof dispatchWorkflow !== "function") email = { ok: false, why: "no dispatcher" };
	else {
		try { email = await emailViaIssue(env, a, day, dispatchWorkflow); } catch (e) { email = { ok: false, why: "the email dispatch was unreachable" }; }
	}
	return { push, email };
}

// ---- entry point -----------------------------------------------------------------------------------------------------

// Run whatever is due at this firing. Never throws: a broken check is reported as an alert of its own, and nothing here may
// stop the Worker's other jobs.
export async function runWatchdog(event, env, deps = {}, log = console.log) {
	const nowMs = Math.floor((event.scheduledTime ?? Date.now()) / 60000) * 60000;
	const now = ist(nowMs);
	const dispatch = deps.dispatchWorkflow;
	const results = [];
	if (String(env.WATCHDOG_TEST || "") === "1") {                       // the drill: remove the variable after one alert arrives
		const a = { sev: "INFO", check: "TEST", title: "Watchdog test", body: `Test alert from the watchdog at ${now.date} ${now.hhmm} IST.`, link: "" };
		results.push({ check: "TEST", alerts: [a], sent: [await sendAlert(env, a, now.date, dispatch)] });
	}
	for (const slot of SLOTS) {
		if (slot.at !== now.hhmm || !dayMatches(slot.days, now)) continue;
		let alerts;
		try {
			alerts = await slot.run({ env, now, nowMs });
		} catch (e) {
			alerts = [{ sev: "P2", check: slot.check, title: "Watchdog could not run a check",
				body: `Check ${slot.check} at ${now.hhmm} IST failed to run: ${ascii(e && e.message, 120)}. The desk is not being watched for this.`, link: "" }];
		}
		const sent = [];
		for (const a of alerts) sent.push(await sendAlert(env, a, now.date, dispatch));
		results.push({ check: slot.check, alerts, sent });
	}
	for (const r of results) {
		const n = r.alerts.length;
		log(`watchdog ${r.check} ${now.date} ${now.hhmm} IST: ${n} alert(s)` + r.sent.map((s, i) =>
			` [${r.alerts[i].sev} push: ${s.push.why}; email: ${s.email.why}]`).join(""));
	}
	return results;
}
