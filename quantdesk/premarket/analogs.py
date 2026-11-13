"""What each instrument did on past episodes like this one, in markets like this one (owner, 13 Nov 2026: "The news analyser must ... understand past and present
situations well so that it can accurately predict the future ... Models should read differently as per the instrument").

history.macro_history measures NIFTY and BANKNIFTY on every past episode of a kind (an RBI decision, an FOMC, a budget, an election, a geopolitical shock, an oil shock),
all episodes alike. Two refinements here:

* EVERY INSTRUMENT on its own: gold, crude, USD/INR and a bank each answer an oil shock differently, so each is measured on its own daily history (the same series the
  tail models use: tailrisk.series_for).
* THE SITUATION: an RBI hike into a falling, frightened market is not an RBI hike into a calm rally. Each past episode is described by the market the day before it: its
  20-session trend (in standard deviations), its volatility against its own previous year (log ratio), and its drawdown from the 60-session high. Today is described the
  same way, and each episode is weighted by its similarity, w = exp(-d^2 / 2) with d the distance in units of each feature's spread. The weighted share of rises is the
  analogue's P(up); n_eff = (sum w)^2 / sum w^2 says how many episodes it really rests on, and the news model (paper/newsmodel.py) trusts it accordingly.

Pure functions (pandas); fitted once a morning with the tail models.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from . import history as H

FEATURES = ("trend20", "vol_ratio", "dd60")
MIN_DAYS = 300


def situation(close: pd.Series) -> pd.DataFrame:
    """The market as it stood at each day's CLOSE: 20-session trend in standard deviations, volatility against its own past year, drawdown from the 60-session high."""
    c = close.astype(float)
    r = np.log(c / c.shift())
    sd20 = r.rolling(20).std()
    return pd.DataFrame({
        "trend20": np.log(c / c.shift(20)) / (sd20 * math.sqrt(20)),
        "vol_ratio": np.log(sd20 / sd20.rolling(250, min_periods=120).median()),
        "dd60": np.log(c / c.rolling(60).max()),
    }, index=c.index)


def for_instrument(close: pd.Series, dates: dict, today: pd.Series | None = None) -> dict:
    """{kind: {n, n_eff, p_up, median_ret, mean_ret_w, worst, ret5_w, nearest: [(date, similarity, ret)]}} for one instrument's daily closes."""
    close = close.dropna().sort_index()
    close = close[close > 0]
    if len(close) < MIN_DAYS:
        return {}
    close.index = pd.DatetimeIndex(close.index).tz_localize(None) if getattr(close.index, "tz", None) is not None else pd.DatetimeIndex(close.index)
    raw = situation(close)
    f = raw.shift(1)                                                  # an event day is described by the market at the close BEFORE it
    now = today if today is not None else raw.iloc[-1]                # today: the market at the last close
    spread = f.std()
    ret = np.log(close / close.shift())
    ret5 = np.log(close.shift(-4) / close.shift())
    idx = close.index
    out = {}
    for kind, spec in dates.get("kinds", {}).items():
        days = pd.to_datetime(spec.get("dates", []))
        k = idx.searchsorted(days, side="right" if spec.get("reacts") == "next_session" else "left")
        hit = sorted({idx[i] for i in k if 0 < i < len(idx)})
        rows = []
        for d in hit:
            x, y, y5 = f.loc[d], ret.loc[d], ret5.loc[d]
            if not np.isfinite(y) or x.isna().any() or now.isna().any():
                continue
            dist2 = float(sum(((x[c] - now[c]) / spread[c]) ** 2 for c in FEATURES if spread[c] > 0))
            rows.append((d, math.exp(-dist2 / 2), float(y), float(y5) if np.isfinite(y5) else None))
        if not rows:
            continue
        w = np.array([r[1] for r in rows])
        y = np.array([r[2] for r in rows])
        sw = w.sum()
        if sw <= 0:
            continue
        y5 = [(r[1], r[3]) for r in rows if r[3] is not None]
        near = sorted(rows, key=lambda r: -r[1])[:3]
        out[kind] = {"n": len(rows), "n_eff": round(float(sw ** 2 / (w ** 2).sum()), 2), "p_up": round(float((w * (y > 0)).sum() / sw), 3),
                     "median_ret": round(float(np.median(y)), 5), "mean_ret_w": round(float((w * y).sum() / sw), 5), "worst": round(float(y.min()), 5),
                     "ret5_w": round(sum(a * b for a, b in y5) / sum(a for a, _ in y5), 5) if y5 and sum(a for a, _ in y5) > 0 else None,
                     "nearest": [[str(d.date()), round(s, 3), round(r, 5)] for d, s, r, _ in near]}
    return out


def build(series: dict, dates: dict | None = None) -> dict:
    """{kind: {instrument: for_instrument(...)[kind]}} over every instrument's daily closes (series: {u: pd.Series})."""
    dates = dates or H.macro_dates()
    out: dict = {}
    for u, s in series.items():
        if s is None:
            continue
        for kind, v in for_instrument(s, dates).items():
            out.setdefault(kind, {})[u] = v
    return out
