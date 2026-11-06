"""The paper desk's money and brakes (quantdesk/paper): the account, the risk gate and the paper broker.

Every brake has a test that fails if the brake is removed. The owner's rule is no cap on the number of trades or open positions,
only loss caps, and that is tested too."""
import datetime as dt
import json
import math
from pathlib import Path

import pytest

from quantdesk.config import Config
from quantdesk.core.types import Instrument
from quantdesk.markets import sessions as MK
from quantdesk.paper.account import Account
from quantdesk.paper.broker import PaperBroker
from quantdesk.paper.risk import KillSwitch, Limits, Order, Quote, RiskGate

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
    d, row = buy(desk)
    _, acct, *_ = desk
    assert d.allowed and row["kind"] == "buy" and row["price"] == 100.0 and row["fees"] > 0
    assert acct.cash == pytest.approx(500_000 - 75 * 100.0 - row["fees"])
    pos = acct.positions[opt().symbol]
    assert pos.qty == 75 and pos.thesis == "range break with rising volume, 30m" and pos.strategy == "s1"
    assert acct.verify_ledger() and len(acct.ledger) == 1


def test_a_sell_fills_at_the_bid_and_the_round_trip_pays_the_spread_and_fees(desk):
    broker, acct, *_ = desk
    buy(desk)
    d, row = broker.sell(opt().symbol, 75, quote(), MON)
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
    ("mcx costs unverified", dict(o=order(seg="mcx")), "not configured and verified"),
    ("currency costs unverified", dict(o=order(seg="nse_cds")), "not configured and verified"),
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


def test_a_risk_check_that_itself_fails_refuses_the_trade(desk):
    naive = dt.datetime(2026, 11, 9, 9, 59, 58)                                # a quote time with no timezone raises on subtraction
    d, row = buy(desk, q=Quote(99.0, 100.0, naive))
    assert not d.allowed and row is None and any("check itself failed" in r for r in d.reasons)


def test_cash_tied_up_in_positions_refuses_a_new_entry_cleanly_even_when_equity_is_large(cfg, tmp_path):
    acct = Account(1_000_000)
    held = opt(24000)
    acct.apply_fill("buy", held, "nse_fo", 75, 13_200.0, 0.0, MON.isoformat(), "s", "t")          # 990,000 of the cash now sits in one position
    broker = PaperBroker(cfg, acct, RiskGate(cfg, kill=KillSwitch(tmp_path / "K")))
    marks = {held.symbol: 13_200.0}
    assert acct.equity(marks) == pytest.approx(1_000_000) and acct.cash == pytest.approx(10_000)
    d, row = broker.buy(order(inst=opt(26000)), quote(bid=265.0, ask=266.0), marks, MON)         # ~20,000: under 2.5% of equity, over the cash
    assert not d.allowed and row is None and any("cash is" in r for r in d.reasons), d.reasons
    assert acct.cash == pytest.approx(10_000) and len(acct.ledger) == 1                            # refused, not crashed, nothing moved


def test_not_enough_cash_refuses(cfg, tmp_path):
    broker = PaperBroker(cfg, Account(10_000), RiskGate(cfg, kill=KillSwitch(tmp_path / "K")))
    d, _ = broker.buy(order(qty=75), quote(ask=200.0, bid=199.0), {}, MON)                  # 15,000 outlay on 10,000
    assert not d.allowed and any("risk" in r or "cash" in r for r in d.reasons)


# ---- no cap on the number of trades or positions -------------------------------------------------------------------------------
def test_there_is_no_cap_on_trades_or_open_positions(desk):
    broker, acct, gate, _ = desk
    assert not any("max" in f and ("trade" in f or "open" in f or "position" in f) for f in Limits.__dataclass_fields__)
    cheap = quote(bid=1.9, ask=2.0)
    for i in range(300):                                                                 # 300 distinct entries in one session
        d, row = broker.buy(order(inst=opt(strike=20000 + 50 * i)), cheap, {s: p.avg_price for s, p in acct.positions.items()}, MON)
        assert d.allowed, (i, d.reasons)
    assert len(acct.positions) == 300 and len(acct.ledger) == 300 and acct.verify_ledger()
    for i in range(300):                                                                 # and 300 exits
        sym = opt(strike=20000 + 50 * i).symbol
        assert broker.sell(sym, 75, cheap, MON)[0].allowed
    assert not acct.positions and len(acct.ledger) == 600


# ---- the loss caps --------------------------------------------------------------------------------------------------------------
def fill_n(broker, acct, n, ask=160.0, now=MON):
    """n entries of about 12,000 each (about 2.4% of equity), all at one price, on different strikes."""
    syms = []
    for i in range(n):
        inst = opt(strike=24000 + 100 * i)
        d, _ = broker.buy(order(inst=inst), quote(bid=ask - 1, ask=ask, now=now), {s: p.avg_price for s, p in acct.positions.items()}, now)
        assert d.allowed, d.reasons
        syms.append(inst.symbol)
    return syms


def test_the_daily_loss_cap_stops_new_entries_for_the_day_and_says_flatten(desk):
    broker, acct, gate, _ = desk
    syms = fill_n(broker, acct, 3)                                                   # ~36,000 at risk
    ok = {s: 160.0 for s in syms}
    assert gate.update(acct, ok, MON) == [] and not acct.day_halted                  # no loss yet
    worthless = {s: 0.0 for s in syms}                                               # all three go to zero: about -36,000 > 5% of 500,000
    why = gate.update(acct, worthless, MON)
    assert acct.day_halted and any("daily loss cap" in r for r in why)
    d, _ = broker.buy(order(inst=opt(strike=30000)), quote(), worthless, MON)
    assert not d.allowed and any("daily loss cap" in r for r in d.reasons)
    assert acct.halt is None                                                         # -7% is under the 10% drawdown halt
    assert any("daily loss cap" in r for r in gate.update(acct, ok, MON))            # sticky: marks recovering does not undo it today


def test_the_daily_cap_resets_the_next_day_but_the_drawdown_halt_does_not(desk):
    broker, acct, gate, _ = desk
    syms = fill_n(broker, acct, 3)
    gate.update(acct, {s: 0.0 for s in syms}, MON)
    assert acct.day_halted
    tue = MON + dt.timedelta(days=1)                                                 # 10 Nov is a holiday: use Wednesday 11 Nov
    wed = dt.datetime(2026, 11, 11, 10, 0, tzinfo=IST)
    after = {s: 0.0 for s in syms}
    d, _ = broker.buy(order(inst=opt(strike=31000)), quote(now=wed), after, wed)
    assert not acct.day_halted and d.allowed, d.reasons                              # a new day, a new daily cap


def test_the_drawdown_halt_holds_until_the_owner_clears_it(desk):
    broker, acct, gate, _ = desk
    syms = fill_n(broker, acct, 5)                                                   # ~60,000 at risk
    why = gate.update(acct, {s: 0.0 for s in syms}, MON)                             # -12% from the high-water mark
    assert acct.halt and any("drawdown halt" in r for r in why)
    wed = dt.datetime(2026, 11, 11, 10, 0, tzinfo=IST)
    marks = {s: 0.0 for s in syms}
    d, _ = broker.buy(order(inst=opt(strike=31000)), quote(now=wed), marks, wed)
    assert not d.allowed and any("drawdown halt" in r for r in d.reasons)           # a new day does not clear it
    with pytest.raises(ValueError):
        acct.clear_halt("", "looks fine", 440_000)                                   # needs who and why
    acct.clear_halt("owner", "reviewed the losses", acct.equity(marks))
    assert acct.halt is None and acct.hwm == pytest.approx(acct.equity(marks))
    d, _ = broker.buy(order(inst=opt(strike=31000)), quote(now=wed), marks, wed)
    assert d.allowed, d.reasons


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
def test_the_paper_package_has_no_network_secret_or_real_order_path():
    import re
    for f in (ROOT / "quantdesk" / "paper").glob("*.py"):
        src = f.read_text(encoding="utf-8")
        assert not re.search(r"^\s*(from|import)\s+(\.\.?\s*)?(quantdesk\.)?(intraday|journal|web|data|learnbot)\b", src, re.M), f.name
        for bad in ("requests", "urllib", "socket", "subprocess", "os.environ", "kiteconnect", "place_order", "KITE_", "KOTAK_", "secrets."):
            assert bad not in src, (f.name, bad)
        assert not re.search(r"(?<![\w`])max_(trades|open)\w*\s*[:=(]|\.max_(trades|open)", src), f.name        # no such limit exists in code


def test_the_config_carries_loss_caps_only(cfg):
    p = cfg.get("paper")
    assert set(p) == {"capital", "risk_per_trade", "daily_loss_limit", "drawdown_halt", "max_quote_age_s", "cost_verified_segments", "kill_switch_file"}
    assert p["risk_per_trade"] == 0.025 and p["daily_loss_limit"] == 0.05 and p["drawdown_halt"] == 0.10 and p["cost_verified_segments"] == ["nse_fo"]
