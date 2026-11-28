"""News phase P1: the historical corpus the one-time labelling run and the event library are built from.

What the P0 probe found answers from GitHub Actions (28 Nov 2026):
  * NSE corporate announcements, back to 2019 with exact dissemination times and a short summary of each filing
    (results, board meetings, M&A, ratings, orders ...): the most reliable stock news there is.
  * Google News RSS with after:/before: dates: headlines from any past window (up to 100 a query), with their source.
BSE's API refuses Actions (403); GDELT's API allows one request in five seconds (kept for later, not needed here).

Two tables, one Parquet file per source and year (news_nse_2019.parquet, news_gnews_2019.parquet ...), on the
`news-corpus` release. Every row: id (a hash of the source's own key), ts (UTC), ts_quality ("exact" or "day": Google's
dates are often a day stamp, and P2 must not pretend to know the minute), source, kind ("filing" | "headline"), symbol
(the stock a filing is about, or the instrument a query was for), title, summary, publisher, query, link.

Resumable: done.json lists every (source, window) already fetched, so a run that stops is continued by the next one.
Read-only on the web: GETs only. Nothing here is a price or a position.
"""
from __future__ import annotations

import datetime as dt
import email.utils
import hashlib
import json
import re
import time
from html import unescape
from pathlib import Path

import pandas as pd
import requests

from ..universe import INDICES, STOCKS

COLS = ["id", "ts", "ts_quality", "source", "kind", "symbol", "title", "summary", "publisher", "query", "link"]
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
      "Accept": "application/rss+xml, application/xml, text/xml, */*", "Accept-Language": "en-IN,en;q=0.9"}
NSE_FROM = dt.date(2019, 1, 1)

# filings that never carry market news (certificates, newspaper copies, routine compliance)
ROUTINE = re.compile(r"loss of share certificate|duplicate share certificate|copy of newspaper|newspaper publication|"
                     r"trading window|certificate under (?:sebi|reg)|compliance certificate|shareholders meeting|"
                     r"closure of trading|issue of duplicate|transfer of shares|transmission of shares|"
                     r"record date for interest|statement of investor complaints|depositories and participants", re.I)

# Google News queries: each watchlist instrument by its name, plus the macro channels that move all of them
MACRO = {
    "MACRO:RBI": '"RBI" (repo OR policy OR governor OR liquidity)',
    "MACRO:INFLATION": 'India (CPI OR inflation OR WPI)',
    "MACRO:GROWTH": 'India (GDP OR IIP OR PMI)',
    "MACRO:BUDGET": 'India (budget OR "fiscal deficit" OR GST)',
    "MACRO:FLOWS": '(FII OR FPI OR "foreign investors") India stocks',
    "MACRO:RUPEE": 'rupee dollar',
    "MACRO:CRUDE": '(crude OR Brent) oil prices',
    "MACRO:FED": '"Federal Reserve" OR "Fed rate" OR "US inflation"',
    "MACRO:GLOBAL": '("Wall Street" OR "Asian markets" OR "US stocks") close',
    "MACRO:GEOPOLITICS": 'India (Pakistan OR China OR border OR war OR sanctions OR tariff)',
    "MACRO:GOLD": 'gold prices',
    "MACRO:SEBI": 'SEBI (F&O OR derivatives OR rules OR circular)',
    "MACRO:MONSOON": 'India monsoon',
}
INDEX_Q = {"NIFTY": '"Nifty" OR "Sensex"', "BANKNIFTY": '"Bank Nifty" OR "banking stocks"', "FINNIFTY": '"Fin Nifty" OR "financial stocks" India',
           "MIDCPNIFTY": 'midcap stocks India', "NIFTYNXT50": '"Nifty Next 50"', "SENSEX": '"Sensex"', "BANKEX": '"Bankex" OR "bank stocks" BSE',
           "INDIAVIX": '"India VIX" OR "volatility index" India'}


def queries() -> dict[str, str]:
    q = {i.symbol: INDEX_Q.get(i.symbol, f'"{i.name}"') for i in INDICES}
    q["INDIAVIX"] = INDEX_Q["INDIAVIX"]
    for s in STOCKS:
        name = s.name.split(" (")[0]
        q[s.symbol] = f'"{name}"' + (' OR "Paytm"' if s.symbol == "PAYTM" else "")
    q.update(MACRO)
    return q


def _id(*parts) -> str:
    return hashlib.sha1("|".join(str(p) for p in parts).encode()).hexdigest()[:16]


# ---- NSE corporate announcements ---------------------------------------------------------------------------------------------
def parse_nse(rows: list, query: str = "") -> pd.DataFrame:
    out = []
    for r in rows or []:
        sym, subj = str(r.get("symbol") or "").strip(), str(r.get("desc") or "").strip()
        when = r.get("sort_date") or r.get("an_dt") or r.get("exchdisstime")
        ts = pd.to_datetime(when, errors="coerce", dayfirst=not str(when)[:4].isdigit())
        if not sym or pd.isna(ts):
            continue
        text = re.sub(r"\s+", " ", unescape(str(r.get("attchmntText") or ""))).strip()
        if ROUTINE.search(subj) or ROUTINE.search(text[:160]):
            continue
        out.append({"id": _id("nse", r.get("seq_id") or "", sym, when, subj), "ts": ts.tz_localize("Asia/Kolkata").tz_convert("UTC"),
                    "ts_quality": "exact", "source": "nse", "kind": "filing", "symbol": sym, "title": subj, "summary": text[:1200],
                    "publisher": "NSE", "query": query, "link": str(r.get("attchmntFile") or "")[:300]})
    return pd.DataFrame(out, columns=COLS)


def fetch_nse(nse, day: dt.date) -> pd.DataFrame:
    s = f"{day:%d-%m-%Y}"
    j, raw, url = nse.api(f"/api/corporate-announcements?index=equities&from_date={s}&to_date={s}")
    rows = j if isinstance(j, list) else (j or {}).get("data", [])
    return parse_nse(rows)


# ---- Google News RSS ---------------------------------------------------------------------------------------------------------
ITEM = re.compile(r"<item>(.*?)</item>", re.S)
TAG = lambda t: re.compile(rf"<{t}[^>]*>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</{t}>", re.S)        # noqa: E731
T_TITLE, T_LINK, T_DATE, T_SRC = TAG("title"), TAG("link"), TAG("pubDate"), TAG("source")


def parse_gnews(xml: str, symbol: str, query: str) -> pd.DataFrame:
    out = []
    for it in ITEM.findall(xml or ""):
        title = unescape((T_TITLE.search(it) or [None, ""])[1]).strip()
        pub = unescape((T_SRC.search(it) or [None, ""])[1]).strip()
        if pub and title.endswith(" - " + pub):
            title = title[: -len(pub) - 3].strip()
        d = (T_DATE.search(it) or [None, ""])[1].strip()
        try:
            ts = pd.Timestamp(email.utils.parsedate_to_datetime(d)).tz_convert("UTC")
        except Exception:                                        # noqa: BLE001 - an item without a date is no use
            continue
        if not title:
            continue
        exact = not (ts.minute == 0 and ts.second == 0)          # Google stamps many old stories at a round hour: a day, not a time
        link = unescape((T_LINK.search(it) or [None, ""])[1]).strip()
        out.append({"id": _id("gnews", title.lower(), pub.lower()), "ts": ts, "ts_quality": "exact" if exact else "day",
                    "source": "gnews", "kind": "headline", "symbol": symbol, "title": title[:400], "summary": "",
                    "publisher": pub[:80], "query": query, "link": link[:300]})
    return pd.DataFrame(out, columns=COLS)


def fetch_gnews(session, symbol: str, query: str, a: dt.date, b: dt.date) -> pd.DataFrame:
    q = f"{query} after:{a:%Y-%m-%d} before:{b:%Y-%m-%d}"
    url = "https://news.google.com/rss/search?q=" + requests.utils.quote(q) + "&hl=en-IN&gl=IN&ceid=IN:en"
    r = session.get(url, headers=UA, timeout=30)
    r.raise_for_status()
    return parse_gnews(r.text, symbol, query)


def windows(a: dt.date, b: dt.date, days: int):
    while a < b:
        e = min(b, a + dt.timedelta(days=days))
        yield a, e
        a = e


# ---- the store ---------------------------------------------------------------------------------------------------------------
class Corpus:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        p = self.root / "done.json"
        self.done = set(json.loads(p.read_text())) if p.exists() else set()

    def path(self, source: str, year: int) -> Path:
        return self.root / f"news_{source}_{year}.parquet"

    def add(self, df: pd.DataFrame) -> int:
        if df is None or df.empty:
            return 0
        n = 0
        df = df.copy()
        df["ts"] = pd.to_datetime(df["ts"], utc=True)
        for (src, yr), part in df.groupby([df["source"], df["ts"].dt.year]):
            p = self.path(src, int(yr))
            old = pd.read_parquet(p) if p.exists() else pd.DataFrame(columns=COLS)
            both = pd.concat([old, part[COLS]], ignore_index=True).drop_duplicates("id", keep="first")
            n += len(both) - len(old)
            both.sort_values("ts").to_parquet(p, index=False)
        return n

    def mark(self, key: str):
        self.done.add(key)
        (self.root / "done.json").write_text(json.dumps(sorted(self.done)))

    def files(self) -> list[str]:
        return sorted(p.name for p in self.root.glob("news_*.parquet")) + ["done.json"]

    def read(self, source: str | None = None) -> pd.DataFrame:
        ps = sorted(self.root.glob(f"news_{source or '*'}_*.parquet"))
        return pd.concat([pd.read_parquet(p) for p in ps], ignore_index=True) if ps else pd.DataFrame(columns=COLS)


def collect(corpus: Corpus, start: dt.date, end: dt.date, sources=("nse", "gnews"), nse=None, session=None,
            say=print, pause: float = 1.0, budget_s: float = 5.5 * 3600, clock=time.monotonic, sleep=time.sleep) -> dict:
    """Fill every (source, window) in [start, end) not yet done, until the time budget runs out (the next run continues)."""
    t0, counts = clock(), {"nse": 0, "gnews": 0, "windows": 0, "errors": 0}
    session = session or requests.Session()
    if "nse" in sources:
        if nse is None:
            from quantdesk.data import nse as N
            nse = N.NSE()
        for d in (start + dt.timedelta(days=i) for i in range((end - start).days)):
            if d < NSE_FROM:
                continue
            key = f"nse:{d}"
            if key in corpus.done:
                continue
            if clock() - t0 > budget_s:
                say("  time budget reached; the next run continues")
                return counts
            try:
                counts["nse"] += corpus.add(fetch_nse(nse, d))
                if d < dt.date.today() - dt.timedelta(days=3):       # a recent day may still gain filings
                    corpus.mark(key)
                counts["windows"] += 1
            except Exception as e:                               # noqa: BLE001 - one bad day is retried next run
                counts["errors"] += 1
                say(f"  nse {d}: {type(e).__name__}: {str(e)[:100]}")
            sleep(pause)
            if counts["windows"] % 50 == 0:
                say(f"  … nse to {d}: {counts['nse']} new filings")
    if "gnews" in sources:
        qs = queries()
        for a, b in windows(start, end, 31):
            for sym, q in qs.items():
                key = f"gnews:{sym}:{a}"
                if key in corpus.done:
                    continue
                if clock() - t0 > budget_s:
                    say("  time budget reached; the next run continues")
                    return counts
                try:
                    df = fetch_gnews(session, sym, q, a, b)
                    if len(df) >= 95 and (b - a).days > 4:          # Google caps a query at 100: split the window and read it in parts
                        parts = [fetch_gnews(session, sym, q, x, y) for x, y in windows(a, b, max(2, (b - a).days // 4))]
                        df = pd.concat([df, *parts], ignore_index=True)
                    counts["gnews"] += corpus.add(df)
                    if b < dt.date.today() - dt.timedelta(days=3):
                        corpus.mark(key)
                    counts["windows"] += 1
                except Exception as e:                           # noqa: BLE001
                    counts["errors"] += 1
                    say(f"  gnews {sym} {a}: {type(e).__name__}: {str(e)[:100]}")
                    if "429" in str(e):
                        sleep(60)
                sleep(pause)
            say(f"  … gnews to {b}: {counts['gnews']} new headlines")
    return counts


def stats(corpus: Corpus) -> dict:
    out = {}
    for src in ("nse", "gnews"):
        df = corpus.read(src)
        if df.empty:
            continue
        ts = pd.to_datetime(df["ts"], utc=True)
        out[src] = {"rows": len(df), "from": str(ts.min().date()), "to": str(ts.max().date()),
                    "exact_time": round(float((df["ts_quality"] == "exact").mean()), 3),
                    "by_year": {int(k): int(v) for k, v in ts.dt.year.value_counts().sort_index().items()},
                    "top_symbols": {k: int(v) for k, v in df["symbol"].value_counts().head(12).items()}}
    return out
