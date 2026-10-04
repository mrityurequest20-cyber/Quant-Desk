"""The warehouse audit (data/audit.py) and NSE's official index closes: coverage against an independent calendar,
duplicates, holiday-shifted and re-dated expiries told apart from missing data, and the expiry-day settlement checked
against the exchange's own close."""
import datetime as dt

import pandas as pd

from quantdesk.data import audit as A
from quantdesk.data import nse as N

IC = b"""Index Name,Index Date,Open Index Value,High Index Value,Low Index Value,Closing Index Value,Points Change,Change(%),Volume,Turnover (Rs. Cr.),P/E,P/B,Div Yield
Nifty 50,03-09-2024,25313.4,25321.7,25235.8,25279.85,1.15,0,212131921,27276.14,23.51,4.27,1.21
Nifty Financial Services,03-09-2024,23600,23700,23500,23650.5,1,0,1,1,1,1,1
Nifty 100,03-09-2024,26000,26100,25900,26050,1,0,1,1,1,1,1
India VIX,03-09-2024,14,15,13,-,1,0,1,1,1,1,1
"""


def test_index_close_file_parses_and_names_the_fo_underlyings():
    df = N.parse_index_close(IC, dt.date(2024, 9, 3))
    assert list(df["index"]) == ["Nifty 50", "Nifty Financial Services", "Nifty 100"]     # a dash is no close
    assert dict(zip(df["index"], df["symbol"])) == {"Nifty 50": "NIFTY", "Nifty Financial Services": "FINNIFTY",
                                                    "Nifty 100": ""}
    assert df.loc[0, "close"] == 25279.85 and (df["date"] == pd.Timestamp("2024-09-03")).all()


def _days(*ds):
    return pd.DataFrame([{"date": pd.Timestamp(d), "index": "Nifty 50", "symbol": "NIFTY", "close": 100.0 + i}
                         for i, d in enumerate(ds)])


def _opt(date, expiry, strike=100.0, kind="CE", close=1.0, contracts=10, settle=0.0, underlying=float("nan")):
    return {"date": pd.Timestamp(date), "symbol": "NIFTY", "kind": kind, "expiry": pd.Timestamp(expiry), "strike": strike,
            "high": close, "low": close, "close": close, "settle": settle, "underlying": underlying,
            "contracts": contracts, "lot": 75.0, "src": "old"}


def test_the_audit_tells_explained_gaps_from_missing_data(tmp_path):
    cal = ["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04", "2024-01-08", "2024-01-09", "2024-01-10"]
    _days(*cal).assign(date=lambda d: d["date"]).to_parquet(tmp_path / "nse_index_close_2024.parquet")
    rows = [_opt(d, "2024-01-04") for d in ("2024-01-01", "2024-01-02", "2024-01-03")]       # 01-04 itself: missing
    rows += [_opt("2024-01-02", "2024-01-05")]                                                   # 01-05: a holiday
    rows += [_opt("2024-01-01", "2024-01-08")]                                                   # last seen 7 days out: re-dated
    rows += [_opt("2024-01-08", "2024-01-09"), _opt("2024-01-09", "2024-01-09", settle=101.0 + 4)]   # settles on the close
    rows += [_opt("2024-01-08", "2024-01-09")]                                                   # a duplicate row
    rows += [_opt("2024-01-10", "2024-01-09")]                                                   # traded after expiry
    pd.DataFrame(rows).to_parquet(tmp_path / "fo_bhav_2024-01.parquet")
    res = A.run(tmp_path)
    t = res["tables"]["fo_bhav"]
    assert t["coverage"]["missing"] == ["2024-01-04"] and t["duplicates"] == 1
    gaps = t["contracts"]["expiry_day_gaps"]
    assert gaps == {"holiday_shifted": ["NIFTY 2024-01-05"], "redated": ["NIFTY 2024-01-08"], "missing": ["NIFTY 2024-01-04"]}
    assert t["contracts"]["rows_after_expiry"] == 1
    s = t["settlement"]["expiring_settle_is_official_close"]
    assert s["carry_a_value"] == 1 and s["match_within_0.01pct"] == 1.0
    v = "\n".join(res["verdict"])
    assert "1 trading day(s) missing (2024-01-04)" in v and "1 duplicate rows" in v and "NIFTY 2024-01-04" in v
    assert "Warehouse audit" in A.render(res)


def test_the_basis_of_a_future_that_does_not_expire_is_measured(tmp_path):
    _days("2024-01-01", "2024-01-02").to_parquet(tmp_path / "nse_index_close_2024.parquet")    # closes 100, 101
    rows = [_opt("2024-01-01", "2024-01-02"), _opt("2024-01-02", "2024-01-02"),
            dict(_opt("2024-01-02", "2024-01-25", kind="FUT", strike=0.0, settle=101.0 * 1.002))]  # monthly future
    pd.DataFrame(rows).to_parquet(tmp_path / "fo_bhav_2024-01.parquet")
    b = A.run(tmp_path)["tables"]["fo_bhav"]["settlement"]["futures_fallback_basis"]["expiry_days_future_does_not_expire"]
    assert b["days"] == 1 and abs(b["mean_pct"] - 0.2) < 1e-9


def test_a_day_the_exchange_never_published_is_not_an_alarm():
    days = list(pd.to_datetime(["2021-03-26", "2021-03-30", "2021-03-31"]))
    df = pd.DataFrame({"date": pd.to_datetime(["2021-03-26", "2021-03-31"])})
    c = A._coverage(df, days, unpublished={"2021-03-30": "404 at NSE"})
    assert c["missing"] == [] and c["unpublished"] == {"2021-03-30": "404 at NSE"}
    assert A._coverage(df, days)["missing"] == ["2021-03-30"]
