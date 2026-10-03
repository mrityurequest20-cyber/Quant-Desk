"""Research on the TrueData export (data/external_truedata.py), with what one year of daily index bars can and cannot say.

Three parts, kept apart in the report:
1. **Descriptive (observed).** Returns, volatility, drawdown, gaps, ranges, trend and range behaviour, persistence
   (lag-1 autocorrelation, variance ratio, Hurst, ADX), monthly realised volatility. The 2010–2023 aeron7 minutes give
   context where available.
2. **The pre-registered daily hypotheses D1–D5** of research/edges.py, re-measured on this year. They were written
   before this data existed, but research/edges.py has run on Yahoo's full history, which contains these same
   prices. So this is a re-measurement on the latest year, not a fresh out-of-sample test.
3. **A causal replay through a prediction ledger.**
   - Each day, every hypothesis and baseline writes its call at 09:15 IST, from closes up to yesterday and today's
     open only.
   - The outcome is attached only once the replay clock passes that day's 15:30 close.
   - Scored: accuracy, balanced accuracy, signed points after the cost hurdle, drawdown, by volatility regime, against
     baselines (always long, persistence, reversal, coin).
   - Probability calibration does not apply: none of these rules emits a probability.

Nothing here is option evidence. There are no option prices in the export, and the cost hurdle (one lot of a 0.35Δ
option, research/edges.py) only says how large a move would have to be. The replay ledger is research-only
(`source = truedata_replay`) and is never mixed with the live forward ledger.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

from ..analytics.indicators import adx
from ..analytics.stats import hurst, variance_ratio
from ..data import external_truedata as T
from . import edges

HYPOTHESES = {
    "D1": "long open→close every day",
    "D2": "after a gap > 0.3%, the gap's direction open→close",
    "D3": "after a close-to-close fall > 1.5%, long open→close",
    "D4": "Tuesday (weekly expiry), long open→close",
    "D5": "turn of the month (last day + first 3), long open→close",
}
BASELINES = {
    "B_persist": "yesterday's open→close direction again",
    "B_reverse": "the opposite of yesterday's open→close direction",
    "B_coin": "a fair coin (seeded)",
}
MIN_N = 30


def daily(ds: Path, sym: str) -> pd.DataFrame:
    df = T.load(ds, "1d", [sym], use="direction_research")
    d = df.set_index(pd.DatetimeIndex(df["ts"].dt.tz_localize(None).dt.normalize()))[["open", "high", "low", "close"]].astype(float)
    d.attrs = df.attrs
    return d


# ---- 1. descriptive -------------------------------------------------------------------------------------------------
def describe(d: pd.DataFrame) -> dict:
    c, o, h, l = d["close"], d["open"], d["high"], d["low"]
    r = np.log(c / c.shift(1)).dropna()
    oc = np.log(c / o)
    gap = np.log(o / c.shift(1)).dropna()
    rng = (h - l) / o
    body = (c - o).abs() / (h - l).replace(0, np.nan)
    dd = c / c.cummax() - 1
    a = adx(d.assign(volume=0.0))
    adx14 = a["adx"] if "adx" in a else a.iloc[:, 0]
    vr, vz = variance_ratio(np.log(c.to_numpy()), 5)
    ac1 = float(r.autocorr(1))
    monthly = (r.groupby(r.index.to_period("M")).std() * math.sqrt(252)).round(4)
    return {
        "sessions": int(len(d)), "first": str(d.index[0].date()), "last": str(d.index[-1].date()),
        "total_return": float(c.iloc[-1] / c.iloc[0] - 1), "ann_vol": float(r.std() * math.sqrt(252)),
        "mean_daily_bps": float(r.mean() * 1e4), "skew": float(r.skew()), "excess_kurtosis": float(r.kurt()),
        "up_days": float((r > 0).mean()), "max_drawdown": float(dd.min()), "max_drawdown_on": str(dd.idxmin().date()),
        "best_day": [str(r.idxmax().date()), float(r.max())], "worst_day": [str(r.idxmin().date()), float(r.min())],
        "mean_range_pct": float(rng.mean()), "mean_abs_gap_pct": float(gap.abs().mean()),
        "intraday_share_of_move": float(oc.abs().mean() / r.abs().mean()),
        "trend_days": float((body >= 0.6).mean()), "range_days": float((body <= 0.25).mean()),
        "lag1_autocorr": ac1, "lag1_band95": float(1.96 / math.sqrt(len(r))),
        "variance_ratio_5": [float(vr), float(vz)], "hurst": float(hurst(np.log(c.to_numpy()))),
        "adx14_mean": float(adx14.dropna().mean()), "adx_above_25": float((adx14.dropna() > 25).mean()),
        "monthly_ann_vol": {str(k): float(v) for k, v in monthly.items()},
    }


def history_context(sym: str, ext_root: Path) -> dict | None:
    """The same measures over 2011–2023 from the verified aeron7 minutes, for scale (if imported here)."""
    try:
        from ..data import external_aeron as X
        ds = X.latest(ext_root)
        if ds is None:
            return None
        m = X.load(ds, "5m", [sym], use="regime_research")
        g = m.groupby(m.index.date if not isinstance(m.index, pd.RangeIndex) else pd.to_datetime(m["ts"]).dt.date)
        d = pd.DataFrame({"open": g["open"].first(), "high": g["high"].max(), "low": g["low"].min(), "close": g["close"].last()})
        d.index = pd.to_datetime(d.index)
        x = describe(d)
        return {k: x[k] for k in ("sessions", "first", "last", "ann_vol", "mean_range_pct", "mean_abs_gap_pct", "trend_days",
                                  "range_days", "lag1_autocorr", "up_days")}
    except Exception as exc:                         # context is optional; say why it's missing
        return {"unavailable": f"{exc!s:.120}"}


# ---- 2. the pre-registered hypotheses -------------------------------------------------------------------------------
def hypotheses(d: pd.DataFrame, sym: str) -> list[dict]:
    dd = d.copy()
    dd.index = dd.index.tz_localize(edges.IST)
    return [r.__dict__ for r in edges.daily_tests(sym, dd, vix=None)]


# ---- 3. the causal replay -------------------------------------------------------------------------------------------
class ReplayLedger:
    """Predictions are appended with their as-of time before the outcome exists; `resolve(now)` attaches outcomes only for
    horizons that have ended by `now`. A prediction can't be edited once written."""

    def __init__(self):
        self.rows: list[dict] = []

    def predict(self, as_of: pd.Timestamp, horizon_end: pd.Timestamp, rule: str, symbol: str, direction: int, ctx: dict):
        if horizon_end <= as_of:
            raise ValueError("a prediction's horizon must end after it is made")
        self.rows.append({"source": "truedata_replay", "as_of": as_of, "horizon_end": horizon_end, "rule": rule,
                          "symbol": symbol, "direction": int(direction), **ctx, "outcome": None})

    def resolve(self, now: pd.Timestamp, outcome_of) -> None:
        for r in self.rows:
            if r["outcome"] is None and r["horizon_end"] <= now:
                r["outcome"] = outcome_of(r)

    def frame(self) -> pd.DataFrame:
        return pd.DataFrame(self.rows)


def replay(d: pd.DataFrame, sym: str, seed: int = 20261004) -> pd.DataFrame:
    """Walk the year day by day. At 09:15 IST each rule sees closes up to yesterday and today's open, nothing else."""
    rng = np.random.default_rng(seed)
    led = ReplayLedger()
    idx = d.index
    month = idx.tz_localize(None).to_period("M") if idx.tz is not None else idx.to_period("M")
    pos = pd.Series(range(len(d)), index=idx).groupby(month).rank(method="first")
    size = pd.Series(1, index=idx).groupby(month).transform("size")
    tom = ((pos <= 3) | (pos == size)).to_numpy()                 # the exchange calendar is known in advance
    closes = d["close"].to_numpy()
    for i in range(1, len(d)):
        day = idx[i]
        as_of = pd.Timestamp(f"{day.date()} 09:15", tz=T.IST)
        end = pd.Timestamp(f"{day.date()} 15:30", tz=T.IST)
        past = d.iloc[:i]                                         # closes up to yesterday
        open_t = float(d["open"].iat[i])                         # known at 09:15
        prev_c = float(past["close"].iat[-1])
        gap = math.log(open_t / prev_c)
        r_prev = math.log(prev_c / float(past["close"].iat[-2])) if i >= 2 else float("nan")
        oc_prev = math.log(prev_c / float(past["open"].iat[-1]))
        rv = np.log(past["close"]).diff().tail(20).std() * math.sqrt(252) if i >= 15 else float("nan")
        ctx = {"day": str(day.date()), "rv20": float(rv), "open": open_t}
        calls = {"D1": 1, "D2": int(np.sign(gap)) if abs(gap) > 0.003 else 0, "D3": 1 if r_prev < -0.015 else 0,
                 "D4": 1 if day.dayofweek == 1 else 0, "D5": 1 if tom[i] else 0,
                 "B_persist": int(np.sign(oc_prev)), "B_reverse": -int(np.sign(oc_prev)),
                 "B_coin": int(rng.choice([-1, 1]))}
        for rule, direction in calls.items():
            if direction != 0:
                led.predict(as_of, end, rule, sym, direction, ctx)
        led.resolve(end, lambda r, c=closes[i], o=open_t: {"close": float(c), "ret": math.log(c / o)}
                    if r["day"] == str(day.date()) else None)
    f = led.frame()
    f["ret"] = f["outcome"].map(lambda x: x["ret"])
    return f


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return float("nan"), float("nan")
    p = k / n
    den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return c - h, c + h


def score(f: pd.DataFrame, sym: str) -> dict:
    hurdle = edges.COST_POINTS[sym]
    terc = f["rv20"].quantile([1 / 3, 2 / 3]).to_numpy() if f["rv20"].notna().any() else None
    out = {}
    for rule, g in f.groupby("rule"):
        up = g["ret"] > 0
        hit = np.sign(g["ret"]) == g["direction"]
        pts = g["direction"] * g["ret"] * g["open"]
        net = pts - hurdle
        pred_up = g["direction"] > 0
        tpr = float((pred_up & up).sum() / up.sum()) if up.sum() else float("nan")
        tnr = float((~pred_up & ~up).sum() / (~up).sum()) if (~up).sum() else float("nan")
        m, t, p = edges.hac_mean((g["direction"] * g["ret"]).to_numpy())
        lo, hi = wilson(int(hit.sum()), len(g))
        cum = net.cumsum()
        reg = {}
        if terc is not None:
            band = np.where(g["rv20"] <= terc[0], "low vol", np.where(g["rv20"] <= terc[1], "mid vol", "high vol"))
            band = np.where(g["rv20"].isna(), "warm-up", band)
            for b in ["low vol", "mid vol", "high vol"]:
                s = g[band == b]
                reg[b] = {"n": int(len(s)), "accuracy": float((np.sign(s["ret"]) == s["direction"]).mean()) if len(s) else None,
                          "mean_pts": float((s["direction"] * s["ret"] * s["open"]).mean()) if len(s) else None,
                          "insufficient": len(s) < MIN_N}
        out[rule] = {"n": int(len(g)), "accuracy": float(hit.mean()), "accuracy_ci95": [lo, hi],
                     "balanced_accuracy": float(np.nanmean([tpr, tnr])) if pred_up.any() and (~pred_up).any() else 0.5,
                     "always_one_side": bool(pred_up.all() or (~pred_up).all()),
                     "mean_signed_bps": float(m * 1e4), "t_hac": t, "p": p, "mean_pts": float(pts.mean()),
                     "hurdle_pts": hurdle, "net_pts_per_trade": float(net.mean()), "net_pts_total": float(net.sum()),
                     "max_drawdown_pts": float((cum - cum.cummax()).min()), "by_regime": reg,
                     "insufficient": len(g) < MIN_N}
    return out


# ---- the existing backtester (scenario only) ------------------------------------------------------------------------
def backtest_scenario(cfg, start: str) -> dict:
    """The desk's index strategies need India VIX (their IV input), which the export lacks. With TrueData's index bars
    plus Yahoo's India VIX they can run, but every option price is then modelled: scenario analysis only."""
    from ..backtest.runner import run_backtest
    from ..data.yahoo import YahooProvider
    from ..strategies import build_strategies
    prov = T.TrueDataProvider(Path(cfg.runtime_dir) / "external")
    data = {s: prov.history(s, "2000-01-01") for s in ("NIFTY", "BANKNIFTY")}
    try:
        data["INDIAVIX"] = YahooProvider(cfg).history("INDIAVIX", pd.Timestamp(start) - pd.DateOffset(years=2))
    except Exception as exc:
        return {"status": f"not run: India VIX unavailable ({exc!s:.100})"}
    names = [n for n in ("vrp_condor", "trend_spread", "long_vol")]
    strats = build_strategies(cfg, names)
    res = run_backtest(cfg, data, strats, start=start)
    per = res.per_strategy
    trades = res.trades
    return {"status": "scenario analysis only (option prices modelled from India VIX; index prices from TrueData)",
            "strategies": names, "trades": int(len(trades)),
            "per_strategy": per.reset_index().to_dict("records") if not per.empty else [],
            "summary": res.summary(), "warmup_bars": int(cfg.get("backtest.warmup_bars", 260)),
            "sessions": int(min(len(v) for k, v in data.items() if k != "INDIAVIX")),
            "note": "the daily engine trades only after backtest.warmup_bars sessions; the TrueData year is shorter, "
                    "so no strategy can act on it alone (the warm-up is not lowered: that would change the strategies)"}


def run(cfg, say=print) -> dict:
    ext = Path(cfg.runtime_dir) / "external"
    ds = T.latest(ext)
    if ds is None:
        raise FileNotFoundError("no TrueData import")
    man = json.loads((ds / "manifest.json").read_text())
    rep = {"dataset": ds.name, "status": man["status"], "not_for": T.FORBIDDEN_NOTE, "symbols": {}}
    for sym in ("NIFTY", "BANKNIFTY"):
        d = daily(ds, sym)
        f = replay(d, sym)
        rep["symbols"][sym] = {"describe": describe(d), "context_2011_2023": history_context(sym, ext),
                               "hypotheses": hypotheses(d, sym), "replay": score(f, sym),
                               "predictions": int(len(f)), "resolved": int(f["outcome"].notna().sum())}
        say(f"  {sym}: {len(d)} sessions, {len(f)} replay predictions")
    hp = [h for s in rep["symbols"].values() for h in s["hypotheses"]]
    flags = edges.benjamini_hochberg([h["p"] for h in hp])
    for h, ok in zip(hp, flags):
        h["bh_pass_q10"] = bool(ok)
    try:
        rep["backtest"] = backtest_scenario(cfg, "2025-10-03")
    except Exception as exc:
        rep["backtest"] = {"status": f"failed: {exc!s:.200}"}
    (ds / "research.json").write_text(json.dumps(rep, indent=1, default=str))
    return rep


def render(rep: dict) -> str:
    def pct(x, d=1):
        return "—" if x is None or x != x else f"{x * 100:.{d}f}%"
    L = [f"# TrueData daily research · {rep['dataset']}", "",
         f"Data status **{rep['status']}** (every bar checked against Yahoo). {rep['not_for']}.", "",
         "Three kinds of result are kept apart below:",
         "- **Observed:** what the year looked like.",
         "- **Historical evidence:** the pre-registered rules re-measured, and a causal replay.",
         "- **Evidence of a profitable strategy:** none. Nothing here qualifies one.", "",
         "## 1. Observed: the year (3 Oct 2025 → 1 Oct 2026)", "",
         "| | NIFTY | BANKNIFTY | NIFTY 2010–23 | BANKNIFTY 2010–23 |", "|---|---|---|---|---|"]
    n, b = rep["symbols"]["NIFTY"], rep["symbols"]["BANKNIFTY"]
    nd, bd = n["describe"], b["describe"]
    nc, bc = n.get("context_2011_2023") or {}, b.get("context_2011_2023") or {}
    rows = [("Sessions", nd["sessions"], bd["sessions"], nc.get("sessions"), bc.get("sessions")),
            ("Total return", pct(nd["total_return"]), pct(bd["total_return"]), "", ""),
            ("Annualised volatility", pct(nd["ann_vol"]), pct(bd["ann_vol"]), pct(nc.get("ann_vol")), pct(bc.get("ann_vol"))),
            ("Max drawdown (close)", f"{pct(nd['max_drawdown'])} ({nd['max_drawdown_on']})", f"{pct(bd['max_drawdown'])} ({bd['max_drawdown_on']})", "", ""),
            ("Best / worst day", f"{pct(nd['best_day'][1])} {nd['best_day'][0]} / {pct(nd['worst_day'][1])} {nd['worst_day'][0]}",
             f"{pct(bd['best_day'][1])} {bd['best_day'][0]} / {pct(bd['worst_day'][1])} {bd['worst_day'][0]}", "", ""),
            ("Up days", pct(nd["up_days"]), pct(bd["up_days"]), pct(nc.get("up_days")), pct(bc.get("up_days"))),
            ("Mean high–low range", pct(nd["mean_range_pct"], 2), pct(bd["mean_range_pct"], 2), pct(nc.get("mean_range_pct"), 2), pct(bc.get("mean_range_pct"), 2)),
            ("Mean |opening gap|", pct(nd["mean_abs_gap_pct"], 2), pct(bd["mean_abs_gap_pct"], 2), pct(nc.get("mean_abs_gap_pct"), 2), pct(bc.get("mean_abs_gap_pct"), 2)),
            ("Trend days (body ≥ 60% of range)", pct(nd["trend_days"]), pct(bd["trend_days"]), pct(nc.get("trend_days")), pct(bc.get("trend_days"))),
            ("Range days (body ≤ 25% of range)", pct(nd["range_days"]), pct(bd["range_days"]), pct(nc.get("range_days")), pct(bc.get("range_days"))),
            ("Lag-1 autocorrelation (±95% band)", f"{nd['lag1_autocorr']:+.3f} (±{nd['lag1_band95']:.3f})", f"{bd['lag1_autocorr']:+.3f} (±{bd['lag1_band95']:.3f})",
             f"{nc.get('lag1_autocorr', float('nan')):+.3f}" if nc.get("lag1_autocorr") is not None else "", f"{bc.get('lag1_autocorr', float('nan')):+.3f}" if bc.get("lag1_autocorr") is not None else ""),
            ("Variance ratio (5) · z", f"{nd['variance_ratio_5'][0]:.2f} · {nd['variance_ratio_5'][1]:+.2f}", f"{bd['variance_ratio_5'][0]:.2f} · {bd['variance_ratio_5'][1]:+.2f}", "", ""),
            ("Hurst (log price)", f"{nd['hurst']:.2f}", f"{bd['hurst']:.2f}", "", ""),
            ("ADX(14) mean · share > 25", f"{nd['adx14_mean']:.1f} · {pct(nd['adx_above_25'])}", f"{bd['adx14_mean']:.1f} · {pct(bd['adx_above_25'])}", "", "")]
    for r in rows:
        L.append("| " + " | ".join(str(x) for x in r) + " |")
    L += ["", "## 2. Historical evidence: the pre-registered daily rules (research/edges.py)", "",
          "These rules were written before this data existed. research/edges.py also ran on Yahoo's full history, which "
          "contains these same prices, so this is a re-measurement of the latest year, not a fresh out-of-sample test. "
          "The cost hurdle is one lot of a 0.35Δ option, in index points. BH = Benjamini-Hochberg across all 10 tests.", "",
          "| rule | index | trades | mean (bps) | mean (pts) | t (HAC) | p | hurdle (pts) | BH q<0.10 |", "|---|---|---|---|---|---|---|---|---|"]
    for sym in ("NIFTY", "BANKNIFTY"):
        for h in rep["symbols"][sym]["hypotheses"]:
            L.append(f"| {h['id']} {HYPOTHESES.get(h['id'], '')} | {sym} | {h['n']} | {h['effect_bps']:+.1f} | {h['effect_pts']:+.1f} | "
                     f"{h['t']:+.2f} | {h['p']:.3f} | {h['hurdle_pts']:.1f} | {'yes' if h.get('bh_pass_q10') else 'no'} |")
    L += ["", "## 3. Historical evidence: causal replay through a prediction ledger", "",
          "Every call is written at 09:15 IST from closes up to the day before and that day's open. Its outcome (open → "
          "close) is attached only after the 15:30 close. A test proves that rewriting future prices never changes an "
          "earlier call. Net = signed index points minus the option cost hurdle. Balanced accuracy is 0.5 by definition "
          "for a rule that only ever says 'up'. No rule emits a probability, so calibration does not apply.", "",
          "| rule | index | calls | accuracy (95% CI) | balanced acc. | mean pts | net pts / call | max DD (pts) | t | sample |",
          "|---|---|---|---|---|---|---|---|---|---|"]
    for sym in ("NIFTY", "BANKNIFTY"):
        for rule, s in sorted(rep["symbols"][sym]["replay"].items()):
            L.append(f"| {rule} | {sym} | {s['n']} | {s['accuracy']:.1%} ({s['accuracy_ci95'][0]:.0%}–{s['accuracy_ci95'][1]:.0%}) | "
                     f"{s['balanced_accuracy']:.3f} | {s['mean_pts']:+.1f} | {s['net_pts_per_trade']:+.1f} | {s['max_drawdown_pts']:,.0f} | "
                     f"{s['t_hac']:+.2f} | {'**too small**' if s['insufficient'] else 'ok'} |")
    L += ["", "By volatility regime (rv20 terciles of the year, computed only from prior closes). Each cell is n / accuracy "
          "/ mean pts. Cells under 30 calls are flagged and shouldn't be read as results.", "",
          "| rule | index | low vol | mid vol | high vol |", "|---|---|---|---|---|"]
    for sym in ("NIFTY", "BANKNIFTY"):
        for rule, s in sorted(rep["symbols"][sym]["replay"].items()):
            cells = []
            for band in ("low vol", "mid vol", "high vol"):
                c = s["by_regime"].get(band, {})
                cells.append("—" if not c.get("n") else f"{c['n']} / {c['accuracy']:.0%} / {c['mean_pts']:+.0f}{' ⚠' if c['insufficient'] else ''}")
            L.append(f"| {rule} | {sym} | " + " | ".join(cells) + " |")
    bt = rep.get("backtest", {})
    L += ["", "## 4. The existing daily backtester", "", f"- Status: {bt.get('status')}.",
          f"- Strategies: {', '.join(bt.get('strategies', []))}. Trades: {bt.get('trades', 0)}.",
          f"- Why: {bt.get('note', '')} (warm-up {bt.get('warmup_bars')} sessions, data {bt.get('sessions')}).",
          "- The equity strategies (trend_rider, breakout, mean_reversion, momentum, pairs) have no data here: the export "
          "holds only the two indices.", "",
          "## Limits", "",
          "- One year of **daily** bars, two indices. No intraday files were uploaded yet (1-minute, 5-minute, tick), so "
          "nothing here says anything about intraday behaviour.",
          "- The export's four trailing columns are zero in every row, so there is no volume or open interest.",
          "- Index candles are not option prices, bid/ask, IV, trade-by-trade footprint, aggressor volume or depth.",
          "- About 50 calls per rule-year: an accuracy's 95% interval is about ±14 points wide. A real 55% edge can't be "
          "told from 50% in one year of daily data.", ""]
    return "\n".join(L)
