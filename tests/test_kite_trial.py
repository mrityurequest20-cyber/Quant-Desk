"""The Kite Connect trial recorder and its measures (quantdesk/data/kite_record.py, kite_compare.py, .github/workflows/kite-record.yml; criteria in docs/ml/KITE_TRIAL.md).
Fakes only: no network, no key. The recorder reads market data and nothing else: a test greps its source for order methods."""
import datetime as dt
import json
import shutil
import subprocess
import os
import re
import stat
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

from quantdesk.data import kite_compare as KC
from quantdesk.data import kite_record as K
from quantdesk.intraday.feeds import frozen_minutes

ROOT = Path(__file__).resolve().parents[1]
IST = "Asia/Kolkata"
DAY = "2026-10-26"


# ---- fakes -------------------------------------------------------------------------------------------------------------------
class FakeKite:
    def __init__(self, fut_expiries=("2026-10-27", "2026-11-24")):
        self.fut_expiries = fut_expiries

    def ltp(self, keys):
        ids = {"NSE:NIFTY 50": 256265, "NSE:NIFTY BANK": 260105, "NSE:INDIA VIX": 264969}
        return {k: {"instrument_token": ids[k], "last_price": 1.0} for k in keys if k in ids}

    def instruments(self, ex):
        rows = []
        for i, name in enumerate(("NIFTY", "BANKNIFTY")):
            for j, e in enumerate(self.fut_expiries):
                rows.append({"instrument_token": 1000 * (i + 1) + j, "name": name, "instrument_type": "FUT", "expiry": e})
            rows.append({"instrument_token": 9999 + i, "name": name, "instrument_type": "CE", "expiry": self.fut_expiries[0]})
        return rows

    def historical_data(self, tok, a, b, interval, oi=False):
        return [{"date": dt.datetime(2026, 10, 26, 9, 15) + dt.timedelta(minutes=i), "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0 + (i % 3), "volume": 10, "oi": 5}
                for i in range(3)]


class FakeTicker:
    MODE_FULL = "full"

    def __init__(self):
        self.subscribed, self.mode, self.connected, self.closed = [], None, False, False

    def subscribe(self, toks):
        self.subscribed = list(toks)

    def set_mode(self, mode, toks):
        self.mode = (mode, list(toks))

    def connect(self, threaded=False):
        self.connected = True
        self.on_connect(self, {})

    def close(self):
        self.closed = True


class Clock:
    def __init__(self, start="2026-10-26 09:00:00"):
        self.t = pd.Timestamp(start, tz=IST)

    def __call__(self):
        return self.t

    def advance(self, s):
        self.t += pd.Timedelta(seconds=s)


def kite_tick(token, price, ts, volume=None, oi=None, depth=True):
    t = {"instrument_token": token, "last_price": price, "exchange_timestamp": ts.tz_localize(None).to_pydatetime(), "last_traded_quantity": 5}
    if volume is not None:
        t["volume_traded"] = volume
    if oi is not None:
        t["oi"] = oi
    if depth:
        t["depth"] = {"buy": [{"price": price - 0.05, "quantity": 50, "orders": 3}], "sell": [{"price": price + 0.05, "quantity": 40, "orders": 2}]}
    return t


# ---- tokens and ticks --------------------------------------------------------------------------------------------------------
def test_the_near_month_future_and_the_three_indices_are_chosen():
    toks = K.resolve_tokens(FakeKite(), dt.date(2026, 10, 26))
    assert toks == {"NIFTY": 256265, "BANKNIFTY": 260105, "INDIAVIX": 264969, "NIFTY-FUT": 1000, "BANKNIFTY-FUT": 2000}
    after = K.resolve_tokens(FakeKite(), dt.date(2026, 10, 28))                                 # the 27 Oct contract has expired: the next one
    assert after["NIFTY-FUT"] == 1001 and after["BANKNIFTY-FUT"] == 2001


def test_a_missing_index_or_future_is_a_named_error():
    class NoVix(FakeKite):
        def ltp(self, keys):
            return {k: v for k, v in super().ltp(keys).items() if "VIX" not in k}
    with pytest.raises(K.KiteRecordError, match="INDIAVIX"):
        K.resolve_tokens(NoVix(), dt.date(2026, 10, 26))
    with pytest.raises(K.KiteRecordError, match="no live future"):
        K.resolve_tokens(FakeKite(fut_expiries=("2026-10-01",)), dt.date(2026, 10, 26))


def test_a_tick_becomes_a_row_with_depth_oi_and_both_clocks():
    recv = pd.Timestamp("2026-10-26 10:00:01", tz=IST)
    r = K.tick_row(kite_tick(1000, 25000.5, pd.Timestamp("2026-10-26 10:00:00"), volume=1234, oi=777), "NIFTY-FUT", recv)
    assert r["symbol"] == "NIFTY-FUT" and r["last_price"] == 25000.5 and r["volume"] == 1234 and r["oi"] == 777 and r["bid"] == 25000.45 and r["ask"] == 25000.55
    assert r["ts_exchange"] == pd.Timestamp("2026-10-26 10:00:00", tz=IST) and r["ts_recv"] == recv and r["bid_qty"] == 50 and r["ask_qty"] == 40
    idx = K.tick_row({"instrument_token": 256265, "last_price": 25000.0, "exchange_timestamp": dt.datetime(2026, 10, 26, 10, 0)}, "NIFTY", recv)      # an index tick has no depth
    assert idx["bid"] is None and idx["volume"] is None and idx["last_price"] == 25000.0


def test_the_recorder_subscribes_in_full_mode_writes_parts_and_logs_connection_events(tmp_path):
    clock, ticker = Clock(), FakeTicker()
    rec = K.Recorder(tmp_path, {"NIFTY": 256265, "NIFTY-FUT": 1000}, lambda: ticker, now=clock, flush_seconds=30)
    ticker.connect()
    assert ticker.subscribed == [256265, 1000] and ticker.mode == ("full", [256265, 1000])
    ticker.on_ticks(ticker, [kite_tick(256265, 25000.0, pd.Timestamp("2026-10-26 09:15:01"), depth=False), kite_tick(1000, 25010.0, pd.Timestamp("2026-10-26 09:15:01"), volume=5, oi=9),
                             kite_tick(4242, 1.0, pd.Timestamp("2026-10-26 09:15:01"))])         # a token we did not ask for is ignored
    ticker.on_reconnect(ticker, 1)
    ticker.on_close(ticker, 1006, "network")
    p = rec.flush()
    df = pd.read_parquet(p)
    assert list(df.columns) == K.TICK_COLUMNS and len(df) == 2 and set(df["symbol"]) == {"NIFTY", "NIFTY-FUT"}
    ev = [json.loads(x) for x in (tmp_path / "events.jsonl").read_text().splitlines()]
    assert [e["kind"] for e in ev] == ["connect", "reconnect", "close"]
    assert rec.flush() is None                                                                    # nothing new: no empty part


def test_a_session_records_until_the_time_then_closes_and_fetches_the_reference(tmp_path, monkeypatch):
    monkeypatch.setenv("KITE_DATA_KEY", "k")
    monkeypatch.setenv("KITE_DATA_TOKEN", "t")
    clock, ticker = Clock("2026-10-26 15:29:58"), FakeTicker()

    def sleep(s):
        clock.advance(1)
        ticker.on_ticks(ticker, [kite_tick(256265, 25000.0, clock().tz_localize(None), depth=False)])
    out = tmp_path / "rec"
    got = None
    # run_session uses the real kiteconnect classes unless fakes are given: give fakes for both
    got = K.run_session(out, "15:30", kite=FakeKite(), ticker_factory=lambda: ticker, now=clock, sleep=sleep, with_reference=True)
    assert ticker.closed and got["day"] == DAY and got["ticks"] >= 1 and got["tokens"]["NIFTY-FUT"] == 1000
    assert json.loads((out / "tokens.json").read_text())["BANKNIFTY"] == 260105
    assert (out / "reference_minutes.parquet").exists() and len(pd.read_parquet(out / "reference_minutes.parquet")) == 15


def test_the_recorder_refuses_a_folder_inside_a_git_tree_and_a_missing_credential(tmp_path, monkeypatch):
    from quantdesk.data.external_aeron import ForbiddenUse
    with pytest.raises(ForbiddenUse):
        K.run_session(ROOT / "docs" / "kite_probe", "15:30", kite=FakeKite(), ticker_factory=FakeTicker)
    monkeypatch.delenv("KITE_DATA_KEY", raising=False)
    monkeypatch.delenv("KITE_DATA_TOKEN", raising=False)
    with pytest.raises(K.KiteRecordError, match="must be set"):
        K.run_session(tmp_path / "x", "15:30")


# ---- the measures --------------------------------------------------------------------------------------------------------------
def ticks_for(symbol, minutes, price_fn, per_minute=3, lag=0.4, start_sec=1):
    rows = []
    for m in minutes:
        for k in range(per_minute):
            ts = m + pd.Timedelta(seconds=start_sec + k * 10)
            rows.append({"symbol": symbol, "token": 1, "ts_exchange": ts, "ts_recv": ts + pd.Timedelta(seconds=lag), "last_price": price_fn(m, k), "last_qty": 1.0,
                         "volume": float(len(rows) + 1) * 10, "oi": None, "bid": None, "ask": None, "bid_qty": None, "ask_qty": None, "buy_qty_total": None, "sell_qty_total": None})
    return rows


def write_session(folder, ticks, reference):
    folder.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(ticks).to_parquet(folder / "ticks_090000_0001.parquet", index=False)
    pd.DataFrame(reference).to_parquet(folder / "reference_minutes.parquet", index=False)
    (folder / "tokens.json").write_text(json.dumps({"NIFTY": 1}))


def reference_for(symbol, minutes, price_fn):
    rows = []
    for m in minutes:
        ps = [price_fn(m, k) for k in range(3)]
        rows.append({"symbol": symbol, "ts": m, "open": ps[0], "high": max(ps), "low": min(ps), "close": ps[-1], "volume": 1, "oi": None})
    return rows


def moving(m, k):
    return 25000.0 + ((m.hour * 60 + m.minute) % 17) * 0.5 + k * 0.05


def test_a_clean_session_passes_every_measure(tmp_path):
    mins = KC.session_minutes(DAY)
    write_session(tmp_path, ticks_for("NIFTY", mins, moving), reference_for("NIFTY", mins, moving))
    rep = KC.session_report(tmp_path, DAY)
    m = rep["measures"][0]
    assert rep["passed"] and m["A1"] == 1.0 and m["A2"] == 0 and m["B1"] == 1.0 and m["B2"] == 1.0 and m["C1"] == 1.0
    assert m["C3_median"] == pytest.approx(0.4) and rep["ticks"] == 375 * 3 and "PASS" in KC.render(rep)


def test_a_coverage_hole_a_long_gap_and_a_wrong_close_each_fail_their_own_measure(tmp_path):
    mins = KC.session_minutes(DAY)
    keep = [m for m in mins if not (pd.Timestamp(f"{DAY} 11:00", tz=IST) <= m < pd.Timestamp(f"{DAY} 11:06", tz=IST))]         # six minutes with no tick
    write_session(tmp_path / "a", ticks_for("NIFTY", keep, moving), reference_for("NIFTY", mins, moving))
    ra = KC.session_report(tmp_path / "a", DAY)
    assert not ra["passed"] and ra["measures"][0]["A2"] == 6 and any("A1" in r for r in ra["reasons"]) and any("A2" in r for r in ra["reasons"])
    off = lambda m, k: moving(m, k) * (1.001 if m.minute % 10 == 0 else 1.0)                  # a tenth of the minutes 0.1% off the reference
    write_session(tmp_path / "b", ticks_for("NIFTY", mins, off), reference_for("NIFTY", mins, moving))
    rb = KC.session_report(tmp_path / "b", DAY)
    assert not rb["passed"] and rb["measures"][0]["B1"] < 0.99 and any("B1" in r for r in rb["reasons"])


def test_no_reference_is_a_failure_not_a_pass_and_no_ticks_is_reported(tmp_path):
    mins = KC.session_minutes(DAY)
    write_session(tmp_path / "a", ticks_for("NIFTY", mins, moving), [])
    assert not KC.session_report(tmp_path / "a", DAY)["passed"]
    empty = KC.session_report(tmp_path / "none", DAY)
    assert empty["recorded"] is False and not empty["passed"] and "no ticks" in empty["reasons"][0] and "nothing recorded" in KC.render(empty)


def test_slow_ticks_show_in_the_latency_measure_but_do_not_fail_the_session(tmp_path):
    mins = KC.session_minutes(DAY)
    write_session(tmp_path, ticks_for("NIFTY", mins, moving, lag=2.5), reference_for("NIFTY", mins, moving))
    rep = KC.session_report(tmp_path, DAY)
    assert rep["passed"] and not any("C3" in r for r in rep["reasons"])                          # C3 is reported, not a pass condition (docs/ml/KITE_TRIAL.md)
    assert rep["measures"][0]["C3_median"] > KC.THRESHOLDS["C3_median"]                        # ...and it is still measured and shown


def test_a_frozen_late_session_shows_in_c1_and_the_detector_equals_the_desks(tmp_path):
    mins = KC.session_minutes(DAY)
    frozen_px = lambda m, k: 25100.0 if pd.Timestamp(f"{DAY} 15:15", tz=IST) <= m <= pd.Timestamp(f"{DAY} 15:28", tz=IST) else moving(m, k)
    write_session(tmp_path, ticks_for("NIFTY", mins, frozen_px, per_minute=1), reference_for("NIFTY", mins, frozen_px))
    ticks = KC.load_ticks(tmp_path)
    bars = KC.tick_bars(ticks, "NIFTY")
    assert list(KC.frozen(bars)) == list(frozen_minutes(bars)) and len(KC.frozen(bars)) == 13           # the first flat minute has a differing previous close
    assert KC.session_report(tmp_path, DAY)["measures"][0]["C1"] < 0.2


def test_the_desk_dependence_counts_what_kite_covers_of_the_desks_bad_minutes(tmp_path):
    mins = KC.session_minutes(DAY)
    write_session(tmp_path, ticks_for("NIFTY", mins, moving), reference_for("NIFTY", mins, moving))
    desk = pd.DataFrame({"ts": mins[:100].tz_convert("UTC"), "open": 1.0, "high": 1.0, "low": 1.0, "close": np.arange(100) + 1.0})        # the desk has only the first 100 minutes
    got = KC.desk_dependence(KC.load_ticks(tmp_path), desk, "NIFTY", DAY)
    assert got["bad_minutes"] == 275 and got["covered"] == 275 and got["C2"] == 1.0


def test_the_session_check_can_be_run_from_the_command(tmp_path, capsys):
    from quantdesk.cli import main
    mins = KC.session_minutes(DAY)
    write_session(tmp_path / "s", ticks_for("NIFTY", mins, moving), reference_for("NIFTY", mins, moving))
    main(["data", "kite-compare", "--dir", str(tmp_path / "s"), "--day", DAY, "--json-out", str(tmp_path / "m.json")])
    assert "PASS" in capsys.readouterr().out and json.loads((tmp_path / "m.json").read_text())["passed"] is True


# ---- what the recorder must never be ---------------------------------------------------------------------------------------------
def test_the_recorder_and_the_measures_never_touch_orders_the_engine_or_the_journal():
    for name in ("kite_record.py", "kite_compare.py"):
        src = (ROOT / "quantdesk" / "data" / name).read_text()
        for forbidden in ("place_order", "modify_order", "cancel_order", "orders(", "order_history", "positions(", "holdings(", "margins(", "profile(", "convert_position"):
            assert forbidden not in src, (name, forbidden)
        assert not re.search(r"^\s*(from|import)\s+(\.\.?\s*)?(quantdesk\.)?(intraday|engine|execution|journal|risk|learnbot|strategies|web)\b", src, re.M), name


def test_the_recorder_workflow_is_read_only_encrypts_before_it_uploads_and_holds_the_secret_only_in_named_steps():
    import sys
    import yaml
    sys.path.insert(0, str(ROOT / "deploy"))
    import check_workflows
    path = ROOT / ".github" / "workflows" / "kite-record.yml"
    text = path.read_text()
    wf = yaml.load(text, Loader=yaml.BaseLoader)
    assert wf["permissions"] == {"contents": "read"} and set(wf["on"]) == {"schedule", "workflow_dispatch"} and check_workflows.check(path) == []
    assert wf["defaults"]["run"]["shell"] == "bash" and wf["env"]["KITE_DATA_KEY"] == "${{ secrets.KITE_API_KEY }}"
    assert sorted(set(re.findall(r"secrets\.([A-Z_]+)", text))) == ["KITE_API_KEY", "KITE_API_SECRET"]
    assert "KITE_ACCESS_TOKEN" not in text and "KITE_API_KEY:" not in text                          # the broker adapter's names are never set
    steps = [(j, s) for j, job in wf["jobs"].items() for s in job["steps"]]
    assert all("${{" not in s["run"] for _, s in steps if "run" in s)                              # times come in through env, never into a script
    holders = [(j, s.get("name")) for j, s in steps if "KITE_API_SECRET" in json.dumps(s.get("env", {}))]
    token_step, enc_step, dec_step = "The day's Kite token (optional; without it nothing is recorded)", "Encrypt the ticks with the owner's API secret", "Decrypt the first job's ticks (for the session's measures only; a failure here never stops the recording)"
    assert holders == [("record-1", token_step), ("record-1", enc_step), ("record-2", token_step), ("record-2", dec_step), ("record-2", enc_step)]      # exactly these five, no others
    for s_ in (s for _, s in steps if "KITE_API_SECRET" in json.dumps(s.get("env", {}))):
        assert "pip install" not in s_.get("run", "")                                              # the library install never holds the secret
    for forbidden in ("git push", "gh release", "gh api", "curl ", "contents: write", "id-token", "pull_request"):
        assert forbidden not in text.lower(), forbidden
    # nothing but ciphertext and the counts-and-ratios metrics is ever uploaded: the raw folders are never an artifact path
    uploads = [s["with"] for _, s in steps if s.get("uses", "").startswith("actions/upload-artifact")]
    assert sorted(u["path"] for u in uploads) == ["kite_metrics.json", "kite_raw_1.tar.enc", "kite_raw_2.tar.enc"]
    assert all(int(u["retention-days"]) <= 90 for u in uploads) and all("runtime" not in u["path"] for u in uploads)
    assert text.count("openssl enc -aes-256-cbc -pbkdf2 -salt -pass env:KITE_DATA_SECRET") == 2
    assert all(s["with"].get("persist-credentials") == "false" for _, s in steps if s.get("uses", "").startswith("actions/checkout"))


def test_the_depth_of_a_future_is_recorded_to_five_levels_and_an_index_leaves_it_empty():
    fut = {"instrument_token": 1000, "last_price": 25010.0, "exchange_timestamp": pd.Timestamp("2026-10-26 09:15:01").to_pydatetime(), "volume_traded": 5, "oi": 9, "last_traded_quantity": 75,
           "total_buy_quantity": 100, "total_sell_quantity": 90,
           "depth": {"buy": [{"price": 25009.0 - i, "quantity": 75 * (i + 1), "orders": i + 2} for i in range(5)], "sell": [{"price": 25011.0 + i, "quantity": 50 * (i + 1), "orders": i + 1} for i in range(5)]}}
    row = K.tick_row(fut, "NIFTY-FUT", pd.Timestamp("2026-10-26 09:15:02", tz=IST))
    assert set(row) == set(K.TICK_COLUMNS) and len(K.DEPTH_COLUMNS) == 30
    assert (row["bid_p1"], row["bid_q1"], row["bid_n1"]) == (25009.0, 75.0, 2.0) and (row["bid_p5"], row["bid_q5"], row["bid_n5"]) == (25005.0, 375.0, 6.0)
    assert (row["ask_p1"], row["ask_q3"], row["ask_n5"]) == (25011.0, 150.0, 5.0) and row["bid"] == row["bid_p1"] and row["ask_qty"] == row["ask_q1"]
    idx = K.tick_row({"instrument_token": 256265, "last_price": 25000.0, "exchange_timestamp": pd.Timestamp("2026-10-26 09:15:01").to_pydatetime()}, "NIFTY", pd.Timestamp("2026-10-26 09:15:02", tz=IST))
    assert all(idx[c] is None for c in K.DEPTH_COLUMNS)
    short = dict(fut, depth={"buy": fut["depth"]["buy"][:2], "sell": []})                           # fewer levels than five: the rest stay empty, nothing is invented
    row = K.tick_row(short, "NIFTY-FUT", pd.Timestamp("2026-10-26 09:15:02", tz=IST))
    assert row["bid_p2"] == 25008.0 and row["bid_p3"] is None and row["ask_p1"] is None


def test_the_command_records_nothing_and_succeeds_on_a_day_without_a_token(tmp_path, monkeypatch, capsys):
    from quantdesk.cli import main
    monkeypatch.delenv("KITE_DATA_KEY", raising=False)
    monkeypatch.delenv("KITE_DATA_TOKEN", raising=False)
    monkeypatch.setattr("quantdesk.data.cli._kite_authority_ended", lambda today=None: False)       # not the wall clock
    main(["data", "kite-record", "--out", str(tmp_path / "k"), "--until", "15:30"])
    assert "nothing recorded" in capsys.readouterr().out and not (tmp_path / "k").exists()


@pytest.mark.skipif(shutil.which("openssl") is None, reason="openssl is needed")
def test_the_owners_script_decrypts_what_the_workflow_encrypts_and_nothing_else_can(tmp_path):
    src = tmp_path / "kite"
    src.mkdir()
    pd.DataFrame({"a": [1, 2, 3]}).to_parquet(src / "ticks_x_0001.parquet")
    (src / "events.jsonl").write_text('{"kind": "connect"}\n')
    enc = tmp_path / "kite_raw_1.tar.enc"
    env = {**os.environ, "KITE_DATA_SECRET": "THE-API-SECRET"}
    subprocess.run(f'tar -C {src} -cf - . | openssl enc -aes-256-cbc -pbkdf2 -salt -pass env:KITE_DATA_SECRET -out {enc}', shell=True, check=True, env=env)
    assert b"connect" not in enc.read_bytes() and b"PAR1" not in enc.read_bytes()                  # ciphertext: nothing readable
    ok = subprocess.run(["bash", str(ROOT / "deploy" / "kite-decrypt.sh"), str(enc), str(tmp_path / "out")], env=env, capture_output=True, text=True)
    assert ok.returncode == 0 and len(pd.read_parquet(tmp_path / "out" / "ticks_x_0001.parquet")) == 3
    bad = subprocess.run(["bash", str(ROOT / "deploy" / "kite-decrypt.sh"), str(enc), str(tmp_path / "out2")], env={**os.environ, "KITE_DATA_SECRET": "WRONG"}, capture_output=True, text=True)
    assert bad.returncode != 0 or not (tmp_path / "out2" / "ticks_x_0001.parquet").exists()
    assert subprocess.run(["bash", str(ROOT / "deploy" / "kite-decrypt.sh"), str(enc), str(tmp_path / "o3")], env={k: v for k, v in os.environ.items() if k != "KITE_DATA_SECRET"},
                          capture_output=True, text=True).returncode == 2


def _kite_exception(name):
    """A stand-in for kiteconnect.exceptions.<name>, which CI does not install: the command tells Kite's failures from ours by the class's module."""
    return type(name, (Exception,), {"__module__": "kiteconnect.exceptions"})


def _record_with(tmp_path, monkeypatch, exc):
    from quantdesk.cli import main
    monkeypatch.setenv("KITE_DATA_KEY", "k")
    monkeypatch.setenv("KITE_DATA_TOKEN", "STALE1234567890ABCDEF")
    monkeypatch.setattr("quantdesk.data.cli._kite_authority_ended", lambda today=None: False)       # not the wall clock

    def boom(*a, **k):
        raise exc
    monkeypatch.setattr(K, "run_session", boom)
    main(["data", "kite-record", "--out", str(tmp_path / "k"), "--until", "15:30"])


def test_a_token_that_decrypts_but_is_stale_ends_the_command_cleanly_not_with_a_traceback(tmp_path, monkeypatch, capsys):
    _record_with(tmp_path, monkeypatch, _kite_exception("TokenException")("Incorrect api_key or access_token"))      # returns: no SystemExit, no traceback
    assert "no usable session today (TokenException)" in capsys.readouterr().out
    _record_with(tmp_path, monkeypatch, ConnectionResetError("network"))                                              # the network is Kite's side too
    assert "no usable session today (ConnectionResetError)" in capsys.readouterr().out
    import requests
    _record_with(tmp_path, monkeypatch, requests.exceptions.ReadTimeout("slow"))                                      # what kiteconnect's HTTP client raises
    assert "no usable session today (ReadTimeout)" in capsys.readouterr().out


def test_a_bug_of_ours_is_not_swallowed_as_a_quiet_day(tmp_path, monkeypatch):
    with pytest.raises(KeyError):                                                   # a changed instruments dump, say: the run goes red
        _record_with(tmp_path, monkeypatch, KeyError("instrument_token"))
    with pytest.raises(RuntimeError, match="TokenException"):                       # a name alone does not make it Kite's
        _record_with(tmp_path, monkeypatch, RuntimeError("TokenException: spoofed by name only"))
    with pytest.raises(OSError, match="No space"):                                  # our own disk is not Kite's network
        _record_with(tmp_path, monkeypatch, OSError(28, "No space left on device"))
    with pytest.raises(TimeoutError):                                               # a built-in timeout can come from our own filesystem; Kite's timeouts carry their library's class
        _record_with(tmp_path, monkeypatch, TimeoutError("a slow mount"))


def test_ticks_dropped_from_a_full_buffer_fail_the_run_even_when_a_later_flush_succeeds(tmp_path, monkeypatch):
    monkeypatch.setenv("KITE_DATA_KEY", "k")
    monkeypatch.setenv("KITE_DATA_TOKEN", "t")
    monkeypatch.setattr(K, "MAX_BUFFER", 2)
    clock, ticker = Clock("2026-10-26 15:29:58"), FakeTicker()

    def sleep(s):
        clock.advance(1)
        ticker.on_ticks(ticker, [kite_tick(256265, 25000.0 + i, clock().tz_localize(None), depth=False) for i in range(3)])
    out = tmp_path / "rec"
    with pytest.raises(K.KiteRecordError, match="dropped"):                         # the final flush wrote what it held (unwritten is 0), yet ticks were lost earlier
        K.run_session(out, "15:30", kite=FakeKite(), ticker_factory=lambda: ticker, now=clock, sleep=sleep)
    assert any(json.loads(x)["kind"] == "overflow" for x in (out / "events.jsonl").read_text().splitlines())      # and the loss is on record


def test_ticks_that_could_not_be_written_at_the_end_fail_the_run_and_keep_what_was_written(tmp_path, monkeypatch, capsys):
    from quantdesk.cli import main
    monkeypatch.setenv("KITE_DATA_KEY", "k")
    monkeypatch.setenv("KITE_DATA_TOKEN", "t")
    monkeypatch.setattr("quantdesk.data.cli._kite_authority_ended", lambda today=None: False)
    clock, ticker = Clock("2026-10-26 15:29:58"), FakeTicker()
    real = pd.DataFrame.to_parquet
    fail = {"on": False}

    def to_parquet(self, path, *a, **k):
        if fail["on"] and Path(path).name.startswith("ticks_"):
            raise OSError("disk full")
        return real(self, path, *a, **k)
    monkeypatch.setattr(pd.DataFrame, "to_parquet", to_parquet)

    def sleep(s):
        clock.advance(1)
        ticker.on_ticks(ticker, [kite_tick(256265, 25000.0, clock().tz_localize(None), depth=False)])
        if clock() >= pd.Timestamp("2026-10-26 15:29:59", tz=K.IST):
            fail["on"] = True                                                       # the disk goes just before the final flush
    out = tmp_path / "rec"
    with pytest.raises(K.KiteRecordError, match="could not be written"):
        K.run_session(out, "15:30", kite=FakeKite(), ticker_factory=lambda: ticker, now=clock, sleep=sleep, with_reference=True)
    assert (out / "reference_minutes.parquet").exists()                             # the reference was still fetched: the session's measures are not lost with it
    monkeypatch.setattr(K, "run_session", lambda *a, **k: (_ for _ in ()).throw(K.KiteRecordError("12 ticks could not be written")))
    with pytest.raises(SystemExit) as e:                                            # and the command ends non-zero, so the workflow shows red
        main(["data", "kite-record", "--out", str(tmp_path / "k"), "--until", "15:30"])
    assert "could not be written" in str(e.value)


def test_one_instruments_reference_failing_costs_the_session_only_that_instrument(tmp_path):
    class Flaky(FakeKite):
        def historical_data(self, tok, a, b, interval, oi=False):
            if tok == 260105:
                raise RuntimeError("rate limit")
            return super().historical_data(tok, a, b, interval, oi)
    path = K.fetch_reference(Flaky(), {"NIFTY": 256265, "BANKNIFTY": 260105}, dt.date(2026, 10, 26), tmp_path)
    df = pd.read_parquet(path)
    assert set(df["symbol"]) == {"NIFTY"} and len(df) == 3


def test_a_failed_write_keeps_the_ticks_for_the_next_flush(tmp_path, monkeypatch):
    clock, ticker = Clock(), FakeTicker()
    rec = K.Recorder(tmp_path, {"NIFTY": 256265}, lambda: ticker, now=clock, flush_seconds=30)
    ticker.connect()
    ticker.on_ticks(ticker, [kite_tick(256265, 25000.0, pd.Timestamp("2026-10-26 09:15:01"), depth=False)])
    real = pd.DataFrame.to_parquet
    monkeypatch.setattr(pd.DataFrame, "to_parquet", lambda *a, **k: (_ for _ in ()).throw(OSError("disk")))
    assert rec.flush() is None and len(rec.rows) == 1                                             # not lost, not written
    monkeypatch.setattr(pd.DataFrame, "to_parquet", real)
    p = rec.flush()
    assert p is not None and len(pd.read_parquet(p)) == 1 and p.name.endswith("_0001.parquet")


@pytest.mark.skipif(shutil.which("openssl") is None, reason="openssl is needed")
def test_the_decrypt_script_refuses_a_file_that_does_not_match_the_digest_it_was_given(tmp_path):
    src = tmp_path / "kite"
    src.mkdir()
    (src / "events.jsonl").write_text('{"kind": "connect"}\n')
    enc = tmp_path / "kite_raw_1.tar.enc"
    env = {**os.environ, "KITE_DATA_SECRET": "THE-API-SECRET"}
    subprocess.run(f"tar -C {src} -cf - . | openssl enc -aes-256-cbc -pbkdf2 -salt -pass env:KITE_DATA_SECRET -out {enc}", shell=True, check=True, env=env)
    import hashlib
    good = hashlib.sha256(enc.read_bytes()).hexdigest()
    ok = subprocess.run(["bash", str(ROOT / "deploy" / "kite-decrypt.sh"), str(enc), str(tmp_path / "a"), good], env=env, capture_output=True, text=True)
    assert ok.returncode == 0 and (tmp_path / "a" / "events.jsonl").exists()
    bad = subprocess.run(["bash", str(ROOT / "deploy" / "kite-decrypt.sh"), str(enc), str(tmp_path / "b"), "0" * 64], env=env, capture_output=True, text=True)
    assert bad.returncode == 1 and not (tmp_path / "b").exists()


def test_the_second_job_cannot_lose_the_first_jobs_events_and_the_measures_run_whatever_happened():
    wf = yaml.safe_load((ROOT / ".github" / "workflows" / "kite-record.yml").read_text())
    steps = {s.get("name"): s for s in wf["jobs"]["record-2"]["steps"]}
    m = steps["Measures for the session (counts and ratios only)"]
    assert m["if"] == "always()" and "cat runtime/kite_1/events.jsonl runtime/kite/events.jsonl" in m["run"] and "cp -n" not in m["run"]
    d = next(s for n, s in steps.items() if n and n.startswith("Decrypt the first job"))
    assert d["continue-on-error"] is True and "sha256sum -c" in d["run"]


def test_a_buffer_that_cannot_be_written_stops_growing_and_says_how_many_ticks_it_dropped(tmp_path, monkeypatch):
    monkeypatch.setattr(K, "MAX_BUFFER", 2)
    clock, ticker = Clock(), FakeTicker()
    rec = K.Recorder(tmp_path, {"NIFTY": 256265}, lambda: ticker, now=clock, flush_seconds=30)
    ticker.connect()
    ticker.on_ticks(ticker, [kite_tick(256265, 25000.0 + i, pd.Timestamp("2026-10-26 09:15:01"), depth=False) for i in range(5)])
    assert len(rec.rows) == 2 and rec.overflow == 3
    p = rec.flush()
    ev = [json.loads(x) for x in (tmp_path / "events.jsonl").read_text().splitlines()]
    assert len(pd.read_parquet(p)) == 2 and any(e["kind"] == "overflow" and e["dropped_ticks"] == 3 for e in ev)


# ---- the owner's exception ends, and so do the Kite commands ----------------------------------------------------------------------
def test_the_kite_commands_stop_on_the_day_the_owners_exception_ends_whatever_secrets_are_set(tmp_path, monkeypatch, capsys):
    from quantdesk.cli import main
    from quantdesk.data import cli as DC
    from quantdesk.intraday import kitelive as KL
    assert KL.AUTHORITY_ENDS == dt.date(2027, 12, 31)                                         # one source for the date (docs/AUTONOMY.md)
    assert DC._kite_authority_ended(dt.date(2027, 12, 30)) is False and DC._kite_authority_ended(dt.date(2027, 12, 31)) is True
    assert DC._kite_authority_ended(dt.date(2028, 3, 1)) is True
    for k in ("KITE_DATA_KEY", "KITE_DATA_TOKEN", "KITE_DATA_SECRET", "KITE_REQUEST_TOKEN"):
        monkeypatch.setenv(k, "A1B2C3D4E5F6G7H8I9J0")                                         # every secret IS set: only the date can stop it
    monkeypatch.setattr(DC, "_kite_authority_ended", lambda today=None: True)

    def must_not_run(*a, **k):
        raise AssertionError("a Kite call was made after the authority ended")
    monkeypatch.setattr(K, "run_session", must_not_run)
    monkeypatch.setattr(KL, "exchange_token", must_not_run)
    main(["data", "kite-record", "--out", str(tmp_path / "k"), "--until", "15:30"])
    assert "authority has ended" in capsys.readouterr().out and not (tmp_path / "k").exists()
    out = tmp_path / "tok"
    with pytest.raises(SystemExit, match="authority has ended"):
        main(["data", "kite-token", "--out", str(out)])
    assert not out.exists()


def test_both_encrypt_steps_fail_closed_on_an_empty_secret_before_openssl_runs():
    text = (ROOT / ".github" / "workflows" / "kite-record.yml").read_text()
    guard = '[ -n "$KITE_DATA_SECRET" ] || {'
    opens = [m.start() for m in re.finditer(r"openssl enc -aes-256-cbc -pbkdf2 -salt", text)]
    guards = [m.start() for m in re.finditer(re.escape(guard), text)]
    assert len(opens) == 2 and len(guards) == 2 and all(g < o and o - g < 400 for g, o in zip(guards, opens))
    assert "exit 1" in text[guards[0]:opens[0]] and "exit 1" in text[guards[1]:opens[1]]
