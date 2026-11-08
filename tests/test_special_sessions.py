"""Special sessions (config `calendar.special_sessions`): a trading window on a day that is normally closed, e.g. Muhurat trading on Diwali, 8 Nov 2026, 14:20 to 15:30 IST (NSE circular
NSE/CMTR/76941 of 19 Oct 2026). It counts only for TRADING questions (the paper gate) and for the relay's Kotak poller; recording calendars, health reports and every other segment are unchanged."""
from __future__ import annotations

import datetime as dt
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from quantdesk.config import Config
from quantdesk.markets import sessions as MK
from quantdesk.paper.account import Account
from quantdesk.paper.broker import PaperBroker
from quantdesk.paper.risk import KillSwitch, Order, Quote, RiskGate
from quantdesk.core.types import Instrument

ROOT = Path(__file__).resolve().parents[1]
IST = MK.IST
DIWALI = dt.date(2026, 11, 8)
needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="Node is not installed")


@pytest.fixture()
def cfg():
    return Config.load(ROOT / "config" / "quantdesk.yaml")


def at(h, m, day=DIWALI):
    return dt.datetime.combine(day, dt.time(h, m), tzinfo=IST)


def test_the_config_names_todays_muhurat_window_and_only_that(cfg):
    assert cfg.special_sessions() == {DIWALI: (dt.time(14, 20), dt.time(15, 30))}


def test_the_special_window_counts_for_trading_questions_only_and_only_for_nse_and_bse(cfg):
    cal = MK.Calendars(cfg)
    assert MK.session("nse_fo", DIWALI, cal, trading=True) == (at(14, 20), at(15, 30)) and MK.session("bse_fo", DIWALI, cal, trading=True) == (at(14, 20), at(15, 30))
    assert MK.session("nse_fo", DIWALI, cal, trading=False) is None and MK.open_segments(at(14, 30), cal, trading=False) == []                  # the recording calendar is unchanged
    assert MK.session("mcx", DIWALI, cal, trading=True) is None and MK.session("nse_cds", DIWALI, cal, trading=True) is None                # not the commodity or currency markets
    assert MK.open_segments(at(14, 30), cal, trading=True) == ["nse_fo", "bse_fo"] and MK.open_segments(at(14, 19), cal, trading=True) == [] and MK.open_segments(at(15, 30), cal, trading=True) == []
    for other in (dt.date(2026, 11, 7), dt.date(2026, 11, 15), dt.date(2026, 11, 14)):                                                      # other weekends stay shut
        assert MK.session("nse_fo", other, cal, trading=True) is None
    assert MK.session("nse_fo", dt.date(2026, 11, 9), cal, trading=True) == (at(9, 15, dt.date(2026, 11, 9)), at(15, 30, dt.date(2026, 11, 9)))   # an ordinary Monday is untouched
    assert MK.day_window(DIWALI, cal) is None and MK.plan_jobs(DIWALI, cal) == []                                                            # recorders' planning does not see it


@pytest.mark.parametrize("bad", ["x", [], ["14:20"], ["15:30", "14:20"], ["14:20", "14:20"], ["25:00", "26:00"], {"a": 1}])
def test_a_malformed_special_session_fails_closed_instead_of_guessing_a_window(cfg, bad):
    real = cfg.get
    cfg.get = lambda key, default=None: ({DIWALI: bad} if bad != "x" else "x") if key == "calendar.special_sessions" else real(key, default)
    with pytest.raises((ValueError, TypeError)):
        MK.Calendars(cfg)


def test_the_paper_gate_opens_for_the_muhurat_window_and_not_a_minute_either_side_or_on_other_sundays(cfg, tmp_path):
    inst = Instrument.option("NIFTY", dt.date(2026, 11, 12), 24500, "CE", 65)
    order = Order(inst, "nse_fo", 65, "muhurat", "range break with rising volume, 30m")

    def tries(now):
        acct = Account(500_000)
        b = PaperBroker(cfg, acct, RiskGate(cfg, kill=KillSwitch(tmp_path / "K")))
        return b.buy(order, Quote(99.0, 100.0, now - dt.timedelta(seconds=2), 5000, 5000), {}, now)[0]

    assert tries(at(14, 20)).allowed and tries(at(15, 29)).allowed
    for closed in (at(14, 19), at(15, 30), at(9, 30), at(14, 30, dt.date(2026, 11, 15)), at(14, 30, dt.date(2026, 11, 7))):
        d = tries(closed)
        assert not d.allowed and any("closed" in r or "holiday" in r or "open" in r for r in d.reasons), (closed, d.reasons)


@needs_node
def test_the_relays_poller_follows_the_same_window_and_the_two_lists_agree(cfg, tmp_path):
    shutil.copyfile(ROOT / "deploy/cloudflare/kotak.js", tmp_path / "kotak.js")
    (tmp_path / "package.json").write_text('{"type": "module"}', encoding="utf-8")
    ms = lambda d, h, m: int(dt.datetime.combine(d, dt.time(h, m), tzinfo=IST).timestamp() * 1000)          # noqa: E731
    probes = {"in": ms(DIWALI, 14, 30), "early": ms(DIWALI, 14, 10), "openMinus5": ms(DIWALI, 14, 15), "closePlus": ms(DIWALI, 15, 34), "late": ms(DIWALI, 15, 35), "morning": ms(DIWALI, 10, 0),
              "nextSunday": ms(dt.date(2026, 11, 15), 14, 30), "monday": ms(dt.date(2026, 11, 9), 10, 0), "mondayNight": ms(dt.date(2026, 11, 9), 16, 0)}
    (tmp_path / "t.mjs").write_text("import { inSession, SPECIAL_SESSIONS } from './kotak.js';\nconst p = " + json.dumps(probes) + ";\nconst o = {};\nfor (const [k, v] of Object.entries(p)) o[k] = inSession(v);\nconsole.log(JSON.stringify({ o, sp: SPECIAL_SESSIONS }));\n", encoding="utf-8")
    r = subprocess.run(["node", "t.mjs"], cwd=tmp_path, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr[-1500:]
    out = json.loads(r.stdout.strip().splitlines()[-1])
    assert out["o"] == {"in": True, "early": False, "openMinus5": True, "closePlus": True, "late": False, "morning": False, "nextSunday": False, "monday": True, "mondayNight": False}
    want = {str(d): [o.hour * 60 + o.minute - 5, c.hour * 60 + c.minute + 5] for d, (o, c) in cfg.special_sessions().items()}
    assert out["sp"] == want                                                                                      # the relay's copy equals the config: five minutes either side
    live = (ROOT / "deploy/cloudflare/live.js").read_text(encoding="utf-8")
    assert "SPECIAL_SESSIONS" in live[live.index("/needs-universe"):live.index("/needs-universe") + 600] or re.search(r'path === "/needs-universe"[\s\S]{0,700}SPECIAL_SESSIONS', live)


def test_a_position_bought_in_the_special_window_can_be_sold_in_it_and_not_outside_or_on_other_sundays(cfg, tmp_path):
    inst = Instrument.option("NIFTY", dt.date(2026, 11, 12), 24500, "CE", 65)
    order = Order(inst, "nse_fo", 65, "muhurat", "range break with rising volume, 30m")

    def held():
        acct = Account(500_000)
        b = PaperBroker(cfg, acct, RiskGate(cfg, kill=KillSwitch(tmp_path / "K")))
        assert b.buy(order, Quote(99.0, 100.0, at(14, 30) - dt.timedelta(seconds=2), 5000, 5000), {}, at(14, 30))[0].allowed
        return b

    def sell(now):
        return held().sell(inst.symbol, 65, Quote(99.0, 100.0, now - dt.timedelta(seconds=2), 5000, 5000), now)[0]

    assert sell(at(14, 31)).allowed and sell(at(15, 29)).allowed
    for closed in (at(14, 19), at(15, 30), at(14, 30, dt.date(2026, 11, 15))):
        d = sell(closed)
        assert not d.allowed and any("closed" in r for r in d.reasons), (closed, d.reasons)
    cal = MK.Calendars(cfg)
    assert MK.exit_session("nse_fo", DIWALI, cal) == (at(14, 20), at(15, 30)) and MK.exit_session("nse_fo", dt.date(2026, 11, 7), cal) is None
    assert MK.exit_session("nse_fo", dt.date(2026, 11, 9), cal) == MK.session("nse_fo", dt.date(2026, 11, 9), cal)             # ordinary days: exactly as before
