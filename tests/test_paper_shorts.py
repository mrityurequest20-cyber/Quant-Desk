"""Sold options in the paper desk (owner's order, 8 Nov 2026: "give yourself this freedom of selling options ... a selling option is just a hedging position").

What is allowed: a sold option only INSIDE a package whose worst case is bounded (verticals, condors, butterflies...). What is never allowed: a naked short call, a sold option whose cover
expires first (calendar), a sale of the long that covers a short, any package that risks more than the per-trade limit, or any of it while `paper.allow_short_legs` is off.
Everything here is paper money, through the REAL gate, broker, account and runner."""
import dataclasses
import datetime as dt
import json
from pathlib import Path

import pytest

from quantdesk.config import Config
from quantdesk.core.types import Instrument
from quantdesk.markets import sessions as MK
from quantdesk.paper import runner as R
from quantdesk.paper.account import Account, stress_equity
from quantdesk.paper.broker import PaperBroker
from quantdesk.paper.risk import KillSwitch, Quote, RiskGate

ROOT = Path(__file__).resolve().parents[1]
IST = MK.IST
MON = dt.datetime(2026, 11, 9, 10, 0, tzinfo=IST)
EXP = dt.date(2026, 11, 12)
LOT = 65


@pytest.fixture()
def cfg():
    return Config.load(ROOT / "config" / "quantdesk.yaml")


def make(cfg, tmp_path, on=True, capital=500_000):
    acct = Account(capital)
    gate = RiskGate(cfg, kill=KillSwitch(tmp_path / "KILL"))
    if on:
        gate.limits = dataclasses.replace(gate.limits, allow_short_legs=True)
    return PaperBroker(cfg, acct, gate), acct, gate


def opt(strike, right="PE", expiry=EXP):
    return Instrument.option("NIFTY", expiry, strike, right, LOT)


def q(bid, ask, now=MON, size=5000):
    return Quote(bid, ask, now - dt.timedelta(seconds=2), size, size)


def leg(side, inst, quote, lots=1):
    return {"side": side, "instrument": inst, "segment": "nse_fo", "qty": lots * LOT, "quote": quote}


def bull_put_spread(lots=1, short_k=24500, long_k=24400, credit=(60, 62), debit=(30, 32)):
    return [leg("sell", opt(short_k), q(*credit), lots), leg("buy", opt(long_k), q(*debit), lots)]


# ---- the switch ---------------------------------------------------------------------------------------------------------------------
def test_the_config_ships_with_selling_off_and_a_package_with_a_sale_is_refused_while_it_is_off(cfg, tmp_path):
    assert cfg.get("paper.allow_short_legs") is False
    b, acct, _ = make(cfg, tmp_path, on=False)
    d, rows = b.open_package(bull_put_spread(), "bull put spread", "support held at 24400 for an hour with falling put volume", {}, MON)
    assert not d.allowed and rows == [] and any("switched off" in r for r in d.reasons) and not acct.ledger and acct.cash == 500_000


# ---- a defined-risk package ----------------------------------------------------------------------------------------------------------
def test_a_bull_put_spread_opens_both_legs_sells_at_the_bid_buys_at_the_ask_and_books_a_credit(cfg, tmp_path):
    b, acct, _ = make(cfg, tmp_path)
    d, rows = b.open_package(bull_put_spread(), "bull put spread", "support held at 24400 for an hour with falling put volume", {}, MON)
    assert d.allowed, d.reasons
    assert [r["kind"] for r in rows] == ["sto", "buy"]                                           # the sale first: its cash pays for the purchase
    sold, bought = rows
    assert sold["price"] == 60 and bought["price"] == 32 and sold["qty"] == bought["qty"] == LOT
    assert acct.positions[opt(24500).symbol].qty == -LOT and acct.positions[opt(24400).symbol].qty == LOT
    assert acct.cash == pytest.approx(500_000 + LOT * (60 - 32) - sold["fees"] - bought["fees"])
    assert acct.verify_ledger() and sold["slip"] and bought["slip"]
    worst = stress_equity(acct.cash, acct.positions)
    assert worst == pytest.approx(500_000 - LOT * 100 + LOT * 28 - sold["fees"] - bought["fees"])      # width 100 less the credit, fees included: the most it can lose


def test_equity_values_a_sold_option_at_what_it_costs_to_buy_back(cfg, tmp_path):
    b, acct, _ = make(cfg, tmp_path)
    b.open_package(bull_put_spread(), "bull put spread", "support held at 24400 for an hour with falling put volume", {}, MON)
    marks = {opt(24500).symbol: 70.0, opt(24400).symbol: 25.0}
    assert acct.equity(marks) == pytest.approx(acct.cash - LOT * 70 + LOT * 25)


def test_a_condor_and_a_butterfly_are_allowed_and_a_wide_package_is_refused_for_its_risk(cfg, tmp_path):
    b, acct, _ = make(cfg, tmp_path)
    condor = [leg("sell", opt(24500, "PE"), q(60, 62)), leg("buy", opt(24400, "PE"), q(30, 32)), leg("sell", opt(25000, "CE"), q(55, 57)), leg("buy", opt(25100, "CE"), q(25, 27))]
    d, rows = b.open_package(condor, "iron condor", "range day expected: inside the 24500-25000 band since the open", {}, MON)
    assert d.allowed and len(rows) == 4, d.reasons
    b2, acct2, _ = make(cfg, tmp_path)
    wide = [leg("sell", opt(24500), q(60, 62)), leg("buy", opt(23500), q(2, 3))]                 # 1000 wide: 65 000 at risk, over 2.5% of 500 000
    d2, rows2 = b2.open_package(wide, "bull put spread", "support held at 24400 for an hour with falling put volume", {}, MON)
    assert not d2.allowed and rows2 == [] and any("at risk" in r for r in d2.reasons) and not acct2.ledger


def test_a_package_whose_worst_case_would_break_the_day_floor_is_refused_even_when_it_fits_the_per_trade_limit(cfg, tmp_path):
    b, acct, gate = make(cfg, tmp_path)
    gate.update(acct, {}, MON)                                          # the day starts at 500 000: today's floor is 475 000
    acct.cash = 476_000                                                 # a 4.8% loss so far today, still above the floor
    d, rows = b.open_package(bull_put_spread(), "bull put spread", "support held at 24400 for an hour with falling put volume", {}, MON)
    assert not d.allowed and rows == [] and any("floor" in r for r in d.reasons) and not any("at risk" in r for r in d.reasons), d.reasons


def test_an_uncovered_short_call_and_a_ratio_spread_and_a_calendar_are_refused(cfg, tmp_path):
    th = "a view long enough to pass the thesis rule of the desk"
    b, acct, _ = make(cfg, tmp_path)
    d, rows = b.open_package([leg("sell", opt(25000, "CE"), q(55, 57))], "naked call", th, {}, MON)
    assert not d.allowed and rows == [] and any("uncovered" in r for r in d.reasons)
    ratio = [leg("sell", opt(25000, "CE"), q(55, 57), 2), leg("buy", opt(24900, "CE"), q(90, 92), 1)]
    assert not b.open_package(ratio, "ratio", th, {}, MON)[0].allowed
    cal = [leg("sell", opt(25000, "CE", EXP), q(55, 57)), leg("buy", opt(25000, "CE", dt.date(2026, 11, 19)), q(95, 97))]      # different expiries are different groups: the near short has no cover of its own
    assert not b.open_package(cal, "calendar", th, {}, MON)[0].allowed and not acct.ledger


def test_a_calendar_with_the_cover_expiring_first_is_refused(cfg, tmp_path):
    b, acct, _ = make(cfg, tmp_path)
    th = "a view long enough to pass the thesis rule of the desk"
    cal = [leg("sell", opt(25000, "CE", dt.date(2026, 11, 19)), q(95, 97)), leg("buy", opt(25000, "CE", EXP), q(55, 57))]
    d, rows = b.open_package(cal, "calendar", th, {}, MON)
    assert not d.allowed and rows == [] and not acct.ledger


def test_a_package_that_names_a_contract_twice_or_has_no_thesis_is_refused(cfg, tmp_path):
    b, acct, _ = make(cfg, tmp_path)
    twice = [leg("sell", opt(24500), q(60, 62)), leg("buy", opt(24500), q(60, 62))]
    assert not b.open_package(twice, "x", "a view long enough to pass the thesis rule of the desk", {}, MON)[0].allowed
    assert not b.open_package(bull_put_spread(), "x", "", {}, MON)[0].allowed and not acct.ledger


def test_a_stale_or_one_sided_quote_on_any_leg_refuses_the_whole_package(cfg, tmp_path):
    b, acct, _ = make(cfg, tmp_path)
    legs = bull_put_spread()
    legs[1]["quote"] = Quote(30, 32, MON - dt.timedelta(seconds=120), 5000, 5000)
    assert not b.open_package(legs, "bull put spread", "support held at 24400 for an hour with falling put volume", {}, MON)[0].allowed and not acct.ledger
    legs = bull_put_spread()
    legs[0]["quote"] = None
    assert not b.open_package(legs, "bull put spread", "support held at 24400 for an hour with falling put volume", {}, MON)[0].allowed and not acct.ledger


def test_the_package_is_judged_at_the_prices_it_really_gets_including_size_impact(cfg, tmp_path):
    b, acct, _ = make(cfg, tmp_path)
    thin = bull_put_spread()
    thin[0]["quote"] = Quote(60, 62, MON - dt.timedelta(seconds=2), 130, 5000)             # 65 of 130 on the bid: the sale walks the book down
    d, rows = b.open_package(thin, "bull put spread", "support held at 24400 for an hour with falling put volume", {}, MON)
    assert d.allowed and rows[0]["price"] < 60 and rows[0]["slip"]["impact"] > 0


def test_a_net_limit_stops_a_package_that_would_cost_more_than_the_owner_said(cfg, tmp_path):
    b, acct, _ = make(cfg, tmp_path)
    th = "support held at 24400 for an hour with falling put volume"
    # the spread is a net credit of 28 a unit; asking for a credit of at least 40 (max debit -40) must fail, a credit of at least 20 must pass
    d, rows = b.open_package(bull_put_spread(), "bull put spread", th, {}, MON, max_debit=-40.0 * LOT)
    assert not d.allowed and rows == [] and not acct.ledger and any("limit" in r for r in d.reasons)
    d, rows = b.open_package(bull_put_spread(), "bull put spread", th, {}, MON, max_debit=-20.0 * LOT)
    assert d.allowed and len(rows) == 2


def test_all_or_nothing_a_failure_half_way_puts_everything_back(cfg, tmp_path, monkeypatch):
    b, acct, _ = make(cfg, tmp_path)
    real = acct.apply_fill
    calls = []

    def flaky(*a, **k):
        calls.append(a[0])
        if len(calls) == 2:
            raise ValueError("boom")
        return real(*a, **k)

    monkeypatch.setattr(acct, "apply_fill", flaky)
    d, rows = b.open_package(bull_put_spread(), "bull put spread", "support held at 24400 for an hour with falling put volume", {}, MON)
    assert not d.allowed and rows == [] and acct.cash == 500_000 and not acct.positions and not acct.ledger and calls == ["sto", "buy"]
    monkeypatch.undo()
    assert acct.verify_ledger()


# ---- closing ---------------------------------------------------------------------------------------------------------------------------
def opened(cfg, tmp_path):
    b, acct, gate = make(cfg, tmp_path)
    assert b.open_package(bull_put_spread(), "bull put spread", "support held at 24400 for an hour with falling put volume", {}, MON)[0].allowed
    return b, acct, gate


def test_the_long_that_covers_a_short_cannot_be_sold_first_and_the_short_can_always_be_bought_back(cfg, tmp_path):
    b, acct, _ = opened(cfg, tmp_path)
    later = MON + dt.timedelta(minutes=30)
    d, row = b.sell(opt(24400).symbol, LOT, q(30, 32, later), later)
    assert not d.allowed and row is None and any("uncovered" in r or "buy the sold option back" in r for r in d.reasons)
    d, row = b.cover(opt(24500).symbol, LOT, q(40, 42, later), later)
    assert d.allowed and row["kind"] == "btc" and row["price"] == 42 and opt(24500).symbol not in acct.positions
    d, row = b.sell(opt(24400).symbol, LOT, q(30, 32, later), later)
    assert d.allowed and not acct.positions and acct.verify_ledger()


def test_flatten_buys_back_the_sold_options_before_selling_the_longs(cfg, tmp_path):
    b, acct, _ = opened(cfg, tmp_path)
    later = MON + dt.timedelta(minutes=30)
    out = b.flatten({opt(24500).symbol: q(40, 42, later), opt(24400).symbol: q(20, 22, later)}, later, "test")
    assert all(d.allowed for d in out.values()), {k: v.reasons for k, v in out.items()} and not acct.positions
    assert [r["kind"] for r in acct.ledger[-2:]] == ["btc", "sell"]


def test_trim_with_a_sold_option_open_closes_the_whole_book_rather_than_leave_a_short_uncovered(cfg, tmp_path):
    b, acct, _ = opened(cfg, tmp_path)
    later = MON + dt.timedelta(minutes=30)
    out = b.trim({opt(24500).symbol: q(40, 42, later), opt(24400).symbol: q(20, 22, later)}, {}, later)
    assert not acct.positions and set(out) == {opt(24500).symbol, opt(24400).symbol}


def test_a_sold_option_that_expires_is_settled_at_its_intrinsic_value_with_no_stt_and_the_long_pays_out(cfg, tmp_path):
    b, acct, _ = opened(cfg, tmp_path)
    cash0 = acct.cash
    out = b.settle_expired(EXP + dt.timedelta(days=1), {"NIFTY": 24450.0}, MON + dt.timedelta(days=3, hours=5.5))
    assert not acct.positions
    short_settle = [r for r in acct.ledger if r["kind"] == "settle" and r["symbol"] == opt(24500).symbol][0]
    assert short_settle["price"] == 50 and short_settle["fees"] == 0                           # 24500 - 24450
    assert acct.cash == pytest.approx(cash0 - LOT * 50 + LOT * 0 - [r for r in acct.ledger if r["kind"] == "settle" and r["symbol"] == opt(24400).symbol][0]["fees"])
    assert acct.verify_ledger() and out


# ---- the ledger replays ------------------------------------------------------------------------------------------------------------------
def test_the_ledger_with_sold_options_replays_to_the_same_account_and_a_tampered_one_does_not(cfg, tmp_path):
    b, acct, _ = opened(cfg, tmp_path)
    again = R.load_account(R.account_json(acct))
    assert again is not None and again.cash == acct.cash and {k: v.qty for k, v in again.positions.items()} == {k: v.qty for k, v in acct.positions.items()}
    doc = json.loads(R.account_json(acct))
    doc["ledger"][0]["qty"] += 65
    with pytest.raises(ValueError, match="hash chain"):
        R.load_account(json.dumps(doc))


# ---- through the runner (what the app really sends) ----------------------------------------------------------------------------------
def snap(now=MON, quotes=None):
    d = {opt(24500).symbol: dict(bid=60.0, ask=62.0, bid_qty=5000, ask_qty=5000, ltp=61, age_s=2.0), opt(24400).symbol: dict(bid=30.0, ask=32.0, bid_qty=5000, ask_qty=5000, ltp=31, age_s=2.0)}
    d.update(quotes or {})
    return {"now": int(now.timestamp() * 1000), "quotes": d}


def package(oid="pkg-00001", now=MON, **kw):
    o = dict(id=oid, side="package", legs=[{"symbol": opt(24500).symbol, "side": "sell", "lots": 1}, {"symbol": opt(24400).symbol, "side": "buy", "lots": 1}],
             strategy="bull put spread", thesis="support held at 24400 for an hour with falling put volume", queued_at=int(now.timestamp() * 1000) - 3000)
    o.update(kw)
    return o


@pytest.fixture()
def rn(cfg, tmp_path):
    acct = Account(500_000)
    gate = RiskGate(cfg, kill=KillSwitch(tmp_path / "KILL"))
    gate.limits = dataclasses.replace(gate.limits, allow_short_legs=True)
    return R.Runner(cfg, acct, gate=gate, kill_file=tmp_path / "KILL")


def go(rn, orders, s=None, now=MON, kill=False):
    return rn.step(s or snap(now), orders, kill, now.astimezone(dt.timezone.utc))


def test_a_package_order_fills_every_leg_once_and_is_not_repeated(rn):
    res = go(rn, [package()])["results"][0]
    assert res["status"] == "filled" and len(res["fills"]) == 2 and {f["symbol"] for f in res["fills"]} == {opt(24500).symbol, opt(24400).symbol}
    assert len(rn.account.ledger) == 2 and rn.account.positions[opt(24500).symbol].qty == -LOT
    again = go(rn, [package()])["results"][0]
    assert again["status"] == "done" and len(rn.account.ledger) == 2
    assert R.done_ids(rn.account) == {"pkg-00001"} or "pkg-00001" in R.done_ids(rn.account)


@pytest.mark.parametrize("patch", [{"legs": []}, {"legs": "x"}, {"strategy": ""}, {"thesis": "short"}, {"net_limit": "a"},
                                   {"legs": [{"symbol": "NIFTY12NOV2624500PE", "side": "buy", "lots": 1}, {"symbol": "NIFTY12NOV2624500PE", "side": "sell", "lots": 1}]},
                                   {"legs": [{"symbol": opt(24500).symbol, "side": "short", "lots": 1}]}, {"legs": [{"symbol": opt(24500).symbol, "side": "buy", "lots": 0}]},
                                   {"legs": [{"symbol": opt(24500).symbol, "side": "buy", "lots": 1}] * 2}])
def test_a_malformed_package_is_invalid_and_changes_nothing(rn, patch):
    res = go(rn, [package(**patch)])["results"][0]
    assert res["status"] == "invalid" and not rn.account.ledger


def test_package_legs_are_checked_for_the_contract_the_expiry_and_the_late_session_rule(rn):
    bad = package(legs=[{"symbol": "SENSEX12NOV2680000PE", "side": "sell", "lots": 1}, {"symbol": opt(24400).symbol, "side": "buy", "lots": 1}])
    assert go(rn, [bad])["results"][0]["status"] == "refused" and not rn.account.ledger
    late = MON.replace(hour=15, minute=25)
    today = dt.date(2026, 11, 12)
    late = dt.datetime.combine(today, dt.time(15, 25), tzinfo=IST)
    res = go(rn, [package("pkg-00002", now=late)], s=snap(late), now=late)["results"][0]
    assert res["status"] == "refused" and "expires today" in res["reasons"][0] and not rn.account.ledger


def test_an_exit_order_on_a_sold_option_buys_it_back_and_its_limit_is_the_most_to_pay(rn):
    go(rn, [package()])
    later = MON + dt.timedelta(minutes=20)
    s = snap(later, {opt(24500).symbol: dict(bid=40.0, ask=42.0, bid_qty=5000, ask_qty=5000, ltp=41, age_s=1.0), opt(24400).symbol: dict(bid=20.0, ask=22.0, bid_qty=5000, ask_qty=5000, ltp=21, age_s=1.0)})
    cheap = {"id": "exit-0001", "side": "sell", "symbol": opt(24500).symbol, "lots": "all", "limit": 41.0, "queued_at": int(later.timestamp() * 1000) - 2000}
    assert go(rn, [cheap], s, later)["results"][0]["status"] == "refused" and rn.account.positions[opt(24500).symbol].qty == -LOT
    ok = {**cheap, "id": "exit-0002", "limit": 43.0}
    res = go(rn, [ok], s, later)["results"][0]
    assert res["status"] == "filled" and res["fill"]["kind"] == "btc" and opt(24500).symbol not in rn.account.positions


def test_selling_the_cover_before_the_short_is_refused_in_the_runner_too(rn):
    go(rn, [package()])
    later = MON + dt.timedelta(minutes=20)
    o = {"id": "exit-0003", "side": "sell", "symbol": opt(24400).symbol, "lots": "all", "queued_at": int(later.timestamp() * 1000) - 2000}
    res = go(rn, [o], snap(later), later)["results"][0]
    assert res["status"] == "refused" and rn.account.positions[opt(24400).symbol].qty == LOT


def test_the_runner_marks_a_sold_option_at_the_ask_and_summarises_it_with_a_negative_quantity(rn):
    go(rn, [package()])
    marks = rn.marks(snap(), MON)
    assert marks[opt(24500).symbol] == 62.0 and marks[opt(24400).symbol] == 30.0
    s = rn.summary(snap(), MON)
    short = [p for p in s["positions"] if p["symbol"] == opt(24500).symbol][0]
    assert short["lots"] == -1 and short["qty"] == -LOT and short["pnl"] == pytest.approx((62 - 60) * -LOT)


def test_an_expiring_sold_option_is_bought_back_from_15_20_and_settled_after_the_close_if_it_could_not_be(rn):
    exp = dt.datetime.combine(EXP, dt.time(10, 0), tzinfo=IST)
    s = snap(exp)
    go(rn, [package(now=exp)], s, exp)
    assert len(rn.account.positions) == 2
    t = dt.datetime.combine(EXP, dt.time(15, 21), tzinfo=IST)
    rep = go(rn, [], snap(t), t)
    assert not rn.account.positions and rep["forced"] and rep["forced"][0]["action"] == "sell expiring"
    assert [r["kind"] for r in rn.account.ledger[-2:]] == ["btc", "sell"]
    assert rn.account.verify_ledger()


def test_without_the_flag_the_runner_refuses_a_package_with_a_sale(cfg, tmp_path):
    acct = Account(500_000)
    r = R.Runner(cfg, acct, gate=RiskGate(cfg, kill=KillSwitch(tmp_path / "K")), kill_file=tmp_path / "K")
    res = go(r, [package()])["results"][0]
    assert res["status"] == "refused" and "switched off" in " ".join(res["reasons"]) and not acct.ledger
