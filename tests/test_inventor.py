"""Strategy liberty (owner, 13 Nov 2026: "make sure the trading desk has full liberty to use any trading strategy and also make its own strategy too"): the wider written
catalogue (butterflies, broken wings, backspreads, with legs of more than one lot) and the INVENTOR (quantdesk/paper/inventor.py), which writes new structures, defined-risk
and new in shape, held to a higher proof bar, capped and retired on a bad record, and kept through a restart."""
from __future__ import annotations

import datetime as dt
import json
import random

from quantdesk.paper import auto2 as A2
from quantdesk.paper import inventor as INV
from tests.test_paper_auto import T0, board
from tests.test_paper_auto2 import FakeRelay, calm, cfg, cycle, desk, proven  # noqa: F401  (cfg is a fixture)

IST = A2.IST
CONDOR = ((1, "CE", -3), (-1, "CE", -1), (-1, "CE", 1), (1, "CE", 3))         # a wide call condor: flat, defined risk, costs well under MAX_FEES_R of its risk
#                                                                                (by put-call parity it is an iron condor's shape, so the inventor itself would not write it)


def test_the_inventor_keeps_only_defined_risk_new_tradable_shapes():
    assert INV.defined_risk(((1, "CE", 0), (-1, "CE", 1))) and not INV.defined_risk(((1, "CE", 0), (-2, "CE", 1)))     # a call ratio spread can lose without limit
    assert INV.defined_risk(((-1, "PE", 0),))                                                    # a short put's worst is its strike: finite (the risk gate refuses its size)
    assert not INV.tradable(((-1, "PE", 0),)) and not INV.tradable(((1, "CE", 9),))              # nothing bought, or a strike too far out
    assert INV.norm([(2, "PE", -1)]) == ((1, "PE", -1),)                                        # two long puts are a long put: results are per unit of risk
    assert INV.view_of(((1, "CE", 0),)) == "up" and INV.view_of(((1, "PE", 0),)) == "down" and INV.view_of(CONDOR) == "flat"
    assert INV.code_of(CONDOR) == INV.code_of(reversed(CONDOR)) and INV.code_of(CONDOR).startswith("G")
    known = A2.known_shapes()
    assert INV.fingerprint(A2.resolved_legs("BCS", 1)) in known
    kids = INV.invent([A2.resolved_legs("BCS", 1), A2.resolved_legs("IC", 1)], known, random.Random(4), 30, tries=2000)
    assert len(kids) >= 10
    for k in kids:
        assert INV.defined_risk(k) and INV.tradable(k) and INV.fingerprint(k) not in known
    assert len({INV.fingerprint(k) for k in kids}) == len(kids)                                  # no two the same shape


def test_it_invents_once_a_day_and_the_inventions_survive_a_restart(cfg, tmp_path):
    rn, ap = desk(cfg, tmp_path)
    made = ap.evolve(dt.date(2026, 11, 16))
    assert len(made) == A2.INVENT_PER_DAY and ap.evolve(dt.date(2026, 11, 16)) == []
    for sid in made:
        s = A2.BY_SID[sid]
        assert s in ap.strategies() and s.struct in ap.lab.inv and ap.lab.min_trades(s) == A2.MIN_TRADES_INVENTED
        assert A2.STRUCTURES[s.struct][0] == s.view and len(f"{A2.TAG} {s.sid} BAJAJ-AUTO") <= 60
    relay = FakeRelay()
    ap.lab.add(made[0], 0.3)
    assert ap.save(relay, 1000.0, force=True)
    rn2, ap2 = desk(cfg, tmp_path)
    ap2.load(relay)
    assert [s.sid for s in ap2.lab.invented()] == made and ap2.lab.stats[made[0]][0] == 1
    raw = json.loads(relay.lab)
    raw["inv"]["Gzzzzz"] = {"legs": [[1, "CE", 0], [-2, "CE", 1]], "active": ["Gzzzzz0.uaan.1/0.5.d"]}     # undefined risk, and a name that is not its shape
    code = next(iter(raw["inv"]))
    raw["inv"][code]["legs"] = [[1, "CE", 0], [-3, "CE", 1]]                                     # tampered legs no longer match their name
    _, ap3 = desk(cfg, tmp_path)
    ap3.load(FakeRelay(json.dumps(raw)))
    assert "Gzzzzz" not in ap3.lab.inv and code not in ap3.lab.inv                               # storage is not trusted


def test_a_bad_invention_is_retired_and_the_population_is_capped(cfg, tmp_path):
    _, ap = desk(cfg, tmp_path)
    made = ap.evolve(dt.date(2026, 11, 16))
    bad = made[0]
    for _ in range(2 * A2.MIN_TRADES_INVENTED):
        ap.lab.add(bad, -0.9)
    ap.evolve(dt.date(2026, 11, 17))
    assert bad not in [s.sid for s in ap.lab.invented()]
    for d in range(18, 40):
        ap.evolve(dt.date(2026, 11, 1) + dt.timedelta(days=d))
    assert len(ap.lab.invented()) <= A2.MAX_INVENTED


def test_a_butterfly_goes_live_with_a_two_lot_body_and_closes_whole(cfg, tmp_path):
    cbf = "CBF2.faan.1/0.5.d"                                                                    # two strikes wide: the one-strike fly costs half its risk to trade (MAX_FEES_R)
    rn, ap = desk(cfg, tmp_path, stats=proven(cbf))
    ap.evolved_on = T0.date()
    calm(rn, ap, minutes=5)
    pos = rn.account.positions
    assert len(pos) == 3 and all(p.strategy == f"{A2.TAG} {cbf} NIFTY" for p in pos.values())
    assert sorted(p.qty // p.instrument.lot_size for p in pos.values()) == [-2, 1, 1]           # the body is two lots, sold; the wings one each, bought
    late = dt.datetime.combine(T0.date(), dt.time(15, 16), tzinfo=IST)
    mine, _ = cycle(rn, ap, board(late), late)
    assert len([o for o in mine if o["side"] == "sell"]) == 3 and not rn.account.positions


def test_costs_above_a_third_of_the_risk_are_not_traded(cfg, tmp_path):
    from quantdesk.paper import auto as V1
    _, ap = desk(cfg, tmp_path)
    for i in range(6):
        t = T0 + dt.timedelta(minutes=i)
        snap = board(t)
        ch = V1.chains(snap, ap.und, ap.lots)
        st = ap.state(snap, "NIFTY", ch, t, None)
    assert ap.price(snap, A2.BY_SID["CBF1.faan.1/0.5.d"], st, ch) is None                      # about half its risk in costs
    p = ap.price(snap, A2.BY_SID["CBF2.faan.1/0.5.d"], st, ch)
    assert p is not None and p["fees"] <= A2.MAX_FEES_R * p["risk"]


def test_an_invention_needs_more_trades_than_a_written_strategy(cfg, tmp_path):
    for n, live in ((A2.MIN_TRADES_INVENTED - 2, False), (A2.MIN_TRADES_INVENTED + 8, True)):
        rn, ap = desk(cfg, tmp_path)
        sid = ap.lab.adopt(CONDOR, A2.BY_SID["IC1.faan.1/0.5.d"])[0].sid
        ap.lab = A2.Lab(proven(sid, n=n), ap.lab.inv)
        ap.evolved_on = T0.date()                                                                # no new inventions in this test
        calm(rn, ap, minutes=5)
        held = {p.strategy for p in rn.account.positions.values()}
        assert (f"{A2.TAG} {sid} NIFTY" in held) is live, (n, held)


def test_the_apps_strategy_builder_is_given_the_inventions_it_can_build(cfg, tmp_path):
    _, ap = desk(cfg, tmp_path)
    made = ap.evolve(dt.date(2026, 11, 16))
    inv = ap.lab.summary()["inventions"]
    assert len(inv) == len(made) and all(set(x) == {"code", "name", "view", "legs", "mu_r", "trades"} for x in inv)
    x = inv[0]
    assert x["view"] in ("up", "down", "flat") and all(len(l) == 3 and l[1] in ("CE", "PE") for l in x["legs"]) and x["name"].startswith("invented: ")
