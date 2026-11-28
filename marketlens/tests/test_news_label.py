"""News P3: the labelling run's selection, packing, parsing, pricing, cap and resume, against a fake client."""
import json
from types import SimpleNamespace as NS

import pandas as pd

from marketlens.news import label as L


def corpus():
    ts = pd.Timestamp("2023-01-06 12:52", tz="UTC")
    return pd.DataFrame([
        {"id": "a", "ts": ts, "ts_quality": "exact", "source": "nse", "kind": "filing", "symbol": "RELIANCE", "title": "Outcome of Board Meeting",
         "summary": "Results for the quarter", "publisher": "NSE", "query": "", "link": ""},
        {"id": "b", "ts": ts, "ts_quality": "exact", "source": "nse", "kind": "filing", "symbol": "RATEGAIN", "title": "Updates",
         "summary": "x", "publisher": "NSE", "query": "", "link": ""},
        {"id": "c", "ts": ts, "ts_quality": "day", "source": "gnews", "kind": "headline", "symbol": "NIFTY", "title": "RBI cuts repo by 25 bps",
         "summary": "", "publisher": "Mint", "query": "", "link": ""},
        {"id": "d", "ts": ts + pd.Timedelta("1h"), "ts_quality": "day", "source": "gnews", "kind": "headline", "symbol": "MACRO:RBI",
         "title": "RBI cuts repo by 25 bps!", "summary": "", "publisher": "ET", "query": "", "link": ""},
    ])


def test_select_keeps_watchlist_filings_and_one_copy_of_a_headline():
    s = L.select(corpus())
    assert list(s["id"]) == ["a", "c"]                        # RATEGAIN is not on the watchlist; d repeats c


def test_requests_pack_stories_cache_the_instructions_and_ask_for_the_schema():
    reqs = L.requests_for(L.select(corpus()), L.HAIKU, per=1)
    assert [r["ids"] for r in reqs] == [["a"], ["c"]]
    p = reqs[0]["params"]
    assert p["system"][0]["cache_control"] == {"type": "ephemeral"} and p["output_config"]["format"]["type"] == "json_schema"
    items = json.loads(p["messages"][0]["content"].split("\n", 1)[1])
    assert items[0]["company"] == "RELIANCE" and items[0]["date"] == "2023-01-06 18:22 IST"
    c = json.loads(reqs[1]["params"]["messages"][0]["content"].split("\n", 1)[1])[0]
    assert c == {"i": 0, "date": "2023-01-06", "source": "Mint", "headline": "RBI cuts repo by 25 bps"}


def test_parse_maps_labels_back_and_drops_bad_ones():
    text = json.dumps({"labels": [{"i": 0, "event_type": "rbi_policy"}, {"i": 5}, {"i": 0, "event_type": "dup"}, {"i": "x"}]})
    assert L.parse(text, ["c"]) == [{"id": "c", "event_type": "rbi_policy"}]
    assert L.parse("not json", ["c"]) == []


def test_cost_uses_batch_prices():
    u = {"input_tokens": 1_000_000, "output_tokens": 1_000_000, "cache_read_input_tokens": 1_000_000}
    assert L.cost(u, L.HAIKU) == (0.10 + 0.50 + 0.01) / 2
    assert L.cost(u, L.OPUS) == (4 + 20 + 0.40) / 2


class FakeBatches:
    def __init__(self, cost_out=400_000):
        self.created, self.cost_out = [], cost_out

    def create(self, requests):
        self.created.append(requests)
        return NS(id=f"b{len(self.created)}")

    def retrieve(self, bid):
        return NS(processing_status="ended")

    def results(self, bid):
        for r in self.created[int(bid[1:]) - 1]:
            n = json.loads(r["params"]["messages"][0]["content"].split("\n", 1)[1])
            text = json.dumps({"labels": [{"i": it["i"], "event_type": "other"} for it in n]})
            msg = NS(usage=NS(input_tokens=1000, output_tokens=self.cost_out, cache_read_input_tokens=0, cache_creation_input_tokens=0),
                     stop_reason="end_turn", content=[NS(type="text", text=text)])
            yield NS(custom_id=r["custom_id"], result=NS(type="succeeded", message=msg))


def test_label_stops_at_the_cap_and_resumes_without_paying_twice(tmp_path):
    stories = pd.concat([corpus().iloc[[0]].assign(id=f"s{k}") for k in range(10)], ignore_index=True)
    reqs = L.requests_for(stories, L.HAIKU, per=1)
    fb = FakeBatches()                                         # each request: 400k output tokens = $0.10 at batch price
    client = NS(messages=NS(batches=fb))
    run = L.Run(tmp_path, L.HAIKU)
    st = L.label(client, reqs, run, cap_usd=0.35, tranche=2, say=lambda *a: None, sleep=lambda s: None)
    assert st["spent"] <= 0.35 + 1e-9 and len(run.done) == 3   # 2 in the first tranche, then only what fits
    again = L.Run(tmp_path, L.HAIKU)
    assert again.done == run.done and again.state["spent"] == st["spent"]
    L.label(client, reqs, again, cap_usd=10, tranche=20, say=lambda *a: None, sleep=lambda s: None)
    sent = [r["custom_id"] for b in fb.created for r in b]
    assert len(sent) == len(set(sent)) == 10                   # no request was sent twice


def test_estimate_counts_tokens_without_spending():
    class C:
        def count_tokens(self, **kw):
            return NS(input_tokens=3000 if kw["messages"][0]["content"] != "x" else 2000)
    reqs = L.requests_for(pd.concat([corpus().iloc[[0]].assign(id=f"s{k}") for k in range(50)]), L.HAIKU, per=25)
    e = L.estimate(NS(messages=C()), reqs, L.HAIKU)
    assert e["requests"] == 2 and e["stories"] == 50 and e["system_tokens"] == 2000 and e["usd"] > 0


def test_audit_sample_draws_from_every_stratum():
    s = pd.concat([corpus().iloc[[0, 2]].assign(id=lambda d, k=k: d["id"] + str(k)) for k in range(30)], ignore_index=True)
    a = L.audit_sample(s, n=10)
    assert len(a) == 10 and set(a["source"]) == {"nse", "gnews"}


def test_the_cli_command_runs_end_to_end_on_an_empty_corpus(tmp_path):
    import subprocess
    import sys
    r = subprocess.run([sys.executable, "-m", "marketlens", "news-label", "--corpus", str(tmp_path / "c"), "--out", str(tmp_path / "o"),
                        "--mode", "estimate"], capture_output=True, text=True, env={**__import__("os").environ, "ANTHROPIC_API_KEY": "x"})
    assert r.returncode == 0, r.stderr
    assert "0 stories to label" in r.stdout
