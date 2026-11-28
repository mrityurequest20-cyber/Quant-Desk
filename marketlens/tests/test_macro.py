"""The global macro calendar: parsing the sources, the reacting session, event studies, the forward calendar."""
import json

import numpy as np
import pandas as pd
import pytest

from marketlens.engine import macro as MX
from quantdesk.data import macro as M

FF = json.dumps([
    {"title": "CPI m/m", "country": "USD", "date": "2026-12-10T08:30:00-05:00", "impact": "High", "forecast": "0.3%", "previous": "0.2%"},
    {"title": "Federal Funds Rate", "country": "USD", "date": "2026-12-16T14:00:00-05:00", "impact": "High", "forecast": "3.50%", "previous": "3.75%"},
    {"title": "Main Refinancing Rate", "country": "EUR", "date": "2026-12-17T08:15:00-05:00", "impact": "High", "forecast": "2.00%", "previous": "2.00%"},
    {"title": "Bank Holiday", "country": "JPY", "date": "2026-12-23T00:00:00-05:00", "impact": "Holiday", "forecast": "", "previous": ""},
])

FED = """<h4><a>2026 FOMC Meetings</a></h4>
<div class="row fomc-meeting"><div class="fomc-meeting__month col-xs-5"><strong>January</strong></div><div class="fomc-meeting__date col-xs-4">27-28</div></div>
<div class="row fomc-meeting"><div class="fomc-meeting__month col-xs-5"><strong>Oct/Nov</strong></div><div class="fomc-meeting__date col-xs-4">31-1*</div></div>
<div class="row fomc-meeting"><div class="fomc-meeting__month col-xs-5"><strong>December</strong></div><div class="fomc-meeting__date col-xs-4">15-16*</div></div>
<h4><a>2025 FOMC Meetings</a></h4>
<div class="row fomc-meeting"><div class="fomc-meeting__month col-xs-5"><strong>March</strong></div><div class="fomc-meeting__date col-xs-4">18-19*</div></div>"""


def test_forex_factory_times_become_ist_and_kinds_are_named():
    d = M.parse_ff(FF)
    cpi = d.iloc[0]
    assert (str(cpi.date.date()), cpi.time_ist, cpi.kind, cpi.forecast) == ("2026-12-10", "19:00", "us_cpi", "0.3%")   # 08:30 ET = 19:00 IST
    assert d.iloc[1].kind == "fomc" and d.iloc[1].time_ist == "00:30" and str(d.iloc[1].date.date()) == "2026-12-17"  # 14:00 ET = 00:30 IST next day
    assert d.iloc[2].kind == "ecb" and d.iloc[3].time_ist == ""                          # an all-day item has no time


def test_fed_page_gives_the_decision_day_including_a_meeting_across_two_months():
    d = M.parse_fed(FED)
    days = sorted(str(x.date()) for x in d["date"])
    assert days == ["2025-03-19", "2026-01-29", "2026-11-02", "2026-12-17"]   # 14:00 New York: 23:30 IST in US summer time, 00:30 the next day in winter
    assert (d["kind"] == "fomc").all() and d["title"].str.contains("projections").sum() == 3


def test_india_release_rules_skip_weekends():
    d = M.india_rules(pd.Timestamp("2026-07-01").date(), pd.Timestamp("2026-09-30").date())
    cpi = d[d["kind"] == "india_cpi"]["date"].dt.date.astype(str).tolist()
    assert cpi == ["2026-07-13", "2026-08-12", "2026-09-14"]                                # 12 Jul and 12 Sep 2026 are a Sunday and a Saturday
    assert d[d["kind"] == "india_gdp"]["date"].dt.date.astype(str).tolist() == ["2026-08-31"]


@pytest.mark.parametrize("t,kind,expect", [("10:00", "rbi", "2026-03-04"), ("19:00", "us_cpi", "2026-03-05"), ("", "fomc", "2026-03-05"),
                                           ("", "budget", "2026-03-04"), ("08:00", "boj", "2026-03-04")])
def test_reacting_session(t, kind, expect):
    s = pd.bdate_range("2026-03-02", periods=10)
    assert str(s[MX.reacting_session(pd.Timestamp("2026-03-04"), t, kind, s)].date()) == expect


def test_study_measures_move_priced_and_iv_change():
    s = pd.bdate_range("2024-01-01", periods=400)
    rng = np.random.default_rng(3)
    r = pd.Series(rng.normal(0, 0.01, len(s)), index=s)
    iv = pd.Series(0.16, index=s)
    days = s[50::60][:6]
    for d in days:                                                       # US CPI at 19:00 IST: the next session reacts
        j = s.get_loc(d) + 1
        r.iloc[j] = 0.03
        iv.iloc[j] = 0.13
    close = 100 * np.exp(r.cumsum())
    ev = MX.events(pd.DataFrame({"date": days, "time_ist": "19:00", "country": "USD", "title": "CPI m/m", "kind": "us_cpi",
                                 "impact": "High", "forecast": "", "previous": "", "source": "forexfactory"}))
    out = {x["kind"]: x for x in MX.study(close, iv, ev, s[-1])}
    u = out["us_cpi"]
    assert u["n"] == 6 and u["median_move"] == pytest.approx(0.03) and u["beat_priced"] == 1.0
    assert u["d_iv"] == pytest.approx(-0.03) and u["ratio"] > 3


def test_upcoming_keeps_the_important_ones_once():
    ev = MX.events(pd.concat([M.parse_ff(FF), M.parse_fed(FED)]))
    up = MX.upcoming(ev, pd.Timestamp("2026-12-01"), days=30)
    assert [x["kind"] for x in up] == ["us_cpi", "fomc", "ecb"]                            # the Fed's page and FF list one meeting once
