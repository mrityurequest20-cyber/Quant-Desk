"""One scorecard for any strategy, from its per-trade P&L: the statistical layers of the desk's validation framework.

Layer 1 — edge:        N, win rate, average win / loss, expectancy E = W·AvgWin − L·|AvgLoss|, profit factor,
                       SQN = √N · mean / sd.
Layer 2 — risk & tail: Sharpe and Sortino (downside semi-deviation about 0), annualised by trades per year; Calmar;
                       Omega at a zero threshold (on per-trade P&L this equals the profit factor); skew and excess
                       kurtosis; historical and Cornish-Fisher VaR and CVaR (expected shortfall) per trade at 95% and
                       99%; maximum drawdown, the longest time under water and the time to recover from the deepest
                       drawdown (in trades); the Ulcer Index.
Layer 3 — friction:    the slippage break-even: the extra cost per trade (₹, and bps of the notional traded) that takes
                       the mean to zero.
Layer 5 — robustness:  PSR against 0; DSR against the best of `n_trials` zero-skill variants; OOS efficiency =
                       Sharpe of the newest third / Sharpe of the older two thirds.
Ruin:                  a bootstrap Monte Carlo of the trade sequence from a given capital: P(losing half), P(losing it
                       all) over the horizon.

Gates (the framework's thresholds): E > 0, profit factor > 1.5, N ≥ 300, OOS efficiency ≥ 0.5, DSR ≥ 0.95.
Flags: negative skew, excess kurtosis > 3, a 99% CVaR deeper than a quarter of the capital."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from ..risk.metrics import cornish_fisher_var, deflated_sharpe, probabilistic_sharpe

GATES = {"expectancy": 0.0, "profit_factor": 1.5, "n": 300, "oos_efficiency": 0.5, "dsr": 0.95}


def _sr(x: np.ndarray) -> float:
    return float(x.mean() / x.std(ddof=1)) if len(x) > 2 and x.std(ddof=1) > 0 else float("nan")


def _drawdowns(pnl: np.ndarray, capital: float | None):
    eq = (capital or 0.0) + np.concatenate([[0.0], np.cumsum(pnl)])
    peak = np.maximum.accumulate(eq)
    dd_rs = eq - peak
    under, longest, cur = dd_rs < 0, 0, 0
    for u in under:
        cur = cur + 1 if u else 0
        longest = max(longest, cur)
    trough = int(np.argmin(dd_rs))
    rec = next((i - trough for i in range(trough, len(eq)) if eq[i] >= peak[trough]), None) if dd_rs[trough] < 0 else 0
    dd_pct = dd_rs / peak if capital else None
    return eq, float(dd_rs.min()), (float(dd_pct.min()) if dd_pct is not None else float("nan")), longest, rec, dd_pct


def ruin(pnl: np.ndarray, capital: float, horizon: int, n_sims: int = 4000, seed: int = 0) -> dict:
    """Bootstrap the trade sequence `horizon` trades ahead from `capital`: the chance the account ever falls to half,
    or to zero (ruin), and the spread of where it ends."""
    rng = np.random.default_rng(seed)
    draws = rng.choice(pnl, size=(n_sims, horizon), replace=True)
    paths = capital + np.cumsum(draws, axis=1)
    low = paths.min(axis=1)
    return {"p_ruin": float((low <= 0).mean()), "p_half": float((low <= capital / 2).mean()),
            "final_p5": float(np.percentile(paths[:, -1], 5)), "final_p50": float(np.percentile(paths[:, -1], 50)),
            "horizon": horizon}


def scorecard(pnl, capital: float | None = None, notional: float | None = None, per_year: float | None = None,
              n_trials: int = 1, sr_std_trials: float | None = None, ruin_horizon: int | None = None,
              n_sims: int = 4000, seed: int = 0) -> dict:
    """`pnl`: per-trade P&L in ₹ (a Series in time order, or an array). `capital`: the account it is run on (for
    percentages, Calmar, Ulcer and ruin). `notional`: ₹ traded per trade (for the break-even in bps). `per_year`:
    trades a year (inferred from a DatetimeIndex when not given). `n_trials`: variants tried (for the DSR)."""
    s = pd.Series(pnl).dropna()
    x = s.to_numpy(dtype=float)
    n = len(x)
    out: dict = {"n": n}
    if n < 10:
        out["note"] = "fewer than 10 trades: nothing to measure"
        return out
    if per_year is None and isinstance(s.index, pd.DatetimeIndex) and len(s.index) > 1:
        span = (s.index[-1] - s.index[0]).days / 365.25
        per_year = n / span if span > 0.05 else None
    ann = math.sqrt(per_year) if per_year else 1.0                 # no time base: Sharpe and Sortino per trade
    wins, losses = x[x > 0], x[x <= 0]
    W, L = len(wins) / n, len(losses) / n
    aw, al = (wins.mean() if len(wins) else 0.0), (abs(losses.mean()) if len(losses) else 0.0)
    gross_l = abs(losses.sum())
    sd = x.std(ddof=1)
    sr = _sr(x)
    downside = math.sqrt(np.mean(np.minimum(x, 0) ** 2))
    out.update({
        # layer 1
        "win_rate": W, "avg_win": float(aw), "avg_loss": float(-al), "expectancy": float(W * aw - L * al),
        "profit_factor": float(wins.sum() / gross_l) if gross_l > 0 else float("inf"),
        "sqn": float(math.sqrt(n) * x.mean() / sd) if sd > 0 else float("nan"),
        # layer 2
        "per_year": per_year, "ratio_basis": "annualised" if per_year else "per trade", "sharpe": sr * ann, "sortino": float(x.mean() / downside * ann) if downside > 0 else float("nan"),
        "omega": float(wins.sum() / gross_l) if gross_l > 0 else float("inf"),
        "skew": float(s.skew()), "excess_kurtosis": float(s.kurt()),
        "var95": float(-np.percentile(x, 5)), "var99": float(-np.percentile(x, 1)),
        "cvar95": float(-x[x <= np.percentile(x, 5)].mean()), "cvar99": float(-x[x <= np.percentile(x, 1)].mean()),
        "cf_var95": cornish_fisher_var(s, 0.05), "cf_var99": cornish_fisher_var(s, 0.01),
        "worst": float(x.min()), "best": float(x.max()), "total": float(x.sum()),
    })
    eq, mdd_rs, mdd_pct, under, rec, dd_pct = _drawdowns(x, capital)
    out.update({"max_dd": mdd_rs, "max_dd_pct": mdd_pct, "longest_underwater_trades": under, "recovery_trades": rec,
                "ulcer_index": float(math.sqrt(np.mean((dd_pct * 100) ** 2))) if dd_pct is not None else float("nan")})
    if capital and per_year:
        yearly = x.mean() * per_year / capital
        out["annual_return_pct"] = float(yearly)
        out["calmar"] = float(yearly / abs(mdd_pct)) if mdd_pct < 0 else float("inf")
    # layer 3: how much more friction per trade the edge survives
    out["breakeven_cost_rs"] = float(x.mean())
    out["breakeven_cost_bps"] = float(x.mean() / notional * 1e4) if notional else float("nan")
    # layer 5
    cut = int(n * 2 / 3)
    sr_is, sr_oos = _sr(x[:cut]), _sr(x[cut:])
    out["sharpe_is"], out["sharpe_oos"] = sr_is * ann, sr_oos * ann
    out["oos_efficiency"] = float(sr_oos / sr_is) if sr_is == sr_is and sr_is > 0 else float("nan")
    out["psr"] = probabilistic_sharpe(s, 0.0)
    out["dsr"] = deflated_sharpe(s, n_trials, sr_std_trials if sr_std_trials is not None else 1 / math.sqrt(n))
    out["n_trials"] = n_trials
    if capital:
        out["ruin"] = ruin(x, capital, ruin_horizon or n, n_sims, seed)
    # the framework's gates and flags
    gates = {"expectancy > 0": out["expectancy"] > GATES["expectancy"],
             "profit factor > 1.5": out["profit_factor"] > GATES["profit_factor"],
             "N ≥ 300": n >= GATES["n"],
             "OOS efficiency ≥ 0.5": out["oos_efficiency"] == out["oos_efficiency"] and out["oos_efficiency"] >= GATES["oos_efficiency"],
             "DSR ≥ 0.95": out["dsr"] == out["dsr"] and out["dsr"] >= GATES["dsr"]}
    flags = []
    if out["skew"] < -0.5:
        flags.append(f"negative skew {out['skew']:.2f}: small frequent gains, rare large losses")
    if out["excess_kurtosis"] > 3:
        flags.append(f"fat tails: excess kurtosis {out['excess_kurtosis']:.1f}")
    if capital and out["cvar99"] > 0.25 * capital:
        flags.append(f"99% CVaR ₹{out['cvar99']:,.0f} is {out['cvar99'] / capital:.0%} of capital")
    if capital and out.get("ruin", {}).get("p_ruin", 0) > 0.01:
        flags.append(f"P(ruin) {out['ruin']['p_ruin']:.1%} over {out['ruin']['horizon']} trades")
    out["gates"], out["flags"] = gates, flags
    failed = [k for k, ok in gates.items() if not ok]
    out["verdict"] = "PASSES every gate" if not failed else "fails: " + ", ".join(failed)
    return out


def _f(v, fmt="{:,.2f}"):
    if v is None or (isinstance(v, float) and v != v):
        return "—"
    if isinstance(v, float) and math.isinf(v):
        return "∞"
    return fmt.format(v)


def to_markdown(sc: dict, title: str, unit: str = "₹") -> str:
    if sc.get("n", 0) < 10:
        return f"**{title}**: {sc.get('note', 'too few trades')}\n"
    r = sc.get("ruin", {})
    L = [f"**{title}** — {sc['verdict']}", "",
         "| layer | metric | value |", "|---|---|---:|",
         f"| 1 edge | N · win rate | {sc['n']:,} · {sc['win_rate']:.0%} |",
         f"| 1 edge | expectancy (W·AvgWin − L·AvgLoss) | {unit}{_f(sc['expectancy'], '{:+,.0f}')} |",
         f"| 1 edge | avg win / avg loss | {unit}{_f(sc['avg_win'], '{:,.0f}')} / {unit}{_f(sc['avg_loss'], '{:,.0f}')} |",
         f"| 1 edge | profit factor · SQN | {_f(sc['profit_factor'])} · {_f(sc['sqn'])} |",
         f"| 2 risk | Sharpe · Sortino ({sc['ratio_basis']}) · Calmar | {_f(sc['sharpe'])} · {_f(sc['sortino'])} · {_f(sc.get('calmar'))} |",
         f"| 2 risk | Omega(0) | {_f(sc['omega'])} |",
         f"| 2 tail | skew · excess kurtosis | {_f(sc['skew'])} · {_f(sc['excess_kurtosis'])} |",
         f"| 2 tail | VaR 95 / 99 per trade | {unit}{_f(sc['var95'], '{:,.0f}')} / {unit}{_f(sc['var99'], '{:,.0f}')} |",
         f"| 2 tail | CVaR 95 / 99 per trade | {unit}{_f(sc['cvar95'], '{:,.0f}')} / {unit}{_f(sc['cvar99'], '{:,.0f}')} |",
         f"| 2 tail | Cornish-Fisher VaR 95 / 99 | {unit}{_f(sc['cf_var95'], '{:,.0f}')} / {unit}{_f(sc['cf_var99'], '{:,.0f}')} |",
         f"| 2 drawdown | max DD | {unit}{_f(sc['max_dd'], '{:,.0f}')} ({_f(sc['max_dd_pct'], '{:.1%}')}) |",
         f"| 2 drawdown | longest under water · recovery from max DD | {sc['longest_underwater_trades']} · "
         f"{sc['recovery_trades'] if sc['recovery_trades'] is not None else 'not recovered'} trades |",
         f"| 2 drawdown | Ulcer Index | {_f(sc['ulcer_index'])} |",
         f"| 3 friction | slippage break-even per trade | {unit}{_f(sc['breakeven_cost_rs'], '{:+,.0f}')} "
         f"({_f(sc['breakeven_cost_bps'], '{:+.1f}')} bps of notional) |",
         f"| 5 robustness | Sharpe IS → OOS · OOS efficiency | {_f(sc['sharpe_is'])} → {_f(sc['sharpe_oos'])} · {_f(sc['oos_efficiency'])} |",
         f"| 5 robustness | PSR · DSR ({sc['n_trials']} trials) | {_f(sc['psr'], '{:.3f}')} · {_f(sc['dsr'], '{:.3f}')} |"]
    if r:
        L.append(f"| ruin | P(−50%) · P(ruin) over {r['horizon']} trades | {r['p_half']:.1%} · {r['p_ruin']:.1%} |")
    if sc["flags"]:
        L += ["", "Flags: " + "; ".join(sc["flags"]) + "."]
    return "\n".join(L) + "\n"
