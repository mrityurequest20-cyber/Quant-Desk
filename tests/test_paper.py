"""The paper desk's money and brakes (quantdesk/paper): the account, the risk gate and the paper broker.

Every brake has a test that fails if the brake is removed. The owner's rule is no cap on the number of trades or open positions,
only loss caps, and that is tested too."""
import datetime as dt
import ast
import json
import math
import re
from pathlib import Path

import pytest

from quantdesk.config import Config
from quantdesk.core.types import Instrument
from quantdesk.markets import sessions as MK
from quantdesk.paper.account import Account
from quantdesk.paper.broker import PaperBroker
from quantdesk.paper.risk import KillSwitch, Limits, Order, Quote, RiskGate

np = pytest.importorskip("numpy")

ROOT = Path(__file__).resolve().parents[1]
IST = MK.IST
MON = dt.datetime(2026, 11, 9, 10, 0, tzinfo=IST)          # a Monday, an NSE trading day, inside the session
EXPIRY = dt.date(2026, 11, 12)


@pytest.fixture()
def cfg():
    return Config.load(ROOT / "config" / "quantdesk.yaml")


@pytest.fixture()
def desk(cfg, tmp_path):
    acct = Account(500_000)
    gate = RiskGate(cfg, kill=KillSwitch(tmp_path / "KILL"))
    return PaperBroker(cfg, acct, gate), acct, gate, tmp_path / "KILL"


def opt(strike=25000, right="CE", expiry=EXPIRY, lot=75, under="NIFTY"):
    return Instrument.option(under, expiry, strike, right, lot)


def quote(bid=99.0, ask=100.0, now=MON, age=2, ask_qty=None, bid_qty=None):
    return Quote(bid, ask, now - dt.timedelta(seconds=age), bid_qty, ask_qty)


def order(inst=None, qty=75, seg="nse_fo", strategy="s1", thesis="range break with rising volume, 30m"):
    return Order(inst or opt(), seg, qty, strategy, thesis)


def buy(desk, o=None, q=None, marks=None, now=MON):
    b, acct, *_ = desk
    return b.buy(o or order(), q or quote(now=now), marks if marks is not None else {s: p.avg_price for s, p in acct.positions.items()}, now)


# ---- a normal trade ----------------------------------------------------------------------------------------------------------
def test_an_allowed_entry_fills_at_the_ask_pays_fees_and_is_recorded_with_its_thesis(desk):
    d, row = buy(desk, q=quote(ask_qty=5000, bid_qty=5000))          # 75 of 5000 shown: no modelled impact
    _, acct, *_ = desk
    assert d.allowed and row["kind"] == "buy" and row["price"] == 100.0 and row["fees"] > 0
    assert acct.cash == pytest.approx(500_000 - 75 * 100.0 - row["fees"])
    pos = acct.positions[opt().symbol]
    assert pos.qty == 75 and pos.thesis == "range break with rising volume, 30m" and pos.strategy == "s1"
    assert acct.verify_ledger() and len(acct.ledger) == 1


def test_a_sell_fills_at_the_bid_and_the_round_trip_pays_the_spread_and_fees(desk):
    broker, acct, *_ = desk
    sized = quote(ask_qty=5000, bid_qty=5000)
    buy(desk, q=sized)
    d, row = broker.sell(opt().symbol, 75, sized, MON)
    assert d.allowed and row["price"] == 99.0 and opt().symbol not in acct.positions
    assert acct.cash < 500_000 and acct.realized == pytest.approx(-75.0) and acct.fees > 0          # -1 point x 75, before fees


# ---- every reason to refuse an entry --------------------------------------------------------------------------------------------
@pytest.mark.parametrize("name,kw,needle", [
    ("no thesis", dict(o=order(thesis="  ")), "thesis"),
    ("no strategy", dict(o=order(strategy="")), "thesis"),
    ("stale quote", dict(q=quote(age=31)), "old"),
    ("quote from the future", dict(q=quote(age=-5)), "future"),
    ("crossed quote", dict(q=quote(bid=101, ask=100)), "two-sided"),
    ("zero bid", dict(q=quote(bid=0, ask=1)), "two-sided"),
    ("NaN ask", dict(q=quote(bid=99, ask=float("nan"))), "two-sided"),
    ("more than shown", dict(q=quote(ask_qty=50)), "on offer"),
    ("not whole lots", dict(o=order(qty=80)), "lots"),
    ("zero quantity", dict(o=order(qty=0)), "long options only"),
    ("too much risk", dict(o=order(qty=150)), "risk"),
    ("unknown segment", dict(o=order(seg="nyse")), "unknown segment"),
    ("a NIFTY option labelled mcx", dict(o=order(seg="mcx")), "not on the list of underlyings that trade in mcx"),
    ("a NIFTY option labelled currency", dict(o=order(seg="nse_cds")), "not on the list of underlyings that trade in nse_cds"),
    ("bse costs unverified", dict(o=order(seg="bse_fo")), "not configured and verified"),
    ("expired option", dict(o=order(inst=opt(expiry=dt.date(2026, 11, 6)))), "expired"),
])
def test_each_reason_to_refuse_an_entry(desk, name, kw, needle):
    d, row = buy(desk, **kw)
    assert not d.allowed and row is None, name
    assert any(needle in r for r in d.reasons), (name, d.reasons)
    assert desk[1].cash == 500_000 and not desk[1].positions and not desk[1].ledger            # nothing moved


def test_futures_and_short_positions_are_refused_because_no_margin_model_exists(desk):
    fut = Instrument.future("NIFTY", 75)
    d, _ = buy(desk, o=order(inst=fut))
    assert not d.allowed and any("margin model" in r for r in d.reasons)


@pytest.mark.parametrize("when,needle", [
    (dt.datetime(2026, 11, 9, 9, 14, tzinfo=IST), "closed"),                 # before the open
    (dt.datetime(2026, 11, 9, 15, 30, tzinfo=IST), "closed"),                # the close is exclusive
    (dt.datetime(2026, 11, 7, 10, 0, tzinfo=IST), "does not trade"),         # Saturday
    (dt.datetime(2026, 11, 10, 10, 0, tzinfo=IST), "does not trade"),        # an NSE holiday
    (dt.datetime(2027, 1, 4, 10, 0, tzinfo=IST), "does not trade"),          # a year with no verified holiday list
])
def test_nothing_opens_outside_a_verified_session(desk, when, needle):
    d, _ = buy(desk, q=quote(now=when), now=when, o=order(inst=opt(expiry=dt.date(2027, 1, 7) if when.year == 2027 else EXPIRY)))
    assert not d.allowed and any(needle in r for r in d.reasons), d.reasons


def test_a_segment_whose_costs_are_not_verified_never_trades_even_if_open(cfg, tmp_path):
    lim = Limits(0.025, 0.05, 0.10, 30, frozenset())                        # no verified cost segment at all
    broker = PaperBroker(cfg, Account(500_000), RiskGate(cfg, lim, KillSwitch(tmp_path / "K")))
    d, _ = broker.buy(order(), quote(), {}, MON)
    assert not d.allowed and any("not configured and verified" in r for r in d.reasons)


def test_a_time_with_no_timezone_is_refused_not_guessed(desk):
    naive = dt.datetime(2026, 11, 9, 9, 59, 58)                                # read as host-local time it could land inside the session
    d, row = buy(desk, q=Quote(99.0, 100.0, naive))
    assert not d.allowed and row is None and any("timezone" in r for r in d.reasons)
    d, row = desk[0].buy(order(), quote(), {}, dt.datetime(2026, 11, 9, 10, 0))
    assert not d.allowed and any("timezone" in r for r in d.reasons)
    assert not desk[0].sell(opt().symbol, 75, quote(), dt.datetime(2026, 11, 9, 10, 0))[0].allowed


def test_a_risk_check_that_itself_fails_refuses_the_trade(desk):
    broken = Order(None, "nse_fo", 75, "s1", "a thesis")                         # no instrument: the check raises an AttributeError
    d, row = desk[0].buy(broken, quote(), {}, MON)
    assert not d.allowed and row is None and any("check itself failed" in r for r in d.reasons)


def test_not_enough_cash_refuses(cfg, tmp_path):
    broker = PaperBroker(cfg, Account(10_000), RiskGate(cfg, kill=KillSwitch(tmp_path / "K")))
    d, _ = broker.buy(order(qty=75), quote(ask=200.0, bid=199.0), {}, MON)                  # 15,000 outlay on 10,000
    assert not d.allowed and any("risk" in r or "cash" in r for r in d.reasons)


# ---- no cap on the number of trades; the loss budget bounds what is open at once -----------------------------------------------
def test_there_is_no_cap_on_the_number_of_trades(desk):
    broker, acct, gate, _ = desk
    assert not any("max" in f and ("trade" in f or "open" in f or "position" in f) for f in Limits.__dataclass_fields__)
    cheap = quote(bid=1.9, ask=2.0, ask_qty=100_000, bid_qty=100_000)
    for i in range(200):                                                                 # 200 entries and exits, one after another
        inst = opt(strike=20000 + 50 * i)
        d, _ = broker.buy(order(inst=inst), cheap, {}, MON)
        assert d.allowed, (i, d.reasons)
        assert broker.sell(inst.symbol, 75, cheap, MON)[0].allowed
    assert not acct.positions and len(acct.ledger) == 400 and acct.verify_ledger()
    assert not acct.day_halted and acct.halt is None                                     # the spread and fees of 200 round trips: under the caps


def test_how_much_can_be_open_at_once_is_bounded_by_the_loss_budget_not_by_a_count(cfg, tmp_path):
    acct = Account(500_000)
    broker = PaperBroker(cfg, acct, RiskGate(cfg, kill=KillSwitch(tmp_path / "K")))
    cheap = quote(bid=1.9, ask=2.0, ask_qty=100_000, bid_qty=100_000)
    n = 0
    while True:
        marks = {s_: 1.9 for s_ in acct.positions}                                       # marked at the bid
        d, _ = broker.buy(order(inst=opt(strike=30000 + 50 * n)), cheap, marks, MON)
        if not d.allowed:
            break
        n += 1
    assert n > 100 and len(acct.positions) == n                                          # far more than any small count cap
    assert any("loss budget" in r for r in d.reasons), d.reasons
    # the worst case is what is bounded: every position at zero together still leaves equity above the day's floor
    assert acct.equity({s_: 0.0 for s_ in acct.positions}) >= 500_000 * 0.95 - 1e-6
    # closing one frees its share of the budget
    first = next(iter(acct.positions))
    assert broker.sell(first, 75, cheap, MON)[0].allowed
    marks = {s_: 1.9 for s_ in acct.positions}
    assert broker.buy(order(inst=opt(strike=60000)), cheap, marks, MON)[0].allowed


def test_the_open_premium_stays_inside_the_daily_floor_when_entries_are_big(desk):
    broker, acct, gate, _ = desk
    allowed = 0
    for i in range(6):                                                                   # each about 2.4% of equity
        marks = {s_: 159.0 for s_ in acct.positions}
        d, _ = broker.buy(order(inst=opt(strike=24000 + 100 * i)), quote(bid=159, ask=160), marks, MON)
        allowed += d.allowed
        if not d.allowed:
            assert any("loss budget" in r for r in d.reasons), d.reasons
    assert allowed == 2                                                                  # two fit under the 5% day budget, the rest do not
    assert acct.equity({s_: 0.0 for s_ in acct.positions}) > 500_000 * 0.95             # all of it worthless: still above the floor


def test_the_drawdown_floor_also_bounds_what_can_be_opened(desk):
    broker, acct, gate, _ = desk
    acct.hwm = 550_000                                                                   # equity 500,000 is 9.1% below: close to the 10% halt
    d, _ = broker.buy(order(), quote(bid=99, ask=100), {}, MON)                          # 7,500 + fees against 5,000 left before the floor
    assert not d.allowed and any("loss budget" in r for r in d.reasons), d.reasons
    d, _ = broker.buy(order(), quote(bid=49, ask=50), {}, MON)                           # 3,750 + fees fits
    assert d.allowed, d.reasons


# ---- the loss caps --------------------------------------------------------------------------------------------------------------
def seed(acct, n, price=160.0, now=MON):
    """n positions of 75 units bought directly (as a gap, a bug or an older run could leave them), about 12,000 each."""
    syms = []
    for i in range(n):
        inst = opt(strike=24000 + 100 * i)
        acct.apply_fill("buy", inst, "nse_fo", 75, price, 20.0, now.isoformat(), "s", "t")
        syms.append(inst.symbol)
    return syms


WED = dt.datetime(2026, 11, 11, 10, 0, tzinfo=IST)           # 10 Nov is an NSE holiday


def test_the_daily_loss_cap_stops_new_entries_for_the_day_and_says_flatten(desk):
    broker, acct, gate, _ = desk
    syms = seed(acct, 3)                                                             # about 36,000 deployed
    ok = {s_: 160.0 for s_ in syms}
    why0 = gate.update(acct, ok, MON)
    assert not acct.day_halted and all(r.startswith("trim") for r in why0)           # no loss yet (the planted book is over the budget: a trim notice only)
    worthless = {s_: 0.0 for s_ in syms}                                             # all three go to zero: -7% > the 5% cap
    why = gate.update(acct, worthless, MON)
    assert acct.day_halted and any("daily loss cap" in r for r in why)
    d, _ = broker.buy(order(inst=opt(strike=30000)), quote(), worthless, MON)
    assert not d.allowed and any("daily loss cap" in r for r in d.reasons)
    assert acct.halt is None                                                         # -7% is under the 10% drawdown halt
    assert any("daily loss cap" in r for r in gate.update(acct, ok, MON))            # sticky: marks recovering does not undo it today


def test_the_daily_cap_resets_the_next_day_but_the_drawdown_halt_does_not(desk):
    broker, acct, gate, _ = desk
    syms = seed(acct, 3)
    gate.update(acct, {s_: 160.0 for s_ in syms}, MON)
    gate.update(acct, {s_: 0.0 for s_ in syms}, MON)
    assert acct.day_halted
    marks = {s_: 0.0 for s_ in syms}
    d, _ = broker.buy(order(inst=opt(strike=31000)), quote(now=WED), marks, WED)
    assert not acct.day_halted and d.allowed, d.reasons                              # a new day, a new daily cap


def test_the_drawdown_halt_holds_until_the_owner_clears_it(desk):
    broker, acct, gate, _ = desk
    syms = seed(acct, 5)                                                             # about 60,000 deployed
    gate.update(acct, {s_: 160.0 for s_ in syms}, MON)
    why = gate.update(acct, {s_: 0.0 for s_ in syms}, MON)                           # -12% from the high-water mark
    assert acct.halt is not None and any("drawdown halt" in r for r in why)
    marks = {s_: 0.0 for s_ in syms}
    d, _ = broker.buy(order(inst=opt(strike=31000)), quote(now=WED), marks, WED)
    assert not d.allowed and any("drawdown halt" in r for r in d.reasons)           # a new day does not clear it
    recovered = {s_: 160.0 for s_ in syms}
    assert any("drawdown halt" in r for r in gate.update(acct, recovered, WED))      # nor does a recovery in the marks
    assert acct.halt is not None
    for who, why_, eq, ts in (("", "reviewed", 440_000, "t"), ("owner", "", 440_000, "t"), ("owner", "reviewed", 440_000, ""),
                              ("owner", "reviewed", float("nan"), "t")):
        with pytest.raises(ValueError):
            acct.clear_halt(who, why_, eq, ts)                                       # needs who, why, when and a known equity
    assert acct.halt is not None
    acct.clear_halt("owner", "reviewed the losses", acct.equity(marks), WED.isoformat())
    assert acct.halt is None and acct.hwm == pytest.approx(acct.equity(marks))
    row = acct.ledger[-1]
    assert row["kind"] == "halt_cleared" and row["who"] == "owner" and row["reason"] == "reviewed the losses" and row["was"]   # on the record
    assert acct.verify_ledger()
    d, _ = broker.buy(order(inst=opt(strike=31000)), quote(now=WED), marks, WED)
    assert d.allowed, d.reasons


def test_an_empty_halt_record_still_halts(desk):
    broker, acct, gate, _ = desk
    acct.halt = {}                                                                   # a falsy record must not switch the brake off
    d, _ = buy(desk)
    assert not d.allowed and any("drawdown halt" in r for r in d.reasons)


def test_an_overnight_gap_counts_against_the_new_day(desk):
    broker, acct, gate, _ = desk
    syms = seed(acct, 3)
    gate.update(acct, {s_: 160.0 for s_ in syms}, MON)                               # Monday's close: about 499,940
    why = gate.update(acct, {s_: 0.0 for s_ in syms}, WED)                           # Wednesday opens at zero: the loss is the gap
    assert acct.day_halted and any("daily loss cap" in r for r in why)               # measured from Monday's close, not from the gap


def test_a_missing_price_does_not_blind_the_loss_caps(desk):
    broker, acct, gate, _ = desk
    syms = seed(acct, 4)                                                             # about 48,000 deployed
    gate.update(acct, {s_: 160.0 for s_ in syms}, MON)
    partial = {syms[0]: 0.0, syms[1]: 0.0, syms[2]: 0.0}                             # three worthless, the fourth has no price at all
    assert math.isnan(acct.equity(partial))
    why = gate.update(acct, partial, MON)
    assert any("flatten" in r and "unknown" in r for r in why), why                  # judged on the worst case: counted as worth nothing
    assert not acct.day_halted and acct.halt is None                                 # but no sticky flag is set from a guess
    d, _ = broker.buy(order(inst=opt(strike=30000)), quote(), partial, MON)
    assert not d.allowed and any("equity is unknown" in r for r in d.reasons)
    assert all(r.startswith("trim") for r in gate.update(acct, {s_: 160.0 for s_ in syms}, MON))     # prices back and healthy: no cap talk, only the planted excess


def test_the_kill_switch_stops_entries_and_says_flatten(desk):
    broker, acct, gate, kill = desk
    buy(desk)
    sym = opt().symbol
    assert not kill.exists() and gate.update(acct, {sym: 99.0}, MON) == []
    kill.write_text("stop")
    why = gate.update(acct, {sym: 99.0}, MON)
    assert any("kill switch" in r for r in why)
    d, _ = buy(desk, o=order(inst=opt(strike=26000)))
    assert not d.allowed and any("kill switch" in r for r in d.reasons)
    kill.unlink()                                                                    # switching it off lets entries through again
    assert gate.update(acct, {sym: 99.0}, MON) == []
    assert buy(desk, o=order(inst=opt(strike=26000)))[0].allowed


def test_a_kill_switch_that_cannot_be_checked_counts_as_on(tmp_path, monkeypatch):
    k = KillSwitch(tmp_path / "KILL")
    monkeypatch.setattr(Path, "exists", lambda self: (_ for _ in ()).throw(OSError("disk")))
    assert k.active() is True


# ---- exits are never trapped by a brake ----------------------------------------------------------------------------------------
def test_exits_are_never_trapped_by_a_brake_but_still_need_a_market_and_a_quote(desk):
    broker, acct, gate, kill = desk
    sym = opt().symbol
    acct.apply_fill("buy", opt(), "nse_fo", 75, 100.0, 20.0, MON.isoformat(), "s1", "t")
    kill.write_text("stop")                                                          # every brake on at once
    acct.halt, acct.day_halted = {"reason": "test"}, True
    closed = dt.datetime(2026, 11, 9, 15, 45, tzinfo=IST)
    assert broker.sell(sym, 76, quote(), MON)[0].allowed is False                    # more than held
    assert broker.sell(sym, 75, quote(bid_qty=10), MON)[0].allowed is False          # more than the bid shows
    assert broker.sell(sym, 75, None, MON)[0].allowed is False                       # no quote
    assert broker.sell(sym, 75, quote(now=closed), closed)[0].allowed is False       # market closed: it waits
    assert acct.positions[sym].qty == 75                                             # none of those refusals moved anything
    d, row = broker.sell(sym, 75, quote(), MON)
    assert d.allowed and row["kind"] == "sell" and not acct.positions                # open, halted and killed: the exit goes through


def test_flatten_sells_everything_that_has_a_usable_quote_and_reports_the_rest(desk):
    broker, acct, gate, _ = desk
    a, b = opt(25000), opt(25100)
    acct.apply_fill("buy", a, "nse_fo", 75, 100.0, 20.0, MON.isoformat(), "s", "t")
    acct.apply_fill("buy", b, "nse_fo", 75, 100.0, 20.0, MON.isoformat(), "s", "t")
    res = broker.flatten({a.symbol: quote()}, MON, "daily loss cap")
    assert res[a.symbol].allowed and not res[b.symbol].allowed and list(acct.positions) == [b.symbol]


# ---- unknown equity ------------------------------------------------------------------------------------------------------------
def test_unknown_equity_refuses_entries_but_not_exits(desk):
    broker, acct, gate, _ = desk
    buy(desk)
    sym = opt().symbol
    for bad in (float("nan"), None, -1.0, float("inf")):
        marks = {sym: bad} if bad is not None else {}
        assert math.isnan(acct.equity(marks))
        d, _ = broker.buy(order(inst=opt(strike=26000)), quote(), marks, MON)
        assert not d.allowed and any("equity is unknown" in r for r in d.reasons), bad
    assert broker.sell(sym, 75, quote(), MON)[0].allowed                              # and the position can still be sold


# ---- expiry ----------------------------------------------------------------------------------------------------------------------
def test_an_expired_in_the_money_call_settles_at_intrinsic_with_exercise_stt(desk, cfg):
    broker, acct, *_ = desk
    acct.apply_fill("buy", opt(25000, "CE"), "nse_fo", 75, 100.0, 20.0, MON.isoformat(), "s", "t")
    after = dt.datetime(2026, 11, 13, 9, 30, tzinfo=IST)
    out = broker.settle_expired(after.date(), {"NIFTY": 25200.0}, after)
    assert "intrinsic 200" in out[opt(25000, "CE").symbol] and not acct.positions
    stt = broker.costs.exercise_stt(EXPIRY) * 75 * 200
    assert acct.ledger[-1]["kind"] == "settle" and acct.ledger[-1]["fees"] == pytest.approx(stt) and stt > 0
    assert acct.cash == pytest.approx(500_000 - 75 * 100 - 20 + 75 * 200 - stt)
    assert acct.verify_ledger()


def test_an_out_of_the_money_option_settles_at_zero_and_a_missing_price_leaves_it_held_and_blocks_entries(desk):
    broker, acct, gate, _ = desk
    acct.apply_fill("buy", opt(25000, "PE"), "nse_fo", 75, 100.0, 20.0, MON.isoformat(), "s", "t")
    after = dt.datetime(2026, 11, 13, 9, 30, tzinfo=IST)
    assert "no settlement price" in broker.settle_expired(after.date(), {}, after)[opt(25000, "PE").symbol]
    assert opt(25000, "PE").symbol in acct.positions
    d, _ = broker.buy(order(inst=opt(25500, "CE", expiry=dt.date(2026, 11, 19))), quote(now=after), {}, after)
    assert not d.allowed and any("equity is unknown" in r for r in d.reasons)         # unsettled: its mark is unknown
    broker.settle_expired(after.date(), {"NIFTY": 25200.0}, after)                    # a put struck below the price: worth nothing
    assert not acct.positions and acct.ledger[-1]["price"] == 0.0


# ---- the ledger and persistence -------------------------------------------------------------------------------------------------
def test_the_ledger_detects_any_change_and_a_saved_account_round_trips(desk, tmp_path):
    broker, acct, *_ = desk
    buy(desk)
    broker.sell(opt().symbol, 75, quote(), MON)
    assert acct.verify_ledger()
    path = tmp_path / "account.json"
    acct.save(path)
    back = Account.load(path)
    assert back.cash == acct.cash and back.ledger == acct.ledger and back.verify_ledger() and back.to_dict() == acct.to_dict()
    for mutate in (lambda L: L[0].__setitem__("price", 1.0), lambda L: L.pop(0), lambda L: L.reverse()):
        data = json.loads(path.read_text())
        mutate(data["ledger"])
        path.write_text(json.dumps(data))
        with pytest.raises(ValueError, match="hash chain"):
            Account.load(path)


def test_the_account_refuses_to_go_wrong(desk):
    _, acct, *_ = desk
    with pytest.raises(ValueError, match="cannot sell"):
        acct.apply_fill("sell", opt(), "nse_fo", 75, 100.0, 1.0, "t", "s", "t")             # nothing held
    with pytest.raises(ValueError, match="bad fill"):
        acct.apply_fill("buy", opt(), "nse_fo", 75, float("nan"), 1.0, "t", "s", "t")       # a NaN price
    with pytest.raises(ValueError, match="not enough cash"):
        acct.apply_fill("buy", opt(), "nse_fo", 1_000_000, 100.0, 1.0, "t", "s", "t")       # more than the cash
    with pytest.raises(ValueError):
        Account(0)
    assert acct.cash == 500_000 and not acct.ledger and not acct.positions


# ---- what the package must not do ---------------------------------------------------------------------------------------------
ALLOWED_INTERNAL = ("quantdesk.core", "quantdesk.execution", "quantdesk.markets", "quantdesk.paper")
FORBIDDEN_MODULES = {"requests", "urllib", "http", "socket", "ssl", "subprocess", "importlib", "ftplib", "smtplib", "kiteconnect", "multiprocessing"}


def _imports(path: Path):
    """Every module a file imports, as a dotted absolute name, relative imports resolved against quantdesk.paper."""
    out = []
    for n in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(n, ast.Import):
            out += [a_.name for a_ in n.names]
        elif isinstance(n, ast.ImportFrom):
            base = n.module or ""
            if n.level:
                pkg = ["quantdesk", "paper"][: 2 - (n.level - 1)]
                base = ".".join(pkg + ([base] if base else []))
            out += [f"{base}.{a_.name}" if a_.name != "*" else base for a_ in n.names]
    return out


def test_the_paper_package_has_no_network_secret_or_real_order_path():
    files = list((ROOT / "quantdesk" / "paper").glob("*.py"))
    assert files
    for f in files:
        for mod in _imports(f):
            top = mod.split(".")[0]
            assert top not in FORBIDDEN_MODULES, (f.name, mod)
            if top == "quantdesk":
                assert mod.startswith(ALLOWED_INTERNAL), (f.name, mod)                 # includes `from .. import intraday`
        src = f.read_text(encoding="utf-8")
        for bad in ("os.environ", "os.getenv", "getenv(", "__import__", "eval(", "exec(", "place_order", "KITE_", "KOTAK_", "secrets."):
            assert bad not in src, (f.name, bad)
        assert not re.search(r"(?<![\w`])max_(trades|open)\w*\s*[:=(]|\.max_(trades|open)", src), f.name        # no such limit exists in code


def test_the_scan_itself_catches_what_it_is_meant_to(tmp_path):
    for line, bad in (("from .. import intraday", "quantdesk.intraday"), ("from quantdesk import intraday", "quantdesk.intraday"),
                      ("import http.client", "http.client"), ("import importlib", "importlib"), ("from ..data import nse", "quantdesk.data.nse")):
        f = tmp_path / "x.py"
        f.write_text(line + "\n")
        mods = _imports(f)
        assert any(m.split(".")[0] in FORBIDDEN_MODULES or (m.startswith("quantdesk") and not m.startswith(ALLOWED_INTERNAL)) for m in mods), (line, mods)


def test_the_config_carries_loss_caps_only(cfg):
    p = cfg.get("paper")
    assert set(p) == {"capital", "risk_per_trade", "daily_loss_limit", "drawdown_halt", "max_quote_age_s", "cost_verified_segments", "kill_switch_file",
                      "underlyings", "allow_short_legs", "stock_options", "futures"}
    assert set(p["stock_options"]) == {"lots", "steps"}
    assert set(p["futures"]) == {"square_off_min", "entry_cutoff_min", "stop_max_pct", "contracts"}                   # MCX and currency (13 Nov 2026): contract facts and session mechanics, no cap on size
    assert all(set(c) == {"segment", "lot", "unit", "margin", "no_entry_days", "opt_tick"} for c in p["futures"]["contracts"].values())                                 # contract facts only (lots per expiry, strike steps): no cap on trades, positions or size hides there
    assert p["allow_short_legs"] is True                                        # sold options, only as legs of bounded packages, are ON by the owner's written order (8 Nov 2026)
    assert p["risk_per_trade"] == 0.025 and p["daily_loss_limit"] == 0.05 and p["drawdown_halt"] == 0.10 and p["cost_verified_segments"] == ["nse_fo", "mcx", "nse_cds"]


# ---- a mislabelled order cannot dodge the costs and hours checks (B3) ---------------------------------------------------------------
@pytest.mark.parametrize("under", ["CRUDEOIL", "USDINR", "SENSEX", "GOLD", "IDEA"])       # IDEA: an F&O stock that is not on the paper desk's list
def test_an_underlying_that_does_not_trade_in_the_labelled_segment_is_refused(desk, under):
    d, row = buy(desk, o=order(inst=opt(under=under)))                             # labelled nse_fo
    assert not d.allowed and row is None and any("not on the list of underlyings" in r for r in d.reasons), d.reasons


@pytest.mark.parametrize("under", ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "nifty", "RELIANCE", "M&M", "BAJAJ-AUTO"])      # the stocks by the owner's order of 13 Nov 2026
def test_the_listed_nse_indices_trade(desk, under):
    assert buy(desk, o=order(inst=opt(under=under)))[0].allowed


def test_the_mislabel_guard_holds_the_other_way_too(desk):
    assert not buy(desk, o=order(inst=opt(under="NIFTY"), seg="mcx"))[0].allowed
    assert not buy(desk, o=order(inst=opt(under="NIFTY"), seg="bse_fo"))[0].allowed


# ---- the account keeps its promises (B4) ------------------------------------------------------------------------------------------
@pytest.mark.parametrize("qty", [float("nan"), float("inf"), 0.5, 75.0, True, False, 0, -75, None, "75"])
def test_a_quantity_that_is_not_a_whole_positive_number_is_refused_and_nothing_changes(desk, qty):
    _, acct, *_ = desk
    with pytest.raises(ValueError):
        acct.apply_fill("buy", opt(), "nse_fo", qty, 100.0, 20.0, "t", "s", "t")
    assert acct.cash == 500_000 and not acct.positions and not acct.ledger


def test_numpy_whole_numbers_are_fine_and_a_zero_priced_buy_is_not(desk):
    _, acct, *_ = desk
    acct.apply_fill("buy", opt(), "nse_fo", np.int64(75), 100.0, 20.0, "t", "s", "t")
    assert acct.positions[opt().symbol].qty == 75 and type(acct.positions[opt().symbol].qty) is int
    with pytest.raises(ValueError, match="free position"):
        acct.apply_fill("buy", opt(25100), "nse_fo", 75, 0.0, 0.0, "t", "s", "t")
    for bad in (float("nan"), -1.0, True):
        with pytest.raises(ValueError):
            acct.apply_fill("buy", opt(25200), "nse_fo", 75, bad, 20.0, "t", "s", "t")
        with pytest.raises(ValueError):
            acct.apply_fill("buy", opt(25200), "nse_fo", 75, 100.0, bad, "t", "s", "t")


def test_a_fill_is_all_or_nothing_even_when_the_record_cannot_be_written(desk):
    _, acct, *_ = desk
    acct.apply_fill("buy", opt(), "nse_fo", 75, 100.0, 20.0, "t", "s", "t")
    before = json.dumps(acct.to_dict(), sort_keys=True)
    with pytest.raises(TypeError):
        acct.apply_fill("buy", opt(25100), "nse_fo", 75, 100.0, 20.0, "t", "s", object())      # a thesis that cannot be saved
    with pytest.raises(TypeError):
        acct.apply_fill("sell", opt(), "nse_fo", 75, 100.0, 20.0, "t", "s", object())
    assert json.dumps(acct.to_dict(), sort_keys=True) == before                                # cash, positions, ledger: exactly as they were


def test_an_exit_is_never_refused_for_its_fees_and_the_next_entry_then_is(cfg, tmp_path):
    acct = Account(100.0)
    acct.apply_fill("buy", opt(), "nse_fo", 75, 1.0, 24.0, MON.isoformat(), "s", "t")          # 75 + 24 of the 100: cash 1
    broker = PaperBroker(cfg, acct, RiskGate(cfg, kill=KillSwitch(tmp_path / "K")))
    d, row = broker.sell(opt().symbol, 75, quote(bid=0.05, ask=0.10), MON)                        # proceeds 3.75, fees about 24
    assert d.allowed and row["fees"] > row["price"] * 75 and acct.cash < 0 and not acct.positions
    d, _ = broker.buy(order(inst=opt(25100)), quote(bid=0.05, ask=0.10), {}, MON)
    assert not d.allowed and any("daily loss cap" in r or "drawdown halt" in r for r in d.reasons), d.reasons      # below both floors now


def test_oversell_and_the_other_account_refusals(desk):
    _, acct, *_ = desk
    acct.apply_fill("buy", opt(), "nse_fo", 75, 100.0, 20.0, "t", "s", "t")
    with pytest.raises(ValueError, match="cannot sell"):
        acct.apply_fill("sell", opt(), "nse_fo", 76, 100.0, 20.0, "t", "s", "t")               # one more than held
    with pytest.raises(ValueError, match="unknown kind"):
        acct.apply_fill("short", opt(), "nse_fo", 75, 100.0, 20.0, "t", "s", "t")
    with pytest.raises(ValueError):
        acct.record_event("buy", "t")                                                          # a fill is not an event


# ---- a saved account is checked against its own history (N2) ----------------------------------------------------------------
def _saved(desk, tmp_path):
    broker, acct, *_ = desk
    buy(desk)
    buy(desk, o=order(inst=opt(25100)))
    broker.sell(opt().symbol, 75, quote(), MON)
    path = tmp_path / "account.json"
    acct.save(path)
    return acct, path


@pytest.mark.parametrize("edit", [
    lambda d: d.__setitem__("cash", d["cash"] + 100_000),
    lambda d: d.__setitem__("positions", {}),
    lambda d: d["positions"][next(iter(d["positions"]))].__setitem__("qty", 750),
    lambda d: d.__setitem__("realized", 1e6),
    lambda d: d.__setitem__("fees", 0.0),
    lambda d: d["ledger"].pop(),                                      # the tail cut off
    lambda d: d.__setitem__("ledger", []),                            # the whole history gone
    lambda d: d["ledger"][0].__setitem__("cash_after", 1.0),          # a row's content
    lambda d: d["ledger"][1].__setitem__("prev", "x" * 64),           # the chain's link
])
def test_an_edited_account_file_is_refused_on_load(desk, tmp_path, edit):
    acct, path = _saved(desk, tmp_path)
    assert Account.load(path).to_dict() == acct.to_dict()
    data = json.loads(path.read_text())
    edit(data)
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        Account.load(path)


def test_save_leaves_no_temporary_file_and_replaces_atomically(desk, tmp_path):
    acct, path = _saved(desk, tmp_path)
    assert [f.name for f in tmp_path.iterdir() if f.name.startswith("account")] == ["account.json"]


# ---- the kill switch's file is found from the repository, not the working directory (N3) ----------------------------------------
def test_a_relative_kill_switch_path_is_taken_from_the_repository_root(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    k = KillSwitch("runtime/paper/KILL")
    assert k.path == ROOT / "runtime" / "paper" / "KILL" and tmp_path not in k.path.parents
    assert KillSwitch(tmp_path / "KILL").path == tmp_path / "KILL"


# ---- inputs that used to fail open (N4) ---------------------------------------------------------------------------------------------
@pytest.mark.parametrize("name,kw", [
    ("NaN ask size", dict(q=quote(ask_qty=float("nan")))),
    ("zero ask size", dict(q=quote(ask_qty=0))),
    ("negative bid size", dict(q=quote(bid_qty=-5))),
    ("bool prices", dict(q=Quote(True, True, MON - dt.timedelta(seconds=1)))),
])
def test_odd_quote_fields_are_refused(desk, name, kw):
    d, _ = buy(desk, **kw)
    assert not d.allowed and any("two-sided" in r for r in d.reasons), (name, d.reasons)


@pytest.mark.parametrize("lot", [0, -75, 75.0, None])
def test_a_contract_without_a_proper_lot_size_is_refused(desk, lot):
    inst = opt()
    object.__setattr__(inst, "lot_size", lot)
    d, _ = buy(desk, o=order(inst=inst, qty=80))
    assert not d.allowed and any("lots of" in r for r in d.reasons), d.reasons


@pytest.mark.parametrize("field,value", [("risk_per_trade", float("nan")), ("risk_per_trade", 0), ("risk_per_trade", 1.5), ("daily_loss_limit", float("nan")),
                                         ("drawdown_halt", -0.1), ("drawdown_halt", True), ("max_quote_age_s", 0), ("max_quote_age_s", float("nan"))])
def test_a_limit_that_is_not_a_sensible_share_is_refused_at_load(cfg, field, value):
    good = dict(risk_per_trade=0.025, daily_loss_limit=0.05, drawdown_halt=0.10, max_quote_age_s=30.0, cost_verified=frozenset({"nse_fo"}))
    with pytest.raises(ValueError):
        Limits(**{**good, field: value})
    bad_cfg = Config.load(ROOT / "config" / "quantdesk.yaml", overrides={"paper": {field: value}})
    with pytest.raises(ValueError):
        Limits.from_config(bad_cfg)


# ---- mutations the first review found the tests missed (N6) ---------------------------------------------------------------------------
def test_the_risk_of_an_entry_includes_its_fees(desk):
    d, _ = buy(desk, q=quote(bid=166.0, ask=166.5))                              # 75 x 166.5 = 12,487.5: under 12,500, over with fees
    assert not d.allowed and any("risk" in r for r in d.reasons), d.reasons


def test_an_option_expiring_today_is_not_settled_until_tomorrow(desk):
    broker, acct, *_ = desk
    acct.apply_fill("buy", opt(), "nse_fo", 75, 100.0, 20.0, MON.isoformat(), "s", "t")
    on_expiry = dt.datetime(2026, 11, 12, 15, 0, tzinfo=IST)
    assert broker.settle_expired(on_expiry.date(), {"NIFTY": 25200.0}, on_expiry) == {} and opt().symbol in acct.positions
    assert broker.settle_expired(dt.date(2026, 11, 13), {"NIFTY": 25200.0}, on_expiry)       # the day after


def test_a_contract_with_no_strike_is_left_held_not_half_settled(desk):
    broker, acct, *_ = desk
    acct.apply_fill("buy", opt(), "nse_fo", 75, 100.0, 20.0, MON.isoformat(), "s", "t")
    object.__setattr__(acct.positions[opt().symbol].instrument, "strike", None)
    out = broker.settle_expired(dt.date(2026, 11, 13), {"NIFTY": 25200.0}, MON)
    assert "left held" in out[opt().symbol] and opt().symbol in acct.positions and len(acct.ledger) == 1


def test_the_halt_survives_a_new_day_when_the_marks_recover(desk):
    broker, acct, gate, _ = desk
    syms = seed(acct, 5)
    gate.update(acct, {s_: 160.0 for s_ in syms}, MON)
    gate.update(acct, {s_: 0.0 for s_ in syms}, MON)
    assert acct.halt is not None
    gate.update(acct, {s_: 160.0 for s_ in syms}, WED)                               # a new day and the marks are back
    assert acct.halt is not None


def test_every_ledger_row_records_the_true_cash_after_its_fill(desk):
    broker, acct, *_ = desk
    for step in (lambda: buy(desk), lambda: buy(desk, o=order(inst=opt(25100))), lambda: broker.sell(opt().symbol, 75, quote(), MON)):
        step()
        assert acct.ledger[-1]["cash_after"] == acct.cash
    assert [r["kind"] for r in acct.ledger] == ["buy", "buy", "sell"] and acct.ledger[0]["cash_after"] > acct.ledger[1]["cash_after"]


def test_verify_ledger_itself_notices_a_changed_link_field(desk):
    broker, acct, *_ = desk
    buy(desk)
    buy(desk, o=order(inst=opt(25100)))
    assert acct.verify_ledger()
    acct.ledger[1]["prev"] = "x" * 64                                  # the stored link, not the content
    assert not acct.verify_ledger()


# ---- the second review (R1 to R4) ---------------------------------------------------------------------------------------------------
def _held_and_saved(desk, tmp_path):
    broker, acct, *_ = desk
    buy(desk)
    path = tmp_path / "account.json"
    acct.save(path)
    return acct, path


@pytest.mark.parametrize("edit", [
    lambda pos: pos["instrument"].__setitem__("strike", 1.0),
    lambda pos: pos["instrument"].__setitem__("expiry", "2030-01-01"),
    lambda pos: pos["instrument"].__setitem__("right", "PE"),
    lambda pos: pos["instrument"].__setitem__("lot_size", 1),
    lambda pos: pos["instrument"].__setitem__("kind", "future"),
    lambda pos: pos["instrument"].__setitem__("underlying", "CRUDEOIL"),
    lambda pos: pos.__setitem__("segment", "mcx"),
    lambda pos: pos.__setitem__("thesis", "something else"),
    lambda pos: pos.__setitem__("opened_at", "2020-01-01T00:00:00+05:30"),
    lambda pos: pos.__setitem__("strategy", "other"),
])
def test_editing_any_field_of_a_saved_position_is_refused_on_load(desk, tmp_path, edit):
    acct, path = _held_and_saved(desk, tmp_path)
    assert Account.load(path).to_dict() == acct.to_dict()
    data = json.loads(path.read_text())
    edit(next(iter(data["positions"].values())))
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="do not match the ledger"):
        Account.load(path)


def test_a_carried_winner_that_the_loss_budget_cannot_cover_is_trimmed(desk):
    broker, acct, gate, _ = desk
    syms = []
    for i in range(2):                                                            # two ordinary entries, each about 2.4% of equity
        d, _ = broker.buy(order(inst=opt(strike=24000 + 100 * i)), quote(bid=159, ask=160), {s_: 159.0 for s_ in syms}, MON)
        assert d.allowed, d.reasons
        syms.append(opt(strike=24000 + 100 * i).symbol)
    big = {s_: 400.0 for s_ in syms}                                              # both run to 2.5x: the book is now worth 60,000
    assert any(r.startswith("trim") for r in gate.update(acct, big, MON))        # the peak is a new high-water mark: the drawdown floor already rose
    mon_excess = gate.trim_excess(acct, big)
    assert mon_excess > 0
    why = gate.update(acct, big, WED)                                             # the next day starts from the higher equity: the day's floor rises too
    assert any(r.startswith("trim") for r in why), why
    excess = gate.trim_excess(acct, big)
    assert excess > mon_excess
    quotes = {s_: quote(bid=399, ask=401, now=WED) for s_ in syms}
    res = broker.trim(quotes, big, WED)
    assert res and all(d.allowed for d in res.values())
    after = {s_: 400.0 for s_ in acct.positions}
    assert gate.trim_excess(acct, after) == 0 and not any(r.startswith("trim") for r in gate.update(acct, after, WED))
    assert acct.verify_ledger()


def test_trim_sells_in_whole_lots_biggest_first_and_leaves_what_it_cannot_sell(desk):
    broker, acct, gate, _ = desk
    a, b = opt(24000), opt(24100)
    acct.apply_fill("buy", a, "nse_fo", 150, 100.0, 20.0, MON.isoformat(), "s", "t")           # 2 lots
    acct.apply_fill("buy", b, "nse_fo", 75, 100.0, 20.0, MON.isoformat(), "s", "t")            # 1 lot
    marks = {a.symbol: 100.0, b.symbol: 100.0}
    gate.update(acct, marks, MON)
    acct.day_start = acct.last_equity = 520_000.0                                  # a higher starting equity raises the day's floor: excess appears
    excess = gate.trim_excess(acct, marks)
    assert excess > 0
    res = broker.trim({a.symbol: quote(bid=99, ask=101)}, marks, MON)                  # no quote for b: it stays held and is reported as not sold
    assert res[a.symbol].allowed and not res[b.symbol].allowed
    assert acct.positions[b.symbol].qty == 75                                          # the unquoted one is untouched
    assert a.symbol not in acct.positions or (acct.positions[a.symbol].qty % 75 == 0 and acct.positions[a.symbol].qty < 150)   # biggest first, whole lots


def test_time_may_not_run_backwards_across_days_and_never_resets_the_daily_cap(desk):
    broker, acct, gate, _ = desk
    syms = seed(acct, 3)
    gate.update(acct, {s_: 160.0 for s_ in syms}, WED)
    gate.update(acct, {s_: 0.0 for s_ in syms}, WED)
    assert acct.day_halted
    with pytest.raises(ValueError, match="backwards"):
        gate.update(acct, {s_: 0.0 for s_ in syms}, MON)                           # an earlier day: refused
    assert acct.day_halted and acct.day == "2026-11-11"
    d, _ = broker.buy(order(inst=opt(strike=31000)), quote(now=MON), {s_: 0.0 for s_ in syms}, MON)
    assert not d.allowed and any("backwards" in r or "check itself failed" in r for r in d.reasons)


def test_the_halt_and_the_daily_cap_are_written_to_the_ledger_and_the_saved_flags_must_agree(desk, tmp_path):
    broker, acct, gate, _ = desk
    syms = seed(acct, 5)
    gate.update(acct, {s_: 160.0 for s_ in syms}, MON)
    gate.update(acct, {s_: 0.0 for s_ in syms}, MON)
    kinds = [r["kind"] for r in acct.ledger]
    assert "daily_cap_hit" in kinds and "halt_set" in kinds and acct.day_halted and acct.halt is not None
    gate.update(acct, {s_: 0.0 for s_ in syms}, MON)                                  # a second look adds nothing
    assert [r["kind"] for r in acct.ledger].count("halt_set") == 1 and [r["kind"] for r in acct.ledger].count("daily_cap_hit") == 1
    path = tmp_path / "halted.json"
    acct.save(path)
    assert Account.load(path).halt is not None
    for edit, why in ((lambda d: d.__setitem__("halt", None), "drawdown halt"), (lambda d: d.__setitem__("day_halted", False), "daily loss cap")):
        data = json.loads(path.read_text())
        edit(data)
        path.write_text(json.dumps(data))
        with pytest.raises(ValueError, match=why):
            Account.load(path)
        acct.save(path)                                                               # put the good file back
    data = json.loads(path.read_text())
    data["halt"] = {}                                                                 # an empty record is still a halt, and the ledger agrees there is one
    path.write_text(json.dumps(data))
    assert Account.load(path).halt == {}
    acct.save(path)
    acct.clear_halt("owner", "reviewed", 430_000, WED.isoformat())                     # a cleared halt: the ledger says so
    acct.save(path)
    assert Account.load(path).halt is None
    data = json.loads(path.read_text())
    data["halt"] = {"reason": "forged"}
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="drawdown halt"):
        Account.load(path)


def test_a_contract_must_belong_to_its_underlying(desk):
    inst = opt()
    object.__setattr__(inst, "symbol", "CRUDEOIL19NOV266000CE")                  # hand-built: a crude-oil name on a NIFTY underlying
    d, _ = buy(desk, o=order(inst=inst))
    assert not d.allowed and any("does not belong to its underlying" in r for r in d.reasons), d.reasons


def test_a_missing_price_counts_as_worth_nothing_in_the_lower_bound(desk):
    _, acct, *_ = desk
    acct.apply_fill("buy", opt(), "nse_fo", 75, 100.0, 20.0, MON.isoformat(), "s", "t")
    assert acct.equity_lower_bound({}) == pytest.approx(acct.cash)                    # not its cost, not its last price: nothing
    assert acct.equity_lower_bound({opt().symbol: float("nan")}) == pytest.approx(acct.cash)
    assert acct.equity_lower_bound({opt().symbol: 100.0}) == pytest.approx(acct.cash + 7500)
