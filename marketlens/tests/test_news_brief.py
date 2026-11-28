"""The situation briefs: the payload carries the measured tables, one request per situation, the budget is shared."""
import json
from types import SimpleNamespace as NS

from marketlens.news import brief as B, label as L

SIT = {"SIT:IRAN_US_ISRAEL": {"name": "US / Israel - Iran", "sides": ["United States", "Israel", "Iran"], "stories": 40,
                              "first": "2019-05-01", "last": "2026-11-27",
                              "episodes": [{"start": "2020-01-03", "stories": 30, "headlines": ["US strike kills Soleimani"],
                                            "reaction": {"Brent": {1: 0.0351, 5: 0.0123, 20: -0.0712}}}],
                              "base_rates": {"Brent": {1: {"n": 1, "median": 0.0351, "share_up": 1.0}}}}}


def test_payload_has_episodes_reactions_base_rates_and_latest_headlines():
    p = B.payload("SIT:IRAN_US_ISRAEL", SIT["SIT:IRAN_US_ISRAEL"], [{"date": "2026-11-27", "title": "Iran warns of retaliation"}])
    assert "2020-01-03 (30 stories): US strike kills Soleimani" in p and '"Brent":{"1":0.0351' in p
    assert "BASE RATES" in p and "2026-11-27: Iran warns of retaliation" in p


def test_requests_one_per_situation_with_the_schema():
    reqs = B.requests_for(SIT, {})
    assert len(reqs) == 1 and reqs[0]["custom_id"] == "SIT_IRAN_US_ISRAEL"
    assert reqs[0]["params"]["model"] == L.OPUS and reqs[0]["params"]["output_config"]["format"]["type"] == "json_schema"


class FB:
    def __init__(self):
        self.sent = []

    def create(self, requests):
        self.sent.append(requests)
        return NS(id="b1")

    def retrieve(self, i):
        return NS(processing_status="ended")

    def results(self, i):
        for r in self.sent[-1]:
            msg = NS(usage={"input_tokens": 20000, "output_tokens": 8000}, model=L.OPUS,
                     content=[NS(type="text", text=json.dumps({"summary": "s"}))])
            yield NS(custom_id=r["custom_id"], result=NS(type="succeeded", message=msg))


def test_write_saves_briefs_counts_the_spend_and_respects_the_shared_budget(tmp_path):
    reqs = B.requests_for(SIT, {})
    fb = FB()
    client = NS(messages=NS(batches=fb))
    st = B.write(client, reqs, tmp_path, spent_elsewhere=12.99, cap=13, say=lambda *a: None)
    assert fb.sent == [] and st["spent"] == 0                    # no room left: nothing sent
    st = B.write(client, reqs, tmp_path, spent_elsewhere=5.0, cap=13, say=lambda *a: None)
    assert (tmp_path / "brief_SIT_IRAN_US_ISRAEL.json").exists() and st["spent"] > 0
    assert L.total_spent(tmp_path) == st["spent"]
    B.write(client, reqs, tmp_path, spent_elsewhere=5.0, cap=13, say=lambda *a: None)
    assert len(fb.sent) == 1                                    # written once, never paid twice
