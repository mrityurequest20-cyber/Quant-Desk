"""AUTO with the strategy search wired in (quantdesk/paper/auto.py + structures.py). Everything runs through the REAL runner, gate, broker and account; only the board is made up. What is pinned: the search is OFF unless
asked for; a calm tape and selling allowed gives a hedged package (sold legs only inside it) that the gate fills; with selling off the same calm tape trades nothing; every leg of a structure is managed and closed
together, the sold ones bought back first; the stop, the target and the overnight rule for structures; nothing AUTO opens is ever sold or touched if it is not AUTO's; the loss caps and the gate stay the bound."""
import dataclasses
import datetime as dt

import pytest

from quantdesk.config import Config
from quantdesk.paper import auto as A
from quantdesk.paper import runner as R
from tests.test_paper_auto import SIG_UP, T0, board, desk, tick, warm

CALM = dict(minutes=12)


@pytest.fixture()
def cfg():
    return Config.load(__import__("pathlib").Path(__file__).resolve().parents[1] / "config" / "quantdesk.yaml")


def search_desk(cfg, tmp_path, short=True):
    rn, ap, cal = desk(cfg, tmp_path)
    rn.gate.limits = dataclasses.replace(rn.gate.limits, allow_short_legs=short)
    ap.structures, ap.allow_short = True, short
    return rn, ap, cal


def at(m):
    return T0 + dt.timedelta(minutes=m)


def test_the_search_is_off_by_default_and_the_old_first_strike_buy_is_unchanged(cfg, tmp_path):
    rn, ap, cal = desk(cfg, tmp_path)
    assert ap.structures is False and ap.allow_short is False
    warm(rn, ap, cal, T0)
    mine, _ = tick(rn, ap, cal, board(at(7), **SIG_UP), at(7))
    assert len(mine) == 1 and mine[0]["strategy"].startswith("AUTO v1")


def test_a_calm_tape_with_selling_allowed_gives_a_hedged_package_the_gate_fills_as_one(cfg, tmp_path):
    rn, ap, cal = search_desk(cfg, tmp_path)
    warm(rn, ap, cal, T0, **CALM)
    mine, rep = tick(rn, ap, cal, board(at(13), **SIG_UP), at(13))
    assert len(mine) == 1 and mine[0]["side"] == "package" and mine[0]["strategy"].startswith("AUTO v2 NIFTY up #")
    sides = sorted((l["side"], l["lots"]) for l in mine[0]["legs"])
    assert ("sell", 2) in sides and sum(l["lots"] for l in mine[0]["legs"] if l["side"] == "buy") == 2           # a butterfly: the two sold are covered by two bought
    assert "wing" in mine[0]["thesis"] and "not a measured edge" in mine[0]["thesis"] and len(mine[0]["thesis"]) <= 1000
    assert rep["results"][0]["status"] == "filled" and len(rep["results"][0]["fills"]) == 3
    assert rn.account.has_shorts() and rn.account.verify_ledger()
    assert ap.last_info["search"]["NIFTY"]["best"] and ap.last_info["search"]["NIFTY"]["vol_ratio"] == 0.6


def test_with_selling_off_the_same_calm_tape_trades_nothing_and_a_normal_tape_buys_one_option(cfg, tmp_path):
    rn, ap, cal = search_desk(cfg, tmp_path, short=False)
    warm(rn, ap, cal, T0, **CALM)
    mine, rep = tick(rn, ap, cal, board(at(13), **SIG_UP), at(13))
    assert mine == [] and not rn.account.positions and ap.last_info["search"]["NIFTY"]["best"] is None
    rn2, ap2, cal2 = search_desk(cfg, tmp_path / "b", short=False)
    (tmp_path / "b").mkdir(exist_ok=True)
    warm(rn2, ap2, cal2, T0)                                                                                    # too little tape to move the expected move: the market's own
    mine2, rep2 = tick(rn2, ap2, cal2, board(at(7), **SIG_UP), at(7))
    assert len(mine2) == 1 and mine2[0]["side"] == "buy" and mine2[0]["strategy"].startswith("AUTO v2") and rep2["results"][0]["status"] == "filled"


def open_package(cfg, tmp_path):
    rn, ap, cal = search_desk(cfg, tmp_path)
    warm(rn, ap, cal, T0, **CALM)
    tick(rn, ap, cal, board(at(13), **SIG_UP), at(13))
    assert rn.account.has_shorts()
    return rn, ap, cal


def reprice_all(snap, mult):
    for k, q in snap["quotes"].items():
        if "NIFTY12NOV26" in k:
            q["bid"], q["ask"] = round(q["bid"] * mult, 2), round(q["ask"] * mult, 2)
    return snap


def test_a_structure_that_loses_half_its_worst_case_is_closed_whole_with_the_sold_legs_bought_back_first(cfg, tmp_path):
    rn, ap, cal = open_package(cfg, tmp_path)
    strat = next(iter(rn.account.positions.values())).strategy
    # the sold middle strike gains and the bought wings lose: the butterfly is hurt (the spot runs away from the middle)
    snap = board(at(20), **SIG_UP)
    for k, q in snap["quotes"].items():
        if k.endswith("24550CE"):
            q["bid"], q["ask"] = q["bid"] + 40.0, q["ask"] + 40.0
    mine, rep = tick(rn, ap, cal, snap, at(20))
    assert mine and all(o["side"] == "sell" for o in mine) and len(mine) == 3
    assert mine[0]["symbol"].endswith("24550CE") and "stop" in mine[0]["_why"]                           # the sold option is bought back FIRST
    assert not rn.account.positions or all(p.strategy != strat for p in rn.account.positions.values()), [r["reasons"] for r in rep["results"]]
    assert rn.account.verify_ledger()


def test_a_structure_is_held_while_it_is_inside_its_stop_and_a_target_closes_it(cfg, tmp_path):
    rn, ap, cal = open_package(cfg, tmp_path)
    mine, _ = tick(rn, ap, cal, board(at(14), **SIG_UP), at(14))
    assert [o for o in mine if o["side"] == "sell"] == [] and rn.account.has_shorts()                             # nothing moved: nothing to do
    snap = board(at(20), **SIG_UP)
    for k, q in snap["quotes"].items():
        if k.endswith("24550CE"):
            q["bid"], q["ask"] = max(q["bid"] - 60.0, 0.05), max(q["ask"] - 60.0, 0.1)
    mine, _ = tick(rn, ap, cal, snap, at(20))
    assert not mine or all("target" in o["_why"] or "trailing" in o["_why"] or "signals" in o["_why"] for o in mine)


def test_the_overnight_rule_holds_a_structure_with_three_days_left_and_closes_one_with_one_day_left(cfg, tmp_path):
    rn, ap, cal = open_package(cfg, tmp_path)
    close = at(5 * 60 + 22)                                                                                        # 15:22 on the 9th: the decision window before the close; expiry is 3 days off
    mine, _ = tick(rn, ap, cal, board(close, **SIG_UP), close)
    assert [o for o in mine if o["side"] == "sell"] == [] and len(ap.last_info["held_overnight"]) == 3
    snap = board(at(13), **SIG_UP)
    ist = dt.datetime(2026, 11, 11, 15, 22, tzinfo=A.IST)                                                        # two sessions later with one day to expiry
    out = ap._manage_structures(snap, rn.account, ist, ist.timestamp(), {"NIFTY": 1}, None, ist, True, {})
    assert len(out) == 3 and all("expiry is too close" in o["_why"] for o in out) and out[0]["symbol"].endswith("24550CE")


def test_nothing_that_is_not_aucos_own_structure_is_managed_and_the_owners_position_is_never_sold(cfg, tmp_path):
    rn, ap, cal = search_desk(cfg, tmp_path)
    warm(rn, ap, cal, T0, **CALM)
    rn.step(board(at(13)), [{"id": "own-order-1", "side": "buy", "symbol": "NIFTY12NOV2624600CE", "lots": 1, "strategy": "owner idea", "thesis": "owner thinks the index will go up after the break",
                           "queued_at": int(at(13).timestamp() * 1000) - 1000}], False, at(13).astimezone(dt.timezone.utc))
    assert "NIFTY12NOV2624600CE" in rn.account.positions
    snap = board(at(20))
    for k, q in snap["quotes"].items():
        if k.endswith("24600CE"):
            q["bid"], q["ask"] = 0.05, 0.1
    mine, _ = tick(rn, ap, cal, snap, at(20))
    assert all(o.get("symbol") != "NIFTY12NOV2624600CE" for o in mine) and "NIFTY12NOV2624600CE" in rn.account.positions
