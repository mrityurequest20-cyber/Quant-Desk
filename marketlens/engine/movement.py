"""How an instrument moves, not where: range, gaps, compression and participation. Nothing here says up or down.

Inputs are daily OHLC (NSE's index close file for indices; NSE's cash bhavcopy for stocks, with volume, trades and
delivery). NSE's own previous close is NOT adjusted for bonuses and splits (Reliance's 1:1 bonus, 28 Oct 2024: previous
close 2,655.70, open 1,337), so the app's own split list rescales prices and volumes before each split, and a
demerger day is left out of every statistic.

  * ATR(14) as a share of price, and range-based vol estimators beside close-to-close: Parkinson (high-low),
    Garman-Klass (adds open-close) and Yang-Zhang (adds the overnight gap). Their gap to close-to-close says how much
    the day's swings exceed where it settles.
  * Overnight against intraday: the share of variance from the gap (previous close to open) against the session
    (open to close). Option sellers hold the overnight part with no chance to hedge.
  * Compression: the 20-day high-low range and Bollinger band width, each ranked against the past year, and NR7 (the
    narrowest range of seven sessions). The folk rule "compression precedes expansion" is TESTED, against what the
    options already priced: is the realised vol of the next 10 sessions, as a share of the 30-day IV that day, any
    different after compressed days?
  * Participation (stocks): volume as a z-score against 63 sessions (log scale), delivery % and its rank, and
    Amihud illiquidity (absolute return per rupee crore traded).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .breadth import rank_1y


def prepare(ohlc: pd.DataFrame, splits=(), drop_days=()) -> pd.DataFrame:
    """Daily OHLC (+ volume, turnover, deliv_pct when there) indexed by date, split-adjusted. `splits`: [{date, ratio}]
    as vol.adjust_splits reports them (ratio = shares after / before); `drop_days`: dates whose move is not the
    market's (a demerger)."""
    d = ohlc.sort_index().copy()
    for sp in splits:
        before = d.index < pd.Timestamp(sp["date"])
        for c in ("open", "high", "low", "close", "prev_close"):
            if c in d:
                d.loc[before, c] = d.loc[before, c] / sp["ratio"]
        if "volume" in d:
            d.loc[before, "volume"] = d.loc[before, "volume"] * sp["ratio"]
    # the previous close: NSE's own where the file has it (it already reflects a session the series lacks, such as
    # the Budget Sunday of 1 Feb 2026), with the split ratio applied on a split day itself (NSE does not adjust it);
    # the series' own previous row otherwise (indices)
    d["pc"] = d["close"].shift()
    if "prev_close" in d:
        pc = d["prev_close"].copy()
        for sp in splits:
            day = pd.Timestamp(sp["date"])
            if day in pc.index:
                pc.loc[day] = pc.loc[day] / sp["ratio"]
        d["pc"] = pc.where(pc > 0, d["pc"])
    d.loc[d.index.isin(pd.to_datetime(list(drop_days))), ["pc"]] = np.nan
    return d


def measures(d: pd.DataFrame) -> pd.DataFrame:
    """Daily measures (columns) from prepare()'s frame."""
    o, h, l, c, pc = (d[x] for x in ("open", "high", "low", "close", "pc"))
    out = pd.DataFrame(index=d.index)
    ok = (o > 0) & (h > 0) & (l > 0) & (c > 0) & (h >= l)
    tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1) / pc
    out["atr14"] = tr.where(ok).rolling(14, min_periods=10).mean()
    rc = np.log(c / pc).where(ok)                                # close to close
    ro = np.log(o / pc).where(ok)                                # overnight
    ri = np.log(c / o).where(ok)                                 # the session
    hl, co = np.log(h / l).where(ok), np.log(c / o).where(ok)
    hc, ho, lc, lo = np.log(h / c), np.log(h / o), np.log(l / c), np.log(l / o)
    W, A = 21, 252
    out["cc21"] = rc.rolling(W, min_periods=15).std() * np.sqrt(A)
    out["pk21"] = np.sqrt((hl ** 2 / (4 * np.log(2))).rolling(W, min_periods=15).mean() * A)
    gk = 0.5 * hl ** 2 - (2 * np.log(2) - 1) * co ** 2
    out["gk21"] = np.sqrt(gk.rolling(W, min_periods=15).mean().clip(lower=0) * A)
    rs = (ho * hc + lo * lc).where(ok)                           # Rogers-Satchell, the intraday part of Yang-Zhang
    k = 0.34 / (1.34 + (W + 1) / (W - 1))
    yz = ro.rolling(W, min_periods=15).var() + k * ri.rolling(W, min_periods=15).var() + (1 - k) * rs.rolling(W, min_periods=15).mean()
    out["yz21"] = np.sqrt(yz.clip(lower=0) * A)
    vo, vi = ro.rolling(63, min_periods=40).var(), ri.rolling(63, min_periods=40).var()
    out["ovn_share"] = vo / (vo + vi)
    out["gap"] = ro
    rng20 = (h.rolling(20, min_periods=15).max() - l.rolling(20, min_periods=15).min()) / c
    out["rng20"] = rng20
    sd = c.rolling(20, min_periods=15).std()
    out["bbw"] = 4 * sd / c.rolling(20, min_periods=15).mean()
    span = h - l
    out["nr7"] = (span <= span.rolling(7, min_periods=7).min()) & ok
    out["rng20_rank"] = rank_1y(out["rng20"])
    out["bbw_rank"] = rank_1y(out["bbw"])
    if "volume" in d:
        lv = np.log(d["volume"].where(d["volume"] > 0))
        out["vol_z"] = (lv - lv.rolling(63, min_periods=40).mean().shift()) / lv.rolling(63, min_periods=40).std().shift()
    if "deliv_pct" in d:
        out["deliv"] = d["deliv_pct"] / 100
        out["deliv_rank"] = rank_1y(out["deliv"])
    if "turnover_lacs" in d:
        cr = d["turnover_lacs"] / 100                            # lakh -> crore
        out["amihud"] = (rc.abs() / cr.where(cr > 0)).rolling(63, min_periods=40).median() * 1e4      # bp per Rs crore
        out["amihud_rank"] = rank_1y(out["amihud"])
    out["ret"] = rc
    return out


def compression_study(m: pd.DataFrame, iv30: pd.Series, n_perm: int = 2000, horizon: int = 10) -> dict | None:
    """After a compressed day (20-day range in the bottom fifth of its past year), was the realised vol of the next
    `horizon` sessions any larger, as a share of the 30-day IV that day (what options priced), than after other days?
    Medians of the two, and a permutation p for 'larger after compression'. Raw ratios are kept to show what the
    folk rule sees without the IV."""
    fwd = m["ret"].rolling(horizon, min_periods=int(horizon * 0.8)).std().shift(-horizon) * np.sqrt(252)
    d = pd.DataFrame({"comp": m["rng20_rank"] <= 0.2, "rank": m["rng20_rank"], "fwd": fwd, "iv": iv30.reindex(m.index),
                      "now": m["cc21"]}).dropna()
    d = d[(d["iv"] > 0) & (d["now"] > 0)]
    c = d["comp"].to_numpy()
    if c.sum() < 30 or (~c).sum() < 30:
        return None
    z = (d["fwd"] / d["iv"]).to_numpy()
    raw = (d["fwd"] / d["now"]).to_numpy()                     # the folk view: next vol against the recent vol
    gap = np.median(z[c]) - np.median(z[~c])
    rng = np.random.default_rng(0)
    # a compressed stretch lasts days: permute in blocks of 21 sessions, not single days, so the p is not too small
    blocks = np.arange(len(c)) // 21
    ub = np.unique(blocks)
    hits = 0
    for _ in range(n_perm):
        sh = rng.permutation(ub)
        m_ = np.concatenate([c[blocks == b] for b in sh])[:len(c)]
        hits += np.median(z[m_]) - np.median(z[~m_]) >= gap
    return {"n_comp": int(c.sum()), "n_other": int((~c).sum()), "since": str(d.index.min().date()), "horizon": horizon,
            "z_comp": float(np.median(z[c])), "z_other": float(np.median(z[~c])),
            "raw_comp": float(np.median(raw[c])), "raw_other": float(np.median(raw[~c])), "p": hits / n_perm}
