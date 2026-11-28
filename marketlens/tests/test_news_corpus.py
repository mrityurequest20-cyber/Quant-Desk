"""News P1 corpus: parsing NSE filings and Google News, dedup, resumable windows, the time budget."""
import datetime as dt

import pandas as pd

from marketlens.news import corpus as C

NSE_ROWS = [
    {"symbol": "RELIANCE", "desc": "Outcome of Board Meeting", "sort_date": "2023-01-06 18:22:24", "seq_id": "1",
     "attchmntText": "Board approved  results for the quarter &amp; a dividend", "attchmntFile": "https://x/1.pdf"},
    {"symbol": "DMCC", "desc": "Loss of Share Certificates", "sort_date": "2023-01-06 23:27:13", "seq_id": "2"},
    {"symbol": "ITI", "desc": "Investor Presentation", "an_dt": "07-Jan-2019 22:21:00", "seq_id": "3"},
    {"symbol": "", "desc": "Updates", "sort_date": "2023-01-06 10:00:00"},
]

RSS = """<rss><channel><title>Google News</title>
<item><title>Reliance buys John Players - Moneycontrol.com</title><link>https://news.google.com/a</link>
<pubDate>Wed, 06 Mar 2019 08:00:00 GMT</pubDate><source url="https://moneycontrol.com">Moneycontrol.com</source></item>
<item><title><![CDATA[RBI cuts repo by 75 bps &amp; more - The Times of India]]></title><link>https://news.google.com/b</link>
<pubDate>Fri, 27 Mar 2020 05:42:10 GMT</pubDate><source url="https://toi.in">The Times of India</source></item>
<item><title>No date</title></item>
</channel></rss>"""


def test_nse_filings_parse_drop_routine_and_keep_exact_ist_times():
    df = C.parse_nse(NSE_ROWS)
    assert list(df["symbol"]) == ["RELIANCE", "ITI"]
    r = df.iloc[0]
    assert r.ts == pd.Timestamp("2023-01-06 12:52:24", tz="UTC") and r.ts_quality == "exact"      # 18:22:24 IST
    assert r.summary == "Board approved results for the quarter & a dividend"
    assert df.iloc[1].ts == pd.Timestamp("2019-01-07 16:51:00", tz="UTC")                             # 22:21 IST, day-first


def test_gnews_parse_strips_publisher_and_marks_round_hour_stamps_as_day_only():
    df = C.parse_gnews(RSS, "RELIANCE", '"Reliance Industries"')
    assert list(df["title"]) == ["Reliance buys John Players", "RBI cuts repo by 75 bps & more"]
    assert list(df["publisher"]) == ["Moneycontrol.com", "The Times of India"]
    assert list(df["ts_quality"]) == ["day", "exact"]


def test_corpus_dedups_by_id_and_files_by_source_and_year(tmp_path):
    c = C.Corpus(tmp_path)
    df = C.parse_gnews(RSS, "RELIANCE", "q")
    assert c.add(df) == 2 and c.add(df) == 0
    assert sorted(p.name for p in tmp_path.glob("*.parquet")) == ["news_gnews_2019.parquet", "news_gnews_2020.parquet"]
    assert len(c.read("gnews")) == 2


class FakeNSE:
    def __init__(self):
        self.calls = []

    def api(self, path):
        self.calls.append(path)
        return NSE_ROWS, b"", path


class FakeSession:
    def __init__(self, n=3):
        self.calls, self.n = [], n

    def get(self, url, **kw):
        self.calls.append(url)
        n = self.n

        class R:
            text = "<rss>" + "".join(f"<item><title>Story {len(self.calls)}-{i} - Pub</title><pubDate>Wed, 06 Mar 2019 0{i % 9}:1{i % 6}:00 GMT</pubDate>"
                                     f"<source>Pub</source></item>" for i in range(n)) + "</rss>"

            def raise_for_status(self):
                pass
        return R()


def test_collect_is_resumable_and_skips_done_windows(tmp_path):
    c, nse = C.Corpus(tmp_path), FakeNSE()
    a, b = dt.date(2023, 1, 2), dt.date(2023, 1, 5)
    C.collect(c, a, b, sources=("nse",), nse=nse, sleep=lambda s: None, say=lambda *x: None)
    assert len(nse.calls) == 3 and "from_date=02-01-2023&to_date=02-01-2023" in nse.calls[0]
    C.collect(C.Corpus(tmp_path), a, b, sources=("nse",), nse=nse, sleep=lambda s: None, say=lambda *x: None)
    assert len(nse.calls) == 3                                                   # all three days were marked done


def test_gnews_splits_a_capped_window_and_stops_at_the_time_budget(tmp_path, monkeypatch):
    monkeypatch.setattr(C, "queries", lambda: {"NIFTY": '"Nifty"'})
    s = FakeSession(n=100)
    C.collect(C.Corpus(tmp_path), dt.date(2019, 3, 1), dt.date(2019, 4, 1), sources=("gnews",), session=s,
              sleep=lambda x: None, say=lambda *x: None)
    assert len(s.calls) > 1 and "after%3A2019-03-01" in s.calls[0]
    t = iter([0, 0, 10 ** 9])
    s2 = FakeSession()
    out = C.collect(C.Corpus(tmp_path / "b"), dt.date(2019, 3, 1), dt.date(2019, 6, 1), sources=("gnews",), session=s2,
                    sleep=lambda x: None, say=lambda *x: None, clock=lambda: next(t, 10 ** 9), budget_s=5)
    assert out["windows"] == 1


def test_queries_cover_every_instrument_and_the_macro_channels():
    q = C.queries()
    for s in ("NIFTY", "BANKNIFTY", "INDIAVIX", "RELIANCE", "M&M", "PAYTM", "MACRO:RBI", "MACRO:CRUDE"):
        assert s in q
    assert q["RELIANCE"] == '"Reliance Industries"' and "Paytm" in q["PAYTM"]
