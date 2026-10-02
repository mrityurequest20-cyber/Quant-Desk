"""ATM IV in context: where today's ATM implied vol sits against the past year's, at the same days to expiry.

Short-dated IV has a strong days-to-expiry shape (the last sessions before an expiry price differently from a
week out), so ranking today against every past day would mix the two. The history is the ATM IV of the nearest
expiry at least `min_days` out at each session's close, from NSE's F&O bhavcopy in the data warehouse (live.yml
pulls the last 13 months), using only strikes that traded that day (an untraded strike's close is yesterday's).
Today's live ATM IV is ranked against the sessions with the same calendar days to expiry (±1, widening to ±3
when that leaves too few). Context for the read, not a trading rule."""
from __future__ import annotations

import datetime as dt
from pathlib import Path

import numpy as np
import pandas as pd

from ..options.pricing import implied_vol_vec
from .chains import IST, time_to_expiry

COLS = ["date", "expiry", "dte", "spot", "atm_strike", "atm_iv"]


def atm_iv_history(bhav: pd.DataFrame, symbol: str, r: float, q: float, min_days: int = 1) -> pd.DataFrame:
    """One row per session: the nearest expiry ≥ min_days out, its calendar days to expiry, the index close, the
    traded strike nearest it, and the mean of its call and put IVs at the close (in %, like the live chain)."""
    if bhav is None or bhav.empty:
        return pd.DataFrame(columns=COLS)
    b = bhav[(bhav["symbol"] == symbol) & bhav["kind"].isin(["CE", "PE"]) & (bhav["close"] > 0) & (bhav["contracts"] > 0)]
    rows = []
    for day, g in b.groupby(pd.to_datetime(b["date"]).dt.date):
        spot = g["underlying"].dropna()
        if spot.empty:
            continue
        S = float(spot.iloc[0])
        exps = sorted(e for e in pd.to_datetime(g["expiry"]).dt.date.unique() if (e - day).days >= min_days)
        if not exps:
            continue
        exp = exps[0]
        ch = g[pd.to_datetime(g["expiry"]).dt.date == exp]
        both = ch.pivot_table(index="strike", columns="kind", values="close", aggfunc="last").dropna()
        if both.empty or not {"CE", "PE"} <= set(both.columns):
            continue
        K = float(both.index[np.argmin(np.abs(both.index.to_numpy(dtype=float) - S))])
        T = time_to_expiry(pd.Timestamp(dt.datetime.combine(day, dt.time(15, 30)), tz=IST), exp)
        ivs = [implied_vol_vec([both.loc[K, side]], S, [K], T, r, q, side)[0] for side in ("CE", "PE")]
        ivs = [v for v in ivs if v == v and v > 0]
        if ivs:
            rows.append((day, exp, (exp - day).days, S, K, float(np.mean(ivs)) * 100))
    return pd.DataFrame(rows, columns=COLS)


def load(root: Path, symbols, r: float, q: float, min_days: int, today: dt.date, days: int = 400) -> dict[str, pd.DataFrame]:
    """{symbol: history} from the warehouse's fo_bhav files under `root`; {} when there are none."""
    from ..data.warehouse import Warehouse
    if not any(Path(root).glob("fo_bhav_*.parquet")):
        return {}
    bhav = Warehouse(root).read("fo_bhav", start=today - dt.timedelta(days=days), end=today - dt.timedelta(days=1))
    out = {}
    for s in symbols:
        h = atm_iv_history(bhav, s, r, q, min_days)
        if len(h):
            out[s] = h
    return out


def iv_percentile(hist: pd.DataFrame | None, iv: float | None, dte: int, today: dt.date, window_days: int = 365,
                  bands=(1, 3), min_obs: int = 15) -> dict:
    """Today's ATM IV ranked against past sessions at about the same days to expiry: the share of them below it
    (ties count half), their median, how many there were and the ±days band used. {} when it can't say."""
    if hist is None or hist.empty or iv is None or not iv == iv or iv <= 0:
        return {}
    d = pd.to_datetime(hist["date"]).dt.date
    h = hist[(d < today) & (d >= today - dt.timedelta(days=window_days))]
    for band in bands:
        m = h.loc[(h["dte"] - dte).abs() <= band, "atm_iv"].to_numpy(dtype=float)
        if len(m) >= min_obs:
            return {"atm_ivp": float((m < iv).mean() + 0.5 * (m == iv).mean()), "atm_iv_median": float(np.median(m)),
                    "atm_ivp_n": int(len(m)), "atm_ivp_dte": int(dte), "atm_ivp_band": int(band)}
    return {}
