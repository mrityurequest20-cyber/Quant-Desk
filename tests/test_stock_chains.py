"""Every-minute F&O stock chains with quotes and the order book (quantdesk/data/stock_chains.py, record-stocks.yml, the depth capture in intraday/kotak.py): sharding, the tape run under a fake
clock, the order-book files, the part and day files, the counts-only manifest, the health check and the workflow's isolation. A fake Kotak: no network, no key."""
from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

from quantdesk.data import stock_chains as SC
from quantdesk.intraday import kotak as K
from quantdesk.intraday.chains import COLUMNS, DEPTH
from quantdesk.intraday.feeds import IST

ROOT = Path(__file__).resolve().parents[1]
WF = ROOT / ".github/workflows/record-stocks.yml"
DAY = dt.date(2026, 11, 9)
NAMES = [f"S{i:03d}" for i in range(23)]


def _book(px):
    return {"buy": [{"price": str(px - i * 0.05), "quantity": str(100 * (i + 1))} for i in range(5)],
            "sell": [{"price": str(px + 0.05 + i * 0.05), "quantity": str(80 * (i + 1))} for i in range(5)]}


class FakeClient:
    """Answers the three Kotak calls KotakOptionChain makes, in the shapes it parses."""
    def __init__(self, fail=()):
        self.fail, self.calls = set(fail), 0

    def expiries(self, u, **kw):
        return [DAY + dt.timedelta(days=17), DAY + dt.timedelta(days=45)]

    def option_chain(self, u, expiry, count, **kw):
        if u in self.fail:
            raise K.KotakError(f"HTTP 500 for {u}")
        self.calls += 1
        items = lambda side: [{"instrument": {"strikePrice": 100 + 5 * i, "neoSymbol": f"nse_fo|{u}{side}{i}"}, "quote": {"ltp": 3 + i, "volume": 10 * i}, "openInterest": {"current": 1000, "previous": 900}}  # noqa: E731
                              for i in range(-3, 4)]
        return {"data": {"call": items("C"), "put": items("P"), "mktLot": 500}}

    def quotes(self, want):
        self.calls += 1
        return [{"exchange": g, "exchange_token": t, "ltp": 3.5, "last_volume": 5, "open_int": 1000, "depth": _book(3.5)} for g, t in want]


def _chain_parts(monkeypatch):
    monkeypatch.setattr(K, "chain_parts", lambda body: (body["data"], body["data"]["call"], body["data"]["put"]), raising=False)
    import quantdesk.intraday.kotak as kk
    monkeypatch.setattr(kk, "chain_parts", lambda body: (body["data"], body["data"]["call"], body["data"]["put"]))


class Clock:
    """Starts at the open and moves one minute a read after the second read of a minute: a session of a few minutes."""
    def __init__(self, start="2026-11-09 09:15:10"):
        self.t = pd.Timestamp(start, tz=IST)

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.t += pd.Timedelta(seconds=max(s, 30.0))


def test_the_stocks_are_split_into_shards_that_cover_each_once_in_a_stable_order():
    names = list(reversed(NAMES))
    parts = [SC.shard_of(names, k, 10) for k in range(10)]
    assert sorted(sum(parts, [])) == NAMES and all(len(p) in (2, 3) for p in parts)
    assert parts[0] == [NAMES[0], NAMES[10], NAMES[20]] and SC.shard_of(NAMES, 0, 10) == parts[0]
    with pytest.raises(ValueError):
        SC.shard_of(NAMES, 10, 10)


def test_the_quote_keeps_five_levels_each_side_and_nan_where_a_level_is_empty():
    q = {"depth": {"buy": [{"price": "10.0", "quantity": "75"}, {"price": "9.9", "quantity": "150"}], "sell": []}}
    r = K.depth_row(q, 100.0, "ce")
    assert r["b1p"] == 10.0 and r["b1q"] == 75 and r["b2p"] == 9.9 and np.isnan(r["b3p"]) and np.isnan(r["a1p"]) and len(r) == 2 + 20
    assert K.depth_row({}, 100.0, "pe")["side"] == "pe"


def test_a_shard_records_every_minute_its_stocks_chain_and_order_book_and_writes_counts_only(tmp_path, monkeypatch):
    _chain_parts(monkeypatch)
    clk = Clock()
    mine = SC.shard_of(NAMES, 3, 10)
    src = K.KotakOptionChain(FakeClient(), strikes=10, depth_levels=5)
    monkeypatch.setattr(src, "now", clk, raising=False)
    man = SC.run_shard(None, tmp_path, 3, 10, "morning-3", dt.time(9, 20), names=NAMES, source=src, clock=clk, sleep=clk.sleep, say=lambda *a: None)
    day = tmp_path / "data" / str(DAY)
    assert sorted({p.name.split("_")[0] for p in (day / "chains").glob("*.csv")}) == sorted(mine)
    n_min = len(list((day / "chains").glob(f"{mine[0]}_*.csv")))
    assert n_min >= 3 and len(list((day / "depth").glob("*.csv"))) == len(list((day / "chains").glob("*.csv")))        # an order book for every snapshot
    parts = tmp_path / "_parts"
    ch, bk = pd.read_parquet(parts / f"{DAY}_morning-3_chains.parquet"), pd.read_parquet(parts / f"{DAY}_morning-3_depth.parquet")
    assert set(ch["underlying"]) == set(mine) and {"ce_bid", "ce_ask", "pe_bidq", "ce_ltp"} <= set(ch.columns)
    assert {"ts", "underlying", "expiry", "strike", "side", "b1p", "b5q", "a1p", "a5q"} <= set(bk.columns) and set(bk["side"]) == {"ce", "pe"} and bk["b1p"].gt(bk["b5p"]).all()
    assert len(bk) == len(ch) * 2                                                                         # a call and a put per strike
    m = json.loads((parts / f"{DAY}_morning-3_manifest.json").read_text())
    assert m["stocks"] == len(mine) and m["recorded"] == len(mine) and all(v >= 3 for v in m["minutes"].values()) and m["chain_rows"] == len(ch) and m["depth_rows"] == len(bk)
    assert SC.publishable({"evidence": "x", "day": str(DAY), "note": "n", "per_stock_minutes": m["minutes"], "stocks": 3}) == [] and not re.search(r"ltp|b1p|ce_bid|\"ask", json.dumps({k: v for k, v in m.items() if k != "note"}))


def test_one_stock_failing_costs_only_that_stock_and_is_in_the_manifest(tmp_path, monkeypatch):
    _chain_parts(monkeypatch)
    clk = Clock()
    mine = SC.shard_of(NAMES, 0, 10)
    src = K.KotakOptionChain(FakeClient(fail={mine[1]}), strikes=10, depth_levels=5)
    monkeypatch.setattr(src, "now", clk, raising=False)
    man = SC.run_shard(None, tmp_path, 0, 10, "morning-0", dt.time(9, 19), names=NAMES, source=src, clock=clk, sleep=clk.sleep, say=lambda *a: None)
    assert man["recorded"] == len(mine) - 1 and mine[1] not in man["minutes"] and man["failures"] >= 1 and "top_errors" not in man


def test_a_day_of_parts_merges_into_three_files_and_one_manifest_and_a_missing_depth_column_is_filled(tmp_path, monkeypatch):
    _chain_parts(monkeypatch)
    for shard, half in ((0, "morning"), (1, "morning"), (0, "afternoon")):
        clk = Clock("2026-11-09 09:15:10" if half == "morning" else "2026-11-09 13:00:10")
        src = K.KotakOptionChain(FakeClient(), strikes=10, depth_levels=5)
        monkeypatch.setattr(src, "now", clk, raising=False)
        SC.run_shard(None, tmp_path / f"{half}{shard}", shard, 10, f"{half}-{shard}", dt.time(9, 18) if half == "morning" else dt.time(13, 3), names=NAMES, source=src, clock=clk, sleep=clk.sleep, say=lambda *a: None)
    parts = tmp_path / "all"
    parts.mkdir()
    for p in tmp_path.glob("*/_parts/*"):
        (parts / p.name).write_bytes(p.read_bytes())
    tot = SC.consolidate(parts, tmp_path / "day", str(DAY))
    out = tmp_path / "day"
    assert sorted(p.name for p in out.glob("*")) == sorted([f"{DAY}_stock_chains.parquet", f"{DAY}_stock_depth.parquet", f"{DAY}_stock_tape.parquet", f"{DAY}_stock_chains_manifest.json"])
    assert len(pd.read_parquet(out / f"{DAY}_stock_chains.parquet")) == tot["rows"]["chains"] > 0 and tot["parts"] == 3 and tot["recorded"] == len(SC.shard_of(NAMES, 0, 10)) + len(SC.shard_of(NAMES, 1, 10))
    assert SC.publishable(tot) == [] and tot["coverage"] is not None
    bad = dict(tot, secret_price=1.5)
    assert SC.publishable(bad) and SC.publishable(dict(tot, per_stock_minutes={"S001": 1.5})) and SC.publishable(dict(tot, per_stock_minutes={"bad name!": 3}))


def test_the_tape_default_is_unchanged_and_a_stagger_and_an_extra_hook_are_opt_in():
    from quantdesk.intraday.tape import ChainTape
    t = ChainTape(object(), Path("x"))
    assert t.offset_s == 5.0 and t.extra is None
    assert ChainTape(object(), Path("x"), offset_s=33.0).offset_s == 33.0


def test_the_workflow_shards_the_stocks_isolates_the_key_and_publishes_with_no_secret():
    import sys
    sys.path.insert(0, str(ROOT / "deploy"))
    import check_workflows
    text = WF.read_text(encoding="utf-8")
    wf = yaml.safe_load(text)
    assert check_workflows.check(WF) == [] and wf["permissions"] == {"contents": "read"} and wf["concurrency"]["group"] == "stock-recorder"
    jobs = wf["jobs"]
    assert jobs["morning"]["strategy"]["matrix"]["shard"] == list(range(10)) == jobs["afternoon"]["strategy"]["matrix"]["shard"] and jobs["morning"]["strategy"]["fail-fast"] is False
    assert sorted(set(re.findall(r"secrets\.(\w+)", text))) == ["KOTAK_CONSUMER_KEY"]                      # the Kotak data key, nothing from Zerodha or the relay
    assert "secrets." not in yaml.safe_dump(jobs["publish"]) and jobs["publish"]["permissions"] == {"contents": "write"}
    assert "permissions" not in jobs["morning"] and "permissions" not in jobs["afternoon"]                   # the shards cannot write
    assert not re.search(r"KITE|TOTP|PASSWORD|API_SECRET|INGEST", text.replace("record.yml", ""))
    assert "${{ inputs." not in "".join(s.get("run", "") for j in jobs.values() for s in j["steps"])         # the hand-over reaches the shell as an env var
    on = wf.get("on", wf.get(True))
    assert set(on) == {"schedule", "workflow_dispatch"} and re.fullmatch(r"\d\d:\d\d", on["workflow_dispatch"]["inputs"]["handover"]["default"])
    assert wf["env"]["HANDOVER"] == "${{ inputs.handover || '12:20' }}" and 'HANDOVER"' in text


def test_the_index_recorder_and_its_workflow_are_untouched_and_nothing_here_places_an_order():
    rec = (ROOT / ".github/workflows/record.yml").read_text(encoding="utf-8")
    assert "record-stocks" not in rec and "stock_chains" not in rec and "stock-tape" not in rec and "stock-chains" not in rec
    src = (ROOT / "quantdesk/data/stock_chains.py").read_text(encoding="utf-8")
    assert not re.search(r"place_order|modify_order|cancel_order|/orders|\.positions\(|\.holdings\(", src, re.I)


class _Store:
    def __init__(self, m=None):
        self.m = m

    def tags(self, t): return ["stock-chains-2026Q4"] if self.m else []
    def assets(self, t): return [f"{self.m['day']}_stock_chains_manifest.json"] if self.m else []
    def read(self, t, n): return json.dumps(self.m).encode()


def test_the_health_check_says_how_many_stocks_and_what_share_of_the_minutes_were_recorded():
    from quantdesk.data import health as H
    ok = {"day": str(DAY), "stocks": 200, "recorded": 200, "coverage": 0.97, "attempts": 80000, "failures": 900, "rows": {"chains": 3000000}}
    assert H.check_stock_chains(_Store(ok), DAY).status == H.OK
    assert H.check_stock_chains(_Store({**ok, "coverage": 0.75}), DAY).status == H.WARN                     # a quarter of the minutes missing
    assert H.check_stock_chains(_Store({**ok, "coverage": 0.40}), DAY).status == H.BAD
    few = H.check_stock_chains(_Store({**ok, "recorded": 150}), DAY)
    assert few.status == H.WARN and "150 of 200 stocks" in few.detail
    assert H.check_stock_chains(_Store(), DAY).status == H.MISSING
    assert "check_stock_chains(store, day)" in (ROOT / "quantdesk/data/health.py").read_text(encoding="utf-8")


# ---- what the first review found: the commands exist, the rate is paced and guarded, a bad day cannot replace a good one --------------------------------------------------------------------

def test_the_two_commands_the_workflow_calls_exist_and_parse():
    import subprocess
    import sys
    for cmd, args in (("stock-tape", ["--shard", "0", "--shards", "10", "--part", "morning-0", "--until", "12:20", "--every-min", "1"]),
                      ("stock-chains-publish", ["--parts", "p", "--day", "2026-11-09"])):
        r = subprocess.run([sys.executable, "-m", "quantdesk", "data", cmd, *args, "--help"], capture_output=True, text=True, cwd=ROOT)
        assert r.returncode == 0 and cmd in r.stdout, r.stderr[-300:]
    text = WF.read_text(encoding="utf-8")
    called = set(re.findall(r"quantdesk data (\S+)", text))
    assert called == {"stock-tape", "stock-chains-publish"}                                                  # every command the workflow runs is one this test has parsed


def test_the_first_pass_is_staggered_only_when_asked_and_the_index_tape_still_starts_at_once():
    from quantdesk.intraday.tape import ChainTape
    seen = []

    class Src:
        def expiries(self, u): return [DAY + dt.timedelta(days=3)]
        def chain(self, u, e, ts=None, **kw): seen.append(ts); raise K.KotakError("x")

    for stagger, first_tick_not_before in ((True, "09:15:40"), (False, "09:15:00")):
        clk, seen[:] = Clock("2026-11-09 09:15:00"), []
        t = ChainTape(Src(), Path("x"), {"AAA": 1}, clock=clk, sleep=clk.sleep, offset_s=40.0, stagger_first=stagger, say=lambda *a: None)
        t.log = []
        t._log = lambda row, day: None
        t.run(dt.time(9, 17))
        assert seen and seen[0] >= pd.Timestamp(f"2026-11-09 {first_tick_not_before}", tz=IST)


def test_a_shard_stops_calling_kotak_after_a_run_of_failures_and_resumes_later():
    clk = Clock()
    calls = []

    class Inner:
        def expiries(self, u): return [DAY]
        def chain(self, u, e, **kw): calls.append(clk()); raise K.KotakError("HTTP 429")

    g = SC.GuardedSource(Inner(), now=clk, say=lambda *a: None)
    for _ in range(SC.BREAKER_AFTER):
        with pytest.raises(K.KotakError):
            g.chain("AAA", DAY)
    n = len(calls)
    with pytest.raises(K.KotakError, match="breaker"):
        g.chain("BBB", DAY)                                                                              # open: no call is made
    with pytest.raises(K.KotakError, match="breaker"):
        g.expiries("BBB")
    assert len(calls) == n
    clk.t += pd.Timedelta(seconds=SC.BREAKER_PAUSE_S + 1)
    with pytest.raises(K.KotakError, match="429"):
        g.chain("BBB", DAY)                                                                              # closed again: it tries
    assert len(calls) == n + 1


def test_a_stock_chain_gets_its_spot_and_iv_from_put_call_parity(monkeypatch):
    _chain_parts(monkeypatch)
    clk = Clock()
    src = K.KotakOptionChain(FakeClient(), strikes=10, depth_levels=5)
    monkeypatch.setattr(src, "now", clk, raising=False)
    ch = SC.GuardedSource(src, now=clk).chain("S001", DAY + dt.timedelta(days=17), ts=clk())
    assert ch.attrs["spot"] == ch.attrs["spot"] and ch.attrs["spot"] > 0 and ch.attrs.get("spot_from") == "put-call parity"


def test_an_unreadable_part_costs_only_itself_and_is_counted(tmp_path, monkeypatch):
    _chain_parts(monkeypatch)
    clk = Clock()
    src = K.KotakOptionChain(FakeClient(), strikes=10, depth_levels=5)
    monkeypatch.setattr(src, "now", clk, raising=False)
    SC.run_shard(None, tmp_path / "a", 0, 10, "morning-0", dt.time(9, 18), names=NAMES, source=src, clock=clk, sleep=clk.sleep, say=lambda *a: None)
    parts = tmp_path / "all"
    parts.mkdir()
    for p in (tmp_path / "a" / "_parts").glob("*"):
        (parts / p.name).write_bytes(p.read_bytes())
    (parts / f"{DAY}_morning-9_chains.parquet").write_bytes(b"PAR1 truncated")                           # a job cancelled mid-write
    (parts / f"{DAY}_morning-9_manifest.json").write_text("{not json")
    tot = SC.consolidate(parts, tmp_path / "day", str(DAY))
    assert tot["bad_parts"] == 2 and tot["recorded"] > 0 and tot["rows"]["chains"] > 0 and SC.publishable(tot) == []


def test_the_published_manifest_is_counts_and_stock_names_only():
    base = {"evidence": "stock_chain_tape", "source": "kotak", "day": str(DAY), "note": SC.NOTE, "parts": 3, "stocks": 2, "recorded": 2, "minutes_total": 5, "session_minutes": 375, "attempts": 9,
            "failures": 0, "rows": {"chains": 10, "depth": 20, "tape": 3}, "files": [f"{DAY}_stock_chains.parquet"], "per_stock_minutes": {"AAA": 3, "BBB": 2}, "coverage": 0.1, "bad_parts": 0}
    assert SC.publishable(base) == []
    for bad in ({**base, "rows": {"chains": 1.5}}, {**base, "rows": {"price": 3}}, {**base, "files": ["secrets.txt"]}, {**base, "day": "x" * 20}, {**base, "note": "n" * 700}, {**base, "bad_parts": 1.5}):
        assert SC.publishable(bad)


def test_a_late_or_empty_run_cannot_publish_over_a_good_day(tmp_path, monkeypatch):
    from quantdesk.data import cli as C
    pushed = []

    class Store:
        def __init__(self, tag, **kw): self.tag = tag
        def push(self, folder, names, clobber=True): pushed.append((self.tag, list(names), clobber))
    import quantdesk.data.warehouse as W
    monkeypatch.setattr(W, "ReleaseStore", Store)
    empty = tmp_path / "empty"
    empty.mkdir()
    C.cmd_stock_chains_publish(None, type("A", (), {"parts": str(empty), "day": str(DAY), "out": str(tmp_path / "o1"), "push": True})())
    assert pushed == []                                                                                  # nothing recorded: nothing published
    _chain_parts(monkeypatch)
    clk = Clock()
    src = K.KotakOptionChain(FakeClient(), strikes=10, depth_levels=5)
    monkeypatch.setattr(src, "now", clk, raising=False)
    SC.run_shard(None, tmp_path / "a", 0, 10, "morning-0", dt.time(9, 18), names=NAMES, source=src, clock=clk, sleep=clk.sleep, say=lambda *a: None)
    C.cmd_stock_chains_publish(None, type("A", (), {"parts": str(tmp_path / "a" / "_parts"), "day": str(DAY), "out": str(tmp_path / "o2"), "push": True})())
    assert pushed and all(p[0] == "stock-chains-2026Q4" and p[2] is False for p in pushed)                # a day is written once: never clobbered
    with pytest.raises(SystemExit):
        C.cmd_stock_chains_publish(None, type("A", (), {"parts": "x", "day": "../../etc", "out": str(tmp_path / "o3"), "push": True})())


def test_the_workflow_has_a_gate_holds_the_key_in_one_step_and_offers_a_rollback():
    wf = yaml.safe_load(WF.read_text(encoding="utf-8"))
    jobs = wf["jobs"]
    assert "gate" in jobs and jobs["morning"]["needs"] == "gate" and "gate.outputs.go" in jobs["morning"]["if"] and "skipped" in jobs["afternoon"]["if"] and "skipped" in jobs["publish"]["if"]
    for j in ("morning", "afternoon"):
        assert "env" not in jobs[j]                                                                      # the key is not a job-wide variable
        keyed = [s for s in jobs[j]["steps"] if "KOTAK_CONSUMER_KEY" in yaml.safe_dump(s)]
        assert len(keyed) == 1 and "stock-tape" in keyed[0]["run"]
    on = wf.get("on", wf.get(True))
    assert on["workflow_dispatch"]["inputs"]["every_min"]["default"] == "1" and wf["env"]["EVERY_MIN"] == "${{ inputs.every_min || '1' }}"


def test_a_shard_does_not_fire_at_the_open_but_waits_for_its_own_offset_in_the_minute(tmp_path, monkeypatch):
    _chain_parts(monkeypatch)
    firsts = {}
    for shard in (0, 9):
        clk = Clock("2026-11-09 09:15:00")
        src = K.KotakOptionChain(FakeClient(), strikes=10, depth_levels=5)
        monkeypatch.setattr(src, "now", clk, raising=False)
        SC.run_shard(None, tmp_path / str(shard), shard, 10, f"morning-{shard}", dt.time(9, 18), names=NAMES, source=src, clock=clk, sleep=clk.sleep, say=lambda *a: None)
        ch = pd.read_parquet(tmp_path / str(shard) / "_parts" / f"{DAY}_morning-{shard}_chains.parquet")
        firsts[shard] = pd.Timestamp(ch["ts"].min())
    assert firsts[0] >= pd.Timestamp("2026-11-09 09:15:05", tz=IST) and firsts[9] >= pd.Timestamp("2026-11-09 09:15:50", tz=IST) > firsts[0]     # the shards do not all hit Kotak at 09:15:00
