"""Phase F forensic probes (read-only: synthetic data, fakes, temp dirs and a copy of the journal).

    QD_JOURNAL=/tmp/qd_journal/intraday python -m pytest -o addopts="" -q -p no:cacheprovider audit/probes

Each passing probe CONFIRMS the finding it names (audit/QUANTDESK_FINDINGS_REGISTER.md). The data-heavy measurements
(expiries vs the exchanges' files, pricing vs references, put/call IV parity, depth, the candle-label test) are the
phase_f_*.py scripts next to this file; their outputs are in audit/data/phase_f_*.
"""
import datetime as dt
import inspect
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

REPO = Path(os.environ.get("QD_REPO", str(Path(__file__).resolve().parents[2])))
JOURNAL = Path(os.environ.get("QD_JOURNAL", "/nonexistent"))
sys.path.insert(0, str(REPO))
IST = "Asia/Kolkata"


def _cfg():
    from quantdesk.config import Config, DEFAULT_CONFIG
    return Config.load(DEFAULT_CONFIG)


# ---- F-01: the model-chain fallback is tradeable, and its fabricated OI votes ------------------------------------------
def test_model_chain_fallback_yields_oi_walls_and_max_pain_from_fabricated_oi():
    from quantdesk.core.calendar import TradingCalendar
    from quantdesk.intraday.chains import ModelOptionChain, chain_analytics
    cfg = _cfg()
    mc = ModelOptionChain(cfg, TradingCalendar(cfg.holidays()), lambda u, ts: (22500.0, 0.14))
    now = pd.Timestamp("2026-10-08 11:00", tz=IST)
    ch = mc.chain("NIFTY", dt.date(2026, 10, 13), ts=now)
    an = chain_analytics(ch)
    assert an["source"] == "model"
    assert an["call_wall"] > 22500 > an["put_wall"] and an["max_pain"] > 0      # walls and max pain from modelled OI
    analyst = (REPO / "quantdesk/intraday/analyst.py").read_text()
    assert 'c.get("source") != "model"' in analyst                             # PCR is guarded …
    i = analyst.index('add("oi_walls"')
    assert "model" not in analyst[analyst.index('if c.get("call_wall")'):i]   # … the OI walls are not


def test_model_chain_is_exempt_from_the_stale_chain_gate_and_used_on_failure():
    from quantdesk.intraday import engine as E
    src = inspect.getsource(E)
    assert 'self.chain_df[u].attrs.get("source") != "model" and age > pd.Timedelta(minutes=self.stale_min)' in src
    assert "ch = self.model_chain.chain(u, self.expiry[u], spot=self.spot(u), ts=now)" in src
    assert 'f"live {self.chains.name} book" if len(live) == len(insts) else "option chain"' in src  # fill label never says "model"


# ---- F-03: paper fills ignore depth --------------------------------------------------------------------------------
def test_paper_fill_takes_any_size_at_top_of_book_plus_one_tick():
    from quantdesk.core.types import Instrument, Order
    from quantdesk.intraday.sim import IntradayBroker
    b = IntradayBroker(_cfg(), starting_cash=5e6, adverse_ticks=1)
    inst = Instrument.option("NIFTY", dt.date(2026, 10, 13), 22500, "CE", 65)
    f1 = b.execute(Order(inst, 65, "t1", "open"), 100.0, pd.Timestamp("2026-10-08 11:00", tz=IST))
    f10 = b.execute(Order(inst, 650, "t2", "open"), 100.0, pd.Timestamp("2026-10-08 11:00", tz=IST))
    assert f1.price == pytest.approx(100.05) and f10.price == pytest.approx(100.05)   # 10 lots: same price as 1
    for mod in ("engine", "playbook", "sim", "risk"):
        assert "bidq" not in (REPO / f"quantdesk/intraday/{mod}.py").read_text()      # depth is recorded, never read


# ---- F-04: exercise STT ------------------------------------------------------------------------------------------
def test_exercise_stt_is_the_pre_april_2026_rate_and_paper_settlement_ignores_it():
    from quantdesk.execution.broker import PaperBroker
    from quantdesk.research.warehouse_research import STT_EXERCISE
    assert STT_EXERCISE == pytest.approx(0.00125)                               # 0.15% since 1 Apr 2026 (secondary sources)
    cfg = _cfg()
    assert cfg.get("costs.segments.options")["stt_sell"] == pytest.approx(0.0015)   # while the sale rate is the new one
    assert "STT on ITM exercise is ignored" in inspect.getsource(PaperBroker.settle_expiry)


# ---- F-05: the live (Kite) adapter loses a partial fill -----------------------------------------------------------
def test_kite_adapter_drops_a_partially_filled_order():
    from quantdesk.core.types import Instrument, Order
    from quantdesk.execution.costs import CostModel
    from quantdesk.execution.kite import KiteBroker

    class FakeKite:
        TRANSACTION_TYPE_BUY, TRANSACTION_TYPE_SELL, PRODUCT_CNC, PRODUCT_NRML = "BUY", "SELL", "CNC", "NRML"
        VARIETY_REGULAR, ORDER_TYPE_LIMIT = "regular", "LIMIT"
        cancelled = []

        def place_order(self, **kw):
            self.kw = kw
            return "OID1"

        polls = 0

        def order_history(self, oid):                    # 130 of 650 filled, then nothing more
            FakeKite.polls += 1
            return [{"status": "OPEN", "filled_quantity": 130, "average_price": 100.1}]

        def cancel_order(self, variety, order_id):
            self.cancelled.append(order_id)

    kb = object.__new__(KiteBroker)                       # skip the live-mode guards: nothing leaves this process
    kb.kite, kb.costs = FakeKite(), CostModel(_cfg())
    kb.kill_file, kb.protection, kb.max_order_value, kb.fill_timeout = Path("/nonexistent/KILL"), 0.01, 1e9, 1.2
    kb.tradingsymbol = lambda inst: ("NFO", "NIFTY26O1322500CE")
    o = Order(Instrument.option("NIFTY", dt.date(2026, 10, 13), 22500, "CE", 65), 650, "t", "open")
    assert kb.execute(o, 100.0, None) is None and o.status == "CANCELLED"     # the 130 filled are not reported
    assert FakeKite.polls >= 1 and kb.kite.cancelled == ["OID1"]               # it saw the partial fill, then cancelled
    src = inspect.getsource(KiteBroker.execute)
    assert "filled_quantity" not in src and "pd.Timestamp.now()" in src         # and a filled order is stamped naive local time


def test_kite_futures_symbology_ignores_the_roll():
    from quantdesk.execution.kite import KiteBroker
    src = inspect.getsource(KiteBroker.tradingsymbol)
    assert 'sort_values("expiry").head(1)' in src                               # nearest future, even on expiry day
    from quantdesk.intraday.kotak import KotakFutures
    assert "roll_days" in inspect.getsource(KotakFutures.active)                # the data side rolls 3 days early


# ---- F-06: the holiday calendar ends in 2026 ---------------------------------------------------------------------
def test_holidays_end_in_2026_so_republic_day_2027_is_an_expiry():
    from quantdesk.core.calendar import TradingCalendar
    cfg = _cfg()
    cal = TradingCalendar(cfg.holidays())
    assert max(cfg.holidays()).year == 2026
    assert cal.is_trading_day(dt.date(2027, 1, 26))                            # Republic Day, a Tuesday
    assert dt.date(2027, 1, 26) in cal.expiries(dt.date(2027, 1, 20), 10, 1, True)


# ---- F-02: the frozen index (E-01) next to live futures -----------------------------------------------------------
def test_index_freezes_while_the_future_keeps_trading():
    d = JOURNAL / "data" / "2026-10-06"
    if not (d / "NIFTY-FUT_1m.csv").exists():
        pytest.skip("journal snapshot not available")
    i = pd.read_csv(d / "NIFTY_1m.csv")
    f = pd.read_csv(d / "NIFTY-FUT_1m.csv")
    w = lambda x: x[x.ts.str[11:16].between("15:15", "15:28")]
    assert w(i).close.nunique() == 1                                            # index: one value for 14 minutes
    assert w(f).close.nunique() >= 10                                           # its future: still trading
    basis = w(f).close.to_numpy() - w(i).close.to_numpy()
    assert basis.max() - basis.min() > 20                                       # a ~24-point swing in "basis" from staleness alone


def test_a_tenth_of_graded_factor_reads_end_in_the_frozen_minutes():
    import sqlite3
    p = JOURNAL / "journal.db"
    if not p.exists():
        pytest.skip("journal snapshot not available")
    with sqlite3.connect(f"file:{p}?mode=ro", uri=True) as c:
        ts = pd.to_datetime(pd.read_sql("SELECT ts FROM thoughts", c).ts, format="mixed").dt.tz_convert(IST)
    late = (ts.dt.strftime("%H:%M") > "14:45").mean()                          # their 30-minute window ends after 15:15
    assert 0.08 < late < 0.15


# ---- display vs decision: GEX and participant OI never vote ------------------------------------------------------
def test_gex_and_participant_oi_are_narrative_only():
    analyst = (REPO / "quantdesk/intraday/analyst.py").read_text()
    assert 'add("gex' not in analyst and "parts.append(f\"Options context: dealer gamma" in analyst
    brain = (REPO / "quantdesk/intraday/brain.py").read_text()
    assert "a regime input, not an intraday vote" in brain
