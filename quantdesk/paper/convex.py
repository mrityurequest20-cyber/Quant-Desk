"""The Convexity desk (owner, 14 Nov 2026). PAPER MONEY ONLY; this module decides nothing by itself, AUTO v2 (auto2.py) calls it.

The owner's words: "Direction, to be honest, is very hard to understand ... irrespective of whichever the systems you put in ... We want to have things of high risk to
reward only. We don't need to trade just mere 10%, 15% return. We are looking for the 100, 200, 300, 400, 500, 1000% return."

So this book never forecasts direction. It buys OPTIONALITY, both sides at once (a straddle, a strangle or a pair of far wings), and only when a measurable test says the
market is pricing the next move too small. A bought option makes five to ten times its price when the underlying moves much more than its price assumed; whichever way.
Buying options blindly loses (implied volatility usually stands above what follows: the insurance premium sellers earn), so each entry must pass one of four tests:

* CHEAPVOL: the options' implied move to expiry (ATM implied volatility x sqrt(T)) is at most CHEAP_RATIO of the move the fitted tail model forecasts over the same trading
  days (its EWMA daily volatility x sqrt(days), tails.py).
* EVENT: a scheduled event that touches the instrument (eventcal.py) is before the expiry, and the event-day move the options imply is at most EVENT_RATIO of what this
  instrument did on past episodes of that kind (premarket/analogs.py, weighted by today's situation, at least EVENT_MIN_NEFF effective episodes). The event's own variance
  is split out of the term structure: near and next both contain it, so sigma_n^2 T_n = s_b^2 T_n + E^2 and sigma_x^2 T_x = s_b^2 T_x + E^2. Or, unscheduled, a high
  news event touching the instrument while the options have not repriced (implied move at most STORM_IV_MAX of the forecast and no event priced in the term structure).
* TAIL: the structure's expected payoff over the fitted fat-tailed distribution (extreme value theory, tails.Model.expected_payoff) is at least TAIL_RATIO of its cost.
  This is where 500-1000% lives: far wings cost a few rupees and a normal model, which is what option prices behave like, underprices the tails a GPD fit sees.
* SQUEEZE: the last hour's realized volatility is compressed (at most SQUEEZE_RV of the daily forecast) and a fresh CUSUM change point says the price has started to move
  (volatility up, or a drift either way: the direction is not used), with the options not yet rich. Catching the breakout early.
Every structure, whatever its test, must also be worth at least EVT_FLOOR of its cost over the tail model when there is one.

Sizing and budget (the owner's choices, 14 Nov 2026): STAKE_PCT of the account a trade (the most it can lose: the premium and its fees), at most MONTH_BUDGET_PCT of the
account spent on convexity premium in a calendar month (what a month with no big winner can cost), at most MAX_OPEN packages open and one per underlying. The risk
gate's own caps (2.5% a trade, 5% a day, 10% drawdown) apply on top, unchanged.

Exits (the owner's choice: thirds): a third at +RUNG1_R (+100% of the premium), a third at +RUNG2_R (+300%), and the last third trailed: out when it gives back more than
1 - TRAIL_KEEP of its peak gain. Also out: once a scheduled event has passed (EVENT_EXIT_MIN after it: before the options' price collapses), when the options have
repriced rich (the edge is spent) before the trade has reached its first rung and while it is not losing, after MAX_HOLD_SESSIONS without the move, and on the expiry's last day. No price stop below that: the
most a trade can lose is its premium, which the stake already sizes.

Evidence: every convex strategy is traded in shadow (real bids and offers, real fees, these exits), scored in R. It trades paper money only once its family (the
structure) has MIN_POOLED shadow trades, it has MIN_OWN of its own, and its hierarchical posterior mean is above zero. R is capped at R_CAP (a bad quote cannot write
+500R); a convex record is expected to be many small losses and a few large wins, so its hit rate is not the measure, its mean R is.

NOT proven to make money. The shadow record is the evidence it builds. Standard library only (paper package rules).
"""
from __future__ import annotations

import datetime as dt
import math

STAKE_PCT = 0.005                # the owner, 14 Nov 2026: 0.5% of the account a trade
MONTH_BUDGET_PCT = 0.03          # the owner, 14 Nov 2026: 3% a month
MAX_OPEN = 3
MIN_POOLED, MIN_OWN = 20, 5
CHEAP_RATIO, RICH_RATIO = 0.80, 1.25
STORM_IV_MAX = 1.00
SQUEEZE_RV, SQUEEZE_IV_MAX = 0.60, 1.00
EVENT_RATIO, EVENT_MIN_NEFF = 0.80, 3.0
EVENT_AHEAD_SESSIONS = 2         # an event further away than this is left for later (the premium would decay waiting for it)
TAIL_RATIO, EVT_FLOOR = 1.25, 0.90
RUNG1_R, RUNG2_R = 1.0, 3.0      # +100% and +300% of the premium (for a bought structure R is its premium and fees)
TRAIL_KEEP = 0.65                # the last third keeps at least 65% of its peak gain
EVENT_EXIT_MIN = 15
MAX_HOLD_SESSIONS = 5
R_CAP = 20.0
EVERY_S = 60                     # the convex entries are looked at this often per underlying (the tail test integrates the whole distribution)
SQRT_2_PI = math.sqrt(2 / math.pi)
SQRT_252 = math.sqrt(252)

STRUCTS = {"XS": "long straddle (convexity)", "XG": "long strangle (convexity)", "XW": "long wings (convexity)"}
WIDTHS = {"XS": (0,), "XG": (1, 2), "XW": (15, 25)}          # XG: strikes out either side; XW: tenths of the forecast move to expiry (1.5 and 2.5 sd)
EDGES = ("cheapvol", "event", "tail", "squeeze")
EDGE_CODE = {"cheapvol": "v", "event": "k", "tail": "t", "squeeze": "q"}
EDGE_TEXT = {"cheapvol": "the options price less movement than the forecast",
             "event": "an event is coming that the options price too small",
             "tail": "the fat-tailed distribution values it above its price",
             "squeeze": "a quiet market has started to break out"}
MOVE_CHANGES = ("volatility up", "drift up", "drift down")


def is_convex(struct: str) -> bool:
    return struct in STRUCTS


def sid_struct(sid: str) -> str:
    """The structure code of a strategy id ("XW25.atan.3/1.s" -> "XW")."""
    head = str(sid).split(".")[0]
    return head.rstrip("0123456789")


def is_convex_text(strategy) -> bool:
    """An AUTO v2 strategy text ("AUTO v2 <sid> <underlying> ...") of a convex package."""
    parts = strategy.split() if isinstance(strategy, str) else []
    return len(parts) >= 3 and is_convex(sid_struct(parts[2]))


# ---------------------------------------------------------------------------------------------------------------- the legs
def legs(struct: str, width: int, strikes: list, atm_i: int, spot: float, sd_to_exp: float | None) -> list[tuple] | None:
    """[(lots, right, strike)] of a convex structure, every leg bought. XS: the at-the-money call and put. XG: `width` strikes out each side. XW: the first listed
    strikes beyond spot x exp(+-z sd_to_exp), z = width / 10. None when the board has no such strike."""
    if not strikes or atm_i is None:
        return None
    if struct == "XS":
        k = strikes[atm_i]
        return [(1, "CE", k), (1, "PE", k)]
    if struct == "XG":
        if atm_i + width >= len(strikes) or atm_i - width < 0:
            return None
        return [(1, "CE", strikes[atm_i + width]), (1, "PE", strikes[atm_i - width])]
    if struct == "XW":
        if not sd_to_exp or sd_to_exp <= 0 or not spot:
            return None
        z = width / 10
        kc, kp = spot * math.exp(z * sd_to_exp), spot * math.exp(-z * sd_to_exp)
        calls = [k for k in strikes if k >= kc and k > strikes[atm_i]]
        puts = [k for k in strikes if k <= kp and k < strikes[atm_i]]
        if not calls or not puts:
            return None
        return [(1, "CE", min(calls)), (1, "PE", max(puts))]
    return None


# ---------------------------------------------------------------------------------------------------------------- the tests
def vol_ratio(iv: float, T: float, daily_sd: float, days: int) -> float | None:
    """The options' move to expiry over the forecast's: (iv sqrt(T)) / (daily_sd sqrt(days)). Below 1: the options price less movement than is forecast."""
    if not (iv and iv > 0 and T and T > 0 and daily_sd and daily_sd > 0 and days and days > 0):
        return None
    return iv * math.sqrt(T) / (daily_sd * math.sqrt(days))


def event_split(iv_n: float, T_n: float, iv_x: float, T_x: float) -> tuple[float, float] | None:
    """(E, base variance a year): the event's own 1-sd log move and the volatility without it, from two expiries that both contain the event.
    sigma_n^2 T_n = s_b^2 T_n + E^2, sigma_x^2 T_x = s_b^2 T_x + E^2."""
    if not (iv_n and iv_x and T_n and T_x and 0 < T_n < T_x):
        return None
    vb = (iv_x ** 2 * T_x - iv_n ** 2 * T_n) / (T_x - T_n)
    if vb <= 0:
        vb = min(iv_n, iv_x) ** 2                                        # an inverted total variance is a bad quote, not a negative variance
    e2 = max(iv_n ** 2 * T_n - vb * T_n, 0.0)
    return math.sqrt(e2), vb


def implied_event_abs(E: float, vb: float, T_n: float, sessions_n: int) -> float:
    """The event day's expected absolute log move the options imply: an ordinary session's variance (the base variance spread over the sessions to the near expiry) plus the
    event's own, as a normal's mean absolute value."""
    day_var = vb * T_n / max(sessions_n, 1)
    return math.sqrt(day_var + E * E) * SQRT_2_PI


def hist_event_abs(analog) -> tuple[float, float] | None:
    """(weighted mean absolute move, effective episodes) from one instrument's analog of an event kind, when it rests on enough episodes."""
    if not isinstance(analog, dict):
        return None
    a, ne = analog.get("abs_w"), analog.get("n_eff")
    if not (isinstance(a, (int, float)) and a > 0 and isinstance(ne, (int, float)) and ne >= EVENT_MIN_NEFF):
        return None
    return float(a), float(ne)


def squeeze(rv_annual: float | None, daily_sd: float | None, change: str | None, ratio: float | None) -> str | None:
    """Why a squeeze is breaking out, or None: the last hour's realized volatility compressed under the daily forecast, a fresh move change point, the options not rich."""
    if not (rv_annual and daily_sd and change in MOVE_CHANGES and ratio is not None and ratio <= SQUEEZE_IV_MAX):
        return None
    comp = rv_annual / SQRT_252 / daily_sd
    if comp > SQUEEZE_RV:
        return None
    return f"the last hour moved {comp:.2f}x its daily forecast and a CUSUM change point ({change}) says it has started to move; options at {ratio:.2f}x the forecast"


# ---------------------------------------------------------------------------------------------------------------- sizing and the budget
def lots_for(stake: float, risk_per_unit: float, lot: int) -> int:
    """Whole lots whose most-can-lose (premium and fees) fits the stake."""
    if not (stake > 0 and risk_per_unit > 0 and lot > 0):
        return 0
    return int(stake // (risk_per_unit * lot))


def month_spent(ledger, month: str) -> float:
    """Rupees of premium and fees the convex book has paid this calendar month (month: "YYYY-MM"), from the account's ledger (the record, so a restart forgets nothing)."""
    tot = 0.0
    for row in ledger or []:
        if not isinstance(row, dict) or row.get("kind") != "buy" or not str(row.get("ts", "")).startswith(month) or not is_convex_text(row.get("strategy")):
            continue
        try:
            tot += float(row["qty"]) * float(row["price"]) + float(row.get("fees") or 0.0)
        except (KeyError, TypeError, ValueError):
            continue
    return tot


# ---------------------------------------------------------------------------------------------------------------- the exits
def tranches(n_lots: int) -> tuple[int, int]:
    """Lots sold at the first and second rung: thirds; two lots: one at the first rung; one lot: none (the trail alone)."""
    if n_lots >= 3:
        return n_lots // 3, n_lots // 3
    if n_lots == 2:
        return 1, 0
    return 0, 0


def exit_action(r: float, peak: float, done1: bool, done2: bool, *, now: dt.datetime, event_at: dt.datetime | None = None, rich: bool = False,
                last_day: bool = False, held_sessions: int = 0) -> tuple[str | None, str | None]:
    """(action, why): "rung1" / "rung2" (sell that third), "all" (close what is left) or None. r: the trade's R now, peak: the best R it has had."""
    if event_at is not None and now >= event_at + dt.timedelta(minutes=EVENT_EXIT_MIN):
        return "all", f"the event has passed ({event_at:%d %b %H:%M}): out before the options' price collapses ({r:+.2f}R)"
    if last_day:
        return "all", f"its expiry is next: out before the last day's decay ({r:+.2f}R)"
    if peak >= RUNG1_R and r <= TRAIL_KEEP * peak:
        return "all", f"trailed: gave back more than {1 - TRAIL_KEEP:.0%} of its +{peak:.2f}R peak ({r:+.2f}R)"
    if rich and r >= 0 and peak < RUNG1_R:
        return "all", f"the options have repriced rich before the move: the edge is spent ({r:+.2f}R)"
    if held_sessions >= MAX_HOLD_SESSIONS and peak < RUNG1_R:
        return "all", f"held {held_sessions} sessions without the move ({r:+.2f}R)"
    if r >= RUNG2_R and not done2:
        return "rung2", f"+{RUNG2_R * 100:.0f}% of the premium: the second third sold ({r:+.2f}R)"
    if r >= RUNG1_R and not done1:
        return "rung1", f"+{RUNG1_R * 100:.0f}% of the premium: the first third sold, its cost is back ({r:+.2f}R)"
    return None, None


class ShadowLadder:
    """A shadow trade's thirds: what has been banked (in R of the whole trade) and how much of it is still open."""

    def __init__(self):
        self.left, self.banked, self.done1, self.done2 = 1.0, 0.0, False, False

    def step(self, action: str | None, r: float) -> float | None:
        """Apply an exit action at R `r`; the whole trade's R once it is closed, else None."""
        if action in ("rung1", "rung2"):
            if action == "rung2" and not self.done1:                        # a jump straight past both rungs sells both thirds
                self.banked, self.left, self.done1 = self.banked + r / 3, self.left - 1 / 3, True
            self.banked, self.left = self.banked + r / 3, self.left - 1 / 3
            if action == "rung1":
                self.done1 = True
            else:
                self.done2 = True
            return None
        if action == "all":
            return self.banked + self.left * r
        return None
