"""Audit K-06 (AIJ-05, FH-05; HIGH) and K-01's view/record split: one exception in the app's summary killed the part (AIJ-05); a cycle that failed every time left
every brake off for the whole part and the part stayed green (FH-05); and a refused summary kept the account off the relay (20 Nov). PAPER MONEY ONLY."""
from __future__ import annotations

import datetime as dt

from quantdesk.paper import runner as R
from quantdesk.paperlink import session as S
from quantdesk.paperlink.relay import RelayError
from tests.test_paper_session import IST, NAME, Clock, FakeRelay, cfg  # noqa: F401 - cfg is a fixture


def go(cfg, rl, clk, tmp_path, minutes=2, lines=None, auto=None):
    return S.run(cfg, rl, tmp_path / "ledger" / "account.json", (clk.t + dt.timedelta(minutes=minutes)).astimezone(IST).time(), every_s=3.0, clock=clk,
                 sleep=clk.sleep, say=(lines.append if lines is not None else (lambda *a: None)), new_account=True, auto=auto)


class BadLab:
    """AUTO whose lab summary raises a KeyError after its first call (the class AIJ-05 found unguarded: only three exception types were caught)."""
    def __init__(self):
        self.n = 0

    def decide(self, *a, **k):
        return []

    def drain_events(self):
        return []

    def summary(self):
        self.n += 1
        if self.n > 1:
            raise KeyError("why")
        return {}


def test_a_key_error_in_autos_summary_never_stops_the_runner_and_the_record_is_kept(cfg, tmp_path, monkeypatch):
    clk, lines = Clock(), []
    monkeypatch.setattr(S.time, "monotonic", lambda: (clk.t - Clock().t).total_seconds())     # the session's pacing follows the test clock (AIJ-16)
    rl = FakeRelay(clk)
    rl.add()
    code = go(cfg, rl, clk, tmp_path, lines=lines, auto=BadLab())
    assert code == 0 and NAME in R.load_account(rl.state["account"]).positions
    assert any("summary could not be built (KeyError)" in m for m in lines)


def test_a_cycle_that_fails_every_time_says_brakes_down_once_and_ends_the_part_red(cfg, tmp_path, monkeypatch):
    def broken(self, *a, **k):
        raise TypeError("a malformed position")
    monkeypatch.setattr(R.Runner, "step", broken)
    clk, lines = Clock(), []
    monkeypatch.setattr(S.time, "monotonic", lambda: (clk.t - Clock().t).total_seconds())
    rl = FakeRelay(clk)
    code = go(cfg, rl, clk, tmp_path, minutes=3, lines=lines)
    assert code == S.EXIT_BRAKES_DOWN                                                         # was 0: green with no brake running (FH-05)
    assert sum("::error::" in m and "brakes are not running" in m for m in lines) == 1        # once, not a line a cycle
    assert rl.state["summary"]["brakes_down"] is True and rl.state["summary"]["cycle_fails"] >= S.BRAKES_DOWN_AFTER


def test_a_cycle_that_recovers_resets_the_count_and_clears_brakes_down_but_the_part_still_ends_red(cfg, tmp_path, monkeypatch):
    real, n = R.Runner.step, {"i": 0}

    def flaky(self, *a, **k):
        n["i"] += 1
        if n["i"] <= S.BRAKES_DOWN_AFTER + 5:
            raise TypeError("transient")
        return real(self, *a, **k)
    monkeypatch.setattr(R.Runner, "step", flaky)
    clk = Clock()
    monkeypatch.setattr(S.time, "monotonic", lambda: (clk.t - Clock().t).total_seconds())
    rl = FakeRelay(clk)
    code = go(cfg, rl, clk, tmp_path, minutes=3)
    assert code == S.EXIT_BRAKES_DOWN                                                          # it happened, so the run is red...
    assert rl.state["summary"]["brakes_down"] is False and rl.state["summary"]["cycle_fails"] == 0   # ...but the state says the brakes run again


class ViewRefusing(FakeRelay):
    """Refuses a summary that carries the full view (as the Worker refused an over-size one on 20 Nov), and takes a minimal one."""
    def put_state(self, summary, account_text):
        if "positions" in summary:
            raise RelayError("POST /paper/state: HTTP 400")
        return super().put_state(summary, account_text)


def test_a_refused_view_never_keeps_a_fill_off_the_relay(cfg, tmp_path):
    clk = Clock()
    rl = ViewRefusing(clk)
    rl.add()
    code = go(cfg, rl, clk, tmp_path, minutes=1)
    assert code == 0 and NAME in R.load_account(rl.state["account"]).positions                # was: the fill stayed on the part's disk (K-01)
    assert rl.state["summary"]["degraded"] == "the full summary was refused" and [r["status"] for r in rl.results] == ["filled"]


def test_the_app_says_when_the_view_is_short_or_the_brakes_are_down_and_never_shows_zero_positions_for_a_short_view():
    from pathlib import Path
    app = (Path(__file__).resolve().parents[1] / "quantdesk/web/static/app/app.js").read_text(encoding="utf-8")
    assert "sm.degraded" in app and "The trade record itself is saved" in app
    assert "sm.brakes_down" in app and "the brakes are not running" in app
    assert 'sm.degraded ? "—" : String(pos.length)' in app



def test_a_summary_error_at_the_opening_or_the_last_save_never_ends_the_part(cfg, tmp_path, monkeypatch):
    """Risk review of K-06: AIJ-05 was still open at a part's first and last save. Every summary fails here, from the very first."""
    def broken(self, snap, now):
        raise KeyError("why")
    monkeypatch.setattr(R.Runner, "summary", broken)
    clk, lines = Clock(), []
    rl = FakeRelay(clk)
    rl.add()
    code = go(cfg, rl, clk, tmp_path, minutes=1, lines=lines)
    assert code == 0 and NAME in R.load_account(rl.state["account"]).positions
    s = rl.state["summary"]
    assert s["degraded"].startswith("summary failed (KeyError)") and s["halt"] is None and s["day_halted"] is False


def test_a_refused_full_summary_is_logged_once_with_its_reason(cfg, tmp_path):
    clk, lines = Clock(), []
    rl = ViewRefusing(clk)
    rl.add()
    go(cfg, rl, clk, tmp_path, minutes=1, lines=lines)
    assert sum("refused the full summary" in m and "HTTP 400" in m for m in lines) == 1
