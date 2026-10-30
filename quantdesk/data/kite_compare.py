"""The Kite trial's measures (docs/ml/KITE_TRIAL.md), computed for one session from the recorded ticks and Kite's own historical candles.

Only counts and ratios leave this module: the ticks are licensed to the subscriber and stay in the recorder's folder. Every threshold below is the one the criteria document fixed
before any data existed; changing one here is changing the criteria, which is a new version of that document, not an edit.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

IST = "Asia/Kolkata"
OPEN_MIN, CLOSE_MIN = "09:15", "15:29"
THRESHOLDS = {"A1": 0.995, "A2": 3, "B1": 0.99, "B2": 0.97, "C1": 0.90, "C2": 0.99, "C3_median": 1.0, "C3_p99": 3.0}
CLOSE_TOL, RANGE_TOL = 0.0002, 0.0005
INDICES = ("NIFTY", "BANKNIFTY", "INDIAVIX")
FRONT_INDICES = ("NIFTY", "BANKNIFTY")
LATE = ("15:15", "15:28")


def load_ticks(folder: Path) -> pd.DataFrame:
    parts = sorted(Path(folder).glob("ticks_*.parquet"))
    if not parts:
        return pd.DataFrame()
    df = pd.concat([pd.read_parquet(p) for p in parts], ignore_index=True)
    df["ts_exchange"] = pd.to_datetime(df["ts_exchange"]).dt.tz_convert(IST)
    df["ts_recv"] = pd.to_datetime(df["ts_recv"]).dt.tz_convert(IST)
    return df.sort_values(["symbol", "ts_exchange"], kind="stable").reset_index(drop=True)


def session_minutes(day) -> pd.DatetimeIndex:
    d = pd.Timestamp(day).strftime("%Y-%m-%d")
    return pd.date_range(f"{d} {OPEN_MIN}", f"{d} {CLOSE_MIN}", freq="min", tz=IST)


def tick_bars(ticks: pd.DataFrame, symbol: str) -> pd.DataFrame:
    """One-minute OHLC from the ticks of one symbol (by exchange time), volume as the day's cumulative-volume difference where the feed carries it."""
    t = ticks[(ticks["symbol"] == symbol) & ticks["last_price"].notna()]
    if t.empty:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    g = t.set_index("ts_exchange").groupby(pd.Grouper(freq="min"))
    bars = g["last_price"].agg(open="first", high="max", low="min", close="last").dropna()
    vol = t.set_index("ts_exchange")["volume"].groupby(pd.Grouper(freq="min")).agg(["first", "last"])
    bars["volume"] = (vol["last"] - vol["first"]).reindex(bars.index)
    return bars


def frozen(bars: pd.DataFrame, min_run: int = 3) -> pd.DatetimeIndex:
    """The desk's F-02 rule (feeds.frozen_minutes; a test holds the two equal): runs of `min_run` or more bars with open = high = low = close = the previous close, within a day."""
    if bars is None or len(bars) < min_run:
        return pd.DatetimeIndex([], tz=IST)
    c, d = bars["close"], bars.index.normalize().to_numpy()
    same_day = np.r_[False, d[1:] == d[:-1]]
    flat = (bars["open"] == c) & (bars["high"] == c) & (bars["low"] == c) & (c == c.shift()) & same_day
    run = flat.groupby((~flat).cumsum()).transform("sum")
    return bars.index[(flat & (run >= min_run)).to_numpy()]


def longest_gap(have: pd.DatetimeIndex, minutes: pd.DatetimeIndex) -> int:
    present = minutes.isin(have)
    best = cur = 0
    for p in present:
        cur = 0 if p else cur + 1
        best = max(best, cur)
    return best


def measure_symbol(ticks: pd.DataFrame, reference: pd.DataFrame, symbol: str, day) -> dict:
    minutes = session_minutes(day)
    bars = tick_bars(ticks, symbol)
    have = bars.index.intersection(minutes)
    ref = reference[reference["symbol"] == symbol].copy() if len(reference) else pd.DataFrame()
    out = {"symbol": symbol, "minutes": len(minutes), "A1": len(have) / len(minutes), "A2": longest_gap(have, minutes)}
    if len(ref):
        ref["ts"] = pd.to_datetime(ref["ts"]).dt.tz_convert(IST)
        ref = ref.set_index("ts").reindex(minutes).dropna(subset=["close"])
        j = ref.join(bars, how="left", rsuffix="_t")
        ok_close = ((j["close_t"] - j["close"]).abs() / j["close"] <= CLOSE_TOL)
        ok_range = ((j["high_t"] - j["high"]).abs() / j["high"] <= RANGE_TOL) & ((j["low_t"] - j["low"]).abs() / j["low"] <= RANGE_TOL)
        out["B1"], out["B2"] = float(ok_close.fillna(False).mean()), float(ok_range.fillna(False).mean())
    else:
        out["B1"] = out["B2"] = None
    if symbol in FRONT_INDICES:
        d = pd.Timestamp(day).strftime("%Y-%m-%d")
        late = pd.date_range(f"{d} {LATE[0]}", f"{d} {LATE[1]}", freq="min", tz=IST)
        fr = frozen(bars)
        present = late.intersection(bars.index)
        out["C1"] = float((len(present) - len(present.intersection(fr))) / len(late))
    lat = (ticks.loc[ticks["symbol"] == symbol, "ts_recv"] - ticks.loc[ticks["symbol"] == symbol, "ts_exchange"]).dt.total_seconds().dropna()
    out["latency_n"] = int(len(lat))
    if len(lat):
        out["C3_median"], out["C3_p99"] = float(lat.median()), float(lat.quantile(0.99))
    return out


def cvd_correlation(ticks: pd.DataFrame, symbol: str) -> float | None:
    """C4 (descriptive): correlation of the minute CVD built from volume differences signed by the price change with the desk's close-location CVD, for a future."""
    t = ticks[(ticks["symbol"] == symbol) & ticks["last_price"].notna() & ticks["volume"].notna()].copy()
    if len(t) < 50:
        return None
    t["dv"] = t["volume"].diff().clip(lower=0)
    t["sign"] = np.sign(t["last_price"].diff()).replace(0, np.nan).ffill().fillna(0)
    t["signed"] = t["dv"] * t["sign"]
    tick_cvd = t.set_index("ts_exchange")["signed"].groupby(pd.Grouper(freq="min")).sum()
    b = tick_bars(ticks, symbol)
    rng = (b["high"] - b["low"]).replace(0, np.nan)
    loc_cvd = (b["volume"].fillna(0) * (2 * b["close"] - b["high"] - b["low"]) / rng).fillna(0)
    j = pd.concat([tick_cvd, loc_cvd], axis=1, join="inner").dropna()
    if len(j) < 10 or j.iloc[:, 0].std() == 0 or j.iloc[:, 1].std() == 0:
        return None
    return float(j.corr().iloc[0, 1])


def desk_dependence(ticks: pd.DataFrame, desk_bars: pd.DataFrame, symbol: str, day) -> dict:
    """C2: of the minutes where the desk's own bars are missing or frozen, the share the Kite tick bars cover. `desk_bars` has a `ts` column and OHLC (the journal's data/<day>/<symbol>_1m.csv)."""
    minutes = session_minutes(day)
    d = desk_bars.copy()
    d["ts"] = pd.to_datetime(d["ts"], utc=True).dt.tz_convert(IST)
    d = d.set_index("ts").sort_index()
    bad = minutes.difference(d.index.intersection(minutes)).union(frozen(d).intersection(minutes))
    covered = bad.intersection(tick_bars(ticks, symbol).index)
    return {"symbol": symbol, "bad_minutes": int(len(bad)), "covered": int(len(covered)), "C2": (len(covered) / len(bad)) if len(bad) else None}


def evaluate(measures: list[dict]) -> dict:
    """Session verdict: A1, A2, B1 and B2 for every recorded instrument. C3 (latency) is reported in the measures and is not a pass condition: exchange stamps are whole seconds and the runner's clock offset is not measured (docs/ml/KITE_TRIAL.md). Missing B (no reference) is a failure, never a pass."""
    reasons = []
    for m in measures:
        s = m["symbol"]
        if m["A1"] < THRESHOLDS["A1"]:
            reasons.append(f"{s}: A1 coverage {m['A1']:.3f} < {THRESHOLDS['A1']}")
        if m["A2"] > THRESHOLDS["A2"]:
            reasons.append(f"{s}: A2 longest gap {m['A2']} > {THRESHOLDS['A2']}")
        if m["B1"] is None or m["B1"] < THRESHOLDS["B1"]:
            reasons.append(f"{s}: B1 {m['B1']} < {THRESHOLDS['B1']}")
        if m["B2"] is None or m["B2"] < THRESHOLDS["B2"]:
            reasons.append(f"{s}: B2 {m['B2']} < {THRESHOLDS['B2']}")
    return {"passed": not reasons, "reasons": reasons}


def session_report(folder: Path, day, desk_dir: Path | None = None) -> dict:
    folder = Path(folder)
    ticks = load_ticks(folder)
    if ticks.empty:
        return {"day": str(pd.Timestamp(day).date()), "recorded": False, "passed": False, "reasons": ["no ticks were recorded"], "measures": []}
    ref_path = folder / "reference_minutes.parquet"
    reference = pd.read_parquet(ref_path) if ref_path.exists() else pd.DataFrame()
    tokens = json.loads((folder / "tokens.json").read_text()) if (folder / "tokens.json").exists() else {}
    symbols = sorted(set(tokens) | set(ticks["symbol"]))
    measures = [measure_symbol(ticks, reference, s, day) for s in symbols]
    events = []
    ev = folder / "events.jsonl"
    if ev.exists():
        events = [json.loads(x) for x in ev.read_text().splitlines() if x.strip()]
    rep = {"day": str(pd.Timestamp(day).date()), "recorded": True, "ticks": int(len(ticks)), "measures": measures,
           "C4_cvd_correlation": {s: cvd_correlation(ticks, s) for s in symbols if s.endswith("-FUT")},
           "D1_reconnects": sum(1 for e in events if e["kind"] == "reconnect"), "D1_closes": sum(1 for e in events if e["kind"] == "close"),
           "D3_bytes": int(sum(p.stat().st_size for p in folder.glob("*.parquet")))}
    if desk_dir is not None:
        rep["C2"] = []
        for s in FRONT_INDICES:
            p = Path(desk_dir) / f"{s}_1m.csv"
            if p.exists():
                rep["C2"].append(desk_dependence(ticks, pd.read_csv(p), s, day))
    rep.update(evaluate(measures))
    return rep


def render(rep: dict) -> str:
    L = [f"Kite trial, session {rep['day']}: {'PASS' if rep['passed'] else 'FAIL'}" + ("" if rep.get("recorded") else " (nothing recorded)")]
    for m in rep.get("measures", []):
        bits = [f"A1 {m['A1']:.3f}", f"gap {m['A2']}", f"B1 {m['B1'] if m['B1'] is None else round(m['B1'], 3)}", f"B2 {m['B2'] if m['B2'] is None else round(m['B2'], 3)}"]
        if "C1" in m:
            bits.append(f"C1 {m['C1']:.2f}")
        if "C3_median" in m:
            bits.append(f"latency {m['C3_median']:.2f}/{m['C3_p99']:.2f}s")
        L.append(f"  {m['symbol']}: " + ", ".join(bits))
    for r in rep.get("reasons", []):
        L.append(f"  fail: {r}")
    L.append(f"  ticks {rep.get('ticks', 0):,}, reconnects {rep.get('D1_reconnects', 0)}, closes {rep.get('D1_closes', 0)}, size {rep.get('D3_bytes', 0) / 1e6:.1f} MB")
    return "\n".join(L)
