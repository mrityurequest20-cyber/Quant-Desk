"""Versioned causal features, the 30-minute label, bar validation and data fingerprints.

The features are the DirectionModel's own (`intraday/quant.py`: `features_5m`), causal by construction: row i uses
5-minute bars up to and including bar i and the previous session, nothing later. `FEATURE_VERSION` hashes the feature
list and the code that computes them, so a model trained on one definition is never fed another (`live.py` refuses).

A sample is one completed 5-minute bar of one symbol:
  ts          the decision time: the bar's end (bar start + 5 minutes), when its close is known
  features    FEATURES at ts
  y           1 if the close 30 minutes later is above this close (the existing label), NaN if the session ends first
  fwd_ret     log return a trade gets: entry `delay_bars` bars after ts, exit 30 minutes after entry (costs come later)
  label_end   when the label is known: the exit bar's end. Purging and the ledger both use it.
  sig5        the rolling 5-minute σ at ts (for volatility regimes; not a model input)
  day_ret     the session's move so far in σ units (for the trend/range regime; not a model input)
"""
from __future__ import annotations

import hashlib
import inspect

import numpy as np
import pandas as pd

from ..intraday import quant as Q

IST = "Asia/Kolkata"
BAR = pd.Timedelta(minutes=5)
FEATURES = list(Q.FEATURES)
HORIZON_BARS = Q.HORIZON_BARS                      # 6 × 5 minutes = the existing 30-minute horizon
OPEN_T, CLOSE_T = (9, 15), (15, 30)


def _code_hash(*objs) -> str:
    h = hashlib.sha256()
    for o in objs:
        h.update(inspect.getsource(o).encode())
    return h.hexdigest()


FEATURE_VERSION = "f1-" + hashlib.sha256(("|".join(FEATURES) + _code_hash(Q._day_features, Q.features_5m, Q.to_5m))
                                         .encode()).hexdigest()[:10]
LABEL_VERSION = f"y30-h{HORIZON_BARS}-" + hashlib.sha256(_code_hash(Q.features_5m).encode()).hexdigest()[:8]


def fingerprint(df: pd.DataFrame | None) -> str:
    """SHA-256 (16 hex) of a bar frame's timestamps and OHLC, rounded so float noise doesn't change it."""
    if df is None or df.empty:
        return "empty"
    cols = [c for c in ("open", "high", "low", "close") if c in df.columns]
    x = df[cols].astype(float).round(4)
    body = pd.util.hash_pandas_object(x, index=True).to_numpy().tobytes()
    return hashlib.sha256(body).hexdigest()[:16]


# ---- validation ------------------------------------------------------------------------------------------------------
def validate_bars(df: pd.DataFrame | None, holidays: set | None = None, now: pd.Timestamp | None = None,
                  max_age_min: float | None = None, jump: float = 0.05, freq_min: int = 5) -> tuple[pd.DataFrame, dict]:
    """Clean a bar frame and say what was wrong with it.

    Fixed (and counted): out-of-order rows (sorted), duplicate timestamps (identical ones dropped; conflicting ones
    dropped entirely, since neither can be trusted), rows with missing or non-positive prices, bars outside the
    09:15–15:30 session or on a weekend / exchange holiday, high < low.
    Flagged: sessions with a bar-to-bar move above `jump` (an adjustment or a bad print: the whole session is
    excluded; an index has no corporate actions, so a real 5% jump in 5 minutes is rare enough to quarantine),
    missing bars inside a session (gaps), and a stale feed (last bar older than `max_age_min` at `now`).
    `ok` is False when anything was excluded for cause or the feed is stale."""
    rep = {"rows_in": 0, "out_of_order": 0, "duplicates": 0, "conflicting_duplicates": 0, "missing": 0,
           "bad_ohlc": 0, "outside_session": 0, "closed_days": 0, "jump_days": [], "gaps": 0, "stale": False,
           "last_bar": None, "issues": []}
    if df is None or df.empty:
        rep["issues"].append("no bars")
        rep["ok"] = False
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"]), rep
    d = df.copy()
    rep["rows_in"] = int(len(d))
    idx = pd.DatetimeIndex(d.index)
    d.index = idx.tz_localize(IST) if idx.tz is None else idx.tz_convert(IST)
    if not d.index.is_monotonic_increasing:
        rep["out_of_order"] = int((np.diff(d.index.asi8) < 0).sum())
        d = d.sort_index(kind="stable")
    if "volume" not in d.columns:
        d["volume"] = 0.0
    dup = d.index.duplicated(keep=False)
    if dup.any():
        g = d[dup].groupby(level=0)[["open", "high", "low", "close"]].nunique().max(axis=1)
        conflicting = set(g[g > 1].index)
        rep["duplicates"] = int(d.index.duplicated().sum())
        rep["conflicting_duplicates"] = len(conflicting)
        d = d[~d.index.duplicated(keep="last")]
        if conflicting:
            d = d[~d.index.isin(list(conflicting))]
    px = d[["open", "high", "low", "close"]].apply(pd.to_numeric, errors="coerce")
    miss = px.isna().any(axis=1) | (px <= 0).any(axis=1)
    rep["missing"] = int(miss.sum())
    bad = (px["high"] < px["low"]) & ~miss
    rep["bad_ohlc"] = int(bad.sum())
    d = d[~miss & ~bad]
    t = d.index
    mins = t.hour * 60 + t.minute
    inside = (mins >= OPEN_T[0] * 60 + OPEN_T[1]) & (mins < CLOSE_T[0] * 60 + CLOSE_T[1])
    rep["outside_session"] = int((~inside).sum())
    d = d[inside]
    hol = set(holidays or ())
    closed = np.array([(x.weekday() >= 5) or (x.date() in hol) for x in d.index], dtype=bool)
    rep["closed_days"] = len({x.date() for x, c in zip(d.index, closed) if c})
    d = d[~closed]
    if len(d):
        c = d["close"].to_numpy(float)
        o = d["open"].to_numpy(float)
        days = np.array(d.index.date)
        same = np.r_[False, days[1:] == days[:-1]]
        step = np.abs(np.r_[0.0, np.diff(np.log(c))])
        bar_jump = np.abs(np.log(np.maximum(d["high"].to_numpy(float), 1e-9) / np.maximum(d["low"].to_numpy(float), 1e-9))) > jump
        jumps = (same & (step > jump)) | bar_jump | (~same & (np.abs(np.log(o / np.r_[c[0], c[:-1]])) > 4 * jump))
        jdays = sorted({str(x) for x in days[jumps & (np.arange(len(c)) > 0)]} | {str(x) for x in days[bar_jump]})
        rep["jump_days"] = jdays
        if jdays:
            d = d[~pd.Index([str(x) for x in d.index.date]).isin(jdays)]
        for day, part in d.groupby(d.index.date):
            span = (part.index[-1] - part.index[0]) / pd.Timedelta(minutes=freq_min) + 1
            rep["gaps"] += int(max(0, round(span) - len(part)))
    rep["rows_out"] = int(len(d))
    if len(d):
        rep["last_bar"] = str(d.index[-1])
        if now is not None and max_age_min is not None:
            age = (pd.Timestamp(now) - (d.index[-1] + pd.Timedelta(minutes=freq_min))) / pd.Timedelta(minutes=1)
            o_, c_ = (pd.Timestamp(now).tz_convert(IST).hour * 60 + pd.Timestamp(now).tz_convert(IST).minute,
                      CLOSE_T[0] * 60 + CLOSE_T[1])
            in_session = OPEN_T[0] * 60 + OPEN_T[1] <= o_ < c_ and pd.Timestamp(now).date() == d.index[-1].date()
            rep["stale"] = bool(in_session and age > max_age_min)
    for k in ("out_of_order", "duplicates", "conflicting_duplicates", "missing", "bad_ohlc", "outside_session", "closed_days", "gaps"):
        if rep[k]:
            rep["issues"].append(f"{k.replace('_', ' ')}: {rep[k]}")
    if rep["jump_days"]:
        rep["issues"].append(f"sessions quarantined for a >{jump:.0%} jump: {', '.join(rep['jump_days'])}")
    if rep["stale"]:
        rep["issues"].append("stale feed")
    rep["ok"] = bool(not rep["conflicting_duplicates"] and not rep["jump_days"] and not rep["stale"] and len(d) > 0)
    return d, rep


# ---- samples ---------------------------------------------------------------------------------------------------------
def build_samples(bars5: pd.DataFrame, symbol: str, delay_bars: int = 0, prev_close: float = float("nan"),
                  prev_sig: float = float("nan")) -> pd.DataFrame:
    """Validated 5-minute bars of one symbol → one row per completed bar (see the module docstring)."""
    cols = FEATURES + ["y", "fwd_ret", "entry_px", "symbol", "ts", "day", "label_end", "sig5", "day_ret", "minute"]
    if bars5 is None or bars5.empty:
        return pd.DataFrame(columns=cols)
    f = Q.features_5m(bars5, prev_close, prev_sig)
    f = f.drop(columns=["day"]).join(pd.Series([str(x) for x in f.index.date], index=f.index, name="day"))
    out = []
    for day, part in bars5.groupby(bars5.index.date):
        c = part["close"].to_numpy(float)
        n = len(c)
        ent = np.full(n, np.nan)
        ext = np.full(n, np.nan)
        k = HORIZON_BARS + delay_bars
        if n > k:
            ent[: n - k] = c[delay_bars: n - HORIZON_BARS]
            ext[: n - k] = c[k:]
        end = pd.Series(part.index, index=part.index).shift(-k) + BAR      # the exit bar's end (NaT past the close)
        lr = pd.Series(np.r_[np.nan, np.diff(np.log(c))])
        sig = lr.rolling(12, min_periods=4).std().bfill().fillna(Q.SIG_DEFAULT).to_numpy()
        day_ret = np.log(c / part["open"].to_numpy(float)[0]) / (sig * np.sqrt(np.arange(1, n + 1)))
        g = pd.DataFrame({"fwd_ret": np.log(ext / ent), "entry_px": ent,
                          "label_end": end,
                          "sig5": sig, "day_ret": day_ret,
                          "minute": ((part.index - pd.Timestamp(day, tz=IST)) / pd.Timedelta(minutes=1)).to_numpy() - 555},
                         index=part.index)
        out.append(g)
    extra = pd.concat(out)
    s = f.join(extra)
    s["symbol"] = symbol
    s["ts"] = s.index + BAR
    s.loc[s["fwd_ret"].isna(), "y"] = np.nan                       # no exit inside the session: no label
    return s.reset_index(drop=True)[cols]


def samples_from_bars(bars1_or_5: dict[str, pd.DataFrame], holidays: set | None = None, delay_bars: int = 0,
                      minute_bars: bool = True) -> tuple[pd.DataFrame, dict]:
    """{symbol: bars} → (samples of all symbols, quality report per symbol). 1-minute bars are validated, then
    resampled to the model's 5-minute bars."""
    parts, report = [], {}
    for sym, b in sorted(bars1_or_5.items()):
        clean, rep = validate_bars(b, holidays, freq_min=1 if minute_bars else 5)
        b5 = Q.to_5m(clean) if minute_bars else clean
        rep["fingerprint"] = fingerprint(b5)
        rep["days"] = int(len(set(b5.index.date))) if len(b5) else 0
        report[sym] = rep
        if len(b5):
            parts.append(build_samples(b5, sym, delay_bars))
    s = pd.concat(parts, ignore_index=True) if parts else build_samples(None, "")
    return s.sort_values(["ts", "symbol"], kind="stable").reset_index(drop=True), report


def session_bucket(minute) -> np.ndarray:
    """Minutes since 09:15 → open (first hour), midday, close (from 13:30)."""
    m = np.asarray(minute, dtype=float)
    return np.where(m < 60, "open", np.where(m < 255, "midday", "close"))
