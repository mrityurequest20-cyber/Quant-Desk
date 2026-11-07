"""MCX and currency evening candles from Kite (quantdesk/data/kite_evening.py, deploy/kite_evening_gate.py, kite-evening.yml): the contracts picked, the candles collected and kept off the
public record, the give-up rule, the login gate, and the workflow's isolation. A fake Kite stands in: no network, no login."""
from __future__ import annotations

import datetime as dt
import json
import re
import sys
from pathlib import Path

import pandas as pd
import pytest
import yaml

from quantdesk.data import kite_evening as KE

ROOT = Path(__file__).resolve().parents[1]
WF = ROOT / ".github/workflows/kite-evening.yml"
sys.path.insert(0, str(ROOT / "deploy"))
import kite_evening_gate as G  # noqa: E402

TODAY = dt.date(2026, 11, 9)
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))


def _instr(rows):
    return pd.DataFrame(rows, columns=["instrument_token", "tradingsymbol", "name", "expiry", "instrument_type"])


MCX = _instr([(1, "GOLDM26NOVFUT", "GOLDM", "2026-11-05", "FUT"),          # expired: never picked
              (2, "GOLDM26DECFUT", "GOLDM", "2026-12-04", "FUT"),
              (3, "GOLDM27JANFUT", "GOLDM", "2027-01-05", "FUT"),
              (4, "GOLDM27FEBFUT", "GOLDM", "2027-02-05", "FUT"),          # a third: beyond the two kept
              (5, "CRUDEOIL26NOVFUT", "CRUDEOIL", "2026-11-19", "FUT"),
              (6, "CRUDEOIL26NOV5000CE", "CRUDEOIL", "2026-11-19", "CE")])   # an option: never picked
CDS = _instr([(7, "USDINR26NOVFUT", "USDINR", "2026-11-27", "FUT"), (8, "USDINR26DECFUT", "USDINR", "2026-12-29", "FUT")])


def _candles(day, n=5, start=9, base=100.0):
    t0 = dt.datetime(*day.timetuple()[:3], start, 0, tzinfo=IST)
    return [{"date": t0 + dt.timedelta(minutes=i), "open": base + i, "high": base + i + 1, "low": base + i - 1, "close": base + i + 0.5, "volume": 10 + i, "oi": 1000 + i} for i in range(n)]


class FakeKite:
    def __init__(self, fail=(), empty=(), all_fail=False):
        self.calls, self.fail, self.empty, self.all_fail = [], set(fail), set(empty), all_fail

    def instruments(self, exchange):
        return {"MCX": MCX, "CDS": CDS}[exchange].to_dict("records")

    def historical_data(self, token, a, b, interval, continuous=False, oi=False):
        self.calls.append((token, interval, continuous, oi))
        if self.all_fail or token in self.fail:
            raise RuntimeError("Insufficient permission for that call.")
        if token in self.empty:
            return []
        if interval == "day":
            return [{"date": dt.datetime(2026, 11, d), "open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "volume": 5, "oi": 9} for d in (2, 3, 4)]
        return _candles(TODAY)


def _run(tmp_path, kite=None, **kw):
    kite = kite or FakeKite()
    return KE.run(kite, tmp_path, TODAY, say=lambda *a: None, sleep=lambda s: None, **kw), kite


def test_the_nearest_two_unexpired_futures_of_each_underlying_are_picked_and_nothing_else():
    got = KE.pick_futures(MCX, TODAY)
    assert [(g["name"], g["token"], g["rank"]) for g in got] == [("CRUDEOIL", 5, 1), ("GOLDM", 2, 1), ("GOLDM", 3, 2)]           # the expired, the third and the option are out
    assert got[1]["expiry"] == dt.date(2026, 12, 4) and got[1]["symbol"] == "GOLDM26DECFUT"
    assert KE.pick_futures(pd.DataFrame(), TODAY) == [] and KE.pick_futures(MCX.drop(columns=["name"]), TODAY) == []


def test_a_run_collects_minutes_for_each_future_and_writes_the_data_apart_from_the_manifest(tmp_path):
    man, kite = _run(tmp_path, days=3)
    run = tmp_path / str(TODAY)
    assert man["totals"]["mcx"] == {"asked": 3, "served": 3, "failed": 0, "empty": 0, "not_attempted": 0} and man["totals"]["cds"]["served"] == 2 and man["stopped"] is None
    mins = pd.read_parquet(run / "data/mcx_minutes.parquet")
    assert set(mins["underlying"]) == {"CRUDEOIL", "GOLDM"} and set(mins["rank"]) == {1, 2} and len(mins) == 15 and mins["oi"].notna().all()
    assert str(pd.DatetimeIndex(mins["ts"]).tz) in ("UTC+05:30", "+05:30") or pd.DatetimeIndex(mins["ts"]).tz is not None
    assert all(c[1] == "minute" and c[3] is True for c in kite.calls)                                  # minutes only, with open interest, by default
    assert json.loads((run / "manifest.json").read_text())["source"] == "kite" and not list(run.glob("*.parquet"))             # the candles live under data/, the manifest beside it


def test_the_daily_history_is_asked_once_per_underlying_on_the_continuous_series(tmp_path):
    man, kite = _run(tmp_path, days=3, daily_days=1500)
    days = [c for c in kite.calls if c[1] == "day"]
    assert len(days) == 3 and all(c[2] is True for c in days)                                          # GOLDM, CRUDEOIL, USDINR: rank 1 only, continuous
    d = pd.read_parquet(tmp_path / str(TODAY) / "data/mcx_daily.parquet")
    assert len(d) == 6 and man["segments"]["mcx"]["names"]["GOLDM#1"]["daily"] == {"status": "served", "bars": 3} and "daily" not in man["segments"]["mcx"]["names"]["GOLDM#2"]


def test_a_refused_empty_or_missing_instrument_is_recorded_and_never_raises(tmp_path):
    man, _ = _run(tmp_path, FakeKite(fail={2}, empty={7}))
    n = man["segments"]["mcx"]["names"]
    assert n["GOLDM#1"]["status"] == "failed" and "Insufficient permission" in n["GOLDM#1"]["error"] and n["GOLDM#2"]["status"] == "served"
    assert man["totals"]["mcx"]["failed"] == 1 and man["totals"]["cds"]["empty"] == 1 and man["totals"]["cds"]["served"] == 1

    class NoList(FakeKite):
        def instruments(self, exchange):
            if exchange == "MCX":
                raise ConnectionError("down")
            return super().instruments(exchange)
    man, _ = _run(tmp_path / "b", NoList())
    assert "instruments" in man["segments"]["mcx"]["error"] and man["totals"]["cds"]["served"] == 2             # one segment's list failing never stops the other


def test_a_run_whose_first_calls_are_all_refused_gives_up_instead_of_hammering_kite(tmp_path, monkeypatch):
    monkeypatch.setattr(KE, "GIVE_UP_AFTER", 3)                                                       # the real limit is 6; the fake list has only 5 futures
    man, kite = _run(tmp_path, FakeKite(all_fail=True))
    assert len(kite.calls) == 3 and "refused" in man["stopped"]                                       # three refusals in a row, none served: stop
    assert sum(t["not_attempted"] for t in man["totals"].values()) == 2 and sum(t["failed"] for t in man["totals"].values()) == 3
    # a key that works for some contracts is not a dead key: later refusals do not trigger the give-up
    class Flaky(FakeKite):
        def historical_data(self, token, a, b, interval, **kw):
            if token in (3, 5, 7, 8):
                self.calls.append((token, interval)); raise RuntimeError("Too many requests")
            return super().historical_data(token, a, b, interval, **kw)
    monkeypatch.setattr(KE, "GIVE_UP_AFTER", 2)
    man, _ = _run(tmp_path / "b", Flaky())
    assert man["stopped"] is None and man["totals"]["mcx"]["failed"] == 2 and man["totals"]["cds"]["failed"] == 2


def test_the_time_budget_stops_the_run_and_says_so(tmp_path):
    t = iter(range(0, 10_000, 100))
    man = KE.run(FakeKite(), tmp_path, TODAY, say=lambda *a: None, sleep=lambda s: None, clock=lambda: next(t), budget_s=250)
    assert man["stopped"] == "time budget" and sum(x["not_attempted"] for x in man["totals"].values()) >= 1


def test_impossible_bars_are_dropped_and_counted(tmp_path):
    class Bad(FakeKite):
        def historical_data(self, token, a, b, interval, **kw):
            rows = _candles(TODAY)
            rows[1]["high"], rows[1]["low"] = 50.0, 200.0                                           # high below low
            return rows
    man, _ = _run(tmp_path, Bad())
    assert man["segments"]["mcx"]["names"]["GOLDM#1"]["bars"] == 4 and man["segments"]["mcx"]["names"]["GOLDM#1"]["rejected"] == 1


def test_a_manifest_carries_no_price_and_one_that_does_is_refused(tmp_path):
    man, _ = _run(tmp_path, days=3, daily_days=100)
    assert KE.publishable(man) == [] and not re.search(r'"(open|high|low|close|ts|volume|oi)"', json.dumps(man))
    leaky = json.loads(json.dumps(man))
    leaky["segments"]["mcx"]["names"]["GOLDM#1"]["close"] = 123.4
    assert [x.split(":")[0] for x in KE.publishable(leaky)] == ["/segments/mcx/names/GOLDM#1/close"]
    assert KE.publishable({"x": list(range(500))})                                                    # an unknown field and a long list are a dump, not a count
    for path, val in ((("note",), "x" * 500), (("segments", "mcx", "exchange"), 123), (("segments", "mcx", "names", "GOLDM#1", "bars"), 12.5),
                      (("segments", "mcx", "names", "GOLDM#1", "gross"), 1), (("totals", "mcx", "served"), True), (("rate_per_s",), "fast")):
        m = json.loads(json.dumps(man))
        d = m
        for k in path[:-1]:
            d = d[k]
        d[path[-1]] = val
        assert KE.publishable(m), path                                                                # a long string, a wrong type, a float count, a new field are each refused


def test_the_health_check_reads_a_kite_evening_manifest_like_any_other(tmp_path):
    from quantdesk.data import health as H
    man, _ = _run(tmp_path, days=3)
    man["as_of"] = "2026-11-06"

    class Store:
        def tags(self, t): return ["evening-minutes-2026"]
        def assets(self, t): return ["2026-11-06_manifest.json"]
        def read(self, t, n): return json.dumps(man).encode()
    c = H.check_evening_minutes(Store(), dt.date(2026, 11, 9))
    assert c.status == H.OK and "5 futures" in c.detail
    man["totals"]["mcx"]["served"] = 0
    assert H.check_evening_minutes(Store(), dt.date(2026, 11, 9)).status == H.BAD


# ---- the login gate -------------------------------------------------------------------------------------------------------------------------------------------------------

def _ts(s):
    return dt.datetime.fromisoformat(s).replace(tzinfo=IST).astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _gate(own, run_id=30, attempt=1, now="2026-11-10 00:05", record=None, steps="success"):
    record = [{"databaseId": 10, "createdAt": _ts("2026-11-09 08:55"), "conclusion": "success"}] if record is None else record
    jobs = lambda i: [{"name": "record-1", "steps": [{"name": "Set up job", "conclusion": "success"}, {"name": "Log in to Kite by itself (data only; the password reaches this step alone)", "conclusion": steps}]}]  # noqa: E731
    now_utc = dt.datetime.fromisoformat(now).replace(tzinfo=IST).astimezone(dt.timezone.utc)
    return G.may_log_in(own, run_id, attempt, now_utc, record, jobs)


def test_the_gate_lets_only_the_first_attempt_of_the_first_run_log_in_after_the_recorders_login_succeeded():
    mine = [{"databaseId": 30, "createdAt": _ts("2026-11-10 00:05")}]
    ok, why = _gate(mine)
    assert ok and "10" in why
    assert not _gate(mine, attempt=2)[0]                                                              # a re-run never logs in
    assert not _gate(mine + [{"databaseId": 25, "createdAt": _ts("2026-11-09 20:00")}])[0]            # a hand-started run earlier in the session day used the login
    assert _gate(mine + [{"databaseId": 25, "createdAt": _ts("2026-11-08 20:00")}])[0]                # a run of another session day does not
    assert not _gate([], run_id=30)[0]                                                                # not yet in the list: no login
    assert not _gate(mine, now="2026-11-11 00:05")[0]                                                 # created for another session day than now: no login


def test_the_gate_refuses_when_the_recorders_login_is_not_proven_that_day():
    mine = [{"databaseId": 30, "createdAt": _ts("2026-11-10 00:05")}]
    assert not _gate(mine, record=[])[0]                                                              # no recorder run
    assert not _gate(mine, record=[{"databaseId": 10, "createdAt": _ts("2026-11-09 08:55"), "conclusion": "failure"}])[0]       # the recorder failed (its login may have)
    assert not _gate(mine, record=[{"databaseId": 10, "createdAt": _ts("2026-11-08 08:55"), "conclusion": "success"}])[0]       # a success on another day
    assert not _gate(mine, steps="skipped")[0] and not _gate(mine, steps="failure")[0]               # the login step did not succeed


def test_the_gate_script_defaults_to_no_login_when_the_run_lists_cannot_be_read(monkeypatch, tmp_path, capsys):
    out = tmp_path / "o"
    monkeypatch.setenv("GITHUB_RUN_ID", "30"); monkeypatch.setenv("GITHUB_REPOSITORY", "o/r"); monkeypatch.setenv("GITHUB_OUTPUT", str(out)); monkeypatch.delenv("GITHUB_RUN_ATTEMPT", raising=False)
    monkeypatch.setattr(G, "_gh", lambda *a: (_ for _ in ()).throw(OSError("no gh")))
    assert G.main() == 0 and out.read_text().strip() == "first=false"


# ---- the workflow ---------------------------------------------------------------------------------------------------------------------------------------------------------

def test_the_module_places_no_order_and_touches_no_account_method():
    src = (ROOT / "quantdesk/data/kite_evening.py").read_text(encoding="utf-8") + (ROOT / "deploy/kite_evening_gate.py").read_text(encoding="utf-8")
    assert not re.search(r"place_order|modify_order|cancel_order|\.orders\(|\.positions\(|\.holdings\(|\.margins\(|\.profile\(|\.trades\(", src)
    cli = (ROOT / "quantdesk/data/cli.py").read_text(encoding="utf-8")
    body = cli[cli.index("def cmd_kite_evening"):cli.index("def cmd_fx_daily")]
    assert "_kite_authority_ended()" in body and "::warning::" in body and "publishable" in body and "clobber=True" in body


def test_the_workflow_isolates_the_kite_secrets_encrypts_before_it_uploads_and_publishes_only_the_manifest():
    import check_workflows
    text = WF.read_text(encoding="utf-8")
    wf = yaml.safe_load(text)
    assert check_workflows.check(WF) == [] and wf["permissions"] == {"contents": "read", "actions": "read"}
    on = wf.get("on", wf.get(True))
    assert set(on) == {"schedule", "workflow_dispatch"} and on["schedule"] == [{"cron": "35 18 * * 1-5"}]
    assert wf["concurrency"]["group"] == "kite-evening"
    jobs = wf["jobs"]
    collect, publish = jobs["collect"], jobs["publish"]
    assert "permissions" not in collect and publish["permissions"] == {"contents": "write"}
    pub_text = yaml.safe_dump(publish)
    assert not re.search(r"KITE|TOTP|PASSWORD|API_SECRET|API_KEY|secrets\.", pub_text)                  # the job that can write holds no Kite secret or key
    login = next(s for s in collect["steps"] if s.get("id") == "login")
    assert set(login["env"]) == {"KITE_USER_ID", "KITE_PASSWORD", "KITE_TOTP_SECRET"} and login["run"] == "deploy/kite-autologin.sh login"
    assert "steps.gate.outputs.first == 'true'" in login["if"] and "github.run_attempt == '1'" in login["if"]
    for s in collect["steps"]:
        if s is not login:
            assert not (set(s.get("env", {})) & {"KITE_USER_ID", "KITE_PASSWORD", "KITE_TOTP_SECRET"}), s.get("name")      # the password reaches the login step alone
    names = [s.get("name", s.get("uses", "")) for s in collect["steps"]]
    enc, up = next(i for i, n in enumerate(names) if n.startswith("Encrypt")), next(i for i, n in enumerate(names) if n == "Keep the encrypted candles")
    assert enc < up and "openssl enc -aes-256-cbc" in collect["steps"][enc]["run"]
    assert {s["with"]["name"] for s in collect["steps"] if "upload-artifact" in s.get("uses", "")} == {"kite-evening-data", "kite-evening-manifest"}
    assert [s["with"]["path"] for s in collect["steps"] if s.get("with", {}).get("name") == "kite-evening-data"] == ["kite_evening_data.tar.enc"]        # only the encrypted file
    assert "${{ inputs." not in "".join(s.get("run", "") for s in collect["steps"]) and "^[0-9]{1,2}$" in text
    assert "KITE_DATA_KEY" not in yaml.safe_dump({k: v for k, v in wf.items() if k != "jobs"}) and "KITE_DATA_KEY" in collect["env"]          # the key sits in the collecting job alone
    ids = [s.get("id") for s in collect["steps"]]
    assert ids.index("gate") > min(i for i, s in enumerate(collect["steps"]) if s.get("name", "").startswith("Check the inputs"))      # bad input never burns the day's login
    assert next(s for s in collect["steps"] if s.get("id") == "find")["if"] == "always()" and collect["steps"][ids.index("find") - 1]["id"] == "run"       # what a stopped run wrote is still kept
    check = next(s for s in publish["steps"] if s.get("name", "").startswith("The day is a plain date"))
    assert publish["steps"].index(check) < next(i for i, s in enumerate(publish["steps"]) if "download-artifact" in s.get("uses", ""))     # validated before it is a path


def test_the_pre_registered_kite_trial_is_untouched_by_the_evening_job():
    kite = (ROOT / ".github/workflows/kite-record.yml").read_text(encoding="utf-8")
    assert "kite_evening" not in kite and "kite-evening" not in kite
    assert "kite_evening" not in (ROOT / "quantdesk/data/kite_record.py").read_text(encoding="utf-8")
    assert "kite-evening" not in (ROOT / "deploy/scheduler.py").read_text(encoding="utf-8")


def test_the_publish_command_takes_its_date_from_the_folder_and_refuses_a_manifest_that_disagrees(tmp_path, monkeypatch):
    from quantdesk.data import cli as C
    man, _ = _run(tmp_path, days=3)
    run = tmp_path / str(TODAY)
    pushed = []
    monkeypatch.setattr(C, "_push_run", lambda out, r, tag, names, *a, **k: pushed.append((tag, names, k.get("clobber"))))
    C.cmd_evening_publish(None, type("A", (), {"dir": str(run), "release_prefix": "evening-minutes"})())
    assert pushed == [("evening-minutes-2026", ["manifest.json"], True)]
    m = json.loads((run / "manifest.json").read_text())
    m["as_of"] = "2025-01-02"                                                                          # a manifest naming another year
    (run / "manifest.json").write_text(json.dumps(m))
    with pytest.raises(SystemExit):
        C.cmd_evening_publish(None, type("A", (), {"dir": str(run), "release_prefix": "evening-minutes"})())
    assert len(pushed) == 1
