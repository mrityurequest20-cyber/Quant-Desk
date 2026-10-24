"""P0.2: the external index-minute importer (quantdesk/ml/intake.py): parsing, the timestamp bound, the session rules, the review
queue and its reviewed list, determinism, immutability, integrity at load, use restrictions, and that the ML package never
reaches into the live engine."""
import ast
import datetime as dt
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from quantdesk.data import external_aeron as legacy
from quantdesk.ml import intake as I

IST = I.IST
DAYS = ["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"]      # Monday to Friday


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


@pytest.fixture
def reviewed_none(tmp_path):
    p = tmp_path / "reviewed.json"
    p.write_text(json.dumps({"schema": 1, "sessions": []}))
    return p


def run_import(src_dir, out_dir, reviewed, **kw):
    return I.import_source(src_dir, out_dir, SRC, reviewed_path=reviewed, say=None, **kw)


# ---- reading --------------------------------------------------------------------------------------------------------
def test_read_floors_small_second_offsets_and_drops_ambiguous_ones(tmp_path):
    p = tmp_path / "x.csv"
    p.write_text("date,open,high,low,close,volume\n"
                 "2024-01-01 09:15:00,100,101,99,100.5,0\n"
                 "2024-01-01 09:16:01,100.5,101,100,100.8,0\n"            # 1 s past: floored
                 "2024-01-01 09:17:15,100.8,101,100,100.9,0\n"            # exactly the bound: floored
                 "2024-01-01 09:18:16,100.9,101,100,100.7,0\n")           # beyond it: dropped, not guessed
    df, rep, _ = I.read_minutes(p, "NIFTY")
    assert [t.strftime("%H:%M:%S") for t in df["ts"]] == ["09:15:00", "09:16:00", "09:17:00"]
    assert rep["floored_seconds"] == 2 and rep["ambiguous_timestamp"] == 1 and rep["unparsed"] == 0
    assert str(df["ts"].dt.tz) == IST


def test_read_drops_and_counts_each_kind_of_bad_row(tmp_path):
    p = tmp_path / "x.csv"
    p.write_text("date,open,high,low,close,volume\n"
                 "2024-01-01 09:15:00,100,101,99,100.5,0\n"
                 "garbage,1,2,3,4,0\n"                                    # unparsable date
                 "2024-01-01 09:17:00,100,abc,99,100,0\n"                 # unparsable price
                 "2024-01-01 09:18:00,100,inf,99,100,0\n"                 # non-finite
                 "2024-01-01 09:19:00,100,99,101,100,0\n"                 # high < low
                 "2024-01-01 09:20:00,0,1,0,1,0\n"                        # non-positive
                 "2024-01-01 09:21:00,100,101,99,102,0\n"                 # close above high
                 "2024-01-01 09:22:00,100,101,99,100,-5\n"                # negative volume
                 "2024-01-01 09:23:00,100,101,99,100,2.5\n"               # fractional volume
                 "2024-01-01 09:24:00,100,101,99,100,7\n")
    df, rep, per_day = I.read_minutes(p, "NIFTY")
    assert len(df) == 2 and rep["rows_in"] == 10
    assert rep["unparsed"] == 3 and rep["bad_price"] == 3 and rep["invalid_volume"] == 2
    assert per_day == {"2024-01-01": 5}                                   # the five rows that had a date to blame
    assert df["volume"].tolist() == [0, 7] and rep["zero_volume"] == 1


def test_read_counts_out_of_order_rows(tmp_path):
    p = tmp_path / "x.csv"
    p.write_text("date,open,high,low,close,volume\n"
                 "2024-01-01 09:16:00,100,101,99,100,0\n2024-01-01 09:15:00,100,101,99,100,0\n")
    assert I.read_minutes(p, "NIFTY")[1]["out_of_order"] == 1


def test_a_different_header_is_refused_not_guessed(tmp_path):
    p = tmp_path / "x.csv"
    p.write_text("Date,Open,High,Low,Close,Volume\n2024-01-01 09:15:00,1,2,0.5,1,0\n")
    with pytest.raises(I.SourceFormatError):
        I.read_minutes(p, "NIFTY")


# ---- one session ----------------------------------------------------------------------------------------------------
def test_a_clean_session_is_accepted():
    g, v = I.check_session(make_day("2024-01-01"), dt.date(2024, 1, 1))
    assert v["status"] == "accepted" and v["minutes"] == 375 and v["missing_minutes"] == 0 and v["reasons"] == []
    assert len(g) == 375 and v["longest_stale_run"] == 0 and v["longest_gap_min"] == 0


def test_weekend_and_short_sessions_are_rejected_for_good():
    _, v = I.check_session(make_day("2024-01-06"), dt.date(2024, 1, 6))          # a Saturday
    assert v["status"] == "rejected" and v["hard_codes"] == ["weekend"]
    _, v = I.check_session(make_day("2024-01-01", n=359), dt.date(2024, 1, 1))
    assert v["status"] == "rejected" and v["hard_codes"] == ["short_session"]
    _, v = I.check_session(make_day("2024-01-01", n=360), dt.date(2024, 1, 1))   # the boundary: 360 is enough
    assert v["status"] == "accepted" and v["missing_minutes"] == 15


def test_a_jump_goes_to_review_for_an_index_but_not_for_a_volatility_index():
    d = make_day("2024-01-01")
    d.loc[200:, ["open", "high", "low", "close"]] *= 1.08
    _, v = I.check_session(d, dt.date(2024, 1, 1))
    assert v["status"] == "review" and v["review_codes"] == ["jump"] and v["max_1m_move"] > 0.05
    assert v["max_1m_move_signed"] > 0 and v["max_1m_move_at"].endswith("+05:30")
    _, v = I.check_session(d, dt.date(2024, 1, 1), jump_rule=False)
    assert v["status"] == "accepted"
    for factor, status in ((1.049, "accepted"), (1.052, "review"), (0.948, "review"), (0.952, "accepted")):    # the 5% bound, both ways
        d2 = make_day("2024-01-01")
        d2.loc[200:, ["open", "high", "low", "close"]] *= factor
        assert I.check_session(d2, dt.date(2024, 1, 1))[1]["status"] == status, factor


def test_the_declared_rules_are_pinned():
    """These numbers are the importer's pre-declared rules (they are in every manifest). Changing one is a decision with a new
    importer version and a new dataset, not an edit: this test makes sure it is noticed."""
    r = I.rules()
    assert (r["jump"], r["stale_run"], r["min_minutes"], r["max_jitter_s"], r["corroborate"]) == (0.05, 10, 360, 15, 0.03)
    assert (I.FIRST_MOD, I.LAST_MOD, I.SESSION_MINUTES) == (555, 929, 375)
    assert r["importer_version"] == "ml-intake-1" and r["header"] == ["date", "open", "high", "low", "close", "volume"]
    assert I.REVIEW_CODES == ("jump", "stale_run") and I.HARD_CODES == ("weekend", "short_session")


@pytest.mark.parametrize("length, status", [(9, "accepted"), (10, "review"), (60, "review")])
def test_a_stale_run_of_ten_bars_goes_to_review(length, status):
    _, v = I.check_session(make_stale(make_day("2024-01-01"), 100, length), dt.date(2024, 1, 1))
    assert v["status"] == status and v["longest_stale_run"] == length
    assert v["review_codes"] == (["stale_run"] if status == "review" else [])


def test_flat_bars_at_moving_prices_are_not_stale_and_a_gap_breaks_a_run():
    d = make_day("2024-01-01")
    for i, row in enumerate(range(100, 131)):                                              # a quiet market: each bar flat, each at a new price
        d.loc[row, ["open", "high", "low", "close"]] = d["close"].iloc[99] + 0.05 * (i + 1)
    assert I.check_session(d, dt.date(2024, 1, 1))[1]["longest_stale_run"] == 0
    frozen = d.copy()
    frozen.loc[100:130, ["open", "high", "low", "close"]] = d["close"].iloc[99] + 3.0       # the same price 31 times: a frozen feed
    assert I.check_session(frozen, dt.date(2024, 1, 1))[1]["longest_stale_run"] == 30
    s = make_stale(make_day("2024-01-01"), 100, 12).drop(index=range(105, 107)).reset_index(drop=True)  # two minutes missing inside
    assert I.check_session(s, dt.date(2024, 1, 1))[1]["longest_stale_run"] == 5       # bars 100-104; 108-111 is 4; the gap breaks it


def test_out_of_session_minutes_are_dropped_and_counted():
    d = pd.concat([make_day("2024-01-01", n=10, first=(9, 5)), make_day("2024-01-01")]).drop_duplicates("ts").reset_index(drop=True)
    d = pd.concat([d, make_day("2024-01-01", n=3, first=(15, 30))]).reset_index(drop=True)
    g, v = I.check_session(d, dt.date(2024, 1, 1))
    assert v["out_of_session"] == 10 + 3 and len(g) == 375 and v["status"] == "accepted"
    assert g["ts"].min().strftime("%H:%M") == "09:15" and g["ts"].max().strftime("%H:%M") == "15:29"


def test_duplicate_minutes_identical_keep_one_conflicting_drop_both():
    d = make_day("2024-01-01")
    ident = pd.concat([d, d.iloc[[10]]]).reset_index(drop=True)
    g, v = I.check_session(ident, dt.date(2024, 1, 1))
    assert len(g) == 375 and v["duplicates"] == 1 and v["conflicting_duplicates"] == 0
    clash = d.iloc[[20]].copy()
    clash[["open", "high", "low", "close"]] = [1.0, 2.0, 0.5, 1.5]
    g, v = I.check_session(pd.concat([d, clash]).reset_index(drop=True), dt.date(2024, 1, 1))
    assert len(g) == 374 and v["conflicting_duplicates"] == 1 and v["missing_minutes"] == 1
    assert d["ts"].iloc[20] not in set(g["ts"])


def test_missing_minutes_and_the_longest_gap_are_recorded():
    d = make_day("2024-01-01").drop(index=range(50, 58)).reset_index(drop=True)
    _, v = I.check_session(d, dt.date(2024, 1, 1))
    assert v["missing_minutes"] == 8 and v["longest_gap_min"] == 8 and v["status"] == "accepted"


def test_the_session_rules_agree_with_the_legacy_importer_on_messy_sessions():
    """Differential test: the aeron7 importer's session_check is the reference for what a session's minutes, gaps and
    acceptance are. Hard rejections and clean sessions must agree; a jump is a rejection there and a review here."""
    rng = np.random.default_rng(7)
    for k in range(40):
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
        g_old, v_old = legacy.session_check(d.assign(ts=d["ts"]))
        assert v_new["minutes"] == v_old["minutes"] and v_new["missing_minutes"] == v_old["missing_minutes"]
        assert v_new["longest_gap_min"] == v_old["longest_gap_min"]
        assert v_new["conflicting_duplicates"] == v_old["conflicting_duplicates"]
        assert abs(v_new["max_1m_move"] - v_old["max_1m_move"]) < 1e-12
        assert list(g_new["ts"]) == list(g_old["ts"])
        legacy_ok = v_old["accepted"]
        assert (v_new["status"] == "accepted") == legacy_ok or (v_new["status"] == "review" and not legacy_ok
                                                                 and v_new["review_codes"] == ["jump"])
        if not legacy_ok and v_new["status"] == "rejected":
            assert v_old["reasons"]


# ---- the import -----------------------------------------------------------------------------------------------------
@pytest.fixture
def imported(tmp_path, reviewed_none):
    src = build_source(tmp_path / "src")
    man = run_import(src, tmp_path / "out", reviewed_none, version="v1")
    return src, tmp_path / "out", man, reviewed_none


def test_import_writes_the_manifest_partitions_and_provenance(imported):
    src, out, man, _ = imported
    ds = out / SRC.name / man["dataset"]
    assert man["status"] == I.UNVERIFIED and man["tier"] == "T1b" and man["source"]["redistributable"] is False
    assert {f["symbol"] for f in man["source"]["files"]} == {"NIFTY", "BANKNIFTY", "INDIAVIX"}
    assert all(len(f["sha256"]) == 64 and f["bytes"] > 0 for f in man["source"]["files"])
    assert set(man["allowed_uses"]) == set(legacy.ALLOWED_USES) and man["not_for"] == legacy.FORBIDDEN_NOTE
    assert (ds / "manifest.json").is_file() and (ds / "quality.md").is_file() and (ds / "quality.json").is_file()
    assert len(man["sessions"]) == 15 and all(s["status"] == "accepted" for s in man["sessions"])
    df = I.load(ds, ["NIFTY"], use="development_folds", allow_unverified=True)
    assert len(df) == 5 * 375 and set(df["tier"]) == {"T1b"} and set(df["symbol"]) == {"NIFTY"}
    assert list(df.columns) == ["ts", "open", "high", "low", "close", "volume", "symbol", "tier", "source_file"]
    assert df["ts"].is_monotonic_increasing and str(df["ts"].dt.tz) == IST
    assert df.attrs["digest"] == man["digest"] and df.attrs["status"] == I.UNVERIFIED


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
    assert (out / SRC.name / man["dataset"] / "manifest.json").is_file()                          # the first is untouched


def test_a_partition_that_no_longer_matches_makes_reimport_and_load_fail(imported):
    src, out, man, reviewed = imported
    ds = out / SRC.name / man["dataset"]
    victim = next(iter(sorted((ds / "1m").rglob("*.parquet"))))
    df = pd.read_parquet(victim)
    df.loc[0, "close"] += 1.0
    df.to_parquet(victim, index=False)
    with pytest.raises(legacy.ImmutableViolation):
        run_import(src, out, reviewed)
    with pytest.raises(legacy.ImmutableViolation):
        I.load(ds, ["NIFTY", "BANKNIFTY", "INDIAVIX"], use="development_folds", allow_unverified=True)


def test_load_refuses_a_missing_or_extra_partition(imported):
    _, out, man, _ = imported
    ds = out / SRC.name / man["dataset"]
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
    ds = out / SRC.name / man["dataset"]
    with pytest.raises(legacy.ForbiddenUse, match="unverified|external_unverified"):
        I.load(ds, ["NIFTY"], use="development_folds")
    for use in ("option_pricing", "bid_ask", "profitability_claim", "paper_gate", "model_promotion", ""):
        with pytest.raises(legacy.ForbiddenUse, match="refused"):
            I.load(ds, ["NIFTY"], use=use, allow_unverified=True)
    empty = tmp_path / "no_manifest"
    (empty / "1m").mkdir(parents=True)
    with pytest.raises(legacy.ForbiddenUse, match="no manifest"):
        I.load(empty, ["NIFTY"], use="development_folds", allow_unverified=True)
    m = json.loads((ds / "manifest.json").read_text())
    m["status"] = I.VERIFIED
    (ds / "manifest.json").write_text(json.dumps(m))
    assert len(I.load(ds, ["NIFTY"], use="regime_research")) == 5 * 375              # verified: no opt-in needed, same uses only


def test_a_missing_source_file_stops_the_import(tmp_path, reviewed_none):
    src = build_source(tmp_path / "src")
    (src / "VIX.csv").unlink()
    with pytest.raises(I.SourceFormatError, match="VIX.csv"):
        run_import(src, tmp_path / "out", reviewed_none)


def test_bad_sessions_are_kept_out_of_the_partitions_and_say_why(tmp_path, reviewed_none):
    nifty = [make_day(DAYS[0], 25000, 0), make_day(DAYS[1], 25000, 1, n=200),                    # short
             make_day("2024-01-06", 25000, 2),                                                    # Saturday
             make_stale(make_day(DAYS[3], 25000, 3), 100, 30),                                    # review
             make_day(DAYS[4], 25000, 4)]
    src = build_source(tmp_path / "src", nifty=nifty)
    man = run_import(src, tmp_path / "out", reviewed_none)
    by_day = {s["day"]: s for s in man["sessions"] if s["symbol"] == "NIFTY"}
    assert {d: s["status"] for d, s in by_day.items()} == {
        DAYS[0]: "accepted", DAYS[1]: "rejected", "2024-01-06": "rejected", DAYS[3]: "review", DAYS[4]: "accepted"}
    ds = tmp_path / "out" / SRC.name / man["dataset"]
    got = I.load(ds, ["NIFTY"], use="development_folds", allow_unverified=True)
    assert sorted({str(t.date()) for t in got["ts"]}) == [DAYS[0], DAYS[4]]
    q = json.loads((ds / "quality.json").read_text())
    assert [r["day"] for r in q["review_queue"] if r["symbol"] == "NIFTY"] == [DAYS[3]]
    assert q["by_symbol"]["NIFTY"]["rejected_by_code"] == {"short_session": 1, "weekend": 1}
    dis = q["index_disagreements"]                                   # the indices must agree about a day; where they don't, say so
    assert dis["count"] == 4 and [r["day"] for r in dis["first"]] == [DAYS[1], DAYS[2], DAYS[3], "2024-01-06"]
    assert dis["first"][0]["NIFTY"] == "rejected" and dis["first"][0]["BANKNIFTY"] == "accepted"
    assert dis["first"][1]["NIFTY"] == "absent" and dis["first"][3]["BANKNIFTY"] == "absent"      # no NIFTY file row on the 3rd; no BANKNIFTY on the Saturday
    assert "Days the indices disagree about (4" in (ds / "quality.md").read_text()


def test_a_jump_seen_by_both_indices_is_corroborated_and_a_lone_one_is_not(tmp_path, reviewed_none):
    def jumped(df, up=True):
        d = df.copy()
        d.loc[200:, ["open", "high", "low", "close"]] *= 1.07 if up else 0.93
        return d
    nifty = [jumped(make_day(DAYS[0], 25000, 0)), jumped(make_day(DAYS[1], 25000, 1)), make_day(DAYS[2], 25000, 2)]
    bank = [jumped(make_day(DAYS[0], 50000, 10)), make_day(DAYS[1], 50000, 11), jumped(make_day(DAYS[2], 50000, 12), up=False)]
    vix = [jumped(make_day(DAYS[0], 15, 20)), jumped(make_day(DAYS[1], 15, 21)), make_day(DAYS[2], 15, 22)]   # the VIX is allowed to jump
    src = build_source(tmp_path / "src", nifty=nifty, bank=bank, vix=vix)
    man = run_import(src, tmp_path / "out", reviewed_none)
    got = {(s["symbol"], s["day"]): s for s in man["sessions"]}
    assert got[("NIFTY", DAYS[0])]["corroborated_by"] == ["BANKNIFTY"] and got[("BANKNIFTY", DAYS[0])]["corroborated_by"] == ["NIFTY"]
    assert got[("NIFTY", DAYS[1])]["status"] == "review" and got[("NIFTY", DAYS[1])]["corroborated_by"] == []
    assert got[("BANKNIFTY", DAYS[2])]["corroborated_by"] == []                        # the other index did not move
    for d in DAYS[:2]:                                                                  # the volatility index has no jump rule, and is not
        assert got[("INDIAVIX", d)]["status"] == "accepted" and got[("INDIAVIX", d)]["max_1m_move"] > 0.05   # evidence for the indices
    assert got[("NIFTY", DAYS[1])]["corroborated_by"] == []                             # (VIX jumped that day; it does not count)


# ---- the reviewed list ----------------------------------------------------------------------------------------------
EVIDENCE = "NIFTY and BANKNIFTY both jumped 6% in the same minute after a flat halt; the provider's daily low matches the last pre-jump print."


def reviewed_file(tmp_path, entries, name="rv.json"):
    p = tmp_path / name
    p.write_text(json.dumps({"schema": 1, "sessions": entries}))
    return p


def stale_source(tmp_path):
    nifty = [make_day(DAYS[0], 25000, 0), make_stale(make_day(DAYS[1], 25000, 1), 100, 30), make_day("2024-01-06", 25000, 2)]
    return build_source(tmp_path / "src", nifty=nifty)


def test_a_reviewed_entry_admits_a_review_session_and_changes_the_dataset_identity(tmp_path, reviewed_none):
    src = stale_source(tmp_path)
    base = run_import(src, tmp_path / "out", reviewed_none)
    rv = reviewed_file(tmp_path, [{"symbol": "NIFTY", "day": DAYS[1], "codes": ["stale_run"], "decision": "admit", "evidence": EVIDENCE}])
    adm = run_import(src, tmp_path / "out", rv)
    st = {s["day"]: s["status"] for s in adm["sessions"] if s["symbol"] == "NIFTY"}
    assert st[DAYS[1]] == "accepted_reviewed" and adm["reviewed_applied"] == [f"NIFTY {DAYS[1]}"]
    assert adm["dataset"] != base["dataset"] and adm["digest"] != base["digest"] and adm["reviewed_sha256"] != base["reviewed_sha256"]
    got = I.load(tmp_path / "out" / SRC.name / adm["dataset"], ["NIFTY"], use="development_folds", allow_unverified=True)
    assert DAYS[1] in {str(t.date()) for t in got["ts"]}
    assert next(s for s in adm["sessions"] if s["day"] == DAYS[1] and s["symbol"] == "NIFTY")["reviewed"] == EVIDENCE


def test_a_reviewed_entry_cannot_admit_a_hard_rejection_or_cover_a_new_code(tmp_path):
    src = stale_source(tmp_path)
    rv = reviewed_file(tmp_path, [
        {"symbol": "NIFTY", "day": "2024-01-06", "codes": ["jump"], "decision": "admit", "evidence": EVIDENCE},       # a weekend
        {"symbol": "NIFTY", "day": DAYS[1], "codes": ["jump"], "decision": "admit", "evidence": EVIDENCE},            # wrong code
        {"symbol": "NIFTY", "day": "2031-01-01", "codes": ["jump"], "decision": "admit", "evidence": EVIDENCE}])      # no such session
    man = run_import(src, tmp_path / "out", rv)
    st = {s["day"]: s["status"] for s in man["sessions"] if s["symbol"] == "NIFTY"}
    assert st["2024-01-06"] == "rejected" and st[DAYS[1]] == "review"
    assert man["reviewed_applied"] == [] and man["reviewed_unused"] == ["NIFTY 2031-01-01"]


@pytest.mark.parametrize("entry, why", [
    ({"symbol": "NIFTY", "day": "2024-01-02", "codes": ["jump"], "decision": "admit", "evidence": "looks fine"}, "too thin"),
    ({"symbol": "NIFTY", "day": "2024-01-02", "codes": [], "decision": "admit", "evidence": EVIDENCE}, "decision must be"),
    ({"symbol": "NIFTY", "day": "2024-01-02", "codes": ["weekend"], "decision": "admit", "evidence": EVIDENCE}, "decision must be"),
    ({"symbol": "NIFTY", "day": "2024-01-02", "codes": ["jump"], "decision": "maybe", "evidence": EVIDENCE}, "decision must be"),
    ({"symbol": "NIFTY", "day": "2024-01-02", "codes": ["jump"], "decision": "admit"}, "lacks"),
    ({"symbol": "NIFTY", "day": "02/01/2024", "codes": ["jump"], "decision": "admit", "evidence": EVIDENCE}, None)])
def test_a_malformed_reviewed_entry_is_an_error_never_skipped(tmp_path, entry, why):
    with pytest.raises((I.ReviewedListError, ValueError), match=why):
        I.load_reviewed(reviewed_file(tmp_path, [entry]))


def test_a_duplicate_reviewed_entry_and_a_wrong_schema_are_errors(tmp_path):
    e = {"symbol": "NIFTY", "day": "2024-01-02", "codes": ["jump"], "decision": "admit", "evidence": EVIDENCE}
    with pytest.raises(I.ReviewedListError, match="twice"):
        I.load_reviewed(reviewed_file(tmp_path, [e, dict(e)]))
    p = tmp_path / "bad.json"
    p.write_text(json.dumps({"schema": 2, "sessions": []}))
    with pytest.raises(I.ReviewedListError, match="schema 1"):
        I.load_reviewed(p)


def test_the_committed_reviewed_list_parses():
    entries, sha = I.load_reviewed()
    assert len(sha) == 64 and isinstance(entries, dict)


# ---- the canonical hash ---------------------------------------------------------------------------------------------
def test_canonical_hash_ignores_representation_and_sees_every_change():
    base = make_day("2024-01-01", n=20).assign(symbol="NIFTY", tier="T1b")
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


# ---- the phase-0 boundary -------------------------------------------------------------------------------------------
LIVE_PACKAGES = {"intraday", "engine", "execution", "journal", "risk", "learnbot", "web", "ops", "strategies", "backtest"}


def test_the_ml_package_never_imports_the_live_engine():
    """ML_PHASE0.md: Phase 0 is offline and read-only: it does not import the live engine, write to a journal, place or size
    anything, or use a secret. Checked on the source of every module in quantdesk/ml, including imports inside functions."""
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


# ---- the command ----------------------------------------------------------------------------------------------------
def test_the_cli_imports_and_reports_and_a_bad_source_exits_cleanly(tmp_path, capsys, reviewed_none):
    from quantdesk.cli import main
    src = tmp_path / "kaggle"
    for fname, start, seed in (("NIFTY 50_minute.csv", 25000, 0), ("NIFTY BANK_minute.csv", 50000, 10), ("INDIA VIX_minute.csv", 15, 20)):
        write_csv(src / fname, [make_day(d, start, seed + i) for i, d in enumerate(DAYS)])
    main(["ml", "import", "--source", str(src), "--out", str(tmp_path / "out"), "--version", "18", "--reviewed", str(reviewed_none)])
    line = capsys.readouterr().out.strip().splitlines()[-1]
    assert "status external_unverified" in line and "'accepted': 15" in line and "quality.md" in line
    ds = I.latest(tmp_path / "out")
    assert ds is not None and len(I.load(ds, ["NIFTY", "BANKNIFTY", "INDIAVIX"], use="development_folds", allow_unverified=True)) == 15 * 375
    (src / "INDIA VIX_minute.csv").unlink()
    with pytest.raises(SystemExit, match="ml import: INDIA VIX_minute.csv is missing"):
        main(["ml", "import", "--source", str(src), "--out", str(tmp_path / "out2"), "--reviewed", str(reviewed_none)])
