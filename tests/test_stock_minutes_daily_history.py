"""Stock option minutes (kotak_backfill.py / collect_wide.py) and the daily-history importer (daily_history.py,
daily-history.yml): strike selection, asset grouping under the release cap, health lines, split/bonus adjustment and jump
detection, the cross-check, the gap report, `verified` refusal, provenance and immutability, and the workflow's isolation."""
import datetime as dt
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

from quantdesk.config import DEFAULT_CONFIG, Config
from quantdesk.data import collect_wide as W
from quantdesk.data import daily_history as D
from quantdesk.data import kotak_backfill as B
from quantdesk.data.external_aeron import ImmutableViolation, _write_once
from quantdesk.intraday.feeds import IST

ROOT = Path(__file__).resolve().parents[1]
TODAY = dt.date(2026, 10, 19)


# ---- Part A: stock option minutes -------------------------------------------------------------------------------------------
def test_window_is_atm_plus_minus_n_and_falls_back_to_the_chain_middle():
    ks = [100 + 5 * i for i in range(21)]                           # 100 … 200
    keep, src = B.select_window(ks, 151.0, 3)
    assert src == "spot" and keep == [135, 140, 145, 150, 155, 160, 165]
    assert B.select_window(ks, 100.0, 3)[0] == [100, 105, 110, 115]                 # clipped at the edge of the chain
    keep, src = B.select_window(ks, float("nan"), 2)
    assert src == "chain-middle" and keep == [140, 145, 150, 155, 160] and len(keep) == 5
    assert B.select_window([], 100.0, 2) == ([], "none")


def _legs(u, exp, strikes, ce_ltp, pe_ltp):
    mk = lambda r, ltp: [{"inst": {"strkPrc": str(k), "neoSymbol": f"nse_fo|{u}{exp:%y%m%d}{r}{int(k)}"},   # noqa: E731
                          "quote": {"ltp": str(ltp(k))}} for k in strikes]
    return {"data": {"call": mk("C", ce_ltp), "put": mk("P", pe_ltp)}}


class StockKotak:
    def __init__(self, spot=2500.0, fail=(), no_bars=()):
        self.spot, self.fail, self.no_bars, self.calls = spot, set(fail), set(no_bars), {}

    def expiries(self, u, exchange="nse_fo"):
        if u in self.fail:
            raise RuntimeError("HTTP 400 unknown underlying")
        return [dt.date(2026, 10, 13), dt.date(2026, 10, 27), dt.date(2026, 11, 24), dt.date(2026, 12, 29)]

    def option_chain(self, u, exp, count, exchange="nse_fo"):
        ks = [self.spot - 100 + 10 * i for i in range(21)]
        return _legs(u, exp, ks, lambda k: max(self.spot - k, 0) + 20, lambda k: max(k - self.spot, 0) + 20)

    def candles(self, token, interval, start, end, raw=False):
        if any(n in token for n in self.no_bars):
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
        idx = pd.DatetimeIndex([pd.Timestamp(f"{end} 09:15", tz=IST) + pd.Timedelta(minutes=m) for m in range(3)])
        return pd.DataFrame({"open": 1.0, "high": 2.0, "low": 0.5, "close": 1.0, "volume": 5.0}, index=idx)


def test_parity_spot_and_contracts_are_the_money_window_for_the_nearest_live_expiries():
    k = StockKotak(spot=2500.0)
    _, calls, puts = B.chain_parts(k.option_chain("RELIANCE", dt.date(2026, 10, 27), 10))
    assert B.chain_spot(calls, puts) == pytest.approx(2500.0)
    cs, info = B.stock_contracts(k, "RELIANCE", 2, 2, TODAY)
    assert info["atm_source"] == "spot" and info["spot"] == pytest.approx(2500.0)
    assert {c["expiry"] for c in cs} == {dt.date(2026, 10, 27), dt.date(2026, 11, 24)}      # 13 Oct has expired
    assert {c["right"] for c in cs} == {"CE", "PE"} and len(cs) == 2 * 2 * 5
    assert sorted({c["strike"] for c in cs}) == [2480.0, 2490.0, 2500.0, 2510.0, 2520.0]
    given, info2 = B.stock_contracts(k, "RELIANCE", 1, 1, TODAY, spot=2433.0)               # a passed-in close wins
    assert info2["atm_source"] == "spot" and sorted({c["strike"] for c in given}) == [2420.0, 2430.0, 2440.0]


def test_assets_stay_under_the_cap_by_grouping_never_one_per_contract():
    p = B.asset_plan(5, 20, 10)
    assert p["groups"] == 2 and p["per_day"] == 5 + 4 + 2 + 1 and p["fits"] and p["per_shard"] <= 900
    big = B.asset_plan(5, 200, 10)                                  # a long list grows the groups instead of the asset count
    assert big["fits"] and big["per_shard"] <= 900 and big["group_size"] > 10 and big["groups"] <= 10
    assert B.asset_plan(5, 0, 10)["per_day"] == 9
    assert B.group_stocks(list("ABCDE"), 2) == [["A", "B"], ["C", "D"], ["E"]]


def test_backfill_stocks_writes_one_file_per_group_and_isolates_a_failing_stock(tmp_path):
    k = StockKotak(fail={"ONGC"}, no_bars={"TCS"})
    groups = [["RELIANCE", "ONGC"], ["TCS", "INFY"]]
    man = B.backfill_stocks(k, tmp_path, groups, days=3, n_expiries=1, window=2, today=TODAY, say=lambda *a: None)
    run = tmp_path / str(TODAY)
    assert sorted(B.release_names(run)) == ["options_STOCKS-1.parquet", "options_STOCKS-2.parquet", "stock_manifest.json"]
    st = man["stocks"]
    assert st["RELIANCE"]["served"] == st["RELIANCE"]["asked"] == 10 and st["RELIANCE"]["bars"] == 30
    assert "contracts" in st["ONGC"]["errors"] and st["ONGC"]["bars"] == 0
    assert st["TCS"]["empty"] == 10 and st["TCS"]["bars"] == 0 and st["INFY"]["bars"] == 30
    g1 = pd.read_parquet(run / "options_STOCKS-1.parquet")
    assert set(g1["underlying"]) == {"RELIANCE"} and list(g1.columns) == B.COLS
    assert json.loads((run / "stock_manifest.json").read_text())["groups"]["STOCKS-2"] == ["TCS", "INFY"]


def test_stock_minute_health_is_ok_missing_or_unknown_per_stock(tmp_path):
    k = StockKotak(no_bars={"TCS"})
    man = B.backfill_stocks(k, tmp_path, [["RELIANCE", "TCS"]], days=0, n_expiries=1, window=1, today=TODAY, say=lambda *a: None)
    rows = {r["source"]: r for r in W.stock_minute_rows(TODAY, man, ["RELIANCE", "TCS", "INFY"])}
    assert rows["stock_minutes:RELIANCE"]["status"] == "OK" and "ATM from spot" in rows["stock_minutes:RELIANCE"]["detail"]
    assert rows["stock_minutes:TCS"]["status"] == "MISSING"
    assert rows["stock_minutes:INFY"]["status"] == "UNKNOWN"                       # never reached: not the same as missing
    stale = W.stock_minute_rows(dt.date(2026, 10, 20), man, ["RELIANCE"])[0]
    assert stale["status"] == "MISSING" and "not today" in stale["detail"]
    assert {r["status"] for r in W.stock_minute_rows(TODAY, None, ["RELIANCE"])} == {"UNKNOWN"}
    full = W.health(TODAY, None, None, None, ["NIFTY"], 3, man, ["RELIANCE", "TCS"])
    assert [r["source"] for r in full if r["source"].startswith("stock_minutes")] == ["stock_minutes:RELIANCE", "stock_minutes:TCS"]
    assert not [r for r in W.health(TODAY, None, None, None, ["NIFTY"], 3) if r["source"].startswith("stock_minutes")]


def test_config_lists_the_stocks_and_the_stock_minute_window():
    cfg = Config.load(DEFAULT_CONFIG)
    S = W.settings(cfg)
    assert S["stock_minutes"] is True and S["stock_minute_strikes"] == 5 and S["stock_minute_expiries"] == 2
    assert len(S["stocks"]) == 20
    assert B.asset_plan(len(S["indices"]), len(S["stocks"]), S["stock_group_size"], S["shard_trading_days"], S["asset_cap"])["fits"]


# ---- Part B: daily history ----------------------------------------------------------------------------------------------------
def _walk(days, start=100.0, seed=1, vol=0.01):
    r = np.random.default_rng(seed).normal(0, vol, len(days))
    c = start * np.exp(np.cumsum(r))
    return pd.DataFrame({"open": c * 0.999, "high": c * 1.004, "low": c * 0.996, "close": c, "volume": 1000.0},
                        index=pd.DatetimeIndex(days, name="date"))


def _stock(frame, splits_at=None, r=5.0, adjusted=False):
    """A series with a split at `splits_at`: prices before it divided by r (adjusted) or left as printed (raw)."""
    f = frame.copy()
    if splits_at is not None:
        pre = f.index < pd.Timestamp(splits_at)
        scale = np.where(pre, 1.0, 1.0 / r)            # raw: the price falls to 1/r on the ex-date
        if adjusted:
            scale = np.where(pre, 1.0 / r, 1.0 / r)
        f[["open", "high", "low", "close"]] = f[["open", "high", "low", "close"]].mul(scale, axis=0)
    f.insert(0, "symbol", "XYZ")
    return f


DAYS = pd.bdate_range("2025-01-01", "2025-12-31")
SPLIT = pd.Timestamp("2025-06-16")


def test_a_split_the_source_did_not_apply_is_adjusted_and_one_it_did_apply_is_left_alone():
    base = _walk(DAYS)
    acts = pd.DataFrame([{"date": SPLIT, "ratio": 5.0, "note": "split 5:1"}])
    raw, ev = D.adjust(_stock(base, SPLIT), acts)
    assert [e["type"] for e in ev] == ["split_applied"]
    i = raw.index.get_loc(SPLIT)
    assert raw["adj_factor"].iloc[0] == pytest.approx(0.2) and raw["adj_factor"].iloc[i] == 1.0
    assert raw["close"].iloc[i - 1] / raw["close"].iloc[i] == pytest.approx(5.0, rel=0.1)      # the raw series keeps the cliff
    assert abs(raw["adj_close"].iloc[i] / raw["adj_close"].iloc[i - 1] - 1) < 0.05              # the adjusted one does not
    assert "unadjusted_jump" not in ",".join(raw["flags"]) and raw["flags"].iloc[i] == "split_applied"
    src, ev2 = D.adjust(_stock(base, SPLIT, adjusted=True), acts)
    assert [e["type"] for e in ev2] == ["split_in_source"] and (src["adj_factor"] == 1.0).all()  # no double adjustment


def test_a_bonus_is_a_ratio_too_and_an_unexplained_cliff_is_flagged_not_hidden():
    base = _walk(DAYS)
    bonus = pd.DataFrame([{"date": SPLIT, "ratio": 2.0, "note": "bonus 1:1"}])
    out, ev = D.adjust(_stock(base, SPLIT, r=2.0), bonus)
    assert [e["type"] for e in ev] == ["split_applied"] and (out["adj_close"].pct_change().abs().dropna() < 0.1).all()
    none, ev = D.adjust(_stock(base, SPLIT), pd.DataFrame(columns=D.ACTION_COLS))            # no action known: a flagged jump
    assert [e["type"] for e in ev] == ["unadjusted_jump"] and ev[0]["date"] == str(SPLIT.date())
    assert none["flags"].iloc[none.index.get_loc(SPLIT)] == "unadjusted_jump" and (none["adj_factor"] == 1.0).all()
    odd = pd.DataFrame([{"date": SPLIT, "ratio": 3.0, "note": "claims 3:1 but the data fell 5:1"}])
    _, ev = D.adjust(_stock(base, SPLIT), odd, tol=0.1)
    assert {e["type"] for e in ev} == {"action_unconfirmed", "unadjusted_jump"}
    ok, ev = D.adjust(_stock(base, SPLIT), pd.DataFrame(columns=D.ACTION_COLS), accepted={("XYZ", str(SPLIT.date()))})
    assert ev == []                                              # a reviewed, genuine move is not flagged


def test_indices_are_never_adjusted_and_thresholds_differ():
    idx = _walk(DAYS)
    idx.insert(0, "symbol", "NIFTY")
    acts = pd.DataFrame([{"date": SPLIT, "ratio": 5.0, "note": "x"}])
    out, ev = D.adjust(idx, acts, kind="index", jump=0.15)
    assert ev == [] and (out["adj_close"] == out["close"]).all() and (out["adj_factor"] == 1.0).all()
    idx.loc[idx.index[100:], "close"] *= 0.8                                      # a -20% day in an index is beyond 15%
    assert [e["type"] for e in D.adjust(idx, None, kind="index", jump=0.15)[1]] == ["unadjusted_jump"]


def test_impossible_bars_are_dropped_and_counted_never_repaired():
    f = _walk(DAYS[:6])
    f.iloc[1, 1] = 50.0                                           # high below low
    f.iloc[2, 3] = -1.0
    f.iloc[3, 3] = np.nan
    f.iloc[4, 3] = f.iloc[4, 1] * 1.5                             # close above the high
    clean, rej = D.clean(f)
    assert len(clean) == 2 and sum(rej.values()) == 4 and rej["missing_price"] == 1 and rej["non_positive_price"] == 1
    assert clean.index.equals(f.index[[0, 5]])


def test_corporate_action_subjects_parse_to_a_multiple():
    assert D.parse_action_subject("Face Value Split (Sub-Division) - From Rs 10/- Per Share To Rs 2/- Per Share") == pytest.approx(5.0)
    assert D.parse_action_subject("Bonus 1:1") == 2.0 and D.parse_action_subject("Bonus 3:2") == 2.5
    assert D.parse_action_subject("Dividend - Rs 5 Per Share") is None


def test_nse_payloads_parse():
    idx = {"data": {"indexCloseOnlineRecords": [{"EOD_INDEX_NAME": "NIFTY 50", "EOD_TIMESTAMP": "02-Jan-2024",
                                                 "EOD_OPEN_INDEX_VAL": "21,727.7", "EOD_HIGH_INDEX_VAL": 21834.35,
                                                 "EOD_LOW_INDEX_VAL": 21680.0, "EOD_CLOSE_INDEX_VAL": 21665.8}]}}
    df = D.parse_nse_index(idx, "NIFTY 50")
    assert df.index[0] == pd.Timestamp("2024-01-02") and df["open"].iloc[0] == 21727.7 and df["volume"].isna().all()
    eq = {"data": [{"CH_SERIES": "EQ", "CH_TIMESTAMP": "2024-01-02", "CH_OPENING_PRICE": 2600, "CH_TRADE_HIGH_PRICE": 2620,
                    "CH_TRADE_LOW_PRICE": 2580, "CH_CLOSING_PRICE": 2610, "CH_TOT_TRADED_QTY": 12345},
                   {"CH_SERIES": "BE", "CH_TIMESTAMP": "2024-01-03", "CH_OPENING_PRICE": 1}]}
    assert len(D.parse_nse_equity(eq)) == 1


def _adj(frame, kind="equity"):
    f = frame.copy()
    if "symbol" not in f:
        f.insert(0, "symbol", "A")
    return D.adjust(f, None, kind)[0]


def test_crosscheck_records_the_match_rate_and_says_when_there_is_no_second_source():
    a = _adj(_walk(DAYS))
    b = a.copy()
    b["adj_close"] = b["adj_close"] * 1.0001
    x = D.crosscheck(a, b, "A", n=60, tol=0.005, seed=3)
    assert x["available"] and x["compared"] == 60 and x["match_rate"] == 1.0
    bad = b.copy()
    bad.iloc[::3, bad.columns.get_loc("adj_close")] *= 1.05
    x2 = D.crosscheck(a, bad, "A", n=60, tol=0.005, seed=3)
    assert 0.5 < x2["match_rate"] < 0.8 and x2["mismatches"] and D.crosscheck(a, bad, "A", 60, 0.005, 3) == x2   # seeded
    none = D.crosscheck(a, None, "A")
    assert none["available"] is False and none["match_rate"] is None


def test_gap_report_uses_the_official_calendar_where_listed_and_peers_elsewhere():
    days = pd.bdate_range("2025-03-03", "2025-03-14")
    hol = {dt.date(2025, 3, 7)}
    idx = days.drop(pd.Timestamp("2025-03-07"))                   # every index skipped the 7th: a holiday (peer calendar)
    stock = idx.drop(pd.Timestamp("2025-03-11"))                  # only the stock skipped the 11th: a gap
    md, cal = D.market_days({"NIFTY": idx, "BANKNIFTY": idx, "ABC": stock}, set(), set(), ["NIFTY", "BANKNIFTY"])
    g = D.gap_report(stock, md, set())
    assert g["missing_days"] == ["2025-03-11"] and g["expected"] == 9 and cal["peer_calendar_years"] == [2025]
    md2, cal2 = D.market_days({"NIFTY": days, "ABC": days}, hol, {2025}, ["NIFTY"])         # official list: 7th is a holiday
    assert pd.Timestamp("2025-03-07") not in md2 and cal2["official_years"] == [2025]
    g2 = D.gap_report(days, md2, hol)
    assert g2["missing"] == 0 and g2["off_calendar"] == ["2025-03-07"]                        # a bar on a holiday: information


class Fake:
    """A source over prepared frames. `splits` serves the corporate-action table; `down` makes it unreachable."""
    def __init__(self, name, frames, splits=None, down=False, start=None):
        self.name, self.frames, self.splits, self.down, self.start = name, frames, splits or {}, down, start
        self.calls = 0

    def daily(self, symbol, kind, start, end):
        self.calls += 1
        if self.down:
            raise D.SourceDown(f"{self.name}: blocked (HTTP 403)")
        f = self.frames[symbol][["open", "high", "low", "close", "volume"]]
        return f if self.start is None else f[f.index >= pd.Timestamp(self.start)]

    def actions(self, symbol, kind):
        if self.down:
            raise D.SourceDown("blocked")
        return pd.DataFrame(self.splits.get(symbol, []), columns=D.ACTION_COLS)


def _cfg(start="2025-01-01"):
    cfg = Config.load(DEFAULT_CONFIG)
    cfg.data["daily_history"] = {"start": start}
    return cfg


def _world():
    nifty, bank = _walk(DAYS, 20000, 1, 0.008), _walk(DAYS, 50000, 2, 0.01)
    stock = _walk(DAYS, 2500, 3, 0.012)
    return nifty, bank, stock


def test_run_verifies_a_clean_series_records_provenance_and_keeps_raw_and_adjusted(tmp_path):
    nifty, bank, stock = _world()
    raw_stock = _stock(stock, SPLIT).drop(columns="symbol")
    nse = Fake("nse", {"NIFTY": nifty, "BANKNIFTY": bank, "XYZ": raw_stock}, {"XYZ": [{"date": SPLIT, "ratio": 5.0, "note": "5:1"}]})
    noisy = lambda f: f.assign(close=f["close"] * 1.0002)                                    # noqa: E731
    yh = Fake("yahoo", {"NIFTY": noisy(nifty), "BANKNIFTY": noisy(bank), "XYZ": noisy(_stock(stock, SPLIT, adjusted=True).drop(columns="symbol"))},
              {"XYZ": [{"date": SPLIT, "ratio": 5.0, "note": "5:1"}]})
    man = D.run(_cfg(), tmp_path, [nse, yh], end=dt.date(2025, 12, 31), say=lambda *a: None,
                symbols=[("NIFTY", "index"), ("BANKNIFTY", "index"), ("XYZ", "equity")], now=pd.Timestamp("2026-10-19 12:00", tz=IST))
    s = man["series"]["XYZ"]
    assert man["status"] == "verified" and s["status"] == "verified" and s["reasons"] == []
    assert s["source"] == "nse" and s["crosscheck"]["second_source"] == "yahoo" and s["crosscheck"]["match_rate"] >= 0.98
    assert s["gaps"]["missing"] == 0 and [e["type"] for e in s["events"]] == ["split_applied"]
    sh = pd.read_parquet(Path(man["path"]) / "daily_2025.parquet")
    x = sh[sh["symbol"] == "XYZ"]
    assert list(sh.columns) == D.COLS and (x["source"] == "nse").all() and (x["series_status"] == "verified").all()
    assert x["close"].iloc[0] > x["adj_close"].iloc[0] * 4                                    # raw kept beside the adjusted
    assert x["flags"].str.contains("split_applied").sum() == 1
    # provenance: per shard rows, sha256 of the file bytes, a content hash; per series hash, fetched_at, rows, source
    import hashlib
    sd = man["shards"][0]
    assert sd["rows"] == len(sh) and sd["sha256"] == hashlib.sha256((Path(man["path"]) / sd["file"]).read_bytes()).hexdigest()
    assert s["content_hash"] and s["fetched_at"] and s["rows"] == len(DAYS) and s["tried"]["nse"].startswith(f"{len(DAYS)} rows")
    assert json.loads((Path(man["path"]) / "manifest.json").read_text())["series"]["XYZ"]["status"] == "verified"
    # immutability: the same partition again is accepted; different content under the same name is refused
    p = Path(man["path"]) / "daily_2025.parquet"
    assert _write_once(pd.read_parquet(p), p)
    with pytest.raises(ImmutableViolation):
        _write_once(pd.read_parquet(p).assign(close=1.0), p)


def test_nse_blocked_falls_back_to_yahoo_per_row_but_cannot_be_verified_without_a_second_source(tmp_path):
    nifty, bank, stock = _world()
    nse = Fake("nse", {}, down=True)
    yh = Fake("yahoo", {"NIFTY": nifty, "BANKNIFTY": bank, "XYZ": stock})
    man = D.run(_cfg(), tmp_path, [nse, yh], end=dt.date(2025, 12, 31), say=lambda *a: None,
                symbols=[("NIFTY", "index"), ("BANKNIFTY", "index"), ("XYZ", "equity")], now=pd.Timestamp("2026-10-19 12:00", tz=IST))
    s = man["series"]["XYZ"]
    assert s["source"] == "yahoo" and "blocked" in man["series"]["NIFTY"]["tried"]["nse"]
    assert "skipped" in s["tried"]["nse"]                      # the third failure had already switched NSE off for the run
    assert s["status"] == "unverified" and any("second source" in r for r in s["reasons"])
    assert man["status"] == "unverified" and set(man["unverified_series"]) == {"NIFTY", "BANKNIFTY", "XYZ"}
    assert nse.calls == 3
    sh = pd.read_parquet(Path(man["path"]) / "daily_2025.parquet")
    assert (sh["source"] == "yahoo").all()


def test_a_dead_source_is_skipped_after_three_failures_in_a_row(tmp_path):
    nifty, bank, stock = _world()
    nse = Fake("nse", {}, down=True)
    yh = Fake("yahoo", {s: nifty for s in "ABCDE"})
    D.run(_cfg(), tmp_path, [nse, yh], end=dt.date(2025, 12, 31), say=lambda *a: None,
          symbols=[(s, "equity") for s in "ABCDE"], now=pd.Timestamp("2026-10-19 12:00", tz=IST))
    assert nse.calls == 3                                          # asked 3 times, then skipped for the other 2 symbols


def test_unverified_when_a_check_fails_and_nothing_is_filled(tmp_path):
    nifty, bank, stock = _world()
    holed = stock.drop(stock.index[[40, 41, 42, 120, 121]])        # five missing market days
    nse = Fake("nse", {"NIFTY": nifty, "BANKNIFTY": bank, "XYZ": holed})
    yh = Fake("yahoo", {"NIFTY": nifty, "BANKNIFTY": bank, "XYZ": stock}, start="2025-02-01")
    man = D.run(_cfg(), tmp_path, [nse, yh], end=dt.date(2025, 12, 31), say=lambda *a: None,
                symbols=[("NIFTY", "index"), ("BANKNIFTY", "index"), ("XYZ", "equity")], now=pd.Timestamp("2026-10-19 12:00", tz=IST))
    s = man["series"]["XYZ"]
    assert s["status"] == "unverified" and any("missing market days" in r for r in s["reasons"])
    assert s["gaps"]["missing"] == 5 and s["rows"] == len(DAYS) - 5                 # the days stay missing: no forward-fill
    assert man["series"]["NIFTY"]["status"] == "verified"
    short = D.decide({**s, "first": "2025-09-01", "rejected_total": 0, "events": [], "rows": 5,
                      "crosscheck": {"available": True, "compared": 60, "match_rate": 1.0},
                      "gaps": {"missing": 0, "missing_fraction": 0.0}}, D.settings(_cfg()), dt.date(2025, 1, 1))
    assert short[0] == "unverified" and "starts 2025-09-01" in short[1][0]


def test_stock_list_comes_from_config_plus_extras_capped():
    cfg = Config.load(DEFAULT_CONFIG)
    S = D.settings(cfg)
    assert S["stocks"][:3] == ["RELIANCE", "HDFCBANK", "ICICIBANK"] and len(S["stocks"]) == 20
    assert S["indices"] == ["SENSEX", "NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY"] and S["start"] == "2013-01-01"
    cfg.data["daily_history"] = {"extra_stocks": [f"S{i}" for i in range(80)], "max_stocks": 70}
    assert len(D.settings(cfg)["stocks"]) == 70


# ---- the new workflow --------------------------------------------------------------------------------------------------------
WF = ROOT / ".github" / "workflows" / "daily-history.yml"


def test_daily_history_workflow_is_manual_only_secretless_pinned_and_isolated():
    text = WF.read_text(encoding="utf-8")
    wf = yaml.safe_load(text)
    live = yaml.safe_load((ROOT / ".github" / "workflows" / "live.yml").read_text(encoding="utf-8"))
    on = wf.get("on", wf.get(True))
    assert list(on) == ["workflow_dispatch"]                       # no schedule, no push, no PR trigger
    assert wf["permissions"] == {"contents": "write"} and all("permissions" not in j for j in wf["jobs"].values())
    assert not re.findall(r"secrets\.(\w+)", text)
    for uses in re.findall(r"uses:\s*(\S+)", text):
        assert re.fullmatch(r"[\w./-]+@[0-9a-f]{40}", uses), uses
    assert wf["concurrency"]["group"] == "daily-history" != live["concurrency"]["group"]
    for st in wf["jobs"]["import"]["steps"]:
        assert st.get("continue-on-error") is True, st
    assert "${{ inputs." not in "".join(st.get("run", "") for st in wf["jobs"]["import"]["steps"])   # inputs via env, not the shell
    assert "quantdesk intraday" not in text and "KOTAK" not in text


def test_collect_wide_workflow_still_adds_no_secret_and_live_is_untouched():
    cw = (ROOT / ".github" / "workflows" / "collect-wide.yml").read_text(encoding="utf-8")
    assert set(re.findall(r"secrets\.(\w+)", cw)) == {"KOTAK_CONSUMER_KEY"}
    live = (ROOT / ".github" / "workflows" / "live.yml").read_text(encoding="utf-8")
    assert "daily-history" not in live and "stock_minutes" not in live and "collect-wide" not in live
