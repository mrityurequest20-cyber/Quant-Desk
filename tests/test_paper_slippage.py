"""Slippage on the paper desk (quantdesk/paper/slippage.py and its use in the broker, the account's sealed ledger row, the runner and the relay's shapes).
PAPER MONEY ONLY. What is measured (spread, delay since the trader looked) and what is modelled (impact by share of the displayed size) are kept apart, and a fill's record is part of its
hash-chained ledger row."""
from __future__ import annotations

import copy
import datetime as dt
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from quantdesk.config import Config
from quantdesk.core.types import Instrument
from quantdesk.markets import sessions as MK
from quantdesk.paper import runner as R
from quantdesk.paper import slippage as SL
from quantdesk.paper.account import Account
from quantdesk.paper.broker import PaperBroker
from quantdesk.paper.risk import KillSwitch, Order, Quote, RiskGate

ROOT = Path(__file__).resolve().parents[1]
IST = MK.IST
MON = dt.datetime(2026, 11, 9, 10, 0, tzinfo=IST)
NAME = "NIFTY12NOV2624500CE"
needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="Node is not installed")


@pytest.fixture()
def cfg():
    return Config.load(ROOT / "config" / "quantdesk.yaml")


def q(bid=99.0, ask=100.0, bq=5000, aq=5000, age=2):
    return Quote(bid, ask, MON - dt.timedelta(seconds=age), bq, aq)


def opt():
    return Instrument.option("NIFTY", dt.date(2026, 11, 12), 24500, "CE", 65)


def order(qty=65):
    return Order(opt(), "nse_fo", qty, "s1", "range break with rising volume, 30m")


def broker(cfg, tmp_path):
    acct = Account(500_000)
    return PaperBroker(cfg, acct, RiskGate(cfg, kill=KillSwitch(tmp_path / "K"))), acct


# ---- the model --------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("qty,shown,ticks", [(65, 5000, 0), (500, 5000, 0), (501, 5000, 1), (1250, 5000, 1), (1251, 5000, 2), (2500, 5000, 2), (2501, 5000, 3), (5000, 5000, 3),
                                              (65, None, 3), (65, 0, 3), (65, float("nan"), 3), (65, -5, 3), (0, 5000, 3)])
def test_impact_grows_with_the_share_of_the_displayed_size_and_an_unknown_size_is_the_worst(qty, shown, ticks):
    assert SL.impact_ticks(qty, shown) == ticks


def test_a_buy_pays_the_modelled_impact_on_top_of_the_offer_and_the_gate_judges_the_dearer_price(cfg, tmp_path):
    b, acct = broker(cfg, tmp_path)
    d, row = b.buy(order(), q(aq=100), {}, MON)                    # 65 of 100 shown: 3 ticks
    assert d.allowed and row["price"] == pytest.approx(100.15)
    assert row["slip"]["impact_ticks"] == 3 and row["slip"]["impact"] == pytest.approx(0.15) and row["slip"]["spread"] == pytest.approx(0.5)
    # the risk cap (2.5% of 500,000 incl. fees) is judged at what is really paid: somewhere there is an offer the gate passes at the touch but refuses once the impact is added
    found = False
    for k in range(0, 400):
        ask = 180.0 + 0.05 * k
        near = broker(cfg, tmp_path)[0].buy(order(), q(bid=ask - 1, ask=ask, aq=5000), {}, MON)[0].allowed
        thin = broker(cfg, tmp_path)[0].buy(order(), q(bid=ask - 1, ask=ask, aq=100), {}, MON)[0].allowed
        assert not (thin and not near)                                               # a thin book never makes a trade easier
        found = found or (near and not thin)
    assert found


def test_a_sale_gets_the_bid_less_the_impact_and_never_below_zero(cfg, tmp_path):
    b, acct = broker(cfg, tmp_path)
    b.buy(order(), q(), {}, MON)
    d, row = b.sell(opt().symbol, 65, q(bid=99.0, ask=100.0, bq=100), MON)
    assert d.allowed and row["price"] == pytest.approx(98.85) and row["slip"]["impact"] == pytest.approx(0.15) and row["slip"]["side"] == "sell"
    b3, acct3 = broker(cfg, tmp_path)
    b3.buy(order(), q(bid=0.05, ask=0.10), {}, MON)
    d3, row3 = b3.sell(opt().symbol, 65, q(bid=0.05, ask=0.10, bq=100), MON)
    assert d3.allowed and row3["price"] == 0.0 and row3["slip"]["impact"] == pytest.approx(0.05)      # only what was really given up is booked as impact


def test_the_split_adds_up_and_signs_mean_cost_for_both_sides():
    s = SL.split("buy", 65, 100.1, 99.0, 100.0, 0.1, seen_bid=98.5, seen_ask=99.5, delay_s=4.2)
    assert s["spread"] == pytest.approx(0.5) and s["impact"] == pytest.approx(0.1) and s["delay"] == pytest.approx(0.5)       # mid moved 99.0 -> 99.5
    assert s["total_vs_seen"] == pytest.approx(s["spread"] + s["impact"] + s["delay"]) == pytest.approx(1.1)                     # 100.1 against the seen mid 99.0
    assert s["shown"] == pytest.approx(0.6) and s["delay_s"] == 4.2 and s["total_inr"] == pytest.approx(1.1 * 65)
    t = SL.split("sell", 65, 98.9, 99.0, 100.0, 0.1, seen_bid=99.4, seen_ask=100.4, delay_s=2)
    assert t["spread"] == pytest.approx(0.5) and t["impact"] == pytest.approx(0.1) and t["delay"] == pytest.approx(0.4) and t["shown"] == pytest.approx(0.5)
    assert t["total_vs_seen"] == pytest.approx(t["spread"] + t["impact"] + t["delay"])
    gain = SL.split("buy", 65, 100.0, 99.0, 100.0, 0.0, seen_bid=100.0, seen_ask=101.0, delay_s=1)                              # the price fell while the trader clicked: a gain
    assert gain["delay"] < 0 and gain["shown"] < 0
    none_seen = SL.split("buy", 65, 100.0, 99.0, 100.0, 0.0)
    assert "delay" not in none_seen and none_seen["total_inr"] == pytest.approx(0.5 * 65)                                         # no sight of the decision: spread + impact only
    for bad in (dict(seen_bid=0, seen_ask=1), dict(seen_bid=2, seen_ask=1), dict(seen_bid=float("nan"), seen_ask=1)):
        assert "delay" not in SL.split("buy", 65, 100.0, 99.0, 100.0, 0.0, **bad)                                                  # an unusable reference is ignored


# ---- the sealed row ----------------------------------------------------------------------------------------------------------------
def test_the_slippage_record_is_inside_the_hash_chained_row_and_survives_save_and_replay(cfg, tmp_path):
    b, acct = broker(cfg, tmp_path)
    b.buy(order(), q(), {}, MON, ref={"bid": 98.5, "ask": 99.5, "at": MON.timestamp() * 1000 - 3000})
    row = acct.ledger[-1]
    assert row["slip"]["delay_s"] == pytest.approx(3.0) and acct.verify_ledger()
    again = Account.from_dict(json.loads(json.dumps(acct.to_dict())))                      # the replay check recomputes the same rows, slip included
    assert again.ledger == acct.ledger
    forged = copy.deepcopy(acct.to_dict())
    forged["ledger"][0]["slip"]["total_inr"] = 0.0
    with pytest.raises(ValueError):
        Account.from_dict(forged)                                                          # editing a slippage figure breaks the chain
    forged2 = copy.deepcopy(acct.to_dict())
    del forged2["ledger"][0]["slip"]
    with pytest.raises(ValueError):
        Account.from_dict(forged2)                                                         # and so does deleting it


def test_an_account_saved_before_slippage_existed_still_loads_and_continues(cfg, tmp_path):
    acct = Account(500_000)
    acct.apply_fill("buy", opt(), "nse_fo", 65, 100.0, 20.0, MON.isoformat(), "s1", "range break with rising volume")           # a row with no slip, as the first session wrote it
    again = Account.from_dict(json.loads(json.dumps(acct.to_dict())))
    assert "slip" not in again.ledger[0] and again.verify_ledger()
    PaperBroker(cfg, again, RiskGate(cfg, kill=KillSwitch(tmp_path / "K"))).sell(opt().symbol, 65, q(), MON)
    assert again.verify_ledger() and "slip" in again.ledger[-1]


@pytest.mark.parametrize("bad", [{"side": "buy", "qty": 65, "fill": float("nan")}, {"side": "buy", "qty": 65, "fill": 1.0, "x": 1}, "text", {"side": "hold", "qty": 1, "fill": 1}, {"qty": 1}])
def test_a_malformed_slippage_record_cannot_be_written_into_the_ledger(bad):
    a = Account(500_000)
    with pytest.raises(ValueError):
        a.apply_fill("buy", opt(), "nse_fo", 65, 100.0, 20.0, MON.isoformat(), "s", "t", bad)
    assert not a.ledger and a.cash == 500_000


# ---- the runner -------------------------------------------------------------------------------------------------------------------
def snap(now=MON, bq=5000, aq=5000):
    return {"now": int(now.timestamp() * 1000), "quotes": {NAME: dict(bid=99.0, ask=100.0, bid_qty=bq, ask_qty=aq, ltp=99.5, age_s=2.0)}}


def raw(**kw):
    o = dict(id="ord-slip-1", side="buy", symbol=NAME, lots=1, strategy="breakout", thesis="range break with rising volume on the 30 minute chart", queued_at=int(MON.timestamp() * 1000) - 3000)
    o.update(kw)
    return o


def rn(cfg, tmp_path):
    return R.Runner(cfg, Account(500_000), gate=RiskGate(cfg, kill=KillSwitch(tmp_path / "K")), kill_file=tmp_path / "K")


def test_an_order_that_carries_what_the_trader_saw_reports_the_delay_and_the_cost_against_it(cfg, tmp_path):
    r = rn(cfg, tmp_path)
    at = int(MON.timestamp() * 1000) - 6000
    out = r.step(snap(), [raw(ref={"bid": 98.0, "ask": 99.0, "at": at})], False, MON.astimezone(dt.timezone.utc))["results"][0]
    assert out["status"] == "filled", out
    s = out["fill"]["slip"]
    assert s["delay_s"] == pytest.approx(6.0) and s["delay"] == pytest.approx(1.0) and s["shown"] == pytest.approx(1.0) and s["spread"] == pytest.approx(0.5) and s["impact"] == 0 and s["total_vs_seen"] == pytest.approx(1.5)
    assert s["total_vs_seen"] == pytest.approx(s["spread"] + s["impact"] + s["delay"])
    summ = r.summary(snap(), MON)
    assert summ["slippage"]["fills"] == 1 and summ["slippage"]["fills_with_decision_price"] == 1 and summ["slips"][-1]["symbol"] == NAME and summ["ledger_ok"] is True
    assert summ["slippage"]["total_inr"] == pytest.approx(s["total_inr"])


def test_without_a_reference_the_delay_is_not_invented_and_a_forged_reference_changes_no_price(cfg, tmp_path):
    base = rn(cfg, tmp_path)
    a = base.step(snap(), [raw()], False, MON.astimezone(dt.timezone.utc))["results"][0]
    assert a["status"] == "filled" and "delay" not in a["fill"]["slip"]
    forged = rn(cfg, tmp_path)
    b = forged.step(snap(), [raw(ref={"bid": 1.0, "ask": 1.2, "at": 1})], False, MON.astimezone(dt.timezone.utc))["results"][0]
    assert b["status"] == "filled" and b["fill"]["price"] == a["fill"]["price"]            # the reference is only for the report
    for junk in ({"bid": "x", "ask": 1}, {"bid": 5, "ask": 4}, {"bid": -1, "ask": 1}, [1, 2], "q", {"bid": float("inf"), "ask": float("inf")}):
        o, why = R.clean_order(raw(ref=junk))
        assert why is None and o["ref"] is None, junk


def test_a_thin_book_costs_more_and_shows_up_as_impact(cfg, tmp_path):
    r = rn(cfg, tmp_path)
    out = r.step(snap(aq=100), [raw()], False, MON.astimezone(dt.timezone.utc))["results"][0]          # 65 of 100: 3 ticks
    assert out["status"] == "filled" and out["fill"]["price"] == pytest.approx(100.15) and out["fill"]["slip"]["impact_inr"] == pytest.approx(0.15 * 65)


# ---- the relay's shapes ------------------------------------------------------------------------------------------------------------
@needs_node
def test_the_relay_keeps_a_sane_reference_drops_a_bad_one_and_passes_only_numbers_in_a_results_slippage(tmp_path):
    shutil.copyfile(ROOT / "deploy/cloudflare/paper.js", tmp_path / "paper.js")
    (tmp_path / "package.json").write_text('{"type": "module"}', encoding="utf-8")
    (tmp_path / "t.mjs").write_text(r"""
import { cleanOrder, cleanResult } from "./paper.js";
const base = { id: "ord-abcdef", side: "buy", symbol: "NIFTY12NOV2624500CE", lots: 1, strategy: "s", thesis: "range break with rising volume 30m chart" };
const o = (ref) => cleanOrder({ ...base, ref });
const out = {
  good: o({ bid: 98, ask: 99, at: 1789000000000 }), noAt: o({ bid: 98, ask: 99 }), crossed: o({ bid: 99, ask: 98 }), neg: o({ bid: -1, ask: 1 }), str: o({ bid: "1", ask: 2 }), arr: o([1, 2]), none: o(undefined),
  res: cleanResult({ id: "ord-abcdef", status: "filled", reasons: [], fill: { qty: 65, price: 100, slip: { side: "buy", fill: 100, spread: 0.5, total_inr: 32.5, evil: 1, mid: "x", delay: null } } }),
};
console.log(JSON.stringify(out));
""", encoding="utf-8")
    r = subprocess.run(["node", "t.mjs"], cwd=tmp_path, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr[-1500:]
    o = json.loads(r.stdout.strip().splitlines()[-1])
    assert o["good"]["ref"] == {"bid": 98, "ask": 99, "at": 1789000000000} and o["noAt"]["ref"] == {"bid": 98, "ask": 99}
    for k in ("crossed", "neg", "str", "arr", "none"):
        assert o[k] is not None and "ref" not in o[k], k                                  # the order still goes; only the reference is dropped
    assert o["res"]["fill"]["slip"] == {"fill": 100, "spread": 0.5, "total_inr": 32.5, "side": "buy"}


# ---- review fixes: a forged reference cannot corrupt the record, and the owner's limit is judged on what is really paid -----------------------------------------
@pytest.mark.parametrize("bid,ask", [(1e150, 1e150), (1e306, 1e308), (1e-9, 2e-9), (0.5, 600.0), (5.0, 6.0)])
def test_a_reference_that_is_not_a_price_of_this_contract_is_ignored_so_the_record_stays_sane(cfg, tmp_path, bid, ask):
    r = rn(cfg, tmp_path)
    out = r.step(snap(), [raw(ref={"bid": bid, "ask": ask, "at": int(MON.timestamp() * 1000) - 5000})], False, MON.astimezone(dt.timezone.utc))["results"][0]
    assert out["status"] == "filled", out
    s = out["fill"]["slip"]
    assert "delay" not in s and "shown" not in s and s["total_inr"] == pytest.approx((s["spread"] + s["impact"]) * 65)            # as if the order had carried nothing
    summ = r.summary(snap(), MON)
    assert summ["slippage"]["fills"] == 1 and summ["slippage"]["total_inr"] == pytest.approx(s["total_inr"])
    json.dumps(summ, allow_nan=False)                                                                                           # the summary can always be sent to the relay


def test_no_figure_in_a_slippage_record_can_be_enormous_and_sums_never_overflow():
    big = {"side": "buy", "qty": 65, "fill": 100.0, "delay_inr": 1e12}
    assert SL.clean(big) is None and SL.clean({"side": "buy", "qty": 65, "fill": 100.0, "delay_inr": 1e8}) is not None
    rows = [{"slip": {"side": "buy", "qty": 1, "fill": 1.0, "total_inr": 1.7e308}} for _ in range(3)]
    t = SL.totals(rows)
    assert all(isinstance(v, (int, float)) and abs(v) < float("inf") for v in t.values() if v is not None)
    json.dumps(t, allow_nan=False)


def test_a_slippage_record_must_match_the_fill_it_is_sealed_into():
    a = Account(500_000)
    ok = SL.split("buy", 65, 100.0, 99.0, 100.0, 0.0)
    for bad in ({**ok, "side": "sell"}, {**ok, "qty": 66}, {**ok, "fill": 101.0}):
        with pytest.raises(ValueError):
            a.apply_fill("buy", opt(), "nse_fo", 65, 100.0, 20.0, MON.isoformat(), "s", "t", bad)
    assert not a.ledger
    a.apply_fill("buy", opt(), "nse_fo", 65, 100.0, 20.0, MON.isoformat(), "s", "t", ok)
    assert len(a.ledger) == 1


def test_a_limit_is_judged_on_the_price_that_would_really_be_paid_impact_included(cfg, tmp_path):
    b, acct = broker(cfg, tmp_path)
    d, row = b.buy(order(), q(bid=1.9, ask=2.0, aq=100), {}, MON, limit=2.0)               # 65 of 100 shown: the fill would be 2.15
    assert not d.allowed and row is None and "2.15" in d.reasons[0] and not acct.ledger
    d2, row2 = b.buy(order(), q(bid=1.9, ask=2.0, aq=100), {}, MON, limit=2.15)
    assert d2.allowed and row2["price"] == pytest.approx(2.15)
    d3, row3 = b.sell(opt().symbol, 65, q(bid=1.9, ask=2.0, bq=100), MON, limit=1.9)       # would sell at 1.75
    assert not d3.allowed and row3 is None and opt().symbol in acct.positions
    assert b.sell(opt().symbol, 65, q(bid=1.9, ask=2.0, bq=100), MON, limit=1.75)[0].allowed


def test_the_runners_limit_checks_the_touch_first_and_then_the_impact(cfg, tmp_path):
    r = rn(cfg, tmp_path)
    out = r.step(snap(aq=100), [raw(limit=100.0)], False, MON.astimezone(dt.timezone.utc))["results"][0]
    assert out["status"] == "refused" and "limit" in out["reasons"][0] and not r.account.ledger                                  # 100.15 against a limit of 100.0
    r2 = rn(cfg, tmp_path)
    ok = r2.step(snap(aq=100), [raw(id="ord-slip-2", limit=100.15)], False, MON.astimezone(dt.timezone.utc))["results"][0]
    assert ok["status"] == "filled"


def test_a_nonsense_time_on_the_reference_costs_only_the_delay_figure_never_the_record(cfg, tmp_path):
    for at in (1, 10**12, int(MON.timestamp() * 1000) + 50_000):
        r = rn(cfg, tmp_path)
        out = r.step(snap(), [raw(id=f"ord-at-{abs(at) % 1000}", ref={"bid": 98.0, "ask": 99.0, "at": at})], False, MON.astimezone(dt.timezone.utc))["results"][0]
        assert out["status"] == "filled" and "slip" in out["fill"], (at, out)
        assert "delay_s" not in out["fill"]["slip"] and out["fill"]["slip"]["total_inr"] > 0
        assert r.summary(snap(), MON)["slippage"]["fills"] == 1


def test_a_reference_must_sit_within_a_factor_of_two_of_the_mid_and_an_odd_price_still_fills(cfg, tmp_path):
    r = rn(cfg, tmp_path)
    far = r.step(snap(), [raw(ref={"bid": 490.0, "ask": 495.0})], False, MON.astimezone(dt.timezone.utc))["results"][0]
    assert far["status"] == "filled" and "delay" not in far["fill"]["slip"]
    s = {"now": int(MON.timestamp() * 1000), "quotes": {NAME: dict(bid=99.12345, ask=100.12345, bid_qty=5000, ask_qty=5000, ltp=99.5, age_s=2.0)}}
    odd = rn(cfg, tmp_path).step(s, [raw(id="ord-odd-1")], False, MON.astimezone(dt.timezone.utc))["results"][0]
    assert odd["status"] == "filled", odd
