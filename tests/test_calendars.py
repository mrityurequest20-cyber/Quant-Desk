"""Calendars and diagonals (owner, 14 Nov 2026: "Build Calendar and diagonal spreads"): a sale in the near expiry covered by a purchase in the next one. The worst case is
judged at the near expiry with the later long at the least a European option can be worth (account.multi_expiry_worst), in the paper gate and in AUTO v2 alike; a proven
calendar goes live as ONE package through the real runner and gate, and its own exit closes it with the sale bought back first."""
from __future__ import annotations

import datetime as dt
import math

import pytest

from quantdesk.paper import auto2 as A2
from quantdesk.paper.account import CAL_S_MAX, Q_MAX, R_MAX, multi_expiry_worst, option_floor
from tests.test_paper_auto import T0, board
from tests.test_paper_auto2 import cfg, cycle, desk, proven  # noqa: F401  (cfg is a fixture)

IST = A2.IST
NEAR, NEXT = dt.date(2026, 11, 12), dt.date(2026, 11, 19)
CAL = "CAL0.faan.1/0.5.d"


def board2(t, **kw):
    """The test board with a second expiry a week later: the same strikes, each option dearer by the extra week at about the same implied volatility (x1.8, the square
    root of the times to expiry). Priced cheaper, the near expiry's volatility would stand above the next's: the market read calls that an event priced, and no
    calendar (short volatility into the near expiry) is opened."""
    b = board(t, **kw)
    for name, qd in list(b["quotes"].items()):
        if "12NOV26" in name:
            m = 1.8
            b["quotes"][name.replace("12NOV26", "19NOV26")] = {**qd, "bid": round(qd["bid"] * m, 1), "ask": round(qd["ask"] * m + 0.1, 1), "ltp": round(qd["ltp"] * m, 1)}
    return b


def test_an_option_is_never_worth_less_than_its_floor():
    from statistics import NormalDist
    N = NormalDist().cdf

    def bs(S, K, T, sig, r, q, right):
        d1 = (math.log(S / K) + (r - q + sig * sig / 2) * T) / (sig * math.sqrt(T))
        d2 = d1 - sig * math.sqrt(T)
        return S * math.exp(-q * T) * N(d1) - K * math.exp(-r * T) * N(d2) if right == "CE" else K * math.exp(-r * T) * N(-d2) - S * math.exp(-q * T) * N(-d1)
    for S in (15000, 24000, 25000, 26000, 40000):
        for T in (1 / 365, 7 / 365, 30 / 365):
            for r, q in ((0.0, 0.0), (0.065, 0.013), (R_MAX, Q_MAX)):
                for right in ("CE", "PE"):
                    assert bs(S, 25000, T, 0.05, r, q, right) >= option_floor(right, 25000, S, T) - 1e-6, (S, T, r, q, right)


def test_the_worst_case_of_the_textbook_shapes():
    lot = 65
    call = multi_expiry_worst([(25000.0, "CE", -lot, NEAR), (25000.0, "CE", lot, NEXT)])
    assert call == pytest.approx(-Q_MAX * 7 / 365 * CAL_S_MAX * 25000 * lot)                        # beyond the debit: only the dividend allowance at three times the strike
    put = multi_expiry_worst([(25000.0, "PE", -lot, NEAR), (25000.0, "PE", lot, NEXT)])
    assert put == pytest.approx(-R_MAX * 7 / 365 * 25000 * lot)                                       # and the rate allowance for a put
    assert multi_expiry_worst([(25100.0, "CE", -lot, NEAR), (25000.0, "CE", lot, NEXT)]) == 0.0       # a call diagonal covered at a lower strike loses nothing more
    assert multi_expiry_worst([(25000.0, "CE", lot, NEAR), (25000.0, "CE", -lot, NEXT)]) is None      # a reverse calendar is not covered this way
    assert multi_expiry_worst([(25000.0, "CE", -2 * lot, NEAR), (25000.0, "CE", lot, NEXT)]) == -math.inf
    assert multi_expiry_worst([(25000.0, "CE", -lot, NEAR), (25000.0, "CE", lot, NEAR)]) is None       # one expiry: the ordinary rule


def test_auto_v2_prices_a_calendar_across_two_expiries(cfg, tmp_path):
    from quantdesk.paper import auto as V1
    _, ap = desk(cfg, tmp_path)
    t = T0 + dt.timedelta(minutes=5)
    snap = board2(t)
    ch = V1.chains(snap, ap.und, ap.lots)
    for i in range(6):
        st = ap.state(board2(T0 + dt.timedelta(minutes=i)), "NIFTY", ch, T0 + dt.timedelta(minutes=i), None)
    assert st["near"] == NEAR and st["next"] == NEXT
    p = ap.price(snap, A2.BY_SID[CAL], st, ch)
    assert st["regime"] == "normal" and p and p["multi"] and [(l["side"], l["right"], l["k"], l["exp"]) for l in p["legs"]] == [(-1, "CE", 24500, NEAR), (1, "CE", 24500, NEXT)]
    debit = p["legs"][1]["px"] - p["legs"][0]["px"]
    assert debit > 0 and p["risk"] == pytest.approx(debit - multi_expiry_worst([(24500, "CE", -1, NEAR), (24500, "CE", 1, NEXT)]) + p["fees"])
    assert ap.tail_check(A2.BY_SID[CAL], st, p, NEAR)[0] is True
    assert ap.price(board(t), A2.BY_SID[CAL], st, V1.chains(board(t), ap.und, ap.lots)) is None       # no next expiry on the board: no calendar


def test_a_proven_calendar_goes_live_as_one_package_and_closes_whole(cfg, tmp_path):
    rn, ap = desk(cfg, tmp_path, stats=proven(CAL))
    ap.evolved_on = T0.date()
    for i in range(6):
        t = T0 + dt.timedelta(minutes=i)
        mine, rep = cycle(rn, ap, board2(t), t)
    pos = rn.account.positions
    assert set(pos) == {"NIFTY12NOV2624500CE", "NIFTY19NOV2624500CE"}, (list(pos), [r for r in rep["results"]])
    assert pos["NIFTY12NOV2624500CE"].qty == -65 and pos["NIFTY19NOV2624500CE"].qty == 65
    assert math.isfinite(rn.account.stress())                                                         # the gate's worst case is bounded
    late = dt.datetime.combine(T0.date(), dt.time(15, 16), tzinfo=IST)
    mine, rep = cycle(rn, ap, board2(late), late)
    sells = [o for o in mine if o["side"] == "sell"]
    assert len(sells) == 2 and sells[0]["symbol"] == "NIFTY12NOV2624500CE" and not rn.account.positions     # the sale bought back first, then the cover sold


def test_no_calendar_when_the_options_price_an_event(cfg, tmp_path):
    from quantdesk.paper import auto as V1
    _, ap = desk(cfg, tmp_path)
    for i in range(6):
        t = T0 + dt.timedelta(minutes=i)
        snap = board(t)
        for name, qd in [(n, x) for n, x in snap["quotes"].items() if "12NOV26" in n]:                # the next expiry barely dearer: the near volatility is the higher
            snap["quotes"][name.replace("12NOV26", "19NOV26")] = {**qd, "bid": round(qd["bid"] * 1.2, 1), "ask": round(qd["ask"] * 1.2 + 0.1, 1)}
        st = ap.state(snap, "NIFTY", V1.chains(snap, ap.und, ap.lots), t, None)
    assert st["regime"] == "event" and not ap.matches(A2.BY_SID[CAL], st)
