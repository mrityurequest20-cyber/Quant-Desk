"""How it moves (engine/movement.py): range estimators, gaps, split handling, and the compression study."""
import math

import numpy as np
import pandas as pd
import pytest

from marketlens.engine import movement as MV


def _ohlc(n=400, seed=0, vol=0.012):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2023-01-02", periods=n)
    c = 1000 * np.exp(np.cumsum(rng.normal(0, vol, n)))
    o = np.r_[1000, c[:-1]] * np.exp(rng.normal(0, vol / 3, n))
    h = np.maximum(o, c) * np.exp(np.abs(rng.normal(0, vol / 2, n)))
    l = np.minimum(o, c) * np.exp(-np.abs(rng.normal(0, vol / 2, n)))
    return pd.DataFrame({"open": o, "high": h, "low": l, "close": c, "volume": rng.integers(1e5, 1e6, n).astype(float)}, index=idx)


def test_estimators_match_their_textbook_formulas_on_the_last_window():
    d = MV.prepare(_ohlc())
    m = MV.measures(d)
    w = d.iloc[-22:]
    x, p = w.iloc[1:], w.iloc[:-1]
    hl = np.log(x["high"] / x["low"]).to_numpy()
    co = np.log(x["close"] / x["open"]).to_numpy()
    rc = np.log(x["close"].to_numpy() / p["close"].to_numpy())
    assert m["cc21"].iat[-1] == pytest.approx(rc.std(ddof=1) * math.sqrt(252), rel=1e-10)
    assert m["pk21"].iat[-1] == pytest.approx(math.sqrt((hl ** 2).mean() / (4 * math.log(2)) * 252), rel=1e-10)
    assert m["gk21"].iat[-1] == pytest.approx(math.sqrt((0.5 * hl ** 2 - (2 * math.log(2) - 1) * co ** 2).mean() * 252), rel=1e-10)


def test_a_bonus_is_not_a_gap_and_volume_is_restated():
    d = _ohlc(120)
    day = d.index[60]
    d.loc[d.index >= day, ["open", "high", "low", "close"]] /= 2              # a 1:1 bonus: prices halve ...
    d.loc[d.index >= day, "volume"] *= 2                                     # ... and share counts double
    raw = MV.measures(MV.prepare(d))
    fixed = MV.measures(MV.prepare(d, [{"date": str(day.date()), "ratio": 2.0}]))
    assert raw.loc[day, "gap"] < -0.6                                        # unadjusted: a fake -69% (log) gap
    assert abs(fixed.loc[day, "gap"]) < 0.05 and fixed["gap"].abs().max() < 0.1
    assert abs(fixed["vol_z"].iloc[60:70]).max() < 3                         # no volume "spike" from the share count


def test_a_demerger_day_is_left_out():
    d = _ohlc(120)
    day = d.index[70]
    d.loc[d.index >= day, ["open", "high", "low", "close"]] *= 0.8
    m = MV.measures(MV.prepare(d, (), [str(day.date())]))
    assert np.isnan(m.loc[day, "gap"]) and np.isnan(m.loc[day, "ret"])


def test_compression_study_finds_nothing_in_noise_and_finds_a_planted_effect():
    rng = np.random.default_rng(5)
    n = 1500
    idx = pd.bdate_range("2019-01-01", periods=n)
    # a vol regime that wanders; IV prices it exactly
    sig = 0.15 * np.exp(np.cumsum(rng.normal(0, 0.03, n)) * 0.3)
    r = rng.normal(0, sig / np.sqrt(252))
    m = pd.DataFrame({"ret": r, "cc21": pd.Series(r).rolling(21).std().to_numpy() * np.sqrt(252),
                      "rng20_rank": rng.uniform(0, 1, n)}, index=idx)
    s = MV.compression_study(m, pd.Series(sig, idx), n_perm=300)
    assert s["p"] > 0.05 and abs(s["z_comp"] - s["z_other"]) < 0.1
    # plant it: the 10 sessions after a "compressed" day move twice as much as priced
    comp = m["rng20_rank"].to_numpy() <= 0.2
    r2 = r.copy()
    for i in np.where(comp)[0]:
        r2[i + 1:i + 11] *= 2
    m2 = m.assign(ret=r2, cc21=pd.Series(r2).rolling(21).std().to_numpy() * np.sqrt(252))
    s2 = MV.compression_study(m2, pd.Series(sig, idx), n_perm=300)
    assert s2["z_comp"] > s2["z_other"] and s2["p"] < 0.05


def test_nse_previous_close_bridges_a_session_the_series_lacks():
    """1 Feb 2026 was a Budget Sunday session: NSE's previous close on 2 Feb is that Sunday's, not Friday's."""
    d = _ohlc(60)
    d["prev_close"] = d["close"].shift()
    day = d.index[40]
    d.loc[day, "prev_close"] = d["close"].iat[39] * 0.99                    # a session in between closed 1% lower
    m = MV.measures(MV.prepare(d))
    assert m.loc[day, "gap"] == pytest.approx(np.log(d.loc[day, "open"] / (d["close"].iat[39] * 0.99)))
    # on a split day NSE's previous close is the old price: the ratio is applied to it as well
    d2 = _ohlc(60)
    d2["prev_close"] = d2["close"].shift()
    sd = d2.index[30]
    d2.loc[d2.index >= sd, ["open", "high", "low", "close"]] /= 2
    d2["prev_close"] = d2["close"].shift()
    d2.loc[sd, "prev_close"] = d2["close"].iat[29]                         # NSE's: the pre-split close, unadjusted
    m2 = MV.measures(MV.prepare(d2, [{"date": str(sd.date()), "ratio": 2.0}]))
    assert abs(m2.loc[sd, "gap"]) < 0.05
