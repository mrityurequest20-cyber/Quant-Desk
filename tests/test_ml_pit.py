"""P0.3/P0.4: the point-in-time canary (quantdesk/ml/pit.py): that it passes an honest builder, catches the leaks a feature table really has,
refuses a perturbation that never reached the future, and that the locked pipeline's own table (volstudy.rows) is point-in-time."""
import datetime as dt

import numpy as np
import pandas as pd
import pytest

from quantdesk.autolearn import volstudy as V
from quantdesk.ml import pit as P

D, T, H = 12, 40, 3
KEYS = [(3, 10), (6, 25), (9, 5)]
FEATS = ["ret_past", "mean_past", "prev_close"]


def make_data(seed=0):
    return {"price": 100 + np.cumsum(np.random.default_rng(seed).standard_normal((D, T)), axis=1)}


def builder(leak=None):
    def build(data):
        p = data["price"]
        rows = []
        for d in range(D):
            for t in range(2, T - H):
                row = {"d": d, "t": t, "ret_past": p[d, t] - p[d, t - 1], "mean_past": p[d, :t + 1].mean(),
                       "prev_close": p[d - 1, -1] if d else np.nan, "label": p[d, t + H] - p[d, t]}
                if leak == "peek":
                    row["peek"] = p[d, t + 1] - p[d, t]                                    # next bar
                elif leak == "day_mean":
                    row["peek"] = p[d, :].mean()                                           # the whole day, known only at the close
                elif leak == "global_scale":
                    row["peek"] = (p[d, t] - p[d, t - 1]) / p.std()                        # scaled by all data, future days included
                elif leak == "next_open":
                    row["peek"] = p[d + 1, 0] if d + 1 < D else np.nan                     # tomorrow's open
                rows.append(row)
        return pd.DataFrame(rows)
    return build


def perturb(data, key, rng):
    d, t = key
    p = data["price"].copy()
    p[d, t + 1:] = p[d, t] + np.cumsum(rng.standard_normal(T - t - 1) * 3)
    p[d + 1:] = 100 + np.cumsum(rng.standard_normal(p[d + 1:].shape) * 3, axis=1)
    return {"price": p}


def run(leak=None, features=FEATS, **kw):
    return P.check_point_in_time(builder(leak), make_data(), KEYS, kw.pop("perturb", perturb), ["d", "t"], features, ["label"], **kw)


def test_an_honest_table_passes_and_its_labels_do_move():
    rep = run()
    assert rep.ok and rep.checked == 3 and rep.leaks == []
    assert rep.label_moved["label"] > 0.1                                                  # the perturbation reached the future
    assert max(rep.max_rel_diff.values()) == 0.0
    assert P.assert_point_in_time(builder(), make_data(), KEYS, perturb, ["d", "t"], FEATS, ["label"]).ok


@pytest.mark.parametrize("leak", ["peek", "day_mean", "global_scale", "next_open"])
def test_each_kind_of_leak_is_caught(leak):
    rep = run(leak, FEATS + ["peek"])
    assert not rep.ok and {x["feature"] for x in rep.leaks} == {"peek"}
    with pytest.raises(P.PointInTimeError, match="leaks in"):
        P.assert_point_in_time(builder(leak), make_data(), KEYS, perturb, ["d", "t"], FEATS + ["peek"], ["label"])


def test_a_perturbation_that_never_reaches_the_future_is_an_error_not_a_pass():
    with pytest.raises(P.PointInTimeError, match="proves nothing"):
        run(perturb=lambda data, key, rng: {"price": data["price"].copy()})
    with pytest.raises(P.PointInTimeError, match="proves nothing"):                          # one that only changes the past
        run(perturb=lambda data, key, rng: {"price": np.concatenate([data["price"][:key[0], :] * 1.5, data["price"][key[0]:]])})
    rep = run(perturb=lambda data, key, rng: {"price": data["price"].copy()}, require_label_move=False)
    assert rep.ok and rep.label_moved["label"] == 0.0                                      # only if the caller says so


def test_the_tolerance_separates_rounding_noise_from_a_leak():
    def noisy(data, key, rng):
        out = perturb(data, key, rng)
        return out

    def build_noise(data):
        df = builder()(data)
        df["mean_past"] = df["mean_past"] * (1 + 1e-13 * np.random.default_rng(int(data["price"].sum() * 1e6) % 2 ** 31).standard_normal(len(df)))
        return df
    rep = P.check_point_in_time(build_noise, make_data(), KEYS, noisy, ["d", "t"], FEATS, ["label"], rtol=1e-9)
    assert rep.ok and 0 < rep.max_rel_diff["mean_past"] < 1e-9                              # 1e-13 relative noise is not a leak
    assert not P.check_point_in_time(build_noise, make_data(), KEYS, noisy, ["d", "t"], FEATS, ["label"], rtol=1e-15).ok   # a tolerance this tight would see it


def test_nan_handling_and_vanished_rows():
    assert P._rel(np.array([np.nan, np.nan, 1.0, np.nan]), np.array([np.nan, 1.0, 1.0, 2.0])).tolist() == [0.0, np.inf, 0.0, np.inf]
    assert P._rel(np.array([0.0]), np.array([0.0])).tolist() == [0.0]
    base = builder()

    def drops_when_future_changes(data):
        df = base(data)
        return df[~((df["d"] == 3) & (df["t"] == 10) & (data["price"][3, 11] != make_data()["price"][3, 11]))]
    rep = P.check_point_in_time(drops_when_future_changes, make_data(), [(3, 10)], perturb, ["d", "t"], FEATS, ["label"])
    assert not rep.ok and rep.leaks[0]["feature"] == "(rows)"                              # a row that exists only for some futures
    with pytest.raises(ValueError, match="no row of the table"):
        P.check_point_in_time(base, make_data(), [(99, 99)], perturb, ["d", "t"], FEATS, ["label"])
    dup = lambda data: pd.concat([base(data), base(data).iloc[:1]])
    with pytest.raises(ValueError, match="more than one row"):
        P.check_point_in_time(dup, make_data(), KEYS, perturb, ["d", "t"], FEATS, ["label"])


# ---- the locked pipeline's own table ---------------------------------------------------------------------------------
def minute_grid(n_days=70, seed=4):
    rng = np.random.default_rng(seed)
    days = pd.Index([d.date() for d in pd.bdate_range("2021-01-04", periods=n_days)])
    r = rng.standard_normal((n_days, 375)) * 3e-4 * (1 + 0.5 * np.sin(np.arange(375) / 60))
    return {"days": days, "r": r, "missing": np.zeros((n_days, 375), dtype=bool), "opens": 15000 * np.exp(np.cumsum(rng.standard_normal(n_days) * 0.004))}


def test_volstudy_rows_is_point_in_time_under_the_canary():
    """The locked move-size study's feature table (autolearn/volstudy.rows) was never tested for look-ahead. Everything after a decision point,
    this day's remaining minutes and every later day, is replaced; the table's features at that point must not move, its targets must."""
    grid = minute_grid()
    s = V.profile((grid["r"] ** 2)[:40])                                                    # a training-window object, held fixed
    build = lambda g: V.rows("X", g["days"], g["r"], g["missing"], g["opens"], s)
    keys = [(grid["days"][i], m) for i, m in ((15, 30), (25, 135), (40, 255), (50, 345), (60, 90))]
    feats = ["F_A", "F_B", "x_prev", "x_prev5", "x_today", "x_gap"]
    rep = P.assert_point_in_time(build, grid, keys, P.perturb_minute_grid, ["day", "m", "horizon"], feats, ["rv", "ret"])
    assert rep.checked == 5 and rep.label_moved["rv"] > 0 and max(rep.max_rel_diff.values()) < 1e-9


def test_the_canary_catches_a_leak_planted_in_the_locked_pipelines_table():
    grid = minute_grid()
    s = V.profile((grid["r"] ** 2)[:40])

    def leaky(g):
        d = V.rows("X", g["days"], g["r"], g["missing"], g["opens"], s)
        full_day = pd.Series((g["r"] ** 2).sum(1), index=g["days"])                         # this day's whole realised variance: known at the close
        d["x_today"] = np.log(full_day.reindex(d["day"]).to_numpy())
        return d
    keys = [(grid["days"][20], 105), (grid["days"][35], 195)]
    rep = P.check_point_in_time(leaky, grid, keys, P.perturb_minute_grid, ["day", "m", "horizon"], ["F_A", "x_today"], ["rv"])
    assert not rep.ok and {x["feature"] for x in rep.leaks} == {"x_today"}


def test_perturb_minute_grid_changes_exactly_the_future():
    grid = minute_grid(20)
    out = P.perturb_minute_grid(grid, (grid["days"][5], 100), np.random.default_rng(1))
    assert np.array_equal(out["r"][:5], grid["r"][:5]) and np.array_equal(out["r"][5, :100], grid["r"][5, :100])      # the past is untouched
    assert not np.array_equal(out["r"][5, 100:], grid["r"][5, 100:]) and not np.array_equal(out["r"][6:], grid["r"][6:])
    assert np.array_equal(out["opens"][:6], grid["opens"][:6]) and not np.array_equal(out["opens"][6:], grid["opens"][6:])
    assert out["days"] is grid["days"] and out["missing"] is grid["missing"]
    assert np.array_equal(P.perturb_minute_grid(grid, (5, 100), np.random.default_rng(1))["r"], out["r"])             # a day index works too
    assert dt.date(2021, 1, 4) == grid["days"][0]
