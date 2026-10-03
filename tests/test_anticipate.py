"""Anticipation: setups the read favours wait at their trigger level and fire the moment price gets there (a live
price between minutes, or a 1-minute bar's range), instead of a 5-minute close later. Exits are checked on the
same fast loop."""

import pandas as pd
import pytest

from quantdesk.core.calendar import TradingCalendar
from quantdesk.intraday.analyst import MarketView
from quantdesk.intraday.engine import IntradayEngine
from quantdesk.intraday.feeds import IST, ReplayFeed
from quantdesk.intraday.playbook import Armed, Playbook
from quantdesk.intraday.chains import IntradayPricer
from quantdesk.intraday.sim import IntradayBroker
from quantdesk.intraday.synthetic import simulate_sessions
from quantdesk.journal.journal import Journal

NOW = pd.Timestamp("2026-09-28 10:00", tz=IST)


def armed(direction=1, kind="break", level=25100.0, inval=25040.0):
    return Armed("orb", "NIFTY", direction, kind, level, inval, 1.5, 60.0, NOW, NOW + pd.Timedelta(minutes=2), "test", "t")


def test_hit_and_bar_fill_follow_the_order_type():
    up_break, dn_break = armed(1, "break", 25100), armed(-1, "break", 24900, 24960)
    up_touch = armed(1, "touch", 25000, 24950)                     # buy the pullback to 25,000
    assert up_break.hit(25100) and not up_break.hit(25099.9)
    assert dn_break.hit(24900) and not dn_break.hit(24900.1)
    assert up_touch.hit(25000) and not up_touch.hit(25000.1)
    assert up_break.bar_fill(25090, 25110, 25080) == 25100           # filled at the level inside the bar
    assert up_break.bar_fill(25120, 25130, 25115) == 25120           # gapped through: at the open
    assert up_break.bar_fill(25050, 25099, 25040) is None            # never reached
    assert dn_break.bar_fill(24910, 24920, 24890) == 24900 and dn_break.bar_fill(24880, 24890, 24870) == 24880
    assert up_touch.bar_fill(25010, 25020, 24995) == 25000 and up_touch.bar_fill(24990, 25000, 24980) == 24990
    assert up_touch.bar_fill(25010, 25020, 25001) is None


def view(score=0.5, conviction=0.6, vetoes=(), day_type="trend", spot=25080.0):
    return MarketView("NIFTY", NOW, spot, "bullish" if score > 0 else "bearish", score, conviction, day_type, "fair",
                      13.0, 11.0, [], list(vetoes), {}, "", {})


def state(**kw):
    s = {"last": 25080.0, "vwap": 25030.0, "atr5": 20.0, "or_done": True, "minutes": 45, "or_high": 25095.0,
         "or_low": 25000.0, "rel_volume": 1.0, "ema9": 25060.0, "ema21": 25040.0}
    s.update(kw)
    return s


def test_arm_only_what_the_read_favours_and_is_within_reach(cfg):
    pb = Playbook(cfg, IntradayPricer())
    a = pb.arm(view(), state(), NOW)
    orb = [x for x in a if x.setup == "orb"]
    assert len(orb) == 1 and orb[0].kind == "break" and orb[0].direction == 1
    assert orb[0].level == pytest.approx(25095 + 0.1 * 20) and orb[0].invalidation == pytest.approx(25047.5)  # OR mid
    assert not [x for x in a if x.setup == "vwap_trend"]                 # 48 pts above VWAP: beyond 1.5 ATR5 of reach
    vw = [x for x in pb.arm(view(), state(last=25050.0), NOW) if x.setup == "vwap_trend"]
    assert vw and vw[0].kind == "touch" and vw[0].level == pytest.approx(25032) and vw[0].invalidation == pytest.approx(25023)
    assert not [x for x in pb.arm(view(), state(last=25100.0), NOW) if x.setup == "orb"]     # already broke: not anticipation
    assert not [x for x in pb.arm(view(), state(last=25040.0), NOW) if x.setup == "orb"]     # 57 pts away > 1.5 ATR5
    assert pb.arm(view(conviction=0.2), state(), NOW) == []
    assert pb.arm(view(vetoes=["event window"]), state(), NOW) == []
    bear = pb.arm(view(score=-0.5, spot=25010.0), state(last=25010.0, vwap=25050.0, ema9=25030.0, ema21=25045.0), NOW)
    assert [x.direction for x in bear if x.setup == "orb"] == [-1]


@pytest.fixture(scope="module")
def day():
    from quantdesk.config import DEFAULT_CONFIG, Config
    c = Config.load(DEFAULT_CONFIG)
    days = [d.date() for d in TradingCalendar(c.holidays()).trading_days("2026-08-31", "2026-09-28")]
    bars, _ = simulate_sessions(days, seed=5)
    return c, bars, days[-1]


class LivePrice(ReplayFeed):
    """A replay with a live price between minutes, like Kotak's quotes."""
    has_ltp = True

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.px, self.fail = {}, False

    def ltp(self, symbols):
        if self.fail:
            raise RuntimeError("quotes down")
        return {s: self.px[s] for s in symbols if s in self.px}


def engine_at(cfg, bars, d, minutes=45):
    from quantdesk.config import DEFAULT_CONFIG, Config
    cfg = Config.load(DEFAULT_CONFIG, overrides={"intraday": {"anticipate": {"confirm_fallback": False}}})
    feed = LivePrice(bars, d)
    eng = IntradayEngine(cfg, feed, "model", Journal(), IntradayBroker(cfg, starting_cash=500000), say=None)
    eng.start_session(d)
    for _ in range(minutes):
        feed.advance()
        eng.step()
    eng.armed = {}
    return eng, feed


def test_a_live_price_fires_the_armed_entry_at_the_level_and_exits_in_real_time(day):
    cfg, bars, d = day
    eng, feed = engine_at(cfg, bars, d)
    u = "NIFTY"
    v = eng.views[u]
    eng.views[u] = v = v.__class__(**{**v.__dict__, "vetoes": [], "score": 0.6, "conviction": 0.7, "bias": "bullish"})
    S = v.spot
    now = feed.now()
    eng.armed[u] = [Armed("orb", u, 1, "break", S + 10, S - 40, 1.5, 30.0, now, now + pd.Timedelta(minutes=2), "test", "t")]
    feed.px[u] = S + 5
    assert not eng.tick() and not eng.open_trades                       # not there yet: nothing happens
    feed.px[u] = S + 12
    eng.tick()
    msgs = eng.journal.df("SELECT * FROM decisions")
    if not eng.open_trades:                                             # the EV gate may still say no; it must say why
        assert msgs.astype(str).apply(lambda r: r.str.contains("reached its level")).any(axis=None)
        return
    t = eng.open_trades[0]
    assert t.entry_underlying == pytest.approx(S + 12) and t.meta["armed"]["level"] == pytest.approx(S + 10, abs=0.01)
    assert "traded through" in t.rationale and eng.armed[u] == []
    feed.px[u] = t.stop - 1                                             # the stop is checked on the live price
    eng.tick()
    assert not eng.open_trades and eng.closed[-1].exit_reason == "invalidation"


def test_quotes_failing_falls_back_to_the_minute_bars(day):
    cfg, bars, d = day
    eng, feed = engine_at(cfg, bars, d, minutes=20)
    now = feed.now()
    eng.armed["NIFTY"] = [Armed("orb", "NIFTY", 1, "break", 1e9, 0.0, 1.5, 1.0, now, now + pd.Timedelta(minutes=2), "x", "t")]
    feed.fail = True
    for _ in range(3):
        eng.tick()
    assert not eng.live_px                                              # the bars decide now
    ev = eng.journal.df("SELECT * FROM events WHERE category='quotes'")
    assert ev["message"].str.contains("fire on the minute bars").any()
    eng._tick_retry = now                                               # a minute later it tries again
    feed.fail = False
    feed.px["NIFTY"] = 1.0
    eng.tick()
    assert eng.live_px


def test_replay_without_a_live_price_fills_armed_setups_inside_the_bar(day):
    cfg, bars, d = day
    feed = ReplayFeed(bars, d)
    eng = IntradayEngine(cfg, feed, "model", Journal(), IntradayBroker(cfg, starting_cash=500000), say=None)
    from quantdesk.intraday.engine import run_replay
    run_replay(eng)
    for t in eng.closed:                                                # every anticipated entry filled at its level
        a = t.meta.get("armed")
        if a:
            lvl = a["level"]
            assert (t.entry_underlying >= lvl - 0.006) if (a["direction"] > 0) == (a["kind"] == "break") else \
                   (t.entry_underlying <= lvl + 0.006)                  # the record rounds the level to 2 dp
    from quantdesk.config import DEFAULT_CONFIG, Config
    off = Config.load(DEFAULT_CONFIG, overrides={"intraday": {"anticipate": {"confirm_fallback": False}}})
    e2 = IntradayEngine(off, ReplayFeed(bars, d), "model", Journal(), IntradayBroker(off, starting_cash=500000), say=None)
    run_replay(e2)                                                      # without the fallback only armed entries exist
    assert all(t.strategy not in ("orb", "trend_break", "vwap_trend") or t.meta.get("armed") for t in e2.closed)


def test_buyer_only_below_the_selling_threshold(day):
    """A ₹20k account can't post margin for a sold leg: only long calls and puts until equity reaches the threshold.
    The selling structures stay in the playbook and come back by themselves."""
    cfg, bars, d = day
    from quantdesk.intraday.engine import run_replay
    small = IntradayEngine(cfg, ReplayFeed(bars, d), "model", Journal(), IntradayBroker(cfg, starting_cash=20000), say=None)
    run_replay(small)
    assert all(l.qty > 0 for t in small.closed for l in t.legs) and not small.playbook.allow_short
    ev = small.journal.df("SELECT message FROM events WHERE category='mode'")["message"]
    assert ev.str.contains("buyer only").any() and ev.str.contains("300,000").any()
    big = IntradayEngine(cfg, ReplayFeed(bars, d), "model", Journal(), IntradayBroker(cfg, starting_cash=500000), say=None)
    run_replay(big)
    assert big.playbook.allow_short                                   # ₹5 lakh: spreads are allowed again

    pb = Playbook(cfg, IntradayPricer())
    from quantdesk.intraday.chains import ModelOptionChain
    eng = IntradayEngine(cfg, ReplayFeed(bars, d), "model", Journal(), IntradayBroker(cfg, starting_cash=500000), say=None)
    eng.start_session(d)
    for _ in range(60):
        eng.feed.advance()
        eng.step()
    ch, now = eng.chain_df["NIFTY"], eng.feed.now()
    v = view(score=0.6, conviction=0.7, spot=float(ch.attrs["spot"]))
    v = v.__class__(**{**v.__dict__, "vol_view": "rich", "state": {"atr5": 20.0}})
    for allow, want in ((True, "bull_call_spread"), (False, "long_call")):
        pb.allow_short = allow
        plan = pb._directional("orb", v, ch, now, 1, "t", "t", float(ch.attrs["spot"]) - 60, float(ch.attrs["spot"]) + 90)
        assert plan.structure == want and (allow or all(l.ratio > 0 for l in plan.legs))
        alts = pb.alternatives(plan, ch, now)
        assert allow or all(a.structure.startswith("long_") for a in alts)
