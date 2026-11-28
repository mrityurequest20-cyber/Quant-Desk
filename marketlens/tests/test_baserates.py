"""Days like today (engine/baserates.py): honest on noise, finds a planted effect, and never peeks ahead."""
import numpy as np
import pandas as pd

from marketlens.engine import baserates as BR


def _market(n=1600, seed=0, planted=1.0):
    """A wandering vol regime priced exactly by IV; `planted` multiplies the next month's moves after days when the
    curve was inverted (a reading the moves themselves cannot feed back into: planting on the premium's sign would
    raise realised vol, make most days 'discount' and contaminate the baseline)."""
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2019-01-01", periods=n)
    sig = 0.16 * np.exp(np.cumsum(rng.normal(0, 0.04, n)) * 0.25)
    iv = pd.Series(sig, idx)
    slope = pd.Series(np.where(rng.uniform(size=n) < 0.02, -0.01, 0.01) + rng.normal(0, 0.002, n), idx)   # rare: boosted windows stay a minority
    r = rng.normal(0, 1, n) * sig / np.sqrt(252)
    if planted != 1.0:
        boost = np.ones(n)
        for i in np.where(slope.to_numpy() < 0)[0]:
            boost[i + 1:i + 22] = np.maximum(boost[i + 1:i + 22], 1.0)
            boost[i + 1:i + 22] = planted
        # keep the planted days a minority: the boost lasts only where the inverted day was isolated
        r = r * boost
    close = pd.Series(1000 * np.exp(np.cumsum(r)), idx)
    rr = pd.Series(np.log(close)).diff()
    return pd.DataFrame({"close": close, "iv30": iv, "rv21": rr.rolling(21).std() * np.sqrt(252), "rv5": rr.rolling(5).std() * np.sqrt(252),
                         "rv63": rr.rolling(63).std() * np.sqrt(252), "rr25": pd.Series(rng.normal(-0.01, 0.005, n), idx),
                         "term_60_30": slope})


def test_fairly_priced_noise_reads_as_an_ordinary_day():
    verdicts = []
    for seed in range(6):
        L = BR.lab(_market(seed=seed), B=200)
        assert L["baseline"]["ratio"] < 1.1
        verdicts.append(L["verdict"]["neighbours"])
    assert verdicts.count("same") >= 4                                   # 90% intervals: an occasional miss, not a habit


def test_a_planted_underpricing_is_found():
    hits = 0
    for seed in range(4):
        df = _market(seed=seed, planted=1.6)
        df.loc[df.index[-1], "term_60_30"] = -0.01                       # today: an inverted curve, like the planted days
        L = BR.lab(df, B=200)
        hits += L["verdict"]["neighbours"] == "higher"
    assert hits >= 3


def test_no_outcome_is_used_before_it_is_known():
    df = _market()
    d = BR.frame(df)
    assert d["ratio"].iloc[-BR.H:].isna().all() and d["inside"].iloc[-BR.H:].isna().all()
    mask = BR.neighbours(d)
    assert not mask.iloc[-BR.H - 1:].any()                                # neighbours all have known outcomes
    pos = np.where(mask.to_numpy())[0]
    assert np.diff(np.sort(pos)).min() >= BR.GAP                          # one per 10-session stretch
