"""Shadow setup replay (quantdesk/shadow): registry, no look-ahead, cost netting, ceiling flagging, no data -> unlabelled,
determinism, the data-quality gate, validate, frequency plausibility, shards, the workflow, and that the live path is untouched."""
import datetime as dt
import os
import re
import sqlite3
import subprocess
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

from quantdesk.config import DEFAULT_CONFIG, Config
from quantdesk.core.types import Instrument
from quantdesk.execution.costs import CostModel
from quantdesk.intraday.feeds import IST
from quantdesk.intraday.playbook import PlanLeg, TradePlan
from quantdesk.intraday.synthetic import simulate_sessions
from quantdesk.shadow import ceilings, quality, registry, replay, report, validate
from quantdesk.shadow.detect import Detector
from quantdesk.shadow.loaders import OHLCV, OptionBook
from quantdesk.shadow.simulate import Haircut, simulate_options, simulate_underlying

ROOT = Path(__file__).resolve().parent.parent
DAYS = [d.date() for d in pd.bdate_range("2026-09-01", "2026-09-30") if d.date() not in Config.load(DEFAULT_CONFIG).holidays()]


@pytest.fixture(scope="module")
def cfg():
    return Config.load(DEFAULT_CONFIG)


@pytest.fixture(scope="module")
def sess():
    bars, _ = simulate_sessions(DAYS[:8], seed=21, force_types={DAYS[7]: "trend_up"})
    return bars


# ---- registry -----------------------------------------------------------------------------------------------------
def test_registry_has_the_five_indices_and_twenty_stocks_from_config(cfg):
    reg = registry.load(cfg)
    assert [n for n, s in reg.items() if s.kind == "index"] == ["NIFTY", "BANKNIFTY", "SENSEX", "FINNIFTY", "MIDCPNIFTY"]
    assert len([s for s in reg.values() if s.kind == "stock"]) == 20
    assert reg["SENSEX"].segment == "bse_fo" and reg["SENSEX"].cash_segment == "bse_cm" and reg["NIFTY"].segment == "nse_fo"
    assert reg["NIFTY"].lot_size == cfg.instrument_spec("NIFTY")["lot_size"] and reg["NIFTY"].strike_step == 50
    assert all(s.cost_segment in cfg.get("costs.segments") for s in reg.values())
    assert all(s.unverified for s in reg.values() if s.kind == "stock")          # never presented as verified


def test_adding_an_instrument_is_configuration_only(cfg):
    c2 = cfg.with_overrides({"collect_wide": {"stocks": ["NEWCO"]}, "shadow": {"stocks": {"NEWCO": {"lot_size": 100, "strike_step": 5}}}})
    s = registry.load(c2)["NEWCO"]
    assert s.lot_size == 100 and s.strike_step == 5 and s.unverified           # default for stocks: unverified until said otherwise
    c3 = cfg.with_overrides({"collect_wide": {"stocks": ["GHOST"]}})
    g = registry.load(c3)["GHOST"]
    assert g.lot_size is None and g.unverified                                  # a lot size we do not know is never guessed


def test_detectors_see_registry_lots_through_the_desks_own_lookup(cfg):
    reg = registry.load(cfg)
    d = registry.derived_config(cfg, reg)
    assert d.instrument_spec("RELIANCE")["lot_size"] == reg["RELIANCE"].lot_size
    assert cfg.instrument_spec("RELIANCE")["lot_size"] == 1                     # the original config is not modified


# ---- no look-ahead --------------------------------------------------------------------------------------------------
def _sig(dec):
    if dec is None:
        return None
    return ([p.describe() + p.setup + str(p.invalidation) + str(p.target_underlying) for p in dec.plans],
            [a.describe() + str(a.level) for a in dec.armed], round(dec.view.score, 10), round(dec.view.conviction, 10),
            dec.view.day_type, {k: v for k, v in dec.state.items() if isinstance(v, (int, float, str, bool)) and v == v})


def test_truncating_future_bars_does_not_change_a_decision(cfg, sess):
    day = DAYS[7]
    cal = registry.calendar(cfg)
    nifty = sess["NIFTY"]
    exp = dt.date(2026, 10, 6)
    fired = 0
    for hhmm in ("09:45", "10:30", "11:15", "13:05", "13:25", "13:35", "14:25"):
        now = pd.Timestamp(f"{day} {hhmm}", tz=IST)
        full = Detector(cfg, "NIFTY", cal).decide(nifty, now, exp)
        cut = Detector(cfg, "NIFTY", cal).decide(nifty[nifty.index + pd.Timedelta(minutes=1) <= now], now, exp)
        scrambled = nifty.copy()
        fut = scrambled.index >= now                                             # replace the future with nonsense
        scrambled.loc[fut, ["open", "high", "low", "close"]] *= 1.07
        bad = Detector(cfg, "NIFTY", cal).decide(scrambled, now, exp)
        assert _sig(full) == _sig(cut) == _sig(bad), hhmm
        fired += bool(full and (full.plans or full.armed))
    assert fired >= 4, "the test must exercise decisions that actually fire setups"


# ---- cost netting and fills -----------------------------------------------------------------------------------------
def _book(day, expiry, strike, right, opens, closes=None, start="09:15", vol=100.0):
    closes = closes or opens
    idx = pd.date_range(pd.Timestamp(f"{day} {start}", tz=IST), periods=len(opens), freq="min")
    df = pd.DataFrame({"ts": idx, "expiry": expiry, "strike": float(strike), "right": right, "open": opens, "high": np.maximum(opens, closes),
                       "low": np.minimum(opens, closes), "close": closes, "volume": vol})
    return df


def _underlying(day, closes):
    idx = pd.date_range(pd.Timestamp(f"{day} 09:15", tz=IST), periods=len(closes), freq="min")
    c = np.asarray(closes, float)
    return pd.DataFrame({"open": np.r_[c[0], c[:-1]], "high": c + 1, "low": c - 1, "close": c, "volume": 1000.0}, index=idx)


def _plan(expiry, strike=22500.0, right="CE", direction=1, inval=22400.0, target=None, stop=0.35, tgt=0.6, tstop=45):
    leg = PlanLeg(strike, right, +1, 100.0, 99.0, 14.0, 0.5)
    return TradePlan("orb", "NIFTY", direction, "long_call", expiry, [leg], 65, "t", "th", inval, target, stop, tgt, tstop, "model", 0.6)


def test_option_label_nets_haircut_and_the_desks_fees(cfg):
    day, exp = dt.date(2026, 9, 10), dt.date(2026, 9, 15)
    n = 120
    ub = _underlying(day, np.full(n, 22500.0) + np.arange(n) * 0.1)
    opens = np.r_[np.full(40, 100.0), np.linspace(100, 180, 80)]                  # the premium climbs through the 60% target
    book = OptionBook(_book(day, exp, 22500, "CE", opens))
    plan = _plan(exp, tgt=0.6)
    hc = Haircut.from_cfg(cfg)
    t0 = pd.Timestamp(f"{day} 09:15", tz=IST) + pd.Timedelta(minutes=20)
    o = simulate_options(plan, 1, ub, book, day, t0, 65, hc, dt.time(15, 15), 2, "NIFTY")
    assert o.status == "labelled" and o.exit_reason == "premium_target"
    inst = Instrument.option("NIFTY", exp, 22500.0, "CE", 65)
    cm = CostModel(cfg)
    fees = cm.fees(inst, 65, o.entry_prices[0])[0] + cm.fees(inst, -65, o.exit_prices[0])[0]
    assert o.fees == pytest.approx(fees)
    assert o.entry_prices[0] > 100.0                                              # bought worse than the traded open (haircut)
    assert o.exit_prices[0] < float(book.by[(exp, 22500.0, "CE")].loc[o.exit_time]["open"])      # sold worse than the open
    assert o.net_pnl == pytest.approx(65 * (o.exit_prices[0] - o.entry_prices[0]) - fees)
    assert o.net_pnl < o.gross_pnl                                                # costs and slippage only ever subtract
    assert o.slippage_cost > 0 and o.entry_time == t0                             # entry on the NEXT bar (the decision minute's bar)


def test_extra_haircut_is_configurable_and_more_pessimistic(cfg):
    base = Haircut.from_cfg(cfg)
    harsh = Haircut.from_cfg(cfg.with_overrides({"shadow": {"slippage": {"extra_pct": 0.05, "extra_ticks": 3}}}))
    inst = Instrument.option("NIFTY", dt.date(2026, 9, 15), 22500.0, "CE", 65)
    assert harsh.fill(inst, 65, 100.0) > base.fill(inst, 65, 100.0) > 100.0
    assert harsh.fill(inst, -65, 100.0) < base.fill(inst, -65, 100.0) < 100.0


# ---- no data -> unlabelled, never a made-up price ------------------------------------------------------------------
def test_missing_option_minutes_are_unlabelled_with_the_reason(cfg):
    day, exp = dt.date(2026, 9, 10), dt.date(2026, 9, 15)
    ub = _underlying(day, np.full(60, 22500.0))
    hc = Haircut.from_cfg(cfg)
    t0 = pd.Timestamp(f"{day} 09:35", tz=IST)
    o = simulate_options(_plan(exp), 1, ub, None, day, t0, 65, hc, dt.time(15, 15), 2, "NIFTY")
    assert o.status == "unlabelled" and "no option minutes" in o.reason and o.net_pnl is None
    other = OptionBook(_book(day, exp, 22600, "CE", [100.0] * 60))               # a different strike only
    o = simulate_options(_plan(exp), 1, ub, other, day, t0, 65, hc, dt.time(15, 15), 2, "NIFTY")
    assert o.status == "unlabelled" and "22500CE" in o.reason
    late = OptionBook(_book(day, exp, 22500, "CE", [100.0] * 5, start="09:16"))   # traded only before the entry
    o = simulate_options(_plan(exp), 1, ub, late, day, t0, 65, hc, dt.time(15, 15), 2, "NIFTY")
    assert o.status == "unlabelled" and "no traded bar within" in o.reason


def test_replay_marks_unlabelled_rows_and_keeps_the_underlying_label(cfg, sess):
    reg = registry.load(cfg)
    dcfg = registry.derived_config(cfg, reg)
    rows = replay.replay_session(dcfg, reg["NIFTY"], DAYS[7], sess["NIFTY"], None, None, registry.calendar(cfg), 5, Haircut.from_cfg(cfg))
    assert rows, "the forced trend day should produce at least one setup"
    assert all(r["status"] == "unlabelled" and "no option minutes" in r["unlabelled_reason"] for r in rows)
    assert all(r["source"] == "shadow-replay" and r["net_pnl"] is None for r in rows)
    assert any(r["u_status"] == "labelled" for r in rows)


def test_an_unknown_lot_size_is_unlabelled_and_priced_nowhere(cfg, sess):
    c2 = cfg.with_overrides({"collect_wide": {"stocks": ["GHOST"]}})
    reg = registry.load(c2)
    dcfg = registry.derived_config(c2, reg)
    rows = replay.replay_session(dcfg, reg["GHOST"], DAYS[7], sess["NIFTY"], None, None, registry.calendar(c2), 5, Haircut.from_cfg(c2))
    assert all(r["status"] == "unlabelled" and "lot size unknown" in r["unlabelled_reason"] and r["lot_unverified"] for r in rows)


# ---- determinism -----------------------------------------------------------------------------------------------------
def test_same_input_same_output(cfg, sess):
    reg = registry.load(cfg)
    kw = dict(days=DAYS[2:8], instruments=["NIFTY"], bars_by={"NIFTY": sess["NIFTY"]}, vix=sess["INDIAVIX"], books={}, reg=reg,
              step=5, say=lambda *a: None)
    a, qa = replay.run(cfg, **kw)
    b, qb = replay.run(cfg, **kw)
    pd.testing.assert_frame_equal(a, b)
    assert len(a) > 0 and a["setup_id"].is_unique
    assert qa["NIFTY"]["usable"] == qb["NIFTY"]["usable"]


# ---- ceilings are flagged, in time order, and never changed ---------------------------------------------------------
def _item(t, sym="NIFTY", pnl=0.0, exit_min=10, prem=100.0, setup="orb"):
    t = pd.Timestamp(f"2026-09-10 {t}", tz=IST)
    plan = _plan(dt.date(2026, 9, 15))
    plan.legs[0].price = prem
    return {"decision_time": t, "entry_time": t, "exit_time": t + pd.Timedelta(minutes=exit_min), "symbol": sym, "setup": setup,
            "plan": plan, "net_pnl": pnl}


def test_the_fifth_trade_of_a_day_is_flagged_max_trades_and_a_third_open_max_open(cfg):
    before = cfg.get("intraday.risk")
    items = [_item("10:00", "NIFTY", exit_min=90), _item("10:05", "BANKNIFTY", exit_min=90), _item("10:10", "SENSEX", exit_min=90)]
    ceilings.evaluate(cfg, dt.date(2026, 9, 10), items)
    assert [i["accepted"] for i in items] == [True, True, False]
    assert "max_open" in items[2]["would_have_been_refused_by"]
    seq = [_item(f"10:{m:02d}", f"S{m}", exit_min=1) for m in (0, 5, 10, 15, 20)]          # one at a time, five in a day
    ceilings.evaluate(cfg, dt.date(2026, 9, 10), seq)
    assert [i["accepted"] for i in seq] == [True, True, True, True, False]
    assert seq[4]["would_have_been_refused_by"] == ["max_trades_per_day"] and cfg.get("intraday.risk") == before


def test_daily_loss_and_outlay_ceilings_are_flagged(cfg):
    big_loss = _item("10:00", "NIFTY", pnl=-30000.0 / 1, exit_min=1)
    nxt = _item("10:30", "BANKNIFTY", exit_min=1)
    ceilings.evaluate(cfg, dt.date(2026, 9, 10), [big_loss, nxt])
    assert "daily_loss_limit" in nxt["would_have_been_refused_by"] or not nxt["accepted"]
    pricey = _item("10:00", prem=9000.0)                                                   # premium far above the outlay cap
    ceilings.evaluate(cfg, dt.date(2026, 9, 10), [pricey])
    assert not pricey["accepted"] and pricey["would_have_been_refused_by"] == ["risk_per_trade"]     # the cap that bound
    cheap_risk = _item("10:00", prem=100.0)                                                # affordable risk, premium over 20% of equity
    ceilings.evaluate(cfg.with_overrides({"intraday": {"risk": {"max_premium_outlay": 0.0001}}}), dt.date(2026, 9, 10), [cheap_risk])
    assert "outlay" in cheap_risk["would_have_been_refused_by"]
    late = _item("14:50")
    ceilings.evaluate(cfg, dt.date(2026, 9, 10), [late])
    assert "entry_window" in late["would_have_been_refused_by"]


# ---- data quality ---------------------------------------------------------------------------------------------------------
def _day_bars(day, n=375, **kw):
    b = _underlying(day, 22500 + np.cumsum(np.random.default_rng(1).normal(0, 2, n)))
    return b


def test_quality_gate_excludes_bad_sessions_and_lists_them(cfg):
    th = quality.thresholds(cfg)
    d = [dt.date(2026, 9, x) for x in (1, 2, 3, 4, 7)]
    frames = [_day_bars(x) for x in d]
    frames[1] = frames[1].drop(frames[1].index[100:112])                                    # a 12-minute gap
    frames[2] = frames[2].iloc[:200]                                                        # too few bars
    s = frames[3].copy()
    s.iloc[150, s.columns.get_loc("close")] *= 1.08                                         # an outlier tick
    frames[3] = s
    frames[4]["close"] = frames[4]["close"].iloc[0]                                         # frozen feed
    bars = pd.concat(frames)
    rep = quality.instrument_report("NIFTY", bars, None, th | {"max_bad_session_share": 0.9}, 50, d)
    assert rep["usable"] == [d[0]] and set(rep["excluded"]) == {str(x) for x in d[1:]}
    assert any("gap" in w for w in rep["excluded"][str(d[1])]) and any("bars" in w for w in rep["excluded"][str(d[2])])
    assert any("outlier" in w for w in rep["excluded"][str(d[3])]) and any("stale" in w for w in rep["excluded"][str(d[4])])
    whole = quality.instrument_report("NIFTY", bars, None, th, 50, d)
    assert whole["instrument_excluded"] and whole["usable"] == []                             # too many bad sessions: out entirely
    assert quality.instrument_report("TCS", pd.DataFrame(columns=OHLCV), None, th, 20, d)["instrument_excluded"]
    assert "EXCLUDED" in quality.render([whole])


def test_missing_option_strikes_are_reported_per_session(cfg):
    day, exp = dt.date(2026, 9, 1), dt.date(2026, 9, 8)
    th = quality.thresholds(cfg)
    book = OptionBook(_book(day, exp, 22500, "CE", [100.0] * 30))
    rep = quality.instrument_report("NIFTY", _day_bars(day), book, th, 50, [day])
    o = rep["sessions"][str(day)]["options"]
    assert not o["ok"] and "near-the-money" in o["reason"]


# ---- validate -----------------------------------------------------------------------------------------------------------------
def _journal(path, trades):
    con = sqlite3.connect(path)
    con.executescript("""CREATE TABLE trades (id TEXT, strategy TEXT, symbol TEXT, direction INT, units INT, opened_at TEXT, closed_at TEXT,
        entry_underlying REAL, stop REAL, target REAL, initial_risk REAL, pnl REAL, fees REAL, exit_reason TEXT, status TEXT, mae REAL, mfe REAL);
        CREATE TABLE decisions (ts TEXT, strategy TEXT, symbol TEXT, action TEXT, detail TEXT);""")
    for t in trades:
        con.execute("INSERT INTO trades VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", t)
    con.commit()
    con.close()


def _setup_row(setup_id, t, exit_t, pnl, status="labelled", reason=None):
    t = pd.Timestamp(t, tz=IST)
    return {"setup_id": setup_id, "instrument": "NIFTY", "session": str(t.date()), "setup": "orb", "direction": 1, "side": "long",
            "decision_time": t, "status": status, "unlabelled_reason": reason, "net_pnl": pnl, "exit_time": pd.Timestamp(exit_t, tz=IST),
            "u_exit_time": pd.Timestamp(exit_t, tz=IST), "exit_reason": "time_exit", "u_exit_reason": "time_exit",
            "would_have_been_refused_by": ""}


def test_validate_passes_on_a_faithful_replay_and_fails_otherwise(cfg, tmp_path):
    jp = tmp_path / "j.db"
    _journal(jp, [("T1", "orb", "NIFTY", 1, 2, "2026-10-12T10:35:04+05:30", "2026-10-12T11:20:04+05:30", 22500, 22450, 22600, 5000, 1000.0,
                   100.0, "time_exit", "closed", -10.0, 20.0)])
    trades, dec = validate.read_journal(jp)
    st = validate.settings(cfg)
    good = pd.DataFrame([_setup_row("a", "2026-10-12 10:35", "2026-10-12 11:21", 520.0)])         # 2 lots: 1040 vs live 1000
    res = validate.compare(good, trades, dec, st)
    assert res["passed"] and res["match_rate"] == 1.0
    bad_pnl = pd.DataFrame([_setup_row("a", "2026-10-12 10:35", "2026-10-12 11:21", -900.0)])
    r2 = validate.compare(bad_pnl, trades, dec, st)
    assert not r2["passed"] and "net P&L differs" in r2["rows"][0]["reasons"][0]
    unl = pd.DataFrame([_setup_row("a", "2026-10-12 10:35", "2026-10-12 11:21", None, "unlabelled", "no option minutes")])
    r3 = validate.compare(unl, trades, dec, st)
    assert not r3["passed"] and "not comparable" in r3["rows"][0]["reasons"][0]
    none = validate.compare(good.iloc[0:0], trades, dec, st)
    assert not none["passed"] and "no setup" in none["rows"][0]["reasons"][0]
    late = pd.DataFrame([_setup_row("a", "2026-10-12 10:35", "2026-10-12 12:40", 520.0)])
    assert "exit time differs" in validate.compare(late, trades, dec, st)["rows"][0]["reasons"][0]
    assert "FAIL" in validate.render(none) and "PASS" in validate.render(res)


def test_validate_threshold_is_configurable_and_strict_by_default(cfg):
    assert validate.settings(cfg)["match_threshold"] >= 0.9
    st = validate.settings(cfg.with_overrides({"shadow": {"validate": {"match_threshold": 0.4}}}))
    assert st["match_threshold"] == 0.4


def test_validate_command_fails_clearly_without_a_journal(cfg, tmp_path):
    from quantdesk.shadow import cli
    a = type("A", (), {"threshold": None, "journal": str(tmp_path / "nope.db"), "data": None, "pull": None, "step": 5, "json": None})()
    with pytest.raises(SystemExit) as e:
        cli.cmd_validate(cfg, a)
    assert "FAIL" in str(e.value)


# ---- plausibility, shards, summary ---------------------------------------------------------------------------------------------
def test_frequency_flags_an_instrument_that_fires_five_times_as_often(cfg):
    df = pd.DataFrame({"instrument": ["NIFTY"] * 10 + ["BANKNIFTY"] * 10 + ["SENSEX"] * 80 + ["FINNIFTY"] * 10 + ["ITC"] * 1})
    f = report.frequency(df, {"NIFTY": 10, "BANKNIFTY": 10, "SENSEX": 10, "FINNIFTY": 10, "ITC": 10}, 5.0)
    pi = f["per_instrument"]
    assert pi["SENSEX"]["flag"] and "8.0x" in pi["SENSEX"]["flag"]
    assert pi["ITC"]["flag"] and pi["FINNIFTY"]["flag"] is None and pi["NIFTY"]["flag"] is None


def test_shard_write_merges_and_replaces_only_replayed_sessions(tmp_path):
    def rows(sess, ids):
        return pd.DataFrame({"setup_id": ids, "instrument": "NIFTY", "session": sess, "decision_time": pd.Timestamp(f"{sess} 10:00", tz=IST),
                             "setup": "orb"})
    out = tmp_path
    report.write_shards(rows("2026-10-05", ["a"]), out, {"NIFTY": {"2026-10-05"}}, say=lambda *a: None)
    report.write_shards(rows("2026-10-06", ["b"]), out, {"NIFTY": {"2026-10-06"}}, say=lambda *a: None)
    assert sorted(pd.read_parquet(out / "shadow-setups-2026Q4.parquet")["setup_id"]) == ["a", "b"]
    report.write_shards(rows("2026-10-05", ["c"]), out, {"NIFTY": {"2026-10-05"}}, say=lambda *a: None)      # a re-run of day 1
    assert sorted(pd.read_parquet(out / "shadow-setups-2026Q4.parquet")["setup_id"]) == ["b", "c"]
    assert report.shard_name(dt.date(2026, 7, 1)) == "shadow-setups-2026Q3"


def test_summary_states_the_samples_are_not_independent(cfg, sess):
    reg = registry.load(cfg)
    df, q = replay.run(cfg, DAYS[2:8], ["NIFTY"], {"NIFTY": sess["NIFTY"]}, None, {}, reg, step=5, say=lambda *a: None)
    s = report.summary(df, q)
    assert "NOT independent" in s and "NIFTY" in s and "unlabelled" in s.lower()


# ---- the workflow and the untouched live path -----------------------------------------------------------------------------------
def test_workflow_is_manual_only_least_privilege_and_fail_soft():
    wf = yaml.load((ROOT / ".github/workflows/shadow-replay.yml").read_text(), Loader=yaml.BaseLoader)
    assert list(wf["on"]) == ["workflow_dispatch"]
    assert wf["permissions"] == {"contents": "write"}
    assert wf["concurrency"]["group"] == "shadow-replay"
    text = (ROOT / ".github/workflows/shadow-replay.yml").read_text()
    assert set(re.findall(r"secrets\.([A-Z_]+)", text)) <= {"KOTAK_CONSUMER_KEY"} and "secrets." not in text.replace("# ", "")
    for job in wf["jobs"].values():
        assert all(s.get("continue-on-error") == "true" for s in job["steps"])
        assert all(re.fullmatch(r"[0-9a-f]{40}", s["uses"].rpartition("@")[2]) for s in job["steps"] if "uses" in s)


def _branch() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    except OSError:
        return ""


@pytest.mark.skipif("shadow-replay" not in (_branch(), os.environ.get("GITHUB_HEAD_REF", ""), os.environ.get("SHADOW_GUARD", "")),
                    reason="the diff guard is for this PR's branch (or SHADOW_GUARD=1)")
def test_this_pr_leaves_live_yml_and_the_intraday_package_unchanged():
    base = subprocess.run(["git", "merge-base", "HEAD", "origin/main"], cwd=ROOT, capture_output=True, text=True)
    if base.returncode != 0:
        pytest.skip("no origin/main to diff against")
    changed = subprocess.run(["git", "diff", "--name-only", base.stdout.strip(), "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.split()
    touched = [f for f in changed if f.startswith("quantdesk/intraday/") or f == ".github/workflows/live.yml" or f.startswith("docs/prereg/")]
    assert touched == []
    cfg_diff = subprocess.run(["git", "diff", base.stdout.strip(), "HEAD", "--", "config/quantdesk.yaml"], cwd=ROOT, capture_output=True, text=True).stdout
    removed = [l for l in cfg_diff.splitlines() if l.startswith("-") and not l.startswith("---")]
    assert removed == []                                                                      # config only gains the shadow: section


def test_shadow_code_never_reaches_the_trading_objects():
    """Static guard that holds for good: the shadow package imports detectors and read-only helpers, never the engine, the
    broker, an order, or a write to an intraday module."""
    forbidden = ("IntradayEngine", "IntradayBroker", "PaperBroker", "KiteBroker", "Order(", "place_order", ".execute(", "set_state(",
                 "account.mode", "KOTAK_CONSUMER_KEY", "apply_limits")
    for p in (ROOT / "quantdesk/shadow").glob("*.py"):
        src = p.read_text()
        for bad in forbidden:
            assert bad not in re.sub(r'""".*?"""', "", src, flags=re.S), f"{p.name} mentions {bad}"
    assert Config.load(DEFAULT_CONFIG).get("account.mode") == "paper"
