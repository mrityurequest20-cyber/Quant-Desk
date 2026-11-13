"""MCX and currency FUTURES on the paper desk (owner's order, 13 Nov 2026: "First, enable the MCX and the currency in the paper trading"). PAPER MONEY ONLY.

What is pinned: a future is long or short, a whole number of lots, and every entry has a stop; the loss to the stop (with a slippage allowance and both sides' fees) is held to
risk_per_trade like an option's premium, the margin to the equity left free, and the whole book to the loss budget. A futures fill moves cash only by its fees and, on the
close, its profit. The runner closes at the stop or the target and squares off before the segment's close (intraday only). The contract month comes with the board's quote
and a position is never priced on another month's quote. The ledger carries the stop, so a restart rebuilds it. Costs are MCX's and NSE currency's own schedules."""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pytest

from quantdesk.config import Config
from quantdesk.core.types import FUTURE, Instrument
from quantdesk.execution.costs import CostModel
from quantdesk.markets import sessions as MK
from quantdesk.paper import runner as R
from quantdesk.paper.account import Account
from quantdesk.paper.risk import KillSwitch, RiskGate

ROOT = Path(__file__).resolve().parents[1]
IST = MK.IST
MON = dt.datetime(2026, 11, 16, 11, 0, tzinfo=IST)            # Mon 16 Nov 2026: NSE, currency and MCX all trade; US daylight saving is over, so MCX closes 23:30
CRUDE, USD = "CRUDEOIL-MCX", "USDINR-CDS"
THESIS = "crude holding above the overnight range with rising open interest"


@pytest.fixture()
def cfg():
    return Config.load(ROOT / "config" / "quantdesk.yaml")


@pytest.fixture()
def rn(cfg, tmp_path):
    return R.Runner(cfg, Account(500_000), gate=RiskGate(cfg, kill=KillSwitch(tmp_path / "KILL")), kill_file=tmp_path / "KILL")


def board(now=MON, crude=(5800.0, 5801.0), usd=(84.5000, 84.5025), e_crude="2026-12-17", e_usd="2026-12-29", age=2.0, **extra):
    q = {CRUDE: dict(bid=crude[0], ask=crude[1], bid_qty=2000, ask_qty=2000, ltp=crude[0], age_s=age, s="mcx", e=e_crude),
         USD: dict(bid=usd[0], ask=usd[1], bid_qty=50000, ask_qty=50000, ltp=usd[0], age_s=age, s="cds", e=e_usd)}
    for k, v in extra.items():
        q[k] = v
    for k in (CRUDE, USD):
        if q[k].get("e") is None:
            q[k].pop("e")
    return {"now": int(now.timestamp() * 1000), "quotes": q}


def order(oid="fut-0001", now=MON, **kw):
    o = dict(id=oid, side="buy", symbol=CRUDE, lots=1, stop=5750.0, strategy="crude breakout", thesis=THESIS, queued_at=int(now.timestamp() * 1000) - 2000)
    o.update(kw)
    return o


def run(rn, orders, s=None, now=MON):
    return rn.step(s if s is not None else board(now), orders, False, now.astimezone(dt.timezone.utc))


def res(rep, oid="fut-0001"):
    return next(r for r in rep["results"] if r["id"] == oid)


# ---- opening ------------------------------------------------------------------------------------------------------------------------------
def test_a_long_fills_at_the_offer_and_moves_cash_only_by_its_fees(rn):
    r = res(run(rn, [order(target=5900.0)]))
    assert r["status"] == "filled", r
    assert r["fill"]["kind"] == "buy" and r["fill"]["price"] == 5801.0 and r["fill"]["qty"] == 100 and r["fill"]["stop"] == 5750.0 and r["fill"]["target"] == 5900.0
    p = rn.account.positions[CRUDE]
    assert p.instrument.kind == FUTURE and p.instrument.expiry == dt.date(2026, 12, 17) and p.segment == "mcx" and p.stop == 5750.0 and p.target == 5900.0
    assert rn.account.cash == pytest.approx(500_000 - r["fill"]["fees"])                        # margined: nothing like 5.8 lakh of notional leaves the cash
    assert rn.account.equity({CRUDE: 5800.0}) == pytest.approx(500_000 - r["fill"]["fees"] - 100.0)   # marked at the bid: one rupee a barrel under the price paid


def test_a_short_fills_at_the_bid_with_its_stop_above(rn):
    r = res(run(rn, [order(side="short", stop=5850.0, target=5700.0)]))
    assert r["status"] == "filled" and r["fill"]["kind"] == "sto" and r["fill"]["price"] == 5800.0
    assert rn.account.positions[CRUDE].qty == -100


def test_currency_futures_trade_with_their_own_lot_and_charges(rn, cfg):
    r = res(run(rn, [order(symbol=USD, lots=2, stop=84.40, strategy="usd bid", thesis="RBI absent, importer demand into month end")]))
    assert r["status"] == "filled" and r["fill"]["qty"] == 2000 and rn.account.positions[USD].segment == "nse_cds"
    inst = rn.account.positions[USD].instrument
    _, br = CostModel(cfg).fees(inst, 2000, 84.5025)
    assert br["stt"] == 0.0 and br["brokerage"] == pytest.approx(min(20.0, 0.0003 * 2000 * 84.5025))                # no STT on currency; 0.03% when it is under 20 rupees


def test_mcx_charges_ctt_on_the_sale_only(cfg):
    inst = Instrument(symbol=CRUDE, kind=FUTURE, underlying="CRUDEOIL", lot_size=100, expiry=dt.date(2026, 12, 17))
    _, buy = CostModel(cfg).fees(inst, 100, 5800.0)
    _, sell = CostModel(cfg).fees(inst, -100, 5800.0)
    assert buy["stt"] == 0.0 and sell["stt"] == pytest.approx(0.0001 * 580_000) and buy["stamp"] == pytest.approx(0.00002 * 580_000) and sell["stamp"] == 0.0
    assert buy["exchange"] == pytest.approx(0.000021 * 580_000) and buy["brokerage"] == 20.0


# ---- refusals ----------------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("kw, now, s, why", [
    (dict(stop=None), MON, None, "needs a stop"),
    (dict(stop=5850.0), MON, None, "must be below"),                                                    # a long's stop above the price
    (dict(side="short", stop=5750.0), MON, None, "must be above"),
    (dict(stop=5000.0), MON, None, "typo"),                                                             # 14% away
    (dict(lots=5, stop=5600.0), MON, None, "risk"),                                                     # 500 barrels x ~200 rupees: far over 2.5% of equity
    (dict(target=5790.0), MON, None, "target"),
    (dict(), MON, "near-expiry", "trading days away"),                                                  # the contract expires 19 Nov: inside its last five trading days
    (dict(), MON, "no-month", "contract month"),
    (dict(), MON.replace(hour=23, minute=20), None, "close"),                                           # within 15 minutes of 23:30
    (dict(), dt.datetime(2026, 11, 24, 10, 0, tzinfo=IST), None, "closed"),                             # Guru Nanak Jayanti: MCX trades only its evening session
    (dict(symbol="SILVERX-MCX"), MON, None, "not a mcx future"),
    (dict(symbol=USD, stop=84.4, now_late=True), MON.replace(hour=16, minute=50), None, "close"),       # currency closes at 17:00
])
def test_each_reason_to_refuse_a_futures_entry(rn, kw, now, s, why):
    kw = dict(kw)
    kw.pop("now_late", None)
    snapshot = board(now, e_crude="2026-11-19") if s == "near-expiry" else board(now, e_crude=None) if s == "no-month" else board(now)
    o = order(now=now, **kw)
    if o.get("stop") is None:
        o.pop("stop")
    r = res(run(rn, [o], snapshot, now))
    assert r["status"] == "refused" and any(why in x for x in r["reasons"]), r
    assert CRUDE not in rn.account.positions


def test_the_evening_of_an_nse_holiday_trades_mcx(rn):
    t = dt.datetime(2026, 11, 24, 18, 0, tzinfo=IST)
    assert res(run(rn, [order(now=t)], board(t), t))["status"] == "filled"


def test_margin_beyond_free_equity_is_refused(rn):
    t = MON
    gold = dict(bid=136000.0, ask=136010.0, bid_qty=500, ask_qty=500, ltp=136000.0, age_s=2.0, s="mcx", e="2026-12-04")
    r = res(run(rn, [order(symbol="GOLD-MCX", lots=4, stop=135990.0)], board(t, **{"GOLD-MCX": gold}), t))     # 4 kg of gold: about 5.4 lakh of margin at 10%
    assert r["status"] == "refused" and any("margin" in x for x in r["reasons"]), r


def test_an_option_cannot_be_shorted_and_one_futures_position_per_contract(rn):
    r = res(run(rn, [dict(order(oid="opt-0001"), symbol="NIFTY12NOV2624500CE", side="short")]), "opt-0001")
    assert r["status"] == "refused" and "future only" in r["reasons"][0]
    assert res(run(rn, [order()]))["status"] == "filled"
    r = res(run(rn, [order(oid="fut-0002")]), "fut-0002")
    assert r["status"] == "refused" and "already held" in r["reasons"][0]


def test_mcx_and_currency_do_not_trade_in_a_year_whose_calendar_is_not_entered(rn):
    t = dt.datetime(2027, 1, 4, 11, 0, tzinfo=IST)
    r = res(run(rn, [order(now=t)], board(t, e_crude="2027-01-19"), t))
    assert r["status"] == "refused" and any("not verified" in x for x in r["reasons"]), r


# ---- holding and closing -----------------------------------------------------------------------------------------------------------------
def test_the_stop_closes_a_long_at_the_bid_and_books_the_loss(rn):
    run(rn, [order()])
    fees_in = rn.account.fees
    t = MON + dt.timedelta(minutes=5)
    rep = run(rn, [], board(t, crude=(5749.0, 5750.0)), t)
    assert CRUDE not in rn.account.positions and any(f["action"] == "futures" and "stop" in f["why"][0] for f in rep["forced"])
    assert rn.account.realized == pytest.approx((5749.0 - 5801.0) * 100)
    assert rn.account.cash == pytest.approx(500_000 + (5749.0 - 5801.0) * 100 - rn.account.fees) and rn.account.fees > fees_in


def test_the_target_closes_a_short_at_the_offer(rn):
    run(rn, [order(side="short", stop=5850.0, target=5700.0)])
    t = MON + dt.timedelta(minutes=5)
    run(rn, [], board(t, crude=(5698.0, 5699.0)), t)
    assert CRUDE not in rn.account.positions and rn.account.realized == pytest.approx((5800.0 - 5699.0) * 100)


def test_futures_are_squared_off_before_the_close(rn):
    run(rn, [order(symbol=USD, stop=84.40, thesis="RBI absent, importer demand into month end")])
    t = MON.replace(hour=16, minute=56)
    rep = run(rn, [], board(t), t)
    assert USD not in rn.account.positions and any("square-off" in w for f in rep["forced"] if f["action"] == "futures" for w in f["why"])


def test_the_owner_closes_a_future_with_a_sell(rn):
    run(rn, [order(side="short", stop=5850.0)])
    t = MON + dt.timedelta(minutes=1)
    r = res(run(rn, [order(oid="fut-0002", now=t, side="sell", lots="all")], board(t), t), "fut-0002")
    assert r["status"] == "filled" and r["fill"]["kind"] == "btc" and CRUDE not in rn.account.positions


def test_a_position_is_never_priced_on_another_months_quote(rn):
    run(rn, [order()])
    t = MON + dt.timedelta(minutes=1)
    s = board(t, crude=(5500.0, 5501.0), e_crude="2027-01-19")                                       # the board's name now shows another month: its price is not this contract's
    assert CRUDE not in rn.marks(s, t)
    run(rn, [], s, t)
    assert CRUDE in rn.account.positions                                                             # not stopped out on the wrong month's price


def test_a_restart_rebuilds_the_future_with_its_stop_from_the_ledger(rn):
    run(rn, [order(target=5900.0)])
    again = Account.from_dict(json.loads(json.dumps(rn.account.to_dict())))
    p = again.positions[CRUDE]
    assert p.stop == 5750.0 and p.target == 5900.0 and p.instrument.expiry == dt.date(2026, 12, 17) and again.verify_ledger()
    tampered = rn.account.to_dict()
    tampered["positions"][CRUDE]["stop"] = 5000.0                                                   # a looser stop written into the saved file does not match the ledger
    with pytest.raises(ValueError):
        Account.from_dict(json.loads(json.dumps(tampered)))


def test_the_book_counts_a_future_at_its_stop(rn):
    run(rn, [order()])
    a = rn.account
    assert a.stress() == pytest.approx(a.cash + (5750.0 - 5801.0) * 100)
    assert a.open_value({CRUDE: 5800.0}) == pytest.approx((5800.0 - 5750.0) * 100)
    assert a.equity_lower_bound({}) == pytest.approx(a.cash + (5750.0 - 5801.0) * 100)            # no price: counted at its stop


def test_the_app_sees_the_future_with_its_stop(rn):
    run(rn, [order(target=5900.0)])
    pos = rn.summary(board(), MON)["positions"]
    assert pos[0]["kind"] == "future" and pos[0]["stop"] == 5750.0 and pos[0]["target"] == 5900.0 and pos[0]["segment"] == "mcx" and pos[0]["lots"] == 1


def test_an_option_fill_still_has_no_stop_and_a_future_fill_must(cfg):
    a = Account(500_000)
    opt = Instrument.option("NIFTY", dt.date(2026, 11, 17), 24500, "CE", 65)
    with pytest.raises(ValueError):
        a.apply_fill("buy", opt, "nse_fo", 65, 100.0, 20.0, MON.isoformat(), "s", "t", stop=90.0)
    fut = Instrument(symbol=CRUDE, kind=FUTURE, underlying="CRUDEOIL", lot_size=100, expiry=dt.date(2026, 12, 17))
    with pytest.raises(ValueError):
        a.apply_fill("buy", fut, "mcx", 100, 5800.0, 20.0, MON.isoformat(), "s", "t")
    with pytest.raises(ValueError):
        a.apply_fill("settle", fut, "mcx", 100, 5800.0, 0.0, MON.isoformat(), "s", "t")


def test_the_relay_queues_a_futures_short_with_its_stop_and_refuses_a_bad_one():
    import shutil
    import subprocess
    if shutil.which("node") is None:
        pytest.skip("Node is not installed")
    js = """import('./deploy/cloudflare/paper.js').then((m) => { const t = 'rejected at the overnight high with inventory build expected';
      console.log(JSON.stringify([m.cleanOrder({ id: 'fut-0001', side: 'short', symbol: 'CRUDEOIL-MCX', lots: 1, stop: 5850, target: 5700, strategy: 'fade', thesis: t }),
        m.cleanOrder({ id: 'fut-0002', side: 'short', symbol: 'CRUDEOIL-MCX', lots: 1, stop: -1, strategy: 'fade', thesis: t }),
        m.cleanOrder({ id: 'fut-0003', side: 'short', symbol: 'CRUDEOIL-MCX', lots: 1, stop: 5850, strategy: 'fade', thesis: 'short' })])); });"""
    out = subprocess.run(["node", "-e", js], cwd=ROOT, capture_output=True, text=True, timeout=60)
    good, bad_stop, bad_thesis = json.loads(out.stdout.strip().splitlines()[-1])
    assert good == {"id": "fut-0001", "side": "short", "symbol": "CRUDEOIL-MCX", "lots": 1, "strategy": "fade", "thesis": "rejected at the overnight high with inventory build expected", "stop": 5850, "target": 5700}
    assert bad_stop is None and bad_thesis is None
