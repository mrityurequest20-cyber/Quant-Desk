"""The market-data warehouse: tidy Parquet tables built from NSE's public files, kept as assets of the
`warehouse` GitHub release (release assets don't bloat the git history; a branch would).

Tables (one file per period, `{table}_{period}.parquet`):
  fo_bhav           month  every index future and option, daily: OHLC, close, settle, underlying, OI, volume
  fo_stocks         month  each F&O stock's near-month liquidity, daily: option contracts and premium traded, OI,
                           active strikes, ATM straddle, futures volume/OI (the same bhavcopy file)
  fo_stock_opts     month  every F&O stock's options and futures, daily, in fo_bhav's columns: the nearest two
                           expiries, strikes within ±30% that traded or are open (the same file, kept, not discarded)
  cm_bhav           month  the cash market's day by security (equity series): OHLC, volume, turnover, trades, delivered
                           quantity and delivery %, from NSE's sec_bhavdata_full (published from 30 Sep 2019)
  fo_stock_far      month  the same for each stock's third expiry, the far month (with fo_stock_opts: current, near and
                           far month). Its own table so fo_stock_opts' readers and studies see exactly what they did
  bse_fo_bhav       month  BSE's index futures and options (SENSEX, BANKEX), daily, in fo_bhav's columns (from 2024)
  nse_index_close   year   NSE's official closing value of every index, daily (ind_close_all): the price NSE's
                           index options settle on, and the true spot on days the bhavcopy has no underlying column
  participant_oi    year   FII / DII / Pro / Client open interest by product, daily (contracts)
  participant_vol   year   the same for volume
  fii_dii           year   FII/FPI and DII cash-market buy/sell/net, ₹ crore (NSE gives only the latest day:
                           this table grows from the day collection started)
  gift_nifty        year   GIFT Nifty prints with NIFTY's prior close (also from collection start)
  corp_events       year   board meetings / results from NSE's event calendar
  nse_holidays      year   the exchange's F&O holiday list
  manifest          year   provenance: every file fetched, its URL, SHA-256, size, rows, and whether NSE had it

`update()` fills every missing day in a range (so a late or skipped run catches up by itself) and writes each
period once. Raw files aren't stored — they stay downloadable from NSE's archives and the manifest's checksums
say exactly which bytes each row came from."""
from __future__ import annotations

import datetime as dt
import json
import subprocess
from pathlib import Path

import pandas as pd

from . import bse as B
from . import nse as N

IST = "Asia/Kolkata"
TABLES = {                                   # table → (period, key columns, date column)
    "fo_bhav": ("month", ["date", "symbol", "kind", "expiry", "strike"], "date"),
    "fo_stocks": ("month", ["date", "symbol"], "date"),
    "fo_stock_opts": ("month", ["date", "symbol", "kind", "expiry", "strike"], "date"),
    "fo_stock_far": ("month", ["date", "symbol", "kind", "expiry", "strike"], "date"),
    "cm_bhav": ("month", ["date", "symbol", "series"], "date"),
    "bse_fo_bhav": ("month", ["date", "symbol", "kind", "expiry", "strike"], "date"),
    "nse_index_close": ("year", ["date", "index"], "date"),
    "participant_oi": ("year", ["date", "participant"], "date"),
    "participant_vol": ("year", ["date", "participant"], "date"),
    "fii_dii": ("year", ["date", "category"], "date"),
    "global_daily": ("year", ["date", "ticker"], "date"),
    "macro_events": ("year", ["date", "country", "title"], "date"),
    "gift_nifty": ("year", ["ts"], "ts"),
    "corp_events": ("year", ["date", "symbol", "purpose"], "date"),
    "nse_holidays": ("year", ["date"], "date"),
    "manifest": ("year", ["table", "date"], "date"),
}
DATE_COLS = ("date", "expiry")
DAILY_FILES = ("fo_bhav", "fo_stocks", "fo_stock_opts", "fo_stock_far", "cm_bhav", "bse_fo_bhav", "nse_index_close", "participant_oi",
               "participant_vol")
# Sessions NSE held on a Saturday or Sunday (Muhurat trading, Budget days, disaster-recovery drill days), found by
# reading every weekend's cash bhavcopy since 2019 and keeping the ones whose rows carry that day's own date (on other
# weekends and holidays the archive serves a copy of the session before). A weekday list never asks for them, so every
# table missed them. New ones are found by update() itself (weekend_sessions), this list is the history.
SPECIAL_SESSIONS = (dt.date(2019, 10, 27), dt.date(2020, 2, 1), dt.date(2020, 11, 14), dt.date(2023, 11, 12),
                    dt.date(2024, 1, 20), dt.date(2024, 3, 2), dt.date(2024, 5, 18), dt.date(2025, 2, 1),
                    dt.date(2026, 2, 1), dt.date(2026, 11, 8))
SETTLE_DAYS = 3                              # a file still missing this many days later is taken as never coming


class Warehouse:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.dirty: set[str] = set()                                    # file names written since load

    @staticmethod
    def period(table: str, d) -> str:
        d = pd.Timestamp(d)
        return f"{d:%Y-%m}" if TABLES[table][0] == "month" else f"{d:%Y}"

    def path(self, table: str, period: str) -> Path:
        return self.root / f"{table}_{period}.parquet"

    def files(self, table: str) -> list[Path]:
        return sorted(self.root.glob(f"{table}_*.parquet"))

    def read(self, table: str, start=None, end=None) -> pd.DataFrame:
        col = TABLES[table][2]
        parts = []
        for p in self.files(table):
            per = p.stem[len(table) + 1:]
            lo, hi = pd.Period(per).start_time, pd.Period(per).end_time
            if (start is not None and hi < pd.Timestamp(start)) or (end is not None and lo > pd.Timestamp(end)):
                continue
            parts.append(pd.read_parquet(p))
        if not parts:
            return pd.DataFrame()
        df = pd.concat(parts, ignore_index=True)
        t = pd.to_datetime(df[col])
        t = t.dt.tz_localize(None) if getattr(t.dt, "tz", None) is not None else t
        keep = pd.Series(True, index=df.index)
        if start is not None:
            keep &= t >= pd.Timestamp(start)
        if end is not None:
            keep &= t <= pd.Timestamp(end) + pd.Timedelta(days=1) - pd.Timedelta(microseconds=1)
        return df[keep].reset_index(drop=True)

    def upsert(self, table: str, df: pd.DataFrame) -> int:
        """Add rows (replacing any with the same keys) to the table's period files. Returns rows written."""
        if df is None or df.empty:
            return 0
        _, keys, col = TABLES[table]
        df = df.copy()
        for c in DATE_COLS:
            if c in df.columns:
                df[c] = pd.to_datetime(df[c])
        per = pd.to_datetime(df[col]).map(lambda x: self.period(table, x))
        n = 0
        for p, part in df.groupby(per):
            path = self.path(table, p)
            if path.exists():
                old = pd.read_parquet(path)
                part = pd.concat([old, part], ignore_index=True)
            part = part.drop_duplicates(keys, keep="last").sort_values(keys).reset_index(drop=True)
            part.to_parquet(path, index=False, compression="zstd")
            self.dirty.add(path.name)
            n += len(part)
        return n

    def coverage(self) -> pd.DataFrame:
        """Rows, first/last day and day count per table. The daily-file tables are counted from the manifest, so
        this works with only the small files pulled."""
        rows = []
        man = self.read("manifest")
        for t, (_, _, col) in TABLES.items():
            if t in DAILY_FILES and not man.empty:
                m = man[(man["table"] == t) & (man["status"] == "ok")]
                d = pd.to_datetime(m["date"])
                rows.append({"table": t, "rows": int(m["rows"].sum()), "first": d.min().date() if len(d) else None,
                             "last": d.max().date() if len(d) else None, "days": d.nunique(),
                             "files": len(self.files(t))})
                continue
            df = self.read(t)
            if df.empty:
                rows.append({"table": t, "rows": 0, "first": None, "last": None, "days": 0, "files": 0})
                continue
            d = pd.to_datetime(df[col])
            d = d.dt.tz_localize(None) if getattr(d.dt, "tz", None) is not None else d
            rows.append({"table": t, "rows": len(df), "first": d.min().date(), "last": d.max().date(),
                         "days": d.dt.normalize().nunique(), "files": len(self.files(t))})
        return pd.DataFrame(rows)


# ---- filling it ---------------------------------------------------------------------------------------------------
def weekend_sessions(nse, start: dt.date, end: dt.date, today: dt.date, say=print, max_days: int = 21) -> list[dt.date]:
    """Weekend days in a short recent range (a nightly run's) on which NSE held a session: its cash bhavcopy for that
    day exists and carries that day's own date. A long backfill does not probe every weekend (SPECIAL_SESSIONS holds
    the history). One small request per weekend day; any failure means no session."""
    if (end - start).days > max_days:
        return []
    found = []
    for d in pd.date_range(start, end):
        d = d.date()
        if d.weekday() < 5 or d in SPECIAL_SESSIONS or d > today or d < N.CM_BHAV_FROM:      # the probe file's archive starts then
            continue
        try:
            b, _ = nse.cm_bhav(d)
            N.parse_cm_bhav(b, d)                                          # raises NotPublished on a copy of another day
            found.append(d)
            say(f"  a weekend session on {d}: fetched like a weekday")
        except Exception:                                                  # noqa: BLE001 - absent, a copy, or unreadable: no session
            continue
    return found


def _settled(man: pd.DataFrame, table: str, today: dt.date) -> set[dt.date]:
    """Days a table needs nothing more for: fetched, or confirmed absent (NSE still had nothing SETTLE_DAYS later)."""
    if man.empty:
        return set()
    m = man[man["table"] == table]
    d = pd.to_datetime(m["date"]).dt.date
    fetched = pd.to_datetime(m["fetched"], utc=True).dt.tz_convert(IST).dt.date
    ok = m["status"] == "ok"
    gone = (m["status"] == "none") & ((fetched - d).map(lambda x: x.days) >= SETTLE_DAYS)
    return set(d[ok | gone])


def update(wh: Warehouse, nse: N.NSE, start: dt.date, end: dt.date, only: set[str] | None = None,
           holidays: set[dt.date] | None = None, say=print, today: dt.date | None = None,
           checkpoint_every: int = 60, on_checkpoint=None, refetch: bool = False, bse=None) -> dict:
    """Fetch every missing trading day in [start, end] for the daily files, plus today's API snapshots when the range
    reaches today. Returns counts per table."""
    sim = today is not None
    today = today or pd.Timestamp.now(tz=IST).date()
    only = only or set(DAILY_FILES) | {"fii_dii", "gift_nifty", "corp_events", "nse_holidays", "global_daily", "macro_events"}
    holidays = holidays or set()
    days = [d.date() for d in pd.bdate_range(start, min(end, today)) if d.date() not in holidays]
    days = sorted(set(days) | {d for d in SPECIAL_SESSIONS if start <= d <= min(end, today)}
                  | set(weekend_sessions(nse, start, min(end, today), today, say)))
    man = wh.read("manifest")
    counts: dict[str, int] = {}
    stamp = (lambda: pd.Timestamp(today, tz=IST)) if sim else (lambda: pd.Timestamp.now(tz=IST))   # noqa: E731
    if "bse_fo_bhav" in only and bse is None:
        bse = B.BSE()
    fetchers = {"fo_bhav": (nse.fo_bhav, N.parse_fo_bhav),
                "fo_stocks": (nse.fo_bhav, N.parse_fo_stocks),
                "fo_stock_opts": (nse.fo_bhav, N.parse_fo_stock_opts),
                "fo_stock_far": (nse.fo_bhav, N.parse_fo_stock_far),
                "cm_bhav": (nse.cm_bhav, N.parse_cm_bhav),
                "bse_fo_bhav": (bse.fo_bhav if bse else None, B.parse_fo_bhav),
                "nse_index_close": (nse.index_close, N.parse_index_close),
                "participant_oi": (lambda d: nse.participant("oi", d), N.parse_participant),
                "participant_vol": (lambda d: nse.participant("vol", d), N.parse_participant)}
    for table in [t for t in DAILY_FILES if t in only]:
        fetch, parse = fetchers[table]
        done = set() if refetch else _settled(man, table, today)    # refetch: parse the range again (new columns)
        todo = [d for d in days if d not in done and (table != "bse_fo_bhav" or d >= B.BSE_FROM)
                and (table != "cm_bhav" or d >= N.CM_BHAV_FROM)]                  # nothing to ask for before the archive starts
        if not todo:
            continue
        say(f"  {table}: {len(todo)} day(s) to fetch, {todo[0]} → {todo[-1]}")
        buf, mbuf = [], []
        for i, d in enumerate(todo, 1):
            try:
                b, url = fetch(d)
                df = parse(b, d)
                buf.append(df)
                mbuf.append({"table": table, "date": d, "status": "ok", "url": url, "sha256": N.sha256(b),
                             "bytes": len(b), "rows": len(df), "fetched": stamp()})
            except N.NotPublished as exc:
                mbuf.append({"table": table, "date": d, "status": "none", "url": str(exc), "sha256": "", "bytes": 0,
                             "rows": 0, "fetched": stamp()})
            except Exception as exc:                                       # leave it for the next run
                say(f"    {table} {d}: {exc!s:.200}")
            if i % checkpoint_every == 0 or i == len(todo):
                if buf:
                    wh.upsert(table, pd.concat(buf, ignore_index=True))
                if mbuf:
                    wh.upsert("manifest", pd.DataFrame(mbuf))
                got = sum(len(x) for x in buf)
                counts[table] = counts.get(table, 0) + got
                say(f"    … {i}/{len(todo)} days, {sum(r['status'] == 'ok' for r in mbuf)} files, {got:,} rows")
                buf, mbuf = [], []
                if on_checkpoint:
                    on_checkpoint()
    if end >= today - dt.timedelta(days=1):
        _snapshots(wh, nse, only, counts, say)
    if "global_daily" in only:
        _globals(wh, start, min(end, today), counts, say, stamp)
    if "macro_events" in only:
        _macro(wh, today, counts, say, stamp, holidays)
    return counts


def _macro(wh: Warehouse, today: dt.date, counts: dict, say, stamp, holidays=frozenset(), get=None) -> None:
    """The global macro calendar (quantdesk/data/macro.py): this week's Forex Factory calendar, the Fed's FOMC dates, India's
    releases by MoSPI's rules from 2019 to four months ahead, and the desk's checked list of past macro days. Each
    source that fails is said and skipped; the table keeps what it already had."""
    from . import macro as M
    if get is None:
        import requests

        def get(url):
            r = requests.get(url, headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64)"}, timeout=30)
            r.raise_for_status()
            return r.content
    parts = [M.checked_history(), M.india_rules(dt.date(2019, 1, 1), today + dt.timedelta(days=120), set(holidays))]
    for name, url, parse in (("forexfactory", M.FF_URL, M.parse_ff), ("fed", M.FED_URL, lambda b: M.parse_fed(b.decode("utf-8", "replace")))):
        try:
            df = parse(get(url))
            parts.append(df)
            say(f"  macro_events {name}: {len(df)} events")
        except Exception as exc:                                       # noqa: BLE001 - one source failing skips only itself
            say(f"  macro_events {name}: {exc!s:.160}")
    df = pd.concat([p for p in parts if len(p)], ignore_index=True)
    if df.empty:
        return
    # one row per key; a later source (Forex Factory, the Fed) wins over the rule or the desk list for the same event
    df = df.drop_duplicates(["date", "country", "title"], keep="last")
    df["fetched"] = stamp()
    wh.upsert("macro_events", df)
    counts["macro_events"] = len(df)


# the international benchmarks MarketLens reads beside Indian markets (commodities against MCX, the dollar, US rates)
GLOBAL_TICKERS = {"CL=F": "WTI crude", "BZ=F": "Brent crude", "GC=F": "COMEX gold", "SI=F": "COMEX silver",
                  "HG=F": "COMEX copper", "NG=F": "Henry Hub gas", "DX-Y.NYB": "Dollar index", "^TNX": "US 10-year yield",
                  "INR=X": "USDINR", "^VIX": "CBOE VIX", "ES=F": "S&P 500 futures"}
GLOBAL_FROM = dt.date(2019, 1, 1)


def _globals(wh: Warehouse, start: dt.date, end: dt.date, counts: dict, say, stamp, history=None) -> None:
    """Daily OHLC of the international benchmarks from Yahoo (yfinance). Not an exchange's own file: every row carries
    its source and fetch time, and a ticker Yahoo will not serve is skipped and said, never filled. On a table that is
    still empty the whole history from GLOBAL_FROM is read once; after that, the run's range less a week of overlap
    (Yahoo revises the last bar after the close)."""
    if history is None:
        def history(tk, a, b):
            import yfinance as yf
            return yf.Ticker(tk).history(start=a.isoformat(), end=(b + dt.timedelta(days=1)).isoformat(), interval="1d", auto_adjust=False)
    have = wh.read("global_daily")
    a = GLOBAL_FROM if have.empty else max(GLOBAL_FROM, start - dt.timedelta(days=7))
    rows = []
    for tk, name in GLOBAL_TICKERS.items():
        try:
            h = history(tk, a, end)
        except Exception as exc:                                       # noqa: BLE001 - one ticker failing skips only itself
            say(f"  global_daily {tk}: {exc!s:.160}")
            continue
        if h is None or len(h) == 0:
            say(f"  global_daily {tk}: nothing served")
            continue
        h = h.rename(columns=str.lower)
        idx = pd.to_datetime(h.index)
        idx = idx.tz_localize(None) if idx.tz is not None else idx
        df = pd.DataFrame({"date": idx.normalize(), "ticker": tk, "name": name,
                           **{c: pd.to_numeric(h[c], errors="coerce").to_numpy() for c in ("open", "high", "low", "close", "volume") if c in h}})
        df = df[(df["close"] > 0) & (df["date"].dt.date <= end)]
        df["source"] = "yahoo"
        df["fetched"] = stamp()
        rows.append(df)
    if rows:
        df = pd.concat(rows, ignore_index=True)
        wh.upsert("global_daily", df)
        counts["global_daily"] = len(df)
        say(f"  global_daily: {len(df):,} rows, {df['ticker'].nunique()} tickers, {df['date'].min().date()} → {df['date'].max().date()}")


def _snapshots(wh: Warehouse, nse: N.NSE, only: set[str], counts: dict, say) -> None:
    """The API endpoints only show the present: take today's reading of each."""
    jobs = [("fii_dii", "/api/fiidiiTradeReact", N.parse_fii_dii),
            ("gift_nifty", "/api/marketStatus", lambda j: N.parse_gift(j)),
            ("corp_events", "/api/event-calendar", N.parse_events),
            ("nse_holidays", "/api/holiday-master?type=trading",
             lambda j: pd.DataFrame(N.parse_holidays(j), columns=["date", "description"]))]
    for table, path, parse in jobs:
        if table not in only:
            continue
        try:
            j, raw, url = nse.api(path)
            df = parse(j)
            wh.upsert(table, df)
            counts[table] = len(df)
            wh.upsert("manifest", pd.DataFrame([{"table": table, "date": pd.Timestamp.now(tz=IST).date(), "status": "ok",
                                                 "url": url, "sha256": N.sha256(raw), "bytes": len(raw), "rows": len(df),
                                                 "fetched": pd.Timestamp.now(tz=IST)}]))
            say(f"  {table}: {len(df)} row(s)")
        except Exception as exc:
            say(f"  {table}: FAIL {exc!s:.200}")


def holiday_diff(wh: Warehouse, configured: set[dt.date], year: int) -> tuple[list, list]:
    """(NSE holidays the config lacks, config holidays NSE doesn't list) for one year, weekdays only."""
    h = wh.read("nse_holidays")
    if h.empty:
        return [], []
    nse = {(d.date(), desc) for d, desc in zip(pd.to_datetime(h["date"]), h["description"]) if d.year == year and d.weekday() < 5}
    mine = {d for d in configured if d.year == year and d.weekday() < 5}
    return sorted(x for x in nse if x[0] not in mine), sorted(d for d in mine if d not in {x[0] for x in nse})


# ---- the GitHub release that holds it ------------------------------------------------------------------------------
class ReleaseStore:
    """Pull/push the warehouse's files as assets of one GitHub release, through the `gh` CLI (GH_TOKEN)."""

    def __init__(self, tag: str = "warehouse", repo: str | None = None, run=subprocess.run,
                 title: str = "Market-data warehouse",
                 notes: str = "NSE end-of-day data as Parquet tables, maintained by data.yml "
                              "(quantdesk/data/warehouse.py). Not a software release."):
        self.tag, self.repo, self._run, self.title, self.notes = tag, repo, run, title, notes

    def _gh(self, *args, check=True) -> subprocess.CompletedProcess:
        cmd = ["gh", *args] + (["-R", self.repo] if self.repo else [])
        return self._run(cmd, check=check, capture_output=True, text=True)

    def assets(self, strict: bool = False) -> list[str]:
        """Asset names; a missing release (or, unless strict, any failure) reads as none. strict raises on failure."""
        r = self._gh("release", "view", self.tag, "--json", "assets", check=strict)
        if r.returncode != 0:
            return []
        return [a["name"] for a in json.loads(r.stdout or "{}").get("assets", [])]

    def ensure(self) -> None:
        if self._gh("release", "view", self.tag, check=False).returncode != 0:
            self._gh("release", "create", self.tag, "--title", self.title, "--latest=false", "--notes", self.notes)

    def pull(self, dest: Path, names: list[str]) -> list[str]:
        have = set(self.assets())
        names = [n for n in names if n in have]
        for n in names:
            self._gh("release", "download", self.tag, "--pattern", n, "--dir", str(dest), "--clobber")
        return names

    def push(self, src: Path, names: list[str], clobber: bool = True) -> None:
        if not names:
            return
        self.ensure()
        for i in range(0, len(names), 20):
            self._gh("release", "upload", self.tag, *[str(src / n) for n in names[i:i + 20]], *(["--clobber"] if clobber else []))


def needed_assets(start: dt.date, end: dt.date, tables=TABLES) -> list[str]:
    """The period files an update over [start, end] reads or writes."""
    out = []
    for t, (per, _, _) in tables.items():
        rng = pd.period_range(start, end, freq="M" if per == "month" else "Y")
        out += [f"{t}_{p}.parquet" for p in rng.astype(str)]
    return out
