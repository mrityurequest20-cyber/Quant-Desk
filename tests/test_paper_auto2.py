"""AUTO v2 (quantdesk/paper/auto2.py): the paper desk writing, testing and choosing its own strategies. PAPER MONEY ONLY.

What is pinned: the catalogue is every combination and each id is unique and says what it is; every structure's worst case is bounded; realized volatility is measured right; the shadow
book trades every matching strategy at the real bid and offer and scores it in R; nothing trades with paper money before MIN_TRADES shadow trades and a positive Thompson draw; a live
structure goes as ONE package through the REAL runner and risk gate; its own exits close it with sold legs bought back first; the record survives a restart through the relay."""
from __future__ import annotations

import datetime as dt
import json
import math
import random
import shutil
import subprocess
from pathlib import Path

import pytest

from quantdesk.config import Config
from quantdesk.core.calendar import TradingCalendar
from quantdesk.markets import sessions as MK
from quantdesk.paper import auto2 as A2
from quantdesk.paper import runner as R
from quantdesk.paper.account import Account
from quantdesk.paper.risk import KillSwitch, RiskGate
from quantdesk.paperlink.cli import auto_v2
from tests.test_paper_auto import SPOT, T0, board

ROOT = Path(__file__).resolve().parents[1]
IST = MK.IST
needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="Node is not installed")
IC = "IC1.faan.1/0.5.d"                     # iron condor, one strike wide, flat view, any volatility, any day, the near expiry, take profit 1R, stop 0.5R, out by the close


@pytest.fixture()
def cfg():
    return Config.load(ROOT / "config" / "quantdesk.yaml")


def desk(cfg, tmp_path, stats=None, seed=1, plan_only=False):
    rn = R.Runner(cfg, Account(500_000), gate=RiskGate(cfg, kill=KillSwitch(tmp_path / "K")), kill_file=tmp_path / "K")
    ap = auto_v2(cfg, ("NIFTY",), {"NIFTY": 65})
    ap.rng = random.Random(seed)
    ap.plan_only = plan_only                    # these tests drive the intraday mechanics; live trading takes only the plan (PLAN_ONLY, tests/test_plan_first.py)
    if stats is not None:
        ap.lab = A2.Lab(stats)
    return rn, ap


def cycle(rn, ap, snap, now):
    srv = R.Runner.server_now(snap)
    mine = ap.decide(snap, rn.account, srv)
    rep = rn.step(snap, mine, False, now.astimezone(dt.timezone.utc))
    return mine, rep


def calm(rn, ap, t0=T0, minutes=6):
    """A quiet tape: no direction and a five-minute move under CALM_PCT, so the view is FLAT."""
    t = t0
    for i in range(minutes + 1):
        t = t0 + dt.timedelta(minutes=i)
        cycle(rn, ap, board(t), t)
    return t


# ---- the catalogue ----------------------------------------------------------------------------------------------------------------------------
def test_the_catalogue_is_every_combination_with_unique_readable_ids():
    assert len(A2.CATALOGUE) == len({s.sid for s in A2.CATALOGUE}) == 3654 + 504                # (9 up + 9 down + 11 flat structure-widths) x 3 vols x 3 timings x (6 exits x 2
    #                                                                                             holds + 2 overnight take-profits), and calendars and diagonals (6 structure-widths, near
    #                                                                                             expiry only: 2 timings)
    assert all(A2.BY_SID[s.sid] is s for s in A2.CATALOGUE)                                     # BY_SID also holds what the inventor writes (test_inventor.py)
    assert {s.view for s in A2.CATALOGUE} == {"up", "down", "flat"} and all(len(s.sid) <= 22 for s in A2.CATALOGUE)
    s = A2.BY_SID[IC]
    assert (s.struct, s.width, s.view, s.vol, s.timing, s.expiry, s.tp, s.sl, s.hold) == ("IC", 1, "flat", "any", "any", "near", 1.0, 0.5, "day")
    assert "iron condor 1-strike, near expiry, when the view is flat" in s.describe()
    for s in A2.CATALOGUE:                                                                      # a structure's view decides the contexts it can trade in
        assert A2.STRUCTURES[s.struct][0] == s.view
        assert len(f"{A2.TAG} {s.sid} BAJAJ-AUTO") <= 60                                         # the strategy text, with the longest underlying, fits the runner's 60 characters


def test_every_structure_has_a_bounded_worst_case_and_the_bounds_are_right():
    strikes = list(range(24100, 24901, 50))                                                      # the at-the-money strike 24500 and 8 either side (a broken wing reaches 5)
    near, nxt = dt.date(2026, 11, 12), dt.date(2026, 11, 19)
    for s in A2.CATALOGUE:
        lg = A2.legs_for(s, strikes, 8, (strikes, 8))                                            # a calendar's later legs on the next expiry's board (the same strikes here)
        assert lg is not None, s.sid
        if A2.is_multi(s.struct):
            worst = A2.multi_expiry_worst([(l[2], l[1], l[0], nxt if len(l) > 3 else near) for l in lg])
            assert worst is not None and math.isfinite(worst), s.sid                               # the later long covers the near sale
            continue
        worst, best = A2.payoff_bounds([(side, r, k, 10.0) for side, r, k in lg])
        assert math.isfinite(worst), s.sid                                                       # a sold option is only ever a leg of a bounded structure
    assert A2.payoff_bounds([(1, "CE", 100, 5.0), (-1, "CE", 110, 2.0)]) == (-3.0, 7.0)          # a bull call spread paid 3: lose 3, make 7
    assert A2.payoff_bounds([(-1, "PE", 100, 3.0), (1, "PE", 90, 1.0)]) == (-8.0, 2.0)           # a bull put spread for a credit of 2
    assert A2.payoff_bounds([(1, "CE", 100, 4.0), (1, "PE", 100, 4.0)]) == (-8.0, math.inf)      # a straddle: no cap on the gain
    ic = A2.legs_for(A2.BY_SID[IC], strikes, 8)
    assert ic == [(-1, "CE", 24550), (1, "CE", 24600), (-1, "PE", 24450), (1, "PE", 24400)]


def test_realized_volatility_is_annualized_from_one_minute_returns():
    rng, px, tape = random.Random(3), 100.0, []
    sigma = 0.20                                                                                 # 20% a year over 6.25-hour sessions
    per_min = sigma / math.sqrt(252 * 6.25 * 60)
    for i in range(90):
        tape.append((i * 60.0, px))
        px *= math.exp(rng.gauss(0, per_min))
    rv = A2.realized_vol(tape, 89 * 60.0)
    assert rv == pytest.approx(0.20, rel=0.3)
    assert A2.realized_vol(tape[:10], 9 * 60.0) is None                                        # too few points to say


# ---- the shadow book ------------------------------------------------------------------------------------------------------------------------
def test_on_a_calm_board_every_flat_strategy_is_traded_in_shadow_and_nothing_goes_live_without_a_record(cfg, tmp_path):
    rn, ap = desk(cfg, tmp_path)
    t = calm(rn, ap)
    st = ap.last_state["NIFTY"]
    assert st["view"] == "flat" and st["near"] == "2026-11-12" and st["eve"] is False
    opened = {sid for sid, u in ap.shadow}
    assert opened and all(A2.BY_SID[sid].view == "flat" for sid in opened)
    assert all(A2.BY_SID[sid].vol in ("any", st["vol"]) for sid in opened) and all(A2.BY_SID[sid].expiry == "near" for sid in opened)    # no "next" expiry on this board
    assert not rn.account.ledger and ap.lab.today["live_entries"] == 0                           # no record yet: shadow only


def test_a_shadow_trade_is_closed_by_its_own_exit_at_real_prices_and_scored_in_r(cfg, tmp_path):
    rn, ap = desk(cfg, tmp_path)
    t = calm(rn, ap)
    sh = ap.shadow[(IC, "NIFTY")]
    assert sh["risk"] > 0 and all(l["px"] == (l["ask"] if l["side"] > 0 else l["bid"]) for l in sh["legs"])     # a buy at the offer, a sale at the bid
    later = dt.datetime.combine(T0.date(), dt.time(15, 16), tzinfo=IST)                            # a "day" strategy is out by 15:15
    cycle(rn, ap, board(later), later)
    assert (IC, "NIFTY") not in ap.shadow and ap.lab.stats[IC][0] == 1
    n, s, ss, w = ap.lab.stats[IC]
    assert -1.0 < s < 0.5                                                                        # crossing the spread twice and paying the fees: a small loss in R, as it should be


# ---- live -----------------------------------------------------------------------------------------------------------------------------------
def proven(sid=IC, n=20, mean=0.6):
    return {sid: [n, mean * n, (mean * mean + 0.25) * n, int(0.7 * n)]}


def test_a_proven_strategy_goes_live_as_one_package_through_the_real_gate(cfg, tmp_path):
    rn, ap = desk(cfg, tmp_path, stats=proven())
    t = calm(rn, ap, minutes=4)                                                                  # four minutes: the view is not yet known (it needs a five-minute move)
    assert not rn.account.ledger
    t = t + dt.timedelta(minutes=1)
    mine, rep = cycle(rn, ap, board(t), t)
    live = [o for o in mine if o.get("group") == "auto2"]
    assert len(live) == 1 and live[0]["side"] == "package" and live[0]["strategy"] == f"{A2.TAG} {IC} NIFTY"
    assert [l["side"] for l in live[0]["legs"]] == ["sell", "buy", "sell", "buy"] and all(l["lots"] == 1 for l in live[0]["legs"])
    res = next(r for r in rep["results"] if r["id"] == live[0]["id"])
    assert res["status"] == "filled", res
    assert len(rn.account.positions) == 4 and all(p.strategy == f"{A2.TAG} {IC} NIFTY" for p in rn.account.positions.values())
    assert "Shadow record 20 trades" in next(iter(rn.account.positions.values())).thesis
    mine2, _ = cycle(rn, ap, board(t + dt.timedelta(seconds=90)), t + dt.timedelta(seconds=90))
    assert not [o for o in mine2 if o.get("side") == "package"]                                  # one package per strategy and underlying at a time


def test_a_short_or_losing_record_never_trades_with_paper_money(cfg, tmp_path):
    for stats in (proven(n=A2.MIN_TRADES - 1), proven(mean=-0.8)):
        rn, ap = desk(cfg, tmp_path, stats=stats)
        t = calm(rn, ap, minutes=6)
        assert not rn.account.ledger and ap.lab.today["live_entries"] == 0, stats


def test_its_own_exit_closes_the_package_with_the_sold_legs_bought_back_first(cfg, tmp_path):
    rn, ap = desk(cfg, tmp_path, stats=proven())
    t = calm(rn, ap, minutes=6)
    assert len(rn.account.positions) == 4
    late = dt.datetime.combine(T0.date(), dt.time(15, 16), tzinfo=IST)
    mine, rep = cycle(rn, ap, board(late), late)
    exits = [o for o in mine if o["side"] == "sell"]
    assert len(exits) == 4 and [rn.account.ledger[-4 + i]["kind"] for i in range(4)] == ["btc", "btc", "sell", "sell"]      # bought back first, then the wings sold
    assert not rn.account.positions


def test_the_kill_switch_and_a_blocked_relay_stop_entries_but_not_exits(cfg, tmp_path):
    rn, ap = desk(cfg, tmp_path, stats=proven())
    calm(rn, ap, minutes=4)
    t = T0 + dt.timedelta(minutes=5)                                                             # the cycle that would have entered
    snap = board(t)
    assert not [o for o in ap.decide(snap, rn.account, R.Runner.server_now(snap), kill=True) if o["side"] != "sell"]
    assert not [o for o in ap.decide(snap, rn.account, R.Runner.server_now(snap), entries_blocked="x") if o["side"] != "sell"]


# ---- the record ------------------------------------------------------------------------------------------------------------------------------
class FakeRelay:
    def __init__(self, lab=None):
        self.lab, self.puts = lab, 0

    def get_lab(self):
        return {"lab": self.lab}

    def put_lab(self, text):
        self.lab, self.puts = text, self.puts + 1
        return {"saved": True}


def test_the_record_is_saved_at_most_every_two_minutes_and_read_back_validated(cfg, tmp_path):
    rn, ap = desk(cfg, tmp_path)
    relay = FakeRelay()
    ap.lab.add(IC, 0.4)
    assert ap.save(relay, 1000.0) and not ap.save(relay, 1060.0)                                   # unchanged: nothing sent
    ap.lab.add(IC, -0.2)
    assert not ap.save(relay, 1060.0) and ap.save(relay, 1121.0) and relay.puts == 2
    ap2 = desk(cfg, tmp_path)[1]
    assert "1 strategies" in ap2.load(relay) and ap2.lab.stats[IC][0] == 2
    bad = json.dumps({"v": 1, "stats": {IC: [3, 1.0, 1.0, 2], "NOPE": [1, 1, 1, 1], "LC0.uran.0.5/0.5.d": [1, "x", 1, 1], "LP0.dran.0.5/0.5.d": [-1, 0, 0, 0]}})
    ap3 = desk(cfg, tmp_path)[1]
    ap3.load(FakeRelay(bad))
    assert set(ap3.lab.stats) == {IC}                                                            # unknown, malformed and negative entries are dropped: storage is not trusted
    ap4 = desk(cfg, tmp_path)[1]
    assert "starting from zero" in ap4.load(FakeRelay("{not json")) and ap4.lab.stats == {}
    big = A2.Lab({s.sid: [1000, 1.0, 1.0, 500] for s in A2.CATALOGUE})
    assert len(big.to_json()) <= A2.LAB_MAX_CHARS + 50                                           # the relay keeps it in one stored value


def test_the_session_loads_and_saves_the_record_and_puts_the_lab_in_the_apps_state():
    src = (ROOT / "quantdesk/paperlink/session.py").read_text()
    assert 'auto.load(relay)' in src and "auto.save(relay, time.monotonic())" in src and "auto.save(relay, time.monotonic(), force=True)" in src
    assert 'summ["lab"] = auto.summary()' in src
    cli = (ROOT / "quantdesk/paperlink/cli.py").read_text()
    assert 'os.environ.get("PAPER_AUTO_ENGINE", "v2")' in cli and "auto = auto_v2(cfg, tradable + tuple(segs), lots_all, segs)" in cli         # v2 is the engine unless PAPER_AUTO_ENGINE=v1


@needs_node
def test_the_relay_keeps_the_record_for_the_runners_key_only_bounded_and_ascii(tmp_path):
    for f in ("paper.js",):
        shutil.copyfile(ROOT / "deploy/cloudflare" / f, tmp_path / f)
    (tmp_path / "package.json").write_text('{"type": "module"}')
    (tmp_path / "t.mjs").write_text("""import { PaperBook, MAX_LAB } from './paper.js';
const store = new Map();
const state = { storage: { get: async (k) => (Array.isArray(k) ? new Map() : store.get(k)), put: async (k, v) => { if (typeof k === "object") for (const [a, b] of Object.entries(k)) store.set(a, b); else store.set(k, v); } } };
const b = new PaperBook(state);
const call = async (m, body) => { const r = await b.handle(new Request("https://live/paper/lab", { method: m, ...(body ? { body: JSON.stringify(body) } : {}) }), new URL("https://live/paper/lab"), 1); return [r.status, await r.json()]; };
const out = {};
out.empty = await call("GET");
out.ok = await call("POST", { lab: JSON.stringify({ v: 1, stats: { a: [1, 0.5, 0.25, 1] } }) });
out.back = await call("GET");
out.big = await call("POST", { lab: JSON.stringify({ v: 1, stats: {}, pad: "x".repeat(MAX_LAB) }) });
out.wide = await call("POST", { lab: JSON.stringify({ v: 1, stats: { "\\u00e9": [1, 1, 1, 1] } }).replace("\\\\u00e9", "\\u00e9") });
out.shape = await call("POST", { lab: JSON.stringify({ v: 2, stats: {} }) });
console.log(JSON.stringify(out));""")
    r = subprocess.run(["node", "t.mjs"], cwd=tmp_path, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr[-1500:]
    o = json.loads(r.stdout)
    assert o["empty"] == [200, {"lab": None, "now": 1}] and o["ok"][0] == 200 and json.loads(o["back"][1]["lab"])["stats"]["a"] == [1, 0.5, 0.25, 1]
    assert o["big"][0] == 400 and o["wide"][0] == 400 and o["shape"][0] == 400
    live = (ROOT / "deploy/cloudflare/live.js").read_text()
    assert '"POST /paper/lab": "ingest", "GET /paper/lab": "ingest"' in live                       # the runner's key only: the app's key cannot read or write the record


def test_the_whole_catalogue_fits_the_relay_compressed_and_a_bad_record_is_refused(cfg, tmp_path):
    import base64
    import random as _r
    import zlib
    rng = _r.Random(1)
    lab = A2.Lab()
    for s in A2.CATALOGUE + A2.CX_CATALOGUE:                                                       # every strategy with a record: plain JSON would hold about 2,600 of them
        for _ in range(rng.randint(1, 30)):
            lab.add(s.sid, rng.gauss(0, 1))
    text = lab.to_json({"read_w": {}})
    assert len(text) <= A2.LAB_MAX_CHARS and json.loads(text)["v"] == 1 and json.loads(text)["stats"] == {} and "z" in json.loads(text)
    assert text.isascii()                                                                        # the relay's own checks: v, stats an object, ASCII
    relay = FakeRelay(text)
    ap = desk(cfg, tmp_path)[1]
    assert f"{len(lab.stats)} strategies" in ap.load(relay) and ap.lab.stats == {k: [v[0], round(v[1], 4), round(v[2], 4), v[3]] for k, v in lab.stats.items()}
    small = A2.Lab({IC: [3, 1.0, 1.0, 2]}).to_json()
    assert "z" not in json.loads(small)                                                          # a record that fits stays plain
    bomb = base64.b64encode(zlib.compress(b"{}" + b" " * (A2.LAB_MAX_INFLATED + 10))).decode()   # cut at the bound it would still parse: only the bound refuses it
    ap2 = desk(cfg, tmp_path)[1]
    assert "starting from zero" in ap2.load(FakeRelay(json.dumps({"v": 1, "stats": {}, "z": bomb}))) and ap2.lab.stats == {}
    ap3 = desk(cfg, tmp_path)[1]
    assert "starting from zero" in ap3.load(FakeRelay(json.dumps({"v": 1, "stats": {}, "z": "not base64!"})))


def test_todays_plan_survives_a_restart_and_yesterdays_does_not(cfg, tmp_path):
    rn, ap = desk(cfg, tmp_path)
    ap.day_plan = {"built_at": T0.date().isoformat() + "T07:30+05:30", "items": [{"u": "NIFTY", "sid": IC, "risk_unit": 10.0, "spot": 24500.0},
                                                                                  {"u": "NIFTY", "sid": "NOPE", "risk_unit": 10.0, "spot": 24500.0},
                                                                                  {"u": "NIFTY", "sid": IC, "risk_unit": "x", "spot": 24500.0},
                                                                                  {"u": "NIFTY", "sid": IC, "risk_unit": 10.0},
                                                                                  {"u": "NIFTY", "sid": IC, "risk_unit": 10.0, "spot": 24500.0, "event_at": "soon"},
                                                                                  {"u": "NIFTY", "sid": IC, "risk_unit": 10.0, "spot": 24500.0, "event_at": 20261114},
                                                                                  {"u": "NIFTY", "sid": IC, "risk_unit": True, "spot": 24500.0},
                                                                                  {"u": "NIFTY", "sid": IC, "risk_unit": float("nan"), "spot": 24500.0},
                                                                                  {"u": "NIFTY", "sid": IC, "risk_unit": -1.0, "spot": 24500.0},
                                                                                  {"u": 7, "sid": IC, "risk_unit": 10.0, "spot": 24500.0}],
                   "states": {"NIFTY": {"view": "up"}}, "notes": []}
    ap.lab.add(IC, 0.3)
    relay = FakeRelay()
    assert ap.save(relay, 1000.0)
    ap2 = desk(cfg, tmp_path)[1]
    ap2.load(relay)
    assert ap2.day_plan and [i["sid"] for i in ap2.day_plan["items"]] == [IC] and ap2.planned("NIFTY") == [IC]     # an unknown strategy, a bad price, no spot, a bad time: dropped
    many = {"built_at": T0.date().isoformat() + "T07:30+05:30", "items": [{"u": "NIFTY", "sid": IC, "risk_unit": 10.0, "spot": 24500.0}] * (A2.PLAN_TOP + 5)}
    assert len(A2.AutoPilotV2.restore_plan(many)["items"]) == A2.PLAN_TOP                       # no longer than a plan the desk builds itself
    assert ap2.day_plan["states"]["NIFTY"]["view"] == "up"
    cycle(rn, ap2, board(T0), T0)
    assert ap2.day_plan is not None                                                              # the same day: it steers the session
    ap3 = desk(cfg, tmp_path)[1]
    ap3.load(relay)
    nxt = T0 + dt.timedelta(days=2)
    cycle(rn, ap3, board(nxt), nxt)
    assert ap3.day_plan is None or not str(ap3.day_plan.get("built_at", "")).startswith(T0.date().isoformat())   # another day: never
    assert A2.AutoPilotV2.restore_plan({"built_at": "not a date", "items": []}) is None and A2.AutoPilotV2.restore_plan("x") is None
