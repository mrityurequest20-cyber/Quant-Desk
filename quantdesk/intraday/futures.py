"""Index futures in the read: what the futures market says that the index can't.

The index itself has no volume and no open interest; its near-month future has both. Three reads come from it:

* **Volume.** Each minute's futures volume is put on the index bar of that minute (the feed does it), so the
  session's volume profile, VWAP, relative volume and the bar-level order flow (CVD) are real volume, not time.
* **Open-interest build-up** over the last 30 minutes, the classic four states:
  price up + OI up = long build-up (fresh buying), price down + OI up = short build-up (fresh selling),
  price up + OI down = short covering, price down + OI down = long unwinding. Covering and unwinding are
  positions closing, so they count for half.
* **Basis**: futures minus spot, as an annualised carry. A premium collapsing toward (or through) fair carry means
  futures are being sold harder than the index; a premium widening means they're being bought.
"""
from __future__ import annotations

import math

import pandas as pd

IST = "Asia/Kolkata"


def buildup(px_chg: float, oi_chg: float, min_oi: float = 0.002) -> tuple[str, float]:
    """(state, direction in [-1, 1]) from the futures price change and the OI change (both fractions)."""
    if not (px_chg == px_chg and oi_chg == oi_chg) or abs(oi_chg) < min_oi or px_chg == 0:
        return "no clear build-up", 0.0
    strength = min(1.0, abs(oi_chg) / 0.01)                  # 1% OI in 30 minutes is a lot for an index future
    if oi_chg > 0:
        return ("long build-up", strength) if px_chg > 0 else ("short build-up", -strength)
    return ("short covering", 0.5 * strength) if px_chg > 0 else ("long unwinding", -0.5 * strength)


def carry(fut: float, spot: float, expiry, now) -> float | None:
    """Annualised carry implied by the futures premium (ACT/365, to the 15:30 expiry close)."""
    T = (pd.Timestamp(f"{expiry} 15:30", tz=IST) - pd.Timestamp(now)).total_seconds() / (365 * 86400)
    if not (fut > 0 and spot > 0) or T <= 1 / 365 / 24:
        return None
    return math.log(fut / spot) / T


def read(history: list[tuple], spot: float, now, expiry, symbol: str = "", window_min: int = 30) -> dict:
    """The futures read from the snapshots so far today: [(ts, ltp, oi, spot), …] of the active contract."""
    if not history:
        return {}
    ts, ltp, oi = history[-1][:3]
    out = {"fut_symbol": symbol, "fut_ltp": float(ltp), "fut_oi": float(oi), "fut_expiry": str(expiry)}
    if spot and spot == spot:
        out["fut_basis"] = float(ltp - spot)
        c = carry(ltp, spot, expiry, now)
        if c is not None:
            out["fut_carry"] = float(c)
    cut = pd.Timestamp(ts) - pd.Timedelta(minutes=window_min)
    past = [h for h in history if pd.Timestamp(h[0]) <= cut]
    if past:
        p0, o0 = past[-1][1], past[-1][2]
        if p0 and o0:
            px, dOI = ltp / p0 - 1, oi / o0 - 1
            state, d = buildup(px, dOI)
            out.update({"fut_px_chg30": float(px), "fut_oi_chg30": float(dOI), "fut_buildup": state, "fut_dir": float(d)})
    first = history[0]
    if first[2]:
        out["fut_oi_day"] = float(oi / first[2] - 1)
    if len(first) > 3 and "fut_carry" in out:                # the premium now vs at the first snapshot today
        c0 = carry(first[1], first[3], expiry, first[0])
        if c0 is not None:
            out["fut_carry_chg"] = float(out["fut_carry"] - c0)
    return out
