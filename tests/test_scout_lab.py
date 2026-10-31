"""The scout's strategy library and rule miner (intraday/scout_lab.py, scout_discover.py, scout.outcomes)."""
import datetime as dt
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from quantdesk.intraday import scout as C
from quantdesk.intraday import scout_discover as D
from quantdesk.intraday import scout_lab as L

IST = "Asia/Kolkata"


def flat(price=100.0, half=0.5):
    n = C.N_MIN
    return {"open": np.full(n, price), "high": np.full(n, price + half), "low": np.full(n, price - half), "close": np.full(n, price), "volume": np.full(n, 100.0)}


def set_bar(a, t, o=None, h=None, l=None, c=None):
    for k, v in (("open", o), ("high", h), ("low", l), ("close", c)):
        if v is not None:
            a[k][t] = v


def test_every_exit_policy_on_a_spike_that_gives_it_all_back():
    a = flat()
    set_bar(a, 30, h=104.6)                                  # 3.07R spike (entry 100, R 1.5), then the next minute is back at 100
    r = C.outcomes(a, 15, 100.0, 1.5)
    assert r["r_fix3"] == 3.0 and r["r_fix2"] == 2.0 and r["r_fix4"] == pytest.approx(0.0) and r["reach_3"] and not r["reach_4"]
    assert r["r_trail"] == pytest.approx(0.0)                # the trail sits 1R under the peak, but the next minute OPENS at 100: filled there, not at the level
    assert r["r_end"] == pytest.approx(0.0) and r["r_t45"] == pytest.approx(0.0)


def test_a_trailing_exit_keeps_a_run_that_a_fixed_target_would_cap():
    a = flat()
    for t in range(15, 36):                                  # a steady climb: +0.5 a minute for 20 minutes, to 110 (the last high is 110.6)
        base = 100 + 0.5 * (t - 15)
        set_bar(a, t, o=base, h=base + 0.6, l=base - 0.1, c=base + 0.5)
    for t in range(36, 360):                                 # then a slide, 0.5 a minute, to 105, where it stays
        o = max(105.0, 110 - 0.5 * (t - 36))
        set_bar(a, t, o=o, h=o + 0.1, l=o - 0.6, c=max(105.0, o - 0.5))
    r = C.outcomes(a, 15, 100.0, 1.5)
    assert r["r_fix2"] == 2.0 and r["r_fix6"] == 6.0         # the fixed targets bank 2R / 6R
    assert r["r_trail"] == pytest.approx((110.6 - 1.5 - 100.0) / 1.5, abs=0.01)    # out 1R under the 110.6 peak, not at the top, not at the bottom
    assert r["r_end"] == pytest.approx((105.0 - 100.0) / 1.5) and r["r_trail"] > r["r_end"]    # holding with no trail gave most of it back


def test_the_trail_only_follows_a_peak_that_was_known_before_the_minute():
    a = flat()
    set_bar(a, 20, o=104.0, h=105.0, l=103.0, c=104.0)       # a new high and a pullback in ONE minute: the trail must not use that minute's own high
    for t in range(21, 360):
        set_bar(a, t, o=104.0, h=104.0, l=104.0, c=104.0)    # then flat at 104, above the 103.5 trail the 105.0 peak sets from the next minute on
    r = C.outcomes(a, 15, 100.0, 1.5)
    assert r["r_trail"] == pytest.approx((104.0 - 100.0) / 1.5)    # not stopped out: a peak of this minute's own would put the trail at 103.5 over this low of 103.0


def test_the_forty_five_minute_exit_marks_at_minute_45_and_ignores_what_happens_after():
    a = flat()
    for t in range(15, 60):                                  # 45 minutes at 101
        set_bar(a, t, o=101.0, h=101.1, l=100.9, c=101.0)
    for t in range(60, 360):                                 # then 103 to the close
        set_bar(a, t, o=103.0, h=103.0, l=103.0, c=103.0)
    r = C.outcomes(a, 15, 100.0, 1.5)
    assert r["r_t45"] == pytest.approx(1.0 / 1.5) and r["r_end"] == pytest.approx(3.0 / 1.5)
    b = flat()                                               # a stop AFTER minute 45 does not touch the 45-minute exit, but ends the stop-only one
    for t in range(15, 60):
        set_bar(b, t, o=101.0, h=101.1, l=100.9, c=101.0)
    set_bar(b, 100, l=98.0)
    r2 = C.outcomes(b, 15, 100.0, 1.5)
    assert r2["r_t45"] == pytest.approx(1.0 / 1.5) and r2["r_end"] == -1.0


def test_the_stop_ends_every_policy_and_wins_a_tie():
    a = flat()
    set_bar(a, 30, h=104.6, l=98.0)                          # target and stop in one minute: the stop wins
    r = C.outcomes(a, 15, 100.0, 1.5)
    assert not r["reach_3"] and r["r_fix3"] == -1.0 and r["r_end"] == -1.0 and r["r_t45"] == -1.0
    assert r["r_trail"] == pytest.approx((100.5 - 1.5 - 100.0) / 1.5)    # the trail had already followed the 100.5 highs to 99.0: out there, not at -1R


def day_frame(day, edits=None):
    idx = pd.date_range(f"{day} 09:15", periods=375, freq="1min", tz=IST)
    df = pd.DataFrame({"open": 100.0, "high": 100.5, "low": 99.5, "close": 100.0, "volume": 100.0}, index=idx)
    for t, cols in (edits or {}).items():
        for k, v in cols.items():
            df.iloc[t, df.columns.get_loc(k)] = v
    return df


def rising(sign=1, start=15, end=60, step=0.25):
    e = {}
    for t in range(start, end):
        base = 100 + sign * step * (t - start + 1)
        e[t] = {"open": base - sign * step, "close": base, "high": max(base, base - sign * step) + 0.25, "low": min(base, base - sign * step) - 0.25}
    return e


PRIOR = day_frame("2026-01-01")


def test_a_strategy_fires_where_it_should_and_a_short_is_the_mirror_image():
    up = L.session_trades(day_frame("2026-01-02", rising(1)), PRIOR, "X", only=("orb15",))
    assert up and up[0]["strategy"] == "orb15" and up[0]["direction"] == 1
    assert up[0]["ts"].strftime("%H:%M") == "09:35"          # the fresh break closes the 09:30-09:34 bar; the entry is the next minute's open
    down = L.session_trades(day_frame("2026-01-02", rising(-1)), PRIOR, "X", only=("orb15",))
    assert down and down[0]["direction"] == -1 and down[0]["ts"] == up[0]["ts"]
    assert up[0]["risk_pts"] > 0


def test_a_signal_needs_a_stop_below_the_entry_and_is_rate_limited():
    trades = L.session_trades(day_frame("2026-01-02", rising(1)), PRIOR, "X")
    per = pd.DataFrame(trades).groupby(["strategy", "direction"]).size()
    assert per.max() <= L.MAX_PER_DAY and all(t["risk_pts"] > 0 for t in trades)
    ts = pd.DataFrame(trades).sort_values("ts").groupby(["strategy", "direction"])["ts"].apply(lambda s: s.diff().dropna().min())
    assert all(x >= pd.Timedelta(minutes=5 * L.COOLDOWN_BARS) for x in ts.dropna())


def test_nothing_the_library_reads_comes_from_after_the_signal():
    base = day_frame("2026-01-02", rising(1))
    changed = day_frame("2026-01-02", {**rising(1), **{t: {"high": 140.0, "low": 60.0, "close": 130.0, "open": 70.0} for t in range(121, 300)}})
    a, b = L.session_trades(base, PRIOR, "X"), L.session_trades(changed, PRIOR, "X")
    cutoff = pd.Timestamp("2026-01-02 09:15", tz=IST) + pd.Timedelta(minutes=120)
    ea = {(r["strategy"], r["direction"], r["ts"]): r for r in a if r["ts"] <= cutoff}
    eb = {(r["strategy"], r["direction"], r["ts"]): r for r in b if r["ts"] <= cutoff}
    assert ea and set(ea) == set(eb)
    for k, ra in ea.items():
        for f in C.FEATURES + ("risk_pts",):
            assert (ra[f] == eb[k][f]) or (pd.isna(ra[f]) and pd.isna(eb[k][f])), (k, f)


def test_sessions_from_the_seal_date_are_refused_by_the_library_too():
    bars = {"X": pd.concat([day_frame("2022-12-29"), day_frame("2022-12-30"), day_frame("2023-01-02")])}
    with pytest.raises(C.Refused, match="sealed"):
        L.build_trades(bars, ["X"], "index", say=lambda *_: None)
    assert L.build_trades({"X": pd.concat([day_frame("2022-12-29"), day_frame("2022-12-30", rising(1))])}, ["X"], "index", say=lambda *_: None)["day"].max() == dt.date(2022, 12, 30)


def test_the_cli_needs_exactly_one_source(tmp_path):
    p = subprocess.run([sys.executable, "-m", "quantdesk", "intraday", "scout-lab", "--out", str(tmp_path / "o")], capture_output=True, text=True,
                       cwd=Path(C.__file__).resolve().parents[2])
    assert p.returncode != 0 and "exactly one of --dataset and --stocks" in p.stderr + p.stdout


def trades_frame(seed=1, days=800, rows=3):
    rng = np.random.default_rng(seed)
    d = pd.bdate_range("2019-01-01", periods=days)
    recs = []
    for day in d:
        for strat, mu in (("good", 0.9), ("flat", -0.05)):
            for _ in range(rows):
                r = rng.normal(mu, 1.0)
                recs.append({"strategy": strat, "symbol": "X", "kind": "index", "day": day.date(), **{c: r for c in C.POLICY_COLUMNS.values()}})
    return pd.DataFrame(recs)


def test_the_leaderboard_sets_a_multiple_testing_bar_caps_r_and_flags_only_a_stable_edge():
    lb = D.leaderboard(trades_frame())
    assert set(lb["strategy"]) == {"good", "flat"} and lb["cells"].iloc[0] == 2 * len(C.POLICY_COLUMNS) and lb["z_needed"].iloc[0] > 2.5
    assert lb[lb["strategy"] == "good"]["passes"].all() and not lb[lb["strategy"] == "flat"]["passes"].any()
    capped = D.net(pd.Series([50.0, -1.0]))
    assert capped.tolist() == [D.CAP_R - C.COST_R, -1.0 - C.COST_R]


def test_the_shift_null_keeps_each_sessions_outcomes_but_breaks_the_link_to_the_rows():
    gid = np.repeat(np.arange(50), 6)
    y = np.arange(300, dtype=float)
    z = D._shift_within_sessions(y, gid, np.random.default_rng(3))
    for g in range(50):
        assert sorted(z[gid == g]) == sorted(y[gid == g])
    assert (z != y).mean() > 0.9


def test_the_miner_finds_a_planted_rule_and_beats_its_null_but_is_charged_for_every_trial():
    rng = np.random.default_rng(5)
    n = 6000
    days = pd.bdate_range("2019-01-01", periods=1500)
    df = pd.DataFrame({"day": [days[i % 1500].date() for i in range(n)], "symbol": "X", "kind": "index",
                       "f1": rng.uniform(0, 1, n), "f2": rng.normal(size=n), "f3": rng.normal(size=n)})
    df["r"] = np.where(df["f1"] > 0.6, 1.5, -0.5) + rng.normal(0, 0.3, n)
    res = D.mine(df, col="r", features=["f1", "f2", "f3"], n_trials=1500, n_null=3, min_support=300, top_k=5, say=lambda *_: None)
    assert res["ledger"]["trials"] == 1500 and res["ledger"]["nulls"] == 3 and res["ledger"]["conditions"] > 10
    assert res["best_valid_mean"] > 0.5 and "f1" in res["rules"][0]["rule"]
    assert res["p_vs_null"] <= 0.25 + 1e-9 and max(res["null_best_valid_means"]) < res["best_valid_mean"]


def test_a_noise_outcome_is_not_called_a_finding():
    rng = np.random.default_rng(8)
    n = 6000
    days = pd.bdate_range("2019-01-01", periods=1500)
    df = pd.DataFrame({"day": [days[i % 1500].date() for i in range(n)], "symbol": "X", "kind": "index",
                       "f1": rng.uniform(0, 1, n), "f2": rng.normal(size=n), "f3": rng.normal(size=n), "r": rng.normal(0, 1, n)})
    res = D.mine(df, col="r", features=["f1", "f2", "f3"], n_trials=1500, n_null=3, min_support=300, top_k=5, say=lambda *_: None)
    assert res["ledger"]["trials"] == 1500
    assert not (res["best_valid_mean"] > 0.3)                # pure noise, less the cost: the best of 1,500 tries on it is still nothing worth reporting


def test_the_lab_report_states_the_bar_the_trials_and_the_not_for(tmp_path):
    tr = trades_frame(days=800)
    p = D.write_lab_report(tmp_path, tr, None, run_mining=False, say=lambda *_: None)
    text = p.read_text()
    assert "Not for:" in text and "Cells passing" in text and "Bonferroni" not in text and "t >=" in text
