"""expiry_wings_v1 (research/wings.py): the spec's variants run through the history's own trade builder, a far wing
caps the loss a crash does to the strangle, and the selection rule is the registered one."""

from quantdesk.research import wings as WG
from test_warehouse_research import _world


def test_variants_run_and_the_wings_cap_the_crash():
    spec = WG.load_spec()
    assert set(WG.strategies(spec)) == {"short_strangle_20d", "iron_condor_20_10", "iron_condor_20_05",
                                        "iron_condor_20_03", "iron_condor_20_02"}
    opts, spot = _world(iv=0.20, rv=0.11)
    opts["symbol"] = "NIFTY"
    crash = spot.index[-30:]                                     # a late crash: the index falls 9% and stays there
    spot.loc[crash] *= 0.91
    tr = WG.build(opts, {"NIFTY": spot}, spec)
    assert set(tr["k"]) == {1} and set(tr["strategy"]) == set(WG.strategies(spec))
    res = WG.evaluate(tr, spec)
    rows = {r["key"]: r for r in res["rows"]}
    assert set(rows) == {"B0", "A0", "W5", "W3", "W2"}
    assert rows["B0"]["max_loss_median"] is None and rows["W3"]["max_loss_median"] > 0
    for k in ("W5", "W3", "W2"):                                  # a defined loss: never worse than its max loss
        assert rows[k]["worst"] >= -rows[k]["max_loss_median"] * 3
    sh = res["shocks"]["NIFTY"]
    assert len(sh) and sh["W3"].iloc[0] > sh["B0"].iloc[0] + 30000      # the crash: the wing pays out
    assert sh["W3"].min() > 2 * sh["B0"].min() / 5                       # and caps the worst day (on mild days it costs a little)
    assert rows["B0"]["credit"] > rows["W3"]["credit"] > rows["A0"]["credit"]   # far wings cost less than 10-delta ones
    md = WG.render(res)
    assert "NIFTY" in md and "Selection" in md


def test_selection_is_the_registered_rule():
    base = {"symbol": "NIFTY", "role": "candidate", "mean_first": 100.0, "mean_last": 50.0}
    rows = [dict(base, key="W5", t=2.5, per_year=40000.0),
            dict(base, key="W3", t=2.2, per_year=60000.0),
            dict(base, key="W2", t=1.9, per_year=90000.0),                   # most money, but t < 2: not eligible
            dict(base, key="B0", role="reference", t=3.0, per_year=99000.0),  # references never selected
            dict(base, symbol="BANKNIFTY", key="W3", t=2.4, per_year=30000.0, mean_last=-10.0)]  # fails the last third
    assert WG.select(rows) == {"NIFTY": "W3", "BANKNIFTY": None}
