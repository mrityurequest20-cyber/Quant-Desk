/* MarketLens alerts: the rules, evaluated the same way in the browser (live-ui.js, while the app is open) and in the
   desk's Worker every ten minutes (deploy/cloudflare/alerts.js, which pushes them to the owner's phone through ntfy).
   Pure functions over the relay's snapshot and the close-of-day baseline (overview.json: live_base and limits); every
   reading goes through LiveCore, so an alert says exactly what the app's live panels say.

   Each alert has a key that names the rule, the instrument, the side and the IST day: an alert fires once a day per key
   (the Worker keeps the keys it sent in the relay's storage; the browser in its own). Nothing here predicts a move: an
   alert says a reading crossed a line the owner set. */
(function (root) {
  "use strict";
  const LC = () => root.LiveCore || (typeof require === "function" ? require("./livecore.js") : null);

  const DEFAULT_RULES = [
    { id: "iv_extreme", on: true, label: "Front-expiry IV at a one-year extreme", hi: 0.95, lo: 0.05, scope: "indices" },
    { id: "big_move", on: true, label: "Moving more than options priced for the day", mult: 2, scope: "all" },
    { id: "gamma_flip", on: true, label: "Index crosses the hedgers' gamma flip" },
    { id: "curve_inverted", on: true, label: "An index's front expiry dearer than 30 days by", pts: 0.02 },
    { id: "ban", on: true, label: "A watchlist stock in, or near, the F&O ban", near: 0.9 },
    { id: "mcx_move", on: true, label: "An MCX commodity moving more than its options priced", mult: 2 },
  ];
  const MCX = ["CRUDEOIL", "NATURALGAS", "GOLD", "SILVER", "COPPER", "CRUDEOILM", "NATGASMINI", "GOLDM", "SILVERM"];
  const MAX_AGE = 120, OPT_MAX_AGE = 480;

  // a rules list as the owner saved it, on top of the defaults: unknown rules dropped, numbers kept in range
  function mergeRules(saved) {
    const by = {};
    (Array.isArray(saved) ? saved : []).forEach((r) => { if (r && typeof r.id === "string") by[r.id] = r; });
    const clamp = (x, lo, hi, d) => (typeof x === "number" && Number.isFinite(x) ? Math.min(hi, Math.max(lo, x)) : d);
    return DEFAULT_RULES.map((d) => {
      const s = by[d.id] || {};
      const r = { ...d, on: typeof s.on === "boolean" ? s.on : d.on };
      if ("hi" in d) r.hi = clamp(s.hi, 0.5, 1, d.hi);
      if ("lo" in d) r.lo = clamp(s.lo, 0, 0.5, d.lo);
      if ("mult" in d) r.mult = clamp(s.mult, 1, 10, d.mult);
      if ("pts" in d) r.pts = clamp(s.pts, 0.0, 0.2, d.pts);
      if ("near" in d) r.near = clamp(s.near, 0.5, 1, d.near);
      if ("scope" in d && ["indices", "all"].includes(s.scope)) r.scope = s.scope;
      return r;
    });
  }

  const pct = (x, d = 1) => (x * 100).toFixed(d) + "%";
  const ord = (p) => { const n = Math.round(p * 100); const s = n % 100 >= 11 && n % 100 <= 13 ? "th" : { 1: "st", 2: "nd", 3: "rd" }[n % 10] || "th"; return n + s; };

  // the alerts due now. quotes: the snapshot's; ov: overview.json; nowMs: the clock; opts.nse / opts.mcx / opts.eod: which
  // families to evaluate (the Worker opens each in its own hours)
  function evaluate(quotes, ov, rules, nowMs, opts = {}) {
    const L = LC();
    const R = {};
    mergeRules(rules).forEach((r) => { R[r.id] = r; });
    const day = L.istDate(nowMs), out = [];
    const add = (rule, sym, side, title, body, sev = "INFO") => out.push({ key: `${day}:${rule}:${sym}:${side}`, rule, symbol: sym, title, body, sev });
    const base = (ov && ov.live_base) || {};
    const kinds = {};
    ((ov && ov.universe) || []).forEach((u) => { kinds[u.symbol] = u.kind; });
    if (opts.nse !== false) {
      for (const sym of Object.keys(base)) {
        const b = base[sym], kind = kinds[sym] || b.kind;
        const isIdx = kind === "index";
        const r = L.readUnderlying(quotes, sym, { nowMs, maxAge: MAX_AGE, optMaxAge: OPT_MAX_AGE });
        if (r.spot === null) continue;
        const front = r.expiries.find((e) => e.ok) || null;
        if (R.iv_extreme.on && front && (isIdx || R.iv_extreme.scope === "all")) {
          const p = L.pctVsHistory(front.atm_iv, b.iv_front);
          if (p !== null && p >= R.iv_extreme.hi) add("iv_extreme", sym, "hi", `${sym} options at a one-year high`, `${sym} front-expiry IV ${pct(front.atm_iv)}: ${ord(p)} percentile of the past year (${front.expiry}).`);
          if (p !== null && p <= R.iv_extreme.lo) add("iv_extreme", sym, "lo", `${sym} options at a one-year low`, `${sym} front-expiry IV ${pct(front.atm_iv)}: ${ord(p)} percentile of the past year (${front.expiry}).`);
        }
        if (R.big_move.on && front && r.spotChg !== null && (isIdx || R.big_move.scope === "all")) {
          const day1 = front.atm_iv / Math.sqrt(252);
          if (Math.abs(r.spotChg) >= R.big_move.mult * day1) add("big_move", sym, r.spotChg > 0 ? "up" : "down", `${sym} ${r.spotChg > 0 ? "+" : ""}${pct(r.spotChg, 2)} today`,
            `${sym} has moved ${(Math.abs(r.spotChg) / day1).toFixed(1)}x the one-day move its options price (${pct(day1, 2)} at ${pct(front.atm_iv)} IV).`, "P2");
        }
        if (R.gamma_flip.on && isIdx && b.gamma && Number.isFinite(b.gamma.flip) && Number.isFinite(b.close)) {
          const was = b.close >= b.gamma.flip, now = r.spot >= b.gamma.flip;
          if (was !== now) add("gamma_flip", sym, now ? "above" : "below", `${sym} crossed its gamma flip`,
            `${sym} at ${Math.round(r.spot)} is ${now ? "above" : "below"} the hedgers' gamma flip (${Math.round(b.gamma.flip)}; it closed ${was ? "above" : "below"} yesterday): their hedging now ${now ? "damps" : "adds to"} moves.`, "P2");
        }
        if (R.curve_inverted.on && isIdx && front && front.days >= 2) {
          const cm = L.constantMaturity(r.expiries);
          if (cm.iv !== null && front.atm_iv - cm.iv >= R.curve_inverted.pts) add("curve_inverted", sym, "inv", `${sym} curve inverted`,
            `${sym} front expiry (${front.expiry}) at ${pct(front.atm_iv)} against ${pct(cm.iv)} for 30 days: the market is pricing something soon.`);
        }
      }
    }
    if (opts.eod && R.ban.on && ov && ov.limits && ov.limits.available) {
      const watch = new Set(((ov && ov.universe) || []).filter((u) => u.kind === "stock").map((u) => u.symbol));
      for (const s of ov.limits.ban || []) if (watch.has(s)) add("ban", s, ov.limits.ban_date || "ban", `${s} in the F&O ban`, `${s} is on NSE's F&O ban list for ${ov.limits.ban_date}: no fresh positions, only closing.`, "P2");
      for (const n of ov.limits.near || []) if (!n.in_ban && n.util >= R.ban.near) add("ban", n.symbol, "near", `${n.symbol} near the F&O ban`, `${n.symbol} open interest at ${pct(n.util, 0)} of its market-wide limit (ban at 95%).`);
    }
    if (opts.mcx && R.mcx_move.on) {
      for (const c of MCX) {
        const fq = quotes[c + "-MCX"];
        if (!fq || !(fq.age_s <= MAX_AGE) || !Number.isFinite(fq.chg)) continue;
        const r = L.readUnderlying(quotes, c, { nowMs, maxAge: MAX_AGE, optMaxAge: OPT_MAX_AGE, futName: c + "-MCX", closeHHMM: "23:30" });
        const front = r.expiries.find((e) => e.ok);
        if (!front) continue;
        const chg = fq.chg / 100, day1 = front.atm_iv / Math.sqrt(252);
        if (Math.abs(chg) >= R.mcx_move.mult * day1) add("mcx_move", c, chg > 0 ? "up" : "down", `${c} ${chg > 0 ? "+" : ""}${pct(chg, 2)} today`,
          `${c} has moved ${(Math.abs(chg) / day1).toFixed(1)}x the one-day move its options price (${pct(day1, 2)} at ${pct(front.atm_iv)} IV).`, "P2");
      }
    }
    return out;
  }

  const api = { DEFAULT_RULES, mergeRules, evaluate };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.AlertRules = api;
})(typeof window !== "undefined" ? window : globalThis);
