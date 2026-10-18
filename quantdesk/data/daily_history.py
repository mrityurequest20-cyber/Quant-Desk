"""Daily OHLCV history (about 2013 → today) for the five index underlyings and the F&O stocks: `quantdesk data daily-history`.

Quality is the point, not volume. For every series the importer:
1. fetches daily bars from the first source that serves the whole range (NSE's own history API through nse.py; Yahoo as the
   fallback, and the only source for SENSEX, because bse.py holds BSE's F&O bhavcopy only), and records the source per row;
2. keeps what the source printed (`open … close`, raw) and adds `adj_*` columns adjusted for splits and bonuses. A corporate
   action is applied ONLY where the data shows the source did not already apply it (the day's move matches 1/ratio);
   where the source already did (Yahoo's Close is split-adjusted), the factor stays 1. Neither fits: `action_unconfirmed`;
3. flags every one-day move beyond a threshold that no corporate action explains (`unadjusted_jump`);
4. cross-checks a seeded random sample of days against a second source, adjusted on the same basis, and records the match rate;
5. reports gaps against the NSE holiday calendar (official where the config lists the year; otherwise a peer calendar:
   a weekday every index series skipped is a market holiday, one only this series skipped is a gap);
6. refuses to mark a series `verified` unless coverage, jumps, cross-check, gaps and row hygiene all pass.
Rows that fail hygiene (non-positive price, high < low, close outside the range) are dropped and counted, never repaired.
Nothing is forward-filled or invented; a missing day stays missing and shows up in the gap report.

Output (immutable per run; a later run is a new dataset, as external_aeron.py):
    <root>/daily-history/<as of>/daily_<YYYY>.parquet   every series' rows of one calendar year
                                manifest.json            per series: source, fetched_at, rows, first/last, content hash,
                                                         rejected rows, actions, flags, cross-check, gaps, status + reasons;
                                                         per shard: rows, sha256, content hash
Nothing here trades, sizes or places an order, and it needs no secret.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import zlib
from pathlib import Path

import numpy as np
import pandas as pd

from .external_aeron import _write_once, frame_hash

VERSION = "daily-history-1"
IST = "Asia/Kolkata"
INDICES = ["SENSEX", "NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY"]
NSE_INDEX_NAMES = {"NIFTY": "NIFTY 50", "BANKNIFTY": "NIFTY BANK", "FINNIFTY": "NIFTY FINANCIAL SERVICES",
                   "MIDCPNIFTY": "NIFTY MIDCAP SELECT"}
OHLC = ["open", "high", "low", "close"]
COLS = ["date", "symbol", "kind", "open", "high", "low", "close", "volume", "adj_open", "adj_high", "adj_low", "adj_close",
        "adj_factor", "source", "flags", "series_status"]
ACTION_COLS = ["date", "ratio", "note"]
DEFAULTS = {
    "start": "2013-01-01",
    "indices": INDICES,
    "extra_stocks": [],            # more F&O stocks (the desk's universe config has no long list); total capped by max_stocks
    "max_stocks": 70,
    "stock_jump": 0.20,            # a one-day move beyond this that no corporate action explains is flagged
    "index_jump": 0.15,            # an index moved -13% on 23 Mar 2020; beyond 15% is suspicious
    "accepted_moves": [],          # [{symbol, date}] reviewed by a person and genuine: not flagged
    "corporate_actions": [],       # [{symbol, date, ratio, note}] extra/override actions (ratio 5 = a 5-for-1 split)
    "action_tol": 0.25,            # how close (log) a day's move must be to 1/ratio (or to 0) to count as the action
    "crosscheck_sample": 60,
    "crosscheck_tol": 0.005,       # relative difference of the adjusted close
    "crosscheck_min_compared": 30,
    "crosscheck_min_match": 0.98,
    "max_gap_fraction": 0.002,     # missing days / expected days
    "start_slack_days": 45,        # the series must begin within this many days of the requested start
    "seed": 20261019,
    "gap_sec": 0.5,
}


def settings(cfg) -> dict:
    raw = (cfg.get("daily_history") if cfg is not None else None) or {}
    s = {**DEFAULTS, **{k: v for k, v in raw.items() if k in DEFAULTS}}
    s["indices"] = [str(x).upper() for x in s["indices"]]
    wide = [str(x).upper() for x in ((cfg.get("collect_wide.stocks") if cfg is not None else None) or [])]
    extra = [str(x).upper() for x in s["extra_stocks"]]
    s["stocks"] = list(dict.fromkeys(wide + extra))[: int(s["max_stocks"])]
    return s


# ---- sources ---------------------------------------------------------------------------------------------------------------
class SourceDown(RuntimeError):
    """The source refused or returned nothing usable (NSE often blocks cloud runners): fall back, say so, carry on."""


def _num(x) -> float:
    try:
        v = float(str(x).replace(",", ""))
    except (TypeError, ValueError):
        return float("nan")
    return v if np.isfinite(v) else float("nan")


def _date(x):
    t = pd.to_datetime(str(x), errors="coerce")
    if pd.isna(t):
        return pd.NaT
    t = pd.Timestamp(t)
    return (t.tz_convert(IST).tz_localize(None) if t.tzinfo is not None else t).normalize()


def _frame(rows: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(rows, columns=["date", *OHLC, "volume"]).dropna(subset=["date"])
    df["date"] = pd.to_datetime(df["date"])
    return df.drop_duplicates("date", keep="last").set_index("date").sort_index()


def parse_nse_index(js, name: str) -> pd.DataFrame:
    """/api/historical/indicesHistory → daily frame (volume stays NaN: the endpoint gives turnover separately)."""
    recs = ((js or {}).get("data") or {}).get("indexCloseOnlineRecords") or []
    rows = [{"date": _date(r.get("EOD_TIMESTAMP") or r.get("TIMESTAMP") or r.get("HistoricalDate")),
             "open": _num(r.get("EOD_OPEN_INDEX_VAL")), "high": _num(r.get("EOD_HIGH_INDEX_VAL")),
             "low": _num(r.get("EOD_LOW_INDEX_VAL")), "close": _num(r.get("EOD_CLOSE_INDEX_VAL")), "volume": np.nan}
            for r in recs if not r.get("EOD_INDEX_NAME") or str(r["EOD_INDEX_NAME"]).upper() == name.upper()]
    return _frame(rows)


def parse_nse_equity(js) -> pd.DataFrame:
    """/api/historical/cm/equity → daily frame of EQ-series rows (prices as traded: not adjusted for splits)."""
    rows = [{"date": _date(r.get("CH_TIMESTAMP")), "open": _num(r.get("CH_OPENING_PRICE")),
             "high": _num(r.get("CH_TRADE_HIGH_PRICE")), "low": _num(r.get("CH_TRADE_LOW_PRICE")),
             "close": _num(r.get("CH_CLOSING_PRICE")), "volume": _num(r.get("CH_TOT_TRADED_QTY"))}
            for r in ((js or {}).get("data") or []) if str(r.get("CH_SERIES", "EQ")) == "EQ"]
    return _frame(rows)


_SPLIT = re.compile(r"from\s*(?:rs\.?|re\.?|inr)?\s*([\d.]+)\s*/?-?.*?to\s*(?:rs\.?|re\.?|inr)?\s*([\d.]+)", re.I | re.S)
_BONUS = re.compile(r"bonus.*?(\d+)\s*:\s*(\d+)", re.I | re.S)


def parse_action_subject(subject: str) -> float | None:
    """A corporate-action subject → the share multiple (5 = a 5-for-1 split or a 4:1 bonus), or None if it is neither.
    'Face Value Split … From Rs 10/- To Rs 2/-' → 5.  'Bonus 1:1' (1 new share per 1 held) → 2.  'Bonus 3:2' → 2.5."""
    t = str(subject or "")
    if re.search(r"split|sub-?division", t, re.I):
        m = _SPLIT.search(t)
        if m and _num(m.group(2)) > 0 and _num(m.group(1)) > _num(m.group(2)):
            return _num(m.group(1)) / _num(m.group(2))
    m = _BONUS.search(t)
    if m and int(m.group(2)) > 0:
        return 1 + int(m.group(1)) / int(m.group(2))
    return None


class NseSource:
    """NSE's own history: raw prices as traded. Often blocked for cloud runners: every failure is a SourceDown.
    Endpoint paths and field names are from memory of NSE's site API and unverified from the build sandbox."""
    name = "nse"

    def __init__(self, nse=None, gap: float = 0.5, chunk_days: int = 360):
        self.nse, self.gap, self.chunk = nse, gap, chunk_days

    def _n(self):
        if self.nse is None:
            from .nse import NSE
            self.nse = NSE(gap=self.gap, tries=2)
        return self.nse

    def daily(self, symbol: str, kind: str, start: dt.date, end: dt.date) -> pd.DataFrame:
        if kind == "index" and symbol not in NSE_INDEX_NAMES:
            raise SourceDown(f"{symbol} is not an NSE index")
        parts, d = [], start
        try:
            while d <= end:
                e = min(end, d + dt.timedelta(days=self.chunk))
                f, t = f"{d:%d-%m-%Y}", f"{e:%d-%m-%Y}"
                if kind == "index":
                    nm = NSE_INDEX_NAMES[symbol]
                    js, _, _ = self._n().api(f"/api/historical/indicesHistory?indexType={nm.replace(' ', '%20')}&from={f}&to={t}")
                    p = parse_nse_index(js, nm)
                else:
                    js, _, _ = self._n().api(f'/api/historical/cm/equity?symbol={symbol}&series=["EQ"]&from={f}&to={t}')
                    p = parse_nse_equity(js)
                if len(p):
                    parts.append(p)
                d = e + dt.timedelta(days=1)
        except Exception as exc:
            raise SourceDown(f"nse: {exc!s:.140}") from exc
        if not parts:
            raise SourceDown("nse: no rows")
        df = pd.concat(parts).sort_index()
        return df[~df.index.duplicated(keep="last")]

    def actions(self, symbol: str, kind: str) -> pd.DataFrame:
        if kind == "index":
            return pd.DataFrame(columns=ACTION_COLS)
        try:
            js, _, _ = self._n().api(f"/api/corporates-corporateActions?index=equities&symbol={symbol}")
        except Exception as exc:
            raise SourceDown(f"nse actions: {exc!s:.140}") from exc
        rows = []
        for r in (js if isinstance(js, list) else (js or {}).get("data") or []):
            ratio = parse_action_subject(r.get("subject"))
            d = _date(r.get("exDate"))
            if ratio and ratio > 1 and not pd.isna(d):
                rows.append({"date": d, "ratio": ratio, "note": str(r.get("subject"))[:120]})
        return pd.DataFrame(rows, columns=ACTION_COLS)


class YahooSource:
    """Yahoo via yfinance with auto_adjust off. Its Close is still adjusted for splits (not for dividends), so adjust() finds
    no jump at a split and leaves the factor at 1. It is also the only source for SENSEX here. Ticker names come from the
    config's `instruments` section, as quantdesk/data/yahoo.py (whose provider returns auto-adjusted prices only)."""
    name = "yahoo"

    def __init__(self, cfg, tries: int = 2):
        self.cfg, self.tries = cfg, tries
        self._splits: dict[str, pd.DataFrame] = {}

    def ticker(self, symbol: str) -> str:
        return self.cfg.instrument_spec(symbol).get("yahoo", f"{symbol}.NS")

    def daily(self, symbol: str, kind: str, start: dt.date, end: dt.date) -> pd.DataFrame:
        try:
            import yfinance as yf
        except ImportError as exc:
            raise SourceDown("yfinance missing") from exc
        last = None
        for _ in range(self.tries):
            try:
                raw = yf.Ticker(self.ticker(symbol)).history(start=str(start), end=str(end + dt.timedelta(days=1)),
                                                             interval="1d", auto_adjust=False, actions=True)
            except Exception as exc:
                last = f"{exc!s:.140}"
                continue
            if raw is not None and len(raw):
                idx = pd.DatetimeIndex(raw.index)
                raw = raw.copy()
                raw.index = (idx.tz_convert(IST).tz_localize(None) if idx.tz is not None else idx).normalize()
                sp = raw["Stock Splits"] if "Stock Splits" in raw else pd.Series(0.0, index=raw.index)
                self._splits[symbol] = pd.DataFrame({"date": sp[sp > 0].index, "ratio": sp[sp > 0].to_numpy(),
                                                     "note": "yahoo Stock Splits"}, columns=ACTION_COLS)
                df = raw.rename(columns=str.lower)[[*OHLC, "volume"]].astype(float)
                df.index.name = "date"
                return df[~df.index.duplicated(keep="last")].sort_index()
            last = "no rows"
        raise SourceDown(f"yahoo {self.ticker(symbol)}: {last}")

    def actions(self, symbol: str, kind: str) -> pd.DataFrame:
        if kind == "index":
            return pd.DataFrame(columns=ACTION_COLS)
        if symbol not in self._splits:
            raise SourceDown("yahoo splits not fetched")
        s = self._splits[symbol]
        return s[s["ratio"] > 1.05].reset_index(drop=True)


# ---- cleaning, adjustment, jumps -----------------------------------------------------------------------------------------------
def clean(df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Drop (never repair) rows that cannot be a real daily bar; count each reason."""
    rej: dict[str, int] = {}
    ok = pd.Series(True, index=df.index)
    tol = 1e-6
    for why, mask in (("missing_price", df[OHLC].isna().any(axis=1)),
                      ("non_positive_price", (df[OHLC] <= 0).any(axis=1)),
                      ("high_below_low", df["high"] < df["low"]),
                      ("close_outside_range", (df["close"] > df["high"] * (1 + tol)) | (df["close"] < df["low"] * (1 - tol))),
                      ("open_outside_range", (df["open"] > df["high"] * (1 + tol)) | (df["open"] < df["low"] * (1 - tol)))):
        hit = mask & ok
        if hit.any():
            rej[why] = int(hit.sum())
        ok &= ~mask
    return df[ok], rej


def adjust(df: pd.DataFrame, actions: pd.DataFrame | None, kind: str = "equity", jump: float = 0.20, tol: float = 0.25,
           accepted=frozenset()) -> tuple[pd.DataFrame, list[dict]]:
    """Adds adj_open…adj_close, adj_factor and flags. For each action (ex-date d, multiple r > 1) the move into the first
    bar at/after d is compared with two hypotheses: the source did NOT adjust (move ≈ 1/r → apply it to all earlier bars)
    or DID (move ≈ 0 → leave it). Neither within `tol` (log): `action_unconfirmed`, nothing applied. Then any remaining
    one-day move beyond `jump` that is not in `accepted` is `unadjusted_jump`. Indices are never adjusted.
    -> (frame, [{date, type, ...}] events for the manifest)."""
    out = df.copy()
    n = len(out)
    factor = np.ones(n)
    flags: list[set] = [set() for _ in range(n)]
    events: list[dict] = []
    c = out["close"].to_numpy(dtype=float)
    if kind != "index" and actions is not None and len(actions):
        for a in actions.sort_values("date").itertuples():
            r = float(a.ratio)
            if not r > 1.05:
                continue
            i = int(out.index.searchsorted(pd.Timestamp(a.date)))
            if i <= 0 or i >= n:
                continue
            obs = float(np.log(c[i] / c[i - 1]))
            d_un, d_ad = abs(obs - np.log(1 / r)), abs(obs)
            ev = {"date": str(out.index[i].date()), "ratio": r, "move": float(np.expm1(obs)), "note": str(getattr(a, "note", ""))}
            if min(d_un, d_ad) > tol:
                flags[i].add("action_unconfirmed")
                ev["type"] = "action_unconfirmed"
            elif d_un < d_ad:
                factor[:i] /= r
                flags[i].add("split_applied")
                ev["type"] = "split_applied"
            else:
                flags[i].add("split_in_source")
                ev["type"] = "split_in_source"
            events.append(ev)
    for k in OHLC:
        out[f"adj_{k}"] = out[k].to_numpy(dtype=float) * factor
    out["adj_factor"] = factor
    ac = out["adj_close"].to_numpy(dtype=float)
    sym = str(out["symbol"].iloc[0]) if "symbol" in out and n else ""
    for i in range(1, n):
        mv = ac[i] / ac[i - 1] - 1
        d = str(out.index[i].date())
        if abs(mv) > jump and (sym, d) not in accepted:
            flags[i].add("unadjusted_jump")
            events.append({"date": d, "type": "unadjusted_jump", "move": float(mv)})
    out["flags"] = [",".join(sorted(f)) for f in flags]
    return out, events


# ---- checks: cross-source, gaps ------------------------------------------------------------------------------------------------
def crosscheck(primary: pd.DataFrame, second: pd.DataFrame | None, symbol: str, n: int = 60, tol: float = 0.005,
               seed: int = 1) -> dict:
    """A seeded random sample of the primary's days against the second source's adjusted close (both adjusted on the same
    basis by adjust()). `second` None: no second source was reachable, which is recorded, never skipped silently."""
    if second is None or not len(second) or not len(primary):
        return {"available": False, "sampled": 0, "compared": 0, "matched": 0, "match_rate": None, "mismatches": []}
    rng = np.random.default_rng(seed + zlib.crc32(symbol.encode()))
    days = primary.index
    pick = days[np.sort(rng.choice(len(days), size=min(n, len(days)), replace=False))]
    rows, matched, compared = [], 0, 0
    for d in pick:
        if d not in second.index:
            continue
        a, b = float(primary.at[d, "adj_close"]), float(second.at[d, "adj_close"])
        compared += 1
        rel = a / b - 1 if b else float("nan")
        if abs(rel) <= tol:
            matched += 1
        else:
            rows.append({"date": str(d.date()), "ours": a, "other": b, "rel_diff": rel})
    return {"available": True, "sampled": int(len(pick)), "compared": compared, "matched": matched,
            "match_rate": (matched / compared) if compared else None, "mismatches": rows[:25]}


def market_days(dates: dict, holidays: set, official_years: set, peers: list[str]) -> tuple[pd.DatetimeIndex, dict]:
    """The days the market was open across the whole span: weekdays minus the NSE holidays in years whose list is
    official (config), and in other years the weekdays that at least half of the `peers` (index series) have a bar on."""
    lo = min(d.min() for d in dates.values() if len(d))
    hi = max(d.max() for d in dates.values() if len(d))
    wk = pd.bdate_range(lo, hi)
    official = [d for d in wk if d.year in official_years and d.date() not in holidays]
    pr = [dates[p] for p in peers if p in dates and len(dates[p])] or [x for x in dates.values() if len(x)]
    peer_days = []
    for d in wk:
        if d.year in official_years:
            continue
        cover = [x for x in pr if x.min() <= d <= x.max()]
        if cover and sum(d in x for x in cover) / len(cover) >= 0.5:
            peer_days.append(d)
    yrs = sorted({d.year for d in wk})
    return pd.DatetimeIndex(sorted(official + peer_days)), {
        "official_years": sorted(y for y in yrs if y in official_years),
        "peer_calendar_years": sorted(y for y in yrs if y not in official_years)}


def gap_report(have: pd.DatetimeIndex, mdays: pd.DatetimeIndex, holidays: set) -> dict:
    """Expected days (market days between the series' first and last bar) not present; bars on weekends or official
    holidays are listed apart (a Muhurat or special Saturday session is real, so it is information, not a failure)."""
    if not len(have):
        return {"expected": 0, "present": 0, "missing": 0, "missing_fraction": None, "missing_days": [], "off_calendar": []}
    exp = mdays[(mdays >= have.min()) & (mdays <= have.max())]
    miss = exp.difference(have)
    off = [str(d.date()) for d in have if d.weekday() >= 5 or d.date() in holidays]
    return {"expected": int(len(exp)), "present": int(len(exp) - len(miss)), "missing": int(len(miss)),
            "missing_fraction": float(len(miss) / len(exp)) if len(exp) else None,
            "missing_days": [str(d.date()) for d in miss[:60]], "off_calendar": off[:30]}


def decide(rep: dict, S: dict, start: dt.date) -> tuple[str, list[str]]:
    """`verified` only if every check passes; otherwise `unverified` with the reasons. Fails closed."""
    if not rep.get("rows"):
        return "unverified", ["no rows"]
    why = []
    if pd.Timestamp(rep["first"]).date() > start + dt.timedelta(days=int(S["start_slack_days"])):
        why.append(f"history starts {rep['first']}, after the requested {start}")
    if rep["rejected_total"]:
        why.append(f"{rep['rejected_total']} rows rejected as impossible bars")
    jumps = [e for e in rep["events"] if e["type"] == "unadjusted_jump"]
    if jumps:
        why.append(f"{len(jumps)} unexplained one-day move(s) beyond the threshold")
    if any(e["type"] == "action_unconfirmed" for e in rep["events"]):
        why.append("a corporate action the data does not confirm")
    x = rep["crosscheck"]
    if not x["available"]:
        why.append("no second source reachable for the cross-check")
    elif x["compared"] < S["crosscheck_min_compared"]:
        why.append(f"cross-check compared only {x['compared']} days (need {S['crosscheck_min_compared']})")
    elif x["match_rate"] < S["crosscheck_min_match"]:
        why.append(f"cross-check match rate {x['match_rate']:.1%} < {S['crosscheck_min_match']:.0%}")
    g = rep["gaps"]
    if g["missing_fraction"] is None or g["missing_fraction"] > S["max_gap_fraction"]:
        why.append(f"{g['missing']} missing market days ({g['missing_fraction']}) vs limit {S['max_gap_fraction']}")
    return ("verified" if not why else "unverified"), why


# ---- the run -------------------------------------------------------------------------------------------------------------------
def _accepted(S) -> frozenset:
    return frozenset((str(a["symbol"]).upper(), str(a["date"])[:10]) for a in S["accepted_moves"] if "symbol" in a and "date" in a)


def _config_actions(S, symbol: str) -> pd.DataFrame:
    rows = [{"date": pd.Timestamp(str(a["date"])[:10]), "ratio": float(a["ratio"]), "note": str(a.get("note", "config"))}
            for a in S["corporate_actions"] if str(a.get("symbol", "")).upper() == symbol]
    return pd.DataFrame(rows, columns=ACTION_COLS)


def fetch_series(symbol: str, kind: str, sources: list, start: dt.date, S: dict, end: dt.date, down: dict, say) -> dict:
    """The first source that serves the whole range wins; a source that fails (or serves only a later part) is recorded
    and the next is tried. If none serves it all, the one with the earliest start is kept (and the check fails the
    series' start). A source that failed three times running is skipped for the rest of the run (NSE blocked)."""
    tried, best = {}, None
    for src in sources:
        if down.get(src.name, 0) >= 3:
            tried[src.name] = "skipped (source down: 3 failures in a row)"
            continue
        try:
            df = src.daily(symbol, kind, start, end)
            down[src.name] = 0
        except Exception as exc:                                   # SourceDown, or a source bug: either way a fallback
            down[src.name] = down.get(src.name, 0) + 1
            tried[src.name] = (str(exc) if isinstance(exc, SourceDown) else f"error: {exc!s}")[:160]
            continue
        if not len(df):
            tried[src.name] = "no rows"
            continue
        tried[src.name] = f"{len(df)} rows from {df.index.min().date()}"
        if best is None or df.index.min() < best[1].index.min():
            best = (src, df)
        if df.index.min().date() <= start + dt.timedelta(days=int(S["start_slack_days"])):
            break
    if best is None:
        say(f"  {symbol}: no source ({'; '.join(f'{k}: {v}' for k, v in tried.items())})")
        return {"df": None, "source": None, "tried": tried, "others": []}
    return {"df": best[1], "source": best[0].name, "tried": tried, "others": [s for s in sources if s is not best[0]],
            "primary": best[0]}


def _prep(df: pd.DataFrame, symbol: str, kind: str, source: str) -> tuple[pd.DataFrame, dict]:
    df = df.copy()
    df.index = pd.DatetimeIndex(df.index).normalize()
    df.index.name = "date"
    df, rej = clean(df)
    df.insert(0, "symbol", symbol)
    df.insert(1, "kind", kind)
    df["source"] = source
    return df, rej


def run(cfg, out_root: Path, sources: list, end: dt.date | None = None, symbols: list | None = None, say=print,
        now: pd.Timestamp | None = None) -> dict:
    """Fetch, adjust, check and write one immutable dataset. `sources` are tried in order (NseSource, YahooSource, …);
    the first that serves a series is its primary and the next reachable one is its cross-check."""
    S = settings(cfg)
    now = now or pd.Timestamp.now(tz=IST)
    end = end or now.date()
    start = dt.date.fromisoformat(str(S["start"]))
    holidays = set(cfg.holidays()) if cfg is not None else set()
    official = set(cfg.holiday_years()) if holidays else set()
    todo = symbols or [(s, "index") for s in S["indices"]] + [(s, "equity") for s in S["stocks"]]
    acc, down, ser, frames, idx = _accepted(S), {}, {}, {}, {}
    for sym, kind in todo:
        f = fetch_series(sym, kind, sources, start, S, end, down, say)
        rep = ser[sym] = {"symbol": sym, "kind": kind, "rows": 0, "tried": f["tried"], "status": "unverified"}
        if f["df"] is None:
            rep["reasons"] = ["no source served this series"]
            continue
        rep.update(source=f["source"], fetched_at=str(pd.Timestamp.now(tz=IST)))
        df, rej = _prep(f["df"], sym, kind, f["source"])
        # the second source first (a Yahoo split table is only known once its bars were fetched), then the actions
        raw2, sname = None, None
        for o in f["others"]:
            if down.get(o.name, 0) >= 3:
                continue
            try:
                s2 = o.daily(sym, kind, start, end)
                down[o.name] = 0
            except Exception:
                down[o.name] = down.get(o.name, 0) + 1
                continue
            if len(s2):
                raw2, sname = _prep(s2, sym, kind, o.name)[0], o.name
                break
        actions, asrc = _config_actions(S, sym), "config" if S["corporate_actions"] else "none"
        if kind != "index":
            for src in [f["primary"], *f["others"]]:
                try:
                    a = src.actions(sym, kind)
                except Exception:
                    continue
                actions = pd.concat([a, actions]).drop_duplicates("date", keep="last") if len(actions) else a
                asrc = src.name + ("+config" if len(_config_actions(S, sym)) else "")
                break
            else:
                asrc = "config only" if len(actions) else "unavailable"
        actions = actions.reset_index(drop=True)
        jump = S["index_jump"] if kind == "index" else S["stock_jump"]
        adj, events = adjust(df, actions, kind, jump, S["action_tol"], acc)
        second = adjust(raw2, actions, kind, jump, S["action_tol"], acc)[0] if raw2 is not None else None
        x = crosscheck(adj, second, sym, int(S["crosscheck_sample"]), float(S["crosscheck_tol"]), int(S["seed"]))
        x["second_source"] = sname
        rep.update(rows=len(adj), first=str(adj.index.min().date()), last=str(adj.index.max().date()), rejected=rej,
                   rejected_total=int(sum(rej.values())), actions_source=asrc, events=events, crosscheck=x,
                   actions=[{**a, "date": str(pd.Timestamp(a["date"]).date())} for a in actions.to_dict("records")],
                   content_hash=frame_hash(adj))
        frames[sym], idx[sym] = adj, adj.index
        mr = x["match_rate"]
        say(f"  {sym}: {len(adj):,} rows from {f['source']}, {sum(1 for e in events if e['type'] == 'unadjusted_jump')} jump(s), "
            f"cross-check {'n/a' if mr is None else format(mr, '.1%')} vs {sname}")
    mdays, cal = market_days(idx, holidays, official, [s for s in S["indices"] if s in idx]) if idx else (
        pd.DatetimeIndex([]), {"official_years": [], "peer_calendar_years": []})
    for sym, adj in frames.items():
        rep = ser[sym]
        rep["gaps"] = gap_report(adj.index, mdays, holidays)
        rep["status"], rep["reasons"] = decide(rep, S, start)
        adj["series_status"] = rep["status"]
    return write_dataset(Path(out_root), frames, ser, S, cal, start, end, now)


def write_dataset(root: Path, frames: dict, ser: dict, S: dict, cal: dict, start, end, now: pd.Timestamp) -> dict:
    ds = Path(root) / "daily-history" / str(now.date())
    shards = []
    if frames:
        allr = pd.concat(frames.values()).reset_index()
        allr["date"] = pd.to_datetime(allr["date"])
        allr = allr[COLS].sort_values(["date", "symbol"]).reset_index(drop=True)
        for y, g in allr.groupby(allr["date"].dt.year):
            p = ds / f"daily_{y}.parquet"
            h = _write_once(g.reset_index(drop=True), p)            # immutable: a different re-run is a different dataset
            shards.append({"file": p.name, "year": int(y), "rows": int(len(g)), "symbols": int(g["symbol"].nunique()),
                           "content_hash": h, "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
                           "sources": {k: int(v) for k, v in g["source"].value_counts().items()}})
    verified = [s for s, r in ser.items() if r["status"] == "verified"]
    man = {"dataset": "daily-history", "version": VERSION, "as_of": str(now.date()), "fetched_at": str(now),
           "range": [str(start), str(end)], "status": "verified" if ser and len(verified) == len(ser) else "unverified",
           "verified_series": verified, "unverified_series": [s for s in ser if s not in verified],
           "thresholds": {k: S[k] for k in ("stock_jump", "index_jump", "action_tol", "crosscheck_sample", "crosscheck_tol",
                                            "crosscheck_min_compared", "crosscheck_min_match", "max_gap_fraction",
                                            "start_slack_days", "seed")},
           "calendar": cal, "series": ser, "shards": shards,
           "note": "open/high/low/close are as the source printed them; adj_* are adjusted for splits/bonuses only where the "
                   "data shows the source did not already apply them. Nothing is forward-filled. A series is 'verified' "
                   "only when its status says so; the dataset is verified only when every series is."}
    ds.mkdir(parents=True, exist_ok=True)
    tmp = ds / "manifest.tmp"
    tmp.write_text(json.dumps(man, indent=1, default=str))
    tmp.replace(ds / "manifest.json")
    man["path"] = str(ds)
    return man


def release_names(ds: Path) -> list[str]:
    return [p.name for p in sorted(Path(ds).iterdir()) if p.suffix in (".parquet", ".json")]


def render(man: dict) -> list[str]:
    L = [f"daily-history {man['as_of']}: {len(man['verified_series'])} verified, {len(man['unverified_series'])} unverified "
         f"of {len(man['series'])} series; {sum(s['rows'] for s in man['shards']):,} rows in {len(man['shards'])} shard(s)"]
    for s, r in man["series"].items():
        mr = (r.get("crosscheck") or {}).get("match_rate")
        jumps = sum(1 for e in r.get("events", []) if e["type"] == "unadjusted_jump")
        L.append(f"  {s:<12} {r['status']:<10} {r.get('source') or '-':<6} rows {r['rows']:>6,} jumps {jumps} "
                 f"xcheck {'n/a' if mr is None else format(mr, '.0%')} gaps {(r.get('gaps') or {}).get('missing', '-')}"
                 + ("" if r["status"] == "verified" else f"  [{'; '.join(r.get('reasons', []))[:140]}]"))
    return L
