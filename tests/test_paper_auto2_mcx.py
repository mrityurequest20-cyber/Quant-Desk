"""AUTO v2 on MCX and currency options (owner, 13 Nov 2026: "Directly implement auto V2" for them). PAPER MONEY ONLY.

Pinned: the underlying is the near-month future the board shows, priced at rate 0 (an option on a future); each segment's own hours (a crude option trades at 21:00, when NSE is
shut); a currency option's premium floor is in its own ticks; it never opens a contract on its last holding day (the runner sells MCX and currency options the trading day
before expiry); and a proven strategy goes live as one package through the real runner and gate, in the MCX segment."""
from __future__ import annotations

import datetime as dt
import math
import random
from pathlib import Path

import pytest

from quantdesk.config import Config
from quantdesk.paper import auto2 as A2
from quantdesk.paper import runner as R
from quantdesk.paper.account import Account
from quantdesk.paper.risk import KillSwitch, RiskGate
from quantdesk.paperlink.cli import auto_v2

ROOT = Path(__file__).resolve().parents[1]
IST = A2.IST
EVE = dt.datetime(2026, 11, 16, 21, 0, tzinfo=IST)                       # Monday evening: NSE shut, MCX open to 23:30
EXP = dt.date(2026, 11, 20)
IC = "IC1.faan.1/0.5.d"


@pytest.fixture()
def cfg():
    return Config.load(ROOT / "config" / "quantdesk.yaml")


def black76(F, K, T, iv, right):
    from statistics import NormalDist
    N = NormalDist().cdf
    d1 = (math.log(F / K) + iv * iv * T / 2) / (iv * math.sqrt(T))
    d2 = d1 - iv * math.sqrt(T)
    return F * N(d1) - K * N(d2) if right == "CE" else K * N(-d2) - F * N(-d1)


def crude_board(t, F=5800.0, age=1.0, exp=EXP):
    T = (dt.datetime.combine(exp, dt.time(15, 30), tzinfo=IST) - t).total_seconds() / (365.25 * 86400)
    q = {"CRUDEOIL-MCX": dict(bid=F - 1, ask=F + 1, ltp=F, age_s=age, s="mcx", e="2026-12-17", bid_qty=500, ask_qty=500)}
    for k in range(5500, 6101, 50):
        for right in ("CE", "PE"):
            m = max(black76(F, k, T, 0.35, right), 2.0)
            q[f"CRUDEOIL{exp:%d%b%y}{k}{right}".upper()] = dict(bid=round(m - 0.4, 1), ask=round(m + 0.4, 1), ltp=round(m, 1), age_s=age, s="opt", bid_qty=3000, ask_qty=3000)
    return {"now": int(t.timestamp() * 1000), "quotes": q}


def desk(cfg, tmp_path, stats=None):
    rn = R.Runner(cfg, Account(500_000), gate=RiskGate(cfg, kill=KillSwitch(tmp_path / "K")), kill_file=tmp_path / "K")
    ap = auto_v2(cfg, ("CRUDEOIL",), {"CRUDEOIL": 100}, {"CRUDEOIL": "mcx"})
    ap.rng = random.Random(1)
    if stats:
        ap.lab = A2.Lab(stats)
    return rn, ap


def proven(sid=IC, n=20, mean=0.6):
    return {sid: [n, mean * n, (mean * mean + 0.25) * n, int(0.7 * n)]}


def cycle(rn, ap, t, **kw):
    snap = crude_board(t, **kw)
    mine = ap.decide(snap, rn.account, R.Runner.server_now(snap))
    rep = rn.step(snap, mine, False, t.astimezone(dt.timezone.utc))
    return mine, rep


def test_the_underlying_is_the_future_priced_at_rate_zero_in_mcx_hours(cfg, tmp_path):
    rn, ap = desk(cfg, tmp_path)
    assert ap.spot(crude_board(EVE), "CRUDEOIL") == 5800.0 and ap.rate("CRUDEOIL") == 0.0 and ap.window("CRUDEOIL")[1] == dt.time(22, 45)
    st = ap.state(crude_board(EVE), "CRUDEOIL", A2.V1.chains(crude_board(EVE), ap.und, ap.lots), EVE, None)
    assert st["near"] == EXP and st["iv"] == pytest.approx(0.35, abs=0.02)                     # Black-76 prices read back at rate 0: the implied volatility they were made with


def test_a_proven_strategy_goes_live_on_crude_at_9pm_as_one_mcx_package(cfg, tmp_path):
    rn, ap = desk(cfg, tmp_path, proven())
    t = EVE
    for i in range(7):                                                                        # a quiet tape: the view becomes flat
        t = EVE + dt.timedelta(minutes=i)
        cycle(rn, ap, t)
    live = {p.strategy for p in rn.account.positions.values()}
    assert live == {f"{A2.TAG} {IC} CRUDEOIL"}, live
    assert {p.segment for p in rn.account.positions.values()} == {"mcx"} and len(rn.account.positions) == 4


def test_nothing_opens_outside_mcx_hours_or_on_a_contracts_last_holding_day(cfg, tmp_path):
    rn, ap = desk(cfg, tmp_path, proven())
    late = EVE.replace(hour=22, minute=50)
    for i in range(7):
        cycle(rn, ap, late + dt.timedelta(minutes=i))
    assert not rn.account.positions                                                            # after 22:45: no entry
    rn, ap = desk(cfg, tmp_path / "b", proven())
    thu = dt.datetime(2026, 11, 19, 10, 0, tzinfo=IST)                                         # the trading day before the 20 Nov expiry
    assert ap.tradable_expiries("CRUDEOIL", [EXP], thu.date()) == []
    for i in range(7):
        cycle(rn, ap, thu + dt.timedelta(minutes=i))
    assert not rn.account.positions


def test_a_currency_options_premium_floor_is_in_its_own_ticks(cfg, tmp_path):
    ap = auto_v2(cfg, ("USDINR",), {"USDINR": 1000}, {"USDINR": "nse_cds"})
    assert ap.min_premium("USDINR") == pytest.approx(20 * 0.0025) and ap.min_premium("NIFTY") == A2.MIN_PREMIUM


# ---- futures in AUTO v2 (owner, 14 Nov 2026: "Futures in automated strategies") ------------------------------------------------------------------------------
FL = "FL1.uaan.1/1.d"            # long future, stop half a day's sd away, take profit at 1R
FS = "FS2.daan.2/1.d"            # short future, stop one day's sd away, take profit at 2R


def futures_state(view, regime="normal", rv=0.32):
    return {"u": "CRUDEOIL", "spot": 5800.0, "view": view, "why": ["test view"], "mom": 0.3, "iv": 0.35, "rv": rv, "ratio": 1.1, "vol": "mid", "eve": False, "near": EXP,
            "next": None, "read": None, "regime": regime, "hmm": {}, "today": EVE.date()}


def test_a_proven_futures_strategy_goes_long_or_short_through_the_real_gate_with_its_stop_and_target(cfg, tmp_path, monkeypatch):
    for sid, view, side in ((FL, "up", "buy"), (FS, "down", "short")):
        rn, ap = desk(cfg, tmp_path, proven(sid))
        ap.evolved_on = EVE.date()
        monkeypatch.setattr(ap, "state", lambda snap, u, ch, now, news, v=view: futures_state(v))
        mine, rep = cycle(rn, ap, EVE)
        fut = [o for o in mine if o.get("symbol") == "CRUDEOIL-MCX"]
        assert len(fut) == 1 and fut[0]["side"] == side and fut[0]["strategy"] == f"{A2.TAG} {sid} CRUDEOIL"
        o, sd = fut[0], 0.32 / math.sqrt(252)
        entry = 5801.0 if side == "buy" else 5799.0
        dist = A2.BY_SID[sid].width * A2.FUT_STOP_SD * sd * entry
        assert o["stop"] == pytest.approx(entry - dist if side == "buy" else entry + dist, rel=1e-6)
        assert (o["target"] > entry) == (side == "buy") and abs(o["target"] - entry) > A2.BY_SID[sid].tp * dist      # the target counts the costs into R
        res = next(r for r in rep["results"] if r["id"] == o["id"])
        assert res["status"] == "filled", res
        pos = rn.account.positions["CRUDEOIL-MCX"]
        assert pos.qty == (100 if side == "buy" else -100) and pos.stop == pytest.approx(o["stop"]) and pos.target == pytest.approx(o["target"])
        mine2, _ = cycle(rn, ap, EVE + dt.timedelta(minutes=2))
        assert not [x for x in mine2 if x.get("symbol") == "CRUDEOIL-MCX"]                    # one position per contract; its exits are the runner's


def test_no_future_in_an_event_near_expiry_or_without_its_contract_month(cfg, tmp_path):
    _, ap = desk(cfg, tmp_path)
    s, board = A2.BY_SID[FL], crude_board(EVE)
    assert ap.matches(s, futures_state("up")) and not ap.matches(s, futures_state("up", regime="event")) and not ap.matches(s, futures_state("down"))
    assert ap.price(board, s, futures_state("up"), None) is not None
    near = crude_board(EVE)
    near["quotes"]["CRUDEOIL-MCX"]["e"] = "2026-11-19"                                           # three days out: inside crude's five no-entry days
    assert ap.price(near, s, futures_state("up"), None) is None
    del near["quotes"]["CRUDEOIL-MCX"]["e"]
    assert ap.price(near, s, futures_state("up"), None) is None                                  # the board must say which contract it is
    wide = crude_board(EVE)
    wide["quotes"]["CRUDEOIL-MCX"].update(bid=5780.0, ask=5820.0)
    assert ap.price(wide, s, futures_state("up"), None) is None
    assert ap.price(board, s, futures_state("up", rv=None), None) is None                        # no volatility: no stop to set


def test_a_shadow_futures_trade_is_scored_in_r_at_its_target(cfg, tmp_path, monkeypatch):
    _, ap = desk(cfg, tmp_path)
    ap.evolved_on = EVE.date()
    monkeypatch.setattr(ap, "state", lambda snap, u, ch, now, news: futures_state("up"))
    ap.decide(crude_board(EVE), Account(500_000), EVE)
    sh = ap.shadow[(FL, "CRUDEOIL")]
    up = sh["risk"] * 1.2 + 2                                                                      # beyond 1R
    ap.decide(crude_board(EVE + dt.timedelta(minutes=3), F=5800.0 + up), Account(500_000), EVE + dt.timedelta(minutes=3))
    assert (FL, "CRUDEOIL") not in ap.shadow and ap.lab.stats[FL][0] == 1 and ap.lab.stats[FL][1] >= 1.0
