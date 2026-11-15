"""Power of the regime library's tests at a REALISTIC outcome noise (docs/prereg/regime_library_v1.json; research review of 15 Nov 2026, item 2: power.py's 0.2 R
noise was assumed, and a Black-Scholes sketch put the overnight R of these structures at 0.5 to over 2 R, varying with the days to expiry).

The outcomes here come from pricing, not from an assumed spread. Each session, for NIFTY and BANKNIFTY:

* the market: the session's REAL 20-session volatility (the fingerprint's vol20; BANKNIFTY's is NIFTY's x IV_BETA, the desk's config), a t(4) overnight move with that
  volatility (the two underlyings' moves correlate 0.8), and a change in implied volatility (sd 5% of its level, correlation -0.5 with the move);
* the contract calendar: the nearest expiry after the session, by the exchange's rules (approximately; no warehouse date was read): NIFTY weekly on Thursday, on Tuesday
  from 2025-09-01; BANKNIFTY weekly on Thursday, on Wednesday from 2023-09-04, monthly on the last Thursday from 2024-11-21 and the last Tuesday from 2025-09-01; an
  expiry that is not a session moves to the session before it;
* each family's width: auto2's own legs (auto2.resolved_legs) on strikes STEP apart around an at-the-money strike at the spot, priced by Black-Scholes at the session's
  implied volatility (= its realized volatility: the expected move is priced in), bought at the price plus research.warehouse_research.leg_cost and sold at it minus,
  the desk's option fee schedule (FEES, config/quantdesk.yaml) on each order; a leg under auto2.MIN_PREMIUM or a width whose round-trip fees exceed auto2.MAX_FEES_R of its
  risk is not traded; out at the next session's Black-Scholes price (the new spot, the new implied volatility, a session less), or at expiry at intrinsic value with
  exercise STT on long legs in the money; R = profit / (worst loss at expiry from auto2.payoff_bounds + round-trip fees at the entry prices), clamped -5 .. +10;
* added on top, as in power.py: a regime effect delta (each family's own smooth function of the six features, sd delta R over sessions), and optionally drift.

The choosers, the statistic and the registered PASS rule are power.py's. Also printed: the sd of D across sessions and the effect the test would detect with 80% power
at that sd (2.80 x the 20-lag standard error of mean D, averaged over worlds), the number the real report prints.

    PYTHONPATH=. python docs/prereg/sims/regime_library_v1/power_bs.py <features csv from library_features.py> [reps, default 200]
"""
from __future__ import annotations

import datetime as dt
import math
import sys
import warnings

import numpy as np
import pandas as pd
from scipy import stats
from scipy.special import ndtr

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from library_features import FEATURES, POOL_START, Z_CLIP  # noqa: I001
from power import GROUPS, H_REG, HALF_LIFE, KAPPA, LAGS, LONG_LAGS, MIN_DIFFER, SEED, nw_t, weight_matrix

from quantdesk.paper import auto2 as A2
from quantdesk.research.warehouse_research import leg_cost

FAMILIES = ["LC", "BCS", "BPS", "BWC", "CRB", "LP", "BRP", "BRC", "BWP", "PRB", "IC", "IF", "LS", "LG", "CBF", "PBF"]      # GROUPS' order: up, down, flat
UND = ("NIFTY", "BANKNIFTY")
S0 = {"NIFTY": 20000.0, "BANKNIFTY": 45000.0}
STEP = {"NIFTY": 50.0, "BANKNIFTY": 100.0}
LOT = {"NIFTY": 65, "BANKNIFTY": 30}
IV_BETA = {"NIFTY": 1.0, "BANKNIFTY": 1.22}
FEES = {"brokerage": 20.0, "brokerage_cap": 0.0003, "stt_sell": 0.0015, "exchange": 0.0003503, "stamp_buy": 0.00003, "gst": 0.18, "sebi_per_crore": 10.0,
        "exercise_stt": 0.0015}
IV_VOL, IV_RHO = 0.05, -0.5


def order_fee(px: np.ndarray, units: int, sell: bool) -> np.ndarray:
    """Rupees per unit for one order of `units` at `px` (the desk's option schedule)."""
    turn = px * units
    brk = np.minimum(FEES["brokerage"], FEES["brokerage_cap"] * turn)
    exch = FEES["exchange"] * turn
    sebi = FEES["sebi_per_crore"] * turn / 1e7
    tax = FEES["stt_sell"] * turn if sell else FEES["stamp_buy"] * turn
    return (brk + exch + sebi + tax + FEES["gst"] * (brk + exch + sebi)) / units


def bs(S, K, T, sig, right):
    S, T, sig = np.asarray(S, float), np.asarray(T, float), np.asarray(sig, float)
    intrinsic = np.maximum(S - K, 0.0) if right == "CE" else np.maximum(K - S, 0.0)
    Tp = np.maximum(T, 1e-12)
    sq = sig * np.sqrt(Tp)
    d1 = (np.log(S / K) + 0.5 * sig * sig * Tp) / sq
    d2 = d1 - sq
    px = S * ndtr(d1) - K * ndtr(d2) if right == "CE" else K * ndtr(-d2) - S * ndtr(-d1)
    return np.where(T > 0, px, intrinsic)


def _last_weekday(y: int, m: int, wd: int) -> dt.date:
    d = (dt.date(y + (m == 12), m % 12 + 1, 1) - dt.timedelta(days=1))
    while d.weekday() != wd:
        d -= dt.timedelta(days=1)
    return d


def nominal_expiries(u: str, start: dt.date, end: dt.date) -> list[dt.date]:
    out, d = [], start
    while d <= end:
        if u == "NIFTY":
            wd = 3 if d < dt.date(2025, 9, 1) else 1
            if d.weekday() == wd:
                out.append(d)
        else:
            if d < dt.date(2024, 11, 21):
                wd = 3 if d < dt.date(2023, 9, 4) else 2
                if d.weekday() == wd:
                    out.append(d)
            elif d.day == 1:
                wd = 3 if d < dt.date(2025, 9, 1) else 1
                out.append(_last_weekday(d.year, d.month, wd))
        d += dt.timedelta(days=1)
    return sorted({x for x in out if x >= start})


def calendar(dates: pd.DatetimeIndex, u: str) -> np.ndarray:
    """Trading days from each session to its near expiry (the first expiry after it), on the session calendar extended by weekdays past its end."""
    days = [d.date() for d in dates]
    ext = days + [d.date() for d in pd.bdate_range(dates[-1] + pd.Timedelta(days=1), periods=60)]
    pos = {d: i for i, d in enumerate(ext)}
    exp_idx = []
    for e in nominal_expiries(u, ext[0], ext[-1]):
        i = np.searchsorted(np.array(ext, dtype="datetime64[D]"), np.datetime64(e), side="right") - 1      # a holiday moves it to the session before
        if i >= 0:
            exp_idx.append(i)
    exp_idx = np.array(sorted(set(exp_idx)))
    dte = np.empty(len(days), int)
    for i, d in enumerate(days):
        j = exp_idx[np.searchsorted(exp_idx, pos[d], side="right")]
        dte[i] = j - pos[d]
    return dte


class World:
    """The deterministic part (entry prices, risk, what is tradable) per session, underlying, family and width; the random part (the move) per world."""

    def __init__(self, fe: pd.DataFrame):
        self.n = len(fe)
        vol = np.clip(fe["vol20"].astype(float).ffill().bfill().values, 0.05, None)
        self.sig = {u: vol * IV_BETA[u] for u in UND}
        self.dte = {u: calendar(fe.index, u) for u in UND}
        self.members = {}                                                        # (u, family) -> list of width dicts
        for u in UND:
            T0 = self.dte[u] / 252.0
            for f in FAMILIES:
                ws = []
                for w in A2.STRUCTURES[f][2]:
                    legs = A2.resolved_legs(f, w)
                    K = [S0[u] + STEP[u] * k for _, _, k in legs]
                    mid = [bs(S0[u], k, T0, self.sig[u], r) for (_, r, _), k in zip(legs, K)]
                    fill = [m + np.sign(q) * leg_cost(m) for (q, _, _), m in zip(legs, mid)]
                    units = [abs(q) * LOT[u] for q, _, _ in legs]
                    fee_in = sum(order_fee(fl, un, q < 0) * abs(q) for (q, _, _), fl, un in zip(legs, fill, units))
                    fee_rt = fee_in + sum(order_fee(fl, un, q > 0) * abs(q) for (q, _, _), fl, un in zip(legs, fill, units))
                    worst = np.array([A2.payoff_bounds([(q, r, k, fl[t]) for (q, r, _), k, fl in zip(legs, K, fill)])[0] for t in range(self.n)])
                    risk = -worst + fee_rt
                    ok = np.all([m >= A2.MIN_PREMIUM for m in mid], axis=0) & (worst < 0) & (fee_rt <= A2.MAX_FEES_R * risk)
                    ws.append({"legs": legs, "K": K, "fill": fill, "fee_in": fee_in, "risk": risk, "ok": ok, "units": units})
                self.members[(u, f)] = ws

    def outcomes(self, rng) -> np.ndarray:
        """y[t, u, f] in R (NaN where no width of the family could be traded)."""
        n = self.n
        common = stats.t.rvs(4, size=n, random_state=rng) / math.sqrt(2)
        y = np.full((n, len(UND), len(FAMILIES)), np.nan)
        for ui, u in enumerate(UND):
            own = stats.t.rvs(4, size=n, random_state=rng) / math.sqrt(2)
            z = math.sqrt(0.8) * common + math.sqrt(0.2) * own
            sd = self.sig[u] / math.sqrt(252)
            S1 = S0[u] * np.exp(sd * z - 0.5 * sd * sd)
            sig1 = self.sig[u] * np.exp(IV_VOL * (IV_RHO * z + math.sqrt(1 - IV_RHO ** 2) * rng.normal(size=n)))
            T1 = (self.dte[u] - 1) / 252.0
            settle = self.dte[u] == 1
            for fi, f in enumerate(FAMILIES):
                rs = []
                for m in self.members[(u, f)]:
                    pnl = -m["fee_in"]
                    for (q, r, _), k, fl, un in zip(m["legs"], m["K"], m["fill"], m["units"]):
                        val = bs(S1, k, T1, sig1, r)
                        out_px = np.where(settle, val, val - np.sign(q) * leg_cost(val))
                        out_fee = np.where(settle, (q > 0) * FEES["exercise_stt"] * val, order_fee(np.maximum(out_px, 0.0), un, q > 0))
                        pnl = pnl + q * (out_px - fl) - abs(q) * out_fee
                    rs.append(np.where(m["ok"], np.clip(pnl / m["risk"], -5, 10), np.nan))
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", RuntimeWarning)                     # a session where no width could be traded: NaN, as intended
                    y[:, ui, fi] = np.nanmean(np.stack(rs), axis=0) if rs else np.nan
        return y


def effect(rng, X: np.ndarray, delta: float, drift: float) -> np.ndarray:
    """delta x each family's own smooth function of the features (sd 1 over sessions), plus drift; [t, f]."""
    n, nf = len(X), len(FAMILIES)
    med = np.nanmedian(X, 0)
    z = np.nan_to_num(np.clip((X - med) / (np.nanmedian(np.abs(X - med), 0) * 1.4826 + 1e-12), -Z_CLIP, Z_CLIP))
    g = np.tanh(z @ rng.normal(size=(nf, X.shape[1])).T / math.sqrt(X.shape[1]))
    g = (g - g.mean(0)) / (g.std(0) + 1e-12)
    return delta * g + np.cumsum(rng.normal(0, drift / math.sqrt(n), (n, nf)), axis=0)


def choose(y: np.ndarray, lo: int, W: np.ndarray, tests: np.ndarray) -> dict:
    """power.run's choosers and statistic, with families that could not be traded left out (never chosen; no outcome added)."""
    n = y.shape[0]
    Yp = y.reshape(n, -1)
    has = np.isfinite(Yp) & (np.arange(n)[:, None] >= lo)
    Y0 = np.where(has, Yp, 0.0)
    cs, cnt = np.cumsum(Y0, 0), np.cumsum(has, 0)
    with np.errstate(all="ignore"):
        flat = np.stack([cs[i - 1] / cnt[i - 1] for i in tests])
        sw = W @ has
        km = (W @ Y0) / sw
        neff = sw ** 2 / ((W ** 2) @ has)
        sim = np.where(sw > 0, (neff * km + KAPPA * flat) / (neff + KAPPA), flat)
    lam = 0.5 ** (1 / HALF_LIFE)
    ew = np.empty_like(flat)
    acc, wt, k = np.zeros(Yp.shape[1]), np.zeros(Yp.shape[1]), 0
    for i in range(lo, n):
        if k < len(tests) and tests[k] == i:
            with np.errstate(all="ignore"):
                ew[k] = acc / wt
            k += 1
        acc, wt = acc * lam + Y0[i], wt * lam + has[i]                         # decay per session; a session without an outcome adds nothing
    real = Yp[tests]
    tradable = np.isfinite(real)
    cells, off = [], 0
    for u in range(len(UND)):
        off = 0
        for m in GROUPS.values():
            cells.append(np.arange(u * 16 + off, u * 16 + off + m))
            off += m
    out = {}
    for name, est in (("S", sim), ("A", ew)):
        dsum, dn, differ, total = np.zeros(len(tests)), np.zeros(len(tests)), 0, 0
        for c in cells:
            ok = tradable[:, c] & np.isfinite(flat[:, c]) & np.isfinite(est[:, c])
            usable = ok.sum(1) >= 2
            e_ = np.where(ok, est[:, c], -np.inf)
            f_ = np.where(ok, flat[:, c], -np.inf)
            pe, pf = e_.argmax(1), f_.argmax(1)                                  # ties: the registered order (argmax takes the first)
            rr = real[:, c]
            r_ = np.arange(len(tests))
            d = np.where(usable, rr[r_, pe] - rr[r_, pf], 0.0)
            dsum += d
            dn += usable
            differ += ((pe != pf) & usable).sum()
            total += usable.sum()
        keep = dn > 0
        dd = dsum[keep] / dn[keep]
        se20 = abs(dd.mean() / nw_t(dd, LAGS)) if dd.mean() != 0 else float("nan")
        out[name] = (dd.mean(), nw_t(dd, LAGS), differ / max(total, 1), nw_t(dd, LONG_LAGS), dd.std(), se20)
    return out


def main():
    fe = pd.read_csv(sys.argv[1], index_col=0, parse_dates=True)
    reps = int(sys.argv[2]) if len(sys.argv) > 2 else 200
    X = fe[list(FEATURES)].astype(float).values
    lo = int(np.searchsorted(fe.index.values, POOL_START.to_datetime64()))
    crit = stats.norm.ppf(0.975)
    world = World(fe)
    W, tests = weight_matrix(X, lo, H_REG)
    rng0 = np.random.default_rng(SEED)
    y0 = world.outcomes(rng0)
    t = np.array(tests)
    print(f"h {H_REG}: {len(tests)} test sessions from {fe.index[tests[0]].date()}; Black-Scholes outcomes")
    print("sd of a family's overnight R over the test sessions (one world), NIFTY | BANKNIFTY:")
    print("  " + "  ".join(f"{f} {np.nanstd(y0[t, 0, i]):.2f}|{np.nanstd(y0[t, 1, i]):.2f}" for i, f in enumerate(FAMILIES)))
    print("share of test sessions each family could be traded, NIFTY | BANKNIFTY:")
    print("  " + "  ".join(f"{f} {np.isfinite(y0[t, 0, i]).mean():.2f}|{np.isfinite(y0[t, 1, i]).mean():.2f}" for i, f in enumerate(FAMILIES)))
    print("near-expiry trading days over the test sessions, NIFTY | BANKNIFTY: median "
          f"{np.median(world.dte['NIFTY'][t]):.0f} | {np.median(world.dte['BANKNIFTY'][t]):.0f}, expiry eves {np.mean(world.dte['NIFTY'][t] == 1):.2f} | "
          f"{np.mean(world.dte['BANKNIFTY'][t] == 1):.2f}")
    worlds = [("null: pricing only", 0.0, 0.0), ("null: drift only", 0.0, 0.15), ("regime 0.05", 0.05, 0.0), ("regime 0.10", 0.10, 0.0),
              ("regime 0.20", 0.20, 0.0), ("regime 0.30", 0.30, 0.0), ("regime 0.20 + drift", 0.20, 0.15)]
    for label, delta, drift in worlds:
        rng = np.random.default_rng(SEED)
        res = []
        for _ in range(reps):
            y = world.outcomes(rng) + effect(rng, X, delta, drift)[:, None, :]
            res.append(choose(np.clip(y, -5, 10), lo, W, tests))
        for k in ("S", "A"):
            m = np.array([r[k][0] for r in res]); tt = np.array([r[k][1] for r in res]); dif = np.array([r[k][2] for r in res])
            t60 = np.array([r[k][3] for r in res]); sdd = np.array([r[k][4] for r in res]); se = np.array([r[k][5] for r in res])
            reg = (tt >= crit) & (t60 >= crit) & (dif >= MIN_DIFFER)
            print(f"  {label:22s} {k}: mean D {m.mean():+.4f} R (sd over worlds {m.std():.4f}); PASS (registered rule) {reg.mean():.3f}; picks differ {dif.mean():.2f}; "
                  f"sd of D {np.nanmean(sdd):.3f} R, detectable mean D at 80% power {2.80 * np.nanmean(se):.4f} R")


if __name__ == "__main__":
    main()
