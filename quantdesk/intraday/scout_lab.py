"""The scout's strategy library (shadow, offline): the intraday strategies traders actually use, each with its OWN structural stop, every one run
over every index and stock and scored under every exit policy. Not limited to the desk's eight. docs/ASYMMETRY_SCOUT.md.

Each strategy is written once, for a LONG, on 5-minute bars known at the bar's close; a short is the same rule on the negated prices. A signal at 5-minute
bar b enters at the NEXT minute's open (minute 5 x (b + 1)). The stop is the strategy's own level, floored at the desk's noise floor (0.75 x the 5-minute
ATR) and capped at 3 x ATR so a tiny or huge structural stop cannot inflate R. At most 3 signals per strategy and direction a session, at least 60 minutes
apart. Outcomes come from `scout.outcomes` (stop wins a tie), before costs; the same point-in-time features as the grid are attached so a rule can mix
strategy and conditions. Nothing here trades; the output is a research candidate, never evidence for a gate, a promotion or a profit claim."""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

import numpy as np
import pandas as pd

from .scout import (DECISIONS, NOISE_FLOOR_FRAC, SEAL_FROM, Refused, _blocks, _flip, _grid, _sessions, feature_row, outcomes, vix_line)

COOLDOWN_BARS, MAX_PER_DAY = 12, 3
STOP_FLOOR_ATR, STOP_CAP_ATR = 0.75, 3.0
NB = 75                                   # 5-minute bars in a session
LIBRARY: dict[str, callable] = {}


def strategy(name: str):
    def deco(fn):
        LIBRARY[name] = fn
        return fn
    return deco


def sh(x: np.ndarray, n: int = 1) -> np.ndarray:
    """x shifted later by n bars (NaN before): sh(x)[b] is the value one bar ago."""
    out = np.full(len(x), np.nan)
    out[n:] = x[:-n]
    return out


def roll(x: np.ndarray, n: int, how: str) -> np.ndarray:
    s = pd.Series(x).rolling(n, min_periods=n)
    return getattr(s, how)().to_numpy()


@dataclass
class View:
    """One session, one direction (prices already negated for a short), on 5-minute bars, every indicator causal."""
    b: np.ndarray
    o: np.ndarray
    h: np.ndarray
    l: np.ndarray
    c: np.ndarray
    atr: np.ndarray
    e9: np.ndarray
    e21: np.ndarray
    rsi: np.ndarray
    bm: np.ndarray
    bu: np.ndarray
    bl: np.ndarray
    bw: np.ndarray
    vw: np.ndarray
    orh: np.ndarray
    orl: np.ndarray
    orh30: np.ndarray
    orl30: np.ndarray
    daylo: np.ndarray
    PH: float
    PL: float
    PC: float
    gap: float
    PR: float


def make_view(a: dict, p: dict, vwap1: np.ndarray, Bp: np.ndarray) -> View:
    h5, l5 = a["high"].reshape(NB, 5).max(1), a["low"].reshape(NB, 5).min(1)
    o5, c5 = a["open"][::5], a["close"][4::5]
    pc5 = p["close"][4::5]
    full = np.concatenate([Bp[-14:], h5 - l5])
    atr = np.convolve(full, np.ones(14) / 14, "valid")[1:NB + 1]
    cf = pd.Series(np.concatenate([pc5, c5]))
    e9, e21 = cf.ewm(span=9, adjust=False).mean().to_numpy()[-NB:], cf.ewm(span=21, adjust=False).mean().to_numpy()[-NB:]
    d = cf.diff()
    up, dn = d.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean(), (-d.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    rsi = (100 - 100 / (1 + up / dn)).fillna(50).to_numpy()[-NB:]            # no losses at all reads 100; no moves at all reads 50
    bm_f = cf.rolling(20).mean()
    sd = cf.rolling(20).std()
    bm, bu, bl = bm_f.to_numpy()[-NB:], (bm_f + 2 * sd).to_numpy()[-NB:], (bm_f - 2 * sd).to_numpy()[-NB:]
    bw = (bu - bl) / np.abs(bm)
    b = np.arange(NB)
    orh, orl = np.where(b >= 2, h5[:3].max(), np.nan), np.where(b >= 2, l5[:3].min(), np.nan)
    orh30, orl30 = np.where(b >= 5, h5[:6].max(), np.nan), np.where(b >= 5, l5[:6].min(), np.nan)
    PH, PL, PC = float(p["high"].max()), float(p["low"].min()), float(p["close"][-1])
    return View(b, o5, h5, l5, c5, atr, e9, e21, rsi, bm, bu, bl, bw, vwap1[4::5], orh, orl, orh30, orl30, np.minimum.accumulate(l5),
                PH, PL, PC, float(a["open"][0] - PC), PH - PL)


def _fresh(c, level):
    return (c > level) & (sh(c) <= level)


@strategy("orb15")
def _orb15(V):
    return _fresh(V.c, V.orh) & (V.b >= 3) & (V.b <= 24), (V.orh + V.orl) / 2


@strategy("orb30")
def _orb30(V):
    return _fresh(V.c, V.orh30) & (V.b >= 6) & (V.b <= 30), (V.orh30 + V.orl30) / 2


@strategy("pdh_break")
def _pdh(V):
    return _fresh(V.c, V.PH) & (V.b >= 2), np.full(NB, V.PH) - 0.5 * V.atr


@strategy("range_break_30m")
def _rb30(V):
    hi, lo = roll(sh(V.h), 6, "max"), roll(sh(V.l), 6, "min")
    return (V.c > hi) & ((hi - lo) <= 7.5 * V.atr) & (V.b >= 8), (hi + lo) / 2


@strategy("range_break_60m")
def _rb60(V):
    hi, lo = roll(sh(V.h), 12, "max"), roll(sh(V.l), 12, "min")
    return (V.c > hi) & ((hi - lo) <= 10 * V.atr) & (V.b >= 14), (hi + lo) / 2


@strategy("vwap_pullback")
def _vwp(V):
    return (V.e9 > V.e21) & (V.c > V.vw) & (V.l <= V.vw + 0.1 * V.atr) & (V.b >= 9), V.vw - 0.35 * V.atr


@strategy("vwap_reclaim")
def _vwr(V):
    return (V.c > V.vw) & (sh(V.c) <= sh(V.vw)) & (V.e9 > sh(V.e9)) & (V.b >= 6), roll(V.l, 3, "min")


@strategy("ema_cross")
def _emax(V):
    return (V.e9 > V.e21) & (sh(V.e9) <= sh(V.e21)) & (V.b >= 6), roll(V.l, 6, "min")


@strategy("ema21_pullback")
def _e21(V):
    return (V.e9 > V.e21) & (V.l <= V.e21 + 0.1 * V.atr) & (V.c > V.e21) & (V.b >= 9), V.e21 - 0.5 * V.atr


@strategy("open_drive_pullback")
def _drive(V):
    drive = (V.c[5] - V.o[0]) >= 2 * V.atr[5]
    m = drive & (sh(V.c) < sh(V.o)) & (V.c > V.o) & (V.c > V.o[0] + 0.5 * (V.c[5] - V.o[0])) & (V.b >= 7) & (V.b <= 30)
    return m, roll(V.l, 3, "min")


@strategy("gap_and_go")
def _gapgo(V):
    return (V.gap >= 0.3 * V.PR) & _fresh(V.c, V.orh) & (V.b >= 3) & (V.b <= 24), (V.orh + V.orl) / 2


@strategy("gap_reversal")
def _gaprev(V):
    return (V.gap <= -0.3 * V.PR) & _fresh(V.c, V.orh) & (V.b >= 3) & (V.b <= 30), V.daylo


@strategy("nr7_break")
def _nr7(V):
    rng = V.h - V.l
    narrowest = (rng == roll(rng, 7, "min")).astype(float)
    return (sh(narrowest) > 0) & (V.c > sh(V.h)) & (V.b >= 8), sh(V.l)


@strategy("squeeze_release")
def _sq(V):
    q = pd.Series(V.bw).rolling(40, min_periods=20).quantile(0.2).to_numpy()
    return (sh(V.bw) <= sh(q)) & (V.c > V.bu) & (V.b >= 6), V.bm


@strategy("rsi_dip")
def _rsi(V):
    return (V.rsi <= 25) & (V.c > V.o) & (V.b >= 6), roll(V.l, 3, "min") - 0.25 * V.atr


@strategy("bollinger_fade")
def _bbf(V):
    return (sh(V.c) < sh(V.bl)) & (V.c > V.bl) & (V.b >= 6), roll(V.l, 2, "min")


@strategy("failed_breakdown")
def _fbd(V):
    below = roll((sh(V.c) < V.orl).astype(float), 4, "max") > 0
    return below & (V.c > V.orl) & (V.b >= 4) & (V.b <= 30), roll(V.l, 6, "min")


@strategy("momentum_ignition")
def _ign(V):
    rng = V.h - V.l
    with np.errstate(divide="ignore", invalid="ignore"):
        top = (V.c - V.l) / rng
    return (rng >= 2 * V.atr) & (top >= 0.8) & (V.c > sh(V.h)) & (V.b >= 3), V.l


@strategy("pivot_bounce")
def _piv(V):
    piv = (V.PH + V.PL + V.PC) / 3
    return (V.l <= piv + 0.1 * V.atr) & (V.c > piv) & (V.c > V.o) & (V.c > V.vw) & (V.b >= 6), piv - 0.5 * V.atr


@strategy("afternoon_trend")
def _aft(V):
    return (V.b == 54) & (V.c > V.vw) & (V.e9 > V.e21) & (V.c > V.orh), V.vw - 0.5 * V.atr


def session_trades(day: pd.DataFrame, prior: pd.DataFrame | None, symbol: str, vix: pd.Series | None = None, kind: str = "index",
                   only: tuple[str, ...] | None = None) -> list[dict]:
    """Every strategy's trades in one session, both directions, with the point-in-time features and every exit policy's outcome."""
    g, gp = _grid(day), (_grid(prior) if prior is not None and len(prior) else None)
    if g is None or gp is None:
        return []
    a0, missing = g
    p0, _ = gp
    Bp = _blocks(p0)
    atr_prior = float(Bp.mean())
    date = day.index[0].date()
    vix_open = vix_line(vix, day, prior)
    out: list[dict] = []
    for d in (1, -1):
        a, p = _flip(a0, d), _flip(p0, d)
        o, h, l, c, v = a["open"], a["high"], a["low"], a["close"], a["volume"]
        w = v if v.sum() > 0 else np.ones(len(c))
        vwap1 = np.cumsum((h + l + c) / 3 * w) / np.cumsum(w)
        V = make_view(a, p, vwap1, Bp)
        for name, fn in LIBRARY.items():
            if only and name not in only:
                continue
            with np.errstate(invalid="ignore"):
                mask, stop = fn(V)
            last, n = -10 ** 9, 0
            for bi in np.flatnonzero(np.nan_to_num(mask.astype(float)) > 0):
                m = 5 * (bi + 1)
                if m not in DECISIONS_SET or bi - last < COOLDOWN_BARS or n >= MAX_PER_DAY or not stop[bi] == stop[bi]:
                    continue
                atr = float(V.atr[bi])
                ent = float(o[m])
                raw = ent - float(stop[bi])
                if not (atr > 0) or raw <= 0:
                    continue
                R = min(max(raw, STOP_FLOOR_ATR * atr, NOISE_FLOOR_FRAC * abs(ent)), STOP_CAP_ATR * atr)
                last, n = bi, n + 1
                row = {"strategy": name, "symbol": symbol, "kind": kind, "day": date,
                       "ts": day.index[0].normalize() + pd.Timedelta(minutes=555 + m), "direction": d, "risk_pts": R,
                       "risk_pct": R / abs(ent) * 100, "bar_gap": missing}
                row.update(outcomes(a, m, ent, R))
                row.update(feature_row(a, p, vwap1, m - 1, R, atr, atr_prior, date, vix_open))
                out.append(row)
    return out


DECISIONS_SET = set(DECISIONS)


def build_trades(bars: dict[str, pd.DataFrame], symbols: list[str], kind: str, first: str | None = None, last: str | None = None,
                 vix: pd.Series | None = None, seal: bool = True, only: tuple[str, ...] | None = None, say=print) -> pd.DataFrame:
    """The library's trades for every symbol-session in the window. Index sessions from SEAL_FROM are refused, not skipped."""
    rows: list[dict] = []
    for sym in symbols:
        if sym not in bars:
            raise Refused(f"no minutes for {sym}")
        sess = _sessions(bars[sym])
        days = sorted(sess)
        n0 = len(rows)
        for k, d in enumerate(days):
            if k == 0 or (first and str(d) < first) or (last and str(d) > last):
                continue
            if seal and d >= SEAL_FROM:
                raise Refused(f"{sym} {d}: sessions from {SEAL_FROM} are sealed for a later pre-registered test; use --to {SEAL_FROM - dt.timedelta(days=1)} or earlier")
            rows += session_trades(sess[d], sess[days[k - 1]], sym, vix, kind, only)
        say(f"  {sym}: {len(rows) - n0} trades")
    if not rows:
        raise Refused("no trade: no session left after the prior-session requirement and the window")
    df = pd.DataFrame(rows)
    for k in (2, 3, 4, 6):
        df[f"reach_{k}"] = df[f"reach_{k}"].astype(bool)
    return df


def _finish(out, trades: pd.DataFrame, params: dict, source: dict, grid: pd.DataFrame | None, mining: bool, say, prior_cells: int = 0, **mine_kw) -> dict:
    import json
    import os
    from .scout import EVIDENCE, NOT_FOR, _check_out, code_state
    from .scout_discover import write_lab_report
    out.mkdir(parents=True, exist_ok=True)
    tmp = out / "scout_trades.parquet.tmp"
    trades.to_parquet(tmp, index=False)
    os.replace(tmp, out / "scout_trades.parquet")
    man = {"kind": "scout_lab", "code": code_state(), "params": params, "source": source, "evidence": EVIDENCE, "not_for": NOT_FOR,
           "rows": int(len(trades)), "strategies": sorted(trades["strategy"].unique()), "first": str(trades["day"].min()), "last": str(trades["day"].max()),
           "sealed_from": str(SEAL_FROM), "cooldown_bars": COOLDOWN_BARS, "max_per_day": MAX_PER_DAY, "stop_floor_atr": STOP_FLOOR_ATR, "stop_cap_atr": STOP_CAP_ATR}
    (out / "manifest.json").write_text(json.dumps(man, indent=1, default=str))
    write_lab_report(out, trades, grid, run_mining=mining, say=say, prior_cells=prior_cells, **mine_kw)
    return man


def run_dataset_lab(dataset, out, symbols=None, first=None, last=None, grid_dir=None, mining: bool = True, say=print, prior_cells: int = 0, **mine_kw) -> dict:
    """The library over the index dataset's OPEN sessions (the sealed ones are dropped on load), then the leaderboard and the miner."""
    from pathlib import Path
    from .scout import INDEX_SYMBOLS, _check_out, assert_open, normalize_first, require_open_window
    from .shadowlab import _digest, _load_bars
    out = Path(out).resolve()
    _check_out(out)
    last = require_open_window(last)                # refused, not shortened
    first = normalize_first(first)
    symbols = list(symbols or INDEX_SYMBOLS)
    bars = _load_bars(dataset, symbols, None)
    for s in bars:
        bars[s] = bars[s][bars[s].index.date < SEAL_FROM]
    vix = bars["INDIAVIX"]["close"] if "INDIAVIX" in bars else None
    trades = build_trades(bars, symbols, "index", first, last, vix, say=say)
    grid = pd.read_parquet(Path(grid_dir) / "scout_candidates.parquet") if grid_dir else None
    assert_open(grid, f"--grid {grid_dir}")
    return _finish(out, trades, {"first": first, "last": last, "symbols": symbols}, {"path": str(dataset), "digest": _digest(dataset), "use": "underlying_features"},
                   grid, mining, say, prior_cells=prior_cells, **mine_kw)


def run_stocks_lab(stock_dir, out, symbols=None, say=print) -> dict:
    from pathlib import Path
    from .scout import _check_out
    from .shadowlab import load_stock_bars
    out = Path(out).resolve()
    _check_out(out)
    bars = load_stock_bars(Path(stock_dir))
    syms = [s for s in (symbols or sorted(bars)) if s in bars and not s.startswith("INDIA")]
    trades = build_trades(bars, syms, "stock", seal=False, say=say)
    return _finish(out, trades, {"symbols": syms}, {"path": str(stock_dir), "use": "stock minutes (release)"}, None, False, say)
