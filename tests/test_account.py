"""A small account: the configured capital, sizing that respects what one lot really costs,
and an account that only resets itself while it has no history."""
import datetime as dt

import pandas as pd
import pytest

from quantdesk.intraday.account import ensure_account, reset_account
from quantdesk.intraday.playbook import PlanLeg, TradePlan
from quantdesk.intraday.risk import IntradayRisk
from quantdesk.journal.journal import Journal


def plan(symbol, lot, legs, conviction=0.8):
    return TradePlan("orb", symbol, 1, "bull_call_spread", dt.date(2026, 10, 6), legs, lot, "t", "th", None, None,
                     0.30, 0.60, 45, "nse", conviction)


def test_small_account_sizing(cfg):
    assert cfg.get("intraday.capital") == 20000
    r = IntradayRisk(cfg)
    # NIFTY 22850/23000 call spread for ~61 → ₹3,955 a lot, ~₹1.2k to the stop: one lot at good conviction
    nifty = plan("NIFTY", 65, [PlanLeg(22850, "CE", 1, 120.0, 119, 13, 0.45), PlanLeg(23000, "CE", -1, 59.2, 60, 13, 0.30)])
    lots, notes = r.size(nifty, 20000, 20000)
    assert lots == 1, notes
    # low conviction: the 8% budget × 0.6 scale can't cover a lot's risk → no trade
    assert r.size(plan("NIFTY", 65, nifty.legs, conviction=0.0), 20000, 20000)[0] == 0
    # BANKNIFTY monthly spread ~₹9.4k a lot and ~₹2.8k to the stop: priced out of a ₹20k account
    bnf = plan("BANKNIFTY", 30, [PlanLeg(51000, "CE", 1, 700.0, 700, 15, 0.45), PlanLeg(51800, "CE", -1, 387.0, 387, 15, 0.30)])
    assert r.size(bnf, 20000, 20000)[0] == 0
    # never pay more than the cash on hand
    lots, notes = r.size(nifty, 20000, 3000)
    assert lots == 0 and "binding: cash" in notes[-1]
    # credit spreads need SPAN-sized margin, not just their max loss
    credit = TradePlan("range_sell", "NIFTY", 0, "iron_condor", dt.date(2026, 10, 6),
                       [PlanLeg(23100, "CE", -1, 40.0, 40, 13, 0.2), PlanLeg(23200, "CE", 1, 20.0, 20, 13, 0.1)],
                       65, "t", "th", None, None, 0.8, 0.3, 120, "nse", 0.8)
    lots, notes = r.size(credit, 20000, 20000)
    assert lots == 0 and "binding: margin" in notes[-1]


def test_account_resets_only_without_history(cfg, tmp_path):
    j = Journal(tmp_path / "journal.db")
    broker = tmp_path / "broker.json"
    broker.write_text('{"cash": 500000}')
    assert ensure_account(cfg, j, broker, say=None) == 20000 and not broker.exists()   # no trades: take the config
    assert j.get_state("intraday_account")["capital"] == 20000
    # after trading, a config change doesn't silently rewrite history
    j.db.execute("INSERT INTO trades (id, status, opened_at) VALUES ('T1', 'closed', '2026-09-29 10:00')")
    j.commit()
    cfg2 = cfg.__class__(dict(cfg.data, intraday=dict(cfg.data["intraday"], capital=100000)))
    msgs = []
    assert ensure_account(cfg2, j, broker, say=msgs.append) == 20000 and "reset-account" in msgs[0]
    # an explicit reset archives it
    base = tmp_path
    moved = reset_account(base)
    assert moved and (moved / "journal.db").exists() and not (base / "journal.db").exists()
