"""The hierarchical Bayesian record (AUTO v2's Lab, owner, 13 Nov 2026: "Hierarchical Bayesian models: sharing evidence between similar strategies"). A simulated record
with a known truth: iron condors make +0.15R, long calls lose 0.20R, everything else is worth nothing, and each strategy scatters 0.10R about its family."""
from __future__ import annotations

import math
import random

import pytest

from quantdesk.paper import auto2 as A2

TRUTH = {"IC": 0.15, "LC": -0.20}


def world(seed=3, sizes=(0, 0, 3, 8, 15, 30), spread=0.1):
    rng, stats, theta = random.Random(seed), {}, {}
    for s in A2.CATALOGUE:
        th = TRUTH.get(s.struct, 0.0) + rng.gauss(0, spread)
        theta[s.sid] = th
        n = rng.choice(sizes)
        rs = [th + rng.gauss(0, 1.0) for _ in range(n)]
        if n:
            stats[s.sid] = [n, sum(rs), sum(r * r for r in rs), sum(r > 0 for r in rs)]
    return stats, theta


def test_families_are_recovered_and_the_spread_within_them_is_estimated():
    stats, _ = world()
    f = A2.Lab(stats).fit()
    assert f["tau"] == pytest.approx(0.1, abs=0.08)                                             # DerSimonian-Laird from the record itself
    ic, lc, bcs = f["family"]["IC"][0], f["family"]["LC"][0], f["family"]["BCS"][0]
    assert 0.03 < ic < 0.15 and -0.20 < lc < -0.05 and abs(bcs) < 0.08                          # the right sign, pulled towards zero (the conservative anchor)


def test_a_strategy_with_no_record_starts_from_its_family_and_a_long_record_speaks_for_itself():
    stats, _ = world()
    lab = A2.Lab(stats)
    new_ic = next(s.sid for s in A2.CATALOGUE if s.struct == "IC" and s.sid not in stats)
    new_lc = next(s.sid for s in A2.CATALOGUE if s.struct == "LC" and s.sid not in stats)
    n, m_ic, se_ic = lab.posterior(new_ic)
    assert n == 0 and m_ic > 0 and lab.posterior(new_lc)[1] < 0                                  # a new member inherits its family's record
    assert se_ic > lab.fit()["tau"]                                                             # and all of the family's uncertainty
    long_lc = next(s.sid for s in A2.CATALOGUE if s.struct == "LC")
    st = dict(stats)
    st[long_lc] = [400, 0.5 * 400, 400 * (0.25 + 1.0), 260]                                     # a long call that has truly made +0.5R over 400 trades
    assert A2.Lab(st).posterior(long_lc)[1] > 0.4                                               # its family's losses do not drown 400 trades of its own


def test_sharing_beats_each_strategy_alone_on_short_records():
    err_h = err_raw = 0.0
    k = 0
    for seed in range(4):
        stats, theta = world(seed, sizes=(3, 5, 8))
        lab = A2.Lab(stats)
        for sid, (n, s, _, _) in stats.items():
            err_h += (lab.posterior(sid)[1] - theta[sid]) ** 2
            err_raw += (s / n - theta[sid]) ** 2
            k += 1
    assert err_h / k < 0.25 * err_raw / k                                                       # shrinkage: a fraction of the raw means' error (Stein's lesson)


def test_correlated_members_are_not_counted_as_independent_evidence():
    stats, _ = world()
    f = A2.Lab(stats).fit()
    mu, var, m, trades = f["family"]["IC"]
    naive = 1 / math.sqrt(trades)                                                               # what 2,000 independent unit-variance trades would claim
    assert math.sqrt(var) > 5 * naive                                                           # the design effect keeps the family honest
    assert A2.Lab({}).posterior(next(iter(A2.BY_SID)))[1] == 0.0                                # no record anywhere: zero edge


def test_the_record_refits_when_it_changes_and_the_summary_shows_the_families():
    lab = A2.Lab()
    sid = next(s.sid for s in A2.CATALOGUE if s.struct == "IF")
    before = lab.posterior(sid)
    for _ in range(30):
        lab.add(sid, 0.6)
    after = lab.posterior(sid)
    assert after[0] == 30 and after[1] > before[1] + 0.2
    sm = lab.summary()
    assert sm["families"][0]["struct"] == "IF" and sm["families"][0]["members"] == 1 and "tau" in sm
