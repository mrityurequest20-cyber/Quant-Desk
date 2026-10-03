"""Language models as second news readers (fakes only: no network, no keys): the Claude request shape, lenient
parsing, the background desk's filters and budget, point-in-time use in the tone, grading per reader, and the
after-close reflection."""
import json
from types import SimpleNamespace as NS

import pandas as pd
import pytest

from quantdesk.intraday import llm
from quantdesk.intraday.news import NewsDesk, NewsItem, classify

IST = "Asia/Kolkata"
NOW = pd.Timestamp("2026-10-05 11:00", tz=IST)


class FakeAnthropic:
    def __init__(self, reply=None, stop="end_turn"):
        self.calls, self.reply, self.stop = [], reply, stop
        self.beta = NS(messages=NS(create=self.create))

    def create(self, **kw):
        self.calls.append(kw)
        ids = [l.split(" | ")[0] for l in kw["messages"][0]["content"].splitlines() if " | " in l and not l.startswith("Headlines")]
        body = self.reply if self.reply is not None else json.dumps(
            {"reads": [{"id": i, "nifty": 0.6, "banknifty": 0.9, "confidence": 0.8, "event": "policy", "why": "rate cut"}
                       for i in ids]})
        return NS(stop_reason=self.stop, usage=NS(input_tokens=900, output_tokens=300),
                  content=[NS(type="thinking", thinking="…"), NS(type="text", text=body)] if self.stop != "refusal" else [])


def test_claude_reader_asks_for_structured_reads_with_fallbacks():
    fake = FakeAnthropic()
    r = llm.ClaudeReader("k", client=fake)
    got = r.read([{"id": "a1", "ts": "2026-10-05 10:00", "source": "ET", "title": "RBI cuts repo rate by 25 bps"}])
    assert got["a1"] == {"NIFTY": 0.6, "BANKNIFTY": 0.9, "confidence": 0.8, "event": "policy", "why": "rate cut"}
    kw = fake.calls[0]
    assert kw["model"] == "claude-opus-5-5" and kw["fallbacks"] == "default"
    assert kw["betas"] == ["server-side-fallback-2026-07-01"]
    assert kw["output_config"]["effort"] == "low" and kw["output_config"]["format"]["type"] == "json_schema"
    assert "thinking" not in kw and kw["max_tokens"] <= 16000                     # Opus 5.5: thinking is always on
    assert r.usage == {"calls": 1, "in": 900, "out": 300}
    assert llm.ClaudeReader("k", client=FakeAnthropic(stop="refusal")).read([{"id": "a1", "ts": "", "source": "", "title": "x"}]) == {}


def test_reads_are_parsed_leniently_and_clipped():
    ids = {"a", "b"}
    txt = 'Sure: {"reads": [{"id": "a", "nifty": 3, "banknifty": "-0.5", "confidence": 2, "event": "weird", "why": "x"},' \
          ' {"id": "zzz", "nifty": 1}]} trailing'
    got = llm._parse_reads(txt, ids)
    assert got == {"a": {"NIFTY": 1.0, "BANKNIFTY": -0.5, "confidence": 1.0, "event": "general", "why": "x"}}
    assert llm._parse_reads("not json", ids) == {} and llm._parse_reads(None, ids) == {}
    # what gpt-oss:120b on Ollama actually sent on 2 Oct 2026, ignoring the JSON format
    md = ("**t1**  \n- **NIFTY impact:**\u202f+0.6  \n- **BANKNIFTY impact:**\u202f+0.5  \n- **confidence:**\u202f0.7  \n"
          "- **why:**\u202fUnexpected 25\u202fbps rate cut lowers funding costs and boosts risk appetite.")
    got = llm._parse_reads(md, {"t1"})["t1"]
    assert (got["NIFTY"], got["BANKNIFTY"], got["confidence"], got["event"]) == (0.6, 0.5, 0.7, "general")
    assert got["why"].startswith("Unexpected 25")
    two = "a: NIFTY −0.4, BANKNIFTY −0.6, confidence 0.8, event inflation, why hot CPI\nb: NIFTY 0 BANKNIFTY 0.1"
    r = llm._parse_reads(two, {"a", "b"})
    assert r["a"]["NIFTY"] == -0.4 and r["a"]["event"] == "inflation" and r["b"]["BANKNIFTY"] == 0.1


class FakeHTTP:
    def __init__(self, payload):
        self.payload, self.posts = payload, []

    def post(self, url, json=None, timeout=None, headers=None):
        self.posts.append((url, json, headers))
        return NS(raise_for_status=lambda: None, json=lambda: self.payload)


def test_gemini_and_ollama_readers_over_rest():
    reads = '{"reads": [{"id": "a", "nifty": -0.4, "banknifty": -0.2, "confidence": 0.5, "event": "inflation", "why": "hot CPI"}]}'
    g = FakeHTTP({"candidates": [{"content": {"parts": [{"text": reads}]}}], "usageMetadata": {"promptTokenCount": 50}})
    got = llm.GeminiReader("gk", session=g).read([{"id": "a", "ts": "", "source": "ET", "title": "CPI 5.4% vs 5.0%"}])
    assert got["a"]["NIFTY"] == -0.4 and g.posts[0][2] == {"x-goog-api-key": "gk"} and "gk" not in g.posts[0][0]
    o = FakeHTTP({"message": {"content": reads}, "prompt_eval_count": 70, "eval_count": 20})
    r = llm.OllamaReader("ok", session=o)
    assert r.read([{"id": "a", "ts": "", "source": "ET", "title": "x"}])["a"]["event"] == "inflation"
    url, body, headers = o.posts[0]
    assert url == "https://ollama.com/api/chat" and body["format"] == llm.READ_SCHEMA and headers["Authorization"] == "Bearer ok"


def test_keys_come_from_any_common_name(monkeypatch):
    for names in llm.KEY_NAMES.values():
        for n in names:
            monkeypatch.delenv(n, raising=False)
    assert llm.key_for("claude") == (None, None)
    monkeypatch.setenv("CLAUDE_API_KEY", "  sk-x ")
    monkeypatch.setenv("GOOGLE_API_KEY", "g")
    assert llm.key_for("claude") == ("CLAUDE_API_KEY", "sk-x") and llm.key_for("gemini")[0] == "GOOGLE_API_KEY"


class Reader:
    def __init__(self, name, tone=0.8, fail=False):
        self.name, self.tone, self.fail, self.seen = name, tone, fail, []
        self.usage = {"calls": 0, "in": 0, "out": 0}

    def read(self, items):
        self.seen.append([i["id"] for i in items])
        self.usage["calls"] += 1
        if self.fail:
            raise RuntimeError("503")
        return {i["id"]: {"NIFTY": self.tone, "BANKNIFTY": self.tone, "confidence": 1.0, "event": "policy", "why": ""}
                for i in items}


def story(title, minutes_ago=10, source="ET"):
    return classify(NewsItem(NOW - pd.Timedelta(minutes=minutes_ago), source, title, id=title[:30]))


def test_the_desk_reads_only_what_matters_within_budget(cfg):
    a, b = Reader("claude"), Reader("gemini", fail=True)
    clock = iter(pd.date_range(NOW, periods=50, freq="1min"))
    desk = llm.LLMDesk(cfg, readers=[a, b], sync=True, clock=lambda: next(clock))
    desk.max_calls, desk.batch = 2, 2
    xs = [story("RBI cuts repo rate by 25 bps, Nifty in focus"), story("Sensex tumbles 700 points"),
          story("Local bakery opens new branch"), story("Fed raises rates; Nifty, Bank Nifty in focus"),
          story("HDFC Bank Q2 net profit beats estimates")]
    assert desk.submit(xs, NOW) == 3                       # the recap and the off-topic story are skipped
    assert desk.submit(xs, NOW) == 0                       # never read twice
    assert a.seen == [[xs[0].id, xs[3].id], [xs[4].id]] and b.usage["calls"] == 2 and "503" in desk.errors["gemini"]
    got = desk.drain()
    assert len(got) == 3 and {g[1] for g in got} == {"claude"} and all("at" in g[2] for g in got)
    desk.submit([story("RBI governor says inflation risks have eased, Nifty")], NOW)
    assert "daily cap" in desk.errors["claude"]


def test_reads_count_from_when_they_arrived_and_by_each_readers_record(cfg):
    news = NewsDesk(cfg, fetch=lambda url: "", sources=[])
    x = story("RBI keeps repo rate unchanged, Nifty in focus", 30)   # the rules read it as neutral
    news.add([x])
    later = NOW + pd.Timedelta(minutes=5)
    news.llm = llm.LLMDesk(cfg, readers=[Reader("claude", tone=0.9), Reader("ollama", tone=-0.9)], sync=True,
                           clock=lambda: later)
    news.llm.submit([x], NOW)
    assert news.collect() == [x] and set(x.nlp["llm"]["readers"]) == {"claude", "ollama"}
    assert news.item_tone(x, "NIFTY", NOW) == x.sentiment                       # not arrived yet at 11:00
    assert news.item_tone(x, "NIFTY", later) == pytest.approx((x.sentiment + 0.9 - 0.9) / 3)
    news.reader_trust = lambda name: {"rules": 1.0, "claude": 1.5, "ollama": 0.5}[name]
    assert news.item_tone(x, "NIFTY", later) == pytest.approx((x.sentiment + 1.35 - 0.45) / 3)
    assert news.state("NIFTY", later)["tone"] > news.state("NIFTY", NOW)["tone"]


def test_each_reader_is_graded_on_its_own(tmp_path):
    from quantdesk.intraday.learning import Memory, grade_news
    from quantdesk.journal.journal import Journal
    from test_learning import day_bars
    j = Journal(tmp_path / "j.db")
    x = classify(NewsItem(pd.Timestamp("2026-10-05 10:00", tz=IST), "ET", "RBI keeps repo rate unchanged, Nifty, banks", id="n1"))
    x.nlp["llm"] = {"readers": {"claude": {"NIFTY": 0.7, "BANKNIFTY": 0.7, "at": "2026-10-05 10:01:00+05:30"},
                                "gemini": {"NIFTY": -0.6, "BANKNIFTY": -0.6, "at": "2026-10-05 10:01:00+05:30"}}}
    j.news_add([x], pd.Timestamp("2026-10-05 10:01", tz=IST))
    m = Memory()
    grade_news(m, j.news(), {"NIFTY": day_bars(), "BANKNIFTY": day_bars(start=55000.0)})
    assert m.stat("news_reader", "claude")["hits"] == 2 and m.stat("news_reader", "gemini")["hits"] == 0
    assert m.stat("news_reader", "rules") is None                              # a neutral rules read isn't graded


def test_the_close_writes_claudes_reflection_and_the_cost(cfg, tmp_path):
    from quantdesk.core.calendar import TradingCalendar
    from quantdesk.intraday.engine import IntradayEngine, run_replay
    from quantdesk.intraday.feeds import ReplayFeed
    from quantdesk.intraday.learning import Memory
    from quantdesk.intraday.sim import IntradayBroker
    from quantdesk.intraday.synthetic import simulate_sessions
    from quantdesk.journal.journal import Journal
    days = [d.date() for d in TradingCalendar(cfg.holidays()).trading_days("2026-09-14", "2026-09-28")]
    bars, _ = simulate_sessions(days, seed=5)
    reply = json.dumps({"lessons": ["The ORB long at 10:05 fought a falling VWAP."], "watch_tomorrow": ["Gap vs 25,100"]})
    claude = llm.ClaudeReader("k", client=FakeAnthropic(reply=reply))
    news = NewsDesk(cfg, fetch=lambda url: "", sources=[])
    news.llm = llm.LLMDesk(cfg, readers=[claude], sync=True)
    mem = Memory(tmp_path / "m.json")
    eng = IntradayEngine(cfg, ReplayFeed(bars, days[-1]), "model", Journal(), IntradayBroker(cfg, starting_cash=500000),
                         say=None, news=news, memory=mem)
    review = run_replay(eng)
    assert "## Reflection (Claude, after the close)" in review and "fought a falling VWAP" in review
    assert "Gap vs 25,100" in review and "Language models today: claude 1 calls" in review and "≈ $0.01" in review
    assert json.loads((tmp_path / "m.json").read_text())["lessons"][-1]["day"] == str(days[-1])
    sent = claude.client.calls[0]
    assert sent["output_config"]["effort"] == "medium" and "Session review" in sent["messages"][0]["content"]


def test_the_workflows_pass_every_accepted_key_name():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1] / ".github" / "workflows"
    live, check = (root / "live.yml").read_text(), (root / "ai-check.yml").read_text()
    for names in llm.KEY_NAMES.values():
        for n in names:
            assert f"secrets.{n} " in live or f"secrets.{n} }}}}" in live, n          # the desk gets the key...
            assert f"HAS_{n}: ${{{{ secrets.{n} != '' }}}}" in check, n             # ...and AI check reports the name


def test_gemini_moves_past_a_retired_model():
    reads = '{"reads": [{"id": "a", "nifty": 0.3, "banknifty": 0.2, "confidence": 0.6, "event": "policy", "why": "cut"}]}'

    class Http:
        def __init__(self):
            self.urls = []

        def post(self, url, json=None, timeout=None, headers=None):
            self.urls.append(url)
            code = 404 if "gemini-2.5-flash:" in url else 503 if "flash-latest" in url else 200   # retired / busy
            return NS(status_code=code, json=lambda: {"candidates": [{"content": {"parts": [{"text": reads}]}}]},
                      raise_for_status=lambda: None)
    h = Http()
    r = llm.GeminiReader("k", model="gemini-2.5-flash", session=h)
    assert r.read([{"id": "a", "ts": "", "source": "ET", "title": "x"}])["a"]["NIFTY"] == 0.3
    assert r.model == "gemini-3-flash-preview" and len(h.urls) == 4             # busy model: tried twice; retired: once
    assert r.last_raw["tried"] == ["gemini-2.5-flash 404", "gemini-flash-latest 503", "gemini-3-flash-preview 200"]
