"""The situation analyzer's measured half: assignment, flare-up episodes, reactions, base rates."""
import numpy as np
import pandas as pd
import pytest

from marketlens.news import situations as S

DAYS = pd.bdate_range("2023-01-02", periods=300)


def stories(spikes):
    rows, k = [], 0
    for d in pd.date_range("2023-01-02", "2024-02-01"):
        n = spikes.get(str(d.date()), 1 if d.day % 5 == 0 else 0)
        for _ in range(n):
            rows.append({"id": f"s{k}", "ts": pd.Timestamp(d, tz="Asia/Kolkata").tz_convert("UTC") + pd.Timedelta("3h"),
                         "title": "Iran warns US over strikes" if k % 2 else "Tehran tensions rise", "publisher": "X", "symbol": "NIFTY"})
            k += 1
    return pd.DataFrame(rows)


def test_assign_by_search_tag_or_subject_words():
    df = pd.DataFrame({"id": ["a", "b", "c"], "ts": pd.Timestamp("2023-01-02", tz="UTC"), "publisher": "X",
                       "title": ["Oil jumps as Iran threatens Hormuz", "Nifty closes flat", "Ukraine talks stall"],
                       "symbol": ["MACRO:CRUDE", "SIT:FED_CYCLE", "NIFTY"]})
    t = S.assign(df)
    pairs = set(zip(t["id"], t["situation"]))
    assert ("a", "SIT:IRAN_US_ISRAEL") in pairs and ("b", "SIT:FED_CYCLE") in pairs and ("c", "SIT:RUSSIA_UKRAINE") in pairs


def test_episodes_find_flare_ups_and_merge_the_days_after():
    daily = pd.Series(0, index=pd.date_range("2023-01-01", periods=200))
    daily.iloc[::7] = 1
    daily.loc["2023-04-10"], daily.loc["2023-04-12"], daily.loc["2023-06-01"] = 12, 9, 15
    eps = S.episodes(daily)
    assert [str(e.date()) for e in eps] == ["2023-04-10", "2023-06-01"]


def test_measure_returns_bp_and_points_from_the_close_before():
    s = pd.Series([100.0, 110.0, 121.0, 133.1], index=pd.bdate_range("2023-03-01", periods=4))
    assert S.measure(s, "ret", pd.Timestamp("2023-03-02"), 1) == pytest.approx(np.log(1.1))
    y = pd.Series([4.00, 4.10, 4.25], index=pd.bdate_range("2023-03-01", periods=3))
    assert S.measure(y, "bp", pd.Timestamp("2023-03-02"), 2) == pytest.approx(25.0)
    assert S.measure(s, "ret", pd.Timestamp("2023-03-01"), 1) is None          # no close before the episode


def test_analyse_end_to_end_with_baskets_relative_to_nifty():
    spikes = {"2023-06-05": 10, "2023-09-04": 12, "2023-11-06": 9}
    st = stories(spikes)
    nifty = pd.Series(np.linspace(100, 130, len(DAYS)), index=DAYS)
    brent = pd.Series(80.0, index=DAYS)
    for d in spikes:
        brent.loc[brent.index >= pd.Timestamp(d)] *= 1.05                  # each flare-up lifts Brent 5%
    closes = {s: nifty * (1.0 + 0.0 * i) for i, s in enumerate(["BPCL", "HINDPETRO", "IOC"])}
    out = S.analyse(st, {"BZ=F": brent}, {"NIFTY": nifty}, closes)
    sit = out["SIT:IRAN_US_ISRAEL"]
    assert [e["start"] for e in sit["episodes"]] == list(spikes)
    br = sit["base_rates"]["Brent"]
    assert br[1]["n"] == 3 and br[1]["median"] == pytest.approx(np.log(1.05)) and br[1]["share_up"] == 1.0
    assert sit["base_rates"]["vs NIFTY: oil_marketing"][5]["median"] == pytest.approx(0.0, abs=1e-12)
    assert sit["episodes"][0]["headlines"]
