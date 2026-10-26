"""Where the replay reads minutes from. Three read-only sources, all already produced by the desk:

1. the desk's own recorder folders  <root>/<day>/<SYMBOL>_1m.csv   (NIFTY, BANKNIFTY, INDIAVIX; runtime/intraday/data)
2. Kotak backfill files             index.parquet / options_<U>.parquet, plain or as release assets `<asof>_index.parquet`
3. GitHub release assets            option-minutes-YYYYQn / option-minutes-YYYY, pulled with the warehouse's ReleaseStore

Nothing is invented: a symbol or day with no file simply has no bars."""
from __future__ import annotations

import datetime as dt
from pathlib import Path

import pandas as pd

from ..intraday.feeds import IST, normalise_bars

OHLCV = ["open", "high", "low", "close", "volume"]


def _ist(ts: pd.Series) -> pd.Series:
    ts = pd.to_datetime(ts)
    return ts.dt.tz_localize(IST) if ts.dt.tz is None else ts.dt.tz_convert(IST)


def _bars(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["ts"] = _ist(df["ts"])
    df = df.drop_duplicates("ts", keep="last").sort_values("ts").set_index("ts")
    for c in OHLCV:
        if c not in df:
            df[c] = 0.0
    return df[OHLCV].astype(float)


def recorded_minutes(root: Path, symbol: str) -> pd.DataFrame:
    """The desk recorder's <root>/<day>/<symbol>_1m.csv files, concatenated (empty frame when none)."""
    parts = []
    for p in sorted(Path(root).glob(f"*/{symbol}_1m.csv")):
        try:
            dt.date.fromisoformat(p.parent.name)
            parts.append(pd.read_csv(p))
        except (ValueError, pd.errors.ParserError, OSError):
            continue
    if not parts:
        return pd.DataFrame(columns=OHLCV)
    return _bars(pd.concat(parts, ignore_index=True))


def kotak_index_minutes(root: Path, symbol: str) -> pd.DataFrame:
    parts = []
    for p in sorted(Path(root).rglob("*index.parquet")):
        df = pd.read_parquet(p)
        if "underlying" in df and (df["underlying"] == symbol).any():
            parts.append(df[df["underlying"] == symbol][["ts", *OHLCV]] if "volume" in df else df[df["underlying"] == symbol])
    if not parts:
        return pd.DataFrame(columns=OHLCV)
    return _bars(pd.concat(parts, ignore_index=True))


def index_minutes(roots: list[Path], symbol: str) -> tuple[pd.DataFrame, str]:
    """Underlying minutes: the Kotak backfill first (traded index candles), the desk's recorder otherwise; both merged
    when both exist (the recorder wins a duplicated minute: it is what the desk really saw). Returns (bars, source)."""
    kot, rec = [], []
    for r in roots:
        k = kotak_index_minutes(r, symbol)
        if len(k):
            kot.append(k)
        c = recorded_minutes(r, symbol)
        if len(c):
            rec.append(c)
    frames = [(pd.concat(kot), "kotak") if kot else None, (pd.concat(rec), "recorder") if rec else None]
    frames = [f for f in frames if f is not None]
    if not frames:
        return pd.DataFrame(columns=OHLCV), "none"
    df = pd.concat([f[0] for f in frames])          # kotak first, recorder last: keep="last" lets the recorder win
    df = df[~df.index.duplicated(keep="last")].sort_index()
    return normalise_bars(df), "+".join(f[1] for f in frames)


def option_minutes(roots: list[Path], underlying: str) -> pd.DataFrame:
    """Kotak option minutes for one underlying: ts, expiry, strike, right, open..volume (de-duplicated by contract/minute)."""
    parts = []
    for r in roots:
        for p in sorted(Path(r).rglob(f"*options_{underlying}.parquet")):
            parts.append(pd.read_parquet(p))
    if not parts:
        return pd.DataFrame()
    df = pd.concat(parts, ignore_index=True)
    df["ts"] = _ist(df["ts"])
    df["expiry"] = pd.to_datetime(df["expiry"]).dt.date
    df["strike"] = df["strike"].astype(float)
    return df.drop_duplicates(["expiry", "strike", "right", "ts"], keep="last").sort_values("ts").reset_index(drop=True)


class OptionBook:
    """Option minutes indexed for lookup: (expiry, strike, right) -> bars by minute."""

    def __init__(self, df: pd.DataFrame):
        self.df = df
        self.by: dict[tuple, pd.DataFrame] = {}
        if len(df):
            for key, g in df.groupby(["expiry", "strike", "right"], sort=True):
                self.by[key] = g.set_index("ts")[OHLCV]

    def days(self) -> set:
        return set(self.df["ts"].dt.date) if len(self.df) else set()

    def expiries_on(self, day: dt.date) -> list[dt.date]:
        if not len(self.df):
            return []
        d = self.df[self.df["ts"].dt.date == day]
        return sorted(set(d["expiry"]))

    def bars(self, expiry, strike, right, day: dt.date) -> pd.DataFrame | None:
        b = self.by.get((expiry, float(strike), right))
        if b is None:
            return None
        b = b[b.index.date == day]
        return b if len(b) else None


def pull_releases(prefix: str, days: list[dt.date], dest: Path, store_for=None, say=print) -> list[str]:
    """Download option-minute assets for the quarters (and years) the date range touches, through the warehouse's
    ReleaseStore (`gh`, the default token reads public/own releases). Missing releases read as none."""
    from ..data.warehouse import ReleaseStore
    store_for = store_for or (lambda tag: ReleaseStore(tag))
    tags = sorted({f"{prefix}-{d.year}Q{(d.month - 1) // 3 + 1}" for d in days} | {f"{prefix}-{d.year}" for d in days})
    got = []
    for tag in tags:
        st = store_for(tag)
        names = [n for n in st.assets() if n.endswith(".parquet") and ("index" in n or "options_" in n)]
        if not names:
            say(f"  release {tag}: nothing")
            continue
        sub = Path(dest) / tag
        sub.mkdir(parents=True, exist_ok=True)
        got += st.pull(sub, names)
        say(f"  release {tag}: {len(names)} file(s)")
    return got
