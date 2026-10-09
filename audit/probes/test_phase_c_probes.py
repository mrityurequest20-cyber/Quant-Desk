"""Phase C forensic probes (read-only: synthetic data and temp dirs only).

    python -m pytest -o addopts="" -q -p no:cacheprovider audit/probes

Each passing probe CONFIRMS the finding it names (audit/QUANTDESK_FINDINGS_REGISTER.md).
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
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tests"))
IST = "Asia/Kolkata"


def _cfg(tmp=None):
    from quantdesk.config import Config, DEFAULT_CONFIG
    return Config.load(DEFAULT_CONFIG, overrides={"runtime": {"dir": str(tmp)}} if tmp else None)


# ---- C-01: even an approved plan model can't let a live directional plan through at ₹5L ------------------------------
def test_approved_plan_model_still_rejects_every_live_directional_plan(tmp_path):
    from quantdesk.autolearn.live import LiveLearner
    from quantdesk.autolearn.plans import dte_bucket
    from quantdesk.intraday.playbook import PlanLeg, TradePlan
    cfg = _cfg(tmp_path)
    # the live config at ₹5L: short legs allowed, every directional setup always builds a debit spread
    assert cfg.get("intraday.capital") >= cfg.get("intraday.short_legs_from_equity")
    for s in ("orb", "vwap_trend", "trend_break", "va_reversion"):
        assert cfg.get(f"intraday.setups.{s}")["always_spread"] is True
    src = inspect.getsource(__import__("quantdesk.intraday.playbook", fromlist=["Playbook"]).Playbook._directional)
    assert 'self.allow_short and (p.get("always_spread", False)' in src

    now = pd.Timestamp("2026-10-08 10:30", tz=IST)
    exp = dt.date(2026, 10, 13)
    ll = LiveLearner(cfg, root=tmp_path / "al")
    ll.start(now.date())
    n = ll.cal.trading_days_between(now.date(), exp)

    class Approving:                                              # a plan champion that approves everything
        bucket, horizon, tau = dte_bucket(n), "30m", 0.0

        def score(self, row):
            return np.array([1.0])

        def p_win(self, row):
            return np.array([0.9])

    from quantdesk.intraday.quant import FEATURES
    ll.plan = ("stub", Approving())
    ll.feats["NIFTY"] = (now, {k: 0.0 for k in FEATURES})

    def plan(legs):
        return TradePlan("orb", "NIFTY", 1, "x", exp, legs, 65, "t", "th", 22400.0, 22600.0, 0.3, 0.6, 45, "kotak", 0.6)
    long_leg = PlanLeg(22500, "CE", 1, 100.0, 99.0, 14.0, 0.45)
    short_leg = PlanLeg(22650, "CE", -1, 40.0, 41.0, 13.0, 0.25)
    kept, why = ll.plan_gate("NIFTY", [plan([long_leg, short_leg])], now)
    assert kept == [] and "single long options only" in why       # the spread the live desk builds: rejected
    kept1, _ = ll.plan_gate("NIFTY", [plan([long_leg])], now)
    assert len(kept1) == 1                                         # a single long option: approved


# ---- C-02: the session DirectionModel's gate passes on noise ---------------------------------------------------------
def test_session_direction_model_validates_on_random_walks():
    from test_autolearn import market, sessions
    from quantdesk.intraday.quant import DirectionModel, features_5m, to_5m
    valid = 0
    for seed in range(40):
        m = DirectionModel()
        m.fit(features_5m(to_5m(market(sessions(52, start="2026-07-20"), phi=0.0, seed=seed))))
        valid += m.valid
    assert valid >= 1                     # 4/40 here; 20/200 = 10% in the audit's run: a gate that noise passes


# ---- C-03: no automatic demotion of a champion ---------------------------------------------------------------------
def test_no_automatic_champion_demotion():
    from quantdesk.autolearn import cycle as C
    from quantdesk.autolearn import research as R
    promote = inspect.getsource(C.Cycle._promote)
    assert 'for mid in reg.get("challengers", [])' in promote      # only challengers are judged
    assert "reject(champ" not in promote and "demot" not in promote
    for mod in (C, R):                                             # no automatic path calls Registry.rollback
        assert "reg.rollback(" not in inspect.getsource(mod)
    cli = (REPO / "quantdesk/autolearn/cli.py").read_text()
    assert "rollback(" in cli                                      # rollback exists only as an operator command


# ---- C-04: two cost models disagree on futures STT ------------------------------------------------------------------
def test_autolearn_and_desk_cost_models_disagree_on_futures_stt():
    cfg = _cfg()
    desk = cfg.get("costs.segments.futures")["stt_sell"] * 1e4     # bps
    auto = cfg.get("autolearn.costs")["stt_sell_bps"]
    assert desk == pytest.approx(5.0) and auto == pytest.approx(2.0)
