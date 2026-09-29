"""Edge research: a fixed list of hypotheses about NIFTY and BANKNIFTY, tested on real data with the
statistics that stop a researcher fooling themselves.

Rules (fixed before looking at the data, so the list can't be tuned to what happened to work):
  * every hypothesis is stated as "trade in direction D over window W": the effect is the average
    signed index return per trade, in basis points and in index points;
  * t-statistics are Newey-West (HAC), so autocorrelated or overlapping observations don't inflate them;
  * discovery = the older 2/3 of the sample, holdout = the newest 1/3; an edge must keep its sign
    in the holdout (one-sided p < 0.10);
  * Benjamini-Hochberg false-discovery control (q = 0.10) across every test run;
  * the cost hurdle: what one lot of a 0.35Δ index option costs to get in and out (brokerage, STT,
    exchange, GST, stamp, the bid/ask) expressed in index points. Under fair (business-time) option
    pricing theta is paid for by gamma, so the directional edge must beat the costs.

Verdicts: EDGE (survives all of it), REAL BUT BELOW COSTS, NEEDS MARGIN (real, but only a premium
seller can harvest it, which a ₹20k account can't), NO EDGE.
"""
from __future__ import annotations

import datetime as dt
import json
import math
from dataclasses import asdict, dataclass, field

import numpy as np
import pandas as pd
from scipy import stats

IST = "Asia/Kolkata"
# round trip for one lot of a 0.35Δ weekly/monthly option, in index points (₹96 NIFTY / ₹100 BANKNIFTY, see EVEngine)
COST_POINTS = {"NIFTY": 96 / (65 * 0.35), "BANKNIFTY": 100 / (30 * 0.35)}
LOT = {"NIFTY": 65, "BANKNIFTY": 30}
DELTA = 0.35


@dataclass
class Result:
    id: str
    symbol: str
    hypothesis: str
    data: str
    n: int
    effect_bps: float
    effect_pts: float
    t: float
    p: float
    effect_holdout_bps: float = float("nan")
    p_holdout: float = float("nan")
    hurdle_pts: float = float("nan")
    kind: str = "directional"             # directional | premium (needs a seller)
    sd_pts: float = float("nan")          # per-trade σ of the index move, points
    capital_half_kelly: float = float("nan")   # account size at which ONE lot of a 0.35Δ option is a half-Kelly bet
    bh_pass: bool = False
    verdict: str = ""
    note: str = ""
    params: dict = field(default_factory=dict)


# ---- statistics ---------------------------------------------------------------------------------------------------
def hac_mean(x: np.ndarray, lags: int | None = None) -> tuple[float, float, float]:
    """Mean, Newey-West t and two-sided p for the mean of x."""
    x = np.asarray(x, dtype=float)
    x = x[np.isfinite(x)]
    n = len(x)
    if n < 8:
        return float("nan"), float("nan"), float("nan")
    lags = int(lags if lags is not None else max(1, math.floor(4 * (n / 100) ** (2 / 9))))
    m = x.mean()
    e = x - m
    s = e @ e / n
    for k in range(1, min(lags, n - 1) + 1):
        w = 1 - k / (lags + 1)
        s += 2 * w * (e[k:] @ e[:-k]) / n
    se = math.sqrt(max(s, 1e-30) / n)
    t = m / se
    return float(m), float(t), float(2 * stats.t.sf(abs(t), n - 1))


def benjamini_hochberg(pvals: list[float], q: float = 0.10) -> list[bool]:
    p = np.array([x if x == x else 1.0 for x in pvals])
    order = np.argsort(p)
    m = len(p)
    thresh = q * (np.arange(1, m + 1)) / m
    passed = p[order] <= thresh
    k = np.max(np.where(passed)[0]) + 1 if passed.any() else 0
    out = np.zeros(m, dtype=bool)
    out[order[:k]] = True
    return out.tolist()


def _split(x: pd.Series):
    x = x.dropna()
    cut = int(len(x) * 2 / 3)
    return x.iloc[:cut], x.iloc[cut:]


def evaluate(rid, symbol, hypothesis, data, signed_returns: pd.Series, price: float, lags=None, kind="directional",
             note="", params=None) -> Result:
    """`signed_returns`: per-trade log returns already signed by the trade direction (a series indexed by time)."""
    x = signed_returns.dropna()
    m, t, p = hac_mean(x.to_numpy(), lags)
    disc, hold = _split(x)
    md, _, _ = hac_mean(disc.to_numpy(), lags)
    mh, th, ph2 = hac_mean(hold.to_numpy(), lags)
    one_sided = ph2 / 2 if (mh == mh and md == md and np.sign(mh) == np.sign(md)) else 1 - (ph2 / 2 if ph2 == ph2 else 0)
    r = Result(rid, symbol, hypothesis, data, int(len(x)), m * 1e4, m * price, t, p, mh * 1e4, one_sided,
               COST_POINTS.get(symbol, float("nan")), kind, note=note, params=params or {})
    r.sd_pts = float(x.std() * price)
    net = abs(r.effect_pts) - r.hurdle_pts
    if kind == "directional" and net > 0 and symbol in LOT:
        # one lot of a 0.35Δ option moves ≈ Δ × lot rupees per index point; Kelly fraction f* = μ/σ² of the account
        mu, sd = net * DELTA * LOT[symbol], r.sd_pts * DELTA * LOT[symbol]
        r.capital_half_kelly = float(2 * sd * sd / mu)
    return r


# ---- data ---------------------------------------------------------------------------------------------------------
def _ist(df: pd.DataFrame) -> pd.DataFrame:
    df = df.rename(columns={c: str(c).lower() for c in df.columns})
    idx = pd.DatetimeIndex(df.index)
    df.index = idx.tz_localize(IST) if idx.tz is None else idx.tz_convert(IST)
    return df[["open", "high", "low", "close"] + (["volume"] if "volume" in df else [])].astype(float)


def load_yahoo(symbols=("NIFTY", "BANKNIFTY")) -> dict:
    import yfinance as yf
    tick = {"NIFTY": "^NSEI", "BANKNIFTY": "^NSEBANK", "INDIAVIX": "^INDIAVIX"}
    out = {"daily": {}, "hourly": {}, "m5": {}}
    for s in list(symbols) + ["INDIAVIX"]:
        t = yf.Ticker(tick[s])
        out["daily"][s] = _ist(t.history(period="max", interval="1d", auto_adjust=False)).dropna(subset=["close"])
        if s == "INDIAVIX":
            continue
        out["hourly"][s] = _ist(t.history(period="730d", interval="1h", auto_adjust=False)).dropna(subset=["close"])
        out["m5"][s] = _ist(t.history(period="60d", interval="5m", auto_adjust=False)).dropna(subset=["close"])
    return out


def _session(df: pd.DataFrame) -> pd.DataFrame:
    t = df.index.time
    return df[(t >= dt.time(9, 15)) & (t < dt.time(15, 30))]


# ---- the hypotheses -----------------------------------------------------------------------------------------------
def daily_tests(sym: str, d: pd.DataFrame, vix: pd.DataFrame | None) -> list[Result]:
    d = d[d["open"] > 0].copy()
    d["r_oc"] = np.log(d["close"] / d["open"])                       # the part an intraday trader can hold
    d["gap"] = np.log(d["open"] / d["close"].shift(1))
    d["r_cc"] = np.log(d["close"] / d["close"].shift(1))
    px = float(d["close"].iloc[-1])
    out = [evaluate("D1", sym, "Intraday drift: long from the open to the close, every day", "daily", d["r_oc"], px)]
    g = d[d["gap"].abs() > 0.003]
    out.append(evaluate("D2", sym, "Gap continuation: after a gap > 0.3%, trade in the gap's direction open→close",
                        "daily", np.sign(g["gap"]) * g["r_oc"], px, params={"min_gap": 0.003}))
    big = d["r_cc"].shift(1) < -0.015
    out.append(evaluate("D3", sym, "Rebound: the day after a close-to-close fall > 1.5%, long open→close", "daily",
                        d.loc[big, "r_oc"], px, params={"fall": -0.015}))
    tue = d.index.dayofweek == 1
    out.append(evaluate("D4", sym, "Tuesday (weekly expiry): long open→close on Tuesdays", "daily", d.loc[tue, "r_oc"], px))
    ym = d.index.tz_localize(None).to_period("M")
    pos = pd.Series(range(len(d)), index=d.index).groupby(ym).rank(method="first")
    size = pd.Series(1, index=d.index).groupby(ym).transform("size")
    tom = (pos <= 3) | (pos == size)
    out.append(evaluate("D5", sym, "Turn of the month (last day + first 3): long open→close", "daily", d.loc[tom, "r_oc"], px))
    if vix is not None and len(vix):
        v = vix["close"].reindex(d.index).ffill()
        spike = np.log(v / v.shift(1)) > 0.10
        out.append(evaluate("D6", sym, "After an India VIX jump > 10%: long the next day open→close", "daily",
                            d["r_oc"][spike.shift(1, fill_value=False).to_numpy()], px))
        if sym == "NIFTY":
            rv_fwd = d["r_cc"].rolling(21).std().shift(-21) * math.sqrt(252)
            vrp = (v / 100 - rv_fwd).dropna()
            r = evaluate("V1", sym, "Volatility risk premium: India VIX minus the next 21 days' realised vol", "daily",
                         vrp, px, lags=25, kind="premium",
                         note="in vol points ×100, not a return; harvested by selling options (margin)")
            r.effect_pts = float("nan")
            r.params = {"share_positive": round(float((vrp > 0).mean()), 3), "mean_vix": round(float(v.mean()), 2)}
            out.append(r)
    return out


def hourly_tests(sym: str, h: pd.DataFrame, daily: pd.DataFrame) -> list[Result]:
    h = _session(h)
    if h.empty:
        return []
    px = float(h["close"].iloc[-1])
    rows = []
    prev_close = daily["close"].copy()
    prev_close.index = prev_close.index.date
    pc = prev_close.shift(1)
    for day, g in h.groupby(h.index.date):
        if len(g) < 6:
            continue
        op = g["open"].iloc[0]
        first = g[g.index.time < dt.time(10, 15)]
        mid = g[(g.index.time >= dt.time(10, 15))]
        last = g[g.index.time >= dt.time(14, 15)]
        if first.empty or mid.empty or last.empty:
            continue
        c1015 = first["close"].iloc[-1]
        c1415 = g[g.index.time < dt.time(14, 15)]["close"].iloc[-1]
        close = g["close"].iloc[-1]
        prev = pc.get(day, np.nan)
        rows.append({"day": pd.Timestamp(day), "r_first": math.log(c1015 / op), "r_rest": math.log(close / c1015),
                     "r_on_first": math.log(c1015 / prev) if prev == prev else np.nan,
                     "r_day_to_1415": math.log(c1415 / op), "r_last": math.log(close / c1415)})
    x = pd.DataFrame(rows).set_index("day")
    return [
        evaluate("H1", sym, "First-hour momentum: trade the 09:15→10:15 direction from 10:15 to the close", "hourly",
                 np.sign(x["r_first"]) * x["r_rest"], px),
        evaluate("H2", sym, "Intraday momentum (Gao et al.): overnight + first hour predicts the last hour (14:15→close)",
                 "hourly", np.sign(x["r_on_first"]) * x["r_last"], px),
        evaluate("H3", sym, "Late-day trend: trade the open→14:15 direction into the close", "hourly",
                 np.sign(x["r_day_to_1415"]) * x["r_last"], px),
    ]


def m5_tests(sym: str, m: pd.DataFrame) -> list[Result]:
    m = _session(m)
    if m.empty:
        return []
    px = float(m["close"].iloc[-1])
    orb, vwap_rev, mom = [], [], []
    for day, g in m.groupby(m.index.date):
        if len(g) < 60:
            continue
        c, hi, lo = g["close"].to_numpy(), g["high"].to_numpy(), g["low"].to_numpy()
        orh, orl = hi[:6].max(), lo[:6].min()                              # 30-minute opening range
        exit_i = min(len(c) - 1, 71)                                        # ~15:15
        for i in range(6, exit_i):
            if c[i] > orh or c[i] < orl:
                d_ = 1 if c[i] > orh else -1
                orb.append((pd.Timestamp(g.index[i]), d_ * math.log(c[exit_i] / c[i])))
                break
        tp = (hi + lo + c) / 3
        vw = np.cumsum(tp) / np.arange(1, len(c) + 1)
        lr = np.r_[0, np.diff(np.log(c))]
        sd = pd.Series(lr).rolling(12, min_periods=6).std().to_numpy()
        for i in range(12, len(c) - 6, 6):                                 # non-overlapping 30-minute steps
            z = (c[i] / vw[i] - 1) / (sd[i] * math.sqrt(6)) if sd[i] and sd[i] == sd[i] else 0
            fwd = math.log(c[i + 6] / c[i])
            if abs(z) > 2:
                vwap_rev.append((pd.Timestamp(g.index[i]), -np.sign(z) * fwd))
            prev30 = math.log(c[i] / c[i - 6])
            mom.append((pd.Timestamp(g.index[i]), np.sign(prev30) * fwd))
    ser = lambda rows: pd.Series([r for _, r in rows], index=[t for t, _ in rows], dtype=float)
    return [
        evaluate("M1", sym, "Opening-range breakout: first 5m close outside the 30-min range, hold to 15:15", "5m", ser(orb), px),
        evaluate("M2", sym, "VWAP reversion: > 2σ from VWAP, fade it for 30 minutes", "5m", ser(vwap_rev), px),
        evaluate("M3", sym, "30-minute momentum: trade the last 30 minutes' direction for the next 30", "5m", ser(mom), px),
    ]


def run(data: dict, symbols=("NIFTY", "BANKNIFTY"), q: float = 0.10) -> list[Result]:
    res: list[Result] = []
    vix = data["daily"].get("INDIAVIX")
    for s in symbols:
        if s in data["daily"]:
            res += daily_tests(s, data["daily"][s], vix)
        if s in data.get("hourly", {}):
            res += hourly_tests(s, data["hourly"][s], data["daily"][s])
        if s in data.get("m5", {}):
            res += m5_tests(s, data["m5"][s])
    passed = benjamini_hochberg([r.p for r in res], q)
    for r, ok in zip(res, passed):
        r.bh_pass = bool(ok)
        holds = r.p_holdout == r.p_holdout and r.p_holdout < 0.10
        if not (ok and holds):
            r.verdict = "NO EDGE"
        elif r.kind == "premium":
            r.verdict = "NEEDS MARGIN" if r.effect_bps > 0 else "NO EDGE"
        elif abs(r.effect_pts) < r.hurdle_pts:
            r.verdict = "REAL BUT BELOW COSTS"
        else:
            r.verdict = "EDGE"
    return res


def report(res: list[Result], data: dict, generated: str) -> str:
    span = {k: {s: f"{df.index[0]:%d-%b-%Y} → {df.index[-1]:%d-%b-%Y} ({len(df):,} bars)" for s, df in v.items()}
            for k, v in data.items()}
    L = [f"# Edge research — NIFTY & BANKNIFTY", "", f"Generated {generated}. Data: Yahoo Finance.", ""]
    for k, v in span.items():
        for s, t in v.items():
            L.append(f"- {k} {s}: {t}")
    L += ["", f"{len(res)} pre-registered tests · Benjamini–Hochberg q = 0.10 · holdout = newest third · cost hurdle "
          f"NIFTY {COST_POINTS['NIFTY']:.1f} pts, BANKNIFTY {COST_POINTS['BANKNIFTY']:.1f} pts per round trip", "",
          "Effect/trade is for the side the test states; a negative effect means the edge is the *opposite* side.", "",
          "| Verdict | ID | Market | Hypothesis | N | Effect/trade | t | p | Holdout | BH |",
          "|---|---|---|---|---:|---:|---:|---:|---:|:-:|"]
    order = {"EDGE": 0, "NEEDS MARGIN": 1, "REAL BUT BELOW COSTS": 2, "NO EDGE": 3}
    for r in sorted(res, key=lambda r: (order.get(r.verdict, 9), r.p)):
        eff = (f"{r.effect_bps:+.1f} bps ({r.effect_pts:+.1f} pts)" if r.kind == "directional"
               else f"{r.effect_bps / 100:+.2f} vol pts")
        hold = f"{r.effect_holdout_bps:+.1f} bps, p {r.p_holdout:.2f}" if r.kind == "directional" else f"p {r.p_holdout:.2f}"
        L.append(f"| **{r.verdict}** | {r.id} | {r.symbol} | {r.hypothesis} | {r.n:,} | {eff} | {r.t:+.2f} | {r.p:.3f} | "
                 f"{hold} | {'✓' if r.bh_pass else '·'} |")
    notes = [r for r in res if r.note or r.params]
    if notes:
        L += ["", "Notes:"]
        for r in notes:
            L.append(f"- {r.id} {r.symbol}: {r.note} {json.dumps(r.params) if r.params else ''}".strip())
    edges = [r for r in res if r.verdict == "EDGE"]
    L += ["", "## Verdict", ""]
    if edges:
        L.append("Survived discovery, holdout, false-discovery control and the cost hurdle:")
        for r in edges:
            side = "as stated" if r.effect_pts > 0 else "**the opposite side** (the effect is negative)"
            L.append(f"- **{r.id} {r.symbol}**: {r.hypothesis}. Trade {side}: {abs(r.effect_pts):.1f} pts/trade vs "
                     f"{r.hurdle_pts:.1f} pts of costs (t {r.t:+.2f}, holdout {r.effect_holdout_bps:+.1f} bps). "
                     f"Per-trade σ {r.sd_pts:,.0f} pts, so one lot of a 0.35Δ option is a half-Kelly bet only on an account of "
                     f"about ₹{r.capital_half_kelly:,.0f}; smaller accounts are over-betting it.")
    else:
        L.append("Nothing survived every test. Trading any of these would be trading noise; the desk won't.")
    return "\n".join(L) + "\n"


def to_json(res: list[Result]) -> str:
    return json.dumps([{k: (None if isinstance(v, float) and v != v else v) for k, v in asdict(r).items()} for r in res], indent=1)
