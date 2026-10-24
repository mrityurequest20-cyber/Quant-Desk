"""P0.6: the independent check (quantdesk/ml/verify.py) under docs/ml/P0_6_criteria.md. Each rule is broken on its own so it can be seen to fail, and
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
    assert V.criteria_sha256() == V.pinned_criteria_sha256() == I.VERIFICATION_CRITERIA["p06-v1"]


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


def test_more_than_ten_percent_of_weekdays_without_a_file_voids_the_run_but_weekend_sessions_do_not_count():
    days = weekdays("2024-01-01", 20)
    gone = set(days[:3])                                                                                   # 15% of the weekdays
    with pytest.raises(V.VoidRun, match="archive layout changed"):
        V.fetch_nse(days, Path("/tmp/does-not-matter-p06-a"), lambda u: None if dt.datetime.strptime(u.rsplit("_", 1)[1][:8], "%d%m%Y").date() in gone else nse_file(dt.datetime.strptime(u.rsplit("_", 1)[1][:8], "%d%m%Y").date()), say=lambda *_: None)
    two = set(days[:2])                                                                                    # 10% exactly: allowed
    V.fetch_nse(days, Path("/tmp/does-not-matter-p06-b"), lambda u: None if dt.datetime.strptime(u.rsplit("_", 1)[1][:8], "%d%m%Y").date() in two else nse_file(dt.datetime.strptime(u.rsplit("_", 1)[1][:8], "%d%m%Y").date()), say=lambda *_: None)


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
    (aeron / "manifest.json").write_text(json.dumps({"status": ea.VERIFIED, "dataset": "aeron7-unit", "digest": "ab" * 32}))
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
    assert rec["passed"] and rec["reasons"] == [] and rec["check"] == "p06-v1" and rec["symbols_verified"] == ["NIFTY", "BANKNIFTY"]
    vr = json.loads((ds / "verification.json").read_text())
    assert vr["digest"] == json.loads((ds / "manifest.json").read_text())["digest"] and vr["criteria_sha256"] == I.VERIFICATION_CRITERIA["p06-v1"]
    assert "overlap" in vr["scope"] and "daily envelope only" in vr["scope"]["new_window"]
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
    assert not rec["passed"] and rec["symbols_verified"] == ["NIFTY"] and any("BANKNIFTY A:" in r for r in rec["reasons"])
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


def test_a_reference_that_returns_less_than_asked_without_an_error_is_a_counted_run(world):
    ds, aeron, cache, fetch, yahoo, closes = world
    short = lambda sym, a, b: closes[sym][["high", "low", "close"]].iloc[:3]                                 # Yahoo answers, but with 3 of 8 days
    rec = V.run(ds, aeron, cache, short, fetch, lambda *_: None)
    assert not rec["passed"] and (ds / "verification.json").exists() and not list(ds.glob("void_run_*.json"))
    assert any("no reference row" in r for r in rec["reasons"])


def test_the_run_refuses_changed_criteria_an_unverified_aeron7_and_an_existing_record(world, monkeypatch):
    ds, aeron, cache, fetch, yahoo, _ = world
    monkeypatch.setitem(I.VERIFICATION_CRITERIA, "p06-v1", "0" * 64)
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
    for over in ({"digest": "0" * 64}, {"passed": "yes"}, {"check": "p06-v2"}, {"criteria_sha256": "0" * 64}, {"symbols_verified": []}):
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
