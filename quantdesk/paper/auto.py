"""AUTO v1: the paper desk deciding for itself. PAPER MONEY ONLY, off unless the owner switches it on.

This module is a pure decision function. It reads the live board (the relay's snapshot), the news digest and the paper account, and it returns ORDERS in the same shape the owner's hand-placed
orders have. Nothing here trades: the orders go through `Runner.handle` and the risk gate exactly like a manual order, so every gate rule, the kill switch, the daily loss cap, the drawdown
halt and the size and freshness checks apply to them unchanged. It adds no trade-count limits of its own (see Limits). It has no network, no environment and no clock of its own.

What it looks for: HIGH REWARD FOR LITTLE RISK. It buys one lot of a long option, so the most it can lose is the premium, and it caps that loss at 40% of the premium with a stop; it puts NO
cap on the gain. A winner is protected by a trailing stop that arms at +80% (twice the risk) and follows 30% below the peak, so a trade that works is allowed to run for several times what it risked.
Most trades will lose their small stop; the ones that work pay for them. That is the bet, and the record will say whether it is a good one.

  Entry   at least TWO of four readings agree and none points the other way: resting bid/offer pressure around the money (calls against puts), the forward the options imply against the
          futures price (put-call parity), the index's own move over five minutes, and the tone of the recent news. Then it buys the first strike out of the money (more convexity for
          the same stop) of an expiry at least three days away (no last-day decay).
  Exit    stop at -40% of the premium; trailing stop (arms at +80%, 30% off the peak); the signals turning the other way; strong news against it (an optional day stop exists, off by default).
  Overnight   it is NOT an intraday system. Ten minutes before the close each position gets a decision: it is HELD overnight if its expiry is still at least two days off, it is not older than
          three sessions, it is above its stop, the signals do not point the other way and the news is not against it; otherwise it is sold. A held position keeps its stop and trailing stop
          in the morning. (The peak the trailing stop needs is written into the ledger, so a restart or the night forgets nothing.)
  Limits   NO cap on trades or open positions and none of its own on the day's loss: the risk gate's loss caps (2.5% a trade with fees, 5% a day, a 10% drawdown halt, the loss budget) are the bound. It only never adds to a
          contract already held, does not re-buy the same contract within five minutes of its last fill in it, waits 60 s between entries for the same index and direction, opens nothing while the account is
          stopped or halted, and stops opening at LEDGER_SOFT_LIMIT ledger rows (a storage guard: the relay holds about 960); exits are always managed.

It is NOT proven to make money: its signals are the ones the app's Flow panel logs and grades, which are "unproven" until they have a record. The point of running it is the record.
"""
from __future__ import annotations

import datetime as dt
import math

from ..markets import sessions as MK
from .runner import MONTHS, OPT_TAIL, _num

IST = MK.IST
TAG = "AUTO v1"
PRESSURE_TH, PARITY_TH_PCT, MOMENTUM_TH_PCT = 0.25, 0.05, 0.10
NEWS_TONE_TH, NEWS_WEIGHT_TH, NEWS_MAX_AGE_S = 0.35, 3.0, 2 * 3600
STOP_KEEP = 0.60                    # the stop sits at 60% of the entry premium: the risk is 40% of it (one R)
TRAIL_ARM, TRAIL_KEEP = 1.80, 0.70  # the trailing stop arms at +80% (two R) and follows 30% below the peak
PEAK_STEP = 1.05                    # a new peak is written to the ledger when it is 5% above the last written
MAX_AGE_DAYS = 3                    # sessions a position may be held
ENTRY_MIN_DAYS_TO_EXPIRY, HOLD_MIN_DAYS_TO_EXPIRY = 3, 2
# NO cap on the number of trades or open positions, and no cap of its own on the day's loss (owner, 8 Nov 2026: "do not keep any cap on the trades ... keep a cap on your losses ... if you're not making those
# percentage losses, on a daily basis, you can trade as much as you want"). The loss caps are the risk gate's (per trade 2.5% with fees, daily 5%, drawdown halt 10%, and the loss budget that bounds what can be open
# at once); AUTO adds none. The one guard kept is against ping-pong: the same contract is not bought again within REENTRY_GUARD_S of AUTO's last fill in it (quote noise around a stop, not a count).
LEDGER_SOFT_LIMIT = 800          # rows: the relay holds about 960 (deploy/cloudflare/paper.js CHUNK x MAX_CHUNKS); past it every save of the account fails, so AUTO stops OPENING (it still manages exits)
REENTRY_GUARD_S = 5 * 60
DIRECTION_BACKOFF_S = 60.0       # after any entry order for an index and direction (filled or refused), no other entry for that index and direction for this long: a spot that moves a strike must not buy a new strike every few seconds
FIRST_ENTRY_AFTER_OPEN_S, LAST_ENTRY_BEFORE_CLOSE_S, DECIDE_BEFORE_CLOSE_S = 5 * 60, 20 * 60, 10 * 60
QUOTE_MAX_AGE_S, MAX_SPREAD_PCT, RATE, MIN_PREMIUM = 15.0, 0.06, 0.065, 5.0
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
                k = float(m.group(4))
                out.setdefault(u, {}).setdefault(exp, {}).setdefault(int(k) if k.is_integer() else k, {})[m.group(5)] = name      # a currency strike has decimals
            break
    return out


def readings(snap, u, exp, chain, now: dt.datetime, spot: float, fut: float | None) -> dict:
    """The board readings for one index and expiry: pressure (-1..+1), the parity gap (% of the futures price) and the at-the-money strike. None where the board does not support a reading."""
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


def news_tone(digest, u: str, now: dt.datetime) -> tuple[float | None, float, int]:
    """(weighted tone -1..+1, total weight, stories) of the recent news that bears on index `u`: stories from the last two hours, medium or high impact, not market-move recaps and not stale
    repeats, naming `u` or naming nothing in particular (market-wide). Weight 2 for medium, 3 for high. (None, 0, 0) with nothing usable."""
    items = digest.get("items") if isinstance(digest, dict) and isinstance(digest.get("items"), list) else []
    t = now.timestamp()
    num = den = 0.0
    n = 0
    for it in items:
        if not isinstance(it, dict) or it.get("recap") is True or it.get("impact") not in ("medium", "high"):
            continue
        tone, nov = _num(it.get("tone")), _num(it.get("novelty"))
        if tone is None or not (-1 <= tone <= 1) or (nov is not None and nov < 0.3):
            continue
        try:
            ts = dt.datetime.strptime(str(it.get("ts")), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc).timestamp()
        except ValueError:
            continue
        if not (0 <= t - ts <= NEWS_MAX_AGE_S):
            continue
        syms = it.get("symbols") if isinstance(it.get("symbols"), list) else []
        if syms and u not in syms:
            continue
        w = 3.0 if it["impact"] == "high" else 2.0
        num, den, n = num + w * tone, den + w, n + 1
    return (num / den if den > 0 else None), den, n


def news_vote(digest, u: str, now: dt.datetime) -> tuple[int, str | None]:
    tone, weight, n = news_tone(digest, u, now)
    if tone is None or weight < NEWS_WEIGHT_TH or abs(tone) < NEWS_TONE_TH:
        return 0, None
    return (1 if tone > 0 else -1), f"news tone {tone:+.2f} over {n} stories"


def direction(pressure, gap_pct, momentum_pct, news_v: int = 0, news_why: str | None = None) -> tuple[int, list[str]]:
    """+1 / -1 / 0 and the reasons: at least two readings point the same way and none points the other way."""
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
    if news_v:
        votes.append(news_v)
        why.append(news_why or "news")
    if len(votes) >= 2 and len(set(votes)) == 1:
        return votes[0], why
    return 0, why


class AutoPilot:
    def __init__(self, underlyings=("NIFTY", "BANKNIFTY"), lots: dict | None = None, capital: float = 500_000.0, day_stop_frac: float | None = None):
        self.day_stop_frac = day_stop_frac                       # None = no stop of its own: the risk gate's daily loss cap applies
        self.und = tuple(underlyings)
        self.lots = dict(lots or {})
        self.capital = float(capital)
        self.tape: dict[str, list[tuple[float, float]]] = {}      # u -> [(epoch s, spot)], this process only
        self.pending_entry: dict = {}                            # contract name -> time, and (index, direction) -> time
        self.pending_exit: dict[str, float] = {}
        self.written_peak: dict[tuple, float] = {}
        self._events: list[dict] = []
        self.n = 0
        self.last_info: dict = {}

    @staticmethod
    def _is_auto(strategy) -> bool:
        return isinstance(strategy, str) and strategy.startswith(TAG)

    def drain_events(self) -> list[dict]:
        """Ledger events to append (a new peak for a held position), once each: the session writes them with `Account.record_event`."""
        out, self._events = self._events, []
        return out

    # ---- the account as the ledger tells it (the ledger is the memory: a restart or a night forgets nothing that matters) -----------------------------------------
    def day_facts(self, account, day: dt.date, marks: dict) -> dict:
        """Entries today, the last buy per index, and the day's own result: the realised result of the sales made today plus the open result of what was opened today, fees included.
        A position carried in from an earlier day is not part of today's open result (it has its own stops), but a sale of it made today is realised today; an unpriced position opened today
        counts as worth nothing. (A settlement row is not counted.)"""
        entries = 0
        last_buy: dict[str, float] = {}
        last_fill: dict[str, float] = {}
        book: dict[str, list] = {}                                  # symbol -> [qty, avg, opened_day, fees_paid_so_far]
        result = 0.0
        for r in account.ledger:
            if not self._is_auto(r.get("strategy")) or r.get("kind") not in ("buy", "sell"):
                continue
            try:
                ts = dt.datetime.fromisoformat(r["ts"]).astimezone(IST)
            except (ValueError, KeyError, TypeError):
                continue
            sym, q, p, f = r.get("symbol"), r["qty"], r["price"], r.get("fees", 0.0)
            last_fill[sym] = max(last_fill.get(sym, 0.0), ts.timestamp())
            today = ts.date() == day
            if r["kind"] == "buy":
                b = book.setdefault(sym, [0, 0.0, ts.date(), 0.0])
                b[1] = (b[1] * b[0] + p * q) / (b[0] + q)
                b[0] += q
                b[3] += f
                if today:
                    entries += 1
                    u = (r.get("instrument") or {}).get("underlying")
                    if u:
                        last_buy[u] = max(last_buy.get(u, 0.0), ts.timestamp())
            else:
                b = book.get(sym)
                if not b:
                    continue
                if today:
                    result += (p - b[1]) * q - f - (b[3] * q / b[0] if b[2] == day and b[0] else 0.0)
                b[3] -= b[3] * q / b[0] if b[0] else 0.0
                b[0] -= q
                if b[0] <= 0:
                    book.pop(sym, None)
        for sym, b in book.items():
            if b[2] != day:
                continue
            m = marks.get(sym)
            result += ((m - b[1]) * b[0] if m is not None else -b[1] * b[0]) - b[3]
        return {"entries": entries, "last_buy": last_buy, "last_fill": last_fill, "result": result}

    def own_qty(self, account) -> dict:
        """symbol -> units that AUTO itself bought and has not sold, from its own ledger fills. A position can hold more than that (the owner bought the same contract): the rest is the owner's
        and is never sold or managed here."""
        q: dict[str, int] = {}
        for r in account.ledger:
            if self._is_auto(r.get("strategy")) and r.get("kind") in ("buy", "sell") and isinstance(r.get("qty"), int):
                q[r.get("symbol")] = q.get(r.get("symbol"), 0) + (r["qty"] if r["kind"] == "buy" else -r["qty"])
        return {k: v for k, v in q.items() if v > 0}

    def _peaks(self, account) -> dict:
        out: dict[tuple, float] = {}
        for r in account.ledger:
            if r.get("kind") == "auto_peak" and isinstance(r.get("peak"), (int, float)):
                k = (r.get("symbol"), r.get("opened_at"))
                out[k] = max(out.get(k, 0.0), float(r["peak"]))
        return out

    # ---- one decision round ------------------------------------------------------------------------------------------------------------------------------------
    def decide(self, snap, account, now: dt.datetime, *, kill: bool = False, entries_blocked: str | None = None, cal=None, news=None) -> list[dict]:
        """Orders to hand to `Runner.step` this cycle (maybe none). `now` is the relay's time (UTC-aware); `cal` the session calendar (MK.Calendars) so a closed day proposes nothing;
        `news` the relay's news digest (or None)."""
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
                if tape and abs(t - tape[-1][0]) > 900:                                          # a clock that jumped (a forged or broken snapshot time): start the tape again
                    tape.clear()
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
        stopped = self.day_stop_frac is not None and facts["result"] <= -self.day_stop_frac * self.capital
        deciding = sess[1] - ist <= dt.timedelta(seconds=DECIDE_BEFORE_CLOSE_S)
        mine_qty = self.own_qty(account)
        ours = {s: p for s, p in account.positions.items() if self._is_auto(p.strategy) and mine_qty.get(s, 0) > 0}
        ch = chains(snap, self.und, self.lots)
        peaks = self._peaks(account)
        dirs: dict[str, int] = {}
        for u in self.und:
            d, why, rd, mom, nv = self._dir_of(snap, u, ist, t, ch, news, now)
            dirs[u] = d
            info["u"][u] = {"dir": d, "pressure": rd.get("pressure") if rd else None, "gap_pct": rd.get("gap_pct") if rd else None, "mom_pct": mom, "news": nv}
        for s, pos in ours.items():                                                          # ---- positions first
            u, want = pos.instrument.underlying, (1 if pos.instrument.right == "CE" else -1)
            mark = marks.get(s)
            key = (s, pos.opened_at)
            peak = max(peaks.get(key, pos.avg_price), self.written_peak.get(key, 0.0), pos.avg_price, mark or 0.0)
            if mark is not None and mark > pos.avg_price and mark >= max(peaks.get(key, 0.0), self.written_peak.get(key, 0.0)) * PEAK_STEP:
                self.written_peak[key] = mark
                self._events.append({"kind": "auto_peak", "symbol": s, "opened_at": pos.opened_at, "peak": round(mark, 2)})
            tone, weight, _ = news_tone(news, u, now)
            news_against = tone is not None and weight >= NEWS_WEIGHT_TH and tone * want <= -NEWS_TONE_TH
            reason = None
            if stopped and self._opened_today(pos, ist.date()):
                reason = f"the day's own stop (down {self.day_stop_frac:.1%} of capital)"
            elif mark is not None and mark <= pos.avg_price * STOP_KEEP:
                reason = f"stop loss at -40% of the premium (bid {mark:g} against {pos.avg_price:g})"
            elif mark is not None and peak >= pos.avg_price * TRAIL_ARM and mark <= peak * TRAIL_KEEP:
                reason = f"trailing stop (bid {mark:g}, peak {peak:g}, {(mark / pos.avg_price - 1) * 100:+.0f}% on the premium)"
            elif dirs.get(u) == -want:
                reason = "the signals turned the other way"
            elif news_against:
                reason = f"the news turned against it (tone {tone:+.2f})"
            elif deciding:
                reason = self._overnight_no(pos, mark, ist.date(), tone, weight, want)
            if reason and t - self.pending_exit.get(s, 0.0) >= EXIT_RESEND_S:
                self.pending_exit[s] = t
                lots = max(1, min(mine_qty[s], pos.qty) // max(1, pos.instrument.lot_size))                  # only the lots AUTO itself bought, never "all"
                orders.append({"id": self._oid(t, "x"), "side": "sell", "symbol": s, "lots": lots, "queued_at": int(t * 1000), "group": "auto", "_why": reason})
            elif deciding and not reason:
                info.setdefault("held_overnight", []).append(s)
        if account.day_halted or account.halt:
            info["entries"] = "none: the account is stopped for the day or halted by the drawdown limit"
            return orders
        if len(account.ledger) >= LEDGER_SOFT_LIMIT:
            info["entries"] = f"none: the ledger holds {len(account.ledger)} rows, near what the relay can store ({LEDGER_SOFT_LIMIT} is the limit for new entries)"
            return orders
        if stopped or deciding or kill or entries_blocked:
            return orders
        open_after = sess[0] + dt.timedelta(seconds=FIRST_ENTRY_AFTER_OPEN_S)
        last_entry = sess[1] - dt.timedelta(seconds=LAST_ENTRY_BEFORE_CLOSE_S)
        if not (open_after <= ist < last_entry):
            return orders
        for u in self.und:
            d = dirs.get(u, 0)
            if d == 0 or u not in ch:
                continue
            _, why, _, _, _ = self._dir_of(snap, u, ist, t, ch, news, now)
            o = self._entry(snap, u, d, why, ch[u], ist, t)
            if not o or o["symbol"] in account.positions:                                      # a contract already held (by the owner or by AUTO) is never added to
                continue
            if t - self.pending_entry.get(o["symbol"], 0.0) < ENTRY_PENDING_S or t - facts["last_fill"].get(o["symbol"], 0.0) < REENTRY_GUARD_S:
                continue                                                                       # an order still in flight, or the same contract traded a moment ago
            if t - self.pending_entry.get((u, d), 0.0) < DIRECTION_BACKOFF_S:
                continue                                                                       # the same index and direction was just tried: no new strike every few seconds
            self.pending_entry[o["symbol"]] = t
            self.pending_entry[(u, d)] = t
            orders.append(o)
        return orders

    # ---- pieces ---------------------------------------------------------------------------------------------------------------------------------------------
    @staticmethod
    def _opened_today(pos, day: dt.date) -> bool:
        try:
            return dt.datetime.fromisoformat(pos.opened_at).astimezone(IST).date() == day
        except (ValueError, TypeError):
            return True                                                                        # unreadable: treat it as today's (the stricter way)

    @staticmethod
    def _overnight_no(pos, mark, today: dt.date, tone, weight, want) -> str | None:
        """Why this position should NOT be kept overnight (None = keep it). Called ten minutes before the close."""
        exp = pos.instrument.expiry
        if exp is None or (exp - today).days < HOLD_MIN_DAYS_TO_EXPIRY:
            return "expiry is too close to hold overnight (decay and expiry-day risk)"
        try:
            age = (today - dt.datetime.fromisoformat(pos.opened_at).astimezone(IST).date()).days
        except (ValueError, TypeError):
            return "its opening time is unreadable: not carried"
        if age >= MAX_AGE_DAYS:
            return f"held {age} sessions already: time limit"
        if mark is None:
            return "no usable price to judge it by: not carried overnight"
        if mark < pos.avg_price * 0.75:
            return "well under its entry at the close: the idea is failing, not carried"
        return None

    def _oid(self, t: float, kind: str) -> str:
        self.n += 1
        return f"auto-{kind}-{int(t)}-{self.n}"

    def _momentum(self, u: str, t: float) -> float | None:
        tape = self.tape.get(u) or []
        if len(tape) < 2:
            return None
        past = [x for x in tape if x[0] <= t - MOMENTUM_WINDOW_S]
        return (tape[-1][1] / past[-1][1] - 1) * 100 if past else None

    @staticmethod
    def _pick_expiry(exps, today):
        ok = sorted(e for e in exps if (e - today).days >= ENTRY_MIN_DAYS_TO_EXPIRY)
        return ok[0] if ok else None

    def _dir_of(self, snap, u, ist, t, ch, news, now):
        sp = _spot(snap, u)
        mom = self._momentum(u, t)
        nv, nwhy = news_vote(news, u, now)
        if not sp or u not in ch:
            return 0, [], None, mom, nv
        exp = self._pick_expiry(ch[u], ist.date())
        if exp is None:
            return 0, [], None, mom, nv
        fq = (snap.get("quotes") or {}).get(u + "-FUT")
        age = _num(fq.get("age_s")) if isinstance(fq, dict) else None
        fut = _mid(fq) if isinstance(fq, dict) and age is not None and 0 <= age <= 60 else None
        rd = readings(snap, u, exp, ch[u][exp], ist, sp, fut)
        d, why = direction(rd["pressure"], rd["gap_pct"], mom, nv, nwhy)
        return d, why, rd, mom, nv

    def _entry(self, snap, u, d, why, by_exp, ist, t):
        exp = self._pick_expiry(by_exp, ist.date())
        chain = by_exp.get(exp) if exp else None
        sp = _spot(snap, u)
        if not sp or not chain:
            return None
        ks = sorted(chain)
        at = min(range(len(ks)), key=lambda i: abs(ks[i] - sp))
        side = "CE" if d > 0 else "PE"
        i = min(max(at + (1 if d > 0 else -1), 0), len(ks) - 1)                              # the first strike out of the money: more convexity for the same stop
        k = ks[i]
        name = chain[k].get(side)
        q = (snap.get("quotes") or {}).get(name)
        if not isinstance(q, dict):
            return None
        age, bid, ask = _num(q.get("age_s")), _num(q.get("bid")), _num(q.get("ask"))
        if None in (age, bid, ask) or not (0 <= age <= QUOTE_MAX_AGE_S) or not (0 < bid <= ask) or ask < MIN_PREMIUM or (ask - bid) / ((ask + bid) / 2) > MAX_SPREAD_PCT:
            return None
        limit = round(math.ceil((ask + max(3 * TICK, 0.02 * ask)) / TICK - 1e-9) * TICK, 2)
        thesis = (f"{TAG}: {u} {'up' if d > 0 else 'down'}: " + "; ".join(why) + f". Buys the {k} {side} ({exp:%d %b}). Risk: a stop at -40% of the premium; reward: uncapped, "
                  "a trailing stop arms at +80% and follows 30% below the peak. Held overnight only if the idea is intact, the news is not against it and expiry is far enough.")
        return {"id": self._oid(t, "b"), "side": "buy", "symbol": name, "lots": 1, "strategy": f"{TAG} {u} {'long call' if d > 0 else 'long put'}"[:60], "thesis": thesis[:1000],
                "limit": limit, "group": "auto", "queued_at": int(t * 1000), "ref": {"bid": bid, "ask": ask, "at": int(t * 1000 - age * 1000)}}
