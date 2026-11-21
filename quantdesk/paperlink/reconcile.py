"""Book paper fills the relay never received, as reconstructed ledger rows (audit K-01; the owner's decision of 21 Nov 2026).

On 20 Nov 2026 the relay refused the runner's state twice (the summary had outgrown its cap), and each part of the day ended with fills the relay
never held: 12 in all. The next part started from the relay's shorter copy, so the paper record lost those fills and kept 7 positions the desk had
already sold. This module puts the record right without rewriting it:

  * a PLAN (a JSON file) lists what the run logs show happened: when, which side, which contract, how much. It holds no price and no P&L.
  * each event is priced from the RECORDED market data of that moment (the recorders' public chain files), by the paper broker's own rules: a buy
    or a cover at the offer plus the modelled impact, a sale at the bid less it, fees from the desk's cost model. The price is not chosen here.
  * the rows are APPENDED to the relay's ledger (its hash chain continues; no existing row is touched), each one's thesis tagged
    "[reconstructed ...]" with the quote it was priced on, how old that quote was, and the original time.
  * it refuses unless the relay's ledger is exactly the one the plan was written against (its length and the time of its last row), so it can
    run once and only once; it refuses a quote older than the plan allows, a crossed or empty quote, and a close of a position that is not held.

Paper money only. Nothing here can reach a broker. A dry run (the default) changes nothing and prints counts and a hash only: the run logs of
this public repository never carry a price, a position or a P&L.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
from pathlib import Path

from ..paper import slippage as SL
from ..paper.account import Account, is_number
from ..paper.runner import Runner, account_json, parse_contract

SIDES = ("buy", "sto", "sell", "btc")          # buy = open long, sto = sell to open, sell = close a long, btc = buy to close a short
MAX_AGE_CAP_S = 600                            # a plan may never price on a quote older than this, whatever it asks
TAG = ("[reconstructed {made}: lost when the relay refused the runner's state (audit K-01); priced by the paper broker's rules on the recorded "
       "{source} quote of {quote_at} ({age:.0f} s before); original time {at}]")


class PlanError(ValueError):
    """A plan, a quote or the account is not what the reconciliation needs. Nothing has been changed."""


def _ts(s: str) -> dt.datetime:
    t = dt.datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    if t.tzinfo is None:
        raise PlanError(f"time {s!r} has no zone")
    return t


def load_plan(path: str | Path) -> dict:
    """A plan, checked for shape. Raises PlanError."""
    try:
        p = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise PlanError(f"the plan cannot be read ({type(e).__name__})") from None
    if not isinstance(p, dict) or not isinstance(p.get("id"), str) or not isinstance(p.get("events"), list) or not p["events"]:
        raise PlanError("a plan needs an id and a list of events")
    exp = p.get("expect")
    if not isinstance(exp, dict) or not isinstance(exp.get("ledger_len"), int) or exp["ledger_len"] < 1 or not isinstance(exp.get("last_ts"), str):
        raise PlanError("a plan must say which ledger it continues: expect.ledger_len and expect.last_ts")
    age = p.get("max_quote_age_s")
    if not (is_number(age) and 0 < age <= MAX_AGE_CAP_S):
        raise PlanError(f"max_quote_age_s must be a number above 0 and at most {MAX_AGE_CAP_S}")
    last = _ts(exp["last_ts"])
    for i, e in enumerate(p["events"]):
        if not isinstance(e, dict) or e.get("side") not in SIDES or not isinstance(e.get("symbol"), str) or not isinstance(e.get("at"), str):
            raise PlanError(f"event {i}: needs side ({'/'.join(SIDES)}), symbol and at")
        _ts(e["at"])
        book = _ts(e.get("book_at") or e["at"])
        if book < last:
            raise PlanError(f"event {i}: it would be booked at {book.isoformat()}, before the ledger's last row ({exp['last_ts']}); give it a book_at after it")
        last = book
        lots = e.get("lots")
        if e["side"] in ("buy", "sto"):
            if not (isinstance(lots, int) and not isinstance(lots, bool) and lots >= 1):
                raise PlanError(f"event {i}: an opening needs a whole number of lots")
            if not (isinstance(e.get("strategy"), str) and e["strategy"].strip() and isinstance(e.get("thesis"), str) and len(e["thesis"].strip()) >= 20):
                raise PlanError(f"event {i}: an opening needs a strategy and a thesis (20 characters or more)")
        elif lots is not None:
            raise PlanError(f"event {i}: a close takes the whole position (lots must be absent)")
    return p


class QuoteBook:
    """Recorded quotes: rows of {ts, underlying, expiry, strike, source, ce_bid, ce_ask, ce_bidq, ce_askq, pe_bid, pe_ask, pe_bidq, pe_askq}, as the
    chain recorders write them (record.yml's `*_chains.parquet`, record-stocks.yml's `*_stock_chains.parquet`)."""

    def __init__(self, rows: list[dict]):
        self.by = {}
        for r in rows:
            try:
                k = (str(r["underlying"]).upper(), str(r["expiry"])[:10], float(r["strike"]))
                t = _ts(r["ts"]) if isinstance(r["ts"], str) else r["ts"]
            except (KeyError, TypeError, ValueError, PlanError):
                continue
            self.by.setdefault(k, []).append((t, r))
        for v in self.by.values():
            v.sort(key=lambda x: x[0])

    @classmethod
    def from_parquet(cls, paths) -> "QuoteBook":
        import pandas as pd                                                       # only here: the paper package itself stays standard-library
        rows = []
        for p in paths:
            d = pd.read_parquet(p)
            d["ts"] = pd.to_datetime(d["ts"], utc=True)
            rows.extend(d.to_dict("records"))
        for r in rows:
            r["ts"] = r["ts"].to_pydatetime()
        return cls(rows)

    def quote(self, inst, at: dt.datetime):
        """(bid, ask, bid size, ask size, quote time, source) of the last record at or before `at`, or None."""
        recs = self.by.get((inst.underlying.upper(), inst.expiry.isoformat(), float(inst.strike)), [])
        best = None
        for t, r in recs:
            if t <= at:
                best = (t, r)
            else:
                break
        if best is None:
            return None
        t, r = best
        c = "ce" if inst.right == "CE" else "pe"

        def num(x):
            return float(x) if is_number(x) and not (isinstance(x, float) and math.isnan(x)) else None
        return num(r.get(f"{c}_bid")), num(r.get(f"{c}_ask")), num(r.get(f"{c}_bidq")), num(r.get(f"{c}_askq")), t, str(r.get("source") or "recorded")


def reconcile(cfg, account: Account, plan: dict, book: QuoteBook, made: str) -> list[dict]:
    """Append the plan's events to `account` as reconstructed fills. Returns what was booked (for the caller's own report). Raises PlanError, changing nothing."""
    exp = plan["expect"]
    if len(account.ledger) != exp["ledger_len"] or not account.ledger or _ts(account.ledger[-1]["ts"]) != _ts(exp["last_ts"]):
        have = account.ledger[-1]["ts"] if account.ledger else None
        raise PlanError(f"the ledger is not the one this plan continues: {len(account.ledger)} rows ending {have}, the plan expects "
                        f"{exp['ledger_len']} ending {exp['last_ts']} (already reconciled, or something changed: the owner must look)")
    if not account.verify_ledger():
        raise PlanError("the account's ledger does not verify")
    rn = Runner(cfg, account)
    snap, booked = account.snapshot(), []
    try:
        for i, e in enumerate(plan["events"]):
            inst, why = parse_contract(e["symbol"], rn.und, rn.lots, frozenset(rn.seg_of))
            if inst is None:
                raise PlanError(f"event {i} ({e['symbol']}): {why}")
            at = _ts(e["at"])
            q = book.quote(inst, at)
            if q is None:
                raise PlanError(f"event {i} ({e['symbol']}): no recorded quote at or before {e['at']}")
            bid, ask, bq, aq, qt, source = q
            age = (at - qt).total_seconds()
            if age > plan["max_quote_age_s"]:
                raise PlanError(f"event {i} ({e['symbol']}): the recorded quote is {age:.0f} s old, more than the plan's {plan['max_quote_age_s']} s")
            if not (is_number(bid) and is_number(ask) and 0 <= bid <= ask and ask > 0):
                raise PlanError(f"event {i} ({e['symbol']}): the recorded quote is empty or crossed ({bid}, {ask})")
            side = e["side"]
            pos = account.positions.get(inst.symbol)
            if side in ("sell", "btc"):
                if pos is None or (pos.qty > 0) != (side == "sell"):
                    raise PlanError(f"event {i} ({e['symbol']}): {'no long' if side == 'sell' else 'no short'} position to close")
                qty, seg = abs(pos.qty), pos.segment
            else:
                qty, seg = e["lots"] * inst.lot_size, rn.segment(inst)
            tick = rn.broker.tick_for(inst)
            buying = side in ("buy", "btc")
            imp = SL.impact_ticks(qty, aq if buying else bq) * tick         # the paper broker's own rule (broker.buy / sell / cover / open_package)
            px = round(ask + imp, 6) if buying else round(max(bid - imp, 0.0), 6)
            if side == "buy" and px <= 0 or side == "sto" and px <= 0:
                raise PlanError(f"event {i} ({e['symbol']}): an opening at a zero price is not a trade")
            fees, _ = rn.broker.costs.fees(inst, qty if buying else -qty, px, segment=seg)
            tag = TAG.format(made=made, source=source, quote_at=qt.isoformat(), age=age, at=e["at"])
            slip = SL.clean(SL.split("buy" if buying else "sell", qty, px, bid, ask, (px - ask) if buying else (bid - px)))
            if side in ("buy", "sto"):
                strategy, thesis = e["strategy"], f"{e['thesis']} {tag}"
            else:
                strategy, thesis = pos.strategy, f"{e.get('why') or 'exit'}: {pos.thesis} {tag}"
            account.apply_fill(side, inst, seg, qty, px, fees, _ts(e.get("book_at") or e["at"]).isoformat(), strategy, thesis, slip)
            booked.append({"side": side, "symbol": inst.symbol, "qty": qty, "price": px, "fees": fees, "quote_age_s": round(age, 1)})
        if not account.verify_ledger():
            raise PlanError("the reconciled ledger does not verify")
    except Exception:
        account.restore(snap)
        raise
    return booked


def digest(account: Account) -> str:
    """A short fingerprint of the saved account: safe to print in a public log (it reveals nothing about the trades)."""
    return hashlib.sha256(account_json(account).encode("utf-8")).hexdigest()[:16]
