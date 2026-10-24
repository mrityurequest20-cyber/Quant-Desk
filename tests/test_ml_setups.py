"""The labelled-setup counter (quantdesk/ml/setups.py, P0.7): the record, the counting rules, and the reading of the real journal and learning memory. The exit test of
P0.7 is that the digest line matches the journal: the count here is checked against rows written into a journal with the desk's own schema."""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import date

import pytest

from quantdesk.journal.journal import Journal
from quantdesk.ml import setups as S

TZ = "+05:30"


def setup(i=1, **over):
    rec = {"setup_id": f"s{i}", "source": "paper", "symbol": "NIFTY", "session": "2026-10-27", "ts": f"2026-10-27T10:00:00{TZ}",
           "labelled_at": f"2026-10-27T15:30:00{TZ}", "outcome": 1.5}
    rec.update(over)
    return rec


# ---- the record -------------------------------------------------------------------------------------------------------------------------------
def test_a_good_record_validates_and_each_rule_fails_on_its_own():
    assert S.validate(setup()) == setup()
    for over, why in (({"source": "tape"}, "source"), ({"symbol": " "}, "symbol"), ({"setup_id": "bad id"}, "setup_id"), ({"setup_id": "x" * 129}, "setup_id"),
                      ({"ts": "2026-10-27T10:00:00"}, "zone"), ({"labelled_at": "2026-10-27T09:59:59+05:30"}, "after ts"), ({"labelled_at": f"2026-10-27T10:00:00{TZ}"}, "after ts"),
                      ({"session": "2026-10-28"}, "date of ts"), ({"session": "2026-13-01"}, "real YYYY-MM-DD"), ({"session": "20261027"}, "real YYYY-MM-DD"),
                      ({"outcome": float("nan")}, "finite"), ({"outcome": True}, "finite"), ({"outcome": 10**400}, "finite"), ({"outcome": "1"}, "finite")):
        with pytest.raises(S.BadSetup, match=why):
            S.validate(setup(**over))
    for k in ("setup_id", "source", "symbol", "session", "ts", "labelled_at", "outcome"):
        rec = setup()
        del rec[k]
        with pytest.raises(S.BadSetup, match=f"missing {k}"):
            S.validate(rec)
    for junk in ([], "x", None, 5):
        assert S.check_setup(junk) == ["a setup record must be an object"]


def test_a_replay_setup_counts_without_a_stored_outcome_and_every_other_source_needs_one():
    assert S.check_setup(setup(source="replay", outcome=None)) == []
    rec = setup(source="replay")
    del rec["outcome"]
    assert S.check_setup(rec) == []
    assert S.check_setup(setup(source="replay", outcome=float("nan"))) != []                 # a value that is given must still be finite
    for src in ("paper", "shadow"):
        assert S.check_setup(setup(source=src, outcome=None)) == ["missing outcome"]


# ---- the counting rules -----------------------------------------------------------------------------------------------------------------------
def test_a_setup_counts_once_in_the_week_it_became_known_and_the_weeks_start_on_monday():
    recs = [setup(1, labelled_at=f"2026-10-30T15:30:00{TZ}"),                       # Friday of the week of Mon 26 Oct
            setup(2, source="replay", outcome=None, ts=f"2026-10-23T10:00:00{TZ}", session="2026-10-23", labelled_at=f"2026-10-25T10:00:00{TZ}"),   # a Sunday: week of Mon 19 Oct
            setup(3, source="replay", outcome=None, labelled_at=f"2026-10-26T09:00:00{TZ}", ts=f"2026-10-26T08:00:00{TZ}", session="2026-10-26"),   # Monday 26 Oct
            setup(4, labelled_at=f"2026-11-02T10:00:00{TZ}")]                                                                                 # Monday 2 Nov
    c = S.count(recs, date(2026, 10, 28))
    assert c["week_start"] == "2026-10-26" and c["this_week"] == 2 and c["this_week_by_source"] == {"paper": 1, "replay": 1, "shadow": 0}
    assert c["by_week"] == {"2026-10-19": {"paper": 0, "replay": 1, "shadow": 0}, "2026-10-26": {"paper": 1, "replay": 1, "shadow": 0},
                            "2026-11-02": {"paper": 1, "replay": 0, "shadow": 0}}
    assert c["total"] == 4 and c["sessions"] == 3 and c["by_source"] == {"paper": 2, "replay": 2, "shadow": 0}
    assert S.week_start(date(2026, 10, 25)) == date(2026, 10, 19) and S.week_start(date(2026, 10, 26)) == date(2026, 10, 26)


def test_duplicates_count_once_and_invalid_records_are_listed_not_counted():
    recs = [setup(1), setup(1, outcome=9.0), setup(2), setup(3, outcome=float("nan")), "junk", setup(4, source="tape")]
    c = S.count(recs, date(2026, 10, 28))
    assert c["total"] == 2 and c["duplicates_ignored"] == 1 and [x["index"] for x in c["invalid"]] == [3, 4, 5]
    assert "outcome" in c["invalid"][0]["problems"][0] and c["invalid"][1]["problems"] == ["a setup record must be an object"]


def test_progress_is_against_the_three_hundred_to_five_hundred_the_entry_filter_needs():
    recs = [setup(i, ts=f"2026-10-27T10:{i % 60:02d}:00{TZ}") for i in range(150)]
    c = S.count(recs, date(2026, 10, 28))
    assert c["total"] == 150 and c["target"] == (300, 500) and c["progress_low"] == pytest.approx(0.5) and c["progress_high"] == pytest.approx(0.3)


def test_the_digest_line_says_zero_when_there_is_nothing_and_names_what_it_did_not_count():
    zero = S.digest_line([], date(2026, 10, 24))
    assert zero.startswith("Labelled setups: 0 this week (paper 0, replay 0, shadow 0); 0 in total from 0 sessions, 0% of the 300")
    line = S.digest_line([setup(1), setup(2, outcome=float("inf"))], date(2026, 10, 28))
    assert "1 this week (paper 1, replay 0, shadow 0); 1 in total from 1 sessions" in line and "1 record(s) failed validation and are not counted" in line


def test_the_records_are_read_from_journal_events_of_the_one_category():
    events = [{"category": "setup_labelled", "data": setup(1)}, {"category": "ml_prediction", "data": setup(2)}, {"category": "setup_labelled", "data": "x"},
              {"category": "setup_labelled", "data": setup(3)}, "junk", {"category": "setup_labelled"}]
    assert [r["setup_id"] for r in S.from_events(events)] == ["s1", "s3"]


def test_the_module_imports_nothing_from_the_desk():
    out = subprocess.run([sys.executable, "-c", "import sys; import quantdesk.ml.setups; print(sorted(m for m in sys.modules if m.startswith('quantdesk')))"],
                         capture_output=True, text=True, check=True).stdout
    assert out.strip() == "['quantdesk', 'quantdesk.ml', 'quantdesk.ml.setups']"


# ---- the real journal -------------------------------------------------------------------------------------------------------------------------
def make_journal(tmp_path, trades=(), decisions=(), graded=None):
    """A journal with the desk's own schema, and a learning memory file listing the graded armed keys."""
    jp = tmp_path / "journal.db"
    j = Journal(jp)
    for t in trades:
        j.db.execute("INSERT INTO trades (id, strategy, symbol, status, opened_at, closed_at, r_multiple) VALUES (?,?,?,?,?,?,?)", t)
    for d in decisions:
        j.db.execute("INSERT INTO decisions (ts, strategy, symbol, action, units, detail, context) VALUES (?,?,?,?,?,?,?)", d)
    j.commit()
    mp = tmp_path / "memory.json"
    if graded is not None:
        mp.write_text(json.dumps({"version": 1, "graded": {"news": [], "trades": [], "armed": list(graded)}}))
    return jp, mp


def test_closed_trades_with_a_finite_r_are_paper_setups_and_nothing_else_in_the_trades_table_is(tmp_path):
    trades = [("t1", "orb", "NIFTY", "closed", "2026-10-26 09:45:00+05:30", "2026-10-26 11:10:00+05:30", 1.2),
              ("t2", "orb", "NIFTY", "closed", "2026-10-26 10:00:00+05:30", "2026-10-26 10:40:00+05:30", -1.0),
              ("t3", "orb", "BANKNIFTY", "open", "2026-10-27 09:45:00+05:30", None, None),                       # still open: no label
              ("t4", "orb", "NIFTY", "closed", "2026-10-27 09:45:00+05:30", "2026-10-27 10:30:00+05:30", None),    # closed with no R: no label
              ("t5", "orb", "NIFTY", "closed", "2026-10-27 09:45:00+05:30", "2026-10-27 10:30:00+05:30", float("nan")),
              ("t6", "orb", "BANKNIFTY", "closed", "2026-10-27 09:15:00", "2026-10-27 09:50:00", 0.4)]            # a naive stamp is the desk's own clock (IST)
    jp, mp = make_journal(tmp_path, trades=trades)
    notes = []
    recs = S.from_journal(jp, mp, notes)
    assert sorted(r["setup_id"] for r in recs) == ["trade:t1", "trade:t2", "trade:t6"] and all(r["source"] == "paper" for r in recs)
    r6 = next(r for r in recs if r["setup_id"] == "trade:t6")
    assert r6["ts"].endswith("+05:30") and r6["session"] == "2026-10-27" and r6["symbol"] == "BANKNIFTY" and r6["outcome"] == 0.4
    assert all(S.check_setup(r) == [] for r in recs)
    assert any("learning memory" in n for n in notes)                                                          # no memory file: replay setups are not counted, and it says so


def test_the_digest_line_matches_the_journal(tmp_path):
    """P0.7's exit test: write known rows into a journal, and the published block counts exactly them."""
    detail = "the market reached its level: the EV gate refused it"
    decisions = [("2026-10-26 09:50:00+05:30", "orb", "NIFTY", "rejected", 0, detail, "{}"),
                 ("2026-10-26 10:20:00+05:30", "orb", "NIFTY", "rejected", 0, detail, "{}"),
                 ("2026-10-27 09:50:00+05:30", "vwap_trend", "BANKNIFTY", "rejected", 0, detail, "{}"),
                 ("2026-10-27 11:00:00+05:30", "orb", "NIFTY", "rejected", 0, "another reason entirely", "{}"),      # not an armed-level refusal
                 ("2026-10-27 12:00:00+05:30", "orb", "NIFTY", "approved", 1, "approved", "{}")]
    graded = ["2026-10-26 09:50:00+05:30|NIFTY|orb", "2026-10-27 09:50:00+05:30|BANKNIFTY|vwap_trend"]      # the memory graded two of the three refusals so far
    trades = [("t1", "orb", "NIFTY", "closed", "2026-10-26 09:45:00+05:30", "2026-10-26 11:10:00+05:30", 1.2),
              ("t2", "orb", "NIFTY", "closed", "2026-10-27 10:00:00+05:30", "2026-10-27 10:40:00+05:30", -1.0)]
    jp, mp = make_journal(tmp_path, trades=trades, decisions=decisions, graded=graded)
    b = S.block(jp, mp, date(2026, 10, 28))
    assert b["total"] == 4 and b["by_source"] == {"paper": 2, "replay": 2, "shadow": 0} and b["this_week"] == 4 and b["sessions"] == 2 and b["invalid"] == 0
    assert b["line"].startswith("Labelled setups: 4 this week (paper 2, replay 2, shadow 0); 4 in total from 2 sessions") and b["notes"] == []
    assert b["week_start"] == "2026-10-26" and b["target"] == [300, 500]
    jp2, mp2 = make_journal(tmp_path / "empty" if (tmp_path / "empty").mkdir() is None else tmp_path, graded=[])
    assert S.block(jp2, mp2, date(2026, 10, 28))["total"] == 0


def test_a_replay_setup_is_labelled_when_its_window_closes_not_when_it_was_graded(tmp_path):
    detail = "reached its level"
    jp, mp = make_journal(tmp_path, decisions=[("2026-10-30 15:00:00+05:30", "orb", "NIFTY", "rejected", 0, detail, "{}")], graded=["2026-10-30 15:00:00+05:30|NIFTY|orb"])
    (r,) = S.from_journal(jp, mp)
    assert r["ts"] == "2026-10-30T15:00:00+05:30" and r["labelled_at"] == "2026-10-30T15:45:00+05:30" and r["outcome"] is None
    assert S.count([r], date(2026, 10, 30))["by_week"] == {"2026-10-26": {"paper": 0, "replay": 1, "shadow": 0}}


def test_an_unreadable_journal_or_memory_gives_a_count_and_a_note_not_an_error(tmp_path):
    notes = []
    assert S.from_journal(tmp_path / "missing.db", tmp_path / "m.json", notes) == [] and notes == ["no journal at missing.db"]
    bad = tmp_path / "bad.db"
    bad.write_bytes(b"this is not a sqlite file at all")
    notes = []
    assert S.from_journal(bad, tmp_path / "m.json", notes) == [] and notes and "journal" in notes[0]
    jp, mp = make_journal(tmp_path / "ok" if (tmp_path / "ok").mkdir() is None else tmp_path)
    mp.write_text("{not json")
    notes = []
    S.from_journal(jp, mp, notes)
    assert any("learning memory not readable" in n for n in notes)
    b = S.block(bad, mp, date(2026, 10, 28))
    assert b["total"] == 0 and b["line"].startswith("Labelled setups: 0 this week")


def test_the_journal_is_opened_read_only(tmp_path):
    jp, mp = make_journal(tmp_path, trades=[("t1", "orb", "NIFTY", "closed", "2026-10-26 09:45:00+05:30", "2026-10-26 11:10:00+05:30", 1.0)])
    before = jp.read_bytes()
    S.block(jp, mp, date(2026, 10, 28))
    assert jp.read_bytes() == before


# ---- the published block ----------------------------------------------------------------------------------------------------------------------
def test_the_site_export_publishes_the_block_and_never_fails_the_publish(tmp_path):
    from quantdesk.web import export_site as E

    class Api:
        def __init__(self, d):
            self.d = d

        def _dir(self, account):
            return self.d
    jp, mp = make_journal(tmp_path, trades=[("t1", "orb", "NIFTY", "closed", "2026-10-26 09:45:00+05:30", "2026-10-26 11:10:00+05:30", 1.0)], graded=[])
    b = E._setups_block(Api(tmp_path), "live")
    assert b["total"] == 1 and b["line"].startswith("Labelled setups:") and "error" not in b
    boom = E._setups_block(object(), "live")                                          # an api with no _dir: the block says what went wrong
    assert boom["line"] is None and "AttributeError" in boom["error"]
