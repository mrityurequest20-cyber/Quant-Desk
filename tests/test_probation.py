"""Evolution phase 2: probation and the vote watch, as registered (docs/prereg/evolution_probation_v1.json; docs/EVOLUTION.md).

What is pinned: the CUSUM is updated once per strategy per session, scaled by that session's trade count, from the record as it stood before the session, and only once
the strategy has its proof; it demotes at g > H; a demoted strategy keeps trading in shadow and cannot trade paper money or be proven on the plan; it is released on
8 trades over 8 sessions with the mean of session means above zero (twice that after a quick repeat; the owner after a third); convexity strategies are never watched;
the hit rate compares the demoted strategy with its family's other strategies (a mean of per-strategy means) and excludes a window with nothing to compare; the
review is INSUFFICIENT under 20 demotions; the vote watch scores votes as calls, one per window, from the first vote after a scored window ends, starts its weighted
rate at the plain mean of the first 50, and decides mutes once a day with hysteresis; a muted vote supports nothing but still opposes and is still a reading; both
states are kept with the private record and read back validated."""
from __future__ import annotations

import datetime as dt
import json
import math

import pytest

from quantdesk.paper import auto2 as A2
from quantdesk.paper import probation as PB
from quantdesk.paper import votewatch as VW
from tests.test_paper_auto import T0, board
from tests.test_paper_auto2 import FakeRelay, IC, cfg, cycle, desk  # noqa: F401  (cfg is a fixture)

DAYS = [(dt.date(2026, 11, 16) + dt.timedelta(days=i)).isoformat() for i in range(400)]


def ctx(stats, min_trades=8, convex=(), struct=None, hold=None):
    """A Ctx over a plain dict record; calendar days stand in for sessions."""
    return PB.Ctx(stats=lambda sid: stats.get(sid), min_trades=lambda sid: min_trades,
                  sessions_between=lambda a, b: (dt.date.fromisoformat(b) - dt.date.fromisoformat(a)).days,
                  struct=lambda sid: (struct or {}).get(sid, "IC"), hold=lambda sid: (hold or {}).get(sid, "overnight"),
                  watched=lambda sid: sid not in convex)


def trade(pb, stats, sid, r, day, c):
    """As shadow_step does it: probation sees the trade, then the record adds it."""
    pb.close(sid, r, day, c)
    n, s, ss = stats.get(sid, [0, 0.0, 0.0])[:3]
    stats[sid] = [n + 1, s + r, ss + r * r, 0]


def seed(stats, sid, n=20, wins=0.7):
    """A record of n trades with mean 0.4R: +1 R and -1 R at 70/30."""
    k = int(n * wins)
    stats[sid] = [n, k - (n - k), float(n), 0]


# ---- B: the statistic -------------------------------------------------------------------------------------------------------------------------------
def test_one_update_per_session_scaled_by_its_trade_count_from_the_record_before_it():
    stats, c, pb = {}, None, PB.Probation()
    seed(stats, "S")
    c = ctx(stats)
    for r in (-1.0, -1.0, -1.0):                                                               # three losses in one session: ONE update, when the session is over
        trade(pb, stats, "S", r, DAYS[0], c)
    assert pb.st["S"]["g"] == 0.0 and pb.st["S"]["pend"][1] == 3
    pb.flush(DAYS[1], c)
    n0, s0, q0 = 20, 8.0, 20.0                                                                # the record before the session
    sd = max(math.sqrt(q0 / n0 - (s0 / n0) ** 2), PB.SD_FLOOR)
    z = -1.0 / (sd * math.sqrt(1 / 3 + PB.RHO_REG * (1 - 1 / 3)))
    assert pb.st["S"]["g"] == pytest.approx(max(0.0, -z - PB.K)) and pb.st["S"]["pend"] is None
    single = PB.Probation()
    s2 = {}
    seed(s2, "S")
    trade(single, s2, "S", -1.0, DAYS[0], ctx(s2))
    single.flush(DAYS[1], ctx(s2))
    z1 = -1.0 / max(math.sqrt(20 / 20 - 0.4 ** 2), PB.SD_FLOOR)
    assert single.st["S"]["g"] == pytest.approx(-z1 - PB.K)                                     # one trade reads as one trade
    assert pb.st["S"]["g"] > single.st["S"]["g"]                                               # three losses are more evidence than one, though not three times


def test_a_session_is_applied_at_the_next_sessions_first_close_and_only_once_proven():
    stats = {"S": [5, 2.0, 5.0, 0]}                                                            # under its min_trades: not watched yet
    c, pb = ctx(stats), PB.Probation()
    trade(pb, stats, "S", -1.0, DAYS[0], c)
    trade(pb, stats, "S", -1.0, DAYS[1], c)                                                    # the first close of the next session applies the last one
    assert pb.st["S"]["g"] == 0.0 and pb.st["S"]["pend"][0] == DAYS[1]
    pb2, s2 = PB.Probation(), {}
    seed(s2, "S")
    trade(pb2, s2, "S", -1.0, DAYS[0], ctx(s2))
    trade(pb2, s2, "S", 1.0, DAYS[1], ctx(s2))
    assert pb2.st["S"]["g"] > 0 and pb2.st["S"]["pend"] == [DAYS[1], 1, 1.0, 1.0]


def test_a_strategy_that_starts_losing_is_demoted_and_a_convexity_one_never_is():
    stats = {}
    seed(stats, "S")
    seed(stats, "CX")
    c, pb = ctx(stats, convex=("CX",)), PB.Probation()
    day = 0
    while not pb.blocked("S"):
        trade(pb, stats, "S", -1.0, DAYS[day], c)
        trade(pb, stats, "CX", -1.0, DAYS[day], c)
        day += 1
        pb.flush(DAYS[day], c)
        assert day < 30
    assert pb.st["S"]["g"] > PB.H and pb.events[-1][1:3] == ["S", "demoted"] and "CX" not in pb.st
    g = pb.st["S"]["g"]
    trade(pb, stats, "S", -1.0, DAYS[day], c)
    pb.flush(DAYS[day + 1], c)
    assert pb.st["S"]["g"] == g                                                                # frozen in probation


def test_release_needs_the_registered_proof_and_a_quick_repeat_needs_twice_then_the_owner():
    stats = {}
    seed(stats, "S")
    c, pb = ctx(stats), PB.Probation()

    def demote(start):
        d = start
        while not pb.blocked("S"):
            trade(pb, stats, "S", -2.0, DAYS[d], c)
            d += 1
            pb.flush(DAYS[d], c)
        return d

    def win(start, sessions):
        for i in range(sessions):
            trade(pb, stats, "S", 0.5, DAYS[start + i], c)
            pb.flush(DAYS[start + i + 1], c)
        return start + sessions

    d = demote(0)
    d = win(d, PB.RELEASE_SESSIONS - 1)
    assert pb.blocked("S")                                                                     # 7 trades over 7 sessions: not yet
    d = win(d, 1)
    assert not pb.blocked("S") and pb.st["S"]["g"] == 0.0 and pb.events[-1][2] == "released"
    d = demote(d)                                                                              # again, within 60 sessions: twice the proof
    assert pb.st["S"]["P"]["mult"] == 2
    d = win(d, PB.RELEASE_SESSIONS * 2 - 1)
    assert pb.blocked("S")
    d = win(d, 1)
    assert not pb.blocked("S")
    d = demote(d)                                                                              # a third: the owner's
    assert pb.st["S"]["P"]["owner"]
    d = win(d, 40)
    assert pb.blocked("S") and pb.owner_release("S", DAYS[d]) and not pb.blocked("S")
    losing = PB.Probation()
    s3 = {}
    seed(s3, "L")
    dd = 0
    while not losing.blocked("L"):
        trade(losing, s3, "L", -2.0, DAYS[dd], ctx(s3))
        dd += 1
        losing.flush(DAYS[dd], ctx(s3))
    for i in range(20):                                                                        # still losing: never released
        trade(losing, s3, "L", -0.5, DAYS[dd + i], ctx(s3))
        losing.flush(DAYS[dd + i + 1], ctx(s3))
    assert losing.blocked("L")


def test_the_hit_rate_compares_with_the_family_and_excludes_a_window_with_nothing_to_compare():
    stats = {}
    for sid in ("S", "A", "B"):
        seed(stats, sid)
    c, pb = ctx(stats), PB.Probation()
    d = 0
    while not pb.blocked("S"):
        trade(pb, stats, "S", -2.0, DAYS[d], c)
        d += 1
        pb.flush(DAYS[d], c)
    demoted_on = DAYS[d - 1]
    trade(pb, stats, "S", -1.0, DAYS[d], c)                                                    # own: -1
    trade(pb, stats, "A", 1.0, DAYS[d], c)                                                     # control: A +1 (two trades, mean +1), B 0
    trade(pb, stats, "A", 1.0, DAYS[d], c)
    trade(pb, stats, "B", 0.0, DAYS[d], c)
    pb.flush(DAYS[d + PB.HIT_HORIZON_SESSIONS + 1], c)
    assert pb.hits[demoted_on]["overnight"] == [1, pytest.approx(-1.5), 0]                    # -1 - mean(+1, 0): a mean of per-strategy means
    lone = PB.Probation()
    s2 = {}
    seed(s2, "S")
    dd = 0
    while not lone.blocked("S"):
        trade(lone, s2, "S", -2.0, DAYS[dd], ctx(s2))
        dd += 1
        lone.flush(DAYS[dd], ctx(s2))
    lone.flush(DAYS[dd + 30], ctx(s2))
    assert lone.report()["review"]["excluded"] == 1 and lone.report()["review"]["demotions"] == 0


def test_the_review_is_insufficient_under_twenty_demotions_and_the_report_names_no_strategy():
    pb = PB.Probation()
    pb.hits = {DAYS[i]: {"overnight": [1, -0.3, 0]} for i in range(19)}
    r = pb.report()
    assert r["review"]["status"] == "INSUFFICIENT"
    pb.hits[DAYS[19]] = {"overnight": [1, -0.3, 0], "day": [5, 25.0, 0]}                      # day strategies are not the review's population
    pb.events = [[DAYS[0], "S1", "demoted", {}]]
    r = pb.report()
    assert r["review"]["demotions"] == 20 and r["review"]["status"] == "WORKING" and r["review"]["mean_diff"] == pytest.approx(-0.3)
    assert "S1" not in json.dumps(r)                                                           # aggregates only: what may be published


def test_probation_state_round_trips_and_a_bad_one_costs_only_itself():
    stats = {}
    seed(stats, IC)
    c, pb = ctx(stats), PB.Probation()
    d = 0
    while not pb.blocked(IC):
        trade(pb, stats, IC, -2.0, DAYS[d], c)
        d += 1
        pb.flush(DAYS[d], c)
    trade(pb, stats, IC, 0.5, DAYS[d], c)
    known = lambda sid: sid in A2.BY_SID                                                       # noqa: E731
    back = PB.Probation()
    back.restore(json.loads(json.dumps(pb.decision())), json.loads(json.dumps(pb.measurement())), pb.pset(), known)
    assert back.st[IC]["P"] == pb.st[IC]["P"] and back.st[IC]["pend"] == pb.st[IC]["pend"] and back.events == pb.events and back.counts == pb.counts
    other = next(s for s in A2.BY_SID if s != IC and not A2.CX.is_convex(A2.BY_SID[s].struct))
    bad = {"st": {"NOPE": {"g": 9}, IC: {"g": "x", "P": {"since": "garbage"}}, other: {"g": 2.0, "p": ["2026-02-30", 1, 0.5, 0.25], "r": "2026-13-01"}}}
    held = PB.Probation()
    held.restore(bad, {"ev": [["x"], [DAYS[0], IC, "hacked", {}]], "fo": [{"sid": IC, "day": "2026-02-30"}], "hi": {"bad": 1}}, None, known)
    assert set(held.st) == {IC, other} and held.blocked(IC) and held.st[IC]["P"]["owner"]   # an unreadable probation stays one, the owner's
    assert held.st[other]["g"] == 2.0 and held.st[other]["pend"] is None and held.st[other]["rel"] is None   # a bad date costs only its own field
    assert held.events == [] and held.follow == [] and held.hits == {}
    lost = PB.Probation()
    lost.restore(None, None, {IC: [DAYS[3], 2, False]}, known)                                 # the book lost, the record's list kept: still in probation
    assert lost.blocked(IC) and lost.st[IC]["P"]["mult"] == 2 and lost.st[IC]["P"]["since"] == DAYS[3]
    junk = PB.Probation()
    junk.restore(None, None, {IC: "junk"}, known)
    assert junk.blocked(IC) and junk.st[IC]["P"]["owner"]
    assert PB.is_day("2026-02-28") and not PB.is_day("2026-02-30") and not PB.is_day(20261116)
    shrunk = pb.decision(max_g=0)
    assert "g" not in shrunk["st"].get(IC, {}) or not pb.st[IC]["g"] and shrunk["st"][IC]["P"] == pb.decision()["st"][IC]["P"]


# ---- B: in AUTO v2 ------------------------------------------------------------------------------------------------------------------------------------
def test_a_strategy_in_probation_is_not_proven_on_the_plan_nor_chosen_live(cfg, tmp_path):
    from tests.test_plan_first import PRE, planned_desk
    rn, ap, sid = planned_desk(cfg, tmp_path)
    ap.probation.st[sid] = {"g": 6.0, "pend": None, "P": {"since": "2026-11-06", "n": 0, "ses": 0, "sm": 0.0, "mult": 1, "owner": False}, "rel": None, "rep": 0}
    from tests.test_paper_dayplan import CLOSE_AGE, UP
    rebuilt = ap.plan(board(PRE, age=CLOSE_AGE, **UP), PRE)
    mine = [i for i in rebuilt["items"] if i["sid"] == sid]
    assert mine and all(i["probation"] and not i["proven"] for i in mine)
    from tests.test_plan_first import OPEN
    ap.day_plan = rebuilt
    orders = ap.decide(board(OPEN, **UP), rn.account, OPEN)
    assert not any(sid in (o.get("strategy") or "") for o in orders)                           # in probation: shadow only
    ap.probation.st.pop(sid)
    ap.day_plan = ap.plan(board(PRE, age=CLOSE_AGE, **UP), PRE)
    assert any(i["sid"] == sid and i["proven"] for i in ap.day_plan["items"])                  # the same strategy, not in probation, is proven


def test_auto2_feeds_probation_each_shadow_close_before_the_record(cfg, tmp_path):
    from tests.test_paper_auto2 import calm
    rn, ap = desk(cfg, tmp_path)
    seen = []
    real = ap.probation.close
    ap.probation.close = lambda sid, r, day, c: (seen.append((sid, r, day, (ap.lab.stats.get(sid) or [0])[0])), real(sid, r, day, c))[1]
    calm(rn, ap, minutes=6)
    late = dt.datetime.combine(T0.date(), dt.time(15, 20), tzinfo=A2.IST)
    cycle(rn, ap, board(late), late)
    assert seen and all(day == T0.date().isoformat() for _, _, day, _ in seen)
    for sid, r, day, n_before in seen:
        assert n_before < ap.lab.stats[sid][0] and -5 <= r <= 10                                # seen before the record added it, clamped as the record clamps it


def test_phase2_rides_with_the_book_and_the_record_keeps_who_is_in_probation(cfg, tmp_path):
    from tests.test_shadow_carry import Relay
    rn, ap = desk(cfg, tmp_path)
    ap.probation.st[IC] = {"g": 6.5, "pend": None, "P": {"since": "2026-11-06", "n": 3, "ses": 2, "sm": 0.4, "mult": 1, "owner": False}, "rel": None, "rep": 0}
    ap.probation.pver += 1
    ap.votes.k["read|NIFTY"] = {"n": 60, "first": 28.0, "ew": 0.47, "up": 30, "muted": True, "pend": None, "free": 0.0}
    ap.votes.ver += 1
    relay = Relay()
    ap.lab.dirty = True
    assert ap.save(relay, 1000.0, force=True)
    rec, book = A2.Lab.unpack(relay.lab), A2.Lab.unpack(relay.shadow)
    assert rec["pbP"] == {IC: ["2026-11-06", 1, False]} and "pb" not in rec and rec["vw"]["k"]["read|NIFTY"][4] is True
    assert book["p2"]["d"]["st"][IC]["P"]["n"] == 3 and "m" in book["p2"]
    ap2 = desk(cfg, tmp_path)[1]
    ap2.load(relay, now=T0)
    assert ap2.probation.st[IC]["P"]["n"] == 3 and ap2.votes.muted("read", "NIFTY")
    ap3 = desk(cfg, tmp_path)[1]
    ap3.load(Relay(relay.lab, None), now=T0)                                                   # the book lost: the record's list keeps the probation
    assert ap3.probation.blocked(IC) and ap3.probation.st[IC]["P"]["n"] == 0 and ap3.votes.muted("read", "NIFTY")
    assert T0.date().isoformat() in ap3.p2x["carry_missing"]
    s = ap2.summary()
    assert s["probation"]["in_probation"] == 1 and s["votes"]["muted"] == 1 and s["phase2"]["spec"] == "evolution_probation_v1"
    assert s["phase2"]["spec_sha256"] and len(s["phase2"]["spec_sha256"]) == 64
    assert not ap.save(relay, 1010.0)                                                          # nothing changed: nothing sent


def test_phase2_never_displaces_a_strategy_record(cfg, tmp_path):
    """Risk review, 14 Nov 2026: measurement state saved with the record pushed cumulative records out of it. Now the record carries only who is in probation
    and the vote watch, and only when that costs no record; the rest rides with the book, shed first there."""
    import random
    rng = random.Random(3)
    sids = [s for s in A2.BY_SID if not A2.CX.is_convex(A2.BY_SID[s].struct)]
    stats = {s: [rng.randint(8, 400), rng.uniform(-40, 40), rng.uniform(1, 600), rng.randint(0, 200)] for s in sids}
    rn, ap = desk(cfg, tmp_path, stats=stats)
    for i, s in enumerate(sids[:200]):
        ap.probation.st[s] = {"g": rng.uniform(0, 4), "pend": [DAYS[0], 3, rng.uniform(-3, 3), rng.uniform(0, 9)], "P": None, "rel": None, "rep": 0}
    for i in range(30):                                                                        # thirty open windows, each with a full family of controls
        ap.probation.follow.append({"sid": sids[i], "struct": "IC", "hold": "overnight", "day": DAYS[0], "own": [3, rng.uniform(-3, 3)],
                                    "ctrl": {s: [rng.randint(1, 9), rng.uniform(-9, 9)] for s in sids[:252]}})
    ap.lab.to_json({})
    alone = ap.lab.last_kept
    from tests.test_shadow_carry import Relay
    relay = Relay()
    ap.lab.dirty = True
    assert ap.save(relay, 1000.0, force=True)
    back = A2.Lab.unpack(relay.lab)
    assert len(back["stats"]) == alone and len(relay.lab) <= A2.LAB_MAX_CHARS                  # every record the record held before phase 2, and within the bound
    assert len(relay.shadow) <= A2.SHADOW_MAX_CHARS


def test_the_session_count_is_not_capped(cfg, tmp_path):
    ap = desk(cfg, tmp_path)[1]
    n = ap.pb_ctx.sessions_between("2026-01-01", "2026-12-31")
    assert n > 200                                                                             # the repeat window and the review clock count real sessions


def test_a_mute_that_stops_an_agreement_is_recorded(cfg, tmp_path):
    from tests.test_plan_first import NEWS_T, UP_BOOK, news_desk, rising
    rn, ap, sid = news_desk(cfg, tmp_path)
    rising(rn, ap, 13, cusum_at=8)
    t = NEWS_T + dt.timedelta(minutes=13)
    snap = board(t, spot=24500 * math.exp(0.0005 * 13), **UP_BOOK)
    ap.votes.muted = lambda k, u: k == "book"
    ap.state(snap, "NIFTY", A2.V1.chains(board(NEWS_T), ap.und, ap.lots), t, None)
    assert ap.p2x["stop"][t.date().isoformat()]["live"] == ["NIFTY"] and ap.phase2_report()["stopped"]["live"] == 1


# ---- C: the vote watch -----------------------------------------------------------------------------------------------------------------------------
def test_votes_are_scored_as_calls_one_per_window_from_the_first_vote_after_it():
    w = VW.VoteWatch()
    w.observe("read", "NIFTY", 0, 0.70, 100.0)                                                 # a vote up
    w.observe("read", "NIFTY", 300, 0.80, 101.0)                                               # within the window: not a new vote
    w.observe("read", "NIFTY", 900, None, 100.5)                                               # the window passed: +0.5%, right
    e = w.k["read|NIFTY"]
    assert e["n"] == 1 and e["first"] == 1.0 and e["up"] == 1 and e["free"] == 900
    w.observe("read", "NIFTY", 950, 0.30, 100.5)                                               # down
    w.observe("read", "NIFTY", 1850, None, 100.52)                                             # +0.02%: under MIN_MOVE, no outcome
    assert e["n"] == 1 and e["pend"] is None
    w.observe("read", "NIFTY", 1900, 0.5, 100.0)                                               # no opinion: not a vote
    assert e["pend"] is None
    w.observe("news", "NIFTY", 2000, 0.66, 100.0)
    w.observe("news", "NIFTY", 2000 + 900, None, 90.0)                                         # the news model's window is an hour: not yet
    assert w.k["news|NIFTY"]["n"] == 0
    w.observe("news", "NIFTY", 2000 + 3600, None, 99.0)
    assert w.k["news|NIFTY"]["n"] == 1 and w.k["news|NIFTY"]["first"] == 0.0
    late = VW.VoteWatch()
    late.observe("read", "X", 0, 0.7, 100.0)
    late.observe("read", "X", 900 + VW.RESOLVE_TOL_S + 1, None, 105.0)                         # not seen at its window's end: no outcome
    assert late.k["read|X"]["n"] == 0 and late.k["read|X"]["late"] == 1
    night = VW.VoteWatch()
    t0 = dt.datetime(2026, 11, 16, 15, 25, tzinfo=A2.IST).timestamp()
    night.observe("read", "X", t0, 0.7, 100.0)
    night.observe("read", "X", dt.datetime(2026, 11, 17, 9, 15, tzinfo=A2.IST).timestamp(), None, 103.0)   # judged across the night: never
    assert night.k["read|X"]["n"] == 0


def test_the_weighted_rate_starts_at_the_mean_of_fifty_and_mutes_once_a_day_with_hysteresis():
    w, t = VW.VoteWatch(), 0.0

    def call(right):
        nonlocal t
        w.observe("read", "X", t, 0.7, 100.0)
        t += 900
        w.observe("read", "X", t, None, 101.0 if right else 99.0)
        t += 1

    for i in range(VW.MIN_VOTES - 1):
        call(i % 2 == 0)
    w.decide("2026-11-16")
    assert not w.muted("read", "X")                                                            # 49 votes: never muted
    call(False)
    e = w.k["read|X"]
    assert e["ew"] == pytest.approx(25 / 50)
    for _ in range(3):
        call(False)
    w.decide("2026-11-16")
    assert not w.muted("read", "X")                                                            # decided once a day: the same day changes nothing
    w.decide("2026-11-17")
    assert w.muted("read", "X") and e["ew"] < VW.MUTE_BELOW
    while e["ew"] < 0.52:
        call(True)
    w.decide("2026-11-18")
    assert w.muted("read", "X")                                                                # 0.52: above 0.50, under 0.53, stays muted
    while e["ew"] < VW.UNMUTE_AT:
        call(True)
    w.decide("2026-11-19")
    assert not w.muted("read", "X")
    back = VW.VoteWatch()
    back.restore(json.loads(json.dumps(w.export())))
    assert back.decided == w.decided and set(back.k) == set(w.k)
    for key, e in w.k.items():
        assert {k: v for k, v in back.k[key].items() if k != "ew"} == {k: v for k, v in e.items() if k != "ew"} and back.k[key]["ew"] == pytest.approx(e["ew"], abs=1e-5)
    back.restore({"k": {"read|X": [10, 3.0, None, 2, True, None, 0.0], "evil|X": [1, 1, 1, 1, False, None, 0], "news|Y": [60, 1.0, None, 1, False, None, 0]}})
    assert not back.muted("read", "X") and set(back.k) == {"read|X"}                           # under 50 votes cannot be muted; an unknown model is dropped


def test_a_muted_vote_supports_nothing_but_still_opposes_and_is_still_a_reading(cfg, tmp_path):
    from tests.test_plan_first import NEWS_T, UP_BOOK, news_desk, rising
    rn, ap, sid = news_desk(cfg, tmp_path)
    rising(rn, ap, 13, cusum_at=8)
    t = NEWS_T + dt.timedelta(minutes=13)
    snap = board(t, spot=24500 * math.exp(0.0005 * 13), **UP_BOOK)
    ch = A2.V1.chains(board(NEWS_T), ap.und, ap.lots)
    base = ap.state(snap, "NIFTY", ch, t, None)
    assert base["agree"] == "up" and base["votes"] == 3
    ap.votes.muted = lambda k, u: k == "book"                                                  # the watch's one hook, pointed at a reading the test can hold
    st = ap.state(snap, "NIFTY", ch, t, None)
    assert st["agree"] is None and st["votes"] == 3 and "book" not in st["sources"]            # two supporting readings are not three; it is still a reading


def test_a_muted_news_vote_cannot_carry_the_day_plans_direction(cfg, tmp_path):
    from tests.test_paper_dayplan import CLOSE_AGE, UP
    from tests.test_plan_first import PRE
    rn, ap = desk(cfg, tmp_path, plan_only=True)
    cs = ap.close_snap(board(PRE, age=CLOSE_AGE, **UP))
    ch = A2.V1.chains(cs, ap.und, ap.lots)

    def view(news, muted):
        ap.news_vote = lambda n, u, t, price, with_globals=True: news
        ap.votes.muted = lambda k, u: muted and k == "news"
        return ap.plan_state(cs, "NIFTY", ch, PRE, None, None, None, None)["view"]
    assert view((0, None, None), False) is None                                                # the closing book and forward alone: two readings, no direction
    assert view((1, "news up", None), False) == "up"                                           # the news as the third reading carries it
    assert view((1, "news up", None), True) is None                                            # muted: it carries nothing, and it is still a reading (never 'flat')
    assert view((-1, "news down", None), True) is None                                         # muted and against: it still stops the others


def test_a_strategy_in_probation_is_not_opened_by_a_live_data_shift_either(cfg, tmp_path):
    """The live board's pool (a strategy the plan did not name, opened on a real shift in the data) skips a strategy in probation too."""
    from tests.test_plan_first import news_desk, rising
    rn, ap, sid = news_desk(cfg, tmp_path)
    rising(rn, ap, 13, cusum_at=8)
    assert any(p.strategy.startswith(f"{A2.TAG} {sid} ") for p in rn.account.positions.values())   # not in probation: the shift opens it
    rn2, ap2, sid2 = news_desk(cfg, tmp_path / "b")
    ap2.probation.st[sid2] = {"g": 6.0, "pend": None, "P": {"since": "2026-11-06", "n": 0, "ses": 0, "sm": 0.0, "mult": 1, "owner": False}, "rel": None, "rep": 0}
    rising(rn2, ap2, 13, cusum_at=8)
    assert not any(p.strategy.startswith(f"{A2.TAG} {sid2} ") for p in rn2.account.positions.values())


def test_the_app_shows_who_is_on_probation_and_which_votes_are_muted():
    from pathlib import Path
    app = (Path(__file__).resolve().parents[1] / "quantdesk/web/static/app/app.js").read_text()
    part = app[app.index("function ppAdapt"):app.index("function ppMarket")]
    assert "lab.probation" in part and "lab.votes" in part and "Adapting" in part and "cannot start one" in part
    assert "ppAdapt(sm.lab)" in app
