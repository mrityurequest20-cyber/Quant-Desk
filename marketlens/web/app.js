/* MarketLens app: a static, read-only analysis site over data/overview.json and data/sym/<SYMBOL>.json. */
"use strict";

// ---------------------------------------------------------------- state & utils
const S = {
  mode: lsGet("ml.mode", "simple"),
  horizon: lsGet("ml.h", "1Y"),
  overview: null,
  sym: {},
  charts: [],
};
function lsGet(k, d) { try { return localStorage.getItem(k) || d; } catch (e) { return d; } }
function lsSet(k, v) { try { localStorage.setItem(k, v); } catch (e) {} }
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const fin = (x) => x !== null && x !== undefined && isFinite(x);
const pct = (x, d = 1) => (fin(x) ? (x * 100).toFixed(d) + "%" : "—");
const vp = (x, d = 1) => (fin(x) ? (x * 100 >= 0 ? "+" : "") + (x * 100).toFixed(d) : "—");
const num = (x, d = 0) => (fin(x) ? Number(x).toLocaleString("en-IN", { maximumFractionDigits: d, minimumFractionDigits: d }) : "—");
const big = (x) => { if (!fin(x)) return "—"; const a = Math.abs(x); return a >= 1e7 ? (x / 1e7).toFixed(2) + " cr" : a >= 1e5 ? (x / 1e5).toFixed(2) + " L" : a >= 1e3 ? (x / 1e3).toFixed(1) + "k" : num(x); };
const ord = (p) => { if (!fin(p)) return "—"; const n = Math.round(p * 100); const s = n % 100 >= 11 && n % 100 <= 13 ? "th" : { 1: "st", 2: "nd", 3: "rd" }[n % 10] || "th"; return n + s; };
const level = (p) => !fin(p) ? "unknown" : p < .1 ? "very low" : p < .3 ? "low" : p <= .7 ? "normal" : p <= .9 ? "high" : "very high";
const toneOf = (p) => !fin(p) ? "" : Math.abs(p - .5) >= .4 ? "extreme" : Math.abs(p - .5) >= .2 ? "elevated" : "";
const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
const slug = (s) => s.replace("&", "_");

async function getJSON(p) { const r = await fetch(p, { cache: "no-cache" }); if (!r.ok) throw new Error(p + " " + r.status); return r.json(); }
async function overview() { if (!S.overview) S.overview = await getJSON("data/overview.json"); return S.overview; }
async function symData(s) { if (!S.sym[s]) S.sym[s] = await getJSON(`data/sym/${slug(s)}.json`); return S.sym[s]; }

// ---------------------------------------------------------------- charts
function disposeCharts() { S.charts.forEach((c) => c.dispose()); S.charts = []; }
window.addEventListener("resize", () => S.charts.forEach((c) => c.resize()));

function theme() {
  return {
    text: css("--text"), text2: css("--text-2"), text3: css("--text-3"), line: css("--line"), line2: css("--line-2"),
    surface: css("--surface"), s1: css("--s1"), s2: css("--s2"), s3: css("--s3"), s4: css("--s4"), s7: css("--s7"),
    pos: css("--pos"), neg: css("--neg"), dpos: css("--div-pos"), dneg: css("--div-neg"), dmid: css("--div-mid"),
  };
}

function chart(el, opt) {
  if (typeof el === "string") el = $(el);
  if (!el || !window.echarts) return null;
  const t = theme();
  const c = echarts.init(el, null, { renderer: "canvas" });
  const base = {
    animationDuration: 300,
    textStyle: { fontFamily: "Inter, system-ui, sans-serif", color: t.text2 },
    grid: { left: 52, right: 18, top: 24, bottom: 30, containLabel: false },
    tooltip: {
      trigger: "axis", backgroundColor: t.surface, borderColor: t.line, textStyle: { color: t.text, fontSize: 12 },
      axisPointer: { type: "line", lineStyle: { color: t.text3, type: "dashed" } }, confine: true,
    },
  };
  if (opt.xAxis && opt.xAxis.name && !opt.grid) base.grid = { ...base.grid, bottom: 44 };     // room for a named x axis ("days to expiry")
  S.charts.push(c);
  try { c.setOption(Object.assign(base, opt)); }
  catch (e) { console.error("chart " + (el.id || "?") + ": " + e.message); el.innerHTML = `<div class="muted small" style="padding:20px">This chart could not be drawn.</div>`; }
  return c;
}

function axisX(dates, t, extra = {}) {
  return Object.assign({ type: "category", data: dates, boundaryGap: false, axisLine: { lineStyle: { color: t.line } },
    axisTick: { show: false }, axisLabel: { color: t.text3, hideOverlap: true, fontSize: 11 } }, extra);
}
function axisY(t, fmt, extra = {}) {
  return Object.assign({ type: "value", scale: true, splitLine: { lineStyle: { color: t.line2 } }, axisLine: { show: false, onZero: false }, axisTick: { show: false },
    axisLabel: { color: t.text3, fontSize: 11, formatter: fmt } }, extra);
}
const fmtPct = (d = 0) => (v) => (v * 100).toFixed(d) + "%";
function line(name, data, color, extra = {}) {
  return Object.assign({ name, type: "line", data, showSymbol: false, symbolSize: 8, connectNulls: true, smooth: false,
    lineStyle: { width: 2, color }, itemStyle: { color }, emphasis: { focus: "series" } }, extra);
}

// dates where the exchange changed how many expiries it lists: total OI and PCR change level there for that reason
function regimeMarks(d, dates, t) {
  const r = (d.meta.regimes || []).filter((x) => dates.includes(x.date));
  return r.length ? { silent: true, symbol: "none", lineStyle: { color: t.text3, type: "dotted" },
    label: { formatter: (p) => p.data.name, color: t.text3, fontSize: 10, position: "insideEndTop" },
    data: r.map((x) => ({ xAxis: x.date, name: `expiries listed ${x.from}→${x.to}` })) } : undefined;
}
const ma = (a, n) => a.map((_, i) => { const w = a.slice(Math.max(0, i - n + 1), i + 1).filter(fin); return w.length >= Math.min(n, 3) ? w.reduce((x, y) => x + y, 0) / w.length : null; });

// slice a {d: [...], col: [...]} series by the chosen horizon
const H = { "3M": 63, "6M": 126, "1Y": 252, "3Y": 756, "All": 1e9 };
function slice(ser, cols, horizon = S.horizon) {
  const n = ser.d.length, k = Math.max(0, n - H[horizon]);
  const out = { d: ser.d.slice(k) };
  cols.forEach((c) => (out[c] = (ser[c] || []).slice(k)));
  return out;
}

// ---------------------------------------------------------------- UI bits
function pbar(p, lo = "low", hi = "high") {
  if (!fin(p)) return `<div class="muted small">not enough history</div>`;
  return `<div class="pbar"><i style="left:${(p * 100).toFixed(1)}%"></i></div><div class="pbar-l"><span>${lo}</span><span>${ord(p)} percentile</span><span>${hi}</span></div>`;
}
function chipP(p, label) {
  if (!fin(p)) return "";
  return `<span class="chip ${toneOf(p)}"><span class="dot"></span>${label || level(p)}</span>`;
}
function card({ title, hint = "", body = "", simple = "", analyst = "", chip = "", cls = "" }) {
  const csv = /class="(tbl|chart)/.test(body) ? `<button class="icon-btn csv" title="Download this card's data as CSV" aria-label="Download CSV" data-csv="${esc(String(title).replace(/<[^>]+>/g, ""))}">CSV</button>` : "";
  return `<section class="card ${cls}"><div class="card-h"><h3>${title}${hint ? ` <span class="hint">${hint}</span>` : ""}</h3><span class="card-tools">${chip}${csv}</span></div>
    ${simple ? `<p class="simple">${esc(simple)}</p>` : ""}${body}${analyst ? `<p class="analyst">${esc(analyst)}</p>` : ""}</section>`;
}
function kpi({ label, value, unit = "", foot = "", p = null, lo, hi, chipLabel }) {
  return `<section class="card kpi"><div class="lab"><span>${label}</span>${chipP(p, chipLabel)}</div>
    <div class="val num">${value}${unit ? `<small>${unit}</small>` : ""}</div>${p !== null ? pbar(p, lo, hi) : ""}
    ${foot ? `<div class="foot">${foot}</div>` : ""}</section>`;
}
function horizonSeg() {
  return `<div class="seg" id="hseg">${Object.keys(H).map((h) => `<button data-h="${h}" class="${h === S.horizon ? "on" : ""}">${h}</button>`).join("")}</div>`;
}
function bindHorizon(rerender) {
  $$("#hseg button").forEach((b) => b.onclick = () => { S.horizon = b.dataset.h; lsSet("ml.h", S.horizon); rerender(); });
}

// ---------------------------------------------------------------- shell
function renderNav(ov, active) {
  const idx = ov.universe.filter((u) => u.kind === "index");
  const stk = ov.universe.filter((u) => u.kind === "stock");
  const m = Object.fromEntries(ov.screener.map((x) => [x.symbol, x]));
  // in the session the sidebar's day change is the live one, like every other price on screen
  const live = window.MLLive && MLLive.state.mode === "live" ? MLLive.state.reads : null;
  const chgOf = (sym) => (live && live[sym] && live[sym].spotChg !== null ? live[sym].spotChg : m[sym]?.chg);
  const a = (href, label, tag = "") => `<a href="${href}" class="${active === href ? "on" : ""}">${label}${tag ? `<span class="tag">${tag}</span>` : ""}</a>`;
  $("#nav").innerHTML = `
    <div class="nav-h">Market</div>
    ${a("#/pulse", "Market pulse")}${a("#/screener", "Volatility screener")}${a("#/positioning", "Who holds what")}
    ${a("#/breadth", "Whole F&O market")}${a("#/commodities", "Commodities (MCX)")}${a("#/flows", "FII / DII money")}${a("#/calendar", "Calendar")}${a("#/alerts", "Alerts")}${a("#/compare", "Compare")}${a("#/health", "Data health")}
    <div class="nav-h">Indices</div>
    ${idx.map((u) => a(`#/sym/${u.slug}`, u.symbol, vp(chgOf(u.symbol), 1) + "%")).join("")}
    <div class="nav-h">Stocks</div>
    ${stk.map((u) => a(`#/sym/${u.slug}`, u.symbol, vp(chgOf(u.symbol), 1) + "%")).join("")}
    <div class="nav-h">Help</div>${a("#/method", "How to read this")}`;
}

function setupShell(ov) {
  $("#asof").textContent = `Data as of ${ov.asof} close`;
  const q = $("#q"), res = $("#qres");
  q.oninput = () => {
    const v = q.value.trim().toUpperCase();
    if (!v) { res.style.display = "none"; return; }
    const hits = ov.universe.filter((u) => u.symbol.includes(v) || u.name.toUpperCase().includes(v)).slice(0, 8);
    res.innerHTML = hits.map((u, i) => `<a href="#/sym/${u.slug}" class="${i ? "" : "hi"}"><b>${u.symbol}</b><span class="muted">${esc(u.name)}</span></a>`).join("") || `<a class="muted">No match</a>`;
    res.style.display = "block";
  };
  q.onkeydown = (e) => { if (e.key === "Enter") { const h = $("a", res); if (h && h.getAttribute("href")) { location.hash = h.getAttribute("href"); q.value = ""; res.style.display = "none"; } } };
  document.addEventListener("click", (e) => { if (!e.target.closest(".search")) res.style.display = "none"; });
  $$("#modeSeg button").forEach((b) => b.onclick = () => { S.mode = b.dataset.mode; lsSet("ml.mode", S.mode); applyMode(); route(); });
  $("#themeBtn").onclick = () => {
    const cur = document.documentElement.dataset.theme || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
    document.documentElement.dataset.theme = cur === "dark" ? "light" : "dark"; lsSet("ml.theme", document.documentElement.dataset.theme); route();
  };
  $("#menuBtn").onclick = () => document.body.classList.toggle("nav-open");
  applyMode();
}
function applyMode() {
  document.body.classList.toggle("mode-simple", S.mode === "simple");
  $$("#modeSeg button").forEach((b) => b.classList.toggle("on", b.dataset.mode === S.mode));
}

// ---------------------------------------------------------------- pages: pulse
async function pagePulse(app, ov) {
  $("#crumbs").textContent = "Market pulse";
  const m = Object.fromEntries(ov.screener.map((x) => [x.symbol, x]));
  const n = m.NIFTY || {}, bn = m.BANKNIFTY || {};
  const fiiLS = ov.participants?.rows?.find((r) => r.who === "FII" && r.metric === "idx_fut_long_share");
  const fl = ov.flows?.FII;
  app.innerHTML = `
    <div class="page-h"><div><h1>Market pulse</h1><div class="sub">What the derivatives market is pricing, and how unusual it is. Live panels refresh every 5 seconds in the session; the analysis below is at the close of ${ov.asof}.</div></div></div>
    ${liveSlot({ kind: "pulse", ov })}
    <div class="grid g4">
      ${kpi({ label: "India VIX (fear gauge)", value: num(ov.vix.now, 2), p: ov.vix.p1y, lo: "calm", hi: "fearful",
        foot: `≈ ${(ov.vix.now / Math.sqrt(252)).toFixed(2)}% expected NIFTY move a day` })}
      ${kpi({ label: `NIFTY: priced move to expiry`, value: "±" + pct(n.move, 1), unit: `${n.move_days}d`,
        foot: `About ±${num(n.spot * n.move)} points. Inside it ${pct(n.inside, 0)} of the time historically` })}
      ${kpi({ label: "FIIs: long share, index futures", value: pct(fiiLS?.now, 0), p: fiiLS?.pct1y, lo: "short-heavy", hi: "long-heavy",
        foot: `vs the past year · 5-day change ${vp(fiiLS?.chg5)} pts` })}
      ${kpi({ label: "FII cash: last 5 sessions", value: (fl ? (fl.sum5 >= 0 ? "+" : "−") + "₹" + num(Math.abs(fl.sum5)) : "—"), unit: "cr",
        foot: fl ? `${fl.streak} day${fl.streak > 1 ? "s" : ""} of ${fl.streak_side} in a row` : "" })}
    </div>
    <div class="grid g2" style="margin-top:16px">
      ${card({ title: "Today in plain words", body: `<ul class="story">${ov.pulse.map((s) => `<li>${esc(s)}</li>`).join("")}</ul>` })}
      ${card({ title: "Options map", hint: "every instrument, one dot", simple: "Right = options expensive for that name (vs its own last year). Up = the price has really been moving a lot. Top-right: expensive for a reason. Bottom-right: expensive while calm.",
        body: `<div class="chart tall" id="map"></div><div class="legend"><span style="--c:${css("--s1")}">Indices</span><span style="--c:${css("--s2")}">Stocks</span></div>` })}
    </div>
    <div style="margin-top:16px">${card({ title: "What changed since yesterday", hint: "the day's most unusual moves, each against its own history",
      simple: "Only changes that are big for that particular instrument make this list: a 2-sigma day is one that happens about once a month for it.",
      body: (ov.changes || []).length ? `<ul class="story">${ov.changes.map((c) => `<li><a href="#/sym/${slug(c.symbol)}"><b>${esc(c.symbol)}</b></a> · ${esc(c.text.replace(c.symbol + ": ", ""))} <span class="chip ${Math.abs(c.z) >= 2.5 ? "extreme" : "elevated"}">${Math.abs(c.z).toFixed(1)}σ</span></li>`).join("")}</ul>` : `<div class="muted">A quiet day: no reading moved unusually for its instrument.</div>`,
      analyst: "Size of a change = the day's change divided by the standard deviation of that instrument's daily changes over the past year. Readings: 30-day IV, 25-delta risk reversal, 21-day realised vol." })}</div>
    ${limitsCard(ov)}
    <div class="grid g2" style="margin-top:16px">
      ${card({ title: "India VIX since 2019", hint: "the market's 30-day fear gauge", body: `<div class="chart" id="vix"></div>`,
        analyst: "India VIX is computed by NSE from NIFTY option prices across strikes (like the US VIX). Spikes mark stress (Mar 2020, Jun 2024 election). It mean-reverts: very high readings have historically come down faster than very low ones went up." })}
      ${card({ title: "Next on the calendar", body: calendarRows(ov.calendar.items.slice(0, 9)) + `<div style="margin-top:10px"><a class="muted small" href="#/calendar">Full calendar →</a></div>` })}
    </div>
    <div style="margin-top:16px">${screenerCard(ov, 10)}</div>`;
  const t = theme();
  // options map
  const pts = ov.screener.filter((x) => fin(x.iv_p1y) && fin(x.rv_p));
  const mk = (kind, color) => ({ name: kind === "index" ? "Indices" : "Stocks", type: "scatter", symbolSize: 11, itemStyle: { color, borderColor: t.surface, borderWidth: 2 },
    data: pts.filter((x) => x.kind === kind).map((x) => ({ value: [x.iv_p1y, x.rv_p], name: x.symbol, slug: x.slug })),
    label: { show: true, formatter: (p) => p.name, position: "right", color: t.text2, fontSize: 10.5 }, labelLayout: { hideOverlap: true } });
  const c = chart("#map", {
    grid: { left: 44, right: 20, top: 16, bottom: 40 },
    tooltip: { trigger: "item", formatter: (p) => { const x = pts.find((z) => z.symbol === p.name); return `<b>${p.name}</b><br>IV30 ${pct(x.iv30)} · ${ord(x.iv_p1y)} pct (1y)<br>Realised 21d ${pct(x.rv21)} · ${ord(x.rv_p)} pct<br>IV − RV ${vp(x.vrp)} vol pts`; } },
    xAxis: { type: "value", min: 0, max: 1, name: "Options price (IV percentile, 1y) →", nameLocation: "middle", nameGap: 26, nameTextStyle: { color: t.text3, fontSize: 11 },
      axisLabel: { formatter: (v) => ord(v), color: t.text3, fontSize: 10 }, splitLine: { lineStyle: { color: t.line2 } } },
    yAxis: { type: "value", min: 0, max: 1, name: "Actual movement →", nameTextStyle: { color: t.text3, fontSize: 11 }, axisLabel: { formatter: (v) => ord(v), color: t.text3, fontSize: 10 }, splitLine: { lineStyle: { color: t.line2 } } },
    series: [mk("index", t.s1), mk("stock", t.s2),
      { type: "line", silent: true, data: [], markLine: { silent: true, symbol: "none", lineStyle: { color: t.text3, type: "dashed", width: 1 }, label: { show: false }, data: [{ xAxis: .5 }, { yAxis: .5 }] } }],
  });
  c && c.on("click", (p) => p.data?.slug && (location.hash = `#/sym/${p.data.slug}`));
  const vx = ov.vix.series;
  chart("#vix", { xAxis: axisX(vx.d, t), yAxis: axisY(t, (v) => v), dataZoom: [{ type: "inside" }],
    series: [line("India VIX", vx.vix, t.s1, { areaStyle: { color: t.s1, opacity: .08 } })] });
  bindScreener(ov);
}

function limitsCard(ov) {
  const L = ov.limits || {};
  if (!L.available) return "";
  const ban = L.ban || [];
  const near = (L.near || []).filter((x) => !x.in_ban);
  return `<div style="margin-top:16px">${card({ title: "F&O ban & position limits", hint: L.ban_date ? `NSE's ban list for ${L.ban_date}` : "",
    simple: ban.length ? `In the F&O ban: no new positions can be opened in these, only existing ones reduced. ${ban.length} stock${ban.length > 1 ? "s" : ""} in all.` : "No stock is in the F&O ban.",
    body: `${ban.length ? `<div style="display:flex;flex-wrap:wrap;gap:6px;margin-bottom:12px">${ban.map((b) => `<span class="chip extreme">${esc(b)}</span>`).join("")}</div>` : ""}
      ${near.length ? `<div class="muted small" style="margin-bottom:4px">Covered stocks with the most of their limit used</div><ul class="story">${near.slice(0, 6).map((x) => `<li><a href="#/sym/${slug(x.symbol)}"><b>${esc(x.symbol)}</b></a> · ${pct(x.util, 0)} of its market-wide limit${fin(x.chg5) ? ` <span class="muted">(${vp(x.chg5, 0)} pts in 5 sessions)</span>` : ""}${x.util >= .8 ? ` <span class="chip elevated">near ban</span>` : ""}</li>`).join("")}</ul>` : ""}`,
    analyst: "A stock enters the ban when its open interest crosses 95% of its market-wide position limit (MWPL) and leaves when it falls below 80%. The ban itself is read from NSE's own list, never inferred. Limits are from NSE's combined open interest file" + (L.mwpl_date ? ` of ${L.mwpl_date}.` : ".") })}</div>`;
}
function calendarRows(items) {
  if (!items.length) return `<div class="muted">Nothing scheduled in the data.</div>`;
  const lab = { expiry: "Expiry", results: "Results", holiday: "Holiday", lot: "Lot change" };
  return items.map((i) => `<div class="cal-row"><span class="num">${i.date}</span><span class="chip ${i.type === "results" || i.type === "lot" ? "elevated" : ""}">${lab[i.type] || i.type}</span>
    <span>${i.symbol ? `<a href="#/sym/${slug(i.symbol)}"><b>${esc(i.symbol)}</b></a> · ` : ""}${esc(i.symbol ? i.text.replace(i.symbol + " ", "") : i.text)}</span></div>`).join("");
}

// ---------------------------------------------------------------- screener
const COLS = [
  { k: "symbol", lab: "Instrument" },
  { k: "spot", lab: "Price", f: (x) => num(x.spot, x.spot > 1000 ? 0 : 2) },
  { k: "chg", lab: "Day", f: (x) => `<span class="chg ${x.chg >= 0 ? "pos" : "neg"}">${vp(x.chg, 2)}%</span>` },
  { k: "iv30", lab: "IV 30d", f: (x) => pct(x.iv30) },
  { k: "iv_p1y", lab: "IV pct 1y", f: (x) => pcell(x.iv_p1y) },
  { k: "rv21", lab: "Realised 21d", f: (x) => pct(x.rv21) },
  { k: "vrp", lab: "IV − RV", f: (x) => vp(x.vrp) },
  { k: "move", lab: "Priced move", f: (x) => fin(x.move) ? `±${pct(x.move, 1)} <span class="muted small">${x.move_days ?? ""}d</span>` : "—" },
  { k: "rr25", lab: "Skew (RR)", f: (x) => vp(x.rr25) },
  { k: "pcr_p", lab: "PCR pct 1y", f: (x) => pcell(x.pcr_p), a: 1 },
  { k: "carry", lab: "Futures carry", f: (x) => pct(x.carry), a: 1 },
  { k: "buildup", lab: "Futures today", f: (x) => x.buildup ? `<span class="bu">${x.buildup}</span>` : "—", a: 1 },
  { k: "mwpl_util", lab: "Limit used", f: (x) => x.in_ban ? `<span class="chip extreme">BAN</span>` : fin(x.mwpl_util) ? `<span class="${x.mwpl_util >= .8 ? "chg neg" : ""}">${pct(x.mwpl_util, 0)}</span>` : "—" },
  { k: "results", lab: "Results", f: (x) => x.results ? `<span class="chip elevated">${x.results.slice(5)}</span>` : (x.event === "results" ? `<span class="chip elevated">results priced</span>` : x.event ? `<span class="chip">front premium</span>` : "") },
];
function pcell(p) {
  if (!fin(p)) return "—";
  const col = p >= .5 ? css("--div-neg") : css("--div-pos");
  const w = Math.abs(p - .5) * 2 * 100;
  return `<span class="cell-p"><span class="num">${ord(p)}</span><span class="mini"><b style="left:${p >= .5 ? 50 : 50 - w / 2}%;width:${w / 2}%;background:${col}"></b></span></span>`;
}
let sortKey = "iv_p1y", sortDir = -1;
function screenerCard(ov, limit) {
  const cols = COLS.filter((c) => !c.a || S.mode === "analyst");
  let rows = [...ov.screener].sort((a, b) => ((a[sortKey] ?? -1e9) > (b[sortKey] ?? -1e9) ? 1 : -1) * sortDir);
  if (sortKey === "symbol") rows.sort((a, b) => a.symbol.localeCompare(b.symbol) * sortDir);
  if (limit) rows = rows.slice(0, limit);
  return card({ title: limit ? "Where options are most unusual" : "All instruments", hint: "click a column to sort · click a row to open",
    simple: limit ? "Sorted by how expensive options are against each name's own past year. 'IV − RV' is how much more (or less) options charge than the price has actually been moving." : "",
    body: `<div class="tbl-wrap"><table class="tbl" id="scr"><thead><tr>${cols.map((c) => `<th data-k="${c.k}">${c.lab}${sortKey === c.k ? (sortDir > 0 ? " ↑" : " ↓") : ""}</th>`).join("")}</tr></thead>
    <tbody>${rows.map((x) => `<tr data-s="${x.slug}" style="cursor:pointer">${cols.map((c) => c.k === "symbol" ? `<td><span class="sym">${x.symbol}</span><span class="nm">${esc(x.name)}</span></td>` : `<td class="num">${c.f(x)}</td>`).join("")}</tr>`).join("")}</tbody></table></div>
    ${limit ? `<div style="margin-top:10px"><a class="muted small" href="#/screener">All ${ov.screener.length} instruments →</a></div>` : ""}` });
}
function bindScreener(ov) {
  $$("#scr th").forEach((th) => th.onclick = () => { const k = th.dataset.k; sortDir = sortKey === k ? -sortDir : -1; sortKey = k; route(); });
  $$("#scr tbody tr").forEach((tr) => tr.onclick = () => (location.hash = `#/sym/${tr.dataset.s}`));
}
async function pageScreener(app, ov) {
  $("#crumbs").textContent = "Volatility screener";
  app.innerHTML = `<div class="page-h"><div><h1>Volatility screener</h1><div class="sub">Every covered index and stock, side by side. Percentiles compare each name with its own past year.</div></div></div>
    ${liveSlot({ kind: "screener", ov })}
    ${screenerCard(ov)}
    <div class="callout" style="margin-top:16px">Reading it: <b>IV</b> is what options charge (annualised). <b>Realised</b> is how much the price actually moved. <b>IV − RV</b> above zero means options are pricier than recent movement: normal, because sellers want paying for risk. <b>Skew (RR)</b> below zero means downside protection costs more than upside calls.</div>`;
  bindScreener(ov);
}

// ---------------------------------------------------------------- positioning
async function pagePositioning(app, ov) {
  $("#crumbs").textContent = "Who holds what";
  if (!S.partSeries) { try { S.partSeries = (await getJSON("data/participants.json")).series; } catch (e) { S.partSeries = {}; } }
  const P = { ...ov.participants, series: ov.participants.series || S.partSeries };
  const rows = P.rows;
  const show = ["idx_fut_long_share", "idx_fut_net", "idx_opt_stance", "stk_fut_net"];
  const who = ["FII", "Client", "Pro", "DII"];
  const nice = { FII: "Foreign investors (FII)", Client: "Individuals & others (Client)", Pro: "Brokers' own trading (Pro)", DII: "Domestic institutions (DII)" };
  const tbl = `<div class="tbl-wrap"><table class="tbl"><thead><tr><th>Who</th>${show.map((k) => `<th>${rows.find((r) => r.metric === k)?.label || k}</th>`).join("")}</tr></thead><tbody>
    ${who.map((w) => `<tr><td><span class="sym">${w}</span><span class="nm">${nice[w]}</span></td>${show.map((k) => { const r = rows.find((x) => x.who === w && x.metric === k); if (!r) return "<td>—</td>";
      const v = k.includes("share") ? pct(r.now, 0) : big(r.now); return `<td class="num">${v}<br><span class="muted small">${ord(r.pct1y)} pct (1y) · 5d ${k.includes("share") ? vp(r.chg5) + " pts" : big(r.chg5)}</span><span class="muted small a-only"><br>${ord(r.pct)} pct since ${P.since}</span></td>`; }).join("")}</tr>`).join("")}
    </tbody></table></div>`;
  app.innerHTML = `<div class="page-h"><div><h1>Who holds what</h1><div class="sub">NSE's participant-wise open interest: positions of foreign investors, domestic institutions, brokers' own desks and everyone else, daily since ${P.since}.</div></div>${horizonSeg()}</div>
    <div class="grid g2">${card({ title: "In plain words", body: `<ul class="story">${P.simple.map((s) => `<li>${esc(s)}</li>`).join("")}</ul>` })}
    ${card({ title: "Index futures: share of positions that are long", body: `<div class="chart" id="ls"></div><div class="legend"><span style="--c:${css("--s1")}">FII</span><span style="--c:${css("--s2")}">Client</span><span style="--c:${css("--s3")}">Pro</span></div>`,
      analyst: "Long share = long contracts / (long + short). Every future has a buyer and a seller, so one group's long is another's short. FIIs hedge their share holdings with index-futures shorts, which keeps their long share structurally low; the extremes, not the level, are what history makes interesting." })}</div>
    <div style="margin-top:16px">${card({ title: "Current books against their history", hint: "contracts; percentile vs the past year", body: tbl,
      analyst: "Percentiles compare with the past year because these books changed regime: FIIs' median long share in index futures was 44-63% in 2019-2024 and 12-17% in 2025-26. Against all history a normal day now looks extreme. Every contract has a buyer and a seller: the four groups' longs equal their shorts each day (checked)." })}</div>
    <div class="grid g2" style="margin-top:16px">
      ${card({ title: "Index futures: net contracts", body: `<div class="chart" id="net"></div><div class="legend"><span style="--c:${css("--s1")}">FII</span><span style="--c:${css("--s2")}">Client</span><span style="--c:${css("--s3")}">Pro</span><span style="--c:${css("--s4")}">DII</span></div>` })}
      ${card({ title: "Index options stance", hint: "net calls − net puts", simple: "Above zero: the group's options gain if the market rises (long calls / short puts). Below zero: they gain on a fall.",
        body: `<div class="chart" id="opt"></div><div class="legend"><span style="--c:${css("--s1")}">FII</span><span style="--c:${css("--s2")}">Client</span><span style="--c:${css("--s3")}">Pro</span></div>` })}
    </div>`;
  const t = theme();
  const s = slice(P.series, Object.keys(P.series).filter((k) => k !== "d"));
  chart("#ls", { xAxis: axisX(s.d, t), yAxis: axisY(t, fmtPct(0)), tooltip: { trigger: "axis", valueFormatter: (v) => pct(v, 1), backgroundColor: t.surface, borderColor: t.line, textStyle: { color: t.text } },
    series: [line("FII", s["idx_fut_long_share:FII"], t.s1), line("Client", s["idx_fut_long_share:Client"], t.s2), line("Pro", s["idx_fut_long_share:Pro"], t.s3)] });
  chart("#net", { xAxis: axisX(s.d, t), yAxis: axisY(t, (v) => big(v)), tooltip: { trigger: "axis", valueFormatter: big, backgroundColor: t.surface, borderColor: t.line, textStyle: { color: t.text } },
    series: [line("FII", s["idx_fut_net:FII"], t.s1), line("Client", s["idx_fut_net:Client"], t.s2), line("Pro", s["idx_fut_net:Pro"], t.s3), line("DII", s["idx_fut_net:DII"], t.s4)] });
  chart("#opt", { xAxis: axisX(s.d, t), yAxis: axisY(t, (v) => big(v)), tooltip: { trigger: "axis", valueFormatter: big, backgroundColor: t.surface, borderColor: t.line, textStyle: { color: t.text } },
    series: [line("FII", s["idx_opt_stance:FII"], t.s1), line("Client", s["idx_opt_stance:Client"], t.s2), line("Pro", s["idx_opt_stance:Pro"], t.s3)] });
  bindHorizon(route);
}

// ---------------------------------------------------------------- flows
async function pageFlows(app, ov) {
  $("#crumbs").textContent = "FII / DII money";
  const F = ov.flows;
  const s = F.series;
  const cum = (a) => { let c = 0; return a.map((v) => (c += v || 0)); };
  app.innerHTML = `<div class="page-h"><div><h1>FII / DII money</h1><div class="sub">Net buying of shares in the cash market, ₹ crore a day.</div></div></div>
    <div class="grid g2">${kpi({ label: "FII · last session", value: (F.FII?.last >= 0 ? "+" : "−") + "₹" + num(Math.abs(F.FII?.last)), unit: "cr", foot: `20 sessions: ${F.FII?.sum20 >= 0 ? "+" : "−"}₹${num(Math.abs(F.FII?.sum20))} cr` })}
    ${kpi({ label: "DII · last session", value: (F.DII?.last >= 0 ? "+" : "−") + "₹" + num(Math.abs(F.DII?.last)), unit: "cr", foot: `20 sessions: ${F.DII?.sum20 >= 0 ? "+" : "−"}₹${num(Math.abs(F.DII?.sum20))} cr` })}</div>
    <div style="margin-top:16px">${card({ title: "In plain words", body: `<ul class="story">${F.simple.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>`, analyst: F.note })}</div>
    <div class="grid g2" style="margin-top:16px">
      ${card({ title: "Daily net buying", body: `<div class="chart" id="fd"></div><div class="legend"><span style="--c:${css("--s1")}">FII</span><span style="--c:${css("--s2")}">DII</span></div>` })}
      ${card({ title: "Running total since " + F.since, simple: "When the two lines move opposite ways, domestic money is absorbing what foreign money sells (or the reverse).", body: `<div class="chart" id="fc"></div><div class="legend"><span style="--c:${css("--s1")}">FII</span><span style="--c:${css("--s2")}">DII</span></div>` })}
    </div>
    <div class="callout" style="margin-top:16px">Positioning in derivatives by the same groups is on <a href="#/positioning"><b>Who holds what</b></a>, with history back to 2019.</div>`;
  const t = theme();
  const bar = (name, data, color) => ({ name, type: "bar", data, itemStyle: { color, borderRadius: [3, 3, 0, 0] }, barGap: "10%" });
  chart("#fd", { xAxis: axisX(s.d, t, { boundaryGap: true }), yAxis: axisY(t, (v) => num(v)), tooltip: { trigger: "axis", valueFormatter: (v) => "₹" + num(v) + " cr", backgroundColor: t.surface, borderColor: t.line, textStyle: { color: t.text } },
    series: [bar("FII", s.FII, t.s1), bar("DII", s.DII, t.s2)] });
  chart("#fc", { xAxis: axisX(s.d, t), yAxis: axisY(t, (v) => num(v)), tooltip: { trigger: "axis", valueFormatter: (v) => "₹" + num(v) + " cr", backgroundColor: t.surface, borderColor: t.line, textStyle: { color: t.text } },
    series: [line("FII", cum(s.FII), t.s1), line("DII", cum(s.DII), t.s2)] });
}

// ---------------------------------------------------------------- the whole F&O market (engine/breadth.py)
async function pageBreadth(app, ov) {
  $("#crumbs").textContent = "Whole F&O market";
  let B;
  try { B = S.breadth || (S.breadth = await getJSON("data/breadth.json")); }
  catch (e) { app.innerHTML = `<div class="loading">The market-wide data is not built yet (${esc(e.message)}).</div>`; return; }
  const t = theme(), T = B.today, cls = ["Long build-up", "Short build-up", "Short covering", "Long unwinding"];
  const vol = { d: B.vol.date, dear: B.vol.dear, cheap: B.vol.cheap, median_rank: B.vol.median_rank, median_iv: B.vol.median_iv };
  const pos = { d: B.positions.date, ...Object.fromEntries(cls.map((c) => [c, B.positions[c]])) };
  const vNow = vol.dear.length - 1, pNow = pos.d.length - 1;
  const shares = cls.map((c) => [c, pos[c][pNow]]);
  const top = shares.slice().sort((a, b) => b[1] - a[1])[0];
  const have = new Set((ov.universe || []).map((u) => u.symbol));
  const name = (sym) => (have.has(sym) ? `<a href="#/sym/${slug(sym)}"><b>${esc(sym)}</b></a>` : `<span>${esc(sym)}</span>`);
  const list = (xs) => xs.map((x) => `${name(x.symbol)} <span class="num">${pct(x.iv, 0)}</span> <span class="muted small">${ord(x.rank)}</span>`).join(" · ");
  const draw = () => {
    app.innerHTML = `<div class="page-h"><div><h1>The whole F&O market</h1><div class="sub">Every stock in NSE's F&O list (${num(T.n_iv)} with a vol reading today), each judged against its own past year · as of ${B.asof}</div></div>${horizonSeg()}</div>
    <div class="grid g4">
      ${kpi({ label: "Options unusually dear", value: pct(vol.dear[vNow], 0), foot: `of stocks at their own 80th percentile of IV or above` })}
      ${kpi({ label: "Options unusually cheap", value: pct(vol.cheap[vNow], 0), foot: `at their own 20th percentile or below` })}
      ${kpi({ label: "Median stock's IV rank", value: ord(vol.median_rank[vNow]), foot: `median IV ${pct(vol.median_iv[vNow], 1)}` })}
      ${kpi({ label: "Most common futures read", value: esc(top[0]), foot: `${pct(top[1], 0)} of ${num(B.positions.n[pNow])} stocks` })}
    </div>
    <div class="grid g2" style="margin-top:16px">
      ${card({ title: "How many stocks have dear or cheap options", hint: "share of F&O stocks, each against its own year", cls: "span2",
        simple: "Each day, the share of stocks whose at-the-money option vol is in the top fifth of its own past year (dear) or the bottom fifth (cheap). When dear options spread across the market, the fear is broad, not about one name.",
        analyst: "At-the-money straddle implied vol of each stock's nearest expiry at least 7 days out, from the strike where call and put (both traded that day) are closest in price; ranked against the stock's own previous 252 readings (126 at least). It equals the engine's own straddle vol on every shared day and sits within a median 0.05 vol points of its smile-based ATM vol. Days with fewer than 50 readable stocks are left out.",
        body: `<div class="chart" id="bvol"></div><div class="legend"><span style="--c:${t.dneg}">Dear (80th pct+)</span><span style="--c:${t.dpos}">Cheap (20th pct−)</span><span style="--c:${t.s7}">Median rank</span></div>` })}
      ${card({ title: "What futures positions did, market-wide", hint: "share of F&O stocks in each class each day", cls: "span2",
        simple: `Today ${shares.map(([c, v]) => `${c.toLowerCase()} ${pct(v, 0)}`).join(", ")}. A market where most stocks see short build-up is being sold with fresh positions; short covering means shorts are leaving.`,
        analyst: "Each stock's futures day classed by price change × open-interest change on the same contracts (the instrument pages' rules: the expiring contract counted on its last day; a book under 500 lots is a thin market; a split or bonus day gets no class). Verified to match those pages day by day on all twenty stocks (34,662 stock-days, no difference).",
        body: `<div class="chart" id="bpos"></div><div class="legend">${cls.map((c, i) => `<span style="--c:${[t.s1, t.s2, t.s3, t.s4][i]}">${c}</span>`).join("")}</div>` })}
      ${card({ title: "Dearest options today", hint: "against each stock's own year", body: `<div class="small" style="line-height:2">${list(T.dearest)}</div>` })}
      ${card({ title: "Cheapest options today", hint: "against each stock's own year", body: `<div class="small" style="line-height:2">${list(T.cheapest)}</div>` })}
      ${card({ title: "Sector vol board", hint: "21-day realised vol of NSE's sector indices", cls: "span2",
        simple: "How much each sector has actually been moving, against its own past year; 'waking' compares the last week with the last quarter (above 1: the sector has started to move more).",
        body: `<div class="tbl-wrap"><table class="tbl"><thead><tr><th>Sector</th><th>Realised vol (21d)</th><th>Rank (1y)</th><th>Waking (5d / 63d)</th><th>Last year</th></tr></thead><tbody>
          ${(B.sectors || []).map((x, i) => `<tr><td>${esc(x.sector)} <span class="muted small">${esc(x.index)}</span></td><td class="num">${pct(x.rv21, 1)}</td><td class="num">${ord(x.rank)}</td>
            <td class="num">${fin(x.wake) ? x.wake.toFixed(2) + "×" : "—"}</td><td><div class="chart" id="sec${i}" style="height:28px;width:160px"></div></td></tr>`).join("")}</tbody></table></div>` })}
      ${Object.values(B.dispersion || {}).map((x) => dispCard(x)).join("")}
      ${card({ title: "Today's futures reads by class", cls: "span2", body: cls.map((c) => `<div style="margin:6px 0"><b>${c}</b> <span class="muted small">(${T.buildups[c].length})</span><div class="small muted" style="line-height:1.8">${T.buildups[c].map((x) => name(x)).join(" · ") || "—"}</div></div>`).join("") })}
    </div>`;
    bindHorizon(draw);
    const v = slice(vol, ["dear", "cheap", "median_rank"]), pp = slice(pos, cls);
    chart("#bvol", { tooltip: { trigger: "axis", valueFormatter: (x) => pct(x, 0), backgroundColor: t.surface, borderColor: t.line, textStyle: { color: t.text } }, xAxis: axisX(v.d, t), yAxis: axisY(t, fmtPct(0), { min: 0, max: 1, scale: false }),
      series: [line("Dear", v.dear, t.dneg, { areaStyle: { color: t.dneg, opacity: .12 } }), line("Cheap", v.cheap, t.dpos, { areaStyle: { color: t.dpos, opacity: .12 } }), line("Median rank", v.median_rank, t.s7, { lineStyle: { width: 1.5, type: "dashed", color: t.s7 } })] });
    chart("#bpos", { tooltip: { trigger: "axis", valueFormatter: (x) => pct(x, 0), backgroundColor: t.surface, borderColor: t.line, textStyle: { color: t.text } }, xAxis: axisX(pp.d, t), yAxis: axisY(t, fmtPct(0), { min: 0, max: 1, scale: false }),
      series: cls.map((c, i) => ({ name: c, type: "line", stack: "all", areaStyle: { opacity: .55 }, lineStyle: { width: 0 }, showSymbol: false, data: ma(pp[c], 5), itemStyle: { color: [t.s1, t.s2, t.s3, t.s4][i] }, color: [t.s1, t.s2, t.s3, t.s4][i] })) });
    Object.values(B.dispersion || {}).forEach((x) => dispChart(x));
    (B.sectors || []).forEach((x, i) => chart(`#sec${i}`, { grid: { left: 0, right: 0, top: 2, bottom: 2 }, xAxis: { type: "category", show: false, data: x.rv21_1y.map((_, j) => j) }, yAxis: { type: "value", show: false, scale: true },
      tooltip: { show: false }, series: [{ type: "line", data: x.rv21_1y, showSymbol: false, lineStyle: { width: 1.2, color: t.s1 }, silent: true }] }));
  };
  draw();
}

// ---- data health: what this build was made from ----
async function pageHealth(app, ov) {
  $("#crumbs").textContent = "Data health";
  const H = ov.health || { tables: [], instruments: [] };
  const what = { fo_bhav: "NSE index futures and options", fo_stock_opts: "NSE stock futures and options (near months)", fo_stock_far: "NSE stock options, far month",
    cm_bhav: "NSE cash market (OHLC, volume, delivery)", global_daily: "International benchmarks (Yahoo)", bse_fo_bhav: "BSE index futures and options",
    nse_index_close: "NSE index closes", participant_oi: "Participant-wise open interest", participant_vol: "Participant-wise volume", fii_dii: "FII / DII cash flows",
    corp_events: "Corporate events (results)", nse_holidays: "Exchange holidays", gift_nifty: "GIFT Nifty" };
  const dot = (b) => (b === null || b === undefined ? `<span class="chip extreme"><span class="dot"></span>missing</span>` : b === 0 ? `<span class="chip"><span class="dot live"></span>current</span>` : b <= 2 ? `<span class="chip elevated"><span class="dot"></span>${b} session${b > 1 ? "s" : ""} behind</span>` : `<span class="chip extreme"><span class="dot"></span>${b} sessions behind</span>`);
  const L = window.MLLive ? MLLive.state : {};
  app.innerHTML = `<div class="page-h"><div><h1>Data health</h1><div class="sub">What this build was made from · built ${esc(ov.built || "")} · analysis as of ${ov.asof}</div></div></div>
    <div class="grid g2">
      ${card({ title: "Warehouse tables", hint: "the newest day each one holds", cls: "span2", simple: "Each table the app reads, and how far its newest day is behind the build's as-of session. 'Missing' means the table has not been filled yet (a new table waits for its first backfill).",
        body: `<div class="tbl-wrap"><table class="tbl"><thead><tr><th>Table</th><th>What</th><th>Files</th><th>Newest day</th><th>State</th></tr></thead><tbody>
          ${H.tables.map((t) => `<tr><td><code>${t.table}</code></td><td style="text-align:left">${what[t.table] || ""}</td><td class="num">${num(t.files)}</td><td class="num">${t.last || "—"}</td><td>${dot(t.behind)}</td></tr>`).join("")}</tbody></table></div>` })}
      ${card({ title: "Live feed", body: `<div class="small" style="line-height:1.9">State: <b>${esc(L.mode || "—")}</b>${L.feedAge !== null && L.feedAge !== undefined ? ` · NIFTY's quote ${Math.round(L.feedAge)} s old` : ""}<br>MCX: ${L.mcx && L.mcx.live ? "live" : "no fresh MCX price"}${L.note ? `<br>${esc(L.note)}` : ""}</div>` })}
      ${card({ title: "Instruments", hint: "readings left blank are listed", body: `<div class="tbl-wrap"><table class="tbl"><thead><tr><th>Instrument</th><th>As of</th><th>Blank today</th></tr></thead><tbody>
          ${H.instruments.map((x) => `<tr><td><a href="#/sym/${slug(x.symbol)}"><b>${esc(x.symbol)}</b></a></td><td class="num">${x.asof}</td><td class="small muted" style="text-align:left">${Object.keys(x.stale).join(", ") || "—"}</td></tr>`).join("")}</tbody></table></div>` })}
    </div>`;
}

// ---- compare two instruments side by side ----
async function pageCompare(app, ov, a, b) {
  $("#crumbs").textContent = "Compare";
  const U = ov.universe || [];
  a = a || "NIFTY"; b = b || "BANKNIFTY";
  const opts = (sel) => U.map((u) => `<option value="${u.slug}" ${u.slug === sel ? "selected" : ""}>${esc(u.symbol)}</option>`).join("");
  let A, B;
  try { [A, B] = await Promise.all([symData(a), symData(b)]); } catch (e) { app.innerHTML = `<div class="loading">Could not load ${esc(a)} or ${esc(b)}.</div>`; return; }
  const t = theme(), ma_ = A.headline.metrics, mb = B.headline.metrics;
  const rows = [["Price", (m) => num(m.spot, 1)], ["Day", (m) => `${vp(m.chg, 2)}%`], ["30-day IV", (m) => pct(m.iv30)], ["IV rank (1y)", (m) => ord(m.iv_p1y)],
    ["Realised vol (21d)", (m) => pct(m.rv21)], ["Premium (IV − RV)", (m) => (fin(m.vrp) ? vp(m.vrp) + " pts" : "—")], ["Skew (25d RR)", (m) => (fin(m.rr25) ? vp(m.rr25) + " pts" : "—")],
    ["Priced move to front expiry", (m) => (fin(m.move) ? "±" + pct(m.move, 2) : "—")], ["Put/call ratio rank", (m) => ord(m.pcr_p)], ["Futures carry", (m) => pct(m.carry)]];
  const extra = (d) => ({ own: d.link && fin(d.link.own) ? pct(d.link.own, 0) : "—", lab: d.lab && d.lab.verdict ? d.lab.verdict.neighbours || "—" : "—",
    gamma: d.gamma && fin(d.gamma.net_total) ? (d.gamma.net_total >= 0 ? "long " : "short ") + num(Math.abs(d.gamma.net_total)) + " cr" : "—",
    atr: d.movement && fin(d.movement.atr14) ? pct(d.movement.atr14, 2) : "—" });
  const ea = extra(A), eb = extra(B);
  app.innerHTML = `<div class="page-h"><div><h1>Compare</h1><div class="sub">Two instruments side by side, each against its own history</div></div>
      <div><select id="cmpA" class="seg" style="padding:6px">${opts(a)}</select> <span class="muted">vs</span> <select id="cmpB" class="seg" style="padding:6px">${opts(b)}</select></div></div>
    <div class="grid g2">
      ${card({ title: "Readings today", cls: "span2", body: `<div class="tbl-wrap"><table class="tbl"><thead><tr><th></th><th>${esc(A.meta.symbol)}</th><th>${esc(B.meta.symbol)}</th></tr></thead><tbody>
        ${rows.map(([l, f]) => `<tr><td style="text-align:left">${l}</td><td class="num">${f(ma_)}</td><td class="num">${f(mb)}</td></tr>`).join("")}
        <tr><td style="text-align:left">Average true range (14d)</td><td class="num">${ea.atr}</td><td class="num">${eb.atr}</td></tr>
        <tr><td style="text-align:left">Own share of variance</td><td class="num">${ea.own}</td><td class="num">${eb.own}</td></tr>
        <tr><td style="text-align:left">Hedgers' net gamma</td><td class="num">${ea.gamma}</td><td class="num">${eb.gamma}</td></tr>
        <tr><td style="text-align:left">Days like today vs an ordinary day</td><td class="num">${ea.lab}</td><td class="num">${eb.lab}</td></tr></tbody></table></div>` })}
      ${card({ title: "30-day IV", hint: "each against its own year", body: `<div class="chart" id="cmpIv"></div>` })}
      ${card({ title: "Realised vol (21d)", body: `<div class="chart" id="cmpRv"></div>` })}
      ${card({ title: "Premium: IV − realised", body: `<div class="chart" id="cmpVrp"></div>` })}
      ${card({ title: "Price, rebased to 100", body: `<div class="chart" id="cmpPx"></div>` })}
    </div>`;
  const sa = slice(A.series, ["iv30", "rv21", "vrp", "close"]), sb = slice(B.series, ["iv30", "rv21", "vrp", "close"]);
  const d = sa.d.length >= sb.d.length ? sa.d : sb.d;
  const align = (s, c) => { const m = new Map(s.d.map((x, i) => [x, s[c][i]])); return d.map((x) => (m.has(x) ? m.get(x) : null)); };
  const tip = (f) => ({ trigger: "axis", valueFormatter: f, backgroundColor: t.surface, borderColor: t.line, textStyle: { color: t.text } });
  const two = (id, c, f, fy) => chart(id, { tooltip: tip(f), xAxis: axisX(d, t), yAxis: axisY(t, fy), legend: { show: true, top: 0, textStyle: { color: t.text2 } },
    series: [line(A.meta.symbol, align(sa, c), t.s1), line(B.meta.symbol, align(sb, c), t.s2)] });
  two("#cmpIv", "iv30", (v) => pct(v, 1), fmtPct(0));
  two("#cmpRv", "rv21", (v) => pct(v, 1), fmtPct(0));
  two("#cmpVrp", "vrp", (v) => vp(v) + " pts", (v) => (v * 100).toFixed(0));
  const reb = (s) => { const x = align(s, "close"), f0 = x.find(fin); return x.map((v) => (fin(v) && f0 ? (100 * v) / f0 : null)); };
  chart("#cmpPx", { tooltip: tip((v) => (fin(v) ? v.toFixed(1) : "—")), xAxis: axisX(d, t), yAxis: axisY(t, (v) => v.toFixed(0)), legend: { show: true, top: 0, textStyle: { color: t.text2 } },
    series: [line(A.meta.symbol, reb(sa), t.s1), line(B.meta.symbol, reb(sb), t.s2)] });
  const go = () => { location.hash = `#/compare/${$("#cmpA").value}/${$("#cmpB").value}`; };
  $("#cmpA").onchange = go; $("#cmpB").onchange = go;
}

// ---- alerts: the owner's rules, kept in the relay; pushed by the Worker, shown here too (alertrules.js) ----
async function pageAlerts(app, ov) {
  $("#crumbs").textContent = "Alerts";
  const key = (() => { try { return localStorage.getItem("qd.livekey") || ""; } catch (e) { return ""; } })();
  let state = { rules: [], log: [] }, err = "";
  if (key) {
    try {
      const r = await fetch("/live/alerts", { headers: { Authorization: "Bearer " + key }, cache: "no-store" });
      if (r.ok) state = await r.json(); else err = r.status === 401 ? "the live key was not accepted" : `the relay answered ${r.status}`;
    } catch (e) { err = "the relay did not answer (alerts live on the desk's Worker, at the same address as this app)"; }
  }
  const rules = AlertRules.mergeRules(state.rules);
  const perm = typeof Notification !== "undefined" ? Notification.permission : "unsupported";
  const field = (r, k, lab, step, scale = 1, unit = "") => (k in r ? `<label class="small muted" style="margin-left:12px">${lab} <input type="number" step="${step}" data-id="${r.id}" data-k="${k}" data-scale="${scale}" value="${+(r[k] * scale).toFixed(2)}" style="width:72px;padding:4px 6px;border-radius:6px;border:1px solid var(--line);background:var(--surface);color:var(--text)"> ${unit}</label>` : "");
  app.innerHTML = `<div class="page-h"><div><h1>Alerts</h1><div class="sub">Pushed to your phone by the desk's Worker every ten minutes in market hours (ntfy, the watchdog's channel), and shown here while the app is open. Each fires at most once a day.</div></div></div>
    ${!key ? `<div class="callout">Alerts need your live key on this device. <a href="#" onclick="MLLive.askKey();return false"><b>Add it</b></a>, then come back.</div>` : err ? `<div class="callout">Could not read the alert settings: ${esc(err)}.</div>` : ""}
    <div class="grid g2" style="margin-top:16px">
      ${card({ title: "Rules", cls: "span2", simple: "Each rule reads the same live numbers as the app's panels. Nothing here predicts a move: an alert says a reading crossed the line you set.",
        analyst: "NSE rules run on trading days 09:20–15:30 IST, MCX 09:05–23:30, the ban list once the site is rebuilt in the evening. Settings live in the desk's relay (your live key); the Worker reads them at each firing.",
        body: `<div>${rules.map((r) => `<div style="padding:10px 0;border-bottom:1px solid var(--line-2)"><label><input type="checkbox" data-id="${r.id}" data-k="on" ${r.on ? "checked" : ""}> <b>${esc(r.label)}</b></label>
          ${field(r, "hi", "above percentile", 1, 100, "")}${field(r, "lo", "below percentile", 1, 100, "")}${field(r, "mult", "times the priced day", 0.1)}${field(r, "pts", "vol points", 0.5, 100)}${field(r, "near", "of the limit", 1, 100, "%")}
          ${"scope" in r ? `<label class="small muted" style="margin-left:12px">for <select data-id="${r.id}" data-k="scope" style="padding:4px;border-radius:6px;background:var(--surface);color:var(--text);border:1px solid var(--line)"><option value="indices" ${r.scope === "indices" ? "selected" : ""}>indices</option><option value="all" ${r.scope === "all" ? "selected" : ""}>indices and stocks</option></select></label>` : ""}</div>`).join("")}
          <div style="margin-top:12px"><button class="btn" id="alSave" ${key ? "" : "disabled"}>Save</button> <span class="muted small" id="alMsg"></span></div></div>` })}
      ${card({ title: "On this device", simple: perm === "granted" ? "Browser notifications are on: while this app is open, an alert also shows here." : perm === "denied" ? "This browser has blocked notifications for this page; the phone push still works." : perm === "unsupported" ? "This browser has no notifications; the phone push still works." : "Turn on browser notifications to see alerts here while the app is open.",
        body: perm === "default" ? `<button class="btn" id="alPerm">Turn on notifications</button>` : "" })}
      ${card({ title: "Sent recently", hint: "by the Worker", body: (state.log || []).length ? `<div class="tbl-wrap"><table class="tbl"><tbody>${state.log.slice(0, 30).map((x) => `<tr><td class="num small">${new Date(x.at).toLocaleString("en-IN", { timeZone: "Asia/Kolkata", day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" })}</td><td style="text-align:left"><b>${esc(x.title)}</b><div class="small muted">${esc(x.body)}</div></td></tr>`).join("")}</tbody></table></div>` : `<div class="muted small">Nothing sent yet.</div>` })}
    </div>`;
  const save = $("#alSave");
  if (save) save.onclick = async () => {
    const out = rules.map((r) => ({ id: r.id }));
    $$("[data-id]").forEach((el) => {
      const r = out.find((x) => x.id === el.dataset.id); if (!r) return;
      if (el.dataset.k === "on") r.on = el.checked;
      else if (el.dataset.k === "scope") r.scope = el.value;
      else r[el.dataset.k] = Number(el.value) / Number(el.dataset.scale || 1);
    });
    $("#alMsg").textContent = "saving…";
    try {
      const r = await fetch("/live/alerts", { method: "PUT", headers: { Authorization: "Bearer " + key, "content-type": "application/json" }, body: JSON.stringify({ rules: out }) });
      $("#alMsg").textContent = r.ok ? "saved: the Worker uses them from its next firing" : `not saved (${r.status})`;
      if (r.ok && window.MLLive) MLLive.state.alertRules = (await r.json()).rules;
    } catch (e) { $("#alMsg").textContent = "not saved: the relay did not answer"; }
  };
  const pb = $("#alPerm");
  if (pb) pb.onclick = async () => { await Notification.requestPermission(); route({ soft: true }); };
}

// ---- MCX commodities: public benchmarks (engine/commodities.py) + the live panel (live-ui.js) ----
async function pageCommodities(app, ov) {
  $("#crumbs").textContent = "Commodities (MCX)";
  let C = {};
  try { C = S.commodities || (S.commodities = await getJSON("data/commodities.json")); } catch (e) { C = {}; }
  const t = theme(), cs = C.contracts || {};
  const names = Object.keys(cs);
  const seen = new Set(), bench = names.filter((n) => { const k = cs[n].ticker; if (seen.has(k)) return false; seen.add(k); return true; });
  const label = { "CL=F": "WTI crude", "NG=F": "Henry Hub gas", "GC=F": "COMEX gold", "SI=F": "COMEX silver", "HG=F": "COMEX copper" };
  app.innerHTML = `<div class="page-h"><div><h1>Commodities (MCX)</h1><div class="sub">Live MCX futures and options from your feeds (9:00–23:30 IST, private), and the international benchmark each contract tracks${C.asof ? ` · benchmarks as of ${C.asof}` : ""}</div></div></div>
    ${liveSlot({ kind: "commodities", ov, C })}
    ${names.length ? `<div class="grid g2" style="margin-top:16px">
      ${card({ title: "The benchmarks MCX tracks", hint: "realised vol and import parity", cls: "span2",
        simple: "MCX contracts follow international prices converted into rupees. Import parity is the benchmark in the MCX contract's own unit at today's dollar rate, before duties and local premiums; the live panel above sets the MCX future against it.",
        analyst: `Benchmarks: front-month futures on NYMEX/COMEX via Yahoo Finance (a public source, not an exchange file): every reading carries its date. Units: gold Rs per 10 g (31.1035 g a troy ounce), silver Rs per kg, copper Rs per kg (2.2046 lb), crude Rs per barrel, gas Rs per mmBtu. Realised vol: 21 sessions, ranked against its own past year.`,
        body: `<div class="tbl-wrap"><table class="tbl"><thead><tr><th>MCX contract</th><th>Benchmark</th><th>Last</th><th>Day</th><th>Realised vol 21d</th><th>Rank 1y</th><th>Import parity</th></tr></thead><tbody>
          ${names.map((n) => { const x = cs[n]; return `<tr><td><b>${n}</b></td><td>${label[x.ticker] || x.ticker} <span class="muted small">${x.benchmark_unit} · ${x.date}</span></td><td class="num">${num(x.close, 2)}</td>
            <td class="num"><span class="chg ${x.chg >= 0 ? "pos" : "neg"}">${vp(x.chg, 2)}%</span></td><td class="num">${pct(x.rv21, 1)}</td><td class="num">${ord(x.rv21_rank)}</td>
            <td class="num">${fin(x.parity) ? num(x.parity, x.parity > 1000 ? 0 : 1) : "—"} <span class="muted small">${x.mcx_unit}</span></td></tr>`; }).join("")}</tbody></table></div>` })}
      ${bench.map((n, i) => card({ title: `${label[cs[n].ticker] || cs[n].ticker}: how much it moves`, hint: `realised vol, 21 days · since ${cs[n].since}`, body: `<div class="chart" id="bm${i}" style="height:200px"></div>` })).join("")}
      ${(C.macro || []).length ? card({ title: "Macro board", hint: "the prices commodities and Indian markets take their cue from", cls: "span2",
        body: `<div class="tbl-wrap"><table class="tbl"><thead><tr><th>Market</th><th>Last</th><th>Day</th><th>Realised vol 21d</th><th>Rank 1y</th></tr></thead><tbody>
          ${C.macro.map((m) => `<tr><td>${esc(m.name)} <span class="muted small">${m.date}</span></td><td class="num">${num(m.close, 2)}${m.is_yield ? "%" : ""}</td>
            <td class="num">${m.is_yield ? (m.chg >= 0 ? "+" : "") + (m.chg * 100).toFixed(0) + " bp" : `<span class="chg ${m.chg >= 0 ? "pos" : "neg"}">${vp(m.chg, 2)}%</span>`}</td>
            <td class="num">${m.is_yield ? (fin(m.rv21) ? (m.rv21 * 1e4).toFixed(0) + " bp/yr" : "—") : pct(m.rv21, 1)}</td><td class="num">${ord(m.rv21_rank)}</td></tr>`).join("")}</tbody></table></div>` }) : ""}
    </div>` : `<div class="callout" style="margin-top:16px">The international benchmarks are not in the warehouse yet: they arrive with its next update (global_daily).</div>`}`;
  bench.forEach((n, i) => {
    const x = cs[n].rv21_1y;
    chart(`#bm${i}`, { grid: { left: 52, right: 18, top: 16, bottom: 26 }, tooltip: { trigger: "axis", valueFormatter: (v) => pct(v, 1), backgroundColor: t.surface, borderColor: t.line, textStyle: { color: t.text } },
      xAxis: axisX(x.date, t), yAxis: axisY(t, fmtPct(0)), series: [line("Realised vol", x.v, t.s1, { areaStyle: { color: t.s1, opacity: .08 } })] });
  });
  if (window.MLLive) MLLive.mcxCharts();
}

// ---- implied against realised correlation (engine/dispersion.py) ----
function dispCard(x) {
  const g = x.gap_median, rich = fin(g) && g > 0.02, cheap = fin(g) && g < -0.02;
  return card({ title: `Do ${x.index}'s members move together?`, hint: "implied vs realised correlation", cls: "span2",
    simple: `Options price ${x.index}'s members to move together with an average correlation of ${fin(x.implied) ? x.implied.toFixed(2) : "—"}${fin(x.implied_rank) ? ` (${ord(x.implied_rank)} percentile of its year)` : ""}; over the last month they did ${fin(x.realised) ? x.realised.toFixed(2) : "—"}. Since ${x.since}, implied correlation ran ${fin(g) ? (g >= 0 ? "+" : "") + g.toFixed(3) : "—"} against what the next month delivered (above it ${pct(x.gap_share_positive, 0)} of days): ${rich ? "the index's options have carried a correlation premium" : cheap ? "the index's options have under-priced how together the members moved" : "close to fair"}.`,
    analyst: `Weights estimated from returns: a price index's daily return is the weighted sum of its members', so a non-negative least-squares fit over 126 sessions recovers them (NSE's weight sources do not answer from the build machine). This month's fit: R² ${x.fit_r2.toFixed(4)}, weights summing to ${x.weight_sum.toFixed(3)}; a month fitting under 0.95 is left out. Members from ${x.members_source}. Implied: each one's at-the-money straddle vol (nearest expiry a week or more out, the same method for the index and every member); realised: 21-session close-to-close.`,
    body: `<div class="chart" id="disp_${x.index}"></div><div class="legend"><span style="--c:${theme().s1}">Implied</span><span style="--c:${theme().s2}">Realised (last month)</span><span style="--c:${theme().s3}">Realised (the month after)</span></div>
      <div class="small muted" style="margin-top:8px;line-height:1.8">Estimated weights: ${x.weights.map((w) => `<b>${esc(w.symbol)}</b> ${pct(w.w, 1)}`).join(" · ")}</div>` });
}
function dispChart(x) {
  const el = $(`#disp_${x.index}`);
  if (!el) return;
  const t = theme(), s = slice({ d: x.series.date, implied: x.series.implied, realised: x.series.realised, realised_next: x.series.realised_next }, ["implied", "realised", "realised_next"]);
  chart(`#disp_${x.index}`, { tooltip: { trigger: "axis", valueFormatter: (v) => (fin(v) ? v.toFixed(2) : "—"), backgroundColor: t.surface, borderColor: t.line, textStyle: { color: t.text } },
    xAxis: axisX(s.d, t), yAxis: axisY(t, (v) => v.toFixed(1)),
    series: [line("Implied", s.implied, t.s1, { connectNulls: false }), line("Realised", s.realised, t.s2, { connectNulls: false, lineStyle: { width: 1.2, color: t.s2 } }),
      line("Realised, next month", s.realised_next, t.s3, { connectNulls: false, lineStyle: { width: 1.2, type: "dashed", color: t.s3 } })] });
}

// ---------------------------------------------------------------- calendar & method
async function pageCalendar(app, ov) {
  $("#crumbs").textContent = "Calendar";
  app.innerHTML = `<div class="page-h"><div><h1>Calendar</h1><div class="sub">Expiries, results of covered stocks, and market holidays, from the exchanges' own calendars.</div></div></div>
    ${card({ title: "Upcoming", body: calendarRows(ov.calendar.items) })}`;
}
async function pageMethod(app) {
  $("#crumbs").textContent = "How to read this";
  const g = [
    ["Implied volatility (IV)", "What options charge, written as an expected yearly move. 16% a year is about 1% a day (divide by 16, the square root of 256 trading days). It is a price, not a forecast you can bank: it includes a premium for risk."],
    ["Realised volatility (RV)", "How much the price actually moved, measured the same way as IV so the two can be compared. RV21 uses the last 21 sessions (about a month)."],
    ["IV − RV (volatility premium)", "Options usually cost a little more than the movement that follows: sellers want paying for carrying risk. Below zero is unusual and tends to come with stress."],
    ["Priced move (straddle)", "The cost of buying both the at-the-money call and put, as a % of price. It is the options market's average expected move to expiry. A fairly priced straddle is beaten about 43% of the time; the scorecard shows how this name actually did."],
    ["Term structure", "IV of each expiry. Normally later expiries cost a bit more. When near ones cost more (inversion), the market expects something soon: results, a policy decision, or stress."],
    ["Skew / risk reversal (RR)", "IV of an out-of-the-money call minus an equally far put (25 delta). Negative = puts dearer: people pay for protection against falls."],
    ["Percentile", "Where today sits against the instrument's own past year: 90th = higher than 90% of the last 252 sessions. Every 'high' and 'low' word in the app comes from this one convention; Analyst mode adds the rank against all history where the two differ."],
    ["Open interest (OI) walls", "Strikes with the most open option contracts. Sellers there hedge and defend, so price often slows near them; they are not hard support or resistance."],
    ["PCR", "Put open interest divided by call open interest. In India most open puts are written (sold), so a high PCR often means put sellers are confident. The app shows it as a percentile, not as bullish or bearish."],
    ["Futures carry", "The futures premium over spot, annualised: roughly the funding rate minus dividends, so its normal level moves with interest rates. The app judges it against its own past year. Much higher: buyers paying up to hold longs. Lower or negative: heavy shorting or hedging."],
    ["Build-up", "Price up with OI up = long build-up; price down with OI up = short build-up; price up with OI down = short covering; price down with OI down = long unwinding. It describes what happened to positions; it does not say who is right."],
    ["Participant OI", "NSE splits open interest by who holds it: FII (foreign), DII (domestic institutions), Pro (brokers' own books) and Client (everyone else, mostly individuals)."],
    ["Event move", "When the nearest expiry has unusually high variance compared with the next one, the extra variance is the market pricing a single event day. The app shows that day's implied move."],
  ];
  app.innerHTML = `<div class="page-h"><div><h1>How to read this</h1><div class="sub">Every number, in one sentence.</div></div></div>
    <div class="grid g2">${card({ title: "Glossary", body: `<dl class="glossary">${g.map(([a, b]) => `<dt>${a}</dt><dd>${b}</dd>`).join("")}</dl>` })}
    ${card({ title: "Where the data comes from", body: `<p class="simple">NSE's and BSE's own end-of-day files: the F&O bhavcopy (every future and option, every day since 2019; BSE since 2024), official index closes, India VIX, participant-wise open interest, FII/DII cash flows and the corporate event calendar.</p>
      <p class="simple">Implied vols are computed here from those prices (Black-76 on the put-call-parity forward). Untraded strikes, which only carry a theoretical settlement price, are kept out of the at-the-money numbers.</p>
      <p class="simple"><b>What this app is not:</b> a signal service. It never says buy or sell. It shows what is priced, how unusual it is, and what happened historically, so the decision stays yours.</p>
      <p class="analyst">Percentiles compare a day with the 252 sessions before it (all-history ranks are shown in Analyst mode where they differ). Historical hit rates use overlapping windows, so they count days, not independent trials. A bonus or split is detected from the one-day jump plus the lot-size change and removed from the price history.</p>` })}</div>`;
}

// ---------------------------------------------------------------- symbol pages
const TABS = [["overview", "Overview"], ["vol", "Volatility"], ["move", "Expected move"], ["movement", "How it moves"], ["oi", "Options positions"], ["futures", "Futures"], ["events", "Events & history"]];

async function pageSymbol(app, ov, sl, tab = "overview") {
  const u = ov.universe.find((x) => x.slug === sl);
  if (!u) { app.innerHTML = `<div class="loading">Unknown instrument.</div>`; return; }
  $("#crumbs").innerHTML = `${esc(u.symbol)} <span class="muted">· ${esc(u.name)}</span>`;
  app.innerHTML = `<div class="loading">Loading ${esc(u.symbol)}…</div>`;
  const d = await symData(u.symbol);
  const h = d.headline, m = h.metrics;
  const pos52 = fin(m.pos52) ? m.pos52 * 100 : 50;
  const head = `<div class="page-h"><div><h1>${esc(u.symbol)} <span class="muted" style="font-weight:500;font-size:16px">${esc(u.name)}</span></h1>
      <div class="sub">${esc(u.sector || "")} · ${d.meta.exchange} · history since ${d.meta.since} · as of ${d.meta.asof}</div></div>${["overview", "events"].includes(tab) ? "" : horizonSeg()}</div>
    <div class="tabs">${TABS.map(([k, l]) => `<a href="#/sym/${sl}/${k}" class="${k === tab ? "on" : ""}">${l}</a>`).join("")}</div>`;
  const body = { overview: symOverview, vol: symVol, move: symMove, movement: symMovement, oi: symOI, futures: symFutures, events: symEvents }[tab] || symOverview;
  const st = d.meta.stale || {};
  const stNames = { iv30: "implied vol", rr25: "skew", implied_move: "priced move", term: "term structure", pcr_oi: "put/call ratio", carry: "carry", rv21: "realised vol", vrp: "premium" };
  const stList = Object.entries(st).filter(([k]) => stNames[k]);
  const stale = stList.length ? `<div class="callout" style="margin-bottom:14px">No reading today for ${stList.map(([k, v]) => `${stNames[k]} (last ${v})`).join(", ")}: the options did not trade enough at the money to read them cleanly, so those numbers are left blank rather than shown out of date.</div>` : "";
  app.innerHTML = head + stale + liveSlot({ kind: "symbol", ov, d, u, tab }) + `<div id="tabBody"></div>`;
  body($("#tabBody"), d, u, pos52);
  if (window.MLLive) MLLive.charts(tab, u);
  bindHorizon(route);
}

function symOverview(el, d, u, pos52) {
  const h = d.headline, m = h.metrics, c = d.cards;
  el.innerHTML = `
    <div class="hero">
      <section class="card"><div class="lab muted small">Last close</div>
        <div><span class="price num">${num(h.spot, h.spot > 1000 ? 0 : 2)}</span> <span class="chg num ${h.chg >= 0 ? "pos" : "neg"}">${vp(h.chg, 2)}%</span></div>
        <div class="range52"><div class="track"><i style="left:${pos52}%"></i></div><div class="pbar-l"><span>52w low ${num(h.lo52)}</span><span>52w high ${num(h.hi52)}</span></div></div>
        <div class="chart short" id="spark" style="margin-top:8px"></div>
      </section>
      ${card({ title: "The story today", body: `<ul class="story">${d.story.map((s) => `<li>${esc(s)}</li>`).join("")}</ul>` })}
    </div>
    <div class="grid g4" style="margin-top:16px">
      ${kpi({ label: "Options price (IV 30d)", value: pct(m.iv30), p: m.iv_p1y, lo: "cheap", hi: "expensive", foot: `5-day change ${vp(m.iv30_chg5)} vol pts` })}
      ${kpi({ label: "Actual movement (21d)", value: pct(m.rv21), p: m.rv_p, lo: "quiet", hi: "wild", foot: `≈ ${pct(m.rv21 / Math.sqrt(252), 2)} a day` })}
      ${kpi({ label: "Premium (IV − RV)", value: vp(m.vrp), unit: "vol pts", p: m.vrp_p, lo: "options cheap", hi: "options rich" })}
      ${fin(m.move) ? kpi({ label: "Priced move to expiry", value: "±" + pct(m.move, 1), unit: `${m.move_days}d`, foot: `≈ ±${num(h.spot * m.move, h.spot > 1000 ? 0 : 1)} · inside ${pct(m.inside, 0)} historically` })
        : kpi({ label: "Priced move to expiry", value: "—", foot: `no clean reading today · inside ${pct(m.inside, 0)} historically` })}
    </div>
    <div class="grid g3" style="margin-top:16px">
      ${card({ title: "Contract facts & changes", hint: "from the exchange's own data", body: rulesHtml(d) })}
      ${["vrp", "skew", "term", "oi", "futures", "realised"].filter((k) => c[k]).map((k) => card({ title: { vrp: "Options vs reality", skew: "Fear of a fall", term: "Near vs far options", oi: "Where positions sit", futures: "Futures", realised: "How it's moving" }[k],
        chip: chipFromTone(c[k].tone), simple: c[k].simple, analyst: c[k].analyst })).join("")}
    </div>`;
  const t = theme();
  const s = slice(d.series, ["close"], "1Y");
  chart("#spark", { grid: { left: 0, right: 0, top: 6, bottom: 0 }, xAxis: axisX(s.d, t, { show: false }), yAxis: axisY(t, null, { show: false }),
    series: [line("Close", s.close, t.s1, { areaStyle: { color: t.s1, opacity: .08 } })] });
}
function rulesHtml(d) {
  const r = d.rules || {}, ch = d.changes || [];
  const notes = (r.notes || []).map((n) => `<li>${esc(n.text)}</li>`).join("");
  const chg = ch.map((c) => `<li>${esc(c.label)}: ${c.from.toFixed(1)} → ${c.to.toFixed(1)} <span class="muted">(${c.chg >= 0 ? "+" : ""}${c.chg.toFixed(1)} ${c.unit}${fin(c.z) ? `, ${Math.abs(c.z).toFixed(1)}σ for it` : ""})</span></li>`).join("");
  const pl = r.position_limit;
  const gauge = pl && fin(pl.util) ? `<div style="margin:4px 0 10px"><div class="lab muted small" style="display:flex;justify-content:space-between"><span>Market-wide position limit used${pl.in_ban ? ` · <b style="color:var(--neg)">IN BAN</b>` : ""}</span><span class="num">${pct(pl.util, 0)}</span></div>
      <div style="position:relative;height:8px;border-radius:6px;background:var(--line);margin-top:6px;overflow:hidden"><b style="position:absolute;left:0;top:0;bottom:0;width:${Math.min(100, pl.util * 100)}%;background:${pl.util >= .95 || pl.in_ban ? "var(--neg)" : pl.util >= .8 ? "var(--s4)" : "var(--s1)"};border-radius:6px"></b>
      <i style="position:absolute;left:80%;top:-2px;bottom:-2px;width:2px;background:var(--text-3)"></i><i style="position:absolute;left:95%;top:-2px;bottom:-2px;width:2px;background:var(--neg)"></i></div>
      <div class="pbar-l"><span>0%</span><span>80% exit · 95% ban</span><span>100%</span></div></div>` : "";
  return `${gauge}<p class="simple">Lot size <b class="num">${num(r.lot)}</b> · next futures expiry <b class="num">${r.front_expiry || "—"}</b>${fin(r.sessions_to_expiry) ? ` (${r.sessions_to_expiry} sessions)` : ""}.</p>
    ${notes ? `<ul class="story">${notes}</ul>` : ""}
    <div class="muted small" style="margin:8px 0 2px">Since yesterday</div><ul class="story">${chg || "<li>No readings.</li>"}</ul>
    <p class="analyst">Open expiries: ${(r.expiries || []).join(", ")}. A lot-size note appears only when the exchange already lists a later expiry with a different lot.${pl ? ` Position limit from NSE's combined OI file of ${pl.mwpl_date || "—"}: open interest ${big(pl.oi)} against a limit of ${big(pl.mwpl)}${fin(pl.util_chg5) ? `, ${vp(pl.util_chg5, 0)} pts in 5 sessions` : ""}; ban status from NSE's ban list${pl.ban_date ? ` for ${pl.ban_date}` : ""}${pl.ban_window ? ` (${pl.ban_days} banned session${pl.ban_days === 1 ? "" : "s"} in the last ${pl.ban_window} read)` : ""}.` : ""}</p>`;
}
const chipFromTone = (tn) => tn === "extreme" ? `<span class="chip extreme"><span class="dot"></span>unusual</span>` : tn === "elevated" ? `<span class="chip elevated"><span class="dot"></span>notable</span>` : `<span class="chip"><span class="dot"></span>normal</span>`;

// expiry labels: weekly, or the current / near / far monthly contract
const seriesName = (x) => x.series || "expiry";
const isMonth = (x) => /month$/.test(x.series || "");

function symVol(el, d, u) {
  const c = d.cards, t = theme(), smc = [t.s1, t.s2, t.s3, t.s4, t.s7];
  const s = slice(d.series, ["close", "iv30", "rv21", "vrp", "rr25", "vix", "fwd_rv21", "pk21"]);
  el.innerHTML = `
    <div class="grid g2">
      ${card({ title: "What options charge vs how it actually moves", hint: "annualised", simple: c.iv?.simple, analyst: c.iv?.analyst, cls: "span2",
        body: `<div class="chart tall" id="ivrv"></div><div class="legend"><span style="--c:${t.s1}">Implied 30d (options' price)</span><span style="--c:${t.s2}">Realised 21d (actual)</span>${s.vix ? `<span style="--c:${t.s3}">India VIX</span>` : ""}</div>` })}
      ${card({ title: "The premium: IV − realised", hint: "vol points", simple: c.vrp?.simple, analyst: c.vrp?.analyst, body: `<div class="chart" id="vrp"></div>` })}
      ${card({ title: "Term structure", hint: "IV by expiry", simple: c.term?.simple, analyst: c.term?.analyst, body: `<div class="chart" id="term"></div><div class="legend"><span style="--c:${t.s1}">Today</span><span style="--c:${t.s2}">A week ago</span><span style="--c:${t.s3}">A month ago</span></div>` })}
      ${card({ title: "Volatility smile", hint: "IV by strike · nearest expiries and the monthly contracts", simple: "How option prices bend across strikes. A steeper left side means crash protection is in demand.", body: `<div class="chart" id="smile"></div><div class="legend">${d.smiles.map((x, i) => `<span style="--c:${smc[i]}">${x.expiry} · ${seriesName(x)} (${x.days}d)</span>`).join("")}</div>` })}
      ${card({ title: "Skew history", hint: "25-delta risk reversal", simple: c.skew?.simple, analyst: c.skew?.analyst, body: `<div class="chart" id="rr"></div>` })}
      ${curveCard(d, u)}
      ${linkCard(d, u)}
      ${card({ title: "Volatility cone", hint: "realised vol by window, since " + d.meta.since, simple: "The bands show the usual range of actual movement for each look-back; the dot is today. A dot near the top of its band: unusually wild.", analyst: c.realised?.analyst, cls: "span2", body: `<div class="chart" id="cone"></div>` })}
    </div>`;
  const tip = { trigger: "axis", valueFormatter: (v) => pct(v, 1), backgroundColor: t.surface, borderColor: t.line, textStyle: { color: t.text } };
  const ser = [line("Implied 30d", s.iv30, t.s1), line("Realised 21d", s.rv21, t.s2)];
  if (s.vix && s.vix.some(fin)) ser.push(line("India VIX", s.vix, t.s3, { lineStyle: { width: 1.5, color: t.s3, type: "dotted" } }));
  chart("#ivrv", { tooltip: tip, xAxis: axisX(s.d, t), yAxis: axisY(t, fmtPct(0)), dataZoom: [{ type: "inside" }], series: ser });
  chart("#vrp", { tooltip: { ...tip, valueFormatter: (v) => vp(v) + " pts" }, xAxis: axisX(s.d, t), yAxis: axisY(t, (v) => (v * 100).toFixed(0)),
    series: [
      line("Options rich", s.vrp.map((v) => fin(v) ? Math.max(v, 0) : null), t.dpos, { lineStyle: { width: 1, color: t.dpos }, areaStyle: { color: t.dpos, opacity: .25 },
        markLine: { silent: true, symbol: "none", data: [{ yAxis: 0 }], lineStyle: { color: t.text3, type: "dashed" }, label: { show: false } } }),
      line("Options cheap", s.vrp.map((v) => fin(v) ? Math.min(v, 0) : null), t.dneg, { lineStyle: { width: 1, color: t.dneg }, areaStyle: { color: t.dneg, opacity: .25 } })] });
  const tc = (k) => (d.term[k] || []).map((x) => ({ value: [x.days, x.iv], symbolSize: isMonth(x) ? 9 : 5, name: `${x.expiry} · ${seriesName(x)}` }));
  chart("#term", { tooltip: { trigger: "item", backgroundColor: t.surface, borderColor: t.line, textStyle: { color: t.text },
      formatter: (p) => `<b>${p.seriesName}</b><br>${p.data.name}<br>${p.data.value[0]} days · ATM IV ${pct(p.data.value[1], 1)}` },
    xAxis: { type: "value", name: "days to expiry", nameLocation: "middle", nameGap: 24, nameTextStyle: { color: t.text3, fontSize: 11 }, axisLabel: { color: t.text3 }, splitLine: { show: false } },
    yAxis: axisY(t, fmtPct(1)),
    series: [line("Today", tc("now"), t.s1, { showSymbol: true }), line("A week ago", tc("week_ago"), t.s2, { showSymbol: true, lineStyle: { width: 1.5, color: t.s2 } }), line("A month ago", tc("month_ago"), t.s3, { showSymbol: true, lineStyle: { width: 1.5, color: t.s3 } })] });
  chart("#smile", { tooltip: { trigger: "axis", valueFormatter: (v) => pct(v, 1), backgroundColor: t.surface, borderColor: t.line, textStyle: { color: t.text } },
    xAxis: { type: "value", name: "strike vs forward", nameLocation: "middle", nameGap: 24, nameTextStyle: { color: t.text3, fontSize: 11 }, axisLabel: { color: t.text3, formatter: (v) => (v >= 0 ? "+" : "") + (v * 100).toFixed(0) + "%" }, splitLine: { show: false } },
    yAxis: axisY(t, fmtPct(0)),
    series: d.smiles.map((x, i) => line(`${x.expiry} ${seriesName(x)}`, x.strike.map((k, j) => [k / x.F - 1, x.iv[j]]), smc[i], isMonth(x) ? {} : { lineStyle: { width: 1.5, type: "dashed", color: smc[i] } })) });
  curveCharts(d);
  linkChart(d);
  chart("#rr", { tooltip: { ...tip, valueFormatter: (v) => vp(v) + " pts" }, xAxis: axisX(s.d, t), yAxis: axisY(t, (v) => (v * 100).toFixed(1)),
    series: [line("Risk reversal", s.rr25, t.s7, { markLine: { silent: true, symbol: "none", data: [{ yAxis: 0 }], lineStyle: { color: t.text3, type: "dashed" }, label: { show: false } } })] });
  const cn = d.cone, W = cn.map((x) => x.window + "d");
  const band = (lo, hi, name, op) => [{ name: name + "lo", type: "line", stack: name, data: cn.map((x) => x[lo]), lineStyle: { opacity: 0 }, showSymbol: false, silent: true },
    { name, type: "line", stack: name, data: cn.map((x) => x[hi] - x[lo]), lineStyle: { opacity: 0 }, showSymbol: false, areaStyle: { color: t.s1, opacity: op }, silent: true }];
  chart("#cone", { tooltip: { trigger: "axis", backgroundColor: t.surface, borderColor: t.line, textStyle: { color: t.text },
      formatter: (ps) => { const x = cn[ps[0].dataIndex]; return `<b>${x.window}-day</b><br>today ${pct(x.now)} (${ord(x.pct)} pct)<br>median ${pct(x.p50)} · 10–90%: ${pct(x.p10)}–${pct(x.p90)}<br>range ${pct(x.min)}–${pct(x.max)}`; } },
    xAxis: { type: "category", data: W, axisLabel: { color: t.text3 }, axisLine: { lineStyle: { color: t.line } } }, yAxis: axisY(t, fmtPct(0)),
    series: [...band("p10", "p90", "10–90%", .12), ...band("p25", "p75", "25–75%", .18), line("Median", cn.map((x) => x.p50), t.s1, { lineStyle: { width: 1.5, type: "dashed", color: t.s1 } }),
      { name: "Today", type: "scatter", data: cn.map((x) => x.now), symbolSize: 11, itemStyle: { color: t.s2, borderColor: t.surface, borderWidth: 2 } }] });
}

function symMove(el, d, u) {
  const t = theme(), c = d.cards, sc = d.scorecard || {};
  const f0 = (d.term.now || [])[0];
  el.innerHTML = `
    <div class="grid g2">
      ${card({ title: "The priced range to expiry", hint: f0 ? `${f0.expiry} · ${f0.days} days` : "", simple: c.move?.simple, analyst: c.move?.analyst, cls: "span2", body: `<div class="chart tall" id="fan"></div>
        <div class="legend"><span style="--c:${t.s1}">Price</span><span style="--c:${t.s2}">±1 priced move (straddle)</span><span style="--c:${t.s3}">±2×</span></div>` })}
      ${card({ title: "Did the price stay inside the priced move?", hint: `by days to expiry · ${num(sc.n)} days since ${sc.since}`, simple: `Overall the price ended inside the straddle-priced range ${pct(sc.inside_all, 0)} of the time (last year: ${pct(sc.inside_1y, 0)}). A fairly priced straddle gives about 57%: above that, options were on average more expensive than the moves that followed.`,
        body: `<div class="chart" id="sc"></div>`, analyst: `Median realised/implied ratio over the last year: ${fin(sc.ratio_1y) ? sc.ratio_1y.toFixed(2) : "—"} (below 1 = moves smaller than priced). The 90th-percentile ratio per bucket is in the tooltip: the tail is where straddle sellers lose.` })}
      ${card({ title: "Priced vs actual, each day", hint: "front expiry, last ~400 days", simple: "Each dot is a day: across is the move options priced, up is the move that happened by expiry. Dots above the line beat the price.", body: `<div class="chart" id="scat"></div>` })}
      ${labCard(d, u)}
      ${expiryCards(d, u)}
      ${card({ title: "Every expiry on the curve", cls: "span2", body: `<div class="tbl-wrap"><table class="tbl"><thead><tr><th>Expiry</th><th>Contract</th><th>Days</th><th>ATM IV</th><th>Straddle</th><th>Priced move</th><th>Range</th></tr></thead><tbody>
        ${(d.term.now || []).map((x) => `<tr${isMonth(x) ? ' class="hl"' : ""}><td class="num">${x.expiry}</td><td>${seriesName(x)}</td><td class="num">${x.days}</td><td class="num">${pct(x.iv)}</td><td class="num">${num(x.straddle, 1)}</td><td class="num">±${pct(x.move, 2)}</td><td class="num">${num(x.F * (1 - x.move))} – ${num(x.F * (1 + x.move))}</td></tr>`).join("")}</tbody></table></div>` })}
    </div>`;
  if (f0) {
    const s = slice(d.series, ["close"], "3M");
    const last = s.close[s.close.length - 1], dts = [...s.d], n0 = s.d.length;
    const future = [];
    const start = new Date(s.d[n0 - 1]);
    for (let i = 1; i <= f0.days; i++) { const x = new Date(start); x.setDate(x.getDate() + i); if (x.getDay() % 6) future.push(x.toISOString().slice(0, 10)); }
    dts.push(...future);
    const nf = future.length, pad = Array(n0 - 1).fill(null);
    const bandAt = (k, mult) => [last, ...future.map((_, i) => last * (1 + k * mult * Math.sqrt((i + 1) / nf)))];
    chart("#fan", { tooltip: { trigger: "axis", valueFormatter: (v) => num(v, 0), backgroundColor: t.surface, borderColor: t.line, textStyle: { color: t.text } },
      xAxis: axisX(dts, t), yAxis: axisY(t, (v) => num(v)), dataZoom: [{ type: "inside", startValue: Math.max(0, n0 - 45) }],
      series: [line("Price", s.close, t.s1),
        line("+1×", [...pad, ...bandAt(1, f0.move)], t.s2, { lineStyle: { width: 1.5, type: "dashed", color: t.s2 } }), line("−1×", [...pad, ...bandAt(-1, f0.move)], t.s2, { lineStyle: { width: 1.5, type: "dashed", color: t.s2 } }),
        line("+2×", [...pad, ...bandAt(1, 2 * f0.move)], t.s3, { lineStyle: { width: 1, type: "dotted", color: t.s3 } }), line("−2×", [...pad, ...bandAt(-1, 2 * f0.move)], t.s3, { lineStyle: { width: 1, type: "dotted", color: t.s3 } })] });
  }
  expiryCharts(d);
  const b = sc.buckets || [];
  chart("#sc", { grid: { left: 44, right: 16, top: 20, bottom: 30 }, tooltip: { trigger: "axis", backgroundColor: t.surface, borderColor: t.line, textStyle: { color: t.text },
      formatter: (ps) => { const x = b[ps[0].dataIndex]; return `<b>${x.bucket}</b> (${num(x.n)} days)<br>inside: ${pct(x.inside, 0)}<br>avg priced ${pct(x.avg_implied, 2)} · avg actual ${pct(x.avg_realised, 2)}<br>90th pct actual/priced: ${x.p90_ratio.toFixed(2)}×`; } },
    xAxis: { type: "category", data: b.map((x) => x.bucket), axisLabel: { color: t.text3 }, axisLine: { lineStyle: { color: t.line } } }, yAxis: axisY(t, fmtPct(0), { min: 0, max: 1, scale: false }),
    series: [{ type: "bar", data: b.map((x) => x.inside), barWidth: "45%", itemStyle: { color: t.s1, borderRadius: [4, 4, 0, 0] }, label: { show: true, position: "top", color: t.text2, formatter: (p) => pct(p.value, 0) },
      markLine: { silent: true, symbol: "none", data: [{ yAxis: .57, label: { formatter: "fair ≈57%", color: t.text3 } }], lineStyle: { color: t.text3, type: "dashed" } } }] });
  const ss = d.scorecard_series;
  if (ss) {
    const pts = ss.d.map((x, i) => [ss.implied_move[i], ss.realised[i], x]);
    const mx = Math.max(...pts.map((p) => Math.max(p[0], p[1])).filter(fin));
    chart("#scat", { grid: { left: 48, right: 16, top: 16, bottom: 40 }, tooltip: { trigger: "item", backgroundColor: t.surface, borderColor: t.line, textStyle: { color: t.text }, formatter: (p) => `${p.data[2]}<br>priced ±${pct(p.data[0], 2)} · actual ${pct(p.data[1], 2)}` },
      xAxis: { type: "value", name: "priced move", nameLocation: "middle", nameGap: 26, nameTextStyle: { color: t.text3, fontSize: 11 }, axisLabel: { color: t.text3, formatter: fmtPct(0) }, splitLine: { lineStyle: { color: t.line2 } } },
      yAxis: { type: "value", name: "actual move", nameTextStyle: { color: t.text3, fontSize: 11 }, axisLabel: { color: t.text3, formatter: fmtPct(0) }, splitLine: { lineStyle: { color: t.line2 } } },
      series: [{ type: "scatter", data: pts, symbolSize: 6, itemStyle: { color: t.s1, opacity: .55 } },
        { type: "line", data: [[0, 0], [mx, mx]], showSymbol: false, lineStyle: { color: t.s2, type: "dashed", width: 1.5 }, silent: true, tooltip: { show: false } }] });
  }
}

// ---- how it moves: range, gaps, compression, participation (engine/movement.py) ----
function symMovement(el, d, u) {
  const m = d.movement, t = theme();
  if (!m) { el.innerHTML = `<div class="callout">No daily high-low data for ${u.symbol} yet: the cash-market table starts with the warehouse's next update.</div>`; return; }
  const st = m.study, stock = u.kind === "stock";
  const swing = fin(m.yz21) && fin(m.cc21) ? m.yz21 / m.cc21 : null;
  const tiles = `<div class="grid g4">
    ${kpi({ label: "Average true range (14d)", value: pct(m.atr14, 2), foot: `a typical day's full swing · ${fin(m.atr_rank) ? ord(m.atr_rank) + " percentile of 1y" : ""}` })}
    ${kpi({ label: "Range vol vs close vol", value: fin(swing) ? swing.toFixed(2) + "×" : "—", foot: `Yang-Zhang ${pct(m.yz21, 1)} vs close-to-close ${pct(m.cc21, 1)}` })}
    ${kpi({ label: "Overnight share of variance", value: pct(m.ovn_share, 0), foot: "the part an option seller cannot hedge (63d)" })}
    ${kpi({ label: "20-day range", value: pct(m.rng20, 1), foot: `${ord(m.rng20_rank)} percentile of 1y${m.nr7 ? " · NR7 today" : ""}` })}
  </div>`;
  const comp = fin(m.rng20_rank) && m.rng20_rank <= 0.2 ? "compressed" : fin(m.rng20_rank) && m.rng20_rank >= 0.8 ? "wide" : "normal";
  const studyTxt = st ? `Since ${st.since}, after compressed days (20-day range in the bottom fifth of its year) the next ${st.horizon} sessions' realised vol was ${st.raw_comp.toFixed(2)}× the recent vol, against ${st.raw_other.toFixed(2)}× after other days: ${st.raw_comp > st.raw_other ? "quiet spells do tend to end" : "no rebound shows even in raw terms"}. But measured against what options priced that day, it was ${st.z_comp.toFixed(2)}× the 30-day IV after compression and ${st.z_other.toFixed(2)}× otherwise (block-permutation p = ${st.p.toFixed(2)} for 'bigger after compression'). ${st.p < 0.05 ? "Compression has been followed by more movement than options priced." : "The rebound is ordinary volatility mean-reversion, and options already price it: compression is not an edge on its own."}` : "Not enough history to test compression here.";
  el.innerHTML = `${tiles}
    <div class="grid g2" style="margin-top:16px">
      ${card({ title: "How big the days are", hint: "annualised, 21 sessions", cls: "span2",
        simple: `${u.symbol}'s daily swings, measured four ways. ${fin(swing) ? (swing > 1.1 ? "The range estimators run above close-to-close: the days swing more than where they settle." : swing < 0.9 ? "Close-to-close runs above the range estimators: big closing moves and gaps, more than intraday swings." : "The four agree: the days settle about as far as they swing.") : ""}`,
        analyst: "Close-to-close: standard deviation of daily log returns. Parkinson: from the high-low range only. Garman-Klass: adds open-to-close. Yang-Zhang: adds the overnight gap and is unbiased under drift; it is the one to set against an option's implied vol. Split-adjusted; a demerger day is left out.",
        body: `<div class="chart" id="mvEst"></div><div class="legend"><span style="--c:${t.s1}">Close-to-close</span><span style="--c:${t.s2}">Yang-Zhang</span><span style="--c:${t.s3}">Garman-Klass</span></div>` })}
      ${card({ title: "Gaps", hint: "open against the previous close",
        simple: `Over the past year the median gap was ${pct(m.gap_p50, 2)} and one day in twenty opened ${pct(m.gap_p95, 2)} or more away. Overnight carries ${pct(m.ovn_share, 0)} of the variance.`,
        analyst: "Overnight share: variance of log(open / previous close) over the variance of that plus log(close / open), 63 sessions.",
        body: `<div class="chart" id="mvGap" style="height:200px"></div><div class="tbl-wrap" style="margin-top:8px"><table class="tbl"><thead><tr><th>Biggest gaps of the year</th><th>Gap</th></tr></thead><tbody>
          ${(m.big_gaps || []).map((g) => `<tr><td class="num">${g.date}</td><td class="num"><span class="chg ${g.gap >= 0 ? "pos" : "neg"}">${vp(g.gap, 2)}%</span></td></tr>`).join("")}</tbody></table></div>` })}
      ${card({ title: "Compression", hint: "20-day range and band width, ranked against the past year",
        simple: `The 20-day range is ${comp} for ${u.symbol} (${ord(m.rng20_rank)} percentile). ${studyTxt}`,
        body: `<div class="chart" id="mvComp"></div><div class="legend"><span style="--c:${t.s7}">20-day range rank</span><span style="--c:${t.s1}">Band-width rank</span></div>` })}
      ${stock ? card({ title: "Participation", hint: "volume, delivery and liquidity", cls: "span2",
        simple: `Volume today is ${fin(m.vol_z) ? (m.vol_z >= 0 ? "+" : "") + m.vol_z.toFixed(1) + " standard deviations" : "—"} against its last 63 sessions; ${pct(m.deliv, 0)} of the traded shares were taken for delivery (${ord(m.deliv_rank)} percentile of its year). Descriptive: delivery shows how much of the day's trade was not day-trading, not who was right.`,
        analyst: `Amihud illiquidity (median absolute return per Rs crore traded, 63 sessions): ${fin(m.amihud) ? m.amihud.toFixed(3) : "—"} bp per crore, ${ord(m.amihud_rank)} percentile of its year (higher: a rupee moves the price more). From NSE's cash-market bhavcopy, since ${m.since}.`,
        body: `<div class="chart" id="mvPart"></div><div class="legend"><span style="--c:${t.s1}">Volume z-score</span><span style="--c:${t.s2}">Delivery %</span></div>` }) : ""}
    </div>`;
  const s = slice(d.series, ["mv_cc21", "mv_yz21", "mv_gk21", "mv_gap", "mv_rng20_rank", "mv_bbw_rank", "mv_vol_z", "mv_deliv"]);
  const tip = (f) => ({ trigger: "axis", valueFormatter: f, backgroundColor: t.surface, borderColor: t.line, textStyle: { color: t.text } });
  chart("#mvEst", { tooltip: tip((v) => pct(v, 1)), xAxis: axisX(s.d, t), yAxis: axisY(t, fmtPct(0)),
    series: [line("Close-to-close", s.mv_cc21, t.s1), line("Yang-Zhang", s.mv_yz21, t.s2), line("Garman-Klass", s.mv_gk21, t.s3, { lineStyle: { width: 1.2, color: t.s3 } })] });
  chart("#mvGap", { grid: { left: 52, right: 18, top: 12, bottom: 26 }, tooltip: tip((v) => vp(v, 2) + "%"), xAxis: axisX(s.d, t, { boundaryGap: true }), yAxis: axisY(t, (v) => (v * 100).toFixed(1) + "%"),
    series: [{ name: "Gap", type: "bar", data: (s.mv_gap || []).map((v) => ({ value: v, itemStyle: { color: fin(v) && v < 0 ? t.dneg : t.dpos } })), barCategoryGap: "10%" }] });
  chart("#mvComp", { tooltip: tip((v) => ord(v)), xAxis: axisX(s.d, t), yAxis: axisY(t, fmtPct(0), { min: 0, max: 1, scale: false }),
    series: [line("20-day range rank", s.mv_rng20_rank, t.s7, { connectNulls: false, markArea: { silent: true, itemStyle: { color: t.dpos, opacity: .08 }, data: [[{ yAxis: 0 }, { yAxis: 0.2 }]] } }),
      line("Band-width rank", s.mv_bbw_rank, t.s1, { connectNulls: false, lineStyle: { width: 1.2, color: t.s1 } })] });
  if (stock && $("#mvPart")) chart("#mvPart", { grid: { left: 52, right: 52, top: 16, bottom: 26 }, tooltip: { trigger: "axis", backgroundColor: t.surface, borderColor: t.line, textStyle: { color: t.text } }, xAxis: axisX(s.d, t, { boundaryGap: true }),
    yAxis: [axisY(t, (v) => v.toFixed(1)), axisY(t, fmtPct(0), { position: "right", splitLine: { show: false } })],
    series: [{ name: "Volume z", type: "bar", data: (s.mv_vol_z || []).map((v) => ({ value: v, itemStyle: { color: fin(v) && v >= 2 ? t.s4 : t.s1, opacity: .7 } })), barCategoryGap: "10%" },
      line("Delivery %", s.mv_deliv, t.s2, { yAxisIndex: 1, lineStyle: { width: 1.2, color: t.s2 } })] });
}

function symOI(el, d, u) {
  const t = theme(), c = d.cards;
  const prof = d.oi_profile || [];
  const s = slice(d.series, ["pcr_oi", "pcr_vol", "opt_oi", "close"]);
  el.innerHTML = `
    <div class="grid g2">
      ${card({ title: "Open interest by strike", hint: "calls to the right, puts to the left", simple: c.oi?.simple, analyst: c.oi?.analyst, cls: "span2",
        body: `<div class="seg" id="expSeg" style="margin-bottom:8px">${prof.map((p, i) => `<button data-i="${i}" class="${i ? "" : "on"}">${p.expiry} · ${p.days}d</button>`).join("")}</div>
        <div class="seg" id="oiMode" style="margin:0 0 8px 8px"><button data-m="oi" class="on">Open positions</button><button data-m="chg">Today's change</button></div>
        <div class="chart tall" id="oi" style="height:460px"></div><div class="legend"><span style="--c:${t.s1}">Calls</span><span style="--c:${t.s2}">Puts</span></div>` })}
      ${gammaCards(d, u)}
      ${card({ title: "Put / call ratio history", hint: "open interest, all expiries", simple: "Puts open divided by calls open. Shown against its own past rather than as 'bullish' or 'bearish': in India most open puts are sold, so the ratio says more about how crowded put-selling is than about direction.", body: `<div class="chart" id="pcr"></div>` })}
      ${card({ title: "Total options open interest", hint: "all strikes, OI units (shares or index quantity)", simple: "How many option positions are open. Rising positions mean money committing; falling, money leaving.", body: `<div class="chart" id="toi"></div>` })}
    </div>`;
  let sel = 0, mode = "oi";
  const draw = () => {
    const p = prof[sel]; if (!p) return;
    const ce = mode === "oi" ? p.call_oi : p.call_chg, pe = mode === "oi" ? p.put_oi : p.put_chg;
    const spot = d.headline.spot;
    const ex = S.charts.find((c) => c.getDom() === $("#oi")); if (ex) { ex.dispose(); S.charts = S.charts.filter((c) => c !== ex); }
    chart("#oi", { grid: { left: 64, right: 24, top: 10, bottom: 30 }, tooltip: { trigger: "axis", axisPointer: { type: "shadow" }, backgroundColor: t.surface, borderColor: t.line, textStyle: { color: t.text },
        formatter: (ps) => `<b>Strike ${num(p.strikes[ps[0].dataIndex])}</b><br>calls ${big(ce[ps[0].dataIndex])}<br>puts ${big(pe[ps[0].dataIndex])}` },
      yAxis: { type: "category", data: p.strikes.map((k) => num(k)), axisLabel: { color: t.text3, fontSize: 10 }, axisLine: { lineStyle: { color: t.line } }, axisTick: { show: false } },
      xAxis: { type: "value", axisLabel: { color: t.text3, formatter: (v) => big(Math.abs(v)) }, splitLine: { lineStyle: { color: t.line2 } } },
      series: [{ name: "Calls", type: "bar", stack: "x", data: ce, itemStyle: { color: t.s1, borderRadius: [0, 3, 3, 0] }, barCategoryGap: "25%",
          markLine: { silent: true, symbol: "none", lineStyle: { color: t.text, type: "dashed" }, label: { formatter: `price ${num(spot)}`, color: t.text2 },
            data: [{ yAxis: p.strikes.reduce((bi, k, i) => Math.abs(k - spot) < Math.abs(p.strikes[bi] - spot) ? i : bi, 0) }] } },
        { name: "Puts", type: "bar", stack: "x", data: pe.map((v) => -v), itemStyle: { color: t.s2, borderRadius: [3, 0, 0, 3] } }] });
  };
  $$("#expSeg button").forEach((b) => b.onclick = () => { sel = +b.dataset.i; $$("#expSeg button").forEach((x) => x.classList.toggle("on", x === b)); draw(); });
  $$("#oiMode button").forEach((b) => b.onclick = () => { mode = b.dataset.m; $$("#oiMode button").forEach((x) => x.classList.toggle("on", x === b)); draw(); });
  draw();
  gammaCharts(d, u);
  chart("#pcr", { tooltip: { trigger: "axis", valueFormatter: (v) => fin(v) ? v.toFixed(2) : "—", backgroundColor: t.surface, borderColor: t.line, textStyle: { color: t.text } }, xAxis: axisX(s.d, t), yAxis: axisY(t, (v) => v.toFixed(2)),
    series: [line("PCR daily", s.pcr_oi, t.s1, { lineStyle: { width: 1, color: t.s1, opacity: .35 }, markLine: regimeMarks(d, s.d, t) }), line("10-day average", ma(s.pcr_oi, 10), t.s1)] });
  chart("#toi", { tooltip: { trigger: "axis", valueFormatter: big, backgroundColor: t.surface, borderColor: t.line, textStyle: { color: t.text } }, xAxis: axisX(s.d, t), yAxis: axisY(t, big),
    series: [line("Options OI daily", s.opt_oi, t.s7, { lineStyle: { width: 1, color: t.s7, opacity: .35 }, markLine: regimeMarks(d, s.d, t) }), line("10-day average", ma(s.opt_oi, 10), t.s7)] });
}

// ---- gamma by strike (engine/gamma.py) ----
const cr = (v, dp = 0) => (fin(v) ? "₹" + num(v, dp) + " cr" : "—");
const kfmt = (v) => (Math.abs(v) >= 1000 ? (v / 1000).toFixed(Math.abs(v) >= 1e4 ? 0 : 1) + "k" : num(v));
function gammaStory(g, u) {
  const w = g.weights, st = g.study, away = (x) => vp(x / g.spot - 1, 1) + "%";
  if (!w || !fin(g.net_total)) return { simple: `Where option hedging would be heaviest if ${u.symbol} moves: the gamma of every strike's open positions, calls and puts. NSE's participant file covers all stocks together, so it cannot say who is long this stock's gamma: no net is estimated.`, analyst: "" };
  const long = g.net_total > 0;
  let simple = `On NSE's own position figures, the desks that hedge (prop traders and FIIs) are net ${long ? "long" : "short"} option gamma around ${u.symbol}'s price: their hedging ${long ? "sells into rises and buys into falls, which damps moves" : "buys into rises and sells into falls, which feeds moves"}.`;
  simple += fin(g.flip) ? ` That turns ${long ? "short" : "long"} at about ${num(g.flip)} (${away(g.flip)}).` : ` It stays ${long ? "long" : "short"} across ±5% of the price.`;
  let analyst = `Hedgers' net share of index open interest (${w.date}): calls ${vp(w.calls, 1)}%, puts ${vp(w.puts, 1)}%, applied to every strike (the file is one figure for all index options). Net ${cr(g.net_total)} per 1% move; total call gamma ${cr(g.call_total)}, put gamma ${cr(g.put_total)}. Expiries read: ${g.expiries.join(", ")}.`;
  if (st) analyst += ` Does the sign matter? Since ${st.since}, on the ${num(st.n_neg)} days the hedgers were short gamma the next day's move was ${pct(st.raw_neg, 2)} against ${pct(st.raw_pos, 2)} on the ${num(st.n_pos)} long-gamma days; measured against what options already priced that day, ${st.z_neg.toFixed(2)} against ${st.z_pos.toFixed(2)} of the priced daily move (permutation p = ${st.p.toFixed(2)}). ${st.p < 0.05 ? "The gap holds beyond the priced volatility." : "The raw gap is the volatile years, not the gamma: read this as where hedging sits, not as a forecast."}`;
  return { simple, analyst };
}
function gammaCards(d, u) {
  const g = d.gamma;
  if (!g || !g.strikes || !g.strikes.length) return "";
  const t = theme(), st = gammaStory(g, u), hasNet = !!g.net;
  return `${card({ title: "Gamma by strike", hint: "Rs crore of hedging per 1% move · all expiries read", cls: "span2", simple: st.simple, analyst: st.analyst,
      body: `${hasNet ? `<div class="seg" id="gmMode" style="margin-bottom:8px"><button data-m="side" class="on">Calls and puts</button><button data-m="net">Hedgers' net</button></div>` : ""}
        <div class="chart tall" id="gmap" style="height:440px"></div><div class="legend" id="gmLeg"><span style="--c:${t.s1}">Call gamma</span><span style="--c:${t.s2}">Put gamma</span></div>` })}
    ${hasNet && g.profile ? card({ title: "Hedgers' net gamma if the price moves", hint: "same positions, prices ±5%", simple: "Each point re-prices every strike's gamma at that index level, positions unchanged. Above zero their hedging damps moves; below, it adds to them.", body: `<div class="chart" id="gprof"></div>` }) : ""}
    ${card({ title: "Gamma over time", hint: hasNet ? "total and hedgers' net, Rs crore per 1%" : "total call and put gamma, Rs crore per 1%", simple: "How much hedging the open options carry each day. It swells into an expiry and empties after it.", body: `<div class="chart" id="ghist"></div>` })}`;
}
function gammaCharts(d, u) {
  const g = d.gamma, t = theme();
  if (!g || !g.strikes || !$("#gmap")) return;
  const near = (v) => g.strikes.reduce((bi, k, i) => Math.abs(k - v) < Math.abs(g.strikes[bi] - v) ? i : bi, 0);
  const inRange = (v) => fin(v) && v >= g.strikes[0] && v <= g.strikes[g.strikes.length - 1];
  const marks = () => ({ silent: true, symbol: "none", lineStyle: { type: "dashed" }, data: [
    { yAxis: near(g.spot), lineStyle: { color: t.text }, label: { formatter: `price ${num(g.spot)}`, color: t.text2 } },
    ...(inRange(g.flip) ? [{ yAxis: near(g.flip), lineStyle: { color: t.s4 }, label: { formatter: `flip ${num(g.flip)}`, color: t.s4 } }] : [])] });
  let mode = "side";
  const draw = () => {
    const ex = S.charts.find((c) => c.getDom() === $("#gmap")); if (ex) { ex.dispose(); S.charts = S.charts.filter((c) => c !== ex); }
    const series = mode === "side"
      ? [{ name: "Call gamma", type: "bar", stack: "x", data: g.call, itemStyle: { color: t.s1, borderRadius: [0, 3, 3, 0] }, barCategoryGap: "25%", markLine: marks() },
         { name: "Put gamma", type: "bar", stack: "x", data: g.put.map((v) => -v), itemStyle: { color: t.s2, borderRadius: [3, 0, 0, 3] } }]
      : [{ name: "Hedgers' net", type: "bar", data: g.net.map((v) => ({ value: v, itemStyle: { color: v >= 0 ? t.dpos : t.dneg } })), barCategoryGap: "25%", markLine: marks() }];
    chart("#gmap", { grid: { left: 64, right: 24, top: 10, bottom: 30 }, tooltip: { trigger: "axis", axisPointer: { type: "shadow" }, backgroundColor: t.surface, borderColor: t.line, textStyle: { color: t.text },
        formatter: (ps) => { const i = ps[0].dataIndex; return `<b>Strike ${num(g.strikes[i])}</b><br>call gamma ${cr(g.call[i], 1)}<br>put gamma ${cr(g.put[i], 1)}${g.net ? `<br>hedgers' net ${cr(g.net[i], 1)}` : ""}`; } },
      yAxis: { type: "category", data: g.strikes.map((k) => num(k)), axisLabel: { color: t.text3, fontSize: 10 }, axisLine: { lineStyle: { color: t.line } }, axisTick: { show: false } },
      xAxis: { type: "value", axisLabel: { color: t.text3, formatter: (v) => num(Math.abs(v)) }, splitLine: { lineStyle: { color: t.line2 } } }, series });
    const leg = $("#gmLeg");
    if (leg) leg.innerHTML = mode === "side" ? `<span style="--c:${t.s1}">Call gamma</span><span style="--c:${t.s2}">Put gamma</span>` : `<span style="--c:${t.dpos}">Hedgers long gamma (damping)</span><span style="--c:${t.dneg}">Hedgers short gamma (amplifying)</span>`;
  };
  $$("#gmMode button").forEach((b) => b.onclick = () => { mode = b.dataset.m; $$("#gmMode button").forEach((x) => x.classList.toggle("on", x === b)); draw(); });
  draw();
  if (g.profile && $("#gprof")) {
    const pr = g.profile;
    chart("#gprof", { tooltip: { trigger: "axis", backgroundColor: t.surface, borderColor: t.line, textStyle: { color: t.text }, formatter: (ps) => `at ${num(pr.price[ps[0].dataIndex])}<br>net ${cr(pr.net[ps[0].dataIndex])}` },
      xAxis: { type: "value", min: pr.price[0], max: pr.price[pr.price.length - 1], name: "price", nameLocation: "middle", nameGap: 24, nameTextStyle: { color: t.text3, fontSize: 11 }, axisLabel: { color: t.text3, formatter: (v) => num(v) }, splitLine: { show: false } },
      yAxis: axisY(t, (v) => num(v), { scale: false }),
      series: [line("Hedgers' net", pr.price.map((p, i) => [p, pr.net[i]]), t.s7, { areaStyle: { color: t.s7, opacity: .08 },
        markLine: { silent: true, symbol: "none", lineStyle: { type: "dashed" }, data: [{ yAxis: 0, lineStyle: { color: t.text3 }, label: { show: false } },
          { xAxis: g.spot, lineStyle: { color: t.text }, label: { formatter: "price", color: t.text2 } },
          ...(fin(g.flip) ? [{ xAxis: g.flip, lineStyle: { color: t.s4 }, label: { formatter: "flip", color: t.s4 } }] : [])] } })] });
  }
  const s = slice(d.series, ["gamma_call", "gamma_put", "gamma_net"]);
  if ($("#ghist") && s.gamma_call) {
    const tot = s.gamma_call.map((v, i) => fin(v) && fin(s.gamma_put[i]) ? v + s.gamma_put[i] : null);
    const ser = [line("Total gamma", tot, t.s1, { areaStyle: { color: t.s1, opacity: .08 } })];
    if (s.gamma_net) ser.push(line("Hedgers' net", s.gamma_net, t.s7, { markLine: { silent: true, symbol: "none", data: [{ yAxis: 0 }], lineStyle: { color: t.text3, type: "dashed" }, label: { show: false } } }));
    chart("#ghist", { tooltip: { trigger: "axis", valueFormatter: (v) => cr(v), backgroundColor: t.surface, borderColor: t.line, textStyle: { color: t.text } }, xAxis: axisX(s.d, t), yAxis: axisY(t, kfmt), series: ser });
  }
}

// ---- the curve between months ----
function curveCard(d, u) {
  const c = d.curve || {}, m = c.months || {};
  const rows = [["current month", "iv_m1", "rr_m1"], ["near month", "iv_m2", "rr_m2"], ["far month", "iv_m3", "rr_m3"]].filter(([, a]) => fin(m[a]));
  if (!fin(c.term_60_30) && !rows.length) return "";
  const tilt = fin(c.term_60_30) ? (c.term_60_30 > 0.005 ? "upward: later months cost more, the usual calm shape" : c.term_60_30 < -0.005 ? "inverted: the next month is dearer than the one after, as when trouble is expected soon" : "flat") : null;
  const simple = tilt ? `The 2-month option price against the 1-month one is ${vp(c.term_60_30, 1)} vol points: the curve is ${tilt}${fin(c.term_p) ? ` (${ord(c.term_p)} percentile of the past year)` : ""}.` : "Not enough listed months today to compare one horizon with another.";
  const tbl = rows.length ? `<div class="tbl-wrap" style="margin-top:10px"><table class="tbl"><thead><tr><th>Contract</th><th>ATM IV</th><th>25-delta skew</th></tr></thead><tbody>
    ${rows.map(([n, a, b]) => `<tr><td>${n}</td><td class="num">${pct(m[a])}</td><td class="num">${fin(m[b]) ? vp(m[b]) + " pts" : "—"}</td></tr>`).join("")}</tbody></table></div>` : "";
  return card({ title: "The curve between months", hint: "constant-maturity IV: 30, 60, 90 days", cls: "span2", simple,
    analyst: `IV at fixed horizons by total-variance interpolation between expiries, shown only where the listed expiries reach the horizon (no flat extension). Today: 30d ${pct(d.headline.metrics?.iv30 ?? null)}, 60d ${pct(c.iv60)}, 90d ${pct(c.iv90)}. Skew is the 25-delta risk reversal of each monthly contract (negative: puts dearer).`,
    body: `<div class="chart" id="cmIv"></div><div class="legend"><span style="--c:${theme().s1}">30 days</span><span style="--c:${theme().s2}">60 days</span><span style="--c:${theme().s3}">90 days</span></div>
      <div class="chart" id="cmSpread" style="height:180px"></div>${tbl}` });
}
function curveCharts(d) {
  if (!$("#cmIv")) return;
  const t = theme(), s = slice(d.series, ["iv30", "iv60", "iv90", "term_60_30"]);
  chart("#cmIv", { tooltip: { trigger: "axis", valueFormatter: (v) => pct(v, 1), backgroundColor: t.surface, borderColor: t.line, textStyle: { color: t.text } }, xAxis: axisX(s.d, t), yAxis: axisY(t, fmtPct(0)),
    // no joining across days without a reading: the 60/90-day lines exist only when the listed expiries reach them
    series: [line("30 days", s.iv30, t.s1), ...(s.iv60 ? [line("60 days", s.iv60, t.s2, { connectNulls: false })] : []), ...(s.iv90 ? [line("90 days", s.iv90, t.s3, { connectNulls: false, lineStyle: { width: 1.5, color: t.s3 } })] : [])] });
  if (s.term_60_30) chart("#cmSpread", { grid: { left: 52, right: 18, top: 16, bottom: 26 }, tooltip: { trigger: "axis", valueFormatter: (v) => vp(v) + " pts", backgroundColor: t.surface, borderColor: t.line, textStyle: { color: t.text } }, xAxis: axisX(s.d, t), yAxis: axisY(t, (v) => (v * 100).toFixed(1)),
    series: [line("60d − 30d", s.term_60_30.map((v) => fin(v) ? Math.max(v, 0) : null), t.dpos, { connectNulls: false, lineStyle: { width: 1, color: t.dpos }, areaStyle: { color: t.dpos, opacity: .25 },
        markLine: { silent: true, symbol: "none", data: [{ yAxis: 0 }], lineStyle: { color: t.text3, type: "dashed" }, label: { show: false } } }),
      line("inverted", s.term_60_30.map((v) => fin(v) ? Math.min(v, 0) : null), t.dneg, { connectNulls: false, lineStyle: { width: 1, color: t.dneg }, areaStyle: { color: t.dneg, opacity: .25 } })] });
}
// ---- how much of a stock's move is its own (engine/linkage.py) ----
function linkCard(d, u) {
  const k = d.link;
  if (!k || !fin(k.own)) return "";
  const own = k.own, word = own >= 0.7 ? "mostly its own" : own >= 0.45 ? "about half its own" : "mostly the market's";
  return card({ title: "How much of its move is its own", hint: "last 63 sessions", cls: "span2",
    simple: `${pct(own, 0)} of ${u.symbol}'s day-to-day variance is its own, not NIFTY's or ${k.sector_index || "its sector"}'s: its moves are ${word}${fin(k.own_p) ? ` (${ord(k.own_p)} percentile of its past year)` : ""}. Its options price that own risk (results, deals, news) on top of the market's, which an index option cannot hedge.`,
    analyst: `Rolling 63-session regression of daily log returns on NIFTY${k.sector_index ? ` and ${k.sector_index}` : ""}: beta to NIFTY ${fin(k.beta_n) ? k.beta_n.toFixed(2) : "—"} (correlation ${fin(k.corr_n) ? k.corr_n.toFixed(2) : "—"})${fin(k.beta_s) ? `, beta to the sector ${k.beta_s.toFixed(2)} (correlation ${k.corr_s.toFixed(2)})` : ""}; R² of the two together ${pct(k.r2, 0)}. Own share = 1 − R². Split- and demerger-adjusted prices.`,
    body: `<div class="chart" id="lkOwn" style="height:200px"></div><div class="legend"><span style="--c:${theme().s7}">Own share of variance</span><span style="--c:${theme().s1}">Beta to NIFTY</span></div>` });
}
function linkChart(d) {
  if (!$("#lkOwn")) return;
  const t = theme(), s = slice(d.series, ["own", "beta_n"]);
  chart("#lkOwn", { grid: { left: 52, right: 52, top: 16, bottom: 26 }, tooltip: { trigger: "axis", backgroundColor: t.surface, borderColor: t.line, textStyle: { color: t.text } }, xAxis: axisX(s.d, t),
    yAxis: [axisY(t, fmtPct(0), { min: 0, max: 1, scale: false }), axisY(t, (v) => v.toFixed(1), { position: "right", splitLine: { show: false } })],
    series: [line("Own share", s.own, t.s7, { areaStyle: { color: t.s7, opacity: .08 }, tooltip: { valueFormatter: (v) => pct(v, 0) } }), line("Beta to NIFTY", s.beta_n, t.s1, { yAxisIndex: 1, lineStyle: { width: 1.2, color: t.s1 } })] });
}

// ---- the roll between futures months ----
function rollCard(d, u) {
  const c = d.curve || {};
  if (!fin(c.cal_carry)) return "";
  return card({ title: "The roll between months", hint: "next month's future over this month's, annualised",
    simple: `Rolling a position from this month's future into the next costs ${pct(c.cal_carry)} a year${fin(c.cal_carry_p) ? `, ${ord(c.cal_carry_p)} percentile of the past year` : ""}${fin(c.cal_spread) && u.kind === "index" ? ` (${num(c.cal_spread, 1)} points)` : ""}. A dear roll means longs are paying up to stay in.`,
    analyst: "ln(next future / this future) over the days between the two expiries, at each close: the market's own financing rate for the roll, independent of when the spot printed. Compare with the futures premium over spot beside it.",
    body: `<div class="chart" id="calc"></div><div class="legend"><span style="--c:${theme().s7}">Roll rate between months</span><span style="--c:${theme().s1}">Premium over spot</span></div>` });
}
function rollChart(d) {
  if (!$("#calc")) return;
  const t = theme(), s = slice(d.series, ["cal_carry", "carry"]), ok = (v) => (fin(v) && Math.abs(v) < 1 ? v : null);
  chart("#calc", { tooltip: { trigger: "axis", valueFormatter: (v) => pct(v, 1), backgroundColor: t.surface, borderColor: t.line, textStyle: { color: t.text } }, xAxis: axisX(s.d, t), yAxis: axisY(t, fmtPct(0)),
    series: [line("Roll rate", (s.cal_carry || []).map(ok), t.s7), line("Premium over spot", (s.carry || []).map(ok), t.s1, { lineStyle: { width: 1, color: t.s1, opacity: .5 } })] });
}

// ---- days like today (engine/baserates.py) ----
function labCard(d, u) {
  const L = d.lab;
  if (!L || !L.baseline) return "";
  const st = L.state, b = L.baseline;
  const ivw = { cheap: "cheap (bottom fifth of its year)", normal: "in its usual range", dear: "dear (top fifth of its year)" }[st.iv];
  const pw = st.premium === "premium" ? "above the vol of the last month" : "below the vol of the last month";
  const cw = st.curve === "inverted" ? "the curve inverted" : st.curve === "upward" ? "the curve sloping up" : "no curve reading";
  const row = (name, x) => x ? `<tr><td>${name}</td><td class="num">${num(x.n)} <span class="muted small">(${num(x.episodes)} episodes)</span></td>
      <td class="num">${x.ratio.toFixed(2)}× <span class="muted small">${x.ratio_ci[0].toFixed(2)}–${x.ratio_ci[1].toFixed(2)}</span></td>
      <td class="num">${pct(x.inside, 0)} <span class="muted small">${pct(x.inside_ci[0], 0)}–${pct(x.inside_ci[1], 0)}</span></td>
      <td class="num">${x.before_2024 ? x.before_2024.ratio.toFixed(2) + "×" : "—"}</td><td class="num">${x.from_2024 ? x.from_2024.ratio.toFixed(2) + "×" : "—"}</td></tr>`
    : `<tr><td>${name}</td><td colspan="5" class="muted small" style="text-align:left">too few past days to say</td></tr>`;
  const v = L.verdict.neighbours, nn = L.neighbours;
  const say = !nn ? "Too few comparable days to say anything." : v === "higher"
    ? `After the ${nn.n} past days most like today, the next month moved ${nn.ratio.toFixed(2)}× what options priced, against ${b.ratio.toFixed(2)}× on an ordinary day: options have tended to under-price what followed states like this.`
    : v === "lower" ? `After the ${nn.n} past days most like today, the next month moved ${nn.ratio.toFixed(2)}× what options priced, against ${b.ratio.toFixed(2)}× on an ordinary day: options have tended to over-price what followed.`
    : `After the ${nn.n} past days most like today, the next month moved ${nn.ratio.toFixed(2)}× what options priced: no different from an ordinary day (${b.ratio.toFixed(2)}×) within the uncertainty.`;
  const split = nn && nn.before_2024 && nn.from_2024 ? ((nn.before_2024.ratio - b.ratio) * (nn.from_2024.ratio - b.ratio) > 0 ? " It points the same way before and after 2024." : " It does not hold the same way before and after 2024: treat it as weak.") : "";
  return card({ title: "Days like today", hint: `what followed, over the next ${L.horizon} sessions`, cls: "span2",
    simple: `Today ${u.symbol}'s options are ${ivw}, priced ${pw}, with ${cw}. ${say}${split}`,
    analyst: `Realised vol of the next ${L.horizon} sessions as a share of the 30-day IV that day (1.00× = priced exactly), and how often the price ended inside the IV's one-sigma range (fairly priced: about 68%). Ranges are 90% moving-block bootstrap intervals (21-session blocks). Nearest neighbours: the 40 past days closest to today on IV rank, premium, curve slope, skew rank and last week's vol against the last quarter's, at most one per 10 sessions. With 27 instruments and two methods, some "different" readings are chance: weight one that holds in both halves. Descriptive, never a signal.`,
    body: `<div class="tbl-wrap"><table class="tbl"><thead><tr><th>Days</th><th>How many</th><th>Moved / priced</th><th>Ended inside ±1 IV move</th><th>Before 2024</th><th>From 2024</th></tr></thead><tbody>
      ${row("Every day (the baseline)", b)}${row("Same state as today", L.same_bucket)}${row("40 nearest days", nn)}</tbody></table></div>
      ${(L.neighbour_days || []).length ? `<div class="muted small" style="margin-top:8px">Nearest days: ${L.neighbour_days.slice(0, 12).join(", ")}${L.neighbour_days.length > 12 ? "…" : ""}</div>` : ""}` });
}

// ---- the expiry in front (engine/expiry.py) ----
function expiryCards(d, u) {
  const x = d.expiry;
  if (!x) return "";
  const away = (v) => (fin(v) ? ` (${vp(v / x.spot - 1, 1)}%)` : "");
  const st = x.study;
  const tiles = `<div class="grid g4" style="margin-bottom:10px">
    ${[["Expiry", `${x.expiry}`, `${x.days} day${x.days === 1 ? "" : "s"} to go`], ["Max pain", num(x.max_pain), `the least payout to option buyers${away(x.max_pain)}`],
       ["Biggest call strike", num(x.call_wall), `within 10% of the price${away(x.call_wall)}`], ["Biggest put strike", num(x.put_wall), `within 10% of the price${away(x.put_wall)}`]]
      .map(([l, v, f]) => `<section class="card kpi"><div class="lab"><span>${l}</span></div><div class="val num" style="font-size:20px">${v}</div><div class="foot">${f}</div></section>`).join("")}</div>`;
  let pin = "";
  if (st) {
    const verdict = st.p < 0.05 ? `more often than chance (p = ${st.p.toFixed(3)} for one instrument; with many instruments tested, treat a single p near 0.05 with care)`
      : st.share < 0.5 && st.p_two < 0.05 ? `less often than a coin toss (two-sided p = ${st.p_two.toFixed(3)}): the price tended to move away from it`
      : `about as often as a coin toss would (p = ${st.p.toFixed(2)}): no pull towards it shows`;
    pin = card({ title: "Does max pain pull the price?", hint: `${num(st.n)} expiries since ${st.since}`, cls: "span2",
      simple: `From the close before each expiry, the settlement landed closer to max pain than to the mirror point the same distance on the other side ${pct(st.share, 0)} of the time, ${verdict}.`,
      analyst: `Max pain from the open interest at the close before expiry; median distance from the price ${pct(st.median_gap, 2)}. Expiries with max pain within 0.1% of the price are not counted (no direction to test). On expiry day itself the price stayed inside the one-day straddle priced the evening before ${pct(st.inside, 0)} of the time (${num(st.n_priced)} expiries; a fairly priced straddle gives about 57%).`,
      body: `<div class="tbl-wrap"><table class="tbl"><thead><tr><th>Expiry</th><th>Close before</th><th>Max pain</th><th>Settled</th><th>Closer to max pain?</th><th>Move</th><th>Priced</th></tr></thead><tbody>
        ${st.recent.slice().reverse().map((r) => `<tr><td class="num">${r.expiry}</td><td class="num">${num(r.close_before, 1)}</td><td class="num">${num(r.max_pain)}</td><td class="num">${num(r.settle, 1)}</td>
          <td>${r.closer === null ? `<span class="muted small">not counted</span>` : r.closer ? "yes" : "no"}</td><td class="num">${pct(r.move, 2)}</td><td class="num">${fin(r.priced) ? "±" + pct(r.priced, 2) : "—"}</td></tr>`).join("")}</tbody></table></div>` });
  }
  const pay = x.payout && x.payout.strike.length ? card({ title: "What option buyers collect at each settlement", hint: `${x.expiry} · every open call and put`,
      simple: `If ${u.symbol} settled at each level, this is what all the open options of the expiry would pay their buyers. The lowest point is max pain${fin(x.max_pain) ? ` (${num(x.max_pain)})` : ""}.`,
      body: `<div class="chart" id="xpay"></div>` }) : "";
  const dec = x.decay && x.decay.date.length > 1 ? card({ title: "How the straddle is decaying", hint: `${x.expiry} · at-the-money call + put`,
      simple: "The at-the-money straddle at each close against the path a steady market would give (shrinking with the square root of the time left). Above the line, options held their value: the market got more nervous or moved.",
      body: `<div class="chart" id="xdec"></div><div class="legend"><span style="--c:${theme().s1}">Straddle</span><span style="--c:${theme().s3}">√time path from the first reading</span></div>` }) : "";
  return `<div class="span2">${card({ title: "The expiry in front", hint: x.expiry, body: tiles, cls: "flat" })}</div>${pay}${dec}${pin}`;
}
function expiryCharts(d) {
  const x = d.expiry, t = theme();
  if (!x) return;
  if ($("#xpay")) {
    const p = x.payout;
    chart("#xpay", { tooltip: { trigger: "axis", backgroundColor: t.surface, borderColor: t.line, textStyle: { color: t.text }, formatter: (ps) => `settles at ${num(p.strike[ps[0].dataIndex])}<br>buyers collect ₹${num(p.payout[ps[0].dataIndex], 0)} cr` },
      xAxis: { type: "category", data: p.strike.map((k) => num(k)), axisLabel: { color: t.text3, fontSize: 10 }, axisLine: { lineStyle: { color: t.line } } }, yAxis: axisY(t, (v) => num(v), { scale: false }),
      series: [{ name: "Payout", type: "bar", data: p.strike.map((k, i) => ({ value: p.payout[i], itemStyle: { color: k === x.max_pain ? t.s4 : t.s1, opacity: k === x.max_pain ? 1 : .7 } })), barCategoryGap: "30%",
        markLine: { silent: true, symbol: "none", lineStyle: { color: t.text, type: "dashed" }, label: { formatter: `price ${num(x.spot)}`, color: t.text2 },
          data: [{ xAxis: p.strike.reduce((bi, k, i) => Math.abs(k - x.spot) < Math.abs(p.strike[bi] - x.spot) ? i : bi, 0) }] } }] });
  }
  if ($("#xdec")) {
    const c = x.decay;
    chart("#xdec", { tooltip: { trigger: "axis", valueFormatter: (v) => num(v, 1), backgroundColor: t.surface, borderColor: t.line, textStyle: { color: t.text } },
      xAxis: axisX(c.date, t), yAxis: axisY(t, (v) => num(v)),
      series: [line("Straddle", c.straddle, t.s1, { showSymbol: true }), line("√time path", c.sqrt_t, t.s3, { lineStyle: { width: 1.5, type: "dashed", color: t.s3 } })] });
  }
}

function futMonthsCard(d) {
  const m = d.fut_months || [];
  if (!m.length) return "";
  const p = (x) => num(x, x > 1000 ? 1 : 2);
  const sp = m.slice(1).map((x, i) => `${m[i].series.replace(" month", "")} → ${x.series.replace(" month", "")} ${num(x.fut - m[i].fut, x.fut > 1000 ? 1 : 2)}`).join(" · ");
  return card({ title: "Futures by month", hint: `current, near and far contracts · ${d.meta.asof}`, cls: "span2",
    simple: `Each listed futures month side by side. Most positions sit in the ${m[0].series} (${pct(m[0].oi_share, 0)} of futures OI); the later months show where traders are rolling and what carrying a position costs further out.`,
    analyst: `Calendar spreads (later minus earlier future): ${sp || "—"}. Carry is annualised from the settlement price against the spot close and shown only 20+ days out (a short basis annualised is noise). OI and price change compare the same contract with the session before.`,
    body: `<div class="tbl-wrap"><table class="tbl"><thead><tr><th>Contract</th><th>Expiry</th><th>Days</th><th>Future</th><th>Day</th><th>Basis</th><th>Carry</th><th>Open interest</th><th>Share</th><th>OI change</th><th>Contracts</th></tr></thead><tbody>
      ${m.map((x) => `<tr><td>${x.series}</td><td class="num">${x.expiry}</td><td class="num">${x.days}</td><td class="num">${p(x.fut)}</td>
        <td class="num">${fin(x.d_price) ? `<span class="chg ${x.d_price >= 0 ? "pos" : "neg"}">${vp(x.d_price, 2)}%</span>` : "—"}</td>
        <td class="num">${fin(x.basis) ? num(x.basis, 1) : "—"}</td><td class="num">${fin(x.carry) ? pct(x.carry) : "—"}</td>
        <td class="num">${big(x.oi)}</td><td class="num">${pct(x.oi_share, 0)}</td><td class="num">${fin(x.d_oi) ? vp(x.d_oi, 1) + "%" : "—"}</td><td class="num">${big(x.contracts)}</td></tr>`).join("")}</tbody></table></div>` });
}

function symFutures(el, d, u) {
  const t = theme(), c = d.cards;
  const s = slice(d.series, ["carry", "fut_oi", "close", "basis", "roll_share"]);
  const fr = d.futures || [];
  const buCol = { "Long build-up": "--s1", "Short build-up": "--s2", "Short covering": "--s3", "Long unwinding": "--s4", "Corporate action": "--text-3", "Thin market": "--text-3" };
  el.innerHTML = `
    <div class="grid g2">
      ${futMonthsCard(d)}
      ${card({ title: "Futures premium (annualised carry)", simple: c.futures?.simple, analyst: c.futures?.analyst, body: `<div class="chart" id="carry"></div>` })}
      ${rollCard(d, u)}
      ${card({ title: "Futures open interest", cls: d.curve && fin(d.curve.cal_carry) ? "span2" : "", hint: "all months, OI units (shares or index quantity)", simple: "How many futures positions are open across all months. It drops at each monthly expiry when the near month settles.", body: `<div class="chart" id="foi"></div>` })}
      ${card({ title: "Last 30 sessions: what positions did", hint: "price change × OI change", cls: "span2", simple: "Each day classified by what happened to price and open positions together. Labels describe position changes; they do not predict.",
        body: `<div class="tbl-wrap"><table class="tbl"><thead><tr><th>Date</th><th>Future</th><th>Day</th><th>OI change</th><th>Open interest</th><th>Basis</th><th>Carry</th><th>Read</th></tr></thead><tbody>
        ${fr.slice().reverse().map((r) => `<tr><td class="num">${r.date}</td><td class="num">${num(r.fut, r.fut > 1000 ? 1 : 2)}</td><td class="num"><span class="chg ${r.d_price >= 0 ? "pos" : "neg"}">${vp(r.d_price, 2)}%</span></td>
          <td class="num">${fin(r.d_oi) ? vp(r.d_oi, 1) + "%" : "—"}</td><td class="num">${big(r.fut_oi)}</td><td class="num">${num(r.basis, 1)}</td><td class="num">${pct(r.carry)}</td>
          <td><span class="bu" style="${buCol[r.buildup] ? `box-shadow: inset 3px 0 0 ${css(buCol[r.buildup])}` : ""}">${r.buildup}</span></td></tr>`).join("")}</tbody></table></div>` })}
      ${card({ title: "Rollover at each expiry", hint: "share of OI already in next month, day before expiry", cls: "span2", simple: "How much of the position was carried into the next month. A high roll means traders kept their bets on; a low roll means they closed out.", body: `<div class="chart" id="roll"></div>` })}
    </div>`;
  const tip = (f) => ({ trigger: "axis", valueFormatter: f, backgroundColor: t.surface, borderColor: t.line, textStyle: { color: t.text } });
  chart("#carry", { tooltip: tip((v) => pct(v, 1)), xAxis: axisX(s.d, t), yAxis: axisY(t, fmtPct(0)),
    series: [line("Carry", s.carry.map((v) => fin(v) && Math.abs(v) < 1 ? v : null), t.s1, { markLine: (() => { const v = s.carry.slice(-252).filter((x) => fin(x) && Math.abs(x) < 1).sort((a, b) => a - b);
      return v.length > 20 ? { silent: true, symbol: "none", data: [{ yAxis: v[Math.floor(v.length / 2)], label: { formatter: `1-year median ${pct(v[Math.floor(v.length / 2)])}`, color: t.text3 } }], lineStyle: { color: t.text3, type: "dashed" } } : undefined; })() })] });
  rollChart(d);
  chart("#foi", { tooltip: tip(big), xAxis: axisX(s.d, t), yAxis: axisY(t, big), series: [line("Futures OI", s.fut_oi, t.s7, { areaStyle: { color: t.s7, opacity: .08 } })] });
  // futures are listed monthly for every underlying: no expiry-regime marks here
  const rl = d.rolls || [];
  chart("#roll", { tooltip: tip((v) => pct(v, 0)), xAxis: { type: "category", data: rl.map((r) => r.expiry), axisLabel: { color: t.text3, fontSize: 10 }, axisLine: { lineStyle: { color: t.line } } }, yAxis: axisY(t, fmtPct(0), { min: 0, max: 1, scale: false }),
    series: [{ name: "Rolled", type: "bar", data: rl.map((r) => r.roll_share), itemStyle: { color: t.s1, borderRadius: [4, 4, 0, 0] }, barWidth: "55%" }] });
}

function symEvents(el, d, u) {
  const t = theme();
  const res = d.results || [];
  el.innerHTML = `<div class="grid g2">
    ${u.kind === "stock" ? card({ title: "Results", hint: "from NSE's event calendar", cls: "span2", simple: "For past results: the move options priced for the results day, and what the stock actually did on that day and the next. For upcoming ones: what the curve prices now.",
      body: res.length ? `<div class="tbl-wrap"><table class="tbl"><thead><tr><th>Date</th><th>Agenda</th><th>Status</th><th>Priced event move</th><th>Results day</th><th>Next day</th><th>Front IV change</th></tr></thead><tbody>
      ${res.map((r) => `<tr><td class="num">${r.date}</td><td>${esc(r.purpose)}</td><td>${r.upcoming ? `<span class="chip elevated">upcoming</span>` : `<span class="chip">done</span>`}</td>
        <td class="num">${fin(r.implied_event_move) ? "±" + pct(r.implied_event_move, 1) : "not separable"}</td>
        <td class="num">${fin(r.move_day0) ? `<span class="chg ${r.move_day0 >= 0 ? "pos" : "neg"}">${vp(r.move_day0, 1)}%</span>` : "—"}</td>
        <td class="num">${fin(r.move_day1) ? `<span class="chg ${r.move_day1 >= 0 ? "pos" : "neg"}">${vp(r.move_day1, 1)}%</span>` : "—"}</td>
        <td class="num">${fin(r.iv_change) ? vp(r.iv_change) + " pts" : "—"}</td></tr>`).join("")}</tbody></table></div>` : `<div class="muted">No results dates in the calendar window.</div>`,
      analyst: "Priced event move: the extra variance in the expiry holding the results over the forward variance to the next expiry, as a one-day move, read at the last close before the results date. 'Not separable' means the curve showed no distinct event. The calendar does not say whether results came in market hours or after the close, so both the results-day and next-day moves are shown. Front IV change: close of the next day minus the last close before." }) : ""}
    ${d.macro?.length ? card({ title: "How it moves on big macro days", hint: "median absolute move, since " + d.meta.since, simple: "On days like these, this index has typically moved this many times its normal amount.",
      body: `<div class="chart" id="macro"></div>`, analyst: "Days from the macro calendar (RBI policy, Union Budget, US Fed, election results...). Descriptive: a small sample per kind, overlapping with other news." }) : ""}
    ${card({ title: "Biggest one-day moves on record", hint: "since " + d.meta.since, body: `<div class="tbl-wrap"><table class="tbl"><tbody>${d.big_days.map((b) => `<tr><td class="num">${b.date}</td><td class="num"><span class="chg ${b.ret >= 0 ? "pos" : "neg"}">${vp(Math.expm1(b.ret), 1)}%</span></td></tr>`).join("")}</tbody></table></div>`,
      analyst: [d.meta.splits?.length ? `Splits and bonuses removed from the price history: ${d.meta.splits.map((x) => `${x.date} (×${x.ratio})`).join(", ")}.` : "",
        d.meta.actions?.length ? `Other corporate actions (demergers and similar, where the exchange rebuilt the option strikes): ${d.meta.actions.map((x) => `${x.date} (${vp(x.adjusted, 1)}% taken out of the history; the 25 sessions of option prices before it are left out of the vol history)`).join(", ")}.` : ""].filter(Boolean).join(" ") })}
  </div>`;
  if (d.macro?.length) {
    const mm = d.macro;
    chart("#macro", { grid: { left: 150, right: 30, top: 10, bottom: 24 }, tooltip: { trigger: "axis", axisPointer: { type: "shadow" }, backgroundColor: t.surface, borderColor: t.line, textStyle: { color: t.text },
        formatter: (ps) => { const x = mm[ps[0].dataIndex]; return `<b>${x.label}</b> (${x.n} days)<br>median move ${pct(x.median_move, 2)} vs ${pct(x.normal_median, 2)} normally<br>biggest ${pct(x.max_move, 1)}`; } },
      yAxis: { type: "category", data: mm.map((x) => x.label), axisLabel: { color: t.text2, fontSize: 11 }, axisLine: { lineStyle: { color: t.line } }, axisTick: { show: false }, inverse: true },
      xAxis: { type: "value", axisLabel: { color: t.text3, formatter: (v) => v.toFixed(1) + "×" }, splitLine: { lineStyle: { color: t.line2 } } },
      series: [{ type: "bar", data: mm.map((x) => x.ratio), itemStyle: { color: t.s1, borderRadius: [0, 4, 4, 0] }, barWidth: "55%", label: { show: true, position: "right", color: t.text2, formatter: (p) => p.value.toFixed(1) + "×" },
        markLine: { silent: true, symbol: "none", data: [{ xAxis: 1 }], lineStyle: { color: t.text3, type: "dashed" }, label: { formatter: "normal day", color: t.text3 } } }] });
  }
}

// ---------------------------------------------------------------- router
async function route(opts = {}) {
  disposeCharts();
  if (!opts.soft) document.body.classList.remove("nav-open");
  const app = $("#app");
  let ov;
  try { ov = await overview(); } catch (e) { app.innerHTML = `<div class="loading">Could not load data (${esc(e.message)}).</div>`; return; }
  if (!route.ready) { setupShell(ov); route.ready = true; }
  const parts = (location.hash.replace(/^#\/?/, "") || "pulse").split("/");
  renderNav(ov, "#/" + parts.slice(0, 2).join("/"));
  if (!opts.soft) window.scrollTo(0, 0);
  try {
    if (parts[0] === "sym") await pageSymbol(app, ov, parts[1], parts[2]);
    else if (parts[0] === "screener") await pageScreener(app, ov);
    else if (parts[0] === "positioning") await pagePositioning(app, ov);
    else if (parts[0] === "flows") await pageFlows(app, ov);
    else if (parts[0] === "breadth") await pageBreadth(app, ov);
    else if (parts[0] === "commodities") await pageCommodities(app, ov);
    else if (parts[0] === "alerts") await pageAlerts(app, ov);
    else if (parts[0] === "health") await pageHealth(app, ov);
    else if (parts[0] === "compare") await pageCompare(app, ov, parts[1], parts[2]);
    else if (parts[0] === "calendar") await pageCalendar(app, ov);
    else if (parts[0] === "method") await pageMethod(app, ov);
    else await pagePulse(app, ov);
  } catch (e) { console.error(e); app.innerHTML = `<div class="loading">Something went wrong drawing this page: ${esc(e.message)}</div>`; }
}
// the live panels sit in one container the live layer refreshes on its own every few seconds, without redrawing the page
function liveSlot(ctx) {
  window.MLLiveCtx = ctx;
  return `<div id="mlLive">${window.MLLive ? MLLive.render(ctx) : ""}</div>`;
}
// ---- CSV: a card's table, or its charts' series (x and every line or bar), as the page shows them ----
function cardCSV(cardEl) {
  const q = (v) => { const t = String(v ?? "").replace(/\s+/g, " ").trim(); return /[",\n]/.test(t) ? `"${t.replace(/"/g, '""')}"` : t; };
  const tbl = cardEl.querySelector("table");
  if (tbl) return [...tbl.querySelectorAll("tr")].map((tr) => [...tr.children].map((c) => q(c.innerText)).join(",")).join("\n");
  const out = [];
  cardEl.querySelectorAll(".chart").forEach((el) => {
    const c = S.charts.find((x) => x.getDom() === el);
    if (!c) return;
    const o = c.getOption(), xs = (o.xAxis && o.xAxis[0] && o.xAxis[0].data) || (o.yAxis && o.yAxis[0] && o.yAxis[0].data) || null;
    const ser = (o.series || []).filter((x) => Array.isArray(x.data) && !/lo$/.test(x.name || ""));
    if (!ser.length) return;
    const val = (v) => (v && typeof v === "object" && !Array.isArray(v) ? (Array.isArray(v.value) ? v.value[v.value.length - 1] : v.value) : Array.isArray(v) ? v[1] : v);
    const xOf = (v, i) => (xs ? xs[i] : Array.isArray(v) ? v[0] : v && Array.isArray(v.value) ? v.value[0] : i);
    const n = Math.max(...ser.map((x) => x.data.length));
    out.push(["x", ...ser.map((x) => q(x.name || "series"))].join(","));
    for (let i = 0; i < n; i++) out.push([q(xOf(ser[0].data[i], i)), ...ser.map((x) => q(val(x.data[i])))].join(","));
    out.push("");
  });
  return out.join("\n");
}
document.addEventListener("click", (e) => {
  const b = e.target.closest && e.target.closest("[data-csv]");
  if (!b) return;
  const txt = cardCSV(b.closest(".card"));
  if (!txt) return;
  const name = (location.hash.replace(/^#\/?/, "").replace(/\//g, "-") || "pulse") + "-" + b.dataset.csv.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") + ".csv";
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([txt], { type: "text/csv" }));
  a.download = name;
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
});

window.MLState = S;
window.MLRoute = route;
(function init() {
  const th = lsGet("ml.theme", ""); if (th) document.documentElement.dataset.theme = th;
  window.addEventListener("hashchange", () => route());
  route().then(() => { if (window.MLLive) window.MLLive.start(); });
  const pillEl = document.getElementById("livePill");
  if (pillEl) pillEl.onclick = () => (window.MLLive.state.mode === "nokey" ? window.MLLive.askKey() : window.MLLive.poll(true));
})();
