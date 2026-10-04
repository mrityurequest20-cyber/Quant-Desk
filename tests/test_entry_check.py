"""expiry_eve_entry_v1 (research/entry_check.py): each eve a sleeve opened is paired with the history's convention on
the same strikes; nothing but counts shows before the registered decision point; the decision follows the spec."""
import datetime as dt
import json

import numpy as np
import pandas as pd
import pytest

from quantdesk.research import entry_check as E

SPEC = E.load_spec()


def _open(u, day, exp, spot, ce, pe, at="15:26", sleeve="B"):
    return {"event": "open", "id": f"{sleeve}-{u}-{exp}", "sleeve": sleeve, "underlying": u, "expiry": exp, "day": day,
            "spot": spot, "recorded_at": f"{day}T{at}:00+05:30",
            "legs": [{"qty": -1, "right": "CE", "strike": ce[0], "target": 0.2, "fill": ce[1]},
                     {"qty": -1, "right": "PE", "strike": pe[0], "target": -0.2, "fill": pe[1]}]}


def _rows(day, sym, exp, legs, underlying=None):
    return [{"date": pd.Timestamp(day), "symbol": sym, "kind": k, "expiry": pd.Timestamp(exp), "strike": float(K),
             "close": float(c), "underlying": underlying, "contracts": float(n)} for k, K, c, n in legs]


@pytest.fixture
def world(tmp_path):
    sl, wh = tmp_path / "sleeves", tmp_path / "wh"
    sl.mkdir()
    wh.mkdir()
    evs = [_open("NIFTY", "2026-10-05", "2026-10-06", 25000.0, (25300, 40.0), (24700, 35.0)),
           _open("NIFTY", "2026-10-05", "2026-10-06", 25000.0, (25400, 1.0), (24600, 1.0), at="15:27", sleeve="A"),
           {"event": "settle", "id": "B-NIFTY-2026-10-06", "settle": 25400.0},
           _open("NIFTY", "2026-10-02", "2026-10-03", 25000.0, (25300, 40.0), (24700, 35.0)),          # before 'from'
           _open("SENSEX", "2026-10-07", "2026-10-08", 82000.0, (82500, 30.0), (81500, 28.0)),
           _open("FINNIFTY", "2026-10-26", "2026-10-27", 24000.0, (24300, 20.0), (23700, 18.0))]
    (sl / "expiry_seller_v1.jsonl").write_text("\n".join(json.dumps(e) for e in evs) + "\n")
    nse = (_rows("2026-10-05", "NIFTY", "2026-10-06", [("CE", 25300, 42, 1000), ("PE", 24700, 36, 500)])
           + _rows("2026-10-26", "FINNIFTY", "2026-10-27", [("CE", 24300, 21, 50), ("PE", 23700, 19, 0)]))
    bse = (_rows("2026-10-07", "SENSEX", "2026-10-08", [("CE", 82500, 31, 200), ("PE", 81500, 29, 300)], 82050.0)
           + _rows("2026-10-08", "SENSEX", "2026-10-08", [("CE", 82500, 100, 9)], 82600.0))
    pd.DataFrame(nse).to_parquet(wh / "fo_bhav_2026-10.parquet")
    pd.DataFrame(bse).to_parquet(wh / "bse_fo_bhav_2026-10.parquet")
    pd.DataFrame({"date": pd.to_datetime(["2026-10-05", "2026-10-06"]), "index": "Nifty 50", "symbol": "NIFTY",
                  "close": [25010.0, 25390.0]}).to_parquet(wh / "nse_index_close_2026.parquet")
    return wh, sl


def test_each_eve_is_paired_on_the_same_strikes(world):
    wh, sl = world
    res, p = E.run(wh, sl)
    p = p.set_index("underlying")
    assert set(p.index) == {"NIFTY", "SENSEX", "FINNIFTY"}            # one per eve, from the earliest open; none before 'from'
    n = p.loc["NIFTY"]
    assert n["ce_strike"] == 25300 and n["executable_credit_bps"] == pytest.approx(30.0)
    hist = ((42 - (0.05 + 0.084)) + (36 - (0.05 + 0.072))) / 25010 * 1e4
    assert n["history_credit_bps"] == pytest.approx(hist) and n["d_bps"] == pytest.approx(hist - 30.0)
    assert n["history_level_source"] == "nse_index_close"
    assert n["payout_official_bps"] == pytest.approx(90 / 25000 * 1e4)       # official close 25,390
    assert n["payout_registered_bps"] == pytest.approx(100 / 25000 * 1e4)    # the sleeve's 25,400
    s = p.loc["SENSEX"]
    assert s["history_level_source"] == "bhavcopy underlying" and s["history_level"] == 82050
    assert s["settle_official"] == 82600 and np.isnan(s["payout_registered_bps"])
    f = p.loc["FINNIFTY"]
    assert np.isnan(f["d_bps"]) and "PE 23700: no traded bhavcopy row" in f["excluded"]
    assert res["eves"] == 2 and res["excluded"] == 1 and res["status"] == "collecting"


def test_nothing_but_counts_before_the_decision_point(world):
    wh, sl = world
    res, _ = E.run(wh, sl)
    md = E.render(res)
    assert "collecting" in md and "No mean" in md
    assert "result" not in res and "per_instrument" not in res and "mean_d_bps" not in json.dumps(res)


def _paired(d, per_week=2):
    rows = []
    for i, x in enumerate(d):
        exp = dt.date(2026, 10, 6) + dt.timedelta(days=7 * (i // per_week) + 2 * (i % per_week))
        rows.append({"underlying": ["NIFTY", "SENSEX"][i % 2], "day": exp - dt.timedelta(days=1), "expiry": exp,
                     "d_bps": float(x)})
    return pd.DataFrame(rows)


def test_the_registered_decision():
    rng = np.random.default_rng(7)
    eq = E.decide(_paired(rng.normal(0, 1, 40)), SPEC)
    assert eq["status"] == "decided" and eq["decided_at"] == 40 and eq["result"]["verdict"] == "equivalent"
    over = E.decide(_paired(5 + rng.normal(0, 1, 40)), SPEC)
    assert over["result"]["verdict"] == "overstated"
    under = E.decide(_paired(-5 + rng.normal(0, 1, 40)), SPEC)
    assert under["result"]["verdict"] == "understated"
    assert E.decide(_paired(rng.normal(0, 1, 39)), SPEC)["status"] == "collecting"
    few_weeks = E.decide(_paired(rng.normal(0, 1, 40), per_week=4), SPEC)       # 40 eves in 10 weeks: wait for 12
    assert few_weeks["status"] == "collecting"


def test_a_noisy_start_can_only_raise_n():
    noisy = E.decide(_paired(np.r_[np.tile([12.0, -12.0], 5), np.zeros(40)]), SPEC)
    assert noisy["reestimated"] and noisy["n"] == 120 and noisy["status"] == "collecting"
    calm = E.decide(_paired(np.zeros(40)), SPEC)
    assert calm["n"] == 40


def test_an_inconclusive_first_look_extends_once():
    d = np.tile([3.0, 1.0], 45)                      # every week averages exactly +2: neither inside nor beyond the margin
    part = E.decide(_paired(d[:60]), SPEC)
    assert part["status"] == "extended: collecting" and part["n"] == 80 and part["first_look_at"] == 40
    assert "result" not in part
    done = E.decide(_paired(d), SPEC)
    assert done["status"] == "decided" and done["decided_at"] == 80 and done["first_look"]["verdict"] == "inconclusive"
    assert done["result"]["verdict"] == "inconclusive"


def test_skip_bias_models_the_skipped_eves_beside_the_traded(tmp_path):
    """The history's convention on every eve the sleeves were due on: traded and skipped modelled side by side."""
    from quantdesk.options.pricing import bs_price
    from quantdesk.research import warehouse_research as W
    days = [d.date() for d in pd.bdate_range("2026-09-01", "2026-10-09")]
    spot = {d: 25000.0 + 10 * i for i, d in enumerate(days)}
    exps = [dt.date(2026, 10, 6), dt.date(2026, 10, 8)]
    rows = []
    for e in exps:
        eve = max(d for d in days if d < e)
        S, T = spot[eve], W._year_frac(eve, e)
        for K in range(24000, 26050, 50):
            for right in ("CE", "PE"):
                rows.append({"date": pd.Timestamp(eve), "symbol": "NIFTY", "kind": right, "expiry": pd.Timestamp(e),
                             "strike": float(K), "close": round(float(bs_price(S, K, T, W.R, W.Q, 0.15, right)), 2),
                             "underlying": None, "contracts": 100.0})
    wh = tmp_path / "wh"
    wh.mkdir()
    pd.DataFrame(rows).to_parquet(wh / "fo_bhav_2026-10.parquet")
    pd.DataFrame({"date": pd.to_datetime(days), "index": "Nifty 50", "symbol": "NIFTY",
                  "close": [spot[d] for d in days]}).to_parquet(wh / "nse_index_close_2026.parquet")
    events = [_open("NIFTY", "2026-10-05", "2026-10-06", 25000.0, (25300, 40.0), (24700, 35.0)),
              {"event": "skip", "sleeve": "B", "underlying": "NIFTY", "expiry": "2026-10-08", "day": "2026-10-07",
               "reason": "no real-quote snapshot"},
              {"event": "skip", "sleeve": "A", "underlying": "NIFTY", "expiry": "2026-10-06", "day": "2026-10-05",
               "reason": "PE 24700: no two-sided quote"}]          # A skipped an eve B traded: the eve counts as traded
    sb = E.skip_bias(wh, events)["NIFTY"]
    assert sb["traded"]["eves"] == 1 and sb["skipped"]["eves"] == 1 and sb["not_modelled"] == 0
    assert sb["traded"]["modelled_mean_bps"] is not None and sb["skipped"]["modelled_mean_bps"] is not None
    md = E.render({"spec": "x", "spec_hash": "y", "status": "collecting", "eves": 0, "excluded": 0, "weeks": 0, "n": 40,
                   "min_weeks": 12, "skip_bias": {"NIFTY": sb}})
    assert "Skip bias" in md and "| NIFTY | 1 |" in md
