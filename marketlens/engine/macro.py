"""Global macro events in MarketLens: what is coming (the calendar) and how each instrument has reacted (event studies).

The events come from the warehouse's `macro_events` table (quantdesk/data/macro.py): central banks (RBI, Fed, ECB,
BoE, BoJ), inflation, jobs and growth data (India and US), China's data, the Budget, elections, and the desk's checked
list of geopolitical and oil shocks.

Which session reacts: an event inside Indian market hours (09:15-15:30 IST) moves that session; one after the close,
or overnight in India (the US releases, the Fed at 23:30 / 00:30 IST, MoSPI's 16:00 releases) moves the NEXT session.
An event with no time takes its kind's usual timing.

For each kind with at least MIN_N past events, per instrument:
  * the median absolute move on the reacting session against the median of all other sessions (x times normal)
  * how often that move was bigger than options priced for a day (the front ATM IV the evening before, / sqrt(252))
  * the change in front ATM IV from the evening before to the reacting session's close (does it crush?)
  * the median signed move (a lean, if any) and the largest move
Descriptive: a small sample per kind, overlapping with other news. The page says so.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

MIN_N = 5
NEXT_BY_DEFAULT = {"fomc", "us_cpi", "us_nfp", "us_gdp", "us_pce", "us_ism", "fed_chair", "ecb", "boe", "india_cpi", "india_gdp", "india_iip"}
STUDY_KINDS = ["rbi", "fomc", "us_cpi", "us_nfp", "us_gdp", "us_pce", "ecb", "boj", "boe", "china_data", "india_cpi", "india_gdp",
               "india_iip", "budget", "election", "geopolitics", "oil_shock", "fed_chair", "us_ism"]
IMPACT_RANK = {"High": 3, "Medium": 2, "Low": 1}


def events(raw: pd.DataFrame) -> pd.DataFrame:
    """Clean rows, one per (date, kind) for studied kinds (several sources can list the same meeting)."""
    if raw is None or raw.empty:
        return pd.DataFrame(columns=["date", "time_ist", "country", "title", "kind", "impact", "forecast", "previous", "source"])
    d = raw.copy()
    d["date"] = pd.to_datetime(d["date"]).dt.normalize()
    for c in ("time_ist", "forecast", "previous", "source", "impact", "title", "country", "kind"):
        if c in d:
            d[c] = d[c].fillna("").astype(str)
    return d.sort_values(["date", "time_ist"])


def reacting_session(day: pd.Timestamp, time_ist: str, kind: str, sessions: pd.DatetimeIndex) -> int | None:
    """Position of the session that reacts to an event on `day` at `time_ist` (IST): that day's session if the event
    lands before the close (15:30), else the next one; with no time, the kind's usual timing."""
    i = sessions.searchsorted(day)                      # the first session on or after the event's day
    on = i < len(sessions) and sessions[i] == day
    late = time_ist > "15:30" if time_ist else kind in NEXT_BY_DEFAULT
    j = i + 1 if (on and late) else i
    return j if j < len(sessions) else None


def study(close: pd.Series, iv: pd.Series | None, ev: pd.DataFrame, asof) -> list[dict]:
    c = close.dropna().sort_index()
    c = c[c.index <= pd.Timestamp(asof)]
    if len(c) < 150 or ev is None or ev.empty:
        return []
    r = np.log(c).diff()
    s = c.index
    out = []
    base = float(r.abs().median())
    for k in STUDY_KINDS:
        e = ev[(ev["kind"] == k) & (ev["date"] <= pd.Timestamp(asof))].drop_duplicates("date")
        hits = []
        for row in e.itertuples():
            j = reacting_session(row.date, row.time_ist, k, s)
            if j is None or j < 1 or j >= len(s):
                continue
            mv = r.iat[j]
            if not np.isfinite(mv):
                continue
            h = {"date": str(s[j].date()), "move": float(mv)}
            if iv is not None:
                a, b = iv.get(s[j - 1]), iv.get(s[j])
                if a is not None and np.isfinite(a) and a > 0:
                    h["priced"] = float(a / np.sqrt(252))
                    if b is not None and np.isfinite(b):
                        h["d_iv"] = float(b - a)
            hits.append(h)
        if len(hits) < MIN_N:
            continue
        mv = np.array([h["move"] for h in hits])
        pr = [h for h in hits if "priced" in h]
        di = [h["d_iv"] for h in hits if "d_iv" in h]
        out.append({"kind": k, "n": len(hits), "median_move": float(np.median(np.abs(mv))), "normal": base,
                    "ratio": float(np.median(np.abs(mv)) / base) if base else None,
                    "beat_priced": float(np.mean([abs(h["move"]) > h["priced"] for h in pr])) if len(pr) >= MIN_N else None,
                    "d_iv": float(np.median(di)) if len(di) >= MIN_N else None,
                    "lean": float(np.median(mv)), "up_share": float((mv > 0).mean()),
                    "max_move": float(mv[np.argmax(np.abs(mv))]), "last": hits[-1]["date"]})
    return sorted(out, key=lambda x: -(x["ratio"] or 0))


def upcoming(ev: pd.DataFrame, asof, days: int = 21, min_impact: str = "Medium") -> list[dict]:
    """Scheduled events after `asof`, the important ones only, one row per (date, title)."""
    if ev is None or ev.empty:
        return []
    a = pd.Timestamp(asof)
    e = ev[(ev["date"] > a) & (ev["date"] <= a + pd.Timedelta(days=days))]
    e = e[e["impact"].map(IMPACT_RANK).fillna(0) >= IMPACT_RANK.get(min_impact, 2)]
    e = e[~((e["source"] == "desk list") & e["kind"].isin(["geopolitics", "oil_shock"]))]
    e = e.drop_duplicates(["date", "kind", "title"]).sort_values(["date", "time_ist"])
    # one row per (date, kind) for the studied kinds: the Fed's page and Forex Factory both list a meeting
    studied = e["kind"].isin(STUDY_KINDS)
    e = pd.concat([e[studied].drop_duplicates(["date", "kind"]), e[~studied]]).sort_values(["date", "time_ist"])
    return [{"date": str(r.date.date()), "time": r.time_ist, "country": r.country, "title": r.title, "kind": r.kind,
             "impact": r.impact, "forecast": r.forecast, "previous": r.previous, "source": r.source} for r in e.itertuples()]
