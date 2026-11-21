"""Audit K-21 (FH-03, HIGH): the wide-data minutes job hit its 90-minute limit every day, so the third stock group (26 of the 80 F&O stocks) never had its option
minutes recorded: zero `options_STOCKS-3` assets on option-minutes-2026Q4 in 25 sessions, and the health check said "UNKNOWN not reached" as a warning only. Now the
step has a budget that fits the measured work with room, the health check always runs after it, and a source not reached turns the run red. Data only: no order,
no account."""
from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path

import pytest
import yaml

from quantdesk.config import DEFAULT_CONFIG, Config
from quantdesk.data import cli as C
from quantdesk.data import collect_wide as W

ROOT = Path(__file__).resolve().parents[1]
WF = yaml.safe_load((ROOT / ".github" / "workflows" / "collect-wide.yml").read_text(encoding="utf-8"))
DAY = dt.date(2026, 11, 20)                                       # a Friday, a trading day
S_PER_STOCK, MIN_PER_INDEX = 57, 28 / 5                           # measured on 20 Nov (run 44717649556): about 57 s a stock; the five indices took about 28 minutes
ROOM = 1.5                                                        # half as much again, for a slow day and a growing list


def test_the_minutes_step_has_a_budget_that_fits_the_measured_work_with_room_and_the_health_check_still_runs():
    S = W.settings(Config.load(DEFAULT_CONFIG))
    job = WF["jobs"]["minutes"]
    step = next(st for st in job["steps"] if "--step minutes" in st.get("run", ""))
    work = len(S["indices"]) * MIN_PER_INDEX + len(S["stocks"]) * S_PER_STOCK / 60
    assert len(S["stocks"]) == 80 and round(work) == 104                                        # the audit's arithmetic: about 105 minutes against 90
    assert step["timeout-minutes"] >= ROOM * work, (step["timeout-minutes"], work)
    assert job["timeout-minutes"] >= step["timeout-minutes"] + 15                               # the health check and the summary fit after a step that hits its own limit
    assert job["timeout-minutes"] <= 359                                                        # under GitHub's six hours


def man(stocks, day=DAY):
    return {"stocks": {s: {"bars": 100, "served": 4, "asked": 4, "last": f"{day} 15:29", "atm_source": "chain"} for s in stocks}}


def rows(reached, stocks=("A", "B", "C"), idx_man=True):
    im = {"underlyings": {"NIFTY": {"bars": 10, "served": 2, "asked": 2, "last": f"{DAY} 15:29"}}} if idx_man else None
    return W.health(DAY, im, [], [], ["NIFTY"], 3, man(reached), stocks)


def test_not_reached_names_only_minute_sources_the_step_never_got_to():
    assert W.not_reached(rows(("A", "B", "C"))) == []
    assert W.not_reached(rows(("A",))) == ["stock_minutes:B", "stock_minutes:C"]               # the 20 Nov case: the step was killed before the last group
    assert W.not_reached(rows(("A", "B", "C"), idx_man=False)) == ["minutes:NIFTY"]
    r = rows(("A", "B", "C"))
    r.append({"source": "stock_minutes:Z", "status": "MISSING", "detail": "no option bars"})      # asked and nothing served (a name Kotak does not know): said, not red
    r.append({"source": "stock_chains", "status": "UNKNOWN", "detail": "release not readable"})   # not a minute source
    assert W.not_reached(r) == []


def health_run(tmp_path, monkeypatch, reached, strict=True, day=DAY):
    out = tmp_path / "collect"
    (out / "minutes" / str(day)).mkdir(parents=True)
    (out / "minutes" / str(day) / "manifest.json").write_text(json.dumps({"underlyings": {u: {"bars": 10, "served": 2, "asked": 2, "last": f"{day} 15:29"}
                                                                                         for u in ("NIFTY", "BANKNIFTY", "SENSEX", "FINNIFTY", "MIDCPNIFTY")}}))
    cfg = Config.load(DEFAULT_CONFIG)
    stocks = W.settings(cfg)["stocks"]
    (out / "minutes_stocks" / str(day)).mkdir(parents=True)
    (out / "minutes_stocks" / str(day) / "stock_manifest.json").write_text(json.dumps(man(stocks[:reached], day)))
    a = argparse.Namespace(step="health", day=str(day), part="local", force=False, out=str(out), push=False, strict=strict)
    return C.cmd_collect_wide(cfg, a)


def test_health_with_strict_is_red_when_stocks_were_not_reached_and_green_when_all_were(tmp_path, monkeypatch, capsys):
    with pytest.raises(SystemExit) as e:
        health_run(tmp_path, monkeypatch, reached=54)                                         # 26 of 80 not reached, as every day since 19 Oct
    assert e.value.code == 1
    err = capsys.readouterr().out
    assert "::error::" in err and "26 minute source(s) not reached" in err and "JIOFIN" in err
    assert health_run(tmp_path / "b", monkeypatch, reached=80) is None                       # everything reached: green


def test_without_strict_the_old_behaviour_is_kept_and_a_non_trading_day_is_never_red(tmp_path, monkeypatch):
    assert health_run(tmp_path, monkeypatch, reached=54, strict=False) is None
    assert health_run(tmp_path / "h", monkeypatch, reached=0, day=dt.date(2026, 11, 22)) is None     # a Sunday: nothing expected


def test_strict_is_red_when_the_check_itself_did_not_finish(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(W, "health", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    with pytest.raises(SystemExit) as e:
        health_run(tmp_path, monkeypatch, reached=80)
    assert e.value.code == 1 and "did not finish" in capsys.readouterr().out


def test_the_health_step_is_strict_and_red_and_the_pipe_keeps_its_status():
    st = next(st for st in WF["jobs"]["minutes"]["steps"] if "--step health" in st.get("run", ""))
    assert "--strict" in st["run"] and "set -o pipefail" in st["run"] and "|| echo" not in st["run"]
    assert st["if"] == "always()" and "continue-on-error" not in st
