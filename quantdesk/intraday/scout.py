"""The asymmetry scout (shadow, offline): where do trades that can pay several times their risk start, and what does the desk's own
entry look like beside them?  docs/ASYMMETRY_SCOUT.md.

It places nothing and touches no desk path. For every symbol-session it takes a candidate every 5 minutes (09:30 to 14:30 IST), in both
directions, with one uniform stop (`stop_atr` x the 5-minute ATR, never under the desk's own noise floor), enters at the NEXT minute's open
and labels FIRST PASSAGE to k x risk (k = 2, 3, 4, 6) before the stop, to the 15:15 square-off. Stop wins a tie inside a minute. An unbounded random walk
reaches k x risk before a 1 x risk stop with probability 1 / (k + 1); the session is finite, so the pooled empirical rate is the baseline and only the lift
over it is information.

Features are read from bars up to and including the decision minute and from earlier sessions: nothing later (tested). The labels are the only
thing that looks forward. Source minutes are third party (`external_unverified`): the output is a research candidate, never evidence for a
gate, a promotion, the paper gate or a profit claim. The most recent sessions are SEALED (`SEAL_FROM`): this module refuses them, so a later
pre-registered test has data nobody has looked at.
"""
from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path

import numpy as np
import pandas as pd

from .shadowlab import Refused, _digest, _inside_git_tree, _load_bars, code_state, load_stock_bars

KS = (2, 3, 4, 6)
N_MIN = 375                          # 09:15 to 15:29
END = 360                            # the 15:15 square-off: bars 0..359 are tradeable
DECISIONS = tuple(range(15, 316, 5))  # minutes after 09:15 (09:30 .. 14:30)
MIN_BARS = 300
STOP_ATR = 1.5
NOISE_FLOOR_FRAC = 0.0004            # the desk's floor: 0.04% of the price
SEAL_FROM = dt.date(2023, 1, 1)      # index sessions from here on are sealed for a later pre-registered test
COST_R = 0.05                        # ASSUMED all-in cost of a long-option round trip in R (journal: fees 0.013R + spread and slippage); not measured
INDEX_SYMBOLS = ("NIFTY", "BANKNIFTY")
FEATURES = ("mins", "weekday", "gap_pr", "atr_ratio", "rng30_atr", "day_rng_pr", "or_w_pr", "trend30_atr", "trend60_atr", "vwap_atr",
            "room_pd_r", "room_or_r", "room_next_r", "n_obst_3r", "open_air", "broke_or", "broke_pd", "vix", "vix_chg", "risk_pct")
LABELS = tuple(f"reach_{k}" for k in KS) + ("mfe_r", "r_end", "t_reach_3")
EVIDENCE = "external_unverified"
NOT_FOR = ("never evidence for a gate, a promotion, the paper gate or a profitability claim; a research candidate only. Underlying-price "
           "first passage, not option P&L; sessions and the two directions are not independent samples.")


def _grid(day: pd.DataFrame) -> tuple[dict[str, np.ndarray], int] | None:
    """One session on the 375-minute grid (a missing minute carries the last close); None if too thin."""
    idx = day.index
    mod = (idx.hour * 60 + idx.minute - 555).to_numpy()
    ok = (mod >= 0) & (mod < N_MIN)
    if int(ok.sum()) < MIN_BARS:
        return None
    arr = {k: np.full(N_MIN, np.nan) for k in ("open", "high", "low", "close", "volume")}
    for k in arr:
        arr[k][mod[ok]] = day[k].to_numpy(dtype=float)[ok]
    missing = int(np.isnan(arr["close"]).sum())
    c = pd.Series(arr["close"]).ffill().bfill().to_numpy()
    for k in ("open", "high", "low"):
        arr[k] = np.where(np.isnan(arr[k]), c, arr[k])
    arr["close"] = c
    arr["volume"] = np.nan_to_num(arr["volume"], nan=0.0)
    return arr, missing


def _blocks(a: dict[str, np.ndarray]) -> np.ndarray:
    """Ranges of the 75 non-overlapping 5-minute blocks of a session."""
    return a["high"].reshape(75, 5).max(1) - a["low"].reshape(75, 5).min(1)


def _flip(a: dict[str, np.ndarray], d: int) -> dict[str, np.ndarray]:
    """The session as seen by a trade in direction d: for a short, prices are negated so every rule reads 'long'."""
    if d > 0:
        return a
    return {"open": -a["open"], "high": -a["low"], "low": -a["high"], "close": -a["close"], "volume": a["volume"]}


def session_candidates(day: pd.DataFrame, prior: pd.DataFrame | None, symbol: str, stop_atr: float = STOP_ATR,
                       vix: pd.Series | None = None, kind: str = "index") -> list[dict]:
    """Candidates of one session, both directions. `prior` is the previous session's minutes (required: the levels and the ATR warm-up)."""
    g, gp = _grid(day), (_grid(prior) if prior is not None and len(prior) else None)
    if g is None or gp is None:
        return []
    a0, missing = g
    p0, _ = gp
    B, Bp = _blocks(a0), _blocks(p0)
    atr_prior = float(Bp.mean())
    date = day.index[0].date()
    vix_open = None
    if vix is not None and len(vix):
        start = day.index[0].normalize()
        today = vix.loc[start:day.index[-1]]
        before = vix.loc[prior.index[0]:start - pd.Timedelta(seconds=1)]
        if len(today):
            mod = (today.index.hour * 60 + today.index.minute - 555).to_numpy()
            ok = (mod >= 0) & (mod < N_MIN)
            vx = np.full(N_MIN, np.nan)
            vx[mod[ok]] = today.to_numpy(dtype=float)[ok]
            vx = pd.Series(vx).ffill().bfill().to_numpy()
            vix_open = (vx, float(before.iloc[-1]) if len(before) else np.nan)
    out: list[dict] = []
    for d in (1, -1):
        a, p = _flip(a0, d), _flip(p0, d)
        o, h, l, c, v = a["open"], a["high"], a["low"], a["close"], a["volume"]
        PH, PC = float(p["high"].max()), float(p["close"][-1])
        PR = float(p["high"].max() - p["low"].min())
        gap = float(o[0] - PC)
        tp = (h + l + c) / 3
        w = v if v.sum() > 0 else np.ones(N_MIN)
        vwap = np.cumsum(tp * w) / np.cumsum(w)
        for m in DECISIONS:
            i, j = m - 1, m
            atr = float(np.concatenate([Bp[-14:], B[:m // 5]])[-14:].mean())
            if not atr > 0:
                continue
            price = abs(float(c[i]))
            R = max(stop_atr * atr, NOISE_FLOOR_FRAC * price)
            ent = float(o[j])
            fh, fl = h[j:END], l[j:END]
            hit_stop = np.flatnonzero(fl <= ent - R)
            t_stop = int(hit_stop[0]) if hit_stop.size else len(fl)
            row = {"symbol": symbol, "kind": kind, "day": date, "ts": day.index[0].normalize() + pd.Timedelta(minutes=555 + m),
                   "direction": d, "stop_atr": stop_atr, "risk_pts": R, "risk_pct": R / price * 100, "bar_gap": missing}
            first3 = None
            for k in KS:
                hit = np.flatnonzero(fh >= ent + k * R)
                reached = bool(hit.size) and int(hit[0]) < t_stop
                row[f"reach_{k}"] = reached
                if k == 3 and reached:
                    first3 = int(hit[0])
            row["mfe_r"] = max(0.0, float(fh[:t_stop].max() - ent) / R) if t_stop > 0 else 0.0
            row["r_end"] = -1.0 if t_stop < len(fl) else float(c[END - 1] - ent) / R
            row["t_reach_3"] = float(first3) if first3 is not None else np.nan
            # ---- features: bars up to and including minute i, and earlier sessions
            lo30 = max(0, i - 29)
            rng30 = float(h[lo30:i + 1].max() - l[lo30:i + 1].min())
            day_hi, day_lo = float(h[:i + 1].max()), float(l[:i + 1].min())
            orh = float(h[:15].max()) if i >= 14 else np.nan
            orl = float(l[:15].min()) if i >= 14 else np.nan
            ahead = [x for x in (PH, orh, day_hi) if x == x and x > c[i]]
            near = (min(ahead) - c[i]) / R if ahead else 10.0
            row.update({
                "mins": m, "weekday": date.weekday(),
                "gap_pr": gap / PR if PR > 0 else np.nan,
                "atr_ratio": atr / atr_prior if atr_prior > 0 else np.nan,
                "rng30_atr": rng30 / atr,
                "day_rng_pr": (day_hi - day_lo) / PR if PR > 0 else np.nan,
                "or_w_pr": float(h[:15].max() - l[:15].min()) / PR if PR > 0 else np.nan,
                "trend30_atr": float(c[i] - c[max(0, i - 30)]) / atr,
                "trend60_atr": float(c[i] - c[max(0, i - 60)]) / atr,
                "vwap_atr": float(c[i] - vwap[i]) / atr,
                "room_pd_r": float(np.clip((PH - c[i]) / R, -10, 10)),
                "room_or_r": float(np.clip((orh - c[i]) / R, -10, 10)),
                "room_next_r": float(min(near, 10.0)),
                "n_obst_3r": float(sum(1 for x in ahead if (x - c[i]) / R <= 3.0)),
                "open_air": float(not ahead),
                "broke_or": float(c[i] > orh) if orh == orh else np.nan,
                "broke_pd": float(c[i] > PH),
                "vix": float(vix_open[0][i]) if vix_open else np.nan,
                "vix_chg": float(vix_open[0][i] - vix_open[1]) if vix_open else np.nan,
            })
            out.append(row)
    return out


def _frame(rows: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    for k in KS:
        df[f"reach_{k}"] = df[f"reach_{k}"].astype(bool)
    return df


def _sessions(bars: pd.DataFrame) -> dict[dt.date, pd.DataFrame]:
    return {d: g for d, g in bars.groupby(bars.index.date)}


def build(bars: dict[str, pd.DataFrame], symbols: list[str], kind: str, stop_atr: float = STOP_ATR, first: str | None = None,
          last: str | None = None, vix: pd.Series | None = None, seal: bool = True, say=print) -> pd.DataFrame:
    """Candidates for every symbol-session in the window. Index sessions on or after SEAL_FROM are refused, not skipped."""
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
                raise Refused(f"{sym} {d}: sessions from {SEAL_FROM} are sealed for a later pre-registered test; use --last {SEAL_FROM - dt.timedelta(days=1)} or earlier")
            rows += session_candidates(sess[d], sess[days[k - 1]], sym, stop_atr, vix, kind)
        say(f"  {sym}: {len(rows) - n0} candidates")
    if not rows:
        raise Refused("no candidate: no session left after the prior-session requirement and the window")
    return _frame(rows)


def _write(out: Path, df: pd.DataFrame, params: dict, source: dict) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    tmp = out / "scout_candidates.parquet.tmp"
    df.to_parquet(tmp, index=False)
    os.replace(tmp, out / "scout_candidates.parquet")
    man = {"kind": "scout", "code": code_state(), "params": params, "source": source, "evidence": EVIDENCE, "not_for": NOT_FOR,
           "rows": int(len(df)), "sessions": int(df[["symbol", "day"]].drop_duplicates().shape[0]),
           "first": str(df["day"].min()), "last": str(df["day"].max()), "sealed_from": str(SEAL_FROM),
           "by_symbol": {s: int(n) for s, n in df.groupby("symbol").size().items()},
           "base_rate_note": "a random walk reaches k x risk before a 1 x risk stop with probability 1/(k+1): 33.3%, 25%, 20%, 14.3% for k = 2, 3, 4, 6",
           "features": list(FEATURES), "labels": list(LABELS)}
    (out / "manifest.json").write_text(json.dumps(man, indent=1, default=str))
    return man


def _check_out(out: Path) -> None:
    git = _inside_git_tree(out)
    if git is not None:
        raise Refused(f"--out {out} is inside the git tree at {git}: third-party minutes must not land in a repository")
    if out.exists() and any(out.iterdir()):
        raise Refused(f"--out {out} must be new or empty")


def run_dataset(dataset: Path, out: Path, symbols: list[str] | None = None, stop_atr: float = STOP_ATR, first: str | None = None,
                last: str | None = None, say=print) -> dict:
    out = Path(out).resolve()
    _check_out(out)
    symbols = list(symbols or INDEX_SYMBOLS)
    bars = _load_bars(dataset, symbols, None)
    for s in bars:                                  # the sealed sessions are dropped here, before any computation
        bars[s] = bars[s][bars[s].index.date < SEAL_FROM]
    vix = bars["INDIAVIX"]["close"] if "INDIAVIX" in bars else None
    df = build(bars, symbols, "index", stop_atr, first, last, vix, say=say)
    return _write(out, df, {"stop_atr": stop_atr, "first": first, "last": last, "symbols": symbols},
                  {"path": str(dataset), "digest": _digest(dataset), "use": "underlying_features"})


def run_stocks(stock_dir: Path, out: Path, symbols: list[str] | None = None, stop_atr: float = STOP_ATR, say=print) -> dict:
    out = Path(out).resolve()
    _check_out(out)
    bars = load_stock_bars(Path(stock_dir))
    syms = [s for s in (symbols or sorted(bars)) if s in bars and not s.startswith("INDIA")]
    df = build(bars, syms, "stock", stop_atr, seal=False, say=say)
    return _write(out, df, {"stop_atr": stop_atr, "symbols": syms}, {"path": str(stock_dir), "use": "stock minutes (release)"})
