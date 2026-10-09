"""Phase E forensic probes (read-only: synthetic data, temp dirs and a copy of the journal).

    QD_JOURNAL=/tmp/qd_journal/intraday python -m pytest -o addopts="" -q -p no:cacheprovider audit/probes

Each passing probe CONFIRMS the finding it names (audit/QUANTDESK_FINDINGS_REGISTER.md). The statistical and
data-heavy reproductions (v2 rerun, D1 on official closes, spreads, NW/BH/DSR references) are the phase_e_*.py
scripts next to this file; their outputs are in audit/data/phase_e_*.
"""
import inspect
import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

REPO = Path(os.environ.get("QD_REPO", str(Path(__file__).resolve().parents[2])))
JOURNAL = Path(os.environ.get("QD_JOURNAL", "/nonexistent"))
sys.path.insert(0, str(REPO))


def _ledger(name):
    p = JOURNAL / "sleeves" / f"{name}.jsonl"
    if not p.exists():
        pytest.skip("journal snapshot not available")
    return [json.loads(x) for x in p.read_text().splitlines() if x.strip()]


# ---- E-01: the sleeve rules run on the registered (stale-minute) settlement, not the official close -------------------
def test_sleeve_rules_use_registered_settlement_pnl():
    from quantdesk.intraday import sleeves
    src = inspect.getsource(sleeves.assess)
    assert 'pnl = [t["pnl_rs"] for t in trades]' in src and "pnl_rs_official" not in src


def test_official_close_flips_the_sign_of_both_nifty_sleeve_trades():
    ev = _ledger("expiry_seller_v1")
    settle = {e["id"]: e for e in ev if e["event"] == "settle"}
    off = {e["id"]: e for e in ev if e["event"] == "official"}
    for tid in ("A-NIFTY-2026-10-06", "B-NIFTY-2026-10-06"):
        assert settle[tid]["pnl_rs"] > 0 > off[tid]["pnl_rs_official"]        # +560 / +2,142 → −3,419 / −1,838
        assert off[tid]["settle_gap_bps"] < -25


def test_recorded_index_freezes_from_1515_every_full_session():
    root = JOURNAL / "data"
    if not root.exists():
        pytest.skip("journal snapshot not available")
    full = 0
    for day in sorted(p for p in root.iterdir() if p.is_dir()):
        f = day / "NIFTY_1m.csv"
        if not f.exists():
            continue
        d = pd.read_csv(f)
        if len(d) < 370:
            continue
        full += 1
        w = d[d.ts.str[11:16].between("15:15", "15:28")]
        assert w.close.value_counts().iloc[0] >= 12                           # 12-14 identical flat minutes
        assert ((w.open == w.close) & (w.high == w.low)).all()
        if day.name >= "2026-10-05":                                          # Kotak sessions (09-29 had no volume at all)
            assert (w.volume > 0).all()                                       # yet volume keeps "trading"
    assert full >= 5


# ---- E-02: the paper-eligibility gate passes a zero-edge sleeve most of the time --------------------------------------
def test_paper_gate_admits_a_zero_edge_sleeve():
    from quantdesk.intraday.sleeves import MIN_ELIGIBLE, assess
    hist = {"mean": 118.0, "sd": 2232.0, "worst": -8457.0}                    # A_NIFTY, expiry_seller_v1.json
    rng = np.random.default_rng(0)
    elig = 0
    for _ in range(2000):
        pnl = rng.normal(0.0, 2232.0, MIN_ELIGIBLE)                          # true edge: zero
        trades = [{"id": str(i), "pnl_rs": float(p), "cost_gap_rs": float(rng.normal(0, 5))} for i, p in enumerate(pnl)]
        elig += assess(trades, hist, naked=False)["eligible"]
    assert elig / 2000 > 0.85                                                 # ≈ 0.93: "eligible" = "not rejected"


# ---- E-03: the D1 research drift (not a registered study) enters every live EV --------------------------------------
def test_d1_drift_becomes_the_live_ev_base_drift(tmp_path):
    from quantdesk.intraday.quant import load_research
    p = tmp_path / "edges.json"
    p.write_text(json.dumps([{"id": "D1", "symbol": "NIFTY", "verdict": "PAPER CANDIDATE", "effect_bps": -5.7, "t": -3.45}]))
    d = load_research(p)["NIFTY"]["drift"]
    assert d["per_min"] == pytest.approx(-5.7 / 1e4 / 375)
    eng = (REPO / "quantdesk/intraday/engine.py").read_text()
    assert 'drift = ((self.research.get(u) or {}).get("drift") or {}).get("per_min", 0.0)' in eng
    edges = (REPO / "quantdesk/research/edges.py").read_text()
    assert "theta is paid for by gamma" in edges                              # the hurdle assumes fair option prices


# ---- E-04: the duplicate guard stops identical experiments only; a one-number variant is "new" ------------------------
def test_fingerprint_guard_admits_a_one_number_variant():
    from quantdesk.research import memory as M
    reg = M.registry()
    v2 = next(r for r in reg if r["name"] == "expiry_eve_law_v2")
    variant = json.loads(json.dumps(v2["spec"]))
    variant["tests"]["pooled"] = variant["tests"]["pooled"].replace("1.645", "1.5")
    variant["name"] = "expiry_eve_law_v2b"
    c = M.check(variant, reg)
    assert c["identical"] == []                                               # not a repeat, so it may be registered
    assert c["nearest"][0][1] == "expiry_eve_law_v2" and c["nearest"][0][0] > 0.9   # though it is v2 with a lower bar


def test_experiment_ledger_does_not_cover_the_program():
    log = REPO / "docs/prereg/results"
    names = {p.stem.split("-")[0] for p in log.glob("*.json")}
    src = (REPO / "quantdesk/research/laws.py").read_text() + (REPO / "quantdesk/research/wings.py").read_text()
    assert "experiment_log" not in src                                        # registered studies never reach the ledger
    assert {"expiry_eve_law_v1", "expiry_eve_law_v2", "expiry_wings_v1"} <= names


# ---- E-05: the v2 spec has no frozen sample end -------------------------------------------------------------------
def test_v2_spec_has_no_frozen_sample():
    spec = json.loads((REPO / "docs/prereg/expiry_eve_law_v2.json").read_text())
    flat = json.dumps(spec).lower()
    assert not any(k in spec for k in ("end", "until", "sample", "period", "to"))
    assert "2026-10-01" not in flat                                           # the registered result's last expiry


# ---- E-06: provenance only on one result, and that one dirty -------------------------------------------------------
def test_registered_results_mostly_lack_provenance():
    res = {p.name: json.loads(p.read_text()) for p in (REPO / "docs/prereg/results").glob("*.json")}
    stamped = {k for k, v in res.items() if "provenance" in v}
    assert stamped == {"expiry_eve_law_v2_audit-7eee17d7220f.json"}
    assert res["expiry_eve_law_v2_audit-7eee17d7220f.json"]["provenance"]["code"]["dirty"] is True


# ---- E-08: the vol study's "desk" baseline is not the forecaster production runs ----------------------------------
def test_vol_study_baseline_excludes_the_live_iv_blend():
    from quantdesk.intraday.quant import VolForecaster
    assert VolForecaster().iv_weight == pytest.approx(0.3)                    # production blends 30% ATM IV
    vs = (REPO / "quantdesk/autolearn/volstudy.py").read_text()
    assert "A_desk: the desk's forecaster without IV" in vs
    assert "C_har" not in (REPO / "quantdesk/intraday/quant.py").read_text()  # L3's winner is not used live
