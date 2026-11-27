"""Events: what is scheduled (results, expiries, holidays) and how this market has moved on such days before."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

MACRO_FILE = Path(__file__).resolve().parents[2] / "quantdesk" / "premarket" / "macro_dates.json"


def results_calendar(ev: pd.DataFrame, symbols: list[str], asof) -> pd.DataFrame:
    """Board meetings that consider financial results, for the covered stocks."""
    if ev.empty:
        return ev
    e = ev[ev["symbol"].isin(symbols) & ev["purpose"].astype(str).str.contains("Financial Results", case=False)]
    e = e.drop_duplicates(["symbol", "date"]).sort_values("date")
    return e[["date", "symbol", "purpose"]]


def results_study(ev: pd.DataFrame, close: pd.Series, t: pd.DataFrame, iv_front: pd.Series, asof) -> list[dict]:
    """For each results date: what the option curve priced, and what happened.

    The announcement time is not in the calendar (during market hours or after the close), so the reaction is shown
    for both the results-day session (day 0) and the next one (day 1), and everything priced is read at the last close
    before day 0, when the event was certainly still ahead. IV change = front ATM IV at the close of day 1 minus at
    that last close before."""
    from . import vol as V
    out = []
    idx = close.index
    for r in ev.itertuples():
        d = pd.Timestamp(r.date)
        item = {"date": str(d.date()), "purpose": r.purpose, "upcoming": bool(d > asof)}
        i0 = idx.searchsorted(d)                    # day 0: the results date, or the first session after it
        if item["upcoming"]:
            ev_now = V.event_vol(t, asof)
            if ev_now and pd.Timestamp(ev_now["front_expiry"]) >= d:
                item["implied_event_move"] = ev_now["event_move"]
        elif 0 < i0 < len(idx):
            pre = idx[i0 - 1]
            item["move_day0"] = float(close.iat[i0] / close.iat[i0 - 1] - 1)
            if i0 + 1 < len(idx):
                item["move_day1"] = float(close.iat[i0 + 1] / close.iat[i0] - 1)
            evp = V.event_vol(t, pre)
            if evp:
                item["implied_event_move"] = evp["event_move"]
            moves = [abs(x) for x in (item.get("move_day0"), item.get("move_day1")) if x is not None]
            item["reaction"] = max(moves) if moves else None
            if i0 + 1 < len(idx):
                a, b = iv_front.get(idx[i0 + 1]), iv_front.get(pre)
                if a is not None and b is not None and np.isfinite(a) and np.isfinite(b):
                    item["iv_change"] = float(a - b)
        out.append(item)
    return out


def macro_kinds() -> dict:
    try:
        return json.loads(MACRO_FILE.read_text())["kinds"]
    except (OSError, ValueError, KeyError):
        return {}


def macro_study(ret: pd.Series) -> list[dict]:
    """For each kind of macro day (RBI policy, Budget, FOMC, elections...): the typical absolute move of this
    instrument on those days against all other days. Descriptive, from the dates listed in macro_dates.json."""
    r = ret.dropna().abs()
    if len(r) < 100:
        return []
    base = float(r.median())
    out = []
    for k, v in macro_kinds().items():
        days = pd.to_datetime(v.get("dates", []))
        lag = 1 if v.get("reacts") == "next_session" else 0
        hit = []
        for d in days:
            i = r.index.searchsorted(d)
            i += lag
            if 0 <= i < len(r) and abs((r.index[min(i, len(r) - 1)] - d).days) <= 4:
                hit.append(r.iat[i])
        if len(hit) >= 5:
            out.append({"kind": k, "label": v.get("label", k), "n": len(hit), "median_move": float(np.median(hit)),
                        "normal_median": base, "ratio": float(np.median(hit) / base) if base else None,
                        "max_move": float(np.max(hit))})
    return sorted(out, key=lambda x: -(x["ratio"] or 0))


def big_days(ret: pd.Series, n: int = 8) -> list[dict]:
    r = ret.dropna()
    top = r.abs().sort_values(ascending=False).head(n)
    return [{"date": str(d.date()), "ret": float(r.loc[d])} for d in top.index]
