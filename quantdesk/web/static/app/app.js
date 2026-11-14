/* QuantDesk: the phone app for the owner's market data.
 * Live: every price the Kite recorder and the Kotak poller watch, refreshed every 5 seconds, with charts and option chains per instrument.
 * Today: the pre-market brief. History: the record of the retired paper desk (it stopped on 6 Nov 2026), read-only.
 * Data: whether each feed and recording channel is delivering, and what is recorded where.
 * Works against the Worker (/live/*, /api/i/*) and, unchanged, as the read-only published site (a shim answers /api/i/* from
 * data.json; /live/* goes to the network). All server text goes in with textContent. */
"use strict";
const VERSION = "2.0";
const $ = (s, r) => (r || document).querySelector(s);
const NS = "http://www.w3.org/2000/svg";
const S = {
	account: "live", tab: "live", sub: { trades: "history" }, eq: null,
	accounts: [], installEvt: null,
};

// ---- icons (24px, stroked) -----------------------------------------------------------------------------------
const IC = {
	trades: "M8 20V5M4.5 8.5L8 5l3.5 3.5M16 4v15M12.5 15.5L16 19l3.5-3.5",
	live: "M3 12h3.2l2.3-6 4 12 2.5-6H21",
	build: "M4 19V9l5 4 5-8 6 6v8z",
	paper: "M7 3h8l4 4v14H7zM15 3v4h4M10.5 14l2 2 3.5-4.5",
	data: "M4 6c0-1.1 3.6-2 8-2s8 .9 8 2-3.6 2-8 2-8-.9-8-2zM4 6v6c0 1.1 3.6 2 8 2s8-.9 8-2V6M4 12v6c0 1.1 3.6 2 8 2s8-.9 8-2v-6",
	today: "M5.5 5h13A1.5 1.5 0 0 1 20 6.5V19a1.5 1.5 0 0 1-1.5 1.5h-13A1.5 1.5 0 0 1 4 19V6.5A1.5 1.5 0 0 1 5.5 5zM4 10h16M8.5 3v4M15.5 3v4",
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

// ---- glossary (the "?" buttons and Settings > How to read this app) -----------------------------------------------
const GLOSS = {
	r: ["R-multiple", "P&L divided by the risk planned at entry. +1R made what the trade risked; −1R lost exactly the planned amount. It makes trades of different sizes comparable."],
	grade: ["Trade grade", "A post-trade review of decision quality (entry, sizing, management, exit), A to F. A well-run loser can grade well; a lucky winner can grade badly."],
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
const TABS = [["live", "Markets"], ["paper", "Positions"], ["today", "Today"], ["trades", "History"], ["data", "Data"]];
const SUBS = { trades: [["history", "History"], ["performance", "Performance"], ["reviews", "Reviews"]] };
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
	if (!TABS.some((t) => t[0] === tab)) tab = "live";
	const changed = tab !== S.tab;
	S.tab = tab;
	if (changed && S.pp) S.pp.confirm = null;                                                     // leaving a tab cancels a half-made sell or kill
	if (sub && SUBS[tab] && SUBS[tab].some((s) => s[0] === sub)) S.sub[tab] = sub;
	store("qd.tab", tab);
	document.querySelectorAll("#tabs button").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.tab === tab)));
	document.querySelectorAll("main > section").forEach((s) => (s.hidden = s.dataset.view !== tab));
	$("#title").textContent = (TABS.find((t) => t[0] === tab) || ["", "Live"])[1];
	if (changed) scrollTo(0, 0);
	if ($("#sheet").classList.contains("open")) closeSheet();          // navigating (or Back) closes a sheet
	setStatus();
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
function closeSheet() { $("#sheet").classList.remove("open"); document.body.style.overflow = ""; S.tk = null; S.ft = null; }
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

// ---- the header pill: the live feeds' state, the same on every tab. It reads the relay's /live/health (a small answer) every 10 seconds. -------------
function liveStatus() {
	const L = S.lv, hl = L.health;
	if (/(^|\.)github\.io$/.test(location.hostname)) return { k: "off", t: "Public copy", s: "no live prices" };
	if (!navigator.onLine) return { k: "off net", t: "Offline", s: "" };
	if (!store("qd.livekey")) return { k: "off", t: "Live off", s: "add your key" };
	if (L.hstate === 503) return { k: "off", t: "Relay off", s: "not switched on" };
	if (L.hstate === 401) return { k: "off", t: "Key?", s: "not accepted" };
	if (!hl) return { k: "off", t: L.hstate === "err" ? "No answer" : "Connecting", s: "" };
	const src = [["Kite", hl.kite], ["Kotak", hl.kotak]].filter(([, x]) => x && fin(x.newest_age_s));
	if (!src.length) return inSession() ? { k: "stale", t: "No prices", s: "" } : { k: "off", t: "Closed", s: "opens " + nextOpen() };
	const newest = Math.min(...src.map(([, x]) => x.newest_age_s));
	const fresh = src.filter(([, x]) => x.newest_age_s <= LIVE_FRESH).map(([n]) => n).join(" + ");
	if (newest <= LIVE_FRESH) return { k: "live", t: "Live", s: fresh };
	if (inSession()) return newest <= LIVE_DELAYED ? { k: "stale", t: "Delayed", s: liveAge(newest) } : { k: "stale", t: "No feed", s: liveAge(newest) };
	return { k: "off", t: "Closed", s: "opens " + nextOpen() };
}
function setStatus() {
	const d = liveStatus(), p = $("#status");
	p.className = "pill " + d.k;
	$("#status-t").textContent = d.t;
	$("#status-s").textContent = d.s;
	return d;
}
let healthBusy = false;
async function pollHealth() {
	const L = S.lv, key = store("qd.livekey");
	if (healthBusy || document.hidden || /(^|\.)github\.io$/.test(location.hostname) || !key) return void setStatus();
	healthBusy = true;
	try {
		const r = await fetch("/live/health", { headers: { Authorization: "Bearer " + key }, cache: "no-store" });
		L.hstate = r.status;
		L.health = r.ok ? await r.json() : null;
	} catch (e) { L.hstate = "err"; L.health = null; }
	finally { healthBusy = false; }
	setStatus();
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
async function doInstall() {
	if (!S.installEvt) return toast("Use your browser's menu: “Install app” or “Add to Home Screen”.");
	S.installEvt.prompt();
	const r = await S.installEvt.userChoice.catch(() => null);
	S.installEvt = null;
	if (r && r.outcome === "accepted") { store("qd.installed", "1"); toast("Installed. Open QuantDesk from your home screen."); }
	document.querySelectorAll(".install").forEach((e) => e.remove());
}

// ---- the equity chart's theme (History > Performance) ---------------------------------------------------------------
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
function restyleCharts() {
	if (S.eq) { try { const t = lwTheme(); delete t.timeScale; S.eq.chart.applyOptions(t); S.eq.paint(); } catch (e) { /* gone */ } }
	if (S.lv && S.lv.chart) { liveChartDrop(); if (S.tab === "live") liveDraw(); }                  // the instrument chart is made again in the new colours
}
async function renderTrades(full) {
	seg($("#t-seg"), SUBS.trades, S.sub.trades, (v) => { S.sub.trades = v; history.replaceState(null, "", "#trades/" + v); renderTrades(true); }, "tab");
	const body = $("#t-body"), sub = S.sub.trades;
	if (!full) return;
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
// the account as it stands with no trades in the window: the starting capital, nothing made or lost
function flatAccount(capital) {
	const kpi = (l, v) => h("div", { class: "kpi" }, h("span", {}, l), h("b", {}, v));
	return h("div", { class: "panel" }, h("div", { class: "kpis" }, kpi("Account", inr(capital)), kpi("Net P&L", inr(0)), kpi("Return", "0.0%"), kpi("Trades", "0")));
}
async function renderHistory(body) {
	let rows;
	try { rows = await api("/api/i/trades?n=300"); } catch (e) { body.textContent = ""; body.appendChild(h("div", { class: "panel" }, empty("alert", e.message))); return; }
	if (S.tab !== "trades" || S.sub.trades !== "history") return;
	body.textContent = "";
	if (!rows.length) {
		let cap = null;
		try { cap = (await api("/api/i/stats")).capital; } catch (e) { /* the summary is skipped */ }
		if (S.tab !== "trades" || S.sub.trades !== "history") return;
		if (fin(cap)) body.appendChild(flatAccount(cap));
		body.appendChild(h("div", { class: "panel" }, empty("trades", "No trades yet. A trade the desk takes will appear here with its full reasoning.")));
		return;
	}
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
	if (!s.trades) {
		if (fin(s.capital)) body.appendChild(flatAccount(s.capital));
		body.appendChild(h("div", { class: "panel" }, empty("chart", "No closed trades yet. Performance appears after the first trade closes.")));
		return;
	}
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
// TODAY: the pre-market brief (quantdesk/premarket; premarket.yml every 15 minutes, 06:00-09:15 IST)
// ==================================================================================================================
async function loadBrief(maxAge) {
	if (S.pm && Date.now() - (S.pmAt || 0) < maxAge) return S.pm;
	try { S.pm = await api("/api/i/premarket"); S.pmErr = null; } catch (e) { S.pmErr = e.message; }
	S.pmAt = Date.now();
	return S.pm;
}
const PM_LABEL = { cheap: "bull", rich: "bear", "within chance": "flat", "no history": "flat", "no implied move": "flat", "already out": "flat" };
const pctU = (v, d = 1) => (fin(v) ? (v * 100).toFixed(d) + "%" : "—");
async function renderToday(full) {
	const body = $("#p-body");
	const b = await loadBrief(full ? 30000 : 120000);
	if (S.tab !== "today") return;
	body.textContent = "";
	if (!b) {
		put(body, grp("Pre-market brief", "", h("div", { class: "rows" }, empty("watch",
			"No pre-market brief yet. It is built every 15 minutes from 06:00 to 09:15 IST on weekdays" + (S.pmErr ? ` (${S.pmErr}).` : "."))))); return;
	}
	const sum = h("div", { class: "rows" }, (b.summary || []).map((line) => h("div", { class: "pad", style: "font-size:13.5px;line-height:1.5" }, line)));
	put(body, grp("Pre-market brief", `built ${ago(b.generated_at)}`, sum));
	if (b.data_stale) put(body, h("div", { class: "banner err" }, icon("alert"), h("div", {}, `The latest bhavcopy is from ${b.last_close}: the warehouse may be behind.`)));
	const notes = (t) => h("div", { class: "f3", style: "font-size:12px;line-height:1.5;margin-top:4px" }, t);
	if ((b.expiring || []).length)
		put(body, grp("Expiry today", b.expiring.map((e) => e.symbol).join(", "), h("div", { class: "rows" }, h("div", { class: "pad" }, notes(b.expiring[0].note)))));
	const cal = (b.calendar || []).filter((e) => e && e.impact !== "low" && e.source !== "brief");
	if (cal.length)                                                          // the scheduled-events calendar (paper/eventcal.py): the next week, IST
		put(body, grp("Coming up", "the next 7 days, IST", h("div", { class: "rows" }, cal.slice(0, 14).map((e) => h("div", { class: "pad row", style: "gap:8px;font-size:13px" },
			h("span", { class: "mono f3", style: "min-width:92px" }, `${e.at.slice(8, 10)}/${e.at.slice(5, 7)} ${e.at.slice(11, 16)}`), h("span", { class: "grow" }, e.name),
			h("span", { class: "tag " + (e.impact === "high" ? "bear" : "flat") }, e.impact + (e.source === "rule" ? " · by rule" : "")))),
			h("div", { class: "pad f3", style: "font-size:11.5px;line-height:1.5" }, "The desk sells no volatility into an event that touches an instrument: a day ahead of a high one, two hours ahead of a release. Dates marked \"by rule\" follow the release's usual rule (a holiday can move one): the owner's own calendar wins."))));
	if ((b.macro || []).length)
		put(body, grp("Macro events", `${b.macro.length}`, h("div", { class: "rows" }, b.macro.map((m) => h("div", { class: "pad", style: "display:grid;gap:4px" },
			h("div", { class: "row" }, h("b", { style: "font-weight:500" }, m.name), h("span", { class: "grow" }), h("span", { class: "tag flat" }, (m.time ? m.time + " IST · " : "") + m.when)),
			Object.entries(m.history || {}).map(([sym, x]) => notes(`${sym}: ${x.n} past sessions, median move ${pctU(x.median_move, 2)} (all sessions ${pctU(x.median_move_all, 2)}); moved more than 1% on ${pctU(x.share_over_1pct, 0)} (all ${pctU(x.share_over_1pct_all, 0)})`)),
			m.evidence ? notes(m.evidence) : null)))));
	if ((b.results || []).length) {
		const tb = h("table", { class: "tbl" }, h("thead", {}, h("tr", {}, ["Stock", "Priced", "Past (NSE)", "Label"].map((x) => h("th", {}, x)))),
			h("tbody", {}, b.results.map((r) => h("tr", {}, h("td", {}, h("b", { style: "font-weight:500" }, r.symbol), h("small", { class: "sub" }, r.when.startsWith("results today") ? "today" : "reacting")),
				h("td", {}, pctU(r.priced_abs_move)), h("td", {}, r.past && r.past.n ? `${pctU(r.past.mean_move)} · ${r.past.n}` : "—"),
				h("td", {}, h("span", { class: "tag " + (PM_LABEL[r.label] || "flat") }, r.label))))));
		const why = h("div", { class: "rows" }, b.results.map((r) => h("div", { class: "pad", style: "font-size:12.5px" }, h("b", { style: "font-weight:500" }, r.symbol + ": "), r.why)));
		put(body, grp("Results", `${b.results.length} companies`, h("div", { class: "scroll" }, tb), why, h("div", { class: "pad" }, notes(b.results_note))));
	}
	if ((b.global || []).length)
		put(body, grp("Overnight", "last daily close", h("div", { class: "chips pad" }, b.global.map((g) =>
			h("span", { class: "tag " + (g.change > 0 ? "bull" : g.change < 0 ? "bear" : "flat") }, `${g.name} ${pct(g.change, 1)}`)))));
	const W = b.watch || [];
	const chips = h("div", { class: "chips pad" }), list = h("div", { class: "rows" });
	const q = h("input", { type: "search", placeholder: `Search ${W.length} instruments`, "aria-label": "Search instruments", class: "search",
		style: "box-sizing:border-box;width:100%;max-width:100%;height:36px;padding:0 12px;border-radius:8px;border:1px solid var(--line);background:var(--bg);color:var(--fg)" });
	S.pmF = S.pmF || "";
	const paint = (all) => {
		chips.textContent = "";
		for (const [val, label] of [["", "All"], ["index", "Indices"], ["results", "Results"], ["news", "In the news"], ["oi", "OI shift"]])
			chips.appendChild(h("button", { class: "chip", "aria-pressed": String(S.pmF === val), onclick: () => { S.pmF = val; paint(); } }, label));
		const term = q.value.trim().toUpperCase(), f = S.pmF;
		const shown = W.filter((w) => (!term || w.symbol.includes(term)) && (!f || (f === "index" ? w.segment === "index"
			: f === "results" ? w.why.some((x) => x.includes("results")) : f === "news" ? w.why.some((x) => x.startsWith("in the news")) : w.why.some((x) => x.startsWith("futures OI")))));
		list.textContent = "";
		if (!shown.length) list.appendChild(empty("watch", "Nothing matches."));
		shown.slice(0, all || term ? 1000 : 60).forEach((w) => list.appendChild(h("div", { class: "pad", style: "display:grid;gap:3px" },
			h("div", { class: "row" }, h("b", { style: "font-weight:500" }, w.symbol), h("span", { class: "f3", style: "font-size:11.5px" }, w.segment === "index" ? "index" : `lot ${w.lot ?? "—"} · step ${w.strike_step ?? "—"}`),
				h("span", { class: "grow" }), h("span", { class: "f3 mono", style: "font-size:12px" }, w.price != null ? w.price.toLocaleString("en-IN") : "—"),
				h("span", { class: "tag flat" }, w.score.toFixed(1))),
			w.why.length ? h("div", { class: "f3", style: "font-size:12px" }, w.why.join(" · ")) : null)));
		if (!all && !term && shown.length > 60) list.appendChild(h("div", { class: "pad" }, h("button", { class: "btn block", onclick: () => paint(true) }, `Show all ${shown.length}`)));
	};
	q.addEventListener("input", () => paint());
	const rp = b.record_plan || {};
	put(body, grp("Watch-list", `${W.length} instruments · the desk's own ranking`, h("div", { class: "pad" }, q), chips, list,
		h("div", { class: "pad" }, notes(`Recording plan: ${rp.names || 0} of ${rp.of || 0} names fit Kite's budget of ${rp.budget || 0} instruments (advisory; the recorders do not read it yet). ${b.not_for}.`))));
	paint();
}
const DATA_RECORDED = [
	["Index and futures minutes, option-chain snapshots", "09:15 to 15:30", "record.yml, kept as Parquet on the chains-YYYY releases"],
	["Chain tape: several expiries a minute", "09:15 to 15:30", "record.yml, kept with the chains"],
	["Kite ticks with market depth", "the session", "kite-record.yml, encrypted with your API secret, kept as an artifact (licensed to you: never published)"],
	["Stock option chains, minutes for all five indices", "15:25 and 15:45", "collect-wide.yml"],
	["NSE warehouse: bhavcopy, participant open interest, FII/DII, events", "evenings", "data.yml"],
	["Pre-market brief", "06:00 to 09:15", "premarket.yml, on its own branch; shown on the Today tab"],
];
const DATA_GAPS = [
	"Live prices (Kite and Kotak) are for display. The relay keeps the latest price of each instrument and one close a minute for the last two days, so it is not a record. The record is the Kite tick recorder and the minute and chain files above.",
	"The recorders stop at about 15:32 IST. MCX and currency trade into the evening and are not recorded after that; there is no recorder for them yet.",
	"The Kite tick content is encrypted, so only its arrival can be checked, not its content.",
];
async function renderDataTab(full) {
	const body = $("#dt-body"), L = S.lv;
	if (full) await pollHealth();
	const pm = await loadBrief(full ? 30000 : 120000);
	if (S.tab !== "data") return;
	const hl = L.health, kk = (hl && hl.kite) || {}, kt = (hl && hl.kotak) || {}, kn = kt.universe || null;
	const tag = (k, t) => h("span", { class: "tag " + k }, t);
	const row = (label, value, note) => h("div", { class: "pad", style: "display:grid;gap:3px" },
		h("div", { class: "row" }, h("b", { style: "font-weight:500" }, label), h("span", { class: "grow" }), value),
		note ? h("div", { class: "f3", style: "font-size:12px;line-height:1.5" }, note) : null);
	const feed = (n, a) => !n ? tag("flat", "nothing yet") : tag(fin(a) && a <= LIVE_FRESH ? "bull" : fin(a) && a <= LIVE_DELAYED ? "flat" : "bear",
		`${n.toLocaleString("en-IN")} · ${liveAge(a)} ago`);
	body.textContent = "";
	const st = liveStatus();
	let live;
	if (!hl) live = [empty("live", st.t === "Public copy" ? "Live feeds are private and only open on the Cloudflare site, not on this address."
		: st.t === "Live off" ? "Type your live key on the Live tab to see the feeds here."
		: st.t === "Relay off" ? "The live relay is not switched on yet: the Worker still needs its two secrets (docs/LIVE.md)."
		: st.t === "Key?" ? "The relay did not accept the key. Type it again on the Live tab."
		: "Waiting for the live relay…")];
	else live = [
		row("Kite (the recorder pushes every 5 s)", feed(kk.n, kk.newest_age_s), "Zerodha ticks for the whole universe during the session."),
		row("Kotak (the relay polls it)", kt.configured === false ? tag("flat", "not set up") : h("span", {}, tag(kt.status === "ok" ? "bull" : "bear", kt.status || "unknown"), " ", feed(kt.n, kt.newest_age_s)),
			kt.configured === false ? "Add KOTAK_CONSUMER_KEY to the Worker to switch the second source on." :
				`${kt.calls_ok || 0} calls ok, ${kt.calls_failed || 0} failed since the relay started${kt.last_error ? " · last problem: " + kt.last_error : ""}`),
		row("Kotak universe", kn ? tag("flat", `${kn.quotes} quotes · ${kn.chains} chains`) : tag("bear", "none"), kn ? `built for ${kn.asof}` : "The universe workflow has not pushed one yet."),
		row("Both sources on the same name", tag(hl.disagree ? "bear" : "bull", hl.both ? `${hl.both} compared · ${hl.disagree || 0} differ` : "none compared"), "A name differs when Kite and Kotak disagree by more than a spread explains."),
		row("Board", tag("flat", `${(hl.names || 0).toLocaleString("en-IN")} instruments`)),
	];
	put(body, grp("Live feeds", st.t, h("div", { class: "rows" }, live)));
	const pmRows = !pm ? [empty("watch", "No pre-market brief yet. It is built every 15 minutes from 06:00 to 09:15 IST on weekdays.")]
		: [row("Pre-market brief", tag("flat", "built " + ago(pm.generated_at))), row("NSE warehouse", pm.data_stale ? tag("bear", "behind") : tag("bull", "up to date"), `latest bhavcopy: ${pm.last_close}`)];
	put(body, grp("Daily data", "", h("div", { class: "rows" }, pmRows)));
	put(body, grp("What is recorded", "every trading day", h("div", { class: "rows" }, DATA_RECORDED.map(([what, when, where]) =>
		h("div", { class: "pad", style: "display:grid;gap:3px" }, h("div", { class: "row" }, h("b", { style: "font-weight:500" }, what), h("span", { class: "grow" }), h("span", { class: "f3 mono", style: "font-size:12px;white-space:nowrap" }, when)),
			h("div", { class: "f3", style: "font-size:12px;line-height:1.5" }, where))))));
	put(body, grp("Not covered", "", h("div", { class: "rows" }, DATA_GAPS.map((t) => h("div", { class: "pad f3", style: "font-size:12.5px;line-height:1.55" }, t)))));
	put(body, h("div", { class: "note" }, "Whether each recording channel delivered on a given day is checked by the Data health workflow at 19:00 and 22:15 IST (docs/DATA_HEALTH.md); a red run there is the alarm."));
}

// ==================================================================================================================
// settings
// ==================================================================================================================
function openSettings() {
	const mode = themeMode(), themeSeg = h("div", { class: "seg full" });
	seg(themeSeg, [["auto", "Auto"], ["dark", "Dark"], ["light", "Light"]], mode, (v) => applyTheme(v));
	const acct = S.accounts.length > 1 ? h("select", { class: "btn block", style: "margin-top:8px", "aria-label": "Account", onchange: (e) => {
		S.account = e.target.value; store("qd.account", S.account); closeSheet(); refresh(true); } },
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
			h("button", { class: "set", onclick: () => { closeSheet(); refresh(true, true); } }, icon("refresh"),
				h("div", { class: "grow" }, "Refresh now", h("small", {}, "Prices update every 5 s by themselves; this reloads the rest")), icon("chev")),
			h("button", { class: "set", onclick: () => openSheet("How to read this app", glossaryList()) }, icon("book"),
				h("div", { class: "grow" }, "How to read this app", h("small", {}, "R, grades, paper trading…")), icon("chev"))),
		h("div", { class: "note" }, h("b", {}, `QuantDesk ${VERSION}. `),
			"Live Indian market prices and option chains, the pre-market brief, the record of the retired paper desk, and the state of the data pipeline. It only displays: nothing here can place an order. Not investment advice."));
}

// ==================================================================================================================
// ---- Markets: the desk's watchlist, refreshed every 5 seconds. PRIVATE: the prices are licensed to the owner, so the relay (deploy/cloudflare/live.js) answers only to a key
// typed once into this device. The watchlist is the config's (desk.watchlist, published as QD_TRADE.watch): the indices, the most traded F&O stocks, the main commodities and
// currencies. Everything else the recorders watch is still on the board and is found with the search box. One tap on a row opens that instrument's page.
const LIVE_FRESH = 15, LIVE_DELAYED = 120;                       // seconds: green up to 15, amber up to 2 minutes, then "no feed"
const WATCH_GROUPS = [["indices", "Indices"], ["stocks", "Stocks"], ["commodities", "Commodities"], ["currencies", "Currency"]];
const WATCH_DEF = {                                              // used only when the page was published without a config (QD_TRADE): the config's list is the one that counts
	indices: ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "NIFTYNXT50", "SENSEX", "BANKEX", "INDIAVIX"],
	stocks: ["RELIANCE", "HDFCBANK", "SBIN", "ICICIBANK", "TCS", "BHARTIARTL", "BSE", "INFY", "AXISBANK", "MARUTI", "DIXON", "PAYTM", "BAJAJ-AUTO", "KOTAKBANK", "BHEL", "LAURUSLABS", "DIVISLAB", "ITC", "BAJFINANCE", "M&M"],
	commodities: ["CRUDEOIL", "CRUDEOILM", "NATURALGAS", "NATGASMINI", "GOLD", "GOLDM", "SILVER", "SILVERM", "COPPER"],
	currencies: ["USDINR", "EURINR", "GBPINR", "JPYINR"],
};
const LIVE_FOUND = 60;                                           // rows a search shows
const LIVE_TF = [[1, "1m"], [5, "5m"], [15, "15m"]];
const LIVE_VOL = new Intl.NumberFormat("en-IN", { notation: "compact", maximumFractionDigits: 1 });
const SRC_NAME = { z: "Kite", k: "Kotak", u: "Upstox", d: "Dhan", a: "Angel One", f: "Fyers" };          // the feeds, by the relay's code (deploy/cloudflare/routes.js)
S.lv = { q: "", grp: "all", data: null, built: false, sel: null, view: "spot", series: null, cand: null, tf: 1, exp: null, allStrikes: false, last: {}, chart: null, at: 0, heavyAt: 0 };
S.open = {};                                                     // which folded sections are open, by id: a redraw keeps them as the reader left them
let liveBusy = false;
const livePx = (v, seg) => (fin(v) ? v.toLocaleString("en-IN", seg === "cds" || seg === "copt" || ((seg === "opt" || seg === "mopt") && Math.abs(v) < 1) ? { minimumFractionDigits: 4, maximumFractionDigits: 4 } : { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : "—");      // a currency price, or an option under a rupee, in four decimals
function liveAge(sec) {
	if (!fin(sec)) return "—";
	if (sec < 90) return Math.round(sec) + "s";
	if (sec < 5400) return Math.round(sec / 60) + " min";
	return (sec / 3600).toFixed(1) + " h";
}
function liveSeg(name, q) {
	if (q.s === "bfo") return "fut";
	if (q.s) return q.s;
	return /-FUT$/.test(name) ? "fut" : "idx";
}
function liveLabel(name, q) {
	if (q.s === "mcx") return name.replace(/-MCX$/, "") + " · MCX";
	if (q.s === "cds") return name.replace(/-CDS$/, "") + " · currency";
	if (q.s === "bfo") return name.replace(/-BFO$/, "") + " fut · BSE";
	return name.replace(/-FUT$/, " fut");
}
function liveKeyForm(note) {
	const inp = h("input", { type: "password", class: "search", placeholder: "Live key", "aria-label": "Live key", autocomplete: "off", id: "lv-key" });
	const save = () => { if (inp.value.trim()) { store("qd.livekey", inp.value.trim()); S.lv.built = false; $("#lv-body").dataset.state = ""; const pb = $("#pp-body"); if (pb) pb.dataset.state = ""; if (S.tab === "paper") renderPaper(true); renderLive(); pollHealth(); } };
	inp.addEventListener("keydown", (e) => { if (e.key === "Enter") save(); });
	return h("div", { class: "panel pad" }, h("div", { style: "font-weight:600;margin-bottom:6px" }, "Live prices"),
		h("div", { style: "font-size:13px;color:var(--fg2);line-height:1.55;margin-bottom:10px" },
			"Real-time prices from the desk's feeds, every 5 seconds. They are private to you: type your live key once on this device (it is the LIVE_READ_TOKEN you set on the Worker)."),
		note ? h("div", { class: "warn", style: "font-size:12.5px;margin-bottom:8px" }, note) : null, inp,
		h("button", { class: "btn primary block", style: "margin-top:10px", onclick: save }, "Save key"));
}
// The watchlist: {group: [name, ...]} from the published config; without one, the built-in list. Only plain symbols are taken.
function watchlist() {
	const w = typeof window !== "undefined" && window.QD_TRADE && window.QD_TRADE.watch, out = {};
	for (const [g] of WATCH_GROUPS) out[g] = w && typeof w === "object" ? (Array.isArray(w[g]) ? w[g].filter((n) => typeof n === "string" && /^[A-Z0-9&_.-]{1,32}$/.test(n)) : []) : WATCH_DEF[g];
	return out;
}
const pctTag = (chg) => (fin(chg) ? h("span", { class: "pct " + (chg > 0 ? "up" : chg < 0 ? "dn" : "flat") }, (chg > 0 ? "+" : chg < 0 ? "−" : "") + Math.abs(chg).toFixed(2) + "%") : h("span", { class: "pct flat" }, "—"));
// a section that folds: closed until the reader opens it, and it stays as they left it across redraws
function fold(id, title, hint, ...content) {
	const d = h("details", { class: "fold", open: S.open[id] ? true : null }, h("summary", {}, h("span", {}, title), hint ? h("span", { class: "hint" }, hint) : null), ...content);
	d.addEventListener("toggle", () => { S.open[id] = d.open; });
	return d;
}

// ---- one instrument: its page. Spot (the cash or index price), Futures and Options are views of one underlying, each with the live quote; Spot and Futures add a candlestick
// chart with volume, the order book and the day's figures, Options the whole chain. Drawn from the snapshot the tab already holds plus one small request for the open view;
// the views in this part only display.
const LIVE_MONTHS = "JAN FEB MAR APR MAY JUN JUL AUG SEP OCT NOV DEC".split(" ");
const LIVE_OPT = /^(.+?)(\d{2}(?:JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)\d{2})(\d+(?:\.\d+)?)(CE|PE)$/;
function liveOpt(name) {                                                   // NIFTY12NOV2624500CE -> {u: "NIFTY", e: "12NOV26", k: 24500, t: "CE"}
	const m = LIVE_OPT.exec(name);
	return m ? { u: m[1], e: m[2], k: parseFloat(m[3]), t: m[4] } : null;
}
const liveExpiryKey = (e) => +("20" + e.slice(5, 7)) * 10000 + (LIVE_MONTHS.indexOf(e.slice(2, 5)) + 1) * 100 + +e.slice(0, 2);          // sortable yyyymmdd
function liveChains(data) {                                                // underlying -> expiry -> strike -> {CE, PE} names, from the names on the board
	const out = Object.create(null);                                         // no prototype: a name like __proto__12NOV26... must be data, not a way into Object.prototype
	for (const n of Object.keys(data.quotes)) {
		const o = liveOpt(n);
		if (!o) continue;
		const ux = (out[o.u] = out[o.u] || Object.create(null));
		const ex = (ux[o.e] = ux[o.e] || Object.create(null));
		(ex[o.k] = ex[o.k] || Object.create(null))[o.t] = n;
	}
	return out;
}
const LIVE_SUFFIX = ["-FUT", "-MCX", "-CDS", "-BFO"];           // how the board names a near-month future: NSE, MCX, currency, BSE
// the underlying a board name belongs to: NIFTY12NOV2624500CE, NIFTY-FUT and NIFTY are all NIFTY; CRUDEOIL-MCX is CRUDEOIL
function liveUnder(name) {
	const o = liveOpt(name);
	if (o) return o.u;
	for (const x of LIVE_SUFFIX) if (name.endsWith(x) && name.length > x.length) return name.slice(0, -x.length);
	return name;
}
// the board names of one underlying: its cash or index price and its near-month future, whichever the board holds; `main` is the one a watchlist row shows
function liveNames(u, quotes) {
	const has = (n) => quotes[n] != null;
	const spot = has(u) ? u : null, fut = LIVE_SUFFIX.map((x) => u + x).find(has) || null;
	return { spot, fut, main: spot || fut };
}
// one-minute candles [minute, o, h, l, c, v] gathered into bars of `n` minutes (a bar starts on a multiple of n minutes of the IST clock: 09:15, 09:20, ...)
function liveAgg(rows, n) {
	if (!(n > 1)) return rows;
	const out = [];
	for (const r of rows) {
		const t = Math.floor((r[0] + 330) / n) * n - 330, b = out[out.length - 1];
		if (b && b[0] === t) { if (r[2] > b[2]) b[2] = r[2]; if (r[3] < b[3]) b[3] = r[3]; b[4] = r[4]; b[5] += r[5]; }
		else out.push([t, r[1], r[2], r[3], r[4], r[5]]);
	}
	return out;
}
function liveHHMM(minute) { const d = new Date(minute * 60000 + 19800000); return String(d.getUTCHours()).padStart(2, "0") + ":" + String(d.getUTCMinutes()).padStart(2, "0"); }
// the line of closes: what the chart falls back to when the relay holds no candles for the instrument (an option contract, or a relay not yet carrying candles)
function liveChart(ser, seg) {
	const W = 320, H = 130, box = h("div", { style: "padding:10px" });
	const day = ser && ser.day ? ser.day : [];
	if (day.length < 2) return put(box, h("div", { class: "f3", style: "font-size:12px;padding:30px 0;text-align:center" }, day.length ? "One price so far today." : "No chart for this instrument yet. It builds as the price moves."));
	const ys = day.map((p) => p[1]), x0 = day[0][0], x1 = day[day.length - 1][0], prev = ser.prev_close;
	let lo = Math.min(...ys), hi = Math.max(...ys);
	if (fin(prev)) { lo = Math.min(lo, prev); hi = Math.max(hi, prev); }
	const span = hi - lo || 1, X = (m) => 4 + ((m - x0) / (x1 - x0 || 1)) * (W - 8), Y = (v) => 13 + ((hi - v) / span) * (H - 40);
	const up = ys[ys.length - 1] >= (fin(prev) ? prev : ys[0]);
	const g = svg("svg", { viewBox: `0 0 ${W} ${H}`, class: "livechart", role: "img", "aria-label": "Today's prices, one a minute", style: "width:100%;height:auto;display:block" });
	if (fin(prev)) svg("line", { x1: 0, x2: W, y1: Y(prev), y2: Y(prev), stroke: cssv("--line2"), "stroke-width": 1, "stroke-dasharray": "3 3" }, g);
	let d = "";
	day.forEach((p, i) => (d += (i ? "L" : "M") + X(p[0]).toFixed(1) + " " + Y(p[1]).toFixed(1)));
	svg("path", { d, fill: "none", stroke: up ? cssv("--up") : cssv("--dn"), "stroke-width": 1.6, "stroke-linejoin": "round" }, g);
	for (const [t, x, y, a] of [[livePx(hi, seg), 2, 9, "start"], [livePx(lo, seg), 2, H - 15, "start"], [liveHHMM(x0), 2, H - 2, "start"], [liveHHMM(x1), W - 2, H - 2, "end"]]) {
		const el = svg("text", { x, y, "text-anchor": a, "font-size": 9, fill: cssv("--fg3") }, g); el.textContent = t;
	}
	return put(box, g);
}
function liveChartDrop() {
	const C = S.lv.chart;
	if (C) { try { C.chart.remove(); } catch (e) { /* already gone */ } S.lv.chart = null; }
}
// The candlestick chart of the open view, with volume under it. It is made once per instrument and then only fed, so a refresh never resets what the reader zoomed to.
function liveChartPaint(name, seg) {
	const L = S.lv, el = $("#lv-chart"), note = $("#lv-chart-note");
	if (!el) return;
	const got = L.cand && L.cand.name === name ? L.cand : null, cand = got ? got.candles : [], LW = window.LightweightCharts;
	if (!cand.length || !LW) {                                             // no candles: the line of closes
		liveChartDrop();
		el.textContent = "";
		put(el, liveChart(L.series && L.series.name === name ? L.series : null, seg));
		if (note) note.textContent = "";
		return;
	}
	if (!L.chart || L.chart.name !== name) {
		liveChartDrop();
		el.textContent = "";
		const cup = cssv("--cup"), cdn = cssv("--cdn"), fx = seg === "cds";
		const chart = LW.createChart(el, Object.assign(lwTheme(), { autoSize: true }));                     // each series formats its own scale: prices to the tick, volume in K and M
		const cs = chart.addSeries(LW.CandlestickSeries, { upColor: cup, downColor: cdn, borderVisible: false, wickUpColor: cup, wickDownColor: cdn, priceFormat: { type: "price", precision: fx ? 4 : 2, minMove: fx ? 0.0025 : 0.05 } });
		let vs = null;
		if (cand.some((r) => r[5] > 0)) {                                    // an index has no volume of its own: no empty pane under its chart
			vs = chart.addSeries(LW.HistogramSeries, { priceFormat: { type: "volume" }, priceLineVisible: false, lastValueVisible: false }, 1);
			try { chart.panes()[1].setHeight(84); } catch (e) { /* the library sizes it */ }
		}
		L.chart = { chart, cs, vs, name, tf: 0, line: null, prev: null };
	}
	const C = L.chart, rows = liveAgg(cand, L.tf), t = (m) => m * 60 + 19800;            // the chart's clock is UTC: shifted so the axis reads IST
	C.cs.setData(rows.map((r) => ({ time: t(r[0]), open: r[1], high: r[2], low: r[3], close: r[4] })));
	if (C.vs) C.vs.setData(rows.map((r) => ({ time: t(r[0]), value: r[5], color: (r[4] >= r[1] ? cssv("--cup") : cssv("--cdn")) + "66" })));
	if (fin(got.prev_close) && C.prev !== got.prev_close) {
		if (C.line) { try { C.cs.removePriceLine(C.line); } catch (e) { /* gone */ } }
		C.line = C.cs.createPriceLine({ price: got.prev_close, color: cssv("--fg3"), lineWidth: 1, lineStyle: 2, axisLabelVisible: false, title: "prev close" });
		C.prev = got.prev_close;
	}
	if (C.tf !== L.tf) { C.chart.timeScale().fitContent(); C.tf = L.tf; }
	if (note) note.textContent = got.exact ? "" : "Wicks show the range of the prices this feed reported, not of every deal.";
}
function liveField(label, value, cl) { return h("div", {}, h("span", {}, label), h("b", { class: "mono " + (cl || "") }, value)); }
// the views an underlying has on the board right now
function liveViews(u, n, chains) {
	const v = [];
	if (n.spot) v.push(["spot", "Spot"]);
	if (n.fut) v.push(["fut", "Futures"]);
	if (chains[u] && Object.keys(chains[u]).length) { v.push(["opt", "Options"]); if (QB.conf().inst[u]) v.push(["strat", "Strategy"]); }
	return v;
}
// the board name the open view charts: the cash or index price on Spot, the near future on Futures; the chain views chart nothing
function liveShown() {
	const L = S.lv;
	if (!L.sel || !L.data) return null;
	const n = liveNames(L.sel, L.data.quotes);
	return L.view === "fut" ? n.fut : L.view === "spot" ? n.spot || n.fut : null;
}
function liveHead(u, name, v) {
	const seg = liveSeg(name, v), src = SRC_NAME[v.src] || "";
	const kind = seg === "idx" ? "Index" : seg === "eq" ? "NSE cash" : seg === "mcx" ? "MCX near-month future" : seg === "cds" ? "Currency near-month future" : "Near-month future";
	return h("div", { class: "ihead" },
		h("div", { class: "grow" }, h("div", { class: "nm" }, u), h("div", { class: "sub" }, kind + " · " + liveAge(v.age_s) + " ago" + (src ? " · " + src : "") + (fin(v.x) ? " · ⚠ feeds differ " + v.x.toFixed(1) + "%" : ""))),
		h("div", { class: "pxb" }, h("div", { class: "px mono" }, livePx(v.ltp, seg)), pctTag(v.chg),
			ftContract(name) ? h("button", { class: "btn", style: "margin-top:6px;font-size:12px;padding:4px 10px", onclick: () => ftOpen(name) }, "Paper ticket") : null));
}
// Spot and Futures: the chart, the book, the day's figures
function liveQuoteView(u, name, v) {
	const L = S.lv, seg = liveSeg(name, v), got = L.cand && L.cand.name === name ? L.cand : null, cand = got ? got.candles : [];
	liveChartPaint(name, seg);
	const book = $("#lv-book"), stats = $("#lv-stats");
	book.textContent = "";
	put(book, liveDepth(name, v, seg, got ? got.depth : null));
	const prev = got && fin(got.prev_close) ? got.prev_close : L.series && L.series.name === name ? L.series.prev_close : null;
	const o = cand.length ? cand[0][1] : null, hi = cand.length ? Math.max(...cand.map((r) => r[2])) : null, lo = cand.length ? Math.min(...cand.map((r) => r[3])) : null;
	const inst = QB.conf().inst[u];
	stats.textContent = "";
	put(stats, h("div", { class: "facts" }, liveField("Open", livePx(o, seg)), liveField("Previous close", livePx(prev, seg)), liveField("High", livePx(hi, seg)), liveField("Low", livePx(lo, seg)),
		liveField("Volume", fin(v.vol) ? v.vol.toLocaleString("en-IN") : "—"), liveField("Open interest", fin(v.oi) ? v.oi.toLocaleString("en-IN") : "—"),
		inst ? liveField("Lot size", String(inst.lot)) : null, inst ? liveField("Strike step", inst.step != null ? String(inst.step) : "from the chain") : null),
		h("div", { class: "f3", style: "font-size:11.5px;line-height:1.5;padding:8px 16px 10px" }, "Open, high and low are of the minutes the relay holds for today, not the exchange's own figures."));
}
// Options: the whole chain of one expiry, live. A tap on a price opens the ticket for that contract (the ticket itself is further down, with the other paper tickets).
function liveChainView(u, data, chains, n) {
	const L = S.lv, box = $("#lv-chain"), exps = Object.keys(chains[u] || {}).sort((a, b) => liveExpiryKey(a) - liveExpiryKey(b));
	if (!exps.length) { box.textContent = ""; box.dataset.key = ""; return void put(box, empty("live", "No option chain for " + u + " on the board right now.")); }
	if (!exps.includes(L.exp)) L.exp = exps[0];
	const ch = chains[u][L.exp], strikes = Object.keys(ch).map(Number).sort((a, b) => a - b);
	const sq = data.quotes[n.spot] || data.quotes[n.fut] || {}, spot = sq.ltp, c = QB.conf(), T = QB.yearsTo(L.exp, Date.now());
	const rows = AN.chainRows(ch, data.quotes, spot, T, QB.rateOf(u, c)), a = AN.atm(rows, spot, T, sq.chg), pc = AN.pcr(rows), mp = AN.maxPain(rows);
	let atm = 0;
	if (fin(spot)) strikes.forEach((k, i) => { if (Math.abs(k - spot) < Math.abs(strikes[atm] - spot)) atm = i; });
	// 25 strikes around the money. The window stays where it is while the money is well inside it, and moves only when the price nears an edge: rows never slide under a finger
	// each time the price crosses a strike.
	const wk = u + "|" + L.exp + "|" + strikes.length, w = L.win && L.win.key === wk ? L.win : null;
	let from = w ? w.from : Math.max(0, atm - 12);
	if (!w || atm - from < 4 || from + 24 - atm < 4) from = Math.max(0, Math.min(atm - 12, strikes.length - 25));
	L.win = { key: wk, from };
	if (L.allStrikes) from = 0;
	const to = L.allStrikes ? strikes.length : Math.min(strikes.length, from + 25);
	const maxOi = Math.max(1, ...rows.flatMap((r) => [r.ce && r.ce.oi, r.pe && r.pe.oi]).filter(fin));
	const shown = rows.slice(from, to);
	// The table is laid out once for an expiry and a window of strikes, then only its numbers change: a tap never lands on a button a refresh has just replaced.
	const key = [u, L.exp, L.allStrikes, shown.map((r) => r.k).join(","), exps.join(",")].join("|");
	if (box.dataset.key !== key) {
		box.textContent = ""; box.dataset.key = key;
		const pxCell = (name) => name ? h("td", { class: "pxc", "data-n": name }, h("button", { "aria-label": "Ticket for " + name, onclick: () => tkOpen(name) }, h("b", { class: "mono" }, "—"), h("small", {}, ""))) : h("td", {}, "—");
		const trs = shown.map((r) => h("tr", { "data-k": String(r.k) },
			h("td", { class: "oi", "data-s": "ce" }, ""), h("td", { class: "x f2", "data-f": "cevol" }, ""), h("td", { class: "x f2", "data-f": "ceiv" }, ""), pxCell(ch[r.k].CE),
			h("td", { class: "k mono" }, r.k.toLocaleString("en-IN")),
			pxCell(ch[r.k].PE), h("td", { class: "x f2", "data-f": "peiv" }, ""), h("td", { class: "x f2", "data-f": "pevol" }, ""), h("td", { class: "oi", "data-s": "pe" }, "")));
		put(box,
			h("div", { class: "chips", style: "padding:10px 16px 8px" }, exps.map((e) => h("button", { class: "chip", "aria-pressed": String(e === L.exp), onclick: () => { L.exp = e; L.allStrikes = false; liveDraw(); } }, e.slice(0, 2) + " " + cap(e.slice(2, 5).toLowerCase())))),
			h("div", { class: "kstrip", id: "lv-cstats" }),
			h("div", { class: "panel scroll", style: "margin-top:0" }, h("table", { class: "tbl chain" },
				h("thead", {}, h("tr", { class: "x" }, h("th", { colspan: "4", class: "side" }, "Calls"), h("th", {}, ""), h("th", { colspan: "4", class: "side" }, "Puts")),
					h("tr", {}, ["OI", "Vol", "IV", "Call", "Strike", "Put", "IV", "Vol", "OI"].map((x, i) => h("th", { class: [1, 2, 6, 7].includes(i) ? "x" : "" }, x)))),
				h("tbody", { id: "lv-ctbody" }, trs))),
			strikes.length > to - from || L.allStrikes ? h("button", { class: "btn block", style: "margin:10px 16px;width:calc(100% - 32px)", onclick: () => { L.allStrikes = !L.allStrikes; liveDraw(); } }, L.allStrikes ? "Only near the money" : `Show all ${strikes.length} strikes`) : null,
			h("div", { class: "f3", style: "font-size:11.5px;line-height:1.5;padding:8px 16px 4px" }, "Tap a price for that contract's ticket. Shaded cells are in the money; the bars show where the open interest sits. IV is from the mid of the bid and the offer, or the last price where the feed gives no book."),
			h("div", { id: "lv-cextra" }));
		L.extraAt = 0;
	}
	// the numbers, in place
	const stat = (k, v2) => h("div", {}, h("span", {}, k), h("b", { class: "mono" }, v2));
	const cs = $("#lv-cstats");
	cs.textContent = "";
	put(cs, stat("Volatility at the money", a && a.iv != null ? (a.iv * 100).toFixed(1) + "%" : "—"), stat("Move priced to expiry", a && a.expiryMovePct != null ? "±" + a.expiryMovePct.toFixed(2) + "%" : "—"),
		stat("Puts per call (OI)", pc.oi != null ? pc.oi.toFixed(2) : "—"), stat("Max pain", mp != null ? num(mp, 0) : "—"));
	const byK = new Map(shown.map((r) => [String(r.k), r]));
	for (const tr of box.querySelectorAll("#lv-ctbody tr")) {
		const r = byK.get(tr.dataset.k);
		if (!r) continue;
		tr.className = fin(spot) && r.k === strikes[atm] ? "atm" : "";
		for (const td of tr.querySelectorAll("td.oi")) {
			const x = r[td.dataset.s], w = x && fin(x.oi) ? Math.round((x.oi / maxOi) * 100) : 0;
			td.textContent = x && fin(x.oi) ? LIVE_VOL.format(x.oi) : "—";
			td.style.background = `linear-gradient(to ${td.dataset.s === "ce" ? "left" : "right"},var(--${td.dataset.s === "ce" ? "dn" : "up"}-bg) ${w}%,transparent ${w}%)`;
		}
		for (const td of tr.querySelectorAll("td[data-f]")) {
			const x = r[td.dataset.f.slice(0, 2)], f = td.dataset.f.slice(2);
			td.textContent = !x ? "—" : f === "iv" ? (x.iv != null ? (x.iv * 100).toFixed(1) : "—") : fin(x.vol) ? LIVE_VOL.format(x.vol) : "—";
		}
		for (const td of tr.querySelectorAll("td.pxc")) {
			const name = td.dataset.n, q = data.quotes[name], call = name.endsWith("CE"), itm = fin(spot) && (call ? r.k < spot : r.k > spot);
			const was = L.last[name], fl = q && fin(was) && was !== q.ltp ? (q.ltp > was ? " flash-up" : " flash-dn") : "";
			if (q) L.last[name] = q.ltp;
			const cl = "pxc" + (itm ? " itm" : "") + (q && q.age_s > LIVE_DELAYED ? " f3" : "");
			if (fl) { td.className = cl; void td.offsetWidth; td.className = cl + fl; } else if (!/flash/.test(td.className) || td.className.replace(/ flash-\w+/, "") !== cl) td.className = cl;
			const bEl = td.querySelector("b"), sEl = td.querySelector("small");
			bEl.textContent = q ? livePx(q.ltp, "opt") : "—";
			sEl.className = "chg " + (q && q.chg > 0 ? "up" : q && q.chg < 0 ? "dn" : "flat");
			sEl.textContent = !q ? "" : fin(q.chg) ? (q.chg > 0 ? "+" : "") + q.chg.toFixed(1) + "%" : fin(q.bid) && fin(q.ask) ? livePx(q.bid, "opt") + " / " + livePx(q.ask, "opt") : "";
		}
	}
	bdSync(u);
	const ctx = { B: S.bd, data, chains, ch, exps, spot, T, sq, c, rows, inst: c.inst[u] || { lot: 1, step: 1 } };
	const safe = (what, fn) => { try { return fn(); } catch (e) { console.error(e); return h("div", { class: "note warn" }, `The ${what} could not be worked out from this snapshot.`); } };          // an extra that fails never takes the chain with it
	const flow = fin(spot) ? safe("flow", () => bdFlow(ctx)) : null;                             // read on every refresh, open or folded: the session's tape must not have holes
	if (Date.now() - (L.extraAt || 0) < 14000) return;                                          // the read, the flow and the news below change slowly: redrawn every 15 s, not under the reader every 5
	L.extraAt = Date.now();
	const ex = $("#lv-cextra");
	ex.textContent = "";
	put(ex,
		fin(spot) ? fold("read", "Market read", "what the chain implies", safe("market read", () => bdRead(ctx))) : null,
		flow ? fold("flow", "Flow and signals", "readings, each graded later", flow) : null,
		fold("news", "News", "headlines, joined to the board", safe("news panel", () => bdNews(S.bd, data))));
}
// the chain views and the builder work on the open underlying and share its expiry
function bdSync(u) {
	const B = S.bd;
	if (B.u !== u) { B.custom = []; B.tk = null; B.view = null; }
	B.u = u;
	if (S.lv.exp) B.exp = S.lv.exp;
}
function liveDetail() {
	const L = S.lv, data = L.data, u = L.sel, box = $("#lv-detail");
	const n = liveNames(u, data.quotes), chains = liveChains(data), views = liveViews(u, n, chains);
	const back = () => h("button", { class: "btn", onclick: () => liveOpen(null) }, "← Markets");
	if (!views.length) {
		liveChartDrop(); box.textContent = ""; box.dataset.key = "";
		return void put(box, h("div", { class: "ibar" }, back()), empty("live", u + " is not on the board right now (it may have expired or not ticked yet)."));
	}
	if (!views.some((x) => x[0] === L.view)) L.view = views[0][0];
	const key = u + "|" + L.view + "|" + views.map((x) => x[0]).join(",");
	if (box.dataset.key !== key) {                                           // another instrument or view: lay the page out once; refreshes then only fill it
		liveChartDrop(); box.textContent = ""; box.dataset.key = key;
		const tabs = h("div", { class: "seg", role: "tablist", "aria-label": u });
		seg(tabs, views, L.view, (x) => { L.view = x; L.cand = null; L.series = null; L.heavyAt = 0; liveDraw(); liveSeries(); }, "tab");
		const tf = h("div", { class: "seg", "aria-label": "Candle size" });
		seg(tf, LIVE_TF, L.tf, (x) => { L.tf = x; liveDraw(); });
		put(box, h("div", { class: "ibar" }, back(), views.length > 1 ? tabs : null), h("div", { id: "lv-head" }),
			L.view === "opt" ? h("div", { id: "lv-chain", class: "grp" }) : L.view === "strat" ? h("div", { id: "bd-body" })
				: h("div", { class: "cgrid" }, h("div", { class: "col" }, h("div", { class: "cpanel" }, h("div", { class: "tools", style: "padding-top:10px" }, tf, h("span", { id: "lv-chart-note", class: "f3", style: "font-size:11px" }, "")), h("div", { class: "chartbox", id: "lv-chart" }))),
					h("div", { class: "col" }, h("div", { id: "lv-book", class: "grp" }), h("div", { id: "lv-stats", class: "grp" }))));
	}
	const shown = L.view === "opt" || L.view === "strat" ? n.main : liveShown(), v = data.quotes[shown], head = $("#lv-head");
	head.textContent = "";
	if (v) put(head, liveHead(u, shown, v));
	if (L.view === "opt") return liveChainView(u, data, chains, n);
	if (L.view === "strat") {                                                // the builder is redrawn at most every 15 seconds, and never under the reader's fingers
		bdSync(u);
		if (!S.bd.editing && Date.now() - L.heavyAt > 14000) { L.heavyAt = Date.now(); bdDraw(); }
		return;
	}
	if (v) liveQuoteView(u, shown, v);
}
function liveOpen(name, view) {
	const L = S.lv, o = name ? liveOpt(name) : null;
	liveChartDrop();
	const box = $("#lv-detail");
	if (box) { box.textContent = ""; box.dataset.key = ""; }
	L.sel = name ? liveUnder(name) : null;
	if (name) L.view = view || (o ? "opt" : LIVE_SUFFIX.some((x) => name.endsWith(x)) ? "fut" : "spot");
	L.series = null; L.cand = null; L.allStrikes = false; L.heavyAt = 0;
	L.exp = o ? o.e : null;
	liveDraw();
	if (name) liveSeries();
	window.scrollTo(0, 0);
}
// The open view's candles and order book (one small request); where the relay holds no candles for it, the line of closes instead.
async function liveSeries() {
	const L = S.lv, name = liveShown(), key = store("qd.livekey");
	if (!name || !key) return;
	try {
		const r = await fetch("/live/candles?name=" + encodeURIComponent(name), { headers: { Authorization: "Bearer " + key }, cache: "no-store" });
		if (r.ok) { const j = await r.json(); if (j && j.name === liveShown() && Array.isArray(j.candles)) L.cand = j; }
	} catch (e) { /* the quote still shows */ }
	if (!(L.cand && L.cand.name === name && L.cand.candles.length)) {
		try {
			const r = await fetch("/live/series?name=" + encodeURIComponent(name), { headers: { Authorization: "Bearer " + key }, cache: "no-store" });
			if (r.ok && liveShown() === name) L.series = await r.json();
		} catch (e) { /* the quote still shows */ }
	}
	if (liveShown() === name) liveDraw();
}
function liveBuild() {
	const L = S.lv, body = $("#lv-body");
	body.textContent = "";
	const search = h("input", { type: "search", class: "search", placeholder: "Search every instrument on the board", "aria-label": "Search instruments", autocomplete: "off", value: L.q });
	search.addEventListener("input", () => { L.q = search.value; liveDraw(); });
	const grp = h("div", { class: "seg", id: "lv-grps", "aria-label": "Watchlist group" });
	put(body, h("div", { class: "mtop" }, h("span", { id: "lv-pill", class: "pill paused" }, h("span", { class: "dot" }), h("b", { id: "lv-pill-t" }, "")), h("span", { id: "lv-sources", class: "f3 grow", style: "font-size:11.5px" }, ""), h("span", { id: "lv-count", class: "f3", style: "font-size:11.5px" }, "")),
		h("div", { id: "lv-list" }, h("div", { class: "subnav" }, search, h("div", { style: "margin-top:8px" }, grp)), h("div", { id: "lv-table" })),
		h("div", { id: "lv-detail", hidden: true }),
		h("div", { class: "f3", style: "font-size:11.5px;line-height:1.55;padding:14px 0" },
			"Prices are the desk's licensed feeds and are shown only to you; under each name is how long ago the relay last heard that price. ",
			h("a", { href: "#", class: "acc", onclick: (e) => { e.preventDefault(); try { localStorage.removeItem("qd.livekey"); } catch (x) { /* ignore */ } L.built = false; L.health = null; L.hstate = null; body.dataset.state = ""; renderLive(); setStatus(); } }, "Forget this key")));
	L.built = true;
	body.dataset.state = "data";
}
// the order book of one instrument: five levels a side where the feed sends them, the best bid and offer where it sends only those
function liveDepth(name, v, seg, d) {
	const head = (hint) => h("div", { class: "sec-h" }, h("h2", {}, "Market depth"), h("span", { class: "hint" }, hint));
	if (d && (d.b.length || d.a.length)) {
		const max = Math.max(1, ...d.b.map((r) => r[1]), ...d.a.map((r) => r[1])), tb = d.b.reduce((s, r) => s + r[1], 0), ta = d.a.reduce((s, r) => s + r[1], 0);
		const lv = (r, bid) => {
			if (!r) return h("div", { class: "lv" });
			const w = Math.round((r[1] / max) * 100), cells = [h("span", { class: "f3" }, r[2] ? String(r[2]) : ""), h("span", {}, r[1].toLocaleString("en-IN")), h("b", { class: bid ? "up" : "dn" }, livePx(r[0], seg))];
			return h("div", { class: "lv", style: `background:linear-gradient(to ${bid ? "left" : "right"},var(--${bid ? "up" : "dn"}-bg) ${w}%,transparent ${w}%)` }, bid ? cells : cells.reverse());
		};
		const rows = Array.from({ length: Math.max(d.b.length, d.a.length) }, (_, i) => [lv(d.b[i], true), lv(d.a[i], false)]).flat();
		return h("div", { class: d.age_s > LIVE_DELAYED ? "stale" : "" }, head(`${SRC_NAME[d.src] || "feed"} · ${liveAge(d.age_s)} ago`),
			h("div", { class: "dom" }, h("div", { class: "lv hd" }, h("span", { title: "Orders at the price" }, "#"), h("span", {}, "Qty"), h("span", {}, "Bid")), h("div", { class: "lv hd" }, h("span", {}, "Offer"), h("span", {}, "Qty"), h("span", { title: "Orders at the price" }, "#")), rows,
				h("div", { class: "lv tot" }, h("span", {}, ""), h("span", {}, tb.toLocaleString("en-IN")), h("span", { class: "f3" }, "total")), h("div", { class: "lv tot" }, h("span", { class: "f3" }, "total"), h("span", {}, ta.toLocaleString("en-IN")), h("span", {}, ""))),
			tb + ta > 0 ? h("div", { class: "bm big", style: "margin:10px 16px 12px", role: "img", "aria-label": `Bids are ${Math.round((tb / (tb + ta)) * 100)}% of the size shown` }, h("i", { style: `left:0;width:${(tb / (tb + ta)) * 100}%;background:var(--up)` }), h("i", { style: `right:0;width:${(ta / (tb + ta)) * 100}%;background:var(--dn)` })) : null);
	}
	if (fin(v.bid) && fin(v.ask)) return h("div", {}, head("best bid and offer only"),
		h("div", { class: "dom" }, h("div", { class: "lv hd" }, h("span", {}, ""), h("span", {}, "Qty"), h("span", {}, "Bid")), h("div", { class: "lv hd" }, h("span", {}, "Offer"), h("span", {}, "Qty"), h("span", {}, "")),
			h("div", { class: "lv" }, h("span", {}, ""), h("span", {}, fin(v.bid_qty) ? v.bid_qty.toLocaleString("en-IN") : "—"), h("b", { class: "up" }, livePx(v.bid, seg))), h("div", { class: "lv" }, h("b", { class: "dn" }, livePx(v.ask, seg)), h("span", {}, fin(v.ask_qty) ? v.ask_qty.toLocaleString("en-IN") : "—"), h("span", {}, ""))));
	return h("div", {}, head(""), h("div", { class: "f3", style: "font-size:12.5px;line-height:1.5;padding:4px 16px 14px" }, seg === "idx" ? "An index is a number, not something that changes hands: its order book is on its future and its options." : "No order book from the feeds for this instrument yet."));
}
// one row of the watchlist: the name, what the price is, the price itself and the day's change; on a wide screen the book, the volume and the open interest too
function liveRow(u, data) {
	const L = S.lv, n = liveNames(u, data.quotes), v = n.main ? data.quotes[n.main] : null;
	if (!v) return h("div", { class: "wrow off" }, h("div", {}, h("div", { class: "nm" }, u), h("div", { class: "sub" }, "not on the board yet")), h("span", { class: "x" }, ""), h("span", { class: "x" }, ""), h("span", { class: "x" }, ""), h("div", { class: "px mono" }, "—"), pctTag(null));
	const seg = liveSeg(n.main, v), f = n.spot && n.fut ? data.quotes[n.fut] : null, book = fin(v.bid) ? v : f && fin(f.bid) ? f : null, bseg = book === f && f ? liveSeg(n.fut, f) : seg;
	const was = L.last[n.main], fl = fin(was) && was !== v.ltp ? (v.ltp > was ? " flash-up" : " flash-dn") : "";
	L.last[n.main] = v.ltp;
	const sub = (n.spot ? (f ? "fut " + livePx(f.ltp, liveSeg(n.fut, f)) : seg === "idx" ? "index" : "cash") : seg === "mcx" ? "MCX near month" : seg === "cds" ? "currency near month" : "near month") + " · " + liveAge(v.age_s);
	const vol = fin(v.vol) ? v.vol : f && fin(f.vol) ? f.vol : null, oi = fin(v.oi) ? v.oi : f && fin(f.oi) ? f.oi : null;
	return h("button", { class: "wrow" + (v.age_s > LIVE_DELAYED ? " off" : ""), onclick: () => liveOpen(n.main) },
		h("div", {}, h("div", { class: "nm" }, u), h("div", { class: "sub" }, sub)),
		h("span", { class: "x" }, book ? livePx(book.bid, bseg) + " / " + livePx(book.ask, bseg) : "—"), h("span", { class: "x" }, fin(vol) ? LIVE_VOL.format(vol) : "—"), h("span", { class: "x" }, fin(oi) ? LIVE_VOL.format(oi) : "—"),
		h("div", { class: "px mono" + fl }, livePx(v.ltp, seg)), pctTag(v.chg));
}
function liveDraw() {
	const L = S.lv, data = L.data;
	if (!data || !L.built) return;
	const newest = data.newest_age_s;
	const kind = !fin(newest) ? (inSession() ? "stale" : "paused") : newest <= LIVE_FRESH ? "live" : newest <= LIVE_DELAYED ? "stale" : "paused";
	const label = !fin(newest) ? (inSession() ? "No prices yet" : "Market closed, opens " + nextOpen()) : newest <= LIVE_FRESH ? "Live" : newest <= LIVE_DELAYED ? "Delayed " + liveAge(newest) : "No feed: last " + liveAge(newest) + " ago";
	const pill = $("#lv-pill"); pill.className = "pill " + kind; $("#lv-pill-t").textContent = label;
	const total = Object.keys(data.quotes).length;
	$("#lv-count").textContent = total.toLocaleString("en-IN") + " on the board";
	const hl = L.health, ln = $("#lv-sources");
	if (hl && ln) {                                                   // the state of each feed, from /live/health
		const feeds = hl.sources ? Object.entries(hl.sources).map(([c, x]) => [SRC_NAME[c] || c, x, c === "k" && hl.kotak && hl.kotak.status && hl.kotak.status !== "ok" ? hl.kotak.status : ""]) : [["Kite", hl.kite || {}, ""], ["Kotak", hl.kotak || {}, hl.kotak && hl.kotak.status && hl.kotak.status !== "ok" ? hl.kotak.status : ""]];
		ln.textContent = feeds.map(([nm, x, st]) => `${x.n > 0 && fin(x.newest_age_s) && x.newest_age_s <= LIVE_FRESH * 2 ? "●" : "○"} ${nm}${st ? " (" + st + ")" : ""}`).join("   ") + (hl.disagree ? `   ⚠ ${hl.disagree} differ` : "");
	}
	$("#lv-list").hidden = !!L.sel; $("#lv-detail").hidden = !L.sel;
	if (L.sel) return liveDetail();
	const tb = $("#lv-table"), q = L.q.trim().toLowerCase(), w = watchlist(), gs = $("#lv-grps");
	if (gs.dataset.g !== L.grp) { gs.dataset.g = L.grp; seg(gs, [["all", "All"], ...WATCH_GROUPS], L.grp, (g) => { L.grp = g; gs.dataset.g = g; liveDraw(); }); }
	tb.textContent = "";
	const heading = () => h("div", { class: "whead" }, h("span", {}, "Instrument"), h("span", { class: "x" }, "Bid / Offer"), h("span", { class: "x" }, "Volume"), h("span", { class: "x" }, "Open int."), h("span", {}, "Last"), h("span", {}, "Change"));
	if (q) {                                                          // a search looks at everything the board holds, not only the watchlist
		const found = Object.keys(data.quotes).filter((n) => n.toLowerCase().includes(q) || liveLabel(n, data.quotes[n]).toLowerCase().includes(q))
			.sort((a, b) => (liveOpt(a) ? 1 : 0) - (liveOpt(b) ? 1 : 0) || (a < b ? -1 : 1));
		if (!found.length) return void put(tb, empty("live", "Nothing on the board matches."));
		return void put(tb, h("div", { class: "grp" }, h("div", { class: "sec-h" }, h("h2", {}, "Search"), h("span", { class: "hint" }, found.length > LIVE_FOUND ? `first ${LIVE_FOUND} of ${found.length}` : `${found.length} found`)),
			found.slice(0, LIVE_FOUND).map((n) => { const v = data.quotes[n], sg = liveSeg(n, v); return h("button", { class: "wrow" + (v.age_s > LIVE_DELAYED ? " off" : ""), onclick: () => liveOpen(n) },
				h("div", {}, h("div", { class: "nm" }, liveLabel(n, v)), h("div", { class: "sub" }, liveAge(v.age_s) + " ago" + (SRC_NAME[v.src] ? " · " + SRC_NAME[v.src] : ""))), h("span", { class: "x" }, fin(v.bid) && fin(v.ask) ? livePx(v.bid, sg) + " / " + livePx(v.ask, sg) : "—"), h("span", { class: "x" }, fin(v.vol) ? LIVE_VOL.format(v.vol) : "—"), h("span", { class: "x" }, fin(v.oi) ? LIVE_VOL.format(v.oi) : "—"),
				h("div", { class: "px mono" }, livePx(v.ltp, sg)), pctTag(v.chg)); })));
	}
	const groups = WATCH_GROUPS.filter(([g]) => (L.grp === "all" || L.grp === g) && w[g].length);
	if (!groups.length) return void put(tb, empty("live", "The watchlist is empty: add names to desk.watchlist in the config."));
	for (const [g, title] of groups) {
		const up = w[g].filter((u) => { const n = liveNames(u, data.quotes).main; return n && data.quotes[n].chg > 0; }).length, dn = w[g].filter((u) => { const n = liveNames(u, data.quotes).main; return n && data.quotes[n].chg < 0; }).length;
		put(tb, h("div", { class: "grp wl" }, h("div", { class: "sec-h" }, h("h2", {}, title), h("span", { class: "hint" }, h("span", { class: "up" }, up + " up"), " · ", h("span", { class: "dn" }, dn + " down"))), heading(), w[g].map((u) => liveRow(u, data))));
	}
	if (!total) put(tb, h("div", { class: "note" }, "Nothing has arrived yet. The recorder pushes from 09:15 IST on a trading day."));
}
async function renderLive() {
	const body = $("#lv-body");
	if (S.tab !== "live" || document.hidden || liveBusy) return;
	if (/(^|\.)github\.io$/.test(location.hostname)) {                // the public Pages address: no key form at all, nothing is stored or sent from here
		if (body.dataset.state !== "pages") { body.textContent = ""; S.lv.built = false; put(body, empty("live", "Live prices are private and only open on the Cloudflare site, not on this address.")); body.dataset.state = "pages"; }
		return;
	}
	const key = store("qd.livekey");
	if (!key) { if (body.dataset.state !== "key") { body.textContent = ""; S.lv.built = false; put(body, liveKeyForm("")); body.dataset.state = "key"; } return; }
	liveBusy = true;
	let j = null, note = "";
	try {
		const r = await fetch("/live/snapshot", { headers: { Authorization: "Bearer " + key }, cache: "no-store" });
		if (r.status === 401) { try { localStorage.removeItem("qd.livekey"); } catch (e) { /* private mode */ } note = "That key was not accepted. Type it again."; }
		else if (r.status === 503) note = "The live feed is not switched on yet: the Worker still needs its two secrets (docs/LIVE.md).";
		else if (!r.ok || !/json/.test(r.headers.get("content-type") || "")) note = `The live relay did not answer as expected: HTTP ${r.status}, ${(r.headers.get("content-type") || "no content type").split(";")[0]}, from ${location.host}. If that address is not your Worker's own (…workers.dev), open the app from the Worker's address.`;          // the status, kind and host say where the request went: nothing secret
		else j = await r.json();
	} catch (e) { note = "No live prices: the request failed before any answer (" + String((e && e.name) || "error") + ") from " + location.host + ". Offline, or the address blocks it."; }
	finally { liveBusy = false; }
	if (S.tab !== "live") return;
	if (!j) { liveChartDrop(); body.textContent = ""; S.lv.built = false; body.dataset.state = "note"; setStatus(); return void put(body, liveKeyForm(note)); }
	const B = S.bd;
	S.lv.data = j; S.lv.at = Date.now();
	B.data = j; B.at = S.lv.at;                                              // the chain views and the tickets price from this same snapshot
	if (S.lv.sel && S.lv.view === "strat" && S.tab === "live") deskLoad().then((got) => { if (got && S.tab === "live" && S.lv.view === "strat" && !S.bd.editing) bdDraw(); });     // the desk's read, for the advisor
	if (S.lv.sel && (S.lv.view === "opt" || S.lv.view === "strat") && Date.now() - B.newsAt > 60000) { B.newsAt = Date.now(); newsLoad(key).then(() => { if (S.tab === "live" && S.lv.view === "opt") liveDraw(); }); }       // the digest changes every ten minutes: once a minute is plenty
	if (!S.lv.built) liveBuild();
	liveDraw();
	if (S.tk) tkDraw();                                                      // an open ticket follows the price
	if (S.ft) ftCalc();                                                      // so does a futures ticket (its inputs are never rebuilt under the user's fingers)
	if (S.lv.sel) liveSeries();                                              // the open view's candles and book, with every refresh
}

/* @@builder:start */
// ==================================================================================================================
// Strategy builder: pure maths, no DOM. Option strategies from the live board's quotes: legs, payoff at expiry and today, break-evens, Greeks, costs, and the desk's own limits
// (read from the config at publish time: window.QD_TRADE). DEFINED RISK ONLY: a structure with an uncovered short call is refused. Paper only: nothing here sends an order.
// ==================================================================================================================
const QB = (() => {
	const DEF = {
		equity: 500000, r: 0.065, currency: "INR",
		limits: { risk_per_trade: 0.025, max_premium_outlay: 0.20, max_total_outlay: 0.5, max_lots: 10, max_open: 2, max_spread_pct: 0.06, max_margin: 0.5, credit_margin_per_lot: 30000, daily_loss_limit: 0.05 },
		costs: { brokerage_per_order: 20, gst: 0.18, sebi_per_crore: 10, options: { stt_buy: 0, stt_sell: 0.0015, exchange: 0.0003503, stamp_buy: 0.00003 } },
		slippage: { option_half_spread_pct: 0.012, option_min_half_spread: 0.10, option_tick: 0.05 },
		paper: { risk_per_trade: 0.025, max_quote_age_s: 30, underlyings: ["AXISBANK", "BAJAJ-AUTO", "BAJFINANCE", "BANKNIFTY", "BHARTIARTL", "BHEL", "BSE", "COPPER", "CRUDEOIL", "CRUDEOILM", "DIVISLAB", "DIXON", "EURINR", "FINNIFTY", "GBPINR", "GOLD", "GOLDM", "HDFCBANK", "ICICIBANK", "INFY", "ITC", "JPYINR", "KOTAKBANK", "LAURUSLABS", "M&M", "MARUTI", "MIDCPNIFTY", "NATGASMINI", "NATURALGAS", "NIFTY", "PAYTM", "RELIANCE", "SBIN", "SILVER", "SILVERM", "TCS", "USDINR"], allow_short_legs: true },     // the paper desk's gate (quantdesk/paper/risk.py)
		inst: { NIFTY: { lot: 65, step: 50 }, BANKNIFTY: { lot: 30, step: 100 }, FINNIFTY: { lot: 60, step: 50 }, MIDCPNIFTY: { lot: 120, step: 25 }, SENSEX: { lot: 20, step: 100 } },
	};
	const conf = () => {
		const w = typeof window !== "undefined" && window.QD_TRADE;
		return w ? { ...DEF, ...w, fromConfig: true, paper: { ...DEF.paper, ...(w.paper || {}) }, limits: { ...DEF.limits, ...(w.limits || {}) }, costs: { ...DEF.costs, ...(w.costs || {}), options: { ...DEF.costs.options, ...((w.costs || {}).options || {}) } },
			slippage: { ...DEF.slippage, ...(w.slippage || {}) }, inst: { ...DEF.inst, ...(w.inst || {}) } } : { ...DEF, fromConfig: false };
	};
	// ---- Black-Scholes (European, cash-settled index options; r flat) ---------------------------------------------------------------
	const npdf = (x) => 0.3989422804014327 * Math.exp(-x * x / 2);
	function ncdf(x) {
		const t = 1 / (1 + 0.2316419 * Math.abs(x)), p = npdf(x) * t * (0.31938153 + t * (-0.356563782 + t * (1.781477937 + t * (-1.821255978 + t * 1.330274429))));
		return x > 0 ? 1 - p : p;
	}
	function bs(type, S, K, T, sig, r) {
		if (!(S > 0 && K > 0)) return NaN;
		if (!(T > 0) || !(sig > 0)) return Math.max(0, type === "CE" ? S - K : K - S);
		const sq = sig * Math.sqrt(T), d1 = (Math.log(S / K) + (r + sig * sig / 2) * T) / sq, d2 = d1 - sq, df = Math.exp(-r * T);
		return type === "CE" ? S * ncdf(d1) - K * df * ncdf(d2) : K * df * ncdf(-d2) - S * ncdf(-d1);
	}
	function greeks(type, S, K, T, sig, r) {
		if (!(S > 0 && K > 0 && T > 0 && sig > 0)) { const itm = type === "CE" ? S > K : S < K; return { delta: itm ? (type === "CE" ? 1 : -1) : 0, gamma: 0, theta: 0, vega: 0 }; }
		const sq = sig * Math.sqrt(T), d1 = (Math.log(S / K) + (r + sig * sig / 2) * T) / sq, d2 = d1 - sq, df = Math.exp(-r * T);
		const delta = type === "CE" ? ncdf(d1) : ncdf(d1) - 1, gamma = npdf(d1) / (S * sq), vega = S * npdf(d1) * Math.sqrt(T) / 100;
		const th = -(S * npdf(d1) * sig) / (2 * Math.sqrt(T)) - (type === "CE" ? 1 : -1) * r * K * df * ncdf(type === "CE" ? d2 : -d2);
		return { delta, gamma, theta: th / 365, vega };
	}
	function impliedVol(type, price, S, K, T, r) {
		if (!(price > 0 && S > 0 && K > 0 && T > 0)) return NaN;
		const lo0 = bs(type, S, K, T, 0.0001, r), hi0 = bs(type, S, K, T, 5, r);
		if (!(price >= lo0 - 1e-9 && price <= hi0)) return NaN;
		let lo = 0.0001, hi = 5;
		for (let i = 0; i < 80; i++) { const m = (lo + hi) / 2; if (bs(type, S, K, T, m, r) < price) lo = m; else hi = m; }
		return (lo + hi) / 2;
	}
	// ---- statutory costs: the same formulas as quantdesk/execution/costs.py CostModel.fees for options (a test compares them) -------------------------
	function fees(side, price, units, c, inst) {
		const turnover = units * price, o = (inst && inst.cost && c.costs[inst.cost]) || c.costs.options, brokerage = c.costs.brokerage_per_order, sebi = turnover * c.costs.sebi_per_crore / 1e7;      // MCX and currency options: their own schedule
		const stt = turnover * (side > 0 ? o.stt_buy : o.stt_sell), exchange = turnover * o.exchange, stamp = side > 0 ? turnover * o.stamp_buy : 0, gst = c.costs.gst * (brokerage + exchange + sebi);
		return brokerage + stt + exchange + sebi + stamp + gst;
	}
	function halfSpread(price, c, inst) {                                // the model's adverse slippage per unit (CostModel.slippage for options); an MCX or currency option in its own ticks
		const s = c.slippage, tick = inst && inst.tick > 0 ? inst.tick : s.option_tick, half = Math.max(s.option_half_spread_pct * price, inst && inst.tick > 0 ? 2 * inst.tick : s.option_min_half_spread);
		return Math.round(half / tick) * tick;
	}
	const rateOf = (u, c) => { c = c || conf(); const i = c.inst[u]; return i && typeof i.r === "number" ? i.r : c.r; };       // an option on a future (MCX, currency) is priced off the future: rate 0
	// ---- templates: [side, type, offset in strike steps from the at-the-money strike] -------------------------------------------------
	// Each template also says WHEN to use it, for the advisor (advise): its direction (up, down, range, big), its volatility stance (long: wants volatility to rise or a
	// move bigger than priced; short: is paid while little happens), its conviction (strong: a naked long option or a backspread; mild: a spread), and its AUTO v2 code
	// (the desk's shadow record for the structure). A leg's side may be 2: two lots of that leg (a butterfly's body).
	const TEMPLATES = {
		long_call: { name: "Long call", view: "Bullish: wants a big move up", wide: false, legs: () => [[1, "CE", 0]], dir: "up", vol: "long", conv: "strong", code: "LC" },
		long_put: { name: "Long put", view: "Bearish: wants a big move down", wide: false, legs: () => [[1, "PE", 0]], dir: "down", vol: "long", conv: "strong", code: "LP" },
		long_straddle: { name: "Long straddle", view: "Big move, either way", wide: false, legs: () => [[1, "CE", 0], [1, "PE", 0]], dir: "big", vol: "long", conv: "strong", code: "LS" },
		long_strangle: { name: "Long strangle", view: "Big move, either way, cheaper", wide: true, legs: (w) => [[1, "CE", w], [1, "PE", -w]], dir: "big", vol: "long", conv: "strong", code: "LG" },
		bull_call_spread: { name: "Bull call spread", view: "Moderately bullish, capped", wide: true, legs: (w) => [[1, "CE", 0], [-1, "CE", w]], dir: "up", vol: "neutral", conv: "mild", code: "BCS" },
		bear_put_spread: { name: "Bear put spread", view: "Moderately bearish, capped", wide: true, legs: (w) => [[1, "PE", 0], [-1, "PE", -w]], dir: "down", vol: "neutral", conv: "mild", code: "BRP" },
		bull_put_spread: { name: "Bull put spread", view: "Not bearish: collects premium", wide: true, legs: (w) => [[-1, "PE", 0], [1, "PE", -w]], dir: "up", vol: "short", conv: "mild", code: "BPS" },
		bear_call_spread: { name: "Bear call spread", view: "Not bullish: collects premium", wide: true, legs: (w) => [[-1, "CE", 0], [1, "CE", w]], dir: "down", vol: "short", conv: "mild", code: "BRC" },
		iron_condor: { name: "Iron condor", view: "Stays in a range: collects premium", wide: true, legs: (w) => [[-1, "CE", w], [1, "CE", 2 * w], [-1, "PE", -w], [1, "PE", -2 * w]], dir: "range", vol: "short", conv: "mild", code: "IC" },
		iron_butterfly: { name: "Iron butterfly", view: "Pins near the strike: collects premium", wide: true, legs: (w) => [[-1, "CE", 0], [-1, "PE", 0], [1, "CE", w], [1, "PE", -w]], dir: "range", vol: "short", conv: "strong", code: "IF" },
		call_butterfly: { name: "Call butterfly", view: "Pins near the strike: cheap, paid for", wide: true, legs: (w) => [[1, "CE", -w], [-2, "CE", 0], [1, "CE", w]], dir: "range", vol: "short", conv: "strong", code: "CBF" },
		put_butterfly: { name: "Put butterfly", view: "Pins near the strike: cheap, paid for", wide: true, legs: (w) => [[1, "PE", w], [-2, "PE", 0], [1, "PE", -w]], dir: "range", vol: "short", conv: "strong", code: "PBF" },
		bw_call_butterfly: { name: "Broken-wing call butterfly", view: "A drift up to a target, little lost below", wide: true, legs: (w) => [[1, "CE", 0], [-2, "CE", w], [1, "CE", 2 * w + 1]], dir: "up", vol: "short", conv: "mild", code: "BWC" },
		bw_put_butterfly: { name: "Broken-wing put butterfly", view: "A drift down to a target, little lost above", wide: true, legs: (w) => [[1, "PE", 0], [-2, "PE", -w], [1, "PE", -2 * w - 1]], dir: "down", vol: "short", conv: "mild", code: "BWP" },
		call_backspread: { name: "Call ratio backspread", view: "A big move up, partly paid for by a sold call", wide: true, legs: (w) => [[-1, "CE", 0], [2, "CE", w]], dir: "up", vol: "long", conv: "strong", code: "CRB" },
		put_backspread: { name: "Put ratio backspread", view: "A big move down, partly paid for by a sold put", wide: true, legs: (w) => [[-1, "PE", 0], [2, "PE", -w]], dir: "down", vol: "long", conv: "strong", code: "PRB" },
		// calendars and diagonals: a leg marked "x" is in the NEXT expiry (owner, 14 Nov 2026: "Build Calendar and diagonal spreads")
		call_calendar: { name: "Call calendar", view: "Sits near the strike into the near expiry; the later call keeps its value", wide: false, legs: () => [[-1, "CE", 0], [1, "CE", 0, "x"]], dir: "range", vol: "short", conv: "mild", code: "CAL", multi: true },
		put_calendar: { name: "Put calendar", view: "Sits near the strike into the near expiry; the later put keeps its value", wide: false, legs: () => [[-1, "PE", 0], [1, "PE", 0, "x"]], dir: "range", vol: "short", conv: "mild", code: "PCAL", multi: true },
		call_diagonal: { name: "Call diagonal", view: "A slow drift up to the sold strike", wide: true, legs: (w) => [[-1, "CE", w], [1, "CE", 0, "x"]], dir: "up", vol: "short", conv: "mild", code: "DGC", multi: true },
		put_diagonal: { name: "Put diagonal", view: "A slow drift down to the sold strike", wide: true, legs: (w) => [[-1, "PE", -w], [1, "PE", 0, "x"]], dir: "down", vol: "short", conv: "mild", code: "DGP", multi: true },
	};
	// ---- your own legs: any number (up to MAX_CUSTOM_LEGS, a bound on the arithmetic only), any strike on the board, buy or sell, call or put, each with a size multiple of the base lots ----------
	const CUSTOM = { name: "Custom structure", view: "Your own legs: any number, any strike, any ratio", wide: false };
	const MAX_CUSTOM_LEGS = 50, MAX_MULT = 100;
	function customLegs(rows, names) {
		if (!Array.isArray(rows) || !rows.length) return { error: "Add at least one leg." };
		if (rows.length > MAX_CUSTOM_LEGS) return { error: `A custom structure can have up to ${MAX_CUSTOM_LEGS} legs.` };
		const merged = new Map();
		for (const r of rows) {
			const side = r && r.side > 0 ? 1 : -1, type = r && r.type === "PE" ? "PE" : "CE", mult = r ? r.mult : NaN;
			if (!(Number.isInteger(mult) && mult >= 1 && mult <= MAX_MULT)) return { error: `Each leg's size must be a whole number from 1 to ${MAX_MULT}.` };
			const name = names && names[r.strike] ? names[r.strike][type] : null;
			if (!name) return { error: `${r.strike} ${type} is not on the board for this expiry: change its strike.` };
			const key = type + r.strike, prev = merged.get(key);
			if (prev && prev.side !== side) return { error: `${r.strike} ${type} is both bought and sold: net it into one leg.` };
			if (prev) { prev.mult += mult; if (prev.mult > MAX_MULT) return { error: `${r.strike} ${type} adds up to more than ${MAX_MULT} times the base size.` }; } else merged.set(key, { side, type, strike: r.strike, name, mult });
		}
		return { legs: [...merged.values()] };
	}
	// legs for a template: strikes = sorted strikes on the board for the expiry; names = {strike: {CE: name, PE: name}}. Returns {legs} or {error}.
	// `next` (calendars and diagonals): {strikes, names, T} of the next expiry, where a leg marked "x" goes
	function legsFor(id, strikes, spot, names, width, next) {
		const t = TEMPLATES[id];
		if (!t) return { error: "Unknown strategy." };
		if (!strikes.length || !(spot > 0)) return { error: "No strikes or no price on the board for this underlying yet." };
		if (t.multi && !(next && next.strikes && next.strikes.length && next.T > 0)) return { error: "A calendar or diagonal needs the next expiry's chain on the board too." };
		const atmOf = (ks) => ks.reduce((b, k, i) => (Math.abs(k - spot) < Math.abs(ks[b] - spot) ? i : b), 0);
		const atm = atmOf(strikes), atmN = next && next.strikes ? atmOf(next.strikes) : 0;
		const w = Math.max(1, Math.round(width || 1)), legs = [];
		for (const [side, type, off, x] of t.legs(w)) {
			if (x === "x") {
				const k = next.strikes[atmN + off], name = k != null && next.names[k] ? next.names[k][type] : null;
				if (k == null || !name) return { error: `The next expiry's ${type} at ${off >= 0 ? "+" : ""}${off} strikes is not on the board.` };
				legs.push({ side: Math.sign(side), type, strike: k, name, ...(Math.abs(side) > 1 ? { mult: Math.abs(side) } : {}), T: next.T });
				continue;
			}
			const k = strikes[atm + off];
			const name = k != null && names[k] ? names[k][type] : null;
			if (k == null || !name) return { error: `The ${type} at ${off >= 0 ? "+" : ""}${off} strikes is not on the board: pick a smaller width.` };
			legs.push(Math.abs(side) > 1 ? { side: Math.sign(side), type, strike: k, name, mult: Math.abs(side) } : { side, type, strike: k, name });
		}
		return { legs, atm: strikes[atm] };
	}
	// the price you would deal at: buy at the offer, sell at the bid. A quote is "book" only when BOTH sides are live and not crossed (0 < bid <= ask), like the paper gate;
	// a one-sided book is priced at the side you would hit but flagged "side"; no book at all is the last trade ("last"); a crossed book is a bad quote ("crossed", no price).
	// `age` is the quote's age in seconds from the relay (unknown if missing, which counts as stale).
	function entry(leg, q) {
		if (!q) return { px: NaN, src: "none", age: NaN };
		const age = Number.isFinite(q.age_s) ? q.age_s : NaN, bid = q.bid > 0 ? q.bid : 0, ask = q.ask > 0 ? q.ask : 0;
		if (bid > 0 && ask > 0 && ask < bid) return { px: NaN, src: "crossed", bid: q.bid, ask: q.ask, age };
		const px = leg.side > 0 ? ask : bid;
		if (bid > 0 && ask > 0) return { px, src: "book", bid: q.bid, ask: q.ask, age };
		if (px > 0) return { px, src: "side", bid: q.bid, ask: q.ask, age };
		return q.ltp > 0 ? { px: q.ltp, src: "last", bid: q.bid, ask: q.ask, age } : { px: NaN, src: "none", age };
	}
	const legPay = (l, S) => l.side * l.units * ((l.type === "CE" ? Math.max(0, S - l.strike) : Math.max(0, l.strike - S)) - l.px);
	// ---- the analysis ----------------------------------------------------------------------------------------------------------------
	// spec: {u, legs:[{side,type,strike,name}], quotes:{name:{ltp,bid,ask,oi}}, spot, T (years), lots, c (config, optional)}
	function analyze(spec) {
		const c = spec.c || conf(), inst = c.inst[spec.u] || { lot: 1, step: 1 }, lots = Math.max(1, Math.round(spec.lots || 1)), r = rateOf(spec.u, c);
		const lot = inst.lots && typeof inst.lots === "object" ? inst.lots[spec.exp] : inst.lot;          // a stock's lot belongs to the contract: NSE revises it from a given expiry
		const legs = spec.legs.map((l) => {
			const e = entry(l, spec.quotes[l.name]);
			const mid = e.src === "book" ? (e.bid + e.ask) / 2 : (spec.quotes[l.name] || {}).ltp;
			const T = Number.isFinite(l.T) && l.T > spec.T ? l.T : spec.T;                             // a calendar's later leg has its own time to run
			const iv = impliedVol(l.type, mid, spec.spot, l.strike, T, r);
			const spread = e.src === "book" ? (e.ask - e.bid) / ((e.ask + e.bid) / 2) : NaN;
			const mult = Number.isInteger(l.mult) && l.mult >= 1 ? l.mult : 1;
			return { ...l, T, mult, units: lots * lot * mult, lots: lots * mult, px: e.px, src: e.src, bid: e.bid, ask: e.ask, age: e.age + (spec.ageAdd || 0), iv, spread };
		});
		const out = { legs, lots, lot, errors: [], checks: [], paperChecks: [], ok: false, paperOk: false };
		if (!(Number.isInteger(lot) && lot > 0)) { out.errors.push(`${spec.u} has no verified lot size for the ${spec.exp || "chosen"} expiry, so this cannot be priced or sent.`); return out; }
		if (!(spec.T >= 0)) { out.errors.push("The expiry on the board could not be read, so the time to expiry is unknown."); return out; }
		const crossed = legs.filter((l) => l.src === "crossed");
		if (crossed.length) { out.errors.push(`Crossed bid/ask (bid above ask) on ${crossed.map((l) => l.strike + l.type).join(", ")}: a bad quote, not a price.`); return out; }
		if (legs.some((l) => !(l.px > 0))) { out.errors.push("A leg has no price on the board yet."); return out; }
		const callSlope = legs.filter((l) => l.type === "CE").reduce((a, l) => a + l.side * l.units, 0);
		out.definedRisk = callSlope >= 0;
		if (!out.definedRisk) { out.errors.push("This would leave a short call uncovered (unlimited loss). The builder only makes defined-risk structures."); return out; }
		out.premium = legs.reduce((a, l) => a + l.side * l.units * l.px, 0);                               // + debit paid, - credit received
		const ks = [...new Set(legs.map((l) => l.strike))].sort((a, b) => a - b), pts = [0, ...ks], far = (ks[ks.length - 1] || spec.spot) * 3;
		const later = (l) => l.T > spec.T + 1e-9;
		out.multi = legs.some(later);                                                                      // a calendar or diagonal: judged at the near expiry
		if (out.multi && legs.some((l) => later(l) && l.side < 0)) { out.errors.push("A calendar's sale must be in the near expiry, covered by the later purchase (a reverse calendar's cover expires first)."); return out; }
		// at the near expiry: the near legs at their value then; a later leg at its Black-Scholes value for the time it has left (the curve), or at the LEAST it can be
		// worth (the worst case, as the paper gate judges it: a call S(1 - 0.02 t) - K, a put K(1 - 0.10 t) - S)
		const floorOf = (l, S) => { const t = l.T - spec.T; return l.type === "CE" ? Math.max(0, S * (1 - 0.02 * t) - l.strike) : Math.max(0, l.strike * (1 - 0.10 * t) - S); };
		const valOf = (l, S) => { const t = l.T - spec.T; return isFinite(l.iv) ? bs(l.type, S, l.strike, t, l.iv, r) : floorOf(l, S); };
		const pay = out.multi ? (S) => legs.reduce((a, l) => a + (later(l) ? l.side * l.units * (valOf(l, S) - l.px) : legPay(l, S)), 0) : (S) => legs.reduce((a, l) => a + legPay(l, S), 0);
		const payW = out.multi ? (S) => legs.reduce((a, l) => a + (later(l) ? l.side * l.units * (floorOf(l, S) - l.px) : legPay(l, S)), 0) : pay;
		const wpts = out.multi ? [...pts, ...legs.filter(later).map((l) => (l.type === "CE" ? l.strike / (1 - 0.02 * (l.T - spec.T)) : l.strike * (1 - 0.10 * (l.T - spec.T)))), far] : [...pts, far];
		const vals = [...pts, far].map((S) => pay(S));
		const tailSlope = callSlope;                                                                       // beyond the highest strike the payoff slope is the net call position
		out.unlimitedProfit = tailSlope > 0;
		out.maxProfit = out.unlimitedProfit ? Infinity : out.multi ? Math.max(...Array.from({ length: 241 }, (_, i) => pay(spec.spot * (0.5 + i / 240)))) : Math.max(...vals);
		out.maxLoss = -Math.min(...wpts.map((S) => payW(S)));
		if (out.maxLoss < 0) { out.errors.push("This would be a guaranteed profit at every price, which is a bad quote rather than a trade. Check the prices on the board."); return out; }
		const be = [];
		const bp = out.multi ? Array.from({ length: 481 }, (_, i) => spec.spot * (0.5 + i / 480)) : [...pts, far];      // a calendar's curve needs a fine grid
		for (let i = 0; i + 1 < bp.length; i++) {
			const a = bp[i], b = bp[i + 1], fa = pay(a), fb = pay(b);
			if (fa === 0 && i === 0) be.push(a); else if ((fa < 0 && fb > 0) || (fa > 0 && fb < 0)) be.push(a + (b - a) * (0 - fa) / (fb - fa));
		}
		out.breakevens = be.filter((x) => x > 0).map((x) => Math.round(x * 100) / 100);
		const lo = spec.spot * 0.85, hi = spec.spot * 1.15, n = 121;
		out.grid = Array.from({ length: n }, (_, i) => lo + (hi - lo) * i / (n - 1));
		out.expiry = out.grid.map(pay);
		out.today = out.grid.map((S) => legs.reduce((a, l) => a + l.side * l.units * ((isFinite(l.iv) ? bs(l.type, S, l.strike, l.T, l.iv, r) : (l.type === "CE" ? Math.max(0, S - l.strike) : Math.max(0, l.strike - S))) - l.px), 0));
		out.greeks = legs.reduce((a, l) => { const g = greeks(l.type, spec.spot, l.strike, l.T, isFinite(l.iv) ? l.iv : 0.2, r); const m = l.side * l.units; return { delta: a.delta + m * g.delta, gamma: a.gamma + m * g.gamma, theta: a.theta + m * g.theta, vega: a.vega + m * g.vega }; }, { delta: 0, gamma: 0, theta: 0, vega: 0 });
		out.fees = legs.reduce((a, l) => a + fees(l.side, l.px, l.units, c, inst) + fees(-l.side, l.px, l.units, c, inst), 0);       // in and out at the entry price: the statutory part of a round trip
		out.exitSpread = legs.reduce((a, l) => a + l.units * (isFinite(l.spread) ? (l.spread * l.px) / 2 : halfSpread(l.px, c, inst)), 0);   // crossing the spread again on the way out
		out.entryFees = legs.reduce((a, l) => a + fees(l.side, l.px, l.units, c, inst), 0);                       // the entry leg only: the paper gate counts "the whole premium plus fees"
		out.cost = out.fees + out.exitSpread;
		out.margin = out.premium < 0 ? c.limits.credit_margin_per_lot * lots : 0;                         // a credit structure ties up margin (config estimate per lot); a debit one only the premium
		out.risk = out.maxLoss + out.entryFees;                                                            // worst loss plus the fees to get in, as the paper gate counts it
		out.riskPct = out.risk / c.equity;
		const L = c.limits, P = c.paper, chk = (id, ok, text) => out.checks.push({ id, ok, text }), pchk = (id, ok, text) => out.paperChecks.push({ id, ok, text });
		const inr0 = (x) => "₹" + Math.round(x).toLocaleString("en-IN");
		chk("risk", out.risk <= c.equity * L.risk_per_trade, `Worst loss ${inr0(out.maxLoss)} + entry fees ${inr0(out.entryFees)} is ${(out.riskPct * 100).toFixed(2)}% of ₹${c.equity.toLocaleString("en-IN")} (limit ${(L.risk_per_trade * 100).toFixed(1)}%)`);
		chk("outlay", out.premium <= c.equity * L.max_premium_outlay, `Premium paid ₹${Math.round(Math.max(out.premium, 0)).toLocaleString("en-IN")} (limit ${(L.max_premium_outlay * 100).toFixed(0)}% of equity)`);
		chk("lots", lots <= L.max_lots, `${lots} lot${lots === 1 ? "" : "s"} (limit ${L.max_lots})`);
		chk("margin", out.margin <= c.equity * L.max_margin, `Margin estimate ₹${Math.round(out.margin).toLocaleString("en-IN")} (limit ${(L.max_margin * 100).toFixed(0)}% of equity)`);
		const nm = (ls) => ls.map((l) => l.strike + l.type).join(", ");
		const wide = legs.filter((l) => isFinite(l.spread) && l.spread > L.max_spread_pct), nospread = legs.filter((l) => !isFinite(l.spread));
		chk("spread", wide.length === 0 && nospread.length === 0, wide.length ? `Wide bid/ask on ${nm(wide)} (limit ${(L.max_spread_pct * 100).toFixed(0)}% of the price)` : nospread.length ? `Spread cannot be measured on ${nm(nospread)}: no two-sided book` : "Bid/ask spreads are inside the limit");
		const nobook = legs.filter((l) => l.src !== "book");
		chk("book", nobook.length === 0, nobook.length ? `No two-sided bid/ask on ${nm(nobook)}: ${nobook.some((l) => l.src === "last") ? "priced at the last trade" : "priced at the one side that is quoted"}` : "Every leg has a two-sided bid/ask");
		const maxAge = P.max_quote_age_s, spotAge = spec.spotAge + (spec.ageAdd || 0);        // ages are as of the fetch; ageAdd is the time since (the board is redrawn without a new fetch)
		const old = legs.filter((l) => !(l.age <= maxAge)), spotOld = !(spotAge <= maxAge);
		chk("fresh", old.length === 0 && !spotOld, old.length || spotOld ? `Quotes not fresh enough (limit ${maxAge}s): ${[...(spotOld ? [spec.u + " price" + (isFinite(spotAge) ? " " + Math.round(spotAge) + "s" : " age unknown")] : []), ...old.map((l) => l.strike + l.type + (isFinite(l.age) ? " " + Math.round(l.age) + "s" : " age unknown"))].join(", ")}` : `Every quote is under ${maxAge}s old`);
		out.ok = out.checks.every((x) => x.ok);
		// ---- the paper desk's own gate, as far as it can be judged before the ticket (the ticket also checks the day's loss budget, the drawdown and the displayed size against the live account)
		const shorts = legs.filter((l) => l.side < 0);
		pchk("long", shorts.length === 0 || P.allow_short_legs === true, shorts.length ? (P.allow_short_legs === true ? `Sold legs (${nm(shorts)}): opened together with the bought legs as one package; the desk checks the worst case` : `Sold legs (${nm(shorts)}): selling is switched off on the paper desk (paper.allow_short_legs)`) : "Long options only");
		pchk("under", P.underlyings.includes(spec.u), P.underlyings.includes(spec.u) ? `${spec.u} trades on the paper desk` : `${spec.u} is not on the paper desk's list (${P.underlyings.join(", ")})`);
		pchk("prisk", out.risk <= c.equity * P.risk_per_trade, `Premium plus entry fees ${inr0(out.risk)} against ${(P.risk_per_trade * 100).toFixed(1)}% of ₹${c.equity.toLocaleString("en-IN")} (${inr0(c.equity * P.risk_per_trade)})`);
		pchk("pbook", nobook.length === 0, nobook.length ? `No two-sided bid/ask on ${nm(nobook)}` : "Two-sided books on every leg");
		pchk("pfresh", old.length === 0 && !spotOld, old.length || spotOld ? `Quotes older than ${maxAge}s (or of unknown age)` : `Quotes under ${maxAge}s old`);
		out.paperOk = out.paperChecks.every((x) => x.ok);
		return out;
	}
	// the largest number of lots (1..max_lots) that passes the risk, outlay and margin limits, from the one-lot analysis; 0 if even one lot does not
	function suggestLots(spec) {
		const c = spec.c || conf(), one = analyze({ ...spec, lots: 1 });
		if (one.errors.length) return 0;
		let best = 0;
		for (let n = 1; n <= c.limits.max_lots; n++) { const a = analyze({ ...spec, lots: n }); if (a.checks.filter((x) => ["risk", "outlay", "lots", "margin"].includes(x.id)).every((x) => x.ok)) best = n; else break; }
		return best;
	}
	// the days to expiry from a board expiry key like "12NOV26" (cash-settled at 15:30 IST on that day), as years
	function yearsTo(exp, nowMs) {
		const m = /^(\d{2})([A-Z]{3})(\d{2})$/.exec(exp), mi = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"].indexOf(m ? m[2] : "");
		if (!m || mi < 0) return NaN;
		const end = Date.UTC(2000 + +m[3], mi, +m[1], 10, 0);                                           // 15:30 IST = 10:00 UTC
		return Math.max(0, (end - nowMs) / 31556952000);
	}
	// what the structure would be worth under a what-if, against what it cost to open (theoretical value at each leg's own implied volatility shifted by `dvol` (absolute, 0.02 = two vol points), spot moved by
	// `move` (0.01 = +1%), and `days` closer to expiry; exit spread and fees are NOT included). At expiry this is the payoff, to the paisa.
	function scenario(a, spec, s) {
		const c = spec.c || conf(), r = rateOf(spec.u, c), S = spec.spot * (1 + s.move), T = Math.max(0, spec.T - s.days / 365);
		let v = 0;
		for (const l of a.legs) {
			const iv = Number.isFinite(l.iv) ? Math.max(0.01, l.iv + s.dvol) : NaN;
			const val = T > 0 && Number.isFinite(iv) ? bs(l.type, S, l.strike, T, iv, r) : (l.type === "CE" ? Math.max(0, S - l.strike) : Math.max(0, l.strike - S));
			v += l.side * l.units * (val - l.px);
		}
		return v;
	}
	// ---- the advisor: which structure, when, and why (owner, 13 Nov 2026: "The strategy builder must have access to the every strategy which it can reason it out when
	// to use which and create it's own if required") ----------------------------------------------------------------------------------------------------
	// ctx: {view: up|down|range|big|null (the desk's read, or yours), vol: rich|cheap|mid|null (implied against realized), event: bool (the event regime), eve: bool (expiry
	// tomorrow), pUp: number|null (the desk's P(up)), trendT: number|null (the Kalman trend's t), record: {code: {mu, se, n}} (AUTO v2's shadow record by structure),
	// extra: [{id, name, dir, vol, conv, code, rows}] (the desk's own inventions)}. Every structure is scored by the textbook's reasons, each one written down, and ranked.
	const ADV = { fit: 3, near: 1.5, against: -4, vol: 2, event: -5, eventLong: 1, eve: 1, conv: 1, trend: 1, recordK: 5, recordMax: 2, recordMinN: 8 };
	function advise(ctx) {
		ctx = ctx || {};
		const list = [...Object.entries(TEMPLATES).map(([id, t]) => ({ id, ...t })), ...((ctx.extra || []).map((x) => ({ ...x, invented: true })))];
		const out = [];
		for (const t of list) {
			let score = 0;
			const why = [], against = [];
			const add = (pts, text) => { score += pts; (pts >= 0 ? why : against).push(text); };
			const v = ctx.view;
			if (v) {
				if (t.dir === v) add(ADV.fit, `fits the view (${v === "big" ? "a big move either way" : v === "range" ? "stays in a range" : v})`);
				else if (v === "range" && t.vol === "short" && (t.dir === "up" || t.dir === "down")) add(ADV.near, "a credit spread also wins if the price stays put");
				else if ((v === "up" || v === "down") && t.dir === "big") add(ADV.near / 3, `a move either way includes ${v}`);
				else if ((v === "up" && t.dir === "down") || (v === "down" && t.dir === "up") || (v === "range" && t.dir === "big") || (v === "big" && t.dir === "range")) add(ADV.against, "against the view");
			}
			if (ctx.vol === "rich" && t.vol !== "neutral") add(t.vol === "short" ? ADV.vol : -ADV.vol, t.vol === "short" ? "options are dear against realized volatility: selling them is paid" : "options are dear: buying them pays up for the move");
			if (ctx.vol === "cheap" && t.vol !== "neutral") add(t.vol === "long" ? ADV.vol : -ADV.vol, t.vol === "long" ? "options are cheap against realized volatility: buying them is cheap" : "options are cheap: selling them is not paid enough");
			if (ctx.event && t.vol === "short") add(ADV.event, "an event is under way or priced: no volatility is sold into it (the desk's rule)");
			if (ctx.event && t.vol === "long") add(ADV.eventLong, "an event can move the price further than usual");
			if (ctx.eve && t.vol === "short" && t.dir === "range") add(ADV.eve, "expiry tomorrow: the premium decays fastest now");
			if (ctx.eve && t.vol === "long") add(-ADV.eve, "expiry tomorrow: a bought option loses its value fastest now");
			if (typeof ctx.pUp === "number" && (t.dir === "up" || t.dir === "down")) {
				const c = Math.abs(ctx.pUp - 0.5);
				if (c >= 0.2 && t.conv === "strong") add(ADV.conv, `strong conviction (P(up) ${ctx.pUp.toFixed(2)}): an uncapped structure`);
				if (c < 0.12 && t.conv === "mild") add(ADV.conv, `mild conviction (P(up) ${ctx.pUp.toFixed(2)}): a capped structure risks less`);
			}
			if (typeof ctx.trendT === "number" && Math.abs(ctx.trendT) >= 2 && (t.dir === "up" || t.dir === "down")) {
				const agree = (ctx.trendT > 0) === (t.dir === "up");
				add(agree ? ADV.trend : -ADV.trend, `the Kalman trend ${agree ? "agrees" : "disagrees"} (t ${ctx.trendT > 0 ? "+" : ""}${ctx.trendT.toFixed(1)})`);
			}
			const rec = ctx.record && t.code ? ctx.record[t.code] : null;
			if (rec && rec.n >= ADV.recordMinN && typeof rec.mu === "number") {
				const pts = Math.max(-ADV.recordMax, Math.min(ADV.recordMax, rec.mu * ADV.recordK));
				add(pts, `the desk's shadow record for ${t.invented ? "this invention" : "this structure"}: ${rec.mu >= 0 ? "+" : ""}${rec.mu.toFixed(2)}R a trade over ${rec.n} trades`);
			}
			out.push({ id: t.id, name: t.name, score: Math.round(score * 100) / 100, why, against, invented: !!t.invented, rows: t.rows || null, wide: !!t.wide });
		}
		return out.sort((a, b) => b.score - a.score);
	}
	// ---- the designer: a structure of its own for a view, when no written one fits well -----------------------------------------------------------------
	// It mutates the written structures that fit the view (move a strike, add a wing, drop, double or flip a leg), keeps what is DEFINED RISK (no net short call),
	// at most 4 legs and 6 lots, priced on the board, and ranks by what it pays IF THE VIEW IS RIGHT, per rupee it can lose, after costs. "Right" is a zone of prices at
	// expiry built from the market's own expected move (em, from the at-the-money volatility): up = S to S + 1.5 em, down the mirror, range = S +- 0.5 em, big = beyond 1 em
	// either side (to 2 em). The opposite zone is "wrong", and what the design does there is shown too. Seeded: the same board gives the same designs.
	const ZONES = { up: [[0, 1.5]], down: [[-1.5, 0]], range: [[-0.5, 0.5]], big: [[-2, -1], [1, 2]] };
	const OPPOSITE = { up: "down", down: "up", range: "big", big: "range" };
	function rng(seed) { let a = seed >>> 0; return () => { a = (a + 0x6D2B79F5) >>> 0; let t = Math.imul(a ^ (a >>> 15), 1 | a); t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296; }; }
	const gcd = (a, b) => (b ? gcd(b, a % b) : Math.abs(a));
	function canon(rows) {
		const m = new Map();
		for (const r of rows) { const k = r.type + ":" + r.off; m.set(k, (m.get(k) || 0) + r.side); }
		let g = 0;
		for (const q of m.values()) g = gcd(g, Math.abs(q));
		return g ? [...m.entries()].filter(([, q]) => q).map(([k, q]) => { const [type, off] = k.split(":"); return { side: q / g, type, off: +off }; }).sort((x, y) => (x.type + x.off).localeCompare(y.type + y.off)) : [];
	}
	function mutate(rows, rnd, span) {
		const r = rows.map((x) => ({ ...x })), pick = (n) => Math.floor(rnd() * n), op = ["shift", "shift", "wing", "drop", "double", "flip", "add"][pick(7)];
		if (op === "shift" && r.length) { const i = pick(r.length); r[i].off += rnd() < 0.5 ? -1 : 1; }
		else if (op === "wing") { const sold = r.filter((x) => x.side < 0); if (sold.length) { const x = sold[pick(sold.length)]; r.push({ side: 1, type: x.type, off: x.off + (x.type === "CE" ? 1 : -1) * (1 + pick(2)) }); } }
		else if (op === "drop" && r.length > 1) r.splice(pick(r.length), 1);
		else if (op === "double" && r.length) { const i = pick(r.length); r[i].side *= 2; }
		else if (op === "flip" && r.length) { const i = pick(r.length); r[i].side = -r[i].side; }
		else r.push({ side: rnd() < 0.5 ? 1 : -1, type: rnd() < 0.5 ? "CE" : "PE", off: pick(5) - 2 });
		return canon(r.filter((x) => Math.abs(x.off) <= span));                                         // off the board first, then the common size divided out
	}
	// the written structure a design turns out to be (its legs, at some width, are the design's), or null: a design of its own
	function knownAs(rows) {
		const key = JSON.stringify(canon(rows));
		for (const [id, t] of Object.entries(TEMPLATES)) if (!t.multi) for (const w of t.wide ? [1, 2, 3, 4, 5, 6] : [1]) {
			if (JSON.stringify(canon(t.legs(w).map(([side, type, off]) => ({ side, type, off })))) === key) return { id, width: w, name: t.name + (t.wide ? `, ${w} strike${w === 1 ? "" : "s"} wide` : "") };
		}
		return null;
	}
	const FIT_WELL = 3;                                                                                  // an advisor score under this: nothing fits the moment well
	function verdict(ranked) {
		const best = ranked && ranked[0];
		if (!best || best.score < FIT_WELL) return { stand_aside: true, text: "Nothing fits the moment well: the reasons for and against cancel out. Standing aside is a position too; or design one for a view of your own." };
		return { stand_aside: false, text: `${best.name} fits best now: ${best.why.slice(0, 2).join("; ")}.` };
	}
	function design(spec) {
		const { view, strikes, names, spot, em } = spec, zones = ZONES[view];
		if (!zones || !(em > 0) || !(spot > 0) || !strikes.length) return { error: "Pick a view, and wait for a price and a volatility on the board." };
		let atm = 0;
		strikes.forEach((k, i) => { if (Math.abs(k - spot) < Math.abs(strikes[atm] - spot)) atm = i; });
		const span = Math.min(6, Math.max(atm, strikes.length - 1 - atm)), rnd = rng(spec.seed || 7);
		const parents = [];
		for (const [, t] of Object.entries(TEMPLATES)) if (t.dir === view && !t.multi) for (const w of t.wide ? [1, 2, 3] : [1]) parents.push(canon(t.legs(w).map(([side, type, off]) => ({ side, type, off }))));
		if (!parents.length) return { error: "No structure to start from." };
		const grid = (zs) => { const pts = []; for (const [a, b] of zs) for (let i = 0; i <= 12; i++) pts.push(spot + em * (a + (b - a) * i / 12)); return pts; };
		const right = grid(zones), rightEach = zones.map((z) => grid([z])), wrong = grid(ZONES[OPPOSITE[view]]), seen = new Set(), found = [];
		const tries = spec.tries || 800;
		for (let n = 0; n < tries; n++) {
			let rows = parents[Math.floor(rnd() * parents.length)];
			for (let k = 0, m = 1 + Math.floor(rnd() * 3); k < m; k++) rows = mutate(rows, rnd, span);
			if (!rows.length || rows.length > 4 || rows.reduce((a, x) => a + Math.abs(x.side), 0) > 6 || !rows.some((x) => x.side > 0)) continue;
			if (rows.filter((x) => x.type === "CE").reduce((a, x) => a + x.side, 0) < 0) continue;              // a net short call: unlimited loss
			const key = JSON.stringify(rows);
			if (seen.has(key)) continue;
			seen.add(key);
			const legs = [];
			let ok = true;
			for (const x of rows) {
				const kk = strikes[atm + x.off], name = kk != null && names[kk] ? names[kk][x.type] : null;
				if (!name) { ok = false; break; }
				legs.push({ side: Math.sign(x.side), type: x.type, strike: kk, name, mult: Math.abs(x.side) });
			}
			if (!ok) continue;
			const a = analyze({ u: spec.u, exp: spec.exp, legs, quotes: spec.quotes, spot, spotAge: spec.spotAge, T: spec.T, lots: 1, c: spec.c });
			if (a.errors.length || !(a.maxLoss > 0) || (spec.budget && a.maxLoss > spec.budget)) continue;
			const pay = (S) => a.legs.reduce((acc, l) => acc + legPay(l, S), 0) - (a.cost || 0);
			const avg = (pts) => pts.reduce((acc, S) => acc + pay(S), 0) / pts.length;
			const avgRight = Math.min(...rightEach.map(avg)), avgWrong = avg(wrong);                  // "either way" must pay on BOTH sides: its worse side counts
			if (!(avgRight > 0)) continue;
			const shape = right.concat(wrong).map((S) => Math.round(pay(S) / a.maxLoss * 50)).join(",");
			if (found.some((f) => f.shape === shape)) continue;
			found.push({ shape, rows: legs.map((l) => ({ side: l.side, type: l.type, strike: l.strike, mult: l.mult })), known: knownAs(rows), score: avgRight / a.maxLoss, avgRight, avgWrong, maxLoss: a.maxLoss,
				maxProfit: a.unlimitedProfit ? Infinity : a.maxProfit, premium: a.premium, breakevens: a.breakevens,
				text: legs.map((l) => `${l.side > 0 ? "buy" : "sell"} ${l.mult} ${num0(l.strike)} ${l.type === "CE" ? "call" : "put"}${l.mult > 1 ? "s" : ""}`).join(", ") });
		}
		found.sort((x, y) => y.score - x.score);
		return { designs: found.slice(0, spec.top || 3).map(({ shape, ...rest }) => rest), tried: seen.size };
	}
	const num0 = (x) => (Math.round(x * 100) / 100).toString();
	// AUTO v2's read of one underlying (the paper runner's lab summary: state rows, families, inventions) as the advisor's context, with what it saw in words.
	// state row: [view, vol, iv/rv, eve, read P(up), read why, event, hmm, change point, trend t, tail, news P(up), news why]
	function deskContext(lab, u) {
		const v = lab && lab.state && Array.isArray(lab.state[u]) ? lab.state[u] : null;
		const record = {};
		for (const f of (lab && Array.isArray(lab.families) ? lab.families : [])) if (f && f.struct) record[f.struct] = { mu: f.mu_r, se: f.se, n: f.trades };
		const extra = (lab && Array.isArray(lab.inventions) ? lab.inventions : []).filter((x) => x && Array.isArray(x.legs) && x.legs.length).map((x) => ({
			id: "inv:" + x.code, name: x.name, dir: x.view === "flat" ? "range" : x.view, vol: "neutral", conv: "mild", code: x.code,
			rows: x.legs.map(([q, r, o]) => ({ side: Math.sign(q), type: r, off: o, mult: Math.abs(q) })) }));
		for (const x of (lab && Array.isArray(lab.inventions) ? lab.inventions : [])) if (x && x.code) record[x.code] = { mu: x.mu_r, n: x.trades };
		if (!v) return { ctx: { record, extra }, seen: [] };
		const event = !!v[6], view = v[0] === "up" ? "up" : v[0] === "down" ? "down" : v[0] === "flat" ? "range" : event ? "big" : null;
		const pUp = typeof v[4] === "number" ? v[4] : typeof v[11] === "number" ? v[11] : null;
		const seen = [view ? `view ${v[0] || "a big move (event)"}` : "no view", v[1] && v[1] !== "mid" ? `volatility ${v[1]}${typeof v[2] === "number" ? ` (${v[2].toFixed(2)}x realized)` : ""}` : "volatility fair",
			v[3] ? "expiry tomorrow" : null, event ? "event regime" : null, typeof pUp === "number" ? `P(up) ${pUp.toFixed(2)}` : null,
			typeof v[9] === "number" ? `Kalman trend t ${v[9] > 0 ? "+" : ""}${v[9].toFixed(1)}` : null, v[7] ? `HMM ${v[7]}` : null].filter(Boolean);
		return { ctx: { view, vol: v[1] === "rich" || v[1] === "cheap" ? v[1] : "mid", event, eve: !!v[3], pUp, trendT: typeof v[9] === "number" ? v[9] : null, record, extra }, seen };
	}
	return { conf, bs, greeks, impliedVol, fees, halfSpread, rateOf, TEMPLATES, CUSTOM, MAX_CUSTOM_LEGS, customLegs, legsFor, entry, analyze, scenario, suggestLots, yearsTo, ncdf, legPay, advise, verdict, design, knownAs, deskContext, ZONES, FIT_WELL };
})();
/* @@builder:end */

// ==================================================================================================================
// Market read: what the live option chain says about an index (implied volatility, the move the options price, skew, term structure, put/call balance, where the open interest sits, max pain),
// and ideas for a view ranked by what the structure risks and pays and the chance the MODEL gives it. Pure maths on the live board: no DOM, no network. NOT a forecast: every figure is
// what the market itself implies, or a count of what is open; the model chance uses the market's own volatility, so before costs every structure is a fair bet and the edge is your view.
// ==================================================================================================================
/* @@analyse:start */
const AN = (() => {
	const fnum = (x) => (typeof x === "number" && isFinite(x) ? x : null);
	const midOf = (q) => (q && q.bid > 0 && q.ask >= q.bid ? (q.bid + q.ask) / 2 : q && q.ltp > 0 ? q.ltp : null);
	const OPT = /^(.+?)(\d{2}(?:JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)\d{2})(\d+(?:\.\d+)?)(CE|PE)$/;
	// one expiry's chain as rows by strike: chain = {strike: {CE: name, PE: name}} (the board's names), quotes = the board
	function chainRows(chain, quotes, spot, T, r) {
		const out = [];
		for (const k of Object.keys(chain).map(Number).sort((a, b) => a - b)) {
			const row = { k };
			for (const t of ["CE", "PE"]) {
				const q = quotes[chain[k][t]];
				if (!q) continue;
				const px = midOf(q), iv = px != null && spot > 0 && T > 0 ? QB.impliedVol(t, px, spot, k, T, r) : NaN;
				row[t === "CE" ? "ce" : "pe"] = { px, iv: isFinite(iv) ? iv : null, oi: fnum(q.oi), vol: fnum(q.vol), age: fnum(q.age_s) };
			}
			out.push(row);
		}
		return out;
	}
	const nearest = (rows, spot) => rows.reduce((b, r, i) => (b < 0 || Math.abs(r.k - spot) < Math.abs(rows[b].k - spot) ? i : b), -1);
	const avg = (xs) => { const v = xs.filter((x) => x != null); return v.length ? v.reduce((a, b) => a + b, 0) / v.length : null; };
	// the at-the-money volatility and the move the straddle prices (to expiry, and one trading day), against the move so far today
	function atm(rows, spot, T, chgPct) {
		const i = nearest(rows, spot);
		if (i < 0) return null;
		const r = rows[i], iv = avg([r.ce && r.ce.iv, r.pe && r.pe.iv]);
		const straddle = r.ce && r.pe && r.ce.px != null && r.pe.px != null ? r.ce.px + r.pe.px : null;
		const dayMovePct = iv != null ? (iv / Math.sqrt(252)) * 100 : null;
		return { k: r.k, iv, straddle, expiryMovePct: straddle != null && spot > 0 ? (straddle / spot) * 100 : null, dayMovePct,
			todayPct: fnum(chgPct), todayVsImplied: dayMovePct && fnum(chgPct) != null ? Math.abs(chgPct) / dayMovePct : null };
	}
	// skew: the put wing's volatility minus the call wing's, `steps` strikes out; positive = puts dearer (the market pays more for downside)
	function skew(rows, spot, steps) {
		const i = nearest(rows, spot);
		if (i < 0 || i - steps < 0 || i + steps >= rows.length) return null;
		const p = rows[i - steps].pe && rows[i - steps].pe.iv, c = rows[i + steps].ce && rows[i + steps].ce.iv;
		return p != null && c != null ? { steps, putK: rows[i - steps].k, callK: rows[i + steps].k, putIv: p, callIv: c, points: (p - c) * 100 } : null;
	}
	function pcr(rows) {
		const sum = (side, f) => rows.reduce((a, r) => a + ((r[side] && r[side][f]) || 0), 0);
		const co = sum("ce", "oi"), po = sum("pe", "oi"), cv = sum("ce", "vol"), pv = sum("pe", "vol");
		return { oi: co > 0 ? po / co : null, vol: cv > 0 ? pv / cv : null, callOi: co, putOi: po };
	}
	// max pain: the strike where option BUYERS would collect least at expiry, from open interest (a count, not a prediction)
	function maxPain(rows) {
		let best = null;
		for (const c of rows) {
			let pay = 0;
			for (const r of rows) pay += ((r.ce && r.ce.oi) || 0) * Math.max(0, c.k - r.k) + ((r.pe && r.pe.oi) || 0) * Math.max(0, r.k - c.k);
			if (best == null || pay < best.pay) best = { k: c.k, pay };
		}
		return best && rows.some((r) => (r.ce && r.ce.oi) || (r.pe && r.pe.oi)) ? best.k : null;
	}
	// where the open interest sits: the biggest call open interest above the price and the biggest put open interest below it
	function walls(rows, spot, n) {
		const top = (side, keep) => rows.filter((r) => r[side] && r[side].oi > 0 && keep(r.k)).sort((a, b) => b[side].oi - a[side].oi).slice(0, n).map((r) => ({ k: r.k, oi: r[side].oi })).sort((a, b) => a.k - b.k);
		return { resistance: top("ce", (k) => k >= spot), support: top("pe", (k) => k <= spot) };
	}
	// term structure: the front expiry's at-the-money volatility against the next one's (front above next = the market is pricing something near)
	function term(frontRows, backRows, spot, Tf, Tb) {
		const f = atm(frontRows, spot, Tf, null), b = atm(backRows, spot, Tb, null);
		return f && b && f.iv != null && b.iv != null ? { front: f.iv, back: b.iv, points: (f.iv - b.iv) * 100 } : null;
	}
	// options trading unusually hard: today's volume against open interest, fresh quotes only; across everything on the board
	function unusual(quotes, n, maxAge) {
		const out = [];
		for (const [name, q] of Object.entries(quotes)) {
			const m = OPT.exec(name);
			if (!m || !(q.vol > 0) || !(q.oi > 0) || !(q.ltp > 0) || !(fnum(q.age_s) != null && q.age_s <= maxAge)) continue;
			out.push({ name, u: m[1], e: m[2], k: parseFloat(m[3]), t: m[4], ltp: q.ltp, chg: fnum(q.chg), vol: q.vol, oi: q.oi, ratio: q.vol / q.oi });
		}
		return out.filter((x) => x.ratio >= 0.5 && x.vol >= 1000).sort((a, b) => b.ratio * Math.log(b.vol) - a.ratio * Math.log(a.vol)).slice(0, n);
	}
	// the model chance that a structure ends in profit: the market's own lognormal (volatility = the at-the-money volatility, rate r), integrated over the payoff at expiry
	function pop(legs, spot, T, sig, r) {
		if (!(spot > 0 && T > 0 && sig > 0) || !legs.length) return null;
		const sd = sig * Math.sqrt(T), n = 800, lo = -5 * sd, hi = 5 * sd;
		let prob = 0, tot = 0;
		for (let i = 0; i < n; i++) {
			const z = lo + ((i + 0.5) / n) * (hi - lo), w = Math.exp(-z * z / (2 * sd * sd)), S = spot * Math.exp((r - sig * sig / 2) * T + z);
			const payoff = legs.reduce((a, l) => a + QB.legPay(l, S), 0);
			tot += w;
			if (payoff > 0) prob += w;
		}
		return tot > 0 ? prob / tot : null;
	}
	const VIEWS = {
		up: { name: "Up", ids: ["long_call", "bull_call_spread", "bull_put_spread", "bw_call_butterfly", "call_backspread", "call_diagonal"] },
		down: { name: "Down", ids: ["long_put", "bear_put_spread", "bear_call_spread", "bw_put_butterfly", "put_backspread", "put_diagonal"] },
		range: { name: "Stays in a range", ids: ["iron_condor", "iron_butterfly", "call_butterfly", "put_butterfly", "call_calendar", "put_calendar", "bull_put_spread", "bear_call_spread"] },
		big: { name: "Big move, either way", ids: ["long_straddle", "long_strangle", "call_backspread", "put_backspread"] },
	};
	// ideas for a view: every structure that fits it, at widths 1 to 4 strikes, each analysed on the live prices and ranked. analyzeFn(id, width) -> the builder's analysis (or {errors}).
	function ideas(view, analyzeFn, ctx) {
		const v = VIEWS[view];
		if (!v) return [];
		const out = [];
		for (const id of v.ids) {
			const wide = QB.TEMPLATES[id].wide;
			for (const width of wide ? [1, 2, 3, 4] : [1]) {
				const a = analyzeFn(id, width);
				if (!a || (a.errors && a.errors.length) || !isFinite(a.maxLoss) || !(a.maxLoss > 0)) continue;
				const rr = a.unlimitedProfit ? Infinity : a.maxProfit / a.maxLoss;
				out.push({ id, width, name: QB.TEMPLATES[id].name, premium: a.premium, maxLoss: a.maxLoss, maxProfit: a.unlimitedProfit ? Infinity : a.maxProfit, rr, breakevens: a.breakevens, paperOk: a.paperOk === true, fits: a.ok === true,
					pop: pop(a.legs, ctx.spot, ctx.T, ctx.sigma, ctx.r) });
			}
		}
		return out;
	}
	const SORTS = {
		rr: (a, b) => (b.rr === a.rr ? 0 : b.rr === Infinity ? 1 : a.rr === Infinity ? -1 : b.rr - a.rr),
		pop: (a, b) => (b.pop || 0) - (a.pop || 0),
		cheap: (a, b) => Math.abs(a.premium) - Math.abs(b.premium),
	};
	const rank = (list, by) => list.slice().sort(SORTS[by] || SORTS.rr);
	return { chainRows, atm, skew, pcr, maxPain, walls, term, unusual, pop, ideas, rank, VIEWS, midOf };
})();
/* @@analyse:end */

// ==================================================================================================================
// Flow and signals: what the futures, the options and the order books say beyond the level of the price, read every few seconds from the live board and kept as a tape for the session. The futures basis,
// the forward the options themselves imply (put-call parity), the pressure of resting bids against offers around the money, a dealer-gamma proxy, and how fast the straddle and volatility are moving.
// Every signal rule is written down below with its threshold; every firing is logged with the price at that moment and graded against what the price did next. A signal with fewer than MIN_N graded
// firings, or that does not beat a coin by a clear margin, is shown as UNPROVEN: nothing here is a forecast until its own record says so. Pure maths, no DOM, no network. Display only.
// ==================================================================================================================
/* @@flow:start */
const FL = (() => {
	const fnum = (x) => (typeof x === "number" && isFinite(x) ? x : null);
	const mid = (q) => (q && q.bid > 0 && q.ask >= q.bid ? (q.bid + q.ask) / 2 : q && q.ltp > 0 ? q.ltp : null);
	// the written-down rules and thresholds (changing one starts a new record: the log keys on the rule's name and version)
	const RULES = {
		pressure_v1: { dir: true, text: "Resting bids beat offers in calls and offers beat bids in puts (or the reverse) around the money by 0.25 or more", th: 0.25 },
		straddle_v1: { dir: false, text: "The at-the-money straddle gained 5% or more in 10 minutes while the price moved less than 0.1%: a bigger move is being priced", th: 5 },
		parity_v1: { dir: true, text: "The forward implied by put-call parity sits 0.05% or more away from the futures price", th: 0.05 },
		gamma_v1: { dir: true, text: "Dealer gamma proxy is negative and the price has fallen under (or risen over) the flip level", th: 0 },
	};
	const HORIZON_S = 900, MIN_N = 30, MIN_MOVE_PCT = 0.05, VOL_MOVE_PCT = 0.15, REFIRE_S = 900, MAX_LOG = 400, MAX_HIST = 360;
	const median = (xs) => { const v = xs.filter((x) => x != null).sort((a, b) => a - b); return v.length ? (v.length % 2 ? v[(v.length - 1) / 2] : (v[v.length / 2 - 1] + v[v.length / 2]) / 2) : null; };
	// resting-size pressure around the money: for calls and puts, (bid size - offer size) / (bid size + offer size) over `n` strikes either side, fresh quotes only. Bullish = calls bid-heavy and puts offer-heavy.
	function pressure(chain, quotes, spot, n, maxAge) {
		const ks = Object.keys(chain).map(Number).sort((a, b) => a - b);
		if (!ks.length || !(spot > 0)) return null;
		let at = 0;
		ks.forEach((k, i) => { if (Math.abs(k - spot) < Math.abs(ks[at] - spot)) at = i; });
		const side = (t) => {
			let b = 0, a = 0, used = 0;
			for (const k of ks.slice(Math.max(0, at - n), at + n + 1)) {
				const q = quotes[chain[k][t]];
				if (!q || !(fnum(q.age_s) != null && q.age_s <= maxAge) || fnum(q.bid_qty) == null || fnum(q.ask_qty) == null || !(q.bid > 0) || !(q.ask >= q.bid)) continue;
				b += q.bid_qty; a += q.ask_qty; used++;
			}
			return a + b > 0 ? { imb: (b - a) / (b + a), used } : null;
		};
		const ce = side("CE"), pe = side("PE");
		return ce && pe ? { ce: ce.imb, pe: pe.imb, score: ce.imb - pe.imb, used: ce.used + pe.used } : null;
	}
	// the forward the options imply: K + (C - P) e^{rT} at the strikes nearest the money (median), against the futures price
	function parity(rows, spot, T, r, fut) {
		if (!(spot > 0 && T > 0)) return null;
		const near = [...rows].sort((a, b) => Math.abs(a.k - spot) - Math.abs(b.k - spot)).slice(0, 5).filter((x) => x.ce && x.pe && x.ce.px != null && x.pe.px != null);
		const f = median(near.map((x) => x.k + (x.ce.px - x.pe.px) * Math.exp(r * T)));
		return f == null ? null : { fwd: f, gapPts: fut > 0 ? f - fut : null, gapPct: fut > 0 ? ((f - fut) / fut) * 100 : null, n: near.length };
	}
	// a dealer-gamma proxy (an ASSUMPTION, not an observation): dealers are taken to be long the calls and short the puts that are open, so net gamma exposure by strike is open interest x gamma x spot^2 x 1%
	// (calls +, puts -), and the flip is where the running total crosses zero. Positive total = price tends to be pinned; negative = moves tend to be amplified.
	function gamma(rows, spot, T, r, lot) {
		if (!(spot > 0 && T > 0 && lot > 0)) return null;
		let net = 0, used = 0;
		const by = [];
		for (const x of rows) {
			let g = 0;
			for (const t of ["ce", "pe"]) {
				const o = x[t];
				if (!o || o.iv == null || !(o.oi > 0)) continue;
				const gm = QB.greeks(t === "ce" ? "CE" : "PE", spot, x.k, T, o.iv, r).gamma;
				g += (t === "ce" ? 1 : -1) * o.oi * gm * spot * spot * 0.01 * lot;
				used++;
			}
			by.push({ k: x.k, g });
			net += g;
		}
		if (!used) return null;
		let run = 0, flip = null;
		for (let i = 0; i < by.length; i++) {
			const before = run;
			run += by[i].g;
			if (flip == null && i > 0 && ((before < 0 && run >= 0) || (before > 0 && run <= 0))) flip = by[i].k;
		}
		return { net, flip, used };
	}
	// one reading of the board. ctx: {t (ms), spot, fut, rows (AN.chainRows), chain, quotes, T, r, lot, atm (AN.atm result)}
	function sample(ctx) {
		const { t, spot, fut, rows, chain, quotes, T, r, lot, atm } = ctx;
		if (!(spot > 0)) return null;
		const par = parity(rows, spot, T, r, fut), pr = pressure(chain, quotes, spot, 3, 60), gx = gamma(rows, spot, T, r, lot);
		return { t, spot, fut: fnum(fut), basis: fut > 0 ? fut - spot : null, atmIv: atm ? atm.iv : null, straddle: atm ? atm.straddle : null, fwd: par ? par.fwd : null, gapPct: par ? par.gapPct : null,
			pressure: pr ? pr.score : null, gexNet: gx ? gx.net : null, flip: gx ? gx.flip : null };
	}
	// which rules fire on the latest sample, given the tape (samples oldest first)
	function fire(hist) {
		const last = hist[hist.length - 1];
		if (!last) return [];
		const out = [];
		if (last.pressure != null && Math.abs(last.pressure) >= RULES.pressure_v1.th) out.push({ rule: "pressure_v1", dir: last.pressure > 0 ? 1 : -1, why: `pressure ${last.pressure.toFixed(2)}` });
		if (last.gapPct != null && Math.abs(last.gapPct) >= RULES.parity_v1.th) out.push({ rule: "parity_v1", dir: last.gapPct > 0 ? 1 : -1, why: `options forward ${last.gapPct >= 0 ? "above" : "below"} futures by ${Math.abs(last.gapPct).toFixed(2)}%` });
		if (last.gexNet != null && last.flip != null && last.gexNet < 0) {
			if (last.spot < last.flip) out.push({ rule: "gamma_v1", dir: -1, why: `negative gamma, price under the flip ${last.flip}` });
			else if (last.spot > last.flip) out.push({ rule: "gamma_v1", dir: 1, why: `negative gamma, price over the flip ${last.flip}` });
		}
		const past = [...hist].reverse().find((s) => s.t <= last.t - 600000);
		if (past && last.straddle > 0 && past.straddle > 0 && Math.abs((last.spot / past.spot - 1) * 100) < 0.1 && (last.straddle / past.straddle - 1) * 100 >= RULES.straddle_v1.th)
			out.push({ rule: "straddle_v1", dir: 0, why: `straddle +${((last.straddle / past.straddle - 1) * 100).toFixed(1)}% in 10 min, price flat` });
		return out;
	}
	// log the firings (not the same rule again within REFIRE_S) and grade the old ones against the tape: after HORIZON_S the price either moved the called way by MIN_MOVE_PCT (a hit), or not
	// (a miss: flat counts against it). A volatility call (dir 0) is a hit if the price moved VOL_MOVE_PCT either way. An entry the tape cannot grade (no sample near the horizon) stays open.
	function update(log, hist, firings, now) {
		const out = log.map((e) => ({ ...e }));
		for (const f of firings) {
			const recent = out.filter((e) => e.rule === f.rule).pop();
			if (!recent || now - recent.t >= REFIRE_S * 1000) { const last = hist[hist.length - 1]; out.push({ t: now, rule: f.rule, dir: f.dir, spot: last.spot, why: f.why, res: null }); }
		}
		for (const e of out) {
			if (e.res || now - e.t < HORIZON_S * 1000) continue;
			const target = e.t + HORIZON_S * 1000, s = hist.filter((x) => x.t >= target && x.t <= target + 300000)[0];
			if (!s) { if (now - e.t > (HORIZON_S + 1800) * 1000) e.res = "ungraded"; continue; }
			const mv = (s.spot / e.spot - 1) * 100;
			e.mv = Math.round(mv * 1000) / 1000;
			e.res = e.dir === 0 ? (Math.abs(mv) >= VOL_MOVE_PCT ? "hit" : "miss") : (e.dir * mv >= MIN_MOVE_PCT ? "hit" : "miss");
		}
		return out.slice(-MAX_LOG);
	}
	// the record of each rule: graded firings, hits, the hit rate and how far it is from a coin (z); UNPROVEN until MIN_N graded and a clear margin (z >= 2)
	function record(log) {
		const out = {};
		for (const id of Object.keys(RULES)) {
			const g = log.filter((e) => e.rule === id && (e.res === "hit" || e.res === "miss")), n = g.length, hits = g.filter((e) => e.res === "hit").length;
			const base = RULES[id].dir ? 0.5 : 0.5;                                                            // a coin is the bar: nothing here has earned more
			const z = n > 0 ? (hits - base * n) / Math.sqrt(base * (1 - base) * n) : 0;
			out[id] = { n, hits, rate: n ? hits / n : null, z, proven: n >= MIN_N && z >= 2, open: log.filter((e) => e.rule === id && !e.res).length };
		}
		return out;
	}
	return { RULES, HORIZON_S, MIN_N, MAX_HIST, MIN_MOVE_PCT, VOL_MOVE_PCT, pressure, parity, gamma, sample, fire, update, record, median };
})();
/* @@flow:end */

// ==================================================================================================================
// News and the board: the news digest (titles and https links from the desk's news engine, via the relay) joined to the live board. For each story: which names it mentions, how far each has moved today
// and whether its options are trading hard, so a headline the market ignored is told apart from one it did not. Pure maths, no DOM, no network. The tone is a word-list reading (tilted by surprise where the
// text states an expectation): a hint, not a view. Nothing here is a forecast or a signal.
// ==================================================================================================================
/* @@news:start */
const NW = (() => {
	const fnum = (x) => (typeof x === "number" && isFinite(x) ? x : null);
	const IMPACT = { high: 3, medium: 2, low: 1 };
	const HALF_LIFE_MIN = 120;
	const isIndex = (sym) => ["NIFTY", "BANKNIFTY", "SENSEX", "FINNIFTY", "MIDCPNIFTY"].includes(sym);
	// today's move of a name on the board (spot, else its future) and how many of its options are trading hard (volume against open interest, fresh quotes)
	function boardOf(sym, quotes, hot) {
		const q = quotes[sym] || ["-FUT", "-MCX", "-CDS", "-BFO"].map((x) => quotes[sym + x]).find(Boolean) || null;     // spot, else its future (NSE, MCX, currency, BSE)
		return { sym, chg: q ? fnum(q.chg) : null, price: q ? fnum(q.ltp) : null, hot: (hot[sym] || []).length, hotTop: (hot[sym] || [])[0] || null };
	}
	// "the market cared": the name moved at least 1% (an index 0.5%) or its options are trading unusually hard
	function cared(b) {
		return (b.chg != null && Math.abs(b.chg) >= (isIndex(b.sym) ? 0.5 : 1)) || b.hot > 0;
	}
	function hotMap(quotes) {
		const out = Object.create(null);
		for (const x of AN.unusual(quotes, 400, 120)) (out[x.u] = out[x.u] || []).push(x);
		return out;
	}
	const toneWord = (t) => (t >= 0.15 ? "leans positive" : t <= -0.15 ? "leans negative" : "neutral");
	// every story, annotated and ranked. now: ms. A recap of the market's own move weighs little; several outlets, a high impact, a named F&O name and the market's reaction weigh more; old stories fade (half-life 2 h).
	function rank(digest, quotes, now) {
		if (!digest || !Array.isArray(digest.items)) return [];
		const hot = hotMap(quotes || {});
		return digest.items.map((it) => {
			const ageMin = Math.max(0, (now - Date.parse(it.ts)) / 60000);
			const names = (it.symbols || []).map((s) => boardOf(s, quotes || {}, hot));
			const care = names.filter(cared);
			const nov = fnum(it.novelty);
			const score = (IMPACT[it.impact] || 1) * (it.recap ? 0.3 : 1) * (1 + 0.5 * Math.max(0, (it.sources || []).length - 1)) * (names.length ? 1.3 : 1) * (1 + care.length * 0.6) * Math.pow(0.5, ageMin / HALF_LIFE_MIN) * (0.5 + 0.5 * (nov == null ? 1 : nov));
			return { item: it, ageMin, names, care, score, tone: toneWord(it.tone) };
		}).sort((a, b) => b.score - a.score);
	}
	// the stories about one underlying, plus (for an index) the market-wide ones that matter to every index: a high impact that is not a recap
	function forUnderlying(ranked, u, n) {
		const wide = (r) => r.item.impact === "high" && !r.item.recap;
		return ranked.filter((r) => (Array.isArray(r.item.symbols) && r.item.symbols.includes(u)) || (isIndex(u) && wide(r))).slice(0, n);      // a story that names nothing is not about this one
	}
	return { rank, forUnderlying, boardOf, cared, hotMap, toneWord, isIndex };
})();
/* @@news:end */

// ---- the builder (an instrument's Strategy view): pick an expiry and a structure; see what it costs, where it makes and loses, and whether it fits the desk's limits. Paper only.
S.bd = { u: null, exp: null, tpl: "bull_call_spread", width: 2, lots: 1, data: null, busy: false, note: "", view: null, sort: "rr", news: null, newsAt: 0, newsErr: "", custom: [], sc: { move: 0, dvol: 0, days: 0 } };
function bdChains(data) {                                                // the underlyings the builder can price: an index with a known lot size, and its board chains
	const c = QB.conf(), all = liveChains(data), out = Object.create(null);
	for (const u of Object.keys(c.inst)) if (all[u] && Object.keys(all[u]).length) out[u] = all[u];
	return out;
}
// ---- the market read and the ideas for a view, above the builder ----------------------------------------------------------------------------
function bdRead(ctx) {
	const { B, data, chains, ch, exps, spot, T, sq, c } = ctx;
	const rows = AN.chainRows(ch, data.quotes, spot, T, QB.rateOf(B.u, c)), a = AN.atm(rows, spot, T, sq.chg);
	if (!a || a.iv == null) return h("div", { class: "note" }, "Not enough two-sided prices around the money yet to read the market.");
	const sk = AN.skew(rows, spot, 3), pc = AN.pcr(rows), mp = AN.maxPain(rows), w = AN.walls(rows, spot, 2);
	const next = exps[exps.indexOf(B.exp) + 1], tm = next ? AN.term(rows, AN.chainRows(chains[B.u][next], data.quotes, spot, QB.yearsTo(next, Date.now()), QB.rateOf(B.u, c)), spot, T, QB.yearsTo(next, Date.now())) : null;
	const ages = rows.filter((r) => r.k === a.k).flatMap((r) => [r.ce && r.ce.age, r.pe && r.pe.age]).filter((x) => x != null), oldest = ages.length ? Math.max(...ages) + Math.max(0, (Date.now() - (B.at || Date.now())) / 1000) : null;
	const kv = (k, v, note) => h("div", { class: "row", style: "justify-content:space-between;padding:7px 16px;border-top:1px solid var(--line);gap:12px;align-items:flex-start" }, h("span", { class: "f3" }, k), h("span", { style: "text-align:right" }, h("b", { class: "mono" }, v), note ? h("div", { class: "f3", style: "font-size:11.5px" }, note) : null));
	const pct = (x, d = 2) => (x == null ? "—" : x.toFixed(d) + "%"), lv = (list) => (list.length ? list.map((x) => num(x.k, 0)).join(", ") : "—");
	const un = AN.unusual(data.quotes, 5, 120);
	return h("div", { class: "grp" }, h("div", { class: "pad", style: "font-weight:600" }, `Market read: ${B.u} ${B.exp}`),
		oldest != null && oldest > 60 ? h("div", { class: "warn", style: "font-size:12.5px;padding:2px 16px" }, `The prices at the money are ${Math.round(oldest)} s old: this read may be stale.`) : null,
		kv("Volatility at the money", pct(a.iv * 100, 1), `strike ${num(a.k, 0)}`),
		kv("The straddle prices a move of", a.expiryMovePct != null ? `±${pct(a.expiryMovePct)} (±${inr(a.straddle)} a unit)` : "—", `by ${B.exp}`),
		kv("A normal day, on that volatility", `±${pct(a.dayMovePct)}`, a.todayPct != null ? `today so far ${signed(a.todayPct)}% (${a.todayVsImplied != null ? a.todayVsImplied.toFixed(1) + "x a normal day" : "—"})` : null),
		sk ? kv("Skew (puts minus calls, 3 strikes out)", `${signed(sk.points, 1)} vol points`, sk.points > 1 ? "puts cost more: the market pays up for downside" : sk.points < -1 ? "calls cost more: the market pays up for upside" : "balanced") : null,
		tm ? kv("This expiry against the next", `${signed(tm.points, 1)} vol points`, tm.points > 1 ? "near-term volatility is dearer: the market prices something soon" : tm.points < -1 ? "later volatility is dearer" : "flat") : null,
		kv("Puts per call (open interest)", pc.oi != null ? pc.oi.toFixed(2) : "—", pc.vol != null ? `traded today ${pc.vol.toFixed(2)}` : null),
		kv("Max pain", mp != null ? num(mp, 0) : "—", mp != null ? `${signed(((mp - spot) / spot) * 100)}% from the price: where option buyers would collect least at expiry` : "no open interest on the board"),
		kv("Most open interest above / below", `${lv(w.resistance)} / ${lv(w.support)}`, "calls above the price, puts below it"),
		un.length ? h("div", { class: "pad", style: "border-top:1px solid var(--line)" }, h("div", { class: "f3", style: "font-size:12px;margin-bottom:4px" }, "Options trading unusually hard today (volume against open interest, across the board)"),
			un.map((x) => h("div", { class: "row", style: "justify-content:space-between;font-size:12.5px;padding:2px 0" }, h("span", { class: "mono" }, `${x.u} ${x.e} ${num(x.k, 0)} ${x.t}`), h("span", { class: "mono f3" }, `${x.ratio.toFixed(1)}x · ${signed(x.chg || 0)}%`)))) : null,
		h("div", { class: "f3", style: "font-size:11.5px;line-height:1.55;padding:6px 16px 10px" }, "What the options imply and what is open: counts and prices, not forecasts. Volatility is the market's own, from the mid of the bid and the offer."));
}
// ---- the advisor and the designer (QB.advise, QB.design) ------------------------------------------------------------------------------------------
function deskLab() {                                                          // AUTO v2's read of the market, from the paper runner's state (deskLoad fetches it): display only
	return (S.pp.data && S.pp.data.summary && S.pp.data.summary.lab) || null;
}
function bdAdvisor(cx) {
	const { B, strikes, names, spot, T, c, data, sq, rows } = cx;
	const chip = (label, on, fn) => h("button", { class: "chip", "aria-pressed": String(on), onclick: fn }, label);
	const dc = QB.deskContext(deskLab(), B.u), ctx = { ...dc.ctx, view: B.advView ? B.advView : dc.ctx.view };
	const box = h("div", { class: "grp" },
		h("div", { class: "f3", style: "font-size:12.5px;line-height:1.55;padding:8px 16px 4px" }, dc.seen.length ? `What the desk sees for ${B.u}: ${dc.seen.join(" · ")}.`
			: `The desk has no read of ${B.u} yet${store("qd.livekey") ? " (AUTO v2 reads an underlying once its options are on the board)" : " (enter the live key on the Paper tab to bring it in)"}. Pick a view below and the advisor reasons from that.`),
		h("div", { class: "chips", style: "padding:4px 16px" }, [chip("The desk's read", !B.advView, () => { B.advView = null; bdDraw(); }),
			...Object.entries(AN.VIEWS).map(([id, v]) => chip(v.name, B.advView === id, () => { B.advView = id; B.design = null; bdDraw(); }))]));
	const ranked = QB.advise(ctx), verdict = QB.verdict(ranked);
	put(box, h("div", { class: "note", style: "margin:6px 16px;padding-top:4px" }, verdict.text));
	const atmIdx = strikes.reduce((b, k, i) => (Math.abs(k - spot) < Math.abs(strikes[b] - spot) ? i : b), 0);
	const buildRows = (rws) => { B.custom = rws.map((x) => ({ side: x.side, type: x.type, strike: x.strike != null ? x.strike : strikes[atmIdx + x.off], mult: x.mult || 1 })); B.tpl = "custom"; bdDraw(); scrollTo({ top: 0, behavior: "smooth" }); };
	for (const x of ranked.slice(0, 6)) put(box, h("div", { class: "pad", style: "border-top:1px solid var(--line)" },
		h("div", { class: "row", style: "justify-content:space-between;align-items:center;gap:8px" }, h("b", {}, x.name), x.invented ? h("span", { class: "tag" }, "invented by the desk") : h("span", { class: "mono f3" }, `score ${x.score > 0 ? "+" : ""}${x.score}`)),
		x.why.length ? h("div", { style: "font-size:12px;line-height:1.5" }, x.why.map((w) => h("div", {}, h("b", { class: "up" }, "✓ "), w))) : null,
		x.against.length ? h("div", { style: "font-size:12px;line-height:1.5" }, x.against.map((w) => h("div", {}, h("b", { class: "dn" }, "✗ "), w))) : null,
		h("button", { class: "btn", style: "margin-top:6px", onclick: () => { if (x.rows) buildRows(x.rows); else { B.tpl = x.id; if (x.wide && !B.width) B.width = 2; bdDraw(); scrollTo({ top: 0, behavior: "smooth" }); } } }, "Build this")));
	const sigma = AN.atm(rows, spot, T, null), em = sigma && sigma.iv != null ? spot * sigma.iv * Math.sqrt(T) : null, view = ctx.view;
	put(box, h("div", { class: "pad", style: "border-top:1px solid var(--line)" },
		h("div", { style: "font-weight:600" }, "Design one for this view"),
		h("div", { class: "f3", style: "font-size:12px;line-height:1.55" }, view ? `Searches leg combinations on the live board (defined risk only, up to 4 legs) for "${AN.VIEWS[view].name.toLowerCase()}", ranked by what each pays if the view is right, per rupee it can lose, after costs. It says when its answer is a structure that already has a name.`
			: "Pick a view first (or wait for the desk's)."),
		view && em ? h("button", { class: "btn", style: "margin-top:6px", onclick: () => { B.design = { view, at: Date.now(), out: QB.design({ u: B.u, exp: B.exp, view, strikes, names, quotes: data.quotes, spot, spotAge: sq.age_s, T, em, c,
			budget: c.equity * c.limits.risk_per_trade, seed: Math.floor(Date.now() / 60000) % 100000 }) }; bdDraw(); } }, "Design it") : null));
	const d = B.design && B.design.view === view ? B.design.out : null;
	if (d && d.error) put(box, h("div", { class: "note" }, d.error));
	if (d && d.designs) {
		if (!d.designs.length) put(box, h("div", { class: "note" }, `Nothing on this board pays if the view is right without risking more than the per-trade limit (${d.tried} combinations tried).`));
		for (const x of d.designs) put(box, h("div", { class: "pad", style: "border-top:1px solid var(--line)" },
			h("div", { class: "row", style: "justify-content:space-between;gap:8px" }, h("b", {}, x.known ? x.known.name : "A structure of its own"), h("span", { class: "tag " + (x.known ? "flat" : "bull") }, x.known ? "has a name" : "new")),
			h("div", { class: "mono", style: "font-size:12px" }, x.text),
			h("div", { class: "f3", style: "font-size:12px;line-height:1.55" }, `If right, on average ${inr(x.avgRight, true)} (${(x.score * 100).toFixed(0)}% of the worst loss) · if wrong ${inr(x.avgWrong, true)} · worst loss ${inr(x.maxLoss)} · ${x.premium >= 0 ? "pay" : "receive"} ${inr(Math.abs(x.premium))}`),
			h("button", { class: "btn", style: "margin-top:6px", onclick: () => buildRows(x.rows) }, "Build this")));
	}
	return put(box, h("div", { class: "f3", style: "font-size:11.5px;line-height:1.55;padding:6px 16px 12px" }, "The reasons are the textbook's and the desk's own record by structure; the designs are judged on your view being right. Neither is a forecast: before costs, options at the market's own volatility are a fair bet."));
}
function bdIdeas(ctx) {
	const { B, strikes, names, spot, T, c, data, sq, rows, next } = ctx;
	const sigma = AN.atm(rows, spot, T, null);
	const chip = (label, on, fn) => h("button", { class: "chip", "aria-pressed": String(on), onclick: fn }, label);
	const box = h("div", { class: "grp" }, h("div", { class: "pad", style: "font-weight:600" }, "Ideas for your view"),
		h("div", { class: "chips", style: "padding:4px 16px" }, Object.entries(AN.VIEWS).map(([id, v]) => chip(v.name, B.view === id, () => { B.view = B.view === id ? null : id; bdDraw(); }))));
	if (!B.view) return put(box, h("div", { class: "f3", style: "font-size:12.5px;padding:2px 16px 12px" }, "Pick what you expect and every structure that fits it is priced on the live board and ranked."));
	if (!sigma || sigma.iv == null) return put(box, h("div", { class: "f3", style: "font-size:12.5px;padding:2px 16px 12px" }, "No volatility to price the chances with yet."));
	const analyzeFn = (id, width) => {
		const L = QB.legsFor(id, strikes, spot, names, width, next);
		return L.error ? null : QB.analyze({ u: B.u, exp: B.exp, legs: L.legs, quotes: data.quotes, spot, spotAge: sq.age_s, ageAdd: Math.max(0, (Date.now() - (B.at || Date.now())) / 1000), T, lots: 1 });
	};
	const list = AN.rank(AN.ideas(B.view, analyzeFn, { spot, T, sigma: sigma.iv, r: QB.rateOf(B.u, c) }), B.sort).slice(0, 6);
	put(box, h("div", { class: "chips", style: "padding:0 16px 4px" }, [["rr", "Best reward for the risk"], ["pop", "Most likely to profit"], ["cheap", "Cheapest"]].map(([id, t]) => chip(t, B.sort === id, () => { B.sort = id; bdDraw(); }))));
	if (!list.length) return put(box, h("div", { class: "f3", style: "font-size:12.5px;padding:2px 16px 12px" }, "None of these structures can be priced on the board right now."));
	for (const x of list) put(box, h("div", { class: "pad", style: "border-top:1px solid var(--line)" },
		h("div", { class: "row", style: "justify-content:space-between;align-items:center;gap:8px" }, h("b", {}, x.name + (QB.TEMPLATES[x.id].wide ? ` (${x.width} strike${x.width === 1 ? "" : "s"} wide)` : "")), h("span", { class: "tag " + (x.paperOk ? "bull" : "flat") }, x.paperOk ? "paper desk can open" : "what-if only")),
		h("div", { class: "f3", style: "font-size:12px;line-height:1.55" }, `${x.premium >= 0 ? "Pay" : "Receive"} ${inr(Math.abs(x.premium))} · worst loss ${inr(x.maxLoss)} · best profit ${x.maxProfit === Infinity ? "no cap" : inr(x.maxProfit)} · chance on the model ${x.pop != null ? Math.round(x.pop * 100) + "%" : "—"}`),
		h("button", { class: "btn", style: "margin-top:6px", onclick: () => { B.tpl = x.id; B.width = x.width; bdDraw(); scrollTo({ top: 0, behavior: "smooth" }); } }, "Build this")));
	return put(box, h("div", { class: "f3", style: "font-size:11.5px;line-height:1.55;padding:6px 16px 12px" }, "The chance uses the market's own volatility, so before costs every structure here is a fair bet: it tells you how a trade pays, not whether to take it. Your edge is your view."));
}
// ---- news and the board, in the Build tab ------------------------------------------------------------------------------------------------------
async function deskLoad() {                                                   // the paper runner's state, for the builder's advisor (a read: GET only), at most once a minute
	const B = S.bd;
	if (!store("qd.livekey") || Date.now() - (B.deskAt || 0) < 60000) return false;
	B.deskAt = Date.now();
	try {
		const r = await paperCall("GET", "/paper/state");
		if (r.status === 200 && r.body) { S.pp.data = r.body; return true; }
	} catch (e) { /* no read: the advisor reasons from the view you pick */ }
	return false;
}
async function newsLoad(key) {
	const B = S.bd;
	try {
		const r = await fetch("/news", { headers: { Authorization: "Bearer " + key }, cache: "no-store" });
		if (!r.ok) { B.newsErr = `The news store did not answer as expected (HTTP ${r.status}).`; return; }
		const j = await r.json();
		B.news = j && typeof j === "object" ? j : null;
		B.newsErr = "";
	} catch (e) { B.newsErr = "The news could not be fetched."; }
}
function bdNews(B, data) {
	const box = h("div", { class: "grp" }, h("div", { class: "pad", style: "font-weight:600" }, "News and the board"));
	const note = (t) => put(box, h("div", { class: "f3", style: "font-size:12.5px;padding:2px 16px 12px" }, t));
	const n = B.news;
	if (!n) return note(B.newsErr || "Loading the news…");
	if (!n.digest) return note("No news digest has reached the relay yet. It is read every ten minutes while the market is open.");
	const now = Date.now(), ranked = NW.rank(n.digest, data.quotes, now), about = NW.forUnderlying(ranked, B.u, 4), top = ranked.filter((r) => !about.includes(r)).slice(0, 5);
	const old = (now - Date.parse(n.digest.asof)) / 60000, feeds = Object.values(n.digest.sources || {}), ok = feeds.filter((x) => String(x).startsWith("ok")).length;
	const ageText = (m) => (m < 1 ? "just now" : m < 60 ? `${Math.round(m)} min ago` : `${(m / 60).toFixed(1)} h ago`);
	const row = (r) => {
		const it = r.item, safe = typeof it.link === "string" && /^https:\/\//.test(it.link);
		const head = safe ? h("a", { href: it.link, target: "_blank", rel: "noopener noreferrer", style: "color:inherit;font-weight:600;font-size:13.5px;line-height:1.4" }, it.title) : h("span", { style: "font-weight:600;font-size:13.5px;line-height:1.4" }, it.title);
		const names = r.names.map((b) => h("span", { class: "mono", style: "font-size:11.5px;margin-right:10px" }, b.sym + (b.chg != null ? " " + signed(b.chg) + "%" : ""), b.hot ? h("span", { class: "warn" }, " options busy") : null));
		return h("div", { class: "pad", style: "border-top:1px solid var(--line)" }, head,
			h("div", { class: "row", style: "gap:6px;flex-wrap:wrap;align-items:center;margin-top:3px" },
				h("span", { class: "tag " + (r.tone === "leans positive" ? "bull" : r.tone === "leans negative" ? "bear" : "flat") }, r.tone),
				it.impact !== "low" ? h("span", { class: "tag " + (it.impact === "high" ? "bear" : "flat") }, it.impact + " impact") : null, it.recap ? h("span", { class: "tag flat" }, "market recap") : null,
				r.care.length ? h("span", { class: "tag bull" }, "the market reacted") : null,
				h("span", { class: "f3", style: "font-size:11.5px" }, `${(it.sources || []).length} outlet${(it.sources || []).length === 1 ? "" : "s"} · ${ageText(r.ageMin)}`)),
			names.length ? h("div", { style: "margin-top:3px" }, names) : null);
	};
	if (old > 25 && inSession()) put(box, h("div", { class: "warn", style: "font-size:12.5px;padding:2px 16px" }, `The newest digest is ${ageText(old)}: the news job may not be running.`));
	const evs = Array.isArray(n.digest.events) ? n.digest.events : [];                        // the event watch (newsdigest.py) and, from the pre-market brief, what happened the last times
	if (evs.length) put(box, h("div", { class: "f3", style: "font-size:12px;padding:6px 16px 2px" }, "Event watch"), evs.map((e) => {
		const a = S.pm && S.pm.analogs && e.kind && S.pm.analogs[e.kind] ? S.pm.analogs[e.kind].NIFTY : null;
		const past = a && a.n ? `The last ${a.n} ${String(e.kind).replace(/_/g, " ")} episodes: NIFTY ${signed((a.median_ret || 0) * 100)}% on the day (median), fell ${Math.round((a.share_down || 0) * a.n)} of ${a.n}, worst ${signed((a.worst || 0) * 100)}%` + (a.median_5d != null ? `, ${signed(a.median_5d * 100)}% over five sessions.` : ".") : "";
		return h("div", { class: "pad", style: "border-top:1px solid var(--line)" },
			h("div", { class: "row", style: "gap:6px;align-items:center;flex-wrap:wrap" }, h("b", {}, String(e.type).replace(/_/g, " ")), h("span", { class: "tag " + (e.level === "high" ? "bear" : "flat") }, e.level === "high" ? "high: AUTO sells no volatility into it" : "watch"),
				h("span", { class: "f3 mono", style: "font-size:11.5px" }, `severity ${fin(e.severity) ? e.severity.toFixed(1) : "—"} · tone ${fin(e.tone) ? signed(e.tone) : "—"} · ${e.n} stor${e.n === 1 ? "y" : "ies"}`)),
			(e.top || []).length ? h("div", { class: "f3", style: "font-size:12px;line-height:1.45;margin-top:2px" }, e.top[0]) : null,
			past ? h("div", { class: "f2", style: "font-size:12px;line-height:1.45;margin-top:2px" }, past) : null);
	}));
	if (about.length) put(box, h("div", { class: "f3", style: "font-size:12px;padding:2px 16px" }, `About ${B.u}`), about.map(row));
	if (top.length) put(box, h("div", { class: "f3", style: "font-size:12px;padding:6px 16px 2px;border-top:1px solid var(--line)" }, "Top stories right now"), top.map(row));
	if (!about.length && !top.length) note("No stories in the digest.");
	return put(box, h("div", { class: "f3", style: "font-size:11.5px;line-height:1.55;padding:6px 16px 12px" },
		`Headlines and links from ${ok} of ${feeds.length} public feeds, read ${ageText(old)}. The tone is a word-list reading of the headline, tilted by surprise where the text states an expectation: a hint, not a view. "The market reacted" means a named name moved 1% (an index 0.5%) today or its options are trading hard.`));
}
function bdPayoff(a, spot) {
	const W = 640, H = 220, P = { l: 78, r: 12, t: 12, b: 26 }, el = svg("svg", { viewBox: `0 0 ${W} ${H}`, class: "bd-chart", role: "img", "aria-label": "Profit and loss at expiry and today, by price of the underlying", style: "width:100%;height:auto;max-height:300px;display:block" });
	const ys = [...a.expiry, ...a.today], lo = Math.min(...ys, 0), hi = Math.max(...ys, 0), pad = (hi - lo) * 0.08 || 1;
	const x = (S) => P.l + (S - a.grid[0]) / (a.grid[a.grid.length - 1] - a.grid[0]) * (W - P.l - P.r), y = (v) => P.t + (hi + pad - v) / (hi - lo + 2 * pad) * (H - P.t - P.b);
	svg("line", { x1: P.l, x2: W - P.r, y1: y(0), y2: y(0), stroke: cssv("--line") || "#888", "stroke-width": 1 }, el);
	for (const v of [lo, hi]) { const t = svg("text", { x: P.l - 6, y: y(v) + 4, "text-anchor": "end", fill: cssv("--fg3") || "#888", "font-size": 11 }, el); t.textContent = inr(v); }
	svg("line", { x1: x(spot), x2: x(spot), y1: P.t, y2: H - P.b, stroke: cssv("--fg3") || "#888", "stroke-dasharray": "3 3" }, el);
	const path = (arr) => arr.map((v, i) => (i ? "L" : "M") + x(a.grid[i]).toFixed(1) + " " + y(v).toFixed(1)).join("");
	svg("path", { d: path(a.today), fill: "none", stroke: cssv("--fg2") || "#999", "stroke-width": 1.5, "stroke-dasharray": "5 4" }, el);
	svg("path", { d: path(a.expiry), fill: "none", stroke: cssv("--acc") || "#7D95FF", "stroke-width": 2.2 }, el);
	for (const b of a.breakevens) if (b > a.grid[0] && b < a.grid[a.grid.length - 1]) svg("circle", { cx: x(b), cy: y(0), r: 3.5, fill: cssv("--acc") || "#7D95FF" }, el);
	const t = svg("text", { x: W / 2, y: H - 6, "text-anchor": "middle", fill: cssv("--fg3") || "#888", "font-size": 10 }, el);
	t.textContent = `${num(a.grid[0], 0)}  ←  price of the underlying  →  ${num(a.grid[a.grid.length - 1], 0)}   (solid: at expiry, dashed: today, dot: break-even)`;
	return el;
}
function bdDraw() {
	const B = S.bd, body = $("#bd-body"), c = QB.conf(), data = B.data;
	if (!body || !data) return;                                               // the builder lives on an instrument's Strategy view: nothing to draw when that is not open
	body.textContent = "";
	const chains = bdChains(data), us = Object.keys(chains);
	if (!us.includes(B.u)) return void put(body, empty("build", `No option chain for ${B.u || "this instrument"} on the board yet. The relay fills it once the market is open and the feeds are on.`));
	const exps = Object.keys(chains[B.u]).sort((p, q) => liveExpiryKey(p) - liveExpiryKey(q));
	if (!exps.includes(B.exp)) B.exp = exps[0];
	const ch = chains[B.u][B.exp], strikes = Object.keys(ch).map(Number).sort((p, q) => p - q);
	const nextExp = exps[exps.indexOf(B.exp) + 1], nextCh = nextExp ? chains[B.u][nextExp] : null;          // a calendar's later leg: the next expiry on the board
	const next = nextCh ? { strikes: Object.keys(nextCh).map(Number).sort((p, q) => p - q), names: nextCh, T: QB.yearsTo(nextExp, Date.now()), exp: nextExp } : null;
	const sq = data.quotes[B.u] || data.quotes[liveNames(B.u, data.quotes).fut] || {}, spot = sq.ltp;        // an MCX or currency option's underlying is its future (-MCX, -CDS)
	const T = QB.yearsTo(B.exp, Date.now()), inst = c.inst[B.u], tpl = B.tpl === "custom" ? QB.CUSTOM : QB.TEMPLATES[B.tpl];
	const chip = (label, on, fn) => h("button", { class: "chip", "aria-pressed": String(on), onclick: fn }, label);
	const step = (label, val, dn, up) => h("div", { class: "row", style: "justify-content:space-between;align-items:center;padding:8px 16px;border-top:1px solid var(--line)" }, h("span", {}, label), h("span", { style: "display:flex;gap:10px;align-items:center" }, h("button", { class: "btn sq", "aria-label": "less " + label, onclick: dn }, "−"), h("b", { class: "mono", style: "min-width:28px;text-align:center" }, String(val)), h("button", { class: "btn sq", "aria-label": "more " + label, onclick: up }, "+")));
	put(body,
		c.fromConfig ? null : h("div", { class: "note warn" }, "This page has no limits from the desk's config (QD_TRADE is missing), so it is using built-in defaults that may be out of date. Do not rely on the checklist; re-publish the site."),
		h("div", { class: "grp" }, h("div", { class: "sec-h" }, h("h2", {}, "Structure"), h("span", { class: "hint" }, tpl.view)),
			h("div", { class: "chips", style: "padding:4px 16px 8px" }, exps.map((e) => chip(e.slice(0, 2) + " " + cap(e.slice(2, 5).toLowerCase()), e === B.exp, () => { B.exp = e; S.lv.exp = e; bdDraw(); }))),
			h("div", { class: "chips", style: "padding:0 16px 10px" }, [...Object.keys(QB.TEMPLATES).map((id) => chip(QB.TEMPLATES[id].name, id === B.tpl, () => { B.tpl = id; bdDraw(); })),
				chip("Custom legs", B.tpl === "custom", () => { if (!B.custom.length && !(QB.TEMPLATES[B.tpl] || {}).multi) { const seed = QB.legsFor(B.tpl, strikes, spot, ch, B.width); if (seed.legs) B.custom = seed.legs.map((l) => ({ side: l.side, type: l.type, strike: l.strike, mult: 1 })); } B.tpl = "custom"; bdDraw(); })]),
			B.tpl === "custom" ? bdCustom(B, strikes, spot) : null,
			tpl.wide ? step("Width (strikes)", B.width, () => { B.width = Math.max(1, B.width - 1); bdDraw(); }, () => { B.width = Math.min(10, B.width + 1); bdDraw(); }) : null,
			step("Lots (" + ((inst.lots ? inst.lots[B.exp] : inst.lot) || "?") + " units each)", B.lots, () => { B.lots = Math.max(1, B.lots - 1); bdDraw(); }, () => { B.lots = Math.min(c.limits.max_lots, B.lots + 1); bdDraw(); })));
	if (!fin(spot)) return void put(body, h("div", { class: "note" }, `No price for ${B.u} on the board yet.`));
	const names = {};
	for (const k of strikes) names[k] = ch[k];
	const rows = AN.chainRows(ch, data.quotes, spot, T, QB.rateOf(B.u, c));
	if (S.open.advise === undefined) S.open.advise = true;                       // the advisor starts open, right under the structures: which one, and why, comes first
	put(body, fold("advise", "Which strategy now, and why", "every structure, reasoned against the desk's read", bdAdvisor({ B, strikes, names, spot, T, c, data, sq, rows })));
	const ideas = () => fold("ideas", "Ideas for your view", "structures that fit what you expect", bdIdeas({ B, strikes, names, spot, T, c, data, sq, rows, next }));
	const L = B.tpl === "custom" ? QB.customLegs(B.custom, names) : QB.legsFor(B.tpl, strikes, spot, names, B.width, next);
	if (L.error) return void put(body, h("div", { class: "note" }, L.error), ideas());
	const spec = { u: B.u, exp: B.exp, legs: L.legs, quotes: data.quotes, spot, spotAge: sq.age_s, ageAdd: Math.max(0, (Date.now() - (B.at || Date.now())) / 1000), T, lots: B.lots };
	const a = QB.analyze(spec);
	if (a.errors.length) return void put(body, h("div", { class: "note" }, a.errors[0]), legsTable2(a), ideas());
	const best = QB.suggestLots(spec);
	const kv = (k, v, cl) => h("div", { class: "row", style: "justify-content:space-between;padding:7px 16px;border-top:1px solid var(--line)" }, h("span", { class: "f3" }, k), h("b", { class: "mono " + (cl || "") }, v));
	const tick = (x) => h("div", { class: "row", style: "padding:6px 16px;gap:8px;align-items:flex-start" }, h("b", { class: x.ok ? "up" : "dn", style: "width:14px" }, x.ok ? "✓" : "✗"), h("span", { style: "font-size:12.5px" }, x.text));
	put(body,
		h("div", { class: "grp" },
			h("div", { class: "kstrip" },
				h("div", {}, h("span", {}, a.premium >= 0 ? "You pay" : "You receive"), h("b", { class: "mono" }, inr(Math.abs(a.premium)))),
				h("div", {}, h("span", {}, "Worst loss"), h("b", { class: "mono dn" }, inr(-a.maxLoss))),
				h("div", {}, h("span", {}, "Best profit"), h("b", { class: "mono up" }, a.unlimitedProfit ? "No cap" : inr(a.maxProfit, true))),
				h("div", {}, h("span", {}, "Break-even" + (a.breakevens.length === 1 ? "" : "s")), h("b", { class: "mono" }, a.breakevens.map((b) => num(b, 0)).join(" · ") || "—"))),
			h("div", { style: "padding:10px 16px 6px" }, bdPayoff(a, spot)),
			a.multi ? h("div", { class: "f3", style: "font-size:11.5px;line-height:1.5;padding:0 16px 10px" }, "A calendar is drawn at the near expiry, the later option at its model value. The worst loss counts the later option at the least it can ever be worth (the paper desk's own rule), so it sits below the curve.") : null),
		h("div", { class: "grp" }, h("div", { class: "pad", style: "font-weight:600;display:flex;gap:8px;align-items:center" }, "Could the paper desk open this today?", h("b", { class: a.paperOk ? "up" : "dn" }, a.paperOk ? "Yes, so far" : "No")),
			(a.paperOk ? [] : a.paperChecks.filter((x) => !x.ok)).map(tick)),
		bdTicket(a, tpl),
		fold("legs", "Legs and prices", `${a.legs.length} leg${a.legs.length === 1 ? "" : "s"}`, legsTable2(a)),
		fold("costs", "Costs and Greeks", "", h("div", { class: "panel", style: "margin:0;border:0" },
			kv("Costs to get in and out (exit at today's price)", inr(a.cost) + ` (fees ${inr(a.fees)} + spread ${inr(a.exitSpread)})`),
			kv("Net delta · gamma", `${signed(a.greeks.delta, 1)} · ${signed(a.greeks.gamma, 3)}`), kv("Theta a day · vega per vol point", `${inr(a.greeks.theta, true)} · ${inr(a.greeks.vega, true)}`))),
		fold("whatif", "What if…", "the price moves, volatility shifts, days pass", bdScenario(B, a, spec)),
		fold("checks", "Sizing guide and the desk's checks", a.ok ? "fits" : "does not fit", h("div", { class: "grp" }, h("div", { class: "pad", style: "font-weight:600" }, "Sizing guide (the intraday desk's limits) and data quality"),
			a.checks.map(tick),
			h("div", { style: "padding:10px 16px;display:flex;gap:10px;align-items:center;flex-wrap:wrap" },
				h("button", { class: "btn", onclick: () => { B.lots = Math.max(1, best); bdDraw(); }, disabled: best < 1 }, best ? `Size it to the limits: ${best} lot${best === 1 ? "" : "s"}` : "Even one lot breaks a limit"),
				h("span", { class: "f3", style: "font-size:12px" }, a.ok ? "Fits the sizing guide." : "Does not fit the sizing guide: change the structure, width or size.")),
			h("div", { class: "pad", style: "font-weight:600;border-top:1px solid var(--line)" }, "The paper desk's own checks"),
			a.paperChecks.map(tick),
			h("div", { class: "f3", style: "font-size:11.5px;line-height:1.5;padding:4px 16px 8px" }, "The paper ticket also checks the day's loss budget, the drawdown halt and the displayed size at the touch against the live account. A structure that is not open-able today is still shown here as a what-if."))),
		ideas(),
		fold("model", "How this is worked out", "", h("div", { class: "f3", style: "font-size:11.5px;line-height:1.55;padding:6px 16px 14px" }, "Paper only. This works out what a structure would cost and risk from the live prices; it reads the live board. The only thing it can send is a paper order, queued on the relay and carried out by the paper runner through the risk gate. Only structures with a known worst loss can be built. Model: Black-Scholes at each leg's own implied volatility, flat rate " + (c.r * 100).toFixed(1) + "%. Buys are priced at the offer and sells at the bid; a leg with no live book is priced at its last trade and flagged. Fees use the desk's cost model. Margin for credit structures is the config estimate per lot, not the broker's figure. Held to expiry, an in-the-money long pays the exchange's exercise STT instead, which this does not model; there is no dividend yield in the pricing. Worst loss and best profit leave out costs.")));
}
// ---- flow and signals: the tape of the session, the rules that fired, and each rule's own record --------------------------------------------------------------
function bdFlow(ctx) {
	const { B, data, ch, spot, T, c, rows, inst } = ctx;
	const key = B.u + "|" + B.exp, logKey = "qd.flowlog." + B.u;
	if (B.tapeKey !== key) { B.tapeKey = key; B.tape = []; B.sampledAt = null; }
	if (!B.flowLogs) B.flowLogs = {};
	if (!B.flowLogs[B.u]) {
		let raw = []; try { raw = JSON.parse(store(logKey) || "[]"); } catch (e) { raw = []; }
		B.flowLogs[B.u] = (Array.isArray(raw) ? raw : []).filter((e) => e && typeof e.rule === "string" && FL.RULES[e.rule] && Number.isFinite(e.t) && Number.isFinite(e.spot)).slice(-400);
	}
	const fq = data.quotes[liveNames(B.u, data.quotes).fut], fut = fq ? (fq.bid > 0 && fq.ask >= fq.bid ? (fq.bid + fq.ask) / 2 : fq.ltp) : NaN;
	const nowT = typeof data.now === "number" ? data.now : Date.now();
	if (B.sampledAt !== B.at) {                                                                    // one reading per fetch of the board, however often the page is redrawn
		B.sampledAt = B.at;
		const sm = FL.sample({ t: nowT, spot, fut: Number.isFinite(fut) ? fut : null, rows, chain: ch, quotes: data.quotes, T, r: QB.rateOf(B.u, c), lot: inst.lot, atm: AN.atm(rows, spot, T, null) });
		if (sm && (!B.tape.length || sm.t > B.tape[B.tape.length - 1].t)) {
			B.tape.push(sm);
			if (B.tape.length > FL.MAX_HIST) B.tape.shift();
			B.flowLogs[B.u] = FL.update(B.flowLogs[B.u], B.tape, FL.fire(B.tape), sm.t);
			try { store(logKey, JSON.stringify(B.flowLogs[B.u])); } catch (e) { /* private mode */ }
		}
	}
	const tape = B.tape, last = tape[tape.length - 1], past = [...tape].reverse().find((x) => last && x.t <= last.t - 600000), rec = FL.record(B.flowLogs[B.u]);
	if (!last) return h("div", { class: "note" }, "Reading the flow: waiting for the first reading of the board.");
	const kv = (k, v, note, cl) => h("div", { class: "row", style: "justify-content:space-between;padding:7px 16px;border-top:1px solid var(--line);gap:12px;align-items:flex-start" }, h("span", { class: "f3" }, k),
		h("span", { style: "text-align:right" }, h("b", { class: "mono " + (cl || "") }, v), note ? h("div", { class: "f3", style: "font-size:11.5px" }, note) : null));
	const pct = (x, d = 2) => (x == null || !Number.isFinite(x) ? "—" : (x >= 0 ? "+" : "") + x.toFixed(d) + "%");
	const dIv = past && last.atmIv != null && past.atmIv != null ? (last.atmIv - past.atmIv) * 100 : null, dStr = past && last.straddle > 0 && past.straddle > 0 ? (last.straddle / past.straddle - 1) * 100 : null;
	const ann = last.basis != null && T > 0 ? (last.basis / spot) / T * 100 : null;
	const firing = FL.fire(tape);
	const recText = (id) => { const r = rec[id]; return r.proven ? `track record ${r.hits}/${r.n} (${(r.rate * 100).toFixed(0)}%, z ${r.z.toFixed(1)})` : `UNPROVEN: ${r.n} graded${r.n ? `, ${r.hits} hit` : ""}${r.open ? `, ${r.open} waiting` : ""} (needs ${FL.MIN_N} and a clear edge over a coin)`; };
	return h("div", { class: "grp" }, h("div", { class: "pad", style: "font-weight:600" }, `Flow and signals: ${B.u} ${B.exp}`, h("span", { class: "f3", style: "font-weight:400;font-size:12px" }, `  (${tape.length} reading${tape.length === 1 ? "" : "s"} this session)`)),
		kv("Futures minus spot", last.basis != null ? `${last.basis >= 0 ? "+" : ""}${num(last.basis, 1)} pts` : "—", ann != null ? `${ann.toFixed(1)}% a year carry` : "no futures price on the board"),
		kv("Forward the options imply, against futures", last.gapPct != null ? pct(last.gapPct) : "—", "from put-call parity at the money; a gap means options and futures disagree about where the price is going to be"),
		kv("Resting-size pressure around the money", last.pressure != null ? (last.pressure >= 0 ? "+" : "") + last.pressure.toFixed(2) : "—", last.pressure == null ? "needs sizes on fresh bids and offers" : last.pressure > 0.1 ? "bids lean bullish (calls bid, puts offered)" : last.pressure < -0.1 ? "bids lean bearish" : "balanced"),
		kv("Dealer gamma proxy (an assumption)", last.gexNet != null ? (last.gexNet >= 0 ? "positive" : "negative") : "—", last.flip != null ? `flips near ${num(last.flip, 0)}; ${last.gexNet >= 0 ? "moves tend to be damped" : "moves tend to be amplified"}` : "needs open interest"),
		kv("Straddle, last 10 minutes", dStr != null ? pct(dStr, 1) : "—", past ? `volatility ${dIv != null ? (dIv >= 0 ? "+" : "") + dIv.toFixed(2) + " points" : "—"}; price ${pct((last.spot / past.spot - 1) * 100)}` : "builds up after ten minutes of readings"),
		h("div", { class: "pad", style: "font-weight:600;border-top:1px solid var(--line)" }, "Rules that are firing now"),
		firing.length ? firing.map((f) => h("div", { class: "row", style: "padding:5px 16px;gap:8px;align-items:flex-start" }, h("b", { class: f.dir > 0 ? "up" : f.dir < 0 ? "dn" : "" }, f.dir > 0 ? "▲" : f.dir < 0 ? "▼" : "◆"),
			h("span", { style: "font-size:12.5px" }, `${FL.RULES[f.rule].text}. ${f.why}.`, h("div", { class: "f3", style: "font-size:11.5px" }, recText(f.rule))))) : h("div", { class: "f3", style: "font-size:12.5px;padding:2px 16px 8px" }, "None right now."),
		h("div", { class: "f3", style: "font-size:11.5px;line-height:1.55;padding:6px 16px 12px" }, `These are readings, not forecasts. Each rule's firings are logged with the price at the time and graded ${FL.HORIZON_S / 60} minutes later (it must move the called way by ${FL.MIN_MOVE_PCT}%; a volatility call must move ${FL.VOL_MOVE_PCT}% either way). Until a rule has ${FL.MIN_N} graded firings and clearly beats a coin it is UNPROVEN and should not be acted on. The record is kept in this browser only.`));
}
// ---- custom legs: add, flip, move and size as many legs as you like ----------------------------------------------------------------------
function bdCustom(B, strikes, spot) {
	const rows = B.custom, redraw = () => { B.editing = false; bdDraw(); };
	const flat = (label, on, fn, cls) => h("button", { class: "chip " + (cls || ""), "aria-pressed": String(on), onclick: fn }, label);
	const atm = strikes.length ? strikes.reduce((b, k) => (Math.abs(k - spot) < Math.abs(b - spot) ? k : b), strikes[0]) : 0;
	return h("div", { class: "grp" }, h("div", { class: "pad", style: "font-weight:600" }, `Your legs (${rows.length} of up to ${QB.MAX_CUSTOM_LEGS})`),
		rows.map((r, i) => h("div", { class: "row", style: "padding:4px 16px;gap:6px;align-items:center;flex-wrap:wrap" },
			flat(r.side > 0 ? "Buy" : "Sell", r.side > 0, () => { r.side = -r.side; redraw(); }, r.side > 0 ? "up" : "dn"), flat(r.type, r.type === "CE", () => { r.type = r.type === "CE" ? "PE" : "CE"; redraw(); }),
			h("select", { class: "search", style: "width:96px", "aria-label": `Strike of leg ${i + 1}`, onchange: (e) => { r.strike = Number(e.target.value); redraw(); } },
				(strikes.includes(r.strike) ? strikes : [r.strike, ...strikes]).map((k) => h("option", { value: String(k), ...(k === r.strike ? { selected: "selected" } : {}) }, String(k)))),
			h("button", { class: "btn", "aria-label": `smaller size of leg ${i + 1}`, onclick: () => { r.mult = Math.max(1, r.mult - 1); redraw(); } }, "−"), h("b", { class: "mono" }, "×" + r.mult),
			h("button", { class: "btn", "aria-label": `bigger size of leg ${i + 1}`, onclick: () => { r.mult = Math.min(100, r.mult + 1); redraw(); } }, "+"),
			h("button", { class: "btn", "aria-label": `remove leg ${i + 1}`, onclick: () => { rows.splice(i, 1); redraw(); } }, "Remove"))),
		h("div", { style: "padding:6px 16px 12px;display:flex;gap:10px;flex-wrap:wrap" },
			h("button", { class: "btn", disabled: rows.length >= QB.MAX_CUSTOM_LEGS, onclick: () => { rows.push({ side: 1, type: "CE", strike: atm, mult: 1 }); redraw(); } }, "Add a leg"),
			h("button", { class: "btn", disabled: !rows.length, onclick: () => { B.custom = []; redraw(); } }, "Clear")),
		h("div", { class: "f3", style: "font-size:11.5px;line-height:1.55;padding:0 16px 10px" }, "Sizes multiply the Lots below. A structure with a short call that is not covered is refused (unlimited loss). Sold legs go to the paper desk as one package (all legs or none), only if selling is switched on there."));
}
// ---- what-if sliders and a grid: the structure's value if spot moves, volatility shifts and days pass (theoretical, before exit costs) --------------------------------------
function bdScenario(B, a, spec) {
	const sc = B.sc, T = spec.T, maxDays = Math.floor(T * 365);
	const cell = (v) => h("td", { class: "mono " + (v >= 0 ? "up" : "dn"), style: "text-align:right" }, inr(v, true));
	const val = () => QB.scenario(a, spec, sc), out = h("b", { class: "mono" }, "");
	const paint = () => { const v = val(); out.textContent = inr(v, true); out.className = "mono " + (v >= 0 ? "up" : "dn"); };
	const slider = (label, key, min, max, step, fmt) => {
		const shown = h("b", { class: "mono" }, fmt(sc[key]));
		const input = h("input", { type: "range", min: String(min), max: String(max), step: String(step), value: String(sc[key]), "aria-label": label, style: "width:100%", oninput: (e) => { sc[key] = Number(e.target.value); shown.textContent = fmt(sc[key]); paint(); }, onfocus: () => { B.editing = true; }, onblur: () => { B.editing = false; } });
		input.addEventListener("pointerdown", () => { B.editing = true; }); input.addEventListener("pointerup", () => { B.editing = false; });
		return h("div", { style: "padding:4px 16px" }, h("div", { class: "row", style: "justify-content:space-between" }, h("span", { class: "f3", style: "font-size:12.5px" }, label), shown), input);
	};
	paint();
	const moves = [-0.04, -0.02, -0.01, 0, 0.01, 0.02, 0.04], dayList = [...new Set([0, Math.round(maxDays / 2), maxDays])];
	return h("div", { class: "grp" }, h("div", { class: "pad", style: "font-weight:600" }, "What if…"),
		slider("Spot moves", "move", -0.08, 0.08, 0.0025, (x) => (x >= 0 ? "+" : "") + (x * 100).toFixed(2) + "%"),
		slider("Volatility shifts (points)", "dvol", -0.1, 0.1, 0.005, (x) => (x >= 0 ? "+" : "") + (x * 100).toFixed(1)),
		slider("Days pass", "days", 0, Math.max(1, maxDays), 1, (x) => x + " day" + (x === 1 ? "" : "s")),
		h("div", { class: "row", style: "justify-content:space-between;padding:8px 16px" }, h("span", {}, "The structure is then worth, against what it cost"), out),
		h("div", { class: "panel scroll" }, h("table", { class: "tbl" }, h("thead", {}, h("tr", {}, [h("th", {}, "Days →"), ...moves.map((m) => h("th", { style: "text-align:right" }, (m >= 0 ? "+" : "") + (m * 100) + "%"))])),
			h("tbody", {}, dayList.map((d) => h("tr", {}, [h("td", {}, d === maxDays ? `${d} (expiry)` : String(d)), ...moves.map((m) => cell(QB.scenario(a, spec, { move: m, dvol: sc.dvol, days: d })))]))))),
		h("div", { class: "f3", style: "font-size:11.5px;line-height:1.55;padding:6px 16px 10px" }, "Theoretical values from the model at each leg's own implied volatility (shifted by the volatility slider); exit spread and fees are not included. At expiry it equals the payoff chart."));
}
function legsTable2(a) {
	return h("div", { class: "panel scroll" }, h("table", { class: "tbl" }, h("thead", {}, h("tr", {}, ["", "Strike", "Type", "Bid", "Ask", "Price used", "IV"].map((x) => h("th", {}, x)))),
		h("tbody", {}, a.legs.map((l) => h("tr", {}, h("td", { class: l.side > 0 ? "up" : "dn" }, l.side > 0 ? "Buy" : "Sell"), h("td", {}, num(l.strike, 0)), h("td", {}, l.type), h("td", {}, fin(l.bid) ? num(l.bid) : "—"), h("td", {}, fin(l.ask) ? num(l.ask) : "—"), h("td", {}, num(l.px) + (l.src === "last" ? " (last)" : l.src === "side" ? " (one side)" : "")), h("td", {}, fin(l.iv) ? (l.iv * 100).toFixed(1) + "%" : "—"))))));
}

// ==================================================================================================================
// Paper tickets. PAPER MONEY ONLY. These are the only functions in the app that POST, and they POST to exactly two relay routes: /paper/order (queue an order) and /paper/kill (the
// kill flag). The paper runner and its risk gate decide what happens; nothing here can reach a broker, and the relay key is the same one that reads the board.
// ==================================================================================================================
/* @@ticket:start */
const PT = (() => {
	const TICK = 0.05;
	const rnd = () => { const b = new Uint8Array(16); if (typeof crypto !== "undefined" && crypto.getRandomValues) crypto.getRandomValues(b); else for (let i = 0; i < 16; i++) b[i] = Math.floor(Math.random() * 256); return b; };
	const idNow = () => "ord-" + Array.from(rnd(), (x) => x.toString(16).padStart(2, "0")).join("");
	const flat = (t) => String(t == null ? "" : t).split(/\s+/).filter(Boolean).join(" ");
	const thesisOk = (t) => { const x = flat(t); return x.length >= 20 && x.length <= 1000; };
	const stratOk = (t) => { const x = flat(t); return x.length >= 1 && x.length <= 60; };
	// a buy may fill a little above the offer shown (three ticks or 2%, whichever is more), never further: the runner refuses it if the offer has run away or the size is expected to pay more
	// (the allowance covers the paper desk's largest modelled size impact, 3 ticks, so a limit is never tighter than what a big order is expected to pay)
	const limitFor = (ask) => Math.round(Math.ceil((ask + Math.max(3 * TICK, 0.02 * ask)) / TICK - 1e-9) * TICK * 100) / 100;
	// the orders for an analysed structure: one buy per leg, or, when any leg is SOLD, ONE package order (all legs together or none). {error} when it cannot be sent.
	function ordersFor(a, strategy, thesis, group, nowMs) {
		if (!a || a.paperOk !== true || !Array.isArray(a.legs) || !a.legs.length) return { error: "The paper desk cannot open this structure today (see the list above)." };
		if (!stratOk(strategy)) return { error: "Give the strategy a name (up to 60 characters)." };
		if (!thesisOk(thesis)) return { error: "Write the thesis: why this trade, now (at least 20 characters)." };
		if (!Number.isInteger(a.lots) || a.lots < 1 || a.lots > 1000) return { error: "The number of lots must be a whole number from 1 to 1000." };
		const pkg = a.legs.some((l) => l.side < 0);
		if (a.legs.some((l) => (pkg ? l.side === 0 : !(l.side > 0)) || typeof l.name !== "string" || typeof l.ask !== "number" || !Number.isFinite(l.ask) || !(l.ask > 0) || (pkg && !(typeof l.bid === "number" && Number.isFinite(l.bid) && l.bid > 0 && l.bid <= l.ask)))) return { error: pkg ? "Every leg needs a two-sided bid and offer on the board." : "Every leg must be a purchase with an offer on the board." };
		if (pkg && !(Number.isInteger(a.lot) && a.lot > 0)) return { error: "The lot size is unknown." };
		const g = group || idNow().slice(4, 20);
		// `ref`: the prices on screen when the trader decided (and when the board last heard them). It is used only to report slippage; it never prices or allows a fill.
		const refOf = (l) => (typeof l.bid === "number" && Number.isFinite(l.bid) && l.bid > 0 && l.bid <= l.ask ? { bid: l.bid, ask: l.ask, ...(Number.isFinite(nowMs) && Number.isFinite(l.age) && l.age >= 0 ? { at: Math.round(nowMs - l.age * 1000) } : {}) } : null);
		if (pkg) {                                                                       // one order: every leg is checked and filled together, or nothing is
			const lotsOf = (l) => (Number.isInteger(l.lots) ? l.lots : a.lots);
			const net = a.legs.reduce((s, l) => s + (l.side > 0 ? limitFor(l.ask) : -Math.max(l.bid - Math.max(3 * TICK, 0.02 * l.bid), 0)) * lotsOf(l) * a.lot, 0);       // the most to pay in total: each bought leg at its limit, each sold leg at the least it may get
			return { orders: [{ id: idNow(), side: "package", legs: a.legs.map((l) => ({ symbol: l.name, side: l.side > 0 ? "buy" : "sell", lots: lotsOf(l), ...(refOf(l) ? { ref: refOf(l) } : {}) })), strategy: flat(strategy), thesis: flat(thesis), net_limit: Math.round(net * 100) / 100, group: g }], package: true };
		}
		return { orders: a.legs.map((l) => ({ id: idNow(), side: "buy", symbol: l.name, lots: Number.isInteger(l.lots) ? l.lots : a.lots, strategy: flat(strategy), thesis: flat(thesis), limit: limitFor(l.ask), group: g, ...(refOf(l) ? { ref: refOf(l) } : {}) })) };
	}
	const sellFor = (symbol) => ({ id: idNow(), side: "sell", symbol, lots: "all" });
	// the structure a review belongs to: if it changes, the review is void and the user must press Review again
	const sigOf = (a) => (a && a.paperOk === true && Array.isArray(a.legs) ? a.lots + "|" + a.legs.map((l) => l.side + ":" + l.name + ":" + (Number.isInteger(l.lots) ? l.lots : a.lots)).join(",") : "");
	return { idNow, flat, thesisOk, stratOk, limitFor, ordersFor, sellFor, sigOf };
})();
// The only three routes this page may call, each with its one method; the request goes to that relative path, on this page's own origin, and nowhere else.
const PAPER_ROUTES = { "/paper/order": "POST", "/paper/kill": "POST", "/paper/state": "GET" };
async function paperSend(fetchFn, key, method, path, body, timeoutMs) {
	if (!key) return { status: 0, body: { error: "no key" } };
	if (!Object.prototype.hasOwnProperty.call(PAPER_ROUTES, path) || PAPER_ROUTES[path] !== method) return { status: 0, body: { error: "not a paper route" } };
	const ac = typeof AbortController !== "undefined" ? new AbortController() : null;
	const timer = ac ? setTimeout(() => ac.abort(), timeoutMs || 15000) : null;
	try {
		const r = await fetchFn(path, { method, headers: { Authorization: "Bearer " + key, ...(body ? { "Content-Type": "application/json" } : {}) }, cache: "no-store", ...(ac ? { signal: ac.signal } : {}), ...(body ? { body: JSON.stringify(body) } : {}) });
		let j = null;
		try { j = await r.json(); } catch (e) { /* no body */ }
		return { status: r.status, body: j && typeof j === "object" ? j : {} };
	} catch (e) { return { status: 0, body: { error: "the request failed or timed out before any answer" } }; }
	finally { if (timer) clearTimeout(timer); }
}
/* @@ticket:end */
async function paperCall(method, path, body) {
	const res = await paperSend((u, o) => fetch(u, o), store("qd.livekey"), method, path, body);
	if (res.status === 401) { try { localStorage.removeItem("qd.livekey"); } catch (e) { /* private mode */ } }
	return res;
}

// ---- the ticket in the Build tab: why, review, send ---------------------------------------------------------------------
// `st` and `rd`: the ticket's own state and redraw when it is not the builder's (the one-contract ticket opened from an option chain).
function bdTicket(a, tpl, st, rd) {
	const B = S.bd, tk = st || (B.tk = B.tk || { strategy: null, thesis: "", stage: "edit", sent: [], busy: false, err: "" });
	const strategy = tk.strategy == null ? tpl.name : tk.strategy;
	const box = h("div", { class: "grp" }, h("div", { class: "pad", style: "font-weight:600" }, "Send as a paper order"));
	const ed = (v) => { if (st) st.editing = v; else B.editing = v; };          // while the reader is typing, a refresh must not rebuild the form under them
	const redraw = rd || (() => { B.editing = false; bdDraw(); });
	const sig = PT.sigOf(a);
	if (tk.sig !== sig) { if (!tk.busy) { tk.sig = sig; tk.stage = "edit"; tk.sent = []; tk.err = ""; } }       // another structure: the old review (and any "sent" screen) is void
	if (!a.paperOk) return put(box, h("div", { class: "f3", style: "font-size:12.5px;padding:2px 16px 12px" }, "Not available: the paper desk could not open this today (see the list above). It stays a what-if."));
	if (tk.stage === "sent") {
		return put(box, tk.sent.map((r) => h("div", { class: "row", style: "padding:6px 16px;gap:8px;align-items:flex-start" }, h("b", { class: r.ok ? "up" : "dn", style: "width:14px" }, r.ok ? "✓" : "✗"), h("span", { style: "font-size:12.5px" }, r.text))),
			h("div", { class: "f3", style: "font-size:12px;padding:4px 16px" }, "Queued orders are carried out by the paper runner within a few seconds, and it may still refuse them. Watch the Positions tab."),
			h("div", { style: "padding:8px 16px 14px;display:flex;gap:10px;flex-wrap:wrap" }, h("button", { class: "btn primary", onclick: () => show("paper") }, "Open Positions"),
				h("button", { class: "btn", onclick: () => { tk.stage = "edit"; tk.thesis = ""; tk.sent = []; redraw(); } }, "Another")));
	}
	const built = PT.ordersFor(a, strategy, tk.thesis, undefined, B.data && typeof B.data.now === "number" ? B.data.now : NaN);
	if (tk.stage === "review" && built.orders) {
		return put(box,
			h("div", { class: "f3", style: "font-size:12px;padding:6px 16px 0" }, `Strategy: ${PT.flat(strategy)}`),
			built.package ? built.orders[0].legs.map((l) => h("div", { class: "row", style: "padding:5px 16px;font-size:12.5px;justify-content:space-between" }, h("span", {}, `${l.side === "buy" ? "Buy" : "Sell"} ${l.lots} lot${l.lots === 1 ? "" : "s"} ${l.symbol}`), h("span", { class: "mono f3" }, l.side === "buy" ? "at the offer" : "at the bid")))
				.concat([h("div", { class: "f3", style: "font-size:12px;line-height:1.55;padding:6px 16px" }, `One package: every leg is opened together or none is. The most you will pay in total is ${num(built.orders[0].net_limit)} (a negative number is a credit you insist on). A sold option can lose more than it earns: the desk refuses any package whose worst case is not bounded or does not fit the risk limits.`)]) :
			built.orders.map((o) => h("div", { class: "row", style: "padding:5px 16px;font-size:12.5px;justify-content:space-between" }, h("span", {}, `Buy ${o.lots} lot${o.lots === 1 ? "" : "s"} ${o.symbol}`), h("span", { class: "mono f3" }, `at most ${num(o.limit)}`))),
			h("div", { class: "f3", style: "font-size:12px;line-height:1.55;padding:6px 16px" }, "A buy fills at the offer plus 0 to 3 ticks, more the bigger it is against the size shown; the Paper tab keeps the price you saw against what you paid."),
			h("div", { class: "f3", style: "font-size:12px;line-height:1.55;padding:6px 16px" }, `Most you can lose, at the offers shown: ${inr(a.maxLoss)} plus ${inr(a.entryFees)} of fees; a fill can be a little dearer, up to the limits above. Paper money. "${PT.flat(tk.thesis)}"`),
			tk.err ? h("div", { class: "warn", style: "font-size:12.5px;padding:2px 16px" }, tk.err) : null,
			h("div", { style: "padding:8px 16px 14px;display:flex;gap:10px;flex-wrap:wrap" },
				h("button", { class: "btn primary", disabled: tk.busy, onclick: async (ev) => {
					if (tk.busy) return;                                                              // a second tap while the first is still going does nothing
					if (ev && ev.currentTarget) ev.currentTarget.disabled = true;
					tk.busy = true; tk.err = ""; tk.sent = [];
					for (const o of built.orders) {
						const r = await paperCall("POST", "/paper/order", o);
						tk.sent.push({ ok: r.status === 200, text: r.status === 200 ? `${o.symbol}: queued` : `${o.symbol}: not queued (${(r.body && r.body.error) || "HTTP " + r.status})` });
						if (r.status !== 200) break;                                                   // a refused first leg must not leave a second one going alone
					}
					tk.busy = false; tk.stage = "sent"; redraw();
				} }, tk.busy ? "Sending…" : "Send paper order"),
				h("button", { class: "btn", disabled: tk.busy, onclick: () => { tk.stage = "edit"; redraw(); } }, "Back")));
	}
	const inp = h("input", { type: "text", class: "search", maxlength: "60", "aria-label": "Strategy name", value: strategy, oninput: (e) => { tk.strategy = e.target.value; } });
	const ta = h("textarea", { class: "search", rows: "3", maxlength: "1000", "aria-label": "Thesis: why this trade, now", placeholder: "Why this trade, now? What would make you wrong?", style: "width:100%;resize:vertical;font:inherit", oninput: (e) => { tk.thesis = e.target.value; const ok = PT.thesisOk(tk.thesis); cnt.textContent = ok ? "Thesis written." : `${PT.flat(tk.thesis).length} of at least 20 characters`; rv.disabled = !(PT.stratOk(tk.strategy == null ? tpl.name : tk.strategy) && ok); }, onfocus: () => { ed(true); }, onblur: () => { ed(false); } }, tk.thesis);
	const cnt = h("div", { class: "f3", style: "font-size:11.5px;padding:2px 0" }, PT.thesisOk(tk.thesis) ? "Thesis written." : `${PT.flat(tk.thesis).length} of at least 20 characters`);
	const rv = h("button", { class: "btn primary", disabled: !!built.error, onclick: () => { tk.stage = "review"; tk.err = ""; redraw(); } }, "Review order");
	inp.addEventListener("focus", () => { ed(true); }); inp.addEventListener("blur", () => { ed(false); });
	return put(box, h("div", { style: "padding:2px 16px 14px;display:flex;flex-direction:column;gap:8px" },
		h("label", { class: "f3", style: "font-size:12px" }, "Strategy name"), inp, h("label", { class: "f3", style: "font-size:12px" }, "Thesis (required: it is kept with the trade)"), ta, cnt, rv));
}

// ---- the ticket for one contract, opened by a tap on its price in an option chain: what it is quoted at, what one or more lots would cost and could lose, whether the paper
// desk can open it, and then the same why / review / send as the builder's ticket. It follows the live price while it is open, except under the reader's fingers.
S.tk = null;
function tkOpen(name) {
	const o = liveOpt(name);
	if (!o) return;
	const box = h("div", {});
	openSheet(`${o.u} ${num(o.k, 0)} ${o.t === "CE" ? "call" : "put"} · ${o.e.slice(0, 2)} ${cap(o.e.slice(2, 5).toLowerCase())}`, box);
	S.tk = { name, o, lots: 1, box, strategy: null, thesis: "", stage: "edit", sent: [], busy: false, err: "", editing: false };
	tkDraw();
}
function tkDraw() {
	const K = S.tk, B = S.bd, data = B.data;
	if (!K || K.editing || K.busy || !data) return;
	const o = K.o, c = QB.conf(), q = data.quotes[K.name], n = liveNames(o.u, data.quotes), sq = data.quotes[n.spot] || data.quotes[n.fut] || {}, inst = c.inst[o.u];
	K.box.textContent = "";
	if (!q) return void put(K.box, h("div", { class: "note" }, K.name + " is no longer on the board."));
	const T = QB.yearsTo(o.e, Date.now()), redraw = () => { K.editing = false; tkDraw(); };
	const a = QB.analyze({ u: o.u, exp: o.e, legs: [{ side: 1, type: o.t, strike: o.k, name: K.name }], quotes: data.quotes, spot: sq.ltp, spotAge: sq.age_s, ageAdd: Math.max(0, (Date.now() - (B.at || Date.now())) / 1000), T, lots: K.lots });
	const leg = a.legs[0], cell = (k, v, cl) => h("div", {}, h("span", {}, k), h("b", { class: "mono " + (cl || "") }, v));
	put(K.box,
		h("div", { class: "kstrip", style: "margin:0 -16px;border-top:1px solid var(--line)" }, cell("Last", livePx(q.ltp, "opt")), cell("Bid", fin(q.bid) ? livePx(q.bid, "opt") : "—", "up"), cell("Offer", fin(q.ask) ? livePx(q.ask, "opt") : "—", "dn"), cell("Change", fin(q.chg) ? signed(q.chg) + "%" : "—", cls(q.chg))),
		h("div", { class: "kstrip", style: "margin:0 -16px" }, cell("Open interest", fin(q.oi) ? LIVE_VOL.format(q.oi) : "—"), cell("Volume", fin(q.vol) ? LIVE_VOL.format(q.vol) : "—"), cell("Implied volatility", fin(leg.iv) ? (leg.iv * 100).toFixed(1) + "%" : "—"), cell(o.u, fin(sq.ltp) ? livePx(sq.ltp, "idx") : "—")),
		h("div", { class: "f3", style: "font-size:11.5px;padding:8px 0 0" }, `Heard ${liveAge(q.age_s)} ago${SRC_NAME[q.src] ? " from " + SRC_NAME[q.src] : ""}.`));
	if (!inst) return void put(K.box, h("div", { class: "note" }, `${o.u} options are shown for reading only: the paper desk has no verified lot size or costs for ${o.u}.`));
	if (inst.physical) put(K.box, h("div", { class: "f3", style: "font-size:11.5px;line-height:1.5;padding:6px 0 0" }, "A stock option is settled by delivery of the shares: the paper desk sells it from 15:20 on the trading day before its expiry, and does not buy it after that."));
	if (inst.prior_day) put(K.box, h("div", { class: "f3", style: "font-size:11.5px;line-height:1.5;padding:6px 0 0" }, `${inst.segment === "mcx" ? "An MCX option turns into the future at expiry" : "A currency option expires at 12:30"}: the paper desk sells it from 15:20 on the trading day before its expiry, and does not buy it after that. Priced off the near-month future.`));
	const lot = inst.lots ? inst.lots[o.e] : inst.lot;
	if (!lot) return void put(K.box, h("div", { class: "note" }, `${o.u} has no verified lot size for the ${o.e} expiry yet (paper.stock_options.lots in the config), so this contract is shown for reading only.`));
	put(K.box, h("div", { class: "row", style: "justify-content:space-between;align-items:center;padding:14px 0 10px" }, h("span", {}, `Lots (${lot} units each)`),
		h("span", { style: "display:flex;gap:10px;align-items:center" }, h("button", { class: "btn sq", "aria-label": "fewer lots", onclick: () => { K.lots = Math.max(1, K.lots - 1); redraw(); } }, "−"), h("b", { class: "mono", style: "min-width:28px;text-align:center" }, String(K.lots)),
			h("button", { class: "btn sq", "aria-label": "more lots", onclick: () => { K.lots = Math.min(c.limits.max_lots, K.lots + 1); redraw(); } }, "+"))));
	if (a.errors.length) return void put(K.box, h("div", { class: "note warn" }, a.errors[0]));
	put(K.box,
		h("div", { class: "kstrip", style: "margin:0 -16px;border-top:1px solid var(--line)" }, cell("You pay", inr(Math.abs(a.premium))), cell("Most you can lose", inr(a.maxLoss + a.entryFees), "dn"), cell("Break-even", a.breakevens.map((b) => num(b, 0)).join(" · ") || "—"), cell("Fees in and out", inr(a.fees))),
		a.paperOk ? null : h("div", { style: "padding:10px 0 0" }, h("div", { class: "lbl", style: "margin-bottom:4px" }, "Why the paper desk would not open this now"),
			a.paperChecks.filter((x) => !x.ok).map((x) => h("div", { class: "row", style: "padding:4px 0;gap:8px;align-items:flex-start" }, h("b", { class: "dn", style: "width:14px" }, "✗"), h("span", { style: "font-size:12.5px" }, x.text)))),
		h("div", { style: "margin-top:12px" }, bdTicket(a, { name: o.t === "CE" ? "Long call" : "Long put" }, K, redraw)));
}

// ---- the futures ticket: an MCX or currency future, Buy or Short, lots, a stop (required) and a target. The runner's gate decides (quantdesk/paper/risk.py check_future); this shows the numbers. ----
function ftContract(name) {
	const m = /^([A-Z][A-Z0-9&]{1,20})-(MCX|CDS)$/.exec(String(name || "")), f = QB.conf().futures;
	if (!m || !f || !f.contracts) return null;
	const c = f.contracts[m[1]];
	return c && c.segment === (m[2] === "MCX" ? "mcx" : "nse_cds") ? { u: m[1], ...c } : null;
}
function ftOpen(name) {
	const c = ftContract(name);
	if (!c) return;
	const box = h("div", {}), calc = h("div", {}), act = h("div", {});
	S.tk = null;
	S.ft = { name, c, side: "buy", lots: 1, stop: "", target: "", strategy: "", thesis: "", box, calc, act, stage: "edit", sent: null, busy: false, err: "" };
	const F = S.ft, num_ = (v) => { const x = parseFloat(String(v).replace(/,/g, "")); return Number.isFinite(x) && x > 0 ? x : null; };
	const sideBtn = (k, t) => h("button", { class: "btn" + (F.side === k ? " primary" : ""), "data-side": k, "aria-pressed": String(F.side === k), onclick: () => { F.side = k; F.stage = "edit"; box.querySelectorAll("[data-side]").forEach((b) => { b.classList.toggle("primary", b.dataset.side === k); b.setAttribute("aria-pressed", String(b.dataset.side === k)); }); ftCalc(); } }, t);
	const field = (lbl, key, ph) => h("label", { class: "row", style: "justify-content:space-between;align-items:center;gap:10px;padding:6px 0" }, h("span", {}, lbl),
		h("input", { class: "mono", inputmode: "decimal", placeholder: ph, style: "width:140px;text-align:right", oninput: (e) => { F[key] = e.target.value; F.stage = "edit"; ftCalc(); } }));
	const lotsB = h("b", { class: "mono", style: "min-width:28px;text-align:center" }, "1");
	put(box,
		h("div", { class: "f3", style: "font-size:12px;line-height:1.5;padding:2px 0 8px" }, `${c.segment === "mcx" ? "MCX" : "NSE currency"} near-month future · ${c.lot} units a lot, priced ${c.unit} · margin ${(c.margin * 100).toFixed(1)}% · paper money only`),
		h("div", { style: "display:flex;gap:8px;padding:4px 0 8px" }, sideBtn("buy", "Buy (long)"), sideBtn("short", "Sell (short)")),
		h("div", { class: "row", style: "justify-content:space-between;align-items:center;padding:6px 0" }, h("span", {}, "Lots"),
			h("span", { style: "display:flex;gap:10px;align-items:center" },
				h("button", { class: "btn sq", "aria-label": "fewer lots", onclick: () => { F.lots = Math.max(1, F.lots - 1); F.stage = "edit"; lotsB.textContent = String(F.lots); ftCalc(); } }, "−"), lotsB,
				h("button", { class: "btn sq", "aria-label": "more lots", onclick: () => { F.lots = Math.min(100, F.lots + 1); F.stage = "edit"; lotsB.textContent = String(F.lots); ftCalc(); } }, "+"))),
		field("Stop (required)", "stop", "price"), field("Target (optional)", "target", "price"),
		calc,
		h("label", { style: "display:block;padding:8px 0 4px" }, h("span", { class: "lbl" }, "Strategy"), h("input", { style: "width:100%", maxlength: "60", placeholder: "e.g. crude breakout", oninput: (e) => { F.strategy = e.target.value; F.stage = "edit"; ftCalc(); } })),
		h("label", { style: "display:block;padding:4px 0" }, h("span", { class: "lbl" }, "Thesis: why this trade, now"), h("textarea", { style: "width:100%;min-height:64px", maxlength: "1000", oninput: (e) => { F.thesis = e.target.value; F.stage = "edit"; ftCalc(); } })),
		act,
		h("div", { class: "f3", style: "font-size:11.5px;line-height:1.55;padding:6px 0 0" }, `Intraday only: the desk closes every futures position ${QB.conf().futures.square_off_min || 5} minutes before the ${c.segment === "mcx" ? "MCX" : "currency"} close, and takes no new one in the last ${QB.conf().futures.entry_cutoff_min || 15} minutes or in a contract's last ${c.no_entry_days} trading day${c.no_entry_days === 1 ? "" : "s"}. The stop and the target are watched by the runner and closed at the bid (long) or the offer (short).`));
	openSheet(`${c.u} future · paper`, box);
	F.num = num_;
	ftCalc();
}
function ftCalc() {
	const F = S.ft, B = S.bd, data = B && B.data;
	if (!F) return;
	const q = data && data.quotes ? data.quotes[F.name] : null, c = F.c, conf = QB.conf(), cell = (k, v, cl) => h("div", {}, h("span", {}, k), h("b", { class: "mono " + (cl || "") }, v));
	F.calc.textContent = "";
	if (!q || !fin(q.bid) || !fin(q.ask)) { F.act.textContent = ""; return void put(F.calc, h("div", { class: "note warn" }, `${F.name} has no two-sided price on the board right now.`)); }
	const short = F.side === "short", px = short ? q.bid : q.ask, qty = F.lots * c.lot, stop = F.num(F.stop), target = F.num(F.target);
	const costs = (conf.futures.costs || {})[c.segment === "mcx" ? "mcx_futures" : "cds_futures"] || {}, cc = conf.costs || {};
	const fee = (buy, price) => { const t = qty * price, br = Math.min(cc.brokerage_per_order || 20, 0.0003 * t), ex = t * (costs.exchange || 0), sebi = t * (cc.sebi_per_crore || 10) / 1e7;
		return br + t * (buy ? costs.stt_buy || 0 : costs.stt_sell || 0) + ex + sebi + (buy ? t * (costs.stamp_buy || 0) : 0) + (cc.gst || 0.18) * (br + ex + sebi); };
	const eq = S.pp && S.pp.data && S.pp.data.summary && fin(S.pp.data.summary.equity) ? S.pp.data.summary.equity : conf.equity;
	const why = [];
	if (stop === null) why.push("Set a stop: every futures entry needs one.");
	else if (short ? stop <= px : stop >= px) why.push(`The stop must be ${short ? "above" : "below"} the ${short ? "bid" : "offer"} ${num(px)}.`);
	else if (Math.abs(px - stop) / px > (conf.futures.stop_max_pct || 0.1)) why.push(`The stop is ${(Math.abs(px - stop) / px * 100).toFixed(1)}% away: that looks like a typo.`);
	if (target !== null && (short ? target >= px : target <= px)) why.push(`The target must be ${short ? "below" : "above"} the entry.`);
	const risk = stop === null ? null : qty * (Math.abs(px - stop) + 0.001 * px) + fee(!short, px) + fee(short, stop), margin = qty * px * c.margin;
	const rr = stop !== null && target !== null ? Math.abs(target - px) / Math.abs(px - stop) : null;
	if (fin(risk) && risk > conf.paper.risk_per_trade * eq) why.push(`It risks ${inr(risk)} to the stop: over ${(conf.paper.risk_per_trade * 100).toFixed(1)}% of equity (${inr(conf.paper.risk_per_trade * eq)}). A closer stop or fewer lots.`);
	if (margin > eq) why.push(`It needs ${inr(margin)} of margin: more than the account's equity.`);
	put(F.calc,
		h("div", { class: "kstrip", style: "margin:6px -16px 0;border-top:1px solid var(--line)" }, cell("Bid", num(q.bid), "up"), cell("Offer", num(q.ask), "dn"), cell(short ? "You sell at" : "You buy at", num(px)), cell("Heard", liveAge(q.age_s) + " ago")),
		h("div", { class: "kstrip", style: "margin:0 -16px" }, cell("Risk to the stop", fin(risk) ? inr(risk) : "—", "dn"), cell("Margin", inr(margin)), cell("Target gain", fin(target) && stop !== null ? inr(qty * Math.abs(target - px)) : "—", "up"), cell("Reward:risk", fin(rr) ? rr.toFixed(1) : "—")),
		why.length ? h("div", { style: "padding:8px 0 0" }, why.map((x) => h("div", { class: "row", style: "padding:3px 0;gap:8px;align-items:flex-start" }, h("b", { class: "dn", style: "width:14px" }, "✗"), h("span", { style: "font-size:12.5px" }, x)))) : null);
	const okText = PT.stratOk(F.strategy) && PT.thesisOk(F.thesis);
	F.act.textContent = "";
	if (F.sent) return void put(F.act, h("div", { class: "note" }, `Queued ${F.sent}: the runner fills it at the ${short ? "bid" : "offer"} if its gate allows. Watch Positions.`));
	if (F.err) put(F.act, h("div", { class: "note warn" }, F.err));
	if (why.length || !okText || F.stage !== "review") {                       // step one: review (any change to the ticket comes back here)
		F.stage = "edit";
		return void put(F.act, h("button", { class: "btn primary", style: "width:100%;margin-top:10px", disabled: why.length || !okText ? "" : null, onclick: () => { if (!why.length && okText) { F.stage = "review"; ftCalc(); } } },
			okText ? "Review order" : "Name the strategy and write the thesis (20+ characters)"));
	}
	const o = { id: PT.idNow(), side: short ? "short" : "buy", symbol: F.name, lots: F.lots, stop, ...(target !== null ? { target } : {}), strategy: PT.flat(F.strategy), thesis: PT.flat(F.thesis),
		ref: { bid: q.bid, ask: q.ask, ...(typeof data.now === "number" && fin(q.age_s) ? { at: Math.round(data.now - q.age_s * 1000) } : {}) } };
	put(F.act, h("div", { class: "note", style: "margin-top:10px" }, `${short ? "Sell short" : "Buy"} ${F.lots} lot${F.lots === 1 ? "" : "s"} of ${F.name} at about ${num(px)}, stop ${num(stop)}${target !== null ? ", target " + num(target) : ""}. Risk to the stop about ${inr(risk)}; margin ${inr(margin)}. Paper money.`),
		h("div", { style: "display:flex;gap:8px;margin-top:8px" },
			h("button", { class: "btn", onclick: () => { F.stage = "edit"; ftCalc(); } }, "Back"),
			h("button", { class: "btn primary", style: "flex:1", disabled: F.busy ? "" : null, onclick: async (ev) => {          // step two: the send, only from the review
				if (F.busy || F.stage !== "review") return;
				F.busy = true;
				if (ev && ev.currentTarget) ev.currentTarget.disabled = true;
				const r = await paperCall("POST", "/paper/order", o);
				F.busy = false;
				if (r.status === 200) F.sent = `${short ? "a short" : "a buy"} of ${F.lots} lot${F.lots === 1 ? "" : "s"}`; else { F.err = "Not queued (" + ((r.body && r.body.error) || "HTTP " + r.status) + ")."; F.stage = "edit"; }
				ftCalc();
			} }, `Send: ${short ? "sell short" : "buy"} ${F.lots} lot${F.lots === 1 ? "" : "s"} (paper)`)));
}
// ---- the Paper tab: the account, the orders, the positions, the kill switch --------------------------------------------------------
S.pp = { data: null, busy: false, confirm: null, confirmAt: 0, acting: false, kill: false, note: "" };
function ppAge(summary) { return summary && summary.asof ? (Date.now() - Date.parse(summary.asof)) / 1000 : NaN; }
function ppDraw() {
	const P = S.pp, body = $("#pp-body"), d = P.data;
	if (P.confirm && !(Date.now() - P.confirmAt < 30000)) P.confirm = null;                         // a half-made "are you sure" does not wait for hours
	body.textContent = "";
	const sm = d && d.summary;
	const kv = (k, v, cl) => h("div", { class: "row", style: "justify-content:space-between;padding:7px 16px;border-top:1px solid var(--line)" }, h("span", { class: "f3" }, k), h("b", { class: "mono " + (cl || "") }, v));
	const cell = (k, v, cl) => h("div", {}, h("span", {}, k), h("b", { class: "mono " + (cl || "") }, v));
	const age = ppAge(sm);
	const tagC = (k, t) => h("span", { class: "tag " + k }, t);
	if (!sm) put(body, h("div", { class: "banner warn" }, icon("alert"), "The paper runner has not reported yet. Orders wait two minutes, then expire. It starts by itself on trading days from about 08:30."));
	else if (inSession() && !(age < 45)) put(body, h("div", { class: "banner warn" }, icon("alert"), `The paper runner last reported ${liveAge(age)} ago. If it is not running, orders will expire unfilled.`));
	if (sm && sm.stuck && sm.stuck.length) put(body, h("div", { class: "banner warn" }, icon("alert"), `Held past expiry with no price: ${sm.stuck.join(", ")}. New orders are refused until this is settled.`));
	if (sm && sm.day_halted) put(body, h("div", { class: "banner err" }, icon("stop"), "Stopped for today: the daily loss limit was hit."));
	if (sm && sm.halt) put(body, h("div", { class: "banner err" }, icon("stop"), "Drawdown halt is ON: only the owner clears it."));
	if (P.note) put(body, h("div", { class: "banner warn" }, icon("alert"), P.note));
	const pos = sm && sm.positions ? sm.positions : [], day = sm && fin(sm.equity) && fin(sm.day_start) ? sm.equity - sm.day_start : null;
	if (sm) put(body, h("div", { class: "grp" },
		h("div", { class: "sec-h" }, h("h2", {}, "Paper account"), h("span", { class: "hint" }, sm.asof ? "as of " + ist(sm.asof) : "")),
		h("div", { class: "acct" }, h("div", {}, h("span", { class: "k" }, "Equity"), h("div", { class: "eq mono" }, fin(sm.equity) ? inr(sm.equity) : "unknown (a position has no price)")),
			h("div", { class: "day mono " + cls(day) }, h("span", { class: "k" }, "Today"), fin(day) ? inr(day, true) : "—")),
		h("div", { class: "kstrip" }, cell("Profit since the start", fin(sm.net_pnl) ? inr(sm.net_pnl, true) : "—", fin(sm.net_pnl) ? (sm.net_pnl >= 0 ? "up" : "dn") : ""), cell("Cash", inr(sm.cash)), cell("Fees paid", inr(sm.fees)), cell("Open positions", String(pos.length)))));
	if (sm && Array.isArray(sm.reviews) && sm.reviews.length) put(body, ppReview(sm.reviews));
	if (sm && sm.lab && sm.lab.plan && typeof sm.lab.plan === "object") put(body, ppPlan(sm.lab.plan));
	if (sm && sm.lab && typeof sm.lab === "object") put(body, ppLab(sm.lab));
	put(body, h("div", { class: "grp" }, h("div", { class: "sec-h" }, h("h2", {}, `Positions (${pos.length})`)),
		pos.length ? pos.map((p) => h("div", { class: "pad", style: "border-top:1px solid var(--line)" },
			h("div", { class: "row", style: "justify-content:space-between;align-items:center;gap:8px" }, h("b", { class: "mono", style: "font-size:13px" }, p.symbol),
				h("span", { class: "mono " + (fin(p.pnl) ? (p.pnl >= 0 ? "up" : "dn") : "f3"), style: "font-size:15px" }, fin(p.pnl) ? inr(p.pnl, true) : "no price")),
			h("div", { class: "f3", style: "font-size:12px;line-height:1.5" }, p.kind === "future"
				? `${p.qty < 0 ? "Short" : "Long"} ${Math.abs(p.lots)} lot${Math.abs(p.lots) === 1 ? "" : "s"} (${Math.abs(p.qty)} units) at ${num(p.avg)} · ${p.qty < 0 ? "offer" : "bid"} ${fin(p.mark) ? num(p.mark) : "—"} · stop ${fin(p.stop) ? num(p.stop) : "—"}${fin(p.target) ? " · target " + num(p.target) : ""} · intraday (${p.segment === "mcx" ? "MCX" : "currency"}) · ${p.strategy || ""}`
				: `${p.lots} lot${p.lots === 1 ? "" : "s"} (${p.qty} units) · bought at ${num(p.avg)} · bid ${fin(p.mark) ? num(p.mark) : "—"} · expires ${p.expiry || "?"} · ${p.strategy || ""}`),
			h("div", { class: "f3", style: "font-size:12px;line-height:1.5;margin-top:2px" }, p.thesis || ""),
			P.confirm === "sell:" + p.symbol ? h("div", { style: "display:flex;gap:8px;margin-top:8px" },
				h("button", { class: "btn danger", onclick: async (ev) => { if (P.acting) return; P.acting = true; if (ev && ev.currentTarget) ev.currentTarget.disabled = true; P.confirm = null; const o = PT.sellFor(p.symbol); const r = await paperCall("POST", "/paper/order", o); P.acting = false; P.note = r.status === 200 ? "" : "The sell was not queued (" + ((r.body && r.body.error) || "HTTP " + r.status) + ")."; renderPaper(true); } }, p.kind === "future" ? (p.qty < 0 ? "Yes, buy it back at the offer" : "Yes, sell it at the bid") : "Yes, sell all at the bid"),
				h("button", { class: "btn", onclick: () => { P.confirm = null; ppDraw(); } }, "Cancel"))
				: h("div", { style: "display:flex;gap:8px;margin-top:8px" }, h("button", { class: "btn", onclick: () => { P.confirm = "sell:" + p.symbol; P.confirmAt = Date.now(); ppDraw(); } }, p.kind === "future" ? "Close" : "Sell all"),
					p.kind === "future" ? null : h("button", { class: "btn", onclick: () => { show("live"); liveOpen(p.symbol); } }, "Open the chain"))))
			: h("div", { class: "f3", style: "font-size:12.5px;padding:2px 16px 14px" }, "Nothing held. Open an instrument on Markets, go to Options and tap a price to make a paper order.")));
	const pend = d && d.pending ? d.pending : [], res = d && d.results ? d.results.slice(-10).reverse() : [];
	put(body, h("div", { class: "grp" }, h("div", { class: "sec-h" }, h("h2", {}, "Orders"), h("span", { class: "hint" }, pend.length ? pend.length + " waiting" : "the last ten")),
		pend.map((o) => h("div", { class: "row", style: "padding:8px 16px;font-size:12.5px;justify-content:space-between;border-top:1px solid var(--line)" }, h("span", { class: "mono" }, `${o.side} ${o.lots} ${o.symbol}`), tagC("warn", "waiting"))),
		res.map((r) => h("div", { style: "padding:8px 16px;border-top:1px solid var(--line)" },
			h("div", { class: "row", style: "justify-content:space-between;font-size:12.5px" }, h("span", { class: "mono" }, r.fill && r.fill.symbol ? `${r.fill.kind || ""} ${r.fill.qty || ""} ${r.fill.symbol}` : r.id), tagC(r.status === "filled" ? "bull" : r.status === "done" ? "flat" : "bear", r.status)),
			r.fill && fin(r.fill.price) ? h("div", { class: "f3", style: "font-size:12px" }, `at ${num(r.fill.price)} · fees ${fin(r.fill.fees) ? num(r.fill.fees) : "—"}`) : null,
			(r.reasons || []).map((x) => h("div", { class: "f3", style: "font-size:12px;line-height:1.5" }, x)))),
		!pend.length && !res.length ? h("div", { class: "f3", style: "font-size:12.5px;padding:2px 16px 14px" }, "No orders yet.") : null));
	if (sm) put(body, fold("pp-risk", "Loss limits", "where the desk stops by itself", h("div", { class: "panel", style: "margin:0;border:0" },
		kv("Stops for the day below", fin(sm.day_floor) ? inr(sm.day_floor) : "—"), kv("Halts below", fin(sm.dd_floor) ? inr(sm.dd_floor) : "—"),
		sm.day_halted ? kv("Today", "stopped: the daily loss limit was hit", "dn") : null, sm.halt ? kv("Drawdown halt", "ON: only the owner clears it", "dn") : null)));
	const sl = sm && sm.slippage;
	if (sl && sl.fills > 0) {
		const bpsTxt = fin(sl.bps) ? `${sl.bps} bps of the value traded` : "";
		put(body, fold("pp-slip", "Slippage", `${sl.fills} fill${sl.fills === 1 ? "" : "s"} · ${inr(sl.total_inr)}`, h("div", { class: "grp" }, h("div", { class: "pad", style: "font-weight:600" }, `Slippage (${sl.fills} fill${sl.fills === 1 ? "" : "s"})`),
			kv("Total cost vs the price you saw", inr(sl.total_inr), sl.total_inr > 0 ? "dn" : ""), kv("Spread paid (measured)", inr(sl.spread_inr)),
			kv(`Price moved before the fill (measured, ${sl.fills_with_decision_price} of ${sl.fills})`, inr(sl.delay_inr, true)), kv("Size impact (a model, not measured)", inr(sl.impact_inr)),
			bpsTxt ? h("div", { class: "f3", style: "font-size:12px;padding:4px 16px" }, bpsTxt) : null,
			(d.summary.slips || []).slice().reverse().map((r) => h("div", { class: "row", style: "padding:4px 16px;font-size:12px;justify-content:space-between;gap:8px;border-top:1px solid var(--line)" },
				h("span", { class: "mono" }, `#${r.seq} ${r.side} ${r.symbol || ""}`), h("span", { class: "mono f3" }, `${fin(r.total_inr) ? inr(r.total_inr) : "—"}${fin(r.delay_s) ? " · " + r.delay_s + "s" : ""}${r.impact_ticks ? " · +" + r.impact_ticks + " tick" + (r.impact_ticks === 1 ? "" : "s") : ""}`))),
			h("div", { class: "f3", style: "font-size:11.5px;line-height:1.55;padding:6px 16px 12px" }, "Positive is a cost. The spread and the price move come from the live board. The size impact is a conservative model (the board shows only the best price and its size) and is shown apart so it is never mistaken for an observation."))));
	}
	const tail = sm && sm.ledger_tail ? sm.ledger_tail.slice(-10).reverse() : [];
	put(body, fold("pp-ledger", "Ledger", `${sm ? sm.ledger_len : 0} rows, ${sm && sm.ledger_ok ? "chain verified" : "NOT verified"}`, h("div", { class: "grp" }, h("div", { class: "pad", style: "font-weight:600" }, `Ledger (${sm ? sm.ledger_len : 0} rows, ${sm && sm.ledger_ok ? "chain verified" : "NOT verified"})`),
		tail.map((r) => h("div", { class: "row", style: "padding:4px 16px;font-size:12px;justify-content:space-between;gap:8px" }, h("span", { class: "mono" }, `#${r.seq} ${r.kind}${r.symbol ? " " + r.symbol : ""}`), h("span", { class: "mono f3" }, fin(r.price) ? `${r.qty} @ ${num(r.price)}` : ""))),
		!tail.length ? h("div", { class: "f3", style: "font-size:12.5px;padding:2px 16px 12px" }, "Empty.") : null)));
	const killOn = d ? d.kill === true : false;
	put(body, h("div", { class: "panel pad", style: "display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-top:8px" },
		h("b", {}, "Kill switch"), killOn ? tagC("bear", "ON: nothing opens, everything is sold") : tagC("bull", "off"),
		P.confirm === (killOn ? "kill:off" : "kill:on") ? h("span", { style: "display:flex;gap:8px" }, h("button", { class: "btn danger", onclick: async (ev) => { if (P.acting) return; P.acting = true; if (ev && ev.currentTarget) ev.currentTarget.disabled = true; P.confirm = null; const r = await paperCall("POST", "/paper/kill", { on: !killOn }); P.acting = false; P.note = r.status === 200 ? "" : "The kill switch could not be changed (" + ((r.body && r.body.error) || "HTTP " + r.status) + ")."; renderPaper(true); } }, killOn ? "Yes, resume trading" : "Yes, stop and sell everything"), h("button", { class: "btn", onclick: () => { P.confirm = null; ppDraw(); } }, "Cancel"))
			: h("button", { class: "btn" + (killOn ? "" : " danger"), style: "margin-left:auto", onclick: () => { P.confirm = killOn ? "kill:off" : "kill:on"; P.confirmAt = Date.now(); ppDraw(); } }, killOn ? "Resume trading" : "Stop all trading and sell everything")),
		h("div", { class: "note" }, "Paper money only. Orders are carried out by the paper runner through the risk gate: the gate, not this page, decides. Nothing here can reach a broker."));
}
// The session review (quantdesk/paper/review.py): what the account did on a day, from its own ledger. Today's whole-day result includes what is still held; an earlier day's is
// realized profit less fees, because the ledger keeps no closing marks for it, and the panel says which it is showing.
const KIND_WORD = { buy: "Bought", sell: "Sold", sto: "Sold to open", btc: "Bought back", settle: "Settled" };
function ppReview(reviews) {
	const P = S.pp, pick = reviews.find((r) => r.day === P.revDay) || reviews[0];
	P.revDay = pick.day;
	const dayName = (d) => new Date(d + "T00:00:00Z").toLocaleDateString("en-IN", { timeZone: "UTC", weekday: "short", day: "2-digit", month: "short" });
	const cell = (k, v, cl) => h("div", {}, h("span", {}, k), h("b", { class: "mono " + (cl || "") }, v));
	const whole = fin(pick.equity_change), head = whole ? pick.equity_change : pick.net;
	const box = h("div", { class: "grp" },
		h("div", { class: "sec-h" }, h("h2", {}, "Session review"), h("span", { class: "hint" }, pick.today ? (inSession() ? "today so far" : "today") : dayName(pick.day))),
		reviews.length > 1 ? h("div", { class: "chips", style: "padding:8px 16px" }, reviews.map((r) => h("button", { class: "chip", "aria-pressed": String(r.day === pick.day), onclick: () => { P.revDay = r.day; ppDraw(); } }, r.today ? "Today" : dayName(r.day)))) : null,
		h("div", { class: "kstrip" },
			cell(whole ? "Day's result (all in)" : "Closed trades, after fees", inr(head, true), cls(head)), cell("Realized", inr(pick.realized, true), cls(pick.realized)),
			cell("Fees", inr(pick.fees)), cell("Trades closed", pick.closes ? `${pick.closes} (${pick.wins} won, ${pick.losses} lost)` : "none")),
		pick.closes ? h("div", { class: "kstrip" }, cell("Best close", inr(pick.best, true), cls(pick.best)), cell("Worst close", inr(pick.worst, true), cls(pick.worst)),
			cell("Opened", String((pick.opened || []).length)), cell("Still held", pick.today ? String((pick.still_open || []).length) : "—")) : null,
		(pick.events || []).map((e) => h("div", { class: "banner warn", style: "margin:0" }, icon("alert"), e)),
		pick.fills.length ? h("div", { class: "rows" }, pick.fills.slice().reverse().map((f) => h("div", { class: "pad", style: "border-top:1px solid var(--line)" },
			h("div", { class: "row", style: "justify-content:space-between;gap:8px;font-size:12.5px" }, h("span", { class: "mono" }, `${f.t} ${KIND_WORD[f.kind] || f.kind} ${f.qty} ${f.symbol}`),
				h("span", { class: "mono " + (f.pnl == null ? "f3" : cls(f.pnl - f.fees)) }, f.pnl == null ? `at ${num(f.price)}` : inr(f.pnl - f.fees, true))),
			f.thesis ? h("div", { class: "f3", style: "font-size:12px;line-height:1.5;margin-top:2px" }, (f.strategy ? f.strategy + ": " : "") + f.thesis) : null)))
			: h("div", { class: "f3", style: "font-size:12.5px;padding:10px 16px 14px" }, pick.today ? "No trades yet today." : "No trades that day."),
		h("div", { class: "f3", style: "font-size:11.5px;line-height:1.5;padding:8px 16px 12px" }, whole
			? "The day's result is the account's equity against where it started the day: closed trades, fees and the change in what is still held, together. A close's figure is after its own fees."
			: "For an earlier day the panel shows closed trades less fees only: the ledger keeps no closing price for what was still held that evening. A close's figure is after its own fees."));
	return box;
}
// AUTO v2's Strategy lab (quantdesk/paper/auto2.py): every strategy it has written is traded in shadow at the real prices; the ones with a record go live. Display only.
// The day plan (AUTO v2, 06:00 to 09:15): what the open will look for, priced on last night's closing books, with its reasons. Trades only through the lab's proof gate.
function ppPlan(dp) {
	const items = Array.isArray(dp.items) ? dp.items : [], notes = Array.isArray(dp.notes) ? dp.notes : [];
	const word = (v) => (v === "up" ? "▲ up" : v === "down" ? "▼ down" : v === "flat" ? "◆ flat" : "—");
	const when = String(dp.built_at || "").slice(11, 16);
	return h("div", { class: "grp" },
		h("div", { class: "sec-h" }, h("h2", {}, "Day plan"), h("span", { class: "hint" }, `built ${when || "—"} IST from the ${dp.from || "last close"}` + (fin(dp.overnight_pct) ? ` · overnight ${signed(dp.overnight_pct)}%` : ""))),
		items.length ? h("div", { class: "rows" }, items.map((i) => h("div", { style: "padding:8px 16px;border-top:1px solid var(--line)" },
			h("div", { class: "row", style: "justify-content:space-between;gap:8px" },
				h("b", { class: "mono" }, `${i.u} ${word(i.view)}`),
				i.proven ? h("span", { class: "tag bull" }, "can trade at the open") : h("span", { class: "tag flat" }, `testing: ${num(i.n, 0)} shadow trades`)),
			h("div", { class: "f2", style: "font-size:12.5px;line-height:1.45;margin-top:2px" }, i.what || i.sid),
			h("div", { class: "mono f2", style: "font-size:12px;margin-top:3px" }, `reward:risk ${fin(i.rr) ? i.rr.toFixed(1) : "—"} · risk ₹${num(i.risk_lot, 0)} · target ₹${num(i.reward_lot, 0)} a lot · expiry ${i.exp || "—"}`),
			Array.isArray(i.legs) && i.legs.length ? h("div", { class: "mono f3", style: "font-size:11px;margin-top:2px;white-space:normal" }, i.legs.join("  ")) : null,
			(i.why || []).length || (i.catalysts || []).length ? h("div", { class: "f3", style: "font-size:11.5px;line-height:1.45;margin-top:3px;white-space:normal" }, [...(i.why || []), ...(i.catalysts || [])].join(" · ")) : null)))
			: h("div", { class: "f3", style: "font-size:12.5px;padding:10px 16px" }, "Nothing on the plan: no underlying has a clear pre-open view with a reward to risk of 2 or better."),
		notes.length ? h("div", { class: "f3", style: "font-size:11.5px;line-height:1.55;padding:6px 16px 0" }, notes.join(" ")) : null,
		h("div", { class: "f3", style: "font-size:11.5px;line-height:1.55;padding:6px 16px 12px" }, "Built every ten minutes from 06:00 to 09:15 from last night's closing books, the overnight markets, the news and the pre-market brief. From 09:20 the desk takes a planned strategy first, if its context still holds and its record is proven; the risk limits are the same as for any trade."));
}
function ppLab(lab) {
	const cell = (k, v, cl) => h("div", {}, h("span", {}, k), h("b", { class: "mono " + (cl || "") }, v));
	const td = lab.today || {}, rows = Array.isArray(lab.top) ? lab.top : [];
	const st = lab.state && typeof lab.state === "object" ? Object.entries(lab.state) : [];
	const word = (v) => (v === "up" ? "▲ up" : v === "down" ? "▼ down" : v === "flat" ? "◆ flat" : "—");
	const fams = Array.isArray(lab.families) ? lab.families : [];
	return h("div", { class: "grp" },
		h("div", { class: "sec-h" }, h("h2", {}, "Strategy lab (AUTO v2)"), h("span", { class: "hint" }, `${num(lab.strategies, 0)} strategies written`)),
		h("div", { class: "kstrip" }, cell("With a record", num(lab.tested, 0)), cell("Shadow trades", num(lab.trades, 0)), cell("Proven enough to trade", num(lab.eligible, 0), lab.eligible ? "up" : ""),
			cell("Today", `${td.shadow_closed || 0} scored · ${td.live_entries || 0} live`), cell("Invented by the desk", num(lab.invented || 0, 0)),
			cell("News forecasts (Brier)", lab.news_calibration && fin(lab.news_calibration.brier) ? `${num(lab.news_calibration.brier, 3)} · ${num(lab.news_calibration.n, 0)}` : "—")),
		rows.length ? h("div", { class: "panel scroll", style: "margin:0;border:0" }, h("table", { class: "tbl" },
			h("thead", {}, h("tr", {}, ["Strategy", "Trades", "Avg R", "Won", ""].map((x) => h("th", {}, x)))),
			h("tbody", {}, rows.map((r) => h("tr", {}, h("td", {}, h("div", { class: "mono", style: "font-size:12px" }, r.sid), h("div", { class: "f3", style: "font-size:11px;line-height:1.4;white-space:normal" }, r.what)),
				h("td", {}, num(r.n, 0)), h("td", { class: cls(r.mean_r) }, signed(r.mean_r)), h("td", {}, Math.round((r.win || 0) * 100) + "%"),
				h("td", {}, r.live ? h("span", { class: "tag bull" }, "live") : h("span", { class: "tag flat" }, r.n < (r.invented ? lab.min_trades_invented || lab.min_trades : lab.min_trades) ? "testing" : "below 0"),
					r.invented ? h("span", { class: "tag", style: "margin-left:4px" }, "invented") : null))))))
			: h("div", { class: "f3", style: "font-size:12.5px;padding:10px 16px" }, "No shadow trade has closed yet. Every strategy whose market context holds is traded in shadow at the real prices; a record builds through the session."),
		st.length ? fold("lab-state", "What it sees now", `${st.length} underlyings`, h("div", { class: "rows" }, st.map(([u, v]) => h("div", { class: "row", style: "justify-content:space-between;padding:6px 16px;font-size:12.5px;border-top:1px solid var(--line)" },
			h("b", { class: "mono" }, u), h("span", { class: "f2", style: "text-align:right" }, `${word(v[0])} · volatility ${v[1] || "—"}${fin(v[2]) ? " (" + v[2].toFixed(2) + "x realized)" : ""}${v[3] ? " · expiry tomorrow" : ""}${fin(v[4]) ? " · read P(up) " + v[4].toFixed(2) : ""}${v[5] ? " (" + v[5] + ")" : ""}${v[6] ? " · " + v[6] : ""}${v[7] ? " · HMM " + v[7] : ""}${v[8] ? " · change point: " + v[8] : ""}${fin(v[9]) ? " · Kalman trend t " + (v[9] > 0 ? "+" : "") + v[9].toFixed(1) : ""}${v[10] ? " · " + v[10] : ""}${fin(v[11]) ? " · news P(up) " + v[11].toFixed(2) : ""}${v[12] ? " (" + v[12] + ")" : ""}`))))) : null,
		fams.length ? fold("lab-fam", "By structure (evidence shared)", `spread within ±${num(lab.tau, 2)}R`, h("div", { class: "rows" }, fams.map((f) => h("div", { class: "row", style: "justify-content:space-between;padding:6px 16px;font-size:12.5px;border-top:1px solid var(--line)" },
			h("b", {}, f.name), h("span", { class: "f2 mono", style: "text-align:right" }, `${signed(f.mu_r)}R ± ${num(f.se, 2)} · ${num(f.members, 0)} strategies · ${num(f.trades, 0)} trades`))))) : null,
		h("div", { class: "f3", style: "font-size:11.5px;line-height:1.55;padding:8px 16px 12px" }, `Each strategy is a combination of a market context, a structure, a width, an expiry and its exits. It trades with paper money only after ${lab.min_trades} shadow trades, chosen by Thompson sampling over a hierarchical model: a short record is pulled towards the record of its structure (every iron condor informs every other), and each structure's towards zero, so an unproven idea keeps being tested before it gets capital. An option sale also has to pay for its tail, measured by extreme value theory. Every morning the desk also INVENTS strategies (new leg combinations, defined risk only), which need ${lab.min_trades_invented || 12} shadow trades before paper money. News is read per instrument: what each story means for that instrument, and what it did in past episodes most like today. Not proven to make money.`));
}
async function renderPaper(force) {
	const body = $("#pp-body"), P = S.pp;
	if (S.tab !== "paper" || document.hidden || (P.busy && !force)) return;
	if (/(^|\.)github\.io$/.test(location.hostname)) { if (body.dataset.state !== "pages") { body.textContent = ""; put(body, empty("paper", "Paper trading uses the private live relay, which is only open on the Cloudflare site, not on this address.")); body.dataset.state = "pages"; } return; }
	if (!store("qd.livekey")) { if (body.dataset.state !== "key") { body.textContent = ""; put(body, liveKeyForm("")); body.dataset.state = "key"; } return; }
	P.busy = true;
	const r = await paperCall("GET", "/paper/state");
	P.busy = false;
	if (S.tab !== "paper") return;
	if (r.status === 401) { body.textContent = ""; body.dataset.state = "note"; return void put(body, liveKeyForm("That key was not accepted. Type it again.")); }
	if (r.status !== 200) { P.note = `The relay did not answer as expected (HTTP ${r.status || "no answer"}).`; if (!P.data) { body.textContent = ""; return void put(body, h("div", { class: "note warn" }, P.note)); } }
	else { P.data = r.body; if (P.note.startsWith("The relay did not")) P.note = ""; }
	body.dataset.state = "data";
	ppDraw();
}

// ==================================================================================================================
// refresh loop, pull to refresh, boot
// ==================================================================================================================
let busy = false, queued = null;
async function refresh(full, force) {
	if (document.hidden) return;
	// one refresh at a time; a tab switch during a slow one runs right after it instead of being dropped
	if (busy) { queued = { full: !!(full || (queued && queued.full)), force: !!(force || (queued && queued.force)) }; return; }
	busy = true;
	try {
		if (force && window.QD_PUBLISHED && window.qdReload) await window.qdReload();
		const t = S.tab;
		if (t === "live") await renderLive();
		else if (t === "paper") await renderPaper();
		else if (t === "today") await renderToday(full);
		else if (t === "trades") await renderTrades(full);
		else if (t === "data") await renderDataTab(full);
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
	buildTabs();
	document.addEventListener("click", (e) => { const g = e.target.closest("[data-go]"); if (g) go(g.dataset.go); });
	document.querySelectorAll("[data-info]").forEach((b) => b.addEventListener("click", () => showGloss(b.dataset.info)));
	$("#btn-settings").addEventListener("click", openSettings);
	$("#status").addEventListener("click", () => { pollHealth(); refresh(true, true); toast("Refreshed"); });
	$("#sheet").addEventListener("click", (e) => { if (e.target.id === "sheet") closeSheet(); });
	document.addEventListener("keydown", (e) => { if (e.key === "Escape") { closeSheet(); } });
	addEventListener("hashchange", () => { const [t, s] = location.hash.slice(1).split("/"); show(t || "live", s); });
	addEventListener("beforeinstallprompt", (e) => { e.preventDefault(); S.installEvt = e; });
	addEventListener("appinstalled", () => { store("qd.installed", "1"); document.querySelectorAll(".install").forEach((x) => x.remove()); });
	addEventListener("offline", () => setStatus());
	addEventListener("online", () => { window.QD_OFFLINE_CACHE = false; pollHealth(); refresh(true, true); });
	try { S.accounts = await api("/api/i/accounts"); } catch (e) { S.accounts = []; }
	if (!S.accounts.length) S.accounts = [{ id: "live", label: "Live paper" }];
	const saved = store("qd.account");
	S.account = S.accounts.some((a) => a.id === saved) ? saved : S.accounts[0].id;
	const [t, s] = location.hash.slice(1).split("/");
	show(t || store("qd.tab") || "live", s);
	pullToRefresh();
	// the chart draws text on a canvas: repaint once the app's own fonts have loaded
	if (document.fonts && document.fonts.ready) document.fonts.ready.then(() => restyleCharts());
	setInterval(() => refresh(false), 15000);
	pollHealth();
	setInterval(pollHealth, 10000);                                                                   // the header pill, on every tab
	setInterval(() => { if (S.tab === "live" && !document.hidden) renderLive(); }, 5000);
	setInterval(() => { if (S.tab === "paper" && !document.hidden) renderPaper(); }, 4000);          // the Paper tab alone refreshes every 4 seconds          // the Live tab alone refreshes every 5 seconds
	document.addEventListener("visibilitychange", () => { if (!document.hidden) refresh(true); });
	if ("serviceWorker" in navigator && window.isSecureContext && window.QD_PUBLISHED)
		navigator.serviceWorker.register("sw.js").catch(() => { /* offline support is a bonus */ });
}
boot().catch((e) => toast("Failed to start: " + e.message));
