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
        self.orders = [o for o in self.orders if o["id"] != res["id"]]

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


def go(cfg, relay, clock, tmp_path, minutes=1, say=None):
    return S.run(cfg, relay, tmp_path / "ledger" / "account.json", (clock.t + dt.timedelta(minutes=minutes)).astimezone(IST).time(), every_s=3.0,
                 clock=clock, sleep=clock.sleep, say=say or (lambda *a: None))


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
    S.run(cfg, rl, tmp_path / "l.json", (clk.t + dt.timedelta(minutes=1)).astimezone(IST).time(), every_s=3.0, clock=clk, sleep=sleep, say=lambda *a: None)
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
        S.run(cfg, rl, tmp_path / "l.json", (clk.t + dt.timedelta(minutes=5)).astimezone(IST).time(), every_s=3.0, clock=clk, sleep=sleep, say=lambda *a: None)
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
    S.run(cfg, rl, tmp_path / "l.json", (clk.t + dt.timedelta(minutes=1)).astimezone(IST).time(), every_s=3.0, clock=clk, sleep=sleep, say=lambda *a: None)
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
