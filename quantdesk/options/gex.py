"""Dealer gamma exposure (GEX) and the forward implied by the chain — context for the read, from the chain the desk
already fetches (no extra data).

GEX here is the naive convention: dealers assumed long the calls and short the puts the public holds, so
GEX = Σ Γ·OI·S²·1% over calls − the same over puts, in ₹ per 1% move of the index. Positive: dealer hedging leans
against moves (volatility tends to be damped); negative: it chases them (moves can accelerate). The flip is the spot
where the sum changes sign. In India much option buying is retail and much selling is proprietary, so the sign
convention is an assumption, not a fact: this is context, never a vote.

The synthetic forward F = K + e^{rT}(C − P) at the money gives the carry the options market is pricing (basis to
spot, annualised), without a futures quote."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from .pricing import greeks


def _gamma(S, K, T, r, q, iv):
    return np.asarray(greeks(S, np.asarray(K, float), T, r, q, np.asarray(iv, float), "CE")["gamma"], dtype=float)


def gex_at(S: float, strikes, ce_oi, pe_oi, ce_iv, pe_iv, T: float, r: float, q: float, units: float = 1.0) -> float:
    """Net GEX in ₹ per 1% move at spot S. `units`: shares per OI unit (the lot when OI counts contracts)."""
    K = np.asarray(strikes, float)
    g_c = np.nan_to_num(_gamma(S, K, T, r, q, np.where(np.asarray(ce_iv) > 0, ce_iv, np.nan)))
    g_p = np.nan_to_num(_gamma(S, K, T, r, q, np.where(np.asarray(pe_iv) > 0, pe_iv, np.nan)))
    per = S * S * 0.01 * units
    return float((g_c * np.nan_to_num(ce_oi) - g_p * np.nan_to_num(pe_oi)).sum() * per)


def gamma_exposure(df: pd.DataFrame, S: float, T: float, r: float, q: float, units: float = 1.0, span: float = 0.05,
                   steps: int = 41) -> dict:
    """GEX now, its sign, and the flip level (nearest zero crossing within ±`span` of spot), from a chain frame with
    ce_/pe_ oi and iv (iv in %)."""
    if df is None or df.empty or not S or T <= 0:
        return {}
    K = df.index.to_numpy(float)
    args = (K, df["ce_oi"].to_numpy(float), df["pe_oi"].to_numpy(float),
            df["ce_iv"].to_numpy(float) / 100, df["pe_iv"].to_numpy(float) / 100, T, r, q, units)
    now = gex_at(S, *args)
    grid = np.linspace(S * (1 - span), S * (1 + span), steps)
    vals = np.array([gex_at(x, *args) for x in grid])
    flip = float("nan")
    cross = np.where(np.sign(vals[:-1]) != np.sign(vals[1:]))[0]
    if len(cross):
        i = cross[int(np.argmin(np.abs(grid[cross] - S)))]
        flip = float(grid[i] - vals[i] * (grid[i + 1] - grid[i]) / (vals[i + 1] - vals[i]))
    return {"gex_cr_per_1pct": now / 1e7, "gex_state": "positive (dealers damp moves)" if now > 0 else
            "negative (dealers chase moves)", "gamma_flip": flip}


def implied_forward(df: pd.DataFrame, S: float, T: float, r: float) -> dict:
    """Synthetic forward from the at-the-money call and put mids, its basis to spot and the annualised carry."""
    if df is None or df.empty or not S or T <= 0:
        return {}
    K = df.index.to_numpy(float)
    i = int(np.argmin(np.abs(K - S)))
    row = df.iloc[i]

    def m(side):
        b, a, l = row.get(f"{side}_bid"), row.get(f"{side}_ask"), row.get(f"{side}_ltp")
        return (a + b) / 2 if pd.notna(b) and pd.notna(a) and a >= b > 0 else l
    c, p = m("ce"), m("pe")
    if not (pd.notna(c) and pd.notna(p) and c > 0 and p > 0):
        return {}
    F = float(K[i] + math.exp(r * T) * (c - p))
    return {"forward": F, "basis": F - S, "carry_ann": math.log(F / S) / T}
