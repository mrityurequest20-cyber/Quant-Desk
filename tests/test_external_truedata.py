"""TrueData export importer (data/external_truedata.py): parsing, validation, deduplication, repeated imports, the
independent check, use restrictions and the daily provider. Synthetic files only, in the export's real layout."""
import json

import pandas as pd
import pytest

from quantdesk.data import external_truedata as T
from quantdesk.data.external_aeron import ForbiddenUse, ImmutableViolation


def daily_rows(days, base=24000.0):
    out = []
    for i, d in enumerate(days):
        o = base + i * 10
        out.append(f"{d:%d-%m-%Y},17:30:00,{o:.2f},{o + 50:.2f},{o - 40:.2f},{o + 20:.2f},0,0,0.00,0.00")
    return out


def write(path, lines, crlf=True):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((("\r\n" if crlf else "\n").join(lines) + ("\r\n" if crlf else "\n")).encode())
    return path


DAYS = list(pd.bdate_range("2026-06-01", periods=60))


def test_daily_file_is_read_as_found_not_as_assumed(tmp_path):
    p = write(tmp_path / "NIFTY.txt", daily_rows(DAYS))
    df, rep = T.read_file(p, "NIFTY")
    assert rep["timeframe"] == "1d" and rep["date_format"] == "%d-%m-%Y" and rep["header"] is None
    assert rep["crlf"] == 60 and rep["lf_only"] == 0 and rep["fields_per_row"] == {10: 60}
    assert rep["rows_accepted"] == 60 and rep["rows_rejected"] == 0
    assert rep["not_populated"] == ["extra_1", "extra_2", "extra_3", "extra_4"]      # zeros get no meaning
    assert "volume" not in df.columns and "oi" not in df.columns
    assert str(df["ts"].dt.tz) == "Asia/Kolkata" and df["source_ts"].iat[0] == f"{DAYS[0]:%d-%m-%Y} 17:30:00"
    assert df["source_line"].tolist() == list(range(1, 61))


def test_bad_rows_are_rejected_visibly_and_duplicates_handled(tmp_path):
    rows = daily_rows(DAYS[:10])
    rows.insert(3, rows[2])                                        # identical duplicate: kept once
    rows.append(f"{DAYS[20]:%d-%m-%Y},17:30:00,100,90,95,92,0,0,0.00,0.00")        # high < low
    clash = rows[7].split(",")
    clash[5] = str(float(clash[5]) + 1)
    rows.append(",".join(clash))                                   # same date, different close: both dropped
    rows.append("32-13-2026,17:30:00,1,2,0.5,1.5,0,0,0,0")         # impossible date
    rows.append("01-09-2026,17:30:00,1,2,0.5")                     # short row
    df, rep = T.read_file(write(tmp_path / "NIFTY.txt", rows), "NIFTY")
    assert rep["duplicate_rows_identical"] == 1 and rep["duplicate_timestamps_conflicting"] == 1
    assert rep["rejected"]["unparsable date/time"] == 1 and rep["rejected"]["5 fields, expected 10"] == 1
    assert any("invalid OHLC" in k for k in rep["rejected"])
    assert all("line" in x and "reason" in x for x in rep["reject_examples"])
    assert df["ts"].is_unique and len(df) == 10 - 1                  # the clashing date is gone; high<low never got in


def test_intraday_timeframe_ist_and_coverage(tmp_path):
    lines = []
    for d in DAYS[:3]:
        for m in range(375 if d != DAYS[1] else 370):              # day 2 misses five minutes
            t = pd.Timestamp(f"{d.date()} 09:15") + pd.Timedelta(minutes=m)
            lines.append(f"{t:%d-%m-%Y},{t:%H:%M:%S},100,101,99,100.5,0,0,0,0")
    p = write(tmp_path / "Trade 1 Minute" / "NIFTY.txt", lines)
    df, rep = T.read_file(p, "NIFTY", hint="1m")
    assert rep["timeframe"] == "1m" and not rep["timeframe_conflict"] and rep["outside_session_rows"] == 0
    assert "inside 09:15–15:30" in rep["ist_evidence"]
    cov = T.session_coverage(df, "1m")
    assert cov["sessions"] == 3 and cov["complete_sessions"] == 2 and cov["missing_bars_total"] == 5
    _, rep5 = T.read_file(write(tmp_path / "Trade 5 Minute" / "NIFTY.txt", lines), "NIFTY", hint="5m")
    assert rep5["timeframe"] == "1m" and rep5["timeframe_conflict"]           # the folder's claim is checked, not trusted


def test_weekend_session_is_kept_and_flagged(tmp_path):
    days = DAYS[:5] + [pd.Timestamp("2026-02-01")]                  # a Sunday (Budget day)
    df, rep = T.read_file(write(tmp_path / "NIFTY.txt", daily_rows(sorted(days))), "NIFTY")
    assert rep["weekend_rows"] == ["2026-02-01"] and len(df) == 6


def test_import_is_immutable_and_idempotent(tmp_path):
    src = tmp_path / "export"
    write(src / "Trade 1 Daily" / "NIFTY.txt", daily_rows(DAYS))
    write(src / "Trade 1 Daily" / "BANKNIFTY.txt", daily_rows(DAYS, 54000))
    (src / "README.md").write_text("not data")
    raw = {p: p.read_bytes() for p in src.rglob("*.txt")}
    man1 = T.import_export(src, tmp_path / "out", say=lambda *a: None)
    man2 = T.import_export(src, tmp_path / "out", say=lambda *a: None)          # same files: a no-op
    assert man1["batch"] == man2["batch"] and man1["partitions"] == man2["partitions"]
    assert man1["imported_at"] == man2["imported_at"]
    assert {p: p.read_bytes() for p in src.rglob("*.txt")} == raw                 # the raw export is never modified
    assert set(man1["partitions"]) == {"1d/symbol=NIFTY.parquet", "1d/symbol=BANKNIFTY.parquet"}
    f = next(x for x in man1["files"] if x["path"].endswith("NIFTY.txt") and "BANK" not in x["path"])
    assert f["timeframe_hint"] == "1d" and len(f["sha256"]) == 64
    write(src / "Trade 1 Daily" / "NIFTY.txt", daily_rows(DAYS + [pd.Timestamp("2026-09-01")]))
    man3 = T.import_export(src, tmp_path / "out", say=lambda *a: None)          # changed content: a new batch
    assert man3["batch"] != man1["batch"]
    assert (tmp_path / "out" / "truedata" / man1["dataset"] / "manifest.json").exists()      # the old batch stays
    p = tmp_path / "out" / "truedata" / man1["dataset"] / "1d" / "symbol=NIFTY.parquet"
    df = pd.read_parquet(p)
    df.loc[0, "close"] += 1
    df.to_parquet(p)
    write(src / "Trade 1 Daily" / "NIFTY.txt", daily_rows(DAYS))
    with pytest.raises(ImmutableViolation):                                      # tampered output is caught
        T.import_export(src, tmp_path / "out", say=lambda *a: None)


def test_verify_sets_status_and_lists_one_sided_dates(tmp_path):
    src = tmp_path / "export"
    write(src / "NIFTY.txt", daily_rows(DAYS + [pd.Timestamp("2026-02-01")]))
    man = T.import_export(src, tmp_path / "out", say=lambda *a: None)
    ds = tmp_path / "out" / "truedata" / man["dataset"]
    mine = pd.read_parquet(ds / "1d" / "symbol=NIFTY.parquet")
    ref = mine.set_index(mine["ts"].dt.date)[["open", "high", "low", "close"]].drop(pd.Timestamp("2026-02-01").date())

    def reference(sym, start, end):
        return ref
    with pytest.raises(ForbiddenUse):
        T.load(ds, "1d", ["NIFTY"], use="daily_backtest")                        # unverified: refused
    r = T.verify(ds, reference=reference, say=lambda *a: None)
    s = r["series"]["1d/symbol=NIFTY.parquet"]
    assert r["passed"] and s["compared"] == 60 and s["only_in_truedata"] == ["2026-02-01"]
    assert json.loads((ds / "manifest.json").read_text())["status"] == T.VERIFIED
    bad = ref.copy()
    bad["close"] *= 1.01

    def wrong(sym, start, end):
        return bad
    assert not T.verify(ds, reference=wrong, say=lambda *a: None)["passed"]
    assert json.loads((ds / "manifest.json").read_text())["status"] == T.UNVERIFIED


def test_uses_are_restricted_and_the_provider_serves_daily_bars(tmp_path):
    src = tmp_path / "export"
    write(src / "NIFTY.txt", daily_rows(DAYS))
    man = T.import_export(src, tmp_path / "out", say=lambda *a: None)
    ds = tmp_path / "out" / "truedata" / man["dataset"]
    with pytest.raises(ForbiddenUse):
        T.load(ds, "1d", ["NIFTY"], use="option_backtest", allow_unverified=True)
    with pytest.raises(ForbiddenUse):
        T.TrueDataProvider(tmp_path / "out").history("NIFTY", "2026-01-01")      # unverified
    p = T.TrueDataProvider(tmp_path / "out", allow_unverified=True)
    h = p.history("NIFTY", "2026-06-10", "2026-06-30")
    assert list(h.columns) == ["open", "high", "low", "close", "volume"] and h.index.tz is None
    assert h.index.min() >= pd.Timestamp("2026-06-10") and (h["volume"] == 0).all()
    assert h.attrs["volume"] == "not provided by the export"
