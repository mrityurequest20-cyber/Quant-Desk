/* QuantDesk: the phone app for the intraday options desk.
 * Desk: account, the desk's stance per index, open positions, global pulse, headlines.
 * Chart: candles with VWAP, levels and trade markers; the desk's read, its evidence, key levels, quant.
 * Trades: positions, history by day, performance, session reviews. Brain: global regime, the influence
 * graph and the measured wiring. Feed: the headlines the desk reads and its own reasoning log.
 * Works against the desk's own server (/api/i/*) and, unchanged, as the read-only published site (a shim
 * answers the same calls from data.json). All server text goes in with textContent. */
"use strict";
const VERSION = "2.0";
const $ = (s, r) => (r || document).querySelector(s);
const NS = "http://www.w3.org/2000/svg";
const S = {
	account: "live", tab: "desk", sub: { trades: "positions", feed: "news" }, sym: "NIFTY", interval: "5m", brainSym: "NIFTY", ckind: "idx",
	state: null, charts: {}, chartAt: {}, news: null, newsAt: 0, lw: null, eq: null, thBefore: null, thSym: "", newsF: "", brk: "by_day_type",
	accounts: [], installEvt: null, networkUnavailable: false,
};

// ---- icons (24px, stroked) -----------------------------------------------------------------------------------
const IC = {
	desk: "M5 3.5h4A1.5 1.5 0 0 1 10.5 5v4A1.5 1.5 0 0 1 9 10.5H5A1.5 1.5 0 0 1 3.5 9V5A1.5 1.5 0 0 1 5 3.5zM15 3.5h4A1.5 1.5 0 0 1 20.5 5v4a1.5 1.5 0 0 1-1.5 1.5h-4A1.5 1.5 0 0 1 13.5 9V5A1.5 1.5 0 0 1 15 3.5zM5 13.5h4a1.5 1.5 0 0 1 1.5 1.5v4A1.5 1.5 0 0 1 9 20.5H5A1.5 1.5 0 0 1 3.5 19v-4A1.5 1.5 0 0 1 5 13.5zM15 13.5h4a1.5 1.5 0 0 1 1.5 1.5v4a1.5 1.5 0 0 1-1.5 1.5h-4a1.5 1.5 0 0 1-1.5-1.5v-4a1.5 1.5 0 0 1 1.5-1.5z",
	chart: "M4 4v16h16M7.5 15l3.5-4 3 2.5 5-6",
	trades: "M8 20V5M4.5 8.5L8 5l3.5 3.5M16 4v15M12.5 15.5L16 19l3.5-3.5",
	brain: "M6 4.8a2.2 2.2 0 1 0 0 4.4 2.2 2.2 0 0 0 0-4.4zM18 4.8a2.2 2.2 0 1 0 0 4.4 2.2 2.2 0 0 0 0-4.4zM12 15.3a2.2 2.2 0 1 0 0 4.4 2.2 2.2 0 0 0 0-4.4zM8.2 7h7.6M7.1 8.9l3.8 6.7M16.9 8.9l-3.8 6.7",
	feed: "M4 6h16M4 11h16M4 16h10",
	chev: "M9 6l6 6-6 6", x: "M6 6l12 12M18 6L6 18",
	aside: "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zM10 9v6M14 9v6",
	watch: "M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12zM12 9a3 3 0 1 0 0 6 3 3 0 0 0 0-6z",
	target: "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zM12 7a5 5 0 1 0 0 10 5 5 0 0 0 0-10zM12 11a1 1 0 1 0 0 2 1 1 0 0 0 0-2z",
	alert: "M12 4l9 16H3zM12 10v4M12 17v.01", moon: "M20 14.5A8 8 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5z",
	up: "M6 15l6-6 6 6", down: "M6 9l6 6 6-6", flat: "M5 12h14",
	ext: "M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5",
	install: "M12 4v11M8 11l4 4 4-4M5 20h14", refresh: "M20 11a8 8 0 1 0-2.3 5.7M20 5v6h-6",
	pause: "M9 5v14M15 5v14", play: "M7 5l12 7-12 7z", stop: "M6 6h12v12H6z",
	globe: "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zM3 12h18M12 3c3 3.5 3 14.5 0 18M12 3c-3 3.5-3 14.5 0 18",
	news: "M4 5h13v14H6a2 2 0 0 1-2-2zM17 9h3v8a2 2 0 0 1-2 2M8 9h5M8 13h5",
	book: "M5 4h9a3 3 0 0 1 3 3v13H8a3 3 0 0 1-3-3zM17 20h2V6M9 8h5M9 12h5", info: "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zM12 11v6M12 7.5v.01",
	bolt: "M13 3L5 13h6l-1 8 8-10h-6z", clock: "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zM12 7v5l3 2",
};
function svg(tag, attrs, parent) {
	const e = document.createElementNS(NS, tag);
	for (const k in attrs) e.setAttribute(k, attrs[k]);
	if (parent) parent.appendChild(e);
	return e;
}
function icon(name) {
	const s = svg("svg", { viewBox: "0 0 24 24", class: "i", "aria-hidden": "true" });
	svg("path", { d: IC[name] || IC.info }, s);
	return s;
}

// ---- helpers ----------------------------------------------------------------------------------------------
function h(tag, attrs, ...kids) {
	const e = document.createElement(tag);
	for (const [k, v] of Object.entries(attrs || {})) {
		if (v == null || v === false) continue;
		if (k === "class") e.className = v;
		else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
		else e.setAttribute(k, v === true ? "" : v);
	}
	for (const k of kids.flat()) if (k != null && k !== false) e.appendChild(typeof k === "object" ? k : document.createTextNode(String(k)));
	return e;
}
// append children, skipping null/false (Element.append would print them as text)
function put(el, ...kids) { for (const k of kids.flat()) if (k != null && k !== false) el.append(k); return el; }
const fin = (v) => v != null && isFinite(v);
const inr = (v, sign) => {
	if (!fin(v)) return "—";
	const a = Math.abs(v), s = v < 0 ? "−" : sign && v > 0 ? "+" : "";
	return s + (a >= 1e7 ? "₹" + (a / 1e7).toFixed(2) + " Cr" : a >= 1e5 ? "₹" + (a / 1e5).toFixed(2) + " L" : "₹" + Math.round(a).toLocaleString("en-IN"));
};
const num = (v, d = 2) => (fin(v) ? Number(v).toLocaleString("en-IN", { minimumFractionDigits: d, maximumFractionDigits: d }) : "—");
const signed = (v, d = 2) => (fin(v) ? (v > 0 ? "+" : v < 0 ? "−" : "") + Math.abs(v).toLocaleString("en-IN", { minimumFractionDigits: d, maximumFractionDigits: d }) : "—");
const pct = (v, d = 2) => (fin(v) ? (v > 0 ? "+" : v < 0 ? "−" : "") + Math.abs(v * 100).toFixed(d) + "%" : "—");
const cls = (v) => (v > 0 ? "up" : v < 0 ? "dn" : "");
const cap = (s) => (s ? String(s).charAt(0).toUpperCase() + String(s).slice(1) : "");
const words = (s) => String(s || "").replace(/_/g, " ");
// "2026-09-29 09:27:04.466562+05:30" → ms. Safari won't parse >3 fractional digits or a space separator.
const tms = (t) => (typeof t === "number" ? t * 1000 : Date.parse(String(t).trim().replace(" ", "T").replace(/(\.\d{3})\d+/, "$1")));
const ist = (t, withDate) => {
	const ms = tms(t);
	if (!isFinite(ms)) return "—";
	return new Date(ms).toLocaleString("en-IN", { timeZone: "Asia/Kolkata", hour: "2-digit", minute: "2-digit", hour12: false,
		...(withDate ? { day: "2-digit", month: "short" } : {}) });
};
const istDay = (t) => new Date(tms(t)).toLocaleDateString("en-IN", { timeZone: "Asia/Kolkata", weekday: "short", day: "2-digit", month: "short" });
function ago(ts) {
	const m = Math.max(0, (Date.now() - tms(ts)) / 60000);
	if (!isFinite(m)) return "";
	return m < 1 ? "just now" : m < 60 ? `${Math.round(m)} min ago` : m < 1440 ? `${Math.round(m / 60)} h ago` : ist(ts, true);
}
function store(k, v) { try { if (v === undefined) return localStorage.getItem(k); localStorage.setItem(k, v); } catch (e) { return null; } return null; }
function toast(msg) {
	const t = $("#toast");
	t.textContent = msg;
	t.classList.add("show");
	clearTimeout(toast.t);
	toast.t = setTimeout(() => t.classList.remove("show"), 3400);
}
async function api(path, opt) {
	const sep = path.includes("?") ? "&" : "?";
	const r = await fetch(path + (path.startsWith("/api/i/") ? sep + "account=" + encodeURIComponent(S.account) : ""), opt);
	const j = await r.json().catch(() => ({}));
	if (r.status === 401) { location.href = "/"; throw new Error("sign in again"); }
	if (!r.ok) throw new Error(j.error || "HTTP " + r.status);
	return j;
}
const post = (p, b) => api(p, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(b) });
const empty = (ic, text) => h("div", { class: "empty" }, icon(ic), text);
const SETUP = { orb: "Opening-range breakout", vwap_trend: "VWAP trend", trend_break: "Trend break", fade: "Fade", reversal: "Reversal", range: "Range" };
const setupName = (s) => SETUP[s] || cap(words(s));
const ACRO = new Set(["vwap", "cpr", "orb", "ema", "pcr", "oi", "iv", "rv", "vix", "gex", "ofi", "vpin", "rsi", "atr", "adx", "fii", "dii", "or", "ib", "poc", "va", "vah", "val", "ou", "ivr", "gift", "us", "fx"]);
const factorName = (f) => cap(words(f).split(" ").map((w) => (ACRO.has(w.toLowerCase()) ? w.toUpperCase() : w)).join(" "));
const DAYTYPE = { undetermined: "Forming", forming: "Forming" };
const dayName = (d) => DAYTYPE[d] || cap(words(d || "forming"));
const structName = (s) => cap(words(s || ""));

// ---- IST clock: is the market open, and when does it next open ------------------------------------------------------
function istNow() {
	const p = Object.fromEntries(new Intl.DateTimeFormat("en-GB", { timeZone: "Asia/Kolkata", weekday: "short", hour: "2-digit", minute: "2-digit", hour12: false })
		.formatToParts(new Date()).map((x) => [x.type, x.value]));
	return { wd: p.weekday, min: Number(p.hour) * 60 + Number(p.minute) };
}
const inSession = () => { const n = istNow(); return !["Sat", "Sun"].includes(n.wd) && n.min >= 555 && n.min <= 930; };
function nextOpen() {
	const n = istNow(), days = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
	let i = days.indexOf(n.wd), k = 0;
	if (i >= 1 && i <= 5 && n.min < 555) return "today 09:15";
	do { i = (i + 1) % 7; k++; } while (i === 0 || i === 6);
	return (k === 1 ? "tomorrow" : days[i]) + " 09:15";
}

// ---- what the desk said, in plain words -------------------------------------------------------------------------
function readAction(a) {
	a = String(a || "").trim();
	let m;
	if (/^ENTER/.test(a)) { m = a.match(/^ENTER (\S+) (\d+)×(.*?)(?: \| |$)/); return { kind: "enter", label: "Entered a trade", reason: m ? `${setupName(m[1])}: ${m[2]} × ${m[3]}` : a.slice(6) }; }
	if (/^EXIT/.test(a)) return { kind: "exit", label: "Closed a trade", reason: a.slice(5) };
	if ((m = a.match(/^standing aside[^:]*:\s*(.*)$/i))) return { kind: "aside", label: "Standing aside", reason: cap(m[1]) };
	if ((m = a.match(/^watching[^:]*:\s*(.*)$/i))) return { kind: "watch", label: "Watching", reason: cap(m[1]) };
	if ((m = a.match(/^armed:\s*(.*)$/i))) return { kind: "armed", label: "Waiting at the level", reason: cap(m[1]) };
	if (/sized to 0 lots|not worth it|\bEV\b/.test(a)) return { kind: "pass", label: "Passed on a setup", reason: cap(a) };
	return { kind: a ? "other" : "none", label: a ? cap(a) : "No read yet", reason: "" };
}
// what the desk is doing on one index: its last action, else (older desks) its first no-trade flag
function stance(v) {
	const a = readAction(v && v.action);
	if (a.kind === "none" && v && (v.vetoes || []).length) return { kind: "aside", label: "Standing aside", reason: cap(v.vetoes[0]) };
	return a;
}
const biasCls = (b) => (b === "bullish" ? "bull" : b === "bearish" ? "bear" : "flat");
function biasTag(bias, score) {
	const k = biasCls(bias);
	return h("span", { class: "tag " + k }, (k === "bull" ? "▲ " : k === "bear" ? "▼ " : "● ") + cap(bias || "neutral") + (fin(score) ? " " + signed(score) : ""));
}
function chgPill(v, pts) {
	return h("span", { class: "chg mono " + (v > 0 ? "up" : v < 0 ? "dn" : "flat") }, pts != null ? signed(pts) : pct(v));
}

// ---- glossary (the "?" buttons) ---------------------------------------------------------------------------------
const GLOSS = {
	bias: ["Bias score", "The desk's lean for the index, from −1 (strongly bearish) to +1 (strongly bullish): a weighted vote of every piece of evidence — trend, structure, momentum, options positioning, volatility, news, global markets, and the quant model when it has proven an edge."],
	conviction: ["Conviction", "How much the evidence agrees, 0 (split) to 1 (unanimous). The desk trades only with enough conviction and no no-trade flag up."],
	premium: ["Premium: rich, fair or cheap", "Implied volatility (IV, what option prices assume) against realised volatility (RV, how much the index is actually moving). Rich premium (IV well above RV) favours spreads that sell some of it back; cheap premium favours buying options outright."],
	armed: ["Waiting at the level", "A setup the desk's read already favours, decided before price gets there: it knows the level that triggers it (the opening range, a 30-minute range edge, VWAP on a pullback) and fires the moment price trades there, from a live price checked every few seconds, instead of waiting for a 5-minute candle to close beyond it. Re-decided every minute from the latest read."],
	aside: ["Standing aside", "A no-trade flag is up: the first minutes after the open, a move too stretched to chase, breaking news, a stale option chain, global stress, or an EV that doesn't clear costs. Not trading is a decision too."],
	r: ["R-multiple", "P&L divided by the risk planned at entry. +1R made what the trade risked; −1R lost exactly the planned amount. It makes trades of different sizes comparable."],
	grade: ["Trade grade", "A post-trade review of decision quality (entry, sizing, management, exit), A to F. A well-run loser can grade well; a lucky winner can grade badly."],
	quant: ["The quant layer", "A 30-minute volatility forecast (realised + implied) and a Monte Carlo that prices every candidate options structure after all costs. A direction model votes only if it beat a coin flip out of sample (AUC ≥ 0.53); research drifts come from years of real data and only count when they survive a holdout."],
	levels: ["Levels", "OR: opening range (first 15 min). IB: initial balance (first hour). PDH/PDL: prior day high/low. VAH/VAL/POC: value area and point of control. CPR: central pivot range. OI walls: the strikes with the most call / put open interest."],
	regime: ["Global regime", "A weighted read of US, Asian and European equities, US volatility, the dollar, the rupee, crude and rates. It's context: only links the weekly research has validated on real data actually vote in the bias."],
	stress: ["Global stress", "How unusual global moves are right now, in standard deviations. Above 2σ the desk cuts position size, down to half."],
	vwap: ["VWAP", "The session's volume-weighted average price (time-weighted for an index, which has no volume of its own). Above it buyers have had the upper hand today, below it sellers."],
	paper: ["Paper trading", "Every trade here is simulated against real prices and real option chains, with real costs (brokerage, STT, exchange fees, slippage). No real money moves and nothing here can place an order."],
};
function info(key) {
	return h("button", { class: "info", "aria-label": "What is " + (GLOSS[key] || [key])[0] + "?", onclick: (e) => { e.stopPropagation(); showGloss(key); } }, "?");
}
function showGloss(key) {
	const g = GLOSS[key];
	if (!g) return;
	openSheet(g[0], h("p", { style: "margin:0;font-size:14.5px;line-height:1.6;color:var(--fg2)" }, g[1]),
		h("button", { class: "btn block", style: "margin-top:18px", onclick: () => openSheet("How to read this app", glossaryList()) }, icon("book"), "All terms"));
}
function glossaryList() {
	return h("div", { class: "panel rows" }, Object.entries(GLOSS).map(([k, [t, d]]) =>
		h("div", { class: "pad" }, h("div", { style: "font-weight:600;margin-bottom:3px" }, t), h("div", { style: "font-size:13px;color:var(--fg2);line-height:1.55" }, d))));
}

// ---- shell: tabs, routing, sheets, theme ---------------------------------------------------------------------------
const TABS = [["desk", "Desk"], ["chart", "Chart"], ["trades", "Trades"], ["brain", "Brain"], ["feed", "Feed"]];
const SUBS = { trades: [["positions", "Positions"], ["history", "History"], ["performance", "Performance"], ["reviews", "Reviews"]],
	feed: [["news", "Headlines"], ["log", "Desk log"]] };
// the app's mark: a price path that tests a level, pulls back and breaks through it
function mark(size) {
	const s = svg("svg", { viewBox: "0 0 64 64", width: size, height: size, "aria-hidden": "true" });
	svg("rect", { width: 64, height: 64, rx: 15, fill: "#0B0E13" }, s);
	svg("path", { d: "M12 34H31M39.5 34H52", stroke: "#5A6474", "stroke-width": 3.5, "stroke-linecap": "round" }, s);
	svg("path", { d: "M12 48L21 40L28 45L40 27L52 15", fill: "none", stroke: "#7D95FF", "stroke-width": 5.5, "stroke-linecap": "round", "stroke-linejoin": "round" }, s);
	return s;
}
function buildTabs() {
	const nav = $("#tabs");
	nav.appendChild(h("div", { class: "brand", "aria-hidden": "true" }, mark(26), h("div", {}, "Quant ", h("span", {}, "Desk"))));
	for (const [id, label] of TABS)
		nav.appendChild(h("button", { role: "tab", "aria-selected": "false", "data-tab": id, onclick: () => go(id) }, icon(id), h("span", {}, label)));
}
function go(route) {
	const [tab, sub] = String(route).split("/");
	if (location.hash !== "#" + route) history.replaceState(null, "", "#" + route);
	show(tab, sub);
}
function show(tab, sub) {
	if (!TABS.some((t) => t[0] === tab)) tab = "desk";
	const changed = tab !== S.tab;
	S.tab = tab;
	if (sub && SUBS[tab] && SUBS[tab].some((s) => s[0] === sub)) S.sub[tab] = sub;
	store("qd.tab", tab);
	document.querySelectorAll("#tabs button").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.tab === tab)));
	document.querySelectorAll("main > section").forEach((s) => (s.hidden = s.dataset.view !== tab));
	$("#title").textContent = (TABS.find((t) => t[0] === tab) || ["", "Desk"])[1];
	if (changed) scrollTo(0, 0);
	if ($("#sheet").classList.contains("open")) closeSheet();          // navigating (or Back) closes a sheet
	if (tab !== "chart" && $("#c-box").classList.contains("fs")) fullscreen(false);
	refresh(true);
}
function openSheet(title, ...content) {
	const b = $("#sheetbody");
	b.textContent = "";
	put(b, h("div", { class: "grab", "aria-hidden": "true" }),
		h("div", { class: "sh-h" }, h("h3", {}, title), h("button", { class: "ib", "aria-label": "Close", onclick: closeSheet }, icon("x"))), ...content);
	$("#sheet").classList.add("open");
	b.scrollTop = 0;
	document.body.style.overflow = "hidden";
}
function closeSheet() { $("#sheet").classList.remove("open"); document.body.style.overflow = ""; }
function themeMode() { return store("qd.theme") || "auto"; }
function applyTheme(mode) {
	const r = document.documentElement;
	if (mode === "dark" || mode === "light") r.setAttribute("data-theme", mode); else r.removeAttribute("data-theme");
	store("qd.theme", mode);
	requestAnimationFrame(() => {
		$("#meta-theme").setAttribute("content", cssv("--bg") || "#0a0c10");
		restyleCharts();
	});
}
function cssv(name) { return getComputedStyle(document.documentElement).getPropertyValue(name).trim(); }
function seg(el, items, current, onpick, role) {
	el.textContent = "";
	for (const [val, label] of items)
		el.appendChild(h("button", { "aria-pressed": String(val === current), role: role || null, "aria-selected": role ? String(val === current) : null,
			onclick: () => { onpick(val); seg(el, items, val, onpick, role); } }, label));
}

// ---- status pill + banner --------------------------------------------------------------------------------------
function deskStatus(st) {
	const hb = (st && st.heartbeat) || {}, pub = !!window.QD_PUBLISHED;
	const stale = !st || st.age_sec == null || !(st.age_sec <= (pub ? 900 : 180));
	if (window.QD_DEMO && !pub) return { k: "off", t: "Snapshot", s: hb.ts ? ist(hb.ts, true) : "", stale: false };
	if (!navigator.onLine || window.QD_OFFLINE_CACHE)
		return { k: "off net", t: "Offline", s: hb.ts ? ist(hb.ts, true) : "", stale: true, network: true };
	if (S.networkUnavailable)
		return { k: "off net", t: "Unavailable", s: hb.ts ? ist(hb.ts, true) : "", stale: true, network: true };
	if (stale && inSession() && st && st.age_sec != null)
		return { k: "stale", t: "Stale", s: Math.round(st.age_sec / 60) + " min", stale: true };
	if (stale) return { k: "off", t: inSession() ? "Offline" : "Closed", s: inSession() ? (hb.ts ? ist(hb.ts, true) : "") : "opens " + nextOpen(), stale: true };
	if (st.paused) return { k: "paused", t: "Paused", s: ist(hb.ts), stale: false };
	if (hb.halted) return { k: "paused", t: "Done for day", s: ist(hb.ts), stale: false };
	return { k: "live", t: "Live", s: ist(hb.ts), stale: false };
}
function setStatus(st) {
	const d = deskStatus(st), p = $("#status");
	p.className = "pill " + d.k;
	$("#status-t").textContent = d.t;
	$("#status-s").textContent = d.s;
	return d;
}

// ---- data ------------------------------------------------------------------------------------------------------
async function loadState() {
	try { S.state = await api("/api/i/state"); S.networkUnavailable = false; S.stateErr = ""; }
	catch (e) { S.networkUnavailable = true; S.stateErr = e.message; }
	setStatus(S.state);
	return S.state;
}
async function loadChart(sym, iv, maxAge) {
	const k = sym + "|" + iv;
	if (S.charts[k] && Date.now() - (S.chartAt[k] || 0) < (maxAge == null ? 20000 : maxAge)) return S.charts[k];
	try { S.charts[k] = await api(`/api/i/chart?symbol=${encodeURIComponent(sym)}&interval=${iv}`); S.chartAt[k] = Date.now(); } catch (e) { /* keep the last */ }
	return S.charts[k];
}
async function loadNews(maxAge) {
	if (S.news && Date.now() - S.newsAt < (maxAge == null ? 60000 : maxAge)) return S.news;
	try { S.news = await api("/api/i/news?n=150"); S.newsAt = Date.now(); } catch (e) { S.news = S.news || []; }
	return S.news;
}
const views = () => ((S.state && S.state.heartbeat && S.state.heartbeat.views) || {});
const symbols = () => { const v = Object.keys(views()); return v.length ? v : ["NIFTY", "BANKNIFTY"]; };

// ==================================================================================================================
// DESK
// ==================================================================================================================
async function renderDesk() {
	const st = S.state;
	if (!st) {
		const banner = $("#d-banner");
		banner.textContent = "";
		if (S.networkUnavailable && (window.QD_PUBLISHED || S.account === "live"))
			banner.appendChild(h("div", { class: "banner net" }, icon("aside"),
				(!navigator.onLine || window.QD_OFFLINE_CACHE ? "Network unavailable." : "Desk connection failed.") +
				" No current session snapshot is available; reconnect and refresh before relying on this desk."));
		$("#d-hero").textContent = "";
		$("#d-hero").appendChild(empty("info", (S.stateErr || "No desk yet") + ". Start one with `quantdesk intraday live` (or `intraday replay --synthetic 5`)."));
		$("#d-now").textContent = "";
		return;
	}
	const hb = st.heartbeat || {}, vs = hb.views || {}, status = deskStatus(st);
	// banner: why nothing is moving
	const bn = $("#d-banner");
	bn.textContent = "";
	if (status.network && (window.QD_PUBLISHED || S.account === "live")) {
		bn.appendChild(h("div", { class: "banner net" }, icon("aside"),
			(!navigator.onLine || window.QD_OFFLINE_CACHE ? "Offline." : "Desk connection failed.") +
			" Showing the last saved state" + (hb.ts ? " from " + ist(hb.ts, true) : "") + "; data may be stale. It refreshes by itself when the connection returns."));
	} else if (status.stale && (window.QD_PUBLISHED || S.account === "live")) {
		const mins = st.age_sec != null ? Math.round(st.age_sec / 60) : null;
		bn.appendChild(inSession()
			? h("div", { class: "banner warn" }, icon("clock"), `The desk hasn't reported for ${mins != null ? mins + " min" : "a while"}${hb.ts ? " · showing " + ist(hb.ts) : ""}. It hands over to a fresh runner at 12:20, and a restart takes a few minutes; this page refreshes by itself.`)
			: h("div", { class: "banner" }, icon("moon"), `Market closed · next session ${nextOpen()}. The desk trades every NSE session by itself, 09:15–15:30 IST (exchange holidays excepted). Showing its last state${hb.ts ? " from " + ist(hb.ts, true) : ""}.`));
	}
	renderNow(st);
	// account strip
	const lim = st.limits || {}, dse = hb.day_start_equity || st.equity || st.capital, dp = hb.day_pnl;
	const lossCap = lim.daily_loss_limit && dse ? lim.daily_loss_limit * dse : null;
	const used = lossCap && fin(dp) ? Math.max(0, -dp) / lossCap : 0;
	const sf = lim.short_legs_from_equity, mode = $("#d-mode");
	mode.textContent = "";
	if (sf === null || (fin(sf) && fin(st.equity) && st.equity < sf))
		mode.appendChild(h("span", { class: "tag acc", title: "Buys calls and puts only: selling options needs margin this account doesn't have yet" },
			fin(sf) ? `Buyer only · selling from ₹${(sf / 1e5).toLocaleString("en-IN", { maximumFractionDigits: 1 })}L` : "Buyer only"));
	const hero = $("#d-hero");
	hero.textContent = "";
	put(hero,
		h("div", { class: "acct" },
			h("div", { style: "min-width:0" }, h("span", { class: "k" }, "Paper equity", info("paper")), h("div", { class: "eq" }, inr(st.equity))),
			h("div", {}, h("span", { class: "k", style: "text-align:right" }, "Today"),
				h("div", { class: "day " + cls(dp) }, fin(dp) ? inr(dp, true) + " " : "—", fin(dp) ? h("small", {}, pct(dp / (dse || 1))) : null))),
		h("div", { class: "stats" },
			h("div", {}, h("span", {}, "All-time"), h("b", { class: cls(st.total_pnl) }, inr(st.total_pnl, true))),
			h("div", {}, h("span", {}, "Trades"), h("b", {}, `${hb.trades_today ?? 0}${lim.max_trades_per_day ? " of " + lim.max_trades_per_day : ""}`)),
			h("div", {}, h("span", {}, "Open"), h("b", {}, String((hb.positions || []).length))),
			h("div", { title: lossCap ? `daily loss limit ${inr(lossCap)}` : null }, h("span", {}, "Loss cap"), h("b", {}, lossCap ? Math.round(used * 100) + "% used" : "—"),
				lossCap ? h("div", { class: "meter" }, h("i", { style: `width:${Math.min(100, used * 100)}%;background:${used > 0.66 ? "var(--dn)" : "var(--acc)"}` })) : null)));
	renderControls(st);
	// markets: the two indices, with the desk's read of each
	const syms = Object.keys(vs).length ? Object.keys(vs) : ["NIFTY", "BANKNIFTY"];
	const mk = $("#d-markets");
	mk.textContent = "";
	for (const s of syms) mk.appendChild(marketRow(s, vs[s]));
	$("#d-mkt-hint").textContent = (hb.feed ? `${hb.feed} · ` : "") + "bias −1 to +1";
	// open positions
	const pos = hb.positions || [];
	$("#d-pos-wrap").hidden = !pos.length;
	$("#d-pos-hint").textContent = pos.length ? `since ${ist(pos[0].opened)}` + (pos.length > 1 ? ` · ${pos.length} open` : "") : "";
	const pl = $("#d-positions");
	pl.textContent = "";
	pos.forEach((p) => pl.appendChild(positionCard(p)));
	// setups decided before price gets there: they fire the moment it does
	const armed = hb.armed || [];
	$("#d-armed-wrap").hidden = !armed.length;
	$("#d-armed-hint").textContent = armed.length ? `${armed.length} armed` : "";
	const ar = $("#d-armed");
	ar.textContent = "";
	armed.forEach((x) => ar.appendChild(armedRow(x, vs[x.symbol])));
	renderGlobalStrip(hb.global);
	// closed today
	const ct = st.closed_today || [];
	$("#d-closed-wrap").hidden = !ct.length;
	const cl = $("#d-closed");
	cl.textContent = "";
	ct.forEach((t) => cl.appendChild(tradeRow(t)));
	// sparklines, the log and headlines load after the first paint
	Promise.all(syms.map((s) => loadChart(s, "5m", 60000))).then(() => {
		if (S.tab !== "desk") return;
		document.querySelectorAll("#d-markets .mrow").forEach((row) => {
			const s = row.dataset.sym, v = vs[s], old = row.querySelector(".spark");
			if (old) old.replaceWith(spark(S.charts[s + "|5m"], v && fin(v.chg) ? v.spot / (1 + v.chg) : null, v && v.chg));
		});
	});
	if (matchMedia("(min-width: 1024px)").matches) renderDeskLog();
	loadNews().then((rows) => {
		if (S.tab !== "desk") return;
		const box = $("#d-news");
		box.textContent = "";
		if (!rows.length) box.appendChild(empty("news", "Headlines appear here while the desk runs."));
		rows.slice(0, 3).forEach((r) => box.appendChild(newsRow(r, true)));
	});
	const note = $("#qd-note");
	if (!note.dataset.done) {
		note.dataset.done = "1";
		put(note, h("b", {}, (window.QD_LABEL || (window.QD_PUBLISHED ? "Live paper desk" : "QuantDesk")) + ". "),
			window.QD_NOTE || "Paper trades only: simulated against real prices and option chains, with real costs. Nothing here can place an order.");
	}
	installCard();
}
function marketRow(s, v) {
	const c = S.charts[s + "|5m"], a = stance(v);
	const last = v && fin(v.spot) ? v.spot : c && c.bars ? c.bars.c[c.bars.c.length - 1] : null;
	const prev = v && fin(v.chg) && fin(v.spot) ? v.spot / (1 + v.chg) : null;
	const k = v ? biasCls(v.bias) : "flat";
	return h("button", { class: "mrow", "data-sym": s, onclick: () => { S.sym = s; store("qd.sym", s); go("chart"); } },
		h("div", { style: "min-width:0" }, h("div", { class: "nm" }, s),
			h("div", { class: "sub" }, v ? `${dayName(v.day_type)} day${v.expiry && v.expiry !== "None" ? " · exp " + fmtExpiry(v.expiry) : ""}` : "no read yet")),
		spark(c, prev, v && v.chg),
		h("div", { class: "px" }, h("div", { class: "v" }, num(last)),
			h("div", { class: "chg " + (v && cls(v.chg) ? cls(v.chg) : "flat") }, v && prev != null && fin(last) ? `${signed(last - prev)} · ${pct(v.chg)}` : "—")),
		v ? h("div", { class: "desk" },
			h("span", { class: "bias" }, biasMeter(v.score), h("span", { class: k === "bull" ? "up" : k === "bear" ? "dn" : "f2" }, `${signed(v.score)} ${cap(v.bias || "neutral")}`)),
			h("span", {}, "Conviction ", h("b", {}, num(v.conviction))),
			h("span", {}, "Premium ", h("b", {}, v.vol_view || "—"), fin(v.iv) ? ` · IV ${num(v.iv, 1)}` : "")) : null,
		v && a.kind !== "none" ? h("div", { class: "st" }, a.label + (a.reason ? " · " + a.reason : "")) : null);
}
// a signed meter from −1 to +1: the fill grows from the centre tick, green right, red left
function biasMeter(score, big) {
	const w = fin(score) ? Math.min(1, Math.abs(score)) * 50 : 0, pos = fin(score) && score >= 0;
	return h("span", { class: "bm" + (big ? " big" : ""), role: "meter", "aria-valuemin": "-1", "aria-valuemax": "1", "aria-valuenow": fin(score) ? Number(score).toFixed(2) : "0", "aria-label": "bias score" },
		h("i", { style: `${pos ? "left:50%" : "right:50%"};width:${w}%;background:${score > 0 ? "var(--up)" : score < 0 ? "var(--dn)" : "var(--fg3)"};border-radius:${pos ? "0 2px 2px 0" : "2px 0 0 2px"}` }));
}
function fmtExpiry(e) {
	const d = new Date(String(e).slice(0, 10) + "T00:00:00Z");
	return isFinite(d) ? d.toLocaleDateString("en-IN", { day: "2-digit", month: "short", timeZone: "UTC" }) : e;
}
// "NIFTY06OCT2625650CE" → "NIFTY 25,650 CE · 06 Oct"
function contractName(sym) {
	const m = String(sym || "").match(/^([A-Z&-]+?)(\d{2})([A-Z]{3})(\d{2})(\d+(?:\.\d+)?)(CE|PE)$/);
	if (!m) return sym || "";
	return [`${m[1]} ${Number(m[5]).toLocaleString("en-IN")} ${m[6]}`, h("small", {}, ` · ${m[2]} ${m[3].charAt(0)}${m[3].slice(1).toLowerCase()}`)];
}
function spark(c, prev, chg) {
	const W = 96, H = 28, s = svg("svg", { class: "spark", viewBox: `0 0 ${W} ${H}`, "aria-hidden": "true" });
	const all = c && c.bars ? c.bars.c : null, i0 = c ? todayFrom(c) : 0;
	const ys = all ? (all.length - i0 >= 2 ? all.slice(i0) : all) : null;
	if (!ys || ys.length < 2) return s;
	let lo = Math.min(...ys), hi = Math.max(...ys);
	if (fin(prev)) { lo = Math.min(lo, prev); hi = Math.max(hi, prev); }
	const span = hi - lo || 1, X = (i) => (i / (ys.length - 1)) * W, Y = (v) => 3 + (hi - v) / span * (H - 6);
	const col = (chg != null ? chg : ys[ys.length - 1] - ys[0]) >= 0 ? cssv("--up") : cssv("--dn");
	if (fin(prev)) svg("line", { x1: 0, x2: W, y1: Y(prev), y2: Y(prev), stroke: cssv("--line2"), "stroke-width": 1, "stroke-dasharray": "2 3" }, s);
	let d = "";
	ys.forEach((v, i) => (d += (i ? "L" : "M") + X(i).toFixed(1) + " " + Y(v).toFixed(1)));
	svg("path", { d, fill: "none", stroke: col, "stroke-width": 1.3, "stroke-linejoin": "round" }, s);
	return s;
}
function renderControls(st) {
	const box = $("#d-controls");
	box.textContent = "";
	if (window.QD_PUBLISHED || window.QD_DEMO) return;
	box.appendChild(h("div", { class: "btns", style: "margin-top:12px" },
		h("button", { class: "btn", onclick: () => command(st.paused ? "resume" : "pause") }, icon(st.paused ? "play" : "pause"), st.paused ? "Resume entries" : "Pause entries"),
		h("button", { class: "btn danger", onclick: () => confirmSheet("Flatten everything?", "Close every open position at the next minute's prices and pause new entries.", "Flatten all", () => command("flatten")) },
			icon("stop"), "Flatten all")));
}
function renderNow(st) {
	const hb = st.heartbeat || {}, vs = hb.views || {}, box = $("#d-now"), pos = hb.positions || [], armed = hb.armed || [];
	box.textContent = "";
	const syms = Object.keys(vs);
	const line = (dot, text, tm) => h("div", { class: "l1" }, h("span", { class: "lbl" }, "Now"), h("span", { class: "dot " + dot }), h("span", { class: "hd" }, text),
		tm ? h("span", { class: "tm" }, tm) : null);
	if (!syms.length) { box.appendChild(line("", "The desk's read appears here from 09:15 IST, updated every minute.")); return; }
	const reads = syms.map((s) => [s, vs[s], stance(vs[s])]);
	let dot = "", head;
	if (st.paused) { dot = "wait"; head = "Paused from the app · open positions are still managed"; }
	else if (hb.halted) { dot = "aside"; head = "Done for the day · the daily loss limit is hit"; }
	else if (pos.length) {
		dot = "in";
		head = (pos.length === 1 ? `In a ${pos[0].symbol} trade` : `In ${pos.length} trades`) +
			(armed.length ? ` · armed on ${[...new Set(armed.map((a) => a.symbol))].join(", ")}` : "");
	} else if (armed.length) { dot = "wait"; const a = armed[0]; head = `Armed · ${setupName(a.setup)} ${a.direction > 0 ? "call" : "put"} on ${a.symbol} at ${num(a.level)}`; }
	else if (reads.some((r) => r[2].kind === "enter")) { dot = "in"; head = "Just entered a trade"; }
	else if (reads.every((r) => r[2].kind === "aside")) { dot = "aside"; head = "Standing aside · a no-trade flag is up"; }
	else if (reads.some((r) => r[2].kind === "watch")) head = "Watching · no setup has triggered";
	else head = "Reading the market every minute";
	put(box, line(dot, head, hb.ts ? ist(hb.ts) : ""),
		h("div", { class: "why" }, reads.filter((r) => r[2].kind !== "none").map(([s, v, a]) => h("div", {}, h("b", {}, s + " "), a.label + (a.reason ? ": " + a.reason : "")))));
	if (reads.some((r) => r[2].kind === "aside")) box.lastChild.appendChild(h("div", {}, h("button", { class: "link", style: "min-height:28px", onclick: () => showGloss("aside") }, "Why stand aside?")));
}
function positionCard(p) {
	const legs = p.legs || [], leg = legs[0] || {}, single = legs.length === 1;
	const risk = fin(p.premium) && fin(p.premium_stop) ? p.premium * p.premium_stop : null;
	const r = risk && fin(p.pnl) ? p.pnl / risk : null;
	const dir = p.direction || (fin(p.target) && fin(p.entry_underlying) ? Math.sign(p.target - p.entry_underlying) : 0);
	const left = p.time_stop ? Math.round((tms(p.time_stop) - Date.now()) / 60000) : null;
	return h("div", { class: "pos" },
		h("div", { class: "r1" }, h("span", { class: "t1" }, single ? contractName(leg.symbol) : `${p.symbol} · ${structName(p.structure)}`),
			h("span", { class: "pnl " + cls(p.pnl) }, inr(p.pnl, true))),
		h("div", { class: "r2" }, h("span", {}, `${structName(p.structure)} · ${p.lots} lot${p.lots === 1 ? "" : "s"}${single && leg.qty ? " (" + Math.abs(leg.qty) + ")" : ""} · ${setupName(p.setup)}`),
			h("span", { class: cls(r) }, r != null ? signed(r) + "R" : "")),
		single ? h("div", { class: "prem" }, `Premium ₹${num(leg.entry)} → `, h("b", {}, `₹${num(leg.mark)}`), fin(p.premium_stop) ? ` · stop −${Math.round(p.premium_stop * 100)}%` : "")
			: legsTable(legs.map((l) => ({ symbol: l.symbol, qty: l.qty, entry: l.entry, mark: l.mark }))),
		fin(p.stop) && fin(p.target) ? track(p.stop, p.target, p.entry_underlying, p.spot, dir) : null,
		h("div", { class: "meta" }, `Since ${ist(p.opened)}` + (p.time_stop ? ` · time stop ${ist(p.time_stop)} if flat${left != null && left > 0 ? ", " + left + " min left" : ""}` : "")),
		h("div", { class: "btns" }, h("button", { class: "btn", onclick: () => openTrade(p.id) }, icon("info"), "Why this trade"),
			window.QD_PUBLISHED || window.QD_DEMO ? h("span") : h("button", { class: "btn danger", onclick: () =>
				confirmSheet(`Close ${p.symbol} ${setupName(p.setup)}?`, "Square off this position at the next minute's prices.", "Close position", () => command("close", p.id)) }, icon("x"), "Close")));
}
function track(stop, target, entry, spot, dir) {
	const lo = Math.min(stop, target), hi = Math.max(stop, target), span = hi - lo || 1;
	const X = (v) => Math.max(0, Math.min(100, (v - lo) / span * 100));
	const targetRight = target > stop;
	const good = fin(entry) && fin(spot) && (spot - entry) * (targetRight ? 1 : -1) >= 0, col = good ? "var(--up)" : "var(--dn)";
	return h("div", { class: "track", role: "img", "aria-label": `index ${num(spot)} between stop ${num(stop)} and target ${num(target)}` },
		h("div", { class: "ln" }),
		fin(entry) && fin(spot) ? h("div", { class: "fill", style: `left:${Math.min(X(entry), X(spot))}%;width:${Math.abs(X(spot) - X(entry))}%;background:${col}` }) : null,
		fin(entry) ? h("div", { class: "en", style: `left:${X(entry)}%`, title: "entry" }) : null,
		fin(spot) ? h("div", { class: "sp", style: `left:${X(spot)}%;border-color:${col}` }) : null,
		h("span", { class: "l" }, `${targetRight ? "Stop" : "Target"} ${num(lo, 0)}`), h("span", { class: "r" }, `${targetRight ? "Target" : "Stop"} ${num(hi, 0)}`));
}
function legsTable(legs, withExit) {
	return h("table", { class: "legs" }, h("tr", {}, h("th", {}, "Leg"), h("th", {}, "Qty"), h("th", {}, "Entry"), h("th", {}, withExit ? "Exit" : "Mark")),
		legs.map((l) => h("tr", {}, h("td", {}, l.symbol), h("td", { class: l.qty < 0 ? "dn" : "" }, (l.qty > 0 ? "+" : "") + l.qty), h("td", {}, num(l.entry)), h("td", {}, num(withExit ? l.exit : l.mark)))));
}
function armedRow(x, v) {
	const away = v && fin(v.spot) && fin(x.level) ? Math.abs(x.level - v.spot) : null;
	return h("div", { class: "arow" },
		h("div", { class: "l1" }, h("span", { class: "tag warn" }, "Armed"), h("b", { style: "font-weight:500" }, x.symbol),
			h("span", { class: x.direction > 0 ? "up" : "dn" }, `${x.direction > 0 ? "▲ call" : "▼ put"} · ${setupName(x.setup)}`),
			h("span", { class: "t" }, x.expires ? "until " + ist(x.expires) : "armed " + ist(x.armed_at))),
		h("div", { class: "l2" }, `${x.kind === "break" ? "On a trade through" : "On a pullback to"} `, h("b", {}, num(x.level)), ` · stop ${num(x.invalidation)}`,
			away != null ? ` · ${num(away, 1)} pts away (${(away / v.spot * 100).toFixed(2)}%)` : ""),
		x.why ? h("div", { class: "l3" }, cap(x.why)) : null);
}
const GLOBAL_ORDER = ["ES", "NQ", "N225", "HSI", "KOSPI", "SSE", "STOXX", "DAX", "FTSE", "USDINR", "DXY", "BRENT", "GOLD", "UST10", "USVIX", "SPX", "NASDAQ", "DJI"];
const SHORT = { ES: "S&P 500 fut", NQ: "Nasdaq fut", N225: "Nikkei 225", HSI: "Hang Seng", KOSPI: "Kospi", SSE: "Shanghai", STOXX: "Stoxx 50", DAX: "DAX", FTSE: "FTSE",
	USDINR: "USD/INR", DXY: "Dollar index", BRENT: "Brent", GOLD: "Gold", UST10: "US 10Y", USVIX: "US VIX", SPX: "S&P 500", NASDAQ: "Nasdaq", DJI: "Dow" };
const PULSE = ["ES", "N225", "BRENT", "DXY", "USDINR", "USVIX", "NQ", "HSI", "STOXX", "GOLD", "UST10", "KOSPI"];
const LEVEL_QUOTED = new Set(["USDINR", "DXY", "USVIX", "UST10"]);         // shown as a level; the rest as a % move
function mchg(m) { return m.live && m.since_open != null ? m.since_open : m.prior_ret; }
function renderGlobalStrip(G) {
	const mk = (G && G.markets) || {}, box = $("#d-global");
	let keys = PULSE.filter((k) => mk[k] && mk[k].last != null);
	if (keys.length > 3) keys = keys.slice(0, Math.min(6, keys.length - (keys.length % 3)));
	$("#d-global-wrap").hidden = !keys.length;
	box.textContent = "";
	for (const k of keys) {
		const m = mk[k], c = mchg(m);
		box.appendChild(h("button", { onclick: () => go("brain"), title: `${m.name}: ${m.live && m.since_open != null ? "since 09:15 IST" : "last session"}` },
			h("span", { class: "n" }, SHORT[k] || m.name),
			LEVEL_QUOTED.has(k) ? h("span", { class: "v" }, num(m.last, 2), " ", h("small", { class: cls(c) }, pct(c))) : h("span", { class: "v " + cls(c) }, pct(c))));
	}
}
async function renderDeskLog() {
	let rows = [];
	try { rows = await api("/api/i/thoughts?n=12"); } catch (e) { rows = []; }
	if (S.tab !== "desk") return;
	const box = $("#d-log");
	box.textContent = "";
	if (!rows.length) { box.appendChild(empty("watch", "The desk's minute-by-minute reasoning appears here while it runs.")); return; }
	rows.forEach((r) => box.appendChild(logRow(r)));
}
function logRow(r) {
	const a = readAction(r.action), sc = Number(r.score);
	return h("div", { class: "logrow" + (a.kind === "enter" ? " ent" : a.kind === "exit" ? " exit" : ""), title: r.narrative || "" },
		h("span", { class: "tm" }, ist(r.ts)), h("span", { class: "s" }, r.symbol), h("span", { class: "b " + cls(sc) }, signed(sc)),
		h("span", { class: "a" }, a.label + (a.reason ? ": " + a.reason : "")));
}
function installCard() {
	const box = $("#d-banner");
	if (store("qd.installed") || store("qd.install-dismissed") || matchMedia("(display-mode: standalone)").matches || navigator.standalone) return;
	const ios = /iphone|ipad|ipod/i.test(navigator.userAgent);
	if (!S.installEvt && !ios) return;
	if (box.querySelector(".install")) return;
	const card = h("div", { class: "banner install" }, icon("install"), h("div", { class: "grow" },
		h("div", { style: "font-weight:600" }, "Install QuantDesk"),
		h("div", { class: "f2", style: "margin-top:2px" }, ios ? "Tap Share, then “Add to Home Screen”: it opens full-screen like an app." : "Add it to your home screen: full-screen, one tap away, works offline."),
		S.installEvt ? h("button", { class: "btn primary", style: "margin-top:10px;height:36px", onclick: doInstall }, "Install app") : null),
		h("button", { class: "ib", "aria-label": "Dismiss", style: "margin:-8px -8px 0 0", onclick: () => { store("qd.install-dismissed", "1"); card.remove(); } }, icon("x")));
	box.appendChild(card);
}
async function doInstall() {
	if (!S.installEvt) return toast("Use your browser's menu: “Install app” or “Add to Home Screen”.");
	S.installEvt.prompt();
	const r = await S.installEvt.userChoice.catch(() => null);
	S.installEvt = null;
	if (r && r.outcome === "accepted") { store("qd.installed", "1"); toast("Installed. Open QuantDesk from your home screen."); }
	document.querySelectorAll(".install").forEach((e) => e.remove());
}

// ---- commands (own desk only) ------------------------------------------------------------------------------------
function confirmSheet(title, text, okLabel, fn) {
	openSheet(title, h("p", { style: "margin:0 0 18px;color:var(--fg2);font-size:14px;line-height:1.55" }, text),
		h("div", { class: "btns" }, h("button", { class: "btn", onclick: closeSheet }, "Cancel"),
			h("button", { class: "btn danger", onclick: () => { closeSheet(); fn(); } }, okLabel)));
}
async function command(cmd, arg) {
	if (window.QD_PUBLISHED) return toast("This site is read-only. Stop a run from the repo's Actions tab.");
	if (window.QD_DEMO) return toast("This is a snapshot: controls work on your own running desk.");
	try {
		await post("/api/i/command", { cmd, arg });
		toast(`${cap(cmd)} sent: applied on the engine's next minute`);
		refresh(true);
	} catch (e) { toast(e.message); }
}

// ==================================================================================================================
// CHART
// ==================================================================================================================
async function renderChart() {
	const syms = symbols();
	if (!syms.includes(S.sym)) S.sym = syms[0];
	seg($("#c-sym"), syms.map((s) => [s, s === "BANKNIFTY" ? "BANK" : s]), S.sym, (v) => { S.sym = v; store("qd.sym", v); renderChart(); });
	seg($("#c-iv"), [["1m", "1m"], ["5m", "5m"], ["15m", "15m"]], S.interval, (v) => { S.interval = v; store("qd.iv", v); renderChart(); });
	seg($("#c-kind"), [["idx", "Index"], ["fut", "Futures"]], S.ckind, (v) => { S.ckind = v; store("qd.ckind", v); renderChart(); });
	const v = views()[S.sym];
	renderQuoteHead(v);
	renderRead(v);
	await loadChart(chartSym(), S.interval);
	if (S.tab !== "chart") return;
	drawChart(false);
	renderQuoteHead(v);
	renderLevelsTable(v);
	renderQuant(v);
}
// the index, or its near-month future (real volume and OI; the index bars carry the futures' volume too)
function chartSym() { return S.sym + (S.ckind === "fut" ? "-FUT" : ""); }
function chartData() { return S.charts[chartSym() + "|" + S.interval]; }
// the latest session's first bar (the chart carries earlier sessions for context)
function todayFrom(d) {
	const B = d && d.bars, n = B ? B.t.length : 0, ss = (d && d.session_starts) || [];
	const t0 = ss.length ? ss[ss.length - 1] : (n ? B.t[0] : 0);
	let i = 0;
	while (i < n && B.t[i] < t0) i++;
	return i;
}
function renderQuoteHead(v) {
	const d = chartData(), B = d && d.bars, n = B ? B.t.length : 0, i0 = todayFrom(d);
	const last = v && fin(v.spot) && S.ckind !== "fut" ? v.spot : n ? B.c[n - 1] : null;
	const pc = i0 > 0 ? B.c[i0 - 1] : null;                 // the prior session's close, when the chart has it
	const chg = v && fin(v.chg) && S.ckind !== "fut" ? v.chg : (pc && last != null ? last / pc - 1 : null);
	const prev = chg != null && last != null ? last / (1 + chg) : null;
	const hi = n > i0 ? Math.max(...B.h.slice(i0)) : null, lo = n > i0 ? Math.min(...B.l.slice(i0)) : null;
	const vw = v && S.ckind !== "fut" ? v.vwap : d && d.vwap ? d.vwap[d.vwap.length - 1] : null;
	const box = $("#c-head");
	box.textContent = "";
	put(box, h("span", { class: "k" }, `${S.sym}${S.ckind === "fut" ? " futures" : ""}${d && d.day ? " · " + istDay(d.day + "T12:00:00+05:30") : ""} · ${S.interval}`),
		h("div", { class: "r" }, h("span", { class: "px" }, num(last)),
			h("span", { class: "ch " + cls(chg) }, prev != null ? `${signed(last - prev)} · ${pct(chg)}` : "")),
		h("span", { class: "hl" }, `H ${num(hi)} · L ${num(lo)} · VWAP ${num(vw)}`));
	$("#c-fs-title").textContent = `${S.sym} · ${S.interval}`;
}
function renderRead(v) {
	const box = $("#c-read");
	box.textContent = "";
	$("#c-read-hint").textContent = v && S.state && S.state.heartbeat ? ist(S.state.heartbeat.ts) + " · each minute" : "";
	if (!v) { box.appendChild(empty("watch", `No read yet for ${S.sym}. It appears from 09:15 IST.`)); $("#c-evidence").textContent = ""; return; }
	const a = stance(v), k = biasCls(v.bias);
	const learned = (v.evidence || []).filter((e) => fin(e.learned) && Math.abs(e.learned - 1) >= 0.02);
	put(box, h("div", { class: "read" },
		h("div", { class: "sc" }, h("span", { class: "v " + (k === "bull" ? "up" : k === "bear" ? "dn" : "") }, signed(v.score)),
			h("div", { class: "g" }, biasMeter(v.score, true), h("div", { class: "gscale" }, h("span", {}, "−1 Bearish"), h("span", {}, "Bullish +1")))),
		h("div", { class: "tags" }, biasTag(v.bias), h("span", { class: "tag line" }, `Conviction ${num(v.conviction)}`), info("conviction"),
			h("span", { class: "tag line" }, `${dayName(v.day_type)} day`),
			h("span", { class: "tag line" }, `Premium ${v.vol_view || "—"}`), info("premium")),
		h("div", { class: "track-rec" }, a.kind === "none" ? "" : `Doing now: ${a.label}${a.reason ? " · " + a.reason : ""}`),
		(v.vetoes || []).length ? h("div", { class: "flags" }, v.vetoes.map((x) => h("div", {}, icon("alert"), cap(x)))) : null,
		v.narrative ? h("p", { class: "narr" }, v.narrative) : null,
		learned.length ? h("div", { class: "track-rec" }, "Track record · " + learned.sort((x, y) => Math.abs(y.learned - 1) - Math.abs(x.learned - 1)).slice(0, 4)
			.map((e) => `${factorName(e.factor)} ×${num(e.learned)}`).join(" · ")) : null));
	const ev = $("#c-evidence");
	ev.textContent = "";
	ev.appendChild(evidenceList(v.evidence || [], 6));
}
function fact(label, value) { return h("div", {}, h("span", {}, label), h("b", {}, value || "—")); }
function narrative(text) { return text ? h("p", { class: "narr pad" }, text) : null; }
const CAT = { trend: "Trend", structure: "Structure", momentum: "Momentum", flow: "Flow", options: "Options", volatility: "Volatility", news: "News", quant: "Quant", global: "Global" };
const CAT_G = { trend: "Tape", structure: "Tape", momentum: "Tape", flow: "Flow", options: "Options", volatility: "Vol", news: "News", quant: "Quant", global: "Global" };
function evidenceList(list, limit) {
	const box = h("div", { class: "evl" });
	if (!list.length) { box.appendChild(empty("info", "No evidence yet.")); return box; }
	const sorted = [...list].sort((a, b) => Math.abs(b.direction * b.weight) - Math.abs(a.direction * a.weight));
	sorted.forEach((e, i) => {
		const w = Math.min(50, Math.abs(e.direction) * 50), probation = !(e.weight > 0);
		const col = probation ? "var(--fg3)" : e.direction >= 0 ? "var(--up)" : "var(--dn)";
		box.appendChild(h("div", { class: "ev" + (probation ? " probation" : "") },
			h("div", { class: "f" }, h("b", {}, factorName(e.factor)), h("small", {}, CAT[e.category] || cap(e.category)),
				probation ? h("span", { class: "ln" }, "probation") : fin(e.learned) && Math.abs(e.learned - 1) >= 0.02 ? h("span", { class: "ln" }, `learned ×${num(e.learned)}`) : null),
			h("div", { class: "dv", title: `${signed(e.direction)} × ${e.weight}` },
				h("i", { style: `${e.direction >= 0 ? "left:50%" : "right:50%"};width:${w}%;background:${col}` })),
			h("span", { class: "w" }, num(e.weight, e.weight >= 10 ? 0 : 2)),
			h("div", { class: "o" }, `${signed(e.direction)} · ${e.observation || ""}`)));
		if (limit && i >= limit) box.lastChild.hidden = true;
	});
	if (limit && sorted.length > limit + 1) {
		const btn = h("button", { class: "more", onclick: () => { box.querySelectorAll(".ev[hidden]").forEach((x) => (x.hidden = false)); btn.remove(); } },
			`Show all ${sorted.length}`, icon("down"));
		box.appendChild(btn);
	} else box.querySelectorAll(".ev[hidden]").forEach((x) => (x.hidden = false));
	return box;
}
const LEVELS = {
	or_high: ["OR high", "or"], or_low: ["OR low", "or"], ib_high: ["IB high", "ib"], ib_low: ["IB low", "ib"], vah: ["VAH", "value"], val: ["VAL", "value"],
	poc: ["POC", "value"], pdh: ["PDH", "prior"], pdl: ["PDL", "prior"], cpr_tc: ["CPR top", "cpr"], cpr_bc: ["CPR bottom", "cpr"],
	call_wall: ["Call wall", "oi"], put_wall: ["Put wall", "oi"], call_add: ["Fresh call writing", "oi"], put_add: ["Fresh put writing", "oi"],
	day_high: ["Day high", "day"], day_low: ["Day low", "day"],
};
const LEVEL_GROUPS = [["prior", "Prior day", "--fg2"], ["or", "Opening range", "--acc"], ["value", "Value area", "--fg3"], ["oi", "OI walls", "--dn"], ["cpr", "CPR", "--fg3"], ["ib", "Initial balance", "--fg3"]];
function levelsOn() {
	let on = null;
	try { on = JSON.parse(store("qd.levels") || "null"); } catch (e) { on = null; }
	return Object.assign({ prior: true, or: true, value: false, oi: true, cpr: false, ib: false }, on || {});
}
function levelColor(k) {
	if (k === "call_wall" || k === "call_add") return cssv("--dn");
	if (k === "put_wall" || k === "put_add") return cssv("--up");
	const g = LEVELS[k][1];
	return cssv((LEVEL_GROUPS.find((x) => x[0] === g) || [0, 0, "--fg3"])[2]);
}
function renderLevelChips() {
	const d = chartData(), box = $("#c-levels"), on = levelsOn();
	const have = new Set(Object.keys((d && d.levels) || {}).map((k) => LEVELS[k] && LEVELS[k][1]));
	box.textContent = "";
	for (const [g, label, col] of LEVEL_GROUPS) {
		if (!have.has(g)) continue;
		box.appendChild(h("button", { class: "chip", "aria-pressed": String(!!on[g]), onclick: () => {
			const o = levelsOn(); o[g] = !o[g]; store("qd.levels", JSON.stringify(o)); drawChart(false); } },
			h("i", { style: `color:${cssv(col)}` }), label));
	}
	box.appendChild(info("levels"));
}
function renderLevelsTable(v) {
	const box = $("#c-levtbl"), d = chartData();
	box.textContent = "";
	const lv = Object.assign({}, (d && d.levels) || {}, (v && v.levels) || {});
	const spot = v && fin(v.spot) ? v.spot : d && d.bars ? d.bars.c[d.bars.c.length - 1] : null;
	const rows = Object.entries(lv).filter(([k, x]) => LEVELS[k] && fin(x) && x > 0).map(([k, x]) => [LEVELS[k][0], x, k]);
	if (!rows.length || !fin(spot)) { box.appendChild(empty("info", "Levels appear once the session has a few bars.")); return; }
	rows.push(["Spot", spot, "spot"]);
	rows.sort((a, b) => b[1] - a[1]);
	box.appendChild(h("div", { class: "scroll" }, h("table", { class: "tbl" },
		h("tr", {}, h("th", {}, "Level"), h("th", {}, "Price"), h("th", {}, "From spot")),
		rows.map(([n, x, k]) => h("tr", { class: k === "spot" ? "spot" : "" },
			h("td", {}, k !== "spot" && LEVELS[k] ? h("span", { class: "sw", style: `background:${levelColor(k)}` }) : null, n),
			h("td", {}, num(x)),
			h("td", { class: k === "spot" ? "" : cls(x - spot) }, k === "spot" ? "—" : [signed(x - spot, 1), h("small", { class: "sub" }, pct((x - spot) / spot))]))))));
}
function renderQuant(v) {
	const box = $("#c-quant");
	box.textContent = "";
	const q = v && v.quant, c = (v && v.chain) || {};
	if (!q && !Object.keys(c).length) { box.appendChild(empty("info", "The quant layer's read appears while the desk runs.")); return; }
	const F = [];
	if (q) {
		const sig = q.sigma_30m_pct, band = fin(sig) && fin(v.spot) ? v.spot * sig / 100 : null, drift = q.research_drift;
		F.push(fact("30-min move, 1σ", fin(sig) ? `±${num(sig, 2)}%${band != null ? " · ±" + num(band, 0) + " pts" : ""}` : "—"),
			fact("Direction model", q.valid ? `Voting · AUC ${num(q.auc, 2)}` : `Off · AUC ${num(q.auc, 2)}`),
			fact("P(up) used", q.valid && fin(q.p_model) ? pct(q.p_model, 0).replace("+", "") : "coin flip + prior"),
			fact("Research drift", drift ? `${signed(drift.bps_day, 1)} bps/day · t ${num(drift.t, 1)}` : "none validated"));
	}
	// the option chain: where it stands and how it moved since the first read (chainflow.py)
	if (fin(c.atm_iv)) F.push(fact("ATM IV · 30 min", `${num(c.atm_iv, 1)}%` + (fin(c.cf_iv_chg30) ? ` · ${signed(c.cf_iv_chg30, 1)} pts` : "")
		+ (fin(c.atm_ivp) ? ` · pctile ${Math.round(c.atm_ivp * 100)}` : "")));
	if (fin(c.implied_move)) F.push(fact("Implied move to expiry", `±${num(c.implied_move * 100, 2)}%` + (fin(c.dte_days) ? ` · ${num(c.dte_days, 1)} days` : "")));
	if (fin(c.pcr_oi)) F.push(fact("PCR · today's ΔOI", num(c.pcr_oi) + (fin(c.pcr_doi) ? ` · ${num(c.pcr_doi)}` : "") + (fin(c.cf_pcr_chg30) ? ` (${signed(c.cf_pcr_chg30)} in 30 min)` : "")));
	if (fin(c.skew_25d)) F.push(fact("Skew, 25Δ put − call IV", `${signed(c.skew_25d, 1)} pts` + (fin(c.cf_skew_chg30) ? ` · ${signed(c.cf_skew_chg30, 1)} in 30 min` : "")));
	if (fin(c.call_wall) || fin(c.put_wall)) {
		const sh = (x) => (fin(x) && x ? ` (${signed(x, 0)})` : "");
		F.push(fact("OI walls · since first read", `call ${num(c.call_wall, 0)}${sh(c.cf_call_wall_shift)} · put ${num(c.put_wall, 0)}${sh(c.cf_put_wall_shift)}`));
	}
	if ((c.top_call_adds || []).length || (c.top_put_adds || []).length)
		F.push(fact("Fresh writing, today's ΔOI", `calls ${(c.top_call_adds || []).map((k) => num(k, 0)).join(", ") || "—"} · puts ${(c.top_put_adds || []).map((k) => num(k, 0)).join(", ") || "—"}`));
	if (fin(c.max_pain)) F.push(fact("Max pain", num(c.max_pain, 0)));
	if (fin(c.fut_basis)) F.push(fact("Futures basis · carry", `${signed(c.fut_basis, 1)} pts` + (fin(c.fut_carry) ? ` · ${num(c.fut_carry * 100, 1)}%/yr` : "")));
	if (c.fut_buildup) F.push(fact("Futures OI build-up", cap(c.fut_buildup)));
	if (c.gex_state) F.push(fact("Dealer gamma (naive sign)", cap(String(c.gex_state).split(" (")[0]) + (fin(c.gamma_flip) ? ` · flip ${num(c.gamma_flip, 0)}` : "")));
	if (F.length % 2) F.push(h("div", {}));
	put(box, h("div", { class: "facts" }, F),
		c.source === "model" ? h("p", { class: "narr pad", style: "border-top:1px solid var(--line);font-size:12px;color:var(--warn)" },
			"No live option chain: priced off India VIX, so the chain reads above are the model's, not the market's.") : null,
		q ? h("p", { class: "narr pad", style: "border-top:1px solid var(--line);font-size:12px;color:var(--fg3)" }, q.valid
			? "The direction model beat a coin flip out of sample, so its probability feeds the EV of every candidate trade."
			: `The direction model scored AUC ${num(q.auc, 2)} out of sample: no better than a coin flip, so it doesn't vote.${q.model_status ? " " + cap(q.model_status) + "." : ""}`) : null);
}
// what the record says (learning.py): the buyer's edge, factor IC by horizon, the factors on probation
function learnedGrp(L, sym) {
	const e = (L.edge || {})[sym], H = ["5", "15", "30", "60"], ic = (L.ic || []).slice(0, 8), pro = Object.entries(L.probation || {});
	const b = (x, c) => h("b", { class: c || "", style: "font-weight:400" }, x);
	const edge = h("div", { class: "pad", style: "display:grid;gap:6px" },
		h("div", { class: "lbl" }, "Buyer's edge: realised vs implied volatility"),
		e ? h("div", { class: "row", style: "flex-wrap:wrap;gap:6px 16px" },
			h("span", {}, "Realised ÷ implied ", b(num(e.rv_iv) + "×", e.rv_iv >= 1 ? "up" : "dn")),
			h("span", {}, "Realised beat implied on ", b(Math.round(e.rv_above * 100) + "%"), " of sessions"),
			e.move_ratio != null ? h("span", {}, "Move ÷ implied move ", b(num(e.move_ratio) + "×")) : null,
			h("span", { class: "f3" }, `${e.sessions} session${e.sessions === 1 ? "" : "s"}`))
			: h("div", { class: "f3", style: "font-size:12.5px" }, "Recorded from the first full session with a live option chain."),
		h("div", { class: "f3", style: "font-size:12px" }, "A desk that only buys options needs the index to move more than the options priced in. Below 1× it is paying for more movement than it gets."));
	const icTable = ic.length ? h("div", { class: "scroll" }, h("table", { class: "tbl" },
		h("tr", {}, h("th", {}, "Factor"), H.map((x) => h("th", {}, x + " min"))),
		ic.map((r) => h("tr", {}, h("td", {}, factorName(r.factor)), H.map((x) => {
			const c = r.h[x];
			return h("td", { class: c && Math.abs(c.t) >= 2 ? (c.ic > 0 ? "up" : "dn") : "f3", title: c ? `t ${num(c.t, 1)} · n ${num(c.n, 0)}` : "" }, c ? signed(c.ic, 3) : "—");
		})))))
		: empty("info", "Fills as sessions are graded: each factor's direction against the move 5, 15, 30 and 60 minutes later.");
	return grp("What the desk has learned", `${L.sessions || 0} session${L.sessions === 1 ? "" : "s"} graded`, h("div", { class: "rows" }, edge,
		h("div", {}, h("div", { class: "pad", style: "padding-bottom:2px" }, h("div", { class: "lbl" }, "Factor IC by horizon"),
			h("div", { class: "f3", style: "font-size:12px;margin-top:4px" }, "Correlation of each factor's call with the index's move that followed. In colour: |t| ≥ 2 on overlap-adjusted samples.")), icTable),
		pro.length ? h("div", { class: "pad", style: "display:grid;gap:6px" }, h("div", { class: "lbl" }, "On probation: graded live, no vote yet"),
			pro.map(([f, p]) => h("div", { class: "row" }, h("span", { class: "grow" }, factorName(f)),
				h("span", { class: "tag " + (p.voting ? "bull" : "dash") }, p.voting ? `Voting · ×${num(p.rel)}` : `${num(p.n, 0)} of 30 graded · ×${num(p.rel)}`)))) : null));
}

// ---- TradingView Lightweight Charts (vendored); IST on the axis by shifting times +5:30 ---------------------------------
const IST_OFF = 19800;
function lwTheme() {
	return {
		layout: { background: { type: "solid", color: cssv("--panel") }, textColor: cssv("--fg3"), fontSize: 11, fontFamily: cssv("--mono") || "monospace", attributionLogo: true },
		grid: { vertLines: { color: cssv("--grid") }, horzLines: { color: cssv("--grid") } },
		rightPriceScale: { borderColor: cssv("--line"), scaleMargins: { top: 0.12, bottom: 0.16 } },
		timeScale: { borderColor: cssv("--line"), timeVisible: true, secondsVisible: false, rightOffset: 5, minBarSpacing: 2 },
		crosshair: { mode: 0, vertLine: { color: cssv("--fg3"), width: 1, style: 3, labelBackgroundColor: cssv("--raise") },
			horzLine: { color: cssv("--fg3"), width: 1, style: 3, labelBackgroundColor: cssv("--raise") } },
	};
}
function candleColors() {
	const up = cssv("--cup"), dn = cssv("--cdn");
	return { upColor: up, downColor: dn, borderUpColor: up, borderDownColor: dn, wickUpColor: up, wickDownColor: dn };
}
// The session profile, drawn inside the price pane from its right edge: how much volume (or, for an index with no
// volume, how much time) traded at each price. The POC bar is strongest, the value area tinted, the rest muted.
function makeSVP() {
	let data = null, series = null, requestUpdate = null;
	const renderer = {
		draw(target) {
			if (!data || !series) return;
			target.useBitmapCoordinateSpace((sc) => {
				const ctx = sc.context, vr = sc.verticalPixelRatio, W = sc.bitmapSize.width, maxW = W * 0.24, half = data.step / 2;
				const acc = cssv("--acc"), mute = cssv("--fg3");
				data.prices.forEach((p, i) => {
					const y1 = series.priceToCoordinate(p + half), y2 = series.priceToCoordinate(p - half);
					if (y1 == null || y2 == null) return;
					const w = data.size[i] * maxW, poc = Math.abs(p - data.poc) <= half, inVA = p >= data.val - half && p <= data.vah + half;
					ctx.globalAlpha = poc ? 0.75 : inVA ? 0.32 : 0.16;
					ctx.fillStyle = poc || inVA ? acc : mute;
					ctx.fillRect(W - w, Math.min(y1, y2) * vr, w, Math.max(1, Math.abs(y2 - y1) * vr - 1));
				});
				ctx.globalAlpha = 1;
			});
		},
	};
	const view = { zOrder: () => "bottom", renderer: () => renderer };
	return {
		attached(p) { series = p.series; requestUpdate = p.requestUpdate; },
		detached() { series = null; requestUpdate = null; },
		updateAllViews() {},
		paneViews: () => [view],
		set(d) { data = d && d.prices && d.prices.length ? d : null; if (requestUpdate) requestUpdate(); },
	};
}
function destroyLW() { if (S.lw) { try { S.lw.chart.remove(); } catch (e) { /* gone */ } } S.lw = null; }
function createLW(el) {
	const LW = window.LightweightCharts;
	el.textContent = "";
	const chart = LW.createChart(el, Object.assign(lwTheme(), {
		autoSize: true,
		handleScroll: { mouseWheel: true, pressedMouseMove: true, horzTouchDrag: true, vertTouchDrag: false },
		handleScale: { axisPressedMouseMove: true, mouseWheel: true, pinch: true },
		localization: { priceFormatter: (p) => num(p, p > 1000 ? 1 : 2) },
	}));
	const candle = chart.addSeries(LW.CandlestickSeries, Object.assign({ priceLineVisible: true, lastValueVisible: true, priceLineStyle: 3 }, candleColors()));
	const vol = chart.addSeries(LW.HistogramSeries, { priceScaleId: "vol", priceFormat: { type: "volume" }, lastValueVisible: false, priceLineVisible: false });
	chart.priceScale("vol").applyOptions({ scaleMargins: { top: 0.86, bottom: 0 }, visible: false });
	const vwap = chart.addSeries(LW.LineSeries, { color: cssv("--vwap"), lineWidth: 2, priceLineVisible: false, lastValueVisible: true, crosshairMarkerVisible: false, title: "VWAP" });
	const markers = LW.createSeriesMarkers ? LW.createSeriesMarkers(candle, []) : null;
	const svp = typeof candle.attachPrimitive === "function" ? makeSVP() : null;
	if (svp) candle.attachPrimitive(svp);
	S.lw = { chart, candle, vol, vwap, markers, svp, lines: [], key: null, byTime: new Map(), marksAt: new Map() };
	chart.subscribeCrosshairMove((param) => ohlcLegend(param && param.time));
}
function ohlcLegend(time) {
	const d = chartData(), L = S.lw, el = $("#c-ohlc");
	if (!L || !d || !d.bars) { el.textContent = ""; return; }
	const B = d.bars, n = B.t.length;
	let i = n - 1;
	if (time != null) { const j = L.byTime.get(time); if (j != null) i = j; }
	const prev = i > 0 ? B.c[i - 1] : B.o[i], chg = (B.c[i] / prev - 1) * 100;
	const kv = (k, v) => [h("span", { class: "k" }, k), v, "  "];
	el.textContent = "";
	put(el, h("div", {}, h("b", {}, ist(B.t[i])), "  ", ...kv("O", num(B.o[i])), ...kv("H", num(B.h[i])), ...kv("L", num(B.l[i])),
		h("span", { class: "k" }, "C"), h("b", { class: cls(chg) }, `${num(B.c[i])} ${chg >= 0 ? "+" : "−"}${Math.abs(chg).toFixed(2)}%`)),
	h("div", { class: "r2" }, h("span", { style: "color:var(--vwap)" }, "VWAP " + num(d.vwap[i])), B.v[i] > 0 ? "  Vol " + num(B.v[i], 0) : "",
		d.profile ? h("span", { style: "color:var(--acc)", title: d.profile.kind === "tpo" ? "time at price: an index has no volume" : "volume at price" },
			`  POC ${num(d.profile.poc, 0)} · VA ${num(d.profile.val, 0)}–${num(d.profile.vah, 0)}${d.profile.kind === "tpo" ? " (TPO)" : ""}`
			+ (d.profile.day && d.profile.day !== d.day ? ` · ${d.profile.day.slice(8)}/${d.profile.day.slice(5, 7)}` : "")) : "",
		...(L.marksAt.get(B.t[i]) || []).map((m) => `  ${m.kind === "entry" ? "▲" : "●"} ${m.text}`)));
}
function drawChart(reframe) {
	const el = $("#chart"), d = chartData();
	if (!window.LightweightCharts || !window.LightweightCharts.createChart) { el.textContent = ""; el.appendChild(empty("chart", "The chart library didn't load.")); return; }
	if (!d || !d.bars) {
		destroyLW();
		el.textContent = "";
		$("#c-ohlc").textContent = "";
		el.appendChild(empty("chart", S.ckind === "fut" ? "No futures bars recorded yet: they come from Kotak during the session (near month, with real volume)."
			: "No bars recorded yet for this session."));
		$("#c-levels").textContent = "";
		return;
	}
	if (!S.lw) createLW(el);
	const L = S.lw, B = d.bars, n = B.t.length, up = cssv("--cup"), dn = cssv("--cdn");
	const T = (t) => t + IST_OFF;
	L.byTime = new Map(B.t.map((t, i) => [T(t), i]));
	L.candle.setData(B.t.map((t, i) => ({ time: T(t), open: B.o[i], high: B.h[i], low: B.l[i], close: B.c[i] })));
	const hasVol = B.v.some((x) => x > 0);
	L.vol.setData(hasVol ? B.t.map((t, i) => ({ time: T(t), value: B.v[i], color: (B.c[i] >= B.o[i] ? up : dn) + "44" })) : []);
	// VWAP restarts each session. A point's colour paints the segment that leaves it (Lightweight Charts 5 draws a
	// line straight through whitespace), so the last bar before each session start leaves a transparent segment.
	const starts = new Set(((d.session_starts) || []).slice(1));
	L.vwap.setData(B.t.map((t, i) => (i + 1 < n && starts.has(B.t[i + 1])
		? { time: T(t), value: d.vwap[i], color: "transparent" } : { time: T(t), value: d.vwap[i] })));
	if (L.svp) L.svp.set(d.profile);
	L.lines.forEach((pl) => L.candle.removePriceLine(pl));
	L.lines = [];
	const on = levelsOn();
	for (const [k, x] of Object.entries(d.levels || {})) {
		if (!LEVELS[k] || !on[LEVELS[k][1]] || !(x > 0) || k === "vwap") continue;
		L.lines.push(L.candle.createPriceLine({ price: x, color: levelColor(k), lineWidth: k.includes("wall") ? 2 : 1, lineStyle: k === "poc" ? 0 : 2,
			axisLabelVisible: true, title: LEVELS[k][0] }));
	}
	renderLevelChips();
	const snap = (t) => { let lo = 0; for (let i = 0; i < n; i++) if (B.t[i] <= t) lo = i; return B.t[lo]; };
	L.marksAt = new Map();
	const mk = (d.markers || []).map((m) => {
		const bt = snap(m.t), long = m.dir >= 0, entry = m.kind === "entry";
		(L.marksAt.get(bt) || L.marksAt.set(bt, []).get(bt)).push(m);
		const loss = /₹-|₹−/.test(m.text);
		return { time: T(bt), position: entry ? (long ? "belowBar" : "aboveBar") : (long ? "aboveBar" : "belowBar"), shape: entry ? (long ? "arrowUp" : "arrowDown") : "circle",
			color: entry ? cssv("--acc-hi") : (loss ? dn : up), text: entry ? m.text.split(" · ")[0] : m.text.replace(/^\S+\s/, "") };
	}).sort((a, b) => a.time - b.time);
	if (L.markers) L.markers.setMarkers(mk); else if (L.candle.setMarkers) L.candle.setMarkers(mk);
	const key = `${d.symbol}|${d.interval}|${d.day}`;
	if (reframe || L.key !== key) {
		L.key = key;
		const narrow = el.clientWidth < 640, want = d.interval === "1m" ? (narrow ? 90 : 200) : d.interval === "5m" ? (narrow ? 60 : n) : n;
		if (n > want) L.chart.timeScale().setVisibleLogicalRange({ from: n - want, to: n + 4 });
		else L.chart.timeScale().fitContent();
	}
	ohlcLegend(null);
}
function restyleCharts() {
	if (S.lw) {
		S.lw.chart.applyOptions(lwTheme());
		S.lw.candle.applyOptions(candleColors());
		S.lw.vwap.applyOptions({ color: cssv("--vwap") });
		drawChart(false);
	}
	if (S.eq) { try { const t = lwTheme(); delete t.timeScale; S.eq.chart.applyOptions(t); S.eq.paint(); } catch (e) { /* gone */ } }
	if (S.tab === "desk" && S.state) renderDesk();
}
function fullscreen(on) {
	const box = $("#c-box");
	box.classList.toggle("fs", on);
	document.body.style.overflow = on ? "hidden" : "";
	if (S.lw) setTimeout(() => S.lw && S.lw.chart.timeScale().scrollToRealTime(), 60);
}

// ==================================================================================================================
// TRADES
// ==================================================================================================================
async function renderTrades(full) {
	seg($("#t-seg"), SUBS.trades, S.sub.trades, (v) => { S.sub.trades = v; history.replaceState(null, "", "#trades/" + v); renderTrades(true); }, "tab");
	const body = $("#t-body"), sub = S.sub.trades;
	if (sub === "positions") return renderPositionsTab(body);
	if (!full && sub !== "positions") return;
	body.textContent = "";
	body.appendChild(h("div", { class: "panel" }, h("div", { class: "pad" }, h("span", { class: "skel", style: "width:70%" }), h("span", { class: "skel", style: "width:40%;margin-top:10px" }))));
	if (sub === "history") return renderHistory(body);
	if (sub === "performance") return renderPerformance(body);
	if (sub === "reviews") return renderReviews(body);
}
// a section: a header band (title, hint or a control) over its rows
function grp(title, hint, ...content) {
	return h("div", { class: "grp" }, h("div", { class: "sec-h" }, h("h2", {}, title),
		hint == null || hint === "" ? null : typeof hint === "object" ? hint : h("span", { class: "hint" }, hint)), ...content);
}
function renderPositionsTab(body) {
	const st = S.state || {}, hb = st.heartbeat || {}, pos = hb.positions || [], ct = st.closed_today || [];
	const net = ct.reduce((a, t) => a + t.pnl, 0);
	body.textContent = "";
	put(body,
		grp("Open", pos.length ? inr(pos.reduce((a, p) => a + (p.pnl || 0), 0), true) + " open P&L" : "",
			h("div", { class: "rows" }, pos.length ? pos.map(positionCard) : empty("target", "Flat: no open positions. The desk takes at most one position at a time."))),
		grp("Closed today", ct.length ? h("span", { class: "hint " + cls(net) }, inr(net, true)) : "",
			h("div", { class: "rows" }, ct.length ? ct.map(tradeRow) : empty("trades", "No closed trades this session."))));
}
function tradeRow(t) {
	const open = t.status === "open";
	return h("button", { class: "trow", onclick: () => openTrade(t.id) },
		h("span", { class: "tm" }, h("b", {}, ist(t.opened_at)), open ? h("span", { class: "acc" }, "open") : h("span", {}, t.closed_at ? ist(t.closed_at) : "")),
		h("div", { style: "min-width:0" }, h("div", { class: "t1" }, setupName(t.strategy)),
			h("div", { class: "t2" }, `${t.symbol}${t.structure ? " · " + structName(t.structure) : ""}${t.units ? ` · ${t.units} lot${t.units === 1 ? "" : "s"}` : ""}`)),
		h("div", { class: "v " + (open ? "" : cls(t.pnl)) }, open ? "Open" : inr(t.pnl, true),
			h("small", {}, open ? "" : `${fin(t.r_multiple) ? signed(t.r_multiple) + "R · " : ""}${cap(words(t.exit_reason || ""))}`)),
		h("span", { class: "grade " + (t.grade || "") }, t.grade || "–"));
}
async function renderHistory(body) {
	let rows;
	try { rows = await api("/api/i/trades?n=300"); } catch (e) { body.textContent = ""; body.appendChild(h("div", { class: "panel" }, empty("alert", e.message))); return; }
	if (S.tab !== "trades" || S.sub.trades !== "history") return;
	body.textContent = "";
	if (!rows.length) { body.appendChild(h("div", { class: "panel" }, empty("trades", "No trades yet. Every trade the desk takes lands here with its full reasoning."))); return; }
	const days = new Map();
	for (const t of rows) { const d = String(t.opened_at).slice(0, 10); (days.get(d) || days.set(d, []).get(d)).push(t); }
	const closed = rows.filter((t) => t.status !== "open"), net = closed.reduce((a, t) => a + t.pnl, 0), wins = closed.filter((t) => t.pnl > 0).length;
	const nOpen = rows.length - closed.length;
	body.appendChild(h("div", { class: "panel" }, h("div", { class: "kpis" },
		h("div", { class: "kpi" }, h("span", {}, `Net, ${days.size} session${days.size === 1 ? "" : "s"}`), h("b", { class: cls(net) }, inr(net, true))),
		h("div", { class: "kpi" }, h("span", {}, "Trades"), h("b", {}, `${rows.length}${nOpen ? " · " + nOpen + " open" : ""}`)),
		h("div", { class: "kpi" }, h("span", {}, "Won"), h("b", {}, closed.length ? `${wins} of ${closed.length}` : "—")),
		h("div", { class: "kpi" }, h("span", {}, "Win rate"), h("b", {}, closed.length ? Math.round(wins / closed.length * 100) + "%" : "—")))));
	for (const [d, ts] of days) {
		const dn = ts.filter((t) => t.status !== "open").reduce((a, t) => a + t.pnl, 0);
		body.appendChild(h("div", { class: "grp" }, h("div", { class: "dayh" }, h("span", {}, istDay(d + "T12:00:00+05:30")), h("span", { class: cls(dn) }, inr(dn, true))),
			h("div", { class: "rows" }, ts.map(tradeRow))));
	}
}
async function openTrade(id) {
	let t;
	try { t = await api("/api/i/trade?id=" + encodeURIComponent(id)); } catch (e) { return toast(e.message); }
	const para = (label, text) => (text ? h("div", { class: "para" }, h("div", { class: "lbl" }, label), h("p", {}, text)) : null);
	const [why, ...rest] = String(t.rationale || "").split(" Market read: ");
	const open = t.status === "open", held = t.closed_at ? Math.round((tms(t.closed_at) - tms(t.opened_at)) / 60000) : null;
	const legs = (t.legs || []).map((l) => ({ symbol: (l.instrument || {}).symbol || l.symbol, qty: l.qty, entry: l.entry_price, exit: l.exit_price }));
	openSheet(`${t.symbol} · ${setupName(t.strategy)}`,
		h("div", { class: "row", style: "align-items:flex-end;margin-bottom:12px" },
			h("div", { class: "grow" }, h("div", { class: "lbl" }, open ? "Open P&L" : "Net P&L, after costs"),
				h("div", { class: cls(t.pnl), style: "font-size:26px;font-weight:300;letter-spacing:-.02em" }, open ? "Open" : inr(t.pnl, true))),
			h("div", { style: "text-align:right" }, h("span", { class: "grade " + (t.grade || "") }, t.grade || "·"), info("grade"))),
		h("div", { class: "kpis" },
			h("div", { class: "kpi" }, h("span", {}, "R multiple"), h("b", { class: cls(t.r_multiple) }, fin(t.r_multiple) ? signed(t.r_multiple) + "R" : "—")),
			h("div", { class: "kpi" }, h("span", {}, "Risked"), h("b", {}, inr(t.initial_risk))),
			h("div", { class: "kpi" }, h("span", {}, "Lots · costs"), h("b", {}, `${t.units} · ${inr(t.fees)}`)),
			h("div", { class: "kpi" }, h("span", {}, "Held"), h("b", {}, held != null ? `${held} min` : "—"))),
		h("div", { class: "panel", style: "margin-top:12px" }, h("div", { class: "pad" },
			h("div", { class: "row", style: "font-size:13px" }, h("span", { class: "f3" }, "Entry"), h("b", { class: "mono" }, `${ist(t.opened_at, true)} @ ${num(t.entry_underlying)}`)),
			h("div", { class: "row", style: "font-size:13px;margin-top:6px" }, h("span", { class: "f3" }, "Exit"),
				h("b", { class: "mono" }, t.closed_at ? `${ist(t.closed_at)} @ ${num(t.exit_underlying)}` : "open")),
			fin(t.stop) && fin(t.target) ? h("div", { style: "margin-top:10px" }, track(t.stop, t.target, t.entry_underlying, open ? null : t.exit_underlying, t.direction)) : null,
			legs.length ? h("div", { style: "margin-top:12px" }, legsTable(legs, true)) : null)),
		para("Why it was taken", why), para("What the market looked like", rest.join(" Market read: ")),
		para("Sizing", (t.sizing || []).join(" · ")), para("Exit", t.exit_reason ? `${cap(words(t.exit_reason))}: ${t.exit_note || ""}` : "Still open"),
		para("Review", t.review), para("Lessons", (t.lessons || []).join(" ")),
		t.fills && t.fills.length ? h("div", { class: "para" }, h("div", { class: "lbl" }, "Fills"), h("div", { class: "panel scroll" }, h("table", { class: "tbl" },
			h("tr", {}, h("th", {}, "Time"), h("th", {}, "Contract"), h("th", {}, "Qty"), h("th", {}, "Price"), h("th", {}, "Fees")),
			t.fills.map((f) => h("tr", {}, h("td", {}, ist(f.ts)), h("td", {}, f.symbol), h("td", {}, f.qty), h("td", {}, num(f.price)), h("td", {}, num(f.fees))))))) : null);
}
async function renderPerformance(body) {
	let s;
	try { s = await api("/api/i/stats"); } catch (e) { body.textContent = ""; body.appendChild(empty("alert", e.message)); return; }
	if (S.tab !== "trades" || S.sub.trades !== "performance") return;
	body.textContent = "";
	if (!s.trades) { body.appendChild(h("div", { class: "panel" }, empty("chart", "No closed trades yet. Performance appears after the first trade closes; until then the desk's reads are under Feed › Desk log."))); return; }
	const kpi = (l, v, c) => h("div", { class: "kpi" }, h("span", {}, l), h("b", { class: c || "" }, v));
	put(body, h("div", { class: "panel" }, h("div", { class: "kpis" },
		kpi("Net P&L", inr(s.net, true), cls(s.net)), kpi("Return", pct(s.net / s.capital, 1), cls(s.net)),
		kpi("Win rate", Math.round(s.win_rate * 100) + "%"), kpi("Profit factor", s.profit_factor ? num(s.profit_factor) : "—"),
		kpi("Avg trade", signed(s.avg_r) + "R", cls(s.avg_r)), kpi("Max drawdown", pct(s.max_dd, 1), "dn"),
		kpi("Green days", Math.round(s.green_days * 100) + "%"), kpi("Costs paid", inr(s.fees)))));
	const eqc = h("div", { class: "eqc" });
	body.appendChild(grp("Equity", `${s.trades} trades · ${s.sessions} sessions · dashed: start`, eqc));
	drawEquity(eqc, s);
	body.appendChild(grp("P&L by setup", "trades", hbars(s.by_setup, setupName)));
	const BRK = [["by_day_type", "Day type"], ["by_structure", "Structure"], ["by_exit", "Exit"], ["by_hour", "Hour"], ["by_symbol", "Index"]];
	const segEl = h("div", { class: "seg" }), tbl = h("div", { class: "scroll" });
	const paint = () => {
		tbl.textContent = "";
		tbl.appendChild(h("table", { class: "tbl" }, h("tr", {}, h("th", {}, ""), h("th", {}, "Trades"), h("th", {}, "Win"), h("th", {}, "Avg R"), h("th", {}, "Net")),
			(s[S.brk] || []).map((r) => h("tr", {}, h("td", {}, cap(words(r.key))), h("td", {}, r.trades), h("td", {}, Math.round(r.win * 100) + "%"),
				h("td", { class: cls(r.avg_r) }, signed(r.avg_r)), h("td", { class: cls(r.pnl) }, inr(r.pnl, true))))));
	};
	seg(segEl, BRK, S.brk, (v) => { S.brk = v; paint(); });
	paint();
	body.appendChild(grp("Breakdown", "closed trades", h("div", { style: "padding:8px 16px 10px;border-top:1px solid var(--line)" }, segEl), tbl));
	if ((s.calibration || []).length)
		body.appendChild(grp("Calibration", "priced vs realised",
			h("div", {}, h("p", { class: "narr pad", style: "font-size:12px;color:var(--fg3)" },
				"P(right direction) the quant layer priced each trade on, against how often the index actually went that way by the exit. Until the realised column tracks the assumed one over many trades, the edge is unproven."),
			h("div", { class: "scroll" }, h("table", { class: "tbl" }, h("tr", {}, h("th", {}, "Source"), h("th", {}, "Assumed"), h("th", {}, "Trades"), h("th", {}, "Realised"), h("th", {}, "Net")),
				s.calibration.map((r) => h("tr", {}, h("td", {}, cap(String(r.source).split(/ from | \(/)[0])), h("td", {}, Math.round(r.assumed * 100) + "%"), h("td", {}, r.trades),
					h("td", {}, Math.round(r.realised * 100) + "%"), h("td", { class: cls(r.pnl) }, inr(r.pnl, true)))))))));
}
function drawEquity(el, s) {
	if (S.eq) { try { S.eq.chart.remove(); } catch (e) { /* gone */ } S.eq = null; }
	const LW = window.LightweightCharts;
	if (!LW || !s.equity || !s.equity.length) return;
	const chart = LW.createChart(el, Object.assign(lwTheme(), { autoSize: true, handleScroll: false, handleScale: false,
		localization: { priceFormatter: (p) => inr(p) } }));
	chart.applyOptions({ timeScale: { timeVisible: false, borderColor: cssv("--line"), rightOffset: 0, fixLeftEdge: true, fixRightEdge: true },
		rightPriceScale: { scaleMargins: { top: 0.15, bottom: 0.1 } } });
	const ser = chart.addSeries(LW.BaselineSeries, { baseValue: { type: "price", price: s.capital }, lineWidth: 2, priceLineVisible: false });
	const first = new Date(s.equity[0].day + "T00:00:00Z");
	first.setUTCDate(first.getUTCDate() - 1);
	const pts = [{ time: first.toISOString().slice(0, 10), value: s.capital }, ...s.equity.map((r) => ({ time: r.day, value: r.equity }))];
	const paint = () => {
		const up = cssv("--up"), dn = cssv("--dn");
		ser.applyOptions({ topLineColor: up, topFillColor1: up + "40", topFillColor2: up + "05", bottomLineColor: dn, bottomFillColor1: dn + "05", bottomFillColor2: dn + "40" });
	};
	paint();
	ser.setData(pts);
	ser.createPriceLine({ price: s.capital, color: cssv("--fg3"), lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: "start" });
	chart.timeScale().fitContent();
	S.eq = { chart, paint };
}
function hbars(rows, name) {
	const box = h("div", {});
	rows = [...rows].sort((a, b) => b.pnl - a.pnl);
	const max = Math.max(...rows.map((r) => Math.abs(r.pnl)), 1);
	for (const r of rows) {
		const w = Math.abs(r.pnl) / max * 50;
		box.appendChild(h("div", { class: "hb" }, h("span", {}, name ? name(r.key) : r.key, h("div", { class: "f3", style: "font-size:11px" }, `${r.trades} trade${r.trades === 1 ? "" : "s"} · ${Math.round(r.win * 100)}% won`)),
			h("div", { class: "bar2" }, h("i", { style: `${r.pnl >= 0 ? "left:50%" : "right:50%"};width:${w}%;background:${r.pnl >= 0 ? "var(--up)" : "var(--dn)"}` })),
			h("b", { class: cls(r.pnl) }, inr(r.pnl, true))));
	}
	return box;
}
async function renderReviews(body) {
	let dates;
	try { dates = await api("/api/i/reviews"); } catch (e) { body.textContent = ""; body.appendChild(empty("alert", e.message)); return; }
	if (S.tab !== "trades" || S.sub.trades !== "reviews") return;
	body.textContent = "";
	body.appendChild(grp("Session reviews", dates.length ? `${dates.length}` : "", h("div", { class: "rows" }, dates.length ? dates.map((d) =>
		h("button", { class: "set", onclick: async () => {
			try { const r = await api("/api/i/review?date=" + encodeURIComponent(d)); openSheet("Session " + istDay(d + "T12:00:00+05:30"), markdown(r.markdown)); } catch (e) { toast(e.message); }
		} }, icon("book"), h("div", { class: "grow" }, istDay(d + "T12:00:00+05:30"), h("small", {}, "The desk's own post-session review")), icon("chev")))
		: empty("book", "Session reviews appear after each close."))));
}
function inline(text) {
	const out = [];
	String(text).split(/(\*\*[^*]+\*\*)/).forEach((p) => out.push(p.startsWith("**") && p.endsWith("**") ? h("b", {}, p.slice(2, -2)) : p));
	return out;
}
function markdown(md) {
	const root = h("div", { class: "md" }), lines = String(md || "").split("\n");
	for (let i = 0; i < lines.length; i++) {
		const l = lines[i];
		if (/^#{1,3} /.test(l)) root.appendChild(h(l.startsWith("## ") ? "h2" : "h1", {}, inline(l.replace(/^#+ /, ""))));
		else if (l.startsWith("|")) {
			const rows = [];
			while (i < lines.length && lines[i].startsWith("|")) { if (!/^\|[-:| ]+\|$/.test(lines[i])) rows.push(lines[i]); i++; }
			i--;
			const cells = (r) => r.slice(1, -1).split("|").map((c) => c.trim());
			root.appendChild(h("div", { class: "panel scroll" }, h("table", { class: "tbl" }, rows.map((r, k) => h("tr", {}, cells(r).map((c) => h(k ? "td" : "th", {}, inline(c))))))));
		} else if (l.startsWith("- ")) root.appendChild(h("li", {}, inline(l.slice(2))));
		else if (l.trim()) root.appendChild(h("p", {}, inline(l)));
	}
	return root;
}

// ==================================================================================================================
// BRAIN
// ==================================================================================================================
function renderBrain() {
	const syms = symbols();
	if (!syms.includes(S.brainSym)) S.brainSym = syms[0];
	seg($("#b-sym"), syms.map((s) => [s, s]), S.brainSym, (v) => { S.brainSym = v; renderBrain(); });
	const hb = (S.state && S.state.heartbeat) || {}, v = (hb.views || {})[S.brainSym] || {}, b = v.brain, body = $("#b-body");
	body.textContent = "";
	// regime
	if (!b) body.appendChild(h("div", { class: "panel" }, empty("globe", "The brain's global read appears here while the desk runs: which world markets are moving, how they usually lean on India, and what that means for the bias.")));
	else {
		const rc = b.regime === "risk-on" ? "on" : b.regime === "risk-off" ? "offr" : "mixed";
		body.appendChild(grp("Global regime", info("regime"),
			h("div", { class: "regime" }, h("div", { class: "big " + rc }, (rc === "on" ? "▲ " : rc === "offr" ? "▼ " : "") + words(b.regime)),
				h("div", { class: "tags" }, h("span", { class: "tag line" }, `Score ${signed(b.regime_score)}`),
					h("span", { class: "tag " + (b.stress >= 2 ? "bear" : "line") }, `Global stress ${num(b.stress, 1)}σ`), info("stress"),
					h("span", { class: "tag " + (b.size_mult < 1 ? "warn" : "line") }, b.size_mult < 1 ? `Size ×${num(b.size_mult)}` : "Full size")),
				b.narrative ? h("p", { class: "narr" }, b.narrative) : null)));
	}
	// the open, explained
	if (b && b.gap) {
		const g = b.gap, against = g.explained * g.gap < 0 && Math.abs(g.explained) > 0.0005;
		const txt = against
			? `${S.brainSym} opened ${pct(g.gap)}, against the global cue: what the world did while India was shut pointed to ${pct(g.explained)}. India shrugged it off.`
			: g.share != null && g.share > 1.2
				? `${S.brainSym} opened ${pct(g.gap)}, while what the world did overnight pointed to ${pct(g.explained)}: India moved less than the global cue.`
				: `${S.brainSym} opened ${pct(g.gap)}. What global markets did while India was shut accounts for ${pct(g.explained)}` +
					(g.share != null && g.share > 0 ? `, about ${Math.round(g.share * 100)}% of the gap.` : ".");
		body.appendChild(grp("The opening gap", "09:15", h("div", { class: "pad" }, h("p", { class: "narr", style: "color:var(--fg)" }, txt),
			(g.parts || []).length ? h("div", { class: "chips", style: "margin-top:8px" }, g.parts.map(([n, x]) => h("span", { class: "tag " + (x > 0 ? "bull" : x < 0 ? "bear" : "flat") }, `${n} ${pct(x)}`))) : null)));
	}
	// influence graph
	body.appendChild(grp("How the read is built", "world → India → bias → decision",
		h("div", {}, h("p", { class: "narr pad", style: "font-size:12px;color:var(--fg3);padding-bottom:0" }, "Solid: research-validated leads that vote. Dashed: explains, doesn't vote."),
			h("div", { class: "scroll", id: "bgraph" }))));
	drawBrainGraph($("#bgraph"), v, hb);
	// what's pushing the bias
	body.appendChild(grp("What's pushing the bias", v.bias ? `${cap(v.bias)} ${signed(v.score)}` : "", evidenceList(v.evidence || [], 8)));
	if (hb.learning) body.appendChild(learnedGrp(hb.learning, S.brainSym));
	// global markets board
	const G = hb.global || {}, mk = G.markets || {}, board = h("div", { class: "rows" });
	for (const r of ["US", "Asia", "Europe", "FX", "Commodities", "Rates"]) {
		const ms = Object.entries(mk).filter(([, m]) => m.region === r);
		if (!ms.length) continue;
		board.appendChild(h("div", { class: "reg-h" }, r));
		for (const [, m] of ms) {
			const c = mchg(m), lean = c == null || !m.india ? "" : (c * m.india > 0 ? "up" : c * m.india < 0 ? "dn" : "");
			board.appendChild(h("div", { class: "grow-row" },
				h("div", { class: "n" }, h("i", { class: m.live ? "on" : "" }), h("span", {}, m.name)),
				h("div", { class: "v" }, m.last != null ? num(m.last, m.last > 1000 ? 0 : 2) : "—"),
				h("span", { class: "chg " + (lean || "flat") }, pct(c)),
				h("div", { class: "s" }, `${m.live && m.since_open != null ? "since 09:15 IST" : "last session" + (m.prior_date ? " " + m.prior_date : "")}` +
					(m.z30 != null ? ` · 30m ${signed(m.z30, 1)}σ` : "") + (m.india ? ` · usually ${m.india > 0 ? "moves with" : "leans against"} India` : ""))));
		}
	}
	if (!Object.keys(mk).length) board.appendChild(empty("globe", "Global markets appear here while the desk runs."));
	body.appendChild(grp("Global markets", "colour: good or bad for India", board));
	// the wiring
	const ds = (b && b.drivers) || [];
	body.appendChild(grp("The wiring, measured", "weekly research, real data",
		h("div", { class: "scroll" }, ds.length ? h("table", { class: "tbl" },
			h("tr", {}, h("th", {}, "Driver"), h("th", {}, "Gap ρ"), h("th", {}, "Same-5m ρ"), h("th", {}, "Lead t"), h("th", {}, "Status")),
			ds.map((d) => h("tr", {}, h("td", {}, d.name), h("td", {}, fin(d.gap_corr) ? num(d.gap_corr) : "—"), h("td", {}, fin(d.co_corr) ? num(d.co_corr) : "—"),
				h("td", {}, fin(d.lead_t) ? num(d.lead_t, 1) : "—"),
				h("td", {}, h("span", { class: "tag " + (d.validated ? "bull" : "dash") }, d.validated ? (d.lead_sign < 0 ? "Validated · fades" : "Validated") : "Probation")))))
			: empty("info", "Appears with the brain's first read."))));
}
function drawBrainGraph(el, v, hb) {
	el.textContent = "";
	const b = v.brain;
	if (!b && !(v.evidence || []).length) { el.appendChild(empty("brain", "Appears with the first market read.")); return; }
	const W = 340, colX = [2, 126, 236], nodeW = [112, 92, 102];
	const world = (b && b.drivers) || [];
	const agg = {};
	for (const e of v.evidence || []) {
		const n = CAT_G[e.category] || cap(e.category);
		const a = (agg[n] = agg[n] || { n, c: 0, w: 0 });
		a.c += e.direction * e.weight; a.w += e.weight;
	}
	const india = ["Tape", "Flow", "Options", "Vol", "News", "Quant", "Global"].filter((k) => agg[k]).map((k) => agg[k]);
	const rowH = 36, H = Math.max(world.length, india.length, 3) * rowH + 30;
	const g = svg("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": "Influence graph from global markets to the decision" }, el);
	const yOf = (i, n) => 24 + (H - 30) * (i + 0.5) / n;
	const color = (x) => (x > 0.02 ? cssv("--up") : x < -0.02 ? cssv("--dn") : cssv("--line2"));
	[["World", colX[0]], ["India read", colX[1]], ["Bias → decision", colX[2]]].forEach(([t, x]) => { svg("text", { x, y: 12, class: "t" }, g).textContent = t; });
	const biasY = H / 2 - 22, decY = H / 2 + 26;
	const edge = (x1, y1, x2, y2, w, col, dash) => svg("path", { d: `M${x1} ${y1} C${(x1 + x2) / 2} ${y1}, ${(x1 + x2) / 2} ${y2}, ${x2} ${y2}`,
		fill: "none", stroke: col, "stroke-width": w, "stroke-dasharray": dash || "", "stroke-opacity": 0.8 }, g);
	const node = (x, y, w, t1, t2, col) => {
		svg("rect", { x, y: y - 15, width: w, height: 30, rx: 8, fill: cssv("--panel2"), stroke: col, "stroke-width": 1.5 }, g);
		svg("text", { x: x + 7, y: y - 2, class: "t" }, g).textContent = t1;
		svg("text", { x: x + 7, y: y + 10 }, g).textContent = t2;
	};
	const gNode = india.find((x) => x.n === "Global"), newsNode = india.find((x) => x.n === "News");
	world.forEach((d, i) => {
		const y = yOf(i, world.length), p = d.pressure || 0;
		const target = d.validated && gNode ? [colX[1], yOf(india.indexOf(gNode), india.length)] : [colX[2], biasY];
		const strength = d.validated ? 3 : Math.max(0.6, Math.abs(d.gap_corr || d.co_corr || 0) * 5);
		edge(colX[0] + nodeW[0], y, target[0], target[1], strength, color(p), d.validated ? "" : "3 3");
		if (d.news_n && newsNode) edge(colX[0] + nodeW[0], y, colX[1], yOf(india.indexOf(newsNode), india.length), 0.8, cssv("--line2"), "1 3");
		const mv = d.move || {};
		const txt = mv.r30 != null ? `${pct(mv.r30)} 30m` : mv.prior_ret != null ? `${pct(mv.prior_ret)} prev` : "—";
		node(colX[0], y, nodeW[0], d.name.length > 16 ? d.name.slice(0, 15) + "…" : d.name, txt, color(p));
	});
	const tot = india.reduce((a, x) => a + x.w, 0) || 1;
	india.forEach((x, i) => {
		const y = yOf(i, india.length), share = x.c / tot;
		edge(colX[1] + nodeW[1], y, colX[2], biasY, Math.max(0.8, Math.abs(share) * 9), color(share));
		node(colX[1], y, nodeW[1], x.n, signed(share), color(share));
	});
	node(colX[2], biasY, nodeW[2], `${S.brainSym} ${v.bias || ""}`, `score ${fin(v.score) ? signed(v.score) : "—"}`, color(v.score || 0));
	edge(colX[2] + nodeW[2] / 2, biasY + 15, colX[2] + nodeW[2] / 2, decY - 15, 1.5, cssv("--line2"));
	const a = readAction(v.action), holding = (hb.positions || []).some((p) => p.symbol === S.brainSym);
	node(colX[2], decY, nodeW[2], "Decision", holding ? "holding" : a.kind === "none" ? "—" : a.label.toLowerCase().slice(0, 16), cssv("--acc-hi"));
}

// ==================================================================================================================
// FEED
// ==================================================================================================================
async function renderFeed(full) {
	seg($("#f-seg"), SUBS.feed, S.sub.feed, (v) => { S.sub.feed = v; history.replaceState(null, "", "#feed/" + v); renderFeed(true); }, "tab");
	if (S.sub.feed === "log") { if (full) await renderLog(true); return; }
	const body = $("#f-body");
	const rows = await loadNews(full ? 30000 : 60000);
	if (S.tab !== "feed" || S.sub.feed !== "news") return;
	body.textContent = "";
	const hb = (S.state && S.state.heartbeat) || {}, vs = Object.entries(hb.views || {});
	const tone = h("div", { class: "rows" });
	if (!vs.length) tone.appendChild(empty("news", "The desk's read of the news appears here while it runs."));
	for (const [u, v] of vs) {
		const n = v.news;
		tone.appendChild(h("div", { class: "pad", style: "display:grid;gap:8px" },
			h("div", { class: "row" }, h("b", { style: "font-weight:500" }, u), h("span", { class: "grow" }),
				n ? h("span", { class: "tag " + (n.tone > 0.1 ? "bull" : n.tone < -0.1 ? "bear" : "flat") }, `${n.tone > 0.1 ? "▲" : n.tone < -0.1 ? "▼" : "●"} Tone ${signed(n.tone)}`)
					: h("span", { class: "f3", style: "font-size:12px" }, "no relevant stories in 2 h")),
			n ? h("div", { class: "dv" }, h("i", { style: `${n.tone >= 0 ? "left:50%" : "right:50%"};width:${Math.min(Math.abs(n.tone), 1) * 50}%;background:${n.tone >= 0 ? "var(--up)" : "var(--dn)"}` })) : null,
			n ? h("div", { class: "f3", style: "font-size:12px" }, `${n.n} ${n.n === 1 ? "story" : "stories"} in the last 2 h · weighs in the bias as news evidence`) : null,
			n && n.breaking ? h("div", { class: "banner err", style: "margin:0" }, icon("bolt"),
				h("div", {}, h("b", { style: "font-weight:500" }, `Breaking, ${Math.round(n.breaking.age_min)} min ago: `), n.breaking.title, ". No new entries until it settles.")) : null));
	}
	const hl = hb.news_health || {}, names = Object.keys(hl), ok = names.filter((k) => String(hl[k]).startsWith("ok"));
	body.appendChild(grp("News tone", names.length ? `${ok.length} of ${names.length} feeds live` : "last 2 h", tone));
	const chips = h("div", { class: "chips pad" });
	const list = h("div", { class: "rows" });
	const paint = () => {
		chips.textContent = "";
		for (const [val, label] of [["", "All"], ["NIFTY", "NIFTY"], ["BANKNIFTY", "BANKNIFTY"], ["high", "High impact"], ["bull", "Bullish"], ["bear", "Bearish"]])
			chips.appendChild(h("button", { class: "chip", "aria-pressed": String(S.newsF === val), onclick: () => { S.newsF = val; paint(); } }, label));
		const f = S.newsF;
		const shown = rows.filter((r) => !f || (f === "high" ? r.impact === "high" : f === "bear" ? r.sentiment < -0.15 : f === "bull" ? r.sentiment > 0.15 : ((r.about || {})[f] || 0) >= 2));
		list.textContent = "";
		if (!shown.length) list.appendChild(empty("news", rows.length ? "Nothing matches this filter." : "No headlines yet. The desk reads 10 feeds every few minutes while it runs."));
		shown.slice(0, 120).forEach((r) => list.appendChild(newsRow(r)));
	};
	body.appendChild(grp("Headlines", rows.length ? `${rows.length}` : "", chips, list));
	paint();
}
// one headline: title first, then what the desk read in it (tone, impact, event, a surprise against expectations,
// speculation, a retelling) and, when they've arrived, the language models' reads for the index it's about
function newsRow(r, compact) {
	const k = r.sentiment > 0.15 ? "bull" : r.sentiment < -0.15 ? "bear" : "flat";
	const n = r.nlp || {}, readers = (n.llm && n.llm.readers) || {};
	const about = Object.entries(r.about || {}).filter(([t, x]) => t !== "macro" && x >= 2).sort((a, b) => b[1] - a[1]).map(([t]) => t);
	const sym = about[0] || "NIFTY", src = (r.sources || [r.source]).filter(Boolean), keep = compact ? 1 : 2;
	const retold = fin(n.novelty) && n.novelty < 0.5;
	const reads = Object.entries(readers).filter(([, rd]) => rd && fin(rd[sym]));
	return h("div", { class: "li" + (retold && !compact ? " muted" : "") },
		r.link ? h("a", { class: "ttl", href: r.link, target: "_blank", rel: "noopener noreferrer" }, r.title) : h("div", { class: "ttl" }, r.title),
		h("div", { class: "meta" },
			h("span", {}, `${src.slice(0, keep).join(", ")}${src.length > keep ? " +" + (src.length - keep) : ""} · ${ago(r.ts)}`),
			h("span", { class: "tag " + k }, `${k === "bull" ? "▲ Bullish" : k === "bear" ? "▼ Bearish" : "● Neutral"} ${signed(r.sentiment)}`),
			r.impact ? h("span", { class: "tag line" }, `Impact ${r.impact === "medium" ? "med" : r.impact}`) : null,
			n.event && n.event !== "general" ? h("span", { class: "tag line" }, cap(words(n.event))) : null,
			fin(n.surprise) && n.surprise !== 0 ? h("span", { class: "tag acc", title: "against expectations" }, n.surprise_text || `Surprise ${signed(n.surprise)}`) : null,
			fin(n.certainty) && n.certainty < 1 ? h("span", { class: "tag warn", title: "speculation, a preview or sources-say: half weight" }, "Unconfirmed") : null,
			retold ? h("span", { class: "tag dash", title: "mostly a retelling of an earlier story" }, "Retelling") : null,
			compact ? null : about.map((t) => h("span", { class: "tag line" }, t))),
		reads.length && !compact ? h("div", { class: "readers" }, h("span", {}, sym),
			h("span", {}, "Rules ", h("span", { class: cls(r.sentiment) }, signed(r.sentiment))),
			reads.map(([name, rd]) => h("span", {}, cap(name) + " ", h("span", { class: cls(rd[sym]) }, signed(rd[sym]))))) : null);
}
async function renderLog(reset) {
	const body = $("#f-body");
	if (reset) {
		S.thBefore = null;
		body.textContent = "";
		const chips = h("div", { class: "chips pad" });
		for (const [val, label] of [["", "All"], ...symbols().map((s) => [s, s]), ["trades", "Trades only"]])
			chips.appendChild(h("button", { class: "chip", "aria-pressed": String(S.thSym === val), onclick: () => { S.thSym = val; renderLog(true); } }, label));
		put(body, grp("Desk log", "every few minutes and on every trade", chips, h("div", { class: "rows", id: "f-log" })),
			h("button", { class: "btn block", id: "f-more", style: "margin-top:10px", onclick: () => renderLog(false) }, "Load earlier"));
	}
	let rows;
	const sym = S.thSym && S.thSym !== "trades" ? "&symbol=" + S.thSym : "";
	try { rows = await api(`/api/i/thoughts?n=40${sym}${S.thBefore ? "&before=" + S.thBefore : ""}`); } catch (e) { rows = []; }
	if (S.tab !== "feed" || S.sub.feed !== "log") return;
	const list = $("#f-log");
	if (!list) return;
	const shown = S.thSym === "trades" ? rows.filter((r) => /^(ENTER|EXIT)/.test(r.action || "")) : rows;
	if (reset && !rows.length) list.appendChild(empty("watch", "The desk's reasoning appears here, one entry every few minutes and on every trade."));
	let lastDay = list.dataset.day || "";
	for (const r of shown) {
		const day = String(r.ts).slice(0, 10);
		if (day !== lastDay) { list.appendChild(h("div", { class: "dayh", style: "background:var(--panel2)" }, h("span", {}, istDay(r.ts)), h("span", {}, ""))); lastDay = day; }
		list.appendChild(thoughtRow(r));
	}
	list.dataset.day = lastDay;
	if (rows.length) S.thBefore = rows[rows.length - 1].id;
	$("#f-more").hidden = rows.length < 40;
}
function thoughtRow(r) {
	const a = readAction(r.action), trade = a.kind === "enter" || a.kind === "exit";
	const more = h("div", { hidden: true, style: "margin:8px -16px 0" }, r.evidence ? evidenceList(r.evidence) : null);
	const row = h("button", { class: "th", "aria-expanded": "false", style: trade ? "background:var(--acc-bg)" : null, onclick: () => {
		more.hidden = !more.hidden;
		row.classList.toggle("open", !more.hidden);
		row.setAttribute("aria-expanded", String(!more.hidden));
	} },
	h("div", { class: "tm" }, ist(r.ts)),
	h("div", { style: "min-width:0" },
		h("div", { class: "row", style: "flex-wrap:wrap;gap:6px" }, h("b", { style: "font-weight:500" }, r.symbol), biasTag(r.bias, Number(r.score)),
			h("span", { class: "f3", style: "font-size:11.5px" }, `${words(r.day_type)} · conviction ${num(r.conviction)}`)),
		h("div", { class: "act" + (trade ? " trade" : "") }, a.label + (a.reason ? ": " + a.reason : "")),
		h("div", { class: "nar" }, r.narrative), more));
	return row;
}
// ==================================================================================================================
// settings
// ==================================================================================================================
function openSettings() {
	const mode = themeMode(), themeSeg = h("div", { class: "seg full" });
	seg(themeSeg, [["auto", "Auto"], ["dark", "Dark"], ["light", "Light"]], mode, (v) => applyTheme(v));
	const acct = S.accounts.length > 1 ? h("select", { class: "btn block", style: "margin-top:8px", "aria-label": "Account", onchange: (e) => {
		S.account = e.target.value; store("qd.account", S.account); S.charts = {}; S.news = null; closeSheet(); refresh(true); } },
		S.accounts.map((a) => h("option", Object.assign({ value: a.id }, a.id === S.account ? { selected: true } : {}), a.label))) : null;
	const standalone = matchMedia("(display-mode: standalone)").matches || navigator.standalone;
	const ios = /iphone|ipad|ipod/i.test(navigator.userAgent);
	openSheet("Settings",
		h("div", { class: "lbl", style: "margin-bottom:8px" }, "Appearance"), themeSeg,
		acct ? h("div", { class: "lbl", style: "margin:18px 0 0" }, "Account") : null, acct,
		h("div", { class: "lbl", style: "margin:18px 0 8px" }, "App"),
		h("div", { class: "panel rows" },
			standalone ? null : h("button", { class: "set", onclick: () => { closeSheet(); doInstall(); } }, icon("install"),
				h("div", { class: "grow" }, "Install on this phone", h("small", {}, ios ? "Share → Add to Home Screen" : "Full-screen, one tap away, works offline")), icon("chev")),
			h("button", { class: "set", onclick: () => { closeSheet(); S.charts = {}; S.news = null; refresh(true, true); } }, icon("refresh"),
				h("div", { class: "grow" }, "Refresh now", h("small", {}, window.QD_PUBLISHED ? "The desk republishes every ~6 min while it runs" : "Updates every 15 s by itself")), icon("chev")),
			h("button", { class: "set", onclick: () => openSheet("How to read this app", glossaryList()) }, icon("book"),
				h("div", { class: "grow" }, "How to read this app", h("small", {}, "Bias, conviction, premium, R, grades, levels…")), icon("chev"))),
		h("div", { class: "note" }, h("b", {}, `QuantDesk ${VERSION}. `),
			"An automated intraday options desk on NIFTY and BANKNIFTY, paper trading against live prices, option chains and news. Not investment advice."));
}

// ==================================================================================================================
// refresh loop, pull to refresh, boot
// ==================================================================================================================
let tick = 0, busy = false, queued = null;
async function refresh(full, force) {
	if (document.hidden) return;
	// one refresh at a time; a tab switch during a slow one runs right after it instead of being dropped
	if (busy) { queued = { full: !!(full || (queued && queued.full)), force: !!(force || (queued && queued.force)) }; return; }
	busy = true;
	try {
		if (force && window.QD_PUBLISHED && window.qdReload) await window.qdReload();
		await loadState();
		const t = S.tab;
		if (t === "desk") await renderDesk();
		else if (t === "chart") await renderChart();
		else if (t === "trades") await renderTrades(full);
		else if (t === "brain") renderBrain();
		else if (t === "feed") await renderFeed(full || tick % 4 === 0);
	} catch (e) {
		console.error(e);
	} finally {
		busy = false;
		if (queued) { const q = queued; queued = null; refresh(q.full, q.force); }
	}
}
function pullToRefresh() {
	const ptr = $("#ptr");
	let y0 = null, dy = 0;
	addEventListener("touchstart", (e) => {
		y0 = scrollY <= 0 && !e.target.closest(".chartbox,.sheet,.ticker,.scroll") ? e.touches[0].clientY : null;
		dy = 0;
	}, { passive: true });
	addEventListener("touchmove", (e) => {
		if (y0 == null) return;
		dy = Math.max(0, e.touches[0].clientY - y0);
		const p = Math.min(1, dy / 80);
		ptr.style.opacity = String(p);
		ptr.style.transform = `translateY(${-20 + p * 34}px) rotate(${p * 270}deg)`;
	}, { passive: true });
	addEventListener("touchend", async () => {
		if (y0 == null) return;
		y0 = null;
		if (dy > 80) {
			ptr.classList.add("spin");
			S.charts = {}; S.news = null;
			await refresh(true, true);
			ptr.classList.remove("spin");
		}
		ptr.style.opacity = "0";
		ptr.style.transform = "";
	});
}
async function boot() {
	applyTheme(themeMode());
	matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => applyTheme(themeMode()));
	S.sym = store("qd.sym") || S.sym;
	S.ckind = store("qd.ckind") || S.ckind;
	S.interval = store("qd.iv") || S.interval;
	buildTabs();
	document.addEventListener("click", (e) => { const g = e.target.closest("[data-go]"); if (g) go(g.dataset.go); });
	document.querySelectorAll("[data-info]").forEach((b) => b.addEventListener("click", () => showGloss(b.dataset.info)));
	$("#btn-settings").addEventListener("click", openSettings);
	$("#status").addEventListener("click", () => { S.charts = {}; S.news = null; refresh(true, true); toast("Refreshed"); });
	$("#c-fs").addEventListener("click", () => fullscreen(true));
	$("#c-fs-x").addEventListener("click", () => fullscreen(false));
	$("#sheet").addEventListener("click", (e) => { if (e.target.id === "sheet") closeSheet(); });
	document.addEventListener("keydown", (e) => { if (e.key === "Escape") { closeSheet(); fullscreen(false); } });
	addEventListener("hashchange", () => { const [t, s] = location.hash.slice(1).split("/"); show(t || "desk", s); });
	addEventListener("beforeinstallprompt", (e) => { e.preventDefault(); S.installEvt = e; if (S.tab === "desk") installCard(); });
	addEventListener("appinstalled", () => { store("qd.installed", "1"); document.querySelectorAll(".install").forEach((x) => x.remove()); });
	addEventListener("offline", () => { S.networkUnavailable = true; setStatus(S.state); if (S.tab === "desk") renderDesk(); });
	addEventListener("online", () => { S.networkUnavailable = false; window.QD_OFFLINE_CACHE = false; refresh(true, true); });
	try { S.accounts = await api("/api/i/accounts"); } catch (e) { S.accounts = []; }
	if (!S.accounts.length) S.accounts = [{ id: "live", label: "Live paper" }];
	const saved = store("qd.account");
	S.account = S.accounts.some((a) => a.id === saved) ? saved : S.accounts[0].id;
	const [t, s] = location.hash.slice(1).split("/");
	show(t || store("qd.tab") || "desk", s);
	pullToRefresh();
	// the chart draws text on a canvas: repaint once the app's own fonts have loaded
	if (document.fonts && document.fonts.ready) document.fonts.ready.then(() => restyleCharts());
	setInterval(() => { tick++; refresh(false); }, 15000);
	document.addEventListener("visibilitychange", () => { if (!document.hidden) refresh(true); });
	if ("serviceWorker" in navigator && window.isSecureContext && window.QD_PUBLISHED)
		navigator.serviceWorker.register("sw.js").catch(() => { /* offline support is a bonus */ });
}
boot().catch((e) => toast("Failed to start: " + e.message));
