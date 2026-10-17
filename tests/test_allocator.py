"""The allocator (intraday/allocator.py, docs/prereg/allocator_v1.json), PHASE 1: SHADOW ONLY. It journals what it would carry
(never touching the paper account: it holds read-only views), sizes to at most 2.5% of equity inside every desk limit,
never allocates a naked or ineligible sleeve, prices all four legs from real quotes or nothing, and refuses a weekend, a
holiday or anything but the sleeve's own next-day expiry. `apply` is not implemented: it runs as shadow."""
import copy
import datetime as dt
import json
from pathlib import Path

import pandas as pd
import pytest

from quantdesk.config import DEFAULT_CONFIG, Config
from quantdesk.core.types import Instrument, Order
from quantdesk.intraday import allocator as A
from quantdesk.intraday.engine import DD_KEY, DD_PEAK_KEY
from quantdesk.intraday.halt import HALT_KEY
from quantdesk.intraday.recorder import SessionRecorder
from quantdesk.intraday.sim import IntradayBroker
from quantdesk.intraday.sleeves import ExpirySeller
from quantdesk.journal.journal import Journal
from test_sleeves import at, closing_bars, eve, snapshot

IST = "Asia/Kolkata"
EQUITY = 500000.0
SPEC = A.load_spec()


class World:
    """An eve with a real-quote snapshot at 15:20, the sleeves' own open for it, and a paper account that has traded the
    day: every state the allocator's gates read is set, so a test breaks exactly one thing."""

    def __init__(self, cfg, tmp_path, depth=None, history=10, mode="shadow", equity=EQUITY, files=False):
        self.cfg = cfg.with_overrides({"intraday": {"allocator": {"mode": mode}}})
        self.cal, self.d, self.e = eve(cfg)
        self.data, self.root = tmp_path / "data", tmp_path / "sleeves"
        self.seller = ExpirySeller(self.cfg, self.root, self.data, say=lambda *a: None)
        self.history(history)
        ch = snapshot(self.cfg, self.cal, self.data, self.d, self.e, "1520")
        if depth is not None:                                   # size resting at the touch, in units, for every leg
            ch["ce_bidq"] = ch["ce_askq"] = ch["pe_bidq"] = ch["pe_askq"] = float(depth)
            SessionRecorder(self.data).record_chain(ch)
        self.seller.run(self.d, now=at(self.d, "15:40"))
        if files:                                               # the account as the workflow keeps it, for a later session to open
            self.journal = Journal(tmp_path / "journal.db")
            self.broker = IntradayBroker(self.cfg, starting_cash=equity, state_path=tmp_path / "broker.json")
        else:
            self.journal, self.broker = Journal(), IntradayBroker(self.cfg, starting_cash=equity)
        self.account(equity)
        self.now = at(self.d, "15:40")

    def account(self, equity, start=None, peak=None, **live):
        self.journal.set_state("intraday_live", {"day": str(self.d), "day_start_equity": start or equity, "equity": equity,
                                                 "paused": False, "halts": {}, **live})
        self.journal.set_state(DD_PEAK_KEY, {"peak": peak or equity})
        self.journal.set_state("intraday_account", {"capital": EQUITY})

    def history(self, n, sleeve="A", cost_gap=0.0, pnl=118.0):
        """n settled forward trades of the sleeve on NIFTY that make it eligible under its own spec."""
        for k in range(n):
            exp = dt.date(2026, 3, 3) + dt.timedelta(days=7 * k)
            i = f"{sleeve}-NIFTY-{exp}"
            self.seller._append({"event": "open", "id": i, "sleeve": sleeve, "strategy": "iron_condor_20_10", "underlying": "NIFTY",
                                 "expiry": str(exp), "day": str(exp - dt.timedelta(days=1)), "lot": 65, "legs": [],
                                 "cost_gap_rs": cost_gap, "max_loss_rs": 20000.0})
            self.seller._append({"event": "settle", "id": i, "settle": 22600.0, "pnl_rs": pnl, "stt_rs": 0.0})

    def alloc(self, mode=None, broker=None, journal=None):
        cfg = self.cfg if mode is None else self.cfg.with_overrides({"intraday": {"allocator": {"mode": mode}}})
        return A.Allocator(cfg, [self.seller], journal or self.journal, broker or self.broker, self.root, say=lambda *a: None)

    def decisions(self):
        return [e for e in self.alloc().events() if e["event"] == "decision"]

    def one(self, mode="shadow"):
        a = self.alloc(mode)
        a.run(self.d, self.now)
        return [e for e in a.events() if e["event"] == "decision" and e.get("sleeve") == "A"][0]

    def seed_shadow_sessions(self, n=5):
        """n earlier shadow sessions on the allocator's ledger: what lets apply take effect."""
        for k in range(n):
            day = self.d - dt.timedelta(days=30 + k)
            self.alloc()._append({"event": "decision", "status": "would_place", "mode": "shadow", "day": str(day), "eve": str(day),
                                  "sleeve_trade": f"X-{k}", "expiry": str(day + dt.timedelta(days=1)), "sizing": {"max_loss": 1, "margin": 1}})


@pytest.fixture
def w(cfg, tmp_path):
    return World(cfg, tmp_path)


def paper_state(w):
    """Everything in the paper account a placement could touch."""
    j = w.journal
    return (w.broker.cash(), copy.deepcopy(w.broker.positions()), len(w.broker.fills), w.broker.fees_paid,
            j.df("SELECT COUNT(*) AS n FROM trades")["n"].iloc[0], j.df("SELECT COUNT(*) AS n FROM fills")["n"].iloc[0],
            j.df("SELECT COUNT(*) AS n FROM decisions")["n"].iloc[0], json.dumps(j.get_state("overnight_carry")),
            json.dumps(j.get_state("intraday_open")))


# ---- the spec and the config ---------------------------------------------------------------------------------------------
def test_the_ceilings_in_the_spec_are_the_owners_numbers():
    c = SPEC["limits"]
    assert c["max_loss_per_position"]["ceiling"] == 0.025 and c["max_trades_per_day"]["ceiling"] == 4
    assert c["max_open"]["ceiling"] == 2 and c["daily_loss"]["ceiling"] == 0.05
    assert c["max_total_outlay"]["ceiling"] == 0.5 and c["cross_day_drawdown_halt"]["ceiling"] == 0.10
    assert "4%" in SPEC["supersedes"]["backlog_item_9"] and "2.5%" in SPEC["supersedes"]["backlog_item_9"]
    assert f"at least {A.SHADOW_SESSIONS_REQUIRED} distinct sessions" in SPEC["mode"]["values"]["apply"]


def test_the_sleeve_specs_are_the_ones_the_allocator_was_registered_against():
    from quantdesk.intraday.sleeves import load_spec, sleeve_table
    for a in SPEC["sleeves"]["allowed"]:
        s = load_spec(A.PREREG / f"{a['spec']}.json")
        assert s["_hash"] == a["spec_sha256_12"]
        t = sleeve_table(s)[a["sleeve"]]
        assert not t["naked"] and t["strategy"] == a["strategy"] and set(a["underlyings"]) <= {"NIFTY", "BANKNIFTY"}
        assert set(a["underlyings"]) <= set(t["underlyings"])


def test_the_config_ships_in_shadow_and_anything_unknown_is_shadow():
    cfg = Config.load(DEFAULT_CONFIG)
    assert cfg.get("intraday.allocator.mode") == "shadow" and A.settings(cfg)["mode"] == "shadow"
    assert cfg.get("account.mode") == "paper"
    for bad in (None, "", "APPLYY", "on", 1):
        assert A.settings(cfg.with_overrides({"intraday": {"allocator": {"mode": bad}}}))["mode"] == "shadow"
    assert A.settings(cfg.with_overrides({"intraday": {"allocator": {"mode": "OFF"}}}))["mode"] == "off"
    assert A.settings(Config({}))["mode"] == "shadow"                      # no section at all


def test_limits_are_never_looser_than_the_config_or_the_ceiling(cfg):
    base = A.limits(cfg, SPEC)
    assert (base["risk_per_trade"], base["max_trades"], base["max_open"], base["daily_loss"], base["max_exposure"],
            base["dd_halt"]) == (0.025, 4, 2, 0.05, 0.5, 0.10)
    loose = cfg.with_overrides({"intraday": {"risk": {"risk_per_trade": 0.04, "max_trades_per_day": 9, "max_open": 5,
                                                    "daily_loss_limit": 0.2, "max_total_outlay": 0.9, "max_margin": 0.9,
                                                    "cross_day_drawdown_halt": 0.5, "max_lots": 50}}})
    assert A.limits(loose, SPEC) == base | {"max_lots": 2, "max_margin": 0.5}   # the ceilings hold; a looser desk changes nothing
    tight = cfg.with_overrides({"intraday": {"risk": {"risk_per_trade": 0.01, "max_trades_per_day": 1, "max_open": 1,
                                                     "daily_loss_limit": 0.02, "cross_day_drawdown_halt": 0.05}}})
    t = A.limits(tight, SPEC)
    assert (t["risk_per_trade"], t["max_trades"], t["max_open"], t["daily_loss"], t["dd_halt"]) == (0.01, 1, 1, 0.02, 0.05)
    assert A.limits(cfg.with_overrides({"intraday": {"risk": {"cross_day_drawdown_halt": 0}}}), SPEC)["dd_halt"] == 0.10


# ---- shadow ------------------------------------------------------------------------------------------------------------------
def test_shadow_journals_what_it_would_place_and_touches_nothing(w):
    before = paper_state(w)
    a = w.alloc("shadow")
    notes = a.run(w.d, w.now)
    assert paper_state(w) == before                                         # not one fill, trade, state key or cent
    rec = [e for e in w.decisions() if e.get("sleeve") == "A"][0]
    assert rec["status"] == "would_place" and rec["mode"] == "shadow" and rec["lots"] >= 1 and rec["reasons"] == []
    assert any("would_place" in n for n in notes)
    assert rec["allocator"] == SPEC["_hash"] and rec["sleeve_spec_hash"] == w.seller.spec["_hash"]
    assert rec["assessment"]["eligible"] and rec["assessment"]["n"] == 10
    assert len(rec["legs"]) == 4 and rec["sizing"]["max_loss"] <= 0.025 * EQUITY
    w.alloc("shadow").run(w.d, w.now)                                       # a re-run decides nothing twice
    assert len([e for e in w.decisions() if e.get("sleeve") == "A"]) == 1


def test_shadow_holds_read_only_views_that_cannot_write(w):
    j, b = A._ReadOnlyJournal(w.journal), A._ReadOnlyBroker(w.broker)
    for sql in ("DELETE FROM trades", "INSERT INTO trades(id) VALUES ('x')", "UPDATE trades SET pnl=1"):
        with pytest.raises(PermissionError):
            j.df(sql)
    assert not any(hasattr(j, m) for m in ("set_state", "open_trade", "fill", "event", "commit", "_exec", "decision"))
    assert not any(hasattr(b, m) for m in ("execute", "settle_expiry", "save", "load"))
    b.positions()["X"] = {"qty": 1}                                         # a copy: even a mutated view changes nothing
    assert "X" not in w.broker.positions()


def test_shadow_marks_with_real_quotes_and_settles_where_the_sleeve_settles(w, cfg):
    w.alloc("shadow").run(w.d, w.now)
    rec = [e for e in w.decisions() if e["status"] == "would_place"][0]
    snapshot(w.cfg, w.cal, w.data, w.e, w.e, "1525", spot=22600.0)
    a = w.alloc("shadow")
    notes = a.run(w.e, at(w.e, "15:26"))
    marks = [e for e in a.events() if e["event"] == "mark"]
    assert len(marks) == 1 and marks[0]["snapshot"].endswith("_1525.csv") and any("mark" in n for n in notes)
    a.run(w.e, at(w.e, "15:27"))                                            # once per session
    assert len([e for e in a.events() if e["event"] == "mark"]) == 1
    closing_bars(w.data, w.e, 22600.0)                                      # the index pins: every leg expires worthless
    w.seller.run(w.e, now=at(w.e, "15:45"))
    a.run(w.e, at(w.e, "15:46"))
    done = [e for e in a.events() if e["event"] == "settle" and e["kind"] == "shadow"]
    assert len(done) == 1 and done[0]["lots"] == rec["lots"] and done[0]["settle"] == pytest.approx(22600.0)
    s = rec["sizing"]
    assert done[0]["pnl_rs"] == pytest.approx(s["credit_pts"] * 65 * rec["lots"] - s["entry_fees"], abs=0.05)
    a.run(w.e, at(w.e, "15:50"))
    assert len([e for e in a.events() if e["event"] == "settle"]) == 1


def test_a_missed_eve_is_never_allocated_late(cfg, tmp_path):
    w = World(cfg, tmp_path / "next_morning")
    w.alloc("shadow").run(w.d, at(w.e, "09:30"))                            # the next morning, not the eve's own step
    rec = [e for e in w.decisions() if e.get("sleeve") == "A"][0]
    assert rec["status"] == "refused" and any("eve's own post-close step" in r for r in rec["reasons"])
    w2 = World(cfg, tmp_path / "too_early")
    w2.alloc("shadow").run(w2.d, at(w2.d, "15:10"))                         # before the sleeves' window closes
    rec = [e for e in w2.decisions() if e.get("sleeve") == "A"][0]
    assert rec["status"] == "refused" and any("before the sleeves' entry window closes" in r for r in rec["reasons"])


# ---- sleeves: naked, unlisted and ineligible never ---------------------------------------------------------------------------------
def test_naked_sleeves_are_never_allocated(w):
    a = w.alloc("shadow")
    a.run(w.d, w.now)
    b = [e for e in w.decisions() if e.get("sleeve") == "B"][0]
    assert b["status"] == "refused" and "not an allocatable sleeve" in b["reasons"][0] and b["lots"] == 0
    # even if the naked sleeve were listed in the spec and eligible by every other test, the sleeve table says naked
    spec = copy.deepcopy(SPEC)
    spec["sleeves"]["allowed"].append({"spec": w.seller.spec["name"], "spec_sha256_12": w.seller.spec["_hash"], "sleeve": "B",
                                       "strategy": "short_strangle_20d", "underlyings": ["NIFTY"]})
    ev = [e for e in w.seller.events() if e["event"] == "open" and e.get("sleeve") == "B" and e["day"] == str(w.d)][0]
    forced = A.Allocator(w.cfg, [w.seller], w.journal, w.broker, w.root, spec=spec)
    w.seller.assessment = lambda s, u: {"n": 99, "cost": "passed", "consistency": "consistent", "retired": None, "bugs": [],
                                        "eligible": True, "mean": 1.0, "z": 0.0}
    rec, legs = forced.decide(w.seller, ev, w.d, w.now, w.journal, w.broker, [])
    assert rec["status"] == "refused" and legs is None and "not an allocatable sleeve" in rec["reasons"][0]
    priced, _ = A.price_legs(ev, w.broker)
    assert priced is None                                                   # and a strangle's two legs are not a priced condor


def test_an_ineligible_sleeve_is_never_allocated(cfg, tmp_path):
    w = World(cfg, tmp_path, history=9)                                     # one short of the 10 settled trades
    rec = w.one()
    assert rec["status"] == "refused" and any("not eligible under its own spec" in r for r in rec["reasons"])
    assert rec["assessment"]["n"] == 9 and not rec["assessment"]["eligible"]


def test_a_sleeve_whose_cost_check_failed_is_not_allocated(cfg, tmp_path):
    w = World(cfg, tmp_path, history=0)
    w.history(10, cost_gap=-400.0)                                          # real quotes cost far more than the edge
    rec = w.one()
    assert rec["status"] == "refused" and rec["assessment"]["cost"] == "failed" and rec["assessment"]["retired"]


def test_a_changed_sleeve_spec_allocates_nothing(w, monkeypatch):
    w.seller.spec["_hash"] = "000000000000"                                 # the sleeve rules in force are not the registered ones
    rec = w.one()
    assert rec["status"] == "refused" and any("not the one this allocator was registered against" in r for r in rec["reasons"])


def test_a_bad_quote_flag_refuses(w):
    ev = [e for e in w.seller.events() if e["event"] == "open" and e.get("sleeve") == "A" and e["day"] == str(w.d)][0]
    for flag in ("locked", "late"):
        e2 = dict(ev, quote_flags=[flag], id=f"A-x-{flag}")
        rec, legs = w.alloc().decide(w.seller, e2, w.d, w.now, w.journal, w.broker, [])
        assert rec["status"] == "refused" and any("quote quality" in r for r in rec["reasons"])


def test_the_structure_is_verified_from_the_legs_not_the_label(w):
    ev = [e for e in w.seller.events() if e["event"] == "open" and e.get("sleeve") == "A" and e["day"] == str(w.d)][0]
    legs, _ = A.price_legs(ev, w.broker)
    assert A.structure_problems(legs) == []
    swapped = [dict(l, qty=-l["qty"]) for l in legs]                        # wings short, shorts long: an inverted condor
    assert A.structure_problems(swapped)
    two_shorts = [dict(l, qty=-1) if l["right"] == "CE" else l for l in legs]
    assert A.structure_problems(two_shorts)
    wing_inside = [dict(l, strike=l["strike"] - 100) if (l["right"] == "CE" and l["qty"] > 0) else l for l in legs]
    assert A.structure_problems(wing_inside)                                # the long call is nearer the money than the short


# ---- sizing --------------------------------------------------------------------------------------------------------------------------
def test_sizing_keeps_the_max_loss_inside_two_and_a_half_percent_with_costs(cfg, tmp_path):
    w = World(cfg, tmp_path, depth=1e6)
    rec = w.one()
    s = rec["sizing"]
    assert rec["lots"] == 2                                                 # the spec's cap of two lots
    assert s["max_loss"] <= 0.025 * EQUITY
    # recomputed independently from the four legs: (wing - credit) x lot x lots + entry fees + 2 x wing x exercise STT
    credit = sum(-l["qty"] * l["fill"] for l in rec["legs"])
    width = max(abs(next(l["strike"] for l in rec["legs"] if l["right"] == r and l["qty"] > 0)
                    - next(l["strike"] for l in rec["legs"] if l["right"] == r and l["qty"] < 0)) for r in ("CE", "PE"))
    assert s["credit_pts"] == pytest.approx(credit) and s["width_pts"] == width == 100
    fees = sum(w.broker.costs.fees(Instrument.from_dict({"symbol": l["symbol"], "kind": "option", "underlying": "NIFTY", "lot_size": 65,
                                                         "strike": l["strike"], "expiry": rec["expiry"], "right": l["right"]}),
                                   l["qty"] * 2 * 65, l["fill"])[0] for l in rec["legs"])
    assert s["entry_fees"] == pytest.approx(fees)
    exp = dt.date.fromisoformat(rec["expiry"])
    assert s["max_loss"] == pytest.approx((s["width_pts"] - credit) * 65 * 2 + fees + w.broker.costs.exercise_stt(exp) * 2 * s["width_pts"] * 130)
    # the fills the allocation is sized on are the ones the paper broker returns: reference quote, one tick worse
    for l in rec["legs"]:
        assert l["fill"] == pytest.approx(l["ask"] + 0.05 if l["qty"] > 0 else l["bid"] - 0.05)
        assert l["ref"] == (l["ask"] if l["qty"] > 0 else l["bid"])


def test_a_position_that_cannot_fit_two_and_a_half_percent_gets_no_lots(cfg, tmp_path):
    tight = cfg.with_overrides({"intraday": {"risk": {"risk_per_trade": 0.005}}})   # budget ₹2,500; one lot's max loss is ~₹5,500
    w = World(tight, tmp_path, depth=1e6)
    rec = w.one()
    assert rec["status"] == "refused" and rec["lots"] == 0 and any("1 lot does not fit" in r and "risk" in r for r in rec["reasons"])
    assert paper_state(w)[2] == 0


def test_depth_at_the_touch_and_unknown_depth_cap_the_lots(cfg, tmp_path):
    assert World(cfg, tmp_path / "a", depth=None).one()["lots"] == 1        # unknown depth: one lot
    assert World(cfg, tmp_path / "b", depth=65 * 1.0).one()["lots"] == 1    # one lot resting
    assert World(cfg, tmp_path / "c", depth=30.0).one()["lots"] == 0        # less than a lot resting: none
    assert World(cfg, tmp_path / "d", depth=1e6).one()["lots"] == 2


@pytest.mark.parametrize("what,mutate,expect", [
    ("max_open", lambda w: w.alloc()._append({"event": "decision", "status": "would_place", "mode": "shadow", "day": str(w.d),
                                              "eve": str(w.d), "sleeve_trade": "V1", "expiry": str(w.e),
                                              "sizing": {"max_loss": 1.0, "margin": 1.0}}) and
                           w.alloc()._append({"event": "decision", "status": "would_place", "mode": "shadow", "day": str(w.d),
                                              "eve": str(w.d), "sleeve_trade": "V2", "expiry": str(w.e),
                                              "sizing": {"max_loss": 1.0, "margin": 1.0}}), "2 positions already open"),
    ("max_trades", lambda w: [w.journal._exec("INSERT INTO trades (id, opened_at, status) VALUES (?,?, 'closed')", (f"T{i}", f"{w.d} 10:0{i}"))
                              for i in range(4)], "4 trades already today"),
    ("daily_loss", lambda w: w.account(EQUITY * 0.94, start=EQUITY, peak=EQUITY * 0.94) or w.broker._pos.clear()
     or setattr(w.broker, "_cash", EQUITY * 0.94), "loss limit"),
    ("drawdown", lambda w: w.account(EQUITY, peak=EQUITY * 1.12), "from its peak"),
    ("drawdown_halt_active", lambda w: w.journal.set_state(DD_KEY, {"since": "x"}), "drawdown halt is active"),
    ("inherited_halt", lambda w: w.journal.set_state(HALT_KEY, {"items": [{"key": "k", "detail": "d"}]}), "inherited-position halt"),
    ("paused", lambda w: w.account(EQUITY, paused=True), "paused"),
    ("paused_state", lambda w: w.journal.set_state("intraday_paused", True), "paused"),
    ("lot_mismatch", lambda w: setattr(w, "cfg", w.cfg.with_overrides({"instruments": {"NIFTY": {"lot_size": 75}}})), "configured lot 75"),
    ("session_halts", lambda w: w.account(EQUITY, halts={"safe_mode": "3 steps failed"}), "recorded a halt: safe_mode"),
    ("governor", lambda w: w.journal.set_state("risk_governor", {"standdown_until": f"{w.d}T23:59:59", "standdown_why": "day_standdown"}),
     "stood the desk down"),
    ("no_session", lambda w: w.journal.set_state("intraday_live", {"day": str(w.e)}), "no session record"),
    ("no_peak", lambda w: w.journal.set_state(DD_PEAK_KEY, None), "no equity peak"),
    ("floor_for_sold_legs", lambda w: setattr(w, "cfg", w.cfg.with_overrides({"intraday": {"short_legs_from_equity": 900000}})), "floor for sold legs"),
    ("selling_off", lambda w: setattr(w, "cfg", w.cfg.with_overrides({"intraday": {"short_legs_from_equity": None}})), "selling is off"),
    ("live_account", lambda w: setattr(w, "cfg", w.cfg.with_overrides({"account": {"mode": "live"}})), "not paper"),
])
def test_every_desk_limit_and_halt_refuses(cfg, tmp_path, what, mutate, expect):
    w = World(cfg, tmp_path, depth=1e6)
    mutate(w)
    a = w.alloc("shadow")
    a.run(w.d, w.now)
    rec = [e for e in a.events() if e["event"] == "decision" and e.get("sleeve") == "A"][0]
    assert rec["status"] == "refused" and rec["lots"] == 0, rec["reasons"]
    assert any(expect in r for r in rec["reasons"]), (expect, rec["reasons"])


def test_the_kill_switch_file_refuses(cfg, tmp_path):
    w = World(cfg, tmp_path, depth=1e6)
    (Path(w.cfg.runtime_dir) / "KILL").write_text("")
    assert any("kill switch" in r for r in w.one()["reasons"])






def test_a_broker_that_disagrees_with_the_journal_refuses(cfg, tmp_path):
    w = World(cfg, tmp_path, depth=1e6)
    w.broker.execute(Order(Instrument.option("NIFTY", w.e, 22000, "CE", 65), -65, "hand", "open"), 100.0, w.now)
    assert any("do not equal the journal" in r for r in w.one()["reasons"])


# ---- the carry rule: one night, to the sleeve's own expiry --------------------------------------------------------------------------
def test_a_weekend_between_the_eve_and_the_expiry_refuses(cfg):
    cal = A.TradingCalendar(cfg.holidays())
    fri = dt.date(2026, 10, 9)
    assert fri.weekday() == 4 and cal.next_trading_day(fri) == dt.date(2026, 10, 12)
    bad = A.carry_problems(cfg, cal, fri, dt.date(2026, 10, 12), pd.Timestamp("2026-10-09 15:40", tz=IST))
    assert any("a weekend or a holiday sits between" in b for b in bad)
    ok = A.carry_problems(cfg, cal, dt.date(2026, 10, 12), dt.date(2026, 10, 13), pd.Timestamp("2026-10-12 15:40", tz=IST))
    assert ok == []


def test_a_holiday_between_the_eve_and_the_expiry_refuses(cfg):
    cal = A.TradingCalendar(cfg.holidays())
    hol = next(h for h in sorted(cfg.holidays()) if h.year == 2026 and h.weekday() in (1, 2, 3)
               and cal.is_trading_day(h - dt.timedelta(days=1)) and cal.is_trading_day(h + dt.timedelta(days=1)))
    eve_day, nxt = hol - dt.timedelta(days=1), hol + dt.timedelta(days=1)
    assert cal.next_trading_day(eve_day) == nxt                             # the expiry "next trading day" skips the holiday
    bad = A.carry_problems(cfg, cal, eve_day, nxt, pd.Timestamp(f"{eve_day} 15:40", tz=IST))
    assert any("2 calendar days" in b for b in bad)


def test_a_year_without_a_holiday_list_refuses(cfg):
    cal = A.TradingCalendar(cfg.holidays())
    bad = A.carry_problems(cfg, cal, dt.date(2027, 12, 20), dt.date(2027, 12, 21), pd.Timestamp("2027-12-20 15:40", tz=IST))
    assert any("cannot be trusted" in b for b in bad)


def test_an_expiry_that_is_not_the_next_trading_day_refuses(cfg):
    cal = A.TradingCalendar(cfg.holidays())
    bad = A.carry_problems(cfg, cal, dt.date(2026, 10, 12), dt.date(2026, 10, 14), pd.Timestamp("2026-10-12 15:40", tz=IST))
    assert any("not the next trading day" in b for b in bad)


# ---- apply -------------------------------------------------------------------------------------------------------------------------------










# ---- all-or-nothing, and never a naked short ------------------------------------------------------------------------------------














# ---- the whole life: placed, carried, settled by the sleeve's own rule ---------------------------------------------------------------










def test_the_report_and_render(w):
    a = w.alloc()
    a.run(w.d, w.now)
    rep = a.report()
    assert rep["mode"] == "shadow" and rep["counts"].get("would_place") == 1 and rep["shadow_sessions"] == 1
    text = A.render(rep)
    assert "Allocator" in text and "would_place" in text and "docs/prereg/allocator_v1.json" in text


def test_off_records_nothing(cfg, tmp_path):
    w = World(cfg, tmp_path, mode="off")
    assert w.alloc().run(w.d, w.now) == [] and not w.alloc().events()




# ---- the command, and the docs -------------------------------------------------------------------------------------------------
def _sleeves(cfg, *args):
    from quantdesk.cli import build_parser
    a = build_parser().parse_args(["intraday", "sleeves", *args])
    a.fn(cfg, a)


def test_the_sleeves_command_reports_the_allocator_in_shadow(cfg, capsys):
    _sleeves(cfg, "--report")
    out = capsys.readouterr().out
    assert "## Allocator · allocator_v1" in out and "Mode **shadow**" in out and "0 of 5 needed" in out


def test_the_sleeves_command_says_nothing_of_the_allocator_when_it_is_off(cfg, capsys):
    _sleeves(cfg.with_overrides({"intraday": {"allocator": {"mode": "off"}}}), "--report")
    assert "Allocator" not in capsys.readouterr().out


def test_an_allocator_failure_is_printed_and_never_stops_the_step(cfg, capsys, monkeypatch):
    monkeypatch.setattr(A.Allocator, "report", lambda self: (_ for _ in ()).throw(RuntimeError("boom")))
    _sleeves(cfg, "--report")
    out = capsys.readouterr().out
    assert "allocator failed (shadow only; nothing was changed)" in out and "Expiry sellers" in out




def test_apply_is_not_implemented_it_is_shadow_and_places_nothing(cfg, tmp_path):
    w = World(cfg, tmp_path, mode="apply", depth=1e6)
    w.seed_shadow_sessions(6)                                                # even with plenty of shadow sessions on record
    before = paper_state(w)
    a = w.alloc()
    assert a.mode()[0] == "shadow" and "not implemented" in a.mode()[1]
    notes = a.run(w.d, w.now)
    assert any("not implemented" in n for n in notes)
    rec = [e for e in a.events() if e["event"] == "decision" and e.get("sleeve") == "A" and e["day"] == str(w.d)][0]
    assert rec["status"] == "would_place" and rec["mode"] == "shadow" and rec["configured_mode"] == "apply"
    assert paper_state(w) == before


def test_the_allocator_holds_only_read_only_views_of_the_account(w):
    a = w.alloc()
    assert isinstance(a.journal, A._ReadOnlyJournal) and isinstance(a.broker, A._ReadOnlyBroker)
    for forbidden in ("execute", "settle_expiry", "set_state", "open_trade", "fill", "commit"):
        assert not hasattr(a.broker, forbidden) and not hasattr(a.journal, forbidden)
    assert not any(n in dir(A) for n in ("carry", "_place", "_unwind"))      # no placement code, no registry, in this build
