"""The mobile web app: token auth, the intraday API over a real engine's journal, and the
phone → engine remote-control round trip (pause / close / flatten)."""
import json
import re
import threading
import urllib.error
import urllib.request
from http.server import HTTPServer

import pandas as pd
import pytest

from quantdesk.core.calendar import TradingCalendar
from quantdesk.execution.broker import PaperBroker
from quantdesk.intraday.feeds import ReplayFeed
from quantdesk.intraday.recorder import SessionRecorder
from quantdesk.journal.journal import Journal
from quantdesk.web.intraday_api import IntradayAPI

TOKEN = "t0k3n-for-tests"


def call(base, path, body=None, token=TOKEN):
    req = urllib.request.Request(base + path, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"X-QD-Token": token} if token else {})
    try:
        with urllib.request.urlopen(req) as r:
            ct = r.headers.get("Content-Type", "")
            raw = r.read()
            return r.status, (json.loads(raw) if "json" in ct else raw), r.headers
    except urllib.error.HTTPError as e:
        return e.code, e.read(), e.headers


def test_a_stub_session_is_charted_with_the_day_before(tmp_path):
    """A desk that started late (30 Sep 2026: ten bars from 15:20) must not chart ten bars alone."""
    import numpy as np
    from quantdesk.web.intraday_api import IntradayAPI
    idx1 = pd.date_range("2026-09-29 09:15", "2026-09-29 15:29", freq="1min", tz="Asia/Kolkata")
    idx2 = pd.date_range("2026-09-30 15:20", "2026-09-30 15:29", freq="1min", tz="Asia/Kolkata")
    rec = SessionRecorder(tmp_path / "data")
    for idx, base in ((idx1, 22700.0), (idx2, 22617.0)):
        c = base + np.sin(np.arange(len(idx)) / 20) * 30
        rec.record_bars("NIFTY", pd.DataFrame({"open": c, "high": c + 3, "low": c - 3, "close": c, "volume": 0.0}, index=idx))
    api = IntradayAPI.__new__(IntradayAPI)
    api._data_dir = lambda account: tmp_path / "data"
    api.j = lambda account: Journal()
    ch = api.chart(None, "NIFTY", None, "5m")
    assert ch["day"] == "2026-09-30" and ch["today_bars"] == 10 and len(ch["bars"]["t"]) == 75 + 2
    assert ch["profile"]["day"] == "2026-09-29"                              # the stub's ten bars don't make a profile
    assert "or_high" not in ch["levels"] and {"pdh", "pdl", "day_high"} <= set(ch["levels"])   # no fake opening range


def test_an_open_trade_beside_a_closed_one_does_not_break_the_chart(tmp_path):
    """30 Oct 2026: right after the hand-over the afternoon desk published nothing for 30 minutes (five failed exports in a
    row, `NaTType does not support timestamp`) and the app said "Stale". pandas 3 returns a missing string as NaN, which is
    truthy, so an open trade's empty `closed_at` (or `meta`) was read as a time. An open trade is marked as an entry only."""
    import numpy as np
    from quantdesk.web.intraday_api import IntradayAPI
    idx = pd.date_range("2026-09-30 09:15", "2026-09-30 15:29", freq="1min", tz="Asia/Kolkata")
    c = 22700.0 + np.sin(np.arange(len(idx)) / 20) * 30
    rec = SessionRecorder(tmp_path / "data")
    rec.record_bars("NIFTY", pd.DataFrame({"open": c, "high": c + 3, "low": c - 3, "close": c, "volume": 0.0}, index=idx))
    j = Journal()
    j._exec("INSERT INTO trades (id, symbol, direction, strategy, status, pnl, opened_at, closed_at, exit_underlying, "
            "exit_reason, meta) VALUES ('c1', 'NIFTY', 1, 'orb', 'closed', 150.0, '2026-09-30 10:00', '2026-09-30 11:00', "
            "22710.0, 'target', '{}')")
    j._exec("INSERT INTO trades (id, symbol, direction, strategy, status, opened_at) "
            "VALUES ('o1', 'NIFTY', -1, 'trend_break', 'open', '2026-09-30 12:00')")        # no closed_at, no meta
    j._exec("INSERT INTO trades (id, symbol, direction, strategy, status, opened_at, meta) "
            "VALUES ('o2', 'NIFTY', 1, 'orb', 'open', '2026-09-30 13:00', '{}')")           # no closed_at only
    j.commit()
    api = IntradayAPI.__new__(IntradayAPI)
    api._data_dir = lambda account: tmp_path / "data"
    api.j = lambda account: j
    ch = api.chart(None, "NIFTY", None, "5m")
    assert sorted(m["kind"] for m in ch["markers"]) == ["entry", "entry", "entry", "exit"]
    assert [t["structure"] for t in api.trades(None)] == [None, None, None]         # the trade list reads the same columns


def test_an_account_that_has_not_traded_shows_the_new_capital(cfg):
    """4 Oct 2026: the account was set to ₹5,00,000 but the app kept showing ₹20,000 until the next session, because
    the journal's stored figure only changes when the engine starts. The app applies the engine's rule itself."""
    import json as _json
    from quantdesk.journal.journal import Journal
    from quantdesk.web.intraday_api import IntradayAPI
    base = cfg.runtime_dir / "intraday"
    base.mkdir(parents=True, exist_ok=True)
    j = Journal(base / "journal.db")
    j.set_state("intraday_account", {"capital": 20000.0, "since": "2026-10-03"})
    j.set_state("intraday_live", {"day": "2026-10-03", "equity": 20000.0})
    j.commit()
    (base / "broker.json").write_text(_json.dumps({"cash": 20000.0}))
    api = IntradayAPI(cfg)
    s = api.state()
    want = float(cfg.get("intraday.capital"))
    assert want != 20000 and s["capital"] == want and s["cash"] == want and s["equity"] == want and s["capital_pending"]
    j._exec("INSERT INTO trades (id, status, pnl, opened_at, closed_at) VALUES ('t1', 'closed', 150.0, "
            "'2026-10-03 10:00', '2026-10-03 11:00')")
    j.commit()
    s = IntradayAPI(cfg).state()                     # once it has traded, its own history stands
    assert s["capital"] == 20000 and s["cash"] == 20000 and not s["capital_pending"]
