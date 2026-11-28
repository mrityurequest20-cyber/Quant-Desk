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
  const OPT_MAX_AGE = 480;          // an option chain may be this old: on Kotak alone each stock chain comes round about every 6 minutes;
                                    // an older one than MAX_AGE is shown with its age, never as if it were this second's
  const chainAge = (e) => (e && e.age > MAX_AGE ? ` · options ${Math.round(e.age / 60)} min old` : "");
  const KEY = "qd.livekey";
  const L = { mode: "init", reads: {}, at: null, feedAge: null, timer: null, note: "", busy: false, intra: {} };
  const INTRA_MS = 60000;           // the minute series change once a minute: fetched at most that often per contract
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
      mcxRead(snap.quotes || {});                       // MCX keeps its own clock: it trades to 23:30, after NSE closes
      const nifty = snap.quotes && snap.quotes.NIFTY;
      L.feedAge = nifty ? nifty.age_s : null;
      L.at = Date.now();
      if (!nifty || !(nifty.age_s <= MAX_AGE)) { L.mode = "closed"; L.reads = {}; return paint(); }
      L.mode = "live";
      const reads = {};
      for (const u of (ov ? ov.universe : [])) {
        const r = LiveCore.readUnderlying(snap.quotes, u.symbol, { nowMs: Date.now(), maxAge: MAX_AGE, optMaxAge: OPT_MAX_AGE }), base = ov.live_base[u.symbol];
        r.months = LiveCore.futuresMonths(snap.quotes, u.symbol, { nowMs: Date.now(), maxAge: MAX_AGE }, base ? base.fut_months : [], r.spot);
        reads[u.symbol] = r;
      }
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
    if (ctx.kind === "commodities") mcxCharts();
    if (typeof renderNav === "function" && ctx.ov) renderNav(ctx.ov, "#/" + (location.hash.replace(/^#\/?/, "") || "pulse").split("/").slice(0, 2).join("/"));
  }
  function render(ctx) {
    if (ctx.kind === "commodities") return mcxPanel(ctx);
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

  // ---- MCX: every watchlist commodity's future and option chain, read with LiveCore on the future ----
  const MCX = ["CRUDEOIL", "CRUDEOILM", "NATURALGAS", "NATGASMINI", "GOLD", "GOLDM", "SILVER", "SILVERM", "COPPER"];
  const MCX_OPEN = 9 * 60, MCX_CLOSE = 23 * 60 + 30;
  L.mcx = { at: null, reads: {}, live: false, sel: "CRUDEOIL" };
  function mcxRead(quotes) {
    const now = Date.now(), reads = {};
    for (const c of MCX) {
      const fq = quotes[c + "-MCX"];
      if (!fq) continue;
      const r = LiveCore.readUnderlying(quotes, c, { nowMs: now, maxAge: MAX_AGE, optMaxAge: OPT_MAX_AGE, futName: c + "-MCX", closeHHMM: "23:30" });
      const front = r.expiries.find((e) => e.ok) || null;
      const any = r.expiries[0] || null;
      const chain = front || any;
      reads[c] = { r, fut: fq, front, gamma: chain && r.spot ? LiveCore.gammaMap({ expiries: front ? [front] : [] }, r.spot, null, 0.08, 0.05) : null,
        maxPain: chain ? LiveCore.maxPain(chain.strikes, chain.by) : null, walls: front ? LiveCore.walls(front, r.spot) : null };
    }
    L.mcx.reads = reads;
    L.mcx.at = now;
    L.mcx.live = Object.values(reads).some((x) => x.fut && x.fut.age_s <= MAX_AGE);
    if (window.MLLiveCtx && window.MLLiveCtx.kind === "commodities") refresh();
  }
  function mcxPanel(ctx) {
    const C = (ctx.C && ctx.C.contracts) || {}, R = L.mcx.reads, ist = new Date(Date.now() + 19800000), mins = ist.getUTCHours() * 60 + ist.getUTCMinutes();
    if (L.mode === "nokey") return `<div class="callout">Live MCX panels need your live key on this device. <a href="#" onclick="MLLive.askKey();return false"><b>Add it</b></a>.</div>`;
    if (!Object.keys(R).length) return `<div class="callout">No MCX prices from the relay yet${L.mode === "error" ? `: ${L.note || "the relay did not answer"}` : ""}.</div>`;
    const open = ist.getUTCDay() >= 1 && ist.getUTCDay() <= 5 && mins >= MCX_OPEN && mins <= MCX_CLOSE;
    const rows = MCX.filter((c) => R[c]).map((c) => {
      const x = R[c], fq = x.fut, fr = x.front, par = C[c] && C[c].parity, fresh = fq.age_s <= MAX_AGE;
      const prem = fin(par) && fq.ltp > 0 ? fq.ltp / par - 1 : null;
      return `<tr class="${c === L.mcx.sel ? "hl" : ""}" style="cursor:pointer" onclick="MLLive.mcxSelect('${c}')"><td><b>${c}</b> <span class="muted small">${fq.e || ""}</span></td>
        <td class="num">${fq.ltp ? (fq.ltp > 1000 ? Math.round(fq.ltp).toLocaleString("en-IN") : fq.ltp.toFixed(2)) : "—"} <span class="muted small">${fresh ? "" : ago(fq.age_s)}</span></td>
        <td class="num">${Number.isFinite(fq.chg) ? `<span class="chg ${fq.chg >= 0 ? "pos" : "neg"}">${fq.chg >= 0 ? "+" : ""}${fq.chg.toFixed(2)}%</span>` : "—"}</td>
        <td class="num">${fr ? f.pct(fr.atm_iv) : `<span class="muted small">${(x.r.expiries[0] && x.r.expiries[0].why) || "no options in the feed"}</span>`}</td>
        <td class="num">${fr ? "±" + f.pct(fr.move) + ` <span class="muted small">${fr.expiry.slice(5)}</span>` : "—"}</td>
        <td class="num">${fr && Number.isFinite(fr.rr25) ? f.sgn(fr.rr25) + " pts" : "—"}</td>
        <td class="num">${x.maxPain !== null ? Math.round(x.maxPain).toLocaleString("en-IN") : "—"}</td>
        <td class="num">${prem !== null ? f.sgn(prem, 1) + "%" : "—"}</td></tr>`;
    }).join("");
    const sel = R[L.mcx.sel] || R[MCX.find((c) => R[c])], sf = sel && sel.front;
    return `${open || L.mcx.live ? "" : `<div class="callout" style="margin-bottom:12px">MCX is closed now (it trades 9:00–23:30 IST on weekdays): these are the last prices the relay holds, with their age.</div>`}
      <div class="grid g2">${card({ title: "MCX now", chip: L.mcx.live ? badgeMcx() : "", hint: "front option expiry · click a row for its smile and open interest", cls: "span2",
        simple: "Each commodity's future and its options read live: the at-the-money vol, the move the straddle prices to the option expiry, skew (call minus put vol at 25 delta), max pain, and the future's premium over import parity (the international benchmark in rupees at the last close).",
        analyst: "MCX options are options on the future, so the future stands in for the spot; time to expiry runs to the 23:30 close of the expiry day. The same reading rules as the index and stock pages (traded at-the-money pair, liquid strikes, the straddle and smile vols agreeing). Import parity is before duties, so a steady premium is normal; a change in it is the news.",
        body: `<div class="tbl-wrap"><table class="tbl"><thead><tr><th>Contract</th><th>Future</th><th>Day</th><th>ATM IV</th><th>Priced move</th><th>Skew 25d</th><th>Max pain</th><th>Over parity</th></tr></thead><tbody>${rows}</tbody></table></div>` })}
      ${sf ? card({ title: `${L.mcx.sel}: smile`, chip: badgeMcx(), hint: `${sf.expiry} · liquid traded strikes`, body: `<div class="chart" id="mcxSmile"></div>`,
        analyst: `Forward ${Math.round(sf.F).toLocaleString("en-IN")} from put-call parity at ${sf.atm_strike}; ATM IV ${f.pct(sf.atm_iv, 2)} (the straddle's own ${f.pct(sf.straddle_iv, 2)}).` }) : ""}
      ${sf ? card({ title: `${L.mcx.sel}: open interest and gamma`, chip: badgeMcx(), hint: "by strike, the strikes the feed carries", body: `<div class="chart" id="mcxOi"></div><div class="legend"><span style="--c:${css("--s1")}">Calls</span><span style="--c:${css("--s2")}">Puts</span></div>`,
        simple: sel.walls ? `The biggest pile of calls is at ${sel.walls.call_wall ? Math.round(sel.walls.call_wall).toLocaleString("en-IN") : "—"}, of puts at ${sel.walls.put_wall ? Math.round(sel.walls.put_wall).toLocaleString("en-IN") : "—"}; put/call ratio ${Number.isFinite(sel.walls.pcr) ? sel.walls.pcr.toFixed(2) : "—"}.` : "" }) : ""}</div>`;
  }
  const ago = (s) => (s < 120 ? Math.round(s) + "s" : s < 7200 ? Math.round(s / 60) + "m" : Math.round(s / 3600) + "h") + " old";
  const badgeMcx = () => `<span class="chip live-chip"><span class="dot live"></span>LIVE · ${L.mcx.at ? Math.round((Date.now() - L.mcx.at) / 1000) : "—"}s</span>`;
  function mcxSelect(c) { L.mcx.sel = c; if (window.MLLiveCtx && window.MLLiveCtx.kind === "commodities") refresh(); }
  function mcxCharts() {
    const x = L.mcx.reads[L.mcx.sel], t = theme();
    if (!x || !x.front) return;
    const fr = x.front;
    if (document.getElementById("mcxSmile")) chart("#mcxSmile", { tooltip: { trigger: "axis", valueFormatter: (v) => f.pct(v, 2), backgroundColor: t.surface, borderColor: t.line, textStyle: { color: t.text } },
      xAxis: { type: "value", scale: true, axisLabel: { color: t.text3, formatter: (v) => Math.round(v).toLocaleString("en-IN") }, splitLine: { show: false } }, yAxis: axisY(t, fmtPct(1)),
      series: [line("IV", fr.smile.map((p) => [p[0], p[1]]), t.s1, { showSymbol: true })] });
    if (document.getElementById("mcxOi")) {
      const K = fr.strikes, by = fr.by;
      chart("#mcxOi", { grid: { left: 64, right: 24, top: 10, bottom: 30 }, tooltip: { trigger: "axis", axisPointer: { type: "shadow" }, backgroundColor: t.surface, borderColor: t.line, textStyle: { color: t.text } },
        yAxis: { type: "category", data: K.map((k) => Math.round(k).toLocaleString("en-IN")), axisLabel: { color: t.text3, fontSize: 10 } },
        xAxis: { type: "value", axisLabel: { color: t.text3, formatter: (v) => big(Math.abs(v)) }, splitLine: { lineStyle: { color: t.line2 } } },
        series: [{ name: "Calls", type: "bar", stack: "x", data: K.map((k) => (by[k].CE ? by[k].CE.oi || 0 : 0)), itemStyle: { color: t.s1 } },
          { name: "Puts", type: "bar", stack: "x", data: K.map((k) => -(by[k].PE ? by[k].PE.oi || 0 : 0)), itemStyle: { color: t.s2 } }] });
    }
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
    const months = r.months || [];
    const gb = base.gamma, gSpot = r.spot || (r.fut && r.fut.ltp) || null;
    const gamma = gb && gSpot ? LiveCore.gammaMap(r, gSpot, gb.weights, base.kind === "index" ? 0.06 : 0.12, base.kind === "index" ? 0.05 : 0.10) : null;
    const oiBase = front ? base.oi.find((p) => p.expiry === front.expiry) : null;
    const oi = front && oiBase ? LiveCore.oiVsClose(front, oiBase) : null;
    return {
      r, front, spot: r.spot, chg: r.spotChg,
      iv: front ? front.atm_iv : null, ivClose: closeIv ?? null, ivChg: front && Number.isFinite(closeIv) ? front.atm_iv - closeIv : null,
      ivPct: front ? LiveCore.pctVsHistory(front.atm_iv, base.iv_front) : null,
      move: front ? front.move : null, rr: front ? front.rr25 ?? null : null, fut, months, gamma, oi, base,
      why: front ? null : (r.expiries[0] && r.expiries[0].why) || (r.spot === null ? "no fresh quote" : "no live options"),
      ...(() => {                                  // 30-day IV the end-of-day way, its percentile, and the premium over
        const cm = LiveCore.constantMaturity(r.expiries);       // realised vol (realised: at the last close)
        const vrp = cm.iv !== null && Number.isFinite(base.rv21) ? cm.iv - base.rv21 : null;
        return { iv30: cm.iv, iv30Why: cm.why || null, iv30Pct: LiveCore.pctVsHistory(cm.iv, base.iv30),
                 vrp, vrpPct: LiveCore.pctVsHistory(vrp, base.vrp),
                 carryPct: fut && Number.isFinite(fut.carry) ? LiveCore.pctVsHistory(fut.carry, base.carry) : null,
                 walls: front ? LiveCore.walls(front, r.spot) : null };
      })(),
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
        <div class="foot">${x.front ? `IV ${f.pct(x.iv)} <span class="muted">(${f.sgn(x.ivChg)} vs close)</span> · move ±${f.pct(x.move)} to ${x.front.expiry.slice(5)}${chainAge(x.front)}` : `<span class="muted">options: ${x.why}</span>`}</div></a>`;
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
      simple: "Price and today's change from your feeds; implied vol of the front expiry against that same expiry's close; 30-day IV the close-of-day way and its premium over realised vol, where the feed carries an expiry near 30 days; the move it prices; what futures positions and options OI did today.",
      body: `<div class="tbl-wrap"><table class="tbl"><thead><tr><th>Instrument</th><th>Price</th><th>Today</th><th>Front IV</th><th>vs close</th><th>IV pct 1y</th><th>30-day IV</th><th>Premium</th><th>Priced move</th><th>Futures today</th><th>OI today</th></tr></thead><tbody>
      ${rows.map(({ u, x }) => `<tr onclick="location.hash='#/sym/${u.slug}'" style="cursor:pointer"><td><span class="sym">${u.symbol}</span></td>
        <td class="num">${f.num(x.spot, x.spot > 1000 ? 0 : 2)}</td><td class="num"><span class="chg ${x.chg >= 0 ? "pos" : "neg"}">${f.sgn(x.chg, 2)}%</span></td>
        <td class="num">${x.front ? f.pct(x.iv) : `<span class="muted small">${x.why || "—"}</span>`}</td><td class="num">${f.sgn(x.ivChg)}</td><td class="num">${Number.isFinite(x.ivPct) ? ord(x.ivPct) : "—"}</td>
        <td class="num">${x.iv30 !== null ? f.pct(x.iv30) : "—"}</td><td class="num">${x.vrp !== null ? f.sgn(x.vrp) : "—"}</td>
        <td class="num">${x.front ? `±${f.pct(x.move)} <span class="muted small">${x.front.expiry.slice(5)}</span>` : "—"}</td>
        <td>${x.fut && x.fut.label ? `<span class="bu">${x.fut.label}</span>` : x.fut && x.fut.why ? `<span class="muted small">${x.fut.why.slice(0, 40)}…</span>` : "—"}</td>
        <td class="num">${x.oi ? `C ${big(x.oi.call_add)} · P ${big(x.oi.put_add)}` : "—"}</td></tr>`).join("")}</tbody></table></div>` })}</div>`;
  }

  function symbol(d, u, tab) {
    if (L.mode !== "live") return statusBlock();
    const x = summary(u.symbol);
    if (!x || x.spot === null) return `<div class="callout" style="margin-bottom:16px">${badge()} No fresh live quote for ${u.symbol} right now.</div>`;
    const lo = x.front ? x.front.F * (1 - x.move) : null, hi = x.front ? x.front.F * (1 + x.move) : null;
    const pctTxt = (p) => (Number.isFinite(p) ? ` · ${ord(p)} pct (1y)` : "");
    const head = `<div class="grid g3" style="margin-bottom:16px">
      ${kpiLive("Price now", f.num(x.spot, x.spot > 1000 ? 1 : 2), `<span class="chg ${x.chg >= 0 ? "pos" : "neg"}">${f.sgn(x.chg, 2)}%</span> today`)}
      ${kpiLive("Front-expiry IV", x.front ? f.pct(x.iv) : "—", x.front ? `${f.sgn(x.ivChg)} vol pts vs ${x.front.expiry} close${pctTxt(x.ivPct)}${chainAge(x.front)}` : `not read: ${x.why}`)}
      ${kpiLive("30-day IV", x.iv30 !== null ? f.pct(x.iv30) : "—", x.iv30 !== null ? `close-of-day method${pctTxt(x.iv30Pct)}` : `not read live: ${x.iv30Why}`)}
      ${kpiLive("Premium (IV − realised)", x.vrp !== null ? f.sgn(x.vrp) + " pts" : "—", x.vrp !== null ? `30-day IV now vs realised ${f.pct(x.base.rv21)} at the close${pctTxt(x.vrpPct)}` : "needs a live 30-day IV")}
      ${kpiLive("Priced move", x.front ? "±" + f.pct(x.move) : "—", x.front ? `${f.num(lo)} – ${f.num(hi)} to ${x.front.expiry}` : "")}
      ${kpiLive("Futures today", x.fut && x.fut.label ? x.fut.label : "—", x.fut && x.fut.label ? `price ${f.sgn(x.fut.dp, 2)}%, OI ${Number.isFinite(x.fut.doi) ? f.sgn(x.fut.doi, 1) + "%" : "—"}${Number.isFinite(x.fut.basis) ? ` · basis ${f.num(x.fut.basis, 1)}` : ""}${Number.isFinite(x.fut.carry) ? ` · carry ${f.pct(x.fut.carry)}` : ""}` : (x.fut && x.fut.why) || "no live future")}
    </div>`;
    const more = { vol: liveVol, move: liveMove, oi: liveOi, futures: liveFut }[tab];
    return head + (more ? more(x, u) : "");
  }
  function kpiLive(label, value, foot) {
    return `<section class="card kpi"><div class="lab"><span>${label}</span>${badge()}</div><div class="val num" style="font-size:22px">${value}</div><div class="foot">${foot}</div></section>`;
  }
  // ---- the day minute by minute: the at-the-money straddle of one contract, from the relay's minute series ----
  function intraContract(x, u) {
    const r = x.r, spot = r.spot || (r.fut && r.fut.ltp);
    const pick = (exp, strikes, by) => {
      const both = strikes.filter((k) => by[k] && by[k].CE && by[k].PE);
      if (!both.length || !spot) return null;
      const K = both.reduce((b, k) => (Math.abs(k - spot) < Math.abs(b - spot) ? k : b), both[0]);
      return { expiry: exp, K, today: exp === today() };
    };
    if (r.expiring) { const c = pick(r.expiring.expiry, r.expiring.strikes, r.expiring.by); if (c) return c; }
    return x.front ? pick(x.front.expiry, x.front.strikes, x.front.by) : null;
  }
  async function loadIntra(sym, c) {
    const id = `${sym}|${c.expiry}|${c.K}`, have = L.intra[sym];
    if (have && have.id === id && Date.now() - have.at < INTRA_MS) return have;
    const get = async (n) => {
      const res = await fetch("/live/series?name=" + encodeURIComponent(n), { headers: { Authorization: "Bearer " + key() }, cache: "no-store" });
      if (!res.ok) throw new Error(String(res.status));
      return (await res.json()).day || [];
    };
    try {
      const [ce, pe, ul] = await Promise.all([get(LiveCore.optName(sym, c.expiry, c.K, "CE")), get(LiveCore.optName(sym, c.expiry, c.K, "PE")), get(sym).catch(() => [])]);
      const m = (a) => a.map(([ms, px]) => [Math.floor(ms), px]);           // the relay's series are [epoch minute, close]
      L.intra[sym] = { id, at: Date.now(), c, data: LiveCore.intraday(m(ce), m(pe), c.K, c.expiry), spot: m(ul) };
    } catch (e) {
      L.intra[sym] = { id, at: Date.now(), c, data: null, err: "the relay has no minute series for it yet" };
    }
    return L.intra[sym];
  }
  function intraCard(x, u) {
    const c = intraContract(x, u);
    if (!c) return "";
    return card({ title: c.today ? "Expiry day, minute by minute" : "Today, minute by minute", chip: badge(), cls: "span2",
      hint: `${c.expiry} · strike ${f.num(c.K)} (nearest the price now) · straddle and the vol it implies`,
      simple: c.today ? `This contract settles at 15:30 today. The straddle shows the market pricing the rest of the day: it should melt towards zero unless the price is moving.` : "The at-the-money straddle through the session and the volatility it implies, minute by minute.",
      analyst: "Built from the relay's one-close-a-minute series of the call and the put (a minute is drawn only when both legs printed within 10 minutes of it). The forward is put-call parity at this strike; the vol is Black-76 on the out-of-the-money leg at that forward, with time to the 15:30 close measured in minutes.",
      body: `<div class="chart" id="liveIntra" style="height:280px"><div class="muted small" style="padding:20px">Loading the day's minutes…</div></div><div class="legend"><span style="--c:${css("--s1")}">Straddle</span><span style="--c:${css("--s7")}">Implied vol</span></div>` });
  }
  function drawIntra(sym) {
    const el = document.getElementById("liveIntra"), it = L.intra[sym];
    if (!el || !it) return;
    const t = theme(), d = it.data;
    if (!d || !d.minute.length) { el.innerHTML = `<div class="muted small" style="padding:20px">No minutes to draw yet: ${it.err || "the two legs have not both printed today"}.</div>`; return; }
    const hm = (m) => new Date(m * 60000).toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", hour12: false, timeZone: "Asia/Kolkata" });
    el.innerHTML = "";
    chart("#liveIntra", { grid: { left: 56, right: 56, top: 16, bottom: 30 }, tooltip: { trigger: "axis", backgroundColor: t.surface, borderColor: t.line, textStyle: { color: t.text },
        formatter: (ps) => { const i = ps[0].dataIndex; return `<b>${hm(d.minute[i])}</b><br>straddle ${f.num(d.straddle[i], 2)}<br>implied vol ${d.iv[i] === null ? "—" : f.pct(d.iv[i], 1)}<br>forward ${f.num(d.F[i], 1)}`; } },
      xAxis: { type: "category", data: d.minute.map(hm), axisLabel: { color: t.text3 }, axisLine: { lineStyle: { color: t.line } } },
      yAxis: [axisY(t, (v) => f.num(v)), axisY(t, (v) => (v * 100).toFixed(1) + "%", { position: "right", splitLine: { show: false } })],
      series: [line("Straddle", d.straddle, t.s1), line("Implied vol", d.iv, t.s7, { yAxisIndex: 1, lineStyle: { width: 1.5, color: t.s7 } })] });
  }

  // Volatility: the live term structure against the close's curve, and the live smile
  function liveVol(x, u) {
    if (!x.front) return "";
    return `<div class="grid g2" style="margin-bottom:16px">
      ${intraCard(x, u)}
      ${card({ title: "Term structure now", chip: badge(), hint: "ATM IV by expiry, live vs the last close", body: `<div class="chart" id="liveTerm"></div><div class="legend"><span style="--c:${css("--s1")}">Now</span><span style="--c:${css("--s2")}">Last close</span></div>`,
        analyst: "Live points are the expiries the feed carries that pass every end-of-day check; the close curve is every expiry at the last close." })}
      ${card({ title: "Live smile", chip: badge(), hint: `${x.front.expiry} · liquid traded strikes`, body: `<div class="chart" id="liveSmile"></div>`,
        analyst: `Forward ${f.num(x.front.F, 1)} from put-call parity at ${f.num(x.front.atm_strike)}; ATM IV ${f.pct(x.iv, 2)} (the straddle's own vol ${f.pct(x.front.straddle_iv, 2)}); 25-delta risk reversal ${Number.isFinite(x.rr) ? f.sgn(x.rr, 2) + " vol pts" : "not covered by the live strikes"}.` })}
    </div>`;
  }
  // Expected move: every live expiry, the end-of-day table's columns
  function liveMove(x, u) {
    const rows = x.r.expiries;
    if (!rows.length) return "";
    // the expiry in front, live: today's expiring contract on expiry day, else the front expiry
    const ex = x.r.expiring || (x.front ? { expiry: x.front.expiry, strikes: x.front.strikes, by: x.front.by } : null);
    const mp = ex ? LiveCore.maxPain(ex.strikes, ex.by) : null, close = x.base.expiry_mp || {};
    const spot = x.r.spot;
    const mpCard = mp !== null ? card({ title: ex.expiry === today() ? "Expiry today: max pain now" : "Max pain now", chip: badge(), hint: `${ex.expiry} · on the strikes the feed carries`,
      simple: `On live open interest the least payout to option buyers is at ${f.num(mp)}${spot ? ` (${f.sgn(mp / spot - 1, 1)}% from the price)` : ""}${close.expiry === ex.expiry && Number.isFinite(close.max_pain) ? `; at the last close it was ${f.num(close.max_pain)}` : ""}. The close-of-day study on the Expected move tab shows whether expiries have actually settled near it.`,
      analyst: "Only the strikes the live feed carries (about ±10 for indices) are counted, so a far-away pile of open interest outside them can move the close-of-day figure." }) : "";
    return `<div style="margin-bottom:16px">${mpCard ? `<div style="margin-bottom:16px">${mpCard}</div>` : ""}${card({ title: "Every live expiry", chip: badge(), hint: "straddle at the parity strike, as at the close",
      body: `<div class="tbl-wrap"><table class="tbl"><thead><tr><th>Expiry</th><th>Days</th><th>ATM IV</th><th>vs close</th><th>Straddle</th><th>Priced move</th><th>Range</th></tr></thead><tbody>
      ${rows.map((e) => { const c = x.base.term.find((t) => t.expiry === e.expiry); return e.ok ? `<tr><td class="num">${e.expiry}</td><td class="num">${e.days.toFixed(1)}</td><td class="num">${f.pct(e.atm_iv)}</td><td class="num">${c ? f.sgn(e.atm_iv - c.iv) : "—"}</td><td class="num">${f.num(e.straddle, 1)}</td><td class="num">±${f.pct(e.move, 2)}</td><td class="num">${f.num(e.F * (1 - e.move))} – ${f.num(e.F * (1 + e.move))}</td></tr>`
        : `<tr><td class="num">${e.expiry}</td><td class="num">${e.days.toFixed(1)}</td><td colspan="5" class="muted small" style="text-align:left">not read: ${e.why}</td></tr>`; }).join("")}</tbody></table></div>` })}</div>`;
  }
  // Options: open interest now by strike (with walls among the live strikes) and what was added today
  function liveOi(x, u) {
    if (!x.front) return `<div class="callout" style="margin-bottom:16px">No live options reading for ${u.symbol}: ${x.why}.</div>`;
    const w = x.walls, oi = x.oi;
    const lvl = card({ title: "Open interest now, by strike", chip: badge(), hint: `${x.front.expiry} · the live strikes ${f.num(w.lo)}–${f.num(w.hi)}`,
      simple: `Within the strikes the feed carries, the biggest pile of calls is at ${w.call_wall ? f.num(w.call_wall) : "—"} and of puts at ${w.put_wall ? f.num(w.put_wall) : "—"}. Put/call ratio on these strikes: ${Number.isFinite(w.pcr) ? w.pcr.toFixed(2) : "—"}.`,
      body: `<div class="chart tall" id="liveOiLvl" style="height:${Math.max(280, x.front.strikes.length * 15)}px"></div><div class="legend"><span style="--c:${css("--s1")}">Calls</span><span style="--c:${css("--s2")}">Puts</span></div>`,
      analyst: "Only the strikes in the live feed (about +-15 for indices, +-8 for stocks): a wall outside them shows in the close-of-day chart below." });
    const add = oi ? card({ title: "Open interest added today, by strike", chip: badge(), hint: `${x.front.expiry} · vs the last close`,
      simple: `Since the close, calls ${oi.call_add >= 0 ? "added" : "shed"} ${big(Math.abs(oi.call_add))} and puts ${oi.put_add >= 0 ? "added" : "shed"} ${big(Math.abs(oi.put_add))} (OI units) on these strikes. Put/call ratio on them: ${Number.isFinite(oi.pcr_live) ? oi.pcr_live.toFixed(2) : "—"} now, ${Number.isFinite(oi.pcr_close) ? oi.pcr_close.toFixed(2) : "—"} at the close.`,
      body: `<div class="chart tall" id="liveOi" style="height:${Math.max(280, oi.rows.length * 15)}px"></div><div class="legend"><span style="--c:${css("--s1")}">Calls added</span><span style="--c:${css("--s2")}">Puts added</span></div>` })
      : card({ title: "Open interest added today", chip: badge(), simple: "The last close has no strike profile for this expiry to compare with." });
    const g = x.gamma, gb = x.base.gamma || {};
    const gcard = g && g.strikes.length ? card({ title: "Gamma now, by strike", chip: badge(), hint: "Rs crore of hedging per 1% move · the live strikes", cls: "span2",
      simple: Number.isFinite(g.net_total)
        ? `The hedgers' net gamma is ${g.net_total >= 0 ? "long" : "short"} at ${f.num(g.net_total)} crore per 1% (${Number.isFinite(gb.net_total) ? f.num(gb.net_total) + " at the close" : "no close figure"}). ${Number.isFinite(g.flip) ? `It flips at about ${f.num(g.flip)}${Number.isFinite(gb.flip) ? ` (${f.num(gb.flip)} at the close)` : ""}.` : "No flip within ±5%."}`
        : `Call gamma ${f.num(g.call_total)} and put gamma ${f.num(g.put_total)} crore per 1% on the strikes the feed carries.`,
      analyst: "The close-of-day map reads every listed strike; live reads only the strikes the feed carries (about ±10 for indices, ±3 to ±8 for stocks), so live totals run lower. The hedgers' weights are the last participant file's.",
      body: `<div class="chart" id="liveGamma" style="height:${Math.max(260, g.strikes.length * 14)}px"></div><div class="legend"><span style="--c:${css("--s1")}">Call gamma</span><span style="--c:${css("--s2")}">Put gamma</span></div>` }) : "";
    return `<div class="grid g2" style="margin-bottom:16px">${lvl}${add}${gcard}</div>`;
  }
  // Futures: today's row, the end-of-day table's columns, read live against the same contract's close
  function liveFut(x) {
    const fu = x.fut, r = x.r.fut;
    if (!r) return `<div class="callout" style="margin-bottom:16px">No live future in the feed for this instrument.</div>`;
    return `<div style="margin-bottom:16px">${card({ title: "Today, live", chip: badge(), hint: "same contract vs its last close; carry from a contract 20+ days out, as at the close",
      body: `<div class="tbl-wrap"><table class="tbl"><thead><tr><th>Now</th><th>Future</th><th>Today</th><th>OI change</th><th>Near-month OI</th><th>Basis</th><th>Carry</th><th>Read</th></tr></thead><tbody>
        <tr><td>live</td><td class="num">${f.num(r.ltp, r.ltp > 1000 ? 1 : 2)}</td><td class="num">${fu && Number.isFinite(fu.dp) ? `<span class="chg ${fu.dp >= 0 ? "pos" : "neg"}">${f.sgn(fu.dp, 2)}%</span>` : "—"}</td>
        <td class="num">${fu && Number.isFinite(fu.doi) ? f.sgn(fu.doi, 1) + "%" : "—"}</td><td class="num">${big(r.oi)}</td><td class="num">${fu && Number.isFinite(fu.basis) ? f.num(fu.basis, 1) : "—"}</td>
        <td class="num">${fu && Number.isFinite(fu.carry) ? f.pct(fu.carry) + (Number.isFinite(x.carryPct) ? ` <span class="muted small">${ord(x.carryPct)} pct</span>` : "") : `<span class="muted small">near month under 20 days</span>`}</td>
        <td>${fu && fu.label ? `<span class="bu">${fu.label}</span>` : `<span class="muted small">${(fu && fu.why) || "—"}</span>`}</td></tr></tbody></table></div>` })}
      ${(x.months || []).length > 1 ? card({ title: "Every futures month, live", chip: badge(), hint: "each contract vs its own last close", cls: "stack",
        analyst: "Calendar spread: this month's future minus the month before it. Carry is annualised against the live spot and shown only 20+ days out.",
        body: `<div class="tbl-wrap"><table class="tbl"><thead><tr><th>Contract</th><th>Expiry</th><th>Future</th><th>Today</th><th>OI</th><th>OI change</th><th>Basis</th><th>Carry</th><th>Spread</th></tr></thead><tbody>
        ${x.months.map((m) => `<tr><td>${m.series}</td><td class="num">${m.expiry}</td><td class="num">${f.num(m.ltp, m.ltp > 1000 ? 1 : 2)}</td>
          <td class="num">${Number.isFinite(m.dp) ? `<span class="chg ${m.dp >= 0 ? "pos" : "neg"}">${f.sgn(m.dp, 2)}%</span>` : "—"}</td><td class="num">${Number.isFinite(m.oi) ? big(m.oi) : "—"}</td>
          <td class="num">${Number.isFinite(m.doi) ? f.sgn(m.doi, 1) + "%" : "—"}</td><td class="num">${Number.isFinite(m.basis) ? f.num(m.basis, 1) : "—"}</td>
          <td class="num">${Number.isFinite(m.carry) ? f.pct(m.carry) : "—"}</td><td class="num">${Number.isFinite(m.spread) ? f.num(m.spread, 1) : "—"}</td></tr>`).join("")}</tbody></table></div>` }) : ""}</div>`;
  }
  // charts for the live panels, drawn after the page's HTML is in place
  function charts(tab, u) {
    if (L.mode !== "live") return;
    const x = summary(u.symbol), t = theme();
    if (tab === "vol" && x && document.getElementById("liveIntra")) {
      const c = intraContract(x, u);
      if (c) { drawIntra(u.symbol); loadIntra(u.symbol, c).then(() => drawIntra(u.symbol)); }
    }
    if (tab === "oi" && x && x.oi && document.getElementById("liveOi")) {
      const rows = x.oi.rows;
      chart("#liveOi", { grid: { left: 64, right: 24, top: 10, bottom: 30 }, tooltip: { trigger: "axis", axisPointer: { type: "shadow" }, backgroundColor: t.surface, borderColor: t.line, textStyle: { color: t.text },
          formatter: (ps) => { const r = rows[ps[0].dataIndex]; return `<b>${f.num(r.K)}</b><br>calls ${big(r.call_oi)} (${r.call_chg >= 0 ? "+" : ""}${big(r.call_chg)} today)<br>puts ${big(r.put_oi)} (${r.put_chg >= 0 ? "+" : ""}${big(r.put_chg)} today)`; } },
        yAxis: { type: "category", data: rows.map((r) => f.num(r.K)), axisLabel: { color: t.text3, fontSize: 10 } },
        xAxis: { type: "value", axisLabel: { color: t.text3, formatter: (v) => big(v) }, splitLine: { lineStyle: { color: t.line2 } } },
        series: [{ name: "Calls added", type: "bar", data: rows.map((r) => r.call_chg), itemStyle: { color: t.s1 } }, { name: "Puts added", type: "bar", data: rows.map((r) => r.put_chg), itemStyle: { color: t.s2 } }] });
    }
    if (tab === "oi" && x && x.gamma && document.getElementById("liveGamma")) {
      const g = x.gamma;
      chart("#liveGamma", { grid: { left: 64, right: 24, top: 10, bottom: 30 }, tooltip: { trigger: "axis", axisPointer: { type: "shadow" }, backgroundColor: t.surface, borderColor: t.line, textStyle: { color: t.text },
          formatter: (ps) => { const i = ps[0].dataIndex; return `<b>${f.num(g.strikes[i])}</b><br>call gamma ${f.num(g.call[i], 1)} cr<br>put gamma ${f.num(g.put[i], 1)} cr${g.net ? `<br>hedgers' net ${f.num(g.net[i], 1)} cr` : ""}`; } },
        yAxis: { type: "category", data: g.strikes.map((k) => f.num(k)), axisLabel: { color: t.text3, fontSize: 10 } },
        xAxis: { type: "value", axisLabel: { color: t.text3, formatter: (v) => f.num(Math.abs(v)) }, splitLine: { lineStyle: { color: t.line2 } } },
        series: [{ name: "Call gamma", type: "bar", stack: "x", data: g.call, itemStyle: { color: t.s1 } }, { name: "Put gamma", type: "bar", stack: "x", data: g.put.map((v) => -v), itemStyle: { color: t.s2 } }] });
    }
    if (tab === "oi" && x && x.front && document.getElementById("liveOiLvl")) {
      const K = x.front.strikes, by = x.front.by;
      chart("#liveOiLvl", { grid: { left: 64, right: 24, top: 10, bottom: 30 }, tooltip: { trigger: "axis", axisPointer: { type: "shadow" }, backgroundColor: t.surface, borderColor: t.line, textStyle: { color: t.text },
          formatter: (ps) => { const k = K[ps[0].dataIndex]; return `<b>${f.num(k)}</b><br>calls ${big(by[k].CE ? by[k].CE.oi : 0)}<br>puts ${big(by[k].PE ? by[k].PE.oi : 0)}`; } },
        yAxis: { type: "category", data: K.map((k) => f.num(k)), axisLabel: { color: t.text3, fontSize: 10 } },
        xAxis: { type: "value", axisLabel: { color: t.text3, formatter: (v) => big(Math.abs(v)) }, splitLine: { lineStyle: { color: t.line2 } } },
        series: [{ name: "Calls", type: "bar", stack: "x", data: K.map((k) => (by[k].CE ? by[k].CE.oi : 0)), itemStyle: { color: t.s1 } },
          { name: "Puts", type: "bar", stack: "x", data: K.map((k) => -(by[k].PE ? by[k].PE.oi : 0)), itemStyle: { color: t.s2 } }] });
    }
    if (tab === "vol" && x && x.front && document.getElementById("liveTerm")) {
      const pt = (days, iv, e, sr) => ({ value: [days, iv], name: `${e} · ${sr || "expiry"}`, symbolSize: /month$/.test(sr || "") ? 9 : 5 });
      const now = x.r.expiries.filter((e) => e.ok).map((e) => pt(+e.days.toFixed(2), e.atm_iv, e.expiry, e.series));
      const close = x.base.term.map((c) => pt(Math.round((Date.parse(c.expiry + "T15:30:00+05:30") - Date.now()) / 86400e3 * 100) / 100, c.iv, c.expiry, c.series)).filter((p) => p.value[0] > 0);
      chart("#liveTerm", { tooltip: { trigger: "item", backgroundColor: t.surface, borderColor: t.line, textStyle: { color: t.text },
          formatter: (p) => `<b>${p.seriesName}</b><br>${p.data.name}<br>${p.data.value[0].toFixed(1)} days · ATM IV ${f.pct(p.data.value[1], 1)}` },
        xAxis: { type: "value", name: "days to expiry", nameLocation: "middle", nameGap: 24, nameTextStyle: { color: t.text3, fontSize: 11 }, axisLabel: { color: t.text3 }, splitLine: { show: false } },
        yAxis: axisY(t, fmtPct(1)), series: [line("Now", now, t.s1, { showSymbol: true }), line("Last close", close, t.s2, { showSymbol: true, lineStyle: { width: 1.5, type: "dashed", color: t.s2 } })] });
    }
    if (tab === "vol" && x && x.front && document.getElementById("liveSmile")) {
      const sm = x.front.smile.filter((p) => Math.abs(p[0] / x.front.F - 1) <= 0.15);
      chart("#liveSmile", { tooltip: { trigger: "axis", valueFormatter: (v) => f.pct(v, 2), backgroundColor: t.surface, borderColor: t.line, textStyle: { color: t.text } },
        xAxis: { type: "value", scale: true, axisLabel: { color: t.text3, formatter: (v) => f.num(v) }, splitLine: { show: false } }, yAxis: axisY(t, fmtPct(1)),
        series: [line("IV now", sm, t.s1, { showSymbol: true })] });
    }
  }

  window.MLLive = { start, poll, askKey, pulse, screener, symbol, charts, render, mcxCharts, mcxSelect, state: L };
})();
