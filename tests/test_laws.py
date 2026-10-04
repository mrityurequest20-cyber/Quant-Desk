"""expiry_eve_law_v1 (research/laws.py): a law found on two indices is tested once on held-out instruments, pooled by
expiry week, in instrument-neutral units. It must replicate where premium is rich, and fail where it is fair."""
import datetime as dt

import numpy as np
import pandas as pd

from quantdesk.research import laws as L
from test_warehouse_research import _world


def market(symbols, iv, rv, seed0=1):
    parts = []
    for i, sym in enumerate(symbols):
        opts, spot = _world(iv=iv, rv=rv, n_exp=120, seed=seed0 + i)
        opts = opts.assign(symbol=sym, underlying=opts["date"].map(spot), settle=np.nan, lot=50.0)
        parts.append(opts)
    return pd.concat(parts, ignore_index=True)


def test_rich_premium_replicates_and_fair_premium_does_not():
    spec = L.load_spec()
    held = spec["held_out"]["instruments"][:3]
    rich = pd.concat([L.trades(market(held, 0.20, 0.11), s, spec) for s in held], ignore_index=True)
    res = L.evaluate(rich, spec)
    st = res["structures"]["strangle"]
    assert st["replicated"] and set(st["candidates"]) == set(held)
    assert st["pooled"]["weeks"] > 50 and all(st["rows"][s]["kept"] > 0 for s in held)
    fair = pd.concat([L.trades(market(held, 0.12, 0.12, seed0=7), s, spec) for s in held], ignore_index=True)
    assert not L.evaluate(fair, spec)["structures"]["strangle"]["replicated"]       # costs eat a fair premium
    assert "REPLICATES" in L.render(res)


def test_spot_falls_back_to_the_nearest_future():
    d1, d2, e1, e2 = dt.date(2023, 3, 1), dt.date(2023, 3, 2), dt.date(2023, 3, 2), dt.date(2023, 3, 30)
    opts = pd.DataFrame([
        {"date": d1, "symbol": "FINNIFTY", "kind": "FUT", "expiry": e1, "strike": np.nan, "close": 18010, "settle": 18005, "underlying": np.nan},
        {"date": d1, "symbol": "FINNIFTY", "kind": "FUT", "expiry": e2, "strike": np.nan, "close": 18100, "settle": 18090, "underlying": np.nan},
        {"date": d2, "symbol": "FINNIFTY", "kind": "FUT", "expiry": e1, "strike": np.nan, "close": 17950, "settle": 17940.5, "underlying": np.nan},
        {"date": d2, "symbol": "FINNIFTY", "kind": "CE", "expiry": e2, "strike": 18000, "close": 120, "settle": 120, "underlying": 17941.0}])
    s = L.spot(opts, "FINNIFTY")
    assert s[d1] == 18005 and s[d2] == 17941.0                 # the file's underlying wins; else the near future settles


def test_official_closes_take_precedence_over_the_monthly_future():
    """v2: on a weekly expiry with no underlying column, the monthly future carries basis; NSE's official close wins."""
    import datetime as dt

    import numpy as np
    import pandas as pd

    from quantdesk.research import laws as L
    d1, d2 = dt.date(2023, 3, 6), dt.date(2023, 3, 7)
    opts = pd.DataFrame([
        {"date": d1, "symbol": "FINNIFTY", "kind": "FUT", "expiry": dt.date(2023, 3, 28), "strike": 0.0, "close": 18100.0,
         "settle": 18090.0, "underlying": np.nan},
        {"date": d2, "symbol": "FINNIFTY", "kind": "FUT", "expiry": dt.date(2023, 3, 28), "strike": 0.0, "close": 18200.0,
         "settle": 18190.0, "underlying": np.nan}])
    assert list(L.spot(opts, "FINNIFTY")) == [18090.0, 18190.0]                    # v1: the monthly future, basis and all
    official = pd.Series({d1: 18050.0})                                             # one day has an official close
    assert list(L.spot(opts, "FINNIFTY", official)) == [18050.0, 18190.0]
    assert L.official_closes(None, {"name": "x"}) == {}                             # v1 specs never read the table
