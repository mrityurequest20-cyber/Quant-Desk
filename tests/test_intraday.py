"""Intraday desk: order flow, chains, features (no look-ahead), analyst, sizing, execution,
and a full synthetic session through the engine."""
import datetime as dt
import json

import numpy as np
import pandas as pd
import pytest

from quantdesk.core.calendar import TradingCalendar
from quantdesk.intraday.chains import (COLUMNS, IntradayPricer, ModelOptionChain, NSEOptionChain, chain_analytics,
                                       fill_iv, time_to_expiry)
from quantdesk.intraday.engine import IntradayEngine, run_replay
from quantdesk.intraday.features import session_state
from quantdesk.intraday.feeds import IST, ReplayFeed
from quantdesk.intraday.orderflow import (FootprintBuilder, TickClassifier, Trade, approx_delta, profile_from_bars,
                                          profile_from_trades)
from quantdesk.intraday.recorder import SessionRecorder
from quantdesk.intraday.sim import IntradayBroker, QuoteMarker
from quantdesk.intraday.synthetic import simulate_sessions
from quantdesk.journal.journal import Journal


@pytest.fixture(scope="module")
def sessions():
    from quantdesk.config import DEFAULT_CONFIG, Config
    cal = TradingCalendar(Config.load(DEFAULT_CONFIG).holidays())
    days = [d.date() for d in cal.trading_days("2026-08-17", "2026-09-28")]
    bars, meta = simulate_sessions(days, seed=5)
    return bars, meta, days


def ts(s):
    return pd.Timestamp(s, tz=IST)


# ---- order flow -------------------------------------------------------------------------------------
def test_value_area_from_known_distribution():
    t = [Trade(ts("2026-09-28 10:00"), p, v) for p, v in [(100, 5), (101, 10), (102, 40), (103, 12), (104, 3), (105, 1)]]
    prof = profile_from_trades(t, tick=1.0)
    assert prof.poc == 102 and not prof.approximate
    covered = prof.volume[(prof.prices >= prof.val) & (prof.prices <= prof.vah)].sum()
    assert covered / prof.volume.sum() >= 0.70 and prof.val <= 102 <= prof.vah
    assert prof.position(106) == "above value" and prof.position(99) == "below value"


def test_profile_from_bars_conserves_volume():
    idx = pd.date_range(ts("2026-09-28 09:15"), periods=3, freq="min")
    df = pd.DataFrame({"open": [100, 101, 102], "high": [101, 103, 104], "low": [99, 100, 101], "close": [101, 102, 103],
                       "volume": [300.0, 500.0, 200.0]}, index=idx)
    prof = profile_from_bars(df, tick=0.5)
    assert prof.volume.sum() == pytest.approx(1000.0) and prof.approximate
    assert (approx_delta(df) > 0).all()                     # all bars closed near their highs


def test_an_index_without_volume_gets_a_time_at_price_profile():
    idx = pd.date_range(ts("2026-09-28 09:15"), periods=60, freq="min")
    px = np.r_[np.full(40, 100.0), np.linspace(100, 110, 20)]             # 40 minutes around 100, then a run to 110
    df = pd.DataFrame({"open": px, "high": px + 0.5, "low": px - 0.5, "close": px, "volume": 0.0}, index=idx)
    prof = profile_from_bars(df, tick=0.5)
    assert prof.kind == "tpo" and abs(prof.poc - 100) <= 1 and prof.val <= 100 <= prof.vah < 105   # 0.5-pt bins
    assert profile_from_bars(df.assign(volume=10.0), tick=0.5).kind == "volume"


def test_tick_classifier_quote_then_tick_rule():
    c = TickClassifier()
    assert c.classify(Trade(ts("2026-09-28 10:00"), 100.05, 1, 0, 100.0, 100.05)).side == 1     # at the ask
    assert c.classify(Trade(ts("2026-09-28 10:00"), 100.00, 1, 0, 100.0, 100.05)).side == -1    # at the bid
    assert c.classify(Trade(ts("2026-09-28 10:00"), 100.10, 1)).side == 1                        # uptick
    assert c.classify(Trade(ts("2026-09-28 10:00"), 100.10, 1)).side == 1                        # zero tick inherits


def test_footprint_delta_and_imbalances():
    fb = FootprintBuilder(tick=0.05)
    t0 = ts("2026-09-28 10:00")
    for i in range(10):
        fb.add(Trade(t0 + pd.Timedelta(seconds=i), 100.05 + 0.05 * (i % 3), 10, 1))   # aggressive buying
    fb.add(Trade(t0 + pd.Timedelta(seconds=20), 100.00, 5, -1))
    bar = fb.add(Trade(t0 + pd.Timedelta(minutes=1), 100.1, 1, 1))                   # next minute closes the bar
    assert bar is not None and bar.delta == 95 and bar.volume == 105
    assert any(side == "buy" for _, side, _ in bar.imbalances)
    assert fb.cvd().iloc[-1] == 95


# ---- chains --------------------------------------------------------------------------------------------
NSE_V3 = {"records": {"timestamp": "28-Sep-2026 10:30:00", "underlyingValue": 25010.5, "data": [
    {"strikePrice": 24950, "expiryDates": "06-Oct-2026",
     "CE": {"lastPrice": 150.0, "buyPrice1": 149.5, "sellPrice1": 150.5, "impliedVolatility": 13.1, "openInterest": 1000,
            "changeinOpenInterest": 100, "totalTradedVolume": 5000, "underlyingValue": 25010.5},
     "PE": {"lastPrice": 90.0, "buyPrice1": 89.5, "sellPrice1": 90.5, "impliedVolatility": 13.9, "openInterest": 3000,
            "changeinOpenInterest": 900, "totalTradedVolume": 7000}},
    {"strikePrice": 25000, "expiryDates": "06-Oct-2026",
     "CE": {"lastPrice": 120.0, "buyPrice1": 119.0, "sellPrice1": 121.0, "impliedVolatility": 0, "openInterest": 5000,
            "changeinOpenInterest": 800, "totalTradedVolume": 9000},
     "PE": {"lastPrice": 110.0, "buyPrice1": 109.5, "sellPrice1": 110.5, "impliedVolatility": 13.5, "openInterest": 4000,
            "changeinOpenInterest": 400, "totalTradedVolume": 8000}},
    {"strikePrice": 25000, "expiryDates": "13-Oct-2026", "CE": {"lastPrice": 999.0}},
]}}


def test_nse_v3_parser_and_analytics():
    df = NSEOptionChain.parse(NSE_V3, "NIFTY", dt.date(2026, 10, 6))
    assert list(df.columns) == COLUMNS and list(df.index) == [24950.0, 25000.0]     # other expiry filtered out
    assert df.attrs["spot"] == 25010.5 and df.attrs["ts"] == ts("2026-09-28 10:30")
    assert np.isnan(df.at[25000.0, "ce_iv"])                                          # NSE "0" means no IV
    df = fill_iv(df, IntradayPricer())
    assert 5 < df.at[25000.0, "ce_iv"] < 40
    a = chain_analytics(df)
    assert a["atm_strike"] == 25000 and a["pcr_oi"] == pytest.approx(7000 / 6000)
    assert a["top_put_adds"][0] == 24950.0 and a["max_pain"] in (24950.0, 25000.0)


def test_liquidity_flags_and_the_liquid_band():
    from quantdesk.intraday.chains import liquid_band, liquidity
    assert liquidity(100.0, 101.0) == "ok" and liquidity(100.0, 105.0) == "wide"          # 1% vs 4.9% of the mid
    assert liquidity(1.0, 1.1) == "ok"                                                   # two ticks on a cheap option
    assert all(liquidity(b, a) == "no quote" for b, a in ((0, 5.0), (np.nan, 5.0), (5.0, 4.0), (None, 1.0)))
    ks = np.arange(24700.0, 25301.0, 100.0)                                              # spot 25010: ATM 25000
    df = pd.DataFrame(np.nan, index=ks, columns=COLUMNS)
    df.index.name = "strike"
    df[["ce_bid", "ce_ask", "pe_bid", "pe_ask"]] = [50.0, 50.5, 50.0, 50.5]
    df.loc[24700.0, ["pe_bid", "pe_ask"]] = [3.0, 3.5]           # out-of-the-money put 15% wide: the band stops above
    df.loc[24800.0, ["ce_bid", "ce_ask"]] = [0.0, 260.0]         # its in-the-money call is one-sided: doesn't matter
    df.loc[25300.0, ["ce_bid", "ce_ask"]] = [np.nan, 2.0]        # out-of-the-money call with no bid
    b = liquid_band(df, 25010.0)
    assert (b["liquid_lo"], b["liquid_hi"], b["liquid_strikes"], b["strikes"]) == (24800.0, 25200.0, 5, 7)
    df.loc[25000.0, ["pe_bid", "pe_ask"]] = [0.0, 0.0]           # at the money both sides must quote
    assert "liquid_lo" not in liquid_band(df, 25010.0) and liquid_band(df, 25010.0)["liquid_strikes"] == 4
    assert liquid_band(df.assign(ce_bid=np.nan, pe_bid=np.nan), 25010.0) == {}         # no book (the model chain)


def test_the_read_gives_the_iv_percentile_and_the_liquid_strikes(cfg, sessions):
    from quantdesk.intraday.analyst import Analyst
    bars, _, days = sessions
    now = ts(f"{days[-1]} 11:00")
    s = session_state(bars["NIFTY"][bars["NIFTY"].index + pd.Timedelta(minutes=1) <= now], now)
    c = {"spot": s["last"], "atm_iv": 12.4, "atm_ivp": 0.66, "atm_iv_median": 10.8, "atm_ivp_n": 146, "atm_ivp_dte": 5,
         "liquid_lo": 24800.0, "liquid_hi": 25200.0, "liquid_strikes": 5, "strikes": 7}
    v = Analyst(cfg).assess("NIFTY", s, c)
    assert "IV percentile 66: ATM IV 12.4 vs a median 10.8 for 5-day options over the past year (146 sessions)." in v.narrative
    assert "Liquid strikes 24,800–25,200 (out-of-the-money side quoting within 3%; 5 of 7)." in v.narrative
    plain = Analyst(cfg).assess("NIFTY", s, {"spot": s["last"], "atm_iv": 12.4}).narrative
    assert "IV percentile" not in plain and "Liquid strikes" not in plain


def test_the_read_weighs_the_futures_build_up_and_basis(cfg, sessions):
    from quantdesk.intraday.analyst import Analyst
    bars, _, days = sessions
    now = ts(f"{days[-1]} 11:00")
    s = session_state(bars["NIFTY"][bars["NIFTY"].index + pd.Timedelta(minutes=1) <= now], now)
    base = {"spot": s["last"], "atm_iv": 12.4}
    fut = {**base, "fut_symbol": "NIFTY26OCTFUT", "fut_ltp": s["last"] + 60, "fut_basis": 60.0, "fut_carry": 0.07,
           "fut_buildup": "short build-up", "fut_dir": -0.8, "fut_px_chg30": -0.004, "fut_oi_chg30": 0.008,
           "fut_carry_chg": -0.02, "fut_oi_vs_prev": 0.031}
    a = Analyst(cfg)
    plain, v = a.assess("NIFTY", s, base), a.assess("NIFTY", s, fut)
    ev = {e.factor: e for e in v.evidence}
    assert ev["fut_oi"].direction == pytest.approx(-0.8) and "short build-up" in ev["fut_oi"].observation
    assert ev["basis"].direction == pytest.approx(-2 / 3) and "shrinking" in ev["basis"].observation
    assert v.score < plain.score                                 # fresh shorts and a fading premium lean it down
    assert "Futures: NIFTY26OCTFUT" in v.narrative and "OI +3.1% vs yesterday" in v.narrative
    quiet = a.assess("NIFTY", s, {**fut, "fut_dir": 0.0, "fut_carry_chg": 0.004})
    assert not {"fut_oi", "basis"} & {e.factor for e in quiet.evidence}


def test_time_to_expiry_is_minute_precise():
    e = dt.date(2026, 9, 29)
    assert time_to_expiry(ts("2026-09-29 15:30"), e) == 0
    assert time_to_expiry(ts("2026-09-29 09:30"), e) == pytest.approx(6 / 24 / 365)


def test_marker_uses_quote_iv_and_spread(cfg, sessions):
    bars, _, days = sessions
    cal = TradingCalendar(cfg.holidays())
    now = ts(f"{days[-1]} 11:00")
    mc = ModelOptionChain(cfg, cal, lambda u, t: (25000.0, 0.13))
    exp = mc.expiries("NIFTY", now)[1]
    ch = mc.chain("NIFTY", exp, ts=now)
    mk = QuoteMarker(IntradayPricer())
    mk.calibrate(ch, 65)
    from quantdesk.core.types import Instrument
    inst = Instrument.option("NIFTY", exp, 25000, "CE", 65)
    row = ch.loc[25000.0]
    assert mk.mid(inst, 25000.0, now) == pytest.approx((row.ce_bid + row.ce_ask) / 2, rel=0.02)
    b, a = mk.bid_ask(inst, 25000.0, now)
    assert a > b and mk.exit_price(inst, 65, 25000.0, now) == b and mk.exit_price(inst, -65, 25000.0, now) == a
    assert mk.mid(inst, 25100.0, now) > mk.mid(inst, 25000.0, now)                      # delta shows up


def test_prices_use_the_iv_the_quote_implies_not_the_printed_one(cfg, sessions):
    """29 Sep 2026: NSE printed 14.7% for a put whose ask implied 14.05%; valuing it at the printed IV made it
    'worth' ₹92 the moment it was bought for ₹85 (phantom EV at entry, phantom P&L at the mark)."""
    from quantdesk.core.types import Instrument
    from quantdesk.intraday.playbook import StrikePicker
    _, _, days = sessions
    cal = TradingCalendar(cfg.holidays())
    now = ts(f"{days[-1]} 11:00")
    mc = ModelOptionChain(cfg, cal, lambda u, t: (25000.0, 0.13))
    exp = mc.expiries("NIFTY", now)[1]
    ch = mc.chain("NIFTY", exp, ts=now)
    ch["ce_iv"] += 1.5                                          # the exchange's figure disagrees with its own quotes
    ch["pe_iv"] += 1.5
    mk = QuoteMarker(IntradayPricer())
    mk.calibrate(ch, 65)
    for K in (24800.0, 25000.0, 25200.0):
        row = ch.loc[K]
        inst = Instrument.option("NIFTY", exp, K, "PE", 65)
        assert mk.mid(inst, 25000.0, now) == pytest.approx((row.pe_bid + row.pe_ask) / 2, rel=0.003)
    rows = StrikePicker(IntradayPricer()).rows(ch, "PE", now).set_index("strike")
    pr, T = IntradayPricer(), time_to_expiry(now, exp)
    for K in (24800.0, 25000.0):
        assert pr.price(K, "PE", 25000.0, T, rows.at[K, "iv"] / 100) == pytest.approx(rows.at[K, "mid"], rel=0.003)


def test_a_stop_inside_one_minutes_noise_is_pushed_out(cfg, sessions):
    from quantdesk.intraday.analyst import MarketView
    from quantdesk.intraday.playbook import Playbook
    _, _, days = sessions
    cal = TradingCalendar(cfg.holidays())
    now = ts(f"{days[-1]} 11:00")
    mc = ModelOptionChain(cfg, cal, lambda u, t: (25000.0, 0.13))
    ch = mc.chain("NIFTY", mc.expiries("NIFTY", now)[0], ts=now)
    view = MarketView("NIFTY", now, 25000.0, "bearish", -0.8, 0.8, "trend", "fair", 13.0, 12.0, [], [], {}, "",
                      state={"atr5": 22.0})
    plan = Playbook(cfg, IntradayPricer())._directional("vwap_trend", view, ch, now, -1, "t", "thesis.", 25003.0, 24980.0)
    floor = cfg.get("intraday.risk.min_stop_atr5") * 22.0
    assert plan.invalidation == pytest.approx(25000.0 + floor)            # 3 pts → 16.5 pts
    assert 25000.0 - plan.target_underlying >= 1.5 * floor - 1e-9 and "floored" in plan.thesis
    wide = Playbook(cfg, IntradayPricer())._directional("vwap_trend", view, ch, now, -1, "t", "thesis.", 25040.0, 24920.0)
    assert wide.invalidation == 25040.0 and wide.target_underlying == 24920.0      # a sane stop is left alone


def test_intraday_broker_fills_at_quote_plus_ticks(cfg):
    from quantdesk.core.types import Instrument, Order
    br = IntradayBroker(cfg, starting_cash=500000, adverse_ticks=1)
    inst = Instrument.option("NIFTY", dt.date(2026, 10, 6), 25000, "CE", 65)
    f = br.execute(Order(inst, 65, "t", "open"), 120.0, ts("2026-09-28 10:00"))
    assert f.price == pytest.approx(120.05)
    f2 = br.execute(Order(inst, -65, "t", "close"), 130.0, ts("2026-09-28 11:00"))
    assert f2.price == pytest.approx(129.95) and f2.fee_breakdown["stt"] == pytest.approx(65 * 129.95 * 0.0015)


# ---- features: no look-ahead ------------------------------------------------------------------------------
def test_session_state_is_causal(sessions):
    bars, _, days = sessions
    day = days[-1]
    full = bars["NIFTY"]
    for hhmm in ("09:40", "11:05", "14:20"):
        now = ts(f"{day} {hhmm}")
        seen = full[full.index + pd.Timedelta(minutes=1) <= now]
        a = session_state(seen, now)
        b = session_state(seen, now, cache={})
        later = full[full.index + pd.Timedelta(minutes=1) <= now + pd.Timedelta(minutes=30)]
        c = session_state(later[later.index + pd.Timedelta(minutes=1) <= now], now)
        for k, v in a.items():
            if isinstance(v, float):
                assert (np.isnan(v) and np.isnan(b[k])) or v == pytest.approx(b[k]), k
                assert (np.isnan(v) and np.isnan(c[k])) or v == pytest.approx(c[k]), k
        assert a["bars_today"] == int((now - ts(f"{day} 09:15")).total_seconds() // 60)


def test_replay_feed_never_shows_the_forming_bar(sessions):
    bars, _, days = sessions
    f = ReplayFeed(bars, days[-1])
    f.advance(10)
    got = f.poll("NIFTY", None)
    assert len(got) == 10 and got.index[-1] == ts(f"{days[-1]} 09:24")
    assert f.history("NIFTY", 3).index.max() < ts(f"{days[-1]} 09:15")


# ---- engine ------------------------------------------------------------------------------------------------
def test_full_session_replay(cfg, sessions, tmp_path):
    bars, meta, days = sessions
    j = Journal(tmp_path / "j.db")
    br = IntradayBroker(cfg, starting_cash=500000, state_path=tmp_path / "b.json")
    rec = SessionRecorder(tmp_path / "data")
    reviews = tmp_path / "reviews"
    totals = []
    for d in days[-3:]:
        eng = IntradayEngine(cfg, ReplayFeed(bars, d), "model", j, br, rec, say=None, review_dir=reviews)
        run_replay(eng)
        totals.append(len(eng.closed))
        assert not eng.open_trades                                             # flat at the close
    tr = j.trades()
    assert len(tr) == sum(totals) and (tr["status"] == "closed").all()
    th = j.thoughts()
    assert len(th) > 100 and set(th["symbol"]) == {"NIFTY", "BANKNIFTY"}
    assert th["narrative"].str.contains("bias").all()
    ev = json.loads(th.iloc[-1]["evidence"])
    assert ev and {"factor", "direction", "weight", "observation"} <= set(ev[0])
    if len(tr):
        t = tr.iloc[0]
        assert "Trigger:" in t["rationale"] and "Thesis:" in t["rationale"] and "Market read:" in t["rationale"]
        opened = pd.to_datetime(tr["opened_at"])
        assert (opened.dt.time >= dt.time(9, 20)).all() and (opened.dt.time <= dt.time(14, 45)).all()
        assert (pd.to_datetime(tr["closed_at"]).dt.time <= dt.time(15, 16)).all()
        assert tr["grade"].notna().all()
        assert (tr.groupby(tr["opened_at"].str[:10]).size() <= cfg.get("intraday.risk.max_trades_per_day")).all()
    fills = j.df("SELECT * FROM fills")
    assert br.cash() == pytest.approx(500000 - (fills["qty"] * fills["price"]).sum() - fills["fees"].sum(), abs=0.01)
    assert sum(tr["pnl"]) == pytest.approx(br.cash() - 500000, abs=0.01)
    assert sorted(p.stem for p in reviews.glob("*.md")) == [str(d) for d in days[-3:]]
    assert (tmp_path / "data" / str(days[-1]) / "NIFTY_1m.csv").exists()


def test_risk_gates(cfg):
    from quantdesk.intraday.risk import IntradayRisk
    r = IntradayRisk(cfg)
    r.reset(dt.date(2026, 9, 28), 500000)
    assert r.gate(ts("2026-09-28 09:17"), 500000, [], "NIFTY")                         # before 09:20
    assert not r.gate(ts("2026-09-28 10:00"), 500000, [], "NIFTY")
    below = 500000 * (1 - cfg.get("intraday.risk.daily_loss_limit") - 0.005)
    assert not any("daily loss" in x for x in r.gate(ts("2026-09-28 10:00"), 500000 * (1 - cfg.get("intraday.risk.daily_loss_limit") + 0.005), [], "NIFTY"))
    assert any("daily loss" in x for x in r.gate(ts("2026-09-28 10:00"), below, [], "NIFTY"))
    r2 = IntradayRisk(cfg)
    r2.reset(dt.date(2026, 9, 28), 500000)
    r2.on_close(-1000, ts("2026-09-28 10:00"))
    r2.on_close(-1000, ts("2026-09-28 10:10"))
    assert any("cooling off" in x for x in r2.gate(ts("2026-09-28 10:20"), 498000, [], "NIFTY"))
    assert not r2.gate(ts("2026-09-28 10:45"), 498000, [], "NIFTY")


def test_no_new_entry_when_the_model_chain_stands_in_for_a_failed_real_one(cfg, sessions):
    """F-01: when the real chain fails the desk prices off the model chain (fine for marks) but must not open trades
    on invented quotes; a replay that chose the model chain on purpose is unaffected."""
    from types import SimpleNamespace
    from quantdesk.intraday.chains import ChainSource

    class Down(ChainSource):
        name = "kotak"

        def expiries(self, underlying):
            raise ConnectionError("kotak down")

        def chain(self, underlying, expiry, spot=None, ts=None):
            raise ConnectionError("kotak down")

    bars, _, days = sessions
    calm = SimpleNamespace(vetoes=[])
    down = IntradayEngine(cfg, ReplayFeed(bars, days[-1]), Down(), Journal(), IntradayBroker(cfg, starting_cash=500000), say=None)
    run_replay(down)
    now = down.last_ts["NIFTY"]
    assert down.chain_df["NIFTY"].attrs["source"] == "model"
    assert "kotak option chain unavailable" in (down._blocked("NIFTY", calm, now) or "")
    assert not down.closed and not down.open_trades                          # nothing opened on invented quotes
    model = IntradayEngine(cfg, ReplayFeed(bars, days[-1]), "model", Journal(), IntradayBroker(cfg, starting_cash=500000), say=None)
    run_replay(model)
    assert "unavailable" not in (model._blocked("NIFTY", calm, model.last_ts["NIFTY"]) or "")


def test_a_forming_5_minute_bar_is_not_complete_after_one_minute(cfg, monkeypatch):
    """A-18: completed() used a 1-minute bar length on Yahoo's 5-minute history."""
    import yfinance as yf
    from quantdesk.intraday.feeds import IntradayFeed, YahooIntradayFeed
    idx = pd.date_range("2026-10-05 09:15", "2026-10-05 10:00", freq="5min", tz=IST)
    raw = pd.DataFrame({"Open": 1.0, "High": 1.0, "Low": 1.0, "Close": 1.0, "Volume": 1.0}, index=idx)
    monkeypatch.setattr(yf, "Ticker", lambda t: type("T", (), {"history": lambda self, **k: raw})())
    feed = YahooIntradayFeed(cfg)
    monkeypatch.setattr(feed, "now", lambda: pd.Timestamp("2026-10-05 10:02", tz=IST))
    got = feed.history_bars("NIFTY")
    assert got.index[-1] == pd.Timestamp("2026-10-05 09:55", tz=IST)          # 10:00-10:05 is still forming
    ones = pd.date_range("2026-10-05 09:15", "2026-10-05 10:01", freq="1min", tz=IST)
    one = pd.DataFrame({"open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1.0}, index=ones)
    monkeypatch.setattr(feed, "history", lambda symbol, days=55: one)
    got = IntradayFeed.history_bars(feed, "NIFTY")                                  # the default: 1m resampled to 5m
    assert got.index[-1] == pd.Timestamp("2026-10-05 09:55", tz=IST)


def test_opening_range_is_a_clock_window_and_unknown_after_a_late_start(cfg, sessions):
    """B-10: the OR / IB were the first 15 / 60 rows present, so a late start or a gap made any bars 'the open'."""
    bars, _, days = sessions
    b = bars["NIFTY"]
    d = days[-1]
    full = b[b.index.date <= d]
    t = pd.Timestamp(f"{d} 11:00", tz=IST)
    s = session_state(full[full.index <= t], t)
    day = full[full.index.date == d]
    first15 = day[day.index < pd.Timestamp(f"{d} 09:30", tz=IST)]
    assert s["or_done"] and s["or_high"] == float(first15["high"].max()) and s["minutes"] == 105
    late = full[(full.index.date < d) | (full.index >= pd.Timestamp(f"{d} 10:00", tz=IST))]    # started at 10:00
    s2 = session_state(late[late.index <= t], t)
    assert s2["minutes"] == 105                                   # time since 09:15, not since the first bar
    assert not s2["or_done"] and not s2["ib_done"]                # the opening range is unknown, not 10:00-10:14
    assert np.isfinite([s2["or_high"], s2["or_low"], s2["ib_high"], s2["ib_low"]]).all()
    # a late start must not open other setups instead: counting minutes from 09:15 on a partial day would lift the
    # "forming"/"first 5 minutes" gates over a VWAP built from a few bars, so the analyst stands aside all day
    from quantdesk.intraday.analyst import Analyst
    assert s["from_open"] and not s2["from_open"]
    assert not any("starts after the open" in v for v in Analyst(cfg).assess("NIFTY", s, {"spot": s["last"]}).vetoes)
    assert any("starts after the open" in v for v in Analyst(cfg).assess("NIFTY", s2, {"spot": s2["last"]}).vetoes)
    gap = full[(full.index.date < d) | (full.index < pd.Timestamp(f"{d} 09:21", tz=IST)) | (full.index >= pd.Timestamp(f"{d} 10:00", tz=IST))]
    s3 = session_state(gap[gap.index <= t], t)                   # 09:15-09:20, then nothing until 10:00
    assert s3["from_open"] and not s3["or_done"] and not s3["ib_done"]   # 6 of 15 bars is not an opening range
    # the engine says so once, at WARN with "failed", so self-review files it instead of a silent day of standing aside
    lb = {sym: df[(df.index.date < d) | (df.index >= pd.Timestamp(f"{d} 10:00", tz=IST))] for sym, df in bars.items()}
    eng = IntradayEngine(cfg, ReplayFeed(lb, d), "model", Journal(), IntradayBroker(cfg, starting_cash=500000), say=None)
    run_replay(eng)
    ev = eng.journal.df("SELECT * FROM events WHERE level = 'WARN' AND category = 'data'")
    assert len(ev) == len(eng.underlyings) and ev["message"].str.contains("opening bars failed to arrive").all()

