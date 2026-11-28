"""The gamma map (engine/gamma.py) and its live mirror (web/livecore.js gammaMap)."""
import json

import numpy as np
import pandas as pd
import pytest

from marketlens.engine import gamma as G
from marketlens.engine import vol as V
from marketlens.tests.test_live import _chain, quotes_from_chain, run_js, pytestmark  # noqa: F401  (node skip)

pytestmark = []                                                      # the Python tests run without node; JS ones skip below


def test_b76_gamma_is_the_second_derivative_of_the_price():
    F, K, T, s, h = 25000.0, 25300.0, 12 / 365, 0.15, 1.0
    p = lambda f: float(V._b76(f, K, T, s, np.array(True)))
    fd = (p(F + h) - 2 * p(F) + p(F - h)) / h ** 2
    assert float(G.b76_gamma(F, K, T, s)) == pytest.approx(fd, rel=1e-4)
    pp = lambda f: float(V._b76(f, K, T, s, np.array(False)))       # a put's gamma is the call's
    assert (pp(F + h) - 2 * pp(F) + pp(F - h)) / h ** 2 == pytest.approx(fd, rel=1e-4)


def _poi(day, calls, puts):
    rows = []
    for who, cl, cs, pl, ps in calls_puts(calls, puts):
        rows.append(dict(date=pd.Timestamp(day), participant=who, opt_idx_call_long=cl, opt_idx_call_short=cs, opt_idx_put_long=pl,
                         opt_idx_put_short=ps, opt_stk_call_long=1.0, opt_stk_call_short=1.0, opt_stk_put_long=1.0, opt_stk_put_short=1.0))
    return pd.DataFrame(rows)


def calls_puts(calls, puts):
    who = ["Client", "DII", "FII", "Pro"]
    out = [(w, calls[w][0], calls[w][1], puts[w][0], puts[w][1]) for w in who]
    out.append(("TOTAL", sum(c[0] for c in calls.values()), sum(c[1] for c in calls.values()),
                sum(p[0] for p in puts.values()), sum(p[1] for p in puts.values())))
    return out


def test_weights_are_the_hedgers_net_share_of_open_interest():
    calls = {"Client": (100, 60), "DII": (0, 0), "FII": (10, 40), "Pro": (40, 50)}          # totals 150 long = 150 short
    puts = {"Client": (50, 120), "DII": (0, 0), "FII": (60, 10), "Pro": (40, 20)}           # 150 = 150
    w = G.weights(_poi("2026-11-26", calls, puts), pd.Timestamp("2026-11-27"), "index")
    assert w["date"] == "2026-11-26"
    assert w["calls"] == pytest.approx((10 - 40 + 40 - 50) / 150) and w["puts"] == pytest.approx((60 - 10 + 40 - 20) / 150)
    h = G.weights_history(_poi("2026-11-26", calls, puts), "index")
    assert h.loc["2026-11-26", "calls"] == pytest.approx(w["calls"]) and h.loc["2026-11-26", "puts"] == pytest.approx(w["puts"])
    assert G.weights(_poi("2026-11-26", calls, puts), pd.Timestamp("2026-11-25"), "index") is None      # nothing on or before


def _map(df, day, spot, w):
    t, iv = V.expiry_table(df)
    return G.profile(df, t, iv, day, spot, w)


def test_profile_sums_gamma_times_oi_and_finds_the_flip():
    day = pd.Timestamp("2026-11-26")
    df = _chain(day, 1000.0, {pd.Timestamp("2026-12-03"): 0.2, pd.Timestamp("2026-12-29"): 0.18})
    df.loc[(df["kind"] == "CE") & (df["strike"] >= 1000), "oi"] = 5000.0      # calls above, puts below
    df.loc[(df["kind"] == "PE") & (df["strike"] < 1000), "oi"] = 8000.0
    m = _map(df, day, 1000.0, {"calls": 0.3, "puts": -0.3, "date": "x"})
    assert m["call_total"] > 0 and m["put_total"] > 0
    # by hand: one strike's call gamma
    t, iv = V.expiry_table(df)
    c = G.chain(df, t, iv, [day])
    r = c[(c["strike"] == 1010) & (c["expiry"] == pd.Timestamp("2026-12-03"))].iloc[0]
    want = float(G.b76_gamma(r["F"], 1010, r["T"], r["iv"])) * r["F"] ** 2 * 0.01 / 1e7 * r["oi_c"]
    got = sum(x for k, x in zip(m["strikes"], m["call"]) if k == 1010)
    other = c[(c["strike"] == 1010) & (c["expiry"] == pd.Timestamp("2026-12-29"))].iloc[0]
    want += float(G.b76_gamma(other["F"], 1010, other["T"], other["iv"])) * other["F"] ** 2 * 0.01 / 1e7 * other["oi_c"]
    assert got == pytest.approx(want, rel=1e-3)                          # rounded to 4 dp in the output
    # long gamma on the calls above, short on the puts below: positive up there, negative down here, a flip between
    p = m["profile"]
    assert p["net"][-1] > 0 > p["net"][0] and 950 < m["flip"] < 1050
    assert m["net_total"] == pytest.approx(p["net"][20], abs=1e-4)          # the profile is rounded to 4 dp


def test_live_gamma_map_matches_end_of_day():
    import shutil
    if shutil.which("node") is None:
        pytest.skip("node not installed")
    day = pd.Timestamp("2026-11-26")
    df = _chain(day, 1000.0, {pd.Timestamp("2026-12-03"): 0.2, pd.Timestamp("2026-12-29"): 0.18})
    rng = np.random.default_rng(1)
    df.loc[df["kind"] != "FUT", "oi"] = rng.integers(100, 9000, (df["kind"] != "FUT").sum()).astype(float)
    df = df[df["close"] > 0]                      # a wing rounded to Rs 0.00: the live feed never carries a priceless quote
    w = {"calls": -0.05, "puts": 0.12}
    py = _map(df, day, 1003.0, dict(w, date="x"))
    now_ms = int(pd.Timestamp("2026-11-26 15:30", tz="Asia/Kolkata").timestamp() * 1000)
    q = quotes_from_chain(df[df["date"] == day], "X")
    js = run_js(f"const r = L.readUnderlying({json.dumps(q)}, 'X', {{nowMs: {now_ms}, maxAge: 120}});"
                f"console.log(JSON.stringify(L.gammaMap(r, 1003.0, {json.dumps(w)})));")
    assert js["strikes"] == py["strikes"]
    # the JS and scipy IV solvers agree to about 1e-6 in vol (test_live), so gamma agrees to about 1e-5 relative
    assert js["call_total"] == pytest.approx(py["call_total"], rel=2e-5) and js["put_total"] == pytest.approx(py["put_total"], rel=2e-5)
    assert np.allclose(js["call"], py["call"], atol=1e-4) and np.allclose(js["net"], py["net"], atol=1e-4)
    assert np.allclose(js["profile"]["net"], py["profile"]["net"], atol=1e-4)
    assert (js["flip"] is None and py["flip"] is None) or js["flip"] == pytest.approx(py["flip"], rel=1e-4)


def test_regime_study_normalises_by_the_priced_move():
    idx = pd.bdate_range("2024-01-01", periods=200)
    net = pd.Series(np.where(np.arange(200) % 4 == 0, -1.0, 1.0), idx)
    iv = pd.Series(np.where(net < 0, 0.40, 0.10), idx)                    # short-gamma days are the volatile ones ...
    ret = pd.Series(0.0, idx)
    ret.iloc[1:] = np.where(net.shift(1).iloc[1:] < 0, 0.4, 0.1) / np.sqrt(252)   # ... and move exactly as priced
    s = G.regime_study(pd.DataFrame({"gamma_net": net}), ret, iv, n_perm=200)
    assert s["raw_neg"] > 3 * s["raw_pos"]                                 # raw: short gamma looks 4x wilder
    assert s["z_neg"] == pytest.approx(s["z_pos"]) and s["p"] > 0.2        # per unit of priced move: no difference
