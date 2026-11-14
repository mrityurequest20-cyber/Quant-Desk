"""The strategy inventor (owner, 13 Nov 2026: "make sure the trading desk has full liberty to use any trading strategy and also make its own strategy too"). PAPER MONEY
ONLY; nothing here trades.

AUTO v2's catalogue is written by hand. The inventor writes more: it takes structures whose record is good (by the hierarchical posterior) and MUTATES them, the way a
trader tinkers with a position: move a strike, widen or narrow a wing, buy a wing to cap a sold option, drop a leg, double a leg (a ratio), flip a leg's side. A child is
kept only if it is:
* DEFINED RISK: its worst case at expiry is finite (no net short call; a short put is finite but its worst case is the strike, which the risk gate's 2.5% refuses anyway);
* NEW: its payoff shape (per unit, without premiums) differs from every structure already known;
* TRADABLE: 1 to 4 legs, at most 6 lots in all, strikes within MAX_OFFSET steps of the money.
Its view (up, down or flat) is read from its own payoff, not inherited.

An invented structure is a strategy like any other: it is shadow-traded at the board's real prices, its record joins the hierarchical model as its own family, and it
trades paper money only after MIN_TRADES_INVENTED shadow trades of its own and a positive Thompson draw. MORE than a written strategy needs, on purpose: a desk that writes
hundreds of strategies and keeps the best is fitting noise unless the bar rises with the number of tries (data snooping). The population is capped, and an invention whose
record is clearly negative is retired.

Legs here are (side, right, offset): side is the signed size in lots, offset whole strike steps from the money. Pure functions; standard library only.
"""
from __future__ import annotations

import hashlib
import math
import random

MAX_LEGS = 4
MAX_LOTS = 6
MAX_OFFSET = 4
GRID = range(-12, 13)                       # the payoff is compared on these strike steps (and beyond, by its slopes)


def norm(legs) -> tuple:
    """Merge legs on one contract, drop zero ones, divide out a common size (two lots of a long put is a long put: results are counted in R, per unit of risk),
    sort: the canonical form."""
    acc: dict[tuple, int] = {}
    for side, right, off in legs:
        acc[(right, int(off))] = acc.get((right, int(off)), 0) + int(side)
    g = 0
    for q in acc.values():
        g = math.gcd(g, abs(q))
    return tuple(sorted((q // g, r, o) for (r, o), q in acc.items() if q)) if g else ()


def payoff(legs, x: float) -> float:
    return sum(q * (max(x - o, 0.0) if r == "CE" else max(o - x, 0.0)) for q, r, o in legs)


def defined_risk(legs) -> bool:
    """Finite worst case: the payoff's slope far above every strike (the net calls) must not be negative. Far below, puts lose at most their strikes: finite."""
    return sum(q for q, r, _ in legs if r == "CE") >= 0


def fingerprint(legs) -> tuple:
    """The payoff shape: values on the grid and the slopes beyond it, made level-free (a constant shift is premium, not shape)."""
    vals = [payoff(legs, x) for x in GRID]
    base = vals[len(vals) // 2]
    up = sum(q for q, r, _ in legs if r == "CE")
    down = -sum(q for q, r, _ in legs if r == "PE")
    return tuple(round(v - base, 6) for v in vals) + (up, down)


def view_of(legs) -> str:
    """up, down or flat, from the payoff two strikes either side of the money against at the money."""
    lo, mid, hi = payoff(legs, -2), payoff(legs, 0), payoff(legs, 2)
    if hi - lo >= 1.0:
        return "up"
    if lo - hi >= 1.0:
        return "down"
    return "flat"


def tradable(legs) -> bool:
    return (1 <= len(legs) <= MAX_LEGS and sum(abs(q) for q, _, _ in legs) <= MAX_LOTS and all(abs(o) <= MAX_OFFSET for _, _, o in legs)
            and any(q > 0 for q, _, _ in legs))


def code_of(legs) -> str:
    """A short, stable name: G and five hex characters of the canonical legs."""
    return "G" + hashlib.sha1(repr(norm(legs)).encode()).hexdigest()[:5]


def describe(legs) -> str:
    def one(q, r, o):
        where = "at the money" if o == 0 else f"{abs(o)} strike{'s' if abs(o) > 1 else ''} {'above' if o > 0 else 'below'}"
        return f"{'buy' if q > 0 else 'sell'} {abs(q)} {'call' if r == 'CE' else 'put'}{'s' if abs(q) > 1 else ''} {where}"
    return "invented: " + ", ".join(one(*l) for l in legs)


def mutate(legs, rng: random.Random) -> tuple:
    """One random edit of a trader's kind."""
    legs = list(norm(legs))
    op = rng.choice(("shift", "shift", "wing", "drop", "double", "flip", "add"))
    if op == "shift" and legs:
        i = rng.randrange(len(legs))
        q, r, o = legs[i]
        legs[i] = (q, r, o + rng.choice((-1, 1)))
    elif op == "wing" and legs:                                          # buy an option further out than a sold one: a cap
        sold = [l for l in legs if l[0] < 0]
        if sold:
            q, r, o = rng.choice(sold)
            legs.append((1, r, o + (1 if r == "CE" else -1) * rng.choice((1, 2))))
    elif op == "drop" and len(legs) > 1:
        legs.pop(rng.randrange(len(legs)))
    elif op == "double" and legs:
        i = rng.randrange(len(legs))
        q, r, o = legs[i]
        legs[i] = (q * 2, r, o)
    elif op == "flip" and legs:
        i = rng.randrange(len(legs))
        q, r, o = legs[i]
        legs[i] = (-q, r, o)
    else:                                                                # add any one option near the money
        legs.append((rng.choice((1, -1)), rng.choice(("CE", "PE")), rng.randint(-2, 2)))
    return norm(legs)


def invent(parents: list[tuple], known: set, rng: random.Random, want: int, tries: int = 400) -> list[tuple]:
    """Up to `want` new leg sets from mutations (one to three edits) of `parents`, each defined-risk, tradable and of a shape not in `known` (fingerprints)."""
    out, seen = [], set(known)
    if not parents:
        return out
    for _ in range(tries):
        child = rng.choice(parents)
        for _ in range(rng.randint(1, 3)):
            child = mutate(child, rng)
        if not (child and tradable(child) and defined_risk(child)):
            continue
        fp = fingerprint(child)
        if fp in seen:
            continue
        seen.add(fp)
        out.append(child)
        if len(out) >= want:
            break
    return out
