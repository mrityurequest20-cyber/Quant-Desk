"""Foreign exchange: the majors and the rupee crosses, as daily history and as 1-minute bars (`quantdesk data fx-daily`, `fx-minutes`; fx-daily.yml, fx-minutes.yml).

Why: nothing in the pipeline covered forex. Indian currency futures are in the Kite universe (and, only while the Kite recorder runs, recorded), but the global pairs they follow, and the
cash USD/INR, were not. Yahoo serves FX 24 hours a day on a weekday and works from a cloud runner (NSE and Kotak's candle API for MCX/currency do not: see docs/PIPELINE_READINESS.md);
the ECB publishes official daily reference rates for the same currencies, an independent source to check Yahoo against.

Daily history (since 2003): fetched from Yahoo, rows that cannot be a real bar dropped and counted (never repaired), one-day moves beyond 5% flagged (never smoothed), weekdays with no
row counted as gaps, and the closes compared with the rate the ECB implies for the pair. The ECB fixes at about 14:15 CET and Yahoo's daily close is later, so the check is a sanity check
(2% tolerance), not an exact match: it catches an inverted pair, a wrong decimal or a frozen series, not a basis point. A series is `verified` only if every check passes.

Minutes: Yahoo keeps seven days of 1-minute bars, so each nightly run re-reads the last five and a missed night heals. Bars are UTC (FX has no exchange session).

Market data only, public sources, no secret and no account. Nothing here trades. Output is immutable per run (a later run is a new dataset)."""
from __future__ import annotations

import datetime as dt
import io
import json
import time
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

from .daily_history import OHLC, clean
from .external_aeron import _write_once, frame_hash

VERSION = "fx-1"
PAIRS = {"EURUSD": "EURUSD=X", "GBPUSD": "GBPUSD=X", "USDJPY": "JPY=X", "AUDUSD": "AUDUSD=X", "USDCAD": "CAD=X", "USDCHF": "CHF=X", "NZDUSD": "NZDUSD=X",
         "USDINR": "INR=X", "EURINR": "EURINR=X", "GBPINR": "GBPINR=X", "JPYINR": "JPYINR=X", "DXY": "DX-Y.NYB"}
DXY_CONSTANT = 50.14348112
DXY_WEIGHTS = {"EUR": -0.576, "JPY": 0.136, "GBP": -0.119, "CAD": 0.091, "SEK": 0.042, "CHF": 0.036}
ECB_URL = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-hist.zip"
START = "2003-01-01"
JUMP = 0.05                    # a one-day move beyond this is flagged (the yen's 2024 intervention days were about 4%)
GAP_MAX = 0.01                 # missing weekdays / expected weekdays above which a series is called "gappy". A hole is a missing day, not a wrong value: it is reported (coverage), it does not make the values unverified
QUARANTINE_MAX = 0.005         # at most this share of a series' rows may be set aside as reverted bad prints; more than that and the series is unverified, not tidied
XCHECK_TOL, XCHECK_MIN, XCHECK_MATCH = 0.02, 30, 0.95      # 2%: the ECB fixes at 14:15 CET and Yahoo closes hours later, so 1% tripped on volatile days; an inverted pair or a wrong decimal is far beyond 2%
HOLIDAY_SHARE, HOLIDAY_MIN_PEERS = 0.75, 3                     # a weekday missing from this share of a group of at least this many pairs is a market holiday, not a gap
MINUTES_MAX_DAYS = 7           # what Yahoo keeps
MIN_ROWS_OK = 500              # a quiet FX day still has far more 1-minute bars than this
COLS_DAILY = ["date", "symbol", "open", "high", "low", "close", "volume", "source", "series_status"]
COLS_MIN = ["ts", "symbol", "open", "high", "low", "close", "volume"]


class SourceDown(Exception):
    """A source that could not serve the request: recorded, never raised past the run."""


def local_dates(idx: pd.DatetimeIndex) -> pd.DatetimeIndex:
    """The calendar date of each daily bar. Yahoo stamps a daily FX bar at midnight in its own zone (London): in summer that is 23:00 UTC the day before, so converting to UTC and
    taking the date moved every summer Monday onto a Sunday (the first real run found 14% of weekdays 'missing'). The date is the wall-clock date in the stamped zone."""
    idx = pd.DatetimeIndex(idx)
    return (idx.tz_localize(None) if idx.tz is not None else idx).normalize()


class YahooFx:
    def __init__(self, tries: int = 2, sleep=time.sleep):
        self.tries, self._sleep = tries, sleep

    def _history(self, symbol: str, keep_zone: bool = False, **kw) -> pd.DataFrame:
        try:
            import yfinance as yf
        except ImportError as exc:
            raise SourceDown("yfinance missing") from exc
        last = "no rows"
        for i in range(self.tries):
            try:
                raw = yf.Ticker(PAIRS[symbol]).history(auto_adjust=False, actions=False, **kw)
            except Exception as exc:
                last = f"{exc!s:.140}"
                self._sleep(1.0 * (i + 1))
                continue
            if raw is not None and len(raw):
                df = raw.rename(columns=str.lower)[[*OHLC, "volume"]].astype(float)
                idx = pd.DatetimeIndex(raw.index)
                if keep_zone:                                              # a daily bar: its date is the wall-clock date in the zone Yahoo stamped it in
                    df.index = idx
                else:                                                      # a minute bar: an instant, stored in UTC
                    df.index = idx.tz_convert("UTC") if idx.tz is not None else idx.tz_localize("UTC")
                return df[~df.index.duplicated(keep="last")].sort_index()
        raise SourceDown(f"yahoo {PAIRS[symbol]}: {last}")

    def minutes(self, symbol: str, days: int) -> pd.DataFrame:
        return self._history(symbol, period=f"{min(max(days, 1), MINUTES_MAX_DAYS)}d", interval="1m")

    def daily(self, symbol: str, start: dt.date, end: dt.date) -> pd.DataFrame:
        df = self._history(symbol, keep_zone=True, start=str(start), end=str(end + dt.timedelta(days=1)), interval="1d")
        df.index = local_dates(df.index)
        df.index.name = "date"
        return df[~df.index.duplicated(keep="last")]


class EcbReference:
    """The ECB's euro foreign exchange reference rates (units of a currency per euro, one row a TARGET day since 1999)."""

    def __init__(self, fetch=None):
        self._fetch, self._t = fetch, None

    def table(self) -> pd.DataFrame:
        if self._t is None:
            try:
                b = self._fetch() if self._fetch else self._download()
                with zipfile.ZipFile(io.BytesIO(b)) as z:
                    t = pd.read_csv(z.open(next(n for n in z.namelist() if n.lower().endswith(".csv"))), na_values=["N/A"])
            except Exception as exc:
                raise SourceDown(f"ecb: {exc!s:.140}") from exc
            t.columns = [str(c).strip() for c in t.columns]
            t = t.loc[:, [c for c in t.columns if not c.startswith("Unnamed")]]
            t["Date"] = pd.to_datetime(t["Date"])
            self._t = t.set_index("Date").sort_index().apply(pd.to_numeric, errors="coerce")
            self._t["EUR"] = 1.0
        return self._t

    @staticmethod
    def _download() -> bytes:
        import requests
        r = requests.get(ECB_URL, timeout=60, headers={"User-Agent": "quantdesk-fx/1"})
        r.raise_for_status()
        return r.content

    def implied(self, symbol: str) -> pd.Series | None:
        """The pair's price the ECB rates imply (quote per base), or None where the ECB has no such currency (the dollar index)."""
        base, quote = symbol[:3], symbol[3:]
        t = self.table()
        if symbol == "DXY":
            return self._dxy(t)
        if base not in t or quote not in t:
            return None
        s = (t[quote] / t[base]).dropna()
        return s if len(s) else None

    @staticmethod
    def _dxy(t: pd.DataFrame) -> pd.Series | None:
        """The dollar index rebuilt from the ECB's rates with ICE's published formula (a geometric basket: euro, yen, sterling, Canadian dollar, krona, franc). An independent
        reconstruction, not the index's own print: it is good to a percent or so, which is what the 2% cross-check asks."""
        if not set(DXY_WEIGHTS) <= set(t.columns) | {"USD"}:
            return None
        usd = t["USD"]
        legs = {"EUR": usd, "GBP": usd / t["GBP"] if "GBP" in t else None}                        # dollars per euro, dollars per pound
        for c in ("JPY", "CAD", "SEK", "CHF"):
            legs[c] = t[c] / usd if c in t else None                                              # units of the currency per dollar
        if any(v is None for v in legs.values()):
            return None
        out = DXY_CONSTANT * pd.concat([legs[c] ** w for c, w in DXY_WEIGHTS.items()], axis=1).prod(axis=1, skipna=False)
        out = out.dropna()
        return out if len(out) else None


def peer_holidays(dfs: dict[str, pd.DataFrame]) -> dict[str, frozenset]:
    """Weekdays on which a group of pairs did not trade: missing from at least HOLIDAY_SHARE of the pairs whose history covers the day (a group needs HOLIDAY_MIN_PEERS pairs). Yahoo has
    no FX bar on 25 Dec, 1 Jan or Good Friday, and none for a rupee pair on an Indian holiday; hard-coding those calendars would be a guess, the peers say it. Rupee pairs are their own group."""
    out: dict[str, frozenset] = {}
    groups = {"inr": [s for s in dfs if s.endswith("INR")], "other": [s for s in dfs if not s.endswith("INR")]}
    for members in groups.values():
        if len(members) < HOLIDAY_MIN_PEERS:
            hol = frozenset()
        else:
            lo, hi = min(dfs[m].index.min() for m in members), max(dfs[m].index.max() for m in members)
            days = pd.bdate_range(lo, hi)
            covers = pd.DataFrame({m: (days >= dfs[m].index.min()) & (days <= dfs[m].index.max()) for m in members}, index=days)
            has = pd.DataFrame({m: days.isin(dfs[m].index) for m in members}, index=days)
            lacking = (covers & ~has).sum(axis=1)
            n = covers.sum(axis=1)
            hol = frozenset(days[(n >= HOLIDAY_MIN_PEERS) & (lacking >= HOLIDAY_SHARE * n)])
        for m in members:
            out[m] = hol
    return out


def gap_report(have: pd.DatetimeIndex, start: pd.Timestamp, end: pd.Timestamp, holidays=frozenset()) -> dict:
    expected = pd.bdate_range(start, end)
    if holidays:
        expected = expected.difference(pd.DatetimeIndex(list(holidays)))
    missing = expected.difference(have.normalize())
    return {"expected": int(len(expected)), "missing": int(len(missing)), "fraction": float(len(missing) / len(expected)) if len(expected) else 0.0,
            "missing_days": [str(d.date()) for d in missing[:20]], "market_holidays": int(len(holidays))}


def crosscheck(close: pd.Series, implied: pd.Series | None, n: int = 200, tol: float = XCHECK_TOL, seed: int = 20261107) -> dict:
    if implied is None or not len(implied):
        return {"available": False, "compared": 0, "matched": 0, "match_rate": None, "mismatches": [], "span": None}
    days = close.index.intersection(implied.index)
    if not len(days):
        return {"available": True, "compared": 0, "matched": 0, "match_rate": None, "mismatches": [], "span": None}
    rng = np.random.default_rng(seed)
    pick = days[np.sort(rng.choice(len(days), size=min(n, len(days)), replace=False))]
    rel = (close.loc[pick] / implied.loc[pick] - 1).abs()
    bad = rel[rel > tol]
    return {"available": True, "compared": int(len(pick)), "matched": int(len(pick) - len(bad)), "match_rate": float(1 - len(bad) / len(pick)),
            "mismatches": [{"date": str(d.date()), "rel_diff": float(v)} for d, v in bad.head(15).items()], "span": [str(days.min().date()), str(days.max().date())]}


def find_jumps(close: pd.Series, symbol: str, accepted=frozenset()) -> tuple[list[dict], list[dict]]:
    """(flagged, accepted) one-day moves beyond JUMP. `reverted`: the price is back within half the move two days later, which a real step is not (a bad print is). A move a person has reviewed
    (config fx.accepted_moves) is listed apart, never silently dropped."""
    mv, prev2 = close.pct_change(), close.shift(1)
    flagged, ok = [], []
    for d in close.index[(mv.abs() > JUMP).fillna(False).to_numpy()]:
        i = close.index.get_loc(d)
        nxt = close.iloc[i + 1] if i + 1 < len(close) else np.nan
        rev = bool(nxt == nxt and abs(nxt / prev2.iloc[i] - 1) < abs(mv.loc[d]) / 2)
        row = {"date": str(d.date()), "move": float(mv.loc[d]), "reverted": rev}
        (ok if (symbol, row["date"]) in accepted else flagged).append(row)
    for a, b in zip(flagged, flagged[1:]):                                   # the day the price comes back is the second leg of the same bad print
        if a["reverted"] and pd.Timestamp(b["date"]) - pd.Timestamp(a["date"]) <= pd.Timedelta(days=4) and a["move"] * b["move"] < 0:
            b["reverted"] = True
    return flagged, ok


def coverage(rep: dict) -> str:
    return "gappy" if rep["gaps"]["fraction"] > GAP_MAX else "complete"


def quarantine(close: pd.Series, flagged: list[dict]) -> list[str]:
    """Dates of rows that are bad prints: a jump that reverses is one leg of a spike, and every bar from the first leg up to (not including) the day the price returns is off the
    line. Only spikes whose both legs are flagged and reversed, and that last at most four days, qualify; a level shift that stays is never touched."""
    out: list[str] = []
    i = 0
    while i < len(flagged) - 1:
        a, b = flagged[i], flagged[i + 1]
        da, db = pd.Timestamp(a["date"]), pd.Timestamp(b["date"])
        if a["reverted"] and b["reverted"] and a["move"] * b["move"] < 0 and (db - da) <= pd.Timedelta(days=4):
            out += [str(d.date()) for d in close.index[(close.index >= da) & (close.index < db)]]
            i += 2
        else:
            i += 1
    return out


def decide(rep: dict) -> tuple[str, list[str]]:
    why = []
    if rep["rows"] == 0:
        return "unverified", ["no rows"]
    if rep["jumps"]:
        spikes = [j["date"] for j in rep["jumps"] if j.get("reverted")]
        why.append(f"{len(rep['jumps'])} one-day move(s) beyond {JUMP:.0%}: {', '.join(j['date'] for j in rep['jumps'][:4])}"
                   + (f"; {len(spikes)} reverse within two days (likely bad prints): {', '.join(spikes[:4])}" if spikes else ""))
    x = rep["crosscheck"]
    if not x["available"]:
        why.append("no independent source for this pair (the ECB has no such currency)")
    elif x["compared"] < XCHECK_MIN:
        why.append(f"cross-check compared only {x['compared']} days (need {XCHECK_MIN})")
    elif x["match_rate"] < XCHECK_MATCH:
        why.append(f"cross-check match rate {x['match_rate']:.1%} < {XCHECK_MATCH:.0%}")
    return ("unverified" if why else "verified"), why


def run_daily(out_root: Path, pairs: list[str] | None = None, start: str = START, today: dt.date | None = None, yahoo=None, ecb=None, say=print, accepted=frozenset()) -> dict:
    today = today or pd.Timestamp.now(tz="UTC").date()
    yahoo, ecb = yahoo or YahooFx(), ecb or EcbReference()
    run = Path(out_root) / str(today)
    dfs, series = {}, {}
    for sym in pairs or list(PAIRS):                                        # pass 1: fetch and clean every pair (the holiday calendar needs the peers)
        rep = series[sym] = {"symbol": sym, "ticker": PAIRS.get(sym), "rows": 0}
        try:
            raw = yahoo.daily(sym, dt.date.fromisoformat(start), today)
        except Exception as exc:                                              # one pair down never stops the others
            rep.update(status="unverified", reasons=[f"no source served this series: {exc!s:.140}"])
            say(f"  {sym}: {rep['reasons'][0]}")
            continue
        df, rejected = clean(raw[OHLC + ["volume"]].copy()) if len(raw) else (raw, {})
        df.index = pd.DatetimeIndex(df.index).normalize()
        rep.update(rejected=rejected, rejected_total=int(sum(rejected.values())))
        if len(df):
            dfs[sym] = df
        else:
            rep.update(status="unverified", reasons=["no rows"])
    holidays = peer_holidays(dfs)
    frames = {}
    for sym, df in dfs.items():                                             # pass 2: judge each series against its group's calendar
        rep = series[sym]
        flagged, reviewed = find_jumps(df["close"], sym, accepted)
        bad_days = quarantine(df["close"], flagged)
        if bad_days and len(bad_days) <= QUARANTINE_MAX * len(df):
            rep["quarantined"] = [{"date": d, "close": float(df["close"].loc[d]), "why": "one-day spike that reverses within the window: a bad print"} for d in bad_days]
            df = df.drop(index=pd.DatetimeIndex(bad_days))
            flagged, reviewed = find_jumps(df["close"], sym, accepted)
        rep.update(rows=int(len(df)), first=str(df.index.min().date()), last=str(df.index.max().date()), jumps=flagged, accepted_moves=reviewed,
                   gaps=gap_report(df.index, df.index.min(), df.index.max(), holidays.get(sym, frozenset())), content_hash=frame_hash(df))
        try:
            rep["crosscheck"] = crosscheck(df["close"], ecb.implied(sym))
        except Exception as exc:
            rep["crosscheck"] = {"available": False, "compared": 0, "matched": 0, "match_rate": None, "mismatches": [], "span": None, "error": f"{exc!s:.140}"}
        rep["status"], rep["reasons"] = decide(rep)
        rep["coverage"] = coverage(rep)
        frames[sym] = df.assign(symbol=sym, source="yahoo", series_status=rep["status"])
        mr = rep["crosscheck"]["match_rate"]
        say(f"  {sym}: {len(df):,} rows, {len(flagged)} jump(s), {rep['gaps']['missing']} gap(s), cross-check {'n/a' if mr is None else format(mr, '.1%')} -> {rep['status']}, coverage {rep['coverage']} ({rep['gaps']['fraction']:.1%} of weekdays missing)"
            + (f", {len(rep.get('quarantined', []))} bad print(s) set aside" if rep.get("quarantined") else "") + "".join(f"\n      - {r}" for r in rep["reasons"]))
    shards = []
    if frames:
        allf = pd.concat(frames.values()).reset_index().rename(columns={"index": "date"})
        for year, g in allf.groupby(allf["date"].dt.year):
            name = f"fx_daily_{year}.parquet"
            h = _write_once(g[COLS_DAILY].reset_index(drop=True), run / name)
            shards.append({"file": name, "rows": int(len(g)), "content_hash": h})
    bad = [s for s, r in series.items() if r.get("status") != "verified"]
    man = {"version": VERSION, "as_of": str(today), "start": start, "series": series, "shards": shards, "unverified_series": bad, "gappy_series": [s for s, r in series.items() if r.get("coverage") == "gappy"], "status": "verified" if not bad else "unverified",
           "note": "daily FX closes from Yahoo, checked against the ECB's reference rates (2% tolerance: a sanity check, not an exact match); weekdays missing from most of a group of pairs are "
                   "market holidays; the dollar index is checked against the ECB's rates via ICE's published basket formula; 'verified' is about the values (cross-check, no unexplained jump), "
                   "'coverage' about missing days; one-day spikes that reverse are set aside and listed in 'quarantined'; public sources, no secret; nothing trades",
           "path": str(run)}
    run.mkdir(parents=True, exist_ok=True)
    (run / "manifest.json").write_text(json.dumps(man, indent=2, default=str), encoding="utf-8")
    return man


def run_minutes(out_root: Path, pairs: list[str] | None = None, days: int = 5, today: dt.date | None = None, yahoo=None, say=print) -> dict:
    today = today or pd.Timestamp.now(tz="UTC").date()
    yahoo = yahoo or YahooFx()
    run = Path(out_root) / str(today)
    run.mkdir(parents=True, exist_ok=True)
    parts, pr = [], {}
    for sym in pairs or list(PAIRS):
        rep = pr[sym] = {"rows": 0}
        try:
            raw = yahoo.minutes(sym, days)
        except Exception as exc:
            rep.update(status="failed", error=f"{exc!s:.140}")
            say(f"  {sym}: {rep['error']}")
            continue
        df, rejected = clean(raw[OHLC + ["volume"]].copy())
        if not len(df):
            rep.update(status="empty", rejected_total=int(sum(rejected.values())))
            continue
        gaps = df.index.to_series().diff().dt.total_seconds().div(60)
        wk = df.index.to_series().dt.dayofweek < 5
        rep.update(status="served", rows=int(len(df)), first=str(df.index.min()), last=str(df.index.max()), rejected_total=int(sum(rejected.values())),
                   days=int(df.index.normalize().nunique()), longest_gap_min=float(gaps[wk].max()) if wk.any() else 0.0, content_hash=frame_hash(df))
        parts.append(df.assign(symbol=sym).reset_index().rename(columns={df.index.name or "index": "ts", "Datetime": "ts"}))
        say(f"  {sym}: {len(df):,} bars over {rep['days']} day(s), longest weekday gap {rep['longest_gap_min']:.0f} min")
    if parts:
        pd.concat(parts, ignore_index=True)[COLS_MIN].to_parquet(run / "fx_minutes.parquet", index=False, compression="zstd")
    served = sum(1 for r in pr.values() if r["status"] == "served")
    man = {"version": VERSION, "as_of": str(today), "days": days, "pairs": pr, "totals": {"asked": len(pr), "served": served,
           "failed": sum(1 for r in pr.values() if r["status"] == "failed"), "empty": sum(1 for r in pr.values() if r["status"] == "empty")},
           "note": "1-minute FX bars from Yahoo, UTC; public source, no secret; nothing trades", "path": str(run)}
    (run / "manifest.json").write_text(json.dumps(man, indent=2, default=str), encoding="utf-8")
    return man


def release_names(run: Path) -> list[str]:
    return sorted(p.name for p in Path(run).glob("*") if p.suffix in (".parquet", ".json"))
