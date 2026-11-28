"""News P2: the timing map and the reaction measures, on hand-computed panels."""
import numpy as np
import pandas as pd
import pytest

from marketlens.news import reactions as R

S = pd.bdate_range("2023-01-02", periods=120)          # sessions: weekdays


def ist(s):
    return pd.Timestamp(s, tz="Asia/Kolkata").tz_convert("UTC")


@pytest.mark.parametrize("when,q,expect", [
    ("2023-03-01 08:30", "exact", ("2023-02-28", "2023-03-01", False)),    # pre-open: that session
    ("2023-03-01 11:00", "exact", ("2023-02-28", "2023-03-01", True)),     # in session: flagged
    ("2023-03-01 18:22", "exact", ("2023-03-01", "2023-03-02", False)),    # after the close: the next session
    ("2023-03-04 10:00", "exact", ("2023-03-03", "2023-03-06", False)),    # a Saturday: Monday reacts
    ("2023-03-01 00:00", "day", ("2023-02-28", "2023-03-02", False)),      # a day stamp: two sessions
])
def test_window_maps_a_story_to_the_first_price_that_could_react(when, q, expect):
    b, e, ins = R.window(ist(when), q, S)
    assert (str(S[b].date()), str(S[e].date()), ins) == expect


def panel(close, iv=0.2, oi=None):
    p = pd.DataFrame({"close": close, "iv_front": iv, "rr25": 0.0, "beta_n": 1.5}, index=S)
    if oi is not None:
        p["fut_oi"] = oi
    return p


def test_abnormal_return_priced_move_iv_and_buildup():
    rng = np.random.default_rng(1)
    nifty = pd.Series(100 * np.exp(np.cumsum(rng.normal(0, 0.01, len(S)))), index=S)
    rs = 1.5 * np.log(nifty).diff().fillna(0) + rng.normal(0, 0.01, len(S))
    close = 50 * np.exp(np.cumsum(rs))
    i = S.get_loc(pd.Timestamp("2023-05-02"))
    close = pd.Series(close, index=S)
    close.iloc[i:] *= np.exp(0.06)                                           # a +6% abnormal jump on 2 May
    iv = pd.Series(0.25, index=S)
    iv.iloc[i:] = 0.30
    oi = pd.Series(1000.0, index=S)
    oi.iloc[i:] = 1200.0
    p = R.prepare(panel(close, iv, oi), nifty, is_index=False)
    out = R.react(p, nifty, ist("2023-05-02 08:00"), "exact", is_index=False)
    ret = np.log(close.iat[i] / close.iat[i - 1])
    ar = ret - 1.5 * np.log(nifty.iat[i] / nifty.iat[i - 1])
    assert out["ret"] == pytest.approx(ret) and out["ar"] == pytest.approx(ar)
    assert out["ar"] == pytest.approx(0.06 + rs.iat[i] - 1.5 * np.log(nifty).diff().iat[i], abs=1e-9)
    assert out["z"] > 3                                                       # six of its ~1% typical moves
    assert out["vs_priced"] == pytest.approx(abs(ret) / (0.25 / np.sqrt(252)))
    assert out["d_iv"] == pytest.approx(0.05) and out["oi_chg"] == pytest.approx(0.2)
    assert out["buildup"] == ("long build-up" if ret > 0 else "short build-up")
    assert "drift5" in out


def test_index_is_its_own_market_and_missing_iv_is_left_out():
    close = pd.Series(np.linspace(100, 120, len(S)), index=S)
    p = R.prepare(panel(close, iv=np.nan), None, is_index=True)
    out = R.react(p, None, ist("2023-03-01 18:00"), "exact", is_index=True)
    assert out["ar"] == out["ret"] and "vs_priced" not in out and "d_iv" not in out


def test_reactions_one_row_per_story_and_instrument():
    close = pd.Series(np.linspace(100, 120, len(S)), index=S)
    panels = {"NIFTY": panel(close), "RELIANCE": panel(close * 2)}
    ev = pd.DataFrame({"id": ["a", "b"], "ts": [ist("2023-04-03 09:00"), ist("2030-01-01 09:00")], "ts_quality": ["exact", "exact"],
                       "targets": [["NIFTY", "RELIANCE", "TCS"], ["NIFTY"]]})
    out = R.reactions(ev, panels, {"NIFTY": "index", "RELIANCE": "stock"})
    assert list(zip(out["id"], out["symbol"])) == [("a", "NIFTY"), ("a", "RELIANCE")]     # TCS has no panel; b is in the future
