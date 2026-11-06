"""The market map (quantdesk/markets/sessions.py): hours per segment, the MCX close that follows the US clock change, the two
ways of treating an unverified holiday calendar (recording vs trading), and the chained jobs that cover a day."""
import datetime as dt
import json
import subprocess
import sys
from pathlib import Path

import pytest

from quantdesk.config import Config
from quantdesk.markets import sessions as S

ROOT = Path(__file__).resolve().parents[1]


def at(s):
    return dt.datetime.fromisoformat(s).replace(tzinfo=S.IST)


@pytest.fixture(scope="module")
def cal():
    return S.Calendars(Config.load(ROOT / "config" / "quantdesk.yaml"))


def test_us_daylight_saving_follows_the_march_and_november_changes():
    assert S.us_dst(dt.date(2026, 3, 8)) is True and S.us_dst(dt.date(2026, 3, 7)) is False         # second Sunday of March 2026
    assert S.us_dst(dt.date(2026, 10, 31)) is True and S.us_dst(dt.date(2026, 11, 1)) is False      # first Sunday of November 2026
    assert S.us_dst(dt.date(2026, 7, 1)) is True and S.us_dst(dt.date(2026, 12, 15)) is False
    assert S.us_dst(dt.date(2027, 3, 14)) is True and S.us_dst(dt.date(2027, 3, 13)) is False       # 2027: second Sunday is the 14th


def test_mcx_closes_at_2355_in_us_summer_and_2330_in_us_winter(cal):
    assert S.session("mcx", dt.date(2026, 10, 30), cal)[1].time() == dt.time(23, 55)                # Friday before the change
    assert S.session("mcx", dt.date(2026, 11, 2), cal)[1].time() == dt.time(23, 30)                 # Monday after it
    assert S.session("mcx", dt.date(2027, 3, 12), cal)[1].time() == dt.time(23, 30)
    assert S.session("mcx", dt.date(2027, 3, 15), cal)[1].time() == dt.time(23, 55)


def test_hours_per_segment(cal):
    d = dt.date(2026, 11, 9)                                                                        # a Monday, not a holiday
    assert [(k, S.session(k, d, cal)[0].strftime("%H:%M"), S.session(k, d, cal)[1].strftime("%H:%M")) for k in S.SEGMENTS] == [
        ("nse_fo", "09:15", "15:30"), ("bse_fo", "09:15", "15:30"), ("nse_cds", "09:00", "17:00"), ("mcx", "09:00", "23:30")]
    assert S.open_segments(at("2026-11-09 08:59"), cal) == []
    assert S.open_segments(at("2026-11-09 09:00"), cal) == ["nse_cds", "mcx"]
    assert S.open_segments(at("2026-11-09 10:00"), cal) == ["nse_fo", "bse_fo", "nse_cds", "mcx"]
    assert S.open_segments(at("2026-11-09 15:30"), cal) == ["nse_cds", "mcx"]                       # the close is exclusive
    assert S.open_segments(at("2026-11-09 17:00"), cal) == ["mcx"]
    assert S.open_segments(at("2026-11-09 23:30"), cal) == []


def test_nothing_trades_at_the_weekend_or_on_an_nse_holiday(cal):
    assert S.day_window(dt.date(2026, 11, 7), cal) is None and S.day_window(dt.date(2026, 11, 8), cal) is None      # Sat, Sun
    assert S.session("nse_fo", dt.date(2026, 11, 10), cal) is None                                                  # Diwali Balipratipada
    assert S.session("bse_fo", dt.date(2026, 11, 10), cal) is None


def test_an_unverified_calendar_records_but_does_not_trade(cal):
    d = dt.date(2026, 11, 9)
    assert not cal.known("mcx", d) and not cal.known("nse_cds", d) and cal.known("nse_fo", d)
    assert S.session("mcx", d, cal, trading=False) is not None                                      # recording: open by default
    assert S.session("mcx", d, cal, trading=True) is None                                           # trading: not until verified
    assert S.open_segments(at("2026-11-09 20:00"), cal, trading=True) == []
    assert S.open_segments(at("2026-11-09 20:00"), cal, trading=False) == ["mcx"]
    assert S.open_segments(at("2026-11-09 10:00"), cal, trading=True) == ["nse_fo", "bse_fo"]       # NSE and BSE are verified for 2026


def test_a_year_without_an_nse_list_is_unverified_for_trading_too(cal):
    d = dt.date(2027, 1, 4)                                                                         # a Monday in a year the config does not list
    assert not cal.known("nse_fo", d)
    assert S.session("nse_fo", d, cal, trading=True) is None and S.session("nse_fo", d, cal) is not None


def test_a_verified_own_calendar_trades_and_honours_its_holidays():
    cfg = Config.load(ROOT / "config" / "quantdesk.yaml", overrides={"markets": {"mcx": {"holiday_years": [2026], "holidays": ["2026-11-09"]}}})
    cal = S.Calendars(cfg)
    assert S.session("mcx", dt.date(2026, 11, 9), cal, trading=True) is None                        # its own holiday, even for recording
    assert S.session("mcx", dt.date(2026, 11, 9), cal) is None
    assert S.session("mcx", dt.date(2026, 11, 11), cal, trading=True) is not None                   # verified year, not a holiday


@pytest.mark.parametrize("day", ["2026-11-09", "2026-10-30", "2026-07-01", "2027-03-15", "2026-12-24"])
def test_the_chained_jobs_cover_every_open_minute_with_no_gap_and_none_too_long(cal, day):
    d = dt.date.fromisoformat(day)
    jobs = S.plan_jobs(d, cal)
    assert jobs and all(j["minutes"] <= 330 for j in jobs)
    assert jobs[0]["from"] == (S.day_window(d, cal)[0] - dt.timedelta(minutes=25)).isoformat()
    assert jobs[-1]["until"] == (S.day_window(d, cal)[1] + dt.timedelta(minutes=5)).isoformat()
    for a, b in zip(jobs, jobs[1:]):
        assert a["until"] == b["from"]                                                              # each starts where the last ended
    assert [j["n"] for j in jobs] == list(range(1, len(jobs) + 1)) and {j["of"] for j in jobs} == {len(jobs)}
    for k in S.SEGMENTS:                                                                            # every open minute of every segment is inside a job
        s = S.session(k, d, cal)
        if s:
            assert jobs[0]["from"] <= s[0].isoformat() and s[1].isoformat() <= jobs[-1]["until"]
            assert any(k in j["segments"] for j in jobs)


def test_a_normal_day_is_three_jobs_and_a_holiday_or_weekend_is_none(cal):
    assert [j["minutes"] for j in S.plan_jobs(dt.date(2026, 11, 9), cal)] == [300, 300, 300]
    assert S.plan_jobs(dt.date(2026, 11, 8), cal) == [] and S.plan_jobs(dt.date(2026, 11, 7), cal) == []
    assert S.plan_jobs(dt.date(2026, 11, 9), cal, trading=True)[0]["segments"] == ["nse_fo", "bse_fo"]
    nse_only = S.plan_jobs(dt.date(2026, 11, 9), cal, trading=True)                                 # only the verified NSE/BSE hours: 08:50-15:35
    assert [j["from"][11:16] for j in nse_only] == ["08:50", "12:12"] and nse_only[-1]["until"][11:16] == "15:35"   # 405 min > 330: two jobs


def test_the_market_map_touches_nothing_it_should_not():
    import re
    for f in (ROOT / "quantdesk" / "markets").glob("*.py"):
        src = f.read_text(encoding="utf-8")
        assert not re.search(r"^\s*(from|import)\s+(\.\.?\s*)?(quantdesk\.)?(intraday|execution|journal|risk|learnbot|web|data)\b", src, re.M), f.name
        for bad in ("requests", "urllib", "socket", "subprocess", "os.environ", "secrets.", "place_order", "KITE_", "KOTAK_"):
            assert bad not in src, (f.name, bad)


def test_the_cli_prints_the_day_and_the_plan():
    out = subprocess.run([sys.executable, "-m", "quantdesk", "markets", "today", "--date", "2026-11-09"], cwd=ROOT, capture_output=True, text=True)
    assert out.returncode == 0 and "mcx" in out.stdout and "09:00-23:30" in out.stdout and "NOT verified" in out.stdout
    plan = subprocess.run([sys.executable, "-m", "quantdesk", "markets", "plan", "--date", "2026-11-09"], cwd=ROOT, capture_output=True, text=True)
    assert plan.returncode == 0 and len(json.loads(plan.stdout)) == 3
