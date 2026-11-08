"""AUTO v1: the paper desk deciding for itself. PAPER MONEY ONLY, off unless the owner switches it on.

This module is a pure decision function. It reads the live board (the relay's snapshot) and the paper account, and it returns ORDERS in the same shape the owner's hand-placed
orders have. Nothing here trades: the orders go through `Runner.handle` and the risk gate exactly like a manual order, so every gate rule, the kill switch, the daily loss cap, the
drawdown halt and the size and freshness checks apply to them unchanged. On top of that it keeps its own, tighter limits (below). It has no network, no environment and no clock of its own.

What it does (v1, deliberately small and fully explained in each order's thesis):
  * Reads three things per index: the pressure of resting bids against offers around the money in calls against puts, the forward the options imply against the futures price (put-call
    parity), and the index's own move over the last five minutes.
  * Enters only when at least TWO of the three agree on a direction and none points the other way: buys the at-the-money call (up) or put (down), ONE lot.
  * Exits on a +30% gain on the premium, a -25% loss, 25 minutes, the signal turning the other way, or ten minutes before the session closes. It never holds overnight.
  * Its own limits: at most 2 positions open, at most 6 entries a day, 20 minutes between entries on an index, and it stops for the day (and sells what it holds) once its own day's
    result is down 1% of the starting capital.

It is NOT proven to make money: these are the same signals the app's Flow panel logs and grades, which are "unproven" until they have a record. The point of running it is the record.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import math
import re

from ..markets import sessions as MK
from .runner import MONTHS, OPT_TAIL, _num

IST = MK.IST
TAG = "AUTO v1"
PRESSURE_TH, PARITY_TH_PCT, MOMENTUM_TH_PCT = 0.25, 0.05, 0.10
TAKE_PROFIT, STOP_LOSS = 1.30, 0.75
HOLD_MAX_S, COOLDOWN_S, MAX_OPEN, MAX_ENTRIES_DAY = 25 * 60, 20 * 60, 2, 6
DAY_STOP_FRAC = 0.01
FIRST_ENTRY_AFTER_OPEN_S, LAST_ENTRY_BEFORE_CLOSE_S, EXIT_BEFORE_CLOSE_S = 5 * 60, 20 * 60, 10 * 60
QUOTE_MAX_AGE_S, MAX_SPREAD_PCT, RATE = 15.0, 0.06, 0.065
TICK = 0.05
MOMENTUM_WINDOW_S = 300
EXIT_RESEND_S, ENTRY_PENDING_S = 15.0, 45.0


def _spot(snap, name):
    q = (snap.get("quotes") or {}).get(name)
    if not isinstance(q, dict):
        return None
    age, px = _num(q.get("age_s")), _num(q.get("ltp"))
    return px if px and px > 0 and age is not None and 0 <= age <= QUOTE_MAX_AGE_S else None


def _mid(q):
    b, a = _num(q.get("bid")), _num(q.get("ask"))
    return (b + a) / 2 if b and a and 0 < b <= a else None


def _expiry_close(day: dt.date) -> dt.datetime:
    return dt.datetime.combine(day, dt.time(15, 30), tzinfo=IST)


def chains(snap, underlyings, lots) -> dict:
    """{underlying: {expiry date: {strike: {"CE": name, "PE": name}}}} from the option names on the board (only the underlyings given, only names that parse)."""
    out: dict = {}
    for name in (snap.get("quotes") or {}):
        if not isinstance(name, str):
            continue
        for u in sorted(underlyings, key=len, reverse=True):
            if not name.startswith(u):
                continue
            m = OPT_TAIL.match(name[len(u):])
            if m:
                try:
                    exp = dt.date(2000 + int(m.group(3)), MONTHS.index(m.group(2)) + 1, int(m.group(1)))
                except ValueError:
                    break
                out.setdefault(u, {}).setdefault(exp, {}).setdefault(int(m.group(4)), {})[m.group(5)] = name
            break
    return out


def readings(snap, u, exp, chain, now: dt.datetime, spot: float, fut: float | None) -> dict:
    """The three readings for one index and expiry: pressure (-1..+1), the parity gap (% of the futures price) and the quotes used. None where the board does not support a reading."""
    quotes = snap.get("quotes") or {}
    ks = sorted(chain)
    if not ks:
        return {"pressure": None, "gap_pct": None, "atm": None}
    at = min(range(len(ks)), key=lambda i: abs(ks[i] - spot))
    sides = {}
    for t in ("CE", "PE"):
        b = a = 0.0
        used = 0
        for k in ks[max(0, at - 3): at + 4]:
            q = quotes.get(chain[k].get(t))
            if not isinstance(q, dict):
                continue
            age, bq, aq, bid, ask = _num(q.get("age_s")), _num(q.get("bid_qty")), _num(q.get("ask_qty")), _num(q.get("bid")), _num(q.get("ask"))
            if None in (age, bq, aq, bid, ask) or not (0 <= age <= 60) or not (0 < bid <= ask) or bq < 0 or aq < 0:
                continue
            b, a, used = b + bq, a + aq, used + 1
        sides[t] = (b - a) / (b + a) if used and b + a > 0 else None
    pressure = sides["CE"] - sides["PE"] if sides.get("CE") is not None and sides.get("PE") is not None else None
    gap = None
    if fut and fut > 0:
        T = (_expiry_close(exp) - now.astimezone(IST)).total_seconds() / (365.25 * 86400)
        fw = []
        for k in sorted(ks, key=lambda x: abs(x - spot))[:5]:
            c, p = quotes.get(chain[k].get("CE")), quotes.get(chain[k].get("PE"))
            cm, pm = (_mid(c) if isinstance(c, dict) else None), (_mid(p) if isinstance(p, dict) else None)
            if cm is not None and pm is not None and T > 0:
                fw.append(k + (cm - pm) * math.exp(RATE * T))
        if fw:
            fw.sort()
            f = fw[len(fw) // 2] if len(fw) % 2 else (fw[len(fw) // 2 - 1] + fw[len(fw) // 2]) / 2
            gap = (f - fut) / fut * 100
    return {"pressure": pressure, "gap_pct": gap, "atm": ks[at]}


def direction(pressure, gap_pct, momentum_pct) -> tuple[int, list[str]]:
    """+1 / -1 / 0 and the reasons: at least two of the three point the same way and none points the other way."""
    votes, why = [], []
    if pressure is not None and abs(pressure) >= PRESSURE_TH:
        votes.append(1 if pressure > 0 else -1)
        why.append(f"resting-size pressure {pressure:+.2f}")
    if gap_pct is not None and abs(gap_pct) >= PARITY_TH_PCT:
        votes.append(1 if gap_pct > 0 else -1)
        why.append(f"options forward {gap_pct:+.2f}% against futures")
    if momentum_pct is not None and abs(momentum_pct) >= MOMENTUM_TH_PCT:
        votes.append(1 if momentum_pct > 0 else -1)
        why.append(f"index {momentum_pct:+.2f}% in 5 min")
    if len(votes) >= 2 and len(set(votes)) == 1:
        return votes[0], why
    return 0, why


class AutoPilot:
    def __init__(self, underlyings=("NIFTY", "BANKNIFTY"), lots: dict | None = None, capital: float = 500_000.0):
        self.und = tuple(underlyings)
        self.lots = dict(lots or {})
        self.capital = float(capital)
        self.tape: dict[str, list[tuple[float, float]]] = {}      # u -> [(epoch s, spot)], this process only
        self.pending_entry: dict[str, float] = {}
        self.pending_exit: dict[str, float] = {}
        self.n = 0
        self.last_info: dict = {}

    # ---- the account as the ledger tells it (the ledger is the memory: a restart forgets nothing that matters) ------------------------------------------------
    @staticmethod
    def _is_auto(strategy) -> bool:
        return isinstance(strategy, str) and strategy.startswith(TAG)

    def day_facts(self, account, day: dt.date, marks: dict) -> dict:
        entries = 0
        last_buy: dict[str, float] = {}
        cash = 0.0
        for r in account.ledger:
            if not self._is_auto(r.get("strategy")) or r.get("kind") not in ("buy", "sell"):
                continue
            try:
                ts = dt.datetime.fromisoformat(r["ts"]).astimezone(IST)
            except (ValueError, KeyError, TypeError):
                continue
            if ts.date() != day:
                continue
            q, p, f = r["qty"], r["price"], r.get("fees", 0.0)
            if r["kind"] == "buy":
                entries += 1
                cash -= q * p + f
                u = (r.get("instrument") or {}).get("underlying")
                if u:
                    last_buy[u] = max(last_buy.get(u, 0.0), ts.timestamp())
            else:
                cash += q * p - f
        held = 0.0
        for s, pos in account.positions.items():
            if self._is_auto(pos.strategy):
                m = marks.get(s)
                held += (pos.qty * m) if m is not None else 0.0                 # an unpriced position counts as worth nothing: the stop trips rather than hides
        return {"entries": entries, "last_buy": last_buy, "result": cash + held}

    # ---- one decision round ------------------------------------------------------------------------------------------------------------------------------------
    def decide(self, snap, account, now: dt.datetime, *, kill: bool = False, entries_blocked: str | None = None, cal=None) -> list[dict]:
        """Orders to hand to `Runner.step` this cycle (maybe none). `now` is the relay's time (UTC-aware); `cal` the session calendar (MK.Calendars) so a closed day proposes nothing."""
        orders: list[dict] = []
        if now.tzinfo is None:
            return orders
        ist = now.astimezone(IST)
        t = now.timestamp()
        sess = MK.session("nse_fo", ist.date(), cal, trading=True) if cal is not None else None
        for u in self.und:
            sp = _spot(snap, u)
            if sp:
                tape = self.tape.setdefault(u, [])
                if not tape or t > tape[-1][0]:
                    tape.append((t, sp))
                del tape[:max(0, len(tape) - 400)]
        info = {"t": ist.strftime("%H:%M:%S"), "session": bool(sess and sess[0] <= ist < sess[1]), "u": {}}
        self.last_info = info
        if not sess or not (sess[0] <= ist < sess[1]):
            return orders
        marks = {}
        for s, pos in account.positions.items():
            q = (snap.get("quotes") or {}).get(s)
            age, bid = (_num(q.get("age_s")), _num(q.get("bid"))) if isinstance(q, dict) else (None, None)
            if bid and bid > 0 and age is not None and 0 <= age <= 600:
                marks[s] = bid
        facts = self.day_facts(account, ist.date(), marks)
        info["day"] = {"entries": facts["entries"], "result": round(facts["result"], 2)}
        stopped = facts["result"] <= -DAY_STOP_FRAC * self.capital
        closing = sess[1] - ist <= dt.timedelta(seconds=EXIT_BEFORE_CLOSE_S)
        ours = {s: p for s, p in account.positions.items() if self._is_auto(p.strategy)}
        for s, pos in ours.items():                                                          # ---- exits first
            mark = marks.get(s)
            reason = None
            if stopped:
                reason = "the day's own stop (down 1% of capital)"
            elif closing:
                reason = "ten minutes to the close: never held overnight"
            elif mark is not None and mark >= pos.avg_price * TAKE_PROFIT:
                reason = f"take profit (bid {mark:g} against {pos.avg_price:g})"
            elif mark is not None and mark <= pos.avg_price * STOP_LOSS:
                reason = f"stop loss (bid {mark:g} against {pos.avg_price:g})"
            else:
                try:
                    held = t - dt.datetime.fromisoformat(pos.opened_at).timestamp()
                except (ValueError, TypeError):
                    held = HOLD_MAX_S + 1
                if held >= HOLD_MAX_S:
                    reason = "25 minutes held"
                else:
                    d = info["u"].get(pos.instrument.underlying, {}).get("dir")
                    want = 1 if pos.instrument.right == "CE" else -1
                    if d is None:
                        d = self._dir_of(snap, pos.instrument.underlying, ist, t)[0]
                    if d == -want:
                        reason = "the signals turned the other way"
            if reason and t - self.pending_exit.get(s, 0.0) >= EXIT_RESEND_S:
                self.pending_exit[s] = t
                orders.append({"id": self._oid(t, "x"), "side": "sell", "symbol": s, "lots": "all", "queued_at": int(t * 1000), "group": "auto", "_why": reason})
        if stopped or closing or kill or entries_blocked:
            return orders
        open_after = sess[0] + dt.timedelta(seconds=FIRST_ENTRY_AFTER_OPEN_S)
        last_entry = sess[1] - dt.timedelta(seconds=LAST_ENTRY_BEFORE_CLOSE_S)
        if not (open_after <= ist < last_entry):
            return orders
        if len(ours) + len([1 for k, v in self.pending_entry.items() if t - v < ENTRY_PENDING_S]) >= MAX_OPEN or facts["entries"] >= MAX_ENTRIES_DAY:
            return orders
        ch = chains(snap, self.und, self.lots)
        for u in self.und:
            d, why, rd, mom = self._dir_of(snap, u, ist, t, ch)
            info["u"][u] = {"dir": d, "pressure": rd.get("pressure") if rd else None, "gap_pct": rd.get("gap_pct") if rd else None, "mom_pct": mom}
            if d == 0 or u not in ch:
                continue
            if t - facts["last_buy"].get(u, 0.0) < COOLDOWN_S or t - self.pending_entry.get(u, 0.0) < ENTRY_PENDING_S:
                continue
            if any(p.instrument.underlying == u for p in ours.values()):
                continue
            o = self._entry(snap, u, d, why, ch[u], ist, t)
            if o:
                self.pending_entry[u] = t
                orders.append(o)
                break                                                                          # one entry a cycle
        return orders

    # ---- pieces ---------------------------------------------------------------------------------------------------------------------------------------------
    def _oid(self, t: float, kind: str) -> str:
        self.n += 1
        return f"auto-{kind}-{int(t)}-{self.n}"

    def _momentum(self, u: str, t: float) -> float | None:
        tape = self.tape.get(u) or []
        if len(tape) < 2:
            return None
        past = [x for x in tape if x[0] <= t - MOMENTUM_WINDOW_S]
        return (tape[-1][1] / past[-1][1] - 1) * 100 if past else None

    def _dir_of(self, snap, u, ist, t, ch=None):
        sp = _spot(snap, u)
        if not sp:
            return 0, [], None, None
        ch = ch if ch is not None else chains(snap, self.und, self.lots)
        if u not in ch:
            return 0, [], None, self._momentum(u, t)
        today = ist.date()
        exps = sorted(e for e in ch[u] if e > today or (e == today and ist.time() < dt.time(13, 0)))
        if not exps:
            return 0, [], None, self._momentum(u, t)
        fq = (snap.get("quotes") or {}).get(u + "-FUT")
        fut = _mid(fq) if isinstance(fq, dict) and _num(fq.get("age_s")) is not None and 0 <= _num(fq.get("age_s")) <= 60 else None
        rd = readings(snap, u, exps[0], ch[u][exps[0]], ist, sp, fut)
        mom = self._momentum(u, t)
        d, why = direction(rd["pressure"], rd["gap_pct"], mom)
        return d, why, rd, mom

    def _entry(self, snap, u, d, why, by_exp, ist, t):
        today = ist.date()
        exps = sorted(e for e in by_exp if e > today or (e == today and ist.time() < dt.time(13, 0)))
        if not exps:
            return None
        chain = by_exp[exps[0]]
        sp = _spot(snap, u)
        if not sp or not chain:
            return None
        k = min(chain, key=lambda x: abs(x - sp))
        side = "CE" if d > 0 else "PE"
        name = chain[k].get(side)
        q = (snap.get("quotes") or {}).get(name)
        if not isinstance(q, dict):
            return None
        age, bid, ask = _num(q.get("age_s")), _num(q.get("bid")), _num(q.get("ask"))
        if None in (age, bid, ask) or not (0 <= age <= QUOTE_MAX_AGE_S) or not (0 < bid <= ask) or (ask - bid) / ((ask + bid) / 2) > MAX_SPREAD_PCT:
            return None
        limit = round(math.ceil((ask + max(3 * TICK, 0.02 * ask)) / TICK - 1e-9) * TICK, 2)
        thesis = f"{TAG}: {u} {'up' if d > 0 else 'down'}: " + "; ".join(why) + f". Buys the {k} {side}; exits at +30% / -25% / 25 min / signals reversing / 10 min before the close."
        return {"id": self._oid(t, "b"), "side": "buy", "symbol": name, "lots": 1, "strategy": f"{TAG} {u} {'long call' if d > 0 else 'long put'}"[:60], "thesis": thesis[:1000],
                "limit": limit, "group": "auto", "queued_at": int(t * 1000), "ref": {"bid": bid, "ask": ask, "at": int(t * 1000 - age * 1000)}}
