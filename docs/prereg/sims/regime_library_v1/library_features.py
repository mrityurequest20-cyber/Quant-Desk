"""The regime library's features at every past session, and how many past sessions the similarity kernel leans on (docs/prereg/regime_library_v1.json).

Reads ONLY closes up to each session (quantdesk.premarket.fingerprint.compute, asof=d): no outcome, no option price, nothing after d. It fixes the kernel's bandwidth
from the features alone, before any replay outcome exists.

    PYTHONPATH=. python docs/prereg/sims/regime_library_v1/library_features.py <dir of daily-history *daily_YYYY.parquet shards | a features csv it wrote> [out.csv]
"""
from __future__ import annotations

import glob
import sys

import numpy as np
import pandas as pd

from quantdesk.premarket import fingerprint as F

FEATURES = ("vol_pct", "trend_t", "vol_change", "vr5", "drawdown", "tail_days")
EMBARGO = 60
Z_CLIP = 4.0
H_GRID = (0.25, 0.35, 0.5, 0.7, 1.0)
POOL_START = pd.Timestamp("2019-01-01")     # the first month of real option closes in the warehouse: only these sessions have replay outcomes
MIN_POOL = 250


def nifty(dirpath: str) -> pd.Series:
    df = pd.concat([pd.read_parquet(p) for p in sorted(glob.glob(f"{dirpath}/*daily_*.parquet"))])
    s = df[df.symbol == "NIFTY"].drop_duplicates("date", keep="last").set_index("date")["close"].astype(float).sort_index()
    return s


def features(close: pd.Series) -> pd.DataFrame:
    rows = {}
    for d in close.index[F.MIN_OBS:]:
        fp = F.compute({"NIFTY": close}, asof=d)
        if fp and fp.get("key"):
            rows[d] = {**{k: fp["features"].get(k) for k in FEATURES}, "vol20": fp["features"].get("vol20"), "key": fp["key"]}
    return pd.DataFrame.from_dict(rows, orient="index")


def robust_z(pool: np.ndarray, x: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    med = np.nanmedian(pool, axis=0)
    mad = np.nanmedian(np.abs(pool - med), axis=0) * 1.4826
    mad = np.where(mad > 0, mad, np.nanstd(pool, axis=0) + 1e-12)
    return np.clip((pool - med) / mad, -Z_CLIP, Z_CLIP), np.clip((x - med) / mad, -Z_CLIP, Z_CLIP)


def weights(X: np.ndarray, i: int, h: float, lo: int = 0) -> np.ndarray | None:
    """The kernel weights of the pool sessions [lo, i - EMBARGO), for session i; the robust scale from that same pool (the past only)."""
    j = i - EMBARGO
    if j - lo < MIN_POOL:
        return None
    pz, xz = robust_z(X[lo:j], X[i])
    d2 = np.nanmean((pz - xz) ** 2, axis=1)
    return np.exp(-d2 / (2 * h * h))


def main():
    src = sys.argv[1]
    fe = pd.read_csv(src, index_col=0, parse_dates=True) if src.endswith(".csv") else features(nifty(src))
    if len(sys.argv) > 2:
        fe.to_csv(sys.argv[2])
    X = fe[list(FEATURES)].astype(float).values
    print(f"sessions with a fingerprint: {len(fe)} ({fe.index[0].date()} to {fe.index[-1].date()})")
    print("regime keys:", fe["key"].value_counts().to_dict())
    print("feature correlations:\n", fe[list(FEATURES)].astype(float).corr().round(2))
    lo = int(np.searchsorted(fe.index.values, POOL_START.to_datetime64()))
    for label, start in (("pool: every fingerprinted session", 0), (f"pool: sessions from {POOL_START.date()} (those with replay outcomes)", lo)):
        print(label)
        for h in H_GRID:
            ne, first = [], None
            for i in range(len(X)):
                w = weights(X, i, h, start)
                if w is not None:
                    first = first or fe.index[i].date()
                    ne.append(w.sum() ** 2 / (w ** 2).sum())
            ne = np.array(ne)
            print(f"  h {h}: test sessions {len(ne)} from {first}, n_eff quantiles 10/50/90 {np.percentile(ne, 10):.0f} / {np.percentile(ne, 50):.0f} / {np.percentile(ne, 90):.0f}, "
              f"share under 30: {np.mean(ne < 30):.2f}")


if __name__ == "__main__":
    main()
