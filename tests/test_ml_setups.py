"""The labelled-setup counter (quantdesk/ml/setups.py, P0.7). Design level: the records are what a later Shadow stage would write; nothing here emits them."""
from __future__ import annotations

import subprocess
import sys
from datetime import date

import pytest

from quantdesk.ml import setups as S

TZ = "+05:30"


def setup(i=1, **over):
    rec = {"setup_id": f"s{i}", "source": "shadow", "symbol": "NIFTY", "session": "2026-10-27", "ts": f"2026-10-27T10:00:00{TZ}",
           "labelled_at": f"2026-10-27T15:30:00{TZ}", "outcome": 1.5}
    rec.update(over)
    return rec


def test_a_good_record_validates_and_each_rule_fails_on_its_own():
    assert S.validate(setup()) == setup()
    for over, why in (({"source": "paper"}, "source"), ({"symbol": " "}, "symbol"), ({"setup_id": "bad id"}, "setup_id"), ({"setup_id": "x" * 97}, "setup_id"),
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


def test_a_setup_counts_once_in_the_week_it_became_known_and_the_weeks_start_on_monday():
    recs = [setup(1, labelled_at=f"2026-10-30T15:30:00{TZ}"),                       # Friday of the week of Mon 26 Oct
            setup(2, source="replay", ts=f"2026-10-23T10:00:00{TZ}", session="2026-10-23", labelled_at=f"2026-10-25T10:00:00{TZ}"),     # a Sunday: the week of Mon 19 Oct
            setup(3, source="replay", labelled_at=f"2026-10-26T09:00:00{TZ}", ts=f"2026-10-26T08:00:00{TZ}", session="2026-10-26"),       # Monday 26 Oct
            setup(4, labelled_at=f"2026-11-02T10:00:00{TZ}", ts=f"2026-10-27T10:00:00{TZ}")]                                              # Monday 2 Nov
    c = S.count(recs, date(2026, 10, 28))
    assert c["week_start"] == "2026-10-26" and c["this_week"] == 2 and c["this_week_by_source"] == {"shadow": 1, "replay": 1}
    assert c["by_week"] == {"2026-10-19": {"shadow": 0, "replay": 1}, "2026-10-26": {"shadow": 1, "replay": 1}, "2026-11-02": {"shadow": 1, "replay": 0}}
    assert c["total"] == 4 and c["sessions"] == 3 and S.week_start(date(2026, 10, 25)) == date(2026, 10, 19) and S.week_start(date(2026, 10, 26)) == date(2026, 10, 26)


def test_duplicates_count_once_and_invalid_records_are_listed_not_counted():
    recs = [setup(1), setup(1, outcome=9.0), setup(2), setup(3, outcome=float("nan")), "junk", setup(4, source="paper")]
    c = S.count(recs, date(2026, 10, 28))
    assert c["total"] == 2 and c["duplicates_ignored"] == 1 and [x["index"] for x in c["invalid"]] == [3, 4, 5]
    assert "outcome" in c["invalid"][0]["problems"][0] and c["invalid"][1]["problems"] == ["a setup record must be an object"]


def test_progress_is_against_the_three_hundred_to_five_hundred_the_entry_filter_needs():
    recs = [setup(i, ts=f"2026-10-27T10:{i % 60:02d}:00{TZ}") for i in range(150)]
    c = S.count(recs, date(2026, 10, 28))
    assert c["total"] == 150 and c["target"] == (300, 500) and c["progress_low"] == pytest.approx(0.5) and c["progress_high"] == pytest.approx(0.3)


def test_the_digest_line_says_zero_while_nothing_produces_setups_and_names_what_it_did_not_count():
    zero = S.digest_line([], date(2026, 10, 24))
    assert zero.startswith("Labelled setups: 0 this week (shadow 0, replay 0); 0 in total from 0 sessions, 0% of the 300")
    line = S.digest_line([setup(1), setup(2, outcome=float("inf"))], date(2026, 10, 28))
    assert "1 this week (shadow 1, replay 0); 1 in total from 1 sessions" in line and "1 record(s) failed validation and are not counted" in line


def test_the_records_are_read_from_journal_events_of_the_one_category():
    events = [{"category": "setup_labelled", "data": setup(1)}, {"category": "ml_prediction", "data": setup(2)}, {"category": "setup_labelled", "data": "x"},
              {"category": "setup_labelled", "data": setup(3)}, "junk", {"category": "setup_labelled"}]
    assert [r["setup_id"] for r in S.from_events(events)] == ["s1", "s3"]
    assert S.CATEGORY == "setup_labelled"


def test_the_module_imports_nothing_from_the_desk():
    out = subprocess.run([sys.executable, "-c", "import sys; import quantdesk.ml.setups; print(sorted(m for m in sys.modules if m.startswith('quantdesk')))"],
                         capture_output=True, text=True, check=True).stdout
    assert out.strip() == "['quantdesk', 'quantdesk.ml', 'quantdesk.ml.setups']"
