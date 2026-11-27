/* MarketLens live layer: polls the private live relay every 5 seconds during the session, reads every instrument
   with LiveCore (the same rules as the end-of-day engine) and redraws the page in place.

   What is live and what is not is always visible:
     - live panels carry a "LIVE" badge and the age of the data they were read from
     - everything else on the page is the audited end-of-day analysis, labelled "at last close"
     - every live change is measured against the SAME contract at the last close (front-expiry IV against that expiry's
       close, today's future against the same future's close), never against a different series
   Live prices are the owner's licensed feeds: they are read with the owner's key (the one the desk app keeps on this
   device, qd.livekey) from the same Worker that serves this page, and are never written anywhere. */
(function () {
  "use strict";
  const POLL_MS = 5000;             // the owner's cadence: every live number within 5 seconds, the relay's own update rate
                                    // (Kite pushes every 5 s, Kotak is polled every ~5 s): faster would show nothing new
  const MAX_AGE = 120;              // a quote older than this (seconds, by the relay's own clock) is not live
  const KEY = "qd.livekey";
  const L = { mode: "init", reads: {}, at: null, feedAge: null, timer: null, note: "", busy: false };
  const key = () => { try { return localStorage.getItem(KEY) || ""; } catch (e) { return ""; } };
  const today = () => LiveCore.istDate(Date.now());

  // ---- polling ----
  async function poll(force) {
    if (L.busy || (!force && document.hidden)) return;
    const k = key();
    if (!k) { L.mode = "nokey"; paint(); return; }
    L.busy = true;
    try {
      const r = await fetch("/live/snapshot", { headers: { Authorization: "Bearer " + k }, cache: "no-store" });
      if (r.status === 401) { try { localStorage.removeItem(KEY); } catch (e) {} L.mode = "nokey"; L.note = "That key was not accepted."; return paint(); }
      if (r.status === 503) { L.mode = "error"; L.note = "The live relay is switched off on the Worker."; return paint(); }
      if (!r.ok) { L.mode = "error"; L.note = "The live relay answered " + r.status + "."; return paint(); }
      const snap = await r.json();
      const ov = window.MLState && window.MLState.overview;
      const nifty = snap.quotes && snap.quotes.NIFTY;
      L.feedAge = nifty ? nifty.age_s : null;
      L.at = Date.now();
      if (!nifty || !(nifty.age_s <= MAX_AGE)) { L.mode = "closed"; L.reads = {}; return paint(); }
      L.mode = "live";
      const reads = {};
      for (const u of (ov ? ov.universe : [])) reads[u.symbol] = LiveCore.readUnderlying(snap.quotes, u.symbol, { nowMs: Date.now(), maxAge: MAX_AGE });
      const vix = snap.quotes.INDIAVIX;
      L.vix = vix && vix.age_s <= MAX_AGE ? { ltp: vix.ltp, chg: Number.isFinite(vix.chg) ? vix.chg / 100 : null } : null;
      L.reads = reads;
      paint(true);
    } catch (e) {
      L.mode = "error"; L.note = "Could not reach the live relay."; paint();
    } finally { L.busy = false; }
  }
  function start() {
    poll(true);
    clearInterval(L.timer);
    L.timer = setInterval(() => poll(false), POLL_MS);
    document.addEventListener("visibilitychange", () => { if (!document.hidden) poll(true); });
    setInterval(pill, 5000);               // the pill's "updated Ns ago" ticks between polls
  }

  // ---- redraw: the page in place, scroll kept ----
  let painted = null;
  function paint(data) {
    pill();
    if (L.mode !== painted) {                           // the state changed (open, closed, key): redraw the page once
      painted = L.mode;
      if (typeof window.MLRoute === "function") {
        const y = window.scrollY;
        window.MLRoute({ soft: true }).then(() => window.scrollTo(0, y));
      }
      return;
    }
    if (data) refresh();                                // same state, new data: only the live panels, in place
  }
  // every tick: rebuild just the live container and its charts, and the sidebar's live changes; the rest of the page,
  // its charts, scroll and selections stay as they are
  function refresh() {
    const ctx = window.MLLiveCtx, el = document.getElementById("mlLive");
    if (!ctx || !el) return;
    if (typeof S !== "undefined" && S.charts) {
      S.charts = S.charts.filter((c) => { if (el.contains(c.getDom())) { c.dispose(); return false; } return true; });
    }
    el.innerHTML = render(ctx);
    if (ctx.kind === "symbol") charts(ctx.tab, ctx.u);
    if (typeof renderNav === "function" && ctx.ov) renderNav(ctx.ov, "#/" + (location.hash.replace(/^#\/?/, "") || "pulse").split("/").slice(0, 2).join("/"));
  }
  function render(ctx) {
    return ctx.kind === "pulse" ? pulse(ctx.ov) : ctx.kind === "screener" ? screener(ctx.ov) : ctx.kind === "symbol" ? symbol(ctx.d, ctx.u, ctx.tab) : "";
  }
  function pill() {
    const el = document.getElementById("livePill");
    if (!el) return;
    const ago = L.at ? Math.round((Date.now() - L.at) / 1000) : null;
    const txt = {
      live: `<span class="dot live"></span>LIVE · ${ago}s ago`, closed: `<span class="dot"></span>Market closed`,
      nokey: `<span class="dot"></span>Live: add key`, error: `<span class="dot err"></span>Live: offline`, init: `<span class="dot"></span>Live…`,
    }[L.mode] || "";
    el.innerHTML = txt;
    el.title = L.mode === "live" ? "Live data from your feeds, refreshed every 5 seconds while this page is open (about 100 MB an hour; paused when hidden)" : (L.note || "");
  }
  function askKey() {
    const k = prompt("Your live key (the LIVE_READ_TOKEN on the Worker). It stays on this device only.");
    if (k && k.trim().length >= 24) { try { localStorage.setItem(KEY, k.trim()); } catch (e) {} L.note = ""; poll(true); }
  }

  // ---- what the pages show ----
  const f = { pct: (x, d = 1) => (Number.isFinite(x) ? (x * 100).toFixed(d) + "%" : "—"),
              sgn: (x, d = 1) => (Number.isFinite(x) ? (x >= 0 ? "+" : "") + (x * 100).toFixed(d) : "—"),
              num: (x, d = 0) => (Number.isFinite(x) ? Number(x).toLocaleString("en-IN", { maximumFractionDigits: d, minimumFractionDigits: d }) : "—") };
  const badge = () => `<span class="chip live-chip"><span class="dot live"></span>LIVE · ${Math.round(L.feedAge || 0)}s</span>`;

  // the live read of one instrument against its close: front expiry IV vs the same expiry's close, the priced move,
  // a live percentile against the past year's front-expiry IV, today's futures read, OI added today
  function summary(sym) {
    const ov = window.MLState.overview, base = ov.live_base[sym], r = L.reads[sym];
    if (!base || !r) return null;
    const front = r.expiries.find((e) => e.ok);
    const closeIv = front ? (base.term.find((c) => c.expiry === front.expiry) || {}).iv : null;
    const fut = LiveCore.futuresToday(r, base.fut ? { fut: base.fut.fut, near_oi: base.fut.near_oi, fut_expiry: base.fut.fut_expiry } : null, today());
    const oiBase = front ? base.oi.find((p) => p.expiry === front.expiry) : null;
    const oi = front && oiBase ? LiveCore.oiVsClose(front, oiBase) : null;
    return {
      r, front, spot: r.spot, chg: r.spotChg,
      iv: front ? front.atm_iv : null, ivClose: closeIv ?? null, ivChg: front && Number.isFinite(closeIv) ? front.atm_iv - closeIv : null,
      ivPct: front ? LiveCore.pctVsHistory(front.atm_iv, base.iv_front) : null,
      move: front ? front.move : null, rr: front ? front.rr25 ?? null : null, fut, oi, base,
      why: front ? null : (r.expiries[0] && r.expiries[0].why) || (r.spot === null ? "no fresh quote" : "no live options"),
    };
  }

  function statusBlock() {
    if (L.mode === "live") return "";
    const msg = {
      closed: `Market closed: the live panels return at the 9:15 open. Everything below is the analysis at the last close.`,
      nokey: `Live mode needs your live key on this device. <a href="#" onclick="MLLive.askKey();return false"><b>Add it</b></a>: it stays on this device and is the same key the desk app uses.`,
      error: `Live data unavailable: ${L.note || "the relay did not answer"}. Showing the analysis at the last close.`,
      init: `Connecting to the live feed…`,
    }[L.mode] || "";
    return msg ? `<div class="callout" style="margin-bottom:16px">${msg}</div>` : "";
  }

  function pulse(ov) {
    if (L.mode !== "live") return statusBlock();
    const idx = ["NIFTY", "BANKNIFTY", "SENSEX", "FINNIFTY", "MIDCPNIFTY"];
    const tiles = idx.map((s) => {
      const x = summary(s);
      if (!x || x.spot === null) return "";
      return `<a class="card kpi live-tile" href="#/sym/${s}"><div class="lab"><span>${s}</span>${badge()}</div>
        <div class="val num">${f.num(x.spot, 1)} <small class="chg ${x.chg >= 0 ? "pos" : "neg"}">${f.sgn(x.chg, 2)}%</small></div>
        <div class="foot">${x.front ? `IV ${f.pct(x.iv)} <span class="muted">(${f.sgn(x.ivChg)} vs close)</span> · move ±${f.pct(x.move)} to ${x.front.expiry.slice(5)}` : `<span class="muted">options: ${x.why}</span>`}</div></a>`;
    }).join("");
    const vix = L.vix ? `<div class="card kpi live-tile"><div class="lab"><span>India VIX</span>${badge()}</div><div class="val num">${f.num(L.vix.ltp, 2)} <small class="chg ${L.vix.chg >= 0 ? "neg" : "pos"}">${f.sgn(L.vix.chg, 2)}%</small></div><div class="foot">≈ ${(L.vix.ltp / Math.sqrt(252)).toFixed(2)}% a day priced for NIFTY</div></div>` : "";
    // the session's biggest live changes, each against its own close
    const rows = ov.universe.map((u) => ({ u, x: summary(u.symbol) })).filter((o) => o.x && o.x.spot !== null);
    const ivMovers = rows.filter((o) => Number.isFinite(o.x.ivChg)).sort((a, b) => Math.abs(b.x.ivChg) - Math.abs(a.x.ivChg)).slice(0, 6);
    const futs = rows.filter((o) => o.x.fut && o.x.fut.label && Number.isFinite(o.x.fut.doi)).sort((a, b) => Math.abs(b.x.fut.doi) - Math.abs(a.x.fut.doi)).slice(0, 6);
    const list = (arr, fn) => arr.length ? `<ul class="story">${arr.map(fn).join("")}</ul>` : `<div class="muted small">Nothing yet this session.</div>`;
    return `<div class="grid g3" style="margin-bottom:16px">${vix}${tiles}</div>
      <div class="grid g2" style="margin-bottom:16px">
        ${card({ title: "Options repricing now", chip: badge(), hint: "front-expiry IV vs the same expiry's close",
          body: list(ivMovers, (o) => `<li><a href="#/sym/${o.u.slug}"><b>${o.u.symbol}</b></a> · IV ${f.pct(o.x.iv)} (${f.sgn(o.x.ivChg)} vol pts since close)${Number.isFinite(o.x.ivPct) ? ` · ${ord(o.x.ivPct)} pct of its past year` : ""}</li>`) })}
        ${card({ title: "Futures positioning today", chip: badge(), hint: "same contract vs its close",
          body: list(futs, (o) => `<li><a href="#/sym/${o.u.slug}"><b>${o.u.symbol}</b></a> · <span class="bu">${o.x.fut.label}</span> price ${f.sgn(o.x.fut.dp, 2)}%, OI ${f.sgn(o.x.fut.doi, 1)}%</li>`) })}
      </div>`;
  }

  function screener(ov) {
    if (L.mode !== "live") return statusBlock();
    const rows = ov.universe.map((u) => ({ u, x: summary(u.symbol) })).filter((o) => o.x);
    return `<div style="margin-bottom:16px">${card({ title: "Live board", chip: badge(), hint: "every instrument, refreshed every 5 seconds",
      simple: "Price and today's change from your feeds; implied vol of the front expiry against that same expiry's close; the move it prices; what futures positions did today.",
      body: `<div class="tbl-wrap"><table class="tbl"><thead><tr><th>Instrument</th><th>Price</th><th>Today</th><th>Front IV</th><th>vs close</th><th>IV pct 1y</th><th>Priced move</th><th>Futures today</th><th>OI today</th></tr></thead><tbody>
      ${rows.map(({ u, x }) => `<tr onclick="location.hash='#/sym/${u.slug}'" style="cursor:pointer"><td><span class="sym">${u.symbol}</span></td>
        <td class="num">${f.num(x.spot, x.spot > 1000 ? 0 : 2)}</td><td class="num"><span class="chg ${x.chg >= 0 ? "pos" : "neg"}">${f.sgn(x.chg, 2)}%</span></td>
        <td class="num">${x.front ? f.pct(x.iv) : `<span class="muted small">${x.why || "—"}</span>`}</td><td class="num">${f.sgn(x.ivChg)}</td><td class="num">${Number.isFinite(x.ivPct) ? ord(x.ivPct) : "—"}</td>
        <td class="num">${x.front ? `±${f.pct(x.move)} <span class="muted small">${x.front.expiry.slice(5)}</span>` : "—"}</td>
        <td>${x.fut && x.fut.label ? `<span class="bu">${x.fut.label}</span>` : x.fut && x.fut.why ? `<span class="muted small">${x.fut.why.slice(0, 40)}…</span>` : "—"}</td>
        <td class="num">${x.oi ? `C ${big(x.oi.call_add)} · P ${big(x.oi.put_add)}` : "—"}</td></tr>`).join("")}</tbody></table></div>` })}</div>`;
  }

  function symbol(d, u, tab) {
    if (L.mode !== "live") return statusBlock();
    const x = summary(u.symbol);
    if (!x || x.spot === null) return `<div class="callout" style="margin-bottom:16px">${badge()} No fresh live quote for ${u.symbol} right now.</div>`;
    const lo = x.front ? x.front.F * (1 - x.move) : null, hi = x.front ? x.front.F * (1 + x.move) : null;
    const head = `<div class="grid g4" style="margin-bottom:16px">
      ${kpiLive("Price now", f.num(x.spot, x.spot > 1000 ? 1 : 2), `<span class="chg ${x.chg >= 0 ? "pos" : "neg"}">${f.sgn(x.chg, 2)}%</span> today`)}
      ${kpiLive("Front-expiry IV", x.front ? f.pct(x.iv) : "—", x.front ? `${f.sgn(x.ivChg)} vol pts vs ${x.front.expiry} close${Number.isFinite(x.ivPct) ? ` · ${ord(x.ivPct)} pct (1y)` : ""}` : `not read: ${x.why}`)}
      ${kpiLive("Priced move", x.front ? "±" + f.pct(x.move) : "—", x.front ? `${f.num(lo)} – ${f.num(hi)} to ${x.front.expiry}` : "")}
      ${kpiLive("Futures today", x.fut && x.fut.label ? x.fut.label : "—", x.fut && x.fut.label ? `price ${f.sgn(x.fut.dp, 2)}%, OI ${Number.isFinite(x.fut.doi) ? f.sgn(x.fut.doi, 1) + "%" : "—"}${Number.isFinite(x.fut.basis) ? ` · basis ${f.num(x.fut.basis, 1)}` : ""}` : (x.fut && x.fut.why) || "no live future")}
    </div>`;
    if (tab === "oi") return head + liveOi(x, u);
    if (tab === "vol" && x.front) return head + `<div style="margin-bottom:16px">${card({ title: "Live smile", chip: badge(), hint: `${x.front.expiry} · liquid traded strikes`, body: `<div class="chart" id="liveSmile"></div>`,
      analyst: `Forward ${f.num(x.front.F, 1)} from put-call parity at ${f.num(x.front.atm_strike)}; ATM IV ${f.pct(x.iv, 2)} (straddle's own vol ${f.pct(x.front.straddle_iv, 2)}); 25-delta risk reversal ${Number.isFinite(x.rr) ? f.sgn(x.rr, 2) + " vol pts" : "not covered by the live strikes"}.` })}</div>`;
    return head;
  }
  function kpiLive(label, value, foot) {
    return `<section class="card kpi"><div class="lab"><span>${label}</span>${badge()}</div><div class="val num" style="font-size:22px">${value}</div><div class="foot">${foot}</div></section>`;
  }
  function liveOi(x, u) {
    if (!x.oi) return `<div class="callout" style="margin-bottom:16px">No live open interest to compare with the close for ${u.symbol}'s front expiry.</div>`;
    const rows = x.oi.rows;
    return `<div style="margin-bottom:16px">${card({ title: "Open interest added today, by strike", chip: badge(), hint: `${x.front.expiry} · vs the last close`,
      simple: `Since the close, calls ${x.oi.call_add >= 0 ? "added" : "shed"} ${big(Math.abs(x.oi.call_add))} and puts ${x.oi.put_add >= 0 ? "added" : "shed"} ${big(Math.abs(x.oi.put_add))} (OI units) on these strikes. Put/call ratio on them: ${Number.isFinite(x.oi.pcr_live) ? x.oi.pcr_live.toFixed(2) : "—"} now, ${Number.isFinite(x.oi.pcr_close) ? x.oi.pcr_close.toFixed(2) : "—"} at the close.`,
      body: `<div class="chart tall" id="liveOi" style="height:${Math.max(280, rows.length * 16)}px"></div><div class="legend"><span style="--c:${css("--s1")}">Calls added</span><span style="--c:${css("--s2")}">Puts added</span></div>` })}</div>`;
  }
  // charts for the live panels, drawn after the page's HTML is in place
  function charts(tab, u) {
    if (L.mode !== "live") return;
    const x = summary(u.symbol), t = theme();
    if (tab === "oi" && x && x.oi && document.getElementById("liveOi")) {
      const rows = x.oi.rows;
      chart("#liveOi", { grid: { left: 64, right: 24, top: 10, bottom: 30 }, tooltip: { trigger: "axis", axisPointer: { type: "shadow" }, backgroundColor: t.surface, borderColor: t.line, textStyle: { color: t.text },
          formatter: (ps) => { const r = rows[ps[0].dataIndex]; return `<b>${f.num(r.K)}</b><br>calls ${big(r.call_oi)} (${r.call_chg >= 0 ? "+" : ""}${big(r.call_chg)} today)<br>puts ${big(r.put_oi)} (${r.put_chg >= 0 ? "+" : ""}${big(r.put_chg)} today)`; } },
        yAxis: { type: "category", data: rows.map((r) => f.num(r.K)), axisLabel: { color: t.text3, fontSize: 10 } },
        xAxis: { type: "value", axisLabel: { color: t.text3, formatter: (v) => big(v) }, splitLine: { lineStyle: { color: t.line2 } } },
        series: [{ name: "Calls added", type: "bar", data: rows.map((r) => r.call_chg), itemStyle: { color: t.s1 } }, { name: "Puts added", type: "bar", data: rows.map((r) => r.put_chg), itemStyle: { color: t.s2 } }] });
    }
    if (tab === "vol" && x && x.front && document.getElementById("liveSmile")) {
      const sm = x.front.smile.filter((p) => Math.abs(p[0] / x.front.F - 1) <= 0.15);
      chart("#liveSmile", { tooltip: { trigger: "axis", valueFormatter: (v) => f.pct(v, 2), backgroundColor: t.surface, borderColor: t.line, textStyle: { color: t.text } },
        xAxis: { type: "value", scale: true, axisLabel: { color: t.text3, formatter: (v) => f.num(v) }, splitLine: { show: false } }, yAxis: axisY(t, fmtPct(0)),
        series: [line("IV now", sm, t.s1, { showSymbol: true })] });
    }
  }

  window.MLLive = { start, poll, askKey, pulse, screener, symbol, charts, render, state: L };
})();
