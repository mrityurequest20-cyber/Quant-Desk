"""Paper-only exploration (intraday.exploration): a directional plan trades without an approved plan model only when
enabled, in paper, inside its caps and through every other gate; it is labelled and never paper-gate evidence."""
from __future__ import annotations

import datetime as dt
import json

import pandas as pd
from test_plan_research import _engine, _plan, _policy, make_cfg, ts

from quantdesk.autolearn.live import LiveLearner
from quantdesk.autolearn.registry import Registry
from quantdesk.intraday.analyst import MarketView
from quantdesk.research.protocol import evaluate_paper_candidate, real_quote_trades, without_exploration

DAY, NOW, EXP = dt.date(2026, 9, 29), ts("2026-09-29 11:00"), dt.date(2026, 10, 6)
ON = {"exploration": {"enabled": True, "max_per_day": 2, "lots": 1, "max_total": 40, "until": None}}


def build(tmp_path, intraday=None, mode=None):
    cfg = make_cfg(tmp_path, intraday=intraday)
    if mode:
        cfg = cfg.with_overrides({"account": {"mode": mode}})
    eng = _engine(cfg, DAY)
    eng.learner = LiveLearner(cfg, root=tmp_path / "al", source="replay")
    eng.learner.start(DAY)
    view = MarketView("NIFTY", NOW, 25000.0, "bull", 0.8, 0.9, "trend", "fair", None, None, [], [], {}, "a strong read")
    eng._blocked = lambda u, v, n: None                              # the other gates have their own tests; stubbed unless named
    eng._by_record = lambda u, plans, view, now: (plans, None)
    eng.playbook.scan = lambda *a, **k: [_plan(EXP)]
    return eng, view


def ev_pass(eng):
    """The EV layer's pass: the plan with the risk engine's size (the real floor is exercised in test_quant)."""
    def pick(u, plans, view, eq, now, chain=None):
        lots, notes = eng.risk.size(plans[0], eq, eng.broker.cash())
        return plans[0], lots, notes
    eng._select_by_ev = pick


def test_disabled_by_default_is_main(tmp_path):
    from quantdesk.config import DEFAULT_CONFIG, Config
    assert Config.load(DEFAULT_CONFIG).get("intraday.exploration.enabled") is False
    eng, view = build(tmp_path)
    ev_pass(eng)
    assert not eng.explore["enabled"]
    for _ in range(3):
        assert "no approved plan model" in eng._maybe_enter("NIFTY", view, {}, NOW)
    assert not eng.open_trades and eng.journal.trades().empty
    assert "[" not in eng._model_gates("NIFTY", [_plan(EXP)], NOW)[1]          # the reason is main's, word for word


def test_enabled_paper_no_champion_trades_one_lot_labelled_and_the_daily_cap_holds(tmp_path):
    eng, view = build(tmp_path, ON)
    ev_pass(eng)
    eng.risk.max_trades = 10
    msg = eng._maybe_enter("NIFTY", view, {}, NOW)
    assert msg.startswith("ENTER") and "EXPLORATION" in msg and len(eng.open_trades) == 1
    t = eng.open_trades[0]
    assert t.units == 1 and t.meta["mode"] == "exploration" and t.rationale.startswith("EXPLORATION (unvalidated prior): ")
    d = eng.journal.decisions()
    assert (d["action"] == "exploration").sum() == 1 and "EXPLORATION (unvalidated prior)" in d["detail"].iloc[-1]
    assert eng._maybe_enter("NIFTY", view, {}, NOW + pd.Timedelta(minutes=5)).startswith("ENTER")
    assert len(eng.open_trades) == 2
    msg = eng._maybe_enter("NIFTY", view, {}, NOW + pd.Timedelta(minutes=10))     # the third: max_per_day is 2
    assert "no approved plan model" in msg and "took its 2 for today" in msg and len(eng.open_trades) == 2
    assert eng._explore_off(NOW + pd.Timedelta(days=1)) is None                   # the next session's cap is fresh


def test_exploration_goes_through_every_other_gate(tmp_path):
    eng, view = build(tmp_path, ON)
    # the EV floor (and sizing): a plan the EV layer refuses stays out
    eng._select_by_ev = lambda *a, **k: "setup orb found but not worth it after costs"
    assert "not worth it" in eng._maybe_enter("NIFTY", view, {}, NOW) and not eng.open_trades
    # the live-book check at _open: a book that moved away skips it
    ev_pass(eng)
    eng._live = lambda insts, now: {i.symbol: (1e4, 1e4) for i in insts}
    assert "moved away" in eng._maybe_enter("NIFTY", view, {}, NOW) and not eng.open_trades
    # sizing: lots the risk and cash checks don't allow are not forced in
    eng._live = lambda insts, now: {}
    eng.explore["lots"] = 3
    eng._select_by_ev = lambda u, plans, v, eq, now, chain=None: (plans[0], 1, [])
    assert "needs 3 lot(s)" in eng._maybe_enter("NIFTY", view, {}, NOW) and not eng.open_trades
    # the setup record's veto and the halts come first (the real _blocked, not the stub)
    eng.explore["lots"] = 1
    eng._by_record = lambda u, plans, v, now: ([], "its record says no")
    assert "its record says no" in eng._maybe_enter("NIFTY", view, {}, NOW)
    eng.killed = True
    del eng._blocked
    assert "halted: kill switch" in eng._maybe_enter("NIFTY", view, {}, NOW) and not eng.open_trades


def test_a_champion_that_says_no_still_blocks_it(tmp_path):
    from quantdesk.autolearn import plans as P
    from quantdesk.autolearn.features import FEATURES
    from quantdesk.core.calendar import TradingCalendar
    eng, view = build(tmp_path, ON)
    ev_pass(eng)
    # a direction champion that calls down: the long plan is refused although exploration let it through plan_gate
    eng.learner.champion_id, eng.learner.models = "m", {"m": object()}                 # a verified direction champion steers
    eng.learner.last["NIFTY"] = {"signal": -1, "model_id": "m", "p": 0.4, "decision_id": "d"}
    assert "champion model calls down" in eng._maybe_enter("NIFTY", view, {}, NOW) and not eng.open_trades
    eng.learner.last["NIFTY"] = {"signal": 0, "model_id": "m", "p": 0.5, "reason": "abstains"}
    assert "abstains" in eng._maybe_enter("NIFTY", view, {}, NOW) and not eng.open_trades
    # an approved plan model that expects a loss: its reason stands, exploration never runs (it stops once one exists)
    eng2, view2 = build(tmp_path / "b", ON)
    bucket = P.dte_bucket(TradingCalendar(eng2.cfg.holidays()).trading_days_between(DAY, EXP))
    reg = Registry(tmp_path / "b" / "al" / "plan")
    card = {"code_fingerprint": "c", "feature_version": "f", "label_version": "l", "data_fingerprint": "d", "training_window": {},
            "validation": {"passed": True}, "family": "plan", "evidence": "real_point_in_time"}
    mid, _ = reg.register(_policy(bucket), card)
    reg.promote(mid, "test", {"forward": True})
    eng2.learner = LiveLearner(eng2.cfg, root=tmp_path / "b" / "al", source="replay")
    eng2.learner.start(DAY)
    assert eng2.learner.plan
    eng2.learner.feats["NIFTY"] = (NOW, {k: 0.0 for k in FEATURES})
    eng2.playbook.scan = lambda *a, **k: [_plan(EXP, -1)]
    assert "plan model expects" in eng2._maybe_enter("NIFTY", view2, {}, NOW) and not eng2.open_trades
    assert "approved plan model is steering" in eng2._explore_off(NOW)


def test_live_mode_is_critical_once_and_never_enters(tmp_path):
    eng, view = build(tmp_path, ON, mode="live")
    ev_pass(eng)
    for i in range(3):
        assert "no approved plan model" in eng._maybe_enter("NIFTY", view, {}, NOW + pd.Timedelta(minutes=i))
    assert not eng.open_trades and eng.journal.trades().empty
    crit = eng.journal.events(level="CRITICAL")
    assert len(crit) == 1 and crit["category"].iloc[0] == "exploration"
    # a non-paper broker is refused the same way, even in a paper config
    eng2, _ = build(tmp_path / "c", ON)
    eng2.broker = object()
    assert "paper only" in eng2._explore_off(NOW) and len(eng2.journal.events(level="CRITICAL")) == 1


def test_max_total_until_and_a_missing_learner_stop_it(tmp_path):
    eng, view = build(tmp_path, {"exploration": {**ON["exploration"], "max_total": 1, "max_per_day": 5}})
    ev_pass(eng)
    eng.risk.max_trades = 10
    assert eng._maybe_enter("NIFTY", view, {}, NOW).startswith("ENTER")
    later = NOW + pd.Timedelta(days=3)                               # a later session: the total, from the journal, still binds
    assert eng._explore_off(later) == "exploration spent its 1 trades"
    eng.explore["max_total"] = 40
    assert eng._explore_off(later) is None
    eng.explore["until"] = DAY                                       # the day itself is inside; the next is not
    assert eng._explore_off(NOW) is None and "ended" in eng._explore_off(later)
    eng.quant_on = False                                             # no EV floor to pass: no exploration
    assert "EV floor" in eng._explore_off(NOW)
    eng.quant_on, eng.learner = True, None
    assert "learning loop is off" in eng._explore_off(NOW)
    bad, _ = build(tmp_path / "d", {"exploration": {**ON["exploration"], "until": "not a date"}})
    assert "ended" in bad._explore_off(NOW)                          # an unreadable end date is an expired one


def test_the_paper_gate_excludes_exploration():
    def meta(**k):
        return json.dumps({"quote_source": "kotak", "fill_quotes": "live kotak book", "exit_quotes": "live kotak book", **k})
    t = pd.DataFrame({"pnl": [100.0, 5000.0, -40.0], "status": "closed", "meta": [meta(), meta(mode="exploration"), "not json"]})
    kept, n = without_exploration(t)
    assert n == 1 and list(kept["pnl"]) == [100.0, -40.0]
    real, _ = real_quote_trades(kept)
    assert evaluate_paper_candidate(real, 1, 0, 500000)["net_pnl_after_costs"] == 100.0
    assert without_exploration(pd.DataFrame())[1] == 0


def test_champion_paper_ledger_skips_exploration(tmp_path):
    from test_autolearn import cfg_for, loader_of

    from quantdesk.autolearn.cycle import Cycle
    from quantdesk.autolearn.store import ChainLog
    from quantdesk.journal.journal import Journal
    j = Journal(tmp_path / "j.db")
    for tid, m in (("T1", {}), ("T2", {"mode": "exploration"})):
        j._exec("INSERT INTO trades (id, strategy, symbol, opened_at, closed_at, pnl, fees, r_multiple, meta, status) VALUES "
                "(?,?,?,?,?,?,?,?,?,?)", (tid, "orb", "NIFTY", "2026-07-01 10:00:00+05:30", "2026-07-01 10:40:00+05:30", 350.0, 60.0,
                                          0.5, json.dumps(m), "closed"))
    j.commit()
    c = Cycle(cfg_for(tmp_path), now=ts("2026-07-01 16:30"), loader=loader_of({}), journal_path=tmp_path / "j.db",
              root=tmp_path / "al2", say=None)
    assert c._ingest_paper_trades() == (1, 0)
    assert [r["trade_id"] for r in ChainLog(tmp_path / "al2" / "paper_trades.jsonl").read()] == ["T1"]


def test_session_review_counts_exploration_separately(tmp_path):
    eng, view = build(tmp_path, ON)
    ev_pass(eng)
    assert eng._maybe_enter("NIFTY", view, {}, NOW).startswith("ENTER")
    eng._close(eng.open_trades[0], NOW + pd.Timedelta(minutes=20), "time_exit", "test")
    review = eng.session_review()
    assert "1 trade(s) (1 exploration" in review and "(exploration)" in review and "Exploration: 1 trade(s)" in review
