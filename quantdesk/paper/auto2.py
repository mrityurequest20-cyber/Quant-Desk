"""AUTO v2: a paper desk that writes, tests and chooses its own option strategies. PAPER MONEY ONLY.

Owner, 13 Nov 2026: "a system which is sophisticated, advanced ... can take any strategy in its place, create its own strategy, permutation, combination, can trade."

How it works, every cycle of the paper runner (a few seconds):

1. MARKET STATE of each underlying (the four index families and the 20 watchlist stocks): its direction (AUTO v1's readings: resting bid/offer pressure, the options' forward
   against the futures, the five-minute move and the news), its VOLATILITY STATE (the options' at-the-money implied volatility against the volatility the price has actually
   shown over the last hour: "rich" when the options price more movement than the price is making, "cheap" when less) and its TIMING (an expiry tomorrow or not). The desk's own
   pre-registered research found direction hard to forecast and volatility easier, and the expiry-eve premium real: the state is built so the strategies can use both.
2. THE CATALOGUE: every combination (permutation) of a market context (direction up, down or flat; volatility rich, cheap or either; any day or the expiry eve), a structure that
   suits it (long call or put; debit and credit spreads; iron condor and iron butterfly; long straddle and strangle), a width, an expiry (the nearest or the next), a take-profit,
   a stop and a holding style (out by the close, or up to three sessions). About 1,800 strategies, each with a short id that says exactly what it is.
3. THE SHADOW BOOK: whenever a strategy's context holds for an underlying, it is "traded" in shadow: no money, no account, but at the real bid and offer of every leg on the live
   board, with the desk's real fees, and closed by its own exits at the real prices. Each closed shadow trade is scored in R (profit over the most it could have lost) and added to
   that strategy's record. The record is kept on the private relay, so it grows across sessions and restarts.
4. CHOOSING WHAT TO TRADE: for each underlying the strategies whose context holds now are compared by THOMPSON SAMPLING (each draws a plausible average R from what its record
   says, shrunk towards zero while the record is short; the highest draw wins). A strategy trades with paper money only once its shadow record has MIN_TRADES trades and its draw
   is above zero, so capital flows to what has worked and away from what has not, and an unproven idea keeps being tested in shadow until it earns a place.
5. LIVE ORDERS go through the runner and the risk gate exactly like the owner's: one lot; a multi-leg structure as one package (every leg or none, worst case bounded and checked by
   the gate). Its exits are the strategy's own (take-profit, stop, time), sold options are bought back first, and the runner's forced sales (expiry, a stock option's last day,
   the brakes, the kill switch) apply on top.

What bounds it: only the risk gate's loss caps (2.5% of the account a trade with fees, 5% a day, a 10% drawdown halt) and the relay's storage guard. No cap on the number of trades,
strategies or positions (owner, 8 Nov 2026). A sold option is only ever a leg of a structure whose worst case is bounded.

NOT proven to make money. The shadow record is the evidence it builds; it is shown in the app (Positions, Strategy lab) and pushed with the session review.
"""
from __future__ import annotations

import datetime as dt
import json
import math
import random
import re
from dataclasses import dataclass

from ..markets import sessions as MK
from . import auto as V1
from . import inventor as INV
from . import marketread as MR
from . import newsmodel as NM
from . import regimes as RG
from . import tails as TL
from .runner import _num

IST = MK.IST
TAG = "AUTO v2"
RATE = V1.RATE
TICK = 0.05

# ---- the knobs ------------------------------------------------------------------------------------------------------------------------------
RICH, CHEAP = 1.25, 0.85                 # implied over realized volatility: rich at or above, cheap at or below
CALM_PCT = 0.10                          # flat: no direction, and the five-minute move under this
# Thresholds in each instrument's OWN volatility (owner, 13 Nov 2026: "Models should read differently as per the instrument"): 0.10% in five minutes is a real move for
# USD/INR and noise for natural gas. With the last hour's realized volatility known, a five-minute move is measured in its five-minute standard deviation: a vote at
# MOVE_K of them, "calm" under CALM_K. Until then, the fixed CALM_PCT and AUTO v1's threshold (both set for NIFTY, where 1.15 sd is about 0.10%).
MOVE_K, CALM_K = 1.15, 1.15
SD5_FROM_ANNUAL = math.sqrt(300 / (252 * 6.25 * 3600))   # an annualized volatility (realized_vol's units) to a five-minute standard deviation
FLAT_TREND_T = 1.0                       # flat also needs the Kalman trend's t-statistic under this (when it has one): a market drifting steadily is not flat
RV_WINDOW_S, RV_STEP_S, RV_MIN_POINTS = 3600, 60, 20      # realized volatility: one-minute returns over the last hour, at least twenty of them
QUOTE_MAX_AGE_S, MAX_LEG_SPREAD = 30.0, 0.10              # every leg needs a two-sided book this fresh, no wider than this (of its mid)
MIN_PREMIUM = 1.0                        # a leg priced below this is not traded (ticks dominate)
MAX_FEES_R = 0.30                        # a structure whose round-trip costs exceed this share of its risk is not opened: born at -0.3R, a 0.5R stop means nothing (a one-strike
#                                          NIFTY butterfly or iron fly costs about half its risk to trade)
REENTRY_S = 15 * 60                      # a strategy waits this long on an underlying after a shadow trade closes (correlated copies of one trade are not evidence)
MIN_TRADES = 8                           # shadow trades a strategy needs before it may trade with paper money
MIN_TRADES_INVENTED = 12                 # an INVENTED strategy needs more (inventor.py): a desk that writes many strategies and keeps the best must raise its bar
INVENT_PER_DAY = 6                       # new structures the inventor writes each morning
MAX_INVENTED = 60                        # invented strategies alive at once; past it, the worst record is retired first
PRIOR_SD = 1.0                           # a strategy's R is taken to vary about this much trade to trade until its own record says otherwise
# The HIERARCHICAL model of the record (owner, 13 Nov 2026: "Hierarchical Bayesian models: sharing evidence between similar strategies"), Lab.fit below:
#   strategy mean R  theta_i ~ N(mu_family, tau^2)       the 180-odd strategies of one structure (an iron condor's widths, filters, exits, holds) are a family
#   family mean R    mu_f    ~ N(0, HB_TAU_TOP^2)        and every family is anchored at zero edge after costs: the honest prior for a rule never seen to work
HB_TAU_TOP = 0.25                        # how far a whole structure's mean R is believed to sit from zero, before any record (a prior, in R)
HB_TAU_MIN, HB_TAU_MAX, HB_TAU_DEFAULT = 0.05, 1.0, 0.25     # tau (strategies about their family's mean) is estimated from the record (DerSimonian-Laird), within these
HB_RHO = 0.3                             # the assumed correlation of strategies within a family (the same market moments, other filters and exits): their records are worth
#                                          fewer independent pieces of evidence about the family, by the design effect 1 + (m - 1) rho
HB_NU0 = 4.0                             # a strategy's own spread of R is shrunk towards PRIOR_SD as if PRIOR_SD came from this many trades
ENTRY_BACKOFF_S = 60.0                   # after a live entry on an underlying (filled or not), the next waits this long
EXIT_RESEND_S = 15.0
DAY_EXIT = dt.time(15, 15)               # "day" strategies are out by here
FIRST_ENTRY = dt.time(9, 20)             # no entries in the opening auction's aftermath
LAST_ENTRY = dt.time(15, 0)
# MCX and currency options (owner, 13 Nov 2026: "treated in the same way" as index and stock options): each segment's own hours. (first entry, last entry, day strategies out by)
WINDOWS = {"nse_fo": (FIRST_ENTRY, LAST_ENTRY, dt.time(15, 15)), "nse_cds": (dt.time(9, 10), dt.time(16, 15), dt.time(16, 40)),
           "mcx": (dt.time(9, 10), dt.time(22, 45), dt.time(23, 10))}
FUT_SUFFIX = {"mcx": "-MCX", "nse_cds": "-CDS"}           # their underlying is the near-month future the board shows
# The event regime (owner, 13 Nov 2026: "the whole analysis of news and data can go hand in hand in a big event situation or in any move geopolitical situation"): a high-severity
# event in the news digest's event watch that touches the underlying, or the options pricing one (the near expiry's volatility above the next's), and AUTO v2 opens no short-
# volatility structure: an iron condor or fly sold into an event is the trade that loses most when the event moves the market.
SHORT_VOL = frozenset({"IC", "IF", "CBF", "PBF"})       # structures that are short volatility (is_short_vol: flat, nothing net long or short in calls or puts)
EVENT_TOUCHES = {"geopolitics": "all", "policy": "all", "inflation": "all", "growth": "all", "flows": "equity", "global": "equity", "regulation": "equity",
                 "commodities": "mcx", "currency": "cds"}
# The TAIL CHECK (owner, 13 Nov 2026: "Extreme value theory: tail-risk estimates"): a structure that TAKES IN PREMIUM sells a tail. The shadow record cannot price that tail (a
# few weeks of trades rarely hold the day that costs most), so before one is opened, shadow or live, its expected value to expiry is taken over the underlying's fitted
# distribution (tails.py: conditional EVT, today's volatility with history's shape; never a volatility below the last hour's realized one), and it opens only when the
# premium pays for the tail: that expectation, net of costs, at least TAIL_MIN_EDGE_R. No tail model in the brief (or no brief): no check, and the plan says so.
TAIL_MIN_EDGE_R = 0.0
TOUCH_MIN = 0.3                                            # a high event touches an instrument whose sensitivity to its stories' subjects is at least this (newsmodel.py)
READ_EVERY_S = 30                                          # the market read is refreshed this often per underlying
MIN_PREMIUM_TICKS = 20                                     # an MCX or currency option's premium floor, in its own ticks (a currency option trades near 0.05)
SWING_SESSIONS = 3
LEDGER_SOFT_LIMIT = V1.LEDGER_SOFT_LIMIT
SUMMARY_SOFT_MAX = 30000                 # AUTO v2's share of the runner's state (the relay's cap is 60,000 for all of it): past this, reasons are dropped before numbers
LAB_MAX_CHARS = 110000                   # the relay keeps the record in one stored value (128 KiB at most)
# The day plan (owner, 13 Nov 2026: "6 am to 9:15 am, the desk will plan the day by analysing options data, futures data and top to bottom predictive news analysis and look
# for high risk to reward trades"). Built from last night's closing books, the overnight markets, the news and the pre-market brief; it ranks defined-risk candidates and the
# open takes a planned strategy first, through the same proof gate (MIN_TRADES, a positive draw) and the same risk gate as any other.
PLAN_FROM, PLAN_UNTIL = dt.time(6, 0), dt.time(9, 15)
PLAN_EVERY_S = 600
PLAN_MAX_AGE_S = 4 * 86400                # last close: Friday's prices plan Monday morning
PLAN_MIN_RR = 2.0                         # reward to risk at the strategy's own take-profit and stop, capped by what the structure can make
PLAN_TOP = 10
PLAN_PER_U = 2
OVERNIGHT_TH_PCT = 0.40                   # the overnight markets' median move that counts as a vote
INDEX_U = frozenset({"NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "NIFTYNXT50", "SENSEX", "BANKEX"})     # the overnight cue and macro events are votes for the indices only

# ---- the catalogue --------------------------------------------------------------------------------------------------------------------------
# structure: (code, view, legs as (side, right, offset from the at-the-money strike in strike steps; "w" is the width), widths)
STRUCTURES = {
    "LC": ("up", [(1, "CE", "1")], (0,)),                                             # long call, the first strike out of the money
    "BCS": ("up", [(1, "CE", "0"), (-1, "CE", "w")], (1, 2)),                         # bull call spread (debit)
    "BPS": ("up", [(-1, "PE", "-1"), (1, "PE", "-1-w")], (1, 2)),                     # bull put spread (credit)
    "LP": ("down", [(1, "PE", "-1")], (0,)),                                          # long put
    "BRP": ("down", [(1, "PE", "0"), (-1, "PE", "-w")], (1, 2)),                      # bear put spread (debit)
    "BRC": ("down", [(-1, "CE", "1"), (1, "CE", "1+w")], (1, 2)),                     # bear call spread (credit)
    "IC": ("flat", [(-1, "CE", "w"), (1, "CE", "2w"), (-1, "PE", "-w"), (1, "PE", "-2w")], (1, 2)),       # iron condor
    "IF": ("flat", [(-1, "CE", "0"), (-1, "PE", "0"), (1, "CE", "w"), (1, "PE", "-w")], (1, 2)),          # iron butterfly
    "LS": ("flat", [(1, "CE", "0"), (1, "PE", "0")], (0,)),                           # long straddle
    "LG": ("flat", [(1, "CE", "w"), (1, "PE", "-w")], (1, 2)),                        # long strangle
    # More of what traders trade (owner, 13 Nov 2026: "the trading desk has full liberty to use any trading strategy"). A leg's side is also its size in lots (2 = two
    # lots): a contract appears once in a package. Every one has a defined worst case, which is what lets the 2.5%-a-trade limit hold; one that could lose without limit
    # (a naked short call, a call ratio spread) is refused by price() whatever writes it.
    "CBF": ("flat", [(1, "CE", "-w"), (-2, "CE", "0"), (1, "CE", "w")], (1, 2)),      # call butterfly: the price pinned near here
    "PBF": ("flat", [(1, "PE", "w"), (-2, "PE", "0"), (1, "PE", "-w")], (1, 2)),      # put butterfly
    "BWC": ("up", [(1, "CE", "0"), (-2, "CE", "w"), (1, "CE", "2w+1")], (1, 2)),      # broken-wing call butterfly: a drift up, little or nothing lost below
    "BWP": ("down", [(1, "PE", "0"), (-2, "PE", "-w"), (1, "PE", "-2w-1")], (1, 2)),  # broken-wing put butterfly
    "CRB": ("up", [(-1, "CE", "0"), (2, "CE", "w")], (1, 2)),                         # call ratio backspread: a big move up, paid for by a sold call
    "PRB": ("down", [(-1, "PE", "0"), (2, "PE", "-w")], (1, 2)),                      # put ratio backspread
}
NAMES = {"LC": "long call", "BCS": "bull call spread", "BPS": "bull put spread", "LP": "long put", "BRP": "bear put spread", "BRC": "bear call spread",
         "IC": "iron condor", "IF": "iron butterfly", "LS": "long straddle", "LG": "long strangle", "CBF": "call butterfly", "PBF": "put butterfly",
         "BWC": "broken-wing call butterfly", "BWP": "broken-wing put butterfly", "CRB": "call ratio backspread", "PRB": "put ratio backspread"}
VOLS = ("rich", "cheap", "any")
TIMINGS = (("any", "near"), ("any", "next"), ("eve", "near"))      # (timing, expiry): the expiry eve only makes sense on the expiry that is tomorrow
EXITS = ((0.5, 0.5), (1.0, 0.5), (2.0, 0.5), (0.5, 1.0), (1.0, 1.0), (2.0, 1.0))      # (take-profit in R, stop in R); a stop of 1 R holds to the worst case
HOLDS = ("day", "swing")
# one letter for each part of a strategy id, each distinct within its part: up/down/flat, rich/cheap/any (volatility), any/eve (timing; "t" for any), near/next (expiry), day/swing
CODE = {"up": "u", "down": "d", "flat": "f", "rich": "r", "cheap": "c", "any": "a", "eve": "e", "near": "n", "next": "x", "day": "d", "swing": "s"}


@dataclass(frozen=True)
class Strategy:
    struct: str
    width: int
    view: str              # up | down | flat
    vol: str               # rich | cheap | any
    timing: str            # any | eve
    expiry: str            # near | next
    tp: float              # take-profit, R
    sl: float              # stop, R
    hold: str              # day | swing

    @property
    def sid(self) -> str:
        return f"{self.struct}{self.width}.{CODE[self.view]}{CODE[self.vol]}{CODE[self.timing]}{CODE[self.expiry]}.{self.tp:g}/{self.sl:g}.{CODE[self.hold]}"

    def describe(self) -> str:
        w = f" {self.width}-strike" if self.width else ""
        return (f"{NAMES[self.struct]}{w}, {self.expiry} expiry, when the view is {self.view} and volatility is {self.vol}"
                + (" on an expiry eve" if self.timing == "eve" else "") + f"; take profit at {self.tp:g}R, stop at {self.sl:g}R, " + ("out by the close" if self.hold == "day" else "held up to three sessions"))


def catalogue() -> list[Strategy]:
    out = []
    for code, (view, _legs, widths) in STRUCTURES.items():
        for w in widths:
            for vol in VOLS:
                for timing, expiry in TIMINGS:
                    for tp, sl in EXITS:
                        for hold in HOLDS:
                            out.append(Strategy(code, w, view, vol, timing, expiry, tp, sl, hold))
    return out


CATALOGUE = catalogue()
BY_SID = {s.sid: s for s in CATALOGUE}


def resolved_legs(struct: str, width: int) -> tuple:
    """A structure's legs as (lots, right, strike steps from the money), the canonical form the inventor works in."""
    return INV.norm((side, right, _offset(expr, width)) for side, right, expr in STRUCTURES[struct][1])


def is_short_vol(struct: str) -> bool:
    """Short volatility: a flat structure with no net calls and no net puts (it is paid while the price sits still and is hurt when it moves)."""
    view, legs, _ = STRUCTURES[struct]
    return view == "flat" and sum(sd for sd, r, _ in legs if r == "CE") == 0 and sum(sd for sd, r, _ in legs if r == "PE") == 0


def register_invention(legs, ctx: "Strategy | None" = None) -> list["Strategy"]:
    """Make an invented structure known (STRUCTURES, NAMES, BY_SID) and return its strategies: one per context in `ctx` (the parent's volatility, timing, expiry, exits and
    hold), or the plainest context when there is no parent. Idempotent."""
    legs = INV.norm(legs)
    code, view = INV.code_of(legs), INV.view_of(legs)
    STRUCTURES[code] = (view, [(q, r, str(o)) for q, r, o in legs], (0,))
    NAMES[code] = INV.describe(legs)
    c = ctx or Strategy(code, 0, view, "any", "any", "near", 1.0, 0.5, "day")
    s = Strategy(code, 0, view, c.vol, c.timing, c.expiry, c.tp, c.sl, c.hold)
    BY_SID.setdefault(s.sid, s)
    return [BY_SID[s.sid]]


def known_shapes() -> set:
    return {INV.fingerprint(resolved_legs(code, w)) for code, (_, _, widths) in STRUCTURES.items() for w in widths}


_TERM = re.compile(r"([+-]?)(\d*)(w?)")


def _offset(expr: str, w: int) -> int:
    """A leg's place in strike steps from the at-the-money strike: a sum of terms, each a whole number of strikes or of widths ("1", "-w", "2w+1", "-1-w")."""
    total, pos, e = 0, 0, expr.replace(" ", "")
    while pos < len(e):
        m = _TERM.match(e, pos)
        if not m or m.end() == pos:
            raise ValueError(f"bad leg offset {expr!r}")
        sign, num, wid = m.groups()
        k = int(num) if num else 1
        total += (-1 if sign == "-" else 1) * (k * w if wid else k)
        pos = m.end()
    return total


def legs_for(s: Strategy, strikes: list, atm_i: int) -> list[tuple[int, str, float]] | None:
    """[(side, right, strike)] on the board's strikes, or None if a strike is not there."""
    out = []
    for side, right, expr in STRUCTURES[s.struct][1]:
        i = atm_i + _offset(expr, s.width)
        if not 0 <= i < len(strikes):
            return None
        out.append((side, right, strikes[i]))
    return out


def payoff_bounds(legs) -> tuple[float, float]:
    """(worst, best) value at expiry per unit of a structure from its legs [(side, right, strike, price paid (+) or received (-) per unit)]: the payoff is piecewise linear, so
    the extremes are at a strike, at zero or out in the tails. best is inf when the structure gains without limit."""
    ks = sorted({k for _, _, k, _ in legs})
    cost = sum(side * px for side, _, _, px in legs)
    val = lambda S: sum(side * (max(0.0, S - k) if r == "CE" else max(0.0, k - S)) for side, r, k, _ in legs) - cost      # noqa: E731
    pts = [0.0, *ks, ks[-1] * 3]
    vals = [val(x) for x in pts]
    call_slope = sum(side for side, r, _, _ in legs if r == "CE")
    best = math.inf if call_slope > 0 else max(vals)
    worst = -math.inf if call_slope < 0 else min(vals)
    return worst, best


# ---- market state ---------------------------------------------------------------------------------------------------------------------------
# Black-Scholes and its implied volatility, here and not imported: the paper package may import only core, execution, markets and itself (a test pins that boundary).
def _ncdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def bs_price(S: float, K: float, T: float, r: float, sigma: float, right: str) -> float:
    if T <= 0 or sigma <= 0:
        return max(0.0, S - K) if right == "CE" else max(0.0, K - S)
    sq = sigma * math.sqrt(T)
    d1 = (math.log(S / K) + (r + sigma * sigma / 2) * T) / sq
    d2 = d1 - sq
    return S * _ncdf(d1) - K * math.exp(-r * T) * _ncdf(d2) if right == "CE" else K * math.exp(-r * T) * _ncdf(-d2) - S * _ncdf(-d1)


def implied_vol(price: float, S: float, K: float, T: float, r: float, right: str) -> float | None:
    """The volatility at which Black-Scholes gives `price`, by bisection between 0.1% and 500%; None when the price is outside what any volatility gives."""
    if not (price > 0 and S > 0 and K > 0 and T > 0):
        return None
    lo, hi = 0.001, 5.0
    if not (bs_price(S, K, T, r, lo, right) - 1e-9 <= price <= bs_price(S, K, T, r, hi, right)):
        return None
    for _ in range(70):
        mid = (lo + hi) / 2
        if bs_price(S, K, T, r, mid, right) < price:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2

def _book(q, now_ok=QUOTE_MAX_AGE_S):
    if not isinstance(q, dict):
        return None
    age, b, a = _num(q.get("age_s")), _num(q.get("bid")), _num(q.get("ask"))
    if None in (age, b, a) or not (0 <= age <= now_ok) or not (0 < b <= a):
        return None
    return b, a


def atm_iv(snap, chain, strikes, atm_i, spot, T, r: float = RATE) -> float | None:
    """The at-the-money implied volatility: the mean of the call's and the put's, each from the mid of its book."""
    if not (T > 0) or atm_i is None:
        return None
    k, ivs = strikes[atm_i], []
    for right in ("CE", "PE"):
        bk = _book((snap.get("quotes") or {}).get(chain[k].get(right)))
        if bk:
            iv = implied_vol((bk[0] + bk[1]) / 2, spot, k, T, r, right)                     # r = 0 for an option on a future (MCX, currency): the future is the forward
            if iv is not None and 0.01 < iv < 3:
                ivs.append(iv)
    return sum(ivs) / len(ivs) if ivs else None


def realized_vol(tape: list[tuple[float, float]], now_s: float) -> float | None:
    """Annualized volatility of one-minute log returns over the last hour of the tape (None with fewer than RV_MIN_POINTS)."""
    pts, last_t = [], None
    for t, px in tape:
        if t < now_s - RV_WINDOW_S or px <= 0:
            continue
        if last_t is None or t - last_t >= RV_STEP_S:
            pts.append((t, px))
            last_t = t
    if len(pts) < RV_MIN_POINTS + 1:
        return None
    rets = [math.log(pts[i][1] / pts[i - 1][1]) / math.sqrt(max(pts[i][0] - pts[i - 1][0], 1.0)) for i in range(1, len(pts))]
    m = sum(rets) / len(rets)
    var = sum((r - m) ** 2 for r in rets) / (len(rets) - 1)
    return math.sqrt(var * 252 * 6.25 * 3600) if var > 0 else None              # per-second variance to a year of 6.25-hour sessions


def _ist(t: float) -> dt.datetime:
    return dt.datetime.fromtimestamp(t, tz=IST)


# ---- the record -----------------------------------------------------------------------------------------------------------------------------
class Lab:
    """Each strategy's shadow record: [n, sum of R, sum of R squared, wins]. Pooled over underlyings (a strategy is a rule, not a stock).

    What a record says is read through a HIERARCHICAL (multilevel) normal model, fitted by empirical Bayes (fit): each strategy's mean R is shrunk towards its FAMILY's (the
    structure it trades: iron condor, bull call spread, ...), and each family's towards zero. A strategy with a short record borrows strength from its family's; one with a
    long record speaks for itself; a family whose members all lose drags a new member down before it has traded once. How much a member is pulled is not set by hand: the
    spread of members about their family (tau) is estimated from the record itself."""

    def __init__(self, stats: dict | None = None, inv: dict | None = None):
        self.inv: dict[str, dict] = {}                 # invented structures: code -> {"legs": [[lots, right, steps]...], "active": [sid, ...]} (inventor.py)
        for code, d in (inv or {}).items():
            try:
                legs = INV.norm(tuple((int(q), str(r), int(o)) for q, r, o in d["legs"]))
                if not (legs and all(r in ("CE", "PE") for _, r, _ in legs) and INV.tradable(legs) and INV.defined_risk(legs) and INV.code_of(legs) == code):
                    continue
                register_invention(legs)
                active = []
                for sid in d.get("active") or []:
                    parts = str(sid).split(".")
                    if len(parts) == 4 and parts[0] == code + "0" and sid not in BY_SID:
                        self._register_sid(code, sid)
                    if sid in BY_SID and BY_SID[sid].struct == code:
                        active.append(sid)
                self.inv[code] = {"legs": [list(l) for l in legs], "active": active}
            except (KeyError, TypeError, ValueError):
                continue
        self.stats: dict[str, list] = {}
        for sid, v in (stats or {}).items():
            if sid in BY_SID and isinstance(v, list) and len(v) == 4 and all(isinstance(x, (int, float)) and math.isfinite(x) for x in v) and v[0] >= 0:
                self.stats[sid] = [int(v[0]), float(v[1]), float(v[2]), int(v[3])]
        self.dirty = False
        self.today = {"shadow_opened": 0, "shadow_closed": 0, "live_entries": 0}
        self._ver, self._fit = 0, None

    @staticmethod
    def _register_sid(code: str, sid: str) -> None:
        """An invented strategy's id read back from storage: its structure is known, its context is in the id."""
        inv = {v: k for k, v in CODE.items() if k in ("up", "down", "flat")}
        try:
            _, ctx, ex, hold = sid.split(".")
            tp, sl = (float(x) for x in ex.split("/"))
            vol = {"r": "rich", "c": "cheap", "a": "any"}[ctx[1]]
            timing = {"e": "eve", "a": "any"}[ctx[2]]
            expiry = {"n": "near", "x": "next"}[ctx[3]]
            s = Strategy(code, 0, inv[ctx[0]], vol, timing, expiry, tp, sl, {"d": "day", "s": "swing"}[hold])
            if s.sid == sid and s.view == STRUCTURES[code][0]:
                BY_SID[sid] = s
        except (KeyError, ValueError, IndexError):
            pass

    def invented(self) -> list["Strategy"]:
        return [BY_SID[sid] for d in self.inv.values() for sid in d["active"] if sid in BY_SID]

    def min_trades(self, s: "Strategy") -> int:
        return MIN_TRADES_INVENTED if s.struct in self.inv else MIN_TRADES

    def adopt(self, legs, parent: "Strategy | None") -> list["Strategy"]:
        legs = INV.norm(legs)
        new = register_invention(legs, parent)
        code = INV.code_of(legs)
        d = self.inv.setdefault(code, {"legs": [list(l) for l in legs], "active": []})
        for s in new:
            if s.sid not in d["active"]:
                d["active"].append(s.sid)
        self.dirty = True
        self._ver += 1                                                          # a new family: the hierarchical model is refitted
        return new

    def retire(self, sid: str) -> None:
        for d in self.inv.values():
            if sid in d["active"]:
                d["active"].remove(sid)
                self.dirty = True
                self._ver += 1

    def add(self, sid: str, r: float) -> None:
        n, s, ss, w = self.stats.get(sid, [0, 0.0, 0.0, 0])
        r = max(-5.0, min(10.0, r))                                            # a bad quote cannot write a record of +500R
        self.stats[sid] = [n + 1, s + r, ss + r * r, w + (1 if r > 0 else 0)]
        self.dirty = True
        self._ver += 1
        self.today["shadow_closed"] += 1

    @staticmethod
    def _own(v: list) -> tuple[float, float] | None:
        """(mean R, its sampling variance) from one record, the spread of R shrunk towards PRIOR_SD (HB_NU0 pseudo-trades); None with no trades."""
        n, s, ss = v[0], v[1], v[2]
        if n <= 0:
            return None
        s2 = max((ss - s * s / n) / (n - 1), 0.0) if n >= 2 else 0.0
        s2 = ((n - 1) * s2 + HB_NU0 * PRIOR_SD ** 2) / ((n - 1) + HB_NU0)
        return s / n, s2 / n

    def fit(self) -> dict:
        """The hierarchical model, refitted when the record changes. {"tau", "family": {struct: (mu, var, members, trades)}, "post": {sid: (n, mean, se)}}.

        1. tau^2, the spread of true strategy means about their family's, by DerSimonian-Laird's method of moments pooled over families: Q = sum of w (y - weighted family
           mean)^2 with w = 1 / v; tau^2 = (Q - df) / (sum w - sum w^2 / sum w), kept within HB_TAU_MIN..HB_TAU_MAX (HB_TAU_DEFAULT while there is too little to say).
        2. Each family's mean: its members' means weighted by 1 / (tau^2 + v), their total weight divided by the design effect 1 + (m - 1) HB_RHO (correlated members are
           not independent evidence), combined with the N(0, HB_TAU_TOP^2) prior.
        3. Each strategy: the normal-normal posterior of its mean between its own record (precision n / s^2) and its family's mean (precision 1 / tau^2), with the family
           mean's own uncertainty carried through: var = 1 / precision + B^2 var(mu) where B is the weight on the family."""
        key = (self._ver, len(self.stats))
        if self._fit is not None and self._fit["key"] == key:
            return self._fit
        fam: dict[str, list] = {}
        for sid, v in self.stats.items():
            own = self._own(v)
            if own is not None:
                fam.setdefault(BY_SID[sid].struct, []).append((sid, v[0], own[0], own[1]))
        Q = df = C = 0.0
        for rows in fam.values():
            if len(rows) < 2:
                continue
            w = [1 / r[3] for r in rows]
            W = sum(w)
            ybar = sum(wi * r[2] for wi, r in zip(w, rows)) / W
            Q += sum(wi * (r[2] - ybar) ** 2 for wi, r in zip(w, rows))
            df += len(rows) - 1
            C += W - sum(wi * wi for wi in w) / W
        tau2 = min(max((Q - df) / C, HB_TAU_MIN ** 2), HB_TAU_MAX ** 2) if df >= 2 and C > 0 else HB_TAU_DEFAULT ** 2
        family = {}
        for struct in STRUCTURES:
            rows = fam.get(struct) or []
            w = [1 / (tau2 + r[3]) for r in rows]
            W = sum(w)
            prec_data = W / (1 + (len(rows) - 1) * HB_RHO) if rows else 0.0
            prec = prec_data + 1 / HB_TAU_TOP ** 2
            ymean = sum(wi * r[2] for wi, r in zip(w, rows)) / W if rows else 0.0
            family[struct] = (prec_data * ymean / prec, 1 / prec, len(rows), sum(r[1] for r in rows))
        post = {}
        for rows in fam.values():
            for sid, n, y, v in rows:
                mu, vmu = family[BY_SID[sid].struct][:2]
                p_i = 1 / v + 1 / tau2
                B = (1 / tau2) / p_i
                post[sid] = (n, (y / v + mu / tau2) / p_i, math.sqrt(1 / p_i + B * B * vmu))
        self._fit = {"key": key, "tau": math.sqrt(tau2), "family": family, "post": post}
        return self._fit

    def posterior(self, sid: str) -> tuple[int, float, float]:
        """(n, the hierarchical posterior mean R, its standard deviation). A strategy with no record gets its family's: (0, mu_family, sqrt(tau^2 + var(mu)))."""
        f = self.fit()
        got = f["post"].get(sid)
        if got is not None:
            return got
        mu, vmu = (f["family"].get(BY_SID[sid].struct) or (0.0, HB_TAU_TOP ** 2))[:2] if sid in BY_SID else (0.0, HB_TAU_TOP ** 2)
        return 0, mu, math.sqrt(f["tau"] ** 2 + vmu)

    def draw(self, sid: str, rng: random.Random) -> float:
        n, mean, se = self.posterior(sid)
        return rng.gauss(mean, se)

    def to_json(self, extra: dict | None = None) -> str:
        inv = {code: d for code, d in self.inv.items() if d["active"] or any(sid.startswith(code + "0.") for sid in self.stats)}
        head = {"v": 1, "inv": inv, **(extra or {})}
        budget = LAB_MAX_CHARS - len(json.dumps(head, separators=(",", ":")))
        items = sorted(self.stats.items(), key=lambda kv: -kv[1][0])
        out, size = {}, 2
        for sid, v in items:                                                    # the busiest records first: if the cap is ever reached, the thinnest are the ones left out
            row = [v[0], round(v[1], 4), round(v[2], 4), v[3]]
            size += len(json.dumps({sid: row}, separators=(",", ":"))) - 1
            if size > budget:
                break
            out[sid] = row
        return json.dumps({**head, "stats": out}, separators=(",", ":"))

    def summary(self, top: int = 12) -> dict:
        rows = []
        for sid, (n, s, ss, w) in self.stats.items():
            if n:
                _, mean, se = self.posterior(sid)
                rows.append({"sid": sid, "what": BY_SID[sid].describe(), "n": n, "mean_r": round(s / n, 3), "shrunk_r": round(mean, 3), "win": round(w / n, 3),
                             "live": n >= self.min_trades(BY_SID[sid]) and mean > 0, "invented": BY_SID[sid].struct in self.inv})
        rows.sort(key=lambda r: (-r["shrunk_r"], -r["n"]))
        f = self.fit()
        fams = [{"struct": k, "name": NAMES[k], "mu_r": round(mu, 3), "se": round(math.sqrt(vmu), 3), "members": m, "trades": n}
                for k, (mu, vmu, m, n) in f["family"].items() if m]
        fams.sort(key=lambda r: -r["mu_r"])
        return {"strategies": len(CATALOGUE), "tested": len(rows), "trades": sum(r["n"] for r in rows), "eligible": sum(1 for r in rows if r["live"]),
                "min_trades": MIN_TRADES, "today": dict(self.today), "top": rows[:top], "worst": sorted(rows, key=lambda r: r["shrunk_r"])[:3],
                "families": fams, "tau": round(f["tau"], 3), "invented": sum(len(d["active"]) for d in self.inv.values()), "min_trades_invented": MIN_TRADES_INVENTED,
                "inventions": self.inventions()}

    def inventions(self, top: int = 12) -> list[dict]:
        """The live inventions the app's strategy builder can build (legs as [lots, right, strike steps from the money]), best record first."""
        out = []
        for code, d in self.inv.items():
            if not d["active"]:
                continue
            fam = self.fit()["family"].get(code) or (0.0, HB_TAU_TOP ** 2, 0, 0)
            out.append({"code": code, "name": NAMES.get(code, code), "view": STRUCTURES[code][0], "legs": d["legs"], "mu_r": round(fam[0], 3), "trades": fam[3]})
        out.sort(key=lambda x: (-x["mu_r"], -x["trades"]))
        return out[:top]


# ---- the engine -----------------------------------------------------------------------------------------------------------------------------
class AutoPilotV2:
    def __init__(self, underlyings, lots: dict, fees_fn, cal, capital: float = 500_000.0, seed: int | None = None, lab: Lab | None = None,
                 segments: dict | None = None, ticks: dict | None = None):
        self.und = tuple(underlyings)
        self.segments = {str(u).upper(): s for u, s in (segments or {}).items() if s in FUT_SUFFIX}      # MCX and currency underlyings; everything else is NSE F&O
        self.ticks = {str(u).upper(): float(t) for u, t in (ticks or {}).items() if isinstance(t, (int, float)) and t > 0}
        self.lots = dict(lots)
        self.fees_fn = fees_fn                     # (underlying, expiry, strike, right, signed qty, price) -> rupees, the desk's real cost model
        self.cal = cal                             # core.calendar.TradingCalendar
        self.capital = float(capital)
        self.rng = random.Random(seed)
        self.lab = lab or Lab()
        self.tape: dict[str, list[tuple[float, float]]] = {}
        self.shadow: dict[tuple, dict] = {}        # (sid, u) -> open shadow trade
        self.cool: dict[tuple, float] = {}         # (sid, u) -> no shadow re-entry before this
        self.backoff: dict[str, float] = {}        # u -> no live entry before this
        self.pending_exit: dict[str, float] = {}
        self.n = 0
        self.last_state: dict[str, dict] = {}
        self.lab_saved_at = -1e9
        self.brief: dict | None = None             # the pre-market brief (quantdesk/premarket), handed in by the session; None = plan without it
        self.day_plan: dict | None = None
        self.plan_at = -1e9

    def strategies(self) -> list[Strategy]:
        """Everything it may trade: the written catalogue and what the inventor has written (inventor.py)."""
        return CATALOGUE + self.lab.invented()

    def evolve(self, today: dt.date) -> list[str]:
        """Once a day: retire inventions whose record is clearly negative (or the worst, past MAX_INVENTED), then write INVENT_PER_DAY new structures by mutating the
        structures of the best records so far (any written structure while there is no record). Returns the new strategy ids."""
        if getattr(self, "evolved_on", None) == today:
            return []
        self.evolved_on = today
        lab = self.lab
        live = lab.invented()
        for s in live:
            n, mean, se = lab.posterior(s.sid)
            if n >= 2 * MIN_TRADES_INVENTED and mean + 2 * se < 0:
                lab.retire(s.sid)
        live = lab.invented()
        while len(live) > MAX_INVENTED - INVENT_PER_DAY:
            worst = min(live, key=lambda s: lab.posterior(s.sid)[1])
            lab.retire(worst.sid)
            live = lab.invented()
        ranked = sorted((sid for sid, v in lab.stats.items() if v[0] >= 3 and sid in BY_SID), key=lambda sid: -lab.posterior(sid)[1])[:8]
        parents = [BY_SID[sid] for sid in ranked] or [s for s in CATALOGUE if s.width <= 1 and s.vol == "any" and s.timing == "any" and s.hold == "day"
                                                         and s.tp == 1.0 and s.sl == 0.5 and s.expiry == "near"]
        pool = [(resolved_legs(p.struct, p.width), p) for p in parents]
        made = []
        for child in INV.invent([lg for lg, _ in pool], known_shapes(), self.rng, INVENT_PER_DAY):
            parent = min(pool, key=lambda lp: len(set(lp[0]) ^ set(child)))[1]          # the nearest parent lends its context (filters, exits, hold)
            made += [s.sid for s in lab.adopt(child, parent)]
        return made

    # ---- the session's hooks (the same as AUTO v1's) ----------------------------------------------------------------------------------------
    def drain_events(self) -> list[dict]:
        return []

    @staticmethod
    def _is_mine(strategy) -> bool:
        return isinstance(strategy, str) and strategy.startswith(TAG)

    def _lot(self, u, expiry) -> int | None:
        lot = self.lots.get(u)
        if isinstance(lot, dict):
            lot = lot.get(expiry)
        return lot if isinstance(lot, int) and lot > 0 else None

    def _oid(self, t: float, kind: str) -> str:
        self.n += 1
        return f"auto2-{kind}-{int(t * 1000)}-{self.n}"

    def _tape(self, u, t, px):
        tp = self.tape.setdefault(u, [])
        if not tp or t - tp[-1][0] >= 5:
            tp.append((t, px))
        while tp and tp[0][0] < t - RV_WINDOW_S - 120:
            tp.pop(0)

    def _momentum(self, u, t):
        tp = self.tape.get(u) or []
        old = [p for s, p in tp if s <= t - V1.MOMENTUM_WINDOW_S]
        return (tp[-1][1] / old[-1] - 1) * 100 if old and tp else None

    def _trading_days_to(self, today: dt.date, exp: dt.date) -> int:
        n, d = 0, today
        while d < exp and n < 60:
            d = self.cal.next_trading_day(d)
            n += 1
        return n

    # ---- each segment on its own terms ---------------------------------------------------------------------------------------------------------
    def window(self, u: str) -> tuple:
        return WINDOWS[self.segments.get(u, "nse_fo")]

    def spot(self, snap, u: str):
        """The underlying's price: the index or stock itself, or for an MCX or currency option its near-month future."""
        return V1._spot(snap, u) if u not in self.segments else V1._spot(snap, u + FUT_SUFFIX[self.segments[u]])

    def profile(self, u: str) -> str:
        """How the market read reads this instrument (marketread.PROFILES): an index, a stock, an MCX commodity or a currency."""
        seg = self.segments.get(u)
        return "mcx" if seg == "mcx" else "cds" if seg == "nse_cds" else "index" if u in INDEX_U else "stock"

    def rate(self, u: str) -> float:
        return 0.0 if u in self.segments else RATE

    def min_premium(self, u: str) -> float:
        return MIN_PREMIUM_TICKS * self.ticks.get(u, 0.05) if u in self.segments else MIN_PREMIUM

    def tradable_expiries(self, u: str, exps, today: dt.date) -> list:
        """Expiries it may open: never today's; for MCX and currency, never one whose last holding day (the trading day before expiry, the runner's rule) is today."""
        out = [e for e in exps if e > today]
        return [e for e in out if self._trading_days_to(today, e) >= 2] if u in self.segments else out

    def state(self, snap, u, ch, now: dt.datetime, news) -> dict | None:
        """This underlying's market state, or None when the board cannot say."""
        t, ist = now.timestamp(), now.astimezone(IST)
        sp = self.spot(snap, u)
        if not sp or u not in ch:
            return None
        self._tape(u, t, sp)
        exps = self.tradable_expiries(u, sorted(ch[u]), ist.date())                       # never open on an expiry day's own contracts (MCX, currency: nor on the day before)
        if not exps:
            return None
        near, nxt = exps[0], (exps[1] if len(exps) > 1 else None)
        chain = ch[u][near]
        strikes = sorted(chain)
        atm_i = min(range(len(strikes)), key=lambda i: abs(strikes[i] - sp)) if strikes else None
        T = max((dt.datetime.combine(near, dt.time(15, 30), tzinfo=IST) - ist).total_seconds() / (365.25 * 86400), 0.0)
        iv = atm_iv(snap, chain, strikes, atm_i, sp, T, self.rate(u))
        rv = realized_vol(self.tape.get(u, []), t)
        fq = (snap.get("quotes") or {}).get(u + "-FUT")
        fut = V1._mid(fq) if isinstance(fq, dict) and (_num(fq.get("age_s")) or 1e9) <= 60 else None
        rd = V1.readings(snap, u, near, chain, ist, sp, fut)
        mom = self._momentum(u, t)
        nv, nwhy, nf = self.news_vote(news, u, t, sp)
        read = self.read(snap, u, ch, t, sp, near, nxt, T, ist)
        if not hasattr(self, "regimes"):
            self.regimes = RG.RegimeBook()
        self.regimes.update(u, t, sp)                                                      # the HMM regime and the CUSUM change points (regimes.py)
        rg = self.regimes.state(u, t)
        sd5 = rv * SD5_FROM_ANNUAL * 100 if rv else None                                    # this instrument's five-minute standard deviation, in %
        pmom, pvote = self.price_vote(mom, rg, sd5)
        d, why = V1.direction(rd["pressure"], rd["gap_pct"], pmom, nv, nwhy)
        d, why = self.with_read(d, why, rd, pmom, nv, nwhy, read, pvote)
        tr = rg.get("trend")
        calm = CALM_K * sd5 if sd5 else CALM_PCT                                           # calm in its own terms
        view = "up" if d > 0 else "down" if d < 0 else ("flat" if mom is not None and abs(mom) < calm and not (read or {}).get("vote")
                                                            and (tr is None or abs(tr["t"]) < FLAT_TREND_T) else None)
        ratio = iv / rv if iv and rv else None
        vol = "rich" if ratio is not None and ratio >= RICH else "cheap" if ratio is not None and ratio <= CHEAP else "mid"
        eve = self._trading_days_to(ist.date(), near) == 1
        regime, rwhy = self.regime(u, news, read, rg)
        if rwhy:
            why = list(why) + [rwhy]
        st = {"u": u, "spot": sp, "view": view, "why": why, "mom": mom, "iv": iv, "rv": rv, "ratio": ratio, "vol": vol, "eve": eve, "near": near, "next": nxt, "read": read,
              "regime": regime, "hmm": rg}
        self.last_state[u] = {k: (round(v, 4) if isinstance(v, float) else (v.isoformat() if isinstance(v, dt.date) else v)) for k, v in st.items() if k not in ("why", "read", "hmm")}
        if regime == "event":
            self.last_state[u]["event"] = (rwhy or "")[:160]
        self.last_state[u]["hmm"], self.last_state[u]["change"] = rg["hmm"], rg["change"]
        self.last_state[u]["trend_t"] = tr["t"] if tr else None
        self.last_state[u]["tail"] = self.tail_text(u)
        if read:
            self.last_state[u]["read"] = {k: read.get(k) for k in ("p_up", "why", "pcr", "buildup", "event_priced", "profile")}
        self.last_state[u]["news"] = {"p_up": nf["p_up"], "why": nf["why"][:2]} if nf and (nf["why"] or nf["vote"]) else None
        return st

    # ---- extreme value theory: the tails the premium must pay for --------------------------------------------------------------------------------
    def tail_model(self, u: str):
        """The underlying's tails.Model from the brief, read once per brief."""
        b = self.brief if isinstance(self.brief, dict) else {}
        if getattr(self, "_tails_of", None) is not b:
            self._tails_of, self._tails, self._tail_ev = b, {}, {}
            for k, d in (b.get("tails") or {}).items():
                m = TL.Model.read(d)
                if m is not None:
                    self._tails[str(k).upper()] = m
        return self._tails.get(u)

    def tail_text(self, u: str) -> str:
        m = self.tail_model(u)
        return f"1-day 99% ES -{m.es_pct(0.99, 1, 'loss'):.1f}% / +{m.es_pct(0.99, 1, 'gain'):.1f}%" if m else ""

    def tail_check(self, s: Strategy, st: dict, p: dict, today: dt.date) -> tuple[bool, str | None, float | None]:
        """(open it?, why not, the expected R to expiry over the tail model) for an option sale; (True, None, None) for anything else or with no model."""
        cost = sum(l["side"] * l["px"] for l in p["legs"])
        if cost >= 0:                                                                  # paid for, not paid: it buys its tails
            return True, None, None
        u = st["u"]
        m = self.tail_model(u)
        if m is None or not p.get("risk") or p["risk"] <= 0:
            return True, None, None
        days = max(1, self._trading_days_to(today, p["exp"]))
        sig = st["rv"] / math.sqrt(252) if st.get("rv") else None
        legs = tuple((l["side"], l["right"], l["k"]) for l in p["legs"])
        key = (u, p["exp"], legs, round(st["spot"], -int(math.floor(math.log10(st["spot"]))) + 3), days, round(sig or 0.0, 5))
        ev = self._tail_ev.get(key)
        if ev is None:
            pay = lambda S: sum(sd * (max(S - k, 0.0) if r == "CE" else max(k - S, 0.0)) for sd, r, k in legs)      # noqa: E731
            ev = m.expected_payoff(pay, st["spot"], days, sig)
            if len(self._tail_ev) > 5000:
                self._tail_ev.clear()
            self._tail_ev[key] = ev
        edge = (ev - cost - p["fees"]) / p["risk"]
        if edge >= TAIL_MIN_EDGE_R:
            return True, None, edge
        return False, f"the premium does not pay for the tail it sells: {edge:+.2f}R expected to expiry over {u}'s fitted tails (EVT)", edge

    def news_vote(self, news, u: str, t: float, price: float, with_globals: bool = True) -> tuple[int, str | None, dict | None]:
        """The news's ONE vote for this instrument (newsmodel.py): its own channel score and its own past episodes, as P(up); scored against the next hour. Where the model
        has no opinion and `u` is an index, AUTO v1's market-wide tone vote stands in."""
        b = self.brief if isinstance(self.brief, dict) else {}
        today = dt.datetime.fromtimestamp(t, tz=IST).date().isoformat()
        glob = b.get("global") if with_globals and b.get("session") == today else None    # last night's markets bear on today's session only
        try:
            nf = NM.forecast(u, news, b.get("news_analogs"), t, glob)
        except Exception:                                                                # noqa: BLE001 - a news model that fails costs the vote, never the session
            nf = None
        if not hasattr(self, "news_scorer"):
            self.news_scorer = NM.Scorer()
        if nf is not None:
            self.news_scorer.add(u, t, nf["p_up"], price)
            if nf["vote"]:
                return nf["vote"], f"news P(up) {nf['p_up']:.2f}" + (f": {nf['why'][0]}" if nf["why"] else ""), nf
        if u in NM.INDEX:
            v, why = V1.news_vote(news, u, dt.datetime.fromtimestamp(t, tz=IST))
            return v, why, nf
        return 0, None, nf

    @staticmethod
    def price_vote(mom, rg: dict, sd5: float | None = None) -> tuple[float | None, tuple | None]:
        """The price's ONE vote in the view: (the raw five-minute move for AUTO v1's rule, or None; an extra (vote, reason), or None).
        The Kalman trend (kalman.py), once fitted, replaces the raw five-minute move: its slope over its standard error is a t-statistic, so one noisy print moves it
        little. A fresh CUSUM drift change point votes only when neither does: the trend, the move and the change point all read the same prices, and the same evidence
        counted twice would let price alone satisfy "two readings agree"."""
        tr = rg.get("trend")
        if tr is not None:
            if tr["vote"]:
                return None, (tr["vote"], f"Kalman trend {tr['slope_pct'] * 60:+.2f}% an hour (t {tr['t']:+.1f})")
            return None, ((rg["vote"], f"CUSUM change point: {rg['change']}") if rg.get("vote") else None)
        if sd5:                                                                         # the move in the instrument's own five-minute standard deviations
            if mom is not None and abs(mom) >= MOVE_K * sd5:
                return None, ((1 if mom > 0 else -1), f"{mom:+.2f}% in 5 min ({abs(mom) / sd5:.1f} of its five-minute sd)")
            return None, ((rg["vote"], f"CUSUM change point: {rg['change']}") if rg.get("vote") else None)
        if mom is not None and abs(mom) >= V1.MOMENTUM_TH_PCT:
            return mom, None
        return mom, ((rg["vote"], f"CUSUM change point: {rg['change']}") if rg.get("vote") else None)

    # ---- the event regime: news and data together --------------------------------------------------------------------------------------------------
    def regime(self, u: str, news, read: dict | None, rg: dict | None = None) -> tuple[str, str | None]:
        """("event", why) when a high event in the digest's event watch touches `u`, or the options price one; else ("normal", None)."""
        seg = self.segments.get(u)
        group = "mcx" if seg == "mcx" else "cds" if seg == "nse_cds" else "equity"
        for e in ((news or {}).get("events") or []) if isinstance(news, dict) else []:
            if not isinstance(e, dict) or e.get("level") != "high":
                continue
            reach = EVENT_TOUCHES.get(e.get("type"))
            if (reach == "all" or reach == group or (reach == "mcx" and group == "equity" and e.get("type") == "commodities")
                    or NM.touches(u, e) >= TOUCH_MIN):                                  # or its stories' subjects reach this instrument (crude news reaches the rupee)
                past = self.analog_line(e.get("kind"), u)
                return "event", f"event regime: {e.get('type')} (severity {e.get('severity')}, tone {e.get('tone'):+.2f})" + (f"; {past}" if past else "")
        if read and read.get("event_priced"):
            return "event", "event regime: the near expiry's volatility is above the next's (an event is priced)"
        if rg and rg.get("stress"):
            if rg.get("change") == "volatility up":
                return "event", "event regime: a CUSUM change point to higher volatility in the last quarter hour"
            return "event", f"event regime: the HMM puts {u} in its stressed state (P {((rg.get('p') or {}).get('stressed') or 0):.2f})"
        return "normal", None

    def analog_line(self, kind, u: str | None = None) -> str | None:
        """What this instrument did on the past episodes of this kind most like today (the brief's news_analogs), else what NIFTY did on all of them, in one line."""
        own = ((((self.brief or {}).get("news_analogs") or {}).get(kind) or {}).get(u)) if kind and u else None
        if isinstance(own, dict) and own.get("n") and isinstance(own.get("p_up"), (int, float)):
            near = ", ".join(f"{d} ({r * 100:+.1f}%)" for d, _, r in (own.get("nearest") or [])[:2])
            return (f"{u} on the {own['n']} past {kind.replace('_', ' ')} episodes, weighted to the most like today (effective {own.get('n_eff', 0):.1f}): rose "
                    f"{own['p_up'] * 100:.0f}% of the time, weighted mean {own.get('mean_ret_w', 0) * 100:+.1f}%, worst {own.get('worst', 0) * 100:+.1f}%"
                    + (f"; closest: {near}" if near else ""))
        a = (((self.brief or {}).get("analogs") or {}).get(kind) or {}).get("NIFTY") if kind else None
        if not isinstance(a, dict) or not a.get("n"):
            return None
        part = f"the last {a['n']} {kind.replace('_', ' ')} episodes: NIFTY median {a.get('median_ret', 0) * 100:+.1f}% on the day"
        if a.get("share_down") is not None:
            part += f", fell {round(a['share_down'] * a['n'])} of {a['n']}"
        if a.get("worst") is not None:
            part += f", worst {a['worst'] * 100:+.1f}%"
        if a.get("median_5d") is not None:
            part += f", {a['median_5d'] * 100:+.1f}% over five sessions"
        return part

    # ---- the market read (marketread.py): options, futures and spot together ------------------------------------------------------------------
    def read(self, snap, u, ch, t, sp, near, nxt, T, ist) -> dict | None:
        """The market read of `u`, at most every READ_EVERY_S (a chain read prices a few implied volatilities)."""
        if not hasattr(self, "reader"):
            self.reader, self.read_at = MR.MarketRead(), {}
            self.reader.restore(getattr(self, "_read_w", None))                         # what each instrument's read learned on earlier days
        if t - self.read_at.get(u, -1e18) < READ_EVERY_S and u in self.reader.last:
            return self.reader.last[u]
        self.read_at[u] = t
        seg = self.segments.get(u)
        fut_name = u + FUT_SUFFIX[seg] if seg else u + "-FUT"
        T_next = max((dt.datetime.combine(nxt, dt.time(15, 30), tzinfo=IST) - ist).total_seconds() / (365.25 * 86400), 0.0) if nxt else None
        try:
            return self.reader.update(u, t, snap, ch[u][near], sp, T, self.rate(u), implied_vol, fut_name=fut_name, next_chain=ch[u].get(nxt) if nxt else None,
                                      T_next=T_next, spot_name=None if seg else u, profile=self.profile(u))
        except Exception:                                                                # noqa: BLE001 - a read that fails costs the read, never the session
            return None

    @staticmethod
    def with_read(d: int, why: list, rd: dict, mom, nv: int, nwhy, read: dict | None, extra: tuple | None = None) -> tuple[int, list]:
        """The view with the market read (and `extra`: the price's vote from price_vote, the Kalman trend or a CUSUM change point, as (vote, reason)) as more votes: the rule
        is AUTO v1's (at least two readings agree, none points the other way)."""
        has_read = bool(read and read.get("vote"))
        if not has_read and not extra:
            return d, why
        votes = []
        if rd["pressure"] is not None and abs(rd["pressure"]) >= V1.PRESSURE_TH:
            votes.append(1 if rd["pressure"] > 0 else -1)
        if rd["gap_pct"] is not None and abs(rd["gap_pct"]) >= V1.PARITY_TH_PCT:
            votes.append(1 if rd["gap_pct"] > 0 else -1)
        if mom is not None and abs(mom) >= V1.MOMENTUM_TH_PCT:
            votes.append(1 if mom > 0 else -1)
        if nv:
            votes.append(nv)
        why = list(why)
        if has_read:
            votes.append(read["vote"])
            why.append(f"market read P(up) {read['p_up']:.2f}" + (f": {'; '.join(read['why'][:2])}" if read.get("why") else ""))
        if extra:
            votes.append(extra[0])
            why.append(extra[1])
        return (votes[0] if len(votes) >= 2 and len(set(votes)) == 1 else 0), why

    def matches(self, s: Strategy, st: dict) -> bool:
        if st["view"] != s.view:
            return False
        if st.get("regime") == "event" and is_short_vol(s.struct):                      # no volatility sold into an event
            return False
        if s.vol != "any" and st["vol"] != s.vol:
            return False
        if s.timing == "eve" and not st["eve"]:
            return False
        return (st["near"] if s.expiry == "near" else st["next"]) is not None

    def price(self, snap, s: Strategy, st: dict, ch) -> dict | None:
        """The structure on the live board: its legs with the price each would be dealt at (a buy at the offer, a sale at the bid), R and the most it can make, per unit."""
        u, exp = st["u"], st["near"] if s.expiry == "near" else st["next"]
        chain = ch[u].get(exp)
        if not chain:
            return None
        strikes = sorted(chain)
        atm_i = min(range(len(strikes)), key=lambda i: abs(strikes[i] - st["spot"]))
        lg = legs_for(s, strikes, atm_i)
        lot = self._lot(u, exp)
        if lg is None or lot is None:
            return None
        legs, q = [], snap.get("quotes") or {}
        for side, right, k in lg:
            name = chain[k].get(right)
            bk = _book(q.get(name))
            if bk is None or bk[1] < self.min_premium(u) or (bk[1] - bk[0]) / ((bk[0] + bk[1]) / 2) > MAX_LEG_SPREAD:
                return None
            legs.append({"name": name, "side": side, "right": right, "k": k, "px": bk[1] if side > 0 else bk[0], "bid": bk[0], "ask": bk[1], "age": _num(q[name].get("age_s"))})
        worst, best = payoff_bounds([(l["side"], l["right"], l["k"], l["px"]) for l in legs])
        if not math.isfinite(worst) or worst >= 0:
            return None
        fees = sum(self.fees_fn(u, exp, l["k"], l["right"], l["side"] * lot, l["px"]) + self.fees_fn(u, exp, l["k"], l["right"], -l["side"] * lot, l["px"]) for l in legs) / lot
        if fees > MAX_FEES_R * (-worst + fees):
            return None
        return {"legs": legs, "exp": exp, "lot": lot, "risk": -worst + fees, "best": best, "fees": fees}

    def mark(self, snap, legs) -> float | None:
        """What closing the structure now would get, per unit (a long sold at the bid, a short bought back at the offer), less what it cost to open."""
        q, v = snap.get("quotes") or {}, 0.0
        for l in legs:
            bk = _book(q.get(l["name"]))
            if bk is None:
                return None
            v += l["side"] * ((bk[0] if l["side"] > 0 else bk[1]) - l["px"])
        return v

    def _exit_why(self, s: Strategy, pnl_r: float, best_r: float, opened: dt.datetime, ist: dt.datetime, exp: dt.date, u: str | None = None) -> str | None:
        day_exit = self.window(u)[2] if u else DAY_EXIT
        if pnl_r >= min(s.tp, 0.9 * best_r if math.isfinite(best_r) else s.tp):
            return f"take-profit ({pnl_r:+.2f}R)"
        if pnl_r <= -s.sl * 0.999:
            return f"stop ({pnl_r:+.2f}R)"
        if s.hold == "day" and ist.time() >= day_exit:
            return f"a day strategy is out by {day_exit:%H:%M}"
        if s.hold == "swing" and (self._trading_days_to(opened.date(), ist.date()) >= SWING_SESSIONS or (ist.date() >= self.cal.prev_trading_day(exp) and ist.time() >= day_exit)):
            return "held its three sessions, or its expiry is next"
        return None

    # ---- the shadow book --------------------------------------------------------------------------------------------------------------------
    def shadow_step(self, snap, states: dict, ch, now: dt.datetime) -> None:
        t, ist = now.timestamp(), now.astimezone(IST)
        for key, sh in list(self.shadow.items()):                                       # exits first
            v = self.mark(snap, sh["legs"])
            if v is None:
                close = (dt.datetime.combine(ist.date(), self.window(key[1])[2]) + dt.timedelta(minutes=16)).time()
                if ist.time() >= close and sh["s"].hold == "day":                        # a day trade that cannot be marked by its segment's close is dropped, not scored
                    self.shadow.pop(key)
                continue
            r = (v - sh["fees"]) / sh["risk"]
            why = self._exit_why(sh["s"], r, sh["best_r"], sh["opened"], ist, sh["exp"], key[1])
            if why:
                self.lab.add(sh["s"].sid, r)
                self.shadow.pop(key)
                self.cool[key] = t + REENTRY_S
        for u, st in states.items():
            first, last, _ = self.window(u)
            if not (first <= ist.time() <= last):                                       # each segment's own hours
                continue
            for s in self.strategies():
                key = (s.sid, u)
                if key in self.shadow or self.cool.get(key, 0) > t or not self.matches(s, st):
                    continue
                p = self.price(snap, s, st, ch)
                if p is None or not self.tail_check(s, st, p, ist.date())[0]:
                    continue
                self.shadow[key] = {"s": s, "legs": p["legs"], "risk": p["risk"], "fees": p["fees"], "best_r": (p["best"] / p["risk"]) if math.isfinite(p["best"]) else math.inf,
                                    "opened": ist, "exp": p["exp"]}
                self.lab.today["shadow_opened"] += 1

    # ---- live --------------------------------------------------------------------------------------------------------------------------------
    def live_packages(self, account) -> dict:
        """{strategy text: {"sid", "u", "legs": {symbol: position}}} of AUTO v2's open positions (each package carries its strategy id and underlying in its strategy text)."""
        out = {}
        for sym, p in account.positions.items():
            if not self._is_mine(p.strategy):
                continue
            parts = p.strategy.split()
            if len(parts) < 4 or parts[2] not in BY_SID:
                continue
            out.setdefault(p.strategy, {"sid": parts[2], "u": parts[3], "legs": {}})["legs"][sym] = p
        return out

    # ---- the day plan, 06:00 to 09:15 ----------------------------------------------------------------------------------------------------------------
    @staticmethod
    def close_snap(snap) -> dict:
        """The board as it closed: every quote up to PLAN_MAX_AGE_S old, its age set to 0 so the pricing code reads it, and nothing older. For PLANNING ONLY: never traded on."""
        q = {}
        for name, v in (snap.get("quotes") or {}).items():
            age = _num(v.get("age_s")) if isinstance(v, dict) else None
            if age is not None and 0 <= age <= PLAN_MAX_AGE_S:
                q[name] = {**v, "age_s": 0.0}
        return {**snap, "quotes": q}

    @staticmethod
    def overnight(brief) -> tuple[float | None, str | None]:
        """The overnight markets' median move in percent (equity markets the brief lists, each signed by how India usually follows it), and a reason."""
        rows = [g for g in ((brief or {}).get("global") or []) if isinstance(g, dict) and g.get("kind") == "equity"]
        moves = sorted(float(g["change"]) * 100 * (1 if (g.get("india_prior") or 1) > 0 else -1) for g in rows if _num(g.get("change")) is not None)
        if len(moves) < 3:
            return None, None
        m = moves[len(moves) // 2] if len(moves) % 2 else (moves[len(moves) // 2 - 1] + moves[len(moves) // 2]) / 2
        return m, f"overnight markets {m:+.2f}% (median of {len(moves)})"

    def plan_state(self, cs, u, ch, now: dt.datetime, news, over: float | None, over_why: str | None, result: dict | None) -> dict | None:
        """This underlying's state for the day plan, from the closing board: the same fields as state(), without touching the live tape."""
        ist = now.astimezone(IST)
        sp = self.spot(cs, u)
        if not sp or u not in ch:
            return None
        exps = self.tradable_expiries(u, sorted(ch[u]), ist.date())
        if not exps:
            return None
        near, nxt = exps[0], (exps[1] if len(exps) > 1 else None)
        chain = ch[u][near]
        strikes = sorted(chain)
        atm_i = min(range(len(strikes)), key=lambda i: abs(strikes[i] - sp)) if strikes else None
        T = max((dt.datetime.combine(near, dt.time(15, 30), tzinfo=IST) - ist).total_seconds() / (365.25 * 86400), 0.0)
        iv = atm_iv(cs, chain, strikes, atm_i, sp, T, self.rate(u))
        fq = (cs.get("quotes") or {}).get(u + "-FUT")
        fut = V1._mid(fq) if isinstance(fq, dict) else None
        rd = V1.readings(cs, u, near, chain, ist, sp, fut)
        votes, why = [], []
        if rd["pressure"] is not None and abs(rd["pressure"]) >= V1.PRESSURE_TH:
            votes.append(1 if rd["pressure"] > 0 else -1)
            why.append(f"closing book pressure {rd['pressure']:+.2f}")
        if rd["gap_pct"] is not None and abs(rd["gap_pct"]) >= V1.PARITY_TH_PCT:
            votes.append(1 if rd["gap_pct"] > 0 else -1)
            why.append(f"options forward {rd['gap_pct']:+.2f}% against futures at the close")
        if over is not None and abs(over) >= OVERNIGHT_TH_PCT:
            votes.append(1 if over > 0 else -1)
            why.append(over_why)
        nv, nwhy, _ = self.news_vote(news, u, now.timestamp(), None, with_globals=over is None)   # the news model (no price: not scored before the open); an index already
        #                                                                                   has the overnight markets as their own vote here, so they are not counted twice
        if nv:
            votes.append(nv)
            why.append(nwhy or "news")
        d = votes[0] if len(votes) >= 2 and len(set(votes)) == 1 else 0
        view = "up" if d > 0 else "down" if d < 0 else ("flat" if not votes and (over is None or abs(over) < OVERNIGHT_TH_PCT / 2) else None)
        label = (result or {}).get("label")
        vol = "rich" if label == "rich" else "cheap" if label == "cheap" else "mid"      # the brief's results test is the only volatility reading before the open
        regime, rwhy = self.regime(u, news, None)
        if rwhy:
            why.append(rwhy)
        return {"u": u, "spot": sp, "view": view, "why": why, "mom": None, "iv": iv, "rv": None, "ratio": None, "vol": vol,
                "eve": self._trading_days_to(ist.date(), near) == 1, "near": near, "next": nxt, "regime": regime}

    def plan(self, snap, now: dt.datetime, news=None) -> dict:
        """The day plan: for each underlying, the defined-risk strategies whose pre-open context holds and whose reward to risk is PLAN_MIN_RR or better, priced on the
        closing books; ranked proven first, then by the measured expectancy, then by reward to risk. What the open will look for, with every reason written down."""
        ist = now.astimezone(IST)
        b = self.brief if isinstance(self.brief, dict) else {}
        cs = self.close_snap(snap)
        ch = V1.chains(cs, self.und, self.lots)
        over, over_why = self.overnight(b)
        results = {r.get("symbol"): r for r in (b.get("results") or []) if isinstance(r, dict)}
        watch = {w.get("symbol"): w for w in (b.get("watch") or []) if isinstance(w, dict)}
        expiring = {e.get("symbol") for e in (b.get("expiring") or []) if isinstance(e, dict)}
        macro = [m.get("name") for m in (b.get("macro") or []) if isinstance(m, dict) and m.get("name")]
        items, states, notes = [], {}, []
        for u in self.und:
            st = self.plan_state(cs, u, ch, now, news, over if u in INDEX_U else None, over_why, results.get(u))
            if st is None:
                continue
            states[u] = {"view": st["view"], "vol": st["vol"], "why": st["why"][:3]}
            cat = []
            r = results.get(u)
            if r:
                cat.append(f"results {r.get('when', '')}: options {r.get('label', '?')} against its own history"[:90])
            if u in expiring:
                cat.append("its options expire today")
            if macro and u in INDEX_U:
                cat.append("macro: " + ", ".join(macro[:2])[:80])
            for why in (watch.get(u) or {}).get("why") or []:
                if why.startswith(("in the news", "futures OI")):
                    cat.append(str(why)[:90])
            if st["view"] is None:
                continue
            found = []
            for s in self.strategies():
                if not self.matches(s, st):
                    continue
                p = self.price(cs, s, st, ch)
                if p is None or not self.tail_check(s, st, p, ist.date())[0]:
                    continue
                reward = min(s.tp * p["risk"], p["best"]) if math.isfinite(p["best"]) else s.tp * p["risk"]
                rr = reward / (s.sl * p["risk"]) if p["risk"] > 0 else 0.0
                if rr < PLAN_MIN_RR:
                    continue
                n, mean, _ = self.lab.posterior(s.sid)
                found.append({"u": u, "sid": s.sid, "what": s.describe()[:160], "view": st["view"], "vol": st["vol"], "why": st["why"][:3], "catalysts": cat[:4],
                              "rr": round(rr, 2), "risk_lot": round(s.sl * p["risk"] * p["lot"]), "reward_lot": round(reward * p["lot"]), "exp": p["exp"].isoformat(),
                              "legs": [("+" if l["side"] > 0 else "-") + l["name"] for l in p["legs"]][:4], "n": n, "mean_r": round(mean, 3),
                              "proven": n >= self.lab.min_trades(s) and mean > 0})
            found.sort(key=lambda x: (not x["proven"], -x["mean_r"], -x["rr"]))
            items += found[:PLAN_PER_U]
        items.sort(key=lambda x: (not x["proven"], -x["mean_r"], -len(x["catalysts"]), -x["rr"]))
        if not any(i["proven"] for i in items):
            notes.append(f"No candidate is proven yet: a strategy trades only after {MIN_TRADES} shadow trades with a positive record. Until then the open shadow-trades these.")
        if not b:
            notes.append("No pre-market brief yet: planned without results, macro and headline catalysts.")
        no_tail = [u for u in states if self.tail_model(u) is None]
        if no_tail:
            notes.append(f"No tail model for {', '.join(no_tail[:6])}{'...' if len(no_tail) > 6 else ''}: option sales there are not tail-checked.")
        if not (cs.get("quotes") or {}):
            notes.append("No closing prices on the board: nothing to price.")
        self.day_plan = {"built_at": ist.isoformat(timespec="minutes"), "from": "last close", "overnight_pct": None if over is None else round(over, 2),
                         "brief": b.get("session") if b else None, "states": states, "items": items[:PLAN_TOP], "notes": notes}
        return self.day_plan

    def planned(self, u: str) -> list[str]:
        """The strategies the day plan names for this underlying, best first (empty after a day boundary)."""
        dp = self.day_plan or {}
        return [i["sid"] for i in dp.get("items") or [] if i.get("u") == u]

    def decide(self, snap, account, now: dt.datetime, *, kill: bool = False, entries_blocked: str | None = None, cal=None, news=None) -> list[dict]:
        if now is None:
            return []
        t, ist = now.timestamp(), now.astimezone(IST)
        ch = V1.chains(snap, self.und, self.lots)
        states = {}
        for u in self.und:
            st = self.state(snap, u, ch, now, news)
            if st is not None:
                states[u] = st
        if ist.time() >= PLAN_FROM:
            try:
                self.evolve(ist.date())                                                    # the inventor's morning (inventor.py)
            except Exception:                                                              # noqa: BLE001 - an inventor that fails costs inventions, never the session
                pass
        self.shadow_step(snap, states, ch, now)
        if PLAN_FROM <= ist.time() < PLAN_UNTIL and t - self.plan_at >= PLAN_EVERY_S:      # before the open: plan the day from the closing books, every ten minutes
            self.plan_at = t
            try:
                self.plan(snap, now, news)
            except Exception:                                                              # noqa: BLE001 - a plan that fails costs the plan, never the session
                self.day_plan = {"built_at": ist.isoformat(timespec="minutes"), "items": [], "notes": ["the plan could not be built this time"]}
        if self.day_plan and str(self.day_plan.get("built_at", ""))[:10] != ist.date().isoformat():
            self.day_plan = None                                                           # yesterday's plan never steers today
        orders: list[dict] = []
        pk = self.live_packages(account)
        for text, pkg in pk.items():                                                    # live exits: the strategy's own
            s = BY_SID[pkg["sid"]]
            first = next(iter(pkg["legs"].values()))
            lot = max(1, first.instrument.lot_size)
            legs = [{"name": sym, "side": (1 if p.qty > 0 else -1) * max(1, round(abs(p.qty) / max(1, p.instrument.lot_size))), "right": p.instrument.right,
                     "k": p.instrument.strike, "px": p.avg_price} for sym, p in pkg["legs"].items()]           # a leg's side is its size in lots (a butterfly's body is 2)
            v = self.mark(snap, legs)
            if v is None:
                continue
            worst, best = payoff_bounds([(l["side"], l["right"], l["k"], l["px"]) for l in legs])
            fees = sum(self.fees_fn(pkg["u"], first.instrument.expiry, l["k"], l["right"], -l["side"] * lot, l["px"]) for l in legs) / lot
            risk = max(-worst, 1e-9) + fees
            r = (v - fees) / risk
            try:
                opened = dt.datetime.fromisoformat(first.opened_at).astimezone(IST)
            except (TypeError, ValueError):
                opened = ist
            why = self._exit_why(s, r, (best / risk) if math.isfinite(best) else math.inf, opened, ist, first.instrument.expiry, pkg["u"])
            if not why:
                continue
            for sym, p in sorted(pkg["legs"].items(), key=lambda kv: kv[1].qty > 0):    # sold legs bought back first: nothing is ever left uncovered
                if self.pending_exit.get(sym, 0) > t:
                    continue
                self.pending_exit[sym] = t + EXIT_RESEND_S
                orders.append({"id": self._oid(t, "x"), "side": "sell", "symbol": sym, "lots": "all", "queued_at": int(t * 1000), "_why": f"{TAG} exit: {why}"})
        if kill or entries_blocked or len(account.ledger) >= LEDGER_SOFT_LIMIT:
            return orders
        held_syms = set(account.positions)
        busy = {(pkg["sid"], pkg["u"]) for pkg in pk.values()}
        for u, st in states.items():                                                    # live entries: Thompson sampling over the strategies whose context holds
            first_t, last_t, _ = self.window(u)
            if self.backoff.get(u, 0) > t or not (first_t <= ist.time() <= last_t):    # each segment's own hours
                continue
            best = None
            for sid in self.planned(u):                                                 # the day plan first: a planned strategy whose context still holds, proven, with a positive draw
                s = BY_SID.get(sid)
                if s is None or (s.sid, u) in busy or not self.matches(s, st) or self.lab.stats.get(s.sid, [0])[0] < self.lab.min_trades(s):
                    continue
                draw = self.lab.draw(s.sid, self.rng)
                if draw > 0:
                    best = (draw, s)
                    break
            for s in self.strategies() if best is None else ():
                if (s.sid, u) in busy or not self.matches(s, st):
                    continue
                n = self.lab.stats.get(s.sid, [0])[0]
                if n < self.lab.min_trades(s):
                    continue
                draw = self.lab.draw(s.sid, self.rng)
                if draw > 0 and (best is None or draw > best[0]):
                    best = (draw, s)
            if best is None:
                continue
            s = best[1]
            p = self.price(snap, s, st, ch)
            if p is None or any(l["name"] in held_syms for l in p["legs"]):            # a contract held by anyone is not shared: every position has one owner
                continue
            ok, _, edge = self.tail_check(s, st, p, ist.date())
            if not ok:
                continue
            o = self._order(s, st, p, t, best[0])
            if edge is not None:
                o["thesis"] = (o["thesis"] + f" Tail check (EVT): {edge:+.2f}R expected to expiry.")[:1000]
            if s.sid in self.planned(u):
                o["thesis"] = (o["thesis"] + " On the day plan built before the open.")[:1000]
            orders.append(o)
            self.backoff[u] = t + ENTRY_BACKOFF_S
            self.lab.today["live_entries"] += 1
        return orders

    def _order(self, s: Strategy, st: dict, p: dict, t: float, draw: float) -> dict:
        n, total, w = self.lab.stats[s.sid][0], self.lab.stats[s.sid][1], self.lab.stats[s.sid][3]
        thesis = (f"{TAG}: {st['u']} {s.describe()}. Now: view {st['view']}" + (f" ({'; '.join(st['why'])})" if st["why"] else "")
                  + (f", implied {st['iv'] * 100:.1f}% against realized {st['rv'] * 100:.1f}%" if st["iv"] and st["rv"] else "") + (", expiry tomorrow" if st["eve"] else "")
                  + f". Shadow record {n} trades, average {total / n:+.2f}R, {w / n * 100:.0f}% won; {self.lab.posterior(s.sid)[1]:+.2f}R after sharing evidence with the other "
                  + f"{NAMES[s.struct]}s; chosen by Thompson sampling (draw {draw:+.2f}R). Risk {p['risk'] * p['lot']:.0f} rupees a lot.")
        strategy = f"{TAG} {s.sid} {st['u']}"[:60]
        ref = lambda l: {"bid": l["bid"], "ask": l["ask"], "at": int(t * 1000 - (l["age"] or 0) * 1000)}      # noqa: E731
        if len(p["legs"]) == 1 and p["legs"][0]["side"] > 0:
            l = p["legs"][0]
            limit = round(math.ceil((l["ask"] + max(3 * TICK, 0.02 * l["ask"])) / TICK - 1e-9) * TICK, 2)
            return {"id": self._oid(t, "b"), "side": "buy", "symbol": l["name"], "lots": 1, "strategy": strategy, "thesis": thesis[:1000], "limit": limit, "group": "auto2",
                    "queued_at": int(t * 1000), "ref": ref(l), "_why": f"{s.sid} draw {draw:+.2f}R"}
        net = sum(abs(l["side"]) * (math.ceil((l["ask"] + max(3 * TICK, 0.02 * l["ask"])) / TICK - 1e-9) * TICK if l["side"] > 0 else -max(l["bid"] - max(3 * TICK, 0.02 * l["bid"]), 0))
                  for l in p["legs"]) * p["lot"]
        return {"id": self._oid(t, "p"), "side": "package", "legs": [{"symbol": l["name"], "side": "buy" if l["side"] > 0 else "sell", "lots": abs(l["side"]), "ref": ref(l)}
                                                                      for l in p["legs"]],
                "strategy": strategy, "thesis": thesis[:1000], "net_limit": round(net, 2), "group": "auto2", "queued_at": int(t * 1000), "_why": f"{s.sid} draw {draw:+.2f}R"}

    # ---- keeping the record ------------------------------------------------------------------------------------------------------------------
    def load(self, relay) -> str:
        try:
            got = relay.get_lab()
            raw = got.get("lab") if isinstance(got, dict) else None
            got = json.loads(raw) if isinstance(raw, str) else {}
            stats, inv = got.get("stats"), got.get("inv")
            self.lab = Lab(stats if isinstance(stats, dict) else None, inv if isinstance(inv, dict) else None)
            self._read_w = got.get("read_w") if isinstance(got.get("read_w"), dict) else None
            if hasattr(self, "reader"):
                self.reader.restore(self._read_w)
            return f"{len(self.lab.stats)} strategies with a record"
        except Exception as e:                                                          # noqa: BLE001 - no record means starting from zero, never not trading
            return f"no record could be read ({type(e).__name__}): starting from zero"

    def save(self, relay, mono: float, force: bool = False) -> bool:
        if not (self.lab.dirty and (force or mono - self.lab_saved_at >= 120)):
            return False
        try:
            relay.put_lab(self.lab.to_json({"read_w": self.reader.export()} if hasattr(self, "reader") else None))
            self.lab.dirty, self.lab_saved_at = False, mono
            return True
        except Exception:                                                               # noqa: BLE001 - kept dirty: the next save tries again
            return False

    def summary(self) -> dict:
        """For the app's Strategy lab panel: the record's leaders, today's counts, and each underlying's state now (compact: the runner's whole state must fit the relay's cap)."""
        state = {u: [st.get("view"), st.get("vol"), st.get("ratio"), bool(st.get("eve")),
                     st["read"]["p_up"] if st.get("read") else None, "; ".join(st["read"]["why"][:2])[:120] if st.get("read") else "", st.get("event", ""),
                     st.get("hmm") or "", st.get("change") or "", st.get("trend_t"), st.get("tail") or "",
                     (st.get("news") or {}).get("p_up"), "; ".join((st.get("news") or {}).get("why") or [])[:140]]
                 for u, st in sorted(self.last_state.items())}
        cal = self.reader.calibration().get("all") if hasattr(self, "reader") else None
        ncal = self.news_scorer.calibration().get("all") if hasattr(self, "news_scorer") else None
        learnt = self.reader.learned if hasattr(self, "reader") else {}
        out = {**self.lab.summary(), "shadow_open": len(self.shadow), "state": state, "plan": self.day_plan, "read_calibration": cal, "news_calibration": ncal,
               "read_learning": {"instruments": sum(1 for v in learnt.values() if v), "outcomes": sum(learnt.values())}}
        if len(json.dumps(out, separators=(",", ":"), default=str)) > SUMMARY_SOFT_MAX:          # the relay refuses a runner state over 60,000 characters whole
            out["state"] = {u: [x if i not in (5, 6, 12) else "" for i, x in enumerate(v)] for u, v in state.items()}     # the reasons go first, the numbers stay
            if self.day_plan and len(json.dumps(out, separators=(",", ":"), default=str)) > SUMMARY_SOFT_MAX:
                out["plan"] = {**self.day_plan, "items": [{k: v for k, v in i.items() if k not in ("what", "why", "catalysts")} for i in self.day_plan.get("items") or []]}
        return out
