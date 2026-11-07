"""MCX and currency minutes, collected after their sessions (quantdesk/data/evening_minutes.py, evening-minutes.yml): the contract choice, the per-name and per-segment fail-soft
behaviour, the files and manifest, the time budget, and the workflow's isolation. A fake Kotak stands in for the network."""
from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path

import pandas as pd
import pytest
import yaml

from quantdesk.data import evening_minutes as E
from quantdesk.intraday.feeds import IST
from quantdesk.intraday.kotak import KotakError

ROOT = Path(__file__).resolve().parents[1]
WF = ROOT / ".github" / "workflows" / "evening-minutes.yml"
TODAY = dt.date(2026, 11, 9)


def _contracts(exchange, name, near=dt.date(2026, 11, 20), far=dt.date(2026, 12, 19)):
    rows = []
    for exp in (near, far):
        rows.append({"inst": {"neoSymbol": f"{exchange}|{name}-{exp:%b}", "symbol": f"{name}{exp:%d%b%y}".upper(), "exp": str(exp)}, "quote": {"ltp": 1.0}, "oi": {"cur": 1}})
    return {"future_contracts": rows}


def _bars(day=TODAY, n=5):
    idx = pd.date_range(dt.datetime.combine(day, dt.time(17, 0)), periods=n, freq="min", tz=IST)
    return pd.DataFrame({"open": 1.0, "high": 1.2, "low": 0.9, "close": 1.1, "volume": 10.0}, index=idx)


class FakeKotak:
    def __init__(self, names=None, fail_contracts=(), empty=(), raise_candles=()):
        self.names = names or {"mcx_fo": ["GOLD", "SILVER"], "cde_fo": ["USDINR"]}
        self.fail_contracts, self.empty, self.raise_candles = set(fail_contracts), set(empty), set(raise_candles)
        self.paths, self.asked = [], []

    def _get(self, path, params=None):
        self.paths.append((path, dict(params or {})))
        name, ex = params["underlying"], params["exchange"]
        if name in self.fail_contracts:
            raise KotakError(f"no futures for {name}")
        return _contracts(ex, name)

    def candles(self, token, interval, start, end, raw=False):
        self.asked.append((token, interval, start, end))
        name = token.split("|")[1].split("-")[0]
        if name in self.raise_candles:
            raise KotakError("HTTP 400 bad request")
        if name in self.empty:
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
        return _bars()


def _master(monkeypatch, per_exchange):
    def fake(client, name):
        v = per_exchange[name]
        if isinstance(v, Exception):
            raise v
        return v
    monkeypatch.setattr(E, "scrip_master", fake)


def _frame(rows):
    return pd.DataFrame(rows, columns=["pSymbolName", "pInstType"])


def _go(tmp_path, client, **kw):
    return E.run(client, tmp_path, TODAY, days=3, say=lambda *a: None, rate=1000.0, sleep=lambda s: None, **kw)


def test_the_futures_underlyings_come_from_the_scrip_master_and_everything_seen_is_listed():
    f = _frame([("GOLD", "FUTCOM"), ("gold ", "FUTCOM"), ("GOLD", "OPTFUT"), ("SILVER", "FUTCOM"), ("USDINR", "FUTCUR"), ("", "FUTCOM"), ("CRUDEOIL", "OPTFUT")])
    names, kinds = E.future_underlyings(f)
    assert names == ["GOLD", "SILVER", "USDINR"] and kinds == ["FUTCOM", "FUTCUR", "OPTFUT"]            # an option-only name is not a future; blanks are dropped
    assert E.future_underlyings(pd.DataFrame({"other": [1]})) == ([], [])                               # no such columns: nothing, and no crash


def test_a_run_collects_the_near_month_future_of_every_name_and_writes_files_and_a_manifest(tmp_path, monkeypatch):
    _master(monkeypatch, {"mcx_fo": _frame([("GOLD", "FUTCOM"), ("SILVER", "FUTCOM")]), "cde_fo": _frame([("USDINR", "FUTCUR")])})
    k = FakeKotak()
    man = _go(tmp_path, k)
    run = tmp_path / str(TODAY)
    assert man["totals"] == {"mcx": {"asked": 2, "served": 2, "failed": 0, "empty": 0, "not_attempted": 0}, "cds": {"asked": 1, "served": 1, "failed": 0, "empty": 0, "not_attempted": 0}}
    mcx = pd.read_parquet(run / "mcx_minutes.parquet")
    assert list(mcx.columns) == E.COLS and set(mcx["underlying"]) == {"GOLD", "SILVER"} and (mcx["segment"] == "mcx").all() and len(mcx) == 10
    assert (mcx["expiry"] == "2026-11-20").all() and mcx["token"].str.startswith("mcx_fo|").all()      # the near month, on the right exchange
    cds = pd.read_parquet(run / "cds_minutes.parquet")
    assert set(cds["underlying"]) == {"USDINR"} and cds["token"].iloc[0].startswith("cde_fo|")
    on_disk = json.loads((run / "manifest.json").read_text())
    assert on_disk["window"] == ["2026-11-06", "2026-11-09"] and on_disk["segments"]["mcx"]["underlyings_seen"] == ["GOLD", "SILVER"] and on_disk["evidence"] == E.EVIDENCE
    assert {p[1]["exchange"] for p in k.paths} == {"mcx_fo", "cde_fo"} and all(p[1]["instrument_type"] == "fut" for p in k.paths)
    assert {a[1] for a in k.asked} == {"1min"} and {(a[2], a[3]) for a in k.asked} == {(dt.date(2026, 11, 6), TODAY)}
    assert E.release_names(run) == ["cds_minutes.parquet", "manifest.json", "mcx_minutes.parquet"]


def test_a_name_kotak_does_not_serve_is_recorded_and_the_rest_still_run(tmp_path, monkeypatch):
    _master(monkeypatch, {"mcx_fo": _frame([("GOLD", "FUTCOM"), ("SILVER", "FUTCOM"), ("COPPER", "FUTCOM"), ("ZINC", "FUTCOM")]), "cde_fo": _frame([("USDINR", "FUTCUR")])})
    man = _go(tmp_path, FakeKotak(fail_contracts={"SILVER"}, empty={"COPPER"}, raise_candles={"ZINC"}))
    names = man["segments"]["mcx"]["names"]
    assert names["GOLD"]["status"] == "served" and names["SILVER"]["status"] == "failed" and "contracts" in names["SILVER"]["error"]
    assert names["COPPER"]["status"] == "empty" and names["ZINC"]["status"] == "failed"
    assert man["totals"]["mcx"] == {"asked": 4, "served": 1, "failed": 2, "empty": 1, "not_attempted": 0} and man["totals"]["cds"]["served"] == 1


def test_a_segment_whose_master_is_unreadable_or_has_no_futures_is_recorded_not_raised(tmp_path, monkeypatch):
    _master(monkeypatch, {"mcx_fo": KotakError("no mcx_fo file in the scrip master (6 files)"), "cde_fo": _frame([("USDINR", "OPTCUR")])})
    man = _go(tmp_path, FakeKotak())
    assert "scrip master" in man["segments"]["mcx"]["error"]
    assert "no future found" in man["segments"]["cds"]["error"] and "OPTCUR" in man["segments"]["cds"]["error"]       # says what it did see, so the first run teaches the next fix
    assert man["segments"]["cds"]["instrument_types_seen"] == ["OPTCUR"] and man["totals"] == {} and not (tmp_path / str(TODAY) / "mcx_minutes.parquet").exists()
    assert (tmp_path / str(TODAY) / "manifest.json").exists()


def test_the_time_budget_stops_cleanly_and_records_what_was_not_reached(tmp_path, monkeypatch):
    _master(monkeypatch, {"mcx_fo": _frame([(n, "FUTCOM") for n in ("A", "B", "C", "D")]), "cde_fo": _frame([("USDINR", "FUTCUR")])})
    t = {"now": 0.0}

    def clock():
        t["now"] += 1.0                                          # every look at the clock costs a second
        return t["now"]
    man = E.run(FakeKotak(), tmp_path, TODAY, days=3, say=lambda *a: None, rate=1000.0, budget_s=12.0, sleep=lambda s: None, clock=clock)
    names = man["segments"]["mcx"]["names"]
    assert man["stopped"] == "time budget" and any(v["status"] == "not_attempted" for v in names.values()) and names["A"]["status"] == "served"
    assert man["totals"]["mcx"]["not_attempted"] >= 1


def test_a_run_after_midnight_belongs_to_the_evening_it_collects():
    ist = lambda s: pd.Timestamp(s, tz=IST)                      # noqa: E731
    assert E.session_day(ist("2026-11-06 23:45")) == dt.date(2026, 11, 6)                        # on time
    assert E.session_day(ist("2026-11-07 01:10")) == dt.date(2026, 11, 6)                        # a late cron: still Friday's evening
    assert E.session_day(ist("2026-11-07 05:59")) == dt.date(2026, 11, 6)
    assert E.session_day(ist("2026-11-07 06:00")) == dt.date(2026, 11, 7)
    cli = (ROOT / "quantdesk/data/cli.py").read_text(encoding="utf-8")
    assert "E.session_day(pd.Timestamp.now(tz=TZ))" in cli                                          # the command uses it


def test_the_collector_can_not_place_an_order_and_the_command_never_fails_a_run():
    src = (ROOT / "quantdesk/data/evening_minutes.py").read_text(encoding="utf-8")
    assert not re.search(r"place_order|\.order\(|modify_order|cancel_order|/orders|\bquick\b|trade\.", src, re.I)
    cli = (ROOT / "quantdesk/data/cli.py").read_text(encoding="utf-8")
    body = cli[cli.index("def cmd_evening_minutes"):cli.index("def cmd_external_verify")]
    assert "::warning::" in body and "clobber=False" in body and "no KOTAK_CONSUMER_KEY" in body                  # a problem is a warning; a name already on the release is never replaced
    assert '"evening-minutes"' in cli and "fn=cmd_evening_minutes" in cli


def test_the_workflow_runs_after_the_evening_close_holds_one_secret_and_is_isolated():
    text = WF.read_text(encoding="utf-8")
    wf = yaml.safe_load(text)
    on = wf.get("on", wf.get(True))
    assert on["schedule"] == [{"cron": "15 18 * * 1-5"}] and "workflow_dispatch" in on                      # 23:45 IST, Monday to Friday; by hand for a 30-day backfill
    assert wf["permissions"] == {"contents": "write"}
    assert sorted(set(re.findall(r"secrets\.(\w+)", text))) == ["KOTAK_CONSUMER_KEY"]                         # the one Kotak key, nothing from Zerodha
    assert not re.search(r"KITE_|LIVE_|TOTP|PASSWORD|API_SECRET|secrets\.(?!KOTAK_CONSUMER_KEY)", text)                  # no Zerodha secret, no relay token, no other secret
    for uses in re.findall(r"uses:\s*(\S+)", text):
        assert re.fullmatch(r"[\w./-]+@[0-9a-f]{40}", uses), uses
    live = yaml.safe_load((ROOT / ".github/workflows/kite-record.yml").read_text(encoding="utf-8"))
    rec = yaml.safe_load((ROOT / ".github/workflows/record.yml").read_text(encoding="utf-8"))
    assert wf["concurrency"]["group"] == "evening-minutes" not in (live["concurrency"]["group"], rec["concurrency"]["group"])
    steps = wf["jobs"]["evening"]["steps"]
    run = next(s for s in steps if "evening-minutes" in s.get("run", ""))
    assert "${{ inputs." not in run["run"] and run["env"]["DAYS"] == "${{ inputs.days || '3' }}" and "KOTAK_CONSUMER_KEY" in run["env"]       # the input reaches the shell as an env var, validated as a number
    assert "[[ \"$DAYS\" =~ ^[0-9]{1,2}$ ]]" in run["run"] and "|| echo \"::warning::" in run["run"]


def test_nothing_in_the_kite_recorder_or_its_trial_changed():
    """The evening collector is a separate workflow and module: the pre-registered Kite trial's recorder is not touched by it."""
    kite = (ROOT / ".github/workflows/kite-record.yml").read_text(encoding="utf-8")
    assert "evening" not in kite.lower().replace("late evening", "")
    assert not (ROOT / "quantdesk/data/kite_record.py").read_text(encoding="utf-8").count("evening_minutes")
