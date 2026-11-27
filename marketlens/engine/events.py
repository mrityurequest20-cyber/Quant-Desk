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
