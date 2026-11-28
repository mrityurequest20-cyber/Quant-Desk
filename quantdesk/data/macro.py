"""The global macro calendar: scheduled events that move Indian markets, kept as the warehouse table `macro_events`.

Sources (what answers from GitHub Actions, checked by marketlens/probe.py on 28 Nov 2026):
  * Forex Factory's weekly calendar (nfs.faireconomy.media/ff_calendar_thisweek.json): every scheduled release and
    central-bank decision of the week for the US, euro area, UK, Japan, China, Canada, Australia, New Zealand and
    Switzerland, with its time, impact (High/Medium/Low), the market's forecast and the previous reading. Read on every
    run, so the table keeps every week it has seen: the history grows from the first run on.
  * The Federal Reserve's FOMC calendar page: every meeting date for the current and recent years (decision = the
    meeting's last day, 14:00 New York time).
  * FRED (St. Louis Fed), when a FRED_API_KEY is set: the release dates of US CPI, the jobs report (NFP), GDP and
    personal income and outlays (PCE), back to 2019 and the scheduled ones ahead; all at 08:30 New York time. This is
    the US data's history for the event studies (Forex Factory only gives the current week).
  * India (no INR in Forex Factory): RBI MPC decisions from the checked list in quantdesk/premarket/macro_dates.json;
    MoSPI's releases by their published rules (CPI on the 12th, IIP on the 28th (the 12th before 2025), GDP on the last working day of Feb,
    May, Aug and Nov, all at 16:00 IST; the next working day when the date is a weekend), marked source "rule" because
    MoSPI can move a date; the Union Budget on 1 Feb.
Every row: date and time in IST, country, title, kind (a normalised name the event studies group by), impact,
forecast, previous, source and when it was read. Nothing here is a price; read-only GETs.
"""
from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path

import pandas as pd

FF_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
FED_URL = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
IST = "Asia/Kolkata"
FRED_DATES = "https://api.stlouisfed.org/fred/release/dates"
# FRED release id -> (title, kind); every one is published at 08:30 New York time
FRED_RELEASES = {10: ("CPI (consumer prices)", "us_cpi"), 50: ("Employment Situation (jobs, NFP)", "us_nfp"),
                 53: ("GDP", "us_gdp"), 54: ("Personal income and outlays (PCE)", "us_pce")}
COLS = ["date", "time_ist", "country", "title", "kind", "impact", "forecast", "previous", "source"]
MACRO_DATES = Path(__file__).resolve().parents[1] / "premarket" / "macro_dates.json"

# normalised kinds: (country, title pattern) -> kind. The event studies group by kind; anything else keeps kind "other".
KINDS = [
    ("USD", r"federal funds rate|fomc statement", "fomc"),
    ("USD", r"^(core )?cpi m/m$|^cpi y/y$", "us_cpi"),
    ("USD", r"non-farm employment change", "us_nfp"),
    ("USD", r"(advance|prelim|final) gdp q/q", "us_gdp"),
    ("USD", r"core pce price index m/m", "us_pce"),
    ("USD", r"ism manufacturing pmi", "us_ism"),
    ("USD", r"fed chair .* speaks|powell speaks", "fed_chair"),
    ("EUR", r"main refinancing rate|monetary policy statement", "ecb"),
    ("GBP", r"official bank rate", "boe"),
    ("JPY", r"boj policy rate|monetary policy statement", "boj"),
    ("CNY", r"gdp q/y|^cpi y/y|manufacturing pmi", "china_data"),
    ("INR", r"rbi|repo rate", "rbi"),
    ("INR", r"^cpi", "india_cpi"),
    ("INR", r"^gdp", "india_gdp"),
    ("INR", r"^iip", "india_iip"),
    ("INR", r"budget", "budget"),
]
LABEL = {"fomc": "US Fed decision", "us_cpi": "US CPI", "us_nfp": "US jobs (NFP)", "us_gdp": "US GDP", "us_pce": "US PCE inflation",
         "us_ism": "US ISM manufacturing", "fed_chair": "Fed chair speaks", "ecb": "ECB decision", "boe": "Bank of England decision",
         "boj": "Bank of Japan decision", "china_data": "China data", "rbi": "RBI policy decision", "india_cpi": "India CPI",
         "india_gdp": "India GDP", "india_iip": "India IIP", "budget": "Union Budget", "election": "Election results",
         "geopolitics": "Geopolitical shock", "oil_shock": "Oil shock", "other": "Other"}


def kind_of(country: str, title: str) -> str:
    t = str(title or "").strip().lower()
    for c, pat, k in KINDS:
        if c == country and re.search(pat, t):
            return k
    return "other"


def parse_ff(payload) -> pd.DataFrame:
    """Forex Factory's weekly JSON -> rows. Its times carry their own UTC offset (New York time); they become IST."""
    ev = json.loads(payload) if isinstance(payload, (bytes, str)) else payload
    rows = []
    for e in ev or []:
        try:
            ts = pd.Timestamp(e["date"])
        except (KeyError, ValueError, TypeError):
            continue
        ny = ts.tz_convert("America/New_York") if ts.tzinfo else ts.tz_localize("America/New_York")
        all_day = ny.hour == 0 and ny.minute == 0                  # Forex Factory's all-day and tentative items sit at midnight
        ts = ny.tz_convert(IST)
        rows.append({"date": pd.Timestamp(ts.date()), "time_ist": "" if all_day else ts.strftime("%H:%M"),
                     "country": str(e.get("country") or ""), "title": str(e.get("title") or "")[:120],
                     "kind": kind_of(str(e.get("country") or ""), e.get("title")), "impact": str(e.get("impact") or ""),
                     "forecast": str(e.get("forecast") or ""), "previous": str(e.get("previous") or ""), "source": "forexfactory"})
    return pd.DataFrame(rows, columns=COLS)


def fred_url(release_id: int, key: str, start: str = "2019-01-01") -> str:
    return (f"{FRED_DATES}?release_id={release_id}&api_key={key}&file_type=json&realtime_start={start}"
            f"&realtime_end=9999-12-31&include_release_dates_with_no_data=true&sort_order=asc&limit=10000")


def parse_fred(payload, release_id: int) -> pd.DataFrame:
    """FRED's release/dates JSON -> rows: each date at 08:30 New York, in IST (19:00 or 18:00 with US daylight time)."""
    d = json.loads(payload) if isinstance(payload, (bytes, str)) else payload
    title, kind = FRED_RELEASES[release_id]
    rows = []
    for r in (d or {}).get("release_dates", []):
        try:
            ny = pd.Timestamp(f"{r['date']} 08:30").tz_localize("America/New_York")
        except (KeyError, ValueError, TypeError):
            continue
        t = ny.tz_convert(IST)
        rows.append({"date": pd.Timestamp(t.date()), "time_ist": t.strftime("%H:%M"), "country": "USD", "title": title, "kind": kind,
                     "impact": "High", "forecast": "", "previous": "", "source": "fred"})
    return pd.DataFrame(rows, columns=COLS).drop_duplicates(["date", "title"])


MONTHS = {m: i for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july", "august", "september",
                                      "october", "november", "december"], 1)}
MON3 = {m[:3]: i for m, i in MONTHS.items()}


def parse_fed(html: str) -> pd.DataFrame:
    """The Fed's FOMC calendar page -> one row per meeting, on its decision day (the last day; 14:00 New York)."""
    rows = []
    parts = re.split(r"(\d{4}) FOMC Meetings", html or "")
    for k in range(1, len(parts) - 1, 2):
        year, body = int(parts[k]), parts[k + 1]
        months = re.findall(r'fomc-meeting__month[^>]*>\s*(?:<strong>)?\s*([A-Za-z/]+)', body)
        dates = re.findall(r'fomc-meeting__date[^>]*>\s*([0-9][0-9\-\s*]*)', body)
        for mo, da in zip(months, dates):
            ms = [MON3.get(x.strip().lower()[:3]) for x in mo.split("/")]
            days = [int(x) for x in re.findall(r"\d+", da)]
            if not days or not all(ms):
                continue
            m = ms[-1] if len(ms) > 1 and (len(days) == 1 or days[-1] < days[0]) else ms[0]
            try:
                ny = pd.Timestamp(year=year, month=m, day=days[-1], hour=14, tz="America/New_York")
            except ValueError:
                continue
            t = ny.tz_convert(IST)
            rows.append({"date": pd.Timestamp(t.date()), "time_ist": t.strftime("%H:%M"), "country": "USD",
                         "title": "FOMC decision" + (" (with projections)" if "*" in da else ""), "kind": "fomc", "impact": "High",
                         "forecast": "", "previous": "", "source": "federalreserve.gov"})
    return pd.DataFrame(rows, columns=COLS).drop_duplicates(["date", "title"])


def _working(d: dt.date, holidays: set) -> dt.date:
    while d.weekday() >= 5 or d in holidays:
        d += dt.timedelta(days=1)
    return d


def _last_working(y: int, m: int, holidays: set) -> dt.date:
    d = (pd.Timestamp(year=y, month=m, day=1) + pd.offsets.MonthEnd(0)).date()
    while d.weekday() >= 5 or d in holidays:
        d -= dt.timedelta(days=1)
    return d


def india_rules(start: dt.date, end: dt.date, holidays: set = frozenset()) -> pd.DataFrame:
    """MoSPI's releases by their published rules, and the Union Budget. Source 'rule': MoSPI can move a date."""
    rows = []
    for y in range(start.year, end.year + 1):
        for m in range(1, 13):
            iip_day = 28 if y >= 2025 else 12                        # MoSPI moved IIP from the 12th to the 28th in 2025
            for title, kind, d, imp in (("CPI inflation y/y", "india_cpi", _working(dt.date(y, m, 12), holidays), "High"),
                                        ("IIP (industrial output) y/y", "india_iip", _working(dt.date(y, m, iip_day), holidays), "Medium")):
                rows.append({"date": pd.Timestamp(d), "time_ist": "16:00", "country": "INR", "title": title, "kind": kind, "impact": imp,
                             "forecast": "", "previous": "", "source": "rule"})
            if m in (2, 5, 8, 11):
                rows.append({"date": pd.Timestamp(_last_working(y, m, holidays)), "time_ist": "16:00", "country": "INR", "title": "GDP growth y/y",
                             "kind": "india_gdp", "impact": "High", "forecast": "", "previous": "", "source": "rule"})
        rows.append({"date": pd.Timestamp(dt.date(y, 2, 1)), "time_ist": "11:00", "country": "INR", "title": "Union Budget", "kind": "budget",
                     "impact": "High", "forecast": "", "previous": "", "source": "rule"})
    df = pd.DataFrame(rows, columns=COLS)
    return df[(df["date"].dt.date >= start) & (df["date"].dt.date <= end)]


def checked_history(path: Path = MACRO_DATES) -> pd.DataFrame:
    """The desk's checked list of past macro days (RBI MPC, FOMC, Budget, elections, geopolitical and oil shocks)."""
    try:
        kinds = json.loads(path.read_text())["kinds"]
    except (OSError, ValueError, KeyError):
        return pd.DataFrame(columns=COLS)
    ctry = {"rbi": "INR", "budget": "INR", "election": "INR", "fomc": "USD", "geopolitics": "WORLD", "oil_shock": "WORLD"}
    rows = [{"date": pd.Timestamp(d), "time_ist": "", "country": ctry.get(k, "WORLD"), "title": v.get("label", k), "kind": k,
             "impact": "High", "forecast": "", "previous": "", "source": "desk list"} for k, v in kinds.items() for d in v.get("dates", [])]
    return pd.DataFrame(rows, columns=COLS)
