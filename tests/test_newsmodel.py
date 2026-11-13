"""The news model (quantdesk/paper/newsmodel.py) and the situation-weighted analogues (quantdesk/premarket/analogs.py), owner, 13 Nov 2026: "The news analyser must be
sophisticated that it understand past and present situations well so that it can accurately predict the future ... Models should read differently as per the instrument"."""
from __future__ import annotations

import datetime as dt
import math
import random

import pandas as pd
import pytest

from quantdesk.paper import auto2 as A2
from quantdesk.paper import newsmodel as NM
from quantdesk.premarket import analogs as AN

NOW = dt.datetime(2026, 11, 16, 4, 30, tzinfo=dt.timezone.utc).timestamp()


def story(title, mins=10, impact="high", tone=0.0, symbols=(), recap=False):
    ts = dt.datetime.fromtimestamp(NOW - mins * 60, tz=dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {"title": title, "ts": ts, "impact": impact, "novelty": 1.0, "tone": tone, "symbols": list(symbols), "recap": recap}


@pytest.mark.parametrize("title, want", [
    ("Brent jumps 6% after drone strikes on Gulf oil facilities", {("crude", 1), ("geopolitics", 1)}),
    ("Rupee hits record low of 88.9 against the dollar", {("rupee", -1)}),
    ("RBI cuts repo rate by 25 bps, signals more easing", {("rbi", -1)}),
    ("Ceasefire agreed as border talks resume", {("geopolitics", -1)}),
    ("Gold prices slip as dollar index climbs", {("gold", -1), ("dollar", 1)}),
    ("SEBI tightens F&O norms for weekly expiries", {("fno_rules", 1)}),
    ("FIIs net sold Rs 4,200 crore on Friday", {("fii", -1)}),
    ("Monsoon rainfall 8% above normal", {("monsoon", 1)}),
    ("Treasury yields climb to 4.8%", {("us_yields", 1)}),
])
def test_it_reads_what_a_headline_is_about_and_which_way(title, want):
    assert set(NM.subjects(title)) == want


def test_one_story_moves_each_instrument_its_own_way():
    dig = {"items": [story("Brent jumps 6% after drone strikes on Gulf oil facilities")]}
    f = {u: NM.forecast(u, dig, None, NOW) for u in ("CRUDEOIL", "USDINR", "GOLD", "NIFTY", "MIDCPNIFTY", "TCS")}
    assert f["CRUDEOIL"]["vote"] == 1 and f["USDINR"]["vote"] == 1 and f["GOLD"]["vote"] == 1
    assert f["NIFTY"]["vote"] == -1 and f["MIDCPNIFTY"]["p_up"] < f["NIFTY"]["p_up"] < 0.5          # mid caps take risk-off harder
    assert f["TCS"]["p_up"] == 0.5 and f["TCS"]["why"] == []                                    # nothing in this story reaches an IT exporter
    assert "crude up (it is crude)" in f["CRUDEOIL"]["why"][0]
    calm = {"items": [story("Ceasefire agreed as border talks resume")]}
    assert NM.forecast("GOLD", calm, None, NOW)["p_up"] < 0.5 < NM.forecast("NIFTY", calm, None, NOW)["p_up"]


def test_age_recaps_and_named_stories():
    old = {"items": [story("Brent jumps 6% after drone strikes", mins=5 * 60)]}
    fresh = {"items": [story("Brent jumps 6% after drone strikes", mins=5)]}
    assert NM.forecast("CRUDEOIL", old, None, NOW)["score"] < NM.forecast("CRUDEOIL", fresh, None, NOW)["score"] / 3     # two-hour half-life
    assert NM.forecast("CRUDEOIL", {"items": [story("Brent jumps 6%", recap=True)]}, None, NOW)["score"] == 0
    assert NM.forecast("CRUDEOIL", {"items": [story("Brent jumps 6%", mins=7 * 60)]}, None, NOW)["score"] == 0          # older than six hours
    named = {"items": [story("Infosys wins $1.5 bn deal", tone=0.8, symbols=["INFY"])]}
    assert NM.forecast("INFY", named, None, NOW)["score"] > 0 == NM.forecast("TCS", named, None, NOW)["score"]           # its own news; one company's contract is not its peer's
    sector = {"items": [story("IT services deal wins accelerate as US tech spending rises")]}
    assert NM.forecast("TCS", sector, None, NOW)["score"] > 0 and NM.forecast("INFY", sector, None, NOW)["score"] > 0     # sector news reaches both


def test_the_past_counts_by_how_many_episodes_it_really_rests_on():
    dig = {"items": [], "events": [{"type": "commodities", "kind": "oil_shock", "level": "high", "severity": 3.0, "top": []}]}
    strong = {"oil_shock": {"GOLD": {"n": 12, "n_eff": 10.0, "p_up": 0.83, "median_ret": 0.011}}}
    thin = {"oil_shock": {"GOLD": {"n": 12, "n_eff": 1.2, "p_up": 0.83, "median_ret": 0.011}}}
    p_strong, p_thin = NM.forecast("GOLD", dig, strong, NOW)["p_up"], NM.forecast("GOLD", dig, thin, NOW)["p_up"]
    assert p_strong > p_thin > 0.5
    assert "most like today" in NM.forecast("GOLD", dig, strong, NOW)["why"][0]
    assert NM.forecast("GOLD", {**dig, "events": [{**dig["events"][0], "level": "low"}]}, strong, NOW)["p_up"] == 0.5    # no event under way: no analogue


def test_events_reach_instruments_through_their_stories_subjects():
    ev = {"type": "geopolitics", "level": "high", "top": ["Brent jumps after strikes on tankers"]}
    assert NM.touches("USDINR", ev) >= A2.TOUCH_MIN and NM.touches("CRUDEOIL", ev) == 1.0 and NM.touches("TCS", ev) == 0.0


def test_forecasts_are_scored_by_what_happened():
    sc = NM.Scorer()
    sc.add("X", 0.0, 0.9, 100.0)
    sc.add("X", 300.0, 0.9, 100.5)                                                               # inside the quarter hour: not a second forecast
    sc.add("X", NM.HORIZON_S + 1, 0.5, 101.0)                                                    # an hour on, the price rose: (0.9 - 1)^2
    assert sc.calibration()["X"] == {"n": 1, "brier": 0.01}


def test_auto_v2_votes_with_the_instruments_own_news_and_names_its_own_past():
    ap = A2.AutoPilotV2(("CRUDEOIL", "TCS"), {"CRUDEOIL": 100, "TCS": 175}, lambda *a: 0.0, None, segments={"CRUDEOIL": "mcx"})
    dig = {"items": [story("Brent jumps 6% after drone strikes on Gulf oil facilities")], "events": []}
    assert ap.news_vote(dig, "CRUDEOIL", NOW, 6000.0)[0] == 1 and ap.news_vote(dig, "TCS", NOW, 4000.0)[0] == 0
    ap.brief = {"news_analogs": {"oil_shock": {"CRUDEOIL": {"n": 5, "n_eff": 3.1, "p_up": 0.8, "mean_ret_w": 0.04, "worst": -0.02,
                                                            "nearest": [["2019-09-16", 0.9, 0.12], ["2022-03-07", 0.7, 0.05]]}}}}
    line = ap.analog_line("oil_shock", "CRUDEOIL")
    assert line.startswith("CRUDEOIL on the 5 past oil shock episodes") and "2019-09-16 (+12.0%)" in line
    regime, why = ap.regime("CRUDEOIL", {"events": [{"type": "geopolitics", "level": "high", "severity": 3.0, "tone": -0.5, "kind": "oil_shock",
                                                     "top": ["Brent jumps after strikes"]}]}, None)
    assert regime == "event" and "CRUDEOIL on the 5 past" in why


# ---- the analogues: past episodes weighted by how much the market then resembled the market now -----------------------------------------------------
def planted(seed=1):
    """A series whose event days go the way of the 20-session trend before them."""
    rng, days = random.Random(seed), pd.bdate_range("2015-01-01", periods=2500)
    px = [100.0]
    for i in range(1, 2500):
        px.append(px[-1] * math.exp(rng.gauss(0.0002, 0.01) + 0.004 * math.sin(i / 40)))
    s = pd.Series(px, index=days)
    raw = AN.situation(s)
    ev = list(days[300::45])
    for d in ev:
        i = days.get_loc(d)
        s.iloc[i:] *= math.exp(0.015 if raw["trend20"].iloc[i - 1] > 0 else -0.015)
    return s, {"kinds": {"rbi": {"reacts": "same_session", "dates": [str(d.date()) for d in ev]}}}, raw


def test_the_analogues_follow_todays_situation():
    s, dates, raw = planted()
    up, down = raw.iloc[-1].copy(), raw.iloc[-1].copy()
    up["trend20"], down["trend20"] = 2.0, -2.0
    a_up, a_down = AN.for_instrument(s, dates, up)["rbi"], AN.for_instrument(s, dates, down)["rbi"]
    assert a_up["p_up"] > 0.55 > 0.45 > a_down["p_up"]                                          # the same 49 episodes, weighted by today
    assert a_up["n"] == 49 and 5 < a_up["n_eff"] < a_up["n"]
    assert len(a_up["nearest"]) == 3 and a_up["nearest"][0][1] >= a_up["nearest"][1][1]
    assert AN.for_instrument(s.iloc[:200], dates) == {}                                          # too short: nothing
    got = AN.build({"X": s, "Y": None}, dates)
    assert set(got["rbi"]) == {"X"}
