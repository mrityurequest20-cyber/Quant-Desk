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
