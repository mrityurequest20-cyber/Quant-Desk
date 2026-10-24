"""Open-interest features and their forward grading, offline and in shadow (docs/prereg/oi_shadow_v1.json).

The live desk already reads OI (PCR, walls, max pain, futures build-up: `intraday/chains.py`, `chainflow.py`, `futures.py`) as small
votes. This module does not touch that. It asks one question the desk has never asked of its own tape: **is a strong OI wall
stickier than the option market's own volatility says a barrier at that distance should be?** It computes, from the recorded chain
tape (`chains-YYYY` Parquet), features known at a decision time, the outcome that followed, and the volatility-implied probability the
outcome should have had; the pre-registered test compares them (`oi_report`). Nothing here reads or writes the journal, places or sizes
anything, or imports the engine.

Why a contrast, not a rate. Implied volatility is usually above the volatility that follows, so *any* barrier is breached less often
than the IV-implied probability says, whatever sits behind it. That is the variance risk premium, not OI. The test therefore compares
decisions whose walls are strong with decisions whose walls are weak at the same implied probability: the premium is common to both
and cancels; only an effect of the OI itself is left.

Definitions (frozen by the spec; changing any of them changes `code_sha256` and the spec refuses the run):
- decision: every 15 minutes from 09:30 to 15:00 IST; the snapshot is the last one at or before it, at most 150 s old;
- expiry: the nearest expiry on or after the day that still has at least 60 minutes to run;
- M = the ATM straddle (mid of bid and ask, else last), in index points; the "implied move";
- call wall = the strike above spot with the most call OI; put wall = the strike below spot with the most put OI;
- wall multiple = that OI over the median OI of the side's strikes with OI > 0 inside spot ± 3 M;
- wall strength = the geometric mean of the two multiples;
- contained over h minutes = spot stayed strictly between the put wall and the call wall for the next h minutes (spot samples of the
  tape: about one a minute, so the tape under-counts extremes slightly; the same for strong and weak walls);
- implied probability = the survival probability of a driftless Brownian motion between the two walls over h minutes with
  sigma = ATM IV x sqrt(h / (252 x 375)) (trading minutes).
"""
from __future__ import annotations

import hashlib
import inspect
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import norm, t as student_t

SPEC = "oi_shadow_v1"
N_MIN = 375
DECISIONS = tuple(range(15, 346, 15))                   # minutes after 09:15: 09:30 ... 15:00
HORIZONS = (30, 60)
LOOKBACK = 30                                           # minutes over which changes are measured
MAX_AGE_S = 150.0                                       # a decision snapshot older than this is not used
MIN_TO_EXPIRY = 60.0                                    # an expiry with less than this to run is not the front one
BAND = 3.0                                              # half-width of the OI band, in implied moves
NEAR = 1.5                                              # half-width of the change band, in implied moves
MIN_COVER = 0.8                                         # share of a label window's minutes that must have a spot sample
OI_MAX = 1e12                                           # an OI print above this (or below 0) is a feed fault, not a position: the tape holds
                                                        # about +-1e18 (near 2**63) in 1.1% of snapshots; real OI is below 1e9
TRADING_MIN_PER_YEAR = 252 * N_MIN
IST = "Asia/Kolkata"
INDICES = ("NIFTY", "BANKNIFTY")
FORWARD_START = "2026-10-26"                            # the first session the pre-registered test may use; 5 to 23 Oct 2026 are development
P_IV_RANGE = (0.15, 0.90)                               # decisions whose implied containment probability is outside this say nothing about walls
# wall strength -> rank in [0, 1] by the empirical distribution of the 14 development sessions (5 to 23 Oct 2026), 21 breakpoints per index:
# frozen here, so a forward value is ranked against the past and clipped, never against the sample it is tested in.
STRENGTH_BREAKS = {
    "BANKNIFTY": [
        5.614,
        6.769,
        7.88,
        8.508,
        9.903,
        10.356,
        10.896,
        11.153,
        11.279,
        11.401,
        11.526,
        11.698,
        11.95,
        12.212,
        12.652,
        12.956,
        13.505,
        13.709,
        13.835,
        14.22,
        15.959
    ],
    "NIFTY": [
        1.824,
        2.168,
        2.391,
        2.591,
        3.034,
        3.517,
        3.845,
        4.044,
        4.237,
        4.377,
        4.551,
        4.682,
        5.015,
        5.116,
        5.348,
        5.528,
        5.78,
        6.158,
        6.461,
        7.322,
        11.053
    ]
}
COLUMNS = ["underlying", "day", "m", "expiry", "ts", "spot", "move", "iv", "to_expiry_min", "expiry_day",
           "call_wall", "put_wall", "wall_c_dist", "wall_p_dist", "mult_c", "mult_p", "strength",
           "pcr_band", "maxpain_dist", "com_c", "com_p", "d_com_c", "d_com_p",
           "call_write", "call_buy", "call_unwind", "put_write", "put_buy", "put_unwind", "band_oi_cover", "snap_age_s", "skipped_invalid"]
ADVANCED = [                                           # recorded from the first session, exploratory: none is tested for significance before its own spec
    "gex_ratio", "gwall_c_dist", "gwall_p_dist", "gwall_c_is_oi_wall", "gwall_p_is_oi_wall", "gex_flip_dist",                                  # gamma
    "wall_c_shift30", "wall_p_shift30", "wall_c_oi_growth30", "wall_p_oi_growth30", "wall_c_stable", "wall_p_stable", "maxpain_shift30",
    "net_write_accel",                                                                                                                         # dynamics
    "hhi_c", "hhi_p", "entropy_c", "entropy_p", "top3_c", "top3_p", "pin_share",                                                              # concentration
    "spread_atm_c", "spread_atm_p", "spread_wall_c", "spread_wall_p", "qimb_atm_c", "qimb_atm_p", "qimb_wall_c", "qimb_wall_p",             # quotes
    "pcr_vol", "turnover_c", "turnover_p", "vol30_pcr", "wall_defense_c", "wall_defense_p",                                                   # volume
    "iv_term", "oi_roll_share", "fwd_basis_bps", "rr_1m", "fly_1m"]                                                                           # term, forward, skew
COLUMNS = COLUMNS + ADVANCED
MIN_T_YEARS = 60.0 / 525600.0                          # gamma is not evaluated closer than an hour to expiry (it diverges at the money)
FLIP_STEPS = 61                                        # spot grid for the gamma flip: BAND implied moves either side
LABELS = ["contained30", "contained60", "ret30", "ret60", "p_iv30", "p_iv60", "cover30", "cover60"]
KEY = ["underlying", "day", "m"]
FEATURES = [c for c in COLUMNS if c not in KEY + ["expiry", "ts"]]


def code_sha256() -> str:
    """The source of every function that makes a feature, a label or an implied probability."""
    fns = (survival_prob, rank_strength, fit_within, wall_test, holm, oi_report, _spot_path, _mid, _snapshot, _wall, _multiple, _buildup, _max_pain, _gamma, _gamma_grid, _nearest_crossing, _conc, _spread_pct, _qimb, _iv_at, _atm_iv, advanced_features, _asof, snapshot_features, valid_oi, Snapshots, decision_row, decision_table, labels_for, tape_files, quarantine_report, run_day)
    src = "\n".join(inspect.getsource(f) for f in fns)
    consts = repr((SPEC, N_MIN, DECISIONS, HORIZONS, LOOKBACK, MAX_AGE_S, MIN_TO_EXPIRY, BAND, NEAR, MIN_COVER, TRADING_MIN_PER_YEAR, OI_MAX, FORWARD_START, P_IV_RANGE, MIN_T_YEARS, FLIP_STEPS, STRENGTH_BREAKS, COLUMNS))
    return hashlib.sha256((src + consts).encode()).hexdigest()


# ---- the implied probability -----------------------------------------------------------------------------------------
def survival_prob(a: float, b: float, s: float, terms: int = 8) -> float:
    """P(a driftless Brownian motion with standard deviation `s` at the horizon stays strictly inside (-b, a) the whole time), by the
    method of images. a, b > 0 are the distances to the upper and lower barrier in the same units as s. Inside the barriers at time 0.
    One barrier far away reduces it to 2 Phi(a/s) - 1."""
    if not (a > 0 and b > 0) or not (s > 0):
        return float("nan")
    w, U, L = a + b, a, -b
    k = np.arange(-terms, terms + 1)
    direct = norm.cdf((U - 2 * k * w) / s) - norm.cdf((L - 2 * k * w) / s)
    image = norm.cdf((-U - 2 * k * w) / s) - norm.cdf((L - 2 * U - 2 * k * w) / s)
    return float(np.clip((direct - image).sum(), 0.0, 1.0))


def valid_oi(g: pd.DataFrame) -> bool:
    """A snapshot is usable only if every OI print in it is plausible (finite, from 0 to OI_MAX). One implausible print quarantines the whole
    snapshot: it is dropped and counted, never clipped or repaired (the feed's fault is not known to be confined to the strike that shows it)."""
    for c in ("ce_oi", "pe_oi"):
        x = g[c].to_numpy(float)
        x = x[~np.isnan(x)]
        if len(x) and (np.isinf(x).any() or (x < 0).any() or (x > OI_MAX).any()):
            return False
    return True


def rank_strength(strength, underlying: str):
    """Wall strength -> its rank in [0, 1] among the development sessions of the same index (linear between breakpoints, clipped)."""
    br = np.asarray(STRENGTH_BREAKS[underlying], float)
    return np.interp(np.asarray(strength, float), br, np.linspace(0.0, 1.0, len(br)))


class Snapshots:
    """The rows of one expiry's chain grouped by snapshot timestamp, without slicing a frame per snapshot up front (a day has hundreds of
    thousands of rows and a decision needs two snapshots). `keys`: the snapshots' timestamps in nanoseconds UTC, sorted; `valid[i]`: whether
    snapshot i passes `valid_oi`, computed for all of them at once; `self[key]`: its raw rows."""

    def __init__(self, g: pd.DataFrame):
        ns = pd.DatetimeIndex(g["ts"]).tz_convert("UTC").as_unit("ns").asi8
        order = np.argsort(ns, kind="stable")
        self.g, ns = g.iloc[order], ns[order]
        self.keys, self.start = np.unique(ns, return_index=True)
        self.stop = np.r_[self.start[1:], len(ns)]
        ok = np.ones(len(self.keys), dtype=bool)
        for c in ("ce_oi", "pe_oi"):
            x = np.nan_to_num(self.g[c].to_numpy(float), nan=0.0)               # a missing print is no fault; an infinity becomes a huge finite number
            ok &= (np.minimum.reduceat(x, self.start) >= 0) & (np.maximum.reduceat(x, self.start) <= OI_MAX)
        self.valid = ok

    def __getitem__(self, key: int) -> pd.DataFrame:
        i = int(np.searchsorted(self.keys, key))
        return self.g.iloc[self.start[i]:self.stop[i]]


# ---- one snapshot ----------------------------------------------------------------------------------------------------
def _mid(bid, ask, ltp):
    """Mid of a two-sided quote, else the last price, else NaN."""
    ok = np.isfinite(bid) & np.isfinite(ask) & (bid > 0) & (ask >= bid)
    return np.where(ok, (bid + ask) / 2, np.where(np.isfinite(ltp) & (ltp > 0), ltp, np.nan))


def _snapshot(g: pd.DataFrame) -> pd.DataFrame:
    """One snapshot's rows -> strike-indexed frame with ce_mid / pe_mid added."""
    s = g.drop_duplicates("strike", keep="last").set_index("strike").sort_index()
    s["ce_mid"] = _mid(s["ce_bid"].to_numpy(float), s["ce_ask"].to_numpy(float), s["ce_ltp"].to_numpy(float))
    s["pe_mid"] = _mid(s["pe_bid"].to_numpy(float), s["pe_ask"].to_numpy(float), s["pe_ltp"].to_numpy(float))
    return s


def _wall(oi: pd.Series, side: str, spot: float) -> float:
    """The strike above (calls) or below (puts) spot with the most OI, or NaN."""
    part = oi[oi.index > spot] if side == "c" else oi[oi.index < spot]
    part = part.dropna()
    return float(part.idxmax()) if len(part) and part.max() > 0 else float("nan")


def _multiple(oi: pd.Series, wall: float, lo: float, hi: float) -> float:
    """The wall's OI over the median OI of the side's strikes with OI > 0 in [lo, hi]."""
    band = oi[(oi.index >= lo) & (oi.index <= hi) & (oi > 0)]
    return float(oi.loc[wall] / band.median()) if len(band) >= 3 and wall == wall and band.median() > 0 else float("nan")


def _max_pain(ks: np.ndarray, ce: np.ndarray, pe: np.ndarray) -> float:
    """The strike at which the total payoff owed to option holders is smallest, given call and put OI at each strike."""
    pain = (np.maximum(ks[:, None] - ks[None, :], 0) * ce[None, :]).sum(1) + (np.maximum(ks[None, :] - ks[:, None], 0) * pe[None, :]).sum(1)
    return float(ks[int(np.argmin(pain))])


def _buildup(snap: pd.DataFrame, past: pd.DataFrame, spot: float, move: float) -> dict:
    """OI added while the option got cheaper (written), dearer (bought) and OI removed (unwound), per side, over the strikes within NEAR implied
    moves of `spot` that both snapshots hold, each as a share of that side's OI there now; and the share of those strikes held by both."""
    nan = float("nan")
    out = {k: nan for k in ("call_write", "call_buy", "call_unwind", "put_write", "put_buy", "put_unwind", "band_oi_cover")}
    ks = snap.index.to_numpy(float)
    ce, pe = snap["ce_oi"].fillna(0.0), snap["pe_oi"].fillna(0.0)
    pce, ppe = past["ce_oi"].fillna(0.0), past["pe_oi"].fillna(0.0)
    near = [k for k in snap.index if abs(k - spot) <= NEAR * move and k in past.index]
    out["band_oi_cover"] = len(near) / max(1, int(((ks >= spot - NEAR * move) & (ks <= spot + NEAR * move)).sum()))
    for side, oi, poi, mid, pmid in (("call", ce, pce, "ce_mid", "ce_mid"), ("put", pe, ppe, "pe_mid", "pe_mid")):
        if not near:
            continue
        d = oi.loc[near].to_numpy(float) - poi.loc[near].to_numpy(float)
        dm = snap.loc[near, mid].to_numpy(float) - past.loc[near, pmid].to_numpy(float)
        base = oi.loc[near].sum()
        if not base > 0:
            continue
        up, dn, price_dn = np.maximum(d, 0.0), np.maximum(-d, 0.0), dm < 0
        out[f"{side}_write"] = float(up[price_dn].sum() / base)             # OI added while the option got cheaper: sold
        out[f"{side}_buy"] = float(up[~price_dn & np.isfinite(dm)].sum() / base)    # OI added while it got dearer: bought
        out[f"{side}_unwind"] = float(dn.sum() / base)
    return out


def snapshot_features(snap: pd.DataFrame, past: pd.DataFrame | None, spot: float, to_expiry_min: float) -> dict:
    """The features of one snapshot (strike-indexed, with ce_mid / pe_mid) and, for the change features, the snapshot LOOKBACK minutes
    before (or None). Everything is a function of these two snapshots only."""
    ks = snap.index.to_numpy(float)
    atm = float(ks[np.argmin(np.abs(ks - spot))])
    move = float(np.nansum([snap.at[atm, "ce_mid"], snap.at[atm, "pe_mid"]])) if np.isfinite(snap.at[atm, "ce_mid"]) and np.isfinite(snap.at[atm, "pe_mid"]) else float("nan")
    ivs = [v for v in (snap.at[atm, "ce_iv"], snap.at[atm, "pe_iv"]) if np.isfinite(v) and v > 0]
    out = {"move": move, "iv": float(np.mean(ivs)) if ivs else float("nan")}
    nan = float("nan")
    keys = ("call_wall", "put_wall", "wall_c_dist", "wall_p_dist", "mult_c", "mult_p", "strength", "pcr_band", "maxpain_dist", "com_c", "com_p",
            "d_com_c", "d_com_p", "call_write", "call_buy", "call_unwind", "put_write", "put_buy", "put_unwind", "band_oi_cover")
    if not (move > 0):
        return {**out, **{k: nan for k in keys}}
    ce, pe = snap["ce_oi"].fillna(0.0), snap["pe_oi"].fillna(0.0)
    cw, pw = _wall(ce, "c", spot), _wall(pe, "p", spot)
    lo, hi = spot - BAND * move, spot + BAND * move
    mc, mp = _multiple(ce, cw, lo, hi), _multiple(pe, pw, lo, hi)
    out.update({"call_wall": cw, "put_wall": pw, "wall_c_dist": (cw - spot) / move, "wall_p_dist": (spot - pw) / move, "mult_c": mc, "mult_p": mp,
                "strength": math.sqrt(mc * mp) if mc > 0 and mp > 0 else nan})
    band = (ks >= lo) & (ks <= hi)
    out["pcr_band"] = float(pe[band].sum() / ce[band].sum()) if ce[band].sum() > 0 else nan
    out["maxpain_dist"] = float((_max_pain(ks, ce.to_numpy(float), pe.to_numpy(float)) - spot) / move)

    def com(oi, side, frame):
        k = frame.index.to_numpy(float)
        sel = (k > spot) & (k <= hi) if side == "c" else (k < spot) & (k >= lo)
        w = oi[sel].to_numpy(float)
        return float((k[sel] * w).sum() / w.sum() - spot) / move if w.sum() > 0 else nan

    out["com_c"], out["com_p"] = com(ce, "c", snap), com(pe, "p", snap)
    out.update({k: nan for k in ("d_com_c", "d_com_p", "call_write", "call_buy", "call_unwind", "put_write", "put_buy", "put_unwind", "band_oi_cover")})
    if past is not None and len(past):
        pce, ppe = past["ce_oi"].fillna(0.0), past["pe_oi"].fillna(0.0)
        out["d_com_c"] = out["com_c"] - com(pce, "c", past) if out["com_c"] == out["com_c"] else nan
        out["d_com_p"] = out["com_p"] - com(ppe, "p", past) if out["com_p"] == out["com_p"] else nan
        out.update(_buildup(snap, past, spot, move))
    return out


# ---- the advanced features -------------------------------------------------------------------------------------------
def _gamma(spot: float, strikes, t_years: float, sigma) -> np.ndarray:
    """Black-Scholes gamma (rate and dividend zero) of an option at each strike with volatility `sigma` (a fraction); 0 where the volatility is
    missing or not positive. Dividing by nothing else: a per-unit-of-OI measure, so sums of gamma x OI are comparable across strikes."""
    k, sig = np.asarray(strikes, float), np.asarray(sigma, float)
    ok = np.isfinite(sig) & (sig > 0) & (k > 0) & (spot > 0)
    out = np.zeros(k.shape)
    sq = sig[ok] * math.sqrt(t_years)
    d1 = (np.log(spot / k[ok]) + 0.5 * sig[ok] ** 2 * t_years) / sq
    out[ok] = norm.pdf(d1) / (spot * sq)
    return out


def _gamma_grid(spots: np.ndarray, strikes, t_years: float, sigma) -> np.ndarray:
    """`_gamma` for every spot in `spots` at once: an array of shape (len(spots), len(strikes))."""
    k, sig, sp = np.asarray(strikes, float), np.asarray(sigma, float), np.asarray(spots, float)[:, None]
    ok = np.isfinite(sig) & (sig > 0) & (k > 0)
    out = np.zeros((sp.shape[0], k.shape[0]))
    sq = sig[ok] * math.sqrt(t_years)
    d1 = (np.log(sp / k[ok][None, :]) + 0.5 * sig[ok][None, :] ** 2 * t_years) / sq[None, :]
    out[:, ok] = norm.pdf(d1) / (sp * sq[None, :])
    return out


def _nearest_crossing(u: np.ndarray, v: np.ndarray) -> float:
    """Where the piecewise-linear curve (u, v) crosses zero, the crossing closest to u = 0; NaN if it never does."""
    best = float("nan")
    for i in range(len(u) - 1):
        a, b = v[i], v[i + 1]
        if a == 0.0:
            x = float(u[i])
        elif a * b < 0:
            x = float(u[i] - a * (u[i + 1] - u[i]) / (b - a))
        else:
            continue
        if best != best or abs(x) < abs(best):
            best = x
    if best != best and len(v) and v[-1] == 0.0:
        best = float(u[-1])
    return best


def _conc(w: np.ndarray) -> tuple[float, float, float]:
    """Concentration of positive weights: Herfindahl index and Shannon entropy, both scaled to [0, 1] (1 = all in one strike for the first, all
    spread evenly for the second), and the share of the three largest. NaN unless at least three weights are positive."""
    w = np.asarray(w, float)
    w = w[np.isfinite(w) & (w > 0)]
    n = len(w)
    if n < 3:
        return float("nan"), float("nan"), float("nan")
    p = w / w.sum()
    return float(((p ** 2).sum() - 1 / n) / (1 - 1 / n)), float(-(p * np.log(p)).sum() / math.log(n)), float(np.sort(p)[-3:].sum())


def _spread_pct(bid, ask) -> float:
    """Quoted spread as a share of the mid; NaN unless a two-sided quote."""
    if not (np.isfinite(bid) and np.isfinite(ask)) or bid <= 0 or ask < bid:
        return float("nan")
    return float((ask - bid) / ((ask + bid) / 2))


def _qimb(bid_qty, ask_qty) -> float:
    """Queue imbalance at the touch, (bid size - ask size) / (bid size + ask size) in [-1, 1]; NaN if either size is missing."""
    if not (np.isfinite(bid_qty) and np.isfinite(ask_qty)) or bid_qty + ask_qty <= 0:
        return float("nan")
    return float((bid_qty - ask_qty) / (bid_qty + ask_qty))


def _iv_at(snap: pd.DataFrame, strike: float, side: str) -> float:
    """The implied volatility (in points) of the out-of-the-money option on `side` ('p' below spot, 'c' above) interpolated at `strike`, with no
    extrapolation: NaN outside the strikes quoted."""
    col = "pe_iv" if side == "p" else "ce_iv"
    s = snap[col].replace([np.inf, -np.inf], np.nan)
    s = s[(s > 0)].dropna()
    if len(s) < 2 or strike < s.index.min() or strike > s.index.max():
        return float("nan")
    return float(np.interp(strike, s.index.to_numpy(float), s.to_numpy(float)))


def _atm_iv(snap: pd.DataFrame, spot: float) -> float:
    """Mean of the call and put implied volatilities (points) at the strike nearest `spot`; NaN if neither is positive."""
    ks = snap.index.to_numpy(float)
    atm = float(ks[np.argmin(np.abs(ks - spot))])
    v = [x for x in (snap.at[atm, "ce_iv"], snap.at[atm, "pe_iv"]) if np.isfinite(x) and x > 0]
    return float(np.mean(v)) if v else float("nan")


def _asof(frames, ts_sorted: np.ndarray, t_ns: int):
    """The last valid snapshot at or before `t_ns` and no older than MAX_AGE_S: (strike-indexed frame, spot, age in seconds), or None."""
    i = int(np.searchsorted(ts_sorted, t_ns, side="right")) - 1
    if i < 0 or (t_ns - int(ts_sorted[i])) / 1e9 > MAX_AGE_S:
        return None
    raw = frames[ts_sorted[i]]
    return _snapshot(raw), float(raw["spot"].iloc[0]), (t_ns - int(ts_sorted[i])) / 1e9


def advanced_features(snap: pd.DataFrame, spot: float, move: float, to_expiry_min: float, base: dict, past=None, past2=None, nxt=None) -> dict:
    """Gamma, dynamics, concentration, quote, volume, term / forward and skew features of one decision, exploratory (see ADVANCED). `base`: the
    decision's `snapshot_features` (walls, implied volatility). `past`, `past2`, `nxt`: (frame, spot) of the snapshot LOOKBACK and 2 x LOOKBACK
    minutes earlier and of the next expiry now, or None. A function of these snapshots only."""
    nan = float("nan")
    out = {c: nan for c in ADVANCED}
    if not (move > 0):
        return out
    ks = snap.index.to_numpy(float)
    ce, pe = snap["ce_oi"].fillna(0.0).to_numpy(float), snap["pe_oi"].fillna(0.0).to_numpy(float)
    lo, hi = spot - BAND * move, spot + BAND * move
    band = (ks >= lo) & (ks <= hi)
    cw, pw = base.get("call_wall", nan), base.get("put_wall", nan)

    # gamma: the dealer-sign-free ratio, the gamma-weighted walls, and where call-heavy gamma turns put-heavy
    t = max(to_expiry_min / 525600.0, MIN_T_YEARS)
    sc, sp = snap["ce_iv"].to_numpy(float) / 100, snap["pe_iv"].to_numpy(float) / 100
    wc, wp = _gamma(spot, ks, t, sc) * ce, _gamma(spot, ks, t, sp) * pe
    tc, tp = wc[band].sum(), wp[band].sum()
    if tc + tp > 0:
        out["gex_ratio"] = float((tc - tp) / (tc + tp))
    for side, w, mask, wall in (("c", wc, ks > spot, cw), ("p", wp, ks < spot, pw)):
        if mask.any() and w[mask].max() > 0:
            g = float(ks[mask][int(np.argmax(w[mask]))])
            out[f"gwall_{side}_dist"] = (g - spot) / move if side == "c" else (spot - g) / move
            out[f"gwall_{side}_is_oi_wall"] = float(g == wall)
    u = np.linspace(-BAND, BAND, FLIP_STEPS)
    spots = spot + move * u
    net = (_gamma_grid(spots, ks, t, sc) * ce[None, :] - _gamma_grid(spots, ks, t, sp) * pe[None, :]).sum(1)
    out["gex_flip_dist"] = _nearest_crossing(u, net)

    # dynamics: how the walls and the writing moved over the last LOOKBACK minutes
    if past is not None:
        ps, pspot = past
        pce, ppe = ps["ce_oi"].fillna(0.0), ps["pe_oi"].fillna(0.0)
        pcw, ppw = _wall(pce, "c", pspot), _wall(ppe, "p", pspot)
        if cw == cw and pcw == pcw:
            out["wall_c_shift30"] = (cw - pcw) / move
        if pw == pw and ppw == ppw:
            out["wall_p_shift30"] = (pw - ppw) / move
        for side, wall, soi, poi in (("c", cw, snap["ce_oi"], pce), ("p", pw, snap["pe_oi"], ppe)):
            if wall == wall and wall in ps.index and poi.loc[wall] > 0 and np.isfinite(soi.loc[wall]):
                out[f"wall_{side}_oi_growth30"] = float(soi.loc[wall] / poi.loc[wall] - 1)
        out["maxpain_shift30"] = (_max_pain(ks, ce, pe) - _max_pain(ps.index.to_numpy(float), pce.to_numpy(float), ppe.to_numpy(float))) / move
        if past2 is not None:
            p2s, p2spot = past2
            p2cw, p2pw = _wall(p2s["ce_oi"].fillna(0.0), "c", p2spot), _wall(p2s["pe_oi"].fillna(0.0), "p", p2spot)
            if cw == cw:
                out["wall_c_stable"] = float((pcw == cw) + (p2cw == cw))
            if pw == pw:
                out["wall_p_stable"] = float((ppw == pw) + (p2pw == pw))
            now, prev = _buildup(snap, ps, spot, move), _buildup(ps, p2s, pspot, move)
            acc = (now["call_write"] - now["put_write"]) - (prev["call_write"] - prev["put_write"])
            out["net_write_accel"] = float(acc) if np.isfinite(acc) else nan

    # concentration of the band's OI
    out["hhi_c"], out["entropy_c"], out["top3_c"] = _conc(ce[band])
    out["hhi_p"], out["entropy_p"], out["top3_p"] = _conc(pe[band])
    tot = (ce + pe)
    if tot[band].sum() > 0:
        out["pin_share"] = float(tot[(np.abs(ks - spot) <= 0.5 * move)].sum() / tot[band].sum())

    # quotes at the money and at the walls
    atm = float(ks[np.argmin(np.abs(ks - spot))])
    g = lambda strike, col: float(snap.at[strike, col]) if col in snap.columns else nan
    out["spread_atm_c"], out["spread_atm_p"] = _spread_pct(g(atm, "ce_bid"), g(atm, "ce_ask")), _spread_pct(g(atm, "pe_bid"), g(atm, "pe_ask"))
    out["qimb_atm_c"], out["qimb_atm_p"] = _qimb(g(atm, "ce_bidq"), g(atm, "ce_askq")), _qimb(g(atm, "pe_bidq"), g(atm, "pe_askq"))
    if cw == cw:
        out["spread_wall_c"], out["qimb_wall_c"] = _spread_pct(g(cw, "ce_bid"), g(cw, "ce_ask")), _qimb(g(cw, "ce_bidq"), g(cw, "ce_askq"))
    if pw == pw:
        out["spread_wall_p"], out["qimb_wall_p"] = _spread_pct(g(pw, "pe_bid"), g(pw, "pe_ask")), _qimb(g(pw, "pe_bidq"), g(pw, "pe_askq"))

    # volume (the day's running total) against OI, and what traded in the last LOOKBACK minutes
    cv, pv = snap["ce_vol"].fillna(0.0).to_numpy(float), snap["pe_vol"].fillna(0.0).to_numpy(float)
    if cv[band].sum() > 0:
        out["pcr_vol"] = float(pv[band].sum() / cv[band].sum())
    if ce[band].sum() > 0:
        out["turnover_c"] = float(cv[band].sum() / ce[band].sum())
    if pe[band].sum() > 0:
        out["turnover_p"] = float(pv[band].sum() / pe[band].sum())
    if past is not None:
        ps, _ = past
        common = [k for k in snap.index[band] if k in ps.index]
        if common:
            dc = snap.loc[common, "ce_vol"].fillna(0.0).to_numpy(float) - ps.loc[common, "ce_vol"].fillna(0.0).to_numpy(float)
            dp = snap.loc[common, "pe_vol"].fillna(0.0).to_numpy(float) - ps.loc[common, "pe_vol"].fillna(0.0).to_numpy(float)
            if (dc >= 0).all() and (dp >= 0).all() and dc.sum() > 0:                     # a running total that fell was reset: no reading
                out["vol30_pcr"] = float(dp.sum() / dc.sum())
        for side, wall, vcol, ocol in (("c", cw, "ce_vol", "ce_oi"), ("p", pw, "pe_vol", "pe_oi")):
            if wall == wall and wall in ps.index and np.isfinite(snap.at[wall, ocol]) and snap.at[wall, ocol] > 0:
                dv = snap.at[wall, vcol] - ps.at[wall, vcol]
                if np.isfinite(dv) and dv >= 0:
                    out[f"wall_defense_{side}"] = float(dv / snap.at[wall, ocol])

    # forward, skew and the next expiry
    cmid, pmid = snap.at[atm, "ce_mid"], snap.at[atm, "pe_mid"]
    if np.isfinite(cmid) and np.isfinite(pmid):
        out["fwd_basis_bps"] = float(((atm + cmid - pmid) / spot - 1.0) * 1e4)
    ivp, ivc = _iv_at(snap, spot - move, "p"), _iv_at(snap, spot + move, "c")
    out["rr_1m"] = ivp - ivc if np.isfinite(ivp) and np.isfinite(ivc) else nan
    iv0 = base.get("iv", nan)
    out["fly_1m"] = (ivp + ivc) / 2 - iv0 if np.isfinite(ivp) and np.isfinite(ivc) and iv0 == iv0 else nan
    if nxt is not None:
        ns, nspot = nxt
        niv = _atm_iv(ns, nspot)
        if niv == niv and iv0 == iv0:
            out["iv_term"] = float(niv - iv0)
        nk = ns.index.to_numpy(float)
        nband = (nk >= lo) & (nk <= hi)
        n_oi = float((ns["ce_oi"].fillna(0.0).to_numpy(float) + ns["pe_oi"].fillna(0.0).to_numpy(float))[nband].sum())
        f_oi = float(tot[band].sum())
        if n_oi + f_oi > 0:
            out["oi_roll_share"] = n_oi / (n_oi + f_oi)
    return out


# ---- one day ---------------------------------------------------------------------------------------------------------
def decision_row(frames, ts_sorted: np.ndarray, t: pd.Timestamp, expiry: pd.Timestamp, day, m: int, underlying: str,
                 bad_ts: np.ndarray | None = None, next_frames=None, next_ts_sorted: np.ndarray | None = None) -> dict | None:
    """The row for one decision, or None when there is no usable snapshot. `frames`: ts -> raw rows of the snapshot (one expiry);
    `ts_sorted`: the timestamps of the valid snapshots only; `bad_ts`: those of the quarantined ones (counted in `skipped_invalid`:
    how many came after the snapshot used, up to the decision); `next_frames`, `next_ts_sorted`: the same for the next expiry."""
    now = _asof(frames, ts_sorted, t.value)
    if now is None:
        return None
    snap, spot, age = now
    i = int(np.searchsorted(ts_sorted, t.value, side="right")) - 1
    ts = pd.Timestamp(ts_sorted[i], tz="UTC").tz_convert(IST)
    back = lambda k: _asof(frames, ts_sorted, (t - pd.Timedelta(minutes=k * LOOKBACK)).value)
    p1, p2 = back(1), back(2)
    past = (p1[0], p1[1]) if p1 else None
    past2 = (p2[0], p2[1]) if p2 else None
    nxt = None
    if next_frames is not None and len(next_ts_sorted):
        n1 = _asof(next_frames, next_ts_sorted, t.value)
        nxt = (n1[0], n1[1]) if n1 else None
    close = pd.Timestamp(f"{expiry:%Y-%m-%d} 15:30", tz=IST)
    to_exp = (close - t).total_seconds() / 60
    row = {"underlying": underlying, "day": str(day), "m": m, "expiry": str(pd.Timestamp(expiry).date()), "ts": ts, "spot": spot,
           "to_expiry_min": to_exp, "expiry_day": bool(pd.Timestamp(expiry).date() == pd.Timestamp(day).date()), "snap_age_s": age,
           "skipped_invalid": int(((bad_ts > ts_sorted[i]) & (bad_ts <= t.value)).sum()) if bad_ts is not None else 0}
    base = snapshot_features(snap, past[0] if past else None, spot, to_exp)
    row.update(base)
    row.update(advanced_features(snap, spot, base["move"], to_exp, base, past, past2, nxt))
    return row


def _spot_path(day_rows: pd.DataFrame) -> pd.Series:
    """The tape's own spot samples of one underlying and day: ts -> spot, one per timestamp."""
    s = day_rows.drop_duplicates("ts").set_index("ts")["spot"].sort_index()
    return s[s > 0]


def labels_for(row: dict, path: pd.Series) -> dict:
    """What followed a decision, and the implied probability it should have had, for each horizon. `path`: the day's spot samples."""
    t = pd.Timestamp(row["day"] + " 09:15", tz=IST) + pd.Timedelta(minutes=row["m"])
    out = {}
    for h in HORIZONS:
        win = path[(path.index > t) & (path.index <= t + pd.Timedelta(minutes=h))]
        minutes = win.index.floor("min").nunique()
        out[f"cover{h}"] = minutes / h
        ok = minutes >= MIN_COVER * h and row["call_wall"] == row["call_wall"] and row["put_wall"] == row["put_wall"]
        out[f"contained{h}"] = float(win.max() < row["call_wall"] and win.min() > row["put_wall"]) if ok else float("nan")
        out[f"ret{h}"] = float(math.log(win.iloc[-1] / row["spot"])) if minutes >= MIN_COVER * h else float("nan")
        iv = row["iv"]
        if ok and iv == iv and iv > 0:
            s = iv / 100 * math.sqrt(h / TRADING_MIN_PER_YEAR)
            out[f"p_iv{h}"] = survival_prob(math.log(row["call_wall"] / row["spot"]), math.log(row["spot"] / row["put_wall"]), s)
        else:
            out[f"p_iv{h}"] = float("nan")
    return out


def decision_table(chains: pd.DataFrame, day, underlying: str, with_labels: bool = True) -> pd.DataFrame:
    """One underlying and one day of the archive's long chain frame -> one row per decision (features, and labels unless `with_labels`
    is False). Only real quotes (source == 'kotak') are used."""
    df = chains[(chains["underlying"] == underlying) & (chains["source"] == "kotak")]
    df = df[df["ts"].dt.tz_convert(IST).dt.date == pd.Timestamp(day).date()]
    if df.empty:
        return pd.DataFrame(columns=COLUMNS + (LABELS if with_labels else []))
    open_ = pd.Timestamp(f"{pd.Timestamp(day).date()} 09:15", tz=IST)
    path = _spot_path(df)
    snaps = {expiry: Snapshots(g) for expiry, g in df.groupby("expiry")}
    rows = []
    for m in DECISIONS:
        t = open_ + pd.Timedelta(minutes=m)
        eligible = [e for e in snaps if (pd.Timestamp(f"{pd.Timestamp(e):%Y-%m-%d} 15:30", tz=IST) - t).total_seconds() / 60 >= MIN_TO_EXPIRY]
        if not eligible:
            continue
        ordered = sorted(eligible)
        expiry = ordered[0]
        frames = snaps[expiry]
        ts_sorted, bad_ts = frames.keys[frames.valid], frames.keys[~frames.valid]
        if not len(ts_sorted):
            continue
        nf = snaps[ordered[1]] if len(ordered) > 1 else None
        row = decision_row(frames, ts_sorted, t, expiry, day, m, underlying, bad_ts, nf, nf.keys[nf.valid] if nf is not None else None)
        if row is None:
            continue
        if with_labels:
            row.update(labels_for(row, path))
        rows.append(row)
    return pd.DataFrame(rows, columns=COLUMNS + (LABELS if with_labels else []))


# ---- the pre-registered test -------------------------------------------------------------------------------------------
def fit_within(y: np.ndarray, X: np.ndarray, groups: np.ndarray) -> dict:
    """OLS of y on X with a fixed effect per group (every variable demeaned within its group), and standard errors robust to arbitrary
    correlation inside a group (CR1: sandwich with G/(G-1)). Returns the coefficients, their standard errors, the number of groups and
    the degrees of freedom G - 1 used for t tests."""
    df = pd.DataFrame(np.column_stack([y, X])).assign(g=groups)
    dm = df.groupby("g").transform(lambda s: s - s.mean()).to_numpy()
    yd, Xd = dm[:, 0], dm[:, 1:]
    total, within = np.sqrt(((X - X.mean(0)) ** 2).sum(0)), np.sqrt((Xd ** 2).sum(0))
    if (within <= 1e-8 * np.maximum(total, 1e-300)).any():                  # a regressor constant inside every group is rounding noise after demeaning
        raise np.linalg.LinAlgError("a regressor has no variation within groups")
    bread = np.linalg.inv(Xd.T @ Xd)
    beta = bread @ Xd.T @ yd
    e = yd - Xd @ beta
    meat = np.zeros((Xd.shape[1],) * 2)
    for g in np.unique(groups):
        sc = Xd[groups == g].T @ e[groups == g]
        meat += np.outer(sc, sc)
    G = len(np.unique(groups))
    cov = bread @ meat @ bread * G / (G - 1)
    return {"beta": beta, "se": np.sqrt(np.diag(cov)), "G": G, "df": G - 1}


def wall_test(table: pd.DataFrame, underlying: str, horizon: int = 60) -> dict:
    """The pre-registered regression for one index: among decisions whose implied containment probability is in `P_IV_RANGE`, does the
    excess of containment over that probability rise with the wall's strength rank, within a session, holding the probability itself fixed?
        (contained - p_iv) = session effect + beta * rank(strength) + c1 * p_iv + c2 * p_iv^2 + c3 * u + c4 * u^2 + error,   H1: beta > 0
    with u = (minutes after 09:15 - 180) / 180, the decision's time of day: the variance premium and wall strength both move through the day,
    and p_iv enters with a square because the barrier is sampled about once a minute and priced at one ATM volatility, a bias that is not linear in p_iv.
    CR1 is G/(G-1) only (no (N-1)/(N-K) factor). Returns the estimate, its robust standard error, the one-sided p-value (t, G-1 df), a two-sided 90%
    interval, the control coefficients and the counts."""
    from scipy.stats import t as student
    d = table[(table["underlying"] == underlying) & (table["day"] >= FORWARD_START)]
    c, p = d[f"contained{horizon}"], d[f"p_iv{horizon}"]
    d = d[c.notna() & p.notna() & d["strength"].notna() & (p >= P_IV_RANGE[0]) & (p <= P_IV_RANGE[1])]
    d = d.groupby("day").filter(lambda g: len(g) >= 2)                    # a session with one decision has nothing left after its fixed effect
    out = {"underlying": underlying, "horizon": horizon, "n": int(len(d)), "sessions": int(d["day"].nunique())}
    if out["sessions"] < 10 or len(d) < 30:
        return {**out, "status": "insufficient: needs at least 10 sessions and 30 decisions"}
    y = (d[f"contained{horizon}"] - d[f"p_iv{horizon}"]).to_numpy(float)
    pv, u = d[f"p_iv{horizon}"].to_numpy(float), (d["m"].to_numpy(float) - 180.0) / 180.0
    X = np.column_stack([rank_strength(d["strength"], underlying), pv, pv ** 2, u, u ** 2])
    try:
        fit = fit_within(y, X, d["day"].to_numpy())
    except np.linalg.LinAlgError:
        return {**out, "status": "insufficient: the regressors do not vary within sessions"}
    b, se, df = float(fit["beta"][0]), float(fit["se"][0]), fit["df"]
    return {**out, "status": "ok", "beta": b, "se": se, "t": b / se, "p_one_sided": float(student.sf(b / se, df)),
            "ci90": [b - student.ppf(0.95, df) * se, b + student.ppf(0.95, df) * se],
            "controls": dict(zip(("p_iv", "p_iv_sq", "time", "time_sq"), (float(x) for x in fit["beta"][1:])))}


def holm(pvals: dict[str, float], alpha: float = 0.05) -> dict[str, bool]:
    """Holm-Bonferroni step-down: which hypotheses are rejected at family-wise level alpha."""
    order = sorted(pvals, key=lambda k: pvals[k])
    out, still = {k: False for k in pvals}, True
    for i, k in enumerate(order):
        still = still and pvals[k] <= alpha / (len(order) - i)
        out[k] = bool(still)
    return out


def oi_report(table: pd.DataFrame, readout: str) -> dict:
    """The pre-registered read-out on the forward decisions of `table` (all sessions on or after FORWARD_START). `readout`: "interim" (all forward
    sessions so far, descriptive: no claim is made from it) or "final" (the FIRST 120 forward sessions in date order, a session being a day present in
    the table; the confirmatory test, Holm over the two indices as a family of two whatever each index's status: an index without a test counts as p = 1)."""
    days = sorted(table.loc[table["day"] >= FORWARD_START, "day"].unique())
    sessions = len(days)
    rep = {"spec": SPEC, "readout": readout, "forward_sessions": sessions, "confirmatory": False,
           "weekdays_without_tables": [str(d.date()) for d in pd.bdate_range(FORWARD_START, days[-1]) if str(d.date()) not in set(days)] if days else []}
    used = table
    if readout == "final":
        if sessions < 120:
            rep["note"] = f"{sessions} forward sessions: the final read-out needs 120; this is an interim look and makes no claim"
        else:
            used = table[(table["day"] < FORWARD_START) | table["day"].isin(days[:120])]
            rep["sessions_used"] = 120
    else:
        rep["note"] = "interim, descriptive: an estimate and its interval, not a finding"
    tests = {u: wall_test(used, u) for u in INDICES}
    rep["tests"] = tests
    if readout == "final" and sessions >= 120:
        rep["confirmatory"] = True
        rep["rejected"] = holm({u: (t["p_one_sided"] if t["status"] == "ok" else 1.0) for u, t in tests.items()})
        rep["retired"] = {u: bool(t["status"] == "ok" and t["ci90"][1] < 0.10) for u, t in tests.items()}
    return rep


def render_report(rep: dict) -> str:
    """The read-out as text. It states what the read-out is before any number, so an interim look is never read as a finding."""
    lines = [f"{rep['spec']}  {rep['readout']} read-out  ({rep['forward_sessions']} forward sessions)", rep.get("note", "confirmatory: Holm over the two indices at 0.05")]
    for u, t in rep["tests"].items():
        if t["status"] != "ok":
            lines.append(f"  {u}: {t['status']} ({t['sessions']} sessions, {t['n']} decisions)")
            continue
        lines.append(f"  {u}: beta {t['beta']:+.3f} (se {t['se']:.3f}, t {t['t']:+.2f}, one-sided p {t['p_one_sided']:.3f}); 90% interval "
                     f"[{t['ci90'][0]:+.3f}, {t['ci90'][1]:+.3f}]; {t['sessions']} sessions, {t['n']} decisions; implied-probability slope {t['controls']['p_iv']:+.3f}")
        if rep["confirmatory"]:
            lines.append(f"    rejected at the family level: {rep['rejected'].get(u, False)}; retired by the kill rule: {rep['retired'][u]}")
    gaps = rep.get("weekdays_without_tables", [])
    if gaps:
        lines.append(f"  {len(gaps)} weekday(s) since {FORWARD_START} have no table (exchange holidays included; any other is a missing session, never dropped for its outcome): "
                     + ", ".join(gaps[:10]) + (" ..." if len(gaps) > 10 else ""))
    return "\n".join(lines)


# ---- one session, end to end -------------------------------------------------------------------------------------------
RUN_VERSION = "ml-oi-1"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def tape_files(source: Path, day: str) -> list[Path]:
    """The archive's chain files for one session: `<day>_<part>_chains.parquet` in a folder (or the one file named)."""
    source = Path(source)
    if source.is_file():
        return [source]
    return sorted(source.glob(f"{day}_*_chains.parquet"))


def quarantine_report(chains: pd.DataFrame, day: str, underlying: str) -> dict:
    """Snapshots of this index and day (every expiry), and how many `valid_oi` quarantines (counted, never repaired)."""
    df = chains[(chains["underlying"] == underlying) & (chains["source"] == "kotak")]
    df = df[df["ts"].dt.tz_convert(IST).dt.date == pd.Timestamp(day).date()]
    n = bad = 0
    for _, g in df.groupby("expiry"):
        sn = Snapshots(g)
        n += len(sn.keys)
        bad += int((~sn.valid).sum())
    return {"snapshots": n, "quarantined": bad}


def run_day(source: Path, day: str, out_dir: Path) -> dict:
    """Features and labels for one session of the tape, both indices, written once: `oi_<day>.parquet` and `oi_<day>.json` (the code, the
    input files' sha256, the table's own sha256, the counts). The JSON is written last and is the commit marker: a parquet without one is an
    interrupted write and is replaced. A committed day is not rewritten: a second run must reproduce it (same code, same inputs, every key,
    feature and label equal in the same order) or it raises."""
    day = str(pd.Timestamp(day).date())
    files = tape_files(source, day)
    if not files:
        raise FileNotFoundError(f"no chain files for {day} in {source}")
    chains = pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)
    chains = chains[chains["source"] == "kotak"].drop_duplicates(["underlying", "expiry", "ts", "strike"])        # a row of another source must not displace a kotak row
    table = pd.concat([decision_table(chains, day, u) for u in INDICES], ignore_index=True)
    man = {"run": RUN_VERSION, "spec": SPEC, "day": day, "code_sha256": code_sha256(), "forward": day >= FORWARD_START,
           "inputs": {f.name: sha256_file(f) for f in files}, "rows": {u: int((table["underlying"] == u).sum()) for u in INDICES},
           "usable60": {u: int(table.loc[table["underlying"] == u, "contained60"].notna().sum()) for u in INDICES},
           "quarantine": {u: quarantine_report(chains, day, u) for u in INDICES}}
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    tp, mp = out_dir / f"oi_{day}.parquet", out_dir / f"oi_{day}.json"
    if mp.exists():
        if not tp.exists():
            raise RuntimeError(f"oi_{day}.json exists but oi_{day}.parquet is missing: the session's table was removed; restore it, do not rewrite it")
        old = pd.read_parquet(tp)
        prev = json.loads(mp.read_text())
        num = FEATURES + LABELS
        same = (prev["code_sha256"] == man["code_sha256"] and prev["inputs"] == man["inputs"] and len(old) == len(table)
                and old[KEY].astype(str).equals(table[KEY].astype(str))
                and np.allclose(old[num].to_numpy(float), table[num].to_numpy(float), rtol=1e-9, equal_nan=True))
        if not same:
            raise RuntimeError(f"oi_{day} exists and a rerun does not reproduce it (code or inputs changed): refusing to overwrite")
        return prev
    tmp = tp.with_name(tp.name + ".part")
    table.to_parquet(tmp, index=False)
    tmp.replace(tp)
    man["table_sha256"] = sha256_file(tp)
    mtmp = mp.with_name(mp.name + ".part")
    mtmp.write_text(json.dumps(man, indent=1))
    mtmp.replace(mp)
    return man


def pinned_code_sha256() -> str:
    """The code hash the registered spec pins (docs/prereg/oi_shadow_v1.json next to this package). A missing spec is an error, not a skipped check."""
    path = Path(__file__).resolve().parents[2] / "docs" / "prereg" / "oi_shadow_v1.json"
    if not path.exists():
        raise FileNotFoundError(f"the registered spec {path} is not beside the code: the pin cannot be checked")
    return json.loads(path.read_text())["code"]["code_sha256"]


def load_tables(folder: Path) -> pd.DataFrame:
    """Every session written by `run_day` in `folder`. Refused: the current code differing from the hash the registered spec pins; a session whose code
    is not the current code (a session graded by other definitions than the ones the spec froze would be a different experiment); a session whose
    table is not the bytes that were written (its sha256 is in the manifest, so a table edited after the fact does not load)."""
    cur, pinned = code_sha256(), pinned_code_sha256()
    if pinned != cur:
        raise RuntimeError(f"the code ({cur[:12]}) is not the code the registered spec pins ({pinned[:12]}): a changed definition is a new spec")
    parts = []
    for mp in sorted(Path(folder).glob("oi_*.json")):
        man = json.loads(mp.read_text())
        if man["code_sha256"] != cur:
            raise RuntimeError(f"{mp.name} was produced by other code ({man['code_sha256'][:12]}, now {cur[:12]}): rerun it or retire it")
        tp = mp.with_suffix(".parquet")
        if not tp.exists():
            raise RuntimeError(f"{mp.name} has no table next to it: restore {tp.name}")
        if sha256_file(tp) != man.get("table_sha256"):
            raise RuntimeError(f"{tp.name} is not the table that was written (its sha256 differs from the manifest): refusing to use it")
        parts.append(pd.read_parquet(tp))
    if not parts:
        raise FileNotFoundError(f"no sessions in {folder}")
    return pd.concat(parts, ignore_index=True)
