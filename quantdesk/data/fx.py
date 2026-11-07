"""Foreign exchange: the majors and the rupee crosses, as daily history and as 1-minute bars (`quantdesk data fx-daily`, `fx-minutes`; fx-daily.yml, fx-minutes.yml).

Why: nothing in the pipeline covered forex. Indian currency futures are in the Kite universe (and, only while the Kite recorder runs, recorded), but the global pairs they follow, and the
cash USD/INR, were not. Yahoo serves FX 24 hours a day on a weekday and works from a cloud runner (NSE and Kotak's candle API for MCX/currency do not: see docs/PIPELINE_READINESS.md);
the ECB publishes official daily reference rates for the same currencies, an independent source to check Yahoo against.

Daily history (since 2003): fetched from Yahoo, rows that cannot be a real bar dropped and counted (never repaired), one-day moves beyond 5% flagged (never smoothed), weekdays with no
row counted as gaps, and the closes compared with the rate the ECB implies for the pair. The ECB fixes at about 14:15 CET and Yahoo's daily close is later, so the check is a sanity check
(1% tolerance), not an exact match: it catches an inverted pair, a wrong decimal or a frozen series, not a basis point. A series is `verified` only if every check passes.

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
ECB_URL = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-hist.zip"
START = "2003-01-01"
JUMP = 0.05                    # a one-day move beyond this is flagged (the yen's 2024 intervention days were about 4%)
GAP_MAX = 0.01                 # missing weekdays / expected weekdays
XCHECK_TOL, XCHECK_MIN, XCHECK_MATCH = 0.01, 30, 0.95
MINUTES_MAX_DAYS = 7           # what Yahoo keeps
MIN_ROWS_OK = 500              # a quiet FX day still has far more 1-minute bars than this
COLS_DAILY = ["date", "symbol", "open", "high", "low", "close", "volume", "source", "series_status"]
COLS_MIN = ["ts", "symbol", "open", "high", "low", "close", "volume"]


class SourceDown(Exception):
    """A source that could not serve the request: recorded, never raised past the run."""


class YahooFx:
    def __init__(self, tries: int = 2, sleep=time.sleep):
        self.tries, self._sleep = tries, sleep

    def _history(self, symbol: str, **kw) -> pd.DataFrame:
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
                df.index = idx.tz_convert("UTC") if idx.tz is not None else idx.tz_localize("UTC")
                return df[~df.index.duplicated(keep="last")].sort_index()
        raise SourceDown(f"yahoo {PAIRS[symbol]}: {last}")

    def minutes(self, symbol: str, days: int) -> pd.DataFrame:
        return self._history(symbol, period=f"{min(max(days, 1), MINUTES_MAX_DAYS)}d", interval="1m")

    def daily(self, symbol: str, start: dt.date, end: dt.date) -> pd.DataFrame:
        df = self._history(symbol, start=str(start), end=str(end + dt.timedelta(days=1)), interval="1d")
        df.index = pd.DatetimeIndex(df.index.tz_convert("UTC").tz_localize(None)).normalize()
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
        if symbol == "DXY" or base not in t or quote not in t:
            return None
        s = (t[quote] / t[base]).dropna()
        return s if len(s) else None


def gap_report(have: pd.DatetimeIndex, start: pd.Timestamp, end: pd.Timestamp) -> dict:
    expected = pd.bdate_range(start, end)
    missing = expected.difference(have.normalize())
    return {"expected": int(len(expected)), "missing": int(len(missing)), "fraction": float(len(missing) / len(expected)) if len(expected) else 0.0,
            "missing_days": [str(d.date()) for d in missing[:20]]}


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


def decide(rep: dict) -> tuple[str, list[str]]:
    why = []
    if rep["rows"] == 0:
        return "unverified", ["no rows"]
    if rep["gaps"]["fraction"] > GAP_MAX:
        why.append(f"{rep['gaps']['missing']} missing weekdays ({rep['gaps']['fraction']:.2%}) vs limit {GAP_MAX:.0%}")
    if rep["jumps"]:
        why.append(f"{len(rep['jumps'])} one-day move(s) beyond {JUMP:.0%}: {', '.join(j['date'] for j in rep['jumps'][:4])}")
    x = rep["crosscheck"]
    if not x["available"]:
        why.append("no independent source for this pair (the ECB has no such currency)")
    elif x["compared"] < XCHECK_MIN:
        why.append(f"cross-check compared only {x['compared']} days (need {XCHECK_MIN})")
    elif x["match_rate"] < XCHECK_MATCH:
        why.append(f"cross-check match rate {x['match_rate']:.1%} < {XCHECK_MATCH:.0%}")
    return ("unverified" if why else "verified"), why


def run_daily(out_root: Path, pairs: list[str] | None = None, start: str = START, today: dt.date | None = None, yahoo=None, ecb=None, say=print) -> dict:
    today = today or pd.Timestamp.now(tz="UTC").date()
    yahoo, ecb = yahoo or YahooFx(), ecb or EcbReference()
    run = Path(out_root) / str(today)
    frames, series = {}, {}
    for sym in pairs or list(PAIRS):
        rep = series[sym] = {"symbol": sym, "ticker": PAIRS.get(sym), "rows": 0}
        try:
            raw = yahoo.daily(sym, dt.date.fromisoformat(start), today)
        except Exception as exc:                                              # one pair down never stops the others
            rep.update(status="unverified", reasons=[f"no source served this series: {exc!s:.140}"])
            say(f"  {sym}: {rep['reasons'][0]}")
            continue
        df, rejected = clean(raw[OHLC + ["volume"]].copy()) if len(raw) else (raw, {})
        df.index = pd.DatetimeIndex(df.index).normalize()
        jumps = (df["close"].pct_change().abs() > JUMP)
        rep.update(rows=int(len(df)), first=str(df.index.min().date()), last=str(df.index.max().date()), rejected=rejected, rejected_total=int(sum(rejected.values())),
                   jumps=[{"date": str(d.date()), "move": float(df["close"].pct_change().loc[d])} for d in df.index[jumps.fillna(False).to_numpy()]],
                   gaps=gap_report(df.index, df.index.min(), df.index.max()), content_hash=frame_hash(df))
        try:
            rep["crosscheck"] = crosscheck(df["close"], ecb.implied(sym))
        except Exception as exc:
            rep["crosscheck"] = {"available": False, "compared": 0, "matched": 0, "match_rate": None, "mismatches": [], "span": None, "error": f"{exc!s:.140}"}
        rep["status"], rep["reasons"] = decide(rep)
        frames[sym] = df.assign(symbol=sym, source="yahoo", series_status=rep["status"])
        mr = rep["crosscheck"]["match_rate"]
        say(f"  {sym}: {len(df):,} rows, {len(rep['jumps'])} jump(s), {rep['gaps']['missing']} gap(s), cross-check {'n/a' if mr is None else format(mr, '.1%')} -> {rep['status']}")
    shards = []
    if frames:
        allf = pd.concat(frames.values()).reset_index().rename(columns={"index": "date"})
        for year, g in allf.groupby(allf["date"].dt.year):
            name = f"fx_daily_{year}.parquet"
            h = _write_once(g[COLS_DAILY].reset_index(drop=True), run / name)
            shards.append({"file": name, "rows": int(len(g)), "content_hash": h})
    bad = [s for s, r in series.items() if r.get("status") != "verified"]
    man = {"version": VERSION, "as_of": str(today), "start": start, "series": series, "shards": shards, "unverified_series": bad, "status": "verified" if not bad else "unverified",
           "note": "daily FX closes from Yahoo, checked against the ECB's reference rates (1% tolerance: a sanity check, not an exact match); public sources, no secret; nothing trades",
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
