"""Strategy search for the paper desk's AUTO mode. PAPER MONEY ONLY. Pure: no network, no environment, no clock.

There is no list of named templates here. Given one expiry's chain (strike -> CE/PE names) and the board's quotes, `candidates` builds EVERY structure from a small set of building blocks
(a single option, two legs of the same right, a ratio, a three-leg wing) over the strikes near the money, and `choose` scores them all on one scale:

    score = expected profit per unit of the most it can lose,

where the expected profit is taken under a distribution of the index at expiry centred on the market's own implied move (the at-the-money straddle) and tilted by AUTO's view (its direction and
how many of its readings agree). That tilt is an ASSUMPTION about AUTO's edge, kept small and written down; it is the thing the record will test. Prices are the ones the desk would really get:
a purchase at the offer, a sale at the bid, plus one tick per leg for size impact. Nothing here decides whether an order is allowed: the risk gate does that, with the same worst-case arithmetic
(`account.stress_equity`).

What it prefers, by construction, is HIGH REWARD FOR LITTLE RISK (owner's brief): a structure must offer at least `min_rr` times its maximum loss as its maximum gain (an unlimited gain always passes),
and among those the best expected return per unit of risk wins. Sold legs appear only where they pay for themselves inside a bounded structure (a vertical that finances a long, a wing).
"""
from __future__ import annotations

import math

TICK = 0.05
STRADDLE_TO_SIGMA = 0.7979                 # ATM straddle ~ 0.798 * S * sigma * sqrt(T)
TILT_SCALE = 0.25                          # a full-conviction view moves the centre of the distribution by this fraction of one standard deviation: small on purpose
GRID = 241
WINDOW = 7                                 # strikes either side of the money that are considered
MAX_WIDTH = 6                              # strike steps between the legs of a vertical or a wing
MIN_RR_DEFAULT = 2.0
MIN_SCORE_DEFAULT = 0.03                   # expected profit of at least 3% of the maximum loss
MIN_POP_DEFAULT = 0.35                     # and a chance of finishing in profit of at least 35% (under the same distribution): the tails alone must not carry a trade


def _num(x):
    return float(x) if isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) else None


def price(q, side):
    """What the desk would get: buy at the offer, sell at the bid, plus one tick of size impact against us. None when the quote is not two-sided."""
    if not isinstance(q, dict):
        return None
    b, a = _num(q.get("bid")), _num(q.get("ask"))
    if b is None or a is None or not (0 < b <= a):
        return None
    return a + TICK if side == "buy" else max(b - TICK, 0.0)


def implied_move(spot, call_mid, put_mid):
    """The market's one-standard-deviation move to expiry (a fraction of spot), from the at-the-money straddle."""
    if not (spot and spot > 0 and call_mid and put_mid and call_mid > 0 and put_mid > 0):
        return None
    return (call_mid + put_mid) / (STRADDLE_TO_SIGMA * spot)


def distribution(spot, sigma, tilt):
    """[(price at expiry, weight)] on a fixed grid: log-normal, standard deviation `sigma` (a fraction), the mean moved by `tilt` standard deviations."""
    out = []
    zs = [-4 + 8 * i / (GRID - 1) for i in range(GRID)]
    ws = [math.exp(-0.5 * z * z) for z in zs]
    tot = sum(ws)
    mu = -0.5 * sigma * sigma + tilt * sigma
    for z, w in zip(zs, ws):
        out.append((spot * math.exp(mu + sigma * z), w / tot))
    return out


def payoff(legs, s):
    """Per unit of the underlying, at expiry price s. A leg: {"strike", "right", "qty"} with qty > 0 bought and < 0 sold."""
    tot = 0.0
    for l in legs:
        v = max(s - l["strike"], 0.0) if l["right"] == "CE" else max(l["strike"] - s, 0.0)
        tot += l["qty"] * v
    return tot


def _extremes(legs, cost):
    """(max loss, max gain) per unit, net of the cost; max gain is inf when the structure gains without limit. Piecewise linear: look at 0, every strike and beyond the last."""
    ks = sorted({l["strike"] for l in legs})
    pts = [0.0] + ks + [ks[-1] * 3]
    vals = [payoff(legs, s) - cost for s in pts]
    slope_up = sum(l["qty"] for l in legs if l["right"] == "CE")
    if slope_up < 0:
        return None, None                                                               # an uncovered short call: never
    lo, hi = min(vals), (math.inf if slope_up > 0 else max(vals))
    return -lo if lo < 0 else 0.0, hi


def candidates(chain, quotes, spot):
    """Every structure the building blocks allow around the money. chain: {strike: {"CE": name, "PE": name}}; quotes: {name: {"bid","ask",...}}.
    Each: {"legs": [{"symbol","strike","right","qty"}], "cost" (per unit, positive = a debit), "max_loss", "max_gain", "label"}."""
    ks = sorted(chain)
    if len(ks) < 3 or not spot:
        return []
    at = min(range(len(ks)), key=lambda i: abs(ks[i] - spot))
    idx = list(range(max(0, at - WINDOW), min(len(ks), at + WINDOW + 1)))

    def leg(i, right, qty):
        name = chain[ks[i]].get(right)
        p = price(quotes.get(name), "buy" if qty > 0 else "sell")
        return None if name is None or p is None else {"symbol": name, "strike": float(ks[i]), "right": right, "qty": qty, "_px": p}

    def make(label, legs):
        if any(l is None for l in legs):
            return None
        cost = sum(l["qty"] * l["_px"] for l in legs)                                    # signed: a purchase adds, a sale takes away
        ml, mg = _extremes(legs, cost)
        if ml is None or ml <= 0:
            return None                                                                  # no risk at all in the numbers = a bad quote, not a free lunch
        return {"legs": [{k: v for k, v in l.items() if k != "_px"} for l in legs], "cost": cost, "max_loss": ml, "max_gain": mg, "label": label}

    out = []
    for r in ("CE", "PE"):
        for i in idx:
            out.append(make(f"long {ks[i]:g} {r}", [leg(i, r, 1)]))
        for i in idx:
            for j in idx:
                if i != j and abs(i - j) <= MAX_WIDTH:
                    out.append(make(f"buy {ks[i]:g} / sell {ks[j]:g} {r}", [leg(i, r, 1), leg(j, r, -1)]))                       # a vertical, debit or credit
                    out.append(make(f"buy 2x {ks[i]:g} / sell {ks[j]:g} {r}", [leg(i, r, 2), leg(j, r, -1)]))                    # a ratio that keeps more longs than shorts
        for i in idx:
            for w in range(1, MAX_WIDTH):
                for w2 in range(1, MAX_WIDTH):
                    lo, hi = i - w, i + w2
                    if lo in idx and hi in idx:
                        out.append(make(f"{ks[lo]:g}/{ks[i]:g}/{ks[hi]:g} {r} wing", [leg(lo, r, 1), leg(i, r, -2), leg(hi, r, 1)]))      # a butterfly, even or broken
    return [c for c in out if c]


def choose(cands, spot, sigma, tilt, min_rr=MIN_RR_DEFAULT, min_score=MIN_SCORE_DEFAULT, min_pop=MIN_POP_DEFAULT):
    """The best structure by expected profit per unit of maximum loss, among those with max gain >= min_rr x max loss. Returns (best or None, how many were scored, how many passed the reward test).
    The winner carries "score", "ev" (expected profit per unit) and "pop" (the chance of finishing in profit)."""
    dist = distribution(spot, sigma, tilt)
    best, passed = None, 0
    for c in cands:
        if not (c["max_gain"] >= min_rr * c["max_loss"]):
            continue
        passed += 1
        vals = [(payoff(c["legs"], s) - c["cost"], w) for s, w in dist]
        ev, pop = sum(v * w for v, w in vals), sum(w for v, w in vals if v > 0)
        score = ev / c["max_loss"]
        if score >= min_score and pop >= min_pop and (best is None or score > best["score"] or (score == best["score"] and c["max_loss"] < best["max_loss"])):
            best = {**c, "ev": ev, "score": score, "pop": pop}
    return best, len(cands), passed
