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
from quantdesk.engine.live import LiveRunner
from quantdesk.execution.broker import PaperBroker
from quantdesk.intraday.engine import IntradayEngine, run_replay
from quantdesk.intraday.feeds import ReplayFeed
from quantdesk.intraday.recorder import SessionRecorder
from quantdesk.intraday.sim import IntradayBroker
from quantdesk.intraday.synthetic import simulate_sessions
from quantdesk.journal.journal import Journal
from quantdesk.web.intraday_api import IntradayAPI
from quantdesk.web.server import DeskAPI, make_handler

TOKEN = "t0k3n-for-tests"


@pytest.fixture(scope="module")
def site(tmp_path_factory, market):
    from quantdesk.config import DEFAULT_CONFIG, Config
    tmp = tmp_path_factory.mktemp("site")
    cfg = Config.load(DEFAULT_CONFIG, overrides={"runtime": {"dir": str(tmp / "rt")}})
    cal = TradingCalendar(cfg.holidays())
    days = [d.date() for d in cal.trading_days("2026-09-01", "2026-09-28")]
    bars, _ = simulate_sessions(days, seed=3)
    base = cfg.runtime_dir / "intraday"
    j = Journal(base / "journal.db")
    br = IntradayBroker(cfg, starting_cash=500000, state_path=base / "broker.json")
    rec = SessionRecorder(base / "data")
    for d in days[-2:]:
        for s in ("NIFTY", "BANKNIFTY", "INDIAVIX"):
            rec.record_bars(s, bars[s][bars[s].index.date == d])
        run_replay(IntradayEngine(cfg, ReplayFeed(bars, d), "model", j, br, None, None, None, base / "reviews"))
    j.commit()
    runner = LiveRunner(cfg, broker=PaperBroker(cfg, state_path=tmp / "p.json"), journal_path=tmp / "d.db", provider=market[0])
    httpd = HTTPServer(("127.0.0.1", 0), make_handler(DeskAPI(cfg, runner), IntradayAPI(cfg), TOKEN))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_port}", cfg, bars, days
    httpd.shutdown()


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


def test_token_required_everywhere_but_the_manifest(site):
    base = site[0]
    assert call(base, "/api/i/accounts", token=None)[0] == 401
    assert call(base, "/api/i/accounts", token="wrong")[0] == 401
    code, body, _ = call(base, "/", token=None)
    assert code == 401 and b"access token" in body                         # the sign-in page
    assert call(base, "/manifest.webmanifest", token=None)[0] == 200
    code, _, headers = call(base, f"/?token={TOKEN}", token=None)
    assert code == 200 and "qd_token=" in headers.get("Set-Cookie", "") and "HttpOnly" in headers["Set-Cookie"]
    assert call(base, "/api/i/command", {"cmd": "pause"}, token=None)[0] == 401


def test_live_state_thoughts_trades_stats_reviews(site):
    base, cfg, bars, days = site
    code, st, _ = call(base, "/api/i/state")
    assert code == 200 and set(st["heartbeat"]["views"]) == {"NIFTY", "BANKNIFTY"}
    v = st["heartbeat"]["views"]["NIFTY"]
    assert v["narrative"] and v["evidence"] and {"factor", "direction", "observation"} <= set(v["evidence"][0])
    code, th, _ = call(base, "/api/i/thoughts?n=5&symbol=NIFTY")
    assert code == 200 and len(th) == 5 and all(t["symbol"] == "NIFTY" for t in th)
    older = call(base, f"/api/i/thoughts?n=5&before={th[-1]['id']}")[1]
    assert all(t["id"] < th[-1]["id"] for t in older)
    code, trades, _ = call(base, "/api/i/trades")
    assert code == 200
    if trades:
        code, t, _ = call(base, f"/api/i/trade?id={trades[0]['id']}")
        assert code == 200 and "Trigger:" in t["rationale"] and t["fills"]
    code, s, _ = call(base, "/api/i/stats")
    assert code == 200 and s["capital"] == cfg.get("intraday.capital")
    code, revs, _ = call(base, "/api/i/reviews")
    assert revs == [str(days[-1]), str(days[-2])]
    assert "session review" in call(base, f"/api/i/review?date={days[-1]}")[1]["markdown"]
    assert call(base, "/api/i/review?date=../../etc")[0] == 404


def test_chart_and_udf(site):
    base, _, _, days = site
    code, c, _ = call(base, "/api/i/chart?symbol=NIFTY&interval=5m")
    assert code == 200 and c["day"] == str(days[-1]) and c["sessions"] == [str(d) for d in days[-2:]]
    assert len(c["bars"]["t"]) == 150 and len(c["vwap"]) == 150 and c["today_bars"] == 375  # both sessions, 5m
    i = c["bars"]["t"].index(c["session_starts"][1])                        # VWAP restarts at the second open
    tp = (c["bars"]["h"][i] + c["bars"]["l"][i] + c["bars"]["c"][i]) / 3
    assert i == 75 and abs(c["vwap"][i] - tp) < 0.02 and abs(c["vwap"][i - 1] - tp) > 0.02
    lv = c["levels"]
    assert {"or_high", "or_low", "ib_high", "ib_low", "pdh", "pdl", "cpr_tc", "cpr_bc", "day_high", "day_low", "poc"} <= set(lv)
    assert lv["pdh"] == max(c["bars"]["h"][:75]) and lv["day_low"] == min(c["bars"]["l"][75:])
    assert lv["cpr_bc"] <= lv["cpr_tc"] and lv["or_low"] <= lv["or_high"]
    pr = c["profile"]                                                       # the session profile the chart draws
    assert pr["val"] <= pr["poc"] <= pr["vah"] and len(pr["prices"]) == len(pr["size"]) and max(pr["size"]) == 1.0
    code, u, _ = call(base, "/api/i/udf?symbol=NSE:INDEX:NIFTY&interval=15m&countback=10&to=2000000000")
    assert u["s"] == "ok" and len(u["t"]) == 10 and u["t"] == sorted(u["t"])


def test_phone_commands_reach_the_engine(site, tmp_path):
    base, cfg, bars, days = site
    assert call(base, "/api/i/command", {"cmd": "rm -rf"})[0] == 400
    assert call(base, "/api/i/command", {"cmd": "close"})[0] == 400                 # needs a trade id
    code, r, _ = call(base, "/api/i/command", {"cmd": "pause"})
    assert code == 200 and r["queued"]["cmd"] == "pause"
    assert call(base, "/api/i/state")[1]["paused"] is True
    # the engine picks the command up on its next step and stops taking entries
    base_dir = cfg.runtime_dir / "intraday"
    j = Journal(base_dir / "journal.db")
    eng = IntradayEngine(cfg, ReplayFeed(bars, days[-1]), "model", j, IntradayBroker(cfg, starting_cash=500000), None, None)
    eng.start_session(days[-1])
    for _ in range(90):
        eng.feed.advance()
        eng.step()
    assert eng.paused and not eng.open_trades
    th = j.thoughts(str(days[-1]))
    assert th["action"].str.contains("paused from the app").any()
    assert call(base, "/api/i/command", {"cmd": "resume"})[0] == 200
    eng.feed.advance()
    eng.step()
    assert not eng.paused
    assert j.events(level="WARN")["message"].str.contains("pause from the app").any()


def test_static_site_exports(site, tmp_path):
    """The one-file snapshot and the live-updating folder the GitHub Actions workflow publishes."""
    from quantdesk.web.export_site import export_site, publish_site
    _, cfg, _, days = site
    one = export_site(cfg, "live", tmp_path / "snap.html")
    html = one.read_text(encoding="utf-8")
    assert html.startswith("<title>QuantDesk</title>") and 'id="qd-data"' in html and "qdAnswer" in html
    assert "</script>" not in html[html.index('id="qd-data"'):html.index("window.QD_DEMO")].split("</script>", 1)[0]

    out = publish_site(cfg, "live", tmp_path / "site", sessions=2)
    names = {p.name for p in out.iterdir()}
    assert {"index.html", "app.js", "data.json", "manifest.webmanifest", "icon-192.png", "icon-512.png", "icon-maskable-512.png",
            "apple-touch-icon.png", ".nojekyll", "lightweight-charts.js", "sw.js", "fonts"} <= names
    # installable app: fonts ship with it, the service worker's cache is named after this app version
    assert {"geist-sans.woff2", "geist-mono.woff2", "LICENSE-Geist.txt"} <= {p.name for p in (out / "fonts").iterdir()}
    sw = (out / "sw.js").read_text()
    assert "__QD_VERSION__" not in sw and re.search(r'const CACHE = "qd-[0-9a-f]{12}"', sw)
    assert "window.QD_NOTE=" in (out / "index.html").read_text()
    page = (out / "index.html").read_text(encoding="utf-8")
    assert "QD_PUBLISHED" in page and '<script src="app.js"></script>' in page and '<script src="lightweight-charts.js">' in page
    assert "TradingView Lightweight Charts" in html                             # the snapshot inlines the chart library
    assert 'href="/' not in page and "/static/" not in page                     # works under /<repo>/ on Pages
    man = json.loads((out / "manifest.webmanifest").read_text())
    assert man["start_url"] == "./" and not any(i["src"].startswith("/") for i in man["icons"])
    assert any(i.get("purpose") == "maskable" for i in man["icons"]) and all(sc["url"].startswith("./#") for sc in man["shortcuts"])
    data = json.loads((out / "data.json").read_text())
    assert data["live"] is True and data["short"] == "Live paper"
    # nothing time-stamped at export time: an idle desk re-exports byte-identical data (no needless re-deploys)
    publish_site(cfg, "live", tmp_path / "site2", sessions=2)
    assert (tmp_path / "site2" / "data.json").read_bytes() == (out / "data.json").read_bytes()
    assert data["state"]["heartbeat"]["ts"] and set(data["reviews"]) == {str(days[-1]), str(days[-2])}
    assert {t["ts"][:10] for t in data["thoughts"]} == {str(days[-1]), str(days[-2])}
    assert set(data["chart"]) == {f"{s}{k}|{iv}" for s in ("NIFTY", "BANKNIFTY") for k in ("", "-FUT") for iv in ("1m", "5m", "15m")}
    assert all(tid in data["trade"] for tid in [t["id"] for t in data["trades"]][:150])
    assert not (out / "data.json.tmp").exists()
    assert data["state"]["limits"]["max_trades_per_day"] == cfg.get("intraday.risk.max_trades_per_day")
    assert (tmp_path / "site2" / "sw.js").read_bytes() == (out / "sw.js").read_bytes()   # stable across re-publishes
    assert "data:font/woff2;base64," in html                                     # the snapshot carries its fonts
    # the host pads a snapshot for phone safe areas: the app bar's own padding must be patched out (index.html's CSS)
    assert ".bar{position:sticky;top:env(safe-area-inset-top,0px);" in html and "min-height:52px;\npadding:0 4px 0 16px;" in html


def test_chart_library_is_served(site):
    """The phone app's chart engine (TradingView Lightweight Charts, vendored) loads from the desk itself."""
    base = site[0]
    code, page, _ = call(base, "/")
    assert code == 200 and b"/static/vendor/lightweight-charts.js" in page
    code, lib, headers = call(base, "/static/vendor/lightweight-charts.js")
    assert code == 200 and b"TradingView Lightweight Charts" in lib[:400] and "javascript" in headers.get("Content-Type", "")



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
