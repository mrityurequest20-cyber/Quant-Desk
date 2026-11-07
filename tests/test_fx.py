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


def _ecb_zip(days=DAYS) -> bytes:
    rng = np.random.default_rng(7)
    walk = lambda x0, s: x0 * np.exp(np.cumsum(rng.normal(0, s, len(days))))                      # noqa: E731
    t = pd.DataFrame({"Date": days.strftime("%Y-%m-%d"), "USD": walk(1.08, 0.004), "JPY": walk(160.0, 0.004), "GBP": walk(0.85, 0.003), "INR": walk(90.0, 0.003)})
    csv = t.to_csv(index=False).replace("\n", ",\n")                                                # the real file ends every row with a comma
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
    y = {"EURUSD": _bars(eurusd * 1.003), "USDJPY": _bars(usdjpy * 0.997), "DXY": _bars(pd.Series(104.0, index=DAYS))}
    y.update(tweak)
    return ecb, y


def test_the_ecb_table_implies_each_pair_from_the_euro_rates_and_has_nothing_for_the_dollar_index():
    ecb = FX.EcbReference(fetch=_ecb_zip)
    t = ecb.table()
    assert t["EUR"].eq(1.0).all() and {"USD", "JPY", "GBP", "INR"} <= set(t.columns) and not any(c.startswith("Unnamed") for c in t.columns)
    assert np.allclose(ecb.implied("EURUSD"), t["USD"])                                              # EURUSD is the dollars per euro
    assert np.allclose(ecb.implied("USDJPY"), t["JPY"] / t["USD"])                                  # dollar-yen is yen per euro over dollars per euro
    assert np.allclose(ecb.implied("GBPINR"), t["INR"] / t["GBP"]) and np.allclose(ecb.implied("EURINR"), t["INR"])
    assert ecb.implied("DXY") is None and ecb.implied("EURXYZ") is None                              # no such currency in the table
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


def test_an_inverted_pair_a_jump_a_gap_and_a_pair_without_an_independent_source_are_each_not_verified_with_the_reason(tmp_path):
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
    assert S["GBPINR"]["status"] == "unverified" and S["GBPINR"]["gaps"]["missing"] == 50 and any("missing weekdays" in r for r in S["GBPINR"]["reasons"])
    assert S["DXY"]["status"] == "unverified" and any("no independent source" in r for r in S["DXY"]["reasons"]) and S["DXY"]["crosscheck"]["available"] is False
    assert set(man["unverified_series"]) == {"EURUSD", "USDJPY", "GBPINR", "DXY"} and man["status"] == "unverified"


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
