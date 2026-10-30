"""P0.6: the independent check (quantdesk/ml/verify.py) under docs/ml/P0_6_criteria_v2.md. Each rule is broken on its own so it can be seen to fail, and
one end-to-end run shows what a pass, a fail and a void leave behind. Real data is never needed: the references are built here."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from quantdesk.data import external_aeron as ea
from quantdesk.ml import intake as I
from quantdesk.ml import verify as V

IST = I.IST
D = dt.date
REPO = Path(V.__file__).resolve().parents[2]


def minutes(days, start=25000.0, seed=0, n=375):
    out = []
    for i, day in enumerate(days):
        rng = np.random.default_rng(seed + i)
        c = np.round(start * np.exp(np.cumsum(rng.normal(0, 3e-4, n))), 2)
        o = np.r_[round(start, 2), c[:-1]]
        ts = pd.Timestamp(f"{day} 09:15", tz=IST) + pd.to_timedelta(np.arange(n), unit="min")
        out.append(pd.DataFrame({"ts": ts, "open": o, "high": np.maximum(o, c) + 0.5, "low": np.minimum(o, c) - 0.5, "close": c, "volume": np.zeros(n, dtype="int64")}))
    return pd.concat(out, ignore_index=True)


def weekdays(start, n):
    return [d.date() for d in pd.bdate_range(start, periods=n)]


def frame(days, **cols):
    base = {"high": 101.0, "low": 99.0, "close": 100.0, "close30": 100.0}
    base.update(cols)
    return pd.DataFrame({k: v for k, v in base.items()}, index=list(days))


@pytest.fixture(autouse=True)
def small(monkeypatch):
    monkeypatch.setattr(V, "MIN_SESSIONS", 5)


# ---- the pinned criteria -------------------------------------------------------------------------------------------------------------
def test_the_code_is_pinned_to_the_criteria_file_committed_before_it():
    assert V.criteria_sha256() == V.pinned_criteria_sha256() == I.VERIFICATION_CRITERIA["p06-v2"]


# ---- the daily bar and the two close definitions --------------------------------------------------------------------------------------
def test_daily_gives_the_envelope_the_last_close_and_the_mean_of_the_last_thirty_minute_closes():
    m = minutes(["2024-01-01", "2024-01-02"]).sample(frac=1.0, random_state=1)
    d = V.daily(m)
    for day, g in m.groupby(m["ts"].dt.date):
        g = g.sort_values("ts")
        last30 = g[(g["ts"].dt.hour == 15) & (g["ts"].dt.minute < 30)]
        assert len(last30) == 30
        assert d.at[day, "high"] == g["high"].max() and d.at[day, "low"] == g["low"].min() and d.at[day, "close"] == g["close"].iloc[-1]
        assert d.at[day, "close30"] == pytest.approx(last30["close"].mean())
    early = minutes(["2024-01-03"]).iloc[:200]                                           # a session with no 15:00 to 15:29 bars
    assert np.isnan(V.daily(early).at[D(2024, 1, 3), "close30"])


# ---- A, B, C: what agrees and what is a gross error ------------------------------------------------------------------------------------
def _cmp(kind, ours, ref, day=D(2024, 1, 1)):
    return V.compare(ours, ref, [day], kind).iloc[0]


@pytest.mark.parametrize("field,tol", [("high", 0.002), ("low", 0.002)])
def test_a_session_agrees_up_to_the_tolerance_on_high_and_low_and_not_beyond_it(field, tol):
    ref = frame([D(2024, 1, 1)])
    ours = frame([D(2024, 1, 1)], **{field: ref.at[D(2024, 1, 1), field] * (1 + tol * 0.99)})
    assert _cmp("A", ours, ref)["pass"]
    for sign in (1, -1):
        ours = frame([D(2024, 1, 1)], **{field: ref.at[D(2024, 1, 1), field] * (1 + sign * tol * 1.05)})
        assert not _cmp("A", ours, ref)["pass"]


def test_the_close_agrees_if_either_the_last_print_or_the_thirty_minute_mean_is_within_the_tolerance():
    ref = frame([D(2024, 1, 1)])
    off = 100.0 * 1.005                                                                   # 0.5%: outside 0.3%
    assert not _cmp("A", frame([D(2024, 1, 1)], close=off, close30=off), ref)["pass"]
    assert _cmp("A", frame([D(2024, 1, 1)], close=off, close30=100.1), ref)["pass"]        # the mean is close enough: NSE computes it that way
    assert _cmp("A", frame([D(2024, 1, 1)], close=100.1, close30=off), ref)["pass"]        # the last print is close enough
    assert not _cmp("A", frame([D(2024, 1, 1)], close=off, close30=np.nan), ref)["pass"]   # no 15:xx bars and a bad last print: not agreeing
    assert _cmp("B", frame([D(2024, 1, 1)], close=off, close30=100.1), ref)["pass"]
    assert not _cmp("B", frame([D(2024, 1, 1)], close=off, close30=off), ref)["pass"]


def test_a_gross_error_needs_both_close_definitions_to_be_far_off_but_either_high_or_low_alone():
    ref = frame([D(2024, 1, 1)])
    far = 100.0 * 1.02
    assert not _cmp("A", frame([D(2024, 1, 1)], close=far, close30=100.0), ref)["gross"]    # the mean is fine: a failure, not a gross error
    assert _cmp("A", frame([D(2024, 1, 1)], close=far, close30=far), ref)["gross"]
    assert _cmp("A", frame([D(2024, 1, 1)], high=101.0 * 1.02), ref)["gross"]
    assert _cmp("A", frame([D(2024, 1, 1)], low=99.0 * 0.98), ref)["gross"]
    assert _cmp("A", frame([D(2024, 1, 1)], close=np.nan, close30=np.nan), ref)["gross"]    # NaN is never within a bound
    assert _cmp("B", frame([D(2024, 1, 1)], close=far, close30=far), ref)["gross"]


def test_check_c_compares_to_a_tenth_of_a_percent_on_all_three_and_gross_is_one_and_a_half():
    ref = frame([D(2024, 1, 1)])
    for k in ("high", "low", "close"):
        ok = frame([D(2024, 1, 1)], **{k: ref.at[D(2024, 1, 1), k] * 1.0009})
        assert _cmp("C", ok, ref)["pass"]
        bad = frame([D(2024, 1, 1)], **{k: ref.at[D(2024, 1, 1), k] * 1.0011})
        r = _cmp("C", bad, ref)
        assert not r["pass"] and not r["gross"]
        assert _cmp("C", frame([D(2024, 1, 1)], **{k: ref.at[D(2024, 1, 1), k] * 1.02}), ref)["gross"]


def test_a_day_missing_on_either_side_is_not_compared():
    ours, ref = frame([D(2024, 1, 1), D(2024, 1, 2)]), frame([D(2024, 1, 1), D(2024, 1, 3)])
    t = V.compare(ours, ref, [D(2024, 1, 1), D(2024, 1, 2), D(2024, 1, 3)], "A")
    assert list(t["compared"]) == [True, False, False]


# ---- judge: the pass rate, gross errors, the month rule and the run rule --------------------------------------------------------------
def _t(days, fail=(), gross=(), unc=()):
    rows = []
    for i, d in enumerate(days):
        if i in unc:
            rows.append({"day": d, "compared": False, "pass": False, "gross": False})
        else:
            rows.append({"day": d, "compared": True, "pass": i not in fail and i not in gross, "gross": i in gross, "close_rel": 0.0})
    return pd.DataFrame(rows)


def test_a_clean_window_passes_judge_and_each_rule_fails_on_its_own():
    days = weekdays("2024-01-01", 260)
    s, r = V.judge(_t(days), len(days))
    assert r == [] and s["pass_rate"] == 1.0
    s, r = V.judge(_t(days, fail=range(0, 260, 8)), 260)                                  # 12.5% fail, none consecutive
    assert any("agree, at least 95%" in x for x in r) and s["failing_run"] == 1
    s, r = V.judge(_t(days, gross=[100]), 260)                                           # one gross error is enough
    assert any("gross error" in x for x in r) and s["n_gross"] == 1
    march = [i for i, d in enumerate(days) if d.month == 3][::2][:6]                      # half of March fails: 96% overall
    s, r = V.judge(_t(days, fail=march), 260)
    assert s["pass_rate"] >= 0.95 and any("month 2024-03" in x for x in r)


def test_the_month_rule_judges_only_months_with_ten_compared_sessions_and_the_run_rule_counts_compared_sessions_only():
    days = weekdays("2024-01-01", 260)
    k = next(i for i in range(1, len(days)) if days[i].month != days[i - 1].month and days[i].month == 4)
    s, r = V.judge(_t(days, fail=range(k - 3, k + 3)), 260)                              # six failures in a row across a month boundary
    assert s["failing_run"] == 6 and any("6 consecutive" in x for x in r) and s["worst_month"][1] >= 0.8
    s, r = V.judge(_t(days, fail=range(k - 3, k + 2)), 260)                              # five are allowed
    assert r == []
    s, r = V.judge(_t(days, fail=[k - 3, k - 2, k - 1, k + 1, k + 2, k + 3], unc=[k]), 260)    # an uncompared session neither breaks nor extends a run
    assert s["failing_run"] == 6 and any("consecutive" in x for x in r)
    few = days[:8]                                                                         # a month with 8 compared sessions is reported, not judged
    s, r = V.judge(_t(few, fail=[0, 1, 2, 3]), 8)
    assert s["worst_month"] is None and s["months_reported_not_judged"] == ["2024-01"]
    assert any("agree, at least 95%" in x for x in r)


# ---- coverage ------------------------------------------------------------------------------------------------------------------------------
def test_coverage_rules_each_fail_on_their_own():
    days = weekdays("2024-01-01", 200)
    nse = set(days)
    s, r = V.coverage(days, set(days), nse, "A")
    assert r == [] and s["accepted_share_of_nse_days"] == 1.0
    s, r = V.coverage(days + [D(2024, 9, 14)], set(days) | {D(2024, 9, 14)}, nse, "A")                  # a Saturday session NSE published no file for: a phantom
    assert any("phantom" in x for x in r) and s["n_phantom"] == 1
    s, r = V.coverage(days, set(days[:190]), nse, "A")                                                   # 10 of 200 have no reference row: 5% > 1%
    assert any("no reference row" in x for x in r)
    s, r = V.coverage(days, set(days[:198]), nse, "A")                                                   # 1% is allowed
    assert not any("no reference row" in x for x in r)
    s, r = V.coverage(days[:190], set(days), nse, "A")                                                   # importer rejections: 190 of 200 NSE days = 95% < 97%
    assert any("of NSE's index days" in x for x in r)
    s, r = V.coverage(days[:3], set(days), set(days[:3]), "A")
    assert any("at least 5 and 95%" in x for x in r)                                                     # too few compared (MIN_SESSIONS patched to 5)


def test_check_b_looks_at_the_nse_close_only_with_the_two_definitions():
    days = weekdays("2024-01-01", 60)
    ours = frame(days, high=500.0)                                                                       # the high is not B's business
    nse = pd.DataFrame({"close": 100.0}, index=days)
    r = V.check_b(ours, nse, days, set(days))
    assert r["passed"] and r["compared"] == 60
    r = V.check_b(frame(days, close=101.0, close30=101.0), nse, days, set(days))
    assert not r["passed"] and any("agree, at least" in x for x in r["reasons"])
    r = V.check_b(frame(days, close=102.0, close30=102.0), nse, days, set(days))
    assert any("gross" in x for x in r["reasons"])


# ---- C: minutes ---------------------------------------------------------------------------------------------------------------------------
def test_identical_minutes_correlate_perfectly_and_a_one_minute_labelling_shift_does_not():
    m = minutes([d.isoformat() for d in weekdays("2024-01-01", 8)])
    assert all(v == pytest.approx(1.0) for v in V.minute_corr(m, m.copy()).values())
    shifted = m.copy()
    shifted["ts"] = shifted["ts"] + pd.Timedelta(minutes=1)
    assert np.nanmedian(list(V.minute_corr(m, shifted).values())) < 0.3


def test_returns_are_taken_only_between_consecutive_minutes_present_in_both_series():
    m = minutes(["2024-01-01"])
    thin = m[m["ts"].dt.minute % 2 == 0]                                                                 # every other minute: no two are consecutive
    assert np.isnan(V.minute_corr(m, thin)[D(2024, 1, 1)])
    sparse = m[~((m["ts"].dt.hour == 11) & (m["ts"].dt.minute < 20))]                                    # one gap: returns across it are not formed, the rest correlate
    assert V.minute_corr(m, sparse)[D(2024, 1, 1)] == pytest.approx(1.0)
    flat = m.copy()
    flat["close"] = 100.0
    assert np.isnan(V.minute_corr(m, flat)[D(2024, 1, 1)])


def test_check_c_passes_identical_minutes_and_fails_each_rule_on_its_own(monkeypatch):
    days = [d.isoformat() for d in weekdays("2024-01-01", 8)]
    m = minutes(days)
    r = V.check_c(m, m.copy())
    assert r["passed"] and r["common_sessions"] == 8 and r["coverage_of_aeron7"] == 1.0
    few = V.check_c(m, m[m["ts"].dt.date < D(2024, 1, 5)])                                                 # only 4 sessions in common (the minimum is patched to 5)
    assert not few["passed"] and any("only 4 sessions in common" in x for x in few["reasons"])
    extra = pd.concat([m, minutes(["2024-02-01", "2024-02-02"], seed=50)], ignore_index=True)           # aeron7 has two sessions this dataset lacks: 8 of 10 = 80%
    r = V.check_c(m, extra)
    assert any("of aeron7's accepted sessions" in x for x in r["reasons"]) and r["only_here_not_gating"] == 0
    r = V.check_c(extra, m)                                                                              # the reverse direction is reported, not gating
    assert not any("aeron7's accepted" in x for x in r["reasons"]) and r["only_here_not_gating"] == 2
    shifted = m.copy()
    shifted["ts"] = shifted["ts"] + pd.Timedelta(minutes=1)
    r = V.check_c(m, shifted)
    assert r["pass_rate"] >= 0.95 and not r["passed"] and any("minute-return correlation" in x for x in r["reasons"])
    monkeypatch.setattr(V, "CORR_MEDIAN", 1.1)
    assert any("median minute-return correlation" in x for x in V.check_c(m, m.copy())["reasons"])
    off = m.copy()
    off["high"] = off["high"] * 1.0015                                                                   # 0.15% > 0.1% on every session
    assert any("agree, at least 95%" in x for x in V.check_c(m, off)["reasons"])


# ---- the NSE files -------------------------------------------------------------------------------------------------------------------------
HEADER = "Index Name,Index Date,Open Index Value,High Index Value,Low Index Value,Closing Index Value,Points Change,Change(%),Volume,Turnover (Rs. Cr.),P/E,P/B,Div Yield\n"


def nse_file(day, nifty=100.0, bank=200.0, date_text=None, extra=""):
    t = date_text or f"{day:%d-%m-%Y}"
    return (HEADER + f"Nifty 50,{t},1,2,0.5,{nifty},0,0,0,0,0,0,0\nNifty Next 50,{t},1,2,0.5,5,0,0,0,0,0,0,0\nNifty Bank,{t},1,2,0.5,{bank},0,0,0,0,0,0,0\n" + extra).encode()


def test_an_nse_file_gives_the_two_closes_and_every_malformed_one_voids_the_run():
    assert V.parse_nse(nse_file(D(2024, 1, 1)), D(2024, 1, 1)) == {"NIFTY": 100.0, "BANKNIFTY": 200.0}
    for raw, why in ((nse_file(D(2024, 1, 1), date_text="02-01-2024"), "Index Date"),               # the file's own date must equal the day asked for
                     (nse_file(D(2024, 1, 1), date_text="2024-01-01"), "could not be read"),          # a date in another layout is an error, not a guess
                     ((HEADER + "Nifty 50,01-01-2024,1,2,1,100,0,0,0,0,0,0,0\n"), "0 rows named Nifty Bank"),
                     (nse_file(D(2024, 1, 1), extra="Nifty 50,01-01-2024,1,2,1,100,0,0,0,0,0,0,0\n"), "2 rows named Nifty 50"),
                     (nse_file(D(2024, 1, 1), nifty="x"), "could not be read"),
                     (nse_file(D(2024, 1, 1), nifty="-5"), "close"),
                     (b"<html>blocked</html>", "0 rows named Nifty 50"),
                     (b"\xff\xfe\x00", "could not be read")):
        raw = raw if isinstance(raw, bytes) else raw.encode()
        with pytest.raises(V.VoidRun, match=why):
            V.parse_nse(raw, D(2024, 1, 1))


def test_version_2_accepts_a_swapped_index_date_label_for_the_three_named_days_only_and_lists_it():
    assert V.SWAPPED_LABEL_DAYS == {D(2023, 4, 6), D(2023, 4, 10), D(2023, 4, 11)}                  # the three files the criteria name
    for day in sorted(V.SWAPPED_LABEL_DAYS):
        label = f"{day:%m-%d-%Y}"                                                                       # the name's date read as MM-DD-YYYY
        assert label != f"{day:%d-%m-%Y}"
        listed = []
        assert V.parse_nse(nse_file(day, date_text=label), day, listed) == {"NIFTY": 100.0, "BANKNIFTY": 200.0}      # the closing values are used as they are
        assert listed == [{"date": str(day), "label": label}]                                         # one entry per file, not per row
        assert V.parse_nse(nse_file(day, date_text=label), day) == {"NIFTY": 100.0, "BANKNIFTY": 200.0}     # no collector: still accepted, only not listed
    normal = []
    D6 = D(2023, 4, 6)
    assert V.parse_nse(nse_file(D6), D6, normal) and normal == []                                       # NSE correcting the file: zero swapped is fine, nothing is listed
    for day, label, why in ((D(2023, 4, 7), "04-07-2023", "Index Date"),                                 # a swapped label on any other day is still an error
                            (D(2023, 5, 4), "05-04-2023", "Index Date"),
                            (D6, "07-04-2023", "Index Date"),                                           # a pinned day whose label is neither its date nor its swap
                            (D6, "04-06-2024", "Index Date"),                                           # right day and month, wrong year
                            (D(2023, 4, 13), "04-13-2023", "could not be read")):                       # a day above 12 has no swapped reading
        with pytest.raises(V.VoidRun, match=why):
            V.parse_nse(nse_file(day, date_text=label), day, [])


def test_one_row_with_a_wrong_label_voids_even_if_the_other_row_is_a_valid_swap():
    day = D(2023, 4, 6)
    t = f"{day:%m-%d-%Y}"
    raw = (HEADER + f"Nifty 50,{t},1,2,0.5,100,0,0,0,0,0,0,0\nNifty Bank,07-04-2023,1,2,0.5,200,0,0,0,0,0,0,0\n").encode()
    with pytest.raises(V.VoidRun, match="Index Date"):
        V.parse_nse(raw, day, [])


def test_fetch_nse_collects_the_swapped_files_also_when_they_are_read_back_from_the_cache(tmp_path):
    day = D(2023, 4, 6)
    days = [D(2023, 4, 5), day, D(2023, 4, 7)]
    fetch = lambda url: nse_file(dt.datetime.strptime(url.rsplit("_", 1)[1][:8], "%d%m%Y").date(), date_text=f"{day:%m-%d-%Y}" if f"{day:%d%m%Y}" in url else None)
    first, second = [], []
    V.fetch_nse(days, tmp_path / "c", fetch, lambda *_: None, first)
    V.fetch_nse(days, tmp_path / "c", lambda u: pytest.fail("the cache must be read"), lambda *_: None, second)
    assert first == second == [{"date": "2023-04-06", "label": "04-06-2023"}]


def test_fetch_nse_treats_404_as_no_file_everything_else_as_void_and_saves_what_it_reads(tmp_path):
    days = weekdays("2024-01-01", 20)
    holiday = days[5]
    calls = []

    def fetch(url):
        calls.append(url)
        d = dt.datetime.strptime(url.rsplit("_", 1)[1][:8], "%d%m%Y").date()
        return None if d == holiday else nse_file(d)
    closes, files, none = V.fetch_nse(days, tmp_path / "c", fetch, say=lambda *_: None)
    assert none == [holiday] and len(files) == 19 and len(closes["NIFTY"]) == 19 and holiday not in closes["NIFTY"].index
    assert len(list((tmp_path / "c").iterdir())) == 19 and all(len(h) == 64 for h in files.values())
    n = len(calls)
    V.fetch_nse(days, tmp_path / "c", fetch, say=lambda *_: None)                                       # the cache is read, only the 404 is asked again
    assert len(calls) == n + 1
    for exc in (RuntimeError("HTTP 403"), TimeoutError("slow")):
        def broken(url, exc=exc):
            raise exc
        with pytest.raises(V.VoidRun, match="could not be fetched"):
            V.fetch_nse(days[:3], tmp_path / "c2", broken, say=lambda *_: None)


def test_more_than_ten_percent_of_weekdays_without_a_file_voids_the_run_but_weekend_sessions_do_not_count(tmp_path):
    days = weekdays("2024-01-01", 20)
    gone = set(days[:3])                                                                                   # 15% of the weekdays
    with pytest.raises(V.VoidRun, match="archive layout changed"):
        V.fetch_nse(days, Path(str(tmp_path / "a")), lambda u: None if dt.datetime.strptime(u.rsplit("_", 1)[1][:8], "%d%m%Y").date() in gone else nse_file(dt.datetime.strptime(u.rsplit("_", 1)[1][:8], "%d%m%Y").date()), say=lambda *_: None)
    two = set(days[:2])                                                                                    # 10% exactly: allowed
    V.fetch_nse(days, Path(str(tmp_path / "b")), lambda u: None if dt.datetime.strptime(u.rsplit("_", 1)[1][:8], "%d%m%Y").date() in two else nse_file(dt.datetime.strptime(u.rsplit("_", 1)[1][:8], "%d%m%Y").date()), say=lambda *_: None)


def test_the_window_is_every_weekday_and_every_accepted_weekend_session():
    sat = D(2025, 2, 1)
    days = V.window_days({"NIFTY": [sat], "BANKNIFTY": []})
    assert sat in days and D(2023, 3, 1) in days and D(2026, 5, 15) in days and D(2023, 3, 4) not in days and days == sorted(days)


# ---- the run -------------------------------------------------------------------------------------------------------------------------------
DAYS = weekdays("2024-01-01", 8)


def _write_csv(path, frames):
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = pd.concat(frames)
    pd.DataFrame({"date": rows["ts"].dt.strftime("%Y-%m-%d %H:%M:%S"), "open": rows["open"], "high": rows["high"], "low": rows["low"], "close": rows["close"],
                  "volume": rows["volume"]}).to_csv(path, index=False)


@pytest.fixture
def world(tmp_path, monkeypatch):
    src = tmp_path / "src"
    for name, start, seed in (("NIFTY.csv", 25000, 0), ("BANKNIFTY.csv", 50000, 50), ("VIX.csv", 15, 90)):
        _write_csv(src / name, [minutes([d.isoformat()], start, seed + i) for i, d in enumerate(DAYS)])
    unit = I.Source(name="unit-index-minutes", url="https://example.invalid/unit",
                    files=(I.SourceFile("NIFTY.csv", "NIFTY"), I.SourceFile("BANKNIFTY.csv", "BANKNIFTY"), I.SourceFile("VIX.csv", "INDIAVIX", kind="vol_index")))
    rv = tmp_path / "rv.json"
    rv.write_text(json.dumps({"schema": 2, "sessions": []}))
    man = I.import_source(src, tmp_path / "out", unit, reviewed_path=rv, say=None, version="v1")
    ds = tmp_path / "out" / unit.name / man["dataset"]
    ours = {s: I.load(ds, [s], use="development_folds", allow_unverified=True) for s in V.SYMBOLS}
    aeron = tmp_path / "aeron"
    aeron.mkdir()
    # the real aeron7 manifest has no "digest" key: the fixture carries the keys the real one has
    (aeron / "manifest.json").write_text(json.dumps({"status": ea.VERIFIED, "dataset": "aeron7-unit", "source_url": "https://example.invalid/aeron", "source_commit": "c" * 40,
                                                     "importer_version": 2, "partitions": {}, "sessions": []}))
    monkeypatch.setattr(V, "DATASET_DIGEST", man["digest"])
    monkeypatch.setattr(V, "AERON_DATASET", "aeron7-unit")
    monkeypatch.setattr(V, "AERON_MANIFEST_SHA256", hashlib.sha256((aeron / "manifest.json").read_bytes()).hexdigest())
    monkeypatch.setattr(V, "verify_aeron_partitions", lambda *_: None)                                       # exercised on real parquet files in its own test below
    monkeypatch.setattr(ea, "load", lambda ds_, kind, symbols, use, allow_unverified=False: ours[symbols[0]].copy())
    monkeypatch.setattr(V, "NEW_START", D(2024, 1, 1))
    monkeypatch.setattr(V, "WINDOW_END", D(2024, 1, 10))
    monkeypatch.setattr(V, "MIN_SESSIONS", 3)
    closes = {s: V.daily(ours[s]) for s in V.SYMBOLS}

    def fetch(url):
        d = dt.datetime.strptime(url.rsplit("_", 1)[1][:8], "%d%m%Y").date()
        if d not in DAYS:
            return None                                                                                    # a weekday of the window the importer has no session for: NSE closed
        return nse_file(d, nifty=float(closes["NIFTY"].at[d, "close"]), bank=float(closes["BANKNIFTY"].at[d, "close"]))

    def yahoo(sym, a, b):
        return closes[sym][["high", "low", "close"]]
    return ds, aeron, tmp_path / "nse_cache", fetch, yahoo, closes


def test_a_passing_run_writes_the_record_once_and_leaves_the_status_alone_until_the_flip(world):
    ds, aeron, cache, fetch, yahoo, _ = world
    say = lambda *_: None
    rec = V.run(ds, aeron, cache, yahoo, fetch, say)
    assert rec["passed"] and rec["reasons"] == [] and rec["check"] == "p06-v2" and rec["symbols_verified"] == ["NIFTY", "BANKNIFTY"]
    vr = json.loads((ds / "verification.json").read_text())
    assert vr["digest"] == json.loads((ds / "manifest.json").read_text())["digest"] and vr["criteria_sha256"] == I.VERIFICATION_CRITERIA["p06-v2"]
    assert "overlap" in vr["scope"] and "DAILY ENVELOPE only" in vr["scope"]["new_window"] and "2023-03-01" in vr["scope"]["new_window"]
    assert "Nothing independent checks minute timestamps" in vr["scope"]["new_window"] and "not independent accuracy" in vr["scope"]["overlap"]
    assert "up to 5%" in vr["scope"]["not_covered"] and "INDIAVIX" in vr["scope"]["not_covered"]
    assert len(vr["references"]["nse"]["file_hashes"]) == 8 and vr["references"]["nse"]["days_without_a_file"] == []
    assert all(len(h) == 64 for h in vr["references"]["nse"]["file_hashes"].values())
    assert "INDIAVIX" not in json.dumps(vr["symbols"])
    assert set(vr["info_only"]) == {"NIFTY", "BANKNIFTY"}
    text = json.dumps(vr)
    assert "high_ref" not in text and "Nifty Next" not in text                                                # no reference rows
    assert json.loads((ds / "manifest.json").read_text())["status"] == I.UNVERIFIED                           # a run does not flip the status
    with pytest.raises(Exception, match="external_unverified"):
        I.load(ds, ["NIFTY"], use="regime_research")
    with pytest.raises(V.AlreadyChecked):
        V.run(ds, aeron, cache, yahoo, fetch, say)
    # the status-only step
    assert V.flip_status(ds) == I.VERIFIED
    assert json.loads((ds / "manifest.json").read_text())["status"] == I.VERIFIED
    assert I.dataset_digest(json.loads((ds / "manifest.json").read_text())) == vr["digest"]                   # the flip did not change the dataset's identity
    assert len(I.load(ds, ["NIFTY"], use="regime_research")) == 8 * 375                                       # no opt-in needed for the covered symbol
    with pytest.raises(Exception, match="external_unverified"):
        I.load(ds, ["INDIAVIX"], use="regime_research")                                                       # the volatility index is never covered
    assert V.flip_status(ds) == I.VERIFIED                                                                    # idempotent


def test_a_failing_run_records_why_lists_what_passed_and_the_flip_refuses_it(world):
    ds, aeron, cache, fetch, yahoo, closes = world
    bad = lambda sym, a, b: closes[sym][["high", "low", "close"]] * (1.02 if sym == "BANKNIFTY" else 1.0)     # Yahoo disagrees by 2% on one symbol only
    rec = V.run(ds, aeron, cache, bad, fetch, lambda *_: None)
    assert not rec["passed"] and rec["symbols_verified"] == [] and any("BANKNIFTY A:" in r for r in rec["reasons"])      # no partial licence
    assert rec["symbols"]["BANKNIFTY"]["B"]["passed"] and rec["symbols"]["BANKNIFTY"]["C"]["passed"]          # the other checks are still reported
    assert json.loads((ds / "verification.json").read_text())["passed"] is False
    with pytest.raises(ValueError, match="status unchanged"):
        V.flip_status(ds)
    assert json.loads((ds / "manifest.json").read_text())["status"] == I.UNVERIFIED


def test_a_reference_that_cannot_be_fetched_voids_the_run_and_it_can_be_run_again(world):
    ds, aeron, cache, fetch, yahoo, _ = world

    def down(sym, a, b):
        raise RuntimeError("429 too many requests")
    with pytest.raises(V.VoidRun, match="Yahoo for NIFTY could not be fetched"):
        V.run(ds, aeron, cache, down, fetch, lambda *_: None)
    assert not (ds / "verification.json").exists() and len(list(ds.glob("void_run_*.json"))) == 1
    assert "429" in json.loads(next(ds.glob("void_run_*.json")).read_text())["void"]

    def no_net(url):
        raise OSError("name resolution")
    with pytest.raises(V.VoidRun, match="NSE file"):
        V.run(ds, aeron, cache / "elsewhere", yahoo, no_net, lambda *_: None)
    assert not (ds / "verification.json").exists()
    rec = V.run(ds, aeron, cache, yahoo, fetch, lambda *_: None)                                             # the same rules, run again: a void spent nothing
    assert rec["passed"]


def test_a_run_lists_the_swapped_files_and_the_record_says_it_supersedes_the_void_run_and_is_post_hoc(world, monkeypatch):
    ds, aeron, cache, fetch, yahoo, closes = world
    day = sorted(DAYS)[2]
    label = f"{day:%m-%d-%Y}"
    assert label != f"{day:%d-%m-%Y}"
    monkeypatch.setattr(V, "SWAPPED_LABEL_DAYS", frozenset({day}))

    def swapped_fetch(url):
        d = dt.datetime.strptime(url.rsplit("_", 1)[1][:8], "%d%m%Y").date()
        return nse_file(d, nifty=float(closes["NIFTY"].at[d, "close"]), bank=float(closes["BANKNIFTY"].at[d, "close"]), date_text=label) if d == day else fetch(url)
    rec = V.run(ds, aeron, cache, yahoo, swapped_fetch, lambda *_: None)
    assert rec["passed"] and rec["check"] == "p06-v2"
    assert rec["date_label_swapped"] == [{"date": str(day), "label": label}]
    assert rec["supersedes"] == "p06-v1 (void)" and rec["post_hoc"] is True
    assert rec["void_log_sha256"] == "d7be976f412fec09fd90ccdb7a7c48e47991c4048b36eee79b079747dbef8533"
    assert rec["prior_exposure"] == V.PRIOR_EXPOSURE and "EXPECTED TO BE passed:false" in rec["prior_exposure"]            # carried verbatim
    assert json.loads((ds / "verification.json").read_text())["date_label_swapped"] == rec["date_label_swapped"]
    assert V.flip_status(ds)                                                                                              # a pass with these flags is flippable


def test_a_swapped_label_outside_the_three_named_days_voids_the_run_and_leaves_no_record(world):
    ds, aeron, cache, fetch, yahoo, closes = world
    day = sorted(DAYS)[2]                                                                                                 # not one of the three real days

    def swapped_fetch(url):
        d = dt.datetime.strptime(url.rsplit("_", 1)[1][:8], "%d%m%Y").date()
        return nse_file(d, nifty=float(closes["NIFTY"].at[d, "close"]), bank=float(closes["BANKNIFTY"].at[d, "close"]), date_text=f"{day:%m-%d-%Y}") if d == day else fetch(url)
    with pytest.raises(V.VoidRun, match="Index Date"):
        V.run(ds, aeron, cache, yahoo, swapped_fetch, lambda *_: None)
    assert not (ds / "verification.json").exists() and len(list(ds.glob("void_run_*.json"))) == 1
    assert json.loads(next(ds.glob("void_run_*.json")).read_text())["check"] == "p06-v2"


def test_the_record_is_a_normal_one_without_swapped_files_when_nse_has_corrected_them(world):
    ds, aeron, cache, fetch, yahoo, _ = world
    rec = V.run(ds, aeron, cache, yahoo, fetch, lambda *_: None)
    assert rec["date_label_swapped"] == [] and rec["supersedes"] == "p06-v1 (void)" and rec["post_hoc"] is True


def test_the_void_log_hash_names_the_real_void_run_and_the_pin_is_the_merged_v2_file():
    assert len(V.VOID_V1_LOG_SHA256) == 64 and V.SUPERSEDES == "p06-v1 (void)"
    assert V.CRITERIA_PATH.name == "P0_6_criteria_v2.md" and V.CHECK == "p06-v2"
    assert hashlib.sha256(V.CRITERIA_PATH.read_bytes()).hexdigest() == I.VERIFICATION_CRITERIA["p06-v2"]
    assert I.VERIFICATION_CRITERIA["p06-v1"] != I.VERIFICATION_CRITERIA["p06-v2"]


def test_a_reference_that_returns_less_than_asked_without_an_error_is_a_counted_run(world):
    ds, aeron, cache, fetch, yahoo, closes = world
    short = lambda sym, a, b: closes[sym][["high", "low", "close"]].iloc[:3]                                 # Yahoo answers, but with 3 of 8 days
    rec = V.run(ds, aeron, cache, short, fetch, lambda *_: None)
    assert not rec["passed"] and (ds / "verification.json").exists() and not list(ds.glob("void_run_*.json"))
    assert any("no reference row" in r for r in rec["reasons"])


def test_the_run_refuses_changed_criteria_an_unverified_aeron7_and_an_existing_record(world, monkeypatch):
    ds, aeron, cache, fetch, yahoo, _ = world
    monkeypatch.setitem(I.VERIFICATION_CRITERIA, "p06-v2", "0" * 64)
    with pytest.raises(V.CriteriaChanged):
        V.run(ds, aeron, cache, yahoo, fetch, lambda *_: None)
    monkeypatch.undo()
    (aeron / "manifest.json").write_text(json.dumps({"status": ea.UNVERIFIED, "dataset": "a", "digest": "b"}))
    with pytest.raises(ValueError, match="external_verified"):
        V.run(ds, aeron, cache, yahoo, fetch, lambda *_: None)
    assert not (ds / "verification.json").exists() and not list(ds.glob("void_run_*.json"))


def test_the_flip_refuses_a_record_for_another_digest_without_scope_or_with_other_criteria(world):
    ds, aeron, cache, fetch, yahoo, _ = world
    V.run(ds, aeron, cache, yahoo, fetch, lambda *_: None)
    good = json.loads((ds / "verification.json").read_text())
    for over in ({"digest": "0" * 64}, {"passed": "yes"}, {"check": "p06-v1"}, {"criteria_sha256": "0" * 64}, {"supersedes": None}, {"post_hoc": False}, {"symbols_verified": []},
                 {"symbols_verified": ["NIFTY", "BANKNIFTY", "INDIAVIX"]}, {"reasons": ["something failed"]}, {"D": {"passed": False, "reasons": []}},
                 {"symbols": {"NIFTY": good["symbols"]["NIFTY"]}}):
        (ds / "verification.json").write_text(json.dumps({**good, **over}))
        with pytest.raises(ValueError, match="status unchanged"):
            V.flip_status(ds)
    (ds / "verification.json").write_text("not json")
    with pytest.raises(ValueError, match="no readable"):
        V.flip_status(ds)
    assert json.loads((ds / "manifest.json").read_text())["status"] == I.UNVERIFIED


# ---- the command ---------------------------------------------------------------------------------------------------------------------------
def test_the_command_needs_its_arguments_and_will_not_cache_inside_a_git_tree(tmp_path):
    from quantdesk.cli import main
    with pytest.raises(SystemExit, match="--dataset"):
        main(["ml", "verify"])
    with pytest.raises(SystemExit, match="--aeron"):
        main(["ml", "verify", "--dataset", str(tmp_path)])
    with pytest.raises(SystemExit, match="inside a git working tree"):
        main(["ml", "verify", "--dataset", str(tmp_path), "--aeron", str(tmp_path), "--cache", str(REPO / "docs" / "nse_cache_probe")])
    assert not (REPO / "docs" / "nse_cache_probe").exists()
    with pytest.raises(SystemExit, match="no readable manifest.json and verification.json"):
        main(["ml", "verify", "--dataset", str(tmp_path), "--flip"])


def test_nothing_is_shown_before_every_reference_is_in_so_a_void_cannot_follow_a_verdict(world):
    ds, aeron, cache, fetch, yahoo, closes = world
    shown = []

    def flaky(sym, a, b):
        if sym == "BANKNIFTY":
            raise RuntimeError("429 too many requests")
        return closes[sym][["high", "low", "close"]]
    with pytest.raises(V.VoidRun, match="BANKNIFTY"):
        V.run(ds, aeron, cache, flaky, fetch, shown.append)
    assert not any("NIFTY A:" in str(x) or "NIFTY B:" in str(x) or "NIFTY C:" in str(x) for x in shown)        # no verdict (the NSE fetch lines are not verdicts)
    assert not (ds / "verification.json").exists() and len(list(ds.glob("void_run_*.json"))) == 1


def test_the_thresholds_are_the_ones_the_criteria_text_states():
    t = (REPO / "docs" / "ml" / "P0_6_criteria_v2.md").read_text()
    assert (V.TOL_A["high"], V.TOL_A["low"], V.TOL_A["close"], V.TOL_C, V.GROSS) == (0.002, 0.002, 0.003, 0.001, 0.015)
    assert (V.PASS_RATE, V.UNCOMPARED_MAX, V.ACCEPTED_FLOOR, V.MONTH_FLOOR, V.MONTH_MIN, V.MAX_RUN) == (0.95, 0.01, 0.97, 0.80, 10, 5)
    assert (V.C_COVERAGE, V.CORR_SESSION, V.CORR_SHARE, V.CORR_MEDIAN, V.MIN_COMMON_MINUTES, V.MAX_404_SHARE) == (0.95, 0.95, 0.90, 0.98, 30, 0.10)
    assert V.NEW_START == D(2023, 3, 1) and V.WINDOW_END == D(2026, 5, 15)
    for needle in ("at least 500 sessions", "0.3%", "0.2%", "1.5%", "97%", "80%", "more than 5 consecutive", "0.95", "0.98", "10% of the weekdays", "ind_close_all_<DDMMYYYY>.csv"):
        assert needle in t, needle


def test_an_undefined_correlation_counts_against_the_median_too():
    idx = pd.date_range("2024-01-01 09:15", periods=375, freq="min", tz="Asia/Kolkata")
    rng = np.random.default_rng(1)
    base = pd.DataFrame({"ts": idx, "open": 100.0, "high": 101.0, "low": 99.0, "close": 100 + rng.normal(0, 1, 375).cumsum(), "volume": 1.0})
    # a flat series has no defined correlation: with only such sessions the median must fail, not be skipped
    flat = base.assign(close=100.0)
    r = V.check_c(flat, flat)
    assert any("median minute-return correlation" in x for x in r["reasons"]) and r["corr_undefined"] >= 1


# ======================================================================================================================================================
# The auditor's real-data rehearsal and mutation run (5e52a0d): pins, the record's contents, the once-only write, the cache, Yahoo's edge cases, the
# unlogged crash class, and the direction of every boundary.
# ======================================================================================================================================================
import sys
import types
import urllib.error


def test_the_defaults_are_the_ones_the_criteria_name_and_min_sessions_is_five_hundred(monkeypatch):
    monkeypatch.undo()                                                                                     # the autouse fixture lowered it for the small fixtures
    t = (REPO / "docs" / "ml" / "P0_6_criteria_v2.md").read_text()
    assert V.MIN_SESSIONS == 500 and "at least 500 sessions" in t
    assert V.DATASET_DIGEST in t and V.AERON_DATASET in t and V.DATASET_DIGEST[:12] == "47d28d6376ca"


def test_a_different_dataset_or_reference_is_refused_before_anything_is_fetched(world, monkeypatch):
    ds, aeron, cache, fetch, yahoo, _ = world
    calls = []
    spy = lambda url: calls.append(url) or fetch(url)
    man = json.loads((ds / "manifest.json").read_text())
    monkeypatch.setattr(V, "DATASET_DIGEST", "0" * 64)
    with pytest.raises(ValueError, match="not the one docs/ml/P0_6_criteria_v2.md names"):
        V.run(ds, aeron, cache, yahoo, spy, lambda *_: None)
    monkeypatch.setattr(V, "DATASET_DIGEST", man["digest"])
    monkeypatch.setattr(V, "AERON_DATASET", "aeron7-other")
    with pytest.raises(ValueError, match="C reference must be"):
        V.run(ds, aeron, cache, yahoo, spy, lambda *_: None)
    monkeypatch.setattr(V, "AERON_DATASET", "aeron7-unit")
    monkeypatch.setattr(V, "AERON_MANIFEST_SHA256", "0" * 64)
    with pytest.raises(ValueError, match="not the one that was verified"):
        V.run(ds, aeron, cache, yahoo, spy, lambda *_: None)
    assert calls == [] and not (ds / "verification.json").exists() and not list(ds.glob("void_run_*.json"))      # refused, not voided: no run was spent


def test_the_aeron7_partitions_are_rehashed_from_their_files(tmp_path):
    aer = tmp_path / "a"
    parts = {}
    for sym in V.SYMBOLS:
        df = pd.DataFrame({"ts": pd.date_range("2022-01-03 09:15", periods=3, freq="min", tz="Asia/Kolkata"), "close": [1.0, 2.0, 3.0]})
        k = f"1m/symbol={sym}/year=2022.parquet"
        (aer / k).parent.mkdir(parents=True)
        df.to_parquet(aer / k)
        parts[k] = ea.frame_hash(pd.read_parquet(aer / k))
    V.verify_aeron_partitions(aer, {"partitions": parts})                                                   # as imported: fine
    pd.DataFrame({"ts": pd.date_range("2022-01-03 09:15", periods=3, freq="min", tz="Asia/Kolkata"), "close": [1.0, 2.0, 3.5]}).to_parquet(aer / "1m/symbol=NIFTY/year=2022.parquet")
    with pytest.raises(ValueError, match="no longer hashes"):
        V.verify_aeron_partitions(aer, {"partitions": parts})
    with pytest.raises(ValueError, match="lists no 1-minute partitions for BANKNIFTY"):
        V.verify_aeron_partitions(aer, {"partitions": {k: v for k, v in parts.items() if "NIFTY/" in k and "BANK" not in k}})


def test_the_record_holds_what_the_criteria_require_to_be_recorded(world):
    ds, aeron, cache, fetch, yahoo, _ = world
    rec = V.run(ds, aeron, cache, yahoo, fetch, lambda *_: None)
    nse = rec["references"]["nse"]
    csv_text = (cache / "nse_closes.csv").read_text()
    assert csv_text.startswith("date,symbol,close\n") and hashlib.sha256(csv_text.encode()).hexdigest() == nse["closes_csv_sha256"]
    manifest = (cache / "nse_files_manifest.json").read_text()
    assert hashlib.sha256(manifest.encode()).hexdigest() == nse["files_manifest_sha256"] and set(json.loads(manifest)["files"]) == set(nse["file_hashes"])
    for name, h in nse["file_hashes"].items():
        assert hashlib.sha256((cache / name).read_bytes()).hexdigest() == h                              # every raw file saved, each hash recorded
    for sym in V.SYMBOLS:
        y = rec["references"]["yahoo_frames"][sym]
        assert len(y["sha256"]) == 64 and y["rows"] == 8 and y["rows_unusable"] == 0 and y["requested"] == [str(DAYS[0]), str(DAYS[-1])]
    assert "yfinance" in rec["references"]["yahoo"] and rec["references"]["aeron7"]["manifest_sha256"] == V.AERON_MANIFEST_SHA256
    assert rec["references"]["aeron7"]["source_commit"] == "c" * 40


def test_the_record_is_written_exclusively_so_a_second_writer_cannot_replace_the_first(world):
    ds, aeron, cache, fetch, yahoo, _ = world

    def racing(url):
        (ds / "verification.json").write_text(json.dumps({"passed": False, "by": "the other run"}))        # another run finishes while this one is fetching
        return fetch(url)
    with pytest.raises(V.AlreadyChecked, match="appeared while this run was computing"):
        V.run(ds, aeron, cache, yahoo, racing, lambda *_: None)
    assert json.loads((ds / "verification.json").read_text()) == {"passed": False, "by": "the other run"}
    assert not list(ds.glob(".verification.json.*.tmp"))
    (ds / "verification.json").unlink()
    (ds / "verification_p06-v2.json").write_text("{}")                                                    # the superseded-record guard
    with pytest.raises(V.AlreadyChecked):
        V.run(ds, aeron, cache, yahoo, fetch, lambda *_: None)


def test_a_bad_file_never_stays_in_the_cache_to_void_every_rerun(world):
    ds, aeron, cache, fetch, yahoo, _ = world
    html = lambda url: b"<html>Access Denied</html>"
    with pytest.raises(V.VoidRun):
        V.run(ds, aeron, cache, yahoo, html, lambda *_: None)
    assert not list(cache.glob("ind_close_all_*.csv"))                                                    # nothing that failed to parse was kept
    calls = []
    rec = V.run(ds, aeron, cache, yahoo, lambda url: calls.append(url) or fetch(url), lambda *_: None)      # the rerun fetches afresh and counts
    assert rec["passed"] and calls
    # and a bad file that is already in the cache is dropped the first time it is found bad
    (ds / "verification.json").unlink()
    first = sorted(cache.glob("ind_close_all_*.csv"))[0]
    first.write_bytes(b"not an index file")
    with pytest.raises(V.VoidRun):
        V.run(ds, aeron, cache, yahoo, fetch, lambda *_: None)
    assert not first.exists()


def test_yahoo_rows_with_missing_numbers_are_not_compared_and_duplicate_dates_void_the_run(world):
    idx = [D(2024, 1, 1), D(2024, 1, 2), D(2024, 1, 3)]
    df = pd.DataFrame({"high": [10.0, float("nan"), 12.0], "low": [9.0, 9.0, 0.0], "close": [9.5, 9.5, 11.0]}, index=idx)
    assert list(V.clean_yahoo(df, "NIFTY").index) == [idx[0]]
    with pytest.raises(V.VoidRun, match="two rows for one date"):
        V.clean_yahoo(pd.concat([df, df.iloc[:1]]), "NIFTY")
    ds, aeron, cache, fetch, yahoo, closes = world
    dup = lambda sym, a, b: pd.concat([closes[sym][["high", "low", "close"]], closes[sym][["high", "low", "close"]].iloc[:1]])
    with pytest.raises(V.VoidRun, match="two rows for one date"):
        V.run(ds, aeron, cache, dup, fetch, lambda *_: None)
    assert len(list(ds.glob("void_run_*.json"))) == 1 and not (ds / "verification.json").exists()


def test_an_empty_yahoo_answer_is_a_void_run_by_decision(monkeypatch):
    fake = types.SimpleNamespace(download=lambda *a, **k: pd.DataFrame())
    monkeypatch.setitem(sys.modules, "yfinance", fake)
    with pytest.raises(V.VoidRun, match="no usable daily bars"):
        V.yahoo_daily("NIFTY", D(2024, 1, 1), D(2024, 1, 10))


def test_any_exception_the_code_raises_is_a_logged_void_not_an_unlogged_crash(world, monkeypatch):
    ds, aeron, cache, fetch, yahoo, closes = world
    boom = lambda sym, a, b: (_ for _ in ()).throw(KeyError("close"))
    with pytest.raises(V.VoidRun, match="Yahoo for NIFTY could not be fetched"):
        V.run(ds, aeron, cache, boom, fetch, lambda *_: None)
    monkeypatch.setattr(V, "check_a", lambda *a, **k: (_ for _ in ()).throw(TypeError("a bug in the compute phase")))
    with pytest.raises(V.VoidRun, match="TypeError"):
        V.run(ds, aeron, cache, yahoo, fetch, lambda *_: None)
    logs = [json.loads(p.read_text()) for p in ds.glob("void_run_*.json")]
    assert sorted(l["void"].split(":")[0] for l in logs) == ["TypeError", "VoidRun"]               # both are on the record, with the exception type
    assert not (ds / "verification.json").exists()


def test_http_fetch_sends_a_browser_user_agent_to_the_named_host_and_only_a_404_is_no_file(monkeypatch):
    seen = {}

    class R:
        def __init__(self, b):
            self.b = b

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return self.b

    def opener(req, timeout):
        seen["url"], seen["ua"] = req.full_url, req.get_header("User-agent")
        return R(b"ok")
    monkeypatch.setattr(V.urllib.request, "urlopen", opener)
    assert V.http_fetch(V.NSE_URL.format(ddmmyyyy="14052026")) == b"ok"
    assert seen["url"] == "https://archives.nseindia.com/content/indices/ind_close_all_14052026.csv" and "Mozilla/5.0" in seen["ua"]

    def err(code):
        def f(req, timeout):
            raise urllib.error.HTTPError(req.full_url, code, "x", {}, None)
        return f
    monkeypatch.setattr(V.urllib.request, "urlopen", err(404))
    assert V.http_fetch("https://archives.nseindia.com/x") is None
    for code in (403, 429, 500):
        monkeypatch.setattr(V.urllib.request, "urlopen", err(code))
        with pytest.raises(urllib.error.HTTPError):
            V.http_fetch("https://archives.nseindia.com/x")


def test_weekend_404s_do_not_count_toward_the_ten_percent_rule(tmp_path):
    weekdays_ = [D(2024, 1, 1) + dt.timedelta(days=i) for i in range(14) if (D(2024, 1, 1) + dt.timedelta(days=i)).weekday() < 5]       # 10 weekdays
    weekend = [D(2024, 1, 6), D(2024, 1, 7), D(2024, 1, 13), D(2024, 1, 14)]
    days = sorted(weekdays_ + weekend)
    holiday = {weekdays_[0]}                                                                                # 1 of 10 weekdays = exactly 10%: allowed
    f = lambda url: None if dt.datetime.strptime(url.rsplit("_", 1)[1][:8], "%d%m%Y").date() in holiday or dt.datetime.strptime(url.rsplit("_", 1)[1][:8], "%d%m%Y").date() in weekend \
        else nse_file(dt.datetime.strptime(url.rsplit("_", 1)[1][:8], "%d%m%Y").date())
    V.fetch_nse(days, tmp_path / "c1", f, lambda *_: None)                                                  # 5 weekend 404s would be 5/14 > 10% if they counted
    holiday.add(weekdays_[1])                                                                               # 2 of 10 weekdays: void
    with pytest.raises(V.VoidRun, match="archive layout changed"):
        V.fetch_nse(days, tmp_path / "c2", f, lambda *_: None)


# ---- the direction of every boundary -------------------------------------------------------------------------------------------------------------
def _frames(n, off=None, base=1000.0):
    """ours / reference daily frames over n consecutive weekdays; `off` maps a day index to a factor on ours' close (high and low untouched, close30 equal to the 15:29 close)."""
    days = [d.date() for d in pd.bdate_range("2024-01-01", periods=n)]
    ref = pd.DataFrame({"high": base + 5, "low": base - 5, "close": base}, index=days)
    ours = ref.copy()
    ours["close30"] = ours["close"]
    for i, f in (off or {}).items():
        ours.iloc[i, ours.columns.get_loc("close")] = base * f
        ours.iloc[i, ours.columns.get_loc("close30")] = base * f
    return days, ours, ref


def test_the_pass_rate_boundary_is_at_least_ninety_five_percent():
    days, ours, ref = _frames(20, {0: 1.01})                                                                # 19 of 20 agree = exactly 95%: passes the rate rule
    s, why = V.judge(V.compare(ours, ref, days, "A"), 20)
    assert s["pass_rate"] == 0.95 and not any("agree" in r for r in why)
    days, ours, ref = _frames(20, {0: 1.01, 7: 1.01})
    s, why = V.judge(V.compare(ours, ref, days, "A"), 20)
    assert any("90.0% of compared sessions agree" in r for r in why)


def test_the_tolerance_and_gross_boundaries_include_equality(monkeypatch):
    days, ours, ref = _frames(3, {0: 1.0})
    ours.iloc[0, ours.columns.get_loc("high")] = 1005.0 * (1 + 0.002)
    r = V._rel(ours.iloc[0]["high"], ref.iloc[0]["high"])
    monkeypatch.setitem(V.TOL_A, "high", r)                                                                 # tolerance exactly the observed difference
    assert bool(V.compare(ours, ref, days, "A").iloc[0]["pass"])
    monkeypatch.setitem(V.TOL_A, "high", r * 0.999999)
    assert not bool(V.compare(ours, ref, days, "A").iloc[0]["pass"])
    monkeypatch.setattr(V, "GROSS", r)
    assert not bool(V.compare(ours, ref, days, "A").iloc[0]["gross"])                                       # exactly the gross limit is not gross
    monkeypatch.setattr(V, "GROSS", r * 0.999999)
    assert bool(V.compare(ours, ref, days, "A").iloc[0]["gross"])


def test_in_b_a_gross_close_needs_both_definitions_to_be_off():
    days, ours, ref = _frames(3)
    ours.iloc[0, ours.columns.get_loc("close")] = 1000.0 * 1.05                                             # the 15:29 close is 5% off, the 15:00-15:29 mean is exact
    t = V.compare(ours, ref, days, "B")
    assert bool(t.iloc[0]["pass"]) and not bool(t.iloc[0]["gross"])
    ours.iloc[0, ours.columns.get_loc("close30")] = 1000.0 * 1.05
    t = V.compare(ours, ref, days, "B")
    assert not bool(t.iloc[0]["pass"]) and bool(t.iloc[0]["gross"])


def test_a_month_needs_ten_sessions_to_be_judged_and_eighty_percent_of_them_to_agree():
    days, ours, ref = _frames(10, {0: 1.01, 1: 1.01})                                                        # one month, 10 sessions, 8 agree = exactly 80%
    s, why = V.judge(V.compare(ours, ref, days, "A"), 10)
    assert not any("month" in r for r in why) and s["worst_month"][1] == 0.8
    days, ours, ref = _frames(10, {0: 1.01, 1: 1.01, 3: 1.01})                                               # 7 of 10: fails the month rule
    s, why = V.judge(V.compare(ours, ref, days, "A"), 10)
    assert any("month 2024-01 has 70% agreeing" in r for r in why)
    days, ours, ref = _frames(9, {i: 1.01 for i in range(9)})                                                # 9 sessions: reported, not judged
    s, why = V.judge(V.compare(ours, ref, days, "A"), 9)
    assert s["worst_month"] is None and s["months_reported_not_judged"] == ["2024-01"] and not any("month" in r for r in why)


def test_accepted_sessions_must_be_at_least_ninety_seven_percent_of_nses_index_days():
    nse_days = {D(2024, 1, 1) + dt.timedelta(days=i) for i in range(100)}
    ok = sorted(nse_days)[:97]
    ref = set(ok)
    _, why = V.coverage(ok, ref, nse_days, "A")
    assert not any("of NSE's index days" in r for r in why)
    _, why = V.coverage(sorted(nse_days)[:96], set(sorted(nse_days)[:96]), nse_days, "A")
    assert any("96.0% of NSE's index days" in r for r in why)


def test_the_correlation_rule_boundaries():
    good, mid = 0.99, 0.96
    share, med, why = V.corr_verdict([mid] * 9 + [0.5])                                                      # 9 of 10 at >= 0.95 = exactly 90%, but the median is below 0.98
    assert share == 0.9 and not any("have minute-return" in r for r in why) and any("median" in r for r in why)
    share, med, why = V.corr_verdict([good] * 9 + [0.5])                                                     # median 0.99: both pass
    assert why == []
    _, _, why = V.corr_verdict([good] * 8 + [0.5, 0.5])                                                      # 80%: the share rule fails
    assert any("80.0% of common sessions" in r for r in why)
    _, med, why = V.corr_verdict([V.CORR_MEDIAN] * 10)                                                       # a median exactly at the limit passes
    assert why == [] and med == V.CORR_MEDIAN
    _, _, why = V.corr_verdict([float("nan")] * 4 + [good] * 6)                                              # undefined counts as a failure: 60% < 90%
    assert any("60.0%" in r for r in why)


def test_a_correlation_needs_thirty_common_minute_returns():
    rng = np.random.default_rng(3)

    def pair(n):
        idx = pd.date_range("2024-01-01 09:15", periods=n, freq="min", tz="Asia/Kolkata")
        c = 100 + rng.normal(0, 1, n).cumsum()
        a = pd.DataFrame({"ts": idx, "close": c})
        return a, a.assign(close=c + rng.normal(0, 0.01, n))
    a, b = pair(31)                                                                                         # 31 minutes = 30 returns: defined
    assert not np.isnan(V.minute_corr(a, b)[D(2024, 1, 1)])
    a, b = pair(30)                                                                                         # 29 returns: undefined
    assert np.isnan(V.minute_corr(a, b)[D(2024, 1, 1)])


def test_c_coverage_counts_only_the_aeron7_sessions_from_our_first_day_on(monkeypatch):
    def m1(days):
        frames = [minutes([d.isoformat()], 25000.0, i) for i, d in enumerate(days)]
        return pd.concat(frames, ignore_index=True)
    early = [D(2023, 12, 18) + dt.timedelta(days=i) for i in range(5)]                                      # aeron7 days before ours begins: not our miss
    common = weekdays("2024-01-01", 8)
    ours, ref = m1(common), m1(early + common)
    r = V.check_c(ours, ref)
    assert r["coverage_of_aeron7"] == 1.0 and not any("also accepted here" in x for x in r["reasons"])


def test_a_failed_integrity_check_fails_the_record_and_leaves_no_licence(world, monkeypatch):
    ds, aeron, cache, fetch, yahoo, _ = world
    man = json.loads((ds / "manifest.json").read_text())
    assert V.check_d({**man, "digest": "0" * 64}, {})["passed"] is False
    monkeypatch.setattr(V, "check_d", lambda *_: {"passed": False, "reasons": ["D: planted"]})
    rec = V.run(ds, aeron, cache, yahoo, fetch, lambda *_: None)
    assert not rec["passed"] and rec["symbols_verified"] == [] and "D: planted" in rec["reasons"]


def test_the_record_carries_the_rehearsal_disclosure_and_the_verdict_is_shown_only_after_it_is_written(world, monkeypatch):
    ds, aeron, cache, fetch, yahoo, _ = world
    seen = []

    def say(x):
        if "NIFTY A:" in str(x):
            seen.append(((ds / "verification.json").exists(), str(x)))
    rec = V.run(ds, aeron, cache, yahoo, fetch, say)
    assert "SYNTHETIC" in rec["prior_exposure"] and "not blind for C" in rec["prior_exposure"] and "post hoc" in rec["prior_exposure"]
    assert seen and all(existed for existed, _ in seen)                                                    # the file was already there when the verdict was printed


def test_the_exclusive_write_still_refuses_when_hard_links_are_unavailable(tmp_path, monkeypatch):
    monkeypatch.setattr(V.os, "link", lambda *a, **k: (_ for _ in ()).throw(OSError("no hard links here")))
    V._write_once(tmp_path / "r.json", {"a": 1})
    assert json.loads((tmp_path / "r.json").read_text()) == {"a": 1}
    with pytest.raises(V.AlreadyChecked):
        V._write_once(tmp_path / "r.json", {"a": 2})
    assert json.loads((tmp_path / "r.json").read_text()) == {"a": 1} and not list(tmp_path.glob(".r.json.*"))


def test_the_disclosure_states_the_expected_outcome_plainly():
    t = V.PRIOR_EXPOSURE
    assert "EXPECTED TO BE passed:false" in t and "15 of 19" in t and "2015-08" in t and "independently" in t and "post hoc" in t


def test_an_undefined_correlation_pulls_the_median_down_not_out():
    vals = [float("nan"), 0.5, 0.6, 0.7, 0.96, 0.985, 0.99, 0.99, 0.99, 0.99]             # 10 sessions, one undefined (-1): the median is (0.96 + 0.985) / 2 = 0.9725; dropping it would give 0.985
    _, med, why = V.corr_verdict(vals)
    assert abs(med - 0.9725) < 1e-12 and float(np.nanmedian(vals)) == 0.985
    assert any("median minute-return correlation 0.9725" in r for r in why)               # and 0.9725 < 0.98 fails the median rule, which dropping the undefined one would have passed


def test_equality_at_the_per_session_correlation_limit_counts_as_good():
    share, _, _ = V.corr_verdict([V.CORR_SESSION] * 10)
    assert share == 1.0
