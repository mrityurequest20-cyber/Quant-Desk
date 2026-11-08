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
const TABS = [["live", "Live"], ["build", "Build"], ["paper", "Paper"], ["today", "Today"], ["trades", "History"], ["data", "Data"]];
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
// TODAY: the pre-market brief (quantdesk/premarket; premarket.yml every 15 minutes, 07:15-09:15 IST)
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
			"No pre-market brief yet. It is built every 15 minutes from 07:15 to 09:15 IST on weekdays" + (S.pmErr ? ` (${S.pmErr}).` : "."))))); return;
	}
	const sum = h("div", { class: "rows" }, (b.summary || []).map((line) => h("div", { class: "pad", style: "font-size:13.5px;line-height:1.5" }, line)));
	put(body, grp("Pre-market brief", `built ${ago(b.generated_at)}`, sum));
	if (b.data_stale) put(body, h("div", { class: "banner err" }, icon("alert"), h("div", {}, `The latest bhavcopy is from ${b.last_close}: the warehouse may be behind.`)));
	const notes = (t) => h("div", { class: "f3", style: "font-size:12px;line-height:1.5;margin-top:4px" }, t);
	if ((b.expiring || []).length)
		put(body, grp("Expiry today", b.expiring.map((e) => e.symbol).join(", "), h("div", { class: "rows" }, h("div", { class: "pad" }, notes(b.expiring[0].note)))));
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
	["Pre-market brief", "07:15 to 09:15", "premarket.yml, on its own branch; shown on the Today tab"],
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
	const pmRows = !pm ? [empty("watch", "No pre-market brief yet. It is built every 15 minutes from 07:15 to 09:15 IST on weekdays.")]
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
// ---- Live: every price the Kite recorder watches, refreshed every 5 seconds. PRIVATE: Zerodha's data is licensed to the owner, so the relay
// (deploy/cloudflare/live.js) answers only to a key typed once into this device. Display only: nothing on this tab can trade. -----------------
// The universe is the recorder's (kite_universe.py): indices, the near-month future of every F&O underlying, MCX and currency, the F&O stocks' cash
// prices and index options near the money: a thousand rows or more, so the tab has search, segment filters, sorting and "show more".
const LIVE_FRESH = 15, LIVE_DELAYED = 120;                       // seconds: green up to 15, amber up to 2 minutes, then "no feed"
const LIVE_SEGS = [["all", "All"], ["idx", "Index"], ["fut", "Futures"], ["eq", "Stocks"], ["opt", "Options"], ["mcx", "MCX"], ["cds", "Currency"]];
const LIVE_SORTS = [["name", "Name"], ["move", "Movers"], ["fresh", "Newest"]];
const LIVE_FIRST = ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX", "INDIAVIX", "NIFTY-FUT", "BANKNIFTY-FUT"];
const LIVE_PAGE = 150;
const LIVE_VOL = new Intl.NumberFormat("en-IN", { notation: "compact", maximumFractionDigits: 1 });
S.lv = { q: "", seg: "all", sort: "name", limit: LIVE_PAGE, data: null, built: false, sel: null, series: null, exp: null, allStrikes: false };
let liveBusy = false;
const livePx = (v, seg) => (fin(v) ? v.toLocaleString("en-IN", seg === "cds" ? { minimumFractionDigits: 4, maximumFractionDigits: 4 } : { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : "—");
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
	const save = () => { if (inp.value.trim()) { store("qd.livekey", inp.value.trim()); S.lv.built = false; $("#lv-body").dataset.state = ""; const bb = $("#bd-body"); if (bb) bb.dataset.state = ""; if (S.tab === "build") renderBuild(); renderLive(); pollHealth(); } };
	inp.addEventListener("keydown", (e) => { if (e.key === "Enter") save(); });
	return h("div", { class: "panel pad" }, h("div", { style: "font-weight:600;margin-bottom:6px" }, "Live prices"),
		h("div", { style: "font-size:13px;color:var(--fg2);line-height:1.55;margin-bottom:10px" },
			"Real-time prices from the desk's Kite recorder, every 5 seconds. They are private to you: type your live key once on this device (it is the LIVE_READ_TOKEN you set on the Worker)."),
		note ? h("div", { class: "warn", style: "font-size:12.5px;margin-bottom:8px" }, note) : null, inp,
		h("button", { class: "btn block", style: "margin-top:10px", onclick: save }, "Save key"));
}
function liveRows(data) {
	const L = S.lv, q = L.q.trim().toLowerCase(), names = Object.keys(data.quotes);
	const rows = names.filter((n) => (L.seg === "all" || liveSeg(n, data.quotes[n]) === L.seg) && (!q || n.toLowerCase().includes(q) || liveLabel(n, data.quotes[n]).toLowerCase().includes(q)));
	const rank = (n) => { const k = LIVE_FIRST.indexOf(n); return k < 0 ? 999 : k; };
	if (L.sort === "move") rows.sort((a, b) => Math.abs(data.quotes[b].chg || 0) - Math.abs(data.quotes[a].chg || 0) || (a < b ? -1 : 1));
	else if (L.sort === "fresh") rows.sort((a, b) => data.quotes[a].age_s - data.quotes[b].age_s || (a < b ? -1 : 1));
	else rows.sort((a, b) => rank(a) - rank(b) || (a < b ? -1 : 1));
	return rows;
}
function liveDraw() {
	const L = S.lv, data = L.data, body = $("#lv-body");
	if (!data || !L.built) return;
	const newest = data.newest_age_s;
	const kind = !fin(newest) ? (inSession() ? "stale" : "paused") : newest <= LIVE_FRESH ? "live" : newest <= LIVE_DELAYED ? "stale" : "paused";
	const label = !fin(newest) ? (inSession() ? "No prices yet" : "Market closed, opens " + nextOpen()) : newest <= LIVE_FRESH ? "Live" : newest <= LIVE_DELAYED ? "Delayed " + liveAge(newest) : "No feed: last " + liveAge(newest) + " ago";
	const pill = $("#lv-pill"); pill.className = "pill " + kind; $("#lv-pill-t").textContent = label;
	const counts = {};
	for (const [n, v] of Object.entries(data.quotes)) { const k = liveSeg(n, v); counts[k] = (counts[k] || 0) + 1; }
	$("#lv-count").textContent = Object.keys(data.quotes).length.toLocaleString("en-IN") + " instruments · every 5 s";
	const hl = L.health, ln = $("#lv-sources");
	if (hl && ln) {                                                   // the state of each source, from /live/health
		const kt = hl.kotak || {}, kk = hl.kite || {};
		const ok = (n, a) => (n > 0 && fin(a) && a <= LIVE_FRESH * 2 ? "●" : "○");
		ln.textContent = `${ok(kk.n, kk.newest_age_s)} Kite ${kk.n || 0}  ·  ${ok(kt.n, kt.newest_age_s)} Kotak ${kt.n || 0}${kt.status && kt.status !== "ok" ? " (" + kt.status + ")" : ""}  ·  ${hl.disagree ? "⚠ " + hl.disagree + " disagree" : "sources agree"}`;
	}
	$("#lv-list").hidden = !!L.sel; $("#lv-detail").hidden = !L.sel;
	if (L.sel) return liveDetail();
	document.querySelectorAll("#lv-segs .chip").forEach((c) => { c.setAttribute("aria-pressed", String(c.dataset.k === L.seg)); const n = c.dataset.k === "all" ? Object.keys(data.quotes).length : counts[c.dataset.k] || 0; c.lastChild.textContent = " " + n; });
	document.querySelectorAll("#lv-sorts .chip").forEach((c) => c.setAttribute("aria-pressed", String(c.dataset.k === L.sort)));
	const rows = liveRows(data), shown = rows.slice(0, L.limit), tb = $("#lv-table");
	tb.textContent = "";
	if (!rows.length) { put(tb, empty("live", Object.keys(data.quotes).length ? "Nothing matches." : "Nothing has arrived yet. The recorder pushes from 09:15 IST on a trading day.")); return; }
	const trs = shown.map((n) => {
		const v = data.quotes[n], old = v.age_s > LIVE_DELAYED, seg = liveSeg(n, v);
		const chg = fin(v.chg) ? h("span", { class: "chg " + (v.chg > 0 ? "up" : v.chg < 0 ? "dn" : "flat") }, (v.chg > 0 ? "+" : "") + v.chg.toFixed(2) + "%") : "—";
		const book = fin(v.bid) && fin(v.ask) ? " · " + livePx(v.bid, seg) + " / " + livePx(v.ask, seg) : "";               // bid / ask, where either feed carries a book
		const src = v.src === "z" ? "Kite" : v.src === "k" ? "Kotak" : "";
		const flag = fin(v.x) ? h("span", { class: "warn" }, " · ⚠ the two sources differ " + v.x.toFixed(1) + "%") : null;     // Kite and Kotak disagree by more than a spread explains
		return h("tr", { style: (old ? "opacity:.55;" : "") + "cursor:pointer", tabindex: "0", role: "button", onclick: () => liveOpen(n), onkeydown: (e) => { if (e.key === "Enter") liveOpen(n); } }, h("td", {}, liveLabel(n, v), h("div", { class: "f3", style: "font-size:10.5px" }, liveAge(v.age_s) + " ago" + (src ? " · " + src : "") + book, flag)), h("td", {}, livePx(v.ltp, seg)), h("td", {}, chg),
			h("td", { class: "f2" }, fin(v.vol) ? LIVE_VOL.format(v.vol) : "—"));
	});
	put(tb, h("div", { class: "panel scroll" }, h("table", { class: "tbl" }, h("thead", {}, h("tr", {}, ["Name", "Last", "Change", "Volume"].map((x) => h("th", {}, x)))), h("tbody", {}, trs))),
		rows.length > shown.length ? h("button", { class: "btn block", style: "margin:10px 16px;width:calc(100% - 32px)", onclick: () => { L.limit += LIVE_PAGE; liveDraw(); } }, `Show ${Math.min(LIVE_PAGE, rows.length - shown.length)} more (${rows.length - shown.length} left)`) : null);
}
// ---- one instrument: its quote, a chart of today's closes (one a minute, from the relay's series), what it relates to, and for an underlying its option chain.
// Everything is drawn from the snapshot the tab already holds plus one small series request; nothing here can trade.
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
function liveHHMM(minute) { const d = new Date(minute * 60000 + 19800000); return String(d.getUTCHours()).padStart(2, "0") + ":" + String(d.getUTCMinutes()).padStart(2, "0"); }
function liveChart(ser, seg) {
	const W = 320, H = 130, box = h("div", { class: "panel", style: "margin:0 16px 10px;padding:10px" });
	const day = ser && ser.day ? ser.day : [];
	if (day.length < 2) return put(box, h("div", { class: "f3", style: "font-size:12px;padding:30px 0;text-align:center" }, day.length ? "One price so far today." : "No chart for this instrument yet. It builds as the price moves; if the relay's chart store is full, a new contract waits until room is made."));
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
function liveField(label, value) { return h("div", { style: "display:flex;justify-content:space-between;padding:7px 0;border-top:1px solid var(--line);font-size:13px" }, h("span", { class: "f3" }, label), h("span", {}, value)); }
function liveRelated(name, v, data, chains) {
	const o = liveOpt(name), links = [], has = (n) => data.quotes[n] != null;
	const go = (n, t) => links.push(h("button", { class: "chip", onclick: () => liveOpen(n) }, t));
	if (o) { if (has(o.u)) go(o.u, o.u + " spot"); if (has(o.u + "-FUT")) go(o.u + "-FUT", o.u + " fut"); }
	else if (/-FUT$/.test(name)) { const u = name.slice(0, -4); if (has(u)) go(u, u + " spot"); }
	else if (has(name + "-FUT")) go(name + "-FUT", name + " fut");
	return links.length ? h("div", { class: "chips", style: "padding:0 16px 10px" }, links) : null;
}
function liveChainTable(u, data, chains) {
	const L = S.lv, exps = Object.keys(chains[u] || {}).sort((a, b) => liveExpiryKey(a) - liveExpiryKey(b));
	if (!exps.length) return null;
	if (!exps.includes(L.exp)) L.exp = exps[0];
	const strikes = Object.keys(chains[u][L.exp]).map(Number).sort((a, b) => a - b);
	const spot = (data.quotes[u] || data.quotes[u + "-FUT"] || {}).ltp;
	let atm = 0;
	if (fin(spot)) strikes.forEach((k, i) => { if (Math.abs(k - spot) < Math.abs(strikes[atm] - spot)) atm = i; });
	const from = L.allStrikes ? 0 : Math.max(0, atm - 12), to = L.allStrikes ? strikes.length : Math.min(strikes.length, atm + 13);
	const cell = (n, f, seg) => { const q = n ? data.quotes[n] : null; return h("td", { class: q && q.age_s > LIVE_DELAYED ? "f3" : "" }, q && fin(q[f]) ? (f === "ltp" ? livePx(q[f], seg) : LIVE_VOL.format(q[f])) : "—"); };
	const rows = strikes.slice(from, to).map((k, i) => {
		const r = chains[u][L.exp][k];
		return h("tr", { style: from + i === atm && fin(spot) ? "background:var(--panel2)" : null }, cell(r.CE, "oi"), cell(r.CE, "ltp", "opt"), h("td", { style: "text-align:center;font-weight:600", onclick: null }, k.toLocaleString("en-IN")), cell(r.PE, "ltp", "opt"), cell(r.PE, "oi"));
	});
	return h("div", {}, h("div", { class: "pad", style: "font-weight:600" }, "Option chain"),
		h("div", { class: "chips", style: "padding:0 16px 8px" }, exps.map((e) => h("button", { class: "chip", "aria-pressed": String(e === L.exp), onclick: () => { L.exp = e; liveDraw(); } }, e))),
		h("div", { class: "panel scroll" }, h("table", { class: "tbl" }, h("thead", {}, h("tr", {}, ["Call OI", "Call", "Strike", "Put", "Put OI"].map((x) => h("th", { style: "text-align:center" }, x)))), h("tbody", {}, rows))),
		strikes.length > to - from ? h("button", { class: "btn block", style: "margin:10px 16px;width:calc(100% - 32px)", onclick: () => { L.allStrikes = !L.allStrikes; liveDraw(); } }, L.allStrikes ? "Only near the money" : `Show all ${strikes.length} strikes`) : null,
		h("div", { class: "f3", style: "font-size:11.5px;padding:6px 16px" }, "The strikes the feeds carry for this underlying" + (fin(spot) ? "; the shaded row is nearest the price" : "") + ". Index chains hold the nearest two expiries."));
}
function liveDetail() {
	const L = S.lv, data = L.data, name = L.sel, box = $("#lv-detail"), v = data.quotes[name];
	box.textContent = "";
	const back = h("button", { class: "btn", style: "margin:0 16px 10px", onclick: () => liveOpen(null) }, "← All instruments");
	if (!v) return void put(box, back, empty("live", name + " is not on the board right now (it may have expired or not ticked yet)."));
	const seg = liveSeg(name, v), o = liveOpt(name), chains = liveChains(data);
	const ser = L.series && L.series.name === name ? L.series : null, prev = ser ? ser.prev_close : null;
	const chgPct = fin(v.chg) ? v.chg : fin(prev) && prev > 0 ? ((v.ltp - prev) / prev) * 100 : null;
	const closes = ser && ser.day.length ? ser.day.map((p) => p[1]) : null;
	const src = v.src === "z" ? "Kite" : v.src === "k" ? "Kotak" : "";
	const alt = v.alt ? `${v.alt.src === "z" ? "Kite" : "Kotak"} ${livePx(v.alt.ltp, seg)} · ${liveAge(v.alt.age_s)} ago` : null;
	put(box, back,
		h("div", { style: "padding:0 16px 8px" }, h("div", { style: "font-size:13px;color:var(--fg2)" }, liveLabel(name, v)),
			h("div", { style: "display:flex;align-items:baseline;gap:10px" }, h("span", { style: "font-size:30px;font-weight:600;font-variant-numeric:tabular-nums" }, livePx(v.ltp, seg)),
				chgPct != null ? h("span", { class: "chg " + (chgPct > 0 ? "up" : chgPct < 0 ? "dn" : "flat"), style: "font-size:14px" }, (chgPct > 0 ? "+" : "") + chgPct.toFixed(2) + "%") : null),
			h("div", { class: "f3", style: "font-size:11.5px" }, liveAge(v.age_s) + " ago" + (src ? " · " + src : "") + (fin(v.x) ? " · ⚠ the two sources differ " + v.x.toFixed(1) + "%" : ""))),
		liveChart(ser, seg), liveRelated(name, v, data, chains),
		h("div", { class: "panel pad", style: "margin:0 16px 12px" },
			liveField("Bid / Ask", fin(v.bid) && fin(v.ask) ? `${livePx(v.bid, seg)} / ${livePx(v.ask, seg)}` + (fin(v.bid_qty) && fin(v.ask_qty) ? ` (${LIVE_VOL.format(v.bid_qty)} / ${LIVE_VOL.format(v.ask_qty)})` : "") : "—"),
			liveField("Volume", fin(v.vol) ? v.vol.toLocaleString("en-IN") : "—"), liveField("Open interest", fin(v.oi) ? v.oi.toLocaleString("en-IN") : "—"),
			liveField("Previous close", fin(prev) ? livePx(prev, seg) : "—"),
			liveField("Day high / low", closes ? `${livePx(Math.max(...closes), seg)} / ${livePx(Math.min(...closes), seg)}` : "—"),
			o ? liveField("Contract", `${o.u} ${o.e} ${o.k.toLocaleString("en-IN")} ${o.t === "CE" ? "call" : "put"}`) : null,
			alt ? liveField("Other source", alt) : null),
		h("div", { class: "f3", style: "font-size:11.5px;padding:0 16px 10px" }, "Day high and low are the highest and lowest of the one-a-minute closes the relay holds for today (only the most recent minutes when its store is full), not the exchange's own figures."),
		o ? null : liveChainTable(name.replace(/-FUT$/, ""), data, chains));
}
function liveOpen(name) {
	const L = S.lv;
	L.sel = name; L.series = null; L.allStrikes = false;
	if (name) L.exp = (liveOpt(name) || {}).e || null;
	liveDraw();
	if (name) liveSeries();
	window.scrollTo(0, 0);
}
async function liveSeries() {
	const L = S.lv, name = L.sel, key = store("qd.livekey");
	if (!name || !key) return;
	try {
		const r = await fetch("/live/series?name=" + encodeURIComponent(name), { headers: { Authorization: "Bearer " + key }, cache: "no-store" });
		if (r.ok && L.sel === name) { L.series = await r.json(); liveDraw(); }
	} catch (e) { /* the quote still shows */ }
}
function liveBuild() {
	const L = S.lv, body = $("#lv-body");
	body.textContent = "";
	const search = h("input", { type: "search", class: "search", placeholder: "Search every instrument", "aria-label": "Search instruments", autocomplete: "off", value: L.q });
	search.addEventListener("input", () => { L.q = search.value; L.limit = LIVE_PAGE; liveDraw(); });
	const seg = h("div", { class: "chips", id: "lv-segs", style: "padding:0 16px 8px" }, LIVE_SEGS.map(([k, t]) => h("button", { class: "chip", "data-k": k, "aria-pressed": "false", onclick: () => { L.seg = k; L.limit = LIVE_PAGE; liveDraw(); } }, t, h("span", { class: "f3" }, " "))));
	const sort = h("div", { class: "chips", id: "lv-sorts", style: "padding:0 16px 8px" }, h("span", { class: "f3", style: "font-size:11.5px;align-self:center" }, "Sort"),
		LIVE_SORTS.map(([k, t]) => h("button", { class: "chip", "data-k": k, "aria-pressed": "false", onclick: () => { L.sort = k; liveDraw(); } }, t)));
	put(body, h("div", { class: "pad", style: "display:flex;justify-content:space-between;align-items:center" }, h("span", { id: "lv-pill", class: "pill paused" }, h("span", { class: "dot" }), h("b", { id: "lv-pill-t" }, "")), h("span", { id: "lv-count", class: "f3", style: "font-size:11.5px" }, "")),
		h("div", { id: "lv-sources", class: "f3", style: "font-size:11.5px;padding:0 16px 8px" }, ""),
		h("div", { id: "lv-list" }, h("div", { style: "padding:0 16px 10px" }, search), seg, sort, h("div", { id: "lv-table" })),
		h("div", { id: "lv-detail", hidden: true }),
		h("div", { class: "f3", style: "font-size:11.5px;line-height:1.55;padding:12px 16px" },
			"Prices come from Zerodha's Kite feed and are shown only to you. Under each name is how long ago the relay last got that price. Tap any row for its chart and, for an underlying, its option chain. This tab only displays: nothing here can place an order. ",
			h("a", { href: "#", class: "acc", onclick: (e) => { e.preventDefault(); try { localStorage.removeItem("qd.livekey"); } catch (x) { /* ignore */ } L.built = false; L.health = null; L.hstate = null; body.dataset.state = ""; renderLive(); setStatus(); } }, "Forget this key")));
	L.built = true;
	body.dataset.state = "data";
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
		if (j && S.lv.sel) {                                                          // an instrument is open: its chart series, with every refresh
			try {
				const sr = await fetch("/live/series?name=" + encodeURIComponent(S.lv.sel), { headers: { Authorization: "Bearer " + key }, cache: "no-store" });
				if (sr.ok) { const sj = await sr.json(); if (sj.name === S.lv.sel) S.lv.series = sj; }
			} catch (e) { /* the quote still shows */ }
		}
	} catch (e) { note = "No live prices: the request failed before any answer (" + String((e && e.name) || "error") + ") from " + location.host + ". Offline, or the address blocks it."; }
	finally { liveBusy = false; }
	if (S.tab !== "live") return;
	if (!j) { body.textContent = ""; S.lv.built = false; body.dataset.state = "note"; setStatus(); return void put(body, liveKeyForm(note)); }
	S.lv.data = j;
	if (!S.lv.built) liveBuild();
	liveDraw();
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
		paper: { risk_per_trade: 0.025, max_quote_age_s: 30, underlyings: ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY"] },     // the paper desk's gate (quantdesk/paper/risk.py)
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
	function fees(side, price, units, c) {
		const turnover = units * price, o = c.costs.options, brokerage = c.costs.brokerage_per_order, sebi = turnover * c.costs.sebi_per_crore / 1e7;
		const stt = turnover * (side > 0 ? o.stt_buy : o.stt_sell), exchange = turnover * o.exchange, stamp = side > 0 ? turnover * o.stamp_buy : 0, gst = c.costs.gst * (brokerage + exchange + sebi);
		return brokerage + stt + exchange + sebi + stamp + gst;
	}
	function halfSpread(price, c) {                                      // the model's adverse slippage per unit (CostModel.slippage for options)
		const s = c.slippage, half = Math.max(s.option_half_spread_pct * price, s.option_min_half_spread);
		return Math.round(half / s.option_tick) * s.option_tick;
	}
	// ---- templates: [side, type, offset in strike steps from the at-the-money strike] -------------------------------------------------
	const TEMPLATES = {
		long_call: { name: "Long call", view: "Bullish: wants a big move up", wide: false, legs: () => [[1, "CE", 0]] },
		long_put: { name: "Long put", view: "Bearish: wants a big move down", wide: false, legs: () => [[1, "PE", 0]] },
		long_straddle: { name: "Long straddle", view: "Big move, either way", wide: false, legs: () => [[1, "CE", 0], [1, "PE", 0]] },
		long_strangle: { name: "Long strangle", view: "Big move, either way, cheaper", wide: true, legs: (w) => [[1, "CE", w], [1, "PE", -w]] },
		bull_call_spread: { name: "Bull call spread", view: "Moderately bullish, capped", wide: true, legs: (w) => [[1, "CE", 0], [-1, "CE", w]] },
		bear_put_spread: { name: "Bear put spread", view: "Moderately bearish, capped", wide: true, legs: (w) => [[1, "PE", 0], [-1, "PE", -w]] },
		bull_put_spread: { name: "Bull put spread", view: "Not bearish: collects premium", wide: true, legs: (w) => [[-1, "PE", 0], [1, "PE", -w]] },
		bear_call_spread: { name: "Bear call spread", view: "Not bullish: collects premium", wide: true, legs: (w) => [[-1, "CE", 0], [1, "CE", w]] },
		iron_condor: { name: "Iron condor", view: "Stays in a range: collects premium", wide: true, legs: (w) => [[-1, "CE", w], [1, "CE", 2 * w], [-1, "PE", -w], [1, "PE", -2 * w]] },
		iron_butterfly: { name: "Iron butterfly", view: "Pins near the strike: collects premium", wide: true, legs: (w) => [[-1, "CE", 0], [-1, "PE", 0], [1, "CE", w], [1, "PE", -w]] },
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
	function legsFor(id, strikes, spot, names, width) {
		const t = TEMPLATES[id];
		if (!t) return { error: "Unknown strategy." };
		if (!strikes.length || !(spot > 0)) return { error: "No strikes or no price on the board for this underlying yet." };
		let atm = 0;
		strikes.forEach((k, i) => { if (Math.abs(k - spot) < Math.abs(strikes[atm] - spot)) atm = i; });
		const w = Math.max(1, Math.round(width || 1)), legs = [];
		for (const [side, type, off] of t.legs(w)) {
			const k = strikes[atm + off];
			const name = k != null && names[k] ? names[k][type] : null;
			if (k == null || !name) return { error: `The ${type} at ${off >= 0 ? "+" : ""}${off} strikes is not on the board: pick a smaller width.` };
			legs.push({ side, type, strike: k, name });
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
		const c = spec.c || conf(), inst = c.inst[spec.u] || { lot: 1, step: 1 }, lots = Math.max(1, Math.round(spec.lots || 1)), lot = inst.lot, r = c.r;
		const legs = spec.legs.map((l) => {
			const e = entry(l, spec.quotes[l.name]);
			const mid = e.src === "book" ? (e.bid + e.ask) / 2 : (spec.quotes[l.name] || {}).ltp;
			const iv = impliedVol(l.type, mid, spec.spot, l.strike, spec.T, r);
			const spread = e.src === "book" ? (e.ask - e.bid) / ((e.ask + e.bid) / 2) : NaN;
			const mult = Number.isInteger(l.mult) && l.mult >= 1 ? l.mult : 1;
			return { ...l, mult, units: lots * lot * mult, lots: lots * mult, px: e.px, src: e.src, bid: e.bid, ask: e.ask, age: e.age + (spec.ageAdd || 0), iv, spread };
		});
		const out = { legs, lots, lot, errors: [], checks: [], paperChecks: [], ok: false, paperOk: false };
		if (!(spec.T >= 0)) { out.errors.push("The expiry on the board could not be read, so the time to expiry is unknown."); return out; }
		const crossed = legs.filter((l) => l.src === "crossed");
		if (crossed.length) { out.errors.push(`Crossed bid/ask (bid above ask) on ${crossed.map((l) => l.strike + l.type).join(", ")}: a bad quote, not a price.`); return out; }
		if (legs.some((l) => !(l.px > 0))) { out.errors.push("A leg has no price on the board yet."); return out; }
		const callSlope = legs.filter((l) => l.type === "CE").reduce((a, l) => a + l.side * l.units, 0);
		out.definedRisk = callSlope >= 0;
		if (!out.definedRisk) { out.errors.push("This would leave a short call uncovered (unlimited loss). The builder only makes defined-risk structures."); return out; }
		out.premium = legs.reduce((a, l) => a + l.side * l.units * l.px, 0);                               // + debit paid, - credit received
		const ks = [...new Set(legs.map((l) => l.strike))].sort((a, b) => a - b), pts = [0, ...ks], far = (ks[ks.length - 1] || spec.spot) * 3;
		const pay = (S) => legs.reduce((a, l) => a + legPay(l, S), 0), vals = [...pts, far].map((S) => pay(S));
		const tailSlope = callSlope;                                                                       // beyond the highest strike the payoff slope is the net call position
		out.unlimitedProfit = tailSlope > 0;
		out.maxProfit = out.unlimitedProfit ? Infinity : Math.max(...vals);
		out.maxLoss = -Math.min(...vals);
		if (out.maxLoss < 0) { out.errors.push("This would be a guaranteed profit at every price, which is a bad quote rather than a trade. Check the prices on the board."); return out; }
		const be = [];
		const bp = [...pts, far];
		for (let i = 0; i + 1 < bp.length; i++) {
			const a = bp[i], b = bp[i + 1], fa = pay(a), fb = pay(b);
			if (fa === 0 && i === 0) be.push(a); else if ((fa < 0 && fb > 0) || (fa > 0 && fb < 0)) be.push(a + (b - a) * (0 - fa) / (fb - fa));
		}
		out.breakevens = be.filter((x) => x > 0).map((x) => Math.round(x * 100) / 100);
		const lo = spec.spot * 0.85, hi = spec.spot * 1.15, n = 121;
		out.grid = Array.from({ length: n }, (_, i) => lo + (hi - lo) * i / (n - 1));
		out.expiry = out.grid.map(pay);
		out.today = out.grid.map((S) => legs.reduce((a, l) => a + l.side * l.units * ((isFinite(l.iv) ? bs(l.type, S, l.strike, spec.T, l.iv, r) : (l.type === "CE" ? Math.max(0, S - l.strike) : Math.max(0, l.strike - S))) - l.px), 0));
		out.greeks = legs.reduce((a, l) => { const g = greeks(l.type, spec.spot, l.strike, spec.T, isFinite(l.iv) ? l.iv : 0.2, r); const m = l.side * l.units; return { delta: a.delta + m * g.delta, gamma: a.gamma + m * g.gamma, theta: a.theta + m * g.theta, vega: a.vega + m * g.vega }; }, { delta: 0, gamma: 0, theta: 0, vega: 0 });
		out.fees = legs.reduce((a, l) => a + fees(l.side, l.px, l.units, c) + fees(-l.side, l.px, l.units, c), 0);       // in and out at the entry price: the statutory part of a round trip
		out.exitSpread = legs.reduce((a, l) => a + l.units * (isFinite(l.spread) ? (l.spread * l.px) / 2 : halfSpread(l.px, c)), 0);   // crossing the spread again on the way out
		out.entryFees = legs.reduce((a, l) => a + fees(l.side, l.px, l.units, c), 0);                       // the entry leg only: the paper gate counts "the whole premium plus fees"
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
		pchk("long", shorts.length === 0, shorts.length ? `Short legs (${nm(shorts)}): the paper desk opens long options only until a margin model is built` : "Long options only");
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
		const c = spec.c || conf(), r = c.r, S = spec.spot * (1 + s.move), T = Math.max(0, spec.T - s.days / 365);
		let v = 0;
		for (const l of a.legs) {
			const iv = Number.isFinite(l.iv) ? Math.max(0.01, l.iv + s.dvol) : NaN;
			const val = T > 0 && Number.isFinite(iv) ? bs(l.type, S, l.strike, T, iv, r) : (l.type === "CE" ? Math.max(0, S - l.strike) : Math.max(0, l.strike - S));
			v += l.side * l.units * (val - l.px);
		}
		return v;
	}
	return { conf, bs, greeks, impliedVol, fees, halfSpread, TEMPLATES, CUSTOM, MAX_CUSTOM_LEGS, customLegs, legsFor, entry, analyze, scenario, suggestLots, yearsTo, ncdf, legPay };
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
		up: { name: "Up", ids: ["long_call", "bull_call_spread", "bull_put_spread"] },
		down: { name: "Down", ids: ["long_put", "bear_put_spread", "bear_call_spread"] },
		range: { name: "Stays in a range", ids: ["iron_condor", "iron_butterfly", "bull_put_spread", "bear_call_spread"] },
		big: { name: "Big move, either way", ids: ["long_straddle", "long_strangle"] },
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

// ---- the Build tab: pick an underlying, an expiry and a structure; see what it costs, where it makes and loses, and whether it fits the desk's limits. Paper only: no order is sent from here.
S.bd = { u: null, exp: null, tpl: "bull_call_spread", width: 2, lots: 1, data: null, busy: false, note: "", view: null, sort: "rr", custom: [], sc: { move: 0, dvol: 0, days: 0 } };
function bdChains(data) {                                                // the underlyings the builder can price: an index with a known lot size, and its board chains
	const c = QB.conf(), all = liveChains(data), out = Object.create(null);
	for (const u of Object.keys(c.inst)) if (all[u] && Object.keys(all[u]).length) out[u] = all[u];
	return out;
}
// ---- the market read and the ideas for a view, above the builder ----------------------------------------------------------------------------
function bdRead(ctx) {
	const { B, data, chains, ch, exps, spot, T, sq, c } = ctx;
	const rows = AN.chainRows(ch, data.quotes, spot, T, c.r), a = AN.atm(rows, spot, T, sq.chg);
	if (!a || a.iv == null) return h("div", { class: "note" }, "Not enough two-sided prices around the money yet to read the market.");
	const sk = AN.skew(rows, spot, 3), pc = AN.pcr(rows), mp = AN.maxPain(rows), w = AN.walls(rows, spot, 2);
	const next = exps[exps.indexOf(B.exp) + 1], tm = next ? AN.term(rows, AN.chainRows(chains[B.u][next], data.quotes, spot, QB.yearsTo(next, Date.now()), c.r), spot, T, QB.yearsTo(next, Date.now())) : null;
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
function bdIdeas(ctx) {
	const { B, strikes, names, spot, T, c, data, sq, rows } = ctx;
	const sigma = AN.atm(rows, spot, T, null);
	const chip = (label, on, fn) => h("button", { class: "chip", "aria-pressed": String(on), onclick: fn }, label);
	const box = h("div", { class: "grp" }, h("div", { class: "pad", style: "font-weight:600" }, "Ideas for your view"),
		h("div", { class: "chips", style: "padding:4px 16px" }, Object.entries(AN.VIEWS).map(([id, v]) => chip(v.name, B.view === id, () => { B.view = B.view === id ? null : id; bdDraw(); }))));
	if (!B.view) return put(box, h("div", { class: "f3", style: "font-size:12.5px;padding:2px 16px 12px" }, "Pick what you expect and every structure that fits it is priced on the live board and ranked."));
	if (!sigma || sigma.iv == null) return put(box, h("div", { class: "f3", style: "font-size:12.5px;padding:2px 16px 12px" }, "No volatility to price the chances with yet."));
	const analyzeFn = (id, width) => {
		const L = QB.legsFor(id, strikes, spot, names, width);
		return L.error ? null : QB.analyze({ u: B.u, legs: L.legs, quotes: data.quotes, spot, spotAge: sq.age_s, ageAdd: Math.max(0, (Date.now() - (B.at || Date.now())) / 1000), T, lots: 1 });
	};
	const list = AN.rank(AN.ideas(B.view, analyzeFn, { spot, T, sigma: sigma.iv, r: c.r }), B.sort).slice(0, 6);
	put(box, h("div", { class: "chips", style: "padding:0 16px 4px" }, [["rr", "Best reward for the risk"], ["pop", "Most likely to profit"], ["cheap", "Cheapest"]].map(([id, t]) => chip(t, B.sort === id, () => { B.sort = id; bdDraw(); }))));
	if (!list.length) return put(box, h("div", { class: "f3", style: "font-size:12.5px;padding:2px 16px 12px" }, "None of these structures can be priced on the board right now."));
	for (const x of list) put(box, h("div", { class: "pad", style: "border-top:1px solid var(--line)" },
		h("div", { class: "row", style: "justify-content:space-between;align-items:center;gap:8px" }, h("b", {}, x.name + (QB.TEMPLATES[x.id].wide ? ` (${x.width} strike${x.width === 1 ? "" : "s"} wide)` : "")), h("span", { class: "tag " + (x.paperOk ? "bull" : "flat") }, x.paperOk ? "paper desk can open" : "what-if only")),
		h("div", { class: "f3", style: "font-size:12px;line-height:1.55" }, `${x.premium >= 0 ? "Pay" : "Receive"} ${inr(Math.abs(x.premium))} · worst loss ${inr(x.maxLoss)} · best profit ${x.maxProfit === Infinity ? "no cap" : inr(x.maxProfit)} · chance on the model ${x.pop != null ? Math.round(x.pop * 100) + "%" : "—"}`),
		h("button", { class: "btn", style: "margin-top:6px", onclick: () => { B.tpl = x.id; B.width = x.width; bdDraw(); scrollTo({ top: 0, behavior: "smooth" }); } }, "Build this")));
	return put(box, h("div", { class: "f3", style: "font-size:11.5px;line-height:1.55;padding:6px 16px 12px" }, "The chance uses the market's own volatility, so before costs every structure here is a fair bet: it tells you how a trade pays, not whether to take it. Your edge is your view."));
}
function bdPayoff(a, spot) {
	const W = 640, H = 220, P = { l: 78, r: 12, t: 12, b: 26 }, el = svg("svg", { viewBox: `0 0 ${W} ${H}`, class: "bd-chart", role: "img", "aria-label": "Profit and loss at expiry and today, by price of the underlying", style: "width:100%;height:auto;display:block" });
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
	body.textContent = "";
	const chains = bdChains(data), us = Object.keys(chains);
	if (!us.length) return void put(body, empty("build", "No index option chain on the board yet. The relay fills it once the market is open and the feeds are on."));
	if (!us.includes(B.u)) B.u = us[0];
	const exps = Object.keys(chains[B.u]).sort((p, q) => liveExpiryKey(p) - liveExpiryKey(q));
	if (!exps.includes(B.exp)) B.exp = exps[0];
	const ch = chains[B.u][B.exp], strikes = Object.keys(ch).map(Number).sort((p, q) => p - q);
	const sq = data.quotes[B.u] || data.quotes[B.u + "-FUT"] || {}, spot = sq.ltp;
	const T = QB.yearsTo(B.exp, Date.now()), inst = c.inst[B.u], tpl = B.tpl === "custom" ? QB.CUSTOM : QB.TEMPLATES[B.tpl];
	const chip = (label, on, fn) => h("button", { class: "chip", "aria-pressed": String(on), onclick: fn }, label);
	const step = (label, val, dn, up) => h("div", { class: "row", style: "justify-content:space-between;align-items:center;padding:8px 16px" }, h("span", {}, label), h("span", { style: "display:flex;gap:10px;align-items:center" }, h("button", { class: "btn", "aria-label": "less " + label, onclick: dn }, "−"), h("b", { class: "mono" }, String(val)), h("button", { class: "btn", "aria-label": "more " + label, onclick: up }, "+")));
	put(body,
		h("div", { class: "note" }, "Paper only. This works out what a structure would cost and risk from the live prices; it reads the live board. The only thing it can send is a paper order, queued on the relay below and carried out by the paper runner through the risk gate. Only structures with a known worst loss can be built."),
		c.fromConfig ? null : h("div", { class: "note warn" }, "This page has no limits from the desk's config (QD_TRADE is missing), so it is using built-in defaults that may be out of date. Do not rely on the checklist; re-publish the site."),
		h("div", { class: "chips", style: "padding:8px 16px 4px" }, us.map((u) => chip(u, u === B.u, () => { B.u = u; B.exp = null; bdDraw(); }))),
		h("div", { class: "chips", style: "padding:4px 16px" }, exps.map((e) => chip(e, e === B.exp, () => { B.exp = e; bdDraw(); }))),
		h("div", { class: "chips", style: "padding:4px 16px" }, [...Object.keys(QB.TEMPLATES).map((id) => chip(QB.TEMPLATES[id].name, id === B.tpl, () => { B.tpl = id; bdDraw(); })),
			chip("Custom legs", B.tpl === "custom", () => { if (!B.custom.length) { const seed = QB.legsFor(B.tpl, strikes, spot, ch, B.width); if (seed.legs) B.custom = seed.legs.map((l) => ({ side: l.side, type: l.type, strike: l.strike, mult: 1 })); } B.tpl = "custom"; bdDraw(); })]),
		h("div", { class: "f3", style: "font-size:12px;padding:2px 16px 6px" }, tpl.view),
		B.tpl === "custom" ? bdCustom(B, strikes, spot) : null,
		tpl.wide ? step("Width (strikes)", B.width, () => { B.width = Math.max(1, B.width - 1); bdDraw(); }, () => { B.width = Math.min(10, B.width + 1); bdDraw(); }) : null,
		step("Lots (" + inst.lot + " units each)", B.lots, () => { B.lots = Math.max(1, B.lots - 1); bdDraw(); }, () => { B.lots = Math.min(c.limits.max_lots, B.lots + 1); bdDraw(); }));
	if (!fin(spot)) return void put(body, h("div", { class: "note" }, `No price for ${B.u} on the board yet.`));
	const names = {};
	for (const k of strikes) names[k] = ch[k];
	put(body, bdRead({ B, data, chains, ch, exps, spot, T, sq, c }), bdIdeas({ B, strikes, names, spot, T, c, data, sq, rows: AN.chainRows(ch, data.quotes, spot, T, c.r) }));
	const L = B.tpl === "custom" ? QB.customLegs(B.custom, names) : QB.legsFor(B.tpl, strikes, spot, names, B.width);
	if (L.error) return void put(body, h("div", { class: "note" }, L.error));
	const spec = { u: B.u, legs: L.legs, quotes: data.quotes, spot, spotAge: sq.age_s, ageAdd: Math.max(0, (Date.now() - (B.at || Date.now())) / 1000), T, lots: B.lots };
	const a = QB.analyze(spec);
	if (a.errors.length) return void put(body, h("div", { class: "note" }, a.errors[0]), legsTable2(a));
	const best = QB.suggestLots(spec);
	const kv = (k, v, cl) => h("div", { class: "row", style: "justify-content:space-between;padding:7px 16px;border-top:1px solid var(--line)" }, h("span", { class: "f3" }, k), h("b", { class: "mono " + (cl || "") }, v));
	put(body,
		h("div", { class: "panel" },
			kv(a.premium >= 0 ? "You pay" : "You receive", inr(Math.abs(a.premium))),
			kv("Worst loss", inr(-a.maxLoss), "dn"), kv("Best profit", a.unlimitedProfit ? "No cap" : inr(a.maxProfit, true), "up"),
			kv("Break-even" + (a.breakevens.length === 1 ? "" : "s"), a.breakevens.map((b) => num(b, 0)).join(" · ") || "—"),
			kv("Costs to get in and out (exit at today's price)", inr(a.cost) + ` (fees ${inr(a.fees)} + spread ${inr(a.exitSpread)})`),
			kv("Net delta · gamma", `${signed(a.greeks.delta, 1)} · ${signed(a.greeks.gamma, 3)}`), kv("Theta a day · vega per vol point", `${inr(a.greeks.theta, true)} · ${inr(a.greeks.vega, true)}`)),
		h("div", { style: "padding:8px 16px" }, bdPayoff(a, spot)),
		bdScenario(B, a, spec),
		legsTable2(a),
		h("div", { class: "grp" }, h("div", { class: "pad", style: "font-weight:600" }, "Sizing guide (the intraday desk's limits) and data quality"),
			a.checks.map((x) => h("div", { class: "row", style: "padding:6px 16px;gap:8px;align-items:flex-start" }, h("b", { class: x.ok ? "up" : "dn", style: "width:14px" }, x.ok ? "✓" : "✗"), h("span", { style: "font-size:12.5px" }, x.text)))),
		h("div", { style: "padding:10px 16px;display:flex;gap:10px;align-items:center;flex-wrap:wrap" },
			h("button", { class: "btn", onclick: () => { B.lots = Math.max(1, best); bdDraw(); }, disabled: best < 1 }, best ? `Size it to the limits: ${best} lot${best === 1 ? "" : "s"}` : "Even one lot breaks a limit"),
			h("span", { class: "f3", style: "font-size:12px" }, a.ok ? "Fits the sizing guide." : "Does not fit the sizing guide: change the structure, width or size.")),
		h("div", { class: "grp" }, h("div", { class: "pad", style: "font-weight:600;display:flex;gap:8px;align-items:center" }, "Could the paper desk open this today?", h("b", { class: a.paperOk ? "up" : "dn" }, a.paperOk ? "Yes, so far" : "No")),
			a.paperChecks.map((x) => h("div", { class: "row", style: "padding:6px 16px;gap:8px;align-items:flex-start" }, h("b", { class: x.ok ? "up" : "dn", style: "width:14px" }, x.ok ? "✓" : "✗"), h("span", { style: "font-size:12.5px" }, x.text))),
			h("div", { class: "f3", style: "font-size:11.5px;line-height:1.5;padding:4px 16px 8px" }, "The paper ticket also checks the day's loss budget, the drawdown halt and the displayed size at the touch against the live account. A structure that is not open-able today is still shown here as a what-if.")),
		bdTicket(a, tpl),
		h("div", { class: "f3", style: "font-size:11.5px;line-height:1.55;padding:6px 16px 14px" }, "Model: Black-Scholes at each leg's own implied volatility, flat rate " + (c.r * 100).toFixed(1) + "%. Buys are priced at the offer and sells at the bid; a leg with no live book is priced at its last trade and flagged. Fees use the desk's cost model. Margin for credit structures is the config estimate per lot, not the broker's figure. Held to expiry, an in-the-money long pays the exchange's exercise STT instead, which this does not model; there is no dividend yield in the pricing. Worst loss and best profit leave out costs."));
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
		h("div", { class: "f3", style: "font-size:11.5px;line-height:1.55;padding:0 16px 10px" }, "Sizes multiply the Lots below. A structure with a short call that is not covered is refused (unlimited loss). The paper desk can open it only if every leg is a purchase."));
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
async function renderBuild() {
	const body = $("#bd-body"), B = S.bd;
	if (S.tab !== "build" || document.hidden || B.busy) return;
	if (/(^|\.)github\.io$/.test(location.hostname)) { if (body.dataset.state !== "pages") { body.textContent = ""; put(body, empty("live", "The builder uses live prices, which are private and only open on the Cloudflare site, not on this address.")); body.dataset.state = "pages"; } return; }
	const key = store("qd.livekey");
	if (!key) { if (body.dataset.state !== "key") { body.textContent = ""; put(body, liveKeyForm("")); body.dataset.state = "key"; } return; }
	B.busy = true;
	let j = null, note = "";
	try {
		const r = await fetch("/live/snapshot", { headers: { Authorization: "Bearer " + key }, cache: "no-store" });
		if (r.status === 401) { try { localStorage.removeItem("qd.livekey"); } catch (e) { /* private mode */ } note = "That key was not accepted. Type it again."; }
		else if (!r.ok) note = `The live relay did not answer as expected (HTTP ${r.status}).`;
		else j = await r.json();
	} catch (e) { note = "No live prices: the request failed before any answer."; }
	finally { B.busy = false; }
	if (S.tab !== "build") return;
	if (!j) { body.textContent = ""; body.dataset.state = "note"; return void put(body, liveKeyForm(note)); }
	B.data = j; B.at = Date.now();
	body.dataset.state = "data";
	if (!B.editing) bdDraw();
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
	// a buy may fill a little above the offer shown (two ticks or 2%, whichever is more), never further: the runner refuses it if the offer has run away
	const limitFor = (ask) => Math.round(Math.ceil((ask + Math.max(2 * TICK, 0.02 * ask)) / TICK - 1e-9) * TICK * 100) / 100;
	// the orders for an analysed structure: one buy per leg. {error} when it cannot be sent.
	function ordersFor(a, strategy, thesis, group, nowMs) {
		if (!a || a.paperOk !== true || !Array.isArray(a.legs) || !a.legs.length) return { error: "The paper desk cannot open this structure today (see the list above)." };
		if (!stratOk(strategy)) return { error: "Give the strategy a name (up to 60 characters)." };
		if (!thesisOk(thesis)) return { error: "Write the thesis: why this trade, now (at least 20 characters)." };
		if (!Number.isInteger(a.lots) || a.lots < 1 || a.lots > 1000) return { error: "The number of lots must be a whole number from 1 to 1000." };
		if (a.legs.some((l) => !(l.side > 0) || typeof l.name !== "string" || typeof l.ask !== "number" || !Number.isFinite(l.ask) || !(l.ask > 0))) return { error: "Every leg must be a purchase with an offer on the board." };
		const g = group || idNow().slice(4, 20);
		// `ref`: the prices on screen when the trader decided (and when the board last heard them). It is used only to report slippage; it never prices or allows a fill.
		const refOf = (l) => (typeof l.bid === "number" && Number.isFinite(l.bid) && l.bid > 0 && l.bid <= l.ask ? { bid: l.bid, ask: l.ask, ...(Number.isFinite(nowMs) && Number.isFinite(l.age) && l.age >= 0 ? { at: Math.round(nowMs - l.age * 1000) } : {}) } : null);
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
function bdTicket(a, tpl) {
	const B = S.bd, tk = (B.tk = B.tk || { strategy: null, thesis: "", stage: "edit", sent: [], busy: false, err: "" });
	const strategy = tk.strategy == null ? tpl.name : tk.strategy;
	const box = h("div", { class: "grp" }, h("div", { class: "pad", style: "font-weight:600" }, "Send as a paper order"));
	const redraw = () => { B.editing = false; bdDraw(); };
	const sig = PT.sigOf(a);
	if (tk.sig !== sig) { if (!tk.busy) { tk.sig = sig; tk.stage = "edit"; tk.sent = []; tk.err = ""; } }       // another structure: the old review (and any "sent" screen) is void
	if (!a.paperOk) return put(box, h("div", { class: "f3", style: "font-size:12.5px;padding:2px 16px 12px" }, "Not available: the paper desk could not open this today (see the list above). It stays a what-if."));
	if (tk.stage === "sent") {
		return put(box, tk.sent.map((r) => h("div", { class: "row", style: "padding:6px 16px;gap:8px;align-items:flex-start" }, h("b", { class: r.ok ? "up" : "dn", style: "width:14px" }, r.ok ? "✓" : "✗"), h("span", { style: "font-size:12.5px" }, r.text))),
			h("div", { class: "f3", style: "font-size:12px;padding:4px 16px" }, "Queued orders are carried out by the paper runner within a few seconds, and it may still refuse them. Watch the Paper tab."),
			h("div", { style: "padding:8px 16px 14px;display:flex;gap:10px;flex-wrap:wrap" }, h("button", { class: "btn", onclick: () => show("paper") }, "Open Paper"),
				h("button", { class: "btn", onclick: () => { tk.stage = "edit"; tk.thesis = ""; tk.sent = []; redraw(); } }, "Another")));
	}
	const built = PT.ordersFor(a, strategy, tk.thesis, undefined, B.data && typeof B.data.now === "number" ? B.data.now : NaN);
	if (tk.stage === "review" && built.orders) {
		return put(box,
			h("div", { class: "f3", style: "font-size:12px;padding:6px 16px 0" }, `Strategy: ${PT.flat(strategy)}`),
			built.orders.map((o) => h("div", { class: "row", style: "padding:5px 16px;font-size:12.5px;justify-content:space-between" }, h("span", {}, `Buy ${o.lots} lot${o.lots === 1 ? "" : "s"} ${o.symbol}`), h("span", { class: "mono f3" }, `at most ${num(o.limit)}`))),
			h("div", { class: "f3", style: "font-size:12px;line-height:1.55;padding:6px 16px" }, "A buy fills at the offer plus 0 to 3 ticks, more the bigger it is against the size shown; the Paper tab keeps the price you saw against what you paid."),
			h("div", { class: "f3", style: "font-size:12px;line-height:1.55;padding:6px 16px" }, `Most you can lose, at the offers shown: ${inr(a.maxLoss)} plus ${inr(a.entryFees)} of fees; a fill can be a little dearer, up to the limits above. Paper money. "${PT.flat(tk.thesis)}"`),
			tk.err ? h("div", { class: "warn", style: "font-size:12.5px;padding:2px 16px" }, tk.err) : null,
			h("div", { style: "padding:8px 16px 14px;display:flex;gap:10px;flex-wrap:wrap" },
				h("button", { class: "btn", disabled: tk.busy, onclick: async (ev) => {
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
	const ta = h("textarea", { class: "search", rows: "3", maxlength: "1000", "aria-label": "Thesis: why this trade, now", placeholder: "Why this trade, now? What would make you wrong?", style: "width:100%;resize:vertical;font:inherit", oninput: (e) => { tk.thesis = e.target.value; const ok = PT.thesisOk(tk.thesis); cnt.textContent = ok ? "Thesis written." : `${PT.flat(tk.thesis).length} of at least 20 characters`; rv.disabled = !(PT.stratOk(tk.strategy == null ? tpl.name : tk.strategy) && ok); }, onfocus: () => { B.editing = true; }, onblur: () => { B.editing = false; } }, tk.thesis);
	const cnt = h("div", { class: "f3", style: "font-size:11.5px;padding:2px 0" }, PT.thesisOk(tk.thesis) ? "Thesis written." : `${PT.flat(tk.thesis).length} of at least 20 characters`);
	const rv = h("button", { class: "btn", disabled: !!built.error, onclick: () => { tk.stage = "review"; tk.err = ""; redraw(); } }, "Review order");
	inp.addEventListener("focus", () => { B.editing = true; }); inp.addEventListener("blur", () => { B.editing = false; });
	return put(box, h("div", { style: "padding:2px 16px 14px;display:flex;flex-direction:column;gap:8px" },
		h("label", { class: "f3", style: "font-size:12px" }, "Strategy name"), inp, h("label", { class: "f3", style: "font-size:12px" }, "Thesis (required: it is kept with the trade)"), ta, cnt, rv));
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
	const age = ppAge(sm);
	const tagC = (k, t) => h("span", { class: "tag " + k }, t);
	put(body, h("div", { class: "note" }, "Paper money only. Orders are carried out by the paper runner through the risk gate: the gate, not this page, decides. Nothing here can reach a broker."));
	if (!sm) put(body, h("div", { class: "note warn" }, "The paper runner has not reported yet. Orders wait two minutes, then expire. It starts by itself on trading days from about 08:30."));
	else if (inSession() && !(age < 45)) put(body, h("div", { class: "note warn" }, `The paper runner last reported ${liveAge(age)} ago. If it is not running, orders will expire unfilled.`));
	if (sm && sm.stuck && sm.stuck.length) put(body, h("div", { class: "note warn" }, `Held past expiry with no price: ${sm.stuck.join(", ")}. New orders are refused until this is settled.`));
	if (sm) put(body, h("div", { class: "panel" },
		kv("Equity", fin(sm.equity) ? inr(sm.equity) : "unknown (a position has no price)"), kv("Profit since the start", fin(sm.net_pnl) ? inr(sm.net_pnl, true) : "—", fin(sm.net_pnl) ? (sm.net_pnl >= 0 ? "up" : "dn") : ""),
		kv("Today", fin(sm.equity) && fin(sm.day_start) ? inr(sm.equity - sm.day_start, true) : "—"), kv("Cash", inr(sm.cash)), kv("Fees paid", inr(sm.fees)),
		kv("Stops for the day below", fin(sm.day_floor) ? inr(sm.day_floor) : "—"), kv("Halts below", fin(sm.dd_floor) ? inr(sm.dd_floor) : "—"),
		sm.day_halted ? kv("Today", "stopped: the daily loss limit was hit", "dn") : null, sm.halt ? kv("Drawdown halt", "ON: only the owner clears it", "dn") : null));
	const sl = sm && sm.slippage;
	if (sl && sl.fills > 0) {
		const bpsTxt = fin(sl.bps) ? `${sl.bps} bps of the value traded` : "";
		put(body, h("div", { class: "grp" }, h("div", { class: "pad", style: "font-weight:600" }, `Slippage (${sl.fills} fill${sl.fills === 1 ? "" : "s"})`),
			kv("Total cost vs the price you saw", inr(sl.total_inr), sl.total_inr > 0 ? "dn" : ""), kv("Spread paid (measured)", inr(sl.spread_inr)),
			kv(`Price moved before the fill (measured, ${sl.fills_with_decision_price} of ${sl.fills})`, inr(sl.delay_inr, true)), kv("Size impact (a model, not measured)", inr(sl.impact_inr)),
			bpsTxt ? h("div", { class: "f3", style: "font-size:12px;padding:4px 16px" }, bpsTxt) : null,
			(d.summary.slips || []).slice().reverse().map((r) => h("div", { class: "row", style: "padding:4px 16px;font-size:12px;justify-content:space-between;gap:8px;border-top:1px solid var(--line)" },
				h("span", { class: "mono" }, `#${r.seq} ${r.side} ${r.symbol || ""}`), h("span", { class: "mono f3" }, `${fin(r.total_inr) ? inr(r.total_inr) : "—"}${fin(r.delay_s) ? " · " + r.delay_s + "s" : ""}${r.impact_ticks ? " · +" + r.impact_ticks + " tick" + (r.impact_ticks === 1 ? "" : "s") : ""}`))),
			h("div", { class: "f3", style: "font-size:11.5px;line-height:1.55;padding:6px 16px 12px" }, "Positive is a cost. The spread and the price move come from the live board. The size impact is a conservative model (the board shows only the best price and its size) and is shown apart so it is never mistaken for an observation.")));
	}
	const killOn = d ? d.kill === true : false;
	put(body, h("div", { class: "panel pad", style: "display:flex;gap:10px;align-items:center;flex-wrap:wrap" },
		h("b", {}, "Kill switch"), killOn ? tagC("bear", "ON: nothing opens, everything is sold") : tagC("bull", "off"),
		P.confirm === (killOn ? "kill:off" : "kill:on") ? h("span", { style: "display:flex;gap:8px" }, h("button", { class: "btn", onclick: async (ev) => { if (P.acting) return; P.acting = true; if (ev && ev.currentTarget) ev.currentTarget.disabled = true; P.confirm = null; const r = await paperCall("POST", "/paper/kill", { on: !killOn }); P.acting = false; P.note = r.status === 200 ? "" : "The kill switch could not be changed (" + ((r.body && r.body.error) || "HTTP " + r.status) + ")."; renderPaper(true); } }, killOn ? "Yes, resume trading" : "Yes, stop and sell everything"), h("button", { class: "btn", onclick: () => { P.confirm = null; ppDraw(); } }, "Cancel"))
			: h("button", { class: "btn", onclick: () => { P.confirm = killOn ? "kill:off" : "kill:on"; P.confirmAt = Date.now(); ppDraw(); } }, killOn ? "Resume trading" : "Stop all trading and sell everything")));
	if (P.note) put(body, h("div", { class: "note warn" }, P.note));
	const pos = sm && sm.positions ? sm.positions : [];
	put(body, h("div", { class: "grp" }, h("div", { class: "pad", style: "font-weight:600" }, `Positions (${pos.length})`),
		pos.length ? pos.map((p) => h("div", { class: "pad", style: "border-top:1px solid var(--line)" },
			h("div", { class: "row", style: "justify-content:space-between;align-items:center;gap:8px" }, h("b", { class: "mono", style: "font-size:13px" }, p.symbol),
				h("span", { class: "mono " + (fin(p.pnl) ? (p.pnl >= 0 ? "up" : "dn") : "f3") }, fin(p.pnl) ? inr(p.pnl, true) : "no price")),
			h("div", { class: "f3", style: "font-size:12px;line-height:1.5" }, `${p.lots} lot${p.lots === 1 ? "" : "s"} (${p.qty} units) · bought at ${num(p.avg)} · bid ${fin(p.mark) ? num(p.mark) : "—"} · expires ${p.expiry || "?"} · ${p.strategy || ""}`),
			h("div", { class: "f3", style: "font-size:12px;line-height:1.5;margin-top:2px" }, p.thesis || ""),
			P.confirm === "sell:" + p.symbol ? h("div", { style: "display:flex;gap:8px;margin-top:6px" },
				h("button", { class: "btn", onclick: async (ev) => { if (P.acting) return; P.acting = true; if (ev && ev.currentTarget) ev.currentTarget.disabled = true; P.confirm = null; const o = PT.sellFor(p.symbol); const r = await paperCall("POST", "/paper/order", o); P.acting = false; P.note = r.status === 200 ? "" : "The sell was not queued (" + ((r.body && r.body.error) || "HTTP " + r.status) + ")."; renderPaper(true); } }, "Yes, sell all at the bid"),
				h("button", { class: "btn", onclick: () => { P.confirm = null; ppDraw(); } }, "Cancel"))
				: h("button", { class: "btn", style: "margin-top:6px", onclick: () => { P.confirm = "sell:" + p.symbol; P.confirmAt = Date.now(); ppDraw(); } }, "Sell all")))
			: h("div", { class: "f3", style: "font-size:12.5px;padding:2px 16px 12px" }, "Nothing held.")));
	const pend = d && d.pending ? d.pending : [], res = d && d.results ? d.results.slice(-10).reverse() : [];
	put(body, h("div", { class: "grp" }, h("div", { class: "pad", style: "font-weight:600" }, "Orders"),
		pend.map((o) => h("div", { class: "row", style: "padding:5px 16px;font-size:12.5px;justify-content:space-between" }, h("span", { class: "mono" }, `${o.side} ${o.lots} ${o.symbol}`), tagC("flat", "waiting"))),
		res.map((r) => h("div", { style: "padding:5px 16px;border-top:1px solid var(--line)" },
			h("div", { class: "row", style: "justify-content:space-between;font-size:12.5px" }, h("span", { class: "mono" }, r.fill && r.fill.symbol ? `${r.fill.kind || ""} ${r.fill.qty || ""} ${r.fill.symbol}` : r.id), tagC(r.status === "filled" ? "bull" : r.status === "done" ? "flat" : "bear", r.status)),
			r.fill && fin(r.fill.price) ? h("div", { class: "f3", style: "font-size:12px" }, `at ${num(r.fill.price)} · fees ${fin(r.fill.fees) ? num(r.fill.fees) : "—"}`) : null,
			(r.reasons || []).map((x) => h("div", { class: "f3", style: "font-size:12px;line-height:1.5" }, x)))),
		!pend.length && !res.length ? h("div", { class: "f3", style: "font-size:12.5px;padding:2px 16px 12px" }, "No orders yet.") : null));
	const tail = sm && sm.ledger_tail ? sm.ledger_tail.slice(-10).reverse() : [];
	put(body, h("div", { class: "grp" }, h("div", { class: "pad", style: "font-weight:600" }, `Ledger (${sm ? sm.ledger_len : 0} rows, ${sm && sm.ledger_ok ? "chain verified" : "NOT verified"})`),
		tail.map((r) => h("div", { class: "row", style: "padding:4px 16px;font-size:12px;justify-content:space-between;gap:8px" }, h("span", { class: "mono" }, `#${r.seq} ${r.kind}${r.symbol ? " " + r.symbol : ""}`), h("span", { class: "mono f3" }, fin(r.price) ? `${r.qty} @ ${num(r.price)}` : ""))),
		!tail.length ? h("div", { class: "f3", style: "font-size:12.5px;padding:2px 16px 12px" }, "Empty.") : null));
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
		else if (t === "build") await renderBuild();
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
