"""The paper runner's session loop and its line to the relay: restore, cycle, save, report; and the relay client's safety (https only, no redirects, no token in an error)."""
import datetime as dt
import io
import json
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from quantdesk.config import Config
from quantdesk.markets import sessions as MK
from quantdesk.paper import runner as R
from quantdesk.paperlink import session as S
from quantdesk.paper.account import Account
from quantdesk.paperlink.relay import Relay, RelayError, base_of

ROOT = Path(__file__).resolve().parents[1]
IST = MK.IST
T0 = dt.datetime(2026, 11, 9, 10, 0, tzinfo=IST)
NAME = "NIFTY12NOV2624500CE"


@pytest.fixture()
def cfg():
    return Config.load(ROOT / "config" / "quantdesk.yaml")


class Clock:
    def __init__(self, t=T0):
        self.t = t

    def __call__(self):
        return self.t.astimezone(dt.timezone.utc)

    def sleep(self, s):
        self.t += dt.timedelta(seconds=s)


class FakeRelay:
    """What the Worker will do: a queue the owner fills, a kill flag, results, a state; each call can be made to fail."""
    def __init__(self, clock):
        self.clock, self.orders, self.kill, self.results, self.state, self.fail = clock, [], False, [], {}, set()
        self.q = {NAME: dict(bid=99.0, ask=100.0, bid_qty=5000, ask_qty=5000, ltp=99.5, age_s=1.0)}

    def _f(self, what):
        if what in self.fail:
            raise RelayError(f"{what}: HTTP 503")

    def snapshot(self):
        self._f("snapshot")
        return {"now": int(self.clock().timestamp() * 1000), "quotes": self.q}

    def queue(self):
        self._f("queue")
        return {"kill": self.kill, "orders": list(self.orders)}

    def post_result(self, res):
        self._f("result")
        self.results.append(res)
        self.orders = [o for o in self.orders if not (isinstance(o, dict) and o.get("id") == res["id"])]

    def put_state(self, summary, account_text):
        self._f("state")
        self.state["summary"] = summary
        if account_text is not None:
            self.state["account"] = account_text

    def get_state(self):
        self._f("get_state")
        return dict(self.state)

    def add(self, oid="ord-0001", **kw):
        o = dict(id=oid, side="buy", symbol=NAME, lots=1, strategy="breakout", thesis="range break with rising volume on the 30 minute chart", queued_at=int(self.clock().timestamp() * 1000))
        o.update(kw)
        self.orders.append(o)


def go(cfg, relay, clock, tmp_path, minutes=1, say=None, new=True):
    return S.run(cfg, relay, tmp_path / "ledger" / "account.json", (clock.t + dt.timedelta(minutes=minutes)).astimezone(IST).time(), every_s=3.0,
                 clock=clock, sleep=clock.sleep, say=say or (lambda *a: None), new_account=new)


def test_an_order_is_filled_saved_to_disk_and_the_relay_and_its_result_reported(cfg, tmp_path):
    clk = Clock()
    rl = FakeRelay(clk)
    rl.add()
    assert go(cfg, rl, clk, tmp_path) == 0
    assert [r["status"] for r in rl.results] == ["filled"] and rl.results[0]["fill"]["price"] == 100.0
    saved = R.load_account(rl.state["account"])
    assert len(saved.ledger) == 1 and NAME in saved.positions and rl.state["summary"]["positions"][0]["symbol"] == NAME
    assert R.load_account((tmp_path / "ledger" / "account.json").read_text()).ledger == saved.ledger                  # the disk copy is the same account


def test_a_restart_continues_from_the_saved_account_and_never_fills_a_replayed_order_twice(cfg, tmp_path):
    clk = Clock()
    rl = FakeRelay(clk)
    rl.add()
    go(cfg, rl, clk, tmp_path)
    rl2 = FakeRelay(clk)
    rl2.state = dict(rl.state)                                                                                        # the relay kept the account
    rl2.add()                                                                                                          # the same order id comes round again (the result post was lost)
    go(cfg, rl2, clk, tmp_path)
    assert [r["status"] for r in rl2.results] == ["done"] and R.load_account(rl2.state["account"]).positions[NAME].qty == 65


def test_the_ledger_branch_is_used_when_the_relay_has_lost_its_state_and_a_conflict_stops_the_start(cfg, tmp_path):
    clk = Clock()
    rl = FakeRelay(clk)
    rl.add()
    go(cfg, rl, clk, tmp_path)
    lost = FakeRelay(clk)                                                                                              # a relay with no state; the branch file is on disk
    said = []
    go(cfg, lost, clk, tmp_path, say=said.append)
    assert any("ledger branch" in m for m in said) and R.load_account(lost.state["account"]).positions                # and the relay is given it back
    other = Account(500_000)
    other.record_event("note", T0.isoformat(), text="a different history")
    conflict = FakeRelay(clk)
    conflict.state = {"account": R.account_json(other)}
    with pytest.raises(SystemExit) as e:
        go(cfg, conflict, clk, tmp_path)
    assert "different histories" in str(e.value)


def test_a_new_account_starts_with_the_papers_capital_and_a_tampered_one_stops_the_start(cfg, tmp_path):
    clk = Clock()
    rl = FakeRelay(clk)
    said = []
    go(cfg, rl, clk, tmp_path, say=said.append)
    assert any("new paper account" in m and "500,000" in m for m in said)
    d = json.loads(rl.state["account"])
    d["cash"] += 1
    bad = FakeRelay(clk)
    bad.state = {"account": json.dumps(d)}
    with pytest.raises(SystemExit) as e:
        go(cfg, bad, clk, tmp_path / "x")
    assert "does not verify" in str(e.value)


def test_without_the_relay_at_the_start_nothing_starts(cfg, tmp_path):
    clk = Clock()
    rl = FakeRelay(clk)
    rl.fail = {"get_state"}
    with pytest.raises(SystemExit) as e:
        go(cfg, rl, clk, tmp_path)
    assert "not starting" in str(e.value)


def test_an_outage_mid_session_loses_nothing_results_are_retried_and_state_is_resent(cfg, tmp_path):
    clk = Clock()
    rl = FakeRelay(clk)
    rl.add()
    rl.fail = {"result", "state"}
    cycles = {"n": 0}
    orig = clk.sleep

    def sleep(s):
        cycles["n"] += 1
        if cycles["n"] == 4:
            rl.fail = set()                                                                                            # the relay recovers
        orig(s)
    S.run(cfg, rl, tmp_path / "l.json", (clk.t + dt.timedelta(minutes=1)).astimezone(IST).time(), every_s=3.0, clock=clk, sleep=sleep, say=lambda *a: None, new_account=True)
    assert [r["status"] for r in rl.results] == ["filled"]                                                             # reported once, after the outage
    assert len(R.load_account(rl.state["account"]).ledger) == 1                                                        # and the account reached the relay


def test_an_unreachable_board_skips_cycles_without_crashing_or_trading(cfg, tmp_path):
    clk = Clock()
    rl = FakeRelay(clk)
    rl.add()
    rl.fail = {"snapshot"}
    assert go(cfg, rl, clk, tmp_path) == 0 and not rl.results and len(rl.orders) == 1


def test_the_kill_flag_reaches_the_gate_and_clearing_it_resumes(cfg, tmp_path):
    clk = Clock()
    rl = FakeRelay(clk)
    rl.add("ord-0001")
    go(cfg, rl, clk, tmp_path)
    rl.kill = True
    rl.add("ord-0002")
    go(cfg, rl, clk, tmp_path)
    assert rl.results[-1]["status"] == "refused" and not R.load_account(rl.state["account"]).positions                # flattened by the kill, new entry refused
    rl.kill = False
    rl.add("ord-0003")
    go(cfg, rl, clk, tmp_path)
    assert rl.results[-1]["status"] == "filled"


# ---- the relay client -------------------------------------------------------------------------------------------------------------------
class Resp:
    def __init__(self, body=b"{}", status=200):
        self.body, self.status = body, status

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self, n=-1):
        return self.body[:n] if n >= 0 else self.body


def test_the_relay_client_is_https_only_keeps_each_key_to_its_calls_and_never_leaks_a_token(monkeypatch):
    with pytest.raises(ValueError):
        Relay("http://x.workers.dev/live/ingest", "r" * 40, "i" * 40)
    with pytest.raises(ValueError):
        Relay("https://x.workers.dev/live/ingest", "", "i" * 40)
    assert base_of("https://x.workers.dev/live/ingest") == "https://x.workers.dev" and base_of("https://x.workers.dev/") == "https://x.workers.dev"
    seen = []

    def opener(req, timeout=None):
        seen.append((req.get_method(), req.full_url, req.get_header("Authorization"), req.data))
        return Resp(b'{"ok": true}')
    rl = Relay("https://x.workers.dev/live/ingest", "R" * 40, "I" * 40, opener=opener)
    rl.snapshot(); rl.queue(); rl.post_result({"id": "a"}); rl.put_state({"a": 1}, "text"); rl.get_state()
    assert [(m, u.split("workers.dev")[1], a[-1]) for m, u, a, _ in seen] == [("GET", "/live/snapshot", "R"), ("GET", "/paper/queue", "I"), ("POST", "/paper/result", "I"), ("POST", "/paper/state", "I"), ("GET", "/paper/state?full=1", "I")]
    assert json.loads(seen[3][3]) == {"summary": {"a": 1}, "account": "text"}


def test_relay_errors_carry_a_status_or_a_class_and_never_the_url_or_the_token_and_big_answers_are_refused():
    secret = "S3CRET" * 7

    def boom(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 401, "no", {}, io.BytesIO(b""))

    def dead(req, timeout=None):
        raise OSError(f"connect to {req.full_url} with {req.get_header('Authorization')} failed")
    for op in (boom, dead):
        with pytest.raises(RelayError) as e:
            Relay("https://x.workers.dev/live/ingest", secret, secret, opener=op).queue()
        assert secret not in str(e.value) and "workers.dev" not in str(e.value)
    with pytest.raises(RelayError):
        Relay("https://x.workers.dev/live/ingest", "a", "b", opener=lambda r, timeout=None: Resp(b"x" * 4_000_100)).queue()
    with pytest.raises(RelayError):
        Relay("https://x.workers.dev/live/ingest", "a", "b", opener=lambda r, timeout=None: Resp(b"[1]")).queue()
    with pytest.raises(RelayError):
        Relay("https://x.workers.dev/live/ingest", "a", "b", opener=lambda r, timeout=None: Resp(b"not json")).queue()


def test_a_redirect_is_refused_so_the_key_never_follows_it():
    from quantdesk.paperlink.relay import _NoRedirect
    req = urllib.request.Request("https://x.workers.dev/paper/queue", headers={"Authorization": "Bearer abc"})
    assert _NoRedirect().redirect_request(req, None, 302, "Found", {}, "https://evil.example/") is None


def test_the_cli_verifies_a_saved_account(cfg, tmp_path, capsys):
    from quantdesk.paperlink import cli as C
    a = Account(500_000)
    f = tmp_path / "a.json"
    a.save(f)
    C.cmd_verify(cfg, type("A", (), {"file": str(f)}))
    assert "ok" in capsys.readouterr().out
    d = a.to_dict(); d["cash"] = 1
    f.write_text(json.dumps(d))
    with pytest.raises(SystemExit) as e:
        C.cmd_verify(cfg, type("A", (), {"file": str(f)}))
    assert e.value.code == 1


def test_a_fill_is_on_disk_before_the_session_ends_so_a_crash_cannot_lose_it(cfg, tmp_path):
    clk = Clock()
    rl = FakeRelay(clk)
    rl.add()
    n = {"c": 0}

    def sleep(s):
        n["c"] += 1
        if n["c"] == 2:
            raise KeyboardInterrupt                                                                                    # the job is killed mid-session
        clk.sleep(s)
    with pytest.raises(KeyboardInterrupt):
        S.run(cfg, rl, tmp_path / "l.json", (clk.t + dt.timedelta(minutes=5)).astimezone(IST).time(), every_s=3.0, clock=clk, sleep=sleep, say=lambda *a: None, new_account=True)
    assert NAME in R.load_account((tmp_path / "l.json").read_text()).positions


def test_a_fill_made_while_the_state_upload_fails_reaches_the_relay_when_it_recovers(cfg, tmp_path):
    clk = Clock()
    rl = FakeRelay(clk)
    n = {"c": 0}
    orig = clk.sleep

    def sleep(s):
        n["c"] += 1
        if n["c"] == 2:                                                                                                # after the first state upload succeeded: the owner trades, then the relay stumbles
            rl.add()
            rl.fail = {"state"}
        if n["c"] == 6:
            rl.fail = set()
        orig(s)
    S.run(cfg, rl, tmp_path / "l.json", (clk.t + dt.timedelta(minutes=1)).astimezone(IST).time(), every_s=3.0, clock=clk, sleep=sleep, say=lambda *a: None, new_account=True)
    assert NAME in R.load_account(rl.state["account"]).positions


def test_the_link_package_has_no_broker_and_no_order_path_and_the_paper_package_stays_pure():
    import ast
    import re
    link = ROOT / "quantdesk" / "paperlink"
    for f in link.glob("*.py"):
        tree = ast.parse(f.read_text(encoding="utf-8"))
        mods = [n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)] + [a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names]
        for m in mods:
            assert not re.search(r"kite|kotak|intraday\.(broker|kotak)|execution\.broker|data\.(kite|kotak)", m, re.I), (f.name, m)
        src = re.sub(r'""".*?"""', "", f.read_text(encoding="utf-8"), flags=re.S)
        assert not re.search(r"place_order|KITE_|KOTAK_|subprocess|socket\b", src), f.name
        assert not re.search(r'_call\([^)]*"/(orders|live/ingest|live/universe)', src), f.name                         # it never writes to the board or calls an order route
    assert not list((ROOT / "quantdesk" / "paper").glob("relay.py")) and not list((ROOT / "quantdesk" / "paper").glob("session.py"))


# ---- the independent review's findings (session level) ---------------------------------------------------------------------------------
def test_a_missing_or_odd_kill_answer_counts_as_on_and_a_normal_off_resumes(cfg, tmp_path):                            # F7a
    clk = Clock()
    rl = FakeRelay(clk)
    rl.add("ord-kill001")
    orig = rl.queue
    rl.queue = lambda: {k: v for k, v in orig().items() if k != "kill"}                                               # an answer with no kill key at all
    go(cfg, rl, clk, tmp_path)
    assert rl.results[-1]["status"] == "refused" and "kill" in " ".join(rl.results[-1]["reasons"])
    rl.queue = lambda: dict(orig(), kill="false")                                                                      # a string is not the boolean false
    rl.add("ord-kill002")
    go(cfg, rl, clk, tmp_path)
    assert rl.results[-1]["status"] == "refused"
    rl.queue = orig
    rl.add("ord-kill003")
    go(cfg, rl, clk, tmp_path)
    assert rl.results[-1]["status"] == "filled"


def test_a_missing_account_everywhere_stops_the_start_unless_it_is_the_declared_first_session(cfg, tmp_path):          # F7c
    clk = Clock()
    with pytest.raises(SystemExit) as e:
        go(cfg, FakeRelay(clk), clk, tmp_path, new=False)
    assert "--new-account" in str(e.value)
    assert go(cfg, FakeRelay(clk), clk, tmp_path, new=True) == 0


def test_a_fill_is_not_reported_until_it_is_safe_on_the_relay(cfg, tmp_path):                                          # F7b
    clk = Clock()
    rl = FakeRelay(clk)
    rl.add("ord-safe001")
    rl.fail = {"state"}
    go(cfg, rl, clk, tmp_path)
    assert rl.results == [] and "account" not in rl.state                                                              # the fill is on disk, but nothing was reported that the relay could lose
    assert NAME in R.load_account((tmp_path / "ledger" / "account.json").read_text()).positions
    rl.fail = set()
    go(cfg, rl, clk, tmp_path, new=False)                                                                              # the next session restores from the branch file and the relay catches up
    assert NAME in R.load_account(rl.state["account"]).positions and [r["status"] for r in rl.results] == ["done"]      # (the order is now known as handled)


def test_a_rising_high_water_mark_is_saved_and_sent_even_with_no_fill(cfg, tmp_path, monkeypatch):                    # F2
    monkeypatch.setattr(S, "FULL_EVERY_S", 0.0)
    clk = Clock()
    rl = FakeRelay(clk)
    rl.add("ord-hwm001")
    n = {"c": 0}
    orig = clk.sleep

    def sleep(s):
        n["c"] += 1
        if n["c"] == 3:
            rl.q[NAME] = dict(bid=160.0, ask=161.0, bid_qty=5000, ask_qty=5000, ltp=160, age_s=1.0)                    # the position is marked up: no fill, but equity (and the mark) rises
        orig(s)
    S.run(cfg, rl, tmp_path / "l.json", (clk.t + dt.timedelta(minutes=1)).astimezone(IST).time(), every_s=3.0, clock=clk, sleep=sleep, say=lambda *a: None, new_account=True)
    on_disk, on_relay = R.load_account((tmp_path / "l.json").read_text()), R.load_account(rl.state["account"])
    assert on_disk.hwm > 500_000 and on_relay.hwm == on_disk.hwm                                                      # both copies carry the new high-water mark


def test_a_poison_queue_entry_or_cycle_error_cannot_kill_the_session_or_lose_a_fill(cfg, tmp_path, monkeypatch):      # F3
    clk = Clock()
    rl = FakeRelay(clk)
    rl.add("ord-good001")
    rl.orders.append({"id": ["not", "a", "string"], "side": "buy"})
    rl.orders.append("junk")
    boom = {"n": 0}
    real = R.Runner.step

    def step(self, *a, **k):
        res = real(self, *a, **k)
        boom["n"] += 1
        if boom["n"] == 1:
            raise RuntimeError("something unexpected after the first order was filled")
        return res
    monkeypatch.setattr(R.Runner, "step", step)
    assert go(cfg, rl, clk, tmp_path) == 0
    assert NAME in R.load_account((tmp_path / "ledger" / "account.json").read_text()).positions                       # the fill made before the error was saved
    assert NAME in R.load_account(rl.state["account"]).positions


def test_the_logs_never_carry_a_line_break_from_outside(cfg, tmp_path):                                                 # F7e
    clk = Clock()
    rl = FakeRelay(clk)
    rl.add("ord-logsafe", symbol="NIFTYZZZZ\n::error::injected")
    said = []
    go(cfg, rl, clk, tmp_path, say=said.append)
    assert said and all("\n" not in m and "\r" not in m for m in said)


def test_a_deeply_nested_or_unencodable_body_is_a_relay_error_not_a_crash():                                           # F3, F7g
    rl = Relay("https://x.workers.dev/live/ingest", "a", "b", opener=lambda r, timeout=None: Resp(b"[" * 200000))
    with pytest.raises(RelayError):
        rl.queue()
    with pytest.raises(RelayError):
        Relay("https://x.workers.dev/live/ingest", "a", "b", opener=lambda r, timeout=None: Resp()).put_state({"x": float("nan"), "ledger_len": 0}, None)


def test_a_big_valid_answer_is_refused_by_size_not_by_accident():                                                       # survivor
    big = b'{"a":"' + b"x" * 4_000_100 + b'"}'
    with pytest.raises(RelayError) as e:
        Relay("https://x.workers.dev/live/ingest", "a", "b", opener=lambda r, timeout=None: Resp(big)).queue()
    assert "too large" in str(e.value)


def test_the_real_opener_refuses_a_redirect_so_the_key_goes_nowhere_else():                                            # survivor
    import http.server
    import threading
    seen = []

    class Target(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            seen.append(self.headers.get("Authorization"))
            self.send_response(200); self.end_headers(); self.wfile.write(b"{}")

        def log_message(self, *a):
            pass
    tgt = http.server.HTTPServer(("127.0.0.1", 0), Target)

    class Redir(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(307); self.send_header("Location", f"http://127.0.0.1:{tgt.server_port}/stolen"); self.end_headers()

        def log_message(self, *a):
            pass
    red = http.server.HTTPServer(("127.0.0.1", 0), Redir)
    for srv in (tgt, red):
        threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        rl = Relay("https://x.workers.dev/live/ingest", "R" * 40, "I" * 40)                                             # its own opener, as built in production
        rl.base = f"http://127.0.0.1:{red.server_port}"                                                                # only the address is swapped, to reach the local server
        with pytest.raises(RelayError) as e:
            rl.queue()
        assert "307" in str(e.value) and seen == []                                                                     # the target never saw a request, let alone the key
    finally:
        tgt.shutdown(); red.shutdown()


def test_a_line_break_in_a_reason_from_anywhere_is_flattened_before_it_is_logged(cfg, tmp_path, monkeypatch):           # F7e, the outer layer
    clk = Clock()
    rl = FakeRelay(clk)
    rl.add("ord-nl000001")
    real = R.Runner.handle
    monkeypatch.setattr(R.Runner, "handle", lambda self, raw, snap_, now: dict(real(self, raw, snap_, now), status="refused", reasons=["line one\n::error::line two\r"]))
    said = []
    go(cfg, rl, clk, tmp_path, say=said.append)
    assert any("refused" in m for m in said) and all("\n" not in m and "\r" not in m for m in said)


def test_buying_stops_when_the_relay_has_not_been_given_the_fills_for_30_seconds_and_resumes_after(cfg, tmp_path):     # R2
    clk = Clock()
    rl = FakeRelay(clk)
    A, B, C, D = "NIFTY12NOV2624600CE", "NIFTY12NOV2624700CE", "NIFTY12NOV2624800CE", "NIFTY12NOV2624900CE"
    for sym in (A, B, C, D):
        rl.q[sym] = dict(bid=39.0, ask=40.0, bid_qty=5000, ask_qty=5000, ltp=39, age_s=1.0)
    rl.add("ord-uns00001")
    n = {"c": 0}
    orig = clk.sleep
    mono = {"t": 1000.0}

    def sleep(s):
        n["c"] += 1
        if n["c"] == 1:
            rl.fail = {"state"}                                                                                        # the relay stops taking the account after the first fill
            rl.add("ord-uns00002", symbol=A)                                                                           # this buy fills but cannot be pushed: the 30 seconds start here
        if n["c"] == 12:                                                                                               # 55+ seconds of real time later
            rl.add("ord-uns00003", symbol=B)                                                                           # refused: the fills could not be kept safe
        if n["c"] == 14:
            rl.fail = set()                                                                                            # the relay is back
        if n["c"] == 16:
            rl.add("ord-uns00004", symbol=C)
        mono["t"] += 5.0                                                                                               # five seconds of real time per cycle
        orig(s)
    import time as _t
    real = _t.monotonic
    _t.monotonic = lambda: mono["t"]
    try:
        S.run(cfg, rl, tmp_path / "l.json", (clk.t + dt.timedelta(minutes=2)).astimezone(IST).time(), every_s=3.0, clock=clk, sleep=sleep, say=lambda *a: None, new_account=True)
    finally:
        _t.monotonic = real
    by = {r["id"]: r for r in rl.results}
    assert by["ord-uns00002"]["status"] == "filled"
    assert by["ord-uns00003"]["status"] == "refused" and "relay could not be given" in " ".join(by["ord-uns00003"]["reasons"])      # not bought while the fills could not be kept safe
    assert by["ord-uns00004"]["status"] == "filled"                                                                    # and bought again once the relay took them


def test_the_opening_state_reaches_the_relay_even_when_no_cycle_runs(cfg, tmp_path):                                    # R3
    clk = Clock()
    rl = FakeRelay(clk)
    S.run(cfg, rl, tmp_path / "l.json", clk.t.astimezone(IST).time(), every_s=3.0, clock=clk, sleep=clk.sleep, say=lambda *a: None, new_account=True)      # the stop time has already come: the loop never runs
    assert R.load_account(rl.state["account"]).capital0 == 500_000                                                      # so the next start finds the account on the relay


def test_an_hwm_only_change_is_on_disk_the_moment_it_happens_not_only_at_the_end(cfg, tmp_path):                       # survivor
    clk = Clock()
    rl = FakeRelay(clk)
    rl.add("ord-hwmd0001")
    n = {"c": 0}

    def sleep(s):
        n["c"] += 1
        if n["c"] == 2:
            rl.q[NAME] = dict(bid=170.0, ask=171.0, bid_qty=5000, ask_qty=5000, ltp=170, age_s=1.0)
        if n["c"] == 4:
            raise KeyboardInterrupt                                                                                    # killed before the end-of-session save
        clk.sleep(s)
    with pytest.raises(KeyboardInterrupt):
        S.run(cfg, rl, tmp_path / "l.json", (clk.t + dt.timedelta(minutes=5)).astimezone(IST).time(), every_s=3.0, clock=clk, sleep=sleep, say=lambda *a: None, new_account=True)
    assert R.load_account((tmp_path / "l.json").read_text()).hwm > 500_000


def test_verify_extends_accepts_a_continuation_and_refuses_a_shorter_or_a_different_history(cfg, tmp_path, capsys):
    import datetime as _dt
    from quantdesk.core.types import Instrument
    from quantdesk.paperlink import cli as C
    base = Account(500_000)
    base.apply_fill("buy", Instrument.option("NIFTY", _dt.date(2026, 11, 12), 24500, "CE", 65), "nse_fo", 65, 100.0, 9.0, T0.isoformat(), "s", "a thesis that is long enough to count")
    old = tmp_path / "old.json"
    base.save(old)
    longer = R.load_account(R.account_json(base))
    longer.apply_fill("sell", Instrument.option("NIFTY", _dt.date(2026, 11, 12), 24500, "CE", 65), "nse_fo", 65, 99.0, 9.0, T0.isoformat(), "s", "exit")
    new = tmp_path / "new.json"
    longer.save(new)
    A = lambda f, e: type("A", (), {"file": str(f), "extends": str(e) if e else None})      # noqa: E731
    C.cmd_verify(cfg, A(new, old))
    assert "continues the branch's account" in capsys.readouterr().out
    with pytest.raises(SystemExit) as e:                                                    # the branch is AHEAD of this file: a shorter ledger is refused
        C.cmd_verify(cfg, A(old, new))
    assert e.value.code == 1
    other = Account(500_000)
    other.apply_fill("buy", Instrument.option("NIFTY", _dt.date(2026, 11, 12), 24000, "CE", 65), "nse_fo", 65, 50.0, 5.0, T0.isoformat(), "s", "a different history entirely")
    other.apply_fill("sell", Instrument.option("NIFTY", _dt.date(2026, 11, 12), 24000, "CE", 65), "nse_fo", 65, 49.0, 5.0, T0.isoformat(), "s", "exit")
    div = tmp_path / "div.json"
    other.save(div)
    with pytest.raises(SystemExit) as e:                                                    # same length, different rows
        C.cmd_verify(cfg, A(div, new))
    assert e.value.code == 1
    C.cmd_verify(cfg, A(new, tmp_path / "missing.json"))                                    # no file on the branch yet: nothing to continue


class _Pilot:
    """A stand-in autopilot: proposes what it is told to, or fails."""
    def __init__(self, orders=None, boom=False):
        self.orders, self.boom, self.calls, self.events = orders or [], boom, 0, []

    def drain_events(self):
        out, self.events = self.events, []
        return out

    def decide(self, snap, account, now, **kw):
        self.calls += 1
        if self.boom:
            raise RuntimeError("the pilot broke")
        out, self.orders = self.orders, []
        return out


def test_a_failing_autopilot_cannot_stop_the_runner_the_brakes_or_the_owners_orders(cfg, tmp_path):
    clk = Clock()
    rl = FakeRelay(clk)
    rl.add()
    lines = []
    pilot = _Pilot(boom=True)
    assert S.run(cfg, rl, tmp_path / "ledger" / "account.json", (clk.t + dt.timedelta(minutes=1)).astimezone(IST).time(), every_s=3.0, clock=clk, sleep=clk.sleep, say=lines.append, new_account=True, auto=pilot) == 0
    assert pilot.calls > 5 and [r["status"] for r in rl.results] == ["filled"]                                         # the owner's order was filled all the same
    assert any("autopilot failed" in m for m in lines)


def test_the_autopilots_orders_go_through_the_same_step_gate_and_result_path(cfg, tmp_path):
    clk = Clock()
    rl = FakeRelay(clk)
    mine = {"id": "auto-b-1-1", "side": "buy", "symbol": NAME, "lots": 1, "strategy": "AUTO v1 NIFTY long call", "thesis": "AUTO v1: pressure +0.40; test of the wiring", "limit": 100.5,
            "queued_at": int(clk().timestamp() * 1000), "group": "auto"}
    bad = {**mine, "id": "auto-b-1-2", "lots": 10_000}                                                                     # an absurd size from the pilot is refused like anyone's
    pilot = _Pilot([mine, bad])
    assert S.run(cfg, rl, tmp_path / "ledger" / "account.json", (clk.t + dt.timedelta(minutes=1)).astimezone(IST).time(), every_s=3.0, clock=clk, sleep=clk.sleep, say=lambda *a: None, new_account=True, auto=pilot) == 0
    status = {r["id"]: r["status"] for r in rl.results}
    assert status["auto-b-1-1"] == "filled" and status["auto-b-1-2"] == "invalid"
    saved = R.load_account(rl.state["account"])
    assert saved.positions[NAME].strategy.startswith("AUTO v1") and saved.verify_ledger()
    rl2 = FakeRelay(Clock())
    rl2.kill = True
    clk2 = rl2.clock
    pilot2 = _Pilot([{**mine, "id": "auto-b-2-1", "queued_at": int(clk2().timestamp() * 1000)}])
    S.run(cfg, rl2, tmp_path / "l2" / "account.json", (clk2.t + dt.timedelta(minutes=1)).astimezone(IST).time(), every_s=3.0, clock=clk2, sleep=clk2.sleep, say=lambda *a: None, new_account=True, auto=pilot2)
    assert {r["id"]: r["status"] for r in rl2.results}["auto-b-2-1"] == "refused"                                          # the owner's kill switch stops the pilot's order too


def test_a_new_peak_from_the_autopilot_is_written_into_the_ledger_and_survives_the_save(cfg, tmp_path):
    clk = Clock()
    rl = FakeRelay(clk)
    rl.add()
    pilot = _Pilot()
    pilot.events = [{"kind": "auto_peak", "symbol": NAME, "opened_at": "2026-11-09T10:00:00+05:30", "peak": 130.5}]
    assert S.run(cfg, rl, tmp_path / "ledger" / "account.json", (clk.t + dt.timedelta(minutes=1)).astimezone(IST).time(), every_s=3.0, clock=clk, sleep=clk.sleep, say=lambda *a: None, new_account=True, auto=pilot) == 0
    saved = R.load_account(rl.state["account"])
    assert any(r["kind"] == "auto_peak" and r["peak"] == 130.5 and r["symbol"] == NAME for r in saved.ledger) and saved.verify_ledger()
    again = R.load_account((tmp_path / "ledger" / "account.json").read_text())
    assert again.ledger == saved.ledger and [r["status"] for r in rl.results] == ["filled"]
