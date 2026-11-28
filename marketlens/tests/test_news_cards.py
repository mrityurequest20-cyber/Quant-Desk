"""The News page's situation cards (marketlens/news/cards.py), on synthetic stories and prices whose answers are known."""
import json
import math

import numpy as np
import pandas as pd

from marketlens.news import cards as C


def _stories(days_counts, sid="SIT:IRAN_US_ISRAEL", title="Iran strikes: oil jumps"):
    rows, k = [], 0
    for day, n in days_counts.items():
        for i in range(n):
            k += 1
            rows.append({"id": f"s{k}", "ts": pd.Timestamp(day, tz="Asia/Kolkata").tz_convert("UTC") + pd.Timedelta(hours=10, minutes=i),
                         "ts_quality": "day", "source": "gnews", "kind": "headline", "symbol": sid, "title": f"{title} {k}",
                         "summary": "", "publisher": "x", "query": "", "link": ""})
    return pd.DataFrame(rows)


def _background(start, end, every=3):
    """One story every few days: the situation's normal hum, so a burst stands out."""
    return {d: 1 for d in pd.date_range(start, end, freq=f"{every}D")}


def _prices(start="2019-01-01", end="2026-11-27"):
    idx = pd.bdate_range(start, end)
    return idx, pd.Series(np.linspace(10000, 26000, len(idx)), index=idx)


def test_activity_heat_against_its_own_year():
    asof = pd.Timestamp("2026-11-27")
    hum = _background("2025-11-01", "2026-11-20", every=7)
    t = C.NS.assign(_stories({**hum, "2026-11-24": 9, "2026-11-25": 6}))
    t["day"] = pd.to_datetime(t["ts"], utc=True).dt.tz_convert("Asia/Kolkata").dt.tz_localize(None).dt.normalize()
    a = C.activity(t, asof)
    assert a["heat"] == "flaring" and a["last7"] == 15 and a["typical7"] <= 1
    t2 = t[t["day"] < "2026-11-21"]
    assert C.activity(t2, asof)["heat"] == "quiet"
    assert len(a["weekly"]) >= 52 and a["weekly"][-1][1] == 15


def test_card_measures_reaction_and_says_too_few_below_five():
    idx, nifty = _prices()
    # NIFTY falls 3% the session of each flare-up and stays there
    bursts = ["2020-01-03", "2024-04-15"]
    for b in bursts:
        i = idx.searchsorted(pd.Timestamp(b))
        nifty.iloc[i:] *= 0.97
    hum = _background("2019-06-01", "2026-11-20", every=4)
    st = _stories({**hum, **{b: 12 for b in bursts}})
    nj = C.build(st, {}, {"NIFTY": nifty}, {}, asof=pd.Timestamp("2026-11-27"))
    card = next(c for c in nj["situations"] if c["sid"] == "SIT:IRAN_US_ISRAEL")
    assert [e["start"] for e in card["episodes"]] == bursts[::-1]             # newest first
    e = card["episodes"][0]
    assert math.isclose(math.exp(e["measures"]["NIFTY"]["1"]) - 1, -0.03 + (26000 - 10000) / len(idx) / 25000, abs_tol=0.002)
    assert card["base"] == [] and "too few for a base rate" in card["plain"]
    assert json.loads(json.dumps(nj))                                          # plain JSON, no NaN


def test_card_base_rates_and_plain_line_with_enough_episodes():
    idx, nifty = _prices()
    bursts = [f"{y}-03-02" for y in range(2019, 2026)]
    for b in bursts:
        i = idx.searchsorted(pd.Timestamp(b))
        nifty.iloc[i:] *= 0.98
    hum = _background("2018-11-01", "2026-11-20", every=4)
    st = _stories({**hum, **{b: 12 for b in bursts}})
    nj = C.build(st, {}, {"NIFTY": nifty}, {}, asof=pd.Timestamp("2026-11-27"))
    card = next(c for c in nj["situations"] if c["sid"] == "SIT:IRAN_US_ISRAEL")
    assert card["n_episodes"] == 7
    row = next(r for r in card["base"] if r["measure"] == "NIFTY")
    assert row["h5"]["n"] == 7 and row["h5"]["share_up"] == 0 and row["h5"]["median"] < -0.015
    assert "After its 7 flare-ups since 2019-03-02" in card["plain"] and "NIFTY −" not in card["plain"]
    assert "NIFTY -1." in card["plain"] and "up in 0 of 7" in card["plain"] and "not a forecast" in card["plain"]


def test_situations_with_no_stories_are_quiet_cards_and_briefs_load(tmp_path):
    (tmp_path / "brief_SIT_OPEC.json").write_text(json.dumps({"situation": "SIT:OPEC", "model": "m", "brief": {"summary": "s"}}))
    (tmp_path / "brief_bad.json").write_text("{not json")
    b = C.load_briefs(tmp_path)
    assert b == {"SIT:OPEC": {"model": "m", "summary": "s"}}
    st = _stories({"2026-11-25": 2})
    nj = C.build(st, {}, {}, {}, briefs=b, asof=pd.Timestamp("2026-11-27"))
    assert len(nj["situations"]) == len(C.NS.SITUATIONS)
    opec = next(c for c in nj["situations"] if c["sid"] == "SIT:OPEC")
    assert opec["brief"]["summary"] == "s" and opec["activity"]["heat"] == "quiet" and opec["episodes"] == []
    assert C.build(pd.DataFrame(), {}, {}, {})["situations"] == []


def test_a_couple_of_stories_is_not_active():
    asof = pd.Timestamp("2026-11-27")
    t = C.NS.assign(_stories({**_background("2025-11-01", "2026-11-19", every=7), "2026-11-24": 2}))
    t["day"] = pd.to_datetime(t["ts"], utc=True).dt.tz_convert("Asia/Kolkata").dt.tz_localize(None).dt.normalize()
    assert C.activity(t, asof)["heat"] == "quiet"
    t = C.NS.assign(_stories({**_background("2025-11-01", "2026-11-19", every=7), "2026-11-24": 3}))
    t["day"] = pd.to_datetime(t["ts"], utc=True).dt.tz_convert("Asia/Kolkata").dt.tz_localize(None).dt.normalize()
    assert C.activity(t, asof)["heat"] == "active"
