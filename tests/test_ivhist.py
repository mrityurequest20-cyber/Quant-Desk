"""The ATM IV history from the bhavcopy and the same-days-to-expiry percentile."""
import datetime as dt

import numpy as np
import pandas as pd
import pytest

from quantdesk.intraday.chains import IST, time_to_expiry
from quantdesk.intraday.ivhist import atm_iv_history, iv_percentile, load
from quantdesk.options.pricing import bs_price

R, Q = 0.065, 0.012


def bhav(days, vol_of=lambda d, dte: 0.12, symbol="NIFTY", step=50.0):
    """A bhavcopy priced by BSM: weekly Tuesday expiries, strikes ±10 steps around a drifting spot."""
    rows, S = [], 22400.0
    for i, d in enumerate(days):
        S *= 1 + 0.004 * np.sin(i)
        exps = [d + dt.timedelta(days=(1 - d.weekday()) % 7 + 7 * w) for w in range(3)]   # this and next Tuesdays
        for e in exps:
            T = time_to_expiry(pd.Timestamp(dt.datetime.combine(d, dt.time(15, 30)), tz=IST), e)
            atm = round(S / step) * step
            for k in np.arange(atm - 10 * step, atm + 11 * step, step):
                for right in ("CE", "PE"):
                    px = float(bs_price(S, k, max(T, 1e-6), R, Q, vol_of(d, (e - d).days), right))
                    rows.append({"date": pd.Timestamp(d), "symbol": symbol, "kind": right, "expiry": pd.Timestamp(e),
                                 "strike": float(k), "close": round(px, 2), "contracts": 100.0, "underlying": S})
        rows.append({"date": pd.Timestamp(d), "symbol": symbol, "kind": "FUT", "expiry": pd.Timestamp(exps[0]),
                     "strike": np.nan, "close": S, "contracts": 1.0, "underlying": S})
    return pd.DataFrame(rows)


def sessions(n, end=dt.date(2026, 9, 30)):
    return [d.date() for d in pd.bdate_range(end=end, periods=n)]


def test_history_recovers_the_vol_and_skips_expiry_day_and_untraded_strikes():
    days = sessions(30)
    b = bhav(days, vol_of=lambda d, dte: 0.10 + 0.01 * dte)              # a days-to-expiry shape: 11% at 1 day out
    # an untraded strike right at the money carries yesterday's close: it must not be the ATM strike
    d0 = days[-1]
    g = b[(b["date"] == pd.Timestamp(d0)) & (b["kind"] != "FUT")]
    S = float(g["underlying"].iloc[0])
    fake = g.iloc[:2].copy()
    fake["strike"], fake["close"], fake["contracts"] = round(S, 2), [999.0, 1.0], 0.0
    h = atm_iv_history(pd.concat([b, fake, bhav(days, symbol="BANKNIFTY")]), "NIFTY", R, Q, min_days=1)
    assert len(h) == 30 and (h["dte"] >= 1).all()
    assert np.allclose(h["atm_iv"], 10 + h["dte"], atol=0.05)           # IV in %, recovered at each tenor
    tue = h[pd.to_datetime(h["date"]).dt.weekday == 1]
    assert (tue["dte"] == 7).all()                                      # on expiry day it moves to the next expiry
    assert h.iloc[-1]["atm_strike"] != round(S, 2)
    assert atm_iv_history(b, "NIFTY", R, Q, min_days=3)["dte"].min() >= 3


def test_percentile_ranks_against_the_same_days_to_expiry():
    rng = np.random.default_rng(0)
    days = pd.bdate_range(end="2026-09-30", periods=260).date
    hist = pd.DataFrame({"date": days, "dte": [(1 - d.weekday()) % 7 or 7 for d in days]})
    hist["atm_iv"] = np.where(hist["dte"] == 1, 16.0, 11.0) + rng.normal(0, 1, len(hist))
    today = dt.date(2026, 10, 1)
    one = iv_percentile(hist, 14.0, 1, today)
    five = iv_percentile(hist, 14.0, 5, today)
    assert one["atm_ivp"] < 0.1 and five["atm_ivp"] > 0.9                # 14% is low a day out, high five days out
    assert one["atm_ivp_band"] == 1 and one["atm_iv_median"] == pytest.approx(16, abs=0.5)
    assert 0 < iv_percentile(hist, 11.0, 5, today)["atm_ivp"] < 1
    later = iv_percentile(hist, 14.0, 5, dt.date(2026, 3, 2))           # only sessions before "today" count
    assert later["atm_ivp_n"] < five["atm_ivp_n"]
    assert iv_percentile(hist, float("nan"), 5, today) == {} and iv_percentile(None, 12.0, 5, today) == {}
    assert iv_percentile(hist.head(10), 12.0, 5, today) == {}           # too few sessions to say


def test_load_reads_the_warehouse_files(tmp_path):
    from quantdesk.data.warehouse import Warehouse
    assert load(tmp_path, ["NIFTY"], R, Q, 1, dt.date(2026, 10, 1)) == {}
    days = sessions(25)
    Warehouse(tmp_path).upsert("fo_bhav", bhav(days).assign(open=np.nan, high=np.nan, low=np.nan, last=np.nan,
                                                            prev_close=np.nan, settle=np.nan, oi=0.0, chg_oi=0.0,
                                                            lot=65.0, src="test"))
    out = load(tmp_path, ["NIFTY", "BANKNIFTY"], R, Q, 1, days[-1])
    assert list(out) == ["NIFTY"] and len(out["NIFTY"]) == 24           # yesterday and before, not today
