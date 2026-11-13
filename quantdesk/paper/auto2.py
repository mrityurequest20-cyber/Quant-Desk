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
from dataclasses import dataclass

from ..markets import sessions as MK
from . import auto as V1
from .runner import _num

IST = MK.IST
TAG = "AUTO v2"
RATE = V1.RATE
TICK = 0.05

# ---- the knobs ------------------------------------------------------------------------------------------------------------------------------
RICH, CHEAP = 1.25, 0.85                 # implied over realized volatility: rich at or above, cheap at or below
CALM_PCT = 0.10                          # flat: no direction, and the five-minute move under this
RV_WINDOW_S, RV_STEP_S, RV_MIN_POINTS = 3600, 60, 20      # realized volatility: one-minute returns over the last hour, at least twenty of them
QUOTE_MAX_AGE_S, MAX_LEG_SPREAD = 30.0, 0.10              # every leg needs a two-sided book this fresh, no wider than this (of its mid)
MIN_PREMIUM = 1.0                        # a leg priced below this is not traded (ticks dominate)
REENTRY_S = 15 * 60                      # a strategy waits this long on an underlying after a shadow trade closes (correlated copies of one trade are not evidence)
MIN_TRADES = 8                           # shadow trades a strategy needs before it may trade with paper money
PRIOR_N, PRIOR_SD = 5.0, 1.0             # shrinkage: a short record is pulled towards zero
ENTRY_BACKOFF_S = 60.0                   # after a live entry on an underlying (filled or not), the next waits this long
EXIT_RESEND_S = 15.0
DAY_EXIT = dt.time(15, 15)               # "day" strategies are out by here
FIRST_ENTRY = dt.time(9, 20)             # no entries in the opening auction's aftermath
LAST_ENTRY = dt.time(15, 0)
SWING_SESSIONS = 3
LEDGER_SOFT_LIMIT = V1.LEDGER_SOFT_LIMIT
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
}
NAMES = {"LC": "long call", "BCS": "bull call spread", "BPS": "bull put spread", "LP": "long put", "BRP": "bear put spread", "BRC": "bear call spread",
         "IC": "iron condor", "IF": "iron butterfly", "LS": "long straddle", "LG": "long strangle"}
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


OFFSETS = {"0": (0, 0), "1": (1, 0), "-1": (-1, 0), "w": (0, 1), "-w": (0, -1), "2w": (0, 2), "-2w": (0, -2), "-1-w": (-1, -1), "1+w": (1, 1)}      # (strikes, widths)


def _offset(expr: str, w: int) -> int:
    a, b = OFFSETS[expr]
    return a + b * w


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


def atm_iv(snap, chain, strikes, atm_i, spot, T) -> float | None:
    """The at-the-money implied volatility: the mean of the call's and the put's, each from the mid of its book."""
    if not (T > 0) or atm_i is None:
        return None
    k, ivs = strikes[atm_i], []
    for right in ("CE", "PE"):
        bk = _book((snap.get("quotes") or {}).get(chain[k].get(right)))
        if bk:
            iv = implied_vol((bk[0] + bk[1]) / 2, spot, k, T, RATE, right)
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
    """Each strategy's shadow record: [n, sum of R, sum of R squared, wins]. Pooled over underlyings (a strategy is a rule, not a stock)."""

    def __init__(self, stats: dict | None = None):
        self.stats: dict[str, list] = {}
        for sid, v in (stats or {}).items():
            if sid in BY_SID and isinstance(v, list) and len(v) == 4 and all(isinstance(x, (int, float)) and math.isfinite(x) for x in v) and v[0] >= 0:
                self.stats[sid] = [int(v[0]), float(v[1]), float(v[2]), int(v[3])]
        self.dirty = False
        self.today = {"shadow_opened": 0, "shadow_closed": 0, "live_entries": 0}

    def add(self, sid: str, r: float) -> None:
        n, s, ss, w = self.stats.get(sid, [0, 0.0, 0.0, 0])
        r = max(-5.0, min(10.0, r))                                            # a bad quote cannot write a record of +500R
        self.stats[sid] = [n + 1, s + r, ss + r * r, w + (1 if r > 0 else 0)]
        self.dirty = True
        self.today["shadow_closed"] += 1

    def posterior(self, sid: str) -> tuple[int, float, float]:
        """(n, shrunk mean R, standard error of it)."""
        n, s, ss, _ = self.stats.get(sid, [0, 0.0, 0.0, 0])
        mean = s / (n + PRIOR_N)
        sd = math.sqrt(max((ss - s * s / n) / (n - 1), 1e-6)) if n >= 2 else PRIOR_SD
        return n, mean, sd / math.sqrt(n + PRIOR_N)

    def draw(self, sid: str, rng: random.Random) -> float:
        n, mean, se = self.posterior(sid)
        return rng.gauss(mean, se)

    def to_json(self) -> str:
        items = sorted(self.stats.items(), key=lambda kv: -kv[1][0])
        out = {}
        for sid, v in items:                                                    # the busiest records first: if the cap is ever reached, the thinnest are the ones left out
            out[sid] = [v[0], round(v[1], 4), round(v[2], 4), v[3]]
            if len(json.dumps(out)) > LAB_MAX_CHARS:
                out.pop(sid)
                break
        return json.dumps({"v": 1, "stats": out}, separators=(",", ":"))

    def summary(self, top: int = 12) -> dict:
        rows = []
        for sid, (n, s, ss, w) in self.stats.items():
            if n:
                _, mean, se = self.posterior(sid)
                rows.append({"sid": sid, "what": BY_SID[sid].describe(), "n": n, "mean_r": round(s / n, 3), "shrunk_r": round(mean, 3), "win": round(w / n, 3),
                             "live": n >= MIN_TRADES and mean > 0})
        rows.sort(key=lambda r: (-r["shrunk_r"], -r["n"]))
        return {"strategies": len(CATALOGUE), "tested": len(rows), "trades": sum(r["n"] for r in rows), "eligible": sum(1 for r in rows if r["live"]),
                "min_trades": MIN_TRADES, "today": dict(self.today), "top": rows[:top], "worst": sorted(rows, key=lambda r: r["shrunk_r"])[:3]}


# ---- the engine -----------------------------------------------------------------------------------------------------------------------------
class AutoPilotV2:
    def __init__(self, underlyings, lots: dict, fees_fn, cal, capital: float = 500_000.0, seed: int | None = None, lab: Lab | None = None):
        self.und = tuple(underlyings)
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

    def state(self, snap, u, ch, now: dt.datetime, news) -> dict | None:
        """This underlying's market state, or None when the board cannot say."""
        t, ist = now.timestamp(), now.astimezone(IST)
        sp = V1._spot(snap, u)
        if not sp or u not in ch:
            return None
        self._tape(u, t, sp)
        exps = sorted(e for e in ch[u] if e > ist.date() or (e == ist.date() and ist.time() < dt.time(15, 0)))
        exps = [e for e in exps if e > ist.date()]                                       # never open on an expiry day's own contracts
        if not exps:
            return None
        near, nxt = exps[0], (exps[1] if len(exps) > 1 else None)
        chain = ch[u][near]
        strikes = sorted(chain)
        atm_i = min(range(len(strikes)), key=lambda i: abs(strikes[i] - sp)) if strikes else None
        T = max((dt.datetime.combine(near, dt.time(15, 30), tzinfo=IST) - ist).total_seconds() / (365.25 * 86400), 0.0)
        iv = atm_iv(snap, chain, strikes, atm_i, sp, T)
        rv = realized_vol(self.tape.get(u, []), t)
        fq = (snap.get("quotes") or {}).get(u + "-FUT")
        fut = V1._mid(fq) if isinstance(fq, dict) and (_num(fq.get("age_s")) or 1e9) <= 60 else None
        rd = V1.readings(snap, u, near, chain, ist, sp, fut)
        mom = self._momentum(u, t)
        nv, nwhy = V1.news_vote(news, u, now)
        d, why = V1.direction(rd["pressure"], rd["gap_pct"], mom, nv, nwhy)
        view = "up" if d > 0 else "down" if d < 0 else ("flat" if mom is not None and abs(mom) < CALM_PCT else None)
        ratio = iv / rv if iv and rv else None
        vol = "rich" if ratio is not None and ratio >= RICH else "cheap" if ratio is not None and ratio <= CHEAP else "mid"
        eve = self._trading_days_to(ist.date(), near) == 1
        st = {"u": u, "spot": sp, "view": view, "why": why, "mom": mom, "iv": iv, "rv": rv, "ratio": ratio, "vol": vol, "eve": eve, "near": near, "next": nxt}
        self.last_state[u] = {k: (round(v, 4) if isinstance(v, float) else (v.isoformat() if isinstance(v, dt.date) else v)) for k, v in st.items() if k != "why"}
        return st

    def matches(self, s: Strategy, st: dict) -> bool:
        if st["view"] != s.view:
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
            if bk is None or bk[1] < MIN_PREMIUM or (bk[1] - bk[0]) / ((bk[0] + bk[1]) / 2) > MAX_LEG_SPREAD:
                return None
            legs.append({"name": name, "side": side, "right": right, "k": k, "px": bk[1] if side > 0 else bk[0], "bid": bk[0], "ask": bk[1], "age": _num(q[name].get("age_s"))})
        worst, best = payoff_bounds([(l["side"], l["right"], l["k"], l["px"]) for l in legs])
        if not math.isfinite(worst) or worst >= 0:
            return None
        fees = sum(self.fees_fn(u, exp, l["k"], l["right"], l["side"] * lot, l["px"]) + self.fees_fn(u, exp, l["k"], l["right"], -l["side"] * lot, l["px"]) for l in legs) / lot
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

    def _exit_why(self, s: Strategy, pnl_r: float, best_r: float, opened: dt.datetime, ist: dt.datetime, exp: dt.date) -> str | None:
        if pnl_r >= min(s.tp, 0.9 * best_r if math.isfinite(best_r) else s.tp):
            return f"take-profit ({pnl_r:+.2f}R)"
        if pnl_r <= -s.sl * 0.999:
            return f"stop ({pnl_r:+.2f}R)"
        if s.hold == "day" and ist.time() >= DAY_EXIT:
            return "a day strategy is out by 15:15"
        if s.hold == "swing" and (self._trading_days_to(opened.date(), ist.date()) >= SWING_SESSIONS or (ist.date() >= self.cal.prev_trading_day(exp) and ist.time() >= DAY_EXIT)):
            return "held its three sessions, or its expiry is next"
        return None

    # ---- the shadow book --------------------------------------------------------------------------------------------------------------------
    def shadow_step(self, snap, states: dict, ch, now: dt.datetime) -> None:
        t, ist = now.timestamp(), now.astimezone(IST)
        for key, sh in list(self.shadow.items()):                                       # exits first
            v = self.mark(snap, sh["legs"])
            if v is None:
                if ist.time() >= dt.time(15, 31) and sh["s"].hold == "day":             # a day trade that cannot be marked by the close is dropped, not scored
                    self.shadow.pop(key)
                continue
            r = (v - sh["fees"]) / sh["risk"]
            why = self._exit_why(sh["s"], r, sh["best_r"], sh["opened"], ist, sh["exp"])
            if why:
                self.lab.add(sh["s"].sid, r)
                self.shadow.pop(key)
                self.cool[key] = t + REENTRY_S
        if not (FIRST_ENTRY <= ist.time() <= LAST_ENTRY):
            return
        for u, st in states.items():
            for s in CATALOGUE:
                key = (s.sid, u)
                if key in self.shadow or self.cool.get(key, 0) > t or not self.matches(s, st):
                    continue
                p = self.price(snap, s, st, ch)
                if p is None:
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
        sp = V1._spot(cs, u)
        if not sp or u not in ch:
            return None
        exps = [e for e in sorted(ch[u]) if e > ist.date()]
        if not exps:
            return None
        near, nxt = exps[0], (exps[1] if len(exps) > 1 else None)
        chain = ch[u][near]
        strikes = sorted(chain)
        atm_i = min(range(len(strikes)), key=lambda i: abs(strikes[i] - sp)) if strikes else None
        T = max((dt.datetime.combine(near, dt.time(15, 30), tzinfo=IST) - ist).total_seconds() / (365.25 * 86400), 0.0)
        iv = atm_iv(cs, chain, strikes, atm_i, sp, T)
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
        nv, nwhy = V1.news_vote(news, u, now)
        if nv:
            votes.append(nv)
            why.append(nwhy or "news")
        d = votes[0] if len(votes) >= 2 and len(set(votes)) == 1 else 0
        view = "up" if d > 0 else "down" if d < 0 else ("flat" if not votes and (over is None or abs(over) < OVERNIGHT_TH_PCT / 2) else None)
        label = (result or {}).get("label")
        vol = "rich" if label == "rich" else "cheap" if label == "cheap" else "mid"      # the brief's results test is the only volatility reading before the open
        return {"u": u, "spot": sp, "view": view, "why": why, "mom": None, "iv": iv, "rv": None, "ratio": None, "vol": vol,
                "eve": self._trading_days_to(ist.date(), near) == 1, "near": near, "next": nxt}

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
            for s in CATALOGUE:
                if not self.matches(s, st):
                    continue
                p = self.price(cs, s, st, ch)
                if p is None:
                    continue
                reward = min(s.tp * p["risk"], p["best"]) if math.isfinite(p["best"]) else s.tp * p["risk"]
                rr = reward / (s.sl * p["risk"]) if p["risk"] > 0 else 0.0
                if rr < PLAN_MIN_RR:
                    continue
                n, mean, _ = self.lab.posterior(s.sid)
                found.append({"u": u, "sid": s.sid, "what": s.describe()[:160], "view": st["view"], "vol": st["vol"], "why": st["why"][:3], "catalysts": cat[:4],
                              "rr": round(rr, 2), "risk_lot": round(s.sl * p["risk"] * p["lot"]), "reward_lot": round(reward * p["lot"]), "exp": p["exp"].isoformat(),
                              "legs": [("+" if l["side"] > 0 else "-") + l["name"] for l in p["legs"]][:4], "n": n, "mean_r": round(mean, 3),
                              "proven": n >= MIN_TRADES and mean > 0})
            found.sort(key=lambda x: (not x["proven"], -x["mean_r"], -x["rr"]))
            items += found[:PLAN_PER_U]
        items.sort(key=lambda x: (not x["proven"], -x["mean_r"], -len(x["catalysts"]), -x["rr"]))
        if not any(i["proven"] for i in items):
            notes.append(f"No candidate is proven yet: a strategy trades only after {MIN_TRADES} shadow trades with a positive record. Until then the open shadow-trades these.")
        if not b:
            notes.append("No pre-market brief yet: planned without results, macro and headline catalysts.")
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
            legs = [{"name": sym, "side": 1 if p.qty > 0 else -1, "right": p.instrument.right, "k": p.instrument.strike, "px": p.avg_price} for sym, p in pkg["legs"].items()]
            v = self.mark(snap, legs)
            if v is None:
                continue
            first = next(iter(pkg["legs"].values()))
            lot = max(1, first.instrument.lot_size)
            worst, best = payoff_bounds([(l["side"], l["right"], l["k"], l["px"]) for l in legs])
            fees = sum(self.fees_fn(pkg["u"], first.instrument.expiry, l["k"], l["right"], -l["side"] * lot, l["px"]) for l in legs) / lot
            risk = max(-worst, 1e-9) + fees
            r = (v - fees) / risk
            try:
                opened = dt.datetime.fromisoformat(first.opened_at).astimezone(IST)
            except (TypeError, ValueError):
                opened = ist
            why = self._exit_why(s, r, (best / risk) if math.isfinite(best) else math.inf, opened, ist, first.instrument.expiry)
            if not why:
                continue
            for sym, p in sorted(pkg["legs"].items(), key=lambda kv: kv[1].qty > 0):    # sold legs bought back first: nothing is ever left uncovered
                if self.pending_exit.get(sym, 0) > t:
                    continue
                self.pending_exit[sym] = t + EXIT_RESEND_S
                orders.append({"id": self._oid(t, "x"), "side": "sell", "symbol": sym, "lots": "all", "queued_at": int(t * 1000), "_why": f"{TAG} exit: {why}"})
        if kill or entries_blocked or len(account.ledger) >= LEDGER_SOFT_LIMIT or not (FIRST_ENTRY <= ist.time() <= LAST_ENTRY):
            return orders
        held_syms = set(account.positions)
        busy = {(pkg["sid"], pkg["u"]) for pkg in pk.values()}
        for u, st in states.items():                                                    # live entries: Thompson sampling over the strategies whose context holds
            if self.backoff.get(u, 0) > t:
                continue
            best = None
            for sid in self.planned(u):                                                 # the day plan first: a planned strategy whose context still holds, proven, with a positive draw
                s = BY_SID.get(sid)
                if s is None or (s.sid, u) in busy or not self.matches(s, st) or self.lab.stats.get(s.sid, [0])[0] < MIN_TRADES:
                    continue
                draw = self.lab.draw(s.sid, self.rng)
                if draw > 0:
                    best = (draw, s)
                    break
            for s in CATALOGUE if best is None else ():
                if (s.sid, u) in busy or not self.matches(s, st):
                    continue
                n = self.lab.stats.get(s.sid, [0])[0]
                if n < MIN_TRADES:
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
            o = self._order(s, st, p, t, best[0])
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
                  + f". Shadow record {n} trades, average {total / n:+.2f}R, {w / n * 100:.0f}% won; chosen by Thompson sampling (draw {draw:+.2f}R). Risk {p['risk'] * p['lot']:.0f} rupees a lot.")
        strategy = f"{TAG} {s.sid} {st['u']}"[:60]
        ref = lambda l: {"bid": l["bid"], "ask": l["ask"], "at": int(t * 1000 - (l["age"] or 0) * 1000)}      # noqa: E731
        if len(p["legs"]) == 1 and p["legs"][0]["side"] > 0:
            l = p["legs"][0]
            limit = round(math.ceil((l["ask"] + max(3 * TICK, 0.02 * l["ask"])) / TICK - 1e-9) * TICK, 2)
            return {"id": self._oid(t, "b"), "side": "buy", "symbol": l["name"], "lots": 1, "strategy": strategy, "thesis": thesis[:1000], "limit": limit, "group": "auto2",
                    "queued_at": int(t * 1000), "ref": ref(l), "_why": f"{s.sid} draw {draw:+.2f}R"}
        net = sum((math.ceil((l["ask"] + max(3 * TICK, 0.02 * l["ask"])) / TICK - 1e-9) * TICK if l["side"] > 0 else -max(l["bid"] - max(3 * TICK, 0.02 * l["bid"]), 0)) for l in p["legs"]) * p["lot"]
        return {"id": self._oid(t, "p"), "side": "package", "legs": [{"symbol": l["name"], "side": "buy" if l["side"] > 0 else "sell", "lots": 1, "ref": ref(l)} for l in p["legs"]],
                "strategy": strategy, "thesis": thesis[:1000], "net_limit": round(net, 2), "group": "auto2", "queued_at": int(t * 1000), "_why": f"{s.sid} draw {draw:+.2f}R"}

    # ---- keeping the record ------------------------------------------------------------------------------------------------------------------
    def load(self, relay) -> str:
        try:
            got = relay.get_lab()
            raw = got.get("lab") if isinstance(got, dict) else None
            stats = json.loads(raw).get("stats") if isinstance(raw, str) else None
            self.lab = Lab(stats if isinstance(stats, dict) else None)
            return f"{len(self.lab.stats)} strategies with a record"
        except Exception as e:                                                          # noqa: BLE001 - no record means starting from zero, never not trading
            return f"no record could be read ({type(e).__name__}): starting from zero"

    def save(self, relay, mono: float, force: bool = False) -> bool:
        if not (self.lab.dirty and (force or mono - self.lab_saved_at >= 120)):
            return False
        try:
            relay.put_lab(self.lab.to_json())
            self.lab.dirty, self.lab_saved_at = False, mono
            return True
        except Exception:                                                               # noqa: BLE001 - kept dirty: the next save tries again
            return False

    def summary(self) -> dict:
        """For the app's Strategy lab panel: the record's leaders, today's counts, and each underlying's state now (compact: the runner's whole state must fit the relay's cap)."""
        state = {u: [st.get("view"), st.get("vol"), st.get("ratio"), bool(st.get("eve"))] for u, st in sorted(self.last_state.items())}
        return {**self.lab.summary(), "shadow_open": len(self.shadow), "state": state, "plan": self.day_plan}
