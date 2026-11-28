"""The situation analyzer's measured half: running situations (US-Iran, Russia-Ukraine, US tariffs, the RBI cycle ...),
their history as dated EPISODES (the days the situation flared in the news), and what markets did after each episode,
macro and micro. The written half (who can do what next, the escalation ladder, scenarios) is in brief.py; every number
it quotes comes from here.

  * assign():    a story belongs to a situation when it was found by the situation's own search or its headline names
                 the situation's subjects (a regular expression per situation)
  * episodes():  a flare-up is a day whose story count for the situation is far above its own recent normal (at least
                 MIN_STORIES, and above the 60-day median + 4 x the median absolute deviation); flare-ups within GAP days
                 of each other are one episode, dated by its first day
  * react():     for each episode, from the last close before it: macro (Brent, gold, USD/INR, the dollar index, the US
                 10-year yield in bp, CBOE VIX in points, S&P futures) and India (NIFTY, BANKNIFTY, India VIX in points),
                 and the situation's sector baskets as returns relative to NIFTY, at 1, 5 and 20 sessions
  * base_rates(): across episodes, per measure and horizon: the median, the share up, n, and how much of the five-day
                 move was still there at twenty days (does it fade?)

Descriptive only: what happened after past flare-ups, never a forecast. With n under 5 a base rate is shown as a list
of episodes, not as a rate.
"""
from __future__ import annotations

import re

import numpy as np
import pandas as pd

MIN_STORIES, GAP, HORIZONS = 4, 7, (1, 5, 20)

BASKETS = {
    "oil_marketing": ["BPCL", "HINDPETRO", "IOC"],
    "upstream_oil_gas": ["ONGC", "OIL"],
    "paints": ["ASIANPAINT", "BERGEPAINT"],
    "airlines": ["INDIGO"],
    "defence": ["HAL", "BEL", "BDL"],
    "it_services": ["TCS", "INFY", "HCLTECH", "WIPRO", "TECHM"],
    "private_banks": ["HDFCBANK", "ICICIBANK", "AXISBANK", "KOTAKBANK"],
    "psu_banks": ["SBIN", "BANKBARODA", "PNB", "CANBK"],
    "metals": ["TATASTEEL", "JSWSTEEL", "HINDALCO", "VEDL"],
    "pharma": ["SUNPHARMA", "DRREDDY", "CIPLA", "DIVISLAB"],
    "autos": ["MARUTI", "M&M", "TATAMOTORS", "BAJAJ-AUTO"],
    "gold_finance": ["MUTHOOTFIN", "MANAPPURAM"],
    "fmcg": ["HINDUNILVR", "ITC", "NESTLEIND"],
    "ports_logistics": ["ADANIPORTS", "CONCOR"],
    "nbfc": ["BAJFINANCE", "CHOLAFIN", "SHRIRAMFIN"],
    "capital_markets": ["BSE", "ANGELONE", "CDSL", "MCX"],
}
MACRO = {"BZ=F": ("Brent", "ret"), "GC=F": ("Gold", "ret"), "INR=X": ("USD/INR", "ret"), "DX-Y.NYB": ("Dollar index", "ret"),
         "^TNX": ("US 10y yield (bp)", "bp"), "^VIX": ("CBOE VIX (pts)", "pts"), "ES=F": ("S&P 500 futures", "ret")}
INDIA = {"NIFTY": ("NIFTY", "ret"), "BANKNIFTY": ("BANKNIFTY", "ret"), "INDIAVIX": ("India VIX (pts)", "pts")}

SITUATIONS = {
    "SIT:IRAN_US_ISRAEL": {"name": "US / Israel - Iran", "sides": ["United States", "Israel", "Iran"],
                           "re": r"\biran|tehran|hormuz|irgc|khamenei|hezbollah",
                           "baskets": ["oil_marketing", "upstream_oil_gas", "paints", "airlines", "defence", "gold_finance"]},
    "SIT:RUSSIA_UKRAINE": {"name": "Russia - Ukraine", "sides": ["Russia", "Ukraine", "NATO / West"],
                           "re": r"\bukrain|kyiv|kremlin|putin|zelensk", "baskets": ["oil_marketing", "upstream_oil_gas", "metals", "defence", "fmcg"]},
    "SIT:CHINA_TAIWAN_US": {"name": "US - China, Taiwan", "sides": ["United States", "China", "Taiwan"],
                            "re": r"taiwan|beijing.*(us|washington)|us-china|china.*(chip|export curb)", "baskets": ["it_services", "metals", "autos"]},
    "SIT:RED_SEA_SHIPPING": {"name": "Red Sea and shipping lanes", "sides": ["Houthis", "US-led navies", "shippers"],
                             "re": r"red sea|houthi|suez|bab.el.mandeb|shipping (disrupt|attack)", "baskets": ["ports_logistics", "oil_marketing", "pharma"]},
    "SIT:OPEC": {"name": "OPEC+ supply", "sides": ["Saudi Arabia", "Russia", "other OPEC+"], "re": r"\bopec",
                 "baskets": ["oil_marketing", "upstream_oil_gas", "paints", "airlines"]},
    "SIT:US_TARIFFS_INDIA": {"name": "US tariffs and trade with India", "sides": ["United States", "India"],
                             "re": r"tariff|trade deal|trade talks|section 301", "baskets": ["it_services", "pharma", "autos", "metals"]},
    "SIT:INDIA_PAKISTAN": {"name": "India - Pakistan", "sides": ["India", "Pakistan"], "re": r"pakistan|\bloc\b|pulwama|balakot|pahalgam",
                           "baskets": ["defence", "psu_banks"]},
    "SIT:INDIA_CHINA_BORDER": {"name": "India - China border", "sides": ["India", "China"], "re": r"\blac\b|galwan|ladakh|arunachal.*china",
                               "baskets": ["defence", "metals"]},
    "SIT:FED_CYCLE": {"name": "The Fed's rate cycle", "sides": ["Federal Reserve", "US markets"], "re": r"federal reserve|\bfomc|powell|fed (hike|cut|pause|rate)",
                      "baskets": ["it_services", "private_banks", "nbfc"]},
    "SIT:RBI_CYCLE": {"name": "RBI's rate and liquidity cycle", "sides": ["RBI", "Government"], "re": r"\brbi\b.*(repo|mpc|rate|crr|liquidity)|monetary policy",
                      "baskets": ["private_banks", "psu_banks", "nbfc", "autos"]},
    "SIT:INDIA_ELECTIONS": {"name": "Indian elections", "sides": ["ruling alliance", "opposition"], "re": r"election|exit poll|lok sabha|assembly poll",
                            "baskets": ["psu_banks", "defence", "capital_markets"]},
    "SIT:CRUDE_SPIKE": {"name": "Crude oil shocks", "sides": ["producers", "importers"], "re": r"(brent|crude).*(surge|spike|soar|crash|plunge|\$1\d\d)",
                        "baskets": ["oil_marketing", "upstream_oil_gas", "paints", "airlines"]},
}


def assign(stories: pd.DataFrame) -> pd.DataFrame:
    """One row per (story, situation): found by the situation's search, or its title matches the situation's subjects."""
    rows = []
    title = stories["title"].fillna("").str.lower()
    for sid, s in SITUATIONS.items():
        pat = re.sub(r"\((?!\?)", "(?:", s["re"])                # groups made non-capturing: a match test only
        hit = (stories["symbol"] == sid) | title.str.contains(pat, regex=True, flags=re.I)
        part = stories.loc[hit, ["id", "ts", "title", "publisher"]].assign(situation=sid)
        rows.append(part)
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame(columns=["id", "ts", "title", "publisher", "situation"])


def episodes(daily: pd.Series, min_stories: int = MIN_STORIES, gap: int = GAP) -> list[pd.Timestamp]:
    """Flare-up days of one situation's daily story count (a calendar-day series, zeros filled), as episode start days."""
    d = daily.asfreq("D", fill_value=0) if len(daily) else daily
    med = d.rolling(60, min_periods=20).median().shift(1)
    mad = (d - med).abs().rolling(60, min_periods=20).median().shift(1)
    flare = (d >= min_stories) & (d > med + 4 * mad.clip(lower=1))
    out, last = [], None
    for day in d.index[flare.fillna(False)]:
        if last is None or (day - last).days > gap:
            out.append(day)
        last = day
    return out


def _level(s: pd.Series, start: pd.Timestamp, h: int) -> tuple[float, float] | None:
    s = s.dropna().sort_index()
    i = s.index.searchsorted(start)                 # the first value on or after the episode's day
    if i == 0 or i - 1 + h >= len(s):
        return None
    return float(s.iat[i - 1]), float(s.iat[i - 1 + h])


def measure(series: pd.Series, kind: str, start: pd.Timestamp, h: int) -> float | None:
    v = _level(series, start, h)
    if v is None or not all(np.isfinite(v)):
        return None
    a, b = v
    if kind == "ret":
        return float(np.log(b / a)) if a > 0 and b > 0 else None
    return float((b - a) * (100 if kind == "bp" else 1))


def basket_index(closes: dict[str, pd.Series]) -> pd.Series:
    """An equal-weight basket's index from its stocks' closes: the mean daily log return, a day over 35% (a split or
    bonus the close was not adjusted for) dropped."""
    rets = []
    for c in closes.values():
        r = np.log(c.sort_index()).diff()
        rets.append(r.where(r.abs() < 0.35))
    if not rets:
        return pd.Series(dtype=float)
    m = pd.concat(rets, axis=1).mean(axis=1, skipna=True).dropna()
    return np.exp(m.cumsum())


def react(start: pd.Timestamp, macro: dict[str, pd.Series], india: dict[str, pd.Series], baskets: dict[str, pd.Series]) -> dict:
    out = {"start": str(start.date())}
    for tk, (name, kind) in MACRO.items():
        if tk in macro:
            out[name] = {h: measure(macro[tk], kind, start, h) for h in HORIZONS}
    for sym, (name, kind) in INDIA.items():
        if sym in india:
            out[name] = {h: measure(india[sym], kind, start, h) for h in HORIZONS}
    nifty = india.get("NIFTY")
    for b, s in baskets.items():
        vals = {}
        for h in HORIZONS:
            rb, rn = measure(s, "ret", start, h), (measure(nifty, "ret", start, h) if nifty is not None else None)
            vals[h] = rb - rn if rb is not None and rn is not None else None
        out["vs NIFTY: " + b] = vals
    return out


def base_rates(reactions: list[dict]) -> dict:
    out = {}
    keys = sorted({k for r in reactions for k in r if k != "start"})
    for k in keys:
        row = {}
        for h in HORIZONS:
            v = np.array([r[k][h] for r in reactions if k in r and r[k].get(h) is not None], dtype=float)
            if len(v):
                row[h] = {"n": int(len(v)), "median": float(np.median(v)), "share_up": float((v > 0).mean())}
        five = [(r[k][5], r[k][20]) for r in reactions if k in r and r[k].get(5) not in (None, 0) and r[k].get(20) is not None]
        if len(five) >= 3:
            row["kept_at_20"] = float(np.median([b / a for a, b in five]))
        out[k] = row
    return out


def analyse(stories: pd.DataFrame, macro: dict, india: dict, closes: dict[str, pd.Series], top: int = 6) -> dict:
    """Every situation: its episodes (date, story count, top headlines), each episode's measured reaction, the base
    rates across them. closes: stock symbol -> close series (for the sector baskets)."""
    tagged = assign(stories)
    tagged["day"] = pd.to_datetime(tagged["ts"], utc=True).dt.tz_convert("Asia/Kolkata").dt.tz_localize(None).dt.normalize()
    out = {}
    for sid, spec in SITUATIONS.items():
        t = tagged[tagged["situation"] == sid]
        if t.empty:
            continue
        daily = t.groupby("day").size()
        eps = episodes(daily)
        bk = {b: basket_index({s: closes[s] for s in BASKETS[b] if s in closes}) for b in spec["baskets"]}
        bk = {b: s for b, s in bk.items() if len(s)}
        rows = []
        for e in eps:
            win = t[(t["day"] >= e) & (t["day"] < e + pd.Timedelta(days=GAP))]
            rows.append({"start": str(e.date()), "stories": int(len(win)),
                         "headlines": win.sort_values("ts")["title"].drop_duplicates().head(top).tolist(),
                         "reaction": react(e, macro, india, bk)})
        out[sid] = {"name": spec["name"], "sides": spec["sides"], "stories": int(len(t)),
                    "first": str(t["day"].min().date()), "last": str(t["day"].max().date()),
                    "episodes": rows, "base_rates": base_rates([r["reaction"] for r in rows])}
    return out


def inputs(wh) -> tuple[dict, dict, dict]:
    """The series analyse() measures, read from MarketLens's warehouse reader (engine/data.py)."""
    g = wh.globals_()
    macro = {}
    if len(g):
        g = g.assign(date=pd.to_datetime(g["date"]))
        for tk in MACRO:
            part = g[g["ticker"] == tk].drop_duplicates("date", keep="last").set_index("date")["close"].sort_index()
            if len(part):
                macro[tk] = part.astype(float)
    india = {}
    for sym in INDIA:
        try:
            india[sym] = wh.spot(sym)["close"].astype(float)
        except Exception:                                           # noqa: BLE001 - a missing series is left out, not guessed
            pass
    closes = {}
    for b in BASKETS.values():
        for sym in b:
            if sym in closes:
                continue
            try:
                c = wh.cash(sym)
                if len(c):
                    closes[sym] = c["close"].astype(float)
            except Exception:                                       # noqa: BLE001
                pass
    return macro, india, closes


def recent(stories: pd.DataFrame, days: int = 45) -> dict[str, list[dict]]:
    """The latest headlines of each situation, newest last: what the brief reads as 'where it stands now'."""
    t = assign(stories)
    if t.empty:
        return {}
    t["ts"] = pd.to_datetime(t["ts"], utc=True)
    t = t[t["ts"] >= t["ts"].max() - pd.Timedelta(days=days)].sort_values("ts")
    return {sid: [{"date": str(r.ts.tz_convert("Asia/Kolkata").date()), "title": r.title} for r in g.drop_duplicates("title").itertuples()]
            for sid, g in t.groupby("situation")}

