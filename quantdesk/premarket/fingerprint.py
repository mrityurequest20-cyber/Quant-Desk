"""The market fingerprint (docs/EVOLUTION.md, phase 1; the owner, 14 Nov 2026: "The way we see market today, market may not behave the same way 2 months later, 3 months
later, a year later. How our trading desk is going to evolve in that process?").

Every morning, a short description of what KIND of market it is, from the same years of daily closes the tail models read (premarket/tailrisk.py), so that every trade
the desk takes (in shadow or with paper money) can be tagged with the market it was taken in, and the desk can later learn which strategies work in which markets:

* VOLATILITY: NIFTY's 20-session realized volatility, and its percentile against the last three years. Low under the 33rd, high over the 80th.
* ITS TREND: that volatility against the same measure 20 sessions earlier (rising or falling).
* DIRECTION: NIFTY's 60-session log move in its own daily standard deviations (sqrt(60) of them): up or down past TREND_T, else a range.
* CHOP: the 5-session variance ratio over a year (under 1: moves reverse; over 1: they persist).
* HERDING: the average pairwise correlation of the desk's stocks' daily moves over 60 sessions; DISPERSION: the spread of their 20-session moves.
* STRESS: NIFTY's distance from its one-year high, and the days of the last 60 that moved more than 2.5 of its one-year daily standard deviations.
* CROSS-ASSET: crude oil's and the rupee's volatility percentiles.
The brief adds what it alone knows: the overnight markets (US VIX, the dollar, US yields) and the events of the next five days.

The KEY is a coarse, transparent regime: volatility (low / normal / high) and direction (up / down / range): nine regimes, on purpose few, so that each collects enough
trades to say something. It is a description, not a forecast; nothing here trades. Later phases measure the strategies by regime (phase 3), look for breaks in the
fingerprint (phase 4) and fingerprint the past (phase 5) from this same function.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

VOL_N, VOL_LOOKBACK = 20, 756              # realized volatility over 20 sessions; its percentile over three years
VOL_LOW, VOL_HIGH = 0.33, 0.80             # the percentiles that bound "normal" volatility
TREND_N, TREND_T = 60, 1.5                 # the direction: a 60-session move of 1.5 of its own standard deviations
VR_Q, VR_N = 5, 250                        # the variance ratio: 5-session against 1-session variance over a year
CORR_N, HERD = 60, 0.5                     # herding: the stocks' average pairwise correlation over 60 sessions
DISP_N = 20
TAIL_K, TAIL_N = 2.5, 60
MIN_OBS = VOL_LOOKBACK // 2                # a fingerprint needs a year and a half of NIFTY
HISTORY = 60                               # the keys of the last sessions, for "since"
ANNUAL = math.sqrt(252)
INDICES = ("NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "NIFTYNXT50", "SENSEX", "BANKEX")
NON_EQUITY = ("CRUDEOIL", "CRUDEOILM", "NATURALGAS", "NATGASMINI", "GOLD", "GOLDM", "SILVER", "SILVERM", "COPPER", "USDINR", "EURINR", "GBPINR", "JPYINR")


def _closes(s) -> pd.Series | None:
    if s is None:
        return None
    s = pd.to_numeric(pd.Series(s), errors="coerce").dropna()
    s = s[s > 0]
    s.index = pd.DatetimeIndex(s.index).tz_localize(None) if getattr(pd.DatetimeIndex(s.index), "tz", None) is not None else pd.DatetimeIndex(s.index)
    return s.sort_index()


def _vol_series(r: pd.Series) -> pd.Series:
    return r.rolling(VOL_N).std() * ANNUAL


def _pct(series: pd.Series, at) -> float | None:
    """The percentile of the value at `at` among the VOL_LOOKBACK values up to it."""
    win = series.loc[:at].dropna().iloc[-VOL_LOOKBACK:]
    if len(win) < VOL_N * 3:
        return None
    return float((win < win.iloc[-1]).mean())


def vol_bucket(pct: float | None) -> str | None:
    if pct is None:
        return None
    return "low" if pct < VOL_LOW else "high" if pct > VOL_HIGH else "normal"


def direction(trend_t: float | None) -> str | None:
    if trend_t is None:
        return None
    return "up" if trend_t >= TREND_T else "down" if trend_t <= -TREND_T else "range"


def _key_at(close: pd.Series, r: pd.Series, vol: pd.Series, at) -> tuple[str | None, float | None, float | None]:
    """(key, volatility percentile, trend t) of the market as it stood at the close of `at`."""
    pct = _pct(vol, at)
    upto = close.loc[:at]
    rr = r.loc[:at].dropna()
    trend = None
    if len(upto) > TREND_N and len(rr) >= VR_N:
        sd = float(rr.iloc[-VR_N:].std())
        if sd > 0:
            trend = float(math.log(upto.iloc[-1] / upto.iloc[-1 - TREND_N]) / (sd * math.sqrt(TREND_N)))
    vb, dr = vol_bucket(pct), direction(trend)
    return (f"{vb}/{dr}" if vb and dr else None), pct, trend


def variance_ratio(r: pd.Series, q: int = VR_Q) -> float | None:
    r = r.dropna()
    if len(r) < q * 10:
        return None
    v1 = float(r.var())
    vq = float(r.rolling(q).sum().dropna().var())
    return vq / (q * v1) if v1 > 0 else None


def compute(series: dict, asof=None) -> dict | None:
    """The fingerprint at the close of `asof` (default: NIFTY's last close) from {u: daily closes} (a Series, or a (Series, source) pair as tailrisk gives it).
    None when NIFTY has under MIN_OBS sessions."""
    ss = {u: _closes(v[0] if isinstance(v, tuple) else v) for u, v in (series or {}).items()}
    close = ss.get("NIFTY")
    if close is None or len(close) < MIN_OBS:
        return None
    if asof is not None:
        close = close.loc[:pd.Timestamp(asof)]
        if len(close) < MIN_OBS:
            return None
    at = close.index[-1]
    r = np.log(close / close.shift())
    vol = _vol_series(r)
    key, pct, trend = _key_at(close, r, vol, at)
    feats: dict = {"vol20": round(float(vol.loc[at]), 4) if pd.notna(vol.loc[at]) else None, "vol_pct": None if pct is None else round(pct, 3),
                   "trend_t": None if trend is None else round(trend, 2)}
    v20 = vol.dropna()
    if len(v20) > VOL_N:
        feats["vol_change"] = round(float(v20.iloc[-1] / v20.iloc[-1 - VOL_N] - 1), 3) if v20.iloc[-1 - VOL_N] > 0 else None
    vr = variance_ratio(r.iloc[-VR_N:])
    feats["vr5"] = None if vr is None else round(vr, 3)
    hi = float(close.iloc[-252:].max())
    feats["drawdown"] = round(float(close.iloc[-1] / hi - 1), 4)
    sd_y = float(r.dropna().iloc[-252:].std())
    feats["tail_days"] = int((r.dropna().iloc[-TAIL_N:].abs() > TAIL_K * sd_y).sum()) if sd_y > 0 else None
    stocks = {u: s.loc[:at] for u, s in ss.items() if s is not None and u not in INDICES and u not in NON_EQUITY and len(s.loc[:at]) > CORR_N + 1}
    if len(stocks) >= 4:
        rets = pd.DataFrame({u: np.log(s / s.shift()) for u, s in stocks.items()}).loc[:at].iloc[-CORR_N:].dropna(axis=1, thresh=int(CORR_N * 0.8))
        if rets.shape[1] >= 4:
            c = rets.corr().values
            n = c.shape[0]
            feats["corr"] = round(float((c.sum() - n) / (n * (n - 1))), 3)
            moves = [math.log(s.iloc[-1] / s.iloc[-1 - DISP_N]) for s in stocks.values() if len(s) > DISP_N]
            feats["dispersion"] = round(float(np.std(moves)), 4) if len(moves) >= 4 else None
            feats["stocks"] = int(rets.shape[1])
    for u, name in (("CRUDEOIL", "crude_vol_pct"), ("USDINR", "rupee_vol_pct")):
        s = ss.get(u)
        if s is not None and len(s.loc[:at]) > VOL_N * 3:
            s = s.loc[:at]
            feats[name] = _pct(_vol_series(np.log(s / s.shift())), s.index[-1])
    hist = []
    for d in close.index[-HISTORY:]:
        k, _, _ = _key_at(close, r, vol, d)
        hist.append([str(d.date()), k])
    since = None
    for d, k in reversed(hist):
        if k != key:
            break
        since = d
    return {"asof": str(at.date()), "key": key, "label": label(key, feats), "since": since, "features": feats, "history": hist[-20:]}


def label(key: str | None, f: dict) -> str:
    """The fingerprint in words."""
    if not key:
        return "not enough history"
    vb, dr = key.split("/")
    parts = [f"{vb} volatility" + (f" ({f['vol_pct'] * 100:.0f}th percentile)" if f.get("vol_pct") is not None else ""),
             {"up": "trending up", "down": "trending down", "range": "in a range"}[dr]]
    vc = f.get("vol_change")
    if vc is not None and abs(vc) >= 0.25:
        parts.append("volatility rising" if vc > 0 else "volatility falling")
    if f.get("vr5") is not None and f["vr5"] < 0.85:
        parts.append("choppy (moves reverse)")
    if f.get("corr") is not None:
        parts.append("stocks moving together" if f["corr"] >= HERD else "stocks moving their own ways")
    if f.get("drawdown") is not None and f["drawdown"] <= -0.10:
        parts.append(f"{-f['drawdown'] * 100:.0f}% below its one-year high")
    return ", ".join(parts)


def with_brief(fp: dict | None, globals_: list | None, calendar: list | None) -> dict | None:
    """The fingerprint with what only the brief knows: the overnight markets (US VIX, the dollar, US 10-year yield) and the events of the next five days."""
    if not fp:
        return fp
    g = {x.get("key"): x for x in globals_ or [] if isinstance(x, dict)}
    f = dict(fp["features"])
    if "USVIX" in g and g["USVIX"].get("last") is not None:
        f["us_vix"] = round(float(g["USVIX"]["last"]), 2)
    if "DXY" in g and g["DXY"].get("change") is not None:
        f["dollar_change"] = round(float(g["DXY"]["change"]), 4)
    if "UST10" in g and g["UST10"].get("last") is not None:
        f["us10y"] = round(float(g["UST10"]["last"]), 3)
    f["events_5d"] = sum(1 for e in calendar or [] if isinstance(e, dict) and e.get("impact") in ("high", "medium"))
    return {**fp, "features": f}


def summary_line(fp: dict | None) -> str | None:
    if not fp or not fp.get("key"):
        return None
    return f"Market: {fp['label']}" + (f"; this regime ({fp['key']}) since {fp['since']}" if fp.get("since") else "") + "."
