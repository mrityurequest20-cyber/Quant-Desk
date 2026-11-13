"""The news analyser (owner, 13 Nov 2026): the digest's EVENT WATCH (quantdesk/premarket/newsdigest.py), the past episodes measured from the warehouse (history.macro_history,
with geopolitical shocks and oil shocks), and AUTO v2's EVENT REGIME, where news and data meet: no volatility is sold into an event."""
from __future__ import annotations

import datetime as dt

import pandas as pd
import pytest

from quantdesk.paper import auto2 as A2
from quantdesk.premarket import history as H
from quantdesk.premarket import newsdigest as ND

NOW = pd.Timestamp("2026-11-16 10:00", tz="Asia/Kolkata")


def story(title, event, impact="high", novelty=1.0, tone=-0.6, mins=10, recap=False):
    ts = (NOW - pd.Timedelta(minutes=mins)).tz_convert("UTC").strftime("%Y-%m-%dT%H:%M:%SZ")
    return {"title": title, "event": event, "impact": impact, "novelty": novelty, "tone": tone, "ts": ts, "recap": recap}


def test_fresh_high_impact_stories_make_a_high_event_and_old_or_recap_ones_do_not():
    rows = [story("Missiles strike near border, troops mobilised", "geopolitics"), story("Air strikes reported overnight", "geopolitics"),
            story("Ceasefire talks stall", "geopolitics", impact="medium")]
    ev = ND.event_watch(rows, NOW)
    assert ev[0]["type"] == "geopolitics" and ev[0]["level"] == "high" and ev[0]["kind"] == "geopolitics" and ev[0]["tone"] < 0 and ev[0]["n"] == 3
    old = [story("Missiles strike near border", "geopolitics", mins=11 * 60), story("Air strikes", "geopolitics", mins=11 * 60)]
    assert ND.event_watch(old, NOW) == []                                                        # eleven hours on, a 4-hour half-life leaves little
    assert ND.event_watch([story("War stocks recap: markets close lower", "geopolitics", recap=True)] * 5, NOW) == []


def test_a_policy_event_is_matched_to_the_rbi_or_the_fed_by_its_words():
    ev = ND.event_watch([story("RBI cuts repo rate by 50 bps in surprise move", "policy", tone=0.7)] * 3, NOW)
    assert ev[0]["kind"] == "rbi" and ev[0]["tone"] > 0
    assert ND.event_watch([story("Fed holds rates, signals cuts", "policy")] * 3, NOW)[0]["kind"] == "fomc"


def test_past_episodes_are_measured_with_their_direction_not_only_their_size():
    days = pd.bdate_range("2021-01-01", periods=300)
    close = [100.0 * (1.001 ** i) for i in range(300)]
    shock = days[150]
    close = [c * (0.97 if d >= shock else 1.0) for c, d in zip(close, days)]                     # a 3% fall on the shock day, which holds
    ic = pd.DataFrame({"date": days, "symbol": "NIFTY", "close": close})
    got = H.macro_history(ic, {"kinds": {"geopolitics": {"reacts": "same_session", "dates": [shock.strftime("%Y-%m-%d")]}}})["geopolitics"]["NIFTY"]
    assert got["n"] == 1 and got["median_ret"] == pytest.approx(0.97 * 1.001 - 1, abs=1e-4) and got["share_down"] == 1.0 and got["worst"] < -0.02
    assert got["median_5d"] == pytest.approx(0.97 * 1.001 ** 5 - 1, abs=1e-4)
    assert {"geopolitics", "oil_shock"} <= set(H.macro_dates()["kinds"])


def _ap(brief=None):
    ap = A2.AutoPilotV2(("NIFTY",), {"NIFTY": 65}, lambda *a: 20.0, None)
    ap.brief = brief
    return ap


GEO = {"events": [{"type": "geopolitics", "severity": 3.4, "level": "high", "tone": -0.55, "n": 4, "top": ["Missiles"], "kind": "geopolitics"}]}
BRIEF = {"analogs": {"geopolitics": {"NIFTY": {"n": 14, "median_ret": -0.009, "share_down": 0.71, "worst": -0.048, "median_5d": 0.004}}}}


def test_a_high_geopolitical_event_is_the_event_regime_with_what_happened_before():
    regime, why = _ap(BRIEF).regime("NIFTY", GEO, None)
    assert regime == "event" and "geopolitics" in why and "the last 14 geopolitics episodes: NIFTY median -0.9% on the day, fell 10 of 14, worst -4.8%" in why
    assert _ap().regime("NIFTY", {"events": [{**GEO["events"][0], "level": "watch"}]}, None)[0] == "normal"
    assert _ap().regime("NIFTY", None, {"event_priced": True})[0] == "event"                  # the options price an event the news has not named


def test_an_oil_event_touches_mcx_and_a_currency_event_touches_currency_only():
    ap = A2.AutoPilotV2(("NIFTY", "CRUDEOIL", "USDINR"), {"NIFTY": 65, "CRUDEOIL": 100, "USDINR": 1000}, lambda *a: 20.0, None,
                        segments={"CRUDEOIL": "mcx", "USDINR": "nse_cds"})
    oil = {"events": [{"type": "commodities", "severity": 3.0, "level": "high", "tone": -0.4, "n": 3, "top": [], "kind": "oil_shock"}]}
    fx = {"events": [{"type": "currency", "severity": 3.0, "level": "high", "tone": -0.4, "n": 3, "top": [], "kind": None}]}
    assert ap.regime("CRUDEOIL", oil, None)[0] == "event" and ap.regime("NIFTY", oil, None)[0] == "event" and ap.regime("USDINR", oil, None)[0] == "normal"
    assert ap.regime("USDINR", fx, None)[0] == "event" and ap.regime("CRUDEOIL", fx, None)[0] == "normal"


def test_no_volatility_is_sold_into_an_event():
    ap = _ap()
    st = {"view": "flat", "vol": "mid", "eve": False, "near": dt.date(2026, 11, 17), "next": dt.date(2026, 11, 24), "regime": "event"}
    ic = A2.BY_SID["IC1.faan.1/0.5.d"]
    assert not ap.matches(ic, st) and ap.matches(ic, {**st, "regime": "normal"})
    longs = [s for s in A2.CATALOGUE if s.view == "flat" and s.struct not in A2.SHORT_VOL and ap.matches(s, st)]
    assert longs                                                                                # bought volatility (straddles, strangles) is still open to it
