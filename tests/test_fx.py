"""Foreign exchange (quantdesk/data/fx.py, fx-daily.yml, fx-minutes.yml): the ECB-implied rates, the daily dataset's checks (cross-check, jumps, gaps, no independent source, a pair
that is down), the minute bars and their manifest, the immutability, and the workflows' isolation. Fake sources stand in for Yahoo and the ECB: no network."""
from __future__ import annotations

import datetime as dt
import io
import json
import re
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

from quantdesk.data import fx as FX
from quantdesk.data.external_aeron import ImmutableViolation, _write_once

ROOT = Path(__file__).resolve().parents[1]
DAYS = pd.bdate_range("2024-01-01", "2025-12-31")
TODAY = dt.date(2026, 11, 9)


def _ecb_zip(days=DAYS, drop=()) -> bytes:
    rng = np.random.default_rng(7)
    walk = lambda x0, s: x0 * np.exp(np.cumsum(rng.normal(0, s, len(days))))                      # noqa: E731
    t = pd.DataFrame({"Date": days.strftime("%Y-%m-%d"), "USD": walk(1.08, 0.004), "JPY": walk(160.0, 0.004), "GBP": walk(0.85, 0.003), "INR": walk(90.0, 0.003),
                      "CAD": walk(1.45, 0.003), "SEK": walk(11.5, 0.003), "CHF": walk(0.95, 0.003)})
    csv = t.drop(columns=list(drop)).to_csv(index=False).replace("\n", ",\n")                                                # the real file ends every row with a comma
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr("eurofxref-hist.csv", csv)
    return b.getvalue()


def _bars(close: pd.Series, spread=0.002) -> pd.DataFrame:
    return pd.DataFrame({"open": close, "high": close * (1 + spread), "low": close * (1 - spread), "close": close, "volume": 0.0})


class FakeYahoo:
    def __init__(self, daily=None, minutes=None, down=()):
        self.d, self.m, self.down = daily or {}, minutes or {}, set(down)

    def daily(self, symbol, start, end):
        if symbol in self.down:
            raise FX.SourceDown(f"yahoo {symbol}: blocked")
        df = self.d[symbol].copy()
        df.index.name = "date"
        return df

    def minutes(self, symbol, days):
        if symbol in self.down:
            raise FX.SourceDown(f"yahoo {symbol}: blocked")
        return self.m[symbol].copy()


def _world(**tweak):
    ecb = FX.EcbReference(fetch=_ecb_zip)
    eurusd, usdjpy = ecb.implied("EURUSD"), ecb.implied("USDJPY")
    y = {"EURUSD": _bars(eurusd * 1.003), "USDJPY": _bars(usdjpy * 0.997), "DXY": _bars(ecb.implied("DXY") * 1.004)}
    y.update(tweak)
    return ecb, y


def test_the_ecb_table_implies_each_pair_from_the_euro_rates_and_has_nothing_for_the_dollar_index():
    ecb = FX.EcbReference(fetch=_ecb_zip)
    t = ecb.table()
    assert t["EUR"].eq(1.0).all() and {"USD", "JPY", "GBP", "INR"} <= set(t.columns) and not any(c.startswith("Unnamed") for c in t.columns)
    assert np.allclose(ecb.implied("EURUSD"), t["USD"])                                              # EURUSD is the dollars per euro
    assert np.allclose(ecb.implied("USDJPY"), t["JPY"] / t["USD"])                                  # dollar-yen is yen per euro over dollars per euro
    assert np.allclose(ecb.implied("GBPINR"), t["INR"] / t["GBP"]) and np.allclose(ecb.implied("EURINR"), t["INR"])
    assert ecb.implied("EURXYZ") is None                                                              # no such currency in the table
    dxy = ecb.implied("DXY")                                                                          # the dollar index rebuilt with ICE's basket formula
    manual = 50.14348112 * (t["USD"] ** -0.576) * ((t["JPY"] / t["USD"]) ** 0.136) * ((t["USD"] / t["GBP"]) ** -0.119) * ((t["CAD"] / t["USD"]) ** 0.091) \
        * ((t["SEK"] / t["USD"]) ** 0.042) * ((t["CHF"] / t["USD"]) ** 0.036)
    assert np.allclose(dxy, manual) and (dxy > 0).all()
    assert FX.EcbReference(fetch=lambda: _ecb_zip(drop=("CHF",))).implied("DXY") is None  # a basket currency the table lacks: nothing is made up
    with pytest.raises(FX.SourceDown):
        FX.EcbReference(fetch=lambda: b"not a zip").table()


def test_a_clean_series_that_agrees_with_the_ecb_is_verified_and_the_dataset_is_written_once(tmp_path):
    ecb, y = _world()
    man = FX.run_daily(tmp_path, ["EURUSD", "USDJPY"], "2024-01-01", TODAY, FakeYahoo(y), ecb, say=lambda *a: None)
    s = man["series"]["EURUSD"]
    assert s["status"] == "verified" and s["reasons"] == [] and s["crosscheck"]["match_rate"] == 1.0 and s["crosscheck"]["compared"] == 200 and s["gaps"]["missing"] == 0
    assert man["status"] == "verified" and man["unverified_series"] == [] and man["as_of"] == "2026-11-09"
    run = tmp_path / "2026-11-09"
    sh = pd.read_parquet(run / "fx_daily_2024.parquet")
    assert list(sh.columns) == FX.COLS_DAILY and set(sh["symbol"]) == {"EURUSD", "USDJPY"} and (sh["source"] == "yahoo").all() and (sh["series_status"] == "verified").all()
    assert json.loads((run / "manifest.json").read_text())["series"]["USDJPY"]["status"] == "verified" and FX.release_names(run)[0] == "fx_daily_2024.parquet"
    p = run / "fx_daily_2024.parquet"
    assert _write_once(pd.read_parquet(p), p)                                                        # the same content again: accepted
    with pytest.raises(ImmutableViolation):
        _write_once(pd.read_parquet(p).assign(close=1.0), p)                                         # different content under the same name: refused


def test_an_inverted_pair_a_jump_and_a_pair_without_an_independent_source_are_each_not_verified_with_the_reason_and_a_gap_is_coverage_not_a_fault(tmp_path):
    ecb, y = _world()
    inverted = _bars(1 / ecb.implied("EURUSD"))                                                      # the pair upside down
    jumpy = ecb.implied("USDJPY") * 1.0
    jumpy.iloc[300:] *= 1.12                                                                         # a 12% step on one day
    gappy = _bars(ecb.implied("GBPINR")).drop(DAYS[100:150])                                         # fifty weekdays missing
    y.update(EURUSD=inverted, USDJPY=_bars(jumpy), GBPINR=gappy)
    man = FX.run_daily(tmp_path, ["EURUSD", "USDJPY", "GBPINR", "DXY"], "2024-01-01", TODAY, FakeYahoo(y), ecb, say=lambda *a: None)
    S = man["series"]
    assert S["EURUSD"]["status"] == "unverified" and any("match rate" in r for r in S["EURUSD"]["reasons"]) and S["EURUSD"]["crosscheck"]["mismatches"]
    assert S["USDJPY"]["status"] == "unverified" and len(S["USDJPY"]["jumps"]) == 1 and any("one-day move" in r for r in S["USDJPY"]["reasons"])
    assert S["GBPINR"]["gaps"]["missing"] == 50 and S["GBPINR"]["coverage"] == "gappy" and S["GBPINR"]["status"] == "verified"      # the values that exist agree with the ECB; the holes are reported
    assert S["DXY"]["status"] == "verified" and S["DXY"]["crosscheck"]["available"] and S["DXY"]["coverage"] == "complete"            # rebuilt from the ECB's basket
    assert set(man["unverified_series"]) == {"EURUSD", "USDJPY"} and man["gappy_series"] == ["GBPINR"] and man["status"] == "unverified"
    ecb2 = FX.EcbReference(fetch=lambda: _ecb_zip(drop=("CHF",)))                                    # a table without a basket currency: no index cross-check
    none = FX.run_daily(tmp_path / "n", ["DXY"], "2024-01-01", TODAY, FakeYahoo(y), ecb2, say=lambda *a: None)["series"]["DXY"]
    assert none["status"] == "unverified" and any("no independent source" in r for r in none["reasons"])


def test_a_one_day_bad_print_is_set_aside_and_listed_but_a_step_that_stays_and_a_flood_of_them_are_not():
    ecb = FX.EcbReference(fetch=_ecb_zip)
    imp = ecb.implied("EURUSD")
    bad = imp.copy()
    bad.iloc[200] *= 1.2                                                                             # one bad print
    y = FakeYahoo({"EURUSD": _bars(bad)})
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        s = FX.run_daily(Path(d), ["EURUSD"], "2024-01-01", TODAY, y, ecb, say=lambda *a: None)["series"]["EURUSD"]
        sh = pd.read_parquet(Path(d) / str(TODAY) / "fx_daily_2024.parquet")
    day = str(imp.index[200].date())
    assert [q["date"] for q in s["quarantined"]] == [day] and s["jumps"] == [] and s["status"] == "verified" and s["rows"] == len(imp) - 1
    assert pd.Timestamp(day) not in set(sh["date"]) and s["quarantined"][0]["close"] == pytest.approx(bad.iloc[200])           # gone from the data, kept in the manifest with its value
    step = imp.copy()
    step.iloc[300:] *= 1.12
    with tempfile.TemporaryDirectory() as d:
        t = FX.run_daily(Path(d), ["EURUSD"], "2024-01-01", TODAY, FakeYahoo({"EURUSD": _bars(step)}), ecb, say=lambda *a: None)["series"]["EURUSD"]
    assert "quarantined" not in t and t["status"] == "unverified"                                    # a level shift is never set aside
    many = imp.copy()
    many.iloc[10:200:8] *= 1.2                                                                       # a flood: more than 0.5% of the rows
    with tempfile.TemporaryDirectory() as d:
        m = FX.run_daily(Path(d), ["EURUSD"], "2024-01-01", TODAY, FakeYahoo({"EURUSD": _bars(many)}), ecb, say=lambda *a: None)["series"]["EURUSD"]
    assert "quarantined" not in m and m["status"] == "unverified"                                    # too much to tidy: the series is not trusted


def test_the_health_check_notes_gappy_series_without_failing_them():
    import datetime as dt2
    from quantdesk.data import health as H

    class Store:
        def tags(self, t): return ["fx-daily"]
        def assets(self, t): return ["2026-11-09_manifest.json"]
        def read(self, t, n): return json.dumps({"as_of": "2026-11-09", "series": {"A": {}, "B": {}}, "unverified_series": [], "gappy_series": ["B"]}).encode()
    c = H.check_fx_daily(Store(), dt2.date(2026, 11, 10))
    assert c.status == H.OK and "all verified" in c.detail and "B" in c.detail


def test_a_pair_that_is_down_is_recorded_and_the_others_still_run_and_a_down_ecb_is_recorded_not_raised(tmp_path):
    ecb, y = _world()
    man = FX.run_daily(tmp_path, ["EURUSD", "USDJPY"], "2024-01-01", TODAY, FakeYahoo(y, down={"USDJPY"}), ecb, say=lambda *a: None)
    assert man["series"]["USDJPY"]["status"] == "unverified" and "no source served" in man["series"]["USDJPY"]["reasons"][0] and man["series"]["EURUSD"]["status"] == "verified"
    dead = FX.EcbReference(fetch=lambda: (_ for _ in ()).throw(RuntimeError("ecb down")))
    man = FX.run_daily(tmp_path / "b", ["EURUSD"], "2024-01-01", TODAY, FakeYahoo(y), dead, say=lambda *a: None)
    s = man["series"]["EURUSD"]
    assert s["status"] == "unverified" and s["crosscheck"]["available"] is False and "ecb" in s["crosscheck"]["error"]               # never skipped silently


def _minutes(day="2026-11-06", n=2400, drop_from=None):
    idx = pd.date_range(f"{day} 00:00", periods=n, freq="min", tz="UTC")
    c = pd.Series(1.08 + np.sin(np.arange(n) / 50) * 0.002, index=idx)
    df = _bars(c, 0.0002)
    return df.drop(df.index[drop_from[0]:drop_from[1]]) if drop_from else df


def test_the_minute_run_writes_bars_and_a_manifest_and_records_a_failed_and_an_empty_pair(tmp_path):
    y = FakeYahoo(minutes={"EURUSD": _minutes(), "USDINR": _minutes(drop_from=(500, 560)), "GBPUSD": _minutes().iloc[0:0]}, down={"USDJPY"})
    man = FX.run_minutes(tmp_path, ["EURUSD", "USDINR", "GBPUSD", "USDJPY"], 5, TODAY, y, say=lambda *a: None)
    P = man["pairs"]
    assert man["totals"] == {"asked": 4, "served": 2, "failed": 1, "empty": 1}
    assert P["EURUSD"]["status"] == "served" and P["EURUSD"]["rows"] == 2400 and P["EURUSD"]["longest_gap_min"] == 1.0
    assert P["USDINR"]["rows"] == 2340 and P["USDINR"]["longest_gap_min"] == 61.0                     # the hour that was missing shows as a gap, never filled
    assert P["GBPUSD"]["status"] == "empty" and P["USDJPY"]["status"] == "failed" and "blocked" in P["USDJPY"]["error"]
    df = pd.read_parquet(tmp_path / "2026-11-09" / "fx_minutes.parquet")
    assert list(df.columns) == FX.COLS_MIN and set(df["symbol"]) == {"EURUSD", "USDINR"} and str(df["ts"].dt.tz) == "UTC" and len(df) == 4740
    assert json.loads((tmp_path / "2026-11-09" / "manifest.json").read_text())["totals"]["served"] == 2


def test_impossible_bars_are_dropped_and_counted_never_repaired(tmp_path):
    m = _minutes(n=100)
    m.iloc[10, m.columns.get_loc("high")] = m.iloc[10]["low"] - 0.01                                  # high below low
    man = FX.run_minutes(tmp_path, ["EURUSD"], 5, TODAY, FakeYahoo(minutes={"EURUSD": m}), say=lambda *a: None)
    assert man["pairs"]["EURUSD"]["rows"] == 99 and man["pairs"]["EURUSD"]["rejected_total"] == 1


def test_the_module_places_no_order_and_the_commands_never_fail_a_run():
    src = (ROOT / "quantdesk/data/fx.py").read_text(encoding="utf-8")
    assert not re.search(r"place_order|\.order\(|modify_order|cancel_order|/orders", src, re.I)
    assert not re.search(r"os\.environ|getenv|KITE_|KOTAK_|_SECRET|_TOKEN|Authorization", src)                  # it reads no credential: public sources only
    cli = (ROOT / "quantdesk/data/cli.py").read_text(encoding="utf-8")
    body = cli[cli.index("def cmd_fx_daily"):cli.index("def cmd_external_verify")]
    assert body.count("except Exception") == 2 and body.count("::warning::") >= 4 and body.count("clobber=False") == 2 and '"fx-daily"' in body


def test_the_fx_workflows_hold_no_secret_are_pinned_and_isolated():
    for name, group in (("fx-minutes", "fx-minutes"), ("fx-daily", "fx-daily")):
        text = (ROOT / ".github/workflows" / f"{name}.yml").read_text(encoding="utf-8")
        wf = yaml.safe_load(text)
        assert wf["permissions"] == {"contents": "write"} and wf["concurrency"]["group"] == group
        assert not re.findall(r"secrets\.\w+", text) and not re.search(r"KITE|KOTAK|LIVE_|TOTP|PASSWORD", text)         # public sources only: no secret of any kind
        for uses in re.findall(r"uses:\s*(\S+)", text):
            assert re.fullmatch(r"[\w./-]+@[0-9a-f]{40}", uses), uses
        assert "${{ inputs." not in "".join(st.get("run", "") for st in wf["jobs"]["fx"]["steps"])
    mins = yaml.safe_load((ROOT / ".github/workflows/fx-minutes.yml").read_text(encoding="utf-8"))
    on = mins.get("on", mins.get(True))
    assert on["schedule"] == [{"cron": "30 22 * * 1-5"}] and "workflow_dispatch" in on                  # 22:30 UTC on weekdays
    run = next(s for s in mins["jobs"]["fx"]["steps"] if "fx-minutes" in s.get("run", ""))
    assert run["env"]["DAYS"] == "${{ inputs.days || '5' }}" and '[[ "$DAYS" =~ ^[0-9]$ ]]' in run["run"] and "|| echo \"::warning::" in run["run"]
    daily = yaml.safe_load((ROOT / ".github/workflows/fx-daily.yml").read_text(encoding="utf-8"))
    assert list(daily.get("on", daily.get(True))) == ["workflow_dispatch"]                               # by hand: each run is a new immutable dataset


def test_a_daily_bar_stamped_at_london_midnight_keeps_its_own_date_in_summer_and_winter():
    """The first real run (7 Nov 2026): 14% of weekdays 'missing' in every series, because a summer bar stamped 00:00+01:00 became 23:00 UTC the day before and its date a Sunday."""
    london = pd.DatetimeIndex(["2024-07-01 00:00", "2024-07-02 00:00", "2024-01-08 00:00"], tz="Europe/London")
    assert [str(d.date()) for d in FX.local_dates(london)] == ["2024-07-01", "2024-07-02", "2024-01-08"]                  # summer Monday, summer Tuesday, winter Monday
    assert [str(d.date()) for d in london.tz_convert("UTC").normalize()][0] == "2024-06-30"                              # what the UTC route gave: a Sunday
    assert (FX.local_dates(london).dayofweek < 5).all()
    assert [str(d.date()) for d in FX.local_dates(pd.DatetimeIndex(["2024-07-01 13:00"]))] == ["2024-07-01"]               # a naive index is just normalised
    # and the gap check sees no gap in a run of weekdays stamped that way
    days = pd.bdate_range("2024-05-01", "2024-09-30")
    stamped = pd.DatetimeIndex([f"{d:%Y-%m-%d} 00:00" for d in days]).tz_localize("Europe/London")
    g = FX.gap_report(FX.local_dates(stamped), days.min(), days.max())
    assert g["missing"] == 0 and g["expected"] == len(days)
    g_bad = FX.gap_report(stamped.tz_convert("UTC").normalize(), days.min(), days.max())
    assert g_bad["missing"] > 50                                                                                         # the old route: dozens of "missing" summer weekdays


def test_the_yahoo_client_returns_daily_bars_on_their_own_dates_and_minute_bars_in_utc(monkeypatch):
    import sys
    import types
    days = pd.bdate_range("2024-06-24", "2024-07-05")
    daily_raw = pd.DataFrame({"Open": 1.0, "High": 1.1, "Low": 0.9, "Close": 1.05, "Volume": 0.0}, index=pd.DatetimeIndex([f"{d:%Y-%m-%d} 00:00" for d in days]).tz_localize("Europe/London"))
    mins_raw = pd.DataFrame({"Open": 1.0, "High": 1.1, "Low": 0.9, "Close": 1.05, "Volume": 0.0}, index=pd.date_range("2024-07-01 00:00", periods=5, freq="min", tz="Europe/London"))

    class Ticker:
        def __init__(self, t):
            self.t = t

        def history(self, **kw):
            return daily_raw if kw.get("interval") == "1d" else mins_raw
    monkeypatch.setitem(sys.modules, "yfinance", types.SimpleNamespace(Ticker=Ticker))
    y = FX.YahooFx(tries=1, sleep=lambda s: None)
    d = y.daily("EURUSD", dt.date(2024, 6, 24), dt.date(2024, 7, 5))
    assert [str(x.date()) for x in d.index] == [f"{x:%Y-%m-%d}" for x in days] and d.index.tz is None and d.index.name == "date"          # Monday 1 July stays Monday
    assert (d.index.dayofweek < 5).all() and FX.gap_report(d.index, days.min(), days.max())["missing"] == 0
    m = y.minutes("EURUSD", 5)
    assert str(m.index.tz) == "UTC" and m.index[0] == pd.Timestamp("2024-06-30 23:00", tz="UTC")                                           # an instant, in UTC


# ---- calibration found by the first real run: market holidays from the peers, the ECB tolerance, spikes vs steps, reviewed moves -------------------------------------------------------------
def _flat(days, v=1.0):
    return pd.DataFrame({"open": v, "high": v * 1.001, "low": v * 0.999, "close": v, "volume": 0.0}, index=days)


def test_a_weekday_missing_from_most_of_a_group_is_a_market_holiday_not_a_gap():
    hols = pd.DatetimeIndex(["2024-12-25", "2025-01-01", "2025-04-18", "2024-08-15"])                           # 25 Dec, 1 Jan, Good Friday, and an Indian holiday
    majors = pd.bdate_range("2024-01-01", "2025-06-30").difference(hols[:3])
    inr = pd.bdate_range("2024-01-01", "2025-06-30").difference(hols)                                           # the rupee pairs also miss 15 Aug
    dfs = {s: _flat(majors) for s in ("EURUSD", "GBPUSD", "USDJPY", "AUDUSD")}
    dfs.update({s: _flat(inr) for s in ("USDINR", "EURINR", "GBPINR")})
    dfs["USDCAD"] = _flat(majors.difference(pd.DatetimeIndex(["2024-03-12", "2024-03-13"])))                    # one pair with two real gaps of its own
    h = FX.peer_holidays(dfs)
    assert h["EURUSD"] == frozenset(hols[:3]) and h["USDINR"] == frozenset(hols)                                 # the groups keep their own calendars
    g = FX.gap_report(dfs["USDCAD"].index, dfs["USDCAD"].index.min(), dfs["USDCAD"].index.max(), h["USDCAD"])
    assert g["missing"] == 2 and g["missing_days"] == ["2024-03-12", "2024-03-13"]                              # only its own gaps count
    assert FX.gap_report(dfs["USDCAD"].index, dfs["USDCAD"].index.min(), dfs["USDCAD"].index.max())["missing"] == 5                       # without the calendar, the holidays count too
    assert FX.peer_holidays({"EURUSD": dfs["EURUSD"], "GBPUSD": dfs["GBPUSD"]})["EURUSD"] == frozenset()          # two pairs are not a calendar: nothing is inferred
    late = _flat(pd.bdate_range("2024-12-02", "2025-06-30").difference(hols[:3]))                                 # a pair that only started in December does not vote on earlier days
    assert FX.peer_holidays({**dfs, "NZDUSD": late})["NZDUSD"] == frozenset(hols[:3])


def test_a_close_within_two_percent_of_the_ecb_fixing_matches_and_an_inverted_pair_does_not(tmp_path):
    ecb = FX.EcbReference(fetch=_ecb_zip)
    imp = ecb.implied("EURUSD")
    rng = np.random.default_rng(3)
    noisy = imp * (1 + rng.uniform(-0.015, 0.015, len(imp)))                                                      # the fixing and the close differ by up to 1.5% on a volatile day
    assert FX.crosscheck(noisy, imp)["match_rate"] == 1.0 and FX.crosscheck(imp * 1.03, imp)["match_rate"] == 0.0
    jpy = ecb.implied("USDJPY")                                                                                   # far from parity, so an inverse cannot match by luck
    assert FX.crosscheck(1 / jpy, jpy)["match_rate"] == 0.0 and FX.XCHECK_TOL == 0.02


def test_a_spike_that_reverses_is_labelled_a_likely_bad_print_and_a_step_is_not():
    idx = pd.bdate_range("2024-01-01", periods=40)
    c = pd.Series(1.0, index=idx)
    spike, step = c.copy(), c.copy()
    spike.iloc[10] = 1.12                                                                                        # one bad print
    step.iloc[20:] = 1.12                                                                                        # a real level shift that stays
    f_spike, _ = FX.find_jumps(spike, "EURUSD")
    f_step, _ = FX.find_jumps(step, "EURUSD")
    assert [j["reverted"] for j in f_spike] == [True, True] and [j["reverted"] for j in f_step] == [False]       # the spike jumps up and back down (two flagged days)
    why = FX.decide({"rows": 40, "gaps": {"fraction": 0.0, "missing": 0}, "jumps": f_spike, "crosscheck": {"available": True, "compared": 200, "match_rate": 1.0}})[1]
    assert any("reverse within two days (likely bad prints)" in r for r in why)


def test_a_move_a_person_reviewed_is_listed_apart_and_lets_the_series_verify(tmp_path):
    ecb = FX.EcbReference(fetch=_ecb_zip)
    ecb.table().loc[ecb.table().index[300:], "JPY"] *= 1.12                                                      # the ECB's yen steps too: a genuine move both sources show
    imp = ecb.implied("USDJPY")
    y = FakeYahoo({"USDJPY": _bars(imp)})
    d = str(imp.index[300].date())
    open_ = FX.run_daily(tmp_path / "a", ["USDJPY"], "2024-01-01", TODAY, y, ecb, say=lambda *a: None)
    assert open_["series"]["USDJPY"]["status"] == "unverified" and [j["date"] for j in open_["series"]["USDJPY"]["jumps"]] == [d]
    rev = FX.run_daily(tmp_path / "b", ["USDJPY"], "2024-01-01", TODAY, y, ecb, say=lambda *a: None, accepted=frozenset({("USDJPY", d)}))
    s = rev["series"]["USDJPY"]
    assert s["jumps"] == [] and [j["date"] for j in s["accepted_moves"]] == [d] and s["status"] == "verified"
    assert FX.find_jumps(imp, "EURUSD", frozenset({("USDJPY", d)}))[1] == []                                     # a review of another pair does not apply
    cli = (ROOT / "quantdesk/data/cli.py").read_text(encoding="utf-8")
    assert 'cfg.get("fx.accepted_moves")' in cli and "accepted=accepted" in cli
    from quantdesk.config import DEFAULT_CONFIG, Config
    assert Config.load(DEFAULT_CONFIG).get("fx.accepted_moves") == []                                           # the shipped list is empty: nothing is accepted until a person reviews it
