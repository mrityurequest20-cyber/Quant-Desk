"""How the option chain moves through the session, not just where it stands.

`chains.chain_analytics` reads one snapshot per refresh: PCR, the OI walls, the 25-delta skew, ATM IV, the straddle.
What option desks trade on is how those change during the day, so each refresh's analytics are kept as a short
history per index and the changes are derived from it:

* **the OI walls migrating** since the first read of the session: the strike with the most call OI above spot moving
  down means writers are pressing on price; the put wall moving up means writers are building a floor under it;
* **the 25-delta risk reversal** (put IV − call IV) over 30 minutes: puts getting dearer than calls leans bearish,
  flattening leans bullish (the spot–vol link options desks watch);
* **ATM IV** over 30 minutes, in vol points: not a direction, but for a desk that only buys options the difference
  between a tailwind and a crush;
* **the PCR** over 30 minutes.

The two directional reads (walls, skew) go to the analyst as evidence **on probation**: the learning loop grades them
live from the first session, and they get a vote only after 30 graded reads at 1.15× reliability (as the brain's
probation drivers do). The first read's ATM IV is kept, so the session's realised volatility can be set against it at
the close (`learning.record_move`: the buyer's edge).

A model chain (priced off India VIX when no live chain is available) carries no market information, so it is ignored.
"""
from __future__ import annotations

from collections import deque

import numpy as np
import pandas as pd

KEEP_MIN = 120                       # history kept per index, minutes
TREND_MIN = 30                       # the window the trends are measured over
FIELDS = ("spot", "atm_iv", "skew_25d", "pcr_oi", "pcr_doi", "call_wall", "put_wall", "straddle", "implied_move",
          "dte_days")


def _num(x) -> float | None:
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    return x if x == x and np.isfinite(x) else None


class ChainFlow:
    """One per desk: `update(u, analytics, now, step)` after each chain refresh returns the derived `cf_*` fields."""

    def __init__(self):
        self.day = None
        self.first: dict[str, dict] = {}
        self.hist: dict[str, deque] = {}

    def update(self, u: str, an: dict | None, now: pd.Timestamp, step: float | None = None) -> dict:
        if not an or an.get("source") == "model":
            return {}
        if self.day != now.date():                      # a new session starts a new history
            self.day, self.first, self.hist = now.date(), {}, {}
        snap = {k: _num(an.get(k)) for k in FIELDS}
        snap["ts"] = now
        self.first.setdefault(u, snap)
        h = self.hist.setdefault(u, deque())
        h.append(snap)
        while h and now - h[0]["ts"] > pd.Timedelta(minutes=KEEP_MIN):
            h.popleft()
        return derive(self.first[u], list(h), now, step)

    def opening(self, u: str) -> dict | None:
        """The session's first live read of `u` (its ATM IV and implied move), or None."""
        return self.first.get(u)


def derive(first: dict, hist: list[dict], now: pd.Timestamp, step: float | None = None) -> dict:
    cur = hist[-1]
    out: dict = {"cf_since": str(first["ts"]), "cf_step": step}
    # 30 minutes ago: the latest read at or before then, if the history reaches back far enough
    cut = now - pd.Timedelta(minutes=TREND_MIN)
    ago = next((x for x in reversed(hist) if x["ts"] <= cut), None)
    if ago is None and hist and now - hist[0]["ts"] >= pd.Timedelta(minutes=TREND_MIN * 0.8):
        ago = hist[0]
    for k, name in (("atm_iv", "iv"), ("skew_25d", "skew"), ("pcr_oi", "pcr")):
        if cur.get(k) is not None:
            out[f"cf_{name}"] = cur[k]
            if ago is not None and ago.get(k) is not None:
                out[f"cf_{name}_chg30"] = cur[k] - ago[k]
            if first.get(k) is not None:
                out[f"cf_{name}_chg_open"] = cur[k] - first[k]
    for k in ("call_wall", "put_wall"):
        if cur.get(k) is not None and first.get(k) is not None:
            out[f"cf_{k}_open"], out[f"cf_{k}_shift"] = first[k], cur[k] - first[k]
    if first.get("atm_iv") is not None:
        out["cf_iv_open"] = first["atm_iv"]
    if first.get("implied_move") is not None:
        out["cf_implied_move_open"] = first["implied_move"]
    return out


def wall_shift_signal(c: dict) -> tuple[float, str] | None:
    """The walls' migration since the first read as a direction in −1..+1 (call wall down / put wall up: writers are
    leaning on price that way) and a sentence, or None when neither wall moved a full strike."""
    step = c.get("cf_step") or 0
    cs, ps = c.get("cf_call_wall_shift"), c.get("cf_put_wall_shift")
    if not step or (cs is None and ps is None):
        return None
    cs, ps = cs or 0.0, ps or 0.0
    if abs(cs) < step and abs(ps) < step:
        return None
    d = float(np.clip((cs + ps) / (2 * step), -1, 1))
    bits = []
    if abs(cs) >= step:
        bits.append(f"call wall {c['cf_call_wall_open']:,.0f} → {c['cf_call_wall_open'] + cs:,.0f}")
    if abs(ps) >= step:
        bits.append(f"put wall {c['cf_put_wall_open']:,.0f} → {c['cf_put_wall_open'] + ps:,.0f}")
    lean = "writers pressing price down" if d < 0 else "writers building a floor under price" if d > 0 else "both walls moved"
    return d, f"OI walls since the first read: {', '.join(bits)} ({lean})"


def skew_trend_signal(c: dict, min_change: float = 0.3) -> tuple[float, str] | None:
    """The 25-delta risk reversal's 30-minute change as a direction: puts getting dearer (rising) leans bearish."""
    ch = c.get("cf_skew_chg30")
    if ch is None or abs(ch) < min_change:
        return None
    d = float(np.clip(-ch / 1.5, -1, 1))
    return d, (f"25Δ risk reversal {c['cf_skew'] - ch:+.1f} → {c['cf_skew']:+.1f} vol pts in 30 min: "
               f"{'put demand rising' if ch > 0 else 'put demand easing'}")


def iv_trend_note(c: dict, min_change: float = 0.3) -> str | None:
    """ATM IV's 30-minute change, for the narrative (for a desk that buys options it decides theta vs vega)."""
    ch = c.get("cf_iv_chg30")
    if ch is None or abs(ch) < min_change:
        return None
    return (f"ATM IV {c['cf_iv'] - ch:.1f} → {c['cf_iv']:.1f} in 30 min "
            f"({'rising: a tailwind for bought options' if ch > 0 else 'falling: bought options lose vega as well as theta'})")


def chain_step(df: pd.DataFrame | None) -> float | None:
    """The chain's strike interval (the most common gap between listed strikes)."""
    if df is None or len(df.index) < 3:
        return None
    gaps = np.diff(np.sort(df.index.to_numpy(dtype=float)))
    gaps = gaps[gaps > 0]
    if not len(gaps):
        return None
    vals, counts = np.unique(np.round(gaps, 2), return_counts=True)
    return float(vals[np.argmax(counts)])
