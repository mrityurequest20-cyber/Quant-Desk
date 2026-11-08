"""Slippage for the paper desk: what a fill cost against what the trader saw, split into the part that is MEASURED and the part that is MODELLED.
Pure maths: no network, no environment, no clock. Paper money only.

For every fill we keep, per unit (a positive number is a cost to us, a negative one a gain):

  spread    half the quoted spread at the fill: buying at the offer or selling at the bid always pays it (measured, from the board)
  delay     how far the mid price moved between the moment the trader looked and the moment of the fill (measured, from the board; only
            when the order carries what the trader saw)
  impact    a MODEL of the extra price a bigger order pays beyond the touch. The board shows only the best price and its size, not the depth
            behind it, so this part cannot be measured here: it is a conservative table of ticks by share of the displayed size, written
            down in IMPACT_TABLE and added to the fill (a buy pays more, a sale gets less). It is reported separately so it is never
            mistaken for something observed, and it is to be calibrated against the recorded depth and, one day, real fills.
  shown     fill against the price the trader was shown to trade at (the offer for a buy, the bid for a sale): what the trader FELT.

total_vs_seen = spread + delay + impact: the fill against the mid price the trader saw. Check: shown + (seen touch - seen mid) = total_vs_seen.
"""
from __future__ import annotations

import math

TICK = 0.05
# (largest share of the displayed size, ticks of modelled impact). Up to 10% of what is shown: no extra. An order larger than the whole
# displayed size is refused by the risk gate, never filled partly, so the last row is the most a fill can pay.
IMPACT_TABLE = ((0.10, 0), (0.25, 1), (0.50, 2), (1.00, 3))
KEYS = ("side", "qty", "fill", "touch", "mid", "impact_ticks", "spread", "impact", "delay_s", "delay", "shown", "total_vs_seen", "seen_bid", "seen_ask",
        "spread_inr", "impact_inr", "delay_inr", "shown_inr", "total_inr", "bps")


def _ok(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def impact_ticks(qty, shown) -> int:
    """Ticks of modelled impact for an order of `qty` units against `shown` units displayed at the touch. Unknown or unusable size: the most (fail to the pessimistic side)."""
    if not (_ok(qty) and qty > 0 and _ok(shown) and shown > 0):
        return IMPACT_TABLE[-1][1]
    share = qty / shown
    for cap, ticks in IMPACT_TABLE:
        if share <= cap:
            return ticks
    return IMPACT_TABLE[-1][1]


def split(side: str, qty: int, fill: float, bid: float, ask: float, impact: float, seen_bid=None, seen_ask=None, delay_s=None) -> dict:
    """The slippage record of one fill. `bid`/`ask` are the touch at the fill (before impact); `impact` is the modelled price per unit already included in `fill`;
    `seen_*` is what the trader saw when deciding (None if the order did not carry it); `delay_s` the seconds since then (None if unknown)."""
    if side not in ("buy", "sell"):
        raise ValueError("side must be buy or sell")
    sign = 1.0 if side == "buy" else -1.0
    touch = ask if side == "buy" else bid
    mid = (bid + ask) / 2
    rec = {"side": side, "qty": int(qty), "fill": round(fill, 4), "touch": round(touch, 4), "mid": round(mid, 4), "impact_ticks": round(impact / TICK) if impact else 0,
           "spread": round(sign * (touch - mid), 4), "impact": round(sign * (fill - touch), 4)}
    seen = _ok(seen_bid) and _ok(seen_ask) and 0 < seen_bid <= seen_ask
    if seen:
        seen_mid = (seen_bid + seen_ask) / 2
        seen_touch = seen_ask if side == "buy" else seen_bid
        rec.update(seen_bid=round(seen_bid, 4), seen_ask=round(seen_ask, 4), delay=round(sign * (mid - seen_mid), 4), shown=round(sign * (fill - seen_touch), 4),
                   total_vs_seen=round(sign * (fill - seen_mid), 4))
    if seen and _ok(delay_s) and delay_s >= 0:
        rec["delay_s"] = round(float(delay_s), 1)
    for k, v in (("spread", rec["spread"]), ("impact", rec["impact"]), ("delay", rec.get("delay")), ("shown", rec.get("shown")), ("total", rec.get("total_vs_seen"))):
        if v is not None:
            rec[k + "_inr"] = round(v * qty, 2)
    if "total_inr" not in rec:                                             # no sight of the decision price: the cost against the mid at the fill is spread + impact
        rec["total_inr"] = round((rec["spread"] + rec["impact"]) * qty, 2)
    rec["bps"] = round(1e4 * (rec["total_inr"] / qty) / mid, 1) if mid > 0 else None
    return rec


def clean(rec) -> dict | None:
    """A slippage record as it may be written into the ledger: only the known keys, only finite numbers (and the side). None if it is not one."""
    if not isinstance(rec, dict):
        return None
    out = {}
    for k in KEYS:
        if k not in rec or rec[k] is None:
            continue
        v = rec[k]
        if k == "side":
            if v not in ("buy", "sell"):
                return None
        elif not _ok(v):
            return None
        out[k] = v
    return out if out.get("side") and _ok(out.get("qty")) else None


def totals(rows: list[dict]) -> dict:
    """The sums over the ledger's fills that carry a slippage record: per-fill ₹ costs added up, the notional, and the average in basis points of notional."""
    n = notional = 0.0
    sums = {"spread_inr": 0.0, "impact_inr": 0.0, "delay_inr": 0.0, "shown_inr": 0.0, "total_inr": 0.0}
    seen_n = 0
    for r in rows:
        s = r.get("slip")
        if not isinstance(s, dict) or not _ok(s.get("fill")) or not _ok(s.get("qty")):
            continue
        n += 1
        notional += s["fill"] * s["qty"]
        if "delay_inr" in s:
            seen_n += 1
        for k in sums:
            if _ok(s.get(k)):
                sums[k] += s[k]
    out = {"fills": int(n), "fills_with_decision_price": seen_n, "notional": round(notional, 2)}
    out.update({k: round(v, 2) for k, v in sums.items()})
    out["bps"] = round(1e4 * sums["total_inr"] / notional, 1) if notional > 0 else None
    return out
