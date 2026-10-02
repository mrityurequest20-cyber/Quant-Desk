"""Headline NLP: event type, surprise against expectations, heavyweight exposure, certainty, novelty, and how they
change what the desk takes from the news."""
import sqlite3

import pandas as pd
import pytest

from quantdesk.intraday import nlp
from quantdesk.intraday.news import NewsDesk, NewsItem, classify
from quantdesk.journal.journal import Journal


@pytest.mark.parametrize("text,sign", [
    ("India's CPI inflation rises to 5.4% in September vs expected 5.0%", -1),     # inflation above: bearish
    ("Retail inflation eases to 3.1% in August; economists had expected 3.5%", 1),
    ("GDP grows 7.8% in Q1 against forecast of 7.2%", 1),                          # not the 1 in "Q1"
    ("US unemployment rate rises to 4.6% vs 4.3% expected", -1),                  # more joblessness: bearish
    ("HDFC Bank Q2 net profit rises 18%, beats estimates", 1),
    ("ICICI Bank misses street estimates as provisions jump", -1),
    ("Reliance Industries Q2 profit ₹19,300 crore vs estimates of ₹18,000 crore", 1),
    ("RBI cuts repo rate by 25 bps to 5.25%", 1),
    ("Fed raises interest rates by 25 basis points", -1),
    ("RBI keeps repo rate unchanged at 5.5%", 0),
    ("Results in line with expectations for Infosys", 0),
])
def test_surprise_is_signed_for_indian_equities(text, sign):
    r = nlp.read(text)
    assert r.surprise is not None and (r.surprise == 0 if sign == 0 else r.surprise * sign > 0.1), (text, r)


def test_no_expectation_no_surprise():
    for t in ("Crude oil prices surge 4% on Middle East tensions", "Sensex, Nifty end lower for third day",
              "Reliance Power shares jump 10%"):
        assert nlp.read(t).surprise is None


def test_events_entities_and_certainty():
    assert nlp.read("RBI cuts repo rate by 25 bps").event == "policy"
    assert nlp.read("Missile strikes hit oil facility").event == "geopolitics"
    assert nlp.read("Sensex, Nifty end lower", recap=True).event == "market_recap"
    assert nlp.read("ICICI Bank misses street estimates").event == "earnings"         # a results story without "results"
    hdfc = nlp.read("HDFC Bank Q2 profit beats estimates")
    assert hdfc.names == ["HDFC Bank"] and hdfc.exposure["BANKNIFTY"] == pytest.approx(0.28)
    assert nlp.read("Reliance Power shares jump").names == []                         # not Reliance Industries
    assert nlp.read("Kotak Securities launches a new app").names == []                # not Kotak Mahindra Bank
    assert nlp.read("Govt may cut excise duty on fuel, sources say").certainty == 0.5
    assert nlp.read("Will the RBI cut rates this week?").certainty <= 0.6
    assert nlp.read("RBI cuts repo rate by 25 bps").certainty == 1.0


def test_novelty_marks_retellings():
    nv = nlp.Novelty()
    assert nv.score("a", "RBI cuts repo rate by 25 bps to 5.25%")[0] == 1.0
    assert nv.score("b", "Crude oil surges on Middle East tension")[0] > 0.9
    again, related = nv.score("c", "RBI slashes repo rate 25 bps, first rate cut this year")
    assert again < 0.7 and related == "a"


def item(title, minutes_ago=10, now=pd.Timestamp("2026-10-05 11:00", tz="Asia/Kolkata"), source="ET"):
    return classify(NewsItem(now - pd.Timedelta(minutes=minutes_ago), source, title, id=title[:40]))


def test_a_surprise_outweighs_how_the_words_lean():
    x = item("Inflation eases to 5.1% but stays above the 4.8% expected", 5)
    y = item("Inflation eases to 5.1% vs expected 5.4%", 5)
    assert x.lex > 0 and x.nlp["surprise"] < 0 and x.sentiment < x.lex              # "eases" reads well; above expected doesn't
    assert y.sentiment > 0.3 and y.nlp["surprise"] > 0
    cpi = item("India's CPI inflation rises to 5.4% in September vs expected 5.0%")
    assert cpi.sentiment < -0.3 and cpi.impact == "high" and cpi.nlp["event"] == "inflation"
    bank = item("HDFC Bank Q2 net profit rises 18%, beats estimates")
    assert bank.about["BANKNIFTY"] > bank.about["NIFTY"] >= 2                        # weighted by index share


def test_desk_weights_event_half_life_certainty_and_novelty(cfg):
    now = pd.Timestamp("2026-10-05 11:00", tz="Asia/Kolkata")
    desk = NewsDesk(cfg, fetch=lambda url: "", sources=[])
    policy = item("RBI cuts repo rate by 25 bps to 5.25%, Nifty in focus", 100)
    gossip = item("Nifty traders may see choppy moves, analysts say", 100)
    desk.add([policy, gossip])
    st = desk.state("NIFTY", now)
    assert st["top_surprise"]["event"] == "policy" and st["surprise"] > 0
    assert st["events"].get("policy") == 1 and st["tone"] > 0                        # policy dominates the stale gossip
    assert policy.novelty == 1.0
    rehash = item("RBI cuts repo rate 25 bps; Nifty in focus as rate cut lands", 5)
    desk.add([rehash])
    assert rehash.novelty < 0.7 and rehash.nlp.get("related") == policy.id


def test_journal_gains_the_nlp_column_in_place(tmp_path):
    path = tmp_path / "old.db"
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE news (id TEXT PRIMARY KEY, ts TEXT, seen_at TEXT, source TEXT, sources TEXT, title TEXT, "
               "link TEXT, summary TEXT, sentiment REAL, impact TEXT, about TEXT)")
    db.commit()
    db.close()
    j = Journal(path)
    j.news_add([item("RBI cuts repo rate by 25 bps")], pd.Timestamp("2026-10-05 11:00", tz="Asia/Kolkata"))
    j.commit()
    row = j.news().iloc[0]
    assert '"event": "policy"' in row["nlp"]
    j.close()


def test_an_outcome_with_the_market_move_is_news_not_a_recap():
    cut = item("RBI cuts repo rate by 25 bps, Nifty and banks rally")
    assert not cut.recap and cut.nlp["event"] == "policy" and cut.impact == "high" and cut.sentiment > 0.3
    miss = item("Sensex, Nifty fall as HDFC Bank Q2 profit misses estimates")
    assert not miss.recap and miss.nlp["event"] == "earnings" and miss.sentiment < 0
    for t in ("Stock market crash: Sensex tumbles 700 points", "Sensex tumbles 700 points as Fed rate hike fears grip markets"):
        assert item(t).recap and item(t).impact != "high"            # the move retold, no outcome: still a recap
