"""MCX and currency OPTIONS on the paper desk (owner, 13 Nov 2026: "MCX and currency options should be treated in the same way" as index and stock options). PAPER MONEY ONLY.

What is pinned: they are bought (and sold as package legs) from the chain like NSE options, under the same names (a currency strike has decimals); each trades in its own segment
with its own charges and session; its slippage is modelled on its own tick; and it is sold from 15:20 on the trading day before its expiry, never held into it (an MCX option turns
into the future at expiry, a currency option expires at 12:30)."""
from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

from quantdesk.config import Config
from quantdesk.core.types import Instrument
from quantdesk.execution.costs import CostModel
from quantdesk.markets import sessions as MK
from quantdesk.paper import runner as R
from quantdesk.paper.account import Account
from quantdesk.paper.risk import KillSwitch, RiskGate

ROOT = Path(__file__).resolve().parents[1]
IST = MK.IST
MON = dt.datetime(2026, 11, 16, 11, 0, tzinfo=IST)
CRUDE_CE, CRUDE_CE2, USD_CE = "CRUDEOIL20NOV265800CE", "CRUDEOIL20NOV265900CE", "USDINR20NOV2684.25CE"
THESIS = "inventory draw expected, calls cheap against the realised move"


@pytest.fixture()
def cfg():
    return Config.load(ROOT / "config" / "quantdesk.yaml")


@pytest.fixture()
def rn(cfg, tmp_path):
    return R.Runner(cfg, Account(500_000), gate=RiskGate(cfg, kill=KillSwitch(tmp_path / "KILL")), kill_file=tmp_path / "KILL")


def board(now=MON, age=2.0):
    q = {CRUDE_CE: dict(bid=92.0, ask=92.6, bid_qty=2000, ask_qty=2000, ltp=92.3, age_s=age, s="opt", oi=4400),
         CRUDE_CE2: dict(bid=60.0, ask=60.5, bid_qty=2000, ask_qty=2000, ltp=60.2, age_s=age, s="opt"),
         USD_CE: dict(bid=0.1075, ask=0.11, bid_qty=500000, ask_qty=500000, ltp=0.1100, age_s=age, s="opt")}
    return {"now": int(now.timestamp() * 1000), "quotes": q}


def order(oid="opt-0001", now=MON, **kw):
    o = dict(id=oid, side="buy", symbol=CRUDE_CE, lots=1, strategy="crude calls", thesis=THESIS, queued_at=int(now.timestamp() * 1000) - 2000)
    o.update(kw)
    return o


def run(rn, orders, s=None, now=MON):
    return rn.step(s if s is not None else board(now), orders, False, now.astimezone(dt.timezone.utc))


def res(rep, oid="opt-0001"):
    return next(r for r in rep["results"] if r["id"] == oid)


def test_names_parse_with_decimal_strikes_only_where_they_exist(rn):
    i, why = R.parse_contract(USD_CE, rn.und, rn.lots, frozenset(rn.seg_of))
    assert why is None and i.strike == 84.25 and i.symbol == USD_CE and i.lot_size == 1000 and rn.segment(i) == "nse_cds"
    i, _ = R.parse_contract(CRUDE_CE, rn.und, rn.lots, frozenset(rn.seg_of))
    assert i.lot_size == 100 and rn.segment(i) == "mcx"
    assert R.parse_contract("NIFTY12NOV2624500.5CE", rn.und, rn.lots, frozenset(rn.seg_of))[0] is None
    assert Instrument.option("USDINR", dt.date(2026, 11, 20), 84.5, "PE", 1000).symbol == "USDINR20NOV2684.5PE"


def test_an_mcx_option_is_bought_from_the_chain_in_its_own_segment_with_its_own_charges(rn, cfg):
    r = res(run(rn, [order()]))
    assert r["status"] == "filled", r
    p = rn.account.positions[CRUDE_CE]
    assert p.segment == "mcx" and p.qty == 100 and r["fill"]["price"] == pytest.approx(92.6, abs=0.31)      # at the offer, plus at most the modelled impact in crude's own ticks
    _, sell = CostModel(cfg).fees(p.instrument, -100, 92.0, segment="mcx")
    assert sell["brokerage"] == 20.0 and sell["stt"] == pytest.approx(0.0005 * 9200) and sell["exchange"] == pytest.approx(0.000418 * 9200)
    _, nse = CostModel(cfg).fees(p.instrument, -100, 92.0)
    assert nse["stt"] != sell["stt"]                                                              # NSE's option schedule is not charged to an MCX option


def test_a_currency_option_is_bought_with_its_own_tick_and_no_stt(rn, cfg):
    r = res(run(rn, [order(symbol=USD_CE, lots=2, thesis="RBI absent, calls cheap into month end importer demand")]))
    assert r["status"] == "filled", r
    assert r["fill"]["qty"] == 2000 and r["fill"]["price"] <= 0.11 + 3 * 0.0025 + 1e-9                    # the impact is in 0.0025 ticks, not NSE's 0.05
    _, br = CostModel(cfg).fees(rn.account.positions[USD_CE].instrument, -2000, 0.11, segment="nse_cds")
    assert br["stt"] == 0.0 and br["brokerage"] == 20.0


def test_mcx_options_trade_in_the_evening_and_currency_options_stop_at_their_close(rn):
    t = MON.replace(hour=21)
    assert res(run(rn, [order(now=t)], board(t), t))["status"] == "filled"
    t2 = MON.replace(hour=17, minute=10)
    r = res(run(rn, [order(oid="opt-0002", now=t2, symbol=USD_CE, thesis="RBI absent, calls cheap into month end")], board(t2), t2), "opt-0002")
    assert r["status"] == "refused" and any("closed" in x for x in r["reasons"]), r


def test_they_are_sold_from_1520_on_the_trading_day_before_expiry_and_not_bought_then(rn):
    run(rn, [order()])
    t = dt.datetime(2026, 11, 19, 15, 21, tzinfo=IST)                                           # Thu: the trading day before the 20 Nov expiry
    rep = run(rn, [order(oid="opt-0003", now=t, symbol=CRUDE_CE2)], board(t), t)
    assert CRUDE_CE not in rn.account.positions and any(f["action"] == "sell expiring" for f in rep["forced"])
    r = res(rep, "opt-0003")
    assert r["status"] == "refused" and "trading day before its expiry" in r["reasons"][0] and "turns into the future" in r["reasons"][0]


def test_an_mcx_spread_opens_as_one_package_in_the_mcx_segment(rn):
    pkg = {"id": "pkg-0001", "side": "package", "legs": [{"symbol": CRUDE_CE, "side": "buy", "lots": 1}, {"symbol": CRUDE_CE2, "side": "sell", "lots": 1}],
           "strategy": "crude call spread", "thesis": THESIS, "queued_at": int(MON.timestamp() * 1000) - 2000}
    r = res(run(rn, [pkg]), "pkg-0001")
    assert r["status"] == "filled", r
    assert {p.segment for p in rn.account.positions.values()} == {"mcx"} and rn.account.positions[CRUDE_CE2].qty == -100
