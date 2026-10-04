"""Expiry sellers (intraday/sleeves.py): the pre-registered paper sleeves open on an expiry's eve from a real-quote
snapshot, settle at the recorded closing half hour, never act twice, refuse modelled quotes, and retire by the spec."""
import datetime as dt
import json

import pandas as pd
import pytest

from quantdesk.core.calendar import TradingCalendar
from quantdesk.intraday.chains import ModelOptionChain
from quantdesk.intraday.recorder import SessionRecorder
from quantdesk.intraday.sleeves import ExpirySeller, assess, entry_snapshot, fill_quality, load_spec, payoff, render

IST = "Asia/Kolkata"
SPOT = 22600.0


def eve(cfg):
    """A Monday whose next trading day is a NIFTY weekly expiry and not BANKNIFTY's monthly one."""
    cal = TradingCalendar(cfg.holidays())
    for d in pd.date_range("2026-06-01", "2026-12-31"):
        d = d.date()
        if d.weekday() != 0 or not cal.is_trading_day(d):
            continue
        e = cal.next_trading_day(d)
        if e in cal.expiries(d, 40, 1, True) and e not in cal.expiries(d, 40, 1, False):
            return cal, d, e
    raise AssertionError("no eve found")


def snapshot(cfg, cal, data, day, expiry, hhmm, source="kotak", spot=SPOT):
    mc = ModelOptionChain(cfg, cal, lambda u, t: (spot, 0.14))
    ts = pd.Timestamp(f"{day} {hhmm[:2]}:{hhmm[2:]}", tz=IST)
    ch = mc.chain("NIFTY", expiry, ts=ts)
    ch.attrs["source"] = source
    SessionRecorder(data).record_chain(ch)
    return ch


def closing_bars(data, day, close):
    idx = pd.date_range(f"{day} 09:15", f"{day} 15:29", freq="1min", tz=IST)
    df = pd.DataFrame({"open": close, "high": close + 5, "low": close - 5, "close": close, "volume": 0.0}, index=idx)
    SessionRecorder(data).record_bars("NIFTY", df)


def at(day, hhmm):
    return pd.Timestamp(f"{day} {hhmm}", tz=IST)


@pytest.fixture
def setup(cfg, tmp_path):
    cal, d, e = eve(cfg)
    data = tmp_path / "data"
    seller = ExpirySeller(cfg, tmp_path / "sleeves", data, say=lambda *a: None)
    return seller, cal, data, d, e


def test_opens_on_the_eve_from_real_quotes_and_settles_at_expiry(cfg, setup):
    seller, cal, data, d, e = setup
    for hhmm in ("1505", "1520", "1524"):                       # 15:05 is outside the window; 15:20 is nearest
        ch = snapshot(cfg, cal, data, d, e, hhmm)
        if hhmm == "1520":
            chosen = ch
    assert entry_snapshot(data / str(d), "NIFTY", e).name == f"NIFTY_{e}_1520.csv"
    assert seller.run(d, now=at(d, "15:00")) == []              # before 15:26 nothing opens
    notes = seller.run(d, now=at(d, "15:40"))
    opened = {t["sleeve"]: t for t in seller.trades()}
    assert set(opened) == {"A", "B"} and all("opened" in n for n in notes)
    a, b = opened["A"], opened["B"]
    assert len(a["legs"]) == 4 and len(b["legs"]) == 2 and a["snapshot"].endswith("_1520.csv") and a["source"] == "kotak"
    for leg in a["legs"]:
        side = "ce" if leg["right"] == "CE" else "pe"
        bid, ask = chosen.at[leg["strike"], f"{side}_bid"], chosen.at[leg["strike"], f"{side}_ask"]
        assert leg["fill"] == pytest.approx(bid - 0.05 if leg["qty"] < 0 else ask + 0.05)
        assert abs(abs(leg["delta"]) - abs(leg["target"])) <= 0.08
        assert (leg["strike"] > SPOT) if leg["right"] == "CE" else (leg["strike"] < SPOT)
        assert leg["fees_rs"] > 0
    assert a["credit_pts"] > 0 and a["max_loss_rs"] > 0 and b["max_loss_rs"] is None and b["margin_est_rs"] > 0
    assert a["cost_gap_rs"] == pytest.approx((a["credit_pts"] - a["model_credit_pts"]) * 65, abs=1)
    seller.run(d, now=at(d, "16:00"))                            # re-run: nothing opens twice
    assert sum(ev["event"] == "open" for ev in seller.events()) == 2

    closing_bars(data, e, SPOT)                                   # the index pins: every leg expires worthless
    assert seller.run(e, now=at(e, "15:20")) == []               # before 15:31 nothing expiring today settles
    notes = seller.run(e, now=at(e, "15:45"))
    done = {t["sleeve"]: t for t in seller.trades()}
    assert all(t["settled"] for t in done.values()) and sum("settled" in n for n in notes) == 2
    for t in done.values():
        assert t["settle"] == pytest.approx(SPOT) and "15:00–15:29" in t["settle_source"]
        assert t["pnl_rs"] == pytest.approx(t["credit_pts"] * 65 - t["entry_fees_rs"], abs=0.05)
    seller.run(e, now=at(e, "16:00"))
    assert sum(ev["event"] == "settle" for ev in seller.events()) == 2
    assert "A NIFTY | 1 |" in render(seller.report())


def test_every_fill_says_how_real_it_was(cfg, setup):
    """Each leg records its spread and the size resting where it would fill; a thin touch or a snapshot far from 15:20 is
    flagged, and the report compares real fills with the history's cost model."""
    seller, cal, data, d, e = setup
    mc = ModelOptionChain(cfg, cal, lambda u, t: (SPOT, 0.14))
    ch = mc.chain("NIFTY", e, ts=pd.Timestamp(f"{d} 15:10", tz=IST))
    ch.attrs["source"] = "kotak"
    ch["ce_bidq"], ch["ce_askq"], ch["pe_bidq"], ch["pe_askq"] = 10.0, 1e5, 1e5, 1e5   # 10 units bid for the calls
    SessionRecorder(data).record_chain(ch)
    seller.run(d, now=at(d, "15:40"))
    opened = {t["sleeve"]: t for t in seller.trades()}
    a = opened["A"]
    assert a["snapshot_off_min"] == 10 and "late" in a["quote_flags"] and "thin" in a["quote_flags"]
    for leg in a["legs"]:
        mid = (leg["bid"] + leg["ask"]) / 2
        assert leg["spread_pct"] == pytest.approx((leg["ask"] - leg["bid"]) / mid, abs=1e-4)
        sold_call = leg["right"] == "CE" and leg["qty"] < 0
        assert ("thin" in leg["flags"]) == sold_call                # selling hits the 10-unit bid; 65 a lot
        assert leg["touch_qty"] == (10.0 if sold_call else 1e5)
    fq = seller.report()["fills"]["NIFTY"]
    assert fq["trades"] == 2 and fq["legs"] == 6 and fq["flags"]["thin"] == 2 and fq["flags"]["late"] == 2
    assert fq["real_vs_model"] > 0 and fq["median_spread_pct"] > 0
    assert "Fill quality" in render(seller.report())
    skips = fill_quality([{"event": "skip", "underlying": "SENSEX", "reason": "CE 81200: no two-sided quote"},
                          {"event": "skip", "underlying": "SENSEX", "reason": "CE 81300: no two-sided quote"}])
    assert skips["SENSEX"]["skips"] == {"CE #: no two-sided quote": 2} and skips["SENSEX"]["legs"] == 0


def test_each_settlement_is_checked_against_the_official_close(cfg, setup):
    """The registered settlement (the 15:00–15:29 mean) stays the result; an `official` event adds the P&L at the
    official close and the gap, once, from 15:45. NSE's published close wins over the 15:29 bar, which wins over Yahoo."""
    seller, cal, data, d, e = setup
    snapshot(cfg, cal, data, d, e, "1520")
    seller.run(d, now=at(d, "15:40"))
    idx = pd.date_range(f"{e} 09:15", f"{e} 15:29", freq="1min", tz=IST)
    close = pd.Series(SPOT, index=idx)
    close.iloc[-1] = SPOT + 600                                  # a late surge: the last bar is the official close
    SessionRecorder(data).record_bars("NIFTY", pd.DataFrame({"open": close, "high": close, "low": close, "close": close,
                                                              "volume": 0.0}, index=idx))
    seller.run(e, now=at(e, "15:35"))                            # settles; too early for the check
    assert not any(ev["event"] == "official" for ev in seller.events())
    seller.run(e, now=at(e, "15:50"))                            # expiry day: NSE's file or nothing; not out yet
    assert not any(ev["event"] == "official" for ev in seller.events())
    nxt = cal.next_trading_day(e)
    notes = seller.check_settlement(nxt, at(nxt, "16:00"))       # the next run falls back to the 15:29 bar
    assert sum("settlement check" in n for n in notes) == 2
    for t in seller.trades():
        assert t["settle"] == pytest.approx(SPOT + 600 / 30, abs=0.01)          # registered: unchanged
        assert t["official"] == SPOT + 600 and t["official_source"] == "the 15:29 one-minute close"
        assert t["settle_gap_bps"] == pytest.approx(((SPOT + 20) / (SPOT + 600) - 1) * 1e4, abs=0.01)
        assert t["pnl_rs_official"] == pytest.approx(payoff(t, SPOT + 600)["pnl_rs"], abs=0.01)
        assert t["pnl_gap_rs"] == pytest.approx(t["pnl_rs"] - t["pnl_rs_official"], abs=0.02)
    seller.check_settlement(nxt, at(nxt, "17:00"))
    assert sum(ev["event"] == "official" for ev in seller.events()) == 2       # once per trade
    rep = seller.report()
    st = rep["settlement"]["NIFTY"]
    assert st["days"] == 1 and st["trades"] == 2 and st["max_abs_gap_bps"] == pytest.approx(250, abs=0.01)
    assert all(r["eves_due"] == 1 and r["skip_rate"] == 0 for r in rep["rows"] if r["underlying"] == "NIFTY")
    md = render(rep)
    assert "Settlement check" in md and "Skip rate" in md

    seller.official_fn = lambda u, day: SPOT + 300
    assert seller.official("NIFTY", e) == (SPOT + 300, "NSE's official close")
    assert seller.official("NIFTY", e, nse_only=True) == (SPOT + 300, "NSE's official close")
    seller.official_fn = lambda u, day: None
    assert seller.official("NIFTY", e) == (SPOT + 600, "the 15:29 one-minute close")
    assert seller.official("NIFTY", e, nse_only=True)[0] is None
    seller.close_fn = lambda u, day: SPOT + 1
    assert seller.official("NIFTY", d) == (SPOT + 1, "Yahoo daily close")       # no 15:29 bar on the eve


def test_a_breakout_costs_the_condor_its_width_and_exercise_stt(cfg, setup):
    seller, cal, data, d, e = setup
    snapshot(cfg, cal, data, d, e, "1520")
    seller.run(d, now=at(d, "15:40"))
    closing_bars(data, e, SPOT + 900)                             # through both call strikes
    seller.run(e, now=at(e, "15:45"))
    a = next(t for t in seller.trades() if t["sleeve"] == "A")
    calls = sorted(x["strike"] for x in a["legs"] if x["right"] == "CE")
    stt = 0.00125 * (SPOT + 900 - calls[1]) * 65
    assert a["stt_rs"] == pytest.approx(stt, abs=0.05)
    assert a["pnl_rs"] == pytest.approx((a["credit_pts"] - (calls[1] - calls[0])) * 65 - a["entry_fees_rs"] - stt, abs=0.1)
    assert seller.assessment("A", "NIFTY")["bugs"] == []           # exercise STT is not a breach of the max loss


def test_modelled_or_missing_quotes_are_skipped_on_the_record(cfg, setup, tmp_path):
    seller, cal, data, d, e = setup
    snapshot(cfg, cal, data, d, e, "1520", source="model")
    seller.run(d, now=at(d, "15:40"))
    skips = [ev for ev in seller.events() if ev["event"] == "skip"]
    assert {s["sleeve"] for s in skips} == {"A", "B"} and all("modelled chain" in s["reason"] for s in skips)
    assert not seller.trades()
    other = ExpirySeller(cfg, tmp_path / "other", tmp_path / "empty", say=lambda *a: None)
    other.run(d, now=at(d, "15:40"))
    reasons = [ev["reason"] for ev in other.events()]
    assert len(reasons) == 2 and all("no real-quote snapshot" in r for r in reasons)
    other.run(d, now=at(d, "16:10"))
    assert len(other.events()) == 2                               # a skip is logged once


def test_rules_retire_and_qualify_as_registered():
    hist = load_spec()["history"]["per_lot_rupees"]

    def trades(pnls, gaps):
        return [{"id": f"t{i}", "pnl_rs": p, "cost_gap_rs": g, "max_loss_rs": 6000.0} for i, (p, g) in enumerate(zip(pnls, gaps))]
    ok = assess(trades([300, -200, 500, 100, 250, -100, 400, 50, 150, 200], [-20, 10, -5, 0, 15, -10, 5, 0, -15, 20]), hist["A_NIFTY"], False)
    assert ok["cost"] == "passed" and ok["consistency"] == "consistent" and ok["eligible"] and not ok["retired"]
    pricey = assess(trades([100] * 6, [-400, -350, -500, -450, -380, -420]), hist["A_NIFTY"], False)
    assert pricey["cost"] == "failed" and "cost more than the edge" in pricey["retired"]
    broken = assess(trades([-3000] * 8, [0] * 8), hist["A_NIFTY"], False)
    assert broken["consistency"] == "rejected" and broken["z"] < -1.645 and broken["retired"]
    tail = assess(trades([2000, -70000], [0, 0]), hist["B_NIFTY"], True)
    assert tail["tail"] == "breached" and tail["retired"] and not tail["eligible"]
    bug = assess([{"id": "x", "pnl_rs": -9000.0, "cost_gap_rs": 0, "max_loss_rs": 6000.0, "stt_rs": 10.0}], hist["A_NIFTY"], False)
    assert bug["bugs"]


def test_a_retired_sleeve_stops_opening(cfg, setup):
    seller, cal, data, d, e = setup
    seller.root.mkdir(parents=True)
    with seller.ledger.open("w") as f:
        for i in range(6):
            tid = f"A-NIFTY-old{i}"
            f.write(json.dumps({"event": "open", "id": tid, "sleeve": "A", "underlying": "NIFTY", "expiry": "2026-01-06",
                                "lot": 65, "legs": [], "cost_gap_rs": -900.0 - i, "max_loss_rs": 6000.0}) + "\n")
            f.write(json.dumps({"event": "settle", "id": tid, "pnl_rs": 50.0}) + "\n")
    snapshot(cfg, cal, data, d, e, "1520")
    seller.run(d, now=at(d, "15:40"))
    new = [ev for ev in seller.events() if ev.get("expiry") == str(e)]
    assert {(ev["event"], ev["sleeve"]) for ev in new} == {("skip", "A"), ("open", "B")}
    assert "retired under the spec" in next(ev["reason"] for ev in new if ev["event"] == "skip")


def test_an_eve_without_a_run_is_recorded_not_dropped(cfg, tmp_path):
    cal = TradingCalendar(cfg.holidays())
    reg = dt.date.fromisoformat(load_spec()["registered"])
    d = next(x.date() for x in pd.date_range(reg, periods=60) if x.weekday() == 0 and cal.is_trading_day(x.date())
             and cal.next_trading_day(x.date()) in cal.expiries(x.date(), 40, 1, True))
    seller = ExpirySeller(cfg, tmp_path / "sleeves", tmp_path / "data", say=lambda *a: None)
    later = cal.next_trading_day(cal.next_trading_day(d))
    seller.run(later, now=at(later, "15:40"))
    missed = [ev for ev in seller.events() if ev["day"] == str(d)]
    assert {ev["sleeve"] for ev in missed if ev["underlying"] == "NIFTY"} == {"A", "B"}
    assert all("did not run on the eve" in ev["reason"] for ev in missed)
    n = len(seller.events())
    seller.run(later, now=at(later, "16:00"))
    assert len(seller.events()) == n


def test_specs_drive_the_sleeves_and_v2_trades_only_its_far_wing_condor(cfg, tmp_path):
    from quantdesk.intraday.sleeves import specs
    names = [s["name"] for s in specs()]
    assert names[:2] == ["expiry_seller_v1", "expiry_seller_v2"]
    v2 = next(s for s in specs() if s["name"] == "expiry_seller_v2")
    cal = TradingCalendar(cfg.holidays())
    d = next(x.date() for x in pd.date_range("2026-06-01", "2026-12-31") if cal.is_trading_day(x.date())
             and cal.next_trading_day(x.date()) in cal.expiries(x.date(), 40, 1, False))   # a BANKNIFTY monthly eve
    e = cal.next_trading_day(d)
    data = tmp_path / "data"
    mc = ModelOptionChain(cfg, cal, lambda u, t: (54000.0, 0.16))
    for u in ("NIFTY", "BANKNIFTY"):
        ch = mc.chain(u, e, spot=22600.0 if u == "NIFTY" else 54000.0, ts=at(d, "15:20"))
        ch.attrs["source"] = "kotak"
        SessionRecorder(data).record_chain(ch)
    seller = ExpirySeller(cfg, tmp_path / "sleeves", data, spec=v2, say=lambda *a: None)
    assert seller.ledger.name == "expiry_seller_v2.jsonl"
    seller.run(d, now=at(d, "15:40"))
    trades = seller.trades()
    assert [(t["sleeve"], t["underlying"]) for t in trades] == [("C", "BANKNIFTY")]    # never NIFTY
    legs = sorted(trades[0]["legs"], key=lambda x: (x["right"], x["strike"]))
    wings = [x for x in legs if x["qty"] > 0]
    assert len(legs) == 4 and all(abs(abs(x["delta"]) - 0.05) <= 0.08 for x in wings)
    assert trades[0]["max_loss_rs"] > 0 and trades[0]["margin_est_rs"] == trades[0]["max_loss_rs"]
    assert "C = iron_condor_20_05 (defined risk)" in render(seller.report())


def test_settlement_from_the_tape_when_no_bars_are_recorded(tmp_path):
    from quantdesk.intraday.sleeves import settlement_price
    day = dt.date(2026, 10, 27)
    d = tmp_path / str(day)
    d.mkdir(parents=True)
    rows = []
    for m in range(0, 31):                                        # 15:00–15:30, two series of the same index
        ts = pd.Timestamp(f"{day} 15:00") + pd.Timedelta(minutes=m)
        for e in ("2026-10-27", "2026-11-24"):
            rows.append({"ts": f"{ts:%Y-%m-%d %H:%M:%S}+05:30", "underlying": "FINNIFTY", "expiry": e, "ok": True,
                         "strikes": 41, "quoted": 80, "spot": 24000.0 + m, "secs": 1.0, "error": ""})
    rows.append({"ts": f"{day} 15:10:00+05:30", "underlying": "SENSEX", "expiry": "2026-10-29", "ok": True, "strikes": 41,
                 "quoted": 80, "spot": 72000.0, "secs": 1.0, "error": ""})
    pd.DataFrame(rows).to_csv(d / "tape.csv", index=False)
    s, src = settlement_price(tmp_path, "FINNIFTY", day)
    assert s == pytest.approx(24014.5) and "30 tape index spots" in src       # 15:30 itself is outside the window
    s2, src2 = settlement_price(tmp_path, "SENSEX", day)
    assert s2 is None and "tape has 1" in src2
