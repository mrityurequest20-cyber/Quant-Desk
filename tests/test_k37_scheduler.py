"""Audit K-37 (FH-07): the scheduler took the first `holidays:` list in the config, the currency segment's (20 dates, NSE has 16), and refused every NSE holiday for
every workflow, so the MCX evening (which trades on an NSE holiday that is not an MCX full closure, from 17:00) never had its paper desk or Fyers feed."""
from __future__ import annotations

import datetime as dt
import importlib.util
from pathlib import Path

from quantdesk.config import Config

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("scheduler_k37", ROOT / "deploy" / "scheduler.py")
sch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sch)
CFG = ROOT / "config" / "quantdesk.yaml"
HOLS, MCX = sch.holidays(CFG), sch.mcx_closures(CFG)
at = lambda y, m, d, hh, mm: dt.datetime(y, m, d, hh, mm, tzinfo=sch.IST)          # noqa: E731


def test_the_holidays_are_nses_own_list_read_by_its_key():
    assert set(HOLS) == set(Config.load(CFG).holidays()) and len(HOLS) == 16
    assert dt.date(2026, 2, 19) not in HOLS                                               # a currency settlement holiday: NSE trades
    assert MCX == {dt.date(2026, 1, 26), dt.date(2026, 4, 3), dt.date(2026, 10, 2), dt.date(2026, 12, 25)}


def test_the_key_path_is_respected_whatever_comes_first():
    text = "a:\n  holidays:\n    - 2020-01-01\ncalendar:\n  x: 1\n  holidays:   # NSE\n    - 2026-11-24   # Guru Nanak\n    - 2026-12-25\n  after: 2\n"
    assert sch._dates_at(text, ("calendar", "holidays")) == {dt.date(2026, 11, 24), dt.date(2026, 12, 25)}
    assert sch._dates_at(text, ("a", "holidays")) == {dt.date(2020, 1, 1)} and sch._dates_at(text, ("b", "holidays")) == set()


def test_on_an_nse_holiday_the_mcx_evening_workflows_start_from_its_open_and_nothing_else_does():
    assert dt.date(2026, 11, 24) in HOLS and dt.date(2026, 11, 24) not in MCX
    assert sch.decide(at(2026, 11, 24, 17, 30), [], HOLS, 3, sch.PAPER_WINDOW, MCX)[0] == "start"
    assert sch.decide(at(2026, 11, 24, 17, 30), [], HOLS, 1, sch.FYERS_WINDOW, MCX)[0] == "start"
    assert sch.decide(at(2026, 11, 24, 10, 0), [], HOLS, 3, sch.PAPER_WINDOW, MCX)[0] == "wait"            # MCX's evening only
    assert sch.decide(at(2026, 11, 24, 17, 30), [], HOLS, 3, sch.WINDOW)[0] == "wait"                     # the NSE recorder: no session
    assert sch.decide(at(2026, 12, 25, 17, 30), [], HOLS, 3, sch.PAPER_WINDOW, MCX)[0] == "wait"          # an MCX full closure
    assert sch.decide(at(2026, 11, 28, 17, 30), [], HOLS, 3, sch.PAPER_WINDOW, MCX)[0] == "wait"          # a Saturday
    assert sch.decide(at(2026, 11, 23, 6, 0), [], HOLS, 3, sch.PAPER_WINDOW, MCX)[0] == "start"           # an ordinary day is unchanged
    assert sch.MCX_EVENING_WORKFLOWS == {"paper-desk.yml", "fyers-feed.yml"}


def test_only_the_keys_own_list_is_taken_not_a_deeper_one_or_one_after_it():
    nested = "calendar:\n  sub:\n    holidays:\n      - 2020-01-01\n  holidays:\n    - 2026-11-24\n"
    assert sch._dates_at(nested, ("calendar", "holidays")) == {dt.date(2026, 11, 24)}            # not sub.holidays
    same_indent = "calendar:\n  holidays:\n  - 2026-11-24\n  - 2026-12-25\n  x: 1\n"
    assert sch._dates_at(same_indent, ("calendar", "holidays")) == {dt.date(2026, 11, 24), dt.date(2026, 12, 25)}   # valid YAML
    after = "calendar:\n  holidays:\n    - 2026-11-24\n- 2020-01-01\n"
    assert sch._dates_at(after, ("calendar", "holidays")) == {dt.date(2026, 11, 24)}              # a less indented item is not its


def test_a_key_missing_from_its_parent_is_not_found_in_the_next_section():
    text = "calendar:\n  x: 1\nother:\n  holidays:\n    - 2020-01-01\n"
    assert sch._dates_at(text, ("calendar", "holidays")) == set()
