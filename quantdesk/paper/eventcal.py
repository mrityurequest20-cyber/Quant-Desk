"""The scheduled-events calendar (owner, 14 Nov 2026: "A scheduled-events calendar"). PAPER MONEY ONLY; nothing here trades.

What is coming, when (IST), and which instruments it touches:
* the owner's verified dates (config calendar.events: RBI decisions, India and US CPI, FOMC, the Budget), source "config";
* recurring releases by their published rule, source "rule": the US jobs report (the first Friday, 08:30 New York time), the EIA crude-oil inventory report (Wednesday,
  10:30 New York time) and India's CPI (the 12th, 16:00 IST). New York time is turned into IST with the US daylight-saving rule (second Sunday of March to first
  Sunday of November). A rule can be wrong in a given month (a holiday moves a release): rule-based dates say so, and a config date of the same kind and day wins;
* the brief's own lists: options expiring and companies reporting results, source "brief".

Each event has an IMPACT (high: a policy decision, the Budget, an election, an OPEC meeting; medium: a data release; low: an expiry) and the SUBJECTS it is about, so
the news model's channels (newsmodel.CHANNELS) say how much it touches each instrument. AUTO v2 uses that as its event regime (no volatility sold into it):
* high: from HIGH_BEFORE_H hours before to HIGH_AFTER_MIN minutes after;
* medium: from MEDIUM_BEFORE_MIN minutes before to MEDIUM_AFTER_MIN after;
* low events are shown, never a regime.
Standard library only (paper package rules).
"""
from __future__ import annotations

import datetime as dt
import re

from . import newsmodel as NM

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
HIGH_BEFORE_H, HIGH_AFTER_MIN = 24, 90
MEDIUM_BEFORE_MIN, MEDIUM_AFTER_MIN = 120, 60
TOUCH_MIN = {"high": 0.3, "medium": 0.5}     # a routine release must reach an instrument directly; a policy decision may reach it through a channel
EQUITY_ALL = 1.0                                         # the Budget and an election reach every Indian equity

# name pattern -> (kind, impact, subjects)
KINDS = [
    (r"\brbi\b|\bmpc\b", "rbi", "high", ("rbi",)),
    (r"fomc|\bfed\b", "fomc", "high", ("fed", "dollar")),
    (r"budget", "budget", "high", ()),
    (r"election|poll results", "election", "high", ()),
    (r"opec", "opec", "high", ("crude",)),
    (r"us cpi", "us_cpi", "medium", ("inflation", "fed", "dollar")),
    (r"india cpi|\bcpi\b", "india_cpi", "medium", ("inflation", "rbi")),
    (r"payrolls|jobs report|\bnfp\b", "us_jobs", "medium", ("fed", "dollar", "growth")),
    (r"\beia\b|crude (?:oil )?inventor", "eia", "medium", ("crude",)),
    (r"\bgdp\b", "gdp", "medium", ("growth",)),
    (r"expir", "expiry", "low", ()),
    (r"results", "results", "medium", ()),
]
_KINDS = [(re.compile(p, re.I), k, imp, subj) for p, k, imp, subj in KINDS]
INDIA_EQUITY = set(NM.GROUPS["INDEX"]) | {"RELIANCE", "HDFCBANK", "SBIN", "ICICIBANK", "TCS", "BHARTIARTL", "BSE", "INFY", "AXISBANK", "MARUTI", "DIXON", "PAYTM",
                                          "BAJAJ-AUTO", "KOTAKBANK", "BHEL", "LAURUSLABS", "DIVISLAB", "ITC", "BAJFINANCE", "M&M"}


def classify(name: str) -> tuple[str | None, str, tuple]:
    for rx, kind, impact, subj in _KINDS:
        if rx.search(name or ""):
            return kind, impact, subj
    return None, "medium", ()


# ---------------------------------------------------------------------------------------------------------------- New York time and the rules
def _nth_weekday(year: int, month: int, weekday: int, n: int) -> dt.date:
    d = dt.date(year, month, 1)
    d += dt.timedelta(days=(weekday - d.weekday()) % 7)
    return d + dt.timedelta(weeks=n - 1)


def us_dst(day: dt.date) -> bool:
    """US daylight saving on this date: from the second Sunday of March to the first Sunday of November."""
    return _nth_weekday(day.year, 3, 6, 2) <= day < _nth_weekday(day.year, 11, 6, 1)


def ny_to_ist(day: dt.date, hh: int, mm: int) -> dt.datetime:
    """A New York wall-clock time on `day` as an IST datetime (EDT is UTC-4, EST UTC-5)."""
    off = -4 if us_dst(day) else -5
    return dt.datetime(day.year, day.month, day.day, hh, mm, tzinfo=dt.timezone(dt.timedelta(hours=off))).astimezone(IST)


def rule_events(start: dt.date, days: int) -> list[dict]:
    """The recurring releases between start and start + days, by rule (each says it is a rule)."""
    out = []
    for i in range(days + 1):
        d = start + dt.timedelta(days=i)
        if d.weekday() == 4 and d.day <= 7:                                        # the first Friday: the US jobs report, 08:30 New York
            out.append(_ev(ny_to_ist(d, 8, 30), "US jobs report (non-farm payrolls)", "rule"))
        if d.weekday() == 2:                                                       # Wednesdays: the EIA crude-oil inventories, 10:30 New York
            out.append(_ev(ny_to_ist(d, 10, 30), "EIA crude oil inventories", "rule"))
        if d.day == 12:                                                            # India's CPI: the 12th, 16:00 IST
            out.append(_ev(dt.datetime(d.year, d.month, d.day, 16, 0, tzinfo=IST), "India CPI", "rule"))
    return out


def _ev(at: dt.datetime, name: str, source: str, **extra) -> dict:
    kind, impact, subj = classify(name)
    return {"at": at.astimezone(IST).isoformat(timespec="minutes"), "name": name, "kind": kind, "impact": impact, "subjects": list(subj), "source": source, **extra}


# ---------------------------------------------------------------------------------------------------------------- the calendar
def build(now: dt.datetime, config_events: list, days: int = 7, expiring: list | None = None, results: list | None = None) -> list[dict]:
    """Every event from now to `days` ahead, earliest first. config_events: [(date, time or None, name)] (the owner's calendar). A rule date of the same kind and day
    as a config date is dropped (the owner's date wins)."""
    now = now.astimezone(IST)
    start, end = now.date(), now.date() + dt.timedelta(days=days)
    out = []
    for d, t, name in config_events or []:
        if start <= d <= end:
            at = dt.datetime.combine(d, t or dt.time(9, 15), IST)
            out.append(_ev(at, name, "config", all_day=t is None))
    have = {(e["kind"], e["at"][:10]) for e in out}
    out += [e for e in rule_events(start, days) if (e["kind"], e["at"][:10]) not in have]
    for x in expiring or []:
        if isinstance(x, dict) and x.get("symbol"):
            out.append(_ev(dt.datetime.combine(start, dt.time(15, 30), IST), f"{x['symbol']} options expire", "brief", symbols=[x["symbol"]]))
    for r in results or []:
        if isinstance(r, dict) and r.get("symbol"):
            out.append(_ev(dt.datetime.combine(start, dt.time(9, 15), IST), f"{r['symbol']} results ({r.get('when', 'today')})", "brief", symbols=[r["symbol"]]))
    out = [e for e in out if dt.datetime.fromisoformat(e["at"]) >= now - dt.timedelta(minutes=HIGH_AFTER_MIN)]
    return sorted(out, key=lambda e: e["at"])


def touches(u: str, ev: dict) -> float:
    """How strongly an event bears on `u` (0 to 1): a named symbol, every Indian equity for the Budget or an election, else its subjects through the news channels."""
    if u in (ev.get("symbols") or []):
        return 1.0
    if ev.get("kind") == "results" and u in NM.GROUPS["INDEX"]:
        return 0.3                                                                 # a heavyweight's results move its index a little
    if ev.get("kind") in ("budget", "election"):
        return EQUITY_ALL if u in INDIA_EQUITY else 0.0
    return max((abs(s) for subj in ev.get("subjects") or [] for s, _ in NM.sensitivity(u, subj)), default=0.0)


def regime(u: str, calendar: list | None, now: dt.datetime) -> str | None:
    """The reason `u` is in an event regime because of a scheduled event, or None."""
    for ev in calendar or []:
        if not isinstance(ev, dict) or ev.get("impact") not in ("high", "medium"):
            continue
        try:
            at = dt.datetime.fromisoformat(ev["at"])
        except (KeyError, TypeError, ValueError):
            continue
        mins = (at - now).total_seconds() / 60
        hi = ev["impact"] == "high"
        if not (-(HIGH_AFTER_MIN if hi else MEDIUM_AFTER_MIN) <= mins <= (HIGH_BEFORE_H * 60 if hi else MEDIUM_BEFORE_MIN)):
            continue
        if touches(u, ev) < TOUCH_MIN[ev["impact"]]:
            continue
        when = f"at {at:%H:%M}" + ("" if at.date() == now.astimezone(IST).date() else f" on {at:%d %b}")
        return f"scheduled: {ev.get('name')} {when} ({'passed' if mins < 0 else 'ahead'})"
    return None
