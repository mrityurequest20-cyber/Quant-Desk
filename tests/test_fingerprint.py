"""The market fingerprint and the regime tags (docs/EVOLUTION.md, phase 1; the owner, 14 Nov 2026: "market may not behave the same way 2 months later, 3 months later,
a year later. How our trading desk is going to evolve in that process?").

What is pinned: the fingerprint reads volatility against three years, direction, chop, herding and stress from daily closes, without looking ahead (a fingerprint at an
earlier date is the one computed on the closes up to it); its key is one of nine regimes; the brief carries it with the overnight markets and the week's events and says
it in a line; AUTO v2 tags every closed shadow trade with today's key ("unknown" without today's brief), keeps it with the private record, and reads it back validated."""
from __future__ import annotations

import datetime as dt
import json
import math
import re

import numpy as np
import pandas as pd
import pytest

from quantdesk.paper import auto2 as A2
from quantdesk.premarket import fingerprint as FP

DAYS = pd.bdate_range("2021-01-04", periods=1300)


def walk(vol, n=1300, seed=0, drift=0.0, tail=None):
    """Daily closes from a random walk; `tail`: (sessions, vol, drift) for the last stretch."""
    r = np.random.default_rng(seed).normal(drift, vol, n)
    if tail:
        k, v, d = tail
        r[-k:] = np.random.default_rng(seed + 1).normal(d, v, k)
    return pd.Series(100 * np.exp(np.cumsum(r)), index=DAYS[:n])


def stocks(common_vol=0.01, own=0.006, k=6, n=1300):
    common = np.random.default_rng(99).normal(0, common_vol, n)
    return {f"S{i}": pd.Series(100 * np.exp(np.cumsum(common + np.random.default_rng(10 + i).normal(0, own, n))), index=DAYS[:n]) for i in range(k)}


def test_a_stressed_falling_market_reads_high_volatility_trending_down():
    fp = FP.compute({"NIFTY": walk(0.007, tail=(60, 0.02, -0.004)), **stocks()})
    f = fp["features"]
    assert fp["key"] == "high/down" and f["vol_pct"] > FP.VOL_HIGH and f["trend_t"] <= -FP.TREND_T and f["drawdown"] < -0.10
    assert "high volatility" in fp["label"] and "trending down" in fp["label"] and "stocks moving together" in fp["label"]
    assert f["corr"] > FP.HERD and f["stocks"] == 6 and f["tail_days"] > 0


def test_a_quiet_market_reads_low_volatility_and_dispersed_stocks():
    fp = FP.compute({"NIFTY": walk(0.012, tail=(80, 0.004, 0.0)), **stocks(common_vol=0.0005, own=0.012)})
    assert fp["key"].startswith("low/") and fp["features"]["vol_pct"] < FP.VOL_LOW
    assert fp["features"]["corr"] < FP.HERD and "stocks moving their own ways" in fp["label"]


def test_the_fingerprint_never_looks_ahead_and_needs_history():
    s = walk(0.009, seed=3)
    cut = s.index[1000]
    assert FP.compute({"NIFTY": s}, asof=cut) == FP.compute({"NIFTY": s.loc[:cut]})
    assert FP.compute({"NIFTY": s.iloc[:200]}) is None and FP.compute({}) is None
    fp = FP.compute({"NIFTY": (s, "yahoo")})                                                  # tailrisk's (series, source) pairs are read as they come
    assert fp and re.fullmatch(r"(low|normal|high)/(up|down|range)", fp["key"])
    assert fp["since"] is None or fp["since"] <= fp["asof"]
    assert len(fp["history"]) == 20 and all(len(h) == 2 for h in fp["history"])


def test_since_is_when_the_regime_began():
    s = walk(0.006, tail=(25, 0.025, -0.006), seed=5)
    fp = FP.compute({"NIFTY": s})
    hist = FP.compute({"NIFTY": s})["history"]
    assert fp["since"] and all(k == fp["key"] for d, k in hist if d >= fp["since"])


def test_the_brief_adds_the_overnight_markets_and_the_weeks_events_and_says_it():
    fp = FP.compute({"NIFTY": walk(0.007, tail=(60, 0.02, -0.004))})
    g = [{"key": "USVIX", "name": "VIX", "last": 27.5, "change": 0.2}, {"key": "DXY", "name": "Dollar index", "last": 104.0, "change": 0.004},
         {"key": "UST10", "name": "US 10-year", "last": 4.6, "change": 0.01}]
    cal = [{"impact": "high"}, {"impact": "medium"}, {"impact": "low"}]
    full = FP.with_brief(fp, g, cal)
    assert full["features"]["us_vix"] == 27.5 and full["features"]["dollar_change"] == 0.004 and full["features"]["us10y"] == 4.6 and full["features"]["events_5d"] == 2
    line = FP.summary_line(full)
    assert line.startswith("Market: high volatility") and f"({fp['key']})" in line
    from quantdesk.premarket import brief as B
    inp = B.Inputs(now=pd.Timestamp("2026-11-16 06:30", tz="Asia/Kolkata"), fingerprint=fp, globals_=g)
    b = B.build(inp)
    assert b["fingerprint"]["key"] == fp["key"] and any(x.startswith("Market: ") for x in b["summary"])
    json.dumps(B.jsonable(b))                                                                 # the brief is published as JSON


# ---- AUTO v2: every closed shadow trade tagged with the market it was taken in -------------------------------------------------------------------------
def test_closed_shadow_trades_are_tagged_with_todays_regime_and_kept_with_the_record(cfg, tmp_path):
    from tests.test_paper_auto import T0, board
    from tests.test_paper_auto2 import FakeRelay, IC, cycle, desk
    rn, ap = desk(cfg, tmp_path)
    ap.brief = {"session": T0.date().isoformat(), "fingerprint": {"key": "normal/range", "label": "normal volatility, in a range", "since": "2026-11-02"}}
    ap.lab.tag(IC, ap.market_key(T0), 0.4, "NIFTY", "2026-11-09")
    ap.lab.tag(IC, None, -0.2, "NIFTY", "2026-11-09")                                          # no brief for the day: unknown
    ap.lab.tag(IC, "nonsense", 0.1, "NIFTY", "2026-11-09")
    assert ap.lab.reg["normal/range"]["IC"] == [1, 0.4, pytest.approx(0.16), 1] and ap.lab.reg["unknown"]["IC"][0] == 2
    assert ap.lab.recent[0] == ["2026-11-09", IC, "NIFTY", 0.4, "normal/range"]
    for i in range(A2.RECENT_MAX + 30):
        ap.lab.tag(IC, "normal/range", 0.0, "NIFTY", "2026-11-09")
    assert len(ap.lab.recent) == A2.RECENT_MAX
    relay = FakeRelay()
    ap.save(relay, 1000.0)
    ap2 = desk(cfg, tmp_path)[1]
    ap2.load(relay)
    assert ap2.lab.recent == ap.lab.recent and set(ap2.lab.reg) == set(ap.lab.reg)
    for k, fam in ap.lab.reg.items():
        for st, v in fam.items():
            assert ap2.lab.reg[k][st] == pytest.approx(v, abs=1e-4)                           # kept to four decimals
    assert ap.summary()["market"]["key"] == "normal/range" and ap.summary()["regimes"]["normal/range"]["trades"] > 0
    assert ap.market_key(T0 + dt.timedelta(days=1)) is None                                  # yesterday's brief does not describe today


def test_a_bad_stored_regime_record_is_dropped(cfg, tmp_path):
    from tests.test_paper_auto2 import FakeRelay, IC, desk
    bad = json.dumps({"v": 1, "stats": {}, "reg": {"high/down": {"IC": [3, 1.0, 1.0, 2], "NOPE": [1, 1, 1, 1], "LC": [1, "x", 1, 1]}, "evil": {"IC": [1, 1, 1, 1]}},
                      "recent": [["2026-11-09", IC, "NIFTY", 0.3, "high/down"], ["2026-11-09", "NOPE", "NIFTY", 0.3, "x"], "junk"]})
    ap = desk(cfg, tmp_path)[1]
    ap.load(FakeRelay(bad))
    assert ap.lab.reg == {"high/down": {"IC": [3, 1.0, 1.0, 2]}} and ap.lab.recent == [["2026-11-09", IC, "NIFTY", 0.3, "high/down"]]


def test_a_malformed_tag_row_never_costs_the_rest_of_the_record(cfg, tmp_path):
    """Risk review, 14 Nov 2026: an unhashable strategy id in a stored row raised inside load(), before the convex trail peaks and today's plan were read back."""
    from tests.test_paper_auto2 import FakeRelay, IC, desk
    rows = [["2026-11-09", [1], "NIFTY", 0.3, "high/down"], ["2026-11-09", {"a": 1}, "NIFTY", 0.3, "high/down"], ["x" * 500, IC, "NIFTY", 0.3, "high/down"],
            ["2026-11-09", IC, {"n": 1}, 0.3, "high/down"], ["2026-11-09", IC, "NIFTY", True, "high/down"], ["2026-11-09", IC, "NIFTY", 0.3, "made/up"],
            ["2026-11-09", IC, "NIFTY", 0.3, "unknown"]]
    bad = json.dumps({"v": 1, "stats": {IC: [2, 0.5, 0.3, 1]}, "cx": {"pkg1": 4.2}, "reg": {"high/down": {"IC": [1, 0.1, 0.01, 1]}}, "recent": rows})
    ap = desk(cfg, tmp_path)[1]
    msg = ap.load(FakeRelay(bad))
    assert "no record" not in msg and ap.cx_peak == {"pkg1": 4.2} and IC in ap.lab.stats
    assert ap.lab.recent == [["2026-11-09", IC, "NIFTY", 0.3, "unknown"]] and ap.lab.reg == {"high/down": {"IC": [1, 0.1, 0.01, 1]}}


def test_the_summary_caps_what_it_reads_from_the_brief(cfg, tmp_path):
    from tests.test_paper_auto import T0
    from tests.test_paper_auto2 import desk
    ap = desk(cfg, tmp_path)[1]
    ap.brief = {"session": T0.date().isoformat(), "fingerprint": {"key": "low/up", "label": "x" * 5000, "since": {"evil": 1}}}
    m = ap.summary()["market"]
    assert m["key"] == "low/up" and len(m["label"]) == 200 and m["since"] is None


def test_the_shadow_book_tags_what_it_closes(cfg, tmp_path):
    from tests.test_paper_auto import T0, board
    from tests.test_paper_auto2 import calm, desk
    rn, ap = desk(cfg, tmp_path)
    ap.brief = {"session": T0.date().isoformat(), "fingerprint": {"key": "low/range", "label": "low volatility, in a range"}}
    t = calm(rn, ap, minutes=6)
    late = dt.datetime.combine(T0.date(), dt.time(15, 20), tzinfo=A2.IST)                      # the day strategies' exits
    from tests.test_paper_auto2 import cycle
    cycle(rn, ap, board(late), late)
    closed = sum(v[0] for v in ap.lab.stats.values())
    assert closed > 0 and sum(v[0] for v in (ap.lab.reg.get("low/range") or {}).values()) == closed
    assert all(r[4] == "low/range" for r in ap.lab.recent)


def test_the_app_shows_the_market_regime_panel():
    from pathlib import Path
    app = (Path(__file__).resolve().parents[1] / "quantdesk/web/static/app/app.js").read_text()
    part = app[app.index("function ppMarket"):app.index("function ppConvex")]
    assert "lab.market" in part and "lab.regimes" in part and "Market regime" in part
    assert "ppMarket(sm.lab)" in app


@pytest.fixture()
def cfg():
    from pathlib import Path
    from quantdesk.config import Config
    return Config.load(Path(__file__).resolve().parents[1] / "config" / "quantdesk.yaml")
