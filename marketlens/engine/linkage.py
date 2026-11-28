"""How much of a stock's movement is the market's, its sector's, or its own.

Over a rolling 63 sessions of daily log returns: beta and correlation to NIFTY and to the stock's sector index, and
the R-squared of a two-factor regression on both. One minus that R-squared is the stock's own share of its variance:
what an option on it prices that an index option cannot (results, deals, news). A high own-share stock's options
move with its own events; a low one is close to a leveraged index bet.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

SECTOR_INDEX = {"Banks": "Nifty Bank", "IT": "Nifty IT", "Pharma": "Nifty Pharma", "Autos": "Nifty Auto", "FMCG": "Nifty FMCG",
                "NBFC": "Nifty Financial Services Ex-Bank", "Capital goods": "Nifty Capital Goods",
                "Capital markets": "Nifty Capital Markets", "Energy & conglomerate": "Nifty Energy",
                "Electronics manufacturing": "Nifty Consumer Durables", "Fintech": "Nifty India Digital",
                "Telecom": "Nifty India Digital"}
WIN = 63


def rolling(stock: pd.Series, nifty: pd.Series, sector: pd.Series | None, win: int = WIN) -> pd.DataFrame:
    """Daily: beta_n, corr_n, beta_s, corr_s, r2 (two-factor, or NIFTY alone without a sector) and own (1 - r2)."""
    df = pd.DataFrame({"s": np.log(stock).diff(), "n": np.log(nifty).diff()})
    if sector is not None:
        df["k"] = np.log(sector).diff()
    df = df.dropna()
    out = pd.DataFrame(index=df.index, dtype=float)
    cov = df["s"].rolling(win).cov(df["n"])
    out["beta_n"] = cov / df["n"].rolling(win).var()
    out["corr_n"] = df["s"].rolling(win).corr(df["n"])
    if "k" in df:
        out["beta_s"] = df["s"].rolling(win).cov(df["k"]) / df["k"].rolling(win).var()
        out["corr_s"] = df["s"].rolling(win).corr(df["k"])
        # two-factor R^2 from the correlations: R^2 = (r_sn^2 + r_sk^2 - 2 r_sn r_sk r_nk) / (1 - r_nk^2)
        r_nk = df["n"].rolling(win).corr(df["k"])
        a, b = out["corr_n"], out["corr_s"]
        den = (1 - r_nk ** 2)
        r2 = (a ** 2 + b ** 2 - 2 * a * b * r_nk) / den.where(den > 1e-6)
        out["r2"] = r2.where(den > 1e-6, a ** 2).clip(0, 1)
    else:
        out["r2"] = (out["corr_n"] ** 2).clip(0, 1)
    out["own"] = 1 - out["r2"]
    return out.dropna(subset=["beta_n"])
