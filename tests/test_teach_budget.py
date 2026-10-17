"""The Claude credit split (llm.ClaudeBudget, intraday.llm.claude.teach_share): reads are paced on their half, teaching
spends from its own pot, both in one real-spend ledger that can never be overspent between them."""
from types import SimpleNamespace as NS

import pytest

from quantdesk.intraday import llm
from quantdesk.journal.journal import Journal
from test_llm import Cfg, Clock

KEY = "llm_claude_spend"


def usage(usd_in=0, usd_out=0):
    """A usage that prices to exactly the dollars asked (4 $/M in, 20 $/M out)."""
    return NS(input_tokens=int(usd_in / 4 * 1e6), output_tokens=int(usd_out / 20 * 1e6))


def test_reads_are_paced_on_their_half_of_what_is_left():
    whole = llm.ClaudeBudget(Cfg(), Journal(), Clock())
    half = llm.ClaudeBudget(Cfg(teach_share=0.5), Journal(), Clock())
    st = half._load()
    half._day(st)
    assert half.allowance(st, "2026-10-12") == pytest.approx(0.5 * 23.60 / 60)
    st = whole._load()
    whole._day(st)
    assert whole.allowance(st, "2026-10-12") == pytest.approx(23.60 / 60)         # no teach_share: as before


def test_the_split_applies_from_what_was_left_on_the_day_it_starts():
    j = Journal()
    # the credit as it stood on the morning of 16 Oct: $1.79 spent over 4 sessions, all before the split existed
    j.set_state(KEY, {"total_usd": 1.79, "by_day": {"2026-10-12": 0.5, "2026-10-13": 0.5, "2026-10-14": 0.4, "2026-10-15": 0.39},
                      "calls": 40, "sessions_used": 4, "day": "2026-10-15"})
    b = llm.ClaudeBudget(Cfg(teach_share=0.5), j, Clock("2026-10-16"))
    assert b.deny("read") is None                                                   # a fresh day: the first read goes ahead
    st = b._load()
    live, teach = b._pots(st, "2026-10-16")
    assert live == pytest.approx(0.5 * (23.60 - 1.79)) and teach == pytest.approx(0.5 * (23.60 - 1.79))
    assert b.allowance(st, "2026-10-16") == pytest.approx(live / 56)                # 56 sessions left, on the live half
    assert b.teach_left() == pytest.approx(teach)


def test_teaching_spends_from_its_own_pot_and_does_not_slow_the_reads():
    j = Journal()
    b = llm.ClaudeBudget(Cfg(teach_share=0.5), j, Clock())
    b.deny("read")
    before = b.allowance(b._load(), "2026-10-12")
    cost = b.charge(usage(usd_in=3.0, usd_out=2.0), "teach")
    assert cost == pytest.approx(5.0)
    st = j.get_state(KEY)
    assert st["total_usd"] == pytest.approx(5.0) and st["teach_usd"] == pytest.approx(5.0)
    assert st["by_day"] == {} and st["teach_by_day"] == {"2026-10-12": pytest.approx(5.0)}      # not the reader's spend
    assert b.allowance(b._load(), "2026-10-12") == pytest.approx(before)            # reads keep their pace
    assert b.teach_left() == pytest.approx(0.5 * 23.60 - 5.0)


def test_the_pots_never_exceed_the_credit_between_them():
    j = Journal()
    b = llm.ClaudeBudget(Cfg(teach_share=0.5, reserve_reflection=False), j, Clock())
    b.deny("read")
    pot = 0.5 * 23.60
    assert b.deny("teach", est=pot + 0.01) is not None and b.deny("teach", est=pot) is None
    b.charge(usage(usd_out=pot), "teach")                                           # the whole teaching pot, spent
    assert b.teach_left() == pytest.approx(0.0) and "teaching pot" in b.deny("teach", est=0.5)
    st = b._load()
    live, teach = b._pots(st, "2026-10-12")
    assert teach == 0.0 and live == pytest.approx(pot)                              # the reads' half is untouched
    b.charge(usage(usd_out=pot), "read")                                            # ...and now the reads' half too
    st = j.get_state(KEY)
    assert st["total_usd"] == pytest.approx(23.60) and st["closed"] is True         # hard stop at zero, nothing over
    assert b.deny("read") == "" and b.deny("teach", est=0.01) == ""
    assert sum(b._pots(b._load(), "2026-10-12")) == 0.0


def test_a_teach_pot_with_no_share_is_closed_and_a_changed_share_rebases_the_day():
    none = llm.ClaudeBudget(Cfg(), Journal(), Clock())
    assert "no pot" in none.deny("teach", est=0.1) and none.teach_left() == 0.0
    j = Journal()
    a = llm.ClaudeBudget(Cfg(teach_share=0.5), j, Clock())
    a.deny("read")
    a.charge(usage(usd_out=1.0), "teach")
    b = llm.ClaudeBudget(Cfg(teach_share=0.25), j, Clock())                         # the owner changes the share the same day
    b.deny("read")
    assert b.teach_left() == pytest.approx(0.25 * 23.60 - 1.0)                      # fixed from the day's start; spend counted
    assert j.get_state(KEY)["pots"]["share"] == 0.25


def test_the_line_shows_teaching_only_when_there_is_a_pot():
    j = Journal()
    b = llm.ClaudeBudget(Cfg(teach_share=0.5), j, Clock())
    b.deny("read")
    assert b.line().endswith("; teaching $0.00, $11.80 left in its pot")
    assert "teaching" not in llm.ClaudeBudget(Cfg(), Journal(), Clock()).line()


@pytest.mark.parametrize("bad", [None, "x", [1], {"total_usd": 1.0, "teach_usd": "abc", "teach_by_day": 4, "pots": "no"}])
def test_a_malformed_ledger_still_degrades_to_defaults_with_the_split(bad):
    j = Journal()
    j.set_state(KEY, bad)
    b = llm.ClaudeBudget(Cfg(teach_share=0.5), j, Clock())
    st = b._load()
    assert st["teach_usd"] == 0.0 and st["teach_by_day"] == {} and st["pots"] is None
    assert b.deny("teach", est=0.5) is None or isinstance(b.deny("teach", est=0.5), str)


def test_a_spent_reads_half_is_skipped_with_one_info_event_a_day_and_teaching_goes_on():
    j = Journal()
    b = llm.ClaudeBudget(Cfg(teach_share=0.5, reserve_reflection=False), j, Clock())
    b.deny("read")
    b.charge(usage(usd_out=0.5 * 23.60), "read")                                    # the reads' whole half
    assert "reads budget" in b.deny("read") and "reads budget" in b.deny("read")
    assert b.deny("teach", est=1.0) is None                                         # teaching's half is untouched
    ev = j.events()
    spent = ev[ev["message"].str.contains("reads budget")]
    assert len(spent) == 1 and spent.iloc[0]["level"] == "INFO"                     # one a day, never an error
    assert b.teach_left() == pytest.approx(0.5 * 23.60)


def test_a_spent_teaching_half_never_slows_or_stops_the_reads():
    j = Journal()
    b = llm.ClaudeBudget(Cfg(teach_share=0.5), j, Clock())
    b.deny("read")
    before = b.allowance(b._load(), "2026-10-12")
    b.charge(usage(usd_out=0.5 * 23.60), "teach")
    assert "teaching pot" in b.deny("teach", est=0.5)
    assert b.deny("read") is None and b.allowance(b._load(), "2026-10-12") == pytest.approx(before)
