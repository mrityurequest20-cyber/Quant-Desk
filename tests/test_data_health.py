"""quantdesk.data.health: every channel check, on synthetic data shaped like the real release assets (no network)."""
from __future__ import annotations

import datetime as dt
import io
import json

import numpy as np
import pandas as pd
import pytest

from quantdesk.data import health as H

DAY = dt.date(2026, 11, 6)          # a Friday
EVE = "2026-11-05"                  # the evening before it: what the MCX/currency check judges
IST = H.IST


def _pq(df: pd.DataFrame) -> bytes:
    b = io.BytesIO()
    df.to_parquet(b)
    return b.getvalue()


def _bars(day=DAY, symbols=H.BAR_SYMBOLS, drop=(), flat_from=None, flat_len=0, bad_high=False) -> pd.DataFrame:
    rows = []
    grid = pd.date_range(dt.datetime.combine(day, dt.time(9, 15), tzinfo=IST), periods=375, freq="min")
    for s in symbols:
        px = 100.0
        for i, ts in enumerate(grid):
            if ts.strftime("%H:%M") in drop:
                continue
            px = px + (0.5 if i % 2 else -0.3)                   # always moving
            if flat_from is not None and flat_from <= i < flat_from + flat_len:
                px = 100.0 + flat_from
            hi = px + 0.2
            rows.append({"ts": ts, "symbol": s, "open": px, "high": hi - (5 if bad_high and i == 7 else 0), "low": px - 0.2, "close": px})
    return pd.DataFrame(rows)


def _chains(day=DAY, underlyings=H.CHAIN_UNDERLYINGS, skip=(), oi=1000.0, extra_bad=None) -> pd.DataFrame:
    rows = []
    for u in underlyings:
        for ts in pd.date_range(dt.datetime.combine(day, dt.time(9, 15), tzinfo=IST), dt.datetime.combine(day, dt.time(15, 30), tzinfo=IST), freq="min"):
            if u in skip and ts.minute % 2 == 0:
                continue
            for k in (100.0, 200.0):
                rows.append({"ts": ts, "underlying": u, "expiry": pd.Timestamp(day + dt.timedelta(days=7)), "strike": k, "spot": 150.0,
                             "ce_oi": oi, "pe_oi": oi, "ce_bid": 1.0, "ce_ask": 1.2, "pe_bid": 1.0, "pe_ask": 1.2, "source": "kotak"})
    df = pd.DataFrame(rows)
    if extra_bad is not None:
        df.loc[df.index[:extra_bad[1]], extra_bad[0]] = extra_bad[2]
    return df


def _store(**kw) -> H.MemoryStore:
    d = str(DAY)
    rel = {"chains-2026": {}}
    if kw.get("bars") is not None:
        rel["chains-2026"][f"{d}_a_bars.parquet"] = _pq(kw["bars"])
    if kw.get("chains") is not None:
        rel["chains-2026"][f"{d}_a_chains.parquet"] = _pq(kw["chains"])
    if kw.get("tape") is not None:
        rel["chains-2026"][f"{d}_a_tape.parquet"] = _pq(kw["tape"])
    if kw.get("gift") is not None:
        rel["chains-2026"][f"{d}_a_gift.parquet"] = _pq(kw["gift"])
    if kw.get("optmin") is not None:
        rel["option-minutes-2026"] = {f"{d}_manifest.json": json.dumps(kw["optmin"]).encode()}
    if kw.get("stockmin") is not None:
        rel["stock-minutes-2026"] = {f"{d}_stocks_manifest.json": json.dumps(kw["stockmin"]).encode()}
    if kw.get("stockopt") is not None:
        rel.setdefault("option-minutes-2026", {})[f"{d}_stock_manifest.json"] = json.dumps(kw["stockopt"]).encode()
    if kw.get("evening") is not None:
        rel["evening-minutes-2026"] = {f"{EVE}_manifest.json": json.dumps(kw["evening"]).encode()}
    if kw.get("history") is not None:
        rel["daily-history"] = {f"{kw['history'].get('as_of', '2026-11-07')}_manifest.json": json.dumps(kw["history"]).encode()}
    if kw.get("fxmin") is not None:
        rel["fx-minutes-2026"] = {f"{EVE}_manifest.json": json.dumps(kw["fxmin"]).encode()}
    if kw.get("fxdaily") is not None:
        rel["fx-daily"] = {f"{kw['fxdaily'].get('as_of', '2026-11-07')}_manifest.json": json.dumps(kw["fxdaily"]).encode()}
    if kw.get("agreement") is not None:
        rel["agreement-2026"] = {f"{d}_agreement.json": json.dumps(kw["agreement"]).encode()}
    if kw.get("warehouse") is not None:
        rel["warehouse"] = {"manifest_2026.parquet": _pq(kw["warehouse"])}
    return H.MemoryStore(rel, kw.get("branches"), kw.get("kite"))


def _tape(n=1000, fail=0) -> pd.DataFrame:
    ok = np.array([True] * (n - fail) + [False] * fail)
    return pd.DataFrame({"ok": ok, "error": [None] * (n - fail) + ["Connection aborted"] * fail})


# ---- bars ----------------------------------------------------------------------------------------------------------------------------
def test_bars_complete_ok():
    c = H.check_bars(_store(bars=_bars()), DAY)
    assert c.status == H.OK and c.critical
    assert all(v["completeness"] == 1.0 for v in c.metrics["symbols"].values())


def test_bars_missing_file_is_missing():
    assert H.check_bars(_store(), DAY).status == H.MISSING


def test_bars_gap_warns_then_goes_bad():
    drop = [f"10:{m:02d}" for m in range(0, 15)]                 # 15 of 375 minutes = 96% -> below 98%, above 90%
    c = H.check_bars(_store(bars=_bars(drop=drop)), DAY)
    assert c.status == H.WARN and "96.0%" in c.detail and "longest gap 15" in c.detail
    drop = [f"{h}:{m:02d}" for h in (10, 11) for m in range(60)]                  # 120 missing -> 68%
    assert H.check_bars(_store(bars=_bars(drop=drop)), DAY).status == H.BAD


def test_bars_symbol_absent_is_bad():
    c = H.check_bars(_store(bars=_bars(symbols=("NIFTY", "BANKNIFTY", "INDIAVIX", "NIFTY-FUT"))), DAY)
    assert c.status == H.BAD and "BANKNIFTY-FUT: no bars" in c.detail


def test_flat_run_outside_closing_window_flagged_inside_ignored():
    mid = H.check_bars(_store(bars=_bars(flat_from=100, flat_len=15)), DAY)                  # 10:55 onward
    assert mid.status == H.WARN and "flat for" in mid.detail
    late = H.check_bars(_store(bars=_bars(flat_from=360, flat_len=15)), DAY)                 # 15:15 onward: the closing auction
    assert late.status == H.OK


def test_impossible_price_flagged():
    c = H.check_bars(_store(bars=_bars(bad_high=True)), DAY)
    assert c.status == H.WARN and "impossible price" in c.detail


def test_overlapping_jobs_that_agree_are_not_a_conflict_but_disagreement_is():
    b = _bars()
    two = pd.concat([b, b], ignore_index=True)
    assert H.check_bars(_store(bars=two), DAY).metrics["conflicts"] == 0
    b2 = b.copy()
    b2.loc[b2.index[10], "close"] += 1.0
    c = H.check_bars(_store(bars=pd.concat([b, b2], ignore_index=True)), DAY)
    assert c.metrics["conflicts"] == 1 and c.status == H.WARN


# ---- chains --------------------------------------------------------------------------------------------------------------------------
def test_chain_fault_mask_catches_each_kind_and_only_those():
    c = _chains(underlyings=("NIFTY",)).head(6).copy()
    c.loc[c.index[0], "ce_oi"] = -9.08e18                     # the real overflow
    c.loc[c.index[1], "pe_oi"] = 5e12
    c.loc[c.index[2], "ce_bid"] = 3.0                         # bid above ask
    c.loc[c.index[3], "spot"] = 0.0
    c.loc[c.index[4], "strike"] = -5.0
    assert H.chain_fault_mask(c).tolist() == [True, True, True, True, True, False]
    ok = c.loc[[c.index[5]]]
    assert not H.chain_fault_mask(ok).any()


def test_zero_oi_and_zero_ask_are_not_faults():
    c = _chains(underlyings=("NIFTY",)).head(2).copy()
    c["ce_oi"] = 0.0
    c["ce_bid"], c["ce_ask"] = 0.0, 0.0
    assert not H.chain_fault_mask(c).any()


def test_chains_clean_ok_and_corrupt_oi_quarantined():
    assert H.check_chains(_store(chains=_chains()), DAY).status == H.OK
    c = H.check_chains(_store(chains=_chains(extra_bad=("ce_oi", 3, -9.08e18))), DAY)
    assert c.status == H.WARN and c.metrics["quarantine_rows"] == 3 and "corrupt open interest" in c.detail


def test_chains_coverage_and_duplicates():
    c = H.check_chains(_store(chains=_chains(skip=("SENSEX",))), DAY)                         # SENSEX only half the minutes
    assert c.status == H.BAD and "SENSEX" in c.detail
    d = _chains()
    c = H.check_chains(_store(chains=pd.concat([d, d.head(4)], ignore_index=True)), DAY)
    assert c.metrics["duplicate_rows"] == 4 and c.status == H.WARN


def test_chains_missing_file():
    assert H.check_chains(_store(), DAY).status == H.MISSING


# ---- tape and the minute backfills -----------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("fail,status", [(0, H.OK), (30, H.OK), (80, H.WARN), (300, H.BAD)])
def test_tape_thresholds(fail, status):
    assert H.check_tape(_store(tape=_tape(1000, fail)), DAY).status == status


def test_option_minutes_ok_failed_and_stale():
    good = {"underlyings": {"NIFTY": {"asked": 100, "served": 100, "failed": 0, "last": f"{DAY} 15:29:00"}}}
    assert H.check_option_minutes(_store(optmin=good), DAY).status == H.OK
    bad = {"underlyings": {"NIFTY": {"asked": 100, "served": 60, "failed": 40, "last": f"{DAY} 15:29:00"}}}
    c = H.check_option_minutes(_store(optmin=bad), DAY)
    assert c.status == H.BAD and "40 contracts failed" in c.detail
    stale = {"underlyings": {"NIFTY": {"asked": 100, "served": 100, "failed": 0, "last": "2026-11-05 15:29:00"}}}
    c = H.check_option_minutes(_store(optmin=stale), DAY)
    assert c.status == H.WARN and "05 Nov" in c.detail
    assert H.check_option_minutes(_store(), DAY).status == H.MISSING


def test_stock_minutes():
    t = {"cash": {"asked": 50, "served": 50, "failed": 0, "not_attempted": 0}, "futures": {"asked": 50, "served": 50, "failed": 0, "not_attempted": 0}}
    assert H.check_stock_minutes(_store(stockmin={"totals": t, "universe": {"n": 50}}), DAY).status == H.OK
    t["futures"].update(served=30, failed=5, not_attempted=15)
    c = H.check_stock_minutes(_store(stockmin={"totals": t, "universe": {"n": 50}, "stopped": "budget"}), DAY)
    assert c.status == H.BAD and "futures" in c.detail and "stopped early" in c.detail


# ---- warehouse -------------------------------------------------------------------------------------------------------------------------
def _wh(last_by_table: dict[str, str], rows=100) -> pd.DataFrame:
    out = []
    for t, last in last_by_table.items():
        for d in pd.bdate_range(end=last, periods=25):
            out.append({"table": t, "date": d.date(), "status": "ok", "rows": rows})
    return pd.DataFrame(out)


def _cal():
    from quantdesk.markets import sessions as MK
    return MK.Calendars(None)


NOW_LATE = dt.datetime(2026, 11, 6, 22, 0, tzinfo=IST)
NOW_EARLY = dt.datetime(2026, 11, 6, 17, 0, tzinfo=IST)


def test_warehouse_current_lagging_and_stale():
    cur = {t: "2026-11-06" for t in H.CORE_WAREHOUSE_TABLES}
    assert H.check_warehouse(_store(warehouse=_wh(cur)), DAY, _cal(), NOW_LATE).status == H.OK
    one = {**cur, "fo_bhav": "2026-11-05"}
    c = H.check_warehouse(_store(warehouse=_wh(one)), DAY, _cal(), NOW_LATE)
    assert c.status == H.WARN and "one trading day behind" in c.detail
    stale = {**cur, "fo_bhav": "2026-11-03"}
    c = H.check_warehouse(_store(warehouse=_wh(stale)), DAY, _cal(), NOW_LATE)
    assert c.status == H.BAD and "3 trading days behind" in c.detail


def test_warehouse_before_evening_expects_yesterday():
    prev = {t: "2026-11-05" for t in H.CORE_WAREHOUSE_TABLES}
    assert H.check_warehouse(_store(warehouse=_wh(prev)), DAY, _cal(), NOW_EARLY).status == H.OK


def test_warehouse_table_missing_and_thin_file():
    cur = {t: "2026-11-06" for t in H.CORE_WAREHOUSE_TABLES[1:]}
    c = H.check_warehouse(_store(warehouse=_wh(cur)), DAY, _cal(), NOW_LATE)
    assert c.status == H.BAD and "fo_bhav: nothing fetched" in c.detail
    full = {t: "2026-11-06" for t in H.CORE_WAREHOUSE_TABLES}
    w = _wh(full)
    w.loc[(w["table"] == "fo_bhav") & (w["date"] == dt.date(2026, 11, 6)), "rows"] = 10
    c = H.check_warehouse(_store(warehouse=w), DAY, _cal(), NOW_LATE)
    assert c.status == H.WARN and "usual" in c.detail


def test_warehouse_no_manifest_for_year():
    assert H.check_warehouse(_store(), DAY, _cal(), NOW_LATE).status == H.MISSING


# ---- brief, kite -----------------------------------------------------------------------------------------------------------------------
def test_premarket_states():
    assert H.check_premarket(_store(), DAY).status == H.MISSING
    br = {"premarket": {"brief.json": json.dumps({"session": str(DAY), "generated_at": "2026-11-06T08:50:00+05:30"}).encode()}}
    assert H.check_premarket(_store(branches=br), DAY).status == H.OK
    old = {"premarket": {"brief.json": json.dumps({"session": "2026-11-05"}).encode()}}
    assert H.check_premarket(_store(branches=old), DAY).status == H.MISSING
    assert H.check_premarket(_store(branches={"premarket": {"brief.json": b"{nope"}}), DAY).status == H.BAD


def test_kite_states():
    assert H.check_kite(_store(kite=None), DAY).status == H.PENDING                 # API unreadable: not judged, never "fine"
    assert H.check_kite(_store(kite=[]), DAY).status == H.MISSING
    tiny = [{"name": "kite-raw-1", "size": 100, "expired": False}]
    assert H.check_kite(_store(kite=tiny), DAY).status == H.MISSING
    ok = [{"name": "kite-raw-1", "size": 5_000_000, "expired": False}]
    assert H.check_kite(_store(kite=ok), DAY).status == H.OK


# ---- the report ------------------------------------------------------------------------------------------------------------------------
def _full_store() -> H.MemoryStore:
    t = {"cash": {"asked": 5, "served": 5}, "futures": {"asked": 5, "served": 5}}
    return _store(bars=_bars(), chains=_chains(), tape=_tape(), optmin={"underlyings": {"NIFTY": {"asked": 5, "served": 5, "last": f"{DAY} 15:29"}}},
                  stockmin={"totals": t}, stockopt=_stockopt(), evening=_evening(), history={"as_of": "2026-11-05", "series": {"NIFTY": {}}, "unverified_series": []},
                  fxmin=_fxmin(), fxdaily={"as_of": "2026-11-05", "series": {"EURUSD": {}}, "unverified_series": []},
                  agreement={"day": str(DAY), "cycles": 4400, "pairs": 100000, "disagree": 500, "agree_pct": 99.5, "opt_agree_pct": 99.0, "worst_cycle_pct": 2.0, "partial": False}, warehouse=_wh({x: "2026-11-06" for x in H.CORE_WAREHOUSE_TABLES}),
                  gift=pd.DataFrame({"ts": pd.date_range(dt.datetime.combine(DAY, dt.time(8, 30), tzinfo=IST), periods=5, freq="10min")}),
                  branches={"premarket": {"brief.json": json.dumps({"session": str(DAY)}).encode()}}, kite=[{"name": "kite-raw", "size": 9e6, "expired": False}])


def test_report_all_good_after_evening():
    r = H.build_report(_full_store(), None, DAY, NOW_LATE)
    assert [c.status for c in r.checks] == [H.OK] * len(r.checks) and not r.failed()
    assert json.loads(json.dumps(r.to_dict()))["failed"] is False
    assert "| session bars * |" in r.markdown()


def test_report_before_due_is_pending_not_missing():
    r = H.build_report(H.MemoryStore(), None, DAY, dt.datetime(2026, 11, 6, 7, 0, tzinfo=IST))
    by = {c.channel: c.status for c in r.checks}
    assert by["session bars"] == by["option chains"] == by["GIFT Nifty pre-open"] == H.PENDING
    assert by["NSE warehouse"] == H.MISSING                                       # its table is not "due" at a time: yesterday's must already exist
    assert r.failed()


def test_report_critical_missing_after_close_fails_but_noncritical_alone_does_not():
    r = H.build_report(H.MemoryStore(), None, DAY, NOW_LATE)
    assert r.failed()
    full = _full_store()
    full.branches = {}                                                           # premarket (non-critical) vanishes
    full.releases["chains-2026"].pop(f"{DAY}_a_tape.parquet")                    # so does the tape
    r = H.build_report(full, None, DAY, NOW_LATE)
    assert {c.channel: c.status for c in r.checks}["pre-market brief"] == H.MISSING
    assert not r.failed()


def test_weekend_and_holiday_have_nothing_due():
    sat = dt.date(2026, 11, 7)
    r = H.build_report(H.MemoryStore(), None, sat, dt.datetime(2026, 11, 7, 20, 0, tzinfo=IST))
    assert len(r.checks) == 1 and not r.failed() and "not an NSE trading day" in r.checks[0].detail


def test_a_check_that_crashes_is_reported_and_critical_crash_fails():
    class Boom(H.MemoryStore):
        def tags(self, prefix):
            raise ConnectionError("down")
    r = H.build_report(Boom(), None, DAY, NOW_LATE)
    by = {c.channel: c for c in r.checks}
    assert by["session bars"].status == H.BAD and "could not run" in by["session bars"].detail and r.failed()
    assert by["fetch tape"].status == H.WARN                                      # non-critical: shown, not fatal


def test_cli_exit_code_and_json(monkeypatch, capsys):
    from quantdesk.data import cli as C
    monkeypatch.setattr(H, "GitHubStore", lambda *a, **k: H.MemoryStore())
    args = type("A", (), {"repo": "x/y", "day": "2026-11-07", "json": True, "summary": False})()
    C.cmd_health(None, args)                                                      # a Saturday: nothing due, exit 0
    assert json.loads(capsys.readouterr().out)["failed"] is False
    args.day = "2026-11-06"
    monkeypatch.setattr(H.dt, "datetime", type("D", (dt.datetime,), {"now": classmethod(lambda cls, tz=None: NOW_LATE)}))
    with pytest.raises(SystemExit) as e:
        C.cmd_health(None, args)
    assert e.value.code == 1


def test_health_module_is_read_only_and_holds_no_secret():
    import re
    src = open(H.__file__, encoding="utf-8").read()
    for bad in (r"os\.environ", r"(?<![\w.])open\(", r"\.write\(", r"\.write_text\(", r"subprocess", r"KITE_API", r"password", r"totp", r"POST", r"method\s*="):
        assert not re.search(bad, src, re.I if bad in ("password", "totp") else 0), bad


# ---- review follow-ups (CodeRabbit on #204) ---------------------------------------------------------------------------------------------------
def test_a_missing_minute_ends_a_flat_run():
    b = _bars(symbols=("NIFTY",), flat_from=100, flat_len=12)
    b = b[b["ts"].dt.strftime("%H:%M") != "11:00"]                               # a gap in the middle of the flat stretch: two runs of 5 and 6
    assert H._flat_runs(_as_minutes(b)) == []
    assert H._flat_runs(_as_minutes(_bars(symbols=("NIFTY",), flat_from=100, flat_len=12)))          # the same stretch with no gap is flagged


def _as_minutes(b: pd.DataFrame) -> pd.DataFrame:
    b = b.copy()
    b["min"] = b["ts"].dt.floor("min")
    return b


def test_empty_tape_and_empty_option_manifest_are_not_ok():
    assert H.check_tape(_store(tape=_tape(0, 0)), DAY).status == H.MISSING
    assert H.check_option_minutes(_store(optmin={"underlyings": {}}), DAY).status == H.BAD


def test_past_day_brief_and_kite_are_not_judged_when_they_cannot_be():
    today = dt.date(2026, 11, 12)
    newer = {"premarket": {"brief.json": json.dumps({"session": "2026-11-12"}).encode()}}
    assert H.check_premarket(_store(branches=newer), DAY, today).status == H.PENDING
    assert H.check_premarket(_store(branches=newer), DAY).status == H.MISSING                          # no `today` given: judged as before
    assert H.check_premarket(_store(branches=newer), dt.date(2026, 11, 12), today).status == H.OK
    assert H.check_kite(_store(kite=[]), DAY, today).status == H.PENDING
    assert H.check_kite(_store(kite=[]), dt.date(2026, 11, 11), today).status == H.MISSING


def test_retry_delay_honours_retry_after_and_rate_limit_reset(monkeypatch):
    monkeypatch.setattr(H.time, "time", lambda: 1000.0)
    assert H.retry_delay(429, {"Retry-After": "7"}, 0) == 7.0
    assert H.retry_delay(403, {"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "1030"}, 0) == 30.0
    assert H.retry_delay(403, {"Retry-After": "900"}, 0) == 60.0                                         # capped
    assert H.retry_delay(500, None, 0) == 2.0 and H.retry_delay(0, None, 1) == 4.0
    assert H.retry_delay(403, {"Retry-After": "soon"}, 0) == 2.0                                        # garbage header: the plain pause


# ---- stock option minutes, MCX/currency minutes, daily history ---------------------------------------------------------------------------------
def _stockopt(**over) -> dict:
    st = {"RELIANCE": {"asked": 44, "served": 44, "failed": 0, "last": f"{DAY} 15:39:00+05:30"}, "TCS": {"asked": 44, "served": 44, "failed": 0, "last": f"{DAY} 15:39:00+05:30"}}
    st.update(over)
    return {"stocks": st}


def _evening(mcx=(40, 40), cds=(6, 6), **over) -> dict:
    m = {"segments": {"mcx": {"names": {}}, "cds": {"names": {}}}, "totals": {"mcx": {"asked": mcx[0], "served": mcx[1], "failed": mcx[0] - mcx[1]},
                                                                                "cds": {"asked": cds[0], "served": cds[1], "failed": cds[0] - cds[1]}}, "stopped": None}
    m.update(over)
    return m


def test_stock_option_minutes_ok_short_stale_and_missing():
    assert H.check_stock_option_minutes(_store(stockopt=_stockopt()), DAY).status == H.OK
    c = H.check_stock_option_minutes(_store(stockopt=_stockopt(TCS={"asked": 44, "served": 30, "failed": 14, "last": f"{DAY} 15:39"})), DAY)
    assert c.status == H.BAD and "TCS: 30 of 44" in c.detail and c.metrics["worst_served_ratio"] < 0.9
    c = H.check_stock_option_minutes(_store(stockopt=_stockopt(TCS={"asked": 44, "served": 43, "failed": 1, "last": f"{DAY} 15:39"})), DAY)
    assert c.status == H.WARN
    stale = _stockopt(TCS={"asked": 44, "served": 44, "failed": 0, "last": "2026-11-05 15:39"})
    assert "newest bar is from 05 Nov" in H.check_stock_option_minutes(_store(stockopt=stale), DAY).detail
    assert H.check_stock_option_minutes(_store(stockopt={"stocks": {}}), DAY).status == H.BAD
    assert H.check_stock_option_minutes(_store(), DAY).status == H.MISSING


def test_evening_minutes_are_judged_for_the_previous_weekday_and_say_which_segment_fell_short():
    assert H.check_evening_minutes(_store(evening=_evening()), DAY).status == H.OK                      # Fri: judged on Thu's manifest
    c = H.check_evening_minutes(_store(evening=_evening(mcx=(40, 20))), DAY)
    assert c.status == H.BAD and "mcx: 20 of 40" in c.detail
    assert H.check_evening_minutes(_store(evening=_evening(mcx=(40, 39))), DAY).status == H.WARN
    err = _evening()
    err["segments"]["cds"] = {"error": "scrip master: HTTP 404"}
    c = H.check_evening_minutes(_store(evening=err), DAY)
    assert c.status == H.BAD and "cds: scrip master" in c.detail
    assert H.check_evening_minutes(_store(evening=_evening(stopped="time budget")), DAY).status == H.WARN
    assert H.check_evening_minutes(_store(evening={"segments": {}, "totals": {}}), DAY).status == H.BAD
    assert H.check_evening_minutes(_store(), DAY).status == H.MISSING
    mon = dt.date(2026, 11, 9)                                                                           # a Monday looks back over the weekend to Friday's evening
    s = _store(evening=_evening())
    s.releases["evening-minutes-2026"] = {"2026-11-06_manifest.json": json.dumps(_evening()).encode()}
    assert H.check_evening_minutes(s, mon).status == H.OK


def test_daily_history_missing_old_and_partly_unverified():
    assert H.check_daily_history(_store(), DAY).status == H.MISSING
    ok = {"as_of": "2026-11-05", "series": {"A": {}, "B": {}}, "unverified_series": []}
    assert H.check_daily_history(_store(history=ok), DAY).status == H.OK
    c = H.check_daily_history(_store(history={**ok, "unverified_series": ["B", "SENSEX"]}), DAY)
    assert c.status == H.WARN and "2 of 2 series are not verified" in c.detail and c.metrics["unverified"] == 2
    c = H.check_daily_history(_store(history={**ok, "as_of": "2026-09-01"}), DAY)
    assert c.status == H.WARN and "66 days old" in c.detail


def test_the_report_lists_the_new_channels_and_they_never_fail_the_run_alone():
    full = _full_store()
    names = [c.channel for c in H.build_report(full, None, DAY, NOW_LATE).checks]
    assert {"stock option minutes", "MCX/currency minutes", "daily history"} <= set(names)
    bare = _full_store()
    bare.releases.pop("evening-minutes-2026"); bare.releases.pop("daily-history"); bare.releases["option-minutes-2026"].pop(f"{DAY}_stock_manifest.json")
    r = H.build_report(bare, None, DAY, NOW_LATE)
    by = {c.channel: c.status for c in r.checks}
    assert by["stock option minutes"] == by["MCX/currency minutes"] == by["daily history"] == H.MISSING and not r.failed()      # non-critical: shown, never red on its own
    early = H.build_report(H.MemoryStore(), None, DAY, dt.datetime(2026, 11, 6, 6, 0, tzinfo=IST))
    assert {c.channel: c.status for c in early.checks}["MCX/currency minutes"] == H.PENDING             # before 07:00 the previous evening is not yet judged


# ---- FX ---------------------------------------------------------------------------------------------------------------------------------------
def _fxmin(**over) -> dict:
    pairs = {s: {"status": "served", "rows": 6000, "last": f"{EVE} 22:29:00+00:00"} for s in ("EURUSD", "USDINR")}
    pairs.update(over)
    return {"pairs": pairs}


def test_fx_minutes_ok_failed_thin_stale_and_missing():
    assert H.check_fx_minutes(_store(fxmin=_fxmin()), DAY).status == H.OK                         # Fri: judged on Thu's manifest
    c = H.check_fx_minutes(_store(fxmin=_fxmin(USDINR={"status": "failed", "error": "yahoo down"})), DAY)
    assert c.status == H.BAD and "USDINR: failed" in c.detail                                      # half the pairs: below 90%
    many = {f"P{i}": {"status": "served", "rows": 6000, "last": f"{EVE} 22:29:00+00:00"} for i in range(20)}
    c = H.check_fx_minutes(_store(fxmin={"pairs": {**many, "X": {"status": "failed"}}}), DAY)
    assert c.status == H.WARN and "X: failed" in c.detail                                          # one of 21: noted, not red
    assert "only 120 bars" in H.check_fx_minutes(_store(fxmin=_fxmin(EURUSD={"status": "served", "rows": 120, "last": f"{EVE} 22:29:00+00:00"})), DAY).detail
    stale = _fxmin(EURUSD={"status": "served", "rows": 6000, "last": "2026-11-03 22:29:00+00:00"})
    assert "newest bar is from 03 Nov" in H.check_fx_minutes(_store(fxmin=stale), DAY).detail
    assert H.check_fx_minutes(_store(fxmin={"pairs": {}}), DAY).status == H.BAD
    assert H.check_fx_minutes(_store(), DAY).status == H.MISSING


def test_fx_daily_history_is_judged_like_the_equity_history_on_its_own_release():
    assert H.check_fx_daily(_store(), DAY).status == H.MISSING and "fx-daily" in H.check_fx_daily(_store(), DAY).detail
    ok = {"as_of": "2026-11-05", "series": {"A": {}, "B": {}}, "unverified_series": []}
    assert H.check_fx_daily(_store(fxdaily=ok), DAY).status == H.OK and H.check_fx_daily(_store(fxdaily=ok), DAY).channel == "FX daily history"
    assert H.check_fx_daily(_store(fxdaily={**ok, "unverified_series": ["DXY"]}), DAY).status == H.WARN
    assert H.check_daily_history(_store(), DAY).channel == "daily history"                          # the default is unchanged
