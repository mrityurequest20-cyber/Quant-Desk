"""Instruments read differently (owner, 13 Nov 2026: "Models should read differently as per the instrument as these instruments are different"): the market read's class
profiles and per-instrument learned weights (quantdesk/paper/marketread.py), and AUTO v2's thresholds in each instrument's own volatility."""
from __future__ import annotations

import json
import random

from quantdesk.paper import auto2 as A2
from quantdesk.paper import marketread as MR
from tests.test_paper_auto2 import FakeRelay


def test_each_class_reads_the_same_board_its_own_way():
    cur = {"spot": 100.0, "pcr": 0.6}
    idx = MR.MarketRead.evidence(cur, None, MR.PROFILES["index"], MR.PCR_BASE["index"])
    stk = MR.MarketRead.evidence(cur, None, MR.PROFILES["stock"], MR.PCR_BASE["stock"])
    assert idx["p_up"] < 0.5 and stk["p_up"] == 0.5                                              # 0.6 is bearish for an index, ordinary for a stock
    then = {"spot": 100.0, "basis": 0.0010}
    now = {"spot": 100.0, "basis": 0.0030}
    assert MR.MarketRead.evidence(now, then, MR.PROFILES["index"])["p_up"] > 0.5
    assert MR.MarketRead.evidence(now, then, MR.PROFILES["cds"])["p_up"] == 0.5                  # a currency future's premium is carry, not sentiment
    assert set(MR.PROFILES) == {"index", "stock", "mcx", "cds"} and all(set(w) == set(MR.WEIGHTS) for w in MR.PROFILES.values())


def test_auto_v2_names_each_instruments_class():
    ap = A2.AutoPilotV2(("NIFTY", "SBIN", "CRUDEOIL", "USDINR"), {}, lambda *a: 0.0, None, segments={"CRUDEOIL": "mcx", "USDINR": "nse_cds"})
    assert [ap.profile(u) for u in ap.und] == ["index", "stock", "mcx", "cds"]


def test_an_instrument_learns_its_own_weights_and_a_reversed_signal_flips():
    mr = MR.MarketRead(lookback_s=900)
    mr.profile["X"] = "index"
    rng = random.Random(2)
    for i in range(600):                                                                         # here a high put/call ratio comes before FALLS (the prior says rises)
        s = rng.choice((-1.0, 1.0))
        p = 1 / (1 + 2.718281828 ** -(mr.weights("X")["pcr"] * s))
        mr.learn("X", {"pcr": s}, p, 0.0 if s > 0 else 1.0)
    assert mr.weights("X")["pcr"] < 0 < MR.PROFILES["index"]["pcr"] and mr.learned["X"] == 600
    assert mr.weights("Y")["pcr"] == MR.PROFILES["index"]["pcr"]                                 # another instrument is untouched


def test_learning_takes_one_outcome_per_window_not_every_overlapping_read():
    mr = MR.MarketRead(lookback_s=900)
    mr.profile["X"] = "index"
    for k in range(0, 3600, 30):                                                                 # a read every 30 seconds for an hour, the price rising
        mr._score("X", float(k), 100.0 + k / 100, 0.6, {"pcr": 0.5})
    assert 2 <= mr.learned["X"] <= 4 and mr.calibration()["X"]["n"] > 20                        # scored every minute, learned from once a window


def test_what_was_learned_survives_a_restart_validated(tmp_path):
    from tests.test_paper_auto2 import desk
    from quantdesk.config import Config
    from pathlib import Path
    cfg = Config.load(Path(__file__).resolve().parents[1] / "config" / "quantdesk.yaml")
    _, ap = desk(cfg, tmp_path)
    ap.reader, ap.read_at = MR.MarketRead(), {}
    ap.reader.profile["NIFTY"] = "index"
    ap.reader.learn("NIFTY", {"pcr": 1.0}, 0.5, 0.0)
    ap.lab.add("IC1.faan.1/0.5.d", 0.2)
    relay = FakeRelay()
    assert ap.save(relay, 1000.0, force=True)
    saved = json.loads(relay.lab)["read_w"]
    assert saved["NIFTY"]["n"] == 1 and saved["NIFTY"]["w"]["pcr"] < MR.PROFILES["index"]["pcr"]
    _, ap2 = desk(cfg, tmp_path)
    ap2.load(relay)
    assert ap2._read_w == saved
    mr = MR.MarketRead()
    assert mr.restore({"NIFTY": {"p": "index", "n": 1, "w": {"pcr": 99.0, "made_up": 1.0}}, "BAD": {"p": "nonsense", "w": {"pcr": 0.1}}}) == 0
    assert mr.restore(saved) == 1 and mr.weights("NIFTY")["pcr"] == saved["NIFTY"]["w"]["pcr"]


def test_a_move_is_measured_in_the_instruments_own_volatility():
    rg = {"trend": None, "vote": 0, "change": None}
    sd5_usdinr, sd5_gas = 0.02, 0.40                                                              # in %: a quiet currency and a wild commodity
    assert A2.AutoPilotV2.price_vote(0.06, rg, sd5_usdinr)[1][0] == 1                             # 0.06% is three of USD/INR's five-minute sd: a move
    assert A2.AutoPilotV2.price_vote(0.30, rg, sd5_gas) == (None, None)                           # 0.30% is noise for natural gas
    assert "of its five-minute sd" in A2.AutoPilotV2.price_vote(-0.06, rg, sd5_usdinr)[1][1]
    assert A2.AutoPilotV2.price_vote(0.12, rg, None) == (0.12, None)                              # no volatility yet: AUTO v1's fixed threshold
    assert abs(0.12 * A2.SD5_FROM_ANNUAL * 100 * A2.CALM_K - 0.10) < 0.01                         # set so that NIFTY at 12% a year keeps its 0.10% calm line


def test_the_lab_state_stays_inside_the_relays_cap_on_a_busy_day():
    import datetime as dt
    from tests.test_lab_hierarchy import world
    ap = A2.AutoPilotV2(tuple(f"U{i:02d}LONGNAME" for i in range(37)), {}, lambda *a: 0.0, None, seed=2)
    ap.lab = A2.Lab(world()[0])
    for d in range(12):
        ap.evolve(dt.date(2026, 11, 1) + dt.timedelta(days=d))
    for u in ap.und:
        ap.last_state[u] = {"view": "flat", "vol": "rich", "ratio": 1.2, "eve": True, "read": {"p_up": 0.71, "why": ["x" * 80, "y" * 80]}, "event": "e" * 160,
                            "hmm": "stressed", "change": "volatility up", "trend_t": -2.3, "tail": "1-day 99% ES -12.3% / +11.9%", "news": {"p_up": 0.71, "why": ["n" * 100] * 2}}
    ap.day_plan = {"items": [{"what": "w" * 160, "why": ["y" * 80] * 3, "catalysts": ["c" * 90] * 4, "legs": ["NIFTY12NOV2624500CE"] * 4} for _ in range(10)],
                   "notes": ["n" * 200] * 4}
    sm = ap.summary()
    assert len(json.dumps(sm, separators=(",", ":"))) <= A2.SUMMARY_SOFT_MAX
    assert all(v[11] == 0.71 and v[12] == "" for v in sm["state"].values())                    # the reasons went, the numbers stayed
