"""The shadow lab (quantdesk/intraday/shadowlab.py): labels, ideas, lockdown, refusals, and one real replay offline."""
import datetime as dt
import subprocess
import sys
import textwrap
from pathlib import Path

import pandas as pd
import pytest

from quantdesk.intraday import shadowlab as L

IST = "Asia/Kolkata"


def minutes(rows, start="2026-09-25 10:00"):
    idx = pd.date_range(start, periods=len(rows), freq="min", tz=IST)
    return pd.DataFrame(rows, index=idx, columns=["open", "high", "low", "close"])


NOW = pd.Timestamp("2026-09-25 10:00", tz=IST)          # the fire happened inside the 09:59 bar; the first bar to read starts at 10:00


def test_a_target_is_a_win_of_reward_over_risk():
    bars = minutes([(100, 101, 99.5, 100.5), (100.5, 103.5, 100.2, 103.0)])
    r = L.label_fire(bars, NOW, fill=100.0, invalidation=98.0, direction=1, reward_risk=1.5, min_move=0.0)
    assert r["exit_reason"] == "target" and r["r_underlying"] == pytest.approx(1.5) and r["target"] == pytest.approx(103.0)
    assert r["mfe_r"] == pytest.approx(1.5) and r["bars_after"] == 2


def test_the_stop_wins_when_one_bar_touches_both():
    bars = minutes([(100, 104, 97.5, 101)])
    r = L.label_fire(bars, NOW, 100.0, 98.0, 1, 1.5, 0.0)
    assert r["exit_reason"] == "stop" and r["r_underlying"] == -1.0 and r["mae_r"] == -1.0


def test_a_short_setup_is_signed_the_other_way():
    bars = minutes([(100, 100.5, 96.5, 97.0)])
    r = L.label_fire(bars, NOW, 100.0, 102.0, -1, 1.5, 0.0)                     # risk 2, target 97
    assert r["exit_reason"] == "target" and r["r_underlying"] == pytest.approx(1.5)


def test_with_neither_touched_the_horizons_last_close_marks_it():
    bars = minutes([(100, 100.6, 99.5, 100.4), (100.4, 100.9, 100.1, 100.8)])
    r = L.label_fire(bars, NOW, 100.0, 98.0, 1, 3.0, 0.0, horizon=45)
    assert r["exit_reason"] == "horizon" and r["r_underlying"] == pytest.approx((100.8 - 100.0) / 2.0)


def test_the_min_move_sets_the_target_when_reward_over_risk_is_smaller():
    bars = minutes([(100, 100.6, 99.8, 100.2)])
    r = L.label_fire(bars, NOW, 100.0, 99.5, 1, 1.0, 4.0)                       # risk 0.5, 1R = 0.5, but the target is at least 4 away
    assert r["target"] == pytest.approx(104.0)


def test_only_bars_from_now_on_are_read_and_the_horizon_cuts_the_window():
    past = pd.DataFrame([(100, 100, 90, 95)], index=[NOW - pd.Timedelta(minutes=1)], columns=["open", "high", "low", "close"])   # the firing bar itself would hit any stop
    later = minutes([(100, 100.4, 99.9, 100.1)] * 3 + [(100, 120, 80, 100)], start="2026-09-25 10:00")
    late = later.iloc[3:].copy()
    bars = pd.concat([past, later])
    r = L.label_fire(bars, NOW, 100.0, 98.0, 1, 3.0, 0.0, horizon=3)
    assert r["bars_after"] == 3 and r["exit_reason"] == "horizon"                # neither the bar before now nor the bar past the horizon was read
    assert L.label_fire(past, NOW, 100.0, 98.0, 1, 3.0, 0.0) is None            # nothing after the fill: no label, no guess


def test_an_invalid_plan_has_no_label():
    bars = minutes([(100, 101, 99, 100)])
    assert L.label_fire(bars, NOW, 100.0, 100.0, 1, 1.5, 0.0) is None            # zero risk
    assert L.label_fire(bars, NOW, 100.0, 102.0, 1, 1.5, 0.0) is None            # a long whose stop is above the fill


def test_a_re_armed_setup_inside_its_window_is_one_idea():
    t = pd.Timestamp("2026-09-25 10:00", tz=IST)
    rows = [{"ts": str(t), "symbol": "NIFTY", "setup": "orb", "direction": 1},
            {"ts": str(t + pd.Timedelta(minutes=1)), "symbol": "NIFTY", "setup": "orb", "direction": 1},
            {"ts": str(t + pd.Timedelta(minutes=2)), "symbol": "NIFTY", "setup": "orb", "direction": -1},
            {"ts": str(t + pd.Timedelta(minutes=2)), "symbol": "BANKNIFTY", "setup": "orb", "direction": 1},
            {"ts": str(t + pd.Timedelta(minutes=60)), "symbol": "NIFTY", "setup": "orb", "direction": 1}]
    assert [r["idea_first"] for r in L.mark_ideas(rows)] == [True, False, True, True, True]


def test_a_worker_can_open_no_connection_and_holds_no_credential():
    code = textwrap.dedent("""
        import os, socket
        os.environ["KITE_DATA_SECRET"] = "x"; os.environ["ANTHROPIC_API_KEY"] = "y"; os.environ["PATH_OK"] = "z"
        from quantdesk.intraday import shadowlab as L
        L.lock_down()
        assert "KITE_DATA_SECRET" not in os.environ and "ANTHROPIC_API_KEY" not in os.environ and os.environ["PATH_OK"] == "z"
        for call in (lambda: socket.socket().connect(("127.0.0.1", 9)), lambda: socket.getaddrinfo("example.com", 80)):
            try:
                call()
            except OSError as e:
                assert "no connection" in str(e)
            else:
                raise SystemExit("a connection was allowed")
        print("locked")
    """)
    res = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=L.REPO, timeout=120)
    assert res.returncode == 0 and "locked" in res.stdout, res.stdout + res.stderr


def test_the_lab_refuses_an_output_inside_a_git_tree_or_a_used_folder(tmp_path):
    with pytest.raises(L.Refused, match="git working tree"):
        L.run(tmp_path / "ds", L.REPO / "shadow_out_should_never_exist", loader=lambda *a, **k: None)
    used = tmp_path / "used"
    used.mkdir()
    (used / "something.txt").write_text("x")
    with pytest.raises(L.Refused, match="new or empty"):
        L.run(tmp_path / "ds", used, loader=lambda *a, **k: None)
    with pytest.raises(L.Refused, match="not an ml-intake dataset"):
        L.run(tmp_path / "missing", tmp_path / "fresh")


def test_one_synthetic_session_is_replayed_offline_into_labelled_rows_and_leaves_the_runtime_alone(tmp_path, cfg):
    from quantdesk.core.calendar import TradingCalendar
    from quantdesk.intraday.synthetic import simulate_sessions
    days = [d.date() for d in TradingCalendar(cfg.holidays()).trading_days("2026-09-14", "2026-09-28")]
    bars, _ = simulate_sessions(days, seed=11)
    day = days[-1]
    work = tmp_path / "work"
    rows = L.replay_day({k: v for k, v in bars.items() if k in ("NIFTY", "BANKNIFTY", "INDIAVIX")}, day, ["NIFTY", "BANKNIFTY"], work)
    assert rows, "this seeded session arms and fires at least one setup"
    need = {"day", "ts", "symbol", "setup", "direction", "fill", "invalidation", "reward_risk", "risk_pct", "minutes_since_open", "r_underlying",
            "exit_reason", "mfe_r", "mae_r", "desk_taken", "idea_first", "view_score", "view_conviction", "view_day_type"}
    assert need <= set(rows[0]) and all(r["day"] == str(day) for r in rows)
    assert all(-1.0 <= r["r_underlying"] and pd.Timestamp(r["ts"]).tz is not None for r in rows)
    assert rows[0]["idea_first"] is True and [r["ts"] for r in rows] == sorted(r["ts"] for r in rows)
    assert (work / "journal.db").is_file()                                       # the throwaway journal is under the work folder ...
    assert not list((tmp_path / "runtime").rglob("*.db")) and not (L.REPO / "journal.db").exists()      # ... and the configured runtime is untouched
