"""The self-learning paper loop (quantdesk/autolearn): leakage, purging and embargo, immutable records, registry integrity,
reproducibility, calibration, abstention, costs, drift, promotion gates, rollback, stale feeds, risk halts, journal
recovery, failed retraining, and Ollama staying explanatory."""
import json
import os

import numpy as np
import pandas as pd
import pytest

from quantdesk.autolearn import drift as D
from quantdesk.autolearn.cycle import STAGES, Cycle, CycleBusy
from quantdesk.autolearn.evaluate import CostModel, gates, simulate
from quantdesk.autolearn.features import FEATURES, build_samples, fingerprint, validate_bars
from quantdesk.autolearn.ledger import LeakageError, Ledger
from quantdesk.autolearn.live import LiveLearner
from quantdesk.autolearn.models import NEVER, ArtifactError, Pipeline, choose_tau, fit_platt
from quantdesk.autolearn.registry import PromotionRefused, Registry
from quantdesk.autolearn.store import ChainLog
from quantdesk.autolearn.validation import LockBox, WalkForwardConfig, folds, split
from quantdesk.config import DEFAULT_CONFIG, Config
from quantdesk.intraday.quant import to_5m

IST = "Asia/Kolkata"


def ts(x):
    return pd.Timestamp(x, tz=IST)


def sessions(n, start="2026-06-01"):
    return [d.date() for d in pd.bdate_range(start, periods=n)]


def market(days, phi=0.0, sig=0.0015, seed=0, start=25000.0):
    """1-minute bars from 5-minute log returns that follow an AR(1) with coefficient `phi` (0: a random walk; 0.5: a
    planted momentum that a model can learn and that beats the costs), each 5-minute step split over its 5 minutes."""
    rng = np.random.default_rng(seed)
    frames, S = [], start
    for d in days:
        r = np.zeros(75)
        e = rng.normal(0, sig, 75)
        for i in range(75):
            r[i] = (phi * r[i - 1] if i else 0.0) + e[i]
        steps = np.repeat(r / 5, 5)
        c = S * np.exp(np.cumsum(steps))
        o = np.r_[S, c[:-1]]
        idx = pd.date_range(f"{d} 09:15", periods=375, freq="1min", tz=IST)
        frames.append(pd.DataFrame({"open": o, "high": np.maximum(o, c) * 1.0001, "low": np.minimum(o, c) * 0.9999,
                                    "close": c, "volume": 1000.0}, index=idx))
        S = float(c[-1])
    return pd.concat(frames)


def cfg_for(tmp_path, **auto):
    a = {"bootstrap": {"samples": 200, "block_days": 3, "seed": 7},
         "promotion": {"min_shadow_sessions": 3, "min_shadow_signals": 10, "max_challenger_days": 45},
         "candidates": ["baseline", "logit_l1", "stumps"], **auto}
    return Config.load(DEFAULT_CONFIG, overrides={"runtime": {"dir": str(tmp_path / "runtime")}, "autolearn": a})


def loader_of(bars: dict):
    return lambda sym: [("synthetic", bars[sym], True)]


# ---- features, labels, data quality --------------------------------------------------------------------------------
def test_features_are_causal_and_labels_come_only_from_later_bars():
    b5 = to_5m(market(sessions(3), phi=0.3, seed=1))
    s = build_samples(b5, "NIFTY")
    day = sorted(s["day"].unique())[-1]
    full = s[s["day"] == day].reset_index(drop=True)
    for k in (8, 30, 60):                                      # recompute on bars truncated at the decision: identical
        cut = full["ts"].iloc[k]
        trunc = build_samples(b5[b5.index + pd.Timedelta(minutes=5) <= cut], "NIFTY")
        row = trunc[trunc["ts"] == cut].iloc[0]
        assert np.allclose(row[FEATURES].to_numpy(float), full.loc[k, FEATURES].to_numpy(float))
    r = full.iloc[10]
    c = b5[b5.index.date == pd.Timestamp(day).date()]["close"].to_numpy()
    assert r["fwd_ret"] == pytest.approx(np.log(c[16] / c[10])) and r["y"] == float(c[16] > c[10])
    assert pd.Timestamp(r["label_end"]) == r["ts"] + pd.Timedelta(minutes=30)
    assert full["y"].iloc[-6:].isna().all()                    # no label where the session ends first


def test_bar_validation_cleans_and_flags():
    b = market(sessions(2), seed=2)
    dup = b.iloc[[10]].copy()
    dup["close"] *= 1.01                                       # a conflicting duplicate
    bad = pd.concat([b, dup, b.iloc[[20]]]).iloc[::-1]          # out of order, plus an identical duplicate
    bad.loc[bad.index[5], "close"] = np.nan
    jump = bad.copy()
    i = jump.index.get_loc(b.index[400])
    jump.iloc[i, jump.columns.get_loc("close")] *= 1.08
    clean, rep = validate_bars(jump, holidays=set(), freq_min=1)
    assert clean.index.is_monotonic_increasing and not clean.index.duplicated().any()
    assert rep["out_of_order"] and rep["conflicting_duplicates"] == 1 and rep["missing"] == 1
    assert rep["jump_days"] == [str(b.index[400].date())] and not rep["ok"]
    assert set(clean.index.date) == {b.index[0].date()}         # the jump session is quarantined
    hol = {b.index[0].date()}
    clean2, rep2 = validate_bars(b, holidays=hol, freq_min=1)
    assert rep2["closed_days"] == 1 and set(clean2.index.date) == {b.index[-1].date()}
    last = b.index[-1]
    _, rep3 = validate_bars(b, now=last.normalize() + pd.Timedelta(hours=14), max_age_min=3, freq_min=1)
    assert rep3["stale"] is False                               # the session closed: not stale
    live = b[b.index < last.normalize() + pd.Timedelta(hours=11)]
    _, rep4 = validate_bars(live, now=last.normalize() + pd.Timedelta(hours=11, minutes=10), max_age_min=3, freq_min=1)
    assert rep4["stale"] is True and not rep4["ok"]
    assert fingerprint(b) == fingerprint(b.copy()) != fingerprint(b.iloc[:-1])


# ---- walk-forward, purge, embargo, the locked final test -------------------------------------------------------------
def test_walk_forward_purges_overlapping_labels_and_embargoes():
    s = build_samples(to_5m(market(sessions(30), seed=3)), "NIFTY")
    cfg = WalkForwardConfig(folds=3, min_train_days=12, embargo_min=30)
    fl = folds(s, cfg)
    assert len(fl) == 3 and all(max(f["train_days"]) < min(f["test_days"]) for f in fl)
    assert fl[0]["test_days"][0] == sorted(s["day"].unique())[12]
    # a fold that starts mid-session: training rows whose label is still open at the start are purged, and the last
    # 30 minutes of decisions before it are embargoed
    day = sorted(s["day"].unique())[20]
    start = ts(f"{day} 12:00")
    f = {"fold": 9, "train_days": sorted(s["day"].unique())[:21], "test_days": [day], "test_start": start,
         "test_end": ts(f"{day} 15:30")}
    s2 = s[(s["day"] != day) | (s["ts"] <= start) | (s["ts"] > start)]
    tr, te, info = split(s2, f, cfg)
    same = tr[tr["day"] == day]
    assert (pd.to_datetime(same["label_end"]) <= start).all() and (same["ts"] <= start - pd.Timedelta(minutes=30)).all()
    assert info["purged"] > 0 and info["embargoed"] >= 0
    # the locked final test: created once, never moved, never in a fold
    lb = LockBox(tmp := (os.path.join(os.path.dirname(__file__), "..", "runtime", "_lb_test")))
    try:
        lock = lb.ensure(s, 5, ts("2026-07-20 16:00"))
        assert lock["days"] == sorted(s["day"].unique())[-5:]
        more = build_samples(to_5m(market(sessions(35), seed=3)), "NIFTY")
        assert lb.ensure(more, 5)["days"] == lock["days"]       # newer data never moves it
        fl2 = folds(more, cfg, set(lock["days"]))
        assert not set().union(*[set(f["test_days"]) | set(f["train_days"]) for f in fl2]) & set(lock["days"])
        assert lb.verify(s) == []
        tampered = s.copy()
        tampered.loc[tampered["day"] == lock["days"][0], "y"] = 1.0
        assert lb.verify(tampered)                               # its labels changed: reported
        assert lb.verify(tampered.drop(tampered.index[tampered["day"] == lock["days"][0]][:1]))   # …and a row dropped (A-07)
        assert lb.verify(s.drop(s.index[s["day"] == lock["days"][-1]][:1]))                     # a row dropped alone
        assert lb.record_access("m", "test") == 1 and lb.peeks() == 1
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


# ---- models: baseline, calibration, abstention ---------------------------------------------------------------------
def test_baseline_is_the_direction_model_and_calibration_and_abstention_behave():
    from quantdesk.intraday.quant import DirectionModel
    s = build_samples(to_5m(market(sessions(30), phi=0.5, seed=4)), "NIFTY").dropna(subset=["y"])
    X, y = s[FEATURES].to_numpy(float), s["y"].to_numpy(float)
    dm = DirectionModel()
    w, mu, sd = dm._fit(X, y)
    p = Pipeline("baseline").fit(s, cost_bps=6.0)
    from quantdesk.autolearn.models import Logit
    lg = Logit(3.0).fit(X, y)
    assert np.allclose(lg.w, w) and np.allclose(lg.mu, mu)      # the baseline is the live DirectionModel's fit
    # Platt: an over-confident score is pulled in, a calibrated one left alone
    rng = np.random.default_rng(0)
    z = rng.normal(0, 1, 4000)
    yy = (rng.random(4000) < 1 / (1 + np.exp(-0.4 * z))).astype(float)
    a, b = fit_platt(z, yy)
    assert a == pytest.approx(0.4, abs=0.08) and abs(b) < 0.1
    # abstention: a planted signal earns a threshold; noise abstains on everything
    assert 0 <= p.tau < NEVER and (p.signal(np.array([0.5])) == 0).all()
    noise = rng.random(3000)
    tau, _ = choose_tau(noise, rng.normal(0, 0.002, 3000), cost_bps=6.0)
    assert tau == NEVER and Pipeline("baseline").signal(noise).sum() == 0
    # the artifact round-trips and refuses tampering
    art = p.artifact()
    q = Pipeline.from_artifact(art)
    assert np.allclose(q.predict(s.head(50)), p.predict(s.head(50)))
    bad = {**art, "tau": 0.0}
    with pytest.raises(ArtifactError):
        Pipeline.from_artifact(bad)
    with pytest.raises(ArtifactError):
        Pipeline.from_artifact({**art, "feature_version": "f0", "sha256": art["sha256"]})


# ---- costs and simulation --------------------------------------------------------------------------------------------
def test_cost_model_and_non_overlapping_simulation():
    c = CostModel(lot={"NIFTY": 65})
    px = 25000.0
    notional = px * 65
    want = (40 / notional * 1e4 + 2 * 0.173 + 2 * 10 / 1e7 * 1e4 + 5.0 + 0.2
            + 0.18 * (40 / notional * 1e4 + 2 * 0.173 + 2 * 10 / 1e7 * 1e4) + 2 * 0.5 + 2 * 1.0)
    assert c.round_trip_bps(px, "NIFTY") == pytest.approx(want)
    t0 = ts("2026-06-01 10:00")
    rows = pd.DataFrame({"symbol": "NIFTY", "day": "2026-06-01", "ts": [t0 + pd.Timedelta(minutes=5 * i) for i in range(8)],
                         "fwd_ret": 0.001, "entry_px": px, "minute": 45.0, "sig5": 8e-4, "day_ret": 0.0})
    rows["label_end"] = rows["ts"] + pd.Timedelta(minutes=30)
    sig = np.array([1, 1, 1, 1, 1, 1, 1, 0])
    tr = simulate(rows, np.full(8, 0.6), sig, c)
    assert len(tr) == 2 and list(tr["ts"]) == [rows["ts"][0], rows["ts"][6]]   # one position per symbol at a time
    assert tr["net_bps"].iloc[0] == pytest.approx(10.0 - want)
    assert len(simulate(rows, np.full(8, 0.6), sig, c, overlap=True)) == 6               # capped at 6 a session
    c.max_trades_per_symbol_day = 3
    assert len(simulate(rows, np.full(8, 0.6), sig, c, overlap=True)) == 3


def test_the_learner_charges_the_desks_futures_stt_unless_overridden():
    cfg = Config.load(DEFAULT_CONFIG)
    c = CostModel.from_cfg(cfg)
    fut = cfg.get("costs.segments.futures")
    assert c.stt_sell_bps == 5.0 == pytest.approx(fut["stt_sell"] * 1e4)            # 0.05% on the sell, as the desk charges
    assert c.exchange_bps == pytest.approx(fut["exchange"] * 1e4) and c.stamp_buy_bps == pytest.approx(fut["stamp_buy"] * 1e4)
    assert CostModel().stt_sell_bps == 5.0
    over = CostModel.from_cfg(cfg.with_overrides({"autolearn": {"costs": {"stt_sell_bps": 3.0}}}))
    assert over.stt_sell_bps == 3.0 and over.exchange_bps == c.exchange_bps         # an explicit override still wins


# ---- the immutable ledger -----------------------------------------------------------------------------------------------
def _decision(t, sym="NIFTY", model="m1", sig=1):
    return {"ts": t, "symbol": sym, "features": {f: 0.1 for f in FEATURES}, "models": [
        {"model_id": model, "role": "champion", "p_raw": 0.6, "p": 0.6, "confidence": 0.2, "signal": sig, "abstained": sig == 0,
         "tau": 0.02}], "data_fingerprint": "fp", "costs_assumed": 6.0, "label_end": t + pd.Timedelta(minutes=30),
        "minute": 100.0, "source": "live"}


def test_ledger_is_append_only_leak_proof_and_recoverable(tmp_path):
    L = Ledger(tmp_path)
    t = ts("2026-06-02 11:00")
    did = L.record_decision(_decision(t), now=t + pd.Timedelta(seconds=20))
    assert did and L.record_decision(_decision(t), now=t + pd.Timedelta(seconds=30)) is None      # once only
    with pytest.raises(LeakageError):                           # written after the outcome was knowable
        L.record_decision(_decision(t + pd.Timedelta(minutes=5)), now=t + pd.Timedelta(minutes=40))
    with pytest.raises(LeakageError):                           # an outcome before its window closed
        L.record_outcome(did, t, {"label_end": str(t + pd.Timedelta(minutes=30)), "fwd_ret": 0.0}, now=t + pd.Timedelta(minutes=10))
    assert L.verify() == []
    p = next((tmp_path / "ledger").glob("predictions-*.jsonl"))
    lines = p.read_text().splitlines()
    rec = json.loads(lines[0])
    rec["models"][0]["p"] = 0.99                                # someone edits history
    p.write_text(json.dumps(rec, sort_keys=True, separators=(",", ":")) + "\n")
    assert any("altered" in x for x in L.verify())
    p.write_text(lines[0] + "\n" + '{"torn": tr')                # a crash mid-append
    L2 = Ledger(tmp_path)
    assert L2.recover() == 1 and L2.verify() == [] and p.with_suffix(".jsonl.corrupt").exists()
    # resolution uses only the bars after the decision and the existing label
    b = market(sessions(1, "2026-06-02"), phi=0.0, seed=5)
    b5 = to_5m(b)
    assert L2.resolve({"NIFTY": b5}, now=t + pd.Timedelta(minutes=20)) == 0                 # window still open
    assert L2.resolve({"NIFTY": b5}, now=t + pd.Timedelta(hours=1)) == 1
    o = L2.outcomes()[did]
    c = b5["close"]
    assert o["fwd_ret"] == pytest.approx(np.log(c[t + pd.Timedelta(minutes=25)] / c[t - pd.Timedelta(minutes=5)]))
    assert L2.resolve({"NIFTY": b5}, now=t + pd.Timedelta(hours=2)) == 0                    # never twice


# ---- drift ---------------------------------------------------------------------------------------------------------
def test_drift_detects_shifted_features_and_calibration():
    rng = np.random.default_rng(1)
    train = pd.DataFrame({f: rng.normal(0, 1, 2000) for f in FEATURES})
    card = {"drift_reference": D.references(train, rng.uniform(0.4, 0.6, 2000)),
            "validation": {"metrics": {"classification": {"ece": 0.02}, "ci": {"expectancy_bps": {"lo": 0.5}}}}}

    def recent(shift, p_bias):
        f = pd.DataFrame({f"f_{k}": rng.normal(shift, 1, 400) for k in FEATURES})
        p_true = rng.uniform(0.4, 0.6, 400)
        f["p"] = np.clip(p_true + p_bias, 0, 1)                   # p_bias 0: outcomes drawn from p (calibrated)
        f["y"] = (rng.random(400) < p_true).astype(float)
        f["signal"], f["resolved"], f["net_bps"] = 1, True, rng.normal(1.0, 5, 400)
        return f
    ok = D.report(card, recent(0.0, 0.0))
    assert ok["state"] == "ok" and ok["checks"]["feature_psi_max"] < 0.1
    bad = D.report(card, recent(1.5, 0.3))
    assert bad["state"] == "alarm" and any("feature drift" in r for r in bad["reasons"]) and any("calibration" in r for r in bad["reasons"])
    assert D.report(card, recent(0, 0).head(20))["state"] == "insufficient data"


# ---- the cycle: registration, shadow paper, promotion, rollback ------------------------------------------------------
def _shadow_days(cfg, root, bars, days, source="live"):
    """Run the live learner over `days` the way the desk does: a decision at every 5-minute bar end, outcomes after."""
    ll = LiveLearner(cfg, root=root, source=source)
    for d in days:
        ll.start(d)
        day_bars = bars[bars.index.date <= d]
        prev = day_bars[day_bars.index.date < d]
        prev_close = float(prev["close"].iloc[-1]) if len(prev) else float("nan")
        for t in pd.date_range(f"{d} 09:20", f"{d} 15:30", freq="5min", tz=IST):
            ll.on_bar("NIFTY", t + pd.Timedelta(seconds=5), day_bars[day_bars.index < t], d, prev_close, float("nan"))
        ll.resolve({"NIFTY": day_bars}, ts(f"{d} 15:45"))
    return ll


def test_full_cycle_registers_shadows_promotes_and_rolls_back(tmp_path):
    days = sessions(60)
    bars = {"NIFTY": market(days, phi=0.5, seed=7), "BANKNIFTY": market(days, phi=0.5, seed=8, start=55000.0)}
    cfg = cfg_for(tmp_path)
    root = tmp_path / "al"
    hist = {k: v[v.index.date <= days[52]] for k, v in bars.items()}
    c = Cycle(cfg, now=ts(f"{days[52]} 16:30"), loader=loader_of(hist), journal_path=tmp_path / "none.db", root=root, say=None)
    st = c.run()
    assert st["status"] == "done", st
    out = {k: v["output"] for k, v in st["stages"].items()}
    assert out["dataset"]["quality_ok"] and len(out["dataset"]["lockbox_days"]) == 8
    assert out["validate"]["passed"], out["validate"]["summary"]
    reg = Registry(root)
    assert reg.state()["champion"] is None and reg.challengers()        # retraining makes challengers only
    assert out["promote"]["decision"] == "no change"                    # no shadow record yet
    mid = reg.challengers()[0]
    card = reg.card(mid)
    for k in ("model_id", "code_fingerprint", "feature_version", "data_fingerprint", "training_window", "validation",
              "artifacts", "status", "lockbox", "drift_reference"):
        assert card.get(k) is not None, k
    assert card["lockbox"]["passed"] and card["validation"]["metrics"]["trading"]["expectancy_bps"] > 0
    assert LockBox(root).peeks() >= 1
    # rerun on the same inputs: every stage skipped, nothing new registered (idempotent)
    again = Cycle(cfg, now=ts(f"{days[52]} 16:30"), loader=loader_of(hist), journal_path=tmp_path / "none.db", root=root, say=None)
    assert again.run()["stages"]["register"]["output"]["registered"] == out["register"]["registered"]
    assert len(reg.challengers()) == len(out["register"]["registered"])
    # live shadow sessions, then the cycle promotes on the evidence
    _shadow_days(cfg, root, bars["NIFTY"], days[53:58])
    later = Cycle(cfg, now=ts(f"{days[58]} 16:30"), loader=loader_of(bars), journal_path=tmp_path / "none.db", root=root, say=None)
    st2 = later.run(["ingest", "paper", "promote"])
    dec = st2["stages"]["promote"]["output"]["decision"]
    assert dec.startswith("promoted"), st2["stages"]["promote"]["output"]
    champ = reg.state()["champion"]
    assert reg.card(champ)["status"] == "champion" and reg.card(champ)["approval"]["checks"]
    # the live learner now steers with it, and fails closed if its artifact is tampered with
    ll = LiveLearner(cfg, root=root)
    ll.start(days[59])
    assert ll.active and ll.champion_id == champ
    art = root / "registry" / "models" / champ / "artifact.json"
    a = json.loads(art.read_text())
    a["tau"] = 0.0
    art.write_text(json.dumps(a))
    ll.start(days[59])
    assert not ll.active and "failed verification" in ll.fault
    assert any(champ in x for x in reg.verify())
    assert reg.state()["rollback_target"] is None
    with pytest.raises(PromotionRefused):                       # nothing to roll back to yet
        reg.rollback("test")


def test_promotion_is_fail_closed_and_rollback_restores_the_previous_champion(tmp_path):
    s = build_samples(to_5m(market(sessions(30), phi=0.5, seed=9)), "NIFTY").dropna(subset=["y"])
    reg = Registry(tmp_path)
    base_card = {"code_fingerprint": "c", "feature_version": "f", "label_version": "l", "data_fingerprint": "d",
                 "training_window": {}, "validation": {"passed": True}, "registered_at": "2026-07-01 16:30:00+05:30"}
    a, _ = reg.register(Pipeline("baseline").fit(s, 6.0), base_card)
    b, _ = reg.register(Pipeline("logit_l1").fit(s, 6.0), base_card)
    with pytest.raises(PromotionRefused):
        reg.promote(a, "x", {"paper_sessions": False, "risk_limits": True})
    with pytest.raises(PromotionRefused):
        reg.promote(a, "x", {})
    assert reg.state()["champion"] is None
    reg.promote(a, "passed", {"all": True})
    reg.promote(b, "passed", {"all": True})
    assert reg.state()["champion"] == b and reg.state()["rollback_target"] == a
    reg.rollback("drill")
    assert reg.state()["champion"] == a and reg.card(b)["status"] == "retired"
    st = json.loads((tmp_path / "registry" / "state.json").read_text())
    (tmp_path / "registry" / "state.json").write_text("{broken")
    assert reg.rebuild_state()["champion"] == st["champion"]    # state is rebuilt from the event log
    assert reg.events.verify() == []


def test_failed_retraining_leaves_the_registry_untouched_and_resumes(tmp_path):
    cfg = cfg_for(tmp_path)
    root = tmp_path / "al"
    few = {k: market(sessions(6), seed=i) for i, k in enumerate(["NIFTY", "BANKNIFTY"])}
    c = Cycle(cfg, now=ts("2026-07-01 16:30"), loader=loader_of(few), journal_path=tmp_path / "x.db", root=root, say=None)
    st = c.run()
    assert st["status"] == "failed" and st["stages"]["train"]["status"] == "failed"
    assert Registry(root).state()["champion"] is None and not Registry(root).challengers()
    assert "not enough sessions" in st["stages"]["train"]["error"]
    # more data arrives: the next run resumes (ingest/dataset rerun on new inputs, train goes on)
    more = {k: market(sessions(40), seed=i) for i, k in enumerate(["NIFTY", "BANKNIFTY"])}
    c2 = Cycle(cfg, now=ts("2026-07-02 16:30"), loader=loader_of(more), journal_path=tmp_path / "x.db", root=root, say=None)
    st2 = c2.run()
    assert st2["stages"]["train"]["status"] == "done"
    assert st2["stages"]["validate"]["output"]["passed"] == []           # a random walk passes nothing
    assert Registry(root).challengers() == []
    # a held lock refuses a second cycle; a stale one is taken over on the record
    (root / "cycle.lock").write_text(json.dumps({"pid": -1, "at": str(ts("2026-07-02 16:00"))}))
    with pytest.raises(CycleBusy):
        Cycle(cfg, now=ts("2026-07-02 16:30"), loader=loader_of(more), root=root, say=None).run(["promote"])
    Cycle(cfg, now=ts("2026-07-02 21:30"), loader=loader_of(more), root=root, say=None).run(["promote"])
    assert any(r.get("event") == "stale_lock_taken" for r in ChainLog(root / "cycles" / "audit.jsonl").read())


def test_the_cycle_is_reproducible(tmp_path):
    days = sessions(36)
    bars = {"NIFTY": market(days, phi=0.5, seed=11), "BANKNIFTY": market(days, phi=0.5, seed=12, start=55000.0)}
    cfg = cfg_for(tmp_path, candidates=["baseline"])
    outs = []
    for k in ("a", "b"):
        st = Cycle(cfg, now=ts(f"{days[-1]} 16:30"), loader=loader_of(bars), journal_path=tmp_path / "n.db",
                   root=tmp_path / k, say=None).run(["ingest", "dataset", "train", "validate"])
        art = json.loads((tmp_path / k / "runs" / str(days[-1]) / "artifact_baseline.json").read_text())
        v = json.loads((tmp_path / k / "runs" / str(days[-1]) / "validation.json").read_text())["baseline"]["metrics"]
        outs.append((st["stages"]["dataset"]["output"]["fingerprint"], st["stages"]["train"]["output"]["layout_hash"],
                     art["sha256"], v["ci"]["expectancy_bps"], v["trading"]["net_bps_total"]))
    assert outs[0] == outs[1]


def test_paper_trades_are_ingested_once_and_attributed(tmp_path):
    from quantdesk.journal.journal import Journal
    j = Journal(tmp_path / "j.db")
    j._exec("INSERT INTO trades (id, strategy, symbol, opened_at, closed_at, pnl, fees, r_multiple, meta, status) VALUES "
            "(?,?,?,?,?,?,?,?,?,?)", ("T1", "orb", "NIFTY", "2026-07-01 10:00:00+05:30", "2026-07-01 10:40:00+05:30", 350.0, 60.0,
                                      0.5, json.dumps({"autolearn": {"model_id": "m-1", "decision_id": "d1"}}), "closed"))
    j._exec("INSERT INTO trades (id, strategy, symbol, opened_at, closed_at, pnl, status) VALUES (?,?,?,?,?,?,?)",
            ("T2", "orb", "NIFTY", "2026-07-01 11:00:00+05:30", "2026-07-01 10:00:00+05:30", 10.0, "closed"))   # closes before opening
    j.commit()
    cfg = cfg_for(tmp_path)
    c = Cycle(cfg, now=ts("2026-07-01 16:30"), loader=loader_of({}), journal_path=tmp_path / "j.db", root=tmp_path / "al", say=None)
    assert c._ingest_paper_trades() == (1, 1)
    assert c._ingest_paper_trades() == (0, 1)                   # never twice
    rows = ChainLog(tmp_path / "al" / "paper_trades.jsonl").read()
    assert rows[0]["model_id"] == "m-1" and rows[0]["decision_id"] == "d1"


# ---- the live desk: halts, the champion's gate, Ollama stays explanatory -------------------------------------------
def _engine(cfg, tmp_path, days):
    from quantdesk.intraday.engine import IntradayEngine
    from quantdesk.intraday.feeds import ReplayFeed
    from quantdesk.intraday.sim import IntradayBroker
    from quantdesk.intraday.synthetic import simulate_sessions
    from quantdesk.journal.journal import Journal
    bars, _ = simulate_sessions(days, seed=11)
    return IntradayEngine(cfg, ReplayFeed(bars, days[-1]), "model", Journal(), IntradayBroker(cfg, starting_cash=500000), say=None)


def test_kill_switch_stale_feed_exposure_and_journal_halts(cfg, tmp_path):
    from quantdesk.core.calendar import TradingCalendar
    from quantdesk.intraday.analyst import MarketView
    days = [d.date() for d in TradingCalendar(cfg.holidays()).trading_days("2026-09-21", "2026-09-28")]
    eng = _engine(cfg, tmp_path, days)
    eng.start_session(days[-1])
    view = MarketView("NIFTY", None, 0, "neutral", 0, 0, "", "", None, None, [], [], {}, "")
    now = ts(f"{days[-1]} 11:00")
    eng.last_ts["NIFTY"] = now - pd.Timedelta(minutes=1)
    assert not str(eng._blocked("NIFTY", view, now) or "").startswith("halted")
    eng.last_ts["NIFTY"] = now - pd.Timedelta(minutes=10)       # the feed stopped 10 minutes ago
    assert "feed stale" in eng._blocked("NIFTY", view, now)
    eng.last_ts["NIFTY"] = now - pd.Timedelta(minutes=1)
    eng.kill_file.parent.mkdir(parents=True, exist_ok=True)
    eng.kill_file.write_text("stop")
    eng._kill_switch(now)
    assert eng.killed and "kill switch" in eng._blocked("NIFTY", view, now)
    assert not eng.journal.events(level="CRITICAL").empty
    eng.kill_file.unlink()
    eng._kill_switch(now)
    assert not eng.killed
    eng.journal.integrity = lambda: "row 7 missing from index"   # a journal that fails SQLite's check
    eng._check_journal(days[-1])
    assert "journal integrity" in eng._blocked("NIFTY", view, now)
    # the exposure cap and the session-close window in the risk gate
    from types import SimpleNamespace
    eng.risk.reset(days[-1], 20000)
    open_ = [SimpleNamespace(symbol="BANKNIFTY", entry_cost=12000.0)]
    eng.risk.max_open = 5
    assert any("exposure cap" in w for w in eng.risk.gate(now, 20000, open_, "NIFTY"))
    assert any("outside entry window" in w for w in eng.risk.gate(ts(f"{days[-1]} 15:00"), 20000, [], "NIFTY"))
    eng.risk.start_equity = 20000
    assert any("daily loss" in w for w in eng.risk.gate(now, 17000, [], "NIFTY"))


def test_abnormal_spread_vetoes_entries(cfg):
    from quantdesk.intraday.analyst import Analyst
    from quantdesk.intraday.features import session_state
    idx = pd.date_range("2026-10-05 09:15", "2026-10-05 11:00", freq="1min", tz=IST)
    c = 25600 + np.arange(len(idx)) * 0.5
    s = session_state(pd.DataFrame({"open": c, "high": c + 2, "low": c - 2, "close": c, "volume": 0.0}, index=idx),
                      idx[-1] + pd.Timedelta(minutes=1))
    v = Analyst(cfg).assess("NIFTY", s, {"atm_spread_pct": 0.20, "source": "kotak"})
    assert any("spread" in x for x in v.vetoes)


def test_champion_gates_entries_and_records_shadow_decisions(tmp_path):
    days = sessions(60)
    bars = {"NIFTY": market(days, phi=0.5, seed=7), "BANKNIFTY": market(days, phi=0.5, seed=8, start=55000.0)}
    cfg = cfg_for(tmp_path)
    root = tmp_path / "al"
    Cycle(cfg, now=ts(f"{days[52]} 16:30"), loader=loader_of({k: v[v.index.date <= days[52]] for k, v in bars.items()}),
          journal_path=tmp_path / "n.db", root=root, say=None).run()
    reg = Registry(root)
    mid = reg.challengers()[0]
    reg.promote(mid, "test", {"all": True})
    ll = _shadow_days(cfg, root, bars["NIFTY"], [days[53]])
    assert ll.active and ll.last["NIFTY"]["model_id"] == mid
    dec = Ledger(root).decisions()
    assert len(dec) >= 70 and all(r["source"] == "live" for r in dec)
    assert all(pd.Timestamp(r["recorded_at"]) < pd.Timestamp(r["label_end"]) for r in dec)
    from types import SimpleNamespace
    plans = [SimpleNamespace(direction=1, notes={}), SimpleNamespace(direction=-1, notes={})]
    ll.last["NIFTY"] = {**ll.last["NIFTY"], "signal": 1, "abstained": False}
    keep, why = ll.entry_filter("NIFTY", plans)
    assert why is None and [p.direction for p in keep] == [1] and keep[0].notes["autolearn"]["model_id"] == mid
    ll.last["NIFTY"] = {**ll.last["NIFTY"], "signal": 0, "abstained": True, "reason": "|p − ½| 0.010 < τ 0.030"}
    keep, why = ll.entry_filter("NIFTY", plans)
    assert keep == [] and "abstains" in why
    (root / "drift.json").write_text(json.dumps({"model_id": mid, "state": "alarm", "reasons": ["feature drift PSI 0.40"]}))
    ll2 = _shadow_days(cfg, root, bars["NIFTY"], [days[54]])
    assert ll2.last["NIFTY"]["signal"] == 0 and "drift alarm" in ll2.last["NIFTY"]["reason"]


def test_ollama_reads_never_move_the_tone(cfg):
    from quantdesk.intraday.news import NewsDesk, NewsItem
    nd = NewsDesk(cfg, fetch=lambda *a, **k: [])
    now = ts("2026-10-05 10:00")
    x = NewsItem(id="h1", ts=now, source="test", title="Markets rally", link="", summary="", sentiment=0.2, impact="medium",
                 about={"NIFTY": 3.0})
    x.nlp = {"llm": {"readers": {"ollama": {"NIFTY": -1.0, "confidence": 1.0, "at": str(now)}}}}
    assert nd.item_tone(x, "NIFTY", now) == pytest.approx(0.2)                 # explanatory only
    x.nlp["llm"]["readers"]["claude"] = {"NIFTY": -1.0, "confidence": 1.0, "at": str(now)}
    assert nd.item_tone(x, "NIFTY", now) < 0.2                                 # a weighed reader still counts
    import ast
    import pathlib
    src = pathlib.Path(__file__).resolve().parents[1] / "quantdesk" / "autolearn"
    for f in src.glob("*.py"):                                                 # the learning loop never imports an LLM
        tree = ast.parse(f.read_text())
        mods = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module} | \
               {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        assert not any("llm" in (m or "") for m in mods), f.name


def test_gates_fail_closed_on_missing_numbers():
    m = {"days": 30, "classification": {"rows": 1000, "ece": float("nan"), "brier_skill": 0.01},
         "trading": {"trades": 100, "expectancy_bps": 2.0, "profit_factor": 1.2, "max_drawdown_bps": -100.0, "trades_per_day": 3.0},
         "ci": {"expectancy_bps": {"p_positive": None}}}
    ok, reasons, checks = gates(m, True)
    assert not ok and "failed calibration_ece" in reasons and "failed cost_ci_p_positive" in reasons
    assert "failed risk_drawdown" in reasons                                   # its recovery time is missing: fails
    assert not gates({}, True)[0]                                              # nothing measured: nothing passes
    assert set(STAGES) == {"ingest", "dataset", "train", "validate", "register", "paper", "promote"}


def test_cli_cycle_status_verify_recover_rollback(tmp_path, capsys, monkeypatch):
    from quantdesk.autolearn import cli as A
    from quantdesk.cli import main
    days = sessions(40)
    bars = {"NIFTY": market(days, seed=21), "BANKNIFTY": market(days, seed=22, start=55000.0)}
    monkeypatch.setattr(A, "default_loader", lambda cfg, offline=False: loader_of(bars))
    rt = tmp_path / "runtime"
    over = tmp_path / "o.yaml"
    over.write_text(f"runtime: {{dir: {rt}}}\nautolearn: {{bootstrap: {{samples: 100}}, candidates: [baseline]}}\n")
    main(["--config", str(over), "autolearn", "cycle", "--offline"])
    out = capsys.readouterr().out
    assert "cycle" in out and ("done" in out or "partial" in out)
    main(["--config", str(over), "autolearn", "status"])
    s = capsys.readouterr().out
    assert "champion        none" in s and "locked test" in s and "integrity OK" in s and "need an approved plan model" in s
    main(["--config", str(over), "autolearn", "verify"])
    assert "intact" in capsys.readouterr().out
    led = next((rt / "intraday" / "autolearn" / "registry").glob("events.jsonl"), None)
    p = rt / "intraday" / "autolearn" / "ledger" / "predictions-2026-07.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text('{"half a line')                                   # a torn write
    with pytest.raises(SystemExit):
        main(["--config", str(over), "autolearn", "verify"])
    main(["--config", str(over), "autolearn", "recover"])
    assert "1 torn ledger line" in capsys.readouterr().out
    main(["--config", str(over), "autolearn", "verify"])
    assert "intact" in capsys.readouterr().out
    with pytest.raises(SystemExit, match="rollback refused"):
        main(["--config", str(over), "autolearn", "rollback", "--reason", "drill"])
    assert led is None or led.exists()


def test_engine_replay_with_the_learner_records_and_reports(cfg, tmp_path):
    from quantdesk.core.calendar import TradingCalendar
    from quantdesk.intraday.engine import run_replay
    days = [d.date() for d in TradingCalendar(cfg.holidays()).trading_days("2026-09-21", "2026-09-28")]
    eng = _engine(cfg, tmp_path, days)
    root = tmp_path / "al"
    s = build_samples(to_5m(market(sessions(30), phi=0.5, seed=31)), "NIFTY").dropna(subset=["y"])
    reg = Registry(root)
    mid, _ = reg.register(Pipeline("baseline").fit(s, 6.0), {"code_fingerprint": "c", "feature_version": "f", "label_version": "l",
                                                             "data_fingerprint": "d", "training_window": {}, "validation": {"passed": True},
                                                             "registered_at": "2026-09-01 16:30:00+05:30"})
    eng.learner = LiveLearner(cfg, root=root, source="replay")
    run_replay(eng)
    hb = eng.journal.get_state("intraday_live")
    assert hb["autolearn"]["challengers"] == [mid] and hb["autolearn"]["champion"] is None
    assert hb["halts"] == {"kill_switch": False, "journal": None, "daily_loss": hb["halts"]["daily_loss"], "safe_mode": None,
                           "reconcile": False}
    assert hb["health"]["reconcile"]["ok"] is True and hb["health"]["consecutive_failures"] == 0
    dec = Ledger(root).decisions()
    assert dec and {r["source"] for r in dec} == {"replay"} and all(m["role"] == "challenger" for r in dec for m in r["models"])
    assert Ledger(root).frame(source="live").empty                 # replays never count as paper evidence
    assert len(Ledger(root).outcomes()) > 0                         # resolved at the session's end


# ---- the trading engine: atomic state, reconciliation, safe mode, graceful stop ------------------------------------
def test_broker_state_is_written_atomically(cfg, tmp_path, monkeypatch):
    from quantdesk.core.types import Instrument, Order
    from quantdesk.intraday.sim import IntradayBroker
    path = tmp_path / "broker.json"
    b = IntradayBroker(cfg, starting_cash=20000, state_path=path)
    inst = Instrument.option("NIFTY", pd.Timestamp("2026-10-06").date(), 25000.0, "CE", 65)
    b.execute(Order(inst, 65, "T1", "open"), 100.0, ts("2026-10-05 10:00"))
    good = path.read_text()
    import quantdesk.execution.broker as BR

    def boom(*a, **k):
        raise OSError("disk full")
    monkeypatch.setattr(BR.json, "dump", boom)
    with pytest.raises(OSError):
        b.execute(Order(inst, -65, "T1", "close"), 110.0, ts("2026-10-05 10:30"))
    assert path.read_text() == good                                   # the last good state survives a failed write
    assert IntradayBroker(cfg, state_path=path).positions()[inst.symbol]["qty"] == 65


def test_reconciliation_halts_on_orphan_positions_and_safe_mode_flattens(cfg, tmp_path):
    from quantdesk.core.calendar import TradingCalendar
    from quantdesk.core.types import Instrument, Order
    from quantdesk.intraday.analyst import MarketView
    from quantdesk.intraday.engine import run_step
    days = [d.date() for d in TradingCalendar(cfg.holidays()).trading_days("2026-09-21", "2026-09-28")]
    eng = _engine(cfg, tmp_path, days)
    inst = Instrument.option("NIFTY", days[-1], 25000.0, "CE", 65)
    eng.broker.execute(Order(inst, 65, "X", "open"), 100.0, ts(f"{days[-1]} 09:00"))   # a fill the journal never saw
    eng.start_session(days[-1])
    view = MarketView("NIFTY", None, 0, "neutral", 0, 0, "", "", None, None, [], [], {}, "")
    assert eng.health["reconcile"]["ok"] is False and "broker +65" in eng.health["reconcile"]["detail"]
    assert "broker and journal disagree" in eng._blocked("NIFTY", view, ts(f"{days[-1]} 11:00"))
    # consistent books reconcile
    eng2 = _engine(cfg, tmp_path, days)
    eng2.start_session(days[-1])
    assert eng2.health["reconcile"] == {"ok": True, "positions": 0}
    # three failed steps in a row: safe mode, entries halted
    calls = {"n": 0}

    def bad_step():
        calls["n"] += 1
        raise RuntimeError("exits broken")
    eng2.step = bad_step
    for _ in range(3):
        assert run_step(eng2) is False
    assert eng2.health["consecutive_failures"] == 3 and eng2.health["safe_mode"]
    assert "safe mode" in eng2._blocked("NIFTY", view, ts(f"{days[-1]} 11:00"))
    assert not eng2.journal.events(level="CRITICAL").empty
    eng2.step = lambda: True                                          # a good step resets the run, safe mode stays
    assert run_step(eng2) is True and eng2.health["consecutive_failures"] == 0 and eng2.health["safe_mode"]
