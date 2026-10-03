"""Warehouse research: the option-trade P&L arithmetic, that a rich-IV world shows a harvestable premium and a fair one
doesn't, and that a planted positioning signal is found while noise isn't."""
import datetime as dt
import math

import numpy as np
import pandas as pd
import pytest

from quantdesk.options.pricing import bs_price
from quantdesk.research import warehouse_research as W


def bdays(n, start="2024-01-01"):
    return [d.date() for d in pd.bdate_range(start, periods=n)]


def chain_rows(day, expiry, S, sigma, strikes, T=None):
    T = (max((expiry - day).days, 0) / 365 + 1e-9) if T is None else T
    rows = []
    for K in strikes:
        for right in ("CE", "PE"):
            rows.append({"date": day, "kind": right, "expiry": expiry, "strike": float(K),
                         "close": round(max(bs_price(S, K, T, W.R, W.Q, sigma, right), 0.05), 2), "contracts": 100.0})
    return rows


def test_short_straddle_pnl_by_hand():
    days = bdays(15)
    spot = pd.Series(20000.0, index=days)
    spot[days[-1]] = 20100.0                                                    # settles 100 points above the strike
    e = days[-1]
    opts = pd.DataFrame(chain_rows(days[-2], e, 20000.0, 0.15, range(19500, 20550, 50)))
    tr = W.build_trades(opts, spot, "NIFTY")
    t = tr[(tr.strategy == "short_straddle") & (tr.k == 1)].iloc[0]
    c = opts[(opts.kind == "CE") & (opts.strike == 20000)].close.iloc[0]
    p = opts[(opts.kind == "PE") & (opts.strike == 20000)].close.iloc[0]
    want = (c - W.leg_cost(c)) + (p - W.leg_cost(p)) - 100.0
    assert math.isclose(t.pnl_pts, want, abs_tol=1e-9) and t.strikes == [20000.0, 20000.0]
    assert math.isclose(t.credit_pts, c + p)
    fly = tr[tr.strategy == "iron_fly"].iloc[0]
    assert fly.max_loss_pts > 0 and len(fly.strikes) == 4                      # defined risk, four legs


def _world(iv, rv, n_exp=200, seed=1):
    """Weekly expiries; the index follows risk-neutral GBM at `rv` on trading days, and options are priced at `iv` over
    the trading days left (so iv == rv is a genuinely fair market: no weekend or drift gift to either side)."""
    rng = np.random.default_rng(seed)
    days = bdays(n_exp * 5 + 20)
    mu = (W.R - W.Q - rv * rv / 2) / 252
    S = 20000 * np.exp(np.cumsum(rng.normal(mu, rv / math.sqrt(252), len(days))))
    spot = pd.Series(S, index=days)
    rows = []
    for j in range(4, n_exp * 5 + 15, 5):
        if j + 1 >= len(days):
            break
        e = days[j + 1]
        for k in (1, 3, 5):
            d = days[j + 1 - k]
            s0 = float(spot[d])
            atm = round(s0 / 50) * 50
            rows += chain_rows(d, e, s0, iv, range(int(atm - 1000), int(atm + 1050), 50), T=k / 252)
    return pd.DataFrame(rows), spot


def test_rich_implied_vol_shows_a_premium_and_fair_pricing_does_not():
    opts, spot = _world(iv=0.20, rv=0.11)
    trades = W.build_trades(opts, spot, "NIFTY")
    res = {(r.strategy, r.k): r for r in W.evaluate_vrp(trades)}
    ss = res[("short_straddle", 1)]
    assert ss.mean_pts > 0 and ss.t > 3 and ss.verdict.startswith("PAPER CANDIDATE")
    assert "fits ₹500k" in ss.verdict and W.ACCOUNT == 500_000                  # a naked straddle (~₹1.5–2L) fits ₹5L
    small = {(r.strategy, r.k): r for r in W.evaluate_vrp(trades, account=100_000)}
    assert "needs" in small[("short_straddle", 1)].verdict                       # ...but not the old ₹1L account
    opts, spot = _world(iv=0.12, rv=0.12, seed=2)
    fair = {(r.strategy, r.k): r for r in W.evaluate_vrp(W.build_trades(opts, spot, "NIFTY"))}
    assert not any(r.verdict.startswith("PAPER CANDIDATE") for r in fair.values())  # costs eat a fairly priced premium


def _participants(n=900, planted=True, seed=3):
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2021-01-01", periods=n)
    net = np.cumsum(rng.normal(0, 5000, n))
    rows = []
    for d, x in zip(dates, net):
        long_ = 200000 + max(x, -150000)
        rows.append({"date": d, "participant": "FII", "fut_idx_long": long_, "fut_idx_short": 200000.0,
                     "opt_idx_call_long": 1e5 + rng.normal(0, 1e3), "opt_idx_call_short": 1e5, "opt_idx_put_long": 1e5,
                     "opt_idx_put_short": 1e5 + rng.normal(0, 1e3)})
        rows.append({"date": d, "participant": "Client", "fut_idx_long": 3e5 + rng.normal(0, 1e4), "fut_idx_short": 3e5,
                     "opt_idx_call_long": 1, "opt_idx_call_short": 1, "opt_idx_put_long": 1, "opt_idx_put_short": 1})
    part = pd.DataFrame(rows)
    d1 = np.sign(np.diff(net, prepend=net[0]))
    oc = rng.normal(0, 0.008, n)
    if planted:                                                                  # the next session follows FII's change
        oc[1:] += 0.004 * d1[:-1]
    o = 20000 * np.exp(np.cumsum(rng.normal(0, 0.003, n)))
    daily = pd.DataFrame({"open": o, "high": o, "low": o, "close": o * np.exp(oc)}, index=dates)
    return part, {"NIFTY": daily}


def test_positioning_finds_a_planted_signal_and_not_noise():
    part, daily = _participants(planted=True)
    res = {r.id: r for r in W.run_positioning(part, daily)}
    assert res["P1"].verdict == "PAPER CANDIDATE" and res["P1"].effect_bps > 20
    part, daily = _participants(planted=False, seed=4)
    assert not any(r.verdict == "PAPER CANDIDATE" for r in W.run_positioning(part, daily))


def test_scorecards_and_stability_on_a_rich_world():
    opts, spot = _world(iv=0.20, rv=0.11, n_exp=120, seed=5)
    tr = W.build_trades(opts, spot, "NIFTY")
    vrp = W.evaluate_vrp(tr)
    cards = W.scorecards(vrp, tr, n_trials=len(vrp))
    assert cards and all(sc["n"] >= 20 and "gates" in sc for _, sc in cards)
    r, sc = cards[0]
    assert sc["expectancy"] > 0 and sc["sqn"] > 0 and "ruin" in sc and sc["n_trials"] == len(vrp)
    st = W.stability({"NIFTY": opts}, {"NIFTY": spot}, None, [r])
    assert st[0]["verdict"] in ("stable", "no parameters to perturb (ATM strikes)") or st[0]["verdict"].startswith("brittle")
    if "−10%" in st[0]:
        assert st[0]["−10%"] > 0 and st[0]["+10%"] > 0                         # a rich premium survives a nudge


def test_term_structure_from_futures():
    days = bdays(30)
    spot = pd.Series(20000.0, index=days)
    e1, e2 = days[-1] + pd.Timedelta(days=20), days[-1] + pd.Timedelta(days=48)
    rows = []
    for d in days:
        for e in (e1, e2):
            T = (e - d).days / 365
            rows.append({"date": d, "kind": "FUT", "expiry": e, "close": 20000 * math.exp(0.07 * T)})
    ts = W.term_structure(pd.DataFrame(rows), spot)
    assert len(ts) == 30 and ts["carry_ann"].iloc[-1] == pytest.approx(0.07, abs=1e-6)
    assert ts["roll_ann"].median() == pytest.approx(0.07, abs=1e-6) and (ts["basis"] > 0).all()


def test_surface_pca_sees_a_level_factor():
    rng = np.random.default_rng(6)
    days = bdays(90)
    spot = pd.Series(20000.0, index=days)
    rows, level = [], 0.15
    for d in days:
        level = max(0.08, level + rng.normal(0, 0.01))
        e = d + dt.timedelta(days=30)
        for K in np.arange(17500, 22550, 50):
            for right in ("CE", "PE"):
                iv = level + 0.1 * max(0, (20000 - K) / 20000)                    # a put skew riding on the level
                rows.append({"date": d, "kind": right, "expiry": e, "strike": float(K), "contracts": 10.0,
                             "close": bs_price(20000.0, K, 30 / 365, W.R, W.Q, iv, right)})
    res = W.surface_pca(pd.DataFrame(rows), spot)
    assert res["days"] >= 85 and res["explained"][0] > 0.9                      # it all moves together
