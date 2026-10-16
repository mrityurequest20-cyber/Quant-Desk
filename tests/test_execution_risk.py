import datetime as dt

import pandas as pd
import pytest

from quantdesk.core.types import Instrument, Order
from quantdesk.execution.broker import PaperBroker
from quantdesk.execution.costs import CostModel
from quantdesk.risk import metrics as M
from quantdesk.risk.manager import RiskManager


def test_option_sell_cost_stack(cfg):
    cm = CostModel(cfg)
    inst = Instrument.option("NIFTY", dt.date(2026, 10, 27), 25000, "CE", 65)
    total, br = cm.fees(inst, -65, 100.0)
    turnover = 6500.0
    assert br["brokerage"] == 20.0
    assert br["stt"] == pytest.approx(turnover * 0.0015)           # 0.15% on sell-side premium (FY27)
    assert br["exchange"] == pytest.approx(turnover * 0.0003503)
    assert br["stamp"] == 0.0                                        # stamp duty only on buys
    assert br["gst"] == pytest.approx(0.18 * (20 + turnover * 0.0003503 + turnover * 1e-6))
    assert total == pytest.approx(sum(br.values()))
    buy_total, buy_br = cm.fees(inst, 65, 100.0)
    assert buy_br["stt"] == 0.0 and buy_br["stamp"] == pytest.approx(turnover * 0.00003)


def test_equity_delivery_stt_both_sides(cfg):
    cm = CostModel(cfg)
    inst = Instrument.equity("RELIANCE")
    _, b = cm.fees(inst, 100, 1000.0)
    _, s = cm.fees(inst, -100, 1000.0)
    assert b["stt"] == s["stt"] == pytest.approx(100.0)              # 0.1% of ₹1L each way
    assert b["brokerage"] == 0.0


def test_slippage_is_adverse(cfg):
    cm = CostModel(cfg)
    eq = Instrument.equity("INFY")
    assert cm.fill_price(eq, 10, 1000.0) > 1000.0 > cm.fill_price(eq, -10, 1000.0)
    opt = Instrument.option("NIFTY", dt.date(2026, 10, 27), 25000, "PE", 65)
    assert cm.fill_price(opt, 65, 3.0) == pytest.approx(3.10)         # min half-spread on cheap options


def test_paper_broker_position_accounting(cfg):
    br = PaperBroker(cfg, starting_cash=1_000_000)
    br.costs.eq_bps = 0.0
    inst = Instrument.equity("TCS")
    ts = pd.Timestamp("2026-01-05")
    br.execute(Order(inst, 10, "t", "open"), 100.0, ts)
    br.execute(Order(inst, 10, "t", "open"), 110.0, ts)
    assert br.positions()["TCS"]["qty"] == 20 and br.positions()["TCS"]["avg_price"] == pytest.approx(105.0)
    br.execute(Order(inst, -25, "t", "close"), 120.0, ts)            # flip to short 5
    p = br.positions()["TCS"]
    assert p["qty"] == -5 and p["avg_price"] == pytest.approx(120.0)
    br.execute(Order(inst, 5, "t", "close"), 120.0, ts)
    assert "TCS" not in br.positions()
    gross = -10 * 100 - 10 * 110 + 25 * 120 - 5 * 120
    assert br.cash() == pytest.approx(1_000_000 + gross - br.fees_paid)


def test_paper_broker_state_roundtrip(cfg, tmp_path):
    path = tmp_path / "b.json"
    br = PaperBroker(cfg, starting_cash=500_000, state_path=path)
    br.execute(Order(Instrument.equity("ITC"), 50, "t", "open"), 400.0, pd.Timestamp("2026-01-05"))
    again = PaperBroker(cfg, state_path=path)
    assert again.cash() == pytest.approx(br.cash()) and again.positions()["ITC"]["qty"] == 50


def test_drawdown_derisk_and_kill_switch(cfg):
    rm = RiskManager(cfg)
    rm.new_bar(pd.Timestamp("2026-01-05"), 1_000_000)
    assert rm.dd_scale(1_000_000) == 1.0
    mid = 1_000_000 * (1 - (rm.dd_start + rm.dd_halt) / 2)
    assert rm.dd_scale(mid) == pytest.approx(0.5)
    assert rm.end_of_bar(1_000_000 * (1 - rm.dd_halt - 0.001)) == ["HALT", "DAILY_LIMIT"]
    ok, why = rm.can_enter()
    assert not ok and "kill switch" in why
    rm.reset_halt(850_000)
    assert not rm.halted


def test_daily_loss_limit_blocks_entries_until_next_day(cfg):
    rm = RiskManager(cfg)
    rm.new_bar(pd.Timestamp("2026-01-05"), 1_000_000)
    assert "DAILY_LIMIT" in rm.end_of_bar(975_000)
    assert not rm.can_enter()[0]
    rm.new_bar(pd.Timestamp("2026-01-06"), 975_000)
    assert rm.can_enter()[0]


def test_probabilistic_and_deflated_sharpe():
    import numpy as np
    rng = np.random.default_rng(0)
    good = pd.Series(rng.normal(0.001, 0.01, 1500))
    noise = pd.Series(rng.normal(0.0, 0.01, 1500))
    noise -= noise.mean()                                            # exactly zero sample Sharpe
    assert M.probabilistic_sharpe(good) > 0.95
    assert M.probabilistic_sharpe(noise) == pytest.approx(0.5, abs=1e-6)
    # the more variants tried, the higher the bar a Sharpe must clear
    assert M.deflated_sharpe(good, 100, 0.02) < M.deflated_sharpe(good, 2, 0.02) <= M.probabilistic_sharpe(good)


# ---- F-05: exercise STT on a long ITM leg held to expiry (0.15% of intrinsic from 2026-04-01, from config) -----------
def _settle(cfg, qty, strike, right="CE", spot=25_300.0, on="2026-10-27"):
    inst = Instrument.option("NIFTY", dt.date.fromisoformat(on), strike, right, 65)
    br = PaperBroker(cfg, starting_cash=1_000_000)
    br._pos[inst.symbol] = {"instrument": inst.to_dict(), "qty": qty, "avg_price": 100.0}
    intr = max(spot - strike, 0.0) if right == "CE" else max(strike - spot, 0.0)
    return br, br.settle_expiry(inst, intr, pd.Timestamp(on, tz="Asia/Kolkata")), intr


def test_a_long_itm_leg_held_to_expiry_pays_015pct_of_intrinsic_times_quantity(cfg):
    br, fill, intr = _settle(cfg, 65, 25_000)
    stt = 0.0015 * intr * 65
    assert intr == 300.0 and fill.fees == pytest.approx(stt) and fill.fee_breakdown == {"stt": pytest.approx(stt)}
    assert br.fees_paid == pytest.approx(stt) and br.fee_breakdown["stt"] == pytest.approx(stt)
    assert br.cash() == pytest.approx(1_000_000 + 65 * intr - stt) and not br.positions()


def test_short_and_otm_legs_pay_no_exercise_stt(cfg):
    for qty, strike, right in ((-65, 25_000, "CE"), (65, 25_500, "CE"), (65, 25_000, "PE"), (-65, 25_500, "PE")):
        br, fill, intr = _settle(cfg, qty, strike, right)
        assert fill.fees == 0.0 and br.fees_paid == 0.0 and br.fee_breakdown == {}
        assert br.cash() == pytest.approx(1_000_000 + qty * intr)        # the intrinsic cash flow only


def test_the_exercise_stt_rate_is_dated_and_comes_from_config(cfg):
    cm = CostModel(cfg)
    assert cm.exercise_stt(dt.date(2026, 3, 31)) == pytest.approx(0.00125) and cm.exercise_stt(dt.date(2026, 4, 1)) == pytest.approx(0.0015)
    assert cm.exercise_stt(pd.Timestamp("2026-10-27", tz="Asia/Kolkata")) == pytest.approx(0.0015)
    other = cfg.with_overrides({"costs": {"exercise_stt": {dt.date(2026, 4, 1): 0.002}}})
    br, fill, intr = _settle(other, 65, 25_000)
    assert fill.fees == pytest.approx(0.002 * intr * 65)                  # the broker follows the config, not a constant
    br, fill, intr = _settle(cfg, 65, 25_000, on="2026-03-30")            # settled before the revision: the earlier rate
    assert fill.fees == pytest.approx(0.00125 * intr * 65)
