"""The progress report (ops/progress.py): the evidence level comes from the principles ledger, snapshots are kept one
per day, and every measure is judged in the direction that is better for it."""
import datetime as dt
import json

from quantdesk.ops import progress as P


def test_level_is_the_highest_rung_any_principle_reached(tmp_path):
    f = tmp_path / "p.json"
    f.write_text(json.dumps({"principles": [{"status": "found"}, {"status": "rejected"}, {"status": "replicated"}]}))
    p = P.principles(f)
    assert p["level"] == 2 and p["tested"] == 3 and p["replicated_plus"] == 1 and p["counts"]["rejected"] == 1
    real = P.principles()                                   # the repo's own ledger parses, negative results included
    assert 1 <= real["level"] <= 4 and real["counts"]["rejected"] >= 1


def test_snapshots_are_kept_one_per_day(tmp_path):
    path = tmp_path / "h.jsonl"
    P.record({"date": "2026-10-05", "equity": 1.0}, path)
    P.record({"date": "2026-10-05", "equity": 2.0}, path)        # a re-run replaces the day
    hist = P.record({"date": "2026-10-04", "equity": 0.5}, path)
    assert [h["date"] for h in hist] == ["2026-10-04", "2026-10-05"] and hist[-1]["equity"] == 2.0


def test_each_measure_is_judged_in_its_better_direction():
    prev = {"equity": 500000.0, "drawdown": 0.02, "level": 1, "sleeves_retired": 0, "tape_sessions": 3}
    curr = {"equity": 510000.0, "drawdown": 0.05, "level": 1, "sleeves_retired": 1, "tape_sessions": 9}
    v = {label: verdict for label, _, _, verdict in P.compare(curr, prev)}
    assert v["paper account equity, ₹"] == "improved" and v["paper drawdown from peak"] == "worse"
    assert v["evidence level (0-4)"] == "same" and v["sleeves retired"] == "worse"
    assert v["full sessions of real chain tape"] == "improved"


def test_report_compares_with_last_week_and_the_start(cfg):
    days = [dt.date(2026, 10, 5) + dt.timedelta(days=7 * k) for k in range(3)]
    hist = [dict(P.snapshot(cfg, d), equity=500000.0 + 1000 * k) for k, d in enumerate(days)]
    md = P.render(hist)
    assert f"Evidence level {P.principles()['level']}/4" in md and "Since last week (2026-10-12 → 2026-10-19)" in md
    assert "Since the first snapshot (2026-10-05 → 2026-10-19)" in md and "⬆ improved" in md
    assert "first snapshot" in P.render(hist[:1])


def test_forecast_skill_is_measured_on_resolved_live_predictions(cfg):
    """A model that is right more often than a coin shows positive skill; one that isn't shows none."""
    import pandas as pd
    from quantdesk.autolearn.cycle import root_of
    from quantdesk.autolearn.features import FEATURES
    from quantdesk.autolearn.ledger import Ledger
    assert P.forecast_skill(cfg)["forecast_skill"] is None                       # nothing recorded yet
    led = Ledger(root_of(cfg))
    t0 = pd.Timestamp("2026-10-05 10:00", tz="Asia/Kolkata")
    for k in range(40):
        ts = t0 + pd.Timedelta(minutes=5 * k)
        y = float(k % 2)
        good = 0.8 if y else 0.2                                                  # leans the right way every time
        did = led.record_decision({"ts": ts, "label_end": ts + pd.Timedelta(minutes=30), "symbol": "NIFTY",
                                   "features": {f: 0.0 for f in FEATURES}, "data_fingerprint": "x", "costs_assumed": 3.0,
                                   "models": [{"model_id": "good", "p": good, "signal": 1 if y else -1},
                                              {"model_id": "coin", "p": 0.5, "signal": 0}], "source": "backfill"},
                                  now=ts)
        led.record_outcome(did, ts, {"y": y, "fwd_ret": 0.001 if y else -0.001, "label_end": str(ts + pd.Timedelta(minutes=30)),
                                     "net_bps": {"good": 7.0, "coin": 0.0}}, now=ts + pd.Timedelta(minutes=31))
    f = P.forecast_skill(cfg)
    assert f["predictions_resolved"] == 80 and abs(f["forecast_skill"] - (1 - 0.04 / 0.25)) < 1e-9
    assert f["signal_hit_rate"] == 1.0 and f["signal_net_bps"] == 7.0


def test_v4_is_the_only_sleeve_ledger_in_the_totals(cfg):
    """v4's trades pair one for one with v1–v3's: the progress totals count the decision ledger once, not both."""
    root = cfg.runtime_dir / "intraday" / "sleeves"
    root.mkdir(parents=True)

    def trade(sleeve, pnl):
        tid = f"{sleeve}-NIFTY-2026-10-20"
        return [{"event": "open", "id": tid, "sleeve": sleeve, "underlying": "NIFTY", "expiry": "2026-10-20", "day": "2026-10-19",
                 "lot": 65, "legs": [], "cost_gap_rs": 0.0, "max_loss_rs": 6000.0},
                {"event": "settle", "id": tid, "pnl_rs": pnl, "settle": 22600.0}]
    for name, sleeve, pnl in (("expiry_seller_v1", "A", 500.0), ("expiry_seller_v4", "F", 700.0)):
        (root / f"{name}.jsonl").write_text("\n".join(json.dumps(e) for e in trade(sleeve, pnl)) + "\n")
    snap = P.snapshot(cfg, dt.date(2026, 10, 21))
    assert snap["sleeve_trades"] == 1 and snap["sleeve_pnl"] == 700.0


def test_comparison_ledgers_stay_visible_and_a_change_of_reading_is_a_reset_not_a_worsening(cfg):
    """K3: v1–v3 are shown as comparison (outside the KPIs); the snapshot says which reading its sleeve KPIs follow, and
    when that differs from the earlier snapshot's the sleeve KPIs are 'reset', never 'worse'."""
    root = cfg.runtime_dir / "intraday" / "sleeves"
    root.mkdir(parents=True)

    def trade(sleeve, pnl):
        tid = f"{sleeve}-NIFTY-2026-10-20"
        return [{"event": "open", "id": tid, "sleeve": sleeve, "underlying": "NIFTY", "expiry": "2026-10-20", "day": "2026-10-19",
                 "lot": 65, "legs": [], "cost_gap_rs": 0.0, "max_loss_rs": 6000.0},
                {"event": "settle", "id": tid, "pnl_rs": pnl, "settle": 22600.0}]
    for name, sleeve, pnl in (("expiry_seller_v1", "A", 500.0), ("expiry_seller_v4", "F", 700.0)):
        (root / f"{name}.jsonl").write_text("\n".join(json.dumps(e) for e in trade(sleeve, pnl)) + "\n")
    snap = P.snapshot(cfg, dt.date(2026, 10, 21))
    assert snap["sleeve_reading"] == "v4" and snap["sleeve_comparison_trades"] == 1 and snap["sleeve_comparison_pnl"] == 500.0
    assert "sleeve_comparison_trades" not in P.KPIS and "sleeve_comparison_pnl" not in P.KPIS
    old = {"date": "2026-10-12", "level": 1, "sleeve_trades": 40, "sleeve_pnl": 9000.0, "sleeves_retired": 0, "equity": 500000.0}
    cur = {**snap, "equity": 499000.0, "sleeve_trades": 1, "sleeve_pnl": 700.0, "sleeves_retired": 1}
    v = {lab: ver for lab, _, _, ver in P.compare(cur, old)}
    assert v["forward sleeve trades settled"] == "reset" and v["forward sleeve P&L, ₹/lot"] == "reset"
    assert v["sleeves retired"] == "reset" and v["paper account equity, ₹"] == "worse"        # other KPIs are unaffected
    same = {**old, "sleeve_reading": "v4"}
    assert {lab: ver for lab, _, _, ver in P.compare(cur, same)}["forward sleeve trades settled"] == "worse"
    md = P.render([old, cur])
    assert "↺ reset" in md and "Comparison ledgers (v1–v3" in md
