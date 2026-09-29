"""Live news: parsing real feed shapes, reading headlines the way the market reads them, and
feeding the analyst without ever showing it a story before it was published."""
import json

import pandas as pd
import pytest

from quantdesk.intraday.engine import IntradayEngine, run_replay
from quantdesk.intraday.feeds import ReplayFeed
from quantdesk.intraday.news import NewsDesk, impact, parse_feed, sentiment
from quantdesk.intraday.sim import IntradayBroker
from quantdesk.intraday.synthetic import simulate_sessions
from quantdesk.journal.journal import Journal

IST = "Asia/Kolkata"


def rss(items):
    body = "".join(f"<item><title>{t}</title><link>https://x.test/{i}</link><pubDate>{d}</pubDate>"
                   f"<description>&lt;p&gt;{t}&lt;/p&gt;</description></item>" for i, (t, d) in enumerate(items))
    return f'<?xml version="1.0"?><rss version="2.0"><channel><title>x</title>{body}</channel></rss>'


def rfc(ts):
    return pd.Timestamp(ts, tz=IST).strftime("%a, %d %b %Y %H:%M:%S +0530")


@pytest.mark.parametrize("title,sign", [
    ("Nifty hits record high as FIIs turn buyers", 1), ("Sensex tumbles 800 points on global selloff", -1),
    ("Crude oil prices surge 4% on Middle East tensions", -1), ("Inflation eases to 3.1% in August", 1),
    ("Rupee falls to record low against dollar", -1), ("Bank Nifty snaps 3-day losing streak", 1),
    ("US Treasury yields rise as Fed signals higher for longer", -1), ("RBI cuts repo rate by 25 bps", 1),
    ("Fed raises interest rates by 25 basis points", -1), ("FPIs turn net sellers, pull out Rs 12,000 crore", -1),
    ("India VIX jumps 12% as markets turn volatile", -1), ("Oil prices rise on supply cuts", -1),
    ("Markets fall despite strong GDP data", -1), ("RBI keeps repo rate unchanged", 0),
])
def test_headline_tone_reads_like_the_market(title, sign):
    v = sentiment(title)
    assert (abs(v) < 0.35) if sign == 0 else (v * sign > 0.2), (title, v)


def test_impact_levels():
    assert impact("RBI keeps repo rate unchanged, maintains stance") == "high"
    assert impact("Rupee slips 10 paise") == "medium"
    assert impact("Five stocks to watch today") == "low"
    # whole words: "war" is not in "toward", "forward", "award" or "software"
    assert impact("Rupee slips toward 96 vs US dollar as crude, yields and stocks weigh") == "medium"
    assert impact("Infosys wins software award; forward guidance steady") != "high"
    assert impact("Markets slump as war fears grip investors") == "high"
    assert impact("Union Budget 2027: what changes for markets") == "high"


def test_parse_rss_atom_and_google_news():
    now = pd.Timestamp("2026-09-29 11:00", tz=IST)
    items = parse_feed(rss([("Nifty extends gains for fifth session - Mint", rfc("2026-09-29 10:40")),
                            ("Sensex, Nifty fall on selloff", "Tue, 29 Sep 2026 05:00:00 GMT")]), "Google News India", now)
    assert [i.title for i in items] == ["Nifty extends gains for fifth session", "Sensex, Nifty fall on selloff"]
    assert items[0].source == "Mint (via Google News)" and items[0].ts == pd.Timestamp("2026-09-29 10:40", tz=IST)
    assert items[1].ts == pd.Timestamp("2026-09-29 10:30", tz=IST)              # GMT converted to IST
    assert items[0].about["NIFTY"] >= 2 and items[0].sentiment > 0 and items[1].sentiment < 0
    atom = ('<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>RBI cuts repo rate</title>'
            '<link href="https://rbi.test/1"/><updated>2026-09-29T10:00:00+05:30</updated></entry></feed>')
    a = parse_feed(atom, "RBI", now)
    assert a[0].link == "https://rbi.test/1" and a[0].impact == "high" and a[0].sentiment > 0
    assert parse_feed("<not xml", "x", now) == []


def test_newsdesk_dedupes_weights_and_stands_aside(cfg):
    feeds = {
        "a": rss([("Nifty hits record high as FIIs turn buyers", rfc("2026-09-29 10:00")),
                  ("RBI cuts repo rate by 25 bps in surprise move", rfc("2026-09-29 11:05")),
                  ("Nifty 50 opens flat ahead of RBI policy", rfc("2026-09-29 09:10"))]),
        "b": rss([("Nifty hits a record high as FIIs turn buyers", rfc("2026-09-29 10:02")),        # same story, second outlet
                  ("Sensex tumbles on global selloff", rfc("2026-09-29 13:00"))]),                  # not published yet at 11:10
    }
    nd = NewsDesk(cfg, fetch=lambda url: feeds[url], sources=[{"name": "A", "url": "a"}, {"name": "B", "url": "b"}])
    t = pd.Timestamp("2026-09-29 11:10", tz=IST)
    fresh = nd.refresh(t)
    titles = [x.title for x in fresh]
    assert len(titles) == 3 and not any("tumbles" in x for x in titles)                  # deduped; nothing from the future
    rec = next(x for x in fresh if "record high" in x.title)
    assert set(rec.sources) == {"A", "B"}
    st = nd.state("NIFTY", t)
    assert st["tone"] > 0.3 and st["n"] == 3
    assert st["breaking"] and "RBI cuts" in st["breaking"]["title"]                   # 5 min old, high impact
    assert nd.state("NIFTY", t + pd.Timedelta(minutes=20))["breaking"] is None         # stand-aside is time-limited
    nd2 = NewsDesk(cfg, fetch=lambda url: rss([("Nifty 50 opens flat ahead of RBI policy", rfc("2026-09-29 09:10"))]),
                   sources=[{"name": "A", "url": "a"}])
    nd2.refresh(pd.Timestamp("2026-09-29 09:15", tz=IST))
    assert nd2.state("NIFTY", pd.Timestamp("2026-09-29 09:15", tz=IST))["breaking"] is None   # a preview isn't the event
    assert nd.refresh(t) == []                                                          # rate-limited to refresh_min
    nd.sources.append({"name": "dead", "url": "dead"})
    nd.fetch = lambda url: feeds[url] if url in feeds else (_ for _ in ()).throw(ConnectionError("403"))
    nd.refresh(t + pd.Timedelta(hours=3))
    assert nd.health["dead"].startswith("fail") and nd.health["A"].startswith("ok")
    assert any("tumbles" in x.title for x in nd.items.values())                          # now it has been published


def test_engine_reads_news_without_look_ahead(cfg, tmp_path):
    from quantdesk.core.calendar import TradingCalendar
    cal = TradingCalendar(cfg.holidays())
    days = [d.date() for d in cal.trading_days("2026-09-01", "2026-09-28")]
    bars, _ = simulate_sessions(days, seed=9)
    d = days[-1]
    feed_xml = rss([("Nifty surges to record high as FIIs turn buyers", rfc(f"{d} 10:00")),
                    ("RBI cuts repo rate by 50 bps in emergency move", rfc(f"{d} 12:00"))])
    j = Journal(tmp_path / "journal.db")
    nd = NewsDesk(cfg, fetch=lambda url: feed_xml, sources=[{"name": "T", "url": "t"}])
    eng = IntradayEngine(cfg, ReplayFeed(bars, d), "model", j, IntradayBroker(cfg, starting_cash=20000), say=None, news=nd)
    run_replay(eng)
    th = j.thoughts(str(d), "NIFTY")
    ts = pd.to_datetime(th["ts"])
    ev = th["evidence"].map(lambda e: [x["factor"] for x in json.loads(e)])
    assert not ev[ts < pd.Timestamp(f"{d} 10:00", tz=IST)].map(lambda f: "news" in f).any()     # nothing before it was published
    assert ev[(ts > pd.Timestamp(f"{d} 10:10", tz=IST)) & (ts < pd.Timestamp(f"{d} 12:00", tz=IST))].map(lambda f: "news" in f).all()
    veto = th["vetoes"].map(lambda v: any("breaking news" in x for x in json.loads(v)))
    assert veto[(ts >= pd.Timestamp(f"{d} 12:05", tz=IST)) & (ts <= pd.Timestamp(f"{d} 12:14", tz=IST))].all()
    assert not veto[ts >= pd.Timestamp(f"{d} 12:30", tz=IST)].any()
    assert len(j.news()) == 2
    assert j.get_state("intraday_live")["views"]["NIFTY"]["news"] is None             # by the close both are > 2h old
