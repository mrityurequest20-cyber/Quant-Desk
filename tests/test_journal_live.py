import datetime as dt

import pandas as pd
import pytest

from quantdesk.cli import build_parser
from quantdesk.core.types import Instrument, Trade, TradeLeg
from quantdesk.execution.broker import PaperBroker
from quantdesk.journal.review import review_trade


def _trade(pnl, mfe, mae, reason, risk=10_000.0, bars=10):
    t = Trade(id="x", strategy="trend_rider", family="trend", symbol="INFY", direction=1, kind="linear",
              legs=[TradeLeg(Instrument.equity("INFY"), 100, 1500.0, 1500.0 + pnl / 100)], units=100,
              opened_at=pd.Timestamp("2026-01-05"), entry_underlying=1500.0, initial_risk=risk, stop=1400.0,
              context={"regime": "trending_up"})
    t.pnl, t.mfe, t.mae, t.exit_reason, t.bars_held = pnl, mfe, mae, reason, bars
    return t


def test_review_rewards_process_over_outcome():
    planned_loss = review_trade(_trade(-10_000, 1_000, -10_000, "stop"))
    lucky_forced = review_trade(_trade(15_000, 16_000, -9_500, "manual"))
    assert planned_loss["grade"] in ("B", "C")
    assert planned_loss["process_score"] > lucky_forced["process_score"]
    assert any("forced" in l for l in lucky_forced["lessons"])


def test_review_lessons():
    rv = review_trade(_trade(-2_000, 15_000, -4_000, "trend_reversal"), regime_at_exit="range")
    text = " ".join(rv["lessons"])
    assert "Round-tripped" in text and "Regime changed" in text
    quick = review_trade(_trade(-10_000, 0, -10_000, "stop", bars=1))
    assert any("within 2 bars" in l for l in quick["lessons"])


