"""The News page's situation cards: one card per running situation (US/Israel-Iran, Russia-Ukraine, US tariffs, the
RBI cycle ...), built every day from the news corpus and the warehouse, with the Opus brief where one was written.

A card has two halves, kept apart on the page:
  * MEASURED (this module, from situations.py): how active the situation is now against its own past year, its dated
    flare-up episodes with their top headlines and what markets did after each (NIFTY, BANKNIFTY, India VIX, Brent,
    gold, USD/INR, the US 10-year, the situation's sector baskets against NIFTY), the base rates across episodes, and
    the latest headlines. Every number here is computed; nothing is written by a model.
  * WRITTEN (brief.py, Claude Opus 5.5, once): where it stands, the sides and their next moves, the escalation ladder,
    scenarios with their precedents, the transmission to India, what to watch. Shown with its date, as analysis.

Descriptive only: what happened after past flare-ups, never a forecast. Below MIN_RATE episodes a base rate is not a
rate: the card lists the episodes instead and says so.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

from . import situations as NS

MIN_RATE = 5
SHOW_EPISODES = 12
# the measures a card leads with, in order; (key in the reaction tables, label, unit)
KEY = [("NIFTY", "NIFTY", "ret"), ("BANKNIFTY", "BANKNIFTY", "ret"), ("India VIX (pts)", "India VIX", "pts"),
       ("Brent", "Brent crude", "ret"), ("Gold", "Gold", "ret"), ("USD/INR", "USD/INR", "ret"),
       ("US 10y yield (bp)", "US 10-year yield", "bp"), ("CBOE VIX (pts)", "CBOE VIX", "pts"), ("S&P 500 futures", "S&P 500 futures", "ret")]
BASKET_LABEL = {"oil_marketing": "Oil marketers (BPCL, HPCL, IOC)", "upstream_oil_gas": "Oil producers (ONGC, Oil India)",
                "paints": "Paints", "airlines": "Airlines (IndiGo)", "defence": "Defence (HAL, BEL, BDL)", "it_services": "IT services",
                "private_banks": "Private banks", "psu_banks": "PSU banks", "metals": "Metals", "pharma": "Pharma", "autos": "Autos",
                "gold_finance": "Gold lenders", "fmcg": "FMCG", "ports_logistics": "Ports and logistics", "nbfc": "NBFCs",
                "capital_markets": "Capital-market stocks"}


def fmt(v: float | None, unit: str, d: int = 1) -> str:
    if v is None or not math.isfinite(v):
        return "—"
    if unit == "ret":
        return f"{(math.exp(v) - 1) * 100:+.{d}f}%"
    if unit == "bp":
        return f"{v:+.0f} bp"
    return f"{v:+.{d}f} pts"


def activity(tagged: pd.DataFrame, asof: pd.Timestamp, weeks: int = 52) -> dict:
    """Weekly story counts for the past year, and how this week compares with that year (the heat)."""
    if tagged.empty:
        return {"weekly": [], "last7": 0, "typical7": 0.0, "heat": "quiet"}
    day = tagged["day"]
    start = asof - pd.Timedelta(weeks=weeks)
    w = tagged[(day > start) & (day <= asof)].groupby(pd.Grouper(key="day", freq="W-SUN")).size()
    w = w.reindex(pd.date_range(start.normalize() + pd.offsets.Week(weekday=6), asof + pd.offsets.Week(weekday=6), freq="W-SUN"), fill_value=0)
    last7 = int(((day > asof - pd.Timedelta(days=7)) & (day <= asof)).sum())
    past = w.iloc[:-1] if len(w) > 1 else w
    typical = float(past.median()) if len(past) else 0.0
    high = float(past.quantile(0.9)) if len(past) else 0.0
    heat = ("flaring" if last7 >= max(NS.MIN_STORIES, high) and last7 > typical else
            "active" if last7 >= max(3, 1.5 * typical) and last7 > typical else "quiet")
    return {"weekly": [[str(k.date()), int(v)] for k, v in w.items()], "last7": last7, "typical7": typical, "heat": heat}


def _top_basket(reaction: dict, h: int = 5):
    best = None
    for k, v in reaction.items():
        if k.startswith("vs NIFTY: ") and isinstance(v, dict) and v.get(h) is not None and math.isfinite(v[h]):
            if best is None or abs(v[h]) > abs(best[1]):
                best = (k[len("vs NIFTY: "):], v[h])
    return best


def episode_row(e: dict) -> dict:
    r = e["reaction"]
    vals = {lab: {str(h): (r.get(k) or {}).get(h) for h in NS.HORIZONS} for k, lab, _ in KEY if k in r}
    baskets = {BASKET_LABEL.get(k[len("vs NIFTY: "):], k[len("vs NIFTY: "):]): {str(h): v.get(h) for h in NS.HORIZONS}
               for k, v in r.items() if k.startswith("vs NIFTY: ")}
    tb = _top_basket(r)
    return {"start": e["start"], "stories": e["stories"], "headlines": e["headlines"][:3], "measures": vals, "baskets": baskets,
            "top_basket": [BASKET_LABEL.get(tb[0], tb[0]), tb[1]] if tb else None}


def base_table(rates: dict) -> list[dict]:
    """The base rates a card shows: each key measure and basket, at 1, 5 and 20 sessions, with n."""
    rows = []
    unit = {k: u for k, _, u in KEY}
    for k, lab, u in KEY:
        if k in rates:
            rows.append({"measure": lab, "unit": u, **_rate_cells(rates[k])})
    for k, v in rates.items():
        if k.startswith("vs NIFTY: "):
            b = k[len("vs NIFTY: "):]
            rows.append({"measure": BASKET_LABEL.get(b, b) + " vs NIFTY", "unit": "ret", "basket": True, **_rate_cells(v)})
    del unit
    return rows


def _rate_cells(v: dict) -> dict:
    out = {}
    for h in NS.HORIZONS:
        c = v.get(h) or v.get(str(h))
        out[f"h{h}"] = {"median": c["median"], "share_up": c["share_up"], "n": c["n"]} if c else None
    out["kept_at_20"] = v.get("kept_at_20")
    return out


def plain(name: str, eps: list[dict], rates: dict, act: dict) -> str:
    """The card's measured story in plain words."""
    n = len(eps)
    now = {"flaring": f"It is flaring now: {act['last7']} stories in the past week against about {act['typical7']:.0f} in a typical week.",
           "active": f"It is active: {act['last7']} stories in the past week against about {act['typical7']:.0f} in a typical week.",
           "quiet": f"It is quiet now: {act['last7']} stories in the past week."}[act["heat"]]
    if n == 0:
        return f"{now} No flare-up stands out in the record yet, so there is nothing measured to compare."
    if n < MIN_RATE:
        return (f"{now} The record has {n} flare-up{'s' if n > 1 else ''} since {eps[0]['start']}, too few for a base rate: "
                f"each one and what markets did after it are listed below.")
    def cell(k, h=5):
        c = (rates.get(k) or {}).get(h)
        return c if c and c["n"] >= MIN_RATE else None
    parts = []
    for k, lab, u in KEY[:4]:
        c = cell(k)
        if c:
            parts.append(f"{lab} {fmt(c['median'], u)} (up in {round(c['share_up'] * c['n'])} of {c['n']})")
    bk = []
    for k, v in rates.items():
        c = (v or {}).get(5)
        if k.startswith("vs NIFTY: ") and c and c["n"] >= MIN_RATE:
            bk.append((abs(c["median"]), BASKET_LABEL.get(k[10:], k[10:]), c))
    bk.sort(reverse=True)
    s = f"{now} After its {n} flare-ups since {eps[0]['start']}, the median move over the next five sessions was: " + "; ".join(parts) + "."
    if bk:
        _, lab, c = bk[0]
        s += f" The sector that moved most against NIFTY: {lab}, {fmt(c['median'], 'ret')} (median)."
    fade = (rates.get("NIFTY") or {}).get("kept_at_20")
    if fade is not None and math.isfinite(fade):
        s += (" NIFTY's five-day move usually faded by twenty sessions." if fade < 0.5 else
              " NIFTY's five-day move usually held at twenty sessions." if fade < 1.5 else
              " NIFTY's five-day move usually grew by twenty sessions.")
    return s + " What happened after past flare-ups, not a forecast."


def load_briefs(folder: Path) -> dict[str, dict]:
    out = {}
    for p in sorted(Path(folder).glob("brief_*.json")):
        try:
            d = json.loads(p.read_text())
            out[d["situation"]] = {"model": d.get("model", ""), **d["brief"]}
        except (OSError, ValueError, KeyError):
            continue
    return out


def build(stories: pd.DataFrame, macro: dict, india: dict, closes: dict, briefs: dict | None = None,
          asof: pd.Timestamp | None = None) -> dict:
    """news.json: every situation's card, the most active first."""
    if stories is None or stories.empty:
        return {"asof": None, "stories": 0, "situations": []}
    an = NS.analyse(stories, macro, india, closes)
    tagged = NS.assign(stories)
    tagged["day"] = pd.to_datetime(tagged["ts"], utc=True).dt.tz_convert("Asia/Kolkata").dt.tz_localize(None).dt.normalize()
    asof = pd.Timestamp(asof).normalize() if asof is not None else tagged["day"].max()
    rec = NS.recent(stories, days=30)
    cards = []
    for sid, spec in NS.SITUATIONS.items():
        sit = an.get(sid)
        t = tagged[tagged["situation"] == sid]
        act = activity(t, asof)
        eps = sit["episodes"] if sit else []
        rates = sit["base_rates"] if sit else {}
        b = (briefs or {}).get(sid)
        cards.append({
            "id": sid.split(":", 1)[1].lower(), "sid": sid, "name": spec["name"], "sides": spec["sides"],
            "baskets": [BASKET_LABEL.get(k, k) for k in spec["baskets"]],
            "stories": int(len(t)), "first": sit["first"] if sit else None, "last": sit["last"] if sit else None,
            "activity": act, "n_episodes": len(eps), "plain": plain(spec["name"], eps, rates, act),
            "episodes": [episode_row(e) for e in eps[-SHOW_EPISODES:]][::-1],
            "base": base_table(rates) if len(eps) >= MIN_RATE else [],
            "latest": rec.get(sid, [])[-8:][::-1],
            "brief": b,
        })
    rank = {"flaring": 0, "active": 1, "quiet": 2}
    cards.sort(key=lambda c: (rank[c["activity"]["heat"]], -c["activity"]["last7"], -c["stories"]))
    return {"asof": str(asof.date()), "stories": int(len(stories)), "situations": _clean(cards)}


def _clean(x):
    if isinstance(x, dict):
        return {str(k): _clean(v) for k, v in x.items()}
    if isinstance(x, list):
        return [_clean(v) for v in x]
    if isinstance(x, (float, np.floating)):
        return round(float(x), 6) if math.isfinite(x) else None
    if isinstance(x, np.integer):
        return int(x)
    return x
