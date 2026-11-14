"""The owner's release from probation (docs/prereg/evolution_probation_v1.json: "a third demotion within REPEAT_WINDOW of the second release leaves it in probation until
the owner releases it").

What is pinned: the app builds a release request ({id, side: "release", sid}) and sends it the same way as a paper order, on the owner's key, after a confirm step,
for a strategy whose release is the owner's; the relay accepts exactly that shape and drops anything else; the runner takes release requests out before the risk
gate (a release is no order and moves no money) and posts a result like any other; AUTO v2 releases only a strategy that is in probation, records it, and saves it;
a released strategy has its ordinary rules back and nothing more."""
from __future__ import annotations

import datetime as dt
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from quantdesk.paper import auto2 as A2
from tests.test_paper_auto import T0
from tests.test_paper_auto2 import IC, cfg, desk  # noqa: F401  (cfg is a fixture)
from tests.test_paper_session import IST, Clock, FakeRelay, S, _Pilot
from tests.test_paper_ticket import block

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "quantdesk/web/static/app/app.js").read_text(encoding="utf-8")
needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="Node is not installed")


def in_probation(ap, sid, owner=True):
    ap.probation.st[sid] = {"g": 6.0, "pend": None, "P": {"since": "2026-11-06", "n": 0, "ses": 0, "sm": 0.0, "mult": 1, "owner": owner}, "rel": "2026-10-01", "rep": 2}


# ---- the app and the relay --------------------------------------------------------------------------------------------------------------------------
@needs_node
def test_the_apps_release_request_is_exactly_what_the_relay_accepts(tmp_path):
    shutil.copyfile(ROOT / "deploy/cloudflare/paper.js", tmp_path / "paper.mjs")
    (tmp_path / "t.mjs").write_text(block() + """
import { cleanOrder } from './paper.mjs';
const r = PT.releaseFor("IC1.faan.1/0.5.d");
const out = { built: r, accepted: cleanOrder(r),
  extra: cleanOrder({ ...r, lots: 999, symbol: "NIFTY", side: "release" }),
  bad: ["", "x", "<script>", "IC1 faan", "a".repeat(61), 5, null].map((sid) => cleanOrder({ ...r, sid })),
  noid: cleanOrder({ side: "release", sid: "IC1.faan.1/0.5.d" }) };
console.log(JSON.stringify(out));
""", encoding="utf-8")
    res = subprocess.run(["node", "t.mjs"], cwd=tmp_path, capture_output=True, text=True, timeout=60)
    assert res.returncode == 0, res.stderr[-2000:]
    o = json.loads(res.stdout.strip().splitlines()[-1])
    assert o["built"]["side"] == "release" and o["built"]["sid"] == "IC1.faan.1/0.5.d" and re.fullmatch(r"ord-[0-9a-f]{32}", o["built"]["id"])
    assert o["accepted"] == o["built"]
    assert o["extra"] == o["built"]                                                            # nothing else rides along: a release carries no lots and no symbol
    assert o["bad"] == [None] * 7 and o["noid"] is None
    assert all(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]{2,59}", s) for s in A2.BY_SID)         # every real strategy id passes the relay's rule


def test_the_release_button_is_the_owners_only_and_confirms_first():
    part = APP[APP.index("function ppReleaseBtn"):APP.index("function ppAdapt")]
    assert 'paperCall("POST", "/paper/order", PT.releaseFor(sid))' in part and "Yes, release it" in part and "Cancel" in part and "P.confirm" in part
    adapt = APP[APP.index("function ppAdapt"):APP.index("function ppMarket")]
    assert "r.owner ? ppReleaseBtn(r.sid, r.since)" in adapt                                  # shown only where the release is the owner's


# ---- the runner --------------------------------------------------------------------------------------------------------------------------------------
class _Releasing(_Pilot):
    def __init__(self):
        super().__init__()
        self.released = []

    def owner_release(self, sid, now):
        self.released.append(sid)
        return (sid == "IC1.faan.1/0.5.d", "released" if sid == "IC1.faan.1/0.5.d" else "not in probation")


def run_with(cfg, tmp_path, relay, clk, pilot):
    return S.run(cfg, relay, tmp_path / "ledger" / "account.json", (clk.t + dt.timedelta(minutes=1)).astimezone(IST).time(), every_s=3.0, clock=clk, sleep=clk.sleep,
                 say=lambda *a: None, new_account=True, auto=pilot)


def test_the_runner_applies_a_release_outside_the_gate_and_reports_it(cfg, tmp_path):
    clk = Clock()
    rl = FakeRelay(clk)
    rl.orders = [{"id": "ord-rel00001", "side": "release", "sid": "IC1.faan.1/0.5.d"}, {"id": "ord-rel00002", "side": "release", "sid": "LC0.uran.0.5/0.5.d"}]
    pilot = _Releasing()
    run_with(cfg, tmp_path, rl, clk, pilot)
    assert pilot.released == ["IC1.faan.1/0.5.d", "LC0.uran.0.5/0.5.d"]                        # each applied once, though the queue is read every cycle
    by = {r["id"]: r for r in rl.results}
    assert by["ord-rel00001"]["status"] == "done" and by["ord-rel00002"]["status"] == "refused" and by["ord-rel00002"]["reasons"] == ["not in probation"]
    assert not rl.orders                                                                       # the result took them off the queue
    ledger = json.loads((tmp_path / "ledger" / "account.json").read_text())["ledger"]
    assert not any(r.get("kind") == "fill" for r in ledger)                                    # no order, no money


def test_without_auto_v2_a_release_is_refused_not_lost(cfg, tmp_path):
    clk = Clock()
    rl = FakeRelay(clk)
    rl.orders = [{"id": "ord-rel00003", "side": "release", "sid": "IC1.faan.1/0.5.d"}]
    run_with(cfg, tmp_path, rl, clk, None)
    assert rl.results and rl.results[0]["status"] == "refused" and "not running" in rl.results[0]["reasons"][0]


# ---- AUTO v2 -----------------------------------------------------------------------------------------------------------------------------------------
def test_auto_v2_releases_only_a_strategy_in_probation_and_keeps_it(cfg, tmp_path):
    rn, ap = desk(cfg, tmp_path)
    assert ap.owner_release("NOPE", T0) == (False, "no such strategy")
    assert ap.owner_release(None, T0) == (False, "no such strategy")
    assert ap.owner_release(IC, T0) == (False, "not in probation")
    in_probation(ap, IC)
    ap.lab.dirty = ap.shadow_dirty = False
    ok, why = ap.owner_release(IC, T0)
    assert ok and "still needs its proof" in why and not ap.probation.blocked(IC)
    assert ap.probation.st[IC]["rel"] == T0.date().isoformat() and ap.probation.st[IC]["rep"] == 2    # the repeat count stays: a quick fourth demotion is the owner's again
    assert ap.probation.events[-1][1:3] == [IC, "released"] and ap.probation.events[-1][3] == {"by": "owner"}
    assert ap.lab.dirty and ap.shadow_dirty
    assert ap.probation.pset(T0.date().isoformat())[IC][0] is None                             # the record's list: released, with its last release kept
    assert ap.owner_release(IC, T0) == (False, "not in probation")                             # a second request (a restart before its result) changes nothing
