"""The market map: which Indian derivatives market is open when, and how a day's recording is split into chained jobs.

Pure logic: no network, no secret, no order, no clock of its own (every function takes the moment it is asked about).

Segments (all times IST, Monday to Friday):
  nse_fo   NSE index and stock F&O      09:15 - 15:30
  bse_fo   BSE index F&O (SENSEX...)    09:15 - 15:30
  nse_cds  NSE currency derivatives     09:00 - 17:00
  mcx      MCX commodity derivatives    09:00 - 23:30, or 23:55 while US daylight saving time is in force
           (crude, natural gas, gold, silver, copper...; the later close follows the US clock change)
Crypto is not a segment here and never will be without the owner's word. No market opens at the weekend, except a special session the exchange announces
(`calendar.special_sessions`, e.g. Muhurat trading), which counts only for trading questions (`trading=True`).

Two ways to ask whether a segment is open, because the two mistakes cost different things:
  recording (trading=False)  an unverified holiday calendar counts as open: recording a holiday costs nothing
  trading   (trading=True)   a segment whose holiday calendar is not verified for that year is NOT open: a paper desk that
                             trades a day it should not is worse than one that sits out a day it could have traded
The NSE and BSE calendars come from config (`calendar.holidays`, `calendar.holiday_years`). MCX and NSE currency calendars
come from `markets.<segment>.holidays` / `markets.<segment>.holiday_years`; until someone enters and verifies them they are
unverified, so those segments record every weekday and trade on none.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
MCX_EARLY_CLOSE = dt.time(23, 30)       # US standard time
MCX_LATE_CLOSE = dt.time(23, 55)        # US daylight saving time
MCX_EVENING_OPEN = dt.time(17, 0)       # on a day MCX shuts only its morning session


@dataclass(frozen=True)
class Segment:
    key: str
    name: str
    opens: dt.time
    closes: dt.time
    calendar: str          # "nse" (config calendar.holidays) or "own" (config markets.<key>.holidays)


SEGMENTS: dict[str, Segment] = {s.key: s for s in (
    Segment("nse_fo", "NSE index and stock F&O", dt.time(9, 15), dt.time(15, 30), "nse"),
    Segment("bse_fo", "BSE index F&O", dt.time(9, 15), dt.time(15, 30), "nse"),
    Segment("nse_cds", "NSE currency derivatives", dt.time(9, 0), dt.time(17, 0), "own"),
    Segment("mcx", "MCX commodity derivatives", dt.time(9, 0), MCX_EARLY_CLOSE, "own"),
)}


def us_dst(day: dt.date) -> bool:
    """US daylight saving time: from the second Sunday of March to the first Sunday of November (the date of the change)."""
    def nth_sunday(year, month, n):
        first = dt.date(year, month, 1)
        return first + dt.timedelta(days=(6 - first.weekday()) % 7 + 7 * (n - 1))
    return nth_sunday(day.year, 3, 2) <= day < nth_sunday(day.year, 11, 1)


def closes_at(seg: Segment, day: dt.date) -> dt.time:
    if seg.key == "mcx":
        return MCX_LATE_CLOSE if us_dst(day) else MCX_EARLY_CLOSE
    return seg.closes


class Calendars:
    """Holidays per segment, from config. `known(seg, day)` is False when the list for that year is not verified."""

    def __init__(self, cfg=None):
        self.nse_days = set(cfg.holidays()) if cfg is not None else set()
        self.nse_years = set(cfg.holiday_years()) if cfg is not None else set()
        self.special = dict(cfg.special_sessions()) if cfg is not None else {}        # NSE/BSE trading windows on days that are normally closed (Muhurat)
        self.own: dict[str, tuple[set[dt.date], set[int]]] = {}
        for key, seg in SEGMENTS.items():
            if seg.calendar != "own":
                continue
            days = {_d(x) for x in ((cfg.get(f"markets.{key}.holidays") if cfg is not None else None) or [])}
            years = {int(y) for y in ((cfg.get(f"markets.{key}.holiday_years") if cfg is not None else None) or [])}
            self.own[key] = (days, years)
        # MCX keeps its evening session on most NSE holidays and shuts only the morning. For TRADING, a weekday NSE holiday that MCX does not list as a full closure counts as
        # evening-only (opens 17:00), as does any date in markets.mcx.evening_only: conservative, so a closed morning is never traded; at worst an open one is missed.
        listed = {_d(x) for x in ((cfg.get("markets.mcx.evening_only") if cfg is not None else None) or [])}
        self.mcx_evening = listed | {d for d in self.nse_days if d.weekday() < 5 and d not in self.own.get("mcx", (set(), set()))[0]}

    def known(self, key: str, day: dt.date) -> bool:
        years = self.nse_years if SEGMENTS[key].calendar == "nse" else self.own[key][1]
        return day.year in years

    def holiday(self, key: str, day: dt.date) -> bool:
        return day in (self.nse_days if SEGMENTS[key].calendar == "nse" else self.own[key][0])


def _d(x) -> dt.date:
    return x if isinstance(x, dt.date) else dt.date.fromisoformat(str(x))


def session(key: str, day: dt.date, cal: Calendars, trading: bool = False) -> tuple[dt.datetime, dt.datetime] | None:
    """(open, close) of `key` on `day` in IST, or None if it does not trade that day (see the module doc for `trading`)."""
    seg = SEGMENTS[key]
    if trading and seg.calendar == "nse" and day in cal.special:           # an exchange-announced special session: only for trading questions, never for the recording calendar
        o, c = cal.special[day]
        return (dt.datetime.combine(day, o, tzinfo=IST), dt.datetime.combine(day, c, tzinfo=IST))
    if day.weekday() >= 5 or cal.holiday(key, day):
        return None
    if trading and not cal.known(key, day):
        return None
    opens = MCX_EVENING_OPEN if trading and key == "mcx" and day in cal.mcx_evening else seg.opens
    return (dt.datetime.combine(day, opens, tzinfo=IST), dt.datetime.combine(day, closes_at(seg, day), tzinfo=IST))


def exit_session(key: str, day: dt.date, cal: Calendars) -> tuple[dt.datetime, dt.datetime] | None:
    """The window in which a HELD position may be sold: the recording calendar (an exit needs only that the market is open, even where the holiday list is unverified), or an announced
    special session. A position bought in a special session must be sellable in it."""
    return session(key, day, cal, trading=False) or session(key, day, cal, trading=True)


def open_segments(now: dt.datetime, cal: Calendars, trading: bool = False) -> list[str]:
    now = now.astimezone(IST)
    out = []
    for key in SEGMENTS:
        s = session(key, now.date(), cal, trading)
        if s and s[0] <= now < s[1]:
            out.append(key)
    return out


def day_window(day: dt.date, cal: Calendars, trading: bool = False) -> tuple[dt.datetime, dt.datetime] | None:
    """From the earliest open to the latest close of any segment on `day`; None if nothing trades."""
    ss = [s for k in SEGMENTS if (s := session(k, day, cal, trading))]
    return (min(s[0] for s in ss), max(s[1] for s in ss)) if ss else None


def plan_jobs(day: dt.date, cal: Calendars, *, lead_min: int = 25, tail_min: int = 5, max_job_min: int = 330,
              trading: bool = False) -> list[dict]:
    """Split the day into chained jobs, each at most `max_job_min` minutes (a hosted job may run six hours; the margin pays for
    setup, handover and the flush at the end). The first job starts `lead_min` before the earliest open (login and warm-up), the
    last ends `tail_min` after the latest close. Consecutive jobs overlap by nothing: each starts where the last ended, and the
    next one is started by the previous one's last step, so there is never a gap or two jobs recording at once."""
    w = day_window(day, cal, trading)
    if not w:
        return []
    start, end = w[0] - dt.timedelta(minutes=lead_min), w[1] + dt.timedelta(minutes=tail_min)
    n = max(1, -(-int((end - start).total_seconds() // 60) // max_job_min))
    step = (end - start) / n
    jobs = []
    for i in range(n):
        a, b = start + step * i, start + step * (i + 1)
        jobs.append({"n": i + 1, "of": n, "from": a.isoformat(), "until": b.isoformat(),
                     "minutes": int((b - a).total_seconds() // 60),
                     "segments": [k for k in SEGMENTS if (s := session(k, day, cal, trading)) and s[0] < b and s[1] > a]})
    return jobs
