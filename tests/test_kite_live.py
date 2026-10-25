"""The Kite websocket attached to the running desk (quantdesk/intraday/kitelive.py): fakes only, no network. The websocket serves index bars and the live price when it is healthy and
complete; every failure leaves the wrapped feed exactly as it was; and nothing in the module can place an order."""
import re
import sys
import types
from pathlib import Path

import pandas as pd
import pytest

from quantdesk.intraday import kitelive as KL

ROOT = Path(__file__).resolve().parents[1]
IST = "Asia/Kolkata"


class Clock:
    def __init__(self, start="2026-10-26 10:00:30"):
        self.t = pd.Timestamp(start, tz=IST)

    def __call__(self):
        return self.t

    def set(self, s):
        s = pd.Timestamp(s)
        self.t = s.tz_localize(IST) if s.tzinfo is None else s.tz_convert(IST)


class FakeWS:
    MODE_FULL = "full"

    def __init__(self):
        self.subscribed = self.mode = None
        self.closed = self.connected = False

    def subscribe(self, t):
        self.subscribed = list(t)

    def set_mode(self, m, t):
        self.mode = (m, list(t))

    def connect(self, threaded=False):
        self.connected = True
        self.on_connect(self, {})

    def close(self):
        self.closed = True


def tick(token, px, ts):
    return {"instrument_token": token, "last_price": px, "exchange_timestamp": pd.Timestamp(ts).tz_localize(None).to_pydatetime()}


def make(clock=None, tokens=None):
    clock = clock or Clock()
    ws = FakeWS()
    live = KL.KiteLive(tokens or {"NIFTY": 1, "INDIAVIX": 3}, lambda: ws, now=clock)
    live.start()
    return live, ws, clock


def feed_minutes(live, ws, clock, symbol_token, start, prices):
    """One tick at the start of each minute, one in the middle, and one just before it ends: o, h/l, c."""
    for i, p in enumerate(prices):
        t0 = pd.Timestamp(start) + pd.Timedelta(minutes=i)
        for sec, px in ((1, p), (20, p + 1), (40, p - 1), (58, p + 0.5)):
            ts = t0 + pd.Timedelta(seconds=sec)
            clock.set(ts)
            ws.on_ticks(ws, [tick(symbol_token, px, ts)])


# ---- the tick aggregator -----------------------------------------------------------------------------------------------------
def test_ticks_become_completed_minutes_and_the_forming_minute_is_not_served():
    live, ws, clock = make()
    assert ws.subscribed == [1, 3] and ws.mode == ("full", [1, 3])
    feed_minutes(live, ws, clock, 1, "2026-10-26 10:00:00", [25000.0, 25010.0, 25020.0])
    clock.set("2026-10-26 10:03:05")
    b = live.bars("NIFTY")
    assert list(b.index) == [pd.Timestamp(f"2026-10-26 10:0{i}:00", tz=IST) for i in range(3)]
    r = b.iloc[0]
    assert (r["open"], r["high"], r["low"], r["close"]) == (25000.0, 25001.0, 24999.0, 25000.5)


def test_the_minute_still_forming_is_not_served():
    live, ws, clock = make(Clock("2026-10-26 10:00:00"))
    feed_minutes(live, ws, clock, 1, "2026-10-26 10:00:00", [25000.0, 25010.0])
    ws.on_ticks(ws, [tick(1, 25020.0, "2026-10-26 10:02:05")])
    clock.set("2026-10-26 10:02:30")                                                           # 10:02 is forming
    assert list(live.bars("NIFTY").index) == [pd.Timestamp("2026-10-26 10:00:00", tz=IST), pd.Timestamp("2026-10-26 10:01:00", tz=IST)]


def test_a_late_tick_a_bad_price_an_unknown_token_and_a_far_stamp_are_handled():
    live, ws, clock = make()
    ws.on_ticks(ws, [tick(1, 25000.0, "2026-10-26 10:00:10")])
    clock.set("2026-10-26 10:01:10")
    ws.on_ticks(ws, [tick(1, 25010.0, "2026-10-26 10:01:05")])
    ws.on_ticks(ws, [tick(1, 99999.0, "2026-10-26 10:00:50")])                                 # for the minute already closed: ignored
    for bad in (0.0, -5.0, float("nan"), None, "x"):
        ws.on_ticks(ws, [{"instrument_token": 1, "last_price": bad, "exchange_timestamp": pd.Timestamp("2026-10-26 10:01:06").to_pydatetime()}])
    ws.on_ticks(ws, [tick(777, 1.0, "2026-10-26 10:01:06")])
    clock.set("2026-10-26 10:02:05")
    b = live.bars("NIFTY")
    assert list(b["close"]) == [25000.0, 25010.0] and b["high"].max() == 25010.0
    ws.on_ticks(ws, [tick(1, 25020.0, "2026-10-26 08:00:00")])                                 # a stamp hours off our clock: dropped, never taken as "now"
    assert live.last_price["NIFTY"] == 25010.0 and live.dropped["stamp"] == 1
    ws.on_ticks(ws, [tick(1, 25030.0, "2026-10-26 10:03:30")])                                 # a stamp more than 5 s ahead of our clock: dropped too
    assert live.last_price["NIFTY"] == 25010.0 and live.dropped["stamp"] == 2


def test_health_is_a_fresh_tick_and_the_live_price_follows_it():
    live, ws, clock = make()
    assert not live.healthy() and live.ltp("NIFTY") is None
    ws.on_ticks(ws, [tick(1, 25000.0, "2026-10-26 10:00:20")])
    assert live.healthy("NIFTY") and live.ltp("NIFTY") == 25000.0 and not live.healthy("INDIAVIX")
    clock.set("2026-10-26 10:01:00")                                                           # 30 s later with no tick
    assert not live.healthy("NIFTY") and live.ltp("NIFTY") is None


# ---- the wrapped feed ----------------------------------------------------------------------------------------------------------
class Inner:
    """A Yahoo-like feed: poll(symbol, since) → bars after since."""
    name = "yahoo"
    has_ticks = False

    def __init__(self, clock, bars=None, boom=None):
        self.clock, self.bars, self.boom, self.calls = clock, bars if bars is not None else {}, boom, 0

    def now(self):
        return self.clock()

    def poll(self, symbol, since):
        self.calls += 1
        if self.boom:
            raise self.boom
        df = self.bars.get(symbol, pd.DataFrame(columns=KL.COLUMNS))
        return df if since is None else df[df.index > since]

    def history(self, symbol, days=5):
        return pd.DataFrame(columns=KL.COLUMNS)

    def ltp(self, symbols):
        return {s: 1.0 for s in symbols}


def bars(start, closes, vol=0.0):
    idx = pd.date_range(start, periods=len(closes), freq="min", tz=IST)
    return pd.DataFrame({"open": closes, "high": [c + 1 for c in closes], "low": [c - 1 for c in closes], "close": closes, "volume": vol}, index=idx)


def wrapped(clock, inner_bars=None, boom=None):
    live, ws, _ = make(clock)
    inner = Inner(clock, inner_bars, boom)
    return KL.KiteBackedFeed(inner, live), live, ws, inner


def test_complete_fresh_kite_minutes_are_served_without_asking_the_fallback():
    clock = Clock("2026-10-26 10:00:00")
    f, live, ws, inner = wrapped(clock)
    feed_minutes(live, ws, clock, 1, "2026-10-26 10:00:00", [25000.0, 25010.0, 25020.0])
    clock.set("2026-10-26 10:03:10")
    ws.on_ticks(ws, [tick(1, 25020.5, "2026-10-26 10:03:08")])
    since = pd.Timestamp("2026-10-26 10:00:00", tz=IST)
    got = f.poll("NIFTY", since)
    assert list(got.index) == [pd.Timestamp("2026-10-26 10:01:00", tz=IST), pd.Timestamp("2026-10-26 10:02:00", tz=IST)] and inner.calls == 0
    assert f.name == "kite (2 minutes in 1 polls) over yahoo" and f.served["kite"] == 1


def test_a_hole_in_kites_minutes_is_filled_by_the_fallback_and_kite_wins_where_both_have_it():
    clock = Clock("2026-10-26 10:00:00")
    inner_bars = {"NIFTY": bars("2026-10-26 10:01:00", [25010.2, 25020.2, 25030.2], vol=7.0)}
    f, live, ws, inner = wrapped(clock, inner_bars)
    feed_minutes(live, ws, clock, 1, "2026-10-26 10:01:00", [25010.0])                       # Kite has only 10:01
    feed_minutes(live, ws, clock, 1, "2026-10-26 10:03:00", [25030.0])                       # and 10:03; 10:02 is missing
    clock.set("2026-10-26 10:04:10")
    ws.on_ticks(ws, [tick(1, 25030.5, "2026-10-26 10:04:08")])
    got = f.poll("NIFTY", pd.Timestamp("2026-10-26 10:00:00", tz=IST))
    assert inner.calls == 1 and len(got) == 3 and got.index.is_monotonic_increasing
    assert got.loc[pd.Timestamp("2026-10-26 10:01:00", tz=IST), "close"] == 25010.5 and got.loc[pd.Timestamp("2026-10-26 10:02:00", tz=IST), "close"] == 25020.2
    assert (got["volume"] == 7.0).all()                                                         # the fallback's volume stays


def test_the_first_poll_asks_the_fallback_for_the_day_then_overlays_kite():
    clock = Clock("2026-10-26 09:30:30")
    inner_bars = {"NIFTY": bars("2026-10-26 09:15:00", [100.0 + i for i in range(15)])}
    f, live, ws, inner = wrapped(clock, inner_bars)
    got = f.poll("NIFTY", None)
    assert len(got) == 15 and inner.calls == 1


def test_a_kite_minute_far_from_the_fallbacks_is_not_used_and_is_counted():
    clock = Clock("2026-10-26 10:00:00")
    f, live, ws, inner = wrapped(clock, {"NIFTY": bars("2026-10-26 10:01:00", [25000.0, 25010.0])})
    feed_minutes(live, ws, clock, 1, "2026-10-26 10:01:00", [25000.0, 25400.0])                # the second minute is 1.5% off
    clock.set("2026-10-26 10:03:10")
    got = f.poll("NIFTY", pd.Timestamp("2026-10-26 10:00:00", tz=IST))
    assert got.loc[pd.Timestamp("2026-10-26 10:02:00", tz=IST), "close"] == 25010.0 and f.served["rejected"] == 1 and "1 minute(s) rejected" in f.name and f.name.startswith("kite (")


def test_when_the_fallback_raises_kites_unbroken_minutes_still_serve_and_a_hole_does_not():
    clock = Clock("2026-10-26 10:00:00")
    f, live, ws, inner = wrapped(clock, boom=RuntimeError("yahoo returned no 1-minute bars for NIFTY"))
    feed_minutes(live, ws, clock, 1, "2026-10-26 10:01:00", [25000.0])                         # 10:01
    feed_minutes(live, ws, clock, 1, "2026-10-26 10:03:00", [25010.0])                         # 10:03 (10:02 never came)
    clock.set("2026-10-26 10:04:10")
    ws.on_ticks(ws, [tick(1, 25010.5, "2026-10-26 10:04:08")])
    got = f.poll("NIFTY", pd.Timestamp("2026-10-26 10:00:00", tz=IST))
    assert list(got.index) == [pd.Timestamp("2026-10-26 10:01:00", tz=IST)] and f.last_error == "RuntimeError"     # up to the hole, not across it
    with pytest.raises(RuntimeError):                                                           # from the hole on there is nothing unbroken: the fallback's error stands
        f.poll("NIFTY", pd.Timestamp("2026-10-26 10:01:00", tz=IST))


def test_a_silent_websocket_leaves_the_wrapped_feed_exactly_as_it_was():
    clock = Clock("2026-10-26 10:00:00")
    inner_bars = {"NIFTY": bars("2026-10-26 10:01:00", [25000.0, 25010.0])}
    f, live, ws, inner = wrapped(clock, inner_bars)
    got = f.poll("NIFTY", pd.Timestamp("2026-10-26 10:00:00", tz=IST))
    assert got.equals(inner_bars["NIFTY"]) and inner.calls == 1 and not f.has_ltp and f.name == "yahoo (kite websocket silent)"


def test_the_live_price_comes_from_kite_when_fresh_else_from_the_wrapped_feed_and_other_attributes_pass_through():
    clock = Clock("2026-10-26 10:00:00")
    f, live, ws, inner = wrapped(clock)
    ws.on_ticks(ws, [tick(1, 25123.0, "2026-10-26 10:00:00")])
    assert not f.has_ltp                                                                        # the websocket never switches a Yahoo-only desk to deciding on single ticks
    inner.has_ltp = True
    assert f.has_ltp and f.ltp(["NIFTY", "BANKNIFTY"]) == {"NIFTY": 25123.0, "BANKNIFTY": 1.0}
    clock.set("2026-10-26 10:01:00")
    assert f.ltp(["NIFTY"]) == {"NIFTY": 1.0}                                                   # stale: the wrapped feed answers
    assert f.has_ticks is False and f.history("NIFTY").empty and f.now() == clock()


# ---- starting it safely ----------------------------------------------------------------------------------------------------------
def test_without_credentials_or_with_a_broken_library_nothing_starts_and_nothing_raises(monkeypatch):
    said = []
    monkeypatch.delenv("KITE_DATA_KEY", raising=False)
    monkeypatch.delenv("KITE_DATA_TOKEN", raising=False)
    assert KL.make_live(None, ["NIFTY"], say=said.append) is None and "no KITE_DATA_KEY" in said[0]
    monkeypatch.setenv("KITE_DATA_KEY", "k")
    monkeypatch.setenv("KITE_DATA_TOKEN", "t")

    class Boom:
        def __init__(self, api_key):
            pass

        def set_access_token(self, t):
            pass

        def ltp(self, keys):
            raise RuntimeError("TokenException: Incorrect api_key or access_token. SECRET-DETAIL")
    fake = types.SimpleNamespace(KiteConnect=Boom, KiteTicker=lambda k, t: FakeWS())
    monkeypatch.setitem(sys.modules, "kiteconnect", fake)
    said.clear()
    assert KL.make_live(None, ["NIFTY"], say=said.append) is None
    assert said and "RuntimeError" in said[0] and "SECRET-DETAIL" not in said[0]                # the library's message is not printed
    monkeypatch.delitem(sys.modules, "kiteconnect")
    monkeypatch.setitem(sys.modules, "kiteconnect", None)                                       # the library is not installed
    assert KL.make_live(None, ["NIFTY"], say=said.append) is None


def test_with_credentials_the_websocket_starts_for_the_desks_indices(monkeypatch):
    monkeypatch.setenv("KITE_DATA_KEY", "k")
    monkeypatch.setenv("KITE_DATA_TOKEN", "t")
    made = []

    class Kite:
        def __init__(self, api_key):
            assert api_key == "k"

        def set_access_token(self, t):
            assert t == "t"

        def ltp(self, keys):
            ids = {"NSE:NIFTY 50": 256265, "NSE:NIFTY BANK": 260105, "NSE:INDIA VIX": 264969}
            return {k: {"instrument_token": ids[k]} for k in keys}

    def ticker(k, t):
        w = FakeWS()
        made.append(w)
        return w
    monkeypatch.setitem(sys.modules, "kiteconnect", types.SimpleNamespace(KiteConnect=Kite, KiteTicker=ticker))
    live = KL.make_live(None, ["NIFTY", "BANKNIFTY", "INDIAVIX", "SENSEX"], say=lambda m: None)
    assert live is not None and live.tokens == {"NIFTY": 256265, "BANKNIFTY": 260105, "INDIAVIX": 264969}
    assert made[0].connected and made[0].subscribed == [256265, 260105, 264969]


def test_the_desk_config_turns_it_on_and_the_cli_wraps_the_feed_only_when_it_starts():
    import yaml
    cfg = yaml.safe_load((ROOT / "config" / "quantdesk.yaml").read_text())
    assert cfg["intraday"]["kite"]["live"] is True
    src = (ROOT / "quantdesk" / "intraday" / "cli.py").read_text()
    assert 'cfg.get("intraday.kite.live", False)' in src and "KiteBackedFeed(feed, live)" in src and "if live is not None" in src


def test_the_module_never_touches_orders_the_broker_risk_or_the_journal():
    src = (ROOT / "quantdesk" / "intraday" / "kitelive.py").read_text()
    for forbidden in ("place_order", "modify_order", "cancel_order", "orders(", "positions(", "holdings(", "margins(", "profile(", "KITE_API_SECRET", "KITE_ACCESS_TOKEN", "KITE_API_KEY", "KITE_DATA_SECRET"):
        assert forbidden not in src, forbidden
    assert not re.search(r"^\s*(from|import)\s+(\.\.?\s*)?(quantdesk\.)?(execution|journal|risk|sizing|governor|engine)\b", src, re.M)


# ---- the daily token: script and workflows --------------------------------------------------------------------------------------
import json
import os
import shutil
import subprocess

needs_openssl = pytest.mark.skipif(shutil.which("openssl") is None or shutil.which("git") is None, reason="openssl and git are needed")


def git(cwd, *args):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=cwd, check=True, capture_output=True)


def run_script(cwd, env_extra):
    env = {k: v for k, v in os.environ.items() if not k.startswith("KITE_")}
    env.update(env_extra)
    return subprocess.run(["bash", str(ROOT / "deploy" / "kite-token.sh")], cwd=cwd, env=env, capture_output=True, text=True)


def repo_with_token(tmp_path, secret="S3CRET", token="DAYTOKEN1234567890AB"):
    origin, work = tmp_path / "origin.git", tmp_path / "work"
    subprocess.run(["git", "init", "-q", "--bare", str(origin)], check=True)
    work.mkdir()
    git(work, "init", "-q", "-b", "main")
    (work / "a.txt").write_text("x")
    git(work, "add", "a.txt")
    git(work, "commit", "-q", "-m", "init")
    git(work, "remote", "add", "origin", str(origin))
    git(work, "push", "-q", "origin", "main")
    if token is not None:
        (work / "tok").write_text(token)
        subprocess.run(["openssl", "enc", "-aes-256-cbc", "-pbkdf2", "-salt", "-in", "tok", "-out", "kite_token.enc", "-pass", "env:SEC"], cwd=work, env={**os.environ, "SEC": secret}, check=True)
        git(work, "checkout", "-q", "--orphan", "kite-token")
        git(work, "rm", "-rfq", ".")
        subprocess.run(["openssl", "enc", "-aes-256-cbc", "-pbkdf2", "-salt", "-in", "/dev/stdin", "-out", "kite_token.enc", "-pass", "env:SEC"], cwd=work, input=token.encode(),
                       env={**os.environ, "SEC": secret}, check=True)
        git(work, "add", "kite_token.enc")
        git(work, "commit", "-q", "-m", "token")
        git(work, "push", "-q", "origin", "kite-token")
        git(work, "checkout", "-q", "main")
    return work


@needs_openssl
def test_the_script_exports_a_masked_token_when_the_secret_opens_it(tmp_path):
    work = repo_with_token(tmp_path)
    genv = tmp_path / "genv"
    r = run_script(work, {"KITE_DATA_SECRET": "S3CRET", "GITHUB_ENV": str(genv)})
    assert r.returncode == 0 and genv.read_text() == "KITE_DATA_TOKEN=DAYTOKEN1234567890AB\n"
    assert "::add-mask::DAYTOKEN1234567890AB" in r.stdout and "loaded" in r.stdout


@needs_openssl
def test_every_problem_leaves_the_desk_on_its_existing_feeds_and_exits_zero(tmp_path):
    work = repo_with_token(tmp_path)
    for name, env in (("no secret", {}), ("wrong secret", {"KITE_DATA_SECRET": "WRONG"})):
        genv = tmp_path / f"genv_{name.replace(' ', '_')}"
        r = run_script(work, {**env, "GITHUB_ENV": str(genv)})
        assert r.returncode == 0 and not genv.exists() and "DAYTOKEN" not in r.stdout + r.stderr, name
    bare = tmp_path / "other"
    bare.mkdir()
    work2 = repo_with_token(bare, token=None)                                                   # no kite-token branch yet
    genv = tmp_path / "genv_none"
    r = run_script(work2, {"KITE_DATA_SECRET": "S3CRET", "GITHUB_ENV": str(genv)})
    assert r.returncode == 0 and not genv.exists() and "no kite-token branch" in r.stdout


def workflow(name):
    import yaml
    path = ROOT / ".github" / "workflows" / name
    return path.read_text(), yaml.load(path.read_text(), Loader=yaml.BaseLoader), path


def test_the_token_workflow_writes_one_encrypted_file_to_one_branch_and_nothing_else():
    import sys
    sys.path.insert(0, str(ROOT / "deploy"))
    import check_workflows
    text, wf, path = workflow("kite-token.yml")
    assert wf["permissions"] == {"contents": "write"} and set(wf["on"]) == {"workflow_dispatch"} and check_workflows.check(path) == []
    assert wf["defaults"]["run"]["shell"] == "bash" and sorted(set(re.findall(r"secrets\.([A-Z_]+)", text))) == ["KITE_API_KEY", "KITE_API_SECRET"]
    steps = [s for j in wf["jobs"].values() for s in j["steps"]]
    assert all("${{" not in s["run"] for s in steps if "run" in s)                              # the request_token comes in through env only
    assert text.count("git push") == 1 and "git push -q origin kite-token" in text and not re.search(r"git push[^\n]*(--force|\s-f\b)", text)
    assert "openssl enc -aes-256-cbc" in text and "cp \"$RUNNER_TEMP/kite_token.enc\" kite_token.enc" in text and "git add kite_token.enc" in text


def test_live_yml_has_the_api_key_at_workflow_level_and_the_secret_only_in_the_two_token_steps():
    text, wf, _ = workflow("live.yml")
    assert wf["env"]["KITE_DATA_KEY"] == "${{ secrets.KITE_API_KEY }}" and "KITE_DATA_SECRET" not in wf["env"] and "KITE_DATA_TOKEN" not in text.split("jobs:")[0]
    assert "KITE_API_KEY:" not in text and "KITE_ACCESS_TOKEN" not in text                      # the broker adapter's names are never set by this workflow
    holders = []
    for jn, job in wf["jobs"].items():
        assert "KITE_API_SECRET" not in json.dumps(job.get("env", {}))
        for s in job["steps"]:
            assert not ("pip install" in s.get("run", "") and "KITE_API_SECRET" in json.dumps(s.get("env", {})))      # the install step never holds the secret
            if "KITE_API_SECRET" in json.dumps(s.get("env", {})):
                holders.append((jn, s["name"], s.get("continue-on-error")))
    assert [h[0] for h in holders] == ["morning", "afternoon"] and all(h[2] == "true" for h in holders)
    for jn in ("morning", "afternoon"):                                                         # the token step comes before the session starts
        names = [s.get("name", "") for s in wf["jobs"][jn]["steps"]]
        tok = next(i for i, n in enumerate(names) if n.startswith("Kite token"))
        trade = next(i for i, n in enumerate(names) if n.startswith("Trade (paper)"))
        assert tok < trade


# ---- the Data panel (display only) ----------------------------------------------------------------------------------------------
def test_status_tells_the_panel_whether_the_websocket_is_delivering_and_how_old_each_price_is():
    clock = Clock("2026-10-26 10:00:00")
    f, live, ws, inner = wrapped(clock)
    st = f.status()
    assert st["attached"] and st["connected"] and not st["live"] and st["polls"] == 0
    assert st["symbols"] == {"NIFTY": {"age_s": None}, "INDIAVIX": {"age_s": None}}
    clock.set("2026-10-26 10:00:20")
    ws.on_ticks(ws, [tick(1, 25000.0, "2026-10-26 10:00:19")])
    clock.set("2026-10-26 10:00:25")
    st = f.status()
    assert st["live"] and st["symbols"]["NIFTY"] == {"age_s": 5.0} and "25000" not in json.dumps(st)        # never a Kite price: that data is not published
    clock.set("2026-10-26 10:05:00")                                                           # silent for minutes: not live, and the age says so
    st = f.status()
    assert not st["live"] and st["symbols"]["NIFTY"]["age_s"] == 280.0
    inner.boom = RuntimeError("yahoo is down " + "x" * 400)
    with pytest.raises(RuntimeError):                                                          # nothing from Kite and the fallback down: the error still surfaces
        f.poll("NIFTY", None)
    assert f.status()["last_error"] == "RuntimeError" and f.status()["fallback_polls"] >= 1


def test_the_heartbeat_carries_the_data_block_and_a_broken_status_costs_it_nothing(cfg, tmp_path):
    from quantdesk.core.calendar import TradingCalendar
    from quantdesk.intraday.engine import IntradayEngine, run_replay
    from quantdesk.intraday.feeds import ReplayFeed
    from quantdesk.intraday.learning import Memory
    from quantdesk.intraday.sim import IntradayBroker
    from quantdesk.intraday.synthetic import simulate_sessions
    from quantdesk.journal.journal import Journal
    days = [d.date() for d in TradingCalendar(cfg.holidays()).trading_days("2026-09-21", "2026-09-28")]
    bars, _ = simulate_sessions(days, seed=11)
    eng = IntradayEngine(cfg, ReplayFeed(bars, days[-1]), "model", Journal(), IntradayBroker(cfg, starting_cash=500000),
                         say=None, memory=Memory(tmp_path / "memory.json"))
    run_replay(eng)
    d = eng.journal.get_state("intraday_live")["data"]
    assert d["feed"] == eng.feed.name and d["kite"] is None                                    # a feed without a websocket has no Kite block
    assert set(d["bars"]) == {*eng.underlyings, eng.vix} and all(b["last_bar"] and b["age_s"] >= 0 for b in d["bars"].values())
    eng.feed.status = lambda: {"attached": True, "live": True}                                  # a feed that has one: carried through as is
    assert eng._data_status(eng.last_ts[eng.underlyings[0]])["kite"] == {"attached": True, "live": True}

    def boom():
        raise RuntimeError("broken")
    eng.feed.status = boom
    assert eng._data_status(eng.last_ts[eng.underlyings[0]]) is None                           # never costs the desk its heartbeat


def test_the_app_has_a_data_panel_that_hides_itself_without_data():
    html = (ROOT / "quantdesk/web/static/app/index.html").read_text(encoding="utf-8")
    js = (ROOT / "quantdesk/web/static/app/app.js").read_text(encoding="utf-8")
    assert 'id="d-data-wrap"' in html and 'id="d-data"' in html and 'id="d-data-hint"' in html
    assert "function renderData(hb)" in js and "renderData(hb);" in js and "wrap.hidden = !d" in js
    assert "hb.data" in js


# ======================================================================================================================================================
# The risk review and audit of 456b289: the live price is vetted, every path is checked, Kite's faults never reach the engine, partial and stale data
# is not served, the cash session only, Kite minutes stay out of the recorder, and the token command exists.
# ======================================================================================================================================================
def test_a_jump_in_the_live_price_is_believed_only_if_the_wrapped_feed_agrees():
    clock = Clock("2026-10-26 10:00:00")
    f, live, ws, inner = wrapped(clock)
    inner.has_ltp = True
    f._last_close["NIFTY"] = 25000.0
    clock.set("2026-10-26 10:00:30")
    ws.on_ticks(ws, [tick(1, 26500.0, "2026-10-26 10:00:29")])                                 # 6% from the last served close
    assert f.ltp(["NIFTY"]) == {"NIFTY": 1.0}                                                   # the wrapped feed says 1.0: the tick is not believed, the wrapped feed answers
    assert f.served["rejected"] == 1
    inner.ltp = lambda syms: {s: 26490.0 for s in syms}                                         # the wrapped feed agrees (within 0.5%): a real move
    assert f.ltp(["NIFTY"]) == {"NIFTY": 26500.0}
    ws.on_ticks(ws, [tick(1, 25010.0, "2026-10-26 10:00:31")])                                  # an ordinary move: no second opinion asked
    inner.ltp = lambda syms: (_ for _ in ()).throw(AssertionError("must not be asked"))
    assert f.ltp(["NIFTY"]) == {"NIFTY": 25010.0}


def test_when_the_fallback_raises_a_jumping_kite_minute_is_not_served():
    clock = Clock("2026-10-26 10:00:00")
    f, live, ws, inner = wrapped(clock, boom=RuntimeError("yahoo down"))
    f._last_close["NIFTY"] = 25000.0
    feed_minutes(live, ws, clock, 1, "2026-10-26 10:01:00", [25800.0])                         # 3.2% off the last served close
    clock.set("2026-10-26 10:02:10")
    ws.on_ticks(ws, [tick(1, 25800.5, "2026-10-26 10:02:08")])
    with pytest.raises(RuntimeError, match="yahoo down"):
        f.poll("NIFTY", pd.Timestamp("2026-10-26 10:00:00", tz=IST))


def test_a_kite_only_minute_is_added_only_if_it_continues_without_a_hole_or_a_jump_and_gets_the_futures_volume():
    clock = Clock("2026-10-26 10:00:00")
    inner_bars = {"NIFTY": bars("2026-10-26 10:01:00", [25000.0, 25001.0]).assign(volume=9.0)}
    f, live, ws, inner = wrapped(clock, inner_bars)
    f._with_volume = lambda sym, df, now: df.assign(volume=9.0)
    feed_minutes(live, ws, clock, 1, "2026-10-26 10:03:00", [25002.0])                         # continues the fallback's 10:02: added
    feed_minutes(live, ws, clock, 1, "2026-10-26 10:05:00", [25003.0])                         # 10:04 missing everywhere: a hole, not added
    clock.set("2026-10-26 10:06:10")
    ws.on_ticks(ws, [tick(1, 25003.5, "2026-10-26 10:06:08")])
    got = f.poll("NIFTY", pd.Timestamp("2026-10-26 10:00:00", tz=IST))
    assert [t.strftime("%H:%M") for t in got.index] == ["10:01", "10:02", "10:03"] and list(got["volume"]) == [9.0, 9.0, 9.0]
    assert f.served["holes"] == 1
    assert "10:03" in {t.strftime("%H:%M") for t in f.unrecorded("NIFTY")}                      # served from Kite: kept out of the recorder


def test_a_fallback_that_returns_nothing_does_not_let_kite_serve_across_a_hole():
    clock = Clock("2026-10-26 10:00:00")
    f, live, ws, inner = wrapped(clock, {})
    feed_minutes(live, ws, clock, 1, "2026-10-26 10:01:00", [25000.0])
    feed_minutes(live, ws, clock, 1, "2026-10-26 10:03:00", [25001.0])                         # 10:02 is missing
    clock.set("2026-10-26 10:04:10")
    ws.on_ticks(ws, [tick(1, 25001.5, "2026-10-26 10:04:08")])
    got = f.poll("NIFTY", pd.Timestamp("2026-10-26 10:00:00", tz=IST))
    assert [t.strftime("%H:%M") for t in got.index] == ["10:01"]                                # 10:03 is not served across the hole


def test_a_partial_minute_a_straggler_and_minutes_outside_the_cash_session_are_not_served():
    live, ws, clock = make(Clock("2026-10-26 10:00:41"))
    ws.on_ticks(ws, [tick(1, 25000.0, "2026-10-26 10:00:40")])                                 # first tick 40 s into the minute: connected late, a partial minute
    clock.set("2026-10-26 10:00:56")
    ws.on_ticks(ws, [tick(1, 25001.0, "2026-10-26 10:00:55")])
    clock.set("2026-10-26 10:01:05")
    ws.on_ticks(ws, [tick(1, 25010.0, "2026-10-26 10:01:02")])
    clock.set("2026-10-26 10:02:05")
    assert list(live.bars("NIFTY")["close"]) == [25010.0] and live.dropped["partial_minute"] == 1
    ws.on_ticks(ws, [tick(1, 99999.0, "2026-10-26 10:01:59")])                                  # a straggler for a minute that has been read and closed
    clock.set("2026-10-26 10:03:05")
    assert list(live.bars("NIFTY")["close"]) == [25010.0] and live.dropped["late"] >= 1
    early = Clock("2026-10-26 08:31:30")                                                       # pre-open: 08:31 and 15:30 are not cash-session minutes
    live2, ws2, clock2 = make(early)
    ws2.on_ticks(ws2, [tick(1, 25000.0, "2026-10-26 08:31:01")])
    clock2.set("2026-10-26 08:32:05")
    assert live2.bars("NIFTY").empty
    clock2.set("2026-10-26 15:30:01")
    ws2.on_ticks(ws2, [tick(1, 25000.0, "2026-10-26 15:30:00")])
    clock2.set("2026-10-26 15:31:05")
    assert live2.bars("NIFTY").empty


def test_a_fault_inside_the_kite_logic_hands_the_poll_to_the_wrapped_feed_and_an_error_of_the_wrapped_feed_stands():
    clock = Clock("2026-10-26 10:00:00")
    inner_bars = {"NIFTY": bars("2026-10-26 10:01:00", [25000.0, 25010.0])}
    f, live, ws, inner = wrapped(clock, inner_bars)
    feed_minutes(live, ws, clock, 1, "2026-10-26 10:01:00", [25000.0])
    clock.set("2026-10-26 10:02:10")
    ws.on_ticks(ws, [tick(1, 25000.5, "2026-10-26 10:02:08")])
    live.bars = lambda sym: (_ for _ in ()).throw(ValueError("a bug in the Kite side"))
    got = f.poll("NIFTY", pd.Timestamp("2026-10-26 10:00:00", tz=IST))
    assert got.equals(inner_bars["NIFTY"]) and f.served["kite_faults"] == 1 and f.last_error == "ValueError"
    inner.ltp = lambda s: {"NIFTY": 7.0}
    live.ltp = lambda s: (_ for _ in ()).throw(ValueError("tick store broke"))
    assert f.ltp(["NIFTY"]) == {"NIFTY": 7.0}                                                   # the live price falls back too
    inner.boom = RuntimeError("kotak down")
    live.bars = lambda sym: pd.DataFrame(columns=KL.COLUMNS)
    with pytest.raises(RuntimeError, match="kotak down"):
        f.poll("NIFTY", pd.Timestamp("2026-10-26 10:00:00", tz=IST))                            # the wrapped feed's own failure is the engine's to count


def test_every_tenth_otherwise_kite_only_poll_also_asks_the_fallback_so_disagreement_has_a_denominator():
    clock = Clock("2026-10-26 10:00:00")
    inner_bars = {"NIFTY": bars("2026-10-26 10:01:00", [25000.0 + i for i in range(30)])}
    f, live, ws, inner = wrapped(clock, inner_bars)
    for i in range(1, 21):
        feed_minutes(live, ws, clock, 1, f"2026-10-26 10:{i:02d}:00", [25000.0 + i - 1])
        clock.set(f"2026-10-26 10:{i + 1:02d}:10")
        ws.on_ticks(ws, [tick(1, 25000.0 + i, f"2026-10-26 10:{i + 1:02d}:08")])
        f.poll("NIFTY", pd.Timestamp(f"2026-10-26 10:{i - 1:02d}:00", tz=IST))                 # the engine's last bar is the minute before
    assert f.served["fallback"] >= 2 and f.served["compared"] >= 2                             # the fallback was consulted on a sample, and minutes were compared
    assert f.served["polls"] == 20


def test_kite_served_minutes_are_kept_out_of_the_recorder_by_the_engine(cfg, tmp_path):
    from quantdesk.core.calendar import TradingCalendar
    from quantdesk.intraday.engine import IntradayEngine, run_replay
    from quantdesk.intraday.feeds import ReplayFeed
    from quantdesk.intraday.learning import Memory
    from quantdesk.intraday.sim import IntradayBroker
    from quantdesk.intraday.synthetic import simulate_sessions
    from quantdesk.journal.journal import Journal
    days = [d.date() for d in TradingCalendar(cfg.holidays()).trading_days("2026-09-21", "2026-09-28")]
    bars_, _ = simulate_sessions(days, seed=11)

    class Rec:
        def __init__(self):
            self.rows = []

        def record_bars(self, sym, df):
            self.rows.append((sym, df))

        def fill_bars(self, *a):
            return 0

        def __getattr__(self, name):
            return lambda *a, **k: None

    class Kitey(ReplayFeed):
        def unrecorded(self, sym):                                   # stands in for KiteBackedFeed: every 10 o'clock minute was "served from Kite"
            b = self.bars_for(sym) if hasattr(self, "bars_for") else None
            return {t for t in self._all_index(sym) if t.hour == 10}

        def _all_index(self, sym):
            return [t for df in self._seen.get(sym, []) for t in df.index]

        def poll(self, symbol, since):
            out = super().poll(symbol, since)
            if out is not None and len(out):
                self._seen = getattr(self, "_seen", {})
                self._seen.setdefault(symbol, []).append(out)
            return out
    feed = Kitey(bars_, days[-1])
    rec = Rec()
    eng = IntradayEngine(cfg, feed, "model", Journal(), IntradayBroker(cfg, starting_cash=500000), recorder=rec, say=None, memory=Memory(tmp_path / "m.json"))
    run_replay(eng)
    recorded = [t for sym, df in rec.rows if "-FUT" not in sym for t in df.index]
    assert recorded and not any(t.hour == 10 for t in recorded)                                  # nothing the feed flagged reached the recorder
    assert any(t.hour == 11 for t in recorded) or any(t.hour == 12 for t in recorded)           # and everything else did


def test_the_token_command_exists_exchanges_with_the_data_names_and_never_prints_the_token(tmp_path, monkeypatch, capsys):
    import types as _t
    from quantdesk.cli import main
    out = tmp_path / "tok"
    monkeypatch.setenv("KITE_DATA_KEY", "k")
    monkeypatch.setenv("KITE_DATA_SECRET", "s")
    monkeypatch.setenv("KITE_REQUEST_TOKEN", "req")

    class KC:
        def __init__(self, api_key):
            assert api_key == "k"

        def generate_session(self, req, api_secret):
            assert (req, api_secret) == ("req", "s")
            return {"access_token": "ABCDEFGH12345678ijkl"}
    monkeypatch.setitem(sys.modules, "kiteconnect", _t.SimpleNamespace(KiteConnect=KC))
    main(["data", "kite-token", "--out", str(out)])
    assert out.read_text() == "ABCDEFGH12345678ijkl" and oct(out.stat().st_mode)[-3:] == "600"
    assert "ABCDEFGH" not in capsys.readouterr().out
    out.unlink()

    class Bad(KC):
        def generate_session(self, req, api_secret):
            raise RuntimeError("TokenException secret-detail s")
    monkeypatch.setitem(sys.modules, "kiteconnect", _t.SimpleNamespace(KiteConnect=Bad))
    with pytest.raises(SystemExit) as e:
        main(["data", "kite-token", "--out", str(out)])
    assert "secret-detail" not in str(e.value) and not out.exists()

    class Weird(KC):
        def generate_session(self, req, api_secret):
            return {"access_token": "bad\nvalue=1"}
    monkeypatch.setitem(sys.modules, "kiteconnect", _t.SimpleNamespace(KiteConnect=Weird))
    with pytest.raises(SystemExit, match="unexpected shape"):
        main(["data", "kite-token", "--out", str(out)])
    assert not out.exists()


@needs_openssl
def test_a_garbage_decrypt_with_a_newline_can_never_inject_into_the_job_environment(tmp_path):
    work = repo_with_token(tmp_path, token="GOOD0000TOKEN11112222")
    genv = tmp_path / "genv_bad"
    bad = repo_with_token(tmp_path / "bad", token="line1\nEVIL=1")                              # a "valid" file whose plaintext is not token-shaped
    r = run_script(bad, {"KITE_DATA_SECRET": "S3CRET", "GITHUB_ENV": str(genv)})
    assert r.returncode == 0 and not genv.exists() and "not token-shaped" in r.stdout
