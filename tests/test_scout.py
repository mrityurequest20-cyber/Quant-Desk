"""The asymmetry scout (intraday/scout.py, scout_report.py): first-passage labels, point-in-time features, the seal, offline output."""
import datetime as dt
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from quantdesk.intraday import scout as C
from quantdesk.intraday import scout_report as R

IST = "Asia/Kolkata"


def day_frame(day, price=100.0, half=0.5, edits=None):
    """A flat session whose every minute spans 2 x half (so the 5-minute ATR is 1.0 and the 1.5 ATR stop is 1.5 points)."""
    idx = pd.date_range(f"{day} 09:15", periods=375, freq="1min", tz=IST)
    df = pd.DataFrame({"open": price, "high": price + half, "low": price - half, "close": price, "volume": 100.0}, index=idx)
    for minute, cols in (edits or {}).items():
        for k, v in cols.items():
            df.iloc[minute, df.columns.get_loc(k)] = v
    return df


PRIOR = day_frame("2026-01-01")


def cand(rows, m, d):
    return next(r for r in rows if r["mins"] == m and r["direction"] == d)


def test_a_target_before_the_stop_is_a_first_passage_and_each_direction_is_signed_its_own_way():
    # decision at minute 15 enters at the open of minute 15 (100.0): long stop 98.5, targets 103 / 104.5 / 106 / 109; short stop 101.5
    rows = C.session_candidates(day_frame("2026-01-02", edits={50: {"high": 104.6}}), PRIOR, "X")
    long = cand(rows, 15, 1)
    assert [long[f"reach_{k}"] for k in C.KS] == [True, True, False, False]       # 104.6 is past 3R (104.5), short of 4R (106)
    assert long["t_reach_3"] == 35 and long["mfe_r"] == pytest.approx(3.0667, abs=1e-3) and long["r_end"] == pytest.approx(0.0)
    short = cand(rows, 15, -1)
    assert not any(short[f"reach_{k}"] for k in C.KS) and short["r_end"] == -1.0   # the same spike is the short's stop (101.5)


def test_the_stop_wins_when_one_minute_touches_both_and_a_stop_first_ends_the_trade():
    both = C.session_candidates(day_frame("2026-01-02", edits={50: {"high": 104.6, "low": 98.0}}), PRIOR, "X")
    assert not cand(both, 15, 1)["reach_3"] and cand(both, 15, 1)["r_end"] == -1.0
    stop_first = C.session_candidates(day_frame("2026-01-02", edits={40: {"low": 98.0}, 50: {"high": 105.0}}), PRIOR, "X")
    assert not any(cand(stop_first, 15, 1)[f"reach_{k}"] for k in C.KS)


def test_the_entry_is_the_next_minute_and_only_later_minutes_count():
    # a spike in the DECISION minute's own bar (minute 14, known at the decision) is not part of the label; one in the entry bar (15) is
    known = C.session_candidates(day_frame("2026-01-02", edits={14: {"high": 110.0}}), PRIOR, "X")
    assert not cand(known, 15, 1)["reach_6"]
    entry_bar = C.session_candidates(day_frame("2026-01-02", edits={15: {"high": 110.0}}), PRIOR, "X")
    assert cand(entry_bar, 15, 1)["reach_6"]


def test_features_use_nothing_after_the_decision_minute():
    base = day_frame("2026-01-02")
    changed = day_frame("2026-01-02", edits={m: {"high": 130.0, "low": 99.5, "close": 120.0, "open": 99.5} for m in range(101, 300)})
    a, b = C.session_candidates(base, PRIOR, "X"), C.session_candidates(changed, PRIOR, "X")
    for ra, rb in zip(a, b):
        if ra["mins"] <= 100:
            for f in C.FEATURES:
                assert (ra[f] == rb[f]) or (pd.isna(ra[f]) and pd.isna(rb[f])), (ra["mins"], f)
    assert any(ra["reach_6"] != rb["reach_6"] for ra, rb in zip(a, b))                 # the labels did see the change


def test_room_is_measured_to_the_nearest_obstacle_ahead_in_units_of_risk():
    # price sits at 100; the prior day's high is 100.5, so the first obstacle ahead is 0.5 points = 1/3 R away
    rows = C.session_candidates(day_frame("2026-01-02"), PRIOR, "X")
    r = cand(rows, 15, 1)
    assert r["room_pd_r"] == pytest.approx(0.5 / 1.5, abs=1e-6) and r["room_next_r"] == pytest.approx(0.5 / 1.5, abs=1e-6)
    assert r["open_air"] == 0.0 and r["n_obst_3r"] >= 1


def test_a_session_without_a_prior_or_with_too_few_minutes_makes_no_candidates():
    assert C.session_candidates(day_frame("2026-01-02"), None, "X") == []
    assert C.session_candidates(day_frame("2026-01-02").iloc[:100], PRIOR, "X") == []


def test_sessions_from_the_seal_date_are_refused_not_skipped():
    bars = {"X": pd.concat([day_frame("2022-12-29"), day_frame("2022-12-30"), day_frame("2023-01-02")])}
    with pytest.raises(C.Refused, match="sealed"):
        C.build(bars, ["X"], "index")
    df = C.build(bars, ["X"], "index", last="2022-12-30", say=lambda *_: None)
    assert df["day"].max() == dt.date(2022, 12, 30)
    assert C.build(bars, ["X"], "stock", seal=False, say=lambda *_: None)["day"].max() == dt.date(2023, 1, 2)


def test_the_output_must_be_new_and_outside_every_git_tree(tmp_path):
    with pytest.raises(C.Refused, match="git tree"):
        C._check_out(Path(C.__file__).resolve().parent / "scout_out")
    used = tmp_path / "used"
    used.mkdir()
    (used / "x").write_text("1")
    with pytest.raises(C.Refused, match="new or empty"):
        C._check_out(used)
    C._check_out(tmp_path / "fresh")


def test_the_cli_needs_exactly_one_source(tmp_path):
    for extra in ([], ["--dataset", str(tmp_path), "--stocks", str(tmp_path)]):
        p = subprocess.run([sys.executable, "-m", "quantdesk", "intraday", "scout", "--out", str(tmp_path / "o"), *extra],
                           capture_output=True, text=True, cwd=Path(C.__file__).resolve().parents[2])
        assert p.returncode != 0 and "exactly one of --dataset and --stocks" in p.stderr + p.stdout


def test_a_rate_carries_a_session_clustered_error():
    df = pd.DataFrame({"symbol": "X", "day": [dt.date(2020, 1, 1)] * 4 + [dt.date(2020, 1, 2)] * 4, "y": [1, 1, 1, 1, 0, 0, 0, 0]})
    r = R.rate(df, "y")
    assert r["rate"] == 0.5 and r["sessions"] == 2
    assert r["se"] == pytest.approx(np.sqrt(8) / 8)                                       # sqrt(sum of cluster residual sums squared) / n
    assert r["se"] > np.sqrt(0.25 / 8)                                                    # wider than 8 independent rows would give
    assert R.rate(df.iloc[:0], "y")["n"] == 0


@pytest.fixture(scope="module")
def synthetic():
    """About 150 synthetic sessions straddling the train/valid split (end of 2020), both indices, with a VIX line."""
    from quantdesk.intraday.synthetic import simulate_sessions
    days = [d.date() for d in pd.bdate_range("2020-10-01", "2021-04-30")]
    bars, _ = simulate_sessions(days, seed=5)
    df = C.build({s: bars[s] for s in ("NIFTY", "BANKNIFTY")}, ["NIFTY", "BANKNIFTY"], "index", vix=bars["INDIAVIX"]["close"], say=lambda *_: None)
    return days, df


def test_the_model_check_is_judged_on_the_later_years_only(synthetic):
    pytest.importorskip("sklearn")                       # scikit-learn is in requirements-ml.txt, not the base install
    _, df = synthetic
    m = R.model_check(df, 3)
    assert m["n_valid"] == int((df["day"] > R.TRAIN_TO).sum()) and 0.3 < m["auc_valid"] < 0.7
    assert {"top5", "top10", "top25"} <= set(m) and len(m["importance"]) == 8


def test_the_report_names_a_missing_scikit_learn_instead_of_failing_or_skipping_silently(tmp_path, synthetic, monkeypatch):
    _, df = synthetic
    C._write(tmp_path / "run", df, {}, {"path": "synthetic"})
    monkeypatch.setitem(sys.modules, "sklearn", None)        # an import now raises ImportError, as on the base CI install
    text = R.write_report(tmp_path / "run", say=lambda *_: None).read_text()
    assert "skipped: scikit-learn is not installed" in text and "## 1. Base rates" in text and "**reach_3**" not in text


def test_an_end_to_end_run_writes_candidates_a_manifest_and_a_report_and_places_nothing(tmp_path, synthetic):
    days, df = synthetic
    man = C._write(tmp_path / "run", df, {"stop_atr": C.STOP_ATR}, {"path": "synthetic"})
    assert man["evidence"] == "external_unverified" and "never evidence" in man["not_for"] and man["sealed_from"] == "2023-01-01"
    lab = pd.DataFrame({"day": [days[60].isoformat()], "ts": [f"{days[60]} 10:00:00+05:30"], "symbol": ["NIFTY"], "direction": [1],
                        "setup": ["orb"], "idea_first": [True]})
    lab.to_parquet(tmp_path / "lab.parquet")
    p = R.write_report(tmp_path / "run", tmp_path / "lab.parquet", say=lambda *_: None)
    text = p.read_text()
    assert "Not for:" in text and "## 1. Base rates" in text and "## 3." in text and "## 5." in text
    assert (tmp_path / "run" / "feature_bins_reach_3.csv").exists()
    br = R.base_rates(df)
    assert set(br["k"]) == set(C.KS) and (br["break_even"] > br["random_walk"]).all()
    dc = json.loads((tmp_path / "run" / "desk_comparison.json").read_text())
    assert dc["candidates"] > 0 and "by_k" in dc


# ---- the seal is REFUSED, not dropped, wherever the sealed sessions could come in ----------------------------------------------------
def _loaded_nothing(*a, **k):
    raise AssertionError("the dataset was read although the window was refused")


@pytest.mark.parametrize("last", [None, "", "2023-01-01", "2025-12-31", "2022-12-31x", "garbage", "2022-13-45"])
def test_an_index_run_without_a_last_day_before_the_seal_is_refused_before_anything_is_read(tmp_path, monkeypatch, last):
    monkeypatch.setattr(C, "_load_bars", _loaded_nothing)
    with pytest.raises(C.Refused, match="sealed"):
        C.run_dataset(tmp_path / "ds", tmp_path / "out", last=last)
    assert not (tmp_path / "out").exists()


def test_the_command_refuses_an_index_run_with_no_last_day_and_says_why(tmp_path):
    r = subprocess.run([sys.executable, "-m", "quantdesk", "intraday", "scout", "--dataset", str(tmp_path / "ds"), "--out", str(tmp_path / "o"), "--journal", "none"],
                       capture_output=True, text=True, cwd=Path(C.__file__).resolve().parents[2])
    assert r.returncode != 0 and "sealed" in r.stderr + r.stdout and "--to" in r.stderr + r.stdout


def test_a_last_day_before_the_seal_runs_and_no_sealed_session_is_computed(tmp_path, monkeypatch):
    from quantdesk.intraday.synthetic import simulate_sessions
    days = [d.date() for d in pd.bdate_range("2022-11-01", "2023-02-28")]
    bars, _ = simulate_sessions(days, seed=3)
    monkeypatch.setattr(C, "_load_bars", lambda *a, **k: {s: bars[s] for s in bars})
    monkeypatch.setattr(C, "_digest", lambda *a, **k: "x")
    man = C.run_dataset(tmp_path / "ds", tmp_path / "out", ["NIFTY", "BANKNIFTY"], last="2022-12-31", say=lambda *_: None)
    assert man["last"] <= "2022-12-31" and man["rows"] > 0


def test_assert_open_refuses_a_table_with_sealed_index_days_but_not_a_stock_table():
    sealed = pd.DataFrame({"day": [dt.date(2022, 12, 30), dt.date(2023, 1, 2)], "kind": ["index", "index"]})
    with pytest.raises(C.Refused, match="sealed"):
        C.assert_open(sealed, "a grid")
    C.assert_open(pd.DataFrame({"day": [dt.date(2025, 6, 2)], "kind": ["stock"]}), "stocks")     # stock sessions are not the sealed index data
    C.assert_open(sealed.iloc[:1], "an open grid")


def test_the_read_out_refuses_a_sealed_grid_file_and_a_folder_inside_a_git_tree(tmp_path):
    out = tmp_path / "run"
    out.mkdir()
    pd.DataFrame({"symbol": ["NIFTY"], "kind": ["index"], "day": [dt.date(2023, 2, 1)], "reach_3": [True], "reach_4": [False]}).to_parquet(out / "scout_candidates.parquet")
    (out / "manifest.json").write_text("{}")
    with pytest.raises(C.Refused, match="sealed"):
        R.write_report(out)
    inside = tmp_path / "repo" / "run"
    inside.mkdir(parents=True)
    (tmp_path / "repo" / ".git").mkdir()
    with pytest.raises(C.Refused, match="git tree"):
        R.write_report(inside)


def test_a_session_without_its_opening_minute_is_left_out_not_filled_from_a_later_close():
    full = day_frame("2026-01-02")
    assert C._grid(full) is not None
    assert C._grid(full.iloc[1:]) is None                       # a back-fill would let a later close stand in for the first minute


def test_standard_errors_are_clustered_by_day_so_two_indices_of_one_day_are_one_market():
    days = pd.bdate_range("2019-01-01", periods=50)
    df = pd.DataFrame({"symbol": ["NIFTY"] * 50 + ["BANKNIFTY"] * 50, "day": list(days.date) * 2, "kind": "index",
                       "reach_3": [bool(i % 3 == 0) for i in range(50)] * 2})
    r = R.rate(df, "reach_3")
    assert r["sessions"] == 50 and r["n"] == 100                # 50 clusters (days), not 100 (symbol and day)
