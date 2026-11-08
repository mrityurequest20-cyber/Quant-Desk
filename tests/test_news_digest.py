"""The news digest (quantdesk/premarket/newsdigest.py): the desk's own news engine over fixture feeds, which instruments a headline names, link safety, and the push to the relay. No network."""
from __future__ import annotations

import io
import json
import urllib.error
from pathlib import Path

import pandas as pd
import pytest

from quantdesk.config import Config
from quantdesk.premarket import newsdigest as N

ROOT = Path(__file__).resolve().parents[1]
NOW = pd.Timestamp("2026-11-09 11:00", tz="Asia/Kolkata")


@pytest.fixture()
def cfg():
    return Config.load(ROOT / "config" / "quantdesk.yaml")


def rss(*items):
    body = "".join(f"<item><title>{t}</title><link>{l}</link><pubDate>{d}</pubDate></item>" for t, l, d in items)
    return f'<?xml version="1.0"?><rss version="2.0"><channel><title>x</title>{body}</channel></rss>'


def rfc(minutes_ago, hours=0):
    return (NOW - pd.Timedelta(minutes=minutes_ago, hours=hours)).tz_convert("UTC").strftime("%a, %d %b %Y %H:%M:%S +0000")


def test_every_symbol_the_desk_records_has_names_a_headline_would_use(cfg):
    cw = cfg.get("collect_wide")
    missing = [s for s in [*cw["indices"], *cw["stocks"], *cw["stocks_extra"]] if s not in N.ALIASES]
    assert missing == []                                                                                              # a new recorded name needs an alias, or news about it is invisible
    assert all(terms and all(t.strip() for t in terms) for terms in N.ALIASES.values())


@pytest.mark.parametrize("title, want", [
    ("Bank Nifty ends higher as HDFC Bank, ICICI Bank rally", ["BANKNIFTY", "HDFCBANK", "ICICIBANK"]),       # 'Bank Nifty' does not also name NIFTY
    ("Sensex, Nifty fall; M&M up; L&T wins order", ["NIFTY", "SENSEX", "LT", "M&M"]),
    ("SBI Q2 profit beats; ITC rises", ["SBIN", "ITC"]),
    ("Reliance Industries and Tata Motors in focus", ["RELIANCE", "TMPV"]),
    ("Titanic sinks; Nifty slips", ["NIFTY"]),                                                                      # a word that merely contains a name is not that name
    ("itc and sbi in lowercase, tcs too", []),                                                                       # short tickers must be capitals
    ("Tech Mahindra and Mahindra & Mahindra both gain", ["M&M", "TECHM"]),
    ("Nifty Financial Services index rises", ["FINNIFTY"]),
    ("RBI holds repo rate; markets cheer", []),
    ("", []), (None, []),
])
def test_a_headline_names_the_instruments_it_names(title, want):
    assert sorted(N.match_symbols(title)) == sorted(want)


def test_the_digest_dedupes_across_outlets_marks_recaps_and_impact_and_drops_old_and_unsafe(cfg):
    a = rss(("RBI cuts repo rate by 25 bps, Nifty rallies", "https://example.com/a1", rfc(20)),
            ("Infosys wins large deal; shares rise", "https://example.com/a2", rfc(50)),
            ("Sensex tumbles 700 points as rate fears grip", "https://example.com/a3", rfc(30)),
            ("Old story about Reliance", "https://example.com/old", rfc(0, hours=50)),
            ("Click here for Nifty", "javascript:alert(1)", rfc(10)),
            ("Plain http link story on HDFC Bank", "http://example.com/plain", rfc(15)))
    b = rss(("RBI cuts repo rate by 25 bps; Nifty rallies", "https://other.example/b1", rfc(18)),           # the same story from another outlet
            ("Unrelated sports headline", "https://other.example/b2", rfc(5)))
    srcs = [{"name": "Outlet A", "url": "https://a.test/feed"}, {"name": "Outlet B", "url": "https://b.test/feed"}, {"name": "Dead", "url": "https://dead.test/feed"}]

    def fetch(url):
        if "dead" in url:
            raise OSError("down")
        return a if "a.test" in url else b
    d = N.fetch_digest(cfg, NOW, fetch=fetch, sources=srcs)
    items = {x["title"]: x for x in d["items"]}
    rbi = next(x for t, x in items.items() if t.startswith("RBI cuts repo"))
    assert sorted(rbi["sources"]) == ["Outlet A", "Outlet B"] and "NIFTY" in rbi["symbols"] and rbi["recap"] is False       # one story, two outlets
    assert rbi["tone"] > 0 and rbi["impact"] == "high" and rbi["link"].startswith("https://")
    recap = next(x for t, x in items.items() if t.startswith("Sensex tumbles"))
    assert recap["recap"] is True and recap["impact"] != "high"                                                         # the market's own move retold is not news
    assert not any("Old story" in t for t in items)                                                                    # older than 36 hours
    assert items["Click here for Nifty"]["link"] == "" and items["Plain http link story on HDFC Bank"]["link"] == ""      # only https links survive
    assert next(x for t, x in items.items() if t.startswith("Infosys"))["symbols"] == ["INFY"]
    assert d["sources"]["Outlet A"].startswith("ok") and d["sources"]["Dead"].startswith("fail") and d["n"] == len(d["items"])
    assert [x["ts"] for x in d["items"]] == sorted((x["ts"] for x in d["items"]), reverse=True)                        # newest first
    json.dumps(d, allow_nan=False)                                                                                     # plain JSON, no NaN


def test_the_digest_is_bounded_and_titles_are_cut(cfg):
    many = rss(*[(f"Story number {i} about Nifty " + "x" * 400, f"https://example.com/{i}", rfc(i + 1)) for i in range(150)])
    d = N.fetch_digest(cfg, NOW, fetch=lambda u: many, sources=[{"name": "A", "url": "https://a.test/f"}])
    assert d["n"] <= N.MAX_ITEMS and all(len(x["title"]) <= 220 for x in d["items"])
    assert len(json.dumps(d)) < 100_000                                                                                # fits the relay's limit with room


class Resp:
    def __init__(self, body=b"{}"):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self, n=-1):
        return self.body


def test_pushing_goes_to_the_news_route_with_the_key_over_https_and_never_leaks_it():
    seen = []

    def opener(req, timeout=None):
        seen.append((req.full_url, req.get_header("Authorization"), json.loads(req.data)))
        return Resp(b'{"ok": true}')
    N.push({"v": 1, "items": []}, "https://x.workers.dev/live/ingest", "I" * 40, opener=opener)
    assert seen[0][0] == "https://x.workers.dev/news/ingest" and seen[0][1] == "Bearer " + "I" * 40 and seen[0][2] == {"v": 1, "items": []}
    with pytest.raises(ValueError):
        N.push({}, "http://x.workers.dev/live/ingest", "I" * 40, opener=opener)
    with pytest.raises(ValueError):
        N.push({}, "https://x.workers.dev/live/ingest", "", opener=opener)
    secret = "S3CRET" * 7

    def boom(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 401, "no", {}, io.BytesIO(b""))

    def dead(req, timeout=None):
        raise OSError(f"{req.full_url} {req.get_header('Authorization')}")
    for op in (boom, dead):
        with pytest.raises(RuntimeError) as e:
            N.push({}, "https://x.workers.dev/live/ingest", secret, opener=op)
        assert secret not in str(e.value) and "workers.dev" not in str(e.value)
    with pytest.raises(ValueError):
        N.push({"x": float("nan")}, "https://x.workers.dev/live/ingest", "I" * 40, opener=opener)                       # NaN is not JSON
    assert N._NoRedirect().redirect_request(None, None, 302, "", {}, "https://evil.example/") is None


def test_the_digest_module_holds_no_secret_and_places_nothing():
    import re
    src = (ROOT / "quantdesk" / "premarket" / "newsdigest.py").read_text(encoding="utf-8")
    code = re.sub(r'""".*?"""', "", src, flags=re.S)
    assert not re.search(r"os\.environ|getenv|KITE_|KOTAK_|place_order|\.order\(|import (subprocess|socket)", code)


def test_the_news_command_builds_saves_and_pushes_only_with_the_key(cfg, tmp_path, monkeypatch, capsys):
    from quantdesk.newslink import cli as NC
    sent = []
    digest = {"v": 1, "asof": "x", "n": 1, "sources": {"A": "ok 1"}, "items": [{"title": "t"}]}
    monkeypatch.setattr(N, "fetch_digest", lambda cfg, now=None, **k: digest)
    monkeypatch.setattr(N, "push", lambda d, url, token, **k: sent.append((d, url, token)) or {"n": 1})
    A = lambda **kw: type("A", (), {"push": False, "send": None, "out": str(tmp_path), "now": None, **kw})      # noqa: E731
    NC.cmd_news(cfg, A())
    assert json.loads((tmp_path / "news.json").read_text()) == digest and not sent                  # saved, not sent
    with pytest.raises(SystemExit) as e:
        NC.cmd_news(cfg, A(push=True))
    assert "LIVE_URL" in str(e.value) and not sent
    monkeypatch.setenv("LIVE_URL", "https://x.workers.dev/live/ingest")
    monkeypatch.setenv("LIVE_INGEST_TOKEN", "I" * 40)
    NC.cmd_news(cfg, A(push=True))
    assert sent == [(digest, "https://x.workers.dev/live/ingest", "I" * 40)]
    monkeypatch.setattr(N, "fetch_digest", lambda cfg, now=None, **k: {**digest, "sources": {"A": "fail x"}})
    with pytest.raises(SystemExit) as e:                                                              # every feed down: nothing is pushed over the last good digest
        NC.cmd_news(cfg, A(push=True))
    assert "no feed answered" in str(e.value) and len(sent) == 1


def test_the_send_step_reads_only_our_own_file_and_needs_the_key_and_a_digest_shape(cfg, tmp_path, monkeypatch):
    from quantdesk.newslink import cli as NC
    sent = []
    monkeypatch.setattr(N, "fetch_digest", lambda *a, **k: (_ for _ in ()).throw(AssertionError("the send step must not read a feed")))
    monkeypatch.setattr(N, "push", lambda d, url, token, **k: sent.append((d, url, token)) or {"n": 2})
    A = lambda **kw: type("A", (), {"push": False, "send": None, "out": str(tmp_path), "now": None, **kw})      # noqa: E731
    f = tmp_path / "news.json"
    f.write_text(json.dumps({"v": 1, "asof": "2026-11-09T05:45:00Z", "items": []}), encoding="utf-8")
    with pytest.raises(SystemExit) as e:
        NC.cmd_news(cfg, A(send=str(f)))
    assert "LIVE_URL" in str(e.value) and not sent                                                  # no key, nothing sent
    monkeypatch.setenv("LIVE_URL", "https://x.workers.dev/live/ingest")
    monkeypatch.setenv("LIVE_INGEST_TOKEN", "I" * 40)
    NC.cmd_news(cfg, A(send=str(f)))
    assert len(sent) == 1 and sent[0][2] == "I" * 40
    for bad in ("not json", json.dumps([1]), json.dumps({"v": 2, "asof": "x", "items": []}), json.dumps({"v": 1, "asof": "x", "items": "no"}), json.dumps({"v": 1, "asof": "x", "items": [0] * 201})):
        f.write_text(bad, encoding="utf-8")
        with pytest.raises(SystemExit):
            NC.cmd_news(cfg, A(send=str(f)))
    with pytest.raises(SystemExit):
        NC.cmd_news(cfg, A(send=str(tmp_path / "missing.json")))
    assert len(sent) == 1
