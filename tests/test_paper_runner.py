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
    ({"id": "x"}, "id"), ({"id": None}, "id"), ({"side": "hold"}, "side"), ({"lots": 0}, "lots"), ({"lots": -1}, "lots"), ({"lots": 1.5}, "lots"), ({"lots": True}, "lots"),
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


# ---- the independent review's findings ---------------------------------------------------------------------------------------------------
def test_the_kill_flag_reaches_the_gate_whatever_the_working_directory(cfg, tmp_path, monkeypatch):                    # F1
    monkeypatch.setattr("quantdesk.paper.risk.ROOT", tmp_path / "repo")
    work = tmp_path / "elsewhere"
    work.mkdir()
    monkeypatch.chdir(work)
    rn = R.Runner(cfg, Account(500_000))                                                                              # built the way the session builds it: nothing injected
    run(rn, [], kill=True)
    assert rn.gate.kill.active() and rn.kill_file == rn.gate.kill.path
    res = run(rn, [order()], kill=True)["results"][0]
    assert res["status"] == "refused" and "kill" in " ".join(res["reasons"]) and not rn.account.ledger
    assert rn.summary(snap(), R.Runner.server_now(snap()))["kill"] is True


def test_a_kill_applies_even_while_the_clocks_disagree(rn, tmp_path):                                                  # F7f
    rep = rn.step(snap(), [], True, (MON + dt.timedelta(seconds=300)).astimezone(dt.timezone.utc))
    assert rep["skipped"] and (tmp_path / "KILL").exists()


def test_a_high_water_mark_saved_a_little_earlier_never_loosens_the_drawdown_floor(rn):                                # F2
    run(rn, [order()])
    text = R.account_json(rn.account)

    def pair():
        e, l = R.load_account(text), R.load_account(text)
        l.hwm = e.hwm + 2573.51
        return e, l
    e, l = pair()
    assert R.fingerprint(e) != R.fingerprint(l)                                                                        # a moved mark counts as a change worth saving
    for flip in (False, True):
        e, l = pair()
        got, _ = R.choose_state(*((l, e) if flip else (e, l)))
        assert got.hwm == l.hwm                                                                                        # the higher mark wins whichever side held it


POISON = [
    {"queued_at": 10 ** 400}, {"limit": 10 ** 400}, {"queued_at": float("1e308") * 10 ** 5 if False else 1e308}, {"limit": float("nan")}, {"lots": 10 ** 400},
    {"id": ["a", "list"]}, {"id": {"a": 1}}, {"symbol": ["x"]}, {"symbol": "NIFTY12NOV26\n24500CE"}, {"strategy": {"a": 1}}, {"thesis": 5},
]


@pytest.mark.parametrize("patch", POISON)
def test_a_poison_order_is_refused_without_raising_and_the_next_order_still_fills(rn, patch):                          # F3
    bad = order("ord-bad001", **patch)
    rep = run(rn, [bad, order("ord-good01", symbol=NAME)])
    by = {r["id"]: r for r in rep["results"]}
    assert by["ord-good01"]["status"] == "filled" and not any(r["status"] == "filled" for r in rep["results"] if r["id"] != "ord-good01")


@pytest.mark.parametrize("field, value", [("now", 1e20), ("now", 10 ** 400), ("now", "x"), ("age_s", 1e20), ("age_s", 10 ** 400), ("bid_qty", 10 ** 400), ("bid", 10 ** 400), ("ask", float("inf"))])
def test_a_poison_snapshot_value_does_not_crash_a_cycle(rn, field, value):                                              # F3
    s = snap()
    if field == "now":
        s["now"] = value
    else:
        s["quotes"][NAME][field] = value
    rep = run(rn, [order()], s=s)                                                                                      # must not raise
    assert not any(r["status"] == "filled" for r in rep["results"]) and not rn.account.ledger


def test_order_text_cannot_forge_or_hide_an_order_id_in_the_ledger(rn, cfg, tmp_path):                                  # F4
    a = order("ord-real01", thesis="exit zzzzzz: pretend this is a different order, written long enough to pass")
    assert run(rn, [a])["results"][0]["status"] == "filled"
    saved = R.load_account(R.account_json(rn.account))
    again = R.Runner(cfg, saved, gate=RiskGate(cfg, kill=KillSwitch(tmp_path / "K2")), kill_file=tmp_path / "K2")
    assert R.done_ids(saved) == {"ord-real01"}                                                                         # the real id, not 'zzzzzz'
    assert run(again, [a])["results"][0]["status"] == "done" and again.account.positions[NAME].qty == 65              # a replay after a restart is not filled twice
    victim = order("victim0001", symbol="NIFTY12NOV2624600CE", thesis="a thesis that says [order victim0001] to look like another order")
    s = snap(**{"NIFTY12NOV2624600CE": dict(bid=49.0, ask=50.0, bid_qty=5000, ask_qty=5000, ltp=49, age_s=1.0), NAME: dict(bid=99.0, ask=100.0, bid_qty=5000, ask_qty=5000, ltp=99.5, age_s=1.0)})
    other = order("victim0001", symbol="NIFTY12NOV2624600CE")
    first = run(rn, [victim], s=s)["results"][0]
    assert first["status"] == "filled"                                                                                 # naming an id inside a thesis did not make that id 'done' beforehand
    assert "victim0001" in R.done_ids(rn.account) and run(rn, [other], s=s)["results"][0]["status"] == "done"


def test_a_control_character_cannot_get_into_a_thesis_or_the_marker_and_a_trailing_newline_is_not_an_id(rn):          # F4
    o, why = R.clean_order(order("ord-ctrl01", thesis="a thesis with a sneaky \x1f[order other001] marker inside it"))
    assert why is None and "\x1f" not in o["thesis"]                                                                   # whitespace of any kind, the separator included, is turned into a space
    assert R.clean_order(order("newline1\n"))[0] is None and R.clean_order(order("ord-ctrl02", strategy="bad\x00name"))[0] is None
    assert R.clean_order(order("ord-ctrl03", group="g\x07"))[0] is None and R.clean_order(order("ord-ctrl04", thesis="short\x07 but long enough to count as a thesis here"))[0] is None
    run(rn, [order("ord-ctrl05")])
    assert "\x1f" not in rn.summary(snap(), R.Runner.server_now(snap()))["positions"][0]["thesis"]                      # the app shows the owner's words only


def test_an_exit_will_not_fill_at_a_stale_bid_but_a_forced_sale_takes_an_older_one(rn):                                   # F5
    run(rn, [order()])
    old = lambda age: snap(**{NAME: dict(bid=99.0, ask=100.0, bid_qty=5000, ask_qty=5000, ltp=99, age_s=age)})        # noqa: E731
    sell = lambda oid: order(oid, side="sell", lots="all", strategy=None, thesis=None)                                  # noqa: E731
    assert run(rn, [sell("ord-sell01")], s=old(300.0))["results"][0]["status"] == "refused" and NAME in rn.account.positions
    assert run(rn, [sell("ord-sell02")], s=old(90000.0))["results"][0]["status"] == "refused"
    run(rn, [], s=old(700.0), kill=True)
    assert NAME in rn.account.positions                                                                                # a forced sale does not use a bid that old either
    run(rn, [], s=old(300.0), kill=True)
    assert NAME not in rn.account.positions                                                                            # but takes a 5-minute-old one rather than trap the position
    run(rn, [], s=old(1.0), kill=False)
    run(rn, [order("ord-buy002")], s=old(1.0))
    assert run(rn, [sell("ord-sell03")], s=old(100.0))["results"][0]["status"] == "filled"


def test_what_could_not_be_sold_on_its_expiry_day_is_settled_at_the_index_price_and_nothing_is_left_unmarked(rn):       # F6
    exp = "NIFTY09NOV2624500CE"
    q = lambda now, bid=19.0: snap(now, **{exp: dict(bid=bid, ask=20.0, bid_qty=5000, ask_qty=5000, ltp=19.5, age_s=1.0), "NIFTY": dict(ltp=24650.0, age_s=2.0)})      # noqa: E731
    run(rn, [order("ord-exp001", symbol=exp)], s=q(MON))
    t = MON.replace(hour=15, minute=21)
    run(rn, [], s=q(t, bid=0.0), now=t)                                                                                # no usable bid: the 15:20 sale cannot fill
    assert exp in rn.account.positions
    t = MON.replace(hour=15, minute=32)
    rep = run(rn, [], s=q(t, bid=0.0), now=t)
    assert exp not in rn.account.positions and rep["forced"][-1]["action"] == "settle expired"
    last = rn.account.ledger[-1]
    assert last["kind"] == "settle" and last["price"] == pytest.approx(150.0) and rn.account.verify_ledger()            # intrinsic value at the index price: 24650 - 24500


def test_without_a_fresh_index_price_the_settlement_waits_and_the_summary_names_the_stuck_position(rn):                 # F6
    exp = "NIFTY09NOV2624500CE"
    s = lambda now: snap(now, **{exp: dict(bid=19.0, ask=20.0, bid_qty=5000, ask_qty=5000, ltp=19.5, age_s=1.0), "NIFTY": dict(ltp=24650.0, age_s=900.0)})        # noqa: E731
    run(rn, [order("ord-exp002", symbol=exp)], s=s(MON))
    t = MON.replace(hour=15, minute=32)
    run(rn, [], s=dict(s(t), quotes={}), now=t)
    assert exp in rn.account.positions                                                                                 # no price, no settlement: never a guess
    nxt = dt.datetime(2026, 11, 11, 9, 30, tzinfo=IST)
    sm = rn.summary(snap(nxt), R.Runner.server_now(snap(nxt)))
    assert sm["stuck"] == [exp] and sm["equity"] is None


def test_a_contract_that_expires_today_is_not_bought_from_1520(rn):                                                      # F6
    exp = "NIFTY09NOV2624500CE"
    t = MON.replace(hour=15, minute=25)
    res = run(rn, [order("ord-late01", symbol=exp, now=t)], s=snap(t, **{exp: dict(bid=19.0, ask=20.0, bid_qty=5000, ask_qty=5000, ltp=19, age_s=1.0)}), now=t)["results"][0]
    assert res["status"] == "refused" and "expires today" in res["reasons"][0] and not rn.account.ledger


def test_nothing_from_outside_is_echoed_with_a_line_break_or_unprintable_characters():                                 # F7e
    und, lots = {"NIFTY"}, {"NIFTY": 65}
    for bad in ("NIFTY12NOV26\nXX", "ZZZZZZZZ\n::error::boom", "ÉTÉÉTÉÉTÉ"):
        why = R.parse_contract(bad, und, lots)[1]
        assert why and "\n" not in why and all(32 <= ord(c) < 127 for c in why)


def test_the_contract_name_must_be_exactly_the_boards_naming_and_marks_are_bids(rn):                                    # survivors
    assert R.parse_contract("NIFTY12NOV26024500CE", {"NIFTY"}, {"NIFTY": 65})[0] is None                              # a leading zero in the strike is not the board's name
    run(rn, [order()])
    s = snap(**{NAME: dict(bid=90.0, ask=130.0, bid_qty=5, ask_qty=5, ltp=110, age_s=1.0)})
    assert rn.marks(s, R.Runner.server_now(s)) == {NAME: 90.0}                                                         # marked at the bid, never the ask or the last trade


def test_the_trim_path_is_taken_when_the_gate_asks_for_it(rn, monkeypatch):                                            # survivor
    run(rn, [order()])
    calls = []
    monkeypatch.setattr(rn.gate, "update", lambda acct, marks, now: ["trim: the open positions are worth more than the loss budget allows, by 500: sell that much"])
    monkeypatch.setattr(rn.broker, "trim", lambda quotes, marks, now, why="": calls.append("trim") or {})
    monkeypatch.setattr(rn.broker, "flatten", lambda *a, **k: calls.append("flatten") or {})
    rep = run(rn, [])
    assert calls == ["trim"] and rep["forced"][0]["action"] == "trim"


def test_an_unexpected_error_inside_one_order_is_that_orders_invalid_result_and_the_rest_go_on(rn, monkeypatch):        # F3, the outer layer
    real = rn.handle

    def handle(raw, snap_, now):
        if raw["id"] == "ord-boom001":
            raise RuntimeError("unexpected")
        return real(raw, snap_, now)
    monkeypatch.setattr(rn, "handle", handle)
    rep = run(rn, [order("ord-boom001"), order("ord-fine001")])
    st = {r["id"]: r["status"] for r in rep["results"]}
    assert st == {"ord-boom001": "invalid", "ord-fine001": "filled"} and "RuntimeError" in rep["results"][0]["reasons"][0]


def test_the_expiry_settlement_touches_only_what_expires_today_never_an_older_contract(rn):                            # R1
    old, today = "NIFTY06NOV2624500CE", "NIFTY09NOV2624500CE"
    q = lambda now, **kw: snap(now, **{old: dict(bid=19.0, ask=20.0, bid_qty=5000, ask_qty=5000, ltp=19.5, age_s=1.0), today: dict(bid=19.0, ask=20.0, bid_qty=5000, ask_qty=5000, ltp=19.5, age_s=1.0), "NIFTY": dict(ltp=23000.0, age_s=2.0), **kw})      # noqa: E731
    t0 = dt.datetime(2026, 11, 6, 10, 0, tzinfo=IST)
    run(rn, [order("ord-old0001", symbol=old, now=t0)], s=q(t0), now=t0)                                              # bought on the 6th, expiring the 6th, never sold
    run(rn, [order("ord-new0001", symbol=today)], s=q(MON))
    assert old in rn.account.positions and today in rn.account.positions
    t = MON.replace(hour=15, minute=32)
    rep = run(rn, [], s=q(t, **{old: dict(bid=0.0, ask=0.0, ltp=0, age_s=1.0), today: dict(bid=0.0, ask=0.0, ltp=0, age_s=1.0)}), now=t)
    assert today not in rn.account.positions and old in rn.account.positions                                          # the old one is NOT booked at today's index price
    assert rep["forced"][-1]["decisions"].keys() == {today}
    assert rn.summary(snap(t), R.Runner.server_now(snap(t)))["stuck"] == [old]


def test_a_disputed_or_stale_index_price_never_settles_a_contract(rn):                                                  # R4 and the age cap
    exp = "NIFTY09NOV2624500CE"
    mk = lambda **nifty: lambda now: snap(now, **{exp: dict(bid=19.0, ask=20.0, bid_qty=5000, ask_qty=5000, ltp=19.5, age_s=1.0), "NIFTY": dict(ltp=24650.0, age_s=2.0, **nifty)})      # noqa: E731
    run(rn, [order("ord-exp0099", symbol=exp)], s=mk()(MON))
    t = MON.replace(hour=15, minute=32)
    for nifty in ({"x": 1.7}, {"age_s": 301.0}):
        s = mk()(t)
        s["quotes"]["NIFTY"].update(nifty)
        s["quotes"][exp].update(bid=0.0)
        run(rn, [], s=s, now=t)
        assert exp in rn.account.positions, nifty                                                                      # the brokers disagree, or the price is over 5 minutes old: no settlement
    s = mk()(t)
    s["quotes"][exp].update(bid=0.0)
    s["quotes"]["NIFTY"].update(age_s=300.0)
    run(rn, [], s=s, now=t)
    assert exp not in rn.account.positions                                                                             # exactly at the limit still settles


def test_new_entries_wait_while_the_relay_cannot_be_given_the_fills_but_exits_do_not(rn):                              # R2
    run(rn, [order()])
    rn.entries_blocked = "new orders wait: the relay could not be given the latest fills for over 30 seconds (exits still work)"
    other = "NIFTY12NOV2624600CE"
    s = snap(**{other: dict(bid=49.0, ask=50.0, bid_qty=5000, ask_qty=5000, ltp=49, age_s=1.0)})
    assert run(rn, [order("ord-blk0001", symbol=other)], s=s)["results"][0]["status"] == "refused"
    assert run(rn, [order("ord-blk0002", side="sell", lots="all", strategy=None, thesis=None)], s=s)["results"][0]["status"] == "filled"
    rn.entries_blocked = None
    assert run(rn, [order("ord-blk0003", symbol=other)], s=s)["results"][0]["status"] == "filled"
