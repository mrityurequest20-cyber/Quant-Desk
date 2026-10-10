import datetime as dt

from quantdesk.core.calendar import TradingCalendar, year_fraction


def test_trading_days_skip_weekends_and_holidays(cfg):
    cal = TradingCalendar(cfg.holidays())
    assert not cal.is_trading_day(dt.date(2026, 1, 26))        # Republic Day (Mon)
    assert not cal.is_trading_day(dt.date(2026, 9, 27))        # Sunday
    assert cal.next_trading_day(dt.date(2026, 1, 23)) == dt.date(2026, 1, 27)
    assert cal.prev_trading_day(dt.date(2026, 1, 27)) == dt.date(2026, 1, 23)


def test_weekly_expiry_is_tuesday_and_shifts_before_holidays(cfg):
    cal = TradingCalendar(cfg.holidays())
    exps = cal.expiries(dt.date(2026, 2, 20), 30)
    assert dt.date(2026, 2, 24) in exps                         # plain Tuesday
    assert dt.date(2026, 3, 2) in exps                          # Tue 3-Mar is Holi → Mon 2-Mar
    assert dt.date(2026, 3, 3) not in exps
    assert all(e.weekday() in (0, 1) for e in exps)


def test_monthly_expiry_last_tuesday(cfg):
    cal = TradingCalendar(cfg.holidays())
    assert cal.monthly_expiry(2026, 10) == dt.date(2026, 10, 27)
    assert cal.monthly_expiry(2026, 3) == dt.date(2026, 3, 30)  # last Tue 31-Mar is a holiday
    monthly_only = cal.expiries(dt.date(2026, 9, 1), 70, weekly=False)
    assert monthly_only == [dt.date(2026, 9, 29), dt.date(2026, 10, 27)]


def test_pick_expiry_respects_min_dte(cfg):
    cal = TradingCalendar(cfg.holidays())
    e = cal.pick_expiry(dt.date(2026, 9, 28), target_dte=14, min_dte=6)
    assert (e - dt.date(2026, 9, 28)).days >= 6
    assert e == dt.date(2026, 10, 13)


def test_year_fraction():
    assert year_fraction(dt.date(2026, 1, 1), dt.date(2026, 1, 1)) == 0
    assert abs(year_fraction(dt.date(2026, 1, 1), dt.date(2027, 1, 1)) - 1) < 1e-9


def test_a_year_without_its_holiday_list_halts_new_entries_and_sleeves(cfg, tmp_path):
    """F-07: the config lists 2026's NSE holidays only. In 2027 a holiday would look like a trading day (and an
    expiry would land on it), so until the list is added the desk opens nothing; self-review asks from 1 December."""
    from types import SimpleNamespace

    import pandas as pd

    from quantdesk.intraday.engine import IntradayEngine
    from quantdesk.intraday.feeds import ReplayFeed
    from quantdesk.intraday.sim import IntradayBroker
    from quantdesk.intraday.sleeves import ExpirySeller
    from quantdesk.intraday.synthetic import simulate_sessions
    from quantdesk.journal.journal import Journal
    from quantdesk.ops.selfreview import check_holidays

    assert cfg.holiday_years() == {2026}
    assert cfg.holiday_gap(dt.date(2026, 12, 31)) is None and cfg.holiday_gap(dt.date(2024, 5, 2)) is None
    assert "2027" in cfg.holiday_gap(dt.date(2027, 1, 4))
    bars, _ = simulate_sessions([dt.date(2026, 10, 5)], seed=3)
    eng = IntradayEngine(cfg, ReplayFeed(bars, dt.date(2026, 10, 5)), "model", Journal(),
                         IntradayBroker(cfg, starting_cash=500000), say=None)
    calm = SimpleNamespace(vetoes=[])
    halt = eng._blocked("NIFTY", calm, pd.Timestamp("2027-01-04 10:00", tz="Asia/Kolkata"))
    assert halt and halt.startswith("halted: no NSE holiday list for 2027")
    assert "holiday list" not in (eng._blocked("NIFTY", calm, pd.Timestamp("2026-10-05 10:00", tz="Asia/Kolkata")) or "")
    seller = ExpirySeller(cfg, tmp_path / "sleeves", tmp_path / "data", say=lambda *a: None)
    notes = seller.run(dt.date(2027, 1, 4), pd.Timestamp("2027-01-04 15:27", tz="Asia/Kolkata"))
    assert any(n.startswith("nothing opened: no NSE holiday list for 2027") for n in notes)
    assert not any(e["event"] == "open" for e in seller.events())
    for d in pd.bdate_range("2027-01-05", "2027-01-22"):                          # every halted day of January
        seller.run(d.date(), pd.Timestamp(f"{d.date()} 15:27", tz="Asia/Kolkata"))
    skips = [e for e in seller.events() if e["event"] == "skip"]
    assert skips and all(e["reason"].startswith("halted: no NSE holiday list for 2027") for e in skips)
    assert {e["day"] for e in skips} >= {"2027-01-04", "2027-01-11", "2027-01-18"}  # each Tuesday's eve is on the record
    resumed = ExpirySeller(cfg.with_overrides({"calendar": {"holiday_years": [2026, 2027]}}), tmp_path / "sleeves",
                           tmp_path / "data", say=lambda *a: None)
    resumed.run(dt.date(2027, 1, 25), pd.Timestamp("2027-01-25 15:27", tz="Asia/Kolkata"))
    assert not any("did not run" in e.get("reason", "") for e in resumed.events())   # never mis-recorded as not run
    # a holiday in the list once it's added moves an expiry onto an eve the halted calendar didn't name (Tue 26 Jan is
    # Republic Day: the expiry moves to Mon 25, its eve is Fri 22): that eve was halted too, not "not run"
    late = ExpirySeller(cfg, tmp_path / "late", tmp_path / "data", say=lambda *a: None)
    for d in pd.bdate_range("2027-01-18", "2027-01-29"):
        late.run(d.date(), pd.Timestamp(f"{d.date()} 15:27", tz="Asia/Kolkata"))
    added = cfg.with_overrides({"calendar": {"holiday_years": [2026, 2027],
                                             "holidays": cfg.get("calendar.holidays") + ["2027-01-26"]}})
    ExpirySeller(added, tmp_path / "late", tmp_path / "data", say=lambda *a: None).run(
        dt.date(2027, 2, 1), pd.Timestamp("2027-02-01 15:27", tz="Asia/Kolkata"))
    reasons = [e["reason"] for e in late.events() if e["event"] == "skip"]
    assert reasons and not any("did not run" in r for r in reasons) and any("halted on the eve (2027-01-22)" in r for r in reasons)
    assert [f.key for f in check_holidays(cfg, dt.date(2026, 11, 30))] == []
    assert [f.key for f in check_holidays(cfg, dt.date(2026, 12, 1))] == ["holiday-list:2027"]
    assert [f.key for f in check_holidays(cfg, dt.date(2027, 1, 4))] == ["holiday-list:2027"]
    added = cfg.with_overrides({"calendar": {"holiday_years": [2026, 2027]}})           # the owner adds 2027's list
    assert added.holiday_gap(dt.date(2027, 1, 4)) is None and check_holidays(added, dt.date(2026, 12, 1)) == []
