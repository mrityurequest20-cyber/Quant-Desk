"""Audit K-01 (B-01, CRITICAL): a fill made after the relay stopped taking the state was lost at the hand-over. The next part started from the relay's
shorter copy: the fill, a sale (so a sold position came back), the day's cap row and the high-water mark were gone, and the order read "expired".

Now every part hands its own account to the next part (and to the next morning) ENCRYPTED, and each part starts from the longest verified copy among the
relay's, the ledger branch's and the earlier parts' own. The workflow's own shell steps are run here, as they are written, with openssl."""
from __future__ import annotations

import datetime as dt
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from quantdesk.paper import runner as R
from quantdesk.paper.account import Account
from quantdesk.paperlink import cli as C
from quantdesk.paperlink import session as S
from quantdesk.paperlink.relay import RelayError
from tests.test_paper_session import IST, NAME, Clock, FakeRelay, cfg  # noqa: F401 - cfg is a fixture

ROOT = Path(__file__).resolve().parents[1]
WF = yaml.safe_load((ROOT / ".github" / "workflows" / "paper-desk.yml").read_text(encoding="utf-8"))
KEY = "k" * 44
needs_openssl = pytest.mark.skipif(shutil.which("openssl") is None, reason="openssl not installed")


class RefusingRelay(FakeRelay):
    """Takes the opening state, then refuses every save, as the Worker did from 10:16 IST on 20 Nov (HTTP 400 for size)."""
    def __init__(self, clock, take=1):
        super().__init__(clock)
        self.n, self.take = 0, take

    def put_state(self, summary, account_text):
        self.n += 1
        if self.n > self.take:
            raise RelayError("POST /paper/state: HTTP 400")
        return super().put_state(summary, account_text)


def cp(src, dst):
    Path(dst).parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(src, dst)


def step(job, start):
    return next(x for x in WF["jobs"][job]["steps"] if x.get("name", "").startswith(start))


def sh(script, cwd, key=KEY):
    env = {**os.environ, "HANDOVER_KEY": key, "PYTHONPATH": str(ROOT)}
    return subprocess.run(["bash", "-e", "-c", script], cwd=cwd, env=env, capture_output=True, text=True, timeout=120)


def part(cfg, relay, clk, ledger, minutes=2, new=False):
    return S.run(cfg, relay, ledger, (clk.t + dt.timedelta(minutes=minutes)).astimezone(IST).time(), every_s=3.0, clock=clk, sleep=clk.sleep,
                 say=lambda *a: None, new_account=new)


def hand_over(job_from, job_to, src: Path, dst_root: Path):
    """The workflow's own steps: encrypt in `job_from`, the artifact (a copy here), decrypt and pick in `job_to`. Returns the account file job_to starts from."""
    a, b = dst_root / "a", dst_root / "b"
    (a / "runtime/paper/ledger").mkdir(parents=True)
    shutil.copy(src, a / "runtime/paper/ledger/account.json")
    r = sh(step(job_from, "Hand this part's own account")["run"], a)
    assert r.returncode == 0, r.stderr
    enc = a / "handover-out/account.json.enc"
    assert enc.exists() and b"ledger" not in enc.read_bytes() and NAME.encode() not in enc.read_bytes()      # ciphertext only: nothing of the account readable
    (b / f"handover/paper-handover-{job_from}").mkdir(parents=True)
    shutil.copy(enc, b / f"handover/paper-handover-{job_from}/account.json.enc")
    for name in ("Decrypt the hand-overs", "Start from the longest verified copy"):
        r = sh(step(job_to, name)["run"], b)
        assert r.returncode == 0, (name, r.stdout, r.stderr)
    return b / "runtime/paper/ledger/account.json"


@needs_openssl
def test_a_fill_the_relay_never_took_reaches_the_next_part(cfg, tmp_path):
    """The audit's test_fill_lost_at_handover, inverted: part 2 restores every ledger row part 1 wrote when the relay refused saves after the opening."""
    clk = Clock()
    rl = RefusingRelay(clk)
    rl.add()
    disk1 = tmp_path / "p1" / "account.json"
    code = part(cfg, rl, clk, disk1, new=True)
    on_disk, on_relay = R.load_account(disk1.read_text()), R.load_account(rl.state["account"])
    assert code == S.EXIT_UNSAVED and NAME in on_disk.positions and NAME not in on_relay.positions        # the failure itself: still red, so it is seen
    start = hand_over("morning", "afternoon", disk1, tmp_path / "h")
    nxt = S.restore(cfg, rl, start, say=lambda *a: None, sleep=lambda s: None)
    assert NAME in nxt.positions and nxt.ledger == on_disk.ledger                                          # was: 0 rows and no position
    rl2 = FakeRelay(clk)                                                                                    # the afternoon: the relay takes saves again
    rl2.state, rl2.orders = dict(rl.state), list(rl.orders)                                                 # the filled order is still queued (its result was never posted)
    disk2 = tmp_path / "p2" / "account.json"
    cp(start, disk2)
    assert part(cfg, rl2, clk, disk2) == 0
    assert [r["status"] for r in rl2.results] == ["done"]                                                   # was: "expired", a false record of a filled order
    assert R.load_account(rl2.state["account"]).ledger == on_disk.ledger                                    # and the relay now holds the whole history


@needs_openssl
def test_a_sale_the_relay_never_took_does_not_bring_the_position_back(cfg, tmp_path):
    clk = Clock()
    rl = FakeRelay(clk)
    rl.add()
    d1 = tmp_path / "p1" / "account.json"
    part(cfg, rl, clk, d1, new=True)                                                                         # bought, and the relay has it
    rl2 = RefusingRelay(clk, take=0)
    rl2.state = dict(rl.state)
    rl2.add("ord-0002", side="sell", lots="all", strategy=None, thesis=None)
    d2 = tmp_path / "p2" / "account.json"
    cp(d1, d2)
    part(cfg, rl2, clk, d2)                                                                                  # sold, and the relay never hears of it
    assert NAME not in R.load_account(d2.read_text()).positions and NAME in R.load_account(rl2.state["account"]).positions
    nxt = S.restore(cfg, rl2, hand_over("afternoon", "evening", d2, tmp_path / "h"), say=lambda *a: None, sleep=lambda s: None)
    assert NAME not in nxt.positions                                                                         # was: the sold position back, to be sold again


@needs_openssl
def test_the_high_water_mark_reached_while_saves_failed_survives_the_hand_over(cfg, tmp_path):
    clk = Clock()
    rl = FakeRelay(clk)
    rl.add()
    d1 = tmp_path / "p1" / "account.json"
    part(cfg, rl, clk, d1, minutes=1, new=True)
    rl2 = RefusingRelay(clk, take=0)
    rl2.state = dict(rl.state)
    rl2.q = {NAME: dict(bid=300.0, ask=301.0, bid_qty=5000, ask_qty=5000, ltp=300, age_s=1.0)}             # the option triples: hwm rises, no new ledger row
    d2 = tmp_path / "p2" / "account.json"
    cp(d1, d2)
    part(cfg, rl2, clk, d2, minutes=1)
    disk, relay = R.load_account(d2.read_text()), R.load_account(rl2.state["account"])
    assert disk.hwm > relay.hwm + 10_000
    nxt = S.restore(cfg, rl2, hand_over("evening", "night", d2, tmp_path / "h"), say=lambda *a: None, sleep=lambda s: None)
    assert nxt.hwm == disk.hwm                                                                               # was: the relay's lower mark, a looser drawdown floor


@needs_openssl
def test_the_morning_takes_the_previous_runs_night_hand_over(cfg, tmp_path):
    clk = Clock()
    rl = RefusingRelay(clk)
    rl.add()
    d1 = tmp_path / "p1" / "account.json"
    part(cfg, rl, clk, d1, new=True)
    a, b = tmp_path / "a", tmp_path / "b"
    (a / "runtime/paper/ledger").mkdir(parents=True)
    shutil.copy(d1, a / "runtime/paper/ledger/account.json")
    assert sh(step("night", "Hand this part's own account")["run"], a).returncode == 0
    (b / "handover-prev/paper-handover-night").mkdir(parents=True)                                          # where gh run download puts the previous run's artifact
    shutil.copy(a / "handover-out/account.json.enc", b / "handover-prev/paper-handover-night/account.json.enc")
    for name in ("Decrypt the hand-overs", "Start from the longest verified copy"):
        assert sh(step("morning", name)["run"], b).returncode == 0
    nxt = S.restore(cfg, rl, b / "runtime/paper/ledger/account.json", say=lambda *a: None, sleep=lambda s: None)
    assert NAME in nxt.positions


@needs_openssl
def test_without_a_key_nothing_is_handed_over_and_the_part_starts_as_before(cfg, tmp_path):
    a = tmp_path / "a"
    (a / "runtime/paper/ledger").mkdir(parents=True)
    Account(500_000).save(a / "runtime/paper/ledger/account.json")
    r = sh(step("morning", "Hand this part's own account")["run"], a, key="short")
    assert r.returncode == 0 and "::warning::" in r.stdout and not (a / "handover-out").exists()            # never a plain or weakly keyed copy
    r = sh(step("afternoon", "Decrypt the hand-overs")["run"], a, key="")
    assert r.returncode == 0 and "::warning::" in r.stdout


@needs_openssl
def test_a_hand_over_under_another_key_or_damaged_is_left_out_and_said(cfg, tmp_path):
    a = tmp_path / "a"
    (a / "runtime/paper/ledger").mkdir(parents=True)
    Account(500_000).save(a / "runtime/paper/ledger/account.json")
    assert sh(step("morning", "Hand this part's own account")["run"], a, key="x" * 40).returncode == 0
    (a / "handover/paper-handover-morning").mkdir(parents=True)
    shutil.copy(a / "handover-out/account.json.enc", a / "handover/paper-handover-morning/account.json.enc")
    r = sh(step("afternoon", "Decrypt the hand-overs")["run"], a)                                           # a different key
    assert r.returncode == 0 and "could not be decrypted" in r.stdout and not list((a / "handover-dec").glob("*.json"))


# ---- the pick ------------------------------------------------------------------------------------------------------------------------------
def acct_with(cfg, tmp_path, n_orders, name):
    clk = Clock()
    rl = FakeRelay(clk)
    for i in range(n_orders):
        rl.add(f"ord-{i + 1:04d}", symbol=NAME)
    d = tmp_path / name / "account.json"
    part(cfg, rl, clk, d, minutes=1, new=True)
    return d


def pick(files, out, branch=None):
    C.cmd_pick(None, type("A", (), {"files": [str(f) for f in files], "out": str(out), "branch": str(branch) if branch else None}))


def test_the_pick_keeps_the_longest_history_and_the_highest_mark(cfg, tmp_path, capsys):
    short = Account(500_000)
    short_f = tmp_path / "short.json"
    short.save(short_f)
    long_f = acct_with(cfg, tmp_path, 1, "long")
    longer = R.load_account(long_f.read_text())
    short_d = json.loads(short_f.read_text())
    short_d["hwm"] = 600_000.0                                                                               # an older copy that saw a higher mark: the mark only ever rises
    short_f.write_text(json.dumps(short_d))
    out = tmp_path / "out.json"
    pick([short_f, long_f, tmp_path / "missing.json"], out)
    got = R.load_account(out.read_text())
    assert got.ledger == longer.ledger and got.hwm == 600_000.0
    assert "2 copies verified" in capsys.readouterr().out
    out2 = tmp_path / "out2.json"
    pick([long_f, short_f], out2)                                                                            # the order does not decide which history wins
    assert R.load_account(out2.read_text()).ledger == longer.ledger


def test_two_different_histories_stop_the_start_and_nothing_is_written(cfg, tmp_path, capsys):
    a = acct_with(cfg, tmp_path, 1, "a")
    other = Account(500_000)
    other.ledger = []
    b = tmp_path / "b.json"
    d = R.load_account(a.read_text()).to_dict()
    d2 = Account(400_000).to_dict()                                                                          # another account altogether
    b.write_text(json.dumps(d2))
    out = tmp_path / "out.json"
    with pytest.raises(SystemExit) as e:
        pick([a, b], out)
    assert e.value.code == 1 and not out.exists() and "two different histories" in capsys.readouterr().out
    assert d                                                                                                 # (a is untouched)


def test_a_copy_that_does_not_verify_is_left_out_and_said_and_no_copy_writes_nothing(cfg, tmp_path, capsys):
    good = acct_with(cfg, tmp_path, 1, "g")
    bad = tmp_path / "bad.json"
    d = json.loads(good.read_text())
    d["cash"] = d["cash"] + 1                                                                                # tampered: the replay does not match
    bad.write_text(json.dumps(d))
    junk = tmp_path / "junk.json"
    junk.write_bytes(b"\x00\xff not json")
    out = tmp_path / "out.json"
    pick([bad, junk, good], out)
    printed = capsys.readouterr().out
    assert R.load_account(out.read_text()).ledger == R.load_account(good.read_text()).ledger and printed.count("does not verify") == 2
    out2 = tmp_path / "none.json"
    pick([bad, tmp_path / "missing.json"], out2)
    assert not out2.exists() and "no usable copy" in capsys.readouterr().out


def test_the_pick_prints_counts_only(cfg, tmp_path, capsys):
    """The run logs are public: no price, position, cash or P&L."""
    f = acct_with(cfg, tmp_path, 1, "p")
    pick([f], tmp_path / "o.json")
    printed = capsys.readouterr().out
    assert NAME not in printed and "cash" not in printed and "100.0" not in printed


# ---- the risk review's findings (K-01, review of 1256c79) ---------------------------------------------------------------------------------
@needs_openssl
def test_a_part_that_never_started_hands_nothing_over_again(cfg, tmp_path):
    """Finding 1: a conflict stopped the part, and its always() step handed the conflicting copy on again, so every later part and morning stayed blocked."""
    b = tmp_path / "b"
    (b / "ledger").mkdir(parents=True)
    Account(500_000).save(b / "ledger/account.json")
    assert sh(step("afternoon", "Start from the longest verified copy")["run"], b).returncode == 0
    r = sh(step("afternoon", "Hand this part's own account")["run"], b)                                      # the runner refused: the file is as the pick left it
    assert r.returncode == 0 and "not handed over again" in r.stdout and not (b / "handover-out").exists()
    import time
    time.sleep(0.05)
    Account(500_000).save(b / "runtime/paper/ledger/account.json")                                           # a part that started saves its account at once
    assert sh(step("afternoon", "Hand this part's own account")["run"], b).returncode == 0 and (b / "handover-out/account.json.enc").exists()


def test_the_ledger_branchs_copy_must_verify_or_nothing_starts_as_before(cfg, tmp_path, capsys):
    """Finding 3: a tampered ledger-branch copy stopped the start before this change; it still does. A hand-over that does not verify is only left out."""
    good = acct_with(cfg, tmp_path, 1, "g")
    bad = tmp_path / "branch.json"
    d = json.loads(good.read_text())
    d["cash"] = d["cash"] + 1
    bad.write_text(json.dumps(d))
    out = tmp_path / "out.json"
    with pytest.raises(SystemExit) as e:
        pick([good], out, branch=bad)
    assert e.value.code == 1 and not out.exists() and "ledger branch's account does not verify" in capsys.readouterr().out
    pick([bad, good], out, branch=tmp_path / "no-branch-yet.json")                                           # no branch yet: not an error; a bad hand-over is left out
    assert R.load_account(out.read_text()).ledger == R.load_account(good.read_text()).ledger


def test_a_copy_of_the_wrong_shape_is_left_out_not_a_crash(cfg, tmp_path, capsys):
    good = acct_with(cfg, tmp_path, 1, "g")
    odd = [tmp_path / f"odd{i}.json" for i in range(3)]
    odd[0].write_text("[]")
    odd[1].write_text('{"v": 1}')
    odd[2].write_text('{"capital0": "x", "ledger": 5}')
    out = tmp_path / "out.json"
    pick(odd + [good], out)
    assert R.load_account(out.read_text()).ledger == R.load_account(good.read_text()).ledger and "left out" in capsys.readouterr().out


def test_the_morning_skips_a_previous_run_with_no_hand_over():
    """Finding 2: the newest completed run may have been cancelled before it ran: the one before it is taken."""
    prev = step("morning", "Fetch the previous run's hand-overs")["run"]
    assert "for prev in $runs" in prev and "break" in prev and "--limit 10" in prev
