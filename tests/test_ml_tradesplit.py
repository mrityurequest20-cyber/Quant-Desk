"""The read-only split of the paper desk's closed trades (quantdesk/ml/tradesplit.py)."""
import hashlib
import json
import math
import sqlite3

import pytest

from quantdesk.cli import main
from quantdesk.ml import tradesplit as T

COLS = ("id TEXT PRIMARY KEY, strategy TEXT, symbol TEXT, direction INTEGER, kind TEXT, opened_at TEXT, entry_underlying REAL, exit_underlying REAL, "
        "pnl REAL, fees REAL, exit_reason TEXT, status TEXT, legs TEXT")


def leg(right, strike, qty=1, kind="option"):
    return {"instrument": {"kind": kind, "strike": strike, "right": right}, "qty": qty}


def trade(i, strategy="orb", day="2026-10-12", spot=1000.0, legs=None, pnl=100.0, fees=10.0, direction=1, exit_u=1010.0, reason="time_exit", symbol="NIFTY", status="closed"):
    return (f"T{i}", strategy, symbol, direction, "options", f"{day} 10:00:00+05:30", spot, exit_u, pnl, fees, reason, status, json.dumps(legs if legs is not None else [leg("CE", 1010.0)]))


def make_db(tmp_path, rows):
    p = tmp_path / "journal.db"
    with sqlite3.connect(p) as db:
        db.execute(f"CREATE TABLE trades ({COLS})")
        db.executemany("INSERT INTO trades VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    return p


def test_distance_is_out_of_the_money_for_calls_and_puts_and_negative_in_the_money():
    f = lambda legs, spot=1000.0: T.long_leg_distance_pct({"entry_underlying": spot, "legs": json.dumps(legs)})
    assert f([leg("CE", 1010.0)]) == pytest.approx(1.0) and f([leg("PE", 990.0)]) == pytest.approx(1.0)
    assert f([leg("CE", 990.0)]) == pytest.approx(-1.0) and f([leg("PE", 1010.0)]) == pytest.approx(-1.0)
    assert f([leg("CE", 1050.0), leg("CE", 1010.0)]) == pytest.approx(1.0)                      # two long legs: the one nearest the money
    assert f([leg("CE", 1010.0, qty=-1)]) is None and f([leg("CE", 1010.0, kind="future")]) is None and f([]) is None
    assert f([leg("CE", 1010.0)], spot=0.0) is None and f([leg("XX", 1010.0)]) is None


@pytest.mark.parametrize("bad", [None, "", "not json", "{}", "[1]", '[{"instrument": 5}]', '[null]'])
def test_unreadable_legs_are_no_long_leg_not_a_crash(bad):
    try:
        d = T.long_leg_distance_pct({"entry_underlying": 1000.0, "legs": bad})
    except AttributeError:
        pytest.fail("a malformed legs value must not crash the report")
    assert d is None


@pytest.mark.parametrize("d,name", [(None, "no long option leg"), (-3.0, "up to 0.25% OTM"), (0.0, "up to 0.25% OTM"), (0.2499, "up to 0.25% OTM"),
                                    (0.25, "0.25% to 0.75% OTM"), (0.7499, "0.25% to 0.75% OTM"), (0.75, "over 0.75% OTM"), (9.0, "over 0.75% OTM")])
def test_the_buckets_are_closed_below_and_open_above_and_fixed(d, name):
    assert T.bucket(d) == name


def test_wilson_interval_matches_known_values_and_is_bounded():
    lo, hi = T.wilson(5, 10, z=1.96)
    assert lo == pytest.approx(0.2366, abs=2e-3) and hi == pytest.approx(0.7634, abs=2e-3)
    assert T.wilson(0, 3)[0] == 0.0 and T.wilson(3, 3)[1] == 1.0 and math.isnan(T.wilson(0, 0)[0])


def test_the_day_bootstrap_is_deterministic_needs_two_days_and_brackets_the_mean():
    ts = [{"opened_at": f"2026-10-{12 + i % 5} 10:00", "pnl": 100.0 * (i % 3 - 1) + i} for i in range(20)]
    a, b = T.day_bootstrap(ts), T.day_bootstrap(ts)
    mean = sum(t["pnl"] for t in ts) / 20
    assert a == b and a[0] <= mean <= a[1]
    assert all(math.isnan(x) for x in T.day_bootstrap(ts[:1]))
    four = [{"opened_at": f"2026-10-{12 + i} 10:00", "pnl": float(i)} for i in range(T.MIN_DAYS - 1)]
    assert all(math.isnan(x) for x in T.day_bootstrap(four))                                       # fewer than MIN_DAYS days: no interval, it would be the day means
    uneven = [{"opened_at": f"2026-10-{12 + d} 10:00", "pnl": p} for d, p in [(0, 10.0), (0, 20.0), (0, 30.0), (1, -5.0), (2, 7.0), (3, 1.0), (4, 2.0), (5, 3.0)]]
    lo, hi = T.day_bootstrap(uneven)
    assert lo <= sum(t["pnl"] for t in uneven) / 8 <= hi
    assert all(math.isnan(x) for x in T.day_bootstrap([{"opened_at": "2026-10-12 10:00", "pnl": 1.0}, {"opened_at": "2026-10-12 11:00", "pnl": 2.0}]))   # one day


def test_a_cell_reports_concentration_and_flags_few_trades():
    ts = [{"opened_at": f"2026-10-{12 + i} 10:00", "pnl": p, "fees": 1.0} for i, p in enumerate([1000.0, 900.0, 800.0, -10.0, -20.0])]
    c = T.cell(ts)
    assert c["n"] == 5 and c["wins"] == 3 and c["pnl"] == 2670.0 and c["top3"] == [1000.0, 900.0, 800.0]
    assert c["too_few"] and c["fees"] == 5.0 and c["days"] == 5
    assert math.isnan(c["pnl_without_top3"])                                                        # under MIN_TOP3 trades the exclusion says nothing
    more = ts + [{"opened_at": f"2026-10-{20 + i} 10:00", "pnl": -5.0, "fees": 1.0} for i in range(5)]
    assert T.cell(more)["pnl_without_top3"] == pytest.approx(-55.0)                                # 2,645 in total less the best three (2,700)


def test_the_report_makes_no_claim_below_the_declared_floor_and_only_descriptive_above(tmp_path):
    small = tmp_path / "small"
    small.mkdir()
    rep = T.split(T.load_closed(make_db(small, [trade(i, day=f"2026-10-{12 + i % 8}") for i in range(T.MIN_TRADES - 1)])))
    assert rep["total_trades"] == T.MIN_TRADES - 1 and rep["claim"].startswith("no claim")
    big = tmp_path / "big"
    big.mkdir()
    rep = T.split(T.load_closed(make_db(big, [trade(i, day=f"2026-10-{12 + i % 8}") for i in range(T.MIN_TRADES)])))
    assert rep["claim"].startswith("descriptive only") and "pre-registered" in rep["claim"]


def test_only_closed_trades_count_and_the_database_is_not_touched(tmp_path):
    rows = [trade(1), trade(2, status="open"), trade(3, strategy="vwap_trend", pnl=-50.0)]
    p = make_db(tmp_path, rows)
    before = hashlib.sha256(p.read_bytes()).hexdigest()
    got = T.load_closed(p)
    T.split(got)
    assert [t["id"] for t in got] == ["T1", "T3"]
    assert hashlib.sha256(p.read_bytes()).hexdigest() == before and sorted(x.name for x in tmp_path.iterdir()) == ["journal.db"]


def test_the_connection_is_read_only(tmp_path, monkeypatch):
    p = make_db(tmp_path, [trade(1)])
    seen = []
    real = sqlite3.connect
    monkeypatch.setattr(T.sqlite3, "connect", lambda *a, **k: (seen.append((a, k)), real(*a, **k))[1])
    T.load_closed(p)
    assert "mode=ro" in seen[0][0][0] and seen[0][1].get("uri") is True


def test_a_missing_file_a_missing_table_and_a_missing_column_are_named(tmp_path):
    with pytest.raises(T.JournalError, match="no journal"):
        T.load_closed(tmp_path / "nope.db")
    empty = tmp_path / "empty.db"
    sqlite3.connect(empty).close()
    with pytest.raises(T.JournalError):
        T.load_closed(empty)
    thin = tmp_path / "thin.db"
    with sqlite3.connect(thin) as db:
        db.execute("CREATE TABLE trades (id TEXT, status TEXT, opened_at TEXT)")
        db.execute("INSERT INTO trades VALUES ('a','closed','2026-10-12')")
    with pytest.raises(T.JournalError, match="lacks"):
        T.load_closed(thin)


def test_the_splits_group_by_sleeve_distance_symbol_exit_and_day(tmp_path):
    rows = [trade(1, "orb", "2026-10-12", legs=[leg("CE", 1001.0)], pnl=500.0),                       # 0.1% out
            trade(2, "orb", "2026-10-13", legs=[leg("CE", 1050.0)], pnl=-200.0, symbol="BANKNIFTY", reason="invalidation"),     # 5% out
            trade(3, "vwap_trend", "2026-10-13", legs=[leg("PE", 995.0)], pnl=-300.0)]                # 0.5% out
    rep = T.split(T.load_closed(make_db(tmp_path, rows)))
    assert {k: v["n"] for k, v in rep["sleeve"].items()} == {"orb": 2, "vwap_trend": 1}
    assert {k: v["n"] for k, v in rep["strike_distance"].items()} == {"up to 0.25% OTM": 1, "0.25% to 0.75% OTM": 1, "over 0.75% OTM": 1}
    assert set(rep["symbol"]) == {"NIFTY", "BANKNIFTY"} and set(rep["exit_reason"]) == {"time_exit", "invalidation"} and set(rep["day"]) == {"2026-10-12", "2026-10-13"}
    assert rep["all"]["all"]["pnl"] == 0.0


def test_the_sleeve_check_separates_a_wrong_underlying_from_a_trade_lost_while_right(tmp_path):
    rows = [trade(1, "vwap_trend", exit_u=990.0, pnl=-500.0, fees=20.0),                                  # long, underlying fell: wrong
            trade(2, "vwap_trend", exit_u=1010.0, pnl=-100.0, fees=20.0, day="2026-10-13"),               # long, underlying rose, still lost
            trade(3, "vwap_trend", direction=-1, exit_u=990.0, pnl=700.0, day="2026-10-14"),              # short, underlying fell: right and won
            trade(4, "orb")]
    c = T.sleeve_check(T.load_closed(make_db(tmp_path, rows)), "vwap_trend")
    assert c["n"] == 3 and c["wins"] == 1 and c["underlying_against"] == 1 and c["underlying_with_trade_lost"] == 1
    assert [r["verdict"] for r in c["trades"]] == ["underlying against, trade lost", "underlying with, trade lost: exit/theta/cost", "won"]
    assert c["trades"][0]["pnl_before_fees"] == -480.0 and c["trades"][2]["underlying_move_in_trade_direction_pct"] == pytest.approx(1.0)
    assert T.sleeve_check([], "vwap_trend")["n"] == 0


def test_the_command_prints_the_report_and_needs_a_journal(tmp_path, capsys):
    p = make_db(tmp_path, [trade(i, "vwap_trend", day=f"2026-10-{12 + i}") for i in range(3)])
    main(["ml", "trades", "--journal", str(p), "--sleeve", "vwap_trend"])
    out = capsys.readouterr().out
    assert "3 closed trades (0 unwound entries left out); no claim" in out and "All: 3 trades" in out and "this labels, it does not separate" in out and "By sleeve:" in out and "Close look at vwap_trend" in out and "[too few]" in out
    with pytest.raises(SystemExit, match="--journal"):
        main(["ml", "trades"])
    with pytest.raises(SystemExit, match="no journal"):
        main(["ml", "trades", "--journal", str(tmp_path / "x.db")])


def test_a_path_with_special_characters_is_opened_read_only_and_creates_nothing(tmp_path):
    for name in ("a?b.db", "c#d.db", "e%20f.db"):
        d = tmp_path / name.replace("?", "q").replace("#", "h").replace("%", "p")
        d.mkdir()
        p = d / name
        with sqlite3.connect(p) as db:
            db.execute(f"CREATE TABLE trades ({COLS})")
            db.execute("INSERT INTO trades VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", trade(1))
        before = sorted(x.name for x in d.iterdir())
        assert [t["id"] for t in T.load_closed(p)] == ["T1"]
        assert sorted(x.name for x in d.iterdir()) == before                                         # no stray file from a misparsed URI


def test_unwound_entries_are_counted_apart_and_never_called_losses_or_right_calls(tmp_path):
    rows = [trade(1, pnl=100.0), trade(2, pnl=-12.0, fees=12.0, reason="entry_aborted", legs=[], exit_u=1000.0), trade(3, "vwap_trend", pnl=-50.0, reason="entry_aborted", legs=[], exit_u=1000.0)]
    got = T.load_closed(make_db(tmp_path, rows))
    rep = T.split(got)
    assert rep["total_trades"] == 1 and rep["aborted_entries"] == 2 and "entry_aborted" not in rep["exit_reason"] and "no long option leg" not in rep["strike_distance"]
    assert T.sleeve_check(got, "vwap_trend")["n"] == 0
    assert "_bucket" not in got[0]                                                                  # the caller's records are not modified


def test_a_flat_underlying_is_flat_and_a_win_is_a_win_whatever_the_spot_did():
    assert T._verdict(0.0, -10.0) == "underlying flat, trade lost" and T._verdict(-0.3, 50.0) == "won" and T._verdict(float("nan"), 1.0) == "no exit price"


def test_bucket_edges_through_the_distance_function():
    f = lambda strike: T.bucket(T.long_leg_distance_pct({"entry_underlying": 1000.0, "legs": json.dumps([leg("CE", strike)])}))
    assert f(1002.5) == "0.25% to 0.75% OTM" and f(1002.4) == "up to 0.25% OTM" and f(1007.5) == "over 0.75% OTM" and f(1007.4) == "0.25% to 0.75% OTM"


# ---- strike distance or the underlying? -----------------------------------------------------------------------------------
def leg_px(right, strike, entry, exit_, qty=10):
    return [{"instrument": {"kind": "option", "strike": strike, "right": right}, "qty": qty, "entry_price": entry, "exit_price": exit_}]


def test_the_decomposition_reads_premium_move_and_return_per_bucket(tmp_path):
    rows = [trade(1, legs=leg_px("CE", 1001.0, 10.0, 12.0), exit_u=1010.0, pnl=20.0, day="2026-10-12"),                    # 0.1% out, +1% underlying, +20% on premium
            trade(2, legs=leg_px("CE", 1050.0, 5.0, 4.0), exit_u=990.0, pnl=-10.0, day="2026-10-13"),                      # 5% out, -1% underlying, -20%
            trade(3, legs=leg_px("PE", 995.0, 8.0, 9.6), direction=-1, exit_u=990.0, pnl=16.0, day="2026-10-14")]            # 0.5% out, short underlying fell 1%: +1% in the trade's way
    dec = T.decomposition(T.load_closed(make_db(tmp_path, rows)))
    assert dec["n"] == 3 and set(dec["buckets"]) == {"up to 0.25% OTM", "0.25% to 0.75% OTM", "over 0.75% OTM"}
    b = dec["buckets"]["up to 0.25% OTM"]
    assert b["n"] == 1 and b["underlying_right"] == 1 and b["mean_underlying_move_pct"] == pytest.approx(1.0) and b["mean_return_on_premium_pct"] == pytest.approx(20.0)
    assert dec["buckets"]["over 0.75% OTM"]["underlying_right"] == 0 and dec["buckets"]["over 0.75% OTM"]["mean_return_on_premium_pct"] == pytest.approx(-20.0)
    assert dec["corr_move_return"] == pytest.approx(1.0) and dec["return_per_underlying_pct"] == pytest.approx(20.0)


def test_the_decomposition_skips_trades_it_cannot_read_and_unwound_entries_and_never_crashes(tmp_path):
    rows = [trade(1, legs=leg_px("CE", 1001.0, 10.0, 12.0), exit_u=1010.0), trade(2, legs=[], exit_u=1010.0), trade(3, legs=leg_px("CE", 1001.0, 10.0, 12.0), reason="entry_aborted"),
            trade(4, legs=[{"instrument": {"kind": "option", "strike": 1001.0, "right": "CE"}, "qty": 1}], exit_u=1010.0)]                # no prices
    dec = T.decomposition(T.load_closed(make_db(tmp_path, rows)))
    assert dec["n"] == 1 and math.isnan(dec["corr_distance_move"]) and math.isnan(dec["return_per_underlying_pct"])                          # one trade: no correlation to speak of
    assert "1 trades with a long option leg" in T.render_decomposition(dec)


def test_the_command_prints_the_decomposition_after_the_split(tmp_path, capsys):
    main(["ml", "trades", "--journal", str(make_db(tmp_path, [trade(i, legs=leg_px("CE", 1001.0 + i, 10.0, 11.0), day=f"2026-10-{12 + i}") for i in range(4)]))])
    out = capsys.readouterr().out
    assert "By sleeve:" in out and "Strike distance or the underlying?" in out and "[too few]" in out
