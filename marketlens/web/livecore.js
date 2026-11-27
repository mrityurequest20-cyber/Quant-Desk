/* MarketLens live engine: the same rules as marketlens/engine/vol.py and positioning.py, applied to the private live
   relay's snapshot (/live/snapshot) every 5 seconds. Pure functions, no page code: marketlens/tests/test_live.py runs
   them in node against the Python engine on the same chains, so live and end-of-day numbers are computed one way.

   Rules carried over from the end-of-day engine (see vol.py for why each exists):
     - a quote counts only if it is fresh (its age from the relay's own clock) and, for an option, traded today (vol > 0)
     - forward from put-call parity at the traded strike where |C - P| is smallest; Black-76 on the out-of-the-money side
     - smile strikes must be liquid (0.5% of the expiry's busiest strike); the money itself always counts
     - an expiry is read only if its ATM pair traded, the parity strike is within 3% of the forward, the forward within
       3% of the live future, the straddle is at least 1 point, one tick moves IV by at most one vol point, and the smile's
       ATM vol agrees with the straddle's own vol within 25%
*/
(function (root) {
  "use strict";
  const MAX_EXPIRIES = 6, R = 0.065, Z25 = 0.6745, TICK_ERR = 0.0625, MIN_STRADDLE = 1.0, MIN_STRIKE_SHARE = 0.005;
  const MON = { JAN: 0, FEB: 1, MAR: 2, APR: 3, MAY: 4, JUN: 5, JUL: 6, AUG: 7, SEP: 8, OCT: 9, NOV: 10, DEC: 11 };
  const OPT = /^(.+?)(\d{2})(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)(\d{2})(\d+(?:\.\d+)?)(CE|PE)$/;

  // ---- maths (Black-76 on the forward, as vol.py) ----
  function ncdf(x) {                       // Abramowitz-Stegun 7.1.26 on erf: |error| < 1.5e-7, far below a vol tick
    const t = 1 / (1 + 0.3275911 * Math.abs(x) / Math.SQRT2);
    const y = 1 - (((((1.061405429 * t - 1.453152027) * t) + 1.421413741) * t - 0.284496736) * t + 0.254829592) * t * Math.exp(-x * x / 2);
    return x >= 0 ? 0.5 * (1 + y) : 0.5 * (1 - y);
  }
  function b76(F, K, T, sig, call) {
    const sq = sig * Math.sqrt(T), d1 = (Math.log(F / K) + 0.5 * sq * sq) / sq, d2 = d1 - sq, df = Math.exp(-R * T);
    return call ? df * (F * ncdf(d1) - K * ncdf(d2)) : df * (K * ncdf(-d2) - F * ncdf(-d1));
  }
  function impliedVol(px, F, K, T, call) {
    const df = Math.exp(-R * T), intr = df * Math.max(call ? F - K : K - F, 0), upper = df * (call ? F : K);
    if (!(px > intr + 1e-9 && px < upper && T > 0 && F > 0 && K > 0)) return null;
    let a = 0.005, b = 4.0;
    for (let i = 0; i < 60; i++) { const m = 0.5 * (a + b); if (b76(F, K, T, m, call) > px) b = m; else a = m; }
    const v = 0.5 * (a + b);
    return v <= 0.005 * 1.01 || v >= 4 * 0.99 ? null : v;
  }
  function ndtri(p) {                      // inverse normal CDF (Acklam), for the straddle's own vol
    const a = [-3.969683028665376e1, 2.209460984245205e2, -2.759285104469687e2, 1.383577518672690e2, -3.066479806614716e1, 2.506628277459239];
    const b = [-5.447609879822406e1, 1.615858368580409e2, -1.556989798598866e2, 6.680131188771972e1, -1.328068155288572e1];
    const c = [-7.784894002430293e-3, -3.223964580411365e-1, -2.400758277161838, -2.549732539343734, 4.374664141464968, 2.938163982698783];
    const d = [7.784695709041462e-3, 3.224671290700398e-1, 2.445134137142996, 3.754408661907416];
    const pl = 0.02425;
    if (p < pl) { const q = Math.sqrt(-2 * Math.log(p)); return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1); }
    if (p > 1 - pl) { const q = Math.sqrt(-2 * Math.log(1 - p)); return -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1); }
    const q = p - 0.5, r = q * q;
    return (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q / (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1);
  }
  const interp = (x, xs, ys) => {
    if (x <= xs[0]) return ys[0];
    for (let i = 1; i < xs.length; i++) if (x <= xs[i]) return ys[i - 1] + (ys[i] - ys[i - 1]) * (x - xs[i - 1]) / (xs[i] - xs[i - 1]);
    return ys[ys.length - 1];
  };

  // ---- time: years to an expiry's 15:30 IST close, from now (ms) ----
  function expiryDate(dd, mon, yy) { return `20${yy}-${String(MON[mon] + 1).padStart(2, "0")}-${dd}`; }
  function istDate(ms) { return new Date(ms + 5.5 * 3600e3).toISOString().slice(0, 10); }
  function yearsTo(expiry, nowMs) {
    const close = Date.parse(expiry + "T15:30:00+05:30");
    return Math.max(close - nowMs, 60e3) / (365 * 86400e3);
  }

  // ---- one underlying's chains from the snapshot ----
  function chains(quotes, symbol, maxAge) {
    const out = {};
    for (const name in quotes) {
      if (!name.startsWith(symbol)) continue;
      const m = OPT.exec(name);
      if (!m || m[1] !== symbol) continue;
      const q = quotes[name];
      if (!(q.age_s <= maxAge) || !(q.ltp > 0)) continue;
      const e = expiryDate(m[2], m[3], m[4]);
      (out[e] = out[e] || []).push({ K: +m[5], right: m[6], ltp: q.ltp, vol: q.vol || 0, oi: q.oi || 0, age: q.age_s });
    }
    return out;
  }

  // one expiry, read the vol.py way
  function readExpiry(rows, T, futAnchor) {
    const by = {};
    for (const r of rows) (by[r.K] = by[r.K] || {})[r.right] = r;
    const Ks = Object.keys(by).map(Number).sort((a, b) => a - b);
    const pairs = Ks.filter((k) => by[k].CE && by[k].PE && by[k].CE.vol > 0 && by[k].PE.vol > 0);
    const res = { strikes: Ks, by, ok: false };
    if (!pairs.length) { res.why = "no traded at-the-money pair"; return res; }
    let best = pairs[0];
    for (const k of pairs) if (Math.abs(by[k].CE.ltp - by[k].PE.ltp) < Math.abs(by[best].CE.ltp - by[best].PE.ltp)) best = k;
    const C = by[best].CE.ltp, P = by[best].PE.ltp, F = best + Math.exp(R * T) * (C - P), straddle = C + P;
    Object.assign(res, { F, atm_strike: best, straddle, move: straddle / F });
    // liquidity is measured among the out-of-the-money quotes, the side the smile is read from (as vol.py)
    const otm = Ks.map((k) => by[k][k >= F ? "CE" : "PE"]).filter((r) => r && r.vol > 0 && r.K / F >= 0.6 && r.K / F <= 1.6);
    const maxVol = otm.length ? Math.max(...otm.map((r) => r.vol)) : 0;
    res.atm_vol = rows.filter((r) => Math.abs(r.K / F - 1) <= 0.03).reduce((a, r) => a + r.vol, 0);
    const smile = [];
    for (const k of Ks) {
      const call = k >= F, r = by[k][call ? "CE" : "PE"];
      if (!r || !(r.vol > 0) || k / F < 0.6 || k / F > 1.6) continue;
      const liquid = r.vol >= Math.max(1, MIN_STRIKE_SHARE * maxVol) || Math.abs(k / F - 1) <= 0.03;
      if (!liquid) continue;
      const iv = impliedVol(r.ltp, F, k, T, call);
      if (iv !== null) smile.push([k, iv]);
    }
    res.smile = smile;
    if (smile.length < 2 || !(smile[0][0] <= F && F <= smile[smile.length - 1][0])) { res.why = "too few liquid strikes around the money"; return res; }
    const xs = smile.map((x) => x[0]), ys = smile.map((x) => x[1]);
    const atm = interp(F, xs, ys);
    const q = (straddle / (2 * Math.exp(-R * T) * F) + 1) / 2;
    const stIv = q > 0.5 && q < 0.9999 ? 2 * ndtri(q) / Math.sqrt(T) : null;
    Object.assign(res, { atm_iv: atm, straddle_iv: stIv });
    const checks = [
      [Math.abs(best / F - 1) <= 0.03, "parity strike far from the forward"],
      [futAnchor === null || Math.abs(F / futAnchor - 1) <= 0.03, "forward far from the live future"],
      [straddle >= MIN_STRADDLE, "straddle too small to read"],
      [TICK_ERR / (F * Math.sqrt(T)) <= 0.01, "one price tick moves the vol by more than a point"],
      [atm >= 0.03 && atm <= 3, "implied vol outside 3%..300%"],
      [stIv !== null && Math.abs(atm / stIv - 1) <= 0.25, "smile and straddle disagree"],
    ];
    const bad = checks.find((c) => !c[0]);
    if (bad) { res.why = bad[1]; return res; }
    res.ok = true;
    const sq = atm * Math.sqrt(T), kc = F * Math.exp(0.5 * sq * sq + Z25 * sq), kp = F * Math.exp(0.5 * sq * sq - Z25 * sq);
    if (xs[0] <= kp && kc <= xs[xs.length - 1]) {
      const ivc = interp(kc, xs, ys), ivp = interp(kp, xs, ys);
      res.rr25 = ivc - ivp;
      res.fly25 = 0.5 * (ivc + ivp) - atm;
    }
    return res;
  }

  // vol.py drop_curve_outliers: an interior expiry far off the total-variance line of its neighbours is a stale print.
  // Below its neighbours (variance falling with maturity) is judged tightly, above (a possible event) loosely; one
  // point at a time, chosen leave-one-out; never more than a third of the curve; the ends are never removed.
  function dropCurveOutliers(exps) {
    let idx = exps.slice().sort((a, b) => a.days - b.days);
    const days = (e) => Math.round(e.days);             // vol.py measures in whole calendar days
    const excesses = (keys) => {
      const out = new Map();
      for (let i = 1; i < keys.length - 1; i++) {
        const k = keys[i], a = keys[i - 1], b = keys[i + 1];
        const wa = a.atm_iv ** 2 * days(a), wb = b.atm_iv ** 2 * days(b);
        const wi = wa + (wb - wa) * (days(k) - days(a)) / (days(b) - days(a));
        const ref = Math.sqrt(Math.max(wi, 1e-12) / days(k));
        const tol = k.atm_iv < ref ? Math.max(0.03, 0.15 * ref) : Math.max(0.05, 0.3 * ref);
        out.set(k, Math.abs(k.atm_iv - ref) / tol);
      }
      return out;
    };
    let budget = Math.max(1, Math.floor(idx.length / 3));
    while (idx.length >= 3 && budget > 0) {
      budget -= 1;
      const ex = excesses(idx);
      const bad = [...ex.entries()].filter(([, e]) => e > 1);
      if (!bad.length) break;
      let best = null, bestScore = null;
      for (const [k, e] of bad) {
        const rest = excesses(idx.filter((j) => j !== k));
        const score = [Math.max(0, ...rest.values()), -e];
        if (!best || score[0] < bestScore[0] || (score[0] === bestScore[0] && score[1] < bestScore[1])) { best = k; bestScore = score; }
      }
      best.ok = false; best.why = "off its own curve (a stale print)";
      idx = idx.filter((j) => j !== best);
    }
  }

  // the whole live read of one underlying
  function readUnderlying(quotes, symbol, opts) {
    const { nowMs, maxAge } = opts;
    const sq = quotes[symbol], fq = quotes[symbol + "-FUT"];
    const fresh = (q) => q && q.age_s <= maxAge && q.ltp > 0;
    const out = { symbol, spot: fresh(sq) ? sq.ltp : null, spotChg: fresh(sq) && Number.isFinite(sq.chg) ? sq.chg / 100 : null,
      spotAge: sq ? sq.age_s : null, src: sq ? sq.src : null,
      fut: fresh(fq) ? { ltp: fq.ltp, oi: fq.oi || 0, chg: Number.isFinite(fq.chg) ? fq.chg / 100 : null, age: fq.age_s, e: fq.e || null } : null,
      expiries: [] };
    const ch = chains(quotes, symbol, maxAge);
    const today = istDate(nowMs);
    for (const e of Object.keys(ch).sort().filter((x) => x > today).slice(0, MAX_EXPIRIES)) {   // the nearest 6, as vol.py
      const T = yearsTo(e, nowMs);
      const days = (Date.parse(e + "T15:30:00+05:30") - nowMs) / 86400e3;
      // a contract on its own expiry day is all gamma, no vol: not read (vol.py MIN_DAYS), and never the yardstick
      // for the other expiries' liquidity
      if (e <= istDate(nowMs)) continue;
      const anchor = out.fut ? out.fut.ltp : null;
      const r = readExpiry(ch[e], T, anchor);
      r.expiry = e; r.days = days; r.T = T;
      out.expiries.push(r);
    }
    // an expiry trading under 0.2% of the busiest one near the money is not read (vol.py MIN_LIQ_SHARE); the front stays
    const busiest = Math.max(0, ...out.expiries.map((x) => x.atm_vol || 0));
    out.expiries.forEach((x, i) => { if (i > 0 && x.ok && (x.atm_vol || 0) < 0.002 * busiest) { x.ok = false; x.why = "too thin next to the front expiry"; } });
    dropCurveOutliers(out.expiries.filter((x) => x.ok));
    return out;
  }

  // ---- comparisons with the end-of-day baseline (the sym/<X>.json the app already has) ----

  // the share of a value's last 252 end-of-day readings below it (positioning.latest_pct's convention)
  function pctVsHistory(v, hist) {
    const h = (hist || []).filter((x) => x !== null && Number.isFinite(x)).slice(-252);
    if (v === null || !Number.isFinite(v) || h.length < 21) return null;
    return h.filter((x) => x < v).length / h.length;
  }

  // OI by strike now vs the last close, on the strikes both carry; near-money PCR on that same set
  function oiVsClose(exp, profile) {
    if (!exp || !profile) return null;
    const rows = [];
    let lc = 0, lp = 0, ec = 0, ep = 0;
    profile.strikes.forEach((k, i) => {
      const s = exp.by[k];
      if (!s || !s.CE || !s.PE) return;
      const c0 = profile.call_oi[i], p0 = profile.put_oi[i];
      rows.push({ K: k, call_oi: s.CE.oi, put_oi: s.PE.oi, call_chg: s.CE.oi - c0, put_chg: s.PE.oi - p0, call_ltp: s.CE.ltp, put_ltp: s.PE.ltp });
      lc += s.CE.oi; lp += s.PE.oi; ec += c0; ep += p0;
    });
    if (!rows.length) return null;
    return { rows, pcr_live: lc > 0 ? lp / lc : null, pcr_close: ec > 0 ? ep / ec : null, call_add: lc - ec, put_add: lp - ep };
  }

  // today's futures read against the last close of the SAME contract (positioning.futures_book's rule)
  function futuresToday(live, lastRow, todayIso) {
    if (!live || !live.fut || !lastRow) return null;
    if (!(lastRow.fut_expiry > todayIso)) return { why: "the contract in the last close has expired: no same-contract read until the next close" };
    const dp = live.fut.ltp / lastRow.fut - 1;
    const doi = lastRow.near_oi > 0 ? live.fut.oi / lastRow.near_oi - 1 : null;
    const label = doi === null ? "No read" : dp > 0 && doi > 0 ? "Long build-up" : dp < 0 && doi > 0 ? "Short build-up" : dp > 0 && doi < 0 ? "Short covering" : dp < 0 && doi < 0 ? "Long unwinding" : "Flat";
    const basis = live.spot !== null ? live.fut.ltp - live.spot : null;
    const days = (Date.parse(lastRow.fut_expiry + "T15:30:00+05:30") - Date.now()) / 86400e3;
    // carry only from a contract 20+ days out, as at end of day (a short basis annualised is noise)
    const carry = basis !== null && days >= 20 ? Math.log(live.fut.ltp / live.spot) / (days / 365) : null;
    return { dp, doi, label, basis, carry, expiry: lastRow.fut_expiry };
  }

  // vol.py constant_maturity, on the live expiries: total variance interpolated in time to `days`; an expiry this week
  // alone is not stretched to 30 days; flat at the ends. One extra rule for live: the feed carries only the nearest
  // expiries, so if none lies within 5 days of the target (NIFTY's live chain is two weeklies) the end-of-day method
  // would have used a monthly the feed does not have: no reading, rather than a number built differently.
  function constantMaturity(exps, days = 30) {
    const g = exps.filter((e) => e.ok && e.days >= 2).sort((a, b) => a.days - b.days);
    if (!g.length || g[g.length - 1].days < 7) return { iv: null, why: "only an expiry this week" };
    if (g[g.length - 1].days < days - 5) return { iv: null, why: "no live expiry near 30 days" };
    const x = g.map((e) => e.days), w = g.map((e) => e.atm_iv * e.atm_iv * e.days);
    if (g.length === 1 || days <= x[0]) return { iv: days <= x[0] ? g[0].atm_iv : g[g.length - 1].atm_iv };
    if (days >= x[x.length - 1]) return { iv: g[g.length - 1].atm_iv };
    return { iv: Math.sqrt(Math.max(interp(days, x, w), 0) / days) };
  }

  // walls among the live strikes: the largest call OI at or above the price, the largest put OI at or below it
  function walls(exp, spot) {
    if (!exp || !spot) return null;
    let cw = null, pw = null, cmax = 0, pmax = 0, tc = 0, tp = 0;
    for (const k of exp.strikes) {
      const s = exp.by[k];
      if (s.CE) { tc += s.CE.oi; if (k >= spot && s.CE.oi > cmax) { cmax = s.CE.oi; cw = k; } }
      if (s.PE) { tp += s.PE.oi; if (k <= spot && s.PE.oi > pmax) { pmax = s.PE.oi; pw = k; } }
    }
    return { call_wall: cw, put_wall: pw, pcr: tc > 0 ? tp / tc : null, lo: exp.strikes[0], hi: exp.strikes[exp.strikes.length - 1] };
  }

  const api = { constantMaturity, walls, istDate, b76, impliedVol, ndtri, readExpiry, readUnderlying, chains, yearsTo, pctVsHistory, oiVsClose, futuresToday, OPT };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.LiveCore = api;
})(typeof window !== "undefined" ? window : globalThis);
