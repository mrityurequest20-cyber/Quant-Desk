"""Pre-registered intraday direction tests (autolearn/prereg.py): definitions, statistics and the one-shot lock."""
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from quantdesk.autolearn import prereg as P
from quantdesk.data import external_aeron as X

ROOT = Path(__file__).resolve().parent.parent
SPEC = ROOT / "docs" / "prereg" / "intraday_direction_v1.json"


def synth(days=400, momentum=0.0, seed=1, start="2017-01-02"):
    """5-minute bars; with `momentum`, the 15:00→close move follows the sign of the 09:15→09:45 move (incl. the gap)."""
    rng = np.random.default_rng(seed)
    out, px = [], 10000.0
    for d in pd.bdate_range(start, periods=days):
        px *= np.exp(rng.normal(0, 0.004))                         # overnight gap
        idx = pd.date_range(f"{d.date()} 09:15", f"{d.date()} 15:25", freq="5min", tz=X.IST)
        r = rng.normal(0, 0.0012, len(idx))
        first = np.log(px / (out[-1]["close"].iloc[-1] if out else px)) + r[:6].sum()
        last = idx >= pd.Timestamp(f"{d.date()} 15:00", tz=X.IST)
        r[last] += momentum * np.sign(first) / last.sum()
        c = px * np.exp(np.cumsum(r))
        o = np.r_[px, c[:-1]]
        out.append(pd.DataFrame({"open": o, "high": np.maximum(o, c) * 1.0005, "low": np.minimum(o, c) * 0.9995,
                                 "close": c, "volume": 0.0, "oi": np.nan, "n_1m": 5}, index=idx))
        px = c[-1]
    return pd.concat(out)


def test_prices_are_taken_at_the_bar_that_ends_at_the_named_time():
    b = synth(30)
    d = P.day_table(b)
    day = d.index[5]
    g = b[b.index.date == day]
    assert d.loc[day, "p0945"] == g.loc[pd.Timestamp(f"{day} 09:40", tz=X.IST), "close"]
    assert d.loc[day, "close"] == g["close"].iloc[-1] and d.loc[day, "open"] == g["open"].iloc[0]
    assert np.isnan(d["rv20"].iloc[10]) and np.isfinite(d["rv20"].iloc[25])      # prior sessions only
    prev = d.index[4]
    assert d.loc[day, "prev_close"] == d.loc[prev, "close"]


def test_a_planted_momentum_effect_is_found_and_noise_is_not():
    on = P.trades(P.day_table(synth(500, momentum=0.004)), "H1_intraday_momentum")
    off = P.trades(P.day_table(synth(500, momentum=0.0, seed=2)), "H1_intraday_momentum")
    assert P.nw_t(on["r"].to_numpy()) > 5
    assert abs(P.nw_t(off["r"].to_numpy())) < 3


def test_breakout_and_gap_definitions():
    d = P.day_table(synth(200, seed=3))
    t = P.trades(d, "H5_opening_range_breakout")
    assert set(np.unique(t["signal"])) <= {-1.0, 1.0} and len(t) > 50
    g = P.trades(d, "H4_large_gap")
    assert (d.loc[g.index, "gap"].abs() >= P.GAP_MIN).all()
    hv = P.trades(d, "H6_momentum_high_vol", vol_cut=float(d["rv20"].quantile(2 / 3)))
    assert 0 < len(hv) < len(P.trades(d, "H1_intraday_momentum"))


def test_newey_west_and_bh():
    rng = np.random.default_rng(0)
    assert abs(P.nw_t(rng.normal(0, 1, 2000))) < 3
    q = P.bh({"a": 0.001, "b": 0.02, "c": 0.04, "d": 0.5})
    assert q["a"] == pytest.approx(0.004) and q["b"] == pytest.approx(0.04) and q["d"] == pytest.approx(0.5)
    assert q["c"] == pytest.approx(0.04 * 4 / 3)


def test_the_spec_is_fixed_and_the_lock_opens_once(tmp_path, monkeypatch):
    spec = json.loads(SPEC.read_text())
    assert set(spec["hypotheses"]) == set(P.TESTS)
    b = pd.concat([synth(1100, momentum=0.004, start="2016-01-01").assign(symbol=s) for s in ("NIFTY", "BANKNIFTY")])
    b.attrs.update({"dataset": "synthetic", "status": "external_verified"})
    monkeypatch.setattr(X, "load", lambda *a, **k: b)
    from quantdesk.config import Config
    cfg = Config.load(ROOT / "config" / "quantdesk.yaml")
    rep = P.run(cfg, tmp_path, SPEC, tmp_path / "res", say=lambda *a: None)
    assert rep["lock"] is None and len(rep["dev"]) == 14
    assert "H1_intraday_momentum NIFTY" in rep["selected"]
    rep = P.run(cfg, tmp_path, SPEC, tmp_path / "res", open_lock=True, say=lambda *a: None)
    assert rep["lock"]["tests"]["H1_intraday_momentum NIFTY"]["passed"]
    assert "Locked period" in P.render(rep)
    with pytest.raises(RuntimeError, match="never again"):
        P.run(cfg, tmp_path, SPEC, tmp_path / "res", open_lock=True, say=lambda *a: None)
    again = P.run(cfg, tmp_path, SPEC, tmp_path / "res", say=lambda *a: None)          # dev re-runs keep the lock record
    assert again["lock"]["opened"] == rep["lock"]["opened"]
    frozen = (tmp_path / "res").glob("*.json").__next__().read_text()
    dearer = cfg.with_overrides({"autolearn": {"costs": {"stt_sell_bps": 50.0}}})        # other costs: other dev results
    with pytest.raises(RuntimeError, match="frozen"):
        P.run(dearer, tmp_path, SPEC, tmp_path / "res", say=lambda *a: None)
    assert (tmp_path / "res").glob("*.json").__next__().read_text() == frozen          # and the file is untouched
