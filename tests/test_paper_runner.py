"""The manual paper runner (quantdesk/paper/runner.py): the owner's queued paper orders go through the REAL risk gate, broker and account. Every refusal here
comes from the gate or from the runner's own shape checks; nothing is faked except the relay's snapshot."""
import datetime as dt
import json
import re
from pathlib import Path

import pytest

from quantdesk.config import Config
from quantdesk.core.types import Instrument
from quantdesk.markets import sessions as MK
from quantdesk.paper import runner as R
from quantdesk.paper.account import Account
from quantdesk.paper.risk import KillSwitch, RiskGate

ROOT = Path(__file__).resolve().parents[1]
IST = MK.IST
MON = dt.datetime(2026, 11, 9, 10, 0, tzinfo=IST)          # a Monday, an NSE trading day, inside the session
NAME = "NIFTY12NOV2624500CE"


@pytest.fixture()
def cfg():
    return Config.load(ROOT / "config" / "quantdesk.yaml")


@pytest.fixture()
def rn(cfg, tmp_path):
    acct = Account(500_000)
    gate = RiskGate(cfg, kill=KillSwitch(tmp_path / "KILL"))
    return R.Runner(cfg, acct, gate=gate, kill_file=tmp_path / "KILL")


def snap(now=MON, **quotes):
    q = {NAME: dict(bid=99.0, ask=100.0, bid_qty=5000, ask_qty=5000, ltp=99.5, age_s=2.0)}
    q.update(quotes)
    return {"now": int(now.timestamp() * 1000), "quotes": q}


def order(oid="ord-0001", now=MON, **kw):
    o = dict(id=oid, side="buy", symbol=NAME, lots=1, strategy="breakout", thesis="range break with rising volume on the 30 minute chart", queued_at=int(now.timestamp() * 1000) - 3000)
    o.update(kw)
    return o


def run(rn, orders, s=None, kill=False, now=MON):
    return rn.step(s or snap(now), orders, kill, now.astimezone(dt.timezone.utc))


# ---- shapes ---------------------------------------------------------------------------------------------------------------------
def test_contract_names_parse_only_for_the_papers_own_underlyings():
    und, lots = {"NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY"}, {"NIFTY": 65, "BANKNIFTY": 30, "SENSEX": 20}
    i, why = R.parse_contract(NAME, und, lots)
    assert why is None and i.underlying == "NIFTY" and i.strike == 24500 and i.right == "CE" and i.expiry == dt.date(2026, 11, 12) and i.lot_size == 65 and i.symbol == NAME
    assert R.parse_contract("BANKNIFTY12NOV2652000PE", und, lots)[0].underlying == "BANKNIFTY"                       # BANKNIFTY is not read as NIFTY
    for bad in ("SENSEX12NOV2680000CE", "RELIANCE12NOV261400CE", "nifty12nov2624500ce", "NIFTY31FEB2624500CE", "NIFTY12NOV26CE", "NIFTY12NOV2624500XX", "", None, 5, "NIFTY12NOV2624500.5CE"):
        assert R.parse_contract(bad, und, lots)[0] is None, bad
    assert R.parse_contract("FINNIFTY12NOV2624500CE", und, lots)[0] is None                                           # an underlying with no known lot size


@pytest.mark.parametrize("patch, word", [
    ({"id": "x"}, "id"), ({"id": None}, "id"), ({"side": "short"}, "side"), ({"lots": 0}, "lots"), ({"lots": -1}, "lots"), ({"lots": 1.5}, "lots"), ({"lots": True}, "lots"),
    ({"lots": "all"}, "lots"), ({"lots": 10**6}, "lots"), ({"thesis": "buy it"}, "thesis"), ({"thesis": None}, "thesis"), ({"strategy": ""}, "strategy"), ({"limit": -3}, "limit"),
    ({"limit": "100"}, "limit"), ({"group": "g" * 41}, "group")])
def test_a_malformed_order_is_refused_with_its_reason(rn, patch, word):
    res = run(rn, [order(**patch)])["results"][0]
    assert res["status"] == "invalid" and word in res["reasons"][0] and not rn.account.ledger


def test_a_sell_may_say_all_and_needs_no_thesis():
    o, why = R.clean_order({"id": "sell-0001", "side": "sell", "symbol": NAME, "lots": "all", "queued_at": 1})
    assert why is None and o["lots"] == "all"


# ---- a normal buy and sell -----------------------------------------------------------------------------------------------------------
def test_a_buy_fills_at_the_ask_through_the_gate_and_carries_its_thesis_and_order_id(rn):
    rep = run(rn, [order()])
    res = rep["results"][0]
    assert res["status"] == "filled" and res["fill"]["price"] == 100.0 and res["fill"]["qty"] == 65 and res["fill"]["fees"] > 0 and res["fill"]["symbol"] == NAME
    pos = rn.account.positions[NAME]
    assert pos.qty == 65 and "[order ord-0001]" in pos.thesis and pos.strategy == "breakout"
    assert rn.account.verify_ledger() and rn.account.day == "2026-11-09"                                           # the gate's day figures were brought up to date


def test_a_sell_fills_at_the_bid_and_all_sells_everything(rn):
    run(rn, [order()])
    res = run(rn, [order("ord-0002", side="sell", lots="all", strategy=None, thesis=None)])["results"][0]
    assert res["status"] == "filled" and res["fill"]["price"] == 99.0 and NAME not in rn.account.positions
    assert "exit ord-0002" in rn.account.ledger[-1]["thesis"]


def test_selling_what_is_not_held_is_refused(rn):
    res = run(rn, [order("ord-0003", side="sell", lots=1, strategy=None, thesis=None)])["results"][0]
    assert res["status"] == "refused" and "holding 0" in res["reasons"][0]


def test_a_limit_price_protects_the_owner_from_a_move(rn):
    assert run(rn, [order(limit=99.5)])["results"][0]["status"] == "refused" and not rn.account.positions         # offer 100 is above a 99.5 limit
    assert run(rn, [order("ord-0004", limit=100.0)])["results"][0]["status"] == "filled"
    res = run(rn, [order("ord-0005", side="sell", lots="all", strategy=None, thesis=None, limit=99.5)])["results"][0]
    assert res["status"] == "refused" and NAME in rn.account.positions                                              # bid 99 is below a 99.5 limit


# ---- nothing is done twice, nothing stale is done -------------------------------------------------------------------------------------
def test_the_same_order_is_never_filled_twice_even_after_a_restart(rn, cfg, tmp_path):
    run(rn, [order()])
    assert run(rn, [order()])["results"][0]["status"] == "done" and rn.account.positions[NAME].qty == 65
    saved = R.load_account(R.account_json(rn.account))                                                              # the runner restarts from its saved account
    again = R.Runner(cfg, saved, gate=RiskGate(cfg, kill=KillSwitch(tmp_path / "K2")), kill_file=tmp_path / "K2")
    assert run(again, [order()])["results"][0]["status"] == "done" and again.account.positions[NAME].qty == 65


def test_an_order_that_waited_too_long_or_has_no_queue_time_is_not_executed(rn):
    old = order(queued_at=int(MON.timestamp() * 1000) - 200_000)
    assert run(rn, [old])["results"][0]["status"] == "expired"
    assert run(rn, [order("ord-0006", queued_at=None)])["results"][0]["status"] == "expired"
    assert run(rn, [order("ord-0007", queued_at=int(MON.timestamp() * 1000) + 600_000)])["results"][0]["status"] == "expired"      # from the future
    assert not rn.account.ledger


def test_a_clock_that_disagrees_with_the_relay_does_nothing(rn):
    rep = rn.step(snap(), [order()], False, (MON + dt.timedelta(seconds=300)).astimezone(dt.timezone.utc))
    assert rep["skipped"] and not rn.account.ledger
    assert rn.step({"quotes": {}}, [order()], False, MON)["skipped"]                                               # no time on the snapshot


# ---- the gate's refusals come through ---------------------------------------------------------------------------------------------
@pytest.mark.parametrize("s, o, word", [
    (snap(**{NAME: dict(bid=99.0, ask=100.0, ltp=99, age_s=90.0)}), {}, "old"),                                      # a stale quote
    (snap(**{NAME: dict(bid=0, ask=100.0, ltp=99, age_s=1.0)}), {}, "two-sided"),                                      # one-sided
    (snap(**{NAME: dict(bid=101.0, ask=100.0, ltp=99, age_s=1.0)}), {}, "two-sided"),                                  # crossed
    (snap(**{NAME: dict(bid=99.0, ask=100.0, ask_qty=10, bid_qty=10, ltp=99, age_s=1.0)}), {}, "on offer"),             # more than the displayed size
    (snap(**{NAME: dict(bid=99.0, ask=300.0, ltp=99, age_s=1.0)}), {"lots": 1}, "risk"),                               # 65 x 300 is over 2.5% of equity
    (snap(), {"symbol": "NIFTY12NOV2624500"}, "not an option"),
    (snap(), {"symbol": "SENSEX12NOV2680000CE"}, "not an option"),
])
def test_what_the_gate_or_the_board_refuses_is_refused_and_nothing_is_recorded(rn, s, o, word):
    res = run(rn, [order(**o)], s=s)["results"][0]
    assert res["status"] == "refused" and word in " ".join(res["reasons"]) and not rn.account.ledger


def test_no_quote_on_the_board_is_a_refusal_not_a_guess(rn):
    s = snap()
    del s["quotes"][NAME]
    res = run(rn, [order()], s=s)["results"][0]
    assert res["status"] == "refused" and "two-sided" in " ".join(res["reasons"])


def test_the_market_being_closed_refuses_the_entry(rn):
    late = MON.replace(hour=16, minute=0)
    res = run(rn, [order(now=late)], now=late)["results"][0]
    assert res["status"] == "refused" and "closed" in " ".join(res["reasons"])


def test_a_holiday_refuses_the_entry(rn):
    hol = dt.datetime(2026, 11, 10, 10, 0, tzinfo=IST)                                                              # Diwali Balipratipada
    res = run(rn, [order(now=hol)], now=hol)["results"][0]
    assert res["status"] == "refused" and not rn.account.ledger


def test_there_is_still_no_cap_on_how_many_trades_only_the_loss_budget(rn):
    held = {}
    for i in range(1, 4):
        name = f"NIFTY12NOV26{24500 + 50 * i}CE"
        held[name] = dict(bid=29.0, ask=30.0, bid_qty=5000, ask_qty=5000, ltp=29.5, age_s=1.0)
        s = snap(**held)                                                                                          # the board carries every held contract: equity must be known
        assert run(rn, [order(f"ord-1{i:03d}", symbol=name)], s=s)["results"][0]["status"] == "filled"
    assert len(rn.account.positions) == 3


# ---- the brakes ------------------------------------------------------------------------------------------------------------------------
def test_the_kill_flag_flattens_everything_and_blocks_new_entries_until_it_is_cleared(rn, tmp_path):
    run(rn, [order()])
    rep = run(rn, [order("ord-0008", symbol="NIFTY12NOV2624600CE")], s=snap(**{"NIFTY12NOV2624600CE": dict(bid=49.0, ask=50.0, bid_qty=5000, ask_qty=5000, ltp=49, age_s=1.0)}), kill=True)
    assert (tmp_path / "KILL").exists() and not rn.account.positions
    assert rep["forced"] and rep["forced"][0]["action"] == "flatten" and rep["results"][0]["status"] == "refused" and "kill" in " ".join(rep["results"][0]["reasons"])
    assert rn.account.ledger[-1]["kind"] == "sell" and rn.account.verify_ledger()
    assert run(rn, [order("ord-0009")], kill=True)["results"][0]["status"] == "refused"
    assert run(rn, [order("ord-0010")], kill=False)["results"][0]["status"] == "filled" and not (tmp_path / "KILL").exists()   # the flag cleared: trading resumes


def test_a_position_that_expires_today_is_sold_from_1520_and_not_before(rn):
    exp = "NIFTY09NOV2624500CE"                                                                                    # expires on the Monday itself
    s = lambda now: snap(now, **{exp: dict(bid=19.0, ask=20.0, bid_qty=5000, ask_qty=5000, ltp=19.5, age_s=1.0)})   # noqa: E731
    assert run(rn, [order("ord-0011", symbol=exp)], s=s(MON))["results"][0]["status"] == "filled"
    t1 = MON.replace(hour=15, minute=19)
    run(rn, [], s=s(t1), now=t1)
    assert exp in rn.account.positions
    t2 = MON.replace(hour=15, minute=21)
    rep = run(rn, [], s=s(t2), now=t2)
    assert exp not in rn.account.positions and rep["forced"][0]["action"] == "sell expiring"


def test_a_held_position_with_no_fresh_quote_is_unmarked_so_the_gate_fails_closed(rn):
    run(rn, [order()])
    s = snap()
    s["quotes"][NAME]["age_s"] = 1200.0
    assert rn.marks(s, R.Runner.server_now(s)) == {}
    res = run(rn, [order("ord-0012", symbol="NIFTY12NOV2624600CE")], s=snap(**{"NIFTY12NOV2624600CE": dict(bid=49.0, ask=50.0, bid_qty=5000, ask_qty=5000, ltp=49, age_s=1.0), NAME: dict(bid=99, ask=100, ltp=99, age_s=1200.0)}))["results"][0]
    assert res["status"] == "refused" and "equity is unknown" in " ".join(res["reasons"])


# ---- state ---------------------------------------------------------------------------------------------------------------------------
def test_the_summary_is_plain_json_with_no_nan_and_shows_the_thesis_and_the_ledger(rn):
    run(rn, [order()])
    sm = rn.summary(snap(), R.Runner.server_now(snap()))
    text = json.dumps(sm, allow_nan=False)
    assert sm["equity"] < 500_000 and sm["positions"][0]["symbol"] == NAME and sm["positions"][0]["lots"] == 1 and "range break" in sm["positions"][0]["thesis"]
    assert sm["ledger_ok"] and sm["ledger_len"] == 1 and sm["ledger_tail"][0]["symbol"] == NAME and sm["kill"] is False and text
    bad = snap()
    bad["quotes"][NAME]["age_s"] = 5000.0
    assert json.dumps(rn.summary(bad, R.Runner.server_now(bad)), allow_nan=False)                                  # an unknown equity is null, not NaN


def test_choosing_the_state_to_continue_from(rn, cfg):
    run(rn, [order()])
    longer = R.load_account(R.account_json(rn.account))
    empty = Account(500_000)
    assert R.choose_state(None, None)[0] is None
    assert R.choose_state(longer, None)[0] is longer and R.choose_state(None, longer)[0] is longer
    assert R.choose_state(empty, longer)[0] is longer and R.choose_state(longer, empty)[0] is longer              # the longer chain wins when the other is its prefix
    other = Account(500_000)
    other.apply_fill("buy", Instrument.option("NIFTY", dt.date(2026, 11, 12), 24000, "CE", 65), "nse_fo", 65, 50.0, 10.0, MON.isoformat(), "x", "a different history")
    got, note = R.choose_state(longer, other)
    assert got is None and "different histories" in note                                                           # two different histories: refuse, do not pick
    assert R.choose_state(longer, Account(400_000))[0] is None                                                     # a different starting capital


def test_a_tampered_saved_account_does_not_load(rn):
    run(rn, [order()])
    d = rn.account.to_dict()
    d["cash"] += 1000
    with pytest.raises(ValueError):
        R.load_account(json.dumps(d))
    assert R.load_account(None) is None and R.load_account("") is None


def test_the_runner_has_no_network_no_credentials_and_no_broker():
    src = (ROOT / "quantdesk/paper/runner.py").read_text(encoding="utf-8")
    code = re.sub(r'""".*?"""', "", src, flags=re.S)
    assert not re.search(r"import (requests|urllib|socket|subprocess|http)|os\.environ|getenv|token|secret|password|kotak|kite|place_order", code, re.I)
