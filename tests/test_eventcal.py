"""The scheduled-events calendar (quantdesk/paper/eventcal.py; owner, 14 Nov 2026: "A scheduled-events calendar"): the owner's dates, the recurring releases by rule with
the US daylight-saving switch, which instruments each event touches, and AUTO v2 selling no volatility into a scheduled event."""
from __future__ import annotations

import datetime as dt

import pandas as pd

from quantdesk.paper import auto2 as A2
from quantdesk.paper import eventcal as EC

IST = EC.IST


def at(s):
    return dt.datetime.fromisoformat(s).replace(tzinfo=IST)


def test_new_york_times_follow_the_us_clock_change():
    assert not EC.us_dst(dt.date(2026, 11, 6)) and EC.us_dst(dt.date(2026, 7, 3)) and not EC.us_dst(dt.date(2026, 3, 7)) and EC.us_dst(dt.date(2026, 3, 9))
    assert EC.ny_to_ist(dt.date(2026, 11, 6), 8, 30).strftime("%H:%M") == "19:00"          # EST: payrolls at 19:00 IST
    assert EC.ny_to_ist(dt.date(2026, 7, 3), 8, 30).strftime("%H:%M") == "18:00"           # EDT: an hour earlier


def test_rules_fill_the_routine_releases_and_the_owners_date_wins():
    ev = EC.rule_events(dt.date(2026, 12, 1), 14)
    names = [(e["at"][:16], e["name"]) for e in ev]
    assert ("2026-12-04T19:00", "US jobs report (non-farm payrolls)") in names                # the first Friday
    assert ("2026-12-02T21:00", "EIA crude oil inventories") in names and ("2026-12-09T21:00", "EIA crude oil inventories") in names
    assert ("2026-12-12T16:00", "India CPI") in names and all(e["source"] == "rule" for e in ev)
    cal = EC.build(at("2026-12-01 08:00"), [(dt.date(2026, 12, 12), dt.time(17, 30), "India CPI (Nov)"), (dt.date(2026, 12, 4), dt.time(10, 0), "RBI MPC decision")], days=14)
    cpi = [e for e in cal if e["kind"] == "india_cpi"]
    assert len(cpi) == 1 and cpi[0]["source"] == "config" and cpi[0]["at"].startswith("2026-12-12T17:30")      # the owner's date replaces the rule's
    assert [e["at"] for e in cal] == sorted(e["at"] for e in cal)
    assert EC.classify("US FOMC decision")[:2] == ("fomc", "high") and EC.classify("Union Budget")[:2] == ("budget", "high")


def test_each_event_touches_the_instruments_it_moves():
    rbi = {"name": "RBI MPC decision", "kind": "rbi", "impact": "high", "subjects": ["rbi"]}
    eia = {"name": "EIA crude oil inventories", "kind": "eia", "impact": "medium", "subjects": ["crude"]}
    budget = {"name": "Union Budget", "kind": "budget", "impact": "high", "subjects": []}
    res = {"name": "TCS results", "kind": "results", "impact": "medium", "subjects": [], "symbols": ["TCS"]}
    assert EC.touches("BAJFINANCE", rbi) >= 0.5 and EC.touches("GOLD", rbi) == 0
    assert EC.touches("CRUDEOIL", eia) == 1.0 and EC.touches("NIFTY", eia) == 0.3                 # crude reaches the index, but too weakly for a routine release
    assert EC.touches("ITC", budget) == 1.0 and EC.touches("CRUDEOIL", budget) == 0.0
    assert EC.touches("TCS", res) == 1.0 and EC.touches("NIFTY", res) == 0.3 and EC.touches("INFY", res) == 0


def test_the_regime_window_is_a_day_before_a_decision_and_hours_around_a_release():
    cal = EC.build(at("2026-11-30 08:00"), [(dt.date(2026, 12, 4), dt.time(10, 0), "RBI MPC decision"), (dt.date(2026, 12, 10), dt.time(19, 0), "US CPI (Nov)")], days=12)
    assert "RBI MPC decision at 10:00 on 04 Dec" in EC.regime("NIFTY", cal, at("2026-12-03 12:00"))
    assert EC.regime("NIFTY", cal, at("2026-12-02 12:00")) is None                                  # more than a day ahead
    assert "passed" in EC.regime("NIFTY", cal, at("2026-12-04 11:00")) and EC.regime("NIFTY", cal, at("2026-12-04 12:00")) is None
    assert EC.regime("CRUDEOIL", cal, at("2026-12-02 19:30")).startswith("scheduled: EIA") and EC.regime("NIFTY", cal, at("2026-12-02 19:30")) is None
    assert EC.regime("USDINR", cal, at("2026-12-10 18:00")) and EC.regime("NIFTY", cal, at("2026-12-10 18:00")) is None


def test_auto_v2_sells_no_volatility_into_a_scheduled_event_and_the_brief_lists_the_week():
    ap = A2.AutoPilotV2(("NIFTY",), {"NIFTY": 65}, lambda *a: 0.0, None)
    ap.brief = {"calendar": EC.build(at("2026-12-01 08:00"), [(dt.date(2026, 12, 4), dt.time(10, 0), "RBI MPC decision")], days=7)}
    regime, why = ap.regime("NIFTY", None, None, None, at("2026-12-03 14:00"))
    assert regime == "event" and "RBI MPC decision" in why
    assert ap.regime("NIFTY", None, None, None, at("2026-12-01 14:00"))[0] == "normal"
    from quantdesk.intraday import events as EV
    from quantdesk.premarket import brief as B
    inp = B.Inputs(now=pd.Timestamp("2026-12-01 06:30", tz="Asia/Kolkata"), macro_events=[EV.Event(dt.date(2026, 12, 4), "RBI MPC decision", dt.time(10, 0))])
    cal = B._calendar(inp, inp.now, [{"symbol": "NIFTY"}], [])
    assert any(e["name"] == "RBI MPC decision" and e["source"] == "config" for e in cal) and any(e["name"] == "NIFTY options expire" for e in cal)
    lines = B.summary({"session": "2026-12-01", "last_close": "2026-11-30", "data_stale": False, "expiring": [], "macro": [], "results": [], "global": [], "watch": [],
                       "calendar": cal})
    assert any(line.startswith("Coming up: ") and "RBI MPC decision" in line and "(by rule: check)" in line for line in lines)
