"""P0.2: the external index-minute importer (quantdesk/ml/intake.py): parsing, the timestamp bound, the session rules, the review
queue and its reviewed list, determinism, immutability, integrity at load, use restrictions, and that the ML package never
reaches into the live engine."""
import ast
import datetime as dt
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from quantdesk.data import external_aeron as legacy
from quantdesk.ml import intake as I

IST = I.IST
DAYS = ["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"]      # Monday to Friday
SAT = "2024-01-06"
REPO = Path(I.__file__).resolve().parents[2]


def make_day(day, start=25000.0, seed=0, n=375, first=(9, 15)):
    """One session of valid 1-minute bars (tz-aware IST, bar start)."""
    rng = np.random.default_rng(seed)
    c = np.round(start * np.exp(np.cumsum(rng.normal(0, 3e-4, n))), 2)
    o = np.r_[round(start, 2), c[:-1]]
    ts = pd.Timestamp(f"{day} {first[0]:02d}:{first[1]:02d}", tz=IST) + pd.to_timedelta(np.arange(n), unit="min")
    return pd.DataFrame({"ts": ts, "open": o, "high": np.maximum(o, c) + 0.5, "low": np.minimum(o, c) - 0.5,
                         "close": c, "volume": np.zeros(n, dtype="int64")})


def make_stale(df, start, length):
    """Make `length` bars from position `start` flat, repeating the previous close."""
    df = df.copy()
    p = float(df["close"].iloc[start - 1])
    for col in ("open", "high", "low", "close"):
        df.loc[df.index[start:start + length], col] = p
    return df


def steady_day(factor=1.0, at=200, day=DAYS[0]):
    """A session with no noise but a 0.05 tick wobble (so no bar is flat) and one step of `factor` at bar `at`: the one-minute
    log return is log(factor) to within 1e-5, so a bound can be tested exactly."""
    n = 375
    c = 25000.0 + 0.05 * (np.arange(n) % 2)
    c = np.where(np.arange(n) >= at, c * factor, c)
    o = np.r_[c[0], c[:-1]]
    ts = pd.Timestamp(f"{day} 09:15", tz=IST) + pd.to_timedelta(np.arange(n), unit="min")
    return pd.DataFrame({"ts": ts, "open": o, "high": np.maximum(o, c) + 0.01, "low": np.minimum(o, c) - 0.01, "close": c,
                         "volume": np.zeros(n, dtype="int64")})


def jumped(df, factor=1.07, at=200):
    d = df.copy()
    d.loc[at:, ["open", "high", "low", "close"]] *= factor
    return d


def check(df, day=DAYS[0], **kw):
    return I.check_session(df, dt.date.fromisoformat(day), **kw)[1]


def write_csv(path, frames):
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = pd.concat(frames)
    out = pd.DataFrame({"date": rows["ts"].dt.strftime("%Y-%m-%d %H:%M:%S"), "open": rows["open"], "high": rows["high"],
                        "low": rows["low"], "close": rows["close"], "volume": rows["volume"]})
    out.to_csv(path, index=False)


SRC = I.Source(name="unit-index-minutes", url="https://example.invalid/unit",
               files=(I.SourceFile("NIFTY.csv", "NIFTY"), I.SourceFile("BANKNIFTY.csv", "BANKNIFTY"),
                      I.SourceFile("VIX.csv", "INDIAVIX", kind="vol_index")))


def build_source(root, nifty=None, bank=None, vix=None):
    nifty = nifty or [make_day(d, 25000, i) for i, d in enumerate(DAYS)]
    bank = bank or [make_day(d, 50000, 10 + i) for i, d in enumerate(DAYS)]
    vix = vix or [make_day(d, 15, 20 + i) for i, d in enumerate(DAYS)]
    write_csv(root / "NIFTY.csv", nifty)
    write_csv(root / "BANKNIFTY.csv", bank)
    write_csv(root / "VIX.csv", vix)
    return root


def reviewed_file(tmp_path, entries, name="rv.json", schema=2):
    p = tmp_path / name
    p.write_text(json.dumps({"schema": schema, "sessions": entries}))
    return p


@pytest.fixture
def reviewed_none(tmp_path):
    return reviewed_file(tmp_path, [], name="none.json")


def run_import(src_dir, out_dir, reviewed, **kw):
    return I.import_source(src_dir, out_dir, SRC, reviewed_path=reviewed, say=None, **kw)


EVIDENCE = "NIFTY and BANKNIFTY both stopped, then moved together after the halt; the provider's daily file shows the same range."


OBSERVED_LITERAL = {"jump": "max_1m_move_at", "stale_run": "longest_stale_run", "stale_share": "stale_bars", "weekend_full": "minutes"}


def entry(man, symbol, day, codes, **over):
    """A reviewed entry for a session of an already-imported manifest, filled with the facts it must match."""
    s = next(x for x in man["sessions"] if x["symbol"] == symbol and x["day"] == day)
    e = {"symbol": symbol, "day": day, "codes": codes, "decision": "admit", "evidence": EVIDENCE, "reviewer": "A. Reviewer",
         "date": "2026-10-25", "file_sha256": man["source"]["files"][s["file_id"]]["sha256"],
         "observed": {OBSERVED_LITERAL[k]: s[OBSERVED_LITERAL[k]] for k in codes}}
    e.update(over)
    return e


# ---- reading --------------------------------------------------------------------------------------------------------
def test_read_floors_small_second_offsets_and_drops_ambiguous_ones(tmp_path):
    p = tmp_path / "x.csv"
    p.write_text("date,open,high,low,close,volume\n"
                 "2024-01-01 09:15:00,100,101,99,100.5,0\n"
                 "2024-01-01 09:16:01,100.5,101,100,100.8,0\n"            # 1 s past: floored
                 "2024-01-01 09:17:15,100.8,101,100,100.9,0\n"            # exactly the bound: floored
                 "2024-01-01 09:18:16,100.9,101,100,100.7,0\n")           # beyond it: dropped, not guessed
    df, rep, per_day = I.read_minutes(p, "NIFTY")
    assert [t.strftime("%H:%M:%S") for t in df["ts"]] == ["09:15:00", "09:16:00", "09:17:00"]
    assert rep["floored_seconds"] == 2 and rep["ambiguous_timestamp"] == 1 and rep["unparsed"] == 0
    assert per_day == {"2024-01-01": 1} and str(df["ts"].dt.tz) == IST


def test_read_drops_and_counts_each_kind_of_bad_row(tmp_path):
    p = tmp_path / "x.csv"
    p.write_text("date,open,high,low,close,volume\n"
                 "2024-01-01 09:15:00,100,101,99,100.5,0\n"
                 "garbage,1,2,3,4,0\n"                                    # unparsable date: no day to blame
                 "2024-01-01 09:17:00,100,abc,99,100,0\n"                 # unparsable price
                 "2024-01-01 09:18:00,100,inf,99,100,0\n"                 # non-finite
                 "2024-01-01 09:19:00,100,99,101,100,0\n"                 # high < low
                 "2024-01-01 09:20:00,0,1,0,1,0\n"                        # non-positive
                 "2024-01-01 09:21:00,100,101,99,102,0\n"                 # close above high
                 "2024-01-01 09:22:00,100,101,99,100,-5\n"                # negative volume
                 "2024-01-01 09:23:00,100,101,99,100,2.5\n"               # fractional volume
                 "2024-01-01 09:24:00,100,101,99,100,7\n"
                 "2024-01-01 09:25:00,98,101,99,100,0\n"                  # open below the low, nothing else wrong
                 "2024-01-01 09:26:00,102,101,99,100,0\n"                 # open above the high, nothing else wrong
                 "2024-01-01 09:27:00,100,101,99,98.5,0\n")               # close below the low, nothing else wrong
    df, rep, per_day = I.read_minutes(p, "NIFTY")
    assert len(df) == 2 and rep["rows_in"] == 13
    assert rep["unparsed"] == 3 and rep["bad_price"] == 6 and rep["invalid_volume"] == 2
    assert per_day == {"2024-01-01": 10}             # every dropped row that had a date: 2 unparsable numbers + 6 prices + 2 volumes
    assert df["volume"].tolist() == [0, 7] and rep["zero_volume"] == 1


def test_read_counts_out_of_order_rows(tmp_path):
    p = tmp_path / "x.csv"
    p.write_text("date,open,high,low,close,volume\n"
                 "2024-01-01 09:16:00,100,101,99,100,0\n2024-01-01 09:15:00,100,101,99,100,0\n")
    assert I.read_minutes(p, "NIFTY")[1]["out_of_order"] == 1


def test_a_different_header_or_an_end_labelled_file_is_refused_not_guessed(tmp_path):
    p = tmp_path / "x.csv"
    p.write_text("Date,Open,High,Low,Close,Volume\n2024-01-01 09:15:00,1,2,0.5,1,0\n")
    with pytest.raises(I.SourceFormatError, match="header"):
        I.read_minutes(p, "NIFTY")
    d = make_day(DAYS[0], n=375, first=(9, 16))                                     # 09:16 ... 15:30: bars labelled by their END
    write_csv(tmp_path / "end.csv", [d])
    with pytest.raises(I.SourceFormatError, match="end-labelled"):
        I.read_minutes(tmp_path / "end.csv", "NIFTY")
    # rows that do not parse are not evidence of a labelling: two garbage rows at 15:30 against one real bar at 09:15
    q = tmp_path / "garbage.csv"
    q.write_text("date,open,high,low,close,volume\n2024-01-01 09:15:00,100,101,99,100.5,0\n"
                 "2024-01-01 15:30:00,x,y,z,w,0\n2024-01-02 15:30:00,x,y,z,w,0\n")
    df, rep, _ = I.read_minutes(q, "NIFTY")
    assert len(df) == 1 and rep["unparsed"] == 2


# ---- one session ----------------------------------------------------------------------------------------------------
def test_a_clean_session_is_accepted_and_carries_its_variance():
    g, v = I.check_session(make_day(DAYS[0]), dt.date(2024, 1, 1))
    assert v["status"] == "accepted" and v["minutes"] == 375 and v["missing_minutes"] == 0 and v["reasons"] == []
    assert len(g) == 375 and v["longest_stale_run"] == 0 and v["longest_gap_min"] == 0
    assert (v["head_gap_min"], v["tail_gap_min"]) == (0, 0)
    r = np.diff(np.log(g["close"].to_numpy()))
    assert v["rv"] == pytest.approx(float(np.sum(r * r)), rel=1e-9) and v["rv"] > 0


def test_short_sessions_are_rejected_and_a_weekend_one_says_so():
    v = check(make_day(DAYS[0], n=359))
    assert v["status"] == "rejected" and "short_session" in v["hard_codes"]
    short_weekend = check(make_day(SAT, n=100), SAT)
    assert short_weekend["status"] == "rejected" and short_weekend["hard_codes"][:2] == ["weekend", "short_session"]
    d = make_day(DAYS[0]).drop(index=range(100, 115)).reset_index(drop=True)          # 360 minutes, 15 missing inside
    v = check(d)
    assert v["status"] == "accepted" and v["minutes"] == 360 and v["missing_minutes"] == 15           # the boundary: 360 is enough


def test_a_full_length_weekend_session_goes_to_review_not_to_the_bin():
    v = check(make_day(SAT, n=375), SAT)                                              # a Budget Saturday
    assert v["status"] == "review" and v["review_codes"] == ["weekend_full"] and v["hard_codes"] == []
    assert v["reasons"] == ["weekend session with 375 minutes"]
    sunday = check(make_day("2024-01-07", n=369), "2024-01-07")                       # a Sunday that stops 6 minutes before the close
    assert sunday["status"] == "rejected" and sunday["hard_codes"] == ["truncated"] and sunday["review_codes"] == ["weekend_full"]


@pytest.mark.parametrize("n, first, status", [(370, (9, 20), "accepted"), (369, (9, 21), "rejected"),     # head gap 5 / 6 minutes
                                              (370, (9, 15), "accepted"), (369, (9, 15), "rejected")])     # tail gap 5 / 6 minutes
def test_a_session_that_misses_its_open_or_its_close_is_truncated(n, first, status):
    v = check(make_day(DAYS[0], n=n, first=first))
    assert v["status"] == status and v["hard_codes"] == ([] if status == "accepted" else ["truncated"])
    assert max(v["head_gap_min"], v["tail_gap_min"]) == (5 if status == "accepted" else 6)


def test_a_jump_goes_to_review_for_an_index_but_not_for_a_volatility_index():
    d = jumped(make_day(DAYS[0]), 1.08)
    v = check(d)
    assert v["status"] == "review" and v["review_codes"] == ["jump"] and v["max_1m_move"] > 0.05
    assert v["max_1m_move_signed"] > 0 and v["max_1m_move_at"].endswith("+05:30") and "log move" in v["reasons"][0]
    assert check(d, index_rules=False)["status"] == "accepted"
    assert "stale" not in "".join(v["review_codes"])


def test_the_jump_bound_is_a_log_return_of_five_percent_in_both_directions():
    """A +5.05% simple move is a 4.93% log move (accepted); a -4.95% simple move is a 5.07% log move (review): the rule is on
    log returns, the quantity a realised variance is made of, and the docs say so."""
    for factor, status in ((1.0488, "accepted"), (1.0505, "accepted"), (1.0515, "review"), (1.052, "review"),
                           (0.9515, "accepted"), (0.9505, "review"), (0.948, "review")):
        v = check(steady_day(factor))
        assert v["status"] == status, (factor, v["max_1m_move"])
        assert v["max_1m_move"] == pytest.approx(abs(np.log(factor)), abs=1e-5)


def test_the_declared_rules_are_pinned():
    """These numbers are the importer's pre-declared rules (they are in every manifest). Changing one is a decision with a new
    importer version and a new dataset, not an edit: this test makes sure it is noticed."""
    r = I.rules()
    assert (r["jump"], r["stale_run"], r["stale_share"], r["min_minutes"], r["max_edge_gap"]) == (0.05, 10, 0.03, 360, 5)
    assert (r["max_jitter_s"], r["corroborate"], r["max_unparsed_share"], r["evidence_min"]) == (15, 0.03, 0.01, [40, 6])
    assert (I.FIRST_MOD, I.LAST_MOD, I.SESSION_MINUTES) == (555, 929, 375)
    assert r["importer_version"] == "ml-intake-2" and r["header"] == ["date", "open", "high", "low", "close", "volume"]
    assert I.REVIEW_CODES == ("jump", "stale_run", "stale_share", "weekend_full")
    assert I.HARD_CODES == ("weekend", "short_session", "truncated", "end_labelled")
    assert I.OBSERVED == OBSERVED_LITERAL                       # which number a reviewer's entry is bound to, per code


@pytest.mark.parametrize("length, codes", [(9, []), (10, ["stale_run"]), (60, ["stale_run", "stale_share"])])
def test_a_stale_run_of_ten_bars_goes_to_review(length, codes):
    v = check(make_stale(make_day(DAYS[0]), 100, length))
    assert v["longest_stale_run"] == length and v["review_codes"] == codes
    assert v["status"] == ("review" if codes else "accepted")


def test_many_short_freezes_are_caught_by_the_share_of_stale_bars():
    """A near-frozen feed can be made of runs of 5, 7, 9: no run reaches 10, but the session is mostly stale."""
    d = make_day(DAYS[0])
    for start, length in ((50, 5), (120, 6)):                                             # 11 stale bars: 2.9%, under the bound
        d = make_stale(d, start, length)
    v = check(d)
    assert v["stale_bars"] == 11 and v["status"] == "accepted"
    d = make_stale(d, 200, 1)                                                              # 12 stale bars: 3.2%
    v = check(d)
    assert v["stale_bars"] == 12 and v["longest_stale_run"] == 6 and v["review_codes"] == ["stale_share"]
    vix = check(d, index_rules=False)                                                      # a volatility index prints flat minutes: not a fault
    assert vix["status"] == "accepted" and vix["stale_bars"] == 12
    assert check(make_stale(make_day(DAYS[0]), 100, 10), index_rules=False)["review_codes"] == ["stale_run"]   # but a 10-bar freeze still is


def test_flat_bars_at_moving_prices_are_not_stale_and_a_gap_breaks_a_run():
    d = make_day(DAYS[0])
    for i, row in enumerate(range(100, 131)):                                              # a quiet market: each bar flat, each at a new price
        d.loc[row, ["open", "high", "low", "close"]] = d["close"].iloc[99] + 0.05 * (i + 1)
    assert check(d)["longest_stale_run"] == 0
    frozen = d.copy()
    frozen.loc[100:130, ["open", "high", "low", "close"]] = d["close"].iloc[99] + 3.0       # the same price 31 times: a frozen feed
    assert check(frozen)["longest_stale_run"] == 30
    s = make_stale(make_day(DAYS[0]), 100, 12).drop(index=range(105, 107)).reset_index(drop=True)  # two minutes missing inside
    assert check(s)["longest_stale_run"] == 5                                              # bars 100-104; 108-111 is 4; the gap breaks it


def test_out_of_session_minutes_are_dropped_and_counted():
    d = pd.concat([make_day(DAYS[0], n=10, first=(9, 5)), make_day(DAYS[0]), make_day(DAYS[0], n=3, first=(15, 30))]).reset_index(drop=True)
    g, v = I.check_session(d, dt.date(2024, 1, 1))
    assert v["out_of_session"] == 10 + 3 and len(g) == 375 and v["status"] == "accepted"
    assert g["ts"].min().strftime("%H:%M") == "09:15" and g["ts"].max().strftime("%H:%M") == "15:29"


def test_duplicate_minutes_identical_keep_one_conflicting_drop_both():
    d = make_day(DAYS[0])
    ident = pd.concat([d, d.iloc[[10]]]).reset_index(drop=True)
    g, v = I.check_session(ident, dt.date(2024, 1, 1))
    assert len(g) == 375 and v["duplicates"] == 1 and v["conflicting_duplicates"] == 0
    clash = d.iloc[[20]].copy()
    clash[["open", "high", "low", "close"]] = [1.0, 2.0, 0.5, 1.5]
    g, v = I.check_session(pd.concat([d, clash]).reset_index(drop=True), dt.date(2024, 1, 1))
    assert len(g) == 374 and v["conflicting_duplicates"] == 1 and v["missing_minutes"] == 1
    assert d["ts"].iloc[20] not in set(g["ts"])
    close_only = d.iloc[[30]].copy()
    close_only["close"] = close_only["close"] + 0.01                                       # differs in the close alone: still a conflict
    assert I.check_session(pd.concat([d, close_only]).reset_index(drop=True), dt.date(2024, 1, 1))[1]["conflicting_duplicates"] == 1


def test_missing_minutes_and_the_longest_gap_are_recorded():
    d = make_day(DAYS[0]).drop(index=range(50, 58)).reset_index(drop=True)
    v = check(d)
    assert v["missing_minutes"] == 8 and v["longest_gap_min"] == 8 and v["status"] == "accepted"


def test_the_session_rules_agree_with_the_legacy_importer_on_messy_sessions():
    """Differential test: the aeron7 importer's session_check is the reference for what a session's minutes, gaps and
    rejection are. Legacy rejects a session exactly when this importer hard-rejects it as short or weekend, or sends it to
    review for a jump or a full weekend; everything else (truncation, stale bars) is new here and does not occur in this data."""
    rng = np.random.default_rng(7)
    for k in range(60):
        day = pd.Timestamp("2023-03-06") + pd.Timedelta(days=int(rng.integers(0, 40)))
        n = int(rng.choice([375, 375, 370, 362, 300, 100]))
        d = make_day(str(day.date()), seed=k, n=n)
        if rng.random() < 0.4:
            d = d.drop(index=rng.choice(len(d), size=int(rng.integers(1, 12)), replace=False)).reset_index(drop=True)
        if rng.random() < 0.3:
            d = pd.concat([d, d.iloc[rng.choice(len(d), size=3)]]).reset_index(drop=True)
        if rng.random() < 0.25:
            d.loc[len(d) // 2:, ["open", "high", "low", "close"]] *= 1.07
        d = d.sample(frac=1.0, random_state=k).reset_index(drop=True)                    # unordered input
        g_new, v_new = I.check_session(d, day.date())
        g_old, v_old = legacy.session_check(d)
        assert v_new["minutes"] == v_old["minutes"] and v_new["missing_minutes"] == v_old["missing_minutes"]
        assert v_new["longest_gap_min"] == v_old["longest_gap_min"]
        assert v_new["conflicting_duplicates"] == v_old["conflicting_duplicates"]
        assert abs(v_new["max_1m_move"] - v_old["max_1m_move"]) < 1e-9
        assert list(g_new["ts"]) == list(g_old["ts"])
        mine_rejects = bool(set(v_new["hard_codes"]) & {"weekend", "short_session"} or set(v_new["review_codes"]) & {"jump", "weekend_full"})
        assert mine_rejects == (not v_old["accepted"]), (k, v_new["hard_codes"], v_new["review_codes"], v_old["reasons"])


# ---- the review queue's evidence ------------------------------------------------------------------------------------
def test_corroboration_needs_the_same_direction_the_same_minute_and_enough_size():
    t0 = pd.Timestamp("2024-01-01 10:00", tz=IST)
    rec = {"review_codes": ["jump"], "max_1m_move_at": str(t0), "max_1m_move_signed": 0.07}

    def other(step_at, factor):
        ts = pd.date_range(t0 - pd.Timedelta(minutes=10), periods=21, freq="min")
        close = np.where(ts >= step_at, 100.0 * factor, 100.0)
        return pd.DataFrame({"ts": ts, "close": close})

    up = 1.05
    assert I.corroborate(rec, {"X": other(t0, up)}) == ["X"]                                  # the same minute
    assert I.corroborate(rec, {"X": other(t0 + pd.Timedelta(minutes=1), up)}) == ["X"]        # one minute later
    assert I.corroborate(rec, {"X": other(t0 - pd.Timedelta(minutes=1), up)}) == ["X"]        # one minute earlier
    assert I.corroborate(rec, {"X": other(t0 + pd.Timedelta(minutes=2), up)}) == []           # two minutes away: not the same event
    assert I.corroborate(rec, {"X": other(t0 - pd.Timedelta(minutes=2), up)}) == []
    assert I.corroborate(rec, {"X": other(t0, 0.95)}) == []                                   # the other way
    assert I.corroborate(rec, {"X": other(t0, 1.025)}) == []                                  # too small to count
    assert I.corroborate({**rec, "max_1m_move_signed": -0.07}, {"X": other(t0, 0.95)}) == ["X"]
    assert I.corroborate({**rec, "review_codes": ["stale_run"]}, {"X": other(t0, up)}) == []


# ---- the import -----------------------------------------------------------------------------------------------------
@pytest.fixture
def imported(tmp_path, reviewed_none):
    src = build_source(tmp_path / "src")
    man = run_import(src, tmp_path / "out", reviewed_none, version="v1")
    return src, tmp_path / "out", man, reviewed_none


def ds_of(out, man):
    return out / SRC.name / man["dataset"]


def test_import_writes_the_manifest_partitions_and_provenance(imported):
    src, out, man, _ = imported
    ds = ds_of(out, man)
    assert man["status"] == I.UNVERIFIED and man["tier"] == "T1b" and man["source"]["redistributable"] is False
    assert {f["symbol"] for f in man["source"]["files"]} == {"NIFTY", "BANKNIFTY", "INDIAVIX"}
    assert all(len(f["sha256"]) == 64 and f["bytes"] > 0 for f in man["source"]["files"])
    assert set(man["allowed_uses"]) == set(legacy.ALLOWED_USES) and man["not_for"] == legacy.FORBIDDEN_NOTE
    assert (ds / "manifest.json").is_file() and (ds / "quality.md").is_file() and (ds / "quality.json").is_file()
    assert len(man["sessions"]) == 15 and all(s["status"] == "accepted" for s in man["sessions"])
    assert set(man["code"]) == {"commit", "dirty"} and man["dataset"].startswith("ml-intake-2-")
    df = I.load(ds, ["NIFTY"], use="development_folds", allow_unverified=True)
    assert len(df) == 5 * 375 and set(df["tier"]) == {"T1b"} and set(df["symbol"]) == {"NIFTY"}
    assert list(df.columns) == ["ts", "open", "high", "low", "close", "volume", "symbol", "tier", "source_file"]
    assert df["ts"].is_monotonic_increasing and str(df["ts"].dt.tz) == IST
    assert df.attrs["digest"] == man["digest"] and df.attrs["status"] == I.UNVERIFIED and df.attrs["excluded_review"] == []
    for sym, fid in (("NIFTY", 0), ("BANKNIFTY", 1), ("INDIAVIX", 2)):                      # each row names the file it came from
        assert set(I.load(ds, [sym], use="development_folds", allow_unverified=True)["source_file"]) == {fid}
    s = man["sessions"][0]
    assert all(float(f"{s[k]:.12g}") == s[k] for k in ("rv", "max_1m_move"))                  # the validation numbers are 12 significant digits


def test_every_part_of_the_data_is_in_the_digest_and_the_bookkeeping_is_not(imported):
    _, _, man, _ = imported
    base = I.dataset_digest(man)
    assert base == man["digest"]

    def changed(fn):
        m = json.loads(json.dumps(man))
        fn(m)
        return I.dataset_digest(m)

    in_digest = {
        "a rule": lambda m: m["rules"].update(jump=0.06),
        "a session record": lambda m: m["sessions"][0].update(minutes=374),
        "the reviewed list": lambda m: m.update(reviewed_sha256="0" * 64),
        "a source file": lambda m: m["source"]["files"][0].update(sha256="1" * 64),
        "the source url": lambda m: m["source"].update(url="https://example.invalid/other"),
        "the licence": lambda m: m["source"].update(licence="MIT"),
        "a partition hash": lambda m: next(iter(m["partitions"].values())).update(sha256="2" * 64),
        "the importer version": lambda m: m.update(importer_version="ml-intake-9"),
        "the schema": lambda m: m.update(schema=99)}
    for what, fn in in_digest.items():
        assert changed(fn) != base, what
    not_in_digest = {
        "the status": lambda m: m.update(status=I.VERIFIED),
        "the import time": lambda m: m.update(imported_at="2000-01-01"),
        "the version label": lambda m: m["source"].update(version="another label"),
        "the code commit": lambda m: m.update(code={"commit": "deadbeef", "dirty": True})}
    for what, fn in not_in_digest.items():
        assert changed(fn) == base, what


def test_the_folder_identity_covers_the_files_the_rules_the_reviewed_list_and_the_sources_metadata(imported):
    _, _, man, _ = imported
    base = I.identity(man["source"], man["rules"], man["reviewed_sha256"])
    assert len(base) == 12 and base == man["dataset"].split("-")[-1]

    def with_(**kw):
        src = json.loads(json.dumps(man["source"]))
        src.update(kw)
        return I.identity(src, man["rules"], man["reviewed_sha256"])

    for what, other in (("name", with_(name="another")), ("url", with_(url="https://example.invalid/x")),
                        ("licence", with_(licence="MIT")), ("redistributable", with_(redistributable=True)),
                        ("rules", I.identity(man["source"], {**man["rules"], "jump": 0.06}, man["reviewed_sha256"])),
                        ("reviewed list", I.identity(man["source"], man["rules"], "0" * 64))):
        assert other != base, what
    assert with_(version="a label") == base                                                  # the version label is documentation
    reordered = json.loads(json.dumps(man["source"]))
    reordered["files"].reverse()
    assert I.identity(reordered, man["rules"], man["reviewed_sha256"]) == base              # the order the files are listed in is not content
    edited = json.loads(json.dumps(man["source"]))
    edited["files"][0]["sha256"] = "9" * 64
    assert I.identity(edited, man["rules"], man["reviewed_sha256"]) != base


def test_the_same_inputs_give_the_same_digest_anywhere(imported, tmp_path):
    src, out, man, reviewed = imported
    again = run_import(src, tmp_path / "elsewhere", reviewed, version="a different label")     # label is documentation
    assert again["digest"] == man["digest"] and again["dataset"] == man["dataset"]
    assert again["partitions"] == man["partitions"]
    same = run_import(src, out, reviewed, version="v1")                                           # idempotent in place
    assert same["digest"] == man["digest"]


def test_a_changed_source_file_is_a_different_dataset_not_an_overwrite(imported, tmp_path):
    src, out, man, reviewed = imported
    src2 = build_source(tmp_path / "src2", nifty=[make_day(d, 25000, 99 + i) for i, d in enumerate(DAYS)])
    other = run_import(src2, out, reviewed)
    assert other["dataset"] != man["dataset"] and other["digest"] != man["digest"]
    assert (ds_of(out, man) / "manifest.json").is_file()                                          # the first is untouched


def test_reimport_keeps_the_status_the_time_and_the_label_and_refuses_a_different_digest(imported):
    src, out, man, reviewed = imported
    mp = ds_of(out, man) / "manifest.json"
    m = json.loads(mp.read_text())
    m.update(status=I.VERIFIED, imported_at="2026-10-24 12:00:00+05:30")
    mp.write_text(json.dumps(m))
    again = run_import(src, out, reviewed, version="relabelled")
    assert again["status"] == I.VERIFIED and again["imported_at"] == "2026-10-24 12:00:00+05:30" and again["source"]["version"] == "v1"
    assert json.loads(mp.read_text())["status"] == I.VERIFIED
    m["digest"] = "f" * 64
    mp.write_text(json.dumps(m))
    with pytest.raises(legacy.ImmutableViolation, match="different digest"):
        run_import(src, out, reviewed)


def test_latest_is_the_newest_import_not_the_highest_folder_name(imported, tmp_path):
    src, out, man, reviewed = imported
    src2 = build_source(tmp_path / "src2", nifty=[make_day(d, 25000, 99 + i) for i, d in enumerate(DAYS)])
    other = run_import(src2, out, reviewed)
    older, newer = sorted([man, other], key=lambda m: m["dataset"])                                # name order: older sorts first
    for m, when in ((older, "2026-10-25 09:00:00+05:30"), (newer, "2026-10-24 09:00:00+05:30")):   # ...but was imported LATER
        mp = ds_of(out, m) / "manifest.json"
        doc = json.loads(mp.read_text())
        doc["imported_at"] = when
        mp.write_text(json.dumps(doc))
    assert I.latest(out, SRC).name == older["dataset"]
    assert I.latest(tmp_path / "nowhere", SRC) is None


def test_a_partition_that_no_longer_matches_makes_reimport_and_load_fail(imported):
    src, out, man, reviewed = imported
    ds = ds_of(out, man)
    victim = next(iter(sorted((ds / "1m").rglob("*.parquet"))))
    df = pd.read_parquet(victim)
    df.loc[0, "close"] += 1.0
    df.to_parquet(victim, index=False)
    with pytest.raises(legacy.ImmutableViolation):
        run_import(src, out, reviewed)
    with pytest.raises(legacy.ImmutableViolation, match="no longer hashes"):
        I.load(ds, ["NIFTY", "BANKNIFTY", "INDIAVIX"], use="development_folds", allow_unverified=True)


def test_a_partition_and_its_manifest_hash_edited_together_still_fails_the_digest(imported):
    """The auditor's case: change a partition and write its new hash into the manifest. The manifest no longer hashes to its own
    digest, and a spec that names the digest it was run on catches even a recomputed one."""
    _, out, man, _ = imported
    ds = ds_of(out, man)
    rel = next(iter(sorted(man["partitions"])))
    df = pd.read_parquet(ds / rel)
    df["close"] = df["close"] * 2
    df.to_parquet(ds / rel, index=False)
    mp = ds / "manifest.json"
    m = json.loads(mp.read_text())
    m["partitions"][rel]["sha256"] = I.canonical_hash(pd.read_parquet(ds / rel))
    mp.write_text(json.dumps(m))
    with pytest.raises(legacy.ImmutableViolation, match="does not hash to its own digest"):
        I.load(ds, ["NIFTY", "BANKNIFTY", "INDIAVIX"], use="development_folds", allow_unverified=True)
    m["digest"] = I.dataset_digest(m)                                                              # a careful forger recomputes the digest...
    mp.write_text(json.dumps(m))
    assert len(I.load(ds, ["NIFTY"], use="development_folds", allow_unverified=True)) > 0         # ...and load alone cannot tell,
    with pytest.raises(legacy.ImmutableViolation, match="is not the"):
        I.load(ds, ["NIFTY"], use="development_folds", allow_unverified=True, expected_digest=man["digest"])  # ...but the spec's digest can


def test_a_renamed_folder_or_an_edited_session_record_is_caught(imported, tmp_path):
    _, out, man, _ = imported
    ds = ds_of(out, man)
    moved = ds.parent / "ml-intake-2-000000000000"
    ds.rename(moved)
    with pytest.raises(legacy.ImmutableViolation, match="folder name"):
        I.load(moved, ["NIFTY"], use="development_folds", allow_unverified=True)
    moved.rename(ds)
    mp = ds / "manifest.json"
    m = json.loads(mp.read_text())
    m["sessions"][0]["status"] = "accepted_reviewed"
    mp.write_text(json.dumps(m))
    with pytest.raises(legacy.ImmutableViolation, match="own digest"):
        I.load(ds, ["NIFTY"], use="development_folds", allow_unverified=True)


def test_load_refuses_a_missing_or_extra_partition(imported):
    _, out, man, _ = imported
    ds = ds_of(out, man)
    extra = ds / "1m" / "symbol=NIFTY" / "year=1999.parquet"
    pd.read_parquet(next(iter((ds / "1m").rglob("*.parquet")))).to_parquet(extra, index=False)
    with pytest.raises(legacy.ImmutableViolation, match="differ from the manifest"):
        I.load(ds, ["NIFTY"], use="development_folds", allow_unverified=True)
    extra.unlink()
    next(iter(sorted((ds / "1m").rglob("*.parquet")))).unlink()
    with pytest.raises(legacy.ImmutableViolation, match="differ from the manifest"):
        I.load(ds, ["NIFTY"], use="development_folds", allow_unverified=True)


def test_load_refuses_without_a_manifest_unverified_data_and_forbidden_uses(imported, tmp_path):
    _, out, man, _ = imported
    ds = ds_of(out, man)
    with pytest.raises(legacy.ForbiddenUse, match="external_unverified"):
        I.load(ds, ["NIFTY"], use="development_folds")
    for use in ("option_pricing", "bid_ask", "profitability_claim", "paper_gate", "model_promotion", ""):
        with pytest.raises(legacy.ForbiddenUse, match="refused"):
            I.load(ds, ["NIFTY"], use=use, allow_unverified=True)
    empty = tmp_path / "no_manifest"
    (empty / "1m").mkdir(parents=True)
    with pytest.raises(legacy.ForbiddenUse, match="no manifest"):
        I.load(empty, ["NIFTY"], use="development_folds", allow_unverified=True)


def good_record(man, **over):
    """The record P0.6 writes when its pinned criteria pass for NIFTY and BANKNIFTY (the volatility index is not covered)."""
    rec = {"digest": man["digest"], "passed": True, "check": "p06-v1", "criteria_sha256": I.VERIFICATION_CRITERIA["p06-v1"],
           "symbols_verified": ["NIFTY", "BANKNIFTY"]}
    rec.update(over)
    return rec


def mark_verified(ds, rec):
    mp = ds / "manifest.json"
    m = json.loads(mp.read_text())
    m["status"] = I.VERIFIED
    mp.write_text(json.dumps(m))
    (ds / "verification.json").write_text(json.dumps(rec) if not isinstance(rec, str) else rec)
    return m


def test_verified_needs_a_verification_record_that_names_this_digest(imported):
    """The word 'external_verified' in a manifest is not evidence: P0.6 writes verification.json naming the digest it checked."""
    _, out, man, _ = imported
    ds = ds_of(out, man)
    mp = ds / "manifest.json"
    m = json.loads(mp.read_text())
    m["status"] = I.VERIFIED
    mp.write_text(json.dumps(m))
    with pytest.raises(legacy.ForbiddenUse, match="external_unverified"):                         # the word alone: refused
        I.load(ds, ["NIFTY"], use="regime_research")
    vp = ds / "verification.json"
    for rec in ({"digest": "0" * 64, **{k: v for k, v in good_record(man).items() if k != "digest"}},   # another dataset's record
                good_record(man, passed=False),                                                           # a failed check
                good_record(man, passed="no"),                                                            # truthy, but not a pass
                good_record(man, passed=1),
                {k: v for k, v in good_record(man).items() if k != "check"},                              # no named check
                good_record(man, check="yahoo-daily"),                                                    # a check this loader does not know
                good_record(man, check=["p06-v1"]),                                                       # not even a string
                ["digest", man["digest"]]):                                                               # not even an object
        vp.write_text(json.dumps(rec))
        with pytest.raises(legacy.ForbiddenUse, match="external_unverified"):
            I.load(ds, ["NIFTY"], use="regime_research")
    vp.write_text("not json")
    with pytest.raises(legacy.ForbiddenUse):
        I.load(ds, ["NIFTY"], use="regime_research")
    vp.write_text(json.dumps(good_record(man)))
    df = I.load(ds, ["NIFTY"], use="regime_research")                                              # a matching record: no opt-in needed, same uses only
    assert len(df) == 5 * 375 and df.attrs["status"] == I.VERIFIED
    with pytest.raises(legacy.ForbiddenUse, match="refused"):
        I.load(ds, ["NIFTY"], use="option_pricing")


def test_the_status_is_per_symbol_and_the_record_must_name_its_criteria(imported):
    """P0.6 checked NIFTY and BANKNIFTY only: the status never covers the volatility index, or a record without its scope and criteria."""
    _, out, man, _ = imported
    ds = ds_of(out, man)
    m = mark_verified(ds, good_record(man))
    assert I.load(ds, ["NIFTY", "BANKNIFTY"], use="regime_research").attrs["status"] == I.VERIFIED
    with pytest.raises(legacy.ForbiddenUse, match="external_unverified"):                          # a symbol the record does not cover
        I.load(ds, ["INDIAVIX"], use="regime_research")
    with pytest.raises(legacy.ForbiddenUse, match="external_unverified"):                          # one covered symbol does not carry the other
        I.load(ds, ["NIFTY", "INDIAVIX"], use="regime_research")
    assert I.load(ds, ["INDIAVIX"], use="regime_research", allow_unverified=True).attrs["status"] == I.UNVERIFIED     # allowed on request, and labelled
    assert I.effective_status(ds, m, ["NIFTY", "BANKNIFTY", "INDIAVIX"]) == I.UNVERIFIED          # the dataset as a whole holds INDIAVIX
    with pytest.raises(TypeError):                                                                 # `symbols` is required: there is no unscoped answer
        I.effective_status(ds, m)
    assert I.effective_status(ds, m, ["NIFTY"]) == I.VERIFIED
    assert I.effective_status(ds, m, "NIFTY") == I.VERIFIED                                        # a bare string is one symbol, not a set of letters
    assert I.effective_status(ds, m, ["NIFTY", "SENSEX"]) == I.UNVERIFIED
    assert I.effective_status(ds, m, []) == I.UNVERIFIED                                           # asking about nothing is not a verification


@pytest.mark.parametrize("override", [
    {"symbols_verified": None}, {"symbols_verified": []}, {"symbols_verified": "NIFTY"}, {"symbols_verified": ["NIFTY", ""]}, {"symbols_verified": ["NIFTY", 5]},
    {"criteria_sha256": None}, {"criteria_sha256": "0" * 64}, {"criteria_sha256": I.VERIFICATION_CRITERIA["p06-v1"].upper()},
    {"check": "p06-v2"}, {"check": ""}, {"passed": None},
])
def test_a_record_without_its_scope_or_with_other_criteria_verifies_nothing(imported, override):
    _, out, man, _ = imported
    ds = ds_of(out, man)
    rec = good_record(man)
    for k, v in override.items():
        if v is None and k in ("symbols_verified", "criteria_sha256"):
            del rec[k]                                                                             # a record without the field at all
        else:
            rec[k] = v
    m = mark_verified(ds, rec)
    assert I.effective_status(ds, m, ["NIFTY"]) == I.UNVERIFIED
    assert I.effective_status(ds, m, ["NIFTY", "BANKNIFTY", "INDIAVIX"]) == I.UNVERIFIED
    with pytest.raises(legacy.ForbiddenUse, match="external_unverified"):
        I.load(ds, ["NIFTY"], use="regime_research")


def test_a_hand_edited_manifest_status_does_not_make_a_record_verify_what_it_does_not_cover(imported):
    """The manifest status sits outside the digest, so anyone can edit it: only the record, tied to pinned criteria, counts."""
    _, out, man, _ = imported
    ds = ds_of(out, man)
    m = mark_verified(ds, good_record(man, symbols_verified=["NIFTY"]))
    assert I.effective_status(ds, m, ["NIFTY"]) == I.VERIFIED
    assert I.effective_status(ds, m, ["BANKNIFTY"]) == I.UNVERIFIED
    m["status"] = I.UNVERIFIED
    assert I.effective_status(ds, m, ["NIFTY"]) == I.UNVERIFIED                                     # a record cannot verify a manifest that says it is not


def test_the_pinned_criteria_hash_is_the_hash_of_the_criteria_file():
    """The pin is the sha256 of docs/ml/P0_6_criteria.md as merged: a changed criteria file is a new check name, added by a reviewed change."""
    import hashlib
    f = REPO / "docs" / "ml" / "P0_6_criteria.md"
    assert f.exists(), "the criteria file must be committed before the loader pins it"
    assert hashlib.sha256(f.read_bytes()).hexdigest() == I.VERIFICATION_CRITERIA["p06-v1"]


def test_load_refuses_a_bare_string_unknown_or_empty_symbol_lists(imported):
    _, out, man, _ = imported
    ds = ds_of(out, man)
    with pytest.raises(ValueError, match="not one string"):
        I.load(ds, "NIFTY", use="development_folds", allow_unverified=True)
    for bad in (["NIFTYX"], ["NIFTY", "SENSEX"]):
        with pytest.raises(ValueError, match="is not in"):
            I.load(ds, bad, use="development_folds", allow_unverified=True)
    for twice in (["NIFTY", "NIFTY"], ["NIFTY", "BANKNIFTY", "NIFTY"]):
        with pytest.raises(ValueError, match="repeats a symbol"):
            I.load(ds, twice, use="development_folds", allow_unverified=True)
    for empty in ([], (), iter([]), pd.Index([])):
        with pytest.raises(ValueError, match="non-empty"):
            I.load(ds, empty, use="development_folds", allow_unverified=True)


def test_a_missing_source_file_or_one_that_is_not_the_format_stops_the_import(tmp_path, reviewed_none):
    src = build_source(tmp_path / "src")
    (src / "VIX.csv").unlink()
    with pytest.raises(I.SourceFormatError, match="VIX.csv"):
        run_import(src, tmp_path / "out", reviewed_none)
    src = build_source(tmp_path / "src2")
    t = pd.read_csv(src / "NIFTY.csv")
    t["date"] = t["date"] + "+05:30"                                                               # every date now unparsable
    t.to_csv(src / "NIFTY.csv", index=False)
    with pytest.raises(I.SourceFormatError, match="unparsable"):
        run_import(src, tmp_path / "out2", reviewed_none)
    src = build_source(tmp_path / "src3")
    (src / "BANKNIFTY.csv").write_text("date,open,high,low,close,volume\n")                        # header only
    with pytest.raises(I.SourceFormatError, match="0 of 0 rows|unparsable"):
        run_import(src, tmp_path / "out3", reviewed_none)
    src = build_source(tmp_path / "src4", vix=[make_day(DAYS[0], 15, 1, n=100)])                   # parses, but not one session passes
    with pytest.raises(I.SourceFormatError, match="not one session passes"):
        run_import(src, tmp_path / "out4", reviewed_none)


def test_bad_sessions_are_kept_out_of_the_partitions_and_say_why(tmp_path, reviewed_none):
    nifty = [make_day(DAYS[0], 25000, 0), make_day(DAYS[1], 25000, 1, n=200),                    # short (and so truncated)
             make_day(SAT, 25000, 2),                                                              # a full Saturday: review
             make_stale(make_day(DAYS[3], 25000, 3), 100, 30),                                    # frozen: review
             make_day(DAYS[4], 25000, 4)]
    src = build_source(tmp_path / "src", nifty=nifty)
    man = run_import(src, tmp_path / "out", reviewed_none)
    by_day = {s["day"]: s for s in man["sessions"] if s["symbol"] == "NIFTY"}
    assert {d: s["status"] for d, s in by_day.items()} == {
        DAYS[0]: "accepted", DAYS[1]: "rejected", SAT: "review", DAYS[3]: "review", DAYS[4]: "accepted"}
    ds = ds_of(tmp_path / "out", man)
    got = I.load(ds, ["NIFTY"], use="development_folds", allow_unverified=True)
    assert sorted({str(t.date()) for t in got["ts"]}) == [DAYS[0], DAYS[4]]
    assert got.attrs["excluded_review"] == [f"NIFTY {DAYS[3]}", f"NIFTY {SAT}"]                  # a consumer is told what was left out
    q = json.loads((ds / "quality.json").read_text())
    assert [(r["day"], r["rv_of"]) for r in q["review_queue"] if r["symbol"] == "NIFTY"] == [(DAYS[3], 4), (SAT, 4)]
    assert all(1 <= r["rv_rank"] <= r["rv_of"] for r in q["review_queue"])
    assert q["by_symbol"]["NIFTY"]["rejected_by_code"] == {"short_session": 1, "truncated": 1}
    dis = q["index_disagreements"]                                   # the indices must agree about a day; where they don't, say so
    assert dis["count"] == 4 and [r["day"] for r in dis["first"]] == [DAYS[1], DAYS[2], DAYS[3], SAT]
    assert dis["first"][0]["NIFTY"] == "rejected" and dis["first"][0]["BANKNIFTY"] == "accepted"
    assert dis["first"][1]["NIFTY"] == "absent" and dis["first"][3]["BANKNIFTY"] == "absent"      # no NIFTY row on the 3rd; no BANKNIFTY on the Saturday
    md = (ds / "quality.md").read_text()
    assert "Days the indices disagree about (4" in md and "The default set excludes 2 sessions in review" in md
    assert "Volume is not used" in md and "realised-variance rank" in md and "highest-variance of them is NIFTY" in md
    assert "A study on the default set is censored at the tail until a reviewer admits them" in md


def test_the_rows_dropped_in_a_session_include_an_unparsable_number_on_a_dated_row(tmp_path, reviewed_none):
    src = build_source(tmp_path / "src")
    t = pd.read_csv(src / "NIFTY.csv", dtype=str)
    t.loc[5, "high"] = "abc"                                                                       # one unparsable number on 2024-01-01
    t.loc[6, "open"] = "-1"                                                                        # one bad price
    t.to_csv(src / "NIFTY.csv", index=False)
    man = run_import(src, tmp_path / "out", reviewed_none)
    s = next(x for x in man["sessions"] if x["symbol"] == "NIFTY" and x["day"] == DAYS[0])
    assert s["rows_dropped"] == 2 and s["minutes"] == 373 and s["status"] == "accepted"


def test_a_jump_seen_by_both_indices_is_corroborated_and_a_lone_one_is_not(tmp_path, reviewed_none):
    nifty = [jumped(make_day(DAYS[0], 25000, 0)), jumped(make_day(DAYS[1], 25000, 1)), make_day(DAYS[2], 25000, 2)]
    bank = [jumped(make_day(DAYS[0], 50000, 10)), make_day(DAYS[1], 50000, 11), jumped(make_day(DAYS[2], 50000, 12), 0.93)]
    vix = [jumped(make_day(DAYS[0], 15, 20)), jumped(make_day(DAYS[1], 15, 21)), make_day(DAYS[2], 15, 22)]   # the VIX is allowed to jump
    src = build_source(tmp_path / "src", nifty=nifty, bank=bank, vix=vix)
    man = run_import(src, tmp_path / "out", reviewed_none)
    got = {(s["symbol"], s["day"]): s for s in man["sessions"]}
    assert got[("NIFTY", DAYS[0])]["corroborated_by"] == ["BANKNIFTY"] and got[("BANKNIFTY", DAYS[0])]["corroborated_by"] == ["NIFTY"]
    assert got[("NIFTY", DAYS[1])]["status"] == "review" and got[("NIFTY", DAYS[1])]["corroborated_by"] == []
    assert got[("BANKNIFTY", DAYS[2])]["corroborated_by"] == []                        # the other index did not move
    for d in DAYS[:2]:                                                                  # the volatility index has no jump rule, and is not
        assert got[("INDIAVIX", d)]["status"] == "accepted" and got[("INDIAVIX", d)]["max_1m_move"] > 0.05   # evidence for the indices


# ---- the reviewed list ----------------------------------------------------------------------------------------------
def stale_source(tmp_path):
    nifty = [make_day(DAYS[0], 25000, 0), make_stale(make_day(DAYS[1], 25000, 1), 100, 30), make_day(SAT, 25000, 2)]
    return build_source(tmp_path / "src", nifty=nifty)


BOTH = ["stale_run", "stale_share"]                      # a 30-bar freeze trips both rules


def test_a_reviewed_entry_admits_a_review_session_and_changes_the_dataset_identity(tmp_path, reviewed_none):
    src = stale_source(tmp_path)
    base = run_import(src, tmp_path / "out", reviewed_none)
    rv = reviewed_file(tmp_path, [entry(base, "NIFTY", DAYS[1], BOTH)])
    adm = run_import(src, tmp_path / "out", rv)
    st = {s["day"]: s["status"] for s in adm["sessions"] if s["symbol"] == "NIFTY"}
    assert st[DAYS[1]] == "accepted_reviewed" and adm["reviewed_applied"] == [f"NIFTY {DAYS[1]}"] and adm["reviewed_not_applied"] == []
    assert adm["dataset"] != base["dataset"] and adm["digest"] != base["digest"] and adm["reviewed_sha256"] != base["reviewed_sha256"]
    got = I.load(ds_of(tmp_path / "out", adm), ["NIFTY"], use="development_folds", allow_unverified=True)
    assert DAYS[1] in {str(t.date()) for t in got["ts"]} and got.attrs["admitted_reviewed"] == [f"NIFTY {DAYS[1]}"]
    rec = next(s for s in adm["sessions"] if s["day"] == DAYS[1] and s["symbol"] == "NIFTY")["reviewed"]
    assert rec == {"by": "A. Reviewer", "on": "2026-10-25", "evidence": EVIDENCE}


def test_a_budget_saturday_can_be_admitted_and_is_otherwise_left_out(tmp_path, reviewed_none):
    src = stale_source(tmp_path)
    base = run_import(src, tmp_path / "out", reviewed_none)
    sat = next(s for s in base["sessions"] if s["symbol"] == "NIFTY" and s["day"] == SAT)
    assert sat["status"] == "review" and sat["review_codes"] == ["weekend_full"]
    adm = run_import(src, tmp_path / "out", reviewed_file(tmp_path, [entry(base, "NIFTY", SAT, ["weekend_full"])]))
    assert next(s for s in adm["sessions"] if s["symbol"] == "NIFTY" and s["day"] == SAT)["status"] == "accepted_reviewed"


def test_a_reviewed_entry_must_cover_every_code_the_session_trips(tmp_path, reviewed_none):
    """The 2020-03-13 sessions trip two rules. An entry that names only one of them does not admit the session."""
    src = stale_source(tmp_path)
    base = run_import(src, tmp_path / "out", reviewed_none)
    for codes in (["stale_run"], ["stale_share"], ["weekend_full", "stale_run"]):                  # one of two; or overlap that misses one
        e = entry(base, "NIFTY", DAYS[1], codes) if set(codes) <= {"stale_run", "stale_share"} else \
            {**entry(base, "NIFTY", DAYS[1], ["stale_run"]), "codes": codes,
             "observed": {"longest_stale_run": 30, "minutes": 375}}
        man = run_import(src, tmp_path / "out", reviewed_file(tmp_path, [e], name=f"rv_{'_'.join(codes)}.json"))
        assert next(s for s in man["sessions"] if s["symbol"] == "NIFTY" and s["day"] == DAYS[1])["status"] == "review", codes
        assert man["reviewed_not_applied"][0]["why"].startswith("the entry covers")


def test_a_reviewed_entry_is_bound_to_the_file_and_the_facts_it_was_reviewed_on(tmp_path, reviewed_none):
    src = stale_source(tmp_path)
    base = run_import(src, tmp_path / "out", reviewed_none)
    wrong_file = entry(base, "NIFTY", DAYS[1], BOTH, file_sha256="a" * 64)
    wrong_fact = entry(base, "NIFTY", DAYS[1], BOTH)
    wrong_fact["observed"]["longest_stale_run"] = 29
    for e, why in ((wrong_file, "not the one that was reviewed"), (wrong_fact, "not the ones that were reviewed")):
        man = run_import(src, tmp_path / "out", reviewed_file(tmp_path, [e], name="rv_b.json"))
        assert next(s for s in man["sessions"] if s["symbol"] == "NIFTY" and s["day"] == DAYS[1])["status"] == "review"
        assert why in man["reviewed_not_applied"][0]["why"]
    # the same entry, kept, against a source where the same day now has a 200% move instead of a freeze
    jump_src = build_source(tmp_path / "src_j", nifty=[make_day(DAYS[0], 25000, 0), jumped(make_day(DAYS[1], 25000, 1), 1.07),
                                                         make_day(SAT, 25000, 2)])
    jbase = run_import(jump_src, tmp_path / "out_j", reviewed_none)
    e = entry(jbase, "NIFTY", DAYS[1], ["jump"])
    big = build_source(tmp_path / "src_big", nifty=[make_day(DAYS[0], 25000, 0), jumped(make_day(DAYS[1], 25000, 1), 3.0),
                                                      make_day(SAT, 25000, 2)])
    man = run_import(big, tmp_path / "out_j2", reviewed_file(tmp_path, [e], name="rv_j.json"))
    assert next(s for s in man["sessions"] if s["symbol"] == "NIFTY" and s["day"] == DAYS[1])["status"] == "review"
    assert "source file" in man["reviewed_not_applied"][0]["why"]            # a changed file is caught before its facts are compared


def test_a_reviewed_entry_cannot_admit_a_hard_rejection_and_unused_ones_are_reported(tmp_path, reviewed_none):
    nifty = [make_day(DAYS[0], 25000, 0), make_day(DAYS[1], 25000, 1, n=200), make_day(SAT, 25000, 2)]
    src = build_source(tmp_path / "src", nifty=nifty)
    base = run_import(src, tmp_path / "out", reviewed_none)
    ghost = {**entry(base, "NIFTY", SAT, ["weekend_full"]), "day": "2031-01-01"}
    short = {**entry(base, "NIFTY", SAT, ["weekend_full"]), "day": DAYS[1]}                      # the short session: rejected, not in review
    man = run_import(src, tmp_path / "out", reviewed_file(tmp_path, [short, ghost]))
    st = {s["day"]: s["status"] for s in man["sessions"] if s["symbol"] == "NIFTY"}
    assert st[DAYS[1]] == "rejected" and man["reviewed_applied"] == []
    assert man["reviewed_unused"] == ["NIFTY 2031-01-01"] and "rejected" in man["reviewed_not_applied"][0]["why"]
    md = (ds_of(tmp_path / "out", man) / "quality.md").read_text()
    assert "did not apply" in md and "2031-01-01" in md


def good_entry():
    return {"symbol": "NIFTY", "day": "2024-01-02", "codes": ["jump"], "decision": "admit", "evidence": EVIDENCE,
            "reviewer": "A. Reviewer", "date": "2026-10-25", "file_sha256": "b" * 64, "observed": {"max_1m_move_at": "x"}}


@pytest.mark.parametrize("change, why", [
    ({"evidence": "looks fine to me"}, "too thin"),
    ({"evidence": "x" * 60}, "too thin"),                                              # long enough, but one word
    ({"codes": [], "observed": {}}, "decision must be"),
    ({"codes": ["weekend"]}, "decision must be"),
    ({"decision": "maybe"}, "decision must be"),
    ({"reviewer": "  "}, "no reviewer"),
    ({"day": "20240102"}, "YYYY-MM-DD"),
    ({"day": "02/01/2024"}, "YYYY-MM-DD"),
    ({"date": "yesterday"}, "YYYY-MM-DD"),
    ({"file_sha256": "abc"}, "sha256"),
    ({"observed": {}}, "observed must hold"),
    ({"observed": {"max_1m_move_at": "x", "extra": 1}}, "observed must hold")])
def test_a_malformed_reviewed_entry_is_an_error_never_skipped(tmp_path, change, why):
    with pytest.raises(I.ReviewedListError, match=why):
        I.load_reviewed(reviewed_file(tmp_path, [{**good_entry(), **change}]))


def test_missing_fields_duplicates_and_wrong_schema_are_errors(tmp_path):
    e = good_entry()
    with pytest.raises(I.ReviewedListError, match="lacks"):
        I.load_reviewed(reviewed_file(tmp_path, [{k: v for k, v in e.items() if k != "reviewer"}]))
    with pytest.raises(I.ReviewedListError, match="twice"):
        I.load_reviewed(reviewed_file(tmp_path, [e, dict(e)]))
    for schema in (1, 3):
        with pytest.raises(I.ReviewedListError, match="schema 2"):
            I.load_reviewed(reviewed_file(tmp_path, [], schema=schema))
    assert I.load_reviewed(reviewed_file(tmp_path, [e]))[0] == {("NIFTY", "2024-01-02"): e}


def test_the_committed_reviewed_list_parses():
    entries, sha = I.load_reviewed()
    assert len(sha) == 64 and isinstance(entries, dict)


# ---- the canonical hash ---------------------------------------------------------------------------------------------
def test_canonical_hash_ignores_representation_and_sees_every_change():
    base = make_day(DAYS[0], n=20).assign(symbol="NIFTY", tier="T1b")
    h = I.canonical_hash(base)
    ns = base.assign(ts=base["ts"].dt.as_unit("ns"))
    us = base.assign(ts=base["ts"].dt.as_unit("us"))
    assert I.canonical_hash(ns) == I.canonical_hash(us) == h                              # the datetime unit does not matter
    assert I.canonical_hash(base.assign(symbol=base["symbol"].astype(object))) == h        # nor does the string dtype
    z = base.copy()
    z.loc[0, "low"], z.loc[1, "low"] = 0.0, -0.0
    z2 = z.copy()
    z2.loc[1, "low"] = 0.0
    assert I.canonical_hash(z) == I.canonical_hash(z2)                                     # -0.0 is 0.0
    n1, n2 = base.copy(), base.copy()
    n1.loc[3, "close"] = np.nan
    n2.loc[3, "close"] = float("nan")
    assert I.canonical_hash(n1) == I.canonical_hash(n2) != h
    ch = base.copy()
    ch.loc[5, "close"] += 0.01
    assert I.canonical_hash(ch) != h                                                       # a value
    assert I.canonical_hash(base.iloc[::-1].reset_index(drop=True)) != h                   # row order
    assert I.canonical_hash(base[list(reversed(base.columns))]) != h                       # column order
    assert I.canonical_hash(base.rename(columns={"close": "settle"})) != h                 # a column name
    assert I.canonical_hash(base.iloc[:-1]) != h                                           # a row count
    assert I.canonical_hash(base.assign(tier="T1")) != h                                   # provenance


def test_canonical_hash_does_not_confuse_kinds_zones_or_string_boundaries():
    for left, right in ((["ab", "c"], ["a", "bc"]), (["a\x00b", "c"], ["a", "b\x00c"]), ([""," x"], [" ", "x"])):
        assert I.canonical_hash(pd.DataFrame({"s": left})) != I.canonical_hash(pd.DataFrame({"s": right})), (left, right)   # a boundary cannot move
    ts = pd.DataFrame({"ts": make_day(DAYS[0], n=5)["ts"]})
    assert I.canonical_hash(ts) != I.canonical_hash(ts.assign(ts=ts["ts"].dt.tz_convert("UTC")))     # same instants, another zone
    assert I.canonical_hash(pd.DataFrame({"x": [True, False]})) != I.canonical_hash(pd.DataFrame({"x": [1, 0]}))
    assert I.canonical_hash(pd.DataFrame({"x": [True, False]})) != I.canonical_hash(pd.DataFrame({"x": ["True", "False"]}))
    assert I.canonical_hash(pd.DataFrame({"x": np.array([1, 2], dtype="int32")})) == I.canonical_hash(
        pd.DataFrame({"x": np.array([1, 2], dtype="int64")}))                              # width is representation, not content


# ---- review round 2 --------------------------------------------------------------------------------------------------
def test_a_day_that_is_end_labelled_inside_a_start_labelled_file_is_rejected(tmp_path, reviewed_none):
    """The whole-file check cannot see a file that mixes labellings: three start-labelled days outnumber two shifted ones."""
    v = check(make_day(DAYS[0], first=(9, 16)))
    assert v["status"] == "rejected" and "end_labelled" in v["hard_codes"] and v["head_gap_min"] == 1
    assert "looks end-labelled" in " ".join(v["reasons"])
    nifty = [make_day(DAYS[0], 25000, 0), make_day(DAYS[1], 25000, 1), make_day(DAYS[2], 25000, 2),
             make_day(DAYS[3], 25000, 3, first=(9, 16)), make_day(DAYS[4], 25000, 4, first=(9, 16))]
    man = run_import(build_source(tmp_path / "src", nifty=nifty), tmp_path / "out", reviewed_none)       # the file-level guard passes
    st = {s["day"]: (s["status"], s["hard_codes"]) for s in man["sessions"] if s["symbol"] == "NIFTY"}
    assert [st[d][0] for d in DAYS] == ["accepted"] * 3 + ["rejected"] * 2
    assert all("end_labelled" in st[d][1] for d in DAYS[3:])


def test_load_takes_any_iterable_of_symbols_and_never_silently_returns_nothing(imported):
    _, out, man, _ = imported
    ds = ds_of(out, man)
    gen = I.load(ds, (s for s in ["NIFTY", "BANKNIFTY"]), use="development_folds", allow_unverified=True)
    assert set(gen["symbol"]) == {"NIFTY", "BANKNIFTY"} and len(gen) == 2 * 5 * 375
    assert len(I.load(ds, pd.Index(["NIFTY"]), use="development_folds", allow_unverified=True)) == 5 * 375
    assert len(I.load(ds, ("NIFTY",), use="development_folds", allow_unverified=True)) == 5 * 375


def test_what_load_reports_comes_from_what_the_digest_covers_and_is_filtered_by_symbol(tmp_path, reviewed_none):
    src = stale_source(tmp_path)
    base = run_import(src, tmp_path / "out", reviewed_none)
    adm = run_import(src, tmp_path / "out", reviewed_file(tmp_path, [entry(base, "NIFTY", DAYS[1], BOTH)]))
    ds = ds_of(tmp_path / "out", adm)
    nifty = I.load(ds, ["NIFTY"], use="development_folds", allow_unverified=True)
    bank = I.load(ds, ["BANKNIFTY"], use="development_folds", allow_unverified=True)
    assert nifty.attrs["admitted_reviewed"] == [f"NIFTY {DAYS[1]}"] and nifty.attrs["excluded_review"] == [f"NIFTY {SAT}"]
    assert bank.attrs["admitted_reviewed"] == [] and bank.attrs["excluded_review"] == []         # only the symbols that were asked for
    mp = ds / "manifest.json"
    m = json.loads(mp.read_text())
    m.update(tier="T1", reviewed_applied=["BANKNIFTY 2020-03-13"], allowed_uses=["everything"], not_for="nothing")   # outside the digest
    mp.write_text(json.dumps(m))
    again = I.load(ds, ["BANKNIFTY"], use="development_folds", allow_unverified=True)
    assert again.attrs["tier"] == "T1b" and again.attrs["admitted_reviewed"] == [] and again.attrs["not_for"] == legacy.FORBIDDEN_NOTE
    assert again.attrs["dataset"] == ds.name and set(again["tier"]) == {"T1b"}


def test_the_review_queue_ranks_by_realised_variance_largest_first(tmp_path, reviewed_none):
    nifty = [make_day(DAYS[0], 25000, 0), make_day(DAYS[1], 25000, 1), jumped(make_day(DAYS[2], 25000, 2), 1.07),
             steady_day(1.0, day=SAT)]                                    # the Saturday has almost no variance at all
    man = run_import(build_source(tmp_path / "src", nifty=nifty), tmp_path / "out", reviewed_none)
    ranks = {r["day"]: (r["rv_rank"], r["rv_of"]) for r in I.quality(man)["review_queue"] if r["symbol"] == "NIFTY"}
    assert ranks == {DAYS[2]: (1, 4), SAT: (4, 4)}
    rv = {s["day"]: s["rv"] for s in man["sessions"] if s["symbol"] == "NIFTY"}
    assert rv[DAYS[2]] > rv[DAYS[0]] > rv[SAT] and rv[SAT] > 0


def test_the_code_commit_records_whether_the_tree_was_dirty(monkeypatch):
    def fake(dirty, fail=False):
        def run(cmd, **kw):
            if fail:
                raise OSError("no git")
            return subprocess.CompletedProcess(cmd, 0, stdout="abc123\n" if "rev-parse" in cmd else (" M x.py\n" if dirty else ""), stderr="")
        return run
    monkeypatch.setattr(I.subprocess, "run", fake(True))
    assert I.code_commit() == {"commit": "abc123", "dirty": True}
    monkeypatch.setattr(I.subprocess, "run", fake(False))
    assert I.code_commit() == {"commit": "abc123", "dirty": False}
    monkeypatch.setattr(I.subprocess, "run", fake(False, fail=True))
    assert I.code_commit() == {"commit": None, "dirty": None}


def test_the_unparsable_share_bound_is_one_percent(tmp_path, reviewed_none):
    def source_with(k, name):
        src = build_source(tmp_path / name, nifty=[make_day(DAYS[0], 25000, 0), make_day(DAYS[1], 25000, 1)])          # 750 rows
        t = pd.read_csv(src / "NIFTY.csv", dtype=str)
        t.loc[list(range(100, 100 + k)), "close"] = "oops"
        t.to_csv(src / "NIFTY.csv", index=False)
        return src
    ok = run_import(source_with(7, "s7"), tmp_path / "o7", reviewed_none)                                             # 0.93%: imports
    assert next(f for f in ok["source"]["files"] if f["symbol"] == "NIFTY")["unparsed"] == 7
    with pytest.raises(I.SourceFormatError, match="unparsable"):
        run_import(source_with(8, "s8"), tmp_path / "o8", reviewed_none)                                              # 1.07%: stops


def test_exactly_one_percent_unparsable_still_imports(tmp_path, reviewed_none):
    """The bound is 'more than 1%': 8 unparsable rows of exactly 800 is 1.000% and imports; the earlier test has 7/750 and 8/750."""
    day0 = pd.concat([make_day(DAYS[0], 25000, 0), make_day(DAYS[0], 25000, 9, n=50, first=(15, 30))])        # 50 after-hours rows
    src = build_source(tmp_path / "src", nifty=[day0, make_day(DAYS[1], 25000, 1)])                            # 375 + 50 + 375 = 800 rows
    t = pd.read_csv(src / "NIFTY.csv", dtype=str)
    t.loc[list(range(100, 108)), "close"] = "oops"
    t.to_csv(src / "NIFTY.csv", index=False)
    man = run_import(src, tmp_path / "out", reviewed_none)
    f = next(f for f in man["source"]["files"] if f["symbol"] == "NIFTY")
    assert (f["rows_in"], f["unparsed"]) == (800, 8) and f["unparsed"] / f["rows_in"] == I.MAX_UNPARSED_SHARE


def test_the_stale_share_is_of_the_bars_the_session_has_not_of_375():
    d = make_day(DAYS[0]).drop(index=range(150, 165)).reset_index(drop=True)                                          # 360 minutes
    d = make_stale(make_stale(d, 20, 5), 60, 6)                                                                       # 11 stale bars
    v = check(d)
    assert v["minutes"] == 360 and v["stale_bars"] == 11 and v["longest_stale_run"] == 6
    assert v["review_codes"] == ["stale_share"]                                                                       # 3.06% of 360; 2.93% of 375


def test_the_quality_report_counts_the_minutes_dropped_for_conflicts_and_the_repeats_collapsed(tmp_path, reviewed_none):
    d = make_day(DAYS[0], 25000, 0)
    clash = d.iloc[[20]].copy()
    clash[["open", "high", "low", "close"]] = [1.0, 2.0, 0.5, 1.5]
    nifty = [pd.concat([d, clash, d.iloc[[40]]]).reset_index(drop=True)] + [make_day(x, 25000, i + 1) for i, x in enumerate(DAYS[1:])]
    man = run_import(build_source(tmp_path / "src", nifty=nifty), tmp_path / "out", reviewed_none)
    b = I.quality(man)["by_symbol"]["NIFTY"]
    assert b["conflicting_duplicate_minutes"] == 1 and b["identical_duplicate_rows"] == 1
    assert "two different bars in one minute: 1 (identical repeats collapsed: 1)" in I.render_quality(I.quality(man), man)


# ---- the phase-0 boundary -------------------------------------------------------------------------------------------
LIVE_PACKAGES = {"intraday", "engine", "execution", "journal", "risk", "learnbot", "web", "ops", "strategies", "backtest"}


def test_the_ml_package_never_imports_the_live_engine():
    """ML_PHASE0.md: Phase 0 is offline and read-only: it does not import the live engine, write to a journal, place or size
    anything, or use a secret. Checked on the source of every module in quantdesk/ml (imports inside functions included), and
    on what actually gets loaded when the package is imported, which catches an import that reaches the engine indirectly."""
    root = Path(I.__file__).parent
    found = []
    for py in sorted(root.glob("*.py")):
        for node in ast.walk(ast.parse(py.read_text())):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                base = ("quantdesk." if node.level == 0 else "quantdesk.ml." if node.level == 1 else "quantdesk.") + (node.module or "")
                names = [base] + [f"{base}.{a.name}" for a in node.names]
            for n in names:
                parts = n.split(".")
                if len(parts) > 1 and parts[0] == "quantdesk" and parts[1] in LIVE_PACKAGES:
                    found.append(f"{py.name}: {n}")
    assert not found, found
    out = subprocess.run([sys.executable, "-c", "import sys, quantdesk.ml.intake; print('\\n'.join(sorted(sys.modules)))"],
                         cwd=REPO, capture_output=True, text=True, check=True).stdout.split()
    loaded = [m for m in out if m.startswith("quantdesk.") and m.split(".")[1] in LIVE_PACKAGES]
    assert not loaded, loaded
    assert not {"requests", "yfinance", "anthropic"} & set(out)                             # no network client either


# ---- the command ----------------------------------------------------------------------------------------------------
def kaggle_source(root):
    for fname, start, seed in (("NIFTY 50_minute.csv", 25000, 0), ("NIFTY BANK_minute.csv", 50000, 10), ("INDIA VIX_minute.csv", 15, 20)):
        write_csv(root / fname, [make_day(d, start, seed + i) for i, d in enumerate(DAYS)])
    return root


def test_the_cli_imports_and_reports_and_bad_input_exits_cleanly(tmp_path, capsys, reviewed_none):
    from quantdesk.cli import main
    src = kaggle_source(tmp_path / "kaggle")
    main(["ml", "import", "--source", str(src), "--out", str(tmp_path / "out"), "--version", "18", "--reviewed", str(reviewed_none)])
    line = capsys.readouterr().out.strip().splitlines()[-1]
    assert "status external_unverified" in line and "'accepted': 15" in line and "quality.md" in line
    ds = I.latest(tmp_path / "out")
    assert ds is not None and len(I.load(ds, ["NIFTY", "BANKNIFTY", "INDIAVIX"], use="development_folds", allow_unverified=True)) == 15 * 375
    ghost = reviewed_file(tmp_path, [{**good_entry(), "day": "2031-01-01"}], name="ghost.json")
    main(["ml", "import", "--source", str(src), "--out", str(tmp_path / "out_g"), "--reviewed", str(ghost)])
    assert "reviewed entry matches no session: NIFTY 2031-01-01" in capsys.readouterr().out
    (src / "INDIA VIX_minute.csv").unlink()
    with pytest.raises(SystemExit, match="ml import: INDIA VIX_minute.csv is missing"):
        main(["ml", "import", "--source", str(src), "--out", str(tmp_path / "out2"), "--reviewed", str(reviewed_none)])
    broken = tmp_path / "broken.json"
    broken.write_text("{ not json")
    with pytest.raises(SystemExit, match="ml import"):
        main(["ml", "import", "--source", str(src), "--out", str(tmp_path / "out3"), "--reviewed", str(broken)])
    with pytest.raises(SystemExit, match="ml import"):
        main(["ml", "import", "--source", str(src), "--out", str(tmp_path / "out4"), "--reviewed", str(tmp_path / "missing.json")])


def test_a_deeply_nested_record_is_unverified_not_a_crash(imported):
    _, out, man, _ = imported
    ds = ds_of(out, man)
    m = mark_verified(ds, "[" * 200000)
    assert I.effective_status(ds, m, ["NIFTY"]) == I.UNVERIFIED
