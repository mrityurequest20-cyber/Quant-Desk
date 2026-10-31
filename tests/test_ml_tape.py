"""P0.2 for tier T2 (quantdesk/ml/tape.py): the desk's own chain tape is registered by hash and count, referenced and not copied, and refused without a manifest."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from quantdesk.data.external_aeron import ForbiddenUse, ImmutableViolation
from quantdesk.ml import oi as OI
from quantdesk.ml import tape as T

IST = "Asia/Kolkata"
REPO = Path(__file__).resolve().parents[1]


def tape_df(day="2026-10-26", n_snap=3, strikes=(25000.0, 25050.0), underlying="NIFTY", source="kotak", start="09:20"):
    rows = []
    for i in range(n_snap):
        ts = pd.Timestamp(f"{day} {start}", tz=IST) + pd.Timedelta(minutes=i)
        for k in strikes:
            rows.append({"ts": ts, "underlying": underlying, "expiry": pd.Timestamp("2026-10-27"), "spot": 25010.0, "source": source, "strike": k,
                         "ce_ltp": 50.0, "ce_bid": 49.0, "ce_ask": 51.0, "ce_iv": 12.0, "ce_oi": 1000.0, "ce_doi": 5.0, "ce_vol": 10.0,
                         "pe_ltp": 40.0, "pe_bid": 39.0, "pe_ask": 41.0, "pe_iv": 13.0, "pe_oi": 2000.0, "pe_doi": -5.0, "pe_vol": 20.0,
                         "ce_bidq": 30.0, "ce_askq": 30.0, "pe_bidq": 30.0, "pe_askq": 30.0})
    return pd.DataFrame(rows)


def write(folder, name, df):
    folder.mkdir(parents=True, exist_ok=True)
    df.to_parquet(folder / name)
    return folder / name


@pytest.fixture
def tape(tmp_path):
    src = tmp_path / "src"
    write(src, "2026-10-26_morning-111_chains.parquet", tape_df("2026-10-26"))
    write(src, "2026-10-26_afternoon-112_chains.parquet", tape_df("2026-10-26", start="13:00"))
    write(src, "2026-10-27_morning-113_chains.parquet", tape_df("2026-10-27"))
    return src, tmp_path / "out"


def test_the_tape_is_registered_by_hash_and_count_and_the_data_is_not_copied(tape):
    src, out = tape
    man = T.import_tape(src, out, say=lambda *_: None)
    assert man["tier"] == "T2" and man["status"] == "internal_recording" and man["referenced_not_copied"] and man["rejected"] == []
    assert man["totals"]["files"] == 3 and man["totals"]["rows"] == 18 and man["totals"]["snapshots"] == 9
    f = next(x for x in man["files"] if x["file"].startswith("2026-10-26_morning"))
    assert f["day"] == "2026-10-26" and f["part"] == "morning" and len(f["sha256"]) == 64 and f["rows"] == 6 and f["snapshots"] == 3
    assert f["underlyings"] == {"NIFTY": 6} and f["sources"] == {"kotak": 6} and f["faults"]["implausible_oi_snapshot"] == 0
    ds = out / "tape" / man["dataset"]
    assert sorted(p.name for p in ds.iterdir()) == ["manifest.json"]                                        # nothing but the manifest: no data copied
    assert T.manifest_digest(json.loads((ds / "manifest.json").read_text())) == man["digest"]


def test_the_same_files_are_the_same_dataset_and_one_more_session_is_a_different_one(tape):
    src, out = tape
    a = T.import_tape(src, out, say=lambda *_: None)
    b = T.import_tape(src, out, say=lambda *_: None)
    assert a["dataset"] == b["dataset"] and a["digest"] == b["digest"]
    write(src, "2026-10-28_morning-114_chains.parquet", tape_df("2026-10-28"))
    c = T.import_tape(src, out, say=lambda *_: None)
    assert c["dataset"] != a["dataset"] and len(c["files"]) == 4
    assert T.latest(out).name == c["dataset"]


def test_files_that_are_not_tapes_are_rejected_with_their_reason_and_never_enter_the_manifest(tape, tmp_path):
    src, out = tape
    write(src, "2026-10-29_morning-1_chains.parquet", tape_df("2026-10-29").drop(columns=["ce_oi"]))                                       # a column missing
    write(src, "2026-10-30_morning-1_chains.parquet", tape_df("2026-10-30").assign(ts=lambda d: d["ts"].dt.tz_localize(None)))             # no timezone
    write(src, "2026-10-31_morning-1_chains.parquet", tape_df("2026-10-30"))                                                               # rows from another day
    write(src, "2026-11-02_morning-1_chains.parquet", tape_df("2026-11-02").iloc[0:0])                                                      # empty
    write(src, "2026-11-03_evening-1_chains.parquet", tape_df("2026-11-03"))                                                               # an unknown part
    write(src, "2026-11-04_morning-1_chains.parquet", tape_df("2026-11-04").assign(spot="x"))                                              # text where a number belongs
    (src / "2026-11-05_morning-1_chains.parquet").write_bytes(b"not parquet")
    man = T.import_tape(src, out, say=lambda *_: None)
    why = {r["file"]: r["reasons"][0] for r in man["rejected"]}
    assert len(man["files"]) == 3 and len(why) == 7
    assert "missing columns ['ce_oi']" in why["2026-10-29_morning-1_chains.parquet"] and "no timezone" in why["2026-10-30_morning-1_chains.parquet"]
    assert "the file's name says 2026-10-31" in why["2026-10-31_morning-1_chains.parquet"] and "no rows" in why["2026-11-02_morning-1_chains.parquet"]
    assert "not a tape file name" in why["2026-11-03_evening-1_chains.parquet"] and "text" in why["2026-11-04_morning-1_chains.parquet"] and "not readable" in why["2026-11-05_morning-1_chains.parquet"]
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(T.TapeError, match="no valid tape file"):
        T.import_tape(empty, out)


def test_two_files_for_one_session_part_are_refused_not_guessed(tape):
    src, out = tape
    write(src, "2026-10-26_morning-999_chains.parquet", tape_df("2026-10-26"))
    with pytest.raises(T.TapeError, match="same session part"):
        T.import_tape(src, out)


def test_faults_are_counted_never_repaired(tape):
    src, out = tape
    df = tape_df("2026-10-29", n_snap=3)
    df.loc[0, "ce_oi"] = 1e18                                                  # one implausible print: the whole snapshot (2 strikes) is a fault
    df.loc[4, "pe_oi"] = -5.0
    df.loc[2, "ce_bid"], df.loc[2, "ce_ask"] = 60.0, 50.0                      # crossed
    df.loc[3, "spot"] = 0.0
    df = pd.concat([df, df.iloc[[5]]], ignore_index=True)                      # an exact duplicate key
    df = pd.concat([df, tape_df("2026-10-29", source="model", start="10:30")], ignore_index=True)
    early = tape_df("2026-10-29", n_snap=1, start="08:00")                     # outside the cash session
    df = pd.concat([df, early], ignore_index=True)
    write(src, "2026-10-29_morning-7_chains.parquet", df)
    man = T.import_tape(src, out, say=lambda *_: None)
    f = next(x for x in man["files"] if x["day"] == "2026-10-29")
    k = f["faults"]
    assert k["implausible_oi_rows"] == 2 and k["implausible_oi_snapshot"] == 5 and k["crossed_quote_rows"] == 1 and k["nonpositive_spot_rows"] == 1
    # (5 rows: the two bad prints sit in two snapshots of two strikes each, and the duplicated row belongs to one of those snapshots)
    assert k["exact_duplicate"] == 1 and k["conflicting_key"] == 0 and k["model_source"] == 6 and k["outside_session"] == 2
    assert f["rows"] == len(df) and man["totals"]["faults"]["model_source"] == 6                    # the raw file is untouched: every row is still counted


def test_load_refuses_without_a_manifest_or_after_any_change_and_for_any_unlisted_use(tape, tmp_path):
    src, out = tape
    man = T.import_tape(src, out, say=lambda *_: None)
    ds = out / "tape" / man["dataset"]
    with pytest.raises(T.TapeError, match="without a manifest is refused"):
        T.load(tmp_path / "nowhere", src, "oi_shadow")
    for bad in ("publication", "gate_evidence", "promotion", ""):
        with pytest.raises(ForbiddenUse):
            T.load(ds, src, bad)
    df = T.load(ds, src, "oi_shadow")
    assert len(df) == 18 and set(df["tier"]) == {"T2"} and set(df["source_file"]) == {f["file"] for f in man["files"]} and df.attrs["status"] == "internal_recording"
    assert len(T.load(ds, src, "replay", days=["2026-10-26"])) == 12
    with pytest.raises(ImmutableViolation, match="expected one"):
        T.load(ds, src, "oi_shadow", expected_digest="0" * 64)
    # a changed file
    p = src / "2026-10-27_morning-113_chains.parquet"
    original = p.read_bytes()
    tape_df("2026-10-27").assign(spot=1.0).to_parquet(p)
    with pytest.raises(ImmutableViolation, match="no longer match"):
        T.load(ds, src, "oi_shadow")
    assert len(T.load(ds, src, "oi_shadow", days=["2026-10-26"])) == 12                          # an unchanged day still loads: only the files asked for are re-hashed
    p.write_bytes(original)
    p.unlink()
    with pytest.raises(ImmutableViolation, match="not found"):
        T.load(ds, src, "oi_shadow")
    p.write_bytes(original)
    # a hand-edited manifest, and a folder renamed to look like another dataset
    mp = ds / "manifest.json"
    good = json.loads(mp.read_text())
    mp.write_text(json.dumps({**good, "days": ["2020-01-01"]}))
    with pytest.raises(ImmutableViolation, match="does not hash"):
        T.load(ds, src, "oi_shadow")
    mp.write_text(json.dumps(good))
    other = ds.parent / "ml-tape-1-000000000000"
    shutil.copytree(ds, other)
    with pytest.raises(ImmutableViolation, match="folder name"):
        T.load(other, src, "oi_shadow")


def test_load_drops_the_counted_faults_by_default_and_says_how_many(tape):
    src, out = tape
    df = tape_df("2026-10-29", n_snap=3)
    df.loc[0, "ce_oi"] = 1e18
    df = pd.concat([df, df.iloc[[5]], tape_df("2026-10-29", source="model", start="10:30"), tape_df("2026-10-29", n_snap=1, start="08:00")], ignore_index=True)
    write(src, "2026-10-29_morning-7_chains.parquet", df)
    man = T.import_tape(src, out, say=lambda *_: None)
    ds = out / "tape" / man["dataset"]
    raw = T.load(ds, src, "oi_shadow", days=["2026-10-29"], clean=False)
    clean = T.load(ds, src, "oi_shadow", days=["2026-10-29"])
    d = clean.attrs["dropped"]
    assert len(raw) == len(df) and len(clean) == len(df) - sum(d.values())
    assert d["model_source"] == 6 and d["implausible_oi_snapshot"] == 2 and d["exact_duplicate"] == 1 and d["outside_session"] == 2
    assert (clean["source"] == "kotak").all() and clean["ce_oi"].max() < 1e12
    both = clean.merge(raw.drop_duplicates(T.KEY), on=T.KEY, suffixes=("", "_raw"))
    assert len(both) == len(clean) and (both["ce_bid"] == both["ce_bid_raw"]).all() and (both["ce_ask"] == both["ce_ask_raw"]).all()   # nothing repaired: surviving values are the recorded ones


def test_the_oi_bound_is_the_one_the_oi_shadow_uses():
    assert T.OI_MAX == OI.OI_MAX


def test_the_module_imports_nothing_live():
    src = (REPO / "quantdesk" / "ml" / "tape.py").read_text()
    import re
    bad = re.findall(r"^\s*(?:from|import)\s+(?:\.\.?)?\s*(?:quantdesk\.)?(intraday|engine|execution|journal|risk|learnbot|web|ops|strategies|backtest)\b", src, flags=re.M)
    assert bad == []


def test_the_command_registers_the_tape_and_refuses_a_tracked_folder(tape, capsys):
    from quantdesk.cli import main
    src, out = tape
    main(["ml", "import-tape", "--source", str(src), "--out", str(out)])
    assert "dataset ml-tape-3-" in capsys.readouterr().out
    with pytest.raises(SystemExit, match="--source"):
        main(["ml", "import-tape"])
    with pytest.raises(SystemExit, match="inside a git working tree"):
        main(["ml", "import-tape", "--source", str(src), "--out", str(REPO / "docs" / "tape_probe")])
    assert not (REPO / "docs" / "tape_probe").exists()


def test_load_returns_rows_in_time_order_whatever_the_file_names_say(tape):
    src, out = tape
    man = T.import_tape(src, out, say=lambda *_: None)
    d = T.load(out / "tape" / man["dataset"], src, "feature_building", days=["2026-10-26"])
    assert set(d["source_file"]) == {"2026-10-26_morning-111_chains.parquet", "2026-10-26_afternoon-112_chains.parquet"}   # "afternoon" sorts before "morning" by name
    for _, g in d.groupby(["underlying", "expiry", "strike"]):
        assert g["ts"].is_monotonic_increasing                                  # a shift or diff per strike never reads a later snapshot as the earlier one
    assert (d["session"] == "2026-10-26").all() and (d["tier"] == "T2").all()


def test_a_key_recorded_twice_with_different_values_is_quarantined_not_resolved_by_row_order(tape):
    src, out = tape
    df = tape_df("2026-10-29", n_snap=3)
    for order in (False, True):
        revised = df.iloc[[2]].assign(ce_ltp=99.0)
        d = pd.concat([df, revised] if not order else [revised, df], ignore_index=True)
        write(src, "2026-10-29_morning-7_chains.parquet", d)
        man = T.import_tape(src, out / str(order), say=lambda *_: None)
        f = next(x for x in man["files"] if x["day"] == "2026-10-29")
        assert f["faults"]["conflicting_key"] == 2 and f["faults"]["exact_duplicate"] == 0      # both rows of the key are counted; neither is preferred
        got = T.load(out / str(order) / "tape" / man["dataset"], src, "replay", days=["2026-10-29"])
        key = df.iloc[2]
        assert not ((got["ts"] == key["ts"]) & (got["strike"] == key["strike"])).any()
        assert got.attrs["dropped"]["conflicting_key"] == 2


def test_a_snapshot_present_in_both_parts_of_a_day_is_seen_across_the_files(tape):
    src, out = tape
    write(src, "2026-10-29_morning-1_chains.parquet", tape_df("2026-10-29", n_snap=3, start="09:20"))
    write(src, "2026-10-29_afternoon-2_chains.parquet", tape_df("2026-10-29", n_snap=3, start="09:21"))   # overlaps the morning's 09:21 and 09:22
    man = T.import_tape(src, out, say=lambda *_: None)
    chk = man["day_checks"]["2026-10-29"]
    assert chk["parts_overlap_in_time"] is True and chk["cross_file_exact_duplicate"] == 4 and chk["cross_file_conflicting_key"] == 0
    assert man["day_checks"]["2026-10-26"]["parts_overlap_in_time"] is False
    got = T.load(out / "tape" / man["dataset"], src, "replay", days=["2026-10-29"])
    assert not got.duplicated(T.KEY).any() and got.attrs["dropped"]["exact_duplicate"] == 4


def test_an_implausible_change_in_oi_quarantines_its_snapshot_like_an_implausible_oi(tape):
    src, out = tape
    df = tape_df("2026-10-29", n_snap=3)
    df.loc[0, "pe_doi"] = -1.6e18
    write(src, "2026-10-29_morning-7_chains.parquet", df)
    man = T.import_tape(src, out, say=lambda *_: None)
    f = next(x for x in man["files"] if x["day"] == "2026-10-29")
    assert f["faults"]["implausible_doi_rows"] == 1 and f["faults"]["implausible_doi_snapshot"] == 2 and f["faults"]["implausible_oi_snapshot"] == 0


def test_a_file_with_a_stored_index_is_read_by_row_and_the_latest_dataset_is_the_larger_one_on_a_tie(tape):
    src, out = tape
    df = tape_df("2026-10-29", n_snap=3)
    df.index = df.index[::-1] + 100                                            # a non-default index stored in the file
    write(src, "2026-10-29_morning-1_chains.parquet", df)
    man = T.import_tape(src, out, say=lambda *_: None)
    f = next(x for x in man["files"] if x["day"] == "2026-10-29")
    assert f["faults"]["implausible_oi_rows"] == 0 and f["faults"]["nonpositive_spot_rows"] == 0 and f["rows"] == len(df)      # no value was turned into NaN by a misaligned index
    write(src, "2026-10-29_afternoon-2_chains.parquet", tape_df("2026-10-29", n_snap=2, start="13:00"))
    bigger = T.import_tape(src, out, say=lambda *_: None)
    assert T.latest(out).name == bigger["dataset"]                             # same last day: the dataset with more files wins


def test_latest_with_a_source_ignores_datasets_whose_files_are_no_longer_there_as_registered(tape):
    src, out = tape
    old = T.import_tape(src, out, say=lambda *_: None)
    write(src, "2026-10-27_morning-113_chains.parquet", tape_df("2026-10-27", n_snap=1))      # the file was corrected: fewer rows, other bytes
    new = T.import_tape(src, out, say=lambda *_: None)
    assert new["dataset"] != old["dataset"] and new["totals"]["rows"] < old["totals"]["rows"]
    assert T.latest(out, src).name == new["dataset"]                                           # without the source the larger, older one would win and load() would refuse it
    assert T.latest(out).name == old["dataset"]


def test_a_single_file_source_registers_and_loads_and_no_manifest_is_ever_left_truncated(tmp_path):
    src = tmp_path / "src"
    f = write(src, "2026-10-26_morning-111_chains.parquet", tape_df("2026-10-26"))
    out = tmp_path / "out"
    man = T.import_tape(f, out, say=lambda *_: None)                           # a file, not a folder
    ds = out / "tape" / man["dataset"]
    assert len(T.load(ds, f, "replay")) == 6 and T.latest(out, f).name == man["dataset"]
    assert not list(ds.glob(".manifest.*")) and json.loads((ds / "manifest.json").read_text())["digest"] == man["digest"]
    again = T.import_tape(f, out, say=lambda *_: None)                         # the first registration stands
    assert again["digest"] == man["digest"]


def _load_day(tape, df, day="2026-10-29"):
    src, out = tape
    write(src, f"{day}_morning-7_chains.parquet", df)
    man = T.import_tape(src, out, say=lambda *_: None)
    return T.load(out / "tape" / man["dataset"], src, "oi_shadow", days=[day]), T.load(out / "tape" / man["dataset"], src, "oi_shadow", days=[day], clean=False)


def test_load_drops_a_snapshot_with_an_implausible_change_in_oi_and_counts_it(tape):
    df = tape_df("2026-10-29", n_snap=3)
    df.loc[0, "pe_doi"] = -1.6e18
    clean, raw = _load_day(tape, df)
    assert len(raw) == 6 and len(clean) == 4                                                          # the faulty row's snapshot (both strikes) is gone, nothing else
    assert clean.attrs["dropped"]["implausible_doi_snapshot"] == 2 and clean.attrs["dropped"]["implausible_oi_snapshot"] == 0
    assert (clean["pe_doi"].abs() < 1e12).all()


def test_a_row_with_two_faults_is_counted_once_under_the_first_fault_in_the_order(tape):
    df = tape_df("2026-10-29", n_snap=1, start="08:00")                                               # outside the session ...
    df.loc[0, "ce_oi"] = 1e18                                                                         # ... and in an implausible-OI snapshot
    clean, raw = _load_day(tape, df)
    d = clean.attrs["dropped"]
    assert len(raw) == 2 and len(clean) == 0
    assert d["implausible_oi_snapshot"] == 2 and d["outside_session"] == 0 and sum(d.values()) == 2   # DROP_ORDER: the OI fault names it first; no row is counted twice


def test_the_session_window_is_from_09_15_up_to_but_not_including_15_30(tape):
    parts = [tape_df("2026-10-29", n_snap=1, start=s) for s in ("09:14", "09:15", "15:29", "15:30")]
    df = pd.concat(parts, ignore_index=True)
    clean, raw = _load_day(tape, df)
    kept = sorted(clean["ts"].dt.tz_convert(IST).dt.strftime("%H:%M").unique())
    assert kept == ["09:15", "15:29"] and clean.attrs["dropped"]["outside_session"] == 4              # 09:14 and 15:30 are out, 09:15 and 15:29 are in


def test_the_load_says_what_it_is_for_and_whether_it_was_cleaned(tape):
    df = tape_df("2026-10-29", n_snap=2)
    df = pd.concat([df, tape_df("2026-10-29", source="model", start="10:30")], ignore_index=True)
    clean, raw = _load_day(tape, df)
    for out in (clean, raw):
        assert out.attrs["not_for"] == T.NOT_FOR and "gate or a promotion" in out.attrs["not_for"]  # the warning travels with the data
        assert out.attrs["tier"] == "T2" and out.attrs["status"] == "internal_recording"
    assert clean.attrs["clean"] is True and raw.attrs["clean"] is False
    assert raw.attrs["dropped"] == {} and (raw["source"] == "model").any()                          # an uncleaned load still holds the model rows, and says so by its flag
